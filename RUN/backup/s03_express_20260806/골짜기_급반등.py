# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 신호기.

주문·브로커 import가 없는 순수 신호 프로그램이다. 체결대금 하한이나
완성 1분봉을 기다리지 않고 다음 사건 순서를 요구한다.

    전일종가 대비 -4% 이하 급락
    -> 매도 체결이 이어져도 가격충격이 둔화되는 흡수
    -> 최우선호가 OFI와 microprice가 위로 전환

신저가, 누계 역행, 낡거나 빠진 최우선호가는 fail-closed/reset 처리한다.
종목별 신호는 거래일에 최대 두 번 발행하며, 두 번째는 첫 신호 뒤 신저가로 조건이 새로 형성돼야 한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_signal_contract_v1 import (
    ALGORITHM,
    FIRST_REBOUND_PCT,
    INTRADAY_CRASH_LANE,
    MIN_HIGHER_LOW_PCT,
    MIN_OBSERVE_SEC,
    MIN_PULLBACK_PCT,
    MIN_SECOND_REBOUND_PCT,
    OPEN_ARM_DROP_PCT,
    OPEN_HANDOFF_DROP_PCT,
    OPEN_MAX_REBOUND_PCT,
    OPEN_CRASH_LANE,
    OPEN_MIN_REBOUND_PCT,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
)
from strategy_03_intraday_rebound_v1 import IntradayReboundDetector

KST = ZoneInfo("Asia/Seoul")
# ★[2026-07-31 친구님 지시 "3번 급락이 9시 2분부터 하자 · 매수 매도는 똑같이"]
#   09:00 → 09:02. 급락은 개장 직후에 몰리는데(7/31 실측: 고저폭 30종목의 저점 25개가
#   09:10 이전 형성) 09:00 정각은 시가 자체가 아직 안 잡혀 판정이 불안정하다.
#   2번(09:06~14:20 늘어지는 하락)과 역할을 나눈다 — 아침 급락은 3번, 낮은 2번.
#   매수 조건·매도는 그대로 둔다(지시대로 시각만 변경).
ENTRY_START = time(9, 2)
ENTRY_END = time(14, 30)
# ★[2026-07-31 친구님 지시 "시간창을 9시부터"] 09:20 → 09:00.
#   실측(7/31): 당일 급락·저점이 전부 09:00~09:11 에 형성됐는데 이 레인이 09:20에
#   열려 전량 놓쳤다(ENTRY_TIME_CLOSED). 7/28 마지막 신호도 급락 순간에만 창이
#   쌓이는 구조라, 레인이 닫힌 시간의 급락은 원천적으로 못 잡는다.
#   ⚠ 09:00~09:20 은 OPEN_CRASH 레인과 겹친다 — 알고리즘이 다르고(흡수 vs 낙폭반등)
#     종목당 일일 2회 제한이 그대로라 중복 폭주는 없다.
#   되돌리기: backup\골짜기_급반등_20260731_lane0900.py +
#             backup\strategy_03_signal_contract_v1_20260731_lane0900.py 복원(쌍으로).
# ★[2026-07-31 친구님 지시 "하나는 9시 21분부터 적용을 해"] 09:00 → 09:21.
#   장초 레인(09:02~09:20)과 겹치던 구간을 없앤다 — 종전에는 09:00~09:20 동안
#   두 레인이 같은 종목을 동시에 보고 있었다(신호 파일 표시는 09:20-14:30 인데
#   실제 코드는 09:00 이라 표시와 실제가 어긋나 있었다).
#   친구님 설명 = 이 레인은 "3분봉 2개가 1자처럼 급속도로 올라가는 것,
#   음봉 다음 바로 양봉 2개가 최대한 커지는 것"을 잡는 장치.
# ★[2026-08-01 친구님 지시 "9시 20분대 1분 틈도 메꿔줘"] 09:21 → 09:20.
#   장초 레인은 09:20 직전(< 09:20)에 끝나므로 09:20:00~09:20:59 는 어느 레인도
#   안 보는 사각이었다. 09:20 시작이면 겹침 없이 정확히 이어진다.
#   계약서(strategy_03_signal_contract_v1)와 쌍으로 수정.
#   롤백: backup\골짜기_급반등_20260801_gapclose.py 복원(계약서 백업과 쌍으로).
INTRADAY_ENTRY_START = time(9, 20)
INTRADAY_ENTRY_END = time(14, 30)
SIGNAL_PROCESS_END = time(14, 31)


@dataclass(frozen=True)
class RapidReboundConfig:
    arm_drop_pct: float = OPEN_ARM_DROP_PCT
    handoff_drop_pct: float = OPEN_HANDOFF_DROP_PCT
    first_rebound_pct: float = FIRST_REBOUND_PCT
    chase_cap_pct: float = OPEN_MAX_REBOUND_PCT
    entry_floor_pct: float = OPEN_MIN_REBOUND_PCT
    pullback_min_pct: float = MIN_PULLBACK_PCT
    higher_low_buffer_pct: float = MIN_HIGHER_LOW_PCT
    second_rebound_pct: float = MIN_SECOND_REBOUND_PCT
    flow_accel_window_sec: float = 10.0
    observe_sec: float = MIN_OBSERVE_SEC
    observe_max_sec: float = 720.0
    rearm_deeper_pct: float = 1.0
    max_signals_per_code: int = 2

    def __post_init__(self) -> None:
        if not self.handoff_drop_pct < self.arm_drop_pct < 0:
            raise ValueError("drop range must satisfy handoff < arm < 0")
        if self.chase_cap_pct <= self.first_rebound_pct:
            raise ValueError("chase cap must exceed first rebound")
        if self.entry_floor_pct > self.first_rebound_pct:
            raise ValueError("entry floor must not exceed first rebound")
        if self.pullback_min_pct <= 0 or self.second_rebound_pct <= 0:
            raise ValueError("retest thresholds must be positive")
        if not 0 < self.higher_low_buffer_pct < self.first_rebound_pct:
            raise ValueError("higher-low buffer must sit below first rebound")
        if self.flow_accel_window_sec < 5:
            raise ValueError("flow acceleration window must be at least 5 seconds")
        if self.observe_sec < 0 or self.observe_max_sec < self.observe_sec:
            raise ValueError("observe windows are inconsistent")
        if not 0 <= self.rearm_deeper_pct <= 5:
            raise ValueError("invalid rearm depth")
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 03 requires exactly two opportunities per code")


@dataclass(frozen=True)
class PriorProfile:
    previous_close: float
    previous_value: float = 0.0
    previous_range_pct: float = 0.0
    previous_close_position: float = 0.0


@dataclass(frozen=True)
class MicroPoint:
    ts: datetime
    price: float
    buy_money_cum: float
    sell_money_cum: float
    open_price: float = 0.0
    # ★[MIN-LOW 2026-08-03 친구님 지시] 신저점은 틱이 아니라 1분봉 저가로 판정한다.
    #   진행 중인 봉의 저가(돈맥_1분봉.json 의 l)를 쓴다 — 완성봉을 기다리면 최대 60초가
    #   밀려, 방금 걷어낸 관찰 60초를 다시 넣는 꼴이 된다.
    #   0 이면(자료 없음) 종전처럼 틱 가격으로 판정한다 — 되돌림 안전.
    minute_low: float = 0.0
    che_str: float = 0.0
    buy_volume_cum: float = 0.0
    sell_volume_cum: float = 0.0
    best_ask_px: float = 0.0
    best_bid_px: float = 0.0
    best_ask_qty: float = 0.0
    best_bid_qty: float = 0.0

    @property
    def book_valid(self) -> bool:
        return (
            self.best_ask_px > self.best_bid_px > 0
            and self.best_ask_qty > 0
            and self.best_bid_qty > 0
        )

    @property
    def spread(self) -> float:
        return self.best_ask_px - self.best_bid_px if self.book_valid else 0.0


@dataclass
class FormingMinute:
    key: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0

    def update(self, point: MicroPoint) -> None:
        key = point.ts.strftime("%Y%m%d%H%M")
        if key != self.key:
            self.key = key
            self.open = self.high = self.low = self.close = point.price
            return
        self.high = max(self.high, point.price)
        self.low = min(self.low, point.price)
        self.close = point.price

    def metrics(self) -> dict[str, Any]:
        if self.high <= self.low or self.open <= 0:
            return {
                "forming_1m_lower_wick_pct": 0.0,
                "forming_1m_lower_gt_upper": False,
            }
        lower = min(self.open, self.close) - self.low
        upper = self.high - max(self.open, self.close)
        span = self.high - self.low
        return {
            "forming_1m_lower_wick_pct": round(lower / span * 100.0, 2),
            "forming_1m_lower_gt_upper": lower > upper,
        }


@dataclass
class DetectorState:
    last: MicroPoint | None = None
    armed: bool = False
    phase: str = "IDLE"
    handoff_to_s06: bool = False
    emitted: bool = False
    emission_count: int = 0
    low_price: float = 0.0
    low_ts: datetime | None = None
    reset_buy_money: float = 0.0
    reset_sell_money: float = 0.0
    dead_low: float = 0.0
    reset_steps: int = 0
    observe_since: datetime | None = None
    first_rebound_peak: float = 0.0
    pullback_seen: bool = False
    pullback_low: float = 0.0
    pre_buy_rate: float = -1.0
    pre_sell_rate: float = -1.0
    # ★[SPEED-GATE 2026-08-03 친구님 지시] 저점 후 매수속도가 매도속도를 넘은 적이 있는가.
    #   넘으면 True, 이후 매도가 다시 이기면 False 로 되돌려 재확인을 요구한다.
    speed_flip_seen: bool = False
    flow_points: list[MicroPoint] = field(default_factory=list)
    minute: FormingMinute = field(default_factory=FormingMinute)


def microprice(point: MicroPoint) -> float | None:
    if not point.book_valid:
        return None
    total = point.best_bid_qty + point.best_ask_qty
    return (
        point.best_ask_px * point.best_bid_qty
        + point.best_bid_px * point.best_ask_qty
    ) / total


def order_flow_imbalance(previous: MicroPoint, current: MicroPoint) -> float | None:
    """Cont-Kukanov-Stoikov 최우선호가 OFI의 단일 이벤트 값."""
    if not previous.book_valid or not current.book_valid:
        return None
    bid = (
        (current.best_bid_qty if current.best_bid_px >= previous.best_bid_px else 0.0)
        - (previous.best_bid_qty if current.best_bid_px <= previous.best_bid_px else 0.0)
    )
    ask = (
        -(current.best_ask_qty if current.best_ask_px <= previous.best_ask_px else 0.0)
        + (previous.best_ask_qty if current.best_ask_px >= previous.best_ask_px else 0.0)
    )
    return bid + ask


def sell_impact_bps_per_million(
    previous: MicroPoint,
    current: MicroPoint,
) -> float | None:
    sell_delta = current.sell_money_cum - previous.sell_money_cum
    if sell_delta <= 0 or previous.price <= 0:
        return None
    fall_bps = max(0.0, (previous.price - current.price) / previous.price * 10_000.0)
    return fall_bps / (sell_delta / 1_000_000.0)


class RapidReboundDetector:
    def __init__(self, config: RapidReboundConfig | None = None) -> None:
        self.config = config or RapidReboundConfig()
        self.state = DetectorState()

    def restore_emitted(self, sequence: int = 1, anchor_low: float = 0.0) -> None:
        self.state.emitted = True
        self.state.emission_count = max(self.state.emission_count, int(sequence or 1))
        if anchor_low > 0:
            self.state.low_price = anchor_low
            self.state.dead_low = anchor_low * (1.0 - self.config.rearm_deeper_pct / 100.0)

    def restore_handoff_to_s06(self) -> None:
        self.state.handoff_to_s06 = True

    def _clear_retest(self) -> None:
        state = self.state
        state.observe_since = None
        state.first_rebound_peak = 0.0
        state.pullback_seen = False
        state.pullback_low = 0.0
        state.speed_flip_seen = False

    def _record_flow(self, point: MicroPoint) -> None:
        points = self.state.flow_points
        if points and (point.buy_money_cum < points[-1].buy_money_cum or point.sell_money_cum < points[-1].sell_money_cum):
            points.clear()
        points.append(point)
        cutoff = point.ts.timestamp() - 360.0
        self.state.flow_points = [row for row in points if row.ts.timestamp() >= cutoff]

    def _pre_rates(self, point: MicroPoint) -> tuple[float, float]:
        window = [row for row in self.state.flow_points if 0 <= (point.ts - row.ts).total_seconds() <= 180.0]
        if len(window) < 2:
            return -1.0, -1.0
        span = (window[-1].ts - window[0].ts).total_seconds()
        if span < 30.0:
            return -1.0, -1.0
        return (
            max(0.0, window[-1].buy_money_cum - window[0].buy_money_cum) / span,
            max(0.0, window[-1].sell_money_cum - window[0].sell_money_cum) / span,
        )

    def _flow_metrics(self, point: MicroPoint) -> dict[str, Any]:
        state = self.state
        out: dict[str, Any] = {
            "dip_buy_sell_ratio": "", "dip_flow_obs_sec": "",
            "pre_buy_rate": "", "pre_sell_rate": "",
            "post_buy_rate": "", "post_sell_rate": "", "flow_flip": "",
        }
        if state.low_ts is None:
            return out
        d_buy = point.buy_money_cum - state.reset_buy_money
        d_sell = point.sell_money_cum - state.reset_sell_money
        if min(d_buy, d_sell) < 0:
            return out
        elapsed = max(1.0, (point.ts - state.low_ts).total_seconds())
        post_buy, post_sell = d_buy / elapsed, d_sell / elapsed
        out.update({
            "dip_buy_sell_ratio": round(d_buy / d_sell, 3) if d_sell > 0 else "",
            "dip_flow_obs_sec": round(elapsed, 1),
            "post_buy_rate": round(post_buy, 1), "post_sell_rate": round(post_sell, 1),
        })
        if state.pre_buy_rate >= 0 and state.pre_sell_rate >= 0:
            out["pre_buy_rate"] = round(state.pre_buy_rate, 1)
            out["pre_sell_rate"] = round(state.pre_sell_rate, 1)
            if (state.pre_buy_rate + state.pre_sell_rate) > 0 and (post_buy + post_sell) > 0:
                out["flow_flip"] = "O" if (state.pre_sell_rate > state.pre_buy_rate and post_buy > post_sell) else "X"
        return out

    def _flow_acceleration(self, point: MicroPoint) -> dict[str, Any]:
        out: dict[str, Any] = {
            "previous_buy_rate_10s": "", "recent_buy_rate_10s": "",
            "previous_sell_rate_10s": "", "recent_sell_rate_10s": "", "flow_accel": "",
        }
        flow = self.state.flow_points
        if len(flow) < 3:
            return out
        window = self.config.flow_accel_window_sec
        end, end_epoch = flow[-1], flow[-1].ts.timestamp()
        tolerance = max(3.0, window * 0.4)

        def point_at_or_before(target: float) -> MicroPoint | None:
            for row in reversed(flow):
                if row.ts.timestamp() <= target:
                    return row
            return None

        middle_target, start_target = end_epoch - window, end_epoch - 2.0 * window
        middle, start = point_at_or_before(middle_target), point_at_or_before(start_target)
        if middle is None or start is None:
            return out
        if middle_target - middle.ts.timestamp() > tolerance or start_target - start.ts.timestamp() > tolerance:
            return out
        previous_span = (middle.ts - start.ts).total_seconds()
        recent_span = (end.ts - middle.ts).total_seconds()
        if min(previous_span, recent_span) < window * 0.6:
            return out
        previous_buy = max(0.0, middle.buy_money_cum - start.buy_money_cum) / previous_span
        previous_sell = max(0.0, middle.sell_money_cum - start.sell_money_cum) / previous_span
        recent_buy = max(0.0, end.buy_money_cum - middle.buy_money_cum) / recent_span
        recent_sell = max(0.0, end.sell_money_cum - middle.sell_money_cum) / recent_span
        out.update({
            "previous_buy_rate_10s": round(previous_buy, 1), "recent_buy_rate_10s": round(recent_buy, 1),
            "previous_sell_rate_10s": round(previous_sell, 1), "recent_sell_rate_10s": round(recent_sell, 1),
            "flow_accel": "O" if (recent_buy > previous_buy and recent_buy > recent_sell and recent_sell <= previous_sell) else "X",
        })
        return out

    def _row(self, action: str, reason: str, point: MicroPoint, profile: PriorProfile) -> dict[str, Any]:
        state = self.state
        previous_drop_pct = (point.price / profile.previous_close - 1.0) * 100.0 if profile.previous_close > 0 else 0.0
        open_drop_pct = (point.price / point.open_price - 1.0) * 100.0 if point.open_price > 0 else 0.0
        row: dict[str, Any] = {
            "ts": point.ts.isoformat(timespec="milliseconds"), "action": action, "reason": reason,
            "price": point.price, "open_price": point.open_price,
            "drop_from_open_pct": round(open_drop_pct, 4),
            "drop_from_previous_close_pct": round(previous_drop_pct, 4),
            "algorithm": ALGORITHM, "mode": SIGNAL_MODE, "phase": state.phase,
            "dip_low_reset_steps": state.reset_steps,
            "current_buy_money_cum": point.buy_money_cum,
            "current_sell_money_cum": point.sell_money_cum,
        }
        if state.low_price > 0:
            rebound = (point.price / state.low_price - 1.0) * 100.0
            first_rebound = (state.first_rebound_peak / state.low_price - 1.0) * 100.0 if state.first_rebound_peak > 0 else 0.0
            observe_sec = max(0.0, (point.ts - state.observe_since).total_seconds()) if state.observe_since else 0.0
            pullback_depth = (state.first_rebound_peak / state.pullback_low - 1.0) * 100.0 if state.first_rebound_peak > 0 and state.pullback_low > 0 else 0.0
            higher_low = (state.pullback_low / state.low_price - 1.0) * 100.0 if state.pullback_low > 0 else 0.0
            second_rebound = (point.price / state.pullback_low - 1.0) * 100.0 if state.pullback_low > 0 else 0.0
            row.update({
                "anchor_low": state.low_price,
                "anchor_low_ts": state.low_ts.isoformat(timespec="milliseconds") if state.low_ts else "",
                "rebound_pct": round(rebound, 4), "first_rebound_pct": round(first_rebound, 4),
                "observe_sec": round(observe_sec, 3), "first_rebound_peak": state.first_rebound_peak,
                "pullback_low": state.pullback_low, "pullback_depth_pct": round(pullback_depth, 4),
                "higher_low_pct": round(higher_low, 4), "second_rebound_pct": round(second_rebound, 4),
                "dead_low": round(state.dead_low, 4),
                "buy_money_since_low": round(max(0.0, point.buy_money_cum - state.reset_buy_money), 2),
                "sell_money_since_low": round(max(0.0, point.sell_money_cum - state.reset_sell_money), 2),
            })
        row.update(self._flow_metrics(point))
        row.update(self._flow_acceleration(point))
        mp = microprice(point)
        if mp is not None:
            midpoint = (point.best_ask_px + point.best_bid_px) / 2.0
            row.update({
                "best_ask_px": point.best_ask_px, "best_bid_px": point.best_bid_px,
                "best_ask_qty": point.best_ask_qty, "best_bid_qty": point.best_bid_qty,
                "microprice": round(mp, 4), "microprice_edge_bps": round((mp / midpoint - 1.0) * 10_000.0, 4),
                "spread_bps": round(point.spread / midpoint * 10_000.0, 4),
            })
        row.update(state.minute.metrics())
        row.update({
            "previous_value": profile.previous_value,
            "previous_range_pct": round(profile.previous_range_pct, 4),
            "previous_close_position": round(profile.previous_close_position, 4),
        })
        return row

    @staticmethod
    def _probe_low(point: MicroPoint) -> float:
        """★[MIN-LOW 2026-08-03] 신저점 판정에 쓸 값 — 진행 중 1분봉 저가 우선.

        자료가 없으면(0) 종전대로 틱 가격을 쓴다. 되돌림 안전.
        """
        return point.minute_low if point.minute_low > 0 else point.price

    def _reset_low(self, point: MicroPoint) -> None:
        state = self.state
        if state.armed and state.low_price > 0:
            state.reset_steps += 1
        state.armed, state.phase = True, "CHASE"
        # 저점값도 1분봉 저가로 잡는다 — 틱 가격으로 잡으면 봉 저가보다 위라서
        # 반등률(저점 대비 +1.0~1.5%)이 실제보다 크게 계산된다.
        state.low_price, state.low_ts = self._probe_low(point), point.ts
        state.reset_buy_money, state.reset_sell_money = point.buy_money_cum, point.sell_money_cum
        state.dead_low = 0.0
        state.pre_buy_rate, state.pre_sell_rate = self._pre_rates(point)
        self._clear_retest()

    def _reset_cycle(self) -> None:
        old = self.state
        self.state = DetectorState(
            handoff_to_s06=old.handoff_to_s06, emitted=old.emitted,
            emission_count=old.emission_count, minute=old.minute)

    def feed(self, point: MicroPoint, profile: PriorProfile, *, allow_signal: bool) -> dict[str, Any]:
        state = self.state
        state.minute.update(point)
        previous = state.last
        if previous is not None:
            if point.ts <= previous.ts:
                return self._row("WAIT", "DUPLICATE_OR_OLD_SNAPSHOT", point, profile)
            if point.buy_money_cum < previous.buy_money_cum or point.sell_money_cum < previous.sell_money_cum:
                self._reset_cycle()
                self.state.minute.update(point)
                self.state.flow_points = [point]
                self.state.last = point
                return self._row("WAIT", "CUMULATIVE_REVERSE_RESET", point, profile)
        if profile.previous_close <= 0 or point.price <= 0:
            state.last = point
            return self._row("WAIT", "INVALID_PRICE_CONTEXT", point, profile)
        if point.open_price <= 0:
            state.last = point
            return self._row("WAIT", "OPEN_PRICE_MISSING", point, profile)
        self._record_flow(point)
        arm_price = point.open_price * (1.0 + self.config.arm_drop_pct / 100.0)
        handoff_price = point.open_price * (1.0 + self.config.handoff_drop_pct / 100.0)
        if state.handoff_to_s06:
            state.last = point
            return self._row("DONE", "OPEN_DROP_LE_8PCT_HANDOFF_S06", point, profile)
        if point.price <= handoff_price:
            state.armed, state.phase, state.handoff_to_s06, state.last = False, "DONE", True, point
            return self._row("DONE", "OPEN_DROP_LE_8PCT_HANDOFF_S06", point, profile)
        if not allow_signal:
            state.last = point
            return self._row("WAIT", "ENTRY_TIME_CLOSED", point, profile)
        if state.emitted:
            if state.emission_count >= self.config.max_signals_per_code:
                state.last = point
                return self._row("DONE", "CODE_DAILY_ENTRY_LIMIT_2", point, profile)
            rearm_low = state.dead_low or state.low_price * (1.0 - self.config.rearm_deeper_pct / 100.0)
            if point.price >= rearm_low:
                state.last = point
                return self._row("DONE", "SECOND_CHANCE_REQUIRES_1PCT_DEEPER_LOW", point, profile)
            state.emitted = False
            self._reset_low(point)
            state.last = point
            return self._row("RESET", "SECOND_CHANCE_DEEPER_LOW_RESET", point, profile)
        if not state.armed:
            if point.price > arm_price:
                state.last = point
                return self._row("WAIT", "OPEN_DROP_GT_4PCT", point, profile)
            self._reset_low(point)
            state.last = point
            return self._row("ARMED", "OPEN_DROP_4_TO_8PCT_STAIRCASE_START", point, profile)
        # ★[MIN-LOW 2026-08-03 친구님 지시] 신저점은 1분봉 저가로 판정한다.
        #   틱 하나가 순간적으로 찍고 올라와도 계단이 흔들리지 않는다.
        if self._probe_low(point) < state.low_price:
            self._reset_low(point)
            state.last = point
            return self._row("RESET", "NEW_LOW_STAIRCASE_RESET", point, profile)
        rebound_floor = state.low_price * (1.0 + self.config.first_rebound_pct / 100.0)
        chase_ceiling = state.low_price * (1.0 + self.config.chase_cap_pct / 100.0)
        entry_floor = state.low_price * (1.0 + self.config.entry_floor_pct / 100.0)
        higher_low_floor = state.low_price * (1.0 + self.config.higher_low_buffer_pct / 100.0)
        if state.phase == "CHASE":
            if state.dead_low > 0 and state.low_price >= state.dead_low:
                state.last = point
                return self._row("WAIT", "GIVEUP_WAIT_NEW_LOW", point, profile)
            if point.price > chase_ceiling:
                state.dead_low, state.last = state.low_price, point
                return self._row("WAIT", "ABOVE_CHASE_CAP", point, profile)
            if point.price >= rebound_floor:
                state.phase, state.observe_since = "OBSERVE", point.ts
                state.first_rebound_peak, state.pullback_seen, state.pullback_low = point.price, False, 0.0
                state.last = point
                return self._row("OBSERVE", "FIRST_REBOUND_CONFIRMED", point, profile)
            state.last = point
            return self._row("WAIT", "STAIRCASE_CHASING_LOW", point, profile)
        if state.first_rebound_peak <= 0 or state.observe_since is None:
            state.phase = "CHASE"
            self._clear_retest()
            state.last = point
            return self._row("RESET", "RETEST_STATE_INVALID_RESET", point, profile)
        if point.price > chase_ceiling:
            state.dead_low, state.phase = state.low_price, "CHASE"
            self._clear_retest()
            state.last = point
            return self._row("WAIT", "ABOVE_CHASE_CAP_IN_OBSERVE", point, profile)
        elapsed = (point.ts - state.observe_since).total_seconds()
        if elapsed > self.config.observe_max_sec:
            state.dead_low, state.phase = state.low_price, "CHASE"
            self._clear_retest()
            state.last = point
            return self._row("WAIT", "OBSERVE_TIMEOUT", point, profile)
        # ★[2026-08-03] 계단 재테스트 4단계는 그대로 유지한다 — 신저점 추적과 재테스트가
        #   "진짜 저점이냐"를 가리는 핵심이라 버리지 않는다. 매수구간을 +1.0~+1.5% 로
        #   좁혀도 1차반등 문턱만 1.0% 로 낮추면 전부 들어간다:
        #     저점 100 → 1차반등 101.0 → 눌림 100.6(더높은저점 100.3 초과) → 2차반등 101.1
        #     → 매수구간 101.0~101.5 안.
        if not state.pullback_seen:
            state.first_rebound_peak = max(state.first_rebound_peak, point.price)
            pullback_trigger = state.first_rebound_peak * (1.0 - self.config.pullback_min_pct / 100.0)
            if point.price <= pullback_trigger:
                if point.price < higher_low_floor:
                    state.phase = "CHASE"
                    self._clear_retest()
                    state.last = point
                    return self._row("RESET", "PULLBACK_BELOW_HIGHER_LOW_FLOOR", point, profile)
                state.pullback_seen, state.pullback_low = True, point.price
        else:
            if point.price < higher_low_floor:
                state.phase = "CHASE"
                self._clear_retest()
                state.last = point
                return self._row("RESET", "SECOND_LOW_BROKE_FLOOR", point, profile)
            state.pullback_low = min(state.pullback_low, point.price)
        # ★[SPEED-GATE 2026-08-03 친구님 지시] 시간 관찰(60초)을 속도 감시로 교체.
        #   왜: 8/3 실전에서 계단이 16분에 3~4개씩 생기는데 60초를 채우는 동안 가격이
        #   매수 상한 위로 달아나 ABOVE_CHASE_CAP_IN_OBSERVE 로 죽었다. 감시창을 시간이
        #   아니라 "저점 +1.0~+1.5% 구간"으로 두면 급한 반등도 느린 반등도 같은 잣대가 된다.
        #   판정: 저점 후 매수속도 > 매도속도 = 살 시간. 매도가 다시 이기면 이 저점은 버리고
        #   신저점 추적으로 되돌아간다(가짜 반등에 물리지 않는다).
        #   ⚠️저점 후 속도(post_*)는 저점 시점 누적값 하나만 있으면 계산된다 — 8/3 에 흐름
        #   자료의 99%를 비게 만든 pre_rate(저점 전 180초)·flow_accel(10초 구간 2개) 의존이
        #   없다. 그래서 자료 부재로 죽지 않는다.
        #   flow_flip·flow_accel 은 계속 기록되지만 더는 관문이 아니다(fail-closed 해제).
        #   롤백: backup\골짜기_급반등_20260803_speedgate.py 복원 + 신호기 재기동
        flow, acceleration = self._flow_metrics(point), self._flow_acceleration(point)
        post_buy, post_sell = flow.get("post_buy_rate"), flow.get("post_sell_rate")
        if post_buy == "" or post_sell == "":
            state.last = point
            return self._row("WAIT", "NO_POST_FLOW_DATA", point, profile)
        if post_buy > post_sell:
            state.speed_flip_seen = True
        elif state.speed_flip_seen:
            # 매수 우위였다가 매도가 다시 이겼다 = 가짜 반등. 이 저점을 버리고 신저점을 찾는다.
            state.dead_low, state.phase = state.low_price, "CHASE"
            self._clear_retest()
            state.last = point
            return self._row("WAIT", "SELL_SPEED_RESTRENGTHENED", point, profile)
        failures: list[str] = []
        if not state.speed_flip_seen:
            failures.append("NO_BUY_SPEED_LEAD")
        if not state.pullback_seen or state.pullback_low <= 0:
            failures.append("NO_VALID_PULLBACK")
        elif point.price < state.pullback_low * (1.0 + self.config.second_rebound_pct / 100.0):
            failures.append("NO_SECOND_REBOUND")
        if point.price < entry_floor:
            failures.append("PRICE_BELOW_ENTRY_FLOOR")
        if point.price > arm_price:
            failures.append("PRICE_OUTSIDE_S03_4_TO_8PCT_BAND")
        # ★[SPEED-GATE 2026-08-03] flow_flip·flow_accel 은 기록만 한다(위 주석 참조).
        #   둘 다 저점 '전' 자료나 10초 구간 2개가 필요해 8/3 에 99%가 빈 값이었고,
        #   fail-closed 라 3번이 하루 종일 한 건도 못 샀다. 판정은 저점 후 속도로 한다.
        if failures:
            state.last = point
            return self._row("WAIT", ",".join(failures), point, profile)
        state.emitted, state.emission_count = True, state.emission_count + 1
        state.dead_low = state.low_price * (1.0 - self.config.rearm_deeper_pct / 100.0)
        state.last = point
        return self._row(
            # ★[SPEED-GATE 2026-08-03] 사유 문구에서 60S 를 뺐다 — 시간 관찰을 없앴는데
            #   로그가 60초를 지켰다고 말하면 나중에 판독이 거짓말을 읽는다.
            "BUY_READY",
            "S06_STAIRCASE+PULLBACK+HIGHER_LOW+SECOND_REBOUND+BUY_SPEED_LEAD",
            point, profile)

@dataclass(frozen=True)
class SignalConfig:
    watch_path: Path = Path(os.environ.get(
        "S03_WATCH", r"C:\stock_bot\IPC\micro_watch_valley.json"))
    shared_watch_path: Path = Path(os.environ.get(
        "S03_SHARED_WATCH",
        r"C:\stock_bot\IPC\micro_watch_strategy_shared.json"))
    minute_path: Path = Path(os.environ.get(
        "S03_MINUTE_PATH",
        r"C:\stock_bot\data\돈맥_1분봉.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S03_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    eod_path: Path = Path(os.environ.get(
        "S03_EOD", r"C:\stock_bot\data\eod_daily_bars.csv"))
    names_path: Path = Path(os.environ.get(
        "S03_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S03_OUTPUT", r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json"))
    event_dir: Path = Path(os.environ.get(
        "S03_EVENT_DIR", r"C:\stock_bot\data\strategy_03_골짜기_급반등_v1"))
    loop_sec: float = float(os.environ.get("S03_LOOP_SEC", "1"))
    max_snapshot_age_sec: float = float(os.environ.get(
        "S03_SNAPSHOT_MAX_AGE_SEC", "4"))
    min_price: float = float(os.environ.get("S03_MIN_PRICE", "10000"))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        first = path.read_bytes()
        time_module.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any, now: datetime) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)
    return parsed


def _name_map(payload: Mapping[str, Any]) -> Dict[str, str]:
    raw = payload.get("map", payload)
    return {str(code).zfill(6): str(name) for code, name in raw.items()}

def _minute_opens(
    payload: Mapping[str, Any],
    today: str,
) -> dict[str, float]:
    if str(payload.get("ts") or "").replace("-", "")[:8] != today:
        return {}
    return {
        str(code).zfill(6): open_price
        for code, row in (payload.get("m") or {}).items()
        if (open_price := _number((row or {}).get("op"))) > 0
    }


def _minute_lows(
    payload: Mapping[str, Any],
    today: str,
) -> dict[str, float]:
    """★[MIN-LOW 2026-08-03] 진행 중 1분봉의 저가. 신저점(계단) 판정 전용.

    돈맥_1분봉.json 의 l 은 그 분 봉이 시작된 뒤의 최저 관측가다(deep_bottom_signal_recorder
    가 매 틱 갱신). 틱 하나가 순간적으로 찍고 올라와도 그 분 안에서는 저가로 남아,
    틱 잡음으로 계단이 흔들리는 것을 막는다.
    """
    if str(payload.get("ts") or "").replace("-", "")[:8] != today:
        return {}
    return {
        str(code).zfill(6): low
        for code, row in (payload.get("m") or {}).items()
        if (low := _number((row or {}).get("l"))) > 0
    }


def load_prior_profiles(
    path: Path,
    *,
    source_date: str,
    codes: set[str],
) -> dict[str, PriorProfile]:
    output: dict[str, PriorProfile] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = str(row.get("code") or "").zfill(6)
                if code not in codes or str(row.get("date") or "") != source_date:
                    continue
                op = _number(row.get("open"))
                high = _number(row.get("high"))
                low = _number(row.get("low"))
                close = _number(row.get("close"))
                value = _number(row.get("value"))
                if close <= 0 or high < low:
                    continue
                span = high - low
                output[code] = PriorProfile(
                    previous_close=close,
                    previous_value=value,
                    previous_range_pct=(
                        (high - low) / op * 100.0 if op > 0 else 0.0),
                    previous_close_position=(
                        (close - low) / span if span > 0 else 0.5),
                )
    except (OSError, csv.Error):
        return {}
    return output


class RapidReboundMonitor:
    def __init__(self) -> None:
        self.open_detectors: dict[str, RapidReboundDetector] = {}
        self.intraday_detectors: dict[str, IntradayReboundDetector] = {}
        self.emission_counts: dict[str, int] = {}
        self.latest: dict[str, dict[str, Any]] = {}
        self.signals: list[dict[str, Any]] = []

    def restore(self, payload: Mapping[str, Any], today: str) -> None:
        if (
            str(payload.get("schema") or "") != SIGNAL_SCHEMA
            or str(payload.get("date") or "") != today
        ):
            return
        for raw in payload.get("signals") or []:
            if not isinstance(raw, Mapping):
                continue
            code = str(raw.get("code") or "").zfill(6)
            if len(code) != 6:
                continue
            sequence = int(raw.get("signal_sequence") or 1)
            lane = str(raw.get("entry_lane") or OPEN_CRASH_LANE)
            detector = (
                self.intraday_detectors.setdefault(code, IntradayReboundDetector())
                if lane == INTRADAY_CRASH_LANE
                else self.open_detectors.setdefault(code, RapidReboundDetector())
            )
            detector.restore_emitted(
                sequence, float(raw.get("anchor_low") or 0))
            self.emission_counts[code] = max(
                self.emission_counts.get(code, 0), sequence)
            self.signals.append(dict(raw))

        for raw in payload.get("candidates") or []:
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("reason") or "") != "OPEN_DROP_LE_8PCT_HANDOFF_S06":
                continue
            code = str(raw.get("code") or "").zfill(6)
            if len(code) != 6 or not code.isdigit():
                continue
            detector = self.open_detectors.setdefault(code, RapidReboundDetector())
            detector.restore_handoff_to_s06()

    def process_point(
        self,
        code: str,
        name: str,
        point: MicroPoint,
        profile: PriorProfile,
        *,
        allow_signal: bool,
    ) -> tuple[dict[str, Any], bool]:
        total = self.emission_counts.get(code, 0)
        lane = (
            OPEN_CRASH_LANE
            if point.ts.time() < INTRADAY_ENTRY_START
            else INTRADAY_CRASH_LANE
        )
        if lane == OPEN_CRASH_LANE:
            detector = self.open_detectors.setdefault(code, RapidReboundDetector())
            row = detector.feed(
                point, profile, allow_signal=allow_signal and total < 2)
        else:
            detector = self.intraday_detectors.setdefault(
                code, IntradayReboundDetector())
            row = detector.feed(point, allow_signal=allow_signal and total < 2)
        row.update({"code": code, "name": name, "entry_lane": lane})
        fired = row["action"] == "BUY_READY"
        if fired:
            total += 1
            self.emission_counts[code] = total
            row["signal_sequence"] = total
            row["anchor_id"] = (
                f"{row.get('anchor_low_ts')}:"
                f"{float(row.get('anchor_low') or 0):.4f}"
            )
        elif allow_signal and total >= 2:
            row.update({
                "action": "DONE",
                "reason": "CODE_DAILY_ENTRY_LIMIT_2",
            })
        return row, fired

# 신호 행에 그대로 붙여 기록한다. ★2026-07-31 부터 감시대상 제한에도 쓴다(아래 참조).
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
)
# ★[2026-07-31 친구님 지시 "전략 2하고 3부터 고저폭으로 좁혀줘"]
#   S03 감시대상을 고저폭 TOP30(hr_rank 가 실린 종목)으로 제한한다.
#   근거 — 일봉 1년 코스닥 전수(12만건·왕복비용 0.38% 차감)로 저점 진입을 근사
#   (당일 저가 +1% 매수 → 당일 종가 매도) 했을 때:
#       고저폭 조건 밖   +1.251% / 승률 58.8%
#       고저폭 연속 5일↑ +4.343% / 승률 81.4%
#     = 3.5배. 익일 고저폭이 5.87% → 14.06% 로 2.4배 크고, 다음날에도 10%↑ 로
#       움직일 확률이 12.5% → 72.0% 라서 저점 반등을 노릴 폭 자체가 다르다.
#   ⚠️같은 자료에서 "시가 매수 → 당일 종가"(급상승 추격)는 고저폭을 붙이면 오히려
#     나빠진다(-0.75% → -1.47%). 저점에서 사는 전략에만 유효한 제한이다.
#   안전장치: 고저폭 목록이 통째로 비면 제한을 걸지 않는다(fail-open).
#   롤백: setx S03_HIGH_RANGE_ONLY NO + 신호기 재기동
#         또는 backup\골짜기_급반등_20260731_hronly.py 복원
HIGH_RANGE_ONLY = os.environ.get("S03_HIGH_RANGE_ONLY", "YES").strip().upper() == "YES"


def _range_meta(*sources: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, Any] = {}
    for source in sources:
        merged.update(source.get("all_meta") or {})
    output: dict[str, dict[str, Any]] = {}
    for code, row in merged.items():
        if not isinstance(row, Mapping):
            continue
        picked = {key: row[key] for key in RANGE_KEYS if row.get(key) is not None}
        if picked:
            output[str(code).zfill(6)] = picked
    return output


def load_live_points(
    config: SignalConfig,
    *,
    now: datetime,
    watch: Mapping[str, Any],
    profiles: Mapping[str, PriorProfile],
    opens: Mapping[str, float],
    open_codes: set[str],
    lows: Mapping[str, float] | None = None,
) -> tuple[list[tuple[str, str, MicroPoint, PriorProfile]], str]:
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "").replace("-", "")[:8] != today:
        return [], "WATCH_DATE_MISMATCH"
    codes = {str(code).zfill(6) for code in (watch.get("codes") or [])}
    # ★[2026-07-31] 고저폭 TOP30 = all_meta 에 hr_rank 가 실린 종목(위 주석 참조).
    hr_codes = {str(c).zfill(6) for c, m in (watch.get("all_meta") or {}).items()
                if isinstance(m, Mapping) and m.get("hr_rank") is not None}
    snapshot = _read_json(config.snapshot_path)
    names = _name_map(_read_json(config.names_path))
    output = []
    for code, raw in (snapshot.get("codes") or {}).items():
        code = str(code).zfill(6)
        if code not in codes or code not in profiles or not isinstance(raw, Mapping):
            continue
        # hr_codes 가 비면(고저폭 목록 실패) 제한하지 않는다(fail-open).
        if HIGH_RANGE_ONLY and hr_codes and code not in hr_codes:
            continue
        ts = _parse_dt(raw.get("ts"), now)
        if ts is None:
            continue
        if not -2 <= (now - ts).total_seconds() <= config.max_snapshot_age_sec:
            continue
        price = abs(_number(raw.get("cur")))
        buy_cum = _number(raw.get("buy_money_cum"), -1.0)
        sell_cum = _number(raw.get("sell_money_cum"), -1.0)
        # ★[OPEN-PRICE-FIX 2026-08-06 친구님 지시 "지금 문제된거 수정해"] 오늘 시가는
        #   브로커 스냅샷의 op(FID16, 8/3 배선·결측 0.1%)를 우선한다. 종전에 쓰던
        #   돈맥_1분봉의 op 는 전일 시가였다 — 8/6 실측: 049080 기가레인 돈맥 op=9790
        #   (=8/5 시가) vs 실제 오늘 시가 10,990. 9790 이 최소가 1만원 밑이라 아래
        #   min_price 관문에 걸려 그 종목이 평가에서 통째로 빠졌다(오늘 최대 낙폭
        #   -10.7% = S03 가 잡아야 할 바로 그 종목인데 08:57 이후 평가 0건).
        #   폴백은 종전 경로 그대로라 스냅샷에 op 가 없으면 동작이 종전과 같다.
        #   되돌리기: backup\골짜기_급반등_20260806_before_open_price_fix.py
        open_price = _number(raw.get("op")) or _number(opens.get(code))
        if price <= 0 or buy_cum < 0 or sell_cum < 0:
            continue
        if code in open_codes:
            if 0 < open_price < config.min_price:
                continue
        elif price < config.min_price:
            continue
        point = MicroPoint(
            ts=ts,
            price=price,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            open_price=open_price,
            minute_low=_number((lows or {}).get(code)),
            che_str=abs(_number(raw.get("che_str"))),
            buy_volume_cum=_number(raw.get("buy_vol_cum"), -1.0),
            sell_volume_cum=_number(raw.get("sell_vol_cum"), -1.0),
            best_ask_px=abs(_number(raw.get("best_ask_px"))),
            best_bid_px=abs(_number(raw.get("best_bid_px"))),
            best_ask_qty=abs(_number(raw.get("best_ask_qty"))),
            best_bid_qty=abs(_number(raw.get("best_bid_qty"))),
        )
        output.append((code, names.get(code, code), point, profiles[code]))
    return output, ("LIVE" if output else "DATA_WAIT")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★[2026-07-29 친구님 승인 "S03에도 재시도 패치"] 읽는 쪽이 파일을 잡은 순간 os.replace가
    #   WinError 5(접근거부)로 죽어 신호기 전체가 정지하는 패턴(같은 날 S05 11:29 실제 사고).
    #   내일부터 CVD 기록기가 이 신호 JSON을 3초마다 읽어 충돌 확률이 커져 선제 배선.
    #   최초 1회 + 0.2초 간격 재시도 3회. 그래도 실패면 종전대로 예외(원인 은폐 방지). 롤백: 루프 제거.
    for _attempt in range(4):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if _attempt == 3:
                raise
            time_module.sleep(0.2)


def _is_low_gauge_row(row: Mapping[str, Any]) -> bool:
    # ★[2026-08-06 친구님 지시 "계기판 3종 그림자 기록 … 테스트 한번 해보고 배선하자"]
    #   저점이 잡히는 순간(무장 ARMED · 계단 INTRADAY_NEW_LOW_RESET)만 하루 CSV 로 남긴다.
    #   신호까지 못 간 '가짜 저점'의 계기판(dip_climax_mult·dip_book_imb·dip_sell_decel_10s)도
    #   남아야 나중에 "먹힌 저점과 값이 갈리나"를 잴 수 있다(BUY_READY 는 기존 신호 CSV 에 남음).
    #   INTRADAY 레인 전용 — OPEN_CRASH 검출기는 이 계기판을 아직 계산하지 않는다.
    if str(row.get("entry_lane") or "") != INTRADAY_CRASH_LANE:
        return False
    if str(row.get("action") or "") == "ARMED":
        return True
    return str(row.get("reason") or "") == "INTRADAY_NEW_LOW_RESET"


def _append_events(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # ★[2026-07-29 친구님 승인 "열 구성 고정"] 고저폭 hr_* 메타는 TOP30 종목 행에만 붙어
    #   행마다 키가 다를 수 있다. 종전 코드(첫 행 기준 DictWriter)는 다른 키가 섞이면
    #   ValueError 로 신호기 프로세스가 죽고, 안 죽어도 열이 어긋나 기록이 오염됐다.
    #   열 = 기존 파일 헤더 ∪ 이번 배치 전체 키(등장 순서 유지). 새 열이 생기면 하루짜리
    #   작은 파일이므로 통째로 다시 써서 정렬을 맞추고, 빠진 값은 빈칸으로 둔다.
    #   읽기 실패(잠금 등) 시엔 데이터 보존 우선으로 이어쓰기만 한다. 롤백: *.bak_20260729_review23
    batch_fields = list(dict.fromkeys(key for row in rows for key in row))
    header: list[str] = []
    existing: list[dict] = []
    read_ok = True
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                header = list(reader.fieldnames or [])
                existing = list(reader)
        except (OSError, csv.Error):
            read_ok = False
    fieldnames = list(dict.fromkeys(header + batch_fields))
    if read_ok and header != fieldnames:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, restval="", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + rows)
        return
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames if read_ok else batch_fields,
            restval="", extrasaction="ignore",
        )
        writer.writerows(rows)


def _current_watch_codes(
    payload: Mapping[str, Any],
    day: str,
) -> set[str]:
    if str(payload.get("for_date") or "").replace("-", "")[:8] != day:
        return set()
    return {
        str(code).zfill(6)
        for code in (payload.get("codes") or [])
        if str(code).isdigit() and len(str(code).zfill(6)) == 6
    }


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = RapidReboundMonitor()
    monitor.restore(_read_json(config.output_path), now.strftime("%Y%m%d"))
    profile_key: tuple[Any, ...] | None = None
    profiles: dict[str, PriorProfile] = {}
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        day = now.strftime("%Y%m%d")
        open_watch = _read_json(config.watch_path)
        shared_watch = _read_json(config.shared_watch_path)
        # ★[MIN-LOW 2026-08-03] 1분봉을 한 번만 읽어 시가·저가를 함께 뽑는다(파일 I/O 동일).
        minute_payload = _read_json(config.minute_path)
        opens = _minute_opens(minute_payload, day)
        lows = _minute_lows(minute_payload, day)
        range_meta = _range_meta(open_watch, shared_watch)
        open_codes = _current_watch_codes(open_watch, day)
        intraday_codes = _current_watch_codes(shared_watch, day)
        new_profile_key = (
            str(open_watch.get("source_date") or ""),
            tuple(sorted(open_codes)),
            str(shared_watch.get("source_date") or ""),
            tuple(sorted(intraday_codes)),
        )
        if new_profile_key != profile_key:
            open_profiles = load_prior_profiles(
                config.eod_path,
                source_date=str(open_watch.get("source_date") or ""),
                codes=open_codes,
            )
            intraday_profiles = load_prior_profiles(
                config.eod_path,
                source_date=str(shared_watch.get("source_date") or ""),
                codes=intraday_codes,
            )
            profiles = {**open_profiles, **intraday_profiles}
            profile_key = new_profile_key

        union_codes = open_codes | intraday_codes
        combined_watch = {"for_date": day, "codes": sorted(union_codes)}
        points, status = load_live_points(
            config, now=now, watch=combined_watch, profiles=profiles,
            opens=opens,
            lows=lows,
            open_codes=union_codes,
        )
        open_signals: list[dict[str, Any]] = []
        intraday_signals: list[dict[str, Any]] = []
        low_gauge_rows: list[dict[str, Any]] = []  # ★[2026-08-06] 계기판 그림자
        for code, name, point, profile in points:
            row, fired = monitor.process_point(
                code,
                name,
                point,
                profile,
                allow_signal=ENTRY_START <= point.ts.time() < ENTRY_END,
            )
            row.update(range_meta.get(code) or {})
            lane = str(row.get("entry_lane") or OPEN_CRASH_LANE)
            monitor.latest[f"{lane}:{code}"] = row
            if _is_low_gauge_row(row):
                low_gauge_rows.append(dict(row))
            if fired:
                monitor.signals.append(dict(row))
                if lane == OPEN_CRASH_LANE:
                    open_signals.append(dict(row))
                else:
                    intraday_signals.append(dict(row))
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": day,
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": SIGNAL_MODE,
            "status": status,
            "entry_lanes": {
                OPEN_CRASH_LANE: "09:02-09:20 S06_STAIRCASE_RETEST_V1",
                INTRADAY_CRASH_LANE: (
                    "09:20-14:30 S03_INTRADAY_CRASH_REBOUND_V1"
                ),
            },
            "watch_count": len(union_codes),
            "open_watch_count": len(open_codes),
            "intraday_watch_count": len(intraday_codes),
            "profile_count": len(profiles),
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
        }
        _write_json_atomic(config.output_path, payload)
        _append_events(
            config.event_dir / f"strategy_03_signals_{now:%Y%m%d}.csv",
            open_signals,
        )
        _append_events(
            config.event_dir
            / f"strategy_03_intraday_signals_{now:%Y%m%d}.csv",
            intraday_signals,
        )
        # ★[2026-08-06] 계기판 그림자 — 저점 무장·계단 순간만. 빈 배치는 _append_events 가
        #   스스로 건너뛰므로 조용한 날엔 파일 자체가 안 생긴다.
        _append_events(
            config.event_dir / f"strategy_03_low_gauge_{now:%Y%m%d}.csv",
            low_gauge_rows,
        )
        if (
            once
            or now.weekday() >= 5
            or now.time() >= SIGNAL_PROCESS_END
        ):
            return 0
        time_module.sleep(max(0.2, config.loop_sec))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return run(SignalConfig(), once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())

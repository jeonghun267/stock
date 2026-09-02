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
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_signal_contract_v1 import (
    ACTIVE_ENTRY_LANES,
    ALGORITHM,
    EARLY_LOW_ALGORITHM,
    EARLY_LOW_CAPTURE_END,
    EARLY_LOW_CAPTURE_START,
    EARLY_LOW_FAST_REBOUND_MAX_PCT,
    EARLY_LOW_FAST_REBOUND_REASON,
    EARLY_LOW_LANE,
    EARLY_LOW_LOW_STABLE_SEC,
    EARLY_LOW_MAX_REBOUND_PCT,
    EARLY_LOW_MIN_REBOUND_PCT,
    EARLY_LOW_MIN_UP_TICKS,
    EARLY_LOW_RAPID_DROP_PCT,
    EARLY_LOW_RAPID_WINDOW_SEC,
    EARLY_LOW_REBOUND_TIMEOUT_SEC,
    EarlyLowAuditChain,
    FIRST_REBOUND_PCT,
    INTRADAY_CRASH_LANE,
    MIN_HIGHER_LOW_PCT,
    MIN_OBSERVE_SEC,
    MIN_PULLBACK_PCT,
    MIN_SECOND_REBOUND_PCT,
    EXPRESS_DEPTH_PCT,
    EXPRESS_FAST_WINDOW_SEC,
    OPEN_ARM_DROP_PCT,
    OPEN_EXCLUSIVE_DROP_PCT,
    OPEN_MAX_REBOUND_PCT,
    OPEN_CRASH_LANE,
    OPEN_MIN_REBOUND_PCT,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    production_file_sha256,
)
from listed_turnover_common_v1 import listed_turnover_metrics
from strategy_03_intraday_rebound_v1 import IntradayReboundDetector
from strategy_03_flow_turn_fast_v1 import (
    SellerExhaustionFastConfig,
    seller_exhaustion_fast_decision,
)
from strategy_common_relative_strength_rebound_v1 import (
    RelativeStrengthReboundShadow,
    read_market_change_pct,
)
from strategy_03_deep_crash_shadow_ledger_v1 import DeepCrashShadowLedger
import s03_s06_crash_claim_v1 as crash_claim

KST = ZoneInfo("Asia/Seoul")
# ★[2026-08-30 친구님 승인] OPEN_CRASH 시작 09:02 → 09:00.
#   시가가 아직 없으면 OPEN_PRICE_MISSING 으로 기다리고 상태를 무장하지 않는다.
#   신호 계약의 시간창과 반드시 같은 값으로 유지한다.
ENTRY_START = time(9, 0)
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
#   장초 레인(09:00~09:20)과 겹치던 구간을 없앤다 — 종전에는 09:00~09:20 동안
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
    low_stable_sec: float = 2.0

    def __post_init__(self) -> None:
        if not OPEN_EXCLUSIVE_DROP_PCT < self.arm_drop_pct < 0:
            raise ValueError("invalid exclusive open-drop band")
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
        if self.low_stable_sec <= 0:
            raise ValueError("low_stable_sec must be positive")


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
    cum_vol: float = 0.0
    open_price: float = 0.0
    # ★[MIN-LOW 2026-08-03 친구님 지시] 신저점은 틱이 아니라 1분봉 저가로 판정한다.
    #   진행 중인 봉의 저가(돈맥_1분봉.json 의 l)를 쓴다 — 완성봉을 기다리면 최대 60초가
    #   밀려, 방금 걷어낸 관찰 60초를 다시 넣는 꼴이 된다.
    #   0 이면(자료 없음) 종전처럼 틱 가격으로 판정한다 — 되돌림 안전.
    minute_low: float = 0.0
    broker_day_low: float = 0.0
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
class EarlyLowState:
    anchor_low: float = 0.0
    anchor_low_ts: datetime | None = None
    rapid_high: float = 0.0
    rapid_high_ts: datetime | None = None
    rapid_drop_pct: float = 0.0
    last_price: float = 0.0
    up_ticks: int = 0
    chase_blocked: bool = False
    emitted: bool = False


class EarlyLowDetector:
    """09:00~09:10: 3분 급락 뒤 60초 이내 직접반등을 잡는다."""

    def __init__(self) -> None:
        self.state = EarlyLowState()
        self.flow_points: deque[MicroPoint] = deque(maxlen=512)

    def _prune_points(self, point: MicroPoint) -> None:
        cutoff = point.ts.timestamp() - EARLY_LOW_RAPID_WINDOW_SEC
        while self.flow_points and self.flow_points[0].ts.timestamp() < cutoff:
            self.flow_points.popleft()

    def _rolling_high(self, point: MicroPoint) -> tuple[float, datetime]:
        rows = list(self.flow_points)
        high_point = max(rows, key=lambda row: row.price, default=point)
        high_price = high_point.price
        high_ts = high_point.ts
        if point.open_price > high_price:
            high_price = point.open_price
            high_ts = point.ts.replace(hour=9, minute=0, second=0, microsecond=0)
        return high_price, high_ts

    def _flow_meta(self) -> dict[str, Any]:
        rates = []
        anchor_ts = self.state.anchor_low_ts
        points = [
            point for point in self.flow_points
            if anchor_ts is None or point.ts >= anchor_ts
        ]
        for prior, current in zip(points, points[1:]):
            seconds = (current.ts - prior.ts).total_seconds()
            db = current.buy_money_cum - prior.buy_money_cum
            ds = current.sell_money_cum - prior.sell_money_cum
            if seconds > 0 and db >= 0 and ds >= 0:
                rates.append((db / seconds, ds / seconds, prior, current))
        if len(rates) < 2:
            return {
                "flow_turn_ready": False,
                "flow_recent_buy_rate": 0.0,
                "flow_recent_sell_rate": 0.0,
                "flow_baseline_buy_rate": 0.0,
                "flow_baseline_sell_rate": 0.0,
                "flow_price_responding": False,
                "flow_sample_points": len(points),
            }
        recent_buy, recent_sell, prior_point, current_point = rates[-1]
        baseline = rates[max(0, len(rates) - 4):-1]
        prices = [point.price for point in points[-3:]]
        return {
            "flow_turn_ready": True,
            "flow_recent_buy_rate": round(recent_buy, 4),
            "flow_recent_sell_rate": round(recent_sell, 4),
            "flow_baseline_buy_rate": round(median(row[0] for row in baseline), 4),
            "flow_baseline_sell_rate": round(median(row[1] for row in baseline), 4),
            "flow_price_responding": bool(
                current_point.price > prior_point.price
                and current_point.price > min(prices)
            ),
            "flow_sample_points": len(points),
        }

    def restore(self, anchor_low: float, anchor_low_ts: datetime | None, *,
                chase_blocked: bool = False, emitted: bool = False,
                flow_points: Iterable[MicroPoint] | None = None,
                rapid_high: float = 0.0,
                rapid_high_ts: datetime | None = None,
                rapid_drop_pct: float = 0.0,
                last_price: float = 0.0,
                up_ticks: int = 0) -> None:
        if anchor_low > 0 and anchor_low_ts is not None:
            self.state.anchor_low = float(anchor_low)
            self.state.anchor_low_ts = anchor_low_ts
        self.state.chase_blocked = bool(chase_blocked)
        self.state.emitted = bool(emitted)
        self.state.rapid_high = float(rapid_high or 0.0)
        self.state.rapid_high_ts = rapid_high_ts
        self.state.rapid_drop_pct = float(rapid_drop_pct or 0.0)
        self.state.last_price = float(last_price or 0.0)
        self.state.up_ticks = int(up_ticks or 0)
        if flow_points is not None:
            self.flow_points = deque(flow_points, maxlen=512)

    def _row(self, point: MicroPoint, action: str, reason: str) -> dict[str, Any]:
        state = self.state
        rebound = (
            (point.price / state.anchor_low - 1.0) * 100.0
            if state.anchor_low > 0 else 0.0
        )
        anchor_age = (
            max(0.0, (point.ts - state.anchor_low_ts).total_seconds())
            if state.anchor_low_ts else 0.0
        )
        row = {
            "mode": SIGNAL_MODE,
            "algorithm": EARLY_LOW_ALGORITHM,
            "entry_lane": EARLY_LOW_LANE,
            "action": action,
            "reason": reason,
            "ts": point.ts.isoformat(timespec="milliseconds"),
            "price": point.price,
            "open_price": point.open_price,
            "anchor_low": state.anchor_low,
            "anchor_low_ts": (
                state.anchor_low_ts.isoformat(timespec="milliseconds")
                if state.anchor_low_ts else ""
            ),
            "rebound_pct": round(rebound, 6),
            "rapid_high": state.rapid_high,
            "rapid_high_ts": (
                state.rapid_high_ts.isoformat(timespec="milliseconds")
                if state.rapid_high_ts else ""
            ),
            "rapid_drop_pct": round(state.rapid_drop_pct, 6),
            "rapid_window_sec": EARLY_LOW_RAPID_WINDOW_SEC,
            "anchor_age_sec": round(anchor_age, 3),
            "low_stable_sec": round(anchor_age, 3),
            "up_ticks": state.up_ticks,
            "chase_blocked": state.chase_blocked,
            "current_buy_money_cum": point.buy_money_cum,
            "current_sell_money_cum": point.sell_money_cum,
        }
        row.update(self._flow_meta())
        return row

    def feed(self, point: MicroPoint, *, allow_signal: bool) -> dict[str, Any]:
        state = self.state
        if self.flow_points and point.ts <= self.flow_points[-1].ts:
            return self._row(point, "WAIT", "EARLY_LOW_DUPLICATE_OR_OLD_SNAPSHOT")
        prior_price = state.last_price
        self.flow_points.append(point)
        self._prune_points(point)
        point_time = point.ts.time()
        if point_time < EARLY_LOW_CAPTURE_START:
            return self._row(point, "WAIT", "EARLY_LOW_BEFORE_OPEN")

        observed_low = (
            point.broker_day_low
            if point.broker_day_low > 0
            else (point.minute_low if point.minute_low > 0 else point.price)
        )
        if point_time <= EARLY_LOW_CAPTURE_END and (
            state.anchor_low <= 0 or observed_low < state.anchor_low
        ):
            rapid_high, rapid_high_ts = self._rolling_high(point)
            rapid_drop = (
                (observed_low / rapid_high - 1.0) * 100.0
                if rapid_high > 0 else 0.0
            )
            if rapid_drop <= -EARLY_LOW_RAPID_DROP_PCT:
                state.anchor_low = observed_low
                state.anchor_low_ts = point.ts
                state.rapid_high = rapid_high
                state.rapid_high_ts = rapid_high_ts
                state.rapid_drop_pct = rapid_drop
                state.chase_blocked = False
                state.emitted = False
                state.up_ticks = 0
                state.last_price = point.price
                return self._row(point, "ARMED", "EARLY_LOW_3M_DROP_ARMED")
            if state.anchor_low <= 0:
                state.last_price = point.price
                return self._row(point, "WAIT", "EARLY_LOW_3M_DROP_LT_3PCT")
        elif (
            point_time > EARLY_LOW_CAPTURE_END
            and state.anchor_low > 0
            and observed_low < state.anchor_low
        ):
            state.chase_blocked = True
            state.last_price = point.price
            state.up_ticks = 0
            return self._row(point, "DONE", "EARLY_LOW_NEW_LOW_AFTER_CAPTURE")

        if state.anchor_low <= 0 or state.anchor_low_ts is None:
            state.last_price = point.price
            return self._row(point, "WAIT", "EARLY_LOW_3M_DROP_NOT_ARMED")

        if prior_price > 0 and point.price > prior_price:
            state.up_ticks += 1
        else:
            state.up_ticks = 0
        state.last_price = point.price

        if state.emitted:
            return self._row(point, "DONE", "EARLY_LOW_ALREADY_EMITTED")
        if state.anchor_low <= 0 or state.anchor_low_ts is None:
            return self._row(point, "WAIT", "EARLY_LOW_ANCHOR_MISSING")
        if state.chase_blocked:
            return self._row(point, "WAIT", "EARLY_LOW_WAIT_NEW_LOW")

        rebound = (point.price / state.anchor_low - 1.0) * 100.0
        anchor_age = (point.ts - state.anchor_low_ts).total_seconds()
        if anchor_age > EARLY_LOW_REBOUND_TIMEOUT_SEC:
            state.chase_blocked = True
            return self._row(point, "WAIT", "EARLY_LOW_60S_TIMEOUT_WAIT_NEW_LOW")
        if rebound > EARLY_LOW_MAX_REBOUND_PCT:
            state.chase_blocked = True
            return self._row(point, "WAIT", "EARLY_LOW_ABOVE_1P5_WAIT_NEW_LOW")
        if not allow_signal:
            return self._row(point, "WAIT", "ENTRY_TIME_CLOSED")
        if anchor_age < EARLY_LOW_LOW_STABLE_SEC:
            return self._row(point, "ARMED", "EARLY_LOW_2S_STABILITY_WAIT")
        if rebound < EARLY_LOW_MIN_REBOUND_PCT:
            return self._row(point, "ARMED", "EARLY_LOW_REBOUND_LT_0P5")
        if state.up_ticks < EARLY_LOW_MIN_UP_TICKS:
            return self._row(point, "WAIT", "EARLY_LOW_TWO_UP_TICKS_WAIT")

        state.emitted = True
        return self._row(
            point, "BUY_READY", "S03_EARLY_LOW_3M_DROP_60S_REBOUND_2UP")


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
    emitted: bool = False
    emission_count: int = 0
    low_price: float = 0.0
    low_ts: datetime | None = None
    stable_pass_ts: datetime | None = None
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
    # ★[S03-EXPRESS 2026-08-06] 당일 고점(시가 포함) — 급행 깊이(-7%)의 기준점.
    #   자료공백 리셋에도 살아남는다(그날 찍힌 고점이 없던 일이 되지 않는다).
    day_high: float = 0.0
    flow_reversal_streak: int = 0
    seller_exhaustion_fast: dict[str, Any] = field(default_factory=dict)


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

    def _clear_retest(self) -> None:
        state = self.state
        state.observe_since = None
        state.first_rebound_peak = 0.0
        state.pullback_seen = False
        state.pullback_low = 0.0
        state.speed_flip_seen = False
        state.flow_reversal_streak = 0
        state.seller_exhaustion_fast = {}

    def _record_flow(self, point: MicroPoint) -> None:
        points = self.state.flow_points
        if points and (point.buy_money_cum < points[-1].buy_money_cum or point.sell_money_cum < points[-1].sell_money_cum):
            points.clear()
        points.append(point)
        # ★[2026-08-27 급행 폐지 후에도 유지] EXPRESS_FAST_WINDOW_SEC(600초)은 이제
        #   flow_points 보관 창으로만 쓴다. 소비자(_pre_rates 180초·_flow_acceleration 20초)는
        #   자기 창만 봐서 동작 불변 — 이 상수를 지우면 보관 창이 깨진다.
        cutoff = point.ts.timestamp() - EXPRESS_FAST_WINDOW_SEC
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

    def _open_seller_exhaustion(self, point: MicroPoint) -> tuple[dict[str, Any], bool]:
        rows = self.state.flow_points
        low = self.state.low_price
        rebound = (point.price / low - 1.0) * 100.0 if low > 0 else 0.0
        config = SellerExhaustionFastConfig(
            max_rebound_pct=self.config.chase_cap_pct)
        if len(rows) < 4 or self.state.low_ts is None:
            decision = seller_exhaustion_fast_decision(
                rapid_drop_pct=0.0, rebound_pct=rebound,
                sell_rate_old=0.0, sell_rate_mid=0.0, sell_rate_now=0.0,
                price_up_ticks=0, ask_depleting=False, best_bid_share=0.0,
                spread_bps=0.0, microprice_edge_bps=0.0,
                new_low=point.price <= low, config=config,
            )
            decision["metrics"] = {"sample_count": len(rows)}
            return decision, False

        old, mid, recent, end = rows[-4:]

        def rate(left: MicroPoint, right: MicroPoint, field_name: str) -> float:
            elapsed = (right.ts - left.ts).total_seconds()
            delta = getattr(right, field_name) - getattr(left, field_name)
            return max(0.0, delta) / elapsed if elapsed > 0 else 0.0

        buy_old = rate(old, mid, "buy_money_cum")
        buy_mid = rate(mid, recent, "buy_money_cum")
        buy_now = rate(recent, end, "buy_money_cum")
        sell_old = rate(old, mid, "sell_money_cum")
        sell_mid = rate(mid, recent, "sell_money_cum")
        sell_now = rate(recent, end, "sell_money_cum")
        post_low = [row for row in rows if row.ts >= self.state.low_ts]
        up_ticks = 0
        for left, right in reversed(list(zip(post_low[:-1], post_low[1:]))):
            if right.price <= left.price:
                break
            up_ticks += 1
        ask_depleting = bool(
            len(post_low) >= 3
            and all(row.best_ask_qty > 0 for row in post_low[-3:])
            and post_low[-2].best_ask_qty < post_low[-3].best_ask_qty
            and post_low[-1].best_ask_qty < post_low[-2].best_ask_qty
        )
        total_book = end.best_bid_qty + end.best_ask_qty
        bid_share = end.best_bid_qty / total_book if total_book > 0 else 0.0
        mp = microprice(end)
        midpoint = (end.best_ask_px + end.best_bid_px) / 2.0 if end.book_valid else 0.0
        spread_bps = end.spread / midpoint * 10_000.0 if midpoint > 0 else 0.0
        micro_edge = (mp / midpoint - 1.0) * 10_000.0 if mp and midpoint > 0 else 0.0
        anchor_drop = (
            (low / point.open_price - 1.0) * 100.0 if point.open_price > 0 else 0.0)
        decision = seller_exhaustion_fast_decision(
            rapid_drop_pct=abs(min(0.0, anchor_drop)),
            rebound_pct=rebound,
            sell_rate_old=sell_old,
            sell_rate_mid=sell_mid,
            sell_rate_now=sell_now,
            price_up_ticks=up_ticks,
            ask_depleting=ask_depleting,
            best_bid_share=bid_share,
            spread_bps=spread_bps,
            microprice_edge_bps=micro_edge,
            new_low=point.price <= low,
            config=config,
        )
        reversal_now = bool(sell_now > sell_mid and buy_now < buy_mid)
        decision["metrics"] = {
            "buy_rate_old": round(buy_old, 4),
            "buy_rate_mid": round(buy_mid, 4),
            "buy_rate_now": round(buy_now, 4),
            "sell_rate_old": round(sell_old, 4),
            "sell_rate_mid": round(sell_mid, 4),
            "sell_rate_now": round(sell_now, 4),
            "price_up_ticks": up_ticks,
            "best_bid_share": round(bid_share, 4),
            "flow_reversal_now": reversal_now,
        }
        return decision, reversal_now

    def _evaluate_open_direct(
        self, point: MicroPoint, profile: PriorProfile,
    ) -> dict[str, Any]:
        state = self.state
        chase_ceiling = state.low_price * (1.0 + self.config.chase_cap_pct / 100.0)
        entry_floor = state.low_price * (1.0 + self.config.entry_floor_pct / 100.0)
        if state.dead_low > 0 and state.low_price >= state.dead_low:
            state.last = point
            return self._row("WAIT", "GIVEUP_WAIT_NEW_LOW", point, profile)
        if point.price > chase_ceiling:
            state.dead_low = state.low_price
            state.last = point
            return self._row("WAIT", "ABOVE_CHASE_CAP", point, profile)

        decision, reversal_now = self._open_seller_exhaustion(point)
        state.seller_exhaustion_fast = decision
        state.flow_reversal_streak = (
            state.flow_reversal_streak + 1 if reversal_now else 0)
        if state.flow_reversal_streak >= 2:
            state.dead_low = state.low_price
            state.last = point
            return self._row(
                "WAIT", "SELL_REACCEL_BUY_WEAK_2TICKS_WAIT_NEW_LOW",
                point, profile)

        stable = (point.ts - (state.low_ts or point.ts)).total_seconds()
        if stable < self.config.low_stable_sec:
            state.last = point
            return self._row("WAIT", "OPEN_LOW_STABILITY_WAIT", point, profile)
        if state.stable_pass_ts is None:
            state.stable_pass_ts = point.ts
        if point.price < entry_floor:
            state.last = point
            return self._row(
                "WAIT", "OPEN_DIRECT_REBOUND_ENTRY_RANGE_WAIT", point, profile)
        if not decision["ready"]:
            state.last = point
            return self._row("WAIT", "OPEN_SELLER_EXHAUSTION_WAIT", point, profile)

        state.emitted = True
        state.emission_count += 1
        state.dead_low = state.low_price * (
            1.0 - self.config.rearm_deeper_pct / 100.0)
        state.last = point
        return self._row(
            "BUY_READY", "S03_OPEN_SELLER_EXHAUSTION_DIRECT", point, profile)

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
                "anchor_drop_from_open_pct": round(
                    (state.low_price / point.open_price - 1.0) * 100.0, 4),
                "anchor_low_ts": state.low_ts.isoformat(timespec="milliseconds") if state.low_ts else "",
                "s03_first_seen_ts": (
                    state.low_ts.isoformat(timespec="microseconds")
                    if state.low_ts else ""),
                "stable_pass_ts": (
                    state.stable_pass_ts.isoformat(timespec="microseconds")
                    if state.stable_pass_ts else ""),
                "signal_ts": (
                    point.ts.isoformat(timespec="microseconds")
                    if action == "BUY_READY" else ""),
                "rebound_pct": round(rebound, 4), "first_rebound_pct": round(first_rebound, 4),
                "observe_sec": round(observe_sec, 3), "first_rebound_peak": state.first_rebound_peak,
                "pullback_low": state.pullback_low, "pullback_depth_pct": round(pullback_depth, 4),
                "higher_low_pct": round(higher_low, 4), "second_rebound_pct": round(second_rebound, 4),
                "dead_low": round(state.dead_low, 4),
                "flow_reversal_streak": state.flow_reversal_streak,
                "buy_money_since_low": round(max(0.0, point.buy_money_cum - state.reset_buy_money), 2),
                "sell_money_since_low": round(max(0.0, point.sell_money_cum - state.reset_sell_money), 2),
            })
            if state.seller_exhaustion_fast:
                row["seller_exhaustion_fast"] = state.seller_exhaustion_fast
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
        state.stable_pass_ts = None
        state.reset_buy_money, state.reset_sell_money = point.buy_money_cum, point.sell_money_cum
        state.dead_low = 0.0
        state.pre_buy_rate, state.pre_sell_rate = self._pre_rates(point)
        self._clear_retest()

    def _reset_cycle(self) -> None:
        old = self.state
        self.state = DetectorState(
            emitted=old.emitted,
            emission_count=old.emission_count, minute=old.minute,
            day_high=old.day_high)

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
        # ★[S03-EXPRESS 2026-08-06] 당일 고점 갱신(시가 포함) — 급행 깊이의 기준점.
        if point.price > state.day_high:
            state.day_high = point.price
        if point.open_price > state.day_high:
            state.day_high = point.open_price
        arm_price = point.open_price * (1.0 + self.config.arm_drop_pct / 100.0)
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
            if self._probe_low(point) > arm_price:
                state.last = point
                return self._row("WAIT", "OPEN_DROP_GT_4PCT", point, profile)
            self._reset_low(point)
            state.last = point
            return self._row(
                "ARMED", "OPEN_DROP_4PCT_OR_MORE_LOW_TRACK_START", point, profile)
        # ★[MIN-LOW 2026-08-03 친구님 지시] 신저점은 1분봉 저가로 판정한다.
        #   틱 하나가 순간적으로 찍고 올라와도 계단이 흔들리지 않는다.
        if self._probe_low(point) < state.low_price:
            self._reset_low(point)
            state.last = point
            return self._row("RESET", "OPEN_NEW_LOW_RESET", point, profile)
        return self._evaluate_open_direct(point, profile)
        # ★[2026-08-27 친구님 지시 "급행도 꺼 두개만 남겨"] 급행 즉시매수 경로 삭제 —
        #   깊은 급락도 계단(4단계)이 직접 잡는다(깊은구역 차단도 함께 제거).
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
        # ★[2026-08-27 친구님 지시] 급행 폐지 — 깊은 구역도 계단이 직접 잡는다.
        #   (종전 DEEP_ZONE_EXPRESS_ONLY 차단 삭제. 검사기 하한도 같은 날 함께 제거.)
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
    early_high_range_path: Path = Path(os.environ.get(
        "S03_EARLY_HIGH_RANGE",
        r"C:\stock_bot\data\common_high_range_top30.json"))
    mflow_board_path: Path = Path(os.environ.get(
        "S03_MFLOW_BOARD",
        r"C:\stock_bot\data\돈흐름_선별판.json"))
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
    universe = load_prior_profile_universe(
        path,
        source_dates={source_date},
    )
    return {
        code: profile
        for (row_date, code), profile in universe.items()
        if row_date == source_date and code in codes
    }


def load_prior_profile_universe(
    path: Path,
    *,
    source_dates: set[str],
) -> dict[tuple[str, str], PriorProfile]:
    """Load the requested trading dates in one EOD scan.

    The shared watch list changes throughout the session.  Caching this
    date-level universe prevents every small watch-list change from rescanning
    the full EOD file and stalling live snapshot consumption.
    """
    wanted_dates = {str(value) for value in source_dates if str(value)}
    if not wanted_dates:
        return {}
    output: dict[tuple[str, str], PriorProfile] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row_date = str(row.get("date") or "")
                if row_date not in wanted_dates:
                    continue
                code = str(row.get("code") or "").zfill(6)
                op = _number(row.get("open"))
                high = _number(row.get("high"))
                low = _number(row.get("low"))
                close = _number(row.get("close"))
                value = _number(row.get("value"))
                if close <= 0 or high < low:
                    continue
                span = high - low
                output[(row_date, code)] = PriorProfile(
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


def load_latest_prior_profiles(
    path: Path,
    *,
    current_day: str,
) -> tuple[str, dict[str, PriorProfile]]:
    """Load every code from the latest EOD trading date before current_day."""
    selected_date = ""
    output: dict[str, PriorProfile] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row_date = str(row.get("date") or "").replace("-", "")[:8]
                if len(row_date) != 8 or row_date >= current_day or row_date < selected_date:
                    continue
                code = str(row.get("code") or "").zfill(6)
                op, high, low = _number(row.get("open")), _number(row.get("high")), _number(row.get("low"))
                close, value = _number(row.get("close")), _number(row.get("value"))
                if close <= 0 or high < low:
                    continue
                if row_date > selected_date:
                    selected_date, output = row_date, {}
                span = high - low
                output[code] = PriorProfile(previous_close=close, previous_value=value, previous_range_pct=((high-low)/op*100.0 if op>0 else 0.0), previous_close_position=((close-low)/span if span>0 else 0.5))
    except (OSError, csv.Error):
        return "", {}
    return selected_date, output


class RapidReboundMonitor:
    def __init__(self) -> None:
        self.early_detectors: dict[str, EarlyLowDetector] = {}
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
            if lane == EARLY_LOW_LANE:
                detector = self.early_detectors.setdefault(code, EarlyLowDetector())
                detector.restore(
                    float(raw.get("anchor_low") or 0),
                    _parse_dt(raw.get("anchor_low_ts"), datetime.now()),
                    chase_blocked=bool(raw.get("chase_blocked")),
                    emitted=True,
                )
                lane_key = f"{lane}:{code}"
                self.emission_counts[lane_key] = max(
                    self.emission_counts.get(lane_key, 0), sequence)
                restored = dict(raw)
                restored["entry_lane"] = lane
                self.signals.append(restored)
                continue
            if lane not in ACTIVE_ENTRY_LANES:
                continue
            detector = (
                self.intraday_detectors.setdefault(code, IntradayReboundDetector())
                if lane == INTRADAY_CRASH_LANE
                else self.open_detectors.setdefault(code, RapidReboundDetector())
            )
            detector.restore_emitted(
                sequence, float(raw.get("anchor_low") or 0))
            lane_key = f"{lane}:{code}"
            self.emission_counts[lane_key] = max(
                self.emission_counts.get(lane_key, 0), sequence)
            restored = dict(raw)
            restored["entry_lane"] = lane
            self.signals.append(restored)

    def process_early_point(
        self,
        code: str,
        name: str,
        point: MicroPoint,
        *,
        allow_signal: bool,
    ) -> tuple[dict[str, Any], bool]:
        detector = self.early_detectors.setdefault(code, EarlyLowDetector())
        lane_key = f"{EARLY_LOW_LANE}:{code}"
        total = self.emission_counts.get(lane_key, 0)
        row = detector.feed(point, allow_signal=allow_signal and total < 2)
        row.update({"code": code, "name": name, "entry_lane": EARLY_LOW_LANE})
        row.update(listed_turnover_metrics(code, point.cum_vol))
        fired = row["action"] == "BUY_READY"
        if fired:
            total += 1
            self.emission_counts[lane_key] = total
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

    def process_point(
        self,
        code: str,
        name: str,
        point: MicroPoint,
        profile: PriorProfile,
        *,
        allow_signal: bool,
    ) -> tuple[dict[str, Any], bool]:
        lane = (
            OPEN_CRASH_LANE
            if point.ts.time() < INTRADAY_ENTRY_START
            else INTRADAY_CRASH_LANE
        )
        lane_key = f"{lane}:{code}"
        total = self.emission_counts.get(lane_key, 0)
        if lane == OPEN_CRASH_LANE:
            detector = self.open_detectors.setdefault(code, RapidReboundDetector())
            row = detector.feed(
                point, profile, allow_signal=allow_signal and total < 2)
        else:
            detector = self.intraday_detectors.setdefault(
                code, IntradayReboundDetector())
            row = detector.feed(point, allow_signal=allow_signal and total < 2)
        row.update({"code": code, "name": name, "entry_lane": lane})
        row.update(listed_turnover_metrics(code, point.cum_vol))
        if lane == OPEN_CRASH_LANE:
            claim_event_id = (
                f"{row.get('anchor_low_ts')}:"
                f"{float(row.get('anchor_low') or 0):.4f}"
            )
            release_reasons = {
                "ABOVE_CHASE_CAP",
                "GIVEUP_WAIT_NEW_LOW",
                "SELL_REACCEL_BUY_WEAK_2TICKS_WAIT_NEW_LOW",
                "CUMULATIVE_REVERSE_RESET",
                "CODE_DAILY_ENTRY_LIMIT_2",
            }
            if str(row.get("reason") or "") in release_reasons:
                crash_claim.release_claimed_s03(
                    code, point.ts, reason=str(row.get("reason") or ""))
                row["s03_s06_claim_state"] = "RELEASED"
            elif detector.state.armed and float(row.get("anchor_low") or 0) > 0:
                row["s03_s06_claim_state"] = crash_claim.try_claim_s03(
                    code, claim_event_id, point.ts)
                row["s03_s06_claim_event_id"] = claim_event_id
        fired = row["action"] == "BUY_READY"
        if (
            lane == OPEN_CRASH_LANE
            and fired
            and crash_claim.enabled()
            and row.get("s03_s06_claim_state") not in crash_claim.ACTIVE_STATES
        ):
            row.update({
                "action": "WAIT",
                "reason": "S03_CRASH_CLAIM_NOT_HELD",
            })
            fired = False
        if fired:
            total += 1
            self.emission_counts[lane_key] = total
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
    "hr_money_speed_ratio", "hr_turnover_pct", "hr_volatility_quality",
    "hr_quality_risks", "hr_live_status",
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
) -> tuple[list[tuple[str, str, MicroPoint, PriorProfile | None]], str]:
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "").replace("-", "")[:8] != today:
        return [], "WATCH_DATE_MISMATCH"
    codes = {
        str(code).zfill(6) for code in (watch.get("codes") or [])
    }
    snapshot = _read_json(config.snapshot_path)
    names = _name_map(_read_json(config.names_path))
    output = []
    for code, raw in (snapshot.get("codes") or {}).items():
        code = str(code).zfill(6)
        if (code not in codes or code not in open_codes
                or code not in profiles or not isinstance(raw, Mapping)):
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
        point = MicroPoint(
            ts=ts,
            price=price,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            cum_vol=abs(_number(raw.get("cum_vol"))),
            open_price=open_price,
            minute_low=_number((lows or {}).get(code)),
            # ★[DAY-LOW-FIELD-FIX 2026-08-19 친구님 지시 "저점 매수 수리"] 스냅샷의 당일저가는
            #   lo(FID18)다. 종전 키 day_low 는 브로커가 쓴 적 없는 이름이라 항상 0 →
            #   EARLY_LOW 기준저점 미포착 39/39 (8/19 실측). day_low 는 폴백으로 유지.
            #   되돌리기: backup\골짜기_급반등_20260819_before_daylow_field_fix.py
            broker_day_low=abs(_number(raw.get("lo") or raw.get("day_low"))),
            che_str=abs(_number(raw.get("che_str"))),
            buy_volume_cum=_number(raw.get("buy_vol_cum"), -1.0),
            sell_volume_cum=_number(raw.get("sell_vol_cum"), -1.0),
            best_ask_px=abs(_number(raw.get("best_ask_px"))),
            best_bid_px=abs(_number(raw.get("best_bid_px"))),
            best_ask_qty=abs(_number(raw.get("best_ask_qty"))),
            best_bid_qty=abs(_number(raw.get("best_bid_qty"))),
        )
        output.append((code, names.get(code, code), point, profiles.get(code)))
    return output, ("LIVE" if output else "DATA_WAIT")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★[2026-07-29 친구님 승인 "S03에도 재시도 패치"] 읽는 쪽이 파일을 잡은 순간 os.replace가
    #   WinError 5(접근거부)로 죽어 신호기 전체가 정지하는 패턴(같은 날 S05 11:29 실제 사고).
    #   내일부터 CVD 기록기가 이 신호 JSON을 3초마다 읽어 충돌 확률이 커져 선제 배선.
    #   최초 1회 + 0.2초 간격 재시도 3회. 그래도 실패면 종전대로 예외(원인 은폐 방지). 롤백: 루프 제거.
    for _attempt in range(6):
        try:
            os.replace(temporary, path)
            return True
        except PermissionError as exc:
            if _attempt == 5:
                print(
                    f"ATOMIC_WRITE_RETRY_EXHAUSTED_CONTINUING path={path} error={exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return False
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


def _early_high_range_codes(
    payload: Mapping[str, Any],
    day: str,
) -> set[str]:
    if (
        str(payload.get("for_date") or "").replace("-", "")[:8] != day
        or payload.get("source_stale")
        or int(payload.get("schema_version") or 0) < 2
    ):
        return set()
    candidates = sorted(
        (row for row in (payload.get("candidates") or []) if isinstance(row, Mapping)),
        key=lambda row: int(row.get("rank") or 9999),
    )[:40]
    return {
        str(row.get("code") or "").zfill(6)
        for row in candidates
        if str(row.get("code") or "").isdigit()
    }


MFLOW_DUMP_GRADES = frozenset({"🔴던짐", "🔵매도세"})


def _payload_day(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def _mflow_dump_codes(
    payload: Mapping[str, Any],
    day: str,
) -> set[str]:
    if _payload_day(payload.get("ts") or payload.get("for_date")) != day:
        return set()
    codes: set[str] = set()
    for row in (payload.get("rows") or []):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("grade") or "").strip() not in MFLOW_DUMP_GRADES:
            continue
        code = str(row.get("code") or "").strip().zfill(6)
        if len(code) == 6 and code.isascii() and code.isdigit():
            codes.add(code)
    return codes


def _strategy03_board_codes(
    high_range_payload: Mapping[str, Any],
    mflow_payload: Mapping[str, Any],
    day: str,
) -> set[str]:
    """Restore the existing high-range plus money-flow dump universe."""
    return (
        _early_high_range_codes(high_range_payload, day)
        | _mflow_dump_codes(mflow_payload, day)
    )


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = RapidReboundMonitor()
    monitor.restore(_read_json(config.output_path), now.strftime("%Y%m%d"))
    relative_strength_shadow = RelativeStrengthReboundShadow()
    deep_shadow_ledger_day = ""
    deep_shadow_ledger = DeepCrashShadowLedger("")
    deep_shadow_ledger_path = config.event_dir / "strategy_03_deep_crash_shadow_empty.json"
    profile_key: tuple[Any, ...] | None = None
    profile_date = ""
    profiles: dict[str, PriorProfile] = {}
    early_audit: EarlyLowAuditChain | None = None
    early_audit_day = ""
    early_audit_last: dict[str, tuple[str, str]] = {}
    early_audit_sha = production_file_sha256([
        Path(__file__),
        RUN_DIR / "strategy_03_signal_contract_v1.py",
        RUN_DIR / "strategy_03_rotation_engine_v1.py",
        RUN_DIR / "strategy_03_flow_turn_fast_v1.py",
        RUN_DIR / "s03_early_low_release_v1.py",
    ])
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        day = now.strftime("%Y%m%d")
        if day != deep_shadow_ledger_day:
            deep_shadow_ledger_path = (
                config.event_dir / f"strategy_03_deep_crash_shadow_{day}.json"
            )
            deep_shadow_ledger = DeepCrashShadowLedger.restore(
                _read_json(deep_shadow_ledger_path), day
            )
            deep_shadow_ledger_day = day
        if day != early_audit_day:
            early_audit = EarlyLowAuditChain("signal", day)
            early_audit_day = day
            early_audit_last = {}
        open_watch = _read_json(config.watch_path)
        shared_watch = _read_json(config.shared_watch_path)
        early_watch = _read_json(config.early_high_range_path)
        mflow_watch = _read_json(config.mflow_board_path)
        # ★[MIN-LOW 2026-08-03] 1분봉을 한 번만 읽어 시가·저가를 함께 뽑는다(파일 I/O 동일).
        minute_payload = _read_json(config.minute_path)
        opens = _minute_opens(minute_payload, day)
        lows = _minute_lows(minute_payload, day)
        range_meta = _range_meta(open_watch, shared_watch)
        open_codes = _current_watch_codes(open_watch, day)
        intraday_codes = _current_watch_codes(shared_watch, day)
        early_codes = _strategy03_board_codes(
            early_watch, mflow_watch, day)
        open_source_date = str(open_watch.get("source_date") or "")
        intraday_source_date = str(shared_watch.get("source_date") or "")
        early_source_date = str(early_watch.get("source_date") or "")
        try:
            eod_stat = config.eod_path.stat()
            eod_signature = (eod_stat.st_mtime_ns, eod_stat.st_size)
        except OSError:
            eod_signature = (0, 0)
        new_profile_key = (day, eod_signature)
        if new_profile_key != profile_key:
            profile_date, profiles = load_latest_prior_profiles(config.eod_path, current_day=day)
            profile_key = new_profile_key

        requested_codes = open_codes | intraday_codes | early_codes
        combined_watch = {"for_date": day, "codes": sorted(requested_codes)}
        # The first EOD scan can take seconds.  Snapshot freshness must be
        # measured against the decision time, not the stale loop-start time.
        now = datetime.now(KST).replace(tzinfo=None)
        points, status = load_live_points(
            config, now=now, watch=combined_watch, profiles=profiles,
            opens=opens,
            lows=lows,
            open_codes=requested_codes,
        )
        union_codes = {code for code, _name, _point, _profile in points}
        early_codes = set(union_codes)
        early_signals: list[dict[str, Any]] = []
        open_signals: list[dict[str, Any]] = []
        intraday_signals: list[dict[str, Any]] = []
        profile_missing_count = 0
        low_gauge_rows: list[dict[str, Any]] = []  # ★[2026-08-06] 계기판 그림자
        market_pct = read_market_change_pct(now)
        for code, name, point, profile in points:
            if profile is None:
                profile_missing_count += 1
                missing_lane = (
                    OPEN_CRASH_LANE
                    if point.ts.time() < INTRADAY_ENTRY_START
                    else INTRADAY_CRASH_LANE
                )
                missing_row = {
                    "action": "WAIT",
                    "reason": "S03_PRIOR_PROFILE_MISSING",
                    "entry_lane": missing_lane,
                    "code": code,
                    "name": name,
                    "ts": point.ts.isoformat(timespec="microseconds"),
                    "price": point.price,
                }
                monitor.latest[f"PROFILE:{code}"] = missing_row
                missing_key = ("WAIT", "S03_PRIOR_PROFILE_MISSING")
                if (
                    early_audit is not None
                    and early_audit_last.get(code) != missing_key
                ):
                    early_audit_last[code] = missing_key
                    early_audit.append({
                        "event": "PROFILE_MISSING",
                        "entry_lane": EARLY_LOW_LANE,
                        "code": code,
                        "name": name,
                        "hr_rank": (range_meta.get(code) or {}).get("hr_rank"),
                        "snapshot_ts": point.ts.isoformat(timespec="milliseconds"),
                        "current_price": point.price,
                        "snapshot_op": point.open_price,
                        "snapshot_lo": point.broker_day_low,
                        "buy_money_cum": point.buy_money_cum,
                        "sell_money_cum": point.sell_money_cum,
                        "best_ask_px": point.best_ask_px,
                        "best_bid_px": point.best_bid_px,
                        "best_ask_qty": point.best_ask_qty,
                        "best_bid_qty": point.best_bid_qty,
                        "anchor_low": 0.0,
                        "anchor_low_ts": "",
                        "signal_ts": "",
                        "signal_ts_exact": "",
                        "action": "WAIT",
                        "reason": "S03_PRIOR_PROFILE_MISSING",
                        "prod_sha": early_audit_sha,
                    })
                continue
            shadow_meta = relative_strength_shadow.evaluate(
                code=code,
                ts=point.ts,
                price=point.price,
                previous_close=profile.previous_close,
                market_pct=market_pct,
                buy_money_cum=point.buy_money_cum,
                sell_money_cum=point.sell_money_cum,
                best_ask_px=point.best_ask_px,
                best_bid_px=point.best_bid_px,
                best_ask_qty=point.best_ask_qty,
                best_bid_qty=point.best_bid_qty,
                high_range_meta=range_meta.get(code),
                cum_vol=point.cum_vol,
                deep_crash_enabled=True,
            )
            deep_shadow_ledger.observe(
                code=code,
                name=name,
                ts=point.ts,
                price=point.price,
                shadow=shadow_meta,
            )
            if code in early_codes:
                _pre_detector = monitor.early_detectors.get(code)
                _pre_state = {
                    "anchor_low": (
                        _pre_detector.state.anchor_low if _pre_detector else 0.0),
                    "anchor_low_ts": (
                        _pre_detector.state.anchor_low_ts.isoformat(
                            timespec="microseconds")
                        if _pre_detector and _pre_detector.state.anchor_low_ts
                        else ""),
                    "chase_blocked": bool(
                        _pre_detector.state.chase_blocked
                        if _pre_detector else False),
                    "emitted": bool(
                        _pre_detector.state.emitted if _pre_detector else False),
                    "flow_points": [
                        {
                            "ts": flow_point.ts.isoformat(timespec="microseconds"),
                            "price": flow_point.price,
                            "buy_money_cum": flow_point.buy_money_cum,
                            "sell_money_cum": flow_point.sell_money_cum,
                        }
                        for flow_point in (
                            _pre_detector.flow_points if _pre_detector else ())
                    ],
                }
                _early_allow = (
                    EARLY_LOW_CAPTURE_START <= point.ts.time() < ENTRY_END
                )
                early_row, early_fired = monitor.process_early_point(
                    code,
                    name,
                    point,
                    allow_signal=_early_allow,
                )
                early_row.update(range_meta.get(code) or {})
                early_row.update(shadow_meta)
                monitor.latest[f"{EARLY_LOW_LANE}:{code}"] = early_row
                if early_fired:
                    monitor.signals.append(dict(early_row))
                    early_signals.append(dict(early_row))
                _post_state = monitor.early_detectors[code].state
                _state_key = (
                    str(early_row.get("action") or ""),
                    str(early_row.get("reason") or ""),
                )
                _anchor_changed = (
                    _pre_state["anchor_low"] != _post_state.anchor_low
                    or _pre_state["chase_blocked"] != _post_state.chase_blocked
                    or _pre_state["emitted"] != _post_state.emitted
                )
                if early_audit is not None and (
                    _anchor_changed or early_audit_last.get(code) != _state_key
                ):
                    early_audit_last[code] = _state_key
                    early_audit.append({
                        "event": "DECISION",
                        "entry_lane": EARLY_LOW_LANE,
                        "code": code,
                        "name": name,
                        "hr_rank": (range_meta.get(code) or {}).get("hr_rank"),
                        "snapshot_ts": point.ts.isoformat(
                            timespec="microseconds"),
                        "current_price": point.price,
                        "snapshot_op": point.open_price,
                        "snapshot_lo": point.broker_day_low,
                        "broker_day_low": point.broker_day_low,
                        "buy_money_cum": point.buy_money_cum,
                        "sell_money_cum": point.sell_money_cum,
                        "best_ask_px": point.best_ask_px,
                        "best_bid_px": point.best_bid_px,
                        "best_ask_qty": point.best_ask_qty,
                        "best_bid_qty": point.best_bid_qty,
                        "allow_signal": _early_allow,
                        "pre_state": _pre_state,
                        "anchor_low": _post_state.anchor_low,
                        "anchor_low_ts": (
                            _post_state.anchor_low_ts.isoformat(
                                timespec="microseconds")
                            if _post_state.anchor_low_ts else ""),
                        "chase_blocked": bool(_post_state.chase_blocked),
                        "emitted": bool(_post_state.emitted),
                        "rebound_pct": float(
                            early_row.get("rebound_pct") or 0.0),
                        "flow_turn_ready": bool(
                            early_row.get("flow_turn_ready")),
                        "flow_recent_buy_rate": float(
                            early_row.get("flow_recent_buy_rate") or 0.0),
                        "flow_recent_sell_rate": float(
                            early_row.get("flow_recent_sell_rate") or 0.0),
                        "flow_price_responding": bool(
                            early_row.get("flow_price_responding")),
                        "action": str(early_row.get("action") or ""),
                        "reason": str(early_row.get("reason") or ""),
                        "signal_ts": (
                            str(early_row.get("ts") or "")
                            if early_fired else ""),
                        "signal_ts_exact": (
                            point.ts.isoformat(timespec="microseconds")
                            if early_fired else ""),
                        "signal_price": (
                            float(early_row.get("price") or 0.0)
                            if early_fired else 0.0),
                        "prod_sha": early_audit_sha,
                    })
            row, fired = monitor.process_point(
                code,
                name,
                point,
                profile,
                allow_signal=ENTRY_START <= point.ts.time() < ENTRY_END,
            )
            row.update(range_meta.get(code) or {})
            row.update(shadow_meta)
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
                EARLY_LOW_LANE: (
                    "09:00-09:10 3M_DROP_3P0_NEW_LOW_60S_REBOUND_0P5_1P5_2UP"),
                OPEN_CRASH_LANE: (
                    "09:00-09:20 S03_OPEN_SELLER_EXHAUSTION_DIRECT"),
                INTRADAY_CRASH_LANE: (
                    "09:20-14:30 S03_INTRADAY_CRASH_REBOUND_V1"
                ),
            },
            "watch_count": len(union_codes),
            "early_watch_count": len(early_codes),
            "open_watch_count": len(open_codes),
            "intraday_watch_count": len(intraday_codes),
            "profile_date": profile_date,
            "profile_count": len(profiles),
            "profile_missing_count": profile_missing_count,
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
        }
        if not _write_json_atomic(config.output_path, payload):
            print(f"SIGNAL_OUTPUT_STALE_CONTINUING path={config.output_path}", file=sys.stderr, flush=True)
        _write_json_atomic(
            deep_shadow_ledger_path,
            deep_shadow_ledger.payload(
                now,
                finalize=now.time() >= SIGNAL_PROCESS_END,
            ),
        )
        _append_events(
            config.event_dir / f"strategy_03_early_low_signals_{now:%Y%m%d}.csv",
            early_signals,
        )
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

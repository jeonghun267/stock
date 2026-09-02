# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 주문0 회전 배선.

매수신호는 S03 독립 계약을 사용한다. 체결 이후 주문복구·슬롯·보유·매도는
기존 공통 엔진을 사용한다. 기존 VALLEY_MORNING_CRASH 매도 수치와 우선순위는
유지하되, 사용자 지시에 따라 이 S03 프로세스에서만 09:30 강제청산을 15:10
최종청산으로 바꾼다. 기존 골짜기 프로필 전역값은 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import capital_config

# ★[MA3-COMMON 2026-08-03] 상승보유 = 3분봉 5/10/20선 + 매수세 우위(전 전략 공통).
from ma3_common_v1 import (
    ma3_rows,
    ma5_broken as ma3_ma5_broken,
    rider_permit as ma3_rider_permit,
)
from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    Strategy01Engine,
    kst_now,
    number,
    parse_dt,
    read_json,
)
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_LANE,
    EARLY_LOW_LOW_STABLE_SEC,
    EARLY_LOW_MAX_REBOUND_PCT,
    EARLY_LOW_MIN_REBOUND_PCT,
    EARLY_LOW_MIN_UP_TICKS,
    EARLY_LOW_RAPID_DROP_PCT,
    EARLY_LOW_REBOUND_TIMEOUT_SEC,
    EarlyLowAuditChain,
    production_file_sha256,
    # ★[S03-LANE-FIX 2026-08-06 친구님 지시 "가로 해"] 2번 레인 잣대를 새로 가져온다.
    INTRADAY_CRASH_LANE,
    INTRADAY_MAX_REBOUND_PCT,
    INTRADAY_MIN_REBOUND_PCT,
    OPEN_ARM_DROP_PCT,
    OPEN_CRASH_LANE,
    OPEN_MAX_REBOUND_PCT,
    OPEN_MIN_REBOUND_PCT,
    # ★[DROP-REASON-LOG 2026-08-19] 계약이 버린 신호를 기록에서 식별하는 용도(기록 전용).
    _signal_id,
    select_fresh_signals,
)
from strategy_common_hold_sell_v1 import (
    ExitPolicy,
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    STRATEGY_PROFILES,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profile_runtime_snapshot,
)
from hold_sell_audit_v1 import HoldSellAuditRecorder
# ★[2026-08-12 보안수리 2번] env 단독 활성화는 해시 커버리지 밖이라 머신 env 로
#   우회할 수 있었다. 실전 스위치를 env AND 명부승인(지문검증)의 두 요소로 만든다.
from approval_manifest_writer_v1 import live_feature_enabled
from s03_early_low_release_v1 import release_live_enabled
from strategy_03_flow_turn_fast_v1 import (
    bottom_confirm_decision,
    flow_turn_fast_decision,
)
import s03_s06_crash_claim_v1 as crash_claim
from strategy_06_crash_low_chase_v1 import atrp10_pct

# ★[DROP-REASON-LOG 2026-08-19 친구님 지시 "탈락 사유 기록"] 엔진이 신호를 버릴 때
#   이유를 남기는 기록 전용 경로. 판정 로직은 건드리지 않는다.
DROP_LOG_DIR = Path(r"C:\stock_bot\data\audit\s03_engine_drop")
S03_ENTRY_CONTEXT_AUDIT_DIR = Path(r"C:\stock_bot\data\audit\s03_entry_context")
S03_REGIME_PATH = Path(r"C:\stock_bot\data\BACKTEST\regime_std_shadow.csv")
S03_KOSDAQ_INDEX_PATH = Path(r"C:\stock_bot\data\kosdaq_index.json")
S03_KOSDAQ_HISTORY_PATH = Path(r"C:\stock_bot\보고서\코스닥지수_이력.csv")
S03_ORDER_MIN_PRICE = 10_000.0
S03_LANE_SLOT_LIMIT = 3
_REGIME_CACHE: dict[str, Any] = {"mtime_ns": None, "rows": []}


class S03CrashClaimNotHeld(RuntimeError):
    """Abort this S03 tick before broker submission when ownership is lost."""


def _market_regime_at(path: Path, now: datetime) -> str:
    """Return the latest same-day regime row at the decision timestamp."""
    local_now = (
        now.astimezone().replace(tzinfo=None) if now.tzinfo is not None else now
    )
    try:
        mtime_ns = path.stat().st_mtime_ns
        if _REGIME_CACHE["mtime_ns"] != mtime_ns:
            rows = []
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    try:
                        ts = datetime.fromisoformat(str(raw.get("ts") or ""))
                    except ValueError:
                        continue
                    rows.append((
                        ts,
                        str(raw.get("band_us") or raw.get("band") or "UNKNOWN"),
                    ))
            _REGIME_CACHE["mtime_ns"] = mtime_ns
            _REGIME_CACHE["rows"] = rows
    except OSError:
        return "UNKNOWN"
    prior = [
        row for row in _REGIME_CACHE["rows"]
        if row[0].date() == local_now.date() and row[0] <= local_now
    ]
    return prior[-1][1] if prior else "UNKNOWN"


def _s03_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _s03_low_break_shadow(
    reference_low: Any,
    observation: HoldSellObservation,
) -> dict[str, Any]:
    """Return audited S03 low-break evidence for the OPEN_CRASH live exit."""
    reference = _s03_decimal(reference_low)
    threshold = reference * Decimal("0.997")
    sell10 = observation.sell_money_per_sec_10s
    sell30 = observation.sell_money_per_sec_30s
    buy10 = observation.buy_money_per_sec_10s
    flow_data_ready = bool(sell10 > 0 and sell30 > 0)
    sell_reaccelerating = bool(
        flow_data_ready
        and sell10 > buy10
        and sell10 > sell30 * Decimal("1.2")
    )
    would_exit = bool(
        reference > 0
        and observation.price <= threshold
        and sell_reaccelerating
    )
    return {
        "s03_entry_reference_low": str(reference),
        "s03_low_break_threshold": str(threshold),
        "s03_low_break_flow_data_ready": flow_data_ready,
        "s03_sell_reaccelerating": sell_reaccelerating,
        "would_exit_low_break": would_exit,
        "s03_low_break_shadow_reason": (
            "S03_REFERENCE_LOW_BREAK_SELL_REACCEL" if would_exit else ""
        ),
    }


S03_EARLY_PEAK_ARM_PCT = Decimal("1.0")
S03_EARLY_PEAK_DROP_PCT = Decimal("0.6")
S03_EARLY_PEAK_COST_FLOOR_PCT = Decimal("0.25")


def _s03_entry_drop_pct(signal: Mapping[str, Any], lane: str) -> float:
    low = number(signal.get("anchor_low"))
    if low <= 0:
        return 0.0
    basis = (
        number(signal.get("intraday_high"))
        if lane == INTRADAY_CRASH_LANE
        else number(signal.get("open_price"))
    )
    if basis <= low:
        return max(0.0, -number(signal.get("anchor_drop_from_open_pct")))
    return max(0.0, (basis - low) / basis * 100.0)


def _s03_bottom_quality_v2_shadow(
    signal: Mapping[str, Any],
    *,
    entry_price: float,
    ma20: float,
    atrp10: float,
    kosdaq_5m_change_pct: Any,
) -> dict[str, Any]:
    """Evaluate S03 bottom quality for audit only; never gates an order."""
    flow_fields = (
        "previous_buy_rate_10s",
        "recent_buy_rate_10s",
        "recent_sell_rate_10s",
    )
    flow_inputs_ready = all(
        key in signal and signal.get(key) not in {None, ""}
        for key in flow_fields
    )
    previous_buy = number(signal.get("previous_buy_rate_10s"))
    recent_buy = number(signal.get("recent_buy_rate_10s"))
    recent_sell = number(signal.get("recent_sell_rate_10s"))
    buy_accelerating = bool(
        flow_inputs_ready and recent_buy > 0 and recent_buy > previous_buy
    )
    buy_flow_leading = bool(
        flow_inputs_ready and recent_buy > 0 and recent_buy > recent_sell
    )
    ma20_ready = bool(ma20 > 0 and entry_price > 0)
    ma20_distance_pct = (
        (entry_price / ma20 - 1.0) * 100.0 if ma20_ready else None
    )
    ma20_overheated = bool(
        ma20_ready and ma20_distance_pct is not None and ma20_distance_pct > 15.0
    )
    reference_low = number(signal.get("anchor_low"))
    rebound_pct = (
        (entry_price / reference_low - 1.0) * 100.0
        if entry_price > 0 and reference_low > 0 else None
    )
    rebound_atrp_ratio = (
        rebound_pct / atrp10
        if rebound_pct is not None and atrp10 > 0 else None
    )
    evaluation_ready = bool(flow_inputs_ready and ma20_ready)
    quality_checks = {
        "buy_accelerating": buy_accelerating,
        "buy_flow_leading": buy_flow_leading,
        "ma20_not_overheated": bool(ma20_ready and not ma20_overheated),
    }
    shadow_ready = (
        all(quality_checks.values()) if evaluation_ready else None
    )
    return {
        "schema": "S03_BOTTOM_QUALITY_V2",
        "mode": "SHADOW_ORDER_ZERO",
        "evaluation_ready": evaluation_ready,
        "shadow_ready": shadow_ready,
        "would_block_bottom_quality_v2": (
            not shadow_ready if shadow_ready is not None else None
        ),
        "quality_score": sum(quality_checks.values()),
        "quality_score_max": len(quality_checks),
        "checks": quality_checks,
        "previous_buy_rate_10s": previous_buy,
        "recent_buy_rate_10s": recent_buy,
        "recent_sell_rate_10s": recent_sell,
        "ma20": ma20 if ma20 > 0 else None,
        "ma20_distance_pct": (
            round(ma20_distance_pct, 6)
            if ma20_distance_pct is not None else None
        ),
        "ma20_overheated_above_15pct": ma20_overheated,
        "rebound_pct_at_entry": (
            round(rebound_pct, 6) if rebound_pct is not None else None
        ),
        "atrp10_pct": atrp10 if atrp10 > 0 else None,
        "rebound_atrp_ratio": (
            round(rebound_atrp_ratio, 6)
            if rebound_atrp_ratio is not None else None
        ),
        "kosdaq_5m_change_pct": kosdaq_5m_change_pct,
        "kosdaq_observation_only": True,
    }


def _s03_kosdaq_5m_context(
    index_path: Path,
    history_path: Path,
    observed_at: datetime,
) -> dict[str, Any]:
    """Read the current index JSON and its prior five-minute archived sample."""
    local_observed = (
        observed_at.astimezone().replace(tzinfo=None)
        if observed_at.tzinfo is not None
        else observed_at
    )
    result: dict[str, Any] = {
        "kosdaq_5m_change_pct": None,
        "kosdaq_index_ts": "",
        "kosdaq_prior_ts": "",
        "kosdaq_sample_interval_sec": None,
        "kosdaq_source": "kosdaq_index.json+코스닥지수_이력.csv",
    }
    try:
        current = read_json(index_path, {})
        current_ts = datetime.fromisoformat(str(current.get("ts") or ""))
        current_price = number(current.get("price"))
    except (OSError, ValueError, TypeError):
        return result
    if (
        current_price <= 0
        or current_ts.date() != local_observed.date()
        or current_ts > local_observed + timedelta(seconds=10)
        or local_observed - current_ts > timedelta(minutes=10)
    ):
        return result
    prior_rows: list[tuple[datetime, float]] = []
    try:
        with history_path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                try:
                    ts = datetime.fromisoformat(str(raw.get("지수시각") or ""))
                    price = number(raw.get("지수"))
                except ValueError:
                    continue
                if (
                    price > 0
                    and ts.date() == current_ts.date()
                    and ts <= current_ts - timedelta(minutes=4)
                ):
                    prior_rows.append((ts, price))
    except OSError:
        return result
    if not prior_rows:
        return result
    prior_ts, prior_price = max(prior_rows, key=lambda row: row[0])
    result.update({
        "kosdaq_5m_change_pct": round(
            (current_price / prior_price - 1.0) * 100.0, 6
        ),
        "kosdaq_index_ts": current_ts.isoformat(sep=" "),
        "kosdaq_prior_ts": prior_ts.isoformat(sep=" "),
        "kosdaq_sample_interval_sec": int(
            (current_ts - prior_ts).total_seconds()
        ),
    })
    return result


class Strategy03HoldSellEngine(UnifiedHoldSellEngine):
    """공통 장초반 골짜기 매도에서 S03의 시간청산만 15:10으로 분리."""

    def __init__(
        self,
        *,
        audit_recorder=None,
        early_peak_live_enabled: bool | None = None,
    ) -> None:
        super().__init__(audit_recorder=audit_recorder)
        self._s03_entry_reference_low = Decimal("0")
        self._s03_early_peak_watch_since: datetime | None = None
        self._s03_early_peak_live_enabled = (
            live_feature_enabled("S03_EARLY_PEAK")
            if early_peak_live_enabled is None
            else bool(early_peak_live_enabled)
        )
        self.open_profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            hard_stop_pct=Decimal("-2.0"),
            strong_flow_hard_stop_pct=Decimal("-2.0"),
            # ★[S03-EXPRESS 2026-08-06 친구님 지시 "매도 방법은 10:30까지 매도하는 걸로"]
            #   아침 창구 강제청산 09:50 → 10:30. 나머지 공통매도(하드손절 -2%·흐름방어·
            #   꼭지매도)는 그대로. 되돌리기: backup\s03_express_20260806\ 복원.
            force_exit_at=day_time(10, 30),
            early_decision_at=day_time(9, 20),
            exit_policy=ExitPolicy.TREND_REBOUND,
            trail_needs_sell_pressure=True,
        )
        self.profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            # ★[S03-LANE2 2026-08-06 친구님 결정 "-1%로 변경해"] 2레인 손절컷.
            #   처음 지시는 -0.5%였으나 닷새 캡처 검증에서 -0.5%는 바닥의 미세 출렁임에
            #   반등 직전 털려(손절 81.4%·평균 +0.54%) -1%(손절 60.5%·평균 +1.43%)의
            #   절반도 못 벌었다 — 숫자를 보시고 친구님이 -1%로 확정.
            #   되돌리기: backup\s03_lane2_20260806\ 복원.
            hard_stop_pct=Decimal("-1.0"),
            strong_flow_hard_stop_pct=Decimal("-1.0"),
            force_exit_at=day_time(15, 10),
        )

    def set_s03_entry_reference_low(self, value: Any) -> None:
        self._s03_entry_reference_low = _s03_decimal(value)

    def set_s03_early_peak_watch_since(self, value: Any) -> None:
        if isinstance(value, datetime):
            self._s03_early_peak_watch_since = value
            return
        try:
            self._s03_early_peak_watch_since = (
                datetime.fromisoformat(str(value)) if value else None
            )
        except (TypeError, ValueError):
            self._s03_early_peak_watch_since = None

    def get_s03_early_peak_watch_since(self) -> datetime | None:
        return self._s03_early_peak_watch_since

    def _s03_early_peak_v2(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        common_decision,
    ) -> dict[str, Any]:
        """S03 early peak D with shared-flow definitions and four live gates."""
        peak_return_pct = (
            (state.peak_price / state.entry_price - Decimal("1"))
            * Decimal("100")
        )
        peak_drop_pct = (
            (state.peak_price - observation.price)
            / state.peak_price
            * Decimal("100")
        )
        sell_money_break = (
            observation.buy_money_per_sec_10s > 0
            and observation.sell_money_per_sec_10s
            >= observation.buy_money_per_sec_10s
            * self.config.common_peak_sell_money_mult
        )
        sell_volume_break = (
            observation.buy_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_previous_10s > 0
            and observation.sell_volume_per_sec_5s
            >= observation.buy_volume_per_sec_5s
            * self.config.common_peak_sell_volume_mult
            and observation.sell_volume_per_sec_5s
            >= observation.sell_volume_per_sec_previous_10s
            * self.config.common_peak_sell_volume_accel_mult
        )
        buy_fading = (
            observation.buy_money_per_sec_30s > 0
            and observation.buy_money_per_sec_10s
            <= observation.buy_money_per_sec_30s
            * self.config.common_peak_buy_fade_mult
        )
        che_falling = (
            observation.che_str_change_5s
            <= -self.config.common_peak_che_drop
        )
        flow_break_score = sum((
            sell_money_break,
            sell_volume_break,
            buy_fading,
            che_falling,
        ))
        common_rising_hold = bool(
            common_decision.action is HoldSellAction.HOLD
            and (
                common_decision.reason.endswith("_RIDER_HOLD")
                or common_decision.reason.endswith("_MA5_TREND_HOLD")
                or common_decision.reason in {
                    "COMMON_RISING_HOLD",
                    "VALLEY_RISING_HOLD",
                    "VALLEY_PEAK_RECLAIM_HOLD",
                }
            )
        )
        rising_hold = bool(
            observation.daily_ma_permit
            or (
                observation.buy_money_per_sec_10s
                > observation.sell_money_per_sec_10s
            )
            or common_rising_hold
        )
        armed = bool(peak_return_pct >= S03_EARLY_PEAK_ARM_PCT)
        pulled_back = bool(peak_drop_pct >= S03_EARLY_PEAK_DROP_PCT)
        # No single fee/tax field exists on this exit path, so the approved
        # conservative round-trip cost floor remains an explicit 0.25%.
        cost_floor = (
            state.entry_price
            * (
                Decimal("1")
                + S03_EARLY_PEAK_COST_FLOOR_PCT / Decimal("100")
            )
        )
        cost_floor_ok = bool(observation.price >= cost_floor)
        block_reason = ""
        would_exit = False
        if not (armed and pulled_back):
            self._s03_early_peak_watch_since = None
        elif rising_hold:
            self._s03_early_peak_watch_since = None
            block_reason = "RISING_HOLD"
        elif flow_break_score < 2:
            self._s03_early_peak_watch_since = None
            block_reason = "FLOW_SCORE_LOW"
        elif not cost_floor_ok:
            self._s03_early_peak_watch_since = None
            block_reason = "COST_FLOOR_BLOCK"
        else:
            if self._s03_early_peak_watch_since is None:
                self._s03_early_peak_watch_since = observation.observed_at
            watch_age_sec = max(
                0.0,
                (
                    observation.observed_at
                    - self._s03_early_peak_watch_since
                ).total_seconds(),
            )
            if watch_age_sec >= 3.0:
                would_exit = True
            else:
                block_reason = "WATCH_PENDING"
        watch_age_sec = (
            max(
                0.0,
                (
                    observation.observed_at
                    - self._s03_early_peak_watch_since
                ).total_seconds(),
            )
            if self._s03_early_peak_watch_since is not None
            else 0.0
        )
        return {
            "s03_early_peak_variant": "D",
            "s03_early_peak_arm_pct": str(S03_EARLY_PEAK_ARM_PCT),
            "s03_early_peak_drop_pct": str(S03_EARLY_PEAK_DROP_PCT),
            "s03_early_peak_peak_return_pct": str(peak_return_pct),
            "s03_early_peak_current_drop_pct": str(peak_drop_pct),
            "s03_early_peak_armed": armed,
            "s03_early_peak_flow_break_score": flow_break_score,
            "s03_early_peak_rising_hold": rising_hold,
            "s03_early_peak_watch_since": (
                self._s03_early_peak_watch_since.isoformat()
                if self._s03_early_peak_watch_since is not None
                else ""
            ),
            "s03_early_peak_watch_age_sec": watch_age_sec,
            "s03_early_peak_cost_floor": str(cost_floor),
            "s03_early_peak_cost_floor_ok": cost_floor_ok,
            "s03_early_peak_block_reason": block_reason,
            "would_exit_s03_early_peak": would_exit,
        }

    def evaluate(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ):
        if state.strategy_id is not StrategyId.VALLEY_MORNING_CRASH:
            return super().evaluate(state, observation)
        state_before = state.to_dict()
        shadow = _s03_low_break_shadow(
            self._s03_entry_reference_low, observation
        )
        state_before.update(shadow)
        decision = self._evaluate_strategy03_once(state, observation)
        early_peak = self._s03_early_peak_v2(
            state, observation, decision
        )
        early_peak["s03_early_peak_live_enabled"] = (
            self._s03_early_peak_live_enabled
        )
        state_before.update(early_peak)
        if (
            state.entry_lane == OPEN_CRASH_LANE
            and shadow["would_exit_low_break"]
            and not decision.should_sell
        ):
            decision = self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                str(shadow["s03_low_break_shadow_reason"]),
            )
        if (
            self._s03_early_peak_live_enabled
            and early_peak["would_exit_s03_early_peak"]
            and not decision.should_sell
        ):
            decision = self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                "S03_EARLY_PEAK",
            )
        state_after = state.to_dict()
        state_after.update(shadow)
        state_after.update(early_peak)
        self.audit_recorder.record(
            state_before=state_before,
            observation=observation,
            decision=decision,
            state_after=state_after,
        )
        return decision

    def _evaluate_strategy03_once(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ):
        self._validate_sequence(state, observation)
        if state.sell_latched:
            return self._latched_decision(state)
        self._update_state_metrics(state, observation)
        entry_time = state.entry_at.timetz().replace(tzinfo=None)
        is_open_lane = (
            state.entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not state.entry_lane and entry_time < day_time(9, 20))
        )
        profile = self.open_profile if is_open_lane else self.profile
        return self._evaluate_valley(state, observation, profile)



def make_strategy03_signal_selector(
    snapshot_path: Path,
    snapshot_max_age_sec: float,
    early_low_live_enabled: bool | None = None,
    flow_turn_live_enabled: bool | None = None,
    bottom_all_lanes_live_enabled: bool | None = None,
    regime_path: Path = S03_REGIME_PATH,
    audit_stream: str = "engine",
):
    """Recheck the S06-style staircase price band and live flow before ordering."""
    if early_low_live_enabled is None:
        # ★[2026-08-12 보안수리 2번] 두 요소 모두 참이어야 실주문 후보가 된다:
        #   ① env 스위치(운영 편의) ② 명부의 해시/지문 보호된 승인(보안).
        #   env 만 머신 스코프로 우회 설정해도 명부 승인이 없으면 켜지지 않는다.
        early_low_live_enabled = (
            os.environ.get("S03_EARLY_LOW_LIVE", "NO").strip().upper() == "AUTO"
            and live_feature_enabled("S03_EARLY_LOW")
            and release_live_enabled()
        )
    if flow_turn_live_enabled is None:
        flow_turn_live_enabled = (
            os.environ.get("S03_FLOW_TURN_FAST_LIVE", "NO").strip().upper() == "YES"
            and live_feature_enabled("S03_FLOW_TURN_FAST")
        )
    if bottom_all_lanes_live_enabled is None:
        bottom_all_lanes_live_enabled = (
            os.environ.get("S03_BOTTOM_CONFIRM_ALL_LANES_LIVE", "NO").strip().upper()
            == "YES"
            and live_feature_enabled("S03_BOTTOM_CONFIRM_ALL_LANES")
        )

    # ★[EARLY-LOW-AUDIT 2026-08-12] 장초 레인 신호가 계약·주문 selector 를 어떤
    #   입력으로 통과/탈락했는지 해시 사슬 JSONL 로 남긴다. 같은 (신호, 판정) 조합은
    #   한 번만 기록한다 — selector 는 1초마다 돌므로 그대로 남기면 폭주한다.
    _audit_chains: dict[str, EarlyLowAuditChain] = {}
    # ★[DROP-REASON-LOG 2026-08-19] 계약 탈락은 신호당 1회만 기록(1초 틱 폭주 방지).
    _contract_drop_seen: set[str] = set()
    # ★[2026-08-12 보안수리 3번 보강] 값은 '기록 성공 당시의 감사 파일 크기'다.
    #   재방문 시 파일이 그보다 작아졌으면(삭제·절단) seen 을 무효화하고 재기록을
    #   요구한다 — 종전엔 set 이라, 한 번 기록되면 이후 파일이 사라져도 같은 신호의
    #   주문이 통과했다(증거 소실 후 주문).
    _audit_seen: dict[tuple[str, str, bool, bool, bool], int] = {}
    _audit_sha = production_file_sha256([
        Path(__file__),
        Path(__file__).with_name("strategy_03_signal_contract_v1.py"),
        Path(__file__).with_name("strategy_03_flow_turn_fast_v1.py"),
        Path(__file__).with_name("s03_early_low_release_v1.py"),
    ])

    def _audit_early_rows(payload, rows, validated, candidate_validated,
                          snapshot, now, max_age_sec, consumed,
                          price_guard_blocked):
        early_rows = [
            row for row in (payload.get("signals") or [])
            if isinstance(row, Mapping)
            and str(row.get("entry_lane") or "") == EARLY_LOW_LANE
            and str(row.get("action") or "") == "BUY_READY"
        ]
        if not early_rows:
            return set()
        day = now.strftime("%Y%m%d")
        chain = _audit_chains.get(day)
        if chain is None:
            chain = EarlyLowAuditChain(audit_stream, day)
            _audit_chains.clear()
            _audit_chains[day] = chain
            _audit_seen.clear()
        contract_keys = {
            (str(row.get("code") or ""), str(row.get("ts") or ""))
            for row in rows
            if str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        }
        selected_keys = {
            (str(row.get("code") or ""), str(row.get("ts") or ""))
            for row in validated
            if str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        }
        candidate_keys = {
            (str(row.get("code") or ""), str(row.get("ts") or ""))
            for row in candidate_validated
            if str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        }
        codes = snapshot.get("codes") or {}
        # ★[2026-08-12 보안수리 3번] 감사기록에 못 남긴 early_low 주문후보를 모은다.
        #   호출부(selector)가 이 집합에 든 (code, ts) 는 validated 에서 빼서 실주문을
        #   보류한다 = '증거 있는 주문만 실행'. seen 등록은 append 성공 후로 미뤄
        #   실패한 것은 다음 틱에 자연히 재시도된다.
        audit_failed: set[tuple[str, str]] = set()
        for row in early_rows:
            code = str(row.get("code") or "").zfill(6)
            row_ts = str(row.get("ts") or "")
            key = (code, row_ts)
            contract_pass = key in contract_keys
            selector_pass = key in selected_keys
            candidate_selector_pass = key in candidate_keys
            seen_key = (
                code, row_ts, contract_pass, selector_pass,
                candidate_selector_pass,
            )
            if seen_key in _audit_seen:
                # 기록 당시 크기 이상이면 증거 온전 - 스킵. 작아졌으면(삭제·절단)
                # seen 무효화하고 아래에서 재기록한다.
                try:
                    cur_size = chain.path.stat().st_size
                except OSError:
                    cur_size = -1
                if cur_size >= _audit_seen[seen_key]:
                    continue
                del _audit_seen[seen_key]
            raw = codes.get(code)
            written = chain.append({
                "event": "ORDER_GATE",
                "entry_lane": EARLY_LOW_LANE,
                "code": code,
                "name": str(row.get("name") or ""),
                "hr_rank": row.get("hr_rank"),
                "signal_row": dict(row),
                # 계약의 종목당 1행 중복제거(seen_codes)는 signals 목록 순서를 탄다.
                # 같은 종목의 앞선 행(다른 레인 포함)까지 순서대로 남겨야 재생이 같다.
                "same_code_signals": [
                    dict(item)
                    for item in (payload.get("signals") or [])
                    if isinstance(item, Mapping)
                    and str(item.get("code") or "").zfill(6) == code
                ],
                "payload_meta": {
                    "schema": str(payload.get("schema") or ""),
                    "date": str(payload.get("date") or ""),
                    "updated_at": str(payload.get("updated_at") or ""),
                    "mode": str(payload.get("mode") or ""),
                },
                "snapshot_raw": dict(raw) if isinstance(raw, Mapping) else None,
                "snapshot_ts": (
                    str(raw.get("ts") or "") if isinstance(raw, Mapping) else ""),
                "snapshot_op": (
                    abs(number(raw.get("op"))) if isinstance(raw, Mapping)
                    else 0.0),
                "snapshot_lo": (
                    abs(number(raw.get("lo"))) if isinstance(raw, Mapping)
                    else 0.0),
                "best_ask_px": (
                    abs(number(raw.get("best_ask_px"))) if isinstance(raw, Mapping)
                    else 0.0),
                "best_bid_px": (
                    abs(number(raw.get("best_bid_px"))) if isinstance(raw, Mapping)
                    else 0.0),
                "best_ask_qty": (
                    abs(number(raw.get("best_ask_qty"))) if isinstance(raw, Mapping)
                    else 0.0),
                "best_bid_qty": (
                    abs(number(raw.get("best_bid_qty"))) if isinstance(raw, Mapping)
                    else 0.0),
                "current_price": (
                    abs(number(raw.get("cur"))) if isinstance(raw, Mapping)
                    else 0.0),
                "broker_day_low": (
                    # ★[DAY-LOW-FIELD-FIX 20260819] 스냅샷 당일저가 키는 lo(FID18). day_low 는 유령 키(항상 0).
                    abs(number(raw.get("lo") or raw.get("day_low"))) if isinstance(raw, Mapping)
                    else 0.0),
                "anchor_low": number(row.get("anchor_low")),
                "anchor_low_ts": str(row.get("anchor_low_ts") or ""),
                "rebound_pct": number(row.get("rebound_pct")),
                "chase_blocked": bool(row.get("chase_blocked")),
                "signal_ts": str(row.get("ts") or ""),
                "signal_price": number(row.get("price")),
                "decision_now": now.isoformat(timespec="microseconds"),
                "selector_ts": now.isoformat(timespec="microseconds"),
                "selector_terminal_reason": (
                    "S03_PRICE_BELOW_10000" if key in price_guard_blocked else ""
                ),
                "max_age_sec": float(max_age_sec),
                "snapshot_max_age_sec": float(snapshot_max_age_sec),
                "consumed": sorted(str(item) for item in consumed),
                "early_low_live_enabled": bool(early_low_live_enabled),
                "flow_turn_live_enabled": bool(flow_turn_live_enabled),
                "order_mode": (
                    "LIVE" if early_low_live_enabled else "SHADOW_ORDER_ZERO"
                ),
                "contract_pass": contract_pass,
                "selector_pass": selector_pass,
                "candidate_selector_pass": candidate_selector_pass,
                "prod_sha": _audit_sha,
            })
            if written is None:
                # 감사 실패 - seen 미등록(다음 틱 재시도). 주문 예정(selector_pass)이면 보류 대상.
                if selector_pass:
                    audit_failed.add(key)
            else:
                # 기록 성공 - 그 시점 파일 크기를 함께 저장(삭제·절단 감지 기준).
                try:
                    _audit_seen[seen_key] = chain.path.stat().st_size
                except OSError:
                    pass  # 크기를 못 재면 등록하지 않아 다음 틱에 재확인한다.
        return audit_failed

    def selector(
        payload,
        *,
        now: datetime,
        max_age_sec: float,
        consumed=(),
    ):
        contract_payload = payload
        rows = select_fresh_signals(
            contract_payload,
            now=now,
            max_age_sec=max_age_sec,
            consumed=consumed,
        )
        snapshot = read_json(snapshot_path, {})
        codes = snapshot.get("codes") or {}
        decision_at = parse_dt(now.isoformat(), now)
        price_guard_blocked: set[tuple[str, str]] = set()

        # ★[DROP-REASON-LOG 2026-08-19 친구님 지시 "탈락 사유 기록"] 기록 전용 —
        #   판정 로직 무변경. 기록 실패는 삼켜서 주문 판정을 깨지 않는다.
        def _drop(sig_row, reason, **extra):
            try:
                rec = {
                    "ts": decision_at.isoformat(timespec="milliseconds"),
                    "code": str(sig_row.get("code") or "").zfill(6),
                    "name": str(sig_row.get("name") or ""),
                    "lane": str(sig_row.get("entry_lane") or ""),
                    "reason": reason,
                    "signal_ts": str(sig_row.get("ts") or ""),
                    "signal_reason": str(sig_row.get("reason") or ""),
                }
                rec.update(extra)
                DROP_LOG_DIR.mkdir(parents=True, exist_ok=True)
                out = DROP_LOG_DIR / f"s03_engine_drop_{decision_at:%Y%m%d}.jsonl"
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass

        # 계약(select_fresh_signals)이 조용히 버린 BUY_READY 도 사유를 남긴다.
        # 이미 소비된 신호는 제외(매 틱 재기록 방지). 세부 사유는 재계산하지 않고
        # 판독에 필요한 관측치(나이·순번·payload 갱신시각)만 싣는다.
        try:
            day_key = decision_at.strftime("%Y%m%d")
            fresh_ids = {str(r.get("signal_id") or "") for r in rows}
            used_ids = {str(item) for item in consumed}
            for sig in (contract_payload.get("signals") or []):
                if not isinstance(sig, Mapping):
                    continue
                if str(sig.get("action") or "") != "BUY_READY":
                    continue
                sig_id = _signal_id(day_key, sig)
                if (sig_id in fresh_ids or sig_id in used_ids
                        or sig_id in _contract_drop_seen):
                    continue
                _contract_drop_seen.add(sig_id)
                sig_at = parse_dt(sig.get("ts"), None)
                age = (decision_at - sig_at).total_seconds() if sig_at else -1.0
                _drop(sig, "CONTRACT_FILTERED",
                      age_sec=round(age, 3),
                      signal_sequence=sig.get("signal_sequence"),
                      contract_max_age_sec=float(max_age_sec),
                      payload_updated_at=str(contract_payload.get("updated_at") or ""))
        except Exception:
            pass

        validated = []
        candidate_validated = []
        for row in rows:
            raw = codes.get(str(row.get("code") or "").zfill(6))
            if not isinstance(raw, dict):
                _drop(row, "SNAPSHOT_CODE_MISSING")
                continue
            point_at = parse_dt(raw.get("ts"), decision_at)
            if abs((decision_at - point_at).total_seconds()) > snapshot_max_age_sec:
                _drop(row, "SNAPSHOT_TOO_OLD",
                      snapshot_ts=str(raw.get("ts") or ""),
                      age_sec=round(abs((decision_at - point_at).total_seconds()), 3))
                continue

            price = abs(number(raw.get("cur")))
            anchor_low = number(row.get("anchor_low"))
            open_price = number(row.get("open_price"))
            if price <= 0 or anchor_low <= 0:
                _drop(row, "PRICE_OR_ANCHOR_INVALID",
                      price=price, anchor_low=anchor_low)
                continue
            if price < S03_ORDER_MIN_PRICE:
                price_guard_blocked.add((
                    str(row.get("code") or "").zfill(6),
                    str(row.get("ts") or ""),
                ))
                _drop(row, "S03_PRICE_BELOW_10000", price=price)
                continue
            rebound = (price / anchor_low - 1.0) * 100.0

            def _flow_turn_pass() -> bool:
                if not flow_turn_live_enabled:
                    return True
                lane_name = str(row.get("entry_lane") or OPEN_CRASH_LANE)
                if lane_name == EARLY_LOW_LANE:
                    if not bool(row.get("flow_turn_ready")):
                        _drop(row, "FLOW_TURN_HISTORY_NOT_READY")
                        return False
                    recent_buy = number(row.get("flow_recent_buy_rate"))
                    recent_sell = number(row.get("flow_recent_sell_rate"))
                    baseline_buy = number(row.get("flow_baseline_buy_rate"))
                    baseline_sell = number(row.get("flow_baseline_sell_rate"))
                    price_responding = bool(row.get("flow_price_responding"))
                else:
                    recent_buy = number(row.get("recent_buy_rate_10s"))
                    recent_sell = number(row.get("recent_sell_rate_10s"))
                    baseline_buy = number(row.get("previous_buy_rate_10s"))
                    baseline_sell = number(row.get("previous_sell_rate_10s"))
                    price_responding = rebound > 0.0

                ask = abs(number(raw.get("best_ask_px")))
                bid = abs(number(raw.get("best_bid_px")))
                ask_qty = abs(number(raw.get("best_ask_qty")))
                bid_qty = abs(number(raw.get("best_bid_qty")))
                total_qty = ask_qty + bid_qty
                mid = (ask + bid) / 2.0 if ask > bid > 0 else 0.0
                micro = (
                    (ask * bid_qty + bid * ask_qty) / total_qty
                    if total_qty > 0 and mid > 0 else 0.0
                )
                decision = flow_turn_fast_decision(
                    recent_buy_rate=recent_buy,
                    recent_sell_rate=recent_sell,
                    baseline_buy_rate=baseline_buy,
                    baseline_sell_rate=baseline_sell,
                    price_responding=price_responding,
                    microprice_edge_bps=(
                        (micro / mid - 1.0) * 10000.0 if mid > 0 else 0.0
                    ),
                    best_bid_share=(bid_qty / total_qty if total_qty > 0 else 0.0),
                    spread_bps=(
                        (ask - bid) / mid * 10000.0 if mid > 0 else 999.0
                    ),
                )
                if not decision["ready"]:
                    _drop(
                        row,
                        "FLOW_TURN_FAST_BLOCK",
                        flow_score=decision["flow_score"],
                        flow_checks=decision["checks"],
                    )
                    return False
                row.update({
                    "flow_turn_fast": "READY",
                    "flow_turn_fast_score": decision["flow_score"],
                })
                return True

            def _record_bottom_confirm_shadow(lane_name: str) -> dict[str, Any]:
                """Record the complete approved decision without changing orders."""
                if lane_name == EARLY_LOW_LANE:
                    recent_buy = number(row.get("flow_recent_buy_rate"))
                    recent_sell = number(row.get("flow_recent_sell_rate"))
                    baseline_buy = number(row.get("flow_baseline_buy_rate"))
                    baseline_sell = number(row.get("flow_baseline_sell_rate"))
                    price_responding = bool(row.get("flow_price_responding"))
                else:
                    recent_buy = number(row.get("recent_buy_rate_10s"))
                    recent_sell = number(row.get("recent_sell_rate_10s"))
                    baseline_buy = number(row.get("previous_buy_rate_10s"))
                    baseline_sell = number(row.get("previous_sell_rate_10s"))
                    price_responding = rebound > 0.0
                ask = abs(number(raw.get("best_ask_px")))
                bid = abs(number(raw.get("best_bid_px")))
                ask_qty = abs(number(raw.get("best_ask_qty")))
                bid_qty = abs(number(raw.get("best_bid_qty")))
                total_qty = ask_qty + bid_qty
                mid = (ask + bid) / 2.0 if ask > bid > 0 else 0.0
                micro = (
                    (ask * bid_qty + bid * ask_qty) / total_qty
                    if total_qty > 0 and mid > 0 else 0.0
                )
                regime_band = _market_regime_at(Path(regime_path), decision_at)
                decision = bottom_confirm_decision(
                    entry_lane=lane_name,
                    signal_reason=str(row.get("reason") or ""),
                    rebound_pct=rebound,
                    regime_band=regime_band,
                    observe_sec=number(row.get("observe_sec")),
                    reset_steps=int(number(
                        row.get("dip_low_reset_steps") or row.get("reset_steps")
                    )),
                    pullback_depth_pct=number(row.get("pullback_depth_pct")),
                    higher_low_pct=number(row.get("higher_low_pct")),
                    second_rebound_pct=number(row.get("second_rebound_pct")),
                    recent_buy_rate=recent_buy,
                    recent_sell_rate=recent_sell,
                    baseline_buy_rate=baseline_buy,
                    baseline_sell_rate=baseline_sell,
                    price_responding=price_responding,
                    microprice_edge_bps=(
                        (micro / mid - 1.0) * 10000.0 if mid > 0 else 0.0
                    ),
                    best_bid_share=(bid_qty / total_qty if total_qty > 0 else 0.0),
                    spread_bps=(
                        (ask - bid) / mid * 10000.0 if mid > 0 else 999.0
                    ),
                )
                _drop(
                    row,
                    (
                        "BOTTOM_CONFIRM_SHADOW_READY"
                        if decision["ready"] else "BOTTOM_CONFIRM_SHADOW_BLOCK"
                    ),
                    regime_band=regime_band,
                    decision=decision,
                    signal_row=dict(row),
                    snapshot_raw=dict(raw),
                )
                return decision
            # ★[S03-LANE-FIX 2026-08-06 친구님 지시 "가로 해"] 레인마다 제 잣대로 검산한다.
            #   종전에는 1번 레인(OPEN_CRASH)의 잣대를 2번 레인 신호에도 들이댔다:
            #     · 가격대를 '시가 대비 -8%~-4%' 로 봤다 → 2번은 '당일 고점' 기준이라 축이 다르다
            #     · 반등을 1.0~1.5% 로 요구했다 → 2번 신호기는 0.5~1.0% 에서만 신호를 낸다
            #       = 1.0% 한 점에서만 스쳐 사실상 절대 통과 못 했다.
            #   이것이 S03 역대 매수 0건의 최종 원인이었다(1차 원인은 open_price 누락).
            #   되돌리기: backup\s03_fix_20260806\ 복원.
            lane = str(row.get("entry_lane") or OPEN_CRASH_LANE)
            bottom_shadow = _record_bottom_confirm_shadow(lane)
            if lane == EARLY_LOW_LANE:
                rebound_valid = (
                    EARLY_LOW_MIN_REBOUND_PCT
                    <= rebound <= EARLY_LOW_MAX_REBOUND_PCT
                )
                if not rebound_valid:
                    _drop(row, "EARLY_LOW_REBOUND_OUT_OF_BAND",
                          price=price, rebound_pct=round(rebound, 4))
                    continue
                if number(row.get("rapid_drop_pct")) > -EARLY_LOW_RAPID_DROP_PCT:
                    _drop(row, "EARLY_LOW_3M_DROP_NOT_CONFIRMED")
                    continue
                anchor_age = number(row.get("anchor_age_sec"), -1.0)
                if not 0.0 <= anchor_age <= EARLY_LOW_REBOUND_TIMEOUT_SEC:
                    _drop(row, "EARLY_LOW_60S_WINDOW_EXPIRED")
                    continue
                if number(row.get("low_stable_sec")) < EARLY_LOW_LOW_STABLE_SEC:
                    _drop(row, "EARLY_LOW_2S_STABILITY_NOT_CONFIRMED")
                    continue
                if int(number(row.get("up_ticks"))) < EARLY_LOW_MIN_UP_TICKS:
                    _drop(row, "EARLY_LOW_TWO_UP_TICKS_NOT_CONFIRMED")
                    continue
                ask = abs(number(raw.get("best_ask_px")))
                bid = abs(number(raw.get("best_bid_px")))
                ask_qty = abs(number(raw.get("best_ask_qty")))
                bid_qty = abs(number(raw.get("best_bid_qty")))
                if not (ask > bid > 0 and ask_qty > 0 and bid_qty > 0):
                    _drop(row, "EARLY_LOW_TOP_OF_BOOK_INVALID")
                    continue
                candidate_validated.append(row)
                if not early_low_live_enabled:
                    _drop(row, "EARLY_LOW_SHADOW_READY_ORDER_ZERO")
                    continue
                validated.append(row)
                continue
            if lane == INTRADAY_CRASH_LANE:
                # 낙폭(당일 고점 대비)은 신호기와 계약이 이미 검산했다.
                # 여기서는 '그 사이 저점에서 너무 멀어지지 않았나'만 다시 본다.
                intraday_high = number(row.get("intraday_high"))
                if intraday_high <= anchor_low:
                    _drop(row, "INTRADAY_HIGH_LE_ANCHOR",
                          intraday_high=intraday_high, anchor_low=anchor_low)
                    continue
                if not INTRADAY_MIN_REBOUND_PCT <= rebound <= INTRADAY_MAX_REBOUND_PCT:
                    _drop(row, "INTRADAY_REBOUND_OUT_OF_BAND",
                          price=price, rebound_pct=round(rebound, 4))
                    continue
            else:
                if open_price <= 0:
                    _drop(row, "OPEN_PRICE_MISSING")
                    continue
                anchor_drop = (anchor_low / open_price - 1.0) * 100.0
                if not anchor_drop <= OPEN_ARM_DROP_PCT:
                    _drop(row, "OPEN_ANCHOR_DROP_OUT_OF_BAND",
                          anchor_drop_pct=round(anchor_drop, 4))
                    continue
                if not OPEN_MIN_REBOUND_PCT <= rebound <= OPEN_MAX_REBOUND_PCT:
                    _drop(row, "OPEN_REBOUND_OUT_OF_BAND",
                          price=price, rebound_pct=round(rebound, 4))
                    continue

            current_buy = number(raw.get("buy_money_cum"), -1.0)
            current_sell = number(raw.get("sell_money_cum"), -1.0)
            signal_buy = number(row.get("current_buy_money_cum"), -1.0)
            signal_sell = number(row.get("current_sell_money_cum"), -1.0)
            if min(current_buy, current_sell, signal_buy, signal_sell) < 0:
                _drop(row, "MONEY_FIELDS_INVALID")
                continue
            if current_buy < signal_buy or current_sell < signal_sell:
                _drop(row, "MONEY_CUM_WENT_BACKWARDS")
                continue
            signal_at = parse_dt(row.get("ts"), decision_at)
            if point_at > signal_at and lane != INTRADAY_CRASH_LANE:
                delta_buy = current_buy - signal_buy
                delta_sell = current_sell - signal_sell
                if delta_buy <= delta_sell:
                    _drop(row, "BUY_DELTA_LE_SELL_DELTA",
                          delta_buy=delta_buy, delta_sell=delta_sell)
                    continue
            if bottom_all_lanes_live_enabled and not bottom_shadow["ready"]:
                _drop(row, "BOTTOM_CONFIRM_ALL_LANES_BLOCK")
                continue
            validated.append(row)
        # ★[2026-08-12 보안수리 3번] early_low 는 '감사 성공'이 실주문의 전제다.
        #   종전에는 감사 실패를 무시하고 주문을 냈다(증거 없는 주문 가능). 이제
        #   감사에 못 남긴 early_low 주문후보는 validated 에서 빼 보류한다.
        #   감사 배선 자체가 예외로 터지면 early_low 전부 보류(fail-closed).
        try:
            audit_failed = _audit_early_rows(
                payload, rows, validated, candidate_validated, snapshot, decision_at,
                max_age_sec, consumed, price_guard_blocked,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"S03_EARLY_LOW_AUDIT_FAILED error={exc!r}",
                file=sys.stderr, flush=True,
            )
            audit_failed = {
                (str(r.get("code") or "").zfill(6), str(r.get("ts") or ""))
                for r in validated
                if str(r.get("entry_lane") or "") == EARLY_LOW_LANE
            }
        if audit_failed:
            validated = [
                r for r in validated
                if not (
                    str(r.get("entry_lane") or "") == EARLY_LOW_LANE
                    and (str(r.get("code") or "").zfill(6),
                         str(r.get("ts") or "")) in audit_failed
                )
            ]
            print(
                "S03_EARLY_LOW_ORDER_HELD_NO_AUDIT codes="
                f"{sorted({c for c, _ in audit_failed})}",
                file=sys.stderr, flush=True,
            )
        return validated

    return selector


class Strategy03Engine(Strategy01Engine):
    def __init__(self, config: Config, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        base_signal_selector = self.signal_selector

        def lane_capped_selector(*args: Any, **selector_kwargs: Any):
            rows = base_signal_selector(*args, **selector_kwargs)
            return self._apply_lane_slot_limit(rows)

        self.signal_selector = lane_capped_selector
        audit_recorder = self.exit_engine.audit_recorder
        if self.config.audit_enabled:
            audit_recorder = HoldSellAuditRecorder(
                self.config.audit_root,
                [
                    Path(__file__).with_name("strategy_common_hold_sell_v1.py"),
                    Path(__file__),
                ],
                runtime_profile=strategy_profile_runtime_snapshot(
                    self.config.strategy_id
                ),
            )
        self.exit_engine = Strategy03HoldSellEngine(
            audit_recorder=audit_recorder)
        self._s03_daily_trend: dict[str, dict[str, float]] | None = None
        self._s03_atrp10: dict[str, float] | None = None
        self._s03_confirm_lane = ""
        self._reconcile_crash_claims()

    def _reconcile_crash_claims(self) -> None:
        """Restore S03/S06 ownership after the S03 order engine restarts."""
        if not crash_claim.enabled():
            return
        now = kst_now()
        claims = crash_claim.active_s03_claims(now)
        phases_by_code: dict[str, set[str]] = {}
        for position in self._active_positions().values():
            if self._position_entry_lane(position) != OPEN_CRASH_LANE:
                continue
            code = str(position.get("code") or "").zfill(6)
            phases_by_code.setdefault(code, set()).add(
                str(position.get("phase") or ""))
        for code, row in claims.items():
            state = str(row.get("state") or "")
            phases = phases_by_code.get(code, set())
            if state == "ORDERING":
                if phases & {"HOLD", "SELL_PENDING"}:
                    crash_claim.mark_bought(
                        code, now, order_id=str(row.get("order_id") or ""))
                elif not phases & {"BUY_PENDING", "RECOVERY_BLOCKED"}:
                    crash_claim.release_s03(
                        code, now, reason="S03_RESTART_NO_ACTIVE_ORDER")
            elif state == "BOUGHT" and not phases & {
                "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"
            }:
                crash_claim.release_s03(
                    code, now, reason="S03_RESTART_NO_ACTIVE_POSITION")

    @staticmethod
    def _position_entry_lane(position: Mapping[str, Any]) -> str:
        lane = str(position.get("entry_lane") or "")
        if lane in {OPEN_CRASH_LANE, INTRADAY_CRASH_LANE}:
            return lane
        entry_at = parse_dt(position.get("entry_at"))
        return (
            OPEN_CRASH_LANE
            if entry_at.time() < day_time(9, 20)
            else INTRADAY_CRASH_LANE
        )

    def _apply_lane_slot_limit(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Keep three concurrent S03 slots for each of the two entry lanes."""
        active = self._active_positions()
        remaining = {
            OPEN_CRASH_LANE: S03_LANE_SLOT_LIMIT,
            INTRADAY_CRASH_LANE: S03_LANE_SLOT_LIMIT,
        }
        for position in active.values():
            lane = self._position_entry_lane(position)
            remaining[lane] = max(0, remaining[lane] - 1)

        selected: list[dict[str, Any]] = []
        reserved_codes: set[str] = set()
        for row in rows:
            lane = str(row.get("entry_lane") or OPEN_CRASH_LANE)
            if lane not in remaining:
                continue
            code = str(row.get("code") or "").zfill(6)
            if code in active or code in reserved_codes:
                selected.append(row)
                continue
            if remaining[lane] <= 0:
                continue
            remaining[lane] -= 1
            reserved_codes.add(code)
            selected.append(row)
        return selected

    def _event(
        self,
        event: str,
        *,
        code: str = "",
        name: str = "",
        price: float = 0.0,
        quantity: int = 0,
        reason: str = "",
        order_no: str = "",
    ) -> None:
        if event in {
            "BUY_CONFIRMED", "SHADOW_BUY",
            "BUY_ADD_CONFIRMED", "SHADOW_BUY_ADD",
        } and self._s03_confirm_lane:
            reason = f"{reason} lane={self._s03_confirm_lane}"
        if event in {"BUY_REJECTED", "BUY_NOT_CREATED", "BUY_CANCELLED"} and code:
            crash_claim.release_s03(code, kst_now(), reason=event)
        super()._event(
            event,
            code=code,
            name=name,
            price=price,
            quantity=quantity,
            reason=reason,
            order_no=order_no,
        )

    def _order_lifecycle(
        self,
        event: str,
        position: Mapping[str, Any],
        *,
        fill_quantity: int = 0,
        fill_price: float = 0.0,
        fill_source: str = "",
        observed_at: datetime | None = None,
    ) -> None:
        if (
            event == "BUY_PREPARED"
            and self._position_entry_lane(position) == OPEN_CRASH_LANE
            and crash_claim.enabled()
        ):
            pending = position.get("pending") or {}
            claim_ok = crash_claim.mark_ordering(
                str(position.get("code") or "").zfill(6),
                observed_at or kst_now(),
                order_id=str(
                    pending.get("order_no")
                    or pending.get("idempotency_key")
                    or ""),
            )
            if not claim_ok:
                mutable = position if isinstance(position, dict) else None
                if mutable is not None:
                    mutable["phase"] = "FAILED"
                    self._release_slot(mutable)
                    mutable["slot_reserved"] = False
                self._event(
                    "BUY_REJECTED",
                    code=str(position.get("code") or "").zfill(6),
                    name=str(position.get("name") or ""),
                    price=number(position.get("last_price")),
                    reason="S03_CRASH_CLAIM_NOT_HELD_PREORDER",
                )
                self._save()
                raise S03CrashClaimNotHeld(
                    str(position.get("code") or "").zfill(6))
        super()._order_lifecycle(
            event,
            position,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            fill_source=fill_source,
            observed_at=observed_at,
        )

    def tick(self, now: datetime | None = None) -> dict[str, Any]:
        try:
            return super().tick(now)
        except S03CrashClaimNotHeld as exc:
            self.log.error(
                "S03_CRASH_CLAIM_NOT_HELD_PREORDER code=%s", exc)
            return self.state

    def _append_s03_entry_context(
        self,
        position: Mapping[str, Any],
        observed_at: datetime,
        *,
        shadow: bool,
    ) -> None:
        record = {
            "ts": observed_at.isoformat(),
            "strategy_id": self.config.strategy_id.value,
            "event": "S03_ENTRY_CONTEXT",
            "code": str(position.get("code") or "").zfill(6),
            "name": str(position.get("name") or ""),
            "lane": str(position.get("entry_lane") or ""),
            "shadow_order": bool(shadow),
            "s03_entry_reference_low": number(
                position.get("s03_entry_reference_low")
            ),
            "atrp10_pct": position.get("s03_atrp10_pct"),
            "drop_pct": position.get("s03_entry_drop_pct"),
            "drop_atrp_multiple": position.get("s03_drop_atrp_multiple"),
            "kosdaq_5m_change_pct": position.get("s03_kosdaq_5m_change_pct"),
            "kosdaq_index_ts": position.get("s03_kosdaq_index_ts"),
            "kosdaq_prior_ts": position.get("s03_kosdaq_prior_ts"),
            "kosdaq_sample_interval_sec": position.get(
                "s03_kosdaq_sample_interval_sec"
            ),
            "kosdaq_source": position.get("s03_kosdaq_source"),
            "s03_bottom_quality_v2": position.get("s03_bottom_quality_v2"),
            "shadow_only": {
                "low_break_exit": False,
                "atr_normalization": True,
                "kosdaq_5m_filter": True,
                "bottom_quality_v2": True,
            },
            "live_rules": {"low_break_exit": True},
        }
        path = S03_ENTRY_CONTEXT_AUDIT_DIR / f"s03_entry_context_{observed_at:%Y%m%d}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self.log.exception("S03_ENTRY_CONTEXT_AUDIT_WRITE_FAILED")

    def _confirm_entry(
        self,
        position: dict[str, Any],
        quantity: int,
        fill_price: float,
        observed_at: datetime,
        *,
        shadow: bool = False,
    ) -> None:
        signal = position.get("signal_snapshot") or {}
        claim_order_id = str(
            ((position.get("pending") or {}).get("order_no") or ""))
        lane = str(
            position.get("entry_lane")
            or signal.get("entry_lane")
            or self._position_entry_lane(position)
        )
        reference_low = number(signal.get("anchor_low"))
        self._load_s03_daily_trend()
        atrp = number((self._s03_atrp10 or {}).get(
            str(position.get("code") or "").zfill(6)
        ))
        drop_pct = _s03_entry_drop_pct(signal, lane)
        kosdaq = _s03_kosdaq_5m_context(
            S03_KOSDAQ_INDEX_PATH,
            S03_KOSDAQ_HISTORY_PATH,
            observed_at,
        )
        trend = (self._s03_daily_trend or {}).get(
            str(position.get("code") or "").zfill(6), {}
        )
        bottom_quality_v2 = _s03_bottom_quality_v2_shadow(
            signal,
            entry_price=number(fill_price or position.get("last_price")),
            ma20=number(trend.get("ma20")),
            atrp10=atrp,
            kosdaq_5m_change_pct=kosdaq["kosdaq_5m_change_pct"],
        )
        position.update({
            "entry_lane": lane,
            "s03_entry_reference_low": reference_low,
            "s03_atrp10_pct": round(atrp, 6) if atrp > 0 else None,
            "s03_entry_drop_pct": round(drop_pct, 6),
            "s03_drop_atrp_multiple": (
                round(drop_pct / atrp, 6) if atrp > 0 else None
            ),
            "s03_kosdaq_5m_change_pct": kosdaq["kosdaq_5m_change_pct"],
            "s03_kosdaq_index_ts": kosdaq["kosdaq_index_ts"],
            "s03_kosdaq_prior_ts": kosdaq["kosdaq_prior_ts"],
            "s03_kosdaq_sample_interval_sec": kosdaq[
                "kosdaq_sample_interval_sec"
            ],
            "s03_kosdaq_source": kosdaq["kosdaq_source"],
            "s03_bottom_quality_v2": bottom_quality_v2,
        })
        self._s03_confirm_lane = lane
        try:
            super()._confirm_entry(
                position,
                quantity,
                fill_price,
                observed_at,
                shadow=shadow,
            )
        finally:
            self._s03_confirm_lane = ""
        self._append_s03_entry_context(position, observed_at, shadow=shadow)
        if lane == OPEN_CRASH_LANE:
            code = str(position.get("code") or "").zfill(6)
            if shadow:
                crash_claim.release_s03(
                    code, observed_at, reason="SHADOW_ORDER_ZERO")
            else:
                crash_claim.mark_bought(
                    code, observed_at, order_id=claim_order_id)

    def _confirm_exit(
        self,
        position: dict[str, Any],
        fill_price: float,
        reason: str,
        *,
        shadow: bool = False,
    ) -> None:
        lane = self._position_entry_lane(position)
        code = str(position.get("code") or "").zfill(6)
        super()._confirm_exit(
            position, fill_price, reason, shadow=shadow)
        if lane == OPEN_CRASH_LANE:
            crash_claim.release_s03(
                code, kst_now(), reason="S03_POSITION_CLOSED")

    def _load_s03_daily_trend(self) -> None:
        if self._s03_daily_trend is not None:
            return
        self._s03_daily_trend = {}
        self._s03_atrp10 = {}
        session_day = str(self.state.get("date") or "")
        if len(session_day) != 8 or not session_day.isdigit():
            self.log.warning("S03 daily trend disabled: invalid session date")
            return
        by_code: dict[str, dict[str, float]] = {}
        by_code_ohlc: dict[str, dict[str, tuple[float, float, float]]] = {}
        try:
            with self.config.eod_bars_path.open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    high = number(raw.get("high"))
                    low = number(raw.get("low"))
                    if (
                        len(code) == 6
                        and code.isdigit()
                        and day < session_day
                        and len(day) == 8
                        and day.isdigit()
                        and close > 0
                    ):
                        by_code.setdefault(code, {})[day] = close
                        if high >= low > 0:
                            by_code_ohlc.setdefault(code, {})[day] = (
                                high, low, close
                            )
        except OSError:
            self.log.warning("S03 daily trend disabled: EOD bars unavailable")
            return

        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma20_prev = sum(closes[-21:-1]) / 20
            self._s03_daily_trend[code] = {
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma20_prev": ma20_prev,
            }
        for code, series in by_code_ohlc.items():
            days = sorted(series)
            if len(days) >= 10:
                self._s03_atrp10[code] = atrp10_pct(
                    [series[day] for day in days]
                )

    def _daily_ma_permit(self, code: str, price: float,
                         buy_side=None) -> bool:
        """★[MA3-COMMON 2026-08-03] 3분봉 5/10/20선 + 매수세 우위로 통일(공용코어와 동일).

        종전 S03 판정은 일봉 5선>10선·20선 우상향 + 3분봉 고가≥일봉 5선이었다.
        3분봉 고가를 '일봉' 5선과 비교하는 혼합이라, 일봉 5선이 장중 가격보다
        한참 아래인 종목은 상승보유가 영구 참이 됐다.
        되돌리기: backup\\strategy_03_rotation_engine_v1_20260803_ma3wire.py
        """
        return ma3_rider_permit(code, price, buy_side=buy_side)

    def _position_force_exit_at(
        self,
        position: dict[str, Any],
    ) -> day_time:
        entry_at = parse_dt(position.get("entry_at"))
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        # ★[S03-EXPRESS 2026-08-06] 09:50 → 10:30 (위 open_profile 주석 참조).
        return day_time(10, 30) if is_open_lane else self.config.force_exit

    def _completed_open_ma5_broken(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> bool:
        # ★[MA3-COMMON 2026-08-03] 기준선을 일봉 5선 → 3분봉 5선으로 교체.
        #   이 함수는 daily_ma5_broken(흐름역전 민감도 조절)을 채운다. 일봉 5선은
        #   장중에 안 움직여서 '5선을 깼다'가 사실상 발생하지 않았다.
        code = str(position["code"]).zfill(6)
        price = number(point.get("price"))
        rows = ma3_rows(code)
        if not rows:
            return False
        ma5 = rows["ma5"]
        if price >= ma5:
            position["s03_ma5_seen_above"] = True

        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        previous = ((source or {}).get(position["code"]) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False
        observed_at = point["ts"]
        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]), minute=int(hm[2:]), second=0, microsecond=0
            )
        except ValueError:
            return False
        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        latest_completed_minute = current_minute - timedelta(minutes=1)
        if latest_completed_minute < first_post_entry_minute:
            return False
        latest = previous[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            position.get("s03_ma5_seen_above")
            and latest_close > 0
            and latest_close < ma5
            and number(point.get("price")) < ma5
        )

    def _completed_open_structure(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[bool, str]:
        """Return a new post-entry 3m-support/1m-close break.

        The entry minute is deliberately excluded. The three completed
        one-minute bars immediately before the latest completed one-minute
        bar form the post-entry three-minute support. The latest completed
        one-minute close must finish below that support.
        """
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        code = str(position.get("code") or "").zfill(6)
        previous = ((source or {}).get(code) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False, ""

        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False, ""
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]),
                minute=int(hm[2:]),
                second=0,
                microsecond=0,
            )
        except ValueError:
            return False, ""
        if abs((observed_at - current_minute).total_seconds()) > 90:
            return False, ""

        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        full_post_entry_count = int(
            (current_minute - first_post_entry_minute).total_seconds() // 60
        )
        latest_key = (current_minute - timedelta(minutes=1)).strftime("%Y%m%d%H%M")
        if full_post_entry_count < 4:
            return False, latest_key

        post_entry = previous[-min(full_post_entry_count, len(previous)):]
        if len(post_entry) < 4:
            return False, latest_key
        baseline_lows = [
            number(bar[2]) for bar in post_entry[-4:-1]
            if len(bar) >= 4 and number(bar[2]) > 0
        ]
        latest = post_entry[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            len(baseline_lows) == 3
            and latest_close > 0
            and latest_close < min(baseline_lows)
        ), latest_key

    def _open_structure_break_active(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> bool:
        broken, break_key = self._completed_open_structure(position, observed_at)
        if not break_key:
            return False

        tracked_key = str(position.get("s03_structure_bar_key") or "")
        hold_payload = position.get("hold_state")
        if break_key != tracked_key:
            position["s03_structure_bar_key"] = break_key
            position["s03_structure_watch_started"] = bool(broken)
            if isinstance(hold_payload, dict):
                hold_payload["valley_morning_break_since"] = ""
            return broken

        if not broken:
            position["s03_structure_watch_started"] = False
            return False
        if not position.get("s03_structure_watch_started"):
            return False
        if isinstance(hold_payload, dict) and hold_payload.get(
            "valley_morning_break_since"
        ):
            return True

        # This completed one-minute break already received its single 10s
        # exact-flow confirmation and was cancelled. A new completed bar is
        # required before another structure-break watch may start.
        position["s03_structure_watch_started"] = False
        return False

    def _build_observation(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> HoldSellObservation:
        observation = super()._build_observation(position, point)
        entry_at = parse_dt(position.get("entry_at"), point["ts"])
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane in {EARLY_LOW_LANE, OPEN_CRASH_LANE}
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        if not is_open_lane:
            return observation

        exact = point["buy_money_cum"] >= 0 and point["sell_money_cum"] >= 0
        rate10 = self.windows.rates(position["code"], 10) if exact else None
        exact_valid = bool(rate10 and rate10[0] + rate10[1] > 0)
        return replace(
            observation,
            daily_ma5_broken=self._completed_open_ma5_broken(position, point),
            structure_broken=self._open_structure_break_active(
                position, point["ts"]
            ),
            valley_exact_flow_valid=exact_valid,
            valley_exact_sell_dominant=bool(
                exact_valid and rate10 and rate10[1] > rate10[0]
            ),
        )

    def _evaluate_exit(
        self,
        position: dict[str, Any],
        now: datetime,
    ) -> None:
        engine = self.exit_engine
        if isinstance(engine, Strategy03HoldSellEngine):
            engine.set_s03_entry_reference_low(
                position.get("s03_entry_reference_low")
            )
            engine.set_s03_early_peak_watch_since(
                position.get("s03_early_peak_watch_since")
            )
        try:
            super()._evaluate_exit(position, now)
        finally:
            if isinstance(engine, Strategy03HoldSellEngine):
                watch_since = engine.get_s03_early_peak_watch_since()
                position["s03_early_peak_watch_since"] = (
                    watch_since.isoformat() if watch_since is not None else ""
                )
                engine.set_s03_entry_reference_low(0)
                engine.set_s03_early_peak_watch_since(None)


@dataclass(frozen=True)
class Strategy03Config(Config):
    max_cycles_per_code: int = 2

    def __post_init__(self) -> None:
        if self.quantity not in {1, 2}:
            raise ValueError("Strategy 03 requires one or two shares")
        if self.max_slots != 6:
            raise ValueError("Strategy 03 requires exactly six concurrent slots")
        if self.max_daily_codes != 6:
            raise ValueError("Strategy 03 requires exactly six distinct codes per day")
        if self.max_cycles_per_code != 2:
            raise ValueError("Strategy 03 permits exactly two entries per code")
        if self.rotation_capital_krw <= 0:
            raise ValueError("rotation_capital_krw must be positive")
        if self.max_sell_retries < 1:
            raise ValueError("max_sell_retries must be positive")
        if not all((
            self.state_schema,
            self.strategy_slug,
            self.strategy_label,
            self.slot_owner,
            self.broker_order_prefix,
            self.event_prefix,
        )):
            raise ValueError("strategy identity fields must not be empty")


def build_config() -> Strategy03Config:
    return Strategy03Config(
        signal_path=Path(
            r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(
            r"C:\stock_bot\data\strategy_03_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_03_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_03_rotation_v1.log"),
        approval_path=Path(
            r"C:\stock_bot\config\strategy_03_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_03_off.flag"),
        manual_buy_block_path=Path(
            r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_03_rotation_v1.lock"),
        live_requested=(
            os.environ.get("S03_LIVE", "NO").strip().upper() == "YES"),
        quantity=capital_config.get_order_quantity(),
        max_slots=int(os.environ.get("S03_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S03_MAX_DAILY_CODES", "6")),
        max_cycles_per_code=int(os.environ.get("S03_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=capital_config.get_limit("daily_total_max"),
        max_sell_retries=int(os.environ.get("S03_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get(
            "S03_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get(
            "S03_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get(
            "S03_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S03_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S03_LOOP_SEC", "1")),
        entry_start=day_time(9, 0),
        entry_end=day_time(14, 30),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_03_rotation_engine_v1",
        strategy_id=StrategyId.VALLEY_MORNING_CRASH,
        strategy_slug="strategy03",
        strategy_label="Strategy 03 Valley Rapid Rebound",
        slot_owner="STRATEGY03",
        broker_order_prefix="STRATEGY03",
        event_prefix="strategy_03",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 03 is already running.", flush=True)
        return 0
    try:
        selector = make_strategy03_signal_selector(
            config.snapshot_path, config.snapshot_max_age_sec)
        return Strategy03Engine(
            config,
            signal_selector=selector,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

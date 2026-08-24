# -*- coding: utf-8 -*-
"""레짐스탑일 S01/S02/S03 역할 분류기 — 주문 0 독립 그림자.

보호된 생산 전략과 브로커를 import하지 않는다. 입력 한 건을 역할 후보로만
분류하며 live_eligible=False, order_qty=0을 항상 보장한다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any


@dataclass(frozen=True)
class RegimeRoleConfig:
    regime_stop_pct: float = -3.0
    # 코스닥 공식 등락률은 현재 태스크가 5분 주기다. 방향(RED) 참조만 하고
    # 빠른 반등 판정은 1초 주기 전략 감시종목 대용지수가 담당한다.
    max_market_age_sec: float = 360.0
    max_stock_age_sec: float = 4.0
    max_flow_age_sec: float = 8.0
    max_high_range_age_sec: float = 5.0
    max_high_range_rank: int = 40
    max_spread_bps: float = 35.0
    min_best_bid_share: float = 0.50
    s01_min_relative_pct: float = 3.0
    s02_min_relative_pct: float = 2.0
    s02_low_floor_pct: float = -10.0
    s02_low_ceiling_pct: float = -3.0
    s02_min_rebound_pct: float = 0.5
    s02_max_rebound_pct: float = 2.0
    s03_low_ceiling_pct: float = -10.0
    s03_min_rebound_pct: float = 1.0
    s03_max_rebound_pct: float = 2.0
    reversal_min_no_new_low_sec: float = 60.0
    s01_min_no_new_low_sec: float = 5.0
    s01_start: time = time(9, 0)
    s01_end: time = time(9, 20)
    s02_start: time = time(9, 0)
    s02_end: time = time(14, 20)
    s03_start: time = time(9, 2)
    s03_end: time = time(9, 15)


@dataclass(frozen=True)
class RegimeRoleObservation:
    ts: datetime
    code: str
    market_pct: float
    market_age_sec: float
    price: float
    open_price: float
    previous_close: float
    day_low: float
    rebound_pct: float
    no_new_low_sec: float
    flow_turn: bool
    che_rising: bool
    order_book_fresh: bool
    spread_bps: float
    best_bid_share: float
    vi_suspect: bool
    high_range_rank: int
    money_speed_ratio: float | None = None
    turnover_pct: float | None = None
    volatility_quality: str = ""
    stock_age_sec: float = 0.0
    flow_age_sec: float = 0.0
    high_range_age_sec: float = 0.0
    exact_flow: bool = True
    s01_strategy_ready: bool = False
    s02_strategy_ready: bool = False
    s03_strategy_ready: bool = False
    market_source: str = ""
    stock_source: str = ""
    flow_source: str = ""
    high_range_source: str = ""
    market_recovery_state: str = "RED"
    market_recovery_age_sec: float = 0.0
    latched_role: str = ""
    latched_day_low: float = 0.0
    latch_age_sec: float = 0.0
    latch_valid: bool = False


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _priority_score(
    relative_pct: float,
    observation: RegimeRoleObservation,
) -> tuple[int, list[str]]:
    """속도·회전율·변동성은 차단하지 않고 후보 순위에만 반영한다."""
    score = 0
    reasons: list[str] = []
    if relative_pct >= 5.0:
        score += 2; reasons.append("RELATIVE_5P")
    elif relative_pct >= 3.0:
        score += 1; reasons.append("RELATIVE_3P")
    if observation.flow_turn:
        score += 2; reasons.append("FLOW_TURN")
    if observation.che_rising:
        score += 1; reasons.append("CHE_RISING")
    speed = observation.money_speed_ratio
    if speed is not None and not _finite(speed):
        speed = None
    if speed is not None and speed >= 3.0:
        score += 2; reasons.append("MONEY_SPEED_3X")
    elif speed is not None and speed >= 1.0:
        score += 1; reasons.append("MONEY_SPEED_1X")
    turnover = observation.turnover_pct
    if turnover is not None and not _finite(turnover):
        turnover = None
    if turnover is not None and turnover >= 0.30:
        score += 2; reasons.append("TURNOVER_HIGH")
    elif turnover is not None and turnover >= 0.10:
        score += 1; reasons.append("TURNOVER_OK")
    quality = str(observation.volatility_quality or "").upper()
    if any(token in quality for token in ("GOOD", "PASS", "STABLE")):
        score += 1; reasons.append("VOLATILITY_QUALITY")
    return score, reasons


def classify_regime_role(
    observation: RegimeRoleObservation,
    config: RegimeRoleConfig | None = None,
) -> dict[str, Any]:
    cfg = config or RegimeRoleConfig()
    numeric_valid = _finite(
        observation.market_pct, observation.market_age_sec,
        observation.stock_age_sec, observation.flow_age_sec,
        observation.high_range_age_sec, observation.price,
        observation.open_price, observation.previous_close,
        observation.day_low, observation.rebound_pct,
        observation.no_new_low_sec, observation.spread_bps,
        observation.best_bid_share, observation.market_recovery_age_sec,
    )
    stock_pct = (
        (observation.price / observation.previous_close - 1.0) * 100.0
        if observation.price > 0 and observation.previous_close > 0 else None
    )
    low_pct = (
        (observation.day_low / observation.previous_close - 1.0) * 100.0
        if observation.day_low > 0 and observation.previous_close > 0 else None
    )
    relative_pct = (
        stock_pct - observation.market_pct if stock_pct is not None else None
    )
    common_failed: list[str] = []
    if not numeric_valid:
        common_failed.append("NON_FINITE_INPUT")
    if observation.market_pct > cfg.regime_stop_pct:
        common_failed.append("REGIME_STOP_NOT_ACTIVE")
    recovery_state = str(observation.market_recovery_state).upper()
    market_ready = recovery_state in {"FAST_AMBER", "AMBER"}
    if observation.market_age_sec < 0 or observation.market_age_sec > cfg.max_market_age_sec:
        common_failed.append("MARKET_STALE")
    if observation.stock_age_sec < 0 or observation.stock_age_sec > cfg.max_stock_age_sec:
        common_failed.append("STOCK_STALE")
    if observation.flow_age_sec < 0 or observation.flow_age_sec > cfg.max_flow_age_sec:
        common_failed.append("FLOW_STALE")
    if (
        observation.high_range_age_sec < 0
        or observation.high_range_age_sec > cfg.max_high_range_age_sec
    ):
        common_failed.append("HIGH_RANGE_STALE")
    if not observation.exact_flow:
        common_failed.append("FLOW_NOT_EXACT")
    if not (1 <= observation.high_range_rank <= cfg.max_high_range_rank):
        common_failed.append("OUTSIDE_HIGH_RANGE_TOP40")
    if not observation.order_book_fresh:
        common_failed.append("BOOK_STALE")
    elif observation.spread_bps > cfg.max_spread_bps:
        common_failed.append("SPREAD_WIDE")
    elif observation.best_bid_share < cfg.min_best_bid_share:
        common_failed.append("BID_SUPPORT_LOW")
    if not observation.flow_turn:
        common_failed.append("FLOW_TURN_WAIT")
    if not observation.che_rising:
        common_failed.append("CHE_NOT_RISING")
    if observation.vi_suspect:
        common_failed.append("VI_ACTIVE")

    role = "NONE"
    role_failed: list[str] = []
    if not common_failed and stock_pct is not None and relative_pct is not None:
        if (
            cfg.s01_start <= observation.ts.time() < cfg.s01_end
            and observation.price >= observation.open_price > 0
            and observation.price >= observation.previous_close
            and relative_pct >= cfg.s01_min_relative_pct
            and observation.no_new_low_sec >= cfg.s01_min_no_new_low_sec
        ):
            if observation.s01_strategy_ready:
                role = "S01_CRASH_RS_LEADER"
            else:
                role_failed.append("S01_FINAL_GATE_WAIT")
        elif (
            cfg.s03_start <= observation.ts.time() <= cfg.s03_end
            and low_pct is not None and low_pct <= cfg.s03_low_ceiling_pct
            and observation.price < observation.previous_close
            and cfg.s03_min_rebound_pct <= observation.rebound_pct <= cfg.s03_max_rebound_pct
            and observation.no_new_low_sec >= cfg.reversal_min_no_new_low_sec
        ):
            if observation.s03_strategy_ready:
                role = "S03_DEEP_CRASH_REVERSAL"
            else:
                role_failed.append("S03_FINAL_GATE_WAIT")
        elif (
            cfg.s02_start <= observation.ts.time() < cfg.s02_end
            and observation.price < observation.open_price
            and observation.price < observation.previous_close
            and low_pct is not None
            and cfg.s02_low_floor_pct < low_pct <= cfg.s02_low_ceiling_pct
            and relative_pct >= cfg.s02_min_relative_pct
            and cfg.s02_min_rebound_pct <= observation.rebound_pct <= cfg.s02_max_rebound_pct
            and observation.no_new_low_sec >= cfg.reversal_min_no_new_low_sec
        ):
            if observation.s02_strategy_ready:
                role = "S02_SLOW_CRASH_RECOVERY"
            else:
                role_failed.append("S02_FINAL_GATE_WAIT")
        elif (
            market_ready and observation.latch_valid
            and observation.latched_role in ROLE_PRIORITY
            and observation.latched_day_low > 0
            and observation.day_low >= observation.latched_day_low
            and observation.price > observation.latched_day_low
        ):
            role = observation.latched_role
        else:
            role_failed.append("NO_EXCLUSIVE_ROLE_MATCH")

    score, score_reasons = _priority_score(relative_pct or 0.0, observation)
    raw_role_candidate = role != "NONE"
    permission_candidate = raw_role_candidate and market_ready
    permission_reason = (
        "READY" if permission_candidate
        else "MARKET_RECOVERY_WAIT" if raw_role_candidate
        else "|".join(common_failed + role_failed)
    )
    return {
        "schema": "regime_exception_role_shadow_v1",
        "mode": "SHADOW_ORDER_ZERO",
        "live_eligible": False,
        "order_qty": 0,
        "code": str(observation.code).zfill(6),
        "observed_at": observation.ts.isoformat(timespec="milliseconds"),
        "role": role,
        "candidate": permission_candidate,
        "raw_role_candidate": raw_role_candidate,
        "from_latch": bool(role != "NONE" and observation.latch_valid
                           and role == observation.latched_role),
        "reason": permission_reason,
        "market_pct": round(observation.market_pct, 4),
        "stock_pct": round(stock_pct, 4) if stock_pct is not None else None,
        "relative_strength_pct": round(relative_pct, 4) if relative_pct is not None else None,
        "day_low_pct": round(low_pct, 4) if low_pct is not None else None,
        "priority_score": score,
        "priority_reasons": score_reasons,
        "source_trace": {
            "market": observation.market_source,
            "stock": observation.stock_source,
            "flow": observation.flow_source,
            "high_range": observation.high_range_source,
        },
        "config": asdict(cfg),
    }


ROLE_PRIORITY = {
    "S01_CRASH_RS_LEADER": 3,
    "S03_DEEP_CRASH_REVERSAL": 2,
    "S02_SLOW_CRASH_RECOVERY": 1,
}


@dataclass
class RegimeExceptionShadowLedger:
    """주문 0 후보도 하루 한 종목·한 전략만 소유하고 재진입시키지 않는다."""
    day: str = ""
    selected_code: str = ""
    entered_codes: set[str] = field(default_factory=set)
    owner_by_code: dict[str, str] = field(default_factory=dict)

    def _roll_day(self, ts: datetime) -> None:
        day = ts.strftime("%Y%m%d")
        if self.day != day:
            self.day = day
            self.selected_code = ""
            self.entered_codes.clear()
            self.owner_by_code.clear()

    def select(
        self,
        observations: list[RegimeRoleObservation],
        config: RegimeRoleConfig | None = None,
    ) -> list[dict[str, Any]]:
        if not observations:
            return []
        self._roll_day(min(row.ts for row in observations))
        results = [classify_regime_role(row, config) for row in observations]
        eligible = [
            row for row in results
            if row["candidate"] and row["code"] not in self.entered_codes
        ]
        eligible.sort(key=lambda row: (
            -ROLE_PRIORITY.get(str(row["role"]), 0),
            -int(row["priority_score"]),
            str(row["code"]),
        ))
        chosen = eligible[0] if eligible and not self.selected_code else None
        for row in results:
            row["shadow_selected"] = bool(chosen is row)
            if chosen is row:
                self.selected_code = str(row["code"])
                self.entered_codes.add(self.selected_code)
                self.owner_by_code[self.selected_code] = str(row["role"])
                row["selection_reason"] = "DAILY_SINGLE_SLOT_SELECTED"
            elif row["candidate"]:
                row["selection_reason"] = (
                    "REENTRY_BLOCK" if row["code"] in self.entered_codes
                    else "DAILY_SINGLE_SLOT_OCCUPIED"
                )
            else:
                row["selection_reason"] = "NOT_CANDIDATE"
        return results

# -*- coding: utf-8 -*-
"""Strategy 03 FLOW_TURN_FAST and regime-aware bottom confirmation.

Pure decisions only: no broker import, order call, launcher flag, or state write.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class FlowTurnFastConfig:
    sell_deceleration_ratio: float = 0.80
    buy_acceleration_ratio: float = 1.20
    min_flow_score: int = 2
    min_best_bid_share: float = 0.50
    max_spread_bps: float = 35.0


@dataclass(frozen=True)
class BottomConfirmConfig:
    strong_max_rebound_pct: float = 1.50
    retest_max_rebound_pct: float = 2.00
    min_pullback_pct: float = 0.40
    min_higher_low_pct: float = 0.30
    min_second_rebound_pct: float = 0.50
    weak_min_observe_sec: float = 300.0
    weak_min_reset_steps: int = 1


def flow_turn_fast_decision(
    *,
    recent_buy_rate: float,
    recent_sell_rate: float,
    baseline_buy_rate: float,
    baseline_sell_rate: float,
    price_responding: bool,
    microprice_edge_bps: float,
    best_bid_share: float,
    spread_bps: float,
    config: FlowTurnFastConfig | None = None,
) -> Dict[str, Any]:
    cfg = config or FlowTurnFastConfig()
    checks = {
        "sell_decelerating": (
            recent_sell_rate <= baseline_sell_rate * cfg.sell_deceleration_ratio
        ),
        "buy_accelerating": (
            recent_buy_rate >= baseline_buy_rate * cfg.buy_acceleration_ratio
        ),
        "buy_flow_leading": recent_buy_rate > recent_sell_rate,
        "price_responding": bool(price_responding),
        "microprice_positive": microprice_edge_bps > 0.0,
        "best_bid_majority": best_bid_share >= cfg.min_best_bid_share,
        "spread_ok": 0.0 < spread_bps <= cfg.max_spread_bps,
    }
    flow_score = sum(checks[key] for key in (
        "sell_decelerating", "buy_accelerating", "buy_flow_leading"
    ))
    ready = bool(
        checks["price_responding"]
        and checks["microprice_positive"]
        and checks["best_bid_majority"]
        and checks["spread_ok"]
        and flow_score >= cfg.min_flow_score
    )
    return {
        "action": "FLOW_TURN_FAST_READY" if ready else "BLOCK_RESET",
        "ready": ready,
        "flow_score": flow_score,
        "checks": checks,
    }


def regime_group(regime_band: str) -> str:
    value = str(regime_band or "").strip().upper()
    if value in {"BULL", "LEAN_BULL", "LEAN_BULL_US"}:
        return "STRONG"
    if value in {"BEAR", "LEAN_BEAR", "LEAN_BEAR_US"}:
        return "WEAK"
    if value in {"GRAY", "FLAT", "NEUTRAL"}:
        return "NORMAL"
    return "UNKNOWN"


def bottom_confirm_decision(
    *,
    entry_lane: str,
    signal_reason: str,
    rebound_pct: float,
    regime_band: str,
    observe_sec: float,
    reset_steps: int,
    pullback_depth_pct: float,
    higher_low_pct: float,
    second_rebound_pct: float,
    recent_buy_rate: float,
    recent_sell_rate: float,
    baseline_buy_rate: float,
    baseline_sell_rate: float,
    price_responding: bool,
    microprice_edge_bps: float,
    best_bid_share: float,
    spread_bps: float,
    config: BottomConfirmConfig | None = None,
    flow_config: FlowTurnFastConfig | None = None,
) -> Dict[str, Any]:
    """Apply the exact tested flow gate, then the approved regime route."""
    cfg = config or BottomConfirmConfig()
    flow = flow_turn_fast_decision(
        recent_buy_rate=recent_buy_rate,
        recent_sell_rate=recent_sell_rate,
        baseline_buy_rate=baseline_buy_rate,
        baseline_sell_rate=baseline_sell_rate,
        price_responding=price_responding,
        microprice_edge_bps=microprice_edge_bps,
        best_bid_share=best_bid_share,
        spread_bps=spread_bps,
        config=flow_config,
    )
    group = regime_group(regime_band)
    lane = str(entry_lane or "").upper()
    reason = str(signal_reason or "").upper()
    direct = lane in {"EARLY_LOW", "INTRADAY_CRASH"} or reason.startswith("S03_EXPRESS")
    retest = bool(
        "STAIRCASE" in reason
        and pullback_depth_pct >= cfg.min_pullback_pct
        and higher_low_pct >= cfg.min_higher_low_pct
        and second_rebound_pct >= cfg.min_second_rebound_pct
    )
    if group == "STRONG":
        route_ready = direct and 0.0 <= rebound_pct <= cfg.strong_max_rebound_pct
        route = "FAST"
    elif group == "NORMAL":
        route_ready = retest and 0.0 <= rebound_pct <= cfg.retest_max_rebound_pct
        route = "RETEST"
    elif group == "WEAK":
        route_ready = bool(
            retest
            and 0.0 <= rebound_pct <= cfg.retest_max_rebound_pct
            and observe_sec >= cfg.weak_min_observe_sec
            and int(reset_steps) >= cfg.weak_min_reset_steps
        )
        route = "WEAK_RETEST"
    else:
        route_ready = False
        route = "BLOCK"
    ready = bool(route_ready and flow["ready"])
    return {
        "ready": ready,
        "action": "BOTTOM_CONFIRM_READY" if ready else "BLOCK_RESET",
        "route": route,
        "regime_band": str(regime_band or "UNKNOWN"),
        "regime_group": group,
        "route_ready": route_ready,
        "direct": direct,
        "retest": retest,
        "flow_score": flow["flow_score"],
        "flow_checks": flow["checks"],
    }

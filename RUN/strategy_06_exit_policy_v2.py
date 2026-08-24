# -*- coding: utf-8 -*-
"""Order-free Strategy 06 exit policy candidate.

This module never submits an order.  It is intentionally isolated until the
current production engine can be replayed with complete preserved inputs.
"""
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class ExitObservation:
    price: float
    entry_price: float
    anchor_low: float
    peak_price: float
    atr_3m_pct: float
    ma5: float
    ma5_prev: float
    ma10: float
    ma20: float
    ma20_prev: float
    buy_rate_10s: float
    sell_rate_10s: float
    buy_side_alive: bool
    buy_ratio_10s: float
    anchor_break_sec: float = 0.0
    ma5_reversal_sec: float = 0.0
    flow_grace_sec: float = 0.0
    observed_time: time = time(9, 0)
    same_day: bool = True


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str


def decide_exit(obs: ExitObservation) -> ExitDecision:
    """Deterministic S06 v2 decision.  Result is SELL or HOLD only."""
    if obs.entry_price <= 0 or obs.price <= 0:
        return ExitDecision("HOLD", "INPUT_NOT_READY")

    return_pct = (obs.price / obs.entry_price - 1.0) * 100.0
    sell_dominant = (
        obs.sell_rate_10s > 0
        and obs.sell_rate_10s >= 1.5 * max(0.0, obs.buy_rate_10s)
    )
    ma_ready = obs.ma5 > 0 and obs.ma5_prev > 0 and obs.ma10 > 0
    below_ma5 = ma_ready and obs.price < obs.ma5
    below_ma10 = ma_ready and obs.price < obs.ma10
    ma5_rising = ma_ready and obs.ma5 > obs.ma5_prev
    strong_hold = (
        ma_ready and obs.ma20 > 0 and obs.ma20_prev > 0
        and obs.price > obs.ma5 > obs.ma10 > obs.ma20
        and ma5_rising and obs.ma20 > obs.ma20_prev
        and obs.buy_side_alive
    )

    if not obs.same_day:
        return ExitDecision("SELL", "LEGACY_OVERNIGHT_FLAT_0900")

    if return_pct <= -2.0:
        return ExitDecision("SELL", "HARD_STOP_2")
    if (
        obs.anchor_low > 0 and obs.price < obs.anchor_low
        and sell_dominant and obs.anchor_break_sec >= 3.0
    ):
        return ExitDecision("SELL", "ANCHOR_LOW_BREAK_FLOW_3S")
    if below_ma10 and sell_dominant:
        return ExitDecision("SELL", "MA10_BREAK_SELL_FLOW")
    if below_ma5 and not ma5_rising and sell_dominant and obs.ma5_reversal_sec >= 3.0:
        return ExitDecision("SELL", "MA5_FALLING_FLOW_3S")

    # S06 is day-trade only.  Rising-hold and flow grace may delay an ordinary
    # exit, but they must never carry a position beyond the final flat time.
    if obs.observed_time >= time(15, 20):
        return ExitDecision("SELL", "HARD_FLAT_1520")

    if obs.observed_time >= time(15, 10):
        if not (return_pct >= 0 and strong_hold and obs.buy_side_alive):
            return ExitDecision("SELL", "CLOSE_PROTECT_1510")

    peak = max(obs.entry_price, obs.peak_price)
    peak_return = (peak / obs.entry_price - 1.0) * 100.0
    peak_drop = (peak - obs.price) / peak * 100.0
    trail_drop = max(0.8, max(0.0, obs.atr_3m_pct) * 1.5)
    # The peak/ATR line arms the decision.  MA/flow may grant only the bounded
    # five-second grace below; it can never cancel the exit indefinitely.
    trail_trigger = peak_return >= 1.0 and peak_drop >= trail_drop
    if not trail_trigger:
        return ExitDecision("HOLD", "NO_EXIT")

    flow_grace = (
        return_pct > 0 and strong_hold and obs.buy_ratio_10s >= 0.90
        and obs.flow_grace_sec < 5.0
    )
    if flow_grace:
        return ExitDecision("HOLD", "BUY_RATIO_90_GRACE_MAX_5S")
    return ExitDecision("SELL", "MA_FLOW_ATR_TRAIL")

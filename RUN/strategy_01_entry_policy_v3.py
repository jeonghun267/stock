# -*- coding: utf-8 -*-
"""Order-free S01 v3 entry router: ROCKET / PULLBACK / ORB.

The policy contains no sell, quantity, force-exit, or daily-loss shutdown rule.
It must remain order-zero until complete auction and intraday inputs pass the
current production replay gate.
"""
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Iterable


class Lane(str, Enum):
    ROCKET = "ROCKET"
    PULLBACK = "PULLBACK"
    ORB = "ORB"


@dataclass(frozen=True)
class EntryCandidate:
    ts: datetime
    code: str
    price: float
    open_price: float
    low_price: float
    opening_high_3m: float
    vwap: float
    auction_ready: bool = False
    auction_price_rising: bool = False
    auction_buy_ratio: float = 0.0
    auction_volume_percentile: float = 0.0
    relative_volume: float = 0.0
    buy_ratio: float = 0.0
    buy_rate: float = 0.0
    sell_rate: float = 0.0
    buy_accelerating: bool = False
    sell_decelerating: bool = False
    che_rising: bool = False
    first_5s_high_break: bool = False
    low_stable_sec: float = 0.0
    higher_low_pct: float = 0.0
    ma5: float = 0.0
    ma5_prev: float = 0.0
    ma10: float = 0.0
    spread_bps: float = 9999.0
    microprice_edge_bps: float = 0.0
    trend_tier: str = "C"


@dataclass(frozen=True)
class EntryDecision:
    code: str
    lane: Lane | None
    action: str
    score: float
    reason: str


LANE_LIMITS = {Lane.ROCKET: 1, Lane.PULLBACK: 3, Lane.ORB: 2}


def _flow_ready(row: EntryCandidate) -> bool:
    return (
        row.buy_ratio >= 0.65
        and row.buy_rate > row.sell_rate
        and row.buy_accelerating
        and row.che_rising
    )


def _ma_ready(row: EntryCandidate) -> bool:
    return (
        row.ma5 > 0 and row.ma5_prev > 0 and row.ma10 > 0
        and row.price > row.ma5 and row.ma5 > row.ma5_prev
        and row.price >= row.ma10
    )


def _score(row: EntryCandidate) -> float:
    auction = min(25.0, 0.25 * row.auction_volume_percentile)
    volume = min(25.0, 12.5 * max(0.0, row.relative_volume))
    flow = min(20.0, 20.0 * max(0.0, row.buy_ratio))
    price = 15.0 if (row.first_5s_high_break or row.price > row.opening_high_3m > 0) else 8.0
    trend = {"A": 10.0, "B": 6.0, "C": 2.0}.get(row.trend_tier.upper(), 2.0)
    liquidity = 5.0 if row.spread_bps <= 35 and row.microprice_edge_bps >= 0 else 0.0
    return round(auction + volume + flow + price + trend + liquidity, 2)


def evaluate_candidate(row: EntryCandidate) -> EntryDecision:
    clock = row.ts.time()
    if min(row.price, row.open_price, row.low_price) <= 0:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "PRICE_INPUT_MISSING")
    extension = (row.price / row.open_price - 1.0) * 100.0
    dip = (row.low_price / row.open_price - 1.0) * 100.0
    rebound = (row.price / row.low_price - 1.0) * 100.0

    if time(9, 0) <= clock < time(9, 1):
        rocket = (
            row.auction_ready and row.auction_price_rising
            and row.auction_buy_ratio >= 0.65
            and row.auction_volume_percentile >= 80.0
            and row.first_5s_high_break and _flow_ready(row)
            and row.spread_bps <= 35.0 and extension <= 1.2
        )
        if rocket:
            score = _score(row)
            return EntryDecision(row.code, Lane.ROCKET, "READY", score, "ROCKET_CONFIRMED")

    if time(9, 0, 30) <= clock < time(9, 20):
        pullback = (
            -3.0 <= dip <= -0.5 and 0.5 <= rebound <= 1.2
            and row.low_stable_sec >= 5.0 and row.higher_low_pct >= 0.2
            and row.sell_decelerating and row.buy_accelerating
            and _flow_ready(row) and _ma_ready(row)
        )
        if pullback:
            score = _score(row)
            return EntryDecision(row.code, Lane.PULLBACK, "READY", score, "PULLBACK_CONFIRMED")

    if time(9, 3) <= clock < time(9, 20):
        orb = (
            row.opening_high_3m > 0 and row.price > row.opening_high_3m
            and row.price <= row.opening_high_3m * 1.007
            and row.relative_volume >= 2.0 and row.price > row.vwap > 0
            and _flow_ready(row) and _ma_ready(row)
        )
        if orb:
            score = _score(row)
            return EntryDecision(row.code, Lane.ORB, "READY", score, "ORB_CONFIRMED")
    return EntryDecision(row.code, None, "WAIT", 0.0, "NO_LANE_CONFIRMED")


def select_batch(rows: Iterable[EntryCandidate], minimum_score: float = 70.0) -> list[EntryDecision]:
    """Rank a complete three-second batch; never select in arrival order."""
    ready = [evaluate_candidate(row) for row in rows]
    ready = [decision for decision in ready
             if decision.action == "READY" and decision.score >= minimum_score]
    output: list[EntryDecision] = []
    for lane, limit in LANE_LIMITS.items():
        ranked = sorted(
            (decision for decision in ready if decision.lane == lane),
            key=lambda decision: (decision.score, decision.code), reverse=True,
        )
        output.extend(ranked[:limit])
    return output

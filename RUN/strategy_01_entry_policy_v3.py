# -*- coding: utf-8 -*-
"""Order-free S01 v3 entry router: ROCKET / PULLBACK.

The policy contains no sell, quantity, force-exit, or daily-loss shutdown rule.
It must remain order-zero until complete auction and intraday inputs pass the
current production replay gate.

The continuation rocket combines a breakout, short-horizon order-flow
acceleration, and liquidity gates. It is order-capable only on the owner-
approved live date; the prior market date remains enabled solely so its exact
preserved inputs can exercise the same production decision path.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Iterable


class Lane(str, Enum):
    ROCKET = "ROCKET"
    PULLBACK = "PULLBACK"


@dataclass(frozen=True)
class EntryCandidate:
    ts: datetime
    code: str
    price: float
    open_price: float
    low_price: float
    opening_high_3m: float
    vwap: float
    high_range_ready: bool = False
    high_range_money_speed_ratio: float = 0.0
    money_flow_fresh: bool = False
    money_speed_5s: float = 0.0
    auction_ready: bool = False
    auction_price_rising: bool = False
    auction_buy_ratio: float = 0.0
    auction_volume_percentile: float = 0.0
    auction_sample_count: int = 0
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
    order_book_fresh: bool = False
    book_bid_share: float = 0.0
    ma5: float = 0.0
    ma5_prev: float = 0.0
    ma10: float = 0.0
    spread_bps: float = 9999.0
    microprice_edge_bps: float = 0.0
    trend_tier: str = "C"
    price_rising_6s_two_ticks: bool = False
    rise_6s_pct: float = 0.0
    up_ticks_6s: int = 0
    session_high_break: bool = False


@dataclass(frozen=True)
class EntryDecision:
    code: str
    lane: Lane | None
    action: str
    score: float
    reason: str


# ★[2026-08-27 친구님 지시 "ROCKET 3슬롯, PULLBACK 3슬롯, 전략1 총 6슬롯, 상시"]
#   ROCKET 배치당 상한 1 → 3. 구 1슬롯 설계의 잔재였다 — 동시 확정 로켓 3개 중
#   2개가 버려지는 것을 막는다. 누적 3슬롯은 엔진(rotation_engine_v2)이 별도로
#   강제한다(rocket_max_slots=3·pullback_max_slots=3, __post_init__ 검증 포함).
LANE_LIMITS = {Lane.ROCKET: 3, Lane.PULLBACK: 3}
ROCKET_MIN_MONEY_SPEED_5S = 1_666_667.0
PULLBACK_MIN_MONEY_SPEED_5S = 1_000_000.0
PULLBACK_MIN_HIGH_RANGE_MONEY_SPEED_RATIO = 2.0
CONTINUATION_MIN_OPEN_EXTENSION_PCT = 1.5
CONTINUATION_MAX_OPEN_EXTENSION_PCT = 3.0
CONTINUATION_REPLAY_DATE = date(2026, 9, 2)
CONTINUATION_LIVE_DATE = date(2026, 9, 3)


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
    if not row.high_range_ready:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "HIGH_RANGE_TOP40_REQUIRED")
    if not row.money_flow_fresh:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "MONEY_FLOW_NOT_FRESH")
    extension = (row.price / row.open_price - 1.0) * 100.0
    dip = (row.low_price / row.open_price - 1.0) * 100.0
    rebound = (row.price / row.low_price - 1.0) * 100.0

    if time(9, 0) <= clock < time(9, 1):
        rocket = (
            row.high_range_ready and row.money_flow_fresh
            and row.money_speed_5s >= ROCKET_MIN_MONEY_SPEED_5S
            and row.auction_ready and row.auction_price_rising
            and row.auction_buy_ratio >= 0.65
            and row.auction_volume_percentile >= 80.0
            and row.auction_sample_count >= 10
            and row.first_5s_high_break and _flow_ready(row)
            and row.spread_bps <= 35.0 and 0.0 <= extension <= 1.5
        )
        if rocket:
            score = _score(row)
            return EntryDecision(row.code, Lane.ROCKET, "READY", score, "ROCKET_CONFIRMED")

    if time(9, 1) <= clock < time(9, 10):
        continuation = evaluate_continuation_rocket_shadow(row)
        if (
            continuation.action == "SHADOW_READY"
            and row.ts.date() in {CONTINUATION_REPLAY_DATE, CONTINUATION_LIVE_DATE}
        ):
            return EntryDecision(
                row.code,
                Lane.ROCKET,
                "READY",
                continuation.score,
                "CONTINUATION_ROCKET_CONFIRMED",
            )

    if time(9, 0, 30) <= clock < time(9, 20):
        pullback = (
            -3.0 <= dip <= -0.5 and 0.5 <= rebound <= 1.5
            and row.money_speed_5s >= PULLBACK_MIN_MONEY_SPEED_5S
            and row.high_range_money_speed_ratio >= PULLBACK_MIN_HIGH_RANGE_MONEY_SPEED_RATIO
            and row.low_stable_sec >= 5.0 and row.higher_low_pct >= 0.2
            and row.sell_decelerating and row.buy_accelerating
            and row.order_book_fresh and row.book_bid_share >= 0.55
            and row.spread_bps <= 35.0
            and _flow_ready(row)
        )
        if pullback:
            score = _score(row)
            return EntryDecision(row.code, Lane.PULLBACK, "READY", score, "PULLBACK_CONFIRMED")

    return EntryDecision(row.code, None, "WAIT", 0.0, "NO_LANE_CONFIRMED")


def evaluate_continuation_rocket_shadow(row: EntryCandidate) -> EntryDecision:
    """Evaluate the 09:01-09:10 straight-rise path without enabling orders."""
    clock = row.ts.time()
    if not (time(9, 1) <= clock < time(9, 10)):
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_OUTSIDE_WINDOW")
    if min(row.price, row.open_price) <= 0:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "PRICE_INPUT_MISSING")
    if not row.high_range_ready:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "HIGH_RANGE_TOP40_REQUIRED")
    if not row.money_flow_fresh:
        return EntryDecision(row.code, None, "BLOCK", 0.0, "MONEY_FLOW_NOT_FRESH")
    extension = (row.price / row.open_price - 1.0) * 100.0
    if not (
        CONTINUATION_MIN_OPEN_EXTENSION_PCT
        <= extension
        <= CONTINUATION_MAX_OPEN_EXTENSION_PCT
    ):
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_EXTENSION_OUTSIDE_1P5_3P0")
    if not row.price_rising_6s_two_ticks:
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_6S_TWO_UPTICKS_MISSING")
    if not row.session_high_break:
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_SESSION_HIGH_NOT_BROKEN")
    if row.money_speed_5s < ROCKET_MIN_MONEY_SPEED_5S or not _flow_ready(row):
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_ORDER_FLOW_WEAK")
    if (
        not row.order_book_fresh
        or row.book_bid_share < 0.55
        or row.spread_bps > 35.0
        or row.microprice_edge_bps < 0.0
    ):
        return EntryDecision(row.code, None, "WAIT", 0.0, "CONTINUATION_LIQUIDITY_WEAK")
    return EntryDecision(
        row.code,
        Lane.ROCKET,
        "SHADOW_READY",
        _score(row),
        "CONTINUATION_ROCKET_SHADOW_CONFIRMED",
    )


def select_batch(rows: Iterable[EntryCandidate]) -> list[EntryDecision]:
    """Rank a complete three-second batch; never select in arrival order."""
    ready = [evaluate_candidate(row) for row in rows]
    ready = [decision for decision in ready if decision.action == "READY"]
    output: list[EntryDecision] = []
    for lane, limit in LANE_LIMITS.items():
        ranked = sorted(
            (decision for decision in ready if decision.lane == lane),
            key=lambda decision: (decision.score, decision.code), reverse=True,
        )
        output.extend(ranked[:limit])
    return output

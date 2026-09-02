# -*- coding: utf-8 -*-
"""Order-zero runtime adapter for S01 ROCKET/PULLBACK entry policy."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Iterable, Mapping

from ma3_common_v1 import ma3_rows
from strategy_01_entry_policy_v3 import (
    LANE_LIMITS,
    EntryCandidate,
    evaluate_candidate,
    evaluate_continuation_rocket_shadow,
    select_batch,
)


@dataclass
class RuntimeState:
    samples: deque = field(default_factory=lambda: deque(maxlen=180))
    auction: deque = field(default_factory=lambda: deque(maxlen=1200))
    local_lows: deque = field(default_factory=lambda: deque(maxlen=12))
    last_batch: int = -1


class EntryRuntimeV3:
    """Build exact policy inputs; incomplete rows stay UNVERIFIED and never emit."""

    EMIT_RETRY_SEC = 10.0

    @staticmethod
    def _selection_allowed(decision: Any, allow_select: bool) -> bool:
        """Keep legacy batch timing; continuation may trigger between boundaries."""
        return bool(
            allow_select
            or (
                decision.action == "READY"
                and decision.reason == "CONTINUATION_ROCKET_CONFIRMED"
            )
        )

    def __init__(self, volume_baseline: Mapping[str, Any] | None = None) -> None:
        self.states: dict[str, RuntimeState] = defaultdict(RuntimeState)
        self.baseline = dict((volume_baseline or {}).get("codes") or {})
        self.emitted: set[tuple[str, str]] = set()
        self.emitted_at: dict[tuple[str, str], datetime] = {}

    @staticmethod
    def _rates(samples: deque) -> tuple[float, float, float, float]:
        if len(samples) < 3:
            return 0.0, 0.0, 0.0, 0.0
        now = samples[-1]
        def at_age(seconds: float):
            target = now[0].timestamp() - seconds
            eligible = [row for row in samples if row[0].timestamp() <= target]
            return eligible[-1] if eligible else None
        p5, p10 = at_age(5), at_age(10)
        if p5 is None:
            return 0.0, 0.0, 0.0, 0.0
        buy5 = max(0.0, (now[2] - p5[2]) / max(1.0, (now[0] - p5[0]).total_seconds()))
        sell5 = max(0.0, (now[3] - p5[3]) / max(1.0, (now[0] - p5[0]).total_seconds()))
        if p10 is None:
            return buy5, sell5, 0.0, 0.0
        span = max(1.0, (p5[0] - p10[0]).total_seconds())
        return buy5, sell5, max(0.0, (p5[2] - p10[2]) / span), max(0.0, (p5[3] - p10[3]) / span)

    @staticmethod
    def _six_second_price_momentum(samples: deque) -> tuple[bool, float, int, bool]:
        """Return two up-ticks within six seconds and a session-high breakout."""
        if len(samples) < 3:
            return False, 0.0, 0, False
        rows = list(samples)
        now = rows[-1]
        window = [
            row for row in rows
            if 0.0 <= (now[0] - row[0]).total_seconds() <= 6.5
        ]
        if len(window) < 3 or min(row[1] for row in window) <= 0:
            return False, 0.0, 0, False
        up_ticks = sum(
            1 for previous, current in zip(window, window[1:])
            if current[1] > previous[1]
        )
        rise6 = (now[1] / window[0][1] - 1.0) * 100.0
        prior_session_prices = [
            row[1] for row in rows[:-1] if row[0].time() >= time(9, 0)
        ]
        high_break = bool(
            prior_session_prices and now[1] > max(prior_session_prices)
        )
        return up_ticks >= 2 and rise6 > 0.0, rise6, up_ticks, high_break

    def _candidate(self, point: Any, minute_payload: Mapping[str, Any],
                   trend_tier: str, auction_percentile: float,
                   auction_sample_count: int) -> tuple[EntryCandidate, list[str]]:
        state = self.states[point.code]
        state.samples.append((point.ts, point.price, point.buy_money_cum,
                              point.sell_money_cum, point.che_str, point.cum_vol))
        if point.ts.time() < time(9, 0) and point.auction_expected_px > 0:
            state.auction.append((point.ts, point.auction_expected_px,
                                  point.auction_expected_qty, point.bid_tot, point.ask_tot))
        prices = [row[1] for row in state.samples if row[0].time() >= time(9, 0)]
        low = min(prices) if prices else point.price
        low_rows = [row for row in state.samples if row[1] == low]
        low_ts = low_rows[-1][0] if low_rows else point.ts
        if len(state.samples) >= 5:
            window = list(state.samples)[-5:]
            middle = window[2]
            other_prices = [
                row[1] for index, row in enumerate(window) if index != 2
            ]
            if middle[1] <= min(other_prices) and middle[1] < max(other_prices):
                state.local_lows.append((middle[0], middle[1]))
        higher_lows = [price for ts, price in state.local_lows if ts > low_ts]
        higher_low_pct = ((higher_lows[-1] / low - 1) * 100) if higher_lows and low > 0 else 0.0
        opening = [row for row in state.samples if time(9, 0) <= row[0].time() < time(9, 3)]
        opening_high = max((row[1] for row in opening), default=0.0)
        first5_rows = [
            row for row in opening if row[0].time() <= time(9, 0, 5)
        ]
        if point.ts.time() <= time(9, 0, 5):
            first5_reference = [
                row[1] for row in first5_rows if row[0] < point.ts
            ]
        else:
            first5_reference = [row[1] for row in first5_rows]
        first_5s_break = bool(
            first5_reference and point.price > max(first5_reference)
        )
        buy5, sell5, buy_prev, sell_prev = self._rates(state.samples)
        rising_6s_two_ticks, rise_6s_pct, up_ticks_6s, session_high_break = (
            self._six_second_price_momentum(state.samples)
        )
        total_rate = buy5 + sell5
        buy_ratio = buy5 / total_rate if total_rate > 0 else 0.0
        auction = list(state.auction)
        auction_rising = len(auction) >= 3 and auction[-1][1] > auction[-3][1]
        auction_buy_ratio = 0.0
        if auction and auction[-1][3] + auction[-1][4] > 0:
            auction_buy_ratio = auction[-1][3] / (auction[-1][3] + auction[-1][4])
        minute = max(0, min(19, point.ts.minute))
        base = float((self.baseline.get(point.code) or {}).get(str(minute)) or 0)
        relative_volume = point.cum_vol / base if base > 0 else 0.0
        vwap = ((point.buy_money_cum + point.sell_money_cum) / point.cum_vol
                if point.buy_money_cum >= 0 and point.sell_money_cum >= 0 and point.cum_vol > 0 else 0.0)
        bars = ma3_rows(point.code, dict(minute_payload)) or {}
        row = EntryCandidate(
            ts=point.ts, code=point.code, price=point.price,
            open_price=point.open_hint, low_price=low,
            opening_high_3m=opening_high, vwap=vwap,
            high_range_ready=bool(getattr(point, "high_range_ready", False)),
            high_range_money_speed_ratio=float(
                getattr(point, "high_range_money_speed_ratio", 0.0) or 0.0
            ),
            money_flow_fresh=bool(getattr(point, "exact_flow", False)),
            money_speed_5s=float(getattr(point, "money_speed_5s", 0.0) or 0.0),
            auction_ready=bool(auction), auction_price_rising=auction_rising,
            auction_buy_ratio=auction_buy_ratio,
            auction_volume_percentile=auction_percentile,
            auction_sample_count=auction_sample_count,
            relative_volume=relative_volume, buy_ratio=buy_ratio,
            buy_rate=buy5, sell_rate=sell5,
            buy_accelerating=buy5 > 0 and (buy_prev <= 0 or buy5 > buy_prev * 1.2),
            sell_decelerating=0 <= sell5 < sell_prev,
            che_rising=len(state.samples) >= 2 and state.samples[-1][4] > state.samples[-2][4],
            first_5s_high_break=first_5s_break,
            low_stable_sec=max(0.0, (point.ts - low_ts).total_seconds()),
            higher_low_pct=higher_low_pct,
            order_book_fresh=bool(getattr(point, "order_book_fresh", False)),
            book_bid_share=float(getattr(point, "book_bid_share", 0.0) or 0.0),
            ma5=float(bars.get("ma5") or 0), ma5_prev=float(bars.get("ma5_prev") or 0),
            ma10=float(bars.get("ma10") or 0), spread_bps=point.spread_bps,
            microprice_edge_bps=point.microprice_edge_bps, trend_tier=trend_tier,
            price_rising_6s_two_ticks=rising_6s_two_ticks,
            rise_6s_pct=rise_6s_pct,
            up_ticks_6s=up_ticks_6s,
            session_high_break=session_high_break,
        )
        missing = []
        clock = point.ts.time()
        if time(9, 0) <= clock < time(9, 1):
            if not auction:
                missing.append("AUCTION_HISTORY")
            if auction_sample_count < 10:
                missing.append("AUCTION_CROSS_SECTION_MIN10")
        if time(9, 0, 30) <= clock < time(9, 20):
            if not row.order_book_fresh:
                missing.append("ORDER_BOOK")
        if time(9, 0) <= clock < time(9, 20):
            if not row.high_range_ready:
                missing.append("HIGH_RANGE_TOP40")
            if not row.money_flow_fresh:
                missing.append("MONEY_FLOW_BOARD")
        if time(9, 3) <= clock < time(9, 20) and base <= 0:
            missing.append("RELATIVE_VOLUME_BASELINE")
        if point.buy_money_cum < 0 or point.sell_money_cum < 0:
            missing.append("SIGNED_FLOW")
        return row, missing

    def process_batch(self, points: Iterable[Any], minute_payload: Mapping[str, Any],
                      trend_rows: Mapping[str, Mapping[str, Any]], *,
                      allow_select: bool = True) -> tuple[list[dict], list[dict]]:
        points = list(points)
        quantities = sorted(p.auction_expected_qty for p in points if p.auction_expected_qty > 0)
        built: list[tuple[EntryCandidate, list[str]]] = []
        for point in points:
            pct = 0.0
            if quantities and point.auction_expected_qty > 0:
                pct = 100.0 * sum(q <= point.auction_expected_qty for q in quantities) / len(quantities)
            tier = str((trend_rows.get(point.code) or {}).get("tier") or
                       (trend_rows.get(point.code) or {}).get("s01_trend_tier") or "C")
            built.append(self._candidate(
                point, minute_payload, tier, pct, len(quantities),
            ))
        audit = []
        complete = []
        for candidate, missing in built:
            decision = evaluate_candidate(candidate)
            continuation = evaluate_continuation_rocket_shadow(candidate)
            raw = asdict(candidate)
            raw["ts"] = candidate.ts.isoformat(timespec="seconds")
            audit.append({**raw, "lane": decision.lane.value if decision.lane else "",
                          "action": decision.action if not missing else "UNVERIFIED",
                          "score": decision.score, "reason": decision.reason,
                          "continuation_shadow_lane": (
                              continuation.lane.value if continuation.lane else ""
                          ),
                          "continuation_shadow_action": continuation.action,
                          "continuation_shadow_score": continuation.score,
                          "continuation_shadow_reason": continuation.reason,
                          "missing_fields": missing})
            if not missing and self._selection_allowed(decision, allow_select):
                complete.append(candidate)
        selected = []
        for decision in select_batch(complete):
            key = (decision.code, decision.lane.value)
            candidate = next(row for row in complete if row.code == decision.code)
            last_emitted = self.emitted_at.get(key)
            if (
                last_emitted is not None
                and (candidate.ts - last_emitted).total_seconds()
                < self.EMIT_RETRY_SEC
            ):
                continue
            self.emitted.add(key)
            self.emitted_at[key] = candidate.ts
            selected.append({"ts": candidate.ts.isoformat(timespec="seconds"),
                             "code": decision.code, "price": candidate.price,
                             "reference_low": candidate.low_price,
                             "action": "BUY_READY", "stage": decision.lane.value,
                             "score": decision.score, "reason": decision.reason,
                             "mode": "SIGNAL_ONLY_ORDER_ZERO"})
        return selected, audit

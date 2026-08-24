# -*- coding: utf-8 -*-
"""Order-zero runtime adapter for S01 ROCKET/PULLBACK/ORB entry policy."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Iterable, Mapping

from ma3_common_v1 import ma3_rows
from strategy_01_entry_policy_v3 import LANE_LIMITS, EntryCandidate, evaluate_candidate, select_batch


@dataclass
class RuntimeState:
    samples: deque = field(default_factory=lambda: deque(maxlen=180))
    auction: deque = field(default_factory=lambda: deque(maxlen=1200))
    local_lows: deque = field(default_factory=lambda: deque(maxlen=12))
    last_batch: int = -1


class EntryRuntimeV3:
    """Build exact policy inputs; incomplete rows stay UNVERIFIED and never emit."""

    def __init__(self, volume_baseline: Mapping[str, Any] | None = None) -> None:
        self.states: dict[str, RuntimeState] = defaultdict(RuntimeState)
        self.baseline = dict((volume_baseline or {}).get("codes") or {})
        self.emitted: set[tuple[str, str]] = set()
        self.lane_counts: dict[str, int] = defaultdict(int)

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

    def _candidate(self, point: Any, minute_payload: Mapping[str, Any],
                   trend_tier: str, auction_percentile: float) -> tuple[EntryCandidate, list[str]]:
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
        if len(state.samples) >= 3:
            a, b, c = list(state.samples)[-3:]
            if b[1] <= a[1] and b[1] <= c[1]:
                state.local_lows.append((b[0], b[1]))
        higher_lows = [price for ts, price in state.local_lows if ts > low_ts]
        higher_low_pct = ((higher_lows[-1] / low - 1) * 100) if higher_lows and low > 0 else 0.0
        opening = [row for row in state.samples if time(9, 0) <= row[0].time() < time(9, 3)]
        opening_high = max((row[1] for row in opening), default=0.0)
        first5 = [row[1] for row in opening if row[0].time() <= time(9, 0, 5)]
        first_5s_break = len(first5) >= 2 and point.price > max(first5[:-1])
        buy5, sell5, buy_prev, sell_prev = self._rates(state.samples)
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
            auction_ready=bool(auction), auction_price_rising=auction_rising,
            auction_buy_ratio=auction_buy_ratio,
            auction_volume_percentile=auction_percentile,
            relative_volume=relative_volume, buy_ratio=buy_ratio,
            buy_rate=buy5, sell_rate=sell5,
            buy_accelerating=buy5 > 0 and (buy_prev <= 0 or buy5 > buy_prev * 1.2),
            sell_decelerating=0 <= sell5 < sell_prev,
            che_rising=len(state.samples) >= 2 and state.samples[-1][4] > state.samples[-2][4],
            first_5s_high_break=first_5s_break,
            low_stable_sec=max(0.0, (point.ts - low_ts).total_seconds()),
            higher_low_pct=higher_low_pct,
            ma5=float(bars.get("ma5") or 0), ma5_prev=float(bars.get("ma5_prev") or 0),
            ma10=float(bars.get("ma10") or 0), spread_bps=point.spread_bps,
            microprice_edge_bps=point.microprice_edge_bps, trend_tier=trend_tier,
        )
        missing = []
        clock = point.ts.time()
        if time(9, 0) <= clock < time(9, 1) and not auction:
            missing.append("AUCTION_HISTORY")
        if time(9, 3) <= clock < time(9, 20) and base <= 0:
            missing.append("RELATIVE_VOLUME_BASELINE")
        if not bars:
            missing.append("MA3")
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
            built.append(self._candidate(point, minute_payload, tier, pct))
        audit = []
        complete = []
        for candidate, missing in built:
            decision = evaluate_candidate(candidate)
            raw = asdict(candidate)
            raw["ts"] = candidate.ts.isoformat(timespec="seconds")
            audit.append({**raw, "lane": decision.lane.value if decision.lane else "",
                          "action": decision.action if not missing else "UNVERIFIED",
                          "score": decision.score, "reason": decision.reason,
                          "missing_fields": missing})
            if not missing and allow_select:
                complete.append(candidate)
        selected = []
        for decision in select_batch(complete):
            key = (decision.code, decision.lane.value)
            if key in self.emitted:
                continue
            if self.lane_counts[decision.lane.value] >= LANE_LIMITS[decision.lane]:
                continue
            self.emitted.add(key)
            self.lane_counts[decision.lane.value] += 1
            candidate = next(row for row in complete if row.code == decision.code)
            selected.append({"ts": candidate.ts.isoformat(timespec="seconds"),
                             "code": decision.code, "price": candidate.price,
                             "action": "BUY_READY", "stage": decision.lane.value,
                             "score": decision.score, "reason": decision.reason,
                             "mode": "SIGNAL_ONLY_ORDER_ZERO"})
        return selected, audit

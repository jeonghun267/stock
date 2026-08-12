# -*- coding: utf-8 -*-
"""Shared weak-book retest entry gate.

Trend/rebound strategies may submit their normal signal immediately when the
top of book is healthy.  A weak-book signal is held until the anchor low is
retested and exact buy-money/buy-volume speed turns are confirmed twice.
Sideways/base-breakout strategies are deliberately excluded because their
entry anchor is the breakout line, not a turning low.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Deque, Mapping, Optional


SIDEWAYS_STRATEGIES = frozenset({"S05_BASE_BREAKOUT", "BASE"})
ANCHOR_FIELDS = (
    "anchor_low",
    "low_so_far",
    "second_low",
    "pullback_low",
    "reset_low",
    "low_price",
    "low",
)


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _observed_at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class CommonBuyConfig:
    retest_tolerance_pct: float = 0.10
    max_rebound_from_retest_pct: float = 0.50
    pending_expiry_sec: int = 15 * 60
    recent_sec: int = 10
    previous_sec: int = 10
    confirm_ticks: int = 2
    confirm_max_gap_sec: float = 2.0
    max_spread_bps: float = 30.0
    min_microprice_edge_bps: float = 0.0
    min_best_bid_share: float = 0.50


@dataclass(frozen=True)
class CommonBuyDecision:
    status: str
    reason: str
    signal: Optional[dict[str, Any]] = None

    @property
    def ready(self) -> bool:
        return self.status in {"READY", "BYPASS"}

    @property
    def waiting(self) -> bool:
        return self.status == "WAIT"


@dataclass
class _Sample:
    ts: datetime
    price: float
    che_str: float
    buy_money_cum: float
    sell_money_cum: float
    buy_vol_cum: float
    sell_vol_cum: float


@dataclass
class _Pending:
    strategy_id: str
    code: str
    signal: dict[str, Any]
    anchor_low: float
    armed_at: datetime
    retest: Optional[_Sample] = None
    left_retest_zone: bool = False
    confirm_hits: int = 0
    last_confirm_at: Optional[datetime] = None


class CommonBuyEntryGate:
    """Stateful order-preflight gate shared by non-sideways strategies."""

    def __init__(self, config: Optional[CommonBuyConfig] = None) -> None:
        self.config = config or CommonBuyConfig()
        self._pending: dict[tuple[str, str], _Pending] = {}
        self._rows: dict[tuple[str, str], Deque[_Sample]] = defaultdict(
            lambda: deque(maxlen=1200)
        )

    @staticmethod
    def _key(strategy_id: Any, code: Any) -> tuple[str, str]:
        return str(getattr(strategy_id, "value", strategy_id)), str(code).zfill(6)

    @staticmethod
    def _anchor(signal: Mapping[str, Any]) -> float:
        for field_name in ANCHOR_FIELDS:
            value = _number(signal.get(field_name))
            if value > 0:
                return value
        return 0.0

    def pending_signals(self, strategy_id: Any) -> list[dict[str, Any]]:
        strategy = str(getattr(strategy_id, "value", strategy_id))
        return [
            dict(row.signal)
            for (owner, _code), row in self._pending.items()
            if owner == strategy
        ]

    def consume(self, strategy_id: Any, code: Any) -> None:
        key = self._key(strategy_id, code)
        self._pending.pop(key, None)
        self._rows.pop(key, None)

    def _sample(self, market: Mapping[str, Any]) -> Optional[_Sample]:
        ts = _observed_at(market.get("ts") or market.get("observed_at"))
        values = (
            _number(market.get("price") or market.get("cur")),
            _number(market.get("che_str")),
            _number(market.get("buy_money_cum"), -1.0),
            _number(market.get("sell_money_cum"), -1.0),
            _number(market.get("buy_vol_cum"), -1.0),
            _number(market.get("sell_vol_cum"), -1.0),
        )
        if ts is None or values[0] <= 0 or min(values[2:]) < 0:
            return None
        return _Sample(ts, *values)

    def _book_metrics(
        self,
        signal: Mapping[str, Any],
        market: Mapping[str, Any],
    ) -> tuple[float, float, float]:
        ask = _number(market.get("best_ask_px"))
        bid = _number(market.get("best_bid_px"))
        ask_qty = _number(market.get("best_ask_qty"))
        bid_qty = _number(market.get("best_bid_qty"))
        if ask > bid > 0 and ask_qty > 0 and bid_qty > 0:
            midpoint = (ask + bid) / 2.0
            spread = (ask - bid) / midpoint * 10_000.0
            edge = (
                ((ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty) - midpoint)
                / midpoint
                * 10_000.0
            )
            share = bid_qty / (bid_qty + ask_qty)
            return spread, edge, share
        return (
            _number(signal.get("spread_bps"), 9999.0),
            _number(signal.get("microprice_edge_bps"), -9999.0),
            _number(
                signal.get("best_bid_share", signal.get("book_bid_share")),
                -1.0,
            ),
        )

    def _book_strong(
        self,
        signal: Mapping[str, Any],
        market: Mapping[str, Any],
    ) -> bool:
        spread, edge, share = self._book_metrics(signal, market)
        return bool(
            spread <= self.config.max_spread_bps
            and edge >= self.config.min_microprice_edge_bps
            and share >= self.config.min_best_bid_share
        )

    @staticmethod
    def _append(rows: Deque[_Sample], sample: _Sample) -> None:
        if rows and (
            sample.ts <= rows[-1].ts
            or sample.buy_money_cum < rows[-1].buy_money_cum
            or sample.sell_money_cum < rows[-1].sell_money_cum
            or sample.buy_vol_cum < rows[-1].buy_vol_cum
            or sample.sell_vol_cum < rows[-1].sell_vol_cum
        ):
            rows.clear()
        rows.append(sample)
        cutoff = sample.ts - timedelta(minutes=20)
        while rows and rows[0].ts < cutoff:
            rows.popleft()

    @staticmethod
    def _at_or_before(rows: Deque[_Sample], target: datetime) -> Optional[_Sample]:
        return next((row for row in reversed(rows) if row.ts <= target), None)

    def _flow_turn(self, rows: Deque[_Sample], pending: _Pending) -> bool:
        if pending.retest is None or len(rows) < 3:
            return False
        end = rows[-1]
        middle_target = end.ts - timedelta(seconds=self.config.recent_sec)
        start_target = middle_target - timedelta(seconds=self.config.previous_sec)
        middle = self._at_or_before(rows, middle_target)
        start = self._at_or_before(rows, start_target)
        if middle is None or start is None:
            return False
        if (
            (middle_target - middle.ts).total_seconds()
            > max(2.0, self.config.recent_sec * 0.4)
            or (start_target - start.ts).total_seconds()
            > max(3.0, self.config.previous_sec * 0.4)
        ):
            return False
        recent_span = (end.ts - middle.ts).total_seconds()
        previous_span = (middle.ts - start.ts).total_seconds()
        post_span = (end.ts - pending.retest.ts).total_seconds()
        if min(recent_span, previous_span, post_span) <= 0:
            return False
        raw = (
            end.buy_money_cum - middle.buy_money_cum,
            end.sell_money_cum - middle.sell_money_cum,
            middle.buy_money_cum - start.buy_money_cum,
            middle.sell_money_cum - start.sell_money_cum,
            end.buy_vol_cum - middle.buy_vol_cum,
            end.sell_vol_cum - middle.sell_vol_cum,
            middle.buy_vol_cum - start.buy_vol_cum,
            middle.sell_vol_cum - start.sell_vol_cum,
            end.buy_money_cum - pending.retest.buy_money_cum,
            end.sell_money_cum - pending.retest.sell_money_cum,
        )
        if min(raw) < 0:
            return False
        rbm, rsm, pbm, psm = (
            raw[0] / recent_span,
            raw[1] / recent_span,
            raw[2] / previous_span,
            raw[3] / previous_span,
        )
        rbv, rsv, pbv, psv = (
            raw[4] / recent_span,
            raw[5] / recent_span,
            raw[6] / previous_span,
            raw[7] / previous_span,
        )
        return bool(
            rbm > rsm
            and rbm > pbm
            and rsm <= psm
            and rbv > rsv
            and rbv > pbv
            and rsv <= psv
            and end.che_str > middle.che_str
            and end.che_str > pending.retest.che_str
            and raw[8] > raw[9]
        )

    def evaluate(
        self,
        strategy_id: Any,
        signal: Mapping[str, Any],
        market: Mapping[str, Any],
    ) -> CommonBuyDecision:
        strategy, code = self._key(strategy_id, signal.get("code"))
        if strategy in SIDEWAYS_STRATEGIES:
            return CommonBuyDecision("BYPASS", "COMMON_BUY_SIDEWAYS_EXCLUDED", dict(signal))
        anchor = self._anchor(signal)
        # Signals without a turning-low anchor (legacy/custom lanes) retain
        # their existing behavior.  The retest rule must never invent a low.
        if anchor <= 0:
            return CommonBuyDecision(
                "BYPASS", "COMMON_BUY_NO_LOW_ANCHOR_BYPASS", dict(signal)
            )
        sample = self._sample(market)
        if sample is None:
            return CommonBuyDecision("WAIT", "COMMON_BUY_EXACT_FLOW_WAIT")
        key = (strategy, code)
        rows = self._rows[key]
        self._append(rows, sample)
        pending = self._pending.get(key)
        if pending is None:
            if self._book_strong(signal, market):
                return CommonBuyDecision("READY", "COMMON_BUY_BOOK_READY", dict(signal))
            pending = _Pending(strategy, code, dict(signal), anchor, sample.ts)
            self._pending[key] = pending
            return CommonBuyDecision("WAIT", "COMMON_BUY_WEAK_BOOK_RETEST_WAIT")

        if (sample.ts - pending.armed_at).total_seconds() > self.config.pending_expiry_sec:
            self.consume(strategy, code)
            return CommonBuyDecision("REJECT", "COMMON_BUY_RETEST_EXPIRED")

        tolerance_price = pending.anchor_low * (
            1.0 + self.config.retest_tolerance_pct / 100.0
        )
        if sample.price < pending.anchor_low:
            pending.anchor_low = sample.price
            pending.retest = sample
            pending.left_retest_zone = False
            pending.confirm_hits = 0
            pending.last_confirm_at = None
        elif sample.price <= tolerance_price:
            if pending.retest is None or pending.left_retest_zone:
                pending.retest = sample
                pending.left_retest_zone = False
                pending.confirm_hits = 0
                pending.last_confirm_at = None
        elif pending.retest is not None:
            pending.left_retest_zone = True

        if pending.retest is None:
            return CommonBuyDecision("WAIT", "COMMON_BUY_RETEST_WAIT")
        if sample.price > pending.retest.price * (
            1.0 + self.config.max_rebound_from_retest_pct / 100.0
        ):
            pending.confirm_hits = 0
            pending.last_confirm_at = None
            return CommonBuyDecision("WAIT", "COMMON_BUY_REBOUND_CHASE_WAIT")

        if not self._flow_turn(rows, pending):
            pending.confirm_hits = 0
            pending.last_confirm_at = None
            return CommonBuyDecision("WAIT", "COMMON_BUY_FLOW_TURN_WAIT")
        if (
            pending.last_confirm_at is None
            or (sample.ts - pending.last_confirm_at).total_seconds()
            > self.config.confirm_max_gap_sec
        ):
            pending.confirm_hits = 1
        else:
            pending.confirm_hits += 1
        pending.last_confirm_at = sample.ts
        if pending.confirm_hits < self.config.confirm_ticks:
            return CommonBuyDecision("WAIT", "COMMON_BUY_FLOW_CONFIRM_WAIT")

        ready = dict(pending.signal)
        ready.update({
            "ts": sample.ts.isoformat(timespec="seconds"),
            "price": sample.price,
            "anchor_low": pending.anchor_low,
            "common_buy_retest_ts": pending.retest.ts.isoformat(timespec="seconds"),
            "common_buy_retest_price": pending.retest.price,
            "common_buy_confirm_ticks": pending.confirm_hits,
            "common_buy_original_price": _number(pending.signal.get("price")),
            "common_buy_reason": "WEAK_BOOK_LOW_RETEST_BUY_TURN",
        })
        return CommonBuyDecision(
            "READY", "COMMON_BUY_RETEST_FLOW_CONFIRMED", ready
        )

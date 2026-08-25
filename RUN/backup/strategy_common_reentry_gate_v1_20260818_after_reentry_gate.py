# -*- coding: utf-8 -*-
"""Order-free S01/S02 loss re-entry qualification.

The gate never submits orders and never changes strategy state.  It evaluates a
fresh candidate against confirmed loss exits, completed one-minute bars, ATR10,
and three consecutive observations of renewed buy-side strength.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
MIN_STABLE_BARS = 3
ATR_MULTIPLIER = 0.5
BUY_CONFIRMATIONS = 3


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


@dataclass(frozen=True)
class ReentryDecision:
    applies: bool
    allowed: bool
    reason: str
    exit_at: str = ""
    prior_low: float = 0.0
    post_exit_low: float = 0.0
    atr10: float = 0.0
    stable_bars: int = 0
    buy_confirmations: int = 0


def latest_closed_trade(code: str, states: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    normalized = str(code).zfill(6)
    latest: tuple[datetime, Mapping[str, Any]] | None = None
    for state in states:
        for row in state.get("history") or []:
            if not isinstance(row, Mapping) or str(row.get("code") or "").zfill(6) != normalized:
                continue
            exit_at = _dt(row.get("exit_at"))
            if exit_at is None:
                continue
            if latest is None or exit_at > latest[0]:
                latest = (exit_at, row)
    return latest[1] if latest else None


def _bars(code: str, payload: Mapping[str, Any]) -> list[tuple[datetime, float, float, float, float]]:
    source = payload.get("m") if isinstance(payload.get("m"), Mapping) else payload
    item = source.get(str(code).zfill(6)) if isinstance(source, Mapping) else None
    if not isinstance(item, Mapping):
        return []
    result: list[tuple[datetime, float, float, float, float]] = []
    for minute, raw in zip(item.get("pm") or [], item.get("prev") or []):
        if not isinstance(raw, (list, tuple)) or len(raw) < 4:
            continue
        try:
            ts = datetime.strptime(str(minute), "%Y%m%d%H%M").replace(tzinfo=KST)
        except ValueError:
            continue
        result.append((ts, *map(_number, raw[:4])))
    return sorted(result, key=lambda row: row[0])


def _atr10(rows: Sequence[tuple[datetime, float, float, float, float]]) -> float:
    true_ranges: list[float] = []
    previous_close: float | None = None
    for _ts, _open, high, low, close in rows:
        tr = high - low
        if previous_close is not None:
            tr = max(tr, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(tr)
        previous_close = close
    if len(true_ranges) < 10:
        return 0.0
    return sum(true_ranges[-10:]) / 10.0


def _signal_buy_side(signal: Mapping[str, Any]) -> bool:
    s02_fields = ("money_buy_turn", "volume_buy_turn", "che_rising")
    if any(field in signal for field in s02_fields):
        return all(signal.get(field) is True for field in s02_fields)
    return _number(signal.get("buy_ratio")) >= 0.5 and _number(signal.get("money_speed_5s")) > 0


class LossReentryGate:
    def __init__(
        self,
        *,
        min_wait_sec: float = 0.0,
        require_new_low: bool = False,
        min_stable_bars: int = MIN_STABLE_BARS,
        atr_multiplier: float = ATR_MULTIPLIER,
        buy_confirmations: int = BUY_CONFIRMATIONS,
    ) -> None:
        self._confirmations: dict[tuple[str, str], tuple[str, int]] = {}
        self.min_wait_sec = max(0.0, float(min_wait_sec))
        self.require_new_low = bool(require_new_low)
        self.min_stable_bars = max(0, int(min_stable_bars))
        self.atr_multiplier = max(0.0, float(atr_multiplier))
        self.buy_confirmations = max(1, int(buy_confirmations))

    def evaluate(
        self,
        *,
        strategy_id: str,
        code: str,
        signal: Mapping[str, Any],
        current_price: float,
        states: Sequence[Mapping[str, Any]],
        bars_payload: Mapping[str, Any],
    ) -> ReentryDecision:
        trade = latest_closed_trade(code, states)
        if trade is None or _number(trade.get("gross_return_pct")) >= 0:
            self._confirmations.pop((strategy_id, str(code).zfill(6)), None)
            return ReentryDecision(False, True, "NO_LATEST_LOSS")

        exit_at = _dt(trade.get("exit_at"))
        signal_at = _dt(signal.get("ts"))
        if exit_at is None or signal_at is None or signal_at <= exit_at:
            return ReentryDecision(True, False, "REENTRY_SIGNAL_NOT_NEW", str(trade.get("exit_at") or ""))
        if (signal_at - exit_at).total_seconds() < self.min_wait_sec:
            return ReentryDecision(
                True, False, "REENTRY_COOLDOWN_WAIT", exit_at.isoformat(),
            )

        prior_low = _number(trade.get("trough_price"))
        if prior_low <= 0:
            candidates = [
                value for value in (
                    _number(trade.get("exit_price")),
                    _number(trade.get("entry_price")),
                ) if value > 0
            ]
            prior_low = min(candidates) if candidates else 0.0
        if self.require_new_low and prior_low <= 0:
            return ReentryDecision(
                True, False, "REENTRY_PRIOR_LOW_MISSING", exit_at.isoformat(),
            )

        rows = _bars(code, bars_payload)
        atr10 = _atr10(rows)
        exit_minute = exit_at.replace(second=0, microsecond=0)
        post_rows = [row for row in rows if row[0] > exit_minute and row[0] <= signal_at]
        if not post_rows or (self.atr_multiplier > 0 and atr10 <= 0):
            return ReentryDecision(
                True, False, "REENTRY_MINUTE_DATA_NOT_READY", exit_at.isoformat(), prior_low,
            )

        post_low = min(row[3] for row in post_rows)
        if self.require_new_low and post_low >= prior_low:
            return ReentryDecision(
                True, False, "REENTRY_NEW_LOW_REQUIRED", exit_at.isoformat(),
                prior_low, post_low, atr10, 0, 0,
            )
        last_low_index = max(index for index, row in enumerate(post_rows) if row[3] == post_low)
        stable_bars = len(post_rows) - last_low_index - 1
        if stable_bars < self.min_stable_bars:
            return ReentryDecision(
                True, False, "REENTRY_NEW_LOW_STABILITY_WAIT", exit_at.isoformat(),
                prior_low, post_low, atr10, stable_bars, 0,
            )
        if current_price - post_low < atr10 * self.atr_multiplier:
            return ReentryDecision(
                True, False, "REENTRY_ATR_REBOUND_WAIT", exit_at.isoformat(),
                prior_low, post_low, atr10, stable_bars, 0,
            )

        key = (strategy_id, str(code).zfill(6))
        signal_id = str(signal.get("signal_id") or signal.get("ts") or "")
        previous_id, previous_count = self._confirmations.get(key, ("", 0))
        count = previous_count + 1 if previous_id == signal_id else 1
        if not _signal_buy_side(signal):
            count = 0
        self._confirmations[key] = (signal_id, count)
        if count < self.buy_confirmations:
            return ReentryDecision(
                True, False, "REENTRY_BUY_SIDE_CONFIRM_WAIT", exit_at.isoformat(),
                prior_low, post_low, atr10, stable_bars, count,
            )
        return ReentryDecision(
            True, True, "REENTRY_GATE_PASS", exit_at.isoformat(),
            prior_low, post_low, atr10, stable_bars, count,
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def record_reentry_snapshot(
    *,
    root: Path,
    strategy_id: str,
    code: str,
    signal: Mapping[str, Any],
    current_price: float,
    states: Sequence[Mapping[str, Any]],
    bars_payload: Mapping[str, Any],
    decision: ReentryDecision,
    mode: str,
    engine_paths: Sequence[Path],
) -> Path | None:
    """Append replay-complete, order-zero inputs for one gate observation."""
    signal_at = _dt(signal.get("ts")) or datetime.now(KST)
    normalized = str(code).zfill(6)
    source = bars_payload.get("m") if isinstance(bars_payload.get("m"), Mapping) else bars_payload
    bar_row = source.get(normalized) if isinstance(source, Mapping) else None
    paths = [Path(path).resolve() for path in engine_paths]
    row = {
        "schema": "strategy_common_reentry_gate_audit_v1",
        "captured_at": datetime.now(KST).isoformat(),
        "provenance": "HYPOTHETICAL",
        "order_capable": False,
        "mode": str(mode),
        "strategy_id": str(strategy_id),
        "code": normalized,
        "current_price": float(current_price),
        "signal": dict(signal),
        "latest_closed_trade": dict(latest_closed_trade(normalized, states) or {}),
        "bars": dict(bar_row) if isinstance(bar_row, Mapping) else {},
        "decision": {
            "applies": decision.applies,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "exit_at": decision.exit_at,
            "prior_low": decision.prior_low,
            "post_exit_low": decision.post_exit_low,
            "atr10": decision.atr10,
            "stable_bars": decision.stable_bars,
            "buy_confirmations": decision.buy_confirmations,
        },
        "engine_paths": [str(path) for path in paths],
        "engine_sha256": {str(path): _sha256(path) for path in paths},
    }
    target = (
        Path(root)
        / signal_at.strftime("%Y%m%d")
        / str(strategy_id)
        / f"{normalized}.jsonl"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        return target
    except OSError:
        return None

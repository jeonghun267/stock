# -*- coding: utf-8 -*-
"""Strategy 02 signal contract. No broker import and no order submission."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

STRATEGY_NUMBER = "02"
STRATEGY_ID = "S02_LOW_BUY_SELL_EXHAUSTION"
STRATEGY_NAME = "저점매수 매도소진"
SIGNAL_SCHEMA = "strategy_02_low_buy_sell_exhaustion_signal_v1"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"


def _parse_local(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _fresh(ts: datetime | None, now: datetime, max_age_sec: float) -> bool:
    if ts is None:
        return False
    age = (now - ts).total_seconds()
    return -2.0 <= age <= max_age_sec


def _signal_id(day: str, row: Mapping[str, Any]) -> str:
    return (
        f"{day}:{str(row.get('code') or '').zfill(6)}:"
        f"{int(float(row.get('signal_sequence') or 0))}:{row.get('ts')}"
    )


def select_fresh_signals(
    payload: Mapping[str, Any],
    *,
    now: datetime,
    max_age_sec: float,
    consumed: Iterable[str] = (),
) -> list[dict[str, Any]]:
    local_now = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    day = local_now.strftime("%Y%m%d")
    if str(payload.get("schema") or "") != SIGNAL_SCHEMA:
        return []
    if str(payload.get("mode") or "") != SIGNAL_MODE:
        return []
    if str(payload.get("date") or "") != day:
        return []
    if not _fresh(_parse_local(payload.get("updated_at")), local_now, max_age_sec):
        return []

    used = set(consumed)
    selected: list[dict[str, Any]] = []
    for raw in payload.get("signals") or []:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        if str(raw.get("action") or "") != "BUY_READY":
            continue
        if str(raw.get("mode") or "") != SIGNAL_MODE:
            continue
        if not _fresh(_parse_local(raw.get("ts")), local_now, max_age_sec):
            continue
        signal_id = _signal_id(day, raw)
        if signal_id in used:
            continue
        row = dict(raw)
        row.update({
            "code": code,
            "signal_id": signal_id,
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
        })
        selected.append(row)

    selected.sort(
        key=lambda row: (
            -float(row.get("entry_gap_pct") or 99),
            float(row.get("book_imbalance") or 0),
            int(float(row.get("wave_count") or 0)),
            row["code"],
        ),
        reverse=True,
    )
    return selected
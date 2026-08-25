# -*- coding: utf-8 -*-
"""Strategy 01 signal contract.

This module never imports a broker and never submits an order.  It only
validates the shadow monitor's JSON contract and returns fresh BUY_READY rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping


STRATEGY_NUMBER = "01"
STRATEGY_ID = "S01_OPEN_SURGE"
STRATEGY_NAME = "장초반 급상승 초입"
SIGNAL_SCHEMA = "strategy_01_open_surge_signal_v2"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"


def _parse_local(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


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
    """Return fresh, unique Strategy 01 BUY_READY rows in deterministic priority order."""
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
        row["code"] = code
        row["signal_id"] = signal_id
        row["strategy_id"] = STRATEGY_ID
        row["strategy_name"] = STRATEGY_NAME
        selected.append(row)

    selected.sort(
        key=lambda row: (
            int(float(row.get("theme_bonus") or 0)),
            int(float(row.get("listed_turnover_bonus") or 0)),
            float(row.get("money_speed_5s") or 0),
            float(row.get("buy_ratio") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected

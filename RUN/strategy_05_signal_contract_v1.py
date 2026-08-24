# -*- coding: utf-8 -*-
"""Strategy 05 signal contract. No broker import and no order submission."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from strategy_05_base_breakout_signal_v1 import SIGNAL_MODE, SIGNAL_SCHEMA


STRATEGY_NUMBER = "05"
STRATEGY_ID = "S05_BASE_BREAKOUT"
STRATEGY_NAME = "장중 베이스 돌파"


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
        f"{int(float(row.get('signal_sequence') or 0))}:"
        f"{row.get('anchor_id')}:{row.get('ts')}"
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
    if payload.get("schema") != SIGNAL_SCHEMA:
        return []
    if payload.get("mode") != SIGNAL_MODE:
        return []
    if payload.get("date") != day:
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
        if raw.get("action") != "BUY_READY" or raw.get("mode") != SIGNAL_MODE:
            continue
        if not _fresh(_parse_local(raw.get("ts")), local_now, max_age_sec):
            continue
        if not str(raw.get("anchor_id") or ""):
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
            float(row.get("breakout_volx") or 0),
            float(row.get("buy_ratio") or 0),
            -float(row.get("spread_bps") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected

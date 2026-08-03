# -*- coding: utf-8 -*-
"""Strategy 04 signal contract. No broker import and no order submission."""
from __future__ import annotations

import math
from datetime import datetime, time
from typing import Any, Iterable, Mapping

from strategy_04_pullback_signal_v1 import SIGNAL_MODE, SIGNAL_SCHEMA


STRATEGY_NUMBER = "04"
STRATEGY_ID = "S04_PULLBACK"
STRATEGY_NAME = "눌림목"
BUY_ALGORITHM = "S04_DEEP_W_PRO_V1"
BUY_REASON = "DEEP_W_MA3_CROSS_NECKLINE+FLOW+BOOK+MARKET+COST"
ENTRY_START = time(10, 0)
ENTRY_END = time(12, 0)



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

def _number(row: Mapping[str, Any], key: str) -> float | None:
    raw = row.get(key)
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _valid_buy_ready(row: Mapping[str, Any], row_ts: datetime) -> bool:
    keys = (
        "signal_sequence", "first_low", "second_low", "neckline",
        "drop_pct", "second_drop_pct", "rebound_pct", "low_difference_pct",
        "ma3", "ma20", "price", "ask_price", "current_chase_pct",
        "buy_ratio", "flow_observation_sec", "book_bid_share",
        "book_recovery", "spread_bps", "microprice_edge_bps", "rising_sec",
        "gross_edge_pct", "expected_cost_pct", "market_change_pct",
        "market_recovery_pct",
    )
    value = {key: _number(row, key) for key in keys}
    if any(item is None for item in value.values()):
        return False
    market_ok = (
        value["market_change_pct"] >= -0.5
        or value["market_recovery_pct"] >= 0.2
    )
    return (
        str(row.get("algorithm") or "") == BUY_ALGORITHM
        and str(row.get("reason") or "") == BUY_REASON
        and value["signal_sequence"] in (1.0, 2.0)
        and ENTRY_START <= row_ts.time() < ENTRY_END
        and row.get("market_fresh") is True
        and value["first_low"] > 0 and value["second_low"] > 0
        and value["neckline"] > 0 and value["price"] >= 10_000
        and value["price"] >= value["neckline"] and value["ask_price"] > 0
        and -18.0 <= value["drop_pct"] <= -10.0
        and -18.0 <= value["second_drop_pct"] <= -10.0
        and value["rebound_pct"] >= 2.0
        and abs(value["low_difference_pct"]) <= 2.0
        and value["ma3"] > value["ma20"]
        and 0.0 <= value["current_chase_pct"] <= 5.0
        and 0.55 <= value["buy_ratio"] <= 1.0
        and value["flow_observation_sec"] >= 10.0
        and 0.52 <= value["book_bid_share"] <= 1.0
        and value["book_recovery"] >= 0.05
        and 0.0 <= value["spread_bps"] <= 35.0
        and value["microprice_edge_bps"] > 0.0
        and value["rising_sec"] >= 3.0
        and value["expected_cost_pct"] >= 0.0
        and value["gross_edge_pct"] >= value["expected_cost_pct"] + 0.30
        and market_ok
    )


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
        row_ts = _parse_local(raw.get("ts"))
        if not _fresh(row_ts, local_now, max_age_sec):
            continue
        if not str(raw.get("anchor_id") or ""):
            continue
        if not _valid_buy_ready(raw, row_ts):
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
            float(row.get("gross_edge_pct") or 0)
            - float(row.get("expected_cost_pct") or 0),
            float(row.get("book_recovery") or 0),
            float(row.get("buy_ratio") or 0),
            row["code"],
        ),
        reverse=True,
    )
    return selected

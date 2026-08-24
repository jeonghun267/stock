# -*- coding: utf-8 -*-
"""Strategy 01 signal contract.

This module never imports a broker and never submits an order.  It only
validates the shadow monitor's JSON contract and returns fresh BUY_READY rows.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


STRATEGY_NUMBER = "01"
STRATEGY_ID = "S01_OPEN_SURGE"
STRATEGY_NAME = "장초반 급상승 초입"
SIGNAL_SCHEMA = "strategy_01_open_surge_signal_v2"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"
ENTRY_V3_MODE = os.environ.get("S01_ENTRY_V3_MODE", "SHADOW").strip().upper()
if ENTRY_V3_MODE not in {"SHADOW", "LIVE"}:
    ENTRY_V3_MODE = "SHADOW"
TREND_PRIORITY_MODE = os.environ.get(
    "S01_TREND_PRIORITY_MODE", "SHADOW"
).strip().upper()
if TREND_PRIORITY_MODE not in {"OFF", "SHADOW", "LIVE"}:
    TREND_PRIORITY_MODE = "SHADOW"
RUN_DIR = Path(__file__).resolve().parent
OPEN_PRIORITY_AUDIT_ROOT = Path(
    r"C:\stock_bot\data\audit\s01_open_priority"
)
OPEN_PRIORITY_CAPTURE = True


def _base_priority(row: Mapping[str, Any]) -> tuple:
    return (
        int(float(row.get("theme_bonus") or 0)),
        int(float(row.get("listed_turnover_bonus") or 0)),
        float(row.get("money_speed_5s") or 0),
        float(row.get("buy_ratio") or 0),
        str(row.get("code") or ""),
    )


def _trend_priority(row: Mapping[str, Any]) -> int:
    return {"A": 3, "B": 2, "C": 1}.get(
        str(row.get("s01_trend_tier") or "C").upper(), 1,
    )


def order_signals(
    rows: Iterable[Mapping[str, Any]], mode: str | None = None,
) -> list[dict[str, Any]]:
    """Prefer A/B/C before the existing strength key only in LIVE mode."""
    selected = [dict(row) for row in rows]
    base = sorted(selected, key=_base_priority, reverse=True)
    trend = sorted(
        selected,
        key=lambda row: (_trend_priority(row),) + _base_priority(row),
        reverse=True,
    )
    shadow_rank = {
        str(row.get("signal_id") or ""): rank
        for rank, row in enumerate(trend, start=1)
    }
    chosen_mode = str(mode or TREND_PRIORITY_MODE).strip().upper()
    output = trend if chosen_mode == "LIVE" else base
    for row in output:
        row["s01_trend_priority_mode"] = chosen_mode
        row["s01_trend_priority_shadow_rank"] = shadow_rank.get(
            str(row.get("signal_id") or ""), 0,
        )
    return output


def order_selected_signals(
    rows: Iterable[Mapping[str, Any]],
    *,
    entry_v3_mode: str | None = None,
    trend_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Keep v3's own score order; apply A/B/C only to the legacy selector."""
    chosen_entry = str(entry_v3_mode or ENTRY_V3_MODE).strip().upper()
    if chosen_entry == "LIVE":
        output = sorted(
            (dict(row) for row in rows),
            key=lambda row: (
                float(row.get("score") or 0.0),
                str(row.get("code") or ""),
            ),
            reverse=True,
        )
        for row in output:
            row["s01_entry_v3_order"] = "V3_SCORE_ONLY"
        return output
    return order_signals(rows, mode=trend_mode)


def _capture_open_priority_input(
    *,
    payload: Mapping[str, Any],
    now: datetime,
    max_age_sec: float,
    consumed: Iterable[str],
    selected_rows: list[Mapping[str, Any]],
) -> None:
    """Append exact S01 selector inputs; fail-neutral and order-zero."""
    if not OPEN_PRIORITY_CAPTURE or not selected_rows:
        return
    files = (
        RUN_DIR / "strategy_01_rotation_engine_v2.py",
        Path(__file__),
        RUN_DIR / "strategy_open_priority_v1.py",
        RUN_DIR / "strategy_01_open_surge_signal_v2.py",
        RUN_DIR / "strategy_01_entry_runtime_v3.py",
        RUN_DIR / "strategy_01_entry_policy_v3.py",
    )
    record = {
        "schema": "s01_open_priority_replay_input_v1",
        "captured_at": now.isoformat(timespec="microseconds"),
        "production_files": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
        "config": {
            "signal_max_age_sec": max_age_sec,
            "trend_priority_mode": TREND_PRIORITY_MODE,
            "open_priority_mode": os.environ.get(
                "S01_S03_OPEN_PRIORITY_MODE", "SHADOW"
            ).strip().upper(),
            "open_priority_wait_sec": float(os.environ.get(
                "S01_S03_OPEN_PRIORITY_WAIT_SEC", "3"
            )),
        },
        "consumed_signals": list(consumed),
        "signal_payload": payload,
        "selected_rows": selected_rows,
    }
    path = OPEN_PRIORITY_AUDIT_ROOT / f"{now:%Y%m%d}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")
    except OSError:
        pass


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
    source_rows = list(payload.get("signals") or [])
    if ENTRY_V3_MODE == "LIVE":
        source_rows = list(payload.get("entry_v3_signals") or [])
    for raw in source_rows:
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
        row["s01_entry_v3_mode"] = ENTRY_V3_MODE
        selected.append(row)

    output = order_selected_signals(selected)
    _capture_open_priority_input(
        payload=payload,
        now=now,
        max_age_sec=max_age_sec,
        consumed=sorted(used),
        selected_rows=output,
    )
    return output

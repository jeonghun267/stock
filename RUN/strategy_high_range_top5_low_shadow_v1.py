# -*- coding: utf-8 -*-
"""Order-zero high-range TOP5 low-recovery shadow.

Universe: previous-day high-range candidates with at least four qualifying
sessions in the latest five consecutive trading sessions.  The daily TOP5 is
frozen on first observation.  This module has no broker/order imports.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any

from 저점매수_매도소진 import MarketPoint, detect_flow_book_exhaustion


BASE = Path(r"C:\stock_bot")
MARKET_OPEN = clock_time(9, 0)
MARKET_CLOSE = clock_time(15, 30)
LOOP_STOP = clock_time(15, 35)
SNAPSHOT_MAX_AGE_SEC = 15.0
TOP_N = 5
MIN_QUALIFIED_5D = 4
UNIVERSE_SCHEMA_VERSION = 2


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp, path)


def select_shadow_universe(payload: dict) -> list[dict]:
    if (
        payload.get("source_stale")
        or int(payload.get("schema_version") or 0) < UNIVERSE_SCHEMA_VERSION
    ):
        return []
    eligible = [
        row for row in payload.get("candidates", [])
        if int(row.get("qualified_5d_count") or 0) >= MIN_QUALIFIED_5D
    ]
    return sorted(eligible, key=lambda row: int(row.get("rank") or 9999))[:TOP_N]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _point(row: dict) -> MarketPoint | None:
    ts = _parse_ts(row.get("ts"))
    price = abs(_number(row.get("cur")))
    if ts is None or price <= 0:
        return None
    return MarketPoint(
        ts=ts,
        price=price,
        cum_vol=_number(row.get("cum_vol")),
        che_str=_number(row.get("che_str")),
        ask_tot=_number(row.get("ask_tot")),
        bid_tot=_number(row.get("bid_tot")),
        buy_money_cum=_number(row.get("buy_money_cum")),
        sell_money_cum=_number(row.get("sell_money_cum")),
        buy_vol_cum=_number(row.get("buy_vol_cum"), -1.0),
        sell_vol_cum=_number(row.get("sell_vol_cum"), -1.0),
        best_ask_px=_number(row.get("best_ask_px")),
        best_bid_px=_number(row.get("best_bid_px")),
        best_ask_qty=_number(row.get("best_ask_qty")),
        best_bid_qty=_number(row.get("best_bid_qty")),
        broker_day_low=abs(_number(row.get("day_low"))),
        broker_day_high=abs(_number(row.get("day_high"))),
    )


def _point_payload(point: MarketPoint) -> dict:
    payload = asdict(point)
    payload["ts"] = point.ts.isoformat()
    return payload


def _restore_points(rows: list[dict]) -> list[MarketPoint]:
    points = []
    for row in rows:
        payload = dict(row)
        payload["ts"] = datetime.fromisoformat(str(payload["ts"]))
        points.append(MarketPoint(**payload))
    return points


def evaluate_once(
    universe_payload: dict,
    snapshot: dict,
    state: dict,
    now: datetime,
) -> tuple[dict, list[dict]]:
    date_text = now.strftime("%Y%m%d")
    if (
        state.get("date") != date_text
        or state.get("universe_schema_version") != UNIVERSE_SCHEMA_VERSION
    ):
        if int(universe_payload.get("schema_version") or 0) < UNIVERSE_SCHEMA_VERSION:
            return {
                "schema": "high_range_top5_low_shadow_v1",
                "date": date_text,
                "universe_schema_version": None,
                "status": "WAIT_SOURCE_SCHEMA",
                "universe": [],
                "codes": {},
                "signals": [],
                "updated_at": now.isoformat(),
            }, []
        universe = select_shadow_universe(universe_payload)
        state = {
            "schema": "high_range_top5_low_shadow_v1",
            "date": date_text,
            "universe_schema_version": UNIVERSE_SCHEMA_VERSION,
            "status": "WATCH",
            "source_date": universe_payload.get("source_date", ""),
            "universe": universe,
            "codes": {},
            "signals": [],
        }
    emitted: list[dict] = []
    live_codes = snapshot.get("codes") or {}
    for candidate in state.get("universe", []):
        code = str(candidate.get("code") or "").zfill(6)
        live = live_codes.get(code) or {}
        point = _point(live)
        code_state = state["codes"].setdefault(code, {"points": [], "anchors": []})
        if point is None:
            code_state["status"] = "NO_DATA"
            continue
        age = (now - point.ts).total_seconds()
        if point.ts.date() != now.date() or not -2 <= age <= SNAPSHOT_MAX_AGE_SEC:
            code_state["status"] = "STALE"
            continue
        points = _restore_points(code_state.get("points") or [])
        if points and point.ts <= points[-1].ts:
            code_state["status"] = "DUPLICATE"
            continue
        if points and (
            point.buy_money_cum < points[-1].buy_money_cum
            or point.sell_money_cum < points[-1].sell_money_cum
            or (point.ts - points[-1].ts).total_seconds() > 60
        ):
            points = []
        points.append(point)
        cutoff = point.ts.timestamp() - 1800
        points = [item for item in points if item.ts.timestamp() >= cutoff]
        code_state["points"] = [_point_payload(item) for item in points]
        code_state["status"] = "WATCH"
        code_state["current"] = point.price
        code_state["low"] = min(item.price for item in points)
        code_state["high"] = max(item.price for item in points)

        for tracked in state.get("signals", []):
            if tracked.get("code") == code:
                tracked["last_price"] = point.price
                tracked["max_after"] = max(_number(tracked.get("max_after")), point.price)
                prior_min = _number(tracked.get("min_after"), point.price)
                tracked["min_after"] = min(prior_min, point.price)

        signal = detect_flow_book_exhaustion(points)
        if signal is None or abs((point.ts - signal.signal_ts).total_seconds()) > 1:
            continue
        anchor = f"{signal.anchor_low_ts.isoformat()}:{signal.anchor_low_price:.4f}"
        if anchor in code_state["anchors"]:
            continue
        code_state["anchors"].append(anchor)
        event = {
            "provenance": "[HYPOTHETICAL]",
            "date": date_text,
            "code": code,
            "name": candidate.get("name", ""),
            "rank": candidate.get("rank"),
            "qualified_5d_count": candidate.get("qualified_5d_count"),
            "signal_at": signal.signal_ts.isoformat(),
            "signal_price": signal.signal_price,
            "anchor_low_at": signal.anchor_low_ts.isoformat(),
            "anchor_low": signal.anchor_low_price,
            "reason": signal.reason,
            "last_price": point.price,
            "max_after": point.price,
            "min_after": point.price,
        }
        state["signals"].append(event)
        emitted.append(event)
    state["updated_at"] = now.isoformat()
    return state, emitted


def run_once(base: Path = BASE, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    universe = _read_json(base / "data" / "common_high_range_top30.json", {})
    snapshot = _read_json(base / "IPC" / "live_micro_snapshot.json", {})
    state_path = base / "data" / "high_range_top5_low_shadow_state.json"
    state = _read_json(state_path, {})
    state, emitted = evaluate_once(universe, snapshot, state, now)
    _atomic_write(state_path, state)
    if emitted:
        audit = base / "data" / "high_range_top5_low_shadow_signals.jsonl"
        with audit.open("a", encoding="utf-8") as handle:
            for event in emitted:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        now = datetime.now()
        run_once(args.base, now)
        if args.once or now.weekday() >= 5 or now.time() >= LOOP_STOP:
            return 0
        time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())

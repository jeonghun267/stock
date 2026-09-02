# -*- coding: utf-8 -*-
"""Strategy 07 order-zero shell for FLOW_TREND candidates."""
from __future__ import annotations

import argparse
import csv
import json
import time as time_module
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"C:\stock_bot")
SOURCE_JSON = ROOT / "data" / "flow_trend_intraday_board_v1.json"
OUT_JSON = ROOT / "data" / "strategy_07_flow_trend_shadow_v1.json"
MICRO_JSON = ROOT / "IPC" / "live_micro_snapshot.json"
EVENT_DIR = ROOT / "data" / "strategy_07_shadow_v1"
SLOT_COUNT = 6
QUANTITY_PER_SLOT = 1
MICRO_MAX_AGE_SEC = 30.0
OBSERVATION_PHASES = {"REACCEL_TRIGGER", "PULLBACK_READY", "EARLY_REBOUND"}
EVENT_FIELDS = ("ts", "strategy_id", "event", "code", "name", "price", "quantity", "reason")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _observation_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_rows = list(payload.get("display") or [])
    raw_rows.extend(payload.get("early_rebounds") or [])
    for raw in raw_rows:
        row = dict(raw) if isinstance(raw, Mapping) else {}
        code = str(row.get("code") or "").zfill(6)
        if not code.strip("0") or code in seen:
            continue
        phase = str(row.get("entry_phase") or "")
        if phase not in OBSERVATION_PHASES:
            if row.get("early_rebound_status") == "EARLY_REBOUND":
                phase = "EARLY_REBOUND"
            else:
                continue
        row["code"] = code
        row["entry_phase"] = phase
        output.append(row)
        seen.add(code)
    return output


def build_shadow_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("early_rebounds") or [])
    rows.extend(
        row for row in payload.get("display") or []
        if row.get("entry_phase") == "REACCEL_TRIGGER"
    )
    eligible = []
    seen = set()
    for raw in rows:
        row = dict(raw) if isinstance(raw, Mapping) else {}
        code = str(row.get("code") or "").zfill(6)
        if not code.strip("0") or code in seen:
            continue
        seen.add(code)
        if row.get("liquidity_status") != "PASS":
            continue
        if row.get("volatility_status") != "PASS":
            continue
        eligible.append(row)
    eligible.sort(
        key=lambda row: (-_number(row.get("flow_score")), str(row.get("code") or ""))
    )
    slots = []
    for index in range(SLOT_COUNT):
        row = eligible[index] if index < len(eligible) else None
        slots.append({
            "slot": index + 1,
            "pool": "S07_FLOW_TREND_ONLY",
            "status": "SHADOW_READY" if row else "EMPTY",
            "code": str(row.get("code") or "").zfill(6) if row else "",
            "name": str(row.get("name") or "") if row else "",
            "quantity": QUANTITY_PER_SLOT if row else 0,
            "flow_score": _number(row.get("flow_score")) if row else 0.0,
            "signal": (
                "EARLY_REBOUND"
                if row and row.get("early_rebound_status") == "EARLY_REBOUND"
                else "REACCEL_TRIGGER" if row else ""
            ),
            "order_sent": False,
        })
    observed_rows = _observation_rows(payload)
    liq_pass = sum(row.get("liquidity_status") == "PASS" for row in observed_rows)
    vol_pass = sum(row.get("volatility_status") == "PASS" for row in observed_rows)
    both_pass = sum(
        row.get("liquidity_status") == "PASS"
        and row.get("volatility_status") == "PASS"
        for row in observed_rows
    )
    return {
        "schema": "strategy_07_flow_trend_shadow_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_ts": str(payload.get("source_ts") or ""),
        "strategy": "S07",
        "mode": "SHADOW_ORDER_ZERO",
        "separate_slot_pool": True,
        "slot_pool": "S07_FLOW_TREND_ONLY",
        "slot_count": SLOT_COUNT,
        "quantity_per_slot": QUANTITY_PER_SLOT,
        "order_capable": False,
        "orders_sent": 0,
        "eligible_count": len(eligible),
        "funnel": {
            "display": len(payload.get("display") or []),
            "phase_matched": len(observed_rows),
            "liq_pass": liq_pass,
            "vol_pass": vol_pass,
            "both_pass": both_pass,
            "observed": 0,
        },
        "slots": slots,
    }


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    temporary.replace(path)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _fresh_micro_price(micro: Mapping[str, Any], code: str, now: datetime) -> float | None:
    codes = micro.get("codes") if isinstance(micro, Mapping) else None
    row = codes.get(code) if isinstance(codes, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    stamp = _parse_timestamp(row.get("ts"))
    price = _number(row.get("cur"))
    if stamp is None or price <= 0:
        return None
    age = now.timestamp() - stamp.timestamp()
    if age < -5.0 or age > MICRO_MAX_AGE_SEC:
        return None
    return price


def _event_path(now: datetime) -> Path:
    return EVENT_DIR / f"strategy_07_events_{now:%Y%m%d}.csv"


def _read_events(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _append_event(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in EVENT_FIELDS})


def _reason(row: Mapping[str, Any]) -> str:
    return (
        f"[HYPOTHETICAL] phase={row.get('entry_phase') or ''} "
        f"flow={_number(row.get('flow_score')):.1f} "
        f"liq={row.get('liquidity_status') or 'WAIT'} "
        f"vol={row.get('volatility_status') or 'WAIT'} "
        "source=IPC/live_micro_snapshot.json"
    )


def record_shadow_events(
    payload: Mapping[str, Any],
    micro: Mapping[str, Any],
    now: datetime | None = None,
    event_path: Path | None = None,
) -> tuple[int, int]:
    """Append observation/audit rows only; never sends or imports broker orders."""
    current = now or datetime.now()
    path = event_path or _event_path(current)
    events = _read_events(path)
    emitted = {(row.get("code", ""), row.get("event", "")) for row in events}
    entries = {
        row.get("code", ""): row
        for row in events if row.get("event") == "SHADOW_ENTRY"
    }
    appended = 0
    observed = 0

    for row in _observation_rows(payload):
        code = str(row.get("code") or "").zfill(6)
        price = _fresh_micro_price(micro, code, current)
        if price is None:
            continue
        observed += 1
        if (code, "SHADOW_ENTRY") in emitted:
            continue
        event = {
            "ts": current.astimezone().isoformat(timespec="seconds"),
            "strategy_id": "S07_FLOW_TREND_SHADOW",
            "event": "SHADOW_ENTRY",
            "code": code,
            "name": str(row.get("name") or ""),
            "price": price,
            "quantity": QUANTITY_PER_SLOT,
            "reason": _reason(row),
        }
        _append_event(path, event)
        entries[code] = {key: str(value) for key, value in event.items()}
        emitted.add((code, "SHADOW_ENTRY"))
        appended += 1

    close_clock = dt_time(15, 20)
    for code, entry in entries.items():
        entry_at = _parse_timestamp(entry.get("ts"))
        entry_price = _number(entry.get("price"))
        price = _fresh_micro_price(micro, code, current)
        if entry_at is None or entry_price <= 0 or price is None:
            continue
        age_sec = current.timestamp() - entry_at.timestamp()
        audit_events: list[str] = []
        if age_sec >= 30 * 60:
            audit_events.append("SHADOW_AUDIT_30M")
        if age_sec >= 60 * 60:
            audit_events.append("SHADOW_AUDIT_60M")
        if current.time() >= close_clock:
            audit_events.append("SHADOW_CLOSE")
        base_reason = str(entry.get("reason") or "[HYPOTHETICAL]")
        change = (price / entry_price - 1.0) * 100.0
        for event_name in audit_events:
            if (code, event_name) in emitted:
                continue
            _append_event(path, {
                "ts": current.astimezone().isoformat(timespec="seconds"),
                "strategy_id": "S07_FLOW_TREND_SHADOW",
                "event": event_name,
                "code": code,
                "name": entry.get("name", ""),
                "price": price,
                "quantity": QUANTITY_PER_SLOT,
                "reason": f"{base_reason} from_entry={change:+.2f}%",
            })
            emitted.add((code, event_name))
            appended += 1
    return observed, appended


def refresh_once() -> int:
    source = read_json(SOURCE_JSON)
    plan = build_shadow_plan(source)
    observed, appended = record_shadow_events(source, read_json(MICRO_JSON))
    plan["funnel"]["observed"] = observed
    plan["events_appended"] = appended
    if not source:
        plan["status"] = "DATA_WAIT"
    else:
        plan["status"] = "READY"
    atomic_json(OUT_JSON, plan)
    print(json.dumps({
        "status": plan["status"],
        "strategy": plan["strategy"],
        "mode": plan["mode"],
        "eligible": plan["eligible_count"],
        "occupied_slots": sum(slot["status"] != "EMPTY" for slot in plan["slots"]),
        "slot_count": plan["slot_count"],
        "quantity_per_slot": plan["quantity_per_slot"],
        "orders_sent": plan["orders_sent"],
        "funnel": plan["funnel"],
        "events_appended": plan["events_appended"],
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop-sec", type=float, default=0.0)
    parser.add_argument("--until", default="15:20")
    args = parser.parse_args()
    if args.loop_sec <= 0:
        return refresh_once()
    end_clock = dt_time.fromisoformat(args.until)
    while True:
        now = datetime.now()
        end_at = datetime.combine(now.date(), end_clock)
        if now >= end_at:
            return refresh_once()
        refresh_once()
        remaining = (end_at - datetime.now()).total_seconds()
        if remaining <= 0:
            return 0
        time_module.sleep(min(args.loop_sec, remaining))


if __name__ == "__main__":
    raise SystemExit(main())

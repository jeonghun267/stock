# -*- coding: utf-8 -*-
"""Append-only, order-zero TREND_START definition ledger and D+N audits."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import trend_follow_board_v1 as prod
import trend_follow_start_diagnostic_v1 as diagnostic


SOURCE = ROOT / "data" / "eod_daily_bars.csv"
LEDGER_DIR = ROOT / "data" / "trend_follow_start_ledger_v1"
EVENTS = LEDGER_DIR / "events.jsonl"
SUMMARY = LEDGER_DIR / "summary.json"
SIGNAL_CODES = LEDGER_DIR / "signal_codes_by_date.json"
DEFINITIONS = ("CURRENT", "ALT_A_097_VALUE_1P5", "ALT_B_NO_BREAKOUT")
HORIZONS = (1, 3, 5)
INTRADAY_EVENT = "AUDIT_D1_INTRADAY"
# compression_at(t-40) needs its own MA60 history: 40 + 59 prior rows.
FIRST_SAFE_INDEX = prod.PAST_WINDOW[0] + 59


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def event_key(event: dict) -> tuple:
    if event.get("event") == "SIGNAL":
        return ("SIGNAL", event.get("definition"), event.get("signal_date"),
                event.get("code"))
    return (event.get("event"), event.get("definition"), event.get("signal_date"),
            event.get("code"), event.get("horizon"))


def read_events() -> tuple[list[dict], set[tuple]]:
    if not EVENTS.exists():
        return [], set()
    rows = []
    keys = set()
    for line_no, line in enumerate(EVENTS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ledger JSON error line={line_no}: {exc}") from exc
        key = event_key(event)
        if key in keys:
            raise RuntimeError(f"duplicate ledger key line={line_no}: {key}")
        rows.append(event)
        keys.add(key)
    return rows, keys


def signal_event(definition: str, date: str, code: str, entry: dict,
                 flags: dict) -> dict:
    return {
        "provenance": "[HYPOTHETICAL]",
        "event": "SIGNAL",
        "definition": definition,
        "signal_date": date,
        "code": code,
        "name": entry.get("name") or code,
        "signal_close": flags["close"],
        "had_compression": flags["had_compression"],
        "aligned": flags["aligned"],
        "ma20_non_down": flags["ma20_non_down"],
        "breakout_current": flags["breakout_current"],
        "breakout_alt_a": flags["breakout_alt_a"],
        "value_explosion_alt_a": flags["value_explosion_alt_a"],
        "bear_preempted": flags["bear"],
        "overheated_preempted": flags["overheated"],
    }


def audit_event(definition: str, date: str, future_date: str, horizon: int,
                code: str, entry: dict, signal_close: float,
                future_close: float) -> dict:
    return {
        "provenance": "[HYPOTHETICAL]",
        "event": f"AUDIT_D{horizon}",
        "definition": definition,
        "signal_date": date,
        "audit_date": future_date,
        "horizon": horizon,
        "code": code,
        "name": entry.get("name") or code,
        "signal_close": signal_close,
        "audit_close": future_close,
        "gross_close_return_pct": (future_close / signal_close - 1.0) * 100.0,
    }


def load_ohlc() -> dict[tuple[str, str], dict[str, float]]:
    output = {}
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").zfill(6)
            date = str(row.get("date") or "")
            try:
                values = {key: float(row.get(key) or 0.0)
                          for key in ("open", "high", "low", "close")}
            except (TypeError, ValueError):
                continue
            if (not code or not date or min(values.values()) <= 0
                    or values["high"] < max(values["open"], values["close"])
                    or values["low"] > min(values["open"], values["close"])):
                continue
            output[(code, date)] = values
    return output


def intraday_audit_event(definition: str, date: str, future_date: str,
                         code: str, entry: dict, signal_close: float,
                         ohlc: dict[str, float]) -> dict:
    next_open = ohlc["open"]
    return {
        "provenance": "[HYPOTHETICAL]",
        "event": INTRADAY_EVENT,
        "definition": definition,
        "signal_date": date,
        "audit_date": future_date,
        "horizon": 1,
        "code": code,
        "name": entry.get("name") or code,
        "signal_close": signal_close,
        "next_open": next_open,
        "next_high": ohlc["high"],
        "next_low": ohlc["low"],
        "next_close": ohlc["close"],
        "gap_pct": (next_open / signal_close - 1.0) * 100.0,
        "open_to_close_pct": (ohlc["close"] / next_open - 1.0) * 100.0,
        "mfe_from_open_pct": (ohlc["high"] / next_open - 1.0) * 100.0,
        "mae_from_open_pct": (ohlc["low"] / next_open - 1.0) * 100.0,
    }


def build_missing(existing_keys: set[tuple], existing_rows: list[dict]) -> list[dict]:
    series = prod.load_series()
    ohlc_by_code_date = load_ohlc()
    all_dates = sorted({date for entry in series.values() for date in entry["dates"]})
    date_position = {date: index for index, date in enumerate(all_dates)}
    output = []
    staged_keys = set(existing_keys)
    # Append-only SIGNAL rows remain authoritative even if corrected source data
    # no longer reproduces the old signal definition.
    for row in existing_rows:
        if row.get("event") != "SIGNAL":
            continue
        date = row["signal_date"]
        global_index = date_position.get(date)
        if global_index is None or global_index + 1 >= len(all_dates):
            continue
        future_date = all_dates[global_index + 1]
        code = row["code"]
        ohlc = ohlc_by_code_date.get((code, future_date))
        if not ohlc:
            continue
        audit = intraday_audit_event(
            row["definition"], date, future_date, code,
            {"name": row.get("name") or code}, row["signal_close"], ohlc,
        )
        audit_key = event_key(audit)
        if audit_key not in staged_keys:
            output.append(audit)
            staged_keys.add(audit_key)
    for code, entry in series.items():
        close_by_date = dict(zip(entry["dates"], entry["closes"]))
        for index in range(FIRST_SAFE_INDEX, len(entry["dates"])):
            date = entry["dates"][index]
            flags = diagnostic.conditions(entry, index)
            if flags is None:
                continue
            for definition in DEFINITIONS:
                if not diagnostic.signal(flags, definition):
                    continue
                signal = signal_event(definition, date, code, entry, flags)
                key = event_key(signal)
                if key not in staged_keys:
                    output.append(signal)
                    staged_keys.add(key)
                global_index = date_position[date]
                for horizon in HORIZONS:
                    if global_index + horizon >= len(all_dates):
                        continue
                    future_date = all_dates[global_index + horizon]
                    future_close = close_by_date.get(future_date)
                    if not future_close:
                        continue
                    audit = audit_event(
                        definition, date, future_date, horizon, code, entry,
                        flags["close"], future_close,
                    )
                    audit_key = event_key(audit)
                    if audit_key not in staged_keys:
                        output.append(audit)
                        staged_keys.add(audit_key)
                if global_index + 1 < len(all_dates):
                    future_date = all_dates[global_index + 1]
                    ohlc = ohlc_by_code_date.get((code, future_date))
                    if ohlc:
                        audit = intraday_audit_event(
                            definition, date, future_date, code, entry,
                            flags["close"], ohlc,
                        )
                        audit_key = event_key(audit)
                        if audit_key not in staged_keys:
                            output.append(audit)
                            staged_keys.add(audit_key)
    return output


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="Documentary flag; every run is idempotent backfill+incremental.")
    parser.parse_args()
    old_rows, old_keys = read_events()
    new_rows = build_missing(old_keys, old_rows)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    if new_rows:
        with EVENTS.open("a", encoding="utf-8") as handle:
            for event in new_rows:
                handle.write(json.dumps(event, ensure_ascii=False,
                                        allow_nan=False) + "\n")
    all_rows = old_rows + new_rows
    signal_counts = Counter(
        row["definition"] for row in all_rows if row.get("event") == "SIGNAL"
    )
    audit_counts = Counter(
        (row["definition"], row["event"])
        for row in all_rows if str(row.get("event") or "").startswith("AUDIT_D")
    )
    intraday_counts = Counter(
        row["definition"] for row in all_rows
        if row.get("event") == INTRADAY_EVENT
    )
    source_dates = sorted({
        row.get("signal_date") for row in all_rows if row.get("signal_date")
    })
    summary = {
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS",
        "mode": "ORDER_ZERO_APPEND_ONLY",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_data": str(SOURCE),
        "source_sha256": sha256(SOURCE),
        "generator": str(Path(__file__).resolve()),
        "generator_sha256": sha256(Path(__file__)),
        "production_judge": str(ROOT / "RUN" / "trend_follow_board_v1.py") + "::judge",
        "production_judge_sha256": sha256(ROOT / "RUN" / "trend_follow_board_v1.py"),
        "definitions": list(DEFINITIONS),
        "horizons": list(HORIZONS),
        "return_definition": "signal close to D+N close, gross, no fees or slippage",
        "intraday_return_definition": (
            "next trading-day OHLC: gap=signal close to open; open-to-close; "
            "MFE=open to high; MAE=open to low; gross, no fees or slippage"
        ),
        "first_safe_series_index": FIRST_SAFE_INDEX,
        "signal_date_first": source_dates[0] if source_dates else "",
        "signal_date_last": source_dates[-1] if source_dates else "",
        "signal_counts": {definition: signal_counts[definition]
                          for definition in DEFINITIONS},
        "audit_counts": {
            definition: {f"D{horizon}": audit_counts[(definition, f"AUDIT_D{horizon}")]
                         for horizon in HORIZONS}
            for definition in DEFINITIONS
        },
        "intraday_audit_counts": {
            definition: intraday_counts[definition]
            for definition in DEFINITIONS
        },
        "rows_total": len(all_rows),
        "rows_appended": len(new_rows),
        "duplicates": 0,
        "orders_sent": 0,
    }
    atomic_json(SUMMARY, summary)
    codes_by_date = {}
    for row in all_rows:
        if row.get("event") != "SIGNAL":
            continue
        date = row["signal_date"]
        definition = row["definition"]
        day = codes_by_date.setdefault(
            date, {item: [] for item in (*DEFINITIONS, "ALL")}
        )
        day[definition].append(row["code"])
        day["ALL"].append(row["code"])
    for day in codes_by_date.values():
        for key in day:
            day[key] = sorted(set(day[key]))
    atomic_json(SIGNAL_CODES, {
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS",
        "source_data": str(SOURCE),
        "signal_codes_by_date": dict(sorted(codes_by_date.items())),
        "orders_sent": 0,
    })
    print(json.dumps({
        "status": "PASS", "events": str(EVENTS), "summary": str(SUMMARY),
        "signals": summary["signal_counts"], "rows_appended": len(new_rows),
        "orders_sent": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

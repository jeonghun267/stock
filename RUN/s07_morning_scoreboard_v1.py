# -*- coding: utf-8 -*-
"""Order-zero S07M parameter scoreboard from saved one-minute bars."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))
import strategy_07_morning_trend_v1 as engine

OUT_DIR = ROOT / "data" / "strategy_07_morning_v1"
LEDGER = OUT_DIR / "scoreboard.jsonl"
SUMMARY = OUT_DIR / "scoreboard_summary.json"
TAKES = (2.0, 3.0, 4.0)
STOPS = (-1.5, -2.0)
CUTOFFS = (1100, 1130, 1200)
COST_PCT = 0.38


def _load_bars(date: str, codes: set[str]) -> dict[str, list[dict]]:
    path = ROOT / "data" / f"prices_1m_clean_{date}.csv"
    output = defaultdict(list)
    if not path.exists():
        return output
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").zfill(6)
            if code not in codes or not str(row.get("ts") or "").startswith(date):
                continue
            try:
                item = {"ts": str(row["ts"]), "open": float(row["open"]),
                        "high": float(row["high"]), "low": float(row["low"]),
                        "close": float(row["close"])}
            except (KeyError, TypeError, ValueError):
                continue
            if min(item[key] for key in ("open", "high", "low", "close")) > 0:
                output[code].append(item)
    for rows in output.values():
        rows.sort(key=lambda row: row["ts"])
    return output


def _read_existing() -> tuple[list[dict], set[tuple]]:
    rows, keys = [], set()
    if not LEDGER.exists():
        return rows, keys
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["date"], row["code"], row["take_pct"], row["stop_pct"], row["cutoff_hhmm"])
        rows.append(row); keys.add(key)
    return rows, keys


def _simulate(rows: list[dict], entry: float, take: float, stop: float, cutoff: int) -> dict | None:
    active = [row for row in rows if 900 <= int(row["ts"][8:12]) <= cutoff]
    if not active or entry <= 0:
        return None
    take_px = entry * (1 + take / 100.0)
    stop_px = entry * (1 + stop / 100.0)
    for row in active:
        hit_take = row["high"] >= take_px
        hit_stop = row["low"] <= stop_px
        if hit_take and hit_stop:
            return {"status": "AMBIGUOUS_SAME_BAR", "exit_ts": row["ts"]}
        if hit_take:
            return {"status": "SCORED", "exit_ts": row["ts"], "exit_reason": "TAKE",
                    "gross_pct": take, "net_pct": take - COST_PCT}
        if hit_stop:
            return {"status": "SCORED", "exit_ts": row["ts"], "exit_reason": "STOP",
                    "gross_pct": stop, "net_pct": stop - COST_PCT}
    last = active[-1]
    gross = (last["close"] / entry - 1.0) * 100.0
    return {"status": "SCORED", "exit_ts": last["ts"], "exit_reason": "TIME",
            "gross_pct": gross, "net_pct": gross - COST_PCT}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=f"{datetime.now():%Y%m%d}")
    args = parser.parse_args()
    source_date, candidates = engine.load_candidates(args.date)
    codes = {row["code"] for row in candidates}
    bars = _load_bars(args.date, codes)
    old_rows, keys = _read_existing()
    new_rows = []
    for candidate in candidates:
        code = candidate["code"]
        series = bars.get(code) or []
        entry_rows = [row for row in series if 900 <= int(row["ts"][8:12]) <= 905]
        if not entry_rows:
            continue
        market_open = entry_rows[0]["open"]
        fill = market_open
        events = engine._read_events(OUT_DIR / f"s07m_events_{args.date}.csv")
        shadow_entry = next((row for row in events if row.get("event") == "SHADOW_ENTRY"
                             and str(row.get("code") or "").zfill(6) == code), None)
        if shadow_entry:
            fill = engine._number(shadow_entry.get("price")) or market_open
        for take in TAKES:
            for stop in STOPS:
                for cutoff in CUTOFFS:
                    key = (args.date, code, take, stop, cutoff)
                    if key in keys:
                        continue
                    result = _simulate(series, fill, take, stop, cutoff)
                    if result is None:
                        continue
                    row = {
                        "provenance": "[HYPOTHETICAL]", "date": args.date,
                        "source_signal_date": source_date, "code": code,
                        "definitions": candidate["definitions"], "market_open": market_open,
                        "entry_fill": fill, "open_fill_gap_pct": (fill / market_open - 1.0) * 100.0,
                        "take_pct": take, "stop_pct": stop, "cutoff_hhmm": cutoff,
                        **result, "roundtrip_cost_pct": COST_PCT,
                    }
                    new_rows.append(row); keys.add(key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if new_rows:
        with LEDGER.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    all_rows = old_rows + new_rows
    groups = defaultdict(list)
    ambiguous = defaultdict(int)
    for row in all_rows:
        key = f"TP{row['take_pct']}_SL{row['stop_pct']}_T{row['cutoff_hhmm']}"
        if row.get("status") == "SCORED":
            groups[key].append(float(row["net_pct"]))
        else:
            ambiguous[key] += 1
    summary = {"provenance": "[HYPOTHETICAL]", "status": "PASS",
               "mode": "ORDER_ZERO_SCOREBOARD", "generated_at": datetime.now().isoformat(timespec="seconds"),
               "source_date": args.date, "source_signal_date": source_date,
               "coverage": {code: len(bars.get(code) or []) for code in sorted(codes)},
               "combinations": {}, "rows_appended": len(new_rows), "orders_sent": 0}
    for take in TAKES:
        for stop in STOPS:
            for cutoff in CUTOFFS:
                key = f"TP{take}_SL{stop}_T{cutoff}"
                values = groups[key]
                summary["combinations"][key] = {
                    "n": len(values), "ambiguous": ambiguous[key],
                    "decision": "MEASURABLE" if len(values) >= 20 else "INSUFFICIENT_N",
                    "median_net_pct": statistics.median(values) if values else None,
                    "win_rate_pct": (sum(value > 0 for value in values) / len(values) * 100.0) if values else None,
                    "worst_net_pct": min(values) if values else None,
                }
    temporary = SUMMARY.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(SUMMARY)
    print(json.dumps({"status": "PASS", "coverage": summary["coverage"],
                      "rows_appended": len(new_rows), "orders_sent": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Read-only hypothetical comparison of S02 same-day re-entry cooldowns."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
EVENT_DIR = ROOT / "data" / "strategy_02_rotation_v1"
SIGNAL_DIR = ROOT / "data" / "strategy_02_signal_v1"
THRESHOLDS = (10, 15, 20)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def gross_pct(reason: str) -> float | None:
    hit = re.search(r"\bgross=(-?\d+(?:\.\d+)?)%", reason or "")
    return float(hit.group(1)) if hit else None


cases: list[dict[str, object]] = []
all_closed_gross = 0.0
all_closed_count = 0

for event_path in sorted(EVENT_DIR.glob("strategy_02_events_*.csv")):
    date = event_path.stem[-8:]
    event_rows = rows(event_path)
    for event in event_rows:
        if event.get("event") == "SELL_CONFIRMED":
            value = gross_pct(event.get("reason", ""))
            if value is not None:
                all_closed_gross += value
                all_closed_count += 1

    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in event_rows:
        if event.get("event") in {"BUY_CONFIRMED", "SELL_CONFIRMED"}:
            by_code[str(event.get("code") or "").zfill(6)].append(event)

    signal_path = SIGNAL_DIR / f"strategy_02_signals_{date}.csv"
    signal_by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    if signal_path.exists():
        for signal in rows(signal_path):
            signal_by_code[str(signal.get("code") or "").zfill(6)].append(signal)

    for code, code_events in by_code.items():
        code_events.sort(key=lambda row: parse_ts(row["ts"]))
        buy_number = 0
        previous_sell: dict[str, str] | None = None
        for index, event in enumerate(code_events):
            if event["event"] == "SELL_CONFIRMED":
                previous_sell = event
                continue
            buy_number += 1
            if buy_number < 2 or previous_sell is None:
                continue
            buy_at = parse_ts(event["ts"])
            sell_at = parse_ts(previous_sell["ts"])
            wait_minutes = (buy_at - sell_at).total_seconds() / 60.0
            later_sell = next(
                (candidate for candidate in code_events[index + 1:]
                 if candidate["event"] == "SELL_CONFIRMED"),
                None,
            )
            outcome = gross_pct(later_sell.get("reason", "")) if later_sell else None
            code_signals = signal_by_code.get(code, [])
            prior_signal = code_signals[buy_number - 2] if len(code_signals) >= buy_number - 1 else {}
            this_signal = code_signals[buy_number - 1] if len(code_signals) >= buy_number else {}
            prior_low = float(prior_signal.get("day_low") or prior_signal.get("anchor_low") or 0)
            new_low = float(this_signal.get("day_low") or this_signal.get("anchor_low") or 0)
            confirm_ticks = int(float(this_signal.get("low_confirm_ticks") or 0))
            cases.append({
                "date": date,
                "code": code,
                "name": this_signal.get("name") or event.get("name") or code,
                "buy_number": buy_number,
                "previous_sell_at": previous_sell["ts"],
                "reentry_buy_at": event["ts"],
                "wait_minutes": round(wait_minutes, 2),
                "prior_low": prior_low or None,
                "new_low": new_low or None,
                "new_low_pass": bool(prior_low and new_low and new_low < prior_low),
                "logged_confirm_ticks": confirm_ticks or None,
                "closed_gross_pct": outcome,
                "closed": outcome is not None,
            })

comparisons = []
closed_cases = [case for case in cases if case["closed_gross_pct"] is not None]
for minutes in THRESHOLDS:
    blocked = [case for case in cases if case["wait_minutes"] < minutes]
    blocked_closed = [case for case in blocked if case["closed_gross_pct"] is not None]
    blocked_gross = sum(float(case["closed_gross_pct"]) for case in blocked_closed)
    comparisons.append({
        "cooldown_minutes": minutes,
        "repeat_cases_total": len(cases),
        "blocked_cases": len(blocked),
        "blocked_closed_cases": len(blocked_closed),
        "blocked_losses": sum(float(case["closed_gross_pct"]) < 0 for case in blocked_closed),
        "blocked_wins": sum(float(case["closed_gross_pct"]) > 0 for case in blocked_closed),
        "blocked_trade_gross_sum_pct": round(blocked_gross, 4),
        "hypothetical_net_improvement_pctp": round(-blocked_gross, 4),
        "hypothetical_all_closed_gross_pct": round(all_closed_gross - blocked_gross, 4),
    })

print(json.dumps({
    "provenance": "HYPOTHETICAL",
    "window": {
        "first_event_date": min(path.stem[-8:] for path in EVENT_DIR.glob("strategy_02_events_*.csv")),
        "last_event_date": max(path.stem[-8:] for path in EVENT_DIR.glob("strategy_02_events_*.csv")),
        "event_files": len(list(EVENT_DIR.glob("strategy_02_events_*.csv"))),
        "closed_trades": all_closed_count,
        "actual_closed_gross_sum_pct": round(all_closed_gross, 4),
    },
    "comparison": comparisons,
    "repeat_cases": cases,
    "limitations": [
        "Cooldown-only retrospective filter; it is not a production replay.",
        "Open repeat trades have no final outcome and are excluded from net improvement.",
        "Saved signals usually stop at the production confirmation count; later third-tick entry is not reconstructable.",
    ],
    "sources": {
        "events": str(EVENT_DIR / "strategy_02_events_YYYYMMDD.csv"),
        "signals": str(SIGNAL_DIR / "strategy_02_signals_YYYYMMDD.csv"),
        "production_entry": str(ROOT / "RUN" / "strategy_02_rotation_engine_v1.py"),
        "production_signal": str(ROOT / "RUN" / "strategy_02_low_buy_signal_v1.py"),
        "production_changed": "NOT_CHANGED",
    },
}, ensure_ascii=False, indent=2))

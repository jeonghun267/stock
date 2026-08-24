# -*- coding: utf-8 -*-
"""Read-only Strategy 02 diagnostic for 2026-08-18."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
DATES = ["20260810", "20260811", "20260812", "20260813", "20260814", "20260818"]


def csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def gross(reason: str):
    hit = re.search(r"\bgross=(-?\d+(?:\.\d+)?)%", reason or "")
    return float(hit.group(1)) if hit else None


state_path = ROOT / "data" / "strategy_02_rotation_state_v1.json"
state = json.loads(state_path.read_text(encoding="utf-8-sig"))
history = state.get("history", [])

closed = []
for item in history:
    value = float(item.get("gross_return_pct") or 0.0)
    closed.append({
        "code": str(item.get("code") or "").zfill(6),
        "name": item.get("name") or item.get("code"),
        "entry_lane": item.get("entry_lane") or "RETEST_REBOUND",
        "entry_at": str(item.get("entry_at") or ""),
        "exit_at": str(item.get("exit_at") or ""),
        "entry_price": float(item.get("entry_price") or 0.0),
        "exit_price": float(item.get("exit_price") or 0.0),
        "gross_pct": round(value, 4),
        "mfe_pct": round(float(item.get("mfe_pct") or 0.0), 4),
        "mae_pct": round(float(item.get("mae_pct") or 0.0), 4),
        "exit_reason": item.get("exit_reason") or "",
    })

lane_summary = {}
for lane in sorted({row["entry_lane"] for row in closed}):
    group = [row for row in closed if row["entry_lane"] == lane]
    lane_summary[lane] = {
        "n": len(group),
        "wins": sum(row["gross_pct"] > 0 for row in group),
        "gross_sum_pct": round(sum(row["gross_pct"] for row in group), 4),
        "gross_avg_pct": round(sum(row["gross_pct"] for row in group) / len(group), 4),
        "hard_stops": sum(row["exit_reason"].startswith("HARD_STOP") for row in group),
    }

daily = []
for date in DATES:
    event_path = ROOT / "data" / "strategy_02_rotation_v1" / f"strategy_02_events_{date}.csv"
    sells = [row for row in csv_rows(event_path) if row.get("event") == "SELL_CONFIRMED"]
    values = [value for row in sells if (value := gross(row.get("reason") or "")) is not None]
    daily.append({
        "date": date,
        "closed": len(values),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "gross_sum_pct": round(sum(values), 4),
        "gross_avg_pct": round(sum(values) / len(values), 4) if values else None,
        "hard_stops": sum((row.get("reason") or "").startswith("HARD_STOP") for row in sells),
    })

regime_rows = [
    row for row in csv_rows(ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv")
    if (row.get("ts") or "").startswith("2026-08-18")
]
first_bear = next((row for row in regime_rows if row.get("band") == "BEAR"), None)

code_counts = Counter(row["code"] for row in closed)
repeat_damage = {
    code: round(sum(row["gross_pct"] for row in closed if row["code"] == code), 4)
    for code, count in code_counts.items() if count > 1
}
losses = [row for row in closed if row["gross_pct"] < 0]

# Re-apply the proposed same-code re-entry gate to today's preserved records.
# This can determine whether the logged BUY_READY would be blocked, but the
# signal file stops at the production two-tick confirmation and therefore
# cannot reproduce the later price/result of a hypothetical third tick.
signal_path = ROOT / "data" / "strategy_02_signal_v1" / "strategy_02_signals_20260818.csv"
event_path = ROOT / "data" / "strategy_02_rotation_v1" / "strategy_02_events_20260818.csv"
signals = csv_rows(signal_path)
events = csv_rows(event_path)
reentry_cases = []
for code in ("108490", "440110", "083650"):
    code_signals = [row for row in signals if str(row.get("code") or "").zfill(6) == code]
    code_sells = [
        row for row in events
        if str(row.get("code") or "").zfill(6) == code and row.get("event") == "SELL_CONFIRMED"
    ]
    if len(code_signals) < 2 or not code_sells:
        continue
    first_signal, second_signal = code_signals[0], code_signals[1]
    first_sell = code_sells[0]
    sell_at = datetime.fromisoformat(first_sell["ts"])
    signal_at = datetime.fromisoformat(second_signal["ts"]).replace(tzinfo=sell_at.tzinfo)
    wait_min = (signal_at - sell_at).total_seconds() / 60.0
    prior_low = float(first_signal.get("day_low") or first_signal.get("anchor_low") or 0)
    new_low = float(second_signal.get("day_low") or second_signal.get("anchor_low") or 0)
    confirms = int(float(second_signal.get("low_confirm_ticks") or 0))
    second_closed = next(
        (row for row in closed if row["code"] == code and row["entry_at"] > first_sell["ts"]),
        None,
    )
    reentry_cases.append({
        "code": code,
        "name": second_signal.get("name") or code,
        "first_sell_at": first_sell["ts"],
        "second_signal_at": second_signal["ts"],
        "wait_minutes": round(wait_min, 2),
        "wait_15m_pass": wait_min >= 15.0,
        "prior_low": prior_low,
        "new_low": new_low,
        "new_low_pass": new_low < prior_low,
        "logged_confirm_ticks": confirms,
        "three_confirm_pass_at_logged_signal": confirms >= 3,
        "second_trade_closed_gross_pct": second_closed["gross_pct"] if second_closed else None,
    })

definite_blocked_closed = [
    row for row in reentry_cases
    if not row["wait_15m_pass"] and row["second_trade_closed_gross_pct"] is not None
]
avoided_closed_loss = -sum(row["second_trade_closed_gross_pct"] for row in definite_blocked_closed)
reentry_test = {
    "rule": "same-code re-entry requires 15m wait AND new low AND 3 confirmations",
    "provenance": "HYPOTHETICAL",
    "cases": reentry_cases,
    "definitely_blocked_by_15m": len([row for row in reentry_cases if not row["wait_15m_pass"]]),
    "blocked_at_logged_signal_by_3confirm": len([
        row for row in reentry_cases if not row["three_confirm_pass_at_logged_signal"]
    ]),
    "verified_closed_loss_avoided_by_15m_pctp": round(avoided_closed_loss, 4),
    "hypothetical_closed_sum_after_definite_15m_block_pct": round(
        sum(row["gross_pct"] for row in closed) + avoided_closed_loss, 4
    ),
    "third_confirmation_later_entry_and_result": "UNVERIFIED: post-signal third-tick state is not preserved",
}

print(json.dumps({
    "as_of": state.get("heartbeat"),
    "closed_summary": {
        "n": len(closed),
        "wins": sum(row["gross_pct"] > 0 for row in closed),
        "losses": len(losses),
        "gross_sum_pct": round(sum(row["gross_pct"] for row in closed), 4),
        "gross_avg_pct": round(sum(row["gross_pct"] for row in closed) / len(closed), 4),
        "hard_stops": sum(row["exit_reason"].startswith("HARD_STOP") for row in closed),
        "loser_avg_mfe_pct": round(sum(row["mfe_pct"] for row in losses) / len(losses), 4),
        "losers_mfe_below_1pct": sum(row["mfe_pct"] < 1.0 for row in losses),
    },
    "lane_summary": lane_summary,
    "repeat_damage_pct": repeat_damage,
    "reentry_test": reentry_test,
    "first_bear": first_bear,
    "latest_regime": regime_rows[-1] if regime_rows else None,
    "daily_comparison": daily,
    "closed_trades": closed,
    "open_positions": list((state.get("positions") or {}).values()),
    "sources": {
        "state": str(state_path),
        "events": str(ROOT / "data" / "strategy_02_rotation_v1" / "strategy_02_events_YYYYMMDD.csv"),
        "fills": str(ROOT / "LOG" / "fills_20260818.csv"),
        "signals": str(ROOT / "data" / "strategy_02_signal_v1" / "strategy_02_signals_20260818.csv"),
        "regime": str(ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"),
    },
}, ensure_ascii=False, indent=2, default=str))

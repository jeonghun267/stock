# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
sys.path.insert(0, str(ROOT / "RUN"))

import strategy_02_low_buy_signal_v1 as s02

DAY = "2026-08-20"
LOG = ROOT / "LOG" / "strategy_02_rotation_v1.log"
FILLS = ROOT / "LOG" / "fills_20260820.csv"
SHADOW = ROOT / "data" / "s02_adaptive_bottom_shadow" / "s02_adaptive_bottom_shadow_20260820.jsonl"
ENGINE = ROOT / "RUN" / "strategy_02_low_buy_signal_v1.py"
OUT = ROOT / "analysis" / "s02_actual_buys_adaptive_20260820.json"

BUY_RE = re.compile(r"^\[(?P<ts>[^]]+)\] INFO BUY_CONFIRMED (?P<name>.+)\((?P<code>\d{6})\) x1 (?P<price>\d+)")
SELL_RE = re.compile(r"^\[(?P<ts>[^]]+)\] INFO SELL_CONFIRMED (?P<name>.+)\((?P<code>\d{6})\) x0 (?P<price>\d+).+ gross=(?P<gross>-?[0-9.]+)%")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    shadow_rows = [json.loads(line) for line in SHADOW.read_text(encoding="utf-8").splitlines() if line.strip()]
    opens: dict[str, dict] = {}
    trades = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        buy = BUY_RE.match(line)
        if buy and buy["ts"].startswith(DAY):
            opens[buy["code"]] = {
                "code": buy["code"], "name": buy["name"],
                "buy_ts": buy["ts"], "buy_price": int(buy["price"]),
            }
            continue
        sell = SELL_RE.match(line)
        if sell and sell["ts"].startswith(DAY) and sell["code"] in opens:
            trade = opens.pop(sell["code"])
            trade.update({
                "sell_ts": sell["ts"], "sell_price": int(sell["price"]),
                "actual_gross_pct": float(sell["gross"]),
            })
            trades.append(trade)

    for trade in trades:
        buy_ts = datetime.fromisoformat(trade["buy_ts"])
        candidates = []
        for row in shadow_rows:
            if row.get("code") != trade["code"]:
                continue
            signal_ts = datetime.fromisoformat(row["ts"])
            age = (buy_ts - signal_ts).total_seconds()
            if 0 <= age <= 20:
                candidates.append((age, row))
        if not candidates:
            raise RuntimeError(f"shadow signal missing: {trade}")
        source = min(candidates, key=lambda item: item[0])[1]
        low = float(source["anchor_low"])
        low_from_open = float(source["low_from_open_pct"])
        decision = s02.adaptive_bottom_decision(
            algorithm=source["algorithm"],
            entry_gap_pct=float(source["entry_above_anchor_pct"]),
            anchor_low=low,
            open_price=low / (1.0 + low_from_open / 100.0),
            avg_5d_range_pct=float(source["avg_5d_range_pct"]),
            regime_band=source["regime"],
            u201_pct=float(source["u201_pct"]),
            observe_sec=float(source["observe_sec"]),
        )
        trade["signal_ts"] = source["ts"]
        trade["current_lane"] = decision["adaptive_lane"]
        trade["current_action"] = "BUY" if decision["adaptive_pass"] else "BLOCK"
        trade["actual_gross_krw"] = trade["sell_price"] - trade["buy_price"]
        trade["counterfactual_gross_krw"] = (
            trade["actual_gross_krw"] if decision["adaptive_pass"] else 0
        )

    report = {
        "provenance": "[HYPOTHETICAL]",
        "date": DAY.replace("-", ""),
        "scope": "today_strategy02_actual_buys_all",
        "production_entry_point": "RUN/strategy_02_low_buy_signal_v1.py::adaptive_bottom_decision",
        "production_code_changed": "CHANGED",
        "source_data": [str(LOG), str(FILLS), str(SHADOW)],
        "engine_sha256": sha256(ENGINE),
        "command": r"C:\python310\python.exe -B -X utf8 tests\hypothetical_s02_actual_buys_20260820.py",
        "summary": {
            "actual_buy_count": len(trades),
            "current_buy_count": sum(t["current_action"] == "BUY" for t in trades),
            "current_block_count": sum(t["current_action"] == "BLOCK" for t in trades),
            "actual_gross_krw": sum(t["actual_gross_krw"] for t in trades),
            "counterfactual_gross_krw": sum(t["counterfactual_gross_krw"] for t in trades),
        },
        "trades": trades,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if len(trades) == 8 else 2


if __name__ == "__main__":
    raise SystemExit(main())

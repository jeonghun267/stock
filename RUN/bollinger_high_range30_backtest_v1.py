# -*- coding: utf-8 -*-
"""Generate a HYPOTHETICAL report for the order-zero high-range30 BB shadow."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bollinger_high_range30_shadow_v1 import run_once as run_shadow_once
from common_high_range_watchlist_v1 import select_candidates


BASE = Path(r"C:\stock_bot")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYYMMDD")
    parser.add_argument("--base", type=Path, default=BASE)
    args = parser.parse_args()
    base, date = args.base, args.date
    price_path = base / "data" / f"prices_1m_clean_{date}.csv"
    eod_path = base / "data" / "eod_daily_bars.csv"
    strategy_path = base / "RUN" / "bollinger_high_range30_shadow_v1.py"
    selector_path = base / "RUN" / "common_high_range_watchlist_v1.py"

    trading_day = datetime.strptime(date, "%Y%m%d")
    prior_day = (trading_day - timedelta(days=1)).strftime("%Y%m%d")
    eod = pd.read_csv(eod_path, dtype={"code": str, "date": str})
    eod = eod[eod["date"].astype(str) <= prior_day]
    prices = pd.read_csv(price_path, dtype={"code": str, "ts": str})
    prices["code"] = prices["code"].str.zfill(6)
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["close"]).sort_values(["code", "ts"])

    with tempfile.TemporaryDirectory(prefix="bb_high_range30_") as temp_name:
        temp = Path(temp_name)
        filtered_eod = temp / "eod_before_target.csv"
        eod.to_csv(filtered_eod, index=False)
        source_date, candidates = select_candidates(filtered_eod)
        captured_codes = set(prices["code"])
        tested = [row for row in candidates if row["code"] in captured_codes]

        for candidate in tested:
            minute_rows = []
            code_prices = prices[prices["code"] == candidate["code"]]
            payload = {"candidates": [candidate]}
            for row in code_prices.itertuples(index=False):
                stamp = str(row.ts)
                now = datetime.strptime(stamp, "%Y%m%d%H%M%S")
                minute_rows.append([stamp[:12], float(row.close)])
                live_state = {"codes": {candidate["code"]: {
                    "status": "LIVE", "current": float(row.close),
                    "minute_closes": minute_rows[-120:],
                }}}
                run_shadow_once(temp, payload, live_state, now)

        event_path = temp / "data" / "shadow" / f"bollinger_high_range30_{date}.csv"
        events = []
        if event_path.exists():
            with event_path.open(encoding="utf-8-sig", newline="") as handle:
                events = list(csv.DictReader(handle))
        exits = [row for row in events if row.get("event") == "SHADOW_EXIT"]
        returns = [float(row["return_pct"]) for row in exits]
        report = {
            "provenance": "HYPOTHETICAL",
            "date": date,
            "stock_code_scope": "high_range_candidates_with_captured_1m_data",
            "source_date_for_universe": source_date,
            "source_files": {
                str(price_path): _sha256(price_path),
                str(eod_path): _sha256(eod_path),
            },
            "entry_point": str(Path(__file__).resolve()),
            "strategy_file": str(strategy_path),
            "strategy_sha256": _sha256(strategy_path),
            "selector_file": str(selector_path),
            "selector_sha256": _sha256(selector_path),
            "production_code_changed_for_run": "NOT_CHANGED",
            "reproducible_command": f'C:\\python310\\python.exe -X utf8 "{Path(__file__).resolve()}" --date {date}',
            "universe_candidate_count": len(candidates),
            "candidates_with_kiwoom_1m_data": len(tested),
            "candidate_codes_tested": [row["code"] for row in tested],
            "entry_count": sum(row.get("event") == "SHADOW_ENTRY" for row in events),
            "completed_trade_count": len(exits),
            "win_count": sum(value > 0 for value in returns),
            "loss_count": sum(value <= 0 for value in returns),
            "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
            "mean_return_pct": round(statistics.fmean(returns), 4) if returns else None,
            "median_return_pct": round(statistics.median(returns), 4) if returns else None,
            "simple_sum_return_pct": round(sum(returns), 4) if returns else None,
            "events": events,
            "limitations": [
                "No broker fills or slippage/fees; this is not an actual trading result.",
                "Only candidates present in the saved Kiwoom one-minute file were tested.",
                "The Bollinger shadow was created after the target date and is reconstructed.",
            ],
        }
    out = base / "reports" / "hypothetical" / f"bollinger_high_range30_{date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "provenance", "date", "universe_candidate_count", "candidates_with_kiwoom_1m_data",
        "entry_count", "completed_trade_count", "win_count", "loss_count", "win_rate_pct",
        "mean_return_pct", "median_return_pct", "simple_sum_return_pct")}, ensure_ascii=False, indent=2))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

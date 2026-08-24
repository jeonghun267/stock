# -*- coding: utf-8 -*-
"""Truth-gated audit of today's S01 fills against preserved S01 v3 inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
PRODUCTION = (
    ROOT / "RUN" / "strategy_01_open_surge_signal_v2.py",
    ROOT / "RUN" / "strategy_01_entry_runtime_v3.py",
    ROOT / "RUN" / "strategy_01_entry_policy_v3.py",
    ROOT / "RUN" / "strategy_01_signal_contract_v2.py",
    ROOT / "RUN" / "strategy_01_rotation_engine_v2.py",
)


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    day = args.date.replace("-", "")
    events = ROOT / "data" / "strategy_01_rotation_v2" / f"strategy_01_events_{day}.csv"
    fills = ROOT / "LOG" / f"fills_{day}.csv"
    preserved_v3 = ROOT / "data" / "shadow" / f"strategy_01_entry_v3_shadow_{day}.csv"
    buy_events = [row for row in read_rows(events)
                  if row.get("strategy_id") == "S01_OPEN_SURGE" and row.get("event") == "BUY_CONFIRMED"]
    fill_rows = read_rows(fills)
    actual = []
    for event in buy_events:
        code = str(event.get("code") or "").zfill(6)
        matching = [row for row in fill_rows if str(row.get("code") or "").zfill(6) == code
                    and row.get("otype") == "+매수"]
        raw_fill = matching[0] if matching else {}
        actual.append({
            "code": code,
            "broker_fill": raw_fill,
            "v3_provenance": "[UNVERIFIED]",
            "v3_result": "NOT_REPLAYABLE",
            "missing_fields": [
                "AUCTION_EXPECTED_PRICE_HISTORY_0840_0900",
                "AUCTION_EXPECTED_VOLUME_PERCENTILE",
                "SIGNED_FLOW_1S_HISTORY",
                "SECOND_HIGHER_LOW_SEQUENCE",
                "EXACT_3_SECOND_BATCH",
            ],
        })
    payload = {
        "date": day,
        "provenance": "[UNVERIFIED]",
        "reason": "S01_V3_WAS_NOT_RUNNING_AND_REQUIRED_HISTORICAL_INPUTS_WERE_NOT_PRESERVED",
        "sources": {"broker_fills": str(fills), "strategy_events": str(events),
                    "v3_exact_input": str(preserved_v3)},
        "v3_exact_input_exists": preserved_v3.exists(),
        "production_files": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in PRODUCTION},
        "production_code_changed": "CHANGED",
        "actual_s01_buy_count": len(actual),
        "rows": actual,
        "reproducible_command": (
            f"C:\\python310\\python.exe -B -X utf8 "
            f"C:\\stock_bot\\RUN\\s01_entry_v3_today_truth_check.py --date {day}"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

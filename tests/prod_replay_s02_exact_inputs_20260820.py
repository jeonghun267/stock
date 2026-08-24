# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_02_low_buy_signal_v1 as S02  # noqa: E402
from 저점매수_매도소진 import MarketPoint  # noqa: E402


DAY = "20260820"
INPUTS = ROOT / "data" / "s02_exact_replay" / f"s02_exact_inputs_{DAY}.csv"
EVENTS = (
    ROOT / "data" / "s02_exact_replay_runtime" / "events"
    / f"strategy_02_signals_{DAY}.csv"
)
ENGINE = RUN / "strategy_02_low_buy_signal_v1.py"
OUT = ROOT / "data" / "s02_exact_replay" / f"prod_replay_s02_exact_inputs_{DAY}.json"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row):
    return (
        str(row.get("ts") or ""),
        str(row.get("code") or "").zfill(6),
        number(row.get("price")),
        str(row.get("algorithm") or ""),
    )


def replay(rows, *, adaptive: bool):
    monitor = S02.LowBuySignalMonitor(adaptive_bottom_enabled=adaptive)
    fired = []
    for raw in rows:
        ts = datetime.fromisoformat(raw["ts"])
        point = MarketPoint(
            ts=ts,
            price=number(raw.get("price")),
            cum_vol=number(raw.get("cum_vol")),
            che_str=number(raw.get("che_str")),
            ask_tot=number(raw.get("ask_tot")),
            bid_tot=number(raw.get("bid_tot")),
            buy_money_cum=number(raw.get("buy_money_cum")),
            sell_money_cum=number(raw.get("sell_money_cum")),
            buy_vol_cum=number(raw.get("buy_vol_cum"), -1.0),
            sell_vol_cum=number(raw.get("sell_vol_cum"), -1.0),
            best_ask_px=number(raw.get("best_ask_px")),
            best_bid_px=number(raw.get("best_bid_px")),
            best_ask_qty=number(raw.get("best_ask_qty")),
            best_bid_qty=number(raw.get("best_bid_qty")),
            broker_day_low=number(raw.get("broker_day_low")),
            broker_day_high=number(raw.get("broker_day_high")),
        )
        row, hit = monitor.process_point(
            str(raw.get("code") or "").zfill(6),
            str(raw.get("name") or ""),
            point,
            allow_signal=str(raw.get("allow_signal") or "0") == "1",
            open_price=number(raw.get("open_price")),
            session_high=number(raw.get("session_high")),
            regime_band=str(raw.get("regime_band") or "UNKNOWN"),
            u201_pct=number(raw.get("u201_pct"), None),
            avg_5d_range_pct=number(raw.get("avg_5d_range_pct")),
        )
        if hit:
            fired.append(row)
    return fired


def main() -> int:
    with INPUTS.open(encoding="utf-8-sig", newline="") as handle:
        inputs = list(csv.DictReader(handle))
    with EVENTS.open(encoding="utf-8-sig", newline="") as handle:
        expected = list(csv.DictReader(handle))

    diagnostics = io.StringIO()
    with redirect_stdout(diagnostics):
        baseline = replay(inputs, adaptive=False)
        adaptive = replay(inputs, adaptive=True)
    expected_keys = [key(row) for row in expected]
    baseline_keys = [key(row) for row in baseline]
    adaptive_keys = [key(row) for row in adaptive]
    adaptive_invalid = [
        row for row in adaptive
        if row.get("adaptive_pass") is not True
        or row.get("adaptive_lane") not in {"FAST", "RETEST"}
    ]
    passed = (
        len(inputs) > 0
        and expected_keys == baseline_keys
        and expected_keys == adaptive_keys
        and not adaptive_invalid
    )
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": DAY,
        "production_code_changed": "CHANGED",
        "production_entry_point": (
            "RUN/strategy_02_low_buy_signal_v1.py::"
            "LowBuySignalMonitor.process_point"
        ),
        "source_data": [str(INPUTS), str(EVENTS)],
        "sha256": {
            str(INPUTS): sha256(INPUTS),
            str(EVENTS): sha256(EVENTS),
            str(ENGINE): sha256(ENGINE),
        },
        "command": (
            r"C:\python310\python.exe -B -X utf8 "
            r"tests\prod_replay_s02_exact_inputs_20260820.py"
        ),
        "raw_result": {
            "input_rows": len(inputs),
            "expected": [list(item) for item in expected_keys],
            "baseline": [list(item) for item in baseline_keys],
            "adaptive": [
                {
                    "key": list(key(row)),
                    "lane": row.get("adaptive_lane"),
                    "reason": row.get("adaptive_reason"),
                }
                for row in adaptive
            ],
            "adaptive_invalid": adaptive_invalid,
            "diagnostic_line_count": len(diagnostics.getvalue().splitlines()),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "provenance": report["provenance"],
        "status": report["status"],
        "input_rows": len(inputs),
        "expected": len(expected),
        "baseline": len(baseline),
        "adaptive": len(adaptive),
        "adaptive_lanes": [row.get("adaptive_lane") for row in adaptive],
    }, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

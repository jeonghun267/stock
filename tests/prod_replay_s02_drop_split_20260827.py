# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path("C:/stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_02_low_buy_signal_v1 as S02  # noqa: E402
from 저점매수_매도소진 import MarketPoint  # noqa: E402


DAY = "20260827"
CODE = "417030"
INPUTS = ROOT / "data" / "s02_exact_replay" / f"s02_exact_inputs_{DAY}.csv"
ENGINE = RUN / "strategy_02_low_buy_signal_v1.py"
OUT = (
    ROOT / "data" / "s02_exact_replay"
    / f"prod_replay_s02_drop_split_{DAY}.json"
)


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    monitor = S02.LowBuySignalMonitor()
    input_rows = 0
    blocked = 0
    fired = 0
    for raw in csv.DictReader(INPUTS.open(encoding="utf-8-sig", newline="")):
        if str(raw.get("code") or "").zfill(6) != CODE:
            continue
        input_rows += 1
        point = MarketPoint(
            ts=datetime.fromisoformat(raw["ts"]),
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
        decision, hit = monitor.process_point(
            CODE,
            str(raw.get("name") or ""),
            point,
            allow_signal=str(raw.get("allow_signal") or "0") == "1",
            open_price=number(raw.get("open_price")),
            session_high=number(raw.get("session_high")),
            regime_band=str(raw.get("regime_band") or "UNKNOWN"),
            u201_pct=number(raw.get("u201_pct"), None),
            avg_5d_range_pct=number(raw.get("avg_5d_range_pct")),
        )
        blocked += int(
            decision.get("reason") == "S02_DROP_GTE_8PCT_HANDOFF_S06"
        )
        fired += int(hit)

    passed = input_rows > 0 and blocked == 0 and fired > 0
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": DAY,
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_point": (
            "RUN/strategy_02_low_buy_signal_v1.py::"
            "LowBuySignalMonitor.process_point"
        ),
        "source_data": [str(INPUTS)],
        "sha256": {
            str(INPUTS): sha256(INPUTS),
            str(ENGINE): sha256(ENGINE),
        },
        "command": (
            "python -B -X utf8 "
            "tests/prod_replay_s02_drop_split_20260827.py"
        ),
        "raw_result": {
            "code": CODE,
            "input_rows": input_rows,
            "s02_8pct_handoff_decisions": blocked,
            "s02_buy_ready_decisions": fired,
        },
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

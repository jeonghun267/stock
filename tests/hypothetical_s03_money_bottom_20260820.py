from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "RUN"
sys.path.insert(0, str(RUN))

import strategy_02_low_buy_signal_v1 as s02  # noqa: E402


DAY = "20260820"
SIGNALS = ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json"
REGIME = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
TARGETS = {
    ("237690", "2026-08-20T09:08:53.454"),
    ("125490", "2026-08-20T09:10:08.586"),
    ("487400", "2026-08-20T09:10:20.268"),
    ("084370", "2026-08-20T09:10:33.253"),
    ("178320", "2026-08-20T09:14:43.531"),
    ("064760", "2026-08-20T09:17:07.335"),
}


def main() -> int:
    payload = json.loads(SIGNALS.read_text(encoding="utf-8-sig"))
    rows = [
        row for row in payload.get("signals", [])
        if (str(row.get("code") or "").zfill(6), str(row.get("ts") or "")) in TARGETS
    ]
    results = []
    for row in sorted(rows, key=lambda item: item["ts"]):
        ts = datetime.fromisoformat(row["ts"])
        regime, u201 = s02._market_regime_at(REGIME, ts)
        source_algorithm = str(row.get("algorithm") or "")
        mapped_algorithm = (
            "S02_S06_DIRECT_REBOUND_V1"
            if source_algorithm == "S03_EARLY_60S_REBOUND_V1"
            else source_algorithm
        )
        anchor = float(row.get("anchor_low") or 0.0)
        price = float(row.get("price") or 0.0)
        decision = s02.adaptive_bottom_decision(
            algorithm=mapped_algorithm,
            entry_gap_pct=((price / anchor - 1.0) * 100.0) if anchor > 0 else 999.0,
            anchor_low=anchor,
            open_price=float(row.get("open_price") or 0.0),
            avg_5d_range_pct=float(row.get("hr_avg5_range") or 0.0),
            regime_band=regime,
            u201_pct=u201,
            observe_sec=float(row.get("observe_sec") or 0.0),
        )
        results.append({
            "code": row["code"],
            "name": row.get("name", ""),
            "ts": row["ts"],
            "source_algorithm": source_algorithm,
            "mapped_algorithm": mapped_algorithm,
            "entry_gap_pct": round((price / anchor - 1.0) * 100.0, 4),
            **decision,
        })

    complete = len(results) == len(TARGETS)
    print(json.dumps({
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS" if complete else "INCOMPLETE",
        "date": DAY,
        "production_code_changed": "NOT_CHANGED",
        "production_function_used": (
            "RUN/strategy_02_low_buy_signal_v1.py::adaptive_bottom_decision"
        ),
        "source_data": [str(SIGNALS), str(REGIME)],
        "mapping_assumption": (
            "S03 EARLY_LOW is evaluated as S02 DIRECT_REBOUND; "
            "S03 OPEN_CRASH retains STAIRCASE_RETEST"
        ),
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())

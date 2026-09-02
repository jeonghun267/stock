# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path("C:/stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_03_rotation_engine_v1 as rotation  # noqa: E402
from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector  # noqa: E402
from 골짜기_급반등 import MicroPoint, PriorProfile, RapidReboundMonitor  # noqa: E402


INPUT = ROOT / "tests" / "fixtures" / "s03_intraday_direct_rebound_20260827.json"
SNAPSHOT = ROOT / "tests" / "fixtures" / "s03_intraday_order_snapshot_20260827.json"
REPORT = ROOT / "reports" / "prod_replay_s03_intraday_staircase_20260902.json"
SOURCES = (
    RUN / "골짜기_급반등.py",
    RUN / "strategy_03_intraday_rebound_v1.py",
    RUN / "strategy_03_flow_turn_fast_v1.py",
    RUN / "strategy_03_signal_contract_v1.py",
    RUN / "strategy_03_rotation_engine_v1.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    saved = json.loads(INPUT.read_text(encoding="utf-8"))
    start = datetime(2026, 8, 27, 9, 30, 0)
    monitor = RapidReboundMonitor()
    profile = PriorProfile(previous_close=float(saved["previous_close"]))
    emitted = None
    for raw in saved["points"]:
        point = MicroPoint(
            ts=start + timedelta(seconds=int(raw["second"])),
            price=float(raw["price"]),
            minute_low=float(raw.get("minute_low") or 0),
            open_price=float(saved["previous_close"]),
            buy_money_cum=float(raw["buy"]),
            sell_money_cum=float(raw["sell"]),
            buy_volume_cum=float(raw["buy"]),
            sell_volume_cum=float(raw["sell"]),
            best_ask_px=float(raw["price"]) + 10,
            best_bid_px=float(raw["price"]),
            best_ask_qty=float(raw.get("ask_qty") or 100),
            best_bid_qty=1000,
        )
        row, fired = monitor.process_point(
            saved["code"], saved["name"], point, profile, allow_signal=True,
        )
        if fired:
            emitted = row
            break

    selected = []
    if emitted is not None:
        payload = {
            "schema": "strategy_03_valley_rapid_rebound_signal_v1",
            "date": saved["date"],
            "updated_at": emitted["ts"],
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "signals": [emitted],
        }
        original_drop_dir = rotation.DROP_LOG_DIR
        with tempfile.TemporaryDirectory(prefix="s03_replay_") as temp_dir:
            rotation.DROP_LOG_DIR = Path(temp_dir)
            try:
                selector = make_strategy03_signal_selector(
                    SNAPSHOT,
                    snapshot_max_age_sec=4,
                    early_low_live_enabled=False,
                    flow_turn_live_enabled=False,
                    bottom_all_lanes_live_enabled=False,
                )
                selected = selector(
                    payload,
                    now=datetime.fromisoformat(emitted["ts"]) + timedelta(seconds=1),
                    max_age_sec=5,
                )
            finally:
                rotation.DROP_LOG_DIR = original_drop_dir

    expected = saved["expected"]
    passed = bool(
        emitted
        and emitted.get("action") == expected["action"]
        and emitted.get("reason") == expected["reason"]
        and emitted.get("entry_lane") == expected["entry_lane"]
        and float(emitted.get("anchor_low") or 0) == float(expected["anchor_low"])
        and -8.0 < float(emitted.get("intraday_drawdown_pct") or 0) <= -4.0
        and float(expected["rebound_min_pct"]) <= float(emitted.get("rebound_pct") or 0)
        <= float(expected["rebound_max_pct"])
        and len(selected) == 1
    )
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": saved["date"],
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_points": [
            "RUN/골짜기_급반등.py::RapidReboundMonitor.process_point",
            "RUN/strategy_03_intraday_rebound_v1.py::IntradayReboundDetector.feed",
            "RUN/strategy_03_signal_contract_v1.py::select_fresh_signals",
            "RUN/strategy_03_rotation_engine_v1.py::make_strategy03_signal_selector"
        ],
        "source_data": [str(INPUT), str(SNAPSHOT)],
        "sha256": {
            str(INPUT): sha256(INPUT),
            str(SNAPSHOT): sha256(SNAPSHOT),
            **{str(p): sha256(p) for p in SOURCES},
        },
        "non_decision_override": "DROP_LOG_DIR redirected to an isolated temporary directory",
        "command": "python -B -X utf8 tests/prod_replay_s03_intraday_direct_rebound_20260827.py",
        "raw_result": {
            "emitted_decision": ({
                "action": emitted.get("action"),
                "reason": emitted.get("reason"),
                "entry_lane": emitted.get("entry_lane"),
                "anchor_low": emitted.get("anchor_low"),
                "rebound_band_pass": bool(
                    float(expected["rebound_min_pct"])
                    <= float(emitted.get("rebound_pct") or 0)
                    <= float(expected["rebound_max_pct"])
                ),
                "first_rebound_pct": emitted.get("first_rebound_pct"),
                "pullback_depth_pct": emitted.get("pullback_depth_pct"),
                "higher_low_pct": emitted.get("higher_low_pct"),
                "second_rebound_pct": emitted.get("second_rebound_pct"),
            } if emitted else None),
            "selected_count": len(selected),
            "expected_action": expected["action"],
            "expected_lane": expected["entry_lane"],
            "expected_anchor_low": expected["anchor_low"]
        }
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

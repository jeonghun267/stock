# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path("C:/stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_signal_contract_v1 import ACTIVE_ENTRY_LANES  # noqa: E402
from 골짜기_급반등 import RapidReboundMonitor  # noqa: E402


DAY = "20260827"
REPLAY_DIR = ROOT / "data" / "s03_two_lane_replay" / "20260827_133754"
INPUT = REPLAY_DIR / "s03_signal_before_cleanup.json"
OUT = REPLAY_DIR / "prod_replay_s03_two_entry_lanes_20260827.json"
SOURCES = (
    RUN / "골짜기_급반등.py",
    RUN / "strategy_03_signal_contract_v1.py",
    RUN / "hidden" / "SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8-sig"))
    source_lanes = {
        str(row.get("entry_lane") or "OPEN_CRASH")
        for row in payload.get("signals") or []
        if isinstance(row, dict)
    }
    monitor = RapidReboundMonitor()
    monitor.restore(payload, DAY)
    restored_lanes = {
        str(row.get("entry_lane") or "")
        for row in monitor.signals
        if isinstance(row, dict)
    }
    active_lanes = set(ACTIVE_ENTRY_LANES)
    passed = (
        "EARLY_LOW" in source_lanes
        and active_lanes == {"OPEN_CRASH", "INTRADAY_CRASH"}
        and restored_lanes <= active_lanes
        and "EARLY_LOW" not in restored_lanes
    )
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": DAY,
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_points": [
            "RUN/골짜기_급반등.py::RapidReboundMonitor.restore",
            "RUN/strategy_03_signal_contract_v1::_lane_valid",
        ],
        "source_data": [str(INPUT)],
        "sha256": {
            str(INPUT): sha256(INPUT),
            **{str(path): sha256(path) for path in SOURCES},
        },
        "command": (
            "python -B -X utf8 "
            "tests/prod_replay_s03_two_entry_lanes_20260827.py"
        ),
        "raw_result": {
            "active_entry_lanes": sorted(active_lanes),
            "source_signal_lanes": sorted(source_lanes),
            "restored_signal_lanes": sorted(restored_lanes),
            "early_low_restored": "EARLY_LOW" in restored_lanes,
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

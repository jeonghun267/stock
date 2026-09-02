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

from strategy_03_rotation_engine_v1 import Strategy03Engine  # noqa: E402


INPUT = ROOT / "tests" / "fixtures" / "s03_lane_slots_3plus3_20260827.json"
ENGINE = RUN / "strategy_03_rotation_engine_v1.py"
REPORT = ROOT / "reports" / "prod_replay_s03_lane_slots_20260827.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    engine = Strategy03Engine.__new__(Strategy03Engine)
    engine._active_positions = lambda: payload["active_positions"]
    selected = engine._apply_lane_slot_limit(payload["signals"])
    selected_codes = [str(row["code"]).zfill(6) for row in selected]
    passed = selected_codes == payload["expected_selected_codes"]
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": "20260827",
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_points": [
            "RUN/strategy_03_rotation_engine_v1.py::Strategy03Engine._apply_lane_slot_limit"
        ],
        "source_data": [str(INPUT)],
        "sha256": {str(INPUT): sha256(INPUT), str(ENGINE): sha256(ENGINE)},
        "command": "python -B -X utf8 tests/prod_replay_s03_lane_slots_20260827.py",
        "raw_result": {
            "selected_codes": selected_codes,
            "expected_selected_codes": payload["expected_selected_codes"]
        }
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_06_crash_low_chase_v1 as production

FIXTURE = ROOT / "tests" / "fixtures" / "s06_state_save_retry_20260830.json"
REPORT = ROOT / "reports" / "prod_replay_s06_state_save_retry_20260830.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    saved_input = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    payload = saved_input["payload"]
    denied = int(saved_input["transient_permission_denials"])
    original_replace = os.replace
    attempts = 0
    sources: list[Path] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        destination = Path(temp_dir) / "state.json"

        def replace_after_denials(source, target):
            nonlocal attempts
            attempts += 1
            sources.append(Path(source))
            if attempts <= denied:
                raise PermissionError(5, "saved transient denial")
            return original_replace(source, target)

        with patch.object(production.os, "replace", side_effect=replace_after_denials):
            saved = production.write_json_atomic(destination, payload)

        persisted = (
            json.loads(destination.read_text(encoding="utf-8"))
            if destination.exists() else None
        )
        unique_temp = bool(
            sources
            and sources[0] != destination.with_suffix(".json.tmp")
            and sources[0].name.startswith("state.json.")
        )
        leftovers = list(Path(temp_dir).glob("*.tmp"))

    passed = bool(
        saved
        and attempts == denied + 1
        and persisted == payload
        and unique_temp
        and not leftovers
    )
    source = RUN / "strategy_06_crash_low_chase_v1.py"
    replay = Path(__file__).resolve()
    report = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS" if passed else "FAIL",
        "date": saved_input["date"],
        "performance_scope": "DECISION_ONLY",
        "production_code_changed": "CHANGED",
        "production_entry_point": (
            "RUN/strategy_06_crash_low_chase_v1.py::write_json_atomic"
        ),
        "source_data": [str(FIXTURE)],
        "sha256": {
            str(FIXTURE): sha256(FIXTURE),
            str(source): sha256(source),
            str(replay): sha256(replay),
        },
        "command": (
            "python -B -X utf8 "
            "tests/prod_replay_s06_state_save_retry_20260830.py"
        ),
        "raw_result": {
            "saved": saved,
            "attempts": attempts,
            "configured_denials": denied,
            "persisted_matches": persisted == payload,
            "unique_temp": unique_temp,
            "temp_cleanup": not leftovers,
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[PROD_REPLAY] {report['status']} "
        f"entry_point={report['production_entry_point']} report={REPORT}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
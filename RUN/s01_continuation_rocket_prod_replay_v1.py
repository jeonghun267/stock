# -*- coding: utf-8 -*-
"""Decision-only production replay for the S01 continuation ROCKET live gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from s01_entry_v3_prod_replay_v1 import _restart_boundaries
from strategy_01_entry_runtime_v3 import EntryRuntimeV3
from strategy_01_open_surge_signal_v2 import ShadowPoint, promote_rocket_live


ROOT = Path(r"C:\stock_bot")
DEFAULT_SOURCE = (
    ROOT / "data" / "s01_entry_v3_exact_replay"
    / "s01_entry_v3_exact_inputs_20260902.jsonl"
)
DEFAULT_RESTART_LOG = ROOT / "data" / "LOG" / "sched_STRATEGY01_SIGNAL.log"
PRODUCTION_FILES = (
    RUN_DIR / "strategy_01_entry_policy_v3.py",
    RUN_DIR / "strategy_01_entry_runtime_v3.py",
    RUN_DIR / "strategy_01_open_surge_signal_v2.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(source: Path, restart_log: Path, command: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "provenance": "[UNVERIFIED]",
        "status": "BLOCKED",
        "date": "20260902",
        "approved_live_date": "20260903",
        "source_data": [str(source), str(restart_log)],
        "production_entry_points": [
            "RUN/strategy_01_entry_runtime_v3.py:EntryRuntimeV3.process_batch",
            "RUN/strategy_01_open_surge_signal_v2.py:promote_rocket_live",
        ],
        "production_code": "CHANGED",
        "performance_scope": "DECISION_ONLY",
        "command": command,
        "records": 0,
        "continuation_ready_cases": 0,
        "continuation_promoted_cases": 0,
        "requested_quantities": [],
        "violations": [],
    }
    if not source.exists() or source.stat().st_size <= 0:
        report["violations"].append("NO_PRESERVED_INPUT")
        return report

    current_hashes = {str(path): _sha(path) for path in PRODUCTION_FILES}
    report["sha256"] = {
        "source": _sha(source),
        "restart_log": _sha(restart_log),
        "replay_tool": _sha(Path(__file__)),
        "production_files": current_hashes,
    }
    boundaries = _restart_boundaries(restart_log, "20260902")
    report["restart_boundaries"] = [
        boundary.isoformat(timespec="seconds") for boundary in boundaries
    ]
    runtime = EntryRuntimeV3({"codes": {}})
    boundary_index = 0
    capture_hashes: dict[str, str] | None = None
    promoted_signals: list[dict[str, Any]] = []

    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            report["records"] += 1
            required = {
                "schema", "captured_at", "allow_select", "points",
                "minute_payload", "trend_rows", "volume_baseline_rows",
                "production_files",
            }
            missing = sorted(required.difference(record))
            if missing:
                report["violations"].append(
                    f"INPUT_FIELDS_MISSING:{line_number}:{','.join(missing)}"
                )
                continue
            if record.get("schema") != "s01_entry_v3_exact_input_v1":
                report["violations"].append(f"BAD_SCHEMA:{line_number}")
                continue
            record_hashes = dict(record.get("production_files") or {})
            if capture_hashes is None:
                capture_hashes = record_hashes
            elif record_hashes != capture_hashes:
                report["violations"].append(f"MIXED_CAPTURE_HASH:{line_number}")
                continue

            captured_at = datetime.fromisoformat(str(record["captured_at"]))
            while (
                boundary_index < len(boundaries)
                and boundaries[boundary_index] <= captured_at
            ):
                runtime = EntryRuntimeV3({"codes": {}})
                boundary_index += 1
            runtime.baseline.update(record.get("volume_baseline_rows") or {})
            points = []
            for raw in record.get("points") or []:
                point = dict(raw)
                point["ts"] = datetime.fromisoformat(str(point.get("ts") or ""))
                points.append(ShadowPoint(**point))
            actual_signals, _actual_audit = runtime.process_batch(
                points,
                record.get("minute_payload") or {},
                record.get("trend_rows") or {},
                allow_select=bool(record.get("allow_select")),
            )
            continuation_rows = [
                row for row in actual_signals
                if str(row.get("reason") or "") == "CONTINUATION_ROCKET_CONFIRMED"
            ]
            report["continuation_ready_cases"] += len(continuation_rows)
            promoted = promote_rocket_live(
                actual_signals,
                promoted_signals,
                enabled=True,
            )
            if (
                promoted is not None
                and str(promoted.get("reason") or "")
                == "CONTINUATION_ROCKET_CONFIRMED"
            ):
                promoted_signals.append(promoted)
                report["continuation_promoted_cases"] += 1
                report["requested_quantities"].append(
                    int(promoted.get("requested_quantity") or 0)
                )
            elif promoted is not None:
                promoted_signals.append(promoted)

    report["capture_production_hashes"] = capture_hashes or {}
    if report["records"] <= 0:
        report["violations"].append("NO_RECORDS_PROCESSED")
    if report["continuation_ready_cases"] <= 0:
        report["violations"].append("NO_CONTINUATION_READY_CASE")
    if report["continuation_promoted_cases"] <= 0:
        report["violations"].append("NO_CONTINUATION_PROMOTED_CASE")
    if any(quantity != 1 for quantity in report["requested_quantities"]):
        report["violations"].append("QUANTITY_NOT_ONE")
    if not report["violations"]:
        report.update({"provenance": "[PROD_REPLAY]", "status": "PASS"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--restart-log", type=Path, default=DEFAULT_RESTART_LOG)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    command = (
        f'C:\\python310\\python.exe -B -X utf8 '
        f'RUN\\s01_continuation_rocket_prod_replay_v1.py '
        f'--input "{args.input}" --restart-log "{args.restart_log}" '
        f'--out "{args.out}"'
    )
    try:
        report = replay(args.input, args.restart_log, command)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        report = {
            "provenance": "[UNVERIFIED]",
            "status": "BLOCKED",
            "date": "20260902",
            "approved_live_date": "20260903",
            "source_data": [str(args.input), str(args.restart_log)],
            "production_entry_points": [
                "RUN/strategy_01_entry_runtime_v3.py:EntryRuntimeV3.process_batch",
                "RUN/strategy_01_open_surge_signal_v2.py:promote_rocket_live",
            ],
            "production_code": "CHANGED",
            "performance_scope": "DECISION_ONLY",
            "command": command,
            "violations": [f"REPLAY_ERROR:{exc}"],
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

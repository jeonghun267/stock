# -*- coding: utf-8 -*-
"""Create a truth-gated S06 decision-only production replay report."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from s06_release_contract_v1 import (
    CONDITION_ID,
    DURATION,
    EVIDENCE_FILES,
    EXPECTED_CONFIG,
    EXPECTED_RUNTIME_FLAGS,
    PRODUCTION_FILES,
    QUANTITY,
    REPORT_PATH,
    ROOT,
)

KST = ZoneInfo("Asia/Seoul")
EXPECTED_SCHEMA = "s06_exact_input_v2"
RECORD_DIR = ROOT / "data" / "s06_exact_replay"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        try:
            return abs(float(actual) - expected) <= 1e-9
        except (TypeError, ValueError):
            return False
    return actual == expected


def _input_contract_errors(records: list[dict[str, Any]], day: str) -> list[str]:
    errors: list[str] = []
    for index, record in enumerate(records):
        if record.get("schema") != EXPECTED_SCHEMA:
            errors.append(f"ROW_{index}:SCHEMA")
        if str(record.get("state_date") or "") != day:
            errors.append(f"ROW_{index}:TRADE_DATE")
        config = record.get("config") or {}
        for key, expected in EXPECTED_CONFIG.items():
            if not _same(config.get(key), expected):
                errors.append(f"ROW_{index}:CONFIG:{key}")
        flags = record.get("runtime_flags") or {}
        for key, expected in EXPECTED_RUNTIME_FLAGS.items():
            if str(flags.get(key) or "").upper() != expected:
                errors.append(f"ROW_{index}:FLAG:{key}")
        if len(errors) >= 50:
            break
    return errors


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(KST).strftime("%Y%m%d"))
    parser.add_argument("--report-out", default=str(REPORT_PATH))
    args = parser.parse_args()
    day = str(args.date)
    source = RECORD_DIR / f"s06_exact_input_{day}.jsonl"
    report_path = Path(args.report_out)

    for key, value in EXPECTED_RUNTIME_FLAGS.items():
        os.environ[key] = value
    from s06_exact_replay_v1 import load_records, replay_one

    records: list[dict[str, Any]] = []
    source_error = ""
    if not source.is_file():
        source_error = "NO_SAVED_INPUT"
    else:
        try:
            records = load_records(source, None)
        except Exception as exc:
            source_error = f"INPUT_READ:{type(exc).__name__}"
        if not records and not source_error:
            source_error = "EMPTY_INPUT"

    contract_errors = (
        _input_contract_errors(records, day) if records and not source_error else []
    )
    results: list[dict[str, Any]] = []
    if not source_error and not contract_errors:
        with tempfile.TemporaryDirectory(
            prefix="s06_auto_replay_", ignore_cleanup_errors=True
        ) as folder:
            for index, record in enumerate(records):
                workdir = Path(folder) / f"t{index:06d}"
                workdir.mkdir(parents=True, exist_ok=True)
                try:
                    results.append(replay_one(record, workdir))
                except Exception as exc:
                    results.append({
                        "code": record.get("code"),
                        "now_iso": record.get("now_iso"),
                        "match": False,
                        "diffs": [],
                        "error": f"REPLAY_HARNESS:{type(exc).__name__}:{exc}",
                    })

    matched = sum(1 for row in results if row.get("match") is True)
    decisions = sum(1 for row in results if row.get("entry_decision") is True)
    if source_error or contract_errors:
        status, provenance, exit_code = "BLOCKED", "[UNVERIFIED]", 3
    elif matched != len(records):
        status, provenance, exit_code = "FAIL", "[UNVERIFIED]", 1
    elif decisions < 1:
        status, provenance, exit_code = "BLOCKED", "[UNVERIFIED]", 3
    else:
        status, provenance, exit_code = "PASS", "[PROD_REPLAY]", 0

    report = {
        "schema": "s06_current_buy_prod_replay_v1",
        "provenance": provenance,
        "status": status,
        "performance_scope": "DECISION_ONLY",
        "strategy": "S06",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
        "date": day,
        "trade_date": day,
        "production_code_changed": "CHANGED",
        "production_entry_point": (
            "RUN/strategy_06_crash_low_chase_v1.py::"
            "Strategy06Engine._chase_tick"
        ),
        "condition": dict(EXPECTED_CONFIG),
        "runtime_flags": dict(EXPECTED_RUNTIME_FLAGS),
        "source_data": [str(source)],
        "source_sha256": ({str(source): _sha256(source)} if source.is_file() else {}),
        "replay_engine_sha256": _sha256(Path(__file__).resolve()),
        "production_sha256": {
            name: _sha256(path) for name, path in PRODUCTION_FILES.items()
        },
        "evidence_sha256": {
            name: _sha256(path) for name, path in EVIDENCE_FILES.items()
        },
        "scenario_count": len(records),
        "matched_count": matched,
        "entry_decision_count": decisions,
        "source_error": source_error,
        "contract_errors": contract_errors,
        "replay_failures": [
            row for row in results if row.get("match") is not True
        ][:50],
        "command": shlex.join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]),
    }
    _write_report(report_path, report)
    print(json.dumps({
        "provenance": provenance,
        "status": status,
        "report": str(report_path),
        "scenario_count": len(records),
        "matched_count": matched,
        "entry_decision_count": decisions,
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

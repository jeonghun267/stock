# -*- coding: utf-8 -*-
"""Fail-closed validation for a user-approved production replay report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hold_sell_audit_v1 import AuditError, sha256_file, sha256_files
from verified_hold_sell_replay_v1 import ENGINE_PATH, PROVENANCE, REPORT_SCHEMA


APPROVAL_SCHEMA = "verified_replay_approval_v1"


def validate_approval(
    path: Path,
    *,
    engine_path: Path | None = None,
) -> dict[str, Any]:
    approval_path = Path(path)
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"approval missing or invalid: {approval_path}: {exc}")
    if approval.get("schema") != APPROVAL_SCHEMA:
        raise AuditError("approval schema mismatch")
    if approval.get("approved_by_user") is not True:
        raise AuditError("explicit user approval missing")
    report_path = Path(str(approval.get("report_path") or ""))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"approved report missing or invalid: {exc}")
    if report.get("schema") != REPORT_SCHEMA:
        raise AuditError("report schema mismatch")
    if report.get("provenance") != PROVENANCE or report.get("status") != "PASS":
        raise AuditError("report is not a passing production replay")
    if approval.get("report_sha256") != sha256_file(report_path):
        raise AuditError("approved report hash mismatch")
    engine_paths = (
        [Path(engine_path)]
        if engine_path is not None
        else [
            Path(value)
            for value in (
                report.get("replay_engine_paths")
                or [report.get("replay_engine_path") or ENGINE_PATH]
            )
        ]
    )
    current_hash = sha256_files(engine_paths)
    if report.get("replay_engine_sha256") != current_hash:
        raise AuditError("production engine changed after replay")
    if approval.get("engine_sha256") != current_hash:
        raise AuditError("approval engine hash mismatch")
    return {
        "status": "PASS",
        "engine_sha256": current_hash,
        "report_path": str(report_path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_approval(args.approval)
    except AuditError as exc:
        print(json.dumps({
            "provenance": "[UNVERIFIED]",
            "status": "FAIL",
            "error": str(exc),
        }, ensure_ascii=False))
        return 2
    print(json.dumps({
        "provenance": "[PROD_REPLAY]",
        **result,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

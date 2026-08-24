# -*- coding: utf-8 -*-
"""Atomically promote S03 EARLY_LOW after approval of an exact replay hash."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))
from approval_manifest_writer_v1 import read_content_sha, update_manifest
from live_owner_approval_guard_v1 import verify_live_hashes

from s03_early_low_release_v1 import (
    CONDITION_ID,
    DURATION,
    FEATURE,
    MANIFEST,
    QUANTITY,
    ROOT,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_report(path: Path, approved_sha: str) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to((ROOT / "reports" / "verified_replay").resolve())
    actual_sha = _sha256(resolved)
    if actual_sha != approved_sha.lower():
        raise ValueError(
            f"REPORT_SHA_MISMATCH approved={approved_sha} actual={actual_sha}"
        )
    report = json.loads(resolved.read_text(encoding="utf-8"))
    exact = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS",
        "performance_scope": "DECISION_ONLY",
        "strategy": "S03",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
        "code_changed": "NOT_CHANGED",
    }
    for field, expected in exact.items():
        if report.get(field) != expected:
            raise ValueError(
                f"REPORT_FIELD_INVALID field={field} "
                f"got={report.get(field)!r} expected={expected!r}"
            )
    if int(report.get("candidate_pass_count") or 0) < 1:
        raise ValueError("REPORT_HAS_NO_PASSING_CANDIDATE")
    source_hashes = report.get("source_audit_hash")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise ValueError("REPORT_SOURCE_AUDIT_HASH_MISSING")
    for raw_path, expected in source_hashes.items():
        source = Path(str(raw_path)).resolve()
        source.relative_to(ROOT.resolve())
        if _sha256(source) != str(expected):
            raise ValueError(f"SOURCE_AUDIT_HASH_CHANGED:{source}")
    replay_hashes = report.get("replay_engine_hash")
    if not isinstance(replay_hashes, Mapping) or not replay_hashes:
        raise ValueError("REPORT_REPLAY_ENGINE_HASH_MISSING")
    for name, expected in replay_hashes.items():
        current = ROOT / "RUN" / str(name)
        if not current.is_file() or _sha256(current) != str(expected):
            raise ValueError(f"REPLAY_ENGINE_HASH_CHANGED:{name}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--approved-report-sha", required=True)
    args = parser.parse_args()
    report_path = Path(args.report)
    approved_sha = str(args.approved_report_sha).lower()
    report = _validate_report(report_path, approved_sha)
    hashes_ok, hash_errors = verify_live_hashes("S03")
    if not hashes_ok:
        raise ValueError(
            "LIVE_HASH_GATE_FAILED:" + "|".join(hash_errors))
    expected_manifest_sha = read_content_sha(MANIFEST)
    promoted_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def _mutate(data: dict[str, Any]) -> dict[str, Any]:
        releases = data.setdefault("release_states", {})
        current = releases.get(FEATURE)
        if not isinstance(current, Mapping):
            raise ValueError("RELEASE_STATE_MISSING")
        if str(current.get("condition_id") or "") != CONDITION_ID:
            raise ValueError("RELEASE_CONDITION_MISMATCH")
        releases[FEATURE] = {
            "status": "LIVE",
            "condition_id": CONDITION_ID,
            "quantity": QUANTITY,
            "duration": DURATION,
            "approved_report_path": str(report_path.resolve()),
            "approved_report_sha256": approved_sha,
            "trade_date": str(report.get("trade_date") or ""),
            "promoted_at": promoted_at,
        }
        data["approved_at"] = promoted_at
        data["approval_scope"] = (
            str(data.get("approval_scope") or "")
            + f" S03 EARLY_LOW atomic promotion: report_sha256={approved_sha}; "
              f"condition={CONDITION_ID}; quantity={QUANTITY}; duration={DURATION}."
        )
        return data

    new_sha = update_manifest(
        _mutate,
        updated_by="s03_early_low_atomic_promote_v1",
        expect_sha=expected_manifest_sha,
        path=MANIFEST,
    )
    print(
        f"S03_EARLY_LOW_ATOMIC_PROMOTION_PASS "
        f"report_sha256={approved_sha} manifest_sha={new_sha}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

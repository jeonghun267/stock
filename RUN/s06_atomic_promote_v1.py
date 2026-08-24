# -*- coding: utf-8 -*-
"""Fail-closed atomic S06 promotion after an exact current-path replay PASS."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from approval_manifest_writer_v1 import read_content_sha, read_manifest, update_manifest
from live_owner_approval_guard_v1 import verify_live_hashes
from s06_release_contract_v1 import (
    CONDITION_ID,
    DURATION,
    EVIDENCE_FILES,
    EXPECTED_CONFIG,
    EXPECTED_RUNTIME_FLAGS,
    FEATURE,
    MANIFEST,
    PRODUCTION_FILES,
    QUANTITY,
    REPORT_PATH,
    ROOT,
)
from trading_report_truth_gate_v1 import validate as truth_validate

KST = ZoneInfo("Asia/Seoul")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_report(path: Path) -> tuple[dict[str, Any], str]:
    resolved = path.resolve()
    if resolved != REPORT_PATH.resolve():
        raise ValueError("REPORT_PATH_NOT_APPROVED")
    resolved.relative_to((ROOT / "reports" / "verified_replay").resolve())
    report = json.loads(resolved.read_text(encoding="utf-8-sig"))
    truth_ok, truth_reason = truth_validate(report)
    if not truth_ok:
        raise ValueError(f"TRUTH_GATE_FAILED:{truth_reason}")
    exact = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS",
        "performance_scope": "DECISION_ONLY",
        "strategy": "S06",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
        "production_code_changed": "CHANGED",
        "condition": dict(EXPECTED_CONFIG),
        "runtime_flags": dict(EXPECTED_RUNTIME_FLAGS),
    }
    for field, expected in exact.items():
        if report.get(field) != expected:
            raise ValueError(f"REPORT_FIELD_INVALID:{field}")
    today = datetime.now(KST).strftime("%Y%m%d")
    if str(report.get("trade_date") or "") != today:
        raise ValueError("STALE_OR_FUTURE_TRADE_DATE")
    total = int(report.get("scenario_count") or 0)
    matched = int(report.get("matched_count") or 0)
    decisions = int(report.get("entry_decision_count") or 0)
    if total < 1 or matched != total or decisions < 1:
        raise ValueError("REPORT_DECISION_COVERAGE_INVALID")

    source_hashes = report.get("source_sha256")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise ValueError("SOURCE_HASH_MISSING")
    for raw_path, expected in source_hashes.items():
        source = Path(str(raw_path)).resolve()
        source.relative_to((ROOT / "data" / "s06_exact_replay").resolve())
        if not source.is_file() or _sha256(source) != str(expected):
            raise ValueError(f"SOURCE_HASH_CHANGED:{source}")

    production_hashes = report.get("production_sha256")
    if not isinstance(production_hashes, Mapping):
        raise ValueError("PRODUCTION_HASH_MISSING")
    for name, current in PRODUCTION_FILES.items():
        if _sha256(current) != str(production_hashes.get(name) or ""):
            raise ValueError(f"PRODUCTION_HASH_CHANGED:{name}")

    evidence_hashes = report.get("evidence_sha256")
    if not isinstance(evidence_hashes, Mapping):
        raise ValueError("EVIDENCE_HASH_MISSING")
    for name, current in EVIDENCE_FILES.items():
        if _sha256(current) != str(evidence_hashes.get(name) or ""):
            raise ValueError(f"EVIDENCE_HASH_CHANGED:{name}")
    if str(report.get("replay_engine_sha256") or "") != _sha256(
        EVIDENCE_FILES["RUN/s06_auto_replay_report_v1.py"]
    ):
        raise ValueError("REPLAY_ENGINE_HASH_CHANGED")
    return report, _sha256(resolved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT_PATH))
    args = parser.parse_args()
    report, report_sha = _validate_report(Path(args.report))
    manifest = read_manifest(MANIFEST)
    entries = manifest.get("strategies", {}).get("S06")
    if not isinstance(entries, list):
        raise ValueError("S06_MANIFEST_MISSING")
    by_path = {str(row.get("path") or ""): row for row in entries}

    for name, path in EVIDENCE_FILES.items():
        row = by_path.get(name)
        if not isinstance(row, Mapping):
            raise ValueError(f"EVIDENCE_NOT_PINNED:{name}")
        if str(row.get("sha256") or "") != _sha256(path):
            raise ValueError(f"EVIDENCE_MANIFEST_MISMATCH:{name}")
    for name in PRODUCTION_FILES:
        if name not in by_path:
            raise ValueError(f"PRODUCTION_NOT_PINNED:{name}")

    release = (manifest.get("release_states") or {}).get(FEATURE)
    if not isinstance(release, Mapping):
        raise ValueError("S06_RELEASE_STATE_MISSING")
    if str(release.get("condition_id") or "") != CONDITION_ID:
        raise ValueError("S06_RELEASE_CONDITION_MISMATCH")
    if (
        str(release.get("status") or "") == "LIVE"
        and verify_live_hashes("S06") == (True, [])
    ):
        print("S06_AUTO_PROMOTION_ALREADY_LIVE", flush=True)
        return 0

    expected_manifest_sha = read_content_sha(MANIFEST)
    promoted_at = datetime.now(KST).isoformat(timespec="seconds")
    production_hashes = report["production_sha256"]

    def _mutate(data: dict[str, Any]) -> dict[str, Any]:
        target_entries = data["strategies"]["S06"]
        target_by_path = {str(row.get("path") or ""): row for row in target_entries}
        for name in PRODUCTION_FILES:
            target_by_path[name]["sha256"] = str(production_hashes[name])
        data.setdefault("release_states", {})[FEATURE] = {
            "status": "LIVE",
            "condition_id": CONDITION_ID,
            "quantity": QUANTITY,
            "duration": DURATION,
            "approved_report_path": str(Path(args.report).resolve()),
            "approved_report_sha256": report_sha,
            "trade_date": str(report.get("trade_date") or ""),
            "promoted_at": promoted_at,
        }
        marker = f"S06 atomic promotion condition={CONDITION_ID}"
        scope = str(data.get("approval_scope") or "")
        if marker not in scope:
            data["approval_scope"] = (
                scope + f" {marker}; report_sha256={report_sha}; "
                f"quantity={QUANTITY}; duration={DURATION}."
            )
        data["approved_at"] = promoted_at
        return data

    new_sha = update_manifest(
        _mutate,
        updated_by="s06_atomic_promote_v1",
        expect_sha=expected_manifest_sha,
        path=MANIFEST,
    )
    hashes_ok, errors = verify_live_hashes("S06")
    if not hashes_ok:
        raise RuntimeError("POST_PROMOTION_HASH_FAILED:" + "|".join(errors))
    print(
        f"S06_ATOMIC_PROMOTION_PASS report_sha256={report_sha} "
        f"manifest_sha={new_sha}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

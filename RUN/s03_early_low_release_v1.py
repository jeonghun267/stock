# -*- coding: utf-8 -*-
"""Atomic release state for the Strategy 03 EARLY_LOW candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from approval_manifest_writer_v1 import content_sha

ROOT = Path(r"C:\stock_bot")
MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"
FEATURE = "S03_EARLY_LOW"
CONDITION_ID = "S03_EARLY_LOW_0900_0910_NEW_LOW_RESET_REBOUND_1P0_2P0_FLOW_TURN"
QUANTITY = 1
DURATION = "PERMANENT"
OWNER_OVERRIDE_STATUS = "LIVE_OWNER_OVERRIDE_UNVERIFIED"
OWNER_OVERRIDE_BASIS = "OWNER_DIRECT_OVERRIDE_AFTER_UNVERIFIED_REPLAY_20260825"


def verified_release_record(
    manifest_path: Path = MANIFEST,
) -> Mapping[str, Any] | None:
    """Return the release record only when the manifest and scope are exact."""
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if str(data.get("manifest_sha") or "") != content_sha(data):
        return None
    features = data.get("live_features")
    releases = data.get("release_states")
    record = releases.get(FEATURE) if isinstance(releases, Mapping) else None
    if not isinstance(features, Mapping) or features.get(FEATURE) is not True:
        return None
    if not isinstance(record, Mapping):
        return None
    if str(record.get("condition_id") or "") != CONDITION_ID:
        return None
    if int(record.get("quantity") or 0) != QUANTITY:
        return None
    if str(record.get("duration") or "") != DURATION:
        return None
    return record


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _owner_override_evidence_valid(
    record: Mapping[str, Any],
    manifest_path: Path,
) -> bool:
    if str(record.get("approval_basis") or "") != OWNER_OVERRIDE_BASIS:
        return False
    if str(record.get("evidence_status") or "") != "[UNVERIFIED]":
        return False
    if str(record.get("approved_by") or "") != "OWNER":
        return False
    expected_sha = str(record.get("evidence_report_sha256") or "").lower()
    if len(expected_sha) != 64 or any(
        ch not in "0123456789abcdef" for ch in expected_sha
    ):
        return False
    try:
        root = Path(manifest_path).resolve().parents[1]
        report_path = Path(
            str(record.get("evidence_report_path") or "")
        ).resolve()
        report_path.relative_to(
            (root / "reports" / "verified_replay").resolve()
        )
        if _sha256(report_path) != expected_sha:
            return False
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (
        OSError, ValueError, UnicodeError, json.JSONDecodeError, IndexError,
    ):
        return False
    exact = {
        "provenance": "[UNVERIFIED]",
        "status": "UNVERIFIED",
        "strategy": "S03",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
    }
    return all(
        report.get(field) == expected for field, expected in exact.items()
    )


def release_live_enabled(manifest_path: Path = MANIFEST) -> bool:
    """Accept either a PASS-bound release or an explicit hash-bound owner override."""
    record = verified_release_record(manifest_path)
    if record is None:
        return False
    status = str(record.get("status") or "")
    if status == "LIVE":
        report_sha = str(
            record.get("approved_report_sha256") or ""
        ).lower()
        return (
            len(report_sha) == 64
            and all(ch in "0123456789abcdef" for ch in report_sha)
        )
    if status == OWNER_OVERRIDE_STATUS:
        return _owner_override_evidence_valid(
            record, Path(manifest_path),
        )
    return False

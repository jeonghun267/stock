# -*- coding: utf-8 -*-
"""Atomic release state for the Strategy 03 EARLY_LOW candidate."""
from __future__ import annotations

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


def release_live_enabled(manifest_path: Path = MANIFEST) -> bool:
    """Fail closed unless an approved, report-bound atomic release is LIVE."""
    record = verified_release_record(manifest_path)
    if record is None or str(record.get("status") or "") != "LIVE":
        return False
    report_sha = str(record.get("approved_report_sha256") or "").lower()
    return len(report_sha) == 64 and all(ch in "0123456789abcdef" for ch in report_sha)

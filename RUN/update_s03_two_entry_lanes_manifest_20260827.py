# -*- coding: utf-8 -*-
"""Seal the permanent S03 two-entry-lane runtime."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest


ROOT = Path("C:/stock_bot")
PATHS = (
    "RUN/골짜기_급반등.py",
    "RUN/strategy_03_signal_contract_v1.py",
    "RUN/hidden/SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd",
)
EXPECTED_OLD = {
    "RUN/골짜기_급반등.py":
        "1539f7390d9989bfdb9429985591d0dcf41b863899b1b9dc277e5b0f3b40d5c7",
    "RUN/strategy_03_signal_contract_v1.py":
        "2b7defde5c575dc03398f2383f5815d66e559e930188aaf1cf43ebf31c8bb1f3",
    "RUN/hidden/SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd":
        "c27611c64c3b9355a07bab0bc3378828239a5ffe5a3371c7b3076fbc5e12b181",
}
HASHES = {
    rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    for rel in PATHS
}
REPORT = (
    ROOT / "data" / "s03_two_lane_replay" / "20260827_133754"
    / "prod_replay_s03_two_entry_lanes_20260827.json"
)
REPORT_SHA = hashlib.sha256(REPORT.read_bytes()).hexdigest()
REPLAY = json.loads(REPORT.read_text(encoding="utf-8-sig"))

if REPLAY.get("provenance") != "[PROD_REPLAY]" or REPLAY.get("status") != "PASS":
    raise SystemExit("S03 two-lane replay did not pass")
for rel in PATHS:
    if REPLAY.get("sha256", {}).get(str(ROOT / rel)) != HASHES[rel]:
        raise SystemExit(f"replay hash mismatch: {rel}")

NOTE = (
    "2026-08-27 owner-approved permanent S03 entry cleanup: only OPEN_CRASH "
    "(staircase decline) and INTRADAY_CRASH (crash rebound) are active. "
    "EARLY_LOW is rejected by the production contract, removed from signal "
    "restore/output/audit, and its post-run replay launcher was removed. "
    "Historical EARLY_LOW positions retain sell compatibility. Quantity, slots, "
    "sell rules, hard stops, and forced exits are unchanged. Current-path "
    "[PROD_REPLAY] PASS report_sha256=" + REPORT_SHA + "."
)


def _walk_entries(node):
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        else:
            for value in node.values():
                yield from _walk_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_entries(value)


def mutate(data):
    updated = set()
    for entry in _walk_entries(data):
        rel = entry["path"]
        if rel not in HASHES:
            continue
        if entry["sha256"] != EXPECTED_OLD[rel]:
            raise SystemExit(f"unexpected current hash: {rel} {entry['sha256']}")
        entry["sha256"] = HASHES[rel]
        updated.add(rel)
    missing = set(PATHS) - updated
    if missing:
        raise SystemExit(f"manifest entry missing: {sorted(missing)}")

    features = data.get("live_features")
    if not isinstance(features, dict):
        raise SystemExit("live_features missing")
    features["S03_EARLY_LOW"] = False
    release = (data.get("release_states") or {}).get("S03_EARLY_LOW")
    if not isinstance(release, dict):
        raise SystemExit("S03_EARLY_LOW release state missing")
    release["status"] = "REVOKED"
    release["revoked_at"] = "2026-08-27"
    release["revoked_reason"] = "OWNER_TWO_ENTRY_LANES_ONLY"

    numbers = [
        int(n)
        for n in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))
    ]
    nxt = (max(numbers) + 1) if numbers else 1
    data["approval_scope"] += f" ({nxt}) {NOTE}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s03_two_entry_lanes_20260827",
        expect_sha=read_content_sha(),
    ))

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


EXPECTED_SHA = "713b1a5bb691f3431ccb6e22386b0543fcccc719d8237338ab51787e5fddf929"
HASHES = {
    "RUN/hidden/SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd": "0040aa3130ace1508bd13fb80e8919ba7413bf52d710763daac500ee1244f157",
    "RUN/골짜기_급반등.py": "a0aad3a7717a1d94ca14cd71a5c663278d52d7bc5a13d43c42bb263a37b0d206",
    "RUN/strategy_03_rotation_engine_v1.py": "c3649dfebadbbeb5604d4bd8b9110b0339b18526569c8780fb142bd2c9886724",
    "RUN/strategy_03_flow_turn_fast_v1.py": "3b0793c9b932e35b20a5d7a9ebe2c57232041d762e453aaf5c9e3d5bf7c6b855",
}


def mutate(data):
    entries = data["strategies"]["S03"]
    by_path = {entry["path"]: entry for entry in entries}
    for path, digest in HASHES.items():
        if path in by_path:
            by_path[path]["sha256"] = digest
        else:
            entries.append({"path": path, "sha256": digest})
    data.setdefault("live_features", {})["S03_FLOW_TURN_FAST"] = True
    data["approval_scope"] += (
        " (28) 2026-08-20 S03 BOTTOM_CONFIRM dormant all-lane enforcement path is "
        "hash-covered behind the absent S03_BOTTOM_CONFIRM_ALL_LANES live feature and env. "
        "Exact-input capture is active; existing EARLY_LOW one-share live behavior remains "
        "unchanged until the all-lane current-path PROD_REPLAY passes."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s03_flow_turn_prep_20260820",
        expect_sha=EXPECTED_SHA,
    ))

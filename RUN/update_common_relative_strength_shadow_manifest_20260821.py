# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


EXPECTED_SHA = "370b870312f8ec92e2c466b113f6b99eff2f83c9378e3c2f4961afe3c89b50d2"
COMMON_PATH = "RUN/strategy_common_relative_strength_rebound_v1.py"
COMMON_SHA = "89f0cee0b2059a74cbdc0ac56cd62afe710f895c6d0b76c49fe9bb65273cd34a"
STRATEGY_HASHES = {
    "S02": {
        "RUN/strategy_02_low_buy_signal_v1.py":
            "c6c9bf3c3e64359042cc07278687faf606853d0e6f62fe1b70bb0d2b64f4a1fd",
    },
    "S03": {
        "RUN/골짜기_급반등.py":
            "0ed4fdb4292608c0d06a80a89bf2c1a1c160379a78b203bb5b1252ef1a8e4c86",
    },
}


def mutate(data):
    for strategy, hashes in STRATEGY_HASHES.items():
        entries = data["strategies"][strategy]
        by_path = {entry["path"]: entry for entry in entries}
        for path, digest in hashes.items():
            by_path[path]["sha256"] = digest
        if COMMON_PATH not in by_path:
            entries.append({"path": COMMON_PATH, "sha256": COMMON_SHA})
        else:
            by_path[COMMON_PATH]["sha256"] = COMMON_SHA
    data["approval_scope"] += (
        " (31) 2026-08-21 owner-approved S02/S03 common crash relative-strength "
        "rebound evaluator is hash-covered in permanent SHADOW_ORDER_ZERO mode. "
        "It only appends crs_* candidate telemetry; live eligibility is hard-coded "
        "false and existing entry, regime-stop, quantity, broker, and launcher "
        "behavior remain unchanged."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_common_rs_shadow_20260821",
        expect_sha=EXPECTED_SHA,
    ))

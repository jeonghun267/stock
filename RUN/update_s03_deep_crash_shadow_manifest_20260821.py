# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


EXPECTED_SHA = "631b0ed3ff91761219eaaea54abbd2a4d7883bfa202c8fd96167308ca8ca897c"
COMMON_PATH = "RUN/strategy_common_relative_strength_rebound_v1.py"
COMMON_SHA = "95a187bcfc72afa4e2a25445f39c3286db0e293f8085de1c3e69bff4cdc8871b"
S03_PATH = "RUN/골짜기_급반등.py"
S03_SHA = "35d48a1193a83c0abd60b0807afba6a25bea1ba028c12ef6cef4ac43fa8720a7"


def mutate(data):
    for strategy in ("S02", "S03"):
        entries = data["strategies"][strategy]
        by_path = {entry["path"]: entry for entry in entries}
        by_path[COMMON_PATH]["sha256"] = COMMON_SHA
        if strategy == "S03":
            by_path[S03_PATH]["sha256"] = S03_SHA
    data["approval_scope"] += (
        " (32) 2026-08-21 owner-approved S03 deep-crash rebound experiment is "
        "hash-covered in SHADOW_ORDER_ZERO mode only: 09:00-09:15, observed low "
        "at or below -10%, 60-second low stability, 1-2% rebound, flow/book "
        "confirmation, and VI-suspect block. Existing regime stop, order names, "
        "quantity, live entry, exits, broker, and launchers remain unchanged."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s03_deep_crash_shadow_20260821",
        expect_sha=EXPECTED_SHA,
    ))

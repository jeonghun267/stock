# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


EXPECTED_SHA = "7d21dad490cdb0be48d1f08b7a2d9ba3d6a191822592c24b23ba7c58a20ffec9"
HASHES = {
    "RUN/strategy_common_relative_strength_rebound_v1.py":
        "a175de5159222c8c11ac011f4b09402f0ef16590035b1deb06202059f298c433",
    "RUN/strategy_03_deep_crash_shadow_ledger_v1.py":
        "5ed7a57da4c88ad3d3965502382d7340b2c746b7a3fa723181f281a1b6c9cea3",
    "RUN/골짜기_급반등.py":
        "5664907f3d2a6fd7eefbbea43a3e6627e62d4deca2a6edd1d758658497c39a49",
}


def mutate(data):
    for strategy in ("S02", "S03"):
        entries = data["strategies"][strategy]
        by_path = {entry["path"]: entry for entry in entries}
        common_path = "RUN/strategy_common_relative_strength_rebound_v1.py"
        by_path[common_path]["sha256"] = HASHES[common_path]
        if strategy == "S03":
            for path in (
                "RUN/strategy_03_deep_crash_shadow_ledger_v1.py",
                "RUN/골짜기_급반등.py",
            ):
                if path in by_path:
                    by_path[path]["sha256"] = HASHES[path]
                else:
                    entries.append({"path": path, "sha256": HASHES[path]})
    data["approval_scope"] += (
        " (33) 2026-08-21 owner-approved S03 deep-crash shadow result ledger "
        "persists first candidate evidence and tracks post-candidate high, low, "
        "last price, favorable/adverse movement through the unchanged 14:31 signal "
        "cutoff. It remains order-zero; live entry, regime stop, quantity, exits, "
        "broker, launcher, and process end time are unchanged."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s03_deep_crash_ledger_20260821",
        expect_sha=EXPECTED_SHA,
    ))

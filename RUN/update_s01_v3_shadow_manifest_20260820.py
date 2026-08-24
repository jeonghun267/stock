# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


ROOT = Path(r"C:\stock_bot")
EXPECTED_SHA = "e3b42409a8aaa568962aa7d89e6b8571fc68fc842da11e2773d5e327d82d8c78"
PATHS = (
    "RUN/strategy_01_open_surge_signal_v2.py",
    "RUN/strategy_01_signal_contract_v2.py",
    "RUN/hidden/SAFEPLUS_STRATEGY01_SIGNAL.cmd",
    "RUN/hidden/SAFEPLUS_STRATEGY01_LIVE.cmd",
    "RUN/strategy_01_entry_runtime_v3.py",
    "RUN/strategy_01_entry_policy_v3.py",
    "RUN/strategy_01_volume_baseline_v3.py",
)


def digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def mutate(data):
    entries = data["strategies"]["S01"]
    by_path = {entry["path"]: entry for entry in entries}
    for relative in PATHS:
        if relative not in by_path:
            entry = {"path": relative, "sha256": digest(relative)}
            entries.append(entry)
            by_path[relative] = entry
        else:
            by_path[relative]["sha256"] = digest(relative)
    marker = "(30) 2026-08-20 owner-approved S01 v3 SHADOW hash coverage"
    if marker not in data["approval_scope"]:
        data["approval_scope"] += (
            " (30) 2026-08-20 owner-approved S01 v3 SHADOW hash coverage: "
            "ROCKET/PULLBACK/ORB policy, runtime adapter, relative-volume baseline "
            "builder, exact-input capture, signal contract, and both S01 launchers "
            "are hash-covered. S01_ENTRY_V3_MODE remains SHADOW/order-zero and "
            "S01_TREND_PRIORITY_MODE is restored to SHADOW because current-path "
            "PROD_REPLAY has not passed. Existing orders, quantity, sell rules, "
            "and the previously approved dated ABOVE_OPEN lane are unchanged."
        )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s01_v3_shadow_20260820",
        expect_sha=EXPECTED_SHA,
    ))

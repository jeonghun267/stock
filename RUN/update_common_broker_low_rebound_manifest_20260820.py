# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import update_manifest


ROOT = Path(r"C:\stock_bot")
EXPECTED_SHA = "3b348a8e8cdec34093352ae5bf01758cad1bb9be2e81e9b21e27b09a23323774"
PATHS = (
    "RUN/broker_gateway_v1.py",
    "RUN/low_rebound_common_v1.py",
)


def digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def mutate(data):
    entries = data["common"]
    by_path = {entry["path"]: entry for entry in entries}
    for relative in PATHS:
        by_path[relative]["sha256"] = digest(relative)
    marker = "(31) 2026-08-20 owner-approved broker auction capture and low-rebound boundary repair"
    if marker not in data["approval_scope"]:
        data["approval_scope"] += (
            " (31) 2026-08-20 owner-approved broker auction capture and low-rebound boundary repair: "
            "the broker adds read-only expected auction price/quantity FIDs 23/24 and preserves them "
            "for S01 v3 ROCKET shadow inputs; no order call or broker lifecycle change. The shared "
            "DIRECT_REBOUND comparison adds epsilon 1e-9 only at the exact rebound floor and chase-cap "
            "boundaries for S02/S06; all configured thresholds, quantities, sell rules, and other "
            "strategy logic remain unchanged. Focused low-rebound tests passed 12/12."
        )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_common_boundary_auction_20260820",
        expect_sha=EXPECTED_SHA,
    ))

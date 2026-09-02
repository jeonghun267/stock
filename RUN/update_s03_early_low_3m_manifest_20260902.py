# -*- coding: utf-8 -*-
"""Owner-approved S03 EARLY_LOW v2 production hash update."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from approval_manifest_writer_v1 import read_content_sha, update_manifest
from s03_early_low_release_v1 import CONDITION_ID, DURATION, FEATURE, QUANTITY

MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"
CHANGED_PRODUCTION_PATHS = frozenset({
    "RUN/골짜기_급반등.py",
    "RUN/strategy_03_signal_contract_v1.py",
    "RUN/strategy_03_rotation_engine_v1.py",
    "RUN/s03_early_low_release_v1.py",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    expected = read_content_sha(MANIFEST)

    def mutate(data: dict) -> dict:
        rows = data["strategies"]["S03"]
        found = set()
        for row in rows:
            path = str(row.get("path") or "").replace("\\", "/")
            if path in CHANGED_PRODUCTION_PATHS:
                row["sha256"] = sha256(ROOT / path)
                found.add(path)
        missing = CHANGED_PRODUCTION_PATHS - found
        if missing:
            raise ValueError("S03_MANIFEST_PATH_MISSING:" + ",".join(sorted(missing)))
        data.setdefault("live_features", {})[FEATURE] = True
        data.setdefault("release_states", {})[FEATURE] = {
            "status": "PENDING_PROD_REPLAY_PROMOTION",
            "condition_id": CONDITION_ID,
            "quantity": QUANTITY,
            "duration": DURATION,
            "approved_report_path": "",
            "approved_report_sha256": "",
            "trade_date": "20260902",
        }
        data["approval_scope"] = (
            str(data.get("approval_scope") or "")
            + " Owner 2026-09-02 S03 EARLY_LOW only: rolling 3m drop -3%; "
              "new-low 60s reset; 2s stable; rebound 0.5~1.5%; two up ticks; "
              "quantity 1; permanent; restart required."
        )
        return data

    value = update_manifest(
        mutate,
        updated_by="update_s03_early_low_3m_manifest_20260902",
        expect_sha=expected,
        path=MANIFEST,
    )
    print("S03_EARLY_LOW_3M_MANIFEST_PENDING", value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

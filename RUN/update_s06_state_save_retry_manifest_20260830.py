from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

TARGET = "RUN/strategy_06_crash_low_chase_v1.py"
DIGEST = hashlib.sha256((ROOT / TARGET).read_bytes()).hexdigest()

def mutate(data):
    found = False
    for entry in data.get("strategies", {}).get("S06", []):
        if entry.get("path") == TARGET:
            entry["sha256"] = DIGEST
            found = True
    if not found:
        raise RuntimeError(f"manifest entry missing: {TARGET}")
    data["approval_scope"] = (
        str(data.get("approval_scope") or "")
        + " (S06 state-save reliability 2026-08-30: unique per-write temp, "
        "bounded Windows replace retry, fail-closed preserved; trading "
        "conditions, quantity, slots and launchers unchanged.)"
    )
    return data

if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="codex_s06_state_save_reliability_20260830",
        expect_sha=read_content_sha(),
    ))
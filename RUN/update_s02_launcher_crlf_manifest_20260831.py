from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

TARGETS = (
    "RUN/hidden/SAFEPLUS_STRATEGY02_SIGNAL.cmd",
    "RUN/hidden/SAFEPLUS_STRATEGY02_LIVE.cmd",
)
DIGESTS = {
    target: hashlib.sha256((ROOT / target).read_bytes()).hexdigest()
    for target in TARGETS
}


def mutate(data):
    """S02 칸의 런처 두 개만 갱신한다. 다른 전략 칸은 건드리지 않는다."""
    found = 0
    for entry in data.get("strategies", {}).get("S02", []):
        digest = DIGESTS.get(entry.get("path"))
        if digest:
            entry["sha256"] = digest
            found += 1
    if found != len(TARGETS):
        raise RuntimeError(
            f"manifest entry count mismatch: {found} (expected {len(TARGETS)})")
    data["approval_scope"] = (
        str(data.get("approval_scope") or "")
        + " (S02 adaptive-bottom rollback 2026-08-31, owner directed: "
        "SIGNAL cmd sets S02_ADAPTIVE_BOTTOM_ENABLED=NO, restoring the code "
        "default and the pre-2026-08-20 direct-rebound behaviour that had "
        "blocked every DIRECT_REBOUND buy outside a STRONG regime; LIVE cmd "
        "adds S02_PEAK_SCORE=2, returning the S02 exit engine instance to the "
        "pre-2026-08-19 peak score. Line endings normalised to CRLF in the "
        "same pass. Day-low 2pct cap, 0.25pct arrival collar and the regime "
        "stop are deliberately left unchanged; no other strategy is touched.)"
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s02_adaptive_rollback_20260831",
        expect_sha=read_content_sha(),
    ))

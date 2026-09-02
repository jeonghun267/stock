from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

TARGET = "RUN/s03_s06_crash_claim_v1.py"
DIGEST = hashlib.sha256((ROOT / TARGET).read_bytes()).hexdigest()


def mutate(data):
    """S03·S06 두 칸에 같은 파일이 등재되어 있어 양쪽 해시를 함께 맞춘다.

    같은 파일의 같은 sha256 이므로 이웃 칸의 '다른 파일'은 건드리지 않는다.
    """
    found = 0
    for strategy in ("S03", "S06"):
        for entry in data.get("strategies", {}).get(strategy, []):
            if entry.get("path") == TARGET:
                entry["sha256"] = DIGEST
                found += 1
    if found != 2:
        raise RuntimeError(
            f"manifest entry count mismatch for {TARGET}: {found} (expected 2)")
    data["approval_scope"] = (
        str(data.get("approval_scope") or "")
        + " (S06 crash-claim timezone fix 2026-08-31: _expire aligned the "
        "persisted naive expires_ts with the timezone-aware KST clock that "
        "S06 supplies, which raised TypeError and killed the S06 engine at "
        "09:01 on 20260831. Comparison only; claim rules, priority window, "
        "trading conditions, quantity, slots and launchers unchanged.)"
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s06_claim_tz_normalize_20260831",
        expect_sha=read_content_sha(),
    ))

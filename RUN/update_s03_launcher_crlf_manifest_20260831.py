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
    "RUN/hidden/SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd",
    "RUN/hidden/SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd",
)
DIGESTS = {
    target: hashlib.sha256((ROOT / target).read_bytes()).hexdigest()
    for target in TARGETS
}


def mutate(data):
    """S03 칸의 런처 두 개만 줄끝 수리 후 해시로 맞춘다.

    다른 전략 칸과 S03 칸의 다른 파일은 건드리지 않는다.
    """
    found = 0
    for entry in data.get("strategies", {}).get("S03", []):
        digest = DIGESTS.get(entry.get("path"))
        if digest:
            entry["sha256"] = digest
            found += 1
    if found != len(TARGETS):
        raise RuntimeError(
            f"manifest entry count mismatch: {found} (expected {len(TARGETS)})")
    data["approval_scope"] = (
        str(data.get("approval_scope") or "")
        + " (S03 launcher line-ending repair 2026-08-31: the 8/30 edit left "
        "bare LF on 2 lines of STRATEGY03_LIVE_ASCII.cmd and 3 lines of "
        "STRATEGY03_SIGNAL_ASCII.cmd, including 'if %ERRORLEVEL% EQU 0 exit "
        "/b 0'. cmd.exe mis-parsed the launcher, so python never started and "
        "the restart counter stayed at 0/3. Line endings only - every command, "
        "environment variable, threshold and trading condition byte-identical.)"
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s03_launcher_crlf_repair_20260831",
        expect_sha=read_content_sha(),
    ))

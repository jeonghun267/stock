# -*- coding: utf-8 -*-
"""2026-08-27 밤 재봉인: S02 신호기 잠금 실패 사유 로그 1줄(조용사 진단).

친구님 지시("할 수 있는 건 해")로 8/27 09:41 조용사의 남은 절반을 고쳤다.
잠금을 못 잡으면 종전에는 아무 말 없이 종료해 "프로세스는 사는데 산출물 0"으로만
보였다. 종료코드 0 은 그대로 두고(태스크 판정 불변) stderr 에 사유만 남긴다.

검증[실측]: 컴파일 OK · 잠금 점유 재현 3/3(사유 로그 남김·종료코드 0·배타성 유지).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

ROOT = Path(r"C:\stock_bot")
PATHS = ("RUN/strategy_02_low_buy_signal_v1.py",)
HASHES = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS}


def _walk_entries(node):
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        else:
            for value in node.values():
                yield from _walk_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_entries(value)


def mutate(data):
    updated = set()
    for entry in _walk_entries(data):
        digest = HASHES.get(entry["path"])
        if digest:
            entry["sha256"] = digest
            updated.add(entry["path"])
    missing = set(PATHS) - updated
    if missing:
        raise SystemExit(f"manifest entry missing: {sorted(missing)}")
    numbers = [int(n) for n in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))]
    nxt = (max(numbers) + 1) if numbers else 1
    data["approval_scope"] += (
        f" ({nxt}) 2026-08-27 owner approval: the S02 signal now prints "
        "S02_SIGNAL_SINGLETON_LOCK_BUSY to stderr when it cannot take the "
        "singleton lock, instead of exiting silently. Exit code stays 0 so task "
        "scheduling is unchanged; no trading logic touched. This closes the "
        "diagnosis half of the 2026-08-27 09:41 silent death. Compiled; lock "
        "contention replay 3/3 pass."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s02_lock_busy_log_20260827",
        expect_sha=read_content_sha(),
    ))

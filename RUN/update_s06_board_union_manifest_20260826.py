# -*- coding: utf-8 -*-
"""2026-08-26 친구님 확정 재봉인: S06 유니버스 = 고저폭 계열 U 던짐/매도세 (합집합).

승인 경위: GPT 최초 배선은 교집합(8/26 실측 고저폭판*급락 겹침 1종목 — 과소).
Claude 검토 -> GPT 동의 -> 친구님 "직접 배선하는 거다. 너가 말한 대로 합집합".
교집합 매수 관문과 그림자 검증은 검토 후 채택하지 않음(친구님 결정).
대상: RUN/strategy_06_crash_low_chase_v1.py (chase_cap 기본값 2.5 반영 포함)
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

ROOT = Path(r"C:\stock_bot")
PATHS = ("RUN/strategy_06_crash_low_chase_v1.py",)
HASHES = {
    rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS
}


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
        f" ({nxt}) 2026-08-26 owner approval: S06 BOARD universe = high-range family "
        "UNION money-flow dump board (red-dump/blue-sellwave), duplicates collapse "
        "naturally via set union; buy conditions unchanged. Initial intersection "
        "wiring discarded (measured overlap 1 stock on 2026-08-26). chase_cap code "
        "default 2.5 matches the 10:15 live change."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s06_board_union_20260826",
        expect_sha=read_content_sha(),
    ))

# -*- coding: utf-8 -*-
"""2026-08-26 친구님 승인 재봉인: S03 후보군 복구(고저폭판 U 돈흐름판) 2개 파일.

승인 문구: "전략3 후보군을 고저폭판 U 돈흐름판(던짐/매도세)으로 상시 실전 복구 승인"
+ "3번 전레인이 같이 봐야 돼".
대상: RUN/골짜기_급반등.py (후보군 복구, 3레인 공통 유니버스)
      RUN/strategy_03_flow_turn_fast_v1.py (seller_exhaustion order-zero 추가, 미배선)
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

ROOT = Path(r"C:\stock_bot")
PATHS = (
    "RUN/골짜기_급반등.py",
    "RUN/strategy_03_flow_turn_fast_v1.py",
)


def _sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


HASHES = {rel: _sha(rel) for rel in PATHS}


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
        f" ({nxt}) 2026-08-26 owner approval: S03 candidate universe restored to "
        "high-range board UNION money-flow dump board (red-dump/blue-sellwave), "
        "applied to all three S03 lanes permanently (golljjagi board universe restore). "
        "strategy_03_flow_turn_fast_v1 reseal covers the unwired order-zero "
        "seller_exhaustion_fast experiment added the same day."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s03_board_universe_restore_20260826",
        expect_sha=read_content_sha(),
    ))

# -*- coding: utf-8 -*-
"""2026-08-27 장중 친구님 지시 재봉인: S03 급행 폐지 + S06 인계 잔재 제거.

지시 원문: "급행도 꺼 두개만 남겨" / "2번으로 해 급행 끄고 822행도 없애" /
"express_deep 무장 조건 유지해" / "3번에는 급락 급반등과 계단 저점 2개 있어야 돼.
6번에 공급하는 것은 있으면 안 돼".

수정 3파일의 해시를 재봉인한다. 지시서: 보고서\지시서_S03_급행제거_20260827.md
(지시서의 2파일 외에 rotation_engine의 주문시점 -8% 하한 재검산이 실측으로 추가 발견돼
함께 수정 — 안 고치면 깊은 신호가 계약 통과 후 주문에서 조용히 버려진다.)
검증: py_compile 3/3 · pytest strategy_03+s03_express 65 passed(기준선 61, 실패 0→0).
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
    "RUN/strategy_03_signal_contract_v1.py",
    "RUN/strategy_03_rotation_engine_v1.py",
)
HASHES = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS}

NOTE = (
    "2026-08-27 owner order \"remove the express lane, keep two\": S03 EXPRESS "
    "instant-buy path removed from detector, contract checker and order-time recheck; "
    "staircase (OPEN_CRASH) now covers below -8 percent (DEEP_ZONE_EXPRESS_ONLY and "
    "OPEN_HANDOFF_DROP_PCT lower bounds removed at all three gates). deep_arm (day-high "
    "-7 percent arming) kept per explicit owner order. S06 handoff remnants "
    "(handoff_to_s06 flag, restore path, config field) deleted per owner order. "
    "Sell rules, INTRADAY_CRASH lane, quantities, slots unchanged. Tests: 65 passed "
    "(baseline 61, failures 0 before and after)."
)


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
    data["approval_scope"] += f" ({nxt}) {NOTE}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s03_express_removal_20260827",
        expect_sha=read_content_sha(),
    ))

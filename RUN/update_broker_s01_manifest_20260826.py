# -*- coding: utf-8 -*-
"""2026-08-26 밤 재봉인: broker_gateway 계좌응답 재시도 + S01 로켓 진단 기록.

경위: 8/26 10:33 네이처셀 유령 체결(빈 ACCNO 응답 -> BUY_REJECTED 오판, 주문은
실제 체결)의 근본 수리(재시도 + IPC 중복처리 가드)와, S01 ROCKET 미발동 사유
진단 기록(행동 변화 없음). Claude가 diff 검토 + 컴파일 + 테스트 18/18 확인 후
친구님 지시("지금 해결하면 되잖아")로 봉인.
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
    "RUN/broker_gateway_v1.py",
    "RUN/strategy_01_open_surge_signal_v2.py",
)
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
        f" ({nxt}) 2026-08-26 owner approval: broker_gateway retries transient "
        "blank ACCNO login responses (3x200ms, Qt-safe wait; OCX errors still "
        "fail closed) and guards duplicate IPC request processing — root fix for "
        "the 2026-08-26 10:33 ghost fill (BUY_REJECTED misjudgment on a filled "
        "order). strategy_01 adds ROCKET_NOT_ELIGIBLE diagnostics only, no "
        "behavior change. Reviewed, compiled, tests 18/18."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_broker_s01_reseal_20260826",
        expect_sha=read_content_sha(),
    ))

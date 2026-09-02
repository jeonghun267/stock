# -*- coding: utf-8 -*-
"""2026-08-27 아침 재봉인: 친구님 지시 "다 켜야 돼 - 전략들은 다 사야 되니까".

S01_ENTRY_V3_MODE=LIVE 를 S01 런처 2개(LIVE/SIGNAL)에 추가한 뒤의 해시 재봉인.
사전 경고 후 친구님이 재확인한 지시라 그대로 집행한다.
경고 내용: v3 LIVE 는 신호 소스를 entry_v3_signals 로 통째 교체하므로
ROCKET 뿐 아니라 PULLBACK/ORB 도 주문 가능해지고, 레거시 STRONG_FLOW 레인은 멈춘다.
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
    "RUN/hidden/SAFEPLUS_STRATEGY01_LIVE.cmd",
    "RUN/hidden/SAFEPLUS_STRATEGY01_SIGNAL.cmd",
)
HASHES = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS}

NOTE = (
    "2026-08-27 owner order \"open every buy path\": S01_ENTRY_V3_MODE=LIVE added to "
    "both S01 launchers. This switches the S01 live signal source from legacy signals "
    "to entry_v3_signals, so ROCKET, PULLBACK and ORB v3 lanes all become order-capable "
    "and the legacy STRONG_FLOW lane stops feeding orders. The owner was explicitly told "
    "this conflicts with the 2026-08-20 \"remain SHADOW until PROD_REPLAY passes\" clause "
    "and the 2026-08-25 \"PULLBACK and ORB remain SHADOW_ORDER_ZERO\" clause, and "
    "reaffirmed the order. Quantity, slots, capital, sells, hard stop, forced exit and "
    "broker behavior are unchanged. Evidence is [UNVERIFIED]."
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
        updated_by="claude_s01_entry_v3_live_20260827",
        expect_sha=read_content_sha(),
    ))

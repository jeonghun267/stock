# -*- coding: utf-8 -*-
"""2026-08-28 S01 v3 실전 연결 재봉인 — 재생 PASS 후에만 실행할 것.

친구님 조건부 사전승인(8/27 저녁, 8/13 선례): "재생 PASS하면 바로 연결해".
전제(집행자가 먼저 확인):
  1) python RUN\s01_entry_v3_prod_replay_v1.py --date 20260828 → status=PASS
  2) 런처 2개에 S01_ENTRY_V3_MODE=LIVE 추가 완료(이 스크립트는 편집 후 해시만 봉인)
승인 내용: ROCKET 3슬롯·PULLBACK 3슬롯·총 6슬롯·종목당 1주·상시(만료 없음).
레거시 STRONG_FLOW 정지(신호 소스 교체) 고지·승인됨.
집행 지시서: 보고서\지시서_S01_v3실전연결_20260828.md
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

NOTE = (
    "2026-08-28 conditional pre-approval executed (owner, 2026-08-27 evening, "
    "\"connect immediately when the replay passes\", 8/13 precedent): "
    "S01_ENTRY_V3_MODE=LIVE added to both S01 launchers after "
    "s01_entry_v3_prod_replay_v1 --date 20260828 returned PASS with current "
    "production hashes. Permanent (no expiry): ROCKET 3 slots, PULLBACK 3 slots, "
    "6 total, one share per code (common SSOT). Legacy STRONG_FLOW lane stops "
    "(signal source switches to entry_v3). Hard stops, force exit, shadow "
    "comparison and audit recording remain enabled."
)


def _require_live_line(rel: str) -> None:
    data = (ROOT / rel).read_bytes()
    if b"set S01_ENTRY_V3_MODE=LIVE" not in data:
        raise SystemExit(f"precondition failed: {rel} lacks S01_ENTRY_V3_MODE=LIVE")
    if data.count(b"\r") != data.count(b"\n"):
        raise SystemExit(f"precondition failed: {rel} CRLF broken")
    if any(b >= 0x80 for b in data):
        raise SystemExit(f"precondition failed: {rel} non-ASCII byte")


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
    hashes = {
        rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS
    }
    updated = set()
    for entry in _walk_entries(data):
        digest = hashes.get(entry["path"])
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
    for rel in PATHS:
        _require_live_line(rel)
    print(update_manifest(
        mutate,
        updated_by="claude_s01_v3_live_20260828",
        expect_sha=read_content_sha(),
    ))

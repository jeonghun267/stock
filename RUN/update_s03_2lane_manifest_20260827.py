# -*- coding: utf-8 -*-
"""2026-08-27 장중 친구님 지시 재봉인: S03 2레인 체제 완성.

지시서: 보고서\지시서_S03_2레인체제_20260827.md (급행 제거분은 같은 날 오전에
update_s03_express_removal_manifest_20260827.py 로 이미 봉인됨 — 이 스크립트는 차액분).

차액 3건:
- 골짜기_급반등.py: EARLY_LOW 발행 블록(107줄) 제거 — 신호·감사 발행 중단.
  early_codes 는 3레인 공용 유니버스 합집합 재료로 보존.
- SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd: S03_EARLY_LOW_LIVE=NO · S03_FLOW_TURN_FAST_LIVE=NO
  (CRLF 19/19 · ASCII 검증 완료)
- live_features.S03_FLOW_TURN_FAST: true → false (수급반전 레인 폐지)
검증: py_compile OK · pytest strategy_03+s03_express 65 passed(수리 전 65, 실패 0→0).
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
    "RUN/hidden/SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd",
)
HASHES = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in PATHS}

NOTE = (
    "2026-08-27 owner order \"only two lanes: staircase and crash\": EARLY_LOW emission "
    "block (107 lines) removed from the signal generator (early_codes kept as shared "
    "universe input); launcher env S03_EARLY_LOW_LIVE=NO and S03_FLOW_TURN_FAST_LIVE=NO; "
    "live_features.S03_FLOW_TURN_FAST revoked to false. S03 is now OPEN_CRASH + "
    "INTRADAY_CRASH only. Sell rules, INTRADAY thresholds, slots unchanged. Tests 65 "
    "passed before and after."
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
    features = data.get("live_features")
    if not isinstance(features, dict) or "S03_FLOW_TURN_FAST" not in features:
        raise SystemExit("live_features.S03_FLOW_TURN_FAST missing")
    if features["S03_FLOW_TURN_FAST"] is not True:
        raise SystemExit(f"unexpected current value: {features['S03_FLOW_TURN_FAST']!r}")
    features["S03_FLOW_TURN_FAST"] = False
    numbers = [int(n) for n in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))]
    nxt = (max(numbers) + 1) if numbers else 1
    data["approval_scope"] += f" ({nxt}) {NOTE}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s03_2lane_20260827",
        expect_sha=read_content_sha(),
    ))

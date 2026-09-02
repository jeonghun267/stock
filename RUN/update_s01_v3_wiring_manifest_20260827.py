# -*- coding: utf-8 -*-
"""2026-08-27 밤 재봉인: 저녁 S01 v3 배선분을 승인 명부에 반영(활성화 아님).

경위: 8/27 저녁 S01 v3 배선(17:43~18:42)으로 파일 7개가 바뀌었으나 명부는
15:14 이 마지막이었다. 그 중 공용코어 strategy_01_rotation_engine_v2.py 가
common 레코드라서 관문(live_owner_approval_guard_v1)이 S01 뿐 아니라
S02·S03·S06 까지 FAIL 했고, strategy_all_live_gate_launcher_v1 이 return 3 으로
엔진 기동을 막는다(08:59 사전점검에는 해시 검사가 없어 못 잡는다).
그대로 두면 8/28 09:00 에 S01·S02·S03 엔진이 아예 안 뜬다.

친구님 승인("A안으로 해"): 명부 재봉인 + elevated 재기준선 2건만.
활성화 상태는 손대지 않는다 — S01_ENTRY_V3_MODE=SHADOW, S01_ROCKET_LIVE=NO,
S01_LEGACY_ENTRY_LIVE=NO 그대로. 매매 행동 변화 0.

검증(봉인 전 실측): 컴파일 7/7 OK · 집중 테스트 tests -k "strategy_01 or
entry_policy" 116 passed / 1 failed. 실패 1건은 공용 매도엔진 hard_stop 사유
라벨 건으로 기존 별건 — 공용 매도엔진과 해당 테스트는 8/25 이후 무변경이고,
저녁 rotation_engine diff(94+/4-)에 hard_stop 관련 줄이 0건임을 확인했다.
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
    "RUN/strategy_01_signal_contract_v2.py",
    "RUN/hidden/SAFEPLUS_STRATEGY01_SIGNAL.cmd",
    "RUN/strategy_01_open_surge_signal_v2.py",
    "RUN/strategy_01_entry_runtime_v3.py",
    "RUN/strategy_01_rotation_engine_v2.py",
    "RUN/hidden/SAFEPLUS_STRATEGY01_LIVE.cmd",
    "RUN/strategy_01_entry_policy_v3.py",
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
        f" ({nxt}) 2026-08-27 owner approval: reseal the evening S01 v3 wiring "
        "(shared rotation engine slot accounting for 6 total / ROCKET 3 / "
        "PULLBACK 3 with startup verification, entry_policy LANE_LIMITS rocket "
        "placement cap 1->3, entry runtime v3, signal contract v2, open surge "
        "signal v2, and the two S01 launchers) as approved code. Activation is "
        "unchanged and stays SHADOW: S01_ENTRY_V3_MODE=SHADOW, "
        "S01_ROCKET_LIVE=NO, S01_LEGACY_ENTRY_LIVE=NO. No trading behavior "
        "change; this only restores the owner-approval gate that was blocking "
        "S01/S02/S03/S06 engine startup. Compiled 7/7, focused tests 116 "
        "passed / 1 failed (pre-existing common sell-engine hard_stop reason "
        "label, unrelated and unmodified since 2026-08-25)."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s01_v3_wiring_reseal_20260827",
        expect_sha=read_content_sha(),
    ))

# -*- coding: utf-8 -*-
"""2026-08-27 밤 재봉인: S02 신호기 잠금 경로 env 분리(그림자A 경주 근본수리).

경위: 8/27 09:41 S02 실전 신호기 조용사의 원인은 SAFEPLUS_S02_SHADOW_A.cmd 가
실전 스크립트를 그대로 실행해 같은 싱글톤 잠금(data\strategy_02_signal_v1.lock)을
09:00 에 두고 경주한 것이었다(진 쪽이 조용히 return 0). 실전 41분 정지.
그림자 B·C 는 사본이라 무관했던 게 아니라 '잠금 도입 전 옛 버전(77KB)'이라 무관했다.

수리(친구님 지시 "그림자A도 수리해", 선택지 중 'env 분리' 선택):
  - RUN/strategy_02_low_buy_signal_v1.py main(): lock_path 하드코딩 ->
    os.environ.get("S02_LOCK_PATH", 기존 경로). env 미설정이면 기존 경로 그대로라
    실전 동작은 완전 불변.
  - RUN/hidden/SAFEPLUS_S02_SHADOW_A.cmd: S02_LOCK_PATH 를 그림자 전용 경로로 설정.
    (cmd 는 명부·elevated 어느 장부에도 미등록이라 봉인 대상 아님)

검증[실측]: 컴파일 OK · 잠금 점유 재현 3/3 PASS(같은 잠금 점유 중이면 산출물 없음,
다른 잠금이면 산출물 생성, 해제 후 생성) · env 미설정 회귀 2/2 PASS(기본 잠금 점유
중이면 막히고 해제하면 돈다) · pytest -k "strategy_02 or s02" 9 failed/72 passed 로
수정 전 기준선과 동일(신규 실패 0).
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
        f" ({nxt}) 2026-08-27 owner approval: the S02 signal singleton lock path "
        "becomes overridable via S02_LOCK_PATH, defaulting to the existing "
        "data\strategy_02_signal_v1.lock so live behavior is unchanged (the live "
        "launcher does not set it). The S02 shadow A launcher now sets its own "
        "lock path, so it can no longer win the 09:00 lock race that silently "
        "killed the live S02 signal for 41 minutes on 2026-08-27. Compiled; lock "
        "contention replay 3/3 and default-path regression 2/2 pass; "
        "pytest -k \"strategy_02 or s02\" 9 failed / 72 passed, identical to the "
        "pre-change baseline."
    )
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s02_shadow_lock_split_20260827",
        expect_sha=read_content_sha(),
    ))

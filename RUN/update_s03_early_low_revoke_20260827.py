# -*- coding: utf-8 -*-
"""2026-08-27 09:0x 친구님 지시 "초기 저점 지워버려 - 급락을 잡아야 되는데".

live_features.S03_EARLY_LOW 승인을 False 로 회수한다(조기저점 레인 실주문 차단).
- 게이트는 env(S03_EARLY_LOW_LIVE=AUTO) AND 명부 승인 AND release 의 3중 AND —
  승인 하나만 회수해도 fail-closed 로 닫힌다. 런처·엔진 파일은 무수정(해시 관문 무영향).
- 급락 레인(OPEN_CRASH/INTRADAY_CRASH/EXPRESS)은 이 승인과 무관 — 계속 산다.
- 실행 중 엔진은 시작 시 값을 박제하므로, 이 스크립트 실행 후 S03 엔진 재시작이 필요하다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approval_manifest_writer_v1 import read_content_sha, update_manifest

NOTE = (
    "2026-08-27 owner order (09:0x, in chat): remove the S03 early-low lane from live "
    "orders — \"catch crashes, not early lows\". live_features.S03_EARLY_LOW set to "
    "False. Launcher env stays AUTO; the three-factor AND now fails closed. Crash "
    "lanes (OPEN_CRASH/INTRADAY_CRASH/EXPRESS) are unaffected. Today the lane had "
    "already bought 4 (204270, 010170, 222800, 403870) before the revoke; existing "
    "positions keep normal sell management."
)


def mutate(data):
    features = data.get("live_features")
    if not isinstance(features, dict) or "S03_EARLY_LOW" not in features:
        raise SystemExit("live_features.S03_EARLY_LOW missing")
    if features["S03_EARLY_LOW"] is not True:
        raise SystemExit(f"unexpected current value: {features['S03_EARLY_LOW']!r}")
    features["S03_EARLY_LOW"] = False
    numbers = [int(n) for n in re.findall(r"\((\d+)\)", str(data.get("approval_scope") or ""))]
    nxt = (max(numbers) + 1) if numbers else 1
    data["approval_scope"] += f" ({nxt}) {NOTE}"
    return data


if __name__ == "__main__":
    print(update_manifest(
        mutate,
        updated_by="claude_s03_early_low_revoke_20260827",
        expect_sha=read_content_sha(),
    ))

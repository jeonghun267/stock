# -*- coding: utf-8 -*-
"""Start one independent strategy only after today's all-strategy preflight."""
from __future__ import annotations

import argparse
import json
import sys
import time as time_module
from datetime import datetime, time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from live_owner_approval_guard_v1 import verify_live_hashes


ROOT = Path(r"C:\stock_bot")
AUDIT = ROOT / "data" / "strategy_all_auto_live_preflight_v1.json"
GATES = {
    "S01": (
        ROOT / "config" / "strategy_01_off.flag",
        ROOT / "config" / "strategy_01_live_approved.flag",
    ),
    "S02": (
        ROOT / "config" / "strategy_02_off.flag",
        ROOT / "config" / "strategy_02_live_approved.flag",
    ),
    "S03": (
        ROOT / "config" / "strategy_03_off.flag",
        ROOT / "config" / "strategy_03_live_approved.flag",
    ),
}


def audit_state(
    strategy: str,
    today: str,
    audit_path: Path = AUDIT,
) -> str:
    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "WAIT"
    if (
        str(payload.get("for_date") or "") != today
        or not payload.get("finished_at")
    ):
        return "WAIT"
    activated = set(payload.get("activated_strategies") or [])
    if (
        payload.get("passed") is True
        and payload.get("activated") is True
        and strategy in activated
    ):
        return "PASS"
    return "FAIL"


def _engine_main(strategy: str) -> int:
    if strategy == "S01":
        from strategy_01_rotation_engine_v2 import main
    elif strategy == "S02":
        from strategy_02_rotation_engine_v1 import main
    else:
        from strategy_03_rotation_engine_v1 import main
    # Gate 전용 --strategy 인자가 엔진 argparse(--once)로 새어 들어가면
    # 사전점검 PASS 직후 엔진이 usage error(2)로 종료된다.
    original_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0]]
        return main()
    finally:
        sys.argv = original_argv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=tuple(GATES), required=True)
    args = parser.parse_args()
    strategy = args.strategy
    hashes_ok, hash_errors = verify_live_hashes(strategy)
    if not hashes_ok:
        print(
            f"{strategy} owner-approval hash failed; engine stopped: "
            + " | ".join(hash_errors),
            flush=True,
        )
        return 3
    # S01 must be alive before the opening burst arrives.  The engine itself
    # stays fail-closed until its live approval/off flags allow buying, so
    # starting it here only creates a safe standby process.
    if strategy == "S01":
        print("S01 engine starting in gate-controlled standby.", flush=True)
        return _engine_main(strategy)
    today = datetime.now().strftime("%Y%m%d")
    # ★[2026-07-27 친구님 승인] 사전점검(08:59:35)이 TR 지연 등으로 늦어져도 그날 통째로
    #   못 뜨는 일이 없도록 마감 09:00:25 → 09:05 연장(캡틴 BOARD_STALE 7/22 교훈).
    deadline_at = time(9, 21) if strategy == "S02" else time(9, 5, 0)
    deadline = datetime.combine(datetime.now().date(), deadline_at)
    off_path, approval_path = GATES[strategy]
    while True:
        state = audit_state(strategy, today)
        if state == "PASS" and approval_path.exists() and not off_path.exists():
            return _engine_main(strategy)
        if state == "FAIL":
            print(
                f"{strategy} all-strategy preflight failed; engine stopped.",
                flush=True,
            )
            return 2
        # ★[2026-07-27 친구님 승인] 마감은 '점검 결과 대기'의 상한일 뿐 — 오늘 PASS가 이미
        #   있으면 늦은 시각에도 기동 허용(크래시 복구 재기동 경로. 엔진 ProcessLock이 중복 차단).
        if datetime.now() > deadline:
            print(
                f"{strategy} preflight deadline expired; engine stopped.",
                flush=True,
            )
            return 2
        time_module.sleep(0.25)


if __name__ == "__main__":
    raise SystemExit(main())

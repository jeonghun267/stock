# -*- coding: utf-8 -*-
"""Start one independent strategy only after today's all-strategy preflight."""
from __future__ import annotations

import argparse
import json
import sys
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
    # All three opening strategies must be alive before the opening burst.
    # StrategyBroker remains the fail-closed authority for approval/off flags;
    # the shared engine does not select or consume signals while that gate is
    # closed, but its existing-position sell/recovery loop keeps running.
    print(
        f"{strategy} engine starting in gate-controlled standby.",
        flush=True,
    )
    return _engine_main(strategy)


if __name__ == "__main__":
    raise SystemExit(main())

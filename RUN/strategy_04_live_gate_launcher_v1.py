# -*- coding: utf-8 -*-
"""Wait for today's explicit S04 approval, then start the shared rotation."""
from __future__ import annotations

import json
import sys
import time as time_module
from datetime import datetime, time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


ROOT = Path(r"C:\stock_bot")
AUDIT = ROOT / "data" / "strategy_04_preflight_v1.json"
APPROVAL = ROOT / "config" / "strategy_04_live_approved.flag"
OFF = ROOT / "config" / "strategy_04_off.flag"


def _today_approved(today: str) -> bool:
    try:
        return today in APPROVAL.read_text(encoding="ascii")
    except OSError:
        return False


def _audit_passed(today: str) -> bool:
    try:
        payload = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        str(payload.get("for_date") or "") == today
        and payload.get("passed") is True
        and payload.get("activated") is True
        and bool(payload.get("finished_at"))
    )


def main() -> int:
    today = datetime.now().strftime("%Y%m%d")
    deadline = datetime.combine(datetime.now().date(), time(12, 0))
    while True:
        if _audit_passed(today) and _today_approved(today) and not OFF.exists():
            from strategy_04_rotation_engine_v1 import main as engine_main
            return engine_main()
        # ★[2026-07-27 친구님 승인] 마감(12:00)은 '승인 대기'의 상한일 뿐 — 오늘 승인이 이미
        #   있으면 늦은 시각에도 기동 허용(크래시 복구 재기동 경로. 엔진 ProcessLock이 중복 차단).
        if datetime.now() > deadline:
            print(
                "S04 approval/preflight deadline expired; engine stopped.",
                flush=True,
            )
            return 2
        time_module.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())

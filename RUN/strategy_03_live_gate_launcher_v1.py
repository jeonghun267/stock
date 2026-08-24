# -*- coding: utf-8 -*-
"""Start the S03 live engine only after today's automatic preflight passes."""
from __future__ import annotations

import json
import time as time_module
from datetime import datetime, time
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
APPROVAL = ROOT / "config" / "strategy_03_live_approved.flag"
OFF = ROOT / "config" / "strategy_03_off.flag"
AUDIT = ROOT / "data" / "strategy_03_auto_live_preflight_v1.json"


def _today_audit_state(today: str, audit_path: Path = AUDIT) -> str:
    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "WAIT"
    if (
        str(payload.get("for_date") or "") != today
        or not payload.get("finished_at")
    ):
        return "WAIT"
    if payload.get("passed") is True and payload.get("activated") is True:
        return "PASS"
    return "FAIL"


def main() -> int:
    today = datetime.now().strftime("%Y%m%d")
    deadline = datetime.combine(datetime.now().date(), time(9, 0, 25))
    while datetime.now() <= deadline:
        audit_state = _today_audit_state(today)
        if (
            audit_state == "PASS"
            and APPROVAL.exists()
            and not OFF.exists()
        ):
            from strategy_03_rotation_engine_v1 import main as engine_main
            return engine_main()
        if audit_state == "FAIL":
            print("Strategy 03 preflight failed; live engine remains stopped.", flush=True)
            return 2
        time_module.sleep(0.25)
    print("Strategy 03 preflight deadline expired; live engine remains stopped.", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

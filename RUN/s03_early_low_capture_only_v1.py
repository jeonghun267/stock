# -*- coding: utf-8 -*-
"""S03 EARLY_LOW selector capture only; no engine or broker is created."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, time as day_time
from pathlib import Path

from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector

ROOT = Path(r"C:\stock_bot")
SIGNAL = ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json"
SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop-sec", type=float, default=1.0)
    args = parser.parse_args()
    selector = make_strategy03_signal_selector(
        SNAPSHOT,
        4.0,
        early_low_live_enabled=False,
        flow_turn_live_enabled=True,
        bottom_all_lanes_live_enabled=False,
        audit_stream="capture_only",
    )
    while True:
        now = datetime.now()
        selector(_read(SIGNAL), now=now, max_age_sec=5.0, consumed=())
        if args.once or now.time() >= day_time(14, 31):
            return 0
        time.sleep(max(0.2, args.loop_sec))


if __name__ == "__main__":
    raise SystemExit(main())

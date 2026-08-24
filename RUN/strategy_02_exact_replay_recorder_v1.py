# -*- coding: utf-8 -*-
"""전략2 생산입력 주문 0 기록기. 생산 출력·주문·잠금을 사용하지 않는다."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
ISOLATED = ROOT / "data" / "s02_exact_replay_runtime"
ISOLATED.mkdir(parents=True, exist_ok=True)

os.environ["S02_OUTPUT"] = str(ISOLATED / "signal_state.json")
os.environ["S02_EVENT_DIR"] = str(ISOLATED / "events")
os.environ["S02_EXACT_REPLAY_DIR"] = str(ROOT / "data" / "s02_exact_replay")
os.environ["S02_EXACT_REPLAY_JOURNAL"] = "YES"
os.environ["S02_EXACT_REPLAY_MAX_BYTES"] = str(200 * 1024 * 1024)
os.environ["S02_ADAPTIVE_BOTTOM_ENABLED"] = "NO"

if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_02_low_buy_signal_v1 import SignalConfig, run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run(SignalConfig()))

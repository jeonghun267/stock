# -*- coding: utf-8 -*-
"""Read-only S02 flow/book recovery shadow runner.

Uses the production S02 signal monitor but writes to isolated shadow paths.
It never imports the broker or submits orders.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))
SHADOW_DIR = Path(os.environ.get("TEMP", r"C:\Windows\Temp")) / "stock_bot_s02_flow_book"
SHADOW_DIR.mkdir(parents=True, exist_ok=True)

os.environ["S02_OUTPUT"] = str(SHADOW_DIR / "s02_flow_book_shadow_signal.json")
os.environ["S02_EVENT_DIR"] = str(SHADOW_DIR)
os.environ["S02_FLOW_BOOK_SHADOW_ENABLED"] = "YES"

from strategy_02_low_buy_signal_v1 import SignalConfig, run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run(SignalConfig()))

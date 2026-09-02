# -*- coding: utf-8 -*-
"""Start the existing S07 engine with its local module path initialized."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_07_morning_trend_v1 import main

if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Scheduled-task launcher that exposes RUN modules to embedded Python."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_rotation_engine_v1 import main


if __name__ == "__main__":
    raise SystemExit(main())

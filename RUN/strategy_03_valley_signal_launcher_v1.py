# -*- coding: utf-8 -*-
"""ASCII-only scheduled-task launcher for RUN/골짜기_급반등.py."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from 골짜기_급반등 import main


if __name__ == "__main__":
    raise SystemExit(main())

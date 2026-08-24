# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
sys.path.insert(0, str(RUN_DIR))

from high_range_live_board_v1 import update_live_state


class WeekendGuardTest(unittest.TestCase):
    def test_weekend_price_does_not_create_intraday_extrema(self):
        sunday = datetime(2026, 7, 26, 9, 1)
        snapshot = {
            "codes": {
                "000001": {
                    "cur": 11_000,
                    "ts": sunday.isoformat(),
                }
            }
        }
        state = update_live_state([{"code": "000001"}], snapshot, {}, sunday)
        self.assertEqual(state["codes"]["000001"]["status"], "WAIT")
        self.assertNotIn("low", state["codes"]["000001"])


if __name__ == "__main__":
    unittest.main()

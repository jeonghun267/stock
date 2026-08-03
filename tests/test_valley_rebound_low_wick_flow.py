from datetime import datetime
import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_저점체결_분봉꼬리_분석.py")
SPEC = importlib.util.spec_from_file_location("valley_rebound_low_wick_flow", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValleyReboundLowWickFlowTest(unittest.TestCase):
    def test_bar_start_anchors_to_market_clock(self):
        ts = datetime.fromisoformat("2026-07-23T09:14:32.454")
        self.assertEqual(MODULE.bar_start(ts, 1).strftime("%H:%M"), "09:14")
        self.assertEqual(MODULE.bar_start(ts, 3).strftime("%H:%M"), "09:12")
        self.assertEqual(MODULE.bar_start(ts, 5).strftime("%H:%M"), "09:10")

    def test_wick_formula_separates_lower_and_upper(self):
        event = {
            "day": "20260723",
            "code": "000001",
            "name": "TEST",
            "low_at": datetime.fromisoformat("2026-07-23T09:00:10"),
            "low_price": 90.0,
        }
        points = [
            {"ts": datetime.fromisoformat("2026-07-23T09:00:00"), "price": 100.0},
            {"ts": event["low_at"], "price": 90.0},
            {"ts": datetime.fromisoformat("2026-07-23T09:00:59"), "price": 105.0},
        ]
        row = MODULE.wick_row(event, points, 1)
        self.assertEqual(row["lower_wick"], 10.0)
        self.assertEqual(row["upper_wick"], 0.0)
        self.assertTrue(row["lower_gt_upper"])
        self.assertAlmostEqual(row["close_position"], 1.0)

    def test_completed_bar_is_explicitly_lookahead(self):
        event = {
            "day": "20260723",
            "code": "000001",
            "name": "TEST",
            "low_at": datetime.fromisoformat("2026-07-23T09:00:10"),
            "low_price": 90.0,
        }
        points = [
            {"ts": datetime.fromisoformat("2026-07-23T09:00:00"), "price": 100.0},
            {"ts": event["low_at"], "price": 90.0},
            {"ts": datetime.fromisoformat("2026-07-23T09:00:59"), "price": 101.0},
        ]
        self.assertTrue(MODULE.wick_row(event, points, 1)["completed_bar_lookahead"])


if __name__ == "__main__":
    unittest.main()

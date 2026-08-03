from datetime import datetime
import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_저점체결_분봉꼬리_정정.py")
SPEC = importlib.util.spec_from_file_location("valley_rebound_alignment", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValleyReboundTimestampAlignmentTest(unittest.TestCase):
    def test_millisecond_event_matches_microsecond_raw_point(self):
        event = {
            "day": "20260723",
            "code": "067290",
            "name": "TEST",
            "low_at": datetime.fromisoformat("2026-07-23T09:16:56.573"),
            "low_price": 2010.0,
        }
        points = [
            {
                "ts": datetime.fromisoformat("2026-07-23T09:16:56.573091"),
                "price": 2010.0,
                "che_str": 42.78,
                "buy_vol_cum": 260705.0,
                "sell_vol_cum": 582587.0,
                "buy_money_cum": 539691958.0,
                "sell_money_cum": 1196177703.0,
            },
            {
                "ts": datetime.fromisoformat("2026-07-23T09:16:57.580009"),
                "price": 2010.0,
                "che_str": 42.82,
                "buy_vol_cum": 261845.0,
                "sell_vol_cum": 584793.0,
                "buy_money_cum": 541989058.0,
                "sell_money_cum": 1200611763.0,
            },
        ]
        row = MODULE.cumulative_window(event, points, 2)
        self.assertTrue(row["exact_valid"])
        self.assertEqual(row["buy_exec_volume"], 1140.0)
        self.assertEqual(row["sell_exec_volume"], 2206.0)
        self.assertLess(row["buy_sell_volume_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()

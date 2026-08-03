from datetime import datetime
import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_07흡수_1분봉_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_absorption_07", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BASE = MODULE.BASE


def point(second, price, buy, sell, ask=100, bid=120):
    return BASE.Point(
        ts=datetime.fromisoformat(f"2026-07-23T09:00:{second:02d}"),
        price=price,
        che_str=100,
        ask_tot=ask,
        bid_tot=bid,
        buy_vol_cum=buy,
        sell_vol_cum=sell,
    )


EVENT = {
    "day": "20260723",
    "code": "000001",
    "name": "TEST",
    "previous_close": 10_500,
}


class ValleyAbsorption07WickTest(unittest.TestCase):
    def test_one_minute_lower_wick_formula(self):
        bar = {"open": 10_100, "high": 10_100, "low": 10_000, "close": 10_050}
        state = MODULE.wick_state(bar)
        self.assertTrue(state["lower_gt_upper"])
        self.assertEqual(state["lower_wick"], 50)
        self.assertEqual(state["upper_wick"], 0)

    def test_ratio_07_with_lower_wick_and_bid_support_signals(self):
        points = [
            point(0, 10_100, 0, 0),
            point(1, 10_000, 0, 0),
            point(3, 10_040, 6, 10, ask=90, bid=130),
            point(4, 10_050, 7, 11, ask=90, bid=130),
        ]
        candidate = BASE.Candidate(
            "ABSORB_R0.7_WICK_BOOK_3_10",
            "absorption_07",
            10.0,
            "bid_over_ask",
        )
        signal = MODULE.first_signal(EVENT, points, candidate)
        self.assertIsNotNone(signal)
        self.assertLessEqual(signal["buy_sell_ratio"], 0.7)

    def test_ratio_above_limit_does_not_signal(self):
        points = [
            point(0, 10_100, 0, 0),
            point(1, 10_000, 0, 0),
            point(3, 10_040, 8, 10),
            point(4, 10_050, 9, 11),
        ]
        candidate = BASE.Candidate(
            "ABSORB_R0.7_WICK_3_10",
            "absorption_07",
            10.0,
            "none",
        )
        self.assertIsNone(MODULE.first_signal(EVENT, points, candidate))


if __name__ == "__main__":
    unittest.main()

from datetime import datetime
import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_재시도기억_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_retry_memory", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BASE = MODULE.BASE


def point(second, price, buy, sell, che=100, ask=100, bid=120):
    return BASE.Point(
        ts=datetime.fromisoformat(f"2026-07-23T09:00:{second:02d}"),
        price=price,
        che_str=che,
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


class ValleyRetryMemoryTest(unittest.TestCase):
    def test_first_tentative_is_skipped_and_second_low_can_signal(self):
        points = [
            point(0, 10_000, 0, 0, che=100),
            point(3, 10_010, 5, 1, che=101),
            point(4, 10_010, 6, 1, che=102),
            point(5, 9_990, 6, 2, che=90),
            point(8, 10_000, 8, 5, che=91),
            point(9, 10_000, 10, 5, che=92),
        ]
        candidate = BASE.Candidate("RETRY1_ONLY_3_10", "retry_combined", 10.0, "bid_over_ask")
        signal = MODULE.first_signal(EVENT, points, candidate)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["anchor_low_price"], 9_990)
        self.assertEqual(signal["failed_rebounds_before_signal"], 1)

    def test_strong_flow_can_enter_without_prior_failure(self):
        points = [
            point(0, 10_000, 0, 0, che=100),
            point(3, 10_010, 9, 1, che=101),
            point(4, 10_010, 10, 1, che=102),
        ]
        candidate = BASE.Candidate("RETRY1_OR_FLOW5_3_10", "retry_combined", 10.0, "bid_over_ask")
        signal = MODULE.first_signal(EVENT, points, candidate)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["failed_rebounds_before_signal"], 0)


if __name__ == "__main__":
    unittest.main()

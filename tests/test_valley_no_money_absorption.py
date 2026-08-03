from datetime import datetime
import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_매도흡수_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_no_money_absorption", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def point(second, price, buy, sell, che=100, ask=100, bid=120):
    return MODULE.Point(
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
    "armed_at": datetime.fromisoformat("2026-07-23T09:00:00"),
    "final_low": 10_000,
    "final_low_at": datetime.fromisoformat("2026-07-23T09:00:00"),
    "quick_v": True,
}


class ValleyNoMoneyAbsorptionTest(unittest.TestCase):
    def test_small_volume_flow_signal_has_no_money_minimum(self):
        points = [
            point(0, 10_000, 0, 0, che=100),
            point(1, 10_000, 1, 3, che=99),
            point(3, 10_010, 5, 3, che=101),
            point(4, 10_010, 6, 3, che=102),
        ]
        candidate = MODULE.Candidate("FLOW", "flow_transition", 5.0)
        signal = MODULE.first_signal(EVENT, points, candidate)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["buy_exec_volume"] + signal["sell_exec_volume"], 9)

    def test_sell_dominance_with_price_hold_and_bid_support_is_absorption(self):
        points = [
            point(0, 10_000, 0, 0, ask=100, bid=110),
            point(2, 10_010, 1, 4, ask=95, bid=120),
            point(3, 10_020, 2, 7, ask=90, bid=130),
            point(4, 10_020, 3, 9, ask=90, bid=130),
        ]
        candidate = MODULE.Candidate("ABS", "absorption", 5.0, "bid_over_ask")
        signal = MODULE.first_signal(EVENT, points, candidate)
        self.assertIsNotNone(signal)
        self.assertLess(signal["net_exec_volume"], 0)

    def test_new_low_resets_old_flow(self):
        points = [
            point(0, 10_000, 0, 0),
            point(2, 10_010, 10, 1, che=105),
            point(3, 9_990, 10, 10, che=90),
            point(4, 10_000, 10, 11, che=91),
            point(6, 10_000, 10, 12, che=92),
        ]
        candidate = MODULE.Candidate("FLOW", "flow_dominance", 10.0)
        self.assertIsNone(MODULE.first_signal(EVENT, points, candidate))


if __name__ == "__main__":
    unittest.main()

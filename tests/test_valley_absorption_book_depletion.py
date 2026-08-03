import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_07흡수_호가소진_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_absorption_book_depletion", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BASE = MODULE.BASE


def point(ask, bid):
    return BASE.Point(
        ts=datetime.fromisoformat("2026-07-23T09:00:04"),
        price=10_050,
        che_str=100,
        ask_tot=ask,
        bid_tot=bid,
        buy_vol_cum=7,
        sell_vol_cum=11,
    )


class ValleyAbsorptionBookDepletionTest(unittest.TestCase):
    def test_both_hold_requires_bid_hold_and_ask_depletion(self):
        self.assertTrue(MODULE.book_pass("both_hold", point(90, 130), 100, 120))
        self.assertFalse(MODULE.book_pass("both_hold", point(110, 130), 100, 120))
        self.assertFalse(MODULE.book_pass("both_hold", point(90, 110), 100, 120))

    def test_imbalance_must_improve_from_low(self):
        self.assertTrue(MODULE.book_pass("imbalance_improve", point(80, 160), 100, 120))
        self.assertFalse(MODULE.book_pass("imbalance_improve", point(100, 110), 100, 120))


if __name__ == "__main__":
    unittest.main()

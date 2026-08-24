# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "analysis" / "골짜기_급반등_초단기매수우위_백테스트.py"
SPEC = importlib.util.spec_from_file_location("valley_ultra_short", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValleyUltraShortBuyDominanceTest(unittest.TestCase):
    def point(
        self,
        second: float,
        price: float,
        *,
        buy: float,
        sell: float,
        che: float,
    ):
        return MODULE.BASE.ReplayPoint(
            ts=datetime(2026, 7, 23, 9, 0, 0) + timedelta(seconds=second),
            price=price,
            cum_vol=1_000,
            che_str=che,
            ask_tot=1_000,
            bid_tot=1_000,
            buy_money_cum=buy,
            sell_money_cum=sell,
        )

    def cfg(self, ratio: float = 2.0, window: float = 3.0):
        return MODULE.CandidateConfig(ratio, window, 0.0)

    def test_signals_without_completed_candle_when_buy_is_two_times_sell(self):
        points = [
            self.point(0, 11_400, buy=100_000_000, sell=100_000_000, che=90),
            self.point(1, 11_400, buy=112_000_000, sell=105_000_000, che=100),
        ]
        signal = MODULE.ultra_short_signal("000010", 12_000, points, self.cfg())
        self.assertIsNotNone(signal)
        self.assertEqual(signal.ts, points[-1].ts)

    def test_new_low_resets_old_buy_money(self):
        points = [
            self.point(0, 11_400, buy=100_000_000, sell=100_000_000, che=90),
            self.point(0.5, 11_400, buy=120_000_000, sell=101_000_000, che=100),
            self.point(0.6, 11_300, buy=121_000_000, sell=102_000_000, che=95),
            self.point(1.6, 11_300, buy=125_000_000, sell=105_000_000, che=96),
        ]
        signal = MODULE.ultra_short_signal("000010", 12_000, points, self.cfg())
        self.assertIsNone(signal)

    def test_rejects_when_buy_multiple_is_below_threshold(self):
        points = [
            self.point(0, 11_400, buy=100_000_000, sell=100_000_000, che=90),
            self.point(1, 11_400, buy=112_000_000, sell=108_000_000, che=100),
        ]
        signal = MODULE.ultra_short_signal("000010", 12_000, points, self.cfg())
        self.assertIsNone(signal)

    def test_rejects_after_short_window(self):
        points = [
            self.point(0, 11_400, buy=100_000_000, sell=100_000_000, che=90),
            self.point(4, 11_400, buy=130_000_000, sell=105_000_000, che=100),
        ]
        signal = MODULE.ultra_short_signal("000010", 12_000, points, self.cfg())
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()

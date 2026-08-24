# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "analysis" / "골짜기_급반등_진입비교_백테스트.py"
SPEC = importlib.util.spec_from_file_location("valley_rebound_backtest", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValleyReboundEntryComparisonTest(unittest.TestCase):
    def point(
        self,
        second: int,
        price: float,
        *,
        buy: float = 100_000_000,
        sell: float = 100_000_000,
        che: float = 100.0,
    ):
        return MODULE.ReplayPoint(
            ts=datetime(2026, 7, 23, 9, 0, 0) + timedelta(seconds=second),
            price=price,
            cum_vol=1_000 + second * 100,
            che_str=che,
            ask_tot=1_000,
            bid_tot=1_500,
            buy_money_cum=buy,
            sell_money_cum=sell,
        )

    def test_current_fast_path_replays_without_completed_candle(self) -> None:
        points = [
            self.point(0, 11_400, che=100),
            self.point(1, 11_410, buy=102_000_000, sell=101_000_000, che=101),
            self.point(2, 11_480, buy=109_000_000, sell=103_000_000, che=110),
            self.point(3, 11_490, buy=113_000_000, sell=104_000_000, che=112),
            self.point(4, 11_500, buy=117_000_000, sell=105_000_000, che=115),
        ]
        signal = MODULE._current_valley_signal("000010", 12_000, points)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.algorithm, "CURRENT_VALLEY")
        self.assertEqual(signal.ts, points[-1].ts)

    def test_quick_rebound_and_redrop_labels_are_separate(self) -> None:
        points = [
            self.point(0, 11_400),
            self.point(2, 11_300),
            self.point(6, 11_380),
            self.point(8, 11_250),
            self.point(12, 11_370),
        ]
        labels = MODULE._event_labels(points, 12_000)
        self.assertTrue(labels["quick_v_rebound"])
        self.assertTrue(labels["redrop_after_rebound"])
        self.assertTrue(labels["actionable_rebound_1pct"])

    def test_hybrid_chooses_first_valid_signal(self) -> None:
        early = MODULE.EntrySignal(
            "CURRENT_VALLEY",
            datetime(2026, 7, 23, 9, 1, 1),
            10_100,
            datetime(2026, 7, 23, 9, 1, 0),
            10_000,
            "fast",
        )
        late = MODULE.EntrySignal(
            "S02_EXHAUSTION",
            datetime(2026, 7, 23, 9, 1, 10),
            10_120,
            datetime(2026, 7, 23, 9, 1, 5),
            10_000,
            "exhaustion",
        )
        selected = MODULE._first_signal(early, late)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.ts, early.ts)
        self.assertTrue(selected.reason.startswith("CURRENT_VALLEY:"))

    def test_stop_and_costs_are_applied_after_signal_only(self) -> None:
        signal = MODULE.EntrySignal(
            "CURRENT_VALLEY",
            datetime(2026, 7, 23, 9, 1, 0),
            10_000,
            datetime(2026, 7, 23, 9, 0, 58),
            9_950,
            "test",
        )
        prices = [
            (datetime(2026, 7, 23, 9, 1, 0), 10_000),
            (datetime(2026, 7, 23, 9, 1, 1), 10_100),
            (datetime(2026, 7, 23, 9, 1, 2), 9_790),
            (datetime(2026, 7, 23, 9, 1, 3), 10_500),
        ]
        labels = {"morning_low_at": "2026-07-23T09:00:58.000"}
        row = MODULE._evaluate_entry(signal, prices, labels)
        self.assertTrue(row["hard_stop"])
        self.assertEqual(row["exit_price"], 9_790)
        self.assertAlmostEqual(row["gross_stop_or_1520_pct"], -2.1, places=4)
        self.assertAlmostEqual(row["net_with_slippage_pct"], -2.41, places=4)


if __name__ == "__main__":
    unittest.main()

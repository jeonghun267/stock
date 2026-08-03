# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(RUN_DIR))

from 저점매수_매도소진 import (  # noqa: E402
    FlowBookExhaustionConfig,
    LegacyPullConfig,
    MarketPoint,
    SellExhaustionConfig,
    detect_flow_book_exhaustion,
    detect_hybrid_exhaustion_pull,
    detect_sell_exhaustion,
)


BASE_TS = datetime(2026, 7, 24, 9, 30)


def points(
    prices: list[float],
    sell_steps: list[float],
    buy_steps: list[float],
    ask_totals: list[float] | None = None,
    bid_totals: list[float] | None = None,
):
    buy_cum = 0.0
    sell_cum = 0.0
    rows = []
    for idx, price in enumerate(prices):
        buy_cum += buy_steps[idx]
        sell_cum += sell_steps[idx]
        rows.append(
            MarketPoint(
                ts=BASE_TS + timedelta(seconds=idx),
                price=price,
                cum_vol=idx * 100,
                che_str=100.0,
                ask_tot=ask_totals[idx] if ask_totals else 1_000.0,
                bid_tot=bid_totals[idx] if bid_totals else 1_000.0,
                buy_money_cum=buy_cum,
                sell_money_cum=sell_cum,
            )
        )
    return rows


class SellExhaustionBottomTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SellExhaustionConfig(
            min_depth_pct=1.0,
            noise_floor_pct=0.20,
            noise_cap_pct=0.20,
            weakness_required=2,
            min_flow_observations=3,
            min_buy_dominant_fraction=0.60,
        )

    def test_temporary_bounce_does_not_trigger_before_lower_exhausted_low(self):
        prices = [
            10_300,
            10_200,
            10_100,
            10_000,
            10_030,
            10_060,
            10_020,
            9_980,
            9_960,
            9_990,
            10_020,
            10_010,
            9_970,
            9_940,
            9_930,
            9_960,
            9_990,
            10_010,
        ]
        sell = [
            0,
            100,
            100,
            100,
            20,
            20,
            50,
            50,
            50,
            10,
            10,
            20,
            25,
            25,
            25,
            5,
            5,
            5,
        ]
        buy = [
            0,
            10,
            10,
            10,
            30,
            30,
            10,
            10,
            10,
            40,
            40,
            10,
            30,
            30,
            30,
            60,
            60,
            60,
        ]
        signal = detect_sell_exhaustion(points(prices, sell, buy), self.cfg)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.anchor_low_price, 9_930)
        self.assertGreaterEqual(signal.signal_ts, BASE_TS + timedelta(seconds=15))

    def test_continuing_decline_without_reclaim_has_no_signal(self):
        prices = [10_300, 10_200, 10_100, 10_000, 10_030, 9_950, 9_900, 9_850]
        sell = [0, 100, 100, 100, 10, 100, 100, 100]
        buy = [0, 10, 10, 10, 20, 10, 10, 10]
        signal = detect_sell_exhaustion(points(prices, sell, buy), self.cfg)
        self.assertIsNone(signal)

    def test_buy_flow_is_required_after_reclaim(self):
        prices = [
            10_300,
            10_200,
            10_100,
            10_000,
            10_030,
            10_060,
            10_020,
            9_980,
            9_960,
            9_990,
            10_020,
        ]
        sell = [0, 100, 100, 100, 20, 20, 30, 30, 30, 80, 80]
        buy = [0, 10, 10, 10, 30, 30, 10, 10, 10, 5, 5]
        signal = detect_sell_exhaustion(points(prices, sell, buy), self.cfg)
        self.assertIsNone(signal)

    def test_flow_book_detector_rejects_rebound_without_bid_book_recovery(self):
        prices = [
            10_300, 10_200, 10_100, 10_000, 10_030, 10_060,
            10_020, 9_980, 9_960, 9_990, 10_020, 10_010,
            9_970, 9_940, 9_930, 9_960, 9_990, 10_010,
        ]
        sell = [
            0, 100, 100, 100, 20, 20, 50, 50, 50,
            10, 10, 20, 25, 25, 25, 5, 5, 5,
        ]
        buy = [
            0, 10, 10, 10, 30, 30, 10, 10, 10,
            40, 40, 10, 30, 30, 30, 60, 60, 60,
        ]
        asks = [1_000.0] * len(prices)
        bids = [1_000.0] * 12 + [400.0] * 6
        signal = detect_flow_book_exhaustion(
            points(prices, sell, buy, asks, bids),
            self.cfg,
            FlowBookExhaustionConfig(min_sell_pressure_improvement=0.05),
        )
        self.assertIsNone(signal)

    def test_flow_book_detector_accepts_persistent_bid_book_recovery(self):
        prices = [
            10_300, 10_200, 10_100, 10_000, 10_030, 10_060,
            10_020, 9_980, 9_960, 9_990, 10_020, 10_010,
            9_970, 9_940, 9_930, 9_960, 9_990, 10_010,
        ]
        sell = [
            0, 100, 100, 100, 20, 20, 50, 50, 50,
            10, 10, 20, 25, 25, 25, 5, 5, 5,
        ]
        buy = [
            0, 10, 10, 10, 30, 30, 10, 10, 10,
            40, 40, 10, 30, 30, 30, 60, 60, 60,
        ]
        asks = [1_000.0] * len(prices)
        bids = [1_000.0] * 12 + [2_000.0] * 6
        signal = detect_flow_book_exhaustion(
            points(prices, sell, buy, asks, bids),
            self.cfg,
            FlowBookExhaustionConfig(min_sell_pressure_improvement=0.05),
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.anchor_low_price, 9_930)

    def test_hybrid_accepts_higher_low_only_with_real_buy_flow(self):
        prices = [
            10_300,
            10_000,
            10_020,
            10_030,
            10_100,
            10_080,
            10_050,
            10_050,
            10_070,
        ]
        sell = [0, 100, 10, 10, 10, 20, 20, 5, 5]
        buy = [0, 10, 30, 30, 30, 40, 40, 40, 40]
        signal = detect_hybrid_exhaustion_pull(
            points(prices, sell, buy),
            self.cfg,
            LegacyPullConfig(no_new_low_sec=2.0, min_depth_pct=1.0),
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.anchor_low_price, 10_050)
        self.assertIn("HigherLow", signal.reason)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(RUN_DIR))

from captain2_strategy_01_shadow_v1 import (  # noqa: E402
    OpenSurgeShadowMonitor,
    ShadowPoint,
)


class Captain2Strategy01ShadowTests(unittest.TestCase):
    def point(self, second: int, price: float, buy: float, sell: float, **kwargs):
        values = {
            "ts": datetime(2026, 7, 27, 9, 0, second),
            "code": "123450", "name": "테스트",
            "previous_close": 10000.0, "price": price,
            "money_speed_5s": 2_000_000.0,
            "money_speed_30s": 0.0,
            "buy_money_cum": buy, "sell_money_cum": sell,
            "exact_flow": True,
        }
        values.update(kwargs)
        return ShadowPoint(**values)

    def test_emits_once_after_three_second_rise(self):
        monitor = OpenSurgeShadowMonitor()
        signals = []
        for second in range(5):
            signals.extend(monitor.process_points([
                self.point(second, 10000 + 20 * second, 1_000_000 + 750_000 * second,
                           1_000_000 + 250_000 * second)
            ]))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["action"], "BUY_READY")
        self.assertEqual(len(monitor.signals), 1)

    def test_small_gap_is_observed_not_lost(self):
        monitor = OpenSurgeShadowMonitor()
        signals = []
        for second in range(5):
            signals.extend(monitor.process_points([
                self.point(
                    second, 10100 + 20 * second,
                    1_000_000 + 750_000 * second,
                    1_000_000 + 250_000 * second,
                )
            ]))
        self.assertEqual(len(signals), 1)

    def test_below_open_is_reserved_for_strategy_two(self):
        monitor = OpenSurgeShadowMonitor()
        points = [
            self.point(0, 10000, 1_000_000, 1_000_000),
            self.point(1, 9950, 1_750_000, 1_250_000),
            self.point(2, 10020, 2_500_000, 1_500_000),
            self.point(3, 10040, 3_250_000, 1_750_000),
            self.point(4, 10060, 4_000_000, 2_000_000),
        ]
        for point in points:
            monitor.process_points([point])
        self.assertEqual(monitor.latest["123450"]["reason"], "LOW_BUY_IS_STRATEGY_02")
        self.assertEqual(monitor.signals, [])

    def test_prior_high_above_three_percent_blocks_chase(self):
        monitor = OpenSurgeShadowMonitor()
        points = [
            self.point(0, 10000, 1_000_000, 1_000_000),
            self.point(1, 10350, 1_750_000, 1_250_000),
            self.point(2, 10100, 2_500_000, 1_500_000),
            self.point(3, 10120, 3_250_000, 1_750_000),
            self.point(4, 10140, 4_000_000, 2_000_000),
        ]
        for point in points:
            monitor.process_points([point])
        self.assertEqual(monitor.latest["123450"]["reason"], "CHASE_ABOVE_OPEN_3PCT")
        self.assertEqual(monitor.signals, [])

    def test_premarket_gap_is_tracked_without_signal(self):
        monitor = OpenSurgeShadowMonitor()
        premarket = self.point(0, 10350, 1_000_000, 1_000_000)
        premarket = ShadowPoint(**{
            **premarket.__dict__,
            "ts": datetime(2026, 7, 27, 8, 59, 50),
        })
        signals = monitor.process_points([premarket])
        self.assertEqual(signals, [])
        self.assertTrue(monitor.states["123450"].premarket_gap)
        self.assertEqual(monitor.latest["123450"]["reason"], "PREMARKET_TRACK")

    def test_restore_prevents_duplicate_signal_after_restart(self):
        monitor = OpenSurgeShadowMonitor()
        monitor.restore_emitted({
            "date": "20260727",
            "signals": [{"code": "123450", "action": "BUY_READY"}],
        }, "20260727")
        start = datetime(2026, 7, 27, 9, 0)
        for second in range(5):
            point = self.point(
                second, 10000 + second * 20,
                1_000_000 + 750_000 * second,
                1_000_000 + 250_000 * second,
            )
            self.assertLessEqual(abs((point.ts - (start + timedelta(seconds=second))).total_seconds()), 0)
            self.assertEqual(monitor.process_points([point]), [])
        self.assertEqual(len(monitor.signals), 1)


if __name__ == "__main__":
    unittest.main()

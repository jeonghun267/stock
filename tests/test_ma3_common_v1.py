# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import ma3_common_v1 as ma3


class Ma3CommonV1Tests(unittest.TestCase):
    @staticmethod
    def opening_payload():
        closes = list(range(100, 120))
        labels = [f"20260803{1400 + index * 3:04d}" for index in range(20)]
        return {
            "ts": "2026-08-04T09:00:05",
            "hm": "0900",
            "m": {
                "000001": {
                    "prev": [[value, value, value, value] for value in closes],
                    "pm": labels,
                    "c": 120,
                }
            },
        }

    def test_ma_is_available_at_open_with_prior_session_seed_and_live_price(self):
        row = ma3.ma3_rows("000001", self.opening_payload())
        self.assertIsNotNone(row)
        self.assertEqual(row["blocks"], 21.0)
        self.assertAlmostEqual(row["ma5"], sum(range(116, 121)) / 5)
        self.assertAlmostEqual(row["ma20_prev"], sum(range(100, 120)) / 20)

    def test_on_demand_cache_makes_ma_available_without_waiting_an_hour(self):
        start = datetime(2026, 8, 3, 14, 0)
        cached = [(start + timedelta(minutes=3 * index), 100.0 + index)
                  for index in range(20)]
        payload = {
            "ts": "2026-08-04T09:00:05",
            "hm": "0900",
            "m": {"000002": {"prev": [], "pm": [], "c": 120.0}},
        }
        with patch.object(ma3, "read_cached_bars", return_value=cached):
            row = ma3.ma3_rows("000002", payload)
        self.assertIsNotNone(row)
        self.assertEqual(row["blocks"], 21.0)

    def test_premarket_rows_are_not_used_for_ma(self):
        payload = self.opening_payload()
        row = payload["m"]["000001"]
        row["prev"] = [[90, 90, 90, 90]] * 4 + row["prev"]
        row["pm"] = ["202608040830", "202608040833", "202608040836", "202608040839"] + row["pm"]
        closes = ma3.three_minute_closes("000001", payload)
        self.assertEqual(len(closes), 21)
        self.assertEqual(closes[-1], 120.0)
        self.assertNotIn(90.0, closes)

    def test_support_stage_uses_ma5_then_ma10_then_rising_ma20(self):
        rising = {
            "ma5": 105.0,
            "ma10": 100.0,
            "ma20": 95.0,
            "ma20_prev": 94.0,
            "blocks": 21.0,
        }
        with patch.object(ma3, "ma3_rows", return_value=rising):
            self.assertEqual(ma3.line_support_stage("000001", 106.0), "MA5")
            self.assertEqual(ma3.line_support_stage("000001", 102.0), "MA10")
            self.assertEqual(ma3.line_support_stage("000001", 97.0), "MA20")
            self.assertEqual(ma3.line_support_stage("000001", 94.0), "")

        falling = dict(rising, ma20_prev=96.0)
        with patch.object(ma3, "ma3_rows", return_value=falling):
            self.assertEqual(ma3.line_support_stage("000001", 102.0), "MA10")
            self.assertEqual(ma3.line_support_stage("000001", 97.0), "")

    def test_rider_requires_explicit_buy_side(self) -> None:
        rising = {
            "ma5": 105.0,
            "ma10": 100.0,
            "ma20": 95.0,
            "ma20_prev": 94.0,
            "blocks": 21.0,
        }
        with patch.object(ma3, "ma3_rows", return_value=rising):
            self.assertFalse(ma3.rider_permit("000001", 110.0, buy_side=None))
            self.assertFalse(ma3.rider_permit("000001", 110.0, buy_side=False))
            self.assertTrue(ma3.rider_permit("000001", 110.0, buy_side=True))


if __name__ == "__main__":
    unittest.main()

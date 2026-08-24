from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_common_relative_strength_rebound_v1 import (  # noqa: E402
    RelativeStrengthReboundShadow,
)


class RelativeStrengthReboundShadowTest(unittest.TestCase):
    def test_ready_candidate_is_still_order_zero(self) -> None:
        judge = RelativeStrengthReboundShadow()
        start = datetime(2026, 8, 21, 9, 5, 0)
        prices = [9700.0, 9700.0, 9710.0, 9760.0]
        buys = [100.0, 110.0, 120.0, 160.0]
        sells = [100.0, 115.0, 125.0, 130.0]
        row = {}
        for index in range(4):
            row = judge.evaluate(
                code="000001",
                ts=start + timedelta(seconds=index * 2),
                price=prices[index],
                previous_close=10000.0,
                market_pct=-5.0,
                buy_money_cum=buys[index],
                sell_money_cum=sells[index],
                best_ask_px=9770.0,
                best_bid_px=9760.0,
                best_ask_qty=100.0,
                best_bid_qty=120.0,
            )
        self.assertTrue(row["crs_shadow_candidate"])
        self.assertEqual(row["crs_order_qty"], 0)
        self.assertFalse(row["crs_live_eligible"])

    def test_missing_market_fails_closed(self) -> None:
        judge = RelativeStrengthReboundShadow()
        row = judge.evaluate(
            code="000001",
            ts=datetime(2026, 8, 21, 9, 5),
            price=10000.0,
            previous_close=10000.0,
            market_pct=None,
            buy_money_cum=1.0,
            sell_money_cum=1.0,
            best_ask_px=10010.0,
            best_bid_px=10000.0,
            best_ask_qty=100.0,
            best_bid_qty=100.0,
        )
        self.assertFalse(row["crs_shadow_candidate"])
        self.assertIn("MARKET_MISSING", row["crs_shadow_reason"])

    def test_s03_deep_crash_rebound_is_order_zero(self) -> None:
        judge = RelativeStrengthReboundShadow()
        start = datetime(2026, 8, 21, 9, 0, 0)
        rows = [
            (0, 9000.0, 100.0, 100.0, 100.0),
            (20, 9000.0, 110.0, 115.0, 110.0),
            (40, 9010.0, 120.0, 125.0, 120.0),
            (61, 9090.0, 170.0, 130.0, 130.0),
        ]
        result = {}
        for seconds, price, buy, sell, volume in rows:
            result = judge.evaluate(
                code="000001",
                ts=start + timedelta(seconds=seconds),
                price=price,
                previous_close=10000.0,
                market_pct=-4.0,
                buy_money_cum=buy,
                sell_money_cum=sell,
                best_ask_px=9100.0,
                best_bid_px=9090.0,
                best_ask_qty=100.0,
                best_bid_qty=120.0,
                cum_vol=volume,
                deep_crash_enabled=True,
            )
        self.assertTrue(result["dcr_shadow_candidate"])
        self.assertEqual(result["dcr_order_qty"], 0)
        self.assertFalse(result["dcr_live_eligible"])

    def test_s03_deep_crash_blocks_during_vi_suspect(self) -> None:
        judge = RelativeStrengthReboundShadow()
        start = datetime(2026, 8, 21, 9, 0, 0)
        result = {}
        for seconds, price, buy, sell, volume in [
            (0, 9000.0, 100.0, 100.0, 100.0),
            (20, 9000.0, 110.0, 115.0, 120.0),
            (40, 9010.0, 120.0, 125.0, 30.0),
            (61, 9090.0, 170.0, 130.0, 40.0),
        ]:
            result = judge.evaluate(
                code="000001",
                ts=start + timedelta(seconds=seconds),
                price=price,
                previous_close=10000.0,
                market_pct=-4.0,
                buy_money_cum=buy,
                sell_money_cum=sell,
                best_ask_px=9100.0,
                best_bid_px=9090.0,
                best_ask_qty=100.0,
                best_bid_qty=120.0,
                cum_vol=volume,
                deep_crash_enabled=True,
            )
        self.assertFalse(result["dcr_shadow_candidate"])
        self.assertIn("VI_ACTIVE", result["dcr_shadow_reason"])


if __name__ == "__main__":
    unittest.main()

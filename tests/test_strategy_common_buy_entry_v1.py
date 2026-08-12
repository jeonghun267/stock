from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_buy_entry_v1 import CommonBuyEntryGate


class CommonBuyEntryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 8, 4, 9, 30, 0)
        self.signal = {
            "signal_id": "s02:089030:1",
            "code": "089030",
            "price": 101.0,
            "anchor_low": 100.0,
            "spread_bps": 10.0,
            "microprice_edge_bps": -1.0,
            "best_bid_share": 0.35,
        }

    @staticmethod
    def sample(ts, price, buy, sell, buy_vol, sell_vol, che, *, strong=False):
        row = {
            "ts": ts,
            "price": price,
            "buy_money_cum": buy,
            "sell_money_cum": sell,
            "buy_vol_cum": buy_vol,
            "sell_vol_cum": sell_vol,
            "che_str": che,
        }
        if strong:
            row.update({
                "best_ask_px": 100.1,
                "best_bid_px": 100.0,
                "best_ask_qty": 100,
                "best_bid_qty": 300,
            })
        return row

    def test_strong_book_enters_without_retest(self) -> None:
        gate = CommonBuyEntryGate()
        market = self.sample(self.start, 101, 0, 0, 0, 0, 90, strong=True)
        decision = gate.evaluate("S02_LOW_BUY_SELL_EXHAUSTION", self.signal, market)
        self.assertTrue(decision.ready)
        self.assertEqual(decision.reason, "COMMON_BUY_BOOK_READY")

    def test_weak_book_waits_for_low_retest_and_two_buy_turn_ticks(self) -> None:
        gate = CommonBuyEntryGate()
        buy = sell = buy_vol = sell_vol = 0.0
        decision = gate.evaluate(
            "S02_LOW_BUY_SELL_EXHAUSTION",
            self.signal,
            self.sample(self.start, 101, buy, sell, buy_vol, sell_vol, 90),
        )
        self.assertEqual(decision.reason, "COMMON_BUY_WEAK_BOOK_RETEST_WAIT")

        for sec in range(1, 21):
            buy += 10
            sell += 30
            buy_vol += 1
            sell_vol += 3
            decision = gate.evaluate(
                "S02_LOW_BUY_SELL_EXHAUSTION",
                self.signal,
                self.sample(
                    self.start + timedelta(seconds=sec),
                    100.5,
                    buy,
                    sell,
                    buy_vol,
                    sell_vol,
                    90 - sec * 0.2,
                ),
            )
            self.assertTrue(decision.waiting)

        buy += 10
        sell += 30
        buy_vol += 1
        sell_vol += 3
        gate.evaluate(
            "S02_LOW_BUY_SELL_EXHAUSTION",
            self.signal,
            self.sample(
                self.start + timedelta(seconds=21),
                100.0,
                buy,
                sell,
                buy_vol,
                sell_vol,
                85,
            ),
        )

        ready = None
        for sec in range(22, 34):
            buy += 100
            sell += 5
            buy_vol += 10
            sell_vol += 1
            decision = gate.evaluate(
                "S02_LOW_BUY_SELL_EXHAUSTION",
                self.signal,
                self.sample(
                    self.start + timedelta(seconds=sec),
                    100.05,
                    buy,
                    sell,
                    buy_vol,
                    sell_vol,
                    85 + (sec - 21),
                ),
            )
            if decision.ready:
                ready = decision
                break

        self.assertIsNotNone(ready)
        self.assertEqual(ready.reason, "COMMON_BUY_RETEST_FLOW_CONFIRMED")
        self.assertEqual(ready.signal["price"], 100.05)
        self.assertEqual(ready.signal["common_buy_retest_price"], 100.0)
        self.assertEqual(ready.signal["common_buy_confirm_ticks"], 2)

    def test_sideways_base_breakout_is_excluded(self) -> None:
        gate = CommonBuyEntryGate()
        decision = gate.evaluate("S05_BASE_BREAKOUT", self.signal, {})
        self.assertTrue(decision.ready)
        self.assertEqual(decision.status, "BYPASS")
        self.assertEqual(decision.reason, "COMMON_BUY_SIDEWAYS_EXCLUDED")


if __name__ == "__main__":
    unittest.main()

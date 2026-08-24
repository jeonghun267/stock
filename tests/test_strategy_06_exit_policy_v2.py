import sys
import unittest
from dataclasses import replace
from datetime import time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_exit_policy_v2 import ExitObservation, decide_exit


class Strategy06ExitPolicyV2Test(unittest.TestCase):
    def setUp(self):
        self.base = ExitObservation(
            price=101.0, entry_price=100.0, anchor_low=99.0, peak_price=102.0,
            atr_3m_pct=0.4, ma5=100.5, ma5_prev=100.4, ma10=100.0,
            buy_rate_10s=100.0, sell_rate_10s=80.0, buy_side_alive=True,
            buy_ratio_10s=0.56,
        )

    def test_hard_stop_and_take_profit(self):
        self.assertEqual(decide_exit(replace(self.base, price=97.9)).reason, "HARD_STOP_2")
        self.assertEqual(decide_exit(replace(self.base, price=105.0)).reason, "TAKE_PROFIT_5")

    def test_anchor_and_ma_break_need_sell_flow(self):
        anchor = replace(
            self.base, price=98.8, buy_rate_10s=100, sell_rate_10s=160,
            anchor_break_sec=3.0)
        self.assertEqual(decide_exit(anchor).reason, "ANCHOR_LOW_BREAK_FLOW_3S")
        ma10 = replace(
            self.base, price=99.8, anchor_low=98.0, ma10=100.0,
            buy_rate_10s=100, sell_rate_10s=160)
        self.assertEqual(decide_exit(ma10).reason, "MA10_BREAK_SELL_FLOW")

    def test_90_percent_is_only_a_five_second_grace(self):
        trailing = replace(
            self.base, price=101.0, peak_price=103.0, ma5=100.5,
            ma5_prev=100.4, ma10=100.0, buy_rate_10s=900,
            sell_rate_10s=100, buy_ratio_10s=0.90, flow_grace_sec=4.9)
        self.assertEqual(decide_exit(trailing).action, "HOLD")
        self.assertEqual(
            decide_exit(replace(trailing, flow_grace_sec=5.0)).reason,
            "MA_FLOW_ATR_TRAIL")

    def test_close_protection_requires_full_trend_support(self):
        weak = replace(self.base, observed_time=time(15, 10), ma5=101.5)
        self.assertEqual(decide_exit(weak).reason, "CLOSE_PROTECT_1510")


if __name__ == "__main__":
    unittest.main()

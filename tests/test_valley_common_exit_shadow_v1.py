# -*- coding: utf-8 -*-

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
sys.path.insert(0, str(RUN_DIR))
KST = ZoneInfo("Asia/Seoul")

from captain2_common_hold_sell_v1 import (  # noqa: E402
    HoldSellObservation,
    HoldSellState,
    StrategyId,
)
from valley_common_exit_shadow_v1 import (  # noqa: E402
    SideWindows,
    completed_structure_low,
    choose_rates,
    force_0930,
    net_before_slippage,
)


class ValleyCommonExitShadowTest(unittest.TestCase):
    def test_side_window_uses_only_past_samples(self):
        rows = SideWindows()
        rows.add("000001", datetime(2026, 7, 27, 9, 0, 0), 100.0, 100.0)
        rows.add("000001", datetime(2026, 7, 27, 9, 0, 10), 300.0, 200.0)
        self.assertEqual(rows.rates("000001", 10), (20.0, 10.0))
        self.assertIsNone(rows.rates("000001", 30))

    def test_flow_warmup_is_neutral(self):
        buy, sell, ratio, quality = choose_rates(None, None)
        self.assertEqual((buy, sell, ratio, quality), (0.0, 0.0, 0.60, "FLOW_WARMUP"))

    def test_0930_cap_latches_without_order(self):
        state = HoldSellState(
            position_id="shadow-1",
            strategy_id=StrategyId.BASE,
            code="000001",
            quantity=1,
            entry_price=Decimal("10000"),
            entry_at=datetime(2026, 7, 27, 9, 5, 0, tzinfo=KST),
        )
        before = HoldSellObservation(
            observed_at=datetime(2026, 7, 27, 9, 29, 59, tzinfo=KST),
            price=Decimal("10100"),
        )
        at_cap = HoldSellObservation(
            observed_at=datetime(2026, 7, 27, 9, 30, 0, tzinfo=KST),
            price=Decimal("10200"),
        )
        self.assertFalse(force_0930(state, before))
        self.assertTrue(force_0930(state, at_cap))
        self.assertEqual(state.sell_reason, "TIME_EXIT_0930")
        self.assertEqual(state.sell_latched_price, Decimal("10200"))

    def test_costs_are_included_but_slippage_is_not(self):
        value = net_before_slippage(Decimal("10000"), Decimal("10100"))
        self.assertAlmostEqual(float(value), 0.7879, places=3)


    def test_completed_structure_reads_live_nested_bar_map(self):
        bars = {"hm": "0905", "m": {"000001": {"prev": [
            [100, 101, 99, 100], [100, 102, 98, 101], [101, 103, 97, 102],
        ]}}}
        self.assertEqual(completed_structure_low(bars, "000001"), 97.0)

    def test_live_morning_block_delegates_to_common_engine_only(self):
        source = (RUN_DIR / "valley_hunter_live_v1.py").read_text(encoding="utf-8")
        start = source.index('if s.get("entry_gate") == "MORNING_CRASH":')
        end = source.index('elif s.get("entry_gate") == "BASE_BREAKOUT":', start)
        block = source[start:end]
        self.assertIn("_common_exit_decide", block)
        self.assertNotIn("_morning_structure_break", block)
        self.assertIn("MORNING_EXIT_HM", block)
        self.assertIn("MORNING_STOP_PCT", block)

if __name__ == "__main__":
    unittest.main()

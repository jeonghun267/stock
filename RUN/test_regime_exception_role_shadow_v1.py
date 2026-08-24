# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regime_exception_role_shadow_v1 import (
    RegimeRoleObservation,
    RegimeExceptionShadowLedger,
    classify_regime_role,
)


def obs(**changes):
    values = dict(
        ts=datetime(2026, 8, 21, 9, 10), code="123456",
        market_pct=-4.0, market_age_sec=1.0,
        price=10100.0, open_price=10000.0, previous_close=10000.0,
        day_low=9900.0, rebound_pct=2.0, no_new_low_sec=60.0,
        flow_turn=True, che_rising=True, order_book_fresh=True,
        spread_bps=20.0, best_bid_share=0.60, vi_suspect=False,
        high_range_rank=10, money_speed_ratio=3.2, turnover_pct=0.35,
        volatility_quality="GOOD",
        stock_age_sec=1.0, flow_age_sec=1.0, high_range_age_sec=1.0,
        exact_flow=True,
        s01_strategy_ready=True, s02_strategy_ready=True, s03_strategy_ready=True,
        market_recovery_state="AMBER", market_recovery_age_sec=600.0,
        market_source="kosdaq_index.json", stock_source="live_micro_snapshot.json",
        flow_source="micro_rank_board.json", high_range_source="common_high_range_live_state.json",
    )
    values.update(changes)
    return RegimeRoleObservation(**values)


class RegimeExceptionRoleShadowTest(unittest.TestCase):
    def test_s01_leader_has_no_rebound_cap(self):
        result = classify_regime_role(obs(rebound_pct=12.0))
        self.assertEqual(result["role"], "S01_CRASH_RS_LEADER")
        self.assertEqual(result["order_qty"], 0)
        self.assertFalse(result["live_eligible"])

    def test_s03_requires_actual_deep_day_low(self):
        result = classify_regime_role(obs(
            price=9200.0, open_price=9800.0, day_low=8900.0,
            rebound_pct=1.5, no_new_low_sec=65.0,
        ))
        self.assertEqual(result["role"], "S03_DEEP_CRASH_REVERSAL")

    def test_s02_can_classify_opening_crash_recovery_after_s01_s03_miss(self):
        result = classify_regime_role(obs(
            ts=datetime(2026, 8, 21, 9, 10),
            market_pct=-8.0, price=9500.0, open_price=9800.0,
            day_low=9400.0, rebound_pct=1.2, no_new_low_sec=90.0,
        ))
        self.assertEqual(result["role"], "S02_SLOW_CRASH_RECOVERY")

    def test_s02_owns_moderate_negative_recovery(self):
        result = classify_regime_role(obs(
            ts=datetime(2026, 8, 21, 10, 0),
            market_pct=-8.0, price=9500.0, open_price=9800.0,
            day_low=9400.0, rebound_pct=1.2, no_new_low_sec=90.0,
        ))
        self.assertEqual(result["role"], "S02_SLOW_CRASH_RECOVERY")

    def test_common_gate_failure_stays_order_zero(self):
        result = classify_regime_role(obs(market_age_sec=400.0))
        self.assertEqual(result["role"], "NONE")
        self.assertIn("MARKET_STALE", result["reason"])
        self.assertEqual(result["order_qty"], 0)

    def test_existing_strategy_gate_is_required(self):
        result = classify_regime_role(obs(s01_strategy_ready=False))
        self.assertEqual(result["role"], "NONE")
        self.assertIn("S01_FINAL_GATE_WAIT", result["reason"])

    def test_non_finite_input_fails_closed(self):
        result = classify_regime_role(obs(spread_bps=math.nan))
        self.assertEqual(result["role"], "NONE")
        self.assertIn("NON_FINITE_INPUT", result["reason"])

    def test_daily_single_slot_and_reentry_block(self):
        ledger = RegimeExceptionShadowLedger()
        rows = ledger.select([obs(code="222222"), obs(code="111111")])
        chosen = [row for row in rows if row["shadow_selected"]]
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["code"], "111111")
        again = ledger.select([obs(code="111111")])
        self.assertFalse(again[0]["shadow_selected"])
        self.assertEqual(again[0]["selection_reason"], "REENTRY_BLOCK")


if __name__ == "__main__":
    unittest.main()

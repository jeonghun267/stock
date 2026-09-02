from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "RUN"))

from strategy_03_flow_turn_fast_v1 import (  # noqa: E402
    BottomConfirmConfig,
    FlowTurnFastConfig,
    SellerExhaustionFastConfig,
    bottom_confirm_decision,
    seller_exhaustion_fast_decision,
)


class BottomConfirmTest(unittest.TestCase):
    def decide(self, **overrides):
        values = {
            "entry_lane": "EARLY_LOW",
            "signal_reason": "S03_EARLY_60S_LOW_REBOUND",
            "rebound_pct": 1.30,
            "regime_band": "BULL",
            "observe_sec": 0.0,
            "reset_steps": 0,
            "pullback_depth_pct": 0.0,
            "higher_low_pct": 0.0,
            "second_rebound_pct": 0.0,
            "recent_buy_rate": 130.0,
            "recent_sell_rate": 70.0,
            "baseline_buy_rate": 100.0,
            "baseline_sell_rate": 100.0,
            "price_responding": True,
            "microprice_edge_bps": 1.0,
            "best_bid_share": 0.60,
            "spread_bps": 20.0,
        }
        values.update(overrides)
        return bottom_confirm_decision(**values)

    def test_tested_constants_are_locked(self):
        self.assertEqual(FlowTurnFastConfig(), FlowTurnFastConfig(
            sell_deceleration_ratio=0.80,
            buy_acceleration_ratio=1.20,
            min_flow_score=2,
            min_best_bid_share=0.50,
            max_spread_bps=35.0,
        ))
        self.assertEqual(BottomConfirmConfig().strong_max_rebound_pct, 1.50)
        self.assertEqual(BottomConfirmConfig().retest_max_rebound_pct, 2.00)
        self.assertEqual(BottomConfirmConfig().weak_min_observe_sec, 300.0)

    def test_strong_direct_requires_exact_flow_gate(self):
        self.assertTrue(self.decide()["ready"])
        self.assertFalse(self.decide(best_bid_share=0.49)["ready"])
        self.assertFalse(self.decide(rebound_pct=1.51)["ready"])

    def test_bottom_shadow_requires_sell_deceleration(self):
        result = self.decide(recent_sell_rate=90.0)
        self.assertEqual(result["flow_score"], 2)
        self.assertTrue(result["flow_ready"])
        self.assertFalse(result["seller_exhausted"])
        self.assertFalse(result["ready"])

    def test_unknown_uses_existing_bottom_and_flow_checks(self):
        ready = self.decide(regime_band="UNKNOWN")
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["route"], "UNKNOWN_FALLBACK")
        self.assertFalse(self.decide(
            regime_band="UNKNOWN", best_bid_share=0.49
        )["ready"])
        self.assertFalse(self.decide(
            regime_band="UNKNOWN", rebound_pct=1.51
        )["ready"])

    def test_normal_requires_staircase_higher_low_retest(self):
        ready = self.decide(
            entry_lane="OPEN_CRASH",
            signal_reason="S06_STAIRCASE+PULLBACK+HIGHER_LOW+SECOND_REBOUND+BUY_SPEED_LEAD",
            regime_band="GRAY",
            rebound_pct=1.50,
            pullback_depth_pct=0.40,
            higher_low_pct=0.30,
            second_rebound_pct=0.50,
        )
        self.assertTrue(ready["ready"])
        self.assertFalse(self.decide(regime_band="GRAY")["ready"])

    def test_weak_requires_300_seconds_and_new_low_reset(self):
        base = {
            "entry_lane": "OPEN_CRASH",
            "signal_reason": "S06_STAIRCASE+PULLBACK+HIGHER_LOW+SECOND_REBOUND+BUY_SPEED_LEAD",
            "regime_band": "BEAR",
            "rebound_pct": 1.50,
            "pullback_depth_pct": 0.40,
            "higher_low_pct": 0.30,
            "second_rebound_pct": 0.50,
            "observe_sec": 300.0,
            "reset_steps": 1,
        }
        self.assertTrue(self.decide(**base)["ready"])
        self.assertFalse(self.decide(**{**base, "observe_sec": 299.9})["ready"])
        self.assertFalse(self.decide(**{**base, "reset_steps": 0})["ready"])

    def test_seller_exhaustion_fast_allows_weak_buy_price_response(self):
        result = seller_exhaustion_fast_decision(
            rapid_drop_pct=0.70,
            rebound_pct=0.70,
            sell_rate_old=100.0,
            sell_rate_mid=70.0,
            sell_rate_now=50.0,
            price_up_ticks=2,
            ask_depleting=True,
            best_bid_share=0.60,
            spread_bps=20.0,
            microprice_edge_bps=1.0,
            new_low=False,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["action"], "SELLER_EXHAUSTION_FAST_READY")

    def test_seller_exhaustion_fast_resets_on_sell_burst_or_chase(self):
        base = dict(
            rapid_drop_pct=0.70,
            rebound_pct=0.70,
            sell_rate_old=100.0,
            sell_rate_mid=70.0,
            sell_rate_now=50.0,
            price_up_ticks=2,
            ask_depleting=True,
            best_bid_share=0.60,
            spread_bps=20.0,
            microprice_edge_bps=1.0,
            new_low=False,
        )
        self.assertFalse(seller_exhaustion_fast_decision(
            **{**base, "sell_rate_now": 90.0}
        )["ready"])
        self.assertFalse(seller_exhaustion_fast_decision(
            **{**base, "rebound_pct": 1.51}
        )["ready"])
        self.assertFalse(seller_exhaustion_fast_decision(
            **{**base, "new_low": True}
        )["ready"])
        self.assertEqual(
            SellerExhaustionFastConfig().min_rapid_drop_pct,
            0.60,
        )


if __name__ == "__main__":
    unittest.main()

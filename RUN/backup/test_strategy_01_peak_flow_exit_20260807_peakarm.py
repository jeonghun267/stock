from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    STRATEGY_PROFILES,
    StrategyId,
    UnifiedHoldSellEngine,
)

KST = timezone(timedelta(hours=9))


class Strategy01PeakFlowExitTests(unittest.TestCase):
    def setUp(self):
        self.engine = UnifiedHoldSellEngine()
        self.start = datetime(2026, 8, 3, 10, 0, tzinfo=KST)

    def state(self, quantity=1, strategy=StrategyId.S01_OPEN_SURGE):
        return HoldSellState(
            position_id="s01-peak-test",
            strategy_id=strategy,
            code="108490",
            quantity=quantity,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )

    def obs(self, seconds, price, **overrides):
        values = {
            "observed_at": self.start + timedelta(seconds=seconds),
            "price": Decimal(str(price)),
            "buy_money_per_sec_10s": Decimal("100"),
            "sell_money_per_sec_10s": Decimal("200"),
            "buy_money_per_sec_30s": Decimal("200"),
            "sell_money_per_sec_30s": Decimal("100"),
            "buy_volume_per_sec_5s": Decimal("100"),
            "sell_volume_per_sec_5s": Decimal("200"),
            "sell_volume_per_sec_previous_10s": Decimal("100"),
            "one_minute_bull_to_bear": True,
            "common_peak_flow_ready": True,
        }
        values.update(overrides)
        return HoldSellObservation(**values)

    def test_all_profiles_enable_common_peak_flow_rule(self):
        enabled = [
            strategy for strategy, profile in STRATEGY_PROFILES.items()
            if profile.common_peak_flow_exit_enabled
        ]
        self.assertEqual(set(enabled), set(StrategyId))

    def test_same_common_reversal_rule_applies_to_live_strategies(self):
        for strategy in (
            StrategyId.S01_OPEN_SURGE,
            StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            StrategyId.S04_PULLBACK,
            StrategyId.S05_BASE_BREAKOUT,
        ):
            with self.subTest(strategy=strategy):
                state = self.state(strategy=strategy)
                self.engine.evaluate(
                    state, self.obs(0, "107", one_minute_bull_to_bear=False))
                self.engine.evaluate(state, self.obs(1, "105.90"))
                sold = self.engine.evaluate(state, self.obs(4, "105.90"))
                self.assertEqual(sold.action, HoldSellAction.SELL)
                self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_profit_trail_is_disabled_for_standard_profiles(self):
        s01_profile = STRATEGY_PROFILES[StrategyId.S01_OPEN_SURGE]
        self.assertFalse(s01_profile.profit_trail_enabled)
        self.assertIsNone(s01_profile.stop_ladder)
        self.assertIsNone(s01_profile.trail_steps)
        self.assertFalse(
            STRATEGY_PROFILES[
                StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
            ].profit_trail_enabled)

        state = self.state()
        state.peak_price = Decimal("106")
        decision = self.engine._profit_trail_rule(
            state,
            self.obs(
                200, "102.5",
                common_peak_flow_ready=False,
                one_minute_bearish=True,
                buy_money_per_sec_10s=Decimal("50"),
                sell_money_per_sec_10s=Decimal("200"),
                buy_money_per_sec_30s=Decimal("100"),
                sell_money_per_sec_30s=Decimal("100"),
                buy_volume_per_sec_5s=Decimal("100"),
                sell_volume_per_sec_5s=Decimal("200"),
                sell_volume_per_sec_previous_10s=Decimal("100"),
                che_str=Decimal("120"),
            ),
            STRATEGY_PROFILES[StrategyId.S01_OPEN_SURGE],
        )
        self.assertIsNone(decision)

    def test_plus_four_peak_flow_needs_two_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "104", one_minute_bull_to_bear=False))
        watch = self.engine.evaluate(state, self.obs(1, "102.70"))
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(state, self.obs(3, "102.70"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_rising_hold_blocks_peak_flow_until_ma_support_breaks(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "104", one_minute_bull_to_bear=False))
        held = self.engine.evaluate(
            state, self.obs(1, "102.70", daily_ma_permit=True))
        self.assertEqual(held.action, HoldSellAction.HOLD)
        self.assertIn("COMMON_RISING_HOLD", held.reason)
        self.assertIsNone(state.peak_flow_since)
        watch = self.engine.evaluate(state, self.obs(2, "102.70"))
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(
            state, self.obs(4, "102.70"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_sell_speed_break_resets_confirmation_timer(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "104", one_minute_bull_to_bear=False))
        self.engine.evaluate(state, self.obs(1, "102.70"))
        reset = self.engine.evaluate(
            state,
            self.obs(
                6,
                "102.70",
                buy_money_per_sec_10s=Decimal("300"),
                sell_money_per_sec_10s=Decimal("200"),
            ),
        )
        self.assertEqual(reset.action, HoldSellAction.WATCH)
        reset_done = self.engine.evaluate(
            state,
            self.obs(
                12,
                "102.70",
                buy_money_per_sec_10s=Decimal("300"),
                sell_money_per_sec_10s=Decimal("200"),
            ),
        )
        self.assertEqual(reset_done.action, HoldSellAction.HOLD)
        self.assertIn("RESET_BUY_SPEED_RECOVERED", reset_done.reason)
        restarted = self.engine.evaluate(state, self.obs(18, "102.70"))
        self.assertEqual(restarted.action, HoldSellAction.WATCH)
        self.assertIn("COMMON_PEAK_FLOW_WATCH", restarted.reason)

    def test_two_shares_sell_all_at_first_confirmed_exit(self):
        state = self.state(quantity=2)
        self.engine.evaluate(state, self.obs(0, "104", one_minute_bull_to_bear=False))
        self.engine.evaluate(state, self.obs(1, "102.70"))
        sold = self.engine.evaluate(state, self.obs(4, "102.70"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_mid_profit_pullback_does_not_trigger_full_insurance(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "104", one_minute_bull_to_bear=False))
        held = self.engine.evaluate(
            state,
            self.obs(
                1,
                "101.70",
                one_minute_bull_to_bear=False,
                one_minute_bearish=True,
                daily_ma5_broken=True,
            ),
        )
        self.assertFalse(held.should_sell)
        self.assertFalse(state.sell_latched)

    def test_below_four_positive_under_two_does_not_defense_sell(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "103", one_minute_bull_to_bear=False))
        self.engine.evaluate(state, self.obs(1, "100.90"))
        held = self.engine.evaluate(state, self.obs(7, "100.90"))
        self.assertFalse(held.should_sell)

    def test_below_four_profit_needs_structure_break_for_five_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "103.90", one_minute_bull_to_bear=False))
        held = self.engine.evaluate(state, self.obs(1, "102.20"))
        self.assertFalse(held.should_sell)
        watch = self.engine.evaluate(
            state, self.obs(2, "102.20", structure_broken=True))
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(
            state, self.obs(7, "102.20", structure_broken=True))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_FLOW_DEFENSE_EXIT", sold.reason)

    def test_below_entry_defense_sell_needs_five_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "103", one_minute_bull_to_bear=False))
        self.engine.evaluate(state, self.obs(1, "99.80"))
        sold = self.engine.evaluate(state, self.obs(6, "99.80"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_FLOW_DEFENSE_EXIT", sold.reason)

    def test_high_profit_uses_same_two_second_common_flow_rule(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "108", one_minute_bull_to_bear=False))
        watch = self.engine.evaluate(
            state, self.obs(1, "106.90"),
        )
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(
            state, self.obs(3, "106.90"),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_high_profit_price_drop_without_flow_does_not_sell(self):
        state = self.state(quantity=2)
        self.engine.evaluate(state, self.obs(0, "108", one_minute_bull_to_bear=False))
        held = self.engine.evaluate(
            state,
            self.obs(
                1,
                "106.50",
                buy_money_per_sec_10s=Decimal("300"),
                sell_money_per_sec_10s=Decimal("200"),
            ),
        )
        self.assertFalse(held.should_sell)
        self.assertFalse(state.sell_latched)

    def test_explicit_gate_off_disables_peak_flow_rule(self):
        state = self.state()
        self.engine.evaluate(
            state,
            self.obs(
                0,
                "104",
                one_minute_bull_to_bear=False,
                common_peak_flow_ready=False,
            ),
        )
        decision = self.engine.evaluate(
            state,
            self.obs(1, "101.92", common_peak_flow_ready=False),
        )
        self.assertFalse(decision.should_sell)
        self.assertFalse(state.sell_latched)


if __name__ == "__main__":
    unittest.main()

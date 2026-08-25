from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellConfig,
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

    def test_s02_supported_weak_reversal_candidate_needs_six_seconds(self):
        state = self.state(strategy=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION)
        candidate = replace(
            STRATEGY_PROFILES[StrategyId.S02_LOW_BUY_SELL_EXHAUSTION],
            supported_weak_peak_confirm_sec=6,
            supported_weak_peak_active_date="*",
            supported_weak_peak_arm_return_pct=Decimal("5"),
            supported_weak_peak_drop_pct=Decimal("1.5"),
            supported_weak_peak_score=3,
        )
        weak_supported = {
            "ma10_support": True,
            "ma20_rising": True,
        }
        with patch.dict(
            STRATEGY_PROFILES,
            {StrategyId.S02_LOW_BUY_SELL_EXHAUSTION: candidate},
        ):
            self.engine.evaluate(state, self.obs(0, "106", **weak_supported))
            started = self.engine.evaluate(
                state, self.obs(1, "104.30", **weak_supported))
            still_watching = self.engine.evaluate(
                state, self.obs(3, "104.30", **weak_supported))
            sold = self.engine.evaluate(
                state, self.obs(7, "104.30", **weak_supported))

        self.assertEqual(started.action, HoldSellAction.WATCH)
        self.assertEqual(still_watching.action, HoldSellAction.WATCH)
        self.assertIn("2/6s", still_watching.reason)
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("S02_PEAK_5_DROP_1P5_FLOW_3OF4_EXIT", sold.reason)

    def test_s02_six_second_candidate_is_not_live_by_default(self):
        profile = STRATEGY_PROFILES[
            StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
        ]
        self.assertIsNone(profile.supported_weak_peak_confirm_sec)

    def test_s02_strong_reversal_keeps_two_second_confirmation(self):
        state = self.state(strategy=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION)
        strong_supported = {
            "one_minute_bull_to_bear": False,
            "one_minute_bearish": False,
            "ma10_support": True,
            "ma20_rising": True,
        }
        self.engine.evaluate(state, self.obs(0, "104", **strong_supported))
        self.engine.evaluate(state, self.obs(1, "102.70", **strong_supported))
        sold = self.engine.evaluate(state, self.obs(3, "102.70", **strong_supported))

        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("score=3/4", sold.reason)

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

    def test_s01_profitable_rising_ma5_and_ma10_support_blocks_peak_flow(self):
        self.engine = UnifiedHoldSellEngine(
            HoldSellConfig(s01_ma5_trend_hold_active_date="*"))
        state = self.state()
        self.engine.evaluate(
            state, self.obs(0, "104", one_minute_bull_to_bear=False))
        held = self.engine.evaluate(
            state,
            self.obs(
                1,
                "102.70",
                daily_ma5_broken=False,
                ma5_rising=True,
                ma10_support=True,
            ),
        )
        self.assertEqual(held.action, HoldSellAction.HOLD)
        self.assertEqual(held.reason, "S01_MA5_TREND_HOLD")
        self.assertIsNone(state.peak_flow_since)

    def test_s01_ma5_trend_hold_releases_after_ma5_break(self):
        self.engine = UnifiedHoldSellEngine(
            HoldSellConfig(s01_ma5_trend_hold_active_date="*"))
        state = self.state()
        self.engine.evaluate(
            state, self.obs(0, "104", one_minute_bull_to_bear=False))
        self.engine.evaluate(
            state,
            self.obs(
                1,
                "102.70",
                ma5_rising=True,
                ma10_support=True,
            ),
        )
        watch = self.engine.evaluate(
            state,
            self.obs(
                2,
                "102.70",
                daily_ma5_broken=True,
                ma5_rising=True,
                ma10_support=True,
            ),
        )
        self.assertEqual(watch.action, HoldSellAction.WATCH)

    def test_ma5_trend_hold_does_not_change_other_strategies(self):
        state = self.state(strategy=StrategyId.S04_PULLBACK)
        self.engine.evaluate(
            state, self.obs(0, "104", one_minute_bull_to_bear=False))
        self.engine.evaluate(
            state,
            self.obs(1, "102.70", ma5_rising=True, ma10_support=True),
        )
        sold = self.engine.evaluate(
            state,
            self.obs(4, "102.70", ma5_rising=True, ma10_support=True),
        )
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

    # ★[PEAK-ARM 2026-08-07] 꼭지무장 4.0 → 2.0 에 맞춰 아래 3개 시험을 교체했다.
    #   종전 시험은 "꼭지 +4% 미만 = 방어매도 영역"을 전제로 꼭지 +3~3.9% 표본을 썼는데,
    #   이제 그 구간은 꼭지매도 영역이다. 시험이 지키려던 내용(무장 미만에서의 방어 규칙)은
    #   꼭지 +1.5% 표본으로 그대로 유지한다. 원본: RUN\backup\test_..._20260807_peakarm.py

    def test_below_arm_positive_under_two_does_not_defense_sell(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "101.5", one_minute_bull_to_bear=False))
        self.engine.evaluate(state, self.obs(1, "100.90"))
        held = self.engine.evaluate(state, self.obs(7, "100.90"))
        self.assertFalse(held.should_sell)

    def test_two_to_four_profit_pullback_now_sells_via_peak_flow(self):
        """종전 '이익방어(구조붕괴+5초)' 시험 자리. 무장이 2.0 이 되면서 꼭지수익 +2~4%
        구간은 꼭지매도(되돌림 0.8%+수급 2점+2초)가 먼저 덮는다 — 더 빠르고 조건이 낮다.
        ⚠️부수 효과: 이익방어 분기(꼭지수익<무장 AND 수익>=2%)는 산수상 불가능해져
        죽은 코드가 됐다(꼭지수익>=현재수익 이므로). memory.md 8/7 밤 기록 참조."""
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "103.90", one_minute_bull_to_bear=False))
        watch = self.engine.evaluate(state, self.obs(1, "102.20"))
        self.assertFalse(watch.should_sell)
        sold = self.engine.evaluate(state, self.obs(7, "102.20"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("COMMON_PEAK_FLOW_EXIT", sold.reason)

    def test_below_entry_defense_sell_needs_five_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, "101.5", one_minute_bull_to_bear=False))
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

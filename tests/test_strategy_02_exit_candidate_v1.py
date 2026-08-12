from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from strategy_02_exit_candidate_v1 import Strategy02ExitCandidateEngine
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellConfig,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)


KST = timezone(timedelta(hours=9))


class Strategy02ExitCandidateTests(unittest.TestCase):
    def setUp(self):
        self.engine = Strategy02ExitCandidateEngine()
        self.start = datetime(2026, 8, 10, 13, 36, tzinfo=KST)
        self.state = HoldSellState(
            position_id="s02-soft-loss-shadow",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="126730",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )

    def obs(self, seconds, price="98.8", **overrides):
        values = {
            "observed_at": self.start + timedelta(seconds=seconds),
            "price": Decimal(price),
            "buy_money_per_sec_10s": Decimal("100"),
            "sell_money_per_sec_10s": Decimal("300"),
            "daily_ma5_broken": True,
            "structure_broken": True,
            "one_minute_bearish": True,
            "common_peak_flow_ready": True,
        }
        values.update(overrides)
        return HoldSellObservation(**values)

    def test_persistent_soft_loss_flow_break_exits_after_three_seconds(self):
        watch = self.engine.evaluate(self.state, self.obs(0))
        sold = self.engine.evaluate(self.state, self.obs(4, "98.7"))
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("S02_SOFT_LOSS_FLOW_EXIT", sold.reason)

    def test_recovery_above_minus_one_resets_soft_loss_timer(self):
        self.engine.evaluate(self.state, self.obs(0))
        peak_timer = self.start - timedelta(seconds=1)
        self.state.peak_lock_since = peak_timer
        recovered = self.engine.evaluate(self.state, self.obs(2, "99.2"))
        restarted = self.engine.evaluate(self.state, self.obs(5))
        self.assertFalse(recovered.should_sell)
        self.assertEqual(self.state.peak_lock_since, peak_timer)
        self.assertEqual(restarted.action, HoldSellAction.WATCH)
        self.assertIn("0/3s", restarted.reason)

    def test_rising_ma20_defense_blocks_soft_loss_candidate(self):
        held = self.engine.evaluate(
            self.state,
            self.obs(0, ma20_defense_permit=True, ma20_rising=True),
        )
        self.assertFalse(held.should_sell)
        self.assertNotIn("SOFT_LOSS", held.reason)

    def test_morning_soft_loss_does_not_cut_a_later_recovery(self):
        self.state.entry_at = self.start.replace(hour=9, minute=0)
        morning = HoldSellObservation(
            **{
                **self.obs(0).__dict__,
                "observed_at": self.start.replace(hour=9, minute=30),
            }
        )
        held = self.engine.evaluate(self.state, morning)
        self.assertFalse(held.should_sell)
        self.assertNotIn("SOFT_LOSS", held.reason)

    def test_production_switch_is_off_by_default(self):
        engine = UnifiedHoldSellEngine(HoldSellConfig(
            s02_afternoon_soft_loss_enabled=False,
        ))
        state = self.state
        engine.evaluate(state, self.obs(0))
        decision = engine.evaluate(state, self.obs(4, "98.7"))
        self.assertFalse(decision.should_sell)
        self.assertNotIn("SOFT_LOSS", decision.reason)

    def test_production_switch_uses_same_confirmed_soft_exit(self):
        engine = UnifiedHoldSellEngine(HoldSellConfig(
            s02_afternoon_soft_loss_enabled=True,
        ))
        state = self.state
        engine.evaluate(state, self.obs(0))
        sold = engine.evaluate(state, self.obs(4, "98.7"))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("S02_SOFT_LOSS_FLOW_EXIT", sold.reason)

    def test_live_launcher_keeps_unverified_candidate_off(self):
        launcher = (
            Path(__file__).resolve().parents[1]
            / "RUN" / "hidden" / "SAFEPLUS_STRATEGY02_LIVE.cmd"
        )
        text = launcher.read_text(encoding="ascii")
        self.assertIn("set S02_AFTERNOON_SOFT_LOSS_EXIT=NO", text)
        self.assertNotIn("set S02_AFTERNOON_SOFT_LOSS_EXIT=YES", text)


if __name__ == "__main__":
    unittest.main()

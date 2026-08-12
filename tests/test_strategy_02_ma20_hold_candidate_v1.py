from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from strategy_02_ma20_hold_candidate_v1 import (
    Strategy02Ma20HoldCandidateEngine,
)
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
)


KST = timezone(timedelta(hours=9))


class Strategy02Ma20HoldCandidateTests(unittest.TestCase):
    def setUp(self):
        self.engine = Strategy02Ma20HoldCandidateEngine()
        self.start = datetime(2026, 8, 10, 9, 0, tzinfo=KST)

    def state(self):
        return HoldSellState(
            position_id="s02-ma20-shadow",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )

    def obs(self, seconds, *, strong=False, ma20=True):
        return HoldSellObservation(
            observed_at=self.start + timedelta(seconds=seconds),
            price=Decimal("104") if seconds == 0 else Decimal("102.7"),
            buy_money_per_sec_10s=Decimal("100"),
            sell_money_per_sec_10s=Decimal("200"),
            buy_money_per_sec_30s=Decimal("200" if strong else "100"),
            sell_money_per_sec_30s=Decimal("100"),
            buy_volume_per_sec_5s=Decimal("100"),
            sell_volume_per_sec_5s=Decimal("200"),
            sell_volume_per_sec_previous_10s=Decimal("100"),
            one_minute_bull_to_bear=not strong,
            common_peak_flow_ready=True,
            ma10_support=False,
            ma20_rising=ma20,
            ma20_defense_permit=ma20,
        )

    def test_weak_ma20_only_support_uses_six_second_confirmation(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0))
        self.engine.evaluate(state, self.obs(1))
        watching = self.engine.evaluate(state, self.obs(3))
        sold = self.engine.evaluate(state, self.obs(7))
        self.assertEqual(watching.action, HoldSellAction.WATCH)
        self.assertIn("2/6s", watching.reason)
        self.assertEqual(sold.action, HoldSellAction.SELL)

    def test_strong_reversal_still_exits_after_two_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, strong=True))
        self.engine.evaluate(state, self.obs(1, strong=True))
        sold = self.engine.evaluate(state, self.obs(3, strong=True))
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("age=2s", sold.reason)

    def test_without_ma20_support_weak_reversal_keeps_two_seconds(self):
        state = self.state()
        self.engine.evaluate(state, self.obs(0, ma20=False))
        self.engine.evaluate(state, self.obs(1, ma20=False))
        sold = self.engine.evaluate(state, self.obs(3, ma20=False))
        self.assertEqual(sold.action, HoldSellAction.SELL)


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_02_trend_lock_shadow_v1 import (
    DONE_KEY,
    Strategy02TrendLockShadow,
)
from strategy_common_hold_sell_v1 import HoldSellObservation, HoldSellState, StrategyId


KST = timezone(timedelta(hours=9))


class Strategy02TrendLockShadowTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.start = datetime(2026, 8, 11, 13, 34, 58, tzinfo=KST)
        state = HoldSellState(
            position_id="s02-trend-lock-shadow",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="463020",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )
        self.position = {
            "code": "463020",
            "name": "shadow-test",
            "entry_price": "100",
            "hold_state": state.to_dict(),
        }
        self.shadow = Strategy02TrendLockShadow(
            lambda event, **payload: self.events.append((event, payload))
        )

    def obs(self, seconds, price, *, strong=True):
        return HoldSellObservation(
            observed_at=self.start + timedelta(seconds=seconds),
            price=Decimal(price),
            buy_money_per_sec_10s=Decimal("100"),
            sell_money_per_sec_10s=Decimal("200" if strong else "100"),
            buy_money_per_sec_30s=Decimal("200"),
            sell_money_per_sec_30s=Decimal("100"),
            buy_volume_per_sec_5s=Decimal("100"),
            sell_volume_per_sec_5s=Decimal("200" if strong else "100"),
            sell_volume_per_sec_previous_10s=Decimal("100"),
            che_str_change_5s=Decimal("-3" if strong else "0"),
            common_peak_flow_ready=True,
        )

    def test_requires_strong_flow_for_six_seconds_and_never_orders(self):
        self.shadow.evaluate(
            self.position, self.obs(0, "106"), above_ma5_ma10_ma20=True,
        )
        self.shadow.evaluate(
            self.position, self.obs(1, "104"), above_ma5_ma10_ma20=True,
        )
        self.shadow.evaluate(
            self.position, self.obs(6, "104"), above_ma5_ma10_ma20=True,
        )
        self.assertFalse(self.position.get(DONE_KEY, False))
        self.shadow.evaluate(
            self.position, self.obs(7, "104"), above_ma5_ma10_ma20=True,
        )
        self.assertTrue(self.position[DONE_KEY])
        sell = self.events[-1]
        self.assertEqual(sell[0], "S02_TREND_LOCK_SHADOW")
        self.assertIn("[HYPOTHETICAL] SELL", sell[1]["reason"])
        self.assertIn("quantity=0", sell[1]["reason"])

    def test_weak_flow_does_not_start_confirmation(self):
        self.shadow.evaluate(
            self.position, self.obs(0, "106"), above_ma5_ma10_ma20=True,
        )
        self.shadow.evaluate(
            self.position,
            self.obs(1, "104", strong=False),
            above_ma5_ma10_ma20=True,
        )
        self.shadow.evaluate(
            self.position,
            self.obs(20, "104", strong=False),
            above_ma5_ma10_ma20=True,
        )
        self.assertFalse(self.position.get(DONE_KEY, False))
        self.assertFalse(any(" SELL " in payload["reason"] for _, payload in self.events))


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_02_six_second_shadow_v1 import (
    DONE_KEY,
    STATE_KEY,
    Strategy02SixSecondShadow,
)
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
)


KST = timezone(timedelta(hours=9))


class Strategy02SixSecondShadowTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.start = datetime(2026, 8, 11, 10, 0, tzinfo=KST)
        state = HoldSellState(
            position_id="s02-six-second-shadow",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="119850",
            quantity=1,
            entry_price=Decimal("100"),
            entry_at=self.start,
        )
        self.position = {
            "code": "119850",
            "name": "shadow-test",
            "hold_state": state.to_dict(),
        }
        self.shadow = Strategy02SixSecondShadow(
            lambda event, **payload: self.events.append((event, payload))
        )

    def obs(self, seconds, price):
        return HoldSellObservation(
            observed_at=self.start + timedelta(seconds=seconds),
            price=Decimal(price),
            buy_money_per_sec_10s=Decimal("100"),
            sell_money_per_sec_10s=Decimal("200"),
            buy_money_per_sec_30s=Decimal("200"),
            sell_money_per_sec_30s=Decimal("100"),
            buy_volume_per_sec_5s=Decimal("100"),
            sell_volume_per_sec_5s=Decimal("200"),
            sell_volume_per_sec_previous_10s=Decimal("100"),
            one_minute_bull_to_bear=True,
            common_peak_flow_ready=True,
            ma10_support=True,
            ma20_rising=True,
        )

    def test_supported_weak_reversal_is_observed_for_six_seconds(self):
        self.shadow.evaluate(self.position, self.obs(0, "106"))
        self.shadow.evaluate(self.position, self.obs(1, "104.3"))
        self.shadow.evaluate(self.position, self.obs(3, "104.3"))
        self.assertFalse(self.position.get(DONE_KEY, False))
        state = HoldSellState.from_dict(self.position[STATE_KEY])
        self.assertEqual(
            state.supported_peak_since, self.start + timedelta(seconds=1)
        )

        self.shadow.evaluate(self.position, self.obs(7, "104.3"))
        self.assertTrue(self.position[DONE_KEY])
        self.assertTrue(any(
            "[HYPOTHETICAL] SELL S02_PEAK_5_DROP_1P5_FLOW_3OF4_EXIT"
            in payload["reason"]
            for _, payload in self.events
        ))

    def test_mid_position_start_fails_closed(self):
        state = HoldSellState.from_dict(self.position["hold_state"])
        state.last_observed_at = self.start
        self.position["hold_state"] = state.to_dict()
        self.shadow.evaluate(self.position, self.obs(1, "100"))
        self.assertTrue(self.position[DONE_KEY])
        self.assertNotIn(STATE_KEY, self.position)
        self.assertIn("[UNVERIFIED]", self.events[-1][1]["reason"])


if __name__ == "__main__":
    unittest.main()

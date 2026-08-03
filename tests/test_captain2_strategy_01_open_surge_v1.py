# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(RUN_DIR))

from captain2_common_hold_sell_v1 import STRATEGY_PROFILES, StrategyId  # noqa: E402
from captain2_strategy_01_open_surge_v1 import (  # noqa: E402
    BuyAction,
    EntryRoute,
    OpenSurgeBuyStrategy,
    OpenSurgeObservation,
    STRATEGY_ID,
    STRATEGY_NUMBER,
)


KST = ZoneInfo("Asia/Seoul")


class Captain2Strategy01OpenSurgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = OpenSurgeBuyStrategy()

    def observation(self, **overrides) -> OpenSurgeObservation:
        values = {
            "observed_at": datetime(2026, 7, 27, 9, 0, 5, tzinfo=KST),
            "code": "123450",
            "previous_close": Decimal("10000"),
            "open_price": Decimal("10000"),
            "current_price": Decimal("10050"),
            "high_so_far": Decimal("10050"),
            "buy_money_ratio": Decimal("0.72"),
            "money_speed_5s": Decimal("2000000"),
            "money_speed_30s": Decimal("0"),
            "price_rising_sec": 3,
            "exact_flow": True,
            "in_prior_value_pool": True,
            "in_premarket_gap_pool": False,
        }
        values.update(overrides)
        return OpenSurgeObservation(**values)

    def test_strategy_number_and_common_exit_profile_are_registered(self):
        self.assertEqual(STRATEGY_NUMBER, 1)
        self.assertEqual(STRATEGY_ID, StrategyId.C2_01_OPEN_SURGE)
        profile = STRATEGY_PROFILES[STRATEGY_ID]
        self.assertEqual(profile.force_exit_at.strftime("%H:%M"), "15:10")
        self.assertIsNone(profile.early_decision_at)

    def test_direct_open_surge_is_buy_ready(self):
        decision = self.strategy.evaluate(self.observation())
        self.assertEqual(decision.action, BuyAction.BUY_READY)
        self.assertEqual(decision.route, EntryRoute.OPEN_SURGE)

    def test_small_positive_gap_is_not_lost(self):
        decision = self.strategy.evaluate(
            self.observation(
                open_price=Decimal("10100"),
                current_price=Decimal("10150"),
                high_so_far=Decimal("10150"),
            )
        )
        self.assertEqual(decision.action, BuyAction.BUY_READY)
        self.assertEqual(decision.route, EntryRoute.OPEN_SURGE)

    def test_three_percent_gap_is_buy_ready_even_outside_prior_pool(self):
        decision = self.strategy.evaluate(
            self.observation(
                open_price=Decimal("10300"),
                current_price=Decimal("10350"),
                high_so_far=Decimal("10350"),
                in_prior_value_pool=False,
            )
        )
        self.assertEqual(decision.action, BuyAction.BUY_READY)
        self.assertEqual(decision.route, EntryRoute.GAP_SURGE)

    def test_non_gap_stock_outside_opening_pool_is_blocked(self):
        decision = self.strategy.evaluate(
            self.observation(in_prior_value_pool=False)
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "NOT_IN_OPENING_POOL")

    def test_prior_three_percent_high_blocks_pullback_chase(self):
        decision = self.strategy.evaluate(
            self.observation(
                current_price=Decimal("10100"), high_so_far=Decimal("10350")
            )
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "CHASE_ABOVE_OPEN_3PCT")

    def test_below_open_path_is_reserved_for_strategy_two(self):
        decision = self.strategy.evaluate(
            self.observation(below_open_seen=True)
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "LOW_BUY_IS_STRATEGY_02")

    def test_exact_flow_and_three_second_rise_are_required(self):
        missing = self.strategy.evaluate(self.observation(exact_flow=False))
        short = self.strategy.evaluate(self.observation(price_rising_sec=2))
        self.assertEqual(missing.reason, "EXACT_FLOW_MISSING")
        self.assertEqual(short.reason, "PRICE_RISE_NOT_PERSISTENT")

    def test_burst_is_waived_only_during_first_thirty_seconds(self):
        weak = self.strategy.evaluate(
            self.observation(
                observed_at=datetime(2026, 7, 27, 9, 0, 30, tzinfo=KST),
                money_speed_30s=Decimal("1000000"),
            )
        )
        strong = self.strategy.evaluate(
            self.observation(
                observed_at=datetime(2026, 7, 27, 9, 0, 30, tzinfo=KST),
                money_speed_5s=Decimal("3000000"),
                money_speed_30s=Decimal("1000000"),
            )
        )
        self.assertEqual(weak.reason, "MONEY_BURST_WEAK")
        self.assertEqual(strong.action, BuyAction.BUY_READY)

    def test_entry_window_ends_before_0920(self):
        decision = self.strategy.evaluate(
            self.observation(
                observed_at=datetime(2026, 7, 27, 9, 20, tzinfo=KST)
            )
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "OUTSIDE_ENTRY_WINDOW")

    def test_theme_leader_is_bonus_not_gate(self):
        plain = self.strategy.evaluate(self.observation(theme_leader=False))
        leader = self.strategy.evaluate(self.observation(theme_leader=True))
        self.assertEqual(plain.action, BuyAction.BUY_READY)
        self.assertEqual(leader.action, BuyAction.BUY_READY)
        self.assertEqual(plain.priority_bonus, 0)
        self.assertEqual(leader.priority_bonus, 1)


if __name__ == "__main__":
    unittest.main()

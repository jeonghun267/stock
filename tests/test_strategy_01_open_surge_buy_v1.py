# -*- coding: utf-8 -*-
"""새전략 01 매수조건 회귀.

★[2026-07-31] 규칙을 "급상승 초입 추격" → "되돌림 진입"으로 교체하면서 갱신.
  옛 검사 2개(시가 밑 내려가면 영구제외 LOW_BUY_IS_STRATEGY_02 ·
  시가+3% 추격금지 CHASE_ABOVE_OPEN_3PCT)는 규칙이 사라져 삭제하고,
  되돌림 3문턱(밀림 -1.5% / 반등 +0.5% / 추격상한 저점+3%) 검사로 대체했다.
  돈흐름 5조건·진입창·유니버스·매도 프로파일 검사는 그대로 유지한다.
"""
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

from strategy_common_hold_sell_v1 import STRATEGY_PROFILES, StrategyId  # noqa: E402
from strategy_01_open_surge_buy_v1 import (  # noqa: E402
    BuyAction,
    EntryRoute,
    OpenSurgeBuyStrategy,
    OpenSurgeObservation,
    STRATEGY_ID,
    STRATEGY_NUMBER,
)


KST = ZoneInfo("Asia/Seoul")


class Strategy01DipReboundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = OpenSurgeBuyStrategy()

    def observation(self, **overrides) -> OpenSurgeObservation:
        """기본 = 되돌림 성립 상태.
        시가 50,000 → 당일저점 49,000(-2.0%) → 현재 49,500(저점 +1.02%)."""
        values = {
            "observed_at": datetime(2026, 7, 27, 9, 0, 5, tzinfo=KST),
            "code": "123450",
            "previous_close": Decimal("50000"),
            "open_price": Decimal("50000"),
            "current_price": Decimal("49500"),
            "high_so_far": Decimal("50000"),
            "low_so_far": Decimal("49000"),
            "buy_money_ratio": Decimal("0.72"),
            "money_speed_5s": Decimal("2000000"),
            "money_speed_30s": Decimal("0"),
            "price_rising_sec": 3,
            "flow_observation_sec": Decimal("5"),
            "exact_flow": True,
            "in_prior_value_pool": True,
            "in_premarket_gap_pool": False,
        }
        values.update(overrides)
        return OpenSurgeObservation(**values)

    # ── 매도 연결 (이식의 핵심 — 공통 매도가 그대로 붙어 있어야 한다) ──
    def test_strategy_number_and_common_exit_profile_are_registered(self):
        self.assertEqual(STRATEGY_NUMBER, 1)
        self.assertEqual(STRATEGY_ID, StrategyId.S01_OPEN_SURGE)
        profile = STRATEGY_PROFILES[STRATEGY_ID]
        self.assertEqual(profile.force_exit_at.strftime("%H:%M"), "15:10")
        self.assertEqual(profile.early_decision_at.strftime("%H:%M"), "09:20")

    # ── 되돌림 3문턱 ──
    def test_dip_then_rebound_is_buy_ready(self):
        decision = self.strategy.evaluate(self.observation())
        self.assertEqual(decision.action, BuyAction.BUY_READY)
        self.assertEqual(decision.reason, "DIP_REBOUND_CONFIRMED")

    def test_not_dipped_enough_waits(self):
        """저점이 -0.5% 밖에 안 밀렸으면 아직 때가 아니다(영구 제외가 아니라 WAIT)."""
        decision = self.strategy.evaluate(
            self.observation(low_so_far=Decimal("49750"), current_price=Decimal("49900"))
        )
        self.assertEqual(decision.action, BuyAction.WAIT)
        self.assertEqual(decision.reason, "DIP_NOT_DEEP_ENOUGH")

    def test_rebound_not_confirmed_waits(self):
        """저점 대비 +0.1% 뿐이면 반등 미확인."""
        decision = self.strategy.evaluate(
            self.observation(current_price=Decimal("49049"))
        )
        self.assertEqual(decision.action, BuyAction.WAIT)
        self.assertEqual(decision.reason, "REBOUND_NOT_CONFIRMED")

    def test_chase_above_low_three_percent_is_blocked(self):
        """저점에서 이미 +4.1% 멀어졌으면 추격 금지."""
        decision = self.strategy.evaluate(
            self.observation(current_price=Decimal("51009"),
                             high_so_far=Decimal("51009"))
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "CHASE_ABOVE_LOW_3PCT")

    def test_day_low_missing_waits(self):
        """저점 자료가 아직 없으면 판정 보류."""
        decision = self.strategy.evaluate(self.observation(low_so_far=Decimal("0")))
        self.assertEqual(decision.action, BuyAction.WAIT)
        self.assertEqual(decision.reason, "DAY_LOW_NOT_READY")

    def test_price_below_min_is_blocked(self):
        decision = self.strategy.evaluate(
            self.observation(previous_close=Decimal("10000"), open_price=Decimal("10000"),
                             low_so_far=Decimal("9700"), current_price=Decimal("9800"),
                             high_so_far=Decimal("10000"))
        )
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "PRICE_BELOW_10000")

    # ── 유니버스·경로 ──
    def test_non_gap_stock_outside_opening_pool_is_blocked(self):
        decision = self.strategy.evaluate(self.observation(in_prior_value_pool=False))
        self.assertEqual(decision.action, BuyAction.BLOCK)
        self.assertEqual(decision.reason, "NOT_IN_OPENING_POOL")

    def test_gap_route_is_kept(self):
        """시가갭 +3% 이상이면 GAP_SURGE 경로 — 되돌림 판정과 무관하게 유지."""
        decision = self.strategy.evaluate(
            self.observation(previous_close=Decimal("48000"), in_prior_value_pool=False)
        )
        self.assertEqual(decision.action, BuyAction.BUY_READY)
        self.assertEqual(decision.route, EntryRoute.GAP_SURGE)

    # ── 돈흐름 조건(교체하지 않음) ──
    def test_exact_flow_and_three_second_rise_are_required(self):
        missing = self.strategy.evaluate(self.observation(exact_flow=False))
        short = self.strategy.evaluate(self.observation(price_rising_sec=2))
        self.assertEqual(missing.reason, "EXACT_FLOW_MISSING")
        self.assertEqual(short.reason, "PRICE_RISE_NOT_PERSISTENT")

    def test_buy_money_ratio_gate(self):
        weak = self.strategy.evaluate(self.observation(buy_money_ratio=Decimal("0.5")))
        self.assertEqual(weak.reason, "BUY_MONEY_RATIO_WEAK")

    def test_five_second_flow_window_is_required(self):
        warming = self.strategy.evaluate(
            self.observation(flow_observation_sec=Decimal("4.9"))
        )
        ready = self.strategy.evaluate(
            self.observation(flow_observation_sec=Decimal("5"))
        )
        self.assertEqual(warming.action, BuyAction.WAIT)
        self.assertEqual(warming.reason, "FLOW_WINDOW_WARMING_UP")
        self.assertEqual(ready.action, BuyAction.BUY_READY)

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

    # ── 진입창·보너스 ──
    def test_entry_window_ends_before_0920(self):
        decision = self.strategy.evaluate(
            self.observation(observed_at=datetime(2026, 7, 27, 9, 20, tzinfo=KST))
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

# -*- coding: utf-8 -*-
"""★[STOP-FLOW-SPLIT 2026-08-04] 1번만 수급에 따라 손절선을 가른다.

    매도세 우위(매수비율 <= 0.50)  ->  -2%   빨리 자른다
    매수 우위  (매수비율 >  0.50)  ->  -3%   더 버틴다

8/4 S01 실거래가 근거다:
    지엔씨 119850  보유 중 최저 -0.897% -> 당일 +22.42%
    에스피지 058610 보유 중 최저 -1.059% -> 당일  +8.28%
      => 1% 남짓 밀렸다 크게 가는 종목이 있다. 조이면 잃는다(-1% 안은 폐기).
    기가비스 420770 -2.50% 손절 후 -5.68% 까지 더 빠짐
    티엘비 356860  -2.09% 손절 후 -4.36% 까지 더 빠짐
      => 진짜 무너지는 종목엔 손절이 필요하다.

⚠️1번에만 적용. 다른 전략이 같이 바뀌면 안 된다(친구님 지시).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_hold_sell_v1 import (  # noqa: E402
    STRATEGY_PROFILES,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)

KST = timezone(timedelta(hours=9))
ENTRY = Decimal("10000")
ENTRY_AT = datetime(2026, 8, 4, 9, 0, 0, tzinfo=KST)
JUDGE_AT = datetime(2026, 8, 4, 9, 10, 0, tzinfo=KST)

SELL_SIDE = Decimal("0.40")   # 매도세 우위 -> -2%
BUY_SIDE = Decimal("0.60")    # 매수 우위   -> -3%

OTHERS = (
    StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
    StrategyId.S04_PULLBACK,
    StrategyId.S05_BASE_BREAKOUT,
)


class S01StopFlowSplitTests(unittest.TestCase):
    def decide(self, strategy: StrategyId, price: str, buy_ratio: Decimal):
        state = HoldSellState(
            position_id="stop-split", strategy_id=strategy, code="005930",
            quantity=1, entry_price=ENTRY, entry_at=ENTRY_AT, peak_price=ENTRY)
        return UnifiedHoldSellEngine().evaluate(state, HoldSellObservation(
            observed_at=JUDGE_AT, price=Decimal(price), buy_ratio_recent=buy_ratio))

    # ── 1번: 갈래가 살아 있어야 한다 ─────────────────────────────────────

    def test_s01_profile_values(self):
        profile = STRATEGY_PROFILES[StrategyId.S01_OPEN_SURGE]
        self.assertEqual(Decimal("-2.0"), profile.stop_pct(SELL_SIDE))
        self.assertEqual(Decimal("-3.0"), profile.stop_pct(BUY_SIDE))

    def test_s01_sell_side_stops_at_minus_2(self):
        decision = self.decide(StrategyId.S01_OPEN_SURGE, "9790", SELL_SIDE)
        self.assertTrue(decision.should_sell, f"-2.10% 인데 안 판다: {decision.reason}")
        self.assertIn("HARD_STOP", decision.reason)

    def test_s01_buy_side_rides_past_minus_2(self):
        """매수 우위면 -2% 를 지나쳐 -3% 까지 버틴다."""
        decision = self.decide(StrategyId.S01_OPEN_SURGE, "9790", BUY_SIDE)
        self.assertFalse(
            decision.should_sell, "매수 우위인데 -2.10% 에서 팔면 갈래가 죽은 것")

    def test_s01_buy_side_stops_at_minus_3(self):
        decision = self.decide(StrategyId.S01_OPEN_SURGE, "9690", BUY_SIDE)
        self.assertTrue(decision.should_sell, "-3.10% 면 매수 우위여도 팔아야 한다")
        self.assertIn("HARD_STOP", decision.reason)

    # ── -1% 안은 폐기됐다 ────────────────────────────────────────────────

    def test_minus_1_percent_never_sells(self):
        """지엔씨 -0.897% / 에스피지 -1.059% 를 잃지 않도록 못박는다."""
        for side, ratio in (("매도세우위", SELL_SIDE), ("매수우위", BUY_SIDE)):
            with self.subTest(side=side):
                decision = self.decide(StrategyId.S01_OPEN_SURGE, "9894", ratio)
                self.assertFalse(
                    decision.should_sell,
                    f"-1.06% 에서 팔면 에스피지를 놓친다: {decision.reason}")

    # ── 다른 전략은 그대로 -2%/-2% ──────────────────────────────────────

    def test_other_strategies_unchanged(self):
        for strategy in OTHERS:
            with self.subTest(strategy=strategy.value):
                profile = STRATEGY_PROFILES[strategy]
                self.assertEqual(Decimal("-2.0"), profile.stop_pct(SELL_SIDE))
                self.assertEqual(Decimal("-2.0"), profile.stop_pct(BUY_SIDE))

    def test_others_still_sell_at_minus_2_even_on_buy_side(self):
        """2·4·5번은 매수 우위여도 -2% 에서 팔아야 한다(1번만 완화했다)."""
        for strategy in OTHERS:
            with self.subTest(strategy=strategy.value):
                decision = self.decide(strategy, "9790", BUY_SIDE)
                self.assertTrue(
                    decision.should_sell, f"{strategy.value} 가 같이 완화됐다")


if __name__ == "__main__":
    unittest.main()

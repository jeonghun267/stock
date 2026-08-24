# -*- coding: utf-8 -*-
"""손실방어 '꺾인 깊이' 조건 회귀시험 — 2026-08-05 원익IPS 실사례 재현.

무엇을 지키는가
  종전 손실방어는 가격 조건이 return_pct < 0 하나뿐이라, 한 번도 안 오른 종목이
  진입가 밑으로 조금만 내려가도 팔았다.
  8/5 원익IPS: 고점 대비 0.92% 꺾인 자리에서 매도 -> 그 뒤 2시간 반 동안
  매도가 아래로 한 번도 안 내려갔다(완전한 조기매도).

지키는 규칙
  common_peak_defense_drop_pct(1.0%) 보다 얕게 꺾였으면 손실방어로 팔지 않는다.
  깊게 꺾였으면 종전대로 판다.

되돌리기: 이 값을 0 으로 두면 종전과 동일해지고, 아래 얕은 시험은 실패한다.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

RUN_DIR = Path(r"C:\stock_bot\RUN")
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_hold_sell_v1 import (  # noqa: E402
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)

KST = ZoneInfo("Asia/Seoul")


def kst(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 8, 5, h, m, s, tzinfo=KST)


class DefenseDropTests(unittest.TestCase):
    """진입 100 -> 고점 100.4 -> 하락. 원익IPS 와 같은 모양(고점수익 +0.4%)."""

    ENTRY = "100"
    PEAK = "100.4"

    def setUp(self) -> None:
        self.engine = UnifiedHoldSellEngine()

    def _state(self) -> HoldSellState:
        return HoldSellState(
            position_id="position-defense-drop",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="240810",
            quantity=1,
            entry_price=Decimal(self.ENTRY),
            entry_at=kst(11, 0),
        )

    def _obs(self, at: datetime, price: str) -> HoldSellObservation:
        """손실방어 조건을 전부 만족시킨 관측(수급 3 + 구조 1 = 점수 4/5)."""
        return HoldSellObservation(
            observed_at=at,
            price=Decimal(price),
            vwap=Decimal("101"),
            buy_ratio_recent=Decimal("0.30"),
            money_speed_5s=Decimal("0"),
            money_speed_10s=Decimal("100"),
            money_speed_30s=Decimal("100"),
            buy_money_per_sec_10s=Decimal("100"),
            sell_money_per_sec_10s=Decimal("200"),   # 매도속도 우위 -> 1점
            buy_money_per_sec_30s=Decimal("500"),    # 매수 식음    -> 1점
            sell_money_per_sec_30s=Decimal("100"),
            che_str_change_5s=Decimal("-10"),        # 체결강도 하락 -> 1점
            one_minute_bearish=True,                 # 구조 약화    -> 1점
            common_peak_flow_ready=True,
            structure_broken=False,
            money_accelerating=False,
            ma3_permit=False,
            daily_ma_permit=False,                   # 상승보유 아님
            ma10_support=False,
            ma20_rising=False,
            recent_buy_money_rising=False,
        )

    def _run(self, price: str):
        """고점을 만든 뒤 그 가격에서 충분히 확인시간을 준다."""
        state = self._state()
        decisions = []
        self.engine.evaluate(state, self._obs(kst(11, 40, 0), self.PEAK))
        for sec in (0, 5, 10, 20):
            decisions.append(
                self.engine.evaluate(state, self._obs(kst(11, 44, sec), price)))
        return decisions

    def test_shallow_pullback_is_not_sold(self):
        """되돌림 0.90% (< 1.0%) — 원익IPS 자리. 팔면 안 된다."""
        price = "99.5"                      # (100.4-99.5)/100.4 = 0.896%
        for d in self._run(price):
            self.assertNotEqual(
                d.action, HoldSellAction.SELL,
                f"정상 호흡(되돌림 0.90%)에서 손실방어가 팔았다: {d.reason}")

    def test_deep_pullback_is_still_sold(self):
        """되돌림 1.20% (>= 1.0%) — 종전대로 팔려야 한다."""
        price = "99.2"                      # (100.4-99.2)/100.4 = 1.195%
        reasons = [d.reason for d in self._run(price)]
        actions = [d.action for d in self._run(price)]
        self.assertIn(
            HoldSellAction.SELL, actions,
            f"깊게 꺾였는데 손실방어가 안 팔았다: {reasons}")
        self.assertTrue(
            any("COMMON_FLOW_DEFENSE_EXIT" in r for r in reasons),
            f"매도 사유가 손실방어가 아니다: {reasons}")

    def test_threshold_value_is_wired(self):
        """계약: 이 값이 사라지거나 0 이 되면 8/5 회귀다."""
        self.assertEqual(
            self.engine.config.common_peak_defense_drop_pct, Decimal("1.0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

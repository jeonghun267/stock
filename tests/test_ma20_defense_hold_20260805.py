# -*- coding: utf-8 -*-
"""손실방어 국면에서만 20선 지지를 상승보유로 인정한다 — 잠금 시험.

지우기 전에 읽을 것
  8/4 에 "20선만 걸친 단계는 상승보유를 주지 말자"고 정했다(꼭지에서 못 파는 걸
  막으려던 것). 8/5 에 친구님이 정정하셨다 —
    "이 해제는 매도(꼭지) 상황에서만 적용하는 것이지 손실방어 국면엔 적용 안 한다."
  계약서(config\\sellhold_contract_v1.json 의 상승보유._20선이유)에도 그 문장이
  적혀 있었는데 코드만 안 따라가 있었다. daily_ma_permit 이 틱마다 참/거짓 하나라
  꼭지 규칙과 방어 규칙이 같은 값을 썼기 때문이다.

지키는 규칙
  · 손실방어 국면(현재수익 < 0) + 20선 지지 -> 팔지 않는다(COMMON_MA20_DEFENSE_HOLD)
  · 20선 지지가 없으면 -> 종전대로 판다
  · 이익 국면(수익 +2% 이상 방어)에는 20선을 인정하지 않는다 -> 종전대로 판다

  대본은 test_common_defense_drop_20260805.py 의 것을 빌렸다(진입 100 -> 고점
  100.4 -> 99.2, 붕괴점수 4/5). 그 시험과 짝이다.

되돌리기: ma20_defense_permit 배선을 빼면 아래 첫 시험이 실패한다.
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


def kst(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=KST)


class Ma20DefenseHoldTests(unittest.TestCase):

    ENTRY = "100"
    PEAK = "100.4"
    DEEP = "99.2"          # 되돌림 1.195% -> 손실방어가 발동하는 자리

    def setUp(self) -> None:
        self.engine = UnifiedHoldSellEngine()

    def _state(self) -> HoldSellState:
        return HoldSellState(
            position_id="position-ma20-defense",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="240810",
            quantity=1,
            entry_price=Decimal(self.ENTRY),
            entry_at=kst(11, 0),
        )

    def _obs(self, at: datetime, price: str, *,
             ma20_defense_permit: bool) -> HoldSellObservation:
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
            sell_money_per_sec_10s=Decimal("200"),
            buy_money_per_sec_30s=Decimal("500"),
            sell_money_per_sec_30s=Decimal("100"),
            che_str_change_5s=Decimal("-10"),
            one_minute_bearish=True,
            common_peak_flow_ready=True,
            structure_broken=False,
            money_accelerating=False,
            ma3_permit=False,
            daily_ma_permit=False,        # 5선·10선 지지는 없다(20선만 걸친 상태)
            ma20_defense_permit=ma20_defense_permit,
            ma10_support=False,
            ma20_rising=False,
            recent_buy_money_rising=False,
        )

    def _run(self, price: str, *, ma20_defense_permit: bool):
        state = self._state()
        decisions = []
        self.engine.evaluate(
            state, self._obs(kst(11, 40, 0), self.PEAK,
                             ma20_defense_permit=ma20_defense_permit))
        for second in (0, 5, 10, 20):
            decisions.append(self.engine.evaluate(
                state, self._obs(kst(11, 44, second), price,
                                 ma20_defense_permit=ma20_defense_permit)))
        return decisions

    def test_ma20_support_blocks_loss_defense(self):
        """20선이 받쳐주면 손실방어로 팔지 않는다 — 이 배선의 본체."""
        decisions = self._run(self.DEEP, ma20_defense_permit=True)
        reasons = [d.reason for d in decisions]
        for decision in decisions:
            self.assertNotEqual(
                decision.action, HoldSellAction.SELL,
                f"20선이 받쳐주는데 손실방어가 팔았다: {reasons}")
        self.assertTrue(
            any("COMMON_MA20_DEFENSE_HOLD" in r for r in reasons),
            f"20선 보유 사유가 안 나왔다: {reasons}")

    def test_without_ma20_support_it_still_sells(self):
        """20선 지지가 없으면 종전 그대로 판다 — 매도를 통째로 죽이지 않았는지."""
        decisions = self._run(self.DEEP, ma20_defense_permit=False)
        reasons = [d.reason for d in decisions]
        self.assertIn(
            HoldSellAction.SELL, [d.action for d in decisions],
            f"20선 지지가 없는데도 안 팔았다: {reasons}")
        self.assertTrue(
            any("COMMON_FLOW_DEFENSE_EXIT" in r for r in reasons),
            f"매도 사유가 손실방어가 아니다: {reasons}")

    def test_profit_defense_ignores_ma20(self):
        """이익 국면(+2% 이상)에는 20선을 인정하지 않는다 — 범위가 새지 않았는지.

        친구님 정정은 '손실방어 국면'에 한정된 말이다. 이익 구간에서 20선만
        걸친 걸로 붙잡고 있으면 벌어놓은 것을 반납한다.
        """
        state = self._state()
        # 진입 100 -> 고점 103 -> 102.5. 고점수익 +3%(< 4% 라 꼭지매도는 안 뜸),
        # 현재수익 +2.5% -> defensive_profit_setup 자리.
        def obs(at, price):
            row = self._obs(at, price, ma20_defense_permit=True)
            return type(row)(**{**row.__dict__, "structure_broken": True})

        self.engine.evaluate(state, obs(kst(11, 40, 0), "103"))
        decisions = [self.engine.evaluate(state, obs(kst(11, 44, s), "102.5"))
                     for s in (0, 5, 10, 20)]
        reasons = [d.reason for d in decisions]
        self.assertFalse(
            any("COMMON_MA20_DEFENSE_HOLD" in r for r in reasons),
            f"이익 국면인데 20선 보유가 끼어들었다: {reasons}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

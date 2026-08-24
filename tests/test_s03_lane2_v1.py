# -*- coding: utf-8 -*-
"""S03 2레인 개편 잠금 시험 (2026-08-06 친구님 지시).

"2초 관찰, 바로 상승해야 되고, 1분 안에 바로 상승하지 않으면 매수 금지.
 급락 후 바로 급상승하는 거 잡기 위함" + "손절컷 -0.5% 해".
매수 방법은 1레인 급행과 공유(매도 감속 + 매수 가속 + 매수 우위).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_rotation_engine_v1 import Strategy03HoldSellEngine
from strategy_03_intraday_rebound_v1 import IntradayReboundDetector
from 골짜기_급반등 import MicroPoint


class Lane2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 7, 27, 9, 30, 0)

    def point(self, second: int, price: float, buy: float, sell: float) -> MicroPoint:
        return MicroPoint(
            ts=self.start + timedelta(seconds=second),
            price=price,
            open_price=10_500,
            buy_money_cum=buy,
            sell_money_cum=sell,
            buy_volume_cum=buy,
            sell_volume_cum=sell,
            best_ask_px=price + 10,
            best_bid_px=price,
            best_ask_qty=100,
            best_bid_qty=1000,
        )

    def test_stale_low_dies_after_60s_and_needs_lower_low(self) -> None:
        """1분 안에 못 튄 저점은 폐기 — 더 낮은 새 저점이 나와야 다시 무장한다."""
        detector = IntradayReboundDetector()
        for row in [
            self.point(0, 10_000, 100, 100),
            self.point(10, 9_700, 150, 1_300),
            self.point(20, 9_450, 200, 2_500),    # 무장 (저점 9,450)
        ]:
            detector.feed(row, allow_signal=True)
        stale = detector.feed(
            self.point(85, 9_490, 260, 3_700), allow_signal=True)   # 저점 65초 경과
        self.assertEqual(stale["reason"], "INTRADAY_CONFIRM_TIMEOUT")
        blocked = detector.feed(
            self.point(90, 9_460, 280, 3_750), allow_signal=True)   # 죽은 저점 위
        self.assertEqual(blocked["reason"], "DEAD_LOW_REQUIRES_LOWER_LOW")
        rearmed = detector.feed(
            self.point(95, 9_400, 300, 3_900), allow_signal=True)   # 더 낮은 새 저점
        self.assertEqual(rearmed["action"], "ARMED")

    def test_no_buy_while_selling_still_accelerating(self) -> None:
        """반등 띠 안이어도 매도가 아직 폭주 중이면(감속 없음) 안 산다."""
        detector = IntradayReboundDetector()
        for row in [
            self.point(0, 10_000, 100, 100),
            self.point(10, 9_700, 150, 1_300),
            self.point(20, 9_450, 200, 2_500),
            self.point(28, 9_440, 250, 3_600),
        ]:
            detector.feed(row, allow_signal=True)
        detector.feed(
            self.point(34, 9_535, 300, 5_000), allow_signal=True)  # 1차 반등
        detector.feed(
            self.point(40, 9_490, 350, 7_000), allow_signal=True)  # 높은 2차 저점
        row = detector.feed(
            self.point(46, 9_540, 400, 9_500), allow_signal=True)  # 재반등, 매도 가속
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "NO_SELL_DECEL_BUY_FLIP")

    def test_two_second_observe_and_sixty_second_window(self) -> None:
        detector = IntradayReboundDetector()
        self.assertEqual(detector.config.low_stable_sec, 2.0)
        self.assertEqual(detector.config.max_confirm_sec, 60.0)

    def test_lane2_hard_stop_is_one_percent(self) -> None:
        """2레인 손절컷 -1% (친구님 결정 — -0.5%는 검증에서 반등 직전 털림) —
        1레인(-2.0%·10:30 청산)은 그대로."""
        engine = Strategy03HoldSellEngine()
        self.assertEqual(engine.profile.hard_stop_pct, Decimal("-1.0"))
        self.assertEqual(engine.profile.strong_flow_hard_stop_pct, Decimal("-1.0"))
        self.assertEqual(engine.profile.force_exit_at, day_time(15, 10))
        self.assertEqual(engine.open_profile.hard_stop_pct, Decimal("-2.0"))
        self.assertEqual(engine.open_profile.force_exit_at, day_time(10, 30))


if __name__ == "__main__":
    unittest.main()

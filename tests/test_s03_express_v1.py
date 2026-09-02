# -*- coding: utf-8 -*-
"""S03 OPEN_CRASH의 깊은 급락 구간 비독점 계약 시험."""

from __future__ import annotations

import sys
import unittest
from datetime import time as day_time, timedelta
from pathlib import Path
from types import SimpleNamespace

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_01_rotation_engine_v2 import kst_now
from strategy_03_rotation_engine_v1 import Strategy03Engine
from 골짜기_급반등 import MicroPoint, PriorProfile, RapidReboundDetector

OLD_EXPRESS_REASON = "S03_EXPRESS_DEEP_CRASH+SELL_DECEL+BUY_FLIP"


class ExpressRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = kst_now().replace(
            hour=9, minute=5, second=0, microsecond=0, tzinfo=None)
        self.profile = PriorProfile(
            previous_close=10_500, previous_value=20_000,
            previous_range_pct=8.0, previous_close_position=0.7)

    def point(self, second: int, price: float, buy: float, sell: float) -> MicroPoint:
        return MicroPoint(
            ts=self.now + timedelta(seconds=second),
            price=price,
            open_price=10_500,
            buy_money_cum=buy,
            sell_money_cum=sell,
            che_str=100,
            best_ask_px=price + 10,
            best_bid_px=price,
            best_ask_qty=100,
            best_bid_qty=120,
        )

    def test_no_express_fire_without_pullback(self) -> None:
        """종전 급행 발화 지형(깊은 급락 + 감속·역전, 눌림 없음)에서 즉시매수가 없어야 한다."""
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0),
            self.point(10, 9_700, 50, 1_000),
            self.point(20, 9_450, 100, 2_200),
            self.point(30, 9_400, 120, 3_400),
            self.point(40, 9_430, 400, 3_500),   # 종전이면 급행 발화 지점
        ]
        last: dict = {}
        for row in rows:
            last = detector.feed(row, self.profile, allow_signal=True)
        self.assertNotEqual(last["action"], "BUY_READY")
        self.assertNotEqual(last["reason"], OLD_EXPRESS_REASON)
        self.assertNotIn("EXPRESS", last["action"])

    def test_deep_zone_remains_available_to_s03(self) -> None:
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0),
            self.point(20, 9_600, 100, 500),
            self.point(40, 9_150, 200, 1_500),    # 저점 (시가 대비 -12.9%)
            self.point(50, 9_244, 300, 1_520),    # 1차반등 +1.03%
            self.point(60, 9_205, 400, 1_540),    # 눌림(더 높은 저점)
            self.point(70, 9_255, 900, 1_600),    # 2차반등 — 종전 DEEP_ZONE_EXPRESS_ONLY 지점
        ]
        last: dict = {}
        for row in rows:
            last = detector.feed(row, self.profile, allow_signal=True)
        self.assertEqual(last["action"], "WAIT")
        self.assertEqual(last["reason"], "OPEN_SELLER_EXHAUSTION_WAIT")
        self.assertNotEqual(last["reason"], "OPEN_DROP_8PCT_OR_MORE_RESERVED_S06")

    def test_high_flyer_above_minus_4_does_not_arm(self) -> None:
        detector = RapidReboundDetector()
        first = detector.feed(self.point(0, 12_000, 0, 0), self.profile, allow_signal=True)
        self.assertEqual(first["action"], "WAIT")   # 고점 자체선 무장 안 함
        armed = detector.feed(
            self.point(10, 11_100, 50, 900), self.profile, allow_signal=True)
        self.assertEqual(armed["action"], "WAIT")
        self.assertEqual(armed["reason"], "OPEN_DROP_GT_4PCT")

    def test_force_exit_moved_to_1030(self) -> None:
        stub = SimpleNamespace(config=SimpleNamespace(force_exit=day_time(15, 10)))
        morning = {"entry_at": "2026-08-06T09:10:00", "entry_lane": "OPEN_CRASH"}
        self.assertEqual(
            Strategy03Engine._position_force_exit_at(stub, morning),
            day_time(10, 30))
        intraday = {"entry_at": "2026-08-06T10:35:00", "entry_lane": "INTRADAY_CRASH"}
        self.assertEqual(
            Strategy03Engine._position_force_exit_at(stub, intraday),
            day_time(15, 10))


if __name__ == "__main__":
    unittest.main()

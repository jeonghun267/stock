# -*- coding: utf-8 -*-
"""S03 급행 매수(감속+역매수) 잠금 시험 (2026-08-06 친구님 지시 "-7% 이하로 해 / 배선해").

급행 = 깊은 급락(당일 고점 -7%↓) + 빠른 낙하(10분 -3%↓) + 저점 +1.5% 안
       + 매도 감속·매수 가속·매수 우위(flow_accel) → 눌림 없이 즉시 매수.
매수창 09:02~09:20 · 강제청산 10:30 · 깊은 곳(-8%↓)은 4단계 금지(급행 전용).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from types import SimpleNamespace

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_01_rotation_engine_v2 import kst_now
from strategy_03_rotation_engine_v1 import Strategy03Engine
from strategy_03_signal_contract_v1 import (
    EXPRESS_DEPTH_PCT,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)
from 골짜기_급반등 import MicroPoint, PriorProfile, RapidReboundDetector

EXPRESS_REASON = "S03_EXPRESS_DEEP_CRASH+SELL_DECEL+BUY_FLIP"


class ExpressTests(unittest.TestCase):
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

    def express_row(self) -> dict:
        """깊은 급락(-10%) 뒤 매도 감속 + 매수 가속 순간 — 눌림 없이 급행 발화."""
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0),          # 무장
            self.point(10, 9_700, 50, 1_000),     # 계단
            self.point(20, 9_450, 100, 2_200),    # 계단 (매도 폭주)
            self.point(30, 9_400, 120, 3_400),    # 계단 (매도 폭주 지속)
            self.point(40, 9_430, 400, 3_500),    # 매도 감속(120→10/s) + 매수 가속(2→28/s)
        ]
        last: dict = {}
        for row in rows:
            last = detector.feed(row, self.profile, allow_signal=True)
        return last

    def test_express_fires_without_pullback(self) -> None:
        row = self.express_row()
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["reason"], EXPRESS_REASON)
        self.assertLessEqual(row["express_depth_pct"], EXPRESS_DEPTH_PCT)
        # 저점(9,400) 바로 위(+0.32%)에서 샀다 — 눌림·2차반등을 기다리지 않았다.
        self.assertLess(row["rebound_pct"], 1.0)

    def test_express_requires_depth(self) -> None:
        """같은 흐름 모양이라도 얕으면(-5%대) 급행이 안 나간다."""
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0),
            self.point(10, 9_980, 50, 1_000),
            self.point(20, 9_950, 100, 2_200),
            self.point(30, 9_940, 120, 3_400),
            self.point(40, 9_960, 400, 3_500),
        ]
        last: dict = {}
        for row in rows:
            last = detector.feed(row, self.profile, allow_signal=True)
        self.assertNotEqual(last["action"], "BUY_READY")
        self.assertEqual(last["reason"], "STAIRCASE_CHASING_LOW")

    def test_deep_zone_blocks_four_step_path(self) -> None:
        """종전 인계선(-8%) 아래에서는 4단계 경로가 쏘지 못한다(급행 전용) —
        신호 검사기가 버릴 신호에 총알을 낭비하지 않기 위해서다."""
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0),
            self.point(20, 9_600, 100, 500),
            self.point(40, 9_150, 200, 1_500),    # 저점 (시가 대비 -12.9%)
            self.point(50, 9_244, 300, 1_520),    # 1차반등 +1.03%
            self.point(60, 9_205, 400, 1_540),    # 눌림(더 높은 저점)
            self.point(70, 9_255, 900, 1_600),    # 2차반등 — 종전이면 매수 지점
        ]
        last: dict = {}
        for row in rows:
            last = detector.feed(row, self.profile, allow_signal=True)
        self.assertEqual(last["action"], "WAIT")
        self.assertIn("DEEP_ZONE_EXPRESS_ONLY", last["reason"])

    def test_contract_accepts_express_and_rejects_shallow(self) -> None:
        row = self.express_row()
        row.update({
            "code": "123456",
            "name": "TEST",
            "signal_sequence": 1,
            "anchor_id": f"{row['anchor_low_ts']}:{float(row['anchor_low']):.4f}",
        })
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": self.now.strftime("%Y%m%d"),
            "updated_at": row["ts"],
            "mode": SIGNAL_MODE,
            "signals": [row],
        }
        decision_now = datetime.fromisoformat(row["ts"]) + timedelta(seconds=1)
        self.assertEqual(
            len(select_fresh_signals(payload, now=decision_now, max_age_sec=5)), 1)
        shallow = dict(row)
        shallow["express_depth_pct"] = -6.5      # 친구님 문턱(-7)보다 얕음
        payload["signals"] = [shallow]
        self.assertEqual(
            select_fresh_signals(payload, now=decision_now, max_age_sec=5), [])

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

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_rotation_engine_v1 import build_config
from strategy_03_signal_contract_v1 import (
    INTRADAY_CRASH_LANE,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)
from 골짜기_급반등 import (
    MicroPoint,
    PriorProfile,
    RapidReboundMonitor,
)


class Strategy03UnifiedIntradayStaircaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 7, 27, 9, 30, 0)
        self.profile = PriorProfile(previous_close=10_500)

    def point(self, second: int, price: float, buy: float, sell: float) -> MicroPoint:
        return MicroPoint(
            ts=self.start + timedelta(seconds=second),
            price=price,
            open_price=10_500,
            buy_money_cum=buy,
            sell_money_cum=sell,
        )

    def points(self) -> list[MicroPoint]:
        # ★[SPEED-GATE 2026-08-03] 새 규칙에 맞춘 시나리오(주 시험과 동일한 모양).
        #   저점 9,700 → 1차반등 +1.03% → 눌림(더 높은 저점) → 2차반등 +0.53%
        #   → 저점 +1.13% 에서 매수. 옛 매수가 9,855(+1.598%)는 좁아진 매수구간
        #   (+1.0~+1.5%) 밖이라 더는 체결되지 않는다.
        return [
            self.point(0, 10_050, 0, 0),
            self.point(20, 9_900, 100, 500),
            self.point(40, 9_700, 200, 1_500),
            self.point(50, 9_800, 300, 1_520),
            self.point(60, 9_758, 400, 1_540),
            self.point(70, 9_810, 900, 1_600),
        ]

    def fire(self) -> dict:
        monitor = RapidReboundMonitor()
        row = {}
        for point in self.points():
            row, _ = monitor.process_point(
                "043260", "TEST", point, self.profile, allow_signal=True)
        return row

    def test_post_0920_uses_same_s06_staircase_detector(self) -> None:
        """★[SPEED-GATE 2026-08-03] 장중 레인도 장초 레인과 같은 새 판정을 쓴다.

        시간 관찰(60초)과 flow_flip·flow_accel 강제는 빠졌고, 저점 후
        매수속도 > 매도속도 로 판정한다. 계단 재테스트 4단계는 그대로다.
        """
        row = self.fire()
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["entry_lane"], INTRADAY_CRASH_LANE)
        self.assertLess(row["observe_sec"], 60.0)
        self.assertGreater(row["post_buy_rate"], row["post_sell_rate"])
        self.assertGreaterEqual(row["rebound_pct"], 1.0)
        self.assertLessEqual(row["rebound_pct"], 1.5)

    def test_contract_accepts_unified_intraday_lane_only_inside_window(self) -> None:
        row = self.fire()
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": "20260727",
            "updated_at": row["ts"],
            "mode": SIGNAL_MODE,
            "signals": [row],
        }
        now = datetime.fromisoformat(row["ts"]) + timedelta(seconds=2)
        selected = select_fresh_signals(payload, now=now, max_age_sec=5)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["entry_lane"], INTRADAY_CRASH_LANE)
        before_window = dict(row)
        before_window["ts"] = before_window["ts"].replace("09:31", "09:19")
        payload["signals"] = [before_window]
        payload["updated_at"] = before_window["ts"]
        self.assertEqual(select_fresh_signals(
            payload,
            now=datetime.fromisoformat(before_window["ts"]),
            max_age_sec=5,
        ), [])

    def test_rotation_window_and_shared_limits_are_preserved(self) -> None:
        config = build_config()
        self.assertEqual(config.entry_start, time(9, 0))
        self.assertEqual(config.entry_end, time(14, 30))
        self.assertEqual(config.quantity, 1)
        self.assertEqual(config.max_slots, 6)
        self.assertEqual(config.max_daily_codes, 6)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.rotation_capital_krw, 2_000_000)


if __name__ == "__main__":
    unittest.main()
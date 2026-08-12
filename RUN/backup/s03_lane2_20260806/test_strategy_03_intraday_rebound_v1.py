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
    INTRADAY_CRASH_ALGORITHM,
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
            buy_volume_cum=buy,
            sell_volume_cum=sell,
            best_ask_px=price + 10,
            best_bid_px=price,
            best_ask_qty=100,
            best_bid_qty=1000,
        )

    def points(self) -> list[MicroPoint]:
        # 장중 두 번째 로직: 당일 고점 대비 -5.0% 이상 급락 후
        # 저점이 3초 안정되고 +0.5~1.0% 첫 반등에서 진입한다.
        # ★[2026-08-06 친구님 지시 "두번째 저점도 -5% 이하 / 셋 다 고쳐"]
        #   종전 시나리오는 -2.0%(10,000 -> 9,800) 였다. 문턱이 1.5 -> 5.0 으로
        #   올라가 더는 신호가 나지 않으므로 낙폭을 새 문턱에 맞춰 깊게 잡았다.
        return [
            self.point(0, 10_000, 100, 100),
            self.point(20, 9_450, 200, 500),      # -5.5%
            self.point(24, 9_450, 250, 520),      # 저점 안정
            self.point(28, 9_500, 900, 600),      # 반등 +0.529%
        ]

    def slow_points(self) -> list[MicroPoint]:
        """당일 고점이 10분 창 밖으로 밀려난 뒤에 급락하는 흐름.

        ★[2026-08-06 친구님 "장중 고점 잘못된 거야 / 당일 고점으로"]
          고점 10,000 은 t=0 에 찍히고, 그 뒤 9,700 이 계속되다가 t=840 에 9,250 으로 빠진다.
          t=840 시점에서 10분 창(600초)에 남는 것은 9,700 뿐이라
            창 고점 기준 낙폭 = -4.64%  -> 5% 문턱을 못 넘어 종전 코드는 못 잡는다
            당일 고점 기준 낙폭 = -7.50% -> 잡는다
          즉 이 흐름이 잡히면 '당일 고점'이 실제로 쓰이고 있다는 증거다.
          자료 공백 리셋을 피하려고 간격은 120초로 둔다(max_gap_sec=150).
        """
        rows = [self.point(0, 10_000, 100, 100)]
        cum = 100
        for i in range(1, 8):                     # t=120 .. 840
            cum += 100
            rows.append(self.point(120 * i, 9_700, cum, cum))
        rows.append(self.point(960, 9_250, cum + 100, cum + 400))
        rows.append(self.point(964, 9_250, cum + 150, cum + 420))
        rows.append(self.point(968, 9_305, cum + 900, cum + 500))
        return rows

    def fire(self) -> dict:
        monitor = RapidReboundMonitor()
        row = {}
        for point in self.points():
            row, _ = monitor.process_point(
                "043260", "TEST", point, self.profile, allow_signal=True)
        return row

    def test_post_0920_uses_intraday_crash_detector(self) -> None:
        row = self.fire()
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["entry_lane"], INTRADAY_CRASH_LANE)
        self.assertEqual(row["algorithm"], INTRADAY_CRASH_ALGORITHM)
        self.assertLessEqual(row["intraday_drawdown_pct"], -5.0)
        self.assertGreaterEqual(row["rebound_pct"], 0.5)
        self.assertLessEqual(row["rebound_pct"], 1.0)

    # ★[2026-08-06] 회전엔진 선별기가 open_price 로 진입 가격대를 재검산한다.
    #   이 값이 빠지면(strategy_03_rotation_engine_v1.py:141) 신호가 통째로 버려진다 —
    #   S03 가 역대 한 주도 못 산 진짜 원인이었다. 다시 빠지면 여기서 잡는다.
    def test_signal_carries_open_price(self) -> None:
        row = self.fire()
        self.assertEqual(row["action"], "BUY_READY")
        self.assertIn("open_price", row)
        self.assertGreater(float(row["open_price"] or 0), 0)

    # ★[2026-08-06 친구님 "장중 고점 잘못된 거야 / 당일 고점으로"]
    #   고점이 10분 창 밖으로 밀려나도 당일 고점으로 낙폭을 재야 한다.
    #   창 고점 기준이면 -4.64% 라 5% 문턱을 못 넘어 신호가 안 난다.
    def test_uses_day_high_not_rolling_window(self) -> None:
        monitor = RapidReboundMonitor()
        row = {}
        for point in self.slow_points():
            row, _ = monitor.process_point(
                "043260", "TEST", point, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "BUY_READY",
                         "당일 고점이 아니라 10분 창 고점을 쓰고 있다")
        self.assertEqual(float(row["intraday_high"]), 10_000.0,
                         "고점이 당일 고점(10,000)이 아니다")
        self.assertLessEqual(row["intraday_drawdown_pct"], -7.0)

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
        before_window["ts"] = before_window["ts"].replace("09:30", "09:19")
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
        # ★[2026-08-06 친구님 지시 "QTY 2주 원래대로 1주로 돌려줘"] 2 -> 1.
        #   되돌린 뒤 이 단언이 하루 종일 실패한 채 있었다. 상시 실패 시험은
        #   진짜 회귀를 가린다(오늘 실제로 그럴 뻔했다). 새 값으로 잠근다.
        self.assertEqual(config.quantity, 1)
        self.assertEqual(config.max_slots, 6)
        self.assertEqual(config.max_daily_codes, 6)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.rotation_capital_krw, 2_000_000)


if __name__ == "__main__":
    unittest.main()

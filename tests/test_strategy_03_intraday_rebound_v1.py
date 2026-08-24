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
        # 저점이 안정된 뒤 첫 반등→눌림→높은 저점→재반등과 매수 방법을 확인한다.
        # ★[S03-LANE2 2026-08-06 친구님 지시 "2초 관찰·1분 안에 상승 없으면 매수 금지"]
        #   매수 방법이 1레인 급행과 같아져(매도 감속+매수 가속+매수 우위, 10초 두 구간)
        #   시나리오를 그 흐름이 실리게 다시 짰다: 매도 폭주(120/s) → 감속(86/s 매수 우위).
        return [
            self.point(0, 10_000, 100, 100),
            self.point(10, 9_700, 150, 1_300),    # 매도 폭주로 하락
            self.point(20, 9_450, 200, 2_500),    # -5.5% 무장
            self.point(28, 9_440, 250, 3_600),    # 신저점 (매도 여전히 강함)
            self.point(34, 9_535, 1_500, 3_700),  # 1차 반등 +1.0%
            self.point(40, 9_490, 1_600, 3_750),  # 0.4% 눌림·높은 두 번째 저점
            self.point(46, 9_540, 3_000, 3_800),  # 2차 반등 + 매수 가속 → 매수
            # ★[2026-08-13] 같은 ts 중복 틱은 생산 dedup 이 설계상 거부(WAIT)하므로
            #   마지막 row 를 덮어 테스트를 깨뜨린다 — 중복 제거.
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
        # ★[S03-LANE2 2026-08-06] 새 매수 방법(감속+역매수·10초 두 구간)이 실리도록
        #   끝부분을 촘촘하게 다시 짰다: 매도 폭주(50/s) → 감속(8/s)·매수 폭발(86/s).
        rows.append(self.point(946, 9_480, cum + 10, cum + 100))   # -5.2% 무장
        rows.append(self.point(950, 9_400, cum + 20, cum + 300))   # 신저점
        rows.append(self.point(958, 9_250, cum + 40, cum + 700))   # 신저점 (매도 폭주)
        rows.append(self.point(962, 9_250, cum + 60, cum + 740))   # 저점 버팀
        rows.append(self.point(968, 9_345, cum + 900, cum + 780))   # 1차 반등
        rows.append(self.point(974, 9_305, cum + 1000, cum + 810))  # 높은 두 번째 저점
        rows.append(self.point(980, 9_355, cum + 2000, cum + 840))  # 2차 반등 → 매수
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
        self.assertGreaterEqual(row["rebound_pct"], 1.0)
        self.assertLessEqual(row["rebound_pct"], 1.5)
        self.assertIn("EXACT_SHORT_BUY_DOMINANCE", row["reason"])
        self.assertFalse(row["long_flow_gates_enabled"])

    def test_first_rebound_alone_does_not_buy(self) -> None:
        monitor = RapidReboundMonitor()
        row = {}
        for point in self.points()[:5]:
            row, _ = monitor.process_point(
                "043260", "TEST", point, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "FIRST_REBOUND_WAIT_RETEST")

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

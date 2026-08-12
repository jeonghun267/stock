# -*- coding: utf-8 -*-
"""S03 저점 계기판 3종 그림자 기록 잠금 시험 (2026-08-06 친구님 지시).

계기판은 기록 전용이다 — 판정(매수·매도)에 쓰이면 안 되고,
저점이 정해지는 순간(무장·계단)마다 다시 계산돼 행에 실려야 한다.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_intraday_rebound_v1 import IntradayReboundDetector
from 골짜기_급반등 import MicroPoint, _is_low_gauge_row


class LowGaugeShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 7, 27, 9, 30, 0)

    def point(
        self,
        second: int,
        price: float,
        buy: float,
        sell: float,
        ask_qty: float = 100,
        bid_qty: float = 1000,
    ) -> MicroPoint:
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
            best_ask_qty=ask_qty,
            best_bid_qty=bid_qty,
        )

    def test_gauges_recorded_at_armed(self) -> None:
        """무장(ARMED) 순간 계기판 3종이 손계산 값과 일치해야 한다."""
        detector = IntradayReboundDetector()
        rows = [
            self.point(0, 10_000, 1_000_000, 1_000_000),
            self.point(30, 10_000, 1_500_000, 1_500_000),
            self.point(60, 10_000, 2_000_000, 2_000_000),
            self.point(70, 9_990, 2_050_000, 2_200_000),
            self.point(80, 9_950, 2_100_000, 2_500_000),
            self.point(90, 9_400, 2_150_000, 2_700_000),   # -6.0% → 무장
        ]
        last = None
        for row in rows:
            last = detector.feed(row, allow_signal=True)
        assert last is not None
        self.assertEqual(last["action"], "ARMED")
        # ① 클라이맥스: 직전 1분(기준점 t=30) 거래대금 ÷ 당일 분당 평균(09:00 기점 31.5분)
        total_cum = 2_150_000 + 2_700_000
        minute_money = total_cum - (1_500_000 + 1_500_000)
        expected_climax = round(minute_money / (total_cum / 31.5), 3)
        self.assertEqual(last["dip_climax_mult"], expected_climax)
        # ② 대기열 불균형: 1000/(1000+100)
        self.assertEqual(last["dip_book_imb"], 0.909)
        # ③ 매도 감속: (2.70M-2.50M) ÷ (2.50M-2.20M)
        self.assertEqual(last["dip_sell_decel_10s"], 0.667)

    def test_gauges_recomputed_on_staircase_low(self) -> None:
        """계단 저점(INTRADAY_NEW_LOW_RESET)마다 계기판이 새로 계산돼야 한다."""
        detector = IntradayReboundDetector()
        rows = [
            self.point(0, 10_000, 1_000_000, 1_000_000),
            self.point(30, 10_000, 1_500_000, 1_500_000),
            self.point(60, 10_000, 2_000_000, 2_000_000),
            self.point(70, 9_990, 2_050_000, 2_200_000),
            self.point(80, 9_950, 2_100_000, 2_500_000),
            self.point(90, 9_400, 2_150_000, 2_700_000),
        ]
        for row in rows:
            detector.feed(row, allow_signal=True)
        stepped = detector.feed(
            self.point(94, 9_350, 2_160_000, 2_900_000), allow_signal=True)
        self.assertEqual(stepped["reason"], "INTRADAY_NEW_LOW_RESET")
        # 새 저점(t=94) 기준 매도 감속: p10=t=80, p20=t=70
        # (2.90M-2.50M) ÷ (2.50M-2.20M) = 1.333 — 무장 때의 0.667 과 달라야 한다.
        self.assertEqual(stepped["dip_sell_decel_10s"], 1.333)

    def test_gauges_none_when_history_missing(self) -> None:
        """이력이 없으면 0 으로 꾸미지 말고 None(빈칸)이어야 한다."""
        detector = IntradayReboundDetector()
        detector.feed(self.point(0, 10_000, 100, 100), allow_signal=True)
        armed = detector.feed(
            self.point(20, 9_400, 200, 500, ask_qty=0), allow_signal=True)
        self.assertEqual(armed["action"], "ARMED")
        self.assertIsNone(armed["dip_climax_mult"])      # 60초 전 자료 없음
        self.assertIsNone(armed["dip_book_imb"])         # 호가 무효(잔량 0)
        self.assertIsNone(armed["dip_sell_decel_10s"])   # 10초 전·20초 전이 같은 점

    def test_gauges_do_not_change_judgment(self) -> None:
        """계기판 추가 전과 판정 순서가 동일해야 하고, 발화 행에도 계기판이 실려야 한다."""
        detector = IntradayReboundDetector()
        # ★[S03-LANE2 2026-08-06] 매수 방법이 감속+역매수로 바뀌어 시나리오 교체
        #   (tests/test_strategy_03_intraday_rebound_v1.py points() 와 동일).
        rows = [
            self.point(0, 10_000, 100, 100),
            self.point(10, 9_700, 150, 1_300),
            self.point(20, 9_450, 200, 2_500),
            self.point(28, 9_440, 250, 3_600),
            self.point(34, 9_490, 1_500, 3_700),
        ]
        actions = [detector.feed(row, allow_signal=True) for row in rows]
        self.assertEqual(
            [row["action"] for row in actions],
            ["WAIT", "WAIT", "ARMED", "RESET", "BUY_READY"],
        )
        fired = actions[-1]
        for key in ("dip_climax_mult", "dip_book_imb", "dip_sell_decel_10s"):
            self.assertIn(key, fired)

    def test_host_filter_selects_only_low_moments(self) -> None:
        """하루 CSV 에는 저점 무장·계단 행만, INTRADAY 레인만 실려야 한다."""
        self.assertTrue(_is_low_gauge_row(
            {"entry_lane": "INTRADAY_CRASH", "action": "ARMED"}))
        self.assertTrue(_is_low_gauge_row(
            {"entry_lane": "INTRADAY_CRASH", "action": "RESET",
             "reason": "INTRADAY_NEW_LOW_RESET"}))
        self.assertFalse(_is_low_gauge_row(
            {"entry_lane": "OPEN_CRASH", "action": "ARMED"}))
        self.assertFalse(_is_low_gauge_row(
            {"entry_lane": "INTRADAY_CRASH", "action": "WAIT",
             "reason": "LOW_OR_REBOUND_CONFIRMING"}))


if __name__ == "__main__":
    unittest.main()

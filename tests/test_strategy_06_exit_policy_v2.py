import sys
import unittest
from dataclasses import replace
from datetime import time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_exit_policy_v2 import ExitObservation, decide_exit


class Strategy06ExitPolicyV2Test(unittest.TestCase):
    def setUp(self):
        self.base = ExitObservation(
            price=101.0, entry_price=100.0, anchor_low=99.0, peak_price=102.0,
            atr_3m_pct=0.4, ma5=100.5, ma5_prev=100.4, ma10=100.0,
            # ★[2026-08-26 현행화] ma20/ma20_prev 필수 인자 신설(strong_hold
            #   정배열 판정 전용). 0 = 자료 없음 → strong_hold 비활성 = 종전 동작.
            ma20=0.0, ma20_prev=0.0,
            buy_rate_10s=100.0, sell_rate_10s=80.0, buy_side_alive=True,
            buy_ratio_10s=0.56,
        )

    def test_hard_stop_and_no_local_take_profit(self):
        # ★[2026-08-26 현행화] TAKE_PROFIT_5 는 익절의 공용매도 이관으로 삭제 —
        #   +5% 단순 상승(고점 미반납)은 NO_EXIT 보유가 현재 계약이다.
        self.assertEqual(decide_exit(replace(self.base, price=97.9)).reason, "HARD_STOP_2")
        up5 = decide_exit(replace(self.base, price=105.0))
        self.assertEqual(up5.action, "HOLD")
        self.assertEqual(up5.reason, "NO_EXIT")

    def test_anchor_and_ma_break_need_sell_flow(self):
        anchor = replace(
            self.base, price=98.8, buy_rate_10s=100, sell_rate_10s=160,
            anchor_break_sec=3.0)
        self.assertEqual(decide_exit(anchor).reason, "ANCHOR_LOW_BREAK_FLOW_3S")
        # ★[MA10-3S 2026-08-25 친구님 승인 반영] MA10 이탈 매도는 매도우위에
        #   더해 3초 지속(ma10_break_sec>=3.0)이 필요하다 — 8/25 477850 실사고
        #   (+16.88% 놓침) 재발 방지 조건.
        ma10 = replace(
            self.base, price=99.8, anchor_low=98.0, ma10=100.0,
            buy_rate_10s=100, sell_rate_10s=160, ma10_break_sec=3.0)
        self.assertEqual(decide_exit(ma10).reason, "MA10_BREAK_SELL_FLOW")
        instant = replace(ma10, ma10_break_sec=0.0)
        self.assertNotEqual(decide_exit(instant).reason, "MA10_BREAK_SELL_FLOW")

    def test_90_percent_is_only_a_five_second_grace(self):
        # ★[2026-08-26 현행화] 유예(grace)는 이제 완전 정배열 strong_hold
        #   (price>ma5>ma10>ma20, ma5·ma20 상승)일 때만 열린다 — 픽스처에
        #   ma20 정배열을 채워 원래 의도(90% 매수비율 = 최대 5초 유예)를 검증.
        trailing = replace(
            self.base, price=101.0, peak_price=103.0, ma5=100.5,
            ma5_prev=100.4, ma10=100.0, ma20=99.5, ma20_prev=99.4,
            buy_rate_10s=900,
            sell_rate_10s=100, buy_ratio_10s=0.90, flow_grace_sec=4.9)
        self.assertEqual(decide_exit(trailing).action, "HOLD")
        self.assertEqual(
            decide_exit(replace(trailing, flow_grace_sec=5.0)).reason,
            "MA_FLOW_ATR_TRAIL")

    def test_close_protection_requires_full_trend_support(self):
        weak = replace(self.base, observed_time=time(15, 10), ma5=101.5)
        self.assertEqual(decide_exit(weak).reason, "CLOSE_PROTECT_1510")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""1번->2번 저점찾기 다리 잠금 시험.

★[2026-08-06 친구님 지시 "1·2가 매매 방법은 같지만 매수 깊이만 서로 다른 거야"]
  이 시험이 지키는 것 다섯:
   ① 깃발 기본은 꺼짐 — S01 고유의 빠른 진입이 기본이다
   ② 판정을 베끼지 않는다(2번 모듈을 import 해서 부른다)
   ③ 1번 틱이 2번에 필요한 4개 열을 나른다(ask_tot·bid_tot·buy_vol_cum·sell_vol_cum)
   ④ 깊이 띠(DIP_TOO_DEEP_S02_ZONE)가 관문 목록에 남아 있다 — 이게 1·2번 칸막이다
   ⑤ 기준값(시가/장중고점)을 따로 넘긴다 — 같은 값을 주면 재현이 깨진다
  자료 파일이 없어도 전부 검사된다 — 다른 세션이 코드를 고치면 자료 없이도 걸린다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

SIGNAL = RUN / "strategy_01_open_surge_signal_v2.py"
BUY = RUN / "strategy_01_open_surge_buy_v1.py"


class S01LowfindBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SIGNAL.exists(), "1번 신호기가 사라졌다")
        self.src = SIGNAL.read_text(encoding="utf-8")
        self.buy_src = BUY.read_text(encoding="utf-8")

    # ① S01 고유의 빠른 방법이 기본이어야 한다.
    #    S01의 -3% 하한과 S02의 -3% 시작 문턱을 직렬 연결하면 교집합이 한 점뿐이다.
    def test_s01_native_method_is_the_default(self) -> None:
        self.assertIn('os.environ.get("S01_USE_S02_LOWFIND", "NO")', self.src,
                      "기본값이 NO 가 아니다 - S01/S02 상충 배선이 다시 켜졌다")
        import os
        import strategy_01_open_surge_signal_v2 as S1
        if os.environ.get("S01_USE_S02_LOWFIND"):
            self.skipTest("이 셸에 비교 실험 환경변수가 걸려 있다")
        self.assertFalse(S1.USE_S02_LOWFIND, "기본 상태인데 S02 다리가 켜져 있다")

    # ①-2 S02 비교 실험 스위치는 살아 있어야 한다
    def test_s02_opt_in_switch_still_exists(self) -> None:
        self.assertIn('"YES", "Y", "1", "TRUE", "ON"', self.src,
                      "명시적인 YES 비교 실험 스위치가 사라졌다")

    # ② 판정을 베껴 쓰지 않았는가
    def test_calls_real_s02_module_not_a_copy(self) -> None:
        self.assertIn("import strategy_02_low_buy_signal_v1", self.src,
                      "2번 모듈을 import 하지 않는다 = 판정을 재구현했다는 뜻")
        self.assertIn("LowBuySignalMonitor()", self.src,
                      "2번 판정기를 만들지 않는다")
        self.assertIn("mon.process_point(", self.src,
                      "2번의 process_point 를 부르지 않는다")

    # ③ 자료를 실어 나르는가 — 하나라도 빠지면 2번이 눈을 감는다
    def test_tick_carries_fields_s02_needs(self) -> None:
        for col in ("ask_tot", "bid_tot", "buy_vol_cum", "sell_vol_cum"):
            self.assertIn(f"{col}=", self.src, f"1번 틱이 {col} 을 안 나른다")
            self.assertIn(f'raw.get("{col}")', self.src,
                          f"스냅샷에서 {col} 을 안 읽는다")

    # ④ 칸막이 — 깊이 띠가 관문에서 빠지면 1번이 2번 영역을 침범한다
    def test_depth_band_stays_a_gate(self) -> None:
        self.assertIn("DIP_TOO_DEEP_S02_ZONE", self.buy_src,
                      "깊이 띠 사유가 사라졌다 - 부등호가 도로 뒤집혔을 수 있다")
        self.assertIn("S01_GATE_STOP_REASONS", self.src,
                      "관문 목록이 사라졌다")
        head = self.src.split("S01_GATE_STOP_REASONS", 1)[1][:400]
        self.assertIn("DIP_TOO_DEEP_S02_ZONE", head,
                      "깊이 띠가 관문 목록에서 빠졌다 = 깊게 빠진 것도 1번이 산다")

    # ⑤ 기준값 분리 — 같은 값을 주면 재현이 깨진다(재생기에서 실제로 겪은 사고)
    def test_open_and_session_high_are_separate(self) -> None:
        self.assertIn("open_price=state.open_price", self.src,
                      "시가 기준을 안 넘긴다")
        self.assertIn("session_high=state.high_so_far", self.src,
                      "장중고점 기준을 안 넘긴다")


if __name__ == "__main__":
    unittest.main()

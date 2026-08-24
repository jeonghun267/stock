# -*- coding: utf-8 -*-
"""공용 슬롯 장부 - 전략이 서로 같은 종목을 겹쳐 사지 않는다.

★[2026-08-06 친구님 지시 "6번하고 3번 급락이 겹칠 수 있는데 중복 매수만 안 하게 해줘"]
  S03(골짜기 급락)와 S06(급락 저점추격)는 같은 급락 종목을 동시에 노릴 수 있다.
  겹치는 것 자체는 괜찮고(먼저 잡는 쪽이 임자), '둘 다 사는 것'만 막으면 된다.

  이 시험이 지키는 것:
   ① 다른 전략이 이미 잡은 종목은 acquire 가 False - 두 번째 전략은 못 산다
   ② 같은 전략이 다시 부르면 True - 재매수(로테이션)는 막지 않는다
   ③ 슬롯을 반환하면 다른 전략이 가져갈 수 있다
   ④ 총 슬롯 수를 넘겨 잡을 수 없다
  ⚠️실제 장부(data\shared_slots.json)는 절대 건드리지 않는다 - 임시 파일로만 돈다.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

TODAY = "20260806"
S03 = "STRATEGY03"
S06 = "S06_CRASH_LOW_CHASE"


class SharedSlotsNoDoubleBuyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("SHARED_SLOTS_FILE")
        os.environ["SHARED_SLOTS_FILE"] = str(Path(self._tmp.name) / "slots.json")
        import shared_slots
        self.slots = importlib.reload(shared_slots)      # 새 경로로 다시 읽는다
        self.assertNotIn("stock_bot\\data", str(self.slots.FILE),
                         "실제 장부를 가리키고 있다 - 시험이 실전을 건드린다")

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop("SHARED_SLOTS_FILE", None)
        else:
            os.environ["SHARED_SLOTS_FILE"] = self._saved
        self._tmp.cleanup()
        import shared_slots
        importlib.reload(shared_slots)                   # 원래 경로로 되돌린다

    # ① 핵심 - 3번이 잡은 종목을 6번이 못 산다
    def test_other_strategy_cannot_take_same_code(self) -> None:
        self.assertTrue(self.slots.acquire("005930", S03, TODAY))
        self.assertFalse(self.slots.acquire("005930", S06, TODAY),
                         "3번이 잡은 종목을 6번이 또 샀다 = 중복 매수")

    # ①-2 반대 방향도 같다
    def test_block_works_both_ways(self) -> None:
        self.assertTrue(self.slots.acquire("000660", S06, TODAY))
        self.assertFalse(self.slots.acquire("000660", S03, TODAY),
                         "6번이 잡은 종목을 3번이 또 샀다 = 중복 매수")

    # ② 같은 전략의 재매수는 막지 않는다(로테이션)
    def test_same_strategy_may_reenter(self) -> None:
        self.assertTrue(self.slots.acquire("035720", S03, TODAY))
        self.assertTrue(self.slots.acquire("035720", S03, TODAY),
                        "같은 전략의 재매수까지 막혔다")

    # ③ 반환하면 다른 전략이 가져간다
    def test_release_hands_over(self) -> None:
        self.assertTrue(self.slots.acquire("068270", S03, TODAY))
        self.assertFalse(self.slots.acquire("068270", S06, TODAY))
        self.slots.release("068270", TODAY)
        self.assertTrue(self.slots.acquire("068270", S06, TODAY),
                        "반환했는데도 다른 전략이 못 가져간다")

    # ④ 총 슬롯 상한
    def test_pool_is_capped(self) -> None:
        codes = [f"{i:06d}" for i in range(1, self.slots.MAX + 2)]
        got = [self.slots.acquire(c, S03, TODAY) for c in codes]
        self.assertEqual(sum(1 for x in got if x), self.slots.MAX,
                         "슬롯 상한을 넘겨 잡았다")

    # 코드 자리수가 달라도 같은 종목으로 본다
    def test_code_is_normalised(self) -> None:
        self.assertTrue(self.slots.acquire("5930", S03, TODAY))
        self.assertFalse(self.slots.acquire("005930", S06, TODAY),
                         "자리수만 다른 같은 종목을 다른 종목으로 봤다")


if __name__ == "__main__":
    unittest.main()

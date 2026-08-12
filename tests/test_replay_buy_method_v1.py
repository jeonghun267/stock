# -*- coding: utf-8 -*-
"""매수방법 재생기 잠금 시험.

★[2026-08-06 친구님 지시 "재생기를 고정시켜라 · 손 못 대게"]
  이 시험이 지키는 것 넷:
   ① 재생기가 계약서의 '이미 아는 정답'을 여전히 재현한다
   ② 판정 로직을 재구현하지 않는다(실제 전략 모듈을 import 한다)
   ③ 1초 캡처를 utf-8-sig 로 연다(BOM 때문에 ts 가 사라지는 8/6 사고 재발 방지)
   ④ 기준값(시가/장중고점)을 분리해서 넘긴다
  ②③④ 는 캡처 파일이 없어도 검사된다 — 다른 세션이 코드를 고치면 자료 없이도 걸린다.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

ENGINE = RUN / "replay_buy_method_v1.py"
CONTRACT = ROOT / "config" / "replay_contract_v1.json"


class ReplayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(ENGINE.exists(), "재생기가 사라졌다: RUN\\replay_buy_method_v1.py")
        self.assertTrue(CONTRACT.exists(), "계약서가 사라졌다: config\\replay_contract_v1.json")
        self.src = ENGINE.read_text(encoding="utf-8")
        self.spec = json.loads(CONTRACT.read_text(encoding="utf-8"))

    # ② 판정을 베껴 쓰지 않았는가
    def test_uses_real_strategy_module_not_a_copy(self) -> None:
        self.assertIn("import strategy_02_low_buy_signal_v1", self.src,
                      "실제 전략 모듈을 import 하지 않는다 = 판정을 재구현했다는 뜻")
        self.assertIn("mon.process_point(", self.src,
                      "전략의 process_point 를 부르지 않는다")

    # ③ BOM 처리 — 8/6 에 이것 때문에 재생이 조용히 0틱이었다
    def test_capture_opened_with_utf8_sig(self) -> None:
        self.assertIn('encoding="utf-8-sig"', self.src,
                      "1초 캡처를 utf-8-sig 로 열지 않으면 BOM 때문에 ts 열이 사라진다")

    # ④ 기준값 분리 — 같은 값을 주면 재현이 깨진다
    def test_open_and_high_reference_are_separate(self) -> None:
        self.assertIn("open_price=", self.src)
        self.assertIn("session_high=", self.src)
        self.assertIn("open_ref", self.src)
        self.assertIn("high_ref", self.src)

    # 계약서가 비어 있거나 대조가 빠지지 않았는가
    def test_contract_has_reproduction_cases(self) -> None:
        cases = self.spec.get("재현대조") or {}
        self.assertGreaterEqual(len(cases), 4, "재현 대조 사례가 4건 미만이다")
        for code, want in cases.items():
            for key in ("낙폭", "엔진시가", "엔진고점", "이름"):
                self.assertIn(key, want, f"{code} 에 {key} 가 없다")

    # ⑤ 저점 대조가 살아 있는가
    #    ★[2026-08-06 친구님 "중요한 것은 어느 게 저점을 잘 잡는냐는거야"]
    #      실현손익만 남기고 매수가 대조를 빼면 이 질문에 답을 못 한다.
    def test_buy_price_comparison_is_present(self) -> None:
        for token, why in (
            ("def s01_buys", "S01 실제 매수가를 안 뽑으면 대조 자체가 불가능하다"),
            ("def day_low", "그날 진짜 저점을 안 만들면 저점 근접도를 못 낸다"),
            ("맞대결", "두 방법이 둘 다 산 건만 고르는 공정 비교가 사라졌다"),
        ):
            self.assertIn(token, self.src, why)

    # ⑥ 승자편향 방지 — 2번이 안 산 건을 평균에 섞으면 안 된다
    def test_no_winner_bias_in_average(self) -> None:
        self.assertIn("no_signal", self.src,
                      "2번이 안 산 건수를 따로 세지 않는다 = 평균에 섞였을 수 있다")
        spec_rules = json.dumps(self.spec.get("절대규칙") or {}, ensure_ascii=False)
        self.assertIn("승자편향", spec_rules, "계약서에서 승자편향 금지 규칙이 사라졌다")

    # ① 실제 재현 — 캡처가 있을 때만(없으면 건너뜀)
    def test_reproduces_known_signals(self) -> None:
        date = self.spec["기준일"]
        cap = ROOT / "data" / "shadow" / "mf_1s_capture" / f"mf_1s_{date}.csv"
        cache = ROOT / "data" / "replay_cache"
        have_cache = cache.exists() and any(cache.glob(f"{date}_*.csv"))
        if not cap.exists() and not have_cache:
            self.skipTest(f"1초 캡처도 캐시도 없다({date}) — 재현 검증 건너뜀")
        import replay_buy_method_v1 as R
        self.assertTrue(R.verify(verbose=False),
                        "계약서의 이미 아는 정답을 재현하지 못한다 = 재생기를 믿을 수 없다")


if __name__ == "__main__":
    unittest.main()

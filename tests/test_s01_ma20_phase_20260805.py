# -*- coding: utf-8 -*-
"""S01 도 20선을 국면별로 나눠 쓴다 — 잠금 시험.

지우기 전에 읽을 것
  8/5 에 지시가 둘이었고 서로 어긋나 있었다.
    (가) "지금 켜"  — S01 만 20선 단계를 상승보유에 다시 넣어라.
    (나) "이 해제는 매도(꼭지) 상황에서만이지 손실방어 국면엔 적용 안 한다."
  (가)대로면 S01 은 꼭지 국면에서도 20선으로 버텨 이익을 반납한다. 그날 밤
  친구님 지시 "남은 어긋남 지금 해결 해" 로 (나)에 맞춰 통일했다.

지키는 규칙
  · 꼭지용 daily_ma_permit  -> allow_ma20 을 안 붙인다(20선만 걸친 상태는 보유 없음)
  · 손실방어용 ma20_defense_permit -> allow_ma20=True (20선 지지면 버틴다)
  이제 S01·S02·S05 가 같은 규칙이다.
  ⚠️S04 는 Strategy01Engine 을 그대로 쓰므로 같이 바뀐다
    (strategy_04_rotation_engine_v1.py 가 Strategy01Engine 을 직접 생성한다).

되돌리기: RUN\\backup\\strategy_01_rotation_engine_v2_20260805_before_s01_ma20_phase.py
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN_DIR = ROOT / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_01_rotation_engine_v2 as s01  # noqa: E402


class S01Ma20PhaseTests(unittest.TestCase):

    # ── ① 꼭지용 경로: 부를 때 20선을 켜지 않는다 ────────────────────────
    def test_peak_permit_does_not_allow_ma20(self):
        """_daily_ma_permit 이 allow_ma20 을 붙이지 않는지 실제로 불러서 본다.

        ma3_rider_permit 을 기록기로 바꿔치기해 넘어온 인자를 그대로 본다
        (소스를 읽는 게 아니라 실제 호출을 본다).
        """
        seen = {}

        def recorder(code, price, payload=None, buy_side=None, **kw):
            seen.update(kw)
            return True

        engine = object.__new__(s01.Strategy01Engine)   # __init__ 없이 껍데기만
        original = s01.ma3_rider_permit
        try:
            s01.ma3_rider_permit = recorder
            engine._daily_ma_permit("005930", 1000.0, buy_side=True)
        finally:
            s01.ma3_rider_permit = original

        self.assertNotIn(
            "allow_ma20", seen,
            "S01 꼭지용 상승보유가 20선을 다시 켰다 — 8/5 정정과 어긋난다")

    # ── ② 관측 만드는 자리: 두 값이 서로 다른 호출이어야 한다 ────────────
    def test_observation_splits_the_two_permits(self):
        """_build_observation 안에서 꼭지용과 손실방어용이 갈려 있는지.

        _build_observation 은 딸린 상태가 많아 통째로 부르기 어렵다. 그래서
        ast 로 그 함수만 떼어 두 곳의 모양을 본다.
          · ma20_defense_permit= 에 대입되는 호출에는 allow_ma20=True 가 있어야 하고
          · daily_ma_permit= 에 들어가는 값에는 없어야 한다.
        """
        tree = ast.parse(
            (RUN_DIR / "strategy_01_rotation_engine_v2.py").read_text(
                encoding="utf-8"))
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_build_observation"),
            None)
        self.assertIsNotNone(fn, "_build_observation 을 못 찾음")

        defense, peak_name = None, None
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "ma20_defense_permit":
                    defense = kw.value
                elif kw.arg == "daily_ma_permit":
                    peak_name = kw.value

        self.assertIsInstance(
            defense, ast.Call,
            "ma20_defense_permit 이 호출로 직접 채워져 있지 않다 — 아침 계약 "
            "검사가 그 호출을 꼭지용으로 잘못 세게 된다")
        self.assertTrue(
            any(kw.arg == "allow_ma20" for kw in defense.keywords),
            "손실방어용인데 allow_ma20 이 없다")
        self.assertIsInstance(
            peak_name, ast.Name,
            "daily_ma_permit 이 지역변수에서 오지 않는다 — 아래 검사가 무의미해짐")

        # 그 지역변수를 만든 호출을 찾아 allow_ma20 이 없는지 본다.
        target = peak_name.id
        made = [
            n.value for n in ast.walk(fn)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
            and any(isinstance(t, ast.Name) and t.id == target for t in n.targets)
        ]
        self.assertEqual(len(made), 1, f"{target} 을 만드는 자리가 1개가 아니다")
        self.assertFalse(
            any(kw.arg == "allow_ma20" for kw in made[0].keywords),
            f"꼭지용 {target} 에 allow_ma20 이 붙어 있다 — 8/5 정정과 어긋난다")


if __name__ == "__main__":
    unittest.main(verbosity=2)

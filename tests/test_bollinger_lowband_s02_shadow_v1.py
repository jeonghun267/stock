# -*- coding: utf-8 -*-
"""볼린저 하단 × S02 그림자 집중 테스트 (8/13 승인 사양의 '집중 테스트 1개').

핵심 강제 사항: ①주문 API import/호출 금지(소스 검사) ②밴드·상태 계산 ③일봉 최신성 fail-closed.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import bollinger_lowband_s02_shadow_v1 as shadow


class BollingerLowbandS02ShadowTests(unittest.TestCase):
    def test_source_never_touches_order_apis(self):
        """승인 사양: 주문 API import·호출 금지 — 소스 검사로 강제."""
        source = (RUN_DIR / "bollinger_lowband_s02_shadow_v1.py").read_text(
            encoding="utf-8")
        for forbidden in ("broker_client", "BrokerClient", "SENDORDER",
                          "SendOrder", "submit(", "ipc_order_auth",
                          "IPC\\requests", "broker_gateway"):
            self.assertNotIn(forbidden, source, f"주문 경로 접촉 금지: {forbidden}")

    def test_bollinger_lower_and_state(self):
        closes = [100.0] * 19 + [100.0]
        self.assertAlmostEqual(shadow.bollinger_lower(closes), 100.0)  # σ=0
        self.assertIsNone(shadow.bollinger_lower(closes[:19]))  # 20개 미만 → 밴드 없음
        varied = [100 + (1 if i % 2 else -1) for i in range(20)]  # 평균100, σ=1
        lower = shadow.bollinger_lower([float(v) for v in varied])
        self.assertAlmostEqual(lower, 98.0)
        self.assertEqual(shadow.classify_bb_state(97.9, lower), "BELOW")
        self.assertEqual(shadow.classify_bb_state(98.5, lower), "NEAR")  # +0.51%
        self.assertEqual(shadow.classify_bb_state(99.5, lower), "OUTSIDE")
        self.assertEqual(shadow.classify_bb_state(100.0, None), "NO_BAND")

    def test_daily_freshness_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            # 직전 거래일 증거: 8/12 스냅샷 존재 (8/13 사고 재현 — 일봉은 8/11에 멈춤)
            (data_dir / "high_range_shadow_20260812.csv").write_text("", encoding="utf-8")
            ok, reason = shadow.check_daily_freshness(
                "20260813", {"20260811", "20260810"}, data_dir)
            self.assertFalse(ok)
            self.assertIn("20260811", reason)
            # 정상: 일봉 최신일 = 직전 거래일
            ok2, _ = shadow.check_daily_freshness(
                "20260813", {"20260812", "20260811"}, data_dir)
            self.assertTrue(ok2)
            # 연휴 건너뛰기: 8/18 실행, 직전 거래일 8/14 (8/15~17 스냅샷 없음)
            (data_dir / "high_range_shadow_20260814.csv").write_text("", encoding="utf-8")
            ok3, _ = shadow.check_daily_freshness(
                "20260818", {"20260814"}, data_dir)
            self.assertTrue(ok3)


if __name__ == "__main__":
    unittest.main()

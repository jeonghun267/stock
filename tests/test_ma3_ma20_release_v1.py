# -*- coding: utf-8 -*-
"""★[MA20-RELEASE 2026-08-04] 20선만 걸친 단계에서는 상승보유를 주지 않는다.

친구님 지시: "20선 막힌거 풀어야 돼. 그래야 매도를 잘할 수 있어."

왜 필요한가 — 상승보유가 참이면 공통매도의 _daily_ma_hold_rule 이 HOLD 를 돌려주고,
그 뒤에 있는 수급역전·꼭지 매도가 통째로 막힌다. 5선·10선을 다 내주고 20선에만
겨우 걸친 종목까지 그렇게 묶으면 잘 팔지도 못한다.
5선·10선 지지는 종전 그대로 유지되는지도 같이 시험한다(과잉 수정 방지).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ma3_common_v1 import line_support_stage, rider_permit  # noqa: E402


CODE = "005930"


def payload(closes: list[float], live: float) -> dict:
    """완성 1분봉을 3분 간격으로 놓아 3분봉 N개를 만든다(pm 라벨 필수)."""
    bars, labels = [], []
    minute = 9 * 60          # 09:00 부터
    for close in closes:
        bars.append([close, close, close, close])
        labels.append(f"20260804{minute // 60:02d}{minute % 60:02d}")
        minute += 3
    return {
        "ts": "2026-08-04 14:00:00",
        "hm": "1400",
        "m": {CODE: {"prev": bars, "pm": labels, "c": live}},
    }


class MA20ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        # 우상향 20선을 만든다: 100 부터 1씩 오르는 완성봉 24개
        self.rising = [100.0 + i for i in range(24)]

    def stage(self, price: float) -> str:
        return line_support_stage(CODE, price, payload(self.rising, price))

    def permit(self, price: float, **kw) -> bool:
        return rider_permit(CODE, price, payload(self.rising, price),
                            buy_side=True, **kw)

    # ── 해제되어야 하는 경우 ──────────────────────────────────────────────

    def test_ma20_stage_no_longer_holds(self):
        """20선에만 걸친 상태 = 상승보유 해제 → 뒤의 수급역전·꼭지 매도가 판단한다.

        친구님 확인: "20선 해제는 공용이라 전체를 켜도 돼" — S01~S06 전부 적용.
        """
        price = self._price_for_stage("MA20")
        self.assertEqual("MA20", self.stage(price), "시험 전제가 깨졌다")
        self.assertFalse(
            self.permit(price), "20선 단계에서 상승보유가 남으면 매도가 막힌다")

    def test_ma20_can_be_restored_per_strategy(self):
        """되돌리기 — 그 전략만 allow_ma20=True 로 부르면 종전 동작."""
        price = self._price_for_stage("MA20")
        self.assertTrue(self.permit(price, allow_ma20=True))

    # ── 그대로 유지되어야 하는 경우 (과잉 수정 방지) ──────────────────────

    def test_ma5_stage_still_holds(self):
        price = self._price_for_stage("MA5")
        self.assertEqual("MA5", self.stage(price))
        self.assertTrue(self.permit(price), "5선 지지는 손대지 않기로 했다")

    def test_ma10_stage_still_holds(self):
        price = self._price_for_stage("MA10")
        self.assertEqual("MA10", self.stage(price))
        self.assertTrue(self.permit(price), "10선 지지는 손대지 않기로 했다")

    def test_below_all_lines_never_holds(self):
        price = 1.0
        self.assertEqual("", self.stage(price))
        self.assertFalse(self.permit(price))

    def test_buy_side_gate_is_unchanged(self):
        """매수세가 아니면 선이 아무리 좋아도 보유 없음 — 종전 그대로."""
        price = self._price_for_stage("MA5")
        for buy_side in (False, None):
            with self.subTest(buy_side=buy_side):
                self.assertFalse(rider_permit(
                    CODE, price, payload(self.rising, price), buy_side=buy_side))

    # ── 도우미 ────────────────────────────────────────────────────────────

    def _price_for_stage(self, wanted: str) -> float:
        """원하는 지지 단계가 나오는 가격을 실제 판정기로 찾는다(추정 금지)."""
        for tick in range(1, 4000):
            price = tick * 0.5
            if line_support_stage(CODE, price, payload(self.rising, price)) == wanted:
                return price
        raise AssertionError(f"{wanted} 단계를 만드는 가격을 못 찾았다")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""★[SEED-FALLBACK 2026-08-04] 3분봉이 모자라면 공용 모듈이 전일 시드를 직접 쓴다.

친구님 지시: "분봉 부족한것도 공용에 들어가서 다른 전략들이 같이 쓸수 있어야 돼."

종전에는 시드를 08:28 기록기만 읽었다. 그 경로가 어긋나면(기록기 지연·재기동·
봉 누락) S01~S06 전부가 같이 판정 불가가 됐다(8/3 실측 0/200종목).
이제 ma3_rows 가 ①실시간 기록 ②백필 캐시 ③전일 시드 순으로 보고, 가장 많은
봉을 주는 것을 쓴다. 공용 모듈이라 어느 전략이든 같은 혜택을 받는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import ma3_common_v1 as m  # noqa: E402


CODE = "005930"


def bars(start_minute: int, closes: list[float], day: str) -> dict:
    """3분 간격 완성봉 + pm 시각표."""
    prev, labels = [], []
    minute = start_minute
    for close in closes:
        prev.append([close, close, close, close])
        labels.append(f"{day}{minute // 60:02d}{minute % 60:02d}")
        minute += 3
    return {"prev": prev, "pm": labels, "c": closes[-1] if closes else 0.0}


class SeedFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.seed_path = Path(self.temp.name) / "seed.json"
        # SEED_PATH 를 임시 파일로 갈아끼운다(호출 시점에 읽으므로 먹힌다).
        original = m.SEED_PATH
        m.SEED_PATH = self.seed_path
        self.addCleanup(setattr, m, "SEED_PATH", original)

        # 전일 정규장 완성봉 24개 (09:00 부터 3분 간격)
        self.seed_closes = [100.0 + i for i in range(24)]
        self.write_seed(self.seed_closes)

    def write_seed(self, closes: list[float], *, drop_pm: bool = False) -> None:
        row = bars(9 * 60, closes, "20260803")
        if drop_pm:
            row.pop("pm")
        self.seed_path.write_text(json.dumps({
            "ts": "2026-08-03 15:30:00", "hm": "1530", "m": {CODE: row},
        }, ensure_ascii=False), encoding="utf-8")

    def live(self, closes: list[float], hm: str = "0904") -> dict:
        """오늘 자료. hm 은 '지금 시각' — 이보다 뒤의 봉은 미래라 버려진다."""
        row = bars(9 * 60, closes, "20260804") if closes else {
            "prev": [], "pm": [], "c": 50_000.0}
        return {"ts": f"2026-08-04 {hm[:2]}:{hm[2:]}:00", "hm": hm,
                "m": {CODE: row}}

    # ── 시드가 구해줘야 하는 경우 ────────────────────────────────────────

    def test_seed_rescues_when_live_bars_are_short(self):
        """오늘 봉 2개뿐 = 종전이라면 판정 불가. 시드로 선이 선다."""
        payload = self.live([200.0, 201.0])
        self.assertLess(
            len(m.three_minute_closes(CODE, payload)), m.MIN_BLOCKS,
            "시험 전제: 오늘 자료만으로는 모자라야 한다")

        row = m.ma3_rows(CODE, payload)

        self.assertIsNotNone(row, "시드가 있는데도 판정 불가면 배선이 안 된 것")
        self.assertGreaterEqual(int(row["blocks"]), m.MIN_BLOCKS)

    def test_seed_rescue_makes_rider_judgeable(self):
        """상승보유가 실제로 판정 가능해지는지 — 이게 최종 목적이다."""
        payload = self.live([200.0, 201.0])
        row = m.ma3_rows(CODE, payload)
        price = float(row["ma5"]) * 1.05          # 5선 위
        self.assertEqual("MA5", m.line_support_stage(CODE, price, payload))

    def test_live_bars_win_when_they_are_enough(self):
        """오늘 자료가 충분하면 시드를 끌어오지 않는다(더 많은 쪽을 쓴다)."""
        # 09:00 부터 3분 간격 30봉 -> 마지막이 10:27. 지금 시각을 11:00 으로 둬야
        # 미래봉 필터에 안 걸린다.
        payload = self.live([300.0 + i for i in range(30)], hm="1100")
        live_only = len(m.three_minute_closes(CODE, payload))
        row = m.ma3_rows(CODE, payload)

        self.assertGreaterEqual(live_only, m.MIN_BLOCKS, "시험 전제")
        self.assertEqual(live_only, int(row["blocks"]))

    # ── 시드를 믿으면 안 되는 경우 ──────────────────────────────────────

    def test_seed_without_time_labels_is_ignored(self):
        """pm(시각표)이 없으면 3분 격자가 어긋난다 — 쓰지 않는다(기존 원칙)."""
        self.write_seed(self.seed_closes, drop_pm=True)
        self.assertIsNone(m.ma3_rows(CODE, self.live([200.0, 201.0])))

    def test_missing_seed_file_still_fails_closed(self):
        self.seed_path.unlink()
        self.assertIsNone(m.ma3_rows(CODE, self.live([200.0, 201.0])))

    def test_other_code_not_in_seed_fails_closed(self):
        payload = {"ts": "2026-08-04 09:04:00", "hm": "0904",
                   "m": {"999999": {"prev": [], "pm": [], "c": 100.0}}}
        self.assertIsNone(m.ma3_rows("999999", payload))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""[공통배관 잠금 2026-08-07 친구님 지시 "전 전략이 다 같이 써야 돼. 공통으로 넣어."]

intraday_anchor_v1(시가·당일저가·당일고가 공통 배관)의 동작을 잠근다.

★왜 있나: S06 이 실황판(30종목) 밖 종목의 진짜 시가·저가를 몰라서
  8/7 명단 확장이 "눈은 늘렸는데 자를 잘못 줬다"로 끝났다. 이 모듈이 그 구멍을 메운다.
  소스 우선순위(실황판→스냅샷→자체관측)는 "원래 30종목의 종전 동작 보존"이 이유다 —
  순서를 바꾸면 기존 성적과의 비교 기준선이 깨진다. 지우기 전에 memory.md 8/7 밤 참조.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from intraday_anchor_v1 import day_anchor  # noqa: E402


def _write(dirpath: str, name: str, obj: dict) -> Path:
    path = Path(dirpath) / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class TestDayAnchor(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        d = self.td.name
        self.hr = _write(d, "hr.json", {"date": "20260807", "codes": {
            "119850": {"first_price": 53200.0, "low": 50500.0, "high": 57800.0},
        }})
        self.snap = _write(d, "snap.json", {"codes": {
            # 실황판과 값이 다르게 심어 우선순위가 실제로 실황판인지 가른다
            "119850": {"ts": "2026-08-07T10:00:00", "op": 11111.0, "lo": 1.0, "hi": 99999.0},
            "214450": {"ts": "2026-08-07T10:00:00",
                       "op": 396500.0, "lo": 333000.0, "hi": 410000.0},
        }})

    def tearDown(self):
        self.td.cleanup()

    def _anchor(self, code, today="20260807"):
        return day_anchor(code, today=today,
                          hr_state_path=self.hr, snapshot_path=self.snap)

    def test_실황판이_있으면_실황판_값이다(self):
        a = self._anchor("119850")
        self.assertEqual((a.open, a.low, a.high), (53200.0, 50500.0, 57800.0))
        self.assertEqual((a.source_open, a.source_low, a.source_high),
                         ("실황판", "실황판", "실황판"))

    def test_실황판_밖_종목은_스냅샷_거래소값이다(self):
        a = self._anchor("214450")            # 8/7 파마리서치 유형(감시망 밖 최대 급락주)
        self.assertEqual((a.open, a.low, a.high), (396500.0, 333000.0, 410000.0))
        self.assertEqual(a.source_low, "스냅샷")

    def test_둘_다_없으면_0과_자체관측이다(self):
        a = self._anchor("000001")
        self.assertEqual((a.open, a.low, a.high), (0.0, 0.0, 0.0))
        self.assertEqual(a.source_open, "자체관측")

    def test_날짜가_어긋난_실황판은_무시한다(self):
        # 아침 첫 기동 때 전일 잔존 파일이 기준가를 오염시키는 것 방지
        a = self._anchor("119850", today="20260808")
        self.assertEqual(a.open, 0.0)
        self.assertEqual(a.source_open, "자체관측")

    def test_날짜가_어긋난_스냅샷_행도_무시한다(self):
        a = self._anchor("214450", today="20260808")
        self.assertEqual((a.open, a.low, a.high), (0.0, 0.0, 0.0))

    # ★[정합성 2026-08-07 보안검사 지적] 이 값은 S06 무장 판정과 매수구간에 그대로
    #   들어가는데 읽는 두 파일은 UserK 가 쓸 수 있다. 앞뒤가 안 맞는 소스는 버린다.

    def test_앞뒤가_안맞는_실황판은_통째로_버리고_스냅샷으로_내려간다(self):
        _write(self.td.name, "hr.json", {"date": "20260807", "codes": {
            "214450": {"first_price": 396500.0, "low": 999999.0, "high": 1.0},
        }})
        a = self._anchor("214450")
        self.assertEqual((a.open, a.low, a.high), (396500.0, 333000.0, 410000.0))
        self.assertEqual(a.source_low, "스냅샷")

    def test_시가가_저가와_고가_밖이면_그_소스를_버린다(self):
        """시가만 조작해도 S06 낙폭(저가/시가-1)이 통째로 휜다."""
        _write(self.td.name, "snap.json", {"codes": {
            "214450": {"ts": "2026-08-07T10:00:00",
                       "op": 800000.0, "lo": 333000.0, "hi": 410000.0},
        }})
        a = self._anchor("214450")
        self.assertEqual((a.open, a.low, a.high), (0.0, 0.0, 0.0))
        self.assertEqual(a.source_low, "자체관측")

    def test_음수를_양수로_바꾸지_않는다(self):
        """abs() 로 감싸면 이상값이 정상으로 보인다."""
        _write(self.td.name, "snap.json", {"codes": {
            "214450": {"ts": "2026-08-07T10:00:00",
                       "op": 396500.0, "lo": -333000.0, "hi": 410000.0},
        }})
        a = self._anchor("214450")
        self.assertEqual(a.low, 0.0)

    def test_한_필드만_버리고_짝이_안맞는_조합을_남기지_않는다(self):
        """저가만 버리고 실황판 시가와 스냅샷 저가를 섞으면 낙폭이 엉뚱해진다."""
        _write(self.td.name, "hr.json", {"date": "20260807", "codes": {
            "214450": {"first_price": 396500.0, "low": 0.0, "high": 410000.0},
        }})
        a = self._anchor("214450")
        self.assertEqual(a.source_open, a.source_low)
        self.assertEqual((a.open, a.low, a.high), (396500.0, 333000.0, 410000.0))


if __name__ == "__main__":
    unittest.main()

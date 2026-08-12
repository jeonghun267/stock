# -*- coding: utf-8 -*-
r"""[DAY-GATE 잠금 2026-08-08 친구님 승인 "화요일부터 ON"]

S02 하락일 게이트가 살아 있는지 + 안전 기본값을 지킨다.

★왜 이 시험이 있나 — 지우기 전에 반드시 읽을 것
  12일 재생(신호 1,088건): S02 는 하락일(아침 깨진반등률 47%↑)에 크게 잃는다.
    · 게이트 없음: 건당기대 -0.315%  /  게이트 적용: +0.016% (적자→흑자 전환)
    · 최악 이틀 7/28·7/29(승률 32%)를 09:30 판정이 정확히 포착했다
  판정기: RUN\day_judge_v1.py (태스크 SAFEPLUS_DAY_JUDGE 09:32)
  게이트: RUN\strategy_02_rotation_engine_v1.py day_gate_blocked + _try_entries 오버라이드

  ⚠️안전 원칙(이 시험이 지키는 것):
    1) 스위치 기본값은 꺼짐 — S02_DAYGATE 없으면 절대 아무것도 안 바꾼다
    2) 판정 파일이 없으면 차단 안 함 (판정기 죽어도 매수는 정상)
    3) 매도·보유는 건드리지 않는다 — 차단 대상은 신규 진입(_try_entries)뿐

정말로 되돌려야 한다면: 이 시험을 지우지 말고 memory.md 에 이유를 먼저 적을 것.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_02_rotation_engine_v1 as s02


class DayGateTest(unittest.TestCase):
    def setUp(self):
        self._old_dir = s02._DAY_GATE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        s02._DAY_GATE_DIR = Path(self._tmp.name)
        self._old_env = os.environ.get("S02_DAYGATE")

    def tearDown(self):
        s02._DAY_GATE_DIR = self._old_dir
        if self._old_env is None:
            os.environ.pop("S02_DAYGATE", None)
        else:
            os.environ["S02_DAYGATE"] = self._old_env
        self._tmp.cleanup()

    def _write(self, date, suspect):
        path = Path(self._tmp.name) / ("day_judge_%s.json" % date)
        path.write_text(
            json.dumps({"date": date, "suspect": suspect}), encoding="utf-8")

    def test_default_off_never_blocks(self):
        """스위치 없음(기본값) = 하락일이어도 절대 차단 안 함."""
        os.environ.pop("S02_DAYGATE", None)
        self._write("20260810", True)
        self.assertFalse(s02.day_gate_blocked(datetime(2026, 8, 10, 10, 0)))

    def test_on_suspect_blocks_after_0932(self):
        os.environ["S02_DAYGATE"] = "YES"
        self._write("20260810", True)
        self.assertTrue(s02.day_gate_blocked(datetime(2026, 8, 10, 9, 32)))
        self.assertTrue(s02.day_gate_blocked(datetime(2026, 8, 10, 14, 0)))

    def test_on_before_0932_not_blocked(self):
        """판정이 나오기 전(09:32 이전)에는 차단하지 않는다."""
        os.environ["S02_DAYGATE"] = "YES"
        self._write("20260810", True)
        self.assertFalse(s02.day_gate_blocked(datetime(2026, 8, 10, 9, 31, 59)))

    def test_on_normal_day_not_blocked(self):
        os.environ["S02_DAYGATE"] = "YES"
        self._write("20260810", False)
        self.assertFalse(s02.day_gate_blocked(datetime(2026, 8, 10, 10, 0)))

    def test_on_missing_file_not_blocked(self):
        """판정기가 죽어 파일이 없으면 차단 안 함(안전측)."""
        os.environ["S02_DAYGATE"] = "YES"
        self.assertFalse(s02.day_gate_blocked(datetime(2026, 8, 10, 10, 0)))

    def test_gate_hook_alive(self):
        """게이트 훅(_try_entries 오버라이드)이 엔진에서 지워지면 빨갛게."""
        self.assertIn("_try_entries", vars(s02.Strategy02Engine))

    def test_gate_only_touches_entries(self):
        """매도 경로에는 게이트가 없어야 한다 — 오버라이드는 _try_entries 하나뿐."""
        overridden = {
            name for name in vars(s02.Strategy02Engine)
            if name.startswith("_") and name in (
                "_start_sell", "_sell_pending_step", "_force_exit_step")
        }
        self.assertEqual(overridden, set())


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from strategy_open_priority_v1 import OpenPriorityGate, S01, S03


KST = ZoneInfo("Asia/Seoul")


def row(code: str, signal_id: str) -> dict:
    return {"code": code, "signal_id": signal_id, "name": code}


class OpenPriorityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "priority.json"
        self.now = datetime(2026, 8, 19, 9, 0, 0, tzinfo=KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_s01_waits_three_seconds_and_uses_current_top(self) -> None:
        gate = OpenPriorityGate(self.path, wait_sec=3, mode="LIVE")
        first = gate.evaluate(
            strategy_id=S01, rows=[row("111111", "a")], now=self.now
        )
        second = gate.evaluate(
            strategy_id=S01,
            rows=[row("222222", "b"), row("111111", "a")],
            now=self.now + timedelta(seconds=2),
        )
        final = gate.evaluate(
            strategy_id=S01,
            rows=[row("222222", "b"), row("111111", "a")],
            now=self.now + timedelta(seconds=3),
        )
        self.assertTrue(first.waiting)
        self.assertTrue(second.waiting)
        self.assertEqual([], list(second.rows))
        self.assertFalse(final.waiting)
        self.assertEqual("222222", final.rows[0]["code"])

    def test_s03_is_immediate_and_has_priority_in_s01_window(self) -> None:
        gate = OpenPriorityGate(self.path, wait_sec=3, mode="LIVE")
        gate.evaluate(
            strategy_id=S01, rows=[row("111111", "a")], now=self.now
        )
        s03 = gate.evaluate(
            strategy_id=S03,
            rows=[row("333333", "c"), row("444444", "d")],
            now=self.now + timedelta(seconds=2),
        )
        s01 = gate.evaluate(
            strategy_id=S01,
            rows=[row("111111", "a")],
            now=self.now + timedelta(seconds=3),
        )
        self.assertEqual("333333", s03.rows[0]["code"])
        self.assertTrue(s01.s03_priority_seen)
        self.assertEqual("S03_PRIORITY_OBSERVED", s01.reason)

    def test_shadow_never_changes_order_capable_rows(self) -> None:
        gate = OpenPriorityGate(self.path, wait_sec=3, mode="SHADOW")
        rows = [row("111111", "a"), row("222222", "b")]
        result = gate.evaluate(strategy_id=S01, rows=rows, now=self.now)
        self.assertEqual(rows, list(result.rows))
        self.assertTrue(result.reason.startswith("SHADOW_"))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import stockbot_live_broadcast_v1 as broadcast


class StockbotLiveBroadcastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.desktop = self.root / "Desktop"
        (self.root / "data").mkdir()
        (self.root / "config").mkdir()
        (self.root / "LOG").mkdir()
        self.patches = (
            patch.object(broadcast, "BASE", self.root),
            patch.object(broadcast, "DESKTOP", self.desktop),
            patch.object(broadcast, "DATA", self.root / "data"),
            patch.object(broadcast, "CONFIG", self.root / "config"),
            patch.object(broadcast, "LOG_DIR", self.root / "LOG"),
            patch.object(broadcast, "SNAP_TEXT", self.desktop / "스톡봇_중계.txt"),
            patch.object(broadcast, "SNAP_HTML", self.desktop / "스톡봇_중계.html"),
            patch.object(broadcast, "TAPE", self.desktop / "스톡봇_중계_기록.txt"),
            patch.object(broadcast, "LEGACY_HTML", self.desktop / "캡틴2_중계.html"),
            patch.object(broadcast, "SHARED_SLOTS", self.root / "data" / "shared_slots.json"),
            patch.object(broadcast, "NAME_CACHE", self.root / "data" / "_code_name_cache.json"),
        )
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_missing_preopen_files_render_without_crash(self) -> None:
        snapshot = broadcast.build_snapshot(datetime(2026, 7, 27, 8, 40))
        text = broadcast.render_text(snapshot)
        page = broadcast.render_html(snapshot)
        self.assertEqual(snapshot["strategies"][1]["daily_cap"], 15)
        self.assertIn("/15", text)
        self.assertIn("/15", page)

        self.assertIn("전략 01", text)
        self.assertIn("전략 04", text)
        self.assertIn("전략 05", text)
        self.assertIn("전략 06 급락 저점", text)
        self.assertIn("전략 06 급락 저점", page)
        self.assertIn("개장 전", text)
        self.assertIn("스톡봇 통합 중계", page)

    def test_strategy_06_composite_position_key_uses_real_code(self) -> None:
        now = datetime(2026, 8, 3, 9, 5)
        state = {
            "date": "20260803",
            "heartbeat": "2026-08-03T09:04:59+09:00",
            "order_attempts_total": 1,
            "entered_codes": ["123450"],
            "positions": {
                "123450:1": {
                    "code": "123450",
                    "name": "전략6테스트",
                    "phase": "HOLD",
                    "qty": 1,
                    "entry_price": 18200,
                    "last_price": 18300,
                }
            },
            "recovery_blocked": False,
            "last_error": "",
        }
        (self.root / "data" / "strategy_06_crash_low_chase_state_v1.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
        (self.root / "config" / "strategy_06_live_approved.flag").write_text(
            "APPROVED", encoding="ascii"
        )

        snapshot = broadcast.build_snapshot(now)
        strategy = snapshot["strategies"][5]

        self.assertEqual(strategy["name"], "급락 저점")
        self.assertEqual(strategy["daily_cap"], 20)
        self.assertEqual(strategy["held"][0]["code"], "123450")

    def test_current_strategy_state_and_shared_slot_are_visible(self) -> None:
        now = datetime(2026, 7, 27, 9, 1)
        state = {
            "date": "20260727",
            "heartbeat": "2026-07-27T09:00:59+09:00",
            "order_attempts_total": 1,
            "entered_codes": ["123456"],
            "cycles_by_code": {"123456": 0},
            "positions": {
                "123456": {
                    "code": "123456",
                    "name": "테스트",
                    "phase": "HOLD",
                    "qty": 1,
                    "entry_price": 10000,
                    "last_price": 10100,
                }
            },
            "recovery_blocked": False,
            "last_error": "",
        }
        (self.root / "data" / "strategy_01_rotation_state_v2.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
        (self.root / "data" / "shared_slots.json").write_text(
            json.dumps(
                {"date": "20260727", "slots": {"123456": {"strat": "STRATEGY01"}}}
            ),
            encoding="utf-8",
        )
        (self.root / "config" / "strategy_01_live_approved.flag").write_text(
            "APPROVED", encoding="ascii"
        )

        snapshot = broadcast.build_snapshot(now)
        strategy = snapshot["strategies"][0]

        self.assertEqual(strategy["gate"], "LIVE")
        self.assertEqual(strategy["entered_count"], 1)
        self.assertEqual(len(strategy["held"]), 1)
        self.assertEqual(len(snapshot["slots"]), 1)

    def test_obsolete_live_gate_blocks_are_hidden_and_off_blocks_compacted(self) -> None:
        events = [
            {
                "strategy_number": "02",
                "event": "BUY_BLOCKED",
                "code": "123456",
                "reason": "APPROVAL_OR_OFF_FLAG",
            },
            {
                "strategy_number": "02",
                "event": "BUY_BLOCKED",
                "code": "123456",
                "reason": "APPROVAL_OR_OFF_FLAG",
            },
        ]
        live = broadcast.filter_current_events(
            events, [{"number": "02", "gate": "LIVE"}])
        off = broadcast.filter_current_events(
            events, [{"number": "02", "gate": "OFF"}])

        self.assertEqual(live, [])
        self.assertEqual(len(off), 1)
    def test_main_writes_new_and_legacy_outputs(self) -> None:
        with patch.object(broadcast, "now_local", return_value=datetime(2026, 7, 27, 8, 40)):
            self.assertEqual(broadcast.main(), 0)

        self.assertTrue((self.desktop / "스톡봇_중계.txt").exists())
        self.assertTrue((self.desktop / "스톡봇_중계.html").exists())
        self.assertTrue((self.desktop / "캡틴2_중계.html").exists())
        self.assertTrue((self.desktop / "스톡봇_중계_기록.txt").exists())


if __name__ == "__main__":
    unittest.main()

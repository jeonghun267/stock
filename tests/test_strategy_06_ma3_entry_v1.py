# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_crash_low_chase_v1 import Strategy06Engine


class Strategy06Ma3EntryTests(unittest.TestCase):
    def test_real_entry_waits_and_requests_when_ma3_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Strategy06Engine.__new__(Strategy06Engine)
            engine.state = {"entered_codes": [], "recovery_blocked": False}
            engine.config = SimpleNamespace(
                max_slots=6,
                max_entries_per_code=2,
                max_daily_codes=6,
                min_price_krw=10_000,
                max_price_krw=300_000,
                quantity=1,
                capital_krw=2_000_000,
                bars_path=Path(tmp) / "bars.json",
            )
            engine.broker = SimpleNamespace(real_session=True, buy_allowed=True)
            engine._active_positions = lambda: {}
            engine._active_capital_krw = lambda: 0
            events = []
            engine._event = lambda *args, **kwargs: events.append((args, kwargs))

            now = datetime(2026, 8, 4, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
            with patch(
                "strategy_06_crash_low_chase_v1.ma3_rows", return_value=None,
            ), patch(
                "strategy_06_crash_low_chase_v1.ma3_request_missing_history",
            ) as request:
                result = engine._try_entry(
                    "123450", "TEST", {"price": 20_000}, object(), now,
                )

            self.assertEqual(result, "RETRY")
            self.assertEqual(engine.state["last_error"], "MA3_SEED_NOT_READY:123450")
            request.assert_called_once_with("123450", "S06_CRASH_LOW_CHASE:ENTRY")
            self.assertEqual(events[-1][1]["reason"], "MA3_SEED_NOT_READY")


if __name__ == "__main__":
    unittest.main()

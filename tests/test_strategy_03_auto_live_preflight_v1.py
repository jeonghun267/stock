from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_auto_live_preflight_v1 import (
    PreflightFailure,
    _task_enabled,
    activate_flags,
    prepare_daily_guard,
    task_enabled_from_xml,
    validate_snapshot,
)


class Strategy03PreflightTests(unittest.TestCase):
    def test_snapshot_requires_exact_fresh_topbook(self) -> None:
        now = datetime(2026, 7, 27, 9, 0, 1)
        good = {
            "ts": "2026-07-27T09:00:00",
            "ob_ts": "2026-07-27T09:00:00",
            "cur": 12000,
            "best_ask_px": 12010,
            "best_bid_px": 12000,
            "best_ask_qty": 50,
            "best_bid_qty": 80,
            "buy_money_cum": 100,
            "sell_money_cum": 200,
        }
        result = validate_snapshot(
            now=now,
            valley_codes=["111110"],
            snapshot={"codes": {"111110": good}},
            minimum_valid=1,
        )
        self.assertEqual(result["fresh_exact_topbook_count"], 1)
        broken = dict(good)
        broken.pop("best_bid_qty")
        with self.assertRaises(PreflightFailure):
            validate_snapshot(
                now=now,
                valley_codes=["111110"],
                snapshot={"codes": {"111110": broken}},
                minimum_valid=1,
            )

    def test_activation_is_fail_closed_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            off = root / "off.flag"
            approval = root / "approval.flag"
            off.write_text("OFF\n", encoding="ascii")
            activate_flags(off_path=off, approval_path=approval)
            self.assertFalse(off.exists())
            self.assertTrue(approval.exists())
            with self.assertRaises(PreflightFailure):
                activate_flags(off_path=off, approval_path=approval)

    def test_task_xml_enabled_parser(self) -> None:
        enabled = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            b'<Settings><Enabled>true</Enabled></Settings></Task>'
        )
        disabled = enabled.replace(b"true", b"false")
        self.assertTrue(task_enabled_from_xml(enabled))
        self.assertFalse(task_enabled_from_xml(disabled))
        mislabeled = enabled.replace(b"UTF-8", b"UTF-16")
        self.assertTrue(task_enabled_from_xml(mislabeled))
        self.assertIsNone(task_enabled_from_xml(b"not xml"))

    def test_task_query_does_not_override_explicit_disabled(self) -> None:
        xml = (
            b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            b"<Settings><Enabled>false</Enabled></Settings></Task>"
        )
        result = subprocess.CompletedProcess([], 0, stdout=xml, stderr=b"")
        with patch(
            "strategy_03_auto_live_preflight_v1.subprocess.run",
            return_value=result,
        ) as mocked:
            self.assertFalse(_task_enabled("SAFEPLUS_TEST"))
        mocked.assert_called_once()

    def test_task_query_falls_back_to_powershell(self) -> None:
        schtasks = subprocess.CompletedProcess(
            [], 1, stdout=b"", stderr=b"access denied")
        powershell = subprocess.CompletedProcess(
            [], 0, stdout="true\n", stderr="")
        with patch(
            "strategy_03_auto_live_preflight_v1.subprocess.run",
            side_effect=[schtasks, powershell],
        ):
            self.assertTrue(_task_enabled("SAFEPLUS_TEST"))

    def test_task_query_fails_closed_when_both_queries_fail(self) -> None:
        schtasks = subprocess.CompletedProcess(
            [], 1, stdout=b"", stderr=b"access denied")
        powershell = subprocess.CompletedProcess(
            [], 3, stdout="", stderr="not found")
        with patch(
            "strategy_03_auto_live_preflight_v1.subprocess.run",
            side_effect=[schtasks, powershell],
        ):
            self.assertIsNone(_task_enabled("SAFEPLUS_TEST"))

    def test_stale_auto_approval_is_revoked_before_new_day(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            off = root / "off.flag"
            approval = root / "approval.flag"
            approval.write_text(
                "auto-approved 2026-07-27T09:00:00\n", encoding="ascii")
            result = prepare_daily_guard(
                datetime(2026, 7, 28, 8, 59),
                off_path=off,
                approval_path=approval,
            )
            self.assertEqual(result, "STALE_AUTO_APPROVAL_REVOKED")
            self.assertTrue(off.exists())
            self.assertFalse(approval.exists())

if __name__ == "__main__":
    unittest.main()

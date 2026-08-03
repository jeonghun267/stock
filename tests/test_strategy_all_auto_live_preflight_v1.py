from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_all_auto_live_preflight_v1 import (
    _write_audit_preserving_approved_pass,
    activate_all_flags,
)
from strategy_all_live_gate_launcher_v1 import audit_state


class AllStrategyAutoLiveTests(unittest.TestCase):
    def test_redundant_approval_failure_preserves_today_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            passed = {
                "for_date": "20260727",
                "passed": True,
                "activated": True,
                "activated_strategies": ["S01", "S02", "S03"],
            }
            audit.write_text(json.dumps(passed), encoding="utf-8")
            failed = {
                "for_date": "20260727",
                "passed": False,
                "reason": "PreflightFailure:S03_ALREADY_APPROVED_TODAY",
            }
            self.assertTrue(_write_audit_preserving_approved_pass(
                failed, audit_path=audit))
            self.assertTrue(
                json.loads(audit.read_text(encoding="utf-8"))["passed"])
            attempt = audit.with_name("audit_last_attempt.json")
            self.assertTrue(attempt.exists())
            self.assertTrue(json.loads(
                attempt.read_text(encoding="utf-8")
            )["primary_audit_preserved"])

    def test_all_flags_activate_together(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            strategies = {}
            for strategy in ("S01", "S02", "S03"):
                off = root / f"{strategy}.off"
                approval = root / f"{strategy}.approval"
                off.write_text("OFF\n", encoding="ascii")
                strategies[strategy] = {
                    "off": off,
                    "approval": approval,
                }
            activated = activate_all_flags(
                strategies,
                now=datetime(2026, 7, 27, 8, 59, 50),
            )
            self.assertEqual(activated, ["S01", "S02", "S03"])
            for paths in strategies.values():
                self.assertFalse(paths["off"].exists())
                self.assertTrue(paths["approval"].exists())

    def test_gate_requires_today_pass_and_strategy_membership(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            audit.write_text(json.dumps({
                "for_date": "20260727",
                "passed": True,
                "activated": True,
                "activated_strategies": ["S01", "S02", "S03"],
                "finished_at": "2026-07-27T09:00:01",
            }), encoding="utf-8")
            self.assertEqual(audit_state("S01", "20260727", audit), "PASS")
            self.assertEqual(audit_state("S02", "20260727", audit), "PASS")
            self.assertEqual(audit_state("S03", "20260728", audit), "WAIT")

            payload = json.loads(audit.read_text(encoding="utf-8"))
            payload["activated_strategies"] = ["S01", "S03"]
            audit.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(audit_state("S02", "20260727", audit), "FAIL")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_live_gate_launcher_v1 import _today_audit_state


class Strategy03LiveGateTests(unittest.TestCase):
    def test_only_today_pass_and_activation_can_start_live(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "audit.json"
            path.write_text(json.dumps({
                "for_date": "20260727",
                "passed": True,
                "activated": True,
                "finished_at": "2026-07-27T09:00:01",
            }), encoding="utf-8")
            self.assertEqual(_today_audit_state("20260727", path), "PASS")
            self.assertEqual(_today_audit_state("20260728", path), "WAIT")

            path.write_text(json.dumps({
                "for_date": "20260727",
                "passed": False,
                "activated": False,
                "finished_at": "2026-07-27T09:00:01",
            }), encoding="utf-8")
            self.assertEqual(_today_audit_state("20260727", path), "FAIL")


if __name__ == "__main__":
    unittest.main()

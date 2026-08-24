from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import preflight_context_selftest_v1 as selftest


class PreflightContextSelftestTests(unittest.TestCase):
    def _payload(self, now: datetime) -> dict[str, object]:
        return {
            "profile": "high",
            "for_date": now.strftime("%Y%m%d"),
            "finished_at": now.isoformat(timespec="seconds"),
            "scheduled_context": True,
            "order_capability": 0,
            "passed": True,
            "stages": {
                "stage1_mock": {"passed": True},
                "stage2_real_fallback": {"passed": True},
                "stage3_scheduled_context": {
                    "passed": True,
                    "user": "UserK",
                    "elevated": True,
                },
            },
        }

    def test_stage1_preserves_explicit_disabled(self) -> None:
        result = selftest._stage1_mock_contract()
        self.assertTrue(result["passed"])
        self.assertTrue(result["checks"]["disabled_did_not_fallback"])

    def test_validate_audit_requires_all_three_stages(self) -> None:
        now = datetime(2026, 7, 28, 8, 59)
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            audit.write_text(json.dumps(self._payload(now)), encoding="utf-8")
            with patch.dict(selftest.AUDITS, {"high": audit}):
                result = selftest.validate_audit(
                    profile="high", now=now, max_age_sec=60)
                self.assertTrue(result["passed"])
                payload = self._payload(now)
                payload["stages"]["stage2_real_fallback"]["passed"] = False
                audit.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(selftest.SelftestFailure):
                    selftest.validate_audit(
                        profile="high", now=now, max_age_sec=60)

    def test_validate_audit_rejects_stale_result(self) -> None:
        now = datetime(2026, 7, 28, 8, 59)
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            payload = self._payload(now - timedelta(minutes=10))
            payload["for_date"] = now.strftime("%Y%m%d")
            audit.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(selftest.AUDITS, {"high": audit}):
                with self.assertRaises(selftest.SelftestFailure):
                    selftest.validate_audit(
                        profile="high", now=now, max_age_sec=60)


if __name__ == "__main__":
    unittest.main()

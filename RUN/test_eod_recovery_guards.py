# -*- coding: utf-8 -*-
"""Focused regression tests for EOD collector/guard recovery controls."""
import importlib.util
import json
import logging
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parent


def _load(name, path, mute_rotating_log=False):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if mute_rotating_log:
        with patch("logging.handlers.RotatingFileHandler",
                   lambda *args, **kwargs: logging.NullHandler()):
            spec.loader.exec_module(module)
    else:
        spec.loader.exec_module(module)
    return module


class EodRecoveryGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collector = _load(
            "collector_under_test",
            RUN_DIR / "collect_eod_daily_bars_v2_4_SAFEPLUS_FINAL.py",
            mute_rotating_log=True,
        )
        cls.guard = _load(
            "guard_under_test", RUN_DIR / "eod_freshness_guard.py"
        )

    def test_three_consecutive_tr_timeouts_abort(self):
        self.collector._eod_broker_request = lambda *args, **kwargs: {
            "status": "TIMEOUT", "error": "test", "data": None
        }
        client = self.collector.BrokerKiwoom()
        self.assertTrue(client.get_daily("005930", 0).empty)
        self.assertTrue(client.get_daily("005930", 0).empty)
        with self.assertRaises(self.collector.BrokerIpcUnhealthyError):
            client.get_daily("005930", 0)

    def test_pid_lock_rejects_same_process_and_heals_reused_pid(self):
        collector = self.collector
        old_pid_file = collector.PID_FILE
        old_acquired = collector._pid_acquired
        old_token = collector._pid_token
        try:
            with tempfile.TemporaryDirectory() as tmp:
                collector.PID_FILE = Path(tmp) / "collect_eod.pid"
                collector._pid_acquired = False
                collector._pid_token = ""
                collector.PID_FILE.write_text(
                    json.dumps({"pid": 123, "process_created_100ns": 111,
                                "token": "old"}), encoding="utf-8"
                )
                with patch.object(collector, "_process_created_100ns", return_value=111):
                    self.assertFalse(collector._acquire_pid())
                with patch.object(
                    collector, "_process_created_100ns",
                    side_effect=lambda pid: 222 if pid == 123 else 333,
                ):
                    self.assertTrue(collector._acquire_pid())
                    current = json.loads(collector.PID_FILE.read_text(encoding="utf-8"))
                    self.assertEqual(current["pid"], collector.os.getpid())
                    self.assertEqual(current["process_created_100ns"], 333)
                    collector._release_pid()
                    self.assertFalse(collector.PID_FILE.exists())
        finally:
            collector.PID_FILE = old_pid_file
            collector._pid_acquired = old_acquired
            collector._pid_token = old_token

    def test_legacy_pid_reuse_after_heartbeat_is_stale(self):
        collector = self.collector
        old_hb = collector.HB_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                collector.HB_FILE = Path(tmp) / "collect_eod.heartbeat"
                collector.HB_FILE.write_text(json.dumps({
                    "pid": 123,
                    "ts": "2026-08-21T08:20:43",
                }), encoding="utf-8")
                unix_started = datetime(2026, 8, 21, 18, 50).timestamp()
                filetime = int((unix_started + 11_644_473_600) * 10_000_000)
                self.assertFalse(collector._legacy_pid_is_same_collector(123, filetime))
        finally:
            collector.HB_FILE = old_hb

    def test_guard_timeout_bounds(self):
        self.assertEqual(
            self.guard.collector_timeout_sec(datetime(2026, 8, 14, 7, 30)),
            3900,
        )
        self.assertEqual(
            self.guard.collector_timeout_sec(datetime(2026, 8, 14, 8, 35)),
            0,
        )
        self.assertEqual(
            self.guard.collector_timeout_sec(datetime(2026, 8, 14, 20, 0)),
            4500,
        )

    def test_guard_propagates_collector_timeout(self):
        guard = self.guard
        not_running = type("Result", (), {"stdout": "0", "returncode": 0})()
        with tempfile.TemporaryDirectory() as tmp:
            guard.STATUS = Path(tmp) / "status.json"
            guard.latest_eod_date = lambda: "20260811"
            with patch.object(sys, "argv", ["guard", "--rerun"]), patch.object(
                guard.subprocess,
                "run",
                side_effect=[not_running, subprocess.TimeoutExpired("collector", 10)],
            ):
                with self.assertRaisesRegex(SystemExit, "124"):
                    guard.main()
            status = json.loads(guard.STATUS.read_text(encoding="utf-8"))
            self.assertTrue(status["action"].startswith("rerun_timeout:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import tempfile
import unittest
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

_real_rotating_handler = logging.handlers.RotatingFileHandler
logging.handlers.RotatingFileHandler = lambda *a, **kw: logging.NullHandler()
try:
    import broker_gateway_v1 as bg  # noqa: E402
finally:
    logging.handlers.RotatingFileHandler = _real_rotating_handler


class _Ocx:
    def __init__(self, returns):
        self.returns = list(returns)
        self.calls = []

    def dynamicCall(self, *args):
        self.calls.append(args)
        return self.returns.pop(0) if self.returns else 0


class RealRegRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_file = Path(self.temp.name) / "broker_state.json"
        old_state_file = bg.STATE_FILE
        bg.STATE_FILE = self.state_file
        self.addCleanup(setattr, bg, "STATE_FILE", old_state_file)

    def gateway(self, returns=(0,)):
        gw = bg.BrokerGateway.__new__(bg.BrokerGateway)
        gw.state = bg.BrokerState.CONNECTED
        gw.ocx = _Ocx(returns)
        gw._realreg_state = {}
        gw._realreg_load_ok = True
        gw.responses = []
        gw._write_response = lambda request_id, **kw: gw.responses.append(kw)
        return gw

    def test_setreal_nonzero_return_is_error(self):
        gw = self.gateway((-1,))
        gw._handle_setreal_reg_request("r1", {
            "screen_no": "9001", "code_list": "005930",
            "fid_list": "10;13", "real_type": "0",
        })
        self.assertEqual("ERROR", gw.responses[0]["status"])
        self.assertEqual({}, gw._realreg_state)

    def test_append_merges_and_replay_state_uses_new_registration(self):
        gw = self.gateway()
        gw._realreg_state = {
            "9001": {"code_list": "005930", "fid_list": "10",
                     "real_type": "0", "ts": "old"}}
        gw._handle_setreal_reg_request("r2", {
            "screen_no": "9001", "code_list": "000660;005930",
            "fid_list": "13;10", "real_type": "1",
        })
        self.assertEqual("OK", gw.responses[0]["status"])
        saved = gw._realreg_state["9001"]
        self.assertEqual("005930;000660", saved["code_list"])
        self.assertEqual("10;13", saved["fid_list"])
        self.assertEqual("0", saved["real_type"])

    def test_registration_persist_failure_is_not_reported_ok(self):
        gw = self.gateway()
        gw._save_realreg_state = lambda: False
        gw._handle_setreal_reg_request("r3", {
            "screen_no": "9001", "code_list": "005930",
            "fid_list": "10", "real_type": "0",
        })
        self.assertEqual("ERROR", gw.responses[0]["status"])
        self.assertIn("persistence failed", gw.responses[0]["error"])

    def test_scoped_remove_updates_persisted_codes(self):
        gw = self.gateway()
        gw._realreg_state = {
            "9001": {"code_list": "005930;000660", "fid_list": "10;13",
                     "real_type": "0", "ts": "old"}}
        gw._handle_set_real_remove_request(
            "r4", {"screen_no": "9001", "code": "005930"})
        self.assertEqual("OK", gw.responses[0]["status"])
        self.assertEqual("000660", gw._realreg_state["9001"]["code_list"])
        disk = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual("000660", disk["realreg"]["9001"]["code_list"])

    def test_invalid_saved_schema_fails_closed(self):
        self.state_file.write_text(json.dumps({"realreg": []}), encoding="utf-8")
        gw = self.gateway()
        self.assertFalse(gw._load_realreg_state())
        self.assertFalse(gw._realreg_load_ok)

    def test_replay_retries_then_succeeds(self):
        gw = self.gateway((-1, -1, 0))
        gw._realreg_state = {
            "9001": {"code_list": "005930", "fid_list": "10",
                     "real_type": "0", "ts": "old"}}
        old_sleep = bg.time.sleep
        bg.time.sleep = lambda _seconds: None
        self.addCleanup(setattr, bg.time, "sleep", old_sleep)
        self.assertTrue(gw._replay_realreg())
        self.assertEqual(3, len(gw.ocx.calls))

    def test_replay_exhaustion_returns_false(self):
        gw = self.gateway((-1, -1, -1))
        gw._realreg_state = {
            "9001": {"code_list": "005930", "fid_list": "10",
                     "real_type": "0", "ts": "old"}}
        old_sleep = bg.time.sleep
        bg.time.sleep = lambda _seconds: None
        self.addCleanup(setattr, bg.time, "sleep", old_sleep)
        self.assertFalse(gw._replay_realreg())
        self.assertEqual(3, len(gw.ocx.calls))


if __name__ == "__main__":
    unittest.main()

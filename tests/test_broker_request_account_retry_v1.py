# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


class _NoopRotatingHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()


with patch("logging.handlers.RotatingFileHandler", _NoopRotatingHandler):
    import broker_gateway_v1 as gateway


class _LoginOcx:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def dynamicCall(self, *args):
        self.calls += 1
        return next(self.responses)


class BrokerRequestAccountRetryTests(unittest.TestCase):
    def make_gateway(self, responses):
        broker = object.__new__(gateway.BrokerGateway)
        broker.ocx = _LoginOcx(responses)
        waits = []
        broker._wait_qt_interval = waits.append
        return broker, waits

    def test_blank_account_retries_then_succeeds(self):
        broker, waits = self.make_gateway(["", "", "123-45;"])

        self.assertEqual({"12345"}, broker._get_logged_accounts_with_retry())
        self.assertEqual(3, broker.ocx.calls)
        self.assertEqual([200, 200], waits)

    def test_three_blank_accounts_fail_closed(self):
        broker, waits = self.make_gateway(["", "", ""])

        self.assertEqual(set(), broker._get_logged_accounts_with_retry())
        self.assertEqual(3, broker.ocx.calls)
        self.assertEqual([200, 200], waits)

    def test_same_request_id_is_not_processed_reentrantly(self):
        broker = object.__new__(gateway.BrokerGateway)
        broker._processing_request_ids = {"same-request"}
        writes = []
        broker._write_response = lambda *args, **kwargs: writes.append((args, kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            req_path = Path(temp_dir) / "same-request.json"
            req_path.write_text(json.dumps({
                "request_id": "same-request",
                "type": "PING",
                "ts": datetime.now().isoformat(),
                "ttl_sec": 15,
            }), encoding="utf-8")

            broker.process_request(req_path)

            self.assertTrue(req_path.exists())
            self.assertEqual([], writes)
            self.assertEqual({"same-request"}, broker._processing_request_ids)


if __name__ == "__main__":
    unittest.main()
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

_real_rotating_handler = logging.handlers.RotatingFileHandler
logging.handlers.RotatingFileHandler = lambda *a, **kw: logging.NullHandler()
try:
    from broker_gateway_v1 import BrokerGateway  # noqa: E402
finally:
    logging.handlers.RotatingFileHandler = _real_rotating_handler


class _Loop:
    def __init__(self) -> None:
        self.exits = 0

    def isRunning(self) -> bool:
        return True

    def exit(self) -> None:
        self.exits += 1


class _Ocx:
    def dynamicCall(self, signature, *args):
        if str(signature).startswith("GetRepeatCnt"):
            return 0
        if str(signature).startswith("GetCommData"):
            return " 12345 "
        raise AssertionError(signature)


class TrCallbackIsolationTests(unittest.TestCase):
    def gateway(self):
        gw = BrokerGateway.__new__(BrokerGateway)
        gw.ocx = _Ocx()
        gw.tr_loop = _Loop()
        gw.tr_data_buffer = {}
        gw._active_tr = {
            "rqname": "T000001ABCDEF01",
            "tr_code": "opt10080",
            "screen_no": "0001",
            "output_fields": ["현재가"],
        }
        return gw

    def test_late_response_does_not_exit_current_loop(self):
        gw = self.gateway()
        gw._on_receive_tr_data(
            "0001", "OLD_REQUEST", "opt10080", "record", "0")
        self.assertEqual(0, gw.tr_loop.exits)
        self.assertEqual({}, gw.tr_data_buffer)

    def test_matching_response_uses_its_frozen_fields(self):
        gw = self.gateway()
        gw.tr_output_fields = ["잘못된전역필드"]
        gw._on_receive_tr_data(
            "0001", "T000001ABCDEF01", "opt10080", "record", "0")
        self.assertEqual(1, gw.tr_loop.exits)
        records = gw.tr_data_buffer["T000001ABCDEF01"]["records"]
        self.assertEqual([{"현재가": "12345"}], records)

    def test_wire_rqname_is_unique_and_short(self):
        gw = BrokerGateway.__new__(BrokerGateway)
        gw._tr_wire_seq = 0
        names = {gw._next_tr_rqname("B") for _ in range(20)}
        self.assertEqual(20, len(names))
        self.assertTrue(all(name.startswith("B") and len(name) <= 20
                            for name in names))

    def test_balance_wire_rqname_stays_strategy_specific(self):
        gw = BrokerGateway.__new__(BrokerGateway)
        gw._tr_wire_seq = 0
        self.assertEqual(
            "STRATEGY01_BALANCE",
            gw._wire_tr_rqname("STRATEGY01_BALANCE", stable=True),
        )
        self.assertEqual(
            "STRATEGY01_BALANCE",
            gw._wire_tr_rqname("STRATEGY01_BALANCE", stable=True),
        )

    def test_balance_handler_requests_stable_wire_name(self):
        gw = BrokerGateway.__new__(BrokerGateway)
        calls = []
        gw._handle_tr_request = lambda request_id, req, **kw: calls.append(
            (request_id, req, kw)
        )
        gw._handle_balance_tr_request(
            "balance-1", {"tr_code": "opw00018"},
        )
        self.assertEqual(True, calls[0][2]["stable_wire_rqname"])


class RequestTimeGateTests(unittest.TestCase):
    def run_request(self, body):
        responses = []
        gw = BrokerGateway.__new__(BrokerGateway)
        gw._write_response = lambda request_id, **kw: responses.append(kw)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "req.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            gw.process_request(path)
            self.assertFalse(path.exists())
        return responses

    def test_missing_timestamp_is_rejected(self):
        rows = self.run_request({
            "request_id": "bad-time", "type": "PING", "ttl_sec": 30})
        self.assertIn("INVALID_REQUEST_TIME", rows[0]["error"])

    def test_far_future_timestamp_is_rejected(self):
        rows = self.run_request({
            "request_id": "future-time", "type": "PING", "ttl_sec": 30,
            "ts": (datetime.now() + timedelta(minutes=1)).isoformat(),
        })
        self.assertIn("FUTURE_REQUEST_TIME", rows[0]["error"])

    def test_unbounded_ttl_is_rejected(self):
        rows = self.run_request({
            "request_id": "bad-ttl", "type": "PING", "ttl_sec": 999999,
            "ts": datetime.now().isoformat(),
        })
        self.assertIn("INVALID_TTL", rows[0]["error"])


if __name__ == "__main__":
    unittest.main()

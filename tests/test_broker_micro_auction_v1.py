# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import logging.handlers
import sys
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
    def __init__(self, values):
        self.values = {int(k): str(v) for k, v in values.items()}

    def dynamicCall(self, _signature, _code, fid):
        return self.values.get(int(fid), "")


class BrokerMicroAuctionTests(unittest.TestCase):
    def gateway(self, values):
        gw = bg.BrokerGateway.__new__(bg.BrokerGateway)
        gw.ocx = _Ocx(values)
        gw._micro_last_upd = {}
        gw._micro_snapshot = {}
        gw._micro_verify_logged = 0
        return gw

    def test_quote_event_captures_primary_auction_fids(self):
        gw = self.gateway({23: "+12345", 24: "6789"})

        gw._micro_update("005930", "주식호가잔량")

        rec = gw._micro_snapshot["005930"]
        self.assertEqual(12345.0, rec["auction_expected_px"])
        self.assertEqual(6789.0, rec["auction_expected_qty"])
        self.assertTrue(rec["auction_ts"])

    def test_quote_event_falls_back_to_new_auction_fids(self):
        gw = self.gateway({291: "23456", 292: "7890"})

        gw._micro_update("000660", "주식호가잔량")

        rec = gw._micro_snapshot["000660"]
        self.assertEqual(23456.0, rec["auction_expected_px"])
        self.assertEqual(7890.0, rec["auction_expected_qty"])

    def test_registration_contains_both_documented_fid_pairs(self):
        fids = set(bg.MICRO_FIDS.split(";"))
        self.assertTrue({"23", "24", "291", "292"}.issubset(fids))


if __name__ == "__main__":
    unittest.main()
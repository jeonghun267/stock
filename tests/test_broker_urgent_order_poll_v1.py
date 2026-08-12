# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
import logging
import importlib
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

class _NoopRotatingHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()


with patch("logging.handlers.RotatingFileHandler", _NoopRotatingHandler):
    gateway = importlib.import_module("broker_gateway_v1")


class BrokerUrgentOrderPollTests(unittest.TestCase):
    def test_real_order_preempts_while_general_poll_is_busy(self):
        broker = object.__new__(gateway.BrokerGateway)
        broker.state = gateway.BrokerState.CONNECTED
        broker._poll_in_progress = True
        broker._urgent_order_poll_in_progress = False
        processed = []
        broker.process_request = lambda path: processed.append(path)

        with tempfile.TemporaryDirectory() as temp_dir:
            order_path = Path(temp_dir) / "sell.json"
            order_path.write_text("{}", encoding="utf-8")
            with patch.object(
                gateway, "_pending_real_order_paths", return_value=[order_path]
            ):
                broker.poll_urgent_orders()

        self.assertEqual(processed, [order_path])
        self.assertFalse(broker._urgent_order_poll_in_progress)


if __name__ == "__main__":
    unittest.main()

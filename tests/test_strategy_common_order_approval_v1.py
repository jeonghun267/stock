# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_order_v1 import StrategyBroker


class StrategyBrokerApprovalTests(unittest.TestCase):
    def _broker(self, root: Path, *, force_exit_only: bool = False) -> StrategyBroker:
        return StrategyBroker(
            live_requested=True,
            approval_path=root / "approval.flag",
            off_flag_path=root / "off.flag",
            manual_buy_block_path=root / "manual.flag",
            logger=logging.getLogger("strategy-common-order-approval-test"),
            force_exit_only=force_exit_only,
        )

    @staticmethod
    def _write(path: Path, when: datetime) -> None:
        path.write_text(
            f"APPROVED_BY_OWNER {when:%Y%m%d %H:%M:%S}\n", encoding="ascii")

    def test_only_today_non_future_approval_enables_live_buy(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            broker = self._broker(root)
            now = datetime.now()
            invalid = (
                "APPROVED\n",
                f"APPROVED_BY_OWNER {(now - timedelta(days=1)):%Y%m%d %H:%M:%S}\n",
                f"APPROVED_BY_OWNER {(now + timedelta(minutes=5)):%Y%m%d %H:%M:%S}\n",
            )
            for text in invalid:
                broker.approval_path.write_text(text, encoding="ascii")
                self.assertFalse(broker.real_session)
                self.assertFalse(broker.buy_allowed)

            self._write(broker.approval_path, now - timedelta(seconds=1))
            self.assertTrue(broker.real_session)
            self.assertTrue(broker.buy_allowed)

            broker.approval_path.write_text(
                f"auto-approved {(now - timedelta(seconds=1)).isoformat(timespec='seconds')}\n",
                encoding="ascii",
            )
            self.assertTrue(broker.buy_allowed)

            broker.approval_path.write_text(
                f"APPROVED_BY_OWNER {now:%Y%m%d} S06_LIVE\n",
                encoding="ascii",
            )
            self.assertTrue(broker.buy_allowed)

    def test_force_exit_only_never_enables_buy(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            broker = self._broker(root, force_exit_only=True)
            self._write(broker.approval_path, datetime.now() - timedelta(seconds=1))
            self.assertTrue(broker.real_session)
            self.assertFalse(broker.buy_allowed)

    def test_open_orders_retries_transient_tr_failure(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = 0
                self.timeouts = []

            def balance_tr(self, **kwargs):
                self.calls += 1
                self.timeouts.append(kwargs.get("timeout_sec"))
                if self.calls == 1:
                    return {"status": "ERROR", "error": "TR response timeout"}
                return {"status": "OK", "data": {"records": []}}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            broker = self._broker(root)
            self._write(broker.approval_path, datetime.now() - timedelta(seconds=1))
            client = Client()
            broker.client = client
            broker.account = "12345678"

            with patch.object(broker, "connect", return_value=True), patch(
                "strategy_common_order_v1._time.sleep", return_value=None
            ):
                result = broker.prebuy_open_orders("347850", buy=True)

            self.assertEqual(result, {})
            self.assertEqual(client.calls, 2)
            self.assertEqual(client.timeouts, [2.0, 2.0])

    def test_prebuy_holdings_uses_two_second_two_attempt_limit(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = 0
                self.timeouts = []

            def balance_tr(self, **kwargs):
                self.calls += 1
                self.timeouts.append(kwargs.get("timeout_sec"))
                if self.calls == 1:
                    return {"status": "ERROR", "error": "TR response timeout"}
                return {"status": "OK", "data": {"records": []}}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            broker = self._broker(root)
            self._write(broker.approval_path, datetime.now() - timedelta(seconds=1))
            client = Client()
            broker.client = client
            broker.account = "12345678"

            with patch.object(broker, "connect", return_value=True), patch(
                "strategy_common_order_v1._time.sleep", return_value=None
            ):
                result = broker.prebuy_holdings()

            self.assertEqual(result, {})
            self.assertEqual(client.calls, 2)
            self.assertEqual(client.timeouts, [2.0, 2.0])


if __name__ == "__main__":
    unittest.main()

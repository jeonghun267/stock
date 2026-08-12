# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_order_v1 import StrategyBroker  # noqa: E402


class StrategyCommonOrderLiveGuardTests(unittest.TestCase):
    def broker(self, root: Path, number: int, **overrides):
        values = {
            "live_requested": True,
            "approval_path": root / "approval.flag",
            "off_flag_path": root / "off.flag",
            "manual_buy_block_path": root / "manual.flag",
            "logger": logging.getLogger(f"live-guard-S{number:02d}"),
            "order_prefix": f"STRATEGY{number:02d}",
        }
        values.update(overrides)
        return StrategyBroker(**values)

    @staticmethod
    def approve(root: Path, when: datetime) -> None:
        (root / "approval.flag").write_text(
            f"APPROVED_BY_OWNER {when:%Y%m%d %H:%M:%S}\n", encoding="ascii"
        )

    def test_s01_through_s06_share_live_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.approve(root, datetime.now())
            for number in range(1, 7):
                with self.subTest(strategy=number):
                    broker = self.broker(root, number)
                    self.assertTrue(broker.real_session)
                    self.assertTrue(broker.buy_allowed)
                    self.assertEqual("LIVE", broker.mode)
                    self.assertEqual(f"S{number:02d}", broker.live_guard.strategy_id)

    def test_off_and_manual_block_buy_but_keep_sell_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.approve(root, datetime.now())
            for filename in ("off.flag", "manual.flag"):
                path = root / filename
                path.write_text("BLOCK\n", encoding="ascii")
                broker = self.broker(root, 1)
                self.assertTrue(broker.real_session)
                self.assertFalse(broker.buy_allowed)
                self.assertEqual("LIVE_EXIT_ONLY", broker.mode)
                path.unlink()

    def test_stale_future_and_malformed_approval_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            now = datetime.now()
            invalid = (
                f"APPROVED_BY_OWNER {(now - timedelta(days=1)):%Y%m%d %H:%M:%S}\n",
                f"APPROVED_BY_OWNER {(now + timedelta(minutes=5)):%Y%m%d %H:%M:%S}\n",
                "APPROVED\n",
            )
            for text in invalid:
                with self.subTest(text=text.strip()):
                    (root / "approval.flag").write_text(text, encoding="ascii")
                    broker = self.broker(root, 1)
                    self.assertFalse(broker.real_session)
                    self.assertFalse(broker.buy_allowed)
                    self.assertEqual("SHADOW", broker.mode)

    def test_force_exit_only_never_enables_buy(self):
        with tempfile.TemporaryDirectory() as folder:
            broker = self.broker(Path(folder), 6, force_exit_only=True)
            self.assertTrue(broker.real_session)
            self.assertFalse(broker.buy_allowed)
            self.assertEqual("LIVE_EXIT_ONLY", broker.mode)


if __name__ == "__main__":
    unittest.main()

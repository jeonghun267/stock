# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from approval_settings_guard import KST  # noqa: E402
from strategy_broker_live_guard import StrategyBrokerLiveGuard  # noqa: E402


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=KST)


class StrategyBrokerLiveGuardTests(unittest.TestCase):
    def evaluate(self, root: Path, prefix: str, **overrides):
        values = {
            "approval_path": root / "approval.flag",
            "off_flag_path": root / "off.flag",
            "manual_buy_block_path": root / "manual.flag",
            "live_requested": True,
            "force_exit_only": False,
            "now": NOW,
        }
        values.update(overrides)
        return StrategyBrokerLiveGuard(order_prefix=prefix).evaluate(**values)

    def test_s01_through_s06_allow_live_with_today_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "approval.flag").write_text(
                "APPROVED_BY_OWNER 20260804 09:00:00\n", encoding="ascii"
            )
            for number in range(1, 7):
                with self.subTest(strategy=number):
                    decision = self.evaluate(root, f"STRATEGY{number:02d}")
                    self.assertEqual(f"S{number:02d}", decision.strategy_id)
                    self.assertTrue(decision.approval_valid)
                    self.assertTrue(decision.real_session)
                    self.assertTrue(decision.buy_allowed)

    def test_off_and_manual_block_disable_buy_but_keep_exit_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "approval.flag").write_text(
                "APPROVED_BY_OWNER 20260804 09:00:00\n", encoding="ascii"
            )
            for filename in ("off.flag", "manual.flag"):
                path = root / filename
                path.write_text("BLOCK\n", encoding="ascii")
                decision = self.evaluate(root, "STRATEGY01")
                self.assertTrue(decision.real_session)
                self.assertFalse(decision.buy_allowed)
                path.unlink()

    def test_stale_future_and_malformed_approvals_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            invalid = (
                "APPROVED_BY_OWNER 20260803 09:00:00\n",
                "APPROVED_BY_OWNER 20260804 10:05:00\n",
                "APPROVED\n",
            )
            for text in invalid:
                with self.subTest(text=text.strip()):
                    (root / "approval.flag").write_text(text, encoding="ascii")
                    decision = self.evaluate(root, "STRATEGY01")
                    self.assertFalse(decision.real_session)
                    self.assertFalse(decision.buy_allowed)

    def test_exit_only_allows_recovery_sell_without_buy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            decision = self.evaluate(
                root, "STRATEGY06", force_exit_only=True
            )
            self.assertFalse(decision.approval_valid)
            self.assertTrue(decision.real_session)
            self.assertFalse(decision.buy_allowed)

    def test_unknown_strategy_prefix_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            decision = self.evaluate(Path(folder), "UNKNOWN")
            self.assertEqual("", decision.strategy_id)
            self.assertFalse(decision.real_session)
            self.assertFalse(decision.buy_allowed)


if __name__ == "__main__":
    unittest.main()

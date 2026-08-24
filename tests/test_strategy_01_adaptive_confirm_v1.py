# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from datetime import datetime

from strategy_01_open_surge_signal_v2 import adaptive_confirm_ticks


def closed(at: str, net: float, *, real: bool = True) -> dict:
    return {
        "phase": "CLOSED",
        "real": real,
        "exit_at": at,
        "estimated_net_return_pct_before_slippage": net,
    }


class AdaptiveConfirmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 19, 9, 10, 0)

    def test_two_consecutive_opening_losses_require_three(self) -> None:
        state = {"history": [
            closed("2026-08-19T09:01:00", -1.0),
            closed("2026-08-19T09:02:00", -0.5),
        ]}
        self.assertEqual(3, adaptive_confirm_ticks(state, self.now))

    def test_two_loss_trigger_stays_latched_for_opening_window(self) -> None:
        state = {"history": [
            closed("2026-08-19T09:01:00", -1.0),
            closed("2026-08-19T09:02:00", -0.5),
            closed("2026-08-19T09:03:00", 0.2),
        ]}
        self.assertEqual(3, adaptive_confirm_ticks(state, self.now))

    def test_other_day_or_shadow_exit_does_not_count(self) -> None:
        state = {"history": [
            closed("2026-08-18T09:01:00", -1.0),
            closed("2026-08-19T09:02:00", -0.5, real=False),
        ]}
        self.assertEqual(2, adaptive_confirm_ticks(state, self.now))


if __name__ == "__main__":
    unittest.main()

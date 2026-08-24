# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from strategy_02_low_buy_signal_v1 import _direct_rebound_age_route


class Strategy02DirectReboundAgeWindowTests(unittest.TestCase):
    def test_boundaries_and_today_closed_trades(self) -> None:
        self.assertEqual(_direct_rebound_age_route(59.9), "WAIT")
        self.assertEqual(_direct_rebound_age_route(60.0), "DIRECT")
        self.assertEqual(_direct_rebound_age_route(240.0), "DIRECT")
        self.assertEqual(_direct_rebound_age_route(240.1), "RETEST")

        today_winners = (155.9, 224.8, 139.2)
        today_losses = (37.0, 273.8, 32.0)
        self.assertEqual(
            [_direct_rebound_age_route(v) for v in today_winners],
            ["DIRECT", "DIRECT", "DIRECT"],
        )
        self.assertEqual(
            [_direct_rebound_age_route(v) for v in today_losses],
            ["WAIT", "RETEST", "WAIT"],
        )


if __name__ == "__main__":
    unittest.main()

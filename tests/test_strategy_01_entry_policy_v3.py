import sys
import unittest
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_entry_policy_v3 import EntryCandidate, Lane, evaluate_candidate, select_batch
from strategy_01_entry_runtime_v3 import EntryRuntimeV3


class Strategy01EntryPolicyV3Test(unittest.TestCase):
    def base(self, code="000001", at="2026-08-20T09:00:10"):
        return EntryCandidate(
            ts=datetime.fromisoformat(at), code=code, price=101.0,
            open_price=100.0, low_price=99.2, opening_high_3m=100.8,
            vwap=100.2, high_range_ready=True, money_flow_fresh=True,
            money_speed_5s=2_000_000, auction_ready=True, auction_price_rising=True,
            auction_buy_ratio=0.75, auction_volume_percentile=90,
            relative_volume=2.5, buy_ratio=0.8, buy_rate=200,
            sell_rate=80, buy_accelerating=True, sell_decelerating=True,
            che_rising=True, first_5s_high_break=True, low_stable_sec=6,
            higher_low_pct=0.3, ma5=100.5, ma5_prev=100.2, ma10=100.0,
            spread_bps=20, microprice_edge_bps=5, trend_tier="A")

    def test_rocket_does_not_require_below_open_pullback(self):
        row = replace(self.base(), low_price=100.0)
        self.assertEqual(evaluate_candidate(row).lane, Lane.ROCKET)

    def test_rocket_requires_high_range_top40(self):
        self.assertIsNone(evaluate_candidate(
            replace(self.base(), high_range_ready=False)).lane)

    def test_rocket_requires_fresh_money_flow_board(self):
        self.assertIsNone(evaluate_candidate(
            replace(self.base(), money_flow_fresh=False)).lane)

    def test_rocket_requires_existing_s01_money_speed_floor(self):
        self.assertIsNone(evaluate_candidate(
            replace(self.base(), money_speed_5s=1_666_666)).lane)

    def test_pullback_requires_half_to_one_point_two_rebound(self):
        row = self.base(at="2026-08-20T09:01:00")
        row = replace(
            row, price=100.0, low_price=99.2, first_5s_high_break=False,
            ma5=99.7, ma5_prev=99.5, ma10=99.0,
        )
        self.assertEqual(evaluate_candidate(row).lane, Lane.PULLBACK)

    def test_batch_uses_score_and_lane_limits_not_arrival_order(self):
        rows = [self.base(f"{index:06d}") for index in range(1, 4)]
        selected = select_batch(rows)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].code, "000003")

    def test_runtime_missing_exact_inputs_is_unverified_and_order_zero(self):
        runtime = EntryRuntimeV3({})
        point = SimpleNamespace(
            ts=datetime.fromisoformat("2026-08-20T09:03:10"), code="082920",
            price=35500.0, open_hint=34800.0, buy_money_cum=1_000_000.0,
            sell_money_cum=500_000.0, che_str=120.0, cum_vol=1000.0,
            auction_expected_px=0.0, auction_expected_qty=0.0,
            bid_tot=0.0, ask_tot=0.0, spread_bps=20.0,
            microprice_edge_bps=1.0,
        )
        selected, audit = runtime.process_batch([point], {}, {})
        self.assertEqual(selected, [])
        self.assertEqual(audit[0]["action"], "UNVERIFIED")
        self.assertIn("RELATIVE_VOLUME_BASELINE", audit[0]["missing_fields"])
        json.dumps(audit)


if __name__ == "__main__":
    unittest.main()

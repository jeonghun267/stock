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

from strategy_01_entry_policy_v3 import (
    EntryCandidate,
    Lane,
    evaluate_candidate,
    evaluate_continuation_rocket_shadow,
    select_batch,
)
from strategy_01_entry_runtime_v3 import EntryRuntimeV3


class Strategy01EntryPolicyV3Test(unittest.TestCase):
    def base(self, code="000001", at="2026-08-20T09:00:10"):
        return EntryCandidate(
            ts=datetime.fromisoformat(at), code=code, price=101.0,
            open_price=100.0, low_price=99.2, opening_high_3m=100.8,
            vwap=100.2, high_range_ready=True,
            high_range_money_speed_ratio=2.5, money_flow_fresh=True,
            money_speed_5s=2_000_000, auction_ready=True, auction_price_rising=True,
            auction_buy_ratio=0.75, auction_volume_percentile=90,
            auction_sample_count=20,
            relative_volume=2.5, buy_ratio=0.8, buy_rate=200,
            sell_rate=80, buy_accelerating=True, sell_decelerating=True,
            che_rising=True, first_5s_high_break=True, low_stable_sec=6,
            higher_low_pct=0.3, ma5=100.5, ma5_prev=100.2, ma10=100.0,
            order_book_fresh=True, book_bid_share=0.60,
            spread_bps=20, microprice_edge_bps=5, trend_tier="A",
            price_rising_6s_two_ticks=True, rise_6s_pct=0.7,
            up_ticks_6s=2, session_high_break=True)

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

    def test_rocket_requires_ten_auction_comparison_samples(self):
        self.assertIsNone(evaluate_candidate(
            replace(self.base(), auction_sample_count=9)).lane)

    def test_rocket_accepts_zero_to_one_point_five_above_open(self):
        self.assertEqual(
            evaluate_candidate(replace(self.base(), price=101.5)).lane,
            Lane.ROCKET,
        )
        self.assertIsNone(
            evaluate_candidate(replace(self.base(), price=99.9)).lane,
        )

    def test_pullback_requires_half_to_one_point_five_rebound(self):
        row = self.base(at="2026-08-20T09:01:00")
        row = replace(
            row, price=100.0, low_price=99.2, first_5s_high_break=False,
            ma5=99.7, ma5_prev=99.5, ma10=99.0,
        )
        self.assertEqual(evaluate_candidate(row).lane, Lane.PULLBACK)

    def test_pullback_requires_strong_recent_money_inflow(self):
        row = replace(
            self.base(at="2026-08-20T09:01:00"),
            price=100.0, low_price=99.2, first_5s_high_break=False,
        )
        self.assertIsNone(evaluate_candidate(
            replace(row, money_speed_5s=999_999)).lane)
        self.assertIsNone(evaluate_candidate(
            replace(row, high_range_money_speed_ratio=1.99)).lane)
        self.assertEqual(evaluate_candidate(row).lane, Lane.PULLBACK)

    def test_pullback_does_not_use_ma_before_buy(self):
        row = replace(
            self.base(at="2026-08-20T09:01:00"),
            price=100.0, low_price=99.2, first_5s_high_break=False,
            ma5=0.0, ma5_prev=0.0, ma10=0.0,
        )
        self.assertEqual(evaluate_candidate(row).lane, Lane.PULLBACK)

    def test_pullback_requires_fresh_recovered_order_book(self):
        row = replace(
            self.base(at="2026-08-20T09:01:00"),
            price=100.0, low_price=99.2, first_5s_high_break=False,
        )
        self.assertIsNone(evaluate_candidate(
            replace(row, order_book_fresh=False)).lane)
        self.assertIsNone(evaluate_candidate(
            replace(row, book_bid_share=0.54)).lane)
        self.assertIsNone(evaluate_candidate(
            replace(row, spread_bps=35.1)).lane)
        self.assertEqual(
            evaluate_candidate(replace(row, price=100.6)).lane,
            Lane.PULLBACK,
        )

    def test_all_lanes_require_high_range_top40(self):
        row = replace(
            self.base(at="2026-08-20T09:03:10"),
            high_range_ready=False,
        )
        self.assertEqual(evaluate_candidate(row).reason, "HIGH_RANGE_TOP40_REQUIRED")

    def test_all_lanes_require_fresh_money_flow(self):
        row = replace(
            self.base(at="2026-08-20T09:03:10"),
            money_flow_fresh=False,
        )
        self.assertEqual(evaluate_candidate(row).reason, "MONEY_FLOW_NOT_FRESH")

    def test_continuation_rocket_is_shadow_only_between_one_point_five_and_three(self):
        row = replace(
            self.base(at="2026-08-20T09:01:06"),
            price=102.0,
            low_price=100.0,
        )
        decision = evaluate_continuation_rocket_shadow(row)
        self.assertEqual(decision.lane, Lane.ROCKET)
        self.assertEqual(decision.action, "SHADOW_READY")
        self.assertEqual(select_batch([row]), [])
        self.assertEqual(
            evaluate_continuation_rocket_shadow(replace(row, price=101.49)).reason,
            "CONTINUATION_EXTENSION_OUTSIDE_1P5_3P0",
        )
        self.assertEqual(
            evaluate_continuation_rocket_shadow(replace(row, price=103.01)).reason,
            "CONTINUATION_EXTENSION_OUTSIDE_1P5_3P0",
        )

    def test_continuation_rocket_requires_two_rises_breakout_flow_and_liquidity(self):
        row = replace(
            self.base(at="2026-08-20T09:01:06"),
            price=102.0,
            low_price=100.0,
        )
        self.assertEqual(
            evaluate_continuation_rocket_shadow(
                replace(row, price_rising_6s_two_ticks=False)
            ).reason,
            "CONTINUATION_6S_TWO_UPTICKS_MISSING",
        )
        self.assertEqual(
            evaluate_continuation_rocket_shadow(
                replace(row, session_high_break=False)
            ).reason,
            "CONTINUATION_SESSION_HIGH_NOT_BROKEN",
        )
        self.assertEqual(
            evaluate_continuation_rocket_shadow(
                replace(row, money_speed_5s=1_666_666)
            ).reason,
            "CONTINUATION_ORDER_FLOW_WEAK",
        )
        self.assertEqual(
            evaluate_continuation_rocket_shadow(
                replace(row, spread_bps=35.1)
            ).reason,
            "CONTINUATION_LIQUIDITY_WEAK",
        )

    def test_runtime_builds_two_up_ticks_inside_six_seconds(self):
        runtime = EntryRuntimeV3({})
        samples = runtime.states["000001"].samples
        for second, price in ((0, 100.0), (2, 100.3), (4, 100.3), (6, 100.7)):
            samples.append((
                datetime.fromisoformat(f"2026-08-20T09:01:{second:02d}"),
                price, 0.0, 0.0, 100.0, 0.0,
            ))
        rising, rise_6s, up_ticks, high_break = runtime._six_second_price_momentum(samples)
        self.assertTrue(rising)
        self.assertGreater(rise_6s, 0.0)
        self.assertEqual(up_ticks, 2)
        self.assertTrue(high_break)

    def test_continuation_rocket_live_is_limited_to_approved_date(self):
        approved = replace(
            self.base(at="2026-09-03T09:01:06"),
            price=102.0,
            low_price=100.0,
        )
        decision = evaluate_candidate(approved)
        self.assertEqual(decision.lane, Lane.ROCKET)
        self.assertEqual(decision.action, "READY")
        self.assertEqual(decision.reason, "CONTINUATION_ROCKET_CONFIRMED")
        self.assertEqual(select_batch([approved])[0].lane, Lane.ROCKET)
        expired = replace(approved, ts=datetime.fromisoformat("2026-09-04T09:01:06"))
        self.assertEqual(select_batch([expired]), [])

    def test_continuation_replay_date_exercises_same_ready_path(self):
        replay = replace(
            self.base(at="2026-09-02T09:01:06"),
            price=102.0,
            low_price=100.0,
        )
        self.assertEqual(
            evaluate_candidate(replay).reason,
            "CONTINUATION_ROCKET_CONFIRMED",
        )
        runtime = EntryRuntimeV3({})
        self.assertTrue(runtime._selection_allowed(
            evaluate_candidate(replay), allow_select=False,
        ))

        pullback = replace(
            self.base(at="2026-09-02T09:01:06"),
            price=100.0,
            low_price=99.2,
            first_5s_high_break=False,
        )
        self.assertEqual(evaluate_candidate(pullback).lane, Lane.PULLBACK)
        self.assertFalse(runtime._selection_allowed(
            evaluate_candidate(pullback), allow_select=False,
        ))

    def test_batch_uses_score_and_lane_limits_not_arrival_order(self):
        # ★[2026-08-27 친구님 지시 "ROCKET 3슬롯"] 배치당 로켓 상한 1 → 3.
        #   동점이면 코드 역순 정렬이 유지돼야 한다(도착 순서 금지 계약 그대로).
        rows = [self.base(f"{index:06d}") for index in range(1, 5)]
        selected = select_batch(rows)
        self.assertEqual(len(selected), 3)
        self.assertEqual([row.code for row in selected],
                         ["000004", "000003", "000002"])

    def test_ready_lane_is_not_blocked_by_common_score_floor(self):
        row = replace(
            self.base(at="2026-08-20T09:01:00"),
            price=100.0, low_price=99.2, first_5s_high_break=False,
            auction_volume_percentile=0.0, relative_volume=0.0,
            trend_tier="C", spread_bps=20.0, microprice_edge_bps=-1.0,
        )
        self.assertEqual(select_batch([row])[0].lane, Lane.PULLBACK)

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

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "RUN"))

from strategy_flow_priority_shadow_v1 import (
    build_overlay,
    ensure_open_position_watch,
    open_broker_positions,
    reconcile_broker_fills,
    record_observations,
    summarize_fake_rebound,
)


class StrategyFlowPriorityShadowTest(unittest.TestCase):
    def test_only_shadow_rank_changes(self):
        flow = {"ts": "2026-09-01 10:00:00", "rows": [
            {"code": "000001", "name": "지속", "common_flow_state": "유입지속"},
            {"code": "000002", "name": "전환", "common_flow_state": "유입전환"},
        ]}
        payloads = {
            "S01": {"candidates": [{"code": "000002", "action": "WAIT"}, {"code": "000001", "action": "BUY"}]},
            "S02": {"candidates": [{"code": "000001"}, {"code": "000002"}]},
        }
        result = build_overlay(flow, payloads, datetime(2026, 9, 1, 10, 0))
        self.assertFalse(result["order_capable"])
        self.assertEqual(result["orders_sent"], 0)
        self.assertFalse(result["existing_strategy_decisions_changed"])
        self.assertEqual(result["strategies"]["S01"]["candidates"][0]["code"], "000001")
        self.assertEqual(result["strategies"]["S02"]["candidates"][0]["code"], "000002")
        original = {row["code"]: row["original_action"] for row in result["strategies"]["S01"]["candidates"]}
        self.assertEqual(original, {"000001": "BUY", "000002": "WAIT"})

    def test_absolute_weakness_warns_without_high_range_membership(self):
        flow = {"rows": [{
            "code": "000001", "common_flow_state": "유입없음",
            "common_flow_accel_mkrw_per_min": -5, "common_vwap_gap_pct": -1.0,
        }]}
        result = build_overlay(flow, {"S02": {"candidates": [{"code": "000001"}]}})
        row = result["strategies"]["S02"]["candidates"][0]
        self.assertEqual(row["high_range_direction"], "진입함정")
        self.assertTrue(row["absolute_weakness_fallback"])
        self.assertTrue(row["fake_rebound_warning"])

    def test_open_broker_position_is_forced_into_watch(self):
        fills = [{"code": "000001", "order_no": "B1", "otype": "+매수", "fill_qty": 1}]
        positions = open_broker_positions(fills, {"B1": "S02"})
        overlay = build_overlay({}, {})
        ensure_open_position_watch(overlay, {}, {}, positions)
        row = overlay["strategies"]["S02"]["candidates"][0]
        self.assertTrue(row["forced_position_watch"])
        self.assertEqual(row["original_action"], "BROKER_POSITION_WATCH")

    def test_late_weakness_is_cooling_not_fake_rebound(self):
        flow = {"rows": [{
            "code": "000001", "common_flow_state": "유입없음",
            "common_flow_accel_mkrw_per_min": -5, "common_vwap_gap_pct": -1,
        }]}
        overlay = build_overlay(flow, {})
        ensure_open_position_watch(
            overlay, flow, {},
            [{"strategy": "S06", "code": "000001", "quantity": 1,
              "entry_price": 1000, "entry_timestamp": "2026-09-01 09:00:00"}],
            {"codes": {"000001": {"cur": 990}}}, {},
            datetime(2026, 9, 1, 10, 0),
        )
        row = overlay["strategies"]["S06"]["candidates"][0]
        self.assertEqual(row["position_stage"], "유입둔화")
        self.assertFalse(row["fake_rebound_warning"])

    def test_early_below_entry_weakness_must_persist_before_failure(self):
        flow = {"rows": [{
            "code": "000001", "common_flow_state": "유입없음",
            "common_flow_accel_mkrw_per_min": -5, "common_vwap_gap_pct": -1,
        }]}
        overlay = build_overlay(flow, {})
        previous = {"observations": {"S02:000001": [{
            "observed_at": "2026-09-01 09:00:00", "raw_position_failure": True,
        }]}}
        ensure_open_position_watch(
            overlay, flow, {},
            [{"strategy": "S02", "code": "000001", "quantity": 1,
              "entry_price": 1000, "entry_timestamp": "2026-09-01 09:00:00"}],
            {"codes": {"000001": {"cur": 990}}}, previous,
            datetime(2026, 9, 1, 9, 0, 45),
        )
        row = overlay["strategies"]["S02"]["candidates"][0]
        self.assertEqual(row["position_stage"], "보유실패")
        self.assertTrue(row["fake_rebound_warning"])

    def test_broker_fill_result_uses_only_pre_fill_recorded_context(self):
        flow = {"rows": [{"code": "000001", "common_flow_state": "유입지속"}]}
        overlay = build_overlay(flow, {"S01": {"candidates": [{"code": "000001", "action": "BUY"}]}})
        state = record_observations(overlay, {}, datetime(2026, 9, 1, 9, 0, 0))
        fills = [
            {"ts": "2026-09-01 09:00:10", "code": "000001", "order_no": "B1", "otype": "+매수", "fill_qty": 1, "fill_px": 1000},
            {"ts": "2026-09-01 09:05:00", "code": "000001", "order_no": "S1", "otype": "-매도", "fill_qty": 1, "fill_px": 1010},
        ]
        result = reconcile_broker_fills(fills, {"B1": "S01", "S1": "S01"}, state, "fills.csv")
        trade = result["completed_roundtrips"][0]
        self.assertEqual(trade["provenance"], "[BROKER_FILL]")
        self.assertEqual(trade["entry_flow_context_status"], "RECORDED")
        self.assertEqual(trade["entry_flow_context"]["flow_state"], "유입지속")
        self.assertFalse(result["order_capable"])

    def test_fake_warning_is_split_before_and_after_entry(self):
        state = {"observations": {"S01:000001": [
            {"observed_at": "2026-09-01 09:00:00", "fake_rebound_warning": False},
            {"observed_at": "2026-09-01 09:01:00", "fake_rebound_warning": True,
             "fake_rebound_reasons": ["VWAP재이탈", "유입가속급감"]},
        ]}}
        fills = [
            {"ts": "2026-09-01 09:00:10", "code": "000001", "order_no": "B1", "otype": "+매수", "fill_qty": 1, "fill_px": 1000},
            {"ts": "2026-09-01 09:02:00", "code": "000001", "order_no": "S1", "otype": "-매도", "fill_qty": 1, "fill_px": 990},
        ]
        result = reconcile_broker_fills(fills, {"B1": "S01", "S1": "S01"}, state, "fills.csv")
        trade = result["completed_roundtrips"][0]
        self.assertEqual(trade["pre_entry_fake_rebound_status"], "CLEAR")
        self.assertEqual(trade["post_entry_fake_rebound_status"], "WARNING")
        evaluation = summarize_fake_rebound(result)
        self.assertEqual(evaluation["pre_entry_filter_test"]["CLEAR"]["losses"], 1)
        self.assertEqual(evaluation["post_entry_exit_warning_test"]["WARNING"]["losses"], 1)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "RUN"))
from high_range_direction_shadow_v1 import build_direction_board


class HighRangeDirectionShadowTest(unittest.TestCase):
    def test_classifies_without_filtering_or_order_capability(self):
        top = {"candidates": [
            {"rank": 1, "code": "000001", "name": "전환", "prev_close": 1000},
            {"rank": 2, "code": "000002", "name": "위험", "prev_close": 1000},
        ]}
        live = {"codes": {
            "000001": {"current": 1010, "low_time": "09:00", "rebound_from_low_pct": 1.0, "che_str": 110},
            "000002": {"current": 980, "low_time": "10:00", "rebound_from_low_pct": 0.1, "che_str": 60},
        }}
        flow = {"rows": [
            {"code": "000001", "common_flow_state": "유입전환", "common_vwap_gap_pct": 0.2},
            {"code": "000002", "common_flow_state": "유입없음", "common_vwap_gap_pct": -0.5},
        ]}
        result = build_direction_board(top, live, flow, {}, 0.0, datetime(2026, 9, 1, 10, 0))
        self.assertEqual([row["code"] for row in result["rows"]], ["000001", "000002"])
        self.assertEqual(result["rows"][0]["direction"], "상승전환")
        self.assertEqual(result["rows"][1]["direction"], "하락위험")
        self.assertFalse(result["order_capable"])
        self.assertEqual(result["orders_sent"], 0)

    def test_fake_rebound_requires_compound_deterioration(self):
        top = {"candidates": [{"rank": 1, "code": "000001", "prev_close": 1000}]}
        previous = {"rows": [{
            "code": "000001", "flow_accel_mkrw_per_min": 10,
            "vwap_gap_pct": 0.2, "che_str": 100, "peak_rebound_pct": 1.2,
        }]}
        live = {"codes": {"000001": {
            "current": 997, "low_time": "09:59", "rebound_from_low_pct": 0.3,
            "che_str": 70, "buy_ratio_pct": 40,
        }}}
        flow = {"rows": [{
            "code": "000001", "common_flow_state": "유입없음",
            "common_vwap_gap_pct": -0.2, "common_flow_accel_mkrw_per_min": -1,
        }]}
        result = build_direction_board(
            top, live, flow, {}, 0.0, datetime(2026, 9, 1, 10, 0), previous
        )
        row = result["rows"][0]
        self.assertEqual(row["direction"], "진입함정")
        self.assertTrue(row["fake_rebound_warning"])
        self.assertGreaterEqual(row["fake_rebound_score"], 2)


if __name__ == "__main__":
    unittest.main()

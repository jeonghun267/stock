from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_ALGORITHM,
    EARLY_LOW_LANE,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)
from 골짜기_급반등 import EarlyLowDetector, MicroPoint, _early_high_range_codes


class Strategy03EarlyLowTests(unittest.TestCase):
    def point(self, second: int, price: float, day_low: float) -> MicroPoint:
        return MicroPoint(
            ts=datetime(2026, 8, 13, 9, 0, 0) + timedelta(seconds=second),
            price=price,
            buy_money_cum=0.0,
            sell_money_cum=0.0,
            broker_day_low=day_low,
        )

    def signal(self) -> dict:
        anchor_ts = datetime(2026, 8, 13, 9, 0, 40)
        signal_ts = datetime(2026, 8, 13, 9, 1, 5)
        return {
            "mode": SIGNAL_MODE,
            "algorithm": EARLY_LOW_ALGORITHM,
            "entry_lane": EARLY_LOW_LANE,
            "action": "BUY_READY",
            "reason": "S03_EARLY_60S_LOW_REBOUND",
            "ts": signal_ts.isoformat(timespec="milliseconds"),
            "price": 101.2,
            "anchor_low": 100.0,
            "anchor_low_ts": anchor_ts.isoformat(timespec="milliseconds"),
            "anchor_id": f"{anchor_ts.isoformat(timespec='milliseconds')}:100.0000",
            "rebound_pct": 1.2,
            "signal_sequence": 1,
            "code": "000001",
            "name": "TEST",
        }

    def payload(self) -> dict:
        row = self.signal()
        return {
            "schema": SIGNAL_SCHEMA,
            "date": "20260813",
            "updated_at": row["ts"],
            "mode": SIGNAL_MODE,
            "signals": [row],
        }

    def test_captures_first_35_seconds_and_fires_on_price_only_rebound(self):
        detector = EarlyLowDetector()
        armed = detector.feed(self.point(20, 100.0, 100.0), allow_signal=True)
        fired = detector.feed(self.point(65, 101.2, 100.0), allow_signal=True)
        self.assertEqual(armed["action"], "ARMED")
        self.assertEqual(fired["action"], "BUY_READY")
        self.assertEqual(fired["reason"], "S03_EARLY_60S_LOW_REBOUND")
        self.assertEqual(fired["anchor_low"], 100.0)
        self.assertAlmostEqual(fired["rebound_pct"], 1.2)

    def test_blocks_code_for_day_after_crossing_two_percent_first(self):
        detector = EarlyLowDetector()
        detector.feed(self.point(20, 100.0, 100.0), allow_signal=True)
        blocked = detector.feed(self.point(65, 102.1, 100.0), allow_signal=True)
        later = detector.feed(self.point(70, 101.5, 100.0), allow_signal=True)
        self.assertEqual(blocked["reason"], "EARLY_LOW_REBOUND_CHASE_LIMIT")
        self.assertEqual(later["action"], "DONE")

    def test_contract_and_order_selector_require_no_flow_or_book_fields(self):
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        self.assertEqual(
            len(select_fresh_signals(payload, now=decision_now, max_age_sec=5)),
            1,
        )
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({
                    "codes": {
                        "000001": {
                            "ts": decision_now.isoformat(),
                            "cur": 101.2,
                        }
                    }
                }),
                encoding="utf-8",
            )
            selector = make_strategy03_signal_selector(
                snapshot_path, 4.0, early_low_live_enabled=True)
            selected = selector(payload, now=decision_now, max_age_sec=5)
        self.assertEqual([row["code"] for row in selected], ["000001"])

    def test_live_order_path_defaults_closed_until_production_replay(self):
        payload = self.payload()
        decision_now = datetime(2026, 8, 13, 9, 1, 6)
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps({
                    "codes": {
                        "000001": {
                            "ts": decision_now.isoformat(),
                            "cur": 101.2,
                        }
                    }
                }),
                encoding="utf-8",
            )
            selector = make_strategy03_signal_selector(
                snapshot_path, 4.0, early_low_live_enabled=False)
            selected = selector(payload, now=decision_now, max_age_sec=5)
        self.assertEqual(selected, [])

    def test_uses_exactly_first_forty_ranked_high_range_codes(self):
        payload = {
            "schema_version": 2,
            "for_date": "20260813",
            "source_stale": False,
            "candidates": [
                {"rank": rank, "code": f"{rank:06d}"}
                for rank in range(45, 0, -1)
            ],
        }
        codes = _early_high_range_codes(payload, "20260813")
        self.assertEqual(len(codes), 40)
        self.assertIn("000001", codes)
        self.assertIn("000040", codes)
        self.assertNotIn("000041", codes)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_03_deep_crash_shadow_ledger_v1 import (  # noqa: E402
    DeepCrashShadowLedger,
)


class DeepCrashShadowLedgerTest(unittest.TestCase):
    def test_ready_is_persisted_and_path_metrics_are_updated(self) -> None:
        ledger = DeepCrashShadowLedger("20260821")
        ts = datetime(2026, 8, 21, 9, 2)
        shadow = {
            "dcr_shadow_candidate": True,
            "dcr_low_pct": -10.5,
            "dcr_vi_suspect": False,
            "crs_observed_low": 9000.0,
            "crs_observed_low_ts": "2026-08-21T09:00:30.000",
            "crs_market_pct": -4.0,
            "crs_relative_strength_pct": -5.0,
            "crs_flow_turn": True,
            "crs_spread_bps": 10.0,
            "crs_best_bid_share": 0.55,
        }
        ledger.observe(code="000001", name="테스트", ts=ts, price=9090.0, shadow=shadow)
        ledger.observe(
            code="000001", name="테스트", ts=ts + timedelta(minutes=1),
            price=9270.0, shadow={"dcr_shadow_candidate": False},
        )
        ledger.observe(
            code="000001", name="테스트", ts=ts + timedelta(minutes=2),
            price=8910.0, shadow={"dcr_shadow_candidate": False},
        )
        payload = ledger.payload(ts + timedelta(minutes=2), finalize=True)
        self.assertEqual(payload["record_count"], 1)
        record = next(iter(payload["records"].values()))
        self.assertEqual(record["post_candidate_high"], 9270.0)
        self.assertEqual(record["post_candidate_low"], 8910.0)
        self.assertEqual(record["tracking_status"], "SIGNAL_TRACKING_FINAL_1431")
        self.assertEqual(record["order_qty"], 0)

    def test_restore_keeps_first_candidate_evidence(self) -> None:
        ts = datetime(2026, 8, 21, 9, 2)
        ledger = DeepCrashShadowLedger("20260821")
        shadow = {
            "dcr_shadow_candidate": True,
            "crs_observed_low": 9000.0,
            "crs_observed_low_ts": "2026-08-21T09:00:30.000",
        }
        ledger.observe(code="000001", name="테스트", ts=ts, price=9090.0, shadow=shadow)
        restored = DeepCrashShadowLedger.restore(ledger.payload(ts), "20260821")
        restored.observe(
            code="000001", name="테스트", ts=ts + timedelta(seconds=1),
            price=9100.0, shadow=shadow,
        )
        self.assertEqual(len(restored.records), 1)
        record = next(iter(restored.records.values()))
        self.assertEqual(record["candidate_ts"], ts.isoformat(timespec="milliseconds"))


if __name__ == "__main__":
    unittest.main()

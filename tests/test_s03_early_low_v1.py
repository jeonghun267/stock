# -*- coding: utf-8 -*-
"""S03 EARLY_LOW 활성 계약 집중 시험."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from s03_early_low_release_v1 import release_live_enabled
from strategy_03_signal_contract_v1 import (
    ACTIVE_ENTRY_LANES,
    EARLY_LOW_ALGORITHM,
    EARLY_LOW_LANE,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)
from 골짜기_급반등 import EarlyLowDetector, MicroPoint, _early_high_range_codes

MANIFEST = Path(r"C:\stock_bot\config\live_approved_hashes_v1.json")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8-sig"))


class EarlyLowLiveTests(unittest.TestCase):
    def point(self, second: int, price: float, day_low: float,
              buy: float = 0.0, sell: float = 0.0) -> MicroPoint:
        return MicroPoint(
            ts=datetime(2026, 8, 27, 9, 0, 0) + timedelta(seconds=second),
            price=price,
            open_price=10000.0,
            buy_money_cum=buy,
            sell_money_cum=sell,
            broker_day_low=day_low,
        )

    def test_detector_fires_after_3m_drop_and_two_up_ticks(self) -> None:
        detector = EarlyLowDetector()
        detector.feed(self.point(0, 10000.0, 10000.0), allow_signal=True)
        armed = detector.feed(self.point(20, 9700.0, 9700.0), allow_signal=True)
        self.assertEqual(armed["reason"], "EARLY_LOW_3M_DROP_ARMED")
        detector.feed(self.point(23, 9730.0, 9700.0), allow_signal=True)
        fired = detector.feed(
            self.point(25, 9760.0, 9700.0),
            allow_signal=True,
        )
        self.assertEqual(fired["action"], "BUY_READY")
        self.assertEqual(fired["entry_lane"], EARLY_LOW_LANE)
        self.assertEqual(fired["up_ticks"], 2)

    def test_detector_expires_low_after_60_seconds(self) -> None:
        detector = EarlyLowDetector()
        detector.feed(self.point(0, 10000.0, 10000.0), allow_signal=True)
        detector.feed(self.point(20, 9700.0, 9700.0), allow_signal=True)
        expired = detector.feed(self.point(81, 9750.0, 9700.0), allow_signal=True)
        self.assertEqual(expired["reason"], "EARLY_LOW_60S_TIMEOUT_WAIT_NEW_LOW")

    def test_contract_accepts_exact_early_low_signal(self) -> None:
        signal_ts = datetime(2026, 8, 27, 9, 0, 25)
        row = {
            "mode": SIGNAL_MODE,
            "algorithm": EARLY_LOW_ALGORITHM,
            "entry_lane": EARLY_LOW_LANE,
            "action": "BUY_READY",
            "reason": "S03_EARLY_LOW_3M_DROP_60S_REBOUND_2UP",
            "ts": signal_ts.isoformat(timespec="milliseconds"),
            "price": 9760.0,
            "anchor_low": 9700.0,
            "anchor_low_ts": datetime(2026, 8, 27, 9, 0, 20).isoformat(
                timespec="milliseconds"),
            "rebound_pct": 0.618557,
            "rapid_drop_pct": -3.0,
            "anchor_age_sec": 5.0,
            "low_stable_sec": 5.0,
            "up_ticks": 2,
            "signal_sequence": 1,
            "code": "000001",
        }
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": "20260827",
            "updated_at": signal_ts.isoformat(timespec="milliseconds"),
            "mode": SIGNAL_MODE,
            "signals": [row],
        }
        selected = select_fresh_signals(
            payload,
            now=datetime(2026, 8, 27, 9, 0, 26),
            max_age_sec=5,
        )
        self.assertEqual([item["code"] for item in selected], ["000001"])

    def test_live_feature_release_and_launcher_are_enabled(self) -> None:
        features = _manifest().get("live_features") or {}
        self.assertIs(features.get("S03_EARLY_LOW"), True)
        self.assertIn(EARLY_LOW_LANE, ACTIVE_ENTRY_LANES)
        self.assertTrue(release_live_enabled())
        launcher = (
            RUN / "hidden" / "SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd"
        ).read_text(encoding="ascii")
        self.assertIn("set S03_EARLY_LOW_LIVE=AUTO", launcher)


class EarlyHighRangeUniverseTests(unittest.TestCase):
    """살아 있는 배선 — 3레인 공용 유니버스 재료."""

    def test_uses_exactly_first_forty_ranked_high_range_codes(self) -> None:
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

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_07_flow_trend_shadow_v1 import build_shadow_plan, record_shadow_events


def test_s07_uses_six_separate_one_share_shadow_slots_without_orders() -> None:
    rows = []
    for index in range(8):
        rows.append({
            "code": str(700000 + index),
            "name": f"N{index}",
            "flow_score": 80 - index,
            "early_rebound_status": "EARLY_REBOUND",
            "liquidity_status": "WAIT" if index == 7 else "PASS",
            "volatility_status": "PASS",
        })
    plan = build_shadow_plan({"source_ts": "2026-09-01T14:00:00", "early_rebounds": rows})
    assert plan["strategy"] == "S07"
    assert plan["mode"] == "SHADOW_ORDER_ZERO"
    assert plan["separate_slot_pool"] is True
    assert plan["slot_count"] == 6
    assert len(plan["slots"]) == 6
    assert all(slot["quantity"] == 1 for slot in plan["slots"])
    assert all(slot["order_sent"] is False for slot in plan["slots"])
    assert plan["orders_sent"] == 0


class Strategy07ObservationTests(unittest.TestCase):
    def test_records_wait_candidates_and_audits_without_changing_slots(self) -> None:
        now = datetime(2026, 9, 2, 11, 1, 0)
        payload = {
            "source_ts": "2026-09-02T11:00:59",
            "display": [{
                "code": "417840",
                "name": "저스템",
                "entry_phase": "PULLBACK_READY",
                "flow_score": 78.3,
                "liquidity_status": "WAIT",
                "volatility_status": "WAIT",
            }],
        }
        micro = {"codes": {"417840": {"cur": 10000, "ts": now.isoformat()}}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.csv"
            observed, appended = record_shadow_events(payload, micro, now, path)
            self.assertEqual((observed, appended), (1, 1))
            observed, appended = record_shadow_events(payload, micro, now, path)
            self.assertEqual((observed, appended), (1, 0))

            later = now + timedelta(minutes=61)
            later_micro = {"codes": {"417840": {"cur": 10100, "ts": later.isoformat()}}}
            _, appended = record_shadow_events(payload, later_micro, later, path)
            self.assertEqual(appended, 2)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(
            [row["event"] for row in rows],
            ["SHADOW_ENTRY", "SHADOW_AUDIT_30M", "SHADOW_AUDIT_60M"],
        )
        self.assertIn("phase=PULLBACK_READY", rows[0]["reason"])
        self.assertIn("liq=WAIT", rows[0]["reason"])
        self.assertIn("vol=WAIT", rows[0]["reason"])
        self.assertIn("from_entry=+1.00%", rows[-1]["reason"])

        plan = build_shadow_plan(payload)
        self.assertEqual(plan["eligible_count"], 0)
        self.assertEqual(plan["funnel"], {
            "display": 1,
            "phase_matched": 1,
            "liq_pass": 0,
            "vol_pass": 0,
            "both_pass": 0,
            "observed": 0,
        })
        self.assertTrue(all(slot["status"] == "EMPTY" for slot in plan["slots"]))
        self.assertFalse(plan["order_capable"])
        self.assertEqual(plan["orders_sent"], 0)

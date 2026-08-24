# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from regime_exception_shadow_recorder_v1 import RegimeExceptionShadowRecorder
from regime_recovery_gate_shadow_v1 import RegimeRecoveryGateShadow


def put(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class RecorderTest(unittest.TestCase):
    def test_selects_s01_but_remains_order_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            now = datetime(2026, 8, 21, 9, 1, 10)
            points = {"123450": {
                "ts": "2026-08-21T09:01:09", "ob_ts": "2026-08-21T09:01:09",
                "cur": 11000, "op": 10500, "lo": 10200,
                "best_ask_px": 11010, "best_bid_px": 11000,
                "ask_tot": 4000, "bid_tot": 6000}}
            all_meta = {"123450": {"prev_close": 10000}}
            for index in range(40):
                code = f"{index:06d}"
                points[code] = {
                    "ts": "2026-08-21T09:01:09", "cur": 110,
                    "op": 100, "lo": 90}
                all_meta[code] = {"prev_close": 100}
            put(root / "data/kosdaq_index.json", {
                "ts": "2026-08-21T09:01:09", "price": 963,
                "prev": 1000, "chg": -3.7})
            put(root / "IPC/live_micro_snapshot.json", {
                "ts": "2026-08-21T09:01:10", "codes": points})
            put(root / "IPC/micro_watch_strategy_shared.json", {
                "for_date": "20260821", "all_meta": all_meta})
            put(root / "data/micro_rank_board.json", {
                "ts": "2026-08-21T09:01:10", "all_items": [{
                    "code": "123450", "money_5s_now": 200, "money_5s_prev": 100,
                    "che_delta_5s": 1, "snapshot_age_sec": 1,
                    "money_flow_data_quality": "OK"}]})
            put(root / "data/common_high_range_top30.json", {
                "generated_at": "2026-08-21T08:40:00", "candidates": [{
                    "rank": 1, "code": "123450", "prev_close": 10000}]})
            put(root / "data/common_high_range_live_state.json", {
                "updated_at": "2026-08-21T09:01:10", "codes": {"123450": {
                    "age_sec": 1, "low": 10200, "low_time": "2026-08-21T09:00:00",
                    "money_speed_vs_daily_avg": 3.2, "listed_turnover_pct": 0.4}}})
            put(root / "data/strategy_01_open_surge_signal_v2.json", {
                "signals": [{"ts": "2026-08-21T09:01:09", "code": "123450",
                             "action": "BUY_READY"}]})
            put(root / "data/strategy_02_low_buy_signal_v1.json", {"signals": []})
            put(root / "data/strategy_03_골짜기_급반등_signal_v1.json", {"signals": []})

            recorder = RegimeExceptionShadowRecorder(root)
            recorder.recovery_gate.day = "20260821"
            recorder.recovery_gate.state = "AMBER"
            recorder.recovery_gate.market_low_price = 950
            recorder.recovery_gate.market_low_at = datetime(2026, 8, 21, 8, 57)
            recorder.recovery_gate.advancer_share_at_low = 0.0
            recorder.recovery_gate.new_low_share_at_low = 1.0
            recorder.recovery_gate.amber_since = datetime(2026, 8, 21, 8, 56)
            recorder.recovery_gate.minute_prices = [
                ("202608210858", 950), ("202608210859", 954),
                ("202608210900", 958)]
            decisions = recorder.process_once(now)
            selected = next(row for row in decisions if row["shadow_selected"])
            self.assertEqual(selected["role"], "S01_CRASH_RS_LEADER")
            self.assertFalse(selected["live_eligible"])
            self.assertEqual(selected["order_qty"], 0)
            events = list((root / "data/shadow/regime_exception_events_20260821.jsonl")
                          .read_text(encoding="utf-8").splitlines())
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0])["mode"], "SHADOW_ORDER_ZERO")

    def test_recovery_gate_needs_breadth_then_falls_back_on_new_low(self) -> None:
        gate = RegimeRecoveryGateShadow()

        def snapshot(ts: str, above: int, near_low: int) -> dict:
            codes = {}
            for index in range(100):
                previous = 100.0
                if index < near_low:
                    price, low = 90.05, 90.0
                elif index < near_low + above:
                    price, low = 101.0, 90.0
                else:
                    price, low = 99.0, 90.0
                codes[f"{index:06d}"] = {
                    "ts": ts, "cur": price, "lo": low}
            return {"ts": ts, "codes": codes}

        previous_closes = {f"{index:06d}": 100.0 for index in range(100)}

        first = gate.evaluate(
            datetime(2026, 8, 21, 9, 0, 0),
            {"ts": "2026-08-21T09:00:00", "price": 950, "prev": 1000, "chg": -5.0},
            snapshot("2026-08-21T09:00:00", above=20, near_low=60),
            previous_closes,
        )
        for minute, price in ((1, 954), (2, 957), (3, 960)):
            gate.evaluate(
                datetime(2026, 8, 21, 9, minute, 0),
                {"ts": f"2026-08-21T09:0{minute}:00", "price": price,
                 "prev": 1000, "chg": (price / 1000 - 1) * 100},
                snapshot(f"2026-08-21T09:0{minute}:00", above=40, near_low=30),
                previous_closes,
            )
        recovered = gate.evaluate(
            datetime(2026, 8, 21, 9, 4, 0),
            {"ts": "2026-08-21T09:04:00", "price": 963, "prev": 1000, "chg": -3.7},
            snapshot("2026-08-21T09:04:00", above=40, near_low=30),
            previous_closes,
        )
        new_low = gate.evaluate(
            datetime(2026, 8, 21, 9, 4, 1),
            {"ts": "2026-08-21T09:04:01", "price": 940, "prev": 1000, "chg": -6.0},
            snapshot("2026-08-21T09:04:01", above=10, near_low=70),
            previous_closes,
        )
        self.assertEqual(first["state"], "RED")
        self.assertEqual(recovered["state"], "AMBER")
        self.assertEqual(new_low["state"], "RED")
        self.assertFalse(recovered["live_eligible"])
        self.assertEqual(recovered["order_qty"], 0)


if __name__ == "__main__":
    unittest.main()

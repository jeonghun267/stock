# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
RUN = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(RUN))

import strategy_03_rotation_engine_v1 as s03
from strategy_01_rotation_engine_v2 import Strategy01Engine
from strategy_common_hold_sell_v1 import HoldSellObservation, StrategyId


class AuditCapture:
    def __init__(self) -> None:
        self.records = []

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


class Strategy03LowCaptureTests(unittest.TestCase):
    def test_a_intraday_low_break_is_audited_but_preserves_decision(self) -> None:
        audit = AuditCapture()
        engine = s03.Strategy03HoldSellEngine.__new__(s03.Strategy03HoldSellEngine)
        engine.audit_recorder = audit
        engine._s03_entry_reference_low = Decimal("100")
        engine._s03_early_peak_live_enabled = False
        state = SimpleNamespace(
            strategy_id=StrategyId.VALLEY_MORNING_CRASH,
            entry_lane=s03.INTRADAY_CRASH_LANE,
            to_dict=lambda: {"position_id": "s03:test"},
        )
        observation = HoldSellObservation(
            observed_at=datetime(
                2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")
            ),
            price=Decimal("99.6"),
            buy_money_per_sec_10s=Decimal("50"),
            sell_money_per_sec_10s=Decimal("130"),
            sell_money_per_sec_30s=Decimal("100"),
        )
        sentinel = object()
        with (
            patch.object(engine, "_evaluate_strategy03_once", return_value=sentinel),
            patch.object(
                engine,
                "_s03_early_peak_v2",
                return_value={"would_exit_s03_early_peak": False},
            ),
        ):
            decision = engine.evaluate(state, observation)
        self.assertIs(decision, sentinel)
        self.assertTrue(audit.records[0]["state_before"]["would_exit_low_break"])
        self.assertTrue(audit.records[0]["state_after"]["would_exit_low_break"])

    def test_b_buy_confirmed_reason_contains_lane(self) -> None:
        engine = s03.Strategy03Engine.__new__(s03.Strategy03Engine)
        engine._s03_confirm_lane = s03.OPEN_CRASH_LANE
        with patch.object(Strategy01Engine, "_event") as parent_event:
            engine._event(
                "BUY_CONFIRMED",
                code="005930",
                reason="exact fill rank=1/1",
            )
        reason = parent_event.call_args.kwargs["reason"]
        self.assertEqual(reason, "exact fill rank=1/1 lane=OPEN_CRASH")

    def test_c_atrp_drop_and_kosdaq_fields_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "kosdaq_index.json"
            history_path = root / "history.csv"
            index_path.write_text(
                json.dumps({
                    "ts": "2026-08-28 10:05:00",
                    "price": 1010.0,
                    "prev": 1000.0,
                    "chg": 1.0,
                }),
                encoding="utf-8",
            )
            with history_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["기록시각", "지수시각", "지수", "등락률"],
                )
                writer.writeheader()
                writer.writerow({
                    "기록시각": "2026-08-28T10:00:01",
                    "지수시각": "2026-08-28 10:00:00",
                    "지수": "1000",
                    "등락률": "0",
                })
            market = s03._s03_kosdaq_5m_context(
                index_path,
                history_path,
                datetime(2026, 8, 28, 10, 5, 5),
            )
            self.assertEqual(market["kosdaq_5m_change_pct"], 1.0)
            self.assertEqual(market["kosdaq_sample_interval_sec"], 300)
            drop = s03._s03_entry_drop_pct(
                {"anchor_low": 90, "intraday_high": 100},
                s03.INTRADAY_CRASH_LANE,
            )
            self.assertEqual(drop, 10.0)
            atrp = s03.atrp10_pct([(101.0, 99.0, 100.0)] * 10)
            self.assertGreater(atrp, 0)

            engine = s03.Strategy03Engine.__new__(s03.Strategy03Engine)
            engine.config = SimpleNamespace(
                strategy_id=StrategyId.VALLEY_MORNING_CRASH
            )
            engine.log = SimpleNamespace(exception=lambda *args, **kwargs: None)
            position = {
                "code": "005930",
                "name": "test",
                "entry_lane": s03.INTRADAY_CRASH_LANE,
                "s03_entry_reference_low": 90.0,
                "s03_atrp10_pct": atrp,
                "s03_entry_drop_pct": drop,
                "s03_drop_atrp_multiple": drop / atrp,
                "s03_kosdaq_5m_change_pct": market["kosdaq_5m_change_pct"],
                "s03_kosdaq_index_ts": market["kosdaq_index_ts"],
                "s03_kosdaq_prior_ts": market["kosdaq_prior_ts"],
                "s03_kosdaq_sample_interval_sec": market[
                    "kosdaq_sample_interval_sec"
                ],
                "s03_kosdaq_source": market["kosdaq_source"],
            }
            audit_dir = root / "audit"
            with patch.object(s03, "S03_ENTRY_CONTEXT_AUDIT_DIR", audit_dir):
                engine._append_s03_entry_context(
                    position,
                    datetime(2026, 8, 28, 10, 5, 5),
                    shadow=False,
                )
            record = json.loads(next(audit_dir.glob("*.jsonl")).read_text(
                encoding="utf-8"
            ))
            self.assertEqual(record["lane"], s03.INTRADAY_CRASH_LANE)
            self.assertIn("atrp10_pct", record)
            self.assertIn("drop_atrp_multiple", record)
            self.assertIn("kosdaq_5m_change_pct", record)

    def test_d_bottom_quality_v2_is_shadow_only(self) -> None:
        signal = {
            "anchor_low": 100.0,
            "previous_buy_rate_10s": 100.0,
            "recent_buy_rate_10s": 150.0,
            "recent_sell_rate_10s": 120.0,
        }
        ready = s03._s03_bottom_quality_v2_shadow(
            signal,
            entry_price=101.0,
            ma20=100.0,
            atrp10=2.5,
            kosdaq_5m_change_pct=-0.2,
        )
        self.assertEqual(ready["mode"], "SHADOW_ORDER_ZERO")
        self.assertTrue(ready["shadow_ready"])
        self.assertFalse(ready["would_block_bottom_quality_v2"])
        self.assertEqual(ready["rebound_pct_at_entry"], 1.0)
        self.assertEqual(ready["rebound_atrp_ratio"], 0.4)

        overheated = s03._s03_bottom_quality_v2_shadow(
            signal,
            entry_price=116.0,
            ma20=100.0,
            atrp10=2.0,
            kosdaq_5m_change_pct=-0.2,
        )
        self.assertTrue(overheated["ma20_overheated_above_15pct"])
        self.assertTrue(overheated["would_block_bottom_quality_v2"])

    def test_e_bottom_quality_v2_atr_normalization_injection(self) -> None:
        result = s03._s03_bottom_quality_v2_shadow(
            {
                "anchor_low": 100.0,
                "previous_buy_rate_10s": 100.0,
                "recent_buy_rate_10s": 150.0,
                "recent_sell_rate_10s": 120.0,
            },
            entry_price=101.0,
            ma20=100.0,
            atrp10=10.0 / 3.0,
            kosdaq_5m_change_pct=-0.2,
        )
        self.assertEqual(result["mode"], "SHADOW_ORDER_ZERO")
        self.assertTrue(result["shadow_ready"])
        self.assertFalse(result["would_block_bottom_quality_v2"])
        self.assertEqual(result["rebound_pct_at_entry"], 1.0)
        self.assertEqual(result["rebound_atrp_ratio"], 0.3)

    def test_f_d_e_ratios_do_not_change_shadow_decision(self) -> None:
        signal = {
            "anchor_low": 100.0,
            "previous_buy_rate_10s": 100.0,
            "recent_buy_rate_10s": 150.0,
            "recent_sell_rate_10s": 120.0,
        }
        results = [
            s03._s03_bottom_quality_v2_shadow(
                signal,
                entry_price=101.0,
                ma20=100.0,
                atrp10=atrp10,
                kosdaq_5m_change_pct=-0.2,
            )
            for atrp10 in (2.5, 10.0 / 3.0)
        ]
        self.assertEqual(
            [row["rebound_atrp_ratio"] for row in results],
            [0.4, 0.3],
        )
        self.assertTrue(all(row["shadow_ready"] for row in results))
        self.assertTrue(all(
            not row["would_block_bottom_quality_v2"] for row in results
        ))

    def test_g_confirm_entry_wires_v2_into_audit_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp) / "audit"
            engine = s03.Strategy03Engine.__new__(s03.Strategy03Engine)
            engine.config = SimpleNamespace(
                strategy_id=StrategyId.VALLEY_MORNING_CRASH
            )
            engine._s03_daily_trend = {"005930": {"ma20": 100.0}}
            engine._s03_atrp10 = {"005930": 2.5}
            engine.log = SimpleNamespace(exception=lambda *args, **kwargs: None)
            position = {
                "code": "005930",
                "name": "test",
                "entry_lane": s03.INTRADAY_CRASH_LANE,
                "last_price": 101.0,
                "signal_snapshot": {
                    "anchor_low": 100.0,
                    "intraday_high": 110.0,
                    "previous_buy_rate_10s": 100.0,
                    "recent_buy_rate_10s": 150.0,
                    "recent_sell_rate_10s": 120.0,
                },
            }
            market = {
                "kosdaq_5m_change_pct": -0.2,
                "kosdaq_index_ts": "2026-08-28 10:05:00",
                "kosdaq_prior_ts": "2026-08-28 10:00:00",
                "kosdaq_sample_interval_sec": 300,
                "kosdaq_source": "test",
            }
            with (
                patch.object(engine, "_load_s03_daily_trend"),
                patch.object(s03, "_s03_kosdaq_5m_context", return_value=market),
                patch.object(Strategy01Engine, "_confirm_entry"),
                patch.object(s03, "S03_ENTRY_CONTEXT_AUDIT_DIR", audit_dir),
            ):
                engine._confirm_entry(
                    position,
                    quantity=1,
                    fill_price=101.0,
                    observed_at=datetime(2026, 8, 28, 10, 5, 5),
                    shadow=False,
                )

            record = json.loads(next(audit_dir.glob("*.jsonl")).read_text(
                encoding="utf-8"
            ))
            wired = record["s03_bottom_quality_v2"]
            self.assertEqual(wired["mode"], "SHADOW_ORDER_ZERO")
            self.assertTrue(wired["shadow_ready"])
            self.assertEqual(wired["rebound_pct_at_entry"], 1.0)
            self.assertEqual(wired["rebound_atrp_ratio"], 0.4)

            position["signal_snapshot"] = {
                **position["signal_snapshot"],
                "anchor_low": 95.0,
            }
            with (
                patch.object(engine, "_load_s03_daily_trend"),
                patch.object(s03, "_s03_kosdaq_5m_context", return_value=market),
                patch.object(Strategy01Engine, "_confirm_entry"),
                patch.object(engine, "_append_s03_entry_context"),
            ):
                engine._confirm_entry(
                    position,
                    quantity=1,
                    fill_price=101.0,
                    observed_at=datetime(2026, 8, 28, 10, 6, 5),
                    shadow=False,
                )
            self.assertEqual(position["s03_entry_reference_low"], 95.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

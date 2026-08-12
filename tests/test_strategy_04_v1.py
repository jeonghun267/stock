from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_04_preflight_v1 as preflight
from strategy_04_pullback_signal_v1 import (
    Bar,
    MicroPoint,
    PullbackSignalMonitor,
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    SignalConfig,
    _append_events,
    detect_deep_w,
)
from strategy_04_rotation_engine_v1 import build_config
from strategy_04_signal_contract_v1 import select_fresh_signals
from strategy_common_hold_sell_v1 import STRATEGY_PROFILES, StrategyId


def synthetic_w(*, scale: float = 100.0) -> list[Bar]:
    base = datetime(2026, 7, 27, 9, 0)
    closes = [
        95, 94, 92, 88, 86, 87, 88.5, 90, 89, 88, 87,
        86.8, 87, 88, 88.5, 88, 87.8, 88, 88.5, 89, 90.5,
    ]
    bars: list[Bar] = []
    for index, raw_close in enumerate(closes):
        close = raw_close * scale / 100.0
        low = (raw_close - 0.2) * scale / 100.0
        high = (raw_close + 0.2) * scale / 100.0
        if index == 4:
            low = 86 * scale / 100.0
        if index == 7:
            high = 90 * scale / 100.0
        if index == 11:
            low = 86.8 * scale / 100.0
        bars.append(Bar(
            ts=base + timedelta(minutes=3 * index),
            open=close,
            high=high,
            low=low,
            close=close,
        ))
    return bars


class DeepWTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SignalConfig(min_price=10_000)
        self.bars = synthetic_w(scale=100_000)

    def test_requires_ma3_cross_and_neckline_reclaim(self) -> None:
        pattern = detect_deep_w(
            self.bars,
            prev_close=100_000,
            config=self.config,
        )
        self.assertIsNotNone(pattern)
        self.assertLessEqual(pattern["drop_pct"], -10)
        self.assertGreater(pattern["ma3"], pattern["ma20"])
        self.assertGreaterEqual(self.bars[-1].close, pattern["neckline"])

        no_cross = list(self.bars)
        last = no_cross[-1]
        no_cross[-1] = Bar(
            ts=last.ts,
            open=88_000,
            high=88_200,
            low=87_800,
            close=88_000,
        )
        self.assertIsNone(detect_deep_w(
            no_cross,
            prev_close=100_000,
            config=self.config,
        ))

    def test_microstructure_market_cost_and_duplicate_gates(self) -> None:
        monitor = PullbackSignalMonitor(self.config)
        state = monitor.states.setdefault("123456", preflight_state())
        state.bars.extend(self.bars)
        monitor.market_changes.extend([
            (datetime(2026, 7, 27, 9, 0), -0.4),
            (datetime(2026, 7, 27, 10, 0), -0.2),
        ])
        fired_rows = []
        base = datetime(2026, 7, 27, 10, 0, 1)
        for second in range(13):
            point = MicroPoint(
                ts=base + timedelta(seconds=second),
                price=90_000 + second * 20,
                buy_money_cum=1_000_000 + second * 700_000,
                sell_money_cum=1_000_000 + second * 300_000,
                bid_share=0.45 + second * 0.0125,
                spread_bps=10,
                microprice_edge_bps=2,
                ask_price=90_300,
            )
            row, fired = monitor.process_micro(
                "123456",
                "테스트",
                point,
                100_000,
                market_fresh=True,
                market_change=-0.2,
                allow_signal=True,
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(len(fired_rows), 1)
        self.assertEqual(fired_rows[0]["action"], "BUY_READY")
        self.assertGreater(fired_rows[0]["gross_edge_pct"], 0)
        self.assertEqual(state.emission_count, 1)

        duplicate, fired = monitor.process_micro(
            "123456",
            "테스트",
            MicroPoint(
                ts=base + timedelta(seconds=14),
                price=90_300,
                buy_money_cum=11_000_000,
                sell_money_cum=5_000_000,
                bid_share=0.62,
                spread_bps=10,
                microprice_edge_bps=2,
                ask_price=90_400,
            ),
            100_000,
            market_fresh=True,
            market_change=-0.2,
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertEqual(duplicate["reason"], "ANCHOR_OR_CYCLE_ALREADY_USED")

    def test_extreme_drop_is_observed_but_not_buy_ready(self) -> None:
        scaled = synthetic_w(scale=97_000)
        config = SignalConfig(min_price=10_000)
        pattern = detect_deep_w(scaled, prev_close=110_000, config=config)
        self.assertIsNotNone(pattern)
        self.assertLess(pattern["drop_pct"], config.min_drop_pct)
        monitor = PullbackSignalMonitor(config)
        state = monitor.states.setdefault("123456", preflight_state())
        state.bars.extend(scaled)
        row, fired = monitor.process_micro(
            "123456", "테스트", MicroPoint(
                ts=datetime(2026, 7, 27, 10, 1), price=87_800,
                buy_money_cum=1_000_000, sell_money_cum=500_000,
                bid_share=0.60, spread_bps=10, microprice_edge_bps=2,
                ask_price=87_900,
            ), 110_000, market_fresh=True, market_change=0, allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "EXTREME_DROP_NEWS_RISK_UNRESOLVED")

    def test_extreme_second_low_is_not_buy_ready(self) -> None:
        monitor = PullbackSignalMonitor(self.config)
        state = monitor.states.setdefault("123456", preflight_state())
        state.bars.extend(self.bars)
        pattern = detect_deep_w(
            self.bars,
            prev_close=100_000,
            config=self.config,
        )
        self.assertIsNotNone(pattern)
        pattern["drop_pct"] = -17.0
        pattern["second_drop_pct"] = -18.66
        with patch(
            "strategy_04_pullback_signal_v1.detect_deep_w",
            return_value=pattern,
        ):
            row, fired = monitor.process_micro(
                "123456", "???", MicroPoint(
                    ts=datetime(2026, 7, 27, 10, 1),
                    price=90_000,
                    buy_money_cum=1_000_000,
                    sell_money_cum=500_000,
                    bid_share=0.60,
                    spread_bps=10,
                    microprice_edge_bps=2,
                    ask_price=90_100,
                ), 100_000, market_fresh=True, market_change=0,
                allow_signal=True,
            )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "EXTREME_DROP_NEWS_RISK_UNRESOLVED")

    def test_event_csv_lock_does_not_stop_signal_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "funnel.csv"
            with patch.object(
                Path, "open", side_effect=PermissionError("locked"),
            ):
                self.assertFalse(_append_events(path, [{"reason": "WAIT"}]))


def preflight_state():
    from strategy_04_pullback_signal_v1 import CodeState
    return CodeState()


class ContractAndWiringTests(unittest.TestCase):
    def test_contract_freshness_and_consumed_dedup(self) -> None:
        now = datetime(2026, 7, 27, 10, 1, 0)
        row = {
            "ts": now.isoformat(timespec="seconds"),
            "code": "123456",
            "action": "BUY_READY",
            "mode": SIGNAL_MODE,
            "signal_sequence": 1,
            "anchor_id": "2026-07-27T09:30:86000",
            "algorithm": "S04_DEEP_W_PRO_V1",
            "reason": "DEEP_W_MA3_CROSS_NECKLINE+FLOW+BOOK+MARKET+COST",
            "first_low": 83_000,
            "second_low": 83_500,
            "neckline": 88_000,
            "drop_pct": -17.0,
            "second_drop_pct": -16.5,
            "rebound_pct": 6.0,
            "low_difference_pct": 0.6,
            "ma3": 90_000,
            "ma20": 89_000,
            "price": 90_000,
            "ask_price": 90_100,
            "current_chase_pct": 3.0,
            "buy_ratio": 0.60,
            "flow_observation_sec": 10.0,
            "book_bid_share": 0.60,
            "book_recovery": 0.08,
            "spread_bps": 10.0,
            "microprice_edge_bps": 2.0,
            "rising_sec": 3.0,
            "market_fresh": True,
            "market_change_pct": -0.2,
            "market_recovery_pct": 0.2,
            "gross_edge_pct": 2,
            "expected_cost_pct": 0.5,
        }
        payload = {
            "schema": SIGNAL_SCHEMA,
            "mode": SIGNAL_MODE,
            "date": "20260727",
            "updated_at": now.isoformat(timespec="seconds"),
            "signals": [row],
        }
        selected = select_fresh_signals(
            payload, now=now, max_age_sec=5, consumed=())
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["strategy_id"], "S04_PULLBACK")
        self.assertEqual(select_fresh_signals(
            payload,
            now=now,
            max_age_sec=5,
            consumed=[selected[0]["signal_id"]],
        ), [])
        invalid = dict(row)
        invalid["signal_sequence"] = 99
        payload["signals"] = [invalid]
        self.assertEqual(select_fresh_signals(payload, now=now, max_age_sec=5), [])

    def test_common_rotation_identity_and_limits(self) -> None:
        with patch.dict(os.environ, {"S04_LIVE": "NO"}, clear=False):
            config = build_config()
        self.assertFalse(config.live_requested)
        # ★[2026-08-06 친구님 지시 "QTY 2주 원래대로 1주로 돌려줘"] 2 -> 1.
        self.assertEqual(config.quantity, 1)
        self.assertEqual(config.max_slots, 6)
        self.assertEqual(config.max_daily_codes, 6)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.rotation_capital_krw, 2_000_000)
        self.assertEqual(config.strategy_id, StrategyId.S04_PULLBACK)
        self.assertIn(StrategyId.S04_PULLBACK, STRATEGY_PROFILES)

    def test_preflight_check_cannot_create_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval = root / "approved.flag"
            off = root / "off.flag"
            off.write_text("OFF\n", encoding="ascii")
            with (
                patch.object(preflight, "APPROVAL", approval),
                patch.object(preflight, "OFF", off),
                patch.object(preflight, "AUDIT", root / "audit.json"),
                patch.object(preflight, "validate", return_value={"ok": True}),
            ):
                self.assertEqual(
                    preflight.run(
                        activate=False,
                        now=datetime(2026, 7, 27, 9, 57),
                    ),
                    0,
                )
            self.assertFalse(approval.exists())
            self.assertTrue(off.exists())

    def test_today_only_auto_approval_selector(self) -> None:
        today = datetime(2026, 7, 27, 9, 57)
        tomorrow = datetime(2026, 7, 28, 9, 57)
        self.assertTrue(preflight.activation_requested(
            approve=False, approve_on="20260727", now=today))
        self.assertFalse(preflight.activation_requested(
            approve=False, approve_on="20260727", now=tomorrow))
        self.assertTrue(preflight.activation_requested(
            approve=True, approve_on="", now=tomorrow))

    def test_explicit_approval_is_same_day_and_removes_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval = root / "approved.flag"
            off = root / "off.flag"
            off.write_text("OFF\n", encoding="ascii")
            with (
                patch.object(preflight, "APPROVAL", approval),
                patch.object(preflight, "OFF", off),
            ):
                preflight.approve(datetime(2026, 7, 27, 9, 58))
            self.assertIn("20260727", approval.read_text(encoding="ascii"))
            self.assertFalse(off.exists())
            self.assertTrue((root / "off.flag.disabled").exists())

    def test_same_day_approval_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval = root / "approved.flag"
            off = root / "off.flag"
            disabled = root / "off.flag.disabled"
            approval.write_text(
                "APPROVED_BY_OWNER 20260727 09:58:00\n", encoding="ascii")
            disabled.write_text("OFF\n", encoding="ascii")
            with (
                patch.object(preflight, "APPROVAL", approval),
                patch.object(preflight, "OFF", off),
            ):
                self.assertEqual(
                    preflight.approve(datetime(2026, 7, 27, 10, 0)),
                    "ALREADY_APPROVED_TODAY",
                )

    def test_new_day_restores_off_and_revokes_stale_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approval = root / "approved.flag"
            off = root / "off.flag"
            disabled = root / "off.flag.disabled"
            approval.write_text(
                "APPROVED_BY_OWNER 20260727 09:58:00\n", encoding="ascii")
            disabled.write_text("OFF\n", encoding="ascii")
            status = preflight.prepare_daily_guard(
                datetime(2026, 7, 28, 9, 57),
                approval_path=approval,
                off_path=off,
            )
            self.assertEqual(status, "STALE_APPROVAL_REVOKED")
            self.assertTrue(off.exists())
            self.assertFalse(disabled.exists())
            self.assertFalse(approval.exists())


if __name__ == "__main__":
    unittest.main()

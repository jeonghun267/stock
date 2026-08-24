from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from strategy_common_reentry_gate_v1 import (
    LossReentryGate,
    record_reentry_snapshot,
)


KST = ZoneInfo("Asia/Seoul")


class LossReentryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exit_at = datetime(2026, 8, 18, 9, 21, 41, tzinfo=KST)
        self.state = {
            "history": [{
                "code": "108490",
                "exit_at": self.exit_at.isoformat(),
                "gross_return_pct": -1.85,
            }]
        }

    def bars(self, *, stable_after_low: int) -> dict:
        start = self.exit_at.replace(hour=9, minute=10, second=0, microsecond=0)
        rows = []
        minutes = []
        for index in range(18):
            ts = start + timedelta(minutes=index)
            close = 297000 - index * 100
            low = close - 200
            if index == 12:
                low = 290500
                close = 291000
            if index > 12:
                low = 291000 + (index - 13) * 100
                close = low + 500
            rows.append([close - 100, close + 300, low, close])
            minutes.append(ts.strftime("%Y%m%d%H%M"))
        keep = 13 + stable_after_low + 1
        return {"m": {"108490": {"pm": minutes[:keep], "prev": rows[:keep]}}}

    def signal(self, ts: datetime) -> dict:
        return {
            "ts": ts.isoformat(),
            "signal_id": "fresh-2",
            "money_buy_turn": True,
            "volume_buy_turn": True,
            "che_rising": True,
        }

    def test_blocks_before_three_completed_bars_after_latest_low(self) -> None:
        gate = LossReentryGate()
        signal_at = self.exit_at + timedelta(minutes=3)
        decision = gate.evaluate(
            strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
            code="108490",
            signal=self.signal(signal_at),
            current_price=293500,
            states=[self.state],
            bars_payload=self.bars(stable_after_low=1),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "REENTRY_NEW_LOW_STABILITY_WAIT")

    def test_passes_only_on_third_buy_side_confirmation(self) -> None:
        gate = LossReentryGate()
        signal_at = self.exit_at + timedelta(minutes=8)
        decisions = [
            gate.evaluate(
                strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
                code="108490",
                signal=self.signal(signal_at),
                current_price=293500,
                states=[self.state],
                bars_payload=self.bars(stable_after_low=4),
            )
            for _ in range(3)
        ]
        self.assertEqual(
            [decision.allowed for decision in decisions], [False, False, True]
        )
        self.assertEqual(decisions[-1].reason, "REENTRY_GATE_PASS")

    def test_snapshot_preserves_replay_inputs(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        gate = LossReentryGate()
        signal_at = self.exit_at + timedelta(minutes=8)
        signal = self.signal(signal_at)
        bars = self.bars(stable_after_low=4)
        decision = gate.evaluate(
            strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
            code="108490",
            signal=signal,
            current_price=293500,
            states=[self.state],
            bars_payload=bars,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = record_reentry_snapshot(
                root=Path(directory),
                strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
                code="108490",
                signal=signal,
                current_price=293500,
                states=[self.state],
                bars_payload=bars,
                decision=decision,
                mode="SHADOW",
                engine_paths=(Path(__file__),),
            )
            self.assertIsNotNone(target)
            row = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["code"], "108490")
            self.assertEqual(row["latest_closed_trade"]["gross_return_pct"], -1.85)
            self.assertGreaterEqual(len(row["bars"]["prev"]), 10)
            self.assertEqual(row["decision"]["reason"], decision.reason)

    def test_s02_live_rule_waits_15_minutes(self) -> None:
        self.state["history"][0].update({
            "entry_price": 297000,
            "exit_price": 291500,
            "trough_price": 291500,
        })
        gate = LossReentryGate(
            min_wait_sec=900,
            require_new_low=True,
            min_stable_bars=0,
            atr_multiplier=0,
            buy_confirmations=3,
        )
        decision = gate.evaluate(
            strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
            code="108490",
            signal=self.signal(self.exit_at + timedelta(minutes=14, seconds=59)),
            current_price=293500,
            states=[self.state],
            bars_payload=self.bars(stable_after_low=4),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "REENTRY_COOLDOWN_WAIT")

    def test_s02_live_rule_requires_lower_low(self) -> None:
        self.state["history"][0].update({
            "entry_price": 297000,
            "exit_price": 291500,
            "trough_price": 290000,
        })
        gate = LossReentryGate(
            min_wait_sec=900,
            require_new_low=True,
            min_stable_bars=0,
            atr_multiplier=0,
            buy_confirmations=3,
        )
        decision = gate.evaluate(
            strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
            code="108490",
            signal=self.signal(self.exit_at + timedelta(minutes=16)),
            current_price=293500,
            states=[self.state],
            bars_payload=self.bars(stable_after_low=4),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "REENTRY_NEW_LOW_REQUIRED")

    def test_s02_live_rule_passes_on_third_confirmation(self) -> None:
        self.state["history"][0].update({
            "entry_price": 297000,
            "exit_price": 291500,
            "trough_price": 291500,
        })
        gate = LossReentryGate(
            min_wait_sec=900,
            require_new_low=True,
            min_stable_bars=0,
            atr_multiplier=0,
            buy_confirmations=3,
        )
        decisions = [
            gate.evaluate(
                strategy_id="S02_LOW_BUY_SELL_EXHAUSTION",
                code="108490",
                signal=self.signal(self.exit_at + timedelta(minutes=16)),
                current_price=293500,
                states=[self.state],
                bars_payload=self.bars(stable_after_low=4),
            )
            for _ in range(3)
        ]
        self.assertEqual(
            [decision.allowed for decision in decisions], [False, False, True]
        )
        self.assertEqual(decisions[-1].reason, "REENTRY_GATE_PASS")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_all_auto_live_preflight_v1 import (
    _write_audit_preserving_approved_pass,
    activate_all_flags,
)
from strategy_all_live_gate_launcher_v1 import audit_state, main as gate_launcher_main
from strategy_01_rotation_engine_v2 import Strategy01Engine
from strategy_common_hold_sell_v1 import StrategyId


class AllStrategyAutoLiveTests(unittest.TestCase):
    def test_redundant_approval_failure_preserves_today_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            passed = {
                "for_date": "20260727",
                "passed": True,
                "activated": True,
                "activated_strategies": ["S01", "S02", "S03"],
            }
            audit.write_text(json.dumps(passed), encoding="utf-8")
            failed = {
                "for_date": "20260727",
                "passed": False,
                "reason": "PreflightFailure:S03_ALREADY_APPROVED_TODAY",
            }
            self.assertTrue(_write_audit_preserving_approved_pass(
                failed, audit_path=audit))
            self.assertTrue(
                json.loads(audit.read_text(encoding="utf-8"))["passed"])
            attempt = audit.with_name("audit_last_attempt.json")
            self.assertTrue(attempt.exists())
            self.assertTrue(json.loads(
                attempt.read_text(encoding="utf-8")
            )["primary_audit_preserved"])

    def test_all_flags_activate_together(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            strategies = {}
            for strategy in ("S01", "S02", "S03"):
                off = root / f"{strategy}.off"
                approval = root / f"{strategy}.approval"
                off.write_text("OFF\n", encoding="ascii")
                strategies[strategy] = {
                    "off": off,
                    "approval": approval,
                }
            activated = activate_all_flags(
                strategies,
                now=datetime(2026, 7, 27, 8, 59, 50),
            )
            self.assertEqual(activated, ["S01", "S02", "S03"])
            for paths in strategies.values():
                self.assertFalse(paths["off"].exists())
                self.assertTrue(paths["approval"].exists())

    def test_gate_requires_today_pass_and_strategy_membership(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            audit = Path(raw) / "audit.json"
            audit.write_text(json.dumps({
                "for_date": "20260727",
                "passed": True,
                "activated": True,
                "activated_strategies": ["S01", "S02", "S03"],
                "finished_at": "2026-07-27T09:00:01",
            }), encoding="utf-8")
            self.assertEqual(audit_state("S01", "20260727", audit), "PASS")
            self.assertEqual(audit_state("S02", "20260727", audit), "PASS")
            self.assertEqual(audit_state("S03", "20260728", audit), "WAIT")

            payload = json.loads(audit.read_text(encoding="utf-8"))
            payload["activated_strategies"] = ["S01", "S03"]
            audit.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(audit_state("S02", "20260727", audit), "FAIL")

    def test_s01_s02_s03_all_start_in_gate_controlled_standby(self) -> None:
        for strategy in ("S01", "S02", "S03"):
            with self.subTest(strategy=strategy), patch(
                "strategy_all_live_gate_launcher_v1.verify_live_hashes",
                return_value=(True, []),
            ), patch(
                "strategy_all_live_gate_launcher_v1._engine_main",
                return_value=0,
            ) as engine_main, patch.object(
                sys, "argv", ["launcher", "--strategy", strategy],
            ):
                self.assertEqual(gate_launcher_main(), 0)
                engine_main.assert_called_once_with(strategy)

    def test_gate_closed_does_not_select_or_consume_s01_s02_s03_signal(self) -> None:
        strategy_ids = (
            StrategyId.S01_OPEN_SURGE,
            StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            StrategyId.VALLEY_MORNING_CRASH,
        )
        for strategy_id in strategy_ids:
            with self.subTest(strategy_id=strategy_id.value):
                engine = object.__new__(Strategy01Engine)
                engine.config = SimpleNamespace(strategy_id=strategy_id)
                engine.state = {
                    "recovery_blocked": False,
                    "consumed_signals": [],
                }
                engine.broker = SimpleNamespace(
                    buy_allowed=False,
                    live_requested=True,
                )
                engine._last_s01_buy_gate_allowed = None
                engine.log = SimpleNamespace(
                    critical=lambda *args, **kwargs: None,
                    info=lambda *args, **kwargs: None,
                )
                engine.events = []
                engine._event = lambda kind, **fields: engine.events.append(kind)
                engine.signal_selector = lambda *args, **kwargs: self.fail(
                    "closed gate selected a signal"
                )

                engine._try_entries(datetime(2026, 8, 13, 9, 0, 0))

                self.assertEqual(engine.state["consumed_signals"], [])
                self.assertEqual(engine.events, ["BUY_GATE_CLOSED"])

    def test_gate_open_uses_existing_five_second_freshness_selector(self) -> None:
        for strategy_id in (
            StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            StrategyId.VALLEY_MORNING_CRASH,
        ):
            with self.subTest(strategy_id=strategy_id.value):
                calls = []
                engine = object.__new__(Strategy01Engine)
                engine.config = SimpleNamespace(
                    strategy_id=strategy_id,
                    signal_path=Path("signal.json"),
                    signal_max_age_sec=5.0,
                    bars_path=Path("bars.json"),
                )
                engine.state = {
                    "recovery_blocked": False,
                    "consumed_signals": [],
                }
                engine.broker = SimpleNamespace(
                    buy_allowed=True,
                    live_requested=True,
                )
                engine._last_s01_buy_gate_allowed = False
                engine.log = SimpleNamespace(
                    critical=lambda *args, **kwargs: None,
                    info=lambda *args, **kwargs: None,
                )
                engine._event = lambda *args, **kwargs: None
                engine.signal_selector = lambda payload, **kwargs: (
                    calls.append(kwargs) or []
                )
                now = datetime(2026, 8, 13, 9, 0, 5)
                with patch(
                    "strategy_01_rotation_engine_v2.read_json",
                    return_value={"signals": []},
                ), patch(
                    "strategy_01_rotation_engine_v2.read_json_cached",
                    return_value={},
                ):
                    engine._try_entries(now)

                self.assertEqual(calls[0]["now"], now)
                self.assertEqual(calls[0]["max_age_sec"], 5.0)
                self.assertEqual(calls[0]["consumed"], [])


if __name__ == "__main__":
    unittest.main()

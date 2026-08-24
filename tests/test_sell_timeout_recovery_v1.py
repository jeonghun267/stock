# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
import unittest
from datetime import datetime, time as day_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_rotation_engine_v2 import Strategy01Engine  # noqa: E402
from strategy_06_crash_low_chase_v1 import Strategy06Engine  # noqa: E402
from strategy_common_hold_sell_v1 import StrategyId  # noqa: E402


class _BrokerTruth:
    def __init__(self, open_sell, available=1):
        self.open_sell = open_sell
        self.available = available
        self.submissions = []
        self.last_error = ""

    def holdings(self, **kwargs):
        self.holdings_kwargs = kwargs
        return {
            "439090": {
                "qty": 1,
                "available": self.available,
                "buy_price": 20300.0,
            }
        }

    def open_orders(self, code, *, buy, **kwargs):
        self.last_query = (code, buy)
        self.open_order_kwargs = kwargs
        return self.open_sell

    def submit(self, **order):
        self.submissions.append(order)
        return "TIMEOUT"


class SellTimeoutRecoveryTests(unittest.TestCase):
    def _engine(self, open_sell, available=1):
        engine = object.__new__(Strategy01Engine)
        engine.config = SimpleNamespace(
            max_sell_retries=3,
            fill_wait_sec=8.0,
            strategy_slug="strategy01",
            force_exit=day_time(15, 10),
            entry_start=day_time(9, 0),
            entry_end=day_time(14, 30),
        )
        engine.broker = _BrokerTruth(open_sell, available)
        engine._last_reconcile_epoch = {}
        engine.state_save_failure_paths = ()
        engine.events = []
        engine._event = lambda kind, **fields: engine.events.append((kind, fields))
        engine._save = lambda: None
        engine._snapshot_point = lambda code, now: None
        engine._known_orders = lambda code, side: []
        engine.state = {
            "date": "20260812",
            "positions": {},
            "recovery_blocked": True,
            "last_error": "SELL_RETRY_EXHAUSTED_MANUAL_CHECK",
        }
        return engine

    @staticmethod
    def _position():
        return {
            "phase": "RECOVERY_BLOCKED",
            "real": True,
            "code": "439090",
            "name": "마녀공장",
            "qty": 1,
            "hold_state": {"sell_latched": True},
            "sell_retries": 3,
            "retry_after_epoch": 0.0,
            "pending": None,
        }

    def test_rearms_sell_only_after_broker_truth_is_clear(self):
        engine = self._engine({})
        position = self._position()
        engine.state["positions"]["439090"] = position

        before = time.time()
        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["sell_retries"], 0)
        self.assertEqual(position["sell_recovery_cycle"], 1)
        self.assertGreaterEqual(position["retry_after_epoch"], before + 7.0)
        self.assertEqual(engine.broker.last_query, ("439090", False))
        self.assertEqual(engine.events[-1][0], "RECOVERY_SELL_REARMED")

    def test_keeps_blocked_when_a_sell_order_is_open(self):
        engine = self._engine({"1234567": 1})
        position = self._position()
        engine.state["positions"]["439090"] = position

        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")
        self.assertEqual(position["sell_retries"], 3)
        self.assertEqual(engine.events[-1][0], "RECOVERY_SELL_REARM_WAIT")

    def test_keeps_blocked_when_open_order_truth_is_unavailable(self):
        engine = self._engine(None)
        position = self._position()
        engine.state["positions"]["439090"] = position

        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")
        self.assertEqual(position["sell_retries"], 3)
        self.assertEqual(engine.events, [])

    def test_keeps_blocked_when_available_quantity_is_zero(self):
        engine = self._engine({}, available=0)
        position = self._position()
        engine.state["positions"]["439090"] = position

        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")
        self.assertEqual(position["sell_retries"], 3)
        self.assertEqual(engine.events[-1][0], "RECOVERY_SELL_REARM_WAIT")

    def test_strategy06_uses_the_same_safe_rearm_contract(self):
        engine = object.__new__(Strategy06Engine)
        engine.config = SimpleNamespace(max_sell_retries=3, fill_wait_sec=8.0)
        engine.broker = _BrokerTruth({})
        engine._last_reconcile_epoch = {}
        engine.state_save_failure_paths = ()
        engine.events = []
        engine._event = lambda kind, **fields: engine.events.append((kind, fields))
        position = self._position()
        position["entry_at"] = "2026-08-12T10:00:00+09:00"
        engine.state = {
            "date": "20260812",
            "positions": {"439090": position},
            "recovery_blocked": True,
            "last_error": "SELL_RETRY_EXHAUSTED_MANUAL_CHECK",
        }

        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["sell_retries"], 0)
        self.assertEqual(position["sell_recovery_cycle"], 1)
        self.assertEqual(engine.events[-1][0], "RECOVERY_SELL_REARMED")

    def test_force_exit_gets_five_finite_extra_attempts(self):
        engine = self._engine({})
        position = self._position()
        position.update({"phase": "HOLD", "sell_recovery_cycle": 2})

        engine._start_sell(
            position,
            datetime(2026, 8, 12, 15, 10),
            "TIME_EXIT_1510",
            None,
        )

        self.assertEqual(len(engine.broker.submissions), 1)
        self.assertEqual(position["sell_retries"], 4)
        self.assertIn("recovery2:4", position["pending"]["idempotency_key"])

        position.update({"phase": "HOLD", "pending": None, "sell_retries": 8})
        engine._start_sell(
            position,
            datetime(2026, 8, 12, 15, 10, 10),
            "TIME_EXIT_1510",
            None,
        )
        self.assertEqual(len(engine.broker.submissions), 1)
        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")
        self.assertEqual(
            engine.state["last_error"],
            "FORCE_EXIT_RETRY_EXHAUSTED_MANUAL_CHECK",
        )

    def test_non_time_exit_stays_blocked_after_normal_limit(self):
        engine = self._engine({})
        position = self._position()
        engine._start_sell(
            position,
            datetime(2026, 8, 12, 10, 30),
            "COMMON_FLOW_DEFENSE_EXIT",
            None,
        )
        self.assertEqual(engine.broker.submissions, [])
        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")

    def test_s02_initial_sell_uses_two_second_query_budget(self):
        engine = self._engine({})
        engine.config.strategy_id = StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
        engine.config.initial_sell_query_budget_sec = 2.0
        engine.config.fills_dir = Path("missing")
        engine._known_orders = Strategy01Engine._known_orders.__get__(engine)
        position = self._position()
        position.update({"phase": "HOLD", "sell_retries": 0})

        engine._start_sell(
            position,
            datetime(2026, 8, 12, 10, 30),
            "S02_PEAK_5_DROP_1P2_FLOW_1OF4_EXIT",
            {"price": 20400},
        )

        self.assertEqual(len(engine.broker.submissions), 1)
        self.assertEqual(engine.broker.holdings_kwargs,
                         {"timeout_sec": 1.0, "attempts": 1})
        self.assertEqual(engine.broker.open_order_kwargs["attempts"], 1)
        self.assertGreater(engine.broker.open_order_kwargs["timeout_sec"], 0)
        self.assertLessEqual(engine.broker.open_order_kwargs["timeout_sec"], 2.0)
        self.assertEqual(position["phase"], "SELL_PENDING")

    def test_rearm_stops_after_three_recovery_cycles(self):
        engine = self._engine({})
        position = self._position()
        position["sell_recovery_cycle"] = 3
        engine.state["positions"]["439090"] = position

        engine._reconcile_blocked(position, datetime.now())

        self.assertEqual(position["phase"], "RECOVERY_BLOCKED")
        self.assertEqual(position["sell_retries"], 3)
        self.assertEqual(
            engine.state["last_error"],
            "SELL_RECOVERY_CYCLES_EXHAUSTED_MANUAL_CHECK",
        )
        self.assertFalse(hasattr(engine.broker, "last_query"))

    def test_exhausted_event_is_cooled_down_for_sixty_seconds(self):
        engine = self._engine({})
        position = self._position()
        with patch(
            "strategy_01_rotation_engine_v2.time.time",
            side_effect=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0,
                         160.0, 170.0, 180.0, 190.0],
        ):
            for _ in range(10):
                engine._start_sell(
                    position,
                    datetime(2026, 8, 12, 10, 30),
                    "COMMON_FLOW_DEFENSE_EXIT",
                    None,
                )
        exhausted = [event for event in engine.events if event[0] == "SELL_RETRY_EXHAUSTED"]
        self.assertEqual(len(exhausted), 2)

    def test_tick_rearms_then_time_exit_uses_fresh_recovery_key(self):
        engine = self._engine({})
        position = self._position()
        engine.state["positions"]["439090"] = position
        engine._active_positions = lambda: {"439090": position}
        engine._cleanup_terminal = lambda: None
        engine._update_post_exit_audit = lambda now: None
        engine._try_entries = lambda now: None

        with patch(
            "strategy_01_rotation_engine_v2.time.time",
            side_effect=[100.0, 100.0, 100.0, 109.0, 109.0, 109.0],
        ):
            engine.tick(datetime(2026, 8, 12, 15, 10, 0))
            engine.tick(datetime(2026, 8, 12, 15, 10, 9))

        self.assertEqual(len(engine.broker.submissions), 1)
        self.assertEqual(position["phase"], "SELL_PENDING")
        self.assertIn("recovery1:1", position["pending"]["idempotency_key"])


if __name__ == "__main__":
    unittest.main()

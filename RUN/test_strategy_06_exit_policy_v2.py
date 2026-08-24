# -*- coding: utf-8 -*-
import unittest
from datetime import time
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_exit_policy_v2 import ExitObservation, decide_exit
import strategy_06_crash_low_chase_v1  # noqa: F401 - validates production wiring import


def observation(**overrides):
    values = dict(
        price=101.0,
        entry_price=100.0,
        anchor_low=97.0,
        peak_price=101.0,
        atr_3m_pct=0.5,
        ma5=100.5,
        ma5_prev=100.0,
        ma10=99.5,
        ma20=99.0,
        ma20_prev=98.8,
        buy_rate_10s=200.0,
        sell_rate_10s=100.0,
        buy_side_alive=True,
        buy_ratio_10s=0.67,
        observed_time=time(10, 0),
        same_day=True,
    )
    values.update(overrides)
    return ExitObservation(**values)


class Strategy06ExitPolicyTests(unittest.TestCase):
    def test_production_entry_band_matches_approved_contract(self):
        config = strategy_06_crash_low_chase_v1.Config()
        self.assertEqual(
            (config.rebound_pct, config.entry_floor_pct, config.chase_cap_pct),
            (1.5, 1.0, 2.0),
        )

    def test_five_percent_is_not_fixed_take_profit(self):
        decision = decide_exit(observation(price=105.0, peak_price=105.0))
        self.assertEqual((decision.action, decision.reason), ("HOLD", "NO_EXIT"))

    def test_rising_hold_can_pass_1510(self):
        decision = decide_exit(observation(observed_time=time(15, 10)))
        self.assertEqual((decision.action, decision.reason), ("HOLD", "NO_EXIT"))

    def test_1520_is_unconditional_flat(self):
        decision = decide_exit(observation(observed_time=time(15, 20)))
        self.assertEqual((decision.action, decision.reason), ("SELL", "HARD_FLAT_1520"))

    def test_legacy_overnight_is_flattened(self):
        decision = decide_exit(observation(same_day=False, observed_time=time(9, 0)))
        self.assertEqual(
            (decision.action, decision.reason),
            ("SELL", "LEGACY_OVERNIGHT_FLAT_0900"),
        )

    def test_1510_hold_requires_full_ma_stack(self):
        decision = decide_exit(observation(observed_time=time(15, 10), ma20=100.0))
        self.assertEqual(
            (decision.action, decision.reason),
            ("SELL", "CLOSE_PROTECT_1510"),
        )

    def test_hard_stop_has_priority(self):
        decision = decide_exit(observation(price=98.0, observed_time=time(9, 5)))
        self.assertEqual((decision.action, decision.reason), ("SELL", "HARD_STOP_2"))

    def test_production_engine_flattens_legacy_overnight_at_open(self):
        engine = object.__new__(strategy_06_crash_low_chase_v1.Strategy06Engine)
        engine.config = SimpleNamespace(morning_sell_start=time(9, 0))
        point = {
            "price": 99.0,
            "ts": datetime(2026, 8, 24, 9, 2, tzinfo=ZoneInfo("Asia/Seoul")),
        }
        engine._snapshot_point = lambda *_args: point
        engine._update_excursion = lambda *_args: None
        calls = []
        engine._start_sell = lambda _p, _n, reason, _point: calls.append(reason)
        position = {
            "code": "310210", "entry_price": 100.0, "entry_day": "20260820",
            "last_price": 100.0, "retry_after_epoch": 0,
        }
        engine._evaluate_exit(position, point["ts"])
        self.assertEqual(calls, ["LEGACY_OVERNIGHT_FLAT_0900"])


if __name__ == "__main__":
    unittest.main()

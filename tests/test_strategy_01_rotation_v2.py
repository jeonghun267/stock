# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import timedelta, time as day_time
from pathlib import Path

from strategy_01_rotation_engine_v2 import (
    Config,
    Strategy01Engine,
    kst_now,
)


class FakeSlots:
    def __init__(self) -> None:
        self.owned: set[str] = set()
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, code: str, _strategy: str, _day: str) -> bool:
        self.acquire_calls += 1
        if code in self.owned or len(self.owned) >= 6:
            return False
        self.owned.add(code)
        return True

    def release(self, code: str, _day: str) -> None:
        self.release_calls += 1
        self.owned.discard(code)


class FakeBroker:
    def __init__(self, *, real: bool = False, status: str = "SHADOW") -> None:
        self.real_session = real
        self.buy_allowed = real
        self.mode = "LIVE" if real else "SHADOW"
        self.status = status
        self.last_error = ""
        self.submissions: list[dict] = []
        self.balance: dict = {}
        self.opens: dict[tuple[str, bool], dict[str, int]] = {}

    def connect(self) -> bool:
        return True

    def holdings(self):
        return json.loads(json.dumps(self.balance))

    def open_orders(self, code: str, *, buy: bool):
        return dict(self.opens.get((code, buy), {}))

    def submit(self, **kwargs):
        self.submissions.append(dict(kwargs))
        return self.status

    def cancel(self, **_kwargs):
        return "OK"


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("strategy01-rotation-v2-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


class Strategy01RotationV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = kst_now().replace(hour=9, minute=1, second=0, microsecond=0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, *, capital: int = 2_000_000, live: bool = False) -> Config:
        return Config(
            signal_path=self.root / "signal.json",
            snapshot_path=self.root / "snapshot.json",
            board_path=self.root / "board.json",
            bars_path=self.root / "bars.json",
            names_path=self.root / "names.json",
            state_path=self.root / "state.json",
            fills_dir=self.root / "fills",
            event_dir=self.root / "events",
            log_path=self.root / "engine.log",
            approval_path=self.root / "approved.flag",
            off_flag_path=self.root / "off.flag",
            manual_buy_block_path=self.root / "manual.flag",
            lock_path=self.root / "engine.lock",
            live_requested=live,
            quantity=1,
            max_slots=6,
            max_daily_codes=6,
            max_cycles_per_code=2,
            rotation_capital_krw=capital,
            signal_max_age_sec=60,
            snapshot_max_age_sec=60,
            board_max_age_sec=60,
            fill_wait_sec=1000,
            entry_start=day_time(0, 0),
            entry_end=day_time(23, 59, 59),
            force_exit=day_time(23, 59, 59),
            process_end=day_time(23, 59, 59),
        )

    def write_market(
        self,
        codes: list[str],
        prices: dict[str, float],
        observed_at,
        *,
        sequences: dict[str, list[int]] | None = None,
    ) -> None:
        rows = []
        sequences = sequences or {code: [1] for code in codes}
        for rank, code in enumerate(codes):
            for sequence in sequences.get(code, [1]):
                rows.append({
                    "ts": observed_at.isoformat(timespec="seconds"),
                    "code": code,
                    "name": f"TEST-{code}",
                    "action": "BUY_READY",
                    "reason": "OPEN_SURGE_CONFIRMED",
                    "mode": "SIGNAL_ONLY_ORDER_ZERO",
                    "signal_sequence": sequence,
                    "money_speed_5s": 10_000_000 - rank,
                    "buy_ratio": 0.75,
                    "theme_bonus": 0,
                })
        signal = {
            "schema": "strategy_01_open_surge_signal_v2",
            "date": observed_at.strftime("%Y%m%d"),
            "updated_at": observed_at.isoformat(timespec="seconds"),
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "signals": rows,
        }
        snapshot = {
            "codes": {
                code: {
                    "ts": observed_at.isoformat(timespec="seconds"),
                    "cur": prices[code],
                    "cum_vol": 100_000,
                    "buy_money_cum": 700_000_000,
                    "sell_money_cum": 300_000_000,
                }
                for code in codes
            }
        }
        board = {
            "ts": observed_at.isoformat(timespec="seconds"),
            "all_items": [{
                "code": code,
                "money_speed_5s": 2_000_000,
                "money_speed_10s": 1_800_000,
                "money_speed_30s": 1_500_000,
            } for code in codes],
        }
        self.config().signal_path.write_text(
            json.dumps(signal, ensure_ascii=False), encoding="utf-8")
        self.config().snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        self.config().board_path.write_text(
            json.dumps(board, ensure_ascii=False), encoding="utf-8")
        self.config().bars_path.write_text("{}", encoding="utf-8")
        self.config().names_path.write_text("{}", encoding="utf-8")

    def engine(self, config: Config, broker: FakeBroker | None = None):
        broker = broker or FakeBroker()
        return (
            Strategy01Engine(
                config, broker=broker, slots=FakeSlots(), logger=quiet_logger()),
            broker,
        )

    def test_six_slots_fill_and_seventh_waits(self) -> None:
        codes = [f"10{index:04d}" for index in range(7)]
        self.write_market(codes, {code: 10_000 for code in codes}, self.now)
        engine, broker = self.engine(self.config())

        engine.tick(self.now)

        self.assertEqual(len(engine._active_positions()), 6)
        self.assertEqual(engine.state["order_attempts_total"], 6)
        self.assertEqual(len(broker.submissions), 6)
        self.assertEqual(
            len(set(codes) - set(engine._active_positions())),
            1,
        )

    def test_sell_releases_slot_and_capital_for_waiting_code(self) -> None:
        codes = ["200001", "200002"]
        prices = {code: 3_000_000 for code in codes}
        self.write_market(codes, prices, self.now)
        engine, broker = self.engine(self.config(capital=5_000_000))
        engine.tick(self.now)
        self.assertEqual(len(engine._active_positions()), 1)
        first = next(iter(engine._active_positions()))
        waiting = next(code for code in codes if code != first)

        engine._confirm_exit(
            engine._active_positions()[first],
            prices[first],
            "TEST_ROTATION",
            shadow=True,
        )
        later = self.now + timedelta(seconds=1)
        engine.tick(later)

        self.assertEqual(set(engine._active_positions()), {waiting})
        self.assertEqual(engine.state["cycles_by_code"][first], 1)
        self.assertEqual(engine.state["order_attempts_total"], 2)
        self.assertEqual(len(broker.submissions), 2)

    def test_same_code_never_has_two_active_orders(self) -> None:
        code = "300001"
        self.write_market(
            [code],
            {code: 10_000},
            self.now,
            sequences={code: [1, 2]},
        )
        engine, broker = self.engine(self.config())

        engine.tick(self.now)

        self.assertEqual(len(engine._active_positions()), 1)
        self.assertEqual(engine.state["order_attempts_total"], 1)
        self.assertEqual(len(broker.submissions), 1)

        first = engine._active_positions()[code]
        engine._confirm_exit(first, 10_000, "TEST_FIRST_EXIT", shadow=True)
        engine.tick(self.now + timedelta(seconds=1))

        self.assertEqual(len(engine._active_positions()), 1)
        self.assertEqual(engine.state["order_attempts_total"], 2)
        self.assertEqual(len(broker.submissions), 2)

    def test_completed_cycle_limit_is_two_per_code(self) -> None:
        code = "400001"
        self.write_market(
            [code],
            {code: 10_000},
            self.now,
            sequences={code: [3]},
        )
        engine, broker = self.engine(self.config())
        engine.state["cycles_by_code"][code] = 2
        engine.state["entered_codes"] = [code]

        engine.tick(self.now)

        self.assertEqual(engine._active_positions(), {})
        self.assertEqual(engine.state["order_attempts_total"], 0)
        self.assertEqual(broker.submissions, [])

    def test_seventh_distinct_code_is_blocked_after_six_rotations(self) -> None:
        codes = [f"41{index:04d}" for index in range(7)]
        prices = {code: 10_000 for code in codes}
        self.write_market(codes, prices, self.now)
        engine, broker = self.engine(self.config(capital=10_000))

        for second in range(6):
            engine.tick(self.now + timedelta(seconds=second))
            active = engine._active_positions()
            self.assertEqual(len(active), 1)
            code = next(iter(active))
            engine._confirm_exit(
                active[code],
                prices[code],
                "TEST_ROTATION",
                shadow=True,
            )

        engine.tick(self.now + timedelta(seconds=6))

        self.assertEqual(engine._active_positions(), {})
        self.assertEqual(len(engine.state["entered_codes"]), 6)
        self.assertEqual(len(broker.submissions), 6)

    def test_timeout_blocks_replay_and_reconciles_without_duplicate(self) -> None:
        code = "500001"
        self.write_market([code], {code: 10_000}, self.now)
        broker = FakeBroker(real=True, status="TIMEOUT")
        engine, _ = self.engine(self.config(live=True), broker)

        engine.tick(self.now)
        self.assertTrue(engine.state["recovery_blocked"])
        self.assertEqual(len(broker.submissions), 1)

        engine.tick(self.now + timedelta(seconds=1))
        self.assertFalse(engine.state["recovery_blocked"])
        self.assertEqual(len(broker.submissions), 1)
        self.assertEqual(engine._active_positions(), {})
        self.assertEqual(engine.state["history"][-1]["phase"], "FAILED")


    def test_trade_audit_records_rank_excursions_and_post_exit(self) -> None:
        codes = ["600001", "600002"]
        prices = {code: 10_000 for code in codes}
        self.write_market(codes, prices, self.now)
        engine, _ = self.engine(self.config())

        engine.tick(self.now)
        position = engine._active_positions()[codes[0]]
        self.assertEqual(position["candidate_rank_at_entry"], 1)
        self.assertEqual(position["candidate_count_at_entry"], 2)
        engine._update_excursion(
            position, 10_500, self.now + timedelta(seconds=1),
        )
        engine._update_excursion(
            position, 9_800, self.now + timedelta(seconds=2),
        )
        self.assertAlmostEqual(position["mfe_pct"], 5.0)
        self.assertAlmostEqual(position["mae_pct"], -2.0)

        engine._confirm_exit(
            position, 10_000, "TEST_AUDIT_EXIT", shadow=True,
        )
        position["exit_at"] = self.now.isoformat(timespec="seconds")
        engine._cleanup_terminal()
        archived = engine.state["history"][-1]

        checkpoints = [
            (15, 10_500),
            (30, 9_700),
            (60, 11_000),
        ]
        for minutes, price in checkpoints:
            observed_at = self.now + timedelta(minutes=minutes)
            later_prices = {code: (price if code == codes[0] else 10_000) for code in codes}
            self.write_market(codes, later_prices, observed_at)
            engine._update_post_exit_audit(observed_at)

        targets = archived["post_exit_audit"]["targets"]
        self.assertEqual(set(targets), {"15", "30", "60"})
        self.assertAlmostEqual(targets["15"]["return_from_exit_pct"], 5.0)
        self.assertAlmostEqual(targets["30"]["return_from_exit_pct"], -3.0)
        self.assertAlmostEqual(targets["60"]["return_from_exit_pct"], 10.0)
        self.assertAlmostEqual(targets["60"]["return_from_entry_pct"], 10.0)

        event_file = next(engine.config.event_dir.glob("*.csv"))
        text = event_file.read_text(encoding="utf-8-sig")
        self.assertIn("rank=1/2", text)
        self.assertIn("mfe=5.000% mae=-2.000%", text)

if __name__ == "__main__":
    unittest.main()

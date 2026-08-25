# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import logging
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta, time as day_time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_rotation_engine_v2 import (
    Config,
    Strategy01Engine,
    kst_now,
)
from strategy_common_hold_sell_v1 import STRATEGY_PROFILES, StrategyId
from hold_sell_audit_v1 import load_verified_post_exit_rows


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

    def config(self, *, capital: int = 2_000_000, live: bool = False, quantity: int = 1) -> Config:
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
            audit_root=self.root / "audit",
            order_lifecycle_root=self.root / "order_lifecycle",
            reentry_audit_root=self.root / "reentry_audit",
            reentry_peer_state_paths=(),
            audit_enabled=False,
            approval_path=self.root / "approved.flag",
            off_flag_path=self.root / "off.flag",
            manual_buy_block_path=self.root / "manual.flag",
            lock_path=self.root / "engine.lock",
            live_requested=live,
            quantity=quantity,
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
        stages: dict[str, list[str]] | None = None,
    ) -> None:
        rows = []
        sequences = sequences or {code: [1] for code in codes}
        stages = stages or {}
        for rank, code in enumerate(codes):
            for index, sequence in enumerate(sequences.get(code, [1])):
                row = {
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
                }
                if index < len(stages.get(code, [])):
                    row["entry_stage"] = stages[code][index]
                    row["requested_quantity"] = 1
                rows.append(row)
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

    def write_ma3_seed(self, codes: list[str], price: float) -> None:
        start = (self.now - timedelta(days=1)).replace(
            hour=13, minute=50, second=0)
        labels = [
            (start + timedelta(minutes=index)).strftime("%Y%m%d%H%M")
            for index in range(70)
        ]
        payload = {
            "ts": self.now.isoformat(timespec="seconds"),
            "hm": self.now.strftime("%H%M"),
            "m": {code: {"prev": [[price] * 4 for _ in labels],
                         "pm": labels, "c": price} for code in codes},
        }
        self.config().bars_path.write_text(
            json.dumps(payload), encoding="utf-8")

    def engine(self, config: Config, broker: FakeBroker | None = None):
        if broker is None:
            broker = FakeBroker()
            broker.buy_allowed = True
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

    def test_two_share_setting_submits_and_records_two_shares(self) -> None:
        code = "100099"
        self.write_market([code], {code: 10_000}, self.now)
        engine, broker = self.engine(self.config(quantity=2))

        engine.tick(self.now)

        self.assertEqual(broker.submissions[0]["quantity"], 2)
        self.assertEqual(engine._active_positions()[code]["qty"], 2)

    def test_rocket_forces_exactly_one_share(self) -> None:
        code = "100096"
        self.write_market([code], {code: 10_000}, self.now, stages={code: ["ROCKET"]})
        engine, broker = self.engine(self.config(quantity=2))
        engine.tick(self.now)
        self.assertEqual(broker.submissions[0]["quantity"], 1)
        self.assertEqual(engine._active_positions()[code]["qty"], 1)

    def test_staged_signals_buy_one_share_then_add_one_share(self) -> None:
        code = "100097"
        engine, broker = self.engine(self.config(quantity=2))
        self.write_market(
            [code], {code: 10_000}, self.now,
            stages={code: ["EARLY_FLOW"]},
        )
        engine.tick(self.now)
        self.assertEqual(engine._active_positions()[code]["qty"], 1)

        later = self.now + timedelta(seconds=1)
        self.write_market(
            [code], {code: 10_100}, later,
            sequences={code: [2]},
            stages={code: ["STRONG_FLOW"]},
        )
        engine.tick(later)

        position = engine._active_positions()[code]
        self.assertEqual(
            [row["quantity"] for row in broker.submissions], [1, 1])
        self.assertEqual(position["qty"], 2)
        self.assertEqual(
            position["entry_stages"], ["EARLY_FLOW", "STRONG_FLOW"])
        self.assertAlmostEqual(position["entry_price"], 10_050)


    def test_two_share_partial_exit_banks_one_and_keeps_runner(self) -> None:
        code = "100098"
        self.write_market([code], {code: 10_000}, self.now)
        engine, _ = self.engine(self.config(quantity=2))
        engine.tick(self.now)
        position = engine._active_positions()[code]
        point = engine._snapshot_point(code, self.now)
        engine._start_sell(
            position, self.now, "S01_PEAK_FLOW_PARTIAL", point,
            quantity_override=1, partial=True,
        )
        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["qty"], 1)
        self.assertTrue(position["hold_state"]["peak_partial_taken"])
        self.assertEqual(position["partial_exits"][0]["quantity"], 1)
        self.assertEqual(engine.state["cycles_by_code"].get(code, 0), 0)

        engine._start_sell(position, self.now, "FINAL_EXIT", point)
        self.assertEqual(position["phase"], "CLOSED")
        self.assertEqual(position["qty"], 0)
        self.assertEqual(engine.state["cycles_by_code"][code], 1)

    def test_sell_releases_slot_and_capital_for_waiting_code(self) -> None:

        codes = ["200001", "200002"]
        prices = {code: 1_500_000 for code in codes}
        self.write_market(codes, prices, self.now)
        engine, broker = self.engine(self.config(capital=2_000_000))
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
        self.write_ma3_seed([code], 10_000)
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

    def test_real_buy_is_blocked_when_ma3_seed_is_missing(self) -> None:
        code = "500002"
        self.write_market([code], {code: 10_000}, self.now)
        broker = FakeBroker(real=True, status="OK")
        engine, _ = self.engine(self.config(live=True), broker)

        with patch("strategy_01_rotation_engine_v2.ma3_request_missing_history") as request:

            engine.tick(self.now)


        self.assertEqual(broker.submissions, [])

        self.assertEqual(engine.state["last_error"], "MA3_SEED_NOT_READY:500002")

        request.assert_called_once()

        self.assertEqual(request.call_args.args[0], code)

    def test_s01_ma_support_needs_buy_side_rate(self) -> None:
        code = "500003"
        self.write_market([code], {code: 10_000}, self.now)
        self.write_ma3_seed([code], 10_000)
        engine, _ = self.engine(self.config())

        point = engine._snapshot_point(code, self.now)
        self.assertIsNotNone(point)
        observation = engine._build_observation(
            {"code": code, "real": True}, point,
        )

        self.assertFalse(observation.daily_ma_permit)
        self.assertFalse(observation.common_peak_flow_ready)
        self.assertFalse(observation.price_above_ma5)
        self.assertEqual(observation.ma5_value, Decimal("10000"))
        self.assertEqual(observation.ma5_prev_value, Decimal("10000"))
        self.assertEqual(observation.ma10_value, Decimal("10000"))
        self.assertEqual(observation.ma3_source, "live")
        profile = STRATEGY_PROFILES[StrategyId.S01_OPEN_SURGE]
        self.assertTrue(profile.common_peak_flow_exit_enabled)
        self.assertFalse(profile.profit_trail_enabled)
        self.assertTrue(profile.trail_needs_sell_pressure)

    def test_missing_real_flag_is_recovery_blocked(self) -> None:
        config = self.config(live=True)
        config.state_path.write_text(
            json.dumps({
                "schema": config.state_schema,
                "date": self.now.strftime("%Y%m%d"),
                "order_attempts_total": 0,
                "consumed_signals": [],
                "positions": {
                    "000001": {
                        "code": "000001",
                        "name": "LEGACY",
                        "phase": "HOLD",
                        "qty": 1,
                        "entry_price": 10_000,
                        "entry_at": self.now.isoformat(),
                    },
                },
                "cycles_by_code": {},
                "entered_codes": [],
                "history": [],
                "recovery_blocked": False,
                "last_error": "",
            }),
            encoding="utf-8",
        )

        engine, broker = self.engine(config, FakeBroker(real=True))

        self.assertTrue(engine.state["recovery_blocked"])
        self.assertEqual(
            engine.state["positions"]["000001"]["phase"],
            "RECOVERY_BLOCKED",
        )
        self.assertEqual(
            engine.state["last_error"],
            "POSITION_REAL_FLAG_MISSING_MANUAL_CHECK:000001",
        )
        engine.tick(self.now)
        self.assertEqual(broker.submissions, [])


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

    def test_post_exit_observation_capture_is_order_zero_and_hash_verified(self) -> None:
        code = "600003"
        self.write_market([code], {code: 10_000}, self.now)
        config = replace(self.config(), audit_enabled=True)
        engine, broker = self.engine(config)
        engine.tick(self.now)
        position = engine._active_positions()[code]
        submissions_before_capture = len(broker.submissions)

        engine._confirm_exit(position, 10_000, "TEST_CAPTURE", shadow=True)
        exit_at = engine.state["positions"][code]["exit_at"]
        engine._cleanup_terminal()
        observed_at = kst_now() + timedelta(seconds=1)
        self.write_market([code], {code: 10_100}, observed_at)
        engine._update_post_exit_audit(observed_at)

        archived = engine.state["history"][-1]
        capture = archived["post_exit_audit"]["observation_capture"]
        self.assertEqual(capture["rows"], 1)
        rows = load_verified_post_exit_rows(Path(capture["path"]))
        self.assertEqual(rows[0]["code"], code)
        self.assertEqual(rows[0]["exit_at"], exit_at)
        self.assertEqual(rows[0]["observation"]["price"], "10100.0")
        self.assertEqual(len(broker.submissions), submissions_before_capture)

    def test_order_lifecycle_links_signal_to_order_zero_fill(self) -> None:
        code = "600004"
        self.write_market([code], {code: 10_000}, self.now)
        engine, _ = self.engine(self.config())

        engine.tick(self.now)

        audit_file = next(
            engine.config.order_lifecycle_root.glob(
                "*/s01_order_lifecycle.jsonl"
            )
        )
        rows = [
            json.loads(line)
            for line in audit_file.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [row["event"] for row in rows],
            ["BUY_PREPARED", "BUY_SUBMIT_RESULT", "BUY_FILL_CONFIRMED"],
        )
        self.assertEqual(len({row["signal_id"] for row in rows}), 1)
        self.assertTrue(rows[0]["signal_id"])
        self.assertEqual(len({row["idempotency_key"] for row in rows}), 1)
        fill = rows[-1]
        self.assertEqual(fill["requested_quantity"], 1)
        self.assertEqual(fill["fill_quantity"], 1)
        self.assertEqual(fill["fill_price"], 10_000)
        self.assertEqual(fill["fill_source"], "ORDER_ZERO")
        self.assertTrue(fill["fill_reconciled_at"])
        self.assertEqual(fill["signal_snapshot"]["code"], code)
        self.assertEqual(
            set(fill["production_files"]),
            {"engine", "signal_contract", "signal_source", "order_adapter"},
        )
        for row in rows:
            payload = dict(row)
            claimed = payload.pop("record_sha256")
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), default=str,
            )
            self.assertEqual(
                claimed,
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            )

if __name__ == "__main__":
    unittest.main()

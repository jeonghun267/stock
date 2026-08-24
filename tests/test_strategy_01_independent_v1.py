# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, time as day_time
from decimal import Decimal
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_01_open_surge_engine_v1 import (
    Config,
    KST,
    STATE_SCHEMA,
    Strategy01Engine,
    kst_now,
)
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)
from strategy_common_order_v1 import StrategyBroker


class FakeSlots:
    def __init__(self) -> None:
        self.owned: set[str] = set()
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, code: str, _strategy: str, _day: str) -> bool:
        self.acquire_calls += 1
        if code in self.owned:
            return False
        self.owned.add(code)
        return True

    def release(self, code: str, _day: str) -> None:
        self.release_calls += 1
        self.owned.discard(code)


class FakeBroker:
    def __init__(self, *, real: bool, submit_status: str = "SHADOW") -> None:
        self.real_session = real
        self.buy_allowed = real
        self.mode = "LIVE" if real else "SHADOW"
        self.submit_status = submit_status
        self.last_error = ""
        self.submissions: list[dict] = []
        self.cancellations: list[dict] = []
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
        return self.submit_status

    def cancel(self, **kwargs):
        self.cancellations.append(dict(kwargs))
        return "OK"


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("strategy01-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


class IndependentStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = kst_now().replace(microsecond=0)
        self.code = "123456"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, *, live: bool = False, fill_wait: float = 1000) -> Config:
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
            max_order_attempts=1,
            fill_wait_sec=fill_wait,
            entry_start=day_time(0, 0),
            entry_end=day_time(23, 59, 59),
            force_exit=day_time(23, 59, 59),
            process_end=day_time(23, 59, 59),
        )

    def write_inputs(self, price: float = 10_000, *, seconds: int = 0) -> None:
        observed = self.now + timedelta(seconds=seconds)
        signal = {
            "schema": "strategy_01_open_surge_signal_v1",
            "date": observed.strftime("%Y%m%d"),
            "updated_at": observed.isoformat(timespec="seconds"),
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "signals": [{
                "ts": observed.isoformat(timespec="seconds"),
                "code": self.code,
                "name": "테스트",
                "action": "BUY_READY",
                "reason": "OPEN_SURGE_CONFIRMED",
                "mode": "SIGNAL_ONLY_ORDER_ZERO",
                "money_speed_5s": 2_000_000,
                "buy_ratio": 0.75,
                "theme_bonus": 0,
            }],
        }
        snapshot = {
            "codes": {
                self.code: {
                    "ts": observed.isoformat(timespec="seconds"),
                    "cur": price,
                    "cum_vol": 100_000,
                    "buy_money_cum": 700_000_000,
                    "sell_money_cum": 300_000_000,
                }
            }
        }
        board = {
            "ts": observed.isoformat(timespec="seconds"),
            "all_items": [{
                "code": self.code,
                "money_speed_5s": 2_000_000,
                "money_speed_10s": 1_800_000,
                "money_speed_30s": 1_500_000,
            }],
        }
        self.config().signal_path.write_text(
            json.dumps(signal, ensure_ascii=False), encoding="utf-8")
        self.config().snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        self.config().board_path.write_text(
            json.dumps(board, ensure_ascii=False), encoding="utf-8")
        self.config().bars_path.write_text("{}", encoding="utf-8")
        self.config().names_path.write_text("{}", encoding="utf-8")

    def test_shadow_entry_is_one_share_and_common_exit_closes(self) -> None:
        self.write_inputs()
        broker = FakeBroker(real=False)
        slots = FakeSlots()
        engine = Strategy01Engine(
            self.config(), broker=broker, slots=slots, logger=quiet_logger())
        engine.tick(self.now)
        position = engine.state["position"]
        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["qty"], 1)
        self.assertEqual(
            position["hold_state"]["strategy_id"], "S01_OPEN_SURGE")
        self.assertEqual(engine.state["order_attempts"], 1)
        self.assertEqual(len(broker.submissions), 1)
        self.assertEqual(slots.acquire_calls, 0)

        self.write_inputs(price=9_800, seconds=1)
        engine.tick(self.now + timedelta(seconds=1))
        self.assertEqual(engine.state["position"]["phase"], "CLOSED")
        self.assertEqual(len(broker.submissions), 1)

    def test_timeout_stays_pending_and_never_submits_buy_twice(self) -> None:
        self.write_inputs()
        broker = FakeBroker(real=True, submit_status="TIMEOUT")
        slots = FakeSlots()
        engine = Strategy01Engine(
            self.config(live=True), broker=broker, slots=slots,
            logger=quiet_logger())
        engine.tick(self.now)
        engine.tick(self.now + timedelta(seconds=1))
        self.assertEqual(engine.state["position"]["phase"], "BUY_PENDING")
        self.assertEqual(engine.state["order_attempts"], 1)
        self.assertEqual(len(broker.submissions), 1)
        self.assertEqual(slots.acquire_calls, 1)

    def test_exact_order_fill_confirms_without_second_buy(self) -> None:
        self.write_inputs()
        broker = FakeBroker(real=True, submit_status="OK")
        slots = FakeSlots()
        config = self.config(live=True)
        engine = Strategy01Engine(
            config, broker=broker, slots=slots, logger=quiet_logger())
        engine.tick(self.now)
        config.fills_dir.mkdir(parents=True)
        fill_path = config.fills_dir / f"fills_{self.now:%Y%m%d}.csv"
        with fill_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "ts", "code", "order_no", "state", "otype",
                "fill_qty", "fill_px", "remain",
            ])
            writer.writeheader()
            writer.writerow({
                "ts": self.now.isoformat(timespec="seconds"),
                "code": self.code,
                "order_no": "900001",
                "state": "체결",
                "otype": "매수",
                "fill_qty": "1",
                "fill_px": "10010",
                "remain": "0",
            })
        engine.tick(self.now + timedelta(seconds=1))
        self.assertEqual(engine.state["position"]["phase"], "HOLD")
        self.assertEqual(engine.state["position"]["entry_price"], 10010)
        self.assertEqual(len(broker.submissions), 1)

    def test_restart_keeps_attempt_count_and_does_not_duplicate(self) -> None:
        self.write_inputs()
        broker = FakeBroker(real=False)
        config = self.config()
        engine = Strategy01Engine(
            config, broker=broker, slots=FakeSlots(), logger=quiet_logger())
        engine.tick(self.now)
        restarted_broker = FakeBroker(real=False)
        restarted = Strategy01Engine(
            config, broker=restarted_broker, slots=FakeSlots(),
            logger=quiet_logger())
        restarted.tick(self.now + timedelta(seconds=1))
        self.assertEqual(restarted.state["order_attempts"], 1)
        self.assertEqual(restarted_broker.submissions, [])

    def test_common_engine_hard_stop_is_preserved(self) -> None:
        state = HoldSellState(
            position_id="test",
            strategy_id=StrategyId.S01_OPEN_SURGE,
            code=self.code,
            quantity=1,
            entry_price=Decimal("10000"),
            entry_at=self.now,
        )
        decision = UnifiedHoldSellEngine().evaluate(
            state,
            HoldSellObservation(
                observed_at=self.now + timedelta(seconds=1),
                price=Decimal("9800"),
            ),
        )
        self.assertTrue(decision.should_sell)
        self.assertTrue(decision.reason.startswith("HARD_STOP"))

    def test_live_adapter_off_flag_blocks_buy_but_keeps_exit_session(self) -> None:
        config = self.config(live=True)
        config.approval_path.write_text(
            f"APPROVED_BY_OWNER {datetime.now():%Y%m%d %H:%M:%S}\n",
            encoding="ascii")
        config.off_flag_path.write_text("OFF", encoding="ascii")
        adapter = StrategyBroker(
            live_requested=True,
            approval_path=config.approval_path,
            off_flag_path=config.off_flag_path,
            manual_buy_block_path=config.manual_buy_block_path,
            logger=quiet_logger(),
        )
        self.assertTrue(adapter.real_session)
        self.assertFalse(adapter.buy_allowed)
        self.assertEqual(
            adapter.submit(
                side="BUY", code=self.code, quantity=1,
                idempotency_key="test-key"),
            "BLOCKED",
        )

    def test_independent_files_have_no_retired_engine_dependency(self) -> None:
        names = [
            "strategy_01_open_surge_engine_v1.py",
            "strategy_01_open_surge_buy_v1.py",
            "strategy_01_open_surge_signal_v1.py",
            "strategy_01_signal_contract_v1.py",
            "strategy_common_foundation_v1.py",
            "strategy_common_hold_sell_v1.py",
            "strategy_common_order_v1.py",
        ]
        for name in names:
            source = Path(__file__).parent / name
            if not source.exists():
                source = Path(__file__).parent.parent / "RUN" / name
            text = source.read_text(encoding="utf-8").lower()
            self.assertNotIn("captain2", text, name)


if __name__ == "__main__":
    unittest.main()

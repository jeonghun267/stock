# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "RUN"))

from captain2_common_foundation_v1 import (  # noqa: E402
    BrokerOrderStatus,
    ContractError,
    CostRates,
    DryRunOrderPort,
    FillReport,
    FreshnessPolicy,
    InMemoryEventSink,
    JsonStateStore,
    KST,
    MarketSnapshot,
    OrderIntent,
    OrderLedger,
    OrderSide,
    OrderStatus,
    Position,
    SafetyGate,
    TradingSession,
    as_kst,
    calculate_net_pnl,
)


class Captain2CommonFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.off_flag = Path(self.tempdir.name) / "captain2_off.flag"
        self.now = datetime(2026, 7, 27, 9, 5, tzinfo=KST)
        self.session = TradingSession(time(9, 0), time(15, 30))
        self.freshness = FreshnessPolicy(timedelta(seconds=3))
        self.gate = SafetyGate(self.off_flag, self.session, self.freshness)

    def tearDown(self):
        self.tempdir.cleanup()

    def market(self, code="000001", price="100000", age_seconds=0):
        value = Decimal(price)
        return MarketSnapshot(
            code=code,
            observed_at=self.now - timedelta(seconds=age_seconds),
            price=value,
            bid_price=value - 1,
            ask_price=value + 1,
            source="UNIT_TEST",
        )

    def intent(
        self,
        key="key-1",
        code="000001",
        side=OrderSide.BUY,
        quantity=1,
        price="100000",
    ):
        return OrderIntent(
            idempotency_key=key,
            strategy_id="TEST",
            signal_id="signal-1",
            code=code,
            side=side,
            quantity=quantity,
            reservation_price=Decimal(price),
            created_at=self.now,
        )

    def fill(self, key, execution_id, quantity, price="100000"):
        return FillReport(
            execution_id=execution_id,
            idempotency_key=key,
            quantity=quantity,
            price=Decimal(price),
            filled_at=self.now,
        )

    def test_kst_and_trading_session_contract(self):
        utc_value = datetime(2026, 7, 27, 0, 5, tzinfo=timezone.utc)
        self.assertEqual(as_kst(utc_value), self.now)
        self.assertTrue(self.session.contains(self.now))
        self.assertFalse(self.session.contains(
            datetime(2026, 7, 27, 8, 59, 59, tzinfo=KST)
        ))
        with self.assertRaises(ContractError):
            as_kst(datetime(2026, 7, 27, 9, 5))

    def test_stale_market_data_is_blocked(self):
        decision = self.gate.check_buy(
            self.intent(),
            self.market(age_seconds=4),
            OrderLedger(),
            set(),
            self.now,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "STALE_DATA")

    def test_off_flag_blocks_new_buy(self):
        self.off_flag.write_text("OFF\n", encoding="utf-8")
        decision = self.gate.check_buy(
            self.intent(),
            self.market(),
            OrderLedger(),
            set(),
            self.now,
        )
        self.assertEqual(decision.reason, "CAPTAIN2_OFF_FLAG")

    def test_duplicate_idempotency_and_code_are_blocked(self):
        ledger = OrderLedger()
        ledger.submit(self.intent())
        same_key = self.gate.check_buy(
            self.intent(),
            self.market(),
            ledger,
            set(),
            self.now,
        )
        same_code = self.gate.check_buy(
            self.intent(key="key-2"),
            self.market(),
            ledger,
            set(),
            self.now,
        )
        self.assertEqual(same_key.reason, "DUPLICATE_IDEMPOTENCY_KEY")
        self.assertEqual(same_code.reason, "DUPLICATE_CODE")

    def test_buy_quantity_must_be_exactly_one(self):
        decision = self.gate.check_buy(
            self.intent(quantity=2),
            self.market(),
            OrderLedger(),
            set(),
            self.now,
        )
        self.assertEqual(decision.reason, "BUY_QUANTITY_MUST_BE_ONE")

    def test_six_slot_boundary(self):
        occupied = {f"{index:06d}" for index in range(1, 7)}
        decision = self.gate.check_buy(
            self.intent(code="000007"),
            self.market(code="000007"),
            OrderLedger(),
            occupied,
            self.now,
        )
        self.assertEqual(decision.reason, "SLOT_LIMIT")

    def test_two_million_active_capital_boundary(self):
        ledger = OrderLedger()
        ledger.positions["000001"] = Position(
            code="000001",
            quantity=1,
            average_price=Decimal("1900000"),
            opened_at=self.now,
        )
        exactly_limit = self.gate.check_buy(
            self.intent(code="000002", price="100000"),
            self.market(code="000002", price="100000"),
            ledger,
            {"000001"},
            self.now,
        )
        over_limit = self.gate.check_buy(
            self.intent(key="key-2", code="000002", price="100001"),
            self.market(code="000002", price="100001"),
            ledger,
            {"000001"},
            self.now,
        )
        self.assertTrue(exactly_limit.allowed)
        self.assertEqual(over_limit.reason, "ACTIVE_CAPITAL_LIMIT")

    def test_sell_fill_releases_capital_for_rotation(self):
        ledger = OrderLedger()
        ledger.positions["000001"] = Position(
            code="000001",
            quantity=1,
            average_price=Decimal("1900000"),
            opened_at=self.now,
        )
        blocked = self.gate.check_buy(
            self.intent(code="000002", price="200001"),
            self.market(code="000002", price="200001"),
            ledger,
            {"000001"},
            self.now,
        )
        self.assertEqual(blocked.reason, "ACTIVE_CAPITAL_LIMIT")

        sell = self.intent(
            key="sell-1",
            code="000001",
            side=OrderSide.SELL,
            price="1900000",
        )
        ledger.submit(sell)
        ledger.apply_fill(self.fill("sell-1", "sell-exec-1", 1, "1900000"))
        allowed = self.gate.check_buy(
            self.intent(key="key-2", code="000002", price="200001"),
            self.market(code="000002", price="200001"),
            ledger,
            set(),
            self.now,
        )
        self.assertTrue(allowed.allowed)

    def test_partial_fill_state_transition(self):
        sink = InMemoryEventSink()
        ledger = OrderLedger(event_sink=sink)
        order = self.intent(quantity=2, price="100000")
        ledger.submit(order)
        first = ledger.apply_fill(self.fill("key-1", "exec-1", 1, "99000"))
        self.assertEqual(first.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(first.remaining_quantity, 1)
        self.assertEqual(ledger.positions["000001"].quantity, 1)
        self.assertEqual(ledger.active_capital_krw(), Decimal("199000"))

        second = ledger.apply_fill(self.fill("key-1", "exec-2", 1, "101000"))
        self.assertEqual(second.status, OrderStatus.FILLED)
        self.assertEqual(second.average_fill_price, Decimal("100000"))
        self.assertEqual(ledger.positions["000001"].quantity, 2)
        self.assertTrue(any(
            event.event_type == "ORDER_PARTIAL_FILL" for event in sink.events
        ))

    def test_timeout_remains_pending_and_blocks_duplicate(self):
        ledger = OrderLedger()
        ledger.submit(self.intent())
        state = ledger.mark_timeout("key-1", self.now)
        self.assertEqual(state.status, OrderStatus.TIMED_OUT_UNCONFIRMED)
        self.assertEqual(ledger.active_capital_krw(), Decimal("100000"))

        duplicate = self.gate.check_buy(
            self.intent(key="key-2"),
            self.market(),
            ledger,
            set(),
            self.now,
        )
        self.assertEqual(duplicate.reason, "DUPLICATE_CODE")

    def test_restart_reconciliation_does_not_duplicate_fill(self):
        ledger = OrderLedger()
        ledger.submit(self.intent())
        ledger.mark_timeout("key-1", self.now)
        restored = OrderLedger.from_dict(ledger.to_dict())
        state = restored.reconcile(
            "key-1",
            BrokerOrderStatus.FILLED,
            cumulative_filled_quantity=1,
            average_fill_price=Decimal("100000"),
            broker_order_id="broker-1",
            at=self.now,
        )
        self.assertEqual(state.status, OrderStatus.FILLED)
        self.assertEqual(restored.positions["000001"].quantity, 1)

        restored.reconcile(
            "key-1",
            BrokerOrderStatus.FILLED,
            cumulative_filled_quantity=1,
            average_fill_price=Decimal("100000"),
            broker_order_id="broker-1",
            at=self.now,
        )
        self.assertEqual(restored.positions["000001"].quantity, 1)

    def test_cost_injected_net_pnl(self):
        costs = CostRates(
            buy_commission_rate=Decimal("0.001"),
            sell_commission_rate=Decimal("0.001"),
            sell_tax_rate=Decimal("0.002"),
            full_spread_rate=Decimal("0.001"),
            per_side_slippage_rate=Decimal("0.001"),
        )
        pnl = calculate_net_pnl(
            buy_price=Decimal("100"),
            sell_price=Decimal("110"),
            quantity=10,
            costs=costs,
        )
        self.assertEqual(pnl.gross_pnl, Decimal("100"))
        self.assertEqual(pnl.commission, Decimal("2.100"))
        self.assertEqual(pnl.tax, Decimal("2.200"))
        self.assertEqual(pnl.spread, Decimal("1.0500"))
        self.assertEqual(pnl.slippage, Decimal("2.100"))
        self.assertEqual(pnl.net_pnl, Decimal("92.5500"))

    def test_state_serialization_round_trip_uses_temp_path(self):
        ledger = OrderLedger()
        ledger.submit(self.intent())
        ledger.apply_fill(self.fill("key-1", "exec-1", 1))
        ledger.submit(self.intent(key="key-2", code="000002", price="200000"))
        ledger.mark_timeout("key-2", self.now)

        path = Path(self.tempdir.name) / "state" / "ledger.json"
        store = JsonStateStore(path)
        store.save(ledger)
        restored = store.load()
        self.assertEqual(restored.to_dict(), ledger.to_dict())
        self.assertTrue(path.is_file())
        self.assertTrue(str(path).startswith(self.tempdir.name))

    def test_dry_run_order_port_is_idempotent(self):
        port = DryRunOrderPort()
        intent = self.intent()
        first = port.submit(intent)
        second = port.submit(intent)
        self.assertEqual(first, second)
        self.assertEqual(len(port.submissions), 1)
        self.assertEqual(first.status, "DRY_RUN_ACCEPTED")


if __name__ == "__main__":
    unittest.main()

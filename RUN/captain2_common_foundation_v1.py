# -*- coding: utf-8 -*-
"""Captain2 공통 기반 v1.

전략 판단과 운영 연결을 포함하지 않는다. 이 모듈은 시간·데이터 계약,
신규주문 안전관문, 주문/체결 상태, 손익·직렬화 계약만 제공한다.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
STATE_SCHEMA = "captain2_common_foundation_v1"


class ContractError(ValueError):
    """공통 데이터·상태 계약 위반."""


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def as_kst(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError("timezone-aware datetime required")
    return value.astimezone(KST)


def normalize_code(value: str) -> str:
    code = str(value).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ContractError(f"numeric six-digit code required: {value!r}")
    return code


@dataclass(frozen=True)
class TradingSession:
    open_at: time
    close_at: time

    def __post_init__(self) -> None:
        if self.open_at >= self.close_at:
            raise ContractError("market open must be earlier than close")

    def contains(self, moment: datetime) -> bool:
        kst = as_kst(moment)
        local_time = time(kst.hour, kst.minute, kst.second, kst.microsecond)
        return self.open_at <= local_time <= self.close_at


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age: timedelta

    def __post_init__(self) -> None:
        if self.max_age.total_seconds() <= 0:
            raise ContractError("max_age must be positive")

    def check(self, observed_at: datetime, now: datetime) -> tuple[bool, str]:
        age = as_kst(now) - as_kst(observed_at)
        if age.total_seconds() < 0:
            return False, "FUTURE_DATA"
        if age > self.max_age:
            return False, "STALE_DATA"
        return True, ""


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    observed_at: datetime
    price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_code(self.code))
        object.__setattr__(self, "observed_at", as_kst(self.observed_at))
        for name in ("price", "bid_price", "ask_price"):
            value = as_decimal(getattr(self, name))
            if value <= 0:
                raise ContractError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if not self.source.strip():
            raise ContractError("market data source required")


@dataclass(frozen=True)
class CandidateSignal:
    signal_id: str
    strategy_id: str
    code: str
    observed_at: datetime
    reference_price: Decimal
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.strategy_id.strip():
            raise ContractError("signal_id and strategy_id required")
        object.__setattr__(self, "code", normalize_code(self.code))
        object.__setattr__(self, "observed_at", as_kst(self.observed_at))
        price = as_decimal(self.reference_price)
        if price <= 0:
            raise ContractError("reference_price must be positive")
        object.__setattr__(self, "reference_price", price)


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderIntent:
    idempotency_key: str
    strategy_id: str
    signal_id: str
    code: str
    side: OrderSide
    quantity: int
    reservation_price: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or not self.strategy_id.strip():
            raise ContractError("idempotency_key and strategy_id required")
        object.__setattr__(self, "code", normalize_code(self.code))
        object.__setattr__(self, "created_at", as_kst(self.created_at))
        if self.quantity <= 0:
            raise ContractError("quantity must be positive")
        price = as_decimal(self.reservation_price)
        if price <= 0:
            raise ContractError("reservation_price must be positive")
        object.__setattr__(self, "reservation_price", price)

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "strategy_id": self.strategy_id,
            "signal_id": self.signal_id,
            "code": self.code,
            "side": self.side.value,
            "quantity": self.quantity,
            "reservation_price": str(self.reservation_price),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OrderIntent":
        return cls(
            idempotency_key=str(payload["idempotency_key"]),
            strategy_id=str(payload["strategy_id"]),
            signal_id=str(payload.get("signal_id") or ""),
            code=str(payload["code"]),
            side=OrderSide(str(payload["side"])),
            quantity=int(payload["quantity"]),
            reservation_price=as_decimal(payload["reservation_price"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True)
class FillReport:
    execution_id: str
    idempotency_key: str
    quantity: int
    price: Decimal
    filled_at: datetime

    def __post_init__(self) -> None:
        if not self.execution_id.strip() or not self.idempotency_key.strip():
            raise ContractError("execution_id and idempotency_key required")
        if self.quantity <= 0:
            raise ContractError("fill quantity must be positive")
        price = as_decimal(self.price)
        if price <= 0:
            raise ContractError("fill price must be positive")
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "filled_at", as_kst(self.filled_at))


@dataclass
class Position:
    code: str
    quantity: int
    average_price: Decimal
    opened_at: datetime

    def __post_init__(self) -> None:
        self.code = normalize_code(self.code)
        self.average_price = as_decimal(self.average_price)
        self.opened_at = as_kst(self.opened_at)
        if self.quantity <= 0 or self.average_price <= 0:
            raise ContractError("position quantity and price must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "quantity": self.quantity,
            "average_price": str(self.average_price),
            "opened_at": self.opened_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Position":
        return cls(
            code=str(payload["code"]),
            quantity=int(payload["quantity"]),
            average_price=as_decimal(payload["average_price"]),
            opened_at=datetime.fromisoformat(str(payload["opened_at"])),
        )


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    TIMED_OUT_UNCONFIRMED = "TIMED_OUT_UNCONFIRMED"
    CANCELLED = "CANCELLED"


PENDING_ORDER_STATUSES = {
    OrderStatus.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.TIMED_OUT_UNCONFIRMED,
}


@dataclass
class OrderState:
    intent: OrderIntent
    status: OrderStatus
    updated_at: datetime
    broker_order_id: str = ""
    filled_quantity: int = 0
    average_fill_price: Decimal = Decimal("0")
    rejection_reason: str = ""

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.intent.quantity - self.filled_quantity)

    @property
    def is_pending(self) -> bool:
        return self.status in PENDING_ORDER_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat(),
            "broker_order_id": self.broker_order_id,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": str(self.average_fill_price),
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OrderState":
        return cls(
            intent=OrderIntent.from_dict(payload["intent"]),
            status=OrderStatus(str(payload["status"])),
            updated_at=as_kst(datetime.fromisoformat(str(payload["updated_at"]))),
            broker_order_id=str(payload.get("broker_order_id") or ""),
            filled_quantity=int(payload.get("filled_quantity") or 0),
            average_fill_price=as_decimal(payload.get("average_fill_price") or "0"),
            rejection_reason=str(payload.get("rejection_reason") or ""),
        )


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    event_type: str
    entity_id: str
    occurred_at: datetime
    payload: Mapping[str, Any]


class EventSink(Protocol):
    def record(self, event: EventRecord) -> None:
        ...


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: list[EventRecord] = []

    def record(self, event: EventRecord) -> None:
        self.events.append(event)


class NullEventSink:
    def record(self, event: EventRecord) -> None:
        del event


class BrokerOrderStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class OrderLedger:
    """브로커와 분리된 주문·체결·포지션 상태 장부."""

    def __init__(self, event_sink: Optional[EventSink] = None) -> None:
        self.event_sink = event_sink or NullEventSink()
        self.orders: dict[str, OrderState] = {}
        self.positions: dict[str, Position] = {}
        self.processed_execution_ids: set[str] = set()

    def _event(
        self,
        event_type: str,
        entity_id: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        self.event_sink.record(EventRecord(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            entity_id=entity_id,
            occurred_at=as_kst(occurred_at),
            payload=dict(payload),
        ))

    def submit(self, intent: OrderIntent, broker_order_id: str = "") -> tuple[OrderState, bool]:
        previous = self.orders.get(intent.idempotency_key)
        if previous is not None:
            self._event(
                "ORDER_DUPLICATE_SUPPRESSED",
                intent.idempotency_key,
                intent.created_at,
                {"code": intent.code},
            )
            return previous, False
        state = OrderState(
            intent=intent,
            status=OrderStatus.SUBMITTED,
            updated_at=intent.created_at,
            broker_order_id=broker_order_id,
        )
        self.orders[intent.idempotency_key] = state
        self._event(
            "ORDER_SUBMITTED",
            intent.idempotency_key,
            intent.created_at,
            {"code": intent.code, "side": intent.side.value, "quantity": intent.quantity},
        )
        return state, True

    def bind_broker_order_id(self, key: str, broker_order_id: str, at: datetime) -> None:
        state = self._require_order(key)
        state.broker_order_id = broker_order_id
        state.updated_at = as_kst(at)

    def mark_timeout(self, key: str, at: datetime) -> OrderState:
        state = self._require_order(key)
        if state.status in PENDING_ORDER_STATUSES:
            state.status = OrderStatus.TIMED_OUT_UNCONFIRMED
            state.updated_at = as_kst(at)
            self._event("ORDER_TIMEOUT_UNCONFIRMED", key, at, {"code": state.intent.code})
        return state

    def mark_rejected(self, key: str, reason: str, at: datetime) -> OrderState:
        state = self._require_order(key)
        if state.filled_quantity:
            raise ContractError("cannot reject an order that already has fills")
        state.status = OrderStatus.REJECTED
        state.rejection_reason = reason
        state.updated_at = as_kst(at)
        self._event("ORDER_REJECTED", key, at, {"reason": reason})
        return state

    def mark_cancelled(self, key: str, at: datetime) -> OrderState:
        state = self._require_order(key)
        if state.status is not OrderStatus.FILLED:
            state.status = OrderStatus.CANCELLED
            state.updated_at = as_kst(at)
            self._event(
                "ORDER_CANCELLED",
                key,
                at,
                {"filled_quantity": state.filled_quantity},
            )
        return state

    def apply_fill(self, fill: FillReport) -> OrderState:
        state = self._require_order(fill.idempotency_key)
        if fill.execution_id in self.processed_execution_ids:
            return state
        if state.status in {OrderStatus.REJECTED, OrderStatus.CANCELLED}:
            raise ContractError(f"fill received after terminal status {state.status.value}")
        if fill.quantity > state.remaining_quantity:
            raise ContractError("fill exceeds remaining quantity")
        if state.intent.side is OrderSide.SELL:
            position = self.positions.get(state.intent.code)
            if position is None or position.quantity < fill.quantity:
                raise ContractError("sell fill exceeds held position")

        old_notional = state.average_fill_price * state.filled_quantity
        state.filled_quantity += fill.quantity
        state.average_fill_price = (
            old_notional + fill.price * fill.quantity
        ) / state.filled_quantity
        state.updated_at = fill.filled_at
        state.status = (
            OrderStatus.FILLED
            if state.filled_quantity == state.intent.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        self.processed_execution_ids.add(fill.execution_id)
        self._apply_position_fill(state.intent, fill)
        self._event(
            "ORDER_FILLED" if state.status is OrderStatus.FILLED else "ORDER_PARTIAL_FILL",
            fill.idempotency_key,
            fill.filled_at,
            {
                "execution_id": fill.execution_id,
                "filled_quantity": state.filled_quantity,
                "requested_quantity": state.intent.quantity,
                "average_fill_price": str(state.average_fill_price),
            },
        )
        return state

    def _apply_position_fill(self, intent: OrderIntent, fill: FillReport) -> None:
        position = self.positions.get(intent.code)
        if intent.side is OrderSide.BUY:
            if position is None:
                self.positions[intent.code] = Position(
                    code=intent.code,
                    quantity=fill.quantity,
                    average_price=fill.price,
                    opened_at=fill.filled_at,
                )
                return
            total_quantity = position.quantity + fill.quantity
            position.average_price = (
                position.average_price * position.quantity + fill.price * fill.quantity
            ) / total_quantity
            position.quantity = total_quantity
            return
        assert position is not None
        position.quantity -= fill.quantity
        if position.quantity == 0:
            del self.positions[intent.code]

    def reconcile(
        self,
        key: str,
        broker_status: BrokerOrderStatus,
        cumulative_filled_quantity: int,
        average_fill_price: Decimal,
        broker_order_id: str,
        at: datetime,
    ) -> OrderState:
        state = self._require_order(key)
        if cumulative_filled_quantity < state.filled_quantity:
            raise ContractError("broker cumulative fill moved backwards")
        if cumulative_filled_quantity > state.intent.quantity:
            raise ContractError("broker cumulative fill exceeds requested quantity")
        delta = cumulative_filled_quantity - state.filled_quantity
        if delta:
            cumulative_notional = as_decimal(average_fill_price) * cumulative_filled_quantity
            local_notional = state.average_fill_price * state.filled_quantity
            delta_price = (cumulative_notional - local_notional) / delta
            self.apply_fill(FillReport(
                execution_id=f"RECONCILE:{key}:{cumulative_filled_quantity}",
                idempotency_key=key,
                quantity=delta,
                price=delta_price,
                filled_at=at,
            ))
            state = self._require_order(key)
        state.broker_order_id = broker_order_id or state.broker_order_id
        state.updated_at = as_kst(at)
        if broker_status is BrokerOrderStatus.FILLED:
            if state.filled_quantity != state.intent.quantity:
                raise ContractError("FILLED broker status without full quantity")
            state.status = OrderStatus.FILLED
        elif broker_status is BrokerOrderStatus.REJECTED:
            self.mark_rejected(key, "BROKER_REJECTED", at)
        elif broker_status is BrokerOrderStatus.CANCELLED:
            self.mark_cancelled(key, at)
        elif broker_status is BrokerOrderStatus.OPEN:
            state.status = (
                OrderStatus.PARTIALLY_FILLED
                if state.filled_quantity
                else OrderStatus.SUBMITTED
            )
        else:
            state.status = OrderStatus.TIMED_OUT_UNCONFIRMED
        self._event(
            "ORDER_RECONCILED",
            key,
            at,
            {"broker_status": broker_status.value, "filled_quantity": state.filled_quantity},
        )
        return state

    def active_capital_krw(self) -> Decimal:
        held = sum(
            (position.average_price * position.quantity for position in self.positions.values()),
            Decimal("0"),
        )
        pending = sum(
            (
                state.intent.reservation_price * state.remaining_quantity
                for state in self.orders.values()
                if state.intent.side is OrderSide.BUY and state.is_pending
            ),
            Decimal("0"),
        )
        return held + pending

    def active_codes(self) -> set[str]:
        codes = set(self.positions)
        codes.update(
            state.intent.code
            for state in self.orders.values()
            if state.is_pending
        )
        return codes

    def has_pending_code(self, code: str) -> bool:
        normalized = normalize_code(code)
        return any(
            state.intent.code == normalized and state.is_pending
            for state in self.orders.values()
        )

    def _require_order(self, key: str) -> OrderState:
        try:
            return self.orders[key]
        except KeyError as exc:
            raise ContractError(f"unknown idempotency_key: {key}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "orders": {
                key: state.to_dict()
                for key, state in sorted(self.orders.items())
            },
            "positions": {
                code: position.to_dict()
                for code, position in sorted(self.positions.items())
            },
            "processed_execution_ids": sorted(self.processed_execution_ids),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        event_sink: Optional[EventSink] = None,
    ) -> "OrderLedger":
        if payload.get("schema") != STATE_SCHEMA:
            raise ContractError(f"unsupported state schema: {payload.get('schema')!r}")
        ledger = cls(event_sink=event_sink)
        ledger.orders = {
            str(key): OrderState.from_dict(value)
            for key, value in dict(payload.get("orders") or {}).items()
        }
        ledger.positions = {
            normalize_code(code): Position.from_dict(value)
            for code, value in dict(payload.get("positions") or {}).items()
        }
        ledger.processed_execution_ids = set(payload.get("processed_execution_ids") or [])
        return ledger


class JsonStateStore:
    """주입받은 경로만 쓰는 원자적 JSON 상태 저장소."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, ledger: OrderLedger) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def load(self, event_sink: Optional[EventSink] = None) -> OrderLedger:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return OrderLedger.from_dict(payload, event_sink=event_sink)


@dataclass(frozen=True)
class SafetyLimits:
    fixed_buy_quantity: int = 1
    max_slots: int = 6
    max_active_capital_krw: Decimal = Decimal("2000000")

    def __post_init__(self) -> None:
        if self.fixed_buy_quantity != 1:
            raise ContractError("Captain2 common foundation requires exactly one-share buys")
        if self.max_slots != 6:
            raise ContractError("Captain2 common foundation requires exactly six slots")
        if as_decimal(self.max_active_capital_krw) != Decimal("2000000"):
            raise ContractError("Captain2 common foundation requires 2,000,000 KRW active capital")


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


class SafetyGate:
    """전략 신호 뒤, 주문 제출 전에 실행하는 공통 신규매수 안전관문."""

    def __init__(
        self,
        off_flag_path: Path,
        trading_session: TradingSession,
        freshness_policy: FreshnessPolicy,
        limits: Optional[SafetyLimits] = None,
    ) -> None:
        self.off_flag_path = Path(off_flag_path)
        self.trading_session = trading_session
        self.freshness_policy = freshness_policy
        self.limits = limits or SafetyLimits()

    def check_buy(
        self,
        intent: OrderIntent,
        market: MarketSnapshot,
        ledger: OrderLedger,
        occupied_codes: set[str],
        now: datetime,
    ) -> GateDecision:
        now_kst = as_kst(now)
        if intent.side is not OrderSide.BUY:
            return GateDecision(False, "NOT_BUY_INTENT")
        if self.off_flag_path.exists():
            return GateDecision(False, "CAPTAIN2_OFF_FLAG")
        if not self.trading_session.contains(now_kst):
            return GateDecision(False, "MARKET_CLOSED")
        fresh, reason = self.freshness_policy.check(market.observed_at, now_kst)
        if not fresh:
            return GateDecision(False, reason)
        if market.code != intent.code:
            return GateDecision(False, "CODE_MISMATCH")
        if intent.quantity != self.limits.fixed_buy_quantity:
            return GateDecision(False, "BUY_QUANTITY_MUST_BE_ONE")
        if intent.idempotency_key in ledger.orders:
            return GateDecision(False, "DUPLICATE_IDEMPOTENCY_KEY")

        normalized_occupied = {normalize_code(code) for code in occupied_codes}
        active_codes = normalized_occupied | ledger.active_codes()
        if intent.code in active_codes:
            return GateDecision(False, "DUPLICATE_CODE")
        if len(active_codes) >= self.limits.max_slots:
            return GateDecision(False, "SLOT_LIMIT")

        projected = ledger.active_capital_krw() + (
            intent.reservation_price * intent.quantity
        )
        if projected > self.limits.max_active_capital_krw:
            return GateDecision(False, "ACTIVE_CAPITAL_LIMIT")
        return GateDecision(True, "")


@dataclass(frozen=True)
class CostRates:
    buy_commission_rate: Decimal
    sell_commission_rate: Decimal
    sell_tax_rate: Decimal
    full_spread_rate: Decimal
    per_side_slippage_rate: Decimal

    def __post_init__(self) -> None:
        for name in (
            "buy_commission_rate",
            "sell_commission_rate",
            "sell_tax_rate",
            "full_spread_rate",
            "per_side_slippage_rate",
        ):
            value = as_decimal(getattr(self, name))
            if value < 0 or value >= 1:
                raise ContractError(f"{name} must be in [0, 1)")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class PnlBreakdown:
    gross_pnl: Decimal
    commission: Decimal
    tax: Decimal
    spread: Decimal
    slippage: Decimal
    net_pnl: Decimal


def calculate_net_pnl(
    buy_price: Decimal,
    sell_price: Decimal,
    quantity: int,
    costs: CostRates,
) -> PnlBreakdown:
    if quantity <= 0:
        raise ContractError("quantity must be positive")
    buy = as_decimal(buy_price)
    sell = as_decimal(sell_price)
    if buy <= 0 or sell <= 0:
        raise ContractError("buy and sell prices must be positive")
    buy_notional = buy * quantity
    sell_notional = sell * quantity
    gross = sell_notional - buy_notional
    commission = (
        buy_notional * costs.buy_commission_rate
        + sell_notional * costs.sell_commission_rate
    )
    tax = sell_notional * costs.sell_tax_rate
    spread = (
        buy_notional + sell_notional
    ) * costs.full_spread_rate / Decimal("2")
    slippage = (
        buy_notional + sell_notional
    ) * costs.per_side_slippage_rate
    total_cost = commission + tax + spread + slippage
    return PnlBreakdown(
        gross_pnl=gross,
        commission=commission,
        tax=tax,
        spread=spread,
        slippage=slippage,
        net_pnl=gross - total_cost,
    )


@dataclass(frozen=True)
class DryRunSubmission:
    accepted: bool
    broker_order_id: str
    status: str


class DryRunOrderPort:
    """외부 호출이 전혀 없는 멱등성 주문 포트."""

    def __init__(self) -> None:
        self.submissions: dict[str, DryRunSubmission] = {}

    def submit(self, intent: OrderIntent) -> DryRunSubmission:
        previous = self.submissions.get(intent.idempotency_key)
        if previous is not None:
            return previous
        result = DryRunSubmission(
            accepted=True,
            broker_order_id=f"DRY-{len(self.submissions) + 1:06d}",
            status="DRY_RUN_ACCEPTED",
        )
        self.submissions[intent.idempotency_key] = result
        return result


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EntrySignalProvider(Protocol):
    def evaluate_entry(self, market: MarketSnapshot) -> Optional[CandidateSignal]:
        ...


class RisingHoldPolicy(Protocol):
    def evaluate_rising_hold(
        self,
        market: MarketSnapshot,
        position: Position,
    ) -> PolicyDecision:
        ...


class ExitPolicy(Protocol):
    def evaluate_exit(
        self,
        market: MarketSnapshot,
        position: Position,
    ) -> PolicyDecision:
        ...


class TimeExitPolicy(Protocol):
    def evaluate_time_exit(
        self,
        now: datetime,
        position: Position,
    ) -> PolicyDecision:
        ...

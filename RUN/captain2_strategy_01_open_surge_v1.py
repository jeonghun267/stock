# -*- coding: utf-8 -*-
"""캡틴2 전략 01 — 장초반 급상승 초입 매수조건.

매수 판정만 담당한다. 주문을 제출하지 않으며 상승보유·매도는
captain2_common_hold_sell_v1의 공통 엔진에 위임한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from enum import Enum

from captain2_common_foundation_v1 import ContractError, as_decimal, as_kst
from captain2_common_hold_sell_v1 import StrategyId


STRATEGY_NUMBER = 1
STRATEGY_ID = StrategyId.C2_01_OPEN_SURGE
STRATEGY_NAME = "캡틴2 전략 01 — 장초반 급상승 초입"


class BuyAction(str, Enum):
    WAIT = "WAIT"
    BUY_READY = "BUY_READY"
    BLOCK = "BLOCK"


class EntryRoute(str, Enum):
    OPEN_SURGE = "OPEN_SURGE"
    GAP_SURGE = "GAP_SURGE"


@dataclass(frozen=True)
class OpenSurgeConfig:
    entry_start: time = time(9, 0)
    entry_end: time = time(9, 20)
    min_price: Decimal = Decimal("10000")
    gap_min_pct: Decimal = Decimal("3.0")
    max_above_open_pct: Decimal = Decimal("3.0")
    min_buy_money_ratio: Decimal = Decimal("0.70")
    min_money_speed_5s: Decimal = Decimal("1666667")
    min_burst_ratio: Decimal = Decimal("3.0")
    burst_waive_sec: int = 30
    min_price_rising_sec: int = 3


@dataclass(frozen=True)
class OpenSurgeObservation:
    observed_at: datetime
    code: str
    previous_close: Decimal
    open_price: Decimal
    current_price: Decimal
    high_so_far: Decimal
    buy_money_ratio: Decimal
    money_speed_5s: Decimal
    money_speed_30s: Decimal
    price_rising_sec: int
    exact_flow: bool
    in_prior_value_pool: bool
    in_premarket_gap_pool: bool
    is_kosdaq: bool = True
    is_ordinary_share: bool = True
    below_open_seen: bool = False
    theme_leader: bool = False


@dataclass(frozen=True)
class BuyDecision:
    action: BuyAction
    reason: str
    strategy_id: StrategyId = STRATEGY_ID
    route: EntryRoute | None = None
    gap_pct: Decimal = Decimal("0")
    priority_bonus: int = 0


def _decision(
    action: BuyAction,
    reason: str,
    *,
    route: EntryRoute | None = None,
    gap_pct: Decimal = Decimal("0"),
    theme_leader: bool = False,
) -> BuyDecision:
    return BuyDecision(
        action=action,
        reason=reason,
        route=route,
        gap_pct=gap_pct,
        priority_bonus=1 if theme_leader else 0,
    )


def _validated_prices(
    observation: OpenSurgeObservation,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    previous = as_decimal(observation.previous_close)
    opening = as_decimal(observation.open_price)
    current = as_decimal(observation.current_price)
    high = as_decimal(observation.high_so_far)
    if min(previous, opening, current, high) <= 0:
        raise ContractError("Open-surge prices must be positive")
    if high < current:
        raise ContractError("high_so_far cannot be below current_price")
    return previous, opening, current, high


def _flow_block_reason(
    observation: OpenSurgeObservation,
    config: OpenSurgeConfig,
    open_elapsed_sec: float,
) -> str:
    buy_ratio = as_decimal(observation.buy_money_ratio)
    speed_5s = as_decimal(observation.money_speed_5s)
    speed_30s = as_decimal(observation.money_speed_30s)
    if not observation.exact_flow:
        return "EXACT_FLOW_MISSING"
    if buy_ratio < config.min_buy_money_ratio:
        return "BUY_MONEY_RATIO_WEAK"
    if speed_5s < config.min_money_speed_5s:
        return "MONEY_SPEED_WEAK"
    if observation.price_rising_sec < config.min_price_rising_sec:
        return "PRICE_RISE_NOT_PERSISTENT"
    if open_elapsed_sec >= config.burst_waive_sec:
        if speed_30s <= 0 or speed_5s / speed_30s < config.min_burst_ratio:
            return "MONEY_BURST_WEAK"
    return ""


class OpenSurgeBuyStrategy:
    def __init__(self, config: OpenSurgeConfig | None = None) -> None:
        self.config = config or OpenSurgeConfig()

    def evaluate(self, observation: OpenSurgeObservation) -> BuyDecision:
        observed_at = as_kst(observation.observed_at)
        current_time = observed_at.time().replace(tzinfo=None)
        if not self.config.entry_start <= current_time < self.config.entry_end:
            return _decision(BuyAction.BLOCK, "OUTSIDE_ENTRY_WINDOW")
        if not observation.is_kosdaq or not observation.is_ordinary_share:
            return _decision(BuyAction.BLOCK, "UNIVERSE_BLOCK")

        previous, opening, current, high = _validated_prices(observation)
        gap_pct = (opening / previous - Decimal("1")) * Decimal("100")
        route = (
            EntryRoute.GAP_SURGE
            if gap_pct >= self.config.gap_min_pct
            else EntryRoute.OPEN_SURGE
        )
        candidate = (
            observation.in_prior_value_pool
            or observation.in_premarket_gap_pool
            or route is EntryRoute.GAP_SURGE
        )
        if not candidate:
            return _decision(BuyAction.BLOCK, "NOT_IN_OPENING_POOL", gap_pct=gap_pct)
        if current < self.config.min_price:
            return _decision(BuyAction.BLOCK, "PRICE_BELOW_10000", gap_pct=gap_pct)
        if observation.below_open_seen:
            return _decision(BuyAction.BLOCK, "LOW_BUY_IS_STRATEGY_02", gap_pct=gap_pct)
        if current <= opening:
            return _decision(
                BuyAction.WAIT, "PRICE_NOT_ABOVE_OPEN", route=route, gap_pct=gap_pct
            )

        chase_ceiling = opening * (
            Decimal("1") + self.config.max_above_open_pct / Decimal("100")
        )
        if current > chase_ceiling or high > chase_ceiling:
            return _decision(BuyAction.BLOCK, "CHASE_ABOVE_OPEN_3PCT", gap_pct=gap_pct)

        open_at = observed_at.replace(hour=9, minute=0, second=0, microsecond=0)
        flow_reason = _flow_block_reason(
            observation,
            self.config,
            (observed_at - open_at).total_seconds(),
        )
        if flow_reason:
            return _decision(
                BuyAction.WAIT, flow_reason, route=route, gap_pct=gap_pct
            )
        return _decision(
            BuyAction.BUY_READY,
            "OPEN_SURGE_CONFIRMED",
            route=route,
            gap_pct=gap_pct,
            theme_leader=observation.theme_leader,
        )


def strategy_label() -> str:
    return f"C2-{STRATEGY_NUMBER:02d} {STRATEGY_NAME}"

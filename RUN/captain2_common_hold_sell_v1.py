# -*- coding: utf-8 -*-
"""Common rising-hold and sell decision engine.

This module has no broker connection and never submits an order.  Seven entry
Captain2 strategies and three Valley exit routes share one ordered decision
engine while their proven differences are kept in immutable strategy profiles.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from captain2_common_foundation_v1 import (
    ContractError,
    OrderIntent,
    OrderSide,
    as_decimal,
    as_kst,
    normalize_code,
)


STATE_SCHEMA = "captain2_common_hold_sell_v1"


class StrategyId(str, Enum):
    C2_01_OPEN_SURGE = "C2_01_OPEN_SURGE"
    EARLY_DIRECT_ONSET = "EARLY_DIRECT_ONSET"
    EARLY_GAP_ONSET = "EARLY_GAP_ONSET"
    EARLY_DIP_RECLAIM = "EARLY_DIP_RECLAIM"
    RAID = "RAID"
    PULL = "PULL"
    BASE = "BASE"
    REACCEL = "REACCEL"
    VALLEY = "VALLEY"
    VALLEY_MORNING_CRASH = "VALLEY_MORNING_CRASH"
    VALLEY_BASE_BREAKOUT = "VALLEY_BASE_BREAKOUT"


class HoldSellAction(str, Enum):
    HOLD = "HOLD"
    WATCH = "WATCH"
    SELL = "SELL"
    EMERGENCY_SELL = "EMERGENCY_SELL"


class HoldPhase(str, Enum):
    HOLD = "HOLD"
    WATCH = "WATCH"


class PeakStage(str, Enum):
    UNARMED = "UNARMED"
    PROFIT_2 = "PROFIT_2"
    PROFIT_4 = "PROFIT_4"
    PROFIT_7 = "PROFIT_7"


class MA3Mode(str, Enum):
    NONE = "NONE"
    HOLD_LOCK = "HOLD_LOCK"
    SELL_OVERRIDE = "SELL_OVERRIDE"


class ExitPolicy(str, Enum):
    CAPTAIN2 = "CAPTAIN2"
    VALLEY = "VALLEY"
    VALLEY_MORNING_CRASH = "VALLEY_MORNING_CRASH"
    VALLEY_BASE_BREAKOUT = "VALLEY_BASE_BREAKOUT"


EARLY_STRATEGIES = {
    StrategyId.EARLY_DIRECT_ONSET,
    StrategyId.EARLY_GAP_ONSET,
    StrategyId.EARLY_DIP_RECLAIM,
}


@dataclass(frozen=True)
class StrategyExitProfile:
    strategy_id: StrategyId
    hard_stop_pct: Decimal
    strong_flow_hard_stop_pct: Decimal
    force_exit_at: time
    early_decision_at: Optional[time]
    ma3_mode: MA3Mode
    score_min_hold_sec: int
    exit_policy: ExitPolicy
    peak_insure_pct: Optional[Decimal]
    target_profit_pct: Optional[Decimal]

    def stop_pct(self, buy_ratio_recent: Decimal) -> Decimal:
        if buy_ratio_recent > Decimal("0.50"):
            return self.strong_flow_hard_stop_pct
        return self.hard_stop_pct


def _profile(
    strategy_id: StrategyId,
    *,
    stop: str = "-2.0",
    strong_stop: Optional[str] = None,
    force: time = time(15, 10),
    early: Optional[time] = None,
    ma3: MA3Mode = MA3Mode.NONE,
    score_min_hold_sec: int = 60,
    exit_policy: ExitPolicy = ExitPolicy.CAPTAIN2,
    peak_insure: Optional[str] = None,
    target_profit: Optional[str] = None,
) -> StrategyExitProfile:
    return StrategyExitProfile(
        strategy_id=strategy_id,
        hard_stop_pct=Decimal(stop),
        strong_flow_hard_stop_pct=Decimal(strong_stop or stop),
        force_exit_at=force,
        early_decision_at=early,
        ma3_mode=ma3,
        score_min_hold_sec=score_min_hold_sec,
        exit_policy=exit_policy,
        peak_insure_pct=Decimal(peak_insure) if peak_insure is not None else None,
        target_profit_pct=Decimal(target_profit) if target_profit is not None else None,
    )


STRATEGY_PROFILES: Mapping[StrategyId, StrategyExitProfile] = {
    strategy: _profile(
        strategy,
        force=time(9, 30),
        early=time(9, 20),
    )
    for strategy in EARLY_STRATEGIES
}
STRATEGY_PROFILES = {
    **STRATEGY_PROFILES,
    StrategyId.C2_01_OPEN_SURGE: _profile(StrategyId.C2_01_OPEN_SURGE),
    StrategyId.RAID: _profile(StrategyId.RAID, ma3=MA3Mode.HOLD_LOCK),
    StrategyId.PULL: _profile(
        StrategyId.PULL,
        stop="-3.0",
        strong_stop="-4.0",
        ma3=MA3Mode.SELL_OVERRIDE,
        score_min_hold_sec=30,
    ),
    StrategyId.BASE: _profile(StrategyId.BASE, ma3=MA3Mode.SELL_OVERRIDE),
    StrategyId.REACCEL: _profile(StrategyId.REACCEL),
    StrategyId.VALLEY: _profile(
        StrategyId.VALLEY,
        stop="-2.5",
        exit_policy=ExitPolicy.VALLEY,
        peak_insure="-1.5",
    ),
    StrategyId.VALLEY_MORNING_CRASH: _profile(
        StrategyId.VALLEY_MORNING_CRASH,
        stop="-2.0",
        force=time(9, 30),
        exit_policy=ExitPolicy.VALLEY_MORNING_CRASH,
    ),
    StrategyId.VALLEY_BASE_BREAKOUT: _profile(
        StrategyId.VALLEY_BASE_BREAKOUT,
        stop="-1.5",
        exit_policy=ExitPolicy.VALLEY_BASE_BREAKOUT,
        target_profit="2.0",
    ),
}

CAPTAIN2_STRATEGIES = frozenset(set(StrategyId) - {
    StrategyId.VALLEY,
    StrategyId.VALLEY_MORNING_CRASH,
    StrategyId.VALLEY_BASE_BREAKOUT,
})
VALLEY_STRATEGIES = frozenset(set(StrategyId) - set(CAPTAIN2_STRATEGIES))



@dataclass(frozen=True)
class HoldSellConfig:
    watch_buy_ratio: Decimal = Decimal("0.52")
    sell_buy_ratio: Decimal = Decimal("0.48")
    watch_confirm_sec: int = 2
    sell_confirm_sec: int = 15
    ma_permit_confirm_mult: Decimal = Decimal("2.0")
    trail_steps: tuple[tuple[Decimal, Decimal], ...] = (
        (Decimal("2.0"), Decimal("1.5")),
        (Decimal("4.0"), Decimal("2.0")),
        (Decimal("7.0"), Decimal("2.5")),
    )
    trail_guard_buy_ratio: Decimal = Decimal("0.90")
    persistence_speed_fraction: Decimal = Decimal("0.50")
    dryup_fraction: Decimal = Decimal("0.20")
    dryup_confirm_sec: int = 60
    dryup_min_hold_sec: int = 60
    dryup_min_peak_money_per_sec: Decimal = Decimal("1000000")
    score_sell_enabled: bool = True
    score_sell_ready: Decimal = Decimal("75")
    score_confirm_sec: int = 5
    score_peak_min_money_per_sec: Decimal = Decimal("1000000")
    early_trend_min_buy_ratio: Decimal = Decimal("0.52")
    early_trend_speed_fraction: Decimal = Decimal("0.50")
    vwap_warn_exit_enabled: bool = True

    valley_watch_sec: int = 10
    valley_sell_score_threshold: int = 3
    valley_weak_ma_score_threshold: int = 2
    valley_morning_confirm_sec: int = 10

    def __post_init__(self) -> None:
        ratios = (
            self.watch_buy_ratio,
            self.sell_buy_ratio,
            self.trail_guard_buy_ratio,
            self.persistence_speed_fraction,
            self.dryup_fraction,
            self.early_trend_min_buy_ratio,
            self.early_trend_speed_fraction,
        )
        if any(value < 0 or value > 1 for value in ratios):
            raise ContractError("ratio configuration must be in [0, 1]")
        if self.sell_buy_ratio > self.watch_buy_ratio:
            raise ContractError("sell ratio must not exceed watch ratio")
        if not self.trail_steps:
            raise ContractError("at least one trail step is required")

        if self.valley_watch_sec <= 0 or self.valley_morning_confirm_sec <= 0:
            raise ContractError("Valley confirmation seconds must be positive")
        if not 1 <= self.valley_weak_ma_score_threshold <= self.valley_sell_score_threshold <= 4:
            raise ContractError("Valley sell score thresholds must be in [1, 4]")

@dataclass(frozen=True)
class HoldSellObservation:
    observed_at: datetime
    price: Decimal
    vwap: Decimal = Decimal("0")
    buy_ratio_recent: Decimal = Decimal("0.60")
    money_speed_5s: Decimal = Decimal("0")
    money_speed_10s: Decimal = Decimal("0")
    money_speed_30s: Decimal = Decimal("0")
    buy_money_per_sec_10s: Decimal = Decimal("0")
    sell_money_per_sec_10s: Decimal = Decimal("0")
    buy_money_per_sec_30s: Decimal = Decimal("0")
    sell_money_per_sec_30s: Decimal = Decimal("0")
    structure_broken: bool = False
    money_accelerating: bool = False
    ma3_permit: bool = False
    daily_ma_permit: bool = False
    recent_buy_money_rising: bool = False

    valley_completed_bearish_1m: bool = False
    valley_strength_falling: bool = False
    valley_buy_flow_falling: bool = False
    valley_sell_flow_rising: bool = False
    valley_peak_reclaim_failed: bool = False
    valley_peak_reclaimed: bool = False
    valley_ma5_reclaimed_then_lost: bool = False
    valley_ma10_reclaimed_then_lost: bool = False
    valley_exact_flow_valid: bool = False
    valley_exact_sell_dominant: bool = False
    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_kst(self.observed_at))
        decimal_fields = (
            "price",
            "vwap",
            "buy_ratio_recent",
            "money_speed_5s",
            "money_speed_10s",
            "money_speed_30s",
            "buy_money_per_sec_10s",
            "sell_money_per_sec_10s",
            "buy_money_per_sec_30s",
            "sell_money_per_sec_30s",
        )
        for name in decimal_fields:
            value = as_decimal(getattr(self, name))
            if value < 0 or (name == "price" and value <= 0):
                raise ContractError(f"{name} must be non-negative and price positive")
            object.__setattr__(self, name, value)
        if self.buy_ratio_recent > 1:
            raise ContractError("buy_ratio_recent must be in [0, 1]")

    @property
    def money_per_sec_30s(self) -> Decimal:
        return self.buy_money_per_sec_30s + self.sell_money_per_sec_30s

    @property
    def buy_ratio_10s(self) -> Decimal:
        total = self.buy_money_per_sec_10s + self.sell_money_per_sec_10s
        return self.buy_money_per_sec_10s / total if total > 0 else Decimal("0")


@dataclass
class HoldSellState:
    position_id: str
    strategy_id: StrategyId
    code: str
    quantity: int
    entry_price: Decimal
    entry_at: datetime
    peak_price: Decimal = Decimal("0")
    peak_stage: PeakStage = PeakStage.UNARMED
    phase: HoldPhase = HoldPhase.HOLD
    last_observed_at: Optional[datetime] = None
    watch_since: Optional[datetime] = None
    sell_condition_since: Optional[datetime] = None
    ma3_override_since: Optional[datetime] = None
    dryup_since: Optional[datetime] = None
    score_sell_since: Optional[datetime] = None
    hold_peak_money_per_sec: Decimal = Decimal("0")
    valley_watch_since: Optional[datetime] = None
    valley_morning_break_since: Optional[datetime] = None
    hold_peak_speed_5s: Decimal = Decimal("0")
    sell_latched: bool = False
    sell_action: HoldSellAction = HoldSellAction.SELL
    sell_reason: str = ""
    sell_latched_at: Optional[datetime] = None
    sell_latched_price: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.strategy_id = StrategyId(self.strategy_id)
        self.code = normalize_code(self.code)
        self.entry_at = as_kst(self.entry_at)
        self.entry_price = as_decimal(self.entry_price)
        self.peak_price = as_decimal(self.peak_price or self.entry_price)
        if not self.position_id.strip():
            raise ContractError("position_id is required")
        if self.quantity <= 0 or self.entry_price <= 0:
            raise ContractError("positive quantity and entry price are required")
        if self.peak_price < self.entry_price:
            self.peak_price = self.entry_price

    @property
    def order_key(self) -> str:
        return f"captain2-exit:{self.position_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "strategy_id": self.strategy_id.value,
            "code": self.code,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "entry_at": self.entry_at.isoformat(),
            "peak_price": str(self.peak_price),
            "peak_stage": self.peak_stage.value,
            "phase": self.phase.value,
            "last_observed_at": _dt_text(self.last_observed_at),
            "watch_since": _dt_text(self.watch_since),
            "sell_condition_since": _dt_text(self.sell_condition_since),
            "ma3_override_since": _dt_text(self.ma3_override_since),
            "dryup_since": _dt_text(self.dryup_since),
            "score_sell_since": _dt_text(self.score_sell_since),
            "hold_peak_money_per_sec": str(self.hold_peak_money_per_sec),
            "valley_watch_since": _dt_text(self.valley_watch_since),
            "valley_morning_break_since": _dt_text(self.valley_morning_break_since),
            "hold_peak_speed_5s": str(self.hold_peak_speed_5s),
            "sell_latched": self.sell_latched,
            "sell_action": self.sell_action.value,
            "sell_reason": self.sell_reason,
            "sell_latched_at": _dt_text(self.sell_latched_at),
            "sell_latched_price": str(self.sell_latched_price),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HoldSellState":
        state = cls(
            position_id=str(payload["position_id"]),
            strategy_id=StrategyId(str(payload["strategy_id"])),
            code=str(payload["code"]),
            quantity=int(payload["quantity"]),
            entry_price=as_decimal(payload["entry_price"]),
            entry_at=datetime.fromisoformat(str(payload["entry_at"])),
            peak_price=as_decimal(payload["peak_price"]),
        )
        state.peak_stage = PeakStage(str(payload.get("peak_stage") or "UNARMED"))
        state.phase = HoldPhase(str(payload.get("phase") or "HOLD"))
        for name in (
            "last_observed_at",
            "watch_since",
            "sell_condition_since",
            "ma3_override_since",
            "dryup_since",
            "score_sell_since",
            "sell_latched_at",
            "valley_watch_since",
            "valley_morning_break_since",
        ):
            setattr(state, name, _parse_dt(payload.get(name)))
        state.hold_peak_money_per_sec = as_decimal(
            payload.get("hold_peak_money_per_sec") or "0"
        )
        state.hold_peak_speed_5s = as_decimal(payload.get("hold_peak_speed_5s") or "0")
        state.sell_latched = bool(payload.get("sell_latched"))
        state.sell_action = HoldSellAction(str(payload.get("sell_action") or "SELL"))
        state.sell_reason = str(payload.get("sell_reason") or "")
        state.sell_latched_price = as_decimal(payload.get("sell_latched_price") or "0")
        return state


@dataclass(frozen=True)
class HoldSellDecision:
    action: HoldSellAction
    reason: str
    strategy_id: StrategyId
    code: str
    observed_at: datetime
    price: Decimal
    order_key: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def should_sell(self) -> bool:
        return self.action in {
            HoldSellAction.SELL,
            HoldSellAction.EMERGENCY_SELL,
        }


def _dt_text(value: Optional[datetime]) -> str:
    return value.isoformat() if value is not None else ""


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    return as_kst(datetime.fromisoformat(text)) if text else None


class UnifiedHoldSellEngine:
    """One ordered hold/sell coordinator with strategy-specific profiles."""

    def __init__(self, config: Optional[HoldSellConfig] = None) -> None:
        self.config = config or HoldSellConfig()

    def evaluate(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        self._validate_sequence(state, observation)
        if state.sell_latched:
            return self._latched_decision(state)
        self._update_state_metrics(state, observation)
        profile = STRATEGY_PROFILES[state.strategy_id]
        if profile.exit_policy is not ExitPolicy.CAPTAIN2:
            return self._evaluate_valley(state, observation, profile)
        for rule in (
            self._hard_stop_rule,
            self._time_exit_rule,
            self._early_trend_rule,
            self._ma3_rule,
            self._profit_trail_rule,
            self._money_dryup_rule,
            self._score_rule,
            self._vwap_fallback_rule,
        ):
            decision = rule(state, observation, profile)
            if decision is not None:
                return decision
        return self._flow_structure_rule(state, observation, profile)

    def _evaluate_valley(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        if profile.exit_policy is ExitPolicy.VALLEY:
            return self._evaluate_regular_valley(state, observation, profile)
        if profile.exit_policy is ExitPolicy.VALLEY_MORNING_CRASH:
            return self._evaluate_valley_morning(state, observation, profile)
        return self._evaluate_valley_base(state, observation, profile)

    def _evaluate_regular_valley(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        peak_drop = (
            observation.price / state.peak_price - Decimal("1")
        ) * Decimal("100")
        if profile.peak_insure_pct is not None and peak_drop <= profile.peak_insure_pct:
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                f"VALLEY_PEAK_INSURE {peak_drop:.2f}% <= {profile.peak_insure_pct:.2f}%",
            )
        if observation.valley_ma10_reclaimed_then_lost:
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                "VALLEY_MA10_RECLAIM_LOST",
            )
        return self._valley_peak_watch_rule(state, observation)

    def _valley_peak_watch_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        if observation.valley_peak_reclaimed:
            state.valley_watch_since = None
            return self._decision(
                state, observation, HoldSellAction.HOLD, "VALLEY_PEAK_RECLAIM_HOLD"
            )
        if state.valley_watch_since is None:
            if not observation.valley_completed_bearish_1m:
                return self._decision(
                    state, observation, HoldSellAction.HOLD, "VALLEY_RISING_HOLD"
                )
            state.valley_watch_since = observation.observed_at
        age = (observation.observed_at - state.valley_watch_since).total_seconds()
        if age < self.config.valley_watch_sec:
            return self._decision(
                state,
                observation,
                HoldSellAction.WATCH,
                f"VALLEY_PEAK_WATCH {age:.0f}/{self.config.valley_watch_sec}s",
            )
        return self._finish_valley_peak_watch(state, observation)

    def _finish_valley_peak_watch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        points = {
            "STRENGTH_FALL": observation.valley_strength_falling,
            "BUY_FLOW_FALL": observation.valley_buy_flow_falling,
            "SELL_FLOW_RISE": observation.valley_sell_flow_rising,
            "PEAK_RECLAIM_FAIL": observation.valley_peak_reclaim_failed,
        }
        score = sum(1 for value in points.values() if value)
        threshold = (
            self.config.valley_weak_ma_score_threshold
            if observation.valley_ma5_reclaimed_then_lost
            else self.config.valley_sell_score_threshold
        )
        state.valley_watch_since = None
        if score >= threshold:
            hits = ",".join(name for name, hit in points.items() if hit)
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                f"VALLEY_PEAK_SELL score={score}/4 threshold={threshold} {hits}",
            )
        return self._decision(
            state,
            observation,
            HoldSellAction.HOLD,
            f"VALLEY_PEAK_WATCH_RELEASE score={score}/4 threshold={threshold}",
        )

    def _evaluate_valley_morning(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        if not observation.structure_broken:
            state.valley_morning_break_since = None
            return self._decision(
                state, observation, HoldSellAction.HOLD, "VALLEY_MORNING_HOLD"
            )
        if state.valley_morning_break_since is None:
            state.valley_morning_break_since = observation.observed_at
        age = (
            observation.observed_at - state.valley_morning_break_since
        ).total_seconds()
        if age < self.config.valley_morning_confirm_sec:
            return self._decision(
                state,
                observation,
                HoldSellAction.WATCH,
                f"VALLEY_MORNING_BREAK_WATCH {age:.0f}/{self.config.valley_morning_confirm_sec}s",
            )
        return self._finish_valley_morning_watch(state, observation)

    def _finish_valley_morning_watch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        state.valley_morning_break_since = None
        exact_sell = (
            observation.valley_exact_flow_valid
            and observation.valley_exact_sell_dominant
        )
        if exact_sell:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                "VALLEY_MORNING_STRUCTURE_BREAK+EXACT_SELL_DOMINANT",
            )
        return self._decision(
            state, observation, HoldSellAction.HOLD, "VALLEY_MORNING_BREAK_CANCEL"
        )

    def _evaluate_valley_base(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        return_pct = self._return_pct(state, observation.price)
        if profile.target_profit_pct is not None and return_pct >= profile.target_profit_pct:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                f"VALLEY_BASE_TARGET {return_pct:.2f}% >= {profile.target_profit_pct:.2f}%",
            )
        return self._decision(
            state, observation, HoldSellAction.HOLD, "VALLEY_BASE_HOLD"
        )

    def _profile_time_exit(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time < profile.force_exit_at:
            return None
        return self._latch(
            state,
            observation,
            HoldSellAction.EMERGENCY_SELL,
            f"TIME_EXIT_{profile.force_exit_at.strftime('%H%M')}",
        )


    @staticmethod
    def _validate_sequence(
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> None:
        if observation.observed_at < state.entry_at:
            raise ContractError("observation precedes entry time")
        if state.last_observed_at and observation.observed_at < state.last_observed_at:
            raise ContractError("out-of-order observation rejected")

    def _update_state_metrics(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> None:
        state.last_observed_at = observation.observed_at
        state.peak_price = max(state.peak_price, observation.price)
        state.hold_peak_money_per_sec = max(
            state.hold_peak_money_per_sec,
            observation.money_per_sec_30s,
        )
        state.hold_peak_speed_5s = max(
            state.hold_peak_speed_5s,
            observation.money_speed_5s,
        )
        state.peak_stage = self._peak_stage(state)

    def _hard_stop_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        return_pct = self._return_pct(state, observation.price)
        stop_pct = profile.stop_pct(observation.buy_ratio_recent)
        if return_pct <= stop_pct:
            reason = f"HARD_STOP {return_pct:.2f}% <= {stop_pct:.2f}%"
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                reason,
            )
        return None

    def _time_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time >= profile.force_exit_at:
            reason = f"TIME_EXIT_{profile.force_exit_at.strftime('%H%M')}"
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                reason,
            )
        return None

    def _early_trend_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if profile.early_decision_at is None:
            return None
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time < profile.early_decision_at:
            return None
        failures = self._early_trend_failures(state, observation)
        if failures:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                "EARLY_TREND_EXIT " + ",".join(failures),
            )
        return None

    def _early_trend_failures(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> list[str]:
        failures: list[str] = []
        if not (observation.vwap > 0 and observation.price > observation.vwap):
            failures.append("VWAP")
        if not observation.ma3_permit:
            failures.append("MA3")
        if observation.buy_ratio_recent < self.config.early_trend_min_buy_ratio:
            failures.append("FLOW")
        speed_floor = self.config.early_trend_speed_fraction * observation.money_speed_30s
        if not (observation.money_speed_30s > 0 and observation.money_speed_10s >= speed_floor):
            failures.append("SPEED")
        if observation.structure_broken:
            failures.append("STRUCTURE")
        if self._sell_score(state, observation) >= self.config.score_sell_ready:
            failures.append("SELL_SCORE")
        return failures

    def _ma3_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if not observation.ma3_permit or profile.ma3_mode is MA3Mode.NONE:
            state.ma3_override_since = None
            return None
        if profile.ma3_mode is MA3Mode.HOLD_LOCK:
            self._reset_general_exit_timers(state)
            return self._decision(state, observation, HoldSellAction.HOLD, "MA3_RIDER_HOLD")
        return self._ma3_override_rule(state, observation)

    def _ma3_override_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        self._reset_general_exit_timers(state)
        override = self._sell_dominant_break(observation)
        if not override:
            state.ma3_override_since = None
            return self._decision(state, observation, HoldSellAction.HOLD, "MA3_RIDER_HOLD")
        if state.ma3_override_since is None:
            state.ma3_override_since = observation.observed_at
        age = (observation.observed_at - state.ma3_override_since).total_seconds()
        if age >= self.config.sell_confirm_sec:
            reason = f"{state.strategy_id.value}_MA3_SELL_OVERRIDE {age:.0f}s"
            return self._latch(state, observation, HoldSellAction.SELL, reason)
        return self._decision(
            state,
            observation,
            HoldSellAction.WATCH,
            f"MA3_SELL_WATCH {age:.0f}/{self.config.sell_confirm_sec}s",
        )

    def _profit_trail_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        drop_threshold = self._trail_drop_threshold(state)
        if drop_threshold <= 0:
            return None
        peak_drop = (state.peak_price - observation.price) / state.peak_price * 100
        if peak_drop < drop_threshold or self._trail_money_guard(observation):
            return None
        peak_return = self._return_pct(state, state.peak_price)
        reason = (
            f"PROFIT_TRAIL peak={peak_return:.2f}% "
            f"drop={peak_drop:.2f}% threshold={drop_threshold:.2f}%"
        )
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _trail_money_guard(self, observation: HoldSellObservation) -> bool:
        speed_alive = (
            observation.money_speed_30s <= 0
            or observation.money_speed_10s
            >= self.config.persistence_speed_fraction * observation.money_speed_30s
        )
        return (
            observation.buy_ratio_10s >= self.config.trail_guard_buy_ratio
            and speed_alive
        )

    def _money_dryup_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        hold_age = (observation.observed_at - state.entry_at).total_seconds()
        peak = state.hold_peak_money_per_sec
        dry = (
            hold_age >= self.config.dryup_min_hold_sec
            and peak >= self.config.dryup_min_peak_money_per_sec
            and observation.money_per_sec_30s < self.config.dryup_fraction * peak
            and not observation.money_accelerating
            and observation.sell_money_per_sec_30s > observation.buy_money_per_sec_30s
        )
        if not dry:
            state.dryup_since = None
            return None
        if state.dryup_since is None:
            state.dryup_since = observation.observed_at
        age = (observation.observed_at - state.dryup_since).total_seconds()
        if age < self.config.dryup_confirm_sec:
            return None
        reason = f"MONEY_DRYUP sell_dominant {age:.0f}s"
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _score_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if not self.config.score_sell_enabled:
            return None
        score = self._sell_score(state, observation)
        hold_age = (observation.observed_at - state.entry_at).total_seconds()
        blocked = (
            score < self.config.score_sell_ready
            or observation.daily_ma_permit
            or hold_age < profile.score_min_hold_sec
            or observation.recent_buy_money_rising
        )
        if blocked:
            state.score_sell_since = None
            return None
        if state.score_sell_since is None:
            state.score_sell_since = observation.observed_at
        age = (observation.observed_at - state.score_sell_since).total_seconds()
        if age < self.config.score_confirm_sec:
            return None
        reason = f"SCORE_SELL score={score:.1f} age={age:.0f}s"
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _sell_score(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> Decimal:
        score = Decimal("0")
        if observation.vwap > 0 and observation.price < observation.vwap:
            score += Decimal("25")
        peak = state.hold_peak_speed_5s
        if peak >= self.config.score_peak_min_money_per_sec:
            if observation.money_speed_5s < Decimal("0.20") * peak:
                score += Decimal("40")
            elif observation.money_speed_5s < Decimal("0.50") * peak:
                score += Decimal("25")
        total_30 = observation.money_per_sec_30s
        if total_30 > 0:
            buy_share = observation.buy_money_per_sec_30s / total_30
            if buy_share < Decimal("0.35"):
                score += Decimal("35")
            elif buy_share < Decimal("0.50"):
                score += Decimal("25")
        return score * Decimal("0.50") if observation.money_accelerating else score

    def _vwap_fallback_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if self.config.score_sell_enabled or not self.config.vwap_warn_exit_enabled:
            return None
        speed_weak = (
            observation.money_speed_30s > 0
            and observation.money_speed_10s
            < self.config.persistence_speed_fraction * observation.money_speed_30s
        )
        should_sell = (
            observation.vwap > 0
            and observation.price < observation.vwap
            and observation.buy_ratio_recent <= self.config.sell_buy_ratio
            and speed_weak
            and not observation.money_accelerating
        )
        if not should_sell:
            return None
        return self._latch(
            state,
            observation,
            HoldSellAction.SELL,
            "VWAP_WARN_EXIT",
        )

    def _flow_structure_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        flow_weak = observation.buy_ratio_recent < self.config.watch_buy_ratio
        if state.phase is HoldPhase.HOLD:
            if not flow_weak:
                return self._decision(state, observation, HoldSellAction.HOLD, "FLOW_HEALTHY")
            state.phase = HoldPhase.WATCH
            state.watch_since = observation.observed_at
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.WATCH, "FLOW_WEAK")
        if not flow_weak:
            state.phase = HoldPhase.HOLD
            state.watch_since = None
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.HOLD, "FLOW_RECOVERED")
        return self._watch_flow_rule(state, observation)

    def _watch_flow_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        if not self._sell_dominant_break(observation):
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.WATCH, "WATCH_CONTINUE")
        if state.sell_condition_since is None:
            state.sell_condition_since = observation.observed_at
        watch_age = (observation.observed_at - (state.watch_since or observation.observed_at)).total_seconds()
        condition_age = (observation.observed_at - state.sell_condition_since).total_seconds()
        multiplier = self.config.ma_permit_confirm_mult if observation.daily_ma_permit else Decimal("1")
        required = Decimal(self.config.sell_confirm_sec) * multiplier
        if watch_age >= self.config.watch_confirm_sec and Decimal(str(condition_age)) >= required:
            reason = f"FLOW_WEAK+STRUCTURE_BREAK {condition_age:.0f}s"
            return self._latch(state, observation, HoldSellAction.SELL, reason)
        return self._decision(
            state,
            observation,
            HoldSellAction.WATCH,
            f"SELL_CONFIRM {condition_age:.0f}/{required:.0f}s",
        )

    def _sell_dominant_break(self, observation: HoldSellObservation) -> bool:
        return (
            observation.buy_ratio_recent <= self.config.sell_buy_ratio
            and observation.structure_broken
            and not observation.money_accelerating
        )

    @staticmethod
    def _reset_general_exit_timers(state: HoldSellState) -> None:
        state.phase = HoldPhase.HOLD
        state.watch_since = None
        state.sell_condition_since = None
        state.dryup_since = None
        state.score_sell_since = None

    def _peak_stage(self, state: HoldSellState) -> PeakStage:
        peak_return = self._return_pct(state, state.peak_price)
        if peak_return >= Decimal("7"):
            return PeakStage.PROFIT_7
        if peak_return >= Decimal("4"):
            return PeakStage.PROFIT_4
        if peak_return >= Decimal("2"):
            return PeakStage.PROFIT_2
        return PeakStage.UNARMED

    def _trail_drop_threshold(self, state: HoldSellState) -> Decimal:
        peak_return = self._return_pct(state, state.peak_price)
        threshold = Decimal("0")
        for arm, drop in self.config.trail_steps:
            if peak_return >= arm:
                threshold = drop
        return threshold

    @staticmethod
    def _return_pct(state: HoldSellState, price: Decimal) -> Decimal:
        return (as_decimal(price) / state.entry_price - Decimal("1")) * Decimal("100")

    def _latch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        action: HoldSellAction,
        reason: str,
    ) -> HoldSellDecision:
        state.sell_latched = True
        state.sell_action = action
        state.sell_reason = reason
        state.sell_latched_at = observation.observed_at
        state.sell_latched_price = observation.price
        return self._latched_decision(state)

    def _latched_decision(self, state: HoldSellState) -> HoldSellDecision:
        if state.sell_latched_at is None or state.sell_latched_price <= 0:
            raise ContractError("latched sell state is incomplete")
        metadata = {
            "peak_price": str(state.peak_price),
            "peak_stage": state.peak_stage.value,
        }
        return HoldSellDecision(
            action=state.sell_action,
            reason=state.sell_reason,
            strategy_id=state.strategy_id,
            code=state.code,
            observed_at=state.sell_latched_at,
            price=state.sell_latched_price,
            order_key=state.order_key,
            metadata=metadata,
        )

    def _decision(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        action: HoldSellAction,
        reason: str,
    ) -> HoldSellDecision:
        metadata = {
            "peak_price": str(state.peak_price),
            "peak_stage": state.peak_stage.value,
            "phase": state.phase.value,
        }
        return HoldSellDecision(
            action=action,
            reason=reason,
            strategy_id=state.strategy_id,
            code=state.code,
            observed_at=observation.observed_at,
            price=observation.price,
            order_key=state.order_key,
            metadata=metadata,
        )


def build_sell_intent(
    state: HoldSellState,
    decision: HoldSellDecision,
) -> Optional[OrderIntent]:
    """Build a deterministic sell intent; no broker call is made."""
    if not decision.should_sell:
        return None
    if decision.code != state.code or decision.strategy_id is not state.strategy_id:
        raise ContractError("decision and position state do not match")
    return OrderIntent(
        idempotency_key=decision.order_key,
        strategy_id=state.strategy_id.value,
        signal_id=decision.reason,
        code=state.code,
        side=OrderSide.SELL,
        quantity=state.quantity,
        reservation_price=decision.price,
        created_at=decision.observed_at,
    )


class JsonHoldSellStateStore:
    """Atomic persistence for restart-safe hold/sell decision state."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, states: Mapping[str, HoldSellState]) -> None:
        payload = {
            "schema": STATE_SCHEMA,
            "states": {
                normalize_code(code): state.to_dict()
                for code, state in sorted(states.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def load(self) -> dict[str, HoldSellState]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != STATE_SCHEMA:
            raise ContractError(f"unsupported state schema: {payload.get('schema')!r}")
        return {
            normalize_code(code): HoldSellState.from_dict(state)
            for code, state in dict(payload.get("states") or {}).items()
        }

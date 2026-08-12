# -*- coding: utf-8 -*-
"""Order-zero S02 six-second exit shadow.

The engine consumes the same observation as S02 live exits but can only emit
comparison events.  It never receives a broker or order callback.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict

from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyExitProfile,
    StrategyId,
    UnifiedHoldSellEngine,
)


STATE_KEY = "s02_six_second_shadow_state"
DONE_KEY = "s02_six_second_shadow_done"
ACTION_KEY = "s02_six_second_shadow_action"


class Strategy02SixSecondCandidateEngine(UnifiedHoldSellEngine):
    """Use six seconds only for an MA-supported weak S02 peak reversal."""

    def _common_peak_flow_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ):
        if state.strategy_id is StrategyId.S02_LOW_BUY_SELL_EXHAUSTION:
            profile = replace(
                profile,
                supported_weak_peak_confirm_sec=6,
                supported_weak_peak_active_date="*",
                supported_weak_peak_arm_return_pct=5,
                supported_weak_peak_drop_pct=1.5,
                supported_weak_peak_score=3,
            )
        return super()._common_peak_flow_exit_rule(
            state, observation, profile,
        )


class Strategy02SixSecondShadow:
    """Persist candidate state inside the position and emit order-zero events."""

    def __init__(self, event_sink: Callable[..., None]) -> None:
        self.engine = Strategy02SixSecondCandidateEngine()
        self.event_sink = event_sink

    def evaluate(
        self,
        position: Dict[str, Any],
        observation: HoldSellObservation,
    ) -> None:
        if position.get(DONE_KEY):
            return
        payload = position.get(STATE_KEY)
        if payload:
            state = HoldSellState.from_dict(payload)
        else:
            state = HoldSellState.from_dict(position["hold_state"])
            if state.last_observed_at is not None:
                position[DONE_KEY] = True
                self._emit(
                    position,
                    observation,
                    "[UNVERIFIED] skipped: shadow started mid-position",
                )
                return
        if (
            state.last_observed_at is not None
            and observation.observed_at <= state.last_observed_at
        ):
            return

        decision = self.engine.evaluate(state, observation)
        position[STATE_KEY] = state.to_dict()
        action = decision.action.value
        if action != position.get(ACTION_KEY) or decision.should_sell:
            position[ACTION_KEY] = action
            self._emit(
                position,
                observation,
                f"[HYPOTHETICAL] {action} {decision.reason}",
            )
        if decision.should_sell:
            position[DONE_KEY] = True

    def _emit(
        self,
        position: Dict[str, Any],
        observation: HoldSellObservation,
        reason: str,
    ) -> None:
        self.event_sink(
            "S02_EXIT_6S_SHADOW",
            code=str(position.get("code") or "").zfill(6),
            name=str(position.get("name") or ""),
            price=float(observation.price),
            reason=reason,
        )

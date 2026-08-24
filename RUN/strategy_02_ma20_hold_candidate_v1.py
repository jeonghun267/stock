# -*- coding: utf-8 -*-
"""Order-zero S02 candidate: extend only weak MA20-supported peak confirmation.

This module is intentionally not imported by any live rotation engine.  It is a
replay/shadow candidate until post-exit production observations prove the result.
"""
from __future__ import annotations

from dataclasses import replace

from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyExitProfile,
    StrategyId,
    UnifiedHoldSellEngine,
)


class Strategy02Ma20HoldCandidateEngine(UnifiedHoldSellEngine):
    """Treat valid rising-MA20 support like MA10 support for the weak 6s gate."""

    def _common_peak_flow_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ):
        candidate_observation = observation
        if (
            state.strategy_id is StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
            and not observation.ma10_support
            and observation.ma20_rising
            and observation.ma20_defense_permit
        ):
            candidate_observation = replace(observation, ma10_support=True)
        return super()._common_peak_flow_exit_rule(
            state, candidate_observation, profile,
        )

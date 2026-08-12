# -*- coding: utf-8 -*-
"""Order-zero S02 exit candidate; deliberately not wired to live execution."""
from __future__ import annotations

from datetime import time
from decimal import Decimal

from strategy_02_ma20_hold_candidate_v1 import (
    Strategy02Ma20HoldCandidateEngine,
)
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyExitProfile,
    StrategyId,
)


class Strategy02ExitCandidateEngine(Strategy02Ma20HoldCandidateEngine):
    """Add a confirmed -1% soft exit when MA structure and buy flow both fail."""

    soft_loss_pct = Decimal("-1.0")
    soft_loss_sell_money_mult = Decimal("2.0")
    soft_loss_confirm_sec = 3
    soft_loss_start_at = time(12, 0)

    def _common_peak_flow_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ):
        return_pct = self._return_pct(state, observation.price)
        soft_loss_setup = bool(
            state.strategy_id is StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
            and observation.observed_at.time() >= self.soft_loss_start_at
            and return_pct <= self.soft_loss_pct
            and observation.daily_ma5_broken
            and observation.structure_broken
            and observation.one_minute_bearish
            and not observation.ma20_defense_permit
            and observation.buy_money_per_sec_10s > 0
            and observation.sell_money_per_sec_10s
            >= observation.buy_money_per_sec_10s
            * self.soft_loss_sell_money_mult
        )
        if soft_loss_setup:
            if state.soft_loss_since is None:
                state.soft_loss_since = observation.observed_at
            age = (
                observation.observed_at - state.soft_loss_since
            ).total_seconds()
            if age >= self.soft_loss_confirm_sec:
                return self._latch(
                    state,
                    observation,
                    HoldSellAction.SELL,
                    "S02_SOFT_LOSS_FLOW_EXIT "
                    f"return={return_pct:.2f}% age={age:.0f}s",
                )
            return self._decision(
                state,
                observation,
                HoldSellAction.WATCH,
                f"S02_SOFT_LOSS_FLOW_WATCH {age:.0f}/"
                f"{self.soft_loss_confirm_sec}s return={return_pct:.2f}%",
            )
        state.soft_loss_since = None
        return super()._common_peak_flow_exit_rule(state, observation, profile)

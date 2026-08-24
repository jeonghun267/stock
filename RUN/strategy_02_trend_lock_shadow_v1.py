# -*- coding: utf-8 -*-
"""Order-zero S02 trend-lock exit shadow."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from strategy_common_hold_sell_v1 import HoldSellConfig, HoldSellObservation


STATE_KEY = "s02_trend_lock_shadow_state"
DONE_KEY = "s02_trend_lock_shadow_done"
STATUS_KEY = "s02_trend_lock_shadow_status"


class Strategy02TrendLockShadow:
    """Observe a stronger exit while the 3-minute MA trend is supported.

    This object has no broker dependency and can only emit telemetry events.
    """

    def __init__(
        self,
        event_sink: Callable[..., None],
        config: Optional[HoldSellConfig] = None,
    ) -> None:
        self.event_sink = event_sink
        self.config = config or HoldSellConfig()
        self.arm_return_pct = Decimal("5")
        self.watch_drop_pct = Decimal("1.5")
        self.required_flow_score = 3
        self.confirm_sec = 6

    def evaluate(
        self,
        position: Dict[str, Any],
        observation: HoldSellObservation,
        *,
        above_ma5_ma10_ma20: bool,
    ) -> None:
        if position.get(DONE_KEY):
            return

        state = position.get(STATE_KEY)
        if not state:
            hold_state = position.get("hold_state") or {}
            if hold_state.get("last_observed_at"):
                position[DONE_KEY] = True
                self._emit(
                    position,
                    observation,
                    "[UNVERIFIED] skipped: shadow started mid-position",
                )
                return
            state = {
                "entry_price": str(position.get("entry_price") or hold_state.get("entry_price") or "0"),
                "peak_price": str(observation.price),
                "watch_since": "",
                "last_observed_at": "",
            }

        last_observed_at = self._parse_dt(state.get("last_observed_at"))
        if last_observed_at and observation.observed_at <= last_observed_at:
            return

        entry_price = Decimal(str(state.get("entry_price") or "0"))
        if entry_price <= 0:
            position[DONE_KEY] = True
            self._emit(position, observation, "[UNVERIFIED] skipped: entry price missing")
            return

        peak_price = max(
            Decimal(str(state.get("peak_price") or "0")), observation.price,
        )
        state["peak_price"] = str(peak_price)
        state["last_observed_at"] = observation.observed_at.isoformat()
        peak_return = (peak_price - entry_price) / entry_price * Decimal("100")
        peak_drop = (peak_price - observation.price) / peak_price * Decimal("100")
        flow_score = self._flow_score(observation)
        setup = bool(
            above_ma5_ma10_ma20
            and peak_return >= self.arm_return_pct
            and peak_drop >= self.watch_drop_pct
            and flow_score >= self.required_flow_score
        )

        if not setup:
            state["watch_since"] = ""
            position[STATE_KEY] = state
            self._status(
                position,
                observation,
                "HOLD",
                f"[HYPOTHETICAL] HOLD peak={peak_return:.2f}% "
                f"drop={peak_drop:.2f}% flow={flow_score}/4 "
                f"ma_all={int(above_ma5_ma10_ma20)}",
            )
            return

        watch_since = self._parse_dt(state.get("watch_since"))
        if watch_since is None:
            watch_since = observation.observed_at
            state["watch_since"] = watch_since.isoformat()
        age = (observation.observed_at - watch_since).total_seconds()
        position[STATE_KEY] = state
        if age < self.confirm_sec:
            self._status(
                position,
                observation,
                "WATCH",
                f"[HYPOTHETICAL] WATCH {age:.0f}/{self.confirm_sec}s "
                f"peak={peak_return:.2f}% drop={peak_drop:.2f}% flow={flow_score}/4",
            )
            return

        position[DONE_KEY] = True
        self._status(
            position,
            observation,
            "SELL",
            f"[HYPOTHETICAL] SELL TREND_LOCK_3M_MA "
            f"peak={peak_return:.2f}% drop={peak_drop:.2f}% "
            f"flow={flow_score}/4 age={age:.0f}s quantity=0",
        )

    def _flow_score(self, observation: HoldSellObservation) -> int:
        sell_money_break = bool(
            observation.buy_money_per_sec_10s > 0
            and observation.sell_money_per_sec_10s
            >= observation.buy_money_per_sec_10s
            * self.config.common_peak_sell_money_mult
        )
        sell_volume_break = bool(
            observation.buy_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_previous_10s > 0
            and observation.sell_volume_per_sec_5s
            >= observation.buy_volume_per_sec_5s
            * self.config.common_peak_sell_volume_mult
            and observation.sell_volume_per_sec_5s
            >= observation.sell_volume_per_sec_previous_10s
            * self.config.common_peak_sell_volume_accel_mult
        )
        buy_fading = bool(
            observation.buy_money_per_sec_30s > 0
            and observation.buy_money_per_sec_10s
            <= observation.buy_money_per_sec_30s
            * self.config.common_peak_buy_fade_mult
        )
        che_falling = bool(
            observation.che_str_change_5s <= -self.config.common_peak_che_drop
        )
        return sum((sell_money_break, sell_volume_break, buy_fading, che_falling))

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _status(
        self,
        position: Dict[str, Any],
        observation: HoldSellObservation,
        status: str,
        reason: str,
    ) -> None:
        if status == position.get(STATUS_KEY) and status != "SELL":
            return
        position[STATUS_KEY] = status
        self._emit(position, observation, reason)

    def _emit(
        self,
        position: Dict[str, Any],
        observation: HoldSellObservation,
        reason: str,
    ) -> None:
        self.event_sink(
            "S02_TREND_LOCK_SHADOW",
            code=str(position.get("code") or "").zfill(6),
            name=str(position.get("name") or ""),
            price=float(observation.price),
            reason=reason,
        )

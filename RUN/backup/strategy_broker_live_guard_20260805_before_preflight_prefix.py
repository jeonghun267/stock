# -*- coding: utf-8 -*-
"""Live-compatible approval/OFF guard for the shared StrategyBroker boundary.

This module does not submit, cancel, or query broker orders.  It only converts
the already-approved daily flag, OFF flag, manual block, and exit-only state
into one fail-closed decision shared by strategies S01 through S06.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from approval_settings_guard import KST, legacy_approval_signals


PREFIX_TO_STRATEGY = {
    "STRATEGY01": "S01",
    "STRATEGY02": "S02",
    "STRATEGY03": "S03",
    "STRATEGY04": "S04",
    "STRATEGY05": "S05",
    "STRATEGY06": "S06",
}


@dataclass(frozen=True)
class LiveGuardDecision:
    strategy_id: str
    approval_valid: bool
    real_session: bool
    buy_allowed: bool


class StrategyBrokerLiveGuard:
    """Evaluate existing live gates without changing trading parameters."""

    def __init__(self, *, order_prefix: str) -> None:
        self.order_prefix = str(order_prefix or "").strip().upper()
        self.strategy_id = PREFIX_TO_STRATEGY.get(self.order_prefix, "")

    @staticmethod
    def _as_kst(value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.now(KST)
        if value.tzinfo is None:
            return value.replace(tzinfo=KST)
        return value.astimezone(KST)

    def evaluate(
        self,
        *,
        approval_path: Path,
        off_flag_path: Path,
        manual_buy_block_path: Path,
        live_requested: bool,
        force_exit_only: bool,
        now: Optional[datetime] = None,
    ) -> LiveGuardDecision:
        if not self.strategy_id:
            return LiveGuardDecision("", False, False, False)
        try:
            approval_text = Path(approval_path).read_text(
                encoding="ascii", errors="strict"
            )
        except (OSError, UnicodeError):
            approval_text = ""
        signals = legacy_approval_signals(
            approval_text=approval_text,
            now_kst=self._as_kst(now),
            live_requested=bool(live_requested),
            force_exit_only=bool(force_exit_only),
            off_flag_exists=Path(off_flag_path).exists(),
            manual_block_exists=Path(manual_buy_block_path).exists(),
        )
        return LiveGuardDecision(
            strategy_id=self.strategy_id,
            approval_valid=signals.approval_valid,
            real_session=signals.real_session_signal,
            buy_allowed=signals.buy_allowed_signal,
        )

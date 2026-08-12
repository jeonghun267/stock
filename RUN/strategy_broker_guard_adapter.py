# -*- coding: utf-8 -*-
"""기존 StrategyBroker 공통 주문 경계가 호출할 staging 어댑터.

운영 모듈을 import하거나 주문을 전송하지 않는다. 시작과 submit 직전에 같은
ApprovalSettingsGuard를 호출하는 최소 연결면만 제공한다.
"""
from __future__ import annotations

from approval_settings_guard import (
    ApprovalSettingsGuard,
    GuardSnapshot,
    PreOrderDecision,
    PreOrderRequest,
    RecoveryStatus,
    StartRequest,
)


CONNECTION_ROUTES = {
    "S01": "S01_DIRECT_TO_COMMON_BROKER",
    "S02": "S01_ENGINE_TO_COMMON_BROKER",
    "S03": "S01_ENGINE_TO_COMMON_BROKER",
    "S04": "S01_ENGINE_TO_COMMON_BROKER",
    "S05": "S01_ENGINE_TO_COMMON_BROKER",
    "S06": "S06_DIRECT_TO_COMMON_BROKER",
}


class StrategyBrokerGuardAdapter:
    def __init__(self, guard: ApprovalSettingsGuard) -> None:
        self.guard = guard

    @staticmethod
    def connection_route(strategy_id: str) -> str:
        return CONNECTION_ROUTES.get(str(strategy_id).strip().upper(), "UNSUPPORTED")

    def startup_check(self, request: StartRequest) -> GuardSnapshot:
        return self.guard.startup_check(request)

    def pre_submit_check(
        self, snapshot: GuardSnapshot, request: PreOrderRequest
    ) -> PreOrderDecision:
        return self.guard.preorder_check(snapshot, request)

    def complete_dry_run(self, intent_id: str, receipt_ref: str) -> None:
        self.guard.complete_dry_run(intent_id, receipt_ref)

    def mark_dry_run_unknown(self, intent_id: str, reason_ref: str) -> None:
        self.guard.mark_dry_run_unknown(intent_id, reason_ref)

    def recovery_status(self, intent_id: str) -> RecoveryStatus:
        return self.guard.recovery_status(intent_id)

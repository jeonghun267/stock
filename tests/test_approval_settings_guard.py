# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import itertools
import json
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from approval_settings_guard import (  # noqa: E402
    ApprovalRecord,
    ApprovalSettingsGuard,
    ApprovalState,
    ChangeEntry,
    ConfigBundle,
    ConfigItem,
    GuardDenied,
    GuardPolicy,
    GuardResult,
    KST,
    PreOrderRequest,
    RecoveryStatus,
    StartRequest,
    SyntheticIntentState,
    legacy_approval_signals,
    legacy_daily_approval_valid,
)
from strategy_broker_guard_adapter import StrategyBrokerGuardAdapter  # noqa: E402


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=KST)
KEYS = (
    "synthetic.rule",
    "synthetic.cost.commission",
    "synthetic.cost.tax",
    "synthetic.cost.spread",
    "synthetic.cost.slippage",
)
SCOPE = frozenset({"S01", "S02", "S03", "S04", "S05", "S06", "DRY_RUN"})


def digest_of(bundle: ConfigBundle) -> str:
    """synthetic 테스트용이며 운영 해시·저장 형식을 확정하지 않는다."""
    payload = {
        "version": bundle.version_id,
        "parent": bundle.parent_version_id,
        "items": [
            [item.key, item.value, item.value_type, item.unit, item.meaning,
             sorted(item.scope), item.required, item.validator_ref, item.source_ref]
            for item in bundle.items
        ],
        "scope": sorted(bundle.effective_scope),
        "created_by": bundle.created_by,
        "created_at": bundle.created_at_kst.isoformat(),
        "reason": bundle.change_reason,
        "impact": bundle.impact_summary,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_bundle(
    version_id="synthetic-v2",
    parent="synthetic-v1",
    state=ApprovalState.APPROVED,
):
    items = tuple(ConfigItem(
        key=key,
        value=f"SYNTHETIC:{key}",
        value_type="synthetic-text",
        unit="synthetic-unit",
        meaning="synthetic test only",
        scope=SCOPE,
        required=True,
        validator_ref="synthetic.nonempty",
        source_ref="synthetic-test",
    ) for key in KEYS)
    draft = ConfigBundle(
        version_id=version_id,
        parent_version_id=parent,
        digest="PENDING",
        items=items,
        state=state,
        effective_scope=SCOPE,
        created_by="synthetic-proposer",
        created_at_kst=NOW - timedelta(minutes=5),
        change_reason="synthetic change",
        impact_summary="synthetic test only",
    )
    return replace(draft, digest=digest_of(draft))


def make_approval(
    bundle,
    state=ApprovalState.APPROVED,
    basis=("synthetic-evidence",),
):
    return ApprovalRecord(
        decision_id=f"decision-{bundle.version_id}",
        version_id=bundle.version_id,
        digest=bundle.digest,
        state=state,
        approver="synthetic-owner",
        authority="synthetic-test",
        basis_refs=basis,
        approved_at_kst=NOW - timedelta(minutes=1),
        approved_scope=SCOPE,
    )


def make_history(bundle, approval):
    if bundle.parent_version_id is None:
        return ()
    return (ChangeEntry(
        change_id=f"change-{bundle.version_id}",
        from_version_id=bundle.parent_version_id,
        to_version_id=bundle.version_id,
        before_digest="synthetic-before",
        after_digest=bundle.digest,
        changed_keys=("synthetic.rule",),
        actor="synthetic-proposer",
        reason="synthetic change",
        changed_at_kst=NOW - timedelta(minutes=3),
        approval_decision_ref=approval.decision_id,
    ),)


class Fixture:
    def __init__(self, audit_ok=True):
        self.bundle = make_bundle()
        self.approval = make_approval(self.bundle)
        self.history = make_history(self.bundle, self.approval)
        self.state = SyntheticIntentState()
        self.audit_ok = audit_ok
        self.audit_events = []
        ids = itertools.count(1)
        self.guard = ApprovalSettingsGuard(
            policy=GuardPolicy(
                approved_non_live_modes=frozenset({"DRY_RUN"}),
                required_keys=frozenset(KEYS),
                cost_key_by_role={
                    "commission": "synthetic.cost.commission",
                    "tax": "synthetic.cost.tax",
                    "spread": "synthetic.cost.spread",
                    "slippage": "synthetic.cost.slippage",
                },
                validators={
                    "synthetic.nonempty": lambda item: bool(str(item.value).strip())
                },
            ),
            active_bundle=lambda _strategy: self.bundle,
            approval_for=lambda version: (
                self.approval if version == self.approval.version_id else None
            ),
            history_for=lambda version: (
                self.history if version == self.bundle.version_id else ()
            ),
            digest_of=digest_of,
            intent_state=self.state,
            audit_sink=self._audit,
            clock=lambda: NOW,
            id_factory=lambda: f"synthetic-id-{next(ids)}",
        )
        self.adapter = StrategyBrokerGuardAdapter(self.guard)

    def _audit(self, event):
        self.audit_events.append(event)
        return self.audit_ok

    def refresh(self):
        self.approval = make_approval(self.bundle)
        self.history = make_history(self.bundle, self.approval)

    def start_request(
        self, strategy="S01", mode="DRY_RUN", trading=True, session=True
    ):
        return StartRequest(
            run_id=f"run-{strategy}",
            strategy_id=strategy,
            mode=mode,
            checked_at_kst=NOW,
            trading_day_verified=trading,
            session_open_verified=session,
            calendar_evidence_ref="synthetic-calendar",
            data_cutoff_kst=NOW - timedelta(seconds=2),
        )

    def preorder(self, snapshot, intent="intent-1", available_at=None, costs=None):
        decision_at = NOW - timedelta(seconds=1)
        return PreOrderRequest(
            strategy_id=snapshot.strategy_id,
            mode=snapshot.mode,
            intent_id=intent,
            deduplication_key=f"dedupe-{intent}",
            intent_fingerprint=f"fingerprint-{intent}",
            side="BUY",
            checked_at_kst=NOW,
            trading_day_verified=True,
            session_open_verified=True,
            calendar_evidence_ref="synthetic-calendar",
            decision_at_kst=decision_at,
            data_observed_at_kst=decision_at - timedelta(seconds=2),
            data_available_at_kst=(
                available_at
                if available_at is not None
                else decision_at - timedelta(seconds=1)
            ),
            data_evidence_ref="synthetic-data",
            cost_version_id=snapshot.version_id,
            cost_digest=snapshot.digest,
            cost_evidence_refs=(
                costs
                if costs is not None
                else {
                    "commission": "synthetic-proof",
                    "tax": "synthetic-proof",
                    "spread": "synthetic-proof",
                    "slippage": "synthetic-proof",
                }
            ),
            unresolved_check_ref="synthetic-state-check",
        )


class GuardTests(unittest.TestCase):
    def denied(self, code, call):
        with self.assertRaises(GuardDenied) as raised:
            call()
        self.assertIn(code, raised.exception.reason_codes)

    def connection(self, strategy, route):
        fx = Fixture()
        snapshot = fx.adapter.startup_check(fx.start_request(strategy))
        request = fx.preorder(snapshot, f"intent-{strategy}")
        decision = fx.adapter.pre_submit_check(snapshot, request)
        self.assertEqual(GuardResult.ALLOW_SIMULATED_ONLY, decision.result)
        self.assertEqual(route, fx.adapter.connection_route(strategy))
        fx.adapter.complete_dry_run(request.intent_id, "synthetic-receipt")
        self.assertEqual(
            RecoveryStatus.RECONCILED_FINAL,
            fx.adapter.recovery_status(request.intent_id),
        )

    def test_s01_connection(self):
        self.connection("S01", "S01_DIRECT_TO_COMMON_BROKER")

    def test_s02_connection(self):
        self.connection("S02", "S01_ENGINE_TO_COMMON_BROKER")

    def test_s03_connection(self):
        self.connection("S03", "S01_ENGINE_TO_COMMON_BROKER")

    def test_s04_connection(self):
        self.connection("S04", "S01_ENGINE_TO_COMMON_BROKER")

    def test_s05_connection(self):
        self.connection("S05", "S01_ENGINE_TO_COMMON_BROKER")

    def test_s06_connection(self):
        self.connection("S06", "S06_DIRECT_TO_COMMON_BROKER")

    def test_pending_and_rejected_fail_closed(self):
        for state, code in (
            (ApprovalState.PENDING, "CONFIG_APPROVAL_PENDING"),
            (ApprovalState.REJECTED, "CONFIG_REJECTED"),
        ):
            with self.subTest(state=state):
                fx = Fixture()
                fx.bundle = replace(fx.bundle, state=state)
                fx.approval = make_approval(fx.bundle, state)
                fx.history = make_history(fx.bundle, fx.approval)
                self.denied(
                    code,
                    lambda: fx.adapter.startup_check(fx.start_request()),
                )

    def test_missing_value_has_no_default(self):
        fx = Fixture()
        items = tuple(
            replace(item, value="") if item.key == "synthetic.rule" else item
            for item in fx.bundle.items
        )
        draft = replace(fx.bundle, items=items, digest="PENDING")
        fx.bundle = replace(draft, digest=digest_of(draft))
        fx.refresh()
        self.denied(
            "CONFIG_ITEM_INCOMPLETE:synthetic.rule",
            lambda: fx.adapter.startup_check(fx.start_request()),
        )

    def test_tamper_is_blocked(self):
        fx = Fixture()
        fx.bundle = replace(fx.bundle, items=tuple(
            replace(item, value="TAMPERED")
            if item.key == "synthetic.rule"
            else item
            for item in fx.bundle.items
        ))
        self.denied(
            "CONFIG_DIGEST_MISMATCH",
            lambda: fx.adapter.startup_check(fx.start_request()),
        )

    def test_version_change_is_blocked_preorder(self):
        fx = Fixture()
        snapshot = fx.adapter.startup_check(fx.start_request())
        fx.bundle = make_bundle("synthetic-v3", "synthetic-v2")
        fx.refresh()
        self.denied(
            "CONFIG_VERSION_CHANGED",
            lambda: fx.adapter.pre_submit_check(snapshot, fx.preorder(snapshot)),
        )

    def test_approval_evidence_and_history_are_required(self):
        fx = Fixture()
        fx.approval = make_approval(fx.bundle, basis=())
        fx.history = ()
        with self.assertRaises(GuardDenied) as raised:
            fx.adapter.startup_check(fx.start_request())
        self.assertIn("APPROVAL_EVIDENCE_MISSING", raised.exception.reason_codes)
        self.assertIn("CHANGE_HISTORY_MISSING", raised.exception.reason_codes)

    def test_live_mode_is_blocked(self):
        fx = Fixture()
        self.denied(
            "REAL_ACCOUNT_FORBIDDEN",
            lambda: fx.adapter.startup_check(fx.start_request(mode="LIVE")),
        )

    def test_kst_trading_day_and_session_checks_fail_closed(self):
        fx = Fixture()
        with self.assertRaises(GuardDenied) as raised:
            fx.adapter.startup_check(fx.start_request(trading=False, session=None))
        self.assertIn("TRADING_DAY_NOT_VERIFIED", raised.exception.reason_codes)
        self.assertIn("SESSION_NOT_VERIFIED", raised.exception.reason_codes)

    def test_lookahead_is_blocked(self):
        fx = Fixture()
        snapshot = fx.adapter.startup_check(fx.start_request())
        request = fx.preorder(snapshot, available_at=NOW)
        self.denied(
            "LOOKAHEAD_UNAVAILABLE_DATA",
            lambda: fx.adapter.pre_submit_check(snapshot, request),
        )

    def test_all_four_cost_evidences_are_required(self):
        fx = Fixture()
        snapshot = fx.adapter.startup_check(fx.start_request())
        request = fx.preorder(snapshot, costs={
            "commission": "proof",
            "tax": "proof",
            "spread": "proof",
        })
        self.denied(
            "COST_EVIDENCE_MISSING:slippage",
            lambda: fx.adapter.pre_submit_check(snapshot, request),
        )

    def test_duplicate_and_unknown_recovery_fail_closed(self):
        fx = Fixture()
        snapshot = fx.adapter.startup_check(fx.start_request())
        request = fx.preorder(snapshot)
        fx.adapter.pre_submit_check(snapshot, request)
        self.denied(
            "DUPLICATE_ORDER",
            lambda: fx.adapter.pre_submit_check(snapshot, request),
        )
        fx.adapter.mark_dry_run_unknown(request.intent_id, "synthetic-timeout")
        self.assertEqual(
            RecoveryStatus.RECONCILIATION_REQUIRED,
            fx.adapter.recovery_status(request.intent_id),
        )
        self.denied(
            "RECOVERY_REQUIRED",
            lambda: fx.adapter.startup_check(fx.start_request()),
        )

    def test_audit_failure_fails_closed(self):
        fx = Fixture(audit_ok=False)
        self.denied(
            "AUDIT_WRITE_FAILED",
            lambda: fx.adapter.startup_check(fx.start_request()),
        )

    def test_legacy_today_future_past_regression(self):
        today = f"APPROVED_BY_OWNER {NOW:%Y%m%d} 09:59:59"
        future = f"APPROVED_BY_OWNER {NOW:%Y%m%d} 10:05:00"
        past = f"APPROVED_BY_OWNER {(NOW - timedelta(days=1)):%Y%m%d} 09:59:59"
        self.assertTrue(legacy_daily_approval_valid(today, NOW))
        self.assertFalse(legacy_daily_approval_valid(future, NOW))
        self.assertFalse(legacy_daily_approval_valid(past, NOW))

    def test_legacy_exit_only_blocks_buy(self):
        signals = legacy_approval_signals(
            approval_text=f"APPROVED_BY_OWNER {NOW:%Y%m%d} 09:59:59",
            now_kst=NOW,
            live_requested=True,
            force_exit_only=True,
            off_flag_exists=False,
            manual_block_exists=False,
        )
        self.assertTrue(signals.real_session_signal)
        self.assertFalse(signals.buy_allowed_signal)


if __name__ == "__main__":
    unittest.main()

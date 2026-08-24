# -*- coding: utf-8 -*-
"""승인·설정 안전관리 단일 관문.

운영 설정값·저장 형식·전략 계산식·브로커 연결을 포함하지 않는다.
모든 허가는 mock/dry-run에만 한정되며 나머지는 fail-closed 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Collection, Mapping, Optional, Sequence


KST = timezone(timedelta(hours=9), name="KST")
SUPPORTED_STRATEGIES = frozenset({"S01", "S02", "S03", "S04", "S05", "S06"})
COST_ROLES = ("commission", "tax", "spread", "slippage")


class ApprovalState(str, Enum):
    PENDING = "승인 대기"
    APPROVED = "승인됨"
    REJECTED = "거부됨"


class GuardResult(str, Enum):
    ALLOW_SIMULATED_ONLY = "ALLOW_SIMULATED_ONLY"
    DENY = "DENY"


class RecoveryStatus(str, Enum):
    RECONCILED_FINAL = "RECONCILED_FINAL"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    MANUAL_DECISION_REQUIRED = "MANUAL_DECISION_REQUIRED"


class GuardDenied(RuntimeError):
    def __init__(self, stage: str, reason_codes: Collection[str]) -> None:
        self.stage = stage
        self.reason_codes = tuple(dict.fromkeys(code for code in reason_codes if code))
        if not self.reason_codes:
            self.reason_codes = ("UNSPECIFIED_DENY",)
        super().__init__(f"{stage}: {','.join(self.reason_codes)}")


@dataclass(frozen=True)
class ConfigItem:
    key: str
    value: Any
    value_type: str
    unit: str
    meaning: str
    scope: frozenset[str]
    required: bool
    validator_ref: str
    source_ref: str


@dataclass(frozen=True)
class ConfigBundle:
    version_id: str
    parent_version_id: Optional[str]
    digest: str
    items: tuple[ConfigItem, ...]
    state: ApprovalState
    effective_scope: frozenset[str]
    created_by: str
    created_at_kst: datetime
    change_reason: str
    impact_summary: str


@dataclass(frozen=True)
class ApprovalRecord:
    decision_id: str
    version_id: str
    digest: str
    state: ApprovalState
    approver: str
    authority: str
    basis_refs: tuple[str, ...]
    approved_at_kst: datetime
    approved_scope: frozenset[str]


@dataclass(frozen=True)
class ChangeEntry:
    change_id: str
    from_version_id: str
    to_version_id: str
    before_digest: str
    after_digest: str
    changed_keys: tuple[str, ...]
    actor: str
    reason: str
    changed_at_kst: datetime
    approval_decision_ref: str


@dataclass(frozen=True)
class GuardPolicy:
    approved_non_live_modes: frozenset[str]
    required_keys: frozenset[str]
    cost_key_by_role: Mapping[str, str]
    validators: Mapping[str, Callable[[ConfigItem], bool]]


@dataclass(frozen=True)
class StartRequest:
    run_id: str
    strategy_id: str
    mode: str
    checked_at_kst: datetime
    trading_day_verified: Optional[bool]
    session_open_verified: Optional[bool]
    calendar_evidence_ref: str
    data_cutoff_kst: datetime


@dataclass(frozen=True)
class GuardSnapshot:
    run_id: str
    strategy_id: str
    mode: str
    version_id: str
    digest: str
    approval_decision_id: str
    checked_at_kst: datetime
    items: tuple[ConfigItem, ...]


@dataclass(frozen=True)
class PreOrderRequest:
    strategy_id: str
    mode: str
    intent_id: str
    deduplication_key: str
    intent_fingerprint: str
    side: str
    checked_at_kst: datetime
    trading_day_verified: Optional[bool]
    session_open_verified: Optional[bool]
    calendar_evidence_ref: str
    decision_at_kst: datetime
    data_observed_at_kst: datetime
    data_available_at_kst: datetime
    data_evidence_ref: str
    cost_version_id: str
    cost_digest: str
    cost_evidence_refs: Mapping[str, str]
    unresolved_check_ref: str


@dataclass(frozen=True)
class PreOrderDecision:
    decision_id: str
    checked_at_kst: datetime
    run_id: str
    version_id: str
    digest: str
    intent_id: str
    deduplication_key: str
    result: GuardResult
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class LegacyApprovalSignals:
    approval_valid: bool
    real_session_signal: bool
    buy_allowed_signal: bool


class SyntheticIntentState:
    """mock/dry-run 전용 상태. 운영 저장 형식은 승인 필요 상태로 남긴다."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, str] = {}
        self._intent_by_key: dict[str, str] = {}

    def has_unresolved(self) -> bool:
        with self._lock:
            return any(state in {"PENDING", "UNKNOWN"} for state in self._records.values())

    def reserve(self, intent_id: str, deduplication_key: str) -> str:
        with self._lock:
            if intent_id in self._records or deduplication_key in self._intent_by_key:
                return "DUPLICATE"
            if any(state in {"PENDING", "UNKNOWN"} for state in self._records.values()):
                return "UNRESOLVED"
            self._records[intent_id] = "PENDING"
            self._intent_by_key[deduplication_key] = intent_id
            return "RESERVED"

    def complete(self, intent_id: str, outcome_ref: str) -> bool:
        if not _present(outcome_ref):
            return False
        with self._lock:
            if self._records.get(intent_id) != "PENDING":
                return False
            self._records[intent_id] = "FINAL"
            return True

    def mark_unknown(self, intent_id: str, reason_ref: str) -> bool:
        if not _present(reason_ref):
            return False
        with self._lock:
            if self._records.get(intent_id) not in {"PENDING", "UNKNOWN"}:
                return False
            self._records[intent_id] = "UNKNOWN"
            return True

    def recovery_status(self, intent_id: str) -> RecoveryStatus:
        with self._lock:
            state = self._records.get(intent_id)
            if state == "FINAL":
                return RecoveryStatus.RECONCILED_FINAL
            if state in {"PENDING", "UNKNOWN"}:
                return RecoveryStatus.RECONCILIATION_REQUIRED
            return RecoveryStatus.MANUAL_DECISION_REQUIRED


class ApprovalSettingsGuard:
    """시작 검사와 주문 직전 재검사를 같은 승인 묶음에 고정한다."""

    def __init__(
        self,
        *,
        policy: GuardPolicy,
        active_bundle: Callable[[str], ConfigBundle],
        approval_for: Callable[[str], Optional[ApprovalRecord]],
        history_for: Callable[[str], Sequence[ChangeEntry]],
        digest_of: Callable[[ConfigBundle], str],
        intent_state: SyntheticIntentState,
        audit_sink: Callable[[Mapping[str, Any]], bool],
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._modes = frozenset(_token(mode) for mode in policy.approved_non_live_modes)
        if not self._modes or any(_real_mode(mode) for mode in self._modes):
            raise ValueError("approved modes must be explicit and non-live")
        self._required_keys = frozenset(str(key).strip() for key in policy.required_keys)
        self._cost_keys = dict(policy.cost_key_by_role)
        self._validators = dict(policy.validators)
        if not self._required_keys or "" in self._required_keys:
            raise ValueError("required settings must be explicit")
        if set(self._cost_keys) != set(COST_ROLES):
            raise ValueError("four cost roles must be explicit")
        if any(not _present(key) for key in self._cost_keys.values()):
            raise ValueError("cost setting keys must be explicit")
        if not set(self._cost_keys.values()).issubset(self._required_keys):
            raise ValueError("cost settings must be required settings")
        if not self._validators:
            raise ValueError("validators must be explicit")
        self._active_bundle = active_bundle
        self._approval_for = approval_for
        self._history_for = history_for
        self._digest_of = digest_of
        self._intent_state = intent_state
        self._audit_sink = audit_sink
        self._clock = clock
        self._id_factory = id_factory

    def startup_check(self, request: StartRequest) -> GuardSnapshot:
        now, errors = self._now()
        strategy = _token(request.strategy_id)
        mode = _token(request.mode)
        errors.extend(self._context_errors(
            strategy, mode, request.checked_at_kst,
            request.trading_day_verified, request.session_open_verified,
            request.calendar_evidence_ref, now,
        ))
        if not _present(request.run_id):
            errors.append("RUN_ID_MISSING")
        if not _kst(request.data_cutoff_kst):
            errors.append("DATA_CUTOFF_NOT_KST")
        elif request.data_cutoff_kst > now:
            errors.append("DATA_CUTOFF_IN_FUTURE")
        try:
            if self._intent_state.has_unresolved():
                errors.append("RECOVERY_REQUIRED")
        except Exception:
            errors.append("INTENT_STATE_UNAVAILABLE")
        bundle, approval, digest, bundle_errors = self._load_validated(strategy, mode, now)
        errors.extend(bundle_errors)
        refs = {"run_id": request.run_id, "strategy": strategy}
        if errors or bundle is None or approval is None or digest is None:
            self._deny("STARTUP", errors, now, refs)
        snapshot = GuardSnapshot(
            run_id=request.run_id,
            strategy_id=strategy,
            mode=mode,
            version_id=bundle.version_id,
            digest=digest,
            approval_decision_id=approval.decision_id,
            checked_at_kst=now,
            items=tuple(bundle.items),
        )
        if not self._audit("STARTUP", GuardResult.ALLOW_SIMULATED_ONLY,
                           ("STARTUP_VALIDATED",), now, refs):
            self._deny("STARTUP", ("AUDIT_WRITE_FAILED",), now, refs)
        return snapshot

    def preorder_check(
        self, snapshot: GuardSnapshot, request: PreOrderRequest
    ) -> PreOrderDecision:
        now, errors = self._now()
        strategy = _token(request.strategy_id)
        mode = _token(request.mode)
        errors.extend(self._context_errors(
            strategy, mode, request.checked_at_kst,
            request.trading_day_verified, request.session_open_verified,
            request.calendar_evidence_ref, now,
        ))
        if snapshot.strategy_id != strategy or snapshot.mode != mode:
            errors.append("SNAPSHOT_CONTEXT_MISMATCH")
        for value, code in (
            (request.intent_id, "INTENT_ID_MISSING"),
            (request.deduplication_key, "DEDUPLICATION_KEY_MISSING"),
            (request.intent_fingerprint, "INTENT_FINGERPRINT_MISSING"),
            (request.data_evidence_ref, "DATA_EVIDENCE_MISSING"),
            (request.unresolved_check_ref, "UNRESOLVED_CHECK_MISSING"),
        ):
            if not _present(value):
                errors.append(code)
        if _token(request.side) not in {"BUY", "SELL"}:
            errors.append("ORDER_SIDE_INVALID")
        data_times = (
            request.decision_at_kst,
            request.data_observed_at_kst,
            request.data_available_at_kst,
        )
        if any(not _kst(value) for value in data_times):
            errors.append("DATA_TIME_NOT_KST")
        else:
            if request.decision_at_kst > now:
                errors.append("DECISION_IN_FUTURE")
            if request.data_observed_at_kst > request.decision_at_kst:
                errors.append("LOOKAHEAD_OBSERVED_DATA")
            if request.data_available_at_kst > request.decision_at_kst:
                errors.append("LOOKAHEAD_UNAVAILABLE_DATA")
        if request.cost_version_id != snapshot.version_id:
            errors.append("COST_VERSION_MISMATCH")
        if request.cost_digest != snapshot.digest:
            errors.append("COST_DIGEST_MISMATCH")
        for role in COST_ROLES:
            if not _present(request.cost_evidence_refs.get(role)):
                errors.append(f"COST_EVIDENCE_MISSING:{role}")

        bundle, approval, digest, bundle_errors = self._load_validated(strategy, mode, now)
        errors.extend(bundle_errors)
        if bundle is not None and bundle.version_id != snapshot.version_id:
            errors.append("CONFIG_VERSION_CHANGED")
        if digest is not None and digest != snapshot.digest:
            errors.append("CONFIG_DIGEST_CHANGED")
        if approval is not None and approval.decision_id != snapshot.approval_decision_id:
            errors.append("APPROVAL_DECISION_CHANGED")
        refs = {"run_id": snapshot.run_id, "strategy": strategy, "intent": request.intent_id}
        if errors:
            self._deny("PRE_ORDER", errors, now, refs)
        try:
            reservation = self._intent_state.reserve(
                request.intent_id, request.deduplication_key
            )
        except Exception:
            reservation = "ERROR"
        if reservation == "DUPLICATE":
            self._deny("PRE_ORDER", ("DUPLICATE_ORDER",), now, refs)
        if reservation == "UNRESOLVED":
            self._deny("PRE_ORDER", ("RECOVERY_REQUIRED",), now, refs)
        if reservation != "RESERVED":
            self._deny("PRE_ORDER", ("INTENT_RESERVATION_FAILED",), now, refs)
        decision = PreOrderDecision(
            decision_id=self._id(),
            checked_at_kst=now,
            run_id=snapshot.run_id,
            version_id=snapshot.version_id,
            digest=snapshot.digest,
            intent_id=request.intent_id,
            deduplication_key=request.deduplication_key,
            result=GuardResult.ALLOW_SIMULATED_ONLY,
            reason_codes=("ALL_CHECKS_PASSED",),
        )
        if not self._audit("PRE_ORDER", decision.result, decision.reason_codes, now, refs):
            self._intent_state.mark_unknown(request.intent_id, "AUDIT_WRITE_FAILED")
            self._deny("PRE_ORDER", ("AUDIT_WRITE_FAILED",), now, refs)
        return decision

    def complete_dry_run(self, intent_id: str, outcome_ref: str) -> None:
        if not self._intent_state.complete(intent_id, outcome_ref):
            raise GuardDenied("RECOVERY", ("FINAL_STATE_UNPROVEN",))

    def mark_dry_run_unknown(self, intent_id: str, reason_ref: str) -> None:
        if not self._intent_state.mark_unknown(intent_id, reason_ref):
            raise GuardDenied("RECOVERY", ("RECOVERY_STATE_WRITE_FAILED",))

    def recovery_status(self, intent_id: str) -> RecoveryStatus:
        try:
            return self._intent_state.recovery_status(intent_id)
        except Exception:
            return RecoveryStatus.MANUAL_DECISION_REQUIRED

    def _load_validated(self, strategy: str, mode: str, now: datetime):
        errors: list[str] = []
        try:
            bundle = self._active_bundle(strategy)
        except Exception:
            return None, None, None, ["ACTIVE_CONFIG_UNAVAILABLE"]
        if not isinstance(bundle, ConfigBundle):
            return None, None, None, ["ACTIVE_CONFIG_INVALID"]
        try:
            digest = str(self._digest_of(bundle)).strip()
        except Exception:
            digest = ""
        if not digest or digest != bundle.digest:
            errors.append("CONFIG_DIGEST_MISMATCH")
        if bundle.state == ApprovalState.PENDING:
            errors.append("CONFIG_APPROVAL_PENDING")
        elif bundle.state == ApprovalState.REJECTED:
            errors.append("CONFIG_REJECTED")
        elif bundle.state != ApprovalState.APPROVED:
            errors.append("CONFIG_APPROVAL_INVALID")
        if not _scope(bundle.effective_scope, strategy, mode):
            errors.append("CONFIG_SCOPE_MISMATCH")
        if not _kst(bundle.created_at_kst) or bundle.created_at_kst > now:
            errors.append("CONFIG_TIME_INVALID")
        for value, code in (
            (bundle.version_id, "VERSION_ID_MISSING"),
            (bundle.created_by, "CONFIG_CREATOR_MISSING"),
            (bundle.change_reason, "CHANGE_REASON_MISSING"),
            (bundle.impact_summary, "IMPACT_SUMMARY_MISSING"),
        ):
            if not _present(value):
                errors.append(code)
        items: dict[str, ConfigItem] = {}
        for item in bundle.items:
            if not isinstance(item, ConfigItem):
                errors.append("CONFIG_ITEM_TYPE_INVALID")
                continue
            if item.key in items:
                errors.append("CONFIG_ITEM_DUPLICATE")
            items[item.key] = item
            if any(not _present(value) for value in (
                item.key, item.value_type, item.unit, item.meaning,
                item.validator_ref, item.source_ref,
            )) or _missing_value(item.value) or not item.scope:
                errors.append(f"CONFIG_ITEM_INCOMPLETE:{item.key}")
            validator = self._validators.get(item.validator_ref)
            try:
                valid = validator is not None and validator(item) is True
            except Exception:
                valid = False
            if not valid:
                errors.append(f"CONFIG_ITEM_INVALID:{item.key}")
        for key in sorted(self._required_keys):
            if key not in items:
                errors.append(f"REQUIRED_CONFIG_MISSING:{key}")
            elif items[key].required is not True:
                errors.append(f"REQUIRED_FLAG_MISMATCH:{key}")

        try:
            approval = self._approval_for(bundle.version_id)
        except Exception:
            approval = None
        if not isinstance(approval, ApprovalRecord):
            errors.append("APPROVAL_MISSING")
            return bundle, None, digest or None, errors
        if approval.state == ApprovalState.PENDING:
            errors.append("APPROVAL_PENDING")
        elif approval.state == ApprovalState.REJECTED:
            errors.append("APPROVAL_REJECTED")
        elif approval.state != ApprovalState.APPROVED:
            errors.append("APPROVAL_INVALID")
        if approval.version_id != bundle.version_id or approval.digest != digest:
            errors.append("APPROVAL_VERSION_OR_DIGEST_MISMATCH")
        if (
            any(not _present(value) for value in (
                approval.decision_id, approval.approver, approval.authority,
            ))
            or not approval.basis_refs
            or any(not _present(ref) for ref in approval.basis_refs)
        ):
            errors.append("APPROVAL_EVIDENCE_MISSING")
        if not _kst(approval.approved_at_kst) or approval.approved_at_kst > now:
            errors.append("APPROVAL_TIME_INVALID")
        if not _scope(approval.approved_scope, strategy, mode):
            errors.append("APPROVAL_SCOPE_MISMATCH")

        try:
            history = tuple(self._history_for(bundle.version_id))
        except Exception:
            history = ()
        if bundle.parent_version_id is not None:
            matches = [entry for entry in history if (
                isinstance(entry, ChangeEntry)
                and entry.from_version_id == bundle.parent_version_id
                and entry.to_version_id == bundle.version_id
            )]
            if len(matches) != 1:
                errors.append("CHANGE_HISTORY_MISSING")
            else:
                entry = matches[0]
                if (
                    not _present(entry.change_id)
                    or not entry.before_digest
                    or entry.after_digest != digest
                    or not entry.changed_keys
                    or not _present(entry.actor)
                    or not _present(entry.reason)
                    or not _kst(entry.changed_at_kst)
                    or entry.changed_at_kst > approval.approved_at_kst
                    or entry.approval_decision_ref != approval.decision_id
                ):
                    errors.append("CHANGE_HISTORY_INVALID")
        return bundle, approval, digest or None, errors

    def _context_errors(self, strategy, mode, checked_at, trading_day,
                        session_open, evidence_ref, now):
        errors: list[str] = []
        if strategy not in SUPPORTED_STRATEGIES:
            errors.append("STRATEGY_NOT_SUPPORTED")
        if _real_mode(mode):
            errors.append("REAL_ACCOUNT_FORBIDDEN")
        if mode not in self._modes:
            errors.append("MODE_NOT_APPROVED")
        if not _kst(checked_at) or checked_at > now:
            errors.append("KST_CHECK_INVALID")
        if trading_day is not True:
            errors.append("TRADING_DAY_NOT_VERIFIED")
        if session_open is not True:
            errors.append("SESSION_NOT_VERIFIED")
        if not _present(evidence_ref):
            errors.append("CALENDAR_EVIDENCE_MISSING")
        return errors

    def _now(self):
        try:
            now = self._clock()
        except Exception:
            return datetime.min.replace(tzinfo=KST), ["CLOCK_UNAVAILABLE"]
        if not _kst(now):
            return datetime.min.replace(tzinfo=KST), ["CLOCK_NOT_KST"]
        return now, []

    def _id(self) -> str:
        value = str(self._id_factory()).strip()
        if not value:
            raise GuardDenied("IDENTIFIER", ("IDENTIFIER_MISSING",))
        return value

    def _audit(self, stage, result, reasons, now, refs) -> bool:
        try:
            return self._audit_sink({
                "event_id": self._id(),
                "occurred_at_kst": now,
                "stage": stage,
                "result": result.value,
                "reason_codes": tuple(reasons),
                "references": dict(refs),
            }) is True
        except Exception:
            return False

    def _deny(self, stage, reasons, now, refs):
        codes = list(dict.fromkeys(code for code in reasons if code)) or ["UNSPECIFIED_DENY"]
        if not self._audit(stage, GuardResult.DENY, codes, now, refs):
            codes.append("AUDIT_WRITE_FAILED")
        raise GuardDenied(stage, codes)


def legacy_daily_approval_valid(text: str, now_kst: datetime) -> bool:
    """기존 오늘 승인만 허용하고 미래·과거·변형값은 차단한다."""
    if not _kst(now_kst):
        return False
    candidate = str(text).strip()
    owner = re.fullmatch(
        r"APPROVED_BY_OWNER\s+(\d{8})\s+(\d{2}:\d{2}:\d{2})", candidate
    )
    automatic = re.fullmatch(
        r"auto-approved\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", candidate
    )
    dated = re.fullmatch(r"APPROVED_BY_OWNER\s+(\d{8})\s+S06_LIVE", candidate)
    try:
        if owner:
            approved_at = datetime.strptime(
                f"{owner.group(1)} {owner.group(2)}", "%Y%m%d %H:%M:%S"
            ).replace(tzinfo=KST)
        elif automatic:
            approved_at = datetime.fromisoformat(automatic.group(1)).replace(tzinfo=KST)
        elif dated:
            approved_at = datetime.strptime(dated.group(1), "%Y%m%d").replace(tzinfo=KST)
        else:
            return False
    except ValueError:
        return False
    return approved_at.date() == now_kst.date() and approved_at <= now_kst


def legacy_approval_signals(
    *, approval_text: str, now_kst: datetime, live_requested: bool,
    force_exit_only: bool, off_flag_exists: bool, manual_block_exists: bool,
) -> LegacyApprovalSignals:
    """기존 상태 신호만 계산하며 주문·브로커는 호출하지 않는다."""
    valid = legacy_daily_approval_valid(approval_text, now_kst)
    real_signal = bool(live_requested) and (valid or bool(force_exit_only))
    buy_signal = (
        real_signal and valid and not force_exit_only
        and not off_flag_exists and not manual_block_exists
    )
    return LegacyApprovalSignals(valid, real_signal, buy_signal)


def _token(value: Any) -> str:
    return str(value or "").strip().upper()


def _present(value: Any) -> bool:
    return value is not None and bool(str(value).strip())


def _missing_value(value: Any) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    return isinstance(value, (tuple, list, dict, set, frozenset)) and not value


def _kst(value: Any) -> bool:
    try:
        return value.tzinfo is not None and value.utcoffset() == timedelta(hours=9)
    except (AttributeError, TypeError, ValueError):
        return False


def _real_mode(mode: str) -> bool:
    normalized = _token(mode)
    compact = re.sub(r"[^A-Z]", "", normalized)
    words = set(re.findall(r"[A-Z]+", normalized))
    return compact in {"LIVE", "REAL", "REALACCOUNT", "PRODUCTION", "BROKER"} or bool(
        words.intersection({"LIVE", "REAL", "PRODUCTION", "BROKER"})
    )


def _scope(scope: Collection[str], strategy: str, mode: str) -> bool:
    normalized = {_token(value) for value in scope}
    return strategy in normalized and mode in normalized

# -*- coding: utf-8 -*-
"""One fail-closed automatic live preflight for Strategies 01, 02, and 03."""
from __future__ import annotations

import json
import sys
import os
import time as time_module
from datetime import datetime, time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))
from typing import Any, Mapping

from preflight_context_selftest_v1 import (
    SelftestFailure,
    validate_audit as validate_context_selftest,
)
from ma3_common_v1 import load_payload, ma3_rows, request_missing_history
from strategy_03_auto_live_preflight_v1 import (
    OLD_TASKS,
    PreflightFailure,
    _age_seconds,
    _broker_snapshot,
    _broker_truth,
    _read_json,
    _task_enabled,
    _write_json,
    prepare_daily_guard,
    validate_snapshot,
)


ROOT = Path(r"C:\stock_bot")
CONFIG = ROOT / "config"
DATA = ROOT / "data"
IPC = ROOT / "IPC"
AUDIT = DATA / "strategy_all_auto_live_preflight_v1.json"
CONTEXT = DATA / "strategy_common_candidate_context_v1.json"
SHARED_WATCH = IPC / "micro_watch_strategy_shared.json"
VALLEY_WATCH = IPC / "micro_watch_valley.json"
SNAPSHOT = IPC / "live_micro_snapshot.json"
VALLEY_OFF = CONFIG / "valley_off.flag"
MANUAL_BLOCK = CONFIG / "manual_buy_block.flag"
OLD_LEDGER = DATA / "valley_hunter_live_ledger.json"
SHARED_SLOTS = DATA / "shared_slots.json"
HIGH_RANGE = DATA / "common_high_range_top30.json"

BROKER_RETRYABLE_PREFIXES = (
    "BROKER_CONNECT:",
    "BROKER_HOLDINGS:",
    "BROKER_OPEN_ORDERS:",
)
BROKER_SNAPSHOT_MAX_ATTEMPTS = 3
BROKER_SNAPSHOT_RETRY_DELAY_SEC = 0.5
AUTO_RECOVERY_END = time(9, 5)
AUTO_RECOVERY_DELAY_SEC = 1.0

STRATEGIES = {
    "S01": {
        "off": CONFIG / "strategy_01_off.flag",
        "approval": CONFIG / "strategy_01_live_approved.flag",
        "state": DATA / "strategy_01_rotation_state_v2.json",
    },
    "S02": {
        "off": CONFIG / "strategy_02_off.flag",
        "approval": CONFIG / "strategy_02_live_approved.flag",
        "state": DATA / "strategy_02_rotation_state_v1.json",
    },
    "S03": {
        "off": CONFIG / "strategy_03_off.flag",
        "approval": CONFIG / "strategy_03_live_approved.flag",
        "state": DATA / "strategy_03_rotation_state_v1.json",
    },
}
REQUIRED_TASKS = (
    "SAFEPLUS_STRATEGY_COMMON_CONTEXT",
    "SAFEPLUS_STRATEGY01_SIGNAL",
    "SAFEPLUS_STRATEGY01_LIVE",
    "SAFEPLUS_STRATEGY02_SIGNAL",
    "SAFEPLUS_STRATEGY02_LIVE",
    "SAFEPLUS_STRATEGY03_SIGNAL",
    "SAFEPLUS_STRATEGY_ALL_PREFLIGHT",
    "SAFEPLUS_STRATEGY03_LIVE",
    "SAFEPLUS_PREFLIGHT_SELFTEST_HIGH",
)
REQUIRED_SOURCES = (
    "captain_money_rank",
    "moneyflow_selector",
    "moneyflow_watch",
    "high_range_top30",
)


def _broker_snapshot_with_retry(
    *,
    deadline: datetime,
    snapshot_reader=_broker_snapshot,
    max_attempts: int = BROKER_SNAPSHOT_MAX_ATTEMPTS,
    retry_delay_sec: float = BROKER_SNAPSHOT_RETRY_DELAY_SEC,
) -> tuple[dict[str, Any], int, list[str]]:
    """Retry only transient broker reads; all other failures remain closed."""
    attempts = 0
    errors: list[str] = []
    while attempts < max(1, int(max_attempts)):
        attempts += 1
        try:
            return snapshot_reader(), attempts, errors
        except PreflightFailure as exc:
            message = str(exc)
            errors.append(message)
            retryable = message.startswith(BROKER_RETRYABLE_PREFIXES)
            if (
                not retryable
                or attempts >= max_attempts
                or datetime.now() > deadline
            ):
                raise
            time_module.sleep(max(0.0, retry_delay_sec))
    raise PreflightFailure("BROKER_SNAPSHOT_RETRY_EXHAUSTED")


def _preload_s01_ma3(
    now: datetime,
    *,
    candidate_path: Path = HIGH_RANGE,
    payload_loader=load_payload,
    row_reader=ma3_rows,
    requester=request_missing_history,
) -> dict[str, Any]:
    """Check S01 high-range MA3 locally and queue missing history early."""
    source = _read_json(candidate_path)
    if str(source.get("for_date") or "") != now.strftime("%Y%m%d"):
        return {
            "status": "SKIPPED_DATE_MISMATCH",
            "candidate_count": 0,
            "ready_count": 0,
            "missing_count": 0,
            "requested_count": 0,
        }
    codes: list[str] = []
    for row in source.get("candidates") or []:
        code = str((row or {}).get("code") or "").strip().zfill(6)
        if len(code) == 6 and code.isdigit() and code not in codes:
            codes.append(code)
    payload = payload_loader()
    ready: list[str] = []
    missing: list[str] = []
    requested: list[str] = []
    request_errors: list[str] = []
    for code in codes:
        try:
            if row_reader(code, payload) is not None:
                ready.append(code)
                continue
            missing.append(code)
            if requester(code, "S01_PREFLIGHT_HIGH_RANGE"):
                requested.append(code)
        except Exception as exc:
            missing.append(code)
            request_errors.append(f"{code}:{type(exc).__name__}:{exc}")
    return {
        "status": "READY" if not missing else "BACKFILL_REQUESTED",
        "candidate_count": len(codes),
        "ready_count": len(ready),
        "missing_count": len(missing),
        "requested_count": len(requested),
        "missing_codes": missing,
        "requested_codes": requested,
        "request_errors": request_errors,
    }


def _strategy_state(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.exists() else {}


def _validate_local_state(now: datetime) -> dict[str, Any]:
    if now.weekday() >= 5:
        raise PreflightFailure("NOT_A_WEEKDAY")
    # ★[2026-07-27 친구님 승인] 평일 휴장일 차단(7/17 휴장일 기동 사고 재발 방지) —
    #   config\krx_holidays.txt(YYYYMMDD 줄단위·# 주석 허용)에 오늘이 있으면 실패.
    #   파일이 없거나 못 읽으면 기존 동작 유지(통과).
    try:
        _holidays = {
            line.strip()
            for line in (CONFIG / "krx_holidays.txt").read_text(
                encoding="utf-8-sig").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError:
        _holidays = set()
    if now.strftime("%Y%m%d") in _holidays:
        raise PreflightFailure("KRX_HOLIDAY")
    if not VALLEY_OFF.exists():
        raise PreflightFailure("OLD_VALLEY_OFF_MISSING")
    if MANUAL_BLOCK.exists():
        raise PreflightFailure("MANUAL_BUY_BLOCK_ACTIVE")
    try:
        context_selftest = validate_context_selftest(
            profile="high",
            now=now,
            max_age_sec=45 * 60,
        )
    except SelftestFailure as exc:
        raise PreflightFailure(
            f"PREFLIGHT_CONTEXT_SELFTEST:{exc}") from exc

    guard_status: dict[str, str] = {}
    for strategy, paths in STRATEGIES.items():
        guard_status[strategy] = prepare_daily_guard(
            now,
            off_path=paths["off"],
            approval_path=paths["approval"],
        )

    old_task_state = {name: _task_enabled(name) for name in OLD_TASKS}
    enabled_old = [
        name for name, enabled in old_task_state.items() if enabled is True]
    if enabled_old:
        raise PreflightFailure(
            "OLD_VALLEY_TASK_ENABLED:" + ",".join(enabled_old))
    required_task_state = {
        name: _task_enabled(name) for name in REQUIRED_TASKS}
    unavailable = [
        name for name, enabled in required_task_state.items()
        if enabled is not True
    ]
    if unavailable:
        raise PreflightFailure(
            "STRATEGY_TASK_NOT_ENABLED:" + ",".join(unavailable))

    states: dict[str, dict[str, Any]] = {}
    for strategy, paths in STRATEGIES.items():
        state = _strategy_state(paths["state"])
        positions = state.get("positions") or {}
        if positions:
            raise PreflightFailure(f"{strategy}_POSITIONS_NOT_EMPTY")
        if state.get("pending_order"):
            raise PreflightFailure(f"{strategy}_PENDING_ORDER_EXISTS")
        if state.get("recovery_required") or state.get("recovery_blocked"):
            raise PreflightFailure(f"{strategy}_RECOVERY_REQUIRED")
        states[strategy] = {
            "date": str(state.get("date") or ""),
            "order_attempts_total": int(
                state.get("order_attempts_total") or 0),
            "positions": len(positions),
            "recovery_blocked": bool(state.get("recovery_blocked")),
        }

    old_ledger = _read_json(OLD_LEDGER) if OLD_LEDGER.exists() else {}
    if old_ledger.get("slots"):
        raise PreflightFailure("OLD_VALLEY_LEDGER_NOT_EMPTY")
    shared = _read_json(SHARED_SLOTS) if SHARED_SLOTS.exists() else {}
    active_shared = (
        shared.get("slots") or {}
        if str(shared.get("date") or "") == now.strftime("%Y%m%d")
        else {}
    )
    if active_shared:
        raise PreflightFailure("SHARED_SLOTS_NOT_EMPTY")

    return {
        "context_selftest": context_selftest,
        "daily_guards": guard_status,
        "old_tasks": old_task_state,
        "required_tasks": required_task_state,
        "states": states,
        "old_valley_ledger_slots": len(old_ledger.get("slots") or {}),
        "shared_slots": len(active_shared),
    }


def _validate_sources(now: datetime) -> dict[str, Any]:
    context = _read_json(CONTEXT)
    today = now.strftime("%Y%m%d")
    if str(context.get("for_date") or "") != today:
        raise PreflightFailure("CONTEXT_DATE_MISMATCH")
    if _age_seconds(now, context.get("ts")) > 5:
        raise PreflightFailure("CONTEXT_STALE")
    if int(context.get("order_capability", -1)) != 0:
        raise PreflightFailure("CONTEXT_ORDER_CAPABILITY_NOT_ZERO")
    status = context.get("source_status") or {}
    for source in REQUIRED_SOURCES:
        row = status.get(source) or {}
        if not row.get("fresh"):
            raise PreflightFailure(f"SOURCE_STALE:{source}")
        if int(row.get("accepted_count") or 0) <= 0:
            raise PreflightFailure(f"SOURCE_EMPTY:{source}")
        if source != "high_range_top30":
            max_age = 30 if source == "captain_money_rank" else 60
            if _age_seconds(now, row.get("source_ts")) > max_age:
                raise PreflightFailure(f"SOURCE_TIMESTAMP_STALE:{source}")
    return {
        "context_ts": str(context.get("ts") or ""),
        "source_counts": dict(context.get("source_counts") or {}),
        "source_status": status,
    }


def _validate_watch(
    *,
    now: datetime,
    path: Path,
    require_unchanged_base: bool,
) -> tuple[list[str], dict[str, Any]]:
    watch = _read_json(path)
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "") != today:
        raise PreflightFailure(f"WATCH_DATE_MISMATCH:{path.name}")
    codes = [str(code).zfill(6) for code in (watch.get("codes") or [])]
    if not codes:
        raise PreflightFailure(f"WATCH_EMPTY:{path.name}")
    base_codes = [
        str(code).zfill(6)
        for code in (watch.get("base_codes") or codes)
    ]
    if require_unchanged_base and codes != base_codes:
        raise PreflightFailure(f"WATCH_BASE_CHANGED:{path.name}")
    check = validate_snapshot(
        now=now,
        valley_codes=codes,
        snapshot=_read_json(SNAPSHOT),
        minimum_valid=5,
    )
    return codes, check


def _validate_market_data(now: datetime) -> dict[str, Any]:
    source_check = _validate_sources(now)
    shared_codes, shared_check = _validate_watch(
        now=now,
        path=SHARED_WATCH,
        require_unchanged_base=False,
    )
    valley_codes, valley_check = _validate_watch(
        now=now,
        path=VALLEY_WATCH,
        require_unchanged_base=True,
    )
    return {
        **source_check,
        "shared_watch": shared_check,
        "valley_watch": valley_check,
        "candidate_codes": sorted(set(shared_codes) | set(valley_codes)),
    }


def activate_all_flags(
    strategies: Mapping[str, Mapping[str, Path]] = STRATEGIES,
    *,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now()
    created: list[Path] = []
    try:
        for strategy, paths in strategies.items():
            off_path = Path(paths["off"])
            approval_path = Path(paths["approval"])
            if not off_path.exists() or approval_path.exists():
                raise PreflightFailure(
                    f"{strategy}_FLAG_STATE_CHANGED_BEFORE_ACTIVATION")
        for strategy, paths in strategies.items():
            approval_path = Path(paths["approval"])
            tmp = approval_path.with_suffix(".flag.tmp")
            tmp.write_text(
                f"auto-approved {now.isoformat(timespec='seconds')}\n",
                encoding="ascii",
            )
            os.replace(tmp, approval_path)
            created.append(approval_path)
        for paths in strategies.values():
            Path(paths["off"]).unlink()
        return list(strategies)
    except Exception:
        for paths in strategies.values():
            off_path = Path(paths["off"])
            if not off_path.exists():
                off_path.write_text("OFF\n", encoding="ascii")
        for approval_path in created:
            approval_path.unlink(missing_ok=True)
        raise


def _write_audit_preserving_approved_pass(
    result: dict[str, Any],
    *,
    audit_path: Path = AUDIT,
) -> bool:
    """Keep the recovery gate open only for a redundant same-day approval run."""
    preserve = False
    try:
        previous = _read_json(audit_path)
        preserve = (
            result.get("passed") is not True
            and "ALREADY_APPROVED_TODAY" in str(result.get("reason") or "")
            and str(previous.get("for_date") or "")
            == str(result.get("for_date") or "")
            and previous.get("passed") is True
            and previous.get("activated") is True
            and set(previous.get("activated_strategies") or [])
            == set(STRATEGIES)
        )
    except PreflightFailure:
        preserve = False
    if not preserve:
        _write_json(audit_path, result)
        return False

    result["primary_audit_preserved"] = True
    attempt_path = audit_path.with_name(
        f"{audit_path.stem}_last_attempt{audit_path.suffix}")
    _write_json(attempt_path, result)
    return True


def run_preflight(
    *,
    activate: bool,
    allow_opening_recovery: bool = False,
    persist_audit: bool = True,
) -> dict[str, Any]:
    started = datetime.now()
    result: dict[str, Any] = {
        "schema": "strategy_all_auto_live_preflight_v1",
        "started_at": started.isoformat(timespec="milliseconds"),
        "for_date": started.strftime("%Y%m%d"),
        "activate_requested": bool(activate),
        "opening_recovery_requested": bool(allow_opening_recovery),
        "order_attempts": 0,
        "passed": False,
        "activated": False,
        "activated_strategies": [],
    }
    try:
        deadline_time = (
            time(9, 19, 30) if allow_opening_recovery else time(9, 0, 15)
        )
        deadline = datetime.combine(started.date(), deadline_time)
        # Local-only preparation: this cannot place orders or open a broker TR.
        # A missing MA3 remains an entry block until the common worker fills it.
        try:
            result["s01_ma3_preload"] = _preload_s01_ma3(started)
        except Exception as exc:
            result["s01_ma3_preload"] = {
                "status": "ERROR",
                "error": f"{type(exc).__name__}:{exc}",
            }
        # 브로커 조회를 맨 앞에서 한다(2026-07-28 사고).
        # 태스크 점검(PowerShell 폴백)·시장데이터 수집을 거친 뒤에 부르면
        # 같은 프로세스에서 잔고 조회가 12s 타임아웃되고 재연결로도 못 살린다.
        broker_snapshot, broker_attempts, broker_errors = (
            _broker_snapshot_with_retry(deadline=deadline)
        )
        result["broker_snapshot_attempts"] = broker_attempts
        result["broker_snapshot_retry_errors"] = broker_errors
        result["local_state"] = _validate_local_state(started)
        market: dict[str, Any] | None = None
        last_error = ""
        while datetime.now() <= deadline:
            try:
                market = _validate_market_data(datetime.now())
                break
            except PreflightFailure as exc:
                last_error = str(exc)
                time_module.sleep(0.25)
        if market is None:
            raise PreflightFailure(
                "MARKET_DATA_DEADLINE:" + (last_error or "UNKNOWN"))
        candidates = set(market.pop("candidate_codes"))
        result["market_data"] = market
        result["broker_truth"] = _broker_truth(candidates, broker_snapshot)
        if activate:
            result["activated_strategies"] = activate_all_flags()
            result["activated"] = True
        result["passed"] = True
        result["reason"] = "PASS"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}:{exc}"
    finally:
        result["finished_at"] = datetime.now().isoformat(timespec="milliseconds")
        result["flags"] = {
            strategy: {
                "off": Path(paths["off"]).exists(),
                "approval": Path(paths["approval"]).exists(),
            }
            for strategy, paths in STRATEGIES.items()
        }
        if persist_audit:
            _write_audit_preserving_approved_pass(result)
    return result


def _auto_recovery_retryable(result: Mapping[str, Any]) -> bool:
    reason = str(result.get("reason") or "")
    return reason.startswith((
        "PreflightFailure:BROKER_CONNECT:",
        "PreflightFailure:BROKER_HOLDINGS:",
        "PreflightFailure:BROKER_OPEN_ORDERS:",
        "PreflightFailure:MARKET_DATA_DEADLINE:",
        "PreflightFailure:PREFLIGHT_CONTEXT_SELFTEST:",
    ))


def run_preflight_with_auto_recovery(*, activate: bool) -> dict[str, Any]:
    """Keep transient opening failures in WAIT, retrying safely through 09:05."""
    started = datetime.now()
    cutoff = datetime.combine(started.date(), AUTO_RECOVERY_END)
    reasons: list[str] = []
    attempt = 0
    while True:
        attempt += 1
        result = run_preflight(
            activate=activate,
            allow_opening_recovery=attempt > 1,
            persist_audit=False,
        )
        reasons.append(str(result.get("reason") or "UNKNOWN"))
        if (
            result.get("passed") is True
            or not _auto_recovery_retryable(result)
            or datetime.now() >= cutoff
        ):
            break
        time_module.sleep(AUTO_RECOVERY_DELAY_SEC)
    result["auto_recovery"] = {
        "attempts": attempt,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "reasons": reasons,
        "final_state": "PASS" if result.get("passed") else "BLOCKED",
    }
    _write_audit_preserving_approved_pass(result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true")
    parser.add_argument(
        "--allow-opening-recovery",
        action="store_true",
        help="Explicit one-run recovery path; keep fail-closed after 09:19:30.",
    )
    args = parser.parse_args()
    if args.activate and not args.allow_opening_recovery:
        result = run_preflight_with_auto_recovery(activate=True)
    else:
        result = run_preflight(
            activate=args.activate,
            allow_opening_recovery=args.allow_opening_recovery,
        )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

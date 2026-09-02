# -*- coding: utf-8 -*-
"""Strategy 04 fail-closed preflight and explicit owner approval."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from preflight_context_selftest_v1 import (
    SelftestFailure,
    validate_audit as validate_context_selftest,
)
from strategy_04_pullback_signal_v1 import SIGNAL_MODE, SIGNAL_SCHEMA


ROOT = Path(r"C:\stock_bot")
WATCH = ROOT / "IPC" / "micro_watch_valley.json"
SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"
MINUTE = ROOT / "data" / "돈맥_1분봉.json"
MARKET = ROOT / "data" / "kosdaq_index.json"
SIGNAL = ROOT / "data" / "strategy_04_pullback_signal_v1.json"
STATE = ROOT / "data" / "strategy_04_rotation_state_v1.json"
AUDIT = ROOT / "data" / "strategy_04_preflight_v1.json"
APPROVAL = ROOT / "config" / "strategy_04_live_approved.flag"
OFF = ROOT / "config" / "strategy_04_off.flag"
MANUAL_BLOCK = ROOT / "config" / "manual_buy_block.flag"
REQUIRED_TASKS = (
    "SAFEPLUS_WATCHDOG_BROKER",
    "SAFEPLUS_STRATEGY_WATCHLIST",
    "SAFEPLUS_DEEP_SIGNAL_REC",
    "SAFEPLUS_KOSDAQ_IDX_REFRESH",
    "SAFEPLUS_STRATEGY04_SIGNAL",
    "SAFEPLUS_STRATEGY04_PREFLIGHT",
    "SAFEPLUS_STRATEGY04_LIVE",
    "SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED",
)


class PreflightFailure(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightFailure(f"JSON_UNAVAILABLE:{path.name}:{exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _age(now: datetime, value: Any) -> float:
    parsed = _parse_dt(value)
    return float("inf") if parsed is None else abs((now - parsed).total_seconds())


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _task_enabled(name: str) -> bool:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         f"(Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue).Settings.Enabled"],
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _approval_date(path: Path) -> str:
    try:
        text = path.read_text(encoding="ascii", errors="ignore")
    except OSError:
        return ""
    return next(
        (token for token in text.split() if len(token) == 8 and token.isdigit()),
        "",
    )


def _write_off(path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("OFF\n", encoding="ascii")
    os.replace(temporary, path)


def prepare_daily_guard(
    now: datetime,
    *,
    approval_path: Path | None = None,
    off_path: Path | None = None,
) -> str:
    approval_path = approval_path or APPROVAL
    off_path = off_path or OFF
    disabled = off_path.with_suffix(".flag.disabled")
    today = now.strftime("%Y%m%d")

    if approval_path.exists():
        approved_for = _approval_date(approval_path)
        if approved_for == today:
            if off_path.exists() or not disabled.exists():
                raise PreflightFailure("S04_CURRENT_APPROVAL_FLAG_MISMATCH")
            return "ALREADY_APPROVED_TODAY"
        if not off_path.exists():
            if disabled.exists():
                os.replace(disabled, off_path)
            else:
                _write_off(off_path)
        approval_path.unlink()
        if not approved_for:
            raise PreflightFailure("S04_UNRECOGNIZED_APPROVAL_REVOKED")
        return "STALE_APPROVAL_REVOKED"

    if not off_path.exists():
        if disabled.exists():
            os.replace(disabled, off_path)
            return "OFF_RESTORED_FROM_DISABLED"
        _write_off(off_path)
        raise PreflightFailure("S04_OFF_REPAIRED_FROM_UNSAFE_STATE")
    return "GUARD_READY"


def validate_snapshot(
    snapshot: Mapping[str, Any],
    codes: list[str],
    now: datetime,
    *,
    max_age_sec: float = 4.0,
    minimum_valid: int = 5,
) -> list[str]:
    valid: list[str] = []
    for code in codes:
        row = (snapshot.get("codes") or {}).get(code) or {}
        if _age(now, row.get("ts")) > max_age_sec:
            continue
        if _age(now, row.get("ob_ts")) > max_age_sec:
            continue
        if not (
            _number(row.get("cur")) >= 10_000
            and _number(row.get("best_ask_px")) > _number(row.get("best_bid_px")) > 0
            and _number(row.get("best_ask_qty")) > 0
            and _number(row.get("best_bid_qty")) > 0
            and _number(row.get("buy_money_cum"), -1) >= 0
            and _number(row.get("sell_money_cum"), -1) >= 0
        ):
            continue
        valid.append(code)
    required = min(max(1, minimum_valid), max(1, len(codes)))
    if len(valid) < required:
        raise PreflightFailure(f"TOPBOOK_COVERAGE:{len(valid)}<{required}")
    return valid


def validate(now: datetime) -> dict[str, Any]:
    if now.weekday() >= 5:
        raise PreflightFailure("NOT_A_WEEKDAY")
    # ★[2026-07-27 친구님 승인] 평일 휴장일 차단(7/17 휴장일 기동 사고 재발 방지) —
    #   config\krx_holidays.txt(YYYYMMDD 줄단위·# 주석 허용)에 오늘이 있으면 실패.
    #   파일이 없거나 못 읽으면 기존 동작 유지(통과).
    try:
        _holidays = {
            line.strip()
            for line in (ROOT / "config" / "krx_holidays.txt").read_text(
                encoding="utf-8-sig").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError:
        _holidays = set()
    if now.strftime("%Y%m%d") in _holidays:
        raise PreflightFailure("KRX_HOLIDAY")
    guard_status = prepare_daily_guard(now)
    if MANUAL_BLOCK.exists():
        raise PreflightFailure("MANUAL_BUY_BLOCK_ACTIVE")
    try:
        context_selftest = validate_context_selftest(
            profile="limited",
            now=now,
            max_age_sec=2 * 60 * 60,
        )
    except SelftestFailure as exc:
        raise PreflightFailure(
            f"PREFLIGHT_CONTEXT_SELFTEST:{exc}") from exc
    tasks = {name: _task_enabled(name) for name in REQUIRED_TASKS}
    missing = [name for name, enabled in tasks.items() if not enabled]
    if missing:
        raise PreflightFailure("TASK_MISSING_OR_DISABLED:" + ",".join(missing))

    # 예약작업 조회는 여러 PowerShell subprocess 때문에 수 초가 걸린다. 시작 시각
    # `now`로 이후 파일 신선도를 재면 그 사이 갱신된 파일이 미래로 보여 오탐한다.
    observed_at = datetime.now()
    day = observed_at.strftime("%Y%m%d")
    watch = _read_json(WATCH)
    if str(watch.get("for_date") or "") != day:
        raise PreflightFailure("WATCH_DATE_MISMATCH")
    codes = [str(code).zfill(6) for code in watch.get("codes") or []]
    if not codes:
        raise PreflightFailure("WATCH_EMPTY")

    minute = _read_json(MINUTE)
    if _age(observed_at, minute.get("ts")) > 90:
        raise PreflightFailure("MINUTE_DATA_STALE")
    if not (minute.get("m") or {}):
        raise PreflightFailure("MINUTE_DATA_EMPTY")

    market = _read_json(MARKET)
    if _age(observed_at, market.get("ts")) > 600:
        raise PreflightFailure("KOSDAQ_INDEX_STALE")

    signal = _read_json(SIGNAL)
    if str(signal.get("schema") or "") != SIGNAL_SCHEMA:
        raise PreflightFailure("SIGNAL_SCHEMA_MISMATCH")
    if str(signal.get("mode") or "") != SIGNAL_MODE:
        raise PreflightFailure("SIGNAL_MODE_NOT_ORDER_ZERO")
    if str(signal.get("date") or "") != day or _age(observed_at, signal.get("updated_at")) > 5:
        raise PreflightFailure("SIGNAL_NOT_FRESH")
    if str(signal.get("status") or "") != "LIVE":
        raise PreflightFailure(
            "SIGNAL_NOT_READY:" + str(signal.get("status") or "UNKNOWN"))
    if int(signal.get("valid_topbook_count") or 0) < 5:
        raise PreflightFailure("SIGNAL_TOPBOOK_COVERAGE_LOW")

    valid = validate_snapshot(_read_json(SNAPSHOT), codes, observed_at)
    state = _read_json(STATE) if STATE.exists() else {}
    if state.get("positions") or state.get("pending_order"):
        raise PreflightFailure("S04_LOCAL_POSITION_OR_PENDING")
    if state.get("recovery_required") or state.get("recovery_blocked"):
        raise PreflightFailure("S04_RECOVERY_REQUIRED")
    return {
        "context_selftest": context_selftest,
        "guard_status": guard_status,
        "tasks": tasks,
        "watch_count": len(codes),
        "fresh_exact_topbook_count": len(valid),
        "topbook_sample": valid[:10],
        "signal_order_capability": 0,
        "state_order_attempts_total": int(state.get("order_attempts_total") or 0),
    }


def approve(now: datetime) -> str:
    disabled = OFF.with_suffix(".flag.disabled")
    if APPROVAL.exists():
        if (
            _approval_date(APPROVAL) == now.strftime("%Y%m%d")
            and not OFF.exists()
            and disabled.exists()
        ):
            return "ALREADY_APPROVED_TODAY"
        raise PreflightFailure("S04_APPROVAL_FLAG_STATE_MISMATCH")
    if not OFF.exists():
        raise PreflightFailure("S04_OFF_MISSING_BEFORE_APPROVAL")
    APPROVAL.parent.mkdir(parents=True, exist_ok=True)
    temporary = APPROVAL.with_suffix(".flag.tmp")
    temporary.write_text(
        f"APPROVED_BY_OWNER {now:%Y%m%d} {now:%H:%M:%S}\n",
        encoding="ascii",
    )
    os.replace(temporary, APPROVAL)
    if disabled.exists():
        disabled.unlink()
    os.replace(OFF, disabled)
    return "APPROVED"


def run(*, activate: bool = False, now: datetime | None = None) -> int:
    now = now or datetime.now()
    payload: dict[str, Any] = {
        "for_date": now.strftime("%Y%m%d"),
        "started_at": now.isoformat(timespec="seconds"),
        "passed": False,
        "activated": False,
    }
    try:
        payload["checks"] = validate(now)
        if activate:
            payload["approval_status"] = approve(now)
            payload["activated"] = True
        payload["passed"] = True
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(AUDIT, payload)
        print("STRATEGY04_PREFLIGHT_PASS" + (" APPROVED" if activate else ""))
        return 0
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}:{exc}"
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(AUDIT, payload)
        print(f"STRATEGY04_PREFLIGHT_FAIL {payload['error']}")
        return 2


def activation_requested(
    *, approve: bool, approve_on: str, now: datetime,
) -> bool:
    return bool(approve) or str(approve_on or "").strip() == now.strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--approve",
        action="store_true",
        help="write today's owner approval and remove OFF only after every check passes",
    )
    parser.add_argument(
        "--approve-on",
        default="",
        help="approve only on this YYYYMMDD; other dates remain read-only",
    )
    args = parser.parse_args()
    now = datetime.now()
    return run(
        activate=activation_requested(
            approve=args.approve, approve_on=args.approve_on, now=now),
        now=now,
    )


if __name__ == "__main__":
    raise SystemExit(main())

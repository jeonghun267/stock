# -*- coding: utf-8 -*-
"""Fail-closed, read-only preflight for Strategy 03 automatic activation.

No order method is imported or called.  The only live-state mutation occurs
after every check passes: create the S03 approval flag, then remove S03 OFF.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time as time_module
import xml.etree.ElementTree as ET
from datetime import datetime, time
from pathlib import Path

# ★[SYSPATH-FIX 2026-08-05] python._pth 때문에 스크립트 폴더가 sys.path 에 안 들어간다
#   (실측 [python310.zip, C:\python310, site-packages]). 이 파일은 .cmd 가 직접
#   실행하는 진입점(SAFEPLUS_STRATEGY03_PREFLIGHT.cmd)이라 부트스트랩이 필요하다.
#   없으면 아래 strategy_common_order_v1 import 가 ModuleNotFoundError 로 즉사한다.
#   ⚠️지금은 해당 태스크가 Disabled 라 잠복 상태였고, 8/5 아침 리허설 검사기가
#   진입점 130개 중 유일한 잔여 지뢰로 찾아냈다.
#   같은 패턴: strategy_all_live_gate_launcher_v1.py:12-14
#   되돌리기: backup\strategy_03_auto_live_preflight_v1_20260805_before_syspath_fix.py
RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))
from typing import Any, Mapping


ROOT = Path(r"C:\stock_bot")
CONFIG = ROOT / "config"
DATA = ROOT / "data"
IPC = ROOT / "IPC"
APPROVAL = CONFIG / "strategy_03_live_approved.flag"
S03_OFF = CONFIG / "strategy_03_off.flag"
VALLEY_OFF = CONFIG / "valley_off.flag"
MANUAL_BLOCK = CONFIG / "manual_buy_block.flag"
CONTEXT = DATA / "strategy_common_candidate_context_v1.json"
VALLEY_WATCH = IPC / "micro_watch_valley.json"
SNAPSHOT = IPC / "live_micro_snapshot.json"
S03_STATE = DATA / "strategy_03_rotation_state_v1.json"
OLD_LEDGER = DATA / "valley_hunter_live_ledger.json"
AUDIT = DATA / "strategy_03_auto_live_preflight_v1.json"
OLD_TASKS = (
    "SAFEPLUS_VALLEY_HUNTER_LIVE",
    "SAFEPLUS_VALLEY_EXT_SHADOW",
    "SAFEPLUS_VALLEY_FLAT",
    "SAFEPLUS_VALLEY_GATE1_DIAG",
    "SAFEPLUS_VALLEY_COMMON_EXIT_SHADOW",
)
REQUIRED_TASKS = (
    "SAFEPLUS_STRATEGY_COMMON_CONTEXT",
    "SAFEPLUS_STRATEGY03_SIGNAL",
    "SAFEPLUS_STRATEGY03_LIVE",
)
REQUIRED_SOURCES = (
    "captain_money_rank",
    "moneyflow_selector",
    "moneyflow_watch",
    "high_range_top30",
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


def _age_seconds(now: datetime, value: Any) -> float:
    parsed = _parse_dt(value)
    return float("inf") if parsed is None else abs((now - parsed).total_seconds())


def task_enabled_from_xml(xml_bytes: bytes) -> bool | None:
    try:
        if xml_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = xml_bytes.decode("utf-16")
        else:
            text = xml_bytes.decode("utf-8-sig")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError):
        return None
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Enabled":
            return str(element.text or "").strip().lower() == "true"
    return True


def _task_enabled(name: str) -> bool | None:
    try:
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", name, "/XML"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.warning("TASK_QUERY_SCHTASKS_ERROR name=%s error=%s", name, exc)
    else:
        if result.returncode == 0:
            enabled = task_enabled_from_xml(result.stdout)
            if enabled is not None:
                return enabled
        logging.warning(
            "TASK_QUERY_SCHTASKS_FAILED name=%s rc=%s stderr=%s",
            name,
            result.returncode,
            result.stderr.decode("utf-8", errors="replace").strip(),
        )

    command = (
        "$task=Get-ScheduledTask -TaskName $env:SAFEPLUS_TASK_QUERY_NAME "
        "-ErrorAction SilentlyContinue; "
        "if ($null -eq $task) { exit 3 }; "
        "if ($task.Settings.Enabled) { 'true' } else { 'false' }"
    )
    fallback_env = os.environ.copy()
    fallback_env["SAFEPLUS_TASK_QUERY_NAME"] = name
    try:
        fallback = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=8,
            env=fallback_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.warning(
            "TASK_QUERY_POWERSHELL_ERROR name=%s error=%s", name, exc)
        return None
    output = fallback.stdout.strip().lower()
    if fallback.returncode == 0 and output in {"true", "false"}:
        return output == "true"
    logging.warning(
        "TASK_QUERY_POWERSHELL_FAILED name=%s rc=%s stderr=%s",
        name,
        fallback.returncode,
        fallback.stderr.strip(),
    )
    return None


def validate_snapshot(
    *,
    now: datetime,
    valley_codes: list[str],
    snapshot: Mapping[str, Any],
    max_age_sec: float = 4.0,
    minimum_valid: int = 5,
) -> dict[str, Any]:
    valid: list[str] = []
    for code in valley_codes:
        row = (snapshot.get("codes") or {}).get(code) or {}
        if (
            _age_seconds(now, row.get("ts")) > max_age_sec
            or _age_seconds(now, row.get("ob_ts")) > max_age_sec
        ):
            continue
        if not (
            _number(row.get("cur")) > 0
            and _number(row.get("best_ask_px")) > _number(row.get("best_bid_px")) > 0
            and _number(row.get("best_ask_qty")) > 0
            and _number(row.get("best_bid_qty")) > 0
            and _number(row.get("buy_money_cum"), -1) >= 0
            and _number(row.get("sell_money_cum"), -1) >= 0
        ):
            continue
        valid.append(code)
    required = min(max(1, minimum_valid), max(1, len(valley_codes)))
    if len(valid) < required:
        raise PreflightFailure(
            f"TOPBOOK_COVERAGE:{len(valid)}<{required}")
    return {
        "valley_watch_count": len(valley_codes),
        "fresh_exact_topbook_count": len(valid),
        "sample_codes": valid[:10],
    }


def prepare_daily_guard(
    now: datetime,
    *,
    off_path: Path = S03_OFF,
    approval_path: Path = APPROVAL,
) -> str:
    if approval_path.exists():
        text = approval_path.read_text(encoding="ascii", errors="ignore")
        approval_date = text[14:24].replace("-", "")
        if approval_date == now.strftime("%Y%m%d"):
            raise PreflightFailure("S03_ALREADY_APPROVED_TODAY")
        tmp = off_path.with_suffix(".flag.tmp")
        tmp.write_text("OFF\n", encoding="ascii")
        os.replace(tmp, off_path)
        approval_path.unlink()
        if len(approval_date) != 8 or not approval_date.isdigit():
            raise PreflightFailure("UNRECOGNIZED_APPROVAL_REVOKED")
        return "STALE_AUTO_APPROVAL_REVOKED"
    if not off_path.exists():
        off_path.write_text("OFF\n", encoding="ascii")
        raise PreflightFailure("S03_OFF_REPAIRED_FROM_UNSAFE_STATE")
    return "GUARD_READY"


def _validate_local_state(now: datetime) -> dict[str, Any]:
    if now.weekday() >= 5:
        raise PreflightFailure("NOT_A_WEEKDAY")
    if not VALLEY_OFF.exists():
        raise PreflightFailure("OLD_VALLEY_OFF_MISSING")
    guard_status = prepare_daily_guard(now)
    if MANUAL_BLOCK.exists():
        raise PreflightFailure("MANUAL_BUY_BLOCK_ACTIVE")

    old_task_state = {name: _task_enabled(name) for name in OLD_TASKS}
    enabled_old = [
        name for name, enabled in old_task_state.items() if enabled is True]
    if enabled_old:
        raise PreflightFailure(
            "OLD_VALLEY_TASK_ENABLED:" + ",".join(enabled_old))
    required_task_state = {
        name: _task_enabled(name) for name in REQUIRED_TASKS}
    missing_or_disabled = [
        name for name, enabled in required_task_state.items()
        if enabled is not True
    ]
    if missing_or_disabled:
        raise PreflightFailure(
            "S03_TASK_NOT_ENABLED:" + ",".join(missing_or_disabled))

    state = _read_json(S03_STATE) if S03_STATE.exists() else {}
    if state.get("positions"):
        raise PreflightFailure("S03_LOCAL_POSITIONS_NOT_EMPTY")
    if state.get("pending_order"):
        raise PreflightFailure("S03_PENDING_ORDER_EXISTS")
    if state.get("recovery_required") or state.get("recovery_blocked"):
        raise PreflightFailure("S03_RECOVERY_REQUIRED")

    ledger = _read_json(OLD_LEDGER) if OLD_LEDGER.exists() else {}
    if ledger.get("slots"):
        raise PreflightFailure("OLD_VALLEY_LEDGER_NOT_EMPTY")

    return {
        "old_tasks": old_task_state,
        "required_tasks": required_task_state,
        "daily_guard": guard_status,
        "s03_state_date": str(state.get("date") or ""),
        "s03_order_attempts_total": int(state.get("order_attempts_total") or 0),
        "old_valley_ledger_slots": len(ledger.get("slots") or {}),
    }


def _validate_market_data(now: datetime) -> dict[str, Any]:
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

    valley = _read_json(VALLEY_WATCH)
    valley_codes = [
        str(code).zfill(6) for code in (valley.get("codes") or [])]
    base_codes = [
        str(code).zfill(6) for code in (valley.get("base_codes") or valley_codes)]
    if not valley_codes or valley_codes != base_codes:
        raise PreflightFailure("VALLEY_POOL_CHANGED")
    snapshot_check = validate_snapshot(
        now=now,
        valley_codes=valley_codes,
        snapshot=_read_json(SNAPSHOT),
    )
    return {
        "context_ts": str(context.get("ts") or ""),
        "source_counts": dict(context.get("source_counts") or {}),
        "source_status": status,
        **snapshot_check,
        "valley_codes": valley_codes,
    }


def _broker_snapshot() -> dict[str, Any]:
    """후보 목록과 무관한 브로커 조회(잔고·미체결)를 먼저 떼어 수행한다.

    2026-07-28 실측: 시장데이터 수집 뒤에 잔고를 조회하면 같은 프로세스에서
    첫 조회가 12s 타임아웃되고 재시도·재연결로도 살아나지 않아 사전점검이
    통째로 실패했다(S01·S03 진입창 상실). 같은 조회를 수집 전에 하면 1~2s에
    성공한다. 후보 목록이 필요 없는 조회이므로 순서를 앞으로 옮긴다.
    """
    from strategy_common_order_v1 import StrategyBroker

    logger = logging.getLogger("strategy03_preflight")
    broker = StrategyBroker(
        live_requested=True,
        approval_path=APPROVAL,
        off_flag_path=S03_OFF,
        manual_buy_block_path=MANUAL_BLOCK,
        logger=logger,
        order_prefix="STRATEGY03_PREFLIGHT",
        screen_no="9783",
        force_exit_only=True,
    )
    if not broker.connect():
        raise PreflightFailure(f"BROKER_CONNECT:{broker.last_error}")
    holdings = broker.holdings()
    if holdings is None:
        # 2026-07-28 실측: 이 자리(시장데이터 수집 직후)의 첫 조회만 12s 타임아웃.
        # 같은 인스턴스로 재시도해도 실패하나, 새 연결로는 1~2s에 성공한다.
        # 재연결 후에도 못 읽으면 종전대로 잠근다.
        logger.warning("BROKER_HOLDINGS_RECONNECT after %s", broker.last_error)
        broker = StrategyBroker(
            live_requested=True,
            approval_path=APPROVAL,
            off_flag_path=S03_OFF,
            manual_buy_block_path=MANUAL_BLOCK,
            logger=logger,
            order_prefix="STRATEGY03_PREFLIGHT",
            screen_no="9783",
            force_exit_only=True,
        )
        if broker.connect():
            holdings = broker.holdings()
    if holdings is None:
        raise PreflightFailure(f"BROKER_HOLDINGS:{broker.last_error}")

    response = broker.client.balance_tr(
        tr_code="opt10075",
        inputs={
            "계좌번호": broker.account,
            "전체종목구분": "0",
            "매매구분": "0",
            "종목코드": "",
            "체결구분": "1",
        },
        output_fields=[
            "주문번호", "종목코드", "주문구분", "주문수량",
            "미체결수량", "주문상태",
        ],
        rqname="STRATEGY03_PREFLIGHT_OPEN_ALL",
        screen_no="9783",
        timeout_sec=10.0,
    )
    if str(response.get("status") or "").upper() != "OK":
        raise PreflightFailure(
            "BROKER_OPEN_ORDERS:"
            + str(response.get("error") or "NOT_OK"))
    open_rows: list[dict[str, Any]] = []
    for row in ((response.get("data") or {}).get("records") or []):
        remaining = int(_number(row.get("미체결수량")))
        if remaining <= 0:
            continue
        open_rows.append({
            "code": str(row.get("종목코드") or "").strip().lstrip("A").zfill(6),
            "order_no": str(row.get("주문번호") or ""),
            "remaining": remaining,
            "side": str(row.get("주문구분") or ""),
        })
    return {
        "account": broker.account,
        "holdings": holdings,
        "open_rows": open_rows,
    }


def _broker_truth(
    candidate_codes: set[str],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = _broker_snapshot() if snapshot is None else snapshot
    account = str(snap["account"])
    holdings = snap["holdings"]
    open_candidates = [
        row for row in snap["open_rows"] if row["code"] in candidate_codes]
    if open_candidates:
        raise PreflightFailure(
            "CANDIDATE_OPEN_ORDER_EXISTS:"
            + ",".join(row["code"] for row in open_candidates))
    return {
        "account_verified": True,
        "account_masked": account[:4] + "*" * max(0, len(account) - 4),
        "holding_count": len(holdings),
        "candidate_holding_count": len(set(holdings) & candidate_codes),
        "candidate_open_order_count": 0,
    }


def activate_flags(*, off_path: Path = S03_OFF, approval_path: Path = APPROVAL) -> None:
    if not off_path.exists() or approval_path.exists():
        raise PreflightFailure("FLAG_STATE_CHANGED_BEFORE_ACTIVATION")
    tmp = approval_path.with_suffix(".flag.tmp")
    tmp.write_text(
        f"auto-approved {datetime.now().isoformat(timespec='seconds')}\n",
        encoding="ascii",
    )
    os.replace(tmp, approval_path)
    try:
        off_path.unlink()
    except OSError:
        approval_path.unlink(missing_ok=True)
        raise


def run_preflight(*, activate: bool) -> dict[str, Any]:
    started = datetime.now()
    approval_preexisting = APPROVAL.exists()
    result: dict[str, Any] = {
        "schema": "strategy_03_auto_live_preflight_v1",
        "started_at": started.isoformat(timespec="milliseconds"),
        "for_date": started.strftime("%Y%m%d"),
        "activate_requested": bool(activate),
        "order_attempts": 0,
        "passed": False,
        "activated": False,
    }
    try:
        result["local_state"] = _validate_local_state(started)

        deadline = datetime.combine(started.date(), time(9, 0, 15))
        last_market_error = ""
        market: dict[str, Any] | None = None
        while datetime.now() <= deadline:
            try:
                market = _validate_market_data(datetime.now())
                break
            except PreflightFailure as exc:
                last_market_error = str(exc)
                time_module.sleep(0.25)
        if market is None:
            raise PreflightFailure(
                "MARKET_DATA_DEADLINE:" + (last_market_error or "UNKNOWN"))
        result["market_data"] = {
            key: value for key, value in market.items() if key != "valley_codes"
        }
        result["broker_truth"] = _broker_truth(set(market["valley_codes"]))
        if activate:
            activate_flags()
            result["activated"] = True
        result["passed"] = True
        result["reason"] = "PASS"
        return result
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}:{exc}"
        if (
            not approval_preexisting
            and S03_OFF.exists()
            and APPROVAL.exists()
        ):
            APPROVAL.unlink(missing_ok=True)
        return result
    finally:
        result["finished_at"] = datetime.now().isoformat(timespec="milliseconds")
        result["off_flag_exists"] = S03_OFF.exists()
        result["approval_exists"] = APPROVAL.exists()
        _write_json(AUDIT, result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    result = run_preflight(activate=args.activate)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

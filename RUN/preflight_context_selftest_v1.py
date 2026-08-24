# -*- coding: utf-8 -*-
"""Three-stage scheduled-task context self-test; order and approval capability zero."""
from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import subprocess
import sys
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_03_auto_live_preflight_v1 as task_query


ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
AUDITS = {
    "high": DATA / "preflight_context_selftest_high_v1.json",
    "limited": DATA / "preflight_context_selftest_limited_v1.json",
}
SELFTEST_TASKS = (
    "SAFEPLUS_PREFLIGHT_SELFTEST_HIGH",
    "SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED",
)
REQUIRED_TASKS = (
    "SAFEPLUS_WATCHDOG_BROKER",
    "SAFEPLUS_STRATEGY_WATCHLIST",
    "SAFEPLUS_STRATEGY_COMMON_CONTEXT",
    "SAFEPLUS_STRATEGY01_SIGNAL",
    "SAFEPLUS_STRATEGY01_LIVE",
    "SAFEPLUS_STRATEGY02_SIGNAL",
    "SAFEPLUS_STRATEGY02_LIVE",
    "SAFEPLUS_STRATEGY03_SIGNAL",
    "SAFEPLUS_STRATEGY_ALL_PREFLIGHT",
    "SAFEPLUS_STRATEGY03_LIVE",
    "SAFEPLUS_DEEP_SIGNAL_REC",
    "SAFEPLUS_KOSDAQ_IDX_REFRESH",
    "SAFEPLUS_STRATEGY04_SIGNAL",
    "SAFEPLUS_STRATEGY04_PREFLIGHT",
    "SAFEPLUS_STRATEGY04_LIVE",
) + SELFTEST_TASKS
RETIRED_TASKS = task_query.OLD_TASKS
ENABLED_PROBE = "SAFEPLUS_STRATEGY_ALL_PREFLIGHT"
MISSING_PROBE = "SAFEPLUS_SELFTEST_TASK_MUST_NOT_EXIST_7F2C"


class SelftestFailure(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelftestFailure(f"AUDIT_UNAVAILABLE:{path.name}:{exc}") from exc


def _parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _stage1_mock_contract() -> dict[str, Any]:
    enabled_xml = (
        b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        b"<Settings><Enabled>true</Enabled></Settings></Task>"
    )
    disabled_xml = enabled_xml.replace(b"true", b"false")
    fake_disabled = subprocess.CompletedProcess(
        [], 0, stdout=disabled_xml, stderr=b"")
    with patch.object(
        task_query.subprocess, "run", return_value=fake_disabled,
    ) as mocked:
        explicit_disabled = task_query._task_enabled("SAFEPLUS_MOCK_DISABLED")
    checks = {
        "xml_enabled": task_query.task_enabled_from_xml(enabled_xml) is True,
        "xml_disabled": task_query.task_enabled_from_xml(disabled_xml) is False,
        "xml_malformed": task_query.task_enabled_from_xml(b"not xml") is None,
        "explicit_disabled": explicit_disabled is False,
        "disabled_did_not_fallback": mocked.call_count == 1,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _forced_fallback(name: str) -> bool | None:
    real_run = task_query.subprocess.run

    def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if args and str(args[0]).lower().endswith("schtasks.exe"):
            return subprocess.CompletedProcess(
                args, 1, stdout=b"", stderr=b"forced selftest failure")
        return real_run(args, **kwargs)

    with patch.object(task_query.subprocess, "run", side_effect=runner):
        return task_query._task_enabled(name)


def _stage2_real_fallback() -> dict[str, Any]:
    retired_probe = RETIRED_TASKS[0]
    last: dict[str, Any] = {}
    for attempt in range(1, 4):
        last = {
            "attempt": attempt,
            "enabled": _forced_fallback(ENABLED_PROBE),
            "retired": _forced_fallback(retired_probe),
            "missing": _forced_fallback(MISSING_PROBE),
            "retired_probe": retired_probe,
        }
        if (
            last["enabled"] is True
            and last["retired"] is not True
            and last["missing"] is None
        ):
            return {"passed": True, **last}
        time_module.sleep(0.2)
    return {"passed": False, **last}


def _stage3_scheduled_context(
    *, profile: str, scheduled_context: bool,
) -> dict[str, Any]:
    states = {name: task_query._task_enabled(name) for name in REQUIRED_TASKS}
    retired = {name: task_query._task_enabled(name) for name in RETIRED_TASKS}
    missing = [name for name, state in states.items() if state is not True]
    retired_enabled = [
        name for name, state in retired.items() if state is True]
    marker = os.environ.get("SAFEPLUS_SCHEDULED_SELFTEST", "") == profile
    return {
        "passed": (
            scheduled_context
            and marker
            and not missing
            and not retired_enabled
        ),
        "profile": profile,
        "scheduled_argument": scheduled_context,
        "scheduled_marker": marker,
        "user": getpass.getuser(),
        "elevated": _is_elevated(),
        "required_tasks": states,
        "retired_tasks": retired,
        "missing_or_disabled": missing,
        "retired_enabled": retired_enabled,
    }


def validate_audit(
    *, profile: str, now: datetime, max_age_sec: float,
) -> dict[str, Any]:
    if profile not in AUDITS:
        raise SelftestFailure(f"UNKNOWN_PROFILE:{profile}")
    payload = _read_json(AUDITS[profile])
    if str(payload.get("for_date") or "") != now.strftime("%Y%m%d"):
        raise SelftestFailure(f"DATE_MISMATCH:{profile}")
    finished = _parse_dt(payload.get("finished_at"))
    if finished is None or abs((now - finished).total_seconds()) > max_age_sec:
        raise SelftestFailure(f"STALE:{profile}")
    if payload.get("passed") is not True:
        raise SelftestFailure(f"FAILED:{profile}:{payload.get('reason') or 'UNKNOWN'}")
    if payload.get("scheduled_context") is not True:
        raise SelftestFailure(f"NOT_SCHEDULED_CONTEXT:{profile}")
    if int(payload.get("order_capability", -1)) != 0:
        raise SelftestFailure(f"ORDER_CAPABILITY_NOT_ZERO:{profile}")
    stages = payload.get("stages") or {}
    if any((stages.get(name) or {}).get("passed") is not True for name in (
        "stage1_mock", "stage2_real_fallback", "stage3_scheduled_context",
    )):
        raise SelftestFailure(f"STAGE_NOT_PASSED:{profile}")
    return {
        "profile": profile,
        "finished_at": payload.get("finished_at"),
        "user": (stages.get("stage3_scheduled_context") or {}).get("user"),
        "elevated": (stages.get("stage3_scheduled_context") or {}).get("elevated"),
        "age_sec": round(abs((now - finished).total_seconds()), 3),
        "passed": True,
    }


def run(*, profile: str, scheduled_context: bool) -> dict[str, Any]:
    started = datetime.now()
    payload: dict[str, Any] = {
        "schema": "preflight_context_selftest_v1",
        "profile": profile,
        "for_date": started.strftime("%Y%m%d"),
        "started_at": started.isoformat(timespec="milliseconds"),
        "scheduled_context": bool(scheduled_context),
        "order_capability": 0,
        "approval_capability": 0,
        "passed": False,
        "stages": {},
    }
    try:
        payload["stages"]["stage1_mock"] = _stage1_mock_contract()
        payload["stages"]["stage2_real_fallback"] = _stage2_real_fallback()
        payload["stages"]["stage3_scheduled_context"] = (
            _stage3_scheduled_context(
                profile=profile,
                scheduled_context=scheduled_context,
            )
        )
        failed = [
            name for name, result in payload["stages"].items()
            if result.get("passed") is not True
        ]
        if failed:
            raise SelftestFailure("FAILED_STAGES:" + ",".join(failed))
        payload["passed"] = True
        payload["reason"] = "PASS"
    except Exception as exc:
        payload["reason"] = f"{type(exc).__name__}:{exc}"
    payload["finished_at"] = datetime.now().isoformat(timespec="milliseconds")
    _write_json(AUDITS[profile], payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(AUDITS), required=True)
    parser.add_argument("--scheduled-context", action="store_true")
    args = parser.parse_args()
    result = run(
        profile=args.profile,
        scheduled_context=args.scheduled_context,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

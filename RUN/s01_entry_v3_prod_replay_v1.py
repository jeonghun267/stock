# -*- coding: utf-8 -*-
"""Replay S01 v3 through the current production runtime using exact saved inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ★[2026-08-28 수리] C:\stock_bot 에서 `python RUN\...py` 로 부르면 RUN 이
#   모듈 경로에 없어 ModuleNotFoundError 로 죽었다(지시서 명령 그대로가 실패).
_RUN_DIR = str(Path(__file__).resolve().parent)
if _RUN_DIR not in sys.path:
    sys.path.insert(0, _RUN_DIR)

from strategy_01_entry_runtime_v3 import EntryRuntimeV3
from strategy_01_open_surge_signal_v2 import ShadowPoint


ROOT = Path(r"C:\stock_bot")
DEFAULT_RESTART_LOG = ROOT / "data" / "LOG" / "sched_STRATEGY01_SIGNAL.log"

# ★[2026-08-28 친구님 지시 "지금 수정해"] ma5/ma5_prev/ma10 은 ma3_rows 의
#   백필 캐시 폴백(ma3_common_v1.py 246행 — 호출 시점 디스크 읽기)이 장중에
#   자라나, 캡처 이후의 재생에선 값이 어긋난다(8/28 실측: 716건 전건 1봉 시프트,
#   신호는 716건 전건 일치). 판정 변화는 신호 비교가 그대로 강제하므로
#   감사 비교에서만 이 3필드를 뺀다. 근본 수리(백필 캐시까지 캡처)는 별도 안건.
AUDIT_ENV_FIELDS = ("ma5", "ma5_prev", "ma10")


def _strip_env_fields(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    return {key: value for key, value in row.items()
            if key not in AUDIT_ENV_FIELDS}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _restart_boundaries(path: Path, trade_date: str) -> list[datetime]:
    """Read proven signal-process restarts from the preserved scheduler log."""
    boundaries: list[datetime] = []
    restart_pending = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "PermissionError:" in line:
                restart_pending = True
                continue
            if not restart_pending or not line.lstrip().startswith("{"):
                continue
            try:
                payload = json.loads(line)
                updated_at = datetime.fromisoformat(str(payload.get("updated_at") or ""))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            restart_pending = False
            if updated_at.strftime("%Y%m%d") == trade_date:
                boundaries.append(updated_at)
    return boundaries


def replay(
    source: Path,
    trade_date: str,
    restart_log: Path,
    command: str,
) -> dict[str, Any]:
    records = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result: dict[str, Any] = {
        "provenance": "[UNVERIFIED]", "status": "BLOCKED",
        "date": trade_date,
        "source": str(source), "production_entry_point":
        "RUN/strategy_01_entry_runtime_v3.py:EntryRuntimeV3.process_batch",
        "production_code": "NOT_CHANGED", "records": len(records),
        "audit_env_fields_excluded": list(AUDIT_ENV_FIELDS),
        "ready_cases": 0, "violations": [],
        "performance_scope": "DECISION_ONLY",
        "command": command,
    }
    if not records:
        result["violations"].append("NO_PRESERVED_INPUT")
        return result

    expected_hashes = records[0].get("production_files") or {}
    if not expected_hashes:
        result["violations"].append("PRODUCTION_HASHES_MISSING")
    for raw_path, expected in expected_hashes.items():
        path = Path(raw_path)
        if not path.exists() or _sha(path) != str(expected):
            result["violations"].append(f"PRODUCTION_HASH_CHANGED:{path}")

    restart_boundaries = _restart_boundaries(restart_log, trade_date)
    captured_times = [
        datetime.fromisoformat(str(record.get("captured_at") or ""))
        for record in records
    ]
    first_capture, last_capture = captured_times[0], captured_times[-1]
    restart_boundaries = [
        boundary for boundary in restart_boundaries
        if first_capture < boundary <= last_capture
    ]
    result["source_data"] = [str(source), str(restart_log)]
    result["restart_boundaries"] = [
        boundary.isoformat(timespec="seconds") for boundary in restart_boundaries
    ]
    result["sha256"] = {
        "source": _sha(source),
        "restart_log": _sha(restart_log),
        "replay_tool": _sha(Path(__file__)),
        "production_files": expected_hashes,
    }

    runtime = EntryRuntimeV3({"codes": {}})
    restart_index = 0
    for index, record in enumerate(records, start=1):
        if record.get("schema") != "s01_entry_v3_exact_input_v1":
            result["violations"].append(f"BAD_SCHEMA:{index}")
            continue
        if (record.get("production_files") or {}) != expected_hashes:
            result["violations"].append(f"MIXED_PRODUCTION_HASH:{index}")
            continue
        captured_at = captured_times[index - 1]
        if (
            restart_index < len(restart_boundaries)
            and restart_boundaries[restart_index] <= captured_at
        ):
            runtime = EntryRuntimeV3({"codes": {}})
            restart_index += 1
        runtime.baseline.update(record.get("volume_baseline_rows") or {})
        points = []
        for raw in record.get("points") or []:
            point = dict(raw)
            point["ts"] = datetime.fromisoformat(str(point.get("ts") or ""))
            points.append(ShadowPoint(**point))
        actual_signals, actual_audit = runtime.process_batch(
            points,
            record.get("minute_payload") or {},
            record.get("trend_rows") or {},
            allow_select=bool(record.get("allow_select")),
        )
        expected_signals = record.get("expected_signals") or []
        expected_audit = record.get("expected_audit") or []
        result["ready_cases"] += len(expected_signals)
        if _canonical(actual_signals) != _canonical(expected_signals):
            result["violations"].append(f"SIGNAL_MISMATCH:{index}")
        if (_canonical([_strip_env_fields(row) for row in actual_audit])
                != _canonical([_strip_env_fields(row) for row in expected_audit])):
            result["violations"].append(f"AUDIT_MISMATCH:{index}")

    if result["ready_cases"] == 0:
        result["violations"].append("NO_V3_READY_CASE_OBSERVED")
    if not result["violations"]:
        result.update({"provenance": "[PROD_REPLAY]", "status": "PASS"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--restart-log", type=Path, default=DEFAULT_RESTART_LOG)
    args = parser.parse_args()
    source = args.input or (
        ROOT / "data" / "s01_entry_v3_exact_replay"
        / f"s01_entry_v3_exact_inputs_{args.date}.jsonl"
    )
    command = (
        f'C:\\python310\\python.exe -B -X utf8 '
        f'RUN\\s01_entry_v3_prod_replay_v1.py --date {args.date} '
        f'--input "{source}" --restart-log "{args.restart_log}" '
        f'--out "{args.out}"'
    )
    try:
        result = replay(source, args.date, args.restart_log, command)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "provenance": "[UNVERIFIED]", "status": "BLOCKED",
            "source": str(source), "production_code": "NOT_CHANGED",
            "date": args.date,
            "source_data": [str(source), str(args.restart_log)],
            "production_entry_point":
                "RUN/strategy_01_entry_runtime_v3.py:EntryRuntimeV3.process_batch",
            "performance_scope": "DECISION_ONLY",
            "command": command,
            "violations": [f"READ_ERROR:{exc}"],
        }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

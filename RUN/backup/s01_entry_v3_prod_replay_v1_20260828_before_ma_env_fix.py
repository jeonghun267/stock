# -*- coding: utf-8 -*-
"""Replay S01 v3 through the current production runtime using exact saved inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from strategy_01_entry_runtime_v3 import EntryRuntimeV3
from strategy_01_open_surge_signal_v2 import ShadowPoint


ROOT = Path(r"C:\stock_bot")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def replay(source: Path) -> dict[str, Any]:
    records = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result: dict[str, Any] = {
        "provenance": "[UNVERIFIED]", "status": "BLOCKED",
        "source": str(source), "production_entry_point":
        "RUN/strategy_01_entry_runtime_v3.py:EntryRuntimeV3.process_batch",
        "production_code": "NOT_CHANGED", "records": len(records),
        "ready_cases": 0, "violations": [],
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

    runtime = EntryRuntimeV3({"codes": {}})
    for index, record in enumerate(records, start=1):
        if record.get("schema") != "s01_entry_v3_exact_input_v1":
            result["violations"].append(f"BAD_SCHEMA:{index}")
            continue
        if (record.get("production_files") or {}) != expected_hashes:
            result["violations"].append(f"MIXED_PRODUCTION_HASH:{index}")
            continue
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
        if _canonical(actual_audit) != _canonical(expected_audit):
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
    args = parser.parse_args()
    source = args.input or (
        ROOT / "data" / "s01_entry_v3_exact_replay"
        / f"s01_entry_v3_exact_inputs_{args.date}.jsonl"
    )
    try:
        result = replay(source)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "provenance": "[UNVERIFIED]", "status": "BLOCKED",
            "source": str(source), "production_code": "NOT_CHANGED",
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

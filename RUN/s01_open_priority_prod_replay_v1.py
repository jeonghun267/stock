# -*- coding: utf-8 -*-
"""Replay preserved S01 trend ordering plus the production three-second gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_01_signal_contract_v2 as signal_contract
from strategy_01_signal_contract_v2 import order_signals, select_fresh_signals
from strategy_open_priority_v1 import OpenPriorityGate, S01

signal_contract.OPEN_PRIORITY_CAPTURE = False


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(audit: Path) -> dict:
    records = [
        json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = {
        "provenance": "[UNVERIFIED]",
        "source": str(audit),
        "records": len(records),
        "waits": 0,
        "completed": 0,
        "mixed_tier_windows": 0,
        "violations": [],
    }
    if not records:
        result["violations"].append("NO_PRESERVED_INPUT")
        return result

    for recorded_path, expected in records[0].get("production_files", {}).items():
        path = Path(recorded_path)
        if not path.exists() or _sha(path) != expected:
            result["violations"].append(f"PRODUCTION_HASH_CHANGED:{path}")

    with tempfile.TemporaryDirectory() as raw:
        gate = OpenPriorityGate(
            Path(raw) / "open_priority_state.json", mode="LIVE", wait_sec=3.0,
        )
        for record in records:
            if record.get("schema") != "s01_open_priority_replay_input_v1":
                result["violations"].append("BAD_SCHEMA")
                continue
            now = datetime.fromisoformat(record["captured_at"])
            config = record.get("config") or {}
            rows = select_fresh_signals(
                record.get("signal_payload") or {},
                now=now,
                max_age_sec=float(config.get("signal_max_age_sec") or 0),
                consumed=record.get("consumed_signals") or [],
            )
            rows = order_signals(rows, mode="LIVE")
            tiers = {str(row.get("s01_trend_tier") or "C") for row in rows}
            if len(rows) >= 2 and len(tiers) >= 2:
                result["mixed_tier_windows"] += 1
            decision = gate.evaluate(strategy_id=S01, rows=rows, now=now)
            if decision.waiting:
                result["waits"] += 1
            if decision.rows and not decision.waiting:
                result["completed"] += 1
                chosen = str(decision.rows[0].get("code") or "").zfill(6)
                expected = str(rows[0].get("code") or "").zfill(6)
                if chosen != expected:
                    result["violations"].append(
                        f"WRONG_TOP:{chosen}!={expected}"
                    )

    if result["waits"] == 0:
        result["violations"].append("THREE_SECOND_WAIT_NOT_OBSERVED")
    if result["completed"] == 0:
        result["violations"].append("WINDOW_COMPLETION_NOT_OBSERVED")
    if result["mixed_tier_windows"] == 0:
        result["violations"].append("A_B_C_COMPARISON_NOT_OBSERVED")
    if not result["violations"]:
        result["provenance"] = "[PROD_REPLAY]"
        result["status"] = "PASS"
    else:
        result["status"] = "BLOCKED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = replay(args.audit)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "provenance": "[UNVERIFIED]", "status": "BLOCKED",
            "source": str(args.audit), "violations": [f"READ_ERROR:{exc}"],
        }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Replay the approved S01 ABOVE_OPEN promotion through production functions."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_01_signal_contract_v2 as signal_contract
from strategy_01_open_surge_signal_v2 import promote_above_open_rebreak_live
from strategy_01_signal_contract_v2 import (
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    select_fresh_signals,
)

signal_contract.OPEN_PRIORITY_CAPTURE = False

DECISION_KEYS = (
    "ts", "code", "price", "action", "reason", "entry_stage",
    "requested_quantity", "signal_sequence", "mode",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source_hash = _sha(args.input)
    producer = RUN_DIR / "strategy_01_open_surge_signal_v2.py"
    contract = RUN_DIR / "strategy_01_signal_contract_v2.py"
    before_hashes = {str(producer): _sha(producer), str(contract): _sha(contract)}
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    signals = list(payload.get("signals") or [])
    expected_rows = [
        row for row in signals
        if str(row.get("entry_stage") or "") == "ABOVE_OPEN_REBREAK_LIVE"
    ]
    violations: list[str] = []
    if len(expected_rows) != 1:
        violations.append(f"EXPECTED_PROMOTED_COUNT:{len(expected_rows)}")
        expected = {}
    else:
        expected = expected_rows[0]

    try:
        decision_at = datetime.fromisoformat(str(expected.get("ts") or ""))
    except ValueError:
        decision_at = datetime.min
        violations.append("INVALID_DECISION_TS")

    existing = [row for row in signals if row is not expected]
    replayed = promote_above_open_rebreak_live(
        payload.get("shadow_signals") or [], existing, decision_at,
    )
    if replayed is None:
        violations.append("PROMOTION_NOT_REPRODUCED")
        replayed = {}
    for key in DECISION_KEYS:
        if replayed.get(key) != expected.get(key):
            violations.append(
                f"DECISION_MISMATCH:{key}:got={replayed.get(key)!r}:"
                f"expected={expected.get(key)!r}"
            )

    contract_payload = {
        "schema": SIGNAL_SCHEMA,
        "mode": SIGNAL_MODE,
        "date": decision_at.strftime("%Y%m%d"),
        "updated_at": decision_at.isoformat(timespec="seconds"),
        "signals": [replayed],
    }
    selected = select_fresh_signals(
        contract_payload,
        now=decision_at + timedelta(seconds=1),
        max_age_sec=5.0,
    )
    if len(selected) != 1:
        violations.append(f"CONTRACT_SELECTED_COUNT:{len(selected)}")
    elif selected[0].get("entry_stage") != "ABOVE_OPEN_REBREAK_LIVE":
        violations.append("CONTRACT_STAGE_MISMATCH")

    after_hashes = {str(producer): _sha(producer), str(contract): _sha(contract)}
    if before_hashes != after_hashes:
        violations.append("PRODUCTION_HASH_CHANGED_DURING_REPLAY")

    result = {
        "provenance": "[PROD_REPLAY]" if not violations else "[UNVERIFIED]",
        "status": "PASS" if not violations else "FAIL",
        "date": decision_at.strftime("%Y%m%d") if decision_at != datetime.min else "",
        "production_entry_points": [
            "RUN/strategy_01_open_surge_signal_v2.py::promote_above_open_rebreak_live",
            "RUN/strategy_01_signal_contract_v2.py::select_fresh_signals",
        ],
        "source": str(args.input.resolve()),
        "source_sha256": source_hash,
        "production_sha256": before_hashes,
        "decision_keys": {key: replayed.get(key) for key in DECISION_KEYS},
        "contract_selected": len(selected),
        "violations": violations,
        "performance_scope": "DECISION_ONLY",
        "command": (
            f"C:\\python310\\python.exe -B -X utf8 "
            f"RUN\\s01_above_open_prod_replay_v1.py --input {args.input} "
            f"--out {args.out}"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())

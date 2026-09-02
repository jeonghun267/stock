# -*- coding: utf-8 -*-
"""Exact decision-only production replay for S03 EARLY_LOW v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from s03_early_low_release_v1 import CONDITION_ID, DURATION, QUANTITY
from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_LANE, SIGNAL_MODE, SIGNAL_SCHEMA, select_fresh_signals,
)
from 골짜기_급반등 import EarlyLowDetector, MicroPoint

ENGINE_FILES = (
    "골짜기_급반등.py",
    "strategy_03_signal_contract_v1.py",
    "strategy_03_rotation_engine_v1.py",
    "s03_early_low_release_v1.py",
    "s03_early_low_3m_prod_replay_v2.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    report_path = Path(args.report).resolve()
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    detector = EarlyLowDetector()
    rows = []
    for item in raw["points"]:
        point = MicroPoint(
            ts=datetime.fromisoformat(item["ts"]),
            price=float(item["price"]),
            open_price=float(item["open_price"]),
            broker_day_low=float(item["broker_day_low"]),
            buy_money_cum=float(item.get("buy_money_cum") or 0.0),
            sell_money_cum=float(item.get("sell_money_cum") or 0.0),
        )
        rows.append(detector.feed(point, allow_signal=True))
    actions = [str(row.get("action") or "") for row in rows]
    expected = [str(value) for value in raw["expected_actions"]]
    signal = dict(rows[-1])
    signal.update({
        "code": str(raw["code"]), "name": str(raw["name"]),
        "entry_lane": EARLY_LOW_LANE, "signal_sequence": 1,
    })
    signal_ts = datetime.fromisoformat(signal["ts"])
    now = signal_ts + timedelta(seconds=1)
    payload = {
        "schema": SIGNAL_SCHEMA,
        "date": str(raw["trade_day"]),
        "updated_at": signal["ts"],
        "mode": SIGNAL_MODE,
        "signals": [signal],
    }
    contract = select_fresh_signals(payload, now=now, max_age_sec=5)
    selector = make_strategy03_signal_selector(
        input_path, 4.0, early_low_live_enabled=True,
        flow_turn_live_enabled=False, bottom_all_lanes_live_enabled=False,
    )
    selected = selector(payload, now=now, max_age_sec=5, consumed=[])
    passed = bool(
        actions == expected
        and signal.get("reason") == "S03_EARLY_LOW_3M_DROP_60S_REBOUND_2UP"
        and len(contract) == 1
        and len(selected) == 1
    )
    command = subprocess.list2cmdline([
        sys.executable, "-B", str(Path(__file__).resolve()),
        "--input", str(input_path), "--report", str(report_path),
    ])
    source_hashes = {str(input_path): sha256(input_path)}
    engine_hashes = {name: sha256(RUN / name) for name in ENGINE_FILES}
    report = {
        "schema": "s03_early_low_3m_prod_replay_v2",
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "performance_scope": "DECISION_ONLY",
        "strategy": "S03",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
        "date": str(raw["trade_day"]),
        "trade_date": str(raw["trade_day"]),
        "source_data": [str(input_path)],
        "source_audit_hash": source_hashes,
        "source_sha256": source_hashes,
        "production_entry_points": [
            str(RUN / "골짜기_급반등.py"),
            str(RUN / "strategy_03_signal_contract_v1.py"),
            str(RUN / "strategy_03_rotation_engine_v1.py"),
        ],
        "replay_engine_hash": engine_hashes,
        "replay_engine_sha256": engine_hashes,
        "command": command,
        "exact_command": command,
        "code_changed": "NOT_CHANGED",
        "candidate_pass_count": 1 if passed else 0,
        "decision_trace": actions,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, report_path)
    print(("[PROD_REPLAY] PASS" if passed else "[UNVERIFIED] FAIL"), report_path)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import hashlib
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
sys.path.insert(0, str(RUN))

from 골짜기_급반등 import EarlyLowDetector, MicroPoint  # noqa: E402
from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector  # noqa: E402
from strategy_03_signal_contract_v1 import EarlyLowAuditChain  # noqa: E402


DAY = "20260820"
SIGNAL_AUDIT = ROOT / "data" / "audit" / "s03_early_low" / f"s03_early_low_signal_{DAY}.jsonl"
ENGINE_AUDIT = ROOT / "data" / "audit" / "s03_early_low" / f"s03_early_low_engine_{DAY}.jsonl"
TARGETS = {"125490", "487400", "084370", "178320", "064760"}
EXPECTED = {
    "125490": False,
    "487400": True,
    "084370": True,
    "178320": False,
    "064760": False,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_rows(path: Path):
    ok, reason, records = EarlyLowAuditChain.verify_file(path)
    if not ok:
        raise RuntimeError(f"audit chain invalid: {path}: {reason}")
    return records


def main() -> int:
    detectors = {code: EarlyLowDetector() for code in TARGETS}
    generated = {}
    signal_mismatches = []
    signal_records = verified_rows(SIGNAL_AUDIT)
    engine_audit_records = verified_rows(ENGINE_AUDIT)
    for record in signal_records:
        code = str(record.get("code") or "").zfill(6)
        if code not in TARGETS:
            continue
        point = MicroPoint(
            ts=datetime.fromisoformat(record["snapshot_ts"]),
            price=float(record["current_price"]),
            buy_money_cum=float(record["buy_money_cum"]),
            sell_money_cum=float(record["sell_money_cum"]),
            broker_day_low=float(record["broker_day_low"]),
        )
        row = detectors[code].feed(point, allow_signal=bool(record["allow_signal"]))
        if row["action"] != record["action"] or row["reason"] != record["reason"]:
            signal_mismatches.append({
                "code": code,
                "ts": record["snapshot_ts"],
                "expected": [record["action"], record["reason"]],
                "actual": [row["action"], row["reason"]],
            })
        if record["action"] == "BUY_READY":
            generated[code] = row

    engine_records = {}
    for record in engine_audit_records:
        code = str(record.get("code") or "").zfill(6)
        if code in TARGETS and record.get("selector_pass") is True and code not in engine_records:
            engine_records[code] = record

    selected = {}
    with tempfile.TemporaryDirectory(prefix="s03_flow_turn_replay_") as temp:
        scratch = Path(temp)
        os.environ["S03_EARLY_LOW_AUDIT_DIR"] = str(scratch / "audit")
        for code in sorted(TARGETS):
            record = engine_records[code]
            merged = dict(record["signal_row"])
            merged.update({
                key: value for key, value in generated[code].items()
                if key.startswith("flow_")
            })
            same_rows = []
            for item in record["same_code_signals"]:
                same_rows.append(
                    merged if str(item.get("ts") or "") == str(record["signal_ts"])
                    else dict(item)
                )
            payload = {
                **dict(record["payload_meta"]),
                "signals": same_rows,
            }
            snapshot = scratch / f"snapshot_{code}.json"
            snapshot.write_text(json.dumps({"codes": {code: record["snapshot_raw"]}}), encoding="utf-8")
            selector = make_strategy03_signal_selector(
                snapshot,
                float(record["snapshot_max_age_sec"]),
                early_low_live_enabled=True,
                flow_turn_live_enabled=True,
            )
            output = selector(
                payload,
                now=datetime.fromisoformat(record["decision_now"]),
                max_age_sec=float(record["max_age_sec"]),
                consumed=record["consumed"],
            )
            selected[code] = any(
                str(row.get("code") or "").zfill(6) == code for row in output
            )

    early_pass = not signal_mismatches and selected == EXPECTED
    report = {
        "provenance": "[PROD_REPLAY]" if early_pass else "[UNVERIFIED]",
        "status": "PASS" if early_pass else "FAIL",
        "scope": "S03 EARLY_LOW only; OPEN_CRASH and INTRADAY are unchanged",
        "date": DAY,
        "production_changed": "CHANGED",
        "production_entry_points": [
            "RUN/골짜기_급반등.py::EarlyLowDetector.feed",
            "RUN/strategy_03_rotation_engine_v1.py::make_strategy03_signal_selector",
        ],
        "source_data": [str(SIGNAL_AUDIT), str(ENGINE_AUDIT)],
        "source_sha256": {
            str(SIGNAL_AUDIT): sha256(SIGNAL_AUDIT),
            str(ENGINE_AUDIT): sha256(ENGINE_AUDIT),
        },
        "capture_production_sha256": {
            "signal": signal_records[0]["prod_sha"],
            "engine": engine_audit_records[0]["prod_sha"],
        },
        "replay_engine_sha256": {
            str(RUN / "골짜기_급반등.py"): sha256(RUN / "골짜기_급반등.py"),
            str(RUN / "strategy_03_rotation_engine_v1.py"): sha256(RUN / "strategy_03_rotation_engine_v1.py"),
            str(RUN / "strategy_03_signal_contract_v1.py"): sha256(RUN / "strategy_03_signal_contract_v1.py"),
        },
        "early_low_exact_replay": {
            "status": "PASS" if early_pass else "FAIL",
            "signal_mismatches": signal_mismatches,
            "selected": selected,
        },
        "excluded_scope": (
            "237690 OPEN_CRASH actual order-gate snapshot was not preserved; "
            "therefore FLOW_TURN_FAST is not applied to OPEN_CRASH"
        ),
        "command": r"C:\python310\python.exe -B -X utf8 tests\prod_replay_s03_flow_turn_fast_20260820.py",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if early_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())

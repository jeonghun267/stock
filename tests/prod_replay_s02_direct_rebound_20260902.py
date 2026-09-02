# -*- coding: utf-8 -*-
"""Decision-only replay for the live S02 direct-rebound configuration."""
from __future__ import annotations
import csv, hashlib, json, os, sys
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
TESTS = ROOT / "tests"
for folder in (RUN, TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
os.environ["LOW_REBOUND_DIRECT"] = "YES"
import prod_replay_s02_exact_inputs_20260820 as base  # noqa: E402

DAY = "20260820"
INPUTS = ROOT / "data" / "s02_exact_replay" / f"s02_exact_inputs_{DAY}.csv"
OUT = ROOT / "reports" / "prod_replay_s02_direct_rebound_20260902.json"
PRODUCTION_FILES = {
    "signal_source": RUN / "strategy_02_low_buy_signal_v1.py",
    "direct_policy": RUN / "low_rebound_common_v1.py",
    "launcher": RUN / "hidden" / "SAFEPLUS_STRATEGY02_SIGNAL.cmd",
}
EXPECTED = [("2026-08-20T14:17:00", "131290", 240500.0, "S02_S06_DIRECT_REBOUND_V1")]

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def result_key(row):
    return (str(row.get("ts") or ""), str(row.get("code") or "").zfill(6), float(row.get("price") or 0.0), str(row.get("algorithm") or ""))

def main():
    with INPUTS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fired = base.replay(rows, adaptive=False)
    actual = [result_key(row) for row in fired]
    checks = {
        "preserved_inputs_present": bool(rows),
        "launcher_direct_enabled": "set LOW_REBOUND_DIRECT=YES" in PRODUCTION_FILES["launcher"].read_text(encoding="utf-8"),
        "exact_direct_decision": actual == EXPECTED,
        "direct_lane_only": bool(actual) and all(item[3] == "S02_S06_DIRECT_REBOUND_V1" for item in actual),
    }
    passed = all(checks.values())
    report = {
        "schema": "prod_replay_s02_direct_rebound_v1",
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "performance_scope": "DECISION_ONLY_SIGNAL_GENERATION",
        "date": DAY,
        "production_code_changed": "CHANGED",
        "production_entry_point": "RUN/strategy_02_low_buy_signal_v1.py::LowBuySignalMonitor.process_point",
        "source_data": [str(INPUTS)],
        "source_sha256": {str(INPUTS): sha256(INPUTS)},
        "production_sha256": {name: sha256(path) for name, path in PRODUCTION_FILES.items()},
        "replay_engine_sha256": sha256(Path(__file__)),
        "command": r"C:\python310\python.exe -B -X utf8 tests\prod_replay_s02_direct_rebound_20260902.py",
        "checks": checks,
        "raw_result": {"input_rows": len(rows), "expected": [list(x) for x in EXPECTED], "actual": [list(x) for x in actual]},
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"provenance": report["provenance"], "status": report["status"], "checks": checks}, ensure_ascii=False))
    return 0 if passed else 2

if __name__ == "__main__":
    raise SystemExit(main())
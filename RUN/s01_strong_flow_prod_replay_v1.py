# -*- coding: utf-8 -*-
"""Replay S01 STRONG_FLOW through the current production monitor."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ma3_backfill_v1 import CACHE_DIR as MA3_CACHE_DIR
from ma3_common_v1 import SEED_PATH, ma3_rows
from strategy_01_open_surge_signal_v2 import (
    OpenSurgeShadowMonitor,
    ShadowPoint,
)

PRODUCER = RUN_DIR / "strategy_01_open_surge_signal_v2.py"
PRODUCTION_PATHS = (
    PRODUCER,
    RUN_DIR / "strategy_01_open_surge_buy_v1.py",
    RUN_DIR / "ma3_common_v1.py",
    RUN_DIR / "listed_turnover_common_v1.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PreservedMA3:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {}
        self.sources: set[str] = set()
        self.support_hashes: dict[str, str] = {}

    def _remember(self, path: Path) -> None:
        if path.exists():
            self.support_hashes.setdefault(str(path.resolve()), _sha(path))

    def __call__(self, code: str) -> dict[str, Any] | None:
        self._remember(SEED_PATH)
        self._remember(MA3_CACHE_DIR / f"{str(code).zfill(6)}.json")
        row = ma3_rows(code, self.payload)
        if row:
            self.sources.add(str(row.get("source") or ""))
        return row


def replay(source: Path, trade_date: str, command: str) -> dict[str, Any]:
    violations: list[str] = []
    source_hash = _sha(source)
    capture_files: dict[str, str] | None = None
    capture_engine_hash = ""
    previous_capture: datetime | None = None
    record_count = 0
    point_count = 0
    ma3 = PreservedMA3()
    monitor = OpenSurgeShadowMonitor(ma3_provider=ma3)
    strong_decisions: list[dict[str, Any]] = []

    with source.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record_count += 1
            record = json.loads(line)
            if record.get("schema") != "s01_entry_v3_exact_input_v1":
                violations.append(f"BAD_SCHEMA:{index}")
                continue
            captured_at = datetime.fromisoformat(str(record.get("captured_at") or ""))
            if captured_at.strftime("%Y%m%d") != trade_date:
                violations.append(f"DATE_MISMATCH:{index}")
            if previous_capture is not None and captured_at < previous_capture:
                violations.append(f"TIME_DISORDER:{index}")
            previous_capture = captured_at

            record_files = {
                str(path): str(digest)
                for path, digest in (record.get("production_files") or {}).items()
            }
            if capture_files is None:
                capture_files = record_files
                for raw_path, digest in record_files.items():
                    if Path(raw_path).name == PRODUCER.name:
                        capture_engine_hash = digest
            elif record_files != capture_files:
                violations.append(f"MIXED_CAPTURE_HASH:{index}")

            ma3.payload = record.get("minute_payload") or {}
            points: list[ShadowPoint] = []
            for raw in record.get("points") or []:
                item = dict(raw)
                item["ts"] = datetime.fromisoformat(str(item.get("ts") or ""))
                points.append(ShadowPoint(**item))
            point_count += len(points)
            emitted = monitor.process_points(points)
            for row in emitted:
                if str(row.get("entry_stage") or "") != "STRONG_FLOW":
                    continue
                strong_decisions.append({
                    "ts": row.get("ts"),
                    "code": row.get("code"),
                    "entry_stage": row.get("entry_stage"),
                    "requested_quantity": row.get("requested_quantity"),
                    "rebound_pct": row.get("rebound_pct"),
                    "strong_dip_pct": row.get("strong_dip_pct"),
                    "strong_flow_gate": row.get("strong_flow_gate"),
                })

    capture_files = capture_files or {}
    if not capture_files:
        violations.append("CAPTURE_HASHES_MISSING")
    if not capture_engine_hash:
        violations.append("CAPTURE_ENGINE_HASH_MISSING")
    for raw_path, expected in capture_files.items():
        path = Path(raw_path)
        if path.name == PRODUCER.name:
            continue
        if not path.exists() or _sha(path) != expected:
            violations.append(f"CAPTURE_DEPENDENCY_CHANGED:{path}")
    if record_count == 0 or point_count == 0:
        violations.append("NO_PRESERVED_INPUT")
    if not strong_decisions:
        violations.append("NO_STRONG_READY_CASE_OBSERVED")
    for row in strong_decisions:
        if row.get("requested_quantity") != 1:
            violations.append(f"QUANTITY_MISMATCH:{row.get('code')}")
        if row.get("strong_flow_gate") != "READY":
            violations.append(f"GATE_MISMATCH:{row.get('code')}")

    support_after = {
        path: _sha(Path(path))
        for path in ma3.support_hashes
        if Path(path).exists()
    }
    if support_after != ma3.support_hashes:
        violations.append("MA3_SUPPORT_CHANGED_DURING_REPLAY")

    production_hashes = {
        str(path.resolve()): _sha(path) for path in PRODUCTION_PATHS
    }
    replay_engine_hash = production_hashes[str(PRODUCER.resolve())]
    replay_tool = Path(__file__).resolve()
    report = {
        "provenance": "[PROD_REPLAY]" if not violations else "[UNVERIFIED]",
        "status": "PASS" if not violations else "BLOCKED",
        "date": trade_date,
        "source_data": [str(source.resolve()), *sorted(ma3.support_hashes)],
        "source_sha256": source_hash,
        "capture_engine_sha256": capture_engine_hash,
        "replay_engine_sha256": replay_engine_hash,
        "production_entry_points": [
            "RUN/strategy_01_open_surge_signal_v2.py::OpenSurgeShadowMonitor.process_points",
            "RUN/strategy_01_open_surge_buy_v1.py::OpenSurgeBuyStrategy.evaluate",
        ],
        "production_code": "CHANGED",
        "sha256": {
            "source_audit": source_hash,
            "capture_engine": capture_engine_hash,
            "replay_engine": replay_engine_hash,
            "replay_tool": _sha(replay_tool),
            "production_dependencies": production_hashes,
            "ma3_support": ma3.support_hashes,
        },
        "records": record_count,
        "points": point_count,
        "ma3_sources": sorted(ma3.sources),
        "strong_ready_cases": len(strong_decisions),
        "strong_decisions": strong_decisions,
        "violations": violations,
        "performance_scope": "DECISION_ONLY",
        "command": command,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.input or (
        ROOT / "data" / "s01_entry_v3_exact_replay"
        / f"s01_entry_v3_exact_inputs_{args.date}.jsonl"
    )
    command = (
        f"C:\\python310\\python.exe -B -X utf8 "
        f"RUN\\s01_strong_flow_prod_replay_v1.py --date {args.date} "
        f"--input \"{source}\" --out \"{args.out}\""
    )
    try:
        report = replay(source, args.date, command)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        report = {
            "provenance": "[UNVERIFIED]",
            "status": "BLOCKED",
            "date": args.date,
            "source_data": str(source),
            "production_entry_point":
                "RUN/strategy_01_open_surge_signal_v2.py::OpenSurgeShadowMonitor.process_points",
            "violations": [f"READ_ERROR:{exc}"],
            "performance_scope": "DECISION_ONLY",
            "command": command,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

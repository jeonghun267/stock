# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import strategy_02_low_buy_signal_v1 as S02  # noqa: E402


LIVE_INPUTS = {
    "watch.json": ROOT / "IPC" / "micro_watch_strategy_shared.json",
    "snapshot.json": ROOT / "IPC" / "live_micro_snapshot.json",
    "names.json": ROOT / "data" / "_code_name_cache.json",
}
ENGINE = RUN / "strategy_02_low_buy_signal_v1.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_inputs(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, source in LIVE_INPUTS.items():
        shutil.copyfile(source, target / name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    capture_dir = args.capture_dir.resolve()
    if args.capture:
        capture_inputs(capture_dir)

    watch_path = capture_dir / "watch.json"
    snapshot_path = capture_dir / "snapshot.json"
    names_path = capture_dir / "names.json"
    watch = json.loads(watch_path.read_text(encoding="utf-8-sig"))
    replay_now = datetime.fromisoformat(str(watch["ts"]))
    points, load_status, watch_count, candidate_meta = S02.load_live_points(
        S02.SignalConfig(
            watch_path=watch_path,
            snapshot_path=snapshot_path,
            names_path=names_path,
        ),
        replay_now,
    )
    selected = S02._select_candidate_codes(watch, candidate_meta)
    high_range = {
        code for code, meta in candidate_meta.items()
        if meta.get("hr_rank") is not None
    }
    money_flow = {
        str(code).zfill(6)
        for code, tags in (watch.get("source_tags") or {}).items()
        if "moneyflow_selector" in set(tags or [])
    }
    overlap = high_range & money_flow
    overlap_prefix = selected[:min(len(overlap), len(selected))]
    checks = {
        "candidate_limit": len(selected) <= S02.S02_CANDIDATE_LIMIT,
        "candidate_count_matches_loader": watch_count == len(selected),
        "union_only": set(selected) <= high_range | money_flow,
        "overlap_first": set(overlap_prefix) == overlap,
        "unique_codes": len(selected) == len(set(selected)),
        "production_loader_reached": load_status in {"LIVE", "DATA_WAIT"},
    }
    passed = bool(selected) and all(checks.values())
    report_path = capture_dir / "prod_replay_s02_candidate_union_20260827.json"
    source_paths = [watch_path, snapshot_path, names_path]
    command = (
        "python -B -X utf8 tests\\prod_replay_s02_candidate_union_20260827.py "
        f"--capture-dir {capture_dir}"
    )
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "performance_scope": "DECISION_ONLY_CANDIDATE_SELECTION",
        "date": str(watch.get("for_date") or ""),
        "production_code_changed": "CHANGED",
        "production_entry_points": [
            "RUN/strategy_02_low_buy_signal_v1.py::load_live_points",
            "RUN/strategy_02_low_buy_signal_v1.py::_select_candidate_codes",
        ],
        "source_data": [str(path) for path in source_paths],
        "sha256": {
            str(path): sha256(path)
            for path in source_paths + [ENGINE, Path(__file__)]
        },
        "command": command,
        "raw_result": {
            "load_status": load_status,
            "candidate_count": len(selected),
            "high_range_count": len(high_range),
            "money_flow_count": len(money_flow),
            "overlap_count": len(overlap),
            "fresh_point_count": len(points),
            "selected_codes": selected,
            "checks": checks,
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "report": str(report_path),
        "provenance": report["provenance"],
        "status": report["status"],
        "candidate_count": len(selected),
        "overlap_count": len(overlap),
        "fresh_point_count": len(points),
        "checks": checks,
    }, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

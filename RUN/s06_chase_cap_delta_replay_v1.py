# -*- coding: utf-8 -*-
"""Replay one preserved S06 observation and validate only the approved cap delta."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\stock_bot")
RUN_DIR = ROOT / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from s06_exact_replay_v1 import replay_one  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _first_record(path: Path) -> tuple[dict[str, Any], bytes]:
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line.decode("utf-8")), line
    raise ValueError(f"EMPTY_INPUT:{path}")


def _capture_hash_and_contains(path: Path, target: bytes) -> tuple[str, int]:
    digest = hashlib.sha256()
    matches = 0
    with path.open("rb") as handle:
        for line in handle:
            digest.update(line)
            if line == target:
                matches += 1
    return digest.hexdigest(), matches


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--replay-input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    violations: list[str] = []
    original, original_line = _first_record(args.original)
    replay_record, _ = _first_record(args.replay_input)
    code = str(original.get("code") or "").zfill(6)

    capture_sha, source_matches = _capture_hash_and_contains(
        args.capture, original_line
    )
    if source_matches != 1:
        violations.append(f"SOURCE_RECORD_MATCH_COUNT:{source_matches}")

    expected_input = copy.deepcopy(original)
    old_cap = (expected_input.get("config") or {}).get("chase_cap_pct")
    (expected_input.get("config") or {})["chase_cap_pct"] = 2.5
    if old_cap != 2.0:
        violations.append(f"ORIGINAL_CAP_NOT_2P0:{old_cap}")
    if expected_input != replay_record:
        violations.append("REPLAY_INPUT_CHANGED_OUTSIDE_APPROVED_CAP")

    before = (
        ((replay_record.get("state_before") or {}).get("chase") or {}).get(code)
        or {}
    )
    low = float(before.get("low") or 0.0)
    price = float((replay_record.get("snapshot_rec") or {}).get("cur") or 0.0)
    rebound_pct = ((price / low) - 1.0) * 100.0 if low > 0 else -999.0
    if before.get("phase") != "OBSERVE":
        violations.append(f"INPUT_PHASE_NOT_OBSERVE:{before.get('phase')}")
    if not (2.0 < rebound_pct <= 2.5):
        violations.append(f"INPUT_NOT_IN_APPROVED_DELTA_BAND:{rebound_pct:.6f}")

    with tempfile.TemporaryDirectory(
        prefix="s06_cap_delta_", ignore_cleanup_errors=True
    ) as temporary:
        result = replay_one(replay_record, Path(temporary))

    if result.get("error"):
        violations.append(f"PRODUCTION_REPLAY_ERROR:{result['error']}")
    diffs = result.get("diffs") or []
    if [row.get("field") for row in diffs] != ["chase"]:
        violations.append("DIFF_OUTSIDE_CHASE_STATE")

    legacy = {}
    produced = {}
    if len(diffs) == 1 and diffs[0].get("field") == "chase":
        legacy = (diffs[0].get("expected") or {}).get(code) or {}
        produced = (diffs[0].get("produced") or {}).get(code) or {}
    if legacy.get("phase") != "CHASE" or float(
        legacy.get("dead_low") or 0.0
    ) != float(legacy.get("low") or -1.0):
        violations.append("LEGACY_2P0_GIVEUP_NOT_PROVEN")
    if produced.get("phase") != "OBSERVE" or float(
        produced.get("dead_low", -1.0)
    ) != 0.0:
        violations.append("CURRENT_2P5_DID_NOT_REMAIN_OBSERVE")

    changed_from_before = {
        key
        for key in set(before) | set(produced)
        if before.get(key) != produced.get(key)
    }
    if changed_from_before != {"first_rebound_peak"}:
        violations.append(
            "CURRENT_STATE_CHANGED_OUTSIDE_PEAK:" + ",".join(
                sorted(changed_from_before)
            )
        )
    if float(produced.get("first_rebound_peak") or 0.0) != price:
        violations.append("CURRENT_PEAK_NOT_CURRENT_PRICE")

    engine_path = RUN_DIR / "strategy_06_crash_low_chase_v1.py"
    base_replay_path = RUN_DIR / "s06_exact_replay_v1.py"
    command = shlex.join([sys.executable, str(Path(__file__).resolve())] + sys.argv[1:])
    passed = not violations
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "BLOCKED",
        "date": str(replay_record.get("state_date") or ""),
        "source_data": [
            str(args.capture.resolve()),
            str(args.original.resolve()),
            str(args.replay_input.resolve()),
        ],
        "source_sha256": _sha256(args.replay_input),
        "production_entry_point": (
            "RUN/strategy_06_crash_low_chase_v1.py::"
            "Strategy06Engine._chase_tick"
        ),
        "production_code": "CHANGED",
        "sha256": {
            "capture": capture_sha,
            "original_extract": _sha256(args.original),
            "replay_input": _sha256(args.replay_input),
            "production_engine": _sha256(engine_path),
            "base_replay_engine": _sha256(base_replay_path),
            "delta_replay_engine": _sha256(Path(__file__).resolve()),
        },
        "comparison_scope": "APPROVED_CHASE_CAP_DELTA_ONLY",
        "source_record_match_count": source_matches,
        "scenario_count": 1,
        "approved_change": {
            "field": "chase_cap_pct",
            "before": old_cap,
            "after": 2.5,
        },
        "decision": {
            "code": code,
            "timestamp": replay_record.get("now_iso"),
            "input_rebound_pct": round(rebound_pct, 6),
            "legacy_phase": legacy.get("phase"),
            "current_phase": produced.get("phase"),
            "current_dead_low": produced.get("dead_low"),
            "current_first_rebound_peak": produced.get("first_rebound_peak"),
            "raw_legacy_match": bool(result.get("match")),
        },
        "violations": violations,
        "performance_scope": "DECISION_ONLY",
        "command": command,
    }
    _write_report(args.out, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Decision-only replay for the S01 PULLBACK live-promotion boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
RUN_DIR = ROOT / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_open_surge_signal_v2 import promote_pullback_live


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    command = (
        f'C:\\python310\\python.exe -B -X utf8 '
        f'RUN\\s01_pullback_live_prod_replay_v1.py --date {args.date} '
        f'--input "{args.input}" --out "{args.out}"'
    )
    production_file = RUN_DIR / "strategy_01_open_surge_signal_v2.py"
    violations: list[str] = []
    existing: list[dict] = []
    source_codes: set[str] = set()
    promoted_codes: list[str] = []
    records = [
        json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for index, record in enumerate(records, start=1):
        rows = list(record.get("expected_signals") or [])
        for row in rows:
            if str(row.get("stage") or "") == "PULLBACK":
                source_codes.add(str(row.get("code") or "").zfill(6))
        promoted = promote_pullback_live(rows, existing, enabled=True)
        if promoted is None:
            continue
        if promoted not in [
            {**row, "entry_stage": "PULLBACK", "requested_quantity": 1,
             "signal_sequence": 1, "mode": "SIGNAL_ONLY_ORDER_ZERO"}
            for row in rows if str(row.get("stage") or "") == "PULLBACK"
        ]:
            violations.append(f"NON_SOURCE_PROMOTION:{index}")
        if str(promoted.get("entry_stage") or "") != "PULLBACK":
            violations.append(f"BAD_STAGE:{index}")
        if int(promoted.get("requested_quantity") or 0) != 1:
            violations.append(f"BAD_QUANTITY:{index}")
        promoted_codes.append(str(promoted.get("code") or "").zfill(6))
        existing.append(promoted)
    expected_count = min(3, len(source_codes))
    if not source_codes:
        violations.append("NO_PRESERVED_PULLBACK_INPUT")
    if len(promoted_codes) != expected_count:
        violations.append(
            f"PROMOTION_COUNT_MISMATCH:{len(promoted_codes)}!={expected_count}"
        )
    if len(set(promoted_codes)) != len(promoted_codes):
        violations.append("DUPLICATE_CODE_PROMOTION")
    first_rows = next(
        (list(row.get("expected_signals") or []) for row in records
         if any(str(item.get("stage") or "") == "PULLBACK"
                for item in row.get("expected_signals") or [])),
        [],
    )
    if promote_pullback_live(first_rows, [], enabled=False) is not None:
        violations.append("DISABLED_GATE_PROMOTED")
    report = {
        "provenance": "[PROD_REPLAY]",
        "status": "PASS" if not violations else "BLOCKED",
        "date": args.date,
        "source": str(args.input),
        "source_data": [str(args.input)],
        "production_entry_point":
            "RUN/strategy_01_open_surge_signal_v2.py:promote_pullback_live",
        "production_code": "CHANGED",
        "performance_scope": "DECISION_ONLY",
        "command": command,
        "sha256": {
            "source": sha256(args.input),
            "replay_tool": sha256(Path(__file__)),
            "production_files": {str(production_file): sha256(production_file)},
        },
        "records": len(records),
        "preserved_pullback_codes": len(source_codes),
        "promoted_codes": len(promoted_codes),
        "quantity": 1,
        "daily_code_cap": 3,
        "violations": violations,
    }
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""거래 결과 보고서가 사용자에게 인용 가능한지 fail-closed로 판정한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PERFORMANCE_TOKENS = ("gross", "net_pnl", "pnl", "profit", "loss", "return", "drawdown")


def _performance_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(token in str(key).lower() for token in PERFORMANCE_TOKENS):
                found.append(path)
            found.extend(_performance_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_performance_keys(item, f"{prefix}[{index}]"))
    return found


def validate(report: dict[str, Any]) -> tuple[bool, str]:
    provenance = report.get("provenance")
    if provenance not in {"[BROKER_FILL]", "[PROD_REPLAY]"}:
        return False, f"NON_QUOTABLE_PROVENANCE {provenance or 'MISSING'}"
    if not report.get("date") or not report.get("source_data"):
        return False, "MISSING_DATE_OR_SOURCE"
    if provenance == "[BROKER_FILL]":
        required = ("timestamp", "code", "price", "quantity")
        missing = [key for key in required if report.get(key) in (None, "")]
        return (not missing, "PASS" if not missing else f"MISSING_BROKER_FIELDS {','.join(missing)}")

    if report.get("status") != "PASS" or not report.get("command"):
        return False, "PROD_REPLAY_NOT_PASS_OR_COMMAND_MISSING"
    if not (report.get("production_entry_point") or report.get("production_entry_points")):
        return False, "MISSING_PRODUCTION_ENTRY_POINT"
    has_hashes = bool(report.get("sha256")) or bool(
        report.get("source_sha256") and report.get("replay_engine_sha256")
    )
    if not has_hashes:
        return False, "MISSING_REQUIRED_HASHES"
    performance = _performance_keys(report)
    if performance and report.get("performance_scope") != "FULL_ENTRY_EXIT":
        return False, f"PERFORMANCE_SCOPE_NOT_FULL_ENTRY_EXIT {performance[0]}"
    return True, "PASS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    args = parser.parse_args()
    path = Path(args.report)
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    ok, reason = validate(report)
    print(json.dumps({"quotable": ok, "reason": reason, "report": str(path)}, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

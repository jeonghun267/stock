# -*- coding: utf-8 -*-
"""Replay an exact sell-boundary audit through the current production engine."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

RUN = Path(__file__).resolve().parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from hold_sell_audit_v1 import (
    AuditError,
    load_verified_rows,
    sha256_file,
    sha256_files,
)
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)


REPORT_SCHEMA = "verified_hold_sell_replay_v1"
PROVENANCE = "[PROD_REPLAY]"
ENGINE_PATH = RUN / "strategy_common_hold_sell_v1.py"
STRATEGY03_ENGINE_PATH = RUN / "strategy_03_rotation_engine_v1.py"
DEFAULT_REPORT_ROOT = Path(r"C:\stock_bot\reports\verified_replay")


def _production_engine(strategy_id: StrategyId):
    if strategy_id is StrategyId.VALLEY_MORNING_CRASH:
        from strategy_03_rotation_engine_v1 import Strategy03HoldSellEngine

        return (
            Strategy03HoldSellEngine(),
            [ENGINE_PATH, STRATEGY03_ENGINE_PATH],
        )
    return UnifiedHoldSellEngine(), [ENGINE_PATH]


def _decimal_pct(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return ""
    return f"{((numerator / denominator) - Decimal('1')) * Decimal('100'):.4f}"


def _drawdown_pct(peak: Decimal, price: Decimal) -> str:
    if peak <= 0:
        return ""
    return f"{((peak - price) / peak) * Decimal('100'):.4f}"


def replay_audit(
    audit_path: Path,
    *,
    report_root: Path = DEFAULT_REPORT_ROOT,
    command: Optional[str] = None,
) -> tuple[Path, dict[str, Any]]:
    audit_path = Path(audit_path).resolve()
    rows = load_verified_rows(audit_path)
    expected_fields = {item.name for item in fields(HoldSellObservation)}
    for index, row in enumerate(rows, 1):
        observed = set((row.get("observation") or {}).keys())
        missing = sorted(expected_fields - observed)
        if missing:
            raise AuditError(
                f"observation fields missing at sequence {index}: {missing}"
            )

    initial = rows[0]["state_before"]
    state = HoldSellState.from_dict(initial)
    engine, replay_engine_paths = _production_engine(state.strategy_id)
    prior_time: Optional[datetime] = None
    trace: list[dict[str, Any]] = []
    last_signature: tuple[str, str] | None = None
    mismatches: list[dict[str, Any]] = []
    sell = None
    replayed = 0

    for row in rows:
        observation_payload = dict(row["observation"])
        observation_payload["observed_at"] = datetime.fromisoformat(
            str(observation_payload["observed_at"])
        )
        observation = HoldSellObservation(**observation_payload)
        if prior_time is not None and observation.observed_at <= prior_time:
            raise AuditError("observation timestamps are not strictly increasing")
        prior_time = observation.observed_at
        decision = engine.evaluate(state, observation)
        replayed += 1
        captured = row.get("decision") or {}
        captured_action = str(captured.get("action") or "")
        captured_reason = str(captured.get("reason") or "")
        if (
            captured_action != decision.action.value
            or captured_reason != decision.reason
        ):
            mismatches.append({
                "sequence": row["sequence"],
                "observed_at": observation.observed_at.isoformat(),
                "captured_action": captured_action,
                "captured_reason": captured_reason,
                "replay_action": decision.action.value,
                "replay_reason": decision.reason,
            })
        signature = (decision.action.value, decision.reason)
        if signature != last_signature or decision.should_sell:
            trace.append({
                "observed_at": decision.observed_at.isoformat(),
                "price": str(decision.price),
                "action": decision.action.value,
                "reason": decision.reason,
            })
            last_signature = signature
        if decision.should_sell:
            sell = decision
            break

    replay_hash = sha256_files(replay_engine_paths)
    audit_hash = sha256_file(audit_path)
    capture_hash = str(rows[0]["engine_sha256"])
    entry_price = state.entry_price
    report = {
        "schema": REPORT_SCHEMA,
        "provenance": PROVENANCE,
        "status": "PASS",
        "generated_at": datetime.now().astimezone().isoformat(),
        "command": command or " ".join(sys.argv),
        "audit_path": str(audit_path),
        "audit_sha256": audit_hash,
        "capture_engine_sha256": capture_hash,
        "replay_engine_path": str(replay_engine_paths[0].resolve()),
        "replay_engine_paths": [
            str(path.resolve()) for path in replay_engine_paths
        ],
        "replay_engine_sha256": replay_hash,
        "production_code_changed": capture_hash != replay_hash,
        "audit_rows_verified": True,
        "capture_replay_mismatches": mismatches,
        "date": rows[0]["observation"]["observed_at"][:10],
        "code": state.code,
        "strategy_id": state.strategy_id.value,
        "position_id": state.position_id,
        "observations_total": len(rows),
        "observations_replayed": replayed,
        "entry_at": state.entry_at.isoformat(),
        "entry_price": str(entry_price),
        "peak_price": str(state.peak_price),
        "decision_trace": trace,
        "sell": None,
    }
    if sell is not None:
        report["sell"] = {
            "observed_at": sell.observed_at.isoformat(),
            "price": str(sell.price),
            "action": sell.action.value,
            "reason": sell.reason,
            "gross_return_pct": _decimal_pct(sell.price, entry_price),
            "peak_giveback_pct": _drawdown_pct(state.peak_price, sell.price),
        }

    date_text = report["date"].replace("-", "")
    filename = (
        f"{state.code}__{state.position_id}__{replay_hash[:12]}.json"
        .replace(":", "_")
        .replace("/", "_")
    )
    target = Path(report_root) / date_text / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    args = parser.parse_args()
    command = " ".join(sys.argv)
    try:
        target, report = replay_audit(
            args.audit,
            report_root=args.report_root,
            command=command,
        )
    except AuditError as exc:
        print(json.dumps({
            "provenance": "[UNVERIFIED]",
            "status": "FAIL",
            "error": str(exc),
        }, ensure_ascii=False))
        return 2
    print(json.dumps({
        "provenance": report["provenance"],
        "status": report["status"],
        "report": str(target),
        "code": report["code"],
        "sell": report["sell"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

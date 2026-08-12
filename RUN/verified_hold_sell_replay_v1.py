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
from typing import Any, Mapping, Optional

RUN = Path(__file__).resolve().parent
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from hold_sell_audit_v1 import (
    AuditError,
    load_verified_post_exit_rows,
    load_verified_rows,
    sha256_file,
    sha256_files,
)
from strategy_common_hold_sell_v1 import (
    HoldSellConfig,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profiles_from_runtime_snapshot,
)


REPORT_SCHEMA = "verified_hold_sell_replay_v1"
PROVENANCE = "[PROD_REPLAY]"
ENGINE_PATH = RUN / "strategy_common_hold_sell_v1.py"
STRATEGY03_ENGINE_PATH = RUN / "strategy_03_rotation_engine_v1.py"
DEFAULT_REPORT_ROOT = Path(r"C:\stock_bot\reports\verified_replay")


def _production_engine(
    strategy_id: StrategyId,
    *,
    s02_afternoon_soft_loss: bool = False,
    runtime_profile: Optional[Mapping[str, Any]] = None,
):
    if strategy_id is StrategyId.VALLEY_MORNING_CRASH:
        from strategy_03_rotation_engine_v1 import Strategy03HoldSellEngine

        return (
            Strategy03HoldSellEngine(),
            [ENGINE_PATH, STRATEGY03_ENGINE_PATH],
        )
    profiles = None
    if runtime_profile:
        try:
            profiles = strategy_profiles_from_runtime_snapshot(runtime_profile)
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError(f"invalid captured runtime profile: {exc}") from exc
    return UnifiedHoldSellEngine(
        HoldSellConfig(
            s02_afternoon_soft_loss_enabled=s02_afternoon_soft_loss,
        ),
        profiles=profiles,
    ), [ENGINE_PATH]


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
    post_exit_audit_path: Optional[Path] = None,
    s02_afternoon_soft_loss: bool = False,
    report_root: Path = DEFAULT_REPORT_ROOT,
    command: Optional[str] = None,
) -> tuple[Path, dict[str, Any]]:
    audit_path = Path(audit_path).resolve()
    rows = load_verified_rows(audit_path)
    runtime_profile = dict(rows[0].get("runtime_profile") or {})
    if any(
        dict(row.get("runtime_profile") or {}) != runtime_profile
        for row in rows[1:]
    ):
        raise AuditError("runtime profile changes inside one audit stream")
    post_exit_rows: list[dict[str, Any]] = []
    resolved_post_exit_path: Optional[Path] = None
    if post_exit_audit_path is not None:
        resolved_post_exit_path = Path(post_exit_audit_path).resolve()
        post_exit_rows = load_verified_post_exit_rows(resolved_post_exit_path)
    expected_fields = {item.name for item in fields(HoldSellObservation)}
    for index, row in enumerate(rows + post_exit_rows, 1):
        observed = set((row.get("observation") or {}).keys())
        missing = sorted(expected_fields - observed)
        if missing:
            raise AuditError(
                f"observation fields missing at sequence {index}: {missing}"
            )

    initial = rows[0]["state_before"]
    state = HoldSellState.from_dict(initial)
    if post_exit_rows:
        first_post_exit = post_exit_rows[0]
        post_identity = (
            str(first_post_exit.get("strategy_id") or ""),
            str(first_post_exit.get("code") or ""),
            str(first_post_exit.get("position_id") or ""),
        )
        state_identity = (
            state.strategy_id.value,
            state.code,
            state.position_id,
        )
        if post_identity != state_identity:
            raise AuditError("post-exit audit position does not match hold/sell audit")
        last_primary_at = datetime.fromisoformat(
            str(rows[-1]["observation"]["observed_at"])
        )
        first_post_at = datetime.fromisoformat(
            str(first_post_exit["observation"]["observed_at"])
        )
        if first_post_at <= last_primary_at:
            raise AuditError("post-exit audit overlaps the primary audit")
    engine, replay_engine_paths = _production_engine(
        state.strategy_id,
        s02_afternoon_soft_loss=s02_afternoon_soft_loss,
        runtime_profile=runtime_profile,
    )
    prior_time: Optional[datetime] = None
    trace: list[dict[str, Any]] = []
    last_signature: tuple[str, str] | None = None
    mismatches: list[dict[str, Any]] = []
    sell = None
    replayed = 0

    replay_rows = [
        (row, True, "primary") for row in rows
    ] + [
        (row, False, "post_exit") for row in post_exit_rows
    ]
    post_exit_replayed = 0
    for row, has_captured_decision, source in replay_rows:
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
        if source == "post_exit":
            post_exit_replayed += 1
        if has_captured_decision:
            captured = row.get("decision") or {}
            captured_action = str(captured.get("action") or "")
            captured_reason = str(captured.get("reason") or "")
            if (
                captured_action != decision.action.value
                or captured_reason != decision.reason
            ):
                mismatch_kind = (
                    "ACTION"
                    if captured_action != decision.action.value
                    else "REASON"
                )
                mismatches.append({
                    "kind": mismatch_kind,
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
                "source": source,
            })
            last_signature = signature
        if decision.should_sell:
            sell = decision
            break

    replay_hash = sha256_files(replay_engine_paths)
    audit_hash = sha256_file(audit_path)
    capture_hash = str(rows[0]["engine_sha256"])
    entry_price = state.entry_price
    # ★[REPLAY-STATUS 2026-08-04] status 가 "PASS" 로 하드코딩돼 있었다.
    #   불일치를 capture_replay_mismatches 에 담아 놓고도 아무도 읽지 않아,
    #   verified_replay_gate_v1 의 status 검사가 항상 통과했다 = 재생이 실제
    #   판정과 어긋나도 승인되는 상태. 검증 도구가 검증을 안 하고 있었다.
    #   되돌리기: backup/verified_hold_sell_replay_v1_20260804_before_status_fix.py
    status = "PASS" if not mismatches else "FAIL"
    action_mismatch_count = sum(
        1 for mismatch in mismatches if mismatch["kind"] == "ACTION"
    )
    reason_mismatch_count = len(mismatches) - action_mismatch_count
    report = {
        "schema": REPORT_SCHEMA,
        "provenance": PROVENANCE,
        "status": status,
        "generated_at": datetime.now().astimezone().isoformat(),
        "command": command or " ".join(sys.argv),
        "audit_path": str(audit_path),
        "audit_sha256": audit_hash,
        "post_exit_audit_path": str(resolved_post_exit_path or ""),
        "post_exit_audit_sha256": (
            sha256_file(resolved_post_exit_path)
            if resolved_post_exit_path is not None else ""
        ),
        "capture_engine_sha256": capture_hash,
        "replay_engine_path": str(replay_engine_paths[0].resolve()),
        "replay_engine_paths": [
            str(path.resolve()) for path in replay_engine_paths
        ],
        "replay_engine_sha256": replay_hash,
        "production_code_changed": capture_hash != replay_hash,
        "s02_afternoon_soft_loss_enabled": s02_afternoon_soft_loss,
        "runtime_profile": runtime_profile,
        "audit_rows_verified": True,
        "capture_replay_mismatches": mismatches,
        "action_mismatch_count": action_mismatch_count,
        "reason_mismatch_count": reason_mismatch_count,
        "date": rows[0]["observation"]["observed_at"][:10],
        "code": state.code,
        "strategy_id": state.strategy_id.value,
        "position_id": state.position_id,
        "observations_total": len(rows) + len(post_exit_rows),
        "observations_replayed": replayed,
        "post_exit_observations_total": len(post_exit_rows),
        "post_exit_observations_replayed": post_exit_replayed,
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
    parser.add_argument("--post-exit-audit", type=Path)
    parser.add_argument("--s02-afternoon-soft-loss", action="store_true")
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    args = parser.parse_args()
    command = " ".join(sys.argv)
    try:
        target, report = replay_audit(
            args.audit,
            post_exit_audit_path=args.post_exit_audit,
            s02_afternoon_soft_loss=args.s02_afternoon_soft_loss,
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
        "mismatches": len(report["capture_replay_mismatches"]),
        "sell": report["sell"],
    }, ensure_ascii=False))
    # ★[REPLAY-STATUS 2026-08-04] FAIL 인데 종료코드 0 이면 예약작업·배치가
    #   성공으로 읽는다. 사람이 화면을 볼 때만 걸리는 검증은 검증이 아니다.
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())

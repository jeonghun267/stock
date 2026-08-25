# -*- coding: utf-8 -*-
"""전략 03 장초 레인 [PROD_REPLAY] — 감사 기록을 실제 생산 코드로 재생한다.

★[2026-08-12 친구님 승인 "영구 실전 연결"] 이 재생이 통과해야만
S03_EARLY_LOW_LIVE=YES 활성화가 허용된다.

원칙:
  - 조건을 별도 시뮬레이터로 재구현하지 않는다. 실제 생산 물건만 import 한다:
      EarlyLowDetector / MicroPoint      (RUN\\골짜기_급반등.py)
      select_fresh_signals               (RUN\\strategy_03_signal_contract_v1.py)
      make_strategy03_signal_selector    (RUN\\strategy_03_rotation_engine_v1.py)
  - 해시 사슬이 깨졌거나 필수 입력 필드가 하나라도 없으면 [UNVERIFIED] 중단.
  - 저장된 브로커 당일저가(broker_day_low>0) 입력이 하나도 없으면 [UNVERIFIED]
    (실전 자료 없이 통과를 선언할 수 없다).

종료코드: 0=PASS / 1=FAIL(재생 불일치) / 2=UNVERIFIED(자료 부족·사슬 손상)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_signal_contract_v1 import (
    EARLY_LOW_LANE,
    EarlyLowAuditChain,
    early_low_audit_dir,
    select_fresh_signals,
)

REBOUND_TOLERANCE = 1e-6

SIGNAL_REQUIRED = (
    "trade_day", "code", "hr_rank", "snapshot_ts", "current_price",
    "entry_lane", "snapshot_op", "snapshot_lo",
    "best_ask_px", "best_bid_px", "best_ask_qty", "best_bid_qty",
    "broker_day_low", "buy_money_cum", "sell_money_cum", "allow_signal",
    "pre_state", "anchor_low", "anchor_low_ts", "chase_blocked", "emitted",
    "rebound_pct", "flow_turn_ready", "flow_recent_buy_rate",
    "flow_recent_sell_rate", "flow_price_responding", "action", "reason",
    "signal_ts", "signal_ts_exact", "signal_price", "prod_sha",
)
PROFILE_MISSING_REQUIRED = (
    "trade_day", "event", "entry_lane", "code", "snapshot_ts",
    "current_price", "snapshot_op", "snapshot_lo", "buy_money_cum",
    "sell_money_cum", "best_ask_px", "best_bid_px", "best_ask_qty",
    "best_bid_qty", "anchor_low", "anchor_low_ts", "signal_ts",
    "signal_ts_exact", "action", "reason", "prod_sha",
)
PRE_STATE_REQUIRED = (
    "anchor_low", "anchor_low_ts", "chase_blocked", "emitted", "flow_points",
)
ENGINE_REQUIRED = (
    "trade_day", "code", "hr_rank", "signal_row", "same_code_signals",
    "payload_meta", "snapshot_raw", "snapshot_ts", "current_price",
    "broker_day_low", "anchor_low", "anchor_low_ts", "rebound_pct",
    "chase_blocked", "signal_ts", "signal_price", "decision_now",
    "max_age_sec", "snapshot_max_age_sec", "consumed",
    "early_low_live_enabled", "flow_turn_live_enabled", "order_mode",
    "contract_pass", "selector_pass", "candidate_selector_pass",
    "entry_lane", "snapshot_op", "snapshot_lo", "best_ask_px",
    "best_bid_px", "best_ask_qty", "best_bid_qty", "selector_ts",
    "selector_terminal_reason", "prod_sha",
)
PAYLOAD_META_REQUIRED = ("schema", "date", "updated_at", "mode")


def _fail_unverified(reason: str) -> int:
    print(f"[PROD_REPLAY] UNVERIFIED {reason}", flush=True)
    return 2


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _check_fields(record: Mapping[str, Any], required: tuple[str, ...],
                  where: str) -> str | None:
    for key in required:
        if key not in record:
            return f"MISSING_FIELD field={key} {where}"
    return None


def _replay_signal_record(record: Mapping[str, Any]) -> str | None:
    """None=일치, 아니면 불일치 설명."""
    from 골짜기_급반등 import EarlyLowDetector, MicroPoint

    pre = record["pre_state"]
    if not isinstance(pre, Mapping):
        return "pre_state not a mapping"
    raw_flow_points = pre.get("flow_points")
    if not isinstance(raw_flow_points, list):
        return "pre_state.flow_points not a list"
    flow_points = []
    for index, raw in enumerate(raw_flow_points):
        if not isinstance(raw, Mapping):
            return f"pre_state.flow_points[{index}] not a mapping"
        flow_ts = _parse_ts(raw.get("ts"))
        if flow_ts is None:
            return f"pre_state.flow_points[{index}].ts unparsable"
        try:
            flow_points.append(MicroPoint(
                ts=flow_ts,
                price=float(raw["price"]),
                buy_money_cum=float(raw["buy_money_cum"]),
                sell_money_cum=float(raw["sell_money_cum"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return f"pre_state.flow_points[{index}] invalid: {exc}"
    detector = EarlyLowDetector()
    detector.restore(
        float(pre.get("anchor_low") or 0.0),
        _parse_ts(pre.get("anchor_low_ts")),
        chase_blocked=bool(pre.get("chase_blocked")),
        emitted=bool(pre.get("emitted")),
        flow_points=flow_points,
    )
    ts = _parse_ts(record["snapshot_ts"])
    if ts is None:
        return "snapshot_ts unparsable"
    point = MicroPoint(
        ts=ts,
        price=float(record["current_price"]),
        buy_money_cum=float(record["buy_money_cum"]),
        sell_money_cum=float(record["sell_money_cum"]),
        broker_day_low=float(record["broker_day_low"]),
    )
    row = detector.feed(point, allow_signal=bool(record["allow_signal"]))
    state = detector.state
    checks = (
        ("action", str(row.get("action")), str(record["action"])),
        ("reason", str(row.get("reason")), str(record["reason"])),
        ("chase_blocked", bool(state.chase_blocked),
         bool(record["chase_blocked"])),
        ("emitted", bool(state.emitted), bool(record["emitted"])),
        ("flow_turn_ready", bool(row.get("flow_turn_ready")),
         bool(record["flow_turn_ready"])),
        ("flow_price_responding", bool(row.get("flow_price_responding")),
         bool(record["flow_price_responding"])),
    )
    for label, got, expected in checks:
        if got != expected:
            return f"{label} got={got} recorded={expected}"
    if abs(float(state.anchor_low) - float(record["anchor_low"])) > 1e-9:
        return (f"anchor_low got={state.anchor_low} "
                f"recorded={record['anchor_low']}")
    if abs(float(row.get("rebound_pct") or 0.0)
           - float(record["rebound_pct"])) > REBOUND_TOLERANCE:
        return (f"rebound_pct got={row.get('rebound_pct')} "
                f"recorded={record['rebound_pct']}")
    for label in ("flow_recent_buy_rate", "flow_recent_sell_rate"):
        got = float(row.get(label) or 0.0)
        expected = float(record[label])
        if abs(got - expected) > REBOUND_TOLERANCE:
            return f"{label} got={got} recorded={expected}"
    return None


def _replay_engine_record(
    record: Mapping[str, Any],
    scratch: Path,
) -> tuple[str | None, bool | None]:
    """(불일치 설명 또는 None, 활성화 가정 시 통과 여부)."""
    from strategy_03_rotation_engine_v1 import make_strategy03_signal_selector

    meta = record["payload_meta"]
    if not isinstance(meta, Mapping):
        return "payload_meta not a mapping", None
    missing = _check_fields(meta, PAYLOAD_META_REQUIRED, "in payload_meta")
    if missing:
        return missing, None
    now = _parse_ts(record["decision_now"])
    if now is None:
        return "decision_now unparsable", None
    code = str(record["code"]).zfill(6)
    key = (code, str(record["signal_ts"]))
    payload = {
        "schema": meta["schema"],
        "date": meta["date"],
        "updated_at": meta["updated_at"],
        "mode": meta["mode"],
        "signals": [dict(row) for row in record["same_code_signals"]],
    }
    consumed = [str(item) for item in (record["consumed"] or [])]
    contract_rows = select_fresh_signals(
        payload, now=now,
        max_age_sec=float(record["max_age_sec"]),
        consumed=consumed,
    )
    contract_ok = any(
        (str(row.get("code") or ""), str(row.get("ts") or "")) == key
        and str(row.get("entry_lane") or "") == EARLY_LOW_LANE
        for row in contract_rows
    )
    if contract_ok != bool(record["contract_pass"]):
        return (f"contract_pass got={contract_ok} "
                f"recorded={record['contract_pass']}"), None

    raw = record["snapshot_raw"]
    snapshot_path = scratch / f"snapshot_{code}_{record['seq']}.json"
    snapshot_path.write_text(
        json.dumps(
            {"codes": ({code: dict(raw)} if isinstance(raw, Mapping) else {})},
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    def _run_selector(enabled: bool) -> bool:
        selector = make_strategy03_signal_selector(
            snapshot_path,
            float(record["snapshot_max_age_sec"]),
            early_low_live_enabled=enabled,
            flow_turn_live_enabled=bool(record["flow_turn_live_enabled"]),
        )
        selected = selector(
            payload, now=now,
            max_age_sec=float(record["max_age_sec"]),
            consumed=consumed,
        )
        return any(
            (str(row.get("code") or ""), str(row.get("ts") or "")) == key
            for row in selected
        )

    selector_ok = _run_selector(bool(record["early_low_live_enabled"]))
    expected_mode = "LIVE" if record["early_low_live_enabled"] else "SHADOW_ORDER_ZERO"
    if str(record["order_mode"]) != expected_mode:
        return (f"order_mode recorded={record['order_mode']} "
                f"expected={expected_mode}"), None
    if selector_ok != bool(record["selector_pass"]):
        return (f"selector_pass got={selector_ok} "
                f"recorded={record['selector_pass']}"), None
    candidate_ok = _run_selector(True)
    if candidate_ok != bool(record["candidate_selector_pass"]):
        return (f"candidate_selector_pass got={candidate_ok} "
                f"recorded={record['candidate_selector_pass']}"), None
    terminal_reason = str(record.get("selector_terminal_reason") or "")
    if terminal_reason == "S03_PRICE_BELOW_10000":
        raw_price = abs(float((record.get("snapshot_raw") or {}).get("cur") or 0))
        if raw_price >= 10000 or candidate_ok:
            return "S03_PRICE_BELOW_10000 record is not fail-closed", None
    return None, candidate_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--audit-dir", default="")
    args = parser.parse_args()
    day = args.date
    audit_dir = Path(args.audit_dir) if args.audit_dir else early_low_audit_dir()

    signal_path = audit_dir / f"s03_early_low_signal_{day}.jsonl"
    engine_path = audit_dir / f"s03_early_low_engine_{day}.jsonl"
    if not signal_path.exists() and not engine_path.exists():
        return _fail_unverified(
            f"NO_AUDIT_DATA date={day} dir={audit_dir}")

    streams: dict[str, list[dict[str, Any]]] = {"signal": [], "engine": []}
    for stream, path in (("signal", signal_path), ("engine", engine_path)):
        if not path.exists():
            continue
        ok, reason, records = EarlyLowAuditChain.verify_file(path)
        if not ok:
            return _fail_unverified(
                f"CHAIN_INVALID stream={stream} reason={reason} path={path}")
        streams[stream] = records

    for record in streams["signal"]:
        required = (
            PROFILE_MISSING_REQUIRED
            if str(record.get("event") or "") == "PROFILE_MISSING"
            else SIGNAL_REQUIRED
        )
        missing = _check_fields(
            record, required, f"stream=signal seq={record.get('seq')}")
        if missing:
            return _fail_unverified(missing)
        if str(record.get("event") or "") == "PROFILE_MISSING":
            if not (
                str(record.get("entry_lane") or "") == EARLY_LOW_LANE
                and str(record.get("action") or "") == "WAIT"
                and str(record.get("reason") or "")
                == "S03_PRIOR_PROFILE_MISSING"
                and not str(record.get("signal_ts") or "")
            ):
                return _fail_unverified(
                    f"PROFILE_MISSING_INVALID seq={record.get('seq')}")
            continue
        pre = record.get("pre_state")
        if not isinstance(pre, Mapping):
            return _fail_unverified(
                f"MISSING_FIELD field=pre_state stream=signal "
                f"seq={record.get('seq')}")
        sub = _check_fields(
            pre, PRE_STATE_REQUIRED,
            f"in pre_state stream=signal seq={record.get('seq')}")
        if sub:
            return _fail_unverified(sub)
    for record in streams["engine"]:
        missing = _check_fields(
            record, ENGINE_REQUIRED, f"stream=engine seq={record.get('seq')}")
        if missing:
            return _fail_unverified(missing)

    # 실전 브로커 당일저가 입력 없이는 통과를 선언하지 않는다.
    day_low_records = [
        record for record in streams["signal"]
        if float(record.get("broker_day_low") or 0.0) > 0.0
    ]
    if not day_low_records:
        return _fail_unverified(
            f"NO_BROKER_DAY_LOW_INPUT date={day} "
            f"signal_records={len(streams['signal'])}")

    # 재생 중 selector 가 감사를 다시 쓰지 않도록 임시 폴더로 돌린다.
    mismatches: list[str] = []
    would_live_pass = 0
    with tempfile.TemporaryDirectory() as scratch_name:
        scratch = Path(scratch_name)
        os.environ["S03_EARLY_LOW_AUDIT_DIR"] = str(scratch / "replay_audit")
        for record in streams["signal"]:
            if str(record.get("event") or "") == "PROFILE_MISSING":
                continue
            problem = _replay_signal_record(record)
            if problem:
                mismatches.append(
                    f"stream=signal seq={record['seq']} "
                    f"code={record['code']} {problem}")
        for record in streams["engine"]:
            problem, would_live = _replay_engine_record(record, scratch)
            if problem:
                mismatches.append(
                    f"stream=engine seq={record['seq']} "
                    f"code={record['code']} {problem}")
            elif would_live:
                would_live_pass += 1

    fired = [
        record for record in streams["signal"]
        if str(record.get("action")) == "BUY_READY"
    ]
    profile_missing = [
        record for record in streams["signal"]
        if str(record.get("event") or "") == "PROFILE_MISSING"
    ]
    under_10000 = [
        record for record in streams["engine"]
        if str(record.get("selector_terminal_reason") or "")
        == "S03_PRICE_BELOW_10000"
    ]
    print(
        f"[PROD_REPLAY] date={day} signal_records={len(streams['signal'])} "
        f"engine_records={len(streams['engine'])} "
        f"day_low_inputs={len(day_low_records)} buy_ready={len(fired)} "
        f"would_pass_if_live={would_live_pass} "
        f"profile_missing={len(profile_missing)} "
        f"under_10000_blocked={len(under_10000)} broker_submit=0",
        flush=True,
    )
    if mismatches:
        for line in mismatches[:20]:
            print(f"[PROD_REPLAY] MISMATCH {line}", flush=True)
        print(
            f"[PROD_REPLAY] FAIL mismatches={len(mismatches)}", flush=True)
        return 1
    print("[PROD_REPLAY] PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

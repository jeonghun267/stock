# -*- coding: utf-8 -*-
"""S07M morning-trend shadow engine: order-zero capture, decision, and replay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(r"C:\stock_bot")
SIGNALS = ROOT / "data" / "trend_follow_start_ledger_v1" / "signal_codes_by_date.json"
MICRO = ROOT / "IPC" / "live_micro_snapshot.json"
WATCH = ROOT / "IPC" / "micro_watch_s07_morning.json"
DATA_DIR = ROOT / "data" / "strategy_07_morning_v1"
AUDIT_DIR = ROOT / "data" / "audit" / "s07_morning_entry"
REPLAY_DIR = ROOT / "reports" / "verified_replay" / "s07_morning"
LIVE_ORDERS_MODULE = ROOT / "RUN" / "s07_morning_live_orders_v1.py"
EVENT_FIELDS = ("ts", "strategy_id", "event", "code", "name", "price", "quantity", "reason")
DEFINITION_PRIORITY = ("CURRENT", "ALT_A_097_VALUE_1P5", "ALT_B_NO_BREAKOUT")
S07M_MAX_POS = 6
S07M_QUANTITY = 1
S07M_MIN_PRICE = 10000.0
S07M_TAKE_PROFIT_PCT = 3.0
S07M_STOP_LOSS_PCT = -2.0
S07M_ENTRY_START = dt_time(9, 0)
S07M_ENTRY_END = dt_time(9, 5, 59)
S07M_FORCE_EXIT = dt_time(11, 30)
S07M_MICRO_MAX_AGE_SEC = 30.0


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _engine_sha() -> str:
    payload = "|".join((_sha(Path(__file__).resolve()), _sha(LIVE_ORDERS_MODULE)))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _live_requested_and_verified(trade_date: str) -> tuple[bool, list[str]]:
    if os.environ.get("S07M_ARM", "NO").strip().upper() != "YES":
        return False, ["ARM_OFF"]
    if os.environ.get("S07M_LIVE", "NO").strip().upper() != "YES":
        return False, ["LIVE_OFF"]
    from live_owner_approval_guard_v1 import verify_live_hashes
    passed, errors = verify_live_hashes("S07M")
    if not passed:
        return False, errors
    replay_exit = replay_auto(trade_date)
    if replay_exit != 0:
        # ★[2026-09-02 친구님 승인(3회 확인) "내일이라도 실전"] 첫날 한정 대체 열쇠.
        #   AGENTS.md §5 Bootstrap exception (owner-only) 근거. 재생 검사 하나만
        #   대체한다 — ARM·LIVE·승인해시 검증은 위에서 이미 통과한 뒤다.
        #   값이 당일 trade_date 와 정확히 일치하는 하루만 유효, 이후 자동 실효.
        #   롤백: 런처에서 S07M_DAY1_OVERRIDE 줄 삭제.
        override = os.environ.get("S07M_DAY1_OVERRIDE", "").strip()
        if override and override == trade_date:
            event = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                     "status": "DAY1_OVERRIDE_USED", "trade_date": trade_date,
                     "replay_exit": replay_exit, "provenance": "[UNVERIFIED]",
                     "basis": "AGENTS.md §5 Bootstrap exception (owner-only)"}
            print(json.dumps(event, ensure_ascii=False))
            # 영구 감사기록 — 기록에 실패하면 실전도 거부한다(기록 없는 우회 금지).
            try:
                gate_log = AUDIT_DIR / trade_date / "live_gate.jsonl"
                gate_log.parent.mkdir(parents=True, exist_ok=True)
                with gate_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as exc:
                return False, [f"DAY1_OVERRIDE_AUDIT_WRITE_FAILED:{type(exc).__name__}"]
            return True, [f"DAY1_OVERRIDE_USED_REPLAY_EXIT_{replay_exit}"]
        return False, [f"PROD_REPLAY_EXIT_{replay_exit}"]
    return True, []


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _parse_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def load_candidates(trade_date: str) -> tuple[str, list[dict[str, Any]]]:
    payload = _read_json(SIGNALS)
    by_date = payload.get("signal_codes_by_date") or {}
    source_dates = sorted(date for date in by_date if str(date) < trade_date)
    if not source_dates:
        return "", []
    source_date = source_dates[-1]
    day = by_date.get(source_date) or {}
    definitions_by_code: dict[str, list[str]] = {}
    for definition in DEFINITION_PRIORITY:
        for raw in day.get(definition) or []:
            code = str(raw).zfill(6)
            definitions_by_code.setdefault(code, []).append(definition)
    ranked = sorted(
        definitions_by_code,
        key=lambda code: (
            min(DEFINITION_PRIORITY.index(item) for item in definitions_by_code[code]),
            code,
        ),
    )[:S07M_MAX_POS]
    return source_date, [
        {"code": code, "definitions": definitions_by_code[code]}
        for code in ranked
    ]


def prepare_watch(trade_date: str) -> tuple[str, list[dict[str, Any]]]:
    source_date, candidates = load_candidates(trade_date)
    payload = {
        "schema": "micro_watch_s07_morning_v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_date": source_date,
        "trade_date": trade_date,
        "codes": [row["code"] for row in candidates],
        "candidate_definitions": {row["code"]: row["definitions"] for row in candidates},
        "mode": "LIVE_CAPABLE_FAIL_CLOSED",
        "order_capable": True,
        "orders_sent": 0,
    }
    WATCH.parent.mkdir(parents=True, exist_ok=True)
    temporary = WATCH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(WATCH)
    return source_date, candidates


def _audit_paths(trade_date: str) -> tuple[Path, Path]:
    folder = AUDIT_DIR / trade_date
    return folder / "capture.jsonl", DATA_DIR / f"s07m_events_{trade_date}.csv"


def verify_chain(path: Path) -> tuple[bool, str, list[dict[str, Any]]]:
    if not path.exists():
        return True, "EMPTY", []
    previous = "0" * 64
    rows = []
    for expected_seq, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        claimed = str(row.pop("record_sha256", ""))
        expected = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
        if row.get("seq") != expected_seq or row.get("prev_sha256") != previous or claimed != expected:
            return False, f"CHAIN_MISMATCH_SEQ_{expected_seq}", []
        row["record_sha256"] = claimed
        rows.append(row)
        previous = claimed
    return True, "PASS", rows


class ChainWriter:
    def __init__(self, path: Path):
        ok, reason, rows = verify_chain(path)
        if not ok:
            raise RuntimeError(reason)
        self.path = path
        self.seq = len(rows)
        self.previous = rows[-1]["record_sha256"] if rows else "0" * 64
        self.rows = rows

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(payload)
        self.seq += 1
        row["seq"] = self.seq
        row["prev_sha256"] = self.previous
        digest = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
        row["record_sha256"] = digest
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        self.previous = digest
        self.rows.append(row)
        return row


def _read_events(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _append_event(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in EVENT_FIELDS})


class DecisionEngine:
    def __init__(self, candidates: list[dict[str, Any]]):
        self.candidates = {row["code"]: row for row in candidates}
        self.positions: dict[str, dict[str, Any]] = {}

    def process(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        code = str(row.get("code") or "").zfill(6)
        candidate = self.candidates.get(code)
        observed_at = _parse_dt(row.get("observed_at"))
        price = _number(row.get("cur"))
        day_open = _number(row.get("day_open"))
        if candidate is None or observed_at is None or price <= 0:
            return []
        state = self.positions.get(code)
        clock = observed_at.time()
        if state is None and S07M_ENTRY_START <= clock <= S07M_ENTRY_END:
            if price < S07M_MIN_PRICE:
                return []
            state = {
                "entry_ts": observed_at.isoformat(timespec="seconds"),
                "entry_price": price,
                "day_open": day_open,
                "closed": False,
            }
            self.positions[code] = state
            definitions = "+".join(candidate["definitions"])
            gap = ((price / day_open - 1.0) * 100.0) if day_open > 0 else 0.0
            return [{
                "ts": state["entry_ts"], "strategy_id": "S07_MORNING_SHADOW",
                "event": "SHADOW_ENTRY", "code": code, "name": row.get("name") or "",
                "price": price, "quantity": S07M_QUANTITY,
                "reason": (f"[HYPOTHETICAL] definitions={definitions} open={day_open:.0f} "
                           f"fill={price:.0f} open_fill_gap={gap:+.2f}% basis=first_fresh_quote"),
            }]
        if state is None or state["closed"]:
            return []
        entry = _number(state["entry_price"])
        change = (price / entry - 1.0) * 100.0
        reason = ""
        if clock >= S07M_FORCE_EXIT:
            reason = "TIME_1130"
        elif change >= S07M_TAKE_PROFIT_PCT:
            reason = "TAKE_PROFIT_3PCT"
        elif change <= S07M_STOP_LOSS_PCT:
            reason = "STOP_LOSS_2PCT"
        if not reason:
            return []
        state["closed"] = True
        state["exit_ts"] = observed_at.isoformat(timespec="seconds")
        state["exit_price"] = price
        return [{
            "ts": state["exit_ts"], "strategy_id": "S07_MORNING_SHADOW",
            "event": "SHADOW_EXIT", "code": code, "name": row.get("name") or "",
            "price": price, "quantity": S07M_QUANTITY,
            "reason": f"[HYPOTHETICAL] {reason} from_fill={change:+.2f}% orders_sent=0",
        }]


def _capture_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if row.get("record_type") == "DECISION_INPUT"]


def _simulate(candidates: list[dict[str, Any]], captures: list[dict[str, Any]]) -> tuple[DecisionEngine, list[dict[str, Any]]]:
    engine = DecisionEngine(candidates)
    events = []
    for row in captures:
        events.extend(engine.process(row))
    return engine, events


def _event_identity(row: Mapping[str, Any]) -> tuple:
    return (row.get("ts"), row.get("event"), str(row.get("code") or "").zfill(6),
            round(_number(row.get("price")), 4), int(_number(row.get("quantity"))))


def _fresh_inputs(now: datetime, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = _read_json(MICRO)
    codes = payload.get("codes") or {}
    output = []
    for candidate in candidates:
        code = candidate["code"]
        raw = codes.get(code) if isinstance(codes, Mapping) else None
        if not isinstance(raw, Mapping):
            continue
        source_ts = _parse_dt(raw.get("ts"))
        price = _number(raw.get("cur"))
        if source_ts is None or source_ts.date() != now.date() or price <= 0:
            continue
        age = now.timestamp() - source_ts.timestamp()
        if age < -5.0 or age > S07M_MICRO_MAX_AGE_SEC:
            continue
        output.append({
            "record_type": "DECISION_INPUT",
            "observed_at": now.astimezone().isoformat(timespec="seconds"),
            "source_ts": source_ts.isoformat(timespec="seconds"),
            "code": code,
            "name": str(raw.get("name") or ""),
            "definitions": candidate["definitions"],
            "cur": price,
            "day_open": _number(raw.get("op")),
            "best_bid_px": _number(raw.get("best_bid_px")),
            "best_ask_px": _number(raw.get("best_ask_px")),
            "cum_vol": _number(raw.get("cum_vol")),
            "buy_money_cum": _number(raw.get("buy_money_cum")),
            "sell_money_cum": _number(raw.get("sell_money_cum")),
            "che_str": _number(raw.get("che_str")),
        })
    return output


def run_shadow(trade_date: str, loop_sec: float, until: str) -> int:
    source_date, candidates = prepare_watch(trade_date)
    capture_path, event_path = _audit_paths(trade_date)
    writer = ChainWriter(capture_path)
    engine_hash = _engine_sha()
    if not writer.rows:
        writer.append({
            "record_type": "HEADER", "trade_date": trade_date,
            "source_date": source_date, "candidates": candidates,
            "engine_sha256": engine_hash, "order_capable": True,
            "orders_sent": 0, "rules": {"entry": "09:00-09:05 first fresh quote",
                "take_profit_pct": 3.0, "stop_loss_pct": -2.0, "force_exit": "11:30"},
        })
    header = writer.rows[0]
    if header.get("engine_sha256") != engine_hash:
        print(json.dumps({"status": "ENGINE_CHANGED_REBASELINE", "orders_sent": 0}, ensure_ascii=False))
        return 3
    engine, expected = _simulate(candidates, _capture_rows(writer.rows))
    actual = _read_events(event_path)
    if [_event_identity(row) for row in expected] != [_event_identity(row) for row in actual]:
        print(json.dumps({"status": "EVENT_REPLAY_MISMATCH", "orders_sent": 0}, ensure_ascii=False))
        return 4
    seen_source = {str(row.get("code")): str(row.get("source_ts")) for row in _capture_rows(writer.rows)}
    appended = 0
    live_ready, live_gate_errors = _live_requested_and_verified(trade_date)
    live_orders = None
    if live_ready:
        from s07_morning_live_orders_v1 import S07MLiveOrders
        live_orders = S07MLiveOrders(trade_date)
    end_clock = dt_time.fromisoformat(until)
    while True:
        now = datetime.now().astimezone()
        for row in _fresh_inputs(now, candidates):
            if seen_source.get(row["code"]) == row["source_ts"]:
                continue
            writer.append(row)
            seen_source[row["code"]] = row["source_ts"]
            for event in engine.process(row):
                _append_event(event_path, event)
                appended += 1
            if live_orders is not None:
                live_orders.process(row)
        if loop_sec <= 0 or now.time() >= end_clock:
            break
        time.sleep(loop_sec)
    print(json.dumps({
        "status": "PASS", "mode": "SHADOW_ORDER_ZERO", "trade_date": trade_date,
        "source_date": source_date, "candidates": candidates,
        "captures": len(_capture_rows(writer.rows)), "events_appended": appended,
        "order_capable": True, "live_ready": live_ready,
        "live_gate_errors": live_gate_errors,
        "orders_sent": live_orders.orders_sent if live_orders is not None else 0,
    }, ensure_ascii=False))
    return 0


def replay_auto(trade_date: str) -> int:
    folders = sorted(path for path in AUDIT_DIR.glob("20*") if path.name < trade_date)
    folders = [path for path in folders if (path / "capture.jsonl").exists()]
    if not folders:
        print(json.dumps({"status": "NO_SAVED_INPUT", "orders_sent": 0}, ensure_ascii=False))
        return 2
    folder = folders[-1]
    capture_path = folder / "capture.jsonl"
    ok, reason, records = verify_chain(capture_path)
    if not ok:
        print(json.dumps({"status": reason, "orders_sent": 0}, ensure_ascii=False))
        return 3
    header = records[0]
    engine_hash = _engine_sha()
    if header.get("engine_sha256") != engine_hash:
        print(json.dumps({"status": "ENGINE_CHANGED_REBASELINE", "orders_sent": 0}, ensure_ascii=False))
        return 4
    _, expected = _simulate(header.get("candidates") or [], _capture_rows(records))
    event_path = DATA_DIR / f"s07m_events_{folder.name}.csv"
    actual = _read_events(event_path)
    match = [_event_identity(row) for row in expected] == [_event_identity(row) for row in actual]
    report = {
        "provenance": "[PROD_REPLAY]", "status": "PASS" if match else "EVENT_MISMATCH",
        "performance_scope": "DECISION_ONLY", "production_entry_point": str(Path(__file__).resolve()),
        "engine_sha256": engine_hash, "saved_input": str(capture_path),
        "saved_input_sha256": _sha(capture_path), "chain_rows": len(records),
        "decision_events": len(expected), "orders_sent": 0,
        "repro_command": f"python {Path(__file__).resolve()} replay_auto --trade-date {trade_date}",
    }
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    out = REPLAY_DIR / f"s07m_replay_{folder.name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if match else 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("shadow", "prepare", "replay_auto"), nargs="?", default="shadow")
    parser.add_argument("--trade-date", default=f"{datetime.now():%Y%m%d}")
    parser.add_argument("--loop-sec", type=float, default=0.0)
    parser.add_argument("--until", default="11:35")
    args = parser.parse_args()
    if args.mode == "prepare":
        source_date, candidates = prepare_watch(args.trade_date)
        print(json.dumps({"status": "PASS", "source_date": source_date,
                          "candidates": candidates, "orders_sent": 0}, ensure_ascii=False))
        return 0
    if args.mode == "replay_auto":
        return replay_auto(args.trade_date)
    return run_shadow(args.trade_date, args.loop_sec, args.until)


if __name__ == "__main__":
    raise SystemExit(main())

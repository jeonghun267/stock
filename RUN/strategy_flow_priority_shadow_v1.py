"""Join existing strategy candidates with common money-flow tags (order zero)."""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(r"C:\stock_bot")
FLOW_BOARD = ROOT / "data" / "돈흐름_선별판.json"
HIGH_RANGE_DIRECTION = ROOT / "data" / "high_range_direction_shadow_v1.json"
MICRO_SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"
OUT_JSON = ROOT / "data" / "strategy_flow_priority_shadow_v1.json"
STATE_JSON = ROOT / "data" / "strategy_flow_priority_shadow_audit_state_v1.json"
RESULT_JSON = ROOT / "data" / "strategy_flow_priority_shadow_results_v1.json"
TRUTH_REPORT_DIR = ROOT / "data" / "strategy_flow_priority_truth_reports"
SOURCES = {
    "S01": ROOT / "data" / "strategy_01_open_surge_signal_v2.json",
    "S02": ROOT / "data" / "strategy_02_low_buy_signal_v1.json",
    "S03": ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json",
    "S04": ROOT / "data" / "strategy_04_pullback_signal_v1.json",
    "S05": ROOT / "data" / "strategy_05_base_breakout_signal_v1.json",
    "S06": ROOT / "data" / "strategy_06_crash_low_chase_state_v1.json",
    "S07": ROOT / "data" / "strategy_07_flow_trend_shadow_v1.json",
}
TREND_STRATEGIES = {"S01", "S04", "S05", "S07"}
EVENT_SOURCES = {
    "S01": ROOT / "data" / "strategy_01_rotation_v2",
    "S02": ROOT / "data" / "strategy_02_rotation_v1",
    "S03": ROOT / "data" / "strategy_03_rotation_v1",
    "S04": ROOT / "data" / "strategy_04_rotation_v1",
    "S05": ROOT / "data" / "strategy_05_rotation_v1",
    "S06": ROOT / "data" / "strategy_06_crash_low_chase",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        first = path.read_bytes()
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else ""


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def strategy_candidates(strategy: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if strategy in {"S01", "S02", "S03", "S04", "S05"}:
        raw = payload.get("candidates") or []
    elif strategy == "S06":
        raw = [dict(value, code=code) for code, value in (payload.get("chase") or {}).items()]
    elif strategy == "S07":
        raw = [row for row in (payload.get("slots") or []) if _code(row.get("code"))]
    else:
        raw = []
    output = []
    seen = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        code = _code(item.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        output.append(dict(item, code=code))
    return output


def _priority(strategy: str, state: str) -> tuple[int, str, str]:
    preferred = "유입지속" if strategy in TREND_STRATEGIES else "유입전환"
    secondary = "유입전환" if strategy in TREND_STRATEGIES else "유입지속"
    if state == preferred:
        return 2, "HIGH", f"{strategy}:{preferred} 우선"
    if state == secondary:
        return 1, "MEDIUM", f"{strategy}:{secondary} 참고"
    return 0, "BASE", f"{strategy}:기존 후보 유지"


def _high_range_bonus(strategy: str, direction: str) -> int:
    preferred = "상승지속" if strategy in TREND_STRATEGIES else "상승전환"
    secondary = "상승전환" if strategy in TREND_STRATEGIES else "상승지속"
    if direction == preferred:
        return 2
    if direction == secondary:
        return 1
    if direction in {"가짜반등의심", "진입함정", "보유실패"}:
        return -2
    if direction == "하락위험":
        return -1
    return 0


def _decorate_candidate(
    strategy: str, candidate: Mapping[str, Any], original_rank: int,
    flow_by_code: Mapping[str, Mapping[str, Any]],
    direction_by_code: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    code = _code(candidate.get("code"))
    flow = flow_by_code.get(code) or {}
    state = str(flow.get("common_flow_state") or "유입없음")
    if state not in {"유입지속", "유입전환", "유입없음"}:
        state = "유입없음"
    flow_bonus, priority, reason = _priority(strategy, state)
    direction_row = direction_by_code.get(code) or {}
    direction = str(direction_row.get("direction") or "확인대기")
    flow_accel = _float_or_none(flow.get("common_flow_accel_mkrw_per_min"))
    vwap_gap = _float_or_none(flow.get("common_vwap_gap_pct"))
    fake_warning = bool(direction_row.get("fake_rebound_warning"))
    fake_reasons = list(direction_row.get("fake_rebound_reasons") or [])
    absolute_weakness = bool(
        state == "유입없음"
        and flow_accel is not None and flow_accel < 0
        and vwap_gap is not None and vwap_gap < 0
    )
    inconsistent_continuing = bool(
        state == "유입지속"
        and flow_accel is not None and flow_accel <= 0
        and vwap_gap is not None and vwap_gap < 0
    )
    if absolute_weakness or inconsistent_continuing:
        fake_warning = True
        direction = "진입함정"
        for item in (
            "절대약세:유입없음" if absolute_weakness else "유입지속불일치",
            "유입가속음수", "VWAP아래",
        ):
            if item not in fake_reasons:
                fake_reasons.append(item)
    high_range_bonus = _high_range_bonus(strategy, direction)
    return {
        "code": code,
        "name": candidate.get("name") or flow.get("name") or code,
        "original_rank": original_rank,
        "original_action": candidate.get("action") or candidate.get("status") or "WATCH",
        "common_flow_state": state,
        "flow_shadow_bonus": flow_bonus,
        "high_range_direction": direction,
        "high_range_shadow_bonus": high_range_bonus,
        "shadow_bonus": flow_bonus + high_range_bonus,
        "shadow_priority": priority,
        "shadow_reason": reason,
        "flow_accel_mkrw_per_min": flow_accel,
        "vwap_gap_pct": vwap_gap,
        "high_range_relative_strength_pct": direction_row.get("relative_strength_pct"),
        "high_range_rebound_pct": direction_row.get("rebound_from_low_pct"),
        "high_range_no_new_low_sec": direction_row.get("no_new_low_sec"),
        "high_range_money_speed_ratio": direction_row.get("money_speed_ratio"),
        "fake_rebound_warning": fake_warning,
        "fake_rebound_reasons": fake_reasons,
        "absolute_weakness_fallback": absolute_weakness,
    }


def build_overlay(
    flow_payload: Mapping[str, Any],
    strategy_payloads: Mapping[str, Mapping[str, Any]],
    now: datetime | None = None,
    direction_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    flow_by_code = {
        _code(row.get("code")): row
        for row in (flow_payload.get("rows") or [])
        if isinstance(row, Mapping) and _code(row.get("code"))
    }
    direction_by_code = {
        _code(row.get("code")): row
        for row in ((direction_payload or {}).get("rows") or [])
        if isinstance(row, Mapping) and _code(row.get("code"))
    }
    strategies: dict[str, Any] = {}
    for strategy in ("S01", "S02", "S03", "S04", "S05", "S06", "S07"):
        candidates = strategy_candidates(strategy, strategy_payloads.get(strategy) or {})
        joined = []
        counts = {"유입지속": 0, "유입전환": 0, "유입없음": 0}
        for original_rank, candidate in enumerate(candidates, 1):
            row = _decorate_candidate(strategy, candidate, original_rank, flow_by_code, direction_by_code)
            counts[row["common_flow_state"]] += 1
            joined.append(row)
        ranked = sorted(joined, key=lambda row: (-row["shadow_bonus"], row["original_rank"]))
        for shadow_rank, row in enumerate(ranked, 1):
            row["shadow_rank"] = shadow_rank
        strategies[strategy] = {
            "candidate_count": len(candidates),
            "state_counts": counts,
            "candidates": ranked,
        }
    return {
        "schema": "strategy_flow_priority_shadow_v1",
        "generated_at": now.isoformat(timespec="seconds"),
        "source_ts": flow_payload.get("ts"),
        "mode": "SHADOW_ORDER_ZERO",
        "order_capable": False,
        "orders_sent": 0,
        "existing_strategy_decisions_changed": False,
        "rules": {
            "S01_S04_S05_S07": "유입지속 HIGH, 유입전환 MEDIUM, 유입없음 BASE",
            "S02_S03_S06": "유입전환 HIGH, 유입지속 MEDIUM, 유입없음 BASE",
            "HIGH_RANGE": "상승방향 가점, 하락위험 -1 SHADOW 가점만; 차단 없음",
        },
        "strategies": strategies,
    }


def open_broker_positions(
    fill_rows: list[dict[str, Any]], order_map: Mapping[str, str]
) -> list[dict[str, Any]]:
    queues: dict[str, collections.deque[dict[str, Any]]] = collections.defaultdict(collections.deque)
    for fill in fill_rows:
        code = _code(fill.get("code"))
        qty = int(fill.get("fill_qty") or 0)
        if not code or qty <= 0:
            continue
        if "매수" in str(fill.get("otype") or ""):
            queues[code].append({
                "strategy": str(order_map.get(str(fill.get("order_no") or "")) or "UNKNOWN"),
                "quantity": qty,
                "entry_price": _float_or_none(fill.get("fill_px")) or 0.0,
                "entry_timestamp": str(fill.get("ts") or ""),
            })
            continue
        remaining = qty
        while remaining > 0 and queues[code]:
            buy = queues[code][0]
            matched = min(remaining, buy["quantity"])
            buy["quantity"] -= matched
            remaining -= matched
            if buy["quantity"] <= 0:
                queues[code].popleft()
    positions = []
    for code, queue in queues.items():
        by_strategy: dict[str, int] = collections.defaultdict(int)
        for buy in queue:
            if buy["strategy"] != "UNKNOWN":
                by_strategy[buy["strategy"]] += buy["quantity"]
        for strategy, quantity in by_strategy.items():
            owned = [item for item in queue if item["strategy"] == strategy]
            total_cost = sum(item["entry_price"] * item["quantity"] for item in owned)
            positions.append({
                "strategy": strategy, "code": code, "quantity": quantity,
                "entry_price": total_cost / quantity if quantity > 0 else 0.0,
                "entry_timestamp": min(
                    (item["entry_timestamp"] for item in owned if item["entry_timestamp"]),
                    default="",
                ),
            })
    return positions


def ensure_open_position_watch(
    overlay: dict[str, Any], flow_payload: Mapping[str, Any],
    direction_payload: Mapping[str, Any], positions: list[dict[str, Any]],
    micro_snapshot: Mapping[str, Any] | None = None,
    previous_audit_state: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now()
    flow_by_code = {_code(row.get("code")): row for row in (flow_payload.get("rows") or []) if isinstance(row, Mapping)}
    direction_by_code = {_code(row.get("code")): row for row in (direction_payload.get("rows") or []) if isinstance(row, Mapping)}
    micro_codes = (micro_snapshot or {}).get("codes") or {}
    previous_observations = (previous_audit_state or {}).get("observations") or {}
    for position in positions:
        strategy = str(position.get("strategy") or "")
        section = (overlay.get("strategies") or {}).get(strategy)
        if not section:
            continue
        code = _code(position.get("code"))
        rows = section.get("candidates") or []
        row = next((item for item in rows if item.get("code") == code), None)
        added = row is None
        if row is None:
            row = _decorate_candidate(
                strategy,
                {"code": code, "action": "BROKER_POSITION_WATCH"},
                len(rows) + 1,
                flow_by_code,
                direction_by_code,
            )
            row["forced_position_watch"] = True
            rows.append(row)
        row["broker_open_quantity"] = int(position.get("quantity") or 0)
        entry_price = _float_or_none(position.get("entry_price")) or 0.0
        entry_dt = _local_dt(position.get("entry_timestamp"))
        current_price = _float_or_none((micro_codes.get(code) or {}).get("cur")) or 0.0
        held_sec = max(0.0, (now - entry_dt).total_seconds()) if entry_dt else 999999.0
        below_entry = bool(entry_price > 0 and current_price > 0 and current_price < entry_price)
        raw_failure = bool(row.get("fake_rebound_warning"))
        history = previous_observations.get(f"{strategy}:{code}", []) or []
        last = history[-1] if history else {}
        last_dt = _local_dt(last.get("observed_at"))
        sustained_sec = (
            max(0.0, (now - last_dt).total_seconds())
            if raw_failure and last.get("raw_position_failure") and last_dt else 0.0
        )
        confirmed_failure = bool(raw_failure and below_entry and held_sec <= 300 and sustained_sec >= 30)
        if confirmed_failure:
            row["high_range_direction"] = "보유실패"
            row["fake_rebound_warning"] = True
        elif raw_failure and below_entry and held_sec <= 300:
            row["high_range_direction"] = "보유실패확인중"
            row["fake_rebound_warning"] = False
        elif raw_failure:
            row["high_range_direction"] = "유입둔화"
            row["fake_rebound_warning"] = False
        row["position_stage"] = row["high_range_direction"]
        row["raw_position_failure"] = raw_failure
        row["position_failure_sustained_sec"] = round(sustained_sec, 1)
        row["entry_price"] = entry_price
        row["current_price"] = current_price
        row["held_sec"] = round(held_sec, 1)
        row["below_entry"] = below_entry
        row["high_range_shadow_bonus"] = _high_range_bonus(strategy, row["high_range_direction"])
        row["shadow_bonus"] = row["flow_shadow_bonus"] + row["high_range_shadow_bonus"]
        rows.sort(key=lambda item: (-item["shadow_bonus"], item["original_rank"]))
        for rank, item in enumerate(rows, 1):
            item["shadow_rank"] = rank
        section["candidates"] = rows
        section["candidate_count"] = len(rows)
        if added:
            section["forced_position_watch_count"] = int(section.get("forced_position_watch_count") or 0) + 1
            state = row["common_flow_state"]
            section["state_counts"][state] = int(section["state_counts"].get(state) or 0) + 1


def _local_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def record_observations(
    overlay: Mapping[str, Any],
    state: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keep timestamped candidate context; never sends or changes an order."""
    now = now or datetime.now()
    day = now.strftime("%Y%m%d")
    previous = state if isinstance(state, Mapping) and state.get("date") == day else {}
    observations = {
        key: list(value)[-500:]
        for key, value in (previous.get("observations") or {}).items()
        if isinstance(value, list)
    }
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    for strategy, section in (overlay.get("strategies") or {}).items():
        for row in section.get("candidates") or []:
            code = _code(row.get("code"))
            if not code:
                continue
            key = f"{strategy}:{code}"
            history = observations.setdefault(key, [])
            signature = "|".join(str(row.get(field) or "") for field in (
                "common_flow_state", "high_range_direction", "shadow_priority", "original_action",
                "raw_position_failure", "fake_rebound_warning",
            ))
            last = history[-1] if history else {}
            last_dt = _local_dt(last.get("observed_at"))
            due = not last_dt or (now - last_dt).total_seconds() >= 60
            if signature != last.get("signature") or due:
                history.append({
                    "observed_at": stamp,
                    "strategy": strategy,
                    "code": code,
                    "name": row.get("name"),
                    "flow_state": row.get("common_flow_state"),
                    "shadow_priority": row.get("shadow_priority"),
                    "original_action": row.get("original_action"),
                    "flow_accel_mkrw_per_min": row.get("flow_accel_mkrw_per_min"),
                    "vwap_gap_pct": row.get("vwap_gap_pct"),
                    "high_range_direction": row.get("high_range_direction"),
                    "high_range_shadow_bonus": row.get("high_range_shadow_bonus"),
                    "high_range_relative_strength_pct": row.get("high_range_relative_strength_pct"),
                    "high_range_rebound_pct": row.get("high_range_rebound_pct"),
                    "high_range_no_new_low_sec": row.get("high_range_no_new_low_sec"),
                    "high_range_money_speed_ratio": row.get("high_range_money_speed_ratio"),
                    "fake_rebound_warning": row.get("fake_rebound_warning"),
                    "fake_rebound_reasons": row.get("fake_rebound_reasons"),
                    "position_stage": row.get("position_stage"),
                    "raw_position_failure": row.get("raw_position_failure"),
                    "position_failure_sustained_sec": row.get("position_failure_sustained_sec"),
                    "entry_price": row.get("entry_price"),
                    "current_price": row.get("current_price"),
                    "held_sec": row.get("held_sec"),
                    "below_entry": row.get("below_entry"),
                    "signature": signature,
                })
                observations[key] = history[-500:]
    return {"schema": "strategy_flow_priority_shadow_audit_state_v1", "date": day, "observations": observations}


def _event_order_map(day: str) -> tuple[dict[str, str], list[str]]:
    order_map: dict[str, str] = {}
    paths: list[str] = []
    for strategy, directory in EVENT_SOURCES.items():
        number = strategy[1:]
        path = directory / f"strategy_{number}_events_{day}.csv"
        if not path.exists():
            continue
        paths.append(str(path))
        try:
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    order_no = str(row.get("order_no") or "").strip()
                    if order_no:
                        order_map[order_no] = strategy
        except OSError:
            continue
    return order_map, paths


def _fill_rows(day: str) -> tuple[list[dict[str, Any]], Path]:
    path = ROOT / "LOG" / f"fills_{day}.csv"
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            for raw in csv.DictReader(handle):
                if raw.get("state") != "체결":
                    continue
                code = _code(raw.get("code"))
                qty = int(float(raw.get("fill_qty") or 0))
                price = float(raw.get("fill_px") or 0)
                if code and qty > 0 and price > 0:
                    rows.append(dict(raw, code=code, fill_qty=qty, fill_px=price))
    except (OSError, TypeError, ValueError):
        pass
    return rows, path


def _entry_context(
    observations: Mapping[str, Any], strategy: str, code: str, fill_ts: str
) -> dict[str, Any] | None:
    fill_dt = _local_dt(fill_ts)
    if not fill_dt:
        return None
    eligible = []
    for item in observations.get(f"{strategy}:{code}", []) or []:
        observed_dt = _local_dt(item.get("observed_at"))
        if observed_dt and observed_dt <= fill_dt:
            eligible.append((observed_dt, item))
    return dict(max(eligible, key=lambda pair: pair[0])[1]) if eligible else None


def _warning_between(
    observations: Mapping[str, Any], strategy: str, code: str,
    start_ts: str, end_ts: str,
) -> tuple[bool, dict[str, Any] | None]:
    start_dt = _local_dt(start_ts)
    end_dt = _local_dt(end_ts)
    if not start_dt or not end_dt:
        return False, None
    covered = False
    warnings = []
    for item in observations.get(f"{strategy}:{code}", []) or []:
        observed_dt = _local_dt(item.get("observed_at"))
        if not observed_dt or not (start_dt <= observed_dt <= end_dt):
            continue
        covered = True
        if item.get("fake_rebound_warning"):
            warnings.append((observed_dt, item))
    return covered, (dict(min(warnings, key=lambda pair: pair[0])[1]) if warnings else None)


def reconcile_broker_fills(
    fill_rows: list[dict[str, Any]],
    order_map: Mapping[str, str],
    audit_state: Mapping[str, Any],
    fill_path: str,
    event_paths: list[str] | None = None,
) -> dict[str, Any]:
    """FIFO-match exact broker fills and attach only pre-fill recorded context."""
    queues: dict[str, collections.deque[dict[str, Any]]] = collections.defaultdict(collections.deque)
    completed: list[dict[str, Any]] = []
    observations = audit_state.get("observations") or {}
    for fill in fill_rows:
        code = _code(fill.get("code"))
        order_no = str(fill.get("order_no") or "").strip()
        strategy = str(order_map.get(order_no) or "UNKNOWN")
        side = "BUY" if "매수" in str(fill.get("otype") or "") else "SELL"
        record = {
            "timestamp": str(fill.get("ts") or ""),
            "code": code,
            "order_no": order_no,
            "quantity": int(fill.get("fill_qty") or 0),
            "price": float(fill.get("fill_px") or 0),
            "side": side,
            "strategy": strategy,
        }
        if side == "BUY":
            record["entry_context"] = _entry_context(observations, strategy, code, record["timestamp"])
            queues[code].append(record)
            continue
        remaining = record["quantity"]
        while remaining > 0 and queues[code]:
            buy = queues[code][0]
            matched = min(remaining, buy["quantity"])
            flow_context = buy.get("entry_context")
            post_covered, post_warning = _warning_between(
                observations, buy["strategy"], code,
                buy["timestamp"], record["timestamp"],
            )
            completed.append({
                "provenance": "[BROKER_FILL]",
                "performance_scope": "FULL_ENTRY_EXIT",
                "production_code_changed": "NOT_CHANGED",
                "strategy": buy["strategy"],
                "code": code,
                "quantity": matched,
                "buy": {"timestamp": buy["timestamp"], "order_no": buy["order_no"], "price": buy["price"]},
                "sell": {"timestamp": record["timestamp"], "order_no": order_no, "price": record["price"]},
                "return_pct": (record["price"] / buy["price"] - 1.0) * 100.0,
                "cash_pnl_before_costs": (record["price"] - buy["price"]) * matched,
                "entry_flow_context_status": "RECORDED" if flow_context else "[UNVERIFIED]",
                "entry_flow_context": flow_context,
                "pre_entry_fake_rebound_status": (
                    "WARNING" if flow_context and flow_context.get("fake_rebound_warning")
                    else "CLEAR" if flow_context and "fake_rebound_warning" in flow_context
                    else "[UNVERIFIED]"
                ),
                "post_entry_fake_rebound_status": (
                    "WARNING" if post_warning else "CLEAR" if post_covered else "[UNVERIFIED]"
                ),
                "first_post_entry_fake_warning": post_warning,
                "broker_journal_path": fill_path,
            })
            buy["quantity"] -= matched
            remaining -= matched
            if buy["quantity"] <= 0:
                queues[code].popleft()
    groups: dict[str, dict[str, int]] = {}
    for trade in completed:
        context = trade.get("entry_flow_context") or {}
        key = f"{trade['strategy']}:{context.get('flow_state') or 'UNVERIFIED'}"
        group = groups.setdefault(key, {"completed_trades": 0, "wins": 0, "losses": 0})
        group["completed_trades"] += 1
        group["wins" if trade["return_pct"] > 0 else "losses"] += 1
    return {
        "schema": "strategy_flow_priority_shadow_results_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "READ_ONLY_AUDIT",
        "order_capable": False,
        "broker_journal_path": fill_path,
        "strategy_event_paths": event_paths or [],
        "completed_roundtrips": completed,
        "groups": groups,
        "note": "RECORDED 컨텍스트만 유입태그 판단에 사용; 과거 미기록 체결은 UNVERIFIED",
    }


def summarize_fake_rebound(result: Mapping[str, Any]) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {"pre_entry": {}, "post_entry": {}}
    unverified = {"pre_entry": 0, "post_entry": 0}
    for trade in result.get("completed_roundtrips") or []:
        for section, field in (
            ("pre_entry", "pre_entry_fake_rebound_status"),
            ("post_entry", "post_entry_fake_rebound_status"),
        ):
            status = str(trade.get(field) or "[UNVERIFIED]")
            if status == "[UNVERIFIED]":
                unverified[section] += 1
                continue
            group = sections[section].setdefault(status, {
                "provenance": "[BROKER_FILL]",
                "performance_scope": "FULL_ENTRY_EXIT",
                "completed_trades": 0, "wins": 0, "losses": 0,
                "cash_pnl_before_costs": 0.0, "return_pct_values": [],
                "evidence_reports": [],
            })
            group["completed_trades"] += 1
            group["wins" if trade.get("return_pct", 0) > 0 else "losses"] += 1
            group["cash_pnl_before_costs"] += float(trade.get("cash_pnl_before_costs") or 0)
            group["return_pct_values"].append(float(trade.get("return_pct") or 0))
            if trade.get("truth_report_path"):
                group["evidence_reports"].append(trade["truth_report_path"])
    return {
        "provenance": "[BROKER_FILL]",
        "performance_scope": "FULL_ENTRY_EXIT",
        "pre_entry_filter_test": sections["pre_entry"],
        "post_entry_exit_warning_test": sections["post_entry"],
        "unverified_trade_counts": unverified,
        "decision_rule": "RECORDED 표본만 비교; UNVERIFIED 과거 체결은 효과판단에서 제외",
    }


def write_truth_reports(result: Mapping[str, Any]) -> list[str]:
    """Write one truth-gate-compatible report per completed broker roundtrip."""
    paths: list[str] = []
    for trade in result.get("completed_roundtrips") or []:
        buy = trade.get("buy") or {}
        sell = trade.get("sell") or {}
        date = str(buy.get("timestamp") or "")[:10].replace("-", "")
        code = _code(trade.get("code"))
        if not date or not code:
            continue
        filename = f"{date}_{trade.get('strategy')}_{code}_{buy.get('order_no')}_{sell.get('order_no')}.json"
        path = TRUTH_REPORT_DIR / filename
        report = {
            "provenance": "[BROKER_FILL]",
            "date": date,
            "source_data": trade.get("broker_journal_path"),
            "timestamp": buy.get("timestamp"),
            "code": code,
            "price": buy.get("price"),
            "quantity": trade.get("quantity"),
            "performance_scope": "FULL_ENTRY_EXIT",
            "production_code_changed": "NOT_CHANGED",
            "strategy": trade.get("strategy"),
            "buy": buy,
            "sell": sell,
            "return_pct": trade.get("return_pct"),
            "cash_pnl_before_costs": trade.get("cash_pnl_before_costs"),
            "entry_flow_context_status": trade.get("entry_flow_context_status"),
            "entry_flow_context": trade.get("entry_flow_context"),
            "pre_entry_fake_rebound_status": trade.get("pre_entry_fake_rebound_status"),
            "post_entry_fake_rebound_status": trade.get("post_entry_fake_rebound_status"),
            "first_post_entry_fake_warning": trade.get("first_post_entry_fake_warning"),
        }
        atomic_json(path, report)
        trade["truth_report_path"] = str(path)
        paths.append(str(path))
    return paths


def publish_once() -> dict[str, Any]:
    day = datetime.now().strftime("%Y%m%d")
    order_map, event_paths = _event_order_map(day)
    fills, fill_path = _fill_rows(day)
    flow_payload = read_json(FLOW_BOARD)
    direction_payload = read_json(HIGH_RANGE_DIRECTION)
    previous_audit_state = read_json(STATE_JSON)
    payload = build_overlay(
        flow_payload,
        {strategy: read_json(path) for strategy, path in SOURCES.items()},
        direction_payload=direction_payload,
    )
    ensure_open_position_watch(
        payload, flow_payload, direction_payload,
        open_broker_positions(fills, order_map),
        read_json(MICRO_SNAPSHOT), previous_audit_state,
    )
    atomic_json(OUT_JSON, payload)
    audit_state = record_observations(payload, previous_audit_state)
    atomic_json(STATE_JSON, audit_state)
    result = reconcile_broker_fills(fills, order_map, audit_state, str(fill_path), event_paths)
    result["truth_report_paths"] = write_truth_reports(result)
    result["fake_rebound_evaluation"] = summarize_fake_rebound(result)
    atomic_json(RESULT_JSON, result)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop-sec", type=float, default=15.0)
    parser.add_argument("--until", default="15:20")
    args = parser.parse_args()
    if args.once:
        result = publish_once()
        print(json.dumps({"mode": result["mode"], "orders_sent": 0}, ensure_ascii=False))
        return 0
    while datetime.now().strftime("%H:%M") <= args.until:
        publish_once()
        time.sleep(max(5.0, args.loop_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

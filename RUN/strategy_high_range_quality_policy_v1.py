"""Order-zero high-range quality policy shared by S01-S06.

This module never creates an entry and never calls a broker.  It only enriches
already eligible strategy candidates and calculates a reproducible shadow order.
The same pure ``rank_candidates`` function is the future production adapter after
an exact replay and owner approval.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


MOMENTUM_PRIORITY = frozenset({"S01", "S04", "S05"})
REVERSAL_RISK_CONTEXT = frozenset({"S02", "S03", "S06"})


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else text


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def strategy_use(strategy_id: str) -> str:
    strategy = strategy_id.upper()
    if strategy in MOMENTUM_PRIORITY:
        return "PRIORITY_AMONG_ALREADY_ELIGIBLE"
    if strategy in REVERSAL_RISK_CONTEXT:
        return "RISK_CONTEXT_ONLY"
    raise ValueError(f"unsupported strategy: {strategy_id}")


def load_quality_maps(base: Path, now: datetime) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    static_path = base / "data" / "common_high_range_top30.json"
    live_path = base / "data" / "common_high_range_live_state.json"

    def read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    static = read(static_path)
    live = read(live_path)
    today = now.strftime("%Y%m%d")
    static_fresh = str(static.get("for_date") or "").replace("-", "")[:8] == today
    live_fresh = str(live.get("date") or "").replace("-", "")[:8] == today
    result: dict[str, dict[str, Any]] = {}

    if static_fresh:
        for row in static.get("candidates") or []:
            code = _code(row.get("code"))
            if code:
                result.setdefault(code, {}).update({
                    "hr_rank": row.get("rank"),
                    "hr_crown": bool(row.get("crown")),
                    "hr_prev_range": _number(row.get("prev_range_pct")),
                    "hr_avg5_range": _number(row.get("avg_5d_range_pct")),
                    "hr_min5_range": _number(row.get("min_5d_range_pct")),
                    "hr_streak": row.get("streak"),
                })
    if live_fresh:
        for raw_code, row in (live.get("codes") or {}).items():
            if not isinstance(row, Mapping):
                continue
            code = _code(raw_code)
            result.setdefault(code, {}).update({
                "hr_money_speed_ratio": _number(row.get("money_speed_vs_daily_avg")),
                "hr_turnover_pct": _number(row.get("listed_turnover_pct")),
                "hr_volatility_quality": row.get("volatility_quality"),
                "hr_quality_risks": list(row.get("quality_risk_reasons") or []),
                "hr_live_status": row.get("status"),
            })
    return result, {
        "static_fresh": static_fresh,
        "live_fresh": live_fresh,
        "static_path": str(static_path),
        "live_path": str(live_path),
    }


def enrich_candidates(
    strategy_id: str,
    candidates: Iterable[Mapping[str, Any]],
    quality_by_code: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    use = strategy_use(strategy_id)
    rows: list[dict[str, Any]] = []
    for original_position, source in enumerate(candidates, 1):
        row = dict(source)
        code = _code(row.get("code"))
        row["code"] = code
        row.update(dict(quality_by_code.get(code) or {}))
        row.update({
            "strategy_id": strategy_id.upper(),
            "high_range_use": use,
            "high_range_static_fresh": bool(source_status.get("static_fresh")),
            "high_range_live_fresh": bool(source_status.get("live_fresh")),
            "original_position": original_position,
            "order_qty": 0,
            "live_eligible": False,
            "mode": "SHADOW_ORDER_ZERO",
        })
        rows.append(row)
    return rows


def _priority_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    risks = list(row.get("hr_quality_risks") or [])
    rank = _number(row.get("hr_rank"))
    speed = _number(row.get("hr_money_speed_ratio"))
    turnover = _number(row.get("hr_turnover_pct"))
    return (
        not (row.get("high_range_static_fresh") and row.get("high_range_live_fresh")),
        bool(risks),
        str(row.get("hr_live_status") or "").upper() != "LIVE",
        not bool(row.get("hr_crown")),
        -(speed if speed is not None else -1.0),
        -(turnover if turnover is not None else -1.0),
        rank if rank is not None else 9999.0,
        int(row.get("original_position") or 9999),
    )


def rank_candidates(strategy_id: str, enriched: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return shadow order; reversal strategies intentionally retain signal order."""
    rows = [dict(row) for row in enriched]
    if strategy_use(strategy_id) == "PRIORITY_AMONG_ALREADY_ELIGIBLE":
        rows.sort(key=_priority_key)
    else:
        rows.sort(key=lambda row: int(row.get("original_position") or 9999))
    for position, row in enumerate(rows, 1):
        row["shadow_position"] = position
    return rows


def append_shadow_batch(path: Path, now: datetime, strategy_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for source in rows:
            row = dict(source)
            row["observed_at"] = now.isoformat(timespec="milliseconds")
            row["strategy_id"] = strategy_id.upper()
            row["mode"] = "SHADOW_ORDER_ZERO"
            row["order_qty"] = 0
            row["live_eligible"] = False
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

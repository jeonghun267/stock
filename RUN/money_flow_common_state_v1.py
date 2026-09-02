"""Display-only common money-flow tags for the money-flow board."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


FLOW_CONTINUING = "유입지속"
FLOW_TURNING = "유입전환"
FLOW_NONE = "유입없음"


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def build_common_flow_tags(
    rows: list[dict[str, Any]],
    micro_codes: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int]]:
    """Attach shadow-only tags without filtering, sorting, or changing ranks."""
    previous_state = previous_state or {}
    old_codes = previous_state.get("codes") or {}
    next_codes: dict[str, dict[str, Any]] = {}
    counts = {FLOW_CONTINUING: 0, FLOW_TURNING: 0, FLOW_NONE: 0}
    tagged: list[dict[str, Any]] = []

    for source_row in rows:
        row = dict(source_row)
        code = str(row.get("code") or "").zfill(6)
        micro = micro_codes.get(code) if isinstance(micro_codes, Mapping) else None
        micro = micro if isinstance(micro, Mapping) else {}
        prior = old_codes.get(code) if isinstance(old_codes, Mapping) else None
        prior = prior if isinstance(prior, Mapping) else {}

        sample_ts = str(micro.get("ts") or "")
        current_dt = _timestamp(sample_ts)
        prior_dt = _timestamp(prior.get("ts"))
        elapsed_seconds = (
            (current_dt - prior_dt).total_seconds()
            if current_dt and prior_dt and current_dt.date() == prior_dt.date()
            else 0.0
        )
        is_new = bool(sample_ts and sample_ts != str(prior.get("ts") or ""))
        valid_interval = is_new and 1.0 <= elapsed_seconds <= 600.0
        elapsed_min = elapsed_seconds / 60.0 if valid_interval else 0.0

        buy_money = _number(micro.get("buy_money_cum"))
        sell_money = _number(micro.get("sell_money_cum"))
        signed_money = (buy_money - sell_money) / 1_000_000.0
        value_eok = (buy_money + sell_money) / 100_000_000.0
        price = _number(micro.get("cur")) or _number(row.get("price"))
        volume = _number(micro.get("buy_vol_cum")) + _number(micro.get("sell_vol_cum"))
        vwap = (buy_money + sell_money) / volume if volume > 0 else price

        previous_accel = _number(prior.get("flow_accel_mkrw_per_min"))
        accel = previous_accel
        value_accel = _number(prior.get("value_accel_eok_per_min"))
        price_step_pct = _number(prior.get("price_step_pct"))
        streak = int(_number(prior.get("positive_streak")))
        transition_active = bool(prior.get("transition_active"))

        if valid_interval:
            flow_delta = signed_money - _number(prior.get("signed_money_mkrw"))
            value_delta = value_eok - _number(prior.get("value_eok"))
            accel = flow_delta / elapsed_min
            value_accel = value_delta / elapsed_min
            prior_price = _number(prior.get("price"))
            price_step_pct = (
                (price / prior_price - 1.0) * 100.0 if prior_price > 0 and price > 0 else 0.0
            )
            positive = accel > 0 and value_accel > 0 and price_step_pct >= 0
            streak = streak + 1 if positive else 0
            transition_now = (
                previous_accel <= 0 < accel
                and value_accel > 0
                and price > 0
                and vwap > 0
                and price >= vwap
            )
            transition_active = bool(
                transition_now or (transition_active and positive and streak < 3)
            )

        if not prior or not micro:
            flow_state = FLOW_NONE
        elif not is_new:
            flow_state = str(prior.get("flow_state") or FLOW_NONE)
        elif streak >= 3:
            flow_state = FLOW_CONTINUING
            transition_active = False
        elif transition_active:
            flow_state = FLOW_TURNING
        else:
            flow_state = FLOW_NONE

        row["common_flow_state"] = flow_state
        row["common_flow_accel_mkrw_per_min"] = round(accel, 3)
        row["common_value_accel_eok_per_min"] = round(value_accel, 4)
        row["common_flow_streak"] = streak
        row["common_vwap_gap_pct"] = round((price / vwap - 1.0) * 100.0, 3) if vwap > 0 else 0.0
        tagged.append(row)
        counts[flow_state] += 1
        next_codes[code] = {
            "ts": sample_ts,
            "signed_money_mkrw": round(signed_money, 4),
            "value_eok": round(value_eok, 6),
            "price": price,
            "flow_accel_mkrw_per_min": accel,
            "value_accel_eok_per_min": value_accel,
            "price_step_pct": price_step_pct,
            "positive_streak": streak,
            "transition_active": transition_active,
            "flow_state": flow_state,
        }

    return tagged, {"version": 1, "codes": next_codes}, counts

"""Direction overlay for the existing high-range board (display/order zero)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else ""


def _low_age_seconds(value: Any, now: datetime) -> float:
    text = str(value or "").strip()
    try:
        if len(text) == 5 and text[2] == ":":
            low_dt = now.replace(hour=int(text[:2]), minute=int(text[3:]), second=0, microsecond=0)
        else:
            low_dt = datetime.fromisoformat(text).replace(tzinfo=None)
        return max(0.0, (now.replace(tzinfo=None) - low_dt).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def build_direction_board(
    high_range: Mapping[str, Any],
    live_state: Mapping[str, Any],
    money_flow: Mapping[str, Any],
    micro_snapshot: Mapping[str, Any],
    market_change_pct: float | None,
    now: datetime | None = None,
    previous_direction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    flow_rows = {
        _code(row.get("code")): row
        for row in (money_flow.get("rows") or [])
        if isinstance(row, Mapping) and _code(row.get("code"))
    }
    micro_codes = micro_snapshot.get("codes") or {}
    live_codes = live_state.get("codes") or {}
    rows = []
    previous_by_code = {
        _code(row.get("code")): row
        for row in ((previous_direction or {}).get("rows") or [])
        if isinstance(row, Mapping) and _code(row.get("code"))
    }
    counts = {"상승전환": 0, "상승지속": 0, "진입함정": 0, "하락위험": 0, "확인대기": 0}
    for candidate in high_range.get("candidates") or []:
        code = _code(candidate.get("code"))
        if not code:
            continue
        live = live_codes.get(code) or {}
        micro = micro_codes.get(code) or {}
        flow = flow_rows.get(code) or {}
        prior = previous_by_code.get(code) or {}
        current = _number(live.get("current")) or _number(micro.get("cur"))
        previous_close = _number(candidate.get("prev_close"))
        stock_change = (current / previous_close - 1.0) * 100.0 if current > 0 and previous_close > 0 else 0.0
        relative_strength = stock_change - _number(market_change_pct)
        rebound = _number(live.get("rebound_from_low_pct"))
        no_new_low_sec = _low_age_seconds(live.get("low_time"), now)
        flow_state = str(flow.get("common_flow_state") or "유입없음")
        vwap_gap = _number(flow.get("common_vwap_gap_pct"))
        if not flow:
            buy_money = _number(micro.get("buy_money_cum"))
            sell_money = _number(micro.get("sell_money_cum"))
            volume = _number(micro.get("buy_vol_cum")) + _number(micro.get("sell_vol_cum"))
            vwap = (buy_money + sell_money) / volume if volume > 0 else 0.0
            vwap_gap = (current / vwap - 1.0) * 100.0 if current > 0 and vwap > 0 else 0.0
        che = _number(live.get("che_str")) or _number(micro.get("che_str"))
        buy_ratio = _number(live.get("buy_ratio_pct"))
        money_speed = _number(live.get("money_speed_vs_daily_avg"))
        macd_hist = _number(live.get("macd_hist"))
        flow_accel = _number(flow.get("common_flow_accel_mkrw_per_min"))
        prior_accel = _number(prior.get("flow_accel_mkrw_per_min"))
        prior_vwap_gap = _number(prior.get("vwap_gap_pct"))
        prior_che = _number(prior.get("che_str"))
        prior_peak_rebound = _number(prior.get("peak_rebound_pct"))
        peak_rebound = rebound if no_new_low_sec < 5 else max(rebound, prior_peak_rebound)

        fake_reasons = []
        if prior_accel > 0 and (flow_accel <= 0 or flow_accel < prior_accel * 0.25):
            fake_reasons.append("유입가속급감")
        vwap_rebreak = prior_vwap_gap >= 0 and vwap_gap < 0
        if vwap_rebreak:
            fake_reasons.append("VWAP재이탈")
        rebound_fading = peak_rebound >= 0.8 and rebound <= peak_rebound * 0.5
        if rebound_fading:
            fake_reasons.append("반등폭절반축소")
        if (prior_che >= 90 and che < 80) or (buy_ratio > 0 and buy_ratio < 45):
            fake_reasons.append("체결매수비약화")
        fake_rebound_warning = bool(
            len(fake_reasons) >= 2 and (vwap_rebreak or rebound_fading)
        )

        turn = (
            flow_state == "유입전환" and vwap_gap >= 0
            and rebound >= 0.5 and no_new_low_sec >= 30
            and (che >= 100 or macd_hist >= 0)
        )
        continuing = (
            flow_state == "유입지속" and vwap_gap >= 0
            and relative_strength >= 0 and no_new_low_sec >= 60
            and (che >= 90 or money_speed >= 1.0)
        )
        danger = (
            (no_new_low_sec < 30 and rebound < 0.3)
            or (vwap_gap < 0 and relative_strength < 0 and flow_state == "유입없음")
            or (che > 0 and che < 70 and vwap_gap < 0)
        )
        if fake_rebound_warning:
            direction = "진입함정"
        elif turn:
            direction = "상승전환"
        elif continuing:
            direction = "상승지속"
        elif danger:
            direction = "하락위험"
        else:
            direction = "확인대기"
        counts[direction] += 1
        rows.append({
            "rank": candidate.get("rank"), "code": code,
            "name": candidate.get("name") or code,
            "direction": direction, "flow_state": flow_state,
            "vwap_gap_pct": round(vwap_gap, 3),
            "relative_strength_pct": round(relative_strength, 3),
            "rebound_from_low_pct": round(rebound, 3),
            "no_new_low_sec": round(no_new_low_sec, 1),
            "che_str": round(che, 2),
            "money_speed_ratio": round(money_speed, 3),
            "macd_hist": round(macd_hist, 5),
            "buy_ratio_pct": round(buy_ratio, 2),
            "flow_accel_mkrw_per_min": round(flow_accel, 3),
            "peak_rebound_pct": round(peak_rebound, 3),
            "fake_rebound_warning": fake_rebound_warning,
            "fake_rebound_score": len(fake_reasons),
            "fake_rebound_reasons": fake_reasons,
            "mode": "SHADOW_ORDER_ZERO", "order_capable": False,
        })
    return {
        "schema": "high_range_direction_shadow_v1",
        "generated_at": now.isoformat(timespec="seconds"),
        "source_ts": live_state.get("updated_at"),
        "mode": "SHADOW_ORDER_ZERO", "order_capable": False, "orders_sent": 0,
        "existing_strategy_decisions_changed": False,
        "counts": counts, "rows": rows,
    }

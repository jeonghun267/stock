# -*- coding: utf-8 -*-
"""Order-zero intraday money-inflow acceleration selector for trend leaders."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

ALLOWED_STATES = {"TREND_START", "TREND_UP", "TREND_STRONG"}
PERSISTENCE_REQUIRED = 3
LIQUIDITY_REFERENCE_KRW = 20_000_000
LIQUIDITY_DEPTH_MULTIPLE = 5.0
LIQUIDITY_VALUE_MULTIPLE = 10.0
LIQUIDITY_MAX_SPREAD_PCT = 0.5
ROUND_TRIP_FEE_TAX_PCT = 0.21
SLIPPAGE_RESERVE_PCT = 0.20
VOLATILITY_COST_MULTIPLE = 3.0
VOLATILITY_WINDOW_SECONDS = 300
COMPRESSION_MAX_RANGE_PCT = 0.8
VALUE_EXPLOSION_MULTIPLE = 2.0
OVERHEAT_VWAP_GAP_PCT = 2.0
PULLBACK_MIN_PCT = 0.5
PULLBACK_MAX_PCT = 2.5
REACCEL_FROM_PULLBACK_PCT = 0.3
EARLY_REBOUND_MIN_PCT = 0.5
EARLY_REBOUND_MAX_PCT = 3.0
EARLY_REBOUND_1M_SPEED_PCT = 0.3
EARLY_REBOUND_3M_SPEED_PCT = 0.5
EARLY_REBOUND_WINDOW_SECONDS = 600
FLOW_TURN_WINDOW_SECONDS = 180


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _market_pct(text: Any) -> float:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)%", str(text or ""))
    return float(match.group(1)) if match else 0.0


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def build_flow_trend(
    trend_payload: Mapping[str, Any],
    flow_payload: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None = None,
    micro_snapshot: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan the dynamic market funnel; return order-zero display and state."""
    previous_state = dict(previous_state or {})
    micro_snapshot = dict(micro_snapshot or {})
    source_ts = str(micro_snapshot.get("ts") or flow_payload.get("ts") or "")
    current_dt = _timestamp(source_ts)
    previous_dt = _timestamp(previous_state.get("source_ts"))
    is_new_snapshot = bool(source_ts and source_ts != previous_state.get("source_ts"))
    valid_interval = bool(
        is_new_snapshot and current_dt and previous_dt
        and current_dt.date() == previous_dt.date()
        and 10 <= (current_dt - previous_dt).total_seconds() <= 600
    )
    elapsed_min = (
        (current_dt - previous_dt).total_seconds() / 60.0
        if valid_interval and current_dt and previous_dt else 0.0
    )
    trend_rows = {
        str(row.get("code") or "").zfill(6): dict(row)
        for row in list(trend_payload.get("candidates") or [])
        + list(trend_payload.get("observe") or [])
    }
    detailed_rows = {
        str(row.get("code") or "").zfill(6): dict(row)
        for row in flow_payload.get("rows") or []
    }
    micro_codes = micro_snapshot.get("codes") or {}
    universe = [
        str(code).zfill(6) for code in flow_payload.get("univ_codes") or []
    ] or list(detailed_rows)
    old_rows = previous_state.get("codes") or {}
    market_pct = _market_pct(flow_payload.get("regime"))
    watch: list[dict[str, Any]] = []
    next_codes: dict[str, dict[str, Any]] = {}
    for code in universe:
        raw = detailed_rows.get(code) or {}
        micro = micro_codes.get(code) if isinstance(micro_codes, Mapping) else None
        micro = micro if isinstance(micro, Mapping) else {}
        if not raw and not micro:
            continue
        trend = trend_rows.get(code) or {}
        smart_net = _number(raw.get("big"))
        buy_money = _number(micro.get("buy_money_cum"))
        sell_money = _number(micro.get("sell_money_cum"))
        signed_money = (
            (buy_money - sell_money) / 1_000_000.0
            if buy_money or sell_money else smart_net
        )
        price = _number(micro.get("cur")) or _number(raw.get("price"))
        open_price = _number(micro.get("op"))
        value_eok = (
            (buy_money + sell_money) / 100_000_000.0
            if buy_money or sell_money else _number(raw.get("val_eok"))
        )
        change_pct = (
            (price / open_price - 1.0) * 100.0
            if open_price > 0 and price > 0 else _number(raw.get("chg"))
        )
        buy_count = int(_number(raw.get("buy_cnt")))
        grade = str(raw.get("grade") or "")
        prior = old_rows.get(code) if isinstance(old_rows, Mapping) else None
        prior = prior if isinstance(prior, Mapping) else {}
        same_session = bool(
            current_dt and previous_dt and current_dt.date() == previous_dt.date()
        )
        samples = list(prior.get("samples") or []) if same_session else []
        kept_samples = []
        if current_dt:
            for sample in samples:
                sample_dt = _timestamp(sample.get("ts")) if isinstance(sample, Mapping) else None
                if sample_dt and sample_dt.date() == current_dt.date():
                    age = (current_dt - sample_dt).total_seconds()
                    if 0 <= age <= 420:
                        kept_samples.append(dict(sample))
        samples = kept_samples
        sample_ts = str(micro.get("ts") or source_ts)
        sample_dt = _timestamp(sample_ts)
        if (
            sample_dt and current_dt and sample_dt.date() == current_dt.date()
            and price > 0 and (not samples or samples[-1].get("ts") != sample_ts)
        ):
            samples.append({
                "ts": sample_ts, "price": price, "value_eok": round(value_eok, 4),
            })
        reported_low = _number(micro.get("lo"))
        observed_low = reported_low or price
        session_low = _number(prior.get("session_low")) if same_session else 0.0
        session_low_time = str(prior.get("session_low_time") or "") if same_session else ""
        if session_low <= 0:
            session_low = observed_low
            if price > 0 and session_low > 0 and price <= session_low:
                session_low_time = str(micro.get("ts") or source_ts)
        elif observed_low > 0 and observed_low < session_low:
            session_low = observed_low
            session_low_time = str(micro.get("ts") or source_ts)
        if price > 0 and (session_low <= 0 or price < session_low):
            session_low = price
            session_low_time = str(micro.get("ts") or source_ts)
        rebound_amount = max(0.0, price - session_low) if session_low > 0 else 0.0
        rebound_pct = (
            rebound_amount / session_low * 100.0 if session_low > 0 else 0.0
        )
        previous_accel = _number(prior.get("flow_accel_mkrw_per_min"))
        accel = previous_accel
        value_accel = _number(prior.get("value_accel_eok_per_min"))
        price_step_pct = _number(prior.get("price_step_pct"))
        streak = int(_number(prior.get("positive_streak")))
        if valid_interval:
            delta = signed_money - _number(prior.get("signed_money_mkrw"))
            accel = delta / elapsed_min if elapsed_min > 0 else 0.0
            value_delta = value_eok - _number(prior.get("value_eok"))
            value_accel = value_delta / elapsed_min if elapsed_min > 0 else 0.0
            prior_price = _number(prior.get("price"))
            price_step_pct = (
                (price / prior_price - 1.0) * 100.0 if prior_price > 0 else 0.0
            )
            positive = delta > 0 and value_delta > 0 and price_step_pct >= 0
            streak = streak + 1 if positive else 0
        best_ask = _number(micro.get("best_ask_px"))
        best_bid = _number(micro.get("best_bid_px"))
        ask_depth_krw = _number(micro.get("ask_tot")) * best_ask
        bid_depth_krw = _number(micro.get("bid_tot")) * best_bid
        two_way_depth_krw = min(ask_depth_krw, bid_depth_krw)
        one_min_value_krw = max(0.0, value_accel) * 100_000_000.0
        spread_pct = (
            (best_ask - best_bid) / ((best_ask + best_bid) / 2.0) * 100.0
            if best_ask > 0 and best_bid > 0 and best_ask >= best_bid else 999.0
        )
        depth_ok = two_way_depth_krw >= LIQUIDITY_REFERENCE_KRW * LIQUIDITY_DEPTH_MULTIPLE
        value_ok = one_min_value_krw >= LIQUIDITY_REFERENCE_KRW * LIQUIDITY_VALUE_MULTIPLE
        spread_ok = spread_pct <= LIQUIDITY_MAX_SPREAD_PCT
        liquidity_status = "PASS" if depth_ok and value_ok and spread_ok else "WAIT"
        slice_cap_krw = max(0.0, min(
            LIQUIDITY_REFERENCE_KRW / 4.0,
            two_way_depth_krw * 0.05,
            one_min_value_krw * 0.05,
        ))
        timed_samples = []
        if current_dt:
            for sample in samples:
                sample_dt = _timestamp(sample.get("ts"))
                if sample_dt:
                    age = (current_dt - sample_dt).total_seconds()
                    timed_samples.append((age, sample_dt, sample))
        recent = [item for item in timed_samples if 0 <= item[0] <= VOLATILITY_WINDOW_SECONDS]
        recent_prices = [_number(item[2].get("price")) for item in recent]
        recent_span = (
            (recent[-1][1] - recent[0][1]).total_seconds() if len(recent) >= 2 else 0.0
        )
        recent_range_pct = (
            (max(recent_prices) / min(recent_prices) - 1.0) * 100.0
            if len(recent_prices) >= 3 and min(recent_prices) > 0 and recent_span >= 60 else 0.0
        )
        prior_band = [item for item in timed_samples if 60 < item[0] <= 360]
        prior_prices = [_number(item[2].get("price")) for item in prior_band]
        prior_span = (
            (prior_band[-1][1] - prior_band[0][1]).total_seconds()
            if len(prior_band) >= 2 else 0.0
        )
        prior_range_pct = (
            (max(prior_prices) / min(prior_prices) - 1.0) * 100.0
            if len(prior_prices) >= 4 and min(prior_prices) > 0 and prior_span >= 120 else 999.0
        )
        last_minute = [item for item in timed_samples if 0 <= item[0] <= 60]

        def value_rate(items: list[tuple[float, datetime, dict[str, Any]]]) -> float:
            if len(items) < 2:
                return 0.0
            span_min = (items[-1][1] - items[0][1]).total_seconds() / 60.0
            value_delta = (
                _number(items[-1][2].get("value_eok"))
                - _number(items[0][2].get("value_eok"))
            )
            return max(0.0, value_delta / span_min) if span_min > 0 else 0.0

        current_value_rate = value_rate(last_minute)
        prior_value_rate = value_rate(prior_band)
        compression_breakout = bool(
            prior_range_pct <= COMPRESSION_MAX_RANGE_PCT
            and current_value_rate >= max(prior_value_rate * VALUE_EXPLOSION_MULTIPLE, 0.01)
            and len(last_minute) >= 2
            and _number(last_minute[-1][2].get("price"))
            > _number(last_minute[0][2].get("price"))
        )
        total_cost_pct = ROUND_TRIP_FEE_TAX_PCT + SLIPPAGE_RESERVE_PCT + spread_pct
        required_volatility_pct = total_cost_pct * VOLATILITY_COST_MULTIPLE
        volatility_status = (
            "PASS" if recent_range_pct >= required_volatility_pct else "WAIT"
        )
        day_high = _number(micro.get("hi"))
        day_low = _number(micro.get("lo"))
        day_range_pct = (
            (day_high / day_low - 1.0) * 100.0
            if day_high > 0 and day_low > 0 and day_high >= day_low else 0.0
        )
        patterns = []
        if day_range_pct >= required_volatility_pct:
            patterns.append("장중고저확대")
        if compression_breakout:
            patterns.append("횡보후거래폭발")
        total_flow_volume = (
            _number(micro.get("buy_vol_cum"))
            + _number(micro.get("sell_vol_cum"))
        )
        intraday_vwap = (
            (buy_money + sell_money) / total_flow_volume
            if total_flow_volume > 0 and buy_money + sell_money > 0 else price
        )
        vwap_gap_pct = (
            (price / intraday_vwap - 1.0) * 100.0
            if intraday_vwap > 0 and price > 0 else 0.0
        )
        prior_phase = (
            str(prior.get("entry_phase") or "FLOW_FOUND")
            if same_session else "FLOW_FOUND"
        )
        setup_peak = _number(prior.get("setup_peak")) if same_session else 0.0
        pullback_anchor = (
            _number(prior.get("pullback_anchor")) if same_session else 0.0
        )
        entry_phase = prior_phase
        if prior_phase == "OVERHEAT_WAIT":
            setup_peak = max(setup_peak, price)
            peak_pullback_pct = (
                (price / setup_peak - 1.0) * 100.0 if setup_peak > 0 else 0.0
            )
            if price < intraday_vwap or peak_pullback_pct < -PULLBACK_MAX_PCT:
                entry_phase, setup_peak, pullback_anchor = "FLOW_FOUND", price, 0.0
            elif -PULLBACK_MAX_PCT <= peak_pullback_pct <= -PULLBACK_MIN_PCT:
                entry_phase, pullback_anchor = "PULLBACK_READY", price
        elif prior_phase == "PULLBACK_READY":
            setup_peak = max(setup_peak, price)
            pullback_anchor = min(pullback_anchor or price, price)
            peak_pullback_pct = (
                (price / setup_peak - 1.0) * 100.0 if setup_peak > 0 else 0.0
            )
            reaccel_pct = (
                (price / pullback_anchor - 1.0) * 100.0
                if pullback_anchor > 0 else 0.0
            )
            if price < intraday_vwap or peak_pullback_pct < -PULLBACK_MAX_PCT:
                entry_phase, setup_peak, pullback_anchor = "FLOW_FOUND", price, 0.0
            elif (
                reaccel_pct >= REACCEL_FROM_PULLBACK_PCT
                and accel > 0 and value_accel > 0 and price_step_pct > 0
            ):
                entry_phase = "REACCEL_TRIGGER"
        elif prior_phase == "REACCEL_TRIGGER":
            setup_peak = max(setup_peak, price)
            if price < intraday_vwap or accel <= 0 or value_accel <= 0:
                entry_phase, setup_peak, pullback_anchor = "FLOW_FOUND", price, 0.0
        else:
            setup_peak, pullback_anchor = price, 0.0
            entry_phase = (
                "OVERHEAT_WAIT"
                if vwap_gap_pct >= OVERHEAT_VWAP_GAP_PCT else "FLOW_FOUND"
            )
        peak_pullback_pct = (
            (price / setup_peak - 1.0) * 100.0 if setup_peak > 0 else 0.0
        )
        def window_return_pct(seconds: int, min_span: int) -> float:
            window = [item for item in timed_samples if 0 <= item[0] <= seconds]
            if len(window) < 2:
                return 0.0
            span = (window[-1][1] - window[0][1]).total_seconds()
            start_price = _number(window[0][2].get("price"))
            end_price = _number(window[-1][2].get("price"))
            return (
                (end_price / start_price - 1.0) * 100.0
                if span >= min_span and start_price > 0 else 0.0
            )

        rebound_speed_1m_pct = window_return_pct(60, 40)
        rebound_speed_3m_pct = window_return_pct(180, 120)
        flow_turn_time = (
            str(prior.get("flow_turn_time") or "") if same_session else ""
        )
        if valid_interval and previous_accel <= 0 < accel:
            flow_turn_time = str(micro.get("ts") or source_ts)
        flow_turn_dt = _timestamp(flow_turn_time)
        flow_turn_recent = bool(
            current_dt and flow_turn_dt
            and 0 <= (current_dt - flow_turn_dt).total_seconds() <= FLOW_TURN_WINDOW_SECONDS
        )
        low_dt = _timestamp(session_low_time)
        low_recent = bool(
            current_dt and low_dt
            and 0 <= (current_dt - low_dt).total_seconds() <= EARLY_REBOUND_WINDOW_SECONDS
        )
        early_rebound_status = "DATA_WAIT" if not session_low_time else "WATCH"
        if (
            low_recent
            and EARLY_REBOUND_MIN_PCT <= rebound_pct <= EARLY_REBOUND_MAX_PCT
            and rebound_speed_1m_pct >= EARLY_REBOUND_1M_SPEED_PCT
            and rebound_speed_3m_pct >= EARLY_REBOUND_3M_SPEED_PCT
            and flow_turn_recent and value_accel > 0
            and price >= intraday_vwap
        ):
            early_rebound_status = "EARLY_REBOUND"
        next_codes[code] = {
            "signed_money_mkrw": round(signed_money, 2),
            "value_eok": round(value_eok, 4), "price": price,
            "flow_accel_mkrw_per_min": round(accel, 2),
            "value_accel_eok_per_min": round(value_accel, 3),
            "price_step_pct": round(price_step_pct, 3),
            "positive_streak": streak,
            "session_low": session_low,
            "session_low_time": session_low_time,
            "samples": samples,
            "entry_phase": entry_phase,
            "setup_peak": setup_peak,
            "pullback_anchor": pullback_anchor,
            "flow_turn_time": flow_turn_time,
        }
        flow_ratio_pct = signed_money / value_eok if value_eok > 0 else 0.0
        relative_strength_pct = change_pct - market_pct
        blocked = []
        trend_ok = str(trend.get("state") or "") in ALLOWED_STATES
        smart_ok = smart_net > 0 and buy_count >= 2
        if not trend_ok:
            blocked.append("NO_DAILY_TREND")
        if not smart_ok:
            blocked.append("SMART_MONEY_PENDING")
        if "던짐" in grade or "매도" in grade:
            blocked.append("DUMP_GRADE")
        if value_eok < 30:
            blocked.append("LOW_LIQUIDITY")
        if change_pct <= 0 or relative_strength_pct <= 0:
            blocked.append("NO_PRICE_RESPONSE")
        if change_pct > 15:
            blocked.append("OVERHEATED")
        if streak < PERSISTENCE_REQUIRED:
            blocked.append(f"PERSISTENCE_{streak}/{PERSISTENCE_REQUIRED}")
        if accel <= 0 or value_accel <= 0:
            blocked.append("NO_INTRADAY_ACCELERATION")
        discovery_blocked = {
            reason for reason in blocked
            if reason not in {"NO_DAILY_TREND", "SMART_MONEY_PENDING"}
        }
        status = (
            "READY" if not blocked else
            "DISCOVERY" if not discovery_blocked else "WATCH"
        )
        base_score = (
            min(100.0, max(0.0, accel / max(value_eok, 1.0) * 10.0)) * 0.20
            + min(100.0, max(0.0, relative_strength_pct * 10.0)) * 0.20
            + min(100.0, max(0.0, (_number(micro.get("che_str") or raw.get("che")) - 90.0) * 2.0)) * 0.15
            + _number(trend.get("trend_score")) * 0.15
            + min(100.0, buy_count / 3.0 * 100.0) * 0.15
        )
        watch.append({
            "code": code, "name": raw.get("name") or trend.get("name") or code,
            "trend_state": trend.get("state") or "UNCONFIRMED",
            "trend_score": _number(trend.get("trend_score")),
            "flow_score": round(base_score, 1),
            "_base_score": base_score,
            "flow_source": "SMART+MICRO" if raw else "MICRO_DISCOVERY",
            "smart_net_mkrw": smart_net,
            "signed_money_mkrw": round(signed_money, 2),
            "flow_ratio_pct": round(flow_ratio_pct, 2),
            "flow_accel_mkrw_per_min": round(accel, 2),
            "value_accel_eok_per_min": round(value_accel, 3),
            "positive_streak": streak,
            "change_pct": change_pct,
            "relative_strength_pct": round(relative_strength_pct, 2),
            "buy_count": buy_count,
            "price": price,
            "session_low": session_low,
            "session_low_time": session_low_time,
            "rebound_amount": round(rebound_amount, 2),
            "rebound_pct": round(rebound_pct, 2),
            "two_way_depth_eok": round(two_way_depth_krw / 100_000_000.0, 2),
            "one_min_value_eok": round(one_min_value_krw / 100_000_000.0, 2),
            "spread_pct": round(spread_pct, 3),
            "slice_cap_manwon": int(slice_cap_krw // 10_000),
            "liquidity_status": liquidity_status,
            "intraday_vwap": round(intraday_vwap, 2),
            "vwap_gap_pct": round(vwap_gap_pct, 2),
            "peak_pullback_pct": round(peak_pullback_pct, 2),
            "entry_phase": entry_phase,
            "rebound_speed_1m_pct": round(rebound_speed_1m_pct, 2),
            "rebound_speed_3m_pct": round(rebound_speed_3m_pct, 2),
            "flow_turn_time": flow_turn_time,
            "early_rebound_status": early_rebound_status,
            "recent_range_pct": round(recent_range_pct, 2),
            "day_range_pct": round(day_range_pct, 2),
            "total_cost_pct": round(total_cost_pct, 2),
            "required_volatility_pct": round(required_volatility_pct, 2),
            "compression_range_pct": round(prior_range_pct, 2),
            "value_explosion_multiple": (
                round(current_value_rate / prior_value_rate, 2)
                if prior_value_rate > 0 else 0.0
            ),
            "volatility_pattern": "+".join(patterns) or "-",
            "volatility_status": volatility_status,
            "status": status,
            "blocked_by": blocked,
        })
    positive_accels = sorted(
        row["flow_accel_mkrw_per_min"]
        for row in watch if row["flow_accel_mkrw_per_min"] > 0
    )
    for row in watch:
        accel_value = row["flow_accel_mkrw_per_min"]
        absolute_percentile = (
            sum(value <= accel_value for value in positive_accels)
            / len(positive_accels) * 100.0
            if accel_value > 0 and positive_accels else 0.0
        )
        row["absolute_flow_percentile"] = round(absolute_percentile, 1)
        row["flow_score"] = round(
            float(row.pop("_base_score", 0.0)) + absolute_percentile * 0.15, 1
        )
    order = {"READY": 0, "DISCOVERY": 1, "WATCH": 2}
    watch.sort(key=lambda row: (order[row["status"]], -row["flow_score"], row["code"]))
    candidates = [row for row in watch if row["status"] == "READY"][:30]
    discoveries = [row for row in watch if row["status"] == "DISCOVERY"][:30]
    early_rebounds = sorted(
        [row for row in watch if row["early_rebound_status"] == "EARLY_REBOUND"],
        key=lambda row: (-row["rebound_speed_3m_pct"], -row["flow_score"], row["code"]),
    )[:30]
    display = sorted(
        watch, key=lambda row: (-row["flow_score"], row["code"])
    )[:30]
    result = {
        "schema": "flow_trend_intraday_board_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_ts": source_ts,
        "trend_source_date": trend_payload.get("source_date") or "",
        "mode": "SHADOW_ORDER_ZERO",
        "status": "READY" if valid_interval else "WARMUP",
        "persistence_required": PERSISTENCE_REQUIRED,
        "liquidity_reference_krw": LIQUIDITY_REFERENCE_KRW,
        "liquidity_mode": "HYPOTHETICAL_DISPLAY_ONLY",
        "volatility_mode": "HYPOTHETICAL_DISPLAY_ONLY",
        "entry_phase_mode": "HYPOTHETICAL_DISPLAY_ONLY",
        "early_rebound_mode": "HYPOTHETICAL_DISPLAY_ONLY",
        "market_pct": market_pct,
        "dynamic_universe": len(universe),
        "candidates": candidates,
        "discoveries": discoveries,
        "early_rebounds": early_rebounds,
        "display": display,
        "watch": watch[:30],
    }
    state = {
        "schema": "flow_trend_intraday_state_v1",
        "source_ts": source_ts,
        "codes": next_codes,
    }
    return result, state

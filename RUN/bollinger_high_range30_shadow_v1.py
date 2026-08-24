# -*- coding: utf-8 -*-
"""Order-zero, volatility-adaptive Bollinger shadow for high-range TOP30."""
from __future__ import annotations

import csv
import json
import os
import statistics
from datetime import datetime, time as clock_time
from pathlib import Path

PERIOD = 20
SQUEEZE_PERCENTILE = 0.20
MAX_SQUEEZE_WIDTH_PCT = 4.0
MIN_EXPANSION_RATIO = 1.05
MIN_ZSCORE = 2.0
ATR_STOP_MULTIPLIER = 1.5
MAX_HOLD_MINUTES = 60
FORCE_EXIT = clock_time(15, 20)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bands(values):
    if len(values) < PERIOD:
        return None
    window = values[-PERIOD:]
    mid = sum(window) / PERIOD
    std = statistics.pstdev(window)
    return None if mid <= 0 else (mid, mid + 2 * std, mid - 2 * std, std)


def _widths(values):
    result = []
    for end in range(PERIOD, len(values) + 1):
        band = _bands(values[:end])
        if band:
            mid, upper, lower, _ = band
            result.append((upper - lower) / mid * 100.0)
    return result[-50:]


def _percentile(values, fraction):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _append(path, row):
    columns = ["ts", "date", "code", "name", "event", "reason", "price",
               "entry_price", "return_pct", "hold_minutes", "bb_mid", "bb_upper",
               "bb_lower", "bb_width_pct", "squeeze_threshold_pct", "zscore",
               "expansion_ratio", "atr_proxy_pct", "max_gain_pct", "max_loss_pct",
               "requested_quantity", "provenance"]
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in columns})


def run_once(base: Path, payload: dict, live_state: dict, now: datetime):
    """Evaluate frozen high-range candidates; never import or call an order API."""
    if now.weekday() >= 5 or not (clock_time(9, 0) <= now.time() <= clock_time(15, 30)):
        return
    date = now.strftime("%Y%m%d")
    state_path = base / "data" / "shadow" / f"bollinger_high_range30_state_{date}.json"
    event_path = base / "data" / "shadow" / f"bollinger_high_range30_{date}.csv"
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        saved = {"date": date, "codes": {}}
    if saved.get("date") != date:
        saved = {"date": date, "codes": {}}

    candidates = {str(row.get("code") or "").zfill(6): row for row in payload.get("candidates", [])}
    for code, candidate in candidates.items():
        live = (live_state.get("codes") or {}).get(code) or {}
        if live.get("status") != "LIVE":
            continue
        prices = [_number(item[1]) for item in (live.get("minute_closes") or [])
                  if len(item) >= 2 and _number(item[1]) > 0]
        if len(prices) < PERIOD + 11:
            continue
        current = _number(live.get("current"))
        history = prices[:-1]
        band, current_band, widths = _bands(history), _bands(prices), _widths(history)
        if band is None or current_band is None or len(widths) < 10 or current <= 0:
            continue
        mid, upper, lower, std = band
        prior_width = (upper - lower) / mid * 100.0
        current_mid, current_upper, current_lower, _ = current_band
        width = (current_upper - current_lower) / current_mid * 100.0
        threshold = min(_percentile(widths, SQUEEZE_PERCENTILE), MAX_SQUEEZE_WIDTH_PCT)
        zscore = (current - mid) / std if std > 0 else 0.0
        returns = [abs(prices[i] / prices[i - 1] - 1) for i in range(max(1, len(prices) - PERIOD), len(prices))]
        atr_pct = statistics.fmean(returns) * 100 if returns else 0.0
        item = saved["codes"].setdefault(code, {})
        position = item.get("position")

        common = {"ts": now.isoformat(), "date": date, "code": code,
                  "name": candidate.get("name", ""), "price": round(current, 4),
                  "bb_mid": round(mid, 4), "bb_upper": round(upper, 4),
                  "bb_lower": round(lower, 4), "bb_width_pct": round(width, 4),
                  "squeeze_threshold_pct": round(threshold, 4), "zscore": round(zscore, 4),
                  "atr_proxy_pct": round(atr_pct, 4), "requested_quantity": 0,
                  "provenance": "HYPOTHETICAL"}
        if position:
            entry = _number(position["entry_price"])
            gain = (current / entry - 1) * 100
            position["max_gain_pct"] = max(_number(position.get("max_gain_pct")), gain)
            position["max_loss_pct"] = min(_number(position.get("max_loss_pct")), gain)
            hold = (now - datetime.fromisoformat(position["entry_ts"])).total_seconds() / 60
            stop_pct = max(1.0, min(3.0, atr_pct * ATR_STOP_MULTIPLIER))
            reason = ("VOLATILITY_STOP" if gain <= -stop_pct else
                      "BB_MID_BREAK" if current < mid else
                      "TIME_EXIT_60M" if hold >= MAX_HOLD_MINUTES else
                      "FORCE_EXIT_1520" if now.time() >= FORCE_EXIT else "")
            if reason:
                _append(event_path, {**common, "event": "SHADOW_EXIT", "reason": reason,
                        "entry_price": entry, "return_pct": round(gain, 4),
                        "hold_minutes": round(hold, 2),
                        "max_gain_pct": round(position["max_gain_pct"], 4),
                        "max_loss_pct": round(position["max_loss_pct"], 4)})
                item["position"] = None
                item["armed"] = False
            continue

        if prior_width <= threshold and current <= upper:
            item["armed"] = True
            item["armed_width_pct"] = prior_width
        armed_width = _number(item.get("armed_width_pct"), prior_width)
        expansion = width / armed_width if armed_width > 0 else 1.0
        if item.get("armed") and current > upper and zscore >= MIN_ZSCORE and expansion >= MIN_EXPANSION_RATIO:
            item["position"] = {"entry_ts": now.isoformat(), "entry_price": current,
                                "max_gain_pct": 0.0, "max_loss_pct": 0.0}
            item["armed"] = False
            _append(event_path, {**common, "event": "SHADOW_ENTRY",
                    "reason": "SQUEEZE_UPPER_BREAK_EXPANSION", "entry_price": round(current, 4),
                    "expansion_ratio": round(expansion, 4)})
    saved["updated_at"] = now.isoformat()
    _save(state_path, saved)

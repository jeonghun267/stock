from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EOD_PATH = ROOT / "data" / "eod_daily_bars.csv"
MINUTE_DIR = ROOT / "data" / "intraday_close_archive"
OUTPUT = ROOT / "data" / "research_reports" / "public_video_daytrade_patterns_20260821.json"
START_DATE, END_DATE = "20260611", "20260819"
HORIZONS = (5, 15, 30, 60)
COST_PCT = 0.47


def prepare_daily() -> dict[str, dict[str, dict[str, Any]]]:
    columns = ["date", "code", "open", "high", "low", "close", "value"]
    data = pd.read_csv(EOD_PATH, usecols=columns, dtype={"date": str, "code": str})
    for column in columns[2:]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna().sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    data["code"] = data["code"].astype(str).str.zfill(6)
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for code, group in data.groupby("code", sort=False):
        group = group.reset_index(drop=True)
        group["prev_close"] = group["close"].shift(1)
        group["day_return_pct"] = (group["close"] / group["prev_close"] - 1.0) * 100.0
        group["value_median20_prior"] = group["value"].shift(1).rolling(20, min_periods=10).median()
        group["ma5_prior"] = group["close"].shift(1).rolling(5, min_periods=5).mean()
        group["ma10_prior"] = group["close"].shift(1).rolling(10, min_periods=10).mean()
        for index, row in group.iterrows():
            date = str(row["date"])
            if not START_DATE <= date <= END_DATE:
                continue
            candidates = []
            for lag in range(3, 8):
                impulse_index = index - lag
                if impulse_index < 20:
                    continue
                impulse = group.iloc[impulse_index]
                median_value = float(impulse["value_median20_prior"] or 0)
                value_multiple = float(impulse["value"] / median_value) if median_value > 0 else 0.0
                return_pct = float(impulse["day_return_pct"] or 0)
                close_near_high = float(impulse["close"] / impulse["high"]) if impulse["high"] > 0 else 0.0
                if return_pct >= 20.0 and value_multiple >= 3.0:
                    candidates.append({
                        "lag": lag,
                        "anchor_open": float(impulse["open"]),
                        "impulse_return_pct": return_pct,
                        "value_multiple": value_multiple,
                        "limit_up": bool(return_pct >= 28.0 and close_near_high >= 0.98),
                    })
            if candidates:
                best = max(candidates, key=lambda item: (item["limit_up"], item["impulse_return_pct"], item["value_multiple"]))
                output.setdefault(date, {})[code] = {
                    **best,
                    "ma5_prior": float(row["ma5_prior"]) if pd.notna(row["ma5_prior"]) else 0.0,
                    "ma10_prior": float(row["ma10_prior"]) if pd.notna(row["ma10_prior"]) else 0.0,
                }
    return output


def low_rebound_trigger(bars: pd.DataFrame, candidate: dict[str, Any]) -> int | None:
    anchor = candidate["anchor_open"]
    support = min(value for value in (candidate["ma5_prior"], candidate["ma10_prior"]) if value > 0)
    eligible = bars[(bars["bar_ts"].dt.time >= pd.Timestamp("09:00").time()) &
                    (bars["bar_ts"].dt.time <= pd.Timestamp("14:20").time())].reset_index(drop=True)
    touch_indices = eligible.index[
        (eligible["low"] <= anchor * 1.02)
        & (eligible["low"] >= anchor * 0.97)
        & (eligible["low"] >= support * 0.97)
    ].tolist()
    if not touch_indices:
        return None
    touch = touch_indices[0]
    for index in range(touch + 3, len(eligible) - 1):
        recent = eligible.iloc[index - 3:index + 1]
        prior = eligible.iloc[index - 2:index]
        current = eligible.iloc[index]
        no_new_low = float(recent.iloc[-1]["low"]) > float(recent["low"].iloc[:-1].min())
        price_reclaim = float(current["close"]) > float(prior["high"].max())
        volume_turn = float(current["volume"]) > float(prior["volume"].mean())
        if no_new_low and price_reclaim and volume_turn:
            original_index = bars.index[bars["bar_ts"] == current["bar_ts"]]
            return int(original_index[0]) if len(original_index) else None
    return None


def same_day_volume_trigger(bars: pd.DataFrame) -> int | None:
    work = bars[(bars["bar_ts"].dt.time >= pd.Timestamp("09:00").time()) &
                (bars["bar_ts"].dt.time <= pd.Timestamp("14:20").time())].reset_index(drop=True)
    if len(work) < 15:
        return None
    median10 = work["volume"].shift(1).rolling(10, min_periods=10).median()
    body_pct = (work["close"] / work["open"] - 1.0) * 100.0
    close_position = (work["close"] - work["low"]) / (work["high"] - work["low"]).replace(0, np.nan)
    impulses = work.index[(body_pct >= 2.0) & (work["volume"] >= median10 * 10.0) & (close_position >= 0.80)].tolist()
    for impulse_index in impulses:
        impulse = work.iloc[impulse_index]
        midpoint = float(impulse["open"] + (impulse["close"] - impulse["open"]) * 0.50)
        end = min(len(work) - 1, impulse_index + 30)
        for index in range(impulse_index + 3, end):
            pullback = work.iloc[impulse_index + 1:index]
            current = work.iloc[index]
            if pullback.empty or float(pullback["low"].min()) < midpoint:
                continue
            volume_dry = float(pullback["volume"].tail(3).mean()) <= float(impulse["volume"]) * 0.50
            price_reclaim = float(current["close"]) > float(work.iloc[index - 2:index]["high"].max())
            volume_turn = float(current["volume"]) >= max(1.0, float(pullback["volume"].tail(3).mean()) * 2.0)
            if volume_dry and price_reclaim and volume_turn:
                original = bars.index[bars["bar_ts"] == current["bar_ts"]]
                return int(original[0]) if len(original) else None
    return None


def make_trade(pattern: str, code: str, bars: pd.DataFrame, trigger_index: int, meta: dict[str, Any]) -> dict[str, Any] | None:
    position = bars.index.get_loc(trigger_index)
    if position + 1 >= len(bars):
        return None
    entry_bar = bars.iloc[position + 1]
    entry_price = float(entry_bar["open"])
    if entry_price <= 0:
        return None
    window = bars.iloc[position + 1:position + 61]
    if window.empty:
        return None
    result: dict[str, Any] = {
        "pattern": pattern, "code": code,
        "signal_ts": bars.iloc[position]["bar_ts"].isoformat(),
        "entry_ts": entry_bar["bar_ts"].isoformat(),
        "entry_price": entry_price,
        "mfe_60m_pct": (float(window["high"].max()) / entry_price - 1.0) * 100.0,
        "mae_60m_pct": (float(window["low"].min()) / entry_price - 1.0) * 100.0,
        **meta,
    }
    for horizon in HORIZONS:
        if len(window) >= horizon:
            exit_price = float(window.iloc[horizon - 1]["close"])
            result[f"net_{horizon}m_pct"] = (exit_price / entry_price - 1.0) * 100.0 - COST_PCT
        else:
            result[f"net_{horizon}m_pct"] = None
    return result


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {
        "signals": int(len(frame)),
        "dates": int(frame["date"].nunique()) if len(frame) else 0,
        "codes": int(frame["code"].nunique()) if len(frame) else 0,
    }
    for horizon in HORIZONS:
        values = pd.to_numeric(frame[f"net_{horizon}m_pct"], errors="coerce").dropna() if len(frame) else pd.Series(dtype=float)
        output[f"observed_{horizon}m"] = int(len(values))
        output[f"mean_net_{horizon}m_pct"] = round(float(values.mean()), 6) if len(values) else None
        output[f"median_net_{horizon}m_pct"] = round(float(values.median()), 6) if len(values) else None
        output[f"win_rate_net_{horizon}m_pct"] = round(float((values > 0).mean() * 100.0), 4) if len(values) else None
    if len(frame):
        date_counts = frame.groupby("date").size().sort_values(ascending=False)
        output["largest_date_signal_share_pct"] = round(float(date_counts.iloc[0] / len(frame) * 100.0), 4)
        split_date = sorted(frame["date"].unique())[int(frame["date"].nunique() * 0.7)] if frame["date"].nunique() > 1 else frame["date"].iloc[0]
        output["early_70pct_dates"] = summarize_simple(frame[frame["date"] < split_date])
        output["late_30pct_dates"] = summarize_simple(frame[frame["date"] >= split_date])
    return output


def summarize_simple(frame: pd.DataFrame) -> dict[str, Any]:
    output = {"signals": int(len(frame)), "dates": int(frame["date"].nunique()) if len(frame) else 0}
    for horizon in HORIZONS:
        values = pd.to_numeric(frame[f"net_{horizon}m_pct"], errors="coerce").dropna() if len(frame) else pd.Series(dtype=float)
        output[f"mean_net_{horizon}m_pct"] = round(float(values.mean()), 6) if len(values) else None
    return output


def run() -> dict[str, Any]:
    daily = prepare_daily()
    trades: list[dict[str, Any]] = []
    minute_files = sorted(
        path for path in MINUTE_DIR.glob("prices_1m_*.csv")
        if START_DATE <= path.stem.rsplit("_", 1)[-1] <= END_DATE)
    for path in minute_files:
        date = path.stem.rsplit("_", 1)[-1]
        bars = pd.read_csv(path, usecols=["code", "ts", "open", "high", "low", "close", "volume"], dtype={"code": str, "ts": str})
        bars["code"] = bars["code"].astype(str).str.zfill(6)
        bars["bar_ts"] = pd.to_datetime(bars["ts"], format="%Y%m%d%H%M%S", errors="coerce")
        bars = bars.dropna(subset=["bar_ts"]).sort_values(["code", "bar_ts"])
        day_candidates = daily.get(date, {})
        for code, code_bars in bars.groupby("code", sort=False):
            code_bars = code_bars.reset_index(drop=True)
            candidate = day_candidates.get(code)
            if candidate:
                trigger = low_rebound_trigger(code_bars, candidate)
                if trigger is not None:
                    n_trade = make_trade("N_PULLBACK", code, code_bars, trigger, candidate)
                    if n_trade:
                        n_trade["date"] = date
                        trades.append(n_trade)
                    if candidate["limit_up"]:
                        limit_trade = make_trade("LIMIT_FIRST_FORCE", code, code_bars, trigger, candidate)
                        if limit_trade:
                            limit_trade["date"] = date
                            trades.append(limit_trade)
            trigger = same_day_volume_trigger(code_bars)
            if trigger is not None:
                volume_trade = make_trade("INTRADAY_VOLUME_PULLBACK", code, code_bars, trigger, {})
                if volume_trade:
                    volume_trade["date"] = date
                    trades.append(volume_trade)
    frame = pd.DataFrame(trades)
    summaries = {}
    for pattern in ("N_PULLBACK", "LIMIT_FIRST_FORCE", "INTRADAY_VOLUME_PULLBACK"):
        summaries[pattern] = summarize(frame[frame["pattern"] == pattern].copy()) if len(frame) else summarize(pd.DataFrame())
    result = {
        "schema": "public_video_daytrade_patterns_v1",
        "provenance": "[HYPOTHETICAL]",
        "performance_scope": "PUBLIC_RULE_TRANSLATION_NEXT_1M_OPEN_FIXED_EXIT_NOT_PRODUCTION",
        "period": {"from": START_DATE, "to": END_DATE, "minute_files": len(minute_files)},
        "cost_pct": COST_PCT,
        "summaries": summaries,
        "definitions": {
            "N_PULLBACK": ">=20% daily impulse, >=3x prior median value, 3-7 sessions later near impulse open and MA5/10 support, 3-minute low stabilization plus price/volume turn",
            "LIMIT_FIRST_FORCE": "N pullback subset with >=28% impulse and close near day high",
            "INTRADAY_VOLUME_PULLBACK": ">=2% bullish 1m bar with >=10x prior 10-bar median volume, <=50% retrace, volume dry-up, then price/volume reacceleration",
            "entry": "next one-minute bar open after confirmation",
            "exit": "fixed 5/15/30/60-minute bar close",
        },
        "sources": [str(EOD_PATH), str(MINUTE_DIR)],
        "limitations": [
            "Narrative concepts such as news validity and operator intent are intentionally excluded",
            "Minute archive covers the monitored universe, not every KRX stock",
            "Fixed exits are not current production strategy exits",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

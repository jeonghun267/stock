from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "eod_daily_bars.csv"
OUTPUT = ROOT / "data" / "research_reports" / "high_range_cycle_backtest_20260821.json"
COST_PCT = 0.47


def _summarize(frame: pd.DataFrame, mask: pd.Series) -> dict:
    result = {"signals": int(mask.sum())}
    for horizon in (1, 3, 5):
        values = frame.loc[mask, f"net_{horizon}d"].dropna()
        result[f"observed_{horizon}d"] = int(values.size)
        result[f"mean_net_{horizon}d_pct"] = round(float(values.mean()), 6) if len(values) else None
        result[f"median_net_{horizon}d_pct"] = round(float(values.median()), 6) if len(values) else None
        result[f"win_rate_net_{horizon}d_pct"] = round(float((values > 0).mean() * 100), 4) if len(values) else None
    return result


def run() -> dict:
    usecols = ["date", "code", "open", "high", "low", "close", "value"]
    df = pd.read_csv(SOURCE, usecols=usecols, dtype={"date": str, "code": str})
    for column in ("open", "high", "low", "close", "value"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "code", "open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df.sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    grouped = df.groupby("code", sort=False, group_keys=False)
    df["prev_close"] = grouped["close"].shift(1)
    df["range_pct"] = (df["high"] - df["low"]) / df["prev_close"] * 100.0
    df["ma20"] = grouped["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma20_slope5"] = df["ma20"] - grouped["ma20"].shift(5)
    df["prior_burst"] = grouped["range_pct"].transform(
        lambda s: s.shift(3).rolling(6, min_periods=6).max())
    df["contraction2"] = grouped["range_pct"].transform(
        lambda s: s.shift(1).rolling(2, min_periods=2).mean())
    trend = (df["close"] > df["ma20"]) & (df["ma20_slope5"] > 0)
    low_reclaim = (
        (df["low"] <= df["ma20"] * 1.02)
        & (df["low"] >= df["ma20"] * 0.95)
        & (df["close"] >= df["ma20"])
        & (df["close"] > df["open"])
    )
    baseline = trend & low_reclaim
    for horizon in (1, 3, 5):
        entry = grouped["open"].shift(-1)
        exit_close = grouped["close"].shift(-(horizon))
        df[f"net_{horizon}d"] = (exit_close / entry - 1.0) * 100.0 - COST_PCT

    variants = {}
    for burst_threshold in (8.0, 10.0, 12.0):
        cycle = baseline & (df["prior_burst"] >= burst_threshold) & (
            df["contraction2"] <= df["prior_burst"] * 0.70)
        variants[str(int(burst_threshold))] = _summarize(df, cycle)

    main = baseline & (df["prior_burst"] >= 10.0) & (
        df["contraction2"] <= df["prior_burst"] * 0.70)
    by_date = []
    for date, part in df.loc[main].groupby("date"):
        values = part["net_5d"].dropna()
        if len(values):
            by_date.append({"date": date, "signals": int(len(values)), "mean_net_5d_pct": round(float(values.mean()), 6)})
    result = {
        "schema": "high_range_cycle_backtest_v1",
        "provenance": "[HYPOTHETICAL]",
        "performance_scope": "EOD_RESEARCH_NEXT_OPEN_TO_CLOSE_NOT_PRODUCTION_ENTRY_EXIT",
        "source": str(SOURCE),
        "source_rows": int(len(df)),
        "unique_codes": int(df["code"].nunique()),
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "cost_pct": COST_PCT,
        "definitions": {
            "trend": "close>MA20 and MA20 higher than five sessions earlier",
            "burst": "maximum daily high-low range / previous close in sessions t-8..t-3",
            "contraction": "mean range of t-2..t-1 <= 70% of prior burst",
            "low_reclaim": "low within -5%/+2% of MA20, close>=MA20, bullish daily candle",
            "entry": "next session open",
            "exit": "close after 1/3/5 sessions",
        },
        "baseline": _summarize(df, baseline),
        "cycle_threshold_sensitivity": variants,
        "main_threshold": variants["10"],
        "main_by_date": by_date,
        "limitations": [
            "EOD-only; cannot reproduce intraday low-entry timing or production signal path",
            "Unadjusted/corporate-action quality depends on source file",
            "Thresholds are predeclared research values, not approved live conditions",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

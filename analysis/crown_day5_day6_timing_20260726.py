# -*- coding: utf-8 -*-
"""Compare day-5 and day-6 timing for high-range crown candidates.

This is a research-only analysis. It reads completed EOD and one-minute files,
does not import any broker/order module, and never submits an order.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(r"C:\stock_bot")
DATA = BASE / "data"
EOD_PATH = DATA / "eod_daily_bars.csv"
MINUTE_GLOB = "prices_1m_clean_*.csv"


def load_eod(path: Path = EOD_PATH) -> pd.DataFrame:
    columns = ["date", "code", "name", "open", "high", "low", "close", "value"]
    bars = pd.read_csv(
        path,
        usecols=columns,
        dtype={"date": str, "code": str, "name": str},
    )
    for column in ["open", "high", "low", "close", "value"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.dropna(subset=columns).sort_values(["code", "date"]).copy()
    bars["code"] = bars["code"].str.zfill(6)
    if bars.duplicated(["date", "code"]).any():
        raise ValueError("duplicate date-code rows in EOD")
    return bars


def add_metrics(bars: pd.DataFrame) -> pd.DataFrame:
    rows = bars.copy()
    rows["range_pct"] = (rows["high"] / rows["low"] - 1.0) * 100.0
    rows["value_eok"] = rows["value"] / 100.0
    rows["qualified"] = (rows["range_pct"] >= 10.0) & (
        rows["value_eok"] >= 100.0
    )
    grouped = rows.groupby("code", group_keys=False)
    rows["streak"] = (
        grouped["qualified"]
        .transform(lambda values: values.groupby((~values).cumsum()).cumsum())
        .astype(int)
    )
    rows["avg4_value"] = grouped["value_eok"].transform(
        lambda values: values.rolling(4, min_periods=4).mean()
    )
    rows["avg5_value"] = grouped["value_eok"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    next_columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "value_eok",
        "range_pct",
        "qualified",
        "avg5_value",
        "streak",
    ]
    for column in next_columns:
        rows[f"next_{column}"] = grouped[column].shift(-1)
    return rows


def build_cohort(rows: pd.DataFrame, attack_day: str) -> pd.DataFrame:
    market_dates = sorted(rows["date"].unique())
    next_market_date = {
        market_dates[index]: market_dates[index + 1]
        for index in range(len(market_dates) - 1)
    }
    if attack_day == "DAY5":
        cohort = rows[
            (rows["streak"] == 4)
            & (rows["avg4_value"] >= 500.0)
            & (rows["close"] >= 10_000.0)
        ].copy()
    elif attack_day == "DAY6":
        cohort = rows[
            (rows["streak"] == 5)
            & (rows["avg5_value"] >= 500.0)
            & (rows["close"] >= 10_000.0)
        ].copy()
    else:
        raise ValueError(f"unsupported attack day: {attack_day}")
    cohort["expected_next_date"] = cohort["date"].map(next_market_date)
    cohort = cohort[cohort["next_date"] == cohort["expected_next_date"]].copy()
    cohort["attack_day"] = attack_day
    cohort["gap_pct"] = (cohort["next_open"] / cohort["close"] - 1.0) * 100.0
    cohort["high_from_open_pct"] = (
        cohort["next_high"] / cohort["next_open"] - 1.0
    ) * 100.0
    cohort["low_from_open_pct"] = (
        cohort["next_low"] / cohort["next_open"] - 1.0
    ) * 100.0
    cohort["close_from_open_pct"] = (
        cohort["next_close"] / cohort["next_open"] - 1.0
    ) * 100.0
    cohort["continues"] = cohort["next_qualified"].astype(bool)
    cohort["crown_next"] = (
        cohort["next_qualified"].astype(bool)
        & (cohort["next_avg5_value"] >= 500.0)
        & (cohort["next_close"] >= 10_000.0)
    )
    return cohort


def summarize_eod(cohort: pd.DataFrame) -> dict:
    return {
        "samples": len(cohort),
        "median_high_from_open_pct": cohort["high_from_open_pct"].median(),
        "median_low_from_open_pct": cohort["low_from_open_pct"].median(),
        "median_close_from_open_pct": cohort["close_from_open_pct"].median(),
        "range10_value100_pct": cohort["continues"].mean() * 100.0,
        "crown_next_pct": cohort["crown_next"].mean() * 100.0,
        "high_ge_5_pct": (cohort["high_from_open_pct"] >= 5.0).mean() * 100.0,
        "high_ge_10_pct": (cohort["high_from_open_pct"] >= 10.0).mean() * 100.0,
        "low_le_minus3_pct": (cohort["low_from_open_pct"] <= -3.0).mean()
        * 100.0,
        "low_le_minus5_pct": (cohort["low_from_open_pct"] <= -5.0).mean()
        * 100.0,
        "close_above_open_pct": (cohort["close_from_open_pct"] > 0.0).mean()
        * 100.0,
    }


def minute_files() -> dict[str, Path]:
    return {
        path.stem.rsplit("_", 1)[-1]: path
        for path in DATA.glob(MINUTE_GLOB)
        if path.stat().st_size > 1_000
    }


def load_minute_file(path: Path) -> pd.DataFrame:
    columns = ["code", "ts", "open", "high", "low", "close"]
    rows = pd.read_csv(path, usecols=columns, dtype={"code": str, "ts": str})
    rows["code"] = rows["code"].str.zfill(6)
    for column in ["open", "high", "low", "close"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows = rows.dropna(subset=columns)
    rows["hhmm"] = rows["ts"].str[8:12]
    return rows[
        (rows["hhmm"] >= "0900") & (rows["hhmm"] <= "1530")
    ].sort_values(["code", "ts"])


def best_low_then_later_high(
    rows: pd.DataFrame,
    end_hhmm: str,
) -> tuple[float, str, str]:
    window = rows[
        (rows["hhmm"] >= "0900") & (rows["hhmm"] <= end_hhmm)
    ].reset_index(drop=True)
    if len(window) < 2:
        return np.nan, "", ""
    best_return, best_buy, best_sell = -np.inf, "", ""
    for index in range(len(window) - 1):
        future = window.iloc[index + 1 :]
        sell_index = future["high"].idxmax()
        candidate_return = (
            float(window.loc[sell_index, "high"]) / float(window.loc[index, "low"])
            - 1.0
        ) * 100.0
        if candidate_return > best_return:
            best_return = candidate_return
            best_buy = str(window.loc[index, "hhmm"])
            best_sell = str(window.loc[sell_index, "hhmm"])
    return best_return, best_buy, best_sell


def minute_details(cohort: pd.DataFrame) -> pd.DataFrame:
    records: list[dict] = []
    for trade_date, path in minute_files().items():
        targets = cohort[cohort["next_date"] == trade_date]
        if targets.empty:
            continue
        minutes = load_minute_file(path)
        for target in targets.itertuples(index=False):
            rows = minutes[minutes["code"] == target.code].reset_index(drop=True)
            if rows.empty:
                continue
            open_price = float(rows.iloc[0]["open"])
            high_row = rows.loc[rows["high"].idxmax()]
            low_row = rows.loc[rows["low"].idxmin()]
            best_1h = best_low_then_later_high(rows, "1000")
            best_2h = best_low_then_later_high(rows, "1100")
            records.append(
                {
                    "attack_day": target.attack_day,
                    "signal_date": target.date,
                    "trade_date": trade_date,
                    "code": target.code,
                    "name": target.name,
                    "high_from_open_pct": (
                        float(high_row["high"]) / open_price - 1.0
                    )
                    * 100.0,
                    "low_from_open_pct": (
                        float(low_row["low"]) / open_price - 1.0
                    )
                    * 100.0,
                    "high_time": str(high_row["hhmm"]),
                    "low_time": str(low_row["hhmm"]),
                    "low_before_high": str(low_row["hhmm"])
                    < str(high_row["hhmm"]),
                    "best_1h_pct": best_1h[0],
                    "best_1h_buy": best_1h[1],
                    "best_1h_sell": best_1h[2],
                    "best_2h_pct": best_2h[0],
                    "best_2h_buy": best_2h[1],
                    "best_2h_sell": best_2h[2],
                }
            )
    return pd.DataFrame(records)


def _time_to_minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[2:])


def _minutes_to_time(value: float) -> str:
    rounded = int(round(value))
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def summarize_minutes(details: pd.DataFrame) -> dict:
    return {
        "samples": len(details),
        "median_low_time": _minutes_to_time(
            details["low_time"].map(_time_to_minutes).median()
        ),
        "median_high_time": _minutes_to_time(
            details["high_time"].map(_time_to_minutes).median()
        ),
        "low_before_high_pct": details["low_before_high"].mean() * 100.0,
        "low_by_1000_pct": (details["low_time"] <= "1000").mean() * 100.0,
        "low_by_1100_pct": (details["low_time"] <= "1100").mean() * 100.0,
        "high_by_1000_pct": (details["high_time"] <= "1000").mean() * 100.0,
        "high_by_1100_pct": (details["high_time"] <= "1100").mean() * 100.0,
        "median_best_1h_pct": details["best_1h_pct"].median(),
        "median_best_2h_pct": details["best_2h_pct"].median(),
    }


def current_crown_times(rows: pd.DataFrame) -> pd.DataFrame:
    latest_date = str(rows["date"].max())
    selected = rows[
        (rows["date"] == latest_date)
        & rows["qualified"]
        & (rows["close"] >= 10_000.0)
        & (rows["streak"] >= 5)
        & (rows["avg5_value"] >= 500.0)
    ]
    path = minute_files().get(latest_date)
    if path is None:
        return pd.DataFrame()
    minutes = load_minute_file(path)
    records: list[dict] = []
    for selected_row in selected.itertuples(index=False):
        stock = minutes[minutes["code"] == selected_row.code].reset_index(drop=True)
        if stock.empty:
            continue
        low_row = stock.loc[stock["low"].idxmin()]
        high_row = stock.loc[stock["high"].idxmax()]
        records.append(
            {
                "date": latest_date,
                "code": selected_row.code,
                "name": selected_row.name,
                "streak": selected_row.streak,
                "low": float(low_row["low"]),
                "low_time": str(low_row["hhmm"]),
                "high": float(high_row["high"]),
                "high_time": str(high_row["hhmm"]),
                "low_before_high": str(low_row["hhmm"])
                < str(high_row["hhmm"]),
            }
        )
    return pd.DataFrame(records)


def run_analysis() -> dict[str, pd.DataFrame]:
    rows = add_metrics(load_eod())
    day5 = build_cohort(rows, "DAY5")
    day6 = build_cohort(rows, "DAY6")
    eod_summary = pd.DataFrame(
        [
            {"attack_day": "DAY5", **summarize_eod(day5)},
            {"attack_day": "DAY6", **summarize_eod(day6)},
        ]
    )
    details = pd.concat(
        [minute_details(day5), minute_details(day6)],
        ignore_index=True,
    )
    timing_summary = pd.DataFrame(
        [
            {
                "attack_day": attack_day,
                **summarize_minutes(group),
            }
            for attack_day, group in details.groupby("attack_day")
        ]
    )
    return {
        "eod_summary": eod_summary,
        "timing_summary": timing_summary,
        "minute_details": details,
        "current_crowns": current_crown_times(rows),
    }


if __name__ == "__main__":
    analysis = run_analysis()
    for name, frame in analysis.items():
        print(f"\n[{name}]")
        print(frame.round(2).to_string(index=False))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고저폭 TOP30 급락 뒤 단순 3분봉 MA3/MA20 교차와 1~2시간 매도 분석."""

from __future__ import annotations

import importlib.util
import json
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "analysis" / "strategy04_top30_open_drop_study.py"
OUT_JSON = ROOT / "analysis" / "strategy04_top30_ma_cross_exit_study.json"
OUT_MD = ROOT / "analysis" / "strategy04_top30_ma_cross_exit_study.md"

THRESHOLDS = (-12.0, -17.0)
COST_PCT = 0.50
STOP_PCT = -2.0
NET_TARGETS = (0.5, 1.0, 2.0)


def load_base():
    spec = importlib.util.spec_from_file_location("top30_base_study", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("TOP30 base study import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summary(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"n": 0}
    return {
        "n": int(len(clean)),
        "mean_pct": round(float(clean.mean()), 4),
        "median_pct": round(float(clean.median()), 4),
        "win_rate_pct": round(float((clean > 0).mean() * 100.0), 2),
        "loss_rate_pct": round(float((clean < 0).mean() * 100.0), 2),
        "worst_pct": round(float(clean.min()), 4),
        "best_pct": round(float(clean.max()), 4),
    }


def prepare_frame(base):
    top30, codes, names = base.load_top30()
    daily = base.load_daily(codes)
    intraday, quality = base.load_complete_intraday(codes)
    daily_meta = daily[
        ["date", "code", "name", "open", "high", "low", "prev_close", "prev_value"]
    ].rename(columns={"open": "day_open", "high": "day_high", "low": "day_low"})
    frame = intraday.merge(daily_meta, on=["date", "code"], how="inner")
    frame = frame[
        frame["prev_close"].ge(10_000)
        & frame["prev_value"].between(10_000, 2_000_000, inclusive="both")
    ].copy()
    bar_min = frame[["open", "high", "low", "close"]].min(axis=1)
    bar_max = frame[["open", "high", "low", "close"]].max(axis=1)
    frame["daily_ohlc_consistent"] = (
        bar_min.ge(frame["day_low"] * 0.995)
        & bar_max.le(frame["day_high"] * 1.005)
    )
    consistency = frame.groupby(["date", "code"])["daily_ohlc_consistent"].all()
    invalid = consistency[~consistency]
    valid = consistency[consistency].reset_index()[["date", "code"]]
    frame = frame.merge(valid, on=["date", "code"], how="inner")
    return top30, names, frame, quality, int(len(invalid))


def first_close_at_or_before(rows: pd.DataFrame, target: pd.Timestamp) -> float:
    selected = rows[rows["ts"].le(target)]
    return float(selected.iloc[-1]["close"]) if not selected.empty else float("nan")


def target_before_stop(
    rows: pd.DataFrame,
    *,
    entry: float,
    net_target_pct: float,
) -> tuple[bool, str]:
    target_price = entry * (1.0 + (net_target_pct + COST_PCT) / 100.0)
    stop_price = entry * (1.0 + STOP_PCT / 100.0)
    for row in rows.itertuples(index=False):
        stop_hit = float(row.low) <= stop_price
        target_hit = float(row.high) >= target_price
        if stop_hit and target_hit:
            return False, "SAME_BAR_AMBIGUOUS_AS_STOP"
        if stop_hit:
            return False, "STOP_FIRST"
        if target_hit:
            return True, "TARGET_FIRST"
    return False, "NEITHER"


def analyze_cross(
    group: pd.DataFrame,
    *,
    cross_i: int,
) -> dict[str, Any]:
    cross = group.iloc[cross_i]
    entry = float(cross["close"])
    future = group.iloc[cross_i + 1 :].copy()
    row: dict[str, Any] = {
        "cross_ts": pd.Timestamp(cross["ts"]).isoformat(),
        "entry_price": entry,
    }
    for minutes, label in ((60, "1h"), (120, "2h")):
        end = pd.Timestamp(cross["ts"]) + pd.Timedelta(minutes=minutes)
        window = future[future["ts"].le(end)]
        exit_price = first_close_at_or_before(future, end)
        row[f"exit_{label}_net_pct"] = (
            (exit_price / entry - 1.0) * 100.0 - COST_PCT
            if np.isfinite(exit_price)
            else float("nan")
        )
        if window.empty:
            row[f"mfe_{label}_net_pct"] = float("nan")
            row[f"mae_{label}_pct"] = float("nan")
            row[f"stop_hit_{label}"] = False
            for target in NET_TARGETS:
                suffix = str(target).replace(".", "_")
                row[f"target_{suffix}_touch_{label}"] = False
                row[f"target_{suffix}_before_stop_{label}"] = False
                row[f"target_{suffix}_outcome_{label}"] = "NO_DATA"
            continue
        row[f"mfe_{label}_net_pct"] = (
            float(window["high"].max()) / entry - 1.0
        ) * 100.0 - COST_PCT
        row[f"mae_{label}_pct"] = (
            float(window["low"].min()) / entry - 1.0
        ) * 100.0
        row[f"stop_hit_{label}"] = bool(
            float(window["low"].min()) <= entry * (1.0 + STOP_PCT / 100.0)
        )
        for target in NET_TARGETS:
            suffix = str(target).replace(".", "_")
            target_price = entry * (1.0 + (target + COST_PCT) / 100.0)
            touched = bool(float(window["high"].max()) >= target_price)
            before_stop, outcome = target_before_stop(
                window, entry=entry, net_target_pct=target
            )
            row[f"target_{suffix}_touch_{label}"] = touched
            row[f"target_{suffix}_before_stop_{label}"] = before_stop
            row[f"target_{suffix}_outcome_{label}"] = outcome
    return row


def event_rows(frame: pd.DataFrame) -> pd.DataFrame:
    events: list[dict[str, Any]] = []
    for (date, code), group in frame.groupby(["date", "code"], sort=True):
        group = group.sort_values("ts").reset_index(drop=True)
        group["ma3"] = group["close"].rolling(3).mean()
        group["ma20"] = group["close"].rolling(20).mean()
        group["raw_cross"] = (
            group["ma3"].shift(1).le(group["ma20"].shift(1))
            & group["ma3"].gt(group["ma20"])
        )
        day_open = float(group.iloc[0]["day_open"])
        for threshold in THRESHOLDS:
            trigger_price = day_open * (1.0 + threshold / 100.0)
            hits = group[group["low"].le(trigger_price)]
            if hits.empty:
                continue
            trigger_i = int(hits.index[0])
            trigger_ts = pd.Timestamp(group.loc[trigger_i, "ts"])
            if trigger_ts.time() >= time(12, 0):
                continue
            later_crosses = group.index[
                (group.index > trigger_i)
                & group["raw_cross"]
                & (group["ts"].dt.time < time(14, 0))
            ].tolist()
            entry_crosses = [
                index
                for index in later_crosses
                if time(10, 0) <= pd.Timestamp(group.loc[index, "ts"]).time() < time(12, 0)
            ]
            row: dict[str, Any] = {
                "date": int(date),
                "code": str(code),
                "name": str(group.iloc[0]["name"]),
                "threshold_pct": threshold,
                "trigger_ts": trigger_ts.isoformat(),
                "minimum_drop_from_open_pct": round(
                    (float(group["low"].min()) / day_open - 1.0) * 100.0, 4
                ),
                "raw_cross_by_1400": bool(later_crosses),
                "raw_cross_count_by_1400": int(len(later_crosses)),
                "raw_cross_1000_1200": bool(entry_crosses),
                "raw_cross_count_1000_1200": int(len(entry_crosses)),
            }
            if entry_crosses:
                row.update(analyze_cross(group, cross_i=entry_crosses[0]))
            events.append(row)
    return pd.DataFrame(events)


def build_summary(events: pd.DataFrame, full_pattern: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for threshold in THRESHOLDS:
        key = str(int(abs(threshold)))
        rows = events[events["threshold_pct"].eq(threshold)].copy()
        crossed = rows[rows["raw_cross_1000_1200"]].copy()
        threshold_result: dict[str, Any] = {
            "events_before_noon": int(len(rows)),
            "raw_cross_by_1400": int(rows["raw_cross_by_1400"].sum()),
            "raw_cross_by_1400_rate_pct": round(
                float(rows["raw_cross_by_1400"].mean() * 100.0), 2
            )
            if not rows.empty
            else None,
            "raw_cross_1000_1200": int(rows["raw_cross_1000_1200"].sum()),
            "raw_cross_1000_1200_rate_pct": round(
                float(rows["raw_cross_1000_1200"].mean() * 100.0), 2
            )
            if not rows.empty
            else None,
            "current_s04_full_price_pattern": int(
                full_pattern.get(key, {}).get("price_pattern_found", 0)
            ),
            "entry_cross_sample": int(len(crossed)),
            "exit_1h_net": summary(crossed.get("exit_1h_net_pct", pd.Series(dtype=float))),
            "exit_2h_net": summary(crossed.get("exit_2h_net_pct", pd.Series(dtype=float))),
            "mfe_1h_net": summary(crossed.get("mfe_1h_net_pct", pd.Series(dtype=float))),
            "mfe_2h_net": summary(crossed.get("mfe_2h_net_pct", pd.Series(dtype=float))),
            "stop_hit_1h_rate_pct": round(
                float(crossed["stop_hit_1h"].mean() * 100.0), 2
            )
            if not crossed.empty
            else None,
            "stop_hit_2h_rate_pct": round(
                float(crossed["stop_hit_2h"].mean() * 100.0), 2
            )
            if not crossed.empty
            else None,
        }
        for label in ("1h", "2h"):
            for target in NET_TARGETS:
                suffix = str(target).replace(".", "_")
                touch_col = f"target_{suffix}_touch_{label}"
                before_col = f"target_{suffix}_before_stop_{label}"
                outcome_col = f"target_{suffix}_outcome_{label}"
                policy_return = np.where(
                    crossed[outcome_col].eq("TARGET_FIRST"),
                    target,
                    np.where(
                        crossed[outcome_col].isin(
                            ["STOP_FIRST", "SAME_BAR_AMBIGUOUS_AS_STOP"]
                        ),
                        STOP_PCT - COST_PCT,
                        crossed[f"exit_{label}_net_pct"],
                    ),
                )
                threshold_result[f"net_target_{target:.1f}_{label}"] = {
                    "touch_rate_pct": round(
                        float(crossed[touch_col].mean() * 100.0), 2
                    )
                    if not crossed.empty
                    else None,
                    "before_stop_conservative_rate_pct": round(
                        float(crossed[before_col].mean() * 100.0), 2
                    )
                    if not crossed.empty
                    else None,
                    "target_stop_or_time_return": summary(
                        pd.Series(policy_return, dtype=float)
                    ),
                }
        output[key] = threshold_result
    return output


def build_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 고저폭 TOP30 — 단순 MA3/20 교차 후 1~2시간 매도",
        "",
        "- 단순 교차: 완성 3분봉 MA3가 MA20을 아래에서 위로 통과",
        "- 현재 S04 전체 가격구조: 단순 교차에 W·목선·추격·시간 조건을 추가",
        "- 비용: 왕복 0.50%, 손절: 매수가 대비 -2.0%",
        "- 고점 수익(MFE)은 사후 상한선, 고정 목표가는 실행 가능한 근사치",
        "",
        "| 시가 낙폭 | 사건 | 14시 전 단순교차 | 10~12시 교차 | S04 전체구조 | 1시간 종가 승률/평균 | 2시간 종가 승률/평균 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("12", "17"):
        row = result["summary"][key]
        lines.append(
            f"| -{key}% | {row['events_before_noon']} | "
            f"{row['raw_cross_by_1400']} ({row['raw_cross_by_1400_rate_pct']:.1f}%) | "
            f"{row['raw_cross_1000_1200']} ({row['raw_cross_1000_1200_rate_pct']:.1f}%) | "
            f"{row['current_s04_full_price_pattern']} | "
            f"{row['exit_1h_net'].get('win_rate_pct', 0):.1f}%/{row['exit_1h_net'].get('mean_pct', 0):+.2f}% | "
            f"{row['exit_2h_net'].get('win_rate_pct', 0):.1f}%/{row['exit_2h_net'].get('mean_pct', 0):+.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 실행 가능한 고정 익절",
            "",
            "| 시가 낙폭 | 시간 | 순익 +0.5% 도달/손절 전 | 순익 +1.0% 도달/손절 전 | 순익 +2.0% 도달/손절 전 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for key in ("12", "17"):
        row = result["summary"][key]
        for label in ("1h", "2h"):
            cells = []
            for target in NET_TARGETS:
                stat = row[f"net_target_{target:.1f}_{label}"]
                cells.append(
                    f"{stat['touch_rate_pct'] or 0:.1f}%/{stat['before_stop_conservative_rate_pct'] or 0:.1f}%"
                )
            lines.append(f"| -{key}% | {label} | {' | '.join(cells)} |")
    lines.extend(
        [
            "",
            "## 한계",
            "",
            "- 현재 TOP30을 과거에 소급한 표본이며, 연속 3분봉이 있는 종목일만 사용했습니다.",
            "- 같은 3분봉에서 목표가와 손절가가 모두 닿으면 손절이 먼저인 것으로 보수 처리했습니다.",
            "- 초단위 호가·수급을 포함한 실제 공통 매도엔진 재생은 아닙니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    base = load_base()
    top30, names, frame, quality, invalid_count = prepare_frame(base)
    events = event_rows(frame)
    prior = json.loads(base.OUT_JSON.read_text(encoding="utf-8"))
    result = {
        "schema": "strategy04_top30_ma_cross_exit_study_v1",
        "scope": {
            "for_date": top30.get("for_date"),
            "source_date": top30.get("source_date"),
            "candidate_count": 30,
            "cost_pct": COST_PCT,
            "stop_pct": STOP_PCT,
            "cross_definition": "completed 3m MA3 crosses above MA20 after threshold",
            "entry_window": "10:00<=cross<12:00",
        },
        "data_quality": {
            **quality,
            "daily_ohlc_inconsistent_stock_days_excluded": invalid_count,
        },
        "summary": build_summary(events, prior["intraday_summary"]),
        "events": events.replace({np.nan: None}).to_dict(orient="records"),
    }
    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    OUT_MD.write_text(build_markdown(result), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

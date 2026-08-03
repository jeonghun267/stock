#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고저폭 TOP30의 당일 시가 대비 -12%/-17% 급락 후 반등·손실·S04 포착력 분석."""

from __future__ import annotations

import json
import sys
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TOP30_PATH = ROOT / "data" / "common_high_range_top30.json"
DAILY_PATH = ROOT / "data" / "eod_daily_bars.csv"
INTRADAY_PATH = ROOT / "data" / "prices_3m.csv"
S04_STATE_PATH = ROOT / "data" / "strategy_04_pullback_signal_state_v1.json"
S04_SIGNAL_PATH = ROOT / "data" / "strategy_04_pullback_signal_v1.json"
WATCH_PATH = ROOT / "IPC" / "micro_watch_valley.json"
OUT_JSON = ROOT / "analysis" / "strategy04_top30_open_drop_study.json"
OUT_MD = ROOT / "analysis" / "strategy04_top30_open_drop_study.md"

THRESHOLDS = (-12.0, -17.0)
OFFICIAL_COST_PCT = 0.21
CONSERVATIVE_COST_PCT = 0.50
HARD_STOP_PCT = -2.0
NAMED_CODES = ("024060", "389260", "119850")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _summary(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"n": 0}
    return {
        "n": int(len(clean)),
        "mean_pct": round(float(clean.mean()), 4),
        "median_pct": round(float(clean.median()), 4),
        "win_rate_pct": round(float((clean > 0).mean() * 100), 2),
        "loss_rate_pct": round(float((clean < 0).mean() * 100), 2),
        "p10_pct": round(float(clean.quantile(0.10)), 4),
        "worst_pct": round(float(clean.min()), 4),
        "best_pct": round(float(clean.max()), 4),
    }


def load_top30() -> tuple[dict[str, Any], list[str], dict[str, str]]:
    payload = json.loads(TOP30_PATH.read_text(encoding="utf-8"))
    rows = payload.get("candidates") or []
    codes = [str(row["code"]).zfill(6) for row in rows]
    if len(codes) != 30 or len(set(codes)) != 30:
        raise RuntimeError(f"TOP30 명단 불일치: rows={len(codes)}, unique={len(set(codes))}")
    names = {str(row["code"]).zfill(6): str(row["name"]) for row in rows}
    return payload, codes, names


def load_daily(codes: list[str]) -> pd.DataFrame:
    usecols = ["date", "code", "name", "market", "open", "high", "low", "close", "value"]
    frame = pd.read_csv(DAILY_PATH, usecols=usecols, dtype={"code": str})
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame = frame[
        frame["code"].isin(codes)
        & frame["code"].str.fullmatch(r"\d{6}")
        & frame["market"].eq("KOSDAQ")
    ].copy()
    frame["date"] = pd.to_numeric(frame["date"], errors="coerce").astype("Int64")
    for col in ["open", "high", "low", "close", "value"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame = frame[(frame[["open", "high", "low", "close"]] > 0).all(axis=1)]
    frame = frame.sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    frame["prev_close"] = frame.groupby("code")["close"].shift(1)
    frame["prev_value"] = frame.groupby("code")["value"].shift(1)
    frame["drop_from_open_pct"] = (frame["low"] / frame["open"] - 1.0) * 100.0
    return frame


def daily_event_rows(daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    outputs: list[pd.DataFrame] = []
    summaries: dict[str, Any] = {}
    eligible = daily[
        daily["prev_close"].ge(10_000)
        & daily["prev_value"].between(10_000, 2_000_000, inclusive="both")
    ].copy()
    for threshold in THRESHOLDS:
        events = eligible[eligible["drop_from_open_pct"].le(threshold)].copy()
        entry = events["open"] * (1.0 + threshold / 100.0)
        events["threshold_pct"] = threshold
        events["entry_at_threshold"] = entry
        events["close_gross_pct"] = (events["close"] / entry - 1.0) * 100.0
        events["close_net_021_pct"] = events["close_gross_pct"] - OFFICIAL_COST_PCT
        events["close_net_050_pct"] = events["close_gross_pct"] - CONSERVATIVE_COST_PCT
        events["hard_stop_hit"] = ((events["low"] / entry - 1.0) * 100.0).le(HARD_STOP_PCT)
        events["threshold_entry_stop_or_close_net_050_pct"] = np.where(
            events["hard_stop_hit"],
            HARD_STOP_PCT - CONSERVATIVE_COST_PCT,
            events["close_net_050_pct"],
        )
        key = str(int(abs(threshold)))
        summaries[key] = {
            "events": int(len(events)),
            "stock_days": int(eligible.shape[0]),
            "date_min": str(int(events["date"].min())) if not events.empty else None,
            "date_max": str(int(events["date"].max())) if not events.empty else None,
            "close_net_050": _summary(events["close_net_050_pct"]),
            "close_net_021": _summary(events["close_net_021_pct"]),
            "hard_stop_hit_rate_pct": round(float(events["hard_stop_hit"].mean() * 100), 2)
            if not events.empty
            else None,
            "threshold_stop_or_close_net_050": _summary(
                events["threshold_entry_stop_or_close_net_050_pct"]
            ),
        }
        outputs.append(events)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame(), summaries


def load_complete_intraday(codes: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    chunks: list[pd.DataFrame] = []
    usecols = ["ts", "code", "open", "high", "low", "close"]
    for chunk in pd.read_csv(
        INTRADAY_PATH,
        usecols=usecols,
        dtype={"code": str},
        chunksize=150_000,
    ):
        chunk["code"] = chunk["code"].astype(str).str.zfill(6)
        selected = chunk[chunk["code"].isin(codes)].copy()
        if not selected.empty:
            chunks.append(selected)
    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=usecols)
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["ts", "open", "high", "low", "close"])
    frame = frame[(frame[["open", "high", "low", "close"]] > 0).all(axis=1)]
    frame["date"] = frame["ts"].dt.strftime("%Y%m%d").astype(int)
    frame = frame.sort_values(["date", "code", "ts"]).drop_duplicates(
        ["date", "code", "ts"], keep="last"
    )
    quality = frame.groupby(["date", "code"]).agg(
        rows=("ts", "size"),
        first=("ts", "min"),
        last=("ts", "max"),
        max_gap_min=("ts", lambda series: series.diff().dt.total_seconds().div(60).max()),
    )
    complete = quality[
        (quality["rows"] >= 110)
        & (quality["first"].dt.time <= time(9, 3))
        & (quality["last"].dt.time >= time(15, 9))
        & (quality["max_gap_min"] <= 9)
    ].reset_index()[["date", "code"]]
    frame = frame.merge(complete, on=["date", "code"], how="inner")
    info = {
        "raw_top30_rows": int(sum(len(chunk) for chunk in chunks)),
        "raw_stock_days": int(len(quality)),
        "complete_stock_days": int(len(complete)),
        "complete_dates": int(complete["date"].nunique()),
        "quality_rule": ">=110 bars, first<=09:03, last>=15:09, max_gap<=9m",
    }
    return frame, info


def _close_at_or_before(future: pd.DataFrame, target: pd.Timestamp) -> float:
    rows = future[future["ts"].le(target)]
    return float(rows.iloc[-1]["close"]) if not rows.empty else float("nan")


def _replay_price_pattern(
    group: pd.DataFrame,
    prev_close: float,
) -> dict[str, Any] | None:
    sys.path.insert(0, str(ROOT / "RUN"))
    from strategy_04_pullback_signal_v1 import Bar, SignalConfig, detect_deep_w

    config = SignalConfig()
    bars = [
        Bar(
            ts=row.ts.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            value=0.0,
        )
        for row in group.itertuples(index=False)
    ]
    for end in range(19, len(bars)):
        current_time = bars[end].ts.time()
        if current_time < time(10, 0):
            continue
        if current_time >= time(12, 0):
            break
        pattern = detect_deep_w(bars[: end + 1], prev_close=prev_close, config=config)
        if pattern is not None:
            pattern = dict(pattern)
            pattern["signal_ts"] = bars[end].ts.isoformat(timespec="minutes")
            pattern["signal_price"] = bars[end].close
            pattern["auto_drop_allowed"] = pattern["drop_pct"] >= config.min_drop_pct
            return pattern
    return None


def intraday_event_rows(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    daily_meta = daily[
        ["date", "code", "name", "open", "high", "low", "prev_close", "prev_value"]
    ].rename(columns={"open": "day_open", "high": "day_high", "low": "day_low"})
    frame = intraday.merge(daily_meta, on=["date", "code"], how="inner")
    frame = frame[
        frame["prev_close"].ge(10_000)
        & frame["prev_value"].between(10_000, 2_000_000, inclusive="both")
    ].copy()
    intraday_min = frame[["open", "high", "low", "close"]].min(axis=1)
    intraday_max = frame[["open", "high", "low", "close"]].max(axis=1)
    frame["daily_ohlc_consistent"] = (
        intraday_min.ge(frame["day_low"] * 0.995)
        & intraday_max.le(frame["day_high"] * 1.005)
    )
    consistency = frame.groupby(["date", "code"])["daily_ohlc_consistent"].all()
    invalid_keys = consistency[~consistency].index
    valid_keys = consistency[consistency].reset_index()[["date", "code"]]
    frame = frame.merge(valid_keys, on=["date", "code"], how="inner")
    events: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    for (date, code), group in frame.groupby(["date", "code"], sort=True):
        group = group.sort_values("ts").reset_index(drop=True)
        day_open = float(group.iloc[0]["day_open"])
        prev_close = float(group.iloc[0]["prev_close"])
        minimum_drop = (float(group["low"].min()) / day_open - 1.0) * 100.0
        pattern = _replay_price_pattern(group, prev_close) if minimum_drop <= -12.0 else None
        if pattern is not None:
            signal_ts = pd.Timestamp(pattern["signal_ts"])
            signal_i = int(group["ts"].searchsorted(signal_ts, side="left"))
            signal_future = group.iloc[signal_i + 1 :]
            pattern_row = {
                "date": int(date),
                "code": str(code),
                "name": str(group.iloc[0]["name"]),
                **pattern,
            }
            if not signal_future.empty:
                entry = float(pattern["signal_price"])
                pattern_row["mfe_to_1510_net_050_pct"] = (
                    float(signal_future[signal_future["ts"].dt.time <= time(15, 9)]["high"].max())
                    / entry
                    - 1.0
                ) * 100.0 - CONSERVATIVE_COST_PCT
                exit_price = _close_at_or_before(
                    signal_future, pd.Timestamp(f"{date} 15:09:00")
                )
                pattern_row["exit_1510_net_050_pct"] = (
                    (exit_price / entry - 1.0) * 100.0 - CONSERVATIVE_COST_PCT
                    if np.isfinite(exit_price)
                    else float("nan")
                )
            patterns.append(pattern_row)
        for threshold in THRESHOLDS:
            trigger_price = day_open * (1.0 + threshold / 100.0)
            hits = group[group["low"].le(trigger_price)]
            if hits.empty:
                continue
            trigger_i = int(hits.index[0])
            trigger_ts = pd.Timestamp(group.loc[trigger_i, "ts"])
            if trigger_ts.time() >= time(12, 0):
                continue
            future = group.iloc[trigger_i + 1 :]
            through_1510 = future[future["ts"].dt.time <= time(15, 9)]
            if through_1510.empty:
                continue
            row: dict[str, Any] = {
                "date": int(date),
                "code": str(code),
                "name": str(group.iloc[0]["name"]),
                "threshold_pct": threshold,
                "trigger_ts": trigger_ts.isoformat(),
                "entry_at_threshold": trigger_price,
                "minimum_drop_from_open_pct": round(minimum_drop, 4),
                "mfe_to_1510_net_050_pct": (
                    float(through_1510["high"].max()) / trigger_price - 1.0
                )
                * 100.0
                - CONSERVATIVE_COST_PCT,
                "mae_to_1510_pct": (
                    min(float(group.loc[trigger_i, "low"]), float(through_1510["low"].min()))
                    / trigger_price
                    - 1.0
                )
                * 100.0,
                "hard_stop_hit": (
                    min(float(group.loc[trigger_i, "low"]), float(through_1510["low"].min()))
                    / trigger_price
                    - 1.0
                )
                * 100.0
                <= HARD_STOP_PCT,
                "price_pattern_found": pattern is not None,
                "price_pattern_auto_allowed": bool(
                    pattern is not None and pattern["auto_drop_allowed"]
                ),
            }
            for minutes, label in ((60, "1h"), (120, "2h"), (180, "3h")):
                exit_price = _close_at_or_before(
                    future, trigger_ts + pd.Timedelta(minutes=minutes)
                )
                row[f"exit_{label}_net_050_pct"] = (
                    (exit_price / trigger_price - 1.0) * 100.0 - CONSERVATIVE_COST_PCT
                    if np.isfinite(exit_price)
                    else float("nan")
                )
            exit_1510 = _close_at_or_before(
                through_1510, pd.Timestamp(f"{date} 15:09:00")
            )
            row["exit_1510_net_050_pct"] = (
                (exit_1510 / trigger_price - 1.0) * 100.0 - CONSERVATIVE_COST_PCT
                if np.isfinite(exit_1510)
                else float("nan")
            )
            events.append(row)
    event_frame = pd.DataFrame(events)
    pattern_frame = pd.DataFrame(patterns)
    summaries: dict[str, Any] = {}
    for threshold in THRESHOLDS:
        rows = event_frame[event_frame["threshold_pct"].eq(threshold)].copy()
        rows["stop_or_1510_net_050_pct"] = np.where(
            rows["hard_stop_hit"],
            HARD_STOP_PCT - CONSERVATIVE_COST_PCT,
            rows["exit_1510_net_050_pct"],
        )
        key = str(int(abs(threshold)))
        summaries[key] = {
            "events_before_noon": int(len(rows)),
            "exit_1h_net_050": _summary(rows.get("exit_1h_net_050_pct", pd.Series(dtype=float))),
            "exit_2h_net_050": _summary(rows.get("exit_2h_net_050_pct", pd.Series(dtype=float))),
            "exit_3h_net_050": _summary(rows.get("exit_3h_net_050_pct", pd.Series(dtype=float))),
            "exit_1510_net_050": _summary(
                rows.get("exit_1510_net_050_pct", pd.Series(dtype=float))
            ),
            "mfe_to_1510_net_050": _summary(
                rows.get("mfe_to_1510_net_050_pct", pd.Series(dtype=float))
            ),
            "hard_stop_hit_rate_pct": round(float(rows["hard_stop_hit"].mean() * 100), 2)
            if not rows.empty
            else None,
            "stop_or_1510_net_050": _summary(rows["stop_or_1510_net_050_pct"]),
            "price_pattern_found": int(rows["price_pattern_found"].sum())
            if not rows.empty
            else 0,
            "price_pattern_auto_allowed": int(rows["price_pattern_auto_allowed"].sum())
            if not rows.empty
            else 0,
        }
    summaries["_data_quality"] = {
        "daily_ohlc_inconsistent_stock_days_excluded": int(len(invalid_keys)),
        "rule": "all 3m OHLC within completed daily low/high ±0.5%",
    }
    return event_frame, summaries, pattern_frame


def named_daily_history(events: pd.DataFrame, names: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code in NAMED_CODES:
        for threshold in THRESHOLDS:
            selected = events[
                events["code"].eq(code) & events["threshold_pct"].eq(threshold)
            ]
            rows.append(
                {
                    "code": code,
                    "name": names.get(code, code),
                    "threshold_pct": threshold,
                    "events": int(len(selected)),
                    "close_net_050": _summary(selected["close_net_050_pct"]),
                    "hard_stop_hit_rate_pct": round(
                        float(selected["hard_stop_hit"].mean() * 100), 2
                    )
                    if not selected.empty
                    else None,
                }
            )
    return rows


def current_named(names: dict[str, str]) -> dict[str, Any]:
    state = json.loads(S04_STATE_PATH.read_text(encoding="utf-8"))
    signal = json.loads(S04_SIGNAL_PATH.read_text(encoding="utf-8"))
    watch = json.loads(WATCH_PATH.read_text(encoding="utf-8"))
    candidate_rows = {
        str(row.get("code")).zfill(6): row for row in signal.get("candidates") or []
    }
    meta = watch.get("all_meta") or {}
    output: list[dict[str, Any]] = []
    for code in NAMED_CODES:
        bars = (state.get("codes") or {}).get(code, {}).get("bars") or []
        if not bars:
            continue
        day_open = _number(bars[0].get("open"))
        day_low = min(_number(row.get("low")) for row in bars)
        last = _number(bars[-1].get("close"))
        prev_close = _number((meta.get(code) or {}).get("prev_close"))
        item: dict[str, Any] = {
            "code": code,
            "name": names.get(code, code),
            "observed_until": bars[-1].get("ts"),
            "day_open": day_open,
            "day_low": day_low,
            "last": last,
            "drop_from_open_pct": round((day_low / day_open - 1.0) * 100.0, 4),
            "drop_from_prev_close_pct": round((day_low / prev_close - 1.0) * 100.0, 4),
            "candidate_reason": (candidate_rows.get(code) or {}).get("reason"),
        }
        threshold_observations: list[dict[str, Any]] = []
        for threshold in THRESHOLDS:
            trigger_price = day_open * (1.0 + threshold / 100.0)
            hit_i = next(
                (
                    index
                    for index, row in enumerate(bars)
                    if _number(row.get("low")) <= trigger_price
                ),
                None,
            )
            if hit_i is None:
                threshold_observations.append(
                    {"threshold_pct": threshold, "crossed": False}
                )
                continue
            post = bars[hit_i + 1 :]
            post_high = max(
                [_number(row.get("high")) for row in post] or [last]
            )
            post_low = min(
                [_number(row.get("low")) for row in post]
                or [_number(bars[hit_i].get("low"))]
            )
            threshold_observations.append(
                {
                    "threshold_pct": threshold,
                    "crossed": True,
                    "cross_ts": bars[hit_i].get("ts"),
                    "last_net_050_pct": round(
                        (last / trigger_price - 1.0) * 100.0
                        - CONSERVATIVE_COST_PCT,
                        4,
                    ),
                    "observed_mfe_net_050_pct": round(
                        (post_high / trigger_price - 1.0) * 100.0
                        - CONSERVATIVE_COST_PCT,
                        4,
                    ),
                    "observed_mae_pct": round(
                        (
                            min(_number(bars[hit_i].get("low")), post_low)
                            / trigger_price
                            - 1.0
                        )
                        * 100.0,
                        4,
                    ),
                }
            )
        item["threshold_observations"] = threshold_observations
        output.append(item)
    return {
        "state_updated_at": state.get("updated_at"),
        "signal_updated_at": signal.get("updated_at"),
        "rows": output,
    }


def build_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 고저폭 TOP30 — 시가 대비 -12%/-17% 급락 후 반등·손실 분석",
        "",
        f"- TOP30 기준일: {result['scope']['for_date']} (원천일 {result['scope']['source_date']})",
        f"- 비용: 공식 왕복 {OFFICIAL_COST_PCT:.2f}%, 보수적 왕복 {CONSERVATIVE_COST_PCT:.2f}%",
        "- 일봉: 정확 문턱가격 체결 뒤 당일 종가 청산 가정",
        "- 3분봉: 12시 이전 최초 문턱 도달, 1·2·3시간 및 15:10 근사 청산",
        "- 전략4 포착: W·MA3/20·목선 가격구조까지만 재생한 상한선이며 실시간 수급·호가·시장·뉴스 관문은 미포함",
        "",
        "## 일봉 전체 이력",
        "",
        "| 시가 낙폭 | 사건수 | 종가 비용후 승률 | 종가 평균 | -2% 손절 도달률 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for key in ("12", "17"):
        row = result["daily_summary"][key]
        close = row["close_net_050"]
        lines.append(
            f"| -{key}% | {row['events']} | {close.get('win_rate_pct', 0):.2f}% | "
            f"{close.get('mean_pct', 0):+.3f}% | {row['hard_stop_hit_rate_pct'] or 0:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 연속 3분봉 이력",
            "",
            "| 시가 낙폭 | 사건수 | 1시간 승률/평균 | 2시간 승률/평균 | 3시간 승률/평균 | 15:10 승률/평균 | S04 가격구조/자동허용 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for key in ("12", "17"):
        row = result["intraday_summary"][key]
        cells = []
        for label in ("exit_1h_net_050", "exit_2h_net_050", "exit_3h_net_050", "exit_1510_net_050"):
            stat = row[label]
            cells.append(
                f"{stat.get('win_rate_pct', 0):.1f}%/{stat.get('mean_pct', 0):+.2f}%"
            )
        lines.append(
            f"| -{key}% | {row['events_before_noon']} | {' | '.join(cells)} | "
            f"{row['price_pattern_found']}/{row['price_pattern_auto_allowed']} |"
        )
    lines.extend(
        [
            "",
            "## 한계",
            "",
            "- 현재 TOP30을 과거에 소급한 조건부 표본이라 생존자 편향이 있습니다.",
            "- 과거 시가총액 1,000억원 필터는 자료가 없어 재현하지 못했고, 전일 주가·거래대금 범위만 적용했습니다.",
            "- 실제 공통 매도엔진의 초단위 수급·호가 판정은 과거 자료가 없어 고정시간/손절 위험으로 대체했습니다.",
            "- 오늘 세 종목은 장중 미완료 자료이므로 1일 결과가 아닙니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    top30, codes, names = load_top30()
    daily = load_daily(codes)
    daily_events, daily_summary = daily_event_rows(daily)
    intraday, intraday_quality = load_complete_intraday(codes)
    intraday_events, intraday_summary, price_patterns = intraday_event_rows(
        intraday, daily
    )
    result = {
        "schema": "strategy04_top30_open_drop_study_v1",
        "scope": {
            "for_date": top30.get("for_date"),
            "source_date": top30.get("source_date"),
            "candidate_count": len(codes),
            "codes": codes,
            "daily_date_min": str(int(daily["date"].min())),
            "daily_date_max": str(int(daily["date"].max())),
            "cost_official_pct": OFFICIAL_COST_PCT,
            "cost_conservative_pct": CONSERVATIVE_COST_PCT,
        },
        "data_quality": intraday_quality,
        "daily_summary": daily_summary,
        "intraday_summary": intraday_summary,
        "named_daily_history": named_daily_history(daily_events, names),
        "current_named_partial": current_named(names),
        "price_pattern_summary": {
            "patterns_found": int(len(price_patterns)),
            "auto_drop_allowed": int(price_patterns.get("auto_drop_allowed", pd.Series(dtype=bool)).sum())
            if not price_patterns.empty
            else 0,
            "exit_1510_net_050": _summary(
                price_patterns.get("exit_1510_net_050_pct", pd.Series(dtype=float))
            ),
            "mfe_to_1510_net_050": _summary(
                price_patterns.get("mfe_to_1510_net_050_pct", pd.Series(dtype=float))
            ),
        },
    }
    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    OUT_MD.write_text(build_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

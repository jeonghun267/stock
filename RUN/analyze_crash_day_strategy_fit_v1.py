# -*- coding: utf-8 -*-
"""8/18 및 8/21 급락장 관측경로와 S01/S02/S03 신호 적합도를 비교한다.

거래 성과 재생이 아니라 high_range 장중 관측값과 각 전략의 신호 CSV를
종목코드로 대조하는 읽기 전용 분석이다.
"""
from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pandas as pd


ROOT = Path(r"C:\stock_bot")
OUT = ROOT / "보고서" / "crash_day_strategy_fit_20260821.json"
DATES = ("20260818", "20260821")
FAIR_CUTOFF = time(11, 0, 0)


def _code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)


def _signals(day: str) -> dict[str, dict[str, dict]]:
    paths = {
        "S01": ROOT / "data" / "shadow" / f"strategy_01_above_open_rebreak_shadow_{day}.csv",
        "S02": ROOT / "data" / "strategy_02_signal_v1" / f"strategy_02_signals_{day}.csv",
        "S03": ROOT / "data" / "strategy_03_골짜기_급반등_v1" / f"strategy_03_signals_{day}.csv",
    }
    result: dict[str, dict[str, dict]] = {}
    for strategy, path in paths.items():
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path, dtype={"code": str}, low_memory=False)
        if frame.empty or "code" not in frame:
            continue
        frame["code"] = _code(frame["code"])
        frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
        frame = frame.sort_values("ts")
        for code, group in frame.groupby("code", sort=False):
            row = group.iloc[0]
            result.setdefault(code, {})[strategy] = {
                "ts": row["ts"].isoformat() if pd.notna(row["ts"]) else "",
                "reason": str(row.get("reason") or ""),
                "entry_stage": str(row.get("entry_stage") or row.get("entry_lane") or ""),
            }
    return result


def _scope(day: str, *, cutoff: time | None) -> dict:
    path = ROOT / "data" / f"high_range_shadow_{day}.csv"
    frame = pd.read_csv(path, dtype={"code": str}, low_memory=False)
    frame["code"] = _code(frame["code"])
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    frame = frame.dropna(subset=["ts", "current", "prev_close"]).sort_values(["code", "ts"])
    if cutoff is not None:
        frame = frame[frame["ts"].dt.time <= cutoff]
    signals = _signals(day)
    rows: list[dict] = []
    for code, group in frame.groupby("code", sort=False):
        group = group.sort_values("ts").copy()
        prev_close = float(group["prev_close"].dropna().iloc[0])
        first_price = float(group["first_price"].dropna().iloc[0])
        group["running_low"] = group["current"].cummin()
        group["running_low_ts"] = group.loc[
            group["current"].eq(group["running_low"]), "ts"
        ].ffill()
        group["path_rebound_pct"] = (group["current"] / group["running_low"] - 1.0) * 100.0
        group["change_calc_pct"] = (group["current"] / prev_close - 1.0) * 100.0
        min_idx = group["current"].idxmin()
        rebound_idx = group["path_rebound_pct"].idxmax()
        after_daily_min = group[group["ts"] >= group.loc[min_idx, "ts"]]
        post_min_high_idx = after_daily_min["current"].idxmax()
        post_daily_min_rebound_pct = (
            float(group.loc[post_min_high_idx, "current"])
            / float(group.loc[min_idx, "current"]) - 1.0
        ) * 100.0
        trigger_rows = group[group["path_rebound_pct"] >= 1.0]
        trigger = trigger_rows.iloc[0] if not trigger_rows.empty else None
        future_upside = None
        if trigger is not None:
            later = group[group["ts"] >= trigger["ts"]]
            future_upside = (float(later["current"].max()) / float(trigger["current"]) - 1.0) * 100.0
        strategy_hits = signals.get(code, {})
        names = group["name"].dropna()
        rows.append({
            "code": code,
            "name": str(names.iloc[-1]) if not names.empty else code,
            "first_ts": group["ts"].iloc[0].isoformat(),
            "last_ts": group["ts"].iloc[-1].isoformat(),
            "first_price_vs_prev_pct": round((first_price / prev_close - 1.0) * 100.0, 4),
            "min_change_pct": round(float(group.loc[min_idx, "change_calc_pct"]), 4),
            "min_ts": group.loc[min_idx, "ts"].isoformat(),
            "max_change_pct": round(float(group["change_calc_pct"].max()), 4),
            "last_change_pct": round(float(group["change_calc_pct"].iloc[-1]), 4),
            "max_rebound_pct": round(float(group.loc[rebound_idx, "path_rebound_pct"]), 4),
            "max_rebound_ts": group.loc[rebound_idx, "ts"].isoformat(),
            "post_daily_min_rebound_pct": round(post_daily_min_rebound_pct, 4),
            "post_daily_min_high_ts": group.loc[post_min_high_idx, "ts"].isoformat(),
            "trigger_ts": trigger["ts"].isoformat() if trigger is not None else "",
            "trigger_change_pct": round(float(trigger["change_calc_pct"]), 4) if trigger is not None else None,
            "trigger_vs_first_pct": round((float(trigger["current"]) / first_price - 1.0) * 100.0, 4) if trigger is not None else None,
            "trigger_buy_ratio_pct": round(float(trigger.get("buy_ratio_pct")), 4) if trigger is not None and pd.notna(trigger.get("buy_ratio_pct")) else None,
            "trigger_che_str": round(float(trigger.get("che_str")), 4) if trigger is not None and pd.notna(trigger.get("che_str")) else None,
            "trigger_money_speed_ratio": round(float(trigger.get("money_speed_vs_daily_avg")), 4) if trigger is not None and pd.notna(trigger.get("money_speed_vs_daily_avg")) else None,
            "trigger_turnover_pct": round(float(trigger.get("listed_turnover_pct")), 4) if trigger is not None and pd.notna(trigger.get("listed_turnover_pct")) else None,
            "future_upside_from_trigger_pct": round(float(future_upside), 4) if future_upside is not None else None,
            "leader_positive5": bool(group["change_calc_pct"].max() >= 5.0),
            "crash_reversal5": bool(
                group.loc[min_idx, "change_calc_pct"] <= -5.0
                and post_daily_min_rebound_pct >= 5.0
            ),
            "above_first_at_trigger": bool(trigger is not None and float(trigger["current"]) >= first_price),
            "strategies": sorted(strategy_hits),
            "strategy_details": strategy_hits,
        })
    table = pd.DataFrame(rows)
    big = table[table["leader_positive5"] | table["crash_reversal5"]].copy()
    triggerable = table[table["trigger_ts"].ne("")].copy()
    strong_after_trigger = triggerable[
        triggerable["future_upside_from_trigger_pct"].fillna(-999) >= 3.0
    ]
    def _median(column: str, data: pd.DataFrame) -> float | None:
        values = pd.to_numeric(data[column], errors="coerce").dropna()
        return round(float(values.median()), 4) if not values.empty else None
    condition_comparison = {}
    for label, data in (("strong_after_trigger", strong_after_trigger),
                        ("other_triggered", triggerable.drop(strong_after_trigger.index))):
        condition_comparison[label] = {
            "n": int(len(data)),
            "above_first_share_pct": round(float(data["above_first_at_trigger"].mean() * 100), 2) if len(data) else None,
            "buy_ratio_median": _median("trigger_buy_ratio_pct", data),
            "che_median": _median("trigger_che_str", data),
            "money_speed_ratio_median": _median("trigger_money_speed_ratio", data),
            "turnover_median": _median("trigger_turnover_pct", data),
            "trigger_change_median": _median("trigger_change_pct", data),
        }
    return {
        "day": day,
        "cutoff": cutoff.strftime("%H:%M:%S") if cutoff else "FULL_CAPTURE",
        "source": str(path),
        "source_last_ts": frame["ts"].max().isoformat() if not frame.empty else "",
        "universe_codes": int(table["code"].nunique()),
        "leader_positive5_count": int(table["leader_positive5"].sum()),
        "crash_reversal5_count": int(table["crash_reversal5"].sum()),
        "condition_comparison": condition_comparison,
        "big_movers": big.sort_values(
            ["leader_positive5", "max_change_pct", "max_rebound_pct"],
            ascending=False,
        ).head(25).to_dict(orient="records"),
        "all_rows": table.to_dict(orient="records"),
    }


def _market() -> dict:
    path = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
    frame = pd.read_csv(path)
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    result = {}
    for day in DATES:
        stamp = pd.to_datetime(day).date()
        rows = frame[frame["ts"].dt.date.eq(stamp)].sort_values("ts")
        rows = rows[rows["ts"].dt.time <= FAIR_CUTOFF]
        result[day] = {
            "first": float(rows["u201_chg"].iloc[0]) if not rows.empty else None,
            "min_to_cutoff": float(rows["u201_chg"].min()) if not rows.empty else None,
            "last_to_cutoff": float(rows["u201_chg"].iloc[-1]) if not rows.empty else None,
            "last_ts": rows["ts"].iloc[-1].isoformat() if not rows.empty else "",
        }
    return {"source": str(path), "days": result}


def main() -> int:
    payload = {
        "schema": "crash_day_strategy_fit_v1",
        "provenance": "UNVERIFIED_PRICE_PATH_NOT_TRADE_RESULT",
        "definitions": {
            "leader_positive5": "관측구간 중 전일종가 대비 +5% 이상",
            "crash_reversal5": "관측구간 중 전일종가 대비 -5% 이하 저점 후 +5% 이상 반등",
            "trigger": "관측 누적저점 대비 최초 +1% 회복",
            "strong_after_trigger": "trigger 이후 추가 +3% 이상 관측",
        },
        "market": _market(),
        "fair_1100": {day: _scope(day, cutoff=FAIR_CUTOFF) for day in DATES},
        "full_0818": _scope("20260818", cutoff=None),
        "limitations": [
            "high_range_shadow에 들어온 종목만 포함하며 전 시장 전수 자료가 아니다.",
            "8/21은 11:00까지의 부분 장중 자료다.",
            "가격 경로 관측이며 매매 체결 또는 생산 진입-청산 재생 결과가 아니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)
    for day, scope in payload["fair_1100"].items():
        print(day, scope["universe_codes"], scope["leader_positive5_count"], scope["crash_reversal5_count"])
        print(scope["condition_comparison"])
        for row in scope["big_movers"][:10]:
            print(row["code"], row["name"], row["min_change_pct"], row["max_change_pct"], row["max_rebound_pct"], row["strategies"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

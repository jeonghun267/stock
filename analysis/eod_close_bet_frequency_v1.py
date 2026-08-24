"""영상 종가베팅 조건의 로컬 데이터 선별 빈도 검사.

이 파일은 생산 주문 경로를 사용하지 않는 가설 분석 전용이다.
완전 조건에 필요한 MA400/과거 유동주식수/15시 스냅샷이 없으면
그 사실을 보고서에 남기고, 계산 가능한 대체 관문만 집계한다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(r"C:\stock_bot")
BARS_PATH = BASE / "data" / "eod_daily_bars.csv"
SHARES_PATH = BASE / "DATA" / "shares_outstanding.csv"
REPORT_PATH = Path(tempfile.gettempdir()) / "eod_close_bet_frequency_20260811.json"
ROUND_TRIP_COST_PCT = 0.38


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lrl_endpoint_weights(window: int) -> np.ndarray:
    """최소제곱 회귀선의 마지막 x값에 대응하는 선형 가중치."""
    x = np.arange(window, dtype=float)
    centered = x - x.mean()
    return (
        np.ones(window) / window
        + centered * (x[-1] - x.mean()) / np.dot(centered, centered)
    )


def _daily_summary(eligible: pd.DataFrame, flag: str) -> tuple[dict, pd.Series]:
    daily = eligible.groupby("date")[flag].sum().astype(int)
    return {
        "from": int(daily.index.min()),
        "to": int(daily.index.max()),
        "days": int(len(daily)),
        "total": int(daily.sum()),
        "daily_mean": round(float(daily.mean()), 3),
        "daily_median": float(daily.median()),
        "daily_min": int(daily.min()),
        "daily_max": int(daily.max()),
        "nonzero_days": int((daily > 0).sum()),
        "zero_days": int((daily == 0).sum()),
    }, daily


def main() -> None:
    bars = pd.read_csv(BARS_PATH, dtype={"code": str})
    bars = bars.sort_values(["code", "date"]).reset_index(drop=True)
    shares = pd.read_csv(SHARES_PATH, dtype={"code": str})[["code", "shares"]]
    shares = shares.drop_duplicates("code", keep="last")

    quality = {
        "bars_rows": int(len(bars)),
        "bars_dates": int(bars["date"].nunique()),
        "bars_first_date": int(bars["date"].min()),
        "bars_last_date": int(bars["date"].max()),
        "bars_codes": int(bars["code"].nunique()),
        "duplicate_date_code": int(bars.duplicated(["date", "code"]).sum()),
        "shares_codes": int(shares["code"].nunique()),
    }

    w20 = _lrl_endpoint_weights(20)
    w40 = _lrl_endpoint_weights(40)
    grouped = bars.groupby("code", sort=False)
    bars["lrl20"] = grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).apply(
            lambda window: float(np.dot(window, w20)), raw=True
        )
    )
    bars["lrl40"] = grouped["close"].transform(
        lambda values: values.rolling(40, min_periods=40).apply(
            lambda window: float(np.dot(window, w40)), raw=True
        )
    )
    bars["ma200"] = grouped["close"].transform(
        lambda values: values.rolling(200, min_periods=200).mean()
    )
    bars["prev_close"] = grouped["close"].shift(1)
    bars["prev_ma200"] = grouped["ma200"].shift(1)
    bars["next_date"] = grouped["date"].shift(-1)
    bars["next_open"] = grouped["open"].shift(-1)
    bars["next_high"] = grouped["high"].shift(-1)
    bars["next_low"] = grouped["low"].shift(-1)
    bars["next_close"] = grouped["close"].shift(-1)
    bars = bars.merge(shares, on="code", how="left", validate="many_to_one")

    bars["red_zone"] = bars["lrl20"] > bars["lrl40"]
    bars["above_ma200"] = bars["close"] > bars["ma200"]
    bars["fresh_cross_ma200"] = bars["above_ma200"] & (
        bars["prev_close"] <= bars["prev_ma200"]
    )
    bars["listed_turnover"] = bars["volume"] / bars["shares"]
    bars["listed_turnover_ge_1"] = bars["listed_turnover"] >= 1.0
    bars["proxy_above"] = (
        bars["red_zone"] & bars["above_ma200"] & bars["listed_turnover_ge_1"]
    )
    bars["proxy_fresh_cross"] = (
        bars["red_zone"]
        & bars["fresh_cross_ma200"]
        & bars["listed_turnover_ge_1"]
    )

    # 독립 공식 대조: 가중치 계산과 np.polyfit 마지막점이 일치해야 한다.
    max_lrl_error = 0.0
    for _, code_rows in bars.groupby("code", sort=False):
        if len(code_rows) < 40:
            continue
        sample = code_rows.iloc[:40]["close"].to_numpy(dtype=float)
        x = np.arange(40, dtype=float)
        expected = float(np.polyval(np.polyfit(x, sample, 1), x[-1]))
        actual = float(np.dot(sample, w40))
        max_lrl_error = max(max_lrl_error, abs(expected - actual))
        if max_lrl_error > 1e-6:
            raise AssertionError(f"LRL formula mismatch: {max_lrl_error}")

    eligible = bars[bars["ma200"].notna()].copy()
    summary_above, daily_above = _daily_summary(eligible, "proxy_above")
    summary_cross, daily_cross = _daily_summary(eligible, "proxy_fresh_cross")

    candidate_columns = [
        "date", "code", "name", "close", "volume", "shares", "listed_turnover",
        "next_date", "next_open", "next_high", "next_low", "next_close",
    ]
    candidates = eligible.loc[eligible["proxy_above"], candidate_columns]
    candidates = candidates.sort_values(["date", "code"]).reset_index(drop=True)
    for label in ("open", "high", "low", "close"):
        candidates[f"next_{label}_ret_pct"] = (
            candidates[f"next_{label}"] / candidates["close"] - 1.0
        ) * 100.0
    candidates["next_open_net_pct"] = (
        candidates["next_open_ret_pct"] - ROUND_TRIP_COST_PCT
    )
    candidates["next_close_net_pct"] = (
        candidates["next_close_ret_pct"] - ROUND_TRIP_COST_PCT
    )

    def outcome_summary(column: str) -> dict:
        values = candidates[column].dropna()
        return {
            "observations": int(len(values)),
            "positive_count": int((values > 0).sum()),
            "positive_rate_pct": round(float((values > 0).mean() * 100), 2),
            "mean_pct": round(float(values.mean()), 3),
            "median_pct": round(float(values.median()), 3),
            "min_pct": round(float(values.min()), 3),
            "max_pct": round(float(values.max()), 3),
        }

    next_day_outcomes = {
        "raw_open": outcome_summary("next_open_ret_pct"),
        "raw_high": outcome_summary("next_high_ret_pct"),
        "raw_low": outcome_summary("next_low_ret_pct"),
        "raw_close": outcome_summary("next_close_ret_pct"),
        "net_open_after_0_38pct_cost": outcome_summary("next_open_net_pct"),
        "net_close_after_0_38pct_cost": outcome_summary("next_close_net_pct"),
    }

    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BASE, text=True
        ).strip()
    except Exception:
        git_head = None

    report = {
        "provenance": "[HYPOTHETICAL]",
        "question": "영상 종가베팅 조건으로 하루 몇 종목이 선별되는가",
        "stock_universe": "KOSDAQ rows in local eod_daily_bars.csv",
        "source_paths": [str(BARS_PATH), str(SHARES_PATH)],
        "source_sha256": {
            str(BARS_PATH): _sha256(BARS_PATH),
            str(SHARES_PATH): _sha256(SHARES_PATH),
        },
        "source_as_of": int(bars["date"].max()),
        "git_head": git_head,
        "production_entrypoint": None,
        "production_code_changed": "NOT_CHANGED",
        "analysis_entrypoint": str(Path(__file__).resolve()),
        "exact_command": f'python "{Path(__file__).resolve()}"',
        "implemented_proxy_conditions": [
            "LRL20 endpoint > LRL40 endpoint",
            "close > MA200",
            "daily volume >= current total listed shares",
        ],
        "missing_exact_conditions": [
            "MA400: only 252 daily bars available",
            "historical free-float shares: only current total listed shares available",
            "15:00-15:20 decision-boundary state: only end-of-day bars available",
            "exact HTS LRL implementation not independently documented",
        ],
        "data_quality": {
            **quality,
            "eligible_rows_with_ma200": int(len(eligible)),
            "shares_join_coverage_pct": round(
                float(eligible["shares"].notna().mean() * 100), 4
            ),
            "max_lrl_formula_crosscheck_error": max_lrl_error,
        },
        "proxy_above_ma200_summary": summary_above,
        "proxy_fresh_cross_ma200_summary": summary_cross,
        "round_trip_cost_pct_assumption": ROUND_TRIP_COST_PCT,
        "next_day_outcome_summary": next_day_outcomes,
        "proxy_candidate_rows": candidates.to_dict(orient="records"),
        "daily_counts_all_dates": [
            {
                "date": int(date),
                "above_ma200_count": int(count),
                "fresh_cross_ma200_count": int(daily_cross.loc[date]),
            }
            for date, count in daily_above.items()
        ],
        "full_exact_result": "[UNVERIFIED]",
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    raw_result = {
        "provenance": report["provenance"],
        "report": str(REPORT_PATH),
        "proxy_above_ma200_summary": summary_above,
        "proxy_fresh_cross_ma200_summary": summary_cross,
        "candidate_rows": int(len(candidates)),
        "unique_codes": int(candidates["code"].nunique()),
        "next_day_outcome_summary": next_day_outcomes,
        "full_exact_result": report["full_exact_result"],
    }
    print(json.dumps(raw_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

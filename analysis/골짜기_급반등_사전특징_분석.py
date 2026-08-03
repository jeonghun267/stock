# -*- coding: utf-8 -*-
"""급반등 7종목과 동일 -4% 무장 대조군의 사전 특징 비교.

신호일 이전 데이터만 사용한다. 실제 기관·외인 순매수와 일봉 기반
거래대금·변동성·종가위치·다일 자금성격을 비교하며 실제 주문은 없다.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Optional


ROOT = Path(r"C:\stock_bot")
EVENT_PATH = ROOT / "analysis" / "골짜기_급반등_진입비교.csv"
QUICK_PATH = ROOT / "analysis" / "골짜기_급반등_FAST_누락진단.log"
EOD_PATH = ROOT / "data" / "eod_daily_bars.csv"
INVESTOR_PATH = ROOT / "data" / "investor_daily.csv"
OUT_DETAIL = ROOT / "analysis" / "골짜기_급반등_사전특징_77종목.csv"
OUT_COMPARE = ROOT / "analysis" / "골짜기_급반등_사전특징_비교.csv"
OUT_RULES = ROOT / "analysis" / "골짜기_급반등_사전특징_조건후보.csv"
OUT_JSON = ROOT / "analysis" / "골짜기_급반등_사전특징_요약.json"


FEATURES = {
    "previous_value_eok": "전일 거래대금(억원)",
    "market_cap_eok": "전일 기준 시가총액(억원)",
    "d1_return_pct": "전일 수익률(%)",
    "d1_gap_pct": "전일 시가갭(%)",
    "d1_range_pct": "전일 고저폭/전전일종가(%)",
    "d1_close_position": "전일 종가 위치(0=저가,1=고가)",
    "d1_body_pct": "전일 시가대비 종가(%)",
    "d1_upper_wick_share": "전일 윗꼬리/고저폭",
    "d1_value_vs_prior5": "전일 거래대금/직전5일 중앙값",
    "return_3d_pct": "3일 누적수익률(%)",
    "return_5d_pct": "5일 누적수익률(%)",
    "median_range_5d_pct": "최근5일 고저폭 중앙값(%)",
    "up_days_5d": "최근5일 상승일 수",
    "signed_value_balance_5d": "최근5일 방향성 거래대금 균형",
    "up_value_share_5d": "최근5일 상승일 거래대금 비중",
    "inst_d1_volume_pct": "D-1 기관 순매수/거래량(%)",
    "foreign_d1_volume_pct": "D-1 외인 순매수/거래량(%)",
    "supply_d1_volume_pct": "D-1 기관+외인 순매수/거래량(%)",
    "supply_3d_volume_pct": "3일 기관+외인 누적/거래량(%)",
    "supply_5d_volume_pct": "5일 기관+외인 누적/거래량(%)",
    "supply_positive_days_5d": "최근5일 기관+외인 순매수일 수",
}


def number(value: object, default: Optional[float] = None) -> Optional[float]:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def load_events() -> list[dict]:
    quick_doc = json.loads(QUICK_PATH.read_text(encoding="utf-8"))
    quick_keys = {(row["day"], row["code"]) for row in quick_doc["rows"]}
    events: list[dict] = []
    with EVENT_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["algorithm"] != "CURRENT_VALLEY":
                continue
            day = row["day"]
            code = row["code"].zfill(6)
            previous_close = float(row["previous_close"])
            morning_low = float(row["morning_low"])
            events.append(
                {
                    "day": day,
                    "code": code,
                    "name": row["name"],
                    "quick_v": (day, code) in quick_keys,
                    "previous_close": previous_close,
                    "previous_value_eok": float(row["previous_value_eok"]),
                    "market_cap_eok": float(row["market_cap_eok"]),
                    "armed_at": row["armed_at"],
                    "morning_low": morning_low,
                    "morning_low_at": row["morning_low_at"],
                    "morning_low_drop_pct": round(
                        (morning_low / previous_close - 1.0) * 100.0, 4
                    ),
                    "arm_to_low_sec": round(
                        (
                            datetime.fromisoformat(row["morning_low_at"])
                            - datetime.fromisoformat(row["armed_at"])
                        ).total_seconds(),
                        3,
                    ),
                }
            )
    return events


def load_eod(codes: set[str], max_day: str) -> dict[str, list[dict]]:
    by_code: dict[str, list[dict]] = defaultdict(list)
    with EOD_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code", "")).zfill(6)
            day = str(row.get("date", ""))
            if code not in codes or not day or day >= max_day:
                continue
            try:
                parsed = {
                    "date": day,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "value": float(row["value"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if min(
                parsed["open"],
                parsed["high"],
                parsed["low"],
                parsed["close"],
            ) <= 0:
                continue
            by_code[code].append(parsed)
    for rows in by_code.values():
        rows.sort(key=lambda row: row["date"])
    return dict(by_code)


def load_investor() -> dict[tuple[str, str], tuple[float, float]]:
    data: dict[tuple[str, str], tuple[float, float]] = {}
    with INVESTOR_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            day = str(row.get("date", ""))
            code = str(row.get("code", "")).zfill(6)
            inst = number(row.get("inst_net"))
            foreign = number(row.get("foreign_net"))
            if day and code and inst is not None and foreign is not None:
                data[(code, day)] = (inst, foreign)
    return data


def pct(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator * 100.0 if denominator else None


def signed_day_return(rows: list[dict], idx: int) -> Optional[float]:
    if idx <= 0:
        return None
    return (rows[idx]["close"] / rows[idx - 1]["close"] - 1.0) * 100.0


def make_features(
    event: dict,
    eod_rows: list[dict],
    investor: dict[tuple[str, str], tuple[float, float]],
) -> dict:
    history = [row for row in eod_rows if row["date"] < event["day"]]
    result = dict(event)
    result["eod_history_days"] = len(history)
    if len(history) < 2:
        return result

    d1 = history[-1]
    d2 = history[-2]
    d1_range = d1["high"] - d1["low"]
    result.update(
        {
            "d1_date": d1["date"],
            "d1_return_pct": pct(d1["close"] - d2["close"], d2["close"]),
            "d1_gap_pct": pct(d1["open"] - d2["close"], d2["close"]),
            "d1_range_pct": pct(d1_range, d2["close"]),
            "d1_close_position": (
                (d1["close"] - d1["low"]) / d1_range if d1_range > 0 else 0.5
            ),
            "d1_body_pct": pct(d1["close"] - d1["open"], d1["open"]),
            "d1_upper_wick_share": (
                (d1["high"] - max(d1["open"], d1["close"])) / d1_range
                if d1_range > 0
                else 0.0
            ),
        }
    )

    prior_values = [row["value"] for row in history[-6:-1] if row["value"] > 0]
    result["d1_value_vs_prior5"] = (
        d1["value"] / median(prior_values) if prior_values else None
    )
    result["return_3d_pct"] = (
        pct(d1["close"] - history[-4]["close"], history[-4]["close"])
        if len(history) >= 4
        else None
    )
    result["return_5d_pct"] = (
        pct(d1["close"] - history[-6]["close"], history[-6]["close"])
        if len(history) >= 6
        else None
    )

    last5 = history[-5:]
    last5_start = len(history) - len(last5)
    daily_returns: list[Optional[float]] = [
        signed_day_return(history, idx)
        for idx in range(last5_start, len(history))
    ]
    ranges = []
    signed_value = 0.0
    up_value = 0.0
    total_value = 0.0
    up_days = 0
    for row, daily_return in zip(last5, daily_returns):
        prior_close = (
            history[history.index(row) - 1]["close"]
            if history.index(row) > 0
            else row["open"]
        )
        ranges.append((row["high"] - row["low"]) / prior_close * 100.0)
        total_value += row["value"]
        if daily_return is not None and daily_return > 0:
            signed_value += row["value"]
            up_value += row["value"]
            up_days += 1
        elif daily_return is not None and daily_return < 0:
            signed_value -= row["value"]
    result.update(
        {
            "median_range_5d_pct": median(ranges) if ranges else None,
            "up_days_5d": up_days,
            "signed_value_balance_5d": (
                signed_value / total_value if total_value > 0 else None
            ),
            "up_value_share_5d": (
                up_value / total_value if total_value > 0 else None
            ),
        }
    )

    supply_rows = []
    for row in last5:
        values = investor.get((event["code"], row["date"]))
        if values is not None:
            supply_rows.append((row, values[0], values[1]))
    result["investor_days_5d"] = len(supply_rows)
    d1_supply = investor.get((event["code"], d1["date"]))
    if d1_supply is not None:
        inst, foreign = d1_supply
        result["inst_d1_volume_pct"] = pct(inst, d1["volume"])
        result["foreign_d1_volume_pct"] = pct(foreign, d1["volume"])
        result["supply_d1_volume_pct"] = pct(inst + foreign, d1["volume"])
    for days in (3, 5):
        selected = supply_rows[-days:]
        if len(selected) == days:
            net = sum(inst + foreign for _, inst, foreign in selected)
            volume = sum(row["volume"] for row, _, _ in selected)
            result[f"supply_{days}d_volume_pct"] = pct(net, volume)
    if supply_rows:
        result["supply_positive_days_5d"] = sum(
            inst + foreign > 0 for _, inst, foreign in supply_rows
        )
    return result


def common_language_effect(
    quick_rows: list[dict],
    control_rows: list[dict],
    feature: str,
) -> tuple[Optional[float], int]:
    wins = 0.0
    pairs = 0
    for quick in quick_rows:
        q_value = quick.get(feature)
        if q_value is None:
            continue
        for control in control_rows:
            if control["day"] != quick["day"]:
                continue
            c_value = control.get(feature)
            if c_value is None:
                continue
            pairs += 1
            wins += 1.0 if q_value > c_value else 0.5 if q_value == c_value else 0.0
    return ((wins / pairs * 2.0 - 1.0) if pairs else None, pairs)


def average_rank(values: list[tuple[int, float]]) -> dict[int, float]:
    ordered = sorted(values, key=lambda item: item[1])
    result: dict[int, float] = {}
    idx = 0
    while idx < len(ordered):
        end = idx + 1
        while end < len(ordered) and ordered[end][1] == ordered[idx][1]:
            end += 1
        rank = ((idx + 1) + end) / 2.0
        percentile = (rank - 0.5) / len(ordered)
        for pos in range(idx, end):
            result[ordered[pos][0]] = percentile
        idx = end
    return result


def add_within_day_percentiles(rows: list[dict]) -> None:
    for feature in FEATURES:
        for day in sorted({row["day"] for row in rows}):
            values = [
                (idx, float(row[feature]))
                for idx, row in enumerate(rows)
                if row["day"] == day and row.get(feature) is not None
            ]
            for idx, percentile in average_rank(values).items():
                rows[idx][f"{feature}__day_pct"] = percentile


def feature_comparison(rows: list[dict]) -> list[dict]:
    quick = [row for row in rows if row["quick_v"]]
    control = [row for row in rows if not row["quick_v"]]
    output = []
    for feature, label in FEATURES.items():
        quick_values = [float(row[feature]) for row in quick if row.get(feature) is not None]
        control_values = [
            float(row[feature]) for row in control if row.get(feature) is not None
        ]
        effect, pairs = common_language_effect(quick, control, feature)
        q_day_pct = [
            float(row[f"{feature}__day_pct"])
            for row in quick
            if row.get(f"{feature}__day_pct") is not None
        ]
        c_day_pct = [
            float(row[f"{feature}__day_pct"])
            for row in control
            if row.get(f"{feature}__day_pct") is not None
        ]
        output.append(
            {
                "feature": feature,
                "label": label,
                "quick_n": len(quick_values),
                "control_n": len(control_values),
                "quick_median": median(quick_values) if quick_values else None,
                "control_median": median(control_values) if control_values else None,
                "quick_mean": mean(quick_values) if quick_values else None,
                "control_mean": mean(control_values) if control_values else None,
                "same_day_pair_effect": effect,
                "same_day_pairs": pairs,
                "quick_day_percentile_median": median(q_day_pct) if q_day_pct else None,
                "control_day_percentile_median": median(c_day_pct) if c_day_pct else None,
            }
        )
    return sorted(
        output,
        key=lambda row: abs(float(row["same_day_pair_effect"] or 0.0)),
        reverse=True,
    )


def screen_rules(rows: list[dict]) -> list[dict]:
    output = []
    days = sorted({row["day"] for row in rows})
    base_by_day = {
        day: sum(row["quick_v"] for row in rows if row["day"] == day)
        / sum(row["day"] == day for row in rows)
        for day in days
    }
    for feature, label in FEATURES.items():
        pct_field = f"{feature}__day_pct"
        for direction, threshold in (("TOP", 0.75), ("TOP", 0.5), ("BOTTOM", 0.25), ("BOTTOM", 0.5)):
            covered = [row for row in rows if row.get(pct_field) is not None]
            selected = [
                row
                for row in covered
                if (
                    float(row[pct_field]) >= threshold
                    if direction == "TOP"
                    else float(row[pct_field]) <= threshold
                )
            ]
            if len(selected) < 8:
                continue
            quick_hits = sum(row["quick_v"] for row in selected)
            quick_total = sum(row["quick_v"] for row in covered)
            day_lifts = []
            selected_days_with_quick = 0
            for day in days:
                day_selected = [row for row in selected if row["day"] == day]
                if not day_selected:
                    day_lifts.append(0.0)
                    continue
                rate = sum(row["quick_v"] for row in day_selected) / len(day_selected)
                day_lifts.append(rate / base_by_day[day] if base_by_day[day] else 0.0)
                if any(row["quick_v"] for row in day_selected):
                    selected_days_with_quick += 1
            output.append(
                {
                    "feature": feature,
                    "label": label,
                    "direction": direction,
                    "day_percentile_threshold": threshold,
                    "selected": len(selected),
                    "quick_hits": quick_hits,
                    "quick_total_covered": quick_total,
                    "precision_pct": quick_hits / len(selected) * 100.0,
                    "recall_pct": quick_hits / quick_total * 100.0 if quick_total else 0.0,
                    "day1_lift": day_lifts[0],
                    "day2_lift": day_lifts[1],
                    "min_day_lift": min(day_lifts),
                    "quick_days": selected_days_with_quick,
                }
            )
    stable = [
        row
        for row in output
        if row["quick_hits"] >= 2
        and row["quick_days"] == len(days)
        and row["min_day_lift"] > 1.0
    ]
    return sorted(
        stable,
        key=lambda row: (
            -float(row["min_day_lift"]),
            -float(row["recall_pct"]),
            int(row["selected"]),
        ),
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run() -> dict:
    events = load_events()
    codes = {event["code"] for event in events}
    eod = load_eod(codes, max(event["day"] for event in events))
    investor = load_investor()
    rows = [
        make_features(event, eod.get(event["code"], []), investor)
        for event in events
    ]
    add_within_day_percentiles(rows)
    comparisons = feature_comparison(rows)
    rules = screen_rules(rows)
    write_csv(OUT_DETAIL, rows)
    write_csv(OUT_COMPARE, comparisons)
    write_csv(OUT_RULES, rules)

    quick = [row for row in rows if row["quick_v"]]
    control = [row for row in rows if not row["quick_v"]]
    summary = {
        "title": "골짜기 급반등 사전 특징 분석",
        "period": sorted({row["day"] for row in rows}),
        "timezone": "Asia/Seoul",
        "target_definition": "09:00~09:20 최종 저점 뒤 10초 안에 +0.6% 이상",
        "cohort": {
            "events": len(rows),
            "quick_v": len(quick),
            "control": len(control),
            "by_day": {
                day: {
                    "events": sum(row["day"] == day for row in rows),
                    "quick_v": sum(row["day"] == day and row["quick_v"] for row in rows),
                }
                for day in sorted({row["day"] for row in rows})
            },
        },
        "morning_drop": {
            "quick_mean_pct": mean(row["morning_low_drop_pct"] for row in quick),
            "quick_median_pct": median(row["morning_low_drop_pct"] for row in quick),
            "quick_min_pct": min(row["morning_low_drop_pct"] for row in quick),
            "quick_max_pct": max(row["morning_low_drop_pct"] for row in quick),
            "control_mean_pct": mean(row["morning_low_drop_pct"] for row in control),
            "control_median_pct": median(row["morning_low_drop_pct"] for row in control),
        },
        "data_quality": {
            "eod_history_ge_6": sum(row.get("eod_history_days", 0) >= 6 for row in rows),
            "investor_d1_coverage": sum(row.get("supply_d1_volume_pct") is not None for row in rows),
            "investor_5d_complete": sum(row.get("investor_days_5d") == 5 for row in rows),
            "investor_source_min_date": min(day for _, day in investor),
            "investor_source_max_date": max(day for _, day in investor),
        },
        "top_feature_differences": comparisons[:10],
        "stable_single_feature_rules": rules[:10],
        "multiple_testing_warning": (
            "7건 표본의 탐색 결과다. 동일 조건을 추가 거래일 주문0 표본에 고정해 "
            "재검증하기 전 실전 필터로 사용하지 않는다."
        ),
        "outputs": {
            "detail": str(OUT_DETAIL),
            "comparison": str(OUT_COMPARE),
            "rules": str(OUT_RULES),
        },
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run()

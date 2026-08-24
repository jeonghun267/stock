# -*- coding: utf-8 -*-
"""급반등 7종목의 최종 저점 직후 체결차이와 저점 포함 분봉 꼬리 분석.

입력은 1초 SHADOW 원본과 이미 확정한 급반등 7건이다. 실제 주문은 없다.
완성 1·3·5분봉은 사후 기술 통계이며 실시간 진입조건으로 사용하지 않는다.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Optional


ROOT = Path(r"C:\stock_bot")
EVENTS_PATH = ROOT / "analysis" / "골짜기_급반등_사전특징_77종목.csv"
RAW_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
OUT_FLOW = ROOT / "analysis" / "골짜기_급반등_최종저점_1_10초체결차이.csv"
OUT_WICK = ROOT / "analysis" / "골짜기_급반등_저점포함_1_3_5분봉꼬리.csv"
OUT_JSON = ROOT / "analysis" / "골짜기_급반등_저점체결_분봉꼬리_요약.json"

WINDOWS_SEC = (1, 2, 3, 5, 10)
TIMEFRAMES_MIN = (1, 3, 5)


def number(value: str) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def load_events() -> list[dict]:
    with EVENTS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["quick_v"].strip().lower() == "true"
        ]
    events = [
        {
            "day": row["day"],
            "code": row["code"].zfill(6),
            "name": row["name"],
            "low_at": datetime.fromisoformat(row["morning_low_at"]),
            "low_price": float(row["morning_low"]),
        }
        for row in rows
    ]
    if len(events) != 7:
        raise AssertionError(f"급반등 7건이 아니라 {len(events)}건")
    return sorted(events, key=lambda row: (row["day"], row["code"]))


def load_target_points(events: list[dict]) -> tuple[dict, dict]:
    targets_by_day: dict[str, set[str]] = defaultdict(set)
    for event in events:
        targets_by_day[event["day"]].add(event["code"])

    points: dict[tuple[str, str], list[dict]] = defaultdict(list)
    quality: dict[str, dict] = {}
    for day, target_codes in sorted(targets_by_day.items()):
        path = RAW_DIR / f"mf_1s_{day}.csv"
        last_ts: dict[str, datetime] = {}
        kept = invalid = out_of_order = 0
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            header = handle.readline().rstrip("\r\n").split(",")
            fields = (
                "current_price",
                "cum_vol",
                "che_str",
                "buy_vol_cum",
                "sell_vol_cum",
                "buy_money_cum",
                "sell_money_cum",
            )
            index = {field: header.index(field) for field in fields}
            for line in handle:
                first = line.find(",")
                second = line.find(",", first + 1)
                if first < 0 or second < 0:
                    continue
                code = line[first + 1 : second].strip().zfill(6)
                if code not in target_codes:
                    continue
                ts_text = line[:first]
                if len(ts_text) < 19 or not ("09:00:00" <= ts_text[11:19] < "09:20:00"):
                    continue
                parts = line.rstrip("\r\n").split(",")
                try:
                    ts = datetime.fromisoformat(ts_text)
                    price = float(parts[index["current_price"]])
                except (IndexError, ValueError):
                    invalid += 1
                    continue
                if price <= 0:
                    invalid += 1
                    continue
                if code in last_ts and ts <= last_ts[code]:
                    out_of_order += 1
                    continue
                last_ts[code] = ts
                row = {
                    "ts": ts,
                    "price": price,
                    "cum_vol": number(parts[index["cum_vol"]]),
                    "che_str": number(parts[index["che_str"]]),
                    "buy_vol_cum": number(parts[index["buy_vol_cum"]]),
                    "sell_vol_cum": number(parts[index["sell_vol_cum"]]),
                    "buy_money_cum": number(parts[index["buy_money_cum"]]),
                    "sell_money_cum": number(parts[index["sell_money_cum"]]),
                }
                points[(day, code)].append(row)
                kept += 1
        quality[day] = {
            "source": str(path),
            "target_codes": len(target_codes),
            "kept_points": kept,
            "invalid_points": invalid,
            "duplicate_or_out_of_order": out_of_order,
        }
    return dict(points), quality


def cumulative_window(
    event: dict,
    points: list[dict],
    seconds: int,
) -> dict:
    low_at = event["low_at"]
    baseline = next((point for point in points if point["ts"] == low_at), None)
    deadline = low_at + timedelta(seconds=seconds)
    observed = [
        point
        for point in points
        if low_at <= point["ts"] <= deadline
    ]
    endpoint = observed[-1] if len(observed) >= 2 else None
    result = {
        "day": event["day"],
        "code": event["code"],
        "name": event["name"],
        "low_at": low_at.isoformat(timespec="milliseconds"),
        "low_price": event["low_price"],
        "window_sec": seconds,
        "observations": len(observed),
        "actual_elapsed_sec": None,
        "endpoint_price": None,
        "price_rebound_pct": None,
        "che_strength_low": baseline["che_str"] if baseline else None,
        "che_strength_end": None,
        "che_strength_change": None,
        "buy_exec_volume": None,
        "sell_exec_volume": None,
        "net_buy_exec_volume": None,
        "buy_sell_volume_ratio": None,
        "buy_exec_money": None,
        "sell_exec_money": None,
        "net_buy_exec_money": None,
        "buy_sell_money_ratio": None,
        "exact_valid": False,
        "invalid_reason": "",
    }
    if baseline is None or endpoint is None:
        result["invalid_reason"] = "저점 또는 종료 관측치 부족"
        return result

    cumulative_fields = (
        "buy_vol_cum",
        "sell_vol_cum",
        "buy_money_cum",
        "sell_money_cum",
    )
    if any(point[field] is None or point[field] < 0 for point in observed for field in cumulative_fields):
        result["invalid_reason"] = "정확 누적 체결자료 누락"
        return result
    if any(
        current[field] < previous[field]
        for previous, current in zip(observed, observed[1:])
        for field in cumulative_fields
    ):
        result["invalid_reason"] = "누적 체결자료 역행"
        return result

    buy_volume = endpoint["buy_vol_cum"] - baseline["buy_vol_cum"]
    sell_volume = endpoint["sell_vol_cum"] - baseline["sell_vol_cum"]
    buy_money = endpoint["buy_money_cum"] - baseline["buy_money_cum"]
    sell_money = endpoint["sell_money_cum"] - baseline["sell_money_cum"]
    elapsed = (endpoint["ts"] - low_at).total_seconds()
    result.update(
        {
            "actual_elapsed_sec": elapsed,
            "endpoint_price": endpoint["price"],
            "price_rebound_pct": (endpoint["price"] / event["low_price"] - 1.0) * 100.0,
            "che_strength_end": endpoint["che_str"],
            "che_strength_change": (
                endpoint["che_str"] - baseline["che_str"]
                if endpoint["che_str"] is not None and baseline["che_str"] is not None
                else None
            ),
            "buy_exec_volume": buy_volume,
            "sell_exec_volume": sell_volume,
            "net_buy_exec_volume": buy_volume - sell_volume,
            "buy_sell_volume_ratio": buy_volume / sell_volume if sell_volume > 0 else None,
            "buy_exec_money": buy_money,
            "sell_exec_money": sell_money,
            "net_buy_exec_money": buy_money - sell_money,
            "buy_sell_money_ratio": buy_money / sell_money if sell_money > 0 else None,
            "exact_valid": True,
        }
    )
    return result


def bar_start(ts: datetime, timeframe_min: int) -> datetime:
    minute = (ts.minute // timeframe_min) * timeframe_min
    return ts.replace(minute=minute, second=0, microsecond=0)


def wick_row(event: dict, points: list[dict], timeframe_min: int) -> dict:
    start = bar_start(event["low_at"], timeframe_min)
    end = start + timedelta(minutes=timeframe_min)
    bar = [point for point in points if start <= point["ts"] < end]
    if not bar:
        raise AssertionError(f"{event['day']} {event['code']} {timeframe_min}분봉 없음")
    open_price = bar[0]["price"]
    high = max(point["price"] for point in bar)
    low = min(point["price"] for point in bar)
    close = bar[-1]["price"]
    body_top = max(open_price, close)
    body_bottom = min(open_price, close)
    lower = max(0.0, body_bottom - low)
    upper = max(0.0, high - body_top)
    body = abs(close - open_price)
    price_range = high - low
    return {
        "day": event["day"],
        "code": event["code"],
        "name": event["name"],
        "low_at": event["low_at"].isoformat(timespec="milliseconds"),
        "timeframe_min": timeframe_min,
        "bar_start": start.isoformat(timespec="seconds"),
        "bar_end": end.isoformat(timespec="seconds"),
        "observations": len(bar),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "bullish": close > open_price,
        "range": price_range,
        "body": body,
        "lower_wick": lower,
        "upper_wick": upper,
        "lower_wick_share": lower / price_range if price_range > 0 else 0.0,
        "upper_wick_share": upper / price_range if price_range > 0 else 0.0,
        "body_share": body / price_range if price_range > 0 else 0.0,
        "lower_gt_upper": lower > upper,
        "lower_upper_ratio": lower / upper if upper > 0 else None,
        "close_position": (close - low) / price_range if price_range > 0 else 0.5,
        "low_matches_event": abs(low - event["low_price"]) < 1e-9,
        "completed_bar_lookahead": True,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def finite_median(values: list[Optional[float]]) -> Optional[float]:
    valid = [float(value) for value in values if value is not None]
    return median(valid) if valid else None


def run() -> dict:
    events = load_events()
    points, quality = load_target_points(events)
    flow_rows = [
        cumulative_window(event, points[(event["day"], event["code"])], seconds)
        for event in events
        for seconds in WINDOWS_SEC
    ]
    wick_rows = [
        wick_row(event, points[(event["day"], event["code"])], timeframe)
        for event in events
        for timeframe in TIMEFRAMES_MIN
    ]
    write_csv(OUT_FLOW, flow_rows)
    write_csv(OUT_WICK, wick_rows)

    flow_summary = {}
    for seconds in WINDOWS_SEC:
        rows = [row for row in flow_rows if row["window_sec"] == seconds]
        valid = [row for row in rows if row["exact_valid"]]
        flow_summary[str(seconds)] = {
            "valid": len(valid),
            "buy_volume_dominant": sum(row["buy_exec_volume"] > row["sell_exec_volume"] for row in valid),
            "buy_volume_ratio_ge_1_5": sum(
                row["sell_exec_volume"] == 0 < row["buy_exec_volume"]
                or (row["buy_sell_volume_ratio"] or 0) >= 1.5
                for row in valid
            ),
            "buy_volume_ratio_ge_2": sum(
                row["sell_exec_volume"] == 0 < row["buy_exec_volume"]
                or (row["buy_sell_volume_ratio"] or 0) >= 2.0
                for row in valid
            ),
            "buy_money_dominant": sum(row["buy_exec_money"] > row["sell_exec_money"] for row in valid),
            "median_buy_sell_volume_ratio": finite_median(
                [row["buy_sell_volume_ratio"] for row in valid]
            ),
            "median_buy_sell_money_ratio": finite_median(
                [row["buy_sell_money_ratio"] for row in valid]
            ),
            "median_price_rebound_pct": finite_median(
                [row["price_rebound_pct"] for row in valid]
            ),
        }

    wick_summary = {}
    for timeframe in TIMEFRAMES_MIN:
        rows = [row for row in wick_rows if row["timeframe_min"] == timeframe]
        wick_summary[str(timeframe)] = {
            "bars": len(rows),
            "bullish": sum(row["bullish"] for row in rows),
            "lower_wick_gt_upper": sum(row["lower_gt_upper"] for row in rows),
            "median_lower_wick_share": median(row["lower_wick_share"] for row in rows),
            "median_upper_wick_share": median(row["upper_wick_share"] for row in rows),
            "median_body_share": median(row["body_share"] for row in rows),
            "median_close_position": median(row["close_position"] for row in rows),
            "low_matches_event": sum(row["low_matches_event"] for row in rows),
        }

    result = {
        "title": "골짜기 급반등 최종저점 체결차이와 분봉꼬리",
        "period": sorted({event["day"] for event in events}),
        "timezone": "Asia/Seoul",
        "actual_orders": 0,
        "input_granularity": "1초 SHADOW 스냅샷",
        "target": "최종 저점 뒤 10초 안에 +0.6% 이상 급반등한 7건",
        "flow_windows_sec": list(WINDOWS_SEC),
        "wick_timeframes_min": list(TIMEFRAMES_MIN),
        "flow_summary": flow_summary,
        "wick_summary": wick_summary,
        "quality": quality,
        "caveat": "완성 1·3·5분봉 꼬리는 저점 이후 가격을 포함한 사후 기술 통계다.",
        "outputs": {"flow": str(OUT_FLOW), "wick": str(OUT_WICK)},
    }
    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    run()

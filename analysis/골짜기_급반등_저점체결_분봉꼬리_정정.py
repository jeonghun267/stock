# -*- coding: utf-8 -*-
"""밀리초 저점표와 마이크로초 원본을 가격+0.05초로 정합하는 보정 실행기."""
from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path


PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_저점체결_분봉꼬리_분석.py")
SPEC = importlib.util.spec_from_file_location("valley_low_wick_base", PATH)
assert SPEC and SPEC.loader
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


def cumulative_window(event: dict, points: list[dict], seconds: int) -> dict:
    low_at = event["low_at"]
    nearest = min(
        points,
        key=lambda point: abs((point["ts"] - low_at).total_seconds()),
        default=None,
    )
    baseline = (
        nearest
        if nearest is not None
        and abs((nearest["ts"] - low_at).total_seconds()) <= 0.05
        and abs(nearest["price"] - event["low_price"]) < 1e-9
        else None
    )
    baseline_ts = baseline["ts"] if baseline else low_at
    deadline = baseline_ts + timedelta(seconds=seconds)
    observed = [
        point
        for point in points
        if baseline_ts <= point["ts"] <= deadline
    ]
    endpoint = observed[-1] if len(observed) >= 2 else None
    result = {
        "day": event["day"],
        "code": event["code"],
        "name": event["name"],
        "low_at": low_at.isoformat(timespec="milliseconds"),
        "baseline_ts": (
            baseline_ts.isoformat(timespec="microseconds") if baseline else None
        ),
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
    if any(
        point[field] is None or point[field] < 0
        for point in observed
        for field in cumulative_fields
    ):
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
    elapsed = (endpoint["ts"] - baseline_ts).total_seconds()
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


BASE.cumulative_window = cumulative_window


if __name__ == "__main__":
    BASE.run()

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from flow_trend_selector_v1 import build_flow_trend


def test_requires_three_positive_new_snapshots_and_rejects_dump() -> None:
    trend = {"source_date": "20260831", "candidates": [
        {"code": "111111", "name": "A", "state": "TREND_UP", "trend_score": 80},
        {"code": "222222", "name": "B", "state": "TREND_UP", "trend_score": 90},
    ]}
    state = {}
    for index, big in enumerate((100, 130, 160, 190)):
        observed_at = datetime(2026, 9, 1, 9, 0) + timedelta(seconds=index * 20)
        flow = {"ts": observed_at.isoformat(sep=" "), "regime": "코스닥-1.0%", "rows": [
            {"code": "111111", "name": "A", "big": big, "buy_cnt": 3,
             "grade": "매수세", "val_eok": 100 + index, "chg": 2, "che": 120,
             "price": 1000 + index},
            {"code": "222222", "name": "B", "big": big, "buy_cnt": 3,
             "grade": "던짐", "val_eok": 100 + index, "chg": 3, "che": 130,
             "price": 2000 + index},
        ]}
        result, state = build_flow_trend(trend, flow, state)
    assert [row["code"] for row in result["candidates"]] == ["111111"]
    dumped = next(row for row in result["watch"] if row["code"] == "222222")
    assert "DUMP_GRADE" in dumped["blocked_by"]
    assert result["display"][0]["flow_score"] >= result["display"][1]["flow_score"]


def test_dynamic_universe_finds_micro_inflow_before_smart_detail() -> None:
    state = {}
    for index in range(4):
        observed_at = datetime(2026, 9, 1, 10, 0) + timedelta(seconds=index * 20)
        flow = {"ts": observed_at.isoformat(sep=" "), "regime": "코스닥-1.0%",
                "univ_codes": ["333333"], "rows": []}
        micro = {"ts": observed_at.isoformat(), "codes": {"333333": {
            "cur": 1000 + index, "op": 980, "che_str": 120,
            "buy_money_cum": 3_000_000_000 + index * 100_000_000,
            "sell_money_cum": 1_000_000_000 + index * 10_000_000,
        }}}
        result, state = build_flow_trend(
            {"candidates": [], "observe": []}, flow, state, micro,
        )
    assert [row["code"] for row in result["discoveries"]] == ["333333"]
    assert result["discoveries"][0]["flow_source"] == "MICRO_DISCOVERY"


def test_tracks_new_session_low_time_and_rebound() -> None:
    state = {}
    lows = (990, 980, 980)
    prices = (1000, 980, 1020)
    for index, (low, price) in enumerate(zip(lows, prices)):
        observed_at = datetime(2026, 9, 1, 11, 0) + timedelta(seconds=index * 20)
        flow = {"regime": "코스닥+0.0%", "univ_codes": ["444444"], "rows": []}
        micro = {"ts": observed_at.isoformat(), "codes": {"444444": {
            "ts": observed_at.isoformat(), "cur": price, "lo": low, "op": 970,
            "best_ask_px": price + 1, "best_bid_px": price - 1,
            "ask_tot": 200_000, "bid_tot": 200_000,
            "buy_money_cum": 4_000_000_000 + index * 100_000_000,
            "sell_money_cum": 1_000_000_000,
        }}}
        result, state = build_flow_trend({}, flow, state, micro)
    row = result["display"][0]
    assert row["session_low"] == 980
    assert row["session_low_time"] == "2026-09-01T11:00:20"
    assert row["rebound_amount"] == 40
    assert row["rebound_pct"] == 4.08
    assert row["liquidity_status"] == "PASS"
    assert 0 < row["slice_cap_manwon"] <= 500


def test_detects_compression_value_explosion_and_cost_covered_volatility() -> None:
    state = {}
    buy_cum = 4_000_000_000
    for index in range(22):
        observed_at = datetime(2026, 9, 1, 12, 0) + timedelta(seconds=index * 20)
        if index >= 19:
            buy_cum += 100_000_000
            price = 1000 + (index - 19) * 10
        else:
            buy_cum += 10_000_000
            price = 1000
        flow = {"regime": "코스닥+0.0%", "univ_codes": ["555555"], "rows": []}
        micro = {"ts": observed_at.isoformat(), "codes": {"555555": {
            "ts": observed_at.isoformat(), "cur": price, "op": 990,
            "hi": 1020, "lo": 980,
            "best_ask_px": price + 1, "best_bid_px": price - 1,
            "ask_tot": 200_000, "bid_tot": 200_000,
            "buy_money_cum": buy_cum, "sell_money_cum": 1_000_000_000,
        }}}
        result, state = build_flow_trend({}, flow, state, micro)
    row = result["display"][0]
    assert row["recent_range_pct"] >= row["required_volatility_pct"]
    assert row["volatility_status"] == "PASS"
    assert "횡보후거래폭발" in row["volatility_pattern"]


def test_keeps_candidate_visible_through_overheat_pullback_and_reaccel() -> None:
    state = {}
    phases = []
    prices = (1000, 1030, 1020, 1025)
    for index, price in enumerate(prices):
        observed_at = datetime(2026, 9, 1, 13, 0) + timedelta(seconds=index * 20)
        total_money = 5_000_000_000 + index * 100_000_000
        flow = {"regime": "코스닥+0.0%", "univ_codes": ["666666"], "rows": []}
        micro = {"ts": observed_at.isoformat(), "codes": {"666666": {
            "ts": observed_at.isoformat(), "cur": price, "op": 990,
            "buy_money_cum": total_money - 1_000_000_000,
            "sell_money_cum": 1_000_000_000,
            "buy_vol_cum": total_money / 1000 - 1_000_000,
            "sell_vol_cum": 1_000_000,
        }}}
        result, state = build_flow_trend({}, flow, state, micro)
        assert len(result["display"]) == 1
        phases.append(result["display"][0]["entry_phase"])
    assert phases == [
        "FLOW_FOUND", "OVERHEAT_WAIT", "PULLBACK_READY", "REACCEL_TRIGGER",
    ]


def test_adds_absolute_flow_acceleration_percentile_to_score() -> None:
    state = {}
    for index in range(2):
        observed_at = datetime(2026, 9, 1, 14, 0) + timedelta(seconds=index * 20)
        flow = {
            "regime": "코스닥+0.0%", "univ_codes": ["777777", "888888"],
            "rows": [],
        }
        micro = {"ts": observed_at.isoformat(), "codes": {
            "777777": {
                "ts": observed_at.isoformat(), "cur": 1000 + index, "op": 990,
                "buy_money_cum": 3_000_000_000 + index * 100_000_000,
                "sell_money_cum": 1_000_000_000,
            },
            "888888": {
                "ts": observed_at.isoformat(), "cur": 1000 + index, "op": 990,
                "buy_money_cum": 3_000_000_000 + index * 50_000_000,
                "sell_money_cum": 1_000_000_000,
            },
        }}
        result, state = build_flow_trend({}, flow, state, micro)
    rows = {row["code"]: row for row in result["display"]}
    assert rows["777777"]["absolute_flow_percentile"] == 100.0
    assert rows["888888"]["absolute_flow_percentile"] == 50.0
    assert rows["777777"]["flow_score"] > rows["888888"]["flow_score"]


def test_detects_early_rebound_without_removing_top_display() -> None:
    state = {}
    prices = (1000, 1000, 1002, 1005, 1008, 1010, 1012)
    buy_values = (2_000, 2_100, 2_300, 2_450, 2_600, 2_750, 2_900)
    sell_values = (1_000, 1_150, 1_200, 1_210, 1_220, 1_230, 1_240)
    for index, price in enumerate(prices):
        observed_at = datetime(2026, 9, 1, 14, 30) + timedelta(seconds=index * 20)
        buy_money = buy_values[index] * 1_000_000
        sell_money = sell_values[index] * 1_000_000
        total_money = buy_money + sell_money
        flow = {"regime": "코스닥+0.0%", "univ_codes": ["999999"], "rows": []}
        micro = {"ts": observed_at.isoformat(), "codes": {"999999": {
            "ts": observed_at.isoformat(), "cur": price, "op": 990,
            "lo": 1000, "hi": 1012,
            "buy_money_cum": buy_money, "sell_money_cum": sell_money,
            "buy_vol_cum": total_money / 1000 - 1_000_000,
            "sell_vol_cum": 1_000_000,
        }}}
        result, state = build_flow_trend({}, flow, state, micro)
    assert len(result["display"]) == 1
    assert result["early_rebounds"][0]["code"] == "999999"
    assert result["early_rebounds"][0]["early_rebound_status"] == "EARLY_REBOUND"

# -*- coding: utf-8 -*-
"""체결대금 하한 없이 매수전환·매도흡수형을 비교하는 주문0 재생.

기존 S03 가격 하한 1만원, -4% 무장, 신저가 RESET, 종목당 1회,
-2% 안전손절은 유지한다. 체결대금 최소값은 사용하지 않는다.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from statistics import median
from typing import Optional


ROOT = Path(r"C:\stock_bot")
EVENTS_PATH = ROOT / "analysis" / "골짜기_급반등_사전특징_77종목.csv"
RAW_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
OUT_DETAIL = ROOT / "analysis" / "골짜기_급반등_무대금_매도흡수_상세.csv"
OUT_SUMMARY = ROOT / "analysis" / "골짜기_급반등_무대금_매도흡수_요약.csv"
OUT_JSON = ROOT / "analysis" / "골짜기_급반등_무대금_매도흡수_요약.json"

ENTRY_START = time(9, 0)
ENTRY_END = time(9, 20)
EVALUATION_END = time(9, 30)
ARM_DROP_PCT = -4.0
MIN_PRICE = 10_000.0
HARD_STOP_PCT = -2.0
ROUND_TRIP_FEES_TAX_PCT = 0.21
ASSUMED_ROUND_TRIP_SLIPPAGE_PCT = 0.10


@dataclass(frozen=True, slots=True)
class Point:
    ts: datetime
    price: float
    che_str: float
    ask_tot: float
    bid_tot: float
    buy_vol_cum: float
    sell_vol_cum: float


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    mode: str
    max_sec: float
    book_rule: str = "none"


CANDIDATES = (
    Candidate("FLOW_TRANSITION_3_5", "flow_transition", 5.0),
    Candidate("FLOW_TRANSITION_3_10", "flow_transition", 10.0),
    Candidate("FLOW_DOMINANCE_3_5", "flow_dominance", 5.0),
    Candidate("FLOW_DOMINANCE_3_10", "flow_dominance", 10.0),
    Candidate("ABSORB_PRICE_3_5", "absorption", 5.0, "none"),
    Candidate("ABSORB_BOOK_3_5", "absorption", 5.0, "bid_over_ask"),
    Candidate("ABSORB_BOOK_3_10", "absorption", 10.0, "bid_over_ask"),
    Candidate("ABSORB_BID_HOLD_3_10", "absorption", 10.0, "bid_hold"),
    Candidate("ABSORB_ASK_DOWN_3_10", "absorption", 10.0, "ask_down"),
    Candidate("COMBINED_BOOK_3_5", "combined", 5.0, "bid_over_ask"),
    Candidate("COMBINED_BOOK_3_10", "combined", 10.0, "bid_over_ask"),
)


def number(value: str, default: float = -1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_events() -> list[dict]:
    with EVENTS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    events = []
    for row in rows:
        events.append(
            {
                "day": row["day"],
                "code": row["code"].zfill(6),
                "name": row["name"],
                "previous_close": float(row["previous_close"]),
                "armed_at": datetime.fromisoformat(row["armed_at"]),
                "final_low": float(row["morning_low"]),
                "final_low_at": datetime.fromisoformat(row["morning_low_at"]),
                "quick_v": row["quick_v"].strip().lower() == "true",
            }
        )
    if len(events) != 77 or len({(row["day"], row["code"]) for row in events}) != 77:
        raise AssertionError("77건 사건 키가 유일하지 않음")
    return sorted(events, key=lambda row: (row["day"], row["code"]))


def load_points(events: list[dict]) -> tuple[dict[tuple[str, str], list[Point]], dict]:
    codes_by_day: dict[str, set[str]] = defaultdict(set)
    for event in events:
        codes_by_day[event["day"]].add(event["code"])
    output: dict[tuple[str, str], list[Point]] = defaultdict(list)
    quality = {}
    for day, codes in sorted(codes_by_day.items()):
        path = RAW_DIR / f"mf_1s_{day}.csv"
        last_ts: dict[str, datetime] = {}
        kept = invalid = out_of_order = exact = 0
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            header = handle.readline().rstrip("\r\n").split(",")
            fields = (
                "current_price",
                "che_str",
                "ask_tot",
                "bid_tot",
                "buy_vol_cum",
                "sell_vol_cum",
            )
            index = {field: header.index(field) for field in fields}
            for line in handle:
                first = line.find(",")
                second = line.find(",", first + 1)
                if first < 0 or second < 0:
                    continue
                code = line[first + 1 : second].strip().zfill(6)
                if code not in codes:
                    continue
                ts_text = line[:first]
                if len(ts_text) < 19 or not ("09:00:00" <= ts_text[11:19] < "09:30:00"):
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
                point = Point(
                    ts=ts,
                    price=price,
                    che_str=number(parts[index["che_str"]], 0.0),
                    ask_tot=number(parts[index["ask_tot"]]),
                    bid_tot=number(parts[index["bid_tot"]]),
                    buy_vol_cum=number(parts[index["buy_vol_cum"]]),
                    sell_vol_cum=number(parts[index["sell_vol_cum"]]),
                )
                output[(day, code)].append(point)
                kept += 1
                if is_exact(point):
                    exact += 1
        quality[day] = {
            "source": str(path),
            "event_codes": len(codes),
            "kept_points_0900_0930": kept,
            "exact_points": exact,
            "exact_rate_pct": round(exact / kept * 100.0, 4) if kept else 0.0,
            "invalid_points": invalid,
            "duplicate_or_out_of_order": out_of_order,
        }
    return dict(output), quality


def is_exact(point: Point) -> bool:
    return (
        point.ask_tot > 0
        and point.bid_tot > 0
        and point.buy_vol_cum >= 0
        and point.sell_vol_cum >= 0
    )


def book_pass(
    rule: str,
    point: Point,
    reset_ask: float,
    reset_bid: float,
) -> bool:
    if rule == "none":
        return True
    if rule == "bid_over_ask":
        return point.bid_tot > point.ask_tot
    if rule == "bid_hold":
        return point.bid_tot > point.ask_tot and point.bid_tot >= reset_bid
    if rule == "ask_down":
        return point.bid_tot > point.ask_tot and point.ask_tot <= reset_ask
    raise ValueError(rule)


def first_signal(event: dict, points: list[Point], candidate: Candidate) -> Optional[dict]:
    armed = False
    low_price = 0.0
    low_ts: Optional[datetime] = None
    reset_ts: Optional[datetime] = None
    reset_che = 0.0
    reset_ask = 0.0
    reset_bid = 0.0
    base_buy: Optional[float] = None
    base_sell: Optional[float] = None
    prior_buy: Optional[float] = None
    prior_sell: Optional[float] = None
    had_sell_dominance = False
    recent: deque[Point] = deque(maxlen=2)

    for point in points:
        if point.ts.time() >= ENTRY_END:
            break
        drop_pct = (point.price / event["previous_close"] - 1.0) * 100.0
        new_low = False
        if not armed and drop_pct <= ARM_DROP_PCT:
            armed = True
            new_low = True
        elif armed and point.price < low_price:
            new_low = True
        if new_low:
            low_price = point.price
            low_ts = point.ts
            reset_ts = point.ts
            reset_che = point.che_str
            reset_ask = point.ask_tot
            reset_bid = point.bid_tot
            base_buy = point.buy_vol_cum if is_exact(point) else None
            base_sell = point.sell_vol_cum if is_exact(point) else None
            prior_buy = base_buy
            prior_sell = base_sell
            had_sell_dominance = False
            recent.clear()
            recent.append(point)
            continue
        if not armed or low_ts is None or reset_ts is None:
            continue
        if not is_exact(point):
            base_buy = base_sell = prior_buy = prior_sell = None
            recent.clear()
            continue
        if base_buy is None or base_sell is None or prior_buy is None or prior_sell is None:
            reset_ts = point.ts
            reset_che = point.che_str
            reset_ask = point.ask_tot
            reset_bid = point.bid_tot
            base_buy = prior_buy = point.buy_vol_cum
            base_sell = prior_sell = point.sell_vol_cum
            had_sell_dominance = False
            recent.clear()
            recent.append(point)
            continue
        if point.buy_vol_cum < prior_buy or point.sell_vol_cum < prior_sell:
            reset_ts = point.ts
            reset_che = point.che_str
            reset_ask = point.ask_tot
            reset_bid = point.bid_tot
            base_buy = prior_buy = point.buy_vol_cum
            base_sell = prior_sell = point.sell_vol_cum
            had_sell_dominance = False
            recent.clear()
            recent.append(point)
            continue
        prior_buy = point.buy_vol_cum
        prior_sell = point.sell_vol_cum
        buy_volume = point.buy_vol_cum - base_buy
        sell_volume = point.sell_vol_cum - base_sell
        total_volume = buy_volume + sell_volume
        net_volume = buy_volume - sell_volume
        elapsed = (point.ts - reset_ts).total_seconds()
        recent.append(point)
        holds = (
            len(recent) == 2
            and recent[0].price > low_price
            and recent[1].price > low_price
            and recent[1].price >= recent[0].price
        )
        flow_transition = (
            total_volume > 0
            and had_sell_dominance
            and net_volume > 0
            and point.che_str > reset_che > 0
        )
        flow_dominance = (
            total_volume > 0
            and net_volume > 0
            and point.che_str > reset_che > 0
        )
        absorption = (
            total_volume > 0
            and net_volume < 0
            and book_pass(candidate.book_rule, point, reset_ask, reset_bid)
        )
        if net_volume < 0:
            had_sell_dominance = True
        if not (
            3.0 <= elapsed <= candidate.max_sec
            and point.price >= MIN_PRICE
            and holds
        ):
            continue
        matched = (
            flow_transition
            if candidate.mode == "flow_transition"
            else flow_dominance
            if candidate.mode == "flow_dominance"
            else absorption
            if candidate.mode == "absorption"
            else flow_dominance or absorption
        )
        if not matched:
            continue
        return {
            "signal_ts": point.ts,
            "signal_price": point.price,
            "anchor_low_ts": low_ts,
            "anchor_low_price": low_price,
            "elapsed_sec": elapsed,
            "buy_exec_volume": buy_volume,
            "sell_exec_volume": sell_volume,
            "net_exec_volume": net_volume,
            "buy_sell_ratio": buy_volume / sell_volume if sell_volume > 0 else None,
            "che_change": point.che_str - reset_che,
            "bid_ask_ratio": point.bid_tot / point.ask_tot if point.ask_tot > 0 else None,
            "bid_change": point.bid_tot - reset_bid,
            "ask_change": point.ask_tot - reset_ask,
            "signal_type": (
                "FLOW"
                if flow_dominance
                else "ABSORPTION"
            ),
        }
    return None


def point_at_or_before(points: list[Point], deadline: datetime) -> Optional[Point]:
    selected = None
    for point in points:
        if point.ts > deadline:
            break
        selected = point
    return selected


def evaluate(event: dict, points: list[Point], candidate: Candidate, signal: Optional[dict]) -> dict:
    row = {
        "day": event["day"],
        "code": event["code"],
        "name": event["name"],
        "algorithm": candidate.name,
        "quick_v": event["quick_v"],
        "quick_eligible": event["quick_v"] and event["final_low"] >= MIN_PRICE,
        "signal": "NO",
        "signal_type": "",
        "signal_ts": "",
        "signal_price": None,
        "anchor_low_ts": "",
        "anchor_low_price": None,
        "signal_after_final_low_sec": None,
        "premature_before_final_low": False,
        "post_signal_new_low": False,
        "hard_stop_by_0930": False,
        "target_1pct_before_stop": False,
        "target_2pct_before_stop": False,
        "mfe_30s_pct": None,
        "mae_30s_pct": None,
        "net_30s_after_cost_pct": None,
        "buy_exec_volume": None,
        "sell_exec_volume": None,
        "net_exec_volume": None,
        "buy_sell_ratio": None,
        "che_change": None,
        "bid_ask_ratio": None,
        "bid_change": None,
        "ask_change": None,
        "elapsed_sec": None,
        "actual_orders": 0,
    }
    if signal is None:
        return row
    signal_ts = signal["signal_ts"]
    signal_price = signal["signal_price"]
    after_final = (signal_ts - event["final_low_at"]).total_seconds()
    later = [point for point in points if point.ts > signal_ts]
    post_new_low = any(
        point.ts.time() < ENTRY_END and point.price < signal["anchor_low_price"]
        for point in later
    )
    stop_price = signal_price * (1.0 + HARD_STOP_PCT / 100.0)
    stop_ts = next((point.ts for point in later if point.price <= stop_price), None)
    target1_ts = next((point.ts for point in later if point.price >= signal_price * 1.01), None)
    target2_ts = next((point.ts for point in later if point.price >= signal_price * 1.02), None)
    within_30 = [point for point in later if point.ts <= signal_ts + timedelta(seconds=30)]
    prices_30 = [signal_price] + [point.price for point in within_30]
    end_30 = point_at_or_before(points, signal_ts + timedelta(seconds=30))
    net_30 = (
        (end_30.price / signal_price - 1.0) * 100.0
        - ROUND_TRIP_FEES_TAX_PCT
        - ASSUMED_ROUND_TRIP_SLIPPAGE_PCT
        if end_30 is not None
        else None
    )
    row.update(
        {
            "signal": "YES",
            "signal_type": signal["signal_type"],
            "signal_ts": signal_ts.isoformat(timespec="milliseconds"),
            "signal_price": signal_price,
            "anchor_low_ts": signal["anchor_low_ts"].isoformat(timespec="milliseconds"),
            "anchor_low_price": signal["anchor_low_price"],
            "signal_after_final_low_sec": after_final,
            "premature_before_final_low": after_final < -0.05,
            "post_signal_new_low": post_new_low,
            "hard_stop_by_0930": stop_ts is not None,
            "target_1pct_before_stop": target1_ts is not None and (stop_ts is None or target1_ts < stop_ts),
            "target_2pct_before_stop": target2_ts is not None and (stop_ts is None or target2_ts < stop_ts),
            "mfe_30s_pct": (max(prices_30) / signal_price - 1.0) * 100.0,
            "mae_30s_pct": (min(prices_30) / signal_price - 1.0) * 100.0,
            "net_30s_after_cost_pct": net_30,
            "buy_exec_volume": signal["buy_exec_volume"],
            "sell_exec_volume": signal["sell_exec_volume"],
            "net_exec_volume": signal["net_exec_volume"],
            "buy_sell_ratio": signal["buy_sell_ratio"],
            "che_change": signal["che_change"],
            "bid_ask_ratio": signal["bid_ask_ratio"],
            "bid_change": signal["bid_change"],
            "ask_change": signal["ask_change"],
            "elapsed_sec": signal["elapsed_sec"],
        }
    )
    return row


def summarize(rows: list[dict], candidate: Candidate) -> dict:
    selected = [row for row in rows if row["algorithm"] == candidate.name]
    signals = [row for row in selected if row["signal"] == "YES"]
    captured = [
        row
        for row in signals
        if row["quick_eligible"]
        and row["signal_after_final_low_sec"] is not None
        and -0.05 <= float(row["signal_after_final_low_sec"]) <= 10.0
    ]
    quick_eligible = sum(row["quick_eligible"] for row in selected)
    return {
        "algorithm": candidate.name,
        "mode": candidate.mode,
        "max_sec": candidate.max_sec,
        "book_rule": candidate.book_rule,
        "minimum_money": 0,
        "events": len(selected),
        "signals": len(signals),
        "flow_signals": sum(row["signal_type"] == "FLOW" for row in signals),
        "absorption_signals": sum(row["signal_type"] == "ABSORPTION" for row in signals),
        "premature": sum(row["premature_before_final_low"] for row in signals),
        "premature_pct": (
            sum(row["premature_before_final_low"] for row in signals) / len(signals) * 100.0
            if signals else 0.0
        ),
        "post_signal_new_low": sum(row["post_signal_new_low"] for row in signals),
        "hard_stops": sum(row["hard_stop_by_0930"] for row in signals),
        "target_1pct_before_stop": sum(row["target_1pct_before_stop"] for row in signals),
        "target_2pct_before_stop": sum(row["target_2pct_before_stop"] for row in signals),
        "quick_all": sum(row["quick_v"] for row in selected),
        "quick_eligible": quick_eligible,
        "quick_eligible_captured": len(captured),
        "quick_capture_pct": len(captured) / quick_eligible * 100.0 if quick_eligible else 0.0,
        "signal_precision_pct": len(captured) / len(signals) * 100.0 if signals else 0.0,
        "median_mfe_30s_pct": median(
            float(row["mfe_30s_pct"]) for row in signals
        ) if signals else None,
        "median_mae_30s_pct": median(
            float(row["mae_30s_pct"]) for row in signals
        ) if signals else None,
        "median_net_30s_after_cost_pct": median(
            float(row["net_30s_after_cost_pct"]) for row in signals
        ) if signals else None,
        "day1_signals": sum(row["day"] == "20260723" for row in signals),
        "day2_signals": sum(row["day"] == "20260724" for row in signals),
        "day1_captured": sum(row["day"] == "20260723" for row in captured),
        "day2_captured": sum(row["day"] == "20260724" for row in captured),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run() -> dict:
    events = load_events()
    points_by_key, quality = load_points(events)
    detail = []
    for event in events:
        points = points_by_key[(event["day"], event["code"])]
        for candidate in CANDIDATES:
            signal = first_signal(event, points, candidate)
            detail.append(evaluate(event, points, candidate, signal))
    summaries = [summarize(detail, candidate) for candidate in CANDIDATES]
    ranked = sorted(
        summaries,
        key=lambda row: (
            -row["quick_eligible_captured"],
            row["premature_pct"],
            row["hard_stops"],
            -row["signal_precision_pct"],
            row["signals"],
        ),
    )
    write_csv(OUT_DETAIL, detail)
    write_csv(OUT_SUMMARY, ranked)
    result = {
        "title": "골짜기 급반등 체결대금 하한 제거·매도흡수 주문0 비교",
        "period": sorted({event["day"] for event in events}),
        "timezone": "Asia/Seoul",
        "actual_orders": 0,
        "fixed": {
            "minimum_money": 0,
            "minimum_price": MIN_PRICE,
            "arm_drop_pct": ARM_DROP_PCT,
            "one_entry_per_symbol": True,
            "new_low_resets_all": True,
            "hard_stop_pct": HARD_STOP_PCT,
            "fees_tax_pct": ROUND_TRIP_FEES_TAX_PCT,
            "round_trip_slippage_pct": ASSUMED_ROUND_TRIP_SLIPPAGE_PCT,
        },
        "cohort": {
            "events": len(events),
            "quick_all": sum(event["quick_v"] for event in events),
            "quick_price_eligible": sum(
                event["quick_v"] and event["final_low"] >= MIN_PRICE
                for event in events
            ),
        },
        "quality": quality,
        "ranked_summaries": ranked,
        "outputs": {"detail": str(OUT_DETAIL), "summary": str(OUT_SUMMARY)},
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    run()

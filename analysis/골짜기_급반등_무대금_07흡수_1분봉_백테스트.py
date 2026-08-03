# -*- coding: utf-8 -*-
"""매수/매도 체결량 0.6·0.7·0.8과 1분봉 꼬리·호가잔량 흡수 비교."""
from __future__ import annotations

import importlib.util
import sys
from collections import deque
from pathlib import Path


BASE_PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_매도흡수_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_absorption_base", BASE_PATH)
assert SPEC and SPEC.loader
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)

BASE.OUT_DETAIL = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_1분봉_상세.csv"
BASE.OUT_SUMMARY = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_1분봉_요약.csv"
BASE.OUT_JSON = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_1분봉_요약.json"

RULES = {}
for ratio in (0.6, 0.7, 0.8):
    for suffix, wick_required, book_rule in (
        ("PRICE", False, "none"),
        ("WICK", True, "none"),
        ("WICK_BOOK", True, "bid_over_ask"),
        ("WICK_BID_HOLD", True, "bid_hold"),
    ):
        name = f"ABSORB_R{ratio:g}_{suffix}_3_10"
        RULES[name] = (ratio, wick_required, book_rule)

BASE.CANDIDATES = tuple(
    BASE.Candidate(name, "absorption_07", 10.0, book_rule)
    for name, (_, _, book_rule) in RULES.items()
)


def update_minute_bar(bars: dict, point) -> str:
    key = point.ts.strftime("%Y%m%d-%H%M")
    if key not in bars:
        bars[key] = {
            "open": point.price,
            "high": point.price,
            "low": point.price,
            "close": point.price,
        }
    else:
        bar = bars[key]
        bar["high"] = max(bar["high"], point.price)
        bar["low"] = min(bar["low"], point.price)
        bar["close"] = point.price
    return key


def wick_state(bar: dict) -> dict:
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    lower = max(0.0, body_bottom - bar["low"])
    upper = max(0.0, bar["high"] - body_top)
    price_range = bar["high"] - bar["low"]
    return {
        "lower_wick": lower,
        "upper_wick": upper,
        "lower_gt_upper": lower > upper,
        "lower_wick_share": lower / price_range if price_range > 0 else 0.0,
        "upper_wick_share": upper / price_range if price_range > 0 else 0.0,
        "close_position": (
            (bar["close"] - bar["low"]) / price_range
            if price_range > 0
            else 0.5
        ),
    }


def first_signal(event: dict, points: list, candidate) -> dict | None:
    ratio_limit, wick_required, book_rule = RULES[candidate.name]
    armed = False
    low_price = 0.0
    low_ts = None
    reset_ts = None
    reset_che = reset_ask = reset_bid = 0.0
    base_buy = base_sell = prior_buy = prior_sell = None
    recent = deque(maxlen=2)
    minute_bars = {}
    anchor_minute_key = ""

    for point in points:
        if point.ts.time() >= BASE.ENTRY_END:
            break
        minute_key = update_minute_bar(minute_bars, point)
        drop_pct = (point.price / event["previous_close"] - 1.0) * 100.0
        new_low = False
        if not armed and drop_pct <= BASE.ARM_DROP_PCT:
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
            base_buy = point.buy_vol_cum if BASE.is_exact(point) else None
            base_sell = point.sell_vol_cum if BASE.is_exact(point) else None
            prior_buy = base_buy
            prior_sell = base_sell
            anchor_minute_key = minute_key
            recent.clear()
            recent.append(point)
            continue
        if not armed or low_ts is None or reset_ts is None:
            continue
        if not BASE.is_exact(point):
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
            recent.clear()
            recent.append(point)
            continue
        prior_buy = point.buy_vol_cum
        prior_sell = point.sell_vol_cum
        buy_volume = point.buy_vol_cum - base_buy
        sell_volume = point.sell_vol_cum - base_sell
        total_volume = buy_volume + sell_volume
        elapsed = (point.ts - reset_ts).total_seconds()
        recent.append(point)
        holds = (
            len(recent) == 2
            and recent[0].price > low_price
            and recent[1].price > low_price
            and recent[1].price >= recent[0].price
        )
        ratio = buy_volume / sell_volume if sell_volume > 0 else None
        wick = wick_state(minute_bars[anchor_minute_key])
        book_ok = BASE.book_pass(book_rule, point, reset_ask, reset_bid)
        if not (
            3.0 <= elapsed <= candidate.max_sec
            and point.price >= BASE.MIN_PRICE
            and total_volume > 0
            and sell_volume > buy_volume
            and ratio is not None
            and ratio <= ratio_limit
            and holds
            and (not wick_required or wick["lower_gt_upper"])
            and book_ok
        ):
            continue
        return {
            "signal_ts": point.ts,
            "signal_price": point.price,
            "anchor_low_ts": low_ts,
            "anchor_low_price": low_price,
            "elapsed_sec": elapsed,
            "buy_exec_volume": buy_volume,
            "sell_exec_volume": sell_volume,
            "net_exec_volume": buy_volume - sell_volume,
            "buy_sell_ratio": ratio,
            "che_change": point.che_str - reset_che,
            "bid_ask_ratio": point.bid_tot / point.ask_tot if point.ask_tot > 0 else None,
            "bid_change": point.bid_tot - reset_bid,
            "ask_change": point.ask_tot - reset_ask,
            "signal_type": "ABSORPTION",
            "lower_wick_share": wick["lower_wick_share"],
            "upper_wick_share": wick["upper_wick_share"],
            "close_position": wick["close_position"],
        }
    return None


BASE.first_signal = first_signal


if __name__ == "__main__":
    BASE.run()

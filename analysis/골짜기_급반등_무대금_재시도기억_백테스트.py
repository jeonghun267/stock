# -*- coding: utf-8 -*-
"""체결대금 하한 없이 실패한 반등 후보 횟수를 기억하는 주문0 재생."""
from __future__ import annotations

import importlib.util
import sys
from collections import deque
from pathlib import Path


BASE_PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_매도흡수_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_no_money_base", BASE_PATH)
assert SPEC and SPEC.loader
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)

BASE.OUT_DETAIL = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_재시도기억_상세.csv"
BASE.OUT_SUMMARY = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_재시도기억_요약.csv"
BASE.OUT_JSON = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_재시도기억_요약.json"

RULES = {
    "RETRY1_ONLY_3_10": (1, None),
    "RETRY1_OR_FLOW2_3_10": (1, 2.0),
    "RETRY1_OR_FLOW3_3_10": (1, 3.0),
    "RETRY1_OR_FLOW5_3_10": (1, 5.0),
    "RETRY2_OR_FLOW3_3_10": (2, 3.0),
    "RETRY3_OR_FLOW3_3_10": (3, 3.0),
    "RETRY4_OR_FLOW3_3_10": (4, 3.0),
    "RETRY5_OR_FLOW3_3_10": (5, 3.0),
}
BASE.CANDIDATES = tuple(
    BASE.Candidate(name, "retry_combined", 10.0, "bid_over_ask")
    for name in RULES
)


def first_signal(event: dict, points: list, candidate) -> dict | None:
    min_failed, strong_ratio = RULES[candidate.name]
    armed = False
    low_price = 0.0
    low_ts = None
    reset_ts = None
    reset_che = reset_ask = reset_bid = 0.0
    base_buy = base_sell = prior_buy = prior_sell = None
    recent = deque(maxlen=2)
    tentative = False
    failed_rebounds = 0

    for point in points:
        if point.ts.time() >= BASE.ENTRY_END:
            break
        drop_pct = (point.price / event["previous_close"] - 1.0) * 100.0
        new_low = False
        if not armed and drop_pct <= BASE.ARM_DROP_PCT:
            armed = True
            new_low = True
        elif armed and point.price < low_price:
            new_low = True
        if new_low:
            if tentative:
                failed_rebounds += 1
            tentative = False
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
        net_volume = buy_volume - sell_volume
        elapsed = (point.ts - reset_ts).total_seconds()
        recent.append(point)
        holds = (
            len(recent) == 2
            and recent[0].price > low_price
            and recent[1].price > low_price
            and recent[1].price >= recent[0].price
        )
        flow = (
            total_volume > 0
            and net_volume > 0
            and point.che_str > reset_che > 0
        )
        absorption = (
            total_volume > 0
            and net_volume < 0
            and point.bid_tot > point.ask_tot
        )
        if not (
            3.0 <= elapsed <= candidate.max_sec
            and point.price >= BASE.MIN_PRICE
            and holds
            and (flow or absorption)
        ):
            continue
        ratio = buy_volume / sell_volume if sell_volume > 0 else None
        direct_strong = (
            flow
            and strong_ratio is not None
            and (
                sell_volume == 0 < buy_volume
                or (ratio is not None and ratio >= strong_ratio)
            )
        )
        if failed_rebounds < min_failed and not direct_strong:
            tentative = True
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
            "buy_sell_ratio": ratio,
            "che_change": point.che_str - reset_che,
            "bid_ask_ratio": point.bid_tot / point.ask_tot if point.ask_tot > 0 else None,
            "bid_change": point.bid_tot - reset_bid,
            "ask_change": point.ask_tot - reset_ask,
            "signal_type": "FLOW" if flow else "ABSORPTION",
            "failed_rebounds_before_signal": failed_rebounds,
        }
    return None


BASE.first_signal = first_signal


if __name__ == "__main__":
    BASE.run()

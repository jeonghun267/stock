# -*- coding: utf-8 -*-
"""0.7 체결량 흡수에 매도호가 감소·호가불균형 개선을 결합한 주문0 재생."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


FOCUSED_PATH = Path(r"C:\stock_bot\analysis\골짜기_급반등_무대금_07흡수_1분봉_백테스트.py")
SPEC = importlib.util.spec_from_file_location("valley_absorption_focused", FOCUSED_PATH)
assert SPEC and SPEC.loader
FOCUSED = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FOCUSED
SPEC.loader.exec_module(FOCUSED)
BASE = FOCUSED.BASE

BASE.OUT_DETAIL = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_호가소진_상세.csv"
BASE.OUT_SUMMARY = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_호가소진_요약.csv"
BASE.OUT_JSON = BASE.ROOT / "analysis" / "골짜기_급반등_무대금_07흡수_호가소진_요약.json"

FOCUSED.RULES = {
    "ABSORB_R0.7_WICK_ASK_DOWN_3_10": (0.7, True, "ask_down"),
    "ABSORB_R0.7_WICK_BOTH_HOLD_3_10": (0.7, True, "both_hold"),
    "ABSORB_R0.7_WICK_IMB_IMPROVE_3_10": (0.7, True, "imbalance_improve"),
    "ABSORB_R0.7_WICK_BOTH_IMPROVE_3_10": (0.7, True, "both_improve"),
}
BASE.CANDIDATES = tuple(
    BASE.Candidate(name, "absorption_07_book", 10.0, book_rule)
    for name, (_, _, book_rule) in FOCUSED.RULES.items()
)


def book_pass(rule: str, point, reset_ask: float, reset_bid: float) -> bool:
    if rule == "ask_down":
        return point.bid_tot > point.ask_tot and point.ask_tot <= reset_ask
    if rule == "both_hold":
        return (
            point.bid_tot > point.ask_tot
            and point.bid_tot >= reset_bid
            and point.ask_tot <= reset_ask
        )
    reset_ratio = reset_bid / reset_ask if reset_ask > 0 else 0.0
    current_ratio = point.bid_tot / point.ask_tot if point.ask_tot > 0 else 0.0
    if rule == "imbalance_improve":
        return point.bid_tot > point.ask_tot and current_ratio > reset_ratio
    if rule == "both_improve":
        return (
            point.bid_tot > point.ask_tot
            and point.bid_tot >= reset_bid
            and point.ask_tot <= reset_ask
            and current_ratio > reset_ratio
        )
    return FOCUSED.BASE.book_pass(rule, point, reset_ask, reset_bid)


BASE.book_pass = book_pass
BASE.first_signal = FOCUSED.first_signal


if __name__ == "__main__":
    BASE.run()

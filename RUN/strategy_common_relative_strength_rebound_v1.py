# -*- coding: utf-8 -*-
"""급락장 상대강도 반등 공통 그림자 판정기.

주문·브로커·실전 허용값을 전혀 다루지 않는다. S02/S03가 이미 읽은 시세를
공통 기준으로 평가해 후보 메타데이터만 돌려주며 주문수량은 항상 0이다.
"""
from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Deque, Mapping


DEFAULT_REGIME_PATH = Path(
    r"C:\stock_bot\data\BACKTEST\regime_std_shadow.csv"
)


@dataclass(frozen=True)
class RelativeStrengthShadowConfig:
    market_max_pct: float = -1.5
    min_relative_strength_pct: float = 2.0
    min_rebound_pct: float = 0.5
    max_rebound_pct: float = 2.0
    min_no_new_low_sec: float = 5.0
    max_spread_bps: float = 35.0
    min_best_bid_share: float = 0.50
    max_gap_sec: float = 60.0
    deep_crash_max_low_pct: float = -10.0
    deep_crash_min_rebound_pct: float = 1.0
    deep_crash_max_rebound_pct: float = 2.0
    deep_crash_min_no_new_low_sec: float = 60.0


@dataclass(frozen=True)
class _Snapshot:
    ts: datetime
    price: float
    buy_money_cum: float
    sell_money_cum: float
    cum_vol: float


@dataclass
class _CodeState:
    day: str = ""
    low: float = 0.0
    low_ts: datetime | None = None
    points: Deque[_Snapshot] = field(default_factory=lambda: deque(maxlen=8))
    last_result: dict[str, Any] = field(default_factory=dict)
    vi_suspect: bool = False
    vi_normal_cum_vol: float = 0.0


_REGIME_CACHE: dict[str, Any] = {"mtime_ns": None, "rows": []}


def read_market_change_pct(
    now: datetime,
    path: Path = DEFAULT_REGIME_PATH,
) -> float | None:
    """장세 그림자 CSV의 당일 최신 u201 등락률을 읽는다."""
    try:
        mtime_ns = path.stat().st_mtime_ns
        if _REGIME_CACHE["mtime_ns"] != mtime_ns:
            rows: list[tuple[datetime, float]] = []
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    try:
                        ts = datetime.fromisoformat(str(raw.get("ts") or ""))
                        value = float(str(raw.get("u201_chg") or "").replace(",", ""))
                    except (TypeError, ValueError):
                        continue
                    rows.append((ts, value))
            _REGIME_CACHE["mtime_ns"] = mtime_ns
            _REGIME_CACHE["rows"] = rows
    except OSError:
        return None
    prior = [
        row for row in _REGIME_CACHE["rows"]
        if row[0].date() == now.date() and row[0] <= now
    ]
    return prior[-1][1] if prior else None


class RelativeStrengthReboundShadow:
    """종목별 관측 상태를 유지하는 주문 0 공통 후보 판정기."""

    def __init__(self, config: RelativeStrengthShadowConfig | None = None) -> None:
        self.config = config or RelativeStrengthShadowConfig()
        self.states: dict[str, _CodeState] = {}

    @staticmethod
    def _flow_turn(points: list[_Snapshot]) -> tuple[bool, int]:
        rates: list[tuple[float, float]] = []
        for prior, current in zip(points, points[1:]):
            seconds = (current.ts - prior.ts).total_seconds()
            buy_delta = current.buy_money_cum - prior.buy_money_cum
            sell_delta = current.sell_money_cum - prior.sell_money_cum
            if seconds > 0 and buy_delta >= 0 and sell_delta >= 0:
                rates.append((buy_delta / seconds, sell_delta / seconds))
        if len(rates) < 3:
            return False, len(rates)
        recent_buy, recent_sell = rates[-1]
        baseline_buy = median(row[0] for row in rates[-4:-1])
        return bool(recent_buy > recent_sell and recent_buy > baseline_buy), len(rates)

    def evaluate(
        self,
        *,
        code: str,
        ts: datetime,
        price: float,
        previous_close: float,
        market_pct: float | None,
        buy_money_cum: float,
        sell_money_cum: float,
        best_ask_px: float,
        best_bid_px: float,
        best_ask_qty: float,
        best_bid_qty: float,
        high_range_meta: Mapping[str, Any] | None = None,
        cum_vol: float = 0.0,
        deep_crash_enabled: bool = False,
    ) -> dict[str, Any]:
        state = self.states.setdefault(str(code).zfill(6), _CodeState())
        day = ts.strftime("%Y%m%d")
        if state.day != day:
            state.day = day
            state.low = 0.0
            state.low_ts = None
            state.points.clear()
            state.last_result = {}
            state.vi_suspect = False
            state.vi_normal_cum_vol = 0.0
        if state.points and ts <= state.points[-1].ts:
            return dict(state.last_result)
        if state.points and (
            (ts - state.points[-1].ts).total_seconds() > self.config.max_gap_sec
            or buy_money_cum < state.points[-1].buy_money_cum
            or sell_money_cum < state.points[-1].sell_money_cum
        ):
            state.points.clear()
            state.low = 0.0
            state.low_ts = None
            state.vi_suspect = False
            state.vi_normal_cum_vol = 0.0

        previous_point = state.points[-1] if state.points else None
        if previous_point and previous_point.cum_vol > 0 and cum_vol > 0:
            if not state.vi_suspect and cum_vol < previous_point.cum_vol * 0.5:
                state.vi_suspect = True
                state.vi_normal_cum_vol = previous_point.cum_vol
            elif (
                state.vi_suspect
                and state.vi_normal_cum_vol > 0
                and cum_vol >= state.vi_normal_cum_vol
            ):
                state.vi_suspect = False

        state.points.append(_Snapshot(
            ts=ts,
            price=float(price),
            buy_money_cum=float(buy_money_cum),
            sell_money_cum=float(sell_money_cum),
            cum_vol=float(cum_vol),
        ))
        if price > 0 and (state.low <= 0 or price < state.low):
            state.low = float(price)
            state.low_ts = ts

        stock_pct = (
            (price / previous_close - 1.0) * 100.0
            if price > 0 and previous_close > 0 else None
        )
        relative_pct = (
            stock_pct - market_pct
            if stock_pct is not None and market_pct is not None else None
        )
        rebound_pct = (
            (price / state.low - 1.0) * 100.0 if state.low > 0 else None
        )
        no_new_low_sec = (
            max(0.0, (ts - state.low_ts).total_seconds())
            if state.low_ts is not None else None
        )
        flow_turn, flow_intervals = self._flow_turn(list(state.points))

        book_valid = (
            best_ask_px > best_bid_px > 0
            and best_ask_qty > 0 and best_bid_qty > 0
        )
        midpoint = (best_ask_px + best_bid_px) / 2.0 if book_valid else 0.0
        spread_bps = (
            (best_ask_px - best_bid_px) / midpoint * 10_000.0
            if midpoint > 0 else None
        )
        best_bid_share = (
            best_bid_qty / (best_bid_qty + best_ask_qty)
            if book_valid else None
        )

        failed: list[str] = []
        if market_pct is None:
            failed.append("MARKET_MISSING")
        elif market_pct > self.config.market_max_pct:
            failed.append("MARKET_NOT_CRASH")
        if relative_pct is None:
            failed.append("RELATIVE_STRENGTH_MISSING")
        elif relative_pct < self.config.min_relative_strength_pct:
            failed.append("RELATIVE_STRENGTH_LOW")
        if rebound_pct is None:
            failed.append("REBOUND_MISSING")
        elif rebound_pct < self.config.min_rebound_pct:
            failed.append("REBOUND_EARLY")
        elif rebound_pct > self.config.max_rebound_pct:
            failed.append("REBOUND_CHASE")
        if no_new_low_sec is None or no_new_low_sec < self.config.min_no_new_low_sec:
            failed.append("NEW_LOW_NOT_STABLE")
        if not flow_turn:
            failed.append("FLOW_TURN_WAIT")
        if not book_valid:
            failed.append("BOOK_MISSING")
        elif spread_bps is not None and spread_bps > self.config.max_spread_bps:
            failed.append("SPREAD_WIDE")
        elif best_bid_share is not None and best_bid_share < self.config.min_best_bid_share:
            failed.append("BID_SUPPORT_LOW")

        meta = high_range_meta or {}
        result = {
            "crs_mode": "SHADOW_ORDER_ZERO",
            "crs_order_qty": 0,
            "crs_live_eligible": False,
            "crs_shadow_candidate": not failed,
            "crs_shadow_reason": "READY" if not failed else "|".join(failed),
            "crs_market_pct": round(market_pct, 4) if market_pct is not None else None,
            "crs_stock_pct": round(stock_pct, 4) if stock_pct is not None else None,
            "crs_relative_strength_pct": (
                round(relative_pct, 4) if relative_pct is not None else None
            ),
            "crs_observed_low": round(state.low, 4) if state.low > 0 else None,
            "crs_observed_low_ts": (
                state.low_ts.isoformat(timespec="milliseconds")
                if state.low_ts is not None else ""
            ),
            "crs_rebound_pct": round(rebound_pct, 4) if rebound_pct is not None else None,
            "crs_no_new_low_sec": (
                round(no_new_low_sec, 3) if no_new_low_sec is not None else None
            ),
            "crs_flow_turn": flow_turn,
            "crs_flow_intervals": flow_intervals,
            "crs_spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
            "crs_best_bid_share": (
                round(best_bid_share, 4) if best_bid_share is not None else None
            ),
            "crs_hr_money_speed_ratio": meta.get("hr_money_speed_ratio"),
            "crs_hr_turnover_pct": meta.get("hr_turnover_pct"),
            "crs_hr_volatility_quality": meta.get("hr_volatility_quality"),
        }
        if deep_crash_enabled:
            low_pct = (
                (state.low / previous_close - 1.0) * 100.0
                if state.low > 0 and previous_close > 0 else None
            )
            deep_failed: list[str] = []
            if not (datetime.min.time().replace(hour=9) <= ts.time()
                    <= datetime.min.time().replace(hour=9, minute=15)):
                deep_failed.append("TIME_OUTSIDE_0900_0915")
            if low_pct is None:
                deep_failed.append("LOW_DEPTH_MISSING")
            elif state.low > previous_close * (
                1.0 + self.config.deep_crash_max_low_pct / 100.0
            ):
                deep_failed.append("LOW_NOT_DEEP_10PCT")
            if rebound_pct is None:
                deep_failed.append("REBOUND_MISSING")
            elif rebound_pct < self.config.deep_crash_min_rebound_pct:
                deep_failed.append("REBOUND_LT_1PCT")
            elif rebound_pct > self.config.deep_crash_max_rebound_pct:
                deep_failed.append("REBOUND_CHASE_GT_2PCT")
            if (
                no_new_low_sec is None
                or no_new_low_sec < self.config.deep_crash_min_no_new_low_sec
            ):
                deep_failed.append("NEW_LOW_NOT_STABLE_60S")
            if not flow_turn:
                deep_failed.append("FLOW_TURN_WAIT")
            if not book_valid:
                deep_failed.append("BOOK_MISSING")
            elif spread_bps is not None and spread_bps > self.config.max_spread_bps:
                deep_failed.append("SPREAD_WIDE")
            elif (
                best_bid_share is not None
                and best_bid_share < self.config.min_best_bid_share
            ):
                deep_failed.append("BID_SUPPORT_LOW")
            if cum_vol <= 0:
                deep_failed.append("VI_STATUS_MISSING")
            elif state.vi_suspect:
                deep_failed.append("VI_ACTIVE")
            result.update({
                "dcr_mode": "S03_DEEP_CRASH_SHADOW_ORDER_ZERO",
                "dcr_order_qty": 0,
                "dcr_live_eligible": False,
                "dcr_shadow_candidate": not deep_failed,
                "dcr_shadow_reason": (
                    "READY" if not deep_failed else "|".join(deep_failed)
                ),
                "dcr_low_pct": round(low_pct, 4) if low_pct is not None else None,
                "dcr_vi_suspect": state.vi_suspect,
            })
        state.last_result = result
        return dict(result)

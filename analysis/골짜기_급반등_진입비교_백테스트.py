# -*- coding: utf-8 -*-
"""골짜기 급반등 진입 방식 비교.

2026-07-23/24 KST 1초 캡처를 사용해 아래 세 진입을 같은 모집단에서 비교한다.
1) 기존 골짜기 MORNING_CRASH FAST + 완성 양봉/60초 정밀경로
2) 전략02의 계단식 하락·매도소진·호가회복
3) 두 신호 중 먼저 유효해진 결합형

신호 생성에는 현재 시점까지의 데이터만 사용한다. 사후 최저가, 재신저가,
MFE/MAE와 종료수익률은 신호가 끝난 뒤 평가에만 사용한다. 주문은 없다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from statistics import median
from typing import Deque, Iterable, Optional, Sequence


ROOT = Path(r"C:\stock_bot")
RUN_DIR = ROOT / "RUN"
sys.path.insert(0, str(RUN_DIR))

# 기존 골짜기 운영값을 외부 환경과 무관하게 고정한다.
os.environ["VLA_GATE1_ARM_PCT"] = "-4"
os.environ["VLA_GATE1_START"] = "0900"
os.environ["VLA_GATE1_END"] = "0920"
os.environ["VLA_GATE1_FAST"] = "YES"
os.environ["VLA_FAST_MIN_SEC"] = "2"
os.environ["VLA_FAST_MAX_SEC"] = "6"
os.environ["VLA_FAST_CONFIRM_SEC"] = "2"
os.environ["VLA_FAST_REBOUND_LO"] = "0.6"
os.environ["VLA_FAST_REBOUND_HI"] = "3.0"
os.environ["VLA_FAST_MIN_MONEY"] = "10000000"
os.environ["VLA_FAST_MIN_BUY_RATIO"] = "0.70"
os.environ["VLA_OBS_PCT_LO"] = "1.0"
os.environ["VLA_OBS_PCT_HI"] = "1.5"
os.environ["VLA_WATCH_MIN"] = "60"

from valley_low_buy_v1 import LowAnchor  # noqa: E402
from 저점매수_매도소진 import (  # noqa: E402
    BottomSignal,
    MarketPoint,
    detect_flow_book_exhaustion,
)


KST_ENTRY_START = time(9, 0)
KST_ENTRY_END = time(9, 20)
KST_EVALUATION_END = time(15, 20)
ARM_DROP_PCT = -4.0
MIN_SIGNAL_PRICE = 10_000.0
PREV_VALUE_MIN_EOK = 100.0
PREV_VALUE_MAX_EOK = 20_000.0
MARKET_CAP_MIN_EOK = 1_000.0
HARD_STOP_PCT = -2.0
ROUND_TRIP_FEES_TAX_PCT = 0.21
ASSUMED_ROUND_TRIP_SLIPPAGE_PCT = 0.10
DEFAULT_DAYS = ("20260723", "20260724")

RAW_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
EOD_PATH = ROOT / "data" / "eod_daily_bars.csv"
SHARES_PATH = ROOT / "data" / "shares_outstanding.csv"
OUT_CSV = ROOT / "analysis" / "골짜기_급반등_진입비교.csv"
OUT_JSON = ROOT / "analysis" / "골짜기_급반등_진입비교_요약.json"


@dataclass(frozen=True, slots=True)
class UniverseRow:
    code: str
    name: str
    previous_date: str
    previous_close: float
    previous_value_eok: float
    market_cap_eok: float


@dataclass(frozen=True, slots=True)
class ReplayPoint:
    ts: datetime
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float
    bid_tot: float
    buy_money_cum: float
    sell_money_cum: float

    def as_market_point(self) -> MarketPoint:
        return MarketPoint(
            ts=self.ts,
            price=self.price,
            cum_vol=self.cum_vol,
            che_str=self.che_str,
            ask_tot=self.ask_tot,
            bid_tot=self.bid_tot,
            buy_money_cum=self.buy_money_cum,
            sell_money_cum=self.sell_money_cum,
        )


@dataclass(frozen=True, slots=True)
class EntrySignal:
    algorithm: str
    ts: datetime
    price: float
    anchor_low_ts: datetime
    anchor_low_price: float
    reason: str


@dataclass
class DayReplay:
    day: str
    universe: dict[str, UniverseRow]
    morning: dict[str, list[ReplayPoint]]
    outcome_prices: dict[str, list[tuple[datetime, float]]]
    armed_codes: set[str]
    quality: dict[str, object]


class CompletedMinuteBars:
    """현재 시점 이전에 끝난 1분봉만 LowAnchor 형식으로 제공한다."""

    def __init__(self) -> None:
        self.minute_key = ""
        self.current: Optional[list[float]] = None
        self.completed: Deque[tuple[list[float], float]] = deque(maxlen=15)

    def update(self, point: ReplayPoint) -> dict[str, list]:
        minute_key = point.ts.strftime("%H%M")
        if self.minute_key and minute_key != self.minute_key and self.current:
            o, h, low, close, start_vol, end_vol = self.current
            self.completed.append(([o, h, low, close], max(0.0, end_vol - start_vol)))
            self.current = None
        if self.current is None:
            self.minute_key = minute_key
            self.current = [
                point.price,
                point.price,
                point.price,
                point.price,
                point.cum_vol,
                point.cum_vol,
            ]
        else:
            self.current[1] = max(self.current[1], point.price)
            self.current[2] = min(self.current[2], point.price)
            self.current[3] = point.price
            self.current[5] = point.cum_vol
        return {
            "prev": [bar for bar, _ in self.completed],
            "pv": [volume for _, volume in self.completed],
        }


def _number(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _previous_trading_dates(days: Sequence[str]) -> dict[str, str]:
    available: set[str] = set()
    with EOD_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = str(row.get("date") or "")
            if value:
                available.add(value)
    result: dict[str, str] = {}
    for day in days:
        candidates = [value for value in available if value < day]
        if not candidates:
            raise RuntimeError(f"{day} 이전 거래일 일봉이 없습니다.")
        result[day] = max(candidates)
    return result


def _share_counts() -> dict[str, float]:
    result: dict[str, float] = {}
    with SHARES_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").zfill(6)
            shares = _number(row.get("shares") or "0")
            if len(code) == 6 and shares > 0:
                result[code] = shares
    return result


def load_universes(days: Sequence[str]) -> dict[str, dict[str, UniverseRow]]:
    previous_dates = _previous_trading_dates(days)
    target_dates = set(previous_dates.values())
    shares = _share_counts()
    by_previous_date: dict[str, dict[str, UniverseRow]] = defaultdict(dict)
    with EOD_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            previous_date = str(row.get("date") or "")
            if previous_date not in target_dates:
                continue
            code = str(row.get("code") or "").zfill(6)
            name = str(row.get("name") or "").strip()
            close = _number(row.get("close") or "0")
            value_eok = _number(row.get("value") or "0") / 100.0
            market_cap_eok = shares.get(code, 0.0) * close / 100_000_000.0
            if not (
                str(row.get("market") or "") == "KOSDAQ"
                and len(code) == 6
                and code.isdigit()
                and code.endswith("0")
                and "스팩" not in name
                and close > 0
                and PREV_VALUE_MIN_EOK <= value_eok <= PREV_VALUE_MAX_EOK
                and market_cap_eok >= MARKET_CAP_MIN_EOK
            ):
                continue
            by_previous_date[previous_date][code] = UniverseRow(
                code=code,
                name=name or code,
                previous_date=previous_date,
                previous_close=close,
                previous_value_eok=value_eok,
                market_cap_eok=market_cap_eok,
            )
    return {
        day: by_previous_date[previous_dates[day]]
        for day in days
    }


def _raw_path(day: str) -> Path:
    path = RAW_DIR / f"mf_1s_{day}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _parse_replay_point(parts: list[str], index: dict[str, int]) -> Optional[ReplayPoint]:
    try:
        ts = datetime.fromisoformat(parts[index["ts"]])
    except (ValueError, IndexError):
        return None
    price = _number(parts[index["current_price"]])
    if price <= 0:
        return None
    return ReplayPoint(
        ts=ts,
        price=price,
        cum_vol=_number(parts[index["cum_vol"]]),
        che_str=_number(parts[index["che_str"]]),
        ask_tot=_number(parts[index["ask_tot"]], -1.0),
        bid_tot=_number(parts[index["bid_tot"]], -1.0),
        buy_money_cum=_number(parts[index["buy_money_cum"]], -1.0),
        sell_money_cum=_number(parts[index["sell_money_cum"]], -1.0),
    )


def load_day_replay(day: str, universe: dict[str, UniverseRow]) -> DayReplay:
    morning: dict[str, list[ReplayPoint]] = defaultdict(list)
    outcome_prices: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    armed_codes: set[str] = set()
    last_point: dict[str, ReplayPoint] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    min_ts: Optional[datetime] = None
    max_ts: Optional[datetime] = None

    with _raw_path(day).open(encoding="utf-8-sig", errors="replace") as handle:
        header = handle.readline().rstrip("\r\n").split(",")
        fields = (
            "ts",
            "code",
            "current_price",
            "cum_vol",
            "che_str",
            "ask_tot",
            "bid_tot",
            "buy_money_cum",
            "sell_money_cum",
        )
        index = {name: header.index(name) for name in fields}
        max_index = max(index.values())
        for line in handle:
            stats["raw_rows"] += 1
            first = line.find(",")
            second = line.find(",", first + 1)
            if first < 0 or second < 0:
                stats["malformed_rows"] += 1
                continue
            code = line[first + 1 : second].strip().zfill(6)
            if code not in universe:
                continue
            stats["universe_rows"] += 1
            parts = line.rstrip("\r\n").split(",", max_index + 1)
            if len(parts) <= max_index:
                stats["malformed_rows"] += 1
                continue
            point = _parse_replay_point(parts, index)
            if point is None:
                stats["invalid_price_or_time_rows"] += 1
                continue
            if point.ts.strftime("%Y%m%d") != day:
                stats["date_mismatch_rows"] += 1
                continue
            if point.ts.time() < KST_ENTRY_START or point.ts.time() > KST_EVALUATION_END:
                continue
            min_ts = point.ts if min_ts is None else min(min_ts, point.ts)
            max_ts = point.ts if max_ts is None else max(max_ts, point.ts)
            previous = last_point.get(code)
            if previous and point.ts <= previous.ts:
                stats["duplicate_or_out_of_order_rows"] += 1
                continue
            if previous:
                gap = (point.ts - previous.ts).total_seconds()
                if gap > 10:
                    stats["gaps_over_10s"] += 1
                if (
                    point.buy_money_cum >= 0
                    and point.sell_money_cum >= 0
                    and (
                        point.buy_money_cum < previous.buy_money_cum
                        or point.sell_money_cum < previous.sell_money_cum
                    )
                ):
                    stats["cumulative_reversals"] += 1
            last_point[code] = point

            if KST_ENTRY_START <= point.ts.time() < KST_ENTRY_END:
                morning[code].append(point)
                stats["morning_rows"] += 1
                if (
                    point.ask_tot > 0
                    and point.bid_tot > 0
                    and point.buy_money_cum >= 0
                    and point.sell_money_cum >= 0
                ):
                    stats["morning_exact_rows"] += 1
                drop_pct = (
                    point.price / universe[code].previous_close - 1.0
                ) * 100.0
                if drop_pct <= ARM_DROP_PCT:
                    armed_codes.add(code)
            if code in armed_codes:
                outcome_prices[code].append((point.ts, point.price))

    exact_rate = (
        stats["morning_exact_rows"] / stats["morning_rows"] * 100.0
        if stats["morning_rows"]
        else 0.0
    )
    quality: dict[str, object] = dict(stats)
    quality.update(
        {
            "source": str(_raw_path(day)),
            "source_bytes": _raw_path(day).stat().st_size,
            "universe_codes": len(universe),
            "morning_codes_covered": sum(bool(morning.get(code)) for code in universe),
            "armed_codes": len(armed_codes),
            "morning_exact_rate_pct": round(exact_rate, 4),
            "min_timestamp": min_ts.isoformat(timespec="milliseconds") if min_ts else "",
            "max_timestamp": max_ts.isoformat(timespec="milliseconds") if max_ts else "",
        }
    )
    return DayReplay(
        day=day,
        universe=universe,
        morning=dict(morning),
        outcome_prices=dict(outcome_prices),
        armed_codes=armed_codes,
        quality=quality,
    )


def _current_valley_signal(
    code: str,
    previous_close: float,
    points: Sequence[ReplayPoint],
) -> Optional[EntrySignal]:
    anchor = LowAnchor(code)
    bars = CompletedMinuteBars()
    for point in points:
        bar_payload = bars.update(point)
        side_exact = (
            point.buy_money_cum >= 0 and point.sell_money_cum >= 0
        )
        event = anchor.feed(
            point.ts.strftime("%H%M"),
            point.price,
            point.cum_vol,
            point.ts.timestamp(),
            0.0,
            bar_payload,
            None,
            None,
            None,
            point.che_str,
            prev_close=previous_close,
            buy_money_cum=point.buy_money_cum,
            sell_money_cum=point.sell_money_cum,
            side_exact=side_exact,
        )
        if not event or event.get("signal") != "BUY":
            continue
        if point.price < MIN_SIGNAL_PRICE:
            anchor.done = False
            continue
        return EntrySignal(
            algorithm="CURRENT_VALLEY",
            ts=point.ts,
            price=point.price,
            anchor_low_ts=datetime.fromtimestamp(
                anchor.reset_ts or point.ts.timestamp()
            ),
            anchor_low_price=float(event.get("observation_low") or point.price),
            reason=str(event.get("reason") or ""),
        )
    return None


def _strategy02_signal(
    previous_close: float,
    points: Sequence[ReplayPoint],
) -> Optional[EntrySignal]:
    window: Deque[MarketPoint] = deque(maxlen=360)
    armed = False
    for point in points:
        if (point.price / previous_close - 1.0) * 100.0 <= ARM_DROP_PCT:
            armed = True
        if not (
            point.price >= MIN_SIGNAL_PRICE
            and point.ask_tot > 0
            and point.bid_tot > 0
            and point.buy_money_cum >= 0
            and point.sell_money_cum >= 0
        ):
            continue
        current = point.as_market_point()
        if window:
            previous = window[-1]
            if (
                (current.ts - previous.ts).total_seconds() > 10
                or current.buy_money_cum < previous.buy_money_cum
                or current.sell_money_cum < previous.sell_money_cum
            ):
                window.clear()
        window.append(current)
        cutoff = current.ts.timestamp() - 300.0
        while window and window[0].ts.timestamp() < cutoff:
            window.popleft()
        if not armed:
            continue
        detected: Optional[BottomSignal] = detect_flow_book_exhaustion(list(window))
        if detected is None:
            continue
        if abs((current.ts - detected.signal_ts).total_seconds()) > 1.5:
            continue
        return EntrySignal(
            algorithm="S02_EXHAUSTION",
            ts=detected.signal_ts,
            price=detected.signal_price,
            anchor_low_ts=detected.anchor_low_ts,
            anchor_low_price=detected.anchor_low_price,
            reason=detected.reason,
        )
    return None


def _first_signal(
    current: Optional[EntrySignal],
    strategy02: Optional[EntrySignal],
) -> Optional[EntrySignal]:
    available = [signal for signal in (current, strategy02) if signal is not None]
    if not available:
        return None
    selected = min(available, key=lambda signal: signal.ts)
    return EntrySignal(
        algorithm="HYBRID_FIRST",
        ts=selected.ts,
        price=selected.price,
        anchor_low_ts=selected.anchor_low_ts,
        anchor_low_price=selected.anchor_low_price,
        reason=f"{selected.algorithm}:{selected.reason}",
    )


def _event_labels(
    points: Sequence[ReplayPoint],
    previous_close: float,
) -> dict[str, object]:
    armed_idx = next(
        (
            idx
            for idx, point in enumerate(points)
            if (point.price / previous_close - 1.0) * 100.0 <= ARM_DROP_PCT
        ),
        None,
    )
    if armed_idx is None:
        return {
            "armed_at": "",
            "morning_low": None,
            "morning_low_at": "",
            "quick_v_rebound": False,
            "redrop_after_rebound": False,
            "actionable_rebound_1pct": False,
        }
    armed_points = list(points[armed_idx:])
    low_point = min(armed_points, key=lambda point: point.price)
    quick = False
    redrop = False
    running_low = armed_points[0].price
    recovered = False
    for idx, point in enumerate(armed_points):
        if point.price < running_low:
            if recovered:
                redrop = True
            running_low = point.price
            recovered = False
        if point.price >= running_low * 1.006:
            recovered = True
        window_end = point.ts.timestamp() + 10.0
        if any(
            later.ts.timestamp() <= window_end and later.price >= point.price * 1.006
            for later in armed_points[idx + 1 :]
        ):
            quick = True
    low_idx = armed_points.index(low_point)
    actionable = any(
        point.price >= low_point.price * 1.01
        for point in armed_points[low_idx + 1 :]
    )
    return {
        "armed_at": armed_points[0].ts.isoformat(timespec="milliseconds"),
        "morning_low": low_point.price,
        "morning_low_at": low_point.ts.isoformat(timespec="milliseconds"),
        "quick_v_rebound": quick,
        "redrop_after_rebound": redrop,
        "actionable_rebound_1pct": actionable,
    }


def _evaluate_entry(
    signal: Optional[EntrySignal],
    outcome_prices: Sequence[tuple[datetime, float]],
    labels: dict[str, object],
) -> dict[str, object]:
    base = {
        "signal": "YES" if signal else "NO",
        "signal_ts": signal.ts.isoformat(timespec="milliseconds") if signal else "",
        "signal_price": signal.price if signal else None,
        "anchor_low": signal.anchor_low_price if signal else None,
        "anchor_low_ts": (
            signal.anchor_low_ts.isoformat(timespec="milliseconds") if signal else ""
        ),
        "signal_reason": signal.reason if signal else "",
        "signal_after_morning_low_sec": None,
        "post_signal_new_low": None,
        "hard_stop": None,
        "target_1pct_before_stop": None,
        "target_2pct_before_stop": None,
        "mfe_before_exit_pct": None,
        "mae_before_exit_pct": None,
        "gross_stop_or_1520_pct": None,
        "net_fees_tax_pct": None,
        "net_with_slippage_pct": None,
        "exit_ts": "",
        "exit_price": None,
    }
    if signal is None or not outcome_prices:
        return base
    timestamps = [item[0] for item in outcome_prices]
    start = bisect_left(timestamps, signal.ts)
    if start >= len(outcome_prices):
        return base
    future = list(outcome_prices[start:])
    stop_level = signal.price * (1.0 + HARD_STOP_PCT / 100.0)
    stop_idx = next(
        (idx for idx, (_, price) in enumerate(future) if price <= stop_level),
        None,
    )
    exit_idx = stop_idx if stop_idx is not None else len(future) - 1
    path = future[: exit_idx + 1]
    exit_ts, exit_price = future[exit_idx]
    returns = [(price / signal.price - 1.0) * 100.0 for _, price in path]
    morning_low_at = datetime.fromisoformat(str(labels["morning_low_at"]))
    base.update(
        {
            "signal_after_morning_low_sec": round(
                (signal.ts - morning_low_at).total_seconds(), 3
            ),
            "post_signal_new_low": (
                min(price for _, price in future) < signal.anchor_low_price
            ),
            "hard_stop": stop_idx is not None,
            "target_1pct_before_stop": max(returns) >= 1.0,
            "target_2pct_before_stop": max(returns) >= 2.0,
            "mfe_before_exit_pct": round(max(returns), 4),
            "mae_before_exit_pct": round(min(returns), 4),
            "gross_stop_or_1520_pct": round(
                (exit_price / signal.price - 1.0) * 100.0, 4
            ),
            "net_fees_tax_pct": round(
                (exit_price / signal.price - 1.0) * 100.0
                - ROUND_TRIP_FEES_TAX_PCT,
                4,
            ),
            "net_with_slippage_pct": round(
                (exit_price / signal.price - 1.0) * 100.0
                - ROUND_TRIP_FEES_TAX_PCT
                - ASSUMED_ROUND_TRIP_SLIPPAGE_PCT,
                4,
            ),
            "exit_ts": exit_ts.isoformat(timespec="milliseconds"),
            "exit_price": exit_price,
        }
    )
    return base


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 2) if denominator else 0.0


def _median(rows: Iterable[dict], key: str) -> Optional[float]:
    values = [
        float(row[key])
        for row in rows
        if row.get(key) is not None and row.get("signal") == "YES"
    ]
    return round(median(values), 4) if values else None


def summarize_algorithm(rows: list[dict], algorithm: str) -> dict[str, object]:
    selected = [row for row in rows if row["algorithm"] == algorithm]
    signals = [row for row in selected if row["signal"] == "YES"]
    quick_events = [row for row in selected if row["quick_v_rebound"]]
    redrop_events = [row for row in selected if row["redrop_after_rebound"]]
    actionable = [row for row in selected if row["actionable_rebound_1pct"]]
    return {
        "armed_events": len(selected),
        "signals": len(signals),
        "signal_coverage_pct": _pct(len(signals), len(selected)),
        "quick_v_events": len(quick_events),
        "quick_v_captured": sum(row["signal"] == "YES" for row in quick_events),
        "quick_v_capture_pct": _pct(
            sum(row["signal"] == "YES" for row in quick_events), len(quick_events)
        ),
        "redrop_events": len(redrop_events),
        "redrop_captured": sum(row["signal"] == "YES" for row in redrop_events),
        "redrop_capture_pct": _pct(
            sum(row["signal"] == "YES" for row in redrop_events), len(redrop_events)
        ),
        "actionable_1pct_events": len(actionable),
        "missed_actionable_events": sum(row["signal"] == "NO" for row in actionable),
        "post_signal_new_low_pct": _pct(
            sum(bool(row["post_signal_new_low"]) for row in signals), len(signals)
        ),
        "hard_stop_pct": _pct(
            sum(bool(row["hard_stop"]) for row in signals), len(signals)
        ),
        "target_1pct_before_stop_pct": _pct(
            sum(bool(row["target_1pct_before_stop"]) for row in signals), len(signals)
        ),
        "target_2pct_before_stop_pct": _pct(
            sum(bool(row["target_2pct_before_stop"]) for row in signals), len(signals)
        ),
        "net_positive_pct": _pct(
            sum((row["net_with_slippage_pct"] or -999) > 0 for row in signals),
            len(signals),
        ),
        "median_signal_delay_from_morning_low_sec": _median(
            signals, "signal_after_morning_low_sec"
        ),
        "median_mfe_before_exit_pct": _median(signals, "mfe_before_exit_pct"),
        "median_mae_before_exit_pct": _median(signals, "mae_before_exit_pct"),
        "median_net_with_slippage_pct": _median(
            signals, "net_with_slippage_pct"
        ),
    }


def compare_day(replay: DayReplay) -> list[dict]:
    rows: list[dict] = []
    for code in sorted(replay.armed_codes):
        points = replay.morning.get(code, [])
        if not points:
            continue
        universe = replay.universe[code]
        labels = _event_labels(points, universe.previous_close)
        current = _current_valley_signal(code, universe.previous_close, points)
        strategy02 = _strategy02_signal(universe.previous_close, points)
        hybrid = _first_signal(current, strategy02)
        for algorithm, signal in (
            ("CURRENT_VALLEY", current),
            ("S02_EXHAUSTION", strategy02),
            ("HYBRID_FIRST", hybrid),
        ):
            row = {
                "day": replay.day,
                "code": code,
                "name": universe.name,
                "algorithm": algorithm,
                "previous_date": universe.previous_date,
                "previous_close": universe.previous_close,
                "previous_value_eok": round(universe.previous_value_eok, 2),
                "market_cap_eok": round(universe.market_cap_eok, 2),
                **labels,
                **_evaluate_entry(
                    signal,
                    replay.outcome_prices.get(code, []),
                    labels,
                ),
            }
            rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError("비교 가능한 -4% 무장 이벤트가 없습니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(days: Sequence[str], out_csv: Path, out_json: Path) -> dict:
    universes = load_universes(days)
    all_rows: list[dict] = []
    quality: dict[str, dict] = {}
    for day in days:
        replay = load_day_replay(day, universes[day])
        quality[day] = replay.quality
        day_rows = compare_day(replay)
        all_rows.extend(day_rows)
        print(
            f"[{day}] 유니버스 {len(universes[day])} · "
            f"-4% 무장 {len(replay.armed_codes)} · 비교행 {len(day_rows)}",
            flush=True,
        )
    _write_csv(out_csv, all_rows)
    algorithms = {
        name: summarize_algorithm(all_rows, name)
        for name in ("CURRENT_VALLEY", "S02_EXHAUSTION", "HYBRID_FIRST")
    }
    summary = {
        "title": "골짜기 급반등 진입 비교",
        "period": list(days),
        "timezone": "Asia/Seoul",
        "decision": "기존 골짜기, 전략02식 매도소진, 결합형 중 1회 진입 방식 선택",
        "entry_window": "09:00 이상 09:20 미만",
        "evaluation_exit": "-2% 하드스톱 또는 15:20 마지막 관측가",
        "fees_tax_pct": ROUND_TRIP_FEES_TAX_PCT,
        "assumed_round_trip_slippage_pct": ASSUMED_ROUND_TRIP_SLIPPAGE_PCT,
        "universe": (
            "코스닥 6자리 보통주·스팩 제외·신호가 1만원 이상·"
            "전일대금 100억~2조·전일종가 기준 시총 1000억 이상·-4% 무장"
        ),
        "lookahead_policy": (
            "신호는 각 시점까지의 데이터만 사용. 사후 최저가와 손익 경로는 평가에만 사용."
        ),
        "data_quality": quality,
        "algorithms": algorithms,
        "output_csv": str(out_csv),
        "source_files": [str(_raw_path(day)) for day in days],
        "source_eod": str(EOD_PATH),
        "source_shares": str(SHARES_PATH),
    }
    out_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(algorithms, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", nargs="+", default=list(DEFAULT_DAYS))
    parser.add_argument("--out-csv", type=Path, default=OUT_CSV)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = parser.parse_args()
    run(tuple(args.days), args.out_csv, args.out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

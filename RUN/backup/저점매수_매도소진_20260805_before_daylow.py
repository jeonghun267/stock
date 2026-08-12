# -*- coding: utf-8 -*-
"""저점매수 매도소진 — 주문 없는 순수 저점 탐지기.

목적
----
고점에서 계단식으로 하락하는 종목에서 양봉 수나 1~2틱 반등을 사용하지 않고,
각 하락 파동의 매도 압력이 가격을 밀어내는 효율이 약해진 뒤 깨진 저점을
회복하는 순간만 저점매수 후보로 반환한다.

이 모듈은 주문·매도·수익률을 다루지 않는다. 모든 입력은 관측 시점까지의
데이터만 사용하며, 미래 최저가는 별도 백테스트 평가기에서만 사용한다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import median
from typing import Deque, Optional, Sequence


@dataclass(frozen=True)
class MarketPoint:
    ts: datetime
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float
    bid_tot: float
    buy_money_cum: float
    sell_money_cum: float
    buy_vol_cum: float = -1.0
    sell_vol_cum: float = -1.0
    best_ask_px: float = 0.0
    best_bid_px: float = 0.0
    best_ask_qty: float = 0.0
    best_bid_qty: float = 0.0


@dataclass(frozen=True)
class BottomSignal:
    algorithm: str
    signal_ts: datetime
    signal_price: float
    anchor_low_ts: datetime
    anchor_low_price: float
    wave_count: int
    reason: str


@dataclass(frozen=True)
class SellExhaustionConfig:
    min_depth_pct: float = 2.0
    noise_floor_pct: float = 0.25
    noise_cap_pct: float = 0.90
    noise_range_fraction: float = 0.35
    recent_range_sec: float = 60.0
    drop_speed_ratio_max: float = 0.80
    sell_speed_ratio_max: float = 0.80
    sell_impact_ratio_max: float = 0.70
    weakness_required: int = 2
    flow_window_sec: float = 10.0
    min_buy_money_share: float = 0.55
    min_buy_dominant_fraction: float = 0.60
    min_flow_observations: int = 5
    max_entry_above_low_pct: float = 1.50


@dataclass(frozen=True)
class FlowBookExhaustionConfig:
    prior_flow_window_sec: float = 10.0
    recent_flow_window_sec: float = 5.0
    min_window_observations: int = 3
    min_sell_pressure_improvement: float = 0.10
    min_prior_sell_pressure: float = 0.0
    book_window_sec: float = 5.0
    min_book_observations: int = 3
    min_bid_dominant_fraction: float = 0.60
    min_median_book_imbalance: float = 0.10
    min_current_book_imbalance: float = 0.0


@dataclass(frozen=True)
class LegacyPullConfig:
    no_new_low_sec: float = 15.0
    min_depth_pct: float = 2.0
    max_recovery_pct: float = 60.0


@dataclass(frozen=True)
class _Leg:
    high_idx: int
    low_idx: int
    high_price: float
    low_price: float
    drop_pct: float
    duration_sec: float
    drop_speed: float
    sell_money: float
    sell_speed: float
    sell_impact: float


def krx_tick_size(price: float) -> float:
    """2023년 이후 국내 주식 공통 호가단위의 보수적 근사."""
    if price < 2_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 20_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 200_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


def _elapsed(a: MarketPoint, b: MarketPoint) -> float:
    return max(0.0, (b.ts - a.ts).total_seconds())


def _money_deltas(points: Sequence[MarketPoint]) -> tuple[list[float], list[float]]:
    buy_delta = [0.0] * len(points)
    sell_delta = [0.0] * len(points)
    for idx in range(1, len(points)):
        buy_delta[idx] = max(
            0.0, points[idx].buy_money_cum - points[idx - 1].buy_money_cum
        )
        sell_delta[idx] = max(
            0.0, points[idx].sell_money_cum - points[idx - 1].sell_money_cum
        )
    return buy_delta, sell_delta


def _adaptive_noise_pct(
    recent: Deque[tuple[datetime, float]],
    now: datetime,
    cfg: SellExhaustionConfig,
) -> float:
    while recent and (now - recent[0][0]).total_seconds() > cfg.recent_range_sec:
        recent.popleft()
    prices = [value for _, value in recent if value > 0]
    if len(prices) < 3:
        return cfg.noise_floor_pct
    low = min(prices)
    range_pct = (max(prices) / low - 1.0) * 100.0 if low > 0 else 0.0
    dynamic = range_pct * cfg.noise_range_fraction
    return min(cfg.noise_cap_pct, max(cfg.noise_floor_pct, dynamic))


def _build_leg(
    points: Sequence[MarketPoint],
    sell_delta: Sequence[float],
    high_idx: int,
    low_idx: int,
) -> _Leg:
    high = points[high_idx]
    low = points[low_idx]
    duration = max(1.0, _elapsed(high, low))
    drop_pct = max(0.0, (high.price / low.price - 1.0) * 100.0)
    sell_money = sum(sell_delta[high_idx + 1 : low_idx + 1])
    sell_speed = sell_money / duration
    drop_speed = drop_pct / duration
    sell_units = sell_money / 100_000_000.0
    sell_impact = drop_pct / sell_units if sell_units > 0 else float("inf")
    return _Leg(
        high_idx=high_idx,
        low_idx=low_idx,
        high_price=high.price,
        low_price=low.price,
        drop_pct=drop_pct,
        duration_sec=duration,
        drop_speed=drop_speed,
        sell_money=sell_money,
        sell_speed=sell_speed,
        sell_impact=sell_impact,
    )


def _weakness_flags(previous: _Leg, current: _Leg, cfg: SellExhaustionConfig) -> list[str]:
    flags: list[str] = []
    if current.drop_speed <= previous.drop_speed * cfg.drop_speed_ratio_max:
        flags.append("하락속도감소")
    if current.sell_speed <= previous.sell_speed * cfg.sell_speed_ratio_max:
        flags.append("매도속도감소")
    if (
        isfinite(previous.sell_impact)
        and isfinite(current.sell_impact)
        and current.sell_impact <= previous.sell_impact * cfg.sell_impact_ratio_max
    ):
        flags.append("매도효율감소")
    return flags


def _flow_confirmed(
    points: Sequence[MarketPoint],
    buy_delta: Sequence[float],
    sell_delta: Sequence[float],
    idx: int,
    cfg: SellExhaustionConfig,
) -> tuple[bool, float, float]:
    start = idx
    while start > 0 and _elapsed(points[start - 1], points[idx]) <= cfg.flow_window_sec:
        start -= 1
    if idx - start + 1 < cfg.min_flow_observations:
        return False, 0.0, 0.0
    buys = buy_delta[start : idx + 1]
    sells = sell_delta[start : idx + 1]
    total_buy = sum(buys)
    total_sell = sum(sells)
    total = total_buy + total_sell
    buy_share = total_buy / total if total > 0 else 0.0
    positive = sum(1 for buy, sell in zip(buys, sells) if buy > sell)
    positive_fraction = positive / len(buys)
    confirmed = (
        buy_share >= cfg.min_buy_money_share
        and positive_fraction >= cfg.min_buy_dominant_fraction
    )
    return confirmed, buy_share, positive_fraction


def _depth_from_peak(points: Sequence[MarketPoint], low_idx: int) -> float:
    peak = max(point.price for point in points[: low_idx + 1])
    low = points[low_idx].price
    return (peak / low - 1.0) * 100.0 if low > 0 else 0.0


def _window_start(
    points: Sequence[MarketPoint],
    end_idx: int,
    window_sec: float,
) -> int:
    start = end_idx
    while start > 0 and _elapsed(points[start - 1], points[end_idx]) <= window_sec:
        start -= 1
    return start


def _flow_regime_confirmed(
    points: Sequence[MarketPoint],
    buy_delta: Sequence[float],
    sell_delta: Sequence[float],
    idx: int,
    cfg: FlowBookExhaustionConfig,
) -> tuple[bool, float, float]:
    recent_start = _window_start(points, idx, cfg.recent_flow_window_sec)
    prior_start = _window_start(
        points,
        recent_start,
        cfg.prior_flow_window_sec,
    )
    if (
        idx - recent_start + 1 < cfg.min_window_observations
        or recent_start - prior_start < cfg.min_window_observations
    ):
        return False, 0.0, 0.0

    def pressure(start: int, end: int) -> float:
        buy = sum(buy_delta[start:end])
        sell = sum(sell_delta[start:end])
        total = buy + sell
        return (sell - buy) / total if total > 0 else 0.0

    prior_pressure = pressure(prior_start, recent_start)
    recent_pressure = pressure(recent_start, idx + 1)
    confirmed = (
        prior_pressure >= cfg.min_prior_sell_pressure
        and prior_pressure - recent_pressure >= cfg.min_sell_pressure_improvement
    )
    return confirmed, prior_pressure, recent_pressure


def _normalized_book_imbalance(point: MarketPoint) -> Optional[float]:
    total = point.bid_tot + point.ask_tot
    if point.bid_tot <= 0 or point.ask_tot <= 0 or total <= 0:
        return None
    return (point.bid_tot - point.ask_tot) / total


def _book_recovery_confirmed(
    points: Sequence[MarketPoint],
    idx: int,
    cfg: FlowBookExhaustionConfig,
) -> tuple[bool, float, float]:
    start = _window_start(points, idx, cfg.book_window_sec)
    values = [
        value
        for point in points[start : idx + 1]
        if (value := _normalized_book_imbalance(point)) is not None
    ]
    if len(values) < cfg.min_book_observations:
        return False, 0.0, 0.0
    median_imbalance = median(values)
    bid_dominant_fraction = sum(value > 0 for value in values) / len(values)
    current = values[-1]
    confirmed = (
        median_imbalance >= cfg.min_median_book_imbalance
        and bid_dominant_fraction >= cfg.min_bid_dominant_fraction
        and current >= cfg.min_current_book_imbalance
    )
    return confirmed, median_imbalance, bid_dominant_fraction


def detect_sell_exhaustion(
    points: Sequence[MarketPoint],
    cfg: SellExhaustionConfig = SellExhaustionConfig(),
) -> Optional[BottomSignal]:
    """계단식 신저점의 매도소진·가짜이탈 복구를 실시간 순서로 탐지한다."""
    if len(points) < 3:
        return None
    buy_delta, sell_delta = _money_deltas(points)
    recent: Deque[tuple[datetime, float]] = deque()
    phase = "DOWN"
    high_idx = 0
    low_idx = 0
    rebound_high_idx = 0
    previous_leg: Optional[_Leg] = None
    pending_pair: Optional[tuple[_Leg, _Leg, list[str]]] = None
    wave_count = 0

    for idx, point in enumerate(points):
        recent.append((point.ts, point.price))
        noise_pct = _adaptive_noise_pct(recent, point.ts, cfg)
        if phase == "DOWN":
            if points[high_idx].price < point.price and high_idx == low_idx:
                high_idx = low_idx = idx
            if point.price < points[low_idx].price:
                low_idx = idx
            rebound_pct = (point.price / points[low_idx].price - 1.0) * 100.0
            if rebound_pct < noise_pct or low_idx <= high_idx:
                continue
            current_leg = _build_leg(points, sell_delta, high_idx, low_idx)
            if current_leg.drop_pct < noise_pct:
                continue
            wave_count += 1
            pending_pair = None
            if previous_leg and current_leg.low_price < previous_leg.low_price:
                flags = _weakness_flags(previous_leg, current_leg, cfg)
                if len(flags) >= cfg.weakness_required:
                    pending_pair = (previous_leg, current_leg, flags)
            previous_leg = current_leg
            phase = "REBOUND"
            rebound_high_idx = idx

        if phase != "REBOUND":
            continue
        if point.price > points[rebound_high_idx].price:
            rebound_high_idx = idx
        if pending_pair:
            older, current, flags = pending_pair
            reclaimed = point.price >= older.low_price
            entry_gap = (point.price / current.low_price - 1.0) * 100.0
            flow_ok, buy_share, positive_fraction = _flow_confirmed(
                points, buy_delta, sell_delta, idx, cfg
            )
            depth_ok = _depth_from_peak(points, current.low_idx) >= cfg.min_depth_pct
            if (
                reclaimed
                and flow_ok
                and depth_ok
                and entry_gap <= cfg.max_entry_above_low_pct
            ):
                reason = (
                    f"{'+'.join(flags)}·이전저점복구·"
                    f"10초매수비중{buy_share:.1%}·매수우위구간{positive_fraction:.1%}"
                )
                return BottomSignal(
                    algorithm="NEW_SELL_EXHAUSTION",
                    signal_ts=point.ts,
                    signal_price=point.price,
                    anchor_low_ts=points[current.low_idx].ts,
                    anchor_low_price=current.low_price,
                    wave_count=wave_count,
                    reason=reason,
                )
        pullback_pct = (
            1.0 - point.price / points[rebound_high_idx].price
        ) * 100.0
        if pullback_pct >= noise_pct:
            phase = "DOWN"
            high_idx = rebound_high_idx
            low_idx = idx
            pending_pair = None

    return None


def detect_flow_book_exhaustion(
    points: Sequence[MarketPoint],
    wave_cfg: SellExhaustionConfig = SellExhaustionConfig(),
    flow_book_cfg: FlowBookExhaustionConfig = FlowBookExhaustionConfig(),
) -> Optional[BottomSignal]:
    """매도충격 감소 뒤 매도압력 체제전환과 총호가 회복을 확인한다."""
    if len(points) < 3:
        return None
    buy_delta, sell_delta = _money_deltas(points)
    recent: Deque[tuple[datetime, float]] = deque()
    phase = "DOWN"
    high_idx = 0
    low_idx = 0
    rebound_high_idx = 0
    previous_leg: Optional[_Leg] = None
    pending_pair: Optional[tuple[_Leg, _Leg, list[str]]] = None
    wave_count = 0

    for idx, point in enumerate(points):
        recent.append((point.ts, point.price))
        noise_pct = _adaptive_noise_pct(recent, point.ts, wave_cfg)
        if phase == "DOWN":
            if points[high_idx].price < point.price and high_idx == low_idx:
                high_idx = low_idx = idx
            if point.price < points[low_idx].price:
                low_idx = idx
            rebound_pct = (point.price / points[low_idx].price - 1.0) * 100.0
            if rebound_pct < noise_pct or low_idx <= high_idx:
                continue
            current_leg = _build_leg(points, sell_delta, high_idx, low_idx)
            if current_leg.drop_pct < noise_pct:
                continue
            wave_count += 1
            pending_pair = None
            if previous_leg and current_leg.low_price < previous_leg.low_price:
                flags = _weakness_flags(previous_leg, current_leg, wave_cfg)
                if len(flags) >= wave_cfg.weakness_required:
                    pending_pair = (previous_leg, current_leg, flags)
            previous_leg = current_leg
            phase = "REBOUND"
            rebound_high_idx = idx

        if phase != "REBOUND":
            continue
        if point.price > points[rebound_high_idx].price:
            rebound_high_idx = idx
        if pending_pair:
            older, current, flags = pending_pair
            reclaimed = point.price >= older.low_price
            entry_gap = (point.price / current.low_price - 1.0) * 100.0
            flow_ok, prior_pressure, recent_pressure = _flow_regime_confirmed(
                points,
                buy_delta,
                sell_delta,
                idx,
                flow_book_cfg,
            )
            book_ok, median_imbalance, bid_fraction = _book_recovery_confirmed(
                points,
                idx,
                flow_book_cfg,
            )
            depth_ok = _depth_from_peak(points, current.low_idx) >= wave_cfg.min_depth_pct
            if (
                reclaimed
                and flow_ok
                and book_ok
                and depth_ok
                and entry_gap <= wave_cfg.max_entry_above_low_pct
            ):
                return BottomSignal(
                    algorithm="PRO_FLOW_BOOK_EXHAUSTION",
                    signal_ts=point.ts,
                    signal_price=point.price,
                    anchor_low_ts=points[current.low_idx].ts,
                    anchor_low_price=current.low_price,
                    wave_count=wave_count,
                    reason=(
                        f"{'+'.join(flags)}·이전저점복구·"
                        f"매도압력{prior_pressure:.1%}->{recent_pressure:.1%}·"
                        f"호가불균형중앙{median_imbalance:.1%}·"
                        f"매수호가우위구간{bid_fraction:.1%}"
                    ),
                )
        pullback_pct = (
            1.0 - point.price / points[rebound_high_idx].price
        ) * 100.0
        if pullback_pct >= noise_pct:
            phase = "DOWN"
            high_idx = rebound_high_idx
            low_idx = idx
            pending_pair = None
    return None


def detect_legacy_pull(
    points: Sequence[MarketPoint],
    cfg: LegacyPullConfig = LegacyPullConfig(),
) -> Optional[BottomSignal]:
    """현재 캡틴2 PULL의 L1→재눌림→L2 저점확정 부분만 독립 재현한다."""
    if len(points) < 3:
        return None
    reference_high = points[0].price
    candidate_idx = 0
    last_low_update = points[0].ts
    l1_idx: Optional[int] = None
    rebound_high_idx = 0
    repull_seen = False
    wave_count = 0

    for idx, point in enumerate(points):
        reference_high = max(reference_high, point.price)
        if l1_idx is not None and not repull_seen:
            if point.price > points[rebound_high_idx].price:
                rebound_high_idx = idx
            tick = krx_tick_size(points[rebound_high_idx].price)
            if point.price <= points[rebound_high_idx].price - tick:
                candidate_idx = idx
                last_low_update = point.ts
                repull_seen = True
            continue
        if point.price < points[candidate_idx].price:
            candidate_idx = idx
            last_low_update = point.ts
            continue
        tick = krx_tick_size(points[candidate_idx].price)
        no_new_age = (point.ts - last_low_update).total_seconds()
        confirmed = (
            point.price >= points[candidate_idx].price + tick
            and no_new_age >= cfg.no_new_low_sec
        )
        if not confirmed:
            continue
        wave_count += 1
        if l1_idx is None or points[candidate_idx].price <= points[l1_idx].price:
            l1_idx = candidate_idx
            rebound_high_idx = idx
            repull_seen = False
            candidate_idx = idx
            last_low_update = point.ts
            continue
        low_price = points[candidate_idx].price
        depth_pct = (reference_high / low_price - 1.0) * 100.0
        recovery_pct = (
            (point.price - low_price) / (reference_high - low_price) * 100.0
            if reference_high > low_price
            else 100.0
        )
        if depth_pct < cfg.min_depth_pct or recovery_pct > cfg.max_recovery_pct:
            return None
        return BottomSignal(
            algorithm="OLD_CAPTAIN2_PULL",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=points[candidate_idx].ts,
            anchor_low_price=low_price,
            wave_count=wave_count,
            reason=(
                f"L2>L1·신저점없음{cfg.no_new_low_sec:.0f}초·"
                f"깊이{depth_pct:.2f}%·회복위치{recovery_pct:.1f}%"
            ),
        )
    return None


def detect_hybrid_exhaustion_pull(
    points: Sequence[MarketPoint],
    exhaustion_cfg: SellExhaustionConfig = SellExhaustionConfig(),
    legacy_cfg: LegacyPullConfig = LegacyPullConfig(),
) -> Optional[BottomSignal]:
    """매도소진을 우선하고, 순매수가 확인된 Higher Low만 보조 허용한다."""
    exhaustion = detect_sell_exhaustion(points, exhaustion_cfg)
    if exhaustion is not None:
        return BottomSignal(
            algorithm="HYBRID_EXHAUSTION_PULL",
            signal_ts=exhaustion.signal_ts,
            signal_price=exhaustion.signal_price,
            anchor_low_ts=exhaustion.anchor_low_ts,
            anchor_low_price=exhaustion.anchor_low_price,
            wave_count=exhaustion.wave_count,
            reason=f"주경로:{exhaustion.reason}",
        )
    higher_low = detect_legacy_pull(points, legacy_cfg)
    if higher_low is None:
        return None
    signal_idx = next(
        idx for idx, point in enumerate(points) if point.ts >= higher_low.signal_ts
    )
    buy_delta, sell_delta = _money_deltas(points)
    flow_ok, buy_share, positive_fraction = _flow_confirmed(
        points, buy_delta, sell_delta, signal_idx, exhaustion_cfg
    )
    entry_gap = (
        higher_low.signal_price / higher_low.anchor_low_price - 1.0
    ) * 100.0
    if not flow_ok or entry_gap > exhaustion_cfg.max_entry_above_low_pct:
        return None
    return BottomSignal(
        algorithm="HYBRID_EXHAUSTION_PULL",
        signal_ts=higher_low.signal_ts,
        signal_price=higher_low.signal_price,
        anchor_low_ts=higher_low.anchor_low_ts,
        anchor_low_price=higher_low.anchor_low_price,
        wave_count=higher_low.wave_count,
        reason=(
            f"보조경로:HigherLow·10초매수비중{buy_share:.1%}·"
            f"매수우위구간{positive_fraction:.1%}"
        ),
    )

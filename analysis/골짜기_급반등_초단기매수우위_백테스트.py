# -*- coding: utf-8 -*-
"""신저가 직후 초단기 매수체결대금 우위 진입 후보 비교.

완성봉과 30초 대기를 사용하지 않는다. -4% 무장 뒤 신저가마다 정확
매수·매도 체결대금, 체결강도, 타이머를 RESET하고 1~5초 안에서만
후보를 판정한다. 실제 주문은 없다.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional, Sequence


ROOT = Path(r"C:\stock_bot")
BASE_MODULE_PATH = ROOT / "analysis" / "골짜기_급반등_진입비교_백테스트.py"
OUT_CSV = ROOT / "analysis" / "골짜기_급반등_초단기매수우위.csv"
OUT_JSON = ROOT / "analysis" / "골짜기_급반등_초단기매수우위_요약.json"

SPEC = importlib.util.spec_from_file_location("valley_entry_base", BASE_MODULE_PATH)
assert SPEC and SPEC.loader
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)

MIN_OBSERVE_SEC = 1.0
MONEY_MIN = 10_000_000.0
RATIOS = (1.5, 2.0, 3.0)
MAX_WINDOWS_SEC = (2.0, 3.0, 5.0)
MIN_FALL_SPEEDS_PCT_SEC = (0.0, 0.1, 0.2)


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    buy_sell_ratio: float
    max_window_sec: float
    min_fall_speed_pct_sec: float

    @property
    def name(self) -> str:
        return (
            f"R{self.buy_sell_ratio:g}_W{self.max_window_sec:g}"
            f"_S{self.min_fall_speed_pct_sec:g}"
        )


def configs() -> list[CandidateConfig]:
    return [
        CandidateConfig(ratio, window, speed)
        for ratio in RATIOS
        for window in MAX_WINDOWS_SEC
        for speed in MIN_FALL_SPEEDS_PCT_SEC
    ]


def _fall_speed(
    history: Sequence[BASE.ReplayPoint],
    low_point: BASE.ReplayPoint,
) -> float:
    recent = [
        point
        for point in history
        if 0 < (low_point.ts - point.ts).total_seconds() <= 3.0
    ]
    if not recent:
        return 0.0
    prior = recent[0]
    elapsed = (low_point.ts - prior.ts).total_seconds()
    if elapsed <= 0:
        return 0.0
    return max(0.0, (prior.price / low_point.price - 1.0) * 100.0 / elapsed)


def ultra_short_signal(
    code: str,
    previous_close: float,
    points: Sequence[BASE.ReplayPoint],
    cfg: CandidateConfig,
) -> Optional[BASE.EntrySignal]:
    armed = False
    low_price: Optional[float] = None
    low_ts: Optional[datetime] = None
    reset_ts: Optional[datetime] = None
    reset_che = 0.0
    last_buy: Optional[float] = None
    last_sell: Optional[float] = None
    buy_sum = 0.0
    sell_sum = 0.0
    fall_speed = 0.0
    history: deque[BASE.ReplayPoint] = deque()

    for point in points:
        while history and (point.ts - history[0].ts).total_seconds() > 3.0:
            history.popleft()
        if point.ts.time() >= BASE.KST_ENTRY_END:
            break

        drop_pct = (point.price / previous_close - 1.0) * 100.0
        new_low = False
        if not armed and drop_pct <= BASE.ARM_DROP_PCT:
            armed = True
            new_low = True
        elif armed and (low_price is None or point.price < low_price):
            new_low = True

        exact = (
            point.ask_tot > 0
            and point.bid_tot > 0
            and point.buy_money_cum >= 0
            and point.sell_money_cum >= 0
        )
        if new_low:
            low_price = point.price
            low_ts = point.ts
            reset_ts = point.ts
            reset_che = point.che_str
            last_buy = point.buy_money_cum if exact else None
            last_sell = point.sell_money_cum if exact else None
            buy_sum = 0.0
            sell_sum = 0.0
            fall_speed = _fall_speed(tuple(history), point)
            history.append(point)
            continue
        history.append(point)
        if not armed or reset_ts is None or low_price is None or low_ts is None:
            continue

        regressed = (
            exact
            and last_buy is not None
            and last_sell is not None
            and (
                point.buy_money_cum < last_buy
                or point.sell_money_cum < last_sell
            )
        )
        if not exact or last_buy is None or last_sell is None or regressed:
            reset_ts = point.ts
            reset_che = point.che_str
            last_buy = point.buy_money_cum if exact else None
            last_sell = point.sell_money_cum if exact else None
            buy_sum = 0.0
            sell_sum = 0.0
            continue

        buy_sum += max(0.0, point.buy_money_cum - last_buy)
        sell_sum += max(0.0, point.sell_money_cum - last_sell)
        last_buy = point.buy_money_cum
        last_sell = point.sell_money_cum
        elapsed = (point.ts - reset_ts).total_seconds()
        if not (MIN_OBSERVE_SEC <= elapsed <= cfg.max_window_sec):
            continue
        if point.price < BASE.MIN_SIGNAL_PRICE:
            continue
        if fall_speed < cfg.min_fall_speed_pct_sec:
            continue
        if buy_sum + sell_sum < MONEY_MIN or buy_sum <= sell_sum:
            continue
        multiple = buy_sum / sell_sum if sell_sum > 0 else float("inf")
        if multiple < cfg.buy_sell_ratio:
            continue
        if not (point.che_str > reset_che > 0):
            continue
        return BASE.EntrySignal(
            algorithm=cfg.name,
            ts=point.ts,
            price=point.price,
            anchor_low_ts=low_ts,
            anchor_low_price=low_price,
            reason=(
                f"신저가후{elapsed:.2f}초·매수/매도{multiple:.2f}배·"
                f"정확체결{(buy_sum + sell_sum) / 1e8:.2f}억·"
                f"체결강도{reset_che:.1f}→{point.che_str:.1f}·"
                f"직전하락속도{fall_speed:.3f}%/초"
            ),
        )
    return None


def final_low_labels(
    points: Sequence[BASE.ReplayPoint],
    previous_close: float,
) -> dict[str, object]:
    armed_idx = next(
        (
            idx
            for idx, point in enumerate(points)
            if (point.price / previous_close - 1.0) * 100.0 <= BASE.ARM_DROP_PCT
        ),
        None,
    )
    if armed_idx is None:
        return {"morning_low_at": "", "quick_v_final": False}
    armed = list(points[armed_idx:])
    low = min(armed, key=lambda point: point.price)
    low_idx = armed.index(low)
    quick = any(
        0 < (point.ts - low.ts).total_seconds() <= 10.0
        and point.price >= low.price * 1.006
        for point in armed[low_idx + 1 :]
    )
    return {
        "morning_low_at": low.ts.isoformat(timespec="milliseconds"),
        "quick_v_final": quick,
    }


def summarize(rows: list[dict], cfg: CandidateConfig) -> dict[str, object]:
    selected = [row for row in rows if row["algorithm"] == cfg.name]
    signals = [row for row in selected if row["signal"] == "YES"]
    quick = [row for row in selected if row["quick_v_final"]]
    quick_captured = [
        row
        for row in quick
        if row["signal"] == "YES"
        and row["signal_after_morning_low_sec"] is not None
        and 0.0 <= float(row["signal_after_morning_low_sec"]) <= 10.0
        and not row["post_signal_new_low"]
    ]
    before_low = sum(
        float(row["signal_after_morning_low_sec"]) < 0.0 for row in signals
    )
    stops = sum(bool(row["hard_stop"]) for row in signals)
    return {
        "algorithm": cfg.name,
        "buy_sell_ratio": cfg.buy_sell_ratio,
        "max_window_sec": cfg.max_window_sec,
        "min_fall_speed_pct_sec": cfg.min_fall_speed_pct_sec,
        "armed_events": len(selected),
        "signals": len(signals),
        "signals_before_final_low": before_low,
        "premature_signal_pct": round(before_low / len(signals) * 100.0, 2)
        if signals
        else 0.0,
        "quick_v_final_events": len(quick),
        "quick_v_captured": len(quick_captured),
        "quick_v_capture_pct": round(len(quick_captured) / len(quick) * 100.0, 2)
        if quick
        else 0.0,
        "hard_stops": stops,
        "hard_stop_pct": round(stops / len(signals) * 100.0, 2)
        if signals
        else 0.0,
        "target_1pct_before_stop": sum(
            bool(row["target_1pct_before_stop"]) for row in signals
        ),
        "net_positive": sum(
            float(row["net_with_slippage_pct"]) > 0.0 for row in signals
        ),
        "median_net_with_slippage_pct": round(
            median(float(row["net_with_slippage_pct"]) for row in signals), 4
        )
        if signals
        else None,
    }


def run() -> dict[str, object]:
    candidate_configs = configs()
    universes = BASE.load_universes(BASE.DEFAULT_DAYS)
    rows: list[dict] = []
    quality: dict[str, dict] = {}
    for day in BASE.DEFAULT_DAYS:
        replay = BASE.load_day_replay(day, universes[day])
        quality[day] = replay.quality
        for code in sorted(replay.armed_codes):
            points = replay.morning[code]
            universe = replay.universe[code]
            labels = final_low_labels(points, universe.previous_close)
            for cfg in candidate_configs:
                signal = ultra_short_signal(
                    code,
                    universe.previous_close,
                    points,
                    cfg,
                )
                evaluated = BASE._evaluate_entry(
                    signal,
                    replay.outcome_prices.get(code, []),
                    labels,
                )
                evaluated.update(
                    {
                        "day": day,
                        "code": code,
                        "name": universe.name,
                        "algorithm": cfg.name,
                        "quick_v_final": labels["quick_v_final"],
                    }
                )
                rows.append(evaluated)
        print(
            f"[{day}] -4% 무장 {len(replay.armed_codes)} · "
            f"후보행 {len(replay.armed_codes) * len(candidate_configs)}",
            flush=True,
        )

    summaries = [summarize(rows, cfg) for cfg in candidate_configs]
    ranked = sorted(
        summaries,
        key=lambda row: (
            -int(row["quick_v_captured"]),
            float(row["hard_stop_pct"]),
            float(row["premature_signal_pct"]),
            -(float(row["median_net_with_slippage_pct"]) if row["median_net_with_slippage_pct"] is not None else -999.0),
            int(row["signals"]),
        ),
    )
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {
        "title": "골짜기 급반등 초단기 매수우위 비교",
        "period": list(BASE.DEFAULT_DAYS),
        "timezone": "Asia/Seoul",
        "actual_orders": 0,
        "candidate_count": len(candidate_configs),
        "fixed_conditions": {
            "one_entry_per_symbol": True,
            "minimum_observe_sec": MIN_OBSERVE_SEC,
            "minimum_exact_money": MONEY_MIN,
            "che_strength": "RESET 대비 상승",
            "hard_stop_pct": BASE.HARD_STOP_PCT,
            "fees_tax_pct": BASE.ROUND_TRIP_FEES_TAX_PCT,
            "assumed_round_trip_slippage_pct": BASE.ASSUMED_ROUND_TRIP_SLIPPAGE_PCT,
        },
        "quality": quality,
        "ranked_summaries": ranked,
        "output_csv": str(OUT_CSV),
    }
    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(ranked[:10], ensure_ascii=False, indent=2), flush=True)
    return result


if __name__ == "__main__":
    run()

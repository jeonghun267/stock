# -*- coding: utf-8 -*-
"""EARLY_DIP_RECLAIM 최근 2거래일 주문0 재생·자료품질 감사.

거래 코드나 주문 모듈을 import하지 않는다. 과거 EOD로 장전 후보를 재구성하고
1초 FID15 원시자료에서 현재 Captain2 EARLY 상태기계를 재현한다.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(r"C:\stock_bot")
EOD = ROOT / "data" / "eod_daily_bars.csv"
RAW_DIR = ROOT / "data" / "shadow" / "mf_1s_capture"
OUT_JSON = ROOT / "analysis" / "strategy04_dip_reclaim_audit.json"
OUT_CSV = ROOT / "analysis" / "strategy04_dip_reclaim_signals.csv"

DAY_SOURCE = {"20260723": "20260722", "20260724": "20260723"}
SIGNAL_START = "09:00:00"
SIGNAL_END = "09:20:00"
READ_END = "09:40:00"
ROUND_TRIP_FIXED_COST_PCT = 0.21


@dataclass(frozen=True)
class EodRow:
    date: str
    name: str
    close: float
    high: float
    value: float


@dataclass(frozen=True)
class Point:
    ts: datetime
    price: float
    cum_vol: float
    ask_tot: float
    bid_tot: float
    imb: float
    speed5: float
    speed30: float
    buy_money: float
    sell_money: float


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def load_eod() -> dict[str, list[EodRow]]:
    history: dict[str, list[EodRow]] = defaultdict(list)
    max_source = max(DAY_SOURCE.values())
    with EOD.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            date = str(row.get("date") or "")
            code = str(row.get("code") or "").zfill(6)
            if date > max_source or "KOSDAQ" not in str(row.get("market") or "").upper():
                continue
            if len(code) != 6 or not code.isdigit():
                continue
            history[code].append(
                EodRow(
                    date=date,
                    name=str(row.get("name") or ""),
                    close=_float(row.get("close")),
                    high=_float(row.get("high")),
                    value=_float(row.get("value")),
                )
            )
    return history


def universe_for(
    history: dict[str, list[EodRow]], source_day: str
) -> tuple[set[str], set[str], set[str], dict[str, float], dict[str, str]]:
    day_rows: list[tuple[float, str]] = []
    prev_close: dict[str, float] = {}
    names: dict[str, str] = {}
    eligible_history: dict[str, list[EodRow]] = {}
    for code, rows in history.items():
        past = [row for row in rows if row.date <= source_day]
        if not past or past[-1].date != source_day:
            continue
        last = past[-1]
        names[code] = last.name
        prev_close[code] = last.close
        eligible_history[code] = past
        if (
            last.close >= 10_000
            and last.value > 0
            and code.endswith("0")
            and "스팩" not in last.name
        ):
            day_rows.append((last.value, code))
    day_rows.sort(reverse=True)
    top100 = {code for _value, code in day_rows[:100]}
    qualified: set[str] = set()
    reverse_blocked: set[str] = set()
    for code in top100:
        rows = eligible_history[code]
        if len(rows) >= 21:
            last = rows[-1]
            close5 = rows[-6].close
            prior_values = [row.value for row in rows[-21:-1]]
            avg20 = _mean(prior_values)
            if (
                last.close > 0
                and close5 > 0
                and avg20 > 0
                and all(value > 0 for value in prior_values)
                and (last.close / close5 - 1.0) * 100.0 >= -10.0
                and (last.high / last.close - 1.0) * 100.0 >= 10.0
                and last.value / avg20 >= 6.0
            ):
                qualified.add(code)
        if len(rows) >= 60:
            closes = [row.close for row in rows if row.close > 0]
            if len(closes) >= 60:
                ma5 = _mean(closes[-5:])
                ma20 = _mean(closes[-20:])
                ma60 = _mean(closes[-60:])
                if ma5 < ma60 and ma20 < ma60:
                    reverse_blocked.add(code)
    return top100, qualified, reverse_blocked, prev_close, names


def load_raw(
    day: str, codes: set[str]
) -> tuple[dict[str, list[Point]], dict[str, int | float]]:
    path = RAW_DIR / f"mf_1s_{day}.csv"
    points: dict[str, list[Point]] = defaultdict(list)
    stats: dict[str, int | float] = defaultdict(int)
    previous_cum: dict[str, tuple[float, float]] = {}
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        header = handle.readline().rstrip("\r\n").split(",")
        fields = (
            "ts", "code", "current_price", "cum_vol", "ask_tot", "bid_tot", "imb",
            "money_speed_5s", "money_speed_30s", "buy_money_cum", "sell_money_cum",
        )
        index = {name: header.index(name) for name in fields}
        max_index = max(index.values())
        for line in handle:
            stats["raw_rows_scanned"] += 1
            parts = line.rstrip("\r\n").split(",", max_index + 1)
            if len(parts) <= max_index:
                stats["malformed_rows"] += 1
                continue
            ts_text = parts[index["ts"]]
            clock = ts_text[11:19]
            if clock < SIGNAL_START:
                continue
            if clock >= READ_END:
                break
            code = parts[index["code"]].strip().zfill(6)
            if code not in codes:
                continue
            try:
                ts = datetime.fromisoformat(ts_text)
            except ValueError:
                stats["malformed_rows"] += 1
                continue
            point = Point(
                ts=ts,
                price=_float(parts[index["current_price"]]),
                cum_vol=_float(parts[index["cum_vol"]]),
                ask_tot=_float(parts[index["ask_tot"]]),
                bid_tot=_float(parts[index["bid_tot"]]),
                imb=_float(parts[index["imb"]]),
                speed5=_float(parts[index["money_speed_5s"]]),
                speed30=_float(parts[index["money_speed_30s"]]),
                buy_money=_float(parts[index["buy_money_cum"]]),
                sell_money=_float(parts[index["sell_money_cum"]]),
            )
            if point.price <= 0:
                stats["invalid_price_rows"] += 1
                continue
            old = previous_cum.get(code)
            if old and (point.buy_money < old[0] or point.sell_money < old[1]):
                stats["cumulative_reversal_rows"] += 1
            previous_cum[code] = (point.buy_money, point.sell_money)
            if point.ask_tot <= 0 or point.bid_tot <= 0:
                stats["book_missing_rows"] += 1
            points[code].append(point)
            stats["selected_rows"] += 1
    gaps: list[float] = []
    duplicates = 0
    for rows in points.values():
        for before, after in zip(rows, rows[1:]):
            gap = (after.ts - before.ts).total_seconds()
            gaps.append(gap)
            if gap == 0:
                duplicates += 1
    stats["selected_codes"] = len(points)
    stats["duplicate_code_timestamps"] = duplicates
    stats["gap_gt_2_5s"] = sum(gap > 2.5 for gap in gaps)
    stats["median_gap_sec"] = round(median(gaps), 4) if gaps else 0.0
    stats["max_gap_sec"] = round(max(gaps), 4) if gaps else 0.0
    if stats["selected_rows"]:
        stats["book_missing_rate_pct"] = round(
            int(stats["book_missing_rows"]) / int(stats["selected_rows"]) * 100.0, 4
        )
    return points, dict(stats)


def _vwap(point: Point) -> float:
    if point.cum_vol <= 0 or point.buy_money < 0 or point.sell_money < 0:
        return 0.0
    value = (point.buy_money + point.sell_money) / point.cum_vol
    return value if point.price * 0.5 <= value <= point.price * 2.0 else 0.0


def _book_ratio(point: Point) -> float | None:
    total = point.ask_tot + point.bid_tot
    return point.bid_tot / total if total > 0 else None


def _outcomes(rows: list[Point], signal_ts: datetime, entry: float) -> dict[str, float]:
    result: dict[str, float] = {}
    future = [point for point in rows if point.ts >= signal_ts]
    for horizon in (60, 180, 300, 600, 1200):
        selected = [
            point for point in future
            if (point.ts - signal_ts).total_seconds() <= horizon
        ]
        if not selected:
            continue
        high = max(point.price for point in selected)
        low = min(point.price for point in selected)
        last = selected[-1].price
        mfe = (high / entry - 1.0) * 100.0
        result[f"mfe_{horizon}s_pct"] = round(mfe, 4)
        result[f"mae_{horizon}s_pct"] = round((low / entry - 1.0) * 100.0, 4)
        result[f"last_{horizon}s_after_fixed_cost_pct"] = round(
            (last / entry - 1.0) * 100.0 - ROUND_TRIP_FIXED_COST_PCT, 4
        )
        result[f"mfe_{horizon}s_after_fixed_cost_pct"] = round(
            mfe - ROUND_TRIP_FIXED_COST_PCT, 4
        )
    return result


def simulate(
    day: str,
    cohort: str,
    eligible: set[str],
    reverse_blocked: set[str],
    prev_close: dict[str, float],
    names: dict[str, str],
    points: dict[str, list[Point]],
) -> tuple[dict, list[dict]]:
    stages: dict[str, set[str]] = defaultdict(set)
    fired_counts: dict[str, int] = defaultdict(int)
    signals: list[dict] = []
    for code in sorted(eligible - reverse_blocked):
        rows = sorted(points.get(code, []), key=lambda point: point.ts)
        signal_rows = [row for row in rows if row.ts.strftime("%H:%M:%S") < SIGNAL_END]
        if not signal_rows:
            continue
        stages["data"].add(code)
        op = signal_rows[0].price
        bm0 = sm0 = -1.0
        bm0_ts = 0.0
        hist: deque[tuple[float, float, float, float]] = deque(maxlen=20)
        high_px = 0.0
        below_open = False
        dip_low = dip_low_ts = dip_low_speed = 0.0
        dip_book_ratio: float | None = None
        streak = 0
        streak_kind = ""
        last_sec = arm_px = 0.0
        fired = False
        for point in signal_rows:
            if fired:
                break
            if point.price < 10_000 or point.buy_money < 0 or point.sell_money < 0:
                continue
            sec = point.ts.timestamp()
            if bm0 < 0:
                bm0, sm0, bm0_ts = point.buy_money, point.sell_money, sec
            base_bm, base_sm, base_ts = bm0, sm0, bm0_ts or sec
            for old_ts, old_buy, old_sell, _old_px in hist:
                if sec - old_ts >= 10.0:
                    base_bm, base_sm, base_ts = old_buy, old_sell, old_ts
                else:
                    break
            db = point.buy_money - base_bm
            ds = point.sell_money - base_sm
            total = db + ds
            max_px = op * 1.03
            chased_before = high_px > max_px
            high_px = max(high_px, point.price)
            if point.price < op:
                stages["below_open"].add(code)
                below_open = True
                if dip_low <= 0 or point.price < dip_low:
                    dip_low = point.price
                    dip_low_ts = sec
                    dip_low_speed = point.speed5
                    dip_book_ratio = _book_ratio(point)
            dip_age = sec - dip_low_ts if dip_low_ts else 0.0
            if below_open and dip_age >= 2.0:
                stages["no_new_low_2s"].add(code)
            vw = _vwap(point)
            if below_open and dip_age >= 2.0 and point.price >= op:
                stages["open_reclaim"].add(code)
            if below_open and dip_age >= 2.0 and point.price >= op and vw > 0 and point.price > vw:
                stages["open_vwap_reclaim"].add(code)
            if below_open and point.speed5 > dip_low_speed:
                stages["speed_above_dip"].add(code)
            dip_ready = bool(
                below_open and dip_low > 0 and dip_age >= 2.0
                and point.price >= op and vw > 0 and point.price > vw
                and point.speed5 > dip_low_speed
            )
            if below_open:
                variant = "DIP_RECLAIM" if dip_ready else ""
            elif chased_before:
                variant = ""
            elif op <= prev_close.get(code, 0.0):
                variant = "DIRECT_ONSET"
            else:
                gap_pct = (op / max(prev_close.get(code, 0.0), 1.0) - 1.0) * 100.0
                variant = "GAP_ONSET" if gap_pct >= 3.0 else ""
            open_elapsed = (
                sec
                - point.ts.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
            )
            burst = point.speed5 / max(point.speed30, 1.0)
            buy_ratio = db / total if total > 0 else 0.0
            ok = bool(
                variant
                and point.speed5 >= 1_666_667
                and (open_elapsed < 30.0 or burst >= 3.0)
                and total > 0
                and buy_ratio >= 0.70
                and point.price >= op
                and point.price <= max_px
                and (vw > 0 and point.price > vw if variant == "DIP_RECLAIM" else (vw <= 0 or point.price > vw))
            )
            if variant == "DIP_RECLAIM" and ok:
                stages["dip_flow_gate"].add(code)
            if ok and streak > 0 and streak_kind == variant and sec - last_sec <= 2.5 and point.price >= arm_px:
                streak += 1
                last_sec = sec
            elif ok:
                reference = None
                for old_ts, _old_buy, _old_sell, old_px in reversed(hist):
                    if sec - old_ts >= 3.0:
                        reference = old_px
                        break
                if reference is not None and point.price > reference:
                    streak, last_sec, arm_px, streak_kind = 1, sec, point.price, variant
                else:
                    streak, streak_kind = 0, ""
            else:
                streak, streak_kind = 0, ""
            if streak >= 3:
                fired = True
                fired_counts[variant] += 1
                if variant == "DIP_RECLAIM":
                    stages["dip_fired"].add(code)
                    current_book = _book_ratio(point)
                    record = {
                        "day": day,
                        "cohort": cohort,
                        "code": code,
                        "name": names.get(code, code),
                        "signal_ts": point.ts.isoformat(timespec="milliseconds"),
                        "entry_price": point.price,
                        "open": op,
                        "dip_low": dip_low,
                        "dip_depth_from_open_pct": round((dip_low / op - 1.0) * 100.0, 4),
                        "reclaim_from_dip_pct": round((point.price / dip_low - 1.0) * 100.0, 4),
                        "buy_ratio_recent": round(buy_ratio, 4),
                        "speed5": round(point.speed5, 2),
                        "burst": round(burst, 4),
                        "vwap": round(vw, 2),
                        "dip_book_buy_ratio": (
                            round(dip_book_ratio, 4) if dip_book_ratio is not None else None
                        ),
                        "signal_book_buy_ratio": (
                            round(current_book, 4) if current_book is not None else None
                        ),
                        "book_recovered": bool(
                            current_book is not None
                            and dip_book_ratio is not None
                            and current_book >= 0.5
                            and current_book > dip_book_ratio
                        ),
                        "fixed_round_trip_cost_pct": ROUND_TRIP_FIXED_COST_PCT,
                        "spread_cost_available": False,
                    }
                    record.update(_outcomes(rows, point.ts, point.price))
                    signals.append(record)
            hist.append((sec, point.buy_money, point.sell_money, point.price))
    summary = {
        "day": day,
        "cohort": cohort,
        "eligible_codes": len(eligible),
        "reverse_ma_blocked": len(eligible & reverse_blocked),
        "evaluated_codes": len(eligible - reverse_blocked),
        "stage_counts": {name: len(codes) for name, codes in sorted(stages.items())},
        "fired_counts": dict(sorted(fired_counts.items())),
        "dip_signals": len(signals),
    }
    return summary, signals


def main() -> None:
    history = load_eod()
    output = {
        "purpose": "EARLY_DIP_RECLAIM actual-vs-theoretical weakness audit",
        "order_execution": "NONE",
        "signal_window": f"{SIGNAL_START} <= time < {SIGNAL_END}",
        "outcome_read_end": READ_END,
        "fixed_round_trip_cost_pct": ROUND_TRIP_FIXED_COST_PCT,
        "limitations": [
            "historical money-flow selector snapshots are absent; cohort is an upper-bound proxy",
            "best ask/bid prices are absent, so spread and spread cost cannot be measured",
            "market/sector index series are absent from the 1-second source",
            "timestamped news/event labels are absent",
            "historical event logs used old EARLY_ONSET and cannot identify DIP_RECLAIM",
        ],
        "days": {},
        "cohorts": [],
        "signals": [],
    }
    csv_rows: list[dict] = []
    for day, source_day in DAY_SOURCE.items():
        top100, qualified, reverse_blocked, prev_close, names = universe_for(
            history, source_day
        )
        points, quality = load_raw(day, top100)
        output["days"][day] = {
            "source_eod_day": source_day,
            "top100_codes": len(top100),
            "qualified_codes": len(qualified),
            "reverse_ma_blocked_in_top100": len(top100 & reverse_blocked),
            "raw_quality": quality,
        }
        for cohort, codes in (
            ("CURRENT_QUALIFIED_PROXY", qualified),
            ("TOP100_SENSITIVITY_NOT_CURRENT_RULE", top100),
        ):
            summary, signals = simulate(
                day, cohort, codes, reverse_blocked, prev_close, names, points
            )
            output["cohorts"].append(summary)
            output["signals"].extend(signals)
            csv_rows.extend(signals)
    OUT_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fieldnames = sorted({key for row in csv_rows for key in row})
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["no_signal"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"JSON={OUT_JSON}")
    print(f"CSV={OUT_CSV}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Order-zero feasibility test for an opening variant of Strategy 05.

This is deliberately not a production replay.  It imports only the production
base-breakout detector, reconstructs opening bars from a saved 1-second capture,
and evaluates a hypothetical early-base grid.  Spread, microprice, and the
historical live-leader board are absent from the capture, so the flow result is
an optimistic upper bound and must never be used to enable live orders.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_05_base_breakout_signal_v1 import Bar, _tick_size, detect_base_breakout


ROOT = Path(r"C:\stock_bot")
PROVENANCE = "[HYPOTHETICAL]"
OPEN = time(9, 0)
BREAKOUT_END = time(9, 20)
CAPTURE_END = time(10, 31)
COSTS_PCT = (0.29, 0.47)


@dataclass(frozen=True)
class Tick:
    ts: datetime
    price: float
    cum_vol: float
    buy_vol: float
    sell_vol: float
    buy_money: float
    sell_money: float
    ask_total: float
    bid_total: float


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_targets(path: Path, day: str) -> tuple[dict[str, str], int]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if str(payload.get("date") or "") != day:
        raise ValueError(f"candidate date mismatch: {payload.get('date')} != {day}")
    candidates = payload.get("candidates") or []
    targets = {
        str(row.get("code") or "").zfill(6): str(row.get("name") or row.get("code") or "")
        for row in candidates
        if _number(row.get("open")) > 0
        and _number(row.get("low_so_far")) >= _number(row.get("open"))
    }
    return targets, len(candidates)


def _read_capture_prefix(
    path: Path,
    targets: set[str],
    day: str,
    end: time,
) -> tuple[dict[str, list[Tick]], dict[str, Any]]:
    ticks: dict[str, list[Tick]] = defaultdict(list)
    digest = hashlib.sha256()
    prefix_bytes = 0
    malformed = 0
    time_disorder = 0
    last_ts: datetime | None = None
    first_ts: datetime | None = None
    final_ts: datetime | None = None
    header: list[str] | None = None
    index: dict[str, int] = {}
    required = (
        "ts", "code", "current_price", "cum_vol", "ask_tot", "bid_tot",
        "buy_vol_cum", "sell_vol_cum", "buy_money_cum", "sell_money_cum",
    )
    with path.open("rb") as handle:
        while True:
            raw = handle.readline()
            if not raw:
                break
            text = raw.decode("utf-8-sig" if header is None else "utf-8").rstrip("\r\n")
            if header is None:
                header = text.split(",")
                index = {name: pos for pos, name in enumerate(header)}
                missing = [name for name in required if name not in index]
                if missing:
                    raise ValueError(f"capture columns missing: {missing}")
                digest.update(raw)
                prefix_bytes += len(raw)
                continue
            values = text.split(",")
            if len(values) != len(header):
                malformed += 1
                digest.update(raw)
                prefix_bytes += len(raw)
                continue
            try:
                ts = datetime.fromisoformat(values[index["ts"]])
            except ValueError:
                malformed += 1
                digest.update(raw)
                prefix_bytes += len(raw)
                continue
            if ts.strftime("%Y%m%d") != day:
                digest.update(raw)
                prefix_bytes += len(raw)
                continue
            if ts.time() > end:
                break
            digest.update(raw)
            prefix_bytes += len(raw)
            if last_ts is not None and ts < last_ts:
                time_disorder += 1
            last_ts = max(last_ts, ts) if last_ts else ts
            first_ts = first_ts or ts
            final_ts = ts
            code = values[index["code"]].zfill(6)
            if code not in targets:
                continue
            price = _number(values[index["current_price"]])
            if price <= 0:
                continue
            ticks[code].append(Tick(
                ts=ts,
                price=price,
                cum_vol=_number(values[index["cum_vol"]]),
                buy_vol=_number(values[index["buy_vol_cum"]], -1.0),
                sell_vol=_number(values[index["sell_vol_cum"]], -1.0),
                buy_money=_number(values[index["buy_money_cum"]], -1.0),
                sell_money=_number(values[index["sell_money_cum"]], -1.0),
                ask_total=_number(values[index["ask_tot"]], -1.0),
                bid_total=_number(values[index["bid_tot"]], -1.0),
            ))

    # The live file may still be appending.  Verify the exact consumed prefix did
    # not change during analysis instead of pretending the growing tail is fixed.
    verify = hashlib.sha256()
    remaining = prefix_bytes
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(min(8 * 1024 * 1024, remaining))
            if not chunk:
                break
            verify.update(chunk)
            remaining -= len(chunk)
    stable = remaining == 0 and verify.hexdigest() == digest.hexdigest()
    return ticks, {
        "capture_prefix_bytes": prefix_bytes,
        "capture_prefix_sha256": digest.hexdigest(),
        "capture_prefix_stable": stable,
        "first_timestamp": first_ts.isoformat() if first_ts else "",
        "last_timestamp": final_ts.isoformat() if final_ts else "",
        "malformed_rows": malformed,
        "time_disorder_rows": time_disorder,
    }


def _opening_bars(ticks: list[Tick]) -> list[Bar]:
    by_minute: dict[datetime, list[Tick]] = defaultdict(list)
    baseline_cum = 0.0
    for row in ticks:
        if row.ts.time() < OPEN:
            baseline_cum = max(baseline_cum, row.cum_vol)
            continue
        if not OPEN <= row.ts.time() < BREAKOUT_END:
            continue
        by_minute[row.ts.replace(second=0, microsecond=0)].append(row)
    bars: list[Bar] = []
    previous_cum = baseline_cum
    for minute in sorted(by_minute):
        rows = by_minute[minute]
        final_cum = rows[-1].cum_vol
        volume = max(0.0, final_cum - previous_cum)
        previous_cum = max(previous_cum, final_cum)
        bars.append(Bar(
            ts=minute,
            open=rows[0].price,
            high=max(row.price for row in rows),
            low=min(row.price for row in rows),
            close=rows[-1].price,
            volume=volume,
        ))
    return bars


def _continuous(rows: list[Bar]) -> bool:
    return all(
        (right.ts - left.ts).total_seconds() == 60
        for left, right in zip(rows, rows[1:])
    )


def _at_or_before(rows: list[Tick], timestamps: list[datetime], target: datetime) -> Tick | None:
    pos = bisect.bisect_right(timestamps, target) - 1
    return rows[pos] if pos >= 0 else None


def _at_or_after(rows: list[Tick], timestamps: list[datetime], target: datetime) -> Tick | None:
    pos = bisect.bisect_left(timestamps, target)
    return rows[pos] if pos < len(rows) else None


def _flow_upper_bound(
    rows: list[Tick],
    line: float,
    start: datetime,
) -> tuple[Tick | None, dict[str, Any]]:
    timestamps = [row.ts for row in rows]
    begin = bisect.bisect_left(timestamps, start)
    stop = bisect.bisect_right(timestamps, start + timedelta(seconds=150))
    floor = line * (1.0 - 0.8 / 100.0)
    low: Tick | None = None
    low_updated: datetime | None = None
    reset: Tick | None = None
    dominance_since: datetime | None = None
    reason = "FLOW_NOT_CONFIRMED"

    for point in rows[begin:stop]:
        if point.price < floor:
            return None, {"reason": "RETEST_TOO_DEEP"}
        if reset is None:
            if low is None or point.price < low.price:
                low = point
                low_updated = point.ts
                continue
            if low is None or low_updated is None:
                continue
            if (
                point.price < low.price + _tick_size(low.price)
                or (point.ts - low_updated).total_seconds() < 2
            ):
                continue
            reset = low
            dominance_since = None
        elif point.price < reset.price:
            low = point
            low_updated = point.ts
            reset = None
            dominance_since = None
            continue

        elapsed = (point.ts - reset.ts).total_seconds()
        if elapsed < 2:
            continue
        if elapsed > 60:
            reason = "BUY_CONFIRM_TIMEOUT"
            break
        deltas = (
            point.buy_vol - reset.buy_vol,
            point.sell_vol - reset.sell_vol,
            point.buy_money - reset.buy_money,
            point.sell_money - reset.sell_money,
        )
        if min(deltas) < 0:
            reason = "FLOW_COUNTER_RESET_OR_MISSING"
            break
        buy_vol, sell_vol, buy_money, sell_money = deltas
        total_vol = buy_vol + sell_vol
        total_money = buy_money + sell_money
        buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.0
        buy_sell_ratio = buy_vol / max(sell_vol, 1e-9)
        buy_money_ratio = buy_money / total_money if total_money > 0 else 0.0

        p5 = _at_or_before(rows, timestamps, point.ts - timedelta(seconds=5))
        p10 = _at_or_before(rows, timestamps, point.ts - timedelta(seconds=10))
        p15 = _at_or_before(rows, timestamps, point.ts - timedelta(seconds=15))
        p30 = _at_or_before(rows, timestamps, point.ts - timedelta(seconds=30))
        if None in {p5, p10, p15, p30}:
            dominance_since = None
            continue
        assert p5 is not None and p10 is not None and p15 is not None and p30 is not None
        recent_span = (point.ts - p5.ts).total_seconds()
        previous_span = (p5.ts - p15.ts).total_seconds()
        rate10_span = (point.ts - p10.ts).total_seconds()
        rate30_span = (point.ts - p30.ts).total_seconds()
        if min(recent_span, previous_span, rate10_span, rate30_span) <= 0:
            dominance_since = None
            continue
        if (
            (point.ts - timedelta(seconds=5) - p5.ts).total_seconds() > 2
            or (point.ts - timedelta(seconds=15) - p15.ts).total_seconds() > 3
        ):
            dominance_since = None
            continue
        buy_rate10 = max(0.0, point.buy_money - p10.buy_money) / rate10_span
        sell_rate10 = max(0.0, point.sell_money - p10.sell_money) / rate10_span
        buy_rate30 = max(0.0, point.buy_money - p30.buy_money) / rate30_span
        buy_vol_rate5 = max(0.0, point.buy_vol - p5.buy_vol) / recent_span
        sell_vol_rate5 = max(0.0, point.sell_vol - p5.sell_vol) / recent_span
        prior_buy_rate10 = max(0.0, p5.buy_vol - p15.buy_vol) / previous_span
        rebound = (point.price / reset.price - 1.0) * 100.0
        price_ok = (
            point.price >= line
            and point.price <= line * 1.01
            and 0.3 <= rebound <= 1.0
        )
        fast_flow_ok = (
            buy_rate10 > 0
            and sell_rate10 > 0
            and buy_rate10 >= sell_rate10 * 1.5
            and buy_vol_rate5 > 0
            and sell_vol_rate5 > 0
            and prior_buy_rate10 > 0
            and buy_vol_rate5 >= sell_vol_rate5 * 1.5
            and buy_vol_rate5 > prior_buy_rate10
        )
        dominance = (
            total_vol >= 1
            and total_money >= 10_000_000
            and buy_ratio >= 0.58
            and buy_sell_ratio >= 1.35
            and buy_money_ratio >= 0.58
            and price_ok
            and buy_rate30 > 0
            and buy_rate10 >= 0.5 * buy_rate30
            and fast_flow_ok
        )
        if dominance:
            dominance_since = dominance_since or point.ts
        else:
            dominance_since = None
        if dominance_since and (point.ts - dominance_since).total_seconds() >= 3:
            book_total = point.ask_total + point.bid_total
            return point, {
                "reason": "FLOW_GATES_PASS_BOOK_PRICE_FIELDS_MISSING",
                "reset_at": reset.ts.isoformat(timespec="seconds"),
                "reset_price": reset.price,
                "buy_ratio": round(buy_ratio, 4),
                "buy_sell_ratio": round(buy_sell_ratio, 4),
                "buy_money_ratio": round(buy_money_ratio, 4),
                "entry_money_krw": round(total_money),
                "book_bid_share": round(point.bid_total / book_total, 4) if book_total > 0 else None,
            }
    return None, {"reason": reason}


def _outcome(rows: list[Tick], entry: Tick) -> dict[str, Any]:
    timestamps = [row.ts for row in rows]
    row30 = _at_or_after(rows, timestamps, entry.ts + timedelta(minutes=30))
    row60 = _at_or_after(rows, timestamps, entry.ts + timedelta(minutes=60))
    stop = bisect.bisect_right(timestamps, entry.ts + timedelta(minutes=60))
    start = bisect.bisect_left(timestamps, entry.ts)
    window = rows[start:stop]

    def ret(row: Tick | None) -> float | None:
        return (row.price / entry.price - 1.0) * 100.0 if row else None

    gross30 = ret(row30)
    gross60 = ret(row60)
    return {
        "price_30m": row30.price if row30 else None,
        "price_60m": row60.price if row60 else None,
        "gross_30m_pct": round(gross30, 4) if gross30 is not None else None,
        "gross_60m_pct": round(gross60, 4) if gross60 is not None else None,
        "net_30m_pct_cost_029": round(gross30 - COSTS_PCT[0], 4) if gross30 is not None else None,
        "net_30m_pct_cost_047": round(gross30 - COSTS_PCT[1], 4) if gross30 is not None else None,
        "net_60m_pct_cost_029": round(gross60 - COSTS_PCT[0], 4) if gross60 is not None else None,
        "net_60m_pct_cost_047": round(gross60 - COSTS_PCT[1], 4) if gross60 is not None else None,
        "mfe_60m_pct": round((max(row.price for row in window) / entry.price - 1.0) * 100.0, 4) if window else None,
        "mae_60m_pct": round((min(row.price for row in window) / entry.price - 1.0) * 100.0, 4) if window else None,
    }


def _first_candidate(
    code: str,
    name: str,
    rows: list[Tick],
    bars: list[Bar],
    base_n: int,
    volx: float,
) -> dict[str, Any] | None:
    timestamps = [row.ts for row in rows]
    for pos in range(base_n, len(bars)):
        window = bars[pos - base_n:pos + 1]
        if not _continuous(window):
            continue
        pattern = detect_base_breakout(
            window,
            base_n=base_n,
            tight_pct=3.0,
            min_volx=volx,
        )
        if not pattern:
            continue
        signal_at = bars[pos].ts + timedelta(minutes=1)
        end = signal_at + timedelta(minutes=10)
        begin_pos = bisect.bisect_left(timestamps, signal_at)
        end_pos = bisect.bisect_right(timestamps, end)
        line = float(pattern["base_high"])
        retest = next((row for row in rows[begin_pos:end_pos] if row.price <= line), None)
        if retest is None:
            continue
        flow_entry, flow = _flow_upper_bound(rows, line, retest.ts)
        result = {
            "code": code,
            "name": name,
            "base_n": base_n,
            "volx_threshold": volx,
            "breakout_at": signal_at.isoformat(timespec="seconds"),
            "base_high": line,
            "base_range_pct": round(float(pattern["base_range_pct"]), 4),
            "breakout_volx": round(float(pattern["breakout_volx"]), 4),
            "structural_retest_at": retest.ts.isoformat(timespec="seconds"),
            "flow_upper_bound_pass": flow_entry is not None,
            "flow_detail": flow,
        }
        if flow_entry:
            result.update({
                "entry_at": flow_entry.ts.isoformat(timespec="seconds"),
                "entry_price": flow_entry.price,
                "outcome": _outcome(rows, flow_entry),
            })
        return result
    return None


def _mean(rows: Iterable[float | None]) -> float | None:
    values = [float(value) for value in rows if value is not None]
    return round(statistics.fmean(values), 4) if values else None


def _median(rows: Iterable[float | None]) -> float | None:
    values = [float(value) for value in rows if value is not None]
    return round(statistics.median(values), 4) if values else None


def _slot_select(rows: list[dict[str, Any]], slots: int = 6) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    active_until: list[datetime] = []
    for row in sorted(rows, key=lambda item: (
        item.get("entry_at") or "",
        -float(item.get("breakout_volx") or 0),
        item["code"],
    )):
        entered = datetime.fromisoformat(row["entry_at"])
        active_until = [end for end in active_until if end > entered]
        if len(active_until) >= slots:
            continue
        selected.append(row)
        active_until.append(entered + timedelta(minutes=60))
    return selected


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    flow_rows = [row for row in rows if row.get("flow_upper_bound_pass")]
    selected = _slot_select(flow_rows)
    outcomes = [row.get("outcome") or {} for row in selected]
    return {
        "structural_retest_count": len(rows),
        "flow_upper_bound_count": len(flow_rows),
        "six_slot_selected_count": len(selected),
        "selected_codes": [row["code"] for row in selected],
        "mean_net_30m_pct_cost_029": _mean(row.get("net_30m_pct_cost_029") for row in outcomes),
        "median_net_30m_pct_cost_029": _median(row.get("net_30m_pct_cost_029") for row in outcomes),
        "mean_net_60m_pct_cost_029": _mean(row.get("net_60m_pct_cost_029") for row in outcomes),
        "median_net_60m_pct_cost_029": _median(row.get("net_60m_pct_cost_029") for row in outcomes),
        "mean_net_30m_pct_cost_047": _mean(row.get("net_30m_pct_cost_047") for row in outcomes),
        "mean_net_60m_pct_cost_047": _mean(row.get("net_60m_pct_cost_047") for row in outcomes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260810")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    candidate_path = args.candidates or ROOT / "data" / "strategy_01_open_surge_signal_v2.json"
    capture_path = args.capture or ROOT / "data" / "shadow" / "mf_1s_capture" / f"mf_1s_{args.date}.csv"
    output_path = args.output or ROOT / "reports" / "strategy05_opening_feasibility" / f"{args.date}.json"
    production_path = ROOT / "RUN" / "strategy_05_base_breakout_signal_v1.py"

    targets, candidate_count = _load_targets(candidate_path, args.date)
    tick_map, capture_quality = _read_capture_prefix(
        capture_path, set(targets), args.date, CAPTURE_END
    )
    coverage = {
        code: {
            "rows": len(tick_map.get(code) or []),
            "first": (tick_map[code][0].ts.isoformat() if tick_map.get(code) else ""),
            "last": (tick_map[code][-1].ts.isoformat() if tick_map.get(code) else ""),
        }
        for code in sorted(targets)
    }
    variants: dict[str, Any] = {}
    for base_n in (3, 5, 10):
        for volx in (3.0, 6.0):
            key = f"base{base_n}_volx{volx:g}"
            results: list[dict[str, Any]] = []
            for code, name in targets.items():
                rows = tick_map.get(code) or []
                if not rows:
                    continue
                candidate = _first_candidate(
                    code, name, rows, _opening_bars(rows), base_n, volx
                )
                if candidate:
                    results.append(candidate)
            variants[key] = {
                "parameters": {
                    "base_n": base_n,
                    "base_tight_pct": 3.0,
                    "breakout_volx": volx,
                    "breakout_window": "09:00-09:20",
                    "retest_wait_minutes": 10,
                    "flow_gate": "current S05 computable gates; spread/microprice omitted",
                },
                "summary": _summary(results),
                "results": results,
            }

    report = {
        "provenance": PROVENANCE,
        "decision": "DO_NOT_CONNECT_LIVE",
        "date": args.date,
        "production_code_changed": "NOT_CHANGED",
        "test_code": str(Path(__file__).resolve()),
        "production_detector": str(production_path),
        "production_detector_sha256": _sha256(production_path),
        "candidate_source": str(candidate_path),
        "candidate_source_sha256": _sha256(candidate_path),
        "capture_source": str(capture_path),
        "capture_quality": capture_quality,
        "candidate_count": candidate_count,
        "above_open_target_count": len(targets),
        "captured_target_count": sum(1 for code in targets if tick_map.get(code)),
        "coverage": coverage,
        "selection_rule": "earliest flow-upper-bound entries; tie volx desc/code; six slots; 60m occupancy; other strategies excluded",
        "known_missing_fields": [
            "historical best bid/ask spread",
            "historical microprice edge",
            "historical live_leaders membership",
            "other-strategy shared-slot occupancy",
        ],
        "variants": variants,
        "reproducible_command": (
            f'python RUN\\strategy_05_opening_feasibility_test_v1.py --date {args.date}'
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "output": str(output_path),
        "provenance": PROVENANCE,
        "target_count": len(targets),
        "captured_target_count": report["captured_target_count"],
        "capture_prefix_stable": capture_quality["capture_prefix_stable"],
        "summaries": {
            key: value["summary"] for key, value in variants.items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

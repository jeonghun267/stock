# -*- coding: utf-8 -*-
"""Reproducible minute-bar audit for Strategy 05 buy-pattern parameters.

This is research-only: it reads local CSV files and writes one JSON summary.
It does not import a broker, change approval flags, or submit orders.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
OUTPUT = ROOT / "analysis" / "strategy05_base_breakout_audit_v1.json"
BASE_N = 30
TIGHT_PCT = 3.0
VOLX = 6.0
RETEST_BARS = 10
ENTRY_START = "093000"
ENTRY_END = "143000"


def number(value: object) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except ValueError:
        return 0.0


def previous_eod_eligible() -> dict[str, set[str]]:
    by_day: dict[str, set[str]] = defaultdict(set)
    with (DATA / "eod_daily_bars.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            day = str(row.get("date") or "").replace("-", "")
            code = str(row.get("code") or "")
            if (
                len(day) == 8
                and len(code) == 6
                and code.isdigit()
                and str(row.get("market") or "").upper() == "KOSDAQ"
                and number(row.get("close")) >= 10_000
            ):
                by_day[day].add(code)
    ordered = sorted(by_day)
    result: dict[str, set[str]] = {}
    for file in sorted(DATA.glob("prices_1m_clean_202607*.csv")):
        day = file.stem.rsplit("_", 1)[-1]
        prior = [value for value in ordered if value < day]
        result[day] = by_day[prior[-1]] if prior else set()
    return result


def read_bars(path: Path, eligible: set[str]) -> dict[str, list[dict[str, float | str]]]:
    grouped: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "")
            ts = str(row.get("ts") or "")
            if code not in eligible or len(ts) < 14:
                continue
            grouped[code].append({
                "ts": ts,
                "open": number(row.get("open")),
                "high": number(row.get("high")),
                "low": number(row.get("low")),
                "close": number(row.get("close")),
                "volume": number(row.get("volume")),
            })
    return grouped


def consecutive(rows: list[dict[str, float | str]]) -> bool:
    stamps = [datetime.strptime(str(row["ts"]), "%Y%m%d%H%M%S") for row in rows]
    return all(
        (right - left).total_seconds() == 60
        for left, right in zip(stamps, stamps[1:])
    )


def detect(rows: list[dict[str, float | str]], index: int) -> dict[str, float] | None:
    if index < BASE_N:
        return None
    base = rows[index - BASE_N:index]
    current = rows[index]
    if not consecutive(base + [current]):
        return None
    values = [
        number(row[key])
        for row in base + [current]
        for key in ("open", "high", "low", "close", "volume")
    ]
    if min(values) <= 0:
        return None
    high = max(number(row["high"]) for row in base)
    low = min(number(row["low"]) for row in base)
    average_volume = mean(number(row["volume"]) for row in base)
    range_pct = (high / low - 1.0) * 100.0
    volume_multiple = number(current["volume"]) / average_volume
    if (
        range_pct > TIGHT_PCT
        or number(current["close"]) <= number(current["open"])
        or number(current["close"]) <= high
        or volume_multiple < VOLX
    ):
        return None
    return {
        "line": high,
        "range_pct": range_pct,
        "volume_multiple": volume_multiple,
    }


def summarize(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": round(mean(values), 4) if values else 0.0,
        "median": round(median(values), 4) if values else 0.0,
    }


def volume_cohort(
    events: list[dict[str, object]],
    minimum: float,
    maximum: float | None = None,
) -> dict[str, float | int]:
    selected = [
        row for row in events
        if float(row["volume_multiple"]) >= minimum
        and (maximum is None or float(row["volume_multiple"]) < maximum)
    ]
    retests = [row for row in selected if row["retest_offset"] is not None]
    count = len(retests)
    return {
        "breakouts": len(selected),
        "retests": count,
        "retest_rate_pct": round(count / len(selected) * 100.0, 2)
        if selected else 0.0,
        "mfe_ge_0_5_pct": round(
            sum(float(row["mfe_60m_pct"]) >= 0.5 for row in retests)
            / count * 100.0, 2,
        ) if count else 0.0,
        "mfe_ge_1_pct": round(
            sum(float(row["mfe_60m_pct"]) >= 1.0 for row in retests)
            / count * 100.0, 2,
        ) if count else 0.0,
        "mae_le_minus_1_5_pct": round(
            sum(float(row["mae_60m_pct"]) <= -1.5 for row in retests)
            / count * 100.0, 2,
        ) if count else 0.0,
    }


def main() -> int:
    eligible_by_day = previous_eod_eligible()
    events: list[dict[str, object]] = []
    incomplete_files: list[str] = []
    for path in sorted(DATA.glob("prices_1m_clean_202607*.csv")):
        day = path.stem.rsplit("_", 1)[-1]
        grouped = read_bars(path, eligible_by_day.get(day, set()))
        if not grouped:
            incomplete_files.append(path.name)
            continue
        for code, rows in grouped.items():
            rows.sort(key=lambda row: str(row["ts"]))
            for index, row in enumerate(rows):
                hhmmss = str(row["ts"])[8:14]
                if not ENTRY_START <= hhmmss < ENTRY_END:
                    continue
                pattern = detect(rows, index)
                if pattern is None:
                    continue
                wait = rows[index + 1:index + 1 + RETEST_BARS]
                retest_offset = next(
                    (
                        offset
                        for offset, candidate in enumerate(wait, start=1)
                        if number(candidate["low"]) <= pattern["line"]
                    ),
                    None,
                )
                event: dict[str, object] = {
                    "day": day,
                    "code": code,
                    "breakout_ts": row["ts"],
                    **pattern,
                    "retest_offset": retest_offset,
                }
                if retest_offset is not None:
                    entry_index = index + retest_offset
                    future = rows[entry_index:min(len(rows), entry_index + 61)]
                    line = float(pattern["line"])
                    event.update({
                        "retest_low_pct": (
                            min(number(x["low"]) for x in wait[:retest_offset]) / line - 1.0
                        ) * 100.0,
                        "mfe_60m_pct": (
                            max(number(x["high"]) for x in future) / line - 1.0
                        ) * 100.0,
                        "mae_60m_pct": (
                            min(number(x["low"]) for x in future) / line - 1.0
                        ) * 100.0,
                    })
                events.append(event)

    retests = [row for row in events if row["retest_offset"] is not None]
    output = {
        "schema": "strategy05_base_breakout_audit_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "minute_files": [
                path.name for path in sorted(DATA.glob("prices_1m_clean_202607*.csv"))
            ],
            "excluded_empty_or_corrupt": incomplete_files,
            "eligibility": "previous EOD KOSDAQ, six-digit numeric code, close >= 10000",
        },
        "parameters": {
            "base_bars": BASE_N,
            "base_range_max_pct": TIGHT_PCT,
            "breakout_volume_multiple_min": VOLX,
            "retest_wait_bars": RETEST_BARS,
        },
        "counts": {
            "breakouts": len(events),
            "retests": len(retests),
            "retest_rate_pct": round(len(retests) / len(events) * 100.0, 2)
            if events else 0.0,
            "retests_mfe_ge_cost_0_5_pct": sum(
                float(row["mfe_60m_pct"]) >= 0.5 for row in retests
            ),
            "retests_mfe_ge_1_pct": sum(
                float(row["mfe_60m_pct"]) >= 1.0 for row in retests
            ),
            "retests_mae_le_minus_1_5_pct": sum(
                float(row["mae_60m_pct"]) <= -1.5 for row in retests
            ),
        },
        "volume_threshold_comparison": {
            "six_plus": volume_cohort(events, 6.0),
            "six_to_under_ten": volume_cohort(events, 6.0, 10.0),
            "ten_plus": volume_cohort(events, 10.0),
        },
        "distributions": {
            "base_range_pct": summarize(
                [float(row["range_pct"]) for row in events]
            ),
            "breakout_volume_multiple": summarize(
                [float(row["volume_multiple"]) for row in events]
            ),
            "retest_offset_bars": summarize(
                [float(row["retest_offset"]) for row in retests]
            ),
            "retest_low_pct": summarize(
                [float(row["retest_low_pct"]) for row in retests]
            ),
            "mfe_60m_pct": summarize(
                [float(row["mfe_60m_pct"]) for row in retests]
            ),
            "mae_60m_pct": summarize(
                [float(row["mae_60m_pct"]) for row in retests]
            ),
        },
        "events": events,
        "limitations": [
            "Minute OHLC cannot reproduce second-level low confirmation or order-book flow.",
            "MFE/MAE from the breakout line is an opportunity proxy, not common-engine realized PnL.",
            "The local sample is short and is not sufficient to optimize new thresholds.",
        ],
        "order_capability": 0,
    }
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(OUTPUT),
        "counts": output["counts"],
        "distributions": output["distributions"],
        "order_capability": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

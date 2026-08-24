# -*- coding: utf-8 -*-
"""Build the order-zero daily trend tiers used by S01 priority replay.

This module never imports a broker and never submits an order.  It only turns
the latest completed EOD bars into A/B/C metadata so the exact values present
at the S01 decision boundary can be preserved and replayed later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


BASE = Path(r"C:\stock_bot")
DEFAULT_EOD = BASE / "data" / "eod_daily_bars.csv"
DEFAULT_OUT = BASE / "data" / "s01_trend_priority_board_v1.json"
HOLIDAYS = BASE / "config" / "krx_holidays.txt"
SCHEMA = "s01_trend_priority_board_v1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_source_date(now: datetime) -> str:
    try:
        holidays = {
            line.strip() for line in HOLIDAYS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except OSError:
        holidays = set()
    day = now.date() - timedelta(days=1)
    while day.weekday() >= 5 or day.strftime("%Y%m%d") in holidays:
        day -= timedelta(days=1)
    return day.strftime("%Y%m%d")


def build(eod_path: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    bars = pd.read_csv(
        eod_path, usecols=["date", "code", "close"],
        dtype={"code": str}, low_memory=False,
    )
    bars["date"] = pd.to_numeric(bars["date"], errors="coerce")
    bars["code"] = (
        bars["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["date", "code", "close"]).sort_values(["code", "date"])
    if bars.empty:
        raise ValueError("EOD has no usable rows")
    grouped = bars.groupby("code", group_keys=False)
    bars["ma20"] = grouped["close"].transform(lambda s: s.rolling(20).mean())
    bars["ma60"] = grouped["close"].transform(lambda s: s.rolling(60).mean())
    bars["ma20_prev"] = grouped["ma20"].shift(1)
    bars["ma60_prev"] = grouped["ma60"].shift(1)
    source_date = int(bars["date"].max())
    latest = bars[bars["date"] == source_date]
    codes = {}
    counts = {"A": 0, "B": 0, "C": 0}
    for row in latest.itertuples(index=False):
        values_ready = all(
            pd.notna(value)
            for value in (row.ma20, row.ma60, row.ma20_prev, row.ma60_prev)
        )
        tier = "C"
        if values_ready:
            if (
                row.close > row.ma20 > row.ma60
                and row.ma20 > row.ma20_prev
                and row.ma60 > row.ma60_prev
            ):
                tier = "A"
            elif row.close > row.ma20 and row.ma20 > row.ma20_prev:
                tier = "B"
        counts[tier] += 1
        codes[str(row.code).zfill(6)] = {
            "s01_trend_tier": tier,
            "s01_trend_close": round(float(row.close), 4),
            "s01_trend_ma20": None if pd.isna(row.ma20) else round(float(row.ma20), 4),
            "s01_trend_ma60": None if pd.isna(row.ma60) else round(float(row.ma60), 4),
            "s01_trend_ma20_rising": bool(values_ready and row.ma20 > row.ma20_prev),
            "s01_trend_ma60_rising": bool(values_ready and row.ma60 > row.ma60_prev),
        }
    expected_source_date = _expected_source_date(now)
    source_stale = str(source_date) != expected_source_date
    return {
        "schema": SCHEMA,
        "for_date": now.strftime("%Y%m%d"),
        "generated_at": now.isoformat(timespec="seconds"),
        "source_date": str(source_date),
        "expected_source_date": expected_source_date,
        "source_stale": source_stale,
        "status": "STALE" if source_stale else "READY",
        "tier_counts": counts,
        "eod_sha256": _sha256(eod_path),
        "codes": codes,
    }


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eod", type=Path, default=DEFAULT_EOD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    payload = build(args.eod)
    write_atomic(args.out, payload)
    print(json.dumps({
        "status": payload["status"],
        "source_date": payload["source_date"],
        "tier_counts": payload["tier_counts"],
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

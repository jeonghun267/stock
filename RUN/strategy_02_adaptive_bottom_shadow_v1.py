# -*- coding: utf-8 -*-
"""S02 적응형 저점 필터 주문 0 그림자.

생산 S02가 기록한 BUY_READY 신호와 장세 그림자를 읽어 FAST/RETEST/BLOCK만
별도 기록한다. 브로커·주문 모듈을 import하지 않으며 생산 신호/상태를 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIR = ROOT / "data" / "strategy_02_signal_v1"
REGIME_CSV = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
LOWBUY_DIR = ROOT / "data" / "lowbuy_shadow"
UNIVERSE_JSON = ROOT / "data" / "common_high_range_top30.json"
OUT_DIR = ROOT / "data" / "s02_adaptive_bottom_shadow"


def _float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _regime_group(band: str) -> str:
    band = (band or "").strip().upper()
    if band in {"BULL", "LEAN_BULL"}:
        return "STRONG"
    if band in {"BEAR", "LEAN_BEAR"}:
        return "WEAK"
    return "NORMAL"


def _load_regimes(day: str):
    rows = []
    if not REGIME_CSV.exists():
        return rows
    with REGIME_CSV.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            raw_ts = str(row.get("ts") or "")
            if not raw_ts.startswith(f"{day[:4]}-{day[4:6]}-{day[6:8]}"):
                continue
            try:
                ts = datetime.fromisoformat(raw_ts)
            except ValueError:
                continue
            band = str(row.get("band") or row.get("band_us") or "FLAT")
            if band.strip().upper() == "GRAY" and row.get("gray_lean"):
                band = str(row["gray_lean"])
            rows.append((ts, band, _float(row.get("u201_chg"))))
    rows.sort(key=lambda item: item[0])
    return rows


def _regime_at(regimes, signal_ts: datetime):
    prior = [row for row in regimes if row[0] <= signal_ts]
    if not prior:
        return "UNKNOWN", "NORMAL", None
    _, band, u201 = prior[-1]
    return band, _regime_group(band), u201


def _load_market_context(day: str):
    lowbuy_path = LOWBUY_DIR / f"lowbuy_shadow_{day}.json"
    lowbuy = {}
    universe = {}
    if lowbuy_path.exists():
        lowbuy = json.loads(lowbuy_path.read_text(encoding="utf-8-sig")).get("codes", {})
    if UNIVERSE_JSON.exists():
        payload = json.loads(UNIVERSE_JSON.read_text(encoding="utf-8-sig"))
        universe = {
            str(row.get("code") or "").zfill(6): row
            for row in payload.get("candidates", [])
        }
    return lowbuy, universe, lowbuy_path


def _decision(row, regimes, lowbuy, universe):
    signal_ts = datetime.fromisoformat(row["ts"])
    code = str(row.get("code") or "").zfill(6)
    price = _float(row.get("price"))
    anchor = _float(row.get("anchor_low") or row.get("low_price"))
    premium = (price / anchor - 1.0) * 100.0 if price and anchor else None
    observe_sec = _float(row.get("observe_sec"), 0.0) or 0.0
    algorithm = str(row.get("algorithm") or "")
    direct = "DIRECT_REBOUND" in algorithm
    staircase = "STAIRCASE_RETEST" in algorithm
    band, group, u201 = _regime_at(regimes, signal_ts)
    info = lowbuy.get(code, {})
    meta = universe.get(code, {})
    open_px = _float(info.get("open_px"))
    avg_range = _float(meta.get("avg_5d_range_pct"))
    low_from_open = (anchor / open_px - 1.0) * 100.0 if anchor and open_px else None
    relative_low = low_from_open - u201 if low_from_open is not None and u201 is not None else None
    weakness = (
        abs(min(0.0, relative_low)) / avg_range
        if relative_low is not None and avg_range and avg_range > 0 else None
    )

    fast = bool(
        group == "STRONG" and direct and weakness is not None and weakness <= 0.25
        and premium is not None and premium <= 1.5
    )
    retest = bool(
        staircase and premium is not None and premium <= 2.0
        and (group != "WEAK" or observe_sec >= 300.0)
    )
    lane = "FAST" if fast else ("RETEST" if retest else "BLOCK")
    return {
        "provenance": "[HYPOTHETICAL]",
        "schema": "s02_adaptive_bottom_shadow_v1",
        "ts": row["ts"],
        "code": code,
        "name": row.get("name", ""),
        "source_action": row.get("action", ""),
        "shadow_action": "SHADOW_READY" if lane != "BLOCK" else "SHADOW_BLOCK",
        "lane": lane,
        "algorithm": algorithm,
        "anchor_id": row.get("anchor_id", ""),
        "price": price,
        "anchor_low": anchor,
        "entry_above_anchor_pct": round(premium, 4) if premium is not None else None,
        "relative_weakness_ratio": round(weakness, 4) if weakness is not None else None,
        "low_from_open_pct": round(low_from_open, 4) if low_from_open is not None else None,
        "avg_5d_range_pct": avg_range,
        "observe_sec": observe_sec,
        "regime": band,
        "regime_group": group,
        "u201_pct": u201,
        "order_capable": False,
        "production_changed": False,
    }


def _read_existing(path: Path):
    seen = set()
    if not path.exists():
        return seen
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        seen.add((row.get("ts"), row.get("code"), row.get("anchor_id")))
    return seen


def process_day(day: str):
    source = SIGNAL_DIR / f"strategy_02_signals_{day}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events = OUT_DIR / f"s02_adaptive_bottom_shadow_{day}.jsonl"
    summary = OUT_DIR / f"s02_adaptive_bottom_shadow_{day}_summary.json"
    regimes = _load_regimes(day)
    lowbuy, universe, lowbuy_path = _load_market_context(day)
    previous = _read_existing(events)
    current = []
    if source.exists():
        with source.open(encoding="utf-8-sig", newline="") as fp:
            for raw in csv.DictReader(fp):
                row = _decision(raw, regimes, lowbuy, universe)
                key = (row["ts"], row["code"], row["anchor_id"])
                current.append(row)
    temp_events = events.with_suffix(".jsonl.tmp")
    with temp_events.open("w", encoding="utf-8") as fp:
        for row in current:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_events.replace(events)
    all_rows = current
    added_count = sum(
        (row["ts"], row["code"], row["anchor_id"]) not in previous
        for row in current
    )
    payload = {
        "provenance": "[HYPOTHETICAL]",
        "schema": "s02_adaptive_bottom_shadow_v1",
        "date": day,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source),
        "regime_source": str(REGIME_CSV),
        "lowbuy_source": str(lowbuy_path),
        "universe_source": str(UNIVERSE_JSON),
        "production_changed": "NOT_CHANGED",
        "order_capable": False,
        "signals_seen": len(all_rows),
        "shadow_ready": sum(r.get("shadow_action") == "SHADOW_READY" for r in all_rows),
        "shadow_block": sum(r.get("shadow_action") == "SHADOW_BLOCK" for r in all_rows),
        "fast": sum(r.get("lane") == "FAST" for r in all_rows),
        "retest": sum(r.get("lane") == "RETEST" for r in all_rows),
        "added_this_run": added_count,
        "limitation": "생산 S02가 기록한 BUY_READY만 평가하므로 미신호 종목의 기회는 측정하지 않는다.",
    }
    temp = summary.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(summary)
    return payload, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--end-hm", type=int, default=1530)
    args = parser.parse_args()
    while True:
        payload, path = process_day(args.day)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        if args.once or int(datetime.now().strftime("%H%M")) >= args.end_hm:
            print(path, flush=True)
            return 0
        time.sleep(max(1.0, args.poll_sec))


if __name__ == "__main__":
    raise SystemExit(main())

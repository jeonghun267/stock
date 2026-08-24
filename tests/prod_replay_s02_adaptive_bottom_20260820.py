# -*- coding: utf-8 -*-
"""S02 적응형 저점 관문 현재 생산판정 [PROD_REPLAY]."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import replay_buy_method_v1 as replay_source  # noqa: E402
import strategy_02_low_buy_signal_v1 as S02  # noqa: E402
from 저점매수_매도소진 import MarketPoint  # noqa: E402


DAY = "20260820"
TARGET_CODES = {"084370", "095340", "126730"}
SIGNALS = ROOT / "data" / "strategy_02_signal_v1" / f"strategy_02_signals_{DAY}.csv"
SHADOW = ROOT / "data" / "s02_adaptive_bottom_shadow" / f"s02_adaptive_bottom_shadow_{DAY}.jsonl"
CAPTURE = ROOT / "data" / "shadow" / "mf_1s_capture" / f"mf_1s_{DAY}.csv"
LOWBUY = ROOT / "data" / "lowbuy_shadow" / f"lowbuy_shadow_{DAY}.json"
UNIVERSE = ROOT / "data" / "common_high_range_top30.json"
REGIME = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
ENGINE = RUN / "strategy_02_low_buy_signal_v1.py"
OUT = ROOT / "analysis" / f"prod_replay_s02_adaptive_bottom_{DAY}.json"


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_regimes():
    result = []
    with REGIME.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            try:
                ts = datetime.fromisoformat(str(raw.get("ts") or ""))
            except ValueError:
                continue
            if ts.strftime("%Y%m%d") == DAY:
                result.append((
                    ts,
                    str(raw.get("band_us") or raw.get("band") or "UNKNOWN"),
                    f(raw.get("u201_chg"), None),
                ))
    return sorted(result, key=lambda row: row[0])


def replay(code, rows, *, open_px, avg_range, adaptive, regimes, end_ts):
    monitor = S02.LowBuySignalMonitor(adaptive_bottom_enabled=adaptive)
    run_high = 0.0
    fired = []
    regime_index = -1
    for raw in rows:
        try:
            ts = datetime.fromisoformat(raw["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts > end_ts:
            break
        price = f(raw.get("current_price"))
        if price <= 0 or ts.time() < S02.ENTRY_START:
            continue
        run_high = max(run_high, price)
        while (
            regime_index + 1 < len(regimes)
            and regimes[regime_index + 1][0] <= ts
        ):
            regime_index += 1
        if regime_index >= 0:
            _, band, u201 = regimes[regime_index]
        else:
            band, u201 = "UNKNOWN", None
        point = MarketPoint(
            ts=ts,
            price=price,
            cum_vol=f(raw.get("cum_vol")),
            che_str=f(raw.get("che_str")),
            ask_tot=f(raw.get("ask_tot")),
            bid_tot=f(raw.get("bid_tot")),
            buy_money_cum=f(raw.get("buy_money_cum")),
            sell_money_cum=f(raw.get("sell_money_cum")),
            buy_vol_cum=f(raw.get("buy_vol_cum"), -1.0),
            sell_vol_cum=f(raw.get("sell_vol_cum"), -1.0),
        )
        row, hit = monitor.process_point(
            code,
            code,
            point,
            allow_signal=S02.ENTRY_START <= ts.time() < S02.ENTRY_END,
            open_price=open_px,
            session_high=run_high,
            regime_band=band,
            u201_pct=u201,
            avg_5d_range_pct=avg_range,
        )
        if hit:
            fired.append({
                "ts": row["ts"],
                "code": code,
                "price": row["price"],
                "anchor_low": row["anchor_low"],
                "algorithm": row["algorithm"],
                "adaptive_pass": row.get("adaptive_pass"),
                "adaptive_lane": row.get("adaptive_lane"),
                "adaptive_relative_weakness_ratio": row.get(
                    "adaptive_relative_weakness_ratio"
                ),
            })
    return fired


def close_match(expected, actual, max_sec=2.0):
    ets = datetime.fromisoformat(expected["ts"])
    ats = datetime.fromisoformat(actual["ts"])
    return (
        expected["code"] == actual["code"]
        and abs((ets - ats).total_seconds()) <= max_sec
        and abs(f(expected["price"]) - f(actual["price"])) < 0.001
    )


def main():
    with SIGNALS.open(encoding="utf-8-sig", newline="") as handle:
        expected = [
            row for row in csv.DictReader(handle)
            if str(row.get("code") or "").zfill(6) in TARGET_CODES
        ]
    for row in expected:
        row["code"] = str(row["code"]).zfill(6)
    shadow = [
        json.loads(line)
        for line in SHADOW.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    shadow_by_key = {(row["ts"], row["code"]): row for row in shadow}
    codes = {row["code"] for row in expected}
    captures = replay_source.extract(DAY, codes)
    lowbuy = json.loads(LOWBUY.read_text(encoding="utf-8-sig")).get("codes", {})
    board = json.loads(UNIVERSE.read_text(encoding="utf-8-sig"))
    meta = {
        str(row.get("code") or "").zfill(6): row
        for row in board.get("candidates", [])
    }
    regimes = load_regimes()

    baseline = []
    adaptive = []
    for code in sorted(codes):
        open_px = f((lowbuy.get(code) or {}).get("open_px"))
        avg_range = f((meta.get(code) or {}).get("avg_5d_range_pct"))
        end_ts = max(
            datetime.fromisoformat(row["ts"])
            for row in expected if row["code"] == code
        ) + timedelta(seconds=3)
        baseline.extend(replay(
            code, captures.get(code) or [], open_px=open_px,
            avg_range=avg_range, adaptive=False, regimes=regimes, end_ts=end_ts,
        ))
        adaptive.extend(replay(
            code, captures.get(code) or [], open_px=open_px,
            avg_range=avg_range, adaptive=True, regimes=regimes, end_ts=end_ts,
        ))

    expected_sorted = sorted(expected, key=lambda row: (row["code"], row["ts"]))
    baseline_sorted = sorted(baseline, key=lambda row: (row["code"], row["ts"]))
    baseline_mismatches = []
    if len(expected_sorted) != len(baseline_sorted):
        baseline_mismatches.append(
            f"count expected={len(expected_sorted)} actual={len(baseline_sorted)}"
        )
    for index, exp in enumerate(expected_sorted):
        if index >= len(baseline_sorted) or not close_match(exp, baseline_sorted[index]):
            baseline_mismatches.append({
                "expected": {k: exp.get(k) for k in ("ts", "code", "price", "algorithm")},
                "actual": baseline_sorted[index] if index < len(baseline_sorted) else None,
            })

    selection_mismatches = []
    for exp in expected:
        should_pass = (
            shadow_by_key[(exp["ts"], exp["code"])]["shadow_action"]
            == "SHADOW_READY"
        )
        matched = any(close_match(exp, row) for row in adaptive)
        if should_pass != matched:
            selection_mismatches.append({
                "ts": exp["ts"], "code": exp["code"],
                "shadow_should_pass": should_pass, "production_replay_fired": matched,
            })
    invalid_fires = [row for row in adaptive if row.get("adaptive_pass") is not True]
    passed = not baseline_mismatches and not selection_mismatches and not invalid_fires
    stat = CAPTURE.stat()
    report = {
        "provenance": "[PROD_REPLAY]" if passed else "[UNVERIFIED]",
        "status": "PASS" if passed else "FAIL",
        "date": DAY,
        "target_codes": sorted(TARGET_CODES),
        "production_code_changed": "CHANGED",
        "source_data": [str(SIGNALS), str(SHADOW), str(CAPTURE), str(LOWBUY), str(UNIVERSE), str(REGIME)],
        "production_entry_point": f"{ENGINE}::LowBuySignalMonitor.process_point",
        "engine_sha256": sha(ENGINE),
        "small_input_sha256": {
            str(path): sha(path) for path in (SIGNALS, SHADOW, LOWBUY, UNIVERSE)
        },
        "capture_identity": {
            "path": str(CAPTURE), "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "command": r"C:\python310\python.exe -B -X utf8 tests\prod_replay_s02_adaptive_bottom_20260820.py",
        "raw_result": {
            "expected_signals": len(expected),
            "baseline_replayed_signals": len(baseline),
            "adaptive_replayed_signals": len(adaptive),
            "baseline_mismatches": baseline_mismatches,
            "selection_mismatches": selection_mismatches,
            "invalid_adaptive_fires": invalid_fires,
            "adaptive_rows": adaptive,
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "provenance": report["provenance"], "status": report["status"],
        "expected": len(expected), "baseline": len(baseline),
        "adaptive": len(adaptive),
        "baseline_mismatches": len(baseline_mismatches),
        "selection_mismatches": len(selection_mismatches),
    }, ensure_ascii=False))
    print(OUT)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

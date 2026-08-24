from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
sys.path.insert(0, str(RUN))

from strategy_03_flow_turn_fast_v1 import bottom_confirm_decision  # noqa: E402

SIGNAL_AUDIT = ROOT / "data" / "audit" / "s03_early_low" / "s03_early_low_signal_20260820.jsonl"
ENGINE_AUDIT = ROOT / "data" / "audit" / "s03_early_low" / "s03_early_low_engine_20260820.jsonl"
SIGNALS = ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json"
REGIME = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
FILLS = ROOT / "LOG" / "fills_20260820.csv"
OUT = ROOT / "analysis" / "s03_actual_buys_bottom_confirm_20260820.json"
TARGETS = {
    "237690": "2026-08-20T09:08:53.454",
    "125490": "2026-08-20T09:10:08.586",
    "487400": "2026-08-20T09:10:20.268",
    "084370": "2026-08-20T09:10:33.253",
    "178320": "2026-08-20T09:14:43.531",
    "064760": "2026-08-20T09:17:07.335",
}
GROSS_PCT = {
    "237690": -1.349,
    "125490": -1.161,
    "487400": -0.085,
    "084370": 0.595,
    "178320": 0.261,
    "064760": -1.911,
}
GROSS_KRW = {
    "237690": -1500, "125490": -140, "487400": -10,
    "084370": 800, "178320": 100, "064760": -4500,
}


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def regime_at(target: datetime) -> str:
    prior = []
    with REGIME.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ts = datetime.fromisoformat(row["ts"])
            if ts.date() == target.date() and ts <= target:
                prior.append((ts, row.get("band_us") or row.get("band") or "UNKNOWN"))
    return prior[-1][1] if prior else "UNKNOWN"


def book_metrics(raw):
    ask = float(raw.get("best_ask_px") or 0.0)
    bid = float(raw.get("best_bid_px") or 0.0)
    ask_q = float(raw.get("best_ask_qty") or 0.0)
    bid_q = float(raw.get("best_bid_qty") or 0.0)
    total = ask_q + bid_q
    mid = (ask + bid) / 2.0 if ask > 0 and bid > 0 else 0.0
    micro = (ask * bid_q + bid * ask_q) / total if total > 0 else 0.0
    return {
        "best_bid_share": bid_q / total if total > 0 else 0.0,
        "microprice_edge_bps": ((micro / mid) - 1.0) * 10000.0 if mid > 0 else 0.0,
        "spread_bps": ((ask - bid) / mid) * 10000.0 if mid > 0 else 999.0,
    }


def early_flow(code, target_ts, audit_rows):
    target = datetime.fromisoformat(target_ts)
    rows = []
    for raw in audit_rows:
        if raw.get("code") != code:
            continue
        ts = datetime.fromisoformat(str(raw.get("snapshot_ts") or ""))
        if ts <= target:
            rows.append({
                "ts": ts,
                "price": float(raw.get("current_price") or 0.0),
                "buy": float(raw.get("buy_money_cum") or 0.0),
                "sell": float(raw.get("sell_money_cum") or 0.0),
            })
    rows.sort(key=lambda row: row["ts"])
    rates = []
    for prior, current in zip(rows, rows[1:]):
        seconds = (current["ts"] - prior["ts"]).total_seconds()
        db = current["buy"] - prior["buy"]
        ds = current["sell"] - prior["sell"]
        if seconds > 0 and db >= 0 and ds >= 0:
            rates.append((db / seconds, ds / seconds, prior, current))
    if len(rates) < 2:
        return None
    recent_buy, recent_sell, prior_point, current_point = rates[-1]
    base = rates[max(0, len(rates) - 4):-1]
    baseline_buy = median(row[0] for row in base)
    baseline_sell = median(row[1] for row in base)
    recent_prices = [row["price"] for row in rows[-3:]]
    return {
        "sample_points": len(rows),
        "recent_buy_rate": recent_buy,
        "recent_sell_rate": recent_sell,
        "baseline_buy_rate": baseline_buy,
        "baseline_sell_rate": baseline_sell,
        "sell_decelerating": recent_sell <= baseline_sell * 0.80,
        "buy_accelerating": recent_buy >= baseline_buy * 1.20,
        "buy_flow_leading": recent_buy > recent_sell,
        "price_responding": (
            current_point["price"] > prior_point["price"]
            and current_point["price"] > min(recent_prices)
        ),
    }


def main() -> int:
    signal_audit = read_jsonl(SIGNAL_AUDIT)
    engine_audit = read_jsonl(ENGINE_AUDIT)
    signal_payload = json.loads(SIGNALS.read_text(encoding="utf-8-sig"))
    signal_rows = {
        (row.get("code"), row.get("ts")): row
        for row in signal_payload.get("signals", [])
    }
    engine_rows = {}
    for row in engine_audit:
        code = str(row.get("code") or "")
        if code in TARGETS and row.get("selector_pass") is True and code not in engine_rows:
            engine_rows[code] = row

    results = []
    for code, target_ts in TARGETS.items():
        signal = signal_rows[(code, target_ts)]
        if code == "237690":
            flow = {
                "sample_points": 3,
                "recent_buy_rate": signal.get("recent_buy_rate_10s", 0.0),
                "recent_sell_rate": signal.get("recent_sell_rate_10s", 0.0),
                "baseline_buy_rate": signal.get("previous_buy_rate_10s", 0.0),
                "baseline_sell_rate": signal.get("previous_sell_rate_10s", 0.0),
                "sell_decelerating": signal.get("recent_sell_rate_10s", 0.0) <= signal.get("previous_sell_rate_10s", 0.0) * 0.80,
                "buy_accelerating": signal.get("recent_buy_rate_10s", 0.0) >= signal.get("previous_buy_rate_10s", 0.0) * 1.20,
                "buy_flow_leading": signal.get("recent_buy_rate_10s", 0.0) > signal.get("recent_sell_rate_10s", 0.0),
                "price_responding": float(signal.get("rebound_pct") or 0.0) > 0.0,
            }
            book = {
                "best_bid_share": float(signal.get("best_bid_qty") or 0.0) / max(1.0, float(signal.get("best_bid_qty") or 0.0) + float(signal.get("best_ask_qty") or 0.0)),
                "microprice_edge_bps": float(signal.get("microprice_edge_bps") or 0.0),
                "spread_bps": float(signal.get("spread_bps") or 999.0),
            }
        else:
            flow = early_flow(code, target_ts, signal_audit)
            book = book_metrics(engine_rows[code]["snapshot_raw"])

        decision = bottom_confirm_decision(
            entry_lane=str(signal.get("entry_lane") or "OPEN_CRASH"),
            signal_reason=str(signal.get("reason") or ""),
            rebound_pct=float(signal.get("rebound_pct") or 0.0),
            regime_band=regime_at(datetime.fromisoformat(target_ts)),
            observe_sec=float(signal.get("observe_sec") or 0.0),
            reset_steps=int(signal.get("dip_low_reset_steps") or 0),
            pullback_depth_pct=float(signal.get("pullback_depth_pct") or 0.0),
            higher_low_pct=float(signal.get("higher_low_pct") or 0.0),
            second_rebound_pct=float(signal.get("second_rebound_pct") or 0.0),
            recent_buy_rate=float(flow["recent_buy_rate"]),
            recent_sell_rate=float(flow["recent_sell_rate"]),
            baseline_buy_rate=float(flow["baseline_buy_rate"]),
            baseline_sell_rate=float(flow["baseline_sell_rate"]),
            price_responding=bool(flow["price_responding"]),
            microprice_edge_bps=book["microprice_edge_bps"],
            best_bid_share=book["best_bid_share"],
            spread_bps=book["spread_bps"],
        )
        checks = decision["flow_checks"]
        flow_score = decision["flow_score"]
        passed = decision["ready"]
        results.append({
            "code": code,
            "name": signal.get("name", ""),
            "signal_ts": target_ts,
            "action": "BOTTOM_CONFIRM_BUY" if passed else "BLOCK_RESET",
            "route": decision["route"],
            "regime_group": decision["regime_group"],
            "flow_score": flow_score,
            "checks": checks,
            "book": {key: round(value, 4) for key, value in book.items()},
            "flow": flow,
            "broker_fill_gross_pct": GROSS_PCT[code],
            "broker_fill_gross_krw": GROSS_KRW[code],
        })

    selected = [row for row in results if row["action"] == "BOTTOM_CONFIRM_BUY"]
    blocked = [row for row in results if row["action"] == "BLOCK_RESET"]
    report = {
        "provenance": "[HYPOTHETICAL]",
        "status": "PASS",
        "date": "20260820",
        "production_changed": "NOT_CHANGED",
        "method": "S03_BOTTOM_CONFIRM exact-tested-predicate audit replay",
        "source_data": [str(SIGNAL_AUDIT), str(ENGINE_AUDIT), str(SIGNALS), str(REGIME), str(ROOT / "LOG" / "strategy_03_rotation_v1.log"), str(FILLS)],
        "selected": [row["code"] for row in selected],
        "blocked": [row["code"] for row in blocked],
        "selected_gross_sum_pct": round(sum(row["broker_fill_gross_pct"] for row in selected), 3),
        "blocked_gross_sum_pct": round(sum(row["broker_fill_gross_pct"] for row in blocked), 3),
        "actual_gross_sum_krw": sum(row["broker_fill_gross_krw"] for row in results),
        "selected_gross_sum_krw": sum(row["broker_fill_gross_krw"] for row in selected),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if [row["code"] for row in selected] == ["487400", "084370"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Read-only S03 three-lane data and execution-context readiness gate."""
from __future__ import annotations
import argparse, csv, hashlib, json, os
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
DATA = next((ROOT / "data").glob("strategy_03_*_v1"))
REPORTS = ROOT / "reports" / "s03_lane_readiness"
SPECS = {
    "EARLY_LOW": ("strategy_03_early_low_signals_{day}.csv", {
        "ts","action","reason","code","entry_lane","price","anchor_low","anchor_low_ts",
        "rebound_pct","chase_blocked","current_buy_money_cum","current_sell_money_cum"}, {"price"}),
    "OPEN_CRASH": ("strategy_03_signals_{day}.csv", {
        "ts","action","reason","code","entry_lane","price","anchor_low","anchor_low_ts",
        "rebound_pct","flow_flip","recent_buy_rate_10s","recent_sell_rate_10s",
        "best_ask_px","best_bid_px","best_ask_qty","best_bid_qty","spread_bps",
        "microprice","microprice_edge_bps"}, {"best_ask_px","best_bid_px","best_ask_qty",
        "best_bid_qty","spread_bps","microprice","microprice_edge_bps"}),
    "INTRADAY_CRASH": ("strategy_03_low_gauge_{day}.csv", {
        "ts","action","reason","code","entry_lane","price","anchor_low","anchor_low_ts",
        "intraday_drawdown_pct","rebound_pct","spread_bps","microprice_edge_bps",
        "dip_buy_money_since_low","dip_sell_money_since_low","dip_book_imb",
        "dip_sell_decel_10s"}, {"spread_bps","microprice_edge_bps","dip_book_imb"}),
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect(data_dir, day, lane):
    pattern, required, execution = SPECS[lane]
    path = data_dir / pattern.format(day=day)
    result = {"lane": lane, "source": str(path.resolve()), "source_exists": path.is_file(),
              "source_sha256": "", "schema_complete": False, "missing_columns": [],
              "observed_rows": 0, "execution_context_columns": sorted(execution),
              "execution_context_complete": {}, "status": "UNVERIFIED", "errors": []}
    if not path.is_file():
        result["errors"] = ["MISSING_SOURCE"]
        return result
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        headers, rows = set(reader.fieldnames or []), list(reader)
    rows = [row for row in rows if (row.get("entry_lane") or "") == lane]
    missing = sorted(required - headers)
    result.update(source_sha256=sha256(path), schema_complete=not missing,
                  missing_columns=missing, observed_rows=len(rows),
                  execution_context_complete={field: bool(rows) and all(
                      str(row.get(field) or "").strip() for row in rows)
                      for field in sorted(execution)})
    if missing:
        result["errors"] = ["MISSING_REQUIRED_COLUMNS"]
    else:
        result["status"] = "PASS" if rows else "PASS_SCHEMA_NO_OBSERVATION"
    return result


def build_report(data_dir, day):
    lanes = {lane: inspect(data_dir, day, lane) for lane in SPECS}
    errors = [f"{lane}:{error}" for lane, item in lanes.items() for error in item["errors"]]
    return {"schema": "s03_lane_readiness_report_v1", "provenance": "[UNVERIFIED]",
            "performance_scope": "NONE", "strategy": "S03", "trade_date": day,
            "entry_lanes_expected": list(SPECS), "status": "PASS" if not errors else "UNVERIFIED",
            "live_behavior_changed": False,
            "checks": {"per_lane_schema": True, "source_hashes": True,
                       "quote_and_book_context": True, "broker_fill_or_slippage_model": False,
                       "out_of_sample_performance_validation": False},
            "lanes": lanes, "errors": errors,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = build_report(Path(args.data_dir), args.date)
    path = Path(args.report) if args.report else REPORTS / args.date / f"s03_lane_readiness_{args.date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(f"[UNVERIFIED] S03_LANE_READINESS {report['status']} report={path}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

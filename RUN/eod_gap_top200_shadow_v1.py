# -*- coding: utf-8 -*-
"""TR-zero, order-zero TOP200 observation board for EOD_GAP selection."""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
MONITOR = Path(r"C:\stock_bot\MONITOR")
for path in (RUN, MONITOR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import eod_gap_track_shadow_v1 as G
from eod_gap_score_common_v1 import calculate_raw_score

AUDIT_ROOT = Path(r"C:\stock_bot\data\audit\eod_gap_entry")
EOD = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
SHARES = Path(r"C:\stock_bot\DATA\shares_outstanding.csv")
OUT_ROOT = Path(r"C:\stock_bot\data")
LOG = Path(r"C:\stock_bot\data\LOG\eod_gap_top200_shadow.log")
FORBIDDEN_ORDER_MODULES = {"broker_client", "broker_gateway_v1"}
TASK_REGISTRATION_COMMAND = (
    'schtasks /Create /TN "SAFEPLUS_EOD_GAP_TOP200_SHADOW" '
    '/TR "\\"C:\\python310\\python.exe\\" -X utf8 '
    '\\"C:\\stock_bot\\RUN\\eod_gap_top200_shadow_v1.py\\"" '
    '/SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:27 /F'
)


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_audit(path):
    rows = []
    previous = ""
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
        row = json.loads(line)
        digest = str(row.pop("record_sha256", ""))
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        if (row.get("seq") != index or row.get("prev_sha256") != previous
                or digest != hashlib.sha256(canonical).hexdigest()):
            raise ValueError(f"audit hash chain mismatch seq={index}")
        row["record_sha256"] = digest
        rows.append(row)
        previous = digest
    if not rows or rows[0].get("record_type") != "decision_boundary":
        raise ValueError("decision boundary audit missing")
    return rows


def _latest_audit(date):
    files = sorted((AUDIT_ROOT / date).glob("entry_*.jsonl"),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"entry audit missing: {date}")
    return files[0]


def _load_shares():
    out = {}
    with SHARES.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().zfill(6)
            try:
                shares = float(row.get("shares") or 0)
            except (TypeError, ValueError):
                shares = 0
            if code and shares > 0:
                out[code] = shares
    return out


def _load_prev_eod(date):
    import pandas as pd

    cols = ["date", "code", "name", "market", "close", "value"]
    frame = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=cols,
                        low_memory=False)
    frame = frame[(frame["market"] == "KOSDAQ") & (frame["date"] < date)].copy()
    for col in ("close", "value"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["close", "value"]).sort_values(["code", "date"])
    frame["code"] = frame["code"].str.zfill(6)
    grouped = frame.groupby("code")
    frame["v20"] = grouped["value"].transform(lambda series: series.rolling(20).mean())
    frame["c5"] = grouped["close"].shift(5)
    last = frame.groupby("code").tail(1)
    return {
        row.code: {"v20": row.v20, "c5": row.c5, "close_prev": row.close}
        for row in last.itertuples(index=False)
    }


def _theme_ranks(top, memberships):
    grouped = {}
    for code, _name, turnover in top:
        theme = memberships.get(str(code).zfill(6))
        if theme:
            grouped.setdefault(theme, []).append((float(turnover), str(code).zfill(6)))
    ranks = {}
    for rows in grouped.values():
        for rank, (_turnover, code) in enumerate(sorted(rows, reverse=True), 1):
            ranks[code] = rank
    return ranks


def build_shadow(date, audit_path=None):
    order_modules_before = FORBIDDEN_ORDER_MODULES.intersection(sys.modules)
    audit_path = Path(audit_path) if audit_path else _latest_audit(date)
    rows = _read_audit(audit_path)
    header = rows[0]
    if str(header.get("date")) != str(date):
        raise ValueError("audit date mismatch")
    top = [tuple(row) for row in (header.get("top") or [])][:200]
    recorded = {str(row[1]).zfill(6): row for row in (header.get("candidates") or [])}
    unified = {}
    for row in rows:
        if row.get("record_type") == "selection_context":
            unified = dict(row.get("unified_scores") or {})

    saved_inputs = dict(header.get("raw_score_inputs") or {})
    missing_inputs = sorted(set(recorded) - set(saved_inputs))
    if missing_inputs:
        raise ValueError(
            f"SCORE_INPUTS_MISSING_REBASELINE: {len(missing_inputs)}/{len(recorded)}"
        )
    shares = _load_shares()

    identity = []
    recalculated = {}
    for code, old in recorded.items():
        item = saved_inputs[code]
        raw = calculate_raw_score(**item)
        recalculated[code] = raw
        expected = float(old[0])
        match = raw["score"] == expected
        identity.append({"code": code, "name": old[2], "recorded": expected,
                         "recalculated": raw["score"], "match": match})

    min_marketcap = float(os.environ.get(
        "SAFEPLUS_MIN_MARKETCAP", "100000000000") or "100000000000")
    excluded = []
    eligible_rows = []
    missing_shares = []
    for code, old in recorded.items():
        price = float(old[4] or 0)
        outstanding = shares.get(code)
        marketcap = price * outstanding if outstanding else None
        reason = None
        if price <= 10000:
            reason = "PRICE_LE_10000"
        elif outstanding is None:
            reason = "SHARES_MISSING"
            missing_shares.append(code)
        elif marketcap < min_marketcap:
            reason = "MARKETCAP_BELOW_MIN"
        row = {
            "code": code, "name": old[2], "price": price,
            "turnover_eok": float(old[3]), "marketcap": marketcap,
            "raw_score": recalculated[code]["score"],
            "unified_score": unified.get(code),
        }
        if reason:
            row["reason"] = reason
            excluded.append(row)
        else:
            eligible_rows.append(row)
    eligible_rows.sort(key=lambda row: row["turnover_eok"], reverse=True)
    band = [row for row in eligible_rows if 60 <= row["raw_score"] < 70]

    imported = sorted(
        FORBIDDEN_ORDER_MODULES.intersection(sys.modules) - order_modules_before
    )
    if imported:
        raise RuntimeError(f"order API module imported: {','.join(imported)}")
    matched = sum(1 for row in identity if row["match"])
    result = {
        "provenance": "[UNVERIFIED]",
        "date": date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "ORDER_ZERO_TR_ZERO",
        "source_audit": str(audit_path.resolve()),
        "source_audit_sha256": _sha256(audit_path),
        "score_input_source": "saved_audit_raw_score_inputs",
        "tr_design": "(b) TR 0 + honest captured coverage",
        "tr_calls": 0,
        "tr_calls_1515_1526": 0,
        "order_api_imported": False,
        "coverage": {
            "requested_top": 200,
            "captured_top": len(top),
            "captured_top_pct": round(len(top) / 200 * 100, 1),
            "scored_after_existing_hardcuts": len(recorded),
            "note": "TR0: saved audit coverage only; stocks outside captured top are not inferred",
        },
        "prefilter": {
            "price_rule": "price > 10000",
            "min_marketcap": min_marketcap,
            "eligible_count": len(eligible_rows),
            "excluded_count": len(excluded),
        },
        "score_identity": {
            "total": len(identity), "matched": matched,
            "mismatched": len(identity) - matched, "rows": identity,
        },
        "raw_score_band": "60 <= raw_score < 70",
        "candidates": band,
        "excluded": excluded,
        "shares_registry_outside": sorted(set(missing_shares)),
        "task_registration_executed": False,
        "task_registration_command": TASK_REGISTRATION_COMMAND,
    }
    if matched != len(identity):
        raise ValueError(f"raw score identity mismatch: {len(identity) - matched}/{len(identity)}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--audit")
    args = parser.parse_args(argv)
    result = build_shadow(args.date, args.audit)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out_path = OUT_ROOT / f"eod_gap_top200_shadow_{args.date}.json"
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(out_path))
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{result['generated_at']} date={args.date} mode=TR0 "
            f"coverage={result['coverage']['captured_top']}/200 "
            f"identity={result['score_identity']['matched']}/{result['score_identity']['total']} "
            f"band={len(result['candidates'])} order_api=0 task_registered=0\n"
        )
    print(json.dumps({
        "output": str(out_path), "coverage": result["coverage"],
        "score_identity": {key: result["score_identity"][key]
                           for key in ("total", "matched", "mismatched")},
        "candidate_count": len(result["candidates"]),
        "tr_calls_1515_1526": result["tr_calls_1515_1526"],
        "order_api_imported": result["order_api_imported"],
        "task_registration_executed": result["task_registration_executed"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

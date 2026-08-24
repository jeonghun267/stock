# -*- coding: utf-8 -*-
"""Build an idempotent broker-fill outcome ledger with entry-time market regime.

This recorder is audit-only.  It reads the append-only broker fill CSV and event
journal, then rebuilds derived CSV/JSON outputs.  It never sends an order and it
does not modify the legacy PnL ledger.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path


BASE = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot"))
LOG_DIR = BASE / "LOG"
EVENT_DIRS = (LOG_DIR, BASE / "data" / "LOG")
REGIME_HISTORY = BASE / "data" / "BACKTEST" / "regime_std_shadow.csv"
ATTRIBUTED_OUT = BASE / "DATA" / "broker_fill_attributed.csv"
OUTCOME_OUT = BASE / "DATA" / "broker_fill_outcomes.csv"
SUMMARY_OUT = BASE / "DATA" / "broker_fill_outcome_summary.json"

ATTRIBUTED_FIELDS = [
    "provenance", "ts", "date", "code", "side", "qty", "price",
    "order_no", "strategy", "rqname", "intent_id", "match_quality",
    "fill_source", "event_source",
]
OUTCOME_FIELDS = [
    "provenance", "date", "strategy", "code", "qty", "buy_ts", "sell_ts",
    "buy_price", "sell_price", "gross_pnl_krw", "gross_pnl_pct", "outcome",
    "market_regime", "regime_ts", "buy_order_no", "sell_order_no",
    "buy_match_quality", "sell_match_quality", "fill_source",
]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).replace(tzinfo=None)


def _num(value, default=0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _atomic_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _side(text: str) -> str:
    value = str(text).upper()
    if "BUY" in value or "매수" in value:
        return "BUY"
    if "SELL" in value or "매도" in value:
        return "SELL"
    return ""


def _strategy(rqname: str, intent_id: str) -> str:
    value = str(rqname).upper().strip()
    match = re.match(r"(.+?)_(?:BUY|SELL)(?:_|$)", value)
    if match:
        return match.group(1)
    head = str(intent_id).split(":", 1)[0].strip().upper()
    return head or "UNKNOWN"


def load_orders() -> tuple[list[dict], dict[str, str]]:
    orders: list[dict] = []
    event_sources: dict[str, str] = {}
    event_paths = sorted({path.resolve() for root in EVENT_DIRS
                          for path in root.glob("event_journal_*.jsonl")})
    for path in event_paths:
        try:
            with path.open(encoding="utf-8-sig", errors="replace") as handle:
                for line in handle:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("event_type") != "ORDER_SUBMITTED":
                        continue
                    payload = rec.get("payload") or {}
                    ts_text = str(rec.get("ts") or payload.get("ts_client") or "")
                    rqname = str(payload.get("rqname") or "")
                    intent_id = str(rec.get("entity_id") or "")
                    side = _side(rqname) or _side(intent_id)
                    code = str(payload.get("code") or "").strip().lstrip("A").zfill(6)
                    if not ts_text or not side or code == "000000":
                        continue
                    orders.append({
                        "ts": _dt(ts_text), "code": code, "side": side,
                        "qty": int(_num(payload.get("qty"))),
                        "strategy": _strategy(rqname, intent_id), "rqname": rqname,
                        "intent_id": intent_id, "source": str(path), "used": False,
                    })
            event_sources[path.name] = str(path)
        except OSError:
            continue
    orders.sort(key=lambda row: row["ts"])
    return orders, event_sources


def load_fills() -> list[dict]:
    fills: list[dict] = []
    for path in sorted(LOG_DIR.glob("fills_*.csv")):
        try:
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    if "체결" not in str(row.get("state") or ""):
                        continue
                    qty = int(_num(row.get("fill_qty")))
                    price = _num(row.get("fill_px"))
                    side = _side(row.get("otype") or "")
                    code = str(row.get("code") or "").strip().lstrip("A").zfill(6)
                    if qty <= 0 or price <= 0 or not side or code == "000000":
                        continue
                    fills.append({
                        "ts": _dt(row["ts"]), "code": code, "side": side,
                        "qty": qty, "price": price,
                        "order_no": str(row.get("order_no") or "").strip(),
                        "source": str(path),
                    })
        except (OSError, KeyError, ValueError):
            continue
    fills.sort(key=lambda row: row["ts"])
    return fills


def attribute_fills(fills: list[dict], orders: list[dict]) -> list[dict]:
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for order in orders:
        candidates[(order["code"], order["side"])].append(order)
    order_bindings: dict[str, dict] = {}
    result: list[dict] = []
    for fill in fills:
        matched = order_bindings.get(fill["order_no"])
        quality = "ORDER_NO_BOUND" if matched else "UNMATCHED"
        if matched is None:
            possible = []
            for order in candidates[(fill["code"], fill["side"])]:
                age = (fill["ts"] - order["ts"]).total_seconds()
                # fills CSV is second-resolution while event_journal retains
                # microseconds, so the same fill can appear up to 0.999s early.
                if (not order["used"] and -1 < age <= 15
                        and order["qty"] == fill["qty"]):
                    possible.append((age, order))
            # Ambiguous same-code/side/qty submissions are never attributed.
            if len(possible) == 1:
                _, matched = possible[0]
                matched["used"] = True
                if fill["order_no"]:
                    order_bindings[fill["order_no"]] = matched
                quality = "EXACT_EVENT_MATCH"
        strategy = matched["strategy"] if matched else "UNKNOWN"
        result.append({
            **fill, "strategy": strategy,
            "rqname": matched["rqname"] if matched else "",
            "intent_id": matched["intent_id"] if matched else "",
            "match_quality": quality,
            "event_source": matched["source"] if matched else "",
        })
    return result


def load_regimes() -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    if not REGIME_HISTORY.exists():
        return by_day
    with REGIME_HISTORY.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                ts = _dt(row.get("ts") or "")
            except (TypeError, ValueError):
                continue
            regime = str(row.get("band") or row.get("band_us") or "").strip()
            if regime:
                by_day[ts.strftime("%Y-%m-%d")].append({"ts": ts, "regime": regime})
    for rows in by_day.values():
        rows.sort(key=lambda row: row["ts"])
    return by_day


def regime_at(ts: datetime, regimes: dict[str, list[dict]]) -> tuple[str, str]:
    rows = regimes.get(ts.strftime("%Y-%m-%d"), [])
    prior = [row for row in rows if row["ts"] <= ts]
    if not prior:
        return "UNKNOWN", ""
    found = prior[-1]
    return found["regime"], found["ts"].strftime("%Y-%m-%d %H:%M:%S")


def build_outcomes(attributed: list[dict], regimes: dict[str, list[dict]]) -> list[dict]:
    queues: dict[tuple[str, str], deque] = defaultdict(deque)
    outcomes: list[dict] = []
    for fill in attributed:
        # A fill without an exact production order event remains visible in the
        # attributed ledger, but must not be paired into a strategy outcome.
        if fill["strategy"] == "UNKNOWN" or fill["match_quality"] == "UNMATCHED":
            continue
        key = (fill["strategy"], fill["code"])
        if fill["side"] == "BUY":
            lot = dict(fill)
            queues[key].append(lot)
            continue
        remain = fill["qty"]
        while remain > 0 and queues[key]:
            buy = queues[key][0]
            qty = min(remain, buy["qty"])
            pnl_krw = (fill["price"] - buy["price"]) * qty
            pnl_pct = (fill["price"] / buy["price"] - 1.0) * 100.0
            outcome = "WIN" if pnl_krw > 0 else ("LOSS" if pnl_krw < 0 else "FLAT")
            regime, regime_ts = regime_at(buy["ts"], regimes)
            outcomes.append({
                "provenance": "BROKER_FILL",
                "date": fill["ts"].strftime("%Y-%m-%d"),
                "strategy": fill["strategy"], "code": fill["code"], "qty": qty,
                "buy_ts": buy["ts"].strftime("%Y-%m-%d %H:%M:%S"),
                "sell_ts": fill["ts"].strftime("%Y-%m-%d %H:%M:%S"),
                "buy_price": f"{buy['price']:.4f}".rstrip("0").rstrip("."),
                "sell_price": f"{fill['price']:.4f}".rstrip("0").rstrip("."),
                "gross_pnl_krw": round(pnl_krw, 4),
                "gross_pnl_pct": round(pnl_pct, 6), "outcome": outcome,
                "market_regime": regime, "regime_ts": regime_ts,
                "buy_order_no": buy["order_no"], "sell_order_no": fill["order_no"],
                "buy_match_quality": buy["match_quality"],
                "sell_match_quality": fill["match_quality"],
                "fill_source": f"{buy['source']} | {fill['source']}",
            })
            buy["qty"] -= qty
            remain -= qty
            if buy["qty"] <= 0:
                queues[key].popleft()
    return outcomes


def summarize(outcomes: list[dict], attributed: list[dict]) -> dict:
    def group(field: str) -> dict:
        result: dict[str, dict] = {}
        for row in outcomes:
            key = str(row.get(field) or "UNKNOWN")
            rec = result.setdefault(key, {"trades": 0, "wins": 0, "losses": 0, "flats": 0})
            rec["trades"] += 1
            rec[{"WIN": "wins", "LOSS": "losses", "FLAT": "flats"}[row["outcome"]]] += 1
        for rec in result.values():
            decided = rec["wins"] + rec["losses"]
            rec["win_rate_pct"] = round(rec["wins"] / decided * 100, 2) if decided else None
        return result

    unmatched = sum(1 for row in attributed if row["match_quality"] == "UNMATCHED")
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provenance": "BROKER_FILL",
        "code_changed": "CHANGED",
        "note": "Gross fill-to-fill outcomes; fees/taxes excluded. Strategy attribution requires event match.",
        "attributed_fill_count": len(attributed) - unmatched,
        "unmatched_fill_count": unmatched,
        "attribution_coverage_pct": round(
            (len(attributed) - unmatched) / len(attributed) * 100, 2
        ) if attributed else None,
        "closed_outcome_count": len(outcomes),
        "by_strategy": group("strategy"),
        "by_market_regime": group("market_regime"),
        "inputs": {
            "fills": str(LOG_DIR / "fills_YYYYMMDD.csv"),
            "events": [str(root / "event_journal_YYYYMMDD.jsonl") for root in EVENT_DIRS],
            "regime": str(REGIME_HISTORY),
        },
    }


def main() -> int:
    fills = load_fills()
    orders, _ = load_orders()
    attributed = attribute_fills(fills, orders)
    regimes = load_regimes()
    outcomes = build_outcomes(attributed, regimes)
    attributed_rows = [{
        "provenance": "BROKER_FILL",
        "ts": row["ts"].strftime("%Y-%m-%d %H:%M:%S"),
        "date": row["ts"].strftime("%Y-%m-%d"),
        "code": row["code"], "side": row["side"], "qty": row["qty"],
        "price": row["price"], "order_no": row["order_no"],
        "strategy": row["strategy"], "rqname": row["rqname"],
        "intent_id": row["intent_id"], "match_quality": row["match_quality"],
        "fill_source": row["source"], "event_source": row["event_source"],
    } for row in attributed]
    _atomic_csv(ATTRIBUTED_OUT, ATTRIBUTED_FIELDS, attributed_rows)
    _atomic_csv(OUTCOME_OUT, OUTCOME_FIELDS, outcomes)
    summary = summarize(outcomes, attributed)
    _atomic_json(SUMMARY_OUT, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

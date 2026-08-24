# -*- coding: utf-8 -*-
"""Read-only S03 OPEN_CRASH vs S06 handoff diagnostic."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\stock_bot")
DATES = [
    "20260804", "20260805", "20260806", "20260807", "20260810",
    "20260811", "20260812", "20260813", "20260814", "20260818",
]


def rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def number(text: str, field: str):
    hit = re.search(rf"\b{field}=(-?\d+(?:\.\d+)?)%", text or "")
    return float(hit.group(1)) if hit else None


def opening_prices(targets: set[tuple[str, str]]):
    """Return earliest saved 1-minute open for each (date, code).

    The close archives are cumulative snapshots, so a trade date can first
    appear in a later-dated archive file.
    """
    sources = sorted((ROOT / "data" / "intraday_close_archive").glob("prices_1m_*.csv"))
    sources.append(ROOT / "data" / "prices_1m.csv")
    result = {}
    for source in sources:
        for row in rows(source):
            code = str(row.get("code") or "").zfill(6)
            ts = str(row.get("ts") or "")
            date = ts[:8]
            key = (date, code)
            if key not in targets:
                continue
            current = result.get(key)
            if current is None or ts < current[0]:
                result[key] = (ts, float(row.get("open") or 0.0), str(source))
    return result


def exact_fills(date: str):
    result = defaultdict(list)
    for row in rows(ROOT / "LOG" / f"fills_{date}.csv"):
        result[str(row.get("code") or "").zfill(6)].append(row)
    return result


event_sets = {}
targets = set()
for date in DATES:
    event_path = (
        ROOT / "data" / "strategy_03_rotation_v1"
        / f"strategy_03_events_{date}.csv"
    )
    events = rows(event_path)
    buys = [
        row for row in events
        if row.get("event") == "BUY_CONFIRMED"
        and event_time(row["ts"]).time() < datetime.strptime("09:20", "%H:%M").time()
    ]
    event_sets[date] = (event_path, events, buys)
    targets.update((date, str(row["code"]).zfill(6)) for row in buys)

opens = opening_prices(targets)
trades = []
coverage = []
for date in DATES:
    event_path, events, buys = event_sets[date]
    fills = exact_fills(date)
    s06_rows = rows(
        ROOT / "data" / "strategy_06_crash_low_chase"
        / f"strategy_06_signals_{date}.csv"
    )
    coverage.append({
        "date": date,
        "s03_event_file": event_path.exists(),
        "s03_open_buys": len(buys),
        "s06_signal_file": bool(s06_rows),
    })
    for buy in buys:
        code = str(buy["code"]).zfill(6)
        buy_at = event_time(buy["ts"])
        sells = [
            row for row in events
            if row.get("event") == "SELL_CONFIRMED"
            and str(row.get("code") or "").zfill(6) == code
            and event_time(row["ts"]) > buy_at
        ]
        sell = min(sells, key=lambda r: r["ts"]) if sells else {}
        open_row = opens.get((date, code))
        open_price = open_row[1] if open_row else 0.0
        entry_price = float(buy.get("price") or 0.0)
        drop = (entry_price / open_price - 1.0) * 100.0 if open_price > 0 else None
        same_s06 = [r for r in s06_rows if str(r.get("code") or "").zfill(6) == code]
        fill_rows = fills.get(code, [])
        trades.append({
            "date": date,
            "code": code,
            "name": buy.get("name") or code,
            "entry_at": buy["ts"],
            "entry_price": entry_price,
            "open_ts": open_row[0] if open_row else "",
            "open_price": open_price or None,
            "drop_from_open_pct": round(drop, 4) if drop is not None else None,
            "bucket": (
                "-4~-6" if drop is not None and -6 < drop <= -4 else
                "-6~-8" if drop is not None and -8 < drop <= -6 else
                "OUTSIDE_OR_UNKNOWN"
            ),
            "exit_at": sell.get("ts") or "",
            "exit_price": float(sell.get("price") or 0.0) if sell else None,
            "gross_pct": number(sell.get("reason") or "", "gross") if sell else None,
            "mfe_pct": number(sell.get("reason") or "", "mfe") if sell else None,
            "mae_pct": number(sell.get("reason") or "", "mae") if sell else None,
            "exit_reason": (sell.get("reason") or "").split(" cycle=")[0],
            "s06_trigger_at": next((r.get("ts") for r in same_s06 if r.get("event") == "TRIGGER"), ""),
            "s06_buy_ready": any(r.get("event") == "BUY_READY" for r in same_s06),
            "s06_min_low": min((float(r.get("low") or 0) for r in same_s06 if float(r.get("low") or 0) > 0), default=None),
            "fill_rows": [
                {
                    "ts": r.get("ts"), "otype": r.get("otype"),
                    "qty": int(r.get("fill_qty") or 0),
                    "price": float(r.get("fill_px") or 0),
                    "order_no": r.get("order_no"),
                }
                for r in fill_rows
                if r.get("otype") in {"+매수", "-매도"}
                and event_time(r["ts"]).date() == buy_at.date()
            ],
            "price_source": open_row[2] if open_row else "",
            "event_source": str(event_path),
        })


summary = {}
for bucket in ("-4~-6", "-6~-8", "OUTSIDE_OR_UNKNOWN"):
    group = [r for r in trades if r["bucket"] == bucket]
    known = [r for r in group if r["gross_pct"] is not None]
    summary[bucket] = {
        "n": len(group),
        "known_results": len(known),
        "wins": sum(1 for r in known if r["gross_pct"] > 0),
        "win_rate_pct": round(100 * sum(1 for r in known if r["gross_pct"] > 0) / len(known), 2) if known else None,
        "avg_gross_pct": round(sum(r["gross_pct"] for r in known) / len(known), 4) if known else None,
        "avg_mfe_pct": round(sum(r["mfe_pct"] for r in known if r["mfe_pct"] is not None) / sum(1 for r in known if r["mfe_pct"] is not None), 4) if any(r["mfe_pct"] is not None for r in known) else None,
        "avg_mae_pct": round(sum(r["mae_pct"] for r in known if r["mae_pct"] is not None) / sum(1 for r in known if r["mae_pct"] is not None), 4) if any(r["mae_pct"] is not None for r in known) else None,
    }

print(json.dumps({
    "dates_requested": DATES,
    "coverage": coverage,
    "trade_count": len(trades),
    "summary": summary,
    "trades": trades,
}, ensure_ascii=False, indent=2))

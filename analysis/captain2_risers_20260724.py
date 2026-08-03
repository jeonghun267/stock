import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
DAY = "20260724"
ENTRY_END = "1420"
SELECTOR = ROOT / "DATA" / "\ub3c8\ud750\ub984_\uc120\ubcc4\ud310.json"
PRICE = ROOT / "data" / f"prices_1m_clean_{DAY}.csv"
EVENTS = ROOT / "data" / "shadow" / f"captain2_events_{DAY}.csv"
EOD = ROOT / "data" / "eod_daily_bars.csv"

allowed = {
    str(code).zfill(6)
    for code in json.loads(SELECTOR.read_text(encoding="utf-8")).get("univ_codes", [])
}

metadata = {}
with EOD.open(encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        if row.get("date") == DAY:
            metadata[str(row["code"]).zfill(6)] = row

bars = {}
with PRICE.open(encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        timestamp = row["ts"]
        if timestamp[8:12] > ENTRY_END:
            continue
        code = str(row["code"]).zfill(6)
        open_price = float(row["open"])
        high = float(row["high"])
        value = float(row["value"] or 0)
        state = bars.setdefault(
            code,
            {"open": open_price, "high": high, "high_ts": timestamp, "value": 0.0},
        )
        if high > state["high"]:
            state["high"], state["high_ts"] = high, timestamp
        state["value"] += value

events = defaultdict(list)
with EVENTS.open(encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        events[str(row["code"]).zfill(6)].append(row)

results = []
for code, state in bars.items():
    info = metadata.get(code, {})
    if (
        code not in allowed
        or "KOSDAQ" not in str(info.get("market", "")).upper()
        or state["open"] < 10_000
        or state["value"] < 10_000_000_000
    ):
        continue
    rise = (state["high"] / state["open"] - 1) * 100
    code_events = events.get(code, [])
    buys = [row for row in code_events if row.get("event") == "BUY"]
    ready = [row for row in code_events if row.get("event") == "BUY_READY"]
    peak_minute = state["high_ts"][8:12]
    ready_pre_peak = [
        row for row in ready if row["ts"][11:16].replace(":", "") <= peak_minute
    ]
    buy_pre_peak = [
        row for row in buys if row["ts"][11:16].replace(":", "") <= peak_minute
    ]
    if buy_pre_peak:
        status = "CAUGHT"
    elif ready_pre_peak:
        status = "READY_PRE_PEAK_BLOCKED"
    elif ready:
        status = "READY_AFTER_PEAK"
    else:
        status = "NO_READY"
    results.append(
        {
            "code": code,
            "name": info.get("name", code),
            "open_to_high_pct": round(rise, 2),
            "peak_minute": peak_minute,
            "bought": bool(buys),
            "status": status,
        }
    )

results.sort(key=lambda row: row["open_to_high_pct"], reverse=True)
for threshold in (3, 5, 10, 15):
    group = [row for row in results if row["open_to_high_pct"] >= threshold]
    print(
        f">={threshold}%: eligible={len(group)} "
        f"captured={sum(row['bought'] for row in group)}"
    )

print(json.dumps(
    [row for row in results if row["open_to_high_pct"] >= 5],
    ensure_ascii=False,
    indent=2,
))

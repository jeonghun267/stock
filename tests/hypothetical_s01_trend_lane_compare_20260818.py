"""Reproducible, order-zero comparison for a proposed S01 trend lane.

This is deliberately labelled HYPOTHETICAL: the proposed lane is not present in
the production engine and the common live sell path cannot be reconstructed from
minute bars alone.  The script compares entry quality at fixed horizons only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
SHADOW = DATA / "shadow"
REPORT = DATA / "LOG" / "S01_trend_lane_compare_20260818.json"
DATES = (20260803, 20260804, 20260805, 20260806, 20260814)
ROUND_TRIP_COST_PCT = 0.38


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def code6(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)


def load_daily() -> pd.DataFrame:
    path = DATA / "eod_daily_bars.csv"
    d = pd.read_csv(path, usecols=["date", "code", "close", "volume", "value"], low_memory=False)
    d["date"] = pd.to_numeric(d["date"], errors="coerce")
    d["code"] = code6(d["code"])
    for col in ("close", "volume", "value"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["date", "code", "close"]).sort_values(["code", "date"])
    g = d.groupby("code", group_keys=False)
    for n in (5, 20, 60):
        d[f"ma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n).mean())
    d["ma5_prev"] = g["ma5"].shift(1)
    d["ma20_prev"] = g["ma20"].shift(1)
    d["ret5"] = g["close"].pct_change(5)
    d["vol5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    d["vol20"] = g["volume"].transform(lambda s: s.rolling(20).mean())
    d["value5"] = g["value"].transform(lambda s: s.rolling(5).mean())
    d["value20"] = g["value"].transform(lambda s: s.rolling(20).mean())
    return d


def load_minutes(date: int) -> pd.DataFrame:
    path = DATA / f"prices_1m_clean_{date}.csv"
    m = pd.read_csv(path, usecols=["code", "ts", "open", "high", "low", "close", "volume", "value"], low_memory=False)
    m["code"] = code6(m["code"])
    m["dt"] = pd.to_datetime(m["ts"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    for col in ("open", "high", "low", "close", "volume", "value"):
        m[col] = pd.to_numeric(m[col], errors="coerce")
    return m.dropna(subset=["dt", "code", "close"]).sort_values(["code", "dt"])


def prior_daily_rows(daily: pd.DataFrame, date: int) -> pd.DataFrame:
    prev_date = int(daily.loc[daily["date"] < date, "date"].max())
    p = daily[daily["date"] == prev_date].copy()
    p["daily_ok"] = (
        (p["close"] > p["ma5"])
        & (p["ma5"] > p["ma20"])
        & (p["ma20"] > p["ma60"])
        & (p["ma5"] > p["ma5_prev"])
        & (p["ma20"] > p["ma20_prev"])
        & (p["ret5"] >= 0.05)
        & (p["vol5"] >= p["vol20"])
        & (p["value5"] >= p["value20"])
    )
    return p.set_index("code")


def bars_3m(m: pd.DataFrame) -> pd.DataFrame:
    x = m.copy()
    minute = x["dt"].dt.hour * 60 + x["dt"].dt.minute
    x = x[(minute >= 540) & (minute <= 900)].copy()
    x["bucket"] = ((x["dt"].dt.hour * 60 + x["dt"].dt.minute - 540) // 3).astype(int)
    b = x.groupby(["code", "bucket"], as_index=False).agg(
        dt=("dt", "max"), open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
        value=("value", "sum"),
    )
    g = b.groupby("code", group_keys=False)
    for n in (5, 10, 20):
        b[f"ma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n).mean())
    b["ma5_prev"] = g["ma5"].shift(1)
    b["prev3_high"] = g["high"].transform(lambda s: s.shift(1).rolling(3).max())
    b["prior3_low"] = g["low"].transform(lambda s: s.shift(1).rolling(3).min())
    return b


def first_trend_entries(date: int, m: pd.DataFrame, prior: pd.DataFrame) -> list[dict]:
    b = bars_3m(m)
    rows: list[dict] = []
    for code, c in b.groupby("code"):
        if code not in prior.index or not bool(prior.at[code, "daily_ok"]):
            continue
        prev_close = float(prior.at[code, "close"])
        day_open = float(c.iloc[0]["open"])
        gap = day_open / prev_close - 1.0
        if not (-0.03 <= gap <= 0.10):
            continue
        clock = c["dt"].dt.hour * 60 + c["dt"].dt.minute
        hit = c[
            (clock >= 600) & (clock <= 870)
            & (c["close"] > c["ma5"])
            & (c["ma5"] > c["ma10"])
            & (c["ma10"] > c["ma20"])
            & (c["ma5"] > c["ma5_prev"])
            & (c["prior3_low"] <= c["ma10"] * 1.01)
            & (c["prior3_low"] >= c["ma20"] * 0.98)
            & (c["close"] > c["prev3_high"])
            & ((c["close"] / c["ma20"] - 1.0) <= 0.08)
        ]
        if not hit.empty:
            r = hit.iloc[0]
            rows.append({"date": date, "code": code, "dt": r["dt"], "entry": float(r["close"])})
    return rows


def current_s01_entries(date: int) -> list[dict]:
    path = SHADOW / f"strategy_01_open_surge_signal_{date}.csv"
    if not path.exists():
        return []
    s = pd.read_csv(path, dtype={"code": str})
    s["code"] = code6(s["code"])
    s["dt"] = pd.to_datetime(s["ts"], errors="coerce")
    s["price"] = pd.to_numeric(s["price"], errors="coerce")
    s = s.dropna(subset=["dt", "code", "price"]).sort_values("dt").drop_duplicates("code")
    return [{"date": date, "code": r.code, "dt": r.dt, "entry": float(r.price)} for r in s.itertuples()]


def add_outcomes(entries: list[dict], m: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        c = m[(m["code"] == e["code"]) & (m["dt"] >= e["dt"])].copy()
        if c.empty or e["entry"] <= 0:
            continue
        row = dict(e)
        for horizon in (10, 20):
            target = e["dt"] + pd.Timedelta(minutes=horizon)
            q = c[(c["dt"] >= target) & (c["dt"] <= target + pd.Timedelta(minutes=3))]
            row[f"ret_{horizon}m"] = None if q.empty else (float(q.iloc[0]["close"]) / e["entry"] - 1.0) * 100.0
        row["ret_close"] = (float(c.iloc[-1]["close"]) / e["entry"] - 1.0) * 100.0
        row["max_gain"] = (float(c["high"].max()) / e["entry"] - 1.0) * 100.0
        row["dt"] = e["dt"].isoformat()
        out.append(row)
    return out


def metrics(rows: list[dict]) -> dict:
    answer = {"signals": len(rows)}
    for key in ("ret_10m", "ret_20m", "ret_close", "max_gain"):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        answer[key] = {
            "n": len(vals),
            "avg_gross_pct": None if not vals else round(sum(vals) / len(vals), 4),
            "win_rate_gross_pct": None if not vals else round(100.0 * sum(v > 0 for v in vals) / len(vals), 2),
        }
        if key != "max_gain":
            answer[key]["avg_after_0.38pct_cost"] = None if not vals else round(sum(v - ROUND_TRIP_COST_PCT for v in vals) / len(vals), 4)
            answer[key]["win_rate_after_cost_pct"] = None if not vals else round(100.0 * sum(v > ROUND_TRIP_COST_PCT for v in vals) / len(vals), 2)
    return answer


def main() -> int:
    daily = load_daily()
    current: list[dict] = []
    trend: list[dict] = []
    source_paths = [DATA / "eod_daily_bars.csv"]
    per_date = {}
    for date in DATES:
        minute_path = DATA / f"prices_1m_clean_{date}.csv"
        signal_path = SHADOW / f"strategy_01_open_surge_signal_{date}.csv"
        source_paths.extend([minute_path, signal_path])
        m = load_minutes(date)
        prior = prior_daily_rows(daily, date)
        c_rows = add_outcomes(current_s01_entries(date), m)
        t_rows = add_outcomes(first_trend_entries(date, m, prior), m)
        current.extend(c_rows)
        trend.extend(t_rows)
        per_date[str(date)] = {"current_s01": len(c_rows), "proposed_trend_lane": len(t_rows)}

    engine_paths = [
        ROOT / "RUN" / "strategy_01_open_surge_signal_v2.py",
        ROOT / "RUN" / "strategy_01_rotation_engine_v2.py",
    ]
    report = {
        "provenance": "[HYPOTHETICAL]",
        "production_code_changed": "NOT_CHANGED",
        "scope": "fixed-horizon entry-quality comparison; not common live sell replay",
        "dates": list(DATES),
        "criteria": {
            "daily": "prior close>MA5>MA20>MA60; MA5/MA20 rising; 5d return>=5%; 5d avg volume/value>=20d",
            "intraday": "3m MA5>MA10>MA20; prior-3-bar pullback holds MA20 and touches MA10 zone; close rebreaks prior-3-bar high; 10:00-14:30; gap -3%..+10%; <=8% above MA20",
        },
        "per_date": per_date,
        "current_s01": metrics(current),
        "proposed_trend_lane": metrics(trend),
        "source_hashes": {str(p): sha256(p) for p in source_paths},
        "capture_engine_hashes": {str(p): sha256(p) for p in engine_paths},
        "analysis_script_hash": sha256(Path(__file__)),
        "command": r"C:\python310\python.exe -X utf8 tests\hypothetical_s01_trend_lane_compare_20260818.py",
        "rows": {"current_s01": current, "proposed_trend_lane": trend},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "provenance": report["provenance"],
        "current_s01": report["current_s01"],
        "proposed_trend_lane": report["proposed_trend_lane"],
        "per_date": per_date,
        "report": str(REPORT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EOD = ROOT / "data" / "eod_daily_bars.csv"
SIGNAL_DIR = ROOT / "data" / "shadow"
MINUTE_DIR = ROOT / "data" / "intraday_close_archive"
OUTPUT = ROOT / "data" / "research_reports" / "high_range_cycle_intraday_s01_20260821.json"
COST_PCT = 0.47
HORIZONS = (5, 15, 30, 60)


def _summary(frame: pd.DataFrame, mask: pd.Series) -> dict:
    selected = frame.loc[mask]
    out = {"signals": int(mask.sum()), "complete_60m": int(selected["net_60m"].notna().sum())}
    for horizon in HORIZONS:
        values = selected[f"net_{horizon}m"].dropna()
        out[f"observed_{horizon}m"] = int(len(values))
        out[f"mean_net_{horizon}m_pct"] = round(float(values.mean()), 6) if len(values) else None
        out[f"median_net_{horizon}m_pct"] = round(float(values.median()), 6) if len(values) else None
        out[f"win_rate_net_{horizon}m_pct"] = round(float((values > 0).mean() * 100), 4) if len(values) else None
    for field in ("mfe_60m_pct", "mae_60m_pct"):
        values = selected[field].dropna()
        out[f"mean_{field}"] = round(float(values.mean()), 6) if len(values) else None
        out[f"median_{field}"] = round(float(values.median()), 6) if len(values) else None
    return out


def run() -> dict:
    signal_frames = []
    for path in sorted(SIGNAL_DIR.glob("strategy_01_open_surge_signal_2026*.csv")):
        date_text = path.stem.rsplit("_", 1)[-1]
        minute_path = MINUTE_DIR / f"prices_1m_{date_text}.csv"
        if not minute_path.exists():
            continue
        part = pd.read_csv(path, dtype={"code": str})
        if "action" in part:
            part = part[part["action"].astype(str).eq("BUY_READY")]
        if part.empty:
            continue
        part["signal_ts"] = pd.to_datetime(part["ts"], errors="coerce")
        part["signal_date"] = pd.to_datetime(date_text, format="%Y%m%d")
        part["minute_path"] = str(minute_path)
        signal_frames.append(part[["code", "signal_ts", "signal_date", "minute_path"]])
    signals = pd.concat(signal_frames, ignore_index=True).dropna(subset=["signal_ts"])
    signals["code"] = signals["code"].astype(str).str.zfill(6)

    eod = pd.read_csv(
        EOD, usecols=["date", "code", "open", "high", "low", "close"],
        dtype={"date": str, "code": str})
    for field in ("open", "high", "low", "close"):
        eod[field] = pd.to_numeric(eod[field], errors="coerce")
    eod = eod.dropna().sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    eod["date_dt"] = pd.to_datetime(eod["date"], format="%Y%m%d", errors="coerce")
    group = eod.groupby("code", sort=False, group_keys=False)
    eod["prev_close"] = group["close"].shift(1)
    eod["range_pct"] = (eod["high"] - eod["low"]) / eod["prev_close"] * 100.0
    eod["ma20"] = group["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    eod["ma20_slope5"] = eod["ma20"] - group["ma20"].shift(5)
    eod["prior_burst"] = group["range_pct"].transform(lambda s: s.shift(3).rolling(6, min_periods=6).max())
    eod["contraction2"] = group["range_pct"].transform(lambda s: s.shift(1).rolling(2, min_periods=2).mean())
    eod["trend20"] = (eod["close"] > eod["ma20"]) & (eod["ma20_slope5"] > 0)
    eod["cycle10"] = (eod["prior_burst"] >= 10.0) & (eod["contraction2"] <= eod["prior_burst"] * 0.70)

    signals = signals.sort_values(["signal_date", "code"])
    eod_join = eod[["code", "date_dt", "trend20", "cycle10", "prior_burst", "contraction2"]].sort_values(["date_dt", "code"])
    signals = pd.merge_asof(
        signals.sort_values(["signal_date", "code"]),
        eod_join,
        left_on="signal_date", right_on="date_dt", by="code",
        direction="backward", allow_exact_matches=False,
    )
    for horizon in HORIZONS:
        signals[f"net_{horizon}m"] = pd.NA
    signals["mfe_60m_pct"] = pd.NA
    signals["mae_60m_pct"] = pd.NA

    for minute_path, indices in signals.groupby("minute_path").groups.items():
        minute = pd.read_csv(
            minute_path, usecols=["code", "ts", "open", "high", "low", "close"],
            dtype={"code": str, "ts": str})
        minute["code"] = minute["code"].astype(str).str.zfill(6)
        minute["bar_ts"] = pd.to_datetime(minute["ts"], format="%Y%m%d%H%M%S", errors="coerce")
        for index in indices:
            row = signals.loc[index]
            bars = minute[(minute["code"] == row["code"]) & (minute["bar_ts"] > row["signal_ts"])].sort_values("bar_ts")
            if bars.empty:
                continue
            entry = bars.iloc[0]
            entry_price = float(entry["open"])
            window = bars[bars["bar_ts"] < entry["bar_ts"] + pd.Timedelta(minutes=60)]
            if entry_price <= 0 or window.empty:
                continue
            signals.at[index, "mfe_60m_pct"] = (float(window["high"].max()) / entry_price - 1.0) * 100.0
            signals.at[index, "mae_60m_pct"] = (float(window["low"].min()) / entry_price - 1.0) * 100.0
            for horizon in HORIZONS:
                target = entry["bar_ts"] + pd.Timedelta(minutes=horizon - 1)
                exits = window[window["bar_ts"] >= target]
                if exits.empty:
                    continue
                exit_price = float(exits.iloc[0]["close"])
                signals.at[index, f"net_{horizon}m"] = (exit_price / entry_price - 1.0) * 100.0 - COST_PCT

    for field in [f"net_{h}m" for h in HORIZONS] + ["mfe_60m_pct", "mae_60m_pct"]:
        signals[field] = pd.to_numeric(signals[field], errors="coerce")
    trend = signals["trend20"].fillna(False).astype(bool)
    cycle = signals["cycle10"].fillna(False).astype(bool)
    result = {
        "schema": "high_range_cycle_intraday_s01_v1",
        "provenance": "[HYPOTHETICAL]",
        "performance_scope": "S01_SIGNAL_NEXT_1M_OPEN_FIXED_HORIZON_NOT_PRODUCTION_EXIT",
        "source": [str(EOD), str(SIGNAL_DIR), str(MINUTE_DIR)],
        "cost_pct": COST_PCT,
        "signal_date_min": signals["signal_ts"].min().isoformat(),
        "signal_date_max": signals["signal_ts"].max().isoformat(),
        "all_s01": _summary(signals, pd.Series(True, index=signals.index)),
        "trend20": _summary(signals, trend),
        "trend20_cycle10": _summary(signals, trend & cycle),
        "definitions": {
            "entry": "first 1-minute bar open strictly after S01 BUY_READY timestamp",
            "exits": "bar close at 5/15/30/60 minutes after entry",
            "trend20": "previous EOD close>MA20 and MA20 slope over five sessions positive",
            "cycle10": "previous EOD has >=10% range burst in t-8..t-3 and two-session range contraction <=70%",
        },
        "limitations": [
            "Fixed-horizon exits are not the production common exit engine",
            "Historical S01 signal files do not contain complete high-range quality telemetry",
            "This test evaluates S01 only; S02-S06 require their own entry contracts",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

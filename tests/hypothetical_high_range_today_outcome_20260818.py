"""Summarize today's order-zero high-range low-shadow signals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
DATE = "20260818"
REPORT = DATA / "LOG" / f"high_range_outcome_{DATE}.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "avg_pct": None if not values else round(sum(values) / len(values), 4),
        "win_rate_pct": None if not values else round(100 * sum(v > 0 for v in values) / len(values), 2),
    }


def main() -> int:
    board_path = DATA / "common_high_range_top30.json"
    state_path = DATA / "high_range_top5_low_shadow_state.json"
    minute_path = DATA / f"prices_1m_clean_{DATE}.csv"
    daily_path = DATA / "eod_daily_bars.csv"
    engine_path = ROOT / "RUN" / "strategy_high_range_top5_low_shadow_v1.py"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    signals = [r for r in state.get("signals", []) if str(r.get("date")) == DATE]

    first_by_code = {}
    for row in sorted(signals, key=lambda r: str(r.get("signal_at") or "")):
        first_by_code.setdefault(str(row.get("code") or "").zfill(6), row)

    m = pd.read_csv(minute_path, usecols=["code", "ts", "close"], dtype={"code": str})
    m["code"] = m["code"].str.replace(r"\.0$", "", regex=True).str.zfill(6)
    m["dt"] = pd.to_datetime(m["ts"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    m["close"] = pd.to_numeric(m["close"], errors="coerce")

    daily = pd.read_csv(daily_path, usecols=["date", "code", "close"], dtype={"code": str}, low_memory=False)
    daily["code"] = daily["code"].str.replace(r"\.0$", "", regex=True).str.zfill(6)
    daily["date"] = pd.to_numeric(daily["date"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna().sort_values(["code", "date"])
    dg = daily.groupby("code", group_keys=False)
    for n in (5, 20, 60):
        daily[f"ma{n}"] = dg["close"].transform(lambda s, n=n: s.rolling(n).mean())
    daily["ma5_prev"] = dg["ma5"].shift(1)
    daily["ma20_prev"] = dg["ma20"].shift(1)
    source_date = int(state.get("source_date") or 0)
    prior = daily[daily["date"] == source_date].set_index("code")

    rows = []
    for code, signal in first_by_code.items():
        at = pd.Timestamp(signal["signal_at"])
        price = float(signal["signal_price"])
        q = m[(m["code"] == code) & (m["dt"] >= at + pd.Timedelta(minutes=20)) &
              (m["dt"] <= at + pd.Timedelta(minutes=23))]
        ret20 = None if q.empty else (float(q.iloc[0]["close"]) / price - 1) * 100
        last = float(signal.get("last_price") or 0)
        max_after = float(signal.get("max_after") or 0)
        min_after = float(signal.get("min_after") or 0)
        rows.append({
            "code": code,
            "name": signal.get("name"),
            "rank": signal.get("rank"),
            "signal_at": signal.get("signal_at"),
            "signal_price": price,
            "ret_20m_pct": None if ret20 is None else round(ret20, 4),
            "ret_final_pct": round((last / price - 1) * 100, 4),
            "max_after_pct": round((max_after / price - 1) * 100, 4),
            "min_after_pct": round((min_after / price - 1) * 100, 4),
            "daily_trend_ok": bool(
                code in prior.index
                and prior.at[code, "close"] > prior.at[code, "ma5"]
                and prior.at[code, "ma5"] > prior.at[code, "ma20"]
                and prior.at[code, "ma20"] > prior.at[code, "ma60"]
                and prior.at[code, "ma5"] > prior.at[code, "ma5_prev"]
                and prior.at[code, "ma20"] > prior.at[code, "ma20_prev"]
            ),
        })

    ret20 = [float(r["ret_20m_pct"]) for r in rows if r["ret_20m_pct"] is not None]
    final = [float(r["ret_final_pct"]) for r in rows]
    trend_rows = [r for r in rows if r["daily_trend_ok"]]
    trend_ret20 = [float(r["ret_20m_pct"]) for r in trend_rows if r["ret_20m_pct"] is not None]
    trend_final = [float(r["ret_final_pct"]) for r in trend_rows]
    report = {
        "provenance": "[HYPOTHETICAL]",
        "production_code_changed": "NOT_CHANGED",
        "date": DATE,
        "high_range_board_candidates": len(board.get("candidates") or []),
        "low_shadow_qualified_universe": len(state.get("universe") or []),
        "signal_events": len(signals),
        "unique_signal_codes": len(rows),
        "first_signal_per_code_ret_20m": stats(ret20),
        "first_signal_per_code_ret_final": stats(final),
        "daily_trend_filter": "source-date close>MA5>MA20>MA60 and MA5/MA20 rising",
        "trend_filtered_codes": len(trend_rows),
        "trend_filtered_ret_20m": stats(trend_ret20),
        "trend_filtered_ret_final": stats(trend_final),
        "rows": rows,
        "source_hashes": {
            str(board_path): sha(board_path),
            str(state_path): sha(state_path),
            str(minute_path): sha(minute_path),
            str(daily_path): sha(daily_path),
        },
        "capture_engine_hash": sha(engine_path),
        "analysis_script_hash": sha(Path(__file__)),
        "command": r"C:\python310\python.exe -X utf8 tests\hypothetical_high_range_today_outcome_20260818.py",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "source_hashes"}}, ensure_ascii=False, indent=2))
    print(json.dumps(sorted(rows, key=lambda r: r["ret_final_pct"], reverse=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

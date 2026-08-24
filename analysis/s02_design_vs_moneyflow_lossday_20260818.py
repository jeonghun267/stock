# -*- coding: utf-8 -*-
"""2026-08-18 11:33 S02 1승10패 구간 재판정 (분석 전용)."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAY = "20260818"
CUTOFF = datetime.fromisoformat("2026-08-18 11:33:59")
SIGNALS = ROOT / "data" / "strategy_02_signal_v1" / f"strategy_02_signals_{DAY}.csv"
LOWBUY = ROOT / "data" / "lowbuy_shadow" / f"lowbuy_shadow_{DAY}.json"
REGIME = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
ROTATION = ROOT / "LOG" / "strategy_02_rotation_v1.log"
FILLS = ROOT / "LOG" / f"fills_{DAY}.csv"
OUT = ROOT / "analysis" / "s02_design_vs_moneyflow_lossday_20260818.json"

BUY_RE = re.compile(
    r"^\[(?P<ts>2026-08-18 [0-9:]+)\].* BUY_CONFIRMED .*\((?P<code>\d{6})\) x(?P<qty>\d+) (?P<px>[0-9.]+)"
)
SELL_RE = re.compile(
    r"^\[(?P<ts>2026-08-18 [0-9:]+)\].* SELL_CONFIRMED .*\((?P<code>\d{6})\) x\d+ (?P<px>[0-9.]+) (?P<reason>.*?) cycle=.*?gross=(?P<gross>[-0-9.]+)%"
)


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_regimes():
    rows = []
    with REGIME.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            try:
                ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            if ts.strftime("%Y%m%d") == DAY:
                rows.append({"ts": ts, "u201": f(row.get("u201_chg")),
                             "band": row.get("band_us") or row.get("band") or "UNKNOWN"})
    return sorted(rows, key=lambda x: x["ts"])


def regime_at(rows, ts):
    prior = [r for r in rows if r["ts"] <= ts]
    return prior[-1] if prior else {"ts": None, "u201": 0.0, "band": "UNKNOWN"}


def group(band):
    if band in {"BULL", "LEAN_BULL", "LEAN_BULL_US"}:
        return "STRONG"
    if band in {"BEAR", "LEAN_BEAR", "LEAN_BEAR_US"}:
        return "WEAK"
    return "NORMAL"


def load_signals():
    low = json.loads(LOWBUY.read_text(encoding="utf-8-sig"))["codes"]
    regimes = load_regimes()
    out = []
    with SIGNALS.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            ts = datetime.fromisoformat(row["ts"])
            if ts > CUTOFF:
                continue
            code = str(row["code"]).zfill(6)
            info = low.get(code, {})
            anchor = f(row.get("anchor_low") or row.get("low_price"))
            price = f(row.get("price"))
            open_px = f(info.get("open_px"))
            prev = f(info.get("prev_close"))
            premium = (price / anchor - 1) * 100 if anchor else None
            low_open = (anchor / open_px - 1) * 100 if open_px else None
            low_prev = (anchor / prev - 1) * 100 if prev else None
            reg = regime_at(regimes, ts)
            rg = group(reg["band"])
            avg_range = f(row.get("hr_avg5_range"))
            rel = low_open - reg["u201"] if low_open is not None else None
            ratio = abs(min(0.0, rel)) / avg_range if rel is not None and avg_range else None
            alg = row.get("algorithm", "")
            direct = "DIRECT_REBOUND" in alg
            staircase = "STAIRCASE_RETEST" in alg
            observe = f(row.get("observe_sec"))
            fast = bool(rg == "STRONG" and direct and ratio is not None and ratio <= 0.25
                        and premium is not None and premium <= 1.5)
            retest = bool(staircase and premium is not None and premium <= 2.0
                          and (rg != "WEAK" or observe >= 300.0))
            mf = bool(low_prev is not None and low_prev <= -5.0
                      and premium is not None and 1.5 <= premium <= 3.0)
            out.append({
                "ts": row["ts"], "dt": ts, "code": code, "name": row.get("name", ""),
                "regime": reg["band"], "regime_group": rg, "algorithm": alg,
                "entry_above_anchor_pct": round(premium, 4) if premium is not None else None,
                "low_from_prev_close_pct": round(low_prev, 4) if low_prev is not None else None,
                "relative_weakness_ratio": round(ratio, 4) if ratio is not None else None,
                "new_design_pass": fast or retest,
                "new_design_lane": "FAST" if fast else ("RETEST" if retest else "BLOCK"),
                "moneyflow_proxy_pass": mf,
            })
    return out


def load_fills():
    rows = []
    with FILLS.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            rows.append({"ts": row["ts"], "dt": datetime.fromisoformat(row["ts"]),
                         "code": str(row["code"]).zfill(6), "side": row["otype"],
                         "qty": int(row["fill_qty"]), "px": f(row["fill_px"]),
                         "order_no": row["order_no"]})
    return rows


def nearest(fills, code, side, when):
    choices = [r for r in fills if r["code"] == code and r["side"] == side]
    if not choices:
        return None
    row = min(choices, key=lambda r: abs((r["dt"] - when).total_seconds()))
    return row if abs((row["dt"] - when).total_seconds()) <= 12 else None


def load_trades(signals, fills):
    trades, open_by_code = [], {}
    for line in ROTATION.read_text(encoding="utf-8", errors="replace").splitlines():
        mb = BUY_RE.match(line)
        if mb:
            dt = datetime.fromisoformat(mb.group("ts"))
            if dt > CUTOFF:
                continue
            trade = {"code": mb.group("code"), "buy_dt": dt, "buy_ts": mb.group("ts"),
                     "engine_buy_px": f(mb.group("px")), "qty": int(mb.group("qty")),
                     "sell_ts": None, "sell_reason": None, "gross_pct": None}
            trades.append(trade)
            open_by_code[trade["code"]] = trade
            continue
        ms = SELL_RE.match(line)
        if ms:
            dt = datetime.fromisoformat(ms.group("ts"))
            if dt > CUTOFF or ms.group("code") not in open_by_code:
                continue
            trade = open_by_code.pop(ms.group("code"))
            trade.update({"sell_ts": ms.group("ts"), "sell_dt": dt,
                          "sell_reason": ms.group("reason"), "gross_pct": f(ms.group("gross"))})

    out = []
    for trade in trades:
        prior = [s for s in signals if s["code"] == trade["code"] and s["dt"] <= trade["buy_dt"]]
        signal = max(prior, key=lambda s: s["dt"]) if prior else None
        if signal and (trade["buy_dt"] - signal["dt"]).total_seconds() > 90:
            signal = None
        bf = nearest(fills, trade["code"], "+매수", trade["buy_dt"])
        sf = nearest(fills, trade["code"], "-매도", trade.get("sell_dt")) if trade.get("sell_dt") else None
        out.append({
            "provenance": "[BROKER_FILL]" if bf else "[UNVERIFIED]",
            "code": trade["code"], "buy_ts": bf["ts"] if bf else trade["buy_ts"],
            "buy_qty": bf["qty"] if bf else trade["qty"], "buy_px": bf["px"] if bf else trade["engine_buy_px"],
            "buy_order_no": bf["order_no"] if bf else None,
            "sell_ts": sf["ts"] if sf else trade["sell_ts"], "sell_px": sf["px"] if sf else None,
            "sell_order_no": sf["order_no"] if sf else None,
            "gross_pct_from_engine": trade["gross_pct"], "sell_reason": trade["sell_reason"],
            "signal_ts": signal["ts"] if signal else None,
            "new_design_pass": signal["new_design_pass"] if signal else None,
            "new_design_lane": signal["new_design_lane"] if signal else None,
            "moneyflow_proxy_pass": signal["moneyflow_proxy_pass"] if signal else None,
            "regime": signal["regime"] if signal else None,
        })
    return out


def main():
    signals = load_signals()
    trades = load_trades(signals, load_fills())
    closed = [r for r in trades if r["gross_pct_from_engine"] is not None]
    wins = [r for r in closed if r["gross_pct_from_engine"] > 0]
    losses = [r for r in closed if r["gross_pct_from_engine"] <= 0]
    selected = [r for r in closed if r["new_design_pass"]]
    mf_selected = [r for r in closed if r["moneyflow_proxy_pass"]]
    report = {
        "provenance": "[HYPOTHETICAL]",
        "date": DAY, "cutoff": CUTOFF.isoformat(), "production_code_changed": "NOT_CHANGED",
        "sources": [str(SIGNALS), str(LOWBUY), str(REGIME), str(ROTATION), str(FILLS)],
        "command": r"C:\python310\python.exe analysis\s02_design_vs_moneyflow_lossday_20260818.py",
        "actual_s02": {"closed": len(closed), "wins": len(wins), "losses": len(losses)},
        "new_design": {
            "would_buy": len(selected),
            "wins_in_selected_actual_outcomes": sum(r["gross_pct_from_engine"] > 0 for r in selected),
            "losses_in_selected_actual_outcomes": sum(r["gross_pct_from_engine"] <= 0 for r in selected),
            "actual_losses_blocked": sum(not bool(r["new_design_pass"]) for r in losses),
        },
        "moneyflow_proxy": {
            "would_buy": len(mf_selected),
            "wins_in_selected_actual_outcomes": sum(r["gross_pct_from_engine"] > 0 for r in mf_selected),
            "losses_in_selected_actual_outcomes": sum(r["gross_pct_from_engine"] <= 0 for r in mf_selected),
            "actual_losses_blocked": sum(not bool(r["moneyflow_proxy_pass"]) for r in losses),
        },
        "rows": trades,
        "limitations": [
            "새 설계는 저장된 실제 S02 신호에 사후 대입한 주문0 가정이다.",
            "돈맥 프록시는 -5% 등재와 저점+1.5~3% 창만 포함하고 돈유입/3연속 양봉은 포함하지 않는다.",
            "선택하지 않은 S02 신호가 별도 수익 기회를 만들었는지는 이 실제매수 대조에서 측정하지 않는다.",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("actual_s02", "new_design", "moneyflow_proxy")}, ensure_ascii=False))
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

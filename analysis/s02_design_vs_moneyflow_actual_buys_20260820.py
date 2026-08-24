# -*- coding: utf-8 -*-
"""2026-08-20 S02 실제 매수에 새 설계와 돈맥 프록시를 대입한다.

분석 전용 [HYPOTHETICAL]. 생산 주문 경로는 변경하거나 실행하지 않는다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAY = "20260820"
SIGNALS = ROOT / "data" / "strategy_02_signal_v1" / f"strategy_02_signals_{DAY}.csv"
ADAPTIVE = ROOT / "analysis" / f"s02_regime_adaptive_vs_moneyflow_proxy_{DAY}.json"
ROTATION = ROOT / "LOG" / "strategy_02_rotation_v1.log"
FILLS = ROOT / "LOG" / f"fills_{DAY}.csv"
EVENTS = ROOT / "LOG" / f"event_journal_{DAY}.jsonl"
S02_ENGINE = ROOT / "RUN" / "strategy_02_low_buy_signal_v1.py"
MF_ENGINE = ROOT / "RUN" / "money_flow_exec_v1.py"
OUT = ROOT / "analysis" / f"s02_design_vs_moneyflow_actual_buys_{DAY}.json"

BUY_RE = re.compile(
    r"^\[(?P<ts>2026-08-20 [0-9:]+)\].* BUY_CONFIRMED .*\((?P<code>\d{6})\) x(?P<qty>\d+) (?P<px>[0-9.]+)"
)
SELL_RE = re.compile(
    r"^\[(?P<ts>2026-08-20 [0-9:]+)\].* SELL_CONFIRMED .*\((?P<code>\d{6})\) x\d+ (?P<px>[0-9.]+) (?P<reason>.*?) cycle=.*?gross=(?P<gross>[-0-9.]+)%"
)


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_signals():
    context_rows = json.loads(ADAPTIVE.read_text(encoding="utf-8"))["rows"]
    context = {(r["ts"], r["code"]): r for r in context_rows}
    out = []
    with SIGNALS.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            code = str(row["code"]).zfill(6)
            ctx = context[(row["ts"], code)]
            anchor = f(row.get("anchor_low") or row.get("low_price"))
            price = f(row.get("price"))
            premium = (price / anchor - 1.0) * 100.0 if anchor else None
            alg = row.get("algorithm", "")
            direct = "DIRECT_REBOUND" in alg
            staircase = "STAIRCASE_RETEST" in alg
            group = ctx["regime_group"]
            weak_ratio = ctx.get("relative_weakness_ratio")
            observe = f(row.get("observe_sec"))

            fast = bool(
                group == "STRONG" and direct and weak_ratio is not None
                and weak_ratio <= 0.25 and premium is not None and premium <= 1.5
            )
            retest = bool(
                staircase and premium is not None and premium <= 2.0
                and (group != "WEAK" or observe >= 300.0)
            )
            design_pass = fast or retest
            depth = ctx.get("low_from_prev_close_pct")
            # 돈맥 전체가 아닌 핵심 등재+진입가격창 프록시. 실제 돈유입/3연속 양봉은 미포함.
            moneyflow_proxy = bool(
                depth is not None and depth <= -5.0
                and premium is not None and 1.5 <= premium <= 3.0
            )
            out.append({
                "ts": row["ts"], "dt": datetime.fromisoformat(row["ts"]),
                "code": code, "name": row.get("name", ""), "algorithm": alg,
                "regime_group": group, "relative_weakness_ratio": weak_ratio,
                "entry_above_anchor_pct": round(premium, 4) if premium is not None else None,
                "low_from_prev_close_pct": depth,
                "new_design_pass": design_pass,
                "new_design_lane": "FAST" if fast else ("RETEST" if retest else "BLOCK"),
                "moneyflow_proxy_pass": moneyflow_proxy,
            })
    return out


def load_engine_trades():
    trades = []
    open_by_code = {}
    for line in ROTATION.read_text(encoding="utf-8", errors="replace").splitlines():
        mb = BUY_RE.match(line)
        if mb:
            trade = {
                "buy_ts": mb.group("ts"), "buy_dt": datetime.fromisoformat(mb.group("ts")),
                "code": mb.group("code"), "qty": int(mb.group("qty")),
                "engine_buy_px": f(mb.group("px")), "sell_ts": None,
                "engine_sell_px": None, "sell_reason": None, "gross_pct": None,
            }
            trades.append(trade)
            open_by_code[trade["code"]] = trade
            continue
        ms = SELL_RE.match(line)
        if ms and ms.group("code") in open_by_code:
            trade = open_by_code.pop(ms.group("code"))
            trade.update({
                "sell_ts": ms.group("ts"), "engine_sell_px": f(ms.group("px")),
                "sell_reason": ms.group("reason"), "gross_pct": f(ms.group("gross")),
            })
    return trades


def load_fills():
    out = []
    with FILLS.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            out.append({
                "ts": row["ts"], "dt": datetime.fromisoformat(row["ts"]),
                "code": str(row["code"]).zfill(6), "side": row["otype"],
                "qty": int(row["fill_qty"]), "px": f(row["fill_px"]),
                "order_no": row["order_no"],
            })
    return out


def nearest(items, code, side, when, max_sec=12):
    choices = [r for r in items if r["code"] == code and r["side"] == side]
    if not choices:
        return None
    row = min(choices, key=lambda r: abs((r["dt"] - when).total_seconds()))
    return row if abs((row["dt"] - when).total_seconds()) <= max_sec else None


def main() -> int:
    signals = load_signals()
    fills = load_fills()
    trades = load_engine_trades()
    actual = []
    for trade in trades:
        prior = [s for s in signals if s["code"] == trade["code"] and s["dt"] <= trade["buy_dt"]]
        signal = max(prior, key=lambda s: s["dt"]) if prior else None
        if signal and (trade["buy_dt"] - signal["dt"]).total_seconds() > 90:
            signal = None
        buy_fill = nearest(fills, trade["code"], "+매수", trade["buy_dt"])
        sell_dt = datetime.fromisoformat(trade["sell_ts"]) if trade["sell_ts"] else None
        sell_fill = nearest(fills, trade["code"], "-매도", sell_dt) if sell_dt else None
        actual.append({
            "provenance": "[BROKER_FILL]" if buy_fill else "[UNVERIFIED]",
            "code": trade["code"], "buy_ts": buy_fill["ts"] if buy_fill else trade["buy_ts"],
            "buy_qty": buy_fill["qty"] if buy_fill else trade["qty"],
            "buy_px": buy_fill["px"] if buy_fill else trade["engine_buy_px"],
            "buy_order_no": buy_fill["order_no"] if buy_fill else None,
            "sell_ts": sell_fill["ts"] if sell_fill else trade["sell_ts"],
            "sell_px": sell_fill["px"] if sell_fill else trade["engine_sell_px"],
            "sell_order_no": sell_fill["order_no"] if sell_fill else None,
            "sell_reason": trade["sell_reason"], "gross_pct_from_engine": trade["gross_pct"],
            "signal_ts": signal["ts"] if signal else None,
            "new_design_pass": signal["new_design_pass"] if signal else None,
            "new_design_lane": signal["new_design_lane"] if signal else None,
            "moneyflow_proxy_pass": signal["moneyflow_proxy_pass"] if signal else None,
            "entry_above_anchor_pct": signal["entry_above_anchor_pct"] if signal else None,
            "regime_group": signal["regime_group"] if signal else None,
        })

    hard_stops = [r for r in actual if str(r["sell_reason"] or "").startswith("HARD_STOP")]
    design_selected = [r for r in actual if r["new_design_pass"]]
    mf_selected = [r for r in actual if r["moneyflow_proxy_pass"]]

    mflow_orders = []
    for line in EVENTS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") != "ORDER_SUBMITTED":
            continue
        entity = str(event.get("entity_id") or "")
        if not entity.startswith("mflow_buy_"):
            continue
        payload = event.get("payload") or {}
        when = datetime.fromisoformat(event["ts"])
        fill = nearest(fills, str(payload.get("code", "")).zfill(6), "+매수", when)
        mflow_orders.append({
            "provenance": "[BROKER_FILL]" if fill else "[UNVERIFIED]",
            "code": str(payload.get("code", "")).zfill(6),
            "submitted_ts": event["ts"],
            "fill_ts": fill["ts"] if fill else None,
            "fill_qty": fill["qty"] if fill else None,
            "fill_px": fill["px"] if fill else None,
            "order_no": fill["order_no"] if fill else None,
            "outcome": "[UNVERIFIED] 돈맥 매도 전 FLATACCT가 같은 종목을 먼저 매도해 소유성과 분리 불가",
        })

    report = {
        "provenance": "[HYPOTHETICAL]",
        "date": DAY,
        "production_code_changed": "NOT_CHANGED",
        "sources": [str(SIGNALS), str(ADAPTIVE), str(ROTATION), str(FILLS), str(EVENTS)],
        "engines": {str(S02_ENGINE): sha(S02_ENGINE), str(MF_ENGINE): sha(MF_ENGINE)},
        "command": r"C:\python310\python.exe analysis\s02_design_vs_moneyflow_actual_buys_20260820.py",
        "signal_comparison": {
            "s02_ready_signals": len(signals),
            "new_design_pass": sum(bool(s["new_design_pass"]) for s in signals),
            "moneyflow_proxy_pass": sum(bool(s["moneyflow_proxy_pass"]) for s in signals),
        },
        "actual_s02_comparison": {
            "actual_buys": len(actual),
            "new_design_would_buy": len(design_selected),
            "moneyflow_proxy_would_buy": len(mf_selected),
            "actual_hard_stops": len(hard_stops),
            "hard_stops_blocked_by_new_design": sum(not bool(r["new_design_pass"]) for r in hard_stops),
            "hard_stops_blocked_by_moneyflow_proxy": sum(not bool(r["moneyflow_proxy_pass"]) for r in hard_stops),
            "rows": actual,
        },
        "current_moneyflow_actual_buys": mflow_orders,
        "limitations": [
            "새 설계는 실제 S02 신호에 사후 대입한 주문0 가정이다.",
            "돈맥 프록시는 전일종가 -5%와 저점+1.5~3% 창만 사용하며 돈유입/3연속 양봉은 재현하지 못한다.",
            "오늘 장중 미완성이고 열린 S02 포지션의 성과는 결론 내리지 않는다.",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_comparison": report["signal_comparison"],
        "actual_s02_comparison": {k: v for k, v in report["actual_s02_comparison"].items() if k != "rows"},
    }, ensure_ascii=False))
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

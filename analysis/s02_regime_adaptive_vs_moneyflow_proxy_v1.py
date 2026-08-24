# -*- coding: utf-8 -*-
"""S02 장세적응형 저점안 vs 돈맥 깊이관문 비교 (분석 전용).

생산 엔진을 호출하지 않는 [HYPOTHETICAL] 비교다. S02가 실제로 낸 신호에
당시 시장 장세, 종목 시가/전일종가, 최근 5일 평균 변동폭을 결합한다.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAY = "20260820"
SIGNALS = ROOT / "data" / "strategy_02_signal_v1" / f"strategy_02_signals_{DAY}.csv"
LOWBUY = ROOT / "data" / "lowbuy_shadow" / f"lowbuy_shadow_{DAY}.json"
UNIVERSE = ROOT / "data" / "common_high_range_top30.json"
REGIME = ROOT / "data" / "BACKTEST" / "regime_std_shadow.csv"
S02_ENGINE = ROOT / "RUN" / "strategy_02_low_buy_signal_v1.py"
MF_ENGINE = ROOT / "RUN" / "money_flow_exec_v1.py"
OUT_JSON = ROOT / "analysis" / f"s02_regime_adaptive_vs_moneyflow_proxy_{DAY}.json"
OUT_CSV = ROOT / "analysis" / f"s02_regime_adaptive_vs_moneyflow_proxy_{DAY}.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_regimes() -> list[dict]:
    target = datetime.strptime(DAY, "%Y%m%d").date()
    out = []
    with REGIME.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            try:
                ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            if ts.date() == target:
                out.append({"ts": ts, "u201": f(row.get("u201_chg")),
                            "band": row.get("band_us") or row.get("band") or "UNKNOWN"})
    return sorted(out, key=lambda x: x["ts"])


def regime_at(rows: list[dict], ts: datetime) -> dict:
    prior = [row for row in rows if row["ts"] <= ts]
    return prior[-1] if prior else {"ts": None, "u201": 0.0, "band": "UNKNOWN"}


def regime_group(band: str) -> str:
    if band in {"BULL", "LEAN_BULL", "LEAN_BULL_US"}:
        return "STRONG"
    if band in {"BEAR", "LEAN_BEAR", "LEAN_BEAR_US"}:
        return "WEAK"
    return "NORMAL"


def main() -> int:
    lowbuy = json.loads(LOWBUY.read_text(encoding="utf-8-sig"))["codes"]
    board = json.loads(UNIVERSE.read_text(encoding="utf-8-sig"))
    meta = {str(row["code"]).zfill(6): row for row in board.get("candidates", [])}
    regimes = load_regimes()
    results = []

    with SIGNALS.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            code = str(row.get("code", "")).zfill(6)
            ts = datetime.fromisoformat(row["ts"])
            reg = regime_at(regimes, ts)
            group = regime_group(reg["band"])
            info = lowbuy.get(code, {})
            prev_close = f(info.get("prev_close") or meta.get(code, {}).get("prev_close"))
            open_px = f(info.get("open_px"))
            low_px = f(row.get("anchor_low") or row.get("low_price"))
            avg_range = f(meta.get(code, {}).get("avg_5d_range_pct"))
            low_from_prev = (low_px / prev_close - 1.0) * 100.0 if prev_close > 0 else None
            low_from_open = (low_px / open_px - 1.0) * 100.0 if open_px > 0 else None
            rel_low = low_from_open - reg["u201"] if low_from_open is not None else None
            weakness_ratio = (
                abs(min(0.0, rel_low)) / avg_range
                if rel_low is not None and avg_range > 0 else None
            )
            algorithm = row.get("algorithm", "")
            staircase = "STAIRCASE_RETEST" in algorithm
            observe_sec = f(row.get("observe_sec"))

            # 후보 규칙: 고정 낙폭은 쓰지 않는다. 강세장은 시장대비 약세가
            # 최근 변동폭의 25% 이내일 때만 직접반등, 그 외는 구조 재확인.
            if group == "STRONG":
                adaptive_pass = staircase or (
                    "DIRECT_REBOUND" in algorithm
                    and weakness_ratio is not None
                    and weakness_ratio <= 0.25
                )
                adaptive_reason = "STRONG_DIRECT_RELATIVE_OK" if not staircase else "STRONG_RETEST"
            elif group == "NORMAL":
                adaptive_pass = staircase
                adaptive_reason = "NORMAL_RETEST_REQUIRED"
            else:
                adaptive_pass = staircase and observe_sec >= 240.0
                adaptive_reason = "WEAK_LONG_RETEST_REQUIRED"

            # 돈맥 전체 재현이 아니라 핵심 후보등재(-5%)만 대입한 상한 비교다.
            moneyflow_depth_pass = low_from_prev is not None and low_from_prev <= -5.0
            results.append({
                "ts": row["ts"], "code": code, "name": row.get("name", ""),
                "algorithm": algorithm, "regime": reg["band"], "regime_group": group,
                "u201_pct": round(reg["u201"], 3),
                "low_from_open_pct": round(low_from_open, 3) if low_from_open is not None else None,
                "low_from_prev_close_pct": round(low_from_prev, 3) if low_from_prev is not None else None,
                "relative_low_pct": round(rel_low, 3) if rel_low is not None else None,
                "avg_5d_range_pct": avg_range,
                "relative_weakness_ratio": round(weakness_ratio, 4) if weakness_ratio is not None else None,
                "adaptive_pass": adaptive_pass, "adaptive_reason": adaptive_reason,
                "moneyflow_depth_pass": moneyflow_depth_pass,
            })

    fields = list(results[0]) if results else []
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "provenance": "[HYPOTHETICAL]",
        "date": DAY,
        "purpose": "생산 변경 전 S02 장세적응형 후보와 현행 돈맥 핵심 깊이관문 비교",
        "production_code_changed": "NOT_CHANGED",
        "limitations": [
            "적응형 규칙은 제안안이며 생산경로가 아니다.",
            "moneyflow_depth_pass는 현행 돈맥 전체가 아니라 전일종가 -5% 후보등재 관문만 적용한다.",
            "S02 신호는 이미 수급역전/가속 확인을 통과한 행만 포함하므로 미신호 종목의 기회손실은 측정하지 않는다.",
        ],
        "sources": [str(SIGNALS), str(LOWBUY), str(UNIVERSE), str(REGIME)],
        "engines": {str(S02_ENGINE): sha256(S02_ENGINE), str(MF_ENGINE): sha256(MF_ENGINE)},
        "command": r"C:\python310\python.exe analysis\s02_regime_adaptive_vs_moneyflow_proxy_v1.py",
        "counts": {
            "s02_signals": len(results),
            "adaptive_pass": sum(bool(r["adaptive_pass"]) for r in results),
            "moneyflow_depth_pass": sum(bool(r["moneyflow_depth_pass"]) for r in results),
            "both_pass": sum(bool(r["adaptive_pass"] and r["moneyflow_depth_pass"]) for r in results),
        },
        "rows": results,
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    print(OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

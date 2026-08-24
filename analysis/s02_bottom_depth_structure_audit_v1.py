# -*- coding: utf-8 -*-
"""S02 얕은 신호가 깊은 최종 저점을 놓치는지 구조별로 감사한다.

저장된 실제 S02 신호와 장중 저점 기록을 결합하는 분석 전용 도구다.
생산 엔진 재생이 아니므로 결과 provenance는 [HYPOTHETICAL]이다.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIR = ROOT / "data" / "strategy_02_signal_v1"
LOW_DIR = ROOT / "data" / "lowbuy_shadow"
OUT_JSON = ROOT / "analysis" / "s02_bottom_depth_structure_audit_v1.json"
OUT_CSV = ROOT / "analysis" / "s02_bottom_depth_structure_audit_v1.csv"
TODAY = datetime.now().strftime("%Y%m%d")


def f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(values, q):
    if not values:
        return None
    data = sorted(values)
    idx = (len(data) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(data) - 1)
    frac = idx - lo
    return data[lo] * (1 - frac) + data[hi] * frac


def structure(name: str) -> str:
    if "STAIRCASE_RETEST" in name:
        return "STAIRCASE"
    if "DIRECT_REBOUND" in name:
        return "DIRECT"
    return "OTHER"


def main() -> int:
    rows = []
    sources = []
    for signal_path in sorted(SIGNAL_DIR.glob("strategy_02_signals_*.csv")):
        day = signal_path.stem.rsplit("_", 1)[-1]
        low_path = LOW_DIR / f"lowbuy_shadow_{day}.json"
        if not low_path.exists() or day < "20260813":
            continue
        low_doc = json.loads(low_path.read_text(encoding="utf-8-sig"))
        lows = low_doc.get("codes", {})
        sources.extend([str(signal_path), str(low_path)])
        with signal_path.open(encoding="utf-8-sig", newline="") as fp:
            for raw in csv.DictReader(fp):
                code = str(raw.get("code", "")).zfill(6)
                info = lows.get(code)
                if not isinstance(info, dict):
                    continue
                final_low = f(info.get("low"))
                final_time = str(info.get("low_time") or "")
                anchor = f(raw.get("anchor_low") or raw.get("low_price"))
                entry = f(raw.get("price"))
                if min(final_low, anchor, entry) <= 0 or not final_time:
                    continue
                signal_ts = datetime.fromisoformat(raw["ts"])
                try:
                    final_ts = datetime.strptime(day + final_time[:8], "%Y%m%d%H:%M:%S")
                except ValueError:
                    continue
                anchor_to_final = (anchor / final_low - 1.0) * 100.0
                entry_to_final = (entry / final_low - 1.0) * 100.0
                rows.append({
                    "day": day,
                    "day_complete": day != TODAY,
                    "ts": raw["ts"],
                    "code": code,
                    "name": raw.get("name", ""),
                    "structure": structure(raw.get("algorithm", "")),
                    "algorithm": raw.get("algorithm", ""),
                    "signal_price": entry,
                    "anchor_low": anchor,
                    "final_observed_low": final_low,
                    "final_low_time": final_time,
                    "signal_before_final_low": signal_ts < final_ts,
                    "new_low_after_signal": final_low < anchor,
                    "final_low_deeper_2pct": anchor_to_final >= 2.0,
                    "anchor_above_final_low_pct": round(anchor_to_final, 4),
                    "entry_above_final_low_pct": round(entry_to_final, 4),
                    "entry_within_1pct": entry_to_final <= 1.0,
                    "entry_within_2pct": entry_to_final <= 2.0,
                    "entry_within_3pct": entry_to_final <= 3.0,
                })

    complete = [r for r in rows if r["day_complete"]]
    today = [r for r in rows if not r["day_complete"]]

    def group_stats(items):
        result = {}
        for kind in ("DIRECT", "STAIRCASE", "OTHER", "ALL"):
            group = items if kind == "ALL" else [r for r in items if r["structure"] == kind]
            premiums = [r["entry_above_final_low_pct"] for r in group]
            confirmed = [r for r in group if not r["signal_before_final_low"]]
            confirmed_premiums = [r["entry_above_final_low_pct"] for r in confirmed]
            result[kind] = {
                "signals": len(group),
                "new_low_after_signal": sum(bool(r["new_low_after_signal"]) for r in group),
                "new_low_after_signal_pct": round(
                    100 * sum(bool(r["new_low_after_signal"]) for r in group) / len(group), 2
                ) if group else None,
                "final_low_deeper_2pct": sum(bool(r["final_low_deeper_2pct"]) for r in group),
                "confirmed_after_final_low": len(confirmed),
                "entry_premium_median_pct": round(median(premiums), 3) if premiums else None,
                "confirmed_entry_premium_median_pct": round(median(confirmed_premiums), 3)
                if confirmed_premiums else None,
                "confirmed_entry_premium_p75_pct": round(pct(confirmed_premiums, 0.75), 3)
                if confirmed_premiums else None,
                "confirmed_within_1pct": sum(p <= 1.0 for p in confirmed_premiums),
                "confirmed_within_2pct": sum(p <= 2.0 for p in confirmed_premiums),
                "confirmed_within_3pct": sum(p <= 3.0 for p in confirmed_premiums),
            }
        return result

    # 첫 신호가 2% 이상 얕았던 종목이 나중 신호로 최종 저점을 다시 잡았는지 확인.
    by_code = defaultdict(list)
    for row in complete:
        by_code[(row["day"], row["code"])].append(row)
    deep_miss = []
    for (day, code), group in by_code.items():
        group.sort(key=lambda r: r["ts"])
        first = group[0]
        if not first["final_low_deeper_2pct"]:
            continue
        recovered = [r for r in group[1:] if not r["signal_before_final_low"]]
        deep_miss.append({
            "day": day, "code": code, "name": first["name"],
            "first_structure": first["structure"],
            "first_anchor_above_final_low_pct": first["anchor_above_final_low_pct"],
            "later_signal_after_final_low": bool(recovered),
            "later_best_entry_premium_pct": min(
                (r["entry_above_final_low_pct"] for r in recovered), default=None
            ),
        })

    if rows:
        with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    report = {
        "provenance": "[HYPOTHETICAL]",
        "production_code_changed": "NOT_CHANGED",
        "scope": "2026-08-13 이후 저장된 S02 신호와 최종 관측 저점; 오늘은 장중 미완성",
        "sources": sorted(set(sources)),
        "command": r"C:\python310\python.exe analysis\s02_bottom_depth_structure_audit_v1.py",
        "complete_days": sorted({r["day"] for r in complete}),
        "today_incomplete": TODAY,
        "complete_stats": group_stats(complete),
        "today_incomplete_stats": group_stats(today),
        "deep_miss_recovery": {
            "cases": len(deep_miss),
            "later_signal_after_final_low": sum(bool(r["later_signal_after_final_low"]) for r in deep_miss),
            "rows": deep_miss,
        },
        "limitations": [
            "최종 관측 저점은 사후정보이며 실시간으로 미리 알 수 없다.",
            "신호 품질 감사이며 매도 성과 백테스트가 아니다.",
            "오늘 자료는 장 마감 전이라 최종 저점이 바뀔 수 있다.",
        ],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "complete_days": report["complete_days"],
        "complete_stats": report["complete_stats"],
        "deep_miss_recovery": {k: v for k, v in report["deep_miss_recovery"].items() if k != "rows"},
    }, ensure_ascii=False))
    print(OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

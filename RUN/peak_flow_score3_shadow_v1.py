# -*- coding: utf-8 -*-
"""꼭지매도(PEAK_FLOW) "점수 3 이상만 매도" 그림자 기록기.

★[2026-08-19 친구님 지시 "점수 3 이상만 매도 그림자 기록 착수해"]
  8/13 백테심판: score=2 매도 13건 보류 시 30분 평균 +2.67%p(상방 10/12),
  단 이득의 71%가 강세일 하루에 몰림 → 그림자 병행 기록 권고가 안건이었다.
  8/19 사례 +1: S01 491000 score=2/4 매도 후 30분 +4.9%.

방식: 사후 그림자(실전 무개입). 마감 후 그날의 매도 감사에서
COMMON_PEAK_FLOW_EXIT 매도 전건을 읽어, 매도 후 +10/30/60분과 15:10 시점
가격을 고저폭 그림자 스냅샷으로 복원해 기록한다.
- score<3 행 = 새 규칙이 보류했을 매도(그림자 대상)
- score>=3 행 = 새 규칙에서도 팔았을 매도(비교군 — 비교군 전건 기록 원칙)

출력: data\peak_flow_score3_shadow.csv (날짜 재실행 시 그 날짜 행 교체)
읽기 전용 소스: data\audit\hold_sell\<날짜>\ · data\high_range_shadow_<날짜>.csv
· (보조) data\prices_1m.csv — 생산 파일 수정 없음.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
OUT = ROOT / "data" / "peak_flow_score3_shadow.csv"
FIELDS = [
    "date", "strategy", "code", "sell_hms", "score", "score_max",
    "would_hold", "exit_price", "pct_10m", "pct_30m", "pct_60m",
    "pct_1510", "pct_max_to_1510", "price_src", "reason", "generated_at",
]
_REASON = re.compile(r"COMMON_PEAK_FLOW_EXIT score=(\d+)/(\d+)")
_CYCLE = re.compile(r"cycle-(\d+)")


def _load_peak_flow_sells(day: str) -> list[dict]:
    base = ROOT / "data" / "audit" / "hold_sell" / day
    sells: dict[tuple, dict] = {}
    if not base.exists():
        return []
    for path in sorted(base.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            dec = row.get("decision") or {}
            reason = str(dec.get("reason") or "")
            match = _REASON.search(reason)
            if str(dec.get("action")) != "SELL" or not match:
                continue
            cycle_match = _CYCLE.search(str(dec.get("order_key") or ""))
            key = (
                str(dec.get("strategy_id") or ""),
                str(dec.get("code") or ""),
                cycle_match.group(1) if cycle_match else "?",
            )
            if key in sells:  # 재시도 중복 — 첫 판정만
                continue
            sells[key] = {
                "strategy": key[0],
                "code": key[1],
                "sell_ts": str(dec.get("observed_at") or row.get("captured_at")),
                "score": int(match.group(1)),
                "score_max": int(match.group(2)),
                "exit_price": float(dec.get("price") or 0),
                "reason": reason,
            }
    return list(sells.values())


def _load_snapshots(day: str) -> dict[str, list[tuple[datetime, float]]]:
    path = ROOT / "data" / f"high_range_shadow_{day}.csv"
    series: dict[str, list[tuple[datetime, float]]] = {}
    if not path.exists():
        return series
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                ts = datetime.fromisoformat(row["ts"])
                price = float(row["current"])
            except (KeyError, ValueError):
                continue
            if price > 0:
                series.setdefault(row["code"], []).append((ts, price))
    for values in series.values():
        values.sort(key=lambda p: p[0])
    return series


def _price_at(series: list[tuple[datetime, float]], when: datetime):
    """when 이후 첫 스냅샷 가격. 없으면 마지막(장 후반) 가격."""
    for ts, price in series:
        if ts >= when:
            return price
    return series[-1][1] if series else None


def _pct(price, base: float):
    if price is None or not base:
        return ""
    return round((float(price) - base) / base * 100, 3)


def build_rows(day: str) -> list[dict]:
    sells = _load_peak_flow_sells(day)
    snaps = _load_snapshots(day)
    stamp = datetime.now().isoformat(timespec="seconds")
    close_1510 = datetime.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}T15:10:00")
    rows = []
    for sell in sells:
        exit_dt = datetime.fromisoformat(sell["sell_ts"]).replace(tzinfo=None)
        series = snaps.get(sell["code"], [])
        after = [p for p in series if p[0] >= exit_dt]
        until_1510 = [p for p in after if p[0] <= close_1510]
        base = sell["exit_price"]
        rows.append({
            "date": day,
            "strategy": sell["strategy"],
            "code": sell["code"],
            "sell_hms": exit_dt.strftime("%H:%M:%S"),
            "score": sell["score"],
            "score_max": sell["score_max"],
            "would_hold": "Y" if sell["score"] < 3 else "N",
            "exit_price": base,
            "pct_10m": _pct(_price_at(series, exit_dt + timedelta(minutes=10)), base),
            "pct_30m": _pct(_price_at(series, exit_dt + timedelta(minutes=30)), base),
            "pct_60m": _pct(_price_at(series, exit_dt + timedelta(minutes=60)), base),
            "pct_1510": _pct(_price_at(series, close_1510), base),
            "pct_max_to_1510": _pct(
                max((p[1] for p in until_1510), default=None), base),
            "price_src": "high_range_shadow" if series else "미관측",
            "reason": sell["reason"],
            "generated_at": stamp,
        })
    return rows


def append_replacing_day(rows: list[dict], day: str) -> None:
    kept = []
    if OUT.exists():
        with open(OUT, encoding="utf-8-sig", newline="") as fh:
            kept = [r for r in csv.DictReader(fh) if r.get("date") != day]
    fd, tmp = tempfile.mkstemp(dir=str(OUT.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in kept + rows:
            writer.writerow(row)
    for attempt in range(6):  # WinError 5 대비 재시도 (프로젝트 표준 패턴)
        try:
            os.replace(tmp, OUT)
            return
        except PermissionError:
            if attempt == 5:
                raise
            import time
            time.sleep(0.2)


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    rows = build_rows(day)
    append_replacing_day(rows, day)
    held = [r for r in rows if r["would_hold"] == "Y"]
    comp = [r for r in rows if r["would_hold"] == "N"]

    def _avg(group, field):
        values = [float(r[field]) for r in group if r[field] != ""]
        return round(sum(values) / len(values), 3) if values else "-"

    print(f"[{day}] PEAK_FLOW 매도 {len(rows)}건 기록 → {OUT}")
    print(f"  보류 대상(score<3) {len(held)}건: 30분 평균 {_avg(held, 'pct_30m')}% "
          f"/ 15:10 평균 {_avg(held, 'pct_1510')}%")
    print(f"  비교군(score>=3) {len(comp)}건: 30분 평균 {_avg(comp, 'pct_30m')}%")
    missing = [r["code"] for r in rows if r["price_src"] == "미관측"]
    if missing:
        print(f"  ⚠️미관측(스냅샷 없음): {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

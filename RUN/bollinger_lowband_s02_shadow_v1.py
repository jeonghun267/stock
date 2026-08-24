# -*- coding: utf-8 -*-
"""볼린저 하단 × S02 그림자 기록기 (8/13 밤 친구님 승인 사양 · 8/19 착수 지시).

사양 (승인 원문 요지):
- 새 독립 파일 1개. 생산코드·주문경로 수정 금지, 주문 API import/호출 금지(테스트로 강제).
- 볼린저 = 전일까지 확정 일봉 20개의 20이평·2σ 하단. 장중 고정.
- 가상진입은 볼린저 접촉만으로 금지 — S02 생산 판정경로의 신호(BUY_READY) 시점만 기록.
- 보완①(비교군): S02 신호 전건을 기록하고 bb_state(BELOW/NEAR/OUTSIDE)+왕관 태그.
- 보완②(브로커 IPC 0): 파일만 읽는다 — S02 신호 JSON·고저폭 스냅샷 CSV·일봉 CSV.
- 보완③(일봉 최신성 fail-closed): 일봉 최신일 ≠ 직전 거래일이면 그날 관찰 중단+이유 기록.
  직전 거래일 판정 = data\high_range_shadow_<X>.csv 가 존재하는 가장 최근 X (장이 열린 날만 생성됨).
- 기록: 진입 후 10·30·60분·종가(마지막 스냅샷)·장중 최고수익·최대손실.
- 매일 마감 후 한국어 요약 파일 생성 (보고서\볼린저하단그림자_<날짜>.txt).

출력: data\bollinger_lowband_s02_shadow.csv (같은 날짜 재실행 시 그 날짜 행 교체)
주의: S02 신호 JSON 은 당일분만 보존되므로 이 도구는 당일 마감 후 실행 전제.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
OUT = ROOT / "data" / "bollinger_lowband_s02_shadow.csv"
FIELDS = [
    "date", "code", "name", "signal_hms", "bb_state", "crown",
    "entry_price", "bb_lower", "bb_gap_pct",
    "pct_10m", "pct_30m", "pct_60m", "pct_close",
    "pct_max_gain", "pct_max_loss", "price_src", "generated_at",
]


def bollinger_lower(closes: list[float], period: int = 20, k: float = 2.0):
    """전일까지 확정 종가 최근 20개의 20이평 - 2σ(모표준편차). 부족하면 None."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((c - mean) ** 2 for c in window) / period
    return mean - k * math.sqrt(var)


def classify_bb_state(price: float, lower) -> str:
    """BELOW=하단 이탈 / NEAR=하단 위 1% 이내 / OUTSIDE=그 밖 / NO_BAND=밴드 계산 불가."""
    if lower is None or lower <= 0:
        return "NO_BAND"
    if price < lower:
        return "BELOW"
    if price <= lower * 1.01:
        return "NEAR"
    return "OUTSIDE"


def previous_trading_day(day: str, data_dir: Path) -> str | None:
    """day 직전 거래일 = high_range_shadow_<X>.csv 가 존재하는 가장 최근 X (최대 10일 소급)."""
    current = datetime.strptime(day, "%Y%m%d")
    for _ in range(10):
        current -= timedelta(days=1)
        candidate = current.strftime("%Y%m%d")
        if (data_dir / f"high_range_shadow_{candidate}.csv").exists():
            return candidate
    return None


def check_daily_freshness(day: str, dates_in_eod: set[str], data_dir: Path):
    """보완③: (통과여부, 이유). 일봉 최신일(당일 제외)이 직전 거래일과 다르면 fail-closed."""
    prev_dates = {d for d in dates_in_eod if d < day}
    if not prev_dates:
        return False, "일봉에 전일 이전 자료가 없음"
    latest = max(prev_dates)
    expected = previous_trading_day(day, data_dir)
    if expected is None:
        return False, "직전 거래일 판정 불가(고저폭 스냅샷 파일 10일 내 없음)"
    if latest != expected:
        return False, f"일봉 최신일 {latest} ≠ 직전 거래일 {expected} — 묵은 밴드 위험"
    return True, f"일봉 최신일 {latest} = 직전 거래일"


def _load_closes(day: str) -> tuple[dict[str, list[float]], set[str]]:
    """일봉 CSV에서 종목별 (전일까지) 종가 시계열과 날짜 집합. 복사본으로 읽는다."""
    src = ROOT / "data" / "eod_daily_bars.csv"
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    shutil.copyfile(src, tmp)
    closes: dict[str, list[tuple[str, float]]] = {}
    dates: set[str] = set()
    try:
        with open(tmp, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                date = str(row.get("date") or "")
                dates.add(date)
                if date >= day:  # 전일까지 확정 일봉만 (당일 제외 — 장중 고정 밴드)
                    continue
                try:
                    close = float(row["close"])
                except (KeyError, ValueError):
                    continue
                if close > 0:
                    closes.setdefault(str(row["code"]).zfill(6), []).append((date, close))
    finally:
        os.unlink(tmp)
    ordered = {}
    for code, pairs in closes.items():
        pairs.sort(key=lambda p: p[0])
        ordered[code] = [c for _, c in pairs]
    return ordered, dates


def _load_signals(day: str) -> list[dict]:
    src = ROOT / "data" / "strategy_02_low_buy_signal_v1.json"
    payload = json.loads(src.read_text(encoding="utf-8-sig"))
    if str(payload.get("date")) not in (day, f"{day[:4]}-{day[4:6]}-{day[6:]}"):
        return []
    return list(payload.get("signals") or [])


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


def _price_at(series, when):
    for ts, price in series:
        if ts >= when:
            return price
    return series[-1][1] if series else None


def _pct(price, base):
    if price is None or not base:
        return ""
    return round((float(price) - base) / base * 100, 3)


def build_rows(day: str) -> tuple[list[dict], str]:
    closes, eod_dates = _load_closes(day)
    ok, freshness = check_daily_freshness(day, eod_dates, ROOT / "data")
    if not ok:
        return [], f"FAIL_CLOSED: {freshness}"
    signals = _load_signals(day)
    snaps = _load_snapshots(day)
    stamp = datetime.now().isoformat(timespec="seconds")
    rows = []
    for sig in signals:
        code = str(sig.get("code") or "").zfill(6)
        price = float(sig.get("price") or 0)
        ts_raw = str(sig.get("ts") or "")
        try:
            entry_dt = datetime.fromisoformat(ts_raw).replace(tzinfo=None)
        except ValueError:
            continue
        lower = bollinger_lower(closes.get(code, []))
        series = snaps.get(code, [])
        after = [p for p in series if p[0] >= entry_dt]
        rows.append({
            "date": day,
            "code": code,
            "name": str(sig.get("name") or ""),
            "signal_hms": entry_dt.strftime("%H:%M:%S"),
            "bb_state": classify_bb_state(price, lower),
            "crown": "Y" if sig.get("hr_crown") else "N",
            "entry_price": price,
            "bb_lower": round(lower, 1) if lower else "",
            "bb_gap_pct": _pct(price, lower) if lower else "",
            "pct_10m": _pct(_price_at(series, entry_dt + timedelta(minutes=10)), price),
            "pct_30m": _pct(_price_at(series, entry_dt + timedelta(minutes=30)), price),
            "pct_60m": _pct(_price_at(series, entry_dt + timedelta(minutes=60)), price),
            "pct_close": _pct(after[-1][1] if after else None, price),
            "pct_max_gain": _pct(max((p[1] for p in after), default=None), price),
            "pct_max_loss": _pct(min((p[1] for p in after), default=None), price),
            "price_src": "high_range_shadow" if series else "미관측",
            "generated_at": stamp,
        })
    return rows, freshness


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


def write_summary(rows: list[dict], day: str, note: str) -> Path:
    path = ROOT / "보고서" / f"볼린저하단그림자_{day}.txt"
    lines = [f"[볼린저 하단 × S02 그림자] {day}  (생성 {datetime.now():%H:%M:%S})",
             f"일봉 최신성: {note}", ""]
    if not rows:
        lines.append("기록 0건 (fail-closed 또는 S02 신호 없음)")
    else:
        for state in ("BELOW", "NEAR", "OUTSIDE", "NO_BAND"):
            group = [r for r in rows if r["bb_state"] == state]
            if not group:
                continue
            vals = [float(r["pct_30m"]) for r in group if r["pct_30m"] != ""]
            avg30 = round(sum(vals) / len(vals), 2) if vals else "-"
            lines.append(f"{state}: {len(group)}건 (왕관 {sum(1 for r in group if r['crown']=='Y')}) "
                         f"— 30분 평균 {avg30}%")
        lines.append("")
        lines.append("건별: 상태 | 왕관 | 종목 | 신호시각 | 하단대비% | 30분% | 종가%")
        for r in rows:
            lines.append(f"  {r['bb_state']:<7}| {r['crown']} | {r['code']} {r['name']} | "
                         f"{r['signal_hms']} | {r['bb_gap_pct']} | {r['pct_30m']} | {r['pct_close']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    rows, note = build_rows(day)
    if note.startswith("FAIL_CLOSED"):
        summary = write_summary([], day, note)
        print(f"[{day}] {note} → {summary}")
        return 0
    append_replacing_day(rows, day)
    summary = write_summary(rows, day, note)
    below = [r for r in rows if r["bb_state"] == "BELOW"]
    near = [r for r in rows if r["bb_state"] == "NEAR"]
    print(f"[{day}] S02 신호 {len(rows)}건 기록 (하단이탈 {len(below)}·1%이내 {len(near)}) "
          f"→ {OUT}")
    print(f"  요약: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

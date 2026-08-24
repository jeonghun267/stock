# -*- coding: utf-8 -*-
"""돈맥 상승보유 그림자 (읽기 전용 · 기록만).

★[MFLOW-RIDER-SHADOW 2026-08-19 친구님 승인 "1번 먼저 하고"] 발단 실측:
  8/19 돈맥 6왕복 중 5건이 팔고 나서 더 올랐다(서진시스템 +8.1% 익절 후 +7% 추가).
  "전략들의 상승보유(3분봉 5/10/20)를 돈맥에 달면 얼마나 더 태웠나"를 기록으로 잰다.
  돈맥 실행기는 한 줄도 안 건드린다.

한계(정직 고지): 상승보유의 수급 우위 성분(초 단위 대금속도)은 과거 재생 불가.
  이 그림자는 선(線) 성분만 잰다 — 매도 규칙 = "3분봉 종가가 MA5 아래로 마감한
  첫 봉의 종가에 판다". 실제 상승보유보다 오래 드는 쪽 근사(수급 꺾임 매도가 빠짐).

collect 모드(5분마다): 돈맥_1분봉.json 은 70분만 보관 → 오늘 돈맥이 주문한 종목의
  1분봉을 하루 파일로 축적. report 모드(15:50): 왕복별 재생 → 비교표.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                              # noqa: BLE001
    pass

BASE = Path(r"C:\stock_bot")
BARS = BASE / "data" / "돈맥_1분봉.json"
SHADOW_DIR = BASE / "data" / "shadow" / "mflow_rider"
REPORT_DIR = BASE / "보고서"


def _read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def mflow_codes(now: datetime) -> set[str]:
    day_dash = now.strftime("%Y-%m-%d")
    codes: set[str] = set()
    marker = re.compile(r"key=mflow_[a-z]*_?(\d{6})")
    for path in sorted((BASE / "LOG").glob("broker_journal.log*")):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime).date() < now.date():
                continue
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if day_dash not in line or "SENDORDER-REAL" not in line:
                        continue
                    matched = marker.search(line)
                    if matched:
                        codes.add(matched.group(1))
        except OSError:
            continue
    return codes


def collect(now: datetime) -> int:
    codes = mflow_codes(now)
    if not codes:
        print("[rider-shadow] 오늘 돈맥 주문 종목 없음 — 수집 생략")
        return 0
    payload = _read_json(BARS)
    table = payload.get("m") or {}
    out_path = SHADOW_DIR / f"bars_{now:%Y%m%d}.json"
    archive = _read_json(out_path)
    added = 0
    for code in codes:
        entry = table.get(code)
        if not isinstance(entry, dict):
            continue
        dest = archive.setdefault(code, {})
        minutes = entry.get("pm") or []
        bars = entry.get("prev") or []
        for minute, bar in zip(minutes, bars):
            key = str(minute)
            if key.startswith(now.strftime("%Y%m%d")) and key not in dest:
                dest[key] = bar          # [o, h, l, c]
                added += 1
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(archive, ensure_ascii=False),
                         encoding="utf-8")
    os.replace(temporary, out_path)
    print(f"[rider-shadow] 수집 {len(codes)}종목 · 새 봉 {added}개 → {out_path.name}")
    return 0


def _three_minute_closes(minutes_sorted: list[tuple[str, list]]) -> list[tuple[str, float]]:
    """1분봉 → 3분봉 종가. 09:00 기준 3분 묶음, 완성된 묶음만."""
    buckets: dict[int, tuple[str, float]] = {}
    counts: dict[int, int] = {}
    for key, bar in minutes_sorted:
        hh, mm = int(key[8:10]), int(key[10:12])
        idx = (hh * 60 + mm - 540) // 3
        if idx < 0:
            continue
        buckets[idx] = (key, float(bar[3]))      # 마지막 분의 종가
        counts[idx] = counts.get(idx, 0) + 1
    return [buckets[i] for i in sorted(buckets) if counts.get(i, 0) >= 3]


def report(now: datetime) -> int:
    day = now.strftime("%Y%m%d")
    archive = _read_json(SHADOW_DIR / f"bars_{day}.json")
    codes = mflow_codes(now)
    fills = []
    try:
        with (BASE / "LOG" / f"fills_{day}.csv").open(
                encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.reader(handle):
                if (row and not row[0].startswith("ts") and len(row) >= 7
                        and row[1] in codes):
                    fills.append((row[0], row[1],
                                  "B" if "+" in row[4] else "S", float(row[6])))
    except OSError:
        print("[rider-shadow] 오늘 체결 파일 없음")
        return 0
    q = defaultdict(list)
    trips = []
    for ts, code, side, px in fills:
        if side == "B":
            q[code].append((ts, px))
        elif q[code]:
            bts, bpx = q[code].pop(0)
            trips.append((bts, code, bpx, ts, px))
    if not trips:
        print("[rider-shadow] 오늘 돈맥 왕복 없음")
        return 0

    lines = ["=" * 76,
             f"돈맥 상승보유 그림자 {now:%Y-%m-%d %H:%M} — 선(MA5) 성분 재생 [UNVERIFIED]",
             "=" * 76,
             "매도규칙(그림자): 매수 후 3분봉 종가가 MA5 아래로 마감한 첫 봉에 매도",
             f"{'매수':8s} {'종목':7s} {'매수가':>8s} {'실제매도':>8s} {'실제%':>7s} "
             f"{'그림자매도':>9s} {'그림자%':>7s} {'차이%p':>7s}"]
    summary = []
    for bts, code, bpx, sts, spx in sorted(trips):
        bars = sorted((archive.get(code) or {}).items())
        closes = _three_minute_closes(bars)
        buy_key = bts[:16].replace("-", "").replace("T", "").replace(":", "")[:12]
        after = [c for c in closes if c[0] >= buy_key]
        pre = [c[1] for c in closes if c[0] < buy_key]
        exit_px, exit_at = None, ""
        if len(pre) >= 4 and after:
            series = pre[:]
            for key, close in after:
                series.append(close)
                if len(series) >= 5:
                    ma5 = sum(series[-5:]) / 5
                    if close < ma5:
                        exit_px, exit_at = close, key[8:12]
                        break
            if exit_px is None:
                exit_px, exit_at = after[-1][1], after[-1][0][8:12] + "끝"
        actual = (spx / bpx - 1) * 100
        if exit_px:
            shadow = (exit_px / bpx - 1) * 100
            delta = shadow - actual
            lines.append(f"{bts[11:19]} {code:7s} {bpx:>8,.0f} {spx:>8,.0f} "
                         f"{actual:>+6.2f}% {exit_px:>9,.0f} {shadow:>+6.2f}% "
                         f"{delta:>+6.2f}")
            summary.append(delta)
        else:
            lines.append(f"{bts[11:19]} {code:7s} {bpx:>8,.0f} {spx:>8,.0f} "
                         f"{actual:>+6.2f}%   재생불가(봉 부족 — 수집 시작 전 매매)")
    if summary:
        lines.append("-" * 76)
        lines.append(f"재생 {len(summary)}건 · 그림자-실제 차이 평균 "
                     f"{sum(summary)/len(summary):+.2f}%p")
    body = "\n".join(lines)
    print(body)
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"돈맥상승보유그림자_{day}.txt").write_text(
            body + "\n", encoding="utf-8")
        history = REPORT_DIR / "돈맥상승보유그림자_이력.csv"
        new = not history.exists()
        with history.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            if new:
                writer.writerow(["날짜", "재생건수", "평균차이%p"])
            if summary:
                writer.writerow([day, len(summary),
                                 round(sum(summary) / len(summary), 3)])
    except OSError:
        pass
    return 0


def main() -> int:
    now = datetime.now()
    mode = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if mode == "report":
        return report(now)
    return collect(now)


if __name__ == "__main__":
    sys.exit(main())

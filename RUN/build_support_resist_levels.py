# -*- coding: utf-8 -*-
"""
[바닥선/천정선 계산기 v1 2026-06-12] 친구님: "바닥 저지선과 천정선을 항상 찾아낼 수 있게,
매수할 때 참조하게" — 매일 아침 KOSDAQ 전 종목 지지/저항 레벨 산출.
근거(6/12 검증, 참조용): 천정 코앞(0~3%) 눌림매수 = 최악(-1.29%/승21%) /
  바닥 대비 5~15% 이륙구간 = 최선(-0.53%/승30%) / 이미 돌파(신고가) = 무난.
출력: DATA/support_resist_levels.csv (code, low3, low5, low20, high20, base_date)
스케줄: 매일 08:50 (eod_daily_bars 갱신 후). 매매 무연결 — 소비자는 SR-SHADOW(기록전용).
"""
import csv, io
from collections import defaultdict, deque

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
OUT = r"C:\stock_bot\DATA\support_resist_levels.csv"

hist = defaultdict(lambda: deque(maxlen=20))
with io.open(EOD, encoding="utf-8-sig", errors="replace") as fp:
    rd = csv.DictReader(fp)
    for r in rd:
        if r.get("market") != "KOSDAQ": continue
        d = r["date"]
        if d < "20260301": continue
        try:
            h, l = float(r["high"] or 0), float(r["low"] or 0)
        except (TypeError, ValueError):
            continue
        if h > 0 and l > 0:
            hist[r["code"]].append((d, h, l))

n = 0
with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["code", "low3", "low5", "low20", "high20", "base_date"])
    for code, dq in hist.items():
        if len(dq) < 20: continue
        rows = list(dq)
        w.writerow([code,
                    min(r[2] for r in rows[-3:]),
                    min(r[2] for r in rows[-5:]),
                    min(r[2] for r in rows),
                    max(r[1] for r in rows),
                    rows[-1][0]])
        n += 1
print(f"[SR-LEVELS] {n}종목 레벨 산출 → {OUT} (기준일 {rows[-1][0]})")

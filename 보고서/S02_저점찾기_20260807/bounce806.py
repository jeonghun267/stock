# -*- coding: utf-8 -*-
"""8/6 교차 검증: 저점→꼭지 반등률이 승패를 가르는 선이 어제도 있었나. 읽기 전용.

신호는 8/6 실전 신호 CSV(그날 실제 엔진 기록) 그대로. 캐시 없는 종목은
재생기 extract() 로 1초 캡처에서 추출(재생기 자체 캐시 형식, 판정 재구현 없음).
"""
import csv
import pathlib
import statistics
import sys

sys.path.insert(0, r"C:\stock_bot\RUN")
from replay_buy_method_v1 import extract  # noqa: E402

DATE = "20260806"
SIG = pathlib.Path(r"C:\stock_bot\data\strategy_02_signal_v1") / f"strategy_02_signals_{DATE}.csv"
UP, DOWN = 1.0, -2.0

sig_rows = [r for r in csv.DictReader(SIG.open(encoding="utf-8-sig", newline=""))
            if r.get("action") == "BUY_READY"]
codes = {str(r["code"]).zfill(6) for r in sig_rows}
raw = extract(DATE, codes)

ticks = {}
for c, rows in raw.items():
    out = []
    for r in rows:
        h = r["ts"][11:19]
        if h < "09:00:00":
            continue
        try:
            px = float(r["current_price"])
        except (TypeError, ValueError):
            continue
        if px > 0:
            out.append((h, px))
    ticks[c] = out

print("=" * 96)
print("8/6 실전 신호 — 저점에서 몇 % 반등했다가, 밑(-2%)과 위(+1%) 어느 쪽으로 갔나")
print("=" * 96)
print(f"{'시각':>9} {'종목':>7} {'저점시각':>9} {'신호반등%':>9} {'꼭지반등%':>9}"
      f" {'저점밑추가%':>10}  판정")
print("-" * 96)
res_all = []
for s in sig_rows:
    code = str(s["code"]).zfill(6)
    t_sig = str(s["ts"])[11:19]
    price = float(s["price"])
    low = float(s["anchor_low"])
    low_t = str(s["anchor_low_ts"])[11:19]
    tk = ticks[code]
    res, stop_i, sig_i = 0, None, None
    for i, (h, q) in enumerate(tk):
        if h < t_sig:
            continue
        if sig_i is None:
            sig_i = i
        r = (q / price - 1) * 100
        if r <= DOWN:
            res, stop_i = -1, i
            break
        if r >= UP:
            res, stop_i = 1, i
            break
    low_i = next((i for i, (h, _) in enumerate(tk) if h >= low_t), None)
    if low_i is None or sig_i is None:
        print(f"{t_sig:>9} {code:>7}  (자료 부족)")
        continue
    span_end = stop_i if (res == -1 and stop_i is not None) else len(tk) - 1
    peak = max(q for _, q in tk[low_i:span_end + 1])
    peak_pct = (peak / low - 1) * 100
    deeper = None
    if res == -1 and stop_i is not None:
        mn = min(q for _, q in tk[stop_i:])
        deeper = (mn / low - 1) * 100
    entry_gap = (price / low - 1) * 100
    res_all.append(dict(code=code, t=t_sig, res=res, peak=peak_pct, deeper=deeper))
    mark = {1: "위(+1% 먼저)", -1: "밑(-2% 먼저)", 0: "둘 다 안 닿음"}[res]
    dp = f"{deeper:>+9.2f}%" if deeper is not None else "        -"
    print(f"{t_sig:>9} {code:>7} {low_t:>9} {entry_gap:>+8.2f}% {peak_pct:>+8.2f}%"
          f" {dp:>10}  {mark}")

W = [x for x in res_all if x["res"] == 1]
L = [x for x in res_all if x["res"] == -1]
print()
if L:
    print(f"패자 {len(L)}건: 저점→꼭지  " + " · ".join(f"{x['code']} {x['peak']:+.2f}%" for x in L))
if W:
    print(f"승자 {len(W)}건: 저점→꼭지  " + " · ".join(f"{x['code']} {x['peak']:+.2f}%" for x in W))
if L and W:
    print(f"\n가르는 선: 패자 최대 {max(x['peak'] for x in L):+.2f}%"
          f"  vs  승자 최소 {min(x['peak'] for x in W):+.2f}%")

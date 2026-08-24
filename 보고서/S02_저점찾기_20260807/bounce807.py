# -*- coding: utf-8 -*-
"""친구님 질문에 답하기: 음봉 끝 양봉이 저점에서 몇 % 반등했다가 다시 아래로 떨어지나.

읽기 전용. 판정 재구현 없음 — 신호는 fires_gateoff.json(실제 모듈 재생 결과)을 그대로 쓰고,
가격 경로는 data\replay_cache\ (1초 캡처에서 추출한 직접 기록값)만 본다.

측정 3가지
  A. 신호 27건 각각: 앵커저점 → 최대 반등률, 그리고 밑(-2%)/위(+1%) 어느 쪽이 먼저였나.
     패자는 '손절 닿기 전까지'의 꼭지를 잰다 = 몇 % 반등했다가 떨어졌나.
     패자는 이후 옛 저점 밑으로 몇 % 더 내려갔는지도 잰다 (= 더 낮은 저점이 실제로 있었나).
  B. 반등 문턱 시뮬: 저점+X% (1.5/2.0/2.5/3.0)를 기다렸다 샀다면 → 승/패/거름.
  C. 저점+1.5% → 저점+2.0% 올라오는 구간의 매도·매수 대금 속도와 흡수(매수/매도)의 변화.
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0        # 채점 기준: 신호가 +1.0% 먼저 = 위 · -2.0% 먼저 = 밑

_t = {}


def ticks(code):
    """(시각HH:MM:SS, 가격, 매수누적대금, 매도누적대금) — 직접 기록값만."""
    if code not in _t:
        rows = []
        with (CACHE / f"20260807_{code}.csv").open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                h = r["ts"][11:19]
                if h < "09:00:00":
                    continue
                try:
                    px = float(r["current_price"])
                    bm = float(r.get("buy_money_cum") or 0)
                    sm = float(r.get("sell_money_cum") or 0)
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    rows.append((h, px, bm, sm))
        _t[code] = rows
    return _t[code]


fires = json.loads((HERE / "fires_gateoff.json").read_text(encoding="utf-8"))
out = []

for f in fires:
    code = str(f["_code"]).zfill(6)
    t_sig = f["_t"]
    price = float(f["price"])
    low = float(f["anchor_low"])
    low_t = str(f["anchor_low_ts"])[11:19]
    tk = ticks(code)

    # 결과: 신호 후 -2% / +1% 먼저 닿은 쪽 (sentdown.py와 같은 셈법)
    res = 0
    stop_i = None
    sig_i = None
    for i, (h, q, _, _) in enumerate(tk):
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

    # 저점 시각부터의 경로
    low_i = next((i for i, (h, _, _, _) in enumerate(tk) if h >= low_t), None)
    if low_i is None or sig_i is None:
        continue

    # 패자: 손절 닿기 전까지의 꼭지(저점 대비) = "몇 % 반등했다가 떨어졌나"
    span_end = stop_i if (res == -1 and stop_i is not None) else len(tk) - 1
    peak = max(q for _, q, _, _ in tk[low_i:span_end + 1])
    peak_pct = (peak / low - 1) * 100

    # 패자: 손절 이후 옛 저점 밑으로 얼마나 더 내려갔나 (= 더 낮은 저점)
    deeper = None
    if res == -1 and stop_i is not None:
        mn = min(q for _, q, _, _ in tk[stop_i:])
        deeper = (mn / low - 1) * 100

    # 문턱 교차 시각들 (저점 이후 처음으로 저점+X% 도달)
    cross = {}
    for x in (1.5, 2.0, 2.5, 3.0):
        lvl = low * (1 + x / 100)
        cross[x] = next((i for i in range(low_i, len(tk)) if tk[i][1] >= lvl), None)

    out.append(dict(
        code=code, t=t_sig, res=res, price=price, low=low, low_t=low_t,
        entry_gap=float(f.get("entry_gap_pct") or 0), peak_pct=peak_pct,
        deeper=deeper, cross=cross, low_i=low_i, sig_i=sig_i, stop_i=stop_i,
        steps=int(float(f.get("dip_low_reset_steps") or 0)),
    ))

out.sort(key=lambda z: z["t"])
W = [r for r in out if r["res"] == 1]
L = [r for r in out if r["res"] == -1]
M = [r for r in out if r["res"] == 0]

print("=" * 100)
print("A. 신호 27건 — 저점에서 몇 % 반등했다가, 밑(-2%)과 위(+1%) 어느 쪽으로 갔나")
print("=" * 100)
print(f"{'시각':>9} {'종목':>7} {'저점시각':>9} {'신호반등%':>9} {'꼭지반등%':>9}"
      f" {'저점밑추가%':>10}  판정")
print("-" * 100)
for r in out:
    mark = {1: "위(+1% 먼저)", -1: "밑(-2% 먼저)", 0: "둘 다 안 닿음"}[r["res"]]
    dp = f"{r['deeper']:>+9.2f}%" if r["deeper"] is not None else "        -"
    print(f"{r['t']:>9} {r['code']:>7} {r['low_t']:>9} {r['entry_gap']:>+8.2f}%"
          f" {r['peak_pct']:>+8.2f}% {dp:>10}  {mark}")


def med(v):
    return statistics.median(v) if v else float("nan")


print()
print(f"패자 {len(L)}건: 저점→꼭지 반등  "
      f"최소 {min(x['peak_pct'] for x in L):+.2f}% · 중앙 {med([x['peak_pct'] for x in L]):+.2f}%"
      f" · 최대 {max(x['peak_pct'] for x in L):+.2f}%")
print(f"        손절 뒤 옛 저점 밑으로  중앙 {med([x['deeper'] for x in L if x['deeper'] is not None]):+.2f}%"
      f" (전부 {sum(1 for x in L if (x['deeper'] or 0) < 0)}/{len(L)}건이 옛 저점 밑을 다시 봤나 확인)")
print(f"승자 {len(W)}건: 저점→꼭지 반등  "
      f"최소 {min(x['peak_pct'] for x in W):+.2f}% · 중앙 {med([x['peak_pct'] for x in W]):+.2f}%"
      f" · 최대 {max(x['peak_pct'] for x in W):+.2f}%")

print()
print("=" * 100)
print("B. 반등 문턱을 기다렸다 샀다면 — 저점+X% 도달 시점에 매수, 그 가격 기준 +1%/-2% 먼저 닿은 쪽")
print("=" * 100)
print(f"{'문턱':>6} {'매수':>5} {'승':>4} {'패':>4} {'승률':>7} {'안삼':>5}"
      f"  안 산 것들의 원래 결과(승/패/애매)")
print("-" * 100)
for x in (1.5, 2.0, 2.5, 3.0):
    win = lose = tie = 0
    sk_w = sk_l = sk_m = 0
    for r in out:
        ci = r["cross"][x]
        if ci is None:
            if r["res"] == 1:
                sk_w += 1
            elif r["res"] == -1:
                sk_l += 1
            else:
                sk_m += 1
            continue
        entry = ticks(r["code"])[ci][1]
        res2 = 0
        for h, q, _, _ in ticks(r["code"])[ci:]:
            rr = (q / entry - 1) * 100
            if rr <= DOWN:
                res2 = -1
                break
            if rr >= UP:
                res2 = 1
                break
        if res2 == 1:
            win += 1
        elif res2 == -1:
            lose += 1
        else:
            tie += 1
    n = win + lose
    wr = (win / n * 100) if n else float("nan")
    print(f"{x:>5.1f}% {win+lose+tie:>5} {win:>4} {lose:>4} {wr:>6.1f}% {sk_w+sk_l+sk_m:>5}"
          f"  승 {sk_w} / 패 {sk_l} / 애매 {sk_m}")
print(f"(현행 신호 27건: 승 {len(W)} · 패 {len(L)} · 애매 {len(M)}"
      f" → 승률 {len(W)/(len(W)+len(L))*100:.1f}%)")

print()
print("=" * 100)
print("C. 저점+1.5% → 저점+2.0% 올라오는 구간 — 매도·매수 대금과 흡수의 변화")
print("   (흡수비 = 그 구간 매수대금 ÷ 매도대금 · '직전' = 저점→+1.5% 구간의 같은 비율)")
print("=" * 100)
print(f"{'시각':>9} {'종목':>7} {'구간초':>7} {'매수억/s':>9} {'매도억/s':>9}"
      f" {'흡수비':>7} {'직전흡수비':>9} {'변화':>6}  판정")
print("-" * 100)
rows_c = []
for r in out:
    i15, i20 = r["cross"][1.5], r["cross"][2.0]
    if i15 is None or i20 is None or i20 <= i15:
        continue
    tk = ticks(r["code"])
    h15, _, b15, s15 = tk[i15]
    h20, _, b20, s20 = tk[i20]
    _, _, b_low, s_low = tk[r["low_i"]]
    sec = max(1.0, (int(h20[:2]) * 3600 + int(h20[3:5]) * 60 + int(h20[6:8]))
              - (int(h15[:2]) * 3600 + int(h15[3:5]) * 60 + int(h15[6:8])))
    db, ds = b20 - b15, s20 - s15
    ab = db / ds if ds > 0 else float("inf")
    db0, ds0 = b15 - b_low, s15 - s_low
    ab0 = db0 / ds0 if ds0 > 0 else float("inf")
    trend = "↑" if ab > ab0 else "↓"
    rows_c.append(dict(r=r, sec=sec, db=db, ds=ds, ab=ab, ab0=ab0, up=(ab > ab0)))
    mark = {1: "위", -1: "밑", 0: "·"}[r["res"]]
    print(f"{r['t']:>9} {r['code']:>7} {sec:>6.0f}s {db/sec/1e8:>9.3f} {ds/sec/1e8:>9.3f}"
          f" {ab:>7.2f} {ab0:>9.2f} {trend:>4}   {mark}")

cw = [x for x in rows_c if x["r"]["res"] == 1]
cl = [x for x in rows_c if x["r"]["res"] == -1]
print()
print(f"승자 {len(cw)}건: 구간 흡수비 중앙 {med([x['ab'] for x in cw]):.2f}"
      f" · 흡수 증가(↑) {sum(1 for x in cw if x['up'])}/{len(cw)}건")
print(f"패자 {len(cl)}건: 구간 흡수비 중앙 {med([x['ab'] for x in cl]):.2f}"
      f" · 흡수 증가(↑) {sum(1 for x in cl if x['up'])}/{len(cl)}건")

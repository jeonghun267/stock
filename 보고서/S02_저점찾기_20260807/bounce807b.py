# -*- coding: utf-8 -*-
"""bounce807.py 의 B·C 를 '같은 반등 에피소드 안'으로 고친 판. 읽기 전용.

에피소드 규칙: 앵커 저점 이후, 가격이 앵커 저점 밑으로 내려가면 그 반등은 죽은 것.
문턱 도달·흡수 구간 모두 '저점이 안 깨진 동안'만 인정한다.
(원판 B는 반등이 죽고 몇 시간 뒤 우연히 그 가격을 지나간 것도 매수로 세는 오류가 있었다.)
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0

_t = {}


def ticks(code):
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
sigs = []
for f in fires:
    code = str(f["_code"]).zfill(6)
    tk = ticks(code)
    price = float(f["price"])
    low = float(f["anchor_low"])
    low_t = str(f["anchor_low_ts"])[11:19]
    low_i = next((i for i, (h, _, _, _) in enumerate(tk) if h >= low_t), None)
    sig_i = next((i for i, (h, _, _, _) in enumerate(tk) if h >= f["_t"]), None)
    if low_i is None or sig_i is None:
        continue
    res = 0
    for h, q, _, _ in tk[sig_i:]:
        r = (q / price - 1) * 100
        if r <= DOWN:
            res = -1
            break
        if r >= UP:
            res = 1
            break
    sigs.append(dict(code=code, t=f["_t"], price=price, low=low, low_t=low_t,
                     low_i=low_i, res=res))

W = [s for s in sigs if s["res"] == 1]
L = [s for s in sigs if s["res"] == -1]
M = [s for s in sigs if s["res"] == 0]


def episode_cross(s, x):
    """저점이 안 깨진 동안 저점+x% 에 처음 닿은 틱 번호. 못 닿고 저점이 깨지면 None."""
    tk = ticks(s["code"])
    lvl = s["low"] * (1 + x / 100)
    for i in range(s["low_i"], len(tk)):
        q = tk[i][1]
        if q < s["low"]:
            return None
        if q >= lvl:
            return i
    return None


print("=" * 96)
print("B(수정). 같은 반등 안에서 저점+X% 에 닿으면 그때 매수 — 저점이 먼저 깨지면 안 삼")
print("=" * 96)
print(f"{'문턱':>6} {'매수':>5} {'승':>4} {'패':>4} {'승률':>7} {'안삼':>5}"
      f"  안 산 것들의 원래 결과(승/패/애매)")
print("-" * 96)
for x in (1.5, 2.0, 2.5, 3.0):
    win = lose = tie = 0
    sk_w = sk_l = sk_m = 0
    detail_missed = []
    for s in sigs:
        ci = episode_cross(s, x)
        if ci is None:
            if s["res"] == 1:
                sk_w += 1
                detail_missed.append(s)
            elif s["res"] == -1:
                sk_l += 1
            else:
                sk_m += 1
            continue
        tk = ticks(s["code"])
        entry = tk[ci][1]
        res2 = 0
        for h, q, _, _ in tk[ci:]:
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
    miss = " ".join(f"{s['code']}@{s['t'][:5]}" for s in detail_missed)
    print(f"{x:>5.1f}% {win+lose+tie:>5} {win:>4} {lose:>4} {wr:>6.1f}% {sk_w+sk_l+sk_m:>5}"
          f"  승 {sk_w} / 패 {sk_l} / 애매 {sk_m}" + (f"   놓친 승: {miss}" if miss else ""))
print(f"(현행 27건 그대로: 승 {len(W)} · 패 {len(L)} · 애매 {len(M)})")

print()
print("=" * 96)
print("C(수정). 같은 반등 안에서 저점+1.5% → +2.0% 올라오는 구간의 매도·매수와 흡수")
print("=" * 96)
print(f"{'시각':>9} {'종목':>7} {'구간초':>7} {'매수억/s':>9} {'매도억/s':>9}"
      f" {'흡수비':>7} {'직전흡수비':>9} {'변화':>5}  판정")
print("-" * 96)
rows_c = []
for s in sigs:
    i15 = episode_cross(s, 1.5)
    i20 = episode_cross(s, 2.0)
    if i15 is None or i20 is None or i20 <= i15:
        continue
    tk = ticks(s["code"])
    h15, _, b15, s15 = tk[i15]
    h20, _, b20, s20 = tk[i20]
    _, _, b0, s0 = tk[s["low_i"]]
    sec = max(1.0, (int(h20[:2]) * 3600 + int(h20[3:5]) * 60 + int(h20[6:8]))
              - (int(h15[:2]) * 3600 + int(h15[3:5]) * 60 + int(h15[6:8])))
    db, ds = b20 - b15, s20 - s15
    ab = db / ds if ds > 0 else float("inf")
    db0, ds0 = b15 - b0, s15 - s0
    ab0 = db0 / ds0 if ds0 > 0 else float("inf")
    rows_c.append(dict(s=s, ab=ab, ab0=ab0, up=(ab > ab0)))
    mark = {1: "위", -1: "밑", 0: "·"}[s["res"]]
    print(f"{s['t'][:8]:>9} {s['code']:>7} {sec:>6.0f}s {db/sec/1e8:>9.3f} {ds/sec/1e8:>9.3f}"
          f" {ab:>7.2f} {ab0:>9.2f} {('↑' if ab > ab0 else '↓'):>4}   {mark}")

cw = [x for x in rows_c if x["s"]["res"] == 1]
cl = [x for x in rows_c if x["s"]["res"] == -1]
cm = [x for x in rows_c if x["s"]["res"] == 0]


def med(v):
    return statistics.median(v) if v else float("nan")


print()
print(f"이 구간까지 살아서 올라온 것: 승자 {len(cw)} · 패자 {len(cl)} · 애매 {len(cm)}"
      f"  (나머지는 +2.0% 전에 저점이 깨짐)")
if cw:
    print(f"승자: 흡수비 중앙 {med([x['ab'] for x in cw]):.2f}"
          f" · 흡수 증가 {sum(1 for x in cw if x['up'])}/{len(cw)}건")
if cl:
    print(f"패자: 흡수비 중앙 {med([x['ab'] for x in cl]):.2f}"
          f" · 흡수 증가 {sum(1 for x in cl if x['up'])}/{len(cl)}건")

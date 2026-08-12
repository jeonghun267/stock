# -*- coding: utf-8 -*-
"""흡수를 '매도가 쏟아지던 구간'에서 잰다. 읽기 전용.

Kyle(1985) lambda = 가격변화 / 순주문흐름.
  저점을 만드는 동안 매도가 얼마나 나왔고, 그때 가격이 얼마나 밀렸나.
    lambda 작다 = 많이 팔았는데 조금만 밀렸다 = 매수벽이 받아냈다(흡수) = 바닥
    lambda 크다 = 조금 팔았는데 많이 밀렸다   = 받아주는 사람이 없다  = 계속 내려간다

창 = 저점(anchor_low_ts) 직전 N초.  ★신호 직전이 아니다 - 거기선 이미 다 올랐다.
채점 = 신호가 기준 +1.0% 와 -2.0% 중 먼저 닿은 쪽.
"""
import csv
import json
import pathlib
import random

SP = pathlib.Path(r"C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK"
                  r"\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad")
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
                    b = float(r["buy_money_cum"] or 0)
                    s = float(r["sell_money_cum"] or 0)
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    rows.append((h, px, b, s))
        _t[code] = rows
    return _t[code]


def sec(h):
    return int(h[:2]) * 3600 + int(h[3:5]) * 60 + int(h[6:8])


def lam(code, low_t, window):
    """저점 직전 window 초의 흡수. (lambda, 하락%, 순매도억)"""
    seq = ticks(code)
    end = None
    start = None
    tgt = sec(low_t) - window
    for row in seq:
        s = sec(row[0])
        if s <= sec(low_t):
            end = row
        if s <= tgt:
            start = row
    if start is None or end is None or start[1] <= 0:
        return None, None, None
    drop = (end[1] / start[1] - 1) * 100.0          # 음수 = 내려갔다
    net_sell = (end[3] - start[3]) - (end[2] - start[2])
    if net_sell <= 0:
        return None, drop, net_sell / 1e8
    # 억원당 몇 % 밀렸나. 클수록 얕은 시장(= 흡수 없음)
    return abs(drop) / (net_sell / 1e8), drop, net_sell / 1e8


def outcome(code, t, entry):
    for h, q, _b, _s in ticks(code):
        if h < t:
            continue
        r = (q / entry - 1) * 100
        if r <= DOWN:
            return -1
        if r >= UP:
            return 1
    return 0


rows = []
for f in json.loads((SP / "fires_gateoff.json").read_text(encoding="utf-8")):
    code, t = str(f["_code"]).zfill(6), f["_t"]
    px = float(f.get("price") or 0)
    low_ts = str(f.get("anchor_low_ts") or "")
    low_t = low_ts[11:19] if len(low_ts) >= 19 else None
    if not low_t:
        continue
    res = outcome(code, t, px)
    d = {}
    for w in (30, 60, 120):
        d[w] = lam(code, low_t, w)
    rows.append(dict(code=code, t=t, low_t=low_t, res=res,
                     steps=int(float(f.get("dip_low_reset_steps") or 0)), lam=d))
rows.sort(key=lambda z: z["t"])

print("=" * 104)
print("저점을 만들던 구간의 흡수 (억원당 몇 % 밀렸나 - 작을수록 잘 받아냄)")
print("=" * 104)
print(f"{'시각':>9} {'종목':>7} {'저점시각':>9} {'30초':>9} {'60초':>9} {'120초':>9}"
      f" {'60초하락':>9} {'60초순매도(억)':>15}  결과")
print("-" * 104)
lab = {1: "✅ 올랐다", -1: "❌ 밑으로", 0: "· 미도달"}
for r in rows:
    def g(w):
        v = r["lam"][w][0]
        return f"{v:9.2f}" if v is not None else "        -"
    d60 = r["lam"][60][1]
    n60 = r["lam"][60][2]
    print(f"{r['t']:>9} {r['code']:>7} {r['low_t']:>9} {g(30)} {g(60)} {g(120)}"
          f" {(f'{d60:+8.2f}%' if d60 is not None else '       -'):>9}"
          f" {(f'{n60:14.2f}' if n60 is not None else '             -'):>15}"
          f"  {lab[r['res']]}")


def summ(sel, label):
    if not sel:
        return f"  {label:<24} N=0"
    up = sum(1 for x in sel if x["res"] == 1)
    dn = sum(1 for x in sel if x["res"] == -1)
    return (f"  {label:<24} N={len(sel):>2} · 올랐다 {up:>2} · 밑으로 {dn:>2}"
            f" · 승률 {up/len(sel)*100:>5.1f}%")


for w in (30, 60, 120):
    vals = sorted(r["lam"][w][0] for r in rows if r["lam"][w][0] is not None)
    if len(vals) < 6:
        print(f"\n  {w}초 창: 표본 부족({len(vals)})")
        continue
    lo, hi = vals[len(vals) // 3], vals[len(vals) * 2 // 3]
    print(f"\n===== {w}초 창 (문턱 {lo:.2f} / {hi:.2f}) =====")
    print(summ([r for r in rows if r["lam"][w][0] is not None
                and r["lam"][w][0] <= lo], "흡수 잘함(λ 작음)"))
    print(summ([r for r in rows if r["lam"][w][0] is not None
                and lo < r["lam"][w][0] <= hi], "중간"))
    print(summ([r for r in rows if r["lam"][w][0] is not None
                and r["lam"][w][0] > hi], "흡수 못함(λ 큼)"))

w = 60
good = [r for r in rows if r["lam"][w][0] is not None]
if len(good) >= 8:
    vals = sorted(x["lam"][w][0] for x in good)
    med = vals[len(vals) // 2]
    a = [x["res"] == 1 for x in good if x["lam"][w][0] <= med]
    b = [x["res"] == 1 for x in good if x["lam"][w][0] > med]
    obs = sum(a) / len(a) - sum(b) / len(b)
    random.seed(20260807)
    pool = [x["res"] == 1 for x in good]
    hit = 0
    T = 20000
    for _ in range(T):
        random.shuffle(pool)
        p, q = pool[:len(a)], pool[len(a):]
        if abs(sum(p) / len(p) - sum(q) / len(q)) >= abs(obs):
            hit += 1
    print(f"\n  순열검정(60초, 중앙 {med:.2f} 로 반 가름): 차이 {obs*100:+.1f}%p"
          f" · 우연확률 {hit/T*100:.1f}%  (N={len(good)})")

# -*- coding: utf-8 -*-
"""저점 리셋 기준으로 오늘 27건을 가른다. 읽기 전용."""
import csv
import json
import pathlib

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
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    rows.append((h, px))
        _t[code] = rows
    return _t[code]


def touch(code, t, entry):
    lo = entry
    for h, px in ticks(code):
        if h < t:
            continue
        lo = min(lo, px)
        r = (px / entry - 1) * 100
        if r <= DOWN:
            return -1, (lo / entry - 1) * 100
        if r >= UP:
            return 1, (lo / entry - 1) * 100
    return 0, (lo / entry - 1) * 100


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


rows = []
for f in json.loads((SP / "fires_gateoff.json").read_text(encoding="utf-8")):
    code = str(f["_code"]).zfill(6)
    t = f["_t"]
    px = num(f.get("price"), 0.0)
    low = num(f.get("anchor_low"))
    hi = num(f.get("dip_episode_high"))
    res, mae = touch(code, t, px)
    # 리셋 저점(anchor_low) 기준: 그 저점이 직전 고점(episode_high)에서 얼마나 빠졌나
    cyc = (low / hi - 1) * 100 if (low and hi) else None
    rows.append(dict(
        code=code, t=t, res=res, mae=mae,
        steps=int(num(f.get("dip_low_reset_steps"), 0) or 0),
        cyc=cyc,
        reb=(px / low - 1) * 100 if low else None,
        obs=num(f.get("dip_flow_obs_sec")),
        ratio=num(f.get("dip_buy_sell_ratio"))))
rows.sort(key=lambda z: z["t"])


def summ(sel, label):
    if not sel:
        return f"  {label:<28} N=0"
    up = sum(1 for x in sel if x["res"] == 1)
    dn = sum(1 for x in sel if x["res"] == -1)
    m = sorted(x["mae"] for x in sel)
    return (f"  {label:<28} N={len(sel):>2} · 이익 {up:>2} · 손절 {dn:>2}"
            f" · 승률 {up/len(sel)*100:>5.1f}% · MAE중앙 {m[len(m)//2]:+.2f}%")


print("=" * 100)
print(f"{'시각':>9} {'종목':>7} {'리셋횟수':>8} {'리셋저점낙폭':>13} {'저점대비매수':>12}"
      f" {'저점→신호(초)':>13} {'매수÷매도':>10} {'결과':>7}")
print("-" * 100)
for r in rows:
    g = lambda v, s: (format(v, s) if v is not None else "-")   # noqa: E731
    print(f"{r['t']:>9} {r['code']:>7} {r['steps']:>8} {g(r['cyc'], '+12.2f'):>13}"
          f" {g(r['reb'], '+11.2f'):>12} {g(r['obs'], '12.0f'):>13}"
          f" {g(r['ratio'], '9.2f'):>10}"
          f" {('이익' if r['res']==1 else '손절' if r['res']==-1 else '미도달'):>7}")

print("\n" + "=" * 100)
print("저점 리셋 횟수별")
print("=" * 100)
print(summ(rows, "전체"))
for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 999)):
    lab = f"리셋 {lo}회" if hi == lo + 1 else f"리셋 {lo}회 이상" if hi == 999 else f"리셋 {lo}~{hi-1}회"
    print(summ([r for r in rows if lo <= r["steps"] < hi], lab))

print("\n" + "=" * 100)
print("리셋 저점의 낙폭별 (그 저점이 직전 고점에서 얼마나 빠진 자리인가)")
print("=" * 100)
for lo, hi in ((-99, -8), (-8, -6), (-6, -4), (-4, 0)):
    sel = [r for r in rows if r["cyc"] is not None and lo <= r["cyc"] < hi]
    print(summ(sel, f"리셋저점 {hi}% ~ {lo if lo > -99 else '아래'}"))

print("\n" + "=" * 100)
print("저점→신호 경과시간별")
print("=" * 100)
for lo, hi in ((0, 120), (120, 300), (300, 600), (600, 99999)):
    sel = [r for r in rows if r["obs"] is not None and lo <= r["obs"] < hi]
    print(summ(sel, f"{lo}~{hi if hi < 99999 else ''}초"))

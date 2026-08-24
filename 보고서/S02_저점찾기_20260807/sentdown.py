# -*- coding: utf-8 -*-
"""채점 기준: 돈을 잃지 않고 밑으로 다시 내려 보냈는가. 읽기 전용.

  안 샀는데 밑으로 갔다  = ✅잘 내려 보냈다 (돈 안 잃음)
  안 샀는데 위로 갔다    = ❌놓쳤다
  샀는데 밑으로 갔다     = ❌돈 잃음
  샀는데 위로 갔다       = ✅잘 샀다
'밑' = 신호가 -2.0% 도달(손절선) · '위' = 신호가 +1.0% 도달. 먼저 닿은 쪽.
"""
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


def path(code, t, entry):
    """(먼저 닿은 쪽, 신호후 최저%, 신호후 최고%)"""
    res, lo, hi = 0, entry, entry
    hit = False
    for h, q in ticks(code):
        if h < t:
            continue
        lo, hi = min(lo, q), max(hi, q)
        if not hit:
            r = (q / entry - 1) * 100
            if r <= DOWN:
                res, hit = -1, True
            elif r >= UP:
                res, hit = 1, True
    return res, (lo / entry - 1) * 100, (hi / entry - 1) * 100


def load(name):
    return {(str(f["_code"]).zfill(6), f["_t"]): f
            for f in json.loads((SP / name).read_text(encoding="utf-8"))}


off = load("fires_gateoff.json")     # 현행 = 오늘 실제로 돈 규칙
on = load("fires_orig.json")         # 배선된 새 규칙

rows = []
for k, f in off.items():
    code, t = k
    px = float(f.get("price") or 0)
    res, lo, hi = path(code, t, px)
    bought = k in on
    rows.append(dict(code=code, t=t, res=res, lo=lo, hi=hi, bought=bought,
                     steps=int(float(f.get("dip_low_reset_steps") or 0))))
rows.sort(key=lambda z: z["t"])

print("=" * 96)
print("오늘 S02 신호 27건 — 돈을 잃지 않고 밑으로 내려 보냈는가")
print("=" * 96)
print(f"{'시각':>9} {'종목':>7} {'리셋':>5} {'새규칙':>7} {'신호후최저':>11}"
      f" {'신호후최고':>11}  판정")
print("-" * 96)
tally = {"잘내려보냄": [], "놓침": [], "돈잃음": [], "잘삼": [], "애매": []}
for r in rows:
    down = r["res"] == -1
    up = r["res"] == 1
    if not r["bought"]:
        key = "잘내려보냄" if down else ("놓침" if up else "애매")
    else:
        key = "돈잃음" if down else ("잘삼" if up else "애매")
    tally[key].append(r)
    mark = {"잘내려보냄": "✅ 안 사고 밑으로 보냄", "놓침": "❌ 안 샀는데 올랐다",
            "돈잃음": "❌ 샀는데 밑으로", "잘삼": "✅ 샀고 올랐다",
            "애매": "· 둘 다 안 닿음"}[key]
    print(f"{r['t']:>9} {r['code']:>7} {r['steps']:>5}"
          f" {('삼' if r['bought'] else '안 삼'):>7}"
          f" {r['lo']:>+10.2f}% {r['hi']:>+10.2f}%  {mark}")

print("\n" + "=" * 96)
print("현행(전부 삼) vs 새 규칙")
print("=" * 96)
allr = rows
cur_lose = sum(1 for r in allr if r["res"] == -1)
cur_win = sum(1 for r in allr if r["res"] == 1)
print(f"  현행 27건 전부 매수:  돈잃음 {cur_lose}건 · 잘삼 {cur_win}건")
print(f"  새 규칙 {len(on)}건 매수:  돈잃음 {len(tally['돈잃음'])}건"
      f" · 잘삼 {len(tally['잘삼'])}건"
      f"  |  안 산 {len(allr)-len(on)}건 중 ✅잘 내려보냄 {len(tally['잘내려보냄'])}건"
      f" · ❌놓침 {len(tally['놓침'])}건")
print(f"\n  ⇒ 막은 손실 {cur_lose - len(tally['돈잃음'])}건"
      f" · 놓친 이익 {cur_win - len(tally['잘삼'])}건")

# -*- coding: utf-8 -*-
"""신호 목록을 +1% 먼저 / -2% 먼저 로 채점(매도 규칙 안 섞음). 읽기 전용."""
import csv
import json
import pathlib
import sys

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


def score(name):
    out = []
    for f in json.loads((SP / name).read_text(encoding="utf-8")):
        code, t = str(f["_code"]).zfill(6), f["_t"]
        px = float(f.get("price") or 0)
        res, lo = 0, px
        for h, q in ticks(code):
            if h < t:
                continue
            lo = min(lo, q)
            r = (q / px - 1) * 100
            if r <= DOWN:
                res = -1
                break
            if r >= UP:
                res = 1
                break
        out.append(dict(code=code, t=t, res=res, mae=(lo / px - 1) * 100,
                        steps=int(float(f.get("dip_low_reset_steps") or 0))))
    return out


for name, label in (("fires_gateoff.json", "관문 없음(현행)"),
                    ("fires_orig.json", "관문 켬(배선 결과)")):
    if not (SP / name).exists():
        continue
    s = score(name)
    up = sum(1 for x in s if x["res"] == 1)
    dn = sum(1 for x in s if x["res"] == -1)
    m = sorted(x["mae"] for x in s)
    print(f"  {label:<20} N={len(s):>2} · 이익먼저 {up:>2} · 손절먼저 {dn:>2}"
          f" · 미도달 {len(s)-up-dn} · 승률 {up/len(s)*100:>5.1f}%"
          f" · MAE중앙 {m[len(m)//2]:+.2f}%")

a = {(x["code"], x["t"]): x for x in score("fires_gateoff.json")}
b = {(x["code"], x["t"]): x for x in score("fires_orig.json")}
lab = {1: "이익", -1: "손절", 0: "미도달"}
print("\n  사라진 신호:")
for k, v in sorted(a.items(), key=lambda z: z[0][1]):
    if k not in b:
        print(f"    - {v['t']} {v['code']} 리셋{v['steps']:>3}회  {lab[v['res']]}")
print("  새로 생긴 신호(관문에 막혔다가 뒤에서 다시 난 것):")
for k, v in sorted(b.items(), key=lambda z: z[0][1]):
    if k not in a:
        print(f"    + {v['t']} {v['code']} 리셋{v['steps']:>3}회  {lab[v['res']]}")

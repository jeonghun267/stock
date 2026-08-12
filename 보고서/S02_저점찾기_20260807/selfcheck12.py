# -*- coding: utf-8 -*-
"""자가검사: '가르는 선'이 측정 창 비대칭 때문에 생긴 착시인가. 읽기 전용.

multi12.score_fire 는 꼭지를 이렇게 쟀다
  패자: 저점 -> 손절 닿은 지점까지   (죽는 순간에 끊음)
  승자: 저점 -> 장 끝까지            (안 끊음)
이러면 승자 쪽 꼭지가 구조적으로 커진다. 그 비대칭을 없애고 다시 잰다.

대칭 잣대 두 가지로 재확인한다
  A. 둘 다 '결판 시점'까지 — 승자는 +1% 닿은 순간, 패자는 -2% 닿은 순간에서 끊는다
  B. 둘 다 '신호 + 같은 시간'까지 — 패자의 손절까지 걸린 시간 중앙값만큼만 본다
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0
LINES = (2.0, 2.2, 2.4, 2.6, 2.8, 3.0)

rows = [json.loads(x) for x in
        (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
_t = {}


def ticks(date, code):
    key = (date, code)
    if key not in _t:
        out = []
        with (CACHE / f"{date}_{code}.csv").open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                h = r["ts"][11:19]
                if h < "09:00:00":
                    continue
                try:
                    px = float(r["current_price"])
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    out.append((h, px))
        _t[key] = out
    return _t[key]


def _sec(h):
    return int(h[:2]) * 3600 + int(h[3:5]) * 60 + int(h[6:8])


recomputed = []
for r in rows:
    tk = ticks(r["date"], r["code"])
    low_i = next((i for i, (h, _) in enumerate(tk) if h >= str(r["t"])), None)
    # 저점 시각은 원본에 없으니 신호가/entry_gap 으로 저점가를 복원한다
    sig_i = next((i for i, (h, _) in enumerate(tk) if h >= r["t"]), None)
    if sig_i is None:
        continue
    price = tk[sig_i][1]
    low = price / (1.0 + r["entry_gap"] / 100.0)
    # 저점 지점(신호 이전에서 그 가격에 가장 가까운 마지막 지점)
    li = None
    for i in range(sig_i, -1, -1):
        if tk[i][1] <= low * 1.0005:
            li = i
            break
    if li is None:
        li = sig_i
    # 결판 지점
    end_i, res = len(tk) - 1, 0
    for i in range(sig_i, len(tk)):
        rr = (tk[i][1] / price - 1) * 100
        if rr <= DOWN:
            end_i, res = i, -1
            break
        if rr >= UP:
            end_i, res = i, 1
            break
    if res == 0:
        continue
    peak_decision = (max(q for _, q in tk[li:end_i + 1]) / low - 1) * 100
    peak_eod = (max(q for _, q in tk[li:]) / low - 1) * 100
    recomputed.append(dict(res=res, dec=peak_decision, eod=peak_eod,
                           secs=_sec(tk[end_i][0]) - _sec(tk[sig_i][0])))

W = [x for x in recomputed if x["res"] == 1]
L = [x for x in recomputed if x["res"] == -1]
print("=" * 88)
print(f"자가검사 — 같은 잣대로 다시 재기 (승 {len(W)} · 패 {len(L)})")
print("=" * 88)
for name, key in (("종전(승자만 장끝까지 = 비대칭)", "eod"),
                  ("대칭 A (둘 다 결판 시점까지)", "dec")):
    lv = sorted(x[key] for x in L)
    wv = sorted(x[key] for x in W)
    print(f"\n[{name}]")
    print(f"  패자 꼭지: 중앙 {statistics.median(lv):+.2f}% · 90분위 {lv[int(len(lv)*0.9)]:+.2f}%"
          f" · 최대 {lv[-1]:+.2f}%")
    print(f"  승자 꼭지: 최소 {wv[0]:+.2f}% · 25분위 {wv[int(len(wv)*0.25)]:+.2f}%"
          f" · 중앙 {statistics.median(wv):+.2f}%")
    print(f"  {'선':>6} {'가짜 걸러짐':>12} {'진짜 잘못 걸러짐':>16}")
    for ln in LINES:
        fl = sum(1 for x in L if x[key] < ln)
        fw = sum(1 for x in W if x[key] < ln)
        print(f"  {ln:>5.1f}% {fl:>6}/{len(L):<5} ({fl/len(L)*100:4.1f}%)"
              f" {fw:>7}/{len(W):<5} ({fw/len(W)*100:4.1f}%)")

print()
sl = sorted(x["secs"] for x in L)
sw = sorted(x["secs"] for x in W)
print(f"결판까지 걸린 시간: 패자 중앙 {statistics.median(sl)/60:.1f}분"
      f" · 승자 중앙 {statistics.median(sw)/60:.1f}분")
print()
print("읽는 법: 대칭 A 에서도 선이 남아 있으면 진짜 신호다.")
print("        승자 최소가 크게 내려가면 종전 표는 측정 창이 만든 착시였다.")

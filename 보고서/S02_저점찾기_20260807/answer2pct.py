# -*- coding: utf-8 -*-
"""친구님 질문에 대한 직접 답: "+X%까지 올라왔다가 도로 떨어지면 파는 게 낫나?"

두 가지를 잰다 (multi12 신호 + 같은 캐시, 판정 재구현 없음 — 가격 경로만):

  [1] +X%(1.5/2.0/3.0)까지 올라갔다가 본전(0%)까지 되밀린 놈이, 그 뒤 어떻게 됐나
      → "다시 반등해서 많이 올라가는 걸 못 본 것 같아"가 사실인지 세어본다
      (되밀린 뒤 +1% 회복이 먼저냐, -2% 손절이 먼저냐, 그리고 되밀린 뒤 최고 몇 %까지 갔나)

  [2] 본전 청산 규칙의 손익: "조금이라도 올랐다가(+0.3/0.5/0.7% 이상) 본전으로 되밀리면
      0%에 판다" vs 현행 "-2%까지 끌고 간다" — 건당 기대값 비교
      (왕복비용은 두 규칙 다 거래마다 똑같이 나가므로 비교에는 영향 없음)
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0

fires = [json.loads(x) for x in
         (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
dates = sorted({f["date"] for f in fires})

_t = {}


def ticks(date, code):
    key = (date, code)
    if key not in _t:
        rows = []
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
                    rows.append((h, px))
        _t[key] = rows
    return _t[key]


paths = []          # 신호별 수익률 경로
for f in fires:
    tk = ticks(f["date"], f["code"])
    sig_i = next((i for i, (h, _) in enumerate(tk) if h >= f["t"]), None)
    if sig_i is None:
        continue
    P = tk[sig_i][1]
    paths.append([(q / P - 1) * 100 for _, q in tk[sig_i:]])

print("=" * 96)
print(f"[{'·'.join(dates)}] 신호 {len(paths)}건 기준")
print("=" * 96)

print()
print("[1] +X%까지 올라갔다가 본전(0%)으로 되밀린 놈은 그 뒤 어떻게 되나")
print(f"{'문턱':>6} {'도달':>5} {'되밀림':>6} {'→다시+1%회복':>11} {'→-2%손절':>9}"
      f" {'→어중간':>7} {'되밀린뒤 최고(중앙)':>16}")
for x in (1.5, 2.0, 3.0):
    reach = pull = rewin = relose = mid = 0
    remax = []
    for rs in paths:
        i2 = next((i for i, r in enumerate(rs) if r >= x), None)
        if i2 is None:
            continue
        reach += 1
        i0 = next((i for i in range(i2 + 1, len(rs)) if rs[i] <= 0.0), None)
        if i0 is None:
            continue
        pull += 1
        after = rs[i0:]
        out = 0
        for r in after:
            if r >= UP:
                out = 1
                break
            if r <= DOWN:
                out = -1
                break
        if out == 1:
            rewin += 1
        elif out == -1:
            relose += 1
        else:
            mid += 1
        remax.append(max(after))
    med = statistics.median(remax) if remax else float("nan")
    print(f"{x:>5.1f}% {reach:>5} {pull:>6} {rewin:>11} {relose:>9} {mid:>7}"
          f" {med:>+14.2f}%")

print()
print("[2] 본전 청산 vs 현행(-2%까지) — +1% 먼저 승 / -2% 먼저 패 틀로 비교")
base = {"승": 0, "패": 0, "애매": 0}
for rs in paths:
    out = "애매"
    for r in rs:
        if r <= DOWN:
            out = "패"
            break
        if r >= UP:
            out = "승"
            break
    base[out] += 1
n = len(paths)
ev0 = (base["승"] * UP + base["패"] * DOWN) / n
print(f"  현행: 승 {base['승']} · 패 {base['패']} · 애매 {base['애매']}"
      f" → 건당 {ev0:+.3f}%")
print(f"  {'무장문턱':>8} {'승':>5} {'본전':>5} {'패':>5} {'애매':>4} {'건당':>8}"
      f"   본전에 판 것들의 원래 결말")
for a in (0.3, 0.5, 0.7):
    r_ = {"승": 0, "본전": 0, "패": 0, "애매": 0}
    orig = {"승": 0, "패": 0, "애매": 0}
    for rs in paths:
        armed = False
        out = "애매"
        for r in rs:
            if r >= UP:
                out = "승"
                break
            if r <= DOWN:
                out = "패"
                break
            if armed and r <= 0.0:
                out = "본전"
                break
            if r >= a:
                armed = True
        r_[out] += 1
        if out == "본전":
            b = "애매"
            for r in rs:
                if r <= DOWN:
                    b = "패"
                    break
                if r >= UP:
                    b = "승"
                    break
            orig[b] += 1
    ev = (r_["승"] * UP + r_["패"] * DOWN) / n
    print(f"  {a:>7.1f}% {r_['승']:>5} {r_['본전']:>5} {r_['패']:>5} {r_['애매']:>4}"
          f" {ev:>+7.3f}%   놓친 승 {orig['승']} · 피한 패 {orig['패']} · 애매 {orig['애매']}")

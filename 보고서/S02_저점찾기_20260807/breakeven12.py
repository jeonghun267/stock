# -*- coding: utf-8 -*-
"""친구님 제안(8/7 저녁) 채점: 본전 청산 — 읽기 전용.

> "1.5~3%까지 올랐다가 떨어지는 것들이 다시 반등해서 많이 올라가는 걸 못 본 것 같아.
>  -2% 손절까지 끌고 가지 말고 0%(본전)에서 매도하고, 그 돈으로 저점에서 다음 기회를 노리자."

채점 방법 (multi12.py 가 만든 신호 목록 + 같은 캐시 사용, 판정 재구현 없음 — 가격 경로만 본다)
  기준: 지금 채점 틀 그대로 = 신호가 대비 +1.0% 먼저면 승 / -2.0% 먼저면 패
  본전 규칙: 신호 후 +A% 이상 오른 적이 있고(무장), 그 뒤 0% 이하로 되밀리면 본전(0%)에 매도.
             무장 문턱 A = 0.3 / 0.5 / 0.7 세 가지로 잰다.
  ① 되밀린 놈들이 그 뒤 실제로 어디로 갔나 (본전에 판 것들의 원래 결말 = 놓친 승 vs 피한 패)
  ② 건당 기대값 비교 (왕복비용은 두 규칙 모두 같은 상수라 비교에는 영향 없음 — 절대값만 -0.3%p쯤)
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0
ARMS = (0.3, 0.5, 0.7)

fires = [json.loads(x) for x in
         (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

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


results = {a: {"승": 0, "본전": 0, "패": 0, "애매": 0,
               "본전의_원래결말": {"승": 0, "패": 0, "애매": 0}} for a in ARMS}
base = {"승": 0, "패": 0, "애매": 0}
n_skip = 0

for f in fires:
    tk = ticks(f["date"], f["code"])
    sig_i = next((i for i, (h, _) in enumerate(tk) if h >= f["t"]), None)
    if sig_i is None:
        n_skip += 1
        continue
    P = tk[sig_i][1]                      # 신호 시점 가격 = 진입가
    rs = [(q / P - 1) * 100 for _, q in tk[sig_i:]]

    bres = "애매"
    for r in rs:
        if r <= DOWN:
            bres = "패"
            break
        if r >= UP:
            bres = "승"
            break
    base[bres] += 1

    for a in ARMS:
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
        results[a][out] += 1
        if out == "본전":
            results[a]["본전의_원래결말"][bres] += 1

n = sum(base.values())
out = []
P_ = out.append
P_("=" * 96)
P_(f"본전 청산 채점 — 12일 재생 신호 {n}건 (자료부족 제외 {n_skip})")
P_("=" * 96)
ev0 = (base["승"] * UP + base["패"] * DOWN) / n
P_(f"기준(현행 -2%까지 끌고감): 승 {base['승']} · 패 {base['패']} · 애매 {base['애매']}"
   f"  → 건당 기대 {ev0:+.3f}%")
P_("")
P_(f"{'무장문턱':>8} {'승':>5} {'본전':>5} {'패':>5} {'애매':>4} {'건당기대%':>9}"
   f"   본전에 판 것들의 원래 결말")
for a in ARMS:
    r = results[a]
    ev = (r["승"] * UP + r["패"] * DOWN) / n
    d = r["본전의_원래결말"]
    P_(f"{a:>7.1f}% {r['승']:>5} {r['본전']:>5} {r['패']:>5} {r['애매']:>4} {ev:>+8.3f}"
       f"   놓친 승 {d['승']} · 피한 패 {d['패']} · 애매 {d['애매']}")
P_("")
P_("읽는 법: '피한 패'가 '놓친 승'보다 많고 건당 기대가 기준보다 좋으면 친구님 말씀이 맞는 것.")
P_("왕복비용(~0.3%p)은 어느 규칙이든 거래마다 똑같이 나가므로 비교에는 영향 없음.")
text = "\n".join(out)
(HERE / "breakeven12_결과.txt").write_text(text, encoding="utf-8")
print(text)

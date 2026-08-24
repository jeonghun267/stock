# -*- coding: utf-8 -*-
"""친구님 목적 재정의: "흘러내림 저점까지만 잡는 게 목적. 매도 이익은 소용없다."

그래서 채점을 바꾼다. 승률·수익이 아니라 **산 자리가 바닥이었나** 하나만 본다.

  추가하락 = 매수(신호) 후 그 종목이 얼마나 더 흘러내렸는가
             0% 에 가까울수록 바닥을 산 것. -5% 면 5% 더 흘러내린 뒤 바닥이 왔다는 뜻.
  ⚠️손절·매도 규칙을 섞지 않는다. 팔았든 안 팔았든 "그 자리가 바닥이었나"만 본다.
     장 끝까지 본다(당일 한정 — S02 는 15:10 청산이므로 그날 안이 판단 범위다).

보는 것
  ① 전체 분포 — 우리는 평균 몇 % 위에서 사고 있나
  ② 일별 — 흘러내리는 날에 더 심한가 (친구님 가설)
  ③ 아침 시장 상태로 그 날을 알 수 있나 (지표 4종과 순위상관)
  ④ '초반 2건이 계속 흘러내리면 중단' 규칙이 추가하락을 줄이나
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")

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


scored = []
for r in rows:
    tk = ticks(r["date"], r["code"])
    i = next((k for k, (h, _) in enumerate(tk) if h >= r["t"]), None)
    if i is None:
        continue
    buy = tk[i][1]
    after = tk[i:]
    low_after = min(q for _, q in after)
    drop = (low_after / buy - 1) * 100          # 0 이면 바닥을 샀다
    # 바닥까지 걸린 시간
    li = next(k for k, (_, q) in enumerate(after) if q == low_after)
    secs = (int(after[li][0][:2]) * 3600 + int(after[li][0][3:5]) * 60 + int(after[li][0][6:8])
            - (int(after[0][0][:2]) * 3600 + int(after[0][0][3:5]) * 60 + int(after[0][0][6:8])))
    scored.append(dict(date=r["date"], t=r["t"], code=r["code"], drop=drop,
                       secs=secs, res=r["res"]))

out = []
P = out.append
allv = sorted(x["drop"] for x in scored)
n = len(allv)
P("=" * 92)
P(f"채점 재정의 — 산 자리가 바닥이었나 (신호 {n}건 · 매도규칙 안 섞음)")
P("=" * 92)
P(f"매수 후 추가하락: 중앙 {statistics.median(allv):+.2f}%"
  f" · 25분위 {allv[n//4]:+.2f}% · 75분위 {allv[n*3//4]:+.2f}% · 최악 {allv[0]:+.2f}%")
for th in (0.5, 1.0, 2.0, 3.0, 5.0):
    c = sum(1 for v in allv if v >= -th)
    P(f"  추가하락 {th}% 이내(=거의 바닥): {c}/{n} = {c/n*100:.1f}%")
P(f"  바닥까지 걸린 시간 중앙: {statistics.median([x['secs'] for x in scored])/60:.1f}분")

P("")
P("=" * 92)
P("② 일별 — 흘러내리는 날에 더 심한가")
P("=" * 92)
P(f"{'날짜':>10} {'신호':>5} {'추가하락 중앙':>13} {'2%내 비율':>10} {'최악':>9}")
by_day = {}
for x in scored:
    by_day.setdefault(x["date"], []).append(x)
day_med = {}
for d in sorted(by_day):
    g = [x["drop"] for x in by_day[d]]
    med = statistics.median(g)
    day_med[d] = med
    within = sum(1 for v in g if v >= -2.0) / len(g) * 100
    P(f"{d:>10} {len(g):>5} {med:>+12.2f}% {within:>9.1f}% {min(g):>+8.2f}%")
meds = sorted(day_med.values())
P(f"\n  일별 추가하락 중앙의 범위: {meds[0]:+.2f}% ~ {meds[-1]:+.2f}%"
  f"  (폭 {meds[-1]-meds[0]:.2f}%p)")

P("")
P("=" * 92)
P("④ '처음 2건이 각각 2% 넘게 더 흘러내리면 그날 중단' 규칙")
P("=" * 92)
P(f"{'규칙':>34} {'거래':>6} {'추가하락 중앙':>13} {'2%내':>8} {'총 추가하락':>11}")


def summarize(items):
    v = [x["drop"] for x in items]
    if not v:
        return 0, float("nan"), float("nan"), 0.0
    return (len(v), statistics.median(v),
            sum(1 for q in v if q >= -2.0) / len(v) * 100, sum(v))


t, med, w, s = summarize(scored)
P(f"{'현행(전부 매수)':>34} {t:>6} {med:>+12.2f}% {w:>7.1f}% {s:>+10.1f}")
for k, th in ((2, 2.0), (2, 1.0), (3, 2.0)):
    kept = []
    for d in sorted(by_day):
        g = sorted(by_day[d], key=lambda x: x["t"])
        head = g[:k]
        kept.extend(head)
        if not all(x["drop"] <= -th for x in head):
            kept.extend(g[k:])
    t, med, w, s = summarize(kept)
    P(f"{f'첫{k}건 전부 {th}%↑ 하락이면 중단':>34} {t:>6} {med:>+12.2f}% {w:>7.1f}% {s:>+10.1f}")

P("")
P("읽는 법: 추가하락 중앙이 0 에 가까울수록 바닥을 잘 산 것.")
P("        '총 추가하락'은 작을수록(0에 가까울수록) 좋다 — 흘러내림에 덜 물렸다는 뜻.")
text = "\n".join(out)
(HERE / "bottom12_결과.txt").write_text(text, encoding="utf-8")
print(text)

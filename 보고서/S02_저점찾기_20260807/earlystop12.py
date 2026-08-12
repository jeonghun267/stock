# -*- coding: utf-8 -*-
"""친구님 질문 2단계: 시장 지표 말고 '전략 자신의 초반 성적'으로 그날을 알 수 있나. 읽기 전용.

시장 상태(09:05~09:20 등락·체결강도)는 그날 승률과 사실상 무관했다(daygate12.py).
그렇다면 남은 방법은 전략이 직접 겪어 보는 것 — "오늘 처음 N건이 지면 그만둔다".

  ① 첫 N건의 결과가 그날 나머지를 예측하는가 (예측력이 없으면 이 방법도 죽는다)
  ② 실제로 그 규칙을 걸었을 때 12일 합계가 나아지는가 (건당 기대 + 총 손익)

채점틀은 종전과 같다: 신호가 +1.0% 먼저면 승, -2.0% 먼저면 패.
⚠️승자를 +1%로 끊는 틀이라 '멈춰서 아낀 손실'은 정확하지만 '놓친 이익'은 과소평가된다.
  실제 승자는 신호가 대비 중앙 +3.55% 까지 간다 — 결과를 읽을 때 이 편향을 감안할 것.
"""
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
UP, DOWN = 1.0, -2.0

rows = [json.loads(x) for x in
        (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
by_day = {}
for r in rows:
    by_day.setdefault(r["date"], []).append(r)
for d in by_day:
    by_day[d].sort(key=lambda r: r["t"])
dates = sorted(by_day)

out = []
P = out.append

P("=" * 92)
P("① 첫 N건의 성적이 그날 나머지를 예측하는가")
P("=" * 92)
for n in (2, 3, 5):
    P(f"\n[처음 {n}건 기준]")
    P(f"{'날짜':>10} {'첫N':>6} {'나머지 승률':>11} {'나머지 건수':>10}")
    grp = {}
    for d in dates:
        g = [r for r in by_day[d] if r["res"] in (1, -1)]
        if len(g) <= n:
            continue
        head, tail = g[:n], g[n:]
        hw = sum(1 for r in head if r["res"] == 1)
        tw = sum(1 for r in tail if r["res"] == 1)
        rate = tw / len(tail) * 100
        grp.setdefault(hw, []).append((len(tail), tw))
        P(f"{d:>10} {hw:>3}승{n-hw}패 {rate:>10.1f}% {len(tail):>10}")
    P("  첫N 성적별 나머지 승률:")
    for hw in sorted(grp):
        tot = sum(x[0] for x in grp[hw])
        win = sum(x[1] for x in grp[hw])
        P(f"    첫 {n}건 중 {hw}승 → 나머지 {win}/{tot} = {win/tot*100:.1f}%"
          f"  (해당 {len(grp[hw])}일)")

P("")
P("=" * 92)
P("② 그 규칙을 실제로 걸면 12일 합계가 나아지나")
P("=" * 92)
P(f"{'규칙':>28} {'거래':>6} {'승':>5} {'패':>5} {'승률':>7} {'건당':>8} {'총합%':>9}")


def score(trades):
    w = sum(1 for r in trades if r["res"] == 1)
    l = sum(1 for r in trades if r["res"] == -1)
    n = w + l
    total = w * UP + l * DOWN
    return len(trades), w, l, (w / n * 100 if n else float("nan")), \
        (total / n if n else float("nan")), total


base = [r for d in dates for r in by_day[d] if r["res"] in (1, -1)]
t, w, l, wr, ev, tot = score(base)
P(f"{'현행(전부 매수)':>28} {t:>6} {w:>5} {l:>5} {wr:>6.1f}% {ev:>+7.3f} {tot:>+8.1f}")

for n, need in ((2, 1), (3, 1), (3, 2), (5, 2)):
    kept = []
    for d in dates:
        g = [r for r in by_day[d] if r["res"] in (1, -1)]
        head = g[:n]
        kept.extend(head)
        if sum(1 for r in head if r["res"] == 1) >= need:
            kept.extend(g[n:])
    t, w, l, wr, ev, tot = score(kept)
    P(f"{f'첫{n}건 중 {need}승 미만이면 중단':>28} {t:>6} {w:>5} {l:>5} {wr:>6.1f}%"
      f" {ev:>+7.3f} {tot:>+8.1f}")

P("")
P("읽는 법: 총합%가 현행보다 커야 이득이다. 건당이 좋아져도 거래가 줄어 총합이 작아지면")
P("        '덜 벌고 덜 잃은 것'이지 개선이 아니다.")

text = "\n".join(out)
(HERE / "earlystop12_결과.txt").write_text(text, encoding="utf-8")
print(text)

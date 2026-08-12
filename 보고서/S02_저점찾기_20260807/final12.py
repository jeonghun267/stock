# -*- coding: utf-8 -*-
"""12일 검증 최종 정리용 보조 계산 — 읽기 전용.

  ① 일별 승률(날짜가 만드는 폭)
  ② 승자의 실제 크기 — 본전청산이 이득이 되려면 승자가 몇 %여야 하는가
"""
import csv
import json
import pathlib
import statistics

HERE = pathlib.Path(__file__).parent
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0

rows = [json.loads(x) for x in
        (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

print("=" * 84)
print("① 일별 승률 — 규칙이 아니라 날짜가 성적을 정한다")
print("=" * 84)
print(f"{'날짜':>10} {'신호':>5} {'승':>5} {'패':>5} {'승률':>8}")
by_day = {}
for r in rows:
    by_day.setdefault(r["date"], []).append(r)
wr_list = []
for d in sorted(by_day):
    g = by_day[d]
    w = sum(1 for x in g if x["res"] == 1)
    l = sum(1 for x in g if x["res"] == -1)
    wr = w / (w + l) * 100 if (w + l) else float("nan")
    wr_list.append(wr)
    print(f"{d:>10} {len(g):>5} {w:>5} {l:>5} {wr:>7.1f}%")
print(f"\n  승률 범위 {min(wr_list):.1f}% ~ {max(wr_list):.1f}%  (폭 {max(wr_list)-min(wr_list):.1f}%p)")

print()
print("=" * 84)
print("② 승자의 실제 크기 — 본전청산이 이득이려면 승자가 얼마나 작아야 하나")
print("=" * 84)
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


# 승자가 신호가 대비 실제로 어디까지 갔나(=+1%로 끊지 않았다면)
mfe = []
for r in rows:
    if r["res"] != 1:
        continue
    tk = ticks(r["date"], r["code"])
    i = next((k for k, (h, _) in enumerate(tk) if h >= r["t"]), None)
    if i is None:
        continue
    P = tk[i][1]
    peak = max(q for _, q in tk[i:])
    mfe.append((peak / P - 1) * 100)
mfe.sort()
print(f"승자 {len(mfe)}건의 신호가 대비 최고 도달률")
print(f"  25분위 {mfe[len(mfe)//4]:+.2f}%  ·  중앙 {statistics.median(mfe):+.2f}%"
      f"  ·  75분위 {mfe[len(mfe)*3//4]:+.2f}%")

# 본전청산 손익분기: 피한 패 x 2.0 == 놓친 승 x W
for arm, missed_win, avoided_loss in ((0.3, 320, 235), (0.5, 218, 141), (0.7, 122, 85)):
    w_break = avoided_loss * abs(DOWN) / missed_win
    print(f"  무장 {arm}%: 놓친 승 {missed_win} · 피한 패 {avoided_loss}"
          f"  -> 승자 평균이 {w_break:.2f}% 보다 크면 본전청산이 손해")

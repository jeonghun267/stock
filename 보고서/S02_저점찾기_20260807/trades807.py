# -*- coding: utf-8 -*-
"""오늘(8/7) S02 가 실제로 산 13건에 새 관문을 대본다. 읽기 전용.

  fires_gateoff.json = 관문 끈 재생(=오늘 실제로 돈 규칙)
  fires_orig.json    = 관문 켠 재생(=배선된 새 규칙, 실전 모듈 그대로)
매수는 신호 뒤 90초 안에 나므로 종목·시각으로 짝짓는다.
"""
import datetime
import json
import pathlib

SP = pathlib.Path(r"C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK"
                  r"\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad")


def hhmmss(s):
    return datetime.datetime.strptime(s, "%H:%M:%S")


def load(name):
    out = {}
    for f in json.loads((SP / name).read_text(encoding="utf-8")):
        out.setdefault(str(f["_code"]).zfill(6), []).append(
            (f["_t"], int(float(f.get("dip_low_reset_steps") or 0))))
    for c in out:
        out[c].sort()
    return out


off = load("fires_gateoff.json")
on = load("fires_orig.json")
trades = json.loads((SP / "today_trades.json").read_text(encoding="utf-8"))


def nearest(sigs, code, t, window=180):
    """매수 시각 직전 window 초 안의 신호."""
    best = None
    for st, steps in sigs.get(code, []):
        d = (hhmmss(t) - hhmmss(st)).total_seconds()
        if 0 <= d <= window and (best is None or d < best[0]):
            best = (d, st, steps)
    return best


print("=" * 104)
print("오늘 S02 실매수 13건에 저점리셋 관문(리셋 4회 이상)을 대면")
print("=" * 104)
print(f"{'매수시각':>9} {'종목':>7} {'이름':<11} {'실현':>8} {'짝지은신호':>10}"
      f" {'리셋':>5} {'새규칙':>7}  매도사유")
print("-" * 104)

kept, cut, unknown = [], [], []
for tr in trades:
    code, t = tr["code"], tr["t"]
    m = nearest(off, code, t)
    if m is None:
        unknown.append(tr)
        sig, steps, verdict = "-", "-", "짝못지음"
    else:
        _, sig, steps = m
        survives = nearest(on, code, t) is not None
        verdict = "삼" if survives else "안 삼"
        (kept if survives else cut).append(tr)
        steps = str(steps)
    r = "보유" if tr["ret"] is None else f"{tr['ret']:+.2f}%"
    print(f"{t:>9} {code:>7} {str(tr['name'])[:11]:<11} {r:>8} {sig:>10}"
          f" {steps:>5} {verdict:>7}  {tr['why']}")


def tot(rows):
    v = [x["ret"] for x in rows if x["ret"] is not None]
    if not v:
        return "청산 0건"
    return (f"{len(v)}건 · 합계 {sum(v):+.2f}% · 평균 {sum(v)/len(v):+.2f}%"
            f" · 승 {sum(1 for x in v if x > 0)}/{len(v)}")


print("\n" + "=" * 104)
print(f"  오늘 실제        {tot(trades)}")
print(f"  새 규칙이면 삼   {tot(kept)}")
print(f"  새 규칙이 거름   {tot(cut)}")
if unknown:
    print(f"  짝 못 지은 건    {len(unknown)}건 (재생 신호와 시각이 안 맞음)")
a = sum(x["ret"] for x in trades if x["ret"] is not None)
b = sum(x["ret"] for x in kept if x["ret"] is not None)
print(f"\n  => 합계 {a:+.2f}%  ->  {b:+.2f}%   차이 {b-a:+.2f}%p")
print("\n  ⚠️ 거른 자리에 공용 슬롯이 비어 다른 종목을 샀을 수 있다(위 수치엔 안 들어감).")

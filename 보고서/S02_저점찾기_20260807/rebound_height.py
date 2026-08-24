# -*- coding: utf-8 -*-
"""첫 저점에서 몇 %까지 올랐다 떨어지는가 — 오늘 실거래 6건. 읽기 전용."""
import json, pathlib, datetime, re

d = json.loads(pathlib.Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json")
               .read_text(encoding="utf-8-sig"))
sig = json.loads(pathlib.Path(r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json")
                 .read_text(encoding="utf-8-sig"))
snap = json.loads(pathlib.Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
                  .read_text(encoding="utf-8-sig")).get("codes") or {}


def num(x):
    try:
        return float(str(x).replace(",", "").lstrip("+"))
    except Exception:
        return 0.0


reb_by_code = {}
for s in (sig.get("signals") or []):
    if isinstance(s, dict) and s.get("code"):
        m = re.search(r"rebound=([\d.]+)%", str(s.get("reason") or ""))
        if m:
            reb_by_code.setdefault(str(s["code"]).zfill(6), float(m.group(1)))

print(f"===== 첫 저점 → 반등 고점 → 되밀림 (오늘 실거래) {datetime.datetime.now():%H:%M:%S} =====")
print("진입은 저점 +1.5~2.0% 구간에서 이뤄진다(S06식 계단).")
print("따라서  저점대비 총상승 = 진입까지 반등(rebound) + 진입 후 최대상승(MFE)\n")
print(f"{'종목':>8} {'저점':>10} {'진입':>10} {'반등%':>7} {'MFE%':>7} "
      f"{'저점대비최고%':>12} {'결과%':>7}")
print("-" * 72)

tot = []
for h in (d.get("history") or []):
    if not isinstance(h, dict):
        continue
    code = str(h.get("code")).zfill(6)
    entry = num(h.get("entry_price"))
    peak = num(h.get("peak_price"))
    mfe = num(h.get("mfe_pct"))
    g = num(h.get("gross_return_pct"))
    reb = reb_by_code.get(code)
    if not entry or reb is None:
        continue
    low = entry / (1.0 + reb / 100.0)
    top_from_low = (max(peak, entry) / low - 1.0) * 100.0
    tot.append(top_from_low)
    print(f"{code:>8} {low:>10,.0f} {entry:>10,.0f} {reb:>6.2f}% {mfe:>6.2f}% "
          f"{top_from_low:>11.2f}% {g:>6.2f}%")

if tot:
    tot_s = sorted(tot)
    print(f"\n저점 대비 최고 반등폭:  최소 {min(tot):.2f}% · 중앙 {tot_s[len(tot_s)//2]:.2f}% "
          f"· 최대 {max(tot):.2f}% · 평균 {sum(tot)/len(tot):.2f}%")
    print(f"  4% 이상 오른 건: {sum(1 for x in tot if x >= 4.0)}건 / {len(tot)}건  "
          f"← 꼭지무장(4%)이 켜졌을 종목")
    for th in (2.0, 2.5, 3.0, 3.5, 4.0):
        print(f"    {th}% 이상: {sum(1 for x in tot if x >= th)}건")

print("\n--- 참고: 오늘 감시 종목 전체의 '저가 → 고가' 폭 (첫 저점 아님·하루 전체) ---")
hr = json.loads(pathlib.Path(r"C:\stock_bot\IPC\micro_watch_high_range.json")
                .read_text(encoding="utf-8-sig"))
codes = [str(c).zfill(6) for c in (hr.get("codes") or [])]
vals = []
for c in codes:
    r = snap.get(c) or {}
    lo, hi = num(r.get("lo")), num(r.get("hi"))
    if lo > 0 and hi > 0:
        vals.append((hi / lo - 1) * 100)
if vals:
    vals.sort()
    print(f"  감시 {len(vals)}종목 · 저가→고가 중앙 {vals[len(vals)//2]:.2f}% "
          f"· 최소 {vals[0]:.2f}% · 최대 {vals[-1]:.2f}%")
    print("  ※ 이건 하루 전체 폭이라 '첫 저점에서의 첫 반등폭'보다 훨씬 크다. 상한선으로만 보라.")

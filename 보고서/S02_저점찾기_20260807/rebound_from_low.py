# -*- coding: utf-8 -*-
"""8/6 -6%↓ 마감 종목이 오늘 '저점 대비' 얼마나 반등했나 — 읽기 전용."""
import csv, json, pathlib, datetime

BARS = pathlib.Path(r"C:\stock_bot\data\eod_daily_bars.csv")
SNAP = pathlib.Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
SHADOW = pathlib.Path(r"C:\stock_bot\data\high_range_shadow_20260807.csv")

snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes") or {}


def num(x):
    try:
        return float(str(x).replace(",", "").lstrip("+"))
    except Exception:
        return 0.0


# 그림자에서 저가/고가 시각 (30종목만 가능)
times = {}
if SHADOW.exists():
    with SHADOW.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            times[str(r["code"]).zfill(6)] = (r.get("low_time"), r.get("high_time"))

rows = []
with BARS.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
    for r in csv.DictReader(fh):
        if r.get("date") != "20260806":
            continue
        close = num(r["close"]); low = num(r["low"]); high = num(r["high"])
        val = num(r["value"]); ret = num(r["daily_return"]) * 100
        if close < 10000 or val < 3000 or high <= low:
            continue
        if ret > -6.0:
            continue
        code = str(r["code"]).zfill(6)
        s = snap.get(code) or {}
        op, cur, lo, hi = num(s.get("op")), num(s.get("cur")), num(s.get("lo")), num(s.get("hi"))
        if not (op and cur and lo and hi):
            continue
        lt, ht = times.get(code, (None, None))
        rows.append({
            "code": code, "name": r.get("name", "")[:12], "ret": ret,
            "prev_close": close, "op": op, "cur": cur, "lo": lo, "hi": hi,
            "reb_hi": (hi / lo - 1) * 100,     # 저가→고가 (순서 미보장)
            "reb_now": (cur / lo - 1) * 100,   # 저가→현재 (확정)
            "low_from_open": (lo / op - 1) * 100,
            "low_from_prev": (lo / close - 1) * 100,
            "lt": lt, "ht": ht,
        })

print(f"===== 8/6 -6% 이하 마감 · 오늘 저점 대비 반등 ({datetime.datetime.now():%H:%M:%S}) =====")
print(f"대상 {len(rows)}종목 (대금 30억↑·1만원↑·오늘 시세 확인 가능)\n")
print(f"{'종목':>8} {'8/6등락':>8} {'저가@시가':>9} {'저가@전일':>9} "
      f"{'저가→현재':>9} {'저가→고가':>9} {'저가시각':>9} {'고가시각':>9}  이름")
print("-" * 100)
for x in sorted(rows, key=lambda z: -z["reb_now"]):
    lt = x["lt"] or "-"; ht = x["ht"] or "-"
    print(f"{x['code']:>8} {x['ret']:>7.2f}% {x['low_from_open']:>8.2f}% "
          f"{x['low_from_prev']:>8.2f}% {x['reb_now']:>8.2f}% {x['reb_hi']:>8.2f}% "
          f"{lt:>9} {ht:>9}  {x['name']}")

if rows:
    rn = sorted(x["reb_now"] for x in rows)
    rh = sorted(x["reb_hi"] for x in rows)
    print(f"\n저가→현재  중앙 {rn[len(rn)//2]:.2f}% · 평균 {sum(rn)/len(rn):.2f}% "
          f"· 최소 {rn[0]:.2f}% · 최대 {rn[-1]:.2f}%")
    print(f"저가→고가  중앙 {rh[len(rh)//2]:.2f}% · 평균 {sum(rh)/len(rh):.2f}% "
          f"· 최소 {rh[0]:.2f}% · 최대 {rh[-1]:.2f}%")
    for th in (1.5, 2.0, 3.0, 4.0, 5.0):
        print(f"  저가→현재 {th}% 이상: {sum(1 for v in rn if v >= th)}/{len(rn)}  |  "
              f"저가→고가 {th}% 이상: {sum(1 for v in rh if v >= th)}/{len(rh)}")
    known = [x for x in rows if x["lt"] and x["ht"]]
    if known:
        after = sum(1 for x in known if x["ht"] > x["lt"])
        print(f"\n※ 저가/고가 시각을 아는 {len(known)}종목 중 고가가 저가보다 '나중'인 것: {after}건")
        print("   (나중이어야 '저점 이후 반등'이다. 앞이면 갭상승 후 하락이라 반등이 아니다.)")

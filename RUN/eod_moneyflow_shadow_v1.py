# -*- coding: utf-8 -*-
"""
[자금지속x가속 SHADOW 2026-06-11] 친구님 수석합격 가설의 그림자 측정기 (매매 무연결).
매일 16:30(일봉 수집 후) 실행:
  1) 어제까지 기록된 행에 오늘 시가로 갭 채점(backfill)
  2) 오늘의 '옆문 합격자' 기록: KOSDAQ & 강한흐름(ret>=2%, cpos>=0.7) & 대금>=200억
     & 자금지속(대금>=20일평균x2, 오늘 포함 2일+) & 가속(오늘ret - 직전3일평균 >= 10%p)
근거: 1년 4,942건 백테 — 이 조합 +2.95%/59% (gap_combo_v1.py). 현행 score60 문턱은
  강한종가 우주서 변별력 0. 표본 쌓이면 signal_v2 VALUE_FLOOR에 OR-옆문 실전화 판정.
"""
import csv, io, os
from collections import defaultdict

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
OUT = r"C:\stock_bot\data\BACKTEST\moneyflow_shadow.csv"

series = defaultdict(list)
with io.open(EOD, encoding="utf-8-sig") as fp:
    rd = csv.DictReader(fp)
    for r in rd:
        if r.get("market") != "KOSDAQ":
            continue
        try:
            o = float(r["open"] or 0); c = float(r["close"] or 0); v = float(r["value"] or 0)
            ret = float(r["daily_return"]) if r.get("daily_return") not in ("", None) else None
            cpos = float(r["close_position"]) if r.get("close_position") not in ("", None) else None
        except (TypeError, ValueError):
            continue
        if o <= 0 or c <= 0:
            continue
        series[r["code"]].append((r["date"], o, c, v, ret, cpos, r.get("name", "")))

latest = max(d for rows in series.values() for d, *_ in rows)

# ── 1) backfill: 기존 행의 다음날 갭 채점 ──
opens = {}
for code, rows in series.items():
    for d, o, c, v, ret, cpos, name in rows:
        opens[(code, d)] = o

rows_existing = []
if os.path.exists(OUT):
    with io.open(OUT, encoding="utf-8-sig") as fp:
        rows_existing = list(csv.DictReader(fp))
n_filled = 0
for r in rows_existing:
    if r.get("gap_pct"):
        continue
    # r['date'] 다음 거래일의 시가 찾기
    code = r["code"]
    dates = sorted(d for d, *_ in series.get(code, []))
    nxt = [d for d in dates if d > r["date"]]
    if not nxt:
        continue
    o_next = opens.get((code, nxt[0]))
    try:
        close_then = float(r["close"])
    except (TypeError, ValueError):
        continue
    if o_next and close_then > 0:
        r["next_open"] = o_next
        r["gap_pct"] = round((o_next / close_then - 1) * 100, 3)
        n_filled += 1

# ── 2) 오늘의 옆문 합격자 ──
new_rows = []
for code, rows in series.items():
    rows.sort(key=lambda x: x[0])
    if len(rows) < 25 or rows[-1][0] != latest:
        continue
    d, o, c, v, ret, cpos, name = rows[-1]
    if ret is None or cpos is None:
        continue
    if not (ret >= 0.02 and cpos >= 0.7 and v >= 20000):
        continue
    if ret >= 0.28:   # [LOCK-GUARD 2026-06-11] 상한가 부근 = 매수 체결 불가 — 백테 +2.95%의
        continue      #   대부분이 이 함정이었음(락가드 후 +0.66%). 기록도 매수가능 종목만.
    vals = [x[3] for x in rows]
    rets = [x[4] for x in rows]
    i = len(rows) - 1
    # 자금지속
    vp = 0; j = i
    while j >= 0:
        a20 = sum(vals[max(0, j-20):j]) / max(min(j, 20), 1)
        if a20 > 0 and vals[j] >= 2 * a20:
            vp += 1; j -= 1
        else:
            break
    # 가속
    prev3 = [x for x in rets[i-3:i] if x is not None]
    accel = ret - (sum(prev3) / len(prev3) if prev3 else 0.0)
    if vp >= 2 and accel >= 0.10:
        new_rows.append({
            "date": d, "code": code, "name": name, "close": c,
            "ret_pct": round(ret * 100, 2), "value_eok": round(v / 100),
            "vp_days": vp, "accel_pp": round(accel * 100, 1),
            "next_open": "", "gap_pct": "",
        })

# 중복 방지(같은 date+code 재기록 금지)
seen = {(r["date"], r["code"]) for r in rows_existing}
new_rows = [r for r in new_rows if (r["date"], r["code"]) not in seen]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
FIELDS = ["date", "code", "name", "close", "ret_pct", "value_eok", "vp_days", "accel_pp", "next_open", "gap_pct"]
with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows_existing:
        w.writerow(r)
    for r in new_rows:
        w.writerow(r)

print(f"[MONEYFLOW SHADOW] 기준일={latest} 채점완료 {n_filled}건 / 신규 옆문합격자 {len(new_rows)}건")
for r in new_rows:
    print(f"  {r['code']} {r['name']} 종가={r['close']} 등락={r['ret_pct']}% "
          f"대금={r['value_eok']}억 자금지속={r['vp_days']}일 가속=+{r['accel_pp']}%p")
# 누적 성적
done = [float(r["gap_pct"]) for r in rows_existing if r.get("gap_pct") not in ("", None)]
if done:
    import statistics as st
    print(f"[누적채점] n={len(done)} 평균갭 {st.mean(done):+.3f}% 갭>0 {sum(1 for g in done if g>0)/len(done)*100:.0f}%")

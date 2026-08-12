# -*- coding: utf-8 -*-
"""오늘(8/7) S02 재생 27건에 '봉 전환 판정' 4개를 대본다. 읽기 전용.

판정 4개 (전부 부등호, 문턱 0개)
  ① 직전 1분봉이 음봉이었나        prev_close < prev_open
  ② 지금 봉이 양봉인가             현재가 > 이번봉 시가
  ③ 이번 봉에서 매수가 이겼나      봉내 매수대금 > 봉내 매도대금
  ④ 매도가 마르고 있나             이번봉 초당매도 < 직전음봉 초당매도

채점은 매도 규칙을 안 섞는다: 신호 후 +1.0% 를 먼저 닿나 -2.0% 를 먼저 닿나.
"""
import csv
import json
import pathlib

SP = pathlib.Path(r"C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK"
                  r"\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad")
CACHE = pathlib.Path(r"C:\stock_bot\data\replay_cache")
UP, DOWN = 1.0, -2.0

_t = {}


def ticks(code):
    """[(hh:mm:ss, price, buy_cum, sell_cum)] 09:00 이후만."""
    if code not in _t:
        rows = []
        with (CACHE / f"20260807_{code}.csv").open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                hhmmss = r["ts"][11:19]
                if hhmmss < "09:00:00":
                    continue
                try:
                    px = float(r["current_price"])
                    b = float(r["buy_money_cum"] or 0)
                    s = float(r["sell_money_cum"] or 0)
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    rows.append((hhmmss, px, b, s))
        _t[code] = rows
    return _t[code]


def bar_rows(seq, hhmm):
    return [x for x in seq if x[0][:5] == hhmm]


def prev_min(hhmm):
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    m -= 1
    if m < 0:
        h, m = h - 1, 59
    return f"{h:02d}:{m:02d}"


def judge(code, t):
    """봉 전환 판정. (통과여부, 각 항목, 참고값)"""
    seq = ticks(code)
    cur_m = t[:5]
    prv_m = prev_min(cur_m)
    prev = bar_rows(seq, prv_m)
    cur = [x for x in bar_rows(seq, cur_m) if x[0] <= t]
    if len(prev) < 2 or len(cur) < 2:
        return None
    p_open, p_close = prev[0][1], prev[-1][1]
    c_open = cur[0][1]
    now = cur[-1][1]
    g1 = p_close < p_open
    g2 = now > c_open
    buy_in = cur[-1][2] - cur[0][2]
    sell_in = cur[-1][3] - cur[0][3]
    g3 = buy_in > sell_in
    p_sell_rate = (prev[-1][3] - prev[0][3]) / max(1.0, len(prev))
    c_span = max(1.0, len(cur))
    c_sell_rate = sell_in / c_span
    g4 = c_sell_rate < p_sell_rate
    return dict(g1=g1, g2=g2, g3=g3, g4=g4, all=(g1 and g2 and g3 and g4),
                prev_body=(p_close / p_open - 1) * 100 if p_open else 0.0,
                cur_body=(now / c_open - 1) * 100 if c_open else 0.0,
                buy_in=buy_in, sell_in=sell_in,
                p_sell=p_sell_rate, c_sell=c_sell_rate, elapsed=int(c_span))


def first_touch(code, t, entry):
    """신호 후 +1.0% 와 -2.0% 중 무엇을 먼저 닿나. (결과, MAE%, MFE%)"""
    seq = [x for x in ticks(code) if x[0] >= t]
    lo = hi = entry
    for _, px, _b, _s in seq:
        lo, hi = min(lo, px), max(hi, px)
        r = (px / entry - 1) * 100
        if r <= DOWN:
            return "손절먼저", (lo / entry - 1) * 100, (hi / entry - 1) * 100
        if r >= UP:
            return "이익먼저", (lo / entry - 1) * 100, (hi / entry - 1) * 100
    return "둘다못닿음", (lo / entry - 1) * 100, (hi / entry - 1) * 100


fires = json.loads((SP / "fires_gateoff.json").read_text(encoding="utf-8"))
rows = []
for f in fires:
    code = str(f["_code"]).zfill(6)
    t = f["_t"]
    px = float(f.get("price") or 0)
    seq = ticks(code)
    day_open = seq[0][1] if seq else 0.0
    low = float(f.get("anchor_low") or 0)
    day_low_sofar = min((x[1] for x in seq if x[0] <= t), default=px)
    j = judge(code, t)
    res, mae, mfe = first_touch(code, t, px)
    rows.append(dict(
        code=code, t=t, px=px, low=low,
        drop=float(f.get("dip_drop_pct") or 0),
        need=float(f.get("required_drop_pct") or 0),
        open_drop=(day_low_sofar / day_open - 1) * 100 if day_open else None,
        reb=(px / low - 1) * 100 if low else None,
        j=j, res=res, mae=mae, mfe=mfe))
rows.sort(key=lambda z: z["t"])

print("=" * 118)
print("① 오늘 27건의 저점 깊이")
print("=" * 118)
print(f"{'시각':>9} {'종목':>7} {'엔진낙폭':>9} {'요구':>6} {'당일시가대비저점':>16}"
      f" {'저점대비매수':>12} {'결과':>10} {'MAE':>8} {'MFE':>8}")
print("-" * 118)
for r in rows:
    od = f"{r['open_drop']:+.2f}%" if r["open_drop"] is not None else "-"
    rb = f"{r['reb']:+.2f}%" if r["reb"] is not None else "-"
    print(f"{r['t']:>9} {r['code']:>7} {r['drop']:>8.2f}% {r['need']:>5.1f}%"
          f" {od:>16} {rb:>12} {r['res']:>10} {r['mae']:>+7.2f}% {r['mfe']:>+7.2f}%")

d = sorted(r["drop"] for r in rows)
o = sorted(r["open_drop"] for r in rows if r["open_drop"] is not None)
b = sorted(r["reb"] for r in rows if r["reb"] is not None)
print(f"\n  엔진낙폭      최소 {d[0]:.2f}% · 중앙 {d[len(d)//2]:.2f}% · 최대 {d[-1]:.2f}%")
print(f"  시가대비저점  최소 {o[0]:+.2f}% · 중앙 {o[len(o)//2]:+.2f}% · 최대 {o[-1]:+.2f}%")
print(f"  저점대비매수  최소 {b[0]:+.2f}% · 중앙 {b[len(b)//2]:+.2f}% · 최대 {b[-1]:+.2f}%")
n_up = sum(1 for r in rows if r["res"] == "이익먼저")
n_dn = sum(1 for r in rows if r["res"] == "손절먼저")
print(f"\n  현행 27건:  이익(+1%)먼저 {n_up}건 · 손절(-2%)먼저 {n_dn}건"
      f" · 둘다못닿음 {len(rows)-n_up-n_dn}건")

print("\n" + "=" * 118)
print("② 봉 전환 판정 4개를 대보면")
print("=" * 118)
print(f"{'시각':>9} {'종목':>7} {'직전봉몸통':>11} {'이번봉몸통':>11} {'봉내매수(만)':>13}"
      f" {'봉내매도(만)':>13} {'경과':>5} {'①':>3}{'②':>3}{'③':>3}{'④':>3} {'통과':>5} {'결과':>10}")
print("-" * 118)
for r in rows:
    j = r["j"]
    if j is None:
        print(f"{r['t']:>9} {r['code']:>7}  판정불가(봉 자료 부족)")
        continue
    ox = lambda v: "O" if v else "X"          # noqa: E731
    print(f"{r['t']:>9} {r['code']:>7} {j['prev_body']:>+10.2f}% {j['cur_body']:>+10.2f}%"
          f" {j['buy_in']/10000:>13,.0f} {j['sell_in']/10000:>13,.0f} {j['elapsed']:>4}초"
          f" {ox(j['g1']):>3}{ox(j['g2']):>3}{ox(j['g3']):>3}{ox(j['g4']):>3}"
          f" {('통과' if j['all'] else '탈락'):>5} {r['res']:>10}")


def summ(sel, label):
    if not sel:
        return f"  {label:<28} N=0"
    up = sum(1 for x in sel if x["res"] == "이익먼저")
    dn = sum(1 for x in sel if x["res"] == "손절먼저")
    m = sorted(x["mae"] for x in sel)
    return (f"  {label:<28} N={len(sel):>2} · 이익먼저 {up:>2} · 손절먼저 {dn:>2}"
            f" · 미도달 {len(sel)-up-dn:>2} · MAE중앙 {m[len(m)//2]:+.2f}%")


ok = [r for r in rows if r["j"] and r["j"]["all"]]
ng = [r for r in rows if r["j"] and not r["j"]["all"]]
print("\n" + "=" * 118)
print("③ 판정이 좋은 것을 거르나 나쁜 것을 거르나")
print("=" * 118)
print(summ(rows, "전체(현행)"))
print(summ(ok, "4개 전부 통과 = 산다"))
print(summ(ng, "하나라도 탈락 = 안 산다"))
print()
for k, lab in (("g1", "① 직전봉 음봉"), ("g2", "② 이번봉 양봉"),
               ("g3", "③ 봉내 매수우위"), ("g4", "④ 매도 감속")):
    sel = [r for r in rows if r["j"] and r["j"][k]]
    print(summ(sel, f"{lab} 만 적용"))

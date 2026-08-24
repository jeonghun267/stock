# -*- coding: utf-8 -*-
"""VPIN 5일치. 진입 순간의 주문흐름 독성이 성적을 가르는가. 읽기 전용.

VPIN (Easley/Lopez de Prado/O'Hara): 시간이 아니라 '거래량 시계'로 구간을 나눠
  |매수 - 매도| / 총량 의 이동평균. 높으면 정보거래자가 한쪽으로 몰림 = 계속 밀린다.

자료 한계(정직 고지):
  그림자는 분당 1행이고 buy_ratio_pct 가 소수1자리 반올림이라
  누적 매수대금 = V * br/100 의 차분에는 오차가 있다. 누적 V 가 클수록 오차가 커진다.
  -> 오차 추정치를 함께 출력하고, 오차보다 큰 신호만 유효로 본다.
"""
import sys, csv, pathlib, random, statistics as st
from collections import defaultdict
sys.path.insert(0, r'C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad')
from eng4 import run2, D4

DAYS = D4  # 8/3~8/6


def load_flow(day):
    """종목 -> [(분, 누적대금억, 누적매수비율%)] 시간순"""
    p = pathlib.Path(rf"C:\stock_bot\data\high_range_shadow_{day}.csv")
    out = defaultdict(list)
    if not p.exists():
        return out
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                t = r["ts"][11:16]
                v = float(r["live_value_eok"] or 0)
                b = float(r["buy_ratio_pct"] or 0)
            except Exception:
                continue
            out[str(r["code"]).zfill(6)].append((t, v, b))
    for c in out:
        out[c].sort(key=lambda z: z[0])
    return out


def vpin_at(seq, upto_hhmm, nbuckets=10):
    """upto 시각까지의 자료로 VPIN 계산. (vpin, 오차추정, 표본버킷수)"""
    rows = [x for x in seq if x[0] <= upto_hhmm]
    if len(rows) < 4:
        return None, None, 0
    # 분당 증분
    inc = []
    for i in range(1, len(rows)):
        t0, v0, b0 = rows[i - 1]
        t1, v1, b1 = rows[i]
        dv = v1 - v0
        if dv <= 0:
            continue
        buy1, buy0 = v1 * b1 / 100.0, v0 * b0 / 100.0
        db = buy1 - buy0
        ds = dv - db
        if db < 0 or ds < 0:          # 반올림 오차로 음수가 나오면 버린다
            continue
        # 오차: br 이 +-0.05%p 이면 누적매수 오차 +-v*0.0005, 차분은 두 배
        err = (v1 + v0) * 0.0005
        inc.append((dv, db, ds, err))
    if len(inc) < 4:
        return None, None, len(inc)
    # 거래량 시계: 전체 증분대금을 nbuckets 개로 균등 분할
    total = sum(x[0] for x in inc)
    if total <= 0:
        return None, None, len(inc)
    target = total / nbuckets
    buckets, cv, cb, cs, ce = [], 0.0, 0.0, 0.0, 0.0
    for dv, db, ds, err in inc:
        cv += dv; cb += db; cs += ds; ce += err
        if cv >= target:
            buckets.append((abs(cb - cs) / cv, ce / cv))
            cv = cb = cs = ce = 0.0
    if not buckets:
        return None, None, len(inc)
    v = sum(x[0] for x in buckets) / len(buckets)
    e = sum(x[1] for x in buckets) / len(buckets)
    return v, e, len(buckets)


print("===== VPIN 5일치 (진입 순간의 주문흐름 독성) =====")
rows = run2(days=DAYS)
print(f"진입 N={len(rows)} (8/3~8/6 전수)\n")

flows = {d: load_flow(d) for d in DAYS}
ok = 0
for r in rows:
    seq = flows.get(r['day'], {}).get(str(r['code']).zfill(6))
    if not seq:
        r['vpin'] = None
        continue
    hhmm = str(r['t'])[:5] if len(str(r['t'])) >= 5 else None
    v, e, n = vpin_at(seq, hhmm) if hhmm else (None, None, 0)
    r['vpin'], r['vperr'], r['vpn'] = v, e, n
    if v is not None:
        ok += 1

print(f"VPIN 계산 성공 {ok}/{len(rows)}건")
vs = [r['vpin'] for r in rows if r.get('vpin') is not None]
es = [r['vperr'] for r in rows if r.get('vperr') is not None]
if vs:
    q = sorted(vs)
    print(f"VPIN 분포: 최소 {q[0]:.3f} · 중앙 {q[len(q)//2]:.3f} · 최대 {q[-1]:.3f}")
    print(f"오차 추정 중앙: {sorted(es)[len(es)//2]:.3f}  "
          f"(VPIN 중앙의 {sorted(es)[len(es)//2]/q[len(q)//2]*100:.0f}%)")
    if sorted(es)[len(es)//2] > q[len(q)//2] * 0.3:
        print("  !! 오차가 신호의 30% 를 넘는다 - 아래 결과는 참고용")


def summ(sel, label):
    if not sel:
        return f"  {label:<24} N=0"
    out = f"  {label:<24} N={len(sel):>3}"
    for p in "ACE":
        v = sorted(r['ret_' + p] for r in sel)
        out += f" · {p} 중앙 {v[len(v)//2]:+6.2f}%"
    mae = sorted(r['mae'] for r in sel)
    win = sum(1 for r in sel if r['ret_C'] > 0) / len(sel) * 100
    out += f" · C승률 {win:4.1f}% · MAE중앙 {mae[len(mae)//2]:+.2f}%"
    return out


if vs:
    q = sorted(vs)
    lo_th, hi_th = q[len(q) // 3], q[len(q) * 2 // 3]
    print(f"\n===== VPIN 3분위 (문턱 {lo_th:.3f} / {hi_th:.3f}) =====")
    print(summ([r for r in rows if r.get('vpin') is not None and r['vpin'] <= lo_th],
               "낮음(독성 적음)"))
    print(summ([r for r in rows if r.get('vpin') is not None
                and lo_th < r['vpin'] <= hi_th], "중간"))
    print(summ([r for r in rows if r.get('vpin') is not None and r['vpin'] > hi_th],
               "높음(독성 큼)"))

    print("\n===== 순열검정 (낮음 vs 높음) =====")
    random.seed(20260807)
    lo = [r['ret_C'] for r in rows if r.get('vpin') is not None and r['vpin'] <= lo_th]
    hi = [r['ret_C'] for r in rows if r.get('vpin') is not None and r['vpin'] > hi_th]
    if len(lo) >= 3 and len(hi) >= 3:
        obs = sum(lo) / len(lo) - sum(hi) / len(hi)
        pool = lo + hi; hit = 0; T = 20000
        for _ in range(T):
            random.shuffle(pool)
            a, b = pool[:len(lo)], pool[len(lo):]
            if abs(sum(a) / len(a) - sum(b) / len(b)) >= abs(obs):
                hit += 1
        print(f"  낮음 {sum(lo)/len(lo):+.2f}%(N={len(lo)}) vs "
              f"높음 {sum(hi)/len(hi):+.2f}%(N={len(hi)}) · 차 {obs:+.2f}%p · "
              f"우연확률 {hit/T*100:.1f}%")
    else:
        print(f"  표본부족 (낮음 {len(lo)} · 높음 {len(hi)})")

    print("\n===== 날짜별 (규칙보다 날짜가 큰지) =====")
    for d in DAYS:
        v = sorted(r['ret_C'] for r in rows if r['day'] == d)
        if v:
            print(f"  {d}  N={len(v):>3} 중앙 {v[len(v)//2]:+6.2f}%")

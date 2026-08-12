# -*- coding: utf-8 -*-
"""저점->진입 경과시간이 성적과 관계있나. 4일 전수. 읽기 전용.
계측 구간 못박기: '최종 저점이 찍힌 봉 -> 진입 봉' (분).
  = 오늘 실측한 S02 dip_flow_obs_sec(초)와 같은 물건. 분당 자료라 해상도 1분.
"""
import sys, random, statistics as st
sys.path.insert(0, r'C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK\9ab9cd3d-6886-44fe-8412-bd142f982e09\scratchpad')
from eng4 import run2, D4

rows = run2(days=D4)
for r in rows:
    r['age'] = r['mins_ent'] - r['mins_low']      # 최종 저점 -> 진입 (분)

print("===== 저점->진입 경과 (4일 전수, 8/3~8/6) =====")
print(f"진입 N={len(rows)}")
ages = sorted(r['age'] for r in rows)
if ages:
    print(f"경과분: 최소 {ages[0]} · 중앙 {ages[len(ages)//2]} · "
          f"평균 {sum(ages)/len(ages):.1f} · 최대 {ages[-1]}")
    for th in (1, 2, 3, 5, 7, 10):
        n = sum(1 for a in ages if a <= th)
        print(f"   {th:>2}분 이하 {n:>3}건 ({n/len(ages)*100:>3.0f}%)")

print("\n===== 오늘(8/7) S02 실측과 대조 =====")
print("  오늘 28건: 최소 1.7분 · 중앙 7.3분 · 최대 18.8분 · 1분 이하 0건")

def desc(v, label):
    if not v:
        return f"  {label:<22} 자료없음"
    q = sorted(v); n = len(q)
    return (f"  {label:<22} N={n:>3} 중앙 {q[n//2]:+6.2f}% · 평균 {sum(q)/n:+6.2f}% · "
            f"승률 {sum(1 for x in q if x>0)/n*100:4.1f}%")

print("\n===== 경과시간 구간별 성적 (비용 미차감, 정책별) =====")
BINS = [(0, 1, "0~1분 (즉시 반등)"), (2, 3, "2~3분"), (4, 7, "4~7분"),
        (8, 999, "8분 이상 (늘어짐)")]
for pol in "ABCE":
    print(f"\n--- 정책 {pol}")
    for lo, hi, lab in BINS:
        v = [r['ret_'+pol] for r in rows if lo <= r['age'] <= hi]
        print(desc(v, lab))

print("\n===== MAE(진입 후 최대 역행) 구간별 =====")
for lo, hi, lab in BINS:
    v = sorted(r['mae'] for r in rows if lo <= r['age'] <= hi)
    if v:
        print(f"  {lab:<22} N={len(v):>3} 중앙 {v[len(v)//2]:+6.2f}% · "
              f"-2%이하 {sum(1 for x in v if x<=-2)/len(v)*100:>4.1f}%")

print("\n===== 진입가가 저점에서 얼마나 위인가 =====")
for lo, hi, lab in BINS:
    v = sorted(r['ent_low'] for r in rows if lo <= r['age'] <= hi)
    if v:
        print(f"  {lab:<22} N={len(v):>3} 중앙 +{v[len(v)//2]:.2f}%")

# 순열검정: 빠른(<=3분) vs 늦은(>=8분)
print("\n===== 순열검정 (빠름 0~3분 vs 늦음 8분+) =====")
random.seed(20260807)
for pol in "ABCE":
    fast = [r['ret_'+pol] for r in rows if r['age'] <= 3]
    slow = [r['ret_'+pol] for r in rows if r['age'] >= 8]
    if len(fast) < 3 or len(slow) < 3:
        print(f"  정책{pol}  표본부족 (빠름 {len(fast)} · 늦음 {len(slow)})")
        continue
    obs = sum(fast)/len(fast) - sum(slow)/len(slow)
    pool = fast + slow; hit = 0; T = 20000
    for _ in range(T):
        random.shuffle(pool)
        a, b = pool[:len(fast)], pool[len(fast):]
        if abs(sum(a)/len(a) - sum(b)/len(b)) >= abs(obs):
            hit += 1
    print(f"  정책{pol}  빠름 {sum(fast)/len(fast):+6.2f}%(N={len(fast)}) vs "
          f"늦음 {sum(slow)/len(slow):+6.2f}%(N={len(slow)}) · "
          f"차 {obs:+6.2f}%p · 우연확률 {hit/T*100:5.1f}%")

print("\n===== 날짜별 분해 (규칙보다 날짜가 큰지 확인) =====")
for day in D4:
    v = sorted(r['ret_C'] for r in rows if r['day'] == day)
    if v:
        print(f"  {day}  N={len(v):>3} 정책C 중앙 {v[len(v)//2]:+6.2f}% · "
              f"평균 {sum(v)/len(v):+6.2f}%")

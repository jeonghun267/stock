# -*- coding: utf-8 -*-
"""[2026-07-05 친구님 "대안들 그림자 저장해놓고 자동 보고"] 대안 그림자 3거래일 집계 보고서.
대상: ①ALT_NEWHIGH(체결국면 당일신고)·ALT_90(눈금90) 코호트(missed_by_che) ②돌파 mode_C 오후베이스
③종가매수 BRK20 ④갑툭튀(base_surge) ⑤GC560 그림자 로그.
출력: data\보고서\대안검증_3일보고_<오늘>.txt (+stdout). 주문 0·읽기 전용.
사용: python alt_cohort_report.py [시작일 YYYYMMDD] [종료일 YYYYMMDD]  (기본 20260706~20260708)"""
import sys, csv, glob, os
from pathlib import Path
from datetime import datetime

D0 = sys.argv[1] if len(sys.argv) > 1 else "20260706"
D1 = sys.argv[2] if len(sys.argv) > 2 else "20260708"
ROOT = Path(r"C:\stock_bot\data")
OUT = ROOT / "보고서" / f"대안검증_3일보고_{datetime.now():%Y%m%d}.txt"
L = []

def w(s=""):
    L.append(s); print(s, flush=True)

def fnum(x, d=0.0):
    try: return float(str(x).replace(",", ""))
    except Exception: return d

w(f"===== 대안 그림자 검증 보고 ({D0}~{D1}, 작성 {datetime.now():%Y-%m-%d %H:%M}) =====")

# ① ALT 코호트 + 기존 미진입 코호트
rows = []
for f in sorted(glob.glob(str(ROOT / "shadow" / "missed_by_che" / "missed_*.csv"))):
    d = os.path.basename(f)[7:15]
    if not (D0 <= d <= D1): continue
    try:
        with open(f, encoding="utf-8-sig", newline="") as fp:
            rows += [r for r in csv.DictReader(fp)]
    except Exception as e:
        w(f"  (읽기실패 {f}: {e})")
w(f"\n[1] 미진입/대안 코호트 (기록 {len(rows)}건)")
if rows:
    by = {}
    for r in rows: by.setdefault(r.get("engine", "?"), []).append(r)
    w(f"  {'코호트':<12} {'건수':>4} {'승률':>6} {'평균장마감':>8} {'평균최대상승':>10}")
    이름 = {"ALT_NEWHIGH": "①당일신고", "ALT_90": "②눈금90", "ALT_VWAP": "③VWAP재탈환", "ALT_STAIR": "④계단반등", "UNI": "통합대장탈락", "REV": "바닥탈락",
           "PB": "눌림탈락", "GC560": "GC560탈락", "V1IN": "V1(게이트안)", "V1LOW": "V1저점전환", "V1HOT": "V1과열"}
    for e in sorted(by, key=lambda x: (not x.startswith("ALT"), x)):
        a = by[e]; rets = [fnum(r.get("eod_ret")) for r in a]; mfes = [fnum(r.get("mfe")) for r in a]
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100
        w(f"  {이름.get(e, e):<12} {len(a):>4} {wr:>5.0f}% {sum(rets)/len(rets):>+7.2f}% {sum(mfes)/len(mfes):>+9.2f}%")
    for e in ("ALT_NEWHIGH", "ALT_90", "ALT_VWAP", "ALT_STAIR"):
        for r in by.get(e, []):
            qx = f" | 초기매도 {r.get('qx_hm')} {r.get('qx_ret')}%" if r.get("qx_ret") else ""
            w(f"    · {이름[e]} {r.get('date')} {r.get('code')} {r.get('hm')} @{r.get('px')} 체결국면{r.get('che')} → 장마감 {r.get('eod_ret')}% (최대 {r.get('mfe')}%){qx}")
    stair = by.get("ALT_STAIR", [])
    if stair:
        qs = [fnum(r.get("qx_ret")) for r in stair if r.get("qx_ret")]
        es = [fnum(r.get("eod_ret")) for r in stair]
        if qs:
            w(f"  ▶ ④계단반등 매도 비교: 보유(장마감) 평균 {sum(es)/len(es):+.2f}% vs 초기매도 평균 {sum(qs)/len(qs):+.2f}% — 초기매도는 자리를 일찍 비워 다른 종목 재배치 가능(회전 가치 별도)")
        qts = [fnum(r.get("qt_ret")) for r in stair if r.get("qt_ret")]
        if qts:
            w(f"  ▶ 콤보매도(고점-2%트레일 OR VWAP반납+약화) 평균 {sum(qts)/len(qts):+.2f}%")

    # ▶ 시간대별 수익 히트맵 (친구님 "시간 조정 어떻게" — 68캡 편향 사라진 후 진짜 기회 분포 측정)
    w(f"\n  ▶ 시간대별 진입 히트맵 (진입창 조정 근거 — 어느 시각에 수익 자리가 몰리나)")
    buckets = {}
    for r in rows:
        hm = str(r.get("hm", "")).zfill(4)
        if len(hm) < 4 or not hm[:2].isdigit(): continue
        hh = hm[:2]
        buckets.setdefault(hh, []).append(fnum(r.get("eod_ret")))
    for hh in sorted(buckets):
        a = buckets[hh]; win = sum(1 for x in a if x > 0)
        bar = "█" * min(30, len(a))
        w(f"    {hh}시  {len(a):>3}건 승{win/len(a)*100:>3.0f}% 평균{sum(a)/len(a):>+6.2f}%  {bar}")
    w(f"    → 14시 이후에도 수익 자리가 많으면 진입창 연장 검토(현행 바닥14:00·눌림13:30·통합11:00). 오전에만 몰리면 현행 유지.")
else:
    w("  표본 없음 (추적기 15:45 태스크 실행 여부·che_ts 확인 필요)")

# ② 돌파 mode_C 오후베이스 그림자
w(f"\n[2] 돌파사냥꾼 오후베이스(mode_C) 그림자")
n = 0
for f in sorted(glob.glob(str(ROOT / "**" / "돌파사냥_C그림자_*.csv"), recursive=True)):
    d = "".join(ch for ch in os.path.basename(f) if ch.isdigit())[:8]
    if not (D0 <= d <= D1): continue
    try:
        with open(f, encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                n += 1; w(f"    · {os.path.basename(f)} {r}")
    except Exception: pass
w(f"  포착 {n}건" if n else "  포착 0건")

# ③ 종가매수 BRK20 그림자
w(f"\n[3] 종가매수 20일신고가(BRK20) 그림자")
n = 0
p = ROOT / "shadow" / "eod_gap_brk20_shadow.csv"
if p.exists():
    try:
        with open(p, encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                d = str(r.get("date", "")).replace("-", "")[:8]
                if D0 <= d <= D1:
                    n += 1; w(f"    · {r}")
    except Exception: pass
w(f"  포착 {n}건" if n else "  포착 0건")

# ④ 갑툭튀(base_surge)
w(f"\n[4] 갑툭튀(베이스+3%돌파) 그림자")
n = 0
for f in sorted(glob.glob(str(ROOT / "shadow" / "base_surge_shadow_*.csv"))):
    d = "".join(ch for ch in os.path.basename(f) if ch.isdigit())[:8]
    if not (D0 <= d <= D1): continue
    try:
        with open(f, encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                n += 1; w(f"    · {d} {r.get('code')} {r.get('name')} 등급{r.get('tier')} 당일{r.get('d0ret')}% 거래량{r.get('vmult')}배")
    except Exception: pass
w(f"  포착 {n}건 (0건=약장 정상·익일 눌림목 후보 모집단)" if n == 0 else f"  포착 {n}건")

# ⑤ GC560 그림자 로그 (잠금 중 관찰)
w(f"\n[5] GC560 그림자 신호 (잠금 중 — 로그 발췌)")
n = 0
p = ROOT / "LOG" / "golden_cross_560.log"
if p.exists():
    try:
        for ln in open(p, encoding="utf-8", errors="replace"):
            d = ln[1:11].replace("-", "")
            if D0 <= d <= D1 and ("BUY" in ln or "매수" in ln or "진입" in ln):
                n += 1
                if n <= 30: w("    · " + ln.strip())
    except Exception: pass
w(f"  신호 {n}건" if n else "  신호 0건")

w("\n※ 판정 기준: 대안 코호트(①/②)의 승률·평균이 '통합대장탈락(현행100 탈락 전체)'보다 뚜렷이 좋고 표본 10건+ 이면 채택 검토. 부족하면 며칠 더 수집.")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(L), encoding="utf-8")
print(f"\n보고서 저장: {OUT}", flush=True)

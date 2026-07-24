# -*- coding: utf-8 -*-
# [2026-06-25 친구님 패턴] 세력 매집형 돌파 셋업 일일 스크리너 (READ-ONLY·주문0)
#   한달 베이스 횡보 → 거래량 2.5배+ 터짐(세력진입) → 3~5일 음봉 매물소화(베이스 안깨짐) → 양봉 재개
#   진입선 = 양봉(전일) 고가 돌파. 백테(1년): 전일고가돌파 진입 5일 +1.91%/승52%·MFE+12.6%·폭발≥15% 27%·체결률61%.
#   ★검증: 종가진입(+1.15%)보다 돌파진입(+1.91%) 우위·가짜 39% 자동회피. 청산은 NEW_PB CHE_EXIT/돌파실행기가 담당.
#   출력 data/base_thrust_setup.txt. 매일저녁 자동(EOD일봉 수집후). 자동매수 아님=관찰/그림자.
import csv, os, sys
from collections import defaultdict
from datetime import datetime

EOD   = r"C:\stock_bot\data\eod_daily_bars.csv"
THEME = r"C:\stock_bot\data\theme\code_theme_strength.csv"
OUT   = r"C:\stock_bot\data\base_thrust_setup.txt"

BASE_RANGE = float(os.environ.get("BT_BASE_RANGE", "0.35"))   # 한달 베이스 최대 범위
THRUST_X   = float(os.environ.get("BT_THRUST_X",   "2.5"))    # 거래량 터짐 배수
VAL_FLOOR  = float(os.environ.get("BT_VAL_FLOOR",  "1000"))   # 베이스 평균 거래대금(백만원=10억)
GREEN_AGE  = int(os.environ.get("BT_GREEN_AGE",    "2"))      # 양봉재개가 최근 N봉 이내

def _load_theme():
    m = {}
    try:
        rows = list(csv.DictReader(open(THEME, encoding="utf-8-sig", errors="replace")))
        if rows:
            latest = max(r.get("date", "").strip() for r in rows if r.get("date", "").strip())
            for r in rows:
                if r.get("date", "").strip() != latest:
                    continue
                m[str(r.get("code", "")).zfill(6)] = (
                    (r.get("best_theme", "") or "")[:14],
                    str(r.get("is_leader", "0")).strip() == "1")
    except Exception:
        pass
    return m

# ETF/ETN 제외: 브랜드 첫토큰 + 키워드 (market=KOSDAQ로 대부분 걸러지나 안전망)
ETF_BRANDS = {"KODEX","TIGER","KBSTAR","ARIRANG","KOSEF","KINDEX","HANARO","SOL","PLUS","ACE",
              "RISE","KIWOOM","TIMEFOLIO","FOCUS","TREX","KCGI","WON","BNK","TRUE","QV","마이다스",
              "히어로즈","에셋플러스","파워","마이티","KODEX","HK","KOACT","UNICORN"}
ETF_KW = ["ETN","ETF","레버리지","인버스","선물","국고채","채권","합성","리츠","2X","스팩","SPAC"]

def _is_etf(name):
    if not name: return False
    if any(k in name for k in ETF_KW): return True
    tok = name.split()[0].upper() if name.split() else ""
    return tok in ETF_BRANDS

def main():
    bars = defaultdict(list)
    names = {}
    with open(EOD, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            try:
                if row.get("market", "") != "KOSDAQ":   # 전략 유니버스=코스닥(ETF는 대부분 KOSPI → 제거)
                    continue
                nm = row.get("name", "")
                if _is_etf(nm):                          # 코스닥 상장 ETF/ETN/스팩 안전망 제외
                    continue
                c = row["code"]
                bars[c].append((row["date"], float(row["open"]), float(row["high"]),
                                float(row["low"]), float(row["close"]),
                                float(row["volume"]), float(row["value"]),
                                float(row.get("w52_high_pct") or 0)))
                names[c] = nm
            except Exception:
                continue
    for c in bars:
        bars[c].sort()
    theme = _load_theme()
    asof = max((s[-1][0] for s in bars.values() if s), default="")

    hits = []
    for code, seq in bars.items():
        n = len(seq)
        if n < 36:
            continue
        t = n - 1                                   # 최신봉
        base = seq[t-30:t-5]
        if len(base) < 20:
            continue
        bavg = sum(b[5] for b in base) / len(base)
        bval = sum(b[6] for b in base) / len(base)
        if bavg <= 0 or bval < VAL_FLOOR:
            continue
        bh = max(b[2] for b in base); bl = min(b[3] for b in base)
        if bl <= 0 or (bh - bl) / bl > BASE_RANGE:
            continue
        window = seq[t-5:t+1]                       # 최근 6봉(터짐+소화+양봉재개)
        ti = next((i for i, b in enumerate(window) if b[5] >= THRUST_X * bavg), None)
        if ti is None:
            continue
        dig = window[ti:]
        reds = sum(1 for b in dig if b[4] < b[1])
        if reds < 2:
            continue
        if min(b[3] for b in dig) < bl:             # 베이스 깨짐 = 탈락
            continue
        # 양봉 재개 = window 내 최근 양봉(종가>시가 & 종가>전봉종가), 최근 GREEN_AGE 이내
        g_idx = None
        for i in range(len(window) - 1, max(len(window) - 1 - GREEN_AGE, 0) - 1, -1):
            b = window[i]; prev = window[i-1] if i > 0 else seq[t-6]
            if b[4] > b[1] and b[4] > prev[4]:
                g_idx = i; break
        if g_idx is None:
            continue
        green = window[g_idx]
        thrust_x = max(b[5] for b in window) / bavg
        pivot = green[2]                            # 돌파 진입선 = 양봉 고가
        cur = seq[t][4]
        to_break = (pivot / cur - 1) * 100          # 돌파까지 %(+면 아직 밑)
        broke = cur >= pivot                        # 이미 돌파했나
        gcpos = (green[4]-green[3])/(green[2]-green[3]) if green[2] > green[3] else 0.5
        age = (len(window) - 1 - g_idx)             # 양봉재개 며칠전
        th, lead = theme.get(code, ("", False))
        hits.append({"code": code, "name": names.get(code, "")[:10], "theme": th, "lead": lead,
                     "thrust": thrust_x, "reds": reds, "brange": (bh-bl)/bl*100,
                     "pivot": pivot, "cur": cur, "to_break": to_break, "broke": broke,
                     "gcpos": gcpos, "w52": green[7], "val": bval, "age": age})

    broke = sorted([h for h in hits if h["broke"]], key=lambda x: -x["thrust"])
    wait  = sorted([h for h in hits if not h["broke"]], key=lambda x: x["to_break"])

    L = []
    L.append(f"  세력 매집형 돌파 셋업 스크리너  (기준일 {asof})")
    L.append(f"  패턴: 한달베이스(범위≤{BASE_RANGE*100:.0f}%) → 거래량 {THRUST_X:g}배+ 터짐 → 음봉 매물소화 → 양봉 재개 → 전일고가 돌파 진입")
    L.append(f"  백테(1년): 전일고가돌파 진입 5일 +1.91%/승52%·MFE+12.6%·폭발≥15% 27%·체결률61% (종가진입 +1.15%보다 우위)")
    L.append("")
    def fmt(h):
        return (f"  {h['name']:<10} {h['code']}  배수{h['thrust']:4.1f} 음봉{h['reds']}일 "
                f"베이스{h['brange']:4.0f}% 양봉위치{h['gcpos']:.0%} w52 {h['w52']:3.0f} "
                f"거래대금{h['val']/100:5.0f}억 {'★대장' if h['lead'] else '     '} "
                f"[{h['theme']}]")

    L.append(f"🔔 돌파 발생/진입권 (현재가 ≥ 양봉고가)  ({len(broke)}개)")
    L.append(f"   {'종목':<10} {'코드':<6}  {'돌파선':>8} {'현재가':>8}")
    if broke:
        for h in broke:
            L.append(f"   {h['name']:<10} {h['code']}  {h['pivot']:>8,.0f} {h['cur']:>8,.0f}  ↑돌파")
            L.append(fmt(h))
    else:
        L.append("   (오늘 돌파 발생 없음)")
    L.append("")
    L.append(f"👀 돌파 대기 — 양봉고가 근접순  ({len(wait)}개)")
    L.append(f"   {'종목':<10} {'코드':<6}  {'돌파선':>8} {'현재가':>8} {'돌파까지':>7}")
    for h in wait[:25]:
        L.append(f"   {h['name']:<10} {h['code']}  {h['pivot']:>8,.0f} {h['cur']:>8,.0f} {h['to_break']:>+6.1f}%")
        L.append(fmt(h))
    L.append("")
    L.append("※ 매일저녁 자동(EOD 일봉 수집후). 진입선=양봉(전일) 고가 돌파. READ-ONLY(주문0·관찰용).")
    L.append("  실거래는 돌파실행기/NEW_PB가 돌파 확인+CHE_EXIT로 운영. 베이스 자체는 사지말것(돌파를 사라).")

    txt = "\n".join(L)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    # ★실전 연결: 돌파 실행기(_setup_zone_codes)가 읽는 CSV 발행 (수렴 CSV와 동일 패턴)
    #   → 돌파 실행기가 이 셋업을 후보에 병합 → 전일고가 돌파시 진입(BRK_LIVE)·CHE식 청산.
    csv_path = os.path.join(r"C:\stock_bot\data\shadow", f"base_thrust_setup_{asof}.csv")
    try:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as cf:
            w = csv.writer(cf)
            w.writerow(["date", "code", "name", "theme", "thrust_x", "reds", "base_range", "pivot", "w52", "val_eok", "leader"])
            for h in (broke + wait):   # 돌파권 우선, 대기 포함 — 실행기가 돌파 확인후 진입
                w.writerow([asof, h["code"], h["name"], h["theme"], f"{h['thrust']:.2f}", h["reds"],
                            f"{h['brange']:.1f}", f"{h['pivot']:.0f}", f"{h['w52']:.0f}",
                            f"{h['val']/100:.0f}", 1 if h["lead"] else 0])
    except Exception as e:
        print(f"[CSV발행 실패] {e}")
    sys.stdout.reconfigure(encoding="utf-8")
    print(txt)
    print(f"\n[저장] {OUT}\n[실전CSV] {csv_path} · 돌파권 {len(broke)} · 대기 {len(wait)}")

if __name__ == "__main__":
    main()

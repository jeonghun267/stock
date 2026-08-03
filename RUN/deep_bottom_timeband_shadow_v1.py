# -*- coding: utf-8 -*-
"""[깊은바닥 시간대 그림자 v1] 2026-07-09 밤 친구님 "10:25 잠금하고, 매일 그림자로 감시해봐 — 좋은 시간대가 나오는지".
실전은 아침 1차만(매수 ~10:00·10:20 전량청산·오후 폐쇄). 이 그림자는 매일 장 마감 후(16:05) 깊은바닥 대칭 로직을
09:03~14:30 전 시간대에 리플레이해 시간대별 성적을 기록 — 좋은 시간대가 보이면 친구님 보고 후 창 확장 결정.

로직(실전 대칭안과 동일·시간대만 확장):
  유니버스 = 대장주 순위표 · 등재 = 당일저점 전일종가比 -5%↓
  진입 = 체결강도 저점반등+8(표본5+) & 저점+1.5%~+6% (거래량 관문 없음=대칭안) · 종목당 최대 3회
  매도 = 구조붕괴(진입시 저점이탈) > 하드-2% > 체결강도되돌림(피크100+에서-12) > 반등소멸(체결강도≤당일저점+3)
        > 보유 80분 상한(아침 09:00→10:20 프레임과 동일 길이·전 시간대 공평비교) > EOD 15:18
주문 0 · 장중 TR 0(마감 후 opt10080만·0.5s 페이스) · 멱등(날짜 done 마커) · 1분봉 4페이지=~9일 자동 백필.
끄기: 태스크 SAFEPLUS_DEEP_TIMEBAND_SHADOW 비활성화.
"""
import os, sys, csv, io, json, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
DATA = Path(r"C:\stock_bot\data")
OUT = DATA / "shadow" / "deep_timeband_shadow.csv"
DONE = DATA / "shadow" / "deep_timeband_done.json"
LOG = DATA / "LOG" / "deep_timeband_shadow.log"
CHE_DIR = DATA / "shadow" / "che_timeseries"
PACE = float(os.environ.get("DEEPTB_PACE", "0.5"))
REB_PT = 8.0; REB_MINN = 5; SYM_PT = 3.0; HOLD_MAX_MIN = 80
# [7/9 밤 친구님 "서진시스템 09:54 왜 못 잡아"] 등재 -4%로 넓혀 기록(-4~-5% 밴드 vs -5%↓ 코호트 비교용·실전은 -5% 유지).
#   검증: 서진시스템 7/9 아침 저점 -4.0% → -4%안이면 09:18 매수 42,500 → 10:20 매도 44,350 = +4.35%(브로커 검증).
DROP = float(os.environ.get("DEEPTB_DROP", "-4.0"))

def log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    try: print(s, flush=True)
    except Exception: pass
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        io.open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception: pass

def ff(x):
    try: return abs(float(str(x).replace(",", "")))
    except Exception: return 0.0

def load_che(day):
    p = CHE_DIR / f"che_ts_{day}.csv"
    m = {}
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8-sig", newline="")):
            try: m.setdefault(r["code"].zfill(6), {})[r["hm"].zfill(4)] = float(r["che_str"])
            except Exception: pass
    return m

def sim_day(code, day, bars, che_m, pc):
    """bars: {hm4:(o,h,l,c,v)} 그날 1분봉 · che_m: {hm4:che} · 반환 [trade dict]."""
    lo = None; che_min = None; n = 0; reg = False
    pos = None; entries = 0; last_sell = -999; out = []
    for hm in sorted(set(bars) | set(che_m)):
        if hm > "1518": break
        che = che_m.get(hm)
        bar = bars.get(hm)
        px = bar[3] if bar else None
        if px is None: continue
        mi = int(hm[:2]) * 60 + int(hm[2:])
        low = bar[2]
        lo = low if lo is None else min(lo, low)
        if che is not None:
            n += 1; che_min = che if che_min is None else min(che_min, che)
        if not reg and pc and (lo / pc - 1) * 100 <= DROP:
            reg = True
        if pos:
            pos["peak"] = max(pos["peak"], px)
            if che is not None: pos["pkc"] = max(pos["pkc"], che)
            sell = None
            if px < pos["slo"]: sell = "구조붕괴"
            elif (px / pos["px"] - 1) * 100 <= -2.0: sell = "하드-2%"
            elif che is not None and pos["pkc"] >= 100 and che <= pos["pkc"] - 12: sell = "che되돌림"
            # [7/10 새벽] 반등소멸 제외 — 실전이 가격만 진입(NOCHE)으로 바뀌어 동일하게 맞춤(V3 검증)
            elif mi - pos["mi"] >= HOLD_MAX_MIN: sell = "80분상한"
            elif hm >= "1518": sell = "EOD"
            if sell:
                out.append(dict(date=day, code=code, ent_hm=pos["hm"], ent_px=pos["px"],
                                ex_hm=hm, ex_why=sell, ret=round((px / pos["px"] - 1) * 100, 2),
                                lo_pct=pos["lo_pct"]))
                pos = None; last_sell = mi
            continue
        if entries >= 3 or hm < "0903" or hm > "1430" or not reg or che is None: continue
        if mi - last_sell < 3: continue
        # [7/10 새벽 친구님 "체결강도 말고 그날의 저점"] 진입 = 가격만(저점+1.5% 턴·+6%내) — 실전(NOCHE)과 동일.
        #   10일 백테: 체결강도+8 +14.1%p(42%) → 가격만 +50.6%p(55%). 체결강도는 매도(되돌림)에서만 사용.
        if lo * 1.015 <= px <= lo * 1.06:
            entries += 1
            pos = dict(hm=hm, mi=mi, px=px, slo=lo, peak=px, pkc=(che or 0),
                       lo_pct=round((lo / pc - 1) * 100, 1))   # 진입시 등재깊이(-4~-5% 밴드 vs -5%↓ 코호트 비교용)
    if pos:
        lasth = max(bars)
        out.append(dict(date=day, code=code, ent_hm=pos["hm"], ent_px=pos["px"],
                        ex_hm=lasth, ex_why="장끝", ret=round((bars[lasth][3] / pos["px"] - 1) * 100, 2),
                        lo_pct=pos["lo_pct"]))
    return out

def main():
    from broker_client import BrokerClient
    try:
        codes = [str(c).zfill(6) for c in json.loads((DATA / "daily_leader_board.json").read_text(encoding="utf-8-sig")).get("codes", [])]
    except Exception:
        codes = []
    if not codes:
        log("대장주 순위표 없음 → 종료"); return
    # 날짜별 전일종가 표 (eod_daily_bars)
    closes = {}
    names = {}
    for r in csv.DictReader(open(DATA / "eod_daily_bars.csv", encoding="utf-8-sig", newline="")):
        c = r["code"].zfill(6)
        if c not in codes: continue
        names[c] = r["name"]
        try: closes.setdefault(c, {})[r["date"]] = float(r["close"])
        except Exception: pass
    try:
        done = json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {}
    except Exception:
        done = {}
    che_cache = {}
    bc = BrokerClient()
    rows_new = []
    for idx, code in enumerate(codes):
        if idx and idx % 20 == 0: log(f"..{idx}/{len(codes)}")
        try:
            recs = []
            nx = "0"
            for pg in range(4):
                r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "1", "수정주가구분": "1"},
                          output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량"],
                          rqname="DEEPTB", screen_no="9788", timeout_sec=15.0, next_flag=nx if pg else "0")
                d = (r or {}).get("data") or {}
                recs += (d.get("records") or [])
                time.sleep(PACE)
                if not d.get("has_next"): break
                nx = "2"
        except Exception:
            recs = []
        if not recs: continue
        by_day = {}
        for z in recs[::-1]:
            ts = str(z.get("체결시간", ""))
            if len(ts) < 12: continue
            by_day.setdefault(ts[:8], {})[ts[8:12]] = (ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가")), ff(z.get("거래량")))
        days = sorted(by_day)
        for j, day in enumerate(days):
            if done.get(day): continue                      # 이미 처리한 날짜
            if day not in (che_cache or {}):
                che_cache[day] = load_che(day)
            chem = che_cache[day].get(code)
            if not chem: continue                            # 체결강도 기록 없는 날/종목은 판정불가
            pdays = [d for d in closes.get(code, {}) if d < day]
            if not pdays: continue
            pc = closes[code][max(pdays)]
            if pc < 20000: continue
            rows_new += sim_day(code, day, by_day[day], chem, pc)
    # 저장(append·중복은 done 마커가 방지)
    if rows_new:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        new_file = not OUT.exists()
        with io.open(OUT, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "code", "name", "ent_hm", "ent_px", "ex_hm", "ex_why", "ret", "lo_pct"])
            if new_file: w.writeheader()
            for x in rows_new:
                x["name"] = names.get(x["code"], "")
                w.writerow(x)
    # 처리한 날짜 마커 (오늘 포함·che 기록이 있는 날만)
    today = datetime.now().strftime("%Y%m%d")
    for p in CHE_DIR.glob("che_ts_*.csv"):
        d = p.stem.replace("che_ts_", "")
        if d <= today:
            done[d] = True
    DONE.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    # 누적 시간대 집계 보고
    try:
        allr = list(csv.DictReader(open(OUT, encoding="utf-8-sig", newline="")))
    except Exception:
        allr = []
    log(f"신규 {len(rows_new)}건 기록 · 누적 {len(allr)}건 — 시간대별 성적:")
    from collections import defaultdict
    band = defaultdict(list)
    for x in allr:
        try: band[x["ent_hm"][:2] + "시"].append(float(x["ret"]))
        except Exception: pass
    for b in sorted(band):
        v = band[b]; w = sum(1 for y in v if y > 0.1)
        log(f"  {b}: {len(v):>3}건 평균 {sum(v)/len(v):+.2f}% 승률 {w/len(v)*100:.0f}%")
    # 등재깊이 코호트 (-4~-5% 밴드 vs -5%↓) — 실전 문턱 -5%→-4% 전환 판단 재료
    coh = defaultdict(list)
    for x in allr:
        try:
            d = float(x.get("lo_pct") or 0)
            coh["-5%↓(실전)" if d <= -5.0 else "-4~-5%(후보)"].append(float(x["ret"]))
        except Exception: pass
    for b in sorted(coh):
        v = coh[b]; w = sum(1 for y in v if y > 0.1)
        log(f"  깊이 {b}: {len(v):>3}건 평균 {sum(v)/len(v):+.2f}% 승률 {w/len(v)*100:.0f}%")

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""[그림자·주문0] 개장 정배열 전환(MA수렴 벌어짐) 검증 기록기 — 친구님 규칙 (2026-07-09 밤 신설)
매수: 전일 15시~ 3분봉 5/20선 만남(이격≤1%) + 전일엔 5·20이 60선 위가 아니었음
      → 당일 09:00~10:00 5선·20선 둘 다 60선 위로 올라서면 그 봉 종가 매수. 종목당 하루 1회.
매도: 당일 10:30까지 한 번으로 끝 —
      ①체결강도 되돌림(개장보정: 진입후 저점서 +10 되살아난 뒤의 꺾임만·피크120+·-12pt)
      ②20선 이탈(친구님 "20선이 받쳐준다" — 5선 이탈은 경고일 뿐, 20선 종가 이탈에 매도.
        7/9 검증: 5선&che약 +0.19% vs 20선 +0.62%·최악 -5.8%) ③10:30 강제.
      비교용으로 5선 즉시·10:30강제·구간최고도 같이 기록.
운영: 매일 15:50 장 마감 후 실행(태스크 SAFEPLUS_MA_FANOUT_SHADOW). 장중 TR 0.
      브로커 opt10080(3분봉) 1페이지/종목 → 페이지 안의 연속 (전일,당일) 쌍 전부 판정(백필),
      CSV (date,code) 중복은 스킵 = 몇 번 돌려도 안전.
유니버스: [7/9 밤 친구님 "선별기 없이"] 코스닥 전일종가 2만+ · 전일 거래대금 50억+ 전체
      (eod_daily_bars.csv 최근 10일 일별 자격 — 하루 ~100~115종목. 비면 대장주 풀로 폴백).
      검증: 넓은 풀 +0.96%/승률55% > 대장주 풀 +0.62%/54% · 하락일 자동 0건 성질 유지.
끄기: 태스크 Disable. 실전 전환은 별도 배선 필요(이 파일은 주문 코드 자체가 없음).
"""
import sys, os, csv, json, time, datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", buffering=1)

DATA = r"C:\stock_bot\data"
OUT_CSV = os.path.join(DATA, "shadow", "ma_fanout_shadow.csv")
LOG = os.path.join(DATA, "LOG", "ma_fanout_shadow.log")
CHE_DIR = os.path.join(DATA, "shadow", "che_timeseries")
BOARD = os.path.join(DATA, "daily_leader_board.json")

PACE = float(os.environ.get("MAFAN_PACE", "0.6"))
MIN_PRICE = float(os.environ.get("SAFEPLUS_MIN_PRICE", "20000"))
CONV_PCT = float(os.environ.get("MAFAN_CONV_PCT", "1.0"))     # 전일 5/20 이격 상한(%)
ENT_BEG, ENT_END, CUT = "09:00", "10:00", "10:30"
# [우선순위 ★ 7/9 검증] 신뢰창 09:12~09:36(그 전=개장가짜·그 후=추격) + 진입시 당일상승 +3%내(안뜬놈).
# 108건: ★조건 +1.94%/승률68%/최악-2.4% vs 전체 +0.96%/55%/-5.8%. 갭2%+는 오히려 나쁨(+0.21%).
PICK_BEG = os.environ.get("MAFAN_PICK_BEG", "09:12")
PICK_END = os.environ.get("MAFAN_PICK_END", "09:36")
PICK_MAXUP = float(os.environ.get("MAFAN_PICK_MAXUP", "3.0"))
# [◆1군 7/9 밤 친구님 지시] 9시부터 1분봉 관찰·조건 성립 후 3분 이내 매수자우위 체결량(>100) 확인 진입.
# 백테는 체결강도로 확인(기관/외인/프로그램 분단위 과거기록 없음) — 실전 배선 시 돈유입 probe 추가.
CHE_CONFIRM = float(os.environ.get("MAFAN_CHE_CONFIRM", "100"))
CONFIRM_MIN = int(os.environ.get("MAFAN_CONFIRM_MIN", "3"))

def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def ff(x):
    try:
        return abs(float(str(x).replace(",", "")))
    except Exception:
        return 0.0

def load_che(day):
    """day=YYYYMMDD → {(code,HHMM): che}"""
    p = os.path.join(CHE_DIR, f"che_ts_{day}.csv")
    m = {}
    if not os.path.exists(p):
        return m
    try:
        for r in csv.DictReader(open(p, encoding="utf-8-sig", newline="")):
            try:
                m[(r["code"].zfill(6), r["hm"].zfill(4))] = float(r["che_str"])
            except Exception:
                pass
    except Exception:
        pass
    return m

def che_at(chem, code, hm):
    """hm='HH:MM' → 그 분 또는 직전 2분 체결강도"""
    mi = int(hm[:2]) * 60 + int(hm[3:5])
    for k in range(3):
        v = chem.get((code, f"{(mi-k)//60:02d}{(mi-k)%60:02d}"))
        if v is not None:
            return v
    return None

def judge(code, b_prev, b_cur, chem):
    """전일/당일 3분봉 → 진입·매도 판정. 반환 dict 또는 None."""
    if len(b_prev) < 80 or len(b_cur) < 10:
        return None
    pc = b_prev[-1][4]
    if pc < MIN_PRICE:
        return None
    if min(x[3] for x in b_cur) < pc * 0.65 or max(x[2] for x in b_cur) > pc * 1.35:
        return None  # 불량시세
    closes = [x[4] for x in b_prev]
    m5o = sum(closes[-5:]) / 5
    m20o = sum(closes[-20:]) / 20
    m60o = sum(closes[-60:]) / 60
    if abs(m5o / m20o - 1) * 100 > CONV_PCT:
        return None                                   # ①전일 5/20 만남 아님
    if m5o > m60o and m20o > m60o:
        return None                                   # ②이미 60선 위 = "다시 위로"가 아님
    gap = (b_cur[0][1] / pc - 1) * 100
    ent = None
    for i, (hm, o, h, l, c) in enumerate(b_cur):
        if hm > ENT_END:
            break
        closes.append(c)
        m5 = sum(closes[-5:]) / 5
        m20 = sum(closes[-20:]) / 20
        m60 = sum(closes[-60:]) / 60
        if hm >= ENT_BEG and m5 > m60 and m20 > m60:  # ③5·20선 둘 다 60선 위
            ent = (i, hm, c)
            break
    if ent is None:
        return None
    i, ent_hm, ent_px = ent
    win = [x for x in b_cur[i + 1:] if x[0] <= CUT]
    if not win:
        return None
    best = (max(x[2] for x in win) / ent_px - 1) * 100
    # 매도 사다리 + 비교군
    # [개장 보정] 되돌림은 "진입 후 저점에서 +RISE 이상 되살아난 뒤의 꺾임"만 인정 —
    # 개장 체결강도 스파이크(400→180 감쇠)는 고점 갱신이 아니라 식는 것이므로 발동 금지.
    RISE = float(os.environ.get("MAFAN_CHE_RISE", "10"))
    ch = list(closes)
    che_ent = che_at(chem, code, ent_hm)
    che_low = che_ent
    armed = False
    rally_peak = 0.0
    r_ladder = r_m5 = None
    ex_hm = ex_why = ""
    for hm, o, h, l, c in win:
        ch.append(c)
        m5 = sum(ch[-5:]) / 5
        m20 = sum(ch[-20:]) / 20
        cnow = che_at(chem, code, hm)
        if cnow is not None:
            if che_low is None or cnow < che_low:
                che_low = cnow
            if not armed and che_low is not None and cnow >= che_low + RISE:
                armed = True
                rally_peak = cnow
            if armed:
                rally_peak = max(rally_peak, cnow)
        if r_m5 is None and c < m5:
            r_m5 = (c / ent_px - 1) * 100
        if r_ladder is None:
            if armed and cnow is not None and rally_peak >= 120 and cnow <= rally_peak - 12:
                r_ladder = (c / ent_px - 1) * 100
                ex_hm, ex_why = hm, "체결강도되돌림"
            elif c < m20:
                r_ladder = (c / ent_px - 1) * 100
                ex_hm, ex_why = hm, "20선이탈"
    r_cut = (win[-1][4] / ent_px - 1) * 100
    if r_ladder is None:
        r_ladder, ex_hm, ex_why = r_cut, CUT, "10:30강제"
    if r_m5 is None:
        r_m5 = r_cut
    day_up = (ent_px / pc - 1) * 100
    if PICK_BEG <= ent_hm <= PICK_END and day_up <= PICK_MAXUP:
        pick = "★"                                     # 1군: 신뢰창(검증 +2.79%/79%)
    elif ent_hm < PICK_BEG and day_up <= PICK_MAXUP and gap < 2.0:
        pick = "☆"                                     # 2군: 9시 초반(친구님 "9시 바로"·갭점프 제외·검증 +0.64%/44%)
    else:
        pick = ""
    return dict(ent_hm=ent_hm, ent_px=ent_px, gap=round(gap, 2),
                che_ent=("" if che_ent is None else round(che_ent, 1)),
                ex_hm=ex_hm, ex_why=ex_why,
                r_ladder=round(r_ladder, 2), r_m5=round(r_m5, 2),
                r_cut=round(r_cut, 2), best=round(best, 2), prev_close=pc,
                day_up=round(day_up, 2), pick=pick)

def fetch_1m(bc, code, need_oldest):
    """1분봉 최대 4페이지 → {YYYYMMDD: [(hm,o,h,l,c)]}. need_oldest 날짜까지 확보 시도."""
    recs = []
    pn = 0
    for _ in range(4):
        try:
            r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "1", "수정주가구분": "1"},
                      output_fields=["체결시간", "시가", "고가", "저가", "현재가"],
                      rqname="MAFAN_1M", screen_no="9770", next_flag=pn, timeout_sec=15.0)
            d = (r or {}).get("data") or {}
            rows = d.get("records") or []
        except Exception:
            rows = []
        if not rows:
            break
        recs.extend(rows)
        time.sleep(PACE)
        oldest = str(rows[-1].get("체결시간", ""))[:8]
        pnext = str(d.get("prev_next", (r or {}).get("prev_next", ""))).strip()
        if oldest <= need_oldest or pnext != "2":
            break
        pn = 2
    by_day = {}
    for z in recs[::-1]:
        ts = str(z.get("체결시간", ""))
        if len(ts) < 12:
            continue
        by_day.setdefault(ts[:8], []).append(
            (f"{ts[8:10]}:{ts[10:12]}", ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가"))))
    return by_day

def refine_1m(code, d_prev, d, m1, chem):
    """[◆1군·친구님 방식 7/9 밤] 9시부터 1분 관찰(1분종가 15/60/180평균 = 3분봉 5/20/60선 상당).
    조건 성립 후 계속 관찰 — 매수자우위 체결량(>100)이 붙는 그 1분에 진입(강하면 신호 즉시).
    버리지 않음: 확인 늦으면 늦게라도(진입창 내), 당일 +3% 초과 상태면 +3%내로 돌아올 때 진입.
    체결강도 기록이 아예 없는 종목은 신호분 진입(실전은 기관/외인/프로그램 돈유입 probe가 확인 대체)."""
    b0 = (m1 or {}).get(d_prev) or []
    b1 = (m1 or {}).get(d) or []
    if len(b0) < 200 or len(b1) < 20:
        return None
    pc = b0[-1][4]
    has_che = any(k[0] == code for k in chem) if chem else False
    closes = [x[4] for x in b0]
    sig_hm = None
    ent_i = None
    for i, (hm, o, h, l, c) in enumerate(b1):
        if hm > ENT_END:
            break
        closes.append(c)
        ma5 = sum(closes[-15:]) / 15
        ma20 = sum(closes[-60:]) / 60
        ma60 = sum(closes[-180:]) / 180
        if not (hm >= ENT_BEG and ma5 > ma60 and ma20 > ma60):
            continue
        if sig_hm is None:
            sig_hm = hm
        cv = che_at(chem, code, hm)
        if (cv is not None and cv > CHE_CONFIRM) or (cv is None and not has_che):
            ent_i = i
            break
    if sig_hm is None:
        return None
    if ent_i is None:
        return dict(sig1_hm=sig_hm, ent1_hm="", ent1_px="", r1="", why1="확인미충족", ex1_hm="")
    ent_hm, ent_px = b1[ent_i][0], b1[ent_i][4]
    win = [x for x in b1[ent_i + 1:] if x[0] <= CUT]
    if not win:
        return dict(sig1_hm=sig_hm, ent1_hm=ent_hm, ent1_px=ent_px, r1="", why1="장부족", ex1_hm="")
    # [매도판정은 3분봉 마감 주기] 1분 단위 판정은 체결강도 미세출렁(+10↔-12)에 휩쏘 —
    # 탈 때는 1분(빠르게)·팔 때는 3분(차분하게). 코미코 검증: 1분판정 +0.99% vs 3분판정 +8.6%.
    RISE = float(os.environ.get("MAFAN_CHE_RISE", "10"))
    ch = [x[4] for x in b0] + [x[4] for x in b1[:ent_i + 1]]
    che_low = che_at(chem, code, ent_hm)
    armed = False
    rally = 0.0
    r1 = None
    ex_hm, why = CUT, "10:30강제"
    for hm, o, h, l, c in win:
        ch.append(c)
        m20 = sum(ch[-60:]) / 60                       # 3분봉 20선 상당
        cn = che_at(chem, code, hm)
        if cn is not None:
            if che_low is None or cn < che_low:
                che_low = cn
            if not armed and che_low is not None and cn >= che_low + RISE:
                armed = True
                rally = cn
            if armed:
                rally = max(rally, cn)
        if (int(hm[:2]) * 60 + int(hm[3:5]) - 540) % 3 != 2:
            continue                                   # 3분봉 마감분(09:02,09:05,…)에만 매도 판정
        if armed and cn is not None and rally >= 120 and cn <= rally - 12:
            r1 = (c / ent_px - 1) * 100
            ex_hm, why = hm, "체결강도되돌림"
            break
        if c < m20:
            r1 = (c / ent_px - 1) * 100
            ex_hm, why = hm, "20선이탈"
            break
    if r1 is None:
        r1 = (win[-1][4] / ent_px - 1) * 100
    return dict(sig1_hm=sig_hm, ent1_hm=ent_hm, ent1_px=ent_px,
                r1=round(r1, 2), why1=why, ex1_hm=ex_hm,
                day_up1=round((ent_px / pc - 1) * 100, 2))

MIN_VALUE_MW = float(os.environ.get("MAFAN_MIN_VALUE_EOK", "50")) * 100  # 거래대금 하한(백만원 환산)
EOD_BARS = os.path.join(DATA, "eod_daily_bars.csv")

def build_universe():
    """코스닥 전일종가 2만+·거래대금 50억+ 일별 자격표(최근 10일). 반환 (elig{date:set}, names)."""
    elig, names = {}, {}
    try:
        rows = list(csv.DictReader(open(EOD_BARS, encoding="utf-8-sig", newline="")))
        dates = sorted({r["date"] for r in rows})[-10:]
        dset = set(dates)
        for r in rows:
            d = r["date"]
            if d not in dset:
                continue
            code = r["code"].zfill(6)
            names[code] = r["name"]
            try:
                if r["market"] == "KOSDAQ" and float(r["close"]) >= MIN_PRICE and float(r["value"] or 0) >= MIN_VALUE_MW:
                    elig.setdefault(d, set()).add(code)
            except Exception:
                pass
    except Exception as e:
        log(f"일봉 유니버스 구축 실패: {e}")
    return elig, names

def main():
    elig, names = build_universe()
    codes = sorted(set().union(*elig.values())) if elig else []
    if codes:
        log(f"유니버스: 코스닥 2만+·50억+ 최근10일 합집합 {len(codes)}종목")
    else:
        # 폴백: 대장주 풀 (일봉 파일 멈춤 등)
        try:
            board = json.load(open(BOARD, encoding="utf-8"))
            codes = [str(c).zfill(6) for c in (board.get("codes") or [])]
        except Exception as e:
            log(f"대장주 풀 폴백도 실패: {e}")
            return
        log(f"⚠️ 일봉 유니버스 실패 → 대장주 풀 폴백 {len(codes)}종목(전일자격 검사 생략)")
    if not codes:
        log("유니버스 비어있음 — 종료")
        return

    seen = set()
    if os.path.exists(OUT_CSV):
        try:
            for r in csv.DictReader(open(OUT_CSV, encoding="utf-8-sig", newline="")):
                seen.add((r["date"], r["code"]))
        except Exception:
            pass

    from broker_client import BrokerClient
    bc = BrokerClient()
    che_cache = {}
    new_rows = []
    fails = 0
    for idx, code in enumerate(codes):
        try:
            r = bc.tr("opt10080",
                      inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                      output_fields=["체결시간", "시가", "고가", "저가", "현재가"],
                      rqname="MAFAN_SHADOW", screen_no="9767", timeout_sec=15.0)
            recs = (((r or {}).get("data") or {}).get("records") or [])
        except Exception:
            recs = []
        if not recs:
            fails += 1
            time.sleep(PACE)
            continue
        by_day = {}
        for z in recs[::-1]:
            ts = str(z.get("체결시간", ""))
            if len(ts) < 12:
                continue
            by_day.setdefault(ts[:8], []).append(
                (f"{ts[8:10]}:{ts[10:12]}", ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가"))))
        days = sorted(by_day)
        code_events = []
        for j in range(1, len(days)):
            d = days[j]
            if elig and code not in elig.get(days[j - 1], set()):
                continue  # 전일 자격(코스닥·2만+·50억+) 미달
            if (d, code) in seen:
                continue
            if d not in che_cache:
                che_cache[d] = load_che(d)
            res = judge(code, by_day[days[j - 1]], by_day[d], che_cache[d])
            if res:
                res.update(date=d, code=code, name=names.get(code, ""), prev_day=days[j - 1])
                code_events.append(res)
                seen.add((d, code))
        if code_events:
            m1 = fetch_1m(bc, code, min(e["prev_day"] for e in code_events))
            for e in code_events:
                r1 = refine_1m(code, e["prev_day"], e["date"], m1, che_cache.get(e["date"]) or {})
                if r1:
                    e.update(r1)
            new_rows.extend(code_events)
        time.sleep(PACE)

    if new_rows:
        cols = ["date", "code", "name", "ent_hm", "ent_px", "gap", "che_ent",
                "ex_hm", "ex_why", "r_ladder", "r_m5", "r_cut", "best", "prev_close",
                "day_up", "pick", "sig1_hm", "ent1_hm", "ent1_px", "r1", "why1", "ex1_hm", "day_up1"]
        exists = os.path.exists(OUT_CSV)
        os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
        with open(OUT_CSV, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if not exists:
                w.writeheader()
            for row in sorted(new_rows, key=lambda x: (x["date"], x["ent_hm"])):
                w.writerow(row)
    today = f"{datetime.date.today():%Y%m%d}"
    td = [r for r in new_rows if r["date"] == today]
    log(f"스캔 {len(codes)}종목(TR실패 {fails}) → 신규기록 {len(new_rows)}건 (오늘 {len(td)}건)")
    for r in sorted(new_rows, key=lambda x: (x["date"], x["ent_hm"])):
        log(f"  {r['pick'] or ' '}{r['date']} {r['name'] or r['code']} {r['ent_hm']} 매수 {r['ent_px']:,.0f} "
            f"→ {r['ex_hm']} {r['ex_why']} {r['r_ladder']:+.2f}% (5선즉시 {r['r_m5']:+.2f} / 강제 {r['r_cut']:+.2f} / 최고 {r['best']:+.2f}) 체결강도 {r['che_ent']} 당일{r['day_up']:+.1f}%")
    for mark, lab in (("★", f"1군 신뢰창 {PICK_BEG}~{PICK_END}"), ("☆", f"2군 9시초반 ~{PICK_BEG}·갭2%미만")):
        picks = [r for r in new_rows if r["pick"] == mark]
        if picks:
            v = [r["r_ladder"] for r in picks]
            log(f"{mark}{lab} 통과 {len(picks)}건: 평균 {sum(v)/len(v):+.2f}%")
    dia = [r for r in new_rows if isinstance(r.get("r1"), (int, float))]
    if dia:
        v = [r["r1"] for r in dia]
        w = sum(1 for x in v if x > 0.1)
        log(f"◆1분관찰·체결확인 진입 {len(dia)}건: 평균 {sum(v)/len(v):+.2f}% 승률 {w/len(v)*100:.0f}%")

if __name__ == "__main__":
    main()

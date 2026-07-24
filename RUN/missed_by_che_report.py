# -*- coding: utf-8 -*-
"""[READ-ONLY·주문0] 미진입 회수 추적기 — "가격게이트 통과 + che 탈락" 자리 전수 기록 (2026-07-04 친구님 "087010 버리기 아깝다").
매일 장마감 후: 전략100 × {GC560·통합대장·바닥·눌림} 가격게이트를 재현 → che<100(또는 부재)로 실전 미진입이었던 첫 자리를 기록.
이후 EOD 수익률·최대상승(MFE)을 붙여 CSV 누적 → 몇 주 뒤 "che 탈락 코호트"가 플러스면 근거를 갖고 게이트 완화 설계.
출력: data/shadow/missed_by_che/missed_<date>.csv + 로그 요약. TR: 종목당 opt10080 1콜(~100콜)."""
import sys, csv, os, time, json
from datetime import datetime
from pathlib import Path
sys.path.insert(0, r"C:\stock_bot\RUN")

OUTD = Path(r"C:\stock_bot\data\shadow\missed_by_che")
CHED = Path(r"C:\stock_bot\data\shadow\che_timeseries")
STRAT = Path(r"C:\stock_bot\IPC\micro_watch_strategy.json")
CHE_MIN = 100.0
GAP_MIN, GAP_MAX = 0.2, 1.5


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def ff(x):
    try: return abs(float(str(x).replace(",", "")))
    except Exception: return 0.0


def rma(cl, n):
    return sum(cl[-n:]) / min(n, len(cl)) if cl else 0.0


def main():
    today = datetime.now().strftime("%Y%m%d")
    if datetime.now().strftime("%H%M") < "1531":
        log("장마감 전 — 종료"); return
    # che 실기록(그날 실전 스냅과 동일 뷰)
    che = {}
    p = CHED / f"che_ts_{today}.csv"
    if not p.exists():
        log(f"che_ts_{today}.csv 없음(휴장?) — 종료"); return
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            v = (r.get("che_str") or "").strip()
            if not v: continue
            try: che.setdefault(r["code"].zfill(6), []).append((r["hm"], float(v)))
            except Exception: pass
    for c in che: che[c].sort()

    def che_at(code, hm):
        lst = che.get(code)
        if not lst: return None
        t = int(hm[:2]) * 60 + int(hm[2:]); best = None
        for h, v in lst:
            x = int(h[:2]) * 60 + int(h[2:])
            if x <= t and t - x <= 5: best = v
            elif x > t: break
        return best

    try:
        codes = [str(c).zfill(6) for c in (json.loads(STRAT.read_text(encoding="utf-8")).get("codes") or [])]
    except Exception:
        codes = list(che.keys())
    if not codes:
        codes = list(che.keys())
    log(f"universe {len(codes)}종목 · che기록 {len(che)}종목")

    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        log("브로커 미기동 — 종료"); return
    bc = BrokerClient()
    try:
        import reversal_unified_v1 as REV
    except Exception: REV = None
    try:
        import pullback_unified_v1 as PB
    except Exception: PB = None

    OUTD.mkdir(parents=True, exist_ok=True)
    out = OUTD / f"missed_{today}.csv"
    rows = []
    for i, code in enumerate(codes):
        try:
            r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                      output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량"], timeout_sec=8.0, screen_no="9748")
            bars = []
            for z in (((r or {}).get("data") or {}).get("records") or [])[::-1]:
                ts = str(z.get("체결시간", ""))
                if ts[:8] != today: continue
                bars.append((ts[8:12], ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가")), ff(z.get("거래량"))))
        except Exception:
            bars = []
        time.sleep(0.3)
        if len(bars) < 10: continue
        eod_close = bars[-1][4]
        found = {}   # engine -> (hm, px, che, why)
        closes = []
        op = bars[0][1]
        for bi, b in enumerate(bars):
            hm, o, h, l, c, v = b
            closes.append(c)
            m5, m20, m40, m60 = rma(closes, 5), rma(closes, 20), rma(closes, 40), rma(closes, 60)
            not_rev = not (m5 < m20 < m40 < m60)
            # GC560 신설정 가격게이트(이격밴드+우상향+거래량up) — 창 ~11:00
            if "gc" not in found and hm <= "1100" and len(closes) >= 63 and m60 > 0 and c > m60:
                gap = (m5 / m60 - 1) * 100
                pc = closes[:-3]
                up = not (rma(pc, 60) > m60 or rma(pc, 20) > m20)
                volup = bi >= 1 and v > bars[bi - 1][5]
                if GAP_MIN <= gap <= GAP_MAX and not_rev and up and volup:
                    ch = che_at(code, hm)
                    if not (ch is not None and ch >= CHE_MIN):
                        found["GC560"] = (hm, c, ch)
            # 통합대장(p1/p2) — 창 ~11:00
            if "UNI" not in found and hm <= "1100" and len(closes) >= 60:
                p1 = m60 > 0 and c > m60 and 0 <= (c / m60 - 1) * 100 <= 7.0
                p2 = m5 >= m20 and c > op and m20 > 0 and (c / m20 - 1) * 100 <= 8.0
                if not_rev and (p1 or p2):
                    ch = che_at(code, hm)
                    if not (ch is not None and ch >= CHE_MIN):
                        found["UNI"] = (hm, c, ch)
            # 바닥사냥꾼 — 창 ~14:00
            if REV is not None and "REV" not in found and hm <= "1400":
                try:
                    g = REV.gate(bars[:bi + 1], c, hm)
                    if g.get("ok"):
                        ch = che_at(code, hm)
                        if not (ch is not None and ch >= CHE_MIN):
                            found["REV"] = (hm, c, ch)
                except Exception: pass
            # 눌림사냥꾼 — 창 ~13:30
            if PB is not None and "PB" not in found and hm <= "1330":
                try:
                    g = PB.gate(bars[:bi + 1], c)
                    if g:
                        ch = che_at(code, hm)
                        if not (ch is not None and ch >= CHE_MIN):
                            found["PB"] = (hm, c, ch)
                except Exception: pass
        # [V1 코호트 2026-07-04 친구님 "후행없는 조건" 검증] 양봉+거래량↑+che>=100 첫 자리(~11:00).
        #   통합대장 가격게이트(당일봉 근사) 안/밖 분류 — 밖(V1OUT)이 5일 백테 건당 +2.00% 코호트. 표본 축적용.
        closes2 = []
        for bi, b in enumerate(bars):
            hm, o, h, l, c, v = b
            closes2.append(c)
            if hm > "1100" or bi < 1: continue
            if not (c > o and v > bars[bi - 1][5]): continue
            ch = che_at(code, hm)
            if not (ch is not None and ch >= CHE_MIN): continue
            m5, m20, m40, m60 = rma(closes2, 5), rma(closes2, 20), rma(closes2, 40), rma(closes2, 60)
            not_rev = not (m5 < m20 < m40 < m60)
            p1 = m60 > 0 and c > m60 and 0 <= (c / m60 - 1) * 100 <= 7.0
            p2 = m5 >= m20 and c > bars[0][1] and m20 > 0 and (c / m20 - 1) * 100 <= 8.0
            if not_rev and (p1 or p2):
                tag = "V1IN"                                   # 통합대장 영역(참고)
            elif (not not_rev) or (m60 > 0 and c < m60):
                tag = "V1LOW"                                  # ★저점전환형(우하향→우상향 초기점) — 판정 대상
            else:
                tag = "V1HOT"                                  # 과열형(이격초과 추격) — 참고
            found[tag] = (hm, c, ch)
            break
        # [ALT 코호트 2026-07-05 친구님 "대안은 그림자로 기록·3일 후 결과"] 대형주 체결국면 눈금 대안 검증(주문없음·기록만).
        #   ALT_NEWHIGH(대안①): 통합대장 가격게이트 ∩ 체결국면 '당일 신고 갱신'(절대값 무관) 첫 자리 — 7/3 근사검증 에코프로+3.3/엘앤씨+6.7/제룡+1.4.
        #   ALT_90(대안②): 게이트 ∩ 90<=체결국면<100 첫 자리(현행 100이면 탈락) — 분석 때 거래대금 1000억+ 분리.
        closes3 = []; hi = None; nsnap = 0
        cum_pv = 0.0; cum_v = 0.0; below_n = 0; was_below = False
        lo_che = None; day_hi = 0.0
        for bi, b in enumerate(bars):
            hm, o, h, l, c, v = b
            closes3.append(c)
            day_hi = max(day_hi, h)
            cum_pv += c * v; cum_v += v
            vwap = cum_pv / cum_v if cum_v > 0 else 0.0
            ch = che_at(code, hm)
            prev_hi, prev_n = hi, nsnap
            prev_lo = lo_che
            if ch is not None and hm >= "0910":
                hi = ch if hi is None else max(hi, ch); nsnap += 1
                lo_che = ch if lo_che is None else min(lo_che, ch)
            # ALT_STAIR(대안④ 2026-07-05 친구님 "먹을 수 있을 때 먹고 빠진다·계단식도 조건 만들면 먹는다"):
            #   고점比-4%+ & 20선아래 & VWAP아래 30분+(기관 물량흘리기) & 국면 저점+8 반등 첫 자리(~14:00).
            #   7/3 4종목 검증 +2.4(에스티팜 신규)/+3.8(제룡 신규)/+5.7/+3.6 — 폭락지속일 위험만 미검증(표본으로 판정).
            if ("ALT_STAIR" not in found and hm <= "1400" and ch is not None and prev_lo is not None
                    and nsnap >= 5 and ch >= prev_lo + 8 and day_hi > 0
                    and (day_hi - c) / day_hi * 100 >= 4.0 and vwap > 0 and c < vwap and below_n >= 10):
                m20s = rma(closes3, 20)
                if m20s is not None and m20s > 0 and c < m20s:
                    found["ALT_STAIR"] = (hm, c, ch)
            # ALT_VWAP(대안③ 2026-07-05 친구님 "계단식 하락, 프로 방법"): 당일 VWAP 아래 30분+(10봉) 체류(기관 물량흘리기 흔적)
            #   후 첫 재탈환(reclaim) = 매도 소진·전환 후보. 창 ~14:00. 기록만(체결국면 무관·분석 때 슬라이스).
            if "ALT_VWAP" not in found and hm <= "1400" and vwap > 0:
                if c < vwap:
                    below_n += 1; was_below = True
                elif was_below and below_n >= 10 and c > vwap:
                    found["ALT_VWAP"] = (hm, c, ch)
            if hm > "1100" or ch is None: continue
            if "ALT_NEWHIGH" in found and "ALT_90" in found: continue
            m5, m20, m40, m60 = rma(closes3, 5), rma(closes3, 20), rma(closes3, 40), rma(closes3, 60)
            not_rev = not (m5 < m20 < m40 < m60)
            p1 = m60 > 0 and c > m60 and 0 <= (c / m60 - 1) * 100 <= 7.0
            p2 = m5 >= m20 and c > bars[0][1] and m20 > 0 and (c / m20 - 1) * 100 <= 8.0
            if not (not_rev and (p1 or p2)): continue
            if "ALT_NEWHIGH" not in found and prev_hi is not None and prev_n >= 5 and ch >= prev_hi:
                found["ALT_NEWHIGH"] = (hm, c, ch)
            if "ALT_90" not in found and 90 <= ch < 100:
                found["ALT_90"] = (hm, c, ch)
        # [초기매도 2026-07-05 친구님 "초기에 잘라서 자리 비우고 다른 종목 대기"] ALT_STAIR 자리에 대해
        #   '빠른 매도(VWAP반납/하드-3/최저이탈)' 청산가·시각을 병기 → 수요일 보고서에서 보유(eod) vs 초기매도(qx)를
        #   보유시간 포함(시간당 수익)으로 공정 비교. 기록 전용.
        stair_qx = {}
        if "ALT_STAIR" in found:
            try:
                shm, spx, sch = found["ALT_STAIR"]
                LLs = min(x[3] for x in bars if x[0] <= shm)
                cum2p = 0.0; cum2v = 0.0; above = False; qx = None
                for x in bars:
                    cum2p += x[4] * x[5]; cum2v += x[5]
                    vw = cum2p / cum2v if cum2v > 0 else 0.0
                    if x[0] <= shm: continue
                    ret = (x[4] / spx - 1) * 100
                    if ret <= -3.0: qx = (x[0], ret); break
                    if x[4] < LLs: qx = (x[0], ret); break
                    if vw > 0 and x[4] > vw: above = True
                    elif above and vw > 0 and x[4] < vw: qx = (x[0], ret); break
                if qx is None: qx = (bars[-1][0], (eod_close / spx - 1) * 100)
                stair_qx = {"qx_hm": qx[0], "qx_ret": f"{qx[1]:.2f}"}
                # qt = 콤보매도(친구님 7/5 "VWAP+체결강도+고점트레일"): 고점-2%트레일(수익권만) OR VWAP반납+국면약화 OR 하드/최저/EOD
                cum3p = 0.0; cum3v = 0.0; above2 = False; pk = 0.0; cpk2 = None; qt = None
                for x in bars:
                    cum3p += x[4] * x[5]; cum3v += x[5]
                    vw = cum3p / cum3v if cum3v > 0 else 0.0
                    if x[0] < shm: continue
                    pk = max(pk, x[2])
                    ch2 = che_at(code, x[0])
                    if ch2 is not None: cpk2 = ch2 if cpk2 is None else max(cpk2, ch2)
                    if x[0] <= shm: continue
                    ret = (x[4] / spx - 1) * 100
                    if ret <= -3.0: qt = (x[0], ret); break
                    if x[4] < LLs: qt = (x[0], ret); break
                    if pk > spx and x[4] <= pk * 0.98: qt = (x[0], ret); break
                    if vw > 0 and x[4] > vw: above2 = True
                    elif above2 and vw > 0 and x[4] < vw and ch2 is not None and cpk2 is not None and ch2 < cpk2:
                        qt = (x[0], ret); break
                if qt is None: qt = (bars[-1][0], (eod_close / spx - 1) * 100)
                stair_qx["qt_hm"] = qt[0]; stair_qx["qt_ret"] = f"{qt[1]:.2f}"
            except Exception:
                stair_qx = {}
        for eng, (hm, px, ch) in found.items():
            after = [x for x in bars if x[0] > hm]
            mfe = (max(x[2] for x in after) / px - 1) * 100 if after else 0.0
            row = {"date": today, "engine": eng, "code": code, "hm": hm, "px": f"{px:.0f}",
                   "che": ("" if ch is None else f"{ch:.1f}"), "eod_ret": f"{(eod_close/px-1)*100:.2f}",
                   "mfe": f"{mfe:.2f}", "price_level": f"{px:.0f}"}
            if eng == "ALT_STAIR" and stair_qx: row.update(stair_qx)
            rows.append(row)
        if (i + 1) % 25 == 0: log(f"  ...{i + 1}/{len(codes)}")

    new = not out.exists()
    with open(out, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "engine", "code", "hm", "px", "che", "eod_ret", "mfe", "price_level", "qx_hm", "qx_ret", "qt_hm", "qt_ret"], restval="")
        if new: w.writeheader()
        for r in rows: w.writerow(r)
    if rows:
        rets = [float(r["eod_ret"]) for r in rows]
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100
        log(f"★미진입(che탈락) {len(rows)}자리 기록 → EOD 승률 {wr:.1f}% 평균 {sum(rets)/len(rets):+.2f}% (누적파일 {out.name})")
        by = {}
        for r in rows: by.setdefault(r["engine"], []).append(float(r["eod_ret"]))
        for e, a in sorted(by.items()):
            log(f"  {e}: {len(a)}건 평균 {sum(a)/len(a):+.2f}%")
    else:
        log("오늘 미진입(che탈락) 자리 없음")


if __name__ == "__main__":
    main()

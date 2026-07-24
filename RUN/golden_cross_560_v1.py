# -*- coding: utf-8 -*-
"""[3분봉 5/60 골든크로스 — 친구님 2026-06-30 "5선이 60선 살짝 위 = 바닥 시작"] 회복 초입 잡기.
   라이더/딥/갭대장이 다 놓치는 '개장 약세 → 바닥 → 회복' 패턴을 5/60 골든크로스로 초입에 잡는다.
   ★검증(브로커 직접): 065170 +35%·320000 +18.8%·347700 +15.9% (5종목 골든크로스 다 적중·MFE평균+15%).
   진입: 거래대금 대장 ∩ 3분봉 5선이 60선 상향돌파(직전 5≤60·현재 5>60) ∩ 이격 좁음(살짝 위) ∩ 현재가>60선 ∩ 체결강도.
   매도: ①3분봉 60선 이탈(하드·바닥이탈) ②이격≥DEV_TP+1분봉 체결약(꼭지). 당일청산 15:18.
   ★안전: GC560_LIVE=NO면 페이퍼. 그림자(golden_cross_560_shadow)가 전종목 승률 측정.
   ⚠️ 검증 5종목은 선택편향(회복종목)→그림자로 진짜 승률 확인 필수."""
import sys, json, uuid, os
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
import morning_leader_rider_v1 as R   # _cur·_che·_ma_gate·_jload·_jsave·_broker 재사용

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
POS = Path(r"C:\stock_bot\DATA\gc560_positions.json")
LOG = Path(r"C:\stock_bot\data\LOG\golden_cross_560.log")

LIVE       = os.environ.get("GC560_LIVE", "NO").strip().upper() == "YES"
TOPN       = int(os.environ.get("GC560_TOPN", "2"))                       # 동시 진입 수
CAP        = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
GAP_MIN    = float(os.environ.get("GC560_GAP_MIN", "0.2"))               # ★이격 최소: 너무 바닥/flat 크로스(노이즈) 제외·조금 올라온 것만(친구님)
GAP_MAX    = float(os.environ.get("GC560_GAP_MAX", "1.5"))               # 이격 상한: 5선이 60선 위로 이 %이내(살짝 위=바닥초입)
VOL_MULT   = float(os.environ.get("GC560_VOL_MULT", "2.0"))              # ★거래량(체결량) 급증: 크로스봉 거래량≥직전20봉평균×이배(진짜 회복=돈유입)
CHE_BUY    = float(os.environ.get("GC560_CHE", "100"))                   # 진입 체결강도 하한(매수세 확인·가짜크로스 차단)
ENTRY_END  = os.environ.get("GC560_ENTRY_END", "1400")                   # 진입 마감(바닥회복은 장중 아무때나)
EOD_HM     = os.environ.get("GC560_EOD_HM", "1518")
LEADER_TOPN= int(os.environ.get("GC560_LEADER_TOPN", "60"))
MAX_FAIL   = int(os.environ.get("GC560_MAX_FAIL", "2"))                   # [7/2] 매수 주문 실패 최대 재시도. 초과시 오늘 그 종목 스킵(무한 재시도·브로커부하 차단)
# ★[통일 매도 2026-07-02 친구님 "매도전략 진짜 통일"] vol_exit(수급 통합)로 매도 통일. GC560=추세(정배열 위 매수)라 ma20_hard=True(20선 이탈 매도).
UNIFIED_EXIT = os.environ.get("GC560_UNIFIED_EXIT", "YES").strip().upper() == "YES"  # NO=기존 인라인(20선/이격익절) 롤백
MIN_HOLD_SEC = int(os.environ.get("GC560_MIN_HOLD_SEC", "180"))            # 매수후 유예(개장노이즈 성급매도 skip·하드는 무관)
HARD       = float(os.environ.get("GC560_HARD", "5.0"))                    # 하드손절%(기존 GC560엔 없던 하한 추가)
UPTREND    = os.environ.get("GC560_UPTREND", "YES").strip().upper() == "YES"  # ★5/20/60 우상향 게이트(친구님)·롤백 NO
# ★[2026-07-04 친구님 "반전엔진 조건 확인해 적용"] 반전엔진 ⑥거래량↑ 이식: 크로스봉 거래량 > 직전봉(진행중 봉은 3분 환산).
#   백테(che 5일·매도동일): che>=100 단독 257건/승률41.2%/건당+0.21% → +거래량↑ 199건/44.2%/+0.30%(합계 +54.6→+59.1). 롤백 setx GC560_VOL_UP NO.
VOL_UP     = os.environ.get("GC560_VOL_UP", "YES").strip().upper() == "YES"
EXIT_MA    = int(os.environ.get("GC560_EXIT_MA", "20"))                       # ★매도 기준선(친구님 60→20: 60선은 너무 멀어 눌림에 다 토함)
DEV_TP     = float(os.environ.get("GC560_DEV_TP", "10"))                 # 익절 이격문턱
CHE_N      = int(os.environ.get("GC560_CHE_N", "5"))
ACCOUNT    = os.environ.get("SWING_ACCOUNT", "").strip()


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(s + "\n")
    except Exception: pass


def _order(bc, code, qty, side, tag):
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (GC560_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음"); return False
        r = bc.send_order_real(idempotency_key=f"gc560_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"GC560_{side}_{code}", screen_no="9711")
        _st = str((r or {}).get("status", "")).upper()
        _ok = (_st in ("OK", "TIMEOUT")) if side == "BUY" else (_st == "OK")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} status={_st or 'EMPTY'} → {'성공' if _ok else '실패'}")
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _gc560_gap(code):
    """3분봉 5선이 60선을 막 상향돌파(직전봉 5≤60·현재봉 5>60)면 이격%(살짝위) 반환, 아니면 None.
       전일 시드 포함 series로 60선은 장초부터 유효."""
    try:
        import intraday_ma as im
        s = im._series(code)
        if len(s) < 61:
            return None
        def ma(end, w): return sum(s[end - w:end]) / w
        n = len(s)
        m5n, m60n = ma(n, 5), ma(n, 60)
        m5p, m60p = ma(n - 1, 5), ma(n - 1, 60)
        if m5p <= m60p and m5n > m60n:            # ★골든크로스(막 교차)
            return (m5n / m60n - 1) * 100.0
    except Exception:
        pass
    return None


def _vol_surge(bc, code):
    """크로스봉 거래량(체결량) ≥ 직전 20봉평균 × VOL_MULT 면 True. opt10080 3분봉. 실패=True(fail-open)."""
    if not bc:
        return True
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["체결시간", "거래량"], screen_no="9710", timeout_sec=6.0)
        recs = (((r or {}).get("data") or {}).get("records") or [])
        vol = []
        for x in recs[::-1]:                          # 오래된→최근
            try: vol.append(abs(float(str(x.get("거래량", "")).replace(",", ""))))
            except (TypeError, ValueError): vol.append(0.0)
        if len(vol) < 22:
            return True
        avg = sum(vol[-22:-2]) / 20                   # 직전 20봉(형성봉·직전봉 제외) 평균
        recent = max(vol[-2], vol[-1])                # 최근 2봉 중 큰 거래량
        return avg <= 0 or recent >= VOL_MULT * avg
    except Exception:
        return True


def _vol_up(bc, code):
    """[반전엔진 이식] 크로스봉 거래량 > 직전봉. 진행중 봉은 3분 환산(분초반 불공정 보정·reversal VOL_PRORATE 동일). 실패=True(fail-open)."""
    if not bc:
        return True
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["체결시간", "거래량"], screen_no="9711", timeout_sec=6.0)
        recs = (((r or {}).get("data") or {}).get("records") or [])
        rows = []
        for x in recs[::-1]:                          # 오래된→최근
            try:
                rows.append((str(x.get("체결시간", "")), abs(float(str(x.get("거래량", "")).replace(",", "")))))
            except (TypeError, ValueError):
                continue
        if len(rows) < 2:
            return True
        vnow = rows[-1][1]
        ts = rows[-1][0]
        if len(ts) >= 12:                             # 진행중 봉 3분 환산
            bar_min = int(ts[8:10]) * 60 + int(ts[10:12])
            now = datetime.now(); el = (now.hour * 60 + now.minute) - bar_min + 1
            if 1 <= el < 3:
                vnow = vnow * 3.0 / el
        return vnow > rows[-2][1]
    except Exception:
        return True


def _uptrend(c):
    """★친구님 게이트(기존 intraday_ma 계산 재사용): ① 5<20<40<60 역배열 우하향=매수금지 ② 60·20선 우상향(3봉전 대비 상승) 아니면 금지.
       fail-safe: 데이터부족(None)이면 통과(체결강도가 1차게이트)."""
    try:
        import intraday_ma as im
        cl = im._series(c)
        m5, m20, m40, m60 = im._ma_at(cl, 5, 0), im._ma_at(cl, 20, 0), im._ma_at(cl, 40, 0), im._ma_at(cl, 60, 0)
        if None not in (m5, m20, m40, m60) and m5 < m20 < m40 < m60:   # ① 역배열(장기선 우하향) 차단
            return False
        for w in (60, 20):                                            # ② 60·20선 우상향(기울기≥0)
            now, prev = im._ma_at(cl, w, 0), im._ma_at(cl, w, 3)
            if now is not None and prev is not None and now < prev:
                return False
        return True
    except Exception:
        return True


def _signal(bc):
    """진입 후보: 거래대금 대장 ∩ 5/60 골든크로스(이격≤GAP_MAX) ∩ 현재가>60선 ∩ ★5/20/60 우상향·역배열아님 ∩ 체결강도≥CHE_BUY. 이격 좁은 순."""
    out = []
    try:
        import leader_filter as lf
        uni = (lf.leader_list(bc) or [])[:LEADER_TOPN]
    except Exception:
        uni = []
    for c in uni:
        gap = _gc560_gap(c)
        if gap is None or gap < GAP_MIN or gap > GAP_MAX:   # 골든크로스 아님 or 너무 flat(바닥) or 이미 많이 떠버림
            continue
        cur = R._cur(c); ma60 = R._ma_gate(c) if R.MAGATE_PERIOD == 60 else 0
        try:
            import intraday_ma as im; ma60 = float(im.ma(c, 60) or 0)
        except Exception: pass
        if cur <= 0 or ma60 <= 0 or cur < ma60:
            continue
        if UPTREND and not _uptrend(c):            # ★5/20/60 우상향·역배열아님 게이트(친구님)=우하향 골든크로스 페이크 차단
            continue
        che = R._che(c)
        if che is None or che < CHE_BUY:           # 체결강도 확인(가짜크로스 차단)
            continue
        if not _vol_surge(bc, c):                  # ★거래량(체결량) 급증 확인 — 진짜 회복만(노이즈 41→8 컷)
            continue
        if VOL_UP and not _vol_up(bc, c):          # ★[7/4 반전엔진 이식] 크로스봉 거래량>직전봉(백테 승률 41→44%·건당 +0.21→+0.30)
            continue
        out.append((gap, c, cur, ma60, che))
    out.sort()                                     # 이격 작은(바닥 초입) 순
    return out


def _held_now():
    s = set()
    for c, v in R._jload(RT_OPEN).items():
        if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0:
            s.add(str(c).zfill(6))
    return s


def run():
    now_t = datetime.now(); now = now_t.strftime("%H%M"); now_ts = now_t.strftime("%H:%M:%S")
    if now < "0900" or now > "1530":
        return
    bc = R._broker()
    if not bc and LIVE:
        _log("broker dead → 보류"); return
    held = R._jload(POS); today = now_t.strftime("%Y%m%d")

    # ★상한가 익일시가매도(전 전략 공통·limitup_exit 헬퍼)
    try:
        import limitup_exit as LU
    except Exception:
        LU = None
    if LU:                                    # 어제 상한가로 홀드한 포지션 → 오늘 장초 시가 청산
        _ch = False
        for c, p in list(held.items()):
            if isinstance(p, dict) and p.get("status") == "HOLDING" and LU.should_open_sell(p, today, now):
                if _order(bc, c, p["qty"], "SELL", "익일시가매도"):
                    p["status"] = "DONE"; p["exit_reason"] = "익일시가매도(상한가)"; _ch = True
                    _log(f"익일시가매도(상한가) {c} @{R._cur(c):,.0f}")
        if _ch: R._jsave(POS, held)
    # EOD 청산 (★상한가는 당일 안 팔고 익일 시가매도로 유예)
    if now >= EOD_HM:
        for c, p in list(held.items()):
            if isinstance(p, dict) and p.get("status") == "HOLDING" and float(p.get("qty", 0) or 0) > 0:
                if LU and LU.is_limitup(c, R._cur(c)):
                    if not p.get("limitup_hold"):
                        p["limitup_hold"] = True; _log(f"🔒상한가 {c} → 익일 시가매도 유예")
                    continue
                if _order(bc, c, p["qty"], "SELL", "EOD"):
                    p["status"] = "DONE"; p["exit_reason"] = "EOD"
        R._jsave(POS, held); return

    # 보유관리: 60선 이탈 / 이격+체결 익절 (라이더와 동일)
    import intraday_ma as im
    for c, p in list(held.items()):
        if not isinstance(p, dict) or p.get("date") != today or p.get("status") != "HOLDING":
            continue
        cur = R._cur(c); ma60 = float(im.ma(c, 60) or 0); ma_exit = float(im.ma(c, EXIT_MA) or 0)
        if cur <= 0: continue
        che = R._che(c); ch = p.get("che_hist", [])
        if che is not None: ch.append(che); ch = ch[-CHE_N:]; p["che_hist"] = ch
        buy = float(p.get("buy_price", 0) or 0); pnl = (cur / buy - 1) * 100 if buy else 0
        peak = max(float(p.get("peak", cur) or cur), cur); p["peak"] = peak
        # [부분익절 2026-07-02 #3] +PARTIAL_TP%서 절반 익절·나머지 끌기(30만 1주 무동작·1억서 실효).
        try:
            import vol_exit as _VEp
            _VEp.do_partial(p, cur, lambda q, t: _order(bc, c, q, "SELL", t), str(RT_OPEN), _log)
        except Exception:
            pass
        reason = None
        if buy > 0 and pnl <= -HARD:
            reason = f"하드-{HARD:g}"                              # 하드는 유예 무관 항상
        elif UNIFIED_EXIT:
            # [통일 매도 2026-07-02] vol_exit(수급 통합)로 통일. GC560=추세라 ma20_hard=True(20선 이탈 매도). 유예중 성급매도 skip.
            try:
                _age = (now_t - datetime.fromisoformat(p["ts"])).total_seconds() if p.get("ts") else 9999.0
            except Exception:
                _age = 9999.0
            if _age >= MIN_HOLD_SEC:
                try:
                    import vol_exit as VE
                    s, r = VE.decide(c, buy, peak, cur, ma20_hard=True, che=che)
                    if s:
                        reason = r
                except Exception:
                    pass
        else:
            # 기존 인라인(rollback: setx GC560_UNIFIED_EXIT NO)
            if ma_exit > 0 and cur < ma_exit:
                reason = f"{EXIT_MA}선이탈"
            else:
                dev = (cur / ma60 - 1) * 100 if ma60 > 0 else 0
                if dev >= DEV_TP and len(ch) >= CHE_N and all(x < R.CHE_WEAK for x in ch):
                    reason = "이격체결익절"
        if reason and _order(bc, c, p["qty"], "SELL", reason):
            p["status"] = "DONE"; p["exit_reason"] = reason; _log(f"★매도({reason}) {c} @{cur:,.0f} {pnl:+.1f}%")
    R._jsave(POS, held)
    if LIVE:
        rt = R._jload(RT_OPEN); ch2 = False
        for c, p in held.items():
            if isinstance(p, dict) and p.get("status") == "DONE" and c in rt: rt.pop(c, None); ch2 = True
        if ch2: R._jsave(RT_OPEN, rt)

    # 진입
    if now > ENTRY_END:
        return
    open_cnt = sum(1 for v in held.values() if isinstance(v, dict) and v.get("date") == today and v.get("status") == "HOLDING")
    if open_cnt >= TOPN:
        return
    # [전역상한 연결 2026-07-02] GC560이 유일하게 position_budget 미연결이던 구멍 메움(과다매매·하루상한 공유).
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            _log("[전역상한] 진입보류"); return
    except Exception:
        pass
    excl = _held_now()
    ranked = _signal(bc)
    if ranked:
        _log(f"=== GC560 골든크로스 {len(ranked)}종목 (LIVE={LIVE}) ===")
    for gap, c, cur, ma60, che in ranked:
        if open_cnt >= TOPN: break
        # 같은날 재매수 금지. [실패상한 2026-07-02] 실패(FAILED)도 MAX_FAIL 초과면 스킵(무한 재시도 차단).
        if c in excl:
            continue
        _he = held.get(c)
        if isinstance(_he, dict) and _he.get("date") == today:
            if _he.get("status") in ("HOLDING", "DONE"):
                continue
            if _he.get("status") == "FAILED" and int(_he.get("fails", 0)) >= MAX_FAIL:
                continue
        qty = max(1, int(CAP // cur))
        _log(f"★매수(5/60골든) {c} 이격+{gap:.2f}%(살짝위) 체결{che:.0f} @{cur:,.0f} x{qty}")
        if _order(bc, c, qty, "BUY", "진입"):
            # ★[2026-07-02] 매수가 = 실체결가(FID 910). 스냅샷 cur(동시호가 유령값) 앵커 버그 수정.
            _fill = R._fill_price(bc, c, now_t) if LIVE else 0.0
            _bp = _fill if _fill > 0 else cur; _confirmed = bool(_fill > 0)
            if LIVE and not _confirmed:
                _log(f"[FILL-PENDING] {c} 실체결가 미확인 → 임시 스냅샷 @{cur:,.0f}")
            elif LIVE:
                _log(f"[FILL] {c} 실체결가 @{_bp:,.0f} (스냅샷 {cur:,.0f})")
            held[c] = {"code": c, "qty": qty, "buy_price": _bp, "gap560": round(gap, 2),
                       "date": today, "status": "HOLDING", "che_hist": [], "ts": now_t.isoformat(),
                       "fill_confirmed": _confirmed, "buy_price_src": ("FILL" if _confirmed else "SNAP")}
            if LIVE:
                rt = R._jload(RT_OPEN); rt[c] = {"qty": qty, "entry_price": _bp, "code": c, "strategy": "GC560", "peak_price": _bp}
                R._jsave(RT_OPEN, rt)
            open_cnt += 1
        else:
            # [실패상한 2026-07-02] 매수 실패를 매 사이클 무한 재시도하던 것 차단. 실패도 held 기록·MAX_FAIL 초과시 오늘 스킵.
            _fe = held.get(c) if isinstance(held.get(c), dict) else {}
            _fails = (int(_fe.get("fails", 0)) + 1) if _fe.get("date") == today else 1
            held[c] = {"code": c, "date": today, "status": "FAILED", "fails": _fails, "ts": now_t.isoformat()}
            _log(f"[매수실패] {c} 누적{_fails}회" + (f" → 오늘 재시도중단(≥{MAX_FAIL})" if _fails >= MAX_FAIL else ""))
    R._jsave(POS, held)


if __name__ == "__main__":
    try: run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()

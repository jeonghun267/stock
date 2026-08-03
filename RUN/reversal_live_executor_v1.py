# -*- coding: utf-8 -*-
"""[반전 실전 실행기 2026-07-01 친구님 "실전 연결"] 거래량 클라이맥스 바닥반전 실탄·당일치기.
진입: reversal_pattern.detect()=BUY_바닥(급락2.0%→양봉2개→5선위 양봉→40/60안떨어짐) + ★체결강도≥CHE_MIN(매수세·데드캣배제).
매도(친구님 룰): ①20선 이탈 ②체결강도<100(매도심판) ③하드-3% ④EOD 15:18. 재매수 없음·당일청산.
안전: 대장필터·잡주게이트(broker단일점)·전역버짓·CAP30만·TOPN2. 라이더(_cur/_che/_broker/_jload) 재사용.
페이퍼=REVERSAL_LIVE=NO. 실탄 setx REVERSAL_LIVE YES. 롤백 NO.
"""
import os, sys, uuid, time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, r"C:\stock_bot\RUN")
sys.path.insert(0, r"C:\stock_bot\MONITOR")
import morning_leader_rider_v1 as R
import reversal_pattern_shadow_v1 as RP
import intraday_ma as im

LIVE        = os.environ.get("REVERSAL_LIVE", "NO").strip().upper() == "YES"
TOPN        = int(os.environ.get("REVERSAL_TOPN", "2"))
CAP         = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
LEADER_TOPN = int(os.environ.get("REVERSAL_LEADER_TOPN", "60"))
EXIT_MA     = int(os.environ.get("REVERSAL_EXIT_MA", "20"))       # 매도 기준선(친구님 20선)
CHE_EXIT    = float(os.environ.get("REVERSAL_CHE_EXIT", "100"))   # 체결강도 매도심판(<100=매도우위)
HARD        = float(os.environ.get("REVERSAL_HARD", "3.0"))       # 하드손절%
# [매도보강 2026-07-02] MLR_HOLD_ON_CHE와 동일: 20선이탈이라도 매수우위(che≥CHE_EXIT)면 홀드. 롤백 setx REVERSAL_HOLD_ON_CHE NO.
HOLD_ON_CHE = os.environ.get("REVERSAL_HOLD_ON_CHE", "YES").strip().upper() == "YES"
MAX_FAIL    = int(os.environ.get("REVERSAL_MAX_FAIL", "2"))        # [7/2] 매수 주문 실패 최대 재시도(초과시 오늘 그 종목 스킵)
# ★[통일 매도 2026-07-02 친구님 "매도전략 진짜 통일"] vol_exit(수급 통합)로 매도 통일. 반전=바닥매수라 ma20_hard=False(20선 무조건매도 제외).
UNIFIED_EXIT = os.environ.get("REVERSAL_UNIFIED_EXIT", "YES").strip().upper() == "YES"  # NO=기존 인라인(20선/체결약) 롤백
MIN_HOLD_SEC = int(os.environ.get("REVERSAL_MIN_HOLD_SEC", "180"))  # 매수후 유예(개장노이즈 성급매도 skip·하드는 무관)
ENTRY_END   = os.environ.get("REVERSAL_ENTRY_END", "1500")
EOD_HM      = os.environ.get("REVERSAL_EOD_HM", "1518")
POS     = Path(r"C:\stock_bot\data\reversal_positions.json")
RT_OPEN = Path(r"C:\stock_bot\data\rt_open_positions.json")
LOG     = Path(r"C:\stock_bot\data\LOG\reversal_live.log")
_ACC = {"v": None}

# ── [3분봉 디스크 캐시 2026-07-02 친구님 "1분·대장 100종목"] TR 한도(~2건/초) 보호 ─────────
#   3분봉은 3분마다만 갱신 → 종목당 opt10080을 TTL(기본130s) 동안 재사용 → 1분 스캔·100종목도 TR 폭주 없음.
#   진입 판정은 최대 ~130s 지난 봉 허용(3분봉 주기 내라 무해). 매도/manage는 캐시 안 씀(스냅샷 즉시반응).
#   프로세스가 매분 새로 뜨므로 캐시는 디스크(JSON)에 보존. 롤백: setx REVERSAL_BARS_TTL 0 (항상 새 TR).
BARS_CACHE = Path(r"C:\stock_bot\data\reversal_bars3_cache.json")
BARS_TTL   = float(os.environ.get("REVERSAL_BARS_TTL", "130"))
_barsc = {"d": None}


def _bars3_cached(bc, code):
    if _barsc["d"] is None:
        _barsc["d"] = R._jload(BARS_CACHE) or {}
    now = time.time()
    e = _barsc["d"].get(code)
    if isinstance(e, dict) and (now - float(e.get("ts", 0))) <= BARS_TTL and e.get("bars"):
        return e["bars"]
    bars = RP.bars3(bc, code, k=70)
    if bars:
        _barsc["d"][code] = {"ts": now, "bars": bars}
    return bars


def _bars3_cache_save():
    if _barsc["d"] is None:
        return
    now = time.time()
    pruned = {c: e for c, e in _barsc["d"].items()
              if isinstance(e, dict) and (now - float(e.get("ts", 0))) <= 600}
    R._jsave(BARS_CACHE, pruned)


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _order(bc, code, qty, side, tag, live=None):
    # [BUGFIX 2026-07-02] live/paper 불일치 방지: 매도는 '매수시점 live'로 판정(글로벌 LIVE 토글돼도 실포지션은 실매도).
    #   live=None이면 글로벌 LIVE(=매수 기본). 매도 호출측에서 p.get("live") 전달.
    use_live = LIVE if live is None else bool(live)
    if not use_live:
        _log(f"[{tag}][모의] {side} {code} x{qty} (LIVE={use_live})"); return True
    try:
        if not _ACC["v"]:
            ai = bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str):
                accs = [a for a in accs.split(";") if a]
            _ACC["v"] = accs[0] if accs else ""
        if not _ACC["v"]:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"rev_{side.lower()}_{code}_{uuid.uuid4()}", account=_ACC["v"],
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"REV_{side}_{code}", screen_no="9714")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} status={st or 'EMPTY'} → {'성공' if ok else '실패처리'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def run():
    now_t = datetime.now(); now = now_t.strftime("%H%M")
    if now < "0900" or now > "1520":
        return
    bc = R._broker()
    if not bc:
        _log("broker dead → 보류"); return
    today = datetime.now().strftime("%Y%m%d")
    held = R._jload(POS)

    # ===== 매도관리: 20선이탈 / 체결강도<100 / 하드 / EOD =====
    for c, p in list(held.items()):
        if not isinstance(p, dict) or p.get("date") != today or p.get("status") != "HOLDING":
            continue
        cur = R._cur(c)
        if cur <= 0:
            continue
        ma_exit = float(im.ma(c, EXIT_MA) or 0)
        che = R._che(c)
        buy = float(p.get("buy_price", 0) or 0)
        pnl = (cur / buy - 1) * 100 if buy else 0
        peak = max(float(p.get("peak", cur) or cur), cur); p["peak"] = peak
        # [부분익절 2026-07-02 #3] +PARTIAL_TP%서 절반 익절·나머지 끌기(30만 1주 무동작·1억서 실효). EOD 전만.
        if now < EOD_HM:
            try:
                import vol_exit as _VEp
                _VEp.do_partial(p, cur, lambda q, t: _order(bc, c, q, "SELL", t, live=p.get("live", LIVE)), str(RT_OPEN), _log)
            except Exception:
                pass
        reason = None
        if now >= EOD_HM:
            reason = "EOD"
        elif buy > 0 and pnl <= -HARD:
            reason = f"하드-{HARD:g}"                              # 하드는 유예 무관 항상
        elif UNIFIED_EXIT:
            # [통일 매도 2026-07-02] vol_exit(수급 통합)로 통일. 반전=바닥매수→ma20_hard=False(20선 무조건매도 제외·딥V함정회피).
            #   매수우위=끌기·매도우위=5선/고점되밀림/저점이탈. 유예(개장노이즈) 중엔 성급매도 skip.
            try:
                _age = (now_t - datetime.fromisoformat(p["ts"])).total_seconds() if p.get("ts") else 9999.0
            except Exception:
                _age = 9999.0
            if _age >= MIN_HOLD_SEC:
                try:
                    import vol_exit as VE
                    s, r = VE.decide(c, buy, peak, cur, ma20_hard=False, che=che)
                    if s:
                        reason = r
                except Exception:
                    pass
        else:
            # 기존 인라인(rollback: setx REVERSAL_UNIFIED_EXIT NO)
            if ma_exit > 0 and cur < ma_exit and (not HOLD_ON_CHE or che is None or che < CHE_EXIT):
                reason = f"{EXIT_MA}선이탈"
            elif che is not None and che < CHE_EXIT:
                reason = f"체결약{che:.0f}"
        if reason and _order(bc, c, p["qty"], "SELL", reason, live=p.get("live", LIVE)):
            p["status"] = "DONE"; p["exit"] = reason
            _log(f"★매도({reason}) {c} @{cur:,.0f} {pnl:+.1f}%")
    R._jsave(POS, held)
    # [BUGFIX 2026-07-02] 실포지션(live) DONE은 글로벌 LIVE 토글과 무관하게 rt_open 정리
    rt = R._jload(RT_OPEN); ch = False
    for c, p in held.items():
        if isinstance(p, dict) and p.get("status") == "DONE" and c in rt and (p.get("live") or LIVE):
            rt.pop(c, None); ch = True
    if ch:
        R._jsave(RT_OPEN, rt)

    # ===== 진입: 대장 반전 BUY_바닥 + 체결강도 =====
    if now > ENTRY_END:
        return
    open_cnt = sum(1 for v in held.values() if isinstance(v, dict) and v.get("date") == today and v.get("status") == "HOLDING")
    if open_cnt >= TOPN:
        return
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            _log("[전역상한] 진입보류"); return
    except Exception:
        pass
    try:
        import leader_filter as lf
        uni = (lf.leader_list(bc) or [])[:LEADER_TOPN]
    except Exception:
        uni = []
    excl = set()
    for c, p in R._jload(RT_OPEN).items():
        if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0:
            excl.add(str(c).zfill(6))
    _log(f"=== 반전 진입스캔 (LIVE={LIVE} TOPN={TOPN} CAP={CAP:,}) 대장 {len(uni)} ===")
    for code in uni:
        if open_cnt >= TOPN:
            break
        code = str(code).zfill(6)
        # [CHURN FIX 2026-07-02] 오늘 흔적 있는 종목 재진입 차단 (4번째 줄 주석 "재매수 없음" 의도 강제).
        #   ①체결됐던 종목(HOLDING/DONE): 재매수 금지 → 같은사이클 매도후 즉시 재매수 churn 차단(화신정공·인바디·제룡전기).
        #   ②주문 반복실패(FAILED, fails≥MAX): 오늘 재시도 중단 → status=ERROR 무한 재시도 차단(065170 8회·319660 4회).
        if code in excl:
            continue
        _he = held.get(code)
        if isinstance(_he, dict) and _he.get("date") == today:
            if _he.get("status") in ("HOLDING", "DONE"):
                continue
            if _he.get("status") == "FAILED" and int(_he.get("fails", 0)) >= MAX_FAIL:
                continue
        bars = _bars3_cached(bc, code)
        tag, info = RP.detect(bars)
        if not tag or not tag.startswith("BUY"):
            continue
        che = R._che(code)
        if che is None or che < RP.CHE_MIN:      # ★체결강도 확인(매수세·데드캣 배제)
            continue
        cur = R._cur(code)
        if cur <= 0:
            continue
        qty = max(1, int(CAP // cur))
        _log(f"★매수(반전 {tag}) {code} 급락{info.get('move')}% 체결{che:.0f} @{cur:,.0f} x{qty}")
        _t_send = datetime.now()
        if _order(bc, code, qty, "BUY", "진입"):
            # ★[2026-07-02] 매수가 = 실체결가(FID 910). 스냅샷 cur(동시호가 유령값) 앵커 버그 수정.
            _fill = R._fill_price(bc, code, _t_send) if LIVE else 0.0
            _bp = _fill if _fill > 0 else cur; _confirmed = bool(_fill > 0)
            if LIVE and not _confirmed:
                _log(f"[FILL-PENDING] {code} 실체결가 미확인 → 임시 스냅샷 @{cur:,.0f}")
            elif LIVE:
                _log(f"[FILL] {code} 실체결가 @{_bp:,.0f} (스냅샷 {cur:,.0f})")
            held[code] = {"code": code, "qty": qty, "buy_price": _bp, "date": today,
                          "status": "HOLDING", "tag": tag, "live": LIVE, "ts": _t_send.isoformat(),
                          "fill_confirmed": _confirmed, "buy_price_src": ("FILL" if _confirmed else "SNAP")}
            if LIVE:
                rt = R._jload(RT_OPEN)
                rt[code] = {"qty": qty, "entry_price": _bp, "code": code, "strategy": "REVERSAL", "peak_price": _bp}
                R._jsave(RT_OPEN, rt)
            open_cnt += 1
        else:
            # [RETRY-CAP FIX 2026-07-02] 실패(status=ERROR=구조적 거부: 시총/가격/키움거부)한 매수를
            #   매 사이클 무한 재시도(7/2 065170 8회·319660 4회 등)하던 것 차단. 실패도 held에 누적 기록해 MAX_FAIL 초과시 오늘 스킵.
            #   ※브로커 프리징은 TIMEOUT(위에서 성공취급)으로 오므로 이 경로엔 안 옴 → 정상거부만 카운트.
            _fe = held.get(code) if isinstance(held.get(code), dict) else {}
            _fails = (int(_fe.get("fails", 0)) + 1) if _fe.get("date") == today else 1
            held[code] = {"code": code, "date": today, "status": "FAILED", "fails": _fails, "ts": _t_send.isoformat()}
            _log(f"[매수실패] {code} 누적{_fails}회" + (f" → 오늘 재시도중단(≥{MAX_FAIL})" if _fails >= MAX_FAIL else ""))
    _bars3_cache_save()
    R._jsave(POS, held)


if __name__ == "__main__":
    try:
        run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()

# -*- coding: utf-8 -*-
"""
★★★ 잠금(LOCKED) 2026-07-03 — 이 엔진은 폐기됨. 직접 실행 금지. ★★★
사유: FAST_LEADER는 MLR라이더와 진입종목 69% 중복(발산테스트 확인) → 통합 엔진
      unified_leader_v1.py (SAFEPLUS_UNIFIED_LEADER) 로 대체. is_up 경로는 통합의 ②개장로켓 경로로 흡수.
      런처 SAFEPLUS_FAST_LEADER_AM.cmd 는 무력화(LOCKED)됨. 되살리려면 통합 먼저 끄고 런처 원본 복구.
아래는 원본 설계 설명(기록용):
[아침 빠른 대장 라이더 2026-07-02 친구님 "60선 안 기다리고 아침 대장 빨리 잡자"]
문제(126640 화신정공 +24.7% 대장을 아무 엔진도 못 탐): 60선(3분봉 60개=3시간)이 아침엔 안 서고
급등엔 크게 뒤처져 GC560 골든크로스가 12:42(다 끝난뒤)에야 뜸·MLR은 60선이격+진입창10:20이라 놓침.
해결: 60선 대신 '빠른 신호'로 진입 — is_up(5선≥20선 & 현재가>오늘시가) + not_reverse(역배열아님) + 체결강도(매수우위) + 과열상한.
  이 신호는 짧은선(5/20)·현재가>시가라 봉 조금만 있어도 유효 → 09:42~10:00에 화신정공 포착 가능(검증).
청산: 하드손절 → 3분 유예(개장노이즈) → vol_exit(수급·매수우위면 끌기) → EOD. MLR과 동일 철학.
안전: 대장필터·잡주게이트(broker)·전역 daily상한·재매수금지·실패상한. 소액 검증(CAP 10만·TOPN 2).
페이퍼=FASTLDR_LIVE=NO. 실탄 setx FASTLDR_LIVE YES. 시간창 FASTLDR_END(기본 1100·하루종일=1500). 롤백 LIVE NO.
"""
import os, sys, uuid
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")
import morning_leader_rider_v1 as R      # _broker/_cur/_che/_fill_price/_jload/_jsave/RT_OPEN 재사용
import intraday_ma as im

LIVE        = os.environ.get("FASTLDR_LIVE", "NO").strip().upper() == "YES"
TOPN        = int(os.environ.get("FASTLDR_TOPN", "2"))
CAP         = int(float(os.environ.get("FASTLDR_CAP_KRW") or "100000"))   # 소액 검증(10만)
LEADER_TOPN = int(os.environ.get("FASTLDR_LEADER_TOPN", "60"))
CHE_MIN     = float(os.environ.get("FASTLDR_CHE_MIN", "100"))             # 매수우위 하한
OVERHEAT    = float(os.environ.get("FASTLDR_OVERHEAT", "8.0"))            # 과열: 현재가가 20선보다 이 %초과로 뜨면 추격금지(꼭지). 0=끔
RUN_START   = os.environ.get("FASTLDR_START", "0900")
RUN_END     = os.environ.get("FASTLDR_END", "1100")                      # ★진입 마감(아침). 하루종일=1500. 매도는 EOD까지 계속.
EOD_HM      = os.environ.get("FASTLDR_EOD_HM", "1518")
HARD        = float(os.environ.get("FASTLDR_HARD", "3.0"))               # 하드손절%
MIN_HOLD_SEC= int(os.environ.get("FASTLDR_MIN_HOLD_SEC", "180"))         # 매수 후 유예(개장노이즈 성급매도 방지). 유예중 하드는 발동
MAX_FAIL    = int(os.environ.get("FASTLDR_MAX_FAIL", "2"))               # 매수 실패 재시도 상한

import pathlib
POS     = pathlib.Path(r"C:\stock_bot\data\fast_leader_positions.json")
RT_OPEN = R.RT_OPEN
LOG     = pathlib.Path(r"C:\stock_bot\data\LOG\fast_leader_am.log")
_ACC = {"v": None}


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _order(bc, code, qty, side, tag, live=None):
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
        r = bc.send_order_real(idempotency_key=f"fastldr_{side.lower()}_{code}_{uuid.uuid4()}", account=_ACC["v"],
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"FASTLDR_{side}_{code}", screen_no="9722")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} status={st or 'EMPTY'} → {'성공' if ok else '실패처리'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def run():
    now_t = datetime.now(); now = now_t.strftime("%H%M")
    if now < RUN_START or now > EOD_HM:
        return
    bc = R._broker()
    if not bc:
        _log("broker dead → 보류"); return
    today = now_t.strftime("%Y%m%d")
    held = R._jload(POS)

    # ===== 매도관리 (EOD까지 상시): 하드 → 유예 → vol_exit(수급) =====
    for c, p in list(held.items()):
        if not isinstance(p, dict) or p.get("date") != today or p.get("status") != "HOLDING":
            continue
        cur = R._cur(c)
        if cur <= 0:
            continue
        che = R._che(c)
        buy = float(p.get("buy_price", 0) or 0)
        peak = max(float(p.get("peak", cur) or cur), cur); p["peak"] = peak
        pnl = (cur / buy - 1) * 100 if buy else 0
        # [부분익절 2026-07-02 #3] +PARTIAL_TP%서 절반 익절·나머지 끌기(30만 1주는 무동작·1억서 실효). EOD 전만.
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
            reason = f"하드-{HARD:g}"          # 하드는 유예 무관 항상
        else:
            # 유예(개장노이즈) 중이면 vol_exit 성급매도 skip
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
        if reason and _order(bc, c, p["qty"], "SELL", reason, live=p.get("live", LIVE)):
            p["status"] = "DONE"; p["exit_reason"] = reason
            _log(f"★매도({reason}) {c} @{cur:,.0f} {pnl:+.1f}%")
    R._jsave(POS, held)
    # 매도된 live 종목 rt_open 정리
    rt = R._jload(RT_OPEN); ch = False
    for c, p in held.items():
        if isinstance(p, dict) and p.get("status") == "DONE" and c in rt and (p.get("live") or LIVE):
            rt.pop(c, None); ch = True
    if ch:
        R._jsave(RT_OPEN, rt)

    # ===== 진입: 09:00~RUN_END(아침), 빠른 신호 =====
    if now > RUN_END:
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
    # 후보 수집 + 체결강도순 정렬(강한 매수세 우선)
    cands = []
    for code in uni:
        code = str(code).zfill(6)
        if code in excl:
            continue
        he = held.get(code)
        if isinstance(he, dict) and he.get("date") == today:
            if he.get("status") in ("HOLDING", "DONE"):
                continue
            if he.get("status") == "FAILED" and int(he.get("fails", 0)) >= MAX_FAIL:
                continue
        up = im.is_up(code)                 # 5선≥20선 & 현재가>오늘시가 (60선 불필요)
        if up is not True:
            continue
        if not im.not_reverse(code):        # 역배열 우하향 차단
            continue
        che = R._che(code)
        if che is None or che < CHE_MIN:    # 매수우위(실시간)
            continue
        cur = R._cur(code)
        if cur <= 0:
            continue
        if OVERHEAT > 0:                    # 과열: 20선 대비 너무 뜨면 추격금지
            ma20 = float(im.ma20(code) or 0)
            if ma20 > 0 and (cur / ma20 - 1) * 100 > OVERHEAT:
                _log(f"[SKIP-과열] {code} 20선대비 +{(cur/ma20-1)*100:.1f}% > {OVERHEAT:g}%"); continue
        cands.append((che, code, cur))
    cands.sort(reverse=True)                # 체결강도 높은 순
    _log(f"=== 아침대장 진입스캔 (LIVE={LIVE} TOPN={TOPN} CAP={CAP:,}) 대장{len(uni)} 후보{len(cands)} ===")
    for che, code, cur in cands:
        if open_cnt >= TOPN:
            break
        qty = max(1, int(CAP // cur))
        _log(f"★매수(아침대장·빠른신호) {code} 체결{che:.0f} @{cur:,.0f} x{qty}")
        _t_send = datetime.now()
        if _order(bc, code, qty, "BUY", "진입"):
            _fill = R._fill_price(bc, code, _t_send) if LIVE else 0.0
            _bp = _fill if _fill > 0 else cur; _confirmed = bool(_fill > 0)
            if LIVE and not _confirmed:
                _log(f"[FILL-PENDING] {code} 실체결가 미확인 → 임시 @{cur:,.0f}")
            elif LIVE:
                _log(f"[FILL] {code} 실체결가 @{_bp:,.0f} (스냅샷 {cur:,.0f})")
            held[code] = {"code": code, "qty": qty, "buy_price": _bp, "date": today, "status": "HOLDING",
                          "live": LIVE, "ts": _t_send.isoformat(), "peak": _bp,
                          "fill_confirmed": _confirmed, "buy_price_src": ("FILL" if _confirmed else "SNAP")}
            if LIVE:
                rt = R._jload(RT_OPEN)
                rt[code] = {"qty": qty, "entry_price": _bp, "code": code, "strategy": "FASTLDR", "peak_price": _bp}
                R._jsave(RT_OPEN, rt)
            open_cnt += 1
        else:
            _fe = held.get(code) if isinstance(held.get(code), dict) else {}
            _fails = (int(_fe.get("fails", 0)) + 1) if _fe.get("date") == today else 1
            held[code] = {"code": code, "date": today, "status": "FAILED", "fails": _fails, "ts": _t_send.isoformat()}
            _log(f"[매수실패] {code} 누적{_fails}회" + (f" → 오늘 재시도중단(≥{MAX_FAIL})" if _fails >= MAX_FAIL else ""))
    R._jsave(POS, held)


if __name__ == "__main__":
    try:
        run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()

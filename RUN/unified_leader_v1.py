# -*- coding: utf-8 -*-
"""[통합 대장 리더 엔진 — 친구님 2026-07-03 "C안 통합"] MLR라이더 + FAST_LEADER 통합.
배경: 두 엔진(이격기반 MLR / is_up기반 FAST)이 대장 60~100종목에서 69% 중복(발산테스트 확인).
      큰 놈은 둘 다 잡고 진입시각만 다름 → 하나로 합치는 게 커버리지 손실 0 + 타점 빠른쪽 + 중복제거.
설계:
  유니버스 = 대장 top100 (친구님 100종목 유지)
  진입 = che≥100 & 역배열아님 & ( ①강한대장: cur>3분60선 & 이격≤7%  OR  ②개장로켓: is_up(5선≥20선&현재가>시가) & 과열(20선)≤8% )
  랭킹 = che desc(매수세 1순위) → 품질점수 desc(동점가리기)  (품질=MLR_FAST 팩터 재사용, 단 하드필터 없이 가점만=강한 갭업대장도 탈락X)
  청산 = 하드-3% → 3분유예 → vol_exit(수급·매수우위면 끌기) → EOD 15:18  (MLR/FAST와 동일)
  선정 = TOPN 3 · CAP 30만 · 창 09:00~11:00(진입)·매도 EOD까지
안전 = 대장필터·잡주게이트(broker단일점)·전역 daily상한·재매수금지·실패상한·부분익절.
★UNIFIED_LEADER_LIVE=NO(기본)=페이퍼. 실탄 setx UNIFIED_LEADER_LIVE YES. 롤백 NO.
※ 이 엔진 켜면 옛 MLR라이더·FAST_LEADER는 꺼야 함(중복방지).
"""
import os, sys, uuid, pathlib
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
import morning_leader_rider_v1 as R      # _broker/_cur/_che/_fill_price/_jload/_jsave/RT_OPEN
import intraday_ma as im
sys.path.insert(0, r"C:\stock_bot\MONITOR")
import mlr_fast_shadow_v1 as MF          # _bars_today (품질점수용 봉)

LIVE        = os.environ.get("UNIFIED_LEADER_LIVE", "NO").strip().upper() == "YES"
TOPN        = int(os.environ.get("UNIFIED_TOPN", "10"))   # 친구님 2026-07-03: 3→10(적극적·좋은놈 많이). 30만 로테이션이라 과다지출 아님
CAP         = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
LEADER_TOPN = int(os.environ.get("UNIFIED_LEADER_TOPN", "100"))   # ★대장 100종목
SCALP_UNI   = os.environ.get("UNIFIED_SCALP_UNI", "YES").strip().upper() == "YES"  # [7/6 친구님] 유니버스=단타선별(scalp)·기본ON. 끄기(거래대금) setx UNIFIED_SCALP_UNI NO
CHE_MIN     = float(os.environ.get("UNIFIED_CHE_MIN", "100"))     # 매수우위 하한(공통)
DEV_MAX     = float(os.environ.get("UNIFIED_DEV_MAX", "7.0"))     # ①경로: 60선 이격 상한
OVERHEAT    = float(os.environ.get("UNIFIED_OVERHEAT", "8.0"))    # ②경로: 20선 과열 상한
QUAL_MIN    = float(os.environ.get("UNIFIED_QUAL_MIN", "0"))      # 품질 소프트 하한(0=랭킹만·탈락없음)
RUN_START   = os.environ.get("UNIFIED_START", "0900")
RUN_END     = os.environ.get("UNIFIED_END", "1100")              # 진입 마감(아침). 매도는 EOD까지
OPEN_WATCH_MIN = int(os.environ.get("UNIFIED_OPEN_WATCH_MIN", "3"))  # [7/6 친구님] 개장 후 이 분간 매수보류·방향관찰(즉시매수 방지). 0=끔·롤백
_ohh, _omm = int(RUN_START[:2]), int(RUN_START[2:]); _omm += OPEN_WATCH_MIN
_OPEN_GATE = f"{_ohh + _omm // 60:02d}{_omm % 60:02d}"           # 예: 0900+3 → 0903 (이 시각까지 매수보류)
CONV60 = os.environ.get("UNIFIED_CONV60", "YES").strip().upper() == "YES"  # [7/6 친구님] 일봉 5/20/60 수렴+60↑ 경로③(라이브·기본ON·끄기 setx UNIFIED_CONV60 NO)
EOD_HM      = os.environ.get("UNIFIED_EOD_HM", "1518")
# ★[7/5 점검] EOD 매도 재시도 마감. 종전엔 태스크·가드가 딱 15:18에 끝나 EOD 매도 시도가 단 1회 —
#   그 1분에 브로커 문제면 밤새 보유. 3형제와 동일하게 15:25까지 재시도(진입은 RUN_END로 별도 차단·매도규칙 무변경).
#   롤백 setx UNIFIED_HARD_END 1518.
HARD_END    = os.environ.get("UNIFIED_HARD_END", "1525")
HARD        = float(os.environ.get("UNIFIED_HARD", "3.0"))
MIN_HOLD_SEC= int(os.environ.get("UNIFIED_MIN_HOLD_SEC", "180"))
# [7/4 친구님 "통합대장 2회로 늘리자"] 종목당 하루 진입 상한. 170920 검증: 아침 몸털기 컷(-3.1%) 후 재시동(+6.5%)을
# 1회 규칙이 영영 못 잡음 → 2회 허용(하드컷 후 게이트 재성립 시 1회 더). 롤백 setx UNIFIED_MAX_ENTRIES 1.
MAX_ENTRIES = int(os.environ.get("UNIFIED_MAX_ENTRIES", "2"))
MAX_FAIL    = int(os.environ.get("UNIFIED_MAX_FAIL", "2"))
# ★[2026-07-03 친구님] 약장 자동축소: breadth 강하면 풀 TOPN·약하면 자릿수↓(하락장 손실 방어). 0=끔
BREADTH_STRONG = float(os.environ.get("UNIFIED_BREADTH_STRONG", "55"))   # 이상이면 풀 TOPN
BREADTH_WEAK   = float(os.environ.get("UNIFIED_BREADTH_WEAK", "45"))     # 미만이면 최소 TOPN(base//5)
REGIME_F    = r"C:\stock_bot\data\market_regime_std.json"

POS     = pathlib.Path(r"C:\stock_bot\data\unified_leader_positions.json")
RT_OPEN = R.RT_OPEN
LOG     = pathlib.Path(r"C:\stock_bot\data\LOG\unified_leader.log")
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
            _ACC["v"] = (accs[0] if accs else "") or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()  # [7/6] env 폴백(순간 빈응답 방어)
        if not _ACC["v"]:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"unified_{side.lower()}_{code}_{uuid.uuid4()}", account=_ACC["v"],
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"UNIFIED_{side}_{code}", screen_no="9724")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} status={st or 'EMPTY'} → {'성공' if ok else '실패처리'} {((r or {}).get('error') or '')}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _quality(bars, che):
    """품질점수 0~100 (탈락 없음·랭킹/동점용). MLR_FAST 팩터 재사용하되 하드필터 제거."""
    if not bars:
        return 0, "봉없음"
    b0 = bars[0]; o0, c0, v0 = b0[1], b0[4], b0[5]
    last = bars[-1]; cur, lh, ll, lo = last[4], last[2], last[3], last[1]
    vv = sum(((x[2] + x[3] + x[4]) / 3) * x[5] for x in bars); vol = sum(x[5] for x in bars)
    vwap = vv / vol if vol > 0 else 0
    val0 = c0 * v0
    rng = lh - ll; wick = (lh - max(lo, cur)) / rng if rng > 0 else 0
    sc = 0; det = []
    if che is not None and 120 <= che <= 250: sc += 20; det.append("che강")
    elif che is not None and che >= 100:       sc += 10; det.append("che매수우위")
    if vwap > 0 and cur >= vwap:               sc += 20; det.append("VWAP위")
    if wick <= 0.35:                           sc += 20; det.append("윗꼬리ok")
    if val0 >= 10e8:                           sc += 20; det.append("거래대금10억")
    if len(bars) >= 2 and last[5] > bars[-2][5]: sc += 20; det.append("거래량가속")
    return sc, "·".join(det)


def _qualify(code, cur):
    """진입 경로 판정. returns (ok, path, metric) — metric=이격 또는 과열%."""
    # ① 강한대장: cur>3분60선 & 이격 0~DEV_MAX
    try:
        m60 = float(im.ma(code, 60) or 0.0)
    except Exception:
        m60 = 0.0
    if m60 > 0 and cur >= m60:
        dev = (cur / m60 - 1) * 100
        if 0 < dev <= DEV_MAX:
            return True, "강한대장", dev
    # ② 개장로켓: is_up & 과열(20선)≤OVERHEAT
    try:
        up = im.is_up(code) is True
        m20 = float(im.ma20(code) or 0.0)
    except Exception:
        up = False; m20 = 0.0
    if up and m20 > 0:
        over = (cur / m20 - 1) * 100
        if over <= OVERHEAT:
            return True, "개장로켓", over
    # ③ [7/6 친구님] 일봉 5/20/60 수렴 후 60일선 우상향 (che·역배열은 상위 게이트가 이미 확인·백테 대장승률61.6%)
    if CONV60:
        try:
            import daily_conv60 as _DC
            if _DC.is_conv60(code):
                return True, "수렴60", 0.0
        except Exception:
            pass
    return False, "", 0.0


def _breadth():
    import json as _j
    try:
        b = _j.load(open(REGIME_F, encoding="utf-8")).get("breadth")
        if isinstance(b, (int, float)):
            return b * 100 if b <= 1.5 else float(b)
    except Exception:
        pass
    return None


def _eff_topn():
    """약장 자동축소: breadth 강하면 풀·약하면 자릿수↓(하락장 방어). BREADTH_STRONG=0이면 끔."""
    if BREADTH_STRONG <= 0:
        return TOPN
    bd = _breadth()
    if bd is None:
        return TOPN
    if bd >= BREADTH_STRONG:
        return TOPN
    if bd >= BREADTH_WEAK:
        return max(1, TOPN // 2)          # 10→5
    return max(1, TOPN // 5)              # 10→2(최강만)


def run():
    now_t = datetime.now(); now = now_t.strftime("%H%M")
    if now < RUN_START or now > HARD_END:
        return
    bc = R._broker()
    if not bc:
        _log("broker dead → 보류"); return
    today = now_t.strftime("%Y%m%d")
    held = R._jload(POS)

    # ★상한가 익일시가매도(전 전략 공통·limitup_exit 헬퍼)
    try:
        import limitup_exit as LU
    except Exception:
        LU = None
    if LU:                                    # 어제 상한가로 홀드한 포지션 → 오늘 장초 시가 청산
        for c, p in list(held.items()):
            if isinstance(p, dict) and p.get("status") == "HOLDING" and LU.should_open_sell(p, today, now):
                if _order(bc, c, p["qty"], "SELL", "익일시가매도", live=p.get("live", LIVE)):
                    p["status"] = "DONE"; p["exit_reason"] = "익일시가매도(상한가)"
                    _log(f"익일시가매도(상한가) {c} @{R._cur(c):,.0f}")
        R._jsave(POS, held)

    # ===== 매도관리 (EOD까지): 하드 → 3분유예 → vol_exit(수급) =====
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
        if now < EOD_HM:
            try:
                import vol_exit as _VEp
                _VEp.do_partial(p, cur, lambda q, t: _order(bc, c, q, "SELL", t, live=p.get("live", LIVE)), str(RT_OPEN), _log)
            except Exception:
                pass
        reason = None
        if now >= EOD_HM:
            if LU and LU.is_limitup(c, cur):          # ★상한가면 EOD 안 팔고 익일 시가매도 유예
                if not p.get("limitup_hold"):
                    p["limitup_hold"] = True; _log(f"🔒상한가 {c} → 익일 시가매도 유예")
                continue
            reason = "EOD"
        elif buy > 0 and pnl <= -HARD:
            reason = f"하드-{HARD:g}"
        else:
            try:
                _age = (now_t - datetime.fromisoformat(p["ts"])).total_seconds() if p.get("ts") else 9999.0
            except Exception:
                _age = 9999.0
            if _age >= MIN_HOLD_SEC:
                try:
                    import vol_exit as VE
                    s, rr = VE.decide(c, buy, peak, cur, ma20_hard=True, che=che)
                    if s:
                        reason = rr
                except Exception:
                    pass
        if reason and _order(bc, c, p["qty"], "SELL", reason, live=p.get("live", LIVE)):
            p["status"] = "DONE"; p["exit_reason"] = reason
            _log(f"★매도({reason}) {c} @{cur:,.0f} {pnl:+.1f}%")
    R._jsave(POS, held)
    rt = R._jload(RT_OPEN); ch = False
    for c, p in held.items():
        if isinstance(p, dict) and p.get("status") == "DONE" and c in rt and (p.get("live") or LIVE):
            rt.pop(c, None); ch = True
    if ch:
        R._jsave(RT_OPEN, rt)

    # ===== 진입: 09:00~RUN_END =====
    if now > RUN_END:
        return
    topn_eff = _eff_topn()                                  # ★약장이면 자동 축소(10→5→2)
    if topn_eff < TOPN:
        _log(f"[약장 breadth {_breadth()}] TOPN {TOPN}→{topn_eff}")
    open_cnt = sum(1 for v in held.values() if isinstance(v, dict) and v.get("date") == today and v.get("status") == "HOLDING")
    if open_cnt >= topn_eff:
        return
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            _log("[전역상한] 진입보류"); return
    except Exception:
        pass
    uni = []
    if SCALP_UNI:                                     # [7/6 친구님] 거래대금 대신 우리 단타 선별(scalp_score·65조건) 유니버스 사용
        try:
            import json as _j
            _bd = _j.load(open(r"C:\stock_bot\data\daily_leader_board.json", encoding="utf-8"))
            uni = [str(c).zfill(6) for c in (_bd.get("codes") or [])][:LEADER_TOPN]
            if uni: _log(f"유니버스=단타선별(scalp) {len(uni)}종목")
        except Exception:
            uni = []
    if not uni:                                       # 폴백: 단타선별 없으면 거래대금 대장(leader_filter)
        try:
            import leader_filter as lf
            uni = (lf.leader_list(bc) or [])[:LEADER_TOPN]
        except Exception:
            uni = []
    if CONV60:                                        # [7/6 친구님] 수렴60(유동성 통과) 종목을 유니버스에 합침(대장 아니어도 경로③ 발동)
        try:
            import daily_conv60 as _DC
            _cv = [str(c).zfill(6) for c in _DC.codes()]
            if _cv:
                uni = list(dict.fromkeys([str(u).zfill(6) for u in uni] + _cv)); _log(f"수렴60 +{len(_cv)}종목 유니버스 합류(총{len(uni)})")
        except Exception:
            pass
    if OPEN_WATCH_MIN > 0 and now < _OPEN_GATE:      # [7/6 친구님] 개장 관찰창=매수보류(방향확인 대기·매도는 위에서 이미 처리)
        if uni: _log(f"개장 관찰중 {now}<{_OPEN_GATE} — 매수보류(개장 {OPEN_WATCH_MIN}분 방향확인)")
        uni = []
    excl = set()
    for c, p in R._jload(RT_OPEN).items():
        if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0:
            excl.add(str(c).zfill(6))
    cands = []
    for code in uni:
        code = str(code).zfill(6)
        if code in excl:
            continue
        he = held.get(code)
        if isinstance(he, dict) and he.get("date") == today:
            if he.get("status") == "HOLDING":
                continue
            if he.get("status") == "DONE" and int(he.get("buys", 1)) >= MAX_ENTRIES:
                continue                                # 재진입 상한(기본2) 소진
            if he.get("status") == "FAILED" and int(he.get("fails", 0)) >= MAX_FAIL:
                continue
        if not im.not_reverse(code):            # 역배열 우하향 차단(공통)
            continue
        che = R._che(code)
        if che is None or che < CHE_MIN:        # 매수우위(실시간·공통)
            continue
        cur = R._cur(code)
        if cur <= 0:
            continue
        ok, path, metric = _qualify(code, cur)  # ①OR②
        if not ok:
            continue
        bars = None
        try:
            bars = MF._bars_today(bc, code)
        except Exception:
            bars = None
        qsc, qdet = _quality(bars, che)
        if qsc < QUAL_MIN:                       # 소프트 하한(기본0)
            continue
        cands.append((qsc, che, code, cur, path, metric, qdet))
    cands.sort(key=lambda x: (-x[1], -x[0]))     # ★che desc(매수세 1순위) → 품질 desc(동점가리기)
    _log(f"=== 통합대장 진입스캔 (LIVE={LIVE} TOPN={TOPN} CAP={CAP:,}) 대장{len(uni)} 후보{len(cands)} ===")
    for qsc, che, code, cur, path, metric, qdet in cands:
        if open_cnt >= topn_eff:
            break
        qty = max(1, int(CAP // cur))
        # ★[2026-07-06 친구님 "던지기는 피한다·전 전략에·실시간"] 스마트머니 던지기 회피(공용모듈·외국인opt10040+프로그램opt90013)
        try:
            import smart_money as _SM
            _blk, _smi = _SM.dumping(bc, code, cur)
            if _blk:
                _log(f"⛔ 통합대장 {code} 스마트머니 던지기 차단 [{_smi}] — 매수스킵"); continue
        except Exception:
            pass
        mlabel = (f"이격{metric:.1f}%" if path == "강한대장" else f"과열{metric:.1f}%")
        _log(f"★매수(통합·{path}·{mlabel}) {code} 품질{qsc:.0f} che{che:.0f} @{cur:,.0f} x{qty} [{qdet}]")
        _t_send = datetime.now()
        if _order(bc, code, qty, "BUY", "진입"):
            _fill = R._fill_price(bc, code, _t_send) if LIVE else 0.0
            _bp = _fill if _fill > 0 else cur; _confirmed = bool(_fill > 0)
            if LIVE and not _confirmed:
                _log(f"[FILL-PENDING] {code} 실체결가 미확인 → 임시 @{cur:,.0f}")
            elif LIVE:
                _log(f"[FILL] {code} 실체결가 @{_bp:,.0f} (스냅샷 {cur:,.0f})")
            _pb = held.get(code) if isinstance(held.get(code), dict) else {}
            _buys = (int(_pb.get("buys", 0)) + 1) if _pb.get("date") == today else 1
            held[code] = {"code": code, "qty": qty, "buy_price": _bp, "date": today, "status": "HOLDING",
                          "live": LIVE, "ts": _t_send.isoformat(), "peak": _bp, "buys": _buys,
                          "path": path, "quality": qsc, "che": che,
                          "fill_confirmed": _confirmed, "buy_price_src": ("FILL" if _confirmed else "SNAP")}
            if _buys > 1:
                _log(f"  ↻재진입 {_buys}/{MAX_ENTRIES}회차 {code}")
            if LIVE:
                rt = R._jload(RT_OPEN)
                rt[code] = {"qty": qty, "entry_price": _bp, "code": code, "strategy": "UNIFIED", "peak_price": _bp}
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

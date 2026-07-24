# -*- coding: utf-8 -*-
"""[친구님 2026-06-27 완성형 전략 — 페이퍼] 전날 장대양봉+거래대금배수 → 익일 오전10전 베이스 4선 돌파.
   = 눌림없이 급등 잡기(돌파 계열). 우하향(역배열) 원천제거. 백테 EV+0.99%(n22·미확정)→소액 페이퍼 검증.
   ★안전: MBB_LIVE=NO면 모의(주문0)·소액캡·일일캡·종목당1회·충돌배제(rt_open/NEW_PB/돌파/eod/자체)·하드-5·EOD청산.
   충돌배제: 실탄일때만 rt_open에 strategy=MBB(_newpb없음)→NEW_PB _brk_held 자동스킵. 페이퍼는 자체POS만.
"""
import sys, json, uuid, os
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
import prices_1m_reader as _P1M
import pandas as pd

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
RT_OPEN   = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
BRK_POS   = Path(r"C:\stock_bot\DATA\brk_positions.json")
NEWPB_POS = Path(r"C:\stock_bot\DATA\new_pb_positions.json")
EOD_GAP_POS    = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")
MBB_POS = Path(r"C:\stock_bot\DATA\mbb_positions.json")      # 자체 포지션(페이퍼·실탄 공통·manage 대상)
STATE   = Path(r"C:\stock_bot\DATA\mbb_state.json")          # 종목당1회·일일카운트·watchlist 캐시
LOG     = Path(r"C:\stock_bot\data\LOG\mbb_live.log")
SNAP    = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")        # [청산안전망] 보유종목 현재가 fallback
MICRO_WATCH = Path(r"C:\stock_bot\IPC\micro_watch_mbb.json")        # MBB 보유/후보 발행 → broker구독+수집기inject(prices_1m·snapshot 가격확보)

_LIVE_ENV  = os.environ.get("MBB_LIVE", "NO").strip().upper() == "YES"
_LIVE_FROM = os.environ.get("MBB_LIVE_FROM", "20260701")           # ★이 날짜(수)부터만 실탄·그전엔 페이퍼(버그검증)
LIVE = _LIVE_ENV and (datetime.now().strftime("%Y%m%d") >= _LIVE_FROM)   # 월·화=페이퍼, 수~=실탄
CAP  = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or os.environ.get("MBB_CAP_KRW") or "300000"))  # ★통일캡: SAFEPLUS_CAP_KRW 마스터(전 전략 공통·기본30만). 키울땐 이것만.
try:  # [레짐 금액 스케일러 2026-06-29 친구님] 시장 나쁘면 건당 작게(개수는 그대로=작게많이). REGIME_SIZE_SCALE=NO면 1.0(무변경)
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
MAX_BUYS_DAY = int(os.environ.get("MBB_MAX_BUYS", "3"))
MAX_POS      = int(os.environ.get("MBB_MAX_POS", "2"))
MORNING_END  = os.environ.get("MBB_MORNING_END", "1000")           # 오전 이 시각 전만 신규매수
# 전날 강함(screener)
PRIOR_BODY_MIN = float(os.environ.get("MBB_BODY_MIN", "5.0"))       # 전날 (종가-시가)/시가 ≥%
PRIOR_VALMULT  = float(os.environ.get("MBB_VALMULT", "2.0"))       # 전날 거래대금배수(value_ratio) ≥
# 인트라데이(3분봉 4선 베이스 돌파)
CONV_THR = float(os.environ.get("MBB_CONV", "1.5"))                # 1/3/5/10 spread<% = 4선 수렴
# [MA5CROSS 2026-06-29 친구님 "수렴 꼭 아니어도 바닥서 5선 위로 올라서면 매수"] 4선(1/3/5/10) 수렴강제 폐지·5선 턴업 진입.
#   깊은 바닥=큰 pop but dead-cat 위험 → ★체결강도(snapshot)로 진짜만. 정배열 strict 대신 trend(역배열 dead-knife만 차단)+체결강도.
MA5CROSS = os.environ.get("MBB_MA5CROSS", "YES").strip().upper() == "YES"
CHE_MIN  = float(os.environ.get("MBB_CHE_MIN", "100"))            # 바닥 매수 체결강도 하한(snapshot·dead-cat 거름). 0=끔
# [친구님 2026-06-29] MBB=횡보 베이스(4선 만나는 곳)+5선 턴업. 깊은V(5선턴업 안맞음)는 deep_v 담당.
#   4선 수렴은 살리되 빡빡한 1.5%→느슨하게(만나는 곳 유지). 0이면 수렴무관(만나는 곳 무시).
LOOSE_CONV = float(os.environ.get("MBB_LOOSE_CONV", "3.5"))       # MA5CROSS시 4선(1/3/5/10) 느슨수렴 폭%
BASE_WIN = int(os.environ.get("MBB_BASE_WIN", "10"))              # 베이스 횡보 봉수(30분)
BASE_RANGE = float(os.environ.get("MBB_BASE_RANGE", "8.0"))       # 베이스 고저폭<%
MAX_DAYGAIN = float(os.environ.get("MBB_MAX_DAYGAIN", "15.0"))    # 시가대비 이%↑면 추격금지 (실제값은 env MBB_MAX_DAYGAIN로 관리)
# 청산
HARD = float(os.environ.get("MBB_HARD", "5.0"))                   # 하드손절 %
EOD_HM = os.environ.get("MBB_EOD_HM", "1500")

# [CHE-EXIT 2026-06-28 친구님] ★공통 체결강도 매도 — 단계트레일을 체결강도 트레일로 격상(강=넓게/약·급락=타이트). MBB_CHE_EXIT=NO면 단계트레일 폴백.
CHE_EXIT_ON = os.environ.get("MBB_CHE_EXIT", "YES").strip().upper() == "YES"
try:
    import che_exit as _che_mod
    MBB_CHE_PARAMS = _che_mod.default_params("MBB")
    MBB_CHE_PARAMS.update(hard_pct=HARD)
except Exception:
    _che_mod = None; MBB_CHE_PARAMS = None
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()


def _log(m):
    s = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(s + "\n")
    except Exception: pass

def _z(c): return str(c).zfill(6)
def _jload(p, d=None):
    try:
        if Path(p).exists():
            with open(p, encoding="utf-8-sig") as f: return json.load(f)
    except Exception: pass
    return {} if d is None else d
def _jsave(p, obj):
    try:
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e: _log(f"[저장실패] {p}: {e}")

def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None

def _order(bc, code, qty, side, tag):
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (MBB_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"mbb_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"MBB_{side}_{code}", screen_no="9709")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} → {str(r)[:100]}")
        _st = str((r or {}).get("status", "")).upper()
        # [BUGFIX 2026-06-30 #1 비대칭] 매수=OK|TIMEOUT 기록(미체결확인불가→재매수 중복위험 회피)·매도=OK만 완료(비OK는 OPEN유지 재시도)
        if side == "BUY":
            _ok = _st in ("OK", "TIMEOUT")
        else:
            _ok = (_st == "OK")
        if not _ok or _st != "OK":
            _log(f"[{tag}] 주문 status={_st or 'EMPTY'} → " + ("성공" if _ok else "실패처리") + (" (TIMEOUT=체결미확인·수동확인 권장)" if _st == "TIMEOUT" else ""))
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False

def _held_now():
    """충돌배제: rt_open(NEW_PB·돌파·eod)+brk+newpb+eod_gap+eod_pickup+자체 보유 전부 스킵."""
    s = set()
    for f in (RT_OPEN, BRK_POS, NEWPB_POS, EOD_GAP_POS, MBB_POS):
        d = _jload(f)
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and p.get("status", "OPEN") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                    s.add(_z(c))
    # eod_pickup nested {date:{code:pos}}
    d = _jload(EOD_PICKUP_POS)
    if isinstance(d, dict):
        for dt, codes in d.items():
            if isinstance(codes, dict):
                for c, p in codes.items():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                        s.add(_z(c))
    return s

def _watchlist():
    """전날 장대양봉(body≥)+거래대금배수(value_ratio≥)+역배열아님(우하향 원천제거) KOSDAQ. 일자캐시."""
    today = datetime.now().strftime("%Y%m%d")
    st = _jload(STATE)
    if st.get("wl_date") == today and "wl" in st:
        return set(st["wl"])
    wl = []
    try:
        cols = ["date","code","name","market","open","close","value_ratio"]
        e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=cols, low_memory=False, encoding="utf-8-sig")
        e = e[e["market"] == "KOSDAQ"].copy()
        latest = e["date"].max()
        ed = e[e["date"] == latest].copy()
        for col in ("open","close","value_ratio"): ed[col] = pd.to_numeric(ed[col], errors="coerce")
        ed = ed.dropna(subset=["open","close"])
        ed["body"] = (ed["close"]/ed["open"] - 1) * 100
        ed = ed[(ed["body"] >= PRIOR_BODY_MIN) & (ed["value_ratio"] >= PRIOR_VALMULT)]
        cand = [_z(c) for c in ed["code"].tolist()]
        # 역배열(우하향) 제거 — 종가 시계열로 MA5/20/60 ★[7/9 친구님 "이평선은 5/20/60만"] 40선 폐기
        full = e[["date","code","close"]].copy()
        full["close"] = pd.to_numeric(full["close"], errors="coerce")
        from statistics import mean as _mean
        for code in cand:
            cl = full[full["code"] == code].sort_values("date")["close"].dropna().tolist()
            if len(cl) < 60:
                wl.append(code); continue   # 이력부족→포함(보수적이려면 제외도 가능, 일단 포함)
            m5 = _mean(cl[-5:]); m20 = _mean(cl[-20:]); m60 = _mean(cl[-60:])
            if m5 < m20: continue            # ★우하향(단기<중기) 제거
            if m20 < m60: continue           # ★역배열 제거([7/9] 40선 폐기·20<60 두 선)
            wl.append(code)
        _log(f"[WATCHLIST] {latest} 전날 장대양봉(body≥{PRIOR_BODY_MIN:g})+거래대금배수≥{PRIOR_VALMULT:g}+역배열제거 → {len(wl)}종목: {wl[:15]}")
    except Exception as ex:
        _log(f"[WATCHLIST] 실패 {ex} → 빈리스트")
    st["wl_date"] = today; st["wl"] = wl; _jsave(STATE, st)
    return set(wl)

def _bars3(code):
    """중앙 1분봉 → 3분봉 [(hm,o,h,l,c,v)]."""
    b = _P1M.bars(code, log=_log, tag="MBB")
    if not b or len(b) < 14: return None
    b = sorted(b, key=lambda x: x[0]); out = []; i = 0
    while i < len(b):
        g = b[i:i+3]
        out.append((g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g))); i += 3
    return out

def _entry_signal(code):
    """3분봉 4선 베이스 돌파(오전10전). 진입가 or None."""
    from statistics import mean
    b3 = _bars3(code)
    if not b3: return None
    HM=[x[0] for x in b3]; O=[x[1] for x in b3]; H=[x[2] for x in b3]; L=[x[3] for x in b3]; C=[x[4] for x in b3]
    now_hm = datetime.now().strftime("%H%M")
    day_open = O[0]
    if day_open <= 0 or not (1000 <= C[-1] <= 500000): return None
    t = len(b3) - 1                       # 최신 완성 3분봉
    if HM[t] >= MORNING_END: return None  # 오전만
    if t < BASE_WIN: return None
    def sma(n): return mean(C[t-n+1:t+1])
    m1, m3, m5, m10 = C[t], sma(3), sma(5), sma(10)
    if MA5CROSS:
        # [친구님 2026-06-29] ★횡보(4선 1/3/5/10 느슨하게 모임) 중 가격이 5선 위로 올라설 때 = 매수. 체결강도(수급) 확인 필수.
        #   10선 조건 아님. 깊은V(5선턴업 안맞음)는 deep_v가 체결강도로 담당. 여기는 횡보+5선 턴업 전용.
        if LOOSE_CONV > 0 and (max(m1,m3,m5,m10) - min(m1,m3,m5,m10)) / m5 * 100 >= LOOSE_CONV: return None  # 횡보=4선 느슨모임
        m5_prev = mean(C[t-5:t])
        if not (C[t] > m5 and C[t-1] <= m5_prev): return None          # ★5선 아래→위로 올라섬(턴업)
        if C[t] <= C[t-1]: return None                                 # 올라서는 양봉
    else:
        if (max(m1,m3,m5,m10) - min(m1,m3,m5,m10)) / m5 * 100 >= CONV_THR: return None  # 4선 수렴
        base_hi = max(H[t-BASE_WIN:t]); base_lo = min(L[t-BASE_WIN:t])
        if (base_hi - base_lo) / base_lo * 100 >= BASE_RANGE: return None               # 베이스 횡보
        if C[t] <= base_hi or C[t] <= C[t-1]: return None                               # 베이스 위로 돌파
    if C[t] < day_open: return None                                                 # 시가 위(우하향눌림 제거)
    if (C[t]/day_open - 1) * 100 > MAX_DAYGAIN: return None                         # 추격금지
    return float(C[t])

def _name(code):
    try:
        e = pd.read_csv(EOD, dtype={"code": str}, usecols=["code","name"], low_memory=False, encoding="utf-8-sig")
        r = e[e["code"] == _z(code)]
        return str(r["name"].iloc[-1]) if len(r) else code
    except Exception: return code

def _read_che(code):
    """[체결강도] live_micro_snapshot.json의 che_str(FID228). 없으면 None(fail-open)."""
    try:
        d = _jload(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"))
        v = (d.get("codes") or {}).get(_z(code), {})
        c = v.get("che_str")
        return float(c) if c is not None else None
    except Exception:
        return None

def mode_pick():
    hm = datetime.now().strftime("%H%M")
    if hm >= MORNING_END:
        _log(f"{hm} 오전매수 마감({MORNING_END}) — pick skip"); return
    st = _jload(STATE)
    today = datetime.now().strftime("%Y%m%d")
    if st.get("buy_date") != today:
        st["buy_date"] = today; st["buys"] = 0; st["done"] = []
    if st.get("buys", 0) >= MAX_BUYS_DAY:
        _log(f"{hm} 일일 매수캡({MAX_BUYS_DAY}) 도달"); return
    pos_open = {c: p for c, p in _jload(MBB_POS).items() if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0}
    if len(pos_open) >= MAX_POS:
        _log(f"{hm} 동시보유캡({MAX_POS}) 도달"); return
    # [GLOBAL-BUDGET 2026-06-28 친구님] 전 전략 합산 동시보유 상한(MBB는 사이클당 1매수)
    try:
        import position_budget as _gb
        if _gb.budget_on() and _gb.remaining_intraday() <= 0:   # [종가매수 보장 2026-06-29] EOD 예약분 제외
            _log(f"{hm} [GLOBAL-CAP] 전역 실보유 {_gb.total_open()}/{_gb.global_max()} 도달 → 신규매수 보류"); return
    except Exception as _ge:
        _log(f"{hm} [GLOBAL-BUDGET] skip({_ge})")
    wl = _watchlist()
    if not wl:
        _log(f"{hm} watchlist 0 (전날 장대양봉+거래대금배수 종목 없음)"); return
    _write_micro_watch(set(wl) | set(pos_open.keys()))   # 후보+보유 발행 → broker구독+수집기inject(가격확보)
    skip = _held_now() | set(st.get("done", []))
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log(f"{hm} broker 없음 — 실탄 pick skip"); return
    for code in sorted(wl):
        if code in skip: continue
        px = _entry_signal(code)
        if px is None: continue
        # [추세 게이트 2026-06-29] MA5CROSS(바닥 턴업)=trend(역배열 dead-knife만 차단·바닥 허용) / 기존(베이스돌파)=strict 정배열.
        try:
            import trend_filter as _tf
            _jmode = "trend" if MA5CROSS else "strict"
            if not _tf.is_jeongbae(code, _jmode):
                _log(f"{hm} {code} 스킵(추세 {_jmode} 미달)"); continue
        except Exception:
            pass
        # [체결강도 보완 2026-06-29 친구님 "체결량이 보완하지"] 바닥 매수=깊은바닥 dead-cat 위험 → 체결강도로 진짜만(snapshot)
        if MA5CROSS and CHE_MIN > 0:
            _che = _read_che(code)
            if _che is not None and _che < CHE_MIN:
                _log(f"{hm} {code} 체결강도 약({_che:.0f}<{CHE_MIN:.0f})·dead-cat의심 → skip"); continue
        # [FOREIGN-GATE 2026-06-28 친구님] 거래원 외국계 매도우세 게이트(env FOREIGN_GATE: LOG=기록만·BLOCK=보류)
        try:
            import foreign_supply as _fs
            if not _fs.buy_gate(code, log=_log, tag=f"{hm} MBB"):
                continue
        except Exception:
            pass
        qty = max(1, int(CAP // px))
        nm = _name(code)
        _log(f"{hm} ★MBB 매수신호 {code} {nm} @{px:,.0f} x{qty}={qty*px:,.0f}원 (베이스 4선돌파·전날강함)")
        if not _order(bc, code, qty, "BUY", "PICK"): continue
        posrec = {"code": code, "name": nm, "qty": qty, "buy_price": px, "peak": px,
                  "status": "OPEN", "date": today, "live": LIVE, "ts": datetime.now().isoformat()}
        dp = _jload(MBB_POS); dp[code] = posrec; _jsave(MBB_POS, dp)
        if LIVE:
            rt = _jload(RT_OPEN); rt[code] = posrec; _jsave(RT_OPEN, rt)
        st["buys"] = st.get("buys", 0) + 1; st.setdefault("done", []).append(code)
        _jsave(STATE, st)
        break   # 1사이클 1매수
    else:
        _log(f"{hm} 신호없음 (watchlist {len(wl)}·보유/배제 {len(skip)})")

def _write_micro_watch(codes):
    """MBB 보유+후보 코드를 micro_watch_mbb에 기록 → broker 실시간구독(snapshot에 cur 채움)+수집기 inject(prices_1m).
       청산 안전망: 보유종목이 미수집이어도 가격 확보. 실패→무시(기존동작)."""
    try:
        cs = sorted({_z(c) for c in codes if c})
        MICRO_WATCH.parent.mkdir(parents=True, exist_ok=True)
        _jsave(MICRO_WATCH, {"codes": cs, "ts": datetime.now().isoformat()})
    except Exception: pass

def _cur_price(code):
    b = _P1M.bars(code, log=None, tag="MBB")
    if b: return float(b[-1][4])
    # [청산안전망] prices_1m 미수집이면 → live_micro_snapshot의 cur(broker 실시간). 보유종목 청산이 항상 가격 확보.
    try:
        d = _jload(SNAP)
        v = (d.get("codes", {}) if isinstance(d, dict) else {}).get(_z(code), {})
        cur = float(v.get("cur", 0) or 0)
        if cur > 0: return cur
    except Exception: pass
    return 0.0

def _stage_tw(pk): return 7.0 if pk < 10 else 6.0 if pk < 20 else 5.0 if pk < 30 else 4.0

def mode_manage(force_eod=False):
    """보유 청산: 단계트레일(고점-7/6/5/4) + 하드-5 + EOD. 매분 호출."""
    pos = {c: p for c, p in _jload(MBB_POS).items() if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0}
    if not pos: return
    _write_micro_watch(pos.keys())   # 보유종목 계속 발행 → 청산 가격 항상 확보(미수집 방지)
    hm = datetime.now().strftime("%H%M")
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log(f"{hm} broker 없음 — 청산 skip(다음분 재시도)"); return
    _sd = _jload(SNAP); codes_snap = _sd.get("codes", {}) if isinstance(_sd, dict) else {}
    for code, p in list(pos.items()):
        cur = _cur_price(code)
        if cur <= 0:
            # [청산안전망 2026-06-29] 평시엔 skip(micro_watch 재발행→다음분 재시도)·EOD엔 시장가 강제청산(오버나잇 방지)
            if force_eod or hm >= EOD_HM:
                _log(f"{hm} ★EOD강제청산(가격조회실패→시장가) {code} {p.get('name','')} x{int(p['qty'])}")
                if _order(bc, code, int(p["qty"]), "SELL", "SELL"):
                    d = _jload(MBB_POS); d.pop(code, None); _jsave(MBB_POS, d)
                    if LIVE:
                        rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)
            else:
                _log(f"{hm} {code} {p.get('name','')} 현재가 못읽음(prices_1m·snapshot 모두 없음) — 청산보류·micro_watch발행됨 다음분재시도")
            continue
        buy = float(p["buy_price"]); peak = max(float(p.get("peak", buy)), cur)
        if peak != p.get("peak"):
            p["peak"] = peak; dp = _jload(MBB_POS); dp[code] = p; _jsave(MBB_POS, dp)
        pnl = (cur/buy - 1) * 100
        pk_gain = (peak/buy - 1) * 100
        reason = None
        if force_eod or hm >= EOD_HM:
            reason = f"EOD청산 {pnl:+.1f}%"
        elif os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES":
            # [통일 매도 2026-07-01 친구님] 하드손절 유지 → 수급/MA/트레일은 vol_exit(매수우위 보유·매도우위+20선 무조건 매도)
            che = (codes_snap.get(_z(code)) or {}).get("che_str")
            if cur <= buy * (1 - HARD / 100):
                reason = f"하드-{HARD:g}% {pnl:+.1f}%"
            else:
                try:
                    import vol_exit as _VE
                    _s, _r = _VE.decide(code, buy, peak, cur, ma20_hard=True, che=(che if isinstance(che, (int, float)) else None))
                    if _s:
                        reason = f"{_r} {pnl:+.1f}%"
                except Exception:
                    pass
        elif CHE_EXIT_ON and _che_mod is not None:
            che = (codes_snap.get(_z(code)) or {}).get("che_str")
            try:  # [MA-EXIT 공통] 5일선/20일선 청산용 일봉MA (EXIT_MA_LAYER=YES일때만 che_exit가 사용)
                import exit_ma as _DMA; _m5, _m20 = _DMA.ma5(code), _DMA.ma20(code)
            except Exception:
                _m5 = _m20 = 0.0
            sell, rs, tg, _drop, _strong = _che_mod.decide(cur, buy, peak, pnl, che, p.get("che_prev"), MBB_CHE_PARAMS, ma5=_m5, ma20=_m20)
            if che is not None and che != p.get("che_prev"):
                p["che_prev"] = che; dp = _jload(MBB_POS); dp[code] = p; _jsave(MBB_POS, dp)
            if sell:
                reason = f"{rs}·{tg} {pnl:+.1f}%"
        else:   # 폴백: 단계트레일(고점-7/6/5/4)
            tw = _stage_tw(pk_gain)
            hard_line = buy * (1 - HARD/100); trail_line = peak * (1 - tw/100)
            if cur <= hard_line:
                reason = f"하드-{HARD:g}% {pnl:+.1f}%"
            elif pk_gain >= 1.0 and cur <= trail_line:
                reason = f"되밀림[고점-{tw:g}%] {pnl:+.1f}%(고점+{pk_gain:.1f}%)"
        if reason:
            _log(f"{hm} ★매도[{reason}] {code} {p.get('name','')} @{cur:,.0f} x{int(p['qty'])}")
            if _order(bc, code, int(p["qty"]), "SELL", "SELL"):
                d = _jload(MBB_POS); d.pop(code, None); _jsave(MBB_POS, d)
                if LIVE:
                    rt = _jload(RT_OPEN); rt.pop(code, None); _jsave(RT_OPEN, rt)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    _log(f"=== MBB 실행 mode={mode} LIVE={LIVE} CAP={CAP:,} ===")
    if mode == "pick":
        mode_manage(); mode_pick()
    elif mode == "manage":
        mode_manage()
    elif mode == "sell_eod":
        mode_manage(force_eod=True)
    else:
        _log(f"unknown mode {mode}")

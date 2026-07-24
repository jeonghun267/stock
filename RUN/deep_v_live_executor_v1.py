# -*- coding: utf-8 -*-
"""[deep-V 바닥 단타 실전 executor] 친구님 2026-06-26 "소액 실전·오늘 버그잡기".
   신호: 아침 KOSDAQ대장 깊은V(급락-6%↑→바닥→+1%반등) + 5일선이격≤-3(바닥권) + 체결강도≥CHE_BUY(진짜) = ★BUY.
   = 떨어지는中 안삼(반등확인 1번)·이격은 필터(어디)·체결강도는 판별(진짜냐). 위눌림(NEW_PB)과 충돌배제.
   ★안전: DEEPV_LIVE=NO면 모의(주문0)·소액캡·일일매수캡·종목당1회·rt_open held 배제·하드손절·EOD청산.
   주문경로=NEW_PB와 동일 검증된 broker. -X utf8. 실행: ... pick / manage / sell
   충돌배제: 포지션을 rt_open에 strategy=DEEPV(_newpb 없음)로 기록 → NEW_PB의 _brk_held가 자동 스킵(대칭)."""
import sys, json, uuid, os
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")
sys.path.insert(0, r"C:\stock_bot\MONITOR")
import pandas as pd

PRICES_1M = r"C:\stock_bot\data\prices_1m.csv"
SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
MA5_CACHE = Path(r"C:\stock_bot\data\deepv_ma5_cache.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
DEEPV_POS = Path(r"C:\stock_bot\DATA\deepv_positions.json")   # deep-V 자체 포지션(페이퍼·실탄 공통·manage 대상)
EOD_GAP_POS    = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")                    # [CONFLICT 2026-06-30] 종가매수(eod_gap) 보유 — 중복매수 차단
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")   # [CONFLICT 2026-06-30] 종가매수(eod_pickup) 보유 — 중복매수 차단
STATE = Path(r"C:\stock_bot\data\deepv_live_state.json")   # 종목당1회·일일카운트
LOG = Path(r"C:\stock_bot\data\LOG\deep_v_live.log")
THEME_LEAD = Path(r"C:\stock_bot\DATA\theme_leader_top30.json")   # [2026-06-29 친구님] 전일 종가 테마대장 top30(union 감시)

# ── 설정 (env 롤백 가능) ──────────────────────────────────────────────
LIVE = os.environ.get("DEEPV_LIVE", "NO").strip().upper() == "YES"   # 기본 모의(페이퍼)
CAP = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or os.environ.get("DEEPV_CAP_KRW") or "300000"))  # ★통일캡: SAFEPLUS_CAP_KRW 마스터(전 전략 공통·기본30만). 키울땐 이것만.
try:  # [레짐 금액 스케일러 2026-06-29 친구님] 시장 나쁘면 건당 작게(개수는 그대로=작게많이). REGIME_SIZE_SCALE=NO면 1.0(무변경)
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
MAX_BUYS_DAY = int(os.environ.get("DEEPV_MAX_BUYS", "3"))            # 일일 매수 상한(런어웨이 방지)
MAX_POS = int(os.environ.get("DEEPV_MAX_POS", "2"))                  # 동시보유 상한
BUY_CUTOFF = os.environ.get("DEEPV_BUY_CUTOFF", "1030")             # 이 시각 이후 신규매수 금지(아침 단타)
DEEP = float(os.environ.get("DEEPV_DROP", "6.0"))
# [PRIORITY 2026-06-26 친구님] 주연=체결강도(엄격) / 조연=5일선이격(유연).
#   백테근거: 체결강도가 EV 가장 크게 가름(<70 -1.76% → ≥110 +1.03%)·5일선이격은 보조(-0.94→-0.40).
#   체결강도=AND필수(약하면 무조건 거부). 5일선이격=유연(완화·바닥권 근처만 확인, 단독차단 아님).
CHE_BUY = float(os.environ.get("DEEPV_CHE", "115.0"))   # 주연·엄격 (110→115, 진짜 큰손흡수만)
DEV5_GATE = float(os.environ.get("DEEPV_DEV5", "0.0"))  # 조연·유연 (-3→0: 5일선 아래 어디든 OK·바닥권 넓게)
TP_PCT = float(os.environ.get("DEEPV_TP", "5.0"))                    # 익절 +5%(단타)
STOP_PCT = float(os.environ.get("DEEPV_STOP", "5.0"))               # 하드손절 -5%
EOD_HM = os.environ.get("DEEPV_EOD_HM", "1500")
TOPK = 30; EOK_MIN = 30.0; DROP_WIN = 40; WAIT_MAX = 60; BOUNCE = 1.0
FRESH_MIN = int(os.environ.get("DEEPV_FRESH_MIN", "6"))   # 반등 신선도(분). 테스트시 크게.
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()

# [CHE-EXIT 2026-06-28 친구님] ★공통 체결강도 매도 통합 — 고정 +5%/-5% → 체결강도 꼭지점 매도.
#   강하면 끌고(더먹기)·약하거나 급락이면 익절. DEEPV_CHE_EXIT=NO면 기존 고정룰 폴백.
CHE_EXIT_ON = os.environ.get("DEEPV_CHE_EXIT", "YES").strip().upper() == "YES"
WICK_ON = os.environ.get("DEEPV_WICK_EXIT", "YES").strip().upper() == "YES"   # [2026-06-29 친구님] 음봉+긴윗꼬리 매도
try:
    import che_exit as _che_mod
    DEEPV_CHE_PARAMS = _che_mod.default_params("DEEPV")
    DEEPV_CHE_PARAMS.update(hard_pct=STOP_PCT, tp_cap=TP_PCT, che_strong=CHE_BUY)   # 진입문턱과 정합
    DEEPV_CHE_PARAMS.update(retr_wide=float(os.environ.get("DEEPV_RETR_WIDE", "3.0")),     # [2026-06-29 친구님] 강일때 트레일 폭(고점-%)·좁힐수록 꼭지근처 익절(되돌림 덜 토함)
                            retr_tight=float(os.environ.get("DEEPV_RETR_TIGHT", "1.2")))   # 약/만족일때 트레일 폭
    if WICK_ON:
        DEEPV_CHE_PARAMS.update(wick_min=float(os.environ.get("DEEPV_WICK_MIN", "0.6")),   # 윗꼬리 비율(범위대비) 이상=긴꼬리
                                wick_arm=float(os.environ.get("DEEPV_WICK_ARM", "0.0")))    # 이 수익%↑에서만 발동(0=수익무관 무조건)
except Exception:
    _che_mod = None; DEEPV_CHE_PARAMS = None


def _log(m):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {} if d is None else d


def _jsave(p, obj):
    try:
        pp = Path(p); pp.parent.mkdir(parents=True, exist_ok=True)
        tmp = pp.with_suffix(pp.suffix + ".tmp")    # [원자적쓰기 2026-06-29] 임시파일→os.replace = 쓰기중 크래시시 손상방지
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, pp)
    except Exception as e:
        _log(f"저장실패 {p}: {e}")


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag):
    # ★[2026-07-01 대장주 순위표 게이트] 딥V도 전날 종가 대장주 순위표 안의 종목만 급락매수
    #   (역배열 급락이라도 '거래대금 대장'만 = 잡주 낙폭과대 회피). board 없으면 fail-open.
    #   딥V는 예외두고 싶으면 롤백: setx DEEPV_LEADER_BOARD NO
    if side == "BUY" and os.environ.get("DEEPV_LEADER_BOARD", "YES").strip().upper() == "YES":
        try:
            import leader_filter as _lf
            if not _lf.is_leader(bc, code):
                _log(f"[{tag}][대장외] {code} 전날 순위표 밖 → 매수차단"); return False
        except Exception:
            pass
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (DEEPV_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"deepv_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"DEEPV_{side}_{code}", screen_no="9706")
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


def _eod_held():
    """[CONFLICT 2026-06-30 ★누락보강] 종가매수분(eod_gap·eod_pickup) 보유 종목 set — deep-V가 같은종목 중복매수 차단.
       종가매수=오버나잇이라 deep-V 매수창(09:00~10:30)에 전일 종가매수분이 살아있을 수 있음(돌파/NEW_PB엔 6/27 적용·deep_v 누락).
       OPEN+qty>0만. eod_pickup은 nested{날짜:{코드:pos}}라 최근7일 날짜키만(stale 배제). env CONFLICT_EXCLUDE_EOD=NO로 끔."""
    if os.environ.get("CONFLICT_EXCLUDE_EOD", "YES").strip().upper() != "YES":
        return set()
    s = set()
    try:
        d = _jload(EOD_GAP_POS)   # flat {code:pos}
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                    s.add(str(c).zfill(6))
    except Exception:
        pass
    try:
        d = _jload(EOD_PICKUP_POS)   # nested {date:{code:pos}}
        if isinstance(d, dict):
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            for dt, codes in d.items():
                if not (isinstance(dt, str) and dt.isdigit() and dt >= cutoff and isinstance(codes, dict)):
                    continue
                for c, p in codes.items():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                        s.add(str(c).zfill(6))
    except Exception:
        pass
    return s


def _held_now():
    """충돌배제 대상 = rt_open 전체 보유(NEW_PB·돌파) + deep-V 자체 보유 + 종가매수분(eod). 전부 스킵."""
    s = set()
    for f in (RT_OPEN, DEEPV_POS):
        d = _jload(f)
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0:
                    s.add(str(c).zfill(6))
    s |= _eod_held()   # [BUGFIX 2026-06-30 #3] 종가매수 오버나잇 포지션 중복매수 차단
    return s


def _snapshot():
    d = _jload(SNAP)
    return d.get("codes", {}) if isinstance(d, dict) else {}, (d.get("ts", "") if isinstance(d, dict) else "")


def _safe_float(x, default=0.0):
    """[BUGFIX 2026-06-30 #6] 스냅샷 che_str가 문자열 등 비숫자여도 안전 변환(che_exit.decide의 비교 TypeError 방지)."""
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


# ── [반전 매수 로직 2026-07-01 친구님/GPT] '떨어지는 칼' 대신 '급락 → 첫 강한 양봉 → 직전 음봉 고가 돌파' ──
#   핵심 3조건만(과도한 필터 금지=좋은종목 놓침 방지·둔화/몸통축소 필터는 뺌):
#   ① 급락 후 저점(상단 dip 로직 유지) ② 첫 강한 양봉+거래량 증가 ③ 직전 음봉 고가 돌파 → 즉시 매수.
#   ★③(직전 음봉 고가 돌파)가 '칼이 멈추고 돌아섰다'를 증명 → 반전 확인 자체가 falling-knife 필터.
#   → 역배열·비구독(체결강도 못읽는) 급락주도 매수가능(REV_CHE_SOFT). 롤백: setx DEEPV_REVERSAL NO.
REVERSAL_ON  = os.environ.get("DEEPV_REVERSAL", "YES").strip().upper() == "YES"
REV_BODY_MIN = float(os.environ.get("DEEPV_REV_BODY", "0.4"))       # ② 강한 양봉: 몸통 ≥ 이 %(시가대비)
REV_VOL_MULT = float(os.environ.get("DEEPV_REV_VOL_MULT", "1.2"))   # ② 거래량 증가: 반전봉 거래량 ≥ 직전평균×배수
REV_LOOKBACK = int(os.environ.get("DEEPV_REV_LOOKBACK", "4"))       # ③ 직전 음봉 탐색 범위(봉)
REV_CHE_SOFT = os.environ.get("DEEPV_REV_CHE_SOFT", "YES").strip().upper() == "YES"  # 반전확인시 체결강도 소프트(못읽어도 통과)
CHE_SOFT_MIN = float(os.environ.get("DEEPV_CHE_SOFT_MIN", "100.0")) # 체결강도 읽히면 이 값 이상만(소프트문턱)


def _reversal_confirm(O, Hh, Lo, C, V, t):
    """반전봉 판정(핵심 3조건): t=현재봉. ②강한 양봉+거래량 증가 ③직전 음봉 고가 돌파. 반환 (ok, why)."""
    if t < 2:
        return False, "봉부족"
    o, c = float(O[t]), float(C[t])
    if o <= 0 or not (c > o):
        return False, "양봉아님"
    body = (c - o) / o * 100.0
    if body < REV_BODY_MIN:                        # ② 첫 강한 양봉
        return False, f"양봉약함({body:.2f}%)"
    # ② 거래량 증가 — 반전봉 거래량 ≥ 직전 몇봉 평균×배수 (데이터 없으면 통과=과필터 방지)
    try:
        prevv = [float(V[k]) for k in range(max(t - REV_LOOKBACK, 0), t) if float(V[k]) > 0]
        if prevv and float(V[t]) < (sum(prevv) / len(prevv)) * REV_VOL_MULT:
            return False, "거래량부족"
    except Exception:
        pass
    # ③ 직전 '음봉'의 고가 돌파(종가 기준) = '칼이 멈추고 돌아섰다'
    pj = None
    for k in range(t - 1, max(t - 1 - REV_LOOKBACK, -1), -1):
        if C[k] < O[k]:
            pj = k; break
    if pj is None:
        return False, "직전음봉없음"
    if not (c > float(Hh[pj])):
        return False, "직전음봉고가미돌파"
    return True, f"반전OK(몸통{body:.2f}%·거래량↑·직전고가돌파)"


def find_buy_signals():
    """실시간 ★BUY 후보: 깊은V 바닥 + '첫 반전봉'(둔화→강한양봉→직전고가돌파) + 이격바닥권. 반환 [(code,px,dev5,che,drop)]."""
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str},
                         usecols=["code", "ts", "open", "high", "low", "close", "volume"])
    except Exception as e:
        _log(f"prices_1m 읽기실패 {e}"); return []
    df = df[(df["ts"].str.len() == 14) & (~df["code"].isin(["U001", "U201"]))].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) == 0:
        return []
    df["hm"] = df["ts"].str[8:12]
    df = df.sort_values(["code", "ts"])
    val = (df.assign(v=df["close"] * df["volume"]).groupby("code")["v"].sum() / 1e8)
    leaders = set(val[val >= EOK_MIN].sort_values(ascending=False).head(TOPK).index)
    # [테마대장 연결 2026-06-29 친구님] 전일 종가 테마대장 top30 union(오늘 거래대금top30 ∪ 전일테마대장)
    #   → 오늘 움직이는 놈(006920식) 유지 + 전일 테마대장도 감시. fail-safe(파일없으면 기존동작).
    try:
        _tl = _jload(THEME_LEAD)
        if isinstance(_tl, dict):
            _tlc = {str(c).zfill(6) for c in (_tl.get("codes") or [])}
            if _tlc:
                leaders |= _tlc
                _log(f"[UNIVERSE] 전일테마대장 {len(_tlc)} union → 감시 {len(leaders)}종목")
    except Exception:
        pass
    snap, snap_ts = _snapshot()
    try:
        now_hm = int(snap_ts[11:13]) * 60 + int(snap_ts[14:16])
    except Exception:
        now_hm = int(datetime.now().strftime("%H")) * 60 + int(datetime.now().strftime("%M"))
    ma5 = _jload(MA5_CACHE).get("ma5", {})
    out = []
    for code, g in df.groupby("code"):
        if code not in leaders:
            continue
        O = g["open"].values; Hh = g["high"].values; Lo = g["low"].values; C = g["close"].values
        Vv = g["volume"].values; HM = g["hm"].values
        n = len(C)
        if n < 12:
            continue
        leg = Hh[0]; lj = 0; dip = False; Lb = None; Lbj = None
        for t in range(1, n):
            if not dip:
                if Hh[t] > leg: leg = Hh[t]; lj = t
                if Lo[t] <= leg * (1 - DEEP / 100) and (t - lj) <= DROP_WIN:
                    dip = True; Lb = Lo[t]; Lbj = t
            else:
                if Lo[t] < Lb: Lb = Lo[t]; Lbj = t
                if (t - Lbj) > WAIT_MAX:
                    break
                # [반전 매수 2026-07-01 친구님/GPT] 바닥 이후 '첫 반전봉'만 매수(떨어지는 칼 금지).
                #   REVERSAL_ON=NO면 기존 '+1% 반등'(BOUNCE) 폴백.
                if REVERSAL_ON:
                    rev_ok, rev_why = _reversal_confirm(O, Hh, Lo, C, Vv, t)
                else:
                    rev_ok = C[t] >= Lb * (1 + BOUNCE / 100); rev_why = "bounce+1%"
                if not rev_ok:
                    continue
                try:
                    thm = int(HM[t][:2]) * 60 + int(HM[t][2:])
                except Exception:
                    thm = -999
                fresh = 0 <= (now_hm - thm) <= FRESH_MIN
                m5 = ma5.get(code)
                dev5 = (Lb / m5 - 1) * 100 if m5 else None
                che = snap.get(code, {}).get("che_str")
                che_num = isinstance(che, (int, float))
                # [체결강도] 반전 확인시=소프트(못읽어도 통과·읽히면 CHE_SOFT_MIN↑)=역배열 비구독 급락주 극복.
                #   반전 미사용(폴백)시=기존 엄격(≥CHE_BUY 필수).
                if REVERSAL_ON and REV_CHE_SOFT:
                    che_ok = (not che_num) or che >= CHE_SOFT_MIN
                else:
                    che_ok = che_num and che >= CHE_BUY
                dev5_ok = (dev5 is None) or (dev5 <= DEV5_GATE)   # 조연: None통과·바닥권만
                if fresh and che_ok and dev5_ok:
                    out.append((code, float(C[t]), (round(dev5, 1) if dev5 is not None else None),
                                (float(che) if che_num else 0.0), round((leg - Lb) / leg * 100, 1)))
                break
    return out


def mode_pick():
    hm = datetime.now().strftime("%H%M")
    if hm >= BUY_CUTOFF:
        _log(f"[PICK] 매수마감({BUY_CUTOFF}) 지남 hm={hm} → skip"); return
    st = _jload(STATE)
    today = datetime.now().strftime("%Y%m%d")
    if st.get("date") != today:
        st = {"date": today, "bought": [], "count": 0}
    if st["count"] >= MAX_BUYS_DAY:
        _log(f"[PICK] 일일매수상한({MAX_BUYS_DAY}) 도달 → skip"); return
    held = _held_now()
    npos = len([c for c in held])  # 보유총량(충돌배제 기준)
    sigs = find_buy_signals()
    if not sigs:
        _log("[PICK] ★BUY 신호 없음 → HOLD"); return
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("[PICK] broker dead → 매수보류"); return
    sigs.sort(key=lambda x: -x[3])  # 체결강도 강한 순
    # [GLOBAL-BUDGET 2026-06-28 친구님] 전 전략 합산 동시보유 상한
    _grem = 9999; _gbought = 0
    try:
        import position_budget as _gb
        if _gb.budget_on():
            try:
                _grem = _gb.remaining_intraday()   # [종가매수 보장 2026-06-29] EOD 예약분 제외한 잔여
            except Exception as _re:
                _grem = 0   # [BUGFIX 2026-06-30] 캡 ON인데 잔여 읽기 실패 → 보수적 차단(fail-closed)
                _log(f"[GLOBAL-BUDGET] remaining 읽기실패 → 매수보류(fail-closed): {_re}")
            if _grem <= 0:
                _log(f"[PICK] [GLOBAL-CAP] 전역 잔여슬롯 0/오류 → 매수보류"); return
    except Exception as _ge:
        _log(f"[GLOBAL-BUDGET] 모듈불가 → 로컬캡(MAX_POS/MAX_BUYS_DAY)만 적용: {_ge}")
    for code, px, dev5, che, drop in sigs:
        if st["count"] >= MAX_BUYS_DAY:
            break
        if _gbought >= _grem:
            _log(f"[PICK] [GLOBAL-CAP] 전역 잔여슬롯 소진 → 신규중단"); break
        if code in held or code in st["bought"]:
            _log(f"[PICK] {code} 스킵(이미보유/금일매수 — 충돌배제)"); continue
        cur_deepv = _deepv_count()
        if cur_deepv >= MAX_POS:
            _log(f"[PICK] deep-V 동시보유상한({MAX_POS}) → skip"); break
        # [딥 예외 2026-06-29 친구님 "답은 예외"] ★deep_v(깊은딥)는 정배열 게이트 '예외' — 정배열 안 따지고 딥 잡음.
        #   딥은 본질적으로 역배열·횡보권 급락에서 발생(86% 역배열장). falling-knife 필터=실시간 체결강도(≥CHE). 나머지 전략은 전부 strict 정배열만.
        #   예외 끄고 딥에도 정배열 걸려면 setx DEEPV_JEONGBAE_GATE YES.
        if os.environ.get("DEEPV_JEONGBAE_GATE", "NO").strip().upper() == "YES":
            try:
                import trend_filter as _tf
                if not _tf.is_jeongbae(code, "strict"):
                    _log(f"[PICK] {code} 스킵(정배열 아님)"); continue
            except Exception:
                pass
        # [FOREIGN-GATE 2026-06-28 친구님] 거래원 외국계 매도우세 게이트(env FOREIGN_GATE: LOG=기록만·BLOCK=보류)
        try:
            import foreign_supply as _fs
            if not _fs.buy_gate(code, log=_log, tag="[PICK] DEEPV"):
                continue
        except Exception:
            pass
        qty = max(1, int(CAP // px))
        _d5 = f"{dev5}%" if dev5 is not None else "N/A"
        _log(f"★DEEPV ★BUY {code} @{px:,.0f} x{qty}={qty*int(px):,}원 [깊은V-{drop}%·이격{_d5}·체결{che:.0f}강] ({st['count']+1}/{MAX_BUYS_DAY})")
        if not _order(bc, code, qty, "BUY", "PICK"):
            if LIVE: continue
        st["bought"].append(code); st["count"] += 1; _gbought += 1
        posrec = {"qty": qty, "entry_price": px, "code": code, "strategy": "DEEPV",
                  "peak_price": px, "stop_price": round(px * (1 - STOP_PCT / 100)),
                  "tp_price": round(px * (1 + TP_PCT / 100)), "buy_hm": hm,
                  "live": LIVE, "ts": datetime.now().isoformat()}
        dpos = _jload(DEEPV_POS); dpos[code] = posrec; _jsave(DEEPV_POS, dpos)
        if LIVE:   # 실탄일 때만 rt_open 기록(_newpb 없음→NEW_PB _brk_held 자동배제·매도엔진 인지). 페이퍼는 실파일 안건드림
            rt = _jload(RT_OPEN); rt[code] = posrec; _jsave(RT_OPEN, rt)
        held.add(code)
    _jsave(STATE, st)


def _deepv_count():
    d = _jload(DEEPV_POS)
    return len([c for c, p in d.items() if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0])


def _cur_price(code):
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str}, usecols=["code", "ts", "close"])
        g = df[df["code"] == code].sort_values("ts")
        if len(g): return float(g["close"].iloc[-1])
    except Exception:
        pass
    # [청산안전망 2026-06-27] prices_1m 미수집이면 → live_micro_snapshot의 cur(broker 실시간). 보유종목 청산 항상 가격확보.
    try:
        snap, _ = _snapshot()
        cur = float(snap.get(code, {}).get("cur", 0) or 0)
        if cur > 0: return cur
    except Exception:
        pass
    return 0.0


def _cur_bar(code):
    """최근 1분봉 OHLC (음봉/윗꼬리 판정용). 없으면 None. [2026-06-29 친구님]"""
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str},
                         usecols=["code", "ts", "open", "high", "low", "close"])
        g = df[df["code"] == code].sort_values("ts")
        if len(g):
            r = g.iloc[-1]
            return (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
    except Exception:
        pass
    return None


# ── [체결량 홀드 청산 2026-07-01 친구님] "이평선 아니라 체결량으로 끌고 간다" ────────────────
#   체결량(거래량) 살아있으면 보유(가격 빠져도)·죽으면(<최근N분평균)+가격하락/장대음봉/저점이탈=매도.
#   핵심: "가격만 빠졌다고 팔지 말고, 체결량이 죽었을 때 팔아라." 하드손절-5%·EOD는 항상 별도 우선.
#   백테(6/22~7/1 190건): 손익비 0.71→1.30 개선(승자끌기·패자컷). 롤백 setx DEEPV_VOL_EXIT NO(→che_exit).
VOL_EXIT_ON = os.environ.get("DEEPV_VOL_EXIT", "YES").strip().upper() == "YES"
VOL_WIN     = int(os.environ.get("DEEPV_VOL_WIN", "5"))        # 최근 N분 거래량 평균
VOL_PKDROP  = float(os.environ.get("DEEPV_VOL_PKDROP", "2.5")) # 고점대비 하락 매도문턱%
VOL_BIGRED  = float(os.environ.get("DEEPV_VOL_BIGRED", "2.0")) # 장대음봉 몸통%


def _recent_bars(code, k=8):
    """최근 k개 1분봉 (o,h,l,c,v) 리스트(과거→현재). 없으면 []."""
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str},
                         usecols=["code","ts","open","high","low","close","volume"])
        g = df[df["code"] == code].sort_values("ts").tail(k)
        out = []
        for r in g.itertuples(index=False):
            out.append((float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)))
        return out
    except Exception:
        return []


def _vol_hold_decide(code, entry, peak, cur):
    """체결량 홀드 판정. 반환 (sell, reason, tag). 하드손절/EOD는 호출측 별도 처리."""
    bars = _recent_bars(code, VOL_WIN + 2)
    if len(bars) < 2:
        return False, None, ""                        # 데이터부족 → 보유(하드손절은 별도)
    o, h, l, c, v = bars[-1]
    prev_l = bars[-2][2]
    hist = [b[4] for b in bars[:-1] if b[4] > 0][-VOL_WIN:]
    vol_ma = (sum(hist) / len(hist)) if hist else 0.0
    # [구조붕괴=체결량 무관 즉시매도 2026-07-01] 장대음봉·직전저점이탈은 투매(고거래량)라도 판다.
    #   백테: 게이트(체결량죽음일때만)보다 독립발화가 손익비 1.29→1.38 우수(패닉 장대음봉 안 맞음).
    if c < o and o > 0 and (o - c) / o * 100 >= VOL_BIGRED:
        return True, "TRAIL", f"장대음봉{(o-c)/o*100:.1f}%"
    if cur < prev_l:
        return True, "TRAIL", "직전저점이탈"
    # [체결량 홀드] 살아있으면 보유(가격 빠져도) ← 핵심: 가격만 빠졌다고 안 판다
    if vol_ma > 0 and v >= vol_ma:
        return False, None, "체결량유지=보유"
    # 체결량 죽음 → 고점대비 하락 매도
    dp = (cur / peak - 1) * 100 if peak else 0.0
    if dp <= -VOL_PKDROP:
        return True, "TRAIL", f"체결량죽음+고점{dp:.1f}%"
    return False, None, ""


def mode_manage(force_eod=False):
    """deep-V 보유종목 청산관리: ★체결강도 매도(che_exit 공통) + EOD. (매분 호출)
       [CHE-EXIT 2026-06-28] 강하면 끌고·약/급락이면 익절 → 꼭지점 더 먹기. DEEPV_CHE_EXIT=NO면 고정룰 폴백."""
    allpos = _jload(DEEPV_POS)
    deepv = {c: p for c, p in allpos.items() if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0}
    if not deepv:
        return
    hm = datetime.now().strftime("%H%M")
    bc = _broker() if LIVE else None
    if LIVE and not bc:
        _log("[MANAGE] broker dead → 청산보류"); return
    codes_snap, _ = _snapshot()
    dirty = False
    for code, p in list(deepv.items()):
      try:   # [BUGFIX 2026-06-30 #4] per-종목 격리 — 한 종목 레코드 오류가 나머지 보유 전체 청산을 막지 않도록
        entry = float(p["entry_price"]); qty = int(p["qty"])
        cur = _cur_price(code)
        if cur <= 0:
            # [청산안전망 2026-06-29] 가격 2단폴백(prices_1m·snapshot) 다실패: 평시엔 skip(다음분 재시도)·
            #   EOD엔 시장가(_order hoga06·price0) 강제청산 → 가격불명으로 오버나잇 방치 방지.
            if force_eod or hm >= EOD_HM:
                _log(f"[MANAGE] ★EOD강제청산(가격조회실패→시장가) {code} x{qty}")
                if _order(bc, code, qty, "SELL", "MANAGE"):
                    allpos.pop(code, None); _jsave(DEEPV_POS, allpos); dirty = True   # [#5] 매도 즉시저장(중간크래시 재매도 방지)
                    if LIVE:
                        rt2 = _jload(RT_OPEN); rt2.pop(code, None); _jsave(RT_OPEN, rt2)
            continue
        pnl = (cur / entry - 1) * 100
        peak = max(float(p.get("peak_price", entry) or entry), cur)
        if peak != p.get("peak_price"):
            p["peak_price"] = peak; dirty = True
        reason = None; tag = ""
        if force_eod or hm >= EOD_HM:
            reason = "EOD"; tag = f"EOD청산 {pnl:+.1f}%"
        elif VOL_EXIT_ON:
            # [통일 매도 2026-07-01 친구님] 하드손절 최우선 → vol_exit(수급 매수/매도 우위). ★딥V=역배열 매수라 20선 안전장치 제외(ma20_hard=False).
            if cur <= entry * (1 - STOP_PCT / 100):
                reason = "STOP"; tag = f"하드손절 {pnl:+.1f}%"
            else:
                try:
                    import vol_exit as _VE
                    _che_now = _safe_float((codes_snap.get(code) or {}).get("che_str"), None)
                    _vs, _vr = _VE.decide(code, entry, peak, cur, ma20_hard=False, che=_che_now)
                    if _vs:
                        reason = "TRAIL"; tag = f"{_vr} {pnl:+.1f}%"
                except Exception:
                    _vs, _vr, _vt = _vol_hold_decide(code, entry, peak, cur)   # 폴백(옛 로컬 로직)
                    if _vs:
                        reason = _vr; tag = f"{_vt} {pnl:+.1f}%"
        elif CHE_EXIT_ON and _che_mod is not None:
            che = _safe_float((codes_snap.get(code) or {}).get("che_str"), None)   # [#6] 안전변환(문자열→None=데이터없음)
            _bar = _cur_bar(code) if WICK_ON else None   # [2026-06-29] 음봉+긴윗꼬리 판정용 OHLC
            # [MA-EXIT 면제 2026-06-29 친구님] deep_v=장중 역방향 스캘프 → 일봉 5/20일선 구조청산은 시간프레임 불일치.
            #   정배열 진입게이트를 면제한 것과 대칭(딥은 역배열 자리를 사는 전략). 기본 면제(ma5=ma20=0 → che_exit가 MA레이어 skip).
            #   되살리려면 setx DEEPV_MA_EXIT YES. (EXIT_MA_LAYER 전역 ON이어도 deep_v는 이 스위치로 독립 차단)
            _m5 = _m20 = 0.0
            if os.environ.get("DEEPV_MA_EXIT", "NO").strip().upper() == "YES":
                try:
                    import exit_ma as _DMA; _m5, _m20 = _DMA.ma5(code), _DMA.ma20(code)
                except Exception:
                    _m5 = _m20 = 0.0
            sell, rs, tg, _drop, _strong = _che_mod.decide(cur, entry, peak, pnl, che, p.get("che_prev"), DEEPV_CHE_PARAMS, bar=_bar, ma5=_m5, ma20=_m20)
            if che is not None and che != p.get("che_prev"):
                p["che_prev"] = che; dirty = True
            if sell:
                reason = rs; tag = f"{tg} {pnl:+.1f}%"
        else:   # 폴백: 기존 고정 +TP/-STOP
            if cur >= float(p.get("tp_price", entry * 1.05)):
                reason = "TP"; tag = f"익절+{TP_PCT:.0f}% {pnl:+.1f}%"
            elif cur <= float(p.get("stop_price", entry * 0.95)):
                reason = "STOP"; tag = f"하드손절 {pnl:+.1f}%"
        if reason:
            _log(f"[MANAGE] ★매도 {code} x{qty} @{cur:,.0f} ({reason}·{tag})")
            if _order(bc, code, qty, "SELL", "MANAGE"):
                allpos.pop(code, None); _jsave(DEEPV_POS, allpos); dirty = True   # [#5] 매도 즉시저장
                if LIVE:
                    rt2 = _jload(RT_OPEN); rt2.pop(code, None); _jsave(RT_OPEN, rt2)
      except Exception as _e:   # [BUGFIX 2026-06-30 #4] 한 종목 오류 격리 → 나머지 청산 계속
        _log(f"[MANAGE] {code} 처리오류(격리·다음종목 계속): {_e}")
        continue
    if dirty:
        _jsave(DEEPV_POS, allpos)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    _log(f"=== deep-V executor [{mode}] LIVE={LIVE} CAP={CAP:,} maxbuy={MAX_BUYS_DAY} "
         f"| 진입: DROP={DEEP} REV_VOL_MULT={REV_VOL_MULT} REVERSAL={REVERSAL_ON} "
         f"| 청산: VOL_EXIT={VOL_EXIT_ON} STOP={STOP_PCT}% PKDROP={VOL_PKDROP}% ===")
    if mode == "pick":
        mode_pick(); mode_manage()
    elif mode == "manage":
        mode_manage()
    elif mode == "sell":
        mode_manage(force_eod=True)
    _log(f"=== deep-V executor [{mode}] done ===")


if __name__ == "__main__":
    main()

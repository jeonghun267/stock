# -*- coding: utf-8 -*-
"""[NEW_PULLBACK 실시간 실전 executor] 친구님 "소액 실전 내일 바로".
   pick(09:10~14:00, 주기실행): opt10032+분봉 실시간 → NEW_PULLBACK 1등(점수>=문턱) → 자동매수(소액·1종목).
   ★매수는 14:00까지만(15:00 청산이라 늦게사면 못팜). sell(15:00): 청산. 검증된 broker경로.
   ★안전: NEW_PB_LIVE=NO면 모의·소액캡·1종목·env즉시롤백. -X utf8. 실행: ... pick / sell"""
import sys, io, json, uuid, os
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")
sys.path.insert(0, r"C:\stock_bot\MONITOR")
import new_pullback_shadow_v1 as NP   # _bars, _analyze, _load_memb 재사용
import prices_1m_reader as _P1M   # [CENTRAL-1M 2026-06-24] 중앙 1분봉 파일읽기(opt10080 직접호출 대체)

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
POS = Path(r"C:\stock_bot\DATA\new_pb_positions.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
BRK_POS = Path(r"C:\stock_bot\DATA\brk_positions.json")   # [CONFLICT 2026-06-25] 돌파 보유 확인(대칭 충돌방지)
EOD_GAP_POS    = Path(r"C:\stock_bot\DATA\eod_gap_positions.json")                    # [CONFLICT 2026-06-27] 종가매수(eod_gap) 보유 — 중복매수 차단
EOD_PICKUP_POS = Path(r"C:\stock_bot\DATA\eod_pickup\rt_eod_pickup_positions.json")   # [CONFLICT 2026-06-27] 종가매수(eod_pickup) 보유 — 중복매수 차단
LOG = Path(r"C:\stock_bot\data\LOG\new_pullback_live.log")

LIVE = os.environ.get("NEW_PB_LIVE", "NO").strip().upper() == "YES"
CAP = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or os.environ.get("NEW_PB_CAP_KRW") or "300000"))  # ★통일캡: SAFEPLUS_CAP_KRW 마스터(전 전략 공통·기본30만). 키울땐 이것만.
try:  # [레짐 금액 스케일러 2026-06-29 친구님] 시장 나쁘면 건당 작게(개수는 그대로=작게많이). REGIME_SIZE_SCALE=NO면 1.0(무변경)
    import market_regime as _MR_; CAP = max(1, int(CAP * _MR_.cap_mult()))
except Exception: pass
MIN_SCORE = float(os.environ.get("NEW_PB_MIN_SCORE", "70"))
# [2026-06-19 친구님] 백테발견 자리 우대(소프트가점): 60일신고가 첫눌림 + 고가권(range_pos≥0.6) + 강RS(alpha_mom>0).
#   하드차단 아님(NO_TRADE 방지)·페일세이프(eod실패시 가점0)·top1 플래그 로그로 관찰. 롤백 setx NEW_PB_FIRSTPB_BONUS NO.
FIRSTPB_BONUS = os.environ.get("NEW_PB_FIRSTPB_BONUS", "NO").strip().upper() == "YES"  # [6/19 친구님 "상투위험" 지적→OFF]
# [2026-06-21 친구님] ★검증반전: 6/19 '상투위험'으로 껐으나 백테(newpb_position)서 천정권(40일신고가≥98)이 오히려 최고(top1 +3.89%/승62%·중권 60~80%가 진짜 매물대물림). → 40일 신고가권 '우선 선택'. 롤백 setx NEW_PB_HIGHBREAK_PRIORITY NO.
HIGHBREAK_PRIORITY = os.environ.get("NEW_PB_HIGHBREAK_PRIORITY", "NO").strip().upper() == "YES"
# [2026-06-22 친구님] ★거래대금배수+40일신고가 가중강화 — 백테(selection_feature_sep) 거래대금배수 d0.45 최강·신고가권1등 +6.13%. 롤백 setx NEW_PB_VALSURGE_BOOST NO.
VALSURGE_BOOST = os.environ.get("NEW_PB_VALSURGE_BOOST", "NO").strip().upper() == "YES"
BUY_CUTOFF = os.environ.get("NEW_PB_BUY_CUTOFF", "1400")     # 이 시각 이후 매수금지(15:00 청산)
SELL_HM = os.environ.get("NEW_PB_SELL_HM", "1500")
ACCOUNT = os.environ.get("SWING_ACCOUNT", "").strip()
# [2026-06-18 친구님 "저점 못잡은 문제 수정"] 진입 타이밍 게이트 + 1분 가벼운 감시(후보 5분캐시).
ENTRY_GATE = os.environ.get("NEW_PB_ENTRY_GATE", "YES").strip().upper() == "YES"   # 롤백: setx NEW_PB_ENTRY_GATE NO
RESCAN_MIN = int(os.environ.get("NEW_PB_RESCAN_MIN", "5"))   # 무거운 후보발굴 주기(분). 그사이 1분마다 게이트만(가벼움)
GATE_VOL_LB = int(os.environ.get("NEW_PB_GATE_VOL_LB", "5"))
CAND_STATE = Path(r"C:\stock_bot\DATA\new_pb_cand_cache.json")
# [2026-06-18 친구님] 장중 손절 — 매도엔진이 큐기반이라 rt_open만 있는 NEW_PB는 관리못함(손절 안걸림 발견).
#   → NEW_PB 자체 장중손절: 매 1분 보유종목 현재가 확인, -STOP_PCT% 이하면 즉시 매도. 롤백 setx NEW_PB_STOP_PCT 999
STOP_PCT = float(os.environ.get("NEW_PB_STOP_PCT", "5.0"))
# [2026-06-19 친구님 "익절 너무 빨라 큰수익 놓친다"] 고점 -TRAIL_PCT% 넓은 트레일(2단: -5%바닥 + 고점-10%).
#   ★OWN_EXIT=YES일 때만 작동(그때 메인 매도엔진은 NEW_PB 손 뗌). 안 켜면 현행(-5%손절만)과 100% 동일.
#   근거: 6/18 데이터 — 큰상승 종목 꼭대기길 흔듦 평균11%/중앙8% → -10%가 무릎(안 털리고 끝까지). 롤백 setx NEW_PB_OWN_EXIT NO.
OWN_EXIT = os.environ.get("NEW_PB_OWN_EXIT", "NO").strip().upper() == "YES"
TRAIL_PCT = float(os.environ.get("NEW_PB_TRAIL_PCT", "10.0"))
# [2026-06-19 친구님 "트레일링 만든거 바로 적용·소액실전"] 생존분석 단계별 트레일:
#   고점기준 수익 커질수록 조임 0~10%:-7 / 10~20%:-6 / 20~30%:-5 / 30%+:-4. -5%하드 유지·OWN_EXIT 하위.
#   기본 YES(코드 즉시발효, env전파 불요). 롤백: 백업복원 또는 setx NEW_PB_STAGE_TRAIL NO.
STAGE_TRAIL = os.environ.get("NEW_PB_STAGE_TRAIL", "YES").strip().upper() == "YES"
# ★단계트레일 모드의 하드손절은 env(NEW_PB_STOP_PCT=999로 꺼져있음)에 의존하지 않고 코드값 5% 고정.
#   (env는 재부팅 전 라이브 반영 안 되므로 -5% 보장 위해 코드 기본값 사용.)
STAGE_HARD_PCT = float(os.environ.get("NEW_PB_STAGE_HARD", "5.0"))
# [REAL-MICRO 2026-06-24] ★실시간 체결강도/호가(broker IPC snapshot) — 트레일 매도시 체결강도 강(매수우위)하면 보유(하드손절은 유지). 친구님 "체결강도 강하면 안 팔고"
MICRO_USE    = os.environ.get("NEW_PB_MICRO_USE", "YES").strip().upper() == "YES"  # 끄려면 setx NEW_PB_MICRO_USE NO
SELL_CHE_MAX = float(os.environ.get("NEW_PB_SELL_CHE_MAX", "100"))  # 체결강도 이 이상(매수우위)이면 트레일 매도 보류
SELL_OB_MAX  = float(os.environ.get("NEW_PB_SELL_OB_MAX", "0.8"))   # 단 호가 매도우위(imb<이값)면 보류 안함
MICRO_SNAP_FILE  = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
MICRO_WATCH_FILE = Path(r"C:\stock_bot\IPC\micro_watch_newpb.json")
# [CHE-EXIT 2026-06-25 친구님 "트레일링은 하루종일 끌다 토해낸다·줄때먹고빠진다"] 단계트레일 대체 청산:
#   ①+TP_CAP% 무조건 익절 ②체결강도 게이트 되밀림(강=넓게 RETR_WIDE 러너끌기·약=타이트 RETR_TIGHT 가차없이) ③하드-5%.
#   백테(테마대장주 3분봉 151종목일): 되밀림 좁힐수록 수익↑·변동성↓ 단조 — 고점-1% 승48%/stdev2.7 vs 트레일 승31%/stdev4.5.
#   체결강도는 과거데이터無=백테불가, 강/약 비대칭으로 '좁은안정+넓은러너' 둘다 취하는 라이브 레버(forward).
#   진입기회 눌림 2번 → MAX_LEGS=2 재진입 허용(무한 깎임 방지 캡). 롤백: setx NEW_PB_CHE_EXIT NO 또는 백업복원.
CHE_EXIT    = os.environ.get("NEW_PB_CHE_EXIT", "YES").strip().upper() == "YES"
TP_CAP      = float(os.environ.get("NEW_PB_TP_CAP", "10.0"))      # 무조건 익절 상한
CHE_STRONG  = float(os.environ.get("NEW_PB_CHE_STRONG", "120"))   # 체결강도 이 이상=강(러너) → 넓은 되밀림 허용 (친구님 기준 120)
RETR_WIDE   = float(os.environ.get("NEW_PB_RETR_WIDE", "4.0"))    # 강할때 고점-이폭%(끌고감)
RETR_TIGHT  = float(os.environ.get("NEW_PB_RETR_TIGHT", "1.5"))   # 약할때 고점-이폭%(가차없이)
RETR_ARM    = float(os.environ.get("NEW_PB_RETR_ARM", "1.0"))     # 고점이익 이% 넘어야 되밀림탈출 무장(진입노이즈 방지·하드손절은 항상)
MAX_LEGS    = int(os.environ.get("NEW_PB_MAX_LEGS", "2"))         # 종목당 하루 재진입 캡(눌림 2번)
# [RESTEP-CHE 2026-06-26 친구님 "서산 칼날 재매수 막아"] 재진입(leg≥2)은 실시간 체결강도≥이값일 때만.
#   서산079650 1차익절후 떨어지는중(음봉연속) 2차 재매수→-9.83%. 재매수는 첫매수(체결90)보다 엄격(매수확실)일때만.
#   첫매수·깊은V는 영향0(재진입에만). 못읽으면 통과(fail-open). 끄려면 setx NEW_PB_RESTEP_CHE 0.
RESTEP_CHE  = float(os.environ.get("NEW_PB_RESTEP_CHE", "110"))
# [CHE-SLOPE 2026-06-25 친구님 "체결강도 급락(150→90→60)도 매도신호"] 절대값뿐 아니라 기울기:
#   직전(1분전) 대비 이 비율 이상 급락하면 강체결이어도 '약'으로 강등(매수세 꺾임). 0.35=35%↓(150→90 등).
CHE_DROP_FRAC = float(os.environ.get("NEW_PB_CHE_DROP_FRAC", "0.35"))
def _stage_trail_pct(peak_gain_pct):
    if peak_gain_pct < 10: return 7.0
    if peak_gain_pct < 20: return 6.0
    if peak_gain_pct < 30: return 5.0
    return 4.0
# [2026-06-18 게이트 V2 — 친구님/GPT 정밀화] 7조건. 전부 env조절·발화율 로그.
GATE_VOL_MULT  = float(os.environ.get("NEW_PB_GATE_VOL_MULT",  "1.3"))   # 거래량 ≥ 직전유효5봉 중앙값×이배
GATE_CPOS      = float(os.environ.get("NEW_PB_GATE_CPOS",      "0.65"))  # 종가위치 봉상단 이상(윗꼬리 제외)
GATE_LOW_LB    = int(os.environ.get("NEW_PB_GATE_LOW_LB",      "8"))     # 눌림저점 탐색 봉수
RISE_BASE      = float(os.environ.get("NEW_PB_GATE_RISE_BASE", "4.5"))   # 저점대비 허용상승%(기본)
RISE_LEADER    = float(os.environ.get("NEW_PB_GATE_RISE_LEAD", "5.5"))   # 강테마대장
RISE_OVERHEAT  = float(os.environ.get("NEW_PB_GATE_RISE_HOT",  "3.0"))   # 과열(시가대비 +20%↑)
OVERHEAT_PCT   = float(os.environ.get("NEW_PB_GATE_OVERHEAT",  "20.0"))
HIGH_BREAK     = os.environ.get("NEW_PB_GATE_HIGH_BREAK", "YES").strip().upper() == "YES"  # 현재고가>직전고가(가짜턴업 차단)
STOP_DIST_MAX  = float(os.environ.get("NEW_PB_GATE_STOP_DIST", "7.0"))   # 진짜눌림저점까지 거리 이 %↑면 금지(손절거리)
# [DEEPV-CHE 2026-06-25 친구님] 수직낙하 깊은V: 체결강도≥기준일 때만 ⑥(이미올라옴)·⑦(손절거리)를 '완화'(더 허용).
#   ★순수 확대(max)=체결강도 약/없음이면 기존과 100% 동일·아무것도 추가로 안막음. 실손실은 CHE_EXIT 하드-5%가 캡. 끄려면 setx NEW_PB_DEEPV_CHE_ON NO.
DEEPV_CHE_ON   = os.environ.get("NEW_PB_DEEPV_CHE_ON", "YES").strip().upper() == "YES"
DEEPV_CHE      = float(os.environ.get("NEW_PB_DEEPV_CHE",      "120"))    # 체결강도 이 이상=강한 깊은V → 완화
DEEPV_RISE_MAX = float(os.environ.get("NEW_PB_DEEPV_RISE_MAX", "12.0"))   # 완화시 저점대비 허용상승%(기존 4.5~5.5 대신)
DEEPV_STOP_DIST= float(os.environ.get("NEW_PB_DEEPV_STOP_DIST","15.0"))   # 완화시 손절거리 허용%(기존 7 대신·실손실은 하드-5%가 캡)
# [REV-MA60 2026-06-25 친구님] 역배열(일봉 MA20<MA40<MA60)인데 현재가가 60일선 아래면 매수보류(약한 dead-cat 반등 차단).
#   백테(KOSDAQ): 역배열&60일선아래 -1.66%/큰손실20% vs 역배열&60일선위 +0.82%/승45%(강한 추세전환=깊은V 살림). 끄려면 setx NEW_PB_REV_MA60 NO.
REV_MA60       = os.environ.get("NEW_PB_REV_MA60", "YES").strip().upper() == "YES"
# [REV-CHE 2026-06-26 친구님] 역배열(MA20<MA40<MA60)&60선'위'(REV_MA60 허용군)는 dead-cat 섞임(삼익제약 -5.57%).
#   → 그 군은 실시간 체결강도≥REV_CHE_MIN(큰손흡수)일 때만 매수, 약하면 보류. fail-open(스냅샷없음→통과).
#   끄려면 setx NEW_PB_REV_CHE NO. 임계조정 setx NEW_PB_REV_CHE_MIN <값>.
REV_CHE        = os.environ.get("NEW_PB_REV_CHE", "YES").strip().upper() == "YES"
REV_CHE_MIN    = float(os.environ.get("NEW_PB_REV_CHE_MIN", "100"))
# [CHE-FLOOR 2026-06-26 친구님] 모든 NEW_PB 매수에 실시간 체결강도 하한 — 배열무관 약한수급 진입 차단.
#   백테근거(opt10047 일별·60일): 진입일 체결<70 EV-1.76%/승18% · 70~90 -0.84% · 90~110 -0.22% · ≥110 +1.03%/승56%.
#   단조증가=체결강도가 손실 가름. 오늘 손실3종목(체결75~83·중약밴드)이 정확히 이걸로 걸림.
#   ★당일 실시간값으로만 유효(전일값은 백테상 안통함). fail-open(못읽으면 통과·기존동일). 끄려면 setx NEW_PB_CHE_FLOOR 0.
CHE_FLOOR      = float(os.environ.get("NEW_PB_CHE_FLOOR", "90"))   # 실시간 체결강도 이 미만이면 매수보류(0=끔)
# [BASESURGE-WIRE 2026-06-26 친구님] base_surge(횡보→갑툭) 감지 종목을 익일 눌림 후보로 유니버스에 병합.
#   백테검증(6/26): 갑툭 당일추격 +1.28%(평범) but 익일 눌림목 진입이 핵심(+18%·NEW_PB 기계화 ~+2%).
#   감지CSV(detect_log.csv) 종목을 NEW_PB 유니버스에 추가 → 눌림 오면 기존게이트로 잡음. 끄려면 setx NEW_PB_USE_BASESURGE NO.
USE_BASESURGE  = os.environ.get("NEW_PB_USE_BASESURGE", "YES").strip().upper() == "YES"
BASESURGE_CSV  = Path(r"C:\stock_bot\data\shadow\base_surge_intraday\detect_log.csv")
BASESURGE_DAYS = int(os.environ.get("NEW_PB_BASESURGE_DAYS", "2"))  # 최근 N거래일 감지분만(익일~다음날 눌림)
# [MACONV-WIRE 2026-06-26 친구님] 3선(이평) 수렴 종목을 익일 눌림 후보로 병합 — 친구님 "3선 만난 바닥 수렴".
#   ma_convergence_*.csv(EOD발행) 종목 → NEW_PB 유니버스 추가 → 눌림오면 기존게이트로 잡음. 끄려면 setx NEW_PB_USE_MACONV NO.
USE_MACONV     = os.environ.get("NEW_PB_USE_MACONV", "YES").strip().upper() == "YES"
MACONV_GLOB    = r"C:\stock_bot\data\shadow\ma_convergence_*.csv"
_DMA_CACHE     = {"d": "", "m": {}}   # 일봉 MA20/40/60 캐시(당일 1회 로드)
_DMA3_CACHE    = {"ts": 0.0, "m": {}}  # [3분봉 2026-06-30] 3분봉 MA20/40/60 캐시(15초)
_LEADER_CACHE  = {"d": "", "s": set()}


def _daily_ma():
    """종목별 (MA20,MA60). ★[2026-07-09 친구님 "이평선은 5/20/60만·나머지 버려"] 40선 폐기(롤백 .bak_ma520_20260709).
    MA_TIMEFRAME=3MIN(친구님 2026-06-30 "모든 MA 3분봉")이면 당일 3분봉,
    DAILY면 일봉(롤백). 데이터 부족 종목은 dict에서 제외 → 호출측 .get()이 None=fail-open(미차단)."""
    if os.environ.get("MA_TIMEFRAME", "3MIN").strip().upper() == "3MIN":
        import time as _t
        now = _t.time()
        if now - _DMA3_CACHE["ts"] < 15:
            return _DMA3_CACHE["m"]
        try:
            import intraday_ma as _im
            m = {}
            for code in _im.all_codes():
                a20, a60 = _im.ma20(code), _im.ma60(code)
                if a20 and a60:                # 60봉(=3분봉 60개·180분) 다 형성된 종목만
                    m[code] = (a20, a60)
            _DMA3_CACHE.update({"ts": now, "m": m})
            return m
        except Exception:
            return _DMA3_CACHE["m"]
    today = datetime.now().strftime("%Y%m%d")
    if _DMA_CACHE["d"] == today:
        return _DMA_CACHE["m"]
    try:
        import pandas as pd
        e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=["date", "code", "market", "close"], low_memory=False)
        e = e[e["market"] == "KOSDAQ"].copy(); e["code"] = e["code"].str.zfill(6)
        e["close"] = pd.to_numeric(e["close"], errors="coerce")
        days = sorted(e["date"].unique())[-65:]
        e = e[e["date"].isin(days)].sort_values(["code", "date"])
        m = {}
        for code, g in e.groupby("code", sort=False):
            c = g["close"].values
            if len(c) < 60:
                continue
            m[code] = (float(c[-20:].mean()), float(c[-60:].mean()))
        _DMA_CACHE.update({"d": today, "m": m})
        return m
    except Exception:
        return _DMA_CACHE["m"]


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"; print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True); io.open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _z(c): return str(c).zfill(6)
def _jload(p):
    try: return json.load(io.open(p, encoding="utf-8"))
    except Exception: return {}
def _jsave(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")          # [원자적쓰기 2026-06-29] 임시파일→os.replace = 쓰기중 크래시시 손상방지
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag):
    # ★[2026-07-01 대장주 순위표 게이트] 매수는 전날 종가 대장주 순위표 안에서만.
    #   board 없거나 LEADER_FILTER OFF면 is_leader=True(fail-open). 롤백 setx NEWPB_LEADER_BOARD NO
    if side == "BUY" and os.environ.get("NEWPB_LEADER_BOARD", "YES").strip().upper() == "YES":
        try:
            import leader_filter as _lf
            if not _lf.is_leader(bc, code):
                _log(f"[{tag}][대장외] {code} 전날 순위표 밖 → 매수차단"); return False
        except Exception:
            pass
    if not LIVE:
        _log(f"[{tag}][모의] {side} {code} x{qty} (NEW_PB_LIVE=NO)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"newpb_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"NEWPB_{side}_{code}", screen_no="9704")
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


def _opt_universe(bc):
    codes = set()
    try:
        res = bc.tr("opt10032", inputs={"시장구분": "101", "관리종목포함": "0"}, output_fields=["종목코드"], timeout_sec=10.0)
        for r in (((res or {}).get("data") or {}).get("records") or [])[:100]:
            c = _z(str(r.get("종목코드", "")).lstrip("A"))
            if len(c) == 6: codes.add(c)
    except Exception as e:
        _log(f"opt10032 실패 {e}")
    return codes


def _basesurge_codes():
    """[BASESURGE-WIRE 2026-06-26] base_surge 감지 종목(최근 BASESURGE_DAYS거래일) set — 익일 눌림 후보.
       실패→빈set(fail-safe·아무것도 안막음·기존동일)."""
    s = set()
    if not USE_BASESURGE:
        return s
    try:
        import csv as _csv
        if not BASESURGE_CSV.exists():
            return s
        rows = list(_csv.DictReader(open(BASESURGE_CSV, encoding="utf-8-sig", errors="replace")))
        dates = sorted({r.get("date", "") for r in rows if r.get("date")})
        recent = set(dates[-BASESURGE_DAYS:]) if dates else set()
        for r in rows:
            if r.get("date") in recent:
                c = _z(str(r.get("code", "")))
                if len(c) == 6:
                    s.add(c)
    except Exception as e:
        _log(f"[BASESURGE] 읽기실패(무시): {e}")
    return s


def _maconv_codes():
    """[MACONV-WIRE 2026-06-26] 3선 수렴 종목(최신 ma_convergence CSV) set — 익일 눌림 후보.
       실패→빈set(fail-safe·기존동일)."""
    s = set()
    if not USE_MACONV:
        return s
    try:
        import csv as _csv, glob as _glob
        fs = sorted(_glob.glob(MACONV_GLOB))
        if not fs:
            return s
        for r in _csv.DictReader(open(fs[-1], encoding="utf-8-sig", errors="replace")):
            c = _z(str(r.get("code", "")))
            if len(c) == 6:
                s.add(c)
    except Exception as e:
        _log(f"[MACONV] 읽기실패(무시): {e}")
    return s


def _prev_eod():
    import pandas as pd
    e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=["date", "code", "name", "market", "value_ratio", "w52_high_pct"], low_memory=False)
    e = e[e["market"] == "KOSDAQ"]; e["code"] = e["code"].str.zfill(6)
    last = e.sort_values("date").groupby("code").tail(1)
    return {r.code: {"vr": r.value_ratio, "w52": r.w52_high_pct, "name": str(r.name)} for r in last.itertuples(index=False)}


def _eod_pos():
    """[2026-06-19 친구님] 종목별 20일 고저(위치)·60일 신고가 경과일(첫눌림)·alpha_mom(RS). 최근70일만 읽어 가벼움."""
    import pandas as pd, numpy as np
    e = pd.read_csv(EOD, dtype={"date": str, "code": str},
                    usecols=["date", "code", "market", "high", "low", "alpha_mom"], low_memory=False)
    e = e[e["market"] == "KOSDAQ"].copy(); e["code"] = e["code"].str.zfill(6)
    days = sorted(e["date"].unique())[-70:]
    e = e[e["date"].isin(days)].sort_values(["code", "date"])
    for c in ["high", "low", "alpha_mom"]: e[c] = pd.to_numeric(e[c], errors="coerce")
    out = {}
    for code, g in e.groupby("code", sort=False):
        h = g["high"].values; l = g["low"].values
        if len(h) < 20: continue
        hi20 = float(np.nanmax(h[-20:])); lo20 = float(np.nanmin(l[-20:]))
        hi40 = float(np.nanmax(h[-40:]))                              # [6/21] 40일(2달) 고점
        h60 = h[-60:]; dsh = len(h60) - 1 - int(np.nanargmax(h60))
        am = g["alpha_mom"].values[-1]; am = float(am) if am == am else None
        out[code] = (hi20, lo20, dsh, am, hi40)
    return out


def _score_ranked(bc, exclude=None):
    exclude = exclude or set()   # [MULTIPOS 2026-06-25] 보유중 제외 + 점수 내림차순 랭킹리스트 반환(opt10032 1회/사이클)
    today = datetime.now().strftime("%Y%m%d")
    memb = NP._load_memb(); bars = NP._bars(today)
    opt = _opt_universe(bc); prev = _prev_eod()
    try:
        eodpos = _eod_pos() if (FIRSTPB_BONUS or HIGHBREAK_PRIORITY) else {}
    except Exception as _e:
        eodpos = {}; _log(f"[FIRSTPB] eod_pos 실패(가점0): {_e}")
    bsurge = _basesurge_codes()   # [BASESURGE-WIRE] 갑툭 감지종목 익일 눌림 후보 병합
    mconv = _maconv_codes()       # [MACONV-WIRE] 3선 수렴종목 익일 눌림 후보 병합
    uni = set(bars) | opt | bsurge | mconv
    if bsurge:
        _log(f"[BASESURGE] 갑툭 감지종목 {len(bsurge)}개 유니버스 병합: {sorted(bsurge)}")
    if mconv:
        _log(f"[MACONV] 3선수렴 종목 {len(mconv)}개 유니버스 병합: {sorted(mconv)}")
    day_val = {c: sum(b[6] for b in bars[c]) for c in bars}
    th = {}
    for c in uni:
        t = memb.get(c)
        if t: th.setdefault(t, []).append((day_val.get(c, 0), c))
    vrank = {}
    for t, lst in th.items():
        for i, (v, c) in enumerate(sorted(lst, reverse=True), 1): vrank[c] = i
    mr = {c: i + 1 for i, (c, v) in enumerate(sorted(day_val.items(), key=lambda x: -x[1]))}
    best = None; best_flags = (False, False, False, 0); best_hb = None; best_hb_flags = (False, False, False, 0)
    cands = []   # [MULTIPOS] 전 후보 수집 → 랭킹
    for code in uni:
        if code in exclude: continue   # [MULTIPOS] 이미 보유중 → 제외
        bl = bars.get(code)
        if not bl: continue
        eok = day_val.get(code, 0) / 1e8
        if eok < 50 or len(bl) < 8: continue
        px = bl[-1][4]
        if not (1000 <= px <= 500000): continue
        a = NP._analyze(bl)
        if not a: continue
        if not a["vwap_over"] and all(b[4] < b[7] for b in bl[-5:] if b[7] > 0): continue
        if a["big_bull"] and not a["mid_support"] and not a["vwap_over"]: continue
        if a["bad_break"]: continue
        pe = prev.get(code, {}); vr = pe.get("vr", 0) or 0
        p_size = 15 if (eok >= 300 or mr.get(code, 999) <= 20) else 11 if eok >= 100 else 6 if eok >= 50 else 0
        p_v20 = 10 if vr >= 3 else 7 if vr >= 2 else 4 if vr >= 1.5 else 0
        p_re = 10 if a["reentry"] else (5 if a["rebound"] else 0)
        p_bull = (7 + (5 if a["bull_val_eok"] >= 30 else 0) + 5 + (3 if a["bull_uw"] <= 0.2 else 0)) if a["big_bull"] else 0
        p_pb = (10 if (a["mid_support"] or a["vwap_over"]) else 0) + (5 if a["pb_low_hold"] else 0) + (5 if a["pb_vol_contract"] else 0) + (5 if a["rebound"] else 0)
        vrt = vrank.get(code, 99); p_theme = 6 if vrt == 1 else 4 if vrt == 2 else 0
        rs = (px / bl[0][1] - 1) * 100 if bl[0][1] > 0 else 0
        p_rs = (5 if rs > 0 else 0) + (5 if rs > -1 else 0)
        nolead = vrt >= 3 and bool(memb.get(code))
        # [2026-06-19 친구님] 60일신고가 첫눌림+고가권+강RS 소프트가점
        fp = hz = stg = hb = False
        pd_ = eodpos.get(code)
        if pd_:
            hi20, lo20, dsh60, am, hi40 = pd_
            rpos = (px - lo20) / (hi20 - lo20) if (hi20 > lo20) else None
            hz = (rpos is not None and rpos >= 0.6)      # 고가권
            fp = (dsh60 is not None and dsh60 <= 3)       # 60일신고가 최근3일내=첫눌림 자리
            stg = (am is not None and am > 0)             # 강RS(시장대비 양)
            hb = (hi40 and hi40 > 0 and (px / hi40 * 100) >= 98.0)   # ★[6/21] 40일(2달) 신고가권(≥98)=매물대뚫림
        p_fpb = (8 if fp else 0) + (6 if hz else 0) + (5 if stg else 0)
        # [2026-06-22 친구님] ★거래대금배수+신고가 가중강화(env토글). 거래대금배수=백테 최강신호·40일신고가권=매물대뚫림.
        p_vboost = (8 if vr >= 3 else 5 if vr >= 2 else 0) if VALSURGE_BOOST else 0
        p_hboost = (8 if hb else 0) if VALSURGE_BOOST else 0
        score = (p_size + p_v20 + p_re + p_bull + p_pb + p_theme + p_rs + p_fpb + p_vboost + p_hboost) - (1000 if nolead else 0)
        # ★[2026-07-01 단타점수 우선순위] 대장 순위표 단타점수로 랭킹 가점(동시 후보 중 상위 대장 먼저 매수)
        if os.environ.get("NP_SCALP_PRIORITY", "YES").strip().upper() == "YES":
            try:
                import leader_filter as _lf
                score += (_lf.priority(code) - 50.0) * float(os.environ.get("NP_SCALP_W", "0.3"))
            except Exception:
                pass
        ct = (score, code, pe.get("name", ""), px, eok, a["bull_hm"], a.get("bull_mid", 0), a.get("bull_low", 0), a.get("pb_low", 0))
        cands.append(ct)
        if best is None or score > best[0]:
            best = ct; best_flags = (fp, hz, stg, p_fpb)
        if hb and (best_hb is None or score > best_hb[0]):
            best_hb = ct; best_hb_flags = (fp, hz, stg, p_fpb)
    # [2026-06-21 친구님] ★40일 신고가권 우선: 그날 신고가권(hb≥98) 종목 있으면 1등으로 격상(없으면 기존 best 폴백·거래일유지)
    if HIGHBREAK_PRIORITY and best_hb is not None:
        if best is None or best_hb[1] != best[1]:
            _log(f"{datetime.now():%H%M} [HIGHBREAK] 40일신고가권(≥98) 우선선택 {best_hb[1]} {best_hb[2][:8]} (기존1등 {best[1] if best else '-'})")
        best = best_hb; best_flags = best_hb_flags
    if best is not None and FIRSTPB_BONUS:
        _fp, _hz, _stg, _pb = best_flags
        _log(f"{datetime.now():%H%M} [FIRSTPB] top1 {best[1]} {best[2][:8]} {best[0]:.0f}점 "
             f"첫눌림{'O' if _fp else 'X'}·고가권{'O' if _hz else 'X'}·강RS{'O' if _stg else 'X'}(가점+{_pb})")
    cands.sort(key=lambda x: -x[0])
    if best is not None:   # [MULTIPOS] HIGHBREAK 우선선택(또는 1등)을 맨 앞으로, 나머지 점수순
        cands = [c for c in cands if c[1] == best[1]] + [c for c in cands if c[1] != best[1]]
    return cands


def _gate_bars(bc, code):
    """[CENTRAL-1M 2026-06-24] ★opt10080 직접호출 폐지 → 중앙수집 DATA/prices_1m.csv 읽기(친구님: 조회 중복제거).
       반환형식 [(hm,o,h,l,c,v)]·해상도 1분봉 그대로·게이트/매수로직 무수정(데이터 출처만 교체)."""
    return _P1M.bars(code, log=_log, tag="NEW_PB")


def _leader_set():
    """code_theme_strength is_leader=1 코드 set(일자캐시). 실패→빈set."""
    today = datetime.now().strftime("%Y%m%d")
    if _LEADER_CACHE["d"] == today:
        return _LEADER_CACHE["s"]
    s = set()
    try:
        import csv as _csv
        p = r"C:\stock_bot\data\theme\code_theme_strength.csv"
        for r in _csv.DictReader(io.open(p, encoding="utf-8-sig", errors="replace")):
            if str(r.get("is_leader", "0")).strip() == "1":
                s.add(_z(r.get("code", "")))
    except Exception:
        pass
    _LEADER_CACHE["d"] = today; _LEADER_CACHE["s"] = s
    return s


def _entry_gate(bc, code, bull_mid=0, bull_low=0, pb_low=0):
    """[진입게이트 V2 — 친구님/GPT 7조건] 바닥 확인 후 '턴업 초입'만 PASS. (pass, reason, cur).
       ①양봉 ②종가>직전종가 ③거래량≥직전유효5봉 중앙값×MULT ④종가위치≥CPOS
       ⑤현재가≤눌림저점+RISE%(과열3.0/대장5.5/기본4.5) ⑥중심선 위 ⑦장대양봉 저가 이탈없음.
       opt10080 클린분봉(구멍0). 분봉부족=WAIT(fail-safe). '바닥 찍는게 아니라 바닥확인후 초입 매수'."""
    from statistics import median
    bars = _gate_bars(bc, code)
    if len(bars) < 8:
        return False, "분봉부족", (bars[-1][4] if bars else 0)
    o, h, l, c, v = bars[-1][1], bars[-1][2], bars[-1][3], bars[-1][4], bars[-1][5]
    prev_c = bars[-2][4]; prev_h = bars[-2][2]
    vols = [x[5] for x in bars[-(GATE_VOL_LB + 1):-1] if x[5] > 0]
    vmed = median(vols) if vols else 0
    cpos = (c - l) / (h - l) if h > l else 1.0
    micro_low = min(x[3] for x in bars[-GATE_LOW_LB:])
    rise = (c / micro_low - 1) * 100 if micro_low > 0 else 0
    day_open = bars[0][1]
    day_gain = (c / day_open - 1) * 100 if day_open > 0 else 0
    is_lead = code in _leader_set()
    hot = day_gain >= OVERHEAT_PCT
    rmax = RISE_OVERHEAT if hot else (RISE_LEADER if is_lead else RISE_BASE)
    # [DEEPV-CHE 2026-06-25] 체결강도≥기준이면 깊은V 허용 — ⑥⑦만 max()로 '넓힘'(약/없으면 기존동일·축소 절대없음)
    _gche = (_read_micro(code) or {}).get("che_str") if (DEEPV_CHE_ON and MICRO_USE) else None
    _deepv = (_gche is not None and _gche >= DEEPV_CHE)
    eff_rmax = max(rmax, DEEPV_RISE_MAX) if _deepv else rmax
    eff_stop = max(STOP_DIST_MAX, DEEPV_STOP_DIST) if _deepv else STOP_DIST_MAX
    # [REV-MA60 2026-06-25 친구님] 역배열(MA20<MA60)인데 현재가 60일선 아래 = 약한 dead-cat → 매수보류.
    #   ★[2026-07-09 친구님 "이평선은 5/20/60만"] 40선 폐기 — 역배열 판정 20<60 두 선으로.
    #   60일선 위로 반등하면(진짜 추세전환=깊은V포함) 통과. 데이터없음→통과(fail-open·기존동일).
    if REV_MA60:
        _ma = _daily_ma().get(code)
        if _ma and _ma[0] < _ma[1] and c < _ma[1]:
            return False, f"역배열·60일선아래({c:,}<MA60 {int(_ma[1]):,})", c
        # [REV-CHE 2026-06-26 친구님] 역배열인데 60선'위'(허용군) = dead-cat 섞임 → 체결강도 강할때만 매수.
        #   체결강도 못읽으면(None) 통과(fail-open·기존동일). 삼익제약(역배열·체결약86) 같은 dead-cat 차단.
        if REV_CHE and _ma and _ma[0] < _ma[1] and c >= _ma[1]:
            _rche = (_read_micro(code) or {}).get("che_str")
            if _rche is not None and _rche < REV_CHE_MIN:
                return False, f"역배열·60선위 체결약({_rche:.0f}<{REV_CHE_MIN:.0f})", c
    # [CHE-FLOOR 2026-06-26 친구님] 배열무관 실시간 체결강도 하한 — 약한수급 진입차단(백테 단조입증).
    #   못읽으면 통과(fail-open·기존동일). 0이면 끔.
    if CHE_FLOOR > 0 and MICRO_USE:
        _fche = (_read_micro(code) or {}).get("che_str")
        if _fche is not None and _fche < CHE_FLOOR:
            return False, f"체결강도약({_fche:.0f}<{CHE_FLOOR:.0f})", c
    # ── 7조건 (하나라도 안되면 WAIT, 구체 사유) ──
    if c < o:
        return False, "음봉", c
    if c <= prev_c:
        return False, "직전종가 못넘음", c
    if HIGH_BREAK and h <= prev_h:
        return False, "고가 못넘음(가짜턴업)", c
    if vmed > 0 and v < vmed * GATE_VOL_MULT:
        return False, f"거래량약(×{(v/vmed if vmed else 0):.1f}<{GATE_VOL_MULT})", c
    if cpos < GATE_CPOS:
        return False, f"종가약/윗꼬리(상단{cpos:.0%})", c
    if rise > eff_rmax:
        return False, f"이미올라옴(저점+{rise:.1f}%>{eff_rmax:g}{'·대장' if is_lead else ''}{'·과열' if hot else ''})", c
    if pb_low > 0 and (c / pb_low - 1) * 100 > eff_stop:
        return False, f"손절거리멈(진짜저점-{(c/pb_low-1)*100:.1f}%>{eff_stop:g}%)", c
    if bull_mid > 0 and c < bull_mid:
        return False, f"중심선아래({c:,}<{int(bull_mid):,})", c
    if bull_low > 0 and c <= bull_low:
        return False, f"장대양봉저가이탈({c:,}≤{int(bull_low):,})", c
    return True, f"바닥+{rise:.1f}% 거래량×{(v/vmed if vmed else 0):.1f} 종가{cpos:.0%}(한계{eff_rmax:g}{'·대장' if is_lead else ''}{('·깊은V완화(체결%.0f)' % _gche) if _deepv else ''})", c


def _read_micro(code):
    """★IPC live_micro_snapshot에서 종목 실시간 체결강도/호가 읽기(키움 직접호출 X). 없으면 None."""
    try:
        d = json.loads(MICRO_SNAP_FILE.read_text(encoding="utf-8-sig"))
        return (d.get("codes") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _write_micro_watch(codes):
    """★보유종목을 micro_watch_newpb에 기록 → broker 실시간 구독(snapshot에 체결강도 채움)."""
    try:
        seen = []
        for c in codes:
            c = str(c).zfill(6)
            if c and c not in seen:
                seen.append(c)
        tmp = MICRO_WATCH_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"codes": seen[:60]}, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(MICRO_WATCH_FILE))
    except Exception:
        pass


UNIFIED_VOL_EXIT = os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES"  # [통일 매도 2026-07-01 친구님] vol_exit(수급+20선무조건). 롤백 setx UNIFIED_VOL_EXIT NO


def _check_stops(bc, hm, held, opens):
    """[장중 손절] 보유종목 현재가 ≤ 매수가×(1-STOP_PCT%) 면 즉시 매도. 매도엔진이 NEW_PB 미관리라 자체수행."""
    for code, p in list(opens.items()):
        bars = _gate_bars(bc, code)
        cur = bars[-1][4] if bars else 0
        buy = float(p.get("buy_price", 0))
        if cur <= 0 or buy <= 0:
            continue
        pnl = (cur / buy - 1) * 100
        # 고점 추적(트레일용) — OWN_EXIT=YES일 때만 트레일 활성
        peak = float(p.get("peak", buy) or buy)
        if cur > peak:
            peak = cur; p["peak"] = peak; _jsave(POS, held)
        # [CHE-EXIT 2026-06-25] 새 청산(단계트레일 대체·OWN_EXIT 하위). 우선순위: ①하드손절 ②+10%만족 ③되밀림.
        if OWN_EXIT and CHE_EXIT:
            ppk = (peak / buy - 1) * 100
            qty = int(p.get("qty", 0))
            hard_line = buy * (1 - STAGE_HARD_PCT / 100)
            # 체결강도 절대값 + 기울기(직전 대비 급락 → 매수세 꺾임)
            _che = None; _drop = False
            if MICRO_USE:
                _m = _read_micro(code); _che = (_m or {}).get("che_str")
                _prev = p.get("che_prev")
                if _che is not None and _prev:
                    if _che <= float(_prev) * (1 - CHE_DROP_FRAC): _drop = True   # 급락(150→90 등)
                if _che is not None:
                    p["che_prev"] = _che; _jsave(POS, held)
            strong = (_che is not None and _che >= CHE_STRONG) and not _drop      # 급락하면 강이어도 약 취급
            # [MA-EXIT 공통 2026-06-29 친구님 "매도 전부 똑같이"] 20일선이탈=하드·5일선이탈+체결약=추세깸. EXIT_MA_LAYER=YES일때.
            _ma_on = os.environ.get("EXIT_MA_LAYER", "NO").strip().upper() == "YES"
            _m5 = _m20 = 0.0
            if _ma_on:
                try:
                    import exit_ma as _DMA; _m5, _m20 = _DMA.ma5(code), _DMA.ma20(code)
                except Exception:
                    _m5 = _m20 = 0.0
            sell = False; reason = None; tag = ""
            if UNIFIED_VOL_EXIT:
                # [통일 매도 2026-07-01 친구님] 하드손절 유지 → 수급/MA/트레일은 vol_exit(매수우위 보유·매도우위+20선 무조건 매도)
                if cur <= hard_line:
                    sell = True; reason = "STOP"; tag = f"하드-{STAGE_HARD_PCT:g}%"
                else:
                    try:
                        import vol_exit as _VE
                        _s, _r = _VE.decide(code, buy, peak, cur, ma20_hard=True, che=(_che if isinstance(_che, (int, float)) else None))
                        if _s:
                            sell = True; reason = "TRAIL"; tag = _r
                    except Exception:
                        pass
            elif cur <= hard_line:                                    # ① 하드손절(최우선)
                sell = True; reason = "STOP"; tag = f"하드-{STAGE_HARD_PCT:g}%"
            elif _ma_on and _m20 > 0 and cur < _m20:                # 3번 하드: 20일선 이탈
                sell = True; reason = "STOP"; tag = "20일선이탈(하드)"
            elif _ma_on and _m5 > 0 and cur < _m5 and not strong:   # 2번: 5일선 이탈+체결약
                sell = True; reason = "TRAIL"; tag = "5일선이탈+추세깸"
            elif pnl >= TP_CAP:                                     # ② +10% 만족구간
                if strong:                                          #   강체결 → 끌되 타이트(조금 빠지면 익절·12~15% 노림)
                    if cur <= peak * (1 - RETR_TIGHT / 100):
                        sell = True; reason = "TP"; tag = f"+{ppk:.0f}%끌다익절·체결{_che:.0f}강"
                else:                                               #   약/급락 → 만족하고 익절
                    sell = True; reason = "TP"
                    tag = (f"+{pnl:.0f}%만족·체결{_che:.0f}약" if _che is not None else f"+{pnl:.0f}%만족") + ("·급락" if _drop else "")
            elif ppk > RETR_ARM:                                    # ③ 일반 되밀림(체결 게이트: 강=넓게·약=타이트)
                retr = RETR_WIDE if strong else RETR_TIGHT
                if cur <= peak * (1 - retr / 100):
                    sell = True; reason = "TRAIL"
                    tag = (f"체결{_che:.0f}{'강' if strong else '약'}" if _che is not None else "체결?") + ("·급락" if _drop else "") + f"·고점-{retr:g}%"
            if sell:
                _log(f"{hm} ★{reason}[{tag}] {code} {p.get('name','')[:8]} {pnl:.2f}% "
                     f"(현재 {cur:,}·고점 {peak:,.0f}/+{ppk:.1f}%) → 매도 x{qty}")
                if _order(bc, code, qty, "SELL", reason):
                    p["status"] = "CLOSED"; p["sell_date"] = datetime.now().strftime("%Y%m%d")
                    p["sell_price"] = cur; p["sell_reason"] = f"{reason}({pnl:.1f}%)"; p["sell_hm"] = hm
                    _jsave(POS, held)
                    if LIVE:
                        rt = _jload(RT_OPEN)
                        if code in rt and rt[code].get("_newpb"):
                            del rt[code]; _jsave(RT_OPEN, rt)
                    _log(f"{hm} 매도완료 {code} @{cur:,} ({pnl:.2f}%)")
                else:
                    _log(f"{hm} 매도주문 실패 {code} — ★수동확인 필요")
            continue   # CHE-EXIT 처리 완료 → 아래 단계트레일 경로 건너뜀
        eff_stop = STAGE_HARD_PCT if (OWN_EXIT and STAGE_TRAIL) else STOP_PCT  # 단계모드=코드5%(env999 무시)
        hard_line = buy * (1 - eff_stop / 100)                       # -5% 고정 바닥
        if OWN_EXIT and STAGE_TRAIL:
            tw = _stage_trail_pct((peak / buy - 1) * 100)            # 단계별 폭(고점기준 수익 커질수록 조임)
        elif OWN_EXIT and TRAIL_PCT < 100:
            tw = TRAIL_PCT                                           # 구버전 고정 폭
        else:
            tw = None
        trail_line = peak * (1 - tw / 100) if tw is not None else 0.0
        stopline = max(hard_line, trail_line)
        if cur <= stopline:
            is_trail = trail_line >= hard_line and cur <= trail_line and OWN_EXIT
            # ★실시간 체결강도(친구님 6/24): 트레일 매도인데 체결강도 강(매수우위)+호가 매도우위 아니면 보유(하드손절은 그대로). 데이터없으면 기존동작
            if is_trail and cur > hard_line and MICRO_USE:
                _m = _read_micro(code); _che = (_m or {}).get("che_str"); _imb = (_m or {}).get("imb")
                if _che is not None and _che >= SELL_CHE_MAX and not (_imb is not None and _imb < SELL_OB_MAX):
                    _log(f"{hm} 트레일 매도신호·체결강도 {_che:.0f}(강)·imb {_imb} → 보유(하드-{eff_stop:g}%만) {code}")
                    continue
            qty = int(p.get("qty", 0))
            reason = "TRAIL" if is_trail else "STOP"
            ppk = (peak / buy - 1) * 100
            _log(f"{hm} ★{'고점-'+str(tw)+'%트레일(단계)' if is_trail else '장중손절'} {code} {p.get('name','')[:8]} "
                 f"{pnl:.2f}% (현재 {cur:,} ≤ {'트레일' if is_trail else '손절'} {stopline:,.0f}·고점 {peak:,.0f}/+{ppk:.1f}%) → 매도 x{qty}")
            if _order(bc, code, qty, "SELL", reason):
                p["status"] = "CLOSED"; p["sell_date"] = datetime.now().strftime("%Y%m%d")
                p["sell_price"] = cur; p["sell_reason"] = f"{reason}({pnl:.1f}%)"
                _jsave(POS, held)
                if LIVE:
                    rt = _jload(RT_OPEN)
                    if code in rt and rt[code].get("_newpb"):
                        del rt[code]; _jsave(RT_OPEN, rt)
                _log(f"{hm} 손절완료 {code} @{cur:,} ({pnl:.2f}%)")
            else:
                _log(f"{hm} 손절 매도주문 실패 {code} — ★수동확인 필요")


def _brk_held():
    """[CONFLICT 2026-06-25 친구님] 돌파(breakout)가 현재 보유중인 종목 set — NEW_PB가 같은종목 매수 스킵
       (계좌섞임 방지·돌파의 _newpb_held와 대칭). 실패→빈set(차단안함·fail-safe·아무것도 안막음)."""
    s = set()
    try:
        d = _jload(BRK_POS)
        if isinstance(d, dict):
            for c, p in d.items():
                if isinstance(p, dict) and p.get("status") == "OPEN" and float(p.get("qty", 0) or 0) > 0:
                    s.add(str(c).zfill(6))
    except Exception:
        pass
    try:
        rt = _jload(RT_OPEN)
        if isinstance(rt, dict):
            for c, p in rt.items():
                if isinstance(p, dict) and float(p.get("qty", 0) or 0) > 0 and not p.get("_newpb"):
                    s.add(str(c).zfill(6))   # rt_open의 돌파(비_newpb) 보유분도 포함
    except Exception:
        pass
    return s


def _eod_held():
    """[CONFLICT 2026-06-27 ★6/26 3중매매 수정] 종가매수분(eod_gap·eod_pickup) 현재 보유 종목 set —
       NEW_PB가 같은종목 중복매수 차단(6/26 키스트론·삼익이 종가매수분과 동시보유=같은종목 자본 3배몰림).
       OPEN+qty>0만. eod_pickup은 nested{날짜:{코드:pos}}라 최근7일 날짜키만(오래된 stale OPEN 배제).
       env CONFLICT_EXCLUDE_EOD=NO로 끔. 실패→빈set(fail-safe·차단안함·기존동작)."""
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


def mode_pick():
    MAX_POS = int(os.environ.get("NEW_PB_MAX_POS", "5"))   # [MULTIPOS 2026-06-25 친구님] 동시보유 최대(1사이클 1매수 누적·하드캡)
    hm = datetime.now().strftime("%H%M")
    held = _jload(POS)
    opens = {c: p for c, p in held.items() if isinstance(p, dict) and p.get("status") == "OPEN"}
    if opens:
        _write_micro_watch(list(opens.keys()))   # ★보유종목 실시간 구독(체결강도로 트레일 판단)
        bc = _broker()
        if bc:
            _check_stops(bc, hm, held, opens)   # ★보유중이면 매 1분 장중손절 체크
        if len(opens) >= MAX_POS:
            return  # 최대 보유수 도달 = 신규매수 중단(손절체크만)
        # MAX_POS 미만 → 아래로 내려가 '보유외 다음 1등' 추가매수(사이클당 1개)
    if hm > BUY_CUTOFF:
        return  # 매수마감(15:00청산)
    bc = _broker()
    if not bc:
        _log(f"{hm} broker dead → 중단"); return
    today = datetime.now().strftime("%Y%m%d")
    slots = MAX_POS - len(opens)
    # [GLOBAL-BUDGET 2026-06-28 친구님] 전 전략 합산 동시보유 상한 → 남은 전역슬롯만큼만
    try:
        import position_budget as _gb
        if _gb.budget_on():
            _grem = _gb.remaining_intraday()   # [종가매수 보장 2026-06-29] EOD 예약분 제외한 잔여
            if _grem <= 0:
                _log(f"{hm} [GLOBAL-CAP] 전역 실보유 {_gb.total_open()}/{_gb.global_max()} 도달 → 신규매수 보류")
                return
            slots = min(slots, _grem)
    except Exception as _ge:
        _log(f"{hm} [GLOBAL-BUDGET] skip({_ge})")
    # [CHE-EXIT 2026-06-25] 재진입 캡: 오늘 MAX_LEGS회 진입후 청산된 종목은 재매수 제외(눌림 2번까지만)
    capped = {c for c, q in held.items()
              if isinstance(q, dict) and q.get("date") == today and q.get("status") == "CLOSED"
              and int(q.get("leg", 1)) >= MAX_LEGS}
    ranked = _score_ranked(bc, exclude=set(opens) | capped | _brk_held() | _eod_held())   # [MULTIPOS] 랭킹·[CONFLICT] 돌파+종가매수분 보유종목 제외(계좌섞임 방지)
    if not ranked:
        _log(f"{hm} 후보없음"); return
    bought = 0
    for i, best in enumerate(ranked):
        if bought >= slots or i >= 15: break   # 슬롯 다 참 or 상위15개까지만 게이트체크(부하 bound)
        sc, code, nm = best[0], best[1], best[2]
        bmid = best[6] if len(best) > 6 else 0
        blow = best[7] if len(best) > 7 else 0
        pblow = best[8] if len(best) > 8 else 0
        if sc < MIN_SCORE:
            if bought == 0: _log(f"{hm} 1등 {code} {nm[:8]} {sc:.0f}<{MIN_SCORE} NO_TRADE")
            break   # 랭킹 내림차순 → 1등도 문턱미달이면 이하 전부 미달
        gpass, greason, px = _entry_gate(bc, code, bmid, blow, pblow)   # 현재가 클린수집(prices_1m)
        if ENTRY_GATE and not gpass:
            _log(f"{hm} {code} {nm[:8]} {sc:.0f}점 게이트V3 WAIT({greason}) → 다음후보"); continue
        if px <= 0:
            _log(f"{hm} {code} 가격0 → skip"); continue
        # [RESTEP-CHE 2026-06-26 친구님] 재진입(leg≥2)이면 체결강도 게이트 — 칼날 재매수(서산-9.83%) 차단.
        prior = held.get(code)   # [CHE-EXIT] 재진입이면 leg 누적(2레그 캡 추적)
        is_reentry = isinstance(prior, dict) and prior.get("date") == today and int(prior.get("leg", 0)) >= 1
        if is_reentry and RESTEP_CHE > 0 and MICRO_USE:
            _rc = (_read_micro(code) or {}).get("che_str")
            if _rc is not None and _rc < RESTEP_CHE:
                _log(f"{hm} {code} {nm[:8]} 재매수보류: 체결강도 {_rc:.0f}<{RESTEP_CHE:.0f}(떨어지는칼날·매수약) → skip"); continue
        # [정배열 전용 2026-06-29 친구님 "정배열 눌림만·횡보·역배열 진입금지"] ★NEW_PB=눌림은 strict 정배열(MA5>MA20>MA60)일 때만.
        #   파마리서치(일봉 MA20<MA60=횡보)서 눌림산 게 문제 → strict면 애초 차단. 전역끄기 setx JEONGBAE_GATE NO.
        try:
            import trend_filter as _tf
            if not _tf.is_jeongbae(code, "strict"):
                _log(f"{hm} {code} {nm[:8]} 스킵(정배열 아님·횡보/역배열 진입금지)"); continue
        except Exception:
            pass
        # [FOREIGN-GATE 2026-06-28 친구님] 거래원 외국계 매도우세 게이트(env FOREIGN_GATE: LOG=기록만·BLOCK=보류)
        try:
            import foreign_supply as _fs
            if not _fs.buy_gate(code, log=_log, tag=f"{hm} NEW_PB"):
                continue
        except Exception:
            pass
        qty = max(1, int(CAP // px))
        _log(f"★NEW_PB 매수 {code} {nm} {sc:.0f}점 @{px:,} x{qty}={qty*px:,}원 ({len(opens)+bought+1}/{MAX_POS}) 게이트[PASS:{greason}]")
        if not _order(bc, code, qty, "BUY", "PICK"):
            if LIVE: continue
        leg = (int(prior.get("leg", 0)) + 1) if (isinstance(prior, dict) and prior.get("date") == today) else 1
        held[code] = {"code": code, "name": nm, "qty": qty, "buy_price": px, "score": sc, "buy_hm": hm,
                      "date": today, "status": "OPEN", "live": LIVE, "ts": datetime.now().isoformat(), "leg": leg}
        _jsave(POS, held)
        if leg > 1:
            _log(f"{hm} ↻ 재진입 {leg}레그 {code} {nm[:8]} (눌림 {leg}번째)")
        if LIVE:
            rt = _jload(RT_OPEN)
            # strategy=PULLBACK: 검증된 눌림 매도엔진(B고정·트레일·하드스톱) 그대로 물려받음
            rt[code] = {"qty": qty, "entry_price": px, "code": code, "strategy": "PULLBACK", "peak_price": px,
                        "stop_price": round(px * 0.95), "_newpb": 1, "_chejan_ts": datetime.now().isoformat()}
            _jsave(RT_OPEN, rt)
        opens[code] = held[code]; bought += 1
    if bought:
        _log(f"{hm} 이번사이클 {bought}개 매수 → 보유 {len(opens)}/{MAX_POS}")


def mode_sell():
    _log(f"=== NEW_PB sell (15:00 청산, LIVE={LIVE}) ===")
    held = _jload(POS)
    opens = {c: p for c, p in held.items() if isinstance(p, dict) and p.get("status") == "OPEN"}
    if not opens:
        _log("청산할 NEW_PB 없음"); return
    bc = _broker()
    if not bc and LIVE:
        _log("broker dead → 청산불가(★수동확인!)"); return
    for code, p in opens.items():
        cur = 0; pnl = 0.0   # [2026-06-23 친구님] 매도가 기록(매매일지용) — 청산시점 현재가 ≈ 체결가
        if bc:
            b = _gate_bars(bc, code); cur = b[-1][4] if b else 0
        if cur > 0:
            buy = float(p.get("buy_price", 0) or 0)
            pnl = (cur / buy - 1) * 100 if buy > 0 else 0
        if _order(bc, code, int(p["qty"]), "SELL", "SELL"):
            p["status"] = "CLOSED"; p["sell_date"] = datetime.now().strftime("%Y%m%d")
            if cur > 0:
                p["sell_price"] = cur; p["sell_reason"] = f"마감({pnl:.1f}%)"; p["sell_hm"] = datetime.now().strftime("%H%M")
            if LIVE:
                rt = _jload(RT_OPEN)
                if code in rt and rt[code].get("_newpb"):   # 꼬리표 PULLBACK이라 _newpb로 식별
                    del rt[code]; _jsave(RT_OPEN, rt)
            _log(f"청산 {code} x{p['qty']}" + (f" @{cur:,} ({pnl:+.1f}%)" if cur > 0 else ""))
    _jsave(POS, held)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pick"
    # [2026-06-19] 실제 작업프로세스가 보는 설정 덤프(env 전파 확인용·매 fire 덮어씀, 로그노이즈 0)
    try:
        _jsave(Path(r"C:\stock_bot\DATA\new_pb_runtime_config.json"), {
            "ts": datetime.now().isoformat(), "LIVE": LIVE, "OWN_EXIT": OWN_EXIT,
            "STAGE_TRAIL": STAGE_TRAIL, "STAGE_HARD_PCT": STAGE_HARD_PCT,
            "STOP_PCT_env": STOP_PCT, "TRAIL_PCT_env": TRAIL_PCT,
            "CHE_EXIT": CHE_EXIT, "TP_CAP": TP_CAP, "CHE_STRONG": CHE_STRONG,
            "RETR_WIDE": RETR_WIDE, "RETR_TIGHT": RETR_TIGHT, "RETR_ARM": RETR_ARM,
            "CHE_DROP_FRAC": CHE_DROP_FRAC, "MAX_LEGS": MAX_LEGS,
            "MIN_SCORE": MIN_SCORE, "CAP": CAP, "BUY_CUTOFF": BUY_CUTOFF})
    except Exception:
        pass
    try:
        (mode_pick if mode == "pick" else mode_sell)()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)

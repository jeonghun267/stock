# -*- coding: utf-8 -*-
"""
★★★ 직접실행 잠금(LOCKED) 2026-07-03 — 이 엔진의 run()은 폐기됨(런처 SAFEPLUS_MLR_RIDER.cmd 무력화). ★★★
사유: MLR라이더는 FAST_LEADER와 진입종목 69% 중복 → 통합 엔진 unified_leader_v1.py (SAFEPLUS_UNIFIED_LEADER) 로 대체.
      MLR의 '60선 이격' 경로는 통합의 ①강한대장 경로로 흡수됨.
⚠️ 파일 삭제/이동 금지: 통합엔진·GC560·반전엔진이 이 모듈을 헬퍼(_broker/_cur/_che/_fill_price/_jload/_jsave/RT_OPEN)로 import 함.
    = 모듈은 살아있어야 하고, '직접 실행(run 스케줄)'만 잠근 것.
아래는 원본 설계 설명(기록용):
[아침 대장 라이더 — 친구님 2026-06-30 직접 설계] 3분봉 차트 기준. 9시 대장 잡아서 타기.
   친구님 전략:
     · 대장 세력이 아침에 5선·체결강도로 흔들어 털어내도 → 3분봉 60선 이격 큰 대장은 무조건 다시 올라온다.
     · 점수(3분봉 60선 이격) 높은 대장은 고공이어도 9시 땡 하면 '무조건' 매수(어떤 조건이든).
   ★보유: 고정 익절 없음 — +30%든 끝까지 탄다.
   ★매도(2가지만):
     ① 3분봉 60선 캔들 이탈   ② 횡보가 5분 이상 지속(죽은 돈 회수)
     ※ 5선 이탈·체결강도 약화·윗꼬리·%익절로는 절대 안 판다(=세력 털기 트랩).
   ★매도하면 끝(재매수·회전 없음). 떨어졌다 다시 셋업되면 눌림·돌파 엔진이 자기 용도대로 잡는다(역할 분리).
   ★당일청산(EOD 15:18·오버나잇X).
   데이터: intraday_ma(전일 3분봉 시드 덕에 9시부터 3분봉 60선 존재). universe=거래대금 대장(leader_filter).
   ★안전: MLR_LIVE=NO면 전부 페이퍼(주문0). ★독립 엔진(EXIT_MA_LAYER/che_exit 안 씀)."""
import sys, json, uuid, os, time
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\stock_bot\RUN")

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
POS = Path(r"C:\stock_bot\DATA\mlr_positions.json")
LOG = Path(r"C:\stock_bot\data\LOG\morning_leader_rider.log")

LIVE        = os.environ.get("MLR_LIVE", "NO").strip().upper() == "YES"   # 기본 페이퍼(주문0)
TOPN        = int(os.environ.get("MLR_TOPN", "3"))                        # 9시에 살 대장 수(3분봉 60선 이격 상위)
CAP         = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))  # 종목당 금액(마스터 캡·전 전략 통합 30만)
ENTRY_END   = os.environ.get("MLR_ENTRY_END", "1020")                     # 신규 진입 마감(아침 윈도우)
EOD_HM      = os.environ.get("MLR_EOD_HM", "1518")                        # 당일청산
LEADER_TOPN = int(os.environ.get("MLR_LEADER_TOPN", "60"))                # universe = 거래대금 상위 N(대장)
DEV_TP      = float(os.environ.get("MLR_DEV_TP", "10"))                   # 익절 이격문턱%: 3분봉 60선에서 이만큼↑(멀리 뜸)+체결약 → 익절(꼭지)
CHE_WEAK    = float(os.environ.get("MLR_CHE_WEAK", "100"))                # 1분봉 체결강도 약함 기준(<100=매도우위)
CHE_N       = int(os.environ.get("MLR_CHE_N", "5"))                       # 체결약 연속 봉수(1분봉 N개 연속 약=매도세 지속)
MAGATE_PERIOD = int(os.environ.get("MLR_MAGATE_PERIOD", "60"))            # ★MA게이트 기간: 현재가<이 선(3분봉)이면 매수금지. 60=60선(완화)·120=120선(빡셈)·0=끔. 못구하면 통과(fail-open)
UPTREND     = os.environ.get("MLR_UPTREND", "NO").strip().upper() == "YES"  # ★[2026-07-02 친구님 "전일 역배열 지우자·체결량으로만"] 기본 OFF: 전일시드 40/60 역배열·기울기는 9시엔 어제 추세라 반전 종목을 막음 → 제거. 매수우위(che)로만 판단. 복원=setx MLR_UPTREND YES
DEV_MAX     = float(os.environ.get("MLR_DEV_MAX", "7"))                   # ★과열 상한(친구님 "너무 높이 올라갔어")=60선 이격 이 %초과면 추격금지(꼭지방지)·0=끔
EXIT_MA     = int(os.environ.get("MLR_EXIT_MA", "20"))                    # ★매도 기준선(친구님 60→20: 60선 너무 멀어 눌림에 다 토함)·60으로 되돌리면 원래 라이드
# ★[2026-07-02 친구님] 매수 게이트: "매수우위가 되어야만·3분 양봉일 때만 매수"(고점·매도우위 추격 차단).
BUY_CHE_GATE = os.environ.get("MLR_BUY_CHE_GATE", "YES").strip().upper() == "YES"   # 매수우위(체결강도) 게이트 ON
BUY_CHE_MIN  = float(os.environ.get("MLR_BUY_CHE_MIN", "100"))            # ★매수우위 문턱: 체결강도 이 값 미만(=매도우위)이면 매수금지. 100=매수/매도 균형점(친구님 "100가자")
BUY_GREEN_GATE = os.environ.get("MLR_BUY_GREEN_GATE", "NO").strip().upper() == "YES"  # ★[2026-07-02 친구님] 기본 OFF: 3분 양봉 확인은 '바닥'용(반전엔진)이라 MLR(대장 빠르게 타기)엔 늦음(상승 대장 놓침) → 제거. 복원=setx MLR_BUY_GREEN_GATE YES
HOLD_ON_CHE = os.environ.get("MLR_HOLD_ON_CHE", "YES").strip().upper() == "YES"  # ★[2026-07-02 친구님 "매수우위면 20선도 끌기"] 매수우위(체결강도≥CHE_WEAK)면 3분봉 20선 이탈에도 안 팔고 홀드(끌기). 매도우위로 돌면 그때 vol_exit이 5선/저점/음봉/고점-%로 매도. 검증사례 131290(매도시 che126 매수우위인데 20선이탈로 성급매도→이후 +5.3% 회복). 롤백 NO
MAX_FAIL    = int(os.environ.get("MLR_MAX_FAIL", "2"))                    # [7/2] 매수 주문 실패(플래그/게이트/충돌거부) 최대 재시도. 초과시 오늘 그 종목 스킵(무한 재시도·브로커부하 차단)
MIN_HOLD_SEC = int(os.environ.get("MLR_MIN_HOLD_SEC", "180"))             # ★[7/2 친구님 "사자마자 57초 손절"] 매수 후 이 시간(초) 이내엔 개장 노이즈(체결강도 순간<100·직전저점 순간이탈)로 인한 성급매도 skip. 대장 라이드(60선/횡보까지 탐). EOD·하드는 무관. 0=끔
GRACE_HARD  = float(os.environ.get("MLR_GRACE_HARD", "5.0"))              # ★[7/2 친구님] 유예(MIN_HOLD_SEC) 중이라도 -이 %넘게 빠지면 즉시 매도(급락 방어). 0=유예중 완전무방비


def _uptrend(c):
    """★친구님 게이트(intraday_ma 계산 재사용): 5<20<40<60 역배열 우하향=매수금지 · 60·20선 우상향(3봉전대비) 아니면 금지. fail-safe 통과."""
    try:
        import intraday_ma as im
        cl = im._series(c)
        m5, m20, m40, m60 = im._ma_at(cl, 5, 0), im._ma_at(cl, 20, 0), im._ma_at(cl, 40, 0), im._ma_at(cl, 60, 0)
        if None not in (m5, m20, m40, m60) and m5 < m20 < m40 < m60:
            return False
        for w in (60, 20):
            now, prev = im._ma_at(cl, w, 0), im._ma_at(cl, w, 3)
            if now is not None and prev is not None and now < prev:
                return False
        return True
    except Exception:
        return True
ACCOUNT     = os.environ.get("SWING_ACCOUNT", "").strip()


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(s + "\n")
    except Exception: pass


def _jload(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _broker():
    from broker_client import BrokerClient, is_broker_alive
    return BrokerClient() if is_broker_alive() else None


def _order(bc, code, qty, side, tag, live=None):
    # [FIX 2026-07-01] live=None → 전역 LIVE 사용(매수). 매도는 포지션이 매수시점에
    #   기록한 live 플래그를 넘겨받아 그 모드로 처리(전역 LIVE가 중간에 바뀌어도
    #   페이퍼로 산 포지션을 라이브로 팔거나, 라이브 포지션을 페이퍼로 방치하지 않게).
    _live = LIVE if live is None else bool(live)
    if not _live:
        _log(f"[{tag}][모의] {side} {code} x{qty} (페이퍼)"); return True
    try:
        global ACCOUNT
        if not ACCOUNT:
            ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
            ACCOUNT = accs[0] if accs else ""
        if not ACCOUNT:
            _log(f"[{tag}] 계좌없음→주문불가"); return False
        r = bc.send_order_real(idempotency_key=f"mlr_{side.lower()}_{code}_{uuid.uuid4()}", account=ACCOUNT,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"MLR_{side}_{code}", screen_no="9712")
        _st = str((r or {}).get("status", "")).upper()
        _ok = (_st in ("OK", "TIMEOUT")) if side == "BUY" else (_st == "OK")
        _log(f"[{tag}][LIVE] {side} {code} x{qty} status={_st or 'EMPTY'} → {'성공' if _ok else '실패처리'}")
        return _ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _fill_price(bc, code, since_dt, timeout=3.0):
    """★[2026-07-02 유령앵커버그 수정] 실체결가(FID 910) 조회.
    방금 보낸 매수주문의 체결통보(order_shadow_ack, 브로커 게이트웨이가 기록)를 짧게 폴링해
    '실제로 체결된 단가'를 반환. 못 구하면 0.0 (호출측이 스냅샷 폴백).
    - since_dt: 주문 직전 시각(datetime) — 이 시각 이후 ACK만 인정(과거 동일종목 주문 오매칭 차단).
    - 스냅샷 cur(장시작 동시호가 예상체결가 유령값)이 아니라 실체결가를 앵커로 쓰기 위함.
    이 헬퍼는 GC560/reversal 실행기도 R._fill_price로 공유(동일 스냅샷 앵커 버그 일괄 수정)."""
    try:
        target = str(code).zfill(6)
        cutoff = since_dt - timedelta(seconds=5)   # 프로세스 간 미세 시계차 허용(과거주문은 분단위라 무영향)
        seen = {}
        deadline = time.time() + timeout
        best = 0.0
        while time.time() < deadline:
            try:
                acks = bc.consume_order_shadow_ack(seen)
            except Exception:
                acks = []
            for ev in acks:
                try:
                    fd = ev.get("fid_data", {}) or {}
                    # 시각 필터(이 주문 이후 체결통보만)
                    tsr = ev.get("ts_broker_relay") or ev.get("ts_broker_callback") or ""
                    try:
                        if tsr and datetime.fromisoformat(str(tsr)) < cutoff:
                            continue
                    except Exception:
                        pass
                    craw = str(ev.get("code") or fd.get("9001", ""))
                    cc = "".join(ch for ch in craw if ch.isdigit())[-6:].zfill(6)
                    if cc != target:
                        continue
                    otype = str(ev.get("order_direction") or fd.get("905", ""))
                    if not (("매수" in otype) or otype.startswith("+")):
                        continue
                    st = str(ev.get("state") or fd.get("913", ""))
                    if "체결" not in st:                 # 접수/확인 제외, 실체결만
                        continue
                    p = float(ev.get("filled_price") or fd.get("910", 0) or 0)
                    if p > 0:
                        best = abs(p)                    # FID 910 매수는 +부호로 올수 있음
                except Exception:
                    continue
            if best > 0:
                return best
            time.sleep(0.25)
        return best
    except Exception:
        return 0.0


def _cur(code):
    """현재가: 1초 스냅샷 우선, 없으면 당일 3분봉 마지막 종가."""
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8")).get("codes", {})
        v = snap.get(str(code).zfill(6))
        if isinstance(v, dict):
            c = float(v.get("cur", 0) or 0)
            if c > 0: return c
    except Exception:
        pass
    try:
        import intraday_ma as _im
        b = _im.bars3(code)
        return float(b[-1]) if b else 0.0
    except Exception:
        return 0.0


def _ma60(code):
    try:
        import intraday_ma as _im
        return float(_im.ma60(code) or 0.0)
    except Exception:
        return 0.0


def _green3(bc, code):
    """★[2026-07-02] 최근 3분봉 양봉(종가≥시가)? opt10080 틱범위3 시가/현재가.
       매수우위(che)를 이미 통과한 소수 종목에만 호출(TR 최소화).
       True=양봉·False=음봉·None=조회실패(호출측 fail-open)."""
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["시가", "현재가"], timeout_sec=6.0, screen_no="9713")
        recs = ((r or {}).get("data") or {}).get("records") or []
        if not recs:
            return None
        def _f(x):
            try: return abs(float(str(x).replace(",", "")))
            except Exception: return 0.0
        o = _f(recs[0].get("시가")); c = _f(recs[0].get("현재가"))   # recs[0]=최신(형성중) 3분봉
        if o <= 0 or c <= 0:
            return None
        return c >= o
    except Exception:
        return None


def _ma_gate(code):
    """3분봉 MAGATE_PERIOD선(전일 시드 포함). 봉 부족하면 0(=판정불가→fail-open)."""
    try:
        import intraday_ma as _im
        return float(_im.ma(code, MAGATE_PERIOD) or 0.0)
    except Exception:
        return 0.0


def _che(code):
    """1분봉 실시간 체결강도(스냅샷 che_str). 100미만=매도우위. 없으면 None."""
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8")).get("codes", {})
        v = snap.get(str(code).zfill(6))
        if isinstance(v, dict):
            ch = v.get("che_str")
            if isinstance(ch, (int, float)):
                return float(ch)
    except Exception:
        pass
    return None


def _universe(bc):
    try:
        import leader_filter as _lf
        lst = _lf.leader_list(bc) or []
        return list(lst)[:LEADER_TOPN]
    except Exception as e:
        _log(f"universe(leader) 실패 {e}"); return []


def _score(codes):
    """대장 랭킹. ★MLR_RANK_CHE=YES(기본): 체결강도(매수 강도=아주 강한놈) 우선·이격 tiebreak. NO: 기존 이격순.
       둘다 60선 위(이격>0)만·MAGATE선 위만. (친구님 "이격은 이미 오른것·강도를 봐야 로켓")"""
    rank_che = os.environ.get("MLR_RANK_CHE", "YES").strip().upper() == "YES"
    out = []
    for c in codes:
        ma60 = _ma60(c); cur = _cur(c)
        if ma60 <= 0 or cur <= 0:
            continue
        if MAGATE_PERIOD > 0:                           # ★3분봉 MAGATE선 아래 = 매수금지(약한추세). 못구하면 통과(fail-open)
            mg = _ma_gate(c)
            if mg > 0 and cur < mg:
                continue
        dev = (cur / ma60 - 1) * 100.0
        if dev > 0:
            che = _che(c) if rank_che else None
            chek = float(che) if isinstance(che, (int, float)) else -1.0
            out.append((dev, c, cur, ma60, chek))
    if rank_che:
        out.sort(key=lambda x: (x[4], x[0]), reverse=True)   # ★체결강도 우선(강도=아주 강한놈)·이격 tiebreak
    else:
        out.sort(reverse=True)
    return [(d, c, cu, m) for (d, c, cu, m, k) in out]


def _sec(t):
    try:
        hh, mm, ss = t.split(":"); return int(hh) * 3600 + int(mm) * 60 + int(ss)
    except Exception:
        return 0


def _is_flat(p, cur, now_ts):
    """횡보 판정: 최근 FLAT_MIN분 가격 누적 → 폭<FLAT_BAND%면 횡보(매도). 시각 샘플은 position의 px_hist."""
    hist = p.get("px_hist", [])
    hist.append([now_ts, cur])
    now_s = _sec(now_ts)
    hist = [h for h in hist if now_s - _sec(h[0]) <= FLAT_MIN * 60 + 90]   # 오래된 샘플 제거
    p["px_hist"] = hist
    span = now_s - _sec(hist[0][0]) if hist else 0
    if span < FLAT_MIN * 60:                  # 아직 FLAT_MIN분치 안 쌓임
        return False
    prices = [h[1] for h in hist]
    lo, hi = min(prices), max(prices)
    if lo <= 0:
        return False
    return ((hi - lo) / lo * 100.0) < FLAT_BAND


def _held_now():
    s = set()
    for c, v in _jload(RT_OPEN).items():
        if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0:
            s.add(str(c).zfill(6))
    return s


def run():
    now_t = datetime.now()
    now = now_t.strftime("%H%M"); now_ts = now_t.strftime("%H:%M:%S")
    if now < "0900" or now > "1530":
        return
    bc = _broker()
    if not bc and LIVE:
        _log("broker dead → 보류"); return
    held = _jload(POS); today = now_t.strftime("%Y%m%d")

    # ===== ★[2026-07-02] 실체결가 보정 =====
    # 매수시점에 실체결가(FID 910)를 못 구해 임시로 스냅샷을 박은 포지션을, 다음 사이클에
    # 실체결가로 덮어씀(유령 스냅샷 앵커 잔존 방지). ACK 300s TTL 내(다음 분)에 대부분 확정.
    if LIVE and bc:
        _rec_changed = False
        for c, p in list(held.items()):
            if not isinstance(p, dict) or p.get("date") != today or p.get("status") != "HOLDING":
                continue
            if p.get("fill_confirmed"):
                continue
            try:
                _since = datetime.fromisoformat(p.get("ts")) if p.get("ts") else (now_t - timedelta(minutes=10))
            except Exception:
                _since = now_t - timedelta(minutes=10)
            _f = _fill_price(bc, c, _since, timeout=0.8)
            if _f > 0:
                _old = p.get("buy_price")
                p["buy_price"] = _f; p["fill_confirmed"] = True; p["buy_price_src"] = "FILL"
                _rec_changed = True
                _log(f"[FILL-RECONCILE] {c} 매수가 보정 {_old} → 실체결 {_f:,.0f}")
                try:
                    _rt = _jload(RT_OPEN)
                    if isinstance(_rt.get(c), dict):
                        _rt[c]["entry_price"] = _f
                        if float(_rt[c].get("peak_price", 0) or 0) < _f:
                            _rt[c]["peak_price"] = _f
                        _jsave(RT_OPEN, _rt)
                except Exception:
                    pass
        if _rec_changed:
            _jsave(POS, held)

    # ===== EOD 당일청산 =====
    if now >= EOD_HM:
        for c, p in list(held.items()):
            if isinstance(p, dict) and p.get("status") == "HOLDING" and float(p.get("qty", 0) or 0) > 0:
                if _order(bc, c, p["qty"], "SELL", "EOD청산", live=p.get("live", LIVE)):
                    p["status"] = "DONE"; p["exit_reason"] = "EOD"
        _jsave(POS, held); return

    # ===== 보유관리: ①60선 이탈 ②횡보5분 매도 (고정 익절 없음·끝까지 탐·매도하면 끝) =====
    for c, p in list(held.items()):
        if not isinstance(p, dict) or p.get("date") != today or p.get("status") != "HOLDING":
            continue
        cur = _cur(c); ma60 = _ma60(c)
        try:
            import intraday_ma as _im2; ma_exit = float(_im2.ma(c, EXIT_MA) or 0.0)
        except Exception:
            ma_exit = ma60
        if cur <= 0:
            continue
        # 1분봉 체결강도 누적(약함 지속 판정용)
        che = _che(c); ch = p.get("che_hist", [])
        if che is not None:
            ch.append(che); ch = ch[-CHE_N:]; p["che_hist"] = ch
        # ★[초단타 손절 방지 2026-07-02 친구님 "사자마자 57초 손절"] 매수 후 MIN_HOLD_SEC 이내면 성급매도 skip.
        #   개장 직후 1~2분은 체결강도 순간<100(매도우위)·직전저점 순간이탈이 흔해 vol_exit/20선이 즉시 발동→57초 손절.
        #   대장 라이드 철학(60선/횡보까지 탐)이라 이 유예 동안 홀드. EOD청산은 위에서 이미 처리(무관).
        if MIN_HOLD_SEC > 0:
            try:
                _age = (now_t - datetime.fromisoformat(p["ts"])).total_seconds() if p.get("ts") else 9999.0
            except Exception:
                _age = 9999.0
            if _age < MIN_HOLD_SEC:
                # ★[7/2 친구님] 유예 중이라도 하드손절(-GRACE_HARD%)은 발동 — 급락(칼떨어짐) 방어.
                _buyp = float(p.get("buy_price", 0) or 0)
                if GRACE_HARD > 0 and _buyp > 0 and (cur / _buyp - 1) * 100 <= -GRACE_HARD:
                    if _order(bc, c, p["qty"], "SELL", f"유예중하드-{GRACE_HARD:g}", live=p.get("live", LIVE)):
                        p["status"] = "DONE"; p["exit_reason"] = "GRACE_HARD"
                        _log(f"★매도(유예중 하드-{GRACE_HARD:g}%) {c} @{cur:,.0f} (매수 {_buyp:,.0f})")
                    _jsave(POS, held)
                    continue
                _jsave(POS, held)   # che_hist 누적 저장
                continue
        # [통일 매도 2026-07-01 친구님 "수급 주입"] 수급(체결강도 매수/매도 우위) 조기매도: 매수우위=보유(끌기)·매도우위+20/5선·장대음봉·저점이탈=매도.
        _peak_mlr = max(float(p.get("peak", cur) or cur), cur); p["peak"] = _peak_mlr
        # [부분익절 2026-07-02 #3] +PARTIAL_TP%서 절반 익절·나머지 끌기(30만 1주 무동작·1억서 실효).
        try:
            import vol_exit as _VEp
            _VEp.do_partial(p, cur, lambda q, t: _order(bc, c, q, "SELL", t, live=p.get("live", LIVE)), str(RT_OPEN), _log)
        except Exception:
            pass
        if os.environ.get("UNIFIED_VOL_EXIT", "YES").strip().upper() == "YES":
            try:
                import vol_exit as _VE
                _s, _r = _VE.decide(c, cur, _peak_mlr, cur, ma20_hard=True, che=che)
                if _s:
                    if _order(bc, c, p["qty"], "SELL", _r, live=p.get("live", LIVE)):
                        p["status"] = "DONE"; p["exit_reason"] = _r
                        _log(f"★매도(수급:{_r}) {c} @{cur:,.0f}")
                    continue
            except Exception:
                pass
        # ★[2026-07-02 친구님] 매수우위(체결강도≥CHE_WEAK)면 3분봉 20선 이탈에도 끌기(홀드). 매도우위로 돌면 위 vol_exit이 매도.
        _buy_dom = HOLD_ON_CHE and isinstance(che, (int, float)) and che >= CHE_WEAK
        if ma_exit > 0 and cur < ma_exit and not _buy_dom:               # ①3분봉 20선 이탈 → 청산(단 매수우위면 끌기)
            if _order(bc, c, p["qty"], "SELL", f"{EXIT_MA}선이탈", live=p.get("live", LIVE)):
                p["status"] = "DONE"; p["exit_reason"] = f"BREAK{EXIT_MA}"
                _log(f"★매도({EXIT_MA}선이탈) {c} @{cur:,.0f} < {EXIT_MA}선 {ma_exit:,.0f}")
        elif ma_exit > 0 and cur < ma_exit and _buy_dom:                 # 매수우위 → 20선 깨져도 홀드(끌기)
            _log(f"[홀드-매수우위] {c} 3분봉 {EXIT_MA}선({ma_exit:,.0f}) 이탈이나 체결강도 {che:.0f}≥{CHE_WEAK:.0f}=매수우위 → 끌기(안팜)")
        else:                                                            # ②이격 크다(멀리뜸)+1분봉 체결 지속약함 → 익절(꼭지). 60선 근처면 보유(털기)
            dev = (cur / ma60 - 1) * 100.0 if ma60 > 0 else 0.0
            che_weak = len(ch) >= CHE_N and all(x < CHE_WEAK for x in ch)
            if dev >= DEV_TP and che_weak:
                if _order(bc, c, p["qty"], "SELL", "이격체결익절", live=p.get("live", LIVE)):
                    p["status"] = "DONE"; p["exit_reason"] = "DEV_CHE"
                    _log(f"★매도(이격{dev:.0f}%+체결약{che:.0f}) {c} @{cur:,.0f}")
    _jsave(POS, held)
    # 매도된 종목은 rt_open에서 제거. [FIX 2026-07-01] 전역 LIVE가 아니라 rt_open에
    #   실제 있는 DONE 종목을 제거(라이브로 담겼던 포지션은 전역 LIVE가 바뀌어도 정리).
    rt = _jload(RT_OPEN); changed = False
    for c, p in held.items():
        if isinstance(p, dict) and p.get("status") == "DONE" and c in rt:
            rt.pop(c, None); changed = True
    if changed: _jsave(RT_OPEN, rt)

    # ===== 신규 진입: 9시~ENTRY_END, 3분봉 60선 이격 상위 대장 무조건 매수 =====
    if now > ENTRY_END:
        return
    open_cnt = sum(1 for v in held.values() if isinstance(v, dict) and v.get("date") == today and v.get("status") == "HOLDING")
    if open_cnt >= TOPN:
        return
    # 전역 한도(친구님 200만·다른 엔진과 동일): 자리/예산 없으면 보류. 9시에 먼저 돌아 대장 우선권은 유지. fail-open.
    try:
        import position_budget as _gb
        if _gb.budget_on() and _gb.remaining_intraday() <= 0:
            _log("[GLOBAL-CAP] 전역상한 → 진입보류"); return
    except Exception:
        pass
    uni = _universe(bc)
    if not uni:
        _log("universe 비어있음 → 진입보류"); return
    ranked = _score(uni); excl = _held_now()
    _log(f"=== MLR 진입스캔 (LIVE={LIVE} TOPN={TOPN} CAP={CAP:,}) 대장 {len(uni)} → 60선위 {len(ranked)} ===")
    for dev, c, cur, ma60 in ranked:
        if open_cnt >= TOPN: break
        # 오늘 이미 잡았던 종목은 재진입 안 함(회전 없음). [실패상한 2026-07-02] 실패(FAILED)도 MAX_FAIL 초과면 스킵(무한 재시도 차단).
        if c in excl:
            continue
        _he = held.get(c)
        if isinstance(_he, dict) and _he.get("date") == today:
            if _he.get("status") in ("HOLDING", "DONE"):
                continue
            if _he.get("status") == "FAILED" and int(_he.get("fails", 0)) >= MAX_FAIL:
                continue
        if UPTREND and not _uptrend(c):            # ★우상향·역배열아님만(친구님)=하락 대장 무조건매수 방지
            _log(f"[SKIP-우하향] {c} 이격+{dev:.1f}%나 5/20/60 우하향 or 역배열 → 매수보류"); continue
        if DEV_MAX > 0 and dev > DEV_MAX:          # ★과열 상한(친구님)=이미 꼭지(이격 큰) 추격 금지
            _log(f"[SKIP-과열] {c} 이격+{dev:.1f}% > {DEV_MAX:.0f}% → 추격금지(꼭지)"); continue
        # ★[2026-07-02 친구님] 매수우위 게이트: 체결강도<문턱(=매도우위)이면 매수금지.
        #   che None(스냅샷 없음)=매수우위 확인불가 → 매수금지(fail-closed, "매수우위 되어야만"). 롤백 MLR_BUY_CHE_GATE=NO.
        if BUY_CHE_GATE:
            _cche = _che(c)
            if _cche is None or _cche < BUY_CHE_MIN:
                _log(f"[SKIP-매도우위] {c} 체결강도 {_cche}<{BUY_CHE_MIN:.0f}(매수우위 아님) → 매수보류"); continue
        # ★[2026-07-02 친구님] 3분봉 양봉 게이트: 음봉이면 매수금지(떨어지는 칼 안 잡음).
        #   조회실패(None)=fail-open(체결강도는 이미 통과). 롤백 MLR_BUY_GREEN_GATE=NO.
        if BUY_GREEN_GATE:
            _g3 = _green3(bc, c)
            if _g3 is False:
                _log(f"[SKIP-음봉] {c} 3분봉 음봉 → 매수보류(양봉만)"); continue
        qty = max(1, int(CAP // cur))
        _log(f"★매수(무조건) {c} 이격+{dev:.1f}% @{cur:,.0f} x{qty} (60선 {ma60:,.0f})")
        _t_send = datetime.now()
        if _order(bc, c, qty, "BUY", "진입"):
            # ★[2026-07-02] 매수가 앵커 = 실체결가(FID 910). 스냅샷 cur(동시호가 유령 예상체결가)로
            #   박제하던 버그 수정. 실체결가 못 구하면(TIMEOUT 등) 임시로 cur 사용하고 fill_confirmed=False로
            #   표시 → manage() 다음 사이클에서 실체결가로 보정.
            _fill = _fill_price(bc, c, _t_send) if LIVE else 0.0
            _bp = _fill if _fill > 0 else cur
            _confirmed = bool(_fill > 0)
            if LIVE and not _confirmed:
                _log(f"[FILL-PENDING] {c} 실체결가 미확인 → 임시 스냅샷 @{cur:,.0f} (다음 사이클 보정)")
            elif LIVE:
                _log(f"[FILL] {c} 실체결가 @{_bp:,.0f} (스냅샷은 {cur:,.0f})")
            held[c] = {"code": c, "qty": qty, "buy_price": _bp, "dev60": round(dev, 2),
                       "date": today, "status": "HOLDING", "px_hist": [], "ts": now_t.isoformat(),
                       "live": LIVE,                          # [FIX 2026-07-01] 매수시점 모드 고정 → 매도가 이 값으로 판정
                       "fill_confirmed": _confirmed, "buy_price_src": ("FILL" if _confirmed else "SNAP")}
            if LIVE:
                rt = _jload(RT_OPEN); rt[c] = {"qty": qty, "entry_price": _bp, "code": c, "strategy": "MLR", "peak_price": _bp}
                _jsave(RT_OPEN, rt)
            open_cnt += 1
        else:
            # [실패상한 2026-07-02] 매수 실패(플래그/게이트/다른엔진이 먼저 잡아 거부)를 매 사이클 무한 재시도하던 것 차단.
            #   실패도 held에 누적 기록 → MAX_FAIL 초과시 오늘 그 종목 스킵(7/2 298380 9회·033100 8회 재시도).
            _fe = held.get(c) if isinstance(held.get(c), dict) else {}
            _fails = (int(_fe.get("fails", 0)) + 1) if _fe.get("date") == today else 1
            held[c] = {"code": c, "date": today, "status": "FAILED", "fails": _fails, "ts": now_t.isoformat()}
            _log(f"[매수실패] {c} 누적{_fails}회" + (f" → 오늘 재시도중단(≥{MAX_FAIL})" if _fails >= MAX_FAIL else ""))
    _jsave(POS, held)


if __name__ == "__main__":
    try: run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()

# -*- coding: utf-8 -*-
"""🕳🔥 급락주 20분단타 체결강도 매매기 — ★실시간(기본 그림자·주문0)  [2026-07-15 신설]

친구님 확정 전략 (급락주 09:00~09:20):
  매수 : ★[7/16 밤 수술] low_anchor_buy_v1.LowAnchor로 교체 — 7/16 아침 실전 대실패
         (8종목 중 4종목이 진입 즉시 일봉5일선이탈로 0초 청산·나머지는 꼭지매도가 3~9분
         만에 터져 -2.45%~-3.14% 손실 = 저점이 아니라 반등 꼭대기 근처에서 사고 있었다)
         원인 수술: 저점 대비 +LA_OBS_PCT%(기본1.2%) 반등 지점까지 관찰 → 그 순간 체결강도로
         3단계 판정(≥150 강한매수/100~150 기본매수/<100 관망·신저점 재대기).
         기존 CF_LOW_HOLD(7분 고정대기)+CF_GAP(0.5%)+CF_BUY_CHE(105 단일컷)는 이 로직으로 대체됐다.
         (9거래일 백테: che필터 있음 평균+0.9~1.9% vs 없음 거의0% — low_anchor_buy_v1.py 참고)
  매도 : ① 꼭지 = 양봉→음봉(완성봉) ∧ 그 음봉 체결강도 < 문턱
         ② 방어 = 일봉 5일선 이탈  (그림자 백테 최고 +2.57%·89%)  또는 1분봉 5분선 이탈
         ③ 재난손절 -4% (유예 없음)   ④ 09:20 전량청산
  유니버스 : 코스닥·1만원↑·★어제대금 700억~2조 (7/15 친구님 "700억~2조에서 선별"·CF_PVAL_MIN=700)
  정렬     : ★갭하락(시가 전일比 -3%↓) 무조건 1순위 → 깊이순 (7/15 친구님 지시·CF_GAP_TH)

■ ★안전 (아침대장 morning_captain_live 구조 그대로)
  CF_LIVE=NO 가 기본 = 실주문 0(그림자). 실전은 cmd(SAFEPLUS_CRASH_FLOW_LIVE.cmd)가 CF_LIVE=YES 설정.
  끄기 = config\crash_off.flag 생성(다음 기동부터 그림자·setx CF_LIVE NO 는 cmd가 이겨서 무효).
  장중 즉시정지 = config\manual_buy_block.flag (매수 차단·매도는 계속 = 보유분 정리 가능).
  주문 격리 rqname=CRASHFLOW_ (깊은바닥·아침대장과 분리). 실주문 켤 땐 관문 ONLY_MF_ALLOW 확인 필요.

■ ★실시간 봉 주의 (교훈 top-sell-frame-bug)
  양봉→음봉은 '완성봉'으로만 판정한다(돈맥_1분봉.json prev = 직전 완성봉들). 진행중 봉으로 안 판다.

■ 스위치
  CF_LIVE=NO         실주문 (기본 NO=그림자·주문0)
  CF_CAP             종목당 금액 (기본 SAFEPLUS_CAP_KRW=30만)   CF_SLOTS=3
  CF_SELL_CHE=100    매도(음봉) 체결강도 문턱
  CF_DEFENSE=d5      방어선 d5=일봉5일선 / ma5=1분봉5분선       CF_STOP=-4  재난손절
  CF_DROP=-4  급락 기준(유니버스 등재용)   CF_EXIT=0920   CF_END=0922
  ★매수 진입 문턱(LA_ARM_PCT/LA_OBS_PCT/LA_BUY_CHE/LA_STRONG_CHE)은 low_anchor_buy_v1.py 참고
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\stock_bot\RUN")
import shared_slots as shared      # [7/16] 공통 슬롯 장부(아침대장과 총 200만·6슬롯 공유)
from low_anchor_buy_v1 import la_from_ledger, la_to_ledger, REBUY_STOP, REBUY_MAX   # ★[7/17] 저점구간 판정+저점재매수

SNAP   = Path(os.environ.get("CF_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
BARS1M = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
POOL   = Path(r"C:\stock_bot\data\돈맥_전일상위풀.json")
CHE    = Path(r"C:\stock_bot\data\돈흐름_che_state.json")
EOD    = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
NAMEC  = Path(r"C:\stock_bot\data\_code_name_cache.json")
LEDGER = Path(os.environ.get("CF_LEDGER") or r"C:\stock_bot\data\crash_flow_live_ledger.json")
CSVLOG = Path(os.environ.get("CF_CSV") or r"C:\stock_bot\LOG\crash_flow_live.csv")
LOG    = Path(r"C:\stock_bot\data\LOG\crash_flow_live.log")

LIVE     = os.environ.get("CF_LIVE", "NO").strip().upper() == "YES"
CAP      = float(os.environ.get("CF_CAP") or os.environ.get("SAFEPLUS_CAP_KRW", "300000"))
SLOTS    = int(os.environ.get("CF_SLOTS", "3"))
SELL_CHE = float(os.environ.get("CF_SELL_CHE", "100"))
DEFENSE  = os.environ.get("CF_DEFENSE", "d5").strip().lower()     # d5 / ma5
STOP     = float(os.environ.get("CF_STOP", "-4"))
TRAIL    = float(os.environ.get("CF_TRAIL", "-2"))   # ★[7/16 친구님 "고점 -2% 매도 보강"] 고점 대비 %·0이면 끔
DROP     = float(os.environ.get("CF_DROP", "-4"))
# ★[7/17 낮 친구님 지시] 매도 전면개편 — 고점앙커(peak) 기준. FLAT 안전판(09:23/09:24)과 겹쳐 시간연장(10시)은 오늘 보류.
PEAK_WATCH_PCT = float(os.environ.get("CF_PEAK_WATCH_PCT", "-1"))   # 고점 대비 이만큼(%) 빠지면 관찰 시작(즉시매도 아님)
PEAK_HARD_PCT  = float(os.environ.get("CF_PEAK_HARD_PCT", "-2"))    # 고점 대비 이만큼(%) 빠지면 관찰 없이 즉시매도
PEAK_WATCH_SEC = float(os.environ.get("CF_PEAK_WATCH_SEC", "10"))   # 관찰 최대 시간(초)
PEAK_SELL_RATIO = float(os.environ.get("CF_PEAK_SELL_RATIO", "50")) # 관찰 종료 시점 매도비율(%) 이 이상이면 매도 확정
REBUY_COOLDOWN_SEC = float(os.environ.get("CF_REBUY_COOLDOWN_SEC", "1800"))  # ★30분 — 매도 후 재매수 금지 시간

PX_FLR   = float(os.environ.get("CF_PX_FLOOR", "10000"))
PVAL_LO  = float(os.environ.get("CF_PVAL_MIN", "300"))
PVAL_HI  = float(os.environ.get("CF_PVAL_MAX", "20000"))
GAP_TH   = float(os.environ.get("CF_GAP_TH", "-3"))    # ★갭하락 1순위 문턱(시가 전일比 %·깊은바닥 MF_DEEP_GAP과 동일 -3)
ENTRY_HM = os.environ.get("CF_ENTRY", "0900")
ENTRY_END = os.environ.get("CF_ENTRY_END", "0918")
EXIT_HM  = os.environ.get("CF_EXIT", "0920")
END_HM   = os.environ.get("CF_END", "0922")
LOOP_SEC = float(os.environ.get("CF_LOOP_SEC", "2"))
RUN_SEC  = float(os.environ.get("CF_RUN_SEC", "55"))
# ★[7/16 수술③ 유령왕복] 접수OK ≠ 체결(broker_client 계약: 실체결은 Chejan 별도) — 아침대장 기가레인이
#   접수만 되고 체결 0인데 유령 +1.12% 기록. 이 엔진도 동일 구멍이라 친구님 승인으로 동일 배선.
#   매수 후 FILL_WAIT초 안에 게이트웨이 fills CSV에서 체결확인 못 하면 미체결 잔량 취소 → 유령 판정.
#   확인 전엔 보유 아님(매도 안 함). 아침대장(MC_FILL_WAIT)과 동일 구조.
FILL_WAIT = float(os.environ.get("CF_FILL_WAIT", "8"))

COLS = ["일자", "시각", "종목코드", "종목명", "방향", "사유", "체결강도", "고점", "저점",
        "현재가", "일봉5일선", "진입가", "수익퍼센트", "재매수회차", "실전여부", "주문결과",
        "매수비율", "구간매수량", "구간매도량", "판정사유"]   # ★[7/17] 저점구간 매수/매도 비율 A/B 비교용

# ★[7/16 안전수술①-2] 주문 최후 관문 미러 — CRASHFLOW rqname은 MFLOW 예외가 없어
#   브로커 관문의 가격하한(SAFEPLUS_MIN_PRICE)·시총하한(SAFEPLUS_MIN_MARKETCAP)이 그대로 적용된다(7/14 잡주 사고형).
#   급락주는 매수 시점 가격이 전일比 -5~-10%라 전일종가 1만~1.1만 종목은 가격하한에 걸린다.
#   → 지금 가격으로 못 살 종목은 주문 시도 자체를 건너뛴다(2초마다 조용한 거부 반복 방지).
#   발행주식수 모르면 통과(fail-open) = 진짜 관문(broker_client)이 최종 방어. 관문 로직과 반드시 거울 유지.
GATE_MINP  = float(os.environ.get("SAFEPLUS_MIN_PRICE", "1000"))
GATE_MINMC = float(os.environ.get("SAFEPLUS_MIN_MARKETCAP", "0"))
SHARES_CSV = Path(r"C:\stock_bot\DATA\shares_outstanding.csv")
_shares_map = None
_gate_warned = set()


def _shares_of(code):
    """발행주식수 (broker_client._load_shares_cache와 같은 CSV). 모르면 0."""
    global _shares_map
    if _shares_map is None:
        m = {}
        try:
            with SHARES_CSV.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    try:
                        m[str(r.get("code", "")).zfill(6)] = float(r.get("shares") or 0)
                    except Exception:
                        pass
        except Exception:
            pass
        _shares_map = m
    return _shares_map.get(str(code).zfill(6), 0.0)


def _gate_ok(code, cur):
    """False = 이 가격으론 브로커 주문 관문(가격·시총 하한)이 거부한다."""
    if 0 < cur < GATE_MINP:
        return False
    if GATE_MINMC > 0 and cur > 0:
        sh = _shares_of(code)
        if sh > 0 and sh * cur < GATE_MINMC:
            return False
    return True


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _jload(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _cur(code):
    try:
        s = json.loads(SNAP.read_text(encoding="utf-8-sig"))
        v = s.get("codes", {}).get(str(code).zfill(6)) or {}
        # ★[7/16 수술] 브로커 재기동 후 스냅샷에 어제 시세가 잔존 — ts가 있고 오늘이 아니면 무시(ts 없으면 기존대로 신뢰)
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return 0.0
        return float(v.get("cur", 0) or 0)
    except Exception:
        return 0.0


def _che(code):
    """현재 체결강도(che_state.json last). 없으면 0. [7/17] 매수결정에는 더 이상 안 씀 — 로그 비교용."""
    try:
        d = json.loads(CHE.read_text(encoding="utf-8-sig"))
        v = d.get(str(code).zfill(6))
        if isinstance(v, dict):
            return float(v.get("last", 0) or 0)
    except Exception:
        pass
    return 0.0


def _cum_vol(code):
    """[7/17] 누적거래량(live_micro_snapshot) — 저점구간 매수/매도 체결량 근사에 사용."""
    try:
        s = json.loads(SNAP.read_text(encoding="utf-8-sig"))
        v = s.get("codes", {}).get(str(code).zfill(6)) or {}
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return None
        cv = v.get("cum_vol")
        return float(cv) if cv is not None else None
    except Exception:
        return None


def _fills_qty(code, since_hms, side="매수"):
    """★[7/16 수술③·㉮] 체결확인 그라운드트루스 — 게이트웨이가 체결 콜백(Chejan)에서 직접 쓰는
       LOG\\fills_YYYYMMDD.csv에서 since 이후 이 종목 해당 방향('매수'/'매도') 체결의 주문번호별 누적체결량 합.
       (fill_qty=FID911은 주문별 누적치 → 주문번호별 max. 접수OK여도 여기 없으면 체결 0 = 유령)"""
    fp = Path(r"C:\stock_bot\LOG") / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return 0
    code = str(code).zfill(6)
    best = {}
    try:
        with fp.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    if str(r.get("code", "")).strip().zfill(6) != code:
                        continue
                    if side not in str(r.get("otype", "")):
                        continue
                    if "체결" not in str(r.get("state", "")):
                        continue
                    ts = str(r.get("ts", ""))
                    if len(ts) >= 19 and ts[11:19] < since_hms:
                        continue
                    q = int(float(r.get("fill_qty") or 0))
                    ono = str(r.get("order_no", "")).strip() or f"?{ts}"
                    if q > best.get(ono, 0):
                        best[ono] = q
                except Exception:
                    continue
    except Exception:
        return 0
    return sum(best.values())


def _bar1m(code):
    """이번 분 1분봉 {o,h,l,c,pos,bull,prev[[o,h,l,c]..]} — 낡았으면 None."""
    try:
        d = json.loads(BARS1M.read_text(encoding="utf-8-sig"))
        if str(d.get("hm", "")) != datetime.now().strftime("%H%M"):
            return None
        return (d.get("m") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _flip_bear(b):
    """양봉→음봉 완성봉 전환 = 직전 두 완성봉이 [양봉, 음봉]. prev 없으면 False."""
    if not b:
        return False
    prev = b.get("prev") or []
    if len(prev) < 2:
        return False
    try:
        a_o, a_h, a_l, a_c = [float(x) for x in prev[-2][:4]]   # 더 이전 완성봉
        z_o, z_h, z_l, z_c = [float(x) for x in prev[-1][:4]]   # 방금 완성된 봉
        return a_c > a_o and z_c < z_o                          # 양봉 → 음봉
    except Exception:
        return False


def _ma5_1m(b):
    """1분봉 5분선 = 직전 5완성봉 종가평균. prev<5면 None."""
    if not b:
        return None
    prev = b.get("prev") or []
    if len(prev) < 5:
        return None
    try:
        return sum(float(x[3]) for x in prev[-5:]) / 5.0
    except Exception:
        return None


def _ma5_daily():
    """{code: 일봉 5일선} — EOD 직전 5거래일 종가평균."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-5:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


def _ma10_daily():
    """{code: 일봉 10일선} — EOD 직전 10거래일 종가평균. ★[7/17 낮] 10일선 지지 조건 판정용."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {}
    out = {}
    for c, byd in raw.items():
        ks = sorted(byd)[-10:]
        if ks:
            out[c] = sum(byd[d] for d in ks) / len(ks)
    return out


_mkt_cache = None
_name_cache = None
_stale_logged = False


def _crash_map():
    """급락주 {code:{depth,name}} — 코스닥·1만원↑·어제대금 300억~2조·저점 -DROP%↓.
    ★[7/16] 시장구분(260MB EOD 전체 스캔·실측 5.4초)·종목명은 장중 안 변함 → 첫 호출만 읽고 캐시.
      캐시 전엔 2초 루프가 실제 7초+ 였다(진입·재시도 지연). 값·판정은 동일."""
    global _mkt_cache, _name_cache, _stale_logged
    import collections
    pool = _jload(POOL, {})
    che = _jload(CHE, {})
    # ★[7/16 수술] 날짜 검사 — 09:00 직후 보드가 오늘 풀·체결강도를 쓰기 전엔 어제 데이터(어제 저점·7/14 종가)로
    #   급락을 오판할 수 있다(어제 -5%저점+어제 체결강도105↑ 종목 오진입 창). 둘 다 오늘 날짜일 때만 판정.
    _today = datetime.now().strftime("%Y%m%d")
    if str(pool.get("date") or "") != _today or str(che.get("date") or "") != _today:
        # 09:02 넘어서도 낡았으면 보드 이상 — 조용히 굶지 말고 한 번은 알린다
        if not _stale_logged and datetime.now().strftime("%H%M") >= "0902":
            _stale_logged = True
            _log("⏳🚨 보드가 아직 오늘 풀/체결강도를 안 씀(날짜 관문에 막힘) — 급락 등재 대기 중. 보드 생사 확인 요망")
        return {}
    rows = pool.get("rows", [])
    pcm = {str(c).zfill(6): float(px) for c, px, v in rows}
    pvm = {str(c).zfill(6): float(v) for c, px, v in rows}
    if not _mkt_cache:                       # 읽기 실패(빈 결과)면 다음 호출서 재시도 — 빈 캐시로 굳으면 전 종목 탈락(fail-closed)이라
        m = {}
        try:
            with EOD.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    m[r["code"].zfill(6)] = r.get("market", "")
        except Exception:
            pass
        _mkt_cache = m
    mkt = _mkt_cache
    if not _name_cache:
        try:
            _name_cache = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            _name_cache = {}
    names = _name_cache
    out = {}
    for dc, cs in che.items():
        dc = str(dc).zfill(6)
        if not isinstance(cs, dict):
            continue
        pc = pcm.get(dc)
        lo = float(cs.get("lo", 0) or 0)
        if not pc or pc <= 0 or lo <= 0 or pc < PX_FLR or mkt.get(dc) != "KOSDAQ":
            continue
        pv = pvm.get(dc, 0.0)
        if not (PVAL_LO <= pv <= PVAL_HI):
            continue
        if (lo / pc - 1) * 100 > DROP:
            continue
        # ★[7/15 친구님] 갭하락(시가 전일比 -3%↓) = 무조건 1순위. 시가 모르면(0) 갭 아님 처리.
        o = float(cs.get("o", 0) or 0)
        gappct = (o / pc - 1) * 100 if o > 0 else 0.0
        out[dc] = {"depth": round((lo / pc - 1) * 100, 2),
                   "gap": bool(o > 0 and gappct <= GAP_TH), "gappct": round(gappct, 2),
                   "name": (names.get(dc) or "")[:10] or dc, "pc": pc,
                   "pv": pv}   # ★[7/16 친구님] 전일 대금(억) — 정렬 우선권용
    return out


def _csv(r):
    try:
        CSVLOG.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVLOG.exists()
        with CSVLOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패: {e}")


class Broker:
    def __init__(self):
        self.bc = None; self.acc = ""

    def connect(self):
        if not LIVE:
            return True
        try:
            from broker_client import BrokerClient, is_broker_alive
            if not is_broker_alive():
                _log("🚨 브로커 죽음 → 주문 불가"); return False
            self.bc = BrokerClient()
            ai = self.bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str):
                accs = [a for a in accs.split(";") if a]
            self.acc = (accs[0] if isinstance(accs, list) and accs else "") \
                or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()
            return bool(self.acc) or (_log("🚨 계좌 없음") or False)
        except Exception as e:
            _log(f"🚨 브로커 연결 실패: {e}"); return False

    def order(self, code, qty, side):
        if not LIVE:
            _log(f"  [그림자] {side} {code} x{qty}")
            return "SHADOW"
        # ★즉시정지 플래그
        if side == "BUY" and Path(r"C:\stock_bot\config\manual_buy_block.flag").exists():
            _log("  🛑 manual_buy_block.flag → 매수 차단"); return "BLOCKED"
        try:
            r = self.bc.send_order_real(
                idempotency_key=f"crashflow_{side.lower()}_{code}_{uuid.uuid4()}",
                account=self.acc, code=code, qty=int(qty),
                order_type=(1 if side == "BUY" else 2), price=0,
                hoga_gb="06", rqname=f"CRASHFLOW_{side}_{code}", screen_no="9748")
            st = str((r or {}).get("status", "")).upper()
            _log(f"  [LIVE] {side} {code} x{qty} → {st}")
            return st or "NONE"
        except Exception as e:
            _log(f"  🚨 주문 실패 {side} {code}: {e}"); return "ERROR"

    def cancel_open_buys(self, code):
        """★[7/16 수술③] 이 종목의 미체결 매수주문 전량취소(opt10075 조회 → order_type 3).
           체결0 판정 후 재시도 전에 잔량을 죽여 이중매수를 막는다. 실패해도 fail-open(로그만) —
           만에 하나 취소 실패 후 뒤늦게 체결된 잔량은 FLAT 09:23 안전판이 청산."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "2",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"CRASHFLOW_OPEN_{code}", screen_no="9749", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"crashflow_cxl_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=3, price=0, hoga_gb="00",
                    rqname=f"CRASHFLOW_CXL_{code}", screen_no="9749",
                    origin_order_no=ono)
                _log(f"  🧹매수잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️취소 실패 {code}: {e}")

    def cancel_open_sells(self, code):
        """★[7/16 친구님 승인 ㉮] 이 종목의 미체결 매도주문 전량취소(opt10075 매매구분1 → order_type 4).
           매도 체결0 판정 후 재매도 전에 잔량을 죽여 이중매도를 막는다. fail-open(로그만)."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"CRASHFLOW_OPENS_{code}", screen_no="9749", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 매도 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"crashflow_cxls_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=4, price=0, hoga_gb="00",
                    rqname=f"CRASHFLOW_CXLS_{code}", screen_no="9749",
                    origin_order_no=ono)
                _log(f"  🧹매도잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️매도취소 실패 {code}: {e}")


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < "0900" or hm > END_HM:
        return
    _log("=" * 78)
    from low_anchor_buy_v1 import ARM_PCT as LA_ARM, OBS_PCT_LO as LA_OBS_LO, OBS_PCT_HI as LA_OBS_HI, \
        BUY_RATIO as LA_BUY
    _log(f"🕳🔥 급락주 저점앵커 {'★실전(LIVE)' if LIVE else '그림자(주문0)'} — "
         f"매수 armed{LA_ARM:.0f}%→저점반등+{LA_OBS_LO:.0f}~{LA_OBS_HI:.0f}%→매수비율{LA_BUY:.0f}(매수÷매도×100) · "
         f"매도 재난손절{STOP}% / 저점재하락{REBUY_STOP:.0f}%(재매수{REBUY_MAX}회) / 5일선이탈 / "
         f"고점{PEAK_HARD_PCT:.0f}%즉시 / 고점{PEAK_WATCH_PCT:.0f}%+{PEAK_WATCH_SEC:.0f}초관찰(고점매도후 쿨다운{REBUY_COOLDOWN_SEC/60:.0f}분) / "
         f"{EXIT_HM[:2]}:{EXIT_HM[2:]}청산 · {CAP:,.0f}원×{SLOTS}슬롯")

    br = Broker()
    if not br.connect():
        return
    ma5d = _ma5_daily()
    ma10d = _ma10_daily()   # ★[7/17 낮] 10일선 지지 조건(보유연장) + 5일선이탈 매도용

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "slots": {}}
        _jsave(LEDGER, L)

    deadline = time.monotonic() + RUN_SEC
    buy_fails = {}      # ★[7/16 친구님] 종목별 매수 실패 횟수 — 3회면 그 종목만 매수 금지(다른 종목 계속)
    buy_ban = set()
    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        dirty = False

        # ══ 진입 — 급락주 저점서 체결강도 105 (슬롯 찰 때까지·눌림 매도 후 재진입 허용) ══
        if shared.count(today) < SLOTS and ENTRY_HM <= hm <= ENTRY_END:
            cm = _crash_map()
            # ★[7/16 친구님 "500억으로 넓히되 대금 큰 것 우선권"] 정렬 = 갭하락 1순위
            #   → 대금 700억↑ 그룹 우선(백필: 700억↑ +1.81%/78% vs 500~700억 +0.85%/50%)
            #   → 그룹 안에서 깊이순(깊이도 검증된 지렛대: -9%↓ +3.02%). 유니버스는 500억↑ 전체.
            order = sorted(cm.items(), key=lambda kv: (not kv[1].get("gap"),
                                                       kv[1].get("pv", 0) < 700,
                                                       kv[1]["depth"]))
            for code, info in order:
                ex = L["slots"].get(code)
                # [7/16] 공통 슬롯(아침대장과 합산) · 매수 3회 실패 종목(buy_ban)은 건너뜀 — 다른 종목으로 갈아탐
                # ★[7/16 검사수술] 체결확인 대기(pending_buy/sell) 중에도 건너뜀 — 대기 8초 동안 같은 신호로
                #   2초마다 중복 매수 주문이 나가던 구멍(이중매수 폭주) 봉쇄. 유령 판정 시 슬롯이 pop되므로 재시도는 그대로 가능.
                if code in buy_ban or shared.count(today) >= SLOTS \
                        or (ex and (ex.get("pos") or ex.get("done")
                                    or ex.get("pending_buy") or ex.get("pending_sell")
                                    # ★[7/17 낮] 매도 후 30분 쿨다운 — 풀리기 전엔 재매수 스킵
                                    or (ex.get("cooldown_until") and time.time() < float(ex["cooldown_until"])))):
                    continue
                cur = _cur(code); che = _che(code); cv = _cum_vol(code)
                if cur <= 0:
                    continue
                # ★[7/17 아침] 저점구간 매수/매도 체결량 비율 판정 — ledger의 anchors에 종목별 상태 유지(재기동 이어받기)
                L.setdefault("anchors", {})
                a = L["anchors"].get(code) or {"prev_close": info["pc"]}
                la = la_from_ledger(code, a, info["pc"])
                ev = la.feed(hm, cur, cv, time.time())   # ★[7/18 밤] 매수÷매도×100(105 기준) 판정 — che는 로그 참고용으로만 별도 조회
                L["anchors"][code] = la_to_ledger(la)
                dirty = True
                if ev and ev["signal"] == "WAIT":
                    br = ev.get("buy_ratio")
                    _log(f"  ⏳관망 {info['name']}({code}) 저점{ev['obs_low']:,.0f}→{ev['entry_px']:,.0f} "
                         f"매수비율{(br if br is not None else 0):.0f}(누적체결강도{che:.0f}참고) "
                         f"[{ev['reason']}] — 신저점 재대기")
                if ev and ev["signal"] == "BUY":
                    # ★[7/16 안전수술①-2] 관문 미러 — 못 살 종목은 주문 안 보냄(종목당 경고 1회)
                    if not _gate_ok(code, cur):
                        if code not in _gate_warned:
                            _gate_warned.add(code)
                            _log(f"  🚧{info['name']}({code}) @{cur:,.0f} 관문미러 차단"
                                 f"(가격<{GATE_MINP:,.0f} 또는 시총<{GATE_MINMC/1e8:,.0f}억) → 주문 시도 안 함")
                        continue
                    qty = int(CAP // cur)
                    if qty < 1:
                        continue
                    if not shared.acquire(code, "CRASH", today):   # [7/16] 공통 슬롯 확보(풀 차면 스킵)
                        continue
                    st = br.order(code, qty, "BUY")
                    if st not in ("OK", "TIMEOUT", "SHADOW"):
                        # ★[7/16 안전수술①+친구님 "3번까지 해보고 그 종목만 매수 금지"] 실패 시 슬롯 반환·2초 루프 재시도,
                        #   같은 종목 3회 실패면 그 종목만 금지하고 다른 종목으로 갈아탐(전체 매수 금지 아님)
                        shared.release(code, today)
                        buy_fails[code] = buy_fails.get(code, 0) + 1
                        if buy_fails[code] >= 3:
                            buy_ban.add(code)
                            _log(f"  🛑{info['name']}({code}) 매수 3회 연속 실패 → 이 종목만 매수 금지(다른 종목 계속)")
                        else:
                            _log(f"  ⚠️{info['name']}({code}) 매수 {st} → 재시도 {buy_fails[code]}/3")
                        continue
                    buy_fails.pop(code, None)
                    re_n = int((ex or {}).get("re", 0) or 0) + (1 if ex else 0)   # ★재진입이면 회차 +1
                    # ★[7/16 수술③ 유령왕복] 접수OK ≠ 체결 — LIVE는 pending_buy로 적고 체결확인 후에만
                    #   pos=True(아침대장 기가레인형 유령 방지). 그림자는 기존대로 즉시 보유.
                    L["slots"][code] = {"name": info["name"], "depth": info["depth"],
                                        "qty": qty if st == "SHADOW" else 0,
                                        "entry": cur if st == "SHADOW" else 0.0,
                                        "peak": cur, "low": 0.0, "pos": st == "SHADOW",
                                        "done": False, "re": re_n,
                                        "realized": float((ex or {}).get("realized", 0) or 0)}
                    if st != "SHADOW":
                        L["slots"][code]["pending_buy"] = {
                            "qty": qty, "px": cur, "re": re_n,
                            "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                            "sent": time.time()}
                    reason = "눌림재진입" if re_n else "저점앵커진입"
                    br = ev.get("buy_ratio")
                    _log(f"🕳🔥 {'재진입#' + str(re_n) if re_n else '진입'} {info['name']}({code}) @{cur:,.0f} x{qty} "
                         f"깊이{info['depth']:+.1f}%{'·★갭하락' + format(info.get('gappct', 0), '+.1f') + '%' if info.get('gap') else ''} "
                         f"저점{ev['obs_low']:,.0f}→반등{ev['entry_px']:,.0f} "
                         f"매수비율{(br if br is not None else 0):.0f}(매수{ev['seg_buy']:,.0f}/매도{ev['seg_sell']:,.0f}·누적체결강도{che:.0f}참고) "
                         f"일봉5일선{ma5d.get(code,0):,.0f} [{ev['reason']}]")
                    _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": info["name"], "방향": "BUY", "사유": reason,
                          "체결강도": round(che, 1), "저점": round(ev["obs_low"]), "현재가": round(cur),
                          "일봉5일선": round(ma5d.get(code, 0)),
                          "진입가": round(cur), "재매수회차": re_n,
                          "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": st,
                          "매수비율": br, "구간매수량": ev.get("seg_buy"), "구간매도량": ev.get("seg_sell"),
                          "판정사유": ev.get("reason")})
                    dirty = True

        # ══ ★[7/16 수술③·㉮] 매수/매도 체결확인 — 접수OK ≠ 체결(확정 전엔 상태 전환 금지) ══
        for code, s in list(L.get("slots", {}).items()):
            if not isinstance(s, dict) or s.get("done"):
                continue
            # ── ㉮ 매도 체결확인 — 접수OK ≠ 팔림(기가레인 "[800033] 0주" 패턴 방지) ──
            ps = s.get("pending_sell")
            if ps:
                need = int(ps.get("qty") or 0)
                sfill = _fills_qty(code, str(ps.get("since") or "09:00:00"), "매도")
                if need > 0 and sfill >= need:
                    ret2 = float(ps.get("ret") or 0)
                    s["realized"] = round(float(s["realized"]) + ret2, 3)
                    _log(f"  ✅매도 체결확인 {s.get('name')}({code}) {sfill}/{need}주 ({ret2:+.2f}%)")
                    _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": s.get("name", code), "방향": "SELL", "사유": str(ps.get("why") or ""),
                          "체결강도": ps.get("che", ""), "고점": round(float(s.get("peak") or 0)),
                          "현재가": round(float(ps.get("px") or 0)), "일봉5일선": round(ma5d.get(code, 0)),
                          "진입가": round(float(s.get("entry") or 0)), "수익퍼센트": round(ret2, 2),
                          "재매수회차": int(s.get("re", 0) or 0),
                          "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": str(ps.get("st") or "OK")})
                    s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
                    L.setdefault("anchors", {}).pop(code, None)
                    if str(ps.get("why") or "") == "재매수손절":
                        # ★[7/17 낮] 저점에서 재하락 — 쿨다운 없이 즉시 재관찰(신저점 재탐색), 재매수 2회까지
                        _log(f"  🔁재관찰 {s.get('name')}({code}) — 재매수 {int(s.get('re', 0) or 0) + 1}/{REBUY_MAX}회 대기")
                    else:
                        # ★[7/17 낮] 고점 찍고 매도 — "한번 매도하면 30분간 재매수는 없다"
                        s["cooldown_until"] = time.time() + REBUY_COOLDOWN_SEC
                        _log(f"  🔁쿨다운 {s.get('name')}({code}) — {REBUY_COOLDOWN_SEC/60:.0f}분간 재매수 금지")
                    s.pop("pending_sell", None)
                    shared.release(code, today)
                    dirty = True
                elif (time.time() - float(ps.get("sent") or 0)) >= FILL_WAIT:
                    br.cancel_open_sells(code)           # 잔량 취소 후에만 재매도(이중매도 방지)
                    if sfill >= 1:
                        s["qty"] = max(0, need - sfill)
                        s.pop("pending_sell", None)
                        _log(f"  ⚠️매도 부분체결 {s.get('name')}({code}) {sfill}/{need}주 "
                             f"→ 잔량 {s['qty']}주 재매도 예정")
                    else:
                        s.pop("pending_sell", None)
                        _log(f"  👻매도 체결0 {s.get('name')}({code}) — 접수만 되고 체결 없음 "
                             f"→ 잔량 취소·재매도(유령 매도 방지)")
                    dirty = True
                continue
            pb = s.get("pending_buy")
            if not pb:
                continue
            filled = _fills_qty(code, str(pb.get("since") or "09:00:00"), "매수")
            if filled >= 1:
                if filled < int(pb["qty"]):
                    br.cancel_open_buys(code)          # 부분체결 — 잔량 취소·체결분만 장부(매도 초과주문 방지)
                s["pos"] = True
                s["qty"] = int(min(filled, int(pb["qty"])))
                s["entry"] = float(pb["px"])
                s["peak"] = float(pb["px"])
                s.pop("pending_buy", None)
                _log(f"  ✅체결확인 {s.get('name')}({code}) {filled}/{pb['qty']}주"
                     + ("" if filled >= int(pb["qty"]) else " ★부분체결 — 잔량 취소·체결분만 장부"))
                dirty = True
            elif (time.time() - float(pb.get("sent") or 0)) >= FILL_WAIT or hm >= EXIT_HM:
                br.cancel_open_buys(code)              # 잔량 취소 후에만 재시도(이중매수 방지)
                prev_re = int(pb.get("re") or 0)
                if prev_re > 0:
                    # 재진입이 유령 → 눌림 대기 상태 복귀(회차 되돌림·저점 추적 계속)
                    s.pop("pending_buy", None)
                    s["re"] = prev_re - 1
                    s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
                else:
                    # 최초진입이 유령 → 슬롯 회수·장부 삭제(재진입 후보로 되돌림)
                    L["slots"].pop(code, None)
                shared.release(code, today)
                # ★유령도 매수 실패로 계산 — 3회면 그 종목만 매수 금지(친구님 3회 규칙과 통일)
                buy_fails[code] = buy_fails.get(code, 0) + 1
                if buy_fails[code] >= 3:
                    buy_ban.add(code)
                _log(f"  👻체결0 유령판정 {s.get('name')}({code}) — 접수만 되고 체결 없음(유령 왕복 방지) "
                     f"→ 잔량 취소·슬롯 회수 (실패 {buy_fails[code]}/3)")
                _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                      "종목명": s.get("name", code), "방향": "BUY", "사유": "유령판정(체결0·잔량취소)",
                      "현재가": round(_cur(code)), "진입가": round(float(pb.get("px") or 0)),
                      "재매수회차": prev_re,
                      "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": "GHOST"})
                dirty = True

        # ══ 매도 ══
        for code, s in L.get("slots", {}).items():
            if s.get("done") or not s.get("pos"):
                continue
            if s.get("pending_sell") or s.get("pending_buy"):   # ★[㉮] 체결확인 대기 중엔 중복 주문 금지
                continue
            cur = _cur(code); che = _che(code); cv = _cum_vol(code)
            if cur <= 0:
                continue
            ent = float(s["entry"] or 0)
            if ent <= 0:
                continue
            ret = (cur / ent - 1) * 100

            # ── ★[7/17 낮] 고점앙커 갱신 — 새 고점마다 매수/매도 체결량 구간을 리셋(low_anchor와 동일 틱룰 근사) ──
            if cur > s["peak"]:
                s["peak"] = cur
                s["peak_seg_buy"] = 0.0; s["peak_seg_sell"] = 0.0
                s["peak_last_cum_vol"] = cv; s["peak_last_px"] = cur
                s["peak_watch_start"] = None
                dirty = True
            else:
                lp = s.get("peak_last_px"); lv = s.get("peak_last_cum_vol")
                if lp is not None and cv is not None and lv is not None:
                    dv = max(0.0, cv - lv)
                    if cur > lp:
                        s["peak_seg_buy"] = float(s.get("peak_seg_buy", 0) or 0) + dv
                    elif cur < lp:
                        s["peak_seg_sell"] = float(s.get("peak_seg_sell", 0) or 0) + dv
                s["peak_last_px"] = cur
                if cv is not None:
                    s["peak_last_cum_vol"] = cv

            peak = float(s["peak"] or cur)
            drop_pk = (cur / peak - 1) * 100 if peak > 0 else 0.0
            why = None
            if hm >= EXIT_HM:
                why = "시간청산"
            elif ret <= STOP:
                why = "재난손절"
            elif ret <= REBUY_STOP and peak <= ent and int(s.get("re", 0) or 0) < REBUY_MAX:
                # ★[7/17 낮 친구님 "저점에서 재하락은 즉시 재관찰·2회까지 재매수 — 고점 찍고 판 건 다른 얘기"]
                #   진입가를 한 번도 못 넘고(peak<=entry) -2%면 즉시 재관찰(신저점 재탐색), 재매수 2회까지.
                #   재관찰 대신 재난손절/5일선/고점 규칙이 순서상 앞뒤로 있으니 정확히 이 조건에서만 걸림.
                why = "재매수손절"
            elif ma5d.get(code) and peak > ent and cur < ma5d[code]:
                # ★[7/17 낮] 친구님 "5일선 이탈하면 매도" — 고점 찍고 올라탄 뒤(peak>entry)에만 적용
                why = "5일선이탈"
            elif drop_pk <= PEAK_HARD_PCT:
                # ★[7/17 낮] 친구님 "2% 빠지면 즉시 매도" — 관찰 없음
                why = f"고점{PEAK_HARD_PCT:.0f}%즉시매도"
            elif drop_pk <= PEAK_WATCH_PCT:
                # ★[7/17 낮] 친구님 "1% 빠지면 매도하는데 10초간 매수매도를 관망한다"
                if s.get("peak_watch_start") is None:
                    s["peak_watch_start"] = time.time(); dirty = True
                else:
                    elapsed = time.time() - float(s["peak_watch_start"])
                    if elapsed >= PEAK_WATCH_SEC:
                        tot = float(s.get("peak_seg_buy", 0) or 0) + float(s.get("peak_seg_sell", 0) or 0)
                        sell_ratio = (float(s.get("peak_seg_sell", 0) or 0) / tot * 100.0) if tot > 0 else 0.0
                        if sell_ratio >= PEAK_SELL_RATIO:
                            why = f"고점앙커매도(매도비율{sell_ratio:.0f}%)"
                        else:
                            s["peak_watch_start"] = None; dirty = True   # 매수세가 버텨줌 — 관찰 취소·계속 보유
            elif s.get("peak_watch_start") is not None:
                s["peak_watch_start"] = None; dirty = True   # 고점 근처로 회복 — 관찰 취소
            if why:
                st = br.order(code, s["qty"], "SELL")
                if st not in ("OK", "TIMEOUT", "SHADOW"):
                    # ★[7/16 안전수술②] 매도 실패는 성공 취급 안 함 — 포지션 유지·다음 루프 재시도(방치 금지)
                    _log(f"  🚨매도 실패 {why} {s['name']} {st} → 포지션 유지·다음 루프 재시도")
                    dirty = True
                    continue
                if st == "SHADOW":
                    s["realized"] = round(float(s["realized"]) + ret, 3)
                    _log(f"  💰{why} {s['name']} @{cur:,.0f} ({ret:+.2f}%) 체결강도{che:.0f}")
                    _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": s["name"], "방향": "SELL", "사유": why, "체결강도": round(che, 1),
                          "고점": round(s["peak"]), "현재가": round(cur), "일봉5일선": round(ma5d.get(code, 0)),
                          "진입가": round(ent), "수익퍼센트": round(ret, 2), "재매수회차": int(s.get("re", 0) or 0),
                          "실전여부": "SHADOW", "주문결과": st})
                    s["pos"] = False; s["qty"] = 0; s["entry"] = 0.0
                    L.setdefault("anchors", {}).pop(code, None)
                    if why == "재매수손절":
                        # ★[7/17 낮] 저점에서 재하락 — 쿨다운 없이 즉시 재관찰(신저점 재탐색), 재매수 2회까지
                        _log(f"  🔁재관찰 {s['name']}({code}) — 재매수 {int(s.get('re', 0) or 0) + 1}/{REBUY_MAX}회 대기")
                    else:
                        # ★[7/17 낮] 고점 찍고 매도 — "한번 매도하면 30분간 재매수는 없다"
                        s["cooldown_until"] = time.time() + REBUY_COOLDOWN_SEC
                        _log(f"  🔁쿨다운 {s['name']}({code}) — {REBUY_COOLDOWN_SEC/60:.0f}분간 재매수 금지")
                    shared.release(code, today)                      # [7/16] 슬롯 반환 → 로테이션
                else:
                    # ★[7/16 친구님 승인 ㉮] 접수OK ≠ 팔림 — 체결확인 후에만 '팔림' 기록(유령 매도 방지)
                    s["pending_sell"] = {"qty": int(s["qty"]), "px": cur, "ret": round(ret, 3),
                                         "why": why, "che": round(che, 1), "st": st,
                                         "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                                         "sent": time.time()}
                    _log(f"  💰{why} {s['name']} @{cur:,.0f} ({ret:+.2f}%) 체결강도{che:.0f} "
                         f"접수 → 체결확인 대기")
                dirty = True

        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)

    # 마감 요약
    if datetime.now().strftime("%H%M") >= EXIT_HM and L.get("slots"):
        tot = sum(float(s.get("realized") or 0) for s in L["slots"].values())
        n = len([k for k in L["slots"] if not k.startswith("_")])
        _log("─" * 78)
        for code, s in L["slots"].items():
            _log(f"  {s.get('name')}({code}) → {float(s.get('realized') or 0):+.2f}%")
        _log(f"★합계 {tot:+.2f}% · 추정 {tot/100*CAP:+,.0f}원 ({'실전' if LIVE else '그림자'}) → {CSVLOG}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)

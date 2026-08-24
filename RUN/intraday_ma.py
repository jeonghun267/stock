# -*- coding: utf-8 -*-
"""[3분봉 이동평균 공유모듈 2026-06-30 친구님 "모든 배열은 당일 3분봉으로"] 당일치기 시스템용.
   데이터源: brk_realtime이 스냅샷(934종목·대장주포함)을 누적한 3분봉 bars3(brk_rt_state_<date>.json).
   제공: is_up(code)=3분봉 우상향(5선≥20선 & 현재>시초) · not_reverse(code)=3분봉 역배열아님.
   trend_filter가 TREND_TIMEFRAME=3MIN일때 이걸 호출 → 전 전략 동시 3분봉화.
   ★fail-safe: 봉 부족/데이터없음이면 우상향=None·비역배열=True(통과) → 막지 않음(체결강도가 1차게이트).

   [전일 3분봉 시드 2026-06-30 친구님 "전일 3분봉 이어서 쓰게"]
   당일 3분봉은 장중 누적이라 60선(정오~)·120선(막판~)이 늦게 형성됨 → 장 시작부터 60/120선을 쓰도록
   연속 3분봉 파일(prices_3m.csv)에서 '전일까지'의 3분봉 종가를 끌어와 앞에 이어붙인다(_series).
   ★fail-safe: 전일 풀데이(≥SEED_PRIOR_MIN봉)가 있는 종목만 시드·없으면 오늘만(기존과 동일·회귀 0).
   ★시드는 MA 계산용 시리즈에만 적용·'현재>시초(오늘 첫봉)' 판정은 오늘 봉으로 유지(당일 우상향 의미 보존).
   끄기: setx SEED_PRIOR_3M NO.
"""
import json, time, csv, os
from datetime import datetime, timedelta
from pathlib import Path

_cache = None
_cache_ts = 0.0

# --- 전일 시드 설정 ---
PRIOR_CSV  = os.environ.get("PRIOR_3M_CSV", r"C:\stock_bot\data\prices_3m.csv")
SEED_ON    = os.environ.get("SEED_PRIOR_3M", "YES").strip().upper() == "YES"
SEED_KEEP  = int(os.environ.get("SEED_PRIOR_KEEP", "130"))   # 전일에서 끌어올 최대 봉수(하루≈126봉)
SEED_MIN   = int(os.environ.get("SEED_PRIOR_MIN", "30"))     # 전일 봉이 이만큼 미만이면 시드 안함(듬성듬성 종목 fail-safe)
SEED_MAX_AGE_D = int(os.environ.get("SEED_PRIOR_MAX_AGE_D", "4"))  # ★[2026-07-02] 시드 신선도: 가장 최근 전일이 이 일수(달력일·주말/휴일 감안)보다 오래면 시드 안함
_prior = None
_prior_ts = 0.0

# ★[7/2 브로커 직접 3분봉 친구님 "역배열 방어 살려라"] 시드(prices_3m)가 종목당 3~4봉으로 듬성듬성 →
#   60선 미형성 → 역배열/하락 방어 무력화(126340 하락종목 매수). opt10080 3분봉을 브로커에서 직접 받아 이평 보강.
#   ★TR 폭주 방지(오늘 프리징=TR과부하): per-code 공유 디스크캐시(TTL 130s)라 여러 엔진이 같은코드 재조회 안함·
#   시드/오늘봉이 60개 넘으면 브로커 안부름(정상 종목은 부하 0)·브로커 죽으면 기존 fail-safe(시드/오늘봉).
_BFALL  = os.environ.get("INTRADAY_BROKER_BARS", "YES").strip().upper() == "YES"
_BTTL   = float(os.environ.get("INTRADAY_BROKER_TTL", "130"))
_BCACHE = Path(r"C:\stock_bot\data\cache3m")
_BROKER = {"c": None}


def _bc():
    if _BROKER["c"] is None:
        try:
            from broker_client import BrokerClient
            _BROKER["c"] = BrokerClient()
        except Exception:
            _BROKER["c"] = False
    return _BROKER["c"] or None


def _broker_closes(code):
    """opt10080 3분봉 → (전체 closes 오래된→최근, 오늘 closes). per-code 공유 디스크캐시(TTL). 실패/브로커없음=None."""
    if not _BFALL:
        return None
    code = str(code).zfill(6)
    f = _BCACHE / f"{code}.json"
    try:
        if f.exists() and (time.time() - f.stat().st_mtime) < _BTTL:
            d = json.loads(f.read_text(encoding="utf-8"))
            return (d.get("all") or None), (d.get("today") or None)
    except Exception:
        pass
    if _BROKER.get("fail", 0) >= 2:                      # ★프리징 방어: 이 프로세스에서 연속2회 실패시 브로커조회 포기(타임아웃 누적 행 방지·오늘 13:06 프리징 교훈)
        return None
    bc = _bc()
    if not bc:
        return None
    try:
        if hasattr(bc, "alive") and not bc.alive():
            return None
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["체결시간", "현재가"], timeout_sec=4.0)
        if str((r or {}).get("status", "")).upper() in ("TIMEOUT", "ERROR"):
            _BROKER["fail"] = _BROKER.get("fail", 0) + 1
            return None
        recs = ((r or {}).get("data") or {}).get("records") or []
        today = datetime.now().strftime("%Y%m%d")
        allc = []; todc = []
        for x in recs[:130][::-1]:                       # 오래된→최근
            ts = str(x.get("체결시간", ""))
            try:
                px = float(str(x.get("현재가", "")).replace(",", "").replace("-", "").replace("+", ""))
            except Exception:
                continue
            if px <= 0:
                continue
            allc.append(px)
            if ts[:8] == today:
                todc.append(px)
        if len(allc) >= 20:
            try:
                _BCACHE.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps({"ts": time.time(), "all": allc, "today": todc}), encoding="utf-8")
            except Exception:
                pass
            return allc, todc
    except Exception:
        _BROKER["fail"] = _BROKER.get("fail", 0) + 1
    return None


def _state_path():
    return Path(rf"C:\stock_bot\DATA\brk_rt_state_{datetime.now():%Y%m%d}.json")


def _load_state():
    global _cache, _cache_ts
    now = time.time()
    if _cache is not None and (now - _cache_ts) < 15:   # 15초 캐시(여러 전략 동시호출)
        return _cache
    try:
        _cache = json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        _cache = {}
    _cache_ts = now
    return _cache


def _prior_map():
    """전일까지의 3분봉 종가 {code: [..종가..]}. 오늘 행은 제외(라이브 bars3가 담당). 1시간 캐시."""
    global _prior, _prior_ts
    if not SEED_ON:
        return {}
    now = time.time()
    if _prior is not None and (now - _prior_ts) < 3600:
        return _prior
    today = datetime.now().strftime("%Y-%m-%d")
    acc = {}
    try:
        with open(PRIOR_CSV, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            hdr = next(r)
            ti, ci, cli = hdr.index("ts"), hdr.index("code"), hdr.index("close")
            mx = max(ti, ci, cli)
            for row in r:
                if len(row) <= mx:
                    continue
                if row[ti][:10] >= today:        # 오늘/미래 제외(ISO 날짜는 문자열 정렬과 일치)
                    continue
                try:
                    px = float(row[cli])
                except (TypeError, ValueError):
                    continue
                acc.setdefault(str(row[ci]).zfill(6), []).append((row[ti], px))
    except Exception:
        _prior = {}; _prior_ts = now
        return _prior
    out = {}
    # ★[2026-07-02 근본수정·131290 브로커 재구성으로 발견] '가장 최근 하루치'만 + 신선도 게이트.
    #   기존 구현은 날짜 무구분 누적 최근 SEED_KEEP봉이라, 어제 봉이 없는 종목도 몇 주 전 낡은
    #   가격으로 ≥SEED_MIN을 통과해 시드됨(131290: 6/30 12봉+6월중순 → 아침 60선 251,417 vs
    #   브로커 실제 273,325 = -8% 유령선 → dev60 +5.6%로 오인 매수·유령 20선으로 오매도).
    #   수정: 가장 최근 전일 '하루'의 봉만 시드 + 그날이 SEED_MAX_AGE_D일 이내 + 그날 ≥SEED_MIN봉.
    #   아니면 시드 없음=오늘봉만(문서화된 원래 fail-safe·회귀 0). 롤백=.bak_pre_seedday_20260702
    try:
        _cut = (datetime.now() - timedelta(days=SEED_MAX_AGE_D)).strftime("%Y-%m-%d")
    except Exception:
        _cut = "0000-00-00"
    for code, rows in acc.items():
        rows.sort(key=lambda x: x[0])                 # ts 오름차순
        last_day = rows[-1][0][:10]                   # 가장 최근 전일(날짜)
        if last_day < _cut:                           # 낡은 시드(며칠 전) → 시드 안함
            continue
        closes = [px for ts, px in rows if ts[:10] == last_day][-SEED_KEEP:]
        if len(closes) >= SEED_MIN:                   # ★그날 하루 봉수 기준(전일 풀데이만)
            out[code] = closes
    _prior = out; _prior_ts = now
    return _prior


def bars3(code):
    """code의 오늘 3분봉 종가 리스트(라이브·당일만). ★전일시드는 _series가 담당(이건 당일 봉 그대로)."""
    rec = (_load_state().get(str(code).zfill(6)) or {})
    b = rec.get("bars3") or []
    out = []
    for x in b:
        try:
            out.append(float(x[1]))
        except (TypeError, ValueError, IndexError):
            pass
    return out


def _series(code):
    """[MA 계산용] 전일 시드 + 오늘 = 연속 3분봉 종가. 시드 없으면 오늘만.
       ★[7/2] 시드+오늘이 60봉 미만(60선 못그림)이면 브로커 opt10080 직접조회(캐시)로 보강 → 역배열 방어 살림."""
    t = bars3(code)
    p = _prior_map().get(str(code).zfill(6))
    base = (p + t) if p else t
    if len(base) >= 60:
        return base
    bb = _broker_closes(code)
    if bb and bb[0] and len(bb[0]) > len(base):
        return bb[0]                                     # 브로커 전체 시리즈(60선 형성)
    return base


def _ma(cl, w):
    w = min(w, len(cl))
    return sum(cl[-w:]) / w if w else 0.0


def is_up(code):
    """3분봉 우상향(단기선5≥장기선20 & 현재>오늘시초). True/False/None(오늘봉<2=판정불가→호출측 통과)."""
    t = bars3(code)
    if len(t) < 2:
        return None
    s = _series(code)
    return (_ma(s, 5) >= _ma(s, 20)) and (t[-1] > t[0])


def not_reverse(code):
    """3분봉 역배열(5선<20선<60선 & 현재<60선)이 아니면 True. 오늘봉<3이면 True(통과). 60선=전일시드로 장초부터 유효.
       ★[2026-07-09 친구님 "이평선은 5/20/60 세 개만·나머지 버려"] 40선 제거 — 5/20/60 계단식 역순 & 현재가<60선일 때만 매수금지.
       (구버전 5<20<40<60 롤백은 .bak_ma520_20260709)"""
    t = bars3(code)
    if len(t) < 3:
        return True
    s = _series(code)
    ma5, ma20, ma60 = _ma(s, 5), _ma(s, 20), _ma(s, 60)
    cur = t[-1]
    dead = (ma5 < ma20 < ma60) and (cur < ma60)
    return not dead


def strict_up(code):
    """3분봉 정배열(5선≥20선≥60선) + 현재>오늘시초 = 강한 우상향. True/False/None. 60선=전일시드로 장초부터 유효.
       ★[2026-07-09 친구님 "이평선은 5/20/60 세 개만"] 120선 제거(롤백 .bak_ma520_20260709)."""
    t = bars3(code)
    if len(t) < 2:
        return None
    s = _series(code)
    ma5, ma20, ma60 = _ma(s, 5), _ma(s, 20), _ma(s, 60)
    return (ma5 >= ma20 >= ma60) and (t[-1] > t[0])


def _ma_at(cl, w, back=0):
    """back봉 전 시점의 w기간 이평(없으면 None)."""
    end = len(cl) - back
    if end <= 0:
        return None
    ww = min(w, end)
    return sum(cl[end - ww:end]) / ww


def golden_cross(code, fresh=5):
    """[3분봉 골든크로스 2026-06-30 친구님] 5선이 20선을 막 상향돌파(최근 fresh봉내) + 현재 5선>20선 + 5/20선 우상향 + 60선 우상향.
       ★[2026-07-09 친구님 "이평선은 5/20/60만"] 120선 조건 제거. 봉 22개 이상(=진짜 20선, 60분치) 있어야 판정(적으면 가짜교차 양산). 60 미형성이면 그 조건 통과.
       ★당일 교차 판정이므로 오늘 봉(bars3)만 사용(전일시드 미적용=장초 오발화 방지)."""
    cl = bars3(code)
    if len(cl) < 22:                                     # ★[7/2] 오늘봉 듬성듬성(brk_rt_state)이면 브로커 오늘 3분봉으로 보강
        bb = _broker_closes(code)
        if bb and bb[1] and len(bb[1]) > len(cl):
            cl = bb[1]
    n = len(cl)
    if n < 22:
        return False
    ma5n, ma20n = _ma_at(cl, 5, 0), _ma_at(cl, 20, 0)
    if not (ma5n > ma20n):                                # 현재 5선이 20선 위
        return False
    # 최근 fresh봉 안에 '5선≤20선'이었던 적 = 막 교차(한참 위에 있는 건 제외)
    crossed_recent = any((_ma_at(cl, 5, b) is not None and _ma_at(cl, 20, b) is not None
                          and _ma_at(cl, 5, b) <= _ma_at(cl, 20, b)) for b in range(1, fresh + 1))
    if not crossed_recent:
        return False
    ma5p, ma20p = _ma_at(cl, 5, 3), _ma_at(cl, 20, 3)     # 5/20선 우상향
    if not ((ma5p is None or ma5n >= ma5p) and (ma20p is None or ma20n >= ma20p)):
        return False
    ma60n, ma60p = _ma_at(cl, 60, 0), _ma_at(cl, 60, 3)   # 60선 우상향(있으면). ★[2026-07-09 친구님 "이평선은 5/20/60만"] 120선 제거
    rising60 = (ma60n is None or ma60p is None or ma60n >= ma60p)
    return bool(rising60)


def ma(code, w):
    """code의 현재 3분봉 w기간 이평(전일시드 포함 연속 시리즈). ★봉<w(시드+오늘)면 0.0 → 호출측은 0이면 MA게이트/레이어 skip(fail-safe).
    daily_ma와 동일 역할(일봉→3분봉 교체용). 친구님 2026-06-30 '모든 이동평균선 3분봉·전일 이어서'."""
    s = _series(code)
    if len(s) < w:
        return 0.0
    return sum(s[-w:]) / w


def ma5(code):  return ma(code, 5)
def ma20(code): return ma(code, 20)
def ma40(code): return ma(code, 40)   # ★[2026-07-09 친구님 "이평선은 5/20/60만·나머지 버려"] 폐기 — 신규 사용 금지(옛 스크립트 import 호환용으로만 잔존)
def ma60(code): return ma(code, 60)


def all_codes():
    """3분봉 데이터(bars3) 있는 종목 리스트(대장주 포함 스냅샷 전체)."""
    return [c for c, v in _load_state().items() if isinstance(v, dict) and v.get("bars3")]


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    pm = _prior_map()
    print("전일시드 SEED_PRIOR_3M =", SEED_ON, "· 시드된 종목수:", len(pm), "(전일 풀데이 종목만)")
    st = _load_state()
    print("brk_rt_state 종목수:", len(st), "· bars3 있는 종목:", sum(1 for v in st.values() if isinstance(v, dict) and v.get("bars3")))
    for c in list(st.keys())[:6]:
        t = bars3(c); s = _series(c)
        seeded = len(s) - len(t)
        print(f"  {c}: 오늘 {len(t)}봉 + 전일시드 {seeded}봉 = {len(s)}봉 · ma5={ma5(c):.1f} ma20={ma20(c):.1f} ma60={ma60(c):.1f} · 우상향={is_up(c)} 비역배열={not_reverse(c)} 정배열={strict_up(c)}")

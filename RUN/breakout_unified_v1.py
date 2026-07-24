# -*- coding: utf-8 -*-
"""[돌파 통합엔진 「돌파사냥꾼 BREAKOUT HUNTER」 v1 실전 — 친구님 2026-07-04] 돌파 13개 → 1개(2모드). 바닥사냥꾼의 짝.
★진입 = 2모드 OR (각 독립 on/off):
  🅰 신고가 돌파(추격, BRK_MODE): 당일시가 +A_UP%↑ + 당일고점 근접(눌림없음) + 양봉 + che≥CHE_MIN
  🅱 베이스 돌파(초입, BASE_MODE): 최근 BASE_LOOKBACK봉 좁은 박스(≤BASE_RANGE%) + 박스상단 돌파(≤MAXEXT) + 거래량동반 + 양봉 + che
  ※대장만·진입~END·중복배제·전역 daily상한·종목당 1회.
★매도 = 추세용(반전과 정반대·길게): che매수우위면 끌기 / 매도우위면 20선이탈·5선이탈·넓은트레일 / 하드 / EOD
  ★상한가 잡으면 당일 안 팔고 → 익일 시가 매도(갭업 노림·LIMITUP_NEXTOPEN).
★안전: BRKUNI_LIVE=NO(기본)=그림자. 실탄 setx BRKUNI_LIVE YES. 소액캡·전역버짓·che필수. 롤백 전부 env.
데이터: opt10080 3분봉 + live_micro_snapshot(체결강도) + eod_daily_bars(전일종가·상한가판정). 출력 data/돌파사냥꾼/.
"""
import os, sys, json, uuid, csv, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")

LIVE       = os.environ.get("BRKUNI_LIVE", "NO").strip().upper() == "YES"
CAP        = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
TOPN       = int(os.environ.get("BRKUNI_TOPN", "2"))               # 실전 보수적 기본 2
LEADER_TOPN= int(os.environ.get("BRKUNI_LEADER_TOPN", "80"))
SCALP_UNI  = os.environ.get("BRKUNI_SCALP_UNI", "YES").strip().upper() == "YES"  # [7/6 친구님] 유니버스=단타선별. 끄기 setx BRKUNI_SCALP_UNI NO
# [2026-07-07 친구님 "돌파 연결"] ★유니버스 = 돈맥 선별기 매수세 순위(장중 실시간 순매수 우위)에서만 돌파.
#   YES=돈흐름_선별판.json의 🟢/🟡(매수세)만·순매수 순서대로 스캔. 실패/빈보드면 아래 단타선별(SCALP_UNI)로 자동 폴백.
#   장중전략이라 적합(종가매수와 달리)·던짐(🔴)은 유니버스에서 원천 제외. 끄기 setx BRKUNI_MFLOW_UNI NO.
MFLOW_UNI    = os.environ.get("BRKUNI_MFLOW_UNI", "NO").strip().upper() == "YES"
MFLOW_BOARD  = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
MFLOW_GRADES = tuple(g.strip() for g in os.environ.get("BRKUNI_MFLOW_GRADES", "🟢,🟡").split(",") if g.strip())  # 매수세 등급(레짐위험 🟡 포함)
# [2026-07-08 친구님] 유니버스 = ⭐별표 전부(큰손 +10억↑·던짐아님) — 그중 돌파 패턴 맞는 놈만 잡음(개수 제한 아님).
MFLOW_STAR   = os.environ.get("BRKUNI_MFLOW_STAR", "YES").strip().upper() == "YES"
# [2026-07-08 친구님 "돌파는 오후 1시부터 가동"] 진입 시작 시각(이전엔 매도관리만 — 상한가 익일매도 등은 정상).
START_HM     = os.environ.get("BRKUNI_START", "0900")
CHE_MIN    = float(os.environ.get("BRKUNI_CHE_MIN", "100"))
MODE_A     = os.environ.get("BRK_MODE",  "YES").strip().upper() == "YES"
MODE_B     = os.environ.get("BASE_MODE", "YES").strip().upper() == "YES"
# 🅰 신고가
A_UP       = float(os.environ.get("BRKUNI_A_UP", "3.0"))
A_NEARHIGH = float(os.environ.get("BRKUNI_A_NEARHIGH", "0.7"))
A_END      = os.environ.get("BRKUNI_A_END", "1200")
# 🅰 재돌파 모드 [2026-07-04 친구님 "봉마다 최고점 매수" 수정] — 수직 급등의 첫 고점(봉 자체가 고점 갱신중) 추격 금지.
#    당일고점이 A_MINAGE봉 이상 버틴 뒤(=눌림/횡보 숙성) 그 고점을 실제로 넘는 봉에서만 진입. 롤백 setx BRKUNI_A_REBREAK NO.
A_REBREAK  = os.environ.get("BRKUNI_A_REBREAK", "YES").strip().upper() == "YES"
A_MINAGE   = int(os.environ.get("BRKUNI_A_MINAGE", "5"))           # 고점 숙성 최소 봉수(3분봉 5=15분)
A_MAXEXT   = float(os.environ.get("BRKUNI_A_MAXEXT", "1.5"))       # 돌파 후 고점 대비 +이내(추격 배제)
A_VOLX     = float(os.environ.get("BRKUNI_A_VOLX", "1.2"))         # 돌파봉 거래량 배수(0=off·진행중 봉은 과소집계라 보수적)
A_SURGE5   = float(os.environ.get("BRKUNI_A_SURGE5", "5.0"))       # 최근5봉 상승률 상한%(V자 급반등 추격금지·0=off) [7/4 백테 +9.9%p]
# 🅱 베이스 (★진짜 박스돌파로 조임 — 장초반 MA수렴 과다발동 방지)
BASE_LOOKBACK = int(os.environ.get("BRKUNI_BASE_LOOKBACK", "10"))  # 베이스 관찰 봉수(30분)
BASE_RANGE = float(os.environ.get("BRKUNI_BASE_RANGE", "3.0"))     # 박스 고저폭 상한%
BASE_MAXEXT= float(os.environ.get("BRKUNI_BASE_MAXEXT", "2.0"))    # 박스상단 대비 +이내(추격배제)
VOL_MULT   = float(os.environ.get("BRKUNI_VOL_MULT", "1.5"))       # 돌파봉 거래량 배수
B_END      = os.environ.get("BRKUNI_B_END", "1030")
# 🅲 오후베이스 [2026-07-04 친구님 스펙 AFTERNOON_BASE] 오전급락→바닥→횡보 뒤 오후 조용한 base 첫 돌파 = 오후 추세 시작점.
#   백테(che 5일·손절=base하단으로 교정): che>=100 포함 19건 승률 68.4% 건당 +1.16% / che 없인 22일 -0.12%(che 필수).
#   원스펙 '재진입 손절'은 승률 31%라 base하단 손절로 교정. ★기본 SHADOW(신호기록만·주문0) → 검증 후 setx BRKUNI_MODE_C LIVE / 끄기 OFF.
MODE_C     = os.environ.get("BRKUNI_MODE_C", "SHADOW").strip().upper()   # OFF / SHADOW / LIVE
C_START    = os.environ.get("BRKUNI_C_START", "1220")
C_END      = os.environ.get("BRKUNI_C_END", "1345")
C_BASE_W   = float(os.environ.get("BRKUNI_C_BASE_W", "1.5"))     # base(5/7/10봉) 고저폭 상한%
C_VOLX     = float(os.environ.get("BRKUNI_C_VOLX", "1.8"))       # 돌파봉 거래량 배수(직전10봉 평균 대비)
C_CAP3     = float(os.environ.get("BRKUNI_C_CAP3", "3.0"))       # 12:00 대비 이미 이%↑ 오른 뒤 추격금지(0=off)
C_CONV     = float(os.environ.get("BRKUNI_C_CONV", "0.6"))       # |5선-20선| 수렴 상한%(0=off)
C_VOLDEAD  = os.environ.get("BRKUNI_C_VOLDEAD", "YES").strip().upper() == "YES"  # base 거래 죽음(직전10봉보다 한산) 요구
# [2026-07-08 친구님 "낮은 지점에선 체결강도 안 맞을 수 있어"] 진입 체결강도 = 절대 100 OR 저점반등(저점+8pt·돈맥/바닥과 동일).
#   낮은 base는 절대 100이 안 나옴(바닥 실측 58~61) → 보드가 쌓는 che 저점(돈흐름_che_state.json) 대비 반등으로 대체 인정.
C_REB_PT   = float(os.environ.get("BRKUNI_C_REB_PT", "8"))
C_REB_MINN = int(os.environ.get("BRKUNI_C_REB_MINN", "5"))
# [2026-07-08 친구님 "매도는 돈맥과 동일하게"] C 매도 = 돈맥 스택(구조붕괴>하드-2>che되돌림>vol_exit>EOD·MF_* env 공유로 완전동조).
#   돈맥 스택 = 기존 C자체매도(베이스하단/che끌기/고점-2.5)의 상위집합 + 최대손실캡(-2%) + che되돌림 조기매도. 롤백: setx BRKUNI_C_EXIT OWN.
C_EXIT_MFLOW = os.environ.get("BRKUNI_C_EXIT", "MFLOW").strip().upper() == "MFLOW"
# 매도(추세용·넓게)
# [2026-07-08 친구님 "돈맥 등 다른 전략 매도와 같이 쓰면 좋은데"] 공통매도(vol_exit) 통일 — 하드 → vol_exit → EOD.
#   상한가 익일시가 특례·C모드 자체매도(백테검증형)는 유지. 롤백: setx BRKUNI_EXIT_UNIFIED NO(옛 자체매도).
EXIT_UNIFIED = os.environ.get("BRKUNI_EXIT_UNIFIED", "YES").strip().upper() == "YES"
HARD       = float(os.environ.get("BRKUNI_HARD", "3.0"))
TRAIL_ARM  = float(os.environ.get("BRKUNI_TRAIL_ARM", "3.0"))
TRAIL_GIVE = float(os.environ.get("BRKUNI_TRAIL_GIVE", "4.0"))
HOLD_MODE  = os.environ.get("BRKUNI_HOLD", "EOD").strip().upper()
EOD_HM     = os.environ.get("BRKUNI_EOD_HM", "1518")
# ★상한가 → 익일 시가매도
LIMITUP_NEXTOPEN = os.environ.get("BRKUNI_LIMITUP_NEXTOPEN", "YES").strip().upper() == "YES"
LIMIT_NEAR = float(os.environ.get("BRKUNI_LIMIT_NEAR", "1.295"))   # 전일종가×이 배수↑ = 상한가권(KOSDAQ +30%)
BARS_TTL   = float(os.environ.get("BRKUNI_BARS_TTL", "60"))

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
EOD_CSV = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
OUTD = Path(r"C:\stock_bot\data\돌파사냥꾼")
POS  = OUTD / "포지션.json"
BOARD= OUTD / "돌파사냥_현황판.txt"
BARSC= OUTD / "bars_cache.json"
LOG  = Path(r"C:\stock_bot\data\LOG\돌파사냥꾼.log")
RT_OPEN = Path(r"C:\stock_bot\data\rt_open_positions.json")
_PC = {"d": None}


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True); open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception: pass


def _jload(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, p)


def _snap():
    try: return json.loads(SNAP.read_text(encoding="utf-8")).get("codes", {}) or {}
    except Exception: return {}


def _che(sd):
    try:
        v = sd.get("che_str"); return float(v) if isinstance(v, (int, float)) else None
    except Exception: return None


def _prevclose(code):
    """전일종가(eod_daily_bars 최신일 close) — 상한가 판정용. 최초 1회 로드·캐시."""
    if _PC["d"] is None:
        m = {}
        try:
            with open(EOD_CSV, encoding="utf-8-sig") as f:
                r = csv.reader(f); h = next(r)
                di = h.index("date"); ci = h.index("code"); pi = h.index("close")
                rows = list(r)
            maxd = rows[-1][di] if rows else ""
            for x in rows:
                if len(x) > pi and x[di] == maxd:
                    try: m[str(x[ci]).zfill(6)] = float(x[pi])
                    except Exception: pass
        except Exception: pass
        _PC["d"] = m
    return _PC["d"].get(str(code).zfill(6), 0.0)


def _bars(bc, code, cache):
    e = cache.get(code)
    if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= BARS_TTL and e.get("bars"):
        return [tuple(x) for x in e["bars"]]
    def ff(x):
        try: return abs(float(str(x).replace(",", "")))
        except Exception: return 0.0
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                  output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량"], timeout_sec=6.0, screen_no="9722")
        today = datetime.now().strftime("%Y%m%d"); out = []
        for z in (((r or {}).get("data") or {}).get("records") or [])[::-1]:
            ts = str(z.get("체결시간", ""))
            if ts[:8] != today: continue
            out.append((ts[8:12], ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가")), ff(z.get("거래량"))))
        if out: cache[code] = {"ts": time.time(), "bars": out}
        return out
    except Exception: return []


def _vol_proj(bars):
    """[2026-07-08 친구님 '늦게 사는 것 없어지나'] 진행중 3분봉 거래량을 경과시간으로 환산 —
       돌파 직후(봉 초반)엔 거래량이 덜 쌓여 배수 미달 → 1~2분 늦게 사던 문제 해결(바닥사냥꾼 7/4 검증 방식).
       환산배율 최대 3배(경과 1/3 미만은 1/3로 클램프·과대추정 방지)."""
    try:
        hm = bars[-1][0]
        start = int(hm[:2]) * 60 + int(hm[2:])
        nowm = datetime.now().hour * 60 + datetime.now().minute + datetime.now().second / 60.0
        frac = max(0.33, min(1.0, (nowm - start) / 3.0))
        return bars[-1][5] / frac
    except Exception:
        return bars[-1][5]


def _sma(bars, period, back=0):
    cl = [b[4] for b in bars]; end = len(cl) - back
    if end < period: return None
    return sum(cl[end - period:end]) / period


def mode_A(bars, cur):
    """🅰 신고가 돌파. A_REBREAK=YES(기본): '재돌파'만 — 당일고점이 A_MINAGE봉 이상 버틴 뒤 그 위로 실제 돌파.
       cur≥고점 0.7%근접 방식(구버전)은 정의상 항상 그 시점 꼭대기에서 사게 되어 폐기(롤백 env로만)."""
    day_open = bars[0][1]
    if day_open <= 0: return None
    if cur < day_open * (1 + A_UP / 100.0): return None
    if cur <= bars[-1][1]: return None
    if not A_REBREAK:                                   # 구버전(추격) — 롤백용
        day_high = max(b[2] for b in bars)
        if cur < day_high * (1 - A_NEARHIGH / 100.0): return None
        return {"mode": "신고가", "ref": round(day_high), "info": f"시가+{(cur/day_open-1)*100:.1f}%"}
    if len(bars) < A_MINAGE + 2: return None
    prior = bars[:-1]                                   # 현재(진행중) 봉 제외
    ph = max(b[2] for b in prior)
    hi_idx = max(i for i, b in enumerate(prior) if b[2] >= ph)
    age = (len(bars) - 1) - hi_idx                      # 고점 세운 뒤 지난 봉수
    if age < A_MINAGE: return None                      # 고점이 안 익음 = 수직 급등 진행중 → 추격 금지
    if cur <= ph: return None                           # 그 고점 실제 돌파
    if cur > ph * (1 + A_MAXEXT / 100.0): return None   # 이미 멀리 감 = 추격 배제
    if A_SURGE5 > 0 and len(bars) >= 6:
        c5 = bars[-6][4]
        if c5 > 0 and (cur / c5 - 1) * 100 > A_SURGE5: return None   # V자 급반등(깊은 눌림→수직 복귀) 추격 금지
    w = bars[-(A_MINAGE + 1):-1]
    vavg = sum(b[5] for b in w) / len(w) if w else 0.0
    _vp = _vol_proj(bars)                                        # [7/8] 진행중 봉 3분 환산(늦은진입 해결)
    volx = round(_vp / vavg, 2) if vavg > 0 else None
    if A_VOLX > 0 and vavg > 0 and _vp < vavg * A_VOLX: return None   # 거래량 동반(환산)
    return {"mode": "신고가재돌파", "ref": round(ph),
            "info": f"고점{ph:,.0f}({age}봉숙성)돌파·시가+{(cur/day_open-1)*100:.1f}%",
            "age": age, "ext": round((cur / ph - 1) * 100, 2), "volx": volx,
            "surge5": round((cur / bars[-6][4] - 1) * 100, 2) if len(bars) >= 6 and bars[-6][4] > 0 else None}


def mode_B(bars, cur):
    """🅱 베이스 돌파(진짜 박스+거래량): 최근 박스 좁고, 박스상단 돌파, 거래량 동반."""
    if len(bars) < BASE_LOOKBACK + 2: return None
    win = bars[-(BASE_LOOKBACK + 1):-1]           # 직전 베이스(현재봉 제외)
    hi = max(b[2] for b in win); lo = min(b[3] for b in win)
    if lo <= 0: return None
    rng = (hi - lo) / lo * 100
    if rng > BASE_RANGE: return None              # 베이스 좁아야(횡보)
    if cur <= hi: return None                      # 박스상단 돌파
    if cur > hi * (1 + BASE_MAXEXT / 100.0): return None   # 너무 위=추격 배제
    if cur <= bars[-1][1]: return None             # 양봉
    vavg = sum(b[5] for b in win) / len(win)
    _vp = _vol_proj(bars)                                        # [7/8] 진행중 봉 3분 환산(늦은진입 해결)
    if vavg > 0 and _vp < vavg * VOL_MULT: return None  # 거래량 동반(환산)
    return {"mode": "베이스", "ref": round(hi), "info": f"박스{rng:.1f}%·{hi:,.0f}돌파",
            "rng": round(rng, 2), "ext": round((cur / hi - 1) * 100, 2),
            "volx": round(_vp / vavg, 2) if vavg > 0 else None,
            "surge5": round((cur / bars[-6][4] - 1) * 100, 2) if len(bars) >= 6 and bars[-6][4] > 0 else None}


def mode_C(bars, cur):
    """🅲 오후베이스: 12:20~13:45 조용한 횡보 base(5/7/10봉 폭<=C_BASE_W%) 첫 돌파. 손절앵커 = base 하단(base_lo).
       조건: 양봉 + base거래죽음 + 5/20선수렴 + 돌파봉 거래량 x C_VOLX + 12:00比 추격캡. che는 run() 공통(필수)."""
    if len(bars) < 22: return None
    hm = bars[-1][0]
    if not (C_START <= hm <= C_END): return None
    if cur <= bars[-1][1]: return None                          # 양봉
    base = None
    for w in (5, 7, 10):
        if len(bars) < w + 1: continue
        win = bars[-(w + 1):-1]
        hi = max(b[2] for b in win); lo = min(b[3] for b in win)
        if lo > 0 and (hi - lo) / lo * 100 <= C_BASE_W:
            base = (w, hi, lo, sum(b[5] for b in win) / w); break
    if not base: return None
    w, hi, lo, bvol = base
    if cur <= hi: return None                                   # base 상단 첫 돌파(종목당 1회는 run()이 보장)
    if C_VOLDEAD and len(bars) >= 21:
        pvol = sum(b[5] for b in bars[-21:-11]) / 10
        if pvol > 0 and bvol > pvol: return None                # base 거래 죽음
    cl = [b[4] for b in bars]
    m5 = sum(cl[-5:]) / 5; m20 = sum(cl[-20:]) / 20
    if C_CONV > 0 and (m20 <= 0 or abs(m5 / m20 - 1) * 100 > C_CONV): return None   # 수렴
    v10 = sum(b[5] for b in bars[-11:-1]) / 10
    if v10 > 0 and _vol_proj(bars) < v10 * C_VOLX: return None  # 돌파봉 거래량(3분 환산·[7/8] 늦은진입 해결)
    if C_CAP3 > 0:
        p12 = next((b[4] for b in bars if b[0] >= "1200"), None)
        if p12 and (cur / p12 - 1) * 100 >= C_CAP3: return None # 오후 이미 +3% 오른 뒤 추격금지
    rng = (hi - lo) / lo * 100
    return {"mode": "오후베이스", "ref": round(hi), "base_lo": round(lo),
            "info": f"base{w}봉 {rng:.1f}%·{hi:,.0f}돌파·량x{round(bars[-1][5]/v10,1) if v10>0 else '-'}",
            "rng": round(rng, 2), "ext": round((cur / hi - 1) * 100, 2),
            "volx": round(bars[-1][5] / v10, 2) if v10 > 0 else None, "surge5": None}


def _order(bc, code, qty, side, tag, live):
    if not (LIVE and live):
        return True
    try:
        ai = bc.account_info("ACCNO"); accs = (ai.get("data") or {}).get("accounts") or []
        if isinstance(accs, str): accs = [a for a in accs.split(";") if a]   # [7/6 근본수정] 브로커 문자열 계좌 파싱
        acc = (accs[0] if isinstance(accs, list) and accs else "") or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()  # env 폴백
        if not acc: _log(f"[{tag}] 계좌없음"); return False
        r = bc.send_order_real(idempotency_key=f"bkuni_{side.lower()}_{code}_{uuid.uuid4()}", account=acc,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"BKUNI_{side}_{code}", screen_no="9723")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[LIVE] {side} {code} x{qty} status={st} → {'성공' if ok else '실패'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def _sell_decide(cur, buy, peak, che, ma5, ma20, hm):
    if buy > 0 and (cur / buy - 1) * 100 <= -HARD: return f"하드-{HARD:g}%"
    if HOLD_MODE == "EOD" and hm >= EOD_HM: return "EOD청산"
    if che is not None and che >= CHE_MIN: return None                     # 매수세 살아있음=끌기
    if ma20 > 0 and cur < ma20: return "20선이탈(추세붕괴)"
    if ma5 > 0 and cur < ma5: return "5선이탈"
    if buy > 0 and peak > 0 and (peak / buy - 1) * 100 >= TRAIL_ARM and cur <= peak * (1 - TRAIL_GIVE / 100.0):
        return f"트레일(고점-{TRAIL_GIVE:g}%)"
    return None


def run():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < "0900" or hm > "1530": return
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive(): _log("broker dead → skip"); return
        bc = BrokerClient()
    except Exception as e:
        _log(f"broker 연결실패 {e}"); return
    OUTD.mkdir(parents=True, exist_ok=True)
    snap = _snap(); pos = _jload(POS)
    bars_cache = _jload(BARSC); bars_cache = bars_cache if isinstance(bars_cache, dict) else {}
    mode = "[LIVE]" if LIVE else "[그림자]"

    # ===== 매도관리 =====
    for c, p in list(pos.items()):
        if not isinstance(p, dict) or p.get("status") != "HOLDING": continue
        # ★상한가 오버나잇 대기 포지션(이전 거래일) → 익일 시가 매도. [7/8 친구님] 09:00~06 창 놓치면(브로커 사망 등)
        #   당일 아무 때나 일반 매도(방치 방지 — "다른 전략 매도처럼 똑같이").
        if p.get("hold_overnight") and p.get("date") != today:
            if hm >= "0900":
                sd = snap.get(c) or {}; cur = float(sd.get("cur", 0) or 0)
                if cur <= 0:
                    b = _bars(bc, c, bars_cache); cur = b[0][1] if b else 0.0   # 시가
                if cur > 0:
                    _order(bc, c, int(p.get("qty", 0) or 0), "SELL", "익일시가매도", p.get("live"))
                    p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = "익일시가매도(상한가)"; p["sell_hm"] = hm
                    _log(f"{mode} SELL {c} @{cur:,.0f} 익일시가매도(상한가) 매수{p.get('buy_price'):,.0f}")
                    if p.get("live"):
                        try:
                            import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                        except Exception:
                            pass
            continue
        if p.get("date") != today: continue
        sd = snap.get(c) or {}; cur = float(sd.get("cur", 0) or 0)
        b = _bars(bc, c, bars_cache)
        if cur <= 0: cur = b[-1][4] if b else 0.0
        if cur <= 0: continue
        che = _che(sd); buy = float(p.get("buy_price", 0) or 0)
        peak = max(float(p.get("peak", buy) or buy), cur); p["peak"] = peak
        # ★상한가 도달 → 당일 안 팔고 익일 시가매도 예약
        pc = _prevclose(c)
        if LIMITUP_NEXTOPEN and pc > 0 and cur >= pc * LIMIT_NEAR:
            if not p.get("hold_overnight"):
                p["hold_overnight"] = True; p["exit_plan"] = "익일시가매도(상한가)"
                _log(f"{mode} 🔒상한가 {c} @{cur:,.0f} → 오늘 홀드·익일 시가매도 예약")
            continue
        ma5 = _sma(b, 5) or 0.0; ma20 = _sma(b, 20) or 0.0
        if p.get("brk_mode") == "오후베이스":
            _blo = float(p.get("base_lo", 0) or 0)
            if C_EXIT_MFLOW:
                # [7/8 친구님 "매도는 돈맥과 동일"] 돈맥 스택(MF_* env 공유): 구조붕괴(베이스하단-버퍼) > 하드-2% > che되돌림 > vol_exit > EOD
                _mf_buf = float(os.environ.get("MF_STRUCT_BUF", "0.5")) / 100.0
                _mf_hard = float(os.environ.get("MF_HARDCUT", "-2.0") or 0)
                _mf_rpt = float(os.environ.get("MF_RECOIL_PT", "12"))
                _mf_rmin = float(os.environ.get("MF_RECOIL_MINPEAK", "100"))
                sell = None
                if _blo > 0 and cur < _blo * (1 - _mf_buf):
                    sell = f"구조붕괴(베이스하단{_blo:,.0f}이탈)"
                elif _mf_hard < 0 and buy > 0 and (cur / buy - 1) * 100 <= _mf_hard:
                    sell = f"하드{_mf_hard:g}%"
                else:
                    if che is not None:
                        pkche = max(float(p.get("peak_che", 0) or 0), che)
                        p["peak_che"] = pkche
                        if pkche >= _mf_rmin and che <= pkche - _mf_rpt:
                            sell = f"che되돌림({pkche:.0f}→{che:.0f})"
                    if not sell:
                        try:
                            import vol_exit as VE
                            s, _rr = VE.decide(c, buy, peak, cur, ma20_hard=True, che=che)
                            if s:
                                sell = _rr or "vol_exit"
                        except Exception:
                            pass
                if not sell and hm >= EOD_HM:
                    sell = "EOD청산"
            else:
                # [옛 자체매도 — 롤백용] base하단 / che>=100 끌기 / 고점-2.5% / EOD
                sell = None
                if _blo > 0 and cur < _blo: sell = "베이스하단이탈"
                elif hm >= EOD_HM: sell = "EOD청산"
                elif not (che is not None and che >= CHE_MIN) and peak > buy and cur <= peak * 0.975: sell = "고점-2.5%"
        elif EXIT_UNIFIED:
            # [7/8 친구님] 공통매도 통일(돈맥 등 전 전략과 동일) — 하드 → vol_exit(매수우위 끌기/매도우위 컷) → EOD
            sell = None
            if buy > 0 and (cur / buy - 1) * 100 <= -HARD:
                sell = f"하드-{HARD:g}%"
            else:
                try:
                    import vol_exit as VE
                    s, _rr = VE.decide(c, buy, peak, cur, ma20_hard=True, che=che)
                    if s:
                        sell = _rr or "vol_exit"
                except Exception:
                    sell = _sell_decide(cur, buy, peak, che, ma5, ma20, hm)   # vol_exit 불가시 옛 방식(fail-open)
            if not sell and HOLD_MODE == "EOD" and hm >= EOD_HM:
                sell = "EOD청산"
        else:
            sell = _sell_decide(cur, buy, peak, che, ma5, ma20, hm)
        if sell:
            _order(bc, c, int(p.get("qty", 0) or 0), "SELL", sell, p.get("live"))
            # ★매도 진단 [7/4 친구님 매도가설 추적] — 그 순간 윗꼬리/체결량비/che 기록(분석용·판단엔 미사용)
            ed = {}
            try:
                if b:
                    hb = b[-1]; rngv = hb[2] - hb[3]
                    ed["wick"] = round((hb[2] - max(hb[1], hb[4])) / rngv, 2) if rngv > 0 else None
                    w5 = b[-6:-1]; vavg = sum(x[5] for x in w5) / len(w5) if w5 else 0.0
                    ed["volx"] = round(hb[5] / vavg, 2) if vavg > 0 else None
                ed["che"] = che
            except Exception: pass
            p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = sell; p["sell_hm"] = hm; p["exit_diag"] = ed
            _log(f"{mode} SELL {c} @{cur:,.0f} ({(cur/buy-1)*100:+.1f}%) {sell}"
                 f" | 꼬리{ed.get('wick')} 량x{ed.get('volx')} che{ed.get('che')}")
            if p.get("live"):
                try:
                    import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                except Exception:
                    pass
    _jsave(POS, pos)

    # ===== 진입(2모드) =====
    board = [f"=== 돌파사냥꾼 {mode} {now:%H:%M} (신고가{'ON' if MODE_A else 'off'}·베이스{'ON' if MODE_B else 'off'}·che≥{CHE_MIN:.0f}·CAP{CAP:,}·TOP{TOPN}) ==="]
    held = sum(1 for p in pos.values() if isinstance(p, dict) and p.get("status") == "HOLDING")
    # 전역 daily 상한(과다매매 방지)
    budget_block = False
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            budget_block = True; board.append("  [전역상한] 신규진입 보류")
    except Exception: pass
    # [2026-07-08 TR다이어트] 모드 시간창이 전부 닫혔으면 진입 스캔 자체를 안 함 —
    #   기존엔 A(~12:00)/B(~10:30)/C(12:20~13:45) 다 닫힌 13:45~15:30에도 유니버스 최대 100종목 opt10080을
    #   매분 폭격(신호는 어차피 None). 브로커 과부하(51분 사망주기)의 숨은 기여자 → 창 열린 때만 스캔.
    _started = hm >= START_HM        # [7/8 친구님 "오후 1시부터 가동"] 시작 전엔 진입 스캔 없음(매도관리는 위에서 정상)
    _a_open = _started and MODE_A and int(hm) <= int(A_END)
    _b_open = _started and MODE_B and int(hm) <= int(B_END)
    _c_open = _started and MODE_C in ("SHADOW", "LIVE") and (C_START <= hm <= C_END)
    if not (_a_open or _b_open or _c_open):
        board.append("  [스캔휴식] 진입 시간창 없음(TR 절약) — 매도관리만")
    if not budget_block and held < TOPN and (_a_open or _b_open or _c_open):
        uni = []
        if MFLOW_UNI:                                 # [7/7 친구님] ★돈맥 선별기 매수세 순위(실시간 순매수)로 유니버스 — 돈 몰리는 종목에서만 돌파
            try:
                _mb = json.load(open(MFLOW_BOARD, encoding="utf-8"))
                _rows = _mb.get("rows", []) if isinstance(_mb, dict) else []
                # [7/8 친구님] ⭐별표 전부 = 사냥터(그중 돌파패턴 맞는 놈만 잡음). MFLOW_STAR=NO면 등급(🟢🟡)방식.
                uni = [str(r.get("code", "")).zfill(6) for r in _rows       # 이미 순매수 우위 순 정렬(1등=매수세 최강)
                       if (r.get("star") if MFLOW_STAR else str(r.get("grade", "")).startswith(MFLOW_GRADES))][:LEADER_TOPN]
                if uni:
                    _log(f"[유니버스] 돈맥 선별기 {'⭐별표' if MFLOW_STAR else '매수세'} {len(uni)}종목(순매수순) → 이 안에서 돌파 스캔")
            except Exception: uni = []
        # [2026-07-08 친구님 "금액 2만으로 낮췄으니 밖에 있는 거 쓸 필요 없어 — 선별기만 사용"]
        #   MFLOW_UNI=YES면 폴백 없음(선별판 비면 돌파도 쉼 = 선별기가 유일한 소스). 옛 폴백은 MFLOW_UNI=NO일 때만.
        if not uni and not MFLOW_UNI and SCALP_UNI:   # 폴백: 단타 선별(daily_leader_board·전날) — 선별기만 모드에선 미사용
            try:
                _bd = json.load(open(r"C:\stock_bot\data\daily_leader_board.json", encoding="utf-8"))
                uni = [str(c).zfill(6) for c in (_bd.get("codes") or [])][:LEADER_TOPN]
            except Exception: uni = []
        if not uni and not MFLOW_UNI:                 # 폴백2: 거래대금 대장(실시간 opt10032) — 선별기만 모드에선 미사용
            try:
                import leader_filter as lf; uni = list(lf.leader_list(bc) or [])[:LEADER_TOPN]
            except Exception: uni = []
        excl = {str(k).zfill(6) for k, v in _jload(RT_OPEN).items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
        for code in uni:
            if held >= TOPN: break
            code = str(code).zfill(6)
            if code in excl: continue
            he = pos.get(code)
            if isinstance(he, dict) and he.get("date") == today and he.get("status") in ("HOLDING", "DONE", "C_SHADOW"): continue
            bars = _bars(bc, code, bars_cache)
            if not bars or len(bars) < 5: continue
            sd = snap.get(code) or {}; cur = float(sd.get("cur", 0) or 0) or bars[-1][4]
            if cur <= 0: continue
            hit = None
            if MODE_A and int(hm) <= int(A_END): hit = mode_A(bars, cur)
            if not hit and MODE_B and int(hm) <= int(B_END): hit = mode_B(bars, cur)
            if not hit and MODE_C in ("SHADOW", "LIVE"): hit = mode_C(bars, cur)
            if not hit: continue
            che = _che(sd); che_dom = (che is not None and che >= CHE_MIN)
            _reb_ok = False
            if hit["mode"] == "오후베이스":
                # [7/8 친구님] 낮은 base 보완: 절대 100 OR che 저점반등(보드 누적 저점 +8pt·표본 5↑ — 돈맥/바닥과 동일)
                if not che_dom and che is not None:
                    try:
                        _cs = (json.loads(Path(r"C:\stock_bot\data\돈흐름_che_state.json").read_text(encoding="utf-8")) or {}).get(code) or {}
                        _cmin = _cs.get("min"); _cn = int(_cs.get("n", 0) or 0)
                        _reb_ok = (_cmin is not None and _cn >= C_REB_MINN and che >= float(_cmin) + C_REB_PT)
                    except Exception:
                        _reb_ok = False
                if not (che_dom or _reb_ok):
                    continue                                   # 절대100도 저점반등도 아님 → 대기
                if MODE_C != "LIVE":                           # ★기본 그림자: 기록만·주문0
                    pos[code] = {"code": code, "status": "C_SHADOW", "date": today, "hm": hm}
                    _log(f"[C그림자] {code} @{cur:,.0f} {hit['info']} che={che} → 기록만(주문0)")
                    try:
                        fC = OUTD / f"돌파사냥_C그림자_{today}.csv"; newC = not fC.exists()
                        with open(fC, "a", encoding="utf-8-sig", newline="") as fp:
                            wC = csv.writer(fp)
                            if newC: wC.writerow(["hm", "code", "cur", "base_hi", "base_lo", "info", "che"])
                            wC.writerow([hm, code, f"{cur:.0f}", hit["ref"], hit.get("base_lo"), hit["info"], che])
                    except Exception: pass
                    continue
            if LIVE and not che_dom and not (hit["mode"] == "오후베이스" and _reb_ok):
                board.append(f"  ⏸ {code} {hit['mode']}통과·che대기(che={che})"); continue   # ★실전 che 필수(C 저점반등은 예외)
            try:                                   # ★[2026-07-06] 스마트머니 던지기 회피(공용·외국인+프로그램 실시간)
                import smart_money as _SM
                _blk, _smi = _SM.dumping(bc, code, cur)
                if _blk:
                    board.append(f"  ⛔ {code} 스마트머니 던지기 차단 [{_smi}]"); continue
            except Exception:
                pass
            qty = max(1, int(CAP / cur)) if cur > 0 else 0
            if not _order(bc, code, qty, "BUY", f"진입 {hit['mode']}", LIVE):
                continue
            # ★진단 로그 [7/4] — "왜 샀는지" 전 필드 기록(그림자 포함). 매수 100건 모아 유형별 분석용.
            day_high = max(b[2] for b in bars)
            pos_hi = round(cur / day_high * 100, 2) if day_high > 0 else None      # 고점 대비 위치%
            nh_cnt = sum(1 for k in range(1, len(bars)) if bars[k][2] > max(x[2] for x in bars[:k]))  # 당일 고점갱신 봉수
            pc0 = _prevclose(code)
            diag = {"rng": hit.get("rng"), "age": hit.get("age"), "ext": hit.get("ext"),
                    "volx": hit.get("volx"), "surge5": hit.get("surge5"),
                    "pos_vs_high": pos_hi, "newhigh_cnt": nh_cnt,
                    "day_gain": round((cur / pc0 - 1) * 100, 2) if pc0 > 0 else None}
            pos[code] = {"code": code, "status": "HOLDING", "buy_price": cur, "qty": qty, "peak": cur,
                         "brk_mode": hit["mode"], "ref": hit["ref"], "che": che, "base_lo": hit.get("base_lo"),
                         "date": today, "buy_hm": hm, "live": LIVE, "diag": diag}
            if LIVE:
                try:
                    import rt_registry as _RT; _RT.register(code, qty, cur, "BRKUNI")   # [7/5] 공용장부 즉시등록(중복매수·전역한도 시차 제거)
                except Exception:
                    pass
            held += 1
            _log(f"{mode} BUY {code} @{cur:,.0f} [{hit['mode']}] {hit['info']} che={che} x{qty}"
                 f" | 박스폭{diag['rng']}% 숙성{diag['age']}봉 확장{diag['ext']}% 량x{diag['volx']}"
                 f" 5봉{diag['surge5']}% 고점대비{pos_hi}% 고점갱신{nh_cnt}회 전일比{diag['day_gain']}%")
            board.append(f"  🚀★매수 {code} @{cur:,.0f} [{hit['mode']}] {hit['info']} che={che}")
            try:
                f = OUTD / f"돌파사냥_시그널_{today}.csv"; new = not f.exists()
                with open(f, "a", encoding="utf-8-sig", newline="") as fp:
                    w = csv.writer(fp)
                    if new: w.writerow(["hm", "code", "buy", "mode", "ref", "info", "che",
                                        "box_rng", "age", "ext", "volx", "surge5", "pos_vs_high", "newhigh_cnt", "day_gain"])
                    w.writerow([hm, code, f"{cur:.0f}", hit["mode"], hit["ref"], hit["info"], che,
                                diag["rng"], diag["age"], diag["ext"], diag["volx"], diag["surge5"], pos_hi, nh_cnt, diag["day_gain"]])
            except Exception: pass
    for c, p in pos.items():
        if isinstance(p, dict) and p.get("status") == "HOLDING":
            ov = " 🔒익일시가매도" if p.get("hold_overnight") else ""
            board.append(f"  ● 보유 {c} [{p.get('brk_mode')}] 매수{p.get('buy_price'):,.0f} 고점{p.get('peak',0):,.0f}{ov}")
    try: BOARD.write_text("\n".join(board) + "\n", encoding="utf-8")
    except Exception: pass
    _jsave(POS, pos)
    _jsave(BARSC, {c: e for c, e in bars_cache.items() if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= 600})


if __name__ == "__main__":
    # [2026-07-08 친구님 "돌파도 8초마다"] 1분 태스크 내부 8초 빠른루프(돈맥과 동일 구조).
    #   가격/체결강도=실시간 스냅샷(TR 0)·3분봉=60초 캐시 → 8초로 돌려도 키움 조회 증가 없음.
    #   프로세스 55초 수명 → 1분 태스크가 재기동(자동복구). 롤백: setx BRKUNI_LOOP_SEC 60.
    _deadline = time.monotonic() + float(os.environ.get("BRKUNI_RUN_SEC", "55"))
    _loop = float(os.environ.get("BRKUNI_LOOP_SEC", "8"))
    while True:
        try:
            run()
        except Exception as ex:
            _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
        if time.monotonic() >= _deadline:
            break
        time.sleep(_loop)

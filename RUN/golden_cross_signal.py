# -*- coding: utf-8 -*-
"""[골든크로스 신규-진입 신호 v2 — 친구님 2026-06-30 통합패치]
목적: 5/20 골든크로스 '횡보 구간 반복 매수' 제거 → "상승이 시작되는 첫 골든크로스"만 매수.
범위: ★매수 조건 판단부 전용★. 매도/주문/리스크/수집 로직과 무관(이 모듈은 신호 True/False만 판단).

데이터: 라이브 1분봉(prices_1m.csv·OHLCV)을 3분봉으로 resample → MA5/MA20·거래량·고저변동폭 계산.
        (기존 3분봉 brk_rt_state는 종가만 있어 거래량/고저 불가 → 1분봉 재집계로 해결. 수집기 무수정.)

조건(전부 충족시 BUY 신호):
 1) MA5_prev <= MA20_prev  &  MA5_now > MA20_now      (신규 골든크로스 — 직전봉 아래→현재봉 위)
 2) 0.20 <= gap_pct <= 1.20                            (이격: 너무 약하지도/벌어지지도 않음)
 3) slope5_pct  >= 0.30                                (5MA 3봉전 대비 상승)
 4) slope20_pct >= 0.05                                (20MA 하락/평평 제외)
 5) close > MA5_now  &  close > MA20_now               (현재가가 두 선 위)
 6) volume_now >= volume_avg20 * 1.50  (& >0)          (체결량 평균 1.5배 이상)
 7) range20_pct >= 3.00                                (20봉 변동폭 — 횡보 제거)
 8) 같은 크로스 구간 1회만(매수후 MA5<MA20 재발생 전엔 재매수 금지)

임계값은 전부 env로 조정 가능(아래 _F/_I). 로그사유: NO_NEW_GOLDEN_CROSS·GAP_TOO_SMALL·GAP_TOO_WIDE·
MA5_SLOPE_FLAT·MA20_SLOPE_FLAT·PRICE_BELOW_MA·VOLUME_WEAK·RANGE_SIDEWAYS·ALREADY_BOUGHT_THIS_CROSS·NO_DATA.
"""
import os, json
from datetime import datetime
from pathlib import Path

PRICES_1M = r"C:\stock_bot\data\prices_1m.csv"
_GUARD = Path(rf"C:\stock_bot\DATA\gcross_cross_guard_{datetime.now():%Y%m%d}.json")  # 재매수 가드 상태(당일)

# --- 임계값(스펙 기본값 · env override) ---
def _F(k, d):
    try: return float(os.environ.get(k, str(d)))
    except ValueError: return d
def _I(k, d):
    try: return int(os.environ.get(k, str(d)))
    except ValueError: return d

GAP_MIN   = _F("GCROSS2_GAP_MIN",   0.20)
GAP_MAX   = _F("GCROSS2_GAP_MAX",   1.20)
SLOPE5    = _F("GCROSS2_SLOPE5",    0.30)
SLOPE20   = _F("GCROSS2_SLOPE20",   0.05)
VOL_MULT  = _F("GCROSS2_VOL_MULT",  1.50)
RANGE_MIN = _F("GCROSS2_RANGE_MIN", 3.00)
BAR_MIN   = _I("GCROSS2_BAR_MIN",   23)    # MA20 3봉전 기울기까지 보려면 최소 23봉

_LOGP = Path(r"C:\stock_bot\data\LOG\golden_cross_signal.log")
def _log(m):
    try:
        _LOGP.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOGP, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}\n")
    except Exception: pass


# --- 재매수 가드(상태머신) ---
def _load_guard():
    try: return json.loads(_GUARD.read_text(encoding="utf-8"))
    except Exception: return {}

def _save_guard(d):
    try:
        tmp = _GUARD.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _GUARD)
    except Exception: pass

def mark_bought(code):
    """실행기가 매수 성공 직후 호출 → 이 크로스 구간 '매수완료' 표시(MA5<MA20 재발생 전엔 재매수 금지)."""
    g = _load_guard(); g[str(code).zfill(6)] = "BOUGHT"; _save_guard(g)


def _mean(a):
    return sum(a) / len(a) if a else 0.0


def _resample_3m(g):
    """1분봉 DataFrame(한 종목·ts오름차순) → 3분봉 OHLCV 리스트[{o,h,l,c,v}]. ts=YYYYMMDDHHMMSS."""
    bars = {}
    for ts, o, h, l, c, v in zip(g["ts"], g["open"], g["high"], g["low"], g["close"], g["volume"]):
        s = str(ts)
        if len(s) < 12:
            continue
        # 3분 버킷 키: 분을 3으로 내림
        try:
            mm = int(s[10:12]); bucket = s[:10] + f"{(mm // 3) * 3:02d}"
        except ValueError:
            continue
        b = bars.get(bucket)
        if b is None:
            bars[bucket] = {"o": o, "h": h, "l": l, "c": c, "v": (v or 0)}
        else:
            b["h"] = max(b["h"], h); b["l"] = min(b["l"], l); b["c"] = c; b["v"] += (v or 0)
    return [bars[k] for k in sorted(bars.keys())]


def evaluate(bars3, code=None):
    """3분봉 OHLCV 리스트로 스펙 1~8 판정. 반환 (ok: bool, reason: str, info: dict).
    code 주면 가드 상태도 갱신(MA5<MA20이면 ARMED 리셋)."""
    n = len(bars3)
    if n < BAR_MIN:
        return False, "NO_DATA", {}
    cl = [b["c"] for b in bars3]; vol = [b["v"] for b in bars3]
    hi = [b["h"] for b in bars3]; lo = [b["l"] for b in bars3]

    ma5_now  = _mean(cl[-5:]);   ma20_now  = _mean(cl[-20:])
    ma5_prev = _mean(cl[-6:-1]); ma20_prev = _mean(cl[-21:-1])
    ma5_3ago = _mean(cl[-8:-3]); ma20_3ago = _mean(cl[-23:-3])
    close_now = cl[-1]

    # 가드 리셋: 현재 MA5<MA20 (크로스 아래로 내려옴) → 다음 신규크로스 매수 허용(ARMED)
    if code is not None and ma5_now < ma20_now:
        g = _load_guard(); k = str(code).zfill(6)
        if g.get(k) == "BOUGHT":
            g[k] = "ARMED"; _save_guard(g)

    # 1) 신규 골든크로스
    if not (ma5_prev <= ma20_prev and ma5_now > ma20_now):
        return False, "NO_NEW_GOLDEN_CROSS", {}
    # 2) 이격
    gap_pct = (ma5_now - ma20_now) / ma20_now * 100 if ma20_now else 0
    if gap_pct < GAP_MIN:  return False, "GAP_TOO_SMALL", {"gap": gap_pct}
    if gap_pct > GAP_MAX:  return False, "GAP_TOO_WIDE",  {"gap": gap_pct}
    # 3) 5MA 기울기
    slope5 = (ma5_now - ma5_3ago) / ma5_3ago * 100 if ma5_3ago else 0
    if slope5 < SLOPE5:    return False, "MA5_SLOPE_FLAT", {"slope5": slope5}
    # 4) 20MA 기울기
    slope20 = (ma20_now - ma20_3ago) / ma20_3ago * 100 if ma20_3ago else 0
    if slope20 < SLOPE20:  return False, "MA20_SLOPE_FLAT", {"slope20": slope20}
    # 5) 가격 위치
    if not (close_now > ma5_now and close_now > ma20_now):
        return False, "PRICE_BELOW_MA", {}
    # 6) 체결량
    vol_now = vol[-1]; vol_avg20 = _mean(vol[-21:-1])  # 직전 20봉 평균(현재봉 제외)
    if not (vol_now > 0 and vol_avg20 > 0 and vol_now >= vol_avg20 * VOL_MULT):
        return False, "VOLUME_WEAK", {"v": vol_now, "avg": vol_avg20}
    # 7) 횡보 제거(20봉 변동폭)
    lo20 = min(lo[-20:]); hi20 = max(hi[-20:])
    range20 = (hi20 - lo20) / lo20 * 100 if lo20 else 0
    if range20 < RANGE_MIN: return False, "RANGE_SIDEWAYS", {"range": range20}
    # 8) 재매수 금지(같은 크로스 1회)
    if code is not None and _load_guard().get(str(code).zfill(6)) == "BOUGHT":
        return False, "ALREADY_BOUGHT_THIS_CROSS", {}

    return True, "OK", {"close": close_now, "gap": round(gap_pct, 2), "slope5": round(slope5, 2),
                        "slope20": round(slope20, 2), "vol_x": round(vol_now / vol_avg20, 2),
                        "range20": round(range20, 2)}


def scan(universe=None):
    """prices_1m 한 번 읽어 전 종목 3분봉 재집계 → 스펙 통과 종목 dict 반환.
    반환 {code: {"signal_close": close, "info": "3m-GC-v2", "detail": {...}}}.
    universe 주면 그 집합으로 제한(없으면 prices_1m 전체)."""
    import pandas as pd
    try:
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str},
                         usecols=["code", "ts", "open", "high", "low", "close", "volume"])
    except Exception as ex:
        _log(f"[scan] prices_1m 읽기 실패: {ex}")
        return {}
    df["code"] = df["code"].str.zfill(6)
    if universe is not None:
        uni = {str(c).zfill(6) for c in universe}
        df = df[df["code"].isin(uni)]
    out = {}
    reasons = {}
    for code, g in df.sort_values("ts").groupby("code"):
        bars3 = _resample_3m(g)
        ok, reason, info = evaluate(bars3, code=code)
        reasons[reason] = reasons.get(reason, 0) + 1
        if ok:
            out[code] = {"signal_close": info.get("close", bars3[-1]["c"] if bars3 else 0.0),
                         "info": "3m-GC-v2", "detail": info}
            _log(f"★신규GC {code} {info}")
    # 사유 요약 1줄(통과 없을 때 진단)
    top = sorted(reasons.items(), key=lambda x: -x[1])[:6]
    _log(f"[scan] 통과 {len(out)} · 사유 {dict(top)}")
    return out


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    res = scan()
    print(f"신규 골든크로스 통과: {len(res)}종목")
    for c, v in list(res.items())[:20]:
        print(f"  {c}: {v['detail']}")

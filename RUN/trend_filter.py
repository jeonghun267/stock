# -*- coding: utf-8 -*-
"""[정배열 공용 필터] 친구님 2026-06-29 "모든 전략은 정배열일 때만 매수".
★전략 성격별 2기준 (친구님 승인 "너 생각대로"):
  - strict  = MA5>MA20>MA60  (돌파/신고가 전략용·어차피 5일선 위라 자연스러움)
  - trend   = NOT(역배열 MA5<MA20<MA60 AND 현재가<MA60)  (딥바운스/눌림 전략용) ★[7/9 친구님 "이평선은 5/20/60만"] 40선 폐기
              → 백테검증(메모리 NEW_PB_REV_MA60): 역배열&60일선아래 −1.66%/dead-cat vs 그외 +0.82%/강한반전.
              → '추세죽은 falling knife'만 차단·정상 딥(006920 등)은 허용. 하락장(79%역배열)에도 deep_v 생존.
하루1회 eod_daily_bars로 두 맵 동시계산·캐시(DATA/jeongbae_map_<date>.json) → 실행기는 is_jeongbae(code, mode)만 호출.
env JEONGBAE_GATE=NO면 게이트 끔(기존동작). 데이터없는 종목은 fail-open(통과)·전체차단 방지."""
import json, os
from pathlib import Path
from datetime import datetime

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"


def _map_path():
    # [BUGFIX 2026-06-30 stale] 날짜를 사용시점에 계산(자정 넘긴 프로세스가 전일 맵 읽는 문제 방지).
    return Path(rf"C:\stock_bot\DATA\jeongbae_map_{datetime.now():%Y%m%d}.json")


ENFORCE = os.environ.get("JEONGBAE_GATE", "YES").strip().upper() == "YES"
# [정배열 기울기 2026-06-29 친구님·백테검증] 진짜 정배열 = 순서(MA5>MA20>MA60) + 세 선 모두 우상향(45도).
#   기울기 = 각 MA가 SLOPE_LB일전 대비 SLOPE_MIN%↑. 백테(10개월): 순서만 익일+0.056% vs 순서+기울기≥1% +0.151%(2.7배·최적). 0이면 순서만(구동작).
SLOPE_MIN = float(os.environ.get("JEONGBAE_SLOPE_MIN", "1.0"))   # 세 선 기울기 하한%(롤백 0)
SLOPE_LB  = int(os.environ.get("JEONGBAE_SLOPE_LB", "5"))        # 기울기 측정 lookback(거래일)
_MAP = None
_MAP_DATE = None
_BUILD_OK = False   # [BUGFIX 2026-06-30] 맵이 실데이터로 채워졌나. False면 데이터깨짐 → is_jeongbae가 fail-closed(매수차단)


def _build():
    import pandas as pd
    e = pd.read_csv(EOD, dtype={"date": str, "code": str}, usecols=["date", "code", "market", "close"], low_memory=False)
    e = e[e["market"] == "KOSDAQ"].copy(); e["code"] = e["code"].str.zfill(6)
    e["close"] = pd.to_numeric(e["close"], errors="coerce")
    e = e.dropna(subset=["close"]).sort_values(["code", "date"])
    m = {}
    for code, s in e.groupby("code")["close"]:
        if len(s) < 60 + SLOPE_LB:
            continue
        cur = s.iloc[-1]; ma5 = s.tail(5).mean(); ma20 = s.tail(20).mean(); ma60 = s.tail(60).mean()
        # [정배열 기울기] 순서 + 세 선 모두 SLOPE_LB일전 대비 SLOPE_MIN%↑(우상향=45도). SLOPE_MIN=0이면 순서만(구동작).
        lb = SLOPE_LB
        ma5p = s.iloc[-5-lb:-lb].mean(); ma20p = s.iloc[-20-lb:-lb].mean(); ma60p = s.iloc[-60-lb:-lb].mean()
        slope_ok = (ma5p > 0 and ma20p > 0 and ma60p > 0
                    and ma5 >= ma5p * (1 + SLOPE_MIN/100)
                    and ma20 >= ma20p * (1 + SLOPE_MIN/100)
                    and ma60 >= ma60p * (1 + SLOPE_MIN/100))
        strict = bool(ma5 > ma20 > ma60 and slope_ok)
        # trend: 'dead-cat falling knife'(역배열 MA5<MA20<MA60 & 현재가<MA60)만 차단·나머지 딥 허용
        dead_knife = bool(ma5 < ma20 < ma60 and cur < ma60)   # ★[7/9 친구님 "이평선은 5/20/60만·나머지 버려"] 40선 제거·3분봉(not_reverse)과 통일. 롤백 .bak_ma520_20260709
        trend = (not dead_knife)
        # [RISING 2026-06-29 친구님 백테검증] 1·5·20일선 모두 우상향(기울기 상승). 강세종목 안에서 익일 +0.28%/엣지 +0.41%p.
        #   1일선 우상향=전일대비 상승 · 5/20일선 우상향=오늘 MA > 전일 MA. (20선 위는 우상향이면 자동 포함)
        ma5_prev = s.iloc[-6:-1].mean(); ma20_prev = s.iloc[-21:-1].mean()
        rising = bool(cur > s.iloc[-2] and ma5 > ma5_prev and ma20 > ma20_prev)
        m[code] = {"s": 1 if strict else 0, "t": 1 if trend else 0, "r": 1 if rising else 0}
    return m


def _load():
    global _MAP, _MAP_DATE, _BUILD_OK
    today = datetime.now().strftime("%Y%m%d")
    if _MAP is not None and _MAP_DATE == today:   # [BUGFIX 2026-06-30 stale] 날짜 바뀌면 무효화
        return _MAP
    _MAP_DATE = today
    mp = _map_path()
    try:
        _MAP = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        try:
            _MAP = _build()
            mp.parent.mkdir(parents=True, exist_ok=True)
            tmp = mp.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(_MAP), encoding="utf-8")
            os.replace(str(tmp), str(mp))
        except Exception:
            _MAP = {}
    _BUILD_OK = bool(_MAP)   # [BUGFIX 2026-06-30] 비어있으면(빌드실패/0종목) 데이터깨짐 → fail-closed 트리거
    return _MAP


def is_jeongbae(code, mode="trend"):
    """추세 통과여부. mode='strict'(돌파·5>20>60)·'rising'(우상향 1/5/20)·'trend'(딥·dead-knife만차단). 게이트OFF/데이터없음=True."""
    if not ENFORCE:
        return True
    # [3분봉 모드 2026-06-30 친구님 "모든 배열은 당일 3분봉으로·내 계획기준이 원래 3분봉"] TREND_TIMEFRAME=3MIN이면 일봉맵 대신 당일 3분봉 이평.
    #   strict=3분봉 정배열(5≥20≥60 우상향)·rising=3분봉 우상향(5≥20)·trend=3분봉 역배열아님. 봉부족이면 통과(체결강도가 1차). 실패시 fail-open.
    if os.environ.get("TREND_TIMEFRAME", "DAILY").strip().upper() == "3MIN":
        try:
            import intraday_ma as _im
            _md = str(mode).lower()
            if _md == "strict":
                u = _im.strict_up(code); return True if u is None else bool(u)
            if _md == "rising":
                u = _im.is_up(code); return True if u is None else bool(u)
            return bool(_im.not_reverse(code))   # trend: 3분봉 역배열만 차단
        except Exception:
            return True
    m = _load()
    if not _BUILD_OK:
        # [BUGFIX 2026-06-30] 맵 빌드 실패/0종목 = EOD 데이터 깨짐 → 정배열 확인 불가.
        #   '정배열만 매수'(친구님) 원칙상 확인 불가하면 매수 차단이 보수적(fail-closed). 평소엔 맵 정상이라 무영향.
        return False
    c = str(code).zfill(6)
    rec = m.get(c)
    if rec is None:
        return True   # 맵은 정상인데 이 종목만 없음(신규상장 등) → 통과(기존 의도 유지)
    if not isinstance(rec, dict):  # 구버전 캐시(0/1) 호환
        return bool(rec)
    _md = str(mode).lower()
    _key = "s" if _md == "strict" else ("r" if _md == "rising" else "t")
    return bool(rec.get(_key))


def stats():
    m = _load()
    n = len(m)
    if not n:
        return "정배열맵 0종목(데이터없음·fail-open)"
    sc = sum(1 for v in m.values() if isinstance(v, dict) and v.get("s"))
    tc = sum(1 for v in m.values() if isinstance(v, dict) and v.get("t"))
    rc = sum(1 for v in m.values() if isinstance(v, dict) and v.get("r"))
    return f"추세맵 {n}종목 · strict(5>20>60) {sc} · rising(1/5/20우상향) {rc} · trend(dead-knife제외) {tc}"


if __name__ == "__main__":
    print("JEONGBAE_GATE =", ENFORCE)
    print(stats())
    for c in ["006920", "389470", "067170", "214450"]:
        print(f"  {c}: strict={is_jeongbae(c,'strict')} rising={is_jeongbae(c,'rising')} trend={is_jeongbae(c,'trend')}")

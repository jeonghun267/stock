# -*- coding: utf-8 -*-
"""[조건2 일봉] 5/20/60일선 수렴 후 60일선 우상향 종목 = 매수후보. 하루1회 eod_daily_bars로 계산·캐시.
백테(7/6): 수렴≤2%+60↑ 대장 승률 61.6%(baseline 48.6%)·fwd3d +0.62%. 통합대장 경로③에서 is_conv60(code) 조회.
격리 모듈 — 기존 daily_ma 무영향. 실패=fail-open(False 반환, 매수흐름 안 깸)."""
import os, json, csv, re
from pathlib import Path
from datetime import datetime

_ETF = re.compile(r"KODEX|TIGER|RISE|SOL|KBSTAR|ARIRANG|HANARO|PLUS |ACE |KOSEF|TIMEFOLIO|히어로즈|레버리지|인버스|채권|합성|ETN", re.I)  # [7/6] ETF/ETN 제외

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
DATA = Path(r"C:\stock_bot\data")
CONV_MAX  = float(os.environ.get("UNIFIED_CONV_MAX", "3.0"))    # 수렴 판정: 최근5일 5/20/60 최대이격 상한%
SLOPE_BARS = int(os.environ.get("UNIFIED_CONV_SLOPE", "3"))     # 60선 우상향: 이 봉수 전 대비 상승
LIQ_FLOOR = float(os.environ.get("UNIFIED_CONV_LIQ", "0"))      # 유동성 바닥(거래대금 백만원). 기본0=끔(소비엔진이 유동성 처리·스윙B-TRACK 50억). 코일은 원래 조용
PRICE_MIN = float(os.environ.get("CONV60_PRICE_MIN", "10000"))  # [7/6 친구님] 주가 하한(기본 1만원). 5만 너무 빡빡→백테 하루 22개
_MAP = {"date": None, "set": None}


def _cache_path(day):
    return DATA / f"daily_conv60_{day}.json"


def _build(day):
    # code -> [close...] 최신순 로드 (코스닥 일반주식만·ETF/ETN 제외)
    rows = {}; meta = {}
    try:
        with open(EOD, encoding="utf-8-sig") as f:
            r = csv.reader(f); h = next(r)
            ci = h.index("code"); di = h.index("date"); cli = h.index("close"); vi = h.index("value")
            mi = h.index("market"); ni = h.index("name")
            for x in r:
                if len(x) <= max(cli, vi, mi, ni):
                    continue
                try:
                    _v = float(x[vi]) if x[vi] not in ("", None) else 0.0
                    cd = x[ci].zfill(6)
                    rows.setdefault(cd, []).append((x[di], float(x[cli]), _v))
                    meta[cd] = (x[mi], x[ni])
                except Exception:
                    pass
    except Exception:
        return set()
    ok = set()
    for code, seq in rows.items():
        mk, nmn = meta.get(code, ("", ""))
        if mk != "KOSDAQ" or not code.isdigit() or _ETF.search(nmn or ""):   # [7/6] 코스닥 일반주식만(ETF/KOSPI 제외)
            continue
        seq.sort()                                  # 날짜 오름차순
        if not seq or seq[-1][2] < LIQ_FLOOR:       # 최신일 거래대금(백만원)<바닥 = 잡주 배제
            continue
        cl = [c for _, c, _v in seq]
        n = len(cl)
        if n < 68:
            continue
        def ma(p, back=0):
            e = n - back
            return sum(cl[e - p:e]) / p if e >= p else None
        m5, m20, m60 = ma(5), ma(20), ma(60)
        m60_3, m60_8 = ma(60, 3), ma(60, 8)   # [7/6] '이미 확립된 상승추세'용(갓턴 배제·백테 fwd3d +1.05%)
        if None in (m5, m20, m60, m60_3, m60_8) or m60 <= 0:
            continue
        # 최근5일 최소 스프레드(수렴)
        sp_min = 1e9
        for b in range(5):
            a5, a20, a60 = ma(5, b), ma(20, b), ma(60, b)
            if None in (a5, a20, a60) or a60 <= 0:
                continue
            sp = (max(a5, a20, a60) - min(a5, a20, a60)) / a60 * 100
            sp_min = min(sp_min, sp)
        converged = sp_min <= CONV_MAX
        up60 = (m60 > m60_3) and (m60_3 > m60_8)    # [7/6] 60선 '이미 확립된' 우상향(쭉 상승·갓턴 아님)
        bull = cl[-1] > m20                          # 종가 > 20선
        if converged and up60 and bull and cl[-1] >= PRICE_MIN:   # [7/6 친구님] 주가 1만원+ 하한
            ok.add(code)
    try:
        p = _cache_path(day); tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(sorted(ok), ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(p))
    except Exception:
        pass
    return ok


def _load(day):
    if _MAP["date"] == day and _MAP["set"] is not None:
        return _MAP["set"]
    p = _cache_path(day)
    if p.exists():
        try:
            s = set(json.loads(p.read_text(encoding="utf-8")))
            _MAP.update(date=day, set=s); return s
        except Exception:
            pass
    s = _build(day)
    _MAP.update(date=day, set=s)
    return s


def is_conv60(code):
    """오늘 기준(직전 거래일 종가) 5/20/60 수렴+60우상향 종목이면 True. 실패=False(fail-open)."""
    try:
        return str(code).zfill(6) in _load(datetime.now().strftime("%Y%m%d"))
    except Exception:
        return False


def codes():
    """오늘 수렴60(유동성 통과) 종목 리스트 — 통합대장 유니버스 union용. 실패=[]."""
    try:
        return sorted(_load(datetime.now().strftime("%Y%m%d")))
    except Exception:
        return []


if __name__ == "__main__":
    day = datetime.now().strftime("%Y%m%d")
    s = _build(day)
    print(f"[daily_conv60 {day}] 수렴+60↑ 종목 {len(s)}개 (CONV_MAX={CONV_MAX}% SLOPE={SLOPE_BARS})")
    print("  샘플:", sorted(s)[:15])

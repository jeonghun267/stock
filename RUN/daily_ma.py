# -*- coding: utf-8 -*-
"""[일봉 MA 헬퍼 2026-06-29 친구님 구조기반청산] 종목별 일봉 5일선/20일선 — 청산 손절선용.
하루1회 eod_daily_bars로 계산·캐시(DATA/daily_ma_<date>.json). 실행기는 ma5(code)/ma20(code)만 호출.
fail-safe: 데이터없음/예외 = 0.0(호출측이 0이면 해당 MA청산 skip=기존동작).
"""
import json, os, math, statistics
from pathlib import Path
from datetime import datetime

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
_MAP = None
_MAP_DATE = None


def _cache_path():
    # [BUGFIX 2026-06-30 stale] 날짜를 사용시점에 계산(import시 고정 X) → 자정 넘긴 프로세스가 전일 캐시 읽는 문제 방지.
    return Path(rf"C:\stock_bot\DATA\daily_ma_{datetime.now():%Y%m%d}.json")


def _build():
    import csv, collections
    series = collections.defaultdict(list)
    with open(EOD, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                px = float(row["close"])
                if not (math.isfinite(px) and px > 0):   # [BUGFIX 2026-06-30 #7] 0/음수/NaN/inf 등 비정상 close 차단
                    continue
                series[row["code"].zfill(6)].append((row["date"], px))
            except (ValueError, KeyError):
                pass
    m = {}
    for code, ser in series.items():
        ser.sort()
        cl = [x[1] for x in ser]
        if len(cl) < 20:
            continue
        # [BUGFIX 2026-06-30 #7] 데이터피드 글리치(자리수오류 등) 이상치 제거 — 종목 중앙값의 10배 밖은 버림.
        #   ma20이 한 개의 튄 close로 부풀어 멀쩡한 보유를 '20일선이탈' 강제손절하는 것 방지(정상 일변동은 ±30%라 절대 안걸림).
        med = statistics.median(cl)
        if med > 0:
            cl = [x for x in cl if med * 0.1 <= x <= med * 10]
        if len(cl) < 20:
            continue
        ma5 = sum(cl[-5:]) / 5
        ma20 = sum(cl[-20:]) / 20
        m[code] = [round(ma5, 2), round(ma20, 2)]
    return m


def _load():
    global _MAP, _MAP_DATE
    today = datetime.now().strftime("%Y%m%d")
    if _MAP is not None and _MAP_DATE == today:   # [BUGFIX 2026-06-30 stale] 날짜 바뀌면 캐시 무효화
        return _MAP
    _MAP_DATE = today
    cache = _cache_path()
    try:
        _MAP = json.loads(cache.read_text(encoding="utf-8"))
        return _MAP
    except Exception:
        pass
    try:
        _MAP = _build()
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".json.tmp")           # [BUGFIX 2026-06-30] 원자적 쓰기(동시 빌더 torn-file 방지)
        tmp.write_text(json.dumps(_MAP), encoding="utf-8")
        os.replace(str(tmp), str(cache))
    except Exception:
        _MAP = {}
    return _MAP


def ma5(code):
    v = _load().get(str(code).zfill(6))
    return float(v[0]) if v else 0.0


def ma20(code):
    v = _load().get(str(code).zfill(6))
    return float(v[1]) if v else 0.0


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    _MAP = _build()
    try:
        _cp = _cache_path()
        _cp.parent.mkdir(parents=True, exist_ok=True)
        _cp.write_text(json.dumps(_MAP), encoding="utf-8")
    except Exception:
        pass
    print("daily_ma 종목수:", len(_MAP))
    for c in ["247540", "226950", "111710", "419050"]:
        print(f"  {c}: 5일선={ma5(c)} 20일선={ma20(c)}")

# -*- coding: utf-8 -*-
"""[시장 레짐 계산기 2026-06-29 친구님 "레짐 정확해야"] 합성 KOSDAQ지수(전종목 등가)로 BULL/NEUTRAL/BEAR 산출.
검증(`BACKTEST/market_regime_build_validate_v1`): 합성지수 vs MA20 + 기울기 = forward 정확(BULL 5일후+0.51%·BEAR -1.02%).
종목별 eod 'regime'컬럼은 부정확(시장레짐 아님)→이 모듈 사용. 하루1회 eod로 계산·캐시(DATA/market_regime_<date>.json).
정의: BULL=지수>MA20 & MA20기울기>0 & breadth>=BREADTH_OK / BEAR=지수<MA20 & MA20기울기<0 / else NEUTRAL.
fail-safe: 데이터없음/예외 = NEUTRAL(중립=중간노출, 거꾸로 위험 회피).
"""
import json, os
from pathlib import Path
from datetime import datetime

EOD = r"C:\stock_bot\data\eod_daily_bars.csv"
CACHE = Path(rf"C:\stock_bot\DATA\market_regime_{datetime.now():%Y%m%d}.json")
SLOPE_LB = int(os.environ.get("REGIME_SLOPE_LB", "5"))
BREADTH_OK = float(os.environ.get("REGIME_BREADTH_OK", "40"))   # BULL 확인용 시장폭% 하한
_CUR = None


def _build():
    import csv, collections
    series = collections.defaultdict(list)
    with open(EOD, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("market") != "KOSDAQ":
                continue
            try:
                series[row["code"].zfill(6)].append((row["date"], float(row["close"])))
            except (ValueError, KeyError):
                pass
    for c in series:
        series[c].sort()
    day_rets = collections.defaultdict(list)
    above = collections.defaultdict(lambda: [0, 0])
    for code, ser in series.items():
        cl = [x[1] for x in ser]; dt = [x[0] for x in ser]
        for i in range(1, len(cl)):
            if cl[i-1] > 0:
                day_rets[dt[i]].append(cl[i]/cl[i-1]-1)
            if i >= 20:
                ma20 = sum(cl[i-19:i+1])/20
                a = above[dt[i]]; a[1] += 1
                if cl[i] > ma20:
                    a[0] += 1
    dates = sorted(day_rets)
    vals = []; lvl = 100.0
    for d in dates:
        lvl *= (1 + sum(day_rets[d])/len(day_rets[d])); vals.append(lvl)
    if len(vals) < 60 + SLOPE_LB:
        return {"regime": "NEUTRAL", "reason": "데이터부족"}
    i = len(vals) - 1
    ma20 = sum(vals[i-19:i+1])/20
    ma20p = sum(vals[i-19-SLOPE_LB:i+1-SLOPE_LB])/20
    slope = (ma20/ma20p-1)*100 if ma20p else 0.0
    d = dates[i]; br = (above[d][0]/above[d][1]*100) if above[d][1] else 0.0
    if vals[i] > ma20 and slope > 0 and br >= BREADTH_OK:
        reg = "BULL"
    elif vals[i] < ma20 and slope < 0:
        reg = "BEAR"
    else:
        reg = "NEUTRAL"
    return {"regime": reg, "date": d, "idx": round(vals[i], 2), "ma20": round(ma20, 2),
            "slope": round(slope, 2), "breadth": round(br, 1)}


def _info():
    global _CUR
    if _CUR is not None:
        return _CUR
    try:
        _CUR = json.loads(CACHE.read_text(encoding="utf-8"))
        return _CUR
    except Exception:
        pass
    try:
        _CUR = _build()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_CUR, ensure_ascii=False), encoding="utf-8")
    except Exception:
        _CUR = {"regime": "NEUTRAL", "reason": "예외"}
    return _CUR


def current():
    """현재 시장 레짐 'BULL'/'NEUTRAL'/'BEAR'. fail-safe=NEUTRAL."""
    return _info().get("regime", "NEUTRAL")


def info():
    return _info()


def cap_mult():
    """[금액 스케일러 2026-06-29 친구님 "개수말고 금액으로"] 레짐별 건당 사이즈(CAP) 배수.
       REGIME_SIZE_SCALE=NO(기본)=1.0(기존동작). BULL 1.0(풀)·NEUTRAL 0.7·BEAR 0.5(작게·but 개수는 그대로=작게많이).
       검증: BULL 5일후+0.51%·NEUTRAL-0.25%·BEAR-1.02% → 나쁜장일수록 건당 작게. fail-safe=1.0."""
    if os.environ.get("REGIME_SIZE_SCALE", "NO").strip().upper() != "YES":
        return 1.0
    try:
        reg = current()
        if reg == "BULL":
            return float(os.environ.get("REGIME_CAP_BULL", "1.0"))
        if reg == "BEAR":
            return float(os.environ.get("REGIME_CAP_BEAR", "0.5"))
        return float(os.environ.get("REGIME_CAP_NEUTRAL", "0.7"))
    except Exception:
        return 1.0


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    # 강제 재계산
    _CUR = _build()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_CUR, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    print("시장 레짐:", json.dumps(_CUR, ensure_ascii=False))

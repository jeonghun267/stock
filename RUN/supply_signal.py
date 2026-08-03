# -*- coding: utf-8 -*-
"""[수급시차 헬퍼 2026-07-01] 친구님 0763 아이디어 → 직접백테 교정.
★발견(대장 top60·BEAR 20일): 기관 순매수 오늘D(−)·1일전(−)=역신호, 2일전(D-2)=익일+1.22%(승50%·최강), 3일전 약.
  → '갓 들어온 수급 추격 금지, 2~3일 묵힌 기관수급을 사라.' 5일누적/연속streak/외인은 버림(희석·역신호·노이즈).
공유 헬퍼(읽기전용·주문0·fail-open). 데이터=investor_daily.csv(opt10059·date,code,foreign_net,inst_net).
eod_gap(종가매수 선별)·그림자·내일 장중 부스터 공용. mtime 캐시.
"""
import csv
from pathlib import Path
from datetime import date

INV = Path(r"C:\stock_bot\data\investor_daily.csv")
_cache = {"mtime": None, "by_code": None, "dates": None}


def _load():
    """investor_daily.csv → ({code: {date: inst_net}}, sorted_dates). 실패시 (None,None)."""
    try:
        m = INV.stat().st_mtime
    except OSError:
        return None, None
    if _cache["mtime"] == m and _cache["by_code"] is not None:
        return _cache["by_code"], _cache["dates"]
    by_code, dates = {}, set()
    try:
        with open(INV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                c = str(row.get("code", "")).zfill(6)
                d = str(row.get("date", "")).strip()
                if not c or not d:
                    continue
                try:
                    inst = int(float(str(row.get("inst_net", "") or 0).replace(",", "")))
                except (ValueError, TypeError):
                    inst = None
                by_code.setdefault(c, {})[d] = inst
                dates.add(d)
    except Exception:
        return None, None
    dates = sorted(dates)
    _cache.update(mtime=m, by_code=by_code, dates=dates)
    return by_code, dates


def _target_date(dates, as_of, lag):
    """as_of(=오늘/매수일 D)에서 lag 거래일 전 날짜. 데이터에 as_of 없어도 가상삽입해 정합."""
    allsess = sorted(set(dates) | {str(as_of)})
    try:
        i = allsess.index(str(as_of))
    except ValueError:
        return None
    j = i - lag
    return allsess[j] if j >= 0 else None


def inst_lag_net(code, as_of=None, lag=2):
    """기관 순매수 D-lag(기본 2=2일전·백테 최강). 없으면 None. as_of=YYYYMMDD(미지정=오늘)."""
    by_code, dates = _load()
    if not by_code:
        return None
    if as_of is None:
        as_of = date.today().strftime("%Y%m%d")
    td = _target_date(dates, as_of, lag)
    if td is None:
        return None
    return (by_code.get(str(code).zfill(6)) or {}).get(td)


def aged_supply_map(codes, as_of=None, lag=2):
    """{code: 기관 D-lag 순매수}. 데이터 있는 종목만. fail-open(빈 dict)."""
    out = {}
    for c in codes:
        v = inst_lag_net(c, as_of, lag)
        if v is not None:
            out[str(c).zfill(6)] = v
    return out


if __name__ == "__main__":
    import sys
    as_of = sys.argv[1] if len(sys.argv) > 1 else None
    by_code, dates = _load()
    print("dates:", (dates[-5:] if dates else None), " codes:", (len(by_code) if by_code else 0))
    if as_of:
        td = _target_date(dates, as_of, 2)
        print(f"as_of={as_of} lag2 target_date(D-2)={td}")
        # 샘플: 그날 기관 순매수 상위 10
        m = {c: v.get(td) for c, v in by_code.items() if v.get(td) is not None}
        top = sorted(m.items(), key=lambda x: -x[1])[:10]
        for c, v in top:
            print(f"  {c}  기관D-2 {v:>12,}")

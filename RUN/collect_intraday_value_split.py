# -*- coding: utf-8 -*-
"""
[분봉 오전/오후 거래대금 + 종가강도 분리 저장  2026-06-14(일) 친구님] — 눌림 '오후 유지력' 적용용.
배경(친구님/GPT): 오후 눌림은 '거래대금 유지력(오전평균 대비 오후 시간당)' + '종가강도(고가대비 종가)'가 핵심.
  → 이걸 계산하려면 오전(09~12:59)/오후(13~) 거래대금을 따로 + 당일 고가·종가를 매일 쌓아야 함.
매일 장후(15:36) prices_1m → 종목별 am_value/pm_value/day_high/day_close → data/shadow/intraday_value_split.csv 누적.
며칠 쌓이면 오후 유지율(pm/am)·종가강도(close/high) 실측 가능. READ-ONLY 수집·-X utf8·매매무연결.
"""
import csv, io, sys
from pathlib import Path

P1M = Path(r"C:\stock_bot\DATA\prices_1m.csv")
OUT = Path(r"C:\stock_bot\data\shadow\intraday_value_split.csv")

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def main():
    if not P1M.exists():
        print("[VAL-SPLIT] prices_1m.csv 없음 → skip"); return 0
    # 종목별: am_value, pm_value, day_high, last_ts, last_close
    agg = {}; day = None
    with io.open(P1M, encoding="utf-8-sig", errors="replace") as f:
        rd = csv.reader(f); next(rd, None)
        for c in rd:
            if not c or len(c) < 8 or c[0] in ("U001", "U201"):
                continue
            code = c[0]; ts = c[1]; day = ts[:8]; hm = ts[8:12]
            try:
                high = float(c[3] or 0); close = float(c[5] or 0); val = float(c[7] or 0)
            except (ValueError, IndexError):
                continue
            a = agg.get(code)
            if a is None:
                a = {"am": 0.0, "pm": 0.0, "high": 0.0, "last_ts": "", "close": 0.0}
                agg[code] = a
            if "0900" <= hm < "1300":
                a["am"] += val
            elif hm >= "1300":
                a["pm"] += val
            if high > a["high"]:
                a["high"] = high
            if ts > a["last_ts"]:
                a["last_ts"] = ts; a["close"] = close
    if not day or not agg:
        print("[VAL-SPLIT] 데이터 없음 → skip"); return 0

    existing = set()
    if OUT.exists():
        with io.open(OUT, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if r and len(r) >= 2:
                    existing.add((r[0], r[1]))
    new = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT.exists() or OUT.stat().st_size < 5
    with io.open(OUT, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["date", "code", "am_value", "pm_value", "day_high", "day_close", "close_str"])
        for code, a in agg.items():
            if (day, code) in existing:
                continue
            close_str = round(a["close"] / a["high"], 4) if a["high"] > 0 else 0.0   # 종가강도(고가대비)
            w.writerow([day, code, round(a["am"]), round(a["pm"]), round(a["high"]), round(a["close"]), close_str])
            new += 1
    print(f"[VAL-SPLIT] {day}: {new}종목 오전/오후 거래대금+종가강도 저장")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"[FATAL] {ex}"); import traceback; traceback.print_exc(); sys.exit(1)

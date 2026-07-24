# -*- coding: utf-8 -*-
"""[전략용 감시 유니버스 2026-07-01 친구님] EOD 거래대금 상위 100(우리 데이터) → micro_watch_strategy.json.
목적: 키움 라이브 movers(들락날락)에 의존 말고, 전일 EOD 스코어로 우리가 고른 100종목을 9시부터 '연속' 감시.
그럼 043260처럼 급락하는 바닥 시간에도 체결강도가 계속 찍힘(라이브 movers는 오른 뒤에야 들어옴).
broker는 IPC/micro_watch_*.json 을 glob 자동구독(체결강도 FID228). 잡주 배제: 가격≥3000.
장전 08:50 실행. 주문 0.
"""
import os, csv, json
from collections import deque
from datetime import datetime
from pathlib import Path

EOD = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
OUT = Path(r"C:\stock_bot\IPC\micro_watch_strategy.json")
LOG = Path(r"C:\stock_bot\data\LOG\strategy_watchlist.log")
TOPN      = int(os.environ.get("STRAT_WATCH_TOPN", "100"))
MIN_PRICE = float(os.environ.get("STRAT_WATCH_MIN_PRICE", "3000"))
KOSDAQ_ONLY = os.environ.get("STRAT_WATCH_KOSDAQ_ONLY", "YES").strip().upper() == "YES"  # ★기본 코스닥(전략 유니버스·KOSPI대형주/ETF 배제)


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def main():
    # 최신 일자 = 마지막 데이터행의 date
    with open(EOD, encoding="utf-8-sig") as f:
        header = f.readline().rstrip("\n").split(",")
        last = deque(f, maxlen=1)
    di = header.index("date"); ci = header.index("code"); mi = header.index("market")
    pi = header.index("close"); vi = header.index("value")
    maxd = last[0].split(",")[di] if last else ""
    if not maxd:
        _log("[ERR] eod_daily_bars 비어있음"); return

    rows = []
    with open(EOD, encoding="utf-8-sig") as f:
        r = csv.reader(f); next(r)
        for x in r:
            if len(x) <= vi or x[di] != maxd:
                continue
            mkt = str(x[mi]).upper()
            if KOSDAQ_ONLY and "KOSDAQ" not in mkt:
                continue
            try:
                close = float(x[pi] or 0); val = float(x[vi] or 0)
            except ValueError:
                continue
            if close < MIN_PRICE or val <= 0:
                continue
            rows.append((val, str(x[ci]).zfill(6)))
    rows.sort(reverse=True)               # 거래대금 내림차순
    codes = [c for _, c in rows[:TOPN]]
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"codes": codes, "ts": datetime.now().isoformat(), "src": "strategy"},
                                  ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log(f"[ERR] write {e}"); return
    _log(f"전략 감시 유니버스 {len(codes)}종목 (기준일 {maxd}·거래대금상위·가격≥{MIN_PRICE:.0f}) → {OUT.name}")
    _log("상위10: " + " ".join(codes[:10]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"[FATAL] {e}"); raise

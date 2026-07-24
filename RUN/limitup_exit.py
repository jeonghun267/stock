# -*- coding: utf-8 -*-
"""[공통 상한가 매도유예 2026-07-04 친구님 "전 전략 공통"] 보유가 상한가 도달시 당일 안 팔고 익일 시가매도(갭업 노림).
순수 함수·부작용 없음. 각 엔진 EOD 매도부에서 호출:
  ① EOD 직전: if now>=EOD and limitup_exit.is_limitup(code,cur): → EOD매도 skip(홀드·오버나잇 플래그)
  ② 익일 장초: if limitup_exit.should_open_sell(p, today, hm): → 시가 매도(상한가 익일청산)
env: LIMITUP_NEXTOPEN=YES(기본·끄기 NO) · LIMITUP_NEAR=1.295(전일종가×이배수↑=상한가권·KOSDAQ/KOSPI +30%).
데이터: eod_daily_bars.csv 최신일 close = 전일종가(장중엔 latest=전거래일이라 맞음)."""
import os, csv
from pathlib import Path

ON   = os.environ.get("LIMITUP_NEXTOPEN", "YES").strip().upper() == "YES"
NEAR = float(os.environ.get("LIMITUP_NEAR", "1.295"))
OPEN_END = os.environ.get("LIMITUP_OPEN_END", "0906")   # 익일 시가매도 창 끝
EOD_CSV = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
_PC = {"d": None}


def _prevclose(code):
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
        except Exception:
            pass
        _PC["d"] = m
    return _PC["d"].get(str(code).zfill(6), 0.0)


def is_limitup(code, cur):
    """상한가권(전일종가×NEAR↑)이면 True. env OFF면 항상 False."""
    if not ON or cur <= 0:
        return False
    pc = _prevclose(code)
    return pc > 0 and cur >= pc * NEAR


def should_open_sell(pos, today, hm):
    """오버나잇 보유(상한가 홀드)이고, 오늘이 매수일 다음날이고, 익일 시가창이면 True."""
    if not ON:
        return False
    return bool(pos.get("limitup_hold")) and pos.get("date") != today and "0900" <= str(hm) <= OPEN_END

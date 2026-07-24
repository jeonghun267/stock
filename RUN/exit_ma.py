# -*- coding: utf-8 -*-
"""[MA 타임프레임 스위치 2026-06-30 친구님 "모든 캔들·이동평균선 3분봉 기준·일봉 쓰면 시간 안맞음"]
   MA_TIMEFRAME=3MIN(기본)이면 당일 3분봉 MA, DAILY면 일봉 MA(롤백).
   daily_ma / intraday_ma 와 동일 인터페이스(ma5/ma20/ma40/ma60) → 실행기는 import만 이걸로 바꾸면 끝.
   ★봉/데이터 부족이면 0.0 반환(che_exit·게이트가 0이면 MA레이어 skip = fail-safe)."""
import os


def _mod():
    if os.environ.get("MA_TIMEFRAME", "3MIN").strip().upper() == "3MIN":
        import intraday_ma as m
    else:
        import daily_ma as m
    return m


def ma5(code):
    try: return float(_mod().ma5(code) or 0.0)
    except Exception: return 0.0


def ma20(code):
    try: return float(_mod().ma20(code) or 0.0)
    except Exception: return 0.0


def ma40(code):
    try:
        m = _mod()
        return float((m.ma40(code) if hasattr(m, "ma40") else 0.0) or 0.0)
    except Exception: return 0.0


def ma60(code):
    try:
        m = _mod()
        return float((m.ma60(code) if hasattr(m, "ma60") else 0.0) or 0.0)
    except Exception: return 0.0

# -*- coding: utf-8 -*-
"""
theme_leader.py — 테마 주도주 공용 헬퍼 [2026-07-12 친구님 "선별기에 넣어서 전략들이 공동으로 사용"]

데이터 원천: theme_leader_shadow_v1.py(record·3분 태스크)가 쓰는 data\테마주도주.json
신호 정의(7/11 밤 3분봉 백테 근거·[[stockbot-20260711-theme-leader-shadow]]):
  쌍끌이  = 달리는 테마(멤버 3+·평균등락 +3%↑)에서 등락률 1등 + 누적대금 1등
  대금2등 = 등락률 1등 + 누적대금 2등 (백테 최강: 10시 진입도 +30분 +3.19%/82%)

사용 예 (읽기전용·fail-open):
  import theme_leader as TL
  leaders = TL.get_leaders()              # {code: {"signal","theme","name","time","chg",...}}
  leaders = TL.get_leaders(max_age_min=30)  # 파일이 30분보다 오래되면 빈 dict
  if code in leaders: ...                 # 이 종목이 오늘 주도주 신호를 받았나

원칙: 본 모듈은 조회만(주문·차단 없음). 각 전략의 관문 반영은 전략별로 친구님 승인 후.
"""
import json
import time
from pathlib import Path
from datetime import datetime

_PUB = Path(r"C:\stock_bot\data\테마주도주.json")
_CACHE = {"ts": 0.0, "m": {}}


def get_leaders(max_age_min=None, signal=None):
    """당일 테마 주도주 dict {code: info}. 15초 메모리캐시.
    max_age_min: 파일 갱신이 이보다 오래됐으면 빈 dict(장중 신선도 보장용·None=무제한).
    signal: '쌍끌이' 또는 '대금2등'만 골라 받기(None=전부)."""
    now = time.time()
    if now - _CACHE["ts"] > 15:
        m = {}
        try:
            d = json.loads(_PUB.read_text(encoding="utf-8"))
            if d.get("date") == datetime.now().strftime("%Y%m%d"):
                for s in d.get("signals") or []:
                    code = str(s.get("code", "")).zfill(6)
                    if len(code) == 6:
                        m[code] = s
                m["_file_ts"] = d.get("ts", "")
        except Exception:
            m = {}
        _CACHE["ts"] = now
        _CACHE["m"] = m
    m = dict(_CACHE["m"])
    file_ts = m.pop("_file_ts", "")
    if max_age_min is not None and file_ts:
        try:
            age = (datetime.now() - datetime.strptime(file_ts, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0
            if age > max_age_min:
                return {}
        except Exception:
            pass
    if signal:
        m = {c: s for c, s in m.items() if s.get("signal") == signal}
    return m


if __name__ == "__main__":
    L = get_leaders()
    print("오늘 주도주 %d종목" % len(L))
    for c, s in L.items():
        print(" ", c, s.get("name"), s.get("signal"), s.get("theme"), s.get("time"))

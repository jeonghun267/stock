# -*- coding: utf-8 -*-
"""
[US-CRASH-GUARD 2026-06-14 ★친구님 설계] 나스닥 -4%↓ 극단폭락날 = 그날 전 전략(스윙·눌림·종가매수) 신규매수 스킵.
근거 백테(BACKTEST/swing_us_guard_threshold_v1, 1년): 미국 야간 하락 다음날 코스닥 대장주는
  -1.5~-3.5% 폭락엔 시초가 갭하락 후 종가까지 +2~3% '반등'(=싸게사는 기회, 친구님 통찰) →막지않음.
  단 나스닥 -4%↓(진짜 대폭락, 1년 1번)만 대장주도 종가까지 -1.85% '추가하락' →그날만 신규 스킵.
판정: us_overnight.json(나스닥 등락, fetch_us_overnight가 매일 08:00/14:00 수집)의 당일 신선 데이터.
  ★stale(낡음)/없음/오류 → False(안막음=평소대로 매수, fail-safe). env로만 켜짐(기본 OFF).
사용: from us_crash_guard import is_us_crash_day; blk,why=is_us_crash_day()
  - 보유분 탈출엔 안 씀(대장주 반등 때문) — 오직 '신규 진입 스킵'용.
"""
import json, os
from datetime import datetime
from pathlib import Path

_US = Path(r"C:\stock_bot\DATA\us_overnight.json")


def is_us_crash_day():
    """returns (block: bool, reason: str). env US_CRASH_BLOCK_ENABLE=YES 라야 작동."""
    if os.environ.get("US_CRASH_BLOCK_ENABLE", "NO").strip().upper() != "YES":
        return False, "OFF(env)"
    try:
        thr = float(os.environ.get("US_CRASH_NASDAQ_PCT", "-4.0"))
    except ValueError:
        thr = -4.0
    try:
        d = json.loads(_US.read_text(encoding="utf-8-sig"))
        ts = str(d.get("ts", ""))
        # 신선도: 당일(미국 야간→당일 아침 fetch) 데이터만 신뢰. 낡으면 판단보류=평소(안전).
        if ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return False, f"stale({ts[:10]})→평소진행"
        nq = d.get("data", {}).get("nasdaq", {}).get("chg")
        if nq is None:
            return False, "나스닥값없음→평소진행"
        if float(nq) <= thr:
            return True, f"나스닥 {float(nq):.2f}%≤{thr}% 대폭락 → 신규매수 스킵"
        return False, f"나스닥 {float(nq):.2f}%(평소)"
    except Exception as e:
        return False, f"읽기실패({e})→평소진행"


if __name__ == "__main__":
    # 자가 점검
    b, w = is_us_crash_day()
    print(f"[US-CRASH-GUARD] block={b} reason={w}")

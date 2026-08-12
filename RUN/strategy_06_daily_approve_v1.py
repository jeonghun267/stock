# -*- coding: utf-8 -*-
"""S06 승인 깃발의 날짜만 오늘로 갱신한다 — 친구님의 상시 결정이 이미 있을 때만.

★[S06-DAILY-APPROVE 2026-08-04] 왜 필요해졌나
  주문 관문이 '깃발 존재'에서 '내용·날짜가 오늘인지'로 바뀌었는데(approval_settings_guard.
  legacy_daily_approval_valid), S06 만 일일 갱신 경로가 없다.
    S01~S03  strategy_all_auto_live_preflight_v1  08:59:35  (점검 통과 시 자동)
    S04      strategy_04_preflight_v1 --approve   09:57     (점검 통과 시 자동)
    S05      strategy_05_preflight_v1 --approve   09:25     (점검 통과 시 자동)
    S06      없음  <-- 이것 때문에 8/5 부터 하루 종일 그림자로 돌 뻔했다.

  S06 깃발은 8/3 친구님이 실전 결정하며 만든 뒤 영구였다(일일 리셋 대상도 아니다).
  그래서 '깃발의 존재 = 상시 결정'으로 보고 날짜만 오늘로 민다.
  run_strategy_06_crash_low_chase.cmd 에 문서화된 정지 스위치 두 개를 그대로 지킨다:
    - config\\strategy_06_off.flag 생성  -> 매수만 정지 (여기서도 갱신 안 함)
    - 승인 깃발 삭제                     -> 전면 그림자 (여기서 절대 새로 만들지 않음)

  깃발을 새로 만들지 않는 것이 이 파일의 핵심 제약이다. 없는 승인을 만들어내면
  그건 갱신이 아니라 무단 승인이다.
  되돌리기: backup\\run_strategy_06_crash_low_chase_20260804_before_daily_approve.cmd
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


ROOT = Path(r"C:\stock_bot")
APPROVAL_PATH = ROOT / "config" / "strategy_06_live_approved.flag"
OFF_PATH = ROOT / "config" / "strategy_06_off.flag"
HOLIDAYS_PATH = ROOT / "config" / "holidays_kr.txt"

# 주문 관문이 인정하는 S06 형식(approval_settings_guard 의 dated 규칙)과 같아야 한다.
STANDING_RE = re.compile(r"APPROVED_BY_OWNER\s+(\d{8})\s+S06_LIVE")


def _is_holiday(today: str, holidays_path: Path = HOLIDAYS_PATH) -> bool:
    try:
        text = holidays_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip().replace("-", "")
        if entry == today:
            return True
    return False


def renew(
    *,
    now: Optional[datetime] = None,
    approval_path: Path = APPROVAL_PATH,
    off_path: Path = OFF_PATH,
    holidays_path: Path = HOLIDAYS_PATH,
) -> Tuple[bool, str]:
    """(갱신했나, 사유). 어떤 실패에서도 깃발을 만들거나 훼손하지 않는다."""
    today = (now or datetime.now()).strftime("%Y%m%d")

    if Path(off_path).exists():
        return False, "OFF_FLAG"                # 문서화된 정지 스위치 1
    if _is_holiday(today, Path(holidays_path)):
        return False, "HOLIDAY"

    try:
        current = Path(approval_path).read_text(
            encoding="ascii", errors="strict").strip()
    except OSError:
        return False, "NO_STANDING_APPROVAL"    # 문서화된 정지 스위치 2
    except UnicodeError:
        return False, "UNREADABLE_APPROVAL"

    matched = STANDING_RE.fullmatch(current)
    if not matched:
        # 형식이 다르면 상시 결정인지 확신할 수 없다 - 건드리지 않는다.
        return False, "MALFORMED_APPROVAL"
    stamped = matched.group(1)
    if stamped > today:
        return False, "FUTURE_APPROVAL"         # 시계 이상 - 손대지 않는다
    if stamped == today:
        return False, "ALREADY_TODAY"

    target = Path(approval_path)
    temporary = target.with_suffix(".flag.tmp")
    temporary.write_text(
        f"APPROVED_BY_OWNER {today} S06_LIVE\n", encoding="ascii")
    os.replace(temporary, target)
    return True, "RENEWED"


def main() -> int:
    try:
        renewed, reason = renew()
    except Exception as exc:                    # 갱신 실패가 엔진 기동을 막으면 안 된다
        print(f"[S06-DAILY-APPROVE] error={type(exc).__name__}: {exc}", flush=True)
        return 0
    print(f"[S06-DAILY-APPROVE] renewed={renewed} reason={reason}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

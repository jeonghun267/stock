# -*- coding: utf-8 -*-
"""돈맥 1초 캡처(mf_1s_capture) 보관 정리기 v1.

★[2026-08-26 친구님 위임 "너가 판단해서"] 보관 정책 = 최신 15거래일(파일 15개).
근거: (1) 하루 4.5~6.9GB 씩 무한 누적돼 8/26 실측 123.8GB, 방치 시 약 22거래일
  뒤 디스크 고갈 예측(3차 점검). (2) day_judge_v1 의 하락일 문턱이 "12일 재생"
  으로 캘리브레이션된 선례가 있어 10일 보관은 연구를 막는다 → 15일로 여유.
  (3) 읽는 쪽 8곳 중 상시 소비는 당일 파일뿐(day_judge=당일, timeband_shadow=
  기본 당일·인자로 과거 지정)임을 8/26 실측.

동작: 기본은 모의실행(지울 목록·용량만 출력). --apply 를 붙여야 실제 삭제.
  파일명 mf_1s_YYYYMMDD.csv 만 대상으로 하고, 날짜 내림차순 상위
  KEEP(기본 15, env MF1S_KEEP_FILES)개는 무조건 보존한다.
  삭제는 영구다(휴지통 아님) — 원자료 특성상 복구 불가.
주문 0 · 브로커 0 · 캡처 폴더 밖은 절대 건드리지 않는다.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CAP_DIR = Path(r"C:\stock_bot\data\shadow\mf_1s_capture")
KEEP = int(os.environ.get("MF1S_KEEP_FILES", "15"))
NAME_RE = re.compile(r"^mf_1s_(\d{8})\.csv$")


def main() -> int:
    apply = "--apply" in sys.argv
    rows = []
    for p in CAP_DIR.iterdir():
        m = NAME_RE.match(p.name)
        if m and p.is_file():
            rows.append((m.group(1), p))
    rows.sort(reverse=True)               # 날짜 내림차순
    keep, drop = rows[:KEEP], rows[KEEP:]
    total = sum(p.stat().st_size for _, p in drop)
    print("보존 %d개 (최신 %s~%s) / 삭제 대상 %d개 %.1fGB"
          % (len(keep),
             keep[-1][0] if keep else "-", keep[0][0] if keep else "-",
             len(drop), total / 1e9))
    freed = 0
    for day, p in drop:
        size = p.stat().st_size
        if apply:
            try:
                p.unlink()
                freed += size
                print("  삭제 %s  %.2fGB" % (p.name, size / 1e9))
            except OSError as exc:
                print("  실패 %s  %s" % (p.name, exc))
        else:
            print("  (모의) %s  %.2fGB" % (p.name, size / 1e9))
    if apply:
        print("회수 %.1fGB 완료" % (freed / 1e9))
    else:
        print("모의실행 — 실제 삭제는 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

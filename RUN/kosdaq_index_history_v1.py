# -*- coding: utf-8 -*-
"""코스닥 지수 이력 축적기 (읽기 전용 + 이력 CSV append 만).

★[KOSDAQ-HISTORY 2026-08-19 친구님 승인] 현재 data\kosdaq_index.json 은 5분마다
덮어쓰기만 하고 이력이 0 이다 — 레짐스탑(-3%) 판정의 근거가 사후에 재구성 불가.
이 스크립트는 그 파일을 읽어 보고서\코스닥지수_이력.csv 에 한 줄 덧붙인다.
지수 파일이 없거나 낡았으면 조용히 넘어간다(생산 경로 무간섭).
같은 지수 시각(ts)이 이미 기록돼 있으면 중복 기록하지 않는다.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
SRC = BASE / "data" / "kosdaq_index.json"
OUT = BASE / "보고서" / "코스닥지수_이력.csv"
HEADER = ["기록시각", "지수시각", "지수", "등락률"]


def main() -> int:
    try:
        data = json.loads(SRC.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return 0
    try:
        price = float(data.get("price"))
        chg = float(data.get("chg"))
    except (TypeError, ValueError):
        return 0
    src_ts = str(data.get("ts") or "")
    now = datetime.now()

    last_src = ""
    try:
        with OUT.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2:
                    last_src = row[1]
    except OSError:
        pass
    if src_ts and src_ts == last_src:
        return 0  # 지수 파일이 아직 안 바뀜 — 중복 기록 안 함

    is_new = not OUT.exists()
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(HEADER)
            writer.writerow(
                [now.isoformat(timespec="seconds"), src_ts, price, chg])
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

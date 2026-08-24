# -*- coding: utf-8 -*-
"""종목명 캐시 보충기 — 로컬 자료만으로, 추가 전용.

★[NAME-CACHE 2026-08-19 친구님 승인 "8번 진행해"] data\\_code_name_cache.json 의
date=20260619 (원 작성자는 은퇴한 캡틴 계열로 추정 — 두 달째 고아).
8/19 실측: 고저폭판 1위 153890 이름 nan, 돈맥 매수 417840·319660 캐시에 없음.

원칙:
  - TR 0건. 로컬 파일(돈흐름_선별판 rows · 고저폭판 CSV)에서만 이름을 줍는다.
  - 추가 전용: 캐시에 없거나 'nan'/빈 값인 종목만 채운다. 기존 이름 불변.
  - date 필드 보존(소비자 8곳의 의존 여부 미확인 — 바꾸지 않는 쪽이 현상 유지).
    보충 시각은 refreshed_at 에만 기록.
  - 편집 전 백업. 원자 교체(tmp → replace).
전체 갱신(전 종목)은 브로커 GetMasterCodeName 경로가 필요 — 별도 안건.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                              # noqa: BLE001
    pass

BASE = Path(r"C:\stock_bot")
CACHE = BASE / "data" / "_code_name_cache.json"


def gather_names() -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        board = json.loads(
            (BASE / "data" / "돈흐름_선별판.json").read_text(encoding="utf-8-sig"))
        for row in board.get("rows") or []:
            code = str(row.get("code") or "").zfill(6)
            name = str(row.get("name") or "").strip()
            if (len(code) == 6 and name and name.lower() != "nan"
                    and not name.isdigit()):  # 소스가 이름 없는 종목에 코드를 넣어둠
                names.setdefault(code, name)
    except (OSError, ValueError):
        pass
    try:
        with (BASE / "data" / "common_high_range_top30.csv").open(
                encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) > 5 and row[5].strip().isdigit():
                    code = row[5].strip().zfill(6)
                    name = row[4].strip()
                    if len(code) == 6 and name and name.lower() != "nan":
                        names.setdefault(code, name)
    except OSError:
        pass
    return names


def main() -> int:
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"[name-cache] 캐시 읽기 실패: {exc}")
        return 1
    table = cache.get("map")
    if not isinstance(table, dict):
        print("[name-cache] map 형식 이상 — 중단")
        return 1

    found = gather_names()
    added = []
    for code, name in found.items():
        current = str(table.get(code) or "").strip()
        if not current or current.lower() == "nan":
            table[code] = name
            added.append(f"{code}={name}")
    if not added:
        print(f"[name-cache] 보충할 이름 없음 (소스 {len(found)}건 전부 이미 있음)")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(CACHE, CACHE.with_name(f"_code_name_cache_{stamp}_before_refresh.json"))
    cache["map"] = table
    cache["refreshed_at"] = datetime.now().isoformat(timespec="seconds")
    temporary = CACHE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, CACHE)
    print(f"[name-cache] {len(added)}건 보충: " + ", ".join(added[:10])
          + (" ..." if len(added) > 10 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

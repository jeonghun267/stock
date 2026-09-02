# -*- coding: utf-8 -*-
"""이미 아는 테스트 실패를 기준선으로 못 박고, **새로 생긴 실패만** 알린다.

왜: 2026-08-27 기준 tests 는 20건이 실패 중이다(브로커 인증 정책·전략 판정 변경 등
    오래 누적된 것). 실패가 많으면 진짜 회귀 1건이 그 속에 묻힌다 — 실제로 이날
    명부 재봉인을 빠뜨려 생긴 HASH_MISMATCH 1건이 총계 28 그대로에 가려져 있었다.
    기존 20건은 "어느 쪽이 옳은가"가 전략·보안 판단이라 함부로 고치면 가짜 통과가 된다.
    그래서 고치지 않고 **목록으로 고정**하고, 목록에 없는 실패만 빨갛게 띄운다.

쓰기:
    C:\python310\python.exe C:\stock_bot\RUN\pytest_baseline_check_v1.py
        -> 기준선과 대조. 새 실패가 있으면 종료코드 1.
    ... pytest_baseline_check_v1.py --rebaseline
        -> 지금 실패 목록을 기준선으로 굳힌다. **일부러 바뀐 뒤에만 쓸 것.**
           (먼저 굳히고 나중에 확인하면 검사가 무의미해진다 — elevated 기준표와 같은 원칙)

주의: 실전 코드·설정을 건드리지 않는다. 읽기 전용이다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
PYTHON = r"C:\python310\python.exe"
BASELINE = ROOT / "config" / "pytest_failure_baseline_v1.json"
FAILED_RE = re.compile(r"^FAILED\s+(\S+)")


def collect_failures(target: str = "tests") -> tuple[set[str], str]:
    """pytest 를 돌려 실패한 테스트 ID 집합을 얻는다."""
    result = subprocess.run(
        [PYTHON, "-m", "pytest", target, "-q", "--tb=no"],
        cwd=str(ROOT), capture_output=True, text=True, errors="replace",
    )
    output = (result.stdout or "") + (result.stderr or "")
    failures = {
        match.group(1)
        for line in output.splitlines()
        if (match := FAILED_RE.match(line.strip()))
    }
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    return failures, tail


def load_baseline(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_baseline(path: Path, failures: set[str], tail: str) -> None:
    path.write_text(json.dumps({
        "_설명": "이미 아는 테스트 실패 목록. 여기 없는 실패만 새 회귀로 본다.",
        "_왜": ("실패가 많으면 진짜 회귀 1건이 묻힌다. 기존 실패는 전략·보안 판단이 "
                "필요해 함부로 못 고치므로, 고치는 대신 목록으로 고정한다."),
        "_다시만들기": (r"C:\python310\python.exe "
                        r"C:\stock_bot\RUN\pytest_baseline_check_v1.py --rebaseline"),
        "_주의": "일부러 바뀐 뒤에만 다시 만들 것. 먼저 만들고 나중에 확인하면 검사가 무의미해진다.",
        "생성": datetime.now().isoformat(timespec="seconds"),
        "요약": tail,
        "건수": len(failures),
        "실패": sorted(failures),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    try:                                   # 콘솔이 cp949 여도 죽지 않게
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebaseline", action="store_true",
                        help="지금 실패 목록을 기준선으로 굳힌다(일부러 바꾼 뒤에만)")
    parser.add_argument("--baseline", default=str(BASELINE),
                        help="기준선 파일 경로(검증용으로만 바꾼다)")
    parser.add_argument("--target", default="tests", help="검사할 테스트 경로")
    args = parser.parse_args()
    path = Path(args.baseline)

    failures, tail = collect_failures(args.target)

    if args.rebaseline:
        save_baseline(path, failures, tail)
        print(f"기준선 갱신: {len(failures)}건  ({tail})")
        return 0

    known = set(load_baseline(path).get("실패") or [])
    if not known:
        print("기준선이 없다. 먼저 --rebaseline 으로 굳힐 것.")
        return 2

    fresh = sorted(failures - known)
    fixed = sorted(known - failures)

    print(f"현재 {len(failures)}건 / 기준선 {len(known)}건  ({tail})")
    if fixed:
        print(f"[FIXED] 고쳐진 것 {len(fixed)}건 - 확인 후 --rebaseline 으로 줄일 것:")
        for name in fixed:
            print(f"    {name}")
    if fresh:
        print(f"[NEW] *** 새로 생긴 실패 {len(fresh)}건 ***")
        for name in fresh:
            print(f"    {name}")
        return 1
    print("새로 생긴 실패 없음.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

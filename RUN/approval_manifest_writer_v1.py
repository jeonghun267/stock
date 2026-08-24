# -*- coding: utf-8 -*-
"""승인 해시 명부(config/live_approved_hashes_v1.json)의 유일한 안전 편집 진입점.

★[2026-08-12 친구님 지시 "1번부터 고쳐"] 오늘 두 세션(Claude·GPT)이 명부를
  각자 비원자적으로 덮어써 lost update 가 났다(관문이 FALSE-FAIL, 반대로 미검토
  변경의 FALSE-PASS 도 가능). 이 모듈은 두 겹으로 그것을 막는다:

    1) 상호배제 — msvcrt 파일락으로 편집을 직렬화한다(락 잡은 프로세스가 죽으면
       OS 가 자동 해제하므로 stale 락이 안 생긴다).
    2) 낙관적 동시성(CAS) — 편집자는 '내가 읽은 시점의 manifest_sha' 를 함께 낸다.
       그 사이 다른 편집자가 내용을 바꿔 sha 가 달라졌으면 ManifestConflict 로 거부한다.
       (락만으로는 '읽고→오래 있다가→쓰는' 사이의 덮어쓰기를 못 막는다.)

  manifest_sha 는 승인 '내용'(approved_at·approval_scope·common·strategies)의 지문이다.
  기술적 메타(last_written_at·updated_by·manifest_sha 자신)는 지문 계산에서 뺀다 —
  그래야 같은 승인 내용이면 누가 언제 저장하든 지문이 같다.

  ⚠️관문 검사기(live_owner_approval_guard_v1.py)는 이 모듈에 의존하지 않는다.
    관문은 종전대로 파일 해시만 본다 — 실전 기동 경로에 리스크를 더하지 않기 위해서다.
    이 모듈은 '편집하는 쪽'만 안전하게 만든다.
"""
from __future__ import annotations

import hashlib
import json
import msvcrt
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(r"C:\stock_bot")
MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"
_META_KEYS = ("manifest_sha", "last_written_at", "updated_by")


class ManifestConflict(RuntimeError):
    """읽은 이후 명부 내용이 바뀌어 CAS 가 실패했다(lost update 방지)."""


class ManifestLockTimeout(RuntimeError):
    """제한 시간 안에 편집 락을 못 잡았다(다른 편집이 진행 중일 수 있다)."""


def content_sha(data: Mapping[str, Any]) -> str:
    """승인 내용의 지문. 기술적 메타 필드는 제외한 뒤 정규화 JSON 으로 해시한다."""
    body = {k: v for k, v in data.items() if k not in _META_KEYS}
    canonical = json.dumps(
        body, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def read_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_content_sha(path: Path = MANIFEST) -> str:
    """편집 전에 불러 CAS 기준선으로 쓴다."""
    return content_sha(read_manifest(path))


def verify_manifest_sha(path: Path = MANIFEST) -> tuple[bool, str, str]:
    """(일치여부, 저장된값, 재계산값). manifest_sha 가 없으면 저장값은 '' 이다."""
    data = read_manifest(path)
    stored = str(data.get("manifest_sha") or "")
    computed = content_sha(data)
    return (stored == computed and bool(stored)), stored, computed


def live_feature_enabled(name: str, path: Path = MANIFEST) -> bool:
    """해시/지문으로 보호되는 실전 기능 승인을 fail-closed 로 읽는다.

    ★[2026-08-12 보안수리 2번] 종전 실전 스위치는 env var 단독이라, 머신 스코프
      env 로 해시 커버리지를 우회해 켤 수 있었다. 이 함수는 활성화의 두 번째 요소다:
      명부 지문이 정합할 때에만(=writer 로만 정당하게 바뀐 상태) live_features[name]==True
      를 인정한다. 파일이 없거나·지문이 깨졌거나·필드가 없으면 전부 False(fail-closed).
      명부를 직접 변조해 필드만 True 로 바꿔도 지문 불일치로 걸린다.
    """
    try:
        data = read_manifest(path)
    except (OSError, ValueError):
        return False
    stored = str(data.get("manifest_sha") or "")
    if not stored or stored != content_sha(data):
        return False
    features = data.get("live_features")
    return bool(isinstance(features, Mapping) and features.get(name) is True)


def _atomic_replace(temporary: Path, path: Path) -> None:
    """os.replace 를 WinError 5 대비 재시도로 감싼다(이 프로젝트 표준 패턴)."""
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.2)


def _acquire_lock(lock_path: Path, timeout: float):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")
    deadline = time.time() + timeout
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return handle
        except OSError:
            if time.time() >= deadline:
                handle.close()
                raise ManifestLockTimeout(str(lock_path))
            time.sleep(0.1)


def _release_lock(handle) -> None:
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def update_manifest(
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    updated_by: str,
    expect_sha: str | None,
    path: Path = MANIFEST,
    backup: bool = True,
    lock_timeout: float = 15.0,
    allow_no_cas: bool = False,
) -> str:
    """명부를 안전하게 편집한다. mutate 는 명부 dict 를 받아 수정본 dict 를 돌려준다.

    ★[2026-08-12 P1-b] expect_sha 는 필수다. 편집 전 read_content_sha() 로 읽은 값을
      넘기면, 그 사이 내용이 바뀌었을 때 ManifestConflict 로 거부한다(lost update 방지).
      CAS 를 정말 생략해야 하는 경우(예: 손상 복구)에만 allow_no_cas=True 로 명시한다 —
      기본 경로에서 실수로 CAS 없이 덮어쓰는 일을 막기 위해서다.
    반환값은 새 manifest_sha. 락→읽기→CAS→변형→지문재계산→원자교체 를 한 번에 한다.
    """
    path = Path(path)
    lock = _acquire_lock(path.with_suffix(path.suffix + ".lock"), lock_timeout)
    try:
        data = read_manifest(path)
        current = content_sha(data)
        if expect_sha is None:
            if not allow_no_cas:
                raise ManifestConflict(
                    "CAS_REQUIRED: expect_sha 를 넘기거나 allow_no_cas=True 로 명시하라")
        elif current != expect_sha:
            raise ManifestConflict(f"expected={expect_sha[:12]} actual={current[:12]}")

        new_data = mutate(json.loads(json.dumps(data)))  # 깊은 복사본을 넘긴다
        if not isinstance(new_data, dict):
            raise TypeError("mutate 는 dict 를 돌려줘야 한다")

        new_data["manifest_sha"] = content_sha(new_data)
        new_data["last_written_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds")
        new_data["updated_by"] = str(updated_by or "unknown")

        if backup:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(path, path.with_name(
                f"{path.stem}_{stamp}_before_write{path.suffix}"))

        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(new_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _atomic_replace(temporary, path)
        return new_data["manifest_sha"]
    finally:
        _release_lock(lock)


def stamp_current_sha(*, updated_by: str, path: Path = MANIFEST) -> str:
    """현재 명부에 manifest_sha 지문만 심는다(승인 내용은 그대로). CAS 기준선 도입용."""
    return update_manifest(
        lambda d: d, updated_by=updated_by,
        expect_sha=read_content_sha(path), path=path)


if __name__ == "__main__":
    ok, stored, computed = verify_manifest_sha()
    if ok:
        print(f"MANIFEST_SHA_OK {stored[:16]}...", flush=True)
        raise SystemExit(0)
    print(
        f"MANIFEST_SHA_MISMATCH stored={stored[:16] or '(none)'} "
        f"computed={computed[:16]}",
        file=sys.stderr, flush=True)
    raise SystemExit(1)

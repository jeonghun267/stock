# -*- coding: utf-8 -*-
"""★공통 슬롯 장부 — 아침대장 + 급락주가 총 자본을 나눠 쓰는 로테이션  [2026-07-16 신설]

친구님 "총 200만에서 한 종목당 30만 로테이션. 먼저 기회 되는 전략이 먼저 쓴다."
  → 두 전략(별도 프로세스)이 이 파일 하나로 슬롯을 공유. 먼저 acquire 한 쪽이 슬롯 점유.
  → 슬롯 = '지금 쫓는 종목'(진입~완전종료). 매도-재매수 반복은 슬롯 유지(이미 내 것). done이면 release로 반환 → 로테이션.

경쟁 조건: 두 프로세스가 밀리초 단위 동시 진입 확률은 낮고(각 2초 루프), os.replace 원자적 쓰기 + 총 예수금이 2차 방어.
스위치: SHARED_MAX_SLOTS(기본 6) · SHARED_SLOTS_FILE
"""
import json, os, time
from contextlib import contextmanager
from pathlib import Path
import msvcrt

FILE = Path(os.environ.get("SHARED_SLOTS_FILE") or r"C:\stock_bot\data\shared_slots.json")
MAX  = int(os.environ.get("SHARED_MAX_SLOTS", "6"))
LOCK_TIMEOUT_SEC = float(os.environ.get("SHARED_SLOTS_LOCK_TIMEOUT_SEC", "2"))


@contextmanager
def _exclusive_lock():
    lock_path = FILE.with_suffix(FILE.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + LOCK_TIMEOUT_SEC
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("shared slot lock timeout")
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _load(today):
    try:
        d = json.loads(FILE.read_text(encoding="utf-8-sig"))
        if d.get("date") != today:
            return {"date": today, "slots": {}}
        return d
    except Exception:
        return {"date": today, "slots": {}}


def _save(d):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, FILE)


def count(today):
    """현재 점유 슬롯 수(두 전략 합계)."""
    return len(_load(today).get("slots", {}))


def has(code, today):
    return str(code).zfill(6) in _load(today).get("slots", {})


def acquire(code, strat, today):
    """슬롯 확보. 이미 내 종목이면 True(재매수). 풀 차면 False."""
    code = str(code).zfill(6)
    try:
        with _exclusive_lock():
            d = _load(today)
            s = d.setdefault("slots", {})
            if code in s:
                # 다른 전략이 점유한 같은 종목은 중복진입 금지.
                return s[code].get("strat") == strat
            if len(s) >= MAX:
                return False
            s[code] = {"strat": strat}
            d["date"] = today
            _save(d)
            return True
    except TimeoutError:
        return False


def release(code, today):
    """슬롯 반환(완전 종료 시). 다른 종목/전략이 쓸 수 있게."""
    code = str(code).zfill(6)
    with _exclusive_lock():
        d = _load(today)
        if code in d.get("slots", {}):
            del d["slots"][code]
            _save(d)

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
from datetime import datetime
from pathlib import Path
import msvcrt

FILE = Path(os.environ.get("SHARED_SLOTS_FILE") or r"C:\stock_bot\data\shared_slots.json")
MAX  = int(os.environ.get("SHARED_MAX_SLOTS", "6"))
LOCK_TIMEOUT_SEC = float(os.environ.get("SHARED_SLOTS_LOCK_TIMEOUT_SEC", "2"))
AUDIT_DIR = Path(os.environ.get("S01_S03_SLOT_AUDIT_DIR", r"C:\stock_bot\data\audit\s01_s03_slot_competition"))
AUDIT_FRESH_SEC = float(os.environ.get("S01_S03_SLOT_READY_FRESH_SEC", "5"))
REGIME_CACHE_DIR = Path(r"C:\stock_bot\DATA")
_AUDIT_IDS = {"STRATEGY01": "S01", "STRATEGY03": "S03"}

def _aid(value):
    return _AUDIT_IDS.get(str(value).strip().upper(), "")

def _epoch(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.astimezone() if dt.tzinfo else dt.astimezone()).timestamp()
    except (TypeError, ValueError):
        return 0.0

def _regime(day):
    try:
        row = json.loads((REGIME_CACHE_DIR / f"market_regime_{day}.json").read_text(encoding="utf-8-sig"))
        value = str(row.get("regime") or "").upper()
        return value if value in {"BULL", "NEUTRAL", "BEAR"} else "UNKNOWN"
    except (OSError, ValueError, TypeError):
        return "UNKNOWN"

def _audit(day, sid, signal_ts, requested, ok, used, peer, owner, reason):
    try:
        path = AUDIT_DIR / f"s01_s03_slot_competition_{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp": datetime.now().astimezone().isoformat(timespec="microseconds"),
               "regime": _regime(day), "strategy_id": sid, "buy_ready_ts": str(signal_ts),
               "slot_acquire_request_ts": requested.isoformat(timespec="microseconds"),
               "acquire_success": bool(ok), "used_slots_before": int(used),
               "peer_fresh_buy_ready": bool(peer), "final_slot_acquired_strategy": owner,
               "result_reason": reason}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass



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


def _acquire(code, strat, today, buy_ready_ts=""):
    code = str(code).zfill(6); sid = _aid(strat) if buy_ready_ts else ""
    requested = datetime.now().astimezone()
    try:
        with _exclusive_lock():
            d = _load(today); slots = d.setdefault("slots", {}); used = len(slots); peer = False
            if sid:
                ready = d.setdefault("_s01_s03_audit_ready", {})
                other = "S03" if sid == "S01" else "S01"
                age = requested.timestamp() - _epoch((ready.get(other) or {}).get("buy_ready_ts"))
                peer = 0.0 <= age <= AUDIT_FRESH_SEC
                ready[sid] = {"buy_ready_ts": str(buy_ready_ts), "slot_acquire_request_ts": requested.isoformat(timespec="microseconds")}
            if code in slots:
                ok = slots[code].get("strat") == strat; reason = "OWN_SLOT_REUSE" if ok else "CODE_OWNED_BY_PEER"; owner = slots[code].get("strat")
            elif len(slots) >= MAX:
                ok = False; reason = "POOL_FULL"; owner = next(reversed(slots.values())).get("strat") if slots else ""
            else:
                slots[code] = {"strat": strat}; d["date"] = today; ok = True; reason = "ACQUIRED"; owner = strat
            if (ok and reason == "ACQUIRED") or sid: _save(d)
            if sid: _audit(today, sid, buy_ready_ts, requested, ok, used, peer, _aid(owner), reason)
            return ok
    except TimeoutError:
        if sid: _audit(today, sid, buy_ready_ts, requested, False, count(today), False, "", "LOCK_TIMEOUT")
        return False

def acquire(code, strat, today):
    """Unchanged first-come shared-slot decision."""
    return _acquire(code, strat, today)

def acquire_with_audit(code, strat, today, *, buy_ready_ts):
    """Audit S01/S03 competition without changing the decision."""
    return _acquire(code, strat, today, buy_ready_ts)


def release(code, today):
    """슬롯 반환(완전 종료 시). 다른 종목/전략이 쓸 수 있게."""
    code = str(code).zfill(6)
    with _exclusive_lock():
        d = _load(today)
        if code in d.get("slots", {}):
            del d["slots"][code]
            _save(d)

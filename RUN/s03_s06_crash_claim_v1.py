# -*- coding: utf-8 -*-
"""S03 OPEN_CRASH priority ledger shared only with S06.

This ledger never reserves capital. shared_slots.json remains the sole
capital-slot authority and is acquired only by the order engines.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any, Iterator

import msvcrt


CLAIM_DIR = Path(os.environ.get(
    "S03_S06_CRASH_CLAIM_DIR", r"C:\stock_bot\data"))
CLAIM_TTL_SEC = float(os.environ.get("S03_S06_CLAIM_TTL_SEC", "120"))
LOCK_TIMEOUT_SEC = float(os.environ.get(
    "S03_S06_CLAIM_LOCK_TIMEOUT_SEC", "2"))
PRIORITY_END = day_time(9, 20)
ACTIVE_STATES = frozenset({"CLAIMED", "ORDERING", "BOUGHT"})


def enabled() -> bool:
    """Claims stay dormant until separately enabled for the S03 process."""
    return os.environ.get(
        "S03_S06_CRASH_CLAIM_ENABLED", "NO").strip().upper() == "YES"


def claim_path(now: datetime, directory: Path | None = None) -> Path:
    root = Path(directory) if directory is not None else CLAIM_DIR
    return root / f"s03_s06_crash_claim_{now:%Y%m%d}.json"


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
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
                    raise TimeoutError("S03/S06 crash claim lock timeout")
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _load(path: Path, day: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("date") == day and isinstance(payload.get("claims"), dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {"schema": "S03_S06_CRASH_CLAIM_V1", "date": day, "claims": {}}


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _audit(path: Path, row: dict[str, Any], now: datetime, event: str) -> None:
    audit_path = path.parent / f"s03_s06_crash_claim_audit_{now:%Y%m%d}.jsonl"
    record = {
        "ts": now.isoformat(timespec="microseconds"),
        "event": event,
        "code": str(row.get("code") or "").zfill(6),
        "owner": str(row.get("owner") or ""),
        "state": str(row.get("state") or ""),
        "event_id": str(row.get("event_id") or ""),
        "expires_ts": str(row.get("expires_ts") or ""),
        "reason": str(row.get("reason") or ""),
        "order_id": str(row.get("order_id") or ""),
    }
    try:
        with audit_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # The claim ledger is the ownership authority. An auxiliary audit
        # failure must never reverse an already committed claim transition.
        pass


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _expire(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("state") or "") != "CLAIMED":
        return False
    expires = _parse(row.get("expires_ts"))
    if expires is not None and (expires.tzinfo is None) != (now.tzinfo is None):
        # Older S03 rows were stored without an offset, while S06 supplies a
        # timezone-aware KST clock. Both values represent the same KST wall
        # clock, so align the persisted value before comparing them.
        expires = expires.replace(tzinfo=now.tzinfo)
    if now.time() >= PRIORITY_END or expires is None or now >= expires:
        row.update({
            "state": "EXPIRED",
            "updated_ts": now.isoformat(timespec="microseconds"),
            "reason": (
                "PRIORITY_WINDOW_END"
                if now.time() >= PRIORITY_END else "TTL_EXPIRED"),
        })
        return True
    return False


def try_claim_s03(
    code: str,
    event_id: str,
    now: datetime,
    *,
    directory: Path | None = None,
    ttl_sec: float = CLAIM_TTL_SEC,
) -> str:
    """Atomically claim one S03 low event without consuming capital."""
    if not enabled() or now.time() >= PRIORITY_END:
        return "DISABLED"
    code = str(code).zfill(6)
    path = claim_path(now, directory)
    try:
        with _exclusive_lock(path):
            payload = _load(path, now.strftime("%Y%m%d"))
            claims = payload.setdefault("claims", {})
            previous = (
                claims.get(code) if isinstance(claims.get(code), dict) else {})
            _expire(previous, now)
            if (previous.get("owner") == "S03"
                    and previous.get("event_id") == event_id):
                if previous.get("state") in ACTIVE_STATES:
                    return str(previous["state"])
                # The same released/expired low cannot reserve S06 again.
                return str(previous.get("state") or "RELEASED")
            expires = min(
                now + timedelta(seconds=max(1.0, ttl_sec)),
                now.replace(hour=9, minute=20, second=0, microsecond=0),
            )
            claims[code] = {
                "code": code,
                "owner": "S03",
                "state": "CLAIMED",
                "event_id": str(event_id),
                "claimed_ts": now.isoformat(timespec="microseconds"),
                "expires_ts": expires.isoformat(timespec="microseconds"),
                "updated_ts": now.isoformat(timespec="microseconds"),
                "reason": "OPEN_CRASH_ARMED",
                "order_id": "",
            }
            _save(path, payload)
            _audit(path, claims[code], now, "CLAIM_CREATED")
            return "CLAIMED"
    except (OSError, TimeoutError):
        return "ERROR"


def s03_claim_status(
    code: str,
    now: datetime,
    *,
    directory: Path | None = None,
) -> str:
    """Return an active state, FREE, or ERROR for the S06 reader."""
    code = str(code).zfill(6)
    path = claim_path(now, directory)
    if not path.exists():
        return "FREE"
    try:
        with _exclusive_lock(path):
            payload = _load(path, now.strftime("%Y%m%d"))
            row = payload.get("claims", {}).get(code)
            if not isinstance(row, dict):
                return "FREE"
            if _expire(row, now):
                _save(path, payload)
                _audit(path, row, now, "CLAIM_EXPIRED")
            if row.get("owner") == "S03" and row.get("state") in ACTIVE_STATES:
                return str(row["state"])
            return "FREE"
    except (OSError, TimeoutError):
        return "ERROR"


def active_s03_claims(
    now: datetime,
    *,
    directory: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return active S03 rows for startup reconciliation."""
    path = claim_path(now, directory)
    if not path.exists():
        return {}
    try:
        with _exclusive_lock(path):
            payload = _load(path, now.strftime("%Y%m%d"))
            changed = False
            active: dict[str, dict[str, Any]] = {}
            for raw_code, row in payload.get("claims", {}).items():
                if not isinstance(row, dict):
                    continue
                if _expire(row, now):
                    changed = True
                    _audit(path, row, now, "CLAIM_EXPIRED")
                if row.get("owner") == "S03" and row.get("state") in ACTIVE_STATES:
                    active[str(raw_code).zfill(6)] = dict(row)
            if changed:
                _save(path, payload)
            return active
    except (OSError, TimeoutError):
        return {}


def _transition(
    code: str,
    now: datetime,
    state: str,
    *,
    reason: str,
    order_id: str = "",
    directory: Path | None = None,
    allowed_from: frozenset[str] = ACTIVE_STATES,
) -> bool:
    path = claim_path(now, directory)
    if not path.exists():
        return False
    try:
        with _exclusive_lock(path):
            payload = _load(path, now.strftime("%Y%m%d"))
            row = payload.get("claims", {}).get(str(code).zfill(6))
            if not isinstance(row, dict) or row.get("owner") != "S03":
                return False
            if str(row.get("state") or "") not in allowed_from:
                return False
            row.update({
                "state": state,
                "updated_ts": now.isoformat(timespec="microseconds"),
                "reason": str(reason),
                "order_id": str(order_id),
            })
            _save(path, payload)
            _audit(path, row, now, f"CLAIM_{state}")
            return True
    except (OSError, TimeoutError):
        return False


def mark_bought(
    code: str,
    now: datetime,
    *,
    order_id: str = "",
    directory: Path | None = None,
) -> bool:
    return _transition(
        code, now, "BOUGHT", reason="S03_BUY_CONFIRMED",
        order_id=order_id, directory=directory,
        allowed_from=frozenset({"ORDERING", "BOUGHT"}))


def mark_ordering(
    code: str,
    now: datetime,
    *,
    order_id: str = "",
    directory: Path | None = None,
) -> bool:
    return _transition(
        code, now, "ORDERING", reason="S03_BUY_ORDER_PREPARED",
        order_id=order_id, directory=directory,
        allowed_from=frozenset({"CLAIMED", "ORDERING"}))


def release_claimed_s03(
    code: str,
    now: datetime,
    *,
    reason: str,
    directory: Path | None = None,
) -> bool:
    """Signal process may release only an uncommitted candidate claim."""
    return _transition(
        code, now, "RELEASED", reason=reason, directory=directory,
        allowed_from=frozenset({"CLAIMED"}))


def release_s03(
    code: str,
    now: datetime,
    *,
    reason: str,
    directory: Path | None = None,
) -> bool:
    return _transition(
        code, now, "RELEASED", reason=reason, directory=directory)

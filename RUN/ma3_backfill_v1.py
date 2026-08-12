# -*- coding: utf-8 -*-
"""Central, read-only broker backfill for missing opening MA3 history.

Strategies only create one small request file per code.  The single
deep-bottom recorder process services those requests in a daemon thread, so
S01/S02/S03/S05/S06 never issue duplicate opt10080 calls from their sell loops.
This module contains no order path.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


REQUEST_DIR = Path(r"C:\stock_bot\IPC\ma3_backfill_requests")
CACHE_DIR = Path(r"C:\stock_bot\data\ma3_backfill")
PACE_SEC = float(os.environ.get("MA3_BACKFILL_PACE", "0.60"))
MAX_REQUESTS = int(os.environ.get("MA3_BACKFILL_MAX", "200"))
FAIL_RETRY_SEC = int(os.environ.get("MA3_BACKFILL_RETRY_SEC", "60"))


def _code(value: str) -> str:
    normalized = str(value or "").strip().zfill(6)
    return normalized if len(normalized) == 6 and normalized.isdigit() else ""


def _cache_path(code: str, cache_dir: Path = CACHE_DIR) -> Path:
    return Path(cache_dir) / f"{code}.json"


def read_cached_bars(
    code: str,
    trading_day: date,
    cache_dir: Path = CACHE_DIR,
) -> List[Tuple[datetime, float]]:
    """Return timestamped 3-minute closes fetched on ``trading_day``."""
    normalized = _code(code)
    if not normalized:
        return []
    try:
        payload = json.loads(
            _cache_path(normalized, cache_dir).read_text(encoding="utf-8")
        )
        fetched = datetime.fromisoformat(str(payload.get("fetched_at") or ""))
        if fetched.date() != trading_day or payload.get("status") != "OK":
            return []
        out = []
        for item in payload.get("bars") or []:
            ts = datetime.strptime(str(item[0]), "%Y%m%d%H%M%S")
            price = float(item[1])
            minute = ts.hour * 60 + ts.minute
            if price > 0 and 9 * 60 <= minute <= 15 * 60 + 30:
                out.append((ts, price))
        return sorted(out, key=lambda item: item[0])
    except (OSError, ValueError, TypeError, KeyError):
        return []


def request_backfill(
    code: str,
    reason: str,
    request_dir: Path = REQUEST_DIR,
    cache_dir: Path = CACHE_DIR,
    now: Optional[datetime] = None,
) -> bool:
    """Request one central backfill.  Returns True only for a new request."""
    observed = now or datetime.now()
    normalized = _code(code)
    if not normalized:
        return False
    if len(read_cached_bars(normalized, observed.date(), cache_dir)) >= 21:
        return False

    cache_file = _cache_path(normalized, cache_dir)
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        retry_after = float(cached.get("retry_after") or 0)
        if cached.get("status") == "FAILED" and retry_after > time.time():
            return False
    except (OSError, ValueError, TypeError):
        pass

    target_dir = Path(request_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{normalized}.json"
    if target.exists():
        return False
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({
            "code": normalized,
            "reason": str(reason or "MA3_NOT_READY")[:80],
            "requested_at": observed.isoformat(timespec="seconds"),
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.replace(temporary, target)
    except OSError:
        temporary.unlink(missing_ok=True)
        return False
    return True


def _absolute_price(value) -> float:
    try:
        return abs(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0.0


def _fetch(code: str, broker) -> List[List[object]]:
    response = broker.tr(
        "opt10080",
        inputs={"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
        output_fields=["체결시간", "현재가"],
        timeout_sec=4.0,
        rqname="opt10080_ma3_open_backfill_v1",
    )
    if str((response or {}).get("status", "")).upper() != "OK":
        return []
    records = ((response.get("data") or {}).get("records")) or []
    by_block: Dict[str, List[object]] = {}
    for raw in records[:130]:
        digits = "".join(ch for ch in str(raw.get("체결시간") or "") if ch.isdigit())
        if len(digits) < 14:
            continue
        stamp = digits[:14]
        try:
            parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        except ValueError:
            continue
        minute = parsed.hour * 60 + parsed.minute
        price = _absolute_price(raw.get("현재가"))
        if price <= 0 or not 9 * 60 <= minute <= 15 * 60 + 30:
            continue
        block = f"{parsed:%Y%m%d}{minute // 3:04d}"
        current = by_block.get(block)
        if current is None or stamp > str(current[0]):
            by_block[block] = [stamp, price]
    return sorted(by_block.values(), key=lambda item: str(item[0]))[-130:]


def _write_cache(code: str, payload: dict, cache_dir: Path = CACHE_DIR) -> None:
    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path(code, target_dir)
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def serve_requests(
    stop: threading.Event,
    logger: Optional[Callable[[str], None]] = None,
    request_dir: Path = REQUEST_DIR,
    cache_dir: Path = CACHE_DIR,
) -> None:
    """Service deduplicated requests serially with a hard daily call cap."""
    log = logger or (lambda _message: None)
    try:
        from broker_client import BrokerClient
        broker = BrokerClient()
    except Exception as exc:
        log(f"MA3_BACKFILL broker init failed: {exc}")
        return

    calls = 0
    while not stop.is_set():
        paths = sorted(Path(request_dir).glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not paths:
            stop.wait(0.25)
            continue
        path = paths[0]
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            code = _code(request.get("code"))
            if not code:
                path.unlink(missing_ok=True)
                continue
            if len(read_cached_bars(code, datetime.now().date(), cache_dir)) >= 21:
                path.unlink(missing_ok=True)
                continue
            if calls >= MAX_REQUESTS:
                log(f"MA3_BACKFILL daily cap reached={MAX_REQUESTS}")
                stop.wait(5.0)
                continue
            calls += 1
            bars = _fetch(code, broker)
            now = datetime.now()
            if len(bars) >= 21:
                _write_cache(code, {
                    "status": "OK",
                    "fetched_at": now.isoformat(timespec="seconds"),
                    "bars": bars,
                    "reason": request.get("reason", ""),
                }, cache_dir)
                log(f"MA3_BACKFILL OK code={code} blocks={len(bars)} calls={calls}")
            else:
                _write_cache(code, {
                    "status": "FAILED",
                    "fetched_at": now.isoformat(timespec="seconds"),
                    "retry_after": time.time() + FAIL_RETRY_SEC,
                    "bars": [],
                }, cache_dir)
                log(f"MA3_BACKFILL FAIL code={code} blocks={len(bars)} calls={calls}")
            path.unlink(missing_ok=True)
            stop.wait(PACE_SEC)
        except Exception as exc:
            log(f"MA3_BACKFILL error file={path.name}: {exc}")
            path.unlink(missing_ok=True)
            stop.wait(PACE_SEC)


def start_worker(logger: Optional[Callable[[str], None]] = None):
    stop = threading.Event()
    thread = threading.Thread(
        target=serve_requests,
        args=(stop, logger),
        name="ma3-backfill",
        daemon=True,
    )
    thread.start()
    return stop, thread

# -*- coding: utf-8 -*-
"""Fail-closed HMAC authentication for SENDORDER_REAL IPC requests."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Tuple


SECRET_PATH = Path(r"C:\stock_bot\config\ipc_order_auth.key")
AUTH_VERSION = 1
MAX_AUTH_AGE_SEC = 30.0
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

# ★[IPC-AUTH-SCOPE 2026-08-04] 서명이 필요한 파괴적 명령 목록.
#   SET_REAL_REMOVE_ALL 은 SHUTDOWN 보다 은밀하다 — 브로커는 살아 있고 하트비트도
#   정상인데 전 종목 실시간만 끊긴다. 워치독은 하트비트/프리징만 보므로 이걸 절대
#   못 잡고, 그 사이 엔진은 손절·트레일까지 눈이 먼 채로 돈다(8/3 27초 공백과 동류).
#   정당한 호출자는 코드베이스에 0건이다 — broker_client.set_real_remove_all 은
#   정의만 있고 부르는 곳이 없다. 그래서 fail-closed 로 잠가도 깨지는 경로가 없다.
PROTECTED_TYPES = frozenset({"SENDORDER_REAL", "SET_REAL_REMOVE_ALL"})


class OrderAuthError(RuntimeError):
    pass


def _read_secret(path: Path) -> bytes:
    try:
        secret = path.read_bytes()
    except OSError as exc:
        raise OrderAuthError("order IPC auth key is unavailable") from exc
    if len(secret) < 32:
        raise OrderAuthError("order IPC auth key is invalid")
    return secret


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    unsigned = dict(payload)
    unsigned.pop("auth_tag", None)
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_order_request(
    payload: Dict[str, Any],
    *,
    secret_path: Path = SECRET_PATH,
    now: float | None = None,
) -> Dict[str, Any]:
    """Return a signed copy. Missing/invalid key raises and no IPC file is written."""
    if str(payload.get("type") or "") not in PROTECTED_TYPES:
        raise OrderAuthError(
            "this request type does not use IPC authentication")
    if not str(payload.get("request_id") or "").strip():
        raise OrderAuthError("request_id is required before signing")
    signed = dict(payload)
    signed["auth_version"] = AUTH_VERSION
    signed["auth_ts"] = int(time.time() if now is None else now)
    signed["auth_nonce"] = secrets.token_hex(16)
    signed["auth_tag"] = hmac.new(
        _read_secret(secret_path), _canonical_bytes(signed), hashlib.sha256
    ).hexdigest()
    return signed


def verify_order_request(
    payload: Dict[str, Any],
    *,
    expected_type: str | None = None,
    secret_path: Path = SECRET_PATH,
    now: float | None = None,
    max_age_sec: float = MAX_AUTH_AGE_SEC,
) -> Tuple[bool, str]:
    """Verify signature and freshness. Returns (False, reason) on every failure.

    expected_type 은 호출한 분기와 서명된 type 이 같은지 못박는다. 지금은 dispatch 가
    같은 필드를 읽으므로 중복이지만, 분기 기준이 바뀌면 그때 조용히 뚫린다.
    """
    try:
        request_type = str(payload.get("type") or "")
        if request_type not in PROTECTED_TYPES:
            return False, "wrong request type"
        if expected_type is not None and request_type != str(expected_type):
            return False, "request type mismatch"
        if int(payload.get("auth_version", 0)) != AUTH_VERSION:
            return False, "missing or unsupported auth version"
        if not str(payload.get("request_id") or "").strip():
            return False, "missing request_id"
        nonce = str(payload.get("auth_nonce") or "")
        if not _NONCE_RE.fullmatch(nonce):
            return False, "missing or invalid auth nonce"
        auth_ts = float(payload.get("auth_ts"))
        clock = time.time() if now is None else float(now)
        if abs(clock - auth_ts) > float(max_age_sec):
            return False, "expired order authentication"
        supplied = str(payload.get("auth_tag") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", supplied):
            return False, "missing or invalid auth tag"
        expected = hmac.new(
            _read_secret(secret_path), _canonical_bytes(payload), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            return False, "order authentication mismatch"
        return True, ""
    except (OrderAuthError, TypeError, ValueError):
        return False, "order authentication unavailable"

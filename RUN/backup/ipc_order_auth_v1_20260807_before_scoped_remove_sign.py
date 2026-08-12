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
#
# ★[IPC-AUTH-BLANKET 2026-08-05 친구님 승인 ⓐ] 위 잠금 바로 옆에 같은 문이 두 개
#   더 열려 있었다. 8/5 밤 보안점검에서 찾았다.
#     · SET_REAL_REMOVE 에 screen_no/code = "ALL" 을 넣으면 SET_REAL_REMOVE_ALL 과
#       똑같은 일이 무인증으로 된다. 게이트웨이 설명서(:1976)에 그렇게 적혀 있다.
#       즉 8/4 잠금은 앞문만 잠근 것이었다.
#     · SETREAL_REG 는 더 오래 간다 — 성공하면 broker_state.json 에 적히고
#       재기동 때 _replay_realreg() 가 되살린다. 껐다 켜도 안 돌아온다.
#   두 명령 모두 정당한 호출자가 0건이다(구독은 브로커가 자체 OCX 로 한다.
#   broker_client 의 setreal_reg·set_real_remove 는 정의만 있고 부르는 곳이 없다).
#   ⚠️여기에 이름을 넣으면 broker_client.request() 가 자동으로 서명한다. 새 호출자를
#     만들 때 BrokerClient 를 거치기만 하면 따로 할 일이 없다 — 손으로 IPC json 을
#     쓰는 경로를 만들면 그때 조용히 막힌다.
#
# ★[IPC-AUTH-SHUTDOWN 2026-08-06 친구님 지시 "지금해"] SHUTDOWN 을 서명 대상에 넣었다.
#   IPC SHUTDOWN 을 무인증으로 두면 IPC\requests 에 쓸 수 있는 코드가 브로커를 꺼
#   엔진 전체를 눈멀게 한다. 유일한 정당 발신자는 broker_night_stop.ps1 이고 그것은
#   BrokerClient().request({'type':'SHUTDOWN'}) 로 보낸다 → 여기 이름을 넣는 것만으로
#   자동 서명되므로 야간정지는 손대지 않아도 그대로 통과한다(request() :221-223).
#   서명은 페이로드 전체(주문 필드 무관)에 HMAC 을 걸므로 code/qty 없는 SHUTDOWN 도
#   정상 서명·검증된다. 되돌리기: 이 줄 하나 삭제 + 게이트웨이 SHUTDOWN 분기 원복.
#
# ★[IPC-HARDEN 2026-08-07] DISCONNECT_SCR 을 넣었다. 화면 하나를 끊으면 그 화면의
#   실시간이 통째로 죽는데 무인증이었다. 단 게이트웨이가 조건부로만 강제한다 —
#   1분봉 수집기의 TR 풀(2000~2049)은 종전대로 통과하고, 그 밖의 화면(9xxx =
#   전략 실시간 구독)만 서명을 요구한다(broker_gateway_v1._is_protected_screen).
#   수집기는 BrokerClient 를 안 거치고 IPC json 을 직접 쓰기 때문에 전면 강제하면
#   1분봉 수집이 깨진다. BrokerClient.disconnect_scr 경유 호출자는 자동 서명된다.
PROTECTED_TYPES = frozenset({
    "SENDORDER_REAL",
    "SET_REAL_REMOVE_ALL",
    "SET_REAL_REMOVE",      # 전면 해제(ALL)일 때만 게이트웨이가 강제한다
    "SETREAL_REG",
    "SHUTDOWN",             # [2026-08-06] 브로커 정지 — 무인증이면 엔진을 눈멀게 함
    "DISCONNECT_SCR",       # [2026-08-07] 수집기 풀 밖 화면일 때만 게이트웨이가 강제
})


class OrderAuthError(RuntimeError):
    pass


class NonceStore:
    """★[IPC-HARDEN 2026-08-07] 한 번 쓴 nonce 를 다시 못 쓰게 한다.

    서명은 30초(MAX_AUTH_AGE_SEC) 동안 유효하다. 그래서 IPC\\requests 를 읽을 수
    있는 코드가 정당한 요청 파일을 그대로 복사해 다시 넣으면 같은 명령이 한 번 더
    집행됐다 — 실주문이면 같은 주문이 두 번 나간다. 서명은 페이로드에 대한 것이라
    사본은 서명 검증을 정상 통과한다. 그래서 "이미 본 nonce 인가"를 따로 봐야 한다.

    검증(verify_order_request)에는 넣지 않았다. 검증은 순수 함수로 두고 상태는
    받는 쪽(게이트웨이)에 둔다 — 같은 페이로드를 두 번 검증하는 시험이 깨지지 않고,
    "누가 소비했는가"의 책임이 서버에 남는다.

    보관 기간은 서명 유효기간의 2배다. 그보다 오래된 것은 어차피 만료로 거부된다.
    """

    def __init__(self, ttl_sec: float = MAX_AUTH_AGE_SEC * 2) -> None:
        self._ttl = float(ttl_sec)
        self._seen: Dict[str, float] = {}

    def consume(self, nonce: str, *, now: float | None = None) -> bool:
        """처음 보는 nonce 면 기록하고 True. 이미 본 것이면 False(재생 공격)."""
        clock = time.time() if now is None else float(now)
        self._prune(clock)
        if not _NONCE_RE.fullmatch(str(nonce or "")):
            return False
        if nonce in self._seen:
            return False
        self._seen[nonce] = clock
        return True

    def _prune(self, clock: float) -> None:
        if len(self._seen) < 256:
            stale = [n for n, t in self._seen.items() if clock - t > self._ttl]
        else:
            stale = [n for n, t in list(self._seen.items()) if clock - t > self._ttl]
        for n in stale:
            self._seen.pop(n, None)


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

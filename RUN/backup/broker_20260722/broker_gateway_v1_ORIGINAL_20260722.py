"""
broker_gateway_v1.py — Kiwoom OCX Ownership Firewall (STEP-1)

[Broker v1 STEP-1] OCX 1개 소유 + IPC polling + TR 1건 skeleton

설계 철학:
  Broker는 "새 시스템"이 아니다.
  Broker는 SAFE+ 전체를 보호하는 "OCX Ownership Firewall" 역할만 수행.
  Kiwoom OCX/CommConnect는 이 프로세스만 독점 — 다른 모듈은 직접 OCX 호출 금지.

STEP-1 구현 범위:
  - QApplication / QAxWidget 생성
  - CommConnect 로그인 (1회)
  - 5초 간격 broker_heartbeat.json 갱신
  - 500ms IPC request polling
  - TR 1건 처리 skeleton (record_count 회신)
  - State machine (6 states)
  - broker_journal 로그 (RotatingFileHandler)
  - Request TTL 처리
  - 단일 실행 lock (broker_gateway.lock)

STEP-1 금지 (집행):
  - 주문 (SendOrder)
  - 실시간 (SetRealReg / OnReceiveRealData)
  - 전략 수정
  - collector / execution / SAFE+ 모듈 연결
  - 기존 SAFE+ 구조 변경
"""

import sys
import os
import json
import time
import csv as _csv          # [FILL-REC 2026-07-13] 체결가 누적 CSV 기록용
import ctypes
import atexit
import signal
import logging
from pathlib import Path
from enum import Enum
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, QTimer

# ═══════════════════════════════════════════════════════════════
# [TR-THROTTLE 2026-06-24] broker 송출 TR도 공유 레이트리미터 적용.
#   원인: 6/24 돌파 실행기가 broker IPC로 opt10080 28종목 + 주문을 폭주 →
#         broker는 limiter 미적용이라 그대로 OCX에 초당 2회 초과 송출 → 키움 TR 과다 수신차단.
#   해결: 1분봉 수집기가 쓰던 동일 파일기반 KiwoomRateLimiter(2/sec 공유예산)를 broker도 acquire.
#   fail-open: import 실패 시 no-op(_NoLimiter) → broker 동작 절대 차단 안 함.
#   롤백: 본 블록 + 두 acquire() 제거 또는 .bak_pre_trthrottle_20260624 복원.
# ═══════════════════════════════════════════════════════════════
try:
    sys.path.insert(0, r"C:\stock_bot\RUN")
    from safeplus_rate_limiter import KiwoomRateLimiter
    _tr_limiter = KiwoomRateLimiter()
except Exception:
    class _NoLimiter:
        def acquire(self):
            pass
    _tr_limiter = _NoLimiter()

# ═══════════════════════════════════════════════════════════════
# Path
# ═══════════════════════════════════════════════════════════════
BASE_DIR  = Path(r"C:\stock_bot")
DATA_DIR  = BASE_DIR / "DATA"
IPC_DIR   = BASE_DIR / "IPC"
IPC_REQ   = IPC_DIR / "requests"
IPC_RES   = IPC_DIR / "responses"
# [STEP-2F-2.5] Chejan IPC broadcast 디렉터리
IPC_CHEJAN_DIR = IPC_DIR / "chejan_events"
# [STEP-2F-4] SendOrder shadow mirror + ACK/FILL relay 디렉터리
IPC_ORDER_SHADOW_DIR     = IPC_DIR / "order_shadow"
IPC_ORDER_SHADOW_ACK_DIR = IPC_DIR / "order_shadow_ack"
# [N15 2026-05-14] OnReceiveMsg 시스템 메시지 broadcast 디렉터리
IPC_MSG_EVENTS_DIR       = IPC_DIR / "msg_events"
# [B1/C1/D1/E1 2026-05-14] 실시간 시세 broadcast 디렉터리 (OnReceiveRealData → IPC)
IPC_REAL_DATA_DIR        = IPC_DIR / "real_data"
HB_FILE   = IPC_DIR / "broker_heartbeat.json"
LOCK_FILE = DATA_DIR / "broker_gateway.lock"
LOG_DIR   = BASE_DIR / "LOG"
LOG_FILE  = LOG_DIR / "broker_journal.log"
# [Z2 2026-05-14] reconnect/state replay — SetRealReg 등록 상태 영속 저장
STATE_FILE = DATA_DIR / "broker_state.json"

# [REAL-MICRO 2026-06-24] ★실시간 마이크로구조 구독 — 친구님 설계: broker만 키움 실시간구독(SetRealReg)
#   → 체결강도(FID228)·호가총잔량(121/125) 수신 → IPC snapshot 1파일 batched broadcast → 봇은 파일만 읽음.
#   TR기반 체결강도(opt10001=빈값)·호가(opt10004=throttle None) 폐기. env REAL_MICRO=ON 시만 활성(기본 OFF=기존 100% 동일).
#   과거 OFF원인(event당 파일1개 I/O폭주)은 '메모리dict→1초1파일 flush'로 해결.
REAL_MICRO_ON        = os.environ.get("REAL_MICRO", "OFF").strip().upper() == "ON"
MICRO_WATCH_FILE     = IPC_DIR / "micro_watch.json"             # 구독 대상 코드(소비자가 작성: {"codes":[...]})
MICRO_SNAPSHOT_FILE  = IPC_DIR / "live_micro_snapshot.json"     # 종목별 최신 마이크로(broker가 1초마다 작성)
MICRO_SCREEN         = "9300"                                    # 마이크로 전용 실시간 화면(타 화면 무간섭) — 분할 시작 화면번호
MICRO_FIDS           = "10;13;15;228;121;125;27;28"             # 현재가;누적거래량;거래량;체결강도;매도총잔량;매수총잔량;최우선매도;최우선매수
# [OB-FIX 2026-07-13 친구님 "호가도 받게 해줘"] ★키움은 화면 1개당 실시간 100종목이 한계.
#   CAP=120을 화면 9300 하나에 몰아넣어(SetRealReg) 넘치는 뒤쪽이 조용히 잘려나갔다.
#   실측(장중 40초 관측): 정렬 앞100 호가생존 93/100 vs 뒤20 5/20.
#   체결(228)은 타 엔진이 다른 화면에도 등록해둬서 살아남지만, 호가(121/125)는 이 화면에만 있어 통째로 소멸
#   → "체결강도는 오는데 호가만 없는" 종목 발생 → 깊은바닥 진입 호가관문에 걸려 445090·399720 종일 매수불가.
#   해결: MICRO_CHUNK 종목씩 화면 9300·9301·… 로 쪼개 등록(전부 100 미만) + 우선순위 순서 유지(돈맥 깊은바닥이 첫 화면).
#   롤백: setx MICRO_CHUNK 999  (=기존처럼 한 화면에 몰아넣기)
MICRO_CHUNK          = int(os.environ.get("MICRO_CHUNK", "90"))  # 화면당 실시간 등록 종목수(키움 한계 100 미만)
MICRO_THROTTLE_MS    = 200                                       # 종목별 micro update 최소간격(CPU 보호)
MICRO_FLUSH_MS       = 1000                                      # snapshot 파일 flush 주기

for d in (
    DATA_DIR, IPC_REQ, IPC_RES,
    IPC_CHEJAN_DIR, IPC_ORDER_SHADOW_DIR, IPC_ORDER_SHADOW_ACK_DIR,
    IPC_MSG_EVENTS_DIR,
    IPC_REAL_DATA_DIR,
    LOG_DIR,
):
    d.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Logging (broker_journal)
# ═══════════════════════════════════════════════════════════════
logger = logging.getLogger("BROKER_v1")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter(
    "[%(asctime)s][%(levelname)s][BROKER_v1] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_rot = RotatingFileHandler(
    # [L1 2026-05-21] utf-8 → utf-8-sig (BOM) — PowerShell Get-Content 자동 UTF-8 인식 (한글 깨짐 0)
    str(LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8-sig"
)
_rot.setFormatter(_fmt)
logger.addHandler(_rot)


# [CYCLE-6 2026-05-21] event_journal.jsonl — 통합 audit (모든 모듈 inline helper, 단순 jsonl append-only)
# Why: 5/19 funnel cascade 분석 4h+ → 단일 jsonl로 1분 (event_journal cross-module audit).
# 각 모듈 inline 동일 helper (코드 중복 ~10줄, 단 신규 file 미생성 = 사용자 정책 일치).
def _emit_event(event_type, entity, entity_id="", payload=None, prev_state=None, new_state=None):
    """[CYCLE-6] event_journal.jsonl append-only writer. fail-safe (broker 영향 0)."""
    try:
        _evt_path = LOG_DIR / f"event_journal_{datetime.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "broker_gateway_v1",
        }
        if prev_state is not None: _evt["prev_state"] = prev_state
        if new_state is not None: _evt["new_state"] = new_state
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass  # fail-safe

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(_fmt)
logger.addHandler(_console)


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-2.5 2026-05-13] Observability sub-loggers
#   실제 broadcast 는 STEP-2F-3 에서 진행. 본 단계는 계측 기반만.
# ═══════════════════════════════════════════════════════════════
logger_event   = logging.getLogger("BROKER_v1.EVENT_TRACE")    # 일반 이벤트 흐름
logger_chejan  = logging.getLogger("BROKER_v1.CHEJAN_TRACE")   # 체결 이벤트
logger_latency = logging.getLogger("BROKER_v1.IPC_LATENCY")    # IPC end-to-end latency
# [STEP-2F-4] SendOrder shadow latency tracking
logger_order_shadow = logging.getLogger("BROKER_v1.ORDER_SHADOW_LATENCY")
# 각 sub-logger 는 parent BROKER_v1 의 handler 를 자동 상속 (propagate=True 기본)


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-2.5] Chejan Event Schema (template / 미연결)
#   STEP-2F-3 에서 실제 broadcast 시 사용. 본 단계는 schema 문서화만.
# ═══════════════════════════════════════════════════════════════
CHEJAN_EVENT_SCHEMA = {
    "event_id": "",                # uuid4 (dedup 키)
    "ts": "",                      # ISO8601 — broker 파일 write 완료 시각
    "ts_broker_callback": "",      # ISO8601 — OnReceiveChejanData 진입 시각
    "ts_subscriber_consume": "",   # ISO8601 — subscriber 가 채울 필드 (latency 측정용)
    "gubun": "",                   # "0"=체결/잔고
    "fid_data": {                  # FID(string):value(string) map
        # "905":  "주문구분",
        # "9203": "주문번호",
        # "913":  "주문상태",
        # "9001": "종목코드",
        # "911":  "체결수량",
        # "910":  "체결가",
        # "902":  "미체결수량",
    },
}

# [STEP-2F-3] FID 최소셋 (7개) — 추가 금지
CHEJAN_FIDS: dict = {
    "9203": "주문번호",
    "913":  "주문상태",
    "9001": "종목코드",
    "911":  "체결수량",
    "910":  "체결가",
    "902":  "미체결수량",
    "905":  "주문구분",
}
# 보유 파일 청소 임계 (초)
CHEJAN_EVENT_TTL_SEC = 300

import uuid as _bro_uuid_v1


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-2.5] Dedup Cache (skeleton — 미연결)
#   STEP-2F-3 에서 multi-subscriber 경합 시 event_id TTL dedup 으로 사용.
# ═══════════════════════════════════════════════════════════════
class DedupCache:
    """event_id TTL cache. seen_event_ids + expiry_ts (placeholder)."""

    def __init__(self, ttl_sec: float = 60.0):
        self._seen: dict = {}           # event_id -> expiry_ts (epoch)
        self._ttl: float = float(ttl_sec)

    def _purge(self):
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if v > now}

    def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        self._purge()
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        if not event_id:
            return
        self._seen[event_id] = time.time() + self._ttl

    def __len__(self) -> int:
        self._purge()
        return len(self._seen)


# 모듈 단일 인스턴스 (미연결 — STEP-2F-3 에서 dispatch 경로에 통합)
_dedup_cache = DedupCache(ttl_sec=60.0)


# ═══════════════════════════════════════════════════════════════
# PID 생존 검사 (Windows kernel32)
# ═══════════════════════════════════════════════════════════════
_PROCESS_QUERY_INFORMATION         = 0x0400
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # [N14] Vista+ 권장 (낮은 권한, 보안 강화 환경 호환)
_STILL_ACTIVE                      = 259  # Windows GetExitCodeProcess: 살아있을 때 반환값


def is_pid_alive(pid: int) -> bool:
    """Windows GetExitCodeProcess 기반 PID 생존 검사.

    OpenProcess 만으로 판단 시 zombie/recently-terminated process 에
    대해 핸들이 반환되어 alive 로 오판되는 문제 회피.

    [N14 2026-05-14] PROCESS_QUERY_LIMITED_INFORMATION(0x1000) 우선 시도.
    Vista+ 에서 GetExitCodeProcess 호출에 충분 + 보안 강화 환경에서도 권한 확보.
    실패 시 기존 PROCESS_QUERY_INFORMATION(0x0400) fallback.
    """
    if pid <= 0:
        return False
    h = None
    try:
        h = ctypes.windll.kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not h:
            # [N14] Vista 미만 또는 권한 부족 fallback
            h = ctypes.windll.kernel32.OpenProcess(
                _PROCESS_QUERY_INFORMATION, False, pid
            )
        if not h:
            return False
        exit_code = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetExitCodeProcess(
            h, ctypes.byref(exit_code)
        )
        if not ok:
            return False
        return exit_code.value == _STILL_ACTIVE
    except Exception:
        return False
    finally:
        if h:
            try:
                ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# 단일 실행 Lock (broker_gateway.lock)
# ═══════════════════════════════════════════════════════════════
def acquire_singleton_lock() -> bool:
    """단일 broker 실행 보장.

    반환:
        True  — lock 획득 성공 (진행 가능)
        False — 이미 다른 broker 실행 중 (즉시 종료해야 함)
    """
    if LOCK_FILE.exists():
        try:
            existing_pid = int(LOCK_FILE.read_text(encoding="utf-8-sig").strip())
        except Exception:
            existing_pid = 0

        if existing_pid > 0 and is_pid_alive(existing_pid):
            logger.error(
                "another broker already running (PID=%d) — Broker 종료",
                existing_pid,
            )
            return False

        # stale lock
        logger.warning(
            "stale lock 발견 (PID=%d, 사망) — 제거 후 진행",
            existing_pid,
        )
        try:
            LOCK_FILE.unlink()
        except Exception as e:
            logger.error("stale lock 제거 실패: %s", e)
            return False

    # 새 lock 쓰기
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        logger.info("lock 획득 PID=%d → %s", os.getpid(), LOCK_FILE)
    except Exception as e:
        logger.error("lock 쓰기 실패: %s", e)
        return False

    # 종료 시 lock 자동 제거
    atexit.register(release_singleton_lock)
    return True


def release_singleton_lock():
    """종료 시 lock 제거 (현재 PID 소유인 경우만)."""
    # [K1 2026-05-21 Path α] atexit 발화 시 heartbeat state=SHUTDOWN 작성 시도 — broker 종료 시 state=CONNECTED 거짓 표시 차단
    # 한계: kill -9 / OS 강제 종료 / segfault crash 시는 atexit 미발화 → 보강 불가 (5/21 broker 3차 사망 시 발견된 결함 일부 보강)
    try:
        global _broker_instance
        if _broker_instance is not None:
            try:
                if _broker_instance.state != BrokerState.SHUTDOWN:
                    _broker_instance.set_state(BrokerState.SHUTDOWN, reason="atexit_shutdown")
                _broker_instance.write_heartbeat()
                logger.info("[K1] atexit heartbeat state=SHUTDOWN 작성 완료 (PID=%d)", os.getpid())
            except Exception as e:
                logger.error("[K1] atexit heartbeat 작성 오류: %s", e)
    except Exception:
        pass

    try:
        if not LOCK_FILE.exists():
            return
        try:
            owner_pid = int(LOCK_FILE.read_text(encoding="utf-8-sig").strip())
        except Exception:
            owner_pid = 0
        if owner_pid == os.getpid():
            LOCK_FILE.unlink()
            logger.info("lock 제거 완료 (own PID=%d)", os.getpid())
    except Exception as e:
        logger.error("lock 제거 오류: %s", e)


# ═══════════════════════════════════════════════════════════════
# Graceful shutdown (SIGINT / SIGTERM handler)
# ═══════════════════════════════════════════════════════════════
_broker_instance = None  # main() 에서 BrokerGateway 인스턴스 주입


def _signal_handler(signum, frame):
    """SIGINT / SIGTERM 수신 시 graceful shutdown."""
    try:
        sig_name = signal.Signals(signum).name
    except Exception:
        sig_name = str(signum)
    logger.info("shutdown signal received: %s", sig_name)

    try:
        if _broker_instance is not None:
            # [N21 2026-05-14] N20 reason 활성화 — shutdown 사유 명시
            _broker_instance.set_state(BrokerState.SHUTDOWN, reason=f"signal:{sig_name}")
            _broker_instance.write_heartbeat()
    except Exception as e:
        logger.error("signal handler state/heartbeat 오류: %s", e)

    try:
        release_singleton_lock()
    except Exception as e:
        logger.error("signal handler lock 제거 오류: %s", e)

    try:
        from PyQt5.QtWidgets import QApplication as _QA
        _app = _QA.instance()
        if _app is not None:
            _app.quit()
    except Exception as e:
        logger.error("signal handler QApplication.quit 오류: %s", e)


# ═══════════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════════
class BrokerState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING   = "CONNECTING"
    LOGIN_WAIT   = "LOGIN_WAIT"
    CONNECTED    = "CONNECTED"
    RATE_LIMIT   = "RATE_LIMIT"
    SHUTDOWN     = "SHUTDOWN"


# ═══════════════════════════════════════════════════════════════
# Broker Gateway
# ═══════════════════════════════════════════════════════════════
class BrokerGateway:
    """Kiwoom OCX Ownership Firewall — 단일 소유 + IPC dispatcher."""

    # [STEP-2B-1] opt10080 collector TR_TIMEOUT_MS=12000 호환 (10 → 12)
    # [5.14B 2026-05-19] OCX 측 일부 TR 12s+ 처리 → broker QTimer cutoff 정확 12s = client 100% TIMEOUT.
    #   broker 20s + collector 25s 묶음으로 broker timeout 50~80% ↓ 예상. rollback: 20 → 12.
    TR_TIMEOUT_SEC        = 20
    HEARTBEAT_INTERVAL_MS = 5_000
    POLL_INTERVAL_MS      = 500
    DEFAULT_TTL_SEC       = 30

    def __init__(self):
        self.app: QApplication = None
        self.ocx: QAxWidget    = None
        self.state             = BrokerState.DISCONNECTED

        self.login_loop: QEventLoop = None
        self.tr_loop: QEventLoop    = None

        self.start_ts          = time.time()
        self.tr_count          = 0
        self.rate_limit_until  = None
        self.last_request_id   = None
        self.last_request_ts   = None

        # TR 응답 buffer: rqname → data dict
        self.tr_data_buffer = {}
        # [STEP-2A] 현재 TR 요청에서 추출할 컬럼 목록 (OnReceiveTrData 콜백이 참조)
        self.tr_output_fields: list = []
        # [Phase 1.2 2026-05-14] rqname → request_id mapping (관측/진단 + 미래 worker thread 확장 base).
        # 현재 single-thread 라 race 0 — 본 dict 는 observability 용도 (log + 향후 buffer key 마이그레이션 기반).
        # 동시 동일 rqname 두 요청 발생 시 후순위 가 선순위 덮어씀 (현 broker single-thread 라 발생 불가).
        self.tr_pending_rqname: dict = {}  # rqname → {"request_id": str, "start_ts": float}

        self._heartbeat_timer = None
        self._poll_timer      = None
        # [Z2 2026-05-14] state replay — SetRealReg 등록 상태 영속화
        # key = screen_no, value = {"code_list": "035720;...", "fid_list": "10;13;...", "real_type": "0", "ts": ...}
        self._realreg_state: dict = {}

    # ───────────────────────────────────────────────────────────
    # State transition
    # ───────────────────────────────────────────────────────────
    def set_state(self, new_state: BrokerState, reason: str = ""):
        # [N20 2026-05-14] reason 인자 추가 — caller 가 상태 변화 이유 명시 가능 (default "").
        # 기존 호출처는 reason 미지정 = 호환. 후속 패치에서 set_state(state, reason="...") 로 진단 강화.
        old = self.state
        self.state = new_state
        if reason:
            logger.info("STATE: %s → %s (reason=%s)", old.value, new_state.value, reason)
        else:
            logger.info("STATE: %s → %s", old.value, new_state.value)

    # ───────────────────────────────────────────────────────────
    # Heartbeat
    # ───────────────────────────────────────────────────────────
    def write_heartbeat(self):
        try:
            # [STEP-2F-5] backlog 관측 — cleanup 정책 미변경, 측정만
            try:
                shadow_backlog     = sum(1 for _ in IPC_ORDER_SHADOW_DIR.glob("*.json"))
            except Exception:
                shadow_backlog = -1
            try:
                shadow_ack_backlog = sum(1 for _ in IPC_ORDER_SHADOW_ACK_DIR.glob("*.json"))
            except Exception:
                shadow_ack_backlog = -1
            try:
                chejan_backlog     = sum(1 for _ in IPC_CHEJAN_DIR.glob("*.json"))
            except Exception:
                chejan_backlog = -1
            hb = {
                "ts": datetime.now().isoformat(),
                "state": self.state.value,
                "pid": os.getpid(),
                "uptime_sec": int(time.time() - self.start_ts),
                "tr_count": self.tr_count,
                "rate_limit_until": self.rate_limit_until,
                "last_request_id": self.last_request_id,
                "last_request_ts": self.last_request_ts,
                # [STEP-2F-5] backlog observability
                "shadow_backlog":     shadow_backlog,
                "shadow_ack_backlog": shadow_ack_backlog,
                "chejan_backlog":     chejan_backlog,
            }
            tmp = HB_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(hb, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(HB_FILE))
        except Exception as e:
            # [N7-HB-CRITICAL 2026-05-14] heartbeat 쓰기 실패 시 critical + traceback.
            # HB 실패 = sub-process 측 _is_broker_alive 가 stale 판정 → broker 사용 안 함 → popup 폭주 회귀 위험.
            # 따라서 명시적 critical 로그 + exc_info traceback 으로 즉시 진단 가능.
            logger.critical("[HB-FAIL] heartbeat 쓰기 실패: %s", e, exc_info=True)
        # [STEP-2F-3] chejan_events 정기 청소
        self._cleanup_old_chejan_events()

    # ───────────────────────────────────────────────────────────
    # Qt + OCX 초기화
    # ───────────────────────────────────────────────────────────
    def setup_qt(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.ocx.OnEventConnect.connect(self._on_event_connect)
        self.ocx.OnReceiveTrData.connect(self._on_receive_tr_data)
        # [STEP-2F-3 2026-05-13] Chejan paper-mode broadcast hook
        self.ocx.OnReceiveChejanData.connect(self._on_receive_chejan_data)
        # [N15 2026-05-14] 키움 시스템 메시지 broadcast (STEP-3.1/3.2 사전 준비, 현재 효과 0)
        self.ocx.OnReceiveMsg.connect(self._on_receive_msg)
        # [C1 2026-05-14] 실시간 시세 broadcast (SIGA sell register_rt 등을 broker IPC 로 이전 시 사용)
        self.ocx.OnReceiveRealData.connect(self._on_receive_real_data)
        logger.info(
            "QAxWidget 생성 + 이벤트 핸들러 연결 완료 "
            "(EventConnect/TrData/ChejanData/Msg/RealData)"
        )

    # ───────────────────────────────────────────────────────────
    # CommConnect (로그인)
    # ───────────────────────────────────────────────────────────
    def connect_kiwoom(self):
        self.set_state(BrokerState.CONNECTING, reason="connect_kiwoom 진입")
        logger.info("CommConnect() 호출 — 로그인창 출력 예정")
        self.set_state(BrokerState.LOGIN_WAIT, reason="CommConnect 호출 직전")

        self.login_loop = QEventLoop()
        ret = self.ocx.dynamicCall("CommConnect()")
        if ret != 0:
            logger.error("CommConnect() 동기 반환 오류 ret=%s", ret)
            self.set_state(BrokerState.DISCONNECTED, reason=f"CommConnect ret={ret}")
            return

        # [N23+GPT-FIX-5 2026-05-14] login_loop 90s timeout (GPT 검토: 300s 과도 → 60~90s).
        # 사용자 LOGIN popup 미클릭 시 무한 hang 방지 + 장애 회복 속도 확보.
        _login_timeout = QTimer()
        _login_timeout.setSingleShot(True)
        _login_timeout.timeout.connect(self.login_loop.quit)
        _login_timeout.start(90_000)  # 90초 (GPT-FIX-5)

        # OnEventConnect 가 호출되면 login_loop.exit()
        self.login_loop.exec_()
        _login_timeout.stop()

        # [N23] timeout 후 GetConnectState 검사 (run() 측에서 state != CONNECTED 시 종료)
        if self.state != BrokerState.CONNECTED:
            logger.critical("[N23-TIMEOUT] login_loop 300s 경과 또는 LOGIN 실패 (state=%s)", self.state.value)

    def _on_event_connect(self, err_code):
        logger.info("OnEventConnect err_code=%s", err_code)
        if err_code == 0:
            self.set_state(BrokerState.CONNECTED)
        else:
            logger.error("로그인 실패 err_code=%s", err_code)
            self.set_state(BrokerState.DISCONNECTED)
        if self.login_loop and self.login_loop.isRunning():
            self.login_loop.exit()

    # ───────────────────────────────────────────────────────────
    # OnReceiveTrData (TR 응답)
    # ───────────────────────────────────────────────────────────
    def _on_receive_tr_data(self, screen_no, rqname, tr_code,
                            record_name, prev_next, *args):
        logger.info(
            "OnReceiveTrData rqname=%s tr_code=%s screen_no=%s",
            rqname, tr_code, screen_no,
        )
        try:
            record_count_raw = self.ocx.dynamicCall(
                "GetRepeatCnt(QString, QString)", tr_code, rqname
            )
            record_count = int(record_count_raw) if record_count_raw else 0

            # [STEP-2A] output_fields 가 지정된 경우 GetCommData 로 records 추출.
            #   - multi-record TR (record_count > 0): record_count 만큼 row
            #   - single-record TR (record_count == 0): 1 row (index=0) 추출 시도
            records: list = []
            fields = list(self.tr_output_fields or [])
            if fields:
                iter_count = record_count if record_count > 0 else 1
                for i in range(iter_count):
                    rec = {}
                    for field in fields:
                        try:
                            val = self.ocx.dynamicCall(
                                "GetCommData(QString,QString,int,QString)",
                                tr_code, rqname, i, field,
                            )
                            rec[field] = val.strip() if val else ""
                        except Exception as ge:
                            rec[field] = ""
                            logger.error(
                                "GetCommData 오류 field=%s i=%d: %s",
                                field, i, ge,
                            )
                    records.append(rec)

            self.tr_data_buffer[rqname] = {
                "tr_code": tr_code,
                "screen_no": screen_no,
                "record_name": record_name,
                "prev_next": prev_next,
                "record_count": record_count,
                "records": records,
                "ts": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error("TR data 처리 오류: %s", e)
            self.tr_data_buffer[rqname] = {"error": str(e), "records": []}
        finally:
            if self.tr_loop and self.tr_loop.isRunning():
                self.tr_loop.exit()

    # ───────────────────────────────────────────────────────────
    # OnReceiveChejanData (체결/잔고 콜백) — STEP-2F-3 paper broadcast
    # ───────────────────────────────────────────────────────────
    def _on_receive_chejan_data(self, gubun, item_cnt, fid_list):
        """[STEP-2F-3] Chejan callback → IPC/chejan_events/{event_id}.json 단방향 broadcast.

        주문 처리/상태머신 연결 금지. file write + log 만 수행.
        """
        ts_callback = datetime.now()
        event_id = str(_bro_uuid_v1.uuid4())

        try:
            logger_chejan.info(
                "OnReceiveChejanData gubun=%s item_cnt=%s event_id=%s",
                gubun, item_cnt, event_id,
            )

            # 7개 FID 최소셋 추출
            fid_data = {}
            for fid in CHEJAN_FIDS.keys():
                try:
                    val = self.ocx.dynamicCall(
                        "GetChejanData(int)", [int(fid)]
                    )
                    fid_data[fid] = str(val).strip() if val else ""
                except Exception as ge:
                    fid_data[fid] = ""
                    logger_chejan.error(
                        "GetChejanData FID=%s 오류: %s", fid, ge
                    )

            # 디버그 로그 (주요 필드만)
            logger_chejan.info(
                "event_id=%s order_no=%s state=%s code=%s qty=%s remain=%s otype=%s",
                event_id,
                fid_data.get("9203", ""),
                fid_data.get("913", ""),
                fid_data.get("9001", ""),
                fid_data.get("911", ""),
                fid_data.get("902", ""),
                fid_data.get("905", ""),
            )

            # [FILL-REC 2026-07-13 친구님 "체결가 기록 배선해"] ★실제 체결가(FID910) 영구 기록.
            #   Why: 매매기(money_flow_exec)에 체결 처리가 한 줄도 없어 buy_price = '주문 낼 때의 현재가'(지시가)일 뿐,
            #        실제 체결가는 어디에도 안 남았다 → 슬리피지를 한 번도 측정한 적이 없다.
            #        chejan_events/*.json 은 janitor가 지워서 사후 대조 불가(오늘 0개).
            #   → 안 지워지는 LOG에 누적 CSV. 이 값 vs 장부 buy_price(지시가) = 슬리피지.
            #   ★기록 전용 — 주문/상태머신 무관. 실패해도 체결 처리에 영향 없음(독립 try).
            #   중요: 건당 20만→166만(8배) 확대 시점이라, 이 수치가 전략 생사(손익분기 왕복 0.98%)를 가른다.
            #   gubun "0"=주문체결통보(체결가 있음) / "1"=잔고통보(체결가 없음) → 0만 기록.
            try:
                if str(gubun) == "0" and fid_data.get("910", ""):
                    _fp = LOG_DIR / f"fills_{ts_callback.strftime('%Y%m%d')}.csv"
                    _new = not _fp.exists()
                    with open(str(_fp), "a", encoding="utf-8", newline="") as _f:
                        _w = _csv.writer(_f)
                        if _new:
                            _w.writerow(["ts", "code", "order_no", "state",
                                         "otype", "fill_qty", "fill_px", "remain"])
                        _w.writerow([
                            ts_callback.strftime("%Y-%m-%d %H:%M:%S"),
                            str(fid_data.get("9001", "")).lstrip("A"),
                            fid_data.get("9203", ""),
                            fid_data.get("913", ""),
                            fid_data.get("905", ""),
                            fid_data.get("911", ""),
                            fid_data.get("910", ""),
                            fid_data.get("902", ""),
                        ])
            except Exception as _fe:
                logger_chejan.error("[FILL-REC] 체결가 기록 실패: %s", _fe)

            ts_write = datetime.now()
            event = {
                "event_id":             event_id,
                "ts":                   ts_write.isoformat(),
                "ts_broker_callback":   ts_callback.isoformat(),
                "ts_subscriber_consume": "",
                "gubun":                str(gubun),
                "fid_data":             fid_data,
            }

            event_path = IPC_CHEJAN_DIR / f"{event_id}.json"
            tmp = event_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(event_path))

            # [CYCLE-6 2026-05-21] event_journal CHEJAN_RECEIVED emit
            _emit_event("CHEJAN_RECEIVED", entity="order", entity_id=event_id, payload={
                "gubun": str(gubun),
                "order_no": fid_data.get("9203", ""),
                "state": fid_data.get("913", ""),
                "code": fid_data.get("9001", ""),
                "qty": fid_data.get("911", ""),
                "remain": fid_data.get("902", ""),
                "ts_callback": ts_callback.isoformat(),
            })

            # latency 측정 (callback → write)
            try:
                latency_ms = (ts_write - ts_callback).total_seconds() * 1000.0
                backlog = sum(1 for _ in IPC_CHEJAN_DIR.glob("*.json"))
                logger_latency.info(
                    "broker_write event_id=%s callback_to_write_ms=%.1f backlog=%d",
                    event_id, latency_ms, backlog,
                )
            except Exception:
                pass

            # [STEP-2F-4] order_shadow_ack relay — 별도 채널에 ACK/FILL 사본
            try:
                relay = {
                    "event_id":           event_id,
                    "ts_broker_relay":    datetime.now().isoformat(),
                    "ts_broker_callback": ts_callback.isoformat(),
                    "gubun":               str(gubun),
                    "fid_data":            fid_data,
                    "order_no":            fid_data.get("9203", ""),
                    "state":               fid_data.get("913", ""),
                    "code":                fid_data.get("9001", ""),
                    "filled_qty":          fid_data.get("911", ""),
                    "filled_price":        fid_data.get("910", ""),
                    "remain_qty":          fid_data.get("902", ""),
                    "order_direction":     fid_data.get("905", ""),
                }
                relay_path = IPC_ORDER_SHADOW_ACK_DIR / f"{event_id}.json"
                tmp2 = relay_path.with_suffix(".tmp")
                tmp2.write_text(
                    json.dumps(relay, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(str(tmp2), str(relay_path))
                logger_order_shadow.info(
                    "ack_relay event_id=%s order_no=%s state=%s code=%s remain=%s",
                    event_id, relay["order_no"], relay["state"],
                    relay["code"], relay["remain_qty"],
                )
                # [STEP-2F-5] ACK relay backlog warning (drop/차단 금지)
                try:
                    ack_backlog = sum(
                        1 for _ in IPC_ORDER_SHADOW_ACK_DIR.glob("*.json")
                    )
                    if ack_backlog > 100:
                        logger_order_shadow.warning(
                            "ACK_RELAY_BACKLOG_HIGH count=%d (>100) "
                            "event_id=%s order_no=%s",
                            ack_backlog, event_id, relay["order_no"],
                        )
                except Exception:
                    pass
            except Exception as re:
                logger_chejan.error(
                    "order_shadow_ack relay 오류 event_id=%s: %s", event_id, re
                )

        except Exception as e:
            logger_chejan.error(
                "chejan broadcast 오류 event_id=%s: %s", event_id, e
            )

    # [C1 2026-05-14] OnReceiveRealData → IPC broadcast
    # 키움 OCX 실시간 시세 콜백. broker 가 보유 = sub-process 가 broker IPC 로 구독 가능.
    # 현재 sub-process 가 자체 OCX SetRealReg 사용 = broker broadcast 미구독 = 효과 0.
    # STEP-3.1/3.2 (SIGA sell mandatory 화) 시점에 sub-process 가 broker IPC 로 전환 가능.
    # FID 등록 필요 (정확한 fid 목록은 sub-process 가 SETREAL_REG 시 지정).
    _REAL_DATA_FID_MIN = {
        "10":  "현재가",
        "11":  "전일대비",
        "12":  "등락율",
        "13":  "누적거래량",
        "15":  "거래량",
        "16":  "시가",
        "17":  "고가",
        "18":  "저가",
        "27":  "(최우선)매도호가",
        "28":  "(최우선)매수호가",
    }

    # [GPT-FIX-2 2026-05-14] 실시간 데이터 file IPC 부하 차단 throttle.
    # 활발 종목 초당 수십~수백건 콜백 가능 → file write 폭주 + disk I/O 폭증 위험.
    # 종목별 100ms throttle = 최대 10건/초/종목. 60종목 등록 시 ~600건/초 상한.
    # 향후 batch/ring-buffer/shared-memory 적용 시 throttle 해제 가능 (별도 사이클).
    _REAL_DATA_THROTTLE_MS = 100
    _real_data_last_ts: dict = {}  # code → last write ts (epoch ms)
    _real_data_dropped_count: dict = {}  # code → throttle 로 drop 된 콜백 카운트

    # [REAL-MICRO 2026-06-24] 실시간 마이크로구조 구독 상태/메서드
    _micro_snapshot: dict = {}        # code -> {ts, che_str, ask_tot, bid_tot, imb, cur, cum_vol}
    # [OB-FIX 2026-07-13] set → list. 등록 순서(우선순위)가 화면 분할에 그대로 쓰이므로 순서를 잃으면 안 됨.
    _micro_watch_codes: list = []
    _micro_screens: list = []         # 현재 실시간 등록에 쓰고 있는 화면번호(줄었을 때 해제용)
    _micro_last_upd: dict = {}        # code -> last update epoch ms (per-code throttle)
    _micro_verify_logged: int = 0

    def _read_micro_watch(self):
        # [REAL-MICRO 2026-06-24] 다중 소비자: micro_watch*.json (돌파/눌림/종가/스캐너) 전부 합집합 — 전략별 파일 충돌방지
        # [CAP-PRIORITY 2026-07-04 친구님] ★120캡을 set 무작위로 자르면 strategy(EOD 거래대금 100=바닥커버)·반전후보가
        #   상승주 리스트에 밀려 무작위 탈락 → 급락 바닥 구간 체결강도 통째로 누락(170920 오전 09:03~13:01).
        #   해결: 우선순위 확정 컷 — ①반전 바닥워치 ②전략 유니버스(매일 갱신 100) ③나머지(상승/돌파/종가/스캐너).
        #   strategy_watchlist.py가 "급락 바닥 시간에도 체결강도 계속 찍히게" 발행한 100을 캡이 도로 버리던 걸 살림.
        #   롤백(기존 무작위 컷) setx MICRO_CAP_PRIORITY NO.
        CAP = 120
        if os.environ.get("MICRO_CAP_PRIORITY", "YES").strip().upper() != "YES":
            codes = set()
            try:
                for f in IPC_DIR.glob("micro_watch*.json"):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8-sig"))
                        for c in (d.get("codes") or []):
                            codes.add(str(c).zfill(6))
                    except Exception:
                        pass
            except Exception:
                pass
            return list(codes)[:CAP]
        # ── 우선순위 확정 컷 ──
        def _codes_of(name):
            try:
                d = json.loads((IPC_DIR / name).read_text(encoding="utf-8-sig"))
                return [str(c).zfill(6) for c in (d.get("codes") or [])]
            except Exception:
                return []
        out, seen = [], set()
        def _add(lst):
            for c in lst:
                if len(out) >= CAP:
                    break
                if c and len(c) == 6 and c not in seen:
                    seen.add(c); out.append(c)
        # ★[7/12 친구님 "매도 폭탄이 서서히 줄다가 바닥"] ①돈맥 급락종목 최우선 — 실전 매수 엔진이 깊은바닥 하나뿐인데
        #   정작 그 후보들의 호가잔량이 46~65% 결측이었다(reversal 파일은 7/11 엔진잠금으로 소멸·돈맥은 발행한 적 없음).
        #   micro_watch_moneyflow.json = money_flow_board_v1._publish_micro_watch (하락 -2%↓ 낙폭순 60개·30s 갱신)
        PRIOR = ["micro_watch_moneyflow.json",      # ①돈맥 급락종목(실전 매수 후보) ★최우선
                 "micro_watch_reversal.json",       # ②반전 바닥(현재 엔진 잠금 = 파일 없음·복구 대비 유지)
                 "micro_watch_strategy.json"]       # ③전략 EOD100(바닥커버)
        _add(_codes_of(PRIOR[0]))
        _add(_codes_of(PRIOR[1]))
        try:
            for f in sorted(IPC_DIR.glob("micro_watch*.json")):            # ③나머지(남는 자리만)
                if f.name in PRIOR:
                    continue
                _add(_codes_of(f.name))
        except Exception:
            pass
        return out      # [OB-FIX 2026-07-13] 우선순위 순서 그대로(돈맥 깊은바닥이 맨 앞) — 화면 분할이 이 순서를 씀

    def _micro_register(self, codes):
        """[OB-FIX 2026-07-13] 화면당 MICRO_CHUNK(90)씩 분할 등록 — 키움 화면당 100종목 한계 회피.

        기존: sorted(codes) 를 화면 1개에 몰아넣음 → 100 초과분이 조용히 잘림 + 정렬 때문에
              우선순위(돈맥 깊은바닥 최우선)가 무의미해지고 '코드번호 큰 종목'이 잘려나갔다.
        지금: 우선순위 순서를 유지한 채 앞에서부터 90개씩 잘라 화면 9300·9301·… 에 나눠 등록.
              → 깊은바닥 후보 60개는 항상 첫 화면 = 절대 안 잘림.
        """
        try:
            ordered = [c for c in codes]                     # 우선순위 순서 유지(정렬 금지)
            size    = max(1, MICRO_CHUNK)
            chunks  = [ordered[i:i + size] for i in range(0, len(ordered), size)] or [[]]
            used    = []
            for i, ch in enumerate(chunks):
                scr = str(int(MICRO_SCREEN) + i)
                # optType "0" = 그 화면의 기존등록 교체(마이크로 전용 화면이라 타 등록 무간섭)
                ret = self.ocx.dynamicCall(
                    "SetRealReg(QString, QString, QString, QString)",
                    scr, ";".join(ch), MICRO_FIDS, "0")
                used.append(scr)
                # ★[7/17 진단] 반환값 로그 — 0=성공, 음수=키움 거부(지금까지 버려져서 거부도 성공처럼 보였음)
                logger.info("[MICRO] SetRealReg %d종목 (screen=%s) ret=%s", len(ch), scr, ret)
            # 종목수가 줄어 안 쓰게 된 화면은 해제(잔여 실시간 스트림 정리)
            for scr in [s for s in self._micro_screens if s not in used]:
                try:
                    self.ocx.dynamicCall("DisconnectRealData(QString)", scr)
                    logger.info("[MICRO] 화면 해제 %s", scr)
                except Exception:
                    pass
            self._micro_screens = used
            logger.info("[MICRO] 등록 합계 %d종목 / 화면 %d개 (chunk=%d)",
                        len(ordered), len(used), size)
        except Exception as e:
            logger.error("[MICRO] SetRealReg 실패: %s", e)

    def _micro_update(self, code, real_type):
        code = str(code)
        now_ms = time.time() * 1000.0
        if now_ms - self._micro_last_upd.get(code, 0.0) < MICRO_THROTTLE_MS:
            return
        self._micro_last_upd[code] = now_ms
        def _g(fid):
            try:
                v = self.ocx.dynamicCall("GetCommRealData(QString, int)", code, int(fid))
                return str(v).strip() if v is not None else ""
            except Exception:
                return ""
        def _num(s):
            try:
                return abs(float(str(s).replace(",", "").lstrip("+").lstrip("-")))
            except Exception:
                return None
        rec = self._micro_snapshot.get(code) or {}
        rt = str(real_type)
        if "체결" in rt:
            che = _num(_g("228"))
            if che is not None: rec["che_str"] = che
            cur = _num(_g("10"))
            if cur is not None: rec["cur"] = cur
            cv = _num(_g("13"))
            if cv is not None: rec["cum_vol"] = cv
        if "호가" in rt:
            ask = _num(_g("121")); bid = _num(_g("125"))
            if ask is not None: rec["ask_tot"] = ask
            if bid is not None: rec["bid_tot"] = bid
            if rec.get("ask_tot") and rec.get("bid_tot"):
                rec["imb"] = round(rec["bid_tot"] / rec["ask_tot"], 3) if rec["ask_tot"] > 0 else 0.0
                # [OB-FIX 2026-07-13] 호가 전용 시각 — rec["ts"]는 체결에도 갱신돼서 호가가 죽어도 신선해 보인다.
                #   imb는 한번 쓰이면 안 지워지므로(rec 재사용) 낡은 호가를 구분할 방법이 없었다.
                #   ★기록만 한다 — 진입 판정에는 안 씀(친구님: "호가 없으면 안 산다"→"가격 맞으면 사자").
                rec["ob_ts"] = datetime.now().isoformat()
        rec["ts"] = datetime.now().isoformat()
        self._micro_snapshot[code] = rec
        # ★1단계 검증: 체결강도 실제 값이 실시간으로 오는지 첫 15건 로그(opt10001=빈값과 대조)
        if self._micro_verify_logged < 15 and rec.get("che_str"):
            logger.info("[MICRO-VERIFY] %s 체결강도=%s 현재가=%s 매도총=%s 매수총=%s imb=%s",
                        code, rec.get("che_str"), rec.get("cur"), rec.get("ask_tot"),
                        rec.get("bid_tot"), rec.get("imb"))
            self._micro_verify_logged += 1

    def _micro_flush(self):
        if not self._micro_snapshot:
            return
        try:
            snap = {"ts": datetime.now().isoformat(), "codes": self._micro_snapshot}
            tmp = MICRO_SNAPSHOT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(MICRO_SNAPSHOT_FILE))
        except Exception as e:
            logger.error("[MICRO] flush 실패: %s", e)

    def _micro_tick(self):
        if not REAL_MICRO_ON:
            return
        try:
            codes = self._read_micro_watch()
            if codes and codes != self._micro_watch_codes:
                self._micro_register(codes)
                self._micro_watch_codes = codes
            self._micro_flush()
        except Exception as e:
            logger.error("[MICRO] tick 오류: %s", e)

    def _on_receive_real_data(self, code, real_type, real_data):
        """[C1 + GPT-FIX-2 2026-05-14] 실시간 시세 콜백 → IPC/real_data/{event_id}.json broadcast.

        주문 처리/상태머신 미연결. read-only broadcast.
        Sub-process 는 IPC/real_data/ 폴링 후 자기 등록 종목만 필터.

        [GPT-FIX-2] 종목별 100ms throttle 적용. throttle 통과 콜백만 file write.
        Drop 된 콜백은 카운트만 누적, 로그는 100건/종목당 1회 출력.
        """
        # ★[7/17 진단] 콜백 자체가 오는지 첫 5건만 확인용 로그
        n = getattr(self, "_ordr_diag_count", 0) + 1
        self._ordr_diag_count = n
        if n <= 5:
            logger.info("[MICRO-DIAG] _on_receive_real_data 호출됨 #%d code=%s real_type=%s", n, code, real_type)
        # [REAL-MICRO 2026-06-24] 실시간 마이크로구조 갱신(체결강도228/호가총잔량121·125) — env REAL_MICRO=ON 시만
        if REAL_MICRO_ON:
            try:
                self._micro_update(code, real_type)
            except Exception as e:
                logger.error("[MICRO] update 실패 code=%s real_type=%s: %s", code, real_type, e)
        # [REALDATA-OFF 2026-06-02] broadcast 무용(L738: sub-process가 자체 OCX SetRealReg 구독 = broker
        #   broadcast 미사용 = 효과0) + I/O부하(real_data 5778파일/매5초 100개 청소 → broker TR응답 지연
        #   → collector 사이클 86s 의심). 기본 비활성으로 I/O 제거. env REAL_DATA_BROADCAST=ON 복구.
        #   순수 read-only broadcast라 주문/체결/매도 전혀 무관.
        if os.environ.get("REAL_DATA_BROADCAST", "OFF").strip().upper() != "ON":
            return
        try:
            now_ms = time.time() * 1000.0
            last_ms = self._real_data_last_ts.get(code, 0.0)
            if now_ms - last_ms < self._REAL_DATA_THROTTLE_MS:
                cnt = self._real_data_dropped_count.get(code, 0) + 1
                self._real_data_dropped_count[code] = cnt
                if cnt % 100 == 0:
                    logger.info(
                        "[REAL-THROTTLE] code=%s drop=%d (100ms throttle)",
                        code, cnt,
                    )
                return
            self._real_data_last_ts[code] = now_ms

            event_id = str(_bro_uuid_v1.uuid4())
            fid_data = {}
            for fid in self._REAL_DATA_FID_MIN.keys():
                try:
                    val = self.ocx.dynamicCall(
                        "GetCommRealData(QString, int)", code, int(fid)
                    )
                    fid_data[fid] = str(val).strip() if val else ""
                except Exception:
                    fid_data[fid] = ""
            event = {
                "event_id":  event_id,
                "ts":        datetime.now().isoformat(),
                "code":      str(code),
                "real_type": str(real_type),
                "fid_data":  fid_data,
            }
            event_path = IPC_REAL_DATA_DIR / f"{event_id}.json"
            tmp = event_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(event_path))
        except Exception as e:
            logger.error("OnReceiveRealData broadcast 오류 code=%s: %s", code, e)

    def _on_receive_msg(self, screen_no, rqname, tr_code, msg):
        """[N15 2026-05-14] OnReceiveMsg → IPC/msg_events/{event_id}.json broadcast.

        키움 시스템 메시지 (예: '주문 가능 시간이 아닙니다', 'TR 수신 실패' 등).
        주문 처리/상태머신 연결 금지. file write + log only.
        STEP-3.1/3.2 적용 시 sub-process 가 구독하여 주문 거부 메시지 수신 가능.
        """
        try:
            event_id = str(_bro_uuid_v1.uuid4())
            event = {
                "event_id":  event_id,
                "ts":        datetime.now().isoformat(),
                "screen_no": str(screen_no),
                "rqname":    str(rqname),
                "tr_code":   str(tr_code),
                "msg":       str(msg),
            }
            event_path = IPC_MSG_EVENTS_DIR / f"{event_id}.json"
            tmp = event_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(event_path))
            logger.info(
                "[KIWOOM-MSG] screen=%s rqname=%s tr=%s msg=%s",
                screen_no, rqname, tr_code, msg,
            )
        except Exception as e:
            logger.error("OnReceiveMsg broadcast 오류: %s", e)

    def _cleanup_old_chejan_events(self):
        """[STEP-2F-3/4 + N1 2026-05-14] 오래된 IPC event/response 파일 정기 청소.

        대상:
          - IPC/chejan_events/*.json
          - IPC/order_shadow/*.json
          - IPC/order_shadow_ack/*.json
          - IPC/responses/*.json  ← [N1] 추가 (client timeout/crash 시 orphan 누적 차단)
          - IPC/requests/*.json   ← [N1] 추가 (broker 비정상 종료 후 잔존 차단, TTL 짧음)
        TTL: CHEJAN_EVENT_TTL_SEC (300s) — requests/responses 도 동일 300s.
        정상 클라이언트는 request → response 짝을 60s 내에 unlink. 300s 잔존은 orphan.
        """
        try:
            now_ts = time.time()
            for label, dirpath in (
                ("chejan_events",    IPC_CHEJAN_DIR),
                ("order_shadow",     IPC_ORDER_SHADOW_DIR),
                ("order_shadow_ack", IPC_ORDER_SHADOW_ACK_DIR),
                ("responses",        IPC_RES),
                ("requests",         IPC_REQ),
                ("msg_events",       IPC_MSG_EVENTS_DIR),  # [N15] 시스템 메시지 broadcast 청소
                ("real_data",        IPC_REAL_DATA_DIR),   # [C1] 실시간 시세 broadcast 청소
            ):
                removed = 0
                try:
                    for fp in dirpath.glob("*.json"):
                        try:
                            if now_ts - fp.stat().st_mtime > CHEJAN_EVENT_TTL_SEC:
                                fp.unlink()
                                removed += 1
                        except Exception:
                            pass
                except Exception:
                    continue
                if removed > 0:
                    logger_event.info(
                        "%s 청소: %d개 파일 제거 (>%ds)",
                        label, removed, CHEJAN_EVENT_TTL_SEC,
                    )
        except Exception:
            pass

    # ───────────────────────────────────────────────────────────
    # IPC: Request 처리
    # ───────────────────────────────────────────────────────────
    def process_request(self, req_path: Path):
        """단일 IPC request 처리 (TTL 검사 → dispatch → 삭제)."""
        request_id = req_path.stem
        try:
            req = json.loads(req_path.read_text(encoding="utf-8-sig"))
            request_id = req.get("request_id", request_id)
            req_type   = req.get("type", "")
            ts_str     = req.get("ts", "")
            ttl        = int(req.get("ttl_sec", self.DEFAULT_TTL_SEC))

            # TTL 검사
            try:
                req_ts = datetime.fromisoformat(ts_str)
                age = (datetime.now() - req_ts).total_seconds()
            except Exception:
                age = 0.0

            # [N26 2026-05-14] 시계 skew 보호 — req.ts 가 미래 (-ttl 이하) 시 의심 로그 + 0 reset
            if age < -ttl:
                logger.warning(
                    "REQ %s 시계 skew 의심 (req.ts 미래): age=%.1fs — 0 으로 reset 후 진행",
                    request_id, age,
                )
                age = 0.0

            if age > ttl:
                logger.warning(
                    "REQ %s EXPIRED age=%.1fs > ttl=%ds",
                    request_id, age, ttl,
                )
                self._write_response(
                    request_id, status="TIMEOUT",
                    error=f"TTL expired (age={age:.1f}s, ttl={ttl}s)",
                )
                req_path.unlink(missing_ok=True)
                return

            # Type dispatch
            if req_type == "PING":
                self._write_response(
                    request_id, status="OK",
                    data={"pong": True, "state": self.state.value},
                )
            elif req_type == "TR":
                self._handle_tr_request(request_id, req)
            elif req_type == "SHUTDOWN":
                self._handle_shutdown_request(request_id)
            elif req_type == "DISCONNECT_SCR":
                self._handle_disconnect_scr_request(request_id, req)
            elif req_type == "STATE":
                self._handle_state_request(request_id)
            elif req_type == "ACCOUNT_INFO":
                self._handle_account_info_request(request_id, req)
            elif req_type == "BALANCE_TR":
                self._handle_balance_tr_request(request_id, req)
            elif req_type == "MASTER_INFO":
                # [STEP-3.4 MASTER_INFO 2026-05-14] read-only 마스터 함수 위임 (collect_eod_daily_bars 용)
                self._handle_master_info_request(request_id, req)
            elif req_type == "SETREAL_REG":
                # [B1 2026-05-14] SetRealReg 위임 (실시간 시세 등록)
                self._handle_setreal_reg_request(request_id, req)
            elif req_type == "SET_REAL_REMOVE":
                # [E1 2026-05-14] SetRealRemove 위임 (실시간 시세 해제)
                self._handle_set_real_remove_request(request_id, req)
            elif req_type == "GET_COMM_REAL_DATA":
                # [D1 2026-05-14] GetCommRealData 위임 (실시간 데이터 추출)
                self._handle_get_comm_real_data_request(request_id, req)
            elif req_type == "GET_REAL_REG_GRP":
                # [B2 2026-05-14] GetRealRegGroup 위임 (실시간 등록 그룹 조회)
                self._handle_get_real_reg_grp_request(request_id, req)
            elif req_type == "SET_REAL_REMOVE_ALL":
                # [B3 2026-05-14] SetRealRemove("ALL","ALL") 명시 단축 (EOD 정리)
                self._handle_set_real_remove_all_request(request_id, req)
            elif req_type == "KOA_FUNCTIONS":
                # [F1 2026-05-14] KOA_Functions 위임 (자동로그인 설정 등 키움 확장 함수)
                self._handle_koa_functions_request(request_id, req)
            elif req_type == "SENDORDER_SHADOW":
                self._handle_sendorder_shadow_request(request_id, req)
            elif req_type == "SENDORDER_REAL":
                # [Z1 2026-05-14] 실 SendOrder 집행 + idempotency
                self._handle_sendorder_real_request(request_id, req)
            elif req_type == "BATCH_TR":
                # [Phase 1.1 BATCH_TR 2026-05-14] 다종목 TR 일괄 처리 (collector opt10080 throughput 영구 해결 기반)
                self._handle_batch_tr_request(request_id, req)
            else:
                logger.warning("REQ %s UNKNOWN TYPE: %s", request_id, req_type)
                self._write_response(
                    request_id, status="ERROR",
                    error=f"Unknown request type: {req_type}",
                )

            req_path.unlink(missing_ok=True)
            self.last_request_id = request_id
            self.last_request_ts = datetime.now().isoformat()

        except Exception as e:
            logger.error("REQ 처리 오류 %s: %s", req_path.name, e)
            self._write_response(
                request_id, status="ERROR", error=f"Broker exception: {e}"
            )
            try:
                req_path.unlink(missing_ok=True)
            except Exception:
                pass

    # [STEP-2F-1 + I1 2026-05-14] read-only 잔고 TR whitelist — SendOrder 금지
    # [I1] 미체결(opt10075) + 주식잔고(opw00009) 추가
    BALANCE_TR_WHITELIST = {"opw00001", "opw00004", "opw00018", "opt10075", "opw00009"}

    def _handle_state_request(self, request_id):
        """[STEP-2F-1] GetConnectState 위임 — sub-process is_connected 용."""
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="OK",
                data={
                    "connected": False,
                    "broker_state": self.state.value,
                },
            )
            return
        try:
            cs = int(self.ocx.dynamicCall("GetConnectState()"))
            self._write_response(
                request_id, status="OK",
                data={
                    "connected": (cs == 1),
                    "raw": cs,
                    "broker_state": self.state.value,
                },
            )
        except Exception as e:
            logger.error("STATE 조회 오류: %s", e)
            self._write_response(
                request_id, status="ERROR",
                error=f"GetConnectState exception: {e}",
            )

    def _handle_account_info_request(self, request_id, req):
        """[STEP-2F-1] GetLoginInfo(tag) 위임 — sub-process 계좌 조회용.

        payload: { "type": "ACCOUNT_INFO", "tag": "ACCNO" (optional, default ACCNO) }
        """
        tag = str(req.get("tag", "ACCNO")).strip() or "ACCNO"
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return
        try:
            raw = str(
                self.ocx.dynamicCall("GetLoginInfo(QString)", tag)
            ).strip()
            data = {"tag": tag, "value": raw}
            if tag == "ACCNO":
                data["accounts"] = raw
            self._write_response(request_id, status="OK", data=data)
        except Exception as e:
            logger.error("ACCOUNT_INFO 조회 오류 tag=%s: %s", tag, e)
            self._write_response(
                request_id, status="ERROR",
                error=f"GetLoginInfo exception: {e}",
            )

    def _handle_sendorder_shadow_request(self, request_id, req):
        """[STEP-2F-4] SendOrder SHADOW MODE — broker SendOrder 호출 절대 금지.

        실주문은 engine 의 direct OCX SendOrder 가 이미 처리한 상태.
        이 핸들러는:
          1. payload 기록 (IPC/order_shadow/{request_id}.json)
          2. latency log (engine → broker)
          3. OK 응답
        broker 가 실제 SendOrder 호출하지 않음 (중복 주문 방지).
        """
        ts_receive = datetime.now()

        try:
            account         = str(req.get("account", "")).strip()
            code            = str(req.get("code", "")).strip()
            qty             = int(req.get("qty", 0))
            price           = int(req.get("price", 0))
            order_type      = int(req.get("order_type", 0))
            screen_no       = str(req.get("screen_no", "")).strip()
            rqname          = str(req.get("rqname", "")).strip()
            hoga_gb         = str(req.get("hoga_gb", "")).strip()
            origin_order_no = str(req.get("origin_order_no", "")).strip()
            engine_name     = str(req.get("engine", "unknown")).strip()
        except Exception as e:
            self._write_response(
                request_id, status="ERROR",
                error=f"SENDORDER_SHADOW payload parse error: {e}",
            )
            return

        # validation (실주문이 아니므로 strict 하지 않음 — 누락 시 ERROR 로 echo)
        if not account or not code or qty <= 0:
            logger_order_shadow.warning(
                "invalid payload engine=%s account=%s code=%s qty=%d",
                engine_name, account, code, qty,
            )
            self._write_response(
                request_id, status="ERROR",
                error="SENDORDER_SHADOW invalid (account/code/qty required)",
            )
            return

        # shadow record write
        try:
            shadow = {
                "request_id":         request_id,
                "ts_engine":          str(req.get("ts", "")),
                "ts_broker_receive":  ts_receive.isoformat(),
                "engine":             engine_name,
                "account":            account,
                "code":               code,
                "qty":                qty,
                "price":              price,
                "order_type":         order_type,
                "screen_no":          screen_no,
                "rqname":             rqname,
                "hoga_gb":            hoga_gb,
                "origin_order_no":    origin_order_no,
                "note":               "broker_did_not_send (shadow_only)",
            }
            shadow_path = IPC_ORDER_SHADOW_DIR / f"{request_id}.json"
            tmp = shadow_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(shadow, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(shadow_path))

            ts_done = datetime.now()
            engine_to_broker_ms = -1.0
            try:
                ts_eng = datetime.fromisoformat(str(req.get("ts", "")))
                engine_to_broker_ms = (ts_receive - ts_eng).total_seconds() * 1000.0
            except Exception:
                pass
            broker_write_ms = (ts_done - ts_receive).total_seconds() * 1000.0

            logger_order_shadow.info(
                "shadow_recv engine=%s code=%s qty=%d type=%d "
                "engine_to_broker_ms=%.1f broker_write_ms=%.1f request_id=%s",
                engine_name, code, qty, order_type,
                engine_to_broker_ms, broker_write_ms, request_id,
            )
            # [STEP-2F-5] latency warning (warning only — reject/retry 금지)
            if engine_to_broker_ms > 500.0:
                logger_order_shadow.warning(
                    "SHADOW_LATENCY_HIGH engine_to_broker_ms=%.1f (>500ms) "
                    "engine=%s code=%s qty=%d request_id=%s",
                    engine_to_broker_ms, engine_name, code, qty, request_id,
                )

            self._write_response(
                request_id, status="OK",
                data={
                    "shadow_id":           request_id,
                    "broker_receive_ts":   ts_receive.isoformat(),
                    "engine_to_broker_ms": engine_to_broker_ms,
                    "broker_write_ms":     broker_write_ms,
                },
            )
        except Exception as e:
            logger.error("SENDORDER_SHADOW write 오류: %s", e)
            self._write_response(
                request_id, status="ERROR",
                error=f"shadow write exception: {e}",
            )

    def _handle_balance_tr_request(self, request_id, req):
        """[STEP-2F-1 + J4 2026-05-14] read-only 잔고 TR — whitelist 적용 후 기존 TR 흐름 위임.

        whitelist 외 tr_code 는 ERROR 반환 (SendOrder 등 우회 차단).
        [J4] 위임 호출 자체에 try/except 추가 — observability 강화 (위임 외 예외 격리).
        """
        tr_code = str(req.get("tr_code", "")).strip()
        if tr_code not in self.BALANCE_TR_WHITELIST:
            logger.warning(
                "BALANCE_TR whitelist 위반 tr_code=%s", tr_code
            )
            self._write_response(
                request_id, status="ERROR",
                error=f"BALANCE_TR whitelist 외 tr_code='{tr_code}'",
            )
            return
        # 기존 TR 흐름으로 위임 — SetInputValue/CommRqData/OnReceiveTrData
        try:
            self._handle_tr_request(request_id, req)
        except Exception as e:
            logger.error("BALANCE_TR 위임 예외 tr_code=%s: %s", tr_code, e, exc_info=True)
            self._write_response(
                request_id, status="ERROR",
                error=f"BALANCE_TR 위임 예외 tr_code={tr_code}: {e}",
            )

    # [STEP-3.4 MASTER_INFO 2026-05-14] read-only 마스터 함수 whitelist
    MASTER_INFO_WHITELIST = {
        "GetCodeListByMarket",   # arg: market_code (0=KOSPI, 10=KOSDAQ ...)
        "GetMasterCodeName",     # arg: code
        "GetMasterStockInfo",    # arg: code
        "GetMasterETF",          # arg: code  (int 반환 → str 변환)
        "GetMasterStockState",   # arg: code  [A-2a 2026-05-15] collector _load_all_market_codes 필요
    }

    def _handle_master_info_request(self, request_id, req):
        """[STEP-3.4 MASTER_INFO] read-only 키움 마스터 함수 위임.

        payload: { "type": "MASTER_INFO", "func": "<func_name>", "arg": "<value>" }
        whitelist 외 func 는 ERROR. SendOrder/SetRealReg 등 부수효과 함수 차단.
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return
        func = str(req.get("func", "")).strip()
        arg  = str(req.get("arg", "")).strip()
        if func not in self.MASTER_INFO_WHITELIST:
            self._write_response(
                request_id, status="ERROR",
                error=f"MASTER_INFO whitelist 외 func='{func}'",
            )
            return
        try:
            if func == "GetMasterETF":
                # [J2 2026-05-14] N32 cosmetic — 미사용 GetMasterStockInfo 호출 제거
                etf_int = self.ocx.dynamicCall("GetMasterETF(QString)", arg)
                self._write_response(
                    request_id, status="OK",
                    data={"func": func, "arg": arg, "value": int(etf_int) if etf_int is not None else 0},
                )
                return
            val = self.ocx.dynamicCall(f"{func}(QString)", arg)
            self._write_response(
                request_id, status="OK",
                data={"func": func, "arg": arg, "value": str(val) if val is not None else ""},
            )
        except Exception as e:
            logger.error("MASTER_INFO 오류 func=%s arg=%s: %s", func, arg, e)
            self._write_response(
                request_id, status="ERROR",
                error=f"MASTER_INFO exception: {e}",
            )

    # ───────────────────────────────────────────────────────────
    # [B1/D1/E1 2026-05-14] 실시간 시세 위임 핸들러
    # ───────────────────────────────────────────────────────────
    def _handle_setreal_reg_request(self, request_id, req):
        """[B1 + Z2 2026-05-14] SetRealReg 위임 + state replay 영속화.

        payload: {"type": "SETREAL_REG", "screen_no": "9001", "code_list": "035720;005930",
                  "fid_list": "10;13;15;16;27;28", "real_type": "0"}
        real_type: "0" 신규 등록, "1" 추가 등록

        [Z2] 성공 시 self._realreg_state 에 저장 + broker_state.json 디스크 영속화.
             broker 재시작 시 _replay_realreg() 가 자동 재등록.
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return
        screen_no = str(req.get("screen_no", "")).strip()
        code_list = str(req.get("code_list", "")).strip()
        fid_list  = str(req.get("fid_list", "")).strip()
        real_type = str(req.get("real_type", "0")).strip() or "0"
        if not screen_no or not code_list or not fid_list:
            self._write_response(
                request_id, status="ERROR",
                error="SETREAL_REG required: screen_no, code_list, fid_list",
            )
            return
        try:
            ret = self.ocx.dynamicCall(
                "SetRealReg(QString, QString, QString, QString)",
                screen_no, code_list, fid_list, real_type,
            )
            ret_int = int(ret) if ret is not None else -1
            if ret_int == 0:
                # [Z2] state replay — 성공한 등록 영속 저장
                self._realreg_state[screen_no] = {
                    "code_list": code_list,
                    "fid_list":  fid_list,
                    "real_type": real_type,
                    "ts":        datetime.now().isoformat(),
                }
                self._save_realreg_state()
            self._write_response(
                request_id, status="OK",
                data={"screen_no": screen_no, "code_list": code_list,
                      "fid_list": fid_list, "real_type": real_type, "ret": ret_int},
            )
        except Exception as e:
            logger.error("SetRealReg 오류 screen_no=%s: %s", screen_no, e)
            self._write_response(
                request_id, status="ERROR",
                error=f"SetRealReg exception: {e}",
            )

    # ───────────────────────────────────────────────────────────
    # [Z2 2026-05-14] state replay — broker reconnect 시 SetRealReg 자동 재등록
    # ───────────────────────────────────────────────────────────
    def _save_realreg_state(self):
        """SetRealReg 등록 상태를 디스크에 영속 저장 (atomic write)."""
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"realreg": self._realreg_state,
                            "ts": datetime.now().isoformat()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(STATE_FILE))
        except Exception as e:
            logger.error("[Z2] _save_realreg_state 실패: %s", e)

    def _load_realreg_state(self):
        """broker 시작 시 이전 state 로드. 단 _replay_realreg() 호출 전 까지 등록 안 함."""
        try:
            if not STATE_FILE.exists():
                self._realreg_state = {}
                return
            data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
            self._realreg_state = data.get("realreg") or {}
            logger.info("[Z2] state 로드: %d 개 화면 등록 이력", len(self._realreg_state))
        except Exception as e:
            logger.error("[Z2] _load_realreg_state 실패: %s", e)
            self._realreg_state = {}

    def _replay_realreg(self):
        """LOGIN 성공 후 이전 SetRealReg 등록 자동 재실행.

        sub-process 가 broker 재시작 알아챌 필요 없이 broker 가 스스로 복원.
        """
        if not self._realreg_state:
            return
        if self.state != BrokerState.CONNECTED:
            logger.warning("[Z2-REPLAY] state %s — replay 보류", self.state.value)
            return
        logger.info("[Z2-REPLAY] %d 개 화면 SetRealReg 재등록 시작", len(self._realreg_state))
        ok_count = 0
        fail_count = 0
        for screen_no, info in self._realreg_state.items():
            try:
                ret = self.ocx.dynamicCall(
                    "SetRealReg(QString, QString, QString, QString)",
                    screen_no, info.get("code_list", ""), info.get("fid_list", ""),
                    info.get("real_type", "0"),
                )
                ret_int = int(ret) if ret is not None else -1
                if ret_int == 0:
                    ok_count += 1
                    logger.info("[Z2-REPLAY] OK screen=%s codes=%s", screen_no,
                                (info.get("code_list", "")[:40] + "...") if len(info.get("code_list", "")) > 40 else info.get("code_list", ""))
                else:
                    fail_count += 1
                    logger.warning("[Z2-REPLAY] FAIL screen=%s ret=%d", screen_no, ret_int)
            except Exception as e:
                fail_count += 1
                logger.error("[Z2-REPLAY] screen=%s 예외: %s", screen_no, e)
        logger.info("[Z2-REPLAY] 완료 ok=%d fail=%d", ok_count, fail_count)

    def _handle_set_real_remove_request(self, request_id, req):
        """[E1 2026-05-14] SetRealRemove 위임.

        payload: {"type": "SET_REAL_REMOVE", "screen_no": "9001", "code": "035720" or "ALL"}
        code="ALL" 시 화면 전체 해제. screen_no="ALL" + code="ALL" 시 전체 실시간 해제.
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return
        screen_no = str(req.get("screen_no", "")).strip()
        code      = str(req.get("code", "")).strip()
        if not screen_no or not code:
            self._write_response(
                request_id, status="ERROR",
                error="SET_REAL_REMOVE required: screen_no, code",
            )
            return
        try:
            self.ocx.dynamicCall(
                "SetRealRemove(QString, QString)", screen_no, code,
            )
            # [Z2] state 갱신 — screen_no/code 완전 제거 시 state 에서도 제거
            if code.upper() == "ALL":
                # 화면 전체 해제
                self._realreg_state.pop(screen_no, None)
                self._save_realreg_state()
            self._write_response(
                request_id, status="OK",
                data={"screen_no": screen_no, "code": code, "removed": True},
            )
        except Exception as e:
            logger.error("SetRealRemove 오류 screen_no=%s code=%s: %s", screen_no, code, e)
            self._write_response(
                request_id, status="ERROR",
                error=f"SetRealRemove exception: {e}",
            )

    def _handle_get_comm_real_data_request(self, request_id, req):
        """[D1 2026-05-14] GetCommRealData 위임 — 폴링 호출용.

        payload: {"type": "GET_COMM_REAL_DATA", "code": "035720", "fid": 10}
        실시간 broadcast (IPC/real_data/) 와 별개, 직접 호출형. broadcast 가 file IPC 부담 크면 sub-process 가 pull 형식으로 사용 가능.
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return
        code = str(req.get("code", "")).strip()
        try:
            fid = int(req.get("fid", 0))
        except Exception:
            fid = 0
        if not code or fid <= 0:
            self._write_response(
                request_id, status="ERROR",
                error="GET_COMM_REAL_DATA required: code, fid",
            )
            return
        try:
            val = self.ocx.dynamicCall(
                "GetCommRealData(QString, int)", code, fid,
            )
            self._write_response(
                request_id, status="OK",
                data={"code": code, "fid": fid, "value": str(val).strip() if val else ""},
            )
        except Exception as e:
            logger.error("GetCommRealData 오류 code=%s fid=%s: %s", code, fid, e)
            self._write_response(
                request_id, status="ERROR",
                error=f"GetCommRealData exception: {e}",
            )

    # ───────────────────────────────────────────────────────────
    # [Z1 2026-05-14] SendOrder 실 집행 + idempotency dedup
    # ───────────────────────────────────────────────────────────
    # Idempotency: client 가 동일 idempotency_key 로 N회 호출 시 broker 가 1회만 SendOrder.
    # 같은 key 의 후속 호출 = cache 에서 직전 응답 즉시 반환.
    # 이유: client timeout 후 재요청 시 중복 주문 방지 (자산 손실 차단).
    _sendorder_idempotency_cache: dict = {}  # idempotency_key → (ts, response_dict)
    _SENDORDER_IDEMPOTENCY_TTL_SEC = 300  # 5분 dedup 윈도우

    def _purge_sendorder_idempotency(self):
        """idempotency cache 의 TTL 초과 항목 청소."""
        try:
            now = time.time()
            expired = [k for k, v in self._sendorder_idempotency_cache.items()
                       if (now - v[0]) > self._SENDORDER_IDEMPOTENCY_TTL_SEC]
            for k in expired:
                self._sendorder_idempotency_cache.pop(k, None)
        except Exception:
            pass

    # SendOrder 화이트리스트 — order_type 정수만 허용 (1=매수, 2=매도, 3=매수취소, 4=매도취소, 5=매수정정, 6=매도정정)
    SENDORDER_TYPE_WHITELIST = {1, 2, 3, 4, 5, 6}

    def _handle_sendorder_real_request(self, request_id, req):
        """[Z1 2026-05-14] 실 SendOrder 집행. idempotency 보장.

        payload: {
          "type": "SENDORDER_REAL",
          "idempotency_key": "<uuid>",   # 필수. 같은 key = 중복 차단
          "rqname":          "buy_001",
          "screen_no":       "9001",
          "account":         "6502...",
          "order_type":      1,            # 1=매수 2=매도 ...
          "code":            "035720",
          "qty":             10,
          "price":           50000,
          "hoga_gb":         "00",         # 00=지정가 03=시장가
          "origin_order_no": ""            # 정정/취소 시 원주문번호
        }
        """
        self._purge_sendorder_idempotency()

        if self.state != BrokerState.CONNECTED:
            self._write_response(request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})")
            return

        idempotency_key = str(req.get("idempotency_key", "")).strip()
        if not idempotency_key:
            self._write_response(request_id, status="ERROR",
                error="SENDORDER_REAL: idempotency_key required (중복 주문 차단)")
            return

        # idempotency check — 같은 key 이전 응답 있으면 그대로 재반환
        cached = self._sendorder_idempotency_cache.get(idempotency_key)
        if cached:
            _, prev_res = cached
            logger.warning(
                "[SENDORDER-DEDUP] idempotency_key=%s 재요청 — cache 응답 반환 (실 SendOrder 미호출)",
                idempotency_key,
            )
            self._write_response(
                request_id,
                status=prev_res.get("status", "OK"),
                data=prev_res.get("data"),
                error=prev_res.get("error"),
            )
            return

        try:
            rqname    = str(req.get("rqname", f"SendOrder_{request_id[:8]}")).strip()
            screen_no = str(req.get("screen_no", "9999")).strip()
            account   = str(req.get("account", "")).strip()
            order_type = int(req.get("order_type", 0))
            code      = str(req.get("code", "")).strip()
            qty       = int(req.get("qty", 0))
            price     = int(req.get("price", 0))
            hoga_gb   = str(req.get("hoga_gb", "")).strip()
            origin_order_no = str(req.get("origin_order_no", "")).strip()
        except Exception as e:
            self._write_response(request_id, status="ERROR",
                error=f"SENDORDER_REAL payload parse: {e}")
            return

        # validation
        if order_type not in self.SENDORDER_TYPE_WHITELIST:
            self._write_response(request_id, status="ERROR",
                error=f"SENDORDER_REAL: order_type {order_type} 허용 범위 외 (1~6)")
            return
        if not account or not code or qty <= 0:
            self._write_response(request_id, status="ERROR",
                error=f"SENDORDER_REAL required: account/code/qty (got account={account} code={code} qty={qty})")
            return
        if hoga_gb not in ("00", "03", "05", "06", "07", "10", "13", "16", "20", "23", "26", "61", "62", "81"):
            # 키움 표준 호가구분 화이트리스트 (00=지정가, 03=시장가, ...)
            self._write_response(request_id, status="ERROR",
                error=f"SENDORDER_REAL: hoga_gb '{hoga_gb}' 허용 외")
            return

        logger.info(
            "[SENDORDER-REAL] key=%s account=%s code=%s qty=%d price=%d type=%d hoga=%s rqname=%s",
            idempotency_key, account, code, qty, price, order_type, hoga_gb, rqname,
        )

        try:
            ret = self.ocx.dynamicCall(
                "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                # [SENDORDER-LIST-FIX 2026-06-04] 키움 SendOrder 9개 인자는 PyQt dynamicCall에 반드시
                # 리스트로 묶어 전달해야 함. 개별 위치인자 전달 시 "arguments did not match any overloaded
                # call" 예외로 실주문 미발사(프로젝트 전체 실체결0의 근본원인). 리스트 래핑으로 교정.
                [rqname, screen_no, account, order_type, code, qty, price, hoga_gb, origin_order_no],
            )
            ret_int = int(ret) if ret is not None else -1
            ok = (ret_int == 0)
            response_dict = {
                "status": "OK" if ok else "ERROR",
                "data":   {"ret": ret_int, "code": code, "qty": qty, "order_type": order_type,
                           "rqname": rqname, "screen_no": screen_no, "ts": datetime.now().isoformat()},
                "error":  None if ok else f"SendOrder ret={ret_int}",
            }
            # idempotency cache 저장 (성공/실패 모두 — 재시도 시 같은 응답 반환)
            self._sendorder_idempotency_cache[idempotency_key] = (time.time(), response_dict)
            self._write_response(request_id, **{k: response_dict[k] for k in ("status", "data", "error")})
        except Exception as e:
            logger.critical("[SENDORDER-REAL] dynamicCall 예외 key=%s code=%s: %s",
                            idempotency_key, code, e, exc_info=True)
            response_dict = {
                "status": "ERROR",
                "data":   None,
                "error":  f"SendOrder exception: {e}",
            }
            self._sendorder_idempotency_cache[idempotency_key] = (time.time(), response_dict)
            self._write_response(request_id, **{k: response_dict[k] for k in ("status", "data", "error")})

    # ───────────────────────────────────────────────────────────
    # [Phase 1.1 BATCH_TR 2026-05-14] 다종목 TR 일괄 처리
    # ───────────────────────────────────────────────────────────
    # 목적: collector opt10080 의 IPC overhead 영구 해결.
    # 단일 TR 호출 시 IPC write+poll = ~350~500ms 종목당. 60종목 = +30s 사이클.
    # BATCH_TR 시 IPC 1회만 (request write 1 + response write 1) + broker 측에서 N회 OCX 호출 직렬.
    # 효과: IPC overhead = N × 350ms → 1 × 350ms = 사이클당 ~20초 절감 추정.
    # OCX 호출 자체는 single-thread 직렬 (broker constraints) — throughput 한계는 키움 측.
    #
    # payload:
    #   {
    #     "type":              "BATCH_TR",
    #     "tr_code":           "opt10080",
    #     "codes":             ["035720", "005930", ...],
    #     "rqname_template":   "opt10080_req",     # 모든 종목 동일 (broker buffer rqname 기준 처리)
    #     "screen_no_rotate":  ["0001", "0002", ...],  # optional, 종목별 화면번호 rotate
    #     "input_template":    {"종목코드": "{CODE}", "틱범위": "1", "수정주가구분": "0"},
    #     "output_fields":     ["체결시간", "시가", "고가", "저가", "현재가", "거래량", "거래대금"],
    #     "next_flag":         0,
    #     "per_request_timeout_sec": 5.0,   # 종목당 timeout (기본 5s)
    #     "batch_timeout_sec":       60.0   # 전체 batch timeout
    #   }
    #
    # response:
    #   {
    #     "results": [{"code": "...", "status": "OK"|"TIMEOUT"|"ERROR",
    #                  "data": {...}, "error": null|"..."}],
    #     "summary": {"total": N, "ok": M, "timeout": K, "error": L,
    #                 "elapsed_sec": float, "aborted": bool}
    #   }
    #
    # 위험 / 제약:
    #   - broker tr_loop.exec_() 가 batch 안에서 N회 호출 → 그동안 poll_timer/heartbeat_timer 지연
    #     (batch_timeout_sec 안에 끝나면 안전)
    #   - heartbeat 가 batch 중 stale (15s+) 되면 sub-process 가 broker dead 오판 → fallback 진입
    #     → 권장: batch 안에서도 매 N개 종목 처리 후 write_heartbeat() 강제 호출 (구현 포함)
    BATCH_TR_HB_INTERVAL = 5  # 매 5개 종목 처리 후 heartbeat 강제 갱신

    def _handle_batch_tr_request(self, request_id, req):
        """[Phase 1.1 2026-05-14] BATCH_TR — 다종목 일괄 TR 위임."""
        if self.state != BrokerState.CONNECTED:
            self._write_response(request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})")
            return

        tr_code           = str(req.get("tr_code", "")).strip()
        codes             = req.get("codes") or []
        rqname_template   = str(req.get("rqname_template", f"{tr_code}_req")).strip()
        screen_no_rotate  = req.get("screen_no_rotate") or ["0001"]
        input_template    = req.get("input_template") or {}
        output_fields     = req.get("output_fields") or []
        next_flag         = int(req.get("next_flag", 0))
        per_request_to    = float(req.get("per_request_timeout_sec", 5.0))
        batch_to          = float(req.get("batch_timeout_sec", 60.0))

        if not tr_code or not codes:
            self._write_response(request_id, status="ERROR",
                error="BATCH_TR required: tr_code, codes (non-empty list)")
            return
        if not isinstance(codes, list):
            self._write_response(request_id, status="ERROR",
                error="BATCH_TR: codes must be list")
            return

        results: list = []
        summary = {"total": len(codes), "ok": 0, "timeout": 0, "error": 0,
                   "elapsed_sec": 0.0, "aborted": False}
        batch_start = time.time()

        for i, code in enumerate(codes):
            # batch 전체 timeout 검사
            if time.time() - batch_start > batch_to:
                summary["aborted"] = True
                logger.warning("[BATCH_TR] batch timeout %ds 초과 — %d/%d 종목 처리 후 중단",
                               int(batch_to), i, len(codes))
                # 미처리 종목은 status=ERROR 로 추가
                for j in range(i, len(codes)):
                    results.append({"code": str(codes[j]), "status": "ERROR",
                                    "data": None, "error": "batch timeout"})
                    summary["error"] += 1
                break

            # heartbeat 강제 갱신 (batch 중 broker dead 오판 차단)
            if i > 0 and (i % self.BATCH_TR_HB_INTERVAL) == 0:
                try:
                    self.write_heartbeat()
                except Exception:
                    pass

            # screen_no rotate
            scr = str(screen_no_rotate[i % len(screen_no_rotate)])

            # input dict 에 {CODE} 치환
            inputs = {}
            for k, v in input_template.items():
                if isinstance(v, str) and "{CODE}" in v:
                    inputs[k] = v.replace("{CODE}", str(code))
                else:
                    inputs[k] = v

            # 단일 TR 호출 (기존 _handle_tr_request 로직 인라인 — response 작성 대신 results 에 추가)
            try:
                self.tr_output_fields = list(output_fields)
                # SetInputValue
                # [BATCH-FIX-3 2026-05-15] 실패 시 outer continue (CommRqData 부분 input 발사 차단)
                input_failed = False
                for ik, iv in inputs.items():
                    try:
                        self.ocx.dynamicCall("SetInputValue(QString, QString)", ik, str(iv))
                    except Exception as sive:
                        results.append({"code": str(code), "status": "ERROR",
                                        "data": None, "error": f"SetInputValue {ik}: {sive}"})
                        summary["error"] += 1
                        input_failed = True
                        break   # inner loop 즉시 종료
                if input_failed:
                    continue   # outer for code — CommRqData 발사 차단 + 다음 code

                # [BATCH-FIX-2 2026-05-15] stale tr_data_buffer 청소 —
                # 이전 code timeout 후 delayed OnReceiveTrData 응답이 이번 code 결과로 섞이는 corruption 차단
                self.tr_data_buffer.pop(rqname_template, None)

                # tr_loop + timer
                self.tr_loop = QEventLoop()
                _timer = QTimer()
                _timer.setSingleShot(True)
                _timer.timeout.connect(self.tr_loop.quit)
                _timer.start(int(per_request_to * 1000))

                _tr_limiter.acquire()  # [TR-THROTTLE 2026-06-24] 키움 2/sec 공유예산 준수
                ret = self.ocx.dynamicCall(
                    "CommRqData(QString, QString, int, QString)",
                    rqname_template, tr_code, next_flag, scr,
                )
                if ret != 0:
                    _timer.stop()
                    results.append({"code": str(code), "status": "ERROR",
                                    "data": None, "error": f"CommRqData ret={ret}"})
                    summary["error"] += 1
                    continue

                self.tr_loop.exec_()
                _timer.stop()

                data = self.tr_data_buffer.pop(rqname_template, None)
                if data:
                    results.append({"code": str(code), "status": "OK",
                                    "data": data, "error": None})
                    summary["ok"] += 1
                    self.tr_count += 1
                else:
                    results.append({"code": str(code), "status": "TIMEOUT",
                                    "data": None,
                                    "error": f"per_request_timeout {per_request_to}s"})
                    summary["timeout"] += 1

            except Exception as e:
                logger.error("[BATCH_TR] code=%s 예외: %s", code, e)
                results.append({"code": str(code), "status": "ERROR",
                                "data": None, "error": f"exception: {e}"})
                summary["error"] += 1

        summary["elapsed_sec"] = round(time.time() - batch_start, 3)
        logger.info(
            "[BATCH_TR] tr_code=%s total=%d ok=%d timeout=%d error=%d elapsed=%.2fs aborted=%s",
            tr_code, summary["total"], summary["ok"], summary["timeout"],
            summary["error"], summary["elapsed_sec"], summary["aborted"],
        )
        self._write_response(request_id, status="OK",
            data={"results": results, "summary": summary})

    def _handle_get_real_reg_grp_request(self, request_id, req):
        """[B2 2026-05-14] GetRealRegGroup 위임. 현재 등록된 실시간 그룹(화면번호) 목록 조회.

        payload: {"type": "GET_REAL_REG_GRP"}
        return: data.value = "9001;9002;..." (세미콜론 구분)
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})")
            return
        try:
            val = self.ocx.dynamicCall("GetRealRegGroup()")
            self._write_response(request_id, status="OK",
                data={"value": str(val) if val else ""})
        except Exception as e:
            logger.error("GetRealRegGroup 오류: %s", e)
            self._write_response(request_id, status="ERROR",
                error=f"GetRealRegGroup exception: {e}")

    def _handle_set_real_remove_all_request(self, request_id, req):
        """[B3 2026-05-14] SetRealRemove("ALL","ALL") 명시 단축 — EOD 정리/킬스위치 용도.

        payload: {"type": "SET_REAL_REMOVE_ALL"}
        효과: 전체 실시간 등록 해제 (모든 화면, 모든 종목).
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})")
            return
        try:
            self.ocx.dynamicCall("SetRealRemove(QString, QString)", "ALL", "ALL")
            # [Z2] state 전체 초기화
            self._realreg_state = {}
            self._save_realreg_state()
            logger.info("[B3-REAL-REMOVE-ALL] 전체 실시간 등록 해제 완료")
            self._write_response(request_id, status="OK",
                data={"removed": "ALL"})
        except Exception as e:
            logger.error("SetRealRemove(ALL,ALL) 오류: %s", e)
            self._write_response(request_id, status="ERROR",
                error=f"SetRealRemoveAll exception: {e}")

    # [F1 2026-05-14] KOA_Functions whitelist — 안전한 read-only 확장 함수만 허용
    # SendOrder/주문 기능은 화이트리스트 외라 거부됨.
    KOA_FUNCTIONS_WHITELIST = {
        "GetServerGubun",          # 서버 구분 ("1"=모의, ""=실)
        "GetCodeListByMarket",     # 시장별 종목 (MASTER_INFO 와 중복 가능)
        "ShowAccountWindow",       # 계좌비밀번호 저장 창 호출 (사용자 K1 우회 시도)
        "GetMasterStockState",     # 종목 상태 (정상/거래정지 등)
        "GetUpjongCode",           # 업종 코드
        "GetAPIModulePath",        # OpenAPI 설치 경로
    }

    def _handle_koa_functions_request(self, request_id, req):
        """[F1 2026-05-14] KOA_Functions 위임 — 키움 OpenAPI+ 확장 함수.

        payload: {"type": "KOA_FUNCTIONS", "func": "<name>", "arg": "<value>"}
        whitelist 외 함수는 ERROR 응답 (SendOrder 등 우회 차단).
        주요 용도:
          - ShowAccountWindow: 사용자 K1 (계좌비밀번호 저장) 우회 시도용.
            broker IPC 로 호출 → broker 가 키움 자체 창 표출 → 사용자가 그 창에서 설정.
            트레이 메뉴 접근 불가 환경 우회 가능성.
          - GetServerGubun: 모의/실 구분 확인.
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})")
            return
        func = str(req.get("func", "")).strip()
        arg  = str(req.get("arg", "")).strip()
        if func not in self.KOA_FUNCTIONS_WHITELIST:
            logger.warning("KOA_Functions whitelist 위반 func=%s", func)
            self._write_response(request_id, status="ERROR",
                error=f"KOA_FUNCTIONS whitelist 외 func='{func}'")
            return
        try:
            val = self.ocx.dynamicCall("KOA_Functions(QString, QString)", func, arg)
            self._write_response(request_id, status="OK",
                data={"func": func, "arg": arg, "value": str(val) if val is not None else ""})
        except Exception as e:
            logger.error("KOA_Functions 오류 func=%s: %s", func, e)
            self._write_response(request_id, status="ERROR",
                error=f"KOA_Functions exception: {e}")

    def _handle_disconnect_scr_request(self, request_id, req):
        """[STEP-2D] DisconnectRealData(screen_no) 위임 처리.

        payload: { "type": "DISCONNECT_SCR", "screen_no": "2001" }
        """
        screen_no = str(req.get("screen_no", "")).strip()
        if not screen_no:
            self._write_response(
                request_id, status="ERROR",
                error="screen_no required",
            )
            return

        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return

        try:
            self.ocx.dynamicCall(
                "DisconnectRealData(QString)", screen_no
            )
            self._write_response(
                request_id, status="OK",
                data={"screen_no": screen_no, "disconnected": True},
            )
        except Exception as e:
            logger.error(
                "DisconnectRealData 오류 screen_no=%s: %s",
                screen_no, e,
            )
            self._write_response(
                request_id, status="ERROR",
                error=f"DisconnectRealData exception: {e}",
            )

    def _handle_shutdown_request(self, request_id):
        """IPC SHUTDOWN command — graceful shutdown via IPC (Windows 호환)."""
        logger.info("IPC shutdown command received (request_id=%s)", request_id)
        # 1. 응답 먼저 작성 (client 가 확인 가능하도록)
        self._write_response(
            request_id, status="OK",
            data={"shutdown": True, "state": self.state.value},
        )
        # 2. 상태 SHUTDOWN 기록
        self.set_state(BrokerState.SHUTDOWN)
        self.write_heartbeat()
        # 3. lock 제거
        release_singleton_lock()
        # 4. 100ms 후 event loop 종료 — 현재 callback 깔끔히 마무리 보장
        if self.app is not None:
            QTimer.singleShot(100, self.app.quit)

    def _handle_tr_request(self, request_id, req):
        """TR 1건 처리 skeleton.

        payload:
          {
            "request_id": "...",
            "ts": "ISO8601",
            "ttl_sec": 30,
            "type": "TR",
            "tr_code": "opt10001",
            "rqname": "주식기본정보요청",
            "screen_no": "0001",
            "input": {"종목코드": "395270"}
          }
        """
        if self.state != BrokerState.CONNECTED:
            self._write_response(
                request_id, status="ERROR",
                error=f"Not connected (state={self.state.value})",
            )
            return

        tr_code   = req.get("tr_code", "")
        rqname    = req.get("rqname") or f"REQ_{request_id}"
        screen_no = str(req.get("screen_no", "0001"))
        inputs    = req.get("input", {}) or {}
        output_fields = req.get("output_fields", []) or []

        if not tr_code:
            self._write_response(
                request_id, status="ERROR", error="tr_code required"
            )
            return

        # [STEP-2A] OnReceiveTrData 콜백이 참조할 컬럼 목록 설정
        self.tr_output_fields = list(output_fields)

        # [Phase 1.2 2026-05-14] rqname → request_id mapping 등록 (관측용).
        # 동일 rqname 이미 pending 이면 경고 — single-thread 라 race 발생 불가, 단 미래 worker 확장 시 detect.
        if rqname in self.tr_pending_rqname:
            prev = self.tr_pending_rqname[rqname]
            logger.warning(
                "[RQMAP] rqname=%s 동시 pending detected — prev=%s (start_age=%.2fs) curr=%s",
                rqname, prev.get("request_id"),
                time.time() - prev.get("start_ts", 0.0),
                request_id,
            )
        self.tr_pending_rqname[rqname] = {
            "request_id": request_id,
            "start_ts":   time.time(),
        }

        try:
            # [N9 2026-05-14] SetInputValue 실패 시 명시적 ERROR — 기존 silent 상태에서 CommRqData가 잘못된 입력으로 실행되는 위험 차단
            for key, val in inputs.items():
                try:
                    self.ocx.dynamicCall(
                        "SetInputValue(QString, QString)", key, str(val)
                    )
                except Exception as sive:
                    logger.error(
                        "SetInputValue 실패 rqname=%s key=%s val=%s: %s",
                        rqname, key, val, sive,
                    )
                    self._write_response(
                        request_id, status="ERROR",
                        error=f"SetInputValue failed (key={key}): {sive}",
                    )
                    return

            self.tr_loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self.tr_loop.quit)
            timer.start(self.TR_TIMEOUT_SEC * 1000)

            # [N2 2026-05-14] prev_next 연속 조회 지원. payload 의 next_flag (0=첫, 2=연속) 사용.
            # 미지정 시 default 0 = 기존 client 하위 호환.
            next_flag = int(req.get("next_flag", 0))
            _tr_limiter.acquire()  # [TR-THROTTLE 2026-06-24] 키움 2/sec 공유예산 준수
            ret = self.ocx.dynamicCall(
                "CommRqData(QString, QString, int, QString)",
                rqname, tr_code, next_flag, screen_no,
            )
            if ret != 0:
                self._write_response(
                    request_id, status="ERROR",
                    error=f"CommRqData returned {ret}",
                )
                return

            self.tr_loop.exec_()

            data = self.tr_data_buffer.pop(rqname, None)
            if data:
                self._write_response(request_id, status="OK", data=data)
            else:
                # [HFIX-v2 2026-05-22] TIMEOUT recovery — QEventLoop+QTimer 비동기 500ms 대기.
                # HFIX (5/21) time.sleep 은 main thread block → poll_timer/heartbeat/OnReceiveTrData
                # 차단 → TIMEOUT cascade. 5/22 실측: 61회 발화 = 30s 누적 block, TIMEOUT 23.7%.
                # QEventLoop+QTimer.singleShot 조합: 500ms 동안 다른 Qt event 정상 처리 + sleep 동등 효과.
                # OCX 회복 시간 의도는 유지, Qt event loop 차단은 해소.
                try:
                    _hfix_loop = QEventLoop()
                    QTimer.singleShot(500, _hfix_loop.quit)
                    _hfix_loop.exec_()
                except Exception:
                    pass
                logger.warning("[HFIX-v2] TIMEOUT recovery wait 0.5s (non-blocking)")
                self._write_response(
                    request_id, status="TIMEOUT",
                    error=f"TR response timeout ({self.TR_TIMEOUT_SEC}s)",
                )

            self.tr_count += 1

        except Exception as e:
            logger.error("TR 처리 오류 rqname=%s: %s", rqname, e)
            self._write_response(
                request_id, status="ERROR", error=str(e)
            )
        finally:
            # [Phase 1.2 2026-05-14] mapping 정리 — 본 request 의 pending 만 제거
            if rqname in self.tr_pending_rqname and \
               self.tr_pending_rqname[rqname].get("request_id") == request_id:
                self.tr_pending_rqname.pop(rqname, None)

    # ───────────────────────────────────────────────────────────
    # IPC: Response 작성
    # ───────────────────────────────────────────────────────────
    def _write_response(self, request_id, status, data=None, error=None):
        try:
            res = {
                "request_id": request_id,
                "ts": datetime.now().isoformat(),
                "status": status,
                "data": data,
                "error": error,
            }
            res_path = IPC_RES / f"{request_id}.json"
            tmp = res_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(res, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(res_path))
            logger.info("RES %s status=%s", request_id, status)
        except Exception as e:
            logger.error("response 쓰기 실패 %s: %s", request_id, e)

    # ───────────────────────────────────────────────────────────
    # IPC polling
    # ───────────────────────────────────────────────────────────
    def poll_requests(self):
        try:
            files = sorted(IPC_REQ.glob("*.json"))
            if not files:
                return

            logger.info("REQ POLL: %d request(s)", len(files))
            for f in files:
                if self.state == BrokerState.SHUTDOWN:
                    break
                if self.state == BrokerState.RATE_LIMIT:
                    logger.warning("RATE_LIMIT — skipping %s", f.name)
                    continue
                if self.state != BrokerState.CONNECTED:
                    # [N6 2026-05-14] startup race / 비CONNECTED 상태에서 request 도착 시
                    # 기존: continue → request 파일 잔존 → client timeout 12s 대기 → fallback 진입 지연.
                    # 변경: 즉시 NOT_READY ERROR 응답 작성 → client 즉시 fallback (대기 0초).
                    logger.warning(
                        "state=%s — NOT_READY 응답 (req %s)",
                        self.state.value, f.name,
                    )
                    request_id = f.stem
                    try:
                        req = json.loads(f.read_text(encoding="utf-8-sig"))
                        request_id = req.get("request_id", request_id)
                    except Exception:
                        pass
                    self._write_response(
                        request_id, status="ERROR",
                        error=f"BROKER_NOT_READY (state={self.state.value})",
                    )
                    try: f.unlink(missing_ok=True)
                    except Exception: pass
                    continue
                self.process_request(f)
        except Exception as e:
            logger.error("poll 오류: %s", e)

    # ───────────────────────────────────────────────────────────
    # Main run loop
    # ───────────────────────────────────────────────────────────
    def run(self):
        logger.info("=" * 60)
        logger.info("Broker Gateway v1 START")
        logger.info("PID=%s",     os.getpid())
        logger.info("IPC_REQ=%s", IPC_REQ)
        logger.info("IPC_RES=%s", IPC_RES)
        logger.info("IPC_CHEJAN_DIR=%s (STEP-2F-3 broadcast active)", IPC_CHEJAN_DIR)
        logger.info("IPC_ORDER_SHADOW_DIR=%s (STEP-2F-4 shadow active)", IPC_ORDER_SHADOW_DIR)
        logger.info("IPC_ORDER_SHADOW_ACK_DIR=%s (STEP-2F-4 ACK relay active)", IPC_ORDER_SHADOW_ACK_DIR)
        logger.info("HB=%s",      HB_FILE)
        logger.info("LOCK=%s",    LOCK_FILE)
        logger.info("LOG=%s",     LOG_FILE)
        logger_event.info("EVENT_TRACE 초기화 완료")
        logger_chejan.info("CHEJAN_TRACE 초기화 완료 (STEP-2F-3 broadcast active)")
        logger_latency.info("IPC_LATENCY 초기화 완료 (callback→write 측정 active)")
        logger_order_shadow.info("ORDER_SHADOW_LATENCY 초기화 완료 (STEP-2F-4 shadow mode active)")
        logger.info("DedupCache 초기화 완료 (TTL=%.0fs, size=%d)",
                    _dedup_cache._ttl, len(_dedup_cache))
        logger.info("=" * 60)

        # [N17 2026-05-14] setup_qt 예외 시 critical + sys.exit. silent crash 차단.
        try:
            self.setup_qt()
        except Exception as e:
            logger.critical("[SETUP-QT-FAIL] QAxWidget 또는 signal connect 실패: %s", e, exc_info=True)
            release_singleton_lock()
            sys.exit(22)
        self.connect_kiwoom()

        if self.state != BrokerState.CONNECTED:
            logger.error("로그인 실패 — Broker 종료")
            return

        # [Z2 2026-05-14] LOGIN 성공 후 이전 SetRealReg 상태 자동 재등록
        self._load_realreg_state()
        self._replay_realreg()

        # [J5 2026-05-14] SetRealReg 처리 완료 대기 (OCX 내부 race 보호).
        # 다수 화면 등록 시 키움 OCX 가 등록 처리 중인 상태에서 sub-process IPC 진입 가능 → 1s 안전 마진.
        if self._realreg_state:
            logger.info("[J5] _replay_realreg 후 1s 대기 (OCX 처리 완료 race 보호)")
            time.sleep(1.0)

        # Heartbeat timer
        self._heartbeat_timer = QTimer()
        self._heartbeat_timer.timeout.connect(self.write_heartbeat)
        self._heartbeat_timer.start(self.HEARTBEAT_INTERVAL_MS)
        self.write_heartbeat()  # 초기 1회

        # Request polling timer
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self.poll_requests)
        self._poll_timer.start(self.POLL_INTERVAL_MS)

        # [REAL-MICRO 2026-06-24] 마이크로구조(체결강도/호가총잔량) 구독·flush 타이머 — env REAL_MICRO=ON 시만
        if REAL_MICRO_ON:
            self._micro_timer = QTimer()
            self._micro_timer.timeout.connect(self._micro_tick)
            self._micro_timer.start(MICRO_FLUSH_MS)
            logger.info("[MICRO] 실시간 마이크로 구독 활성화 (REAL_MICRO=ON · flush %dms · watch=%s)",
                        MICRO_FLUSH_MS, MICRO_WATCH_FILE)

        # [GRACEFUL] Python signal 처리를 위해 event loop 를 주기적으로 yield 함.
        # Qt event loop 가 C++ 측에서 동작 중일 때 Python signal handler 호출 보장.
        self._signal_check_timer = QTimer()
        self._signal_check_timer.timeout.connect(lambda: None)
        self._signal_check_timer.start(500)

        logger.info(
            "Event loop 진입 (heartbeat=%dms / poll=%dms / TR_timeout=%ds)",
            self.HEARTBEAT_INTERVAL_MS, self.POLL_INTERVAL_MS,
            self.TR_TIMEOUT_SEC,
        )

        exit_code = self.app.exec_()
        logger.info("Event loop 종료 exit_code=%s", exit_code)

        self.set_state(BrokerState.SHUTDOWN)
        self.write_heartbeat()


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════
def main():
    global _broker_instance
    if not acquire_singleton_lock():
        sys.exit(1)

    broker = BrokerGateway()
    _broker_instance = broker

    # [GRACEFUL] SIGINT (Ctrl+C) / SIGTERM 핸들러 등록
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        # [J6 2026-05-14] Windows Ctrl+Break = SIGBREAK 추가. POSIX 환경 미지원 → AttributeError catch.
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
            logger.info("signal handler 등록: SIGINT, SIGTERM, SIGBREAK")
        except (AttributeError, ValueError):
            logger.info("signal handler 등록: SIGINT, SIGTERM (SIGBREAK 미지원 환경)")
    except Exception as e:
        logger.error("signal handler 등록 실패: %s", e)

    try:
        broker.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt 수신 — graceful shutdown")
        broker.set_state(BrokerState.SHUTDOWN)
        broker.write_heartbeat()
    except Exception as e:
        logger.exception("Broker 비정상 종료: %s", e)
        broker.set_state(BrokerState.SHUTDOWN)
        broker.write_heartbeat()
    finally:
        release_singleton_lock()


if __name__ == "__main__":
    main()

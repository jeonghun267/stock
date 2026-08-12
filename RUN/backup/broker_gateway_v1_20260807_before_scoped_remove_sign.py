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

from ipc_order_auth_v1 import NonceStore, verify_order_request

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
# ★[SEC-DAILYCAP-PERSIST 2026-08-05] 일일 매수 건수를 프로세스 밖에 둔다.
#   메모리 변수뿐이던 탓에 브로커를 다시 띄우면 0 이 됐고, 워치독이 자동으로
#   재기동하므로 BROKER_MAX_DAILY_BUY 는 '하루 상한'이 아니라 '브로커 수명당 상한'이었다.
BUY_COUNT_FILE = DATA_DIR / "broker_buy_count.json"

# [REAL-MICRO 2026-06-24] ★실시간 마이크로구조 구독 — 친구님 설계: broker만 키움 실시간구독(SetRealReg)
#   → 체결강도(FID228)·호가총잔량(121/125) 수신 → IPC snapshot 1파일 batched broadcast → 봇은 파일만 읽음.
#   TR기반 체결강도(opt10001=빈값)·호가(opt10004=throttle None) 폐기. env REAL_MICRO=ON 시만 활성(기본 OFF=기존 100% 동일).
#   과거 OFF원인(event당 파일1개 I/O폭주)은 '메모리dict→1초1파일 flush'로 해결.
REAL_MICRO_ON        = os.environ.get("REAL_MICRO", "OFF").strip().upper() == "ON"
MICRO_WATCH_FILE     = IPC_DIR / "micro_watch.json"             # 구독 대상 코드(소비자가 작성: {"codes":[...]})
MICRO_SNAPSHOT_FILE  = IPC_DIR / "live_micro_snapshot.json"     # 종목별 최신 마이크로(broker가 1초마다 작성)
MICRO_SCREEN         = "9300"                                    # 마이크로 전용 실시간 화면(타 화면 무간섭) — 분할 시작 화면번호
MICRO_FIDS           = "10;13;15;228;121;125;27;28;41;51;61;71"             # 현재가;누적거래량;거래량;체결강도;매도총잔량;매수총잔량;최우선매도;최우선매수
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
# ★[2026-07-30 친구님 승인 "고저폭 보강 ② — 돈맥 앞 끼워넣기 하지 마·별개로·50개 해도 돼"]
#   고저폭 TOP30 전용 실시간 구독 통로. 공용 200칸(_read_micro_watch 우선순위)은 한 글자도 안 바꾼다.
#   문제: micro_watch_high_range.json 은 공용 PRIOR 에 없어 "남는 자리" 취급 → 7/30 실측 CAP 200 이
#   돈맥에서 정확히 소진 = 고저폭 몫 0칸(그날 30/30 수신은 앞 목록과 겹친 우연).
#   해결: 고저폭 파일만 읽는 전용 화면 1개를 따로 등록(상한 50 ≤ 키움 화면당 100 한계).
#   수신 데이터는 기존 _micro_update → live_micro_snapshot.json 으로 자동 합류(콜백에 목록 필터 없음).
#   끄기: setx HR_MICRO_CAP 0  ·  롤백: broker_gateway_v1.py.bak_20260730_hrlane 복원.
HR_WATCH_FILE        = IPC_DIR / "micro_watch_high_range.json"   # 고저폭 TOP30(08:40 생성·HR30 감시가 재생성 보장)
# ★[2026-07-30 밤·저점매수 매도기] 오버나이트 보유 목록(eod_gap_lowbuy_sell 이 발행)도 전용 통로에 합류.
#   어제 급락주가 오늘 TOP30 에서 빠져도 매도기의 2초 시세를 보장한다(그 전엔 TR 30초 폴링).
#   보유 종목이 최우선(매도 필수) — 상한 HR_MICRO_CAP 안에서 hold 먼저, TOP30 나중.
HR_HOLD_FILE         = IPC_DIR / "micro_watch_eodgap_hold.json"
HR_SCREEN            = "9250"                                    # 전용 화면(마이크로 9300대 분할과 분리·타 등록 무간섭)
try:
    HR_MICRO_CAP = max(0, int(os.environ.get("HR_MICRO_CAP", "50")))
except (TypeError, ValueError):
    HR_MICRO_CAP = 50

# ★[2026-08-01 친구님 승인 "①② 둘 다 만들어줘"] 실시간 시세 지연 실측 ① — 키움서버→우리 PC 구간.
#   발단: 매도 실측 25건에서 체결가가 신호가보다 평균 -0.136%(최악 -1.084%)인데 플러스도 10건
#         섞여 있다 = 호가 스프레드만이 아니라 '시간이 흘렀다'는 뜻.
#   재는 법: 실시간 체결 이벤트가 들고 온 '체결시각'과 우리가 그 콜백을 받은 로컬 시각의 차.
#   ⚠️해상도 1초 — 키움 체결시간은 HHMMSS 라 밀리초가 없다. "1초 이상 밀리는가"만 판정 가능.
#   ⚠️FID 20 과 908 중 어느 쪽이 값을 주는지 확실치 않아 둘 다 기록하고 실측으로 가린다.
#     MICRO_FIDS(SetRealReg 등록 문자열)는 손대지 않았다 — 등록 목록을 바꾸면 기존 구독이
#     흔들릴 수 있어서다. 등록 없이 읽히는지부터 이 계측으로 확인한다(빈 값이면 보고 후 재판단).
#   기록만 한다 — 판정·주문·스냅샷 어디에도 안 쓴다. 전체 try 격리라 실패해도 영향 0.
#   끄기: setx REAL_LAT_PROBE OFF (브로커 재시작 시 적용)
LAT_PROBE_ON         = os.environ.get("REAL_LAT_PROBE", "ON").strip().upper() == "ON"
LAT_PROBE_DIR        = BASE_DIR / "data" / "latency_probe"
LAT_PROBE_PER_CODE_SEC = 10.0   # 종목별 최소 간격(같은 종목 도배 방지)
LAT_PROBE_MAX_PER_SEC  = 5      # 전역 초당 상한(파일·CPU 부담 차단)
LAT_PROBE_COLUMNS = [
    "ts_local", "code", "fid20", "fid908", "cur", "lag20_sec", "lag908_sec",
]

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


# [SEC-ORDERCAP 2026-07-30] 게이트웨이 주문 상한.
#   기존: order_type/hoga_gb/qty>0 만 보고 수량·금액 상한이 전무 →
#         IPC 요청 파일을 쓸 수 있는 프로세스면 계좌 전액 규모 주문이 가능했다.
#   ★qty×price 상한만으로는 못 막는다 — 실주문 183건 전부 hoga_gb=06(최유리)이라 price=0.
#   ★매수(1)·매수정정(5)만 검사. 매도·취소는 통과 — 포지션 탈출을 절대 막지 않기 위해서.
#   롤백: 이 블록과 _handle_sendorder_real_request 의 상한 검사 6줄 제거
_ORDER_CAP_BUY_SIDES = (1, 5)


def _order_cap_env(name, default):
    """MICRO_CAP 과 같은 관례 — 숫자가 아니면 기본값으로 진행.

    ★[SEC-CAP-POSITIVE 2026-08-05 친구님 지시 "나머지 4개도 다 해줘"] 0 이하도
      기본값으로 되돌린다. 검사부가 `if _max > 0 and ...` 라서 그 전에는
      BROKER_MAX_ORDER_QTY=0 한 줄이면 수량 빗장이 로그 한 줄 없이 사라졌다.
      지금 이 함수를 쓰는 네 자리(수량·금액·일일건수·주문TTL)는 전부 양수여야
      뜻이 통한다 — 0 을 '무제한'으로 쓰는 자리가 하나도 없다.
      ⚠️정말로 상한을 없애야 할 일이 생기면 이 함수가 아니라 호출부에서
        눈에 보이는 이름으로 만들 것(조용히 0 으로 끄는 길은 다시 열지 말 것).
    """
    raw = os.environ.get(name, default)
    try:
        value = int(str(raw).strip())
    except Exception:
        logger.error("[SEC] %s 값이 숫자가 아님(%r) — 기본 %s 로 진행",
                     name, raw, default)
        return int(default)
    if value <= 0:
        logger.critical(
            "[SEC] %s=%r 은 상한을 끄는 값 — 무시하고 기본 %s 로 진행", name, raw, default)
        return int(default)
    return value


def _is_blanket_real_remove(req) -> bool:
    """SET_REAL_REMOVE 가 '싹 지우기'인가.

    ★[IPC-AUTH-BLANKET 2026-08-05 친구님 승인 ⓐ] screen_no/code 중 하나라도
      "ALL" 이면 참이다.
        · ("ALL", "ALL")   전 종목 실시간 해제 = SET_REAL_REMOVE_ALL 과 같은 일
        · (screen, "ALL")  그 화면 통째 — 화면 번호를 돌리면 위와 결과가 같다
        · ("ALL", code)    그 종목을 전 화면에서
      승인은 "ALL/ALL 만"이었으나 두 번째 형태로 화면을 순회하면 결과가 똑같아서
      한쪽만 ALL 이어도 서명을 요구한다. 종목 하나짜리 해제
      (screen=9001, code=005930)는 거짓이라 종전대로 무인증으로 지나간다.
      ⚠️읽을 수 없으면 참을 돌려준다 — 판단 불가일 때 열어 두면 그게 구멍이다.
    """
    try:
        screen_no = str(req.get("screen_no", "")).strip().upper()
        code = str(req.get("code", "")).strip().upper()
    except Exception:
        return True
    return screen_no == "ALL" or code == "ALL"


# ★[IPC-HARDEN 2026-08-07] DISCONNECT_SCR 조건부 관문.
#   이 명령은 무인증인데 화면 하나를 끊으면 그 화면의 실시간이 통째로 죽는다.
#   9xxx 는 전략·브로커의 실시간 구독 화면(엔진의 눈)이고, 2000~2049 는 1분봉
#   수집기의 TR 풀이다(collect_prices_1m_...:576-577 SCR_BASE=2000·POOL=50).
#   수집기는 BrokerClient 를 안 거치고 IPC json 을 직접 쓰므로 자동 서명이 안 된다
#   → PROTECTED_TYPES 에 그냥 넣으면 1분봉 수집이 깨진다. 그래서 "수집기 풀이면
#   종전대로 통과, 그 밖(=엔진의 눈)이면 서명 요구" 로 나눈다.
#   ⚠️읽을 수 없으면 참(=서명 요구)을 돌려준다. 판단 불가일 때 열어 두면 그게 구멍이다.
DISCONNECT_SCR_FREE_MIN = 2000
DISCONNECT_SCR_FREE_MAX = 2049


def _is_protected_screen(req) -> bool:
    """DISCONNECT_SCR 이 서명을 요구하는 화면인가(수집기 TR 풀 밖인가)."""
    try:
        raw = str(req.get("screen_no", "")).strip()
        if not raw.isdigit():
            return True
        number = int(raw)
    except Exception:
        return True
    return not (DISCONNECT_SCR_FREE_MIN <= number <= DISCONNECT_SCR_FREE_MAX)


def _process_snapshot_win32():
    """지금 살아있는 프로세스 목록 — 외부 실행파일에 의존하지 않는다.

    ★[SHUTDOWN-ORIGIN-FIX 2026-08-05 친구님 승인 ⓐ] wmic 이 실전에서 조용히
      빈손으로 돌아왔다(8/5 19:00:02 진짜 종료에서 payload·mtime 은 찍혔는데
      "프로세스 0건"만 남았다. 같은 명령을 셸에서 돌리면 24줄이 나온다).
      예외가 아니라 빈 출력이라 실패로도 안 보였다 = 감시 사각.
      이 경로는 같은 프로세스 안에서 OS 에 직접 물으므로 PATH·인코딩·콘솔 유무와
      무관하다. 명령줄은 못 얻지만 PID/부모PID/이름은 확실히 남는다.
    """
    import ctypes
    from ctypes import wintypes

    class _PE32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    rows = []
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # ⚠️argtypes 를 안 주면 64비트에서 HANDLE 이 잘려 스냅샷이 깨진다.
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PE32)]
        k32.Process32First.restype = wintypes.BOOL
        k32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PE32)]
        k32.Process32Next.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return rows
        try:
            entry = _PE32()
            entry.dwSize = ctypes.sizeof(_PE32)
            ok = k32.Process32First(snap, ctypes.byref(entry))
            while ok:
                rows.append("pid=%d ppid=%d %s" % (
                    entry.th32ProcessID,
                    entry.th32ParentProcessID,
                    entry.szExeFile.decode("cp949", "replace"),
                ))
                ok = k32.Process32Next(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
    except Exception as e:                      # 진단이 종료를 막으면 안 된다
        logger.info("[SHUTDOWN-ORIGIN] OS 스냅샷 실패: %s", e)
    return rows


# [SEC-ACCTMASK 2026-07-30] 로그 계좌번호 마스킹.
#   실주문 1건마다 account 평문이 broker_journal 에 남던 것을 가린다(7/30 보안점검 발견).
#   형식은 기존 관례(eod_gap_live_executor_v1.py:238)와 동일: 0000000000 → 0000**
def _mask_acct(a):
    s = str(a or "")
    return (s[:4] + "**") if len(s) >= 4 else "**"


# [GHOST-WIN 2026-07-30] 유령 주문 창 그림자 스위치.
#   클라 10초 포기 후 게이트웨이가 15초까지 실행하던 5초 창 문제 —
#   7/30 밤은 YES(그림자·로그만)로 두고 age_sec 데이터를 보기로 했었다.
#
# ★[GHOST-BLOCK-ON 2026-08-05 친구님 지시 "유령주문 차단도 켜줘"] 기본값 YES -> NO.
#   그 "7/31 에 보기로 한 데이터"를 아무도 안 봤고, 그래서 7/30 부터 8/5 까지
#   차단이 계속 꺼진 채였다. 환경변수는 User·Machine·런처 어디에도 없었다
#   = 코드 기본값 하나가 실제 동작을 정하고 있었는데 그게 '안 막음'이었다.
#
#   실측 근거(LOG\event_journal_*.jsonl, 실주문 48건 / 7·31·8·3·8·4·8·5):
#     age_sec 중앙 0.33s · p90 0.52s · 최대 1.05s · 8초 초과 0건
#     -> 문턱(min(클라 ttl, BROKER_ORDER_MAX_TTL_SEC=8))까지 7.6배 여유.
#        지난 48건 중 단 한 건도 이 차단에 걸리지 않았다.
#
#   ⚠️이 차단은 매도에도 걸린다(검사 위치가 매수한정 블록보다 앞이다).
#     거부되면 엔진은 포지션을 그대로 두고 5초 뒤 다시 판다
#     (strategy_01_rotation_engine_v2.py:1775-1781 SELL_REJECTED).
#     8/4 처럼 "팔지도 않고 장부에서 지우는" 경로가 아님을 확인하고 켰다.
#
#   🔑되돌리기는 코드 수정 없이:  setx BROKER_GHOST_SHADOW YES  (재기동 후 적용)
#     스위치를 코드 기본값으로 옮긴 이유 = 환경변수는 눈에 안 보이고 백업도 안 돼서
#     조용히 사라진다. 실제로 그렇게 6일을 꺼져 있었다.
_GHOST_SHADOW = str(os.environ.get("BROKER_GHOST_SHADOW", "NO")).strip().upper() != "NO"


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

        # ★[IPC-HARDEN 2026-08-07] 서명 재생 방지. 서명은 30초 유효라, 정당한 요청
        #   파일을 복사해 다시 넣으면 같은 명령이 한 번 더 집행됐다(실주문이면 중복 주문).
        #   프로세스 메모리에만 둔다 — 브로커가 재기동되면 옛 nonce 는 어차피 만료다.
        self._nonce_store = NonceStore()

        self._heartbeat_timer = None
        self._poll_timer      = None
        # QEventLoop.exec_() 중에도 Qt timer가 다시 발화한다. 이때 poll_requests가
        # 재진입하면 뒤 TR이 self.tr_loop/output_fields를 덮어써 앞 TR 응답을
        # 유실시킨다. 한 번의 IPC poll pass가 끝날 때까지 중첩 poll을 막는다.
        self._poll_in_progress = False
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
    _hr_watch_codes: list = []      # ★[2026-07-30] 고저폭 전용 통로 등록 상태
    _micro_screens: list = []         # 현재 실시간 등록에 쓰고 있는 화면번호(줄었을 때 해제용)
    _micro_last_upd: dict = {}        # code -> last update epoch ms (per-code throttle)
    _micro_verify_logged: int = 0
    # ★[REAL-SIDE 2026-07-22 친구님 승인] 부호 있는 체결량(FID15: +매수/-매도) 실체결 누계.
    #   code -> {"bv":매수체결량, "sv":매도체결량, "bm":매수거래대금, "sm":매도거래대금}
    #   매 체결 이벤트마다(스로틀 앞) 쌓고, 1초 flush 때 스냅샷에 병합한다. 읽기·누계뿐 — 주문 경로 무관.
    _micro_acc: dict = {}
    _micro_acc_verify_logged: int = 0
    # ★[LAT-PROBE 2026-08-01] 지연 실측 ① 버퍼(1초 flush 때 배치 append — 콜백에서 직접 파일 안 씀)
    _lat_rows: list = []
    _lat_last_by_code: dict = {}      # code -> last probe epoch
    _lat_sec_bucket: int = 0          # 현재 초(전역 상한 계산용)
    _lat_sec_count: int = 0
    _lat_empty_logged: int = 0        # FID 가 빈 값일 때 진단 로그(첫 5건만)

    def _read_micro_watch(self):
        # [REAL-MICRO 2026-06-24] 다중 소비자: micro_watch*.json (돌파/눌림/종가/스캐너) 전부 합집합 — 전략별 파일 충돌방지
        # [CAP-PRIORITY 2026-07-04 친구님] ★120캡을 set 무작위로 자르면 strategy(EOD 거래대금 100=바닥커버)·반전후보가
        #   상승주 리스트에 밀려 무작위 탈락 → 급락 바닥 구간 체결강도 통째로 누락(170920 오전 09:03~13:01).
        #   해결: 우선순위 확정 컷 — ①반전 바닥워치 ②전략 유니버스(매일 갱신 100) ③나머지(상승/돌파/종가/스캐너).
        #   strategy_watchlist.py가 "급락 바닥 시간에도 체결강도 계속 찍히게" 발행한 100을 캡이 도로 버리던 걸 살림.
        #   롤백(기존 무작위 컷) setx MICRO_CAP_PRIORITY NO.
        # ★[2026-07-29 친구님 승인 "미조치 3건도 고쳐"] 숫자가 아닌 값이 들어와도 죽지 않게.
        #   종전엔 int() 가 ValueError 를 내고 _micro_tick 의 except 가 매초 삼켜서,
        #   실시간 구독(SetRealReg)도 스냅샷 flush 도 영영 안 돌아 전 전략이 신선도 게이트에
        #   걸려 하루 종일 매수 0건이 된다(로그엔 [MICRO] tick 오류만 반복). 기본 200 으로 폴백.
        #   롤백: *.bak_20260729_microcap
        try:
            CAP = max(1, int(os.environ.get("MICRO_CAP", "200")))
        except (TypeError, ValueError):
            CAP = 200
            if not getattr(self, "_micro_cap_warned", False):
                self._micro_cap_warned = True
                logger.error("[MICRO] MICRO_CAP 값이 숫자가 아님(%r) — 기본 200 으로 진행. 환경변수 확인 필요",
                             os.environ.get("MICRO_CAP"))
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
        def _codes_of(name, today_only=False):
            try:
                d = json.loads((IPC_DIR / name).read_text(encoding="utf-8-sig"))
                watch_date = str(
                    d.get("for_date")
                    or str(d.get("ts") or "")[:10].replace("-", ""))
                if today_only and watch_date != datetime.now().strftime("%Y%m%d"):
                    logger.warning("[MICRO] stale watch ignored: %s watch_date=%s", name, watch_date)
                    return []
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
        # 골짜기·캡틴2 09:00 고정풀과 갭상승·장중급등 주입파일은 FID15를 놓치면
        # 신호가 뜬 뒤에야 관측을 시작하므로 우선 등록한다. 오늘 파일만 사용한다.
        # ★[7/12 친구님 "매도 폭탄이 서서히 줄다가 바닥"] 돈맥 급락종목도 우선 유지.
        #   정작 그 후보들의 호가잔량이 46~65% 결측이었다(reversal 파일은 7/11 엔진잠금으로 소멸·돈맥은 발행한 적 없음).
        #   micro_watch_moneyflow.json = money_flow_board_v1._publish_micro_watch (하락 -2%↓ 낙폭순 60개·30s 갱신)
        # ★[MICRO-PRIOR-FIX 2026-07-29 친구님 승인] S01·S02·S03 공용 감시를 1순위로.
        #   문제: micro_watch_strategy_shared.json(138종목)은 S01·S02·S03 신호기가 전부 쓰는
        #   공용 목록인데 PRIOR에 없어 "나머지(남는 자리)" 취급 → CAP 200이 앞에서 소진되어 0칸.
        #   실시간 가격이 안 들어오니 매수단계 스냅샷 신선도(4초)를 영영 못 넘겨 주문시도 0이었다.
        #   (7/28 실측: valley 60 + captain2 100 + premarket 62 = 222 → 이하 전부 0칸)
        #   함께 제거: micro_watch_captain2.json — 캡틴2는 은퇴한 전략인데 100칸을 점유했다.
        #   롤백: broker_gateway_v1.py.bak_20260729_microprior 복원.
        PRIOR = ["micro_watch_strategy_shared.json",  # ①S01·S02·S03 공용 감시(138)
                 "micro_watch_valley.json",         # ②골짜기 Gate1 100억 고정풀
                 "micro_watch_premarket.json",      # ③장전 예상 갭상승
                 "micro_watch_updown.json",         # ④장중 상승률 상위
                 "micro_watch_movers.json",         # ⑤장중 거래대금 급증
                 "micro_watch_strategy05.json",     # ⑥S05 장중 베이스 돌파 장전 활동주
                 "micro_watch_moneyflow.json",      # ⑥돈맥 급락종목
                 "micro_watch_reversal.json",       # ⑦반전 바닥
                 "micro_watch_strategy.json"]       # ⑧전략 EOD100
        for name in PRIOR[:6]:
            _add(_codes_of(name, today_only=True))
        for name in PRIOR[6:]:
            _add(_codes_of(name))
        try:
            for f in sorted(IPC_DIR.glob("micro_watch*.json")):            # 나머지(남는 자리만)
                if f.name in PRIOR:
                    continue
                _add(_codes_of(f.name))
        except Exception:
            pass
        return out      # [OB-FIX 2026-07-13] 우선순위 순서 그대로(돈맥 깊은바닥이 맨 앞) — 화면 분할이 이 순서를 씀

    def _read_high_range_watch(self):
        # ★[2026-07-30 친구님 승인 "고저폭 보강 ②"] 고저폭 전용 통로 판독 — 공용 _read_micro_watch 와
        #   완전 분리. 오늘(for_date) 파일만 쓴다(낡은 목록에 화면을 내주지 않기). 상한 HR_MICRO_CAP.
        if HR_MICRO_CAP <= 0:
            return []
        _today = datetime.now().strftime("%Y%m%d")
        out, seen = [], set()
        # ★[2026-07-30 밤] 1순위 = 저점매수 오버나이트 보유(매도기 발행·오늘 것만·fail-safe).
        #   파일 없음/깨짐/낡음 = 그냥 건너뜀 — 기존 TOP30 동작 무영향.
        try:
            h = json.loads(HR_HOLD_FILE.read_text(encoding="utf-8-sig"))
            if str(h.get("for_date") or "") == _today:
                for c in (h.get("codes") or []):
                    c = str(c).zfill(6)
                    if len(c) == 6 and c not in seen:
                        seen.add(c)
                        out.append(c)
                    if len(out) >= HR_MICRO_CAP:
                        return out
        except Exception:
            pass
        try:
            d = json.loads(HR_WATCH_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            return out
        watch_date = str(
            d.get("for_date")
            or str(d.get("ts") or "")[:10].replace("-", ""))
        if watch_date != _today:
            return out
        for c in (d.get("codes") or []):
            c = str(c).zfill(6)
            if len(c) == 6 and c not in seen:
                seen.add(c)
                out.append(c)
            if len(out) >= HR_MICRO_CAP:
                break
        return out

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
        # ★[REAL-SIDE 2026-07-22 친구님 승인 "실제 매수/매도 체결 분리"] 스로틀 '앞'에서 매 체결
        #   이벤트의 부호 있는 체결량(FID15: +매수/-매도)을 누계로 쌓는다 — 스로틀 뒤면 체결량 유실.
        #   새 TR·새 구독 없음(이미 오는 이벤트에서 필드만 추출). 전부 try/except 격리라
        #   어떤 실패도 기존 스냅샷 갱신·주문 경로에 영향을 못 준다.
        if "체결" in str(real_type):
            try:
                sv_raw = self.ocx.dynamicCall("GetCommRealData(QString, int)", code, 15)
                sv = float(str(sv_raw).replace(",", "").strip() or 0)   # 부호 보존(+매수/-매도)
                if sv:
                    try:
                        px = abs(float(str(self.ocx.dynamicCall(
                            "GetCommRealData(QString, int)", code, 10)).replace(",", "").strip() or 0))
                    except Exception:
                        px = 0.0
                    if px <= 0:  # 가격 추출 실패 시 최근 스냅샷 가격으로 대금 근사(체결량은 정확)
                        try:
                            px = float((self._micro_snapshot.get(code) or {}).get("cur") or 0)
                        except Exception:
                            px = 0.0
                    acc = self._micro_acc.get(code)
                    if acc is None:
                        acc = {"bv": 0.0, "sv": 0.0, "bm": 0.0, "sm": 0.0}
                        self._micro_acc[code] = acc
                    vol = abs(sv)
                    if sv > 0:
                        acc["bv"] += vol
                        acc["bm"] += vol * px
                    else:
                        acc["sv"] += vol
                        acc["sm"] += vol * px
                    # 기동 검증: 부호 데이터가 실제로 오는지 첫 15건만 로그(내일 08:35 필독)
                    if self._micro_acc_verify_logged < 15:
                        logger.info("[REAL-SIDE-VERIFY] %s FID15=%s px=%.0f → 매수량=%.0f 매도량=%.0f",
                                    code, sv_raw, px, acc["bv"], acc["sv"])
                        self._micro_acc_verify_logged += 1
            except Exception as e:
                if self._micro_acc_verify_logged < 15:
                    logger.error("[REAL-SIDE] 누계 실패 code=%s: %s", code, e)
                    self._micro_acc_verify_logged += 1
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
            # ★[OPEN-FID 2026-08-03 친구님 승인] 당일 시가(FID 16)를 스냅샷에 실는다.
            #   왜: 시가는 deep_bottom_signal_recorder 가 "09:00 그 1분에 관측된 종목"만
            #   붙잡아 왔다(hm=="0900"). 09:01 이후 구독에 들어온 종목은 하루 종일 시가가
            #   없어 S03 후보의 37%(86종목)가 OPEN_PRICE_MISSING 으로 판정 불가였다.
            #   시가는 정적 값이라 장중 어느 시점에 구독해도 정확한 값이 온다.
            #   MICRO_FIDS 는 손대지 않았다 — 주식체결 실시간에 16이 원래 실려 오는지
            #   먼저 확인한다(8/1 FID 20·908 계측과 같은 방식). 빈 값이면 등록 추가 재판단.
            #   실패해도 무해: op 가 안 실리면 소비자는 종전과 똑같이 동작한다.
            op = _num(_g("16"))
            if op:  # 0/None 은 기록하지 않는다 — 거짓 시가가 판정을 오염시키면 안 된다
                rec["op"] = op
            # ★[LOW-FID 2026-08-05 친구님 지시 "계약서에 넣어놓으면 공통으로 모든
            #   전략들이 사용 가능하지 않니?"] 당일 고가(17)·저가(18)도 같이 실는다.
            #   왜 — 전략이 각자 자기가 본 틱으로 저점을 만들면 (ㄱ)구독 이전 저점을
            #   못 보고 (ㄴ)엔진 사정으로 리셋된다. 실제로 S02 의 anchor_low 는 새 고점이
            #   찍힐 때마다 통째로 리셋돼서, 문턱을 조일수록 "저점 대비 %"는 좋아 보이는데
            #   실제 매수가는 올라갔다(8/5 원익IPS 실증: 계약서 1.439% vs 진짜 3.785%,
            #   착시폭 2.347%p). 거래소가 주는 공식 저가를 한 자리에서 실어주면
            #   S01~S06 이 전부 같은 진짜 저점을 무수정으로 쓴다.
            #   FID 16 과 같은 방식 — MICRO_FIDS(등록 목록)는 손대지 않는다. 주식체결
            #   실시간에 원래 실려 오는지 먼저 보고, 빈 값이면 등록 추가를 재판단한다.
            #   실패해도 무해: 안 실리면 소비자는 종전과 똑같이 동작한다(전부 폴백 보유).
            hi = _num(_g("17"))
            if hi:
                rec["hi"] = hi
            lo = _num(_g("18"))
            if lo:
                rec["lo"] = lo
            # ★[LAT-PROBE 2026-08-01] 지연 실측 ① — 체결 이벤트에만. 기록 전용, 전체 try 격리.
            if LAT_PROBE_ON:
                try:
                    self._lat_probe(code, _g, rec.get("cur"))
                except Exception:
                    pass
        if "호가" in rt:
            ask = _num(_g("121")); bid = _num(_g("125"))
            best_ask = _num(_g("41")); best_bid = _num(_g("51"))
            best_ask_qty = _num(_g("61")); best_bid_qty = _num(_g("71"))
            if ask is not None: rec["ask_tot"] = ask
            if bid is not None: rec["bid_tot"] = bid
            if best_ask is not None: rec["best_ask_px"] = best_ask
            if best_bid is not None: rec["best_bid_px"] = best_bid
            if best_ask_qty is not None: rec["best_ask_qty"] = best_ask_qty
            if best_bid_qty is not None: rec["best_bid_qty"] = best_bid_qty
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

    # ★[LAT-PROBE 2026-08-01 친구님 승인 "①② 둘 다 만들어줘"] 키움서버→우리 PC 지연 실측.
    #   체결 이벤트가 들고 온 체결시각(HHMMSS) 과 콜백을 받은 로컬 시각의 차 = 우리가 보는 시세가
    #   몇 초 늦은가. 해상도 1초라 "1초 이상 밀리는가"만 판정한다(밀리초는 키움이 안 준다).
    #   FID 20 / 908 둘 다 적어서 어느 쪽이 값을 주는지 실측으로 가린다.
    #   버퍼에만 담고 파일은 1초 flush 때 한 번에 쓴다 — 콜백에서 디스크를 만지지 않는다.
    def _lat_probe(self, code, getter, cur):
        now = datetime.now()
        epoch = time.time()
        # 전역 초당 상한 — 활발한 종목이 버퍼를 채우는 걸 막는다
        bucket = int(epoch)
        if bucket != self._lat_sec_bucket:
            self._lat_sec_bucket = bucket
            self._lat_sec_count = 0
        if self._lat_sec_count >= LAT_PROBE_MAX_PER_SEC:
            return
        # 종목별 간격 — 같은 종목이 표본을 독점하지 않게
        if epoch - self._lat_last_by_code.get(code, 0.0) < LAT_PROBE_PER_CODE_SEC:
            return
        self._lat_last_by_code[code] = epoch
        self._lat_sec_count += 1

        raw20 = str(getter("20") or "").strip()
        raw908 = str(getter("908") or "").strip()

        def _lag(raw):
            """HHMMSS(또는 HHMMSSmmm) → 로컬 시각과의 차(초). 형식이 아니면 빈칸."""
            digits = "".join(ch for ch in raw if ch.isdigit())
            if len(digits) < 6:
                return ""
            try:
                stamp = now.replace(
                    hour=int(digits[0:2]), minute=int(digits[2:4]),
                    second=int(digits[4:6]), microsecond=0)
            except ValueError:
                return ""
            return round((now - stamp).total_seconds(), 3)

        self._lat_rows.append({
            "ts_local":   now.isoformat(timespec="milliseconds"),
            "code":       code,
            "fid20":      raw20,
            "fid908":     raw908,
            "cur":        cur if cur is not None else "",
            "lag20_sec":  _lag(raw20),
            "lag908_sec": _lag(raw908),
        })
        # 둘 다 빈 값이면 SetRealReg 등록 목록(MICRO_FIDS)에 없어서 안 오는 것 — 첫 5건만 알린다.
        if not raw20 and not raw908 and self._lat_empty_logged < 5:
            self._lat_empty_logged += 1
            logger.info("[LAT-PROBE] %s 체결시각 FID 20·908 둘 다 빈 값 — 등록 없이는 안 오는 것으로 보임", code)

    def _lat_flush(self):
        """[LAT-PROBE 2026-08-01] 버퍼 → CSV append (1초 1회). 실패해도 시세 경로에 영향 0."""
        if not self._lat_rows:
            return
        rows, self._lat_rows = self._lat_rows, []
        try:
            path = LAT_PROBE_DIR / f"real_latency_{datetime.now():%Y%m%d}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            with path.open("a", encoding="utf-8-sig", newline="") as handle:
                writer = _csv.DictWriter(handle, fieldnames=LAT_PROBE_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            logger.error("[LAT-PROBE] 기록 실패(계측만 손실·시세 무영향): %s", e)

    def _micro_flush(self):
        if not self._micro_snapshot:
            return
        try:
            # ★[REAL-SIDE 2026-07-22] flush 직전 부호체결 누계를 스냅샷 rec에 병합(1초 1회, 저비용)
            for _c, _acc in self._micro_acc.items():
                _rec = self._micro_snapshot.get(_c)
                if _rec is not None:
                    _rec["buy_vol_cum"] = _acc["bv"]
                    _rec["sell_vol_cum"] = _acc["sv"]
                    _rec["buy_money_cum"] = _acc["bm"]
                    _rec["sell_money_cum"] = _acc["sm"]
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
            # ★[2026-07-30 친구님 승인 "고저폭 보강 ②"] 고저폭 전용 통로 등록 — 공용 경로와 독립.
            #   실패해도 공용 구독·flush 에 영향이 없게 자체 try 로 격리. optType "0" =
            #   그 화면의 기존등록 교체(전용 화면이라 타 등록 무간섭). 목록이 바뀔 때만 재등록.
            try:
                hr_codes = self._read_high_range_watch()
                if hr_codes and hr_codes != self._hr_watch_codes:
                    ret = self.ocx.dynamicCall(
                        "SetRealReg(QString, QString, QString, QString)",
                        HR_SCREEN, ";".join(hr_codes), MICRO_FIDS, "0")
                    self._hr_watch_codes = hr_codes
                    logger.info("[HR-MICRO] 고저폭 전용 %d종목 등록 (screen=%s) ret=%s",
                                len(hr_codes), HR_SCREEN, ret)
            except Exception as e:
                logger.error("[HR-MICRO] 등록 실패: %s", e)
            self._micro_flush()
            # ★[LAT-PROBE 2026-08-01] 지연 계측 버퍼를 1초 1회 CSV 로 흘린다. 자체 try 격리 —
            #   계측이 죽어도 위의 시세 flush 는 이미 끝난 뒤라 영향이 없다.
            if LAT_PROBE_ON:
                try:
                    self._lat_flush()
                except Exception:
                    pass
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
    def _ipc_auth_ok(self, request_id, req, expected_type, tag) -> bool:
        """서명 통과면 True. 실패면 거부 응답까지 쓰고 False.

        ★[IPC-AUTH-BLANKET 2026-08-05] 잠글 분기가 넷이 되면서 같은 12줄을 네 번
          쓰게 돼 한 곳으로 모았다.
        ★[IPC-HARDEN 2026-08-07] 재생 방지를 여기에 넣었다. 이제 실주문 경로
          (SENDORDER_REAL·SET_REAL_REMOVE_ALL)도 이 함수를 쓴다 — 재생 방지가
          가장 필요한 게 바로 그 둘이라 더는 예외로 둘 이유가 없다.
        """
        auth_ok, auth_error = verify_order_request(req, expected_type=expected_type)
        # 저장소가 없으면 여기서 만든다. __init__ 을 거치지 않고 만들어진 인스턴스에서
        # 방어가 조용히 빠지는 것을 막는다(그런 경로가 실제로 있다 — 시험이 그렇게 만든다).
        store = getattr(self, "_nonce_store", None)
        if store is None:
            store = self._nonce_store = NonceStore()
        if auth_ok and not store.consume(str(req.get("auth_nonce") or "")):
            auth_ok, auth_error = False, "auth nonce already used (replay)"
        if auth_ok:
            return True
        logger.error(
            "[%s] rejected request_id=%s caller=%s reason=%s",
            tag, request_id, str(req.get("caller") or "")[:40], auth_error,
        )
        self._write_response(
            request_id, status="ERROR",
            error=f"{expected_type} authentication rejected: {auth_error}",
        )
        return False

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
                # ★[IPC-AUTH-SHUTDOWN 2026-08-06 친구님 지시 "지금해"] 서명 필수로 전환.
                #   무인증이면 IPC\requests 에 쓸 수 있는 코드가 브로커를 꺼 엔진 전체를
                #   눈멀게 한다(워치독은 하트비트/프리징만 보므로 못 잡는다). 유일 발신자
                #   broker_night_stop.ps1 은 broker_client 경유라 PROTECTED_TYPES 추가만으로
                #   자동 서명된다 — 야간정지 스크립트는 무수정. SHUTDOWN 분기는 장중 미발동
                #   (19:00 야간정지에만) 이라 이 변경이 장중 매매에 닿는 경로는 없다.
                if self._ipc_auth_ok(request_id, req, "SHUTDOWN",
                                     "SEC-SHUTDOWN-AUTH"):
                    self._handle_shutdown_request(request_id, req, req_path)
            elif req_type == "DISCONNECT_SCR":
                # ★[IPC-HARDEN 2026-08-07] 수집기 TR 풀(2000~2049)은 종전대로 무인증,
                #   그 밖의 화면(9xxx = 전략 실시간 구독 = 엔진의 눈)은 서명 필수.
                #   _is_protected_screen 주석 참조.
                if (not _is_protected_screen(req)) or self._ipc_auth_ok(
                        request_id, req, "DISCONNECT_SCR",
                        "SEC-DISCONNECTSCR-AUTH"):
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
                # ★[IPC-AUTH-BLANKET 2026-08-05 친구님 승인 ⓐ] 서명 필수로 전환.
                #   이 명령은 성공하면 _realreg_state 에 남아 broker_state.json 으로
                #   디스크에 적히고(:1897 _save_realreg_state), 재기동 때
                #   _replay_realreg() 가 되살린다. 남의 화면 번호를 덮어쓰면
                #   껐다 켜도 안 돌아온다 — 실시간 해제보다 오래 가는 공격이다.
                #   정당한 호출자는 0건(구독은 브로커가 자체 OCX 로 한다).
                if self._ipc_auth_ok(request_id, req, "SETREAL_REG",
                                     "SEC-SETREALREG-AUTH"):
                    self._handle_setreal_reg_request(request_id, req)
            elif req_type == "SET_REAL_REMOVE":
                # [E1 2026-05-14] SetRealRemove 위임 (실시간 시세 해제)
                # ★[IPC-AUTH-BLANKET 2026-08-05 친구님 승인 ⓐ] 전면 해제만 서명 필수.
                #   8/4 에 SET_REAL_REMOVE_ALL 을 잠갔는데 이 명령에 "ALL" 을 넣으면
                #   같은 일이 무인증으로 그대로 됐다(:1976 설명서에 그렇게 적혀 있다).
                #   즉 8/4 잠금은 앞문만 잠근 것이었다.
                #   종목 하나짜리 해제는 종전대로 통과한다 — _is_blanket_real_remove 참조.
                if (not _is_blanket_real_remove(req)) or self._ipc_auth_ok(
                        request_id, req, "SET_REAL_REMOVE",
                        "SEC-REALREMOVE-AUTH"):
                    self._handle_set_real_remove_request(request_id, req)
            elif req_type == "GET_COMM_REAL_DATA":
                # [D1 2026-05-14] GetCommRealData 위임 (실시간 데이터 추출)
                self._handle_get_comm_real_data_request(request_id, req)
            elif req_type == "GET_REAL_REG_GRP":
                # [B2 2026-05-14] GetRealRegGroup 위임 (실시간 등록 그룹 조회)
                self._handle_get_real_reg_grp_request(request_id, req)
            elif req_type == "SET_REAL_REMOVE_ALL":
                # ★[IPC-AUTH-SCOPE 2026-08-04] 전 종목 실시간 해제는 서명된 요청만.
                #   브로커를 살려 둔 채 엔진 전체를 눈멀게 하는 명령이라 워치독
                #   (하트비트·프리징 감시)이 절대 못 잡는다. 정당한 호출자는 0건이다.
                # ★[IPC-HARDEN 2026-08-07] 재생 방지 포함(_ipc_auth_ok).
                if self._ipc_auth_ok(request_id, req, "SET_REAL_REMOVE_ALL",
                                     "SEC-REALREMOVE-AUTH"):
                    # [B3 2026-05-14] SetRealRemove("ALL","ALL") 명시 단축 (EOD 정리)
                    self._handle_set_real_remove_all_request(request_id, req)
            elif req_type == "KOA_FUNCTIONS":
                # [F1 2026-05-14] KOA_Functions 위임 (자동로그인 설정 등 키움 확장 함수)
                self._handle_koa_functions_request(request_id, req)
            elif req_type == "SENDORDER_SHADOW":
                self._handle_sendorder_shadow_request(request_id, req)
            elif req_type == "SENDORDER_REAL":
                # 실주문은 공유 비밀키 HMAC가 일치하는 최신 요청만 집행한다.
                # ★[IPC-HARDEN 2026-08-07] 재생 방지 포함(_ipc_auth_ok). 서명 사본을
                #   30초 안에 다시 넣으면 같은 주문이 두 번 나가던 구멍을 막는다.
                if self._ipc_auth_ok(request_id, req, "SENDORDER_REAL",
                                     "SEC-ORDER-AUTH"):
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
                engine_name, _mask_acct(account), code, qty,
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
            # ★[SEC-PATHTRAV 2026-08-07 보안검사 지적] 7/30 에 _write_response 는
            #   막았는데 이 분기만 원본 request_id 를 그대로 이어붙였다. 무인증
            #   SENDORDER_SHADOW 로 request_id="..\..\..\어딘가\파일" 을 보내면
            #   실측상 C:\PROOF.json 까지 나간다. 브로커는 Highest(관리자)로 뜨므로
            #   UAC 창 없는 관리자 권한 파일 쓰기가 된다 — 오늘 파이썬을 RX 로
            #   강등한 조치를 우회하는 경로다.
            _shadow_rid = self._safe_request_id(request_id)
            if _shadow_rid is None:
                logger.warning("[SEC] SENDORDER_SHADOW request_id 형식 위반 — 격리: %r",
                               str(request_id)[:120])
                _shadow_rid = "rejected_request_id"
            shadow_path = IPC_ORDER_SHADOW_DIR / f"{_shadow_rid}.json"
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
    def _load_buy_count(self, today: str):
        """오늘 이미 몇 건 샀는지 디스크에서 복원해 (날짜, 건수) 로 돌려준다.

        ★[SEC-DAILYCAP-PERSIST 2026-08-05 친구님 지시 "나머지 4개도 다 해줘"]
          _buy_count 가 메모리 변수뿐이라 브로커를 다시 띄우면 0 이 됐다.
          워치독이 자동 재기동하므로 BROKER_MAX_DAILY_BUY=100 은 '하루 100건'이
          아니라 '브로커 수명당 100건'이었다.
          ⚠️읽기 실패는 0 으로 시작한다(fail-open). 파일 하나 깨졌다고 그날 매수를
            통째로 막는 쪽이 더 위험하다 — 대신 CRITICAL 로 남겨 아침에 보이게 한다.
        """
        try:
            if not BUY_COUNT_FILE.exists():
                return today, 0
            saved = json.loads(BUY_COUNT_FILE.read_text(encoding="utf-8-sig"))
            if str(saved.get("date") or "") != today:
                return today, 0             # 어제 파일 — 오늘은 0 부터
            restored = max(0, int(saved.get("count") or 0))
            if restored:
                logger.warning(
                    "[SEC-ORDERCAP] 오늘 매수 %d건을 디스크에서 복원 — "
                    "재기동해도 일일 상한이 초기화되지 않는다", restored)
            return today, restored
        except Exception as e:
            logger.critical(
                "[SEC-ORDERCAP] 일일 매수 카운트 복원 실패 — 0 에서 시작한다: %s", e)
            return today, 0

    def _save_buy_count(self):
        """증가할 때마다 원자적으로 기록. 실패해도 주문 경로는 막지 않는다."""
        try:
            tmp = BUY_COUNT_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"date": self._buy_count_date,
                            "count": int(self._buy_count),
                            "ts": datetime.now().isoformat()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(BUY_COUNT_FILE))
        except Exception as e:
            logger.error("[SEC-ORDERCAP] 일일 매수 카운트 저장 실패: %s", e)

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

    # [SEC-ORDERCAP 2026-07-30] 일일 매수 건수 카운터 (브로커가 매일 재기동되므로 메모리로 충분)
    _buy_count_date: str = ""
    _buy_count: int = 0

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

        # [GHOST-WIN 2026-07-30] 주문 유예 상한 — 클라 값이 더 커도 이 값으로 자른다.
        #   상한 검사보다 앞: 낡아서 버릴 주문이 일일 매수 카운트를 소모하면 안 된다.
        #   ts 없음/깨짐 = 나이 판정 불가 → 차단하지 않는다(fail-open·주문 경로 보수).
        _eff_ttl = min(int(req.get("ttl_sec", 15)), _order_cap_env("BROKER_ORDER_MAX_TTL_SEC", 8))
        try:
            _req_age = (datetime.now() - datetime.fromisoformat(str(req.get("ts", "")))).total_seconds()
        except Exception:
            _req_age = -1.0
        if _req_age > _eff_ttl:
            if _GHOST_SHADOW:          # 그림자 모드 — 로그만 남기고 통과
                logger.warning("[GHOST-SHADOW] 실거부였으면 차단됐을 주문 age=%.2fs > %ds code=%s",
                               _req_age, _eff_ttl, code)
            else:
                logger.critical("[GHOST-BLOCK] 늦은 주문 거부 age=%.2fs > %ds code=%s",
                                _req_age, _eff_ttl, code)
                self._write_response(request_id, status="ERROR",
                    error=f"ORDER_TTL: 접수 지연 {_req_age:.2f}s > {_eff_ttl}s")
                return

        # [SEC-ORDERCAP 2026-07-30] 주문 상한 — 매수 계열만 검사
        if order_type in _ORDER_CAP_BUY_SIDES:
            _max_qty   = _order_cap_env("BROKER_MAX_ORDER_QTY", 5)
            _max_krw   = _order_cap_env("BROKER_MAX_ORDER_KRW", 1000000)
            _max_daily = _order_cap_env("BROKER_MAX_DAILY_BUY", 100)
            _today = datetime.now().strftime("%Y%m%d")
            if self._buy_count_date != _today:
                # ★[SEC-DAILYCAP-PERSIST 2026-08-05] 여기 한 곳이 두 경우를 다 덮는다.
                #   · 프로세스가 방금 떴다(_buy_count_date="")  -> 디스크에서 복원
                #   · 날짜가 바뀌었다                          -> 파일 날짜가 달라 0
                #   그 전에는 무조건 0 이라 재기동이 곧 상한 초기화였다.
                self._buy_count_date, self._buy_count = self._load_buy_count(_today)

            _deny = None
            if _max_qty > 0 and qty > _max_qty:
                _deny = f"수량 상한 초과 (qty={qty} > {_max_qty})"
            elif _max_krw > 0 and price > 0 and qty * price > _max_krw:
                _deny = f"금액 상한 초과 (qty*price={qty * price} > {_max_krw})"
            elif _max_daily > 0 and self._buy_count >= _max_daily:
                _deny = f"일일 매수 건수 상한 초과 ({self._buy_count} >= {_max_daily})"

            # ★[2026-07-31 친구님 승인 #4] 시장가·최유리(price=0)는 위 금액 검사를
            #   그냥 통과하던 구멍(조건이 price > 0). 저점매수·종가매수가 전부
            #   price=0, hoga_gb=06 이라 금액 상한이 사실상 무력했다.
            #   구독 중인 종목이면 _micro_snapshot 의 최근가(cur)로 추정 검사.
            # ★[2026-08-01 친구님 승인 "구멍도 메꿔줘"] 미구독 종목 fail-open 봉합 —
            #   ① 구독에 없으면 키움 마스터 전일가 × 1.3(상한가 여유)으로 보수 추정
            #     (마스터는 로그인 때 메모리에 실리는 값 — 조회 지연·TR 소모 없음).
            #   ② 그래도 가격을 못 구하면: 1주는 통과(금액이 저절로 유계),
            #     2주 이상은 차단(fail-close). 현 체제는 전부 1주라 실전 무영향.
            #   부작용 한도: 전일가 77만원 이상 종목의 1주 시장가는 ×1.3 추정이 100만
            #   상한을 넘겨 거부될 수 있음(로그 CRITICAL로 보임) — 그때는 BROKER_MAX_ORDER_KRW 조정.
            #   롤백: backup\broker_gateway_v1_20260801_capfix.py 복원.
            if _deny is None and _max_krw > 0 and price == 0:
                try:
                    _est = abs(float((self._micro_snapshot.get(code) or {}).get("cur") or 0))
                except Exception:
                    _est = 0.0
                if _est <= 0:
                    try:
                        _mlp = str(self.ocx.dynamicCall(
                            "GetMasterLastPrice(QString)", code)).replace(",", "").strip()
                        _est = abs(float(_mlp or 0)) * 1.3
                    except Exception:
                        _est = 0.0
                if _est > 0 and qty * _est > _max_krw:
                    _deny = (f"금액 상한 초과 (시장가 추정 qty*{_est:.0f}"
                             f"={qty * _est:.0f} > {_max_krw})")
                elif _est <= 0:
                    if qty <= 1:
                        logger.warning(
                            "[SEC-ORDERCAP] 시장가 code=%s 추정가 없음 — 1주 주문이라 통과(금액 유계)",
                            code)
                    else:
                        _deny = (f"시장가 추정가 없음 + 다수량 (qty={qty}) — "
                                 f"금액 검사 불가로 차단")

            if _deny:
                logger.critical("[SEC-ORDERCAP] 매수 차단 — %s | code=%s key=%s",
                                _deny, code, idempotency_key)
                self._write_response(request_id, status="ERROR",
                    error=f"ORDER_CAP: {_deny}")
                return
            self._buy_count += 1
            # ★[SEC-DAILYCAP-PERSIST 2026-08-05] 실제 SendOrder 직전에 남긴다.
            #   증가만 하고 안 적으면 재기동으로 그대로 사라진다(고치려던 그 병).
            self._save_buy_count()

        logger.info(
            "[SENDORDER-REAL] key=%s account=%s code=%s qty=%d price=%d type=%d hoga=%s rqname=%s",
            idempotency_key, _mask_acct(account), code, qty, price, order_type, hoga_gb, rqname,
        )                        # ↑ [SEC-ACCTMASK] 로그 인자만 마스킹 — SendOrder 에는 원본이 간다

        # [ORDER-EVT 2026-07-30] 접수→실행 지연 기록. ②(유령 창) 판단의 유일한 근거.
        #   기존 event_journal 엔 CHEJAN(체결)뿐이라 "언제 접수해서 언제 쐈는지"가 없었다.
        #   클라가 넣어주는 req["ts"](broker_client.py:206)와 지금 시각의 차 = age_sec.
        #   _emit_event 는 내부가 try/except:pass 인 fail-safe → 주문 경로 영향 0.
        _age_sec = -1.0
        try:
            _age_sec = round(
                (datetime.now() - datetime.fromisoformat(str(req.get("ts", "")))).total_seconds(), 3)
        except Exception:
            pass
        _emit_event("ORDER_SUBMITTED", entity="order", entity_id=idempotency_key, payload={
            "code": code, "qty": qty, "order_type": order_type, "hoga_gb": hoga_gb,
            "rqname": rqname, "request_id": request_id,
            "ts_client": str(req.get("ts", "")),
            "age_sec": _age_sec,                                    # ★7/31 아침에 볼 숫자
            "ttl_sec": int(req.get("ttl_sec", self.DEFAULT_TTL_SEC)),
        })

        _t0 = datetime.now()
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
            # [ORDER-EVT 2026-07-30] 실행 결과 + SendOrder 자체 소요
            _emit_event("ORDER_RESULT", entity="order", entity_id=idempotency_key, payload={
                "code": code, "ret": ret_int, "ok": ok,
                "send_ms": round((datetime.now() - _t0).total_seconds() * 1000, 1),
            })
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

    # ★[IPC-HARDEN 2026-08-07] BATCH_TR 상한. 무인증 명령인데 종목수·시간이 무제한이라
    #   한 번의 요청으로 브로커를 몇 시간 붙잡을 수 있었다. 그동안 매도 주문이 전부
    #   밀리는데 하트비트는 batch 안에서 강제 갱신되므로(위 HB_INTERVAL) 워치독이
    #   "정상"으로 본다 = 감시 사각. 정당한 사용은 수집기의 CHUNK_SIZE=15·60초뿐
    #   (collect_prices_1m_...:3063). 3배 여유를 두고 막는다.
    #   종목수는 자르지 않고 거부한다 — 조용히 자르면 부분 결과가 정상으로 보인다.
    BATCH_TR_MAX_CODES = 50
    BATCH_TR_MAX_BATCH_SEC = 120.0
    BATCH_TR_MAX_PER_REQ_SEC = 15.0

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
        # ★[IPC-HARDEN 2026-08-07] 상한 검사. 위 주석 참조.
        if len(codes) > self.BATCH_TR_MAX_CODES:
            logger.error("[SEC-BATCHTR-CAP] rejected request_id=%s codes=%d > %d caller=%s",
                         request_id, len(codes), self.BATCH_TR_MAX_CODES,
                         str(req.get("caller") or "")[:40])
            self._write_response(request_id, status="ERROR",
                error=(f"BATCH_TR: codes {len(codes)} exceeds cap "
                       f"{self.BATCH_TR_MAX_CODES}"))
            return
        # ⚠️[NaN 2026-08-07 보안검사 지적] 부등호를 뒤집어 쓴다.
        #   `if x > MAX` 로 쓰면 x 가 NaN 일 때 비교가 거짓이라 상한을 그냥 지나간다.
        #   json.loads 는 JSON 리터럴 NaN 도, 문자열 "nan" 도 float('nan') 으로 받는다.
        #   그 뒤 루프 중단 조건(경과 > batch_to)도 NaN 비교라 영원히 거짓 = 배치가
        #   안 멈춘다. 실측: "Infinity"·999999 는 정상 절단되는데 NaN 만 뚫렸다.
        #   `not (x <= MAX)` 는 NaN 에서 참이 되므로 이상값이 전부 상한으로 눌린다.
        if not (batch_to <= self.BATCH_TR_MAX_BATCH_SEC):
            logger.warning("[SEC-BATCHTR-CAP] batch_timeout %r -> %.1f (request_id=%s)",
                           batch_to, self.BATCH_TR_MAX_BATCH_SEC, request_id)
            batch_to = self.BATCH_TR_MAX_BATCH_SEC
        if not (per_request_to <= self.BATCH_TR_MAX_PER_REQ_SEC):
            logger.warning("[SEC-BATCHTR-CAP] per_request_timeout %r -> %.1f (request_id=%s)",
                           per_request_to, self.BATCH_TR_MAX_PER_REQ_SEC, request_id)
            per_request_to = self.BATCH_TR_MAX_PER_REQ_SEC

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
        # ★[IPC-HARDEN 2026-08-07] ShowAccountWindow 삭제.
        #   read-only 가 아니라 계좌비밀번호 저장 창을 브로커 화면에 띄우는 명령이라
        #   무인증 IPC 로 계좌 설정 UI 를 열 수 있었다. 코드베이스 호출자 0건
        #   (문서 2곳에만 언급). 다시 필요하면 그때 서명 대상으로 넣을 것.
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

    def _log_shutdown_origin(self, request_id, req=None, req_path=None):
        """[SHUTDOWN-ORIGIN 2026-08-04] 정지명령 발신자 흔적 기록.

        8/3 10:40:58 정지명령으로 27초 시세 공백이 났는데 저널에 request_id 밖에 없어
        누가 보냈는지 끝내 못 찾았다(7/17 에 이어 두 번째). 종료 직전 1회만 찍는다.
        IPC 가 파일 기반이라 발신자를 OS 로 역추적할 수 없다 — 요청 내용과
        "그때 살아있던 프로세스" 목록이 다음 조사의 유일한 단서가 된다.
        어떤 단계가 실패해도 종료 자체는 막지 않는다.
        """
        try:
            payload = json.dumps(req, ensure_ascii=False) if req is not None else "(없음)"
            logger.info("[SHUTDOWN-ORIGIN] payload=%s", payload[:1000])
        except Exception as e:
            logger.info("[SHUTDOWN-ORIGIN] payload 기록 실패: %s", e)

        try:
            if req_path is not None:
                mtime = datetime.fromtimestamp(
                    req_path.stat().st_mtime
                ).isoformat(timespec="seconds")
                logger.info(
                    "[SHUTDOWN-ORIGIN] file=%s mtime=%s", req_path, mtime,
                )
        except Exception:
            pass

        # ★[SHUTDOWN-ORIGIN-FIX 2026-08-05 친구님 승인 ⓐ] wmic 이 실전에서 빈손이었다.
        #   8/5 19:00:02 진짜 종료(uuid·실제 파일경로)에서 payload·mtime 은 남았는데
        #   "프로세스 0건"만 찍혔다. 브로커 자신이 python 인데 0건 = 출력이 비어서 왔다.
        #   예외가 아니라 빈 출력이라 실패로 보이지도 않았다 — 8/4 에 만든 이 추적기가
        #   그동안 아무것도 안 남기고 있었다는 뜻이다(감시 사각).
        #   ① 명령줄이 남는 wmic 은 그대로 시도하고 ② 빈손이면 OS 에 직접 묻는
        #   경로로 반드시 한 번 더 남긴다. 0건은 이제 결론이 아니라 경고다.
        keys = ("python", "powershell", "cmd.exe", "wscript", "cscript")
        keep = []
        try:
            import subprocess
            out = subprocess.run(
                ["wmic", "process", "get",
                 "ProcessId,ParentProcessId,Name,CommandLine", "/format:csv"],
                # ★[SHUTDOWN-ORIGIN-ORDER 2026-08-04] 5 -> 3초. 종료가 그만큼
                #   늦어지고, wmic 은 Windows 가 걷어내는 중이라 언젠가 그냥
                #   실패한다(그때도 아래 except 로 삼키고 종료는 진행한다).
                capture_output=True, text=True, timeout=3,
                encoding="cp949", errors="replace",
                creationflags=0x08000000,   # CREATE_NO_WINDOW - 콘솔 창 튀는 것 방지
            ).stdout or ""
            keep = [ln.strip() for ln in out.splitlines()
                    if ln.strip() and any(k in ln.lower() for k in keys)]
            logger.info("[SHUTDOWN-ORIGIN] wmic %d건", len(keep))
        except Exception as e:
            logger.info("[SHUTDOWN-ORIGIN] wmic 실패: %s", e)

        if not keep:
            rows = _process_snapshot_win32()
            keep = [r for r in rows if any(k in r.lower() for k in keys)]
            logger.warning(
                "[SHUTDOWN-ORIGIN] wmic 이 빈손 — OS 스냅샷으로 대체 (전체 %d개 중 %d개)",
                len(rows), len(keep),
            )
        logger.info("[SHUTDOWN-ORIGIN] 그때 살아있던 프로세스 %d건", len(keep))
        for line in keep[:40]:
            logger.info("[SHUTDOWN-ORIGIN]   %s", line[:400])

    def _handle_shutdown_request(self, request_id, req=None, req_path=None):
        """IPC SHUTDOWN command — graceful shutdown via IPC (Windows 호환)."""
        logger.info("IPC shutdown command received (request_id=%s)", request_id)
        # 1. 응답 먼저 작성 (client 가 확인 가능하도록)
        self._write_response(
            request_id, status="OK",
            data={"shutdown": True, "state": self.state.value},
        )
        # ★[SHUTDOWN-ORIGIN-ORDER 2026-08-04] 발신자 추적을 응답 뒤로 옮겼다.
        #   원래 이 줄이 _write_response 앞에 있어서, wmic 이 걸리는 시간만큼
        #   client 를 붙잡았다(바로 위 주석 "응답 먼저 작성"과도 어긋났다).
        #   프로세스 목록은 몇 ms 뒤에 찍어도 내용이 같으므로 추적 가치는 그대로다.
        #   진단이 종료를 막으면 안 되므로 여기서 한 번 더 감싼다(내부에도 try 가 있지만
        #   그건 _log_shutdown_origin 안에서만 보장된다).
        try:
            self._log_shutdown_origin(request_id, req, req_path)
        except Exception as e:
            logger.info("[SHUTDOWN-ORIGIN] 발신자 추적 건너뜀: %s", e)
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
    # [SEC-PATHTRAV 2026-07-30] request_id 경로조작 차단
    # ───────────────────────────────────────────────────────────
    # 기존: 요청 JSON 의 request_id 를 무검증으로 f"{request_id}.json" 경로에 사용.
    #       "..\..\config\x" 나 "C:/Windows/Temp/x" 로 IPC\responses 를 벗어나
    #       관리자 권한 임의 .json 덮어쓰기가 가능했다(7/30 보안점검 발견).
    # 정상 client 는 전부 str(uuid.uuid4()) → 영숫자+하이픈만 나온다(전수확인).
    # 롤백: 이 메서드와 _write_response 첫 3줄 제거 (bak_20260730_night)
    _RID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

    def _safe_request_id(self, raw):
        """응답 파일명으로 안전한 request_id 만 통과. 아니면 None."""
        rid = str(raw).strip()
        if rid and len(rid) <= 80 and all(ch in self._RID_ALLOWED for ch in rid):
            return rid
        return None

    # ───────────────────────────────────────────────────────────
    # IPC: Response 작성
    # ───────────────────────────────────────────────────────────
    def _write_response(self, request_id, status, data=None, error=None):
        # [SEC-PATHTRAV 2026-07-30] 파일명이 IPC\responses 밖으로 못 나가게 한다
        _safe = self._safe_request_id(request_id)
        if _safe is None:
            logger.warning("[SEC] request_id 형식 위반 — 응답 격리: %r", str(request_id)[:120])
            _safe = "rejected_request_id"
        request_id = _safe
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
        if self._poll_in_progress:
            return
        self._poll_in_progress = True
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
        finally:
            self._poll_in_progress = False

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

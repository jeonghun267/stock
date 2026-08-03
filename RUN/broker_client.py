# -*- coding: utf-8 -*-
"""
broker_client.py  [H1 2026-05-14]

broker_gateway_v1 IPC 클라이언트 공통 라이브러리.

목적:
  현재 collector / investor_daily / EOD 가 각각 ~70줄씩 IPC client 코드 복붙.
  본 모듈로 통합하여 ~30줄 호출만으로 사용 가능.
  sub-process 측 단순화 + 향후 STEP-3.1/3.2 적용 시 SIGA sell / buy_sender 등도
  자체 OCX 제거 후 본 모듈만 import 하여 broker IPC 사용.

호환성:
  기존 sub-process 의 자체 _broker_*** 함수는 그대로 동작. 본 모듈은 신규 옵션.
  점진 마이그레이션 (위험 0).

import 예:
  from broker_client import BrokerClient
  bc = BrokerClient()
  if bc.alive():
      res = bc.tr("opt10059", inputs={...}, output_fields=[...])
      data = bc.master_info("GetMasterCodeName", "035720")
      ok  = bc.setreal_reg("9001", "035720", "10;13;15", "0")

설계 원칙:
  - read-only 인터페이스 (실주문은 broker SHADOW 만 지원 — 사용자 정책)
  - broker dead 시 self.alive() == False → sub-process 가 fallback 진입
  - timeout / retry 는 sub-process 가 결정 (본 모듈은 단발 호출만)
  - file-based IPC (broker_gateway_v1.py 와 동일 protocol)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


_DEFAULT_IPC_BASE = Path(r"C:\stock_bot\IPC")
_DEFAULT_HB_STALE_SEC = 15.0

# [GHOST-WIN 2026-07-30] 실주문 유예 여백(초).
#   기존: request()가 ttl_sec = timeout+5 를 기본 부여 → 클라가 10초에 포기한 주문을
#   게이트웨이가 15초까지 실행하는 5초 유령 창. 실주문만 timeout-2초로 조여 창을 없앤다.
#   TR·BATCH_TR 은 종전대로(낡은 조회는 무해하지만 낡은 주문은 위험).
_GHOST_MARGIN_SEC = 2


# ─────────────────────────────────────────────────────────
# [TR-CALLER 2026-07-11] 화면0001 호출자 특정 수술 — 모든 요청에 호출자 서명
# 배경: broker_journal의 OnReceiveTrData 라인은 rqname/screen_no만 남는데,
#   기본값 호출(rqname=opt10080_req·screen 0001)은 익명 → 7/9~7/10 과다조회
#   1등 소비자(7/10 하루 9,276건)를 특정 못 함.
# 효과: ①모든 IPC payload에 "caller" 필드(게이트웨이는 모르는 키 무시=하위호환)
#   ②rqname 미지정 시 기본 rqname에 진입 스크립트 이름 포함
#     (예: opt10080_req → opt10080_reversal_live_executor_v1) → 기존 저널
#     라인만으로 호출자 집계 가능. 게이트웨이(브로커 본체) 무수정.
#   rqname을 명시하는 호출자(수집기 opt10080_req 등)는 영향 0.
# 덮어쓰기: env BROKER_CALLER. 롤백: broker_client.py.bak_caller_20260711
# ─────────────────────────────────────────────────────────
def _detect_caller() -> str:
    try:
        import sys
        import re
        raw = os.environ.get("BROKER_CALLER", "").strip()
        if not raw:
            raw = Path(sys.argv[0]).stem if (sys.argv and sys.argv[0]) else ""
        raw = re.sub(r"[^A-Za-z0-9_\-]", "", raw)[:28]
        return raw or "adhoc"
    except Exception:
        return "unknown"


_CALLER = _detect_caller()


# ─────────────────────────────────────────────────────────
# [W3 2026-05-15] PID alive 보조 검사 (Windows ctypes)
# broker_gateway L218 is_pid_alive 와 동일 패턴 —
# heartbeat fresh + process dead race 차단 (5/15 09:25 사례 보강)
# ─────────────────────────────────────────────────────────
def _is_pid_alive(pid: int) -> bool:
    """Windows process alive 검사. STILL_ACTIVE (259) 검증."""
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                h, ctypes.byref(exit_code))
            if not ok:
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            try:
                ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass
    except Exception:
        return False


# [시총 잡주차단 2026-06-30 친구님 "가격3000+시총1000억"] 발행주식수 캐시(mtime 갱신).
_SHARES_CACHE: Dict[str, float] = {}
_SHARES_MTIME: float = 0.0
_SHARES_CSV = r"C:\stock_bot\DATA\shares_outstanding.csv"


def _load_shares_cache() -> Dict[str, float]:
    """code(6자리) -> 발행주식수 dict. CSV mtime 변하면 재로드. 실패시 기존/빈 dict(fail-open)."""
    global _SHARES_CACHE, _SHARES_MTIME
    try:
        mt = os.path.getmtime(_SHARES_CSV)
        if mt == _SHARES_MTIME and _SHARES_CACHE:
            return _SHARES_CACHE
        out: Dict[str, float] = {}
        with open(_SHARES_CSV, encoding="utf-8-sig") as f:
            header = f.readline().strip().split(",")
            try:
                ci = header.index("code"); si = header.index("shares")
            except ValueError:
                ci, si = 0, 2
            for line in f:
                parts = line.rstrip("\n").split(",")
                if len(parts) <= max(ci, si):
                    continue
                code = parts[ci].strip().zfill(6)
                try:
                    sh = float(parts[si] or 0)
                except Exception:
                    sh = 0.0
                if code and sh > 0:
                    out[code] = sh
        if out:
            _SHARES_CACHE = out; _SHARES_MTIME = mt
        return _SHARES_CACHE
    except Exception:
        return _SHARES_CACHE


class BrokerClient:
    """broker_gateway_v1 IPC 단일 클라이언트.

    Thread-safe X (각 caller 가 자기 인스턴스 사용 권장).
    """

    def __init__(self, ipc_base: Path = _DEFAULT_IPC_BASE,
                 hb_stale_sec: float = _DEFAULT_HB_STALE_SEC):
        self._ipc_base = Path(ipc_base)
        self._hb_file  = self._ipc_base / "broker_heartbeat.json"
        self._req_dir  = self._ipc_base / "requests"
        self._res_dir  = self._ipc_base / "responses"
        # [J1 2026-05-14] broadcast 구독 디렉터리 (broker_gateway_v1.py 와 동일)
        self._chejan_dir       = self._ipc_base / "chejan_events"
        self._real_data_dir    = self._ipc_base / "real_data"
        self._msg_events_dir   = self._ipc_base / "msg_events"
        self._order_ack_dir    = self._ipc_base / "order_shadow_ack"
        self._hb_stale_sec = float(hb_stale_sec)

    # ──────────────────────────────────────────────────────────
    # broker 가용성 검사
    # ──────────────────────────────────────────────────────────
    def alive(self) -> bool:
        """heartbeat.json mtime 검사 + [W3 2026-05-15] PID alive 보조 검사.

        검사 순서:
          1. heartbeat 파일 존재 + age < stale_sec
          2. heartbeat 안 pid 추출 후 Windows process alive 검증 (false positive 차단)
        PID 검사 실패 시 heartbeat fresh로만 판정 (안전 default).
        """
        try:
            if not self._hb_file.exists():
                return False
            age = time.time() - self._hb_file.stat().st_mtime
            if age >= self._hb_stale_sec:
                return False
            # [W3] PID alive 보조 — broker dead 후 5s lag race 차단
            try:
                hb = json.loads(self._hb_file.read_text(encoding="utf-8-sig"))
                broker_pid = int(hb.get("pid", 0) or 0)
                if broker_pid > 0 and not _is_pid_alive(broker_pid):
                    return False
                # [R 2026-05-21 Path A1] state 검증 추가 — broker 정상 종료/SHUTDOWN/RECONNECTING 시 차단
                # 5/21 broker 3차 사망 (hb fresh + PID alive but state=SHUTDOWN race window) 차단 path
                broker_state = str(hb.get("state", "")).upper()
                if broker_state and broker_state != "CONNECTED":
                    return False
            except Exception:
                pass  # PID/state 검사 실패 시 mtime fresh 로만 판정 (안전 default)
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────
    # 저수준 request/response 1회 (sub-process retry 책임)
    # ──────────────────────────────────────────────────────────
    def request(self, payload: Dict[str, Any], timeout_sec: float = 12.0,
                poll_interval_sec: float = 0.2) -> Dict[str, Any]:
        """단발 IPC 호출. 응답 dict 반환 (status/data/error)."""
        request_id = str(uuid.uuid4())
        req = dict(payload)
        req["request_id"] = request_id
        req["ts"] = datetime.now().isoformat()
        req.setdefault("ttl_sec", int(timeout_sec) + 5)
        # [TR-CALLER 2026-07-11] 호출자 서명 — 게이트웨이는 모르는 키 무시(하위호환)
        req.setdefault("caller", _CALLER)

        self._req_dir.mkdir(parents=True, exist_ok=True)
        self._res_dir.mkdir(parents=True, exist_ok=True)

        req_path = self._req_dir / f"{request_id}.json"
        res_path = self._res_dir / f"{request_id}.json"

        try:
            tmp = req_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(req, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(str(tmp), str(req_path))
        except Exception as e:
            return {"status": "ERROR", "error": f"request write: {e}", "data": None}

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if res_path.exists():
                try:
                    res = json.loads(res_path.read_text(encoding="utf-8-sig"))
                except Exception as e:
                    try: res_path.unlink()
                    except Exception: pass
                    return {"status": "ERROR", "error": f"response parse: {e}", "data": None}
                try: res_path.unlink()
                except Exception: pass
                return res
            time.sleep(poll_interval_sec)
        return {"status": "TIMEOUT", "error": f"client poll {timeout_sec}s", "data": None}

    # ──────────────────────────────────────────────────────────
    # 고수준 API (broker_gateway_v1 IPC type 별 wrapper)
    # ──────────────────────────────────────────────────────────
    def ping(self, timeout_sec: float = 3.0) -> Dict[str, Any]:
        return self.request({"type": "PING"}, timeout_sec=timeout_sec)

    def state(self, timeout_sec: float = 2.0) -> Dict[str, Any]:
        return self.request({"type": "STATE"}, timeout_sec=timeout_sec)

    def account_info(self, tag: str = "ACCNO", timeout_sec: float = 2.0) -> Dict[str, Any]:
        return self.request({"type": "ACCOUNT_INFO", "tag": tag}, timeout_sec=timeout_sec)

    def tr(self, tr_code: str, inputs: Dict[str, Any], output_fields: List[str],
           rqname: Optional[str] = None, screen_no: str = "0001",
           next_flag: int = 0, timeout_sec: float = 12.0) -> Dict[str, Any]:
        """일반 TR 위임. next_flag 0=첫, 2=연속."""
        # [TR-CALLER 2026-07-11] 기본 rqname에 호출자 포함 — 저널 호출자 특정용
        return self.request({
            "type": "TR",
            "tr_code": tr_code,
            "rqname": rqname or f"{tr_code}_{_CALLER}",
            "screen_no": screen_no,
            "next_flag": int(next_flag),
            "input": inputs,
            "output_fields": list(output_fields or []),
        }, timeout_sec=timeout_sec)

    def batch_tr(self,
                 tr_code: str,
                 codes: List[str],
                 input_template: Dict[str, Any],
                 output_fields: List[str],
                 rqname_template: Optional[str] = None,
                 screen_no_rotate: Optional[List[str]] = None,
                 next_flag: int = 0,
                 per_request_timeout_sec: float = 5.0,
                 batch_timeout_sec: float = 60.0,
                 client_timeout_sec: Optional[float] = None) -> Dict[str, Any]:
        """[Phase 1.1 2026-05-14] BATCH_TR — 다종목 일괄 TR.

        IPC overhead 1회만 (vs single TR N회). collector opt10080 60종목 사이클 단축 목적.

        Args:
            tr_code: TR 코드 (예: "opt10080").
            codes: 종목 코드 리스트.
            input_template: SetInputValue dict. value 에 "{CODE}" 포함 시 각 종목 코드로 치환.
                            예: {"종목코드": "{CODE}", "틱범위": "1"}
            output_fields: 응답 추출 컬럼 한글명.
            rqname_template: optional (default f"{tr_code}_req").
            screen_no_rotate: optional 화면번호 rotate 리스트 (default ["0001"]).
            next_flag: 0=첫, 2=연속 (모든 종목 일관).
            per_request_timeout_sec: 종목당 timeout.
            batch_timeout_sec: batch 전체 timeout.
            client_timeout_sec: client poll deadline (default = batch_timeout_sec + 5).

        Returns:
            {"status": "OK", "data": {"results": [...], "summary": {...}}}
            results = [{"code": "...", "status": "OK"|"TIMEOUT"|"ERROR",
                        "data": {...}, "error": null|"..."}]
            summary = {"total": N, "ok": M, "timeout": K, "error": L,
                       "elapsed_sec": float, "aborted": bool}
        """
        if not codes:
            return {"status": "ERROR", "error": "batch_tr: codes empty", "data": None}
        if client_timeout_sec is None:
            client_timeout_sec = batch_timeout_sec + 5.0

        payload = {
            "type":              "BATCH_TR",
            "tr_code":           tr_code,
            "codes":             list(codes),
            # [TR-CALLER 2026-07-11] 기본 rqname에 호출자 포함 — 저널 호출자 특정용
            "rqname_template":   rqname_template or f"{tr_code}_{_CALLER}",
            "screen_no_rotate":  list(screen_no_rotate or ["0001"]),
            "input_template":    dict(input_template),
            "output_fields":     list(output_fields or []),
            "next_flag":         int(next_flag),
            "per_request_timeout_sec": float(per_request_timeout_sec),
            "batch_timeout_sec":       float(batch_timeout_sec),
        }
        return self.request(payload, timeout_sec=client_timeout_sec)

    def balance_tr(self, tr_code: str, inputs: Dict[str, Any], output_fields: List[str],
                   rqname: Optional[str] = None, screen_no: str = "0001",
                   timeout_sec: float = 12.0) -> Dict[str, Any]:
        """잔고/미체결 TR (whitelist 적용)."""
        # [TR-CALLER 2026-07-11] 기본 rqname에 호출자 포함 — 저널 호출자 특정용
        return self.request({
            "type": "BALANCE_TR",
            "tr_code": tr_code,
            "rqname": rqname or f"{tr_code}_{_CALLER}",
            "screen_no": screen_no,
            "input": inputs,
            "output_fields": list(output_fields or []),
        }, timeout_sec=timeout_sec)

    def master_info(self, func: str, arg: str, timeout_sec: float = 5.0) -> Dict[str, Any]:
        """MASTER_INFO whitelist 4종: GetCodeListByMarket / GetMasterCodeName / GetMasterStockInfo / GetMasterETF"""
        return self.request({"type": "MASTER_INFO", "func": func, "arg": arg},
                            timeout_sec=timeout_sec)

    def koa_functions(self, func: str, arg: str = "",
                      timeout_sec: float = 5.0) -> Dict[str, Any]:
        """KOA_Functions whitelist (F1). ShowAccountWindow / GetServerGubun 등."""
        return self.request({"type": "KOA_FUNCTIONS", "func": func, "arg": arg},
                            timeout_sec=timeout_sec)

    # 실시간 시세 위임
    def setreal_reg(self, screen_no: str, code_list: str, fid_list: str,
                    real_type: str = "0", timeout_sec: float = 3.0) -> Dict[str, Any]:
        """SetRealReg 위임. real_type='0' 신규 / '1' 추가."""
        return self.request({
            "type": "SETREAL_REG",
            "screen_no": screen_no,
            "code_list": code_list,
            "fid_list":  fid_list,
            "real_type": real_type,
        }, timeout_sec=timeout_sec)

    def set_real_remove(self, screen_no: str, code: str,
                        timeout_sec: float = 3.0) -> Dict[str, Any]:
        """SetRealRemove 위임."""
        return self.request({
            "type": "SET_REAL_REMOVE",
            "screen_no": screen_no,
            "code":      code,
        }, timeout_sec=timeout_sec)

    def set_real_remove_all(self, timeout_sec: float = 3.0) -> Dict[str, Any]:
        """SetRealRemove("ALL","ALL") 명시 단축."""
        return self.request({"type": "SET_REAL_REMOVE_ALL"}, timeout_sec=timeout_sec)

    def get_real_reg_grp(self, timeout_sec: float = 3.0) -> Dict[str, Any]:
        """GetRealRegGroup 위임 (등록된 화면번호 목록)."""
        return self.request({"type": "GET_REAL_REG_GRP"}, timeout_sec=timeout_sec)

    def get_comm_real_data(self, code: str, fid: int,
                           timeout_sec: float = 2.0) -> Dict[str, Any]:
        """GetCommRealData(code, fid) 위임 (단건 풀)."""
        return self.request({
            "type": "GET_COMM_REAL_DATA",
            "code": code,
            "fid":  int(fid),
        }, timeout_sec=timeout_sec)

    # 화면번호 해제
    def disconnect_scr(self, screen_no: str,
                       timeout_sec: float = 2.0) -> Dict[str, Any]:
        return self.request({"type": "DISCONNECT_SCR", "screen_no": screen_no},
                            timeout_sec=timeout_sec)

    # ──────────────────────────────────────────────────────────
    # [Z1 2026-05-14] 실 SendOrder 집행 + idempotency dedup
    # ──────────────────────────────────────────────────────────
    # broker 측 SENDORDER_REAL 핸들러와 1:1 호환.
    # idempotency_key = 같은 key 재요청 시 broker 가 cache 응답 반환 (실 SendOrder 미호출).
    # client timeout 후 재시도 안전 보장 = 중복 주문 차단.
    #
    # 사용 예:
    #   import uuid
    #   key = str(uuid.uuid4())  # 한 주문당 고유 key, 같은 주문 재시도 시 동일 key 사용
    #   res = bc.send_order_real(
    #       idempotency_key=key,
    #       account="6502...",
    #       code="035720",
    #       qty=10,
    #       order_type=1,      # 1=매수
    #       price=50000,
    #       hoga_gb="00",      # 00=지정가
    #       rqname="buy_001",
    #       screen_no="9001",
    #   )
    #   if res.get("status") == "OK" and (res.get("data") or {}).get("ret") == 0:
    #       # 주문 정상 접수 — Chejan broadcast 구독으로 ACK/FILL 수신
    #       pass

    # broker SENDORDER_TYPE_WHITELIST 와 동일 (1=매수 2=매도 3=매수취소 4=매도취소 5=매수정정 6=매도정정)
    ORDER_TYPE_BUY          = 1
    ORDER_TYPE_SELL         = 2
    ORDER_TYPE_BUY_CANCEL   = 3
    ORDER_TYPE_SELL_CANCEL  = 4
    ORDER_TYPE_BUY_MODIFY   = 5
    ORDER_TYPE_SELL_MODIFY  = 6

    def send_order_real(self,
                        idempotency_key: str,
                        account: str,
                        code: str,
                        qty: int,
                        order_type: int,
                        price: int = 0,
                        hoga_gb: str = "00",
                        rqname: Optional[str] = None,
                        screen_no: str = "9999",
                        origin_order_no: str = "",
                        timeout_sec: float = 10.0) -> Dict[str, Any]:
        """실 SendOrder broker IPC 위임.

        Args:
            idempotency_key: **필수**. uuid4 등 고유값. 같은 key 재요청 시 broker dedup.
            account: 계좌번호.
            code: 종목코드.
            qty: 주문 수량 (>0).
            order_type: 1(매수)/2(매도)/3(매수취소)/4(매도취소)/5(매수정정)/6(매도정정).
            price: 주문가 (시장가=0).
            hoga_gb: 호가구분 ("00"=지정가, "03"=시장가, "05"=조건부지정가, ...).
            rqname: 요청명 (logger 식별).
            screen_no: 화면번호.
            origin_order_no: 정정/취소 시 원주문번호.
            timeout_sec: client poll deadline.

        Returns:
            {"status": "OK"|"ERROR"|"TIMEOUT",
             "data":   {"ret": <SendOrder return>, "code", "qty", "order_type", ...},
             "error":  None|str}

            [#4 contract 정정 2026-05-15] gateway 실 동작 기준:
              status=OK    + data.ret=0  → SendOrder 호출 성공 (실 체결은 Chejan broadcast 별도)
              status=ERROR + data.ret≠0  → 키움 SendOrder 거부 (잔고부족/시간외/한도초과 등). error=f"SendOrder ret={N}"
              status=TIMEOUT             → client poll deadline 초과 (broker 미응답)
              status=ERROR (data=None)   → broker validation 실패 (idempotency_key/account/code/qty/order_type/hoga_gb)

            호출부 권고 처리:
              if res.get("status") != "OK":
                  # 거부 또는 timeout — error 필드에 키움 ret 또는 broker 사유
                  return REJECTED
              # status=OK는 ret=0 보장 (gateway L1489 ok=(ret==0)이 status 결정)
        """
        # [매수 차단기 2026-06-29] manual_buy_block.flag 존재 시 매수(order_type=1) 거부.
        #   ★기존 구멍 메움: 라이브 실행기(deep_v/돌파/눌림/MBB/종가)가 이 메서드를 직접 호출 →
        #   kiwoom_buy_order_sender의 flag체크를 안 거쳐 차단기가 무력했음. 여기서 공통 차단(매도/정정/취소 무관·fail-open).
        if order_type == 1:
            try:
                import os as _os
                if _os.path.exists(r"C:\stock_bot\config\manual_buy_block.flag"):
                    return {"status": "ERROR",
                            "error": "manual_buy_block(flag) — 수동 매수차단 활성",
                            "data": None}
            except Exception:
                pass
        # [돈흐름 단독실험 격리 2026-07-06 친구님 "전략 프로그램들 계좌 사용 차단·돈흐름만 실험"]
        #   only_moneyflow.flag 존재 시 → 매수(order_type=1)는 rqname이 "MFLOW"로 시작하는 돈흐름 매매기만 허용.
        #   나머지 전 전략 매수 전부 거부(★단일 관문이라 전략 하나도 못 빠져나감). 매도/정정/취소는 통과=기존 포지션 청산 가능.
        #   해제: config\only_moneyflow.flag 삭제. fail-open(flag 못읽으면 통과). manual_buy_block(전면 킬스위치)가 우선.
        if order_type == 1:
            try:
                import os as _osmf
                if _osmf.path.exists(r"C:\stock_bot\config\only_moneyflow.flag"):
                    # 허용 접두어(env ONLY_MF_ALLOW로 조정·기본 돈흐름만). ★갭대장 포함 나머지 전 전략 매수 차단.
                    _allow = tuple(p.strip().upper() for p in
                                   _osmf.environ.get("ONLY_MF_ALLOW", "MFLOW").split(",") if p.strip())
                    if not str(rqname or "").upper().startswith(_allow):
                        return {"status": "ERROR",
                                "error": f"only_moneyflow(flag) — 격리·전략매수 차단(rqname={rqname}·허용={_allow})",
                                "data": None}
            except Exception:
                pass
        # [시장 regime 금액축소 2026-07-03 친구님 "차단말고 금액축소·눌림만말고 공통"] 급락장/장전US위험이면
        #   주문수량 축소(전 엔진 공통 단일지점·fail-open). 차단 아님 = 나쁜날도 소액으로 계속 매수.
        #   근거 백테16일: 매수시점 코스닥 ≤0%면 스파이크대장 -0.77%→-5% → 나쁜날은 작게.
        #   env MARKET_REGIME_GATE=YES 활성 / 코스닥 MARKET_DROP_REDUCE(-1.0)이하 or US DANGER면 REGIME_CUT(0.5)배·최소1주.
        #   극단(EXTREME_DROP -3.0 이하)은 REGIME_CUT_EXTREME(0.34)배로 더 축소. 롤백 setx MARKET_REGIME_GATE NO.
        # ★[7/12 친구님 지시 "-1%는 정상진행 / -2%는 금액 절반 / -3%는 스탑 · 레짐 켜"]
        #   ①문턱 -1.0 → -2.0(REDUCE) ②극단은 '축소'가 아니라 '차단'(MARKET_DROP_STOP -3.0·주문 거부).
        #   근거(키움 3분봉 24일·슬롯4 리플레이·세금0.15% 반영): 시장 약한 날에 컷이 잦아 슬롯이 계속 비고
        #   → 그날 더 많이 삼(4.5건 → 7.6건 = 나쁜 날에 베팅 증가·역선택). 09:15 시장 약세일 쉬면 하루 -25,151원 → 흑자 전환.
        #   지수 배관 검증(7/12): 지수 +5.47%(7/10) vs 우리 일봉 1,663종목 중앙 +4.07% = 일치·신뢰 가능.
        #   ⚠️전 엔진 공통 관문(깊은바닥·눌림·통합대장·종가매수 전부 적용). 지수 파일 없음/낡음 = fail-open(무개입).
        #   롤백: setx MARKET_REGIME_GATE NO  ·  문턱: MARKET_DROP_REDUCE / MARKET_DROP_STOP
        if order_type == 1:
            try:
                import os as _osr, json as _jr
                from datetime import datetime as _dtr
                if _osr.environ.get("MARKET_REGIME_GATE", "NO").strip().upper() == "YES":
                    _tdy = _dtr.now().strftime("%Y-%m-%d")
                    _drop = float(_osr.environ.get("MARKET_DROP_REDUCE", "-2.0"))    # 이 이하 = 금액 절반
                    _stop = float(_osr.environ.get("MARKET_DROP_STOP", "-3.0"))      # 이 이하 = 매수 스탑(차단)
                    _cut = float(_osr.environ.get("REGIME_CUT", "0.5"))
                    _kchg = None
                    try:
                        _k = _jr.loads(open(r"C:\stock_bot\data\kosdaq_index.json", encoding="utf-8").read())
                        if str(_k.get("ts", ""))[:10] == _tdy:
                            _kchg = float(_k.get("chg"))
                    except Exception:
                        _kchg = None
                    # ★-3% 이하 = 매수 스탑(주문 거부). 매도는 이 블록(order_type==1=매수)에 안 걸림 = 항상 통과.
                    # ★[2026-07-29 친구님 지시 "레짐스탑 전략별로 분리해"]
                    #   레짐스탑 면제 목록(env REGIME_STOP_EXEMPT · 쉼표구분 rqname 접두어).
                    #   근거(일봉 1년·상한가 종가매수 1,134건·익일 시가매도·비용 0.38% 차감):
                    #     폭락일(시장 -3%↓) +6.262%·승률 73.1%(67건) — 전체 +5.976%보다 오히려 높다.
                    #     기존 "폭락장 전멸" 판단은 표본 8건짜리였다. 상한가 경로엔 레짐스탑이 손해.
                    #   ⚠️장중 전략(S01~S05)은 면제 대상이 아니다. 이 목록에 넣지 말 것.
                    #   기본값 빈 문자열 = 종전 동작 그대로(전 전략 차단). 켤 때만 값을 넣는다.
                    #   예: REGIME_STOP_EXEMPT=EODGAP_   ·  롤백: 환경변수 삭제 또는 빈값
                    _exempt = tuple(p.strip().upper() for p in
                                    _osr.environ.get("REGIME_STOP_EXEMPT", "").split(",") if p.strip())
                    if _kchg is not None and _stop < 0 and _kchg <= _stop:
                        if not (_exempt and str(rqname or "").upper().startswith(_exempt)):
                            return {"status": "ERROR",
                                    "error": f"레짐스탑 — 코스닥 {_kchg:+.2f}% (문턱 {_stop:g}%·폭락일 매수중단)",
                                    "data": None}
                    _bad = (_kchg is not None and _kchg <= _drop)                    # -2% 이하 = 절반
                    if not _bad and _osr.environ.get("US_DANGER_BLOCK", "YES").strip().upper() == "YES":
                        try:
                            _u = _jr.loads(open(r"C:\stock_bot\data\us_overnight.json", encoding="utf-8").read())
                            if (str(_u.get("ts", ""))[:10] == _tdy
                                    and str(_u.get("risk", "")).upper() == "DANGER"
                                    and (_kchg is None or _kchg <= 0)):
                                _bad = True
                        except Exception:
                            pass
                    if _bad and 0 < _cut < 1:
                        qty = max(1, int(round(int(qty) * _cut)))
            except Exception:
                pass
        # [잡주 차단 2026-06-30 친구님 "1000원 이하 잡주 매수금지"] ★전 엔진 통일 단일점(돌파·실시간돌파·골든·딥·갭 전부 여기 거침).
        #   실시간 스냅샷 현재가가 SAFEPLUS_MIN_PRICE(기본1000) 미만이면 매수 거부. 가격 모르면 통과(fail-open).
        if order_type == 1:
            try:
                import os as _os3, json as _json3
                # [2026-07-07 친구님] 돈흐름(rqname MFLOW…)은 큰손추종이라 저가주도 담게 별도 하한(MF_MIN_PRICE).
                #   나머지 전 전략은 SAFEPLUS_MIN_PRICE(5만) 유지 — 7/4 결정 보존. MF_MIN_PRICE 미설정시 SAFEPLUS_MIN_PRICE로 폴백.
                # ★[2026-07-30 친구님 "저점매수는 구애받지 말고 200만 한도 내 매수"] 저점매수(EODGAP_LOWBUY)는
                #   가격하한 면제 — 유니버스(고저폭 TOP30)가 전일종가 1만원↑로 이미 걸러져 있는데
                #   급락 당일가로 재검사하면 -13% 빠진 가장 깊은 후보(전략의 핵심)가 차단된다.
                #   MFLOW 별도하한과 같은 기존 패턴. 롤백: backup\broker_client_20260730_lowbuyfree.py
                if str(rqname or "").upper().startswith("EODGAP_LOWBUY"):
                    _minp = 0.0
                elif str(rqname or "").upper().startswith("MFLOW"):
                    _minp = float(_os3.environ.get("MF_MIN_PRICE") or _os3.environ.get("SAFEPLUS_MIN_PRICE", "1000"))
                else:
                    _minp = float(_os3.environ.get("SAFEPLUS_MIN_PRICE", "1000"))
                _snp = _json3.loads(open(r"C:\stock_bot\IPC\live_micro_snapshot.json", encoding="utf-8-sig").read())
                _cp = float((_snp.get("codes", {}).get(str(code).zfill(6)) or {}).get("cur", 0) or 0)
                if 0 < _cp < _minp:
                    return {"status": "ERROR",
                            "error": f"price_floor: {_cp:.0f}<{_minp:.0f} — 저가 잡주 매수금지(MIN_PRICE)",
                            "data": None}
                # [시총 잡주차단 2026-06-30] 시가총액 = 발행주식수 × 현재가. SAFEPLUS_MIN_MARKETCAP(원) 미만이면 거부.
                #   주식수 모르거나 현재가 모르면 통과(fail-open) — 가격게이트가 1차 방어.
                # ★[7/14 친구님 "시총 500억 이상으로 하는 걸로 해봐"] 돈흐름(MFLOW)만 시총 하한 별도 —
                #   바로 위 가격하한(MF_MIN_PRICE)과 똑같은 구조. 가격은 예외를 뒀는데 시총은 빠뜨렸었다.
                #   🚨7/13 밤 잡주 개방(선별판 시총 500억 완화)이 여기서 통째로 막혀 있었음:
                #     선별판 통과 → 매매기 통과 → 주문 직전 mcap_floor 거부.
                #     전일풀 실측 = 시총 500~1,000억 잡주 65종목이 전멸 → 잡주 개방의 핵심
                #     (500억 완화 = 잡주 건당 -0.031% → +0.939%)이 무력화된 상태였다.
                #   나머지 전 전략(종가매수 EODGAP 포함)은 SAFEPLUS_MIN_MARKETCAP(1,000억) 그대로.
                #   롤백: setx MF_MIN_MARKETCAP 100000000000   (=1,000억 = 기존과 동일)
                if str(rqname or "").upper().startswith("EODGAP_LOWBUY"):
                    _minmc = 0.0   # ★저점매수 시총하한 면제(위 가격하한 주석과 같은 근거)
                elif str(rqname or "").upper().startswith("MFLOW"):
                    _minmc = float(_os3.environ.get("MF_MIN_MARKETCAP")
                                   or _os3.environ.get("SAFEPLUS_MIN_MARKETCAP", "0"))
                else:
                    _minmc = float(_os3.environ.get("SAFEPLUS_MIN_MARKETCAP", "0"))
                if _minmc > 0 and _cp > 0:
                    _sh = _load_shares_cache().get(str(code).zfill(6), 0.0)
                    if _sh > 0:
                        _mc = _sh * _cp
                        if _mc < _minmc:
                            return {"status": "ERROR",
                                    "error": f"mcap_floor: {_mc/1e8:.0f}억<{_minmc/1e8:.0f}억 — 소형 잡주 매수금지(MIN_MARKETCAP)",
                                    "data": None}
            except Exception:
                pass
        if not idempotency_key:
            return {"status": "ERROR",
                    "error": "send_order_real: idempotency_key required (중복 주문 차단)",
                    "data": None}
        if not account or not code or qty <= 0:
            return {"status": "ERROR",
                    "error": f"send_order_real: account/code/qty required (got account={account!r} code={code!r} qty={qty})",
                    "data": None}
        if order_type not in {1, 2, 3, 4, 5, 6}:
            return {"status": "ERROR",
                    "error": f"send_order_real: order_type {order_type} 범위 외 (1~6)",
                    "data": None}

        payload = {
            "type":            "SENDORDER_REAL",
            "idempotency_key": str(idempotency_key),
            "rqname":          rqname or f"SendOrder_{order_type}_{code}",
            "screen_no":       str(screen_no),
            "account":         str(account),
            "order_type":      int(order_type),
            "code":            str(code),
            "qty":             int(qty),
            "price":           int(price),
            "hoga_gb":         str(hoga_gb),
            "origin_order_no": str(origin_order_no),
            # [GHOST-WIN 2026-07-30] 실주문만 유예를 줄인다 — request()의 setdefault(timeout+5)보다
            #   이 명시값이 우선. 게이트웨이 쪽 상한(BROKER_ORDER_MAX_TTL_SEC=8)과 이중 방어.
            "ttl_sec":         max(1, int(timeout_sec) - _GHOST_MARGIN_SEC),
        }
        return self.request(payload, timeout_sec=timeout_sec)


    # ──────────────────────────────────────────────────────────
    # [J1 2026-05-14] Broadcast 구독 helper (stateless)
    # ──────────────────────────────────────────────────────────
    # broker 가 단방향 broadcast (chejan_events / real_data / msg_events / order_shadow_ack) 작성.
    # sub-process 가 본 helper 호출 → 신규 event_id 만 반환. seen_cache 는 caller 가 관리.
    # 패턴 (caller):
    #   seen = {}
    #   while True:
    #       events = bc.consume_chejan_events(seen)
    #       for ev in events:
    #           process_chejan(ev)
    #       time.sleep(0.3)
    #
    # broker 측 청소 정책 (N1): 300s TTL 후 자동 삭제. caller 는 seen_cache 만 TTL 관리.

    @staticmethod
    def _read_event_files(dirpath: Path, seen_cache: dict,
                          cache_ttl_sec: float = 300.0) -> list:
        """공통 폴링 helper. 신규 event 파일만 dict 리스트로 반환.

        seen_cache: {event_id: expiry_ts} — caller 가 owner.
        만료 항목 자동 청소.
        """
        now = time.time()
        # seen_cache 만료 청소
        expired = [k for k, exp in seen_cache.items() if exp < now]
        for k in expired:
            seen_cache.pop(k, None)

        events: list = []
        try:
            if not dirpath.exists():
                return events
            for fp in sorted(dirpath.glob("*.json")):
                event_id = fp.stem
                if event_id in seen_cache:
                    continue
                try:
                    data = json.loads(fp.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                events.append(data)
                seen_cache[event_id] = now + cache_ttl_sec
        except Exception:
            pass
        return events

    def consume_chejan_events(self, seen_cache: dict,
                              cache_ttl_sec: float = 300.0) -> list:
        """Chejan 신규 이벤트 반환. event = {event_id, ts, gubun, fid_data}"""
        return self._read_event_files(self._chejan_dir, seen_cache, cache_ttl_sec)

    def consume_real_data(self, seen_cache: dict,
                          code_filter: Optional[set] = None,
                          cache_ttl_sec: float = 60.0) -> list:
        """RealData 신규 이벤트 반환. event = {event_id, ts, code, real_type, fid_data}.

        code_filter: set/list 지정 시 해당 종목만 반환. None = 전체.
        cache_ttl_sec: RealData 는 빈도 높음 → 짧은 TTL (60s).
        """
        events = self._read_event_files(self._real_data_dir, seen_cache, cache_ttl_sec)
        if code_filter is None:
            return events
        filter_set = set(str(c) for c in code_filter)
        return [e for e in events if str(e.get("code", "")) in filter_set]

    def consume_msg_events(self, seen_cache: dict,
                           cache_ttl_sec: float = 300.0) -> list:
        """OnReceiveMsg 신규 이벤트 반환. event = {event_id, ts, screen_no, rqname, tr_code, msg}"""
        return self._read_event_files(self._msg_events_dir, seen_cache, cache_ttl_sec)

    def consume_order_shadow_ack(self, seen_cache: dict,
                                 cache_ttl_sec: float = 300.0) -> list:
        """SendOrder SHADOW ACK relay 신규 이벤트. Chejan event 의 order_no/state/code 별도 채널.

        event = {event_id, ts_broker_relay, order_no, state, code, filled_qty, filled_price, remain_qty, ...}
        """
        return self._read_event_files(self._order_ack_dir, seen_cache, cache_ttl_sec)

    # ──────────────────────────────────────────────────────────
    # [J3 2026-05-14] broker 가동 대기 helper
    # ──────────────────────────────────────────────────────────
    def wait_alive(self, timeout_sec: float = 30.0,
                   poll_interval_sec: float = 0.5) -> bool:
        """broker alive 까지 대기 (최대 timeout_sec). True = alive 도달, False = timeout.

        용도: sub-process 시작 시 broker 부팅 race 보호.
        """
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.alive():
                return True
            time.sleep(poll_interval_sec)
        return False


# 모듈 단위 helper (인스턴스 없이 사용)
def is_broker_alive(ipc_base: Path = _DEFAULT_IPC_BASE,
                    hb_stale_sec: float = _DEFAULT_HB_STALE_SEC) -> bool:
    """quick check — sub-process 진입점에서 broker 가동 검사용."""
    return BrokerClient(ipc_base=ipc_base, hb_stale_sec=hb_stale_sec).alive()

# -*- coding: utf-8 -*-
"""Shared safe broker adapter for independent strategies.

This module contains no entry or exit formula. It only provides broker
connection, account reconciliation, exact-order cancellation, fill aggregation,
and live-approval gates.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from approval_settings_guard import KST, legacy_daily_approval_valid
from strategy_broker_live_guard import StrategyBrokerLiveGuard


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def fills_by_order(
    fills_dir: Path,
    code: str,
    side: str,
    since_hms: str = "00:00:00",
    day: str = "",
) -> Dict[str, Tuple[int, float]]:
    """Aggregate incremental Chejan fills by exact broker order number."""
    from datetime import datetime

    day = day or datetime.now().strftime("%Y%m%d")
    path = Path(fills_dir) / f"fills_{day}.csv"
    if not path.exists():
        return {}
    code = str(code).zfill(6)
    previous: Dict[str, int] = {}
    totals: Dict[str, Tuple[int, float]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    if str(row.get("code") or "").strip().lstrip("A").zfill(6) != code:
                        continue
                    if side not in str(row.get("otype") or ""):
                        continue
                    if "체결" not in str(row.get("state") or ""):
                        continue
                    stamp = str(row.get("ts") or "")
                    if len(stamp) >= 19 and stamp[11:19] < since_hms:
                        continue
                    order_no = str(row.get("order_no") or "").strip()
                    if not order_no:
                        continue
                    cumulative = int(_number(row.get("fill_qty")))
                    price = _number(row.get("fill_px"))
                    increment = cumulative - previous.get(order_no, 0)
                    if increment <= 0:
                        continue
                    previous[order_no] = cumulative
                    qty, weighted = totals.get(order_no, (0, 0.0))
                    totals[order_no] = (qty + increment, weighted + increment * price)
                except Exception:
                    continue
    except OSError:
        return {}
    return {
        order_no: (qty, weighted / qty if qty > 0 else 0.0)
        for order_no, (qty, weighted) in totals.items()
    }


class StrategyBroker:
    """BrokerClient wrapper with approval-gated buys and exit-only recovery."""

    # ★[SCREEN-SPLIT 2026-08-05] 전략별 전용 화면번호. 같은 화면으로 동시에 TR 을
    #   걸면 키움 응답이 엉켜 가짜 TIMEOUT 이 난다(상세는 __init__ 주석).
    #   S06 은 종전부터 9786 을 명시로 넘겨 쓰고 있었고 여기 값도 같다(친구님
    #   "6번도 통합해도 돼") — 명시값이 이기므로 동작은 그대로다.
    #   9783 은 S03 사전점검이 쓰고 있어 S03 엔진은 9784 로 비켜 놓았다.
    _SCREEN_BY_PREFIX = {
        "STRATEGY01": "9781",
        "STRATEGY02": "9782",
        "STRATEGY03": "9784",
        "STRATEGY04": "9787",
        "STRATEGY05": "9785",
        "STRATEGY06": "9786",
    }

    def __init__(
        self,
        *,
        live_requested: bool,
        approval_path: Path,
        off_flag_path: Path,
        manual_buy_block_path: Path,
        logger: logging.Logger,
        order_prefix: str = "STRATEGY01",
        screen_no: str = "",
        force_exit_only: bool | Callable[[], bool] = False,
    ) -> None:
        self.live_requested = bool(live_requested)
        self.approval_path = Path(approval_path)
        self.off_flag_path = Path(off_flag_path)
        self.manual_buy_block_path = Path(manual_buy_block_path)
        self.log = logger
        self.order_prefix = str(order_prefix).upper()
        # ★[SCREEN-SPLIT 2026-08-05 친구님 지시] 전략마다 화면번호를 나눈다.
        #   종전엔 기본값 "9781" 하나를 S01·S02·S03·S05 가 전부 공유했다(S06 만
        #   9786 을 따로 썼다). 키움은 같은 화면번호로 동시에 TR 을 걸면 응답이
        #   엉킨다 — 브로커가 rqname 버퍼를 못 찾아 "TR response timeout (20s)"
        #   를 1초 만에 쓰고, 엔진은 PREBUY_BALANCE_UNAVAILABLE 로 매수를 취소한다.
        #   8/5 10:43 실측(4엔진 동시 가동 중):
        #       9781 성공 0/3   9782 성공 3/3   9784 성공 3/3   9788 성공 3/3
        #   오늘 10:10 대한광통신(S02) 을 놓친 원인이고, 8/4 "S02 매수 전면 마비
        #   50건 무더기 TIMEOUT" 도 같은 것이다.
        #   명시적으로 넘기면 그 값이 이긴다(S06=9786, S03 사전점검=9783 유지).
        #   되돌리기: backup\strategy_common_order_v1_20260805_before_balance_retry.py
        self.screen_no = str(
            screen_no or self._SCREEN_BY_PREFIX.get(self.order_prefix, "9781"))
        self._force_exit_only = force_exit_only
        self.client = None
        self.account = ""
        self.last_error = ""
        self.live_guard = StrategyBrokerLiveGuard(
            order_prefix=self.order_prefix
        )

    @property
    def force_exit_only(self) -> bool:
        r"""실포지션 보유 여부를 매 판정마다 다시 묻는다.

        ★[SELL-LOCK 2026-08-04] 오늘 real_session 을 '깃발 존재'에서 '내용·날짜
        유효'로 조인 뒤 생긴 구멍을 막는다. 승인 깃발이 장중에 깨지면
        (BOM·재작성 중 빈 파일·시계 역행) real_session 이 False 로 떨어지고,
        holdings() 가 None 이 아니라 {} 를 돌려준다. _start_sell 은 그걸
        'BROKER_ALREADY_FLAT' 으로 읽어 실제로 팔지 않은 채 포지션을 장부에서
        지운다 = 7/14 유령 잔량 재현.

        기존 값은 엔진 __init__ 에서 딱 1회 계산돼 장중에 새로 산 포지션을
        보호하지 못했다. 호출가능 객체를 받아 매번 다시 계산한다.
        판단 자체가 실패하면 '보유 중'으로 본다 — 못 파는 쪽이 더 위험하다.
        되돌리기: backup/strategy_common_order_v1_20260804_before_sell_lock_fix.py

        ★[SLOT-RESTORE 2026-08-05 친구님 지시 "수정해"] 보유 중이라는 이유만으로
        청산 전용이 되지 않게 한다.
          문제: 8/4 이후 엔진이 '실포지션 보유 여부'를 이 자리에 넣으면서, 1건만
          사도 force_exit_only=True -> buy_signal 이 False -> **슬롯 6개가 실질
          1개로 죽었다**(8/5 11:04 실측: 원익IPS 1건 보유 중 S02 buy_allowed=False).
          S01·S02·S03·S06 이 같은 패턴이라 전부 해당됐다.
          8/4 의 원래 목적은 '승인 깃발이 장중에 깨져도 팔 수 있게' 하는 것 하나였다
          (real_session = live_requested and (valid or force_exit_only)).
          승인이 멀쩡하면 real_session 은 valid 로 이미 True 이므로, 그때까지
          청산 전용으로 묶을 이유가 없다.
        판정:
          · 명시적 bool 로 받은 값(예: 사전점검의 force_exit_only=True)은 그대로 존중.
          · 호출가능 객체(엔진의 '보유 탐침')는 **보유 AND 승인 깨짐** 일 때만 True.
        되돌리기: backup\strategy_common_order_v1_20260805_before_slot_restore.py
        """
        value = self._force_exit_only
        if not callable(value):
            return bool(value)
        try:
            holding = bool(value())
        except Exception as exc:
            self.log.warning(
                "[SELL-LOCK] 보유 판정 실패 - 실매도 허용으로 처리: %s", exc)
            return True
        if not holding:
            return False
        # 보유 중 — 승인이 깨졌을 때만 청산 전용(= 8/4 유령삭제 방어를 유지).
        return not self.approval_valid_now()

    def approval_valid_now(self) -> bool:
        """승인 깃발만 직접 본다. _guard_decision 을 거치지 않는다.

        가드는 force_exit_only 를 입력으로 받으므로, 여기서 가드를 부르면
        force_exit_only -> _guard_decision -> force_exit_only 로 무한재귀가 된다.
        """
        try:
            text = Path(self.approval_path).read_text(
                encoding="ascii", errors="strict")
        except (OSError, UnicodeError):
            return False
        try:
            return bool(legacy_daily_approval_valid(text, datetime.now(KST)))
        except Exception:                      # noqa: BLE001
            return False

    def _guard_decision(self, now: Optional[datetime] = None):
        return self.live_guard.evaluate(
            approval_path=self.approval_path,
            off_flag_path=self.off_flag_path,
            manual_buy_block_path=self.manual_buy_block_path,
            live_requested=self.live_requested,
            force_exit_only=self.force_exit_only,
            now=now,
        )

    def _approval_valid(self, now: Optional[datetime] = None) -> bool:
        """Only a well-formed, effective approval for today is valid.

        Recognizes the formats written by the owner/S04, automatic S01-S03,
        and S06 approval paths. Future timestamps, stale dates, malformed
        contents, and read errors all fail closed.
        """
        return self._guard_decision(now).approval_valid

    @property
    def real_session(self) -> bool:
        return self._guard_decision().real_session

    @property
    def buy_allowed(self) -> bool:
        return self._guard_decision().buy_allowed

    @property
    def mode(self) -> str:
        if not self.real_session:
            return "SHADOW"
        return "LIVE" if self.buy_allowed else "LIVE_EXIT_ONLY"

    def connect(self) -> bool:
        self.last_error = ""
        if not self.real_session:
            return True
        if self.client is not None and self.account:
            return True
        try:
            from broker_client import BrokerClient, is_broker_alive

            if not is_broker_alive():
                self.last_error = "BROKER_NOT_ALIVE"
                return False
            self.client = BrokerClient()
            info = self.client.account_info("ACCNO")
            accounts = (info.get("data") or {}).get("accounts") or []
            if isinstance(accounts, str):
                accounts = [item for item in accounts.split(";") if item]
            self.account = str(accounts[0] if accounts else os.environ.get(
                "SAFEPLUS_ACCOUNT", "")).strip()
            if not self.account:
                self.last_error = "ACCOUNT_MISSING"
                self.client = None
                return False
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.client = None
            self.account = ""
            return False

    # ★[BALANCE-RETRY 2026-08-05 친구님 지시 "지금 넣어"] 가짜 TIMEOUT 재시도.
    #   브로커는 모든 TR 이 self.tr_loop(QEventLoop) 하나를 공유하고 응답 버퍼를
    #   rqname 으로 키잉한다(broker_gateway_v1.py:2714·2735·713-714, 코드 주석
    #   :536 에 이미 경고가 적혀 있다). 그래서 내가 잔고 응답을 기다리는 동안
    #   '다른 TR' 의 응답이 도착하면 그게 내 대기 루프를 깨우고, 내 rqname 버퍼는
    #   비어 있으니 브로커가 TIMEOUT 을 쓴다 — 20초라고 적히지만 실제로는 1초 만에.
    #   8/5 실측: 같은 조회를 반복하면 성공/실패가 번갈아 나온다(1.03s 실패 →
    #   1.02s 성공 → 1.84s 실패 → 0.62s 성공). 즉 한 번 더 물으면 대개 통과한다.
    #   여파: holdings() 가 None -> 엔진이 PREBUY_BALANCE_UNAVAILABLE 로 매수 취소.
    #   오늘 10:10 대한광통신(S02) 을 이것 때문에 놓쳤고, 8/4 "S02 매수 전면 마비
    #   50건 무더기 TIMEOUT" 도 같은 원인이다. TR 통행량이 많을수록 자주 터진다.
    #   ⚠️근본 수리는 브로커의 대기 루프를 요청별로 분리하는 것(브로커 재시작이
    #     필요해 장중엔 위험). 이건 그때까지의 방어다.
    #   되돌리기: backup\strategy_common_order_v1_20260805_before_balance_retry.py
    _BALANCE_RETRY = 3
    _BALANCE_RETRY_SLEEP = 0.4

    def _balance_tr_retry(
        self,
        *,
        attempts: Optional[int] = None,
        retry_sleep: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """status != OK 면 짧게 쉬고 다시 묻는다. 마지막 응답을 그대로 돌려준다."""
        response: Dict[str, Any] = {}
        retry_count = max(1, int(attempts or self._BALANCE_RETRY))
        sleep_sec = (
            self._BALANCE_RETRY_SLEEP
            if retry_sleep is None
            else max(0.0, float(retry_sleep))
        )
        for attempt in range(1, retry_count + 1):
            response = self.client.balance_tr(**kwargs)
            if str(response.get("status") or "").upper() == "OK":
                if attempt > 1:
                    self.log.info(
                        "[BALANCE-RETRY] %s %d회째에 성공 (앞선 실패는 공유 "
                        "tr_loop 의 가짜 TIMEOUT)",
                        kwargs.get("tr_code", "?"), attempt)
                return response
            if attempt < retry_count:
                _time.sleep(sleep_sec)
        self.log.warning(
            "[BALANCE-RETRY] %s %d회 모두 실패: %s",
            kwargs.get("tr_code", "?"), retry_count,
            str(response.get("error"))[:80])
        return response

    def holdings(
        self,
        *,
        timeout_sec: float = 30.0,
        attempts: Optional[int] = None,
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """Return broker truth. None means reconciliation is unavailable."""
        if not self.real_session:
            return {}
        if not self.connect():
            return None
        try:
            response = self._balance_tr_retry(
                attempts=attempts,
                tr_code="opw00018",
                inputs={
                    "계좌번호": self.account,
                    "비밀번호": "",
                    "비밀번호입력매체구분": "00",
                    "조회구분": "2",
                },
                output_fields=[
                    "종목번호", "종목명", "보유수량", "매매가능수량",
                    "매입가", "평균단가",
                ],
                rqname=f"{self.order_prefix}_BALANCE",
                screen_no=self.screen_no,
                # ★[BALANCE-TIMEOUT 2026-08-04 친구님 지시] 12 -> 30초.
                #   왜: 09:37~09:50 S02 신호 4건이 전부 매수 직전에 취소됐다
                #   (PREBUY_BALANCE_UNAVAILABLE). 원인은 잔고 조회 자체가 아니라
                #   돈흐름판 시총 조회(mf_mcap, 09시 이후 388건)와 실시간 구독
                #   재등록이 2분 주기로 TR 큐를 막아 12초 안에 응답이 안 온 것.
                #   큐가 풀리면 응답은 오므로 기다리는 쪽이 맞다.
                #   되돌리기: backup\strategy_common_order_v1_20260804_before_balance_timeout.py
                timeout_sec=float(timeout_sec),
            )
            if str(response.get("status") or "").upper() != "OK":
                self.last_error = str(response.get("error") or "BALANCE_NOT_OK")
                return None
            output: Dict[str, Dict[str, Any]] = {}
            for row in ((response.get("data") or {}).get("records") or []):
                code = str(row.get("종목번호") or "").strip().lstrip("A").zfill(6)
                if len(code) != 6 or not code.isdigit():
                    continue
                qty = int(_number(row.get("보유수량")))
                available = int(_number(row.get("매매가능수량")))
                if qty <= 0 and available <= 0:
                    continue
                output[code] = {
                    "qty": max(0, qty),
                    "available": max(0, available),
                    "buy_price": abs(_number(
                        row.get("평균단가") or row.get("매입가"))),
                    "name": str(row.get("종목명") or "").strip(),
                }
            return output
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def prebuy_holdings(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """Strategy 01 pre-buy check: fail closed within its five-second TTL.

        ★[2026-08-14 친구님 지시 "수정부터 해"] 2.0초x2회 -> 1.3초x3회.
          8/14 실측: 잔고 가짜 TIMEOUT 33건, 09:55~09:59 에만 6건이 몰려
          S02 매수가 그 구간 내내 무산됐다(네오오토 1차 신호도 여기서 죽었다).
          위 BALANCE-RETRY 주석의 8/5 실측대로 '성공하는 응답은 0.62~1.02초'라
          한 번의 대기를 2.0->1.3초로 줄여도 정상 응답은 그대로 잡는다.
          대신 시도를 3회로 늘려 실패확률을 p^2 -> p^3 으로 낮춘다.
          총 소요 1.3*3 + 0.4*2 = 4.7초 < 신호 TTL 5초 (TTL 은 그대로 지킨다).
          근본 수리는 브로커 대기루프 분리(브로커 재시작 필요, 장중 위험).
          되돌리기: strategy_common_order_v1_20260814_before_prebuy_retry3.py
        """
        return self.holdings(timeout_sec=1.3, attempts=3)

    def open_orders(
        self,
        code: str,
        *,
        buy: bool,
        timeout_sec: float = 8.0,
        attempts: Optional[int] = None,
    ) -> Optional[Dict[str, int]]:
        """Return exact open order numbers. None means broker truth unavailable."""
        if not self.real_session:
            return {}
        if not self.connect():
            return None
        try:
            # Open-order truth is just as safety-critical as holdings truth,
            # but Kiwoom TR responses can be lost while another request owns
            # the shared event loop.  Use the same bounded retry path as
            # holdings instead of abandoning a valid entry after one timeout.
            response = self._balance_tr_retry(
                attempts=attempts,
                tr_code="opt10075",
                inputs={
                    "계좌번호": self.account,
                    "전체종목구분": "1",
                    "매매구분": "2" if buy else "1",
                    "종목코드": str(code).zfill(6),
                    "체결구분": "1",
                },
                output_fields=[
                    "주문번호", "종목코드", "주문구분", "주문수량",
                    "미체결수량", "주문상태",
                ],
                rqname=f"{self.order_prefix}_OPEN_{'B' if buy else 'S'}_{code}",
                screen_no=self.screen_no,
                timeout_sec=float(timeout_sec),
            )
            if str(response.get("status") or "").upper() != "OK":
                self.last_error = str(response.get("error") or "OPEN_ORDER_NOT_OK")
                return None
            output: Dict[str, int] = {}
            for row in ((response.get("data") or {}).get("records") or []):
                order_no = str(row.get("주문번호") or "").strip()
                remaining = int(_number(row.get("미체결수량")))
                if order_no and remaining > 0:
                    output[order_no] = remaining
            return output
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def prebuy_open_orders(
        self,
        code: str,
        *,
        buy: bool,
    ) -> Optional[Dict[str, int]]:
        """Strategy 01 pre-buy check: fail closed within its five-second TTL.

        ★[2026-08-14] prebuy_holdings 와 같은 사유로 1.3초x3회. opt10075 도
          같은 공유 tr_loop 를 쓰므로 같은 가짜 TIMEOUT 을 맞는다
          (8/14 09:59 153890 PREBUY_OPEN_ORDER_UNAVAILABLE 이 그 사례).
        """
        return self.open_orders(
            code,
            buy=buy,
            timeout_sec=1.3,
            attempts=3,
        )

    def submit(
        self,
        *,
        side: str,
        code: str,
        quantity: int,
        idempotency_key: str,
    ) -> str:
        """Return SHADOW, OK, TIMEOUT, UNKNOWN, BLOCKED, or REJECTED."""
        self.last_error = ""
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if side == "BUY" and not self.buy_allowed:
            if not self.real_session:
                return "SHADOW"
            self.last_error = "BUY_KILL_SWITCH_OR_APPROVAL"
            return "BLOCKED"
        if side == "SELL" and not self.real_session:
            return "SHADOW"
        if not self.connect():
            return "UNKNOWN"
        try:
            response = self.client.send_order_real(
                idempotency_key=idempotency_key,
                account=self.account,
                code=str(code).zfill(6),
                qty=int(quantity),
                order_type=1 if side == "BUY" else 2,
                price=0,
                hoga_gb="06",
                rqname=f"{self.order_prefix}_{side}_{str(code).zfill(6)}",
                screen_no=self.screen_no,
                timeout_sec=10.0,
            )
            status = str(response.get("status") or "").upper()
            self.last_error = str(
                response.get("error") or response.get("message") or "")
            if status in {"OK", "TIMEOUT"}:
                return status
            return "REJECTED"
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return "UNKNOWN"

    def cancel(
        self,
        *,
        code: str,
        order_no: str,
        remaining: int,
        buy: bool,
        idempotency_key: str,
    ) -> str:
        if not self.real_session or not order_no:
            return "SHADOW"
        if not self.connect():
            return "UNKNOWN"
        try:
            response = self.client.send_order_real(
                idempotency_key=idempotency_key,
                account=self.account,
                code=str(code).zfill(6),
                qty=int(remaining),
                order_type=3 if buy else 4,
                price=0,
                hoga_gb="00",
                rqname=f"{self.order_prefix}_CANCEL_{'B' if buy else 'S'}_{code}",
                screen_no=self.screen_no,
                origin_order_no=str(order_no),
                timeout_sec=10.0,
            )
            status = str(response.get("status") or "").upper()
            self.last_error = str(response.get("error") or "")
            return status if status in {"OK", "TIMEOUT"} else "REJECTED"
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return "UNKNOWN"

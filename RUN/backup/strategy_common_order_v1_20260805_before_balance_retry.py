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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

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

    def __init__(
        self,
        *,
        live_requested: bool,
        approval_path: Path,
        off_flag_path: Path,
        manual_buy_block_path: Path,
        logger: logging.Logger,
        order_prefix: str = "STRATEGY01",
        screen_no: str = "9781",
        force_exit_only: bool | Callable[[], bool] = False,
    ) -> None:
        self.live_requested = bool(live_requested)
        self.approval_path = Path(approval_path)
        self.off_flag_path = Path(off_flag_path)
        self.manual_buy_block_path = Path(manual_buy_block_path)
        self.log = logger
        self.order_prefix = str(order_prefix).upper()
        self.screen_no = str(screen_no)
        self._force_exit_only = force_exit_only
        self.client = None
        self.account = ""
        self.last_error = ""
        self.live_guard = StrategyBrokerLiveGuard(
            order_prefix=self.order_prefix
        )

    @property
    def force_exit_only(self) -> bool:
        """실포지션 보유 여부를 매 판정마다 다시 묻는다.

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
        """
        value = self._force_exit_only
        if not callable(value):
            return bool(value)
        try:
            return bool(value())
        except Exception as exc:
            self.log.warning(
                "[SELL-LOCK] 보유 판정 실패 - 실매도 허용으로 처리: %s", exc)
            return True

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

    def holdings(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """Return broker truth. None means reconciliation is unavailable."""
        if not self.real_session:
            return {}
        if not self.connect():
            return None
        try:
            response = self.client.balance_tr(
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
                timeout_sec=30.0,
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

    def open_orders(
        self,
        code: str,
        *,
        buy: bool,
    ) -> Optional[Dict[str, int]]:
        """Return exact open order numbers. None means broker truth unavailable."""
        if not self.real_session:
            return {}
        if not self.connect():
            return None
        try:
            response = self.client.balance_tr(
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
                timeout_sec=8.0,
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

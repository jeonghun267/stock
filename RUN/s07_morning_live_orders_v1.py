# -*- coding: utf-8 -*-
"""S07M-only broker order adapter. Imported only after the production replay gate passes."""
from __future__ import annotations

import csv
import json
import time
import uuid
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(r"C:\stock_bot")
AUDIT_DIR = ROOT / "data" / "audit" / "s07_morning_orders"
STATE_PATH = ROOT / "data" / "strategy_07_morning_v1" / "s07m_live_state.json"
FILLS_DIR = ROOT / "LOG"
QUANTITY = 1
MAX_POSITIONS = 6
ENTRY_START = dt_time(9, 0)
ENTRY_END = dt_time(9, 5, 59)
FORCE_EXIT = dt_time(11, 30)


def _number(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


class S07MLiveOrders:
    """One-share, six-position live lifecycle isolated from S01-S06."""

    def __init__(
        self,
        trade_date: str,
        *,
        client: Any | None = None,
        account: str = "",
        audit_dir: Path = AUDIT_DIR,
        state_path: Path = STATE_PATH,
        fills_dir: Path = FILLS_DIR,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.trade_date = str(trade_date)
        self.audit_dir = Path(audit_dir)
        self.state_path = Path(state_path)
        self.fills_dir = Path(fills_dir)
        self.sleep = sleep_fn
        self.orders_sent = 0
        self.positions: dict[str, dict[str, Any]] = {}
        self.attempted: set[str] = set()
        if client is None:
            from broker_client import BrokerClient, is_broker_alive
            if not is_broker_alive():
                raise RuntimeError("BROKER_NOT_ALIVE")
            client = BrokerClient()
        self.client = client
        self.account = str(account or self._load_account())
        if not self.account:
            raise RuntimeError("ACCOUNT_UNAVAILABLE")
        self._load_state()

    def _load_account(self) -> str:
        response = self.client.account_info("ACCNO")
        data = (response or {}).get("data") or {}
        accounts = data.get("accounts") or data.get("ACCNO") or []
        if isinstance(accounts, str):
            accounts = [item for item in accounts.split(";") if item]
        return str(accounts[0]) if accounts else ""

    def _audit(self, event: str, **payload: Any) -> None:
        row = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": event,
            "strategy_id": "S07M",
            **payload,
        }
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        path = self.audit_dir / f"orders_{self.trade_date}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return
        positions = state.get("positions") or {}
        if positions and str(state.get("trade_date")) != self.trade_date:
            # ★[2026-09-02 P1-2] 전일 잔재 상태 — 예외로 죽이지 않고 격리한다.
            #   죽으면 오늘 매매 전체가 안 돌고, 잔재 보유는 어차피 자동처분 대상이
            #   아니다(다른 날 보유를 임의 매도하면 더 위험). 원본은 보존하고 크게 기록.
            stale_date = str(state.get("trade_date"))
            quarantine = self.state_path.with_suffix(f".stale_{stale_date}.json")
            try:
                self.state_path.replace(quarantine)
            except OSError:
                pass
            self._audit("STALE_STATE_QUARANTINED", provenance="[UNVERIFIED]",
                        stale_trade_date=stale_date, stale_positions=sorted(positions),
                        quarantined_to=str(quarantine),
                        note="owner review required; not auto-sold")
            return
        self.positions = {str(code).zfill(6): dict(value) for code, value in positions.items()}
        self.attempted = {str(code).zfill(6) for code in state.get("attempted") or []}

    def _save_state(self) -> None:
        payload = {
            "trade_date": self.trade_date,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "positions": self.positions,
            "attempted": sorted(self.attempted),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _holdings(self) -> dict[str, int] | None:
        response = self.client.balance_tr(
            "opw00018",
            inputs={"계좌번호": self.account, "비밀번호": "", "비밀번호입력매체구분": "00", "조회구분": "2"},
            output_fields=["종목번호", "보유수량", "매매가능수량"],
            rqname="S07M_BALANCE", screen_no="9797", timeout_sec=1.3,
        )
        if str((response or {}).get("status", "")).upper() != "OK":
            return None
        output: dict[str, int] = {}
        for row in (((response or {}).get("data") or {}).get("records") or []):
            code = str(row.get("종목번호") or "").strip().lstrip("A").zfill(6)
            qty = max(0, int(_number(row.get("매매가능수량") or row.get("보유수량"))))
            if code.isdigit() and qty > 0:
                output[code] = qty
        return output

    def _open_orders(self, code: str, *, buy: bool) -> dict[str, int] | None:
        response = self.client.balance_tr(
            "opt10075",
            inputs={"계좌번호": self.account, "전체종목구분": "1", "매매구분": "2" if buy else "1",
                    "종목코드": code, "체결구분": "1"},
            output_fields=["주문번호", "미체결수량"],
            rqname=f"S07M_OPEN_{'B' if buy else 'S'}_{code}", screen_no="9797", timeout_sec=1.3,
        )
        if str((response or {}).get("status", "")).upper() != "OK":
            return None
        output: dict[str, int] = {}
        for row in (((response or {}).get("data") or {}).get("records") or []):
            order_no = str(row.get("주문번호") or "").strip()
            remaining = max(0, int(_number(row.get("미체결수량"))))
            if order_no and remaining:
                output[order_no] = remaining
        return output

    def _submit(self, code: str, *, buy: bool, hoga_gb: str, stage: str) -> str:
        idem = (f"s07m_buy_{self.trade_date}_{code}" if buy
                else f"s07m_sell_{self.trade_date}_{code}_{stage}_{uuid.uuid4()}")
        self._audit("ORDER_REQUEST", provenance="[UNVERIFIED]", code=code, quantity=QUANTITY,
                    side="BUY" if buy else "SELL", hoga_gb=hoga_gb, stage=stage, idempotency_key=idem)
        response = self.client.send_order_real(
            idempotency_key=idem, account=self.account, code=code, qty=QUANTITY,
            order_type=1 if buy else 2, price=0, hoga_gb=hoga_gb,
            rqname=f"S07M_{'BUY' if buy else 'SELL'}_{code}", screen_no="9797", timeout_sec=10.0,
        )
        self.orders_sent += 1
        status = str((response or {}).get("status") or "").upper()
        self._audit("ORDER_RESPONSE", provenance="[UNVERIFIED]", code=code,
                    side="BUY" if buy else "SELL", stage=stage, status=status,
                    response=response)
        return status

    def _cancel_all(self, code: str, *, buy: bool) -> bool:
        orders = self._open_orders(code, buy=buy)
        if orders is None:
            return False
        for order_no, remaining in orders.items():
            response = self.client.send_order_real(
                idempotency_key=f"s07m_cancel_{self.trade_date}_{code}_{order_no}_{uuid.uuid4()}",
                account=self.account, code=code, qty=remaining, order_type=3 if buy else 4,
                price=0, hoga_gb="00", rqname=f"S07M_CANCEL_{code}", screen_no="9797",
                origin_order_no=order_no, timeout_sec=10.0,
            )
            self.orders_sent += 1
            self._audit("CANCEL_RESPONSE", provenance="[UNVERIFIED]", code=code,
                        side="BUY" if buy else "SELL", order_no=order_no, response=response)
        confirmed = self._open_orders(code, buy=buy)
        return confirmed == {}

    def _fill(self, code: str, *, buy: bool, since: datetime) -> dict[str, Any] | None:
        path = self.fills_dir / f"fills_{self.trade_date}.csv"
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            return None
        wanted = "매수" if buy else "매도"
        for row in reversed(rows):
            if str(row.get("code") or "").strip().lstrip("A").zfill(6) != code:
                continue
            if wanted not in str(row.get("otype") or "") or int(_number(row.get("fill_qty"))) <= 0:
                continue
            stamp = _parse_dt(row.get("ts"))
            if stamp is None:
                continue
            left = stamp.replace(tzinfo=None)
            right = since.replace(tzinfo=None)
            if left < right:
                continue
            price = abs(_number(row.get("fill_px")))
            if price <= 0:
                continue
            return {"ts": str(row.get("ts")), "price": price, "quantity": int(_number(row.get("fill_qty"))),
                    "path": str(path), "order_no": str(row.get("order_no") or "")}
        return None

    def _wait_fill_or_flat(self, code: str, *, buy: bool, since: datetime, seconds: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            fill = self._fill(code, buy=buy, since=since)
            if fill:
                return fill
            holdings = self._holdings()
            if holdings is not None and ((buy and holdings.get(code, 0) >= 1) or (not buy and holdings.get(code, 0) == 0)):
                return {"holding_confirmed": True}
            self.sleep(2.0)
        return None

    def _buy(self, row: Mapping[str, Any]) -> None:
        code = str(row.get("code") or "").zfill(6)
        self.attempted.add(code)
        self._save_state()
        holdings = self._holdings()
        opens = self._open_orders(code, buy=True)
        if holdings is None or opens is None or holdings.get(code, 0) > 0 or opens:
            self._audit("BUY_BLOCKED_TRUTH", provenance="[UNVERIFIED]", code=code)
            return
        submitted_at = datetime.now().astimezone()
        status = self._submit(code, buy=True, hoga_gb="06", stage="ENTRY_06")
        if status not in {"OK", "TIMEOUT"}:
            return
        result = self._wait_fill_or_flat(code, buy=True, since=submitted_at, seconds=20.0)
        fill = self._fill(code, buy=True, since=submitted_at)
        if fill:
            entry_price = fill["price"]
            provenance = "[BROKER_FILL]"
            evidence = fill
        elif result and result.get("holding_confirmed"):
            entry_price = abs(_number(row.get("cur")))
            provenance = "[UNVERIFIED]"
            evidence = {"basis": "holding_plus_current_price_fallback"}
        else:
            # ★[2026-09-02 P1-1] 취소 미확인 = 주문이 살아 늦게 체결될 수 있다.
            #   유령 보유(관리 밖 1주)가 최악이므로: 취소 재시도 → 그래도 미확인이면
            #   늦은 체결·보유를 재확인해 있으면 관리 대상으로 편입한다(11:30 강제청산 적용).
            cancelled = self._cancel_all(code, buy=True)
            attempts = 0
            while not cancelled and attempts < 3:
                self.sleep(2.0)
                cancelled = self._cancel_all(code, buy=True)
                attempts += 1
            late_fill = self._fill(code, buy=True, since=submitted_at)
            holdings = self._holdings() or {}
            if late_fill or holdings.get(code, 0) > 0:
                entry_price = late_fill["price"] if late_fill else abs(_number(row.get("cur")))
                provenance = "[BROKER_FILL]" if late_fill else "[UNVERIFIED]"
                self.positions[code] = {"entry_price": entry_price,
                                        "entry_ts": submitted_at.isoformat(),
                                        "name": str(row.get("name") or ""),
                                        "provenance": provenance}
                self._save_state()
                self._audit("LIVE_ENTRY_CONFIRMED", provenance=provenance, code=code,
                            price=entry_price, quantity=QUANTITY,
                            evidence={"basis": "late_fill_adopted_after_cancel_path",
                                      "cancel_confirmed": cancelled})
                return
            self._audit("BUY_UNFILLED_SKIPPED", provenance="[UNVERIFIED]", code=code,
                        cancel_confirmed=cancelled)
            if not cancelled:
                self._audit("BUY_CANCEL_UNCONFIRMED_ALERT", provenance="[UNVERIFIED]",
                            code=code, note="open buy order may still be live; monitor fills")
            return
        self.positions[code] = {"entry_price": entry_price, "entry_ts": submitted_at.isoformat(),
                                "name": str(row.get("name") or ""), "provenance": provenance}
        self._save_state()
        self._audit("LIVE_ENTRY_CONFIRMED", provenance=provenance, code=code, price=entry_price,
                    quantity=QUANTITY, evidence=evidence)

    def _sell(self, code: str, reason: str) -> None:
        holdings = self._holdings()
        if holdings is None:
            self._audit("SELL_BLOCKED_TRUTH", provenance="[UNVERIFIED]", code=code, reason=reason)
            return
        if holdings.get(code, 0) <= 0:
            self.positions.pop(code, None)
            self._save_state()
            return
        if not self._cancel_all(code, buy=False):
            self._audit("SELL_CANCEL_UNCONFIRMED", provenance="[UNVERIFIED]", code=code, reason=reason)
            return
        stages = [("FORCE_MARKET_03", "03", 30.0)] if datetime.now().time() >= FORCE_EXIT else [
            ("EXIT_06", "06", 10.0), ("RECOVERY_MARKET_03", "03", 30.0)]
        for stage, hoga, wait_sec in stages:
            submitted_at = datetime.now().astimezone()
            status = self._submit(code, buy=False, hoga_gb=hoga, stage=stage)
            if status not in {"OK", "TIMEOUT"}:
                continue
            result = self._wait_fill_or_flat(code, buy=False, since=submitted_at, seconds=wait_sec)
            holdings = self._holdings()
            if result or (holdings is not None and holdings.get(code, 0) <= 0):
                fill = self._fill(code, buy=False, since=submitted_at)
                self.positions.pop(code, None)
                self._save_state()
                self._audit("LIVE_EXIT_CONFIRMED", provenance="[BROKER_FILL]" if fill else "[UNVERIFIED]",
                            code=code, reason=reason, evidence=fill or {"basis": "holding_zero"})
                return
            if hoga == "06" and not self._cancel_all(code, buy=False):
                return
        self._audit("SELL_RETRY_REQUIRED", provenance="[UNVERIFIED]", code=code, reason=reason)

    def process(self, row: Mapping[str, Any]) -> None:
        code = str(row.get("code") or "").zfill(6)
        observed = _parse_dt(row.get("observed_at"))
        price = abs(_number(row.get("cur")))
        if observed is None or price <= 0:
            return
        position = self.positions.get(code)
        if position is None:
            if (code not in self.attempted and len(self.positions) < MAX_POSITIONS
                    and ENTRY_START <= observed.time() <= ENTRY_END and price >= 10000):
                self._buy(row)
            return
        entry = _number(position.get("entry_price"))
        change = (price / entry - 1.0) * 100.0 if entry > 0 else 0.0
        reason = ""
        if observed.time() >= FORCE_EXIT:
            reason = "TIME_1130"
        elif change >= 3.0:
            reason = "TAKE_PROFIT_3PCT"
        elif change <= -2.0:
            reason = "STOP_LOSS_2PCT"
        if reason:
            self._sell(code, reason)

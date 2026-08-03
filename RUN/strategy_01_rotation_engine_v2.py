# -*- coding: utf-8 -*-
"""Independent Strategy 01 live/shadow engine.

Entry: strategy_01_open_surge_signal_v1 JSON contract.
Hold/sell: strategy_common_hold_sell_v1.
Orders/recovery: strategy_common_order_v1.

The module never imports or starts a retired monolithic engine.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time as day_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import shared_slots
from strategy_01_signal_contract_v2 import select_fresh_signals
from strategy_common_hold_sell_v1 import (
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)
from strategy_common_order_v1 import StrategyBroker, fills_by_order


KST = ZoneInfo("Asia/Seoul")
STATE_SCHEMA = "strategy_01_rotation_engine_v2"
ACTIVE_PHASES = {"BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"}
BUY_FEE = Decimal("0.00015")
SELL_FEE = Decimal("0.00015")
SELL_TAX = Decimal("0.0018")


def kst_now() -> datetime:
    return datetime.now(KST)


def as_kst(value: datetime) -> datetime:
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def parse_dt(value: Any, fallback: Optional[datetime] = None) -> datetime:
    text = str(value or "").strip()
    if text:
        try:
            return as_kst(datetime.fromisoformat(text))
        except ValueError:
            pass
    return as_kst(fallback or kst_now())


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def read_json(path: Path, default: Any) -> Any:
    try:
        first = path.read_bytes()
        time.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return default
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass(frozen=True)
class Config:
    signal_path: Path = Path(r"C:\stock_bot\data\strategy_01_open_surge_signal_v2.json")
    snapshot_path: Path = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
    board_path: Path = Path(r"C:\stock_bot\data\micro_rank_board.json")
    bars_path: Path = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
    eod_bars_path: Path = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
    names_path: Path = Path(r"C:\stock_bot\data\_code_name_cache.json")
    state_path: Path = Path(r"C:\stock_bot\data\strategy_01_rotation_state_v2.json")
    fills_dir: Path = Path(r"C:\stock_bot\LOG")
    event_dir: Path = Path(r"C:\stock_bot\data\strategy_01_rotation_v2")
    log_path: Path = Path(r"C:\stock_bot\LOG\strategy_01_rotation_v2.log")
    approval_path: Path = Path(r"C:\stock_bot\config\strategy_01_live_approved.flag")
    off_flag_path: Path = Path(r"C:\stock_bot\config\strategy_01_off.flag")
    manual_buy_block_path: Path = Path(r"C:\stock_bot\config\manual_buy_block.flag")
    lock_path: Path = Path(r"C:\stock_bot\data\strategy_01_rotation_v2.lock")
    live_requested: bool = (
        os.environ.get("S01_LIVE", "NO").strip().upper() == "YES"
    )
    quantity: int = int(os.environ.get("S01_QTY", "1"))
    max_slots: int = int(os.environ.get("S01_MAX_SLOTS", "6"))
    max_daily_codes: int = int(os.environ.get("S01_MAX_DAILY_CODES", "6"))
    max_cycles_per_code: int = int(os.environ.get("S01_MAX_CYCLES_PER_CODE", "2"))
    rotation_capital_krw: int = int(os.environ.get("S01_ROTATION_CAPITAL_KRW", "2000000"))
    max_sell_retries: int = int(os.environ.get("S01_MAX_SELL_RETRIES", "3"))
    signal_max_age_sec: float = float(os.environ.get("S01_SIGNAL_MAX_AGE_SEC", "5"))
    snapshot_max_age_sec: float = float(os.environ.get("S01_SNAPSHOT_MAX_AGE_SEC", "4"))
    board_max_age_sec: float = float(os.environ.get("S01_BOARD_MAX_AGE_SEC", "8"))
    fill_wait_sec: float = float(os.environ.get("S01_FILL_WAIT_SEC", "8"))
    loop_sec: float = float(os.environ.get("S01_LOOP_SEC", "1"))
    entry_start: day_time = day_time(9, 0)
    entry_end: day_time = day_time(9, 20)
    force_exit: day_time = day_time(15, 10)
    process_end: day_time = day_time(15, 25)
    state_schema: str = STATE_SCHEMA
    strategy_id: StrategyId = StrategyId.S01_OPEN_SURGE
    strategy_slug: str = "strategy01"
    strategy_label: str = "Strategy 01"
    slot_owner: str = "STRATEGY01"
    broker_order_prefix: str = "STRATEGY01"
    event_prefix: str = "strategy_01"

    def __post_init__(self) -> None:
        if self.quantity != 1:
            raise ValueError(f"{self.strategy_label} validation requires exactly one share")
        if self.max_slots != 6:
            raise ValueError(f"{self.strategy_label} requires exactly six concurrent slots")
        required_daily_codes = (
            15
            if self.strategy_id == StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
            else 6
        )
        if self.max_daily_codes != required_daily_codes:
            raise ValueError(
                f"{self.strategy_label} requires exactly "
                f"{required_daily_codes} distinct codes per day"
            )
        if self.max_cycles_per_code != 2:
            raise ValueError(
                f"{self.strategy_label} requires exactly two entries per code"
            )
        if self.rotation_capital_krw <= 0:
            raise ValueError("rotation_capital_krw must be positive")
        if self.max_sell_retries < 1:
            raise ValueError("max_sell_retries must be positive")
        if not all((
            self.state_schema,
            self.strategy_slug,
            self.strategy_label,
            self.slot_owner,
            self.broker_order_prefix,
            self.event_prefix,
        )):
            raise ValueError("strategy identity fields must not be empty")


def setup_logger(config: Config) -> logging.Logger:
    logger = logging.getLogger(config.strategy_slug)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(config.log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console)
    return logger


class FlowWindows:
    def __init__(self) -> None:
        self.rows: Dict[str, deque[Tuple[datetime, float, float]]] = defaultdict(deque)

    def add(self, code: str, observed_at: datetime, buy: float, sell: float) -> None:
        rows = self.rows[code]
        if rows and (buy < rows[-1][1] or sell < rows[-1][2]):
            rows.clear()
        rows.append((observed_at, buy, sell))
        while rows and (observed_at - rows[0][0]).total_seconds() > 40:
            rows.popleft()

    def rates(self, code: str, seconds: int) -> Optional[Tuple[float, float]]:
        rows = self.rows.get(code)
        if not rows or len(rows) < 2:
            return None
        end = rows[-1]
        eligible = [
            row for row in rows
            if (end[0] - row[0]).total_seconds() >= seconds
        ]
        if not eligible:
            return None
        start = eligible[-1]
        elapsed = (end[0] - start[0]).total_seconds()
        if elapsed <= 0:
            return None
        return (
            max(0.0, end[1] - start[1]) / elapsed,
            max(0.0, end[2] - start[2]) / elapsed,
        )


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                existing = int(self.path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                existing = 0
            if self._pid_alive(existing):
                return False
            try:
                self.path.unlink()
            except OSError:
                return False
        try:
            descriptor = os.open(
                str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            self.acquired = True
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            if int(self.path.read_text(encoding="ascii").strip()) == os.getpid():
                self.path.unlink()
        except (OSError, ValueError):
            pass
        self.acquired = False


class Strategy01Engine:
    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        broker: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        slots: Any = shared_slots,
        signal_selector: Any = select_fresh_signals,
    ) -> None:
        self.config = config or Config()
        self.log = logger or setup_logger(self.config)
        self.slots = slots
        self.signal_selector = signal_selector
        self.exit_engine = UnifiedHoldSellEngine()
        self.windows = FlowWindows()
        self._daily_ma: Optional[Dict[str, Dict[str, float]]] = None
        self.names = self._load_names()
        self.state = self._load_state()
        force_exit_only = any(
            position.get("real") and position.get("phase") in ACTIVE_PHASES
            for position in (self.state.get("positions") or {}).values()
        )
        self.broker = broker or StrategyBroker(
            live_requested=self.config.live_requested,
            approval_path=self.config.approval_path,
            off_flag_path=self.config.off_flag_path,
            manual_buy_block_path=self.config.manual_buy_block_path,
            logger=self.log,
            order_prefix=self.config.broker_order_prefix,
            force_exit_only=force_exit_only,
        )
        self._last_reconcile_epoch: Dict[str, float] = {}
        self._last_data_warning = ""
        self._startup_reconcile()

    def _blank_state(self, day: str) -> Dict[str, Any]:
        return {
            "schema": self.config.state_schema,
            "date": day,
            "order_attempts_total": 0,
            "consumed_signals": [],
            "positions": {},
            "cycles_by_code": {},
            "entered_codes": [],
            "history": [],
            "recovery_blocked": False,
            "last_error": "",
            "heartbeat": "",
        }

    def _load_state(self) -> Dict[str, Any]:
        now = kst_now()
        today = now.strftime("%Y%m%d")
        payload = read_json(self.config.state_path, {})
        if payload.get("schema") != self.config.state_schema:
            return self._blank_state(today)
        if not isinstance(payload.get("positions"), dict):
            return self._blank_state(today)
        active = any(
            position.get("phase") in ACTIVE_PHASES
            for position in payload["positions"].values()
            if isinstance(position, dict)
        )
        if str(payload.get("date") or "") != today and not active:
            return self._blank_state(today)
        if str(payload.get("date") or "") != today and active:
            payload["recovery_blocked"] = True
            payload["last_error"] = "ACTIVE_POSITION_FROM_PREVIOUS_DAY"
        payload.setdefault("order_attempts_total", 0)
        payload.setdefault("consumed_signals", [])
        payload.setdefault("cycles_by_code", {})
        entered_codes = [
            str(code).zfill(6)
            for code in (payload.get("entered_codes") or [])
            if str(code).strip()
        ]
        for code, cycles in payload["cycles_by_code"].items():
            normalized = str(code).zfill(6)
            if int(cycles or 0) > 0 and normalized not in entered_codes:
                entered_codes.append(normalized)
        for code, position in payload["positions"].items():
            normalized = str(code).zfill(6)
            if (
                isinstance(position, dict)
                and position.get("entry_at")
                and normalized not in entered_codes
            ):
                entered_codes.append(normalized)
        payload["entered_codes"] = entered_codes
        payload.setdefault("history", [])
        return payload
    def _load_names(self) -> Dict[str, str]:
        payload = read_json(self.config.names_path, {})
        raw = payload.get("map", payload) if isinstance(payload, dict) else {}
        return {str(code).zfill(6): str(name) for code, name in raw.items()}

    def _save(self) -> None:
        self.state["heartbeat"] = kst_now().isoformat(timespec="seconds")
        write_json_atomic(self.config.state_path, self.state)

    def _positions(self) -> Dict[str, Dict[str, Any]]:
        positions = self.state.setdefault("positions", {})
        return positions if isinstance(positions, dict) else {}

    def _active_positions(self) -> Dict[str, Dict[str, Any]]:
        return {
            code: position
            for code, position in self._positions().items()
            if position.get("phase") in ACTIVE_PHASES
        }

    def _active_capital_krw(self) -> int:
        total = Decimal("0")
        for position in self._active_positions().values():
            pending = position.get("pending") or {}
            quantity = (
                int(pending.get("requested_qty") or self.config.quantity)
                if position.get("phase") == "BUY_PENDING"
                else int(position.get("qty") or self.config.quantity)
            )
            price = number(position.get("entry_price"))
            if price <= 0:
                price = number(position.get("last_price"))
            total += Decimal(str(max(0.0, price))) * max(0, quantity)
        return int(total)

    def _update_excursion(
        self, position: Dict[str, Any], price: float, observed_at: datetime,
    ) -> None:
        entry = number(position.get("entry_price"))
        current = number(price)
        if entry <= 0 or current <= 0:
            return
        return_pct = (current / entry - 1.0) * 100.0
        position["mfe_pct"] = max(0.0, number(position.get("mfe_pct")), return_pct)
        position["mae_pct"] = min(0.0, number(position.get("mae_pct")), return_pct)
        position["peak_price"] = max(entry, number(position.get("peak_price")), current)
        position["trough_price"] = min(entry, number(position.get("trough_price"), entry), current)
        position["excursion_updated_at"] = as_kst(observed_at).isoformat(timespec="seconds")

    def _refresh_recovery_blocked(self) -> None:
        self.state["recovery_blocked"] = any(
            position.get("phase") == "RECOVERY_BLOCKED"
            for position in self._positions().values()
        )

    def _cleanup_terminal(self) -> None:
        history = self.state.setdefault("history", [])
        for code, position in list(self._positions().items()):
            if position.get("phase") not in {"CLOSED", "FAILED"}:
                continue
            archived = dict(position)
            archived["archived_at"] = kst_now().isoformat(timespec="seconds")
            history.append(archived)
            del self._positions()[code]
        if len(history) > 200:
            del history[:-200]
        self._refresh_recovery_blocked()
    def _update_post_exit_audit(self, now: datetime) -> None:
        for position in self.state.setdefault("history", []):
            if position.get("phase") != "CLOSED" or not position.get("exit_at"):
                continue
            audit = position.setdefault("post_exit_audit", {})
            targets = audit.setdefault("targets", {})
            exit_at = parse_dt(position.get("exit_at"), now)
            elapsed_sec = max(0.0, (now - exit_at).total_seconds())
            due = [
                minutes for minutes in (15, 30, 60)
                if str(minutes) not in targets and elapsed_sec >= minutes * 60
            ]
            if not due:
                continue
            code = str(position.get("code") or "").zfill(6)
            point = self._snapshot_point(code, now)
            for minutes in due:
                key = str(minutes)
                if elapsed_sec > minutes * 60 + 120:
                    targets[key] = {
                        "status": "MISSED_NO_FRESH_PRICE",
                        "target_min": minutes,
                        "checked_at": now.isoformat(timespec="seconds"),
                    }
                    continue
                if point is None:
                    continue
                exit_price = number(position.get("exit_price"))
                entry_price = number(position.get("entry_price"))
                current = number(point.get("price"))
                from_exit = (current / exit_price - 1.0) * 100.0 if exit_price > 0 else 0.0
                from_entry = (current / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
                targets[key] = {
                    "status": "CAPTURED",
                    "target_min": minutes,
                    "captured_at": point["ts"].isoformat(timespec="seconds"),
                    "actual_elapsed_min": round(elapsed_sec / 60.0, 2),
                    "price": current,
                    "return_from_exit_pct": round(from_exit, 4),
                    "return_from_entry_pct": round(from_entry, 4),
                }
                self._event(
                    "POST_EXIT_AUDIT", code=code, name=str(position.get("name") or ""),
                    price=current, reason=(
                        f"{minutes}m from_exit={from_exit:.3f}% "
                        f"from_entry={from_entry:.3f}%"
                    ),
                )

    def _event(
        self,
        event: str,
        *,
        code: str = "",
        name: str = "",
        price: float = 0.0,
        quantity: int = 0,
        reason: str = "",
        order_no: str = "",
    ) -> None:
        now = kst_now()
        path = (
            self.config.event_dir
            / f"{self.config.event_prefix}_events_{now:%Y%m%d}.csv"
        )
        columns = [
            "ts", "strategy_id", "event", "code", "name", "price", "quantity",
            "reason", "order_no", "mode", "order_attempts_total", "active_slots", "capital_in_use_krw",
        ]
        row = {
            "ts": now.isoformat(timespec="seconds"),
            "strategy_id": self.config.strategy_id.value,
            "event": event,
            "code": code,
            "name": name,
            "price": round(price, 2),
            "quantity": quantity,
            "reason": reason,
            "order_no": order_no,
            "mode": getattr(self.broker, "mode", "UNKNOWN"),
            "order_attempts_total": self.state.get("order_attempts_total", 0),
            "active_slots": len(self._active_positions()),
            "capital_in_use_krw": self._active_capital_krw(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            if new:
                writer.writeheader()
            writer.writerow(row)
        self.log.info(
            "%s %s(%s) x%d %.0f %s",
            event, name or "-", code or "-", quantity, price, reason)

    def _startup_reconcile(self) -> None:
        real_positions = [
            position for position in self._active_positions().values()
            if position.get("real")
        ]
        if not real_positions:
            return
        if not self.broker.connect():
            self.state["recovery_blocked"] = True
            self.state["last_error"] = f"BROKER_CONNECT: {self.broker.last_error}"
            self._save()
            return
        holdings = self.broker.holdings()
        if holdings is None:
            self.state["recovery_blocked"] = True
            self.state["last_error"] = f"BALANCE_QUERY: {self.broker.last_error}"
            self._save()
            return
        for position in real_positions:
            code = str(position.get("code") or "").zfill(6)
            actual = holdings.get(code) or {}
            phase = str(position.get("phase") or "")
            if phase == "HOLD":
                if int(actual.get("qty") or 0) <= 0:
                    self._confirm_exit(
                        position,
                        number(position.get("last_price")),
                        "RECOVERY_ALREADY_FLAT",
                    )
                else:
                    position["qty"] = min(
                        int(position.get("qty") or 0) or int(actual["qty"]),
                        int(actual["qty"]),
                    )
                    if number(position.get("entry_price")) <= 0:
                        position["entry_price"] = number(actual.get("buy_price"))
            elif phase == "SELL_PENDING" and int(actual.get("qty") or 0) <= 0:
                self._confirm_exit(
                    position,
                    number(position.get("last_price")),
                    "RECOVERY_FLAT",
                )
        self._refresh_recovery_blocked()
        self._save()
    def _release_slot(self, position: Mapping[str, Any]) -> None:
        if not position.get("slot_reserved"):
            return
        try:
            self.slots.release(
                str(position.get("code") or "").zfill(6),
                str(self.state.get("date") or ""),
            )
        except Exception as exc:
            self.state["last_error"] = f"SLOT_RELEASE: {exc}"

    def _snapshot_point(self, code: str, now: datetime) -> Optional[Dict[str, Any]]:
        snapshot = read_json(self.config.snapshot_path, {})
        raw = (snapshot.get("codes") or {}).get(str(code).zfill(6))
        if not isinstance(raw, dict):
            return None
        observed_at = parse_dt(raw.get("ts"), now)
        if abs((now - observed_at).total_seconds()) > self.config.snapshot_max_age_sec:
            return None
        price = abs(number(raw.get("cur")))
        if price <= 0:
            return None
        board_payload = read_json(self.config.board_path, {})
        board_at = parse_dt(board_payload.get("ts"), now)
        board_fresh = (
            abs((now - board_at).total_seconds()) <= self.config.board_max_age_sec
        )
        board_row: Mapping[str, Any] = {}
        if board_fresh:
            board_row = next((
                row for row in (board_payload.get("all_items") or [])
                if str(row.get("code") or "").zfill(6) == str(code).zfill(6)
            ), {})
        return {
            "code": str(code).zfill(6),
            "ts": observed_at,
            "price": price,
            "cum_vol": max(0.0, number(raw.get("cum_vol"))),
            "buy_money_cum": number(raw.get("buy_money_cum"), -1.0),
            "sell_money_cum": number(raw.get("sell_money_cum"), -1.0),
            "money_speed_5s": max(0.0, number(board_row.get("money_speed_5s"))),
            "money_speed_10s": max(0.0, number(board_row.get("money_speed_10s"))),
            "money_speed_30s": max(0.0, number(board_row.get("money_speed_30s"))),
            "board_fresh": board_fresh,
        }

    def _known_orders(self, code: str, side: str) -> Optional[list[str]]:
        known = set(fills_by_order(
            self.config.fills_dir, code, side, day=str(self.state["date"])))
        open_orders = self.broker.open_orders(code, buy=(side == "매수"))
        if open_orders is None:
            return None
        known.update(open_orders)
        return sorted(known)

    def _discover_order(
        self,
        position: Dict[str, Any],
        *,
        side: str,
    ) -> Tuple[str, Dict[str, Tuple[int, float]], Optional[Dict[str, int]]]:
        pending = position["pending"]
        code = position["code"]
        fills = fills_by_order(
            self.config.fills_dir,
            code,
            side,
            str(pending.get("since_hms") or "00:00:00"),
            str(self.state["date"]),
        )
        open_orders = self.broker.open_orders(code, buy=(side == "매수"))
        current = str(pending.get("order_no") or "")
        if current:
            return current, fills, open_orders
        known = set(pending.get("known_orders") or [])
        candidates = (set(fills) | set(open_orders or {})) - known
        if len(candidates) == 1:
            current = next(iter(candidates))
            pending["order_no"] = current
            self._event(
                "ORDER_NUMBER_CONFIRMED",
                code=code,
                name=position.get("name", ""),
                order_no=current,
                reason=side,
            )
        elif len(candidates) > 1:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = (
                f"AMBIGUOUS_{side}_ORDER_NUMBERS:{','.join(sorted(candidates))}")
            self._event(
                "ORDER_NUMBER_AMBIGUOUS",
                code=code,
                reason=self.state["last_error"],
            )
        return current, fills, open_orders

    def _try_entries(self, now: datetime) -> None:
        if self.state.get("recovery_blocked"):
            return
        payload = read_json(self.config.signal_path, {})
        rows = self.signal_selector(
            payload,
            now=now,
            max_age_sec=self.config.signal_max_age_sec,
            consumed=self.state.get("consumed_signals") or [],
        )
        candidate_count = len(rows)
        for candidate_rank, signal in enumerate(rows, start=1):
            if len(self._active_positions()) >= self.config.max_slots:
                return
            code = str(signal["code"]).zfill(6)
            signal_id = str(signal["signal_id"])
            name = str(signal.get("name") or self.names.get(code) or code)
            if code in self._active_positions():
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="CODE_ALREADY_ACTIVE",
                )
                continue
            entered_codes = {
                str(item).zfill(6)
                for item in (self.state.get("entered_codes") or [])
            }
            cycles = int(
                (self.state.get("cycles_by_code") or {}).get(code) or 0)
            if code in entered_codes and cycles >= self.config.max_cycles_per_code:
                self.state.setdefault("consumed_signals", []).append(signal_id)
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="CODE_DAILY_ENTRY_LIMIT_2",
                )
                continue
            if code not in entered_codes and len(entered_codes) >= self.config.max_daily_codes:
                self.state.setdefault("consumed_signals", []).append(signal_id)
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="DAILY_DISTINCT_CODE_LIMIT_6",
                )
                continue
            cycles = int((self.state.get("cycles_by_code") or {}).get(code) or 0)
            if cycles >= self.config.max_cycles_per_code:
                self.state.setdefault("consumed_signals", []).append(signal_id)
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="CODE_DAILY_ENTRY_LIMIT_2",
                )
                continue
            point = self._snapshot_point(code, now)
            if point is None:
                continue
            required = int(
                Decimal(str(point["price"])) * int(self.config.quantity))
            if self._active_capital_krw() + required > self.config.rotation_capital_krw:
                self._event(
                    "BUY_WAIT", code=code, name=name, price=point["price"],
                    quantity=self.config.quantity,
                    reason=(
                        f"ROTATION_CAPITAL_WAIT "
                        f"{self._active_capital_krw()}+{required}>"
                        f"{self.config.rotation_capital_krw}"
                    ),
                )
                continue

            if getattr(self.broker, "real_session", False):
                if not getattr(self.broker, "buy_allowed", False):
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason="APPROVAL_OR_OFF_FLAG",
                    )
                    self._save()
                    return
                holdings = self.broker.holdings()
                if holdings is None:
                    self.state["last_error"] = (
                        f"PREBUY_BALANCE_UNAVAILABLE:{self.broker.last_error}")
                    self._event(
                        "BUY_WAIT", code=code, name=name,
                        reason=self.state["last_error"],
                    )
                    self._save()
                    return
                if code in holdings:
                    self.state.setdefault("consumed_signals", []).append(signal_id)
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason="ACCOUNT_ALREADY_HOLDS_CODE",
                    )
                    continue
                open_buy = self.broker.open_orders(code, buy=True)
                if open_buy is None:
                    self.state["last_error"] = "PREBUY_OPEN_ORDER_UNAVAILABLE"
                    self._event(
                        "BUY_WAIT", code=code, name=name,
                        reason=self.state["last_error"],
                    )
                    self._save()
                    return
                if open_buy:
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason="ACCOUNT_OPEN_BUY_ALREADY_EXISTS",
                    )
                    continue
                known_orders = self._known_orders(code, "매수")
                if known_orders is None:
                    self.state["last_error"] = "PREBUY_ORDER_HISTORY_UNAVAILABLE"
                    self._event(
                        "BUY_WAIT", code=code, name=name,
                        reason=self.state["last_error"],
                    )
                    self._save()
                    return
                if not self.slots.acquire(
                    code, self.config.slot_owner, self.state["date"]
                ):
                    self._event(
                        "BUY_WAIT", code=code, name=name,
                        reason="SHARED_SLOT_OR_DUPLICATE",
                    )
                    continue
                slot_reserved = True
            else:
                known_orders = []
                slot_reserved = False

            attempt = int(self.state.get("order_attempts_total") or 0) + 1
            order_key = (
                f"{self.config.strategy_slug}:"
                f"{self.state['date']}:buy:{code}:{attempt}"
            )
            pending = {
                "side": "BUY",
                "idempotency_key": order_key,
                "known_orders": known_orders,
                "order_no": "",
                "requested_qty": self.config.quantity,
                "pre_hold_qty": 0,
                "since_hms": now.strftime("%H:%M:%S"),
                "sent_epoch": time.time(),
                "cancel_requested": False,
                "cancel_epoch": 0.0,
                "last_status": "PREPARED",
                "reason": str(signal.get("reason") or "OPEN_SURGE_CONFIRMED"),
            }
            position = {
                "phase": "BUY_PENDING",
                "real": bool(getattr(self.broker, "real_session", False)),
                "code": code,
                "name": name,
                "qty": 0,
                "entry_price": 0.0,
                "entry_at": "",
                "last_price": point["price"],
                "last_ts": point["ts"].isoformat(),
                "signal_id": signal_id,
                "entry_lane": str(signal.get("entry_lane") or ""),
                "signal_sequence": int(signal.get("signal_sequence") or 0),
                "candidate_rank_at_entry": candidate_rank,
                "candidate_count_at_entry": candidate_count,
                "cycle_target": cycles + 1,
                "reserved_capital_krw": required,
                "slot_reserved": slot_reserved,
                "pending": pending,
                "hold_state": None,
                "sell_retries": 0,
                "retry_after_epoch": 0.0,
            }
            self.state.setdefault("consumed_signals", []).append(signal_id)
            self._positions()[code] = position
            self.state["order_attempts_total"] = attempt
            self._save()
            status = self.broker.submit(
                side="BUY",
                code=code,
                quantity=self.config.quantity,
                idempotency_key=order_key,
            )
            pending["last_status"] = status
            if status == "SHADOW":
                self._confirm_entry(
                    position, self.config.quantity, point["price"], now, shadow=True)
            elif status == "OK":
                self._event(
                    "BUY_PENDING", code=code, name=name,
                    price=point["price"], quantity=self.config.quantity,
                    reason="OK: exact fill reconciliation",
                )
            elif status in {"TIMEOUT", "UNKNOWN"}:
                position["phase"] = "RECOVERY_BLOCKED"
                self.state["recovery_blocked"] = True
                self.state["last_error"] = f"BUY_{status}_BROKER_TRUTH_REQUIRED"
                self._event(
                    "RECOVERY_BLOCKED", code=code, name=name,
                    price=point["price"], quantity=self.config.quantity,
                    reason=self.state["last_error"],
                )
                self._save()
                return
            else:
                position["phase"] = "FAILED"
                self._release_slot(position)
                position["slot_reserved"] = False
                self._event(
                    "BUY_REJECTED", code=code, name=name,
                    price=point["price"], quantity=self.config.quantity,
                    reason=f"{status}: {getattr(self.broker, 'last_error', '')}",
                )
            self._save()
    def _confirm_entry(
        self,
        position: Dict[str, Any],
        quantity: int,
        fill_price: float,
        observed_at: datetime,
        *,
        shadow: bool = False,
    ) -> None:
        fill_price = fill_price or number(position.get("last_price"))
        code = str(position.get("code") or "").zfill(6)
        entered_codes = self.state.setdefault("entered_codes", [])
        if code not in entered_codes:
            entered_codes.append(code)
        hold_state = HoldSellState(
            position_id=(
                f"{self.config.strategy_slug}:"
                f"{self.state['date']}:{position['code']}:"
                f"cycle-{int(position.get('cycle_target') or 1)}:"
                f"{(position.get('pending') or {}).get('order_no') or 'shadow'}"
            ),
            strategy_id=self.config.strategy_id,
            code=position["code"],
            quantity=int(quantity),
            entry_price=Decimal(str(fill_price)),
            entry_at=as_kst(observed_at),
            entry_lane=str(position.get("entry_lane") or ""),
        )
        position.update({
            "phase": "HOLD",
            "qty": int(quantity),
            "entry_price": fill_price,
            "entry_at": as_kst(observed_at).isoformat(),
            "hold_state": hold_state.to_dict(),
            "pending": None,
            "real": not shadow,
        })
        self._update_excursion(position, fill_price, observed_at)
        self._refresh_recovery_blocked()
        self._event(
            "SHADOW_BUY" if shadow else "BUY_CONFIRMED",
            code=position["code"], name=position["name"],
            price=fill_price, quantity=quantity,
            reason=(
                ("exact fill" if not shadow else "order zero")
                + f" rank={int(position.get('candidate_rank_at_entry') or 0)}/"
                + f"{int(position.get('candidate_count_at_entry') or 0)}"
            ),
        )

    def _buy_pending_step(self, position: Dict[str, Any], now: datetime) -> None:
        pending = position["pending"]
        code = position["code"]
        order_no, fills, open_orders = self._discover_order(position, side="매수")
        if position["phase"] == "RECOVERY_BLOCKED":
            return
        quantity, average = fills.get(order_no, (0, 0.0)) if order_no else (0, 0.0)
        needed = int(pending["requested_qty"])
        if quantity >= needed:
            self._confirm_entry(position, needed, average, now)
            return

        if pending.get("cancel_requested"):
            if time.time() - number(pending.get("cancel_epoch")) < 2:
                return
            if open_orders is None:
                return
            if order_no and order_no in open_orders:
                return
            holdings = self.broker.holdings()
            if holdings is None:
                return
            fills = fills_by_order(
                self.config.fills_dir, code, "매수",
                pending["since_hms"], self.state["date"])
            quantity, average = fills.get(order_no, (0, 0.0)) if order_no else (0, 0.0)
            actual = holdings.get(code) or {}
            if quantity > 0:
                self._confirm_entry(position, min(quantity, needed), average, now)
            elif int(actual.get("qty") or 0) > int(pending.get("pre_hold_qty") or 0):
                self._confirm_entry(
                    position,
                    min(needed, int(actual["qty"])),
                    number(actual.get("buy_price")) or number(position["last_price"]),
                    now,
                )
            else:
                position["phase"] = "FAILED"
                self._release_slot(position)
                position["slot_reserved"] = False
                position["pending"] = None
                self._event("BUY_FILL_ZERO", code=code, name=position["name"],
                            reason="cancel confirmed and broker balance unchanged")
            return

        elapsed = time.time() - number(pending.get("sent_epoch"))
        if elapsed < self.config.fill_wait_sec and quantity == 0:
            return
        if order_no:
            remaining = (
                (open_orders or {}).get(order_no)
                or max(1, needed - quantity)
            )
            pending["cancel_requested"] = True
            pending["cancel_epoch"] = time.time()
            self._save()
            status = self.broker.cancel(
                code=code,
                order_no=order_no,
                remaining=remaining,
                buy=True,
                idempotency_key=(
                    f"{self.config.strategy_slug}:"
                    f"{self.state['date']}:cancel-buy:{order_no}"
                ),
            )
            self._event("BUY_CANCEL_PENDING", code=code, name=position["name"],
                        quantity=remaining, order_no=order_no, reason=status)
            return

        holdings = self.broker.holdings()
        if open_orders is None or holdings is None:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = "BUY_RESULT_UNKNOWN_BROKER_TRUTH_UNAVAILABLE"
            self._event("RECOVERY_BLOCKED", code=code,
                        reason=self.state["last_error"])
            return
        actual = holdings.get(code) or {}
        if int(actual.get("qty") or 0) > int(pending.get("pre_hold_qty") or 0):
            self._confirm_entry(
                position,
                min(needed, int(actual["qty"])),
                number(actual.get("buy_price")) or number(position["last_price"]),
                now,
            )
            return
        candidates = set(open_orders) - set(pending.get("known_orders") or [])
        if candidates:
            return
        position["phase"] = "FAILED"
        self._release_slot(position)
        position["slot_reserved"] = False
        position["pending"] = None
        self._event("BUY_NOT_CREATED", code=code, name=position["name"],
                    reason="fills/open orders/balance all zero")

    def _load_daily_ma(self) -> None:
        """일봉 종가로 5·10·20일선과 20일선 전일값을 1회 캐시한다(TR 0·읽기 전용)."""
        if self._daily_ma is not None:
            return
        self._daily_ma = {}
        by_code: Dict[str, Dict[str, float]] = {}
        try:
            with self.config.eod_bars_path.open(encoding="utf-8-sig", newline="") as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    if len(code) == 6 and code.isdigit() and day and close > 0:
                        by_code.setdefault(code, {})[day] = close
        except OSError:
            self.log.warning("일봉 파일 없음 — 상승보유 허가 비활성")
            return
        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            self._daily_ma[code] = {
                "ma5": sum(closes[-5:]) / 5,
                "ma10": sum(closes[-10:]) / 10,
                "ma20": sum(closes[-20:]) / 20,
                "ma20_prev": sum(closes[-21:-1]) / 20,
            }
        self.log.info("일봉 이평 캐시 %d종목 (5·10·20일선)", len(self._daily_ma))

    def _recent_3min_high(self, code: str) -> float:
        """완성 1분봉 3개(=3분봉 1개)의 고가. 자료가 없으면 0."""
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        previous = ((source or {}).get(code) or {}).get("prev") or []
        highs = [
            number(bar[1]) for bar in previous[-3:]
            if len(bar) >= 2 and number(bar[1]) > 0
        ]
        return max(highs) if len(highs) == 3 else 0.0

    def _daily_ma_permit(self, code: str, price: float) -> bool:
        """상승보유 허가 — 친구님 확정 조건.

        3분봉이 5일선을 횡보(고가가 5일선 이상)하고, 10일선이 뒤를 받치며(5일선 위 정배열),
        10일선을 침범해도 20일선이 우상향으로 보조하면 매도하지 않고 상승보유한다.
        따라서 현재가가 10일선 아래인지는 조건에 넣지 않는다(침범 허용).
        """
        self._load_daily_ma()
        row = (self._daily_ma or {}).get(code)
        if not row:
            return False
        ma5, ma10, ma20, ma20_prev = (
            row["ma5"], row["ma10"], row["ma20"], row["ma20_prev"])
        if not (ma5 > 0 and ma10 > 0 and ma20 > 0):
            return False
        if not ma5 > ma10:                      # 10일선이 뒤를 받치는 정배열
            return False
        if not ma20 > ma20_prev:                # 20일선 우상향 보조
            return False
        high3 = self._recent_3min_high(code)
        reference = high3 if high3 > 0 else price
        return reference >= ma5                 # 3분봉이 5일선을 횡보(걸치거나 위)

    def _completed_structure_low(self, code: str) -> float:
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        row = (source or {}).get(code) or {}
        previous = row.get("prev") or []
        lows = [
            number(bar[2]) for bar in previous[-3:]
            if len(bar) >= 3 and number(bar[2]) > 0
        ]
        return min(lows) if len(lows) == 3 else 0.0

    def _build_observation(
        self,
        position: Dict[str, Any],
        point: Dict[str, Any],
    ) -> HoldSellObservation:
        code = position["code"]
        observed_at = point["ts"]
        buy_cum = point["buy_money_cum"]
        sell_cum = point["sell_money_cum"]
        exact = buy_cum >= 0 and sell_cum >= 0
        if exact:
            self.windows.add(code, observed_at, buy_cum, sell_cum)
        rate10 = self.windows.rates(code, 10) if exact else None
        rate30 = self.windows.rates(code, 30) if exact else None
        buy30, sell30 = rate30 or rate10 or (0.0, 0.0)
        buy10, sell10 = rate10 or (buy30, sell30)
        total = buy30 + sell30
        ratio = buy30 / total if total > 0 else 0.60
        volume = point["cum_vol"]
        vwap = (
            (buy_cum + sell_cum) / volume
            if exact and volume > 0 else 0.0
        )
        price = point["price"]
        if not (price * 0.5 <= vwap <= price * 2.0):
            vwap = 0.0
        structure_low = self._completed_structure_low(code)
        return HoldSellObservation(
            observed_at=observed_at,
            price=Decimal(str(price)),
            vwap=Decimal(str(vwap)),
            buy_ratio_recent=Decimal(str(ratio)),
            money_speed_5s=Decimal(str(point["money_speed_5s"])),
            money_speed_10s=Decimal(str(point["money_speed_10s"])),
            money_speed_30s=Decimal(str(point["money_speed_30s"])),
            buy_money_per_sec_10s=Decimal(str(buy10)),
            sell_money_per_sec_10s=Decimal(str(sell10)),
            buy_money_per_sec_30s=Decimal(str(buy30)),
            sell_money_per_sec_30s=Decimal(str(sell30)),
            structure_broken=bool(structure_low > 0 and price < structure_low),
            money_accelerating=bool(
                point["money_speed_10s"] > 0
                and point["money_speed_5s"] >= point["money_speed_10s"]
            ),
            recent_buy_money_rising=bool(
                rate10 and rate30 and rate10[0] >= rate30[0]),
            daily_ma_permit=self._daily_ma_permit(code, price),
        )

    def _direct_hard_stop_permitted(
        self,
        _position: Dict[str, Any],
        _point: Dict[str, Any],
    ) -> bool:
        return True

    def _position_force_exit_at(
        self,
        _position: Dict[str, Any],
    ) -> day_time:
        return self.config.force_exit

    def _evaluate_exit(
        self,
        position: Dict[str, Any],
        now: datetime,
    ) -> None:
        if time.time() < number(position.get("retry_after_epoch")):
            return
        force_exit_at = self._position_force_exit_at(position)
        point = self._snapshot_point(position["code"], now)
        if point is None:
            if now.time() >= force_exit_at:
                self._start_sell(
                    position,
                    now,
                    f"TIME_EXIT_{force_exit_at.strftime('%H%M')}",
                    None,
                )
            return
        position["last_price"] = point["price"]
        position["last_ts"] = point["ts"].isoformat()
        self._update_excursion(position, point["price"], point["ts"])
        entry_price = number(position.get("entry_price"))
        return_pct = (
            (point["price"] / entry_price - 1.0) * 100
            if entry_price > 0 else 0.0
        )
        if return_pct <= -2.0 and self._direct_hard_stop_permitted(
            position, point
        ):
            self._start_sell(position, now, f"HARD_STOP {return_pct:.2f}%", point)
            return
        if now.time() >= force_exit_at:
            self._start_sell(
                position,
                now,
                f"TIME_EXIT_{force_exit_at.strftime('%H%M')}",
                point,
            )
            return
        if not point["board_fresh"]:
            return
        hold_state = HoldSellState.from_dict(position["hold_state"])
        if (
            hold_state.last_observed_at is not None
            and point["ts"] <= hold_state.last_observed_at
        ):
            return
        observation = self._build_observation(position, point)
        decision = self.exit_engine.evaluate(hold_state, observation)
        position["hold_state"] = hold_state.to_dict()
        if decision.should_sell:
            self._start_sell(position, now, decision.reason, point)

    def _start_sell(
        self,
        position: Dict[str, Any],
        now: datetime,
        reason: str,
        point: Optional[Mapping[str, Any]],
    ) -> None:
        if int(position.get("sell_retries") or 0) >= self.config.max_sell_retries:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = "SELL_RETRY_EXHAUSTED_MANUAL_CHECK"
            self._event("SELL_RETRY_EXHAUSTED", code=position["code"],
                        name=position["name"], reason=reason)
            return
        price = number((point or {}).get("price"), number(position.get("last_price")))
        if not position.get("real"):
            self._confirm_exit(position, price, reason, shadow=True)
            return
        holdings = self.broker.holdings()
        if holdings is None:
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_WAIT", code=position["code"], name=position["name"],
                        reason=f"BALANCE_UNAVAILABLE:{self.broker.last_error}")
            return
        actual = holdings.get(position["code"]) or {}
        actual_qty = int(actual.get("qty") or 0)
        available = int(actual.get("available") or 0)
        if actual_qty <= 0:
            self._confirm_exit(position, price, "BROKER_ALREADY_FLAT")
            return
        quantity = min(int(position.get("qty") or 0), available or actual_qty)
        if quantity <= 0:
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_WAIT", code=position["code"], name=position["name"],
                        reason="BROKER_AVAILABLE_QTY_ZERO")
            return
        known_orders = self._known_orders(position["code"], "매도")
        if known_orders is None:
            position["retry_after_epoch"] = time.time() + 5
            return
        retry = int(position.get("sell_retries") or 0) + 1
        key = (
            f"{self.config.strategy_slug}:"
            f"{self.state['date']}:sell:{position['code']}:{retry}"
        )
        position["sell_retries"] = retry
        position["phase"] = "SELL_PENDING"
        position["pending"] = {
            "side": "SELL",
            "idempotency_key": key,
            "known_orders": known_orders,
            "order_no": "",
            "requested_qty": quantity,
            "pre_hold_qty": actual_qty,
            "since_hms": now.strftime("%H:%M:%S"),
            "sent_epoch": time.time(),
            "cancel_requested": False,
            "cancel_epoch": 0.0,
            "last_status": "PREPARED",
            "reason": reason,
        }
        self._save()
        status = self.broker.submit(
            side="SELL", code=position["code"], quantity=quantity,
            idempotency_key=key)
        position["pending"]["last_status"] = status
        if status in {"OK", "TIMEOUT", "UNKNOWN"}:
            self._event(
                "SELL_PENDING", code=position["code"], name=position["name"],
                price=price, quantity=quantity,
                reason=f"{reason} / {status} exact fill reconciliation",
            )
        elif status == "SHADOW":
            self._confirm_exit(position, price, reason, shadow=True)
        else:
            position["phase"] = "HOLD"
            position["pending"] = None
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_REJECTED", code=position["code"],
                        name=position["name"], quantity=quantity,
                        reason=f"{status}:{self.broker.last_error}")

    def _sell_pending_step(self, position: Dict[str, Any], now: datetime) -> None:
        pending = position["pending"]
        code = position["code"]
        order_no, fills, open_orders = self._discover_order(position, side="매도")
        if position["phase"] == "RECOVERY_BLOCKED":
            return
        filled, average = fills.get(order_no, (0, 0.0)) if order_no else (0, 0.0)
        needed = int(pending["requested_qty"])
        if filled >= needed:
            self._confirm_exit(position, average, pending["reason"])
            return
        if pending.get("cancel_requested"):
            if time.time() - number(pending.get("cancel_epoch")) < 2:
                return
            if open_orders is None or (order_no and order_no in open_orders):
                return
            holdings = self.broker.holdings()
            if holdings is None:
                return
            actual_qty = int((holdings.get(code) or {}).get("qty") or 0)
            if actual_qty <= max(0, int(pending["pre_hold_qty"]) - needed):
                self._confirm_exit(
                    position,
                    average or number(position.get("last_price")),
                    pending["reason"],
                )
            elif actual_qty < int(pending["pre_hold_qty"]):
                position["qty"] = min(int(position["qty"]), actual_qty)
                position["phase"] = "HOLD"
                position["pending"] = None
                position["retry_after_epoch"] = time.time() + 2
                self._event("SELL_PARTIAL", code=code, name=position["name"],
                            quantity=filled, reason=f"remaining={actual_qty}")
            else:
                position["phase"] = "HOLD"
                position["pending"] = None
                position["retry_after_epoch"] = time.time() + 5
                self._event("SELL_FILL_ZERO", code=code, name=position["name"],
                            reason="cancel confirmed and balance unchanged")
            return
        elapsed = time.time() - number(pending.get("sent_epoch"))
        if elapsed < self.config.fill_wait_sec and filled == 0:
            return
        if order_no:
            remaining = (
                (open_orders or {}).get(order_no)
                or max(1, needed - filled)
            )
            pending["cancel_requested"] = True
            pending["cancel_epoch"] = time.time()
            self._save()
            status = self.broker.cancel(
                code=code, order_no=order_no, remaining=remaining, buy=False,
                idempotency_key=(
                    f"{self.config.strategy_slug}:"
                    f"{self.state['date']}:cancel-sell:{order_no}"
                ))
            self._event("SELL_CANCEL_PENDING", code=code,
                        name=position["name"], quantity=remaining,
                        order_no=order_no, reason=status)
            return
        holdings = self.broker.holdings()
        if open_orders is None or holdings is None:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = "SELL_RESULT_UNKNOWN_BROKER_TRUTH_UNAVAILABLE"
            self._event("RECOVERY_BLOCKED", code=code,
                        reason=self.state["last_error"])
            return
        actual_qty = int((holdings.get(code) or {}).get("qty") or 0)
        if actual_qty < int(pending["pre_hold_qty"]):
            if actual_qty <= max(0, int(pending["pre_hold_qty"]) - needed):
                self._confirm_exit(
                    position, number(position.get("last_price")), pending["reason"])
            else:
                position["qty"] = min(int(position["qty"]), actual_qty)
                position["phase"] = "HOLD"
                position["pending"] = None
            return
        candidates = set(open_orders) - set(pending.get("known_orders") or [])
        if candidates:
            return
        position["phase"] = "HOLD"
        position["pending"] = None
        position["retry_after_epoch"] = time.time() + 5
        self._event("SELL_NOT_CREATED", code=code, name=position["name"],
                    reason="fills/open orders/balance unchanged")

    def _confirm_exit(
        self,
        position: Dict[str, Any],
        fill_price: float,
        reason: str,
        *,
        shadow: bool = False,
    ) -> None:
        entry = Decimal(str(number(position.get("entry_price"))))
        exit_price = Decimal(str(number(fill_price, number(position.get("last_price")))))
        exit_at = kst_now()
        self._update_excursion(position, float(exit_price), exit_at)
        gross = (
            (exit_price / entry - Decimal("1")) * Decimal("100")
            if entry > 0 and exit_price > 0 else Decimal("0")
        )
        net = (
            (
                exit_price * (Decimal("1") - SELL_FEE - SELL_TAX)
                / (entry * (Decimal("1") + BUY_FEE))
                - Decimal("1")
            ) * Decimal("100")
            if entry > 0 and exit_price > 0 else Decimal("0")
        )
        code = str(position.get("code") or "").zfill(6)
        self._release_slot(position)
        cycles = self.state.setdefault("cycles_by_code", {})
        cycles[code] = int(cycles.get(code) or 0) + 1
        position.update({
            "phase": "CLOSED",
            "qty": 0,
            "pending": None,
            "slot_reserved": False,
            "exit_price": float(exit_price),
            "exit_at": exit_at.isoformat(timespec="seconds"),
            "post_exit_audit": {"targets": {}},
            "exit_reason": reason,
            "completed_cycle": cycles[code],
            "gross_return_pct": float(gross),
            "estimated_net_return_pct_before_slippage": float(net),
        })
        self._refresh_recovery_blocked()
        self._event(
            "SHADOW_SELL" if shadow else "SELL_CONFIRMED",
            code=position["code"], name=position["name"],
            price=float(exit_price), reason=(
                f"{reason} cycle={cycles[code]}/{self.config.max_cycles_per_code} "
                f"gross={gross:.3f}% net_before_slippage={net:.3f}%"
                f" mfe={number(position.get('mfe_pct')):.3f}% mae={number(position.get('mae_pct')):.3f}%"
                f" rank={int(position.get('candidate_rank_at_entry') or 0)}/{int(position.get('candidate_count_at_entry') or 0)}"
            ))
    def _reconcile_blocked(self, position: Dict[str, Any], now: datetime) -> None:
        code = str(position.get("code") or "").zfill(6)
        last = self._last_reconcile_epoch.get(code, 0.0)
        if time.time() - last < 10:
            return
        self._last_reconcile_epoch[code] = time.time()
        if not position.get("real"):
            return
        holdings = self.broker.holdings()
        if holdings is None:
            return
        actual = holdings.get(code) or {}
        actual_qty = int(actual.get("qty") or 0)
        pending = position.get("pending") or {}
        if actual_qty > 0:
            if position.get("hold_state"):
                position["qty"] = min(
                    int(position.get("qty") or actual_qty), actual_qty)
                position["phase"] = "HOLD"
                self._event("RECOVERY_HOLD_RESUMED", code=code)
            elif pending.get("side") == "BUY":
                self._confirm_entry(
                    position,
                    min(int(pending.get("requested_qty") or 1), actual_qty),
                    number(actual.get("buy_price")) or number(position.get("last_price")),
                    now,
                )
                self._event("RECOVERY_BUY_CONFIRMED", code=code)
            self._refresh_recovery_blocked()
            return
        open_buy = self.broker.open_orders(code, buy=True)
        open_sell = self.broker.open_orders(code, buy=False)
        if open_buy == {} and open_sell == {}:
            if pending.get("side") == "SELL" or position.get("hold_state"):
                self._confirm_exit(
                    position,
                    number(position.get("last_price")),
                    "RECOVERY_FLAT_CONFIRMED",
                )
            else:
                position["phase"] = "FAILED"
                position["qty"] = 0
                self._release_slot(position)
                position["slot_reserved"] = False
                self._event("RECOVERY_BUY_NOT_CREATED", code=code)
            self._refresh_recovery_blocked()
            if not self.state["recovery_blocked"]:
                self.state["last_error"] = ""
    def tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = as_kst(now or kst_now())
        for position in list(self._active_positions().values()):
            phase = str(position.get("phase") or "")
            if phase == "BUY_PENDING":
                point = self._snapshot_point(position["code"], now)
                if point:
                    position["last_price"] = point["price"]
                    position["last_ts"] = point["ts"].isoformat()
                self._buy_pending_step(position, now)
            elif phase == "SELL_PENDING":
                self._sell_pending_step(position, now)
            elif phase == "HOLD":
                self._evaluate_exit(position, now)
            elif phase == "RECOVERY_BLOCKED":
                self._reconcile_blocked(position, now)
        self._cleanup_terminal()
        self._update_post_exit_audit(now)
        if self.config.entry_start <= now.time() < self.config.entry_end:
            self._try_entries(now)
        self._cleanup_terminal()
        self._save()
        return self.state

    def run(self, *, once: bool = False) -> int:
        self.log.info(
            "%s start mode=%s qty=%d slots=%d cycles_per_code=%d capital=%d",
            self.config.strategy_label,
            getattr(self.broker, "mode", "UNKNOWN"),
            self.config.quantity,
            self.config.max_slots,
            self.config.max_cycles_per_code,
            self.config.rotation_capital_krw,
        )
        while True:
            now = kst_now()
            self.tick(now)
            active = bool(self._active_positions())
            if once:
                return 0
            if now.weekday() >= 5 and not active:
                return 0
            if now.time() >= self.config.process_end and not active:
                return 0
            time.sleep(max(0.2, self.config.loop_sec))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = Config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 01 is already running.", flush=True)
        return 0
    try:
        return Strategy01Engine(config).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

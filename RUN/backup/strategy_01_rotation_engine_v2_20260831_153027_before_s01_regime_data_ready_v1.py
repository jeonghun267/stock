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
import hashlib
import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import shared_slots
import capital_config
import position_budget
from json_cache_v1 import read_json_cached
# ★[MA3-COMMON 2026-08-03] 상승보유 판정을 3분봉 5/10/20선 + 수급으로 통일. S01~S06 공통.
from ma3_common_v1 import (
    ma3_rows,
    buy_side_alive as ma3_buy_side_alive,
    ma5_broken as ma3_ma5_broken,
    request_missing_history as ma3_request_missing_history,
    rider_permit as ma3_rider_permit,
)
from strategy_01_signal_contract_v2 import select_fresh_signals
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
    strategy_profile_runtime_snapshot,
)
from hold_sell_audit_v1 import (
    HoldSellAuditRecorder,
    PostExitObservationAuditRecorder,
)
from strategy_common_order_v1 import StrategyBroker, fills_by_order
from strategy_common_reentry_gate_v1 import (
    LossReentryGate,
    record_reentry_snapshot,
)
from strategy_open_priority_v1 import OpenPriorityGate


KST = ZoneInfo("Asia/Seoul")
STATE_SCHEMA = "strategy_01_rotation_engine_v2"
ACTIVE_PHASES = {"BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"}
BUY_FEE = Decimal("0.00015")
SELL_FEE = Decimal("0.00015")
SELL_TAX = Decimal("0.0018")
FORCE_EXIT_EXTRA_RETRIES = int(
    os.environ.get("S01_FORCE_EXIT_EXTRA_RETRIES", "5")
)
MAX_SELL_RECOVERY_CYCLES = int(
    os.environ.get("S01_MAX_SELL_RECOVERY_CYCLES", "3")
)
EXHAUSTED_EVENT_COOLDOWN_SEC = 60.0


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


# ★[READ-CACHE 2026-08-05] 읽기 캐시는 공통모듈 json_cache_v1 로 옮겼다.
#   S01~S05(이 코어) · S06 · ma3_common_v1 이 같은 것을 쓴다.
#   ⚠️돌려주는 객체를 공유하므로 순수 읽기 소비처에만 쓴다.
#     여기서는 bars/snapshot/board 3개만 캐시한다. state_path(엔진이 직접 씀)·
#     names_path·signal_path(선별기가 콜백이라 변형 여부 보장 못 함)는 제외.


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A fixed ``state.json.tmp`` lets two overlapping writers clobber the same
    # temporary file.  Use a per-process/per-write name and give short-lived
    # Windows readers (indexer/AV included) enough time to release the target.
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                return True
            except PermissionError:
                if attempt == 19:
                    return False
                time.sleep(0.25)
            except OSError:
                return False
    except OSError:
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def state_save_failure_marker(state_path: Path) -> Path:
    return state_path.with_suffix(state_path.suffix + ".save_failed.flag")


def state_save_failure_markers(state_path: Path) -> tuple[Path, ...]:
    primary = state_save_failure_marker(state_path)
    fallback_dir = Path(
        os.environ.get("STOCK_BOT_RECOVERY_FLAG_DIR")
        or Path(__file__).resolve().parents[1] / "IPC" / "recovery_flags"
    )
    fallback = fallback_dir / (state_path.name + ".save_failed.flag")
    return (primary,) if fallback == primary else (primary, fallback)


def mark_state_save_failure(state_path: Path) -> Optional[Path]:
    payload = f"STATE_SAVE_FAILED {kst_now().isoformat(timespec='seconds')}\n"
    for marker in state_save_failure_markers(state_path):
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(payload, encoding="ascii")
            return marker
        except OSError:
            continue
    return None


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
    audit_root: Path = Path(r"C:\stock_bot\data\audit\hold_sell")
    order_lifecycle_root: Path = Path(
        r"C:\stock_bot\data\audit\s01_order_lifecycle"
    )
    post_exit_observation_sec: float = 60.0
    audit_enabled: bool = (
        os.environ.get("HOLD_SELL_AUDIT_ENABLED", "YES").strip().upper()
        == "YES"
    )
    approval_path: Path = Path(r"C:\stock_bot\config\strategy_01_live_approved.flag")
    off_flag_path: Path = Path(r"C:\stock_bot\config\strategy_01_off.flag")
    manual_buy_block_path: Path = Path(r"C:\stock_bot\config\manual_buy_block.flag")
    lock_path: Path = Path(r"C:\stock_bot\data\strategy_01_rotation_v2.lock")
    live_requested: bool = (
        os.environ.get("S01_LIVE", "NO").strip().upper() == "YES"
    )
    quantity: int = capital_config.get_order_quantity()
    max_slots: int = int(os.environ.get("S01_MAX_SLOTS", "6"))
    rocket_max_slots: int = int(os.environ.get("S01_ROCKET_MAX_SLOTS", "3"))
    pullback_max_slots: int = int(os.environ.get("S01_PULLBACK_MAX_SLOTS", "3"))
    max_daily_codes: int = int(os.environ.get("S01_MAX_DAILY_CODES", "6"))
    max_cycles_per_code: int = int(os.environ.get("S01_MAX_CYCLES_PER_CODE", "2"))
    rotation_capital_krw: int = capital_config.get_limit("daily_total_max")
    max_sell_retries: int = int(os.environ.get("S01_MAX_SELL_RETRIES", "3"))
    signal_max_age_sec: float = float(os.environ.get("S01_SIGNAL_MAX_AGE_SEC", "5"))
    snapshot_max_age_sec: float = float(os.environ.get("S01_SNAPSHOT_MAX_AGE_SEC", "4"))
    board_max_age_sec: float = float(os.environ.get("S01_BOARD_MAX_AGE_SEC", "8"))
    fill_wait_sec: float = float(os.environ.get("S01_FILL_WAIT_SEC", "8"))
    initial_sell_query_budget_sec: float = 0.0
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
    loss_reentry_gate_mode: str = os.environ.get(
        "COMMON_LOSS_REENTRY_GATE_MODE", "SHADOW"
    ).strip().upper()
    reentry_peer_state_paths: tuple[Path, ...] = (
        Path(r"C:\stock_bot\data\strategy_01_rotation_state_v2.json"),
        Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json"),
    )
    reentry_audit_root: Path = Path(r"C:\stock_bot\data\audit\reentry_gate")
    open_priority_mode: str = os.environ.get(
        "S01_S03_OPEN_PRIORITY_MODE", "SHADOW"
    ).strip().upper()
    open_priority_wait_sec: float = float(os.environ.get(
        "S01_S03_OPEN_PRIORITY_WAIT_SEC", "3"
    ))
    open_priority_state_path: Path = Path(
        r"C:\stock_bot\data\open_priority_state_v1.json"
    )

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError(f"{self.strategy_label} quantity must be positive")
        if self.max_slots != 6:
            raise ValueError(f"{self.strategy_label} requires exactly six concurrent slots")
        if self.strategy_id == StrategyId.S01_OPEN_SURGE:
            if self.rocket_max_slots != 3 or self.pullback_max_slots != 3:
                raise ValueError(
                    f"{self.strategy_label} requires ROCKET 3 and PULLBACK 3 slots"
                )
        required_daily_codes = (
            12
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
        if self.post_exit_observation_sec <= 0:
            raise ValueError("post_exit_observation_sec must be positive")
        if self.loss_reentry_gate_mode not in {"OFF", "SHADOW", "LIVE"}:
            raise ValueError("loss_reentry_gate_mode must be OFF, SHADOW, or LIVE")
        if self.open_priority_mode not in {"OFF", "SHADOW", "LIVE"}:
            raise ValueError("open_priority_mode must be OFF, SHADOW, or LIVE")
        if self.open_priority_wait_sec <= 0:
            raise ValueError("open_priority_wait_sec must be positive")
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
        self.loss_reentry_gate = LossReentryGate()
        self.open_priority_gate = OpenPriorityGate(
            self.config.open_priority_state_path,
            wait_sec=self.config.open_priority_wait_sec,
            mode=self.config.open_priority_mode,
        )
        # S01 reads the same exact exit telemetry as S02.
        self._common_exit_micro = defaultdict(lambda: deque(maxlen=80))
        # ★[LEGACY-DAILY-MA 제거 2026-08-05] 여기 있던 self._daily_ma 는 아래에서
        #   지운 _load_daily_ma 전용 캐시였다. 자세한 건 그 자리 주석 참조.
        self.names = self._load_names()
        self.state = self._load_state()
        self.state_save_failure_paths = state_save_failure_markers(
            self.config.state_path)
        self.state_save_failure_path = self.state_save_failure_paths[0]
        # ★[SELL-LOCK 2026-08-04] __init__ 1회 계산 -> 매 판정마다 재계산.
        #   장중에 새로 산 포지션이 보호를 못 받아, 승인 깃발이 깨지면 팔지도 않고
        #   장부에서 지워졌다. 상세는 StrategyBroker.force_exit_only 참조.
        # ★[BUYPENDING-DEADLOCK 2026-08-05 09:13 친구님 지시 "수정해"] BUY_PENDING 제외.
        #   증상: 08/05 09:05~09:09 매수 3건이 전부 BUY_KILL_SWITCH_OR_APPROVAL 로 거부.
        #   원인: 매수하려고 포지션을 BUY_PENDING 으로 올리는 순간 이 lambda 가 True 가
        #   되고, buy_signal = ... and not force_exit_only 이므로 자기 매수를 자기가
        #   거부한다. 거부되면 포지션이 지워져 상태 파일엔 0건으로 보여 추적이 어려웠다.
        #   BUY_PENDING 은 '실보유'가 아니라 '사려는 중'이므로 매도잠김 보호 대상이
        #   아니다. SELL_PENDING·HOLD·RECOVERY_BLOCKED 는 그대로 두어 8/4 수리
        #   (승인 깃발이 장중에 깨져도 유령 삭제 금지)는 유지된다.
        #   ⚠️장중 긴급 수정이라 사전 테스트 없이 들어갔다. 마감 후 테스트 추가할 것.
        #   되돌리기: backup\strategy_01_rotation_engine_v2_20260805_before_buypending_fix.py
        force_exit_only = lambda: (
            os.environ.get("STRATEGY_RECOVERY_EXIT_ONLY", "NO").strip().upper()
            == "YES"
        ) or any(path.exists() for path in self.state_save_failure_paths) or any(
            position.get("real")
            and position.get("phase") in ACTIVE_PHASES
            and position.get("phase") != "BUY_PENDING"
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
        if self.config.audit_enabled:
            common_engine_path = Path(__file__).with_name(
                "strategy_common_hold_sell_v1.py"
            )
            self.exit_engine.audit_recorder = HoldSellAuditRecorder(
                self.config.audit_root,
                common_engine_path,
                runtime_profile=strategy_profile_runtime_snapshot(
                    self.config.strategy_id
                ),
            )
            adapter_module = sys.modules.get(type(self).__module__)
            adapter_path = Path(
                getattr(adapter_module, "__file__", __file__)
            )
            self.post_exit_observation_recorder = PostExitObservationAuditRecorder(
                self.config.audit_root.parent / "post_exit_observation",
                [Path(__file__), adapter_path, common_engine_path],
            )
        else:
            self.post_exit_observation_recorder = None
        self._last_reconcile_epoch: Dict[str, float] = {}
        self._last_data_warning = ""
        self._last_s01_buy_gate_allowed: Optional[bool] = None
        production_files = {
            "engine": Path(__file__).resolve(),
            "signal_contract": RUN_DIR / "strategy_01_signal_contract_v2.py",
            "signal_source": RUN_DIR / "strategy_01_open_surge_signal_v2.py",
            "order_adapter": RUN_DIR / "strategy_common_order_v1.py",
        }
        self._order_lifecycle_prod_sha = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in production_files.items()
            if path.is_file()
        }
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
        missing_real = sorted(
            str(code).zfill(6)
            for code, position in payload["positions"].items()
            if (
                isinstance(position, dict)
                and position.get("phase") in ACTIVE_PHASES
                and "real" not in position
            )
        )
        if missing_real:
            for position in payload["positions"].values():
                if (
                    isinstance(position, dict)
                    and position.get("phase") in ACTIVE_PHASES
                    and "real" not in position
                ):
                    position["phase"] = "RECOVERY_BLOCKED"
            payload["recovery_blocked"] = True
            payload["last_error"] = (
                "POSITION_REAL_FLAG_MISSING_MANUAL_CHECK:"
                + ",".join(missing_real)
            )
        payload["entered_codes"] = entered_codes
        payload.setdefault("history", [])
        return payload
    def _load_names(self) -> Dict[str, str]:
        payload = read_json(self.config.names_path, {})
        raw = payload.get("map", payload) if isinstance(payload, dict) else {}
        return {str(code).zfill(6): str(name) for code, name in raw.items()}

    def _save(self) -> None:
        self.state["heartbeat"] = kst_now().isoformat(timespec="seconds")
        if not write_json_atomic(self.config.state_path, self.state):
            marker = mark_state_save_failure(self.config.state_path)
            if marker is None:
                self.log.critical(
                    "STATE_SAVE_FAILURE_MARKER_UNWRITABLE state=%s markers=%s",
                    self.config.state_path,
                    ",".join(str(path) for path in self.state_save_failure_paths),
                )
            self.log.critical(
                "STATE_SAVE_LOCKED_FAIL_CLOSED path=%s", self.config.state_path)
            raise RuntimeError(
                f"STATE_SAVE_LOCKED_FAIL_CLOSED:{self.config.state_path}")

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
                int(pending.get("pre_hold_qty") or 0)
                + int(pending.get("requested_qty") or self.config.quantity)
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
        ) or any(path.exists() for path in self.state_save_failure_paths)

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
            observation_capture = audit.get("observation_capture") or {}
            recorder = self.post_exit_observation_recorder
            if (
                recorder is not None
                and 0.0 <= elapsed_sec <= self.config.post_exit_observation_sec
                and not observation_capture.get("complete")
            ):
                code = str(position.get("code") or "").zfill(6)
                point = self._snapshot_point(code, now)
                last_observed_at = parse_dt(
                    observation_capture.get("last_observed_at"), exit_at,
                )
                if (
                    point is not None
                    and point.get("board_fresh")
                    and point["ts"] > last_observed_at
                ):
                    observation = self._build_observation(position, point)
                    hold_state = position.get("hold_state") or {}
                    audit_position = {
                        "strategy_id": str(
                            hold_state.get("strategy_id")
                            or self.config.strategy_id.value
                        ),
                        "code": code,
                        "position_id": str(hold_state.get("position_id") or ""),
                        "entry_at": str(position.get("entry_at") or ""),
                        "entry_price": str(position.get("entry_price") or ""),
                    }
                    target = recorder.record(
                        position=audit_position,
                        observation=observation,
                        exit_at=exit_at,
                    )
                    if target is not None:
                        observation_capture.update({
                            "last_observed_at": point["ts"].isoformat(),
                            "path": str(target),
                            "rows": int(observation_capture.get("rows") or 0) + 1,
                            "error": "",
                        })
                    elif recorder.last_error:
                        observation_capture["error"] = recorder.last_error
                audit["observation_capture"] = observation_capture
            elif (
                observation_capture
                and elapsed_sec > self.config.post_exit_observation_sec
            ):
                observation_capture["complete"] = True
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

    def _order_lifecycle(
        self,
        event: str,
        position: Mapping[str, Any],
        *,
        fill_quantity: int = 0,
        fill_price: float = 0.0,
        fill_source: str = "",
        observed_at: Optional[datetime] = None,
    ) -> None:
        pending = position.get("pending") or {}
        captured_at = as_kst(observed_at or kst_now())
        record: Dict[str, Any] = {
            "schema": "s01_order_lifecycle_v1",
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "strategy_id": self.config.strategy_id.value,
            "trade_date": str(self.state.get("date") or ""),
            "event": event,
            "code": str(position.get("code") or "").zfill(6),
            "signal_id": str(position.get("signal_id") or ""),
            "signal_ts": str(position.get("signal_ts") or ""),
            "signal_price": number(position.get("signal_price")),
            "signal_reason": str(position.get("signal_reason") or ""),
            "entry_stage": str(pending.get("entry_stage") or position.get("entry_stage") or ""),
            "signal_snapshot": position.get("signal_snapshot") or {},
            "idempotency_key": str(pending.get("idempotency_key") or ""),
            "order_no": str(pending.get("order_no") or ""),
            "requested_quantity": int(pending.get("requested_qty") or 0),
            "broker_status": str(pending.get("last_status") or ""),
            "fill_quantity": int(fill_quantity),
            "fill_price": number(fill_price),
            "fill_reconciled_at": (
                captured_at.isoformat(timespec="seconds")
                if event == "BUY_FILL_CONFIRMED" else ""
            ),
            "fill_source": fill_source,
            "mode": str(getattr(self.broker, "mode", "UNKNOWN")),
            "production_files": dict(self._order_lifecycle_prod_sha),
        }
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        )
        record["record_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        path = (
            self.config.order_lifecycle_root
            / str(self.state.get("date") or captured_at.strftime("%Y%m%d"))
            / "s01_order_lifecycle.jsonl"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self.log.exception("S01_ORDER_LIFECYCLE_AUDIT_WRITE_FAILED")

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
        if any(path.exists() for path in self.state_save_failure_paths):
            self.state["recovery_blocked"] = True
            self.state["last_error"] = "STATE_SAVE_FAILURE_RECONCILE_REQUIRED"
            if not self.broker.connect():
                self._save()
                return
            holdings = self.broker.holdings()
            if holdings is None:
                self.state["last_error"] = (
                    "STATE_SAVE_FAILURE_BALANCE_UNAVAILABLE:"
                    + self.broker.last_error
                )
                self._save()
                return
            broker_codes = sorted(str(code).zfill(6) for code in holdings)
            if not real_positions:
                if broker_codes:
                    self.state["last_error"] = (
                        "STATE_SAVE_FAILURE_BROKER_REVIEW_REQUIRED:"
                        + ",".join(broker_codes)
                    )
                    self._save()
                    return
                self.state["recovery_blocked"] = False
                self.state["last_error"] = ""
                self._save()
                marker_errors = []
                for marker in self.state_save_failure_paths:
                    try:
                        marker.unlink(missing_ok=True)
                    except OSError as exc:
                        marker_errors.append(f"{marker}:{exc}")
                if marker_errors:
                    self.state["recovery_blocked"] = True
                    self.state["last_error"] = (
                        "STATE_SAVE_FAILURE_MARKER_CLEAR_FAILED:"
                        + "|".join(marker_errors)
                    )
                    self._save()
                return
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
        snapshot = read_json_cached(self.config.snapshot_path, {})
        raw = (snapshot.get("codes") or {}).get(str(code).zfill(6))
        if not isinstance(raw, dict):
            return None
        observed_at = parse_dt(raw.get("ts"), now)
        if abs((now - observed_at).total_seconds()) > self.config.snapshot_max_age_sec:
            return None
        price = abs(number(raw.get("cur")))
        if price <= 0:
            return None
        board_payload = read_json_cached(self.config.board_path, {})
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
            "che_str": max(0.0, number(raw.get("che_str"))),
            "buy_vol_cum": number(raw.get("buy_vol_cum"), -1.0),
            "sell_vol_cum": number(raw.get("sell_vol_cum"), -1.0),
            "money_speed_5s": max(0.0, number(board_row.get("money_speed_5s"))),
            "money_speed_10s": max(0.0, number(board_row.get("money_speed_10s"))),
            "money_speed_30s": max(0.0, number(board_row.get("money_speed_30s"))),
            "board_fresh": board_fresh,
            # ★[DAY-LOW 2026-08-05 친구님 지시 "모든 전략들이 공동으로 사용하게 해줘"]
            #   거래소가 주는 당일 시가/고가/저가를 공용 point 에 그대로 실어 배달한다.
            #   왜 — 전략이 각자 자기가 본 틱으로 저점을 만들면 (ㄱ)구독 전 저점을 못 보고
            #   (ㄴ)엔진 사정으로 리셋된다. 실제로 S02 의 anchor_low 는 새 고점마다
            #   현재가로 리셋돼서, 문턱을 조일수록 "저점 대비 %"는 좋아 보이는데 실제
            #   매수가는 올라갔다(8/5 원익IPS: 계약서 1.439% vs 진짜 3.785%, 착시 2.347%p).
            #   브로커 broker_gateway_v1 이 체결 FID 16/17/18 을 op/hi/lo 로 싣는다.
            #   ⚠️안 실리면 0 이다 — 쓰는 쪽에서 0 검사 필수(0 을 저점으로 쓰면 재앙).
            #   ⚠️지금은 기록·참고용이다. 어떤 매수/매도 판정에도 넣지 않았다.
            "open_price": max(0.0, number(raw.get("op"))),
            "day_high": max(0.0, number(raw.get("hi"))),
            "day_low": max(0.0, number(raw.get("lo"))),
        }

    def _common_exit_micro_rates(
        self,
        code: str,
        point: Mapping[str, Any],
    ) -> Tuple[float, float, float, float, float]:
        """Exact volume/strength rates shared by every common exit adapter."""
        if not hasattr(self, "_common_exit_micro"):
            self._common_exit_micro = defaultdict(lambda: deque(maxlen=80))
        rows = self._common_exit_micro[str(code).zfill(6)]
        current = (
            point["ts"],
            number(point.get("buy_vol_cum"), -1.0),
            number(point.get("sell_vol_cum"), -1.0),
            number(point.get("che_str")),
        )
        if min(current[1], current[2]) < 0 or current[3] <= 0:
            rows.clear()
            return 0.0, 0.0, 0.0, 0.0, 0.0
        if rows and (
            current[0] <= rows[-1][0]
            or current[1] < rows[-1][1]
            or current[2] < rows[-1][2]
        ):
            rows.clear()
        rows.append(current)
        while rows and (current[0] - rows[0][0]).total_seconds() > 20:
            rows.popleft()

        def at_or_before(target: datetime):
            for item in reversed(rows):
                if item[0] <= target:
                    return item
            return None

        recent_target = current[0] - timedelta(seconds=5)
        previous_target = current[0] - timedelta(seconds=15)
        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        if recent_start is None or previous_start is None:
            return 0.0, 0.0, 0.0, current[3], 0.0
        if (
            (recent_target - recent_start[0]).total_seconds() > 2
            or (previous_target - previous_start[0]).total_seconds() > 3
        ):
            return 0.0, 0.0, 0.0, current[3], 0.0
        recent_span = (current[0] - recent_start[0]).total_seconds()
        previous_span = (recent_start[0] - previous_start[0]).total_seconds()
        deltas = (
            current[1] - recent_start[1],
            current[2] - recent_start[2],
            recent_start[2] - previous_start[2],
        )
        if recent_span <= 0 or previous_span <= 0 or min(deltas) < 0:
            return 0.0, 0.0, 0.0, current[3], 0.0
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / previous_span,
            current[3],
            current[3] - recent_start[3],
        )

    def _known_orders(
        self,
        code: str,
        side: str,
        *,
        timeout_sec: Optional[float] = None,
        attempts: Optional[int] = None,
    ) -> Optional[list[str]]:
        known = set(fills_by_order(
            self.config.fills_dir, code, side, day=str(self.state["date"])))
        query_kwargs: Dict[str, Any] = {}
        if timeout_sec is not None:
            query_kwargs["timeout_sec"] = timeout_sec
        if attempts is not None:
            query_kwargs["attempts"] = attempts
        open_orders = self.broker.open_orders(
            code, buy=(side == "매수"), **query_kwargs)
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
            if str(pending.get("side") or "") == "BUY":
                self._order_lifecycle("ORDER_NUMBER_CONFIRMED", position)
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

    def _try_staged_add(
        self,
        position: Dict[str, Any],
        signal: Mapping[str, Any],
        now: datetime,
        candidate_rank: int,
        candidate_count: int,
    ) -> bool:
        if str(signal.get("entry_stage") or "") != "STRONG_FLOW":
            return False
        code = str(position.get("code") or "").zfill(6)
        name = str(position.get("name") or code)
        signal_id = str(signal["signal_id"])
        if position.get("phase") != "HOLD":
            self._event(
                "BUY_WAIT", code=code, name=name,
                reason="STAGED_ADD_WAITS_FOR_FIRST_FILL",
            )
            return True

        target_qty = min(2, int(self.config.quantity))
        stages = set(position.get("entry_stages") or [])
        if int(position.get("qty") or 0) >= target_qty or "STRONG_FLOW" in stages:
            self.state.setdefault("consumed_signals", []).append(signal_id)
            self._event(
                "BUY_BLOCKED", code=code, name=name,
                reason="STAGED_TARGET_ALREADY_FILLED",
            )
            return True

        point = self._snapshot_point(code, now)
        if point is None:
            return True
        required = int(Decimal(str(point["price"])))
        if self._active_capital_krw() + required > self.config.rotation_capital_krw:
            self._event(
                "BUY_WAIT", code=code, name=name,
                price=point["price"], quantity=1,
                reason="STAGED_ADD_CAPITAL_WAIT",
            )
            return True

        known_orders: list[str] = []
        if getattr(self.broker, "real_session", False):
            if not getattr(self.broker, "buy_allowed", False):
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="APPROVAL_OR_OFF_FLAG",
                )
                return True
            holdings = self.broker.holdings()
            if holdings is None:
                self._event(
                    "BUY_WAIT", code=code, name=name,
                    reason="STAGED_ADD_BALANCE_UNAVAILABLE",
                )
                return True
            actual_qty = int((holdings.get(code) or {}).get("qty") or 0)
            if actual_qty != int(position.get("qty") or 0):
                self._event(
                    "BUY_WAIT", code=code, name=name,
                    reason="STAGED_ADD_BALANCE_MISMATCH",
                )
                return True
            open_buy = self.broker.open_orders(code, buy=True)
            if open_buy is None or open_buy:
                self._event(
                    "BUY_WAIT", code=code, name=name,
                    reason="STAGED_ADD_OPEN_BUY_EXISTS_OR_UNKNOWN",
                )
                return True
            known = self._known_orders(code, "매수")
            if known is None:
                self._event(
                    "BUY_WAIT", code=code, name=name,
                    reason="STAGED_ADD_ORDER_HISTORY_UNAVAILABLE",
                )
                return True
            known_orders = known

        attempt = int(self.state.get("order_attempts_total") or 0) + 1
        order_key = (
            f"{self.config.strategy_slug}:"
            f"{self.state['date']}:buy-add:{code}:{attempt}"
        )
        pending = {
            "side": "BUY",
            "idempotency_key": order_key,
            "known_orders": known_orders,
            "order_no": "",
            "requested_qty": 1,
            "pre_hold_qty": int(position.get("qty") or 0),
            "entry_stage": "STRONG_FLOW",
            "since_hms": now.strftime("%H:%M:%S"),
            "sent_epoch": time.time(),
            "cancel_requested": False,
            "cancel_epoch": 0.0,
            "last_status": "PREPARED",
            "reason": str(signal.get("reason") or "STRONG_FLOW_CONFIRMED"),
        }
        position.update({
            "phase": "BUY_PENDING",
            "pending": pending,
            "last_price": point["price"],
            "last_ts": point["ts"].isoformat(),
            "signal_id": signal_id,
            "signal_ts": str(signal.get("ts") or ""),
            "signal_price": number(point["price"]),
            "signal_reason": str(signal.get("reason") or ""),
            "signal_snapshot": dict(signal),
            "candidate_rank_at_entry": candidate_rank,
            "candidate_count_at_entry": candidate_count,
        })
        self.state.setdefault("consumed_signals", []).append(signal_id)
        self.state["order_attempts_total"] = attempt
        self._save()
        self._order_lifecycle("BUY_PREPARED", position)
        status = self.broker.submit(
            side="BUY", code=code, quantity=1, idempotency_key=order_key,
        )
        pending["last_status"] = status
        self._order_lifecycle("BUY_SUBMIT_RESULT", position)
        if status == "SHADOW":
            self._confirm_entry(position, 1, point["price"], now, shadow=True)
        elif status == "OK":
            self._event(
                "BUY_ADD_PENDING", code=code, name=name,
                price=point["price"], quantity=1,
                reason="OK: exact fill reconciliation",
            )
        elif status in {"TIMEOUT", "UNKNOWN"}:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = f"BUY_ADD_{status}_BROKER_TRUTH_REQUIRED"
            self._event(
                "RECOVERY_BLOCKED", code=code, name=name,
                reason=self.state["last_error"],
            )
        else:
            self._fail_or_restore_buy(position, "BUY_ADD_REJECTED")
        self._save()
        return True

    def _try_entries(self, now: datetime) -> None:
        if self.state.get("recovery_blocked"):
            return
        # S01~S03 start before the all-strategy preflight so opening signals
        # are not lost to process startup. Do not even select/consume a signal
        # until StrategyBroker confirms that the existing approval/off gate
        # has actually enabled buys. Hold/sell recovery runs earlier in tick().
        gate_controlled = (
            self.config.strategy_id == StrategyId.S01_OPEN_SURGE
            or (
                bool(getattr(self.broker, "live_requested", False))
                and self.config.strategy_id in {
                    StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
                    StrategyId.VALLEY_MORNING_CRASH,
                }
            )
        )
        if gate_controlled:
            buy_gate_allowed = self.broker.buy_allowed
            if not buy_gate_allowed:
                if self._last_s01_buy_gate_allowed is not False:
                    self.log.critical(
                        "%s_BUY_GATE_CLOSED standby; no signal consumed",
                        self.config.strategy_id.value,
                    )
                    self._event(
                        "BUY_GATE_CLOSED",
                        reason="APPROVAL_OR_SAFETY_GATE",
                    )
                self._last_s01_buy_gate_allowed = False
                return
            if self._last_s01_buy_gate_allowed is False:
                self.log.info(
                    "%s_BUY_GATE_OPEN entries enabled",
                    self.config.strategy_id.value,
                )
                self._event("BUY_GATE_OPEN", reason="PREFLIGHT_APPROVED")
            self._last_s01_buy_gate_allowed = True
        payload = read_json(self.config.signal_path, {})
        rows = self.signal_selector(
            payload,
            now=now,
            max_age_sec=self.config.signal_max_age_sec,
            consumed=self.state.get("consumed_signals") or [],
        )
        priority = self.open_priority_gate.evaluate(
            strategy_id=self.config.strategy_id.value,
            rows=rows,
            now=now,
        )
        if priority.applies:
            top = rows[0] if rows else {}
            self._event(
                "OPEN_PRIORITY_WAIT" if priority.waiting else "OPEN_PRIORITY_SELECT",
                code=str(top.get("code") or "").zfill(6),
                name=str(top.get("name") or ""),
                reason=(
                    f"{priority.reason} mode={self.config.open_priority_mode} "
                    f"elapsed={priority.elapsed_sec:.2f}s "
                    f"s03_seen={priority.s03_priority_seen}"
                ),
            )
            rows = list(priority.rows)
        candidate_count = len(rows)
        bars_payload = read_json_cached(self.config.bars_path, {})
        for candidate_rank, signal in enumerate(rows, start=1):
            code = str(signal["code"]).zfill(6)
            signal_id = str(signal["signal_id"])
            name = str(signal.get("name") or self.names.get(code) or code)
            active = self._active_positions().get(code)
            if active is not None:
                if self._try_staged_add(
                    active, signal, now, candidate_rank, candidate_count,
                ):
                    continue
                self._event(
                    "BUY_BLOCKED", code=code, name=name,
                    reason="CODE_ALREADY_ACTIVE",
                )
                continue
            entry_stage = str(signal.get("entry_stage") or "")
            active_positions = self._active_positions()
            if len(active_positions) >= self.config.max_slots:
                return
            lane_limits = {
                "ROCKET": self.config.rocket_max_slots,
                "PULLBACK": self.config.pullback_max_slots,
            }
            if entry_stage in lane_limits:
                lane_active = sum(
                    1 for position in active_positions.values()
                    if str(position.get("entry_stage") or "") == entry_stage
                )
                if lane_active >= lane_limits[entry_stage]:
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason=f"{entry_stage}_SLOT_LIMIT_3",
                    )
                    continue
            order_qty = (
                1 if entry_stage in {
                    "EARLY_FLOW", "STRONG_FLOW", "ROCKET", "PULLBACK"
                }
                else int(self.config.quantity)
            )
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
            if (
                self.config.loss_reentry_gate_mode != "OFF"
                and self.config.strategy_id in {
                    StrategyId.S01_OPEN_SURGE,
                    StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
                }
            ):
                peer_states = [self.state]
                for peer_path in self.config.reentry_peer_state_paths:
                    if Path(peer_path) == self.config.state_path:
                        continue
                    peer = read_json(Path(peer_path), {})
                    if isinstance(peer, dict):
                        peer_states.append(peer)
                reentry = self.loss_reentry_gate.evaluate(
                    strategy_id=self.config.strategy_id.value,
                    code=code,
                    signal=signal,
                    current_price=point["price"],
                    states=peer_states,
                    bars_payload=bars_payload,
                )
                if reentry.applies:
                    audit_path = record_reentry_snapshot(
                        root=self.config.reentry_audit_root,
                        strategy_id=self.config.strategy_id.value,
                        code=code,
                        signal=signal,
                        current_price=point["price"],
                        states=peer_states,
                        bars_payload=bars_payload,
                        decision=reentry,
                        mode=self.config.loss_reentry_gate_mode,
                        engine_paths=(Path(__file__), Path(
                            sys.modules[type(self).__module__].__file__
                        )),
                    )
                    self._event(
                        "REENTRY_GATE_PASS" if reentry.allowed else "REENTRY_GATE_WAIT",
                        code=code,
                        name=name,
                        price=point["price"],
                        reason=(
                            f"{reentry.reason} mode={self.config.loss_reentry_gate_mode} "
                            f"stable={reentry.stable_bars}/3 "
                            f"atr10={reentry.atr10:.2f} low={reentry.post_exit_low:.2f} "
                            f"buy_confirm={reentry.buy_confirmations}/3"
                            f" audit={audit_path or 'WRITE_FAILED'}"
                        ),
                    )
                    if (
                        self.config.loss_reentry_gate_mode == "LIVE"
                        and (not reentry.allowed or audit_path is None)
                    ):
                        continue
            required = int(
                Decimal(str(point["price"])) * order_qty)
            if not position_budget.can_open_krw(required):
                self._event(
                    "BUY_WAIT", code=code, name=name, price=point["price"],
                    quantity=order_qty, reason="COMMON_CAPITAL_WAIT",
                )
                continue
            if self._active_capital_krw() + required > self.config.rotation_capital_krw:
                self._event(
                    "BUY_WAIT", code=code, name=name, price=point["price"],
                    quantity=order_qty,
                    reason=(
                        f"ROTATION_CAPITAL_WAIT "
                        f"{self._active_capital_krw()}+{required}>"
                        f"{self.config.rotation_capital_krw}"
                    ),
                )
                continue

            if getattr(self.broker, "real_session", False):
                s01_entry_ma_not_required = (
                    self.config.strategy_id == StrategyId.S01_OPEN_SURGE
                    and entry_stage in {"ROCKET", "PULLBACK"}
                )
                if (
                    not s01_entry_ma_not_required
                    and ma3_rows(code, bars_payload) is None
                ):
                    ma3_request_missing_history(
                        code, f"{self.config.strategy_id.value}:ENTRY",
                    )
                    self.state["last_error"] = f"MA3_SEED_NOT_READY:{code}"
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason="MA3_SEED_NOT_READY",
                    )
                    self._save()
                    continue
                if not getattr(self.broker, "buy_allowed", False):
                    self._event(
                        "BUY_BLOCKED", code=code, name=name,
                        reason="APPROVAL_OR_OFF_FLAG",
                    )
                    self._save()
                    return
                fast_prebuy_truth = self.config.strategy_id in {
                    StrategyId.S01_OPEN_SURGE,
                    StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
                    StrategyId.VALLEY_MORNING_CRASH,
                }
                holdings_reader = (
                    getattr(
                        self.broker,
                        "prebuy_holdings",
                        self.broker.holdings,
                    )
                    if fast_prebuy_truth
                    else self.broker.holdings
                )
                holdings = holdings_reader()
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
                open_orders_reader = (
                    getattr(
                        self.broker,
                        "prebuy_open_orders",
                        self.broker.open_orders,
                    )
                    if fast_prebuy_truth
                    else self.broker.open_orders
                )
                open_buy = open_orders_reader(code, buy=True)
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
                audit_acquire = getattr(self.slots, "acquire_with_audit", None)
                acquired = (
                    audit_acquire(code, self.config.slot_owner, self.state["date"],
                                  buy_ready_ts=str(signal.get("ts") or ""))
                    if audit_acquire is not None
                    else self.slots.acquire(code, self.config.slot_owner, self.state["date"])
                )
                if not acquired:
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
                "requested_qty": order_qty,
                "pre_hold_qty": 0,
                "entry_stage": entry_stage,
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
                "signal_ts": str(signal.get("ts") or ""),
                "signal_price": number(point["price"]),
                "signal_reason": str(signal.get("reason") or ""),
                "signal_snapshot": dict(signal),
                "entry_lane": str(signal.get("entry_lane") or ""),
                "signal_sequence": int(signal.get("signal_sequence") or 0),
                "entry_stage": entry_stage,
                "entry_stages": [],
                "pullback_reference_low": (
                    number(signal.get("reference_low"))
                    if entry_stage == "PULLBACK" else 0.0
                ),
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
            self._order_lifecycle("BUY_PREPARED", position)
            status = self.broker.submit(
                side="BUY",
                code=code,
                quantity=order_qty,
                idempotency_key=order_key,
            )
            pending["last_status"] = status
            self._order_lifecycle("BUY_SUBMIT_RESULT", position)
            if status == "SHADOW":
                self._confirm_entry(
                    position, order_qty, point["price"], now, shadow=True)
            elif status == "OK":
                self._event(
                    "BUY_PENDING", code=code, name=name,
                    price=point["price"], quantity=order_qty,
                    reason="OK: exact fill reconciliation",
                )
            elif status in {"TIMEOUT", "UNKNOWN"}:
                position["phase"] = "RECOVERY_BLOCKED"
                self.state["recovery_blocked"] = True
                self.state["last_error"] = f"BUY_{status}_BROKER_TRUTH_REQUIRED"
                self._event(
                    "RECOVERY_BLOCKED", code=code, name=name,
                    price=point["price"], quantity=order_qty,
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
                    price=point["price"], quantity=order_qty,
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
        pending = position.get("pending") or {}
        pre_hold_qty = int(pending.get("pre_hold_qty") or 0)
        entry_stage = str(
            pending.get("entry_stage") or position.get("entry_stage") or "")
        fill_source = (
            "ORDER_ZERO" if shadow
            else (
                "BROKER_FILL_JOURNAL"
                if str(pending.get("order_no") or "")
                else "BROKER_BALANCE_RECONCILE"
            )
        )
        self._order_lifecycle(
            "BUY_FILL_CONFIRMED",
            position,
            fill_quantity=quantity,
            fill_price=fill_price,
            fill_source=fill_source,
            observed_at=observed_at,
        )
        if pre_hold_qty > 0 and position.get("hold_state"):
            old_price = number(position.get("entry_price"))
            total_qty = pre_hold_qty + int(quantity)
            average_price = (
                old_price * pre_hold_qty + fill_price * int(quantity)
            ) / total_qty
            hold_state = HoldSellState.from_dict(position["hold_state"])
            hold_state.quantity = total_qty
            hold_state.entry_price = Decimal(str(average_price))
            hold_state.peak_price = max(
                hold_state.peak_price, Decimal(str(average_price)))
            stages = list(position.get("entry_stages") or [])
            if entry_stage and entry_stage not in stages:
                stages.append(entry_stage)
            position.update({
                "phase": "HOLD",
                "qty": total_qty,
                "entry_price": average_price,
                "hold_state": hold_state.to_dict(),
                "entry_stages": stages,
                "pending": None,
                "real": not shadow,
                "reserved_capital_krw": int(average_price * total_qty),
            })
            self._update_excursion(position, fill_price, observed_at)
            self._refresh_recovery_blocked()
            self._event(
                "SHADOW_BUY_ADD" if shadow else "BUY_ADD_CONFIRMED",
                code=position["code"], name=position["name"],
                price=fill_price, quantity=quantity,
                reason=f"{entry_stage or 'STAGED_ADD'} total_qty={total_qty}",
            )
            return
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
        stages = list(position.get("entry_stages") or [])
        if entry_stage and entry_stage not in stages:
            stages.append(entry_stage)
        position["entry_stages"] = stages
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

    def _fail_or_restore_buy(
        self, position: Dict[str, Any], event: str,
    ) -> None:
        pending = position.get("pending") or {}
        pre_hold_qty = int(pending.get("pre_hold_qty") or 0)
        if pre_hold_qty > 0 and position.get("hold_state"):
            position["phase"] = "HOLD"
            position["qty"] = pre_hold_qty
            position["pending"] = None
            self._event(
                event, code=position["code"], name=position["name"],
                reason="existing position preserved",
            )
            return
        position["phase"] = "FAILED"
        self._release_slot(position)
        position["slot_reserved"] = False
        position["pending"] = None
        self._event(
            event, code=position["code"], name=position["name"],
            reason="initial buy not created",
        )

    @staticmethod
    def _balance_fill_price(
        position: Dict[str, Any], actual_qty: int, balance_average: float,
    ) -> float:
        pending = position.get("pending") or {}
        pre_qty = int(pending.get("pre_hold_qty") or 0)
        added = actual_qty - pre_qty
        if pre_qty <= 0 or added <= 0 or balance_average <= 0:
            return balance_average
        old_price = number(position.get("entry_price"))
        incremental = (
            balance_average * actual_qty - old_price * pre_qty
        ) / added
        return incremental if incremental > 0 else balance_average

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
                actual_qty = int(actual["qty"])
                pre_qty = int(pending.get("pre_hold_qty") or 0)
                balance_average = number(actual.get("buy_price"))
                self._confirm_entry(
                    position,
                    min(needed, actual_qty - pre_qty),
                    self._balance_fill_price(
                        position, actual_qty, balance_average,
                    ) or number(position["last_price"]),
                    now,
                )
            else:
                self._fail_or_restore_buy(position, "BUY_FILL_ZERO")
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
            actual_qty = int(actual["qty"])
            pre_qty = int(pending.get("pre_hold_qty") or 0)
            balance_average = number(actual.get("buy_price"))
            self._confirm_entry(
                position,
                min(needed, actual_qty - pre_qty),
                self._balance_fill_price(
                    position, actual_qty, balance_average,
                ) or number(position["last_price"]),
                now,
            )
            return
        candidates = set(open_orders) - set(pending.get("known_orders") or [])
        if candidates:
            return
        self._fail_or_restore_buy(position, "BUY_NOT_CREATED")

    # ★[LEGACY-DAILY-MA 제거 2026-08-05 친구님 지시 "그것도 지워"] 여기 있던
    #   _load_daily_ma(일봉 종가 -> 5/10/20선 캐시)와 __init__ 의 self._daily_ma 를
    #   지웠다. 8/3 에 상승보유를 일봉->3분봉(ma3_common_v1)으로 전면 교체한 뒤로
    #   이 로더를 부르는 곳이 아무 데도 없었다(같은 날 S02 쪽 사본과 그 유일한
    #   소비자 _daily_ma_permit_legacy 도 함께 제거).
    #   ⚠️되살리지 말 것 — 일봉 5일선은 장중에 안 움직이는 고정값이라 하루 안에
    #     깨질 수가 없다. 8/3 실측: 에스피지 손절가가 일봉 5일선보다 +38.2% 위 ->
    #     상승보유 100% 참 -> 매도 판정이 478번 중 124번 통째로 막혔다.
    #   상승보유 판정은 아래 _daily_ma_permit(3분봉) 하나뿐이다.
    #   ⚠️config.eod_bars_path 와 csv 임포트는 지우지 않았다 — 각각 S03/S06 의
    #     자체 로더와 이벤트 CSV 기록이 여전히 쓴다.
    #   되돌리기: backup\strategy_01_rotation_engine_v2_20260805_before_legacy_removal.py

    def _recent_3min_high(self, code: str) -> float:
        """완성 1분봉 3개(=3분봉 1개)의 고가. 자료가 없으면 0."""
        payload = read_json_cached(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        previous = ((source or {}).get(code) or {}).get("prev") or []
        highs = [
            number(bar[1]) for bar in previous[-3:]
            if len(bar) >= 2 and number(bar[1]) > 0
        ]
        return max(highs) if len(highs) == 3 else 0.0

    def _daily_ma_permit(
        self,
        code: str,
        price: float,
        buy_side: Optional[bool] = None,
    ) -> bool:
        """상승보유 허가 — 전 전략 공통. ma3_common_v1 이 유일한 기준이다.

        ★[MA3-COMMON 2026-08-03 친구님 지시] 종전에는 '일봉' 5/10/20선을 썼다.
          일봉 5일선은 장중에 안 움직이는 고정값이라 하루 안에 깨질 수가 없다
          (8/3 실측: 에스피지 손절가가 일봉 5일선보다 +38.2% 위 → 상승보유가
          100% 참 → 트레일 매도가 478번 판정 중 124번 통째로 막힘. 엔젤로보틱스는
          고점 대비 -6.06% 를 방치하고 손절). 친구님이 말한 5/10/20선은 '3분봉'의
          선이었고, 이름만 같은 다른 물건이 들어가 있었다.
          지금은 3분봉 5/10/20선(선 지지) + 매수세 우위, 2단 판정으로 통일한다.
          되돌리기: backup\\strategy_01_rotation_engine_v2_20260803_ma3wire.py
        """
        # ★[MA20-PHASE 2026-08-05 친구님 지시 "남은 어긋남 지금 해결 해"]
        #   같은 날 지시가 둘이었고 서로 어긋나 있었다.
        #     (가) "지금 켜" — S01 만 20선 단계를 상승보유에 다시 넣어라.
        #     (나) "이 해제는 매도(꼭지) 상황에서만이지 손실방어 국면엔 적용 안 한다."
        #   (가)대로 하면 S01 은 꼭지 국면에서도 20선으로 버텨 이익을 반납한다.
        #   (나)가 나중 지시이자 더 좁은 규칙이라 (나)로 통일한다 —
        #     꼭지 국면: 20선만 걸친 상태는 보유 안 줌(= 팔 수 있다)
        #     손실방어 국면: 20선이 받쳐주면 보유(_build_observation 의
        #                    ma20_defense_permit 이 담당한다)
        #   그래서 여기(꼭지용 daily_ma_permit)는 allow_ma20 을 붙이지 않는다.
        #   이제 S01·S02·S05 가 같은 규칙이다.
        #   되돌리기: allow_ma20=True 를 다시 붙이면 8/5 (가) 상태로 간다.
        #   백업: backup\strategy_01_rotation_engine_v2_20260805_before_s01_ma20_phase.py
        return ma3_rider_permit(code, price, buy_side=buy_side)

    def _completed_structure_low(self, code: str) -> float:
        payload = read_json_cached(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        row = (source or {}).get(code) or {}
        previous = row.get("prev") or []
        lows = [
            number(bar[2]) for bar in previous[-3:]
            if len(bar) >= 3 and number(bar[2]) > 0
        ]
        return min(lows) if len(lows) == 3 else 0.0

    def _one_minute_bull_to_bear(self, code: str) -> bool:
        payload = read_json_cached(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        row = (source or {}).get(str(code).zfill(6)) or {}
        previous = row.get("prev") or []
        if not previous or len(previous[-1]) < 4:
            return False
        previous_bull = number(previous[-1][3]) > number(previous[-1][0])
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return bool(
            previous_bull
            and current_open > 0
            and current_close > 0
            and current_close < current_open
        )

    def _one_minute_bearish(self, code: str) -> bool:
        payload = read_json_cached(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        row = (source or {}).get(str(code).zfill(6)) or {}
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return bool(
            current_open > 0
            and current_close > 0
            and current_close < current_open
        )

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
        bars_payload = read_json_cached(self.config.bars_path, {})
        (
            buy_volume_5s,
            sell_volume_5s,
            previous_sell_volume_10s,
            che_str,
            che_change_5s,
        ) = self._common_exit_micro_rates(code, point)
        ma3 = ma3_rows(code, bars_payload) or {}
        # ★[MA20-PHASE 2026-08-05] 국면마다 답이 다르므로 두 번 구한다(위
        #   _daily_ma_permit 주석 참조). 매수세 판정은 한 번만 하고 나눠 쓴다.
        #   ⚠️파일을 두 번 읽지 않는다 — bars_payload 를 그대로 넘기기 때문이다.
        ma_buy_side = ma3_buy_side_alive(
            buy10, buy30, sell10, sell30,
            sell_volume_5s, previous_sell_volume_10s,
        )
        ma_hold = ma3_rider_permit(          # 꼭지용: 20선만 걸친 상태는 보유 없음
            code, price, payload=bars_payload, buy_side=ma_buy_side)
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
            buy_volume_per_sec_5s=Decimal(str(buy_volume_5s)),
            sell_volume_per_sec_5s=Decimal(str(sell_volume_5s)),
            sell_volume_per_sec_previous_10s=Decimal(
                str(previous_sell_volume_10s)),
            che_str=Decimal(str(che_str)),
            che_str_change_5s=Decimal(str(che_change_5s)),
            structure_broken=bool(structure_low > 0 and price < structure_low),
            money_accelerating=bool(
                point["money_speed_10s"] > 0
                and point["money_speed_5s"] >= point["money_speed_10s"]
            ),
            recent_buy_money_rising=bool(
                rate10 and rate30 and rate10[0] >= rate30[0]),
            one_minute_bull_to_bear=self._one_minute_bull_to_bear(code),
            one_minute_bearish=self._one_minute_bearish(code),
            # 명시적 그림자 포지션만 order-zero 규칙을 쓴다. real 키가 없는
            # 구형/손상 상태는 _load_state에서 RECOVERY_BLOCKED로 차단한다.
            common_peak_flow_ready=bool(
                exact
                and rate10 is not None
                and isinstance(position.get("real"), bool)
            ),
            # ★[MA3-COMMON 2026-08-03] 상승보유는 '선 지지 + 매수세 우위' 2단이다.
            #   매수세는 여기 있는 거래대금 속도(10s/30s)로 판정한다. 체결량 속도는
            #   S02·S05 만 관측하므로 그쪽에서 따로 더 넣는다.
            daily_ma_permit=ma_hold,
            # ★[MA20-DEFENSE 2026-08-05] 20선 단계까지 인정한 상승보유.
            #   공통 매도엔진이 손실방어 국면에서만 쓴다(꼭지에는 안 쓴다).
            #   ★[MA20-PHASE 2026-08-05] 8/5 밤에 위 ma_hold 와 갈랐다. 그 전에는
            #   둘이 같은 값(allow_ma20=True)이라 S01 만 꼭지에서도 20선으로
            #   버텼다. 이제 S01·S02·S05 가 같은 규칙이다. ⚠️S04 는 이 엔진을
            #   그대로 쓰므로(strategy_04_rotation_engine_v1.py 가 Strategy01Engine
            #   을 직접 생성) 같이 바뀐다.
            #   ⚠️여기 붙여서 부르는 형태를 유지할 것 — 아침 계약 검사가
            #     'ma20_defense_permit= 에 대입되는 호출'만 손실방어용으로 세고
            #     나머지 allow_ma20=True 는 꼭지용 예외로 고발한다(S02 와 같은 꼴).
            ma20_defense_permit=ma3_rider_permit(
                code, price, payload=bars_payload, buy_side=ma_buy_side,
                allow_ma20=True),
            daily_ma5_broken=ma3_ma5_broken(code, price, bars_payload),
            price_above_ma5=bool(
                ma3.get("ma5", 0.0) > 0 and price > ma3["ma5"]
            ),
            ma5_rising=bool(
                ma3.get("ma5", 0.0) > ma3.get("ma5_prev", 0.0) > 0
            ),
            ma5_value=Decimal(str(ma3.get("ma5", 0.0))),
            ma5_prev_value=Decimal(str(ma3.get("ma5_prev", 0.0))),
            ma10_value=Decimal(str(ma3.get("ma10", 0.0))),
            ma3_source=str(ma3.get("source") or ""),
            ma10_support=bool(
                ma3.get("ma10", 0.0) > 0 and price >= ma3["ma10"]
            ),
            ma20_rising=bool(
                ma3.get("ma20", 0.0) > ma3.get("ma20_prev", 0.0) > 0
            ),
        )

    def _direct_hard_stop_permitted(
        self,
        _position: Dict[str, Any],
        _point: Dict[str, Any],
    ) -> bool:
        return True

    @staticmethod
    def _pullback_failure_reason(
        position: Mapping[str, Any], observation: HoldSellObservation,
    ) -> str:
        stages = set(position.get("entry_stages") or [])
        if str(position.get("entry_stage") or "") == "PULLBACK":
            stages.add("PULLBACK")
        if "PULLBACK" not in stages:
            return ""
        reference_low = Decimal(str(number(
            position.get("pullback_reference_low")
        )))
        if reference_low <= 0 or observation.price >= reference_low:
            return ""
        sell10 = observation.sell_money_per_sec_10s
        sell30 = observation.sell_money_per_sec_30s
        buy10 = observation.buy_money_per_sec_10s
        sell_reaccelerating = (
            sell10 > 0
            and sell10 > buy10
            and sell10 > sell30 * Decimal("1.2")
        )
        return (
            "PULLBACK_LOW_BREAK_SELL_REACCEL"
            if sell_reaccelerating else ""
        )

    @staticmethod
    def _pullback_stale_board_failure_reason(
        position: Mapping[str, Any], point: Mapping[str, Any],
    ) -> str:
        stages = set(position.get("entry_stages") or [])
        if str(position.get("entry_stage") or "") == "PULLBACK":
            stages.add("PULLBACK")
        if "PULLBACK" not in stages:
            return ""
        reference_low = number(position.get("pullback_reference_low"))
        price = number(point.get("price"))
        if reference_low <= 0 or price <= 0:
            return ""
        return (
            "PULLBACK_STALE_BOARD_LOW_BREAK_0P3"
            if price <= reference_low * 0.997 else ""
        )

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
        if now.time() >= force_exit_at:
            self._start_sell(
                position,
                now,
                f"TIME_EXIT_{force_exit_at.strftime('%H%M')}",
                point,
            )
            return
        if not point["board_fresh"]:
            stale_failure = self._pullback_stale_board_failure_reason(
                position, point,
            )
            if stale_failure:
                self._start_sell(position, now, stale_failure, point)
            return
        hold_state = HoldSellState.from_dict(position["hold_state"])
        if (
            hold_state.last_observed_at is not None
            and point["ts"] <= hold_state.last_observed_at
        ):
            return
        observation = self._build_observation(position, point)
        pullback_failure = self._pullback_failure_reason(position, observation)
        if pullback_failure:
            self._start_sell(position, now, pullback_failure, point)
            return
        decision = self.exit_engine.evaluate(hold_state, observation)
        position["hold_state"] = hold_state.to_dict()
        if decision.should_sell:
            partial = decision.action is HoldSellAction.PARTIAL_SELL
            self._start_sell(
                position,
                now,
                decision.reason,
                point,
                quantity_override=1 if partial else None,
                partial=partial,
            )

    def _start_sell(
        self,
        position: Dict[str, Any],
        now: datetime,
        reason: str,
        point: Optional[Mapping[str, Any]],
        *,
        quantity_override: Optional[int] = None,
        partial: bool = False,
    ) -> None:
        retries = int(position.get("sell_retries") or 0)
        force_exit_order = str(reason or "").startswith("TIME_EXIT_")
        retry_limit = self.config.max_sell_retries + (
            FORCE_EXIT_EXTRA_RETRIES if force_exit_order else 0
        )
        if retries >= retry_limit:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = (
                "FORCE_EXIT_RETRY_EXHAUSTED_MANUAL_CHECK"
                if force_exit_order
                else "SELL_RETRY_EXHAUSTED_MANUAL_CHECK"
            )
            now_epoch = time.time()
            last_event = number(
                position.get("sell_retry_exhausted_event_epoch"), -1.0
            )
            if (
                last_event < 0
                or now_epoch - last_event >= EXHAUSTED_EVENT_COOLDOWN_SEC
            ):
                position["sell_retry_exhausted_event_epoch"] = now_epoch
                self._event(
                    "SELL_RETRY_EXHAUSTED",
                    code=position["code"],
                    name=position["name"],
                    reason=reason,
                )
            return
        price = number((point or {}).get("price"), number(position.get("last_price")))
        position_qty = int(position.get("qty") or 0)
        partial_intent = bool(partial and position_qty > 1)
        requested_qty = position_qty
        if quantity_override is not None:
            requested_qty = min(requested_qty, max(1, int(quantity_override)))
        if not position.get("real"):
            if partial_intent and 0 < requested_qty < position_qty:
                self._confirm_partial_exit(
                    position, requested_qty, price, reason, shadow=True)
            else:
                self._confirm_exit(position, price, reason, shadow=True)
            return
        query_budget = float(getattr(
            self.config, "initial_sell_query_budget_sec", 0.0) or 0.0)
        initial_fast_sell = bool(
            getattr(self.config, "strategy_id", None)
            is StrategyId.S02_LOW_BUY_SELL_EXHAUSTION
            and retries == 0
            and query_budget > 0
        )
        query_started = time.monotonic()
        if initial_fast_sell:
            holdings = self.broker.holdings(
                timeout_sec=min(1.0, query_budget), attempts=1)
        else:
            holdings = self.broker.holdings()
        if holdings is None:
            if not initial_fast_sell:
                position["retry_after_epoch"] = time.time() + 5
                self._event(
                    "SELL_WAIT", code=position["code"], name=position["name"],
                    reason=f"BALANCE_UNAVAILABLE:{self.broker.last_error}")
                return
            actual_qty = position_qty
            available = position_qty
            self._event(
                "SELL_QUERY_DEGRADED",
                code=position["code"],
                name=position["name"],
                reason="S02_INITIAL_BALANCE_BUDGET_EXPIRED",
            )
        else:
            actual = holdings.get(position["code"]) or {}
            actual_qty = int(actual.get("qty") or 0)
            available = int(actual.get("available") or 0)
            if actual_qty <= 0:
                self._confirm_exit(position, price, "BROKER_ALREADY_FLAT")
                return
        quantity = min(int(position.get("qty") or 0), available or actual_qty)
        if quantity_override is not None:
            quantity = min(quantity, max(1, int(quantity_override)))
        if quantity <= 0:
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_WAIT", code=position["code"], name=position["name"],
                        reason="BROKER_AVAILABLE_QTY_ZERO")
            return
        if initial_fast_sell:
            remaining = max(0.0, query_budget - (time.monotonic() - query_started))
            known_orders = (
                self._known_orders(
                    position["code"], "매도", timeout_sec=remaining, attempts=1)
                if remaining > 0
                else None
            )
        else:
            known_orders = self._known_orders(position["code"], "매도")
        if known_orders is None:
            if not initial_fast_sell:
                position["retry_after_epoch"] = time.time() + 5
                return
            known_orders = sorted(fills_by_order(
                self.config.fills_dir,
                position["code"],
                "매도",
                day=str(self.state["date"]),
            ))
            self._event(
                "SELL_QUERY_DEGRADED",
                code=position["code"],
                name=position["name"],
                reason="S02_INITIAL_OPEN_ORDER_BUDGET_EXPIRED",
            )
        retry = int(position.get("sell_retries") or 0) + 1
        recovery_cycle = int(position.get("sell_recovery_cycle") or 0)
        # ★[2026-08-19] sell_retries 는 포지션 소속이라 같은 날 재진입한 종목의
        #   첫 매도 키가 직전 포지션의 키와 충돌했다(브로커 DEDUP 이 실주문을
        #   삼켜 매도 24~53초 지연, 8/19 재진입 3/3 재현). 매수 키와 같은
        #   전역 카운터(order_attempts_total)를 붙여 시도마다 유일하게 만든다.
        attempt = int(self.state.get("order_attempts_total") or 0) + 1
        key = (
            f"{self.config.strategy_slug}:"
            f"{self.state['date']}:sell:{position['code']}:"
            + (f"recovery{recovery_cycle}:" if recovery_cycle else "")
            + f"{retry}:a{attempt}"
        )
        self.state["order_attempts_total"] = attempt
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
            "partial": bool(
                partial_intent and quantity < position_qty and quantity < actual_qty
            ),
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
            if position["pending"].get("partial"):
                self._confirm_partial_exit(
                    position, quantity, price, reason, shadow=True)
            else:
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
            if pending.get("partial"):
                self._confirm_partial_exit(
                    position, needed, average, pending["reason"])
            else:
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
                if pending.get("partial") and actual_qty > 0:
                    self._confirm_partial_exit(
                        position,
                        int(pending["pre_hold_qty"]) - actual_qty,
                        average or number(position.get("last_price")),
                        pending["reason"],
                    )
                else:
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
                if pending.get("partial") and actual_qty > 0:
                    self._confirm_partial_exit(
                        position,
                        int(pending["pre_hold_qty"]) - actual_qty,
                        number(position.get("last_price")),
                        pending["reason"],
                    )
                else:
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

    def _confirm_partial_exit(
        self,
        position: Dict[str, Any],
        sold_qty: int,
        fill_price: float,
        reason: str,
        *,
        shadow: bool = False,
    ) -> None:
        current_qty = int(position.get("qty") or 0)
        sold_qty = min(max(0, int(sold_qty)), current_qty)
        remaining = current_qty - sold_qty
        if sold_qty <= 0:
            return
        if remaining <= 0:
            self._confirm_exit(position, fill_price, reason, shadow=shadow)
            return

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

        hold_state = HoldSellState.from_dict(position["hold_state"])
        hold_state.quantity = remaining
        hold_state.peak_partial_taken = True
        hold_state.peak_flow_since = None
        hold_state.peak_recovery_since = None
        hold_state.sell_latched = False
        hold_state.sell_action = HoldSellAction.SELL
        hold_state.sell_reason = ""
        hold_state.sell_latched_at = None
        hold_state.sell_latched_price = Decimal("0")

        reserved = int(position.get("reserved_capital_krw") or 0)
        position.update({
            "phase": "HOLD",
            "qty": remaining,
            "hold_state": hold_state.to_dict(),
            "pending": None,
            "retry_after_epoch": time.time() + 2,
            "reserved_capital_krw": int(reserved * remaining / current_qty),
            "last_price": float(exit_price),
        })
        position.setdefault("partial_exits", []).append({
            "quantity": sold_qty,
            "price": float(exit_price),
            "at": exit_at.isoformat(timespec="seconds"),
            "reason": reason,
            "gross_return_pct": float(gross),
            "estimated_net_return_pct_before_slippage": float(net),
        })
        self._refresh_recovery_blocked()
        self._event(
            "SHADOW_SELL_PARTIAL" if shadow else "SELL_PARTIAL_CONFIRMED",
            code=position["code"], name=position["name"],
            price=float(exit_price), quantity=sold_qty,
            reason=(
                f"{reason} remaining={remaining} gross={gross:.3f}% "
                f"net_before_slippage={net:.3f}%"
            ),
        )

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
            "post_exit_audit": {
                "targets": {},
                "observation_capture": {
                    "last_observed_at": str(
                        (position.get("hold_state") or {}).get(
                            "last_observed_at"
                        ) or exit_at.isoformat(timespec="seconds")
                    ),
                    "rows": 0,
                    "path": "",
                    "error": "",
                    "complete": False,
                },
            },
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
        available_qty = int(actual.get("available") or 0)
        pending = position.get("pending") or {}
        if actual_qty > 0:
            # Retry exhaustion is a mandatory broker-truth checkpoint, not a
            # permanent manual stop. Re-arm only when the broker confirms that
            # shares remain sellable and no sell order is alive.
            sell_exhausted = (
                int(position.get("sell_retries") or 0)
                >= self.config.max_sell_retries
                and bool(position.get("hold_state"))
            )
            if sell_exhausted:
                recovery_cycle = int(
                    position.get("sell_recovery_cycle") or 0
                )
                if recovery_cycle >= MAX_SELL_RECOVERY_CYCLES:
                    position["phase"] = "RECOVERY_BLOCKED"
                    self.state["recovery_blocked"] = True
                    self.state["last_error"] = (
                        "SELL_RECOVERY_CYCLES_EXHAUSTED_MANUAL_CHECK"
                    )
                    return
                open_sell = self.broker.open_orders(code, buy=False)
                if open_sell is None:
                    return
                if open_sell or available_qty <= 0:
                    self._event(
                        "RECOVERY_SELL_REARM_WAIT",
                        code=code,
                        reason=(
                            f"open_sell={open_sell} available={available_qty}"
                        ),
                    )
                    return
                position["qty"] = min(
                    int(position.get("qty") or actual_qty), actual_qty)
                position["pending"] = None
                position["sell_retries"] = 0
                position["sell_recovery_cycle"] = (
                    int(position.get("sell_recovery_cycle") or 0) + 1
                )
                position["retry_after_epoch"] = (
                    time.time() + max(5.0, self.config.fill_wait_sec)
                )
                position["phase"] = "HOLD"
                self.state["last_error"] = ""
                self._event(
                    "RECOVERY_SELL_REARMED",
                    code=code,
                    quantity=position["qty"],
                    reason=(
                        "broker holdings present, available qty positive, "
                        "no open sell order"
                    ),
                )
                self._refresh_recovery_blocked()
                return
            if (
                pending.get("side") == "SELL"
                and pending.get("partial")
                and actual_qty < int(pending.get("pre_hold_qty") or 0)
            ):
                self._confirm_partial_exit(
                    position,
                    int(pending["pre_hold_qty"]) - actual_qty,
                    number(position.get("last_price")),
                    str(pending.get("reason") or "RECOVERY_PARTIAL_CONFIRMED"),
                )
                self._refresh_recovery_blocked()
                return
            if pending.get("side") == "BUY":
                pre_qty = int(pending.get("pre_hold_qty") or 0)
                if actual_qty > pre_qty:
                    balance_average = number(actual.get("buy_price"))
                    self._confirm_entry(
                        position,
                        min(
                            int(pending.get("requested_qty") or 1),
                            actual_qty - pre_qty,
                        ),
                        self._balance_fill_price(
                            position, actual_qty, balance_average,
                        ) or number(position.get("last_price")),
                        now,
                    )
                    self._event("RECOVERY_BUY_CONFIRMED", code=code)
                    self._refresh_recovery_blocked()
                    return
                open_buy = self.broker.open_orders(code, buy=True)
                if open_buy is None or open_buy:
                    return
                if pre_qty > 0 and position.get("hold_state"):
                    position["phase"] = "HOLD"
                    position["pending"] = None
                    self._event("RECOVERY_BUY_ADD_NOT_FILLED", code=code)
                    self._refresh_recovery_blocked()
                    return
            if position.get("hold_state"):
                position["qty"] = min(
                    int(position.get("qty") or actual_qty), actual_qty)
                position["phase"] = "HOLD"
                self._event("RECOVERY_HOLD_RESUMED", code=code)
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

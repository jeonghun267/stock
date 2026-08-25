# -*- coding: utf-8 -*-
"""새전략 06 — 급락 저점추격 매수 (독립 엔진).

★[2026-08-01 친구님 승인 설계 v2]
  대상: 그날의 고저폭30 (IPC\\micro_watch_high_range.json)
  발동: 당일 첫 관측가(시가 근사) 대비 -8% 도달 — 조건은 이것 하나
  추격: 저점을 계속 기록, 신저점이면 리셋(계단식 하락을 끝까지 따라감)
  관찰: 저점+1.5% 첫 반등 뒤 0.4% 이상 눌림을 기다리고, 눌림 저점이 원저점보다
        0.3% 이상 높은 두 번째 저점인지 확인한다. 그 저점에서 다시 0.5% 이상
        상승하고 매수가는 원저점+1~2% 안에 있어야 한다.
  수급: 저점 전 매도우위→저점 후 매수우위, 최근 10초 매수속도 증가·매수우위,
        매도속도 재강화 없음이 모두 필요하다. 수급자료가 없으면 매수하지 않는다.
  포기: 저점+2.0% 초과 회복이면 그 저점은 버리고 다음 신저점 대기(추격매수 금지)
  규모: 10슬롯 · 1종목 1주 · 종목당 하루 2회(2발째는 산 저점보다 1% 더 깊은
        신저점 뒤에만 — 아침 연속 가짜에 연발 낭비 방지) · 종목당 30만원 이내

★매도는 당일 +10%와 익일 상승보유·꼭지점 매도를 분리한다:
  ① 당일 매수가 대비 +10% 도달 시 그 자리에서 매도
  ② 못 갔으면 밤을 넘겨 다음날 09:00부터 고점을 추적한다. 5·10일선 정배열,
     20일선 우상향, 최근 완성 3분봉 고가가 5일선 이상이면 상승보유한다.
     꼭지점 매도는 기존 공통 계단(+1%/-1%, +3%/-1.5%, +6%/-2%)을
     180초마다 판단하고, 꼭지 이후 매수비가 90% 이상이면 매도를 보류한다.
  ⚠️기존 종가매수(EOD_GAP) 코드·포지션 파일은 일절 건드리지 않는다 —
  그쪽 매도경로는 모의 OPEN 을 실매도하는 미해결 문제가 있어(7/29 점검)
  끼어들면 안 된다. 이 엔진이 종가매수 방식을 자체 수행한다.

  공용 6슬롯(shared_slots)·공용코어(strategy_01_rotation_engine_v2)는 일절 쓰지도
  건드리지도 않는다 — 이 전략은 완전 독립 슬롯 10칸으로 돈다.

  기본은 그림자 모드(주문 0·기록만). 실전은 S06_LIVE=YES + 승인깃발
  (config\\strategy_06_live_approved.flag)의 이중게이트를 모두 통과해야 한다.

  구조·주문·복구 절차는 strategy_01_rotation_engine_v2 를 본보기로 복사했다.
  저점 리셋 기록 필드(dip_low_reset_steps 등)는 strategy_02_low_buy_signal_v1 과
  같은 이름을 쓴다(판독 도구 호환).
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

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from zoneinfo import ZoneInfo

# ★[MA3-COMMON 2026-08-03] 상승보유 = 3분봉 5/10/20선 + 매수세 우위(전 전략 공통).
from ma3_common_v1 import (
    buy_side_alive as ma3_buy_side_alive,
    rider_permit as ma3_rider_permit,
)
from strategy_common_order_v1 import StrategyBroker, fills_by_order


KST = ZoneInfo("Asia/Seoul")
STATE_SCHEMA = "strategy_06_crash_low_chase_v1"
STRATEGY_TAG = "S06_CRASH_LOW_CHASE"
ACTIVE_PHASES = {"BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"}
PENDING_PHASES = {"BUY_PENDING", "SELL_PENDING", "RECOVERY_BLOCKED"}
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
    watch_path: Path = Path(r"C:\stock_bot\IPC\micro_watch_high_range.json")
    hr_state_path: Path = Path(r"C:\stock_bot\data\common_high_range_live_state.json")
    snapshot_path: Path = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
    bars_path: Path = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
    eod_bars_path: Path = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
    names_path: Path = Path(r"C:\stock_bot\data\_code_name_cache.json")
    state_path: Path = Path(r"C:\stock_bot\data\strategy_06_crash_low_chase_state_v1.json")
    fills_dir: Path = Path(r"C:\stock_bot\LOG")
    event_dir: Path = Path(r"C:\stock_bot\data\strategy_06_crash_low_chase")
    log_path: Path = Path(r"C:\stock_bot\LOG\strategy_06_crash_low_chase.log")
    approval_path: Path = Path(r"C:\stock_bot\config\strategy_06_live_approved.flag")
    off_flag_path: Path = Path(r"C:\stock_bot\config\strategy_06_off.flag")
    manual_buy_block_path: Path = Path(r"C:\stock_bot\config\manual_buy_block.flag")
    lock_path: Path = Path(r"C:\stock_bot\data\strategy_06_crash_low_chase.lock")
    live_requested: bool = (
        os.environ.get("S06_LIVE", "NO").strip().upper() == "YES"
    )
    quantity: int = int(os.environ.get("S06_QTY", "1"))
    max_slots: int = int(os.environ.get("S06_MAX_SLOTS", "10"))
    max_daily_codes: int = int(os.environ.get("S06_MAX_DAILY_CODES", "20"))
    capital_krw: int = int(os.environ.get("S06_CAPITAL_KRW", "1000000"))
    max_price_krw: int = int(os.environ.get("S06_MAX_PRICE_KRW", "300000"))
    min_price_krw: int = int(os.environ.get("S06_MIN_PRICE_KRW", "10000"))
    drop_pct: float = float(os.environ.get("S06_DROP_PCT", "8.0"))
    rebound_pct: float = float(os.environ.get("S06_REBOUND_PCT", "1.5"))
    chase_cap_pct: float = float(os.environ.get("S06_CHASE_CAP_PCT", "2.0"))
    entry_floor_pct: float = float(os.environ.get("S06_ENTRY_FLOOR_PCT", "1.0"))
    pullback_min_pct: float = float(os.environ.get("S06_PULLBACK_MIN_PCT", "0.4"))
    higher_low_buffer_pct: float = float(os.environ.get("S06_HIGHER_LOW_BUFFER_PCT", "0.3"))
    second_rebound_pct: float = float(os.environ.get("S06_SECOND_REBOUND_PCT", "0.5"))
    flow_accel_window_sec: float = float(os.environ.get("S06_FLOW_ACCEL_WINDOW_SEC", "10"))
    observe_sec: float = float(os.environ.get("S06_OBSERVE_SEC", "60"))
    observe_max_sec: float = float(os.environ.get("S06_OBSERVE_MAX_SEC", "720"))
    max_entries_per_code: int = int(os.environ.get("S06_MAX_ENTRIES_PER_CODE", "2"))
    rearm_deeper_pct: float = float(os.environ.get("S06_REARM_DEEPER_PCT", "1.0"))
    tp_pct: float = float(os.environ.get("S06_TP_PCT", "10.0"))
    morning_trail_eval_interval_sec: int = int(os.environ.get("S06_MORNING_TRAIL_EVAL_SEC", "180"))
    max_sell_retries: int = int(os.environ.get("S06_MAX_SELL_RETRIES", "3"))
    snapshot_max_age_sec: float = float(os.environ.get("S06_SNAPSHOT_MAX_AGE_SEC", "15"))
    fill_wait_sec: float = float(os.environ.get("S06_FILL_WAIT_SEC", "8"))
    loop_sec: float = float(os.environ.get("S06_LOOP_SEC", "1"))
    entry_start: day_time = day_time(9, 0)
    entry_end: day_time = day_time(14, 30)
    morning_sell_start: day_time = day_time(9, 0)
    process_end: day_time = day_time(15, 25)
    strategy_slug: str = "strategy06"
    strategy_label: str = "Strategy 06 crash-low-chase"
    broker_order_prefix: str = "STRATEGY06"
    screen_no: str = "9786"
    event_prefix: str = "strategy_06"

    def __post_init__(self) -> None:
        if self.quantity != 1:
            raise ValueError("Strategy 06 requires exactly one-share buys")
        if not 1 <= self.max_slots <= 10:
            raise ValueError("Strategy 06 slots must be between 1 and 10")
        if self.capital_krw <= 0 or self.max_price_krw <= 0:
            raise ValueError("capital and price caps must be positive")
        if self.drop_pct <= 0 or self.rebound_pct <= 0 or self.entry_floor_pct <= 0:
            raise ValueError("drop/rebound thresholds must be positive")
        if self.chase_cap_pct <= self.rebound_pct:
            raise ValueError("chase cap must exceed rebound threshold")
        if self.entry_floor_pct > self.rebound_pct:
            raise ValueError("entry floor must not exceed first rebound threshold")
        if self.pullback_min_pct <= 0 or self.second_rebound_pct <= 0:
            raise ValueError("pullback/second rebound thresholds must be positive")
        if not 0 < self.higher_low_buffer_pct < self.rebound_pct:
            raise ValueError("higher-low buffer must sit below first rebound")
        if self.flow_accel_window_sec < 5:
            raise ValueError("flow acceleration window must be at least 5 seconds")
        if self.observe_sec < 0 or self.observe_max_sec < self.observe_sec:
            raise ValueError("observe windows are inconsistent")
        if self.tp_pct <= 0:
            raise ValueError("take-profit threshold must be positive")
        if self.morning_trail_eval_interval_sec < 1:
            raise ValueError("morning trail interval must be positive")
        if not 1 <= self.max_entries_per_code <= 2:
            raise ValueError("entries per code must be 1 or 2")
        if not 0 <= self.rearm_deeper_pct <= 5:
            raise ValueError("rearm depth must be between 0 and 5 percent")


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


class VolumeWindow:
    """누적 체결량으로 최근 60초 체결량 속도를 잰다(투매 소진 판정용)."""

    def __init__(self) -> None:
        self.rows: deque = deque()

    def add(self, observed_at: datetime, cum_vol: float) -> None:
        if self.rows and cum_vol < self.rows[-1][1]:
            self.rows.clear()
        self.rows.append((observed_at, cum_vol))
        while self.rows and (observed_at - self.rows[0][0]).total_seconds() > 600:
            self.rows.popleft()

    def rate_60s(self) -> Optional[float]:
        if len(self.rows) < 2:
            return None
        end = self.rows[-1]
        eligible = [r for r in self.rows if (end[0] - r[0]).total_seconds() >= 60]
        if not eligible:
            return None
        start = eligible[-1]
        elapsed = (end[0] - start[0]).total_seconds()
        if elapsed <= 0:
            return None
        return max(0.0, end[1] - start[1]) / elapsed


@dataclass
class ChaseState:
    """종목 하나의 저점추격 상태기계."""
    phase: str = "IDLE"          # IDLE → CHASE → OBSERVE → DONE
    first_price: float = 0.0
    low: float = 0.0
    low_at: str = ""
    dead_low: float = 0.0        # 포기 처리된 저점(신저점이 나오면 해제)
    reset_steps: int = 0         # 계단 수 = 발동 후 저점이 새로 낮아진 횟수
    triggered_at: str = ""
    observe_since: str = ""
    first_rebound_peak: float = 0.0
    first_rebound_at: str = ""
    pullback_seen: bool = False
    pullback_low: float = 0.0
    pullback_low_at: str = ""
    observe_low: float = 0.0
    che_at_observe: float = 0.0
    vol_rate_peak: float = 0.0
    buy_cum_at_low: float = -1.0
    sell_cum_at_low: float = -1.0
    # 저점 직전 3분 매수/매도 속도(원/초). -1은 자료 없음이며 매수를 차단한다.
    # 저점 전 매도우위→저점 후 매수우위 역전 판정에 사용한다.
    low_epoch: float = 0.0
    pre_buy_rate: float = -1.0
    pre_sell_rate: float = -1.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ChaseState":
        state = cls()
        for key, value in dict(payload or {}).items():
            if hasattr(state, key):
                setattr(state, key, value)
        return state


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


class Strategy06Engine:
    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        broker: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config or Config()
        self.log = logger or setup_logger(self.config)
        self.volumes: Dict[str, VolumeWindow] = defaultdict(VolumeWindow)
        # (epoch, 매수누적, 매도누적) 흐름 이력 — 저점 전후 역전·최근 10초 재가속 판정
        self.flows: Dict[str, deque] = defaultdict(deque)
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
            screen_no=self.config.screen_no,
            force_exit_only=force_exit_only,
        )
        self._last_reconcile_epoch: Dict[str, float] = {}
        self._snapshot_cache: Tuple[float, dict] = (0.0, {})
        self._hr_cache: Tuple[float, dict] = (0.0, {})
        self._daily_ma_cache: Tuple[str, dict] = ("", {})
        self._bars_cache: Tuple[float, dict] = (-1.0, {})
        self._entry_wait_epoch: Dict[str, float] = {}
        self._observe_log_epoch: Dict[str, float] = {}
        self._startup_reconcile()

    # ── 상태 ────────────────────────────────────────────────────────────
    def _blank_state(self, day: str) -> Dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "date": day,
            "order_attempts_total": 0,
            "positions": {},
            "entered_codes": [],
            "chase": {},
            "history": [],
            "recovery_blocked": False,
            "last_error": "",
            "heartbeat": "",
        }

    def _load_state(self) -> Dict[str, Any]:
        """날짜가 바뀌어도 HOLD 포지션은 정상이다(종가매수 방식 — 밤 넘김).
        주문이 밤을 넘겨 걸려 있는 것(PENDING류)만 비정상으로 잠근다."""
        now = kst_now()
        today = now.strftime("%Y%m%d")
        payload = read_json(self.config.state_path, {})
        if payload.get("schema") != STATE_SCHEMA:
            return self._blank_state(today)
        if not isinstance(payload.get("positions"), dict):
            return self._blank_state(today)
        if str(payload.get("date") or "") != today:
            holds = {
                code: position
                for code, position in payload["positions"].items()
                if isinstance(position, dict) and position.get("phase") == "HOLD"
            }
            pending = any(
                isinstance(position, dict)
                and position.get("phase") in PENDING_PHASES
                for position in payload["positions"].values()
            )
            fresh = self._blank_state(today)
            fresh["positions"] = dict(payload["positions"]) if pending else holds
            if pending:
                fresh["recovery_blocked"] = True
                fresh["last_error"] = "PENDING_ORDER_FROM_PREVIOUS_DAY"
            return fresh
        payload.setdefault("order_attempts_total", 0)
        payload.setdefault("entered_codes", [])
        payload.setdefault("chase", {})
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

    # ── 기록 ────────────────────────────────────────────────────────────
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
            "reason", "order_no", "mode", "order_attempts_total",
            "active_slots", "capital_in_use_krw",
        ]
        row = {
            "ts": now.isoformat(timespec="seconds"),
            "strategy_id": STRATEGY_TAG,
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

    def _signal_record(self, code: str, name: str, event: str, chase: ChaseState,
                       *, price: float = 0.0, reason: str = "",
                       che_now: float = 0.0, vol_rate_now: float = -1.0,
                       flow: Optional[dict] = None) -> None:
        """관찰창의 가격 모양·수급 판정 근거를 신호마다 남긴다."""
        now = kst_now()
        path = (
            self.config.event_dir
            / f"{self.config.event_prefix}_signals_{now:%Y%m%d}.csv"
        )
        columns = [
            "ts", "event", "code", "name", "price", "first_price", "drop_pct",
            "low", "low_at", "dip_low_reset_steps", "observe_since",
            "first_rebound_peak", "pullback_low", "pullback_depth_pct",
            "higher_low_pct", "second_rebound_pct",
            "che_at_observe", "che_now", "vol_rate_peak", "vol_rate_now",
            "dip_buy_sell_ratio", "dip_flow_obs_sec",
            "pre_buy_rate", "pre_sell_rate", "post_buy_rate", "post_sell_rate",
            "flow_flip", "previous_buy_rate_10s", "recent_buy_rate_10s",
            "previous_sell_rate_10s", "recent_sell_rate_10s", "flow_accel",
            "reason",
        ]
        drop = (chase.low / chase.first_price - 1.0) * 100.0 if chase.first_price > 0 and chase.low > 0 else 0.0
        row = {
            "ts": now.isoformat(timespec="seconds"),
            "event": event,
            "code": code,
            "name": name,
            "price": round(price, 2),
            "first_price": chase.first_price,
            "drop_pct": round(drop, 3),
            "low": chase.low,
            "low_at": chase.low_at,
            "dip_low_reset_steps": chase.reset_steps,
            "observe_since": chase.observe_since,
            "first_rebound_peak": round(chase.first_rebound_peak, 2),
            "pullback_low": round(chase.pullback_low, 2),
            "pullback_depth_pct": round(
                (chase.pullback_low / chase.first_rebound_peak - 1.0) * 100.0, 3
            ) if chase.first_rebound_peak > 0 and chase.pullback_low > 0 else "",
            "higher_low_pct": round(
                (chase.pullback_low / chase.low - 1.0) * 100.0, 3
            ) if chase.low > 0 and chase.pullback_low > 0 else "",
            "second_rebound_pct": round(
                (price / chase.pullback_low - 1.0) * 100.0, 3
            ) if chase.pullback_low > 0 and price > 0 else "",
            "che_at_observe": round(chase.che_at_observe, 2),
            "che_now": round(che_now, 2),
            "vol_rate_peak": round(chase.vol_rate_peak, 1),
            "vol_rate_now": round(vol_rate_now, 1),
            "dip_buy_sell_ratio": "", "dip_flow_obs_sec": "",
            "pre_buy_rate": "", "pre_sell_rate": "",
            "post_buy_rate": "", "post_sell_rate": "", "flow_flip": "",
            "previous_buy_rate_10s": "", "recent_buy_rate_10s": "",
            "previous_sell_rate_10s": "", "recent_sell_rate_10s": "",
            "flow_accel": "",
            "reason": reason,
        }
        if flow:
            row.update(flow)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            if new:
                writer.writeheader()
            writer.writerow(row)

    # ── 브로커 진실 복구(공용코어와 동일 절차) ────────────────────────────
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
        # ★[2026-08-01 보안점검 높음4] 같은 종목 2포지션(code:1·code:2)을 복구할 때
        #   계좌 잔량을 "종목별 총량"으로 나눠 배분한다 — 종전에는 포지션마다
        #   따로 min()을 해서 잔량 1주를 두 포지션이 동시에 자기 것으로 셌다.
        remaining_by_code: Dict[str, int] = {}
        for position in sorted(
            real_positions,
            key=lambda p: (str(p.get("code") or ""), int(p.get("entry_no") or 1)),
        ):
            code = str(position.get("code") or "").zfill(6)
            actual = holdings.get(code) or {}
            if code not in remaining_by_code:
                remaining_by_code[code] = int(actual.get("qty") or 0)
            phase = str(position.get("phase") or "")
            if phase == "HOLD":
                want = int(position.get("qty") or 0) or 1
                give = min(want, remaining_by_code[code])
                if give <= 0:
                    self._confirm_exit(
                        position,
                        number(position.get("last_price")),
                        "RECOVERY_ALREADY_FLAT",
                    )
                else:
                    position["qty"] = give
                    remaining_by_code[code] -= give
                    if number(position.get("entry_price")) <= 0:
                        position["entry_price"] = number(actual.get("buy_price"))
            elif phase == "SELL_PENDING":
                if remaining_by_code[code] <= 0:
                    self._confirm_exit(
                        position,
                        number(position.get("last_price")),
                        "RECOVERY_FLAT",
                    )
                else:
                    remaining_by_code[code] -= min(
                        int(position.get("qty") or 0) or 1,
                        remaining_by_code[code],
                    )
        self._refresh_recovery_blocked()
        self._save()

    # ── 시세 읽기 ────────────────────────────────────────────────────────
    def _snapshot(self) -> dict:
        epoch = time.time()
        if epoch - self._snapshot_cache[0] < 0.5:
            return self._snapshot_cache[1]
        payload = read_json(self.config.snapshot_path, {})
        self._snapshot_cache = (epoch, payload if isinstance(payload, dict) else {})
        return self._snapshot_cache[1]

    def _snapshot_point(self, code: str, now: datetime) -> Optional[Dict[str, Any]]:
        raw = (self._snapshot().get("codes") or {}).get(str(code).zfill(6))
        if not isinstance(raw, dict):
            return None
        observed_at = parse_dt(raw.get("ts"), now)
        if abs((now - observed_at).total_seconds()) > self.config.snapshot_max_age_sec:
            return None
        price = abs(number(raw.get("cur")))
        if price <= 0:
            return None
        return {
            "code": str(code).zfill(6),
            "ts": observed_at,
            "price": price,
            "cum_vol": max(0.0, number(raw.get("cum_vol"))),
            "che_str": number(raw.get("che_str")),
            "buy_money_cum": number(raw.get("buy_money_cum"), -1.0),
            "sell_money_cum": number(raw.get("sell_money_cum"), -1.0),
        }

    def _universe(self, now: datetime) -> Tuple[list, str]:
        """오늘의 고저폭 핵심확인대(A등급 우선). (codes, block_reason)"""
        watch = read_json(self.config.watch_path, {})
        codes = [str(c).zfill(6) for c in (watch.get("codes") or [])]
        if not codes:
            return [], "WATCHLIST_EMPTY"
        if str(watch.get("for_date") or "") != now.strftime("%Y%m%d"):
            return [], "WATCHLIST_NOT_TODAY"
        if watch.get("source_stale"):
            return [], "WATCHLIST_SOURCE_STALE"
        core_codes = [
            str(c).zfill(6) for c in (watch.get("crown_codes") or [])
        ]
        if not core_codes:
            return [], "CORE_WATCHLIST_EMPTY"
        priority_set = {
            str(c).zfill(6) for c in (watch.get("crown_priority_codes") or [])
        }
        priority_codes = [c for c in core_codes if c in priority_set]
        other_core_codes = [c for c in core_codes if c not in priority_set]
        return priority_codes + other_core_codes, ""

    def _hr_row(self, code: str) -> Mapping[str, Any]:
        epoch = time.time()
        if epoch - self._hr_cache[0] >= 1.0:
            payload = read_json(self.config.hr_state_path, {})
            self._hr_cache = (epoch, payload if isinstance(payload, dict) else {})
        return ((self._hr_cache[1].get("codes") or {}).get(str(code).zfill(6)) or {})

    def _pre_rates(self, code: str, epoch_now: float) -> Tuple[float, float]:
        """저점 직전 3분의 매수/매도 속도(원/초). 자료 부족이면 (-1, -1)."""
        flow = self.flows.get(code)
        if not flow or len(flow) < 2:
            return -1.0, -1.0
        window = [r for r in flow if epoch_now - r[0] <= 180.0]
        if len(window) < 2:
            return -1.0, -1.0
        span = window[-1][0] - window[0][0]
        if span < 30.0:
            return -1.0, -1.0
        return (
            max(0.0, window[-1][1] - window[0][1]) / span,
            max(0.0, window[-1][2] - window[0][2]) / span,
        )

    def _flow_metrics(self, chase: ChaseState, point: Dict[str, Any]) -> dict:
        """저점 이후 매수/매도 증가분과 저점 전후 속도 역전을 계산한다."""
        out = dict(dip_buy_sell_ratio="", dip_flow_obs_sec="",
                   pre_buy_rate="", pre_sell_rate="",
                   post_buy_rate="", post_sell_rate="", flow_flip="")
        if not (point["buy_money_cum"] >= 0 and point["sell_money_cum"] >= 0
                and chase.buy_cum_at_low >= 0 and chase.sell_cum_at_low >= 0
                and chase.low_epoch > 0):
            return out
        d_buy = point["buy_money_cum"] - chase.buy_cum_at_low
        d_sell = point["sell_money_cum"] - chase.sell_cum_at_low
        elapsed = max(1.0, point["ts"].timestamp() - chase.low_epoch)
        out["dip_buy_sell_ratio"] = round(d_buy / d_sell, 3) if d_sell > 0 else ""
        out["dip_flow_obs_sec"] = round(elapsed, 1)
        post_b = max(0.0, d_buy) / elapsed
        post_s = max(0.0, d_sell) / elapsed
        out["post_buy_rate"] = round(post_b, 1)
        out["post_sell_rate"] = round(post_s, 1)
        if chase.pre_buy_rate >= 0 and chase.pre_sell_rate >= 0:
            out["pre_buy_rate"] = round(chase.pre_buy_rate, 1)
            out["pre_sell_rate"] = round(chase.pre_sell_rate, 1)
            if (chase.pre_buy_rate + chase.pre_sell_rate) <= 0 or (post_b + post_s) <= 0:
                out["flow_flip"] = ""          # 흐름이 없어 판별 불가
            else:
                out["flow_flip"] = (
                    "O" if (chase.pre_sell_rate > chase.pre_buy_rate
                            and post_b > post_s)
                    else "X"
                )
        return out

    def _flow_acceleration(self, code: str, epoch_now: float) -> dict:
        """직전 10초와 최근 10초의 수급속도를 비교한다. 자료 부족은 빈 값이다."""
        out = {
            "previous_buy_rate_10s": "", "recent_buy_rate_10s": "",
            "previous_sell_rate_10s": "", "recent_sell_rate_10s": "",
            "flow_accel": "",
        }
        flow = self.flows.get(code)
        if not flow or len(flow) < 3:
            return out
        window = self.config.flow_accel_window_sec
        end = flow[-1]
        tolerance = max(3.0, window * 0.4)
        if abs(epoch_now - end[0]) > tolerance:
            return out

        def point_at_or_before(target: float) -> Optional[tuple]:
            for row in reversed(flow):
                if row[0] <= target:
                    return row
            return None

        middle_target = end[0] - window
        start_target = end[0] - 2.0 * window
        middle = point_at_or_before(middle_target)
        start = point_at_or_before(start_target)
        if middle is None or start is None:
            return out
        if middle_target - middle[0] > tolerance or start_target - start[0] > tolerance:
            return out
        previous_span = middle[0] - start[0]
        recent_span = end[0] - middle[0]
        if min(previous_span, recent_span) < window * 0.6:
            return out

        previous_buy = max(0.0, middle[1] - start[1]) / previous_span
        previous_sell = max(0.0, middle[2] - start[2]) / previous_span
        recent_buy = max(0.0, end[1] - middle[1]) / recent_span
        recent_sell = max(0.0, end[2] - middle[2]) / recent_span
        out.update({
            "previous_buy_rate_10s": round(previous_buy, 1),
            "recent_buy_rate_10s": round(recent_buy, 1),
            "previous_sell_rate_10s": round(previous_sell, 1),
            "recent_sell_rate_10s": round(recent_sell, 1),
            "flow_accel": "O" if (
                recent_buy > previous_buy
                and recent_buy > recent_sell
                and recent_sell <= previous_sell
            ) else "X",
        })
        return out

    @staticmethod
    def _clear_retest(chase: ChaseState) -> None:
        chase.observe_since = ""
        chase.observe_low = 0.0
        chase.first_rebound_peak = 0.0
        chase.first_rebound_at = ""
        chase.pullback_seen = False
        chase.pullback_low = 0.0
        chase.pullback_low_at = ""

    # ── 저점추격 상태기계 (이 전략의 심장) ────────────────────────────────
    def _chase_states(self) -> Dict[str, ChaseState]:
        raw = self.state.setdefault("chase", {})
        return {code: ChaseState.from_dict(row) for code, row in raw.items()}

    def _save_chase(self, code: str, chase: ChaseState) -> None:
        self.state.setdefault("chase", {})[code] = chase.to_dict()

    def _chase_tick(self, code: str, now: datetime) -> None:
        raw = self.state.setdefault("chase", {}).get(code) or {}
        chase = ChaseState.from_dict(raw)
        if chase.phase == "DONE":
            return
        point = self._snapshot_point(code, now)
        if point is None:
            return
        price = point["price"]
        name = self.names.get(code, code)
        hr = self._hr_row(code)

        # 수급 이력: 저점 직전 3분 역전과 최근 10초 재가속 판정에 함께 사용한다.
        epoch_now = point["ts"].timestamp()
        if point["buy_money_cum"] >= 0 and point["sell_money_cum"] >= 0:
            flow = self.flows[code]
            if flow and (point["buy_money_cum"] < flow[-1][1]
                         or point["sell_money_cum"] < flow[-1][2]):
                flow.clear()
            flow.append((epoch_now, point["buy_money_cum"], point["sell_money_cum"]))
            while flow and epoch_now - flow[0][0] > 360:
                flow.popleft()

        # 기준가 = 실황판의 첫 관측가(시가 근사). 실황판이 없으면 자체 첫 관측가.
        if chase.first_price <= 0:
            first = number(hr.get("first_price"))
            chase.first_price = first if first > 0 else price
        # 저점 = 실황판 누적저점과 자체 관측의 최소값
        hr_low = number(hr.get("low"))
        seen_low = min(
            value for value in (hr_low, chase.low, price) if value > 0
        )
        new_low = chase.low <= 0 or seen_low < chase.low
        if new_low:
            if chase.phase in {"CHASE", "OBSERVE"} and chase.low > 0:
                chase.reset_steps += 1
            chase.low = seen_low
            chase.low_at = now.strftime("%H:%M:%S")
            # ★[2026-08-01] 죽인 저점은 "문턱보다 깊은" 신저점만 되살린다.
            #   매수 재무장은 산 저점보다 rearm_deeper_pct 만큼 깊어야 함(아침 연속
            #   가짜 역전에 2발을 다 쓰는 것 방지 — 7/29 재생 -2.18%→+0.98%).
            #   포기(dead=저점 그대로)는 어떤 신저점이든 그보다 낮으므로 종전과 동일.
            if chase.dead_low <= 0 or seen_low < chase.dead_low:
                chase.dead_low = 0.0
            chase.buy_cum_at_low = point["buy_money_cum"]
            chase.sell_cum_at_low = point["sell_money_cum"]
            chase.low_epoch = epoch_now
            chase.pre_buy_rate, chase.pre_sell_rate = self._pre_rates(code, epoch_now)
            if chase.phase == "OBSERVE":
                chase.phase = "CHASE"       # 계단 — 기존 반등·눌림을 폐기하고 재추격
                self._clear_retest(chase)

        # 체결량 속도(투매 소진 판정 재료)
        volume = self.volumes[code]
        volume.add(point["ts"], point["cum_vol"])
        vol_rate = volume.rate_60s()

        if chase.phase == "IDLE":
            drop = (chase.low / chase.first_price - 1.0) * 100.0 if chase.first_price > 0 and chase.low > 0 else 0.0
            if drop <= -self.config.drop_pct:
                chase.phase = "CHASE"
                chase.triggered_at = now.strftime("%H:%M:%S")
                chase.vol_rate_peak = vol_rate or 0.0
                self._signal_record(code, name, "TRIGGER", chase, price=price,
                                    reason=f"drop={drop:.2f}%",
                                    flow=self._flow_metrics(chase, point))
                self._event("CHASE_TRIGGER", code=code, name=name, price=price,
                            reason=f"drop={drop:.2f}% low={chase.low:.0f}")
            self._save_chase(code, chase)
            return

        # 투매 절정은 '하락 추격 중'의 최대 체결량 — 관찰창의 반등 거래량은
        # 절정 갱신에 넣지 않는다(반등 매수세를 투매로 오인하는 것 방지).
        if vol_rate is not None and chase.phase == "CHASE":
            chase.vol_rate_peak = max(chase.vol_rate_peak, vol_rate)

        if now.time() >= self.config.entry_end:
            self._save_chase(code, chase)
            return
        if chase.dead_low > 0 and chase.low >= chase.dead_low:
            self._save_chase(code, chase)
            return                          # 포기된 저점 — 신저점만 기다린다

        rebound_floor = chase.low * (1.0 + self.config.rebound_pct / 100.0)
        chase_ceiling = chase.low * (1.0 + self.config.chase_cap_pct / 100.0)
        entry_floor = chase.low * (1.0 + self.config.entry_floor_pct / 100.0)
        higher_low_floor = chase.low * (
            1.0 + self.config.higher_low_buffer_pct / 100.0)

        if chase.phase == "CHASE":
            if price > chase_ceiling:
                chase.dead_low = chase.low   # 이미 저점+2% 위 — 추격 금지
                self._signal_record(code, name, "GIVEUP", chase, price=price,
                                    reason="ABOVE_CHASE_CAP",
                                    flow=self._flow_metrics(chase, point))
            elif price >= rebound_floor and not new_low:
                chase.phase = "OBSERVE"
                chase.observe_since = now.isoformat(timespec="seconds")
                chase.observe_low = chase.low
                chase.first_rebound_peak = price
                chase.first_rebound_at = now.isoformat(timespec="seconds")
                chase.pullback_seen = False
                chase.pullback_low = 0.0
                chase.pullback_low_at = ""
                chase.che_at_observe = point["che_str"]
                self._signal_record(code, name, "OBSERVE_START", chase, price=price,
                                    reason="FIRST_REBOUND_CONFIRMED",
                                    che_now=point["che_str"],
                                    vol_rate_now=vol_rate if vol_rate is not None else -1.0,
                                    flow=self._flow_metrics(chase, point))
            self._save_chase(code, chase)
            return

        # 구버전 OBSERVE 상태는 새 모양 정보가 없으므로 반드시 첫 반등부터 다시 확인한다.
        if chase.first_rebound_peak <= 0:
            chase.phase = "CHASE"
            self._clear_retest(chase)
            self._save_chase(code, chase)
            return

        # OBSERVE — 첫 반등 뒤 눌림과 높은 두 번째 저점을 확인한다.
        if price > chase_ceiling:
            chase.dead_low = chase.low
            chase.phase = "CHASE"
            self._signal_record(code, name, "GIVEUP", chase, price=price,
                                reason="ABOVE_CHASE_CAP_IN_OBSERVE",
                                flow=self._flow_metrics(chase, point))
            self._clear_retest(chase)
            self._save_chase(code, chase)
            return
        since = parse_dt(chase.observe_since, now)
        elapsed = (now - since).total_seconds()
        if elapsed > self.config.observe_max_sec:
            chase.dead_low = chase.low
            chase.phase = "CHASE"
            self._signal_record(code, name, "OBSERVE_TIMEOUT", chase, price=price,
                                reason=f"{elapsed:.0f}s",
                                flow=self._flow_metrics(chase, point))
            self._clear_retest(chase)
            self._save_chase(code, chase)
            return

        if not chase.pullback_seen:
            chase.first_rebound_peak = max(chase.first_rebound_peak, price)
            pullback_trigger = chase.first_rebound_peak * (
                1.0 - self.config.pullback_min_pct / 100.0)
            if price <= pullback_trigger:
                if price < higher_low_floor:
                    self._signal_record(
                        code, name, "HIGHER_LOW_RESET", chase, price=price,
                        reason="PULLBACK_BELOW_HIGHER_LOW_FLOOR",
                        flow=self._flow_metrics(chase, point),
                    )
                    chase.phase = "CHASE"
                    self._clear_retest(chase)
                    self._save_chase(code, chase)
                    return
                chase.pullback_seen = True
                chase.pullback_low = price
                chase.pullback_low_at = now.isoformat(timespec="seconds")
                self._signal_record(
                    code, name, "PULLBACK_FOUND", chase, price=price,
                    reason="HIGHER_SECOND_LOW",
                    flow=self._flow_metrics(chase, point),
                )
        else:
            if price < higher_low_floor:
                self._signal_record(
                    code, name, "HIGHER_LOW_RESET", chase, price=price,
                    reason="SECOND_LOW_BROKE_FLOOR",
                    flow=self._flow_metrics(chase, point),
                )
                chase.phase = "CHASE"
                self._clear_retest(chase)
                self._save_chase(code, chase)
                return
            chase.pullback_low = min(chase.pullback_low, price)
            if price == chase.pullback_low:
                chase.pullback_low_at = now.isoformat(timespec="seconds")

        if elapsed < self.config.observe_sec:
            self._save_chase(code, chase)
            return

        # ★[2026-08-02 친구님 승인] 가격 모양과 수급을 모두 확인한다.
        #   ① +1.5% 첫 반등 ② 0.4% 이상 눌림 ③ 원저점+0.3% 위 두 번째 저점
        #   ④ 두 번째 저점+0.5% 재상승 ⑤ 매수가는 원저점+1~2%
        #   ⑥ 저점 전 매도우위→저점 후 매수우위 ⑦ 최근 10초 매수속도 증가·
        #   매수우위·매도속도 재강화 없음. 수급자료가 없으면 fail-closed.
        failures = []
        if not chase.pullback_seen or chase.pullback_low <= 0:
            failures.append("NO_VALID_PULLBACK")
        elif price < chase.pullback_low * (
                1.0 + self.config.second_rebound_pct / 100.0):
            failures.append("NO_SECOND_REBOUND")
        if price < entry_floor:
            failures.append("PRICE_BELOW_ENTRY_FLOOR")
        che_now = point["che_str"]
        fm = self._flow_metrics(chase, point)
        fm.update(self._flow_acceleration(code, epoch_now))
        if fm.get("flow_flip") != "O":
            failures.append("NO_FLOW_FLIP")
        if fm.get("flow_accel") != "O":
            failures.append(
                "NO_FLOW_ACCEL_DATA" if not fm.get("flow_accel")
                else "NO_FLOW_ACCEL"
            )
        if failures:
            # 실패는 종료가 아니다 — 관찰을 이어가며 다음 틱에 재판정 (기록은 30초에 1줄)
            if time.time() - self._observe_log_epoch.get(code, 0.0) >= 30.0:
                self._observe_log_epoch[code] = time.time()
                self._signal_record(code, name, "OBSERVE_WAIT", chase, price=price,
                                    reason=",".join(failures), che_now=che_now,
                                    vol_rate_now=vol_rate if vol_rate is not None else -1.0,
                                    flow=fm)
            self._save_chase(code, chase)
            return

        # 슬롯·자금 대기 중 매초 재시도로 기록이 넘치지 않게 10초 간격으로만 시도
        if time.time() - self._entry_wait_epoch.get(code, 0.0) < 10.0:
            self._save_chase(code, chase)
            return
        self._entry_wait_epoch[code] = time.time()
        self._signal_record(code, name, "BUY_READY", chase, price=price,
                            che_now=che_now,
                            vol_rate_now=vol_rate if vol_rate is not None else -1.0,
                            flow=fm)
        self._save_chase(code, chase)
        result = self._try_entry(code, name, point, chase, now)
        if result == "STOP":
            chase.phase = "DONE"
            self._save_chase(code, chase)
        elif result == "BOUGHT":
            entries = [str(c).zfill(6) for c in
                       (self.state.get("entered_codes") or [])].count(code)
            if entries >= self.config.max_entries_per_code:
                chase.phase = "DONE"
            else:
                # ★재무장 — 산 저점보다 rearm_deeper_pct 더 깊은 신저점이 나와야 2발째
                chase.phase = "CHASE"
                chase.dead_low = chase.low * (
                    1.0 - self.config.rearm_deeper_pct / 100.0)
                self._clear_retest(chase)
            self._save_chase(code, chase)

    # ── 매수 (공용코어의 주문·복구 절차 복사) ─────────────────────────────
    def _try_entry(
        self,
        code: str,
        name: str,
        point: Dict[str, Any],
        chase: ChaseState,
        now: datetime,
    ) -> str:
        """'BOUGHT'=주문 제출 / 'STOP'=오늘 이 종목 끝 / 'RETRY'=잠시 후 재시도.
        ★[2026-08-01] 재무장 2회 — 같은 종목 2번째 진입은 별도 포지션 칸(code:2)."""
        if self.state.get("recovery_blocked"):
            return "RETRY"
        if len(self._active_positions()) >= self.config.max_slots:
            self._event("BUY_WAIT", code=code, name=name, reason="SLOT_FULL")
            return "RETRY"
        entered_list = [str(c).zfill(6)
                        for c in (self.state.get("entered_codes") or [])]
        entry_no = entered_list.count(code) + 1
        if entry_no > self.config.max_entries_per_code:
            self._event("BUY_BLOCKED", code=code, name=name,
                        reason="CODE_DAILY_ENTRY_LIMIT")
            return "STOP"
        active_same = [p for p in self._active_positions().values()
                       if str(p.get("code")) == code]
        if any(p.get("phase") != "HOLD" for p in active_same):
            return "RETRY"          # 같은 종목 주문이 진행 중 — 겹치지 않게 대기
        if code not in entered_list and len(set(entered_list)) >= self.config.max_daily_codes:
            self._event("BUY_BLOCKED", code=code, name=name,
                        reason="DAILY_CODE_LIMIT")
            return "STOP"
        price = point["price"]
        if price < self.config.min_price_krw:
            self._event("BUY_BLOCKED", code=code, name=name, price=price,
                        reason="PRICE_BELOW_MIN")
            return "STOP"
        if price > self.config.max_price_krw:
            self._event("BUY_BLOCKED", code=code, name=name, price=price,
                        reason="PRICE_ABOVE_CAP_300K")
            return "STOP"
        required = int(Decimal(str(price)) * self.config.quantity)
        if self._active_capital_krw() + required > self.config.capital_krw:
            self._event("BUY_WAIT", code=code, name=name, price=price,
                        reason="CAPITAL_WAIT")
            return "RETRY"

        if getattr(self.broker, "real_session", False):
            if not getattr(self.broker, "buy_allowed", False):
                self._event("BUY_BLOCKED", code=code, name=name,
                            reason="APPROVAL_OR_OFF_FLAG")
                return "RETRY"
            holdings = self.broker.holdings()
            if holdings is None:
                self.state["last_error"] = (
                    f"PREBUY_BALANCE_UNAVAILABLE:{self.broker.last_error}")
                self._event("BUY_WAIT", code=code, name=name,
                            reason=self.state["last_error"])
                return "RETRY"
            held_qty = int((holdings.get(code) or {}).get("qty") or 0)
            ours = sum(int(p.get("qty") or 0) for p in active_same)
            if held_qty > ours:
                # 우리 장부보다 많은 보유 = 다른 경로 물량 — 건드리지 않는다
                self._event("BUY_BLOCKED", code=code, name=name,
                            reason="ACCOUNT_ALREADY_HOLDS_CODE")
                return "STOP"
            open_buy = self.broker.open_orders(code, buy=True)
            if open_buy is None:
                self._event("BUY_WAIT", code=code, name=name,
                            reason="PREBUY_OPEN_ORDER_UNAVAILABLE")
                return "RETRY"
            if open_buy:
                self._event("BUY_BLOCKED", code=code, name=name,
                            reason="ACCOUNT_OPEN_BUY_ALREADY_EXISTS")
                return "STOP"
            known = set(fills_by_order(
                self.config.fills_dir, code, "매수", day=str(self.state["date"])))
            known.update(open_buy)
            known_orders = sorted(known)
        else:
            known_orders = []

        pos_no = entry_no
        while f"{code}:{pos_no}" in self._positions():
            pos_no += 1        # ★[보안점검 높음3] 밤샘 포지션(code:1)과 키 충돌 방지
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
            "reason": "CRASH_LOW_CHASE_CONFIRMED",
        }
        position = {
            "phase": "BUY_PENDING",
            "real": bool(getattr(self.broker, "real_session", False)),
            "code": code,
            "name": name,
            "entry_no": pos_no,
            "qty": 0,
            "entry_price": 0.0,
            "entry_at": "",
            "last_price": price,
            "last_ts": point["ts"].isoformat(),
            "dip_low": chase.low,
            "dip_low_at": chase.low_at,
            "dip_low_reset_steps": chase.reset_steps,
            "dip_first_price": chase.first_price,
            "che_at_observe": chase.che_at_observe,
            "reserved_capital_krw": required,
            "pending": pending,
            "sell_retries": 0,
            "retry_after_epoch": 0.0,
        }
        self.state.setdefault("entered_codes", []).append(code)
        self._positions()[f"{code}:{pos_no}"] = position
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
            self._confirm_entry(position, self.config.quantity, price, now, shadow=True)
        elif status == "OK":
            self._event("BUY_PENDING", code=code, name=name, price=price,
                        quantity=self.config.quantity,
                        reason="OK: exact fill reconciliation")
        elif status in {"TIMEOUT", "UNKNOWN"}:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = f"BUY_{status}_BROKER_TRUTH_REQUIRED"
            self._event("RECOVERY_BLOCKED", code=code, name=name, price=price,
                        reason=self.state["last_error"])
        else:
            position["phase"] = "FAILED"
            self._event("BUY_REJECTED", code=code, name=name, price=price,
                        reason=f"{status}: {getattr(self.broker, 'last_error', '')}")
        self._save()
        return "BOUGHT"

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
        position.update({
            "phase": "HOLD",
            "qty": int(quantity),
            "entry_price": fill_price,
            "entry_at": as_kst(observed_at).isoformat(),
            "entry_day": as_kst(observed_at).strftime("%Y%m%d"),
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
                + f" dip_low={number(position.get('dip_low')):.0f}"
                + f" steps={int(position.get('dip_low_reset_steps') or 0)}"
            ),
        )

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
            self._event("ORDER_NUMBER_CONFIRMED", code=code,
                        name=position.get("name", ""), order_no=current, reason=side)
        elif len(candidates) > 1:
            position["phase"] = "RECOVERY_BLOCKED"
            self.state["recovery_blocked"] = True
            self.state["last_error"] = (
                f"AMBIGUOUS_{side}_ORDER_NUMBERS:{','.join(sorted(candidates))}")
            self._event("ORDER_NUMBER_AMBIGUOUS", code=code,
                        reason=self.state["last_error"])
        return current, fills, open_orders

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
        position["pending"] = None
        self._event("BUY_NOT_CREATED", code=code, name=position["name"],
                    reason="fills/open orders/balance all zero")

    def _daily_ma_rows(self, today: str) -> Mapping[str, Mapping[str, float]]:
        """익일 상승보유용 확정 일봉 이평. 오늘 이후 자료는 읽지 않는다."""
        if self._daily_ma_cache[0] == today:
            return self._daily_ma_cache[1]
        by_code: Dict[str, Dict[str, float]] = {}
        try:
            with self.config.eod_bars_path.open(encoding="utf-8-sig", newline="") as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    if len(code) == 6 and code.isdigit() and day < today and close > 0:
                        by_code.setdefault(code, {})[day] = close
        except OSError:
            self._daily_ma_cache = (today, {})
            return {}
        rows: Dict[str, Dict[str, float]] = {}
        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            rows[code] = {
                "ma5": sum(closes[-5:]) / 5,
                "ma10": sum(closes[-10:]) / 10,
                "ma20": sum(closes[-20:]) / 20,
                "ma20_prev": sum(closes[-21:-1]) / 20,
                "ma5_prev": sum(closes[-6:-1]) / 5,
                "ma10_prev": sum(closes[-11:-1]) / 10,
            }
        self._daily_ma_cache = (today, rows)
        return rows

    def _recent_3min_high(self, code: str) -> float:
        """완성 1분봉 3개의 고가. 자료가 없으면 0으로 상승보유만 보류한다."""
        try:
            mtime = self.config.bars_path.stat().st_mtime
        except OSError:
            return 0.0
        if self._bars_cache[0] != mtime:
            payload = read_json(self.config.bars_path, {})
            source = payload.get("m") if isinstance(payload, dict) and isinstance(
                payload.get("m"), dict) else payload
            self._bars_cache = (mtime, source if isinstance(source, dict) else {})
        previous = ((self._bars_cache[1].get(str(code).zfill(6)) or {}).get("prev") or [])
        highs = [number(bar[1]) for bar in previous[-3:]
                 if isinstance(bar, (list, tuple)) and len(bar) >= 2
                 and number(bar[1]) > 0]
        return max(highs) if len(highs) == 3 else 0.0

    def _morning_daily_ma_permit(self, code: str, price: float, today: str) -> bool:
        """★[MA3-COMMON 2026-08-03] 3분봉 5/10/20선 + 매수세 우위로 통일(S01~S06 공통).

        종전은 일봉 5선>10선·20선 우상향 + 3분봉 고가≥일봉 5선. 일봉 5선이 장중
        가격보다 한참 아래인 종목은 상승보유가 영구 참이 되어 트레일을 막았다.
        today 인자는 호출부 호환을 위해 남긴다(3분봉 판정에는 쓰지 않는다).
        되돌리기: backup\\strategy_06_crash_low_chase_v1_20260803_ma3wire.py
        """
        return ma3_rider_permit(
            code, price,
            buy_side=self._morning_buy_side(code, time.time()),
        )

    def _morning_buy_side(self, code: str, epoch_now: float):
        """S06 매수세 우위 — self.flows 의 거래대금 누적으로 10s/30s 속도를 낸다.

        S06 은 공용코어를 상속하지 않아 FlowWindows 가 없다. 같은 자료(누적 매수/
        매도 대금)를 자체 flows 에서 뽑아 쓴다. 자료 부족이면 None(판정 불가)
        → 상승보유 없음 → 트레일 정상 작동.
        """
        flow = self.flows.get(str(code).zfill(6))
        if not flow or len(flow) < 2:
            return None

        def rate(window_sec: float):
            rows = [r for r in flow if epoch_now - r[0] <= window_sec]
            if len(rows) < 2:
                return None
            span = rows[-1][0] - rows[0][0]
            if span < 3.0:
                return None
            return (max(0.0, rows[-1][1] - rows[0][1]) / span,
                    max(0.0, rows[-1][2] - rows[0][2]) / span)

        recent, base = rate(10.0), rate(30.0)
        if not recent or not base:
            return None
        return ma3_buy_side_alive(recent[0], base[0], recent[1], base[1])

    @staticmethod
    def _morning_trail_drop(entry: float, peak: float) -> float:
        peak_return = (peak / entry - 1.0) * 100.0 if entry > 0 else 0.0
        if peak_return >= 6.0:
            return 2.0
        if peak_return >= 3.0:
            return 1.5
        if peak_return >= 1.0:
            return 1.0
        return 0.0

    def _morning_exit_reason(
        self,
        position: Dict[str, Any],
        point: Optional[Mapping[str, Any]],
        now: datetime,
    ) -> Optional[str]:
        if now.time() < self.config.morning_sell_start or point is None:
            return None
        price = number(point.get("price"))
        today = now.strftime("%Y%m%d")
        position["morning_daily_ma_permit"] = self._morning_daily_ma_permit(
            str(position.get("code")), price, today)
        last_eval = str(position.get("morning_last_trail_eval_at") or "")
        if last_eval and (
            now - parse_dt(last_eval, now)
        ).total_seconds() < self.config.morning_trail_eval_interval_sec:
            return None
        position["morning_last_trail_eval_at"] = now.isoformat(timespec="seconds")
        entry = number(position.get("entry_price"))
        peak = number(position.get("morning_peak_price"))
        threshold = self._morning_trail_drop(entry, peak)
        if threshold <= 0 or peak <= 0:
            return None
        peak_drop = (peak - price) / peak * 100.0
        if peak_drop < threshold:
            return None
        if number(position.get("morning_peak_buy_ratio"), -1.0) >= 0.90:
            return None
        return (
            f"NEXT_MORNING_PROFIT_TRAIL peak_drop={peak_drop:.2f}% "
            f"threshold={threshold:.1f}%"
        )

    def _update_morning_peak(
        self, position: Dict[str, Any], point: Mapping[str, Any], today: str,
    ) -> None:
        if str(position.get("morning_peak_day") or "") != today:
            position.update({
                "morning_peak_day": today,
                "morning_peak_price": 0.0,
                "morning_peak_at": "",
                "morning_peak_base_buy": None,
                "morning_peak_base_sell": None,
                "morning_peak_buy_ratio": None,
                "morning_last_trail_eval_at": "",
            })
        price = number(point.get("price"))
        buy_cum = number(point.get("buy_money_cum"), -1.0)
        sell_cum = number(point.get("sell_money_cum"), -1.0)
        if price > number(position.get("morning_peak_price")):
            position["morning_peak_price"] = price
            position["morning_peak_at"] = point["ts"].strftime("%H:%M:%S")
            position["morning_peak_base_buy"] = buy_cum if buy_cum >= 0 else None
            position["morning_peak_base_sell"] = sell_cum if sell_cum >= 0 else None
            position["morning_peak_buy_ratio"] = None
            return
        base_buy = position.get("morning_peak_base_buy")
        base_sell = position.get("morning_peak_base_sell")
        if buy_cum < 0 or sell_cum < 0 or base_buy is None or base_sell is None:
            position["morning_peak_buy_ratio"] = None
            return
        delta_buy = max(0.0, buy_cum - number(base_buy))
        delta_sell = max(0.0, sell_cum - number(base_sell))
        total = delta_buy + delta_sell
        position["morning_peak_buy_ratio"] = delta_buy / total if total > 0 else None
        position["morning_peak_flow"] = {
            "delta_buy": round(delta_buy, 1), "delta_sell": round(delta_sell, 1),
        }

    # ── 매도 (①당일 +10% 익절 ②익일 상승보유·꼭지점 매도) ─────────────
    def _evaluate_exit(
        self,
        position: Dict[str, Any],
        now: datetime,
    ) -> None:
        """당일 +10%는 유지하고, 익일은 상승보유·꼭지점 매도를 쓴다."""
        if time.time() < number(position.get("retry_after_epoch")):
            return
        today = now.strftime("%Y%m%d")
        entry_day = str(position.get("entry_day") or "")[:8]
        if not entry_day:
            entry_day = str(position.get("entry_at") or "")[:10].replace("-", "")
        overnight = bool(entry_day) and entry_day < today
        point = self._snapshot_point(position["code"], now)
        if point is not None:
            position["last_price"] = point["price"]
            position["last_ts"] = point["ts"].isoformat()
            self._update_excursion(position, point["price"], point["ts"])
        if overnight:
            if point is not None and now.time() >= self.config.morning_sell_start:
                self._update_morning_peak(position, point, today)
            reason = self._morning_exit_reason(position, point, now)
            if reason:
                self._start_sell(position, now, reason, point)
            return
        if point is None:
            return
        entry_price = number(position.get("entry_price"))
        if entry_price <= 0:
            return
        return_pct = (point["price"] / entry_price - 1.0) * 100.0
        if return_pct >= self.config.tp_pct:
            self._start_sell(
                position, now,
                f"TAKE_PROFIT_{self.config.tp_pct:.0f} {return_pct:.2f}%",
                point,
            )

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
        # ★[2026-08-01 보안점검 치명2] 같은 종목 매도 직렬화 — 다른 포지션의 매도가
        #   진행 중이면 3초 뒤 재시도(주문번호 입양 오인·멱등키 충돌 방지).
        for other in self._active_positions().values():
            if (other is not position
                    and str(other.get("code")) == str(position.get("code"))
                    and other.get("phase") == "SELL_PENDING"):
                position["retry_after_epoch"] = time.time() + 3
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
        if available <= 0:
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_WAIT", code=position["code"], name=position["name"],
                        reason="BROKER_AVAILABLE_QTY_ZERO")
            return
        quantity = min(int(position.get("qty") or 0), available)
        if quantity <= 0:
            position["retry_after_epoch"] = time.time() + 5
            self._event("SELL_WAIT", code=position["code"], name=position["name"],
                        reason="BROKER_AVAILABLE_QTY_ZERO")
            return
        known = set(fills_by_order(
            self.config.fills_dir, position["code"], "매도",
            day=str(self.state["date"])))
        open_sell = self.broker.open_orders(position["code"], buy=False)
        if open_sell is None:
            position["retry_after_epoch"] = time.time() + 5
            return
        known.update(open_sell)
        retry = int(position.get("sell_retries") or 0) + 1
        key = (
            f"{self.config.strategy_slug}:"
            f"{self.state['date']}:sell:{position['code']}:"
            f"e{int(position.get('entry_no') or 1)}:{retry}"
        )
        position["sell_retries"] = retry
        position["phase"] = "SELL_PENDING"
        position["pending"] = {
            "side": "SELL",
            "idempotency_key": key,
            "known_orders": sorted(known),
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
        position.update({
            "phase": "CLOSED",
            "qty": 0,
            "pending": None,
            "exit_price": float(exit_price),
            "exit_at": exit_at.isoformat(timespec="seconds"),
            "exit_reason": reason,
            "gross_return_pct": float(gross),
            "estimated_net_return_pct_before_slippage": float(net),
        })
        self._refresh_recovery_blocked()
        self._event(
            "SHADOW_SELL" if shadow else "SELL_CONFIRMED",
            code=position["code"], name=position["name"],
            price=float(exit_price), reason=(
                f"{reason} gross={gross:.3f}% net_before_slippage={net:.3f}%"
                f" mfe={number(position.get('mfe_pct')):.3f}%"
                f" mae={number(position.get('mae_pct')):.3f}%"
                f" dip_steps={int(position.get('dip_low_reset_steps') or 0)}"
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
            if position.get("entry_at"):
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
            if pending.get("side") == "SELL" or position.get("entry_at"):
                self._confirm_exit(
                    position,
                    number(position.get("last_price")),
                    "RECOVERY_FLAT_CONFIRMED",
                )
            else:
                position["phase"] = "FAILED"
                position["qty"] = 0
                self._event("RECOVERY_BUY_NOT_CREATED", code=code)
            self._refresh_recovery_blocked()
            if not self.state["recovery_blocked"]:
                self.state["last_error"] = ""

    # ── 본 루프 ──────────────────────────────────────────────────────────
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
        if self.config.entry_start <= now.time() < self.config.entry_end:
            codes, block = self._universe(now)
            if block:
                if block != self.state.get("last_universe_block"):
                    self.state["last_universe_block"] = block
                    self.log.warning("유니버스 차단 — %s (신규 진입 중단)", block)
            else:
                self.state["last_universe_block"] = ""
                for code in codes:
                    self._chase_tick(code, now)
        self._cleanup_terminal()
        self._save()
        return self.state

    def run(self, *, once: bool = False) -> int:
        self.log.info(
            "%s start mode=%s qty=%d slots=%d capital=%d drop=-%.1f%% "
            "rebound=+%.1f%% cap=+%.1f%% observe=%.0fs",
            self.config.strategy_label,
            getattr(self.broker, "mode", "UNKNOWN"),
            self.config.quantity,
            self.config.max_slots,
            self.config.capital_krw,
            self.config.drop_pct,
            self.config.rebound_pct,
            self.config.chase_cap_pct,
            self.config.observe_sec,
        )
        while True:
            now = kst_now()
            self.tick(now)
            pending = any(
                str(position.get("phase") or "") in {"BUY_PENDING", "SELL_PENDING"}
                for position in self._active_positions().values()
            )
            if once:
                return 0
            # ★[2026-08-01 보안점검 중간5] RECOVERY_BLOCKED 는 프로세스를 붙잡지
            #   않는다(브로커가 죽은 주말·야간에 좀비가 되어 월요일 기동을 막던 구멍).
            #   상태는 파일에 남아 다음 기동의 _startup_reconcile 이 잇는다.
            if now.weekday() >= 5:
                return 0
            if now.time() >= day_time(16, 0):
                return 0
            if now.time() >= self.config.process_end and not pending:
                return 0
            time.sleep(max(0.2, self.config.loop_sec))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = Config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 06 is already running.", flush=True)
        return 0
    try:
        return Strategy06Engine(config).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

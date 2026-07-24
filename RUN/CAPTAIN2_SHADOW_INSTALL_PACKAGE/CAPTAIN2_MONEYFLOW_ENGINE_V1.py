# -*- coding: utf-8 -*-
"""
CAPTAIN 2.0 — RESET 기반 Money Flow Trading Engine

목적
----
가격 위치(바닥/눌림/횡보/돌파/신고가)와 무관하게 거래대금이 강하게 유입되는
순간을 감지하고, 실제 저점 시점으로 소급 RESET한 뒤 RESET 이후의 매수/매도
우위와 가격 반응을 초 단위로 측정한다.

중요 안전 원칙
--------------
1) 기본값은 SHADOW(주문 0)이다. CAPTAIN2_LIVE=YES를 명시해야만 주문 경로가 열린다.
2) 5일선·10일선은 매수/매도 하드 조건으로 사용하지 않는다.
3) 새 TR 및 새 SetRealReg를 호출하지 않는다. 기존 JSON 스냅샷만 읽는다.
4) 키움의 장중 누적거래량(cum_vol)과 누적 체결강도(che_str)를 RESET 시점과
   현재 시점에서 역산해 구간 매수/매도 체결량을 '추정'한다.
5) 실전 전환 전 최소 수 거래일 SHADOW 검증이 필요하다.

입력
----
C:\\stock_bot\\IPC\\live_micro_snapshot.json
C:\\stock_bot\\data\\micro_rank_board.json
C:\\stock_bot\\data\\_code_name_cache.json (선택)

출력
----
C:\\stock_bot\\data\\captain2_state.json
C:\\stock_bot\\data\\shadow\\captain2_events_YYYYMMDD.csv
C:\\stock_bot\\LOG\\captain2_moneyflow.log
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import signal
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


# =============================================================================
# 설정
# =============================================================================

@dataclass(frozen=True)
class Config:
    snapshot_path: Path = Path(os.environ.get(
        "CAPTAIN2_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    micro_board_path: Path = Path(os.environ.get(
        "CAPTAIN2_MICRO_BOARD", r"C:\stock_bot\data\micro_rank_board.json"))
    name_cache_path: Path = Path(os.environ.get(
        "CAPTAIN2_NAME_CACHE", r"C:\stock_bot\data\_code_name_cache.json"))
    state_path: Path = Path(os.environ.get(
        "CAPTAIN2_STATE", r"C:\stock_bot\data\captain2_state.json"))
    event_dir: Path = Path(os.environ.get(
        "CAPTAIN2_EVENT_DIR", r"C:\stock_bot\data\shadow"))
    log_path: Path = Path(os.environ.get(
        "CAPTAIN2_LOG", r"C:\stock_bot\LOG\captain2_moneyflow.log"))
    manual_block_path: Path = Path(os.environ.get(
        "CAPTAIN2_MANUAL_BLOCK", r"C:\stock_bot\config\manual_buy_block.flag"))

    live: bool = os.environ.get("CAPTAIN2_LIVE", "NO").strip().upper() == "YES"
    qty_fixed: int = int(os.environ.get("CAPTAIN2_QTY_FIX", "1"))
    loop_sec: float = float(os.environ.get("CAPTAIN2_LOOP_SEC", "1.0"))
    entry_start: str = os.environ.get("CAPTAIN2_ENTRY_START", "0900")
    entry_end: str = os.environ.get("CAPTAIN2_ENTRY_END", "1520")
    force_exit: str = os.environ.get("CAPTAIN2_FORCE_EXIT", "1525")
    program_end: str = os.environ.get("CAPTAIN2_END", "1530")

    # FLOW 감지. 기존 micro_rank_engine의 money_start_raw/START를 우선 사용한다.
    min_burst_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BURST", "3.0"))
    min_money_add_5s: float = float(os.environ.get("CAPTAIN2_MIN_ADD5S", "0"))

    # 저점 탐색/확정
    low_search_max_sec: float = float(os.environ.get("CAPTAIN2_LOW_SEARCH_MAX", "5.0"))
    low_no_new_sec: float = float(os.environ.get("CAPTAIN2_LOW_NO_NEW_SEC", "2.0"))
    low_confirm_ticks: int = int(os.environ.get("CAPTAIN2_LOW_CONFIRM_TICKS", "1"))

    # RESET 후 초기 진입 확인. 절대 체결강도보다 RESET 이후 상대 매수 우위를 주축으로 둔다.
    buy_min_elapsed_sec: float = float(os.environ.get("CAPTAIN2_BUY_MIN_SEC", "2.0"))
    buy_max_elapsed_sec: float = float(os.environ.get("CAPTAIN2_BUY_MAX_SEC", "6.0"))
    min_reset_exec_volume: float = float(os.environ.get("CAPTAIN2_MIN_RESET_VOL", "1"))
    min_buy_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BUY_RATIO", "0.58"))
    min_buy_sell_ratio: float = float(os.environ.get("CAPTAIN2_MIN_BS_RATIO", "1.35"))
    buy_confirm_sec: float = float(os.environ.get("CAPTAIN2_BUY_CONFIRM_SEC", "2.0"))
    min_price_ticks: int = int(os.environ.get("CAPTAIN2_MIN_PRICE_TICKS", "1"))

    # 보유/경계/청산
    hard_stop_pct: float = float(os.environ.get("CAPTAIN2_STOP_PCT", "-3.0"))
    watch_buy_ratio: float = float(os.environ.get("CAPTAIN2_WATCH_BUY_RATIO", "0.52"))
    sell_buy_ratio: float = float(os.environ.get("CAPTAIN2_SELL_BUY_RATIO", "0.48"))
    watch_confirm_sec: float = float(os.environ.get("CAPTAIN2_WATCH_CONFIRM_SEC", "2.0"))
    structure_lookback_sec: float = float(os.environ.get("CAPTAIN2_STRUCTURE_SEC", "5.0"))
    max_positions: int = int(os.environ.get("CAPTAIN2_MAX_POSITIONS", "1"))
    max_entries_day: int = int(os.environ.get("CAPTAIN2_MAX_ENTRIES", "3"))
    cooldown_sec: float = float(os.environ.get("CAPTAIN2_COOLDOWN_SEC", "20"))

    stale_snapshot_sec: float = float(os.environ.get("CAPTAIN2_STALE_SNAPSHOT_SEC", "3"))
    stale_board_sec: float = float(os.environ.get("CAPTAIN2_STALE_BOARD_SEC", "5"))


# =============================================================================
# 모델
# =============================================================================

class Phase(str, Enum):
    IDLE = "IDLE"
    LOW_SEARCH = "LOW_SEARCH"
    RESET = "RESET"
    BUY_READY = "BUY_READY"
    HOLD = "HOLD"
    WATCH = "WATCH"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass
class MarketPoint:
    ts: datetime
    code: str
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float = 0.0
    bid_tot: float = 0.0
    imb: float = 0.0
    money_add_5s: float = 0.0
    money_speed_5s: float = 0.0
    money_speed_10s: float = 0.0
    money_speed_30s: float = 0.0
    money_start: bool = False
    money_start_raw: bool = False


@dataclass
class CandidateLow:
    ts: datetime
    price: float
    cum_vol: float
    che_str: float
    ask_tot: float
    bid_tot: float
    imb: float
    est_buy_cum: float
    est_sell_cum: float


@dataclass
class FlowState:
    code: str
    name: str = ""
    phase: Phase = Phase.IDLE
    flow_detect_ts: Optional[datetime] = None
    candidate_low: Optional[CandidateLow] = None
    last_low_update_ts: Optional[datetime] = None
    reset_id: str = ""
    reset_ts: Optional[datetime] = None
    reset_price: float = 0.0
    reset_buy_cum: float = 0.0
    reset_sell_cum: float = 0.0
    reset_cum_vol: float = 0.0
    reset_che_str: float = 0.0
    reset_ask_tot: float = 0.0
    reset_bid_tot: float = 0.0
    reset_imb: float = 0.0
    reset_high: float = 0.0
    reset_low: float = 0.0
    structure_low: float = 0.0
    buy_exec_vol: float = 0.0
    sell_exec_vol: float = 0.0
    buy_ratio: float = 0.5
    buy_sell_ratio: float = 1.0
    price_response_pct: float = 0.0
    dominance_since: Optional[datetime] = None
    watch_since: Optional[datetime] = None
    entry_ts: Optional[datetime] = None
    entry_price: float = 0.0
    qty: int = 0
    peak_price: float = 0.0
    exit_ts: Optional[datetime] = None
    exit_price: float = 0.0
    exit_reason: str = ""
    last_update_ts: Optional[datetime] = None
    anomaly_count: int = 0
    terminal_ts: Optional[datetime] = None
    rearm_ready: bool = False
    recent_prices: list[Tuple[float, float]] = field(default_factory=list)


# =============================================================================
# 유틸리티
# =============================================================================

def setup_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("captain2")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(cfg.log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def parse_ts(value: Any, fallback: Optional[datetime] = None) -> datetime:
    fallback = fallback or datetime.now()
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%H:%M:%S.%f", "%H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt.startswith("%H"):
                return fallback.replace(hour=dt.hour, minute=dt.minute, second=dt.second, microsecond=dt.microsecond)
            return dt
        except ValueError:
            continue
    return fallback


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def stable_json_read(path: Path, retries: int = 3, delay: float = 0.03) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for _ in range(retries):
        try:
            raw1 = path.read_bytes()
            time.sleep(0.005)
            raw2 = path.read_bytes()
            if raw1 != raw2:
                time.sleep(delay)
                continue
            return json.loads(raw2.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"JSON 읽기 실패: {path}: {last_error}")


def krx_tick_size(price: float) -> float:
    """국내 주식 일반 호가단위 근사. 시장/ETF 예외는 추후 메타데이터 연동 필요."""
    if price < 2_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 20_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 200_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


def estimate_cumulative_sides(cum_vol: float, che_str: float) -> Tuple[float, float]:
    """
    누적 체결강도 = 누적 매수체결량 / 누적 매도체결량 * 100 이라는 전제에서
    누적 총거래량을 매수/매도로 역산한다.

    이 값은 RESET 구간의 상대 우위 측정을 위한 추정치이며 실제 틱 방향 집계가 아니다.
    """
    total = max(0.0, cum_vol)
    if total <= 0:
        return 0.0, 0.0
    ratio = max(0.0001, che_str / 100.0)
    sell = total / (1.0 + ratio)
    buy = total - sell
    return buy, sell


def state_json(state: FlowState) -> Dict[str, Any]:
    data = asdict(state)
    data["phase"] = state.phase.value
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if state.candidate_low:
        cl = asdict(state.candidate_low)
        cl["ts"] = state.candidate_low.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        data["candidate_low"] = cl
    return data


# =============================================================================
# 입력 어댑터
# =============================================================================

class DataFeed:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.log = logger
        self.names = self._load_names()

    def _load_names(self) -> Dict[str, str]:
        try:
            data = stable_json_read(self.cfg.name_cache_path)
            raw = data.get("map", data)
            return {str(k).zfill(6): str(v) for k, v in raw.items()}
        except Exception:
            return {}

    def read_points(self) -> Dict[str, MarketPoint]:
        snap = stable_json_read(self.cfg.snapshot_path)
        board = stable_json_read(self.cfg.micro_board_path)
        now = datetime.now()

        board_ts = parse_ts(board.get("ts"), now)
        if abs((now - board_ts).total_seconds()) > self.cfg.stale_board_sec:
            raise RuntimeError(f"micro board stale: {(now - board_ts).total_seconds():.1f}s")

        board_items = {
            str(x.get("code") or "").zfill(6): x
            for x in (board.get("all_items") or [])
            if x.get("code")
        }
        points: Dict[str, MarketPoint] = {}
        for raw_code, item in (snap.get("codes") or {}).items():
            code = str(raw_code).zfill(6)
            price = safe_float(item.get("cur"))
            cum_vol = safe_float(item.get("cum_vol"))
            che_str = safe_float(item.get("che_str"))
            if price <= 0 or cum_vol < 0:
                continue
            ts = parse_ts(item.get("ts"), now)
            if abs((now - ts).total_seconds()) > self.cfg.stale_snapshot_sec:
                continue
            b = board_items.get(code, {})
            points[code] = MarketPoint(
                ts=ts,
                code=code,
                price=price,
                cum_vol=cum_vol,
                che_str=che_str,
                ask_tot=safe_float(item.get("ask_tot")),
                bid_tot=safe_float(item.get("bid_tot")),
                imb=safe_float(item.get("imb")),
                money_add_5s=safe_float(b.get("money_add_5s")),
                money_speed_5s=safe_float(b.get("money_speed_5s")),
                money_speed_10s=safe_float(b.get("money_speed_10s")),
                money_speed_30s=safe_float(b.get("money_speed_30s")),
                money_start=bool(b.get("money_start")),
                money_start_raw=bool(b.get("money_start_raw")),
            )
        return points


# =============================================================================
# 주문 어댑터 — 기본 SHADOW
# =============================================================================

class ExecutionAdapter:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.log = logger
        self.client = None
        self.account = ""

    def connect(self) -> bool:
        if not self.cfg.live:
            self.log.info("SHADOW 모드: 주문 0")
            return True
        if self.cfg.manual_block_path.exists():
            self.log.error("manual_buy_block.flag 존재: LIVE 연결 거부")
            return False
        try:
            from broker_client import BrokerClient, is_broker_alive  # type: ignore
            if not is_broker_alive():
                self.log.error("broker gateway 비정상")
                return False
            self.client = BrokerClient()
            info = self.client.account_info("ACCNO")
            accounts = (info.get("data") or {}).get("accounts") or []
            if isinstance(accounts, str):
                accounts = [x for x in accounts.split(";") if x]
            self.account = accounts[0] if accounts else os.environ.get("SAFEPLUS_ACCOUNT", "")
            if not self.account:
                self.log.error("계좌번호 없음")
                return False
            return True
        except Exception:
            self.log.exception("브로커 연결 실패")
            return False

    def buy(self, code: str, qty: int) -> str:
        if self.cfg.live and self.cfg.manual_block_path.exists():
            self.log.warning("BUY 차단 플래그: %s", code)
            return "BLOCKED"
        if not self.cfg.live:
            self.log.info("[SHADOW] BUY %s x%d", code, qty)
            return "SHADOW"
        try:
            result = self.client.send_order_real(
                idempotency_key=f"captain2_buy_{code}_{uuid.uuid4()}",
                account=self.account,
                code=code,
                qty=int(qty),
                order_type=1,
                price=0,
                hoga_gb="06",
                rqname=f"CAPTAIN2_BUY_{code}",
                screen_no="9750",
            )
            return str((result or {}).get("status") or "NONE").upper()
        except Exception:
            self.log.exception("BUY 주문 실패 %s", code)
            return "ERROR"

    def sell(self, code: str, qty: int) -> str:
        if not self.cfg.live:
            self.log.info("[SHADOW] SELL %s x%d", code, qty)
            return "SHADOW"
        try:
            result = self.client.send_order_real(
                idempotency_key=f"captain2_sell_{code}_{uuid.uuid4()}",
                account=self.account,
                code=code,
                qty=int(qty),
                order_type=2,
                price=0,
                hoga_gb="06",
                rqname=f"CAPTAIN2_SELL_{code}",
                screen_no="9750",
            )
            return str((result or {}).get("status") or "NONE").upper()
        except Exception:
            self.log.exception("SELL 주문 실패 %s", code)
            return "ERROR"


# =============================================================================
# 엔진
# =============================================================================

class Captain2Engine:
    EVENT_COLUMNS = [
        "ts", "code", "name", "event", "phase", "price", "reset_price",
        "elapsed_sec", "money_add_5s", "money_speed_5s", "money_speed_10s",
        "money_speed_30s", "burst_ratio", "buy_exec_vol", "sell_exec_vol",
        "buy_ratio", "buy_sell_ratio", "price_response_pct", "structure_low",
        "che_str", "ask_tot", "bid_tot", "imb", "reason",
    ]

    def __init__(self, cfg: Config, feed: DataFeed, execution: ExecutionAdapter, logger: logging.Logger):
        self.cfg = cfg
        self.feed = feed
        self.execution = execution
        self.log = logger
        self.states: Dict[str, FlowState] = {}
        self.entries_today = 0
        self.last_entry_time = 0.0
        self.running = True
        self.event_path = cfg.event_dir / f"captain2_events_{datetime.now():%Y%m%d}.csv"

    def stop(self, *_: Any) -> None:
        self.running = False

    def _event(self, point: MarketPoint, state: FlowState, event: str, reason: str = "") -> None:
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.event_path.exists()
        elapsed = (point.ts - state.reset_ts).total_seconds() if state.reset_ts else 0.0
        burst = point.money_speed_5s / max(point.money_speed_30s, 1e-9) if point.money_speed_30s > 0 else 0.0
        row = {
            "ts": point.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "code": point.code,
            "name": state.name,
            "event": event,
            "phase": state.phase.value,
            "price": point.price,
            "reset_price": state.reset_price,
            "elapsed_sec": round(elapsed, 3),
            "money_add_5s": point.money_add_5s,
            "money_speed_5s": point.money_speed_5s,
            "money_speed_10s": point.money_speed_10s,
            "money_speed_30s": point.money_speed_30s,
            "burst_ratio": round(burst, 4),
            "buy_exec_vol": round(state.buy_exec_vol, 3),
            "sell_exec_vol": round(state.sell_exec_vol, 3),
            "buy_ratio": round(state.buy_ratio, 4),
            "buy_sell_ratio": round(state.buy_sell_ratio, 4),
            "price_response_pct": round(state.price_response_pct, 4),
            "structure_low": state.structure_low,
            "che_str": point.che_str,
            "ask_tot": point.ask_tot,
            "bid_tot": point.bid_tot,
            "imb": point.imb,
            "reason": reason,
        }
        try:
            with self.event_path.open("a", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.EVENT_COLUMNS)
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            self.log.exception("이벤트 CSV 기록 실패")

    def _is_surge(self, p: MarketPoint) -> bool:
        if p.money_start or p.money_start_raw:
            return True
        if p.money_add_5s <= self.cfg.min_money_add_5s:
            return False
        if p.money_speed_30s <= 0:
            return False
        burst = p.money_speed_5s / max(p.money_speed_30s, 1e-9)
        return burst >= self.cfg.min_burst_ratio and p.money_speed_5s >= p.money_speed_10s

    def _start_low_search(self, p: MarketPoint, state: FlowState) -> None:
        buy_cum, sell_cum = estimate_cumulative_sides(p.cum_vol, p.che_str)
        low = CandidateLow(
            ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
            ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
            est_buy_cum=buy_cum, est_sell_cum=sell_cum,
        )
        state.phase = Phase.LOW_SEARCH
        state.flow_detect_ts = p.ts
        state.candidate_low = low
        state.last_low_update_ts = p.ts
        state.last_update_ts = p.ts
        self._event(p, state, "FLOW_DETECTED")

    def _update_low_search(self, p: MarketPoint, state: FlowState) -> None:
        assert state.candidate_low is not None
        if p.price < state.candidate_low.price:
            buy_cum, sell_cum = estimate_cumulative_sides(p.cum_vol, p.che_str)
            state.candidate_low = CandidateLow(
                ts=p.ts, price=p.price, cum_vol=p.cum_vol, che_str=p.che_str,
                ask_tot=p.ask_tot, bid_tot=p.bid_tot, imb=p.imb,
                est_buy_cum=buy_cum, est_sell_cum=sell_cum,
            )
            state.last_low_update_ts = p.ts
            self._event(p, state, "LOW_UPDATED")
            return

        search_age = (p.ts - (state.flow_detect_ts or p.ts)).total_seconds()
        no_new_age = (p.ts - (state.last_low_update_ts or p.ts)).total_seconds()
        tick = krx_tick_size(state.candidate_low.price)
        price_confirmed = p.price >= state.candidate_low.price + self.cfg.low_confirm_ticks * tick

        if price_confirmed and no_new_age >= self.cfg.low_no_new_sec:
            self._confirm_reset(p, state)
            return
        if search_age >= self.cfg.low_search_max_sec:
            state.phase = Phase.FAILED
            state.terminal_ts = p.ts
            state.rearm_ready = False
            self._event(p, state, "LOW_SEARCH_FAILED", "저점 상승전환 미확인")

    def _confirm_reset(self, p: MarketPoint, state: FlowState) -> None:
        low = state.candidate_low
        assert low is not None
        state.phase = Phase.RESET
        state.reset_id = uuid.uuid4().hex[:12]
        state.reset_ts = low.ts
        state.reset_price = low.price
        state.reset_buy_cum = low.est_buy_cum
        state.reset_sell_cum = low.est_sell_cum
        state.reset_cum_vol = low.cum_vol
        state.reset_che_str = low.che_str
        state.reset_ask_tot = low.ask_tot
        state.reset_bid_tot = low.bid_tot
        state.reset_imb = low.imb
        state.reset_high = max(low.price, p.price)
        state.reset_low = low.price
        state.structure_low = low.price
        state.dominance_since = None
        state.watch_since = None
        state.recent_prices.clear()
        self._update_reset_metrics(p, state)
        self._event(p, state, "RESET_CONFIRMED", "실제 저점 시점으로 소급")

    def _update_reset_metrics(self, p: MarketPoint, state: FlowState) -> None:
        buy_cum, sell_cum = estimate_cumulative_sides(p.cum_vol, p.che_str)
        buy_delta = buy_cum - state.reset_buy_cum
        sell_delta = sell_cum - state.reset_sell_cum
        if buy_delta < -1e-6 or sell_delta < -1e-6:
            state.anomaly_count += 1
            buy_delta = max(0.0, buy_delta)
            sell_delta = max(0.0, sell_delta)
        state.buy_exec_vol = buy_delta
        state.sell_exec_vol = sell_delta
        total = buy_delta + sell_delta
        state.buy_ratio = buy_delta / total if total > 0 else 0.5
        state.buy_sell_ratio = buy_delta / max(sell_delta, 1e-9) if total > 0 else 1.0
        state.reset_high = max(state.reset_high, p.price)
        state.reset_low = min(state.reset_low, p.price)
        state.price_response_pct = (p.price / state.reset_price - 1.0) * 100 if state.reset_price > 0 else 0.0
        state.last_update_ts = p.ts

        elapsed_epoch = p.ts.timestamp()
        state.recent_prices.append((elapsed_epoch, p.price))
        cutoff = elapsed_epoch - self.cfg.structure_lookback_sec
        state.recent_prices = [(t, px) for t, px in state.recent_prices if t >= cutoff]
        if state.recent_prices:
            state.structure_low = min(px for _, px in state.recent_prices)

    def _buy_signal(self, p: MarketPoint, state: FlowState) -> Tuple[bool, str]:
        if not state.reset_ts:
            return False, "RESET 없음"
        elapsed = (p.ts - state.reset_ts).total_seconds()
        if elapsed < self.cfg.buy_min_elapsed_sec:
            return False, "최소 관찰시간 미달"
        if elapsed > self.cfg.buy_max_elapsed_sec:
            return False, "진입 확인창 초과"
        total = state.buy_exec_vol + state.sell_exec_vol
        tick = krx_tick_size(state.reset_price)
        price_ok = p.price >= state.reset_price + self.cfg.min_price_ticks * tick
        dominance_ok = (
            total >= self.cfg.min_reset_exec_volume
            and state.buy_ratio >= self.cfg.min_buy_ratio
            and state.buy_sell_ratio >= self.cfg.min_buy_sell_ratio
        )
        if dominance_ok:
            if state.dominance_since is None:
                state.dominance_since = p.ts
            duration = (p.ts - state.dominance_since).total_seconds()
        else:
            state.dominance_since = None
            duration = 0.0
        if dominance_ok and price_ok and duration >= self.cfg.buy_confirm_sec:
            return True, f"매수우위 {state.buy_ratio:.1%}/{state.buy_sell_ratio:.2f}배 {duration:.1f}초"
        return False, "매수우위 또는 가격반응 미확인"

    def _can_open(self) -> Tuple[bool, str]:
        if self.cfg.live and self.cfg.manual_block_path.exists():
            return False, "manual_buy_block"
        open_count = sum(1 for s in self.states.values() if s.phase in (Phase.HOLD, Phase.WATCH))
        if open_count >= self.cfg.max_positions:
            return False, "최대 보유수"
        if self.entries_today >= self.cfg.max_entries_day:
            return False, "일 최대 진입수"
        if time.time() - self.last_entry_time < self.cfg.cooldown_sec:
            return False, "전역 쿨다운"
        return True, "OK"

    def _open(self, p: MarketPoint, state: FlowState, reason: str) -> None:
        ok, why = self._can_open()
        if not ok:
            self._event(p, state, "BUY_BLOCKED", why)
            return
        status = self.execution.buy(p.code, self.cfg.qty_fixed)
        if status not in ("OK", "TIMEOUT", "SHADOW"):
            self._event(p, state, "BUY_ERROR", status)
            return
        state.phase = Phase.HOLD
        state.entry_ts = p.ts
        state.entry_price = p.price
        state.qty = self.cfg.qty_fixed
        state.peak_price = p.price
        state.watch_since = None
        self.entries_today += 1
        self.last_entry_time = time.time()
        self._event(p, state, "BUY", reason)
        self.log.info("BUY %s %s @%.0f x%d | %s", state.name, p.code, p.price, state.qty, reason)

    def _hold_or_sell(self, p: MarketPoint, state: FlowState) -> None:
        previous_structure_low = state.structure_low
        self._update_reset_metrics(p, state)
        if p.price > state.peak_price:
            state.peak_price = p.price

        ret_pct = (p.price / state.entry_price - 1.0) * 100 if state.entry_price > 0 else 0.0
        hm = p.ts.strftime("%H%M")
        if ret_pct <= self.cfg.hard_stop_pct:
            self._close(p, state, f"HARD_STOP {ret_pct:.2f}%")
            return
        if hm >= self.cfg.force_exit:
            self._close(p, state, "TIME_EXIT")
            return

        structure_broken = previous_structure_low > 0 and p.price < previous_structure_low
        flow_weak = state.buy_ratio < self.cfg.watch_buy_ratio
        sell_dominant = state.buy_ratio <= self.cfg.sell_buy_ratio

        if state.phase == Phase.HOLD:
            if flow_weak:
                state.phase = Phase.WATCH
                state.watch_since = p.ts
                self._event(p, state, "WATCH_START", f"buy_ratio={state.buy_ratio:.1%}")
            return

        if state.phase == Phase.WATCH:
            if not flow_weak:
                state.phase = Phase.HOLD
                state.watch_since = None
                self._event(p, state, "HOLD_RECOVERED")
                return
            watch_age = (p.ts - (state.watch_since or p.ts)).total_seconds()
            if watch_age >= self.cfg.watch_confirm_sec and sell_dominant and structure_broken:
                self._close(p, state, f"FLOW_WEAK+STRUCTURE_BREAK ratio={state.buy_ratio:.1%}")

    def _close(self, p: MarketPoint, state: FlowState, reason: str) -> None:
        status = self.execution.sell(p.code, state.qty)
        if status not in ("OK", "TIMEOUT", "SHADOW"):
            self._event(p, state, "SELL_ERROR", status)
            return
        state.phase = Phase.CLOSED
        state.exit_ts = p.ts
        state.exit_price = p.price
        state.exit_reason = reason
        state.terminal_ts = p.ts
        state.rearm_ready = False
        self._event(p, state, "SELL", reason)
        ret = (p.price / state.entry_price - 1.0) * 100 if state.entry_price > 0 else 0.0
        self.log.info("SELL %s %s @%.0f | %s | %.2f%%", state.name, p.code, p.price, reason, ret)

    def _process(self, p: MarketPoint) -> None:
        state = self.states.setdefault(p.code, FlowState(code=p.code, name=self.feed.names.get(p.code, p.code)))
        state.last_update_ts = p.ts

        if state.phase in (Phase.CLOSED, Phase.FAILED):
            # 같은 MONEY_START 파동의 반복 진입 방지: 신호가 한 번 완전히 꺼진 뒤에만 재무장한다.
            surge_now = self._is_surge(p)
            if not surge_now:
                state.rearm_ready = True
                return
            terminal = state.terminal_ts or state.exit_ts or state.last_update_ts
            cooled = terminal is None or (p.ts - terminal).total_seconds() >= self.cfg.cooldown_sec
            if cooled and state.rearm_ready:
                state = FlowState(code=p.code, name=self.feed.names.get(p.code, p.code))
                self.states[p.code] = state
                self._start_low_search(p, state)
            return
        if state.phase == Phase.IDLE:
            if self._is_surge(p):
                self._start_low_search(p, state)
            return
        if state.phase == Phase.LOW_SEARCH:
            self._update_low_search(p, state)
            return
        if state.phase in (Phase.RESET, Phase.BUY_READY):
            self._update_reset_metrics(p, state)
            signal_ok, reason = self._buy_signal(p, state)
            if signal_ok:
                state.phase = Phase.BUY_READY
                self._event(p, state, "BUY_READY", reason)
                self._open(p, state, reason)
            elif state.reset_ts and (p.ts - state.reset_ts).total_seconds() > self.cfg.buy_max_elapsed_sec:
                state.phase = Phase.FAILED
                state.terminal_ts = p.ts
                state.rearm_ready = False
                self._event(p, state, "RESET_FAILED", "진입 확인창 내 매수우위 미확인")
            return
        if state.phase in (Phase.HOLD, Phase.WATCH):
            self._hold_or_sell(p, state)

    def _save_state(self) -> None:
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "live": self.cfg.live,
            "entries_today": self.entries_today,
            "states": {code: state_json(s) for code, s in self.states.items()},
        }
        atomic_json_write(self.cfg.state_path, payload)

    def run(self) -> None:
        if not self.execution.connect():
            raise RuntimeError("ExecutionAdapter 연결 실패")
        self.log.info("CAPTAIN2 시작 live=%s loop=%.1fs", self.cfg.live, self.cfg.loop_sec)
        while self.running:
            loop_started = time.monotonic()
            hm = datetime.now().strftime("%H%M")
            if hm > self.cfg.program_end:
                break
            try:
                points = self.feed.read_points()
                for point in points.values():
                    # 신규 FLOW 탐색은 진입창 안에서만. 기존 보유 추적은 종료시각까지 계속.
                    state = self.states.get(point.code)
                    has_position = bool(state and state.phase in (Phase.HOLD, Phase.WATCH))
                    if has_position or self.cfg.entry_start <= hm <= self.cfg.entry_end:
                        self._process(point)
                self._save_state()
            except Exception:
                self.log.exception("메인 루프 오류 — 다음 루프 계속")
            elapsed = time.monotonic() - loop_started
            time.sleep(max(0.05, self.cfg.loop_sec - elapsed))
        self._save_state()
        self.log.info("CAPTAIN2 종료")


def main() -> int:
    cfg = Config()
    logger = setup_logger(cfg)
    feed = DataFeed(cfg, logger)
    execution = ExecutionAdapter(cfg, logger)
    engine = Captain2Engine(cfg, feed, execution, logger)
    signal.signal(signal.SIGINT, engine.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, engine.stop)
    try:
        engine.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("치명 오류")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

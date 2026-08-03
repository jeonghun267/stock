# -*- coding: utf-8 -*-
"""Strategy 05 intraday base-breakout signal monitor.

Signal/watch only. This module never imports a broker and never submits orders.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time as time_module
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
SIGNAL_SCHEMA = "strategy_05_base_breakout_signal_v1"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"
ENTRY_START = time(9, 30)
ENTRY_END = time(14, 30)


@dataclass(frozen=True)
class SignalConfig:
    leaders_path: Path = Path(os.environ.get(
        "S05_LEADERS", r"C:\stock_bot\data\live_leaders.json"))
    eod_path: Path = Path(os.environ.get(
        "S05_EOD", r"C:\stock_bot\data\eod_daily_bars.csv"))
    watch_path: Path = Path(os.environ.get(
        "S05_WATCH", r"C:\stock_bot\IPC\micro_watch_strategy05.json"))
    shared_watch_path: Path = Path(os.environ.get(
        "S05_SHARED_WATCH",
        r"C:\stock_bot\IPC\micro_watch_strategy_shared.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S05_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    minute_path: Path = Path(os.environ.get(
        "S05_MINUTE", r"C:\stock_bot\data\돈맥_1분봉.json"))
    names_path: Path = Path(os.environ.get(
        "S05_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S05_OUTPUT", r"C:\stock_bot\data\strategy_05_base_breakout_signal_v1.json"))
    state_path: Path = Path(os.environ.get(
        "S05_STATE", r"C:\stock_bot\data\strategy_05_base_breakout_signal_state_v1.json"))
    event_dir: Path = Path(os.environ.get(
        "S05_EVENT_DIR", r"C:\stock_bot\data\strategy_05_signal_v1"))
    loop_sec: float = float(os.environ.get("S05_LOOP_SEC", "1"))
    max_snapshot_age_sec: float = float(os.environ.get("S05_SNAPSHOT_MAX_AGE", "4"))
    max_signals_per_code: int = int(os.environ.get("S05_MAX_CYCLES_PER_CODE", "2"))
    min_price: float = float(os.environ.get("S05_MIN_PRICE", "10000"))
    base_n: int = int(os.environ.get("S05_BASE_N", "30"))
    base_tight_pct: float = float(os.environ.get("S05_BASE_TIGHT_PCT", "3.0"))
    # ★[2026-07-31 친구님 지시 "3배로 바꿔줘"] 돌파봉 거래량 배수 6.0 → 3.0.
    #   S05 가 두 달째 거의 안 움직인 원인이 여기였다. 7/31 단계별 실측
    #   (고저폭30·09:30~14:30):
    #       30분 베이스(폭 3% 이내) 형성  → 구간의 79.2% 가 만족(병목 아님)
    #       베이스 후 돌파 발생           → 27건
    #       돌파봉 거래량 6배             → **1건**   ← 26건을 여기서 버렸다
    #     돌파봉 거래대금 배수 실측: 중앙값 1.2배 · 상위25% 2.4배 · 최대 11.6배.
    #     요구 배수별 통과: 1배 15건 · 2배 8건 · **3배 4건** · 4배 2건 · 6배 1건.
    #   3.0 을 고른 이유 = 오늘 유일한 신호(브이엠 13:13 → 그날 상한가)가 그대로 살아남고
    #     3~4건이 추가로 잡히는 지점. 2배(8건)는 돌파의 '거래량 폭발' 성격이 흐려진다.
    #   ⚠️베이스 폭 3%·길이 30분·재확인 10봉은 병목이 아니라 그대로 둔다.
    #   ⚠️하루 표본이다. 월요일 실측으로 재확인할 것.
    #   되돌리기: setx S05_BASE_VOLX 6 또는
    #             backup\strategy_05_base_breakout_signal_v1_20260731_volx3.py 복원
    base_volx: float = float(os.environ.get("S05_BASE_VOLX", "3.0"))
    retest_wait_bars: int = int(os.environ.get("S05_RETEST_WAIT_BARS", "10"))
    low_search_max_sec: float = float(os.environ.get("S05_LOW_SEARCH_MAX_SEC", "90"))
    low_no_new_sec: float = float(os.environ.get("S05_LOW_NO_NEW_SEC", "2"))
    max_retest_depth_pct: float = float(os.environ.get(
        "S05_MAX_RETEST_DEPTH_PCT", "0.8"))
    min_rebound_pct: float = float(os.environ.get(
        "S05_MIN_REBOUND_PCT", "0.3"))
    max_rebound_pct: float = float(os.environ.get(
        "S05_MAX_REBOUND_PCT", "1.0"))
    max_entry_above_line_pct: float = float(os.environ.get(
        "S05_MAX_ENTRY_ABOVE_LINE_PCT", "1.0"))
    buy_min_sec: float = float(os.environ.get("S05_BUY_MIN_SEC", "2"))
    buy_max_sec: float = float(os.environ.get("S05_BUY_MAX_SEC", "60"))
    buy_confirm_sec: float = float(os.environ.get("S05_BUY_CONFIRM_SEC", "3"))
    min_buy_ratio: float = float(os.environ.get("S05_MIN_BUY_RATIO", "0.58"))
    min_buy_sell_ratio: float = float(os.environ.get("S05_MIN_BS_RATIO", "1.35"))
    min_buy_money_ratio: float = float(os.environ.get(
        "S05_MIN_BUY_MONEY_RATIO", "0.58"))
    min_fast_buy_sell_ratio: float = float(os.environ.get(
        "S05_MIN_FAST_BUY_SELL_RATIO", "1.5"))
    max_entry_spread_bps: float = float(os.environ.get(
        "S05_MAX_ENTRY_SPREAD_BPS", "35"))
    min_microprice_edge_bps: float = float(os.environ.get(
        "S05_MIN_MICROPRICE_EDGE_BPS", "0"))
    min_entry_money_krw: float = float(os.environ.get(
        "S05_MIN_ENTRY_MONEY_KRW", "10000000"))
    persist_min_fraction: float = float(os.environ.get(
        "S05_PERSIST_MIN_FRACTION", "0.5"))

    def __post_init__(self) -> None:
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 05 requires exactly two opportunities per code")
        # ★[2026-07-31] base_volx 를 6.0 고정 → 3.0 이상 허용으로 완화(위 주석 근거).
        #   아예 없애지 않는다 — 실수로 0 이나 음수가 들어오면 "거래량 폭발" 성격이
        #   통째로 사라져 아무 돌파나 사게 된다. 베이스 길이·폭은 종전대로 고정.
        if self.base_n != 30 or self.base_tight_pct != 3.0:
            raise ValueError("Strategy 05 validated BASE parameters must remain 30/3.0")
        if self.base_volx < 3.0:
            raise ValueError("Strategy 05 breakout volume multiple must be >= 3.0")
        if self.retest_wait_bars != 10:
            raise ValueError("Strategy 05 requires the validated ten-bar retest window")
        if self.max_entry_spread_bps <= 0:
            raise ValueError("Strategy 05 entry spread limit must be positive")
        if not 0 < self.max_retest_depth_pct <= 3:
            raise ValueError("Strategy 05 retest depth must be in (0, 3]")
        if not 0 < self.min_rebound_pct < self.max_rebound_pct:
            raise ValueError("Strategy 05 rebound range is invalid")
        if self.max_entry_above_line_pct <= 0:
            raise ValueError("Strategy 05 entry chase limit must be positive")
        if self.buy_confirm_sec < 3:
            raise ValueError("Strategy 05 reclaim confirmation must be >= 3 seconds")
        if self.min_fast_buy_sell_ratio < 1.5:
            raise ValueError("Strategy 05 fast buy/sell ratio must be >= 1.5")


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MicroPoint:
    ts: datetime
    price: float
    buy_volume_cum: float
    sell_volume_cum: float
    buy_money_cum: float
    sell_money_cum: float
    ask_price: float
    bid_price: float
    spread_bps: float
    microprice_edge_bps: float


@dataclass
class CodeState:
    bars: Deque[Bar] = field(default_factory=lambda: deque(maxlen=50))
    building: Bar | None = None
    micro: Deque[MicroPoint] = field(default_factory=lambda: deque(maxlen=180))
    phase: str = "SCAN"
    breakout_line: float = 0.0
    breakout_ts: datetime | None = None
    base_range_pct: float = 0.0
    breakout_volx: float = 0.0
    wait_left: int = 0
    search_start: datetime | None = None
    candidate_low: MicroPoint | None = None
    low_updated_at: datetime | None = None
    reset_point: MicroPoint | None = None
    dominance_since: datetime | None = None
    emission_count: int = 0
    emitted_anchors: set[str] = field(default_factory=set)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        first = path.read_bytes()
        time_module.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    # ★[2026-07-29 친구님 승인 "재시도 패치"] 읽는 쪽이 파일을 잡은 순간 os.replace가
    #   WinError 5(접근거부)로 죽어 신호기 전체 정지(7/29 11:29 실제 사고·마감까지 낡은 신호로 운행).
    #   최초 1회 + 0.2초 간격 재시도 3회. 그래도 실패면 종전대로 예외(원인 은폐 방지). 롤백: 루프 제거.
    for _attempt in range(4):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if _attempt == 3:
                raise
            time_module.sleep(0.2)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)
    return parsed


def _tick_size(price: float) -> float:
    if price < 2000:
        return 1.0
    if price < 5000:
        return 5.0
    if price < 20000:
        return 10.0
    if price < 50000:
        return 50.0
    if price < 200000:
        return 100.0
    if price < 500000:
        return 500.0
    return 1000.0


def detect_base_breakout(
    bars: Iterable[Bar],
    *,
    base_n: int = 30,
    tight_pct: float = 3.0,
    min_volx: float = 6.0,
) -> dict[str, float] | None:
    rows = list(bars)
    if len(rows) < base_n + 1:
        return None
    base = rows[-(base_n + 1):-1]
    current = rows[-1]
    base_high = max(row.high for row in base)
    base_low = min(row.low for row in base)
    average_volume = sum(row.volume for row in base) / len(base)
    if base_low <= 0 or average_volume <= 0:
        return None
    range_pct = (base_high / base_low - 1.0) * 100.0
    volx = current.volume / average_volume
    if (
        range_pct > tight_pct
        or current.close <= current.open
        or current.close <= base_high
        or volx < min_volx
    ):
        return None
    return {
        "base_high": base_high,
        "base_low": base_low,
        "base_range_pct": range_pct,
        "breakout_volx": volx,
        "breakout_close": current.close,
    }


def _book_point(
    raw: Mapping[str, Any],
    now: datetime,
    max_age_sec: float,
) -> MicroPoint | None:
    ts = _parse_dt(raw.get("ts"))
    ob_ts = _parse_dt(raw.get("ob_ts"))
    if ts is None or ob_ts is None:
        return None
    if not (
        -2 <= (now - ts).total_seconds() <= max_age_sec
        and -2 <= (now - ob_ts).total_seconds() <= max_age_sec
    ):
        return None
    price = abs(_number(raw.get("cur")))
    ask = abs(_number(raw.get("best_ask_px")))
    bid = abs(_number(raw.get("best_bid_px")))
    ask_qty = abs(_number(raw.get("best_ask_qty")))
    bid_qty = abs(_number(raw.get("best_bid_qty")))
    buy_volume = _number(raw.get("buy_vol_cum"), -1)
    sell_volume = _number(raw.get("sell_vol_cum"), -1)
    buy_money = _number(raw.get("buy_money_cum"), -1)
    sell_money = _number(raw.get("sell_money_cum"), -1)
    if not (
        price > 0 and ask > bid > 0 and ask_qty > 0 and bid_qty > 0
        and min(buy_volume, sell_volume, buy_money, sell_money) >= 0
    ):
        return None
    midpoint = (ask + bid) / 2.0
    microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
    return MicroPoint(
        ts=ts,
        price=price,
        buy_volume_cum=buy_volume,
        sell_volume_cum=sell_volume,
        buy_money_cum=buy_money,
        sell_money_cum=sell_money,
        ask_price=ask,
        bid_price=bid,
        spread_bps=(ask - bid) / midpoint * 10_000.0,
        microprice_edge_bps=(microprice - midpoint) / midpoint * 10_000.0,
    )


def _name_map(payload: Mapping[str, Any]) -> dict[str, str]:
    raw = payload.get("map", payload)
    return {
        str(code).zfill(6): str(name)
        for code, name in raw.items()
        if str(code).isdigit() and len(str(code).zfill(6)) == 6
    }


# 공통 컨텍스트(strategy_common_candidate_context_v1)가 all_meta 에 실어주는 고저폭 지표.
# 신호 행에 그대로 붙여 기록만 한다 — 매수 판정에는 쓰지 않는다.
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
)


def _range_meta(*sources: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, Any] = {}
    for source in sources:
        merged.update(source.get("all_meta") or {})
    output: dict[str, dict[str, Any]] = {}
    for code, row in merged.items():
        if not isinstance(row, Mapping):
            continue
        picked = {key: row[key] for key in RANGE_KEYS if row.get(key) is not None}
        if picked:
            output[str(code).zfill(6)] = picked
    return output


def _leaders_current_day(payload: Mapping[str, Any], day: str) -> list[str]:
    stamp = _number(payload.get("ts"))
    if stamp <= 0:
        return []
    observed = datetime.fromtimestamp(stamp, KST)
    if observed.strftime("%Y%m%d") != day:
        return []
    return [
        str(code).zfill(6)
        for code in payload.get("codes") or []
        if str(code).isdigit() and len(str(code).zfill(6)) == 6
    ]


def load_eod_eligible(path: Path, min_price: float) -> set[str]:
    latest_date = ""
    rows: list[tuple[str, str, str, float]] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                day = str(raw.get("date") or "").replace("-", "")
                code = str(raw.get("code") or "").zfill(6)
                if day and code.isdigit() and len(code) == 6:
                    rows.append((
                        day,
                        code,
                        str(raw.get("market") or "").upper(),
                        _number(raw.get("close")),
                    ))
                    latest_date = max(latest_date, day)
    except OSError:
        return set()
    return {
        code for day, code, market, close in rows
        if day == latest_date and market == "KOSDAQ" and close >= min_price
    }


def _append_events(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # ★[2026-07-29 친구님 승인 "열 구성 고정"] 고저폭 hr_* 메타는 TOP30 종목 행에만 붙어
    #   행마다 키가 다를 수 있다. 종전 코드(첫 행 기준 DictWriter)는 다른 키가 섞이면
    #   ValueError 로 신호기 프로세스가 죽고, 안 죽어도 열이 어긋나 기록이 오염됐다.
    #   열 = 기존 파일 헤더 ∪ 이번 배치 전체 키(등장 순서 유지). 새 열이 생기면 하루짜리
    #   작은 파일이므로 통째로 다시 써서 정렬을 맞추고, 빠진 값은 빈칸으로 둔다.
    #   읽기 실패(잠금 등) 시엔 데이터 보존 우선으로 이어쓰기만 한다. 롤백: *.bak_20260729_review23
    batch_fields = list(dict.fromkeys(key for row in rows for key in row))
    header: list[str] = []
    existing: list[dict] = []
    read_ok = True
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                header = list(reader.fieldnames or [])
                existing = list(reader)
        except (OSError, csv.Error):
            read_ok = False
    fieldnames = list(dict.fromkeys(header + batch_fields))
    if read_ok and header != fieldnames:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, restval="", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + rows)
        return
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames if read_ok else batch_fields,
            restval="", extrasaction="ignore",
        )
        writer.writerows(rows)


class BaseBreakoutSignalMonitor:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []

    def restore(self, payload: Mapping[str, Any], day: str) -> None:
        if payload.get("schema") != SIGNAL_SCHEMA or payload.get("date") != day:
            return
        for raw_code, raw in (payload.get("codes") or {}).items():
            code = str(raw_code).zfill(6)
            state = self.states.setdefault(code, CodeState())
            for row in raw.get("bars") or []:
                try:
                    state.bars.append(Bar(
                        ts=datetime.fromisoformat(str(row["ts"])),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            state.phase = str(raw.get("phase") or "SCAN")
            state.breakout_line = _number(raw.get("breakout_line"))
            state.breakout_ts = _parse_dt(raw.get("breakout_ts"))
            state.base_range_pct = _number(raw.get("base_range_pct"))
            state.breakout_volx = _number(raw.get("breakout_volx"))
            state.wait_left = int(_number(raw.get("wait_left")))
            state.emission_count = int(_number(raw.get("emission_count")))
            state.emitted_anchors = set(raw.get("emitted_anchors") or [])
            if state.phase not in {"SCAN", "WAIT_RETEST"}:
                state.phase = "SCAN"

    def state_payload(
        self,
        now: datetime,
        *,
        codes: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        selected = set(codes) if codes is not None else None
        return {
            "schema": SIGNAL_SCHEMA,
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "codes": {
                code: {
                    "bars": [asdict(bar) for bar in state.bars],
                    "phase": state.phase,
                    "breakout_line": state.breakout_line,
                    "breakout_ts": state.breakout_ts,
                    "base_range_pct": state.base_range_pct,
                    "breakout_volx": state.breakout_volx,
                    "wait_left": state.wait_left,
                    "emission_count": state.emission_count,
                    "emitted_anchors": sorted(state.emitted_anchors),
                }
                for code, state in self.states.items()
                if (
                    selected is None
                    or code in selected
                    or state.phase != "SCAN"
                    or state.emission_count > 0
                )
            },
        }

    @staticmethod
    def _reset_pattern(state: CodeState) -> None:
        state.phase = "SCAN"
        state.breakout_line = 0.0
        state.breakout_ts = None
        state.base_range_pct = 0.0
        state.breakout_volx = 0.0
        state.wait_left = 0
        state.search_start = None
        state.candidate_low = None
        state.low_updated_at = None
        state.reset_point = None
        state.dominance_since = None

    def update_minute(
        self,
        code: str,
        ts: datetime,
        raw: Mapping[str, Any],
    ) -> bool:
        state = self.states.setdefault(code, CodeState())
        bucket = ts.replace(second=0, microsecond=0)
        incoming = Bar(
            ts=bucket,
            open=_number(raw.get("o")),
            high=_number(raw.get("h")),
            low=_number(raw.get("l")),
            close=_number(raw.get("c")),
            volume=_number(raw.get("v")),
        )
        if min(
            incoming.open, incoming.high, incoming.low,
            incoming.close,
        ) <= 0 or incoming.volume < 0:
            return False
        if state.building is None:
            state.building = incoming
            return False
        if bucket < state.building.ts:
            return False
        if bucket == state.building.ts:
            state.building = Bar(
                ts=bucket,
                open=state.building.open,
                high=max(state.building.high, incoming.high),
                low=min(state.building.low, incoming.low),
                close=incoming.close,
                volume=max(state.building.volume, incoming.volume),
            )
            return False
        if (bucket - state.building.ts).total_seconds() != 60:
            state.bars.clear()
            self._reset_pattern(state)
            state.building = incoming
            return False
        completed = state.building
        state.building = incoming
        if state.bars and completed.ts <= state.bars[-1].ts:
            return False
        if (
            state.bars
            and (completed.ts - state.bars[-1].ts).total_seconds() != 60
        ):
            state.bars.clear()
            self._reset_pattern(state)
        state.bars.append(completed)
        if state.phase == "WAIT_RETEST":
            state.wait_left -= 1
            if state.wait_left <= 0:
                state.phase = "SCAN"
        if state.phase != "SCAN" or not ENTRY_START <= completed.ts.time() < ENTRY_END:
            return True
        pattern = detect_base_breakout(
            state.bars,
            base_n=self.config.base_n,
            tight_pct=self.config.base_tight_pct,
            min_volx=self.config.base_volx,
        )
        if pattern:
            state.phase = "WAIT_RETEST"
            state.breakout_line = pattern["base_high"]
            state.breakout_ts = completed.ts
            state.base_range_pct = pattern["base_range_pct"]
            state.breakout_volx = pattern["breakout_volx"]
            state.wait_left = self.config.retest_wait_bars
        return True

    @staticmethod
    def _row(
        code: str,
        name: str,
        point: MicroPoint,
        state: CodeState,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "WAIT",
            "reason": reason,
            "price": point.price,
            "ask_price": point.ask_price,
            "spread_bps": round(point.spread_bps, 2),
            "microprice_edge_bps": round(point.microprice_edge_bps, 2),
            "phase": state.phase,
            "breakout_line": round(state.breakout_line, 2),
            "base_range_pct": round(state.base_range_pct, 4),
            "breakout_volx": round(state.breakout_volx, 4),
            "mode": SIGNAL_MODE,
        }

    def _money_rate(
        self,
        state: CodeState,
        seconds: float,
        *,
        side: str,
    ) -> float:
        if len(state.micro) < 2:
            return 0.0
        current = state.micro[-1]
        prior = [
            row for row in list(state.micro)[:-1]
            if (current.ts - row.ts).total_seconds() >= seconds
        ]
        if not prior:
            return 0.0
        base = prior[-1]
        elapsed = (current.ts - base.ts).total_seconds()
        if side == "buy":
            money = current.buy_money_cum - base.buy_money_cum
        elif side == "sell":
            money = current.sell_money_cum - base.sell_money_cum
        else:
            raise ValueError(f"unsupported money-rate side: {side}")
        return max(0.0, money) / elapsed if elapsed > 0 else 0.0

    @staticmethod
    def _fast_volume_rates(state: CodeState) -> tuple[float, float, float]:
        """Return current 5s buy/sell rates and the preceding 10s buy rate."""
        if len(state.micro) < 3:
            return 0.0, 0.0, 0.0
        current = state.micro[-1]

        def at_or_before(target: datetime) -> MicroPoint | None:
            for item in reversed(state.micro):
                if item.ts <= target:
                    return item
            return None

        recent_target = current.ts - timedelta(seconds=5)
        previous_target = current.ts - timedelta(seconds=15)
        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        if recent_start is None or previous_start is None:
            return 0.0, 0.0, 0.0
        if (
            (recent_target - recent_start.ts).total_seconds() > 2
            or (previous_target - previous_start.ts).total_seconds() > 3
        ):
            return 0.0, 0.0, 0.0
        recent_span = (current.ts - recent_start.ts).total_seconds()
        previous_span = (recent_start.ts - previous_start.ts).total_seconds()
        deltas = (
            current.buy_volume_cum - recent_start.buy_volume_cum,
            current.sell_volume_cum - recent_start.sell_volume_cum,
            recent_start.buy_volume_cum - previous_start.buy_volume_cum,
        )
        if recent_span <= 0 or previous_span <= 0 or min(deltas) < 0:
            return 0.0, 0.0, 0.0
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / previous_span,
        )

    def process_micro(
        self,
        code: str,
        name: str,
        point: MicroPoint,
        *,
        allow_signal: bool,
    ) -> tuple[dict[str, Any], bool]:
        state = self.states.setdefault(code, CodeState())
        if state.micro and (
            point.ts <= state.micro[-1].ts
            or point.buy_volume_cum < state.micro[-1].buy_volume_cum
            or point.sell_volume_cum < state.micro[-1].sell_volume_cum
            or point.buy_money_cum < state.micro[-1].buy_money_cum
            or point.sell_money_cum < state.micro[-1].sell_money_cum
            or (point.ts - state.micro[-1].ts).total_seconds() > 10
        ):
            state.micro.clear()
            if state.phase in {"LOW_SEARCH", "BUY_CONFIRM"}:
                state.phase = "SCAN"
                state.dominance_since = None
        state.micro.append(point)
        cutoff = point.ts.timestamp() - 90
        while state.micro and state.micro[0].ts.timestamp() < cutoff:
            state.micro.popleft()

        if not allow_signal:
            return self._row(code, name, point, state, "ENTRY_TIME_CLOSED"), False
        if point.price < self.config.min_price:
            return self._row(code, name, point, state, "PRICE_BELOW_10000"), False
        if state.phase == "SCAN":
            return self._row(code, name, point, state, "BASE_30M_WAIT"), False
        if state.phase == "WAIT_RETEST":
            if point.price > state.breakout_line:
                return self._row(code, name, point, state, "BREAKOUT_RETEST_WAIT"), False
            retest_depth_pct = (
                (state.breakout_line - point.price) / state.breakout_line * 100.0
            )
            if retest_depth_pct > self.config.max_retest_depth_pct:
                row = self._row(code, name, point, state, "RETEST_TOO_DEEP")
                row["retest_depth_pct"] = round(retest_depth_pct, 4)
                self._reset_pattern(state)
                return row, False
            state.phase = "LOW_SEARCH"
            state.search_start = point.ts
            state.candidate_low = point
            state.low_updated_at = point.ts
            return self._row(code, name, point, state, "RETEST_LOW_SEARCH"), False

        if state.phase == "LOW_SEARCH":
            if state.search_start is None or state.candidate_low is None:
                state.phase = "SCAN"
                return self._row(code, name, point, state, "LOW_SEARCH_STATE_INVALID"), False
            search_age = (point.ts - state.search_start).total_seconds()
            if search_age >= self.config.low_search_max_sec:
                state.phase = "SCAN"
                return self._row(code, name, point, state, "LOW_SEARCH_TIMEOUT"), False
            retest_floor = state.breakout_line * (
                1.0 - self.config.max_retest_depth_pct / 100.0
            )
            if point.price < retest_floor:
                row = self._row(code, name, point, state, "RETEST_TOO_DEEP")
                row["retest_depth_pct"] = round(
                    (state.breakout_line - point.price)
                    / state.breakout_line * 100.0,
                    4,
                )
                self._reset_pattern(state)
                return row, False
            if point.price < state.candidate_low.price:
                state.candidate_low = point
                state.low_updated_at = point.ts
                return self._row(code, name, point, state, "LOW_UPDATED"), False
            no_new = (point.ts - (state.low_updated_at or point.ts)).total_seconds()
            price_ok = point.price >= (
                state.candidate_low.price + _tick_size(state.candidate_low.price)
            )
            if not price_ok or no_new < self.config.low_no_new_sec:
                return self._row(code, name, point, state, "LOW_CONFIRM_WAIT"), False
            state.phase = "BUY_CONFIRM"
            state.reset_point = state.candidate_low
            state.dominance_since = None

        if state.phase != "BUY_CONFIRM" or state.reset_point is None:
            return self._row(code, name, point, state, "STATE_WAIT"), False
        reset = state.reset_point
        retest_floor = state.breakout_line * (
            1.0 - self.config.max_retest_depth_pct / 100.0
        )
        if point.price < retest_floor:
            row = self._row(code, name, point, state, "RETEST_TOO_DEEP")
            self._reset_pattern(state)
            return row, False
        if point.price < reset.price:
            state.phase = "LOW_SEARCH"
            state.candidate_low = point
            state.low_updated_at = point.ts
            state.dominance_since = None
            return self._row(code, name, point, state, "LOW_RESTART"), False
        elapsed = (point.ts - reset.ts).total_seconds()
        row = self._row(code, name, point, state, "BUY_FLOW_CONFIRM_WAIT")
        if elapsed < self.config.buy_min_sec:
            return row, False
        if elapsed > self.config.buy_max_sec:
            state.phase = "SCAN"
            row["reason"] = "BUY_CONFIRM_TIMEOUT"
            return row, False

        buy_volume = point.buy_volume_cum - reset.buy_volume_cum
        sell_volume = point.sell_volume_cum - reset.sell_volume_cum
        buy_money = point.buy_money_cum - reset.buy_money_cum
        sell_money = point.sell_money_cum - reset.sell_money_cum
        if min(buy_volume, sell_volume, buy_money, sell_money) < 0:
            state.phase = "SCAN"
            row["reason"] = "EXACT_FLOW_COUNTER_RESET"
            return row, False
        total_volume = buy_volume + sell_volume
        total_money = buy_money + sell_money
        buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.0
        buy_sell_ratio = buy_volume / max(sell_volume, 1e-9)
        buy_money_ratio = buy_money / total_money if total_money > 0 else 0.0
        buy_rate10 = self._money_rate(state, 10, side="buy")
        buy_rate30 = self._money_rate(state, 30, side="buy")
        sell_rate10 = self._money_rate(state, 10, side="sell")
        sell_rate30 = self._money_rate(state, 30, side="sell")
        buy_volume_rate5, sell_volume_rate5, prior_buy_volume_rate10 = (
            self._fast_volume_rates(state)
        )
        rebound_pct = (point.price / reset.price - 1.0) * 100.0
        line_reclaimed = point.price >= state.breakout_line
        chase_ok = point.price <= state.breakout_line * (
            1.0 + self.config.max_entry_above_line_pct / 100.0
        )
        rebound_ok = (
            self.config.min_rebound_pct
            <= rebound_pct
            <= self.config.max_rebound_pct
        )
        fast_flow_ok = (
            buy_rate10 > 0
            and sell_rate10 > 0
            and buy_rate10
            >= sell_rate10 * self.config.min_fast_buy_sell_ratio
            and buy_volume_rate5 > 0
            and sell_volume_rate5 > 0
            and prior_buy_volume_rate10 > 0
            and buy_volume_rate5
            >= sell_volume_rate5 * self.config.min_fast_buy_sell_ratio
            and buy_volume_rate5 > prior_buy_volume_rate10
        )
        price_ok = line_reclaimed and chase_ok and rebound_ok
        persistence_ok = (
            buy_rate30 > 0
            and buy_rate10 >= self.config.persist_min_fraction * buy_rate30
        )
        spread_ok = point.spread_bps <= self.config.max_entry_spread_bps
        microprice_ok = (
            point.microprice_edge_bps > self.config.min_microprice_edge_bps
        )
        dominance_ok = (
            total_volume >= 1
            and total_money >= self.config.min_entry_money_krw
            and buy_ratio >= self.config.min_buy_ratio
            and buy_sell_ratio >= self.config.min_buy_sell_ratio
            and buy_money_ratio >= self.config.min_buy_money_ratio
            and price_ok
            and persistence_ok
            and fast_flow_ok
            and spread_ok
        )
        row.update({
            "reset_price": reset.price,
            "flow_observation_sec": round(elapsed, 2),
            "buy_ratio": round(buy_ratio, 4),
            "buy_sell_ratio": round(buy_sell_ratio, 4),
            "buy_money_ratio": round(buy_money_ratio, 4),
            "entry_money_krw": round(total_money),
            "buy_money_rate_10s": round(buy_rate10),
            "buy_money_rate_30s": round(buy_rate30),
            "sell_money_rate_10s": round(sell_rate10),
            "sell_money_rate_30s": round(sell_rate30),
            "buy_volume_rate_5s": round(buy_volume_rate5, 4),
            "sell_volume_rate_5s": round(sell_volume_rate5, 4),
            "prior_buy_volume_rate_10s": round(prior_buy_volume_rate10, 4),
            "rebound_pct": round(rebound_pct, 4),
            "line_reclaimed": line_reclaimed,
            "chase_ok": chase_ok,
            "fast_flow_ok": fast_flow_ok,
            "spread_ok": spread_ok,
            "microprice_ok": microprice_ok,
        })
        if dominance_ok:
            if state.dominance_since is None:
                state.dominance_since = point.ts
        else:
            state.dominance_since = None
        duration = (
            (point.ts - state.dominance_since).total_seconds()
            if state.dominance_since else 0.0
        )
        if (
            not dominance_ok
            or duration < self.config.buy_confirm_sec
            or not microprice_ok
        ):
            if dominance_ok and duration >= self.config.buy_confirm_sec:
                row["reason"] = "MICROPRICE_CONFIRM_WAIT"
            return row, False

        anchor = (
            f"{state.breakout_ts.isoformat(timespec='minutes') if state.breakout_ts else ''}:"
            f"{state.breakout_line:.4f}:{reset.ts.isoformat(timespec='seconds')}"
        )
        if (
            anchor in state.emitted_anchors
            or state.emission_count >= self.config.max_signals_per_code
        ):
            state.phase = "SCAN"
            row["reason"] = "ANCHOR_OR_CYCLE_ALREADY_USED"
            return row, False
        state.emission_count += 1
        state.emitted_anchors.add(anchor)
        state.phase = "SCAN"
        row.update({
            "action": "BUY_READY",
            "reason": "BASE_RETEST+REAL_LOW+EXACT_BUY_DOMINANCE+BOOK_CONFIRM",
            "anchor_id": anchor,
            "entry_lane": (
                f"S05_BASE:{state.breakout_line:.4f}:{reset.price:.4f}"
            ),
            "signal_sequence": state.emission_count,
            "algorithm": "S05_BASE_BREAKOUT_PRO_V2",
            "gross_edge_pct": 0.0,
            "expected_cost_pct": 0.0,
        })
        return row, True


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = BaseBreakoutSignalMonitor(config)
    monitor.restore(_read_json(config.state_path), now.strftime("%Y%m%d"))
    eligible = load_eod_eligible(config.eod_path, config.min_price)
    last_state_save = ""
    last_watch_codes: list[str] = []
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        day = now.strftime("%Y%m%d")
        leaders = _leaders_current_day(_read_json(config.leaders_path), day)
        range_meta = _range_meta(_read_json(config.shared_watch_path))

        minute = _read_json(config.minute_path)
        minute_ts = _parse_dt(minute.get("ts"))
        minute_rows = minute.get("m") or {}
        bars_completed = False
        bar_codes: list[str] = []
        if minute_ts is not None and minute_ts.strftime("%Y%m%d") == day:
            bar_codes = sorted(
                code for code in minute_rows
                if code in eligible and isinstance(minute_rows.get(code), Mapping)
            )
            for code in bar_codes:
                bars_completed |= monitor.update_minute(
                    code, minute_ts, minute_rows[code]
                )

        armed_codes = sorted(
            code for code, state in monitor.states.items()
            if code in eligible and state.phase != "SCAN"
        )
        watch_codes = list(dict.fromkeys(
            [code for code in leaders if code in eligible] + armed_codes
        ))
        if watch_codes != last_watch_codes:
            _write_json_atomic(config.watch_path, {
                "schema": "strategy_05_base_watch_v1",
                "for_date": day,
                "ts": now.isoformat(timespec="seconds"),
                "codes": watch_codes,
                "order_capability": 0,
            })
            last_watch_codes = watch_codes

        names = _name_map(_read_json(config.names_path))
        snapshot = _read_json(config.snapshot_path)
        new_signals: list[dict[str, Any]] = []
        valid_points = 0
        for code in watch_codes:
            raw = (snapshot.get("codes") or {}).get(code)
            point = (
                _book_point(raw, now, config.max_snapshot_age_sec)
                if isinstance(raw, Mapping) else None
            )
            if point is None:
                continue
            valid_points += 1
            row, fired = monitor.process_micro(
                code,
                names.get(code, code),
                point,
                allow_signal=ENTRY_START <= point.ts.time() < ENTRY_END,
            )
            row.update(range_meta.get(code) or {})
            monitor.latest[code] = row
            if fired:
                monitor.signals.append(dict(row))
                new_signals.append(dict(row))

        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": day,
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": SIGNAL_MODE,
            "status": "LIVE" if valid_points else "DATA_WAIT",
            "watch_count": len(watch_codes),
            "bar_universe_count": len(bar_codes),
            "valid_topbook_count": valid_points,
            "entry_window": "09:30-14:30",
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
        }
        _write_json_atomic(config.output_path, payload)
        if bars_completed or last_state_save != now.strftime("%Y%m%d%H%M"):
            _write_json_atomic(
                config.state_path,
                monitor.state_payload(now, codes=watch_codes),
            )
            last_state_save = now.strftime("%Y%m%d%H%M")
        _append_events(
            config.event_dir / f"strategy_05_signals_{now:%Y%m%d}.csv",
            new_signals,
        )
        if once or now.weekday() >= 5 or now.time() >= time(15, 25):
            return 0
        time_module.sleep(max(0.2, config.loop_sec))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return run(SignalConfig(), once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())

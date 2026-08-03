# -*- coding: utf-8 -*-
"""Strategy 04 deep-W pullback signal monitor.

Signal only: this module never imports a broker or submits an order.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time as time_module
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
SIGNAL_SCHEMA = "strategy_04_deep_w_pullback_signal_v1"
SIGNAL_MODE = "SIGNAL_ONLY_ORDER_ZERO"
ENTRY_START = time(10, 0)
ENTRY_END = time(12, 0)
# ★[2026-07-27 친구님 승인] 관문별 탈락 그림자 계측 열 — 기록 전용(신호 로직 무변경).
FUNNEL_FIELDS = (
    "ts", "code", "name", "action", "reason", "price", "drop_pct",
    "second_drop_pct", "rebound_pct", "current_chase_pct", "buy_ratio",
    "flow_observation_sec", "book_recovery", "rising_sec", "gross_edge_pct",
    "expected_cost_pct", "spread_bps", "book_bid_share",
    "microprice_edge_bps",
)
# 공통 컨텍스트(strategy_common_candidate_context_v1)가 all_meta 에 실어주는 고저폭 지표.
# 신호 행에 그대로 붙여 기록만 한다 — 매수 판정에는 쓰지 않는다.
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
)


@dataclass(frozen=True)
class SignalConfig:
    watch_path: Path = Path(os.environ.get(
        "S04_WATCH", r"C:\stock_bot\IPC\micro_watch_valley.json"))
    context_path: Path = Path(os.environ.get(
        "S04_CONTEXT", r"C:\stock_bot\data\strategy_common_candidate_context_v1.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S04_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    minute_path: Path = Path(os.environ.get(
        "S04_MINUTE", r"C:\stock_bot\data\돈맥_1분봉.json"))
    market_path: Path = Path(os.environ.get(
        "S04_MARKET", r"C:\stock_bot\data\kosdaq_index.json"))
    names_path: Path = Path(os.environ.get(
        "S04_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S04_OUTPUT", r"C:\stock_bot\data\strategy_04_pullback_signal_v1.json"))
    state_path: Path = Path(os.environ.get(
        "S04_STATE", r"C:\stock_bot\data\strategy_04_pullback_signal_state_v1.json"))
    event_dir: Path = Path(os.environ.get(
        "S04_EVENT_DIR", r"C:\stock_bot\data\strategy_04_signal_v1"))
    loop_sec: float = float(os.environ.get("S04_LOOP_SEC", "1"))
    max_snapshot_age_sec: float = float(os.environ.get("S04_SNAPSHOT_MAX_AGE", "4"))
    max_market_age_sec: float = float(os.environ.get("S04_MARKET_MAX_AGE", "600"))
    max_signals_per_code: int = int(os.environ.get("S04_MAX_CYCLES_PER_CODE", "2"))
    min_price: float = float(os.environ.get("S04_MIN_PRICE", "10000"))
    min_drop_pct: float = float(os.environ.get("S04_MIN_DROP_PCT", "-18"))
    max_drop_pct: float = float(os.environ.get("S04_MAX_DROP_PCT", "-10"))
    audit_drop_floor_pct: float = float(os.environ.get("S04_AUDIT_DROP_FLOOR_PCT", "-25"))
    min_rebound_pct: float = float(os.environ.get("S04_MIN_REBOUND_PCT", "2"))
    low_tolerance_pct: float = float(os.environ.get("S04_LOW_TOLERANCE_PCT", "2"))
    max_chase_pct: float = float(os.environ.get("S04_MAX_CHASE_PCT", "5"))
    min_buy_ratio: float = float(os.environ.get("S04_MIN_BUY_RATIO", "0.55"))
    min_bid_share: float = float(os.environ.get("S04_MIN_BID_SHARE", "0.52"))
    min_book_recovery: float = float(os.environ.get("S04_MIN_BOOK_RECOVERY", "0.05"))
    max_spread_bps: float = float(os.environ.get("S04_MAX_SPREAD_BPS", "35"))
    min_price_rising_sec: float = float(os.environ.get("S04_MIN_RISING_SEC", "3"))
    min_edge_margin_pct: float = float(os.environ.get("S04_EDGE_MARGIN_PCT", "0.30"))

    def __post_init__(self) -> None:
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 04 requires exactly two opportunities per code")
        if not self.audit_drop_floor_pct <= self.min_drop_pct < self.max_drop_pct < 0:
            raise ValueError("invalid deep-drop thresholds")


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    value: float = 0.0


@dataclass(frozen=True)
class MicroPoint:
    ts: datetime
    price: float
    buy_money_cum: float
    sell_money_cum: float
    bid_share: float
    spread_bps: float
    microprice_edge_bps: float
    ask_price: float


@dataclass
class CodeState:
    bars: Deque[Bar] = field(default_factory=lambda: deque(maxlen=80))
    building: Bar | None = None
    micro: Deque[MicroPoint] = field(default_factory=lambda: deque(maxlen=90))
    rise_since: datetime | None = None
    last_price: float = 0.0
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


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any, now: datetime) -> datetime | None:
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


def _bucket_3m(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 3) * 3, second=0, microsecond=0)


def _name_map(payload: Mapping[str, Any]) -> dict[str, str]:
    raw = payload.get("map", payload)
    return {str(code).zfill(6): str(name) for code, name in raw.items()}


def _prev_close_map(
    watch: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, float]:
    merged: dict[str, Any] = {}
    for source in (context.get("all_meta") or {}, watch.get("all_meta") or {}):
        merged.update(source)
    return {
        str(code).zfill(6): _number((row or {}).get("prev_close"))
        for code, row in merged.items()
        if _number((row or {}).get("prev_close")) > 0
    }


def _range_meta(
    watch: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, Any] = {}
    for source in (context.get("all_meta") or {}, watch.get("all_meta") or {}):
        merged.update(source)
    output: dict[str, dict[str, Any]] = {}
    for code, row in merged.items():
        if not isinstance(row, Mapping):
            continue
        picked = {key: row[key] for key in RANGE_KEYS if row.get(key) is not None}
        if picked:
            output[str(code).zfill(6)] = picked
    return output


def _book_point(
    raw: Mapping[str, Any],
    now: datetime,
    max_age_sec: float,
) -> MicroPoint | None:
    ts = _parse_dt(raw.get("ts"), now)
    ob_ts = _parse_dt(raw.get("ob_ts"), now)
    if ts is None or ob_ts is None:
        return None
    if not (
        -2 <= (now - ts).total_seconds() <= max_age_sec
        and -2 <= (now - ob_ts).total_seconds() <= max_age_sec
    ):
        return None
    price = abs(_number(raw.get("cur")))
    ask_total = abs(_number(raw.get("ask_tot")))
    bid_total = abs(_number(raw.get("bid_tot")))
    ask = abs(_number(raw.get("best_ask_px")))
    bid = abs(_number(raw.get("best_bid_px")))
    ask_qty = abs(_number(raw.get("best_ask_qty")))
    bid_qty = abs(_number(raw.get("best_bid_qty")))
    buy = _number(raw.get("buy_money_cum"), -1)
    sell = _number(raw.get("sell_money_cum"), -1)
    if not (
        price > 0 and ask > bid > 0 and ask_qty > 0 and bid_qty > 0
        and ask_total > 0 and bid_total > 0 and buy >= 0 and sell >= 0
    ):
        return None
    midpoint = (ask + bid) / 2.0
    microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
    return MicroPoint(
        ts=ts,
        price=price,
        buy_money_cum=buy,
        sell_money_cum=sell,
        bid_share=bid_total / (ask_total + bid_total),
        spread_bps=(ask - bid) / midpoint * 10_000.0,
        microprice_edge_bps=(microprice - midpoint) / midpoint * 10_000.0,
        ask_price=ask,
    )


def _market_context(
    payload: Mapping[str, Any],
    now: datetime,
    max_age_sec: float,
) -> tuple[bool, float]:
    ts = _parse_dt(payload.get("ts"), now)
    if ts is None or not -2 <= (now - ts).total_seconds() <= max_age_sec:
        return False, 0.0
    return True, _number(payload.get("chg"))


def _minute_rows(
    payload: Mapping[str, Any],
    now: datetime,
) -> tuple[datetime | None, Mapping[str, Any]]:
    ts = _parse_dt(payload.get("ts"), now)
    rows = payload.get("m") or {}
    return ts, rows if isinstance(rows, Mapping) else {}


def _flow_metrics(points: Deque[MicroPoint]) -> tuple[bool, float, float]:
    if len(points) < 2:
        return False, 0.0, 0.0
    current = points[-1]
    eligible = [
        row for row in list(points)[:-1]
        if (current.ts - row.ts).total_seconds() >= 10
    ]
    if not eligible:
        return False, 0.0, 0.0
    base = eligible[-1]
    buy = current.buy_money_cum - base.buy_money_cum
    sell = current.sell_money_cum - base.sell_money_cum
    elapsed = (current.ts - base.ts).total_seconds()
    total = buy + sell
    exact = buy >= 0 and sell >= 0 and elapsed >= 10 and total > 0
    return exact, (buy / total if exact else 0.0), elapsed


def _moving_average(bars: list[Bar], window: int, end: int) -> float:
    values = [bar.close for bar in bars[max(0, end - window + 1):end + 1]]
    return sum(values) / len(values) if len(values) == window else 0.0


def detect_deep_w(
    bars: Iterable[Bar],
    *,
    prev_close: float,
    config: SignalConfig,
) -> dict[str, Any] | None:
    rows = list(bars)
    if len(rows) < 20 or prev_close < config.min_price:
        return None
    current_i = len(rows) - 1
    ma3 = _moving_average(rows, 3, current_i)
    ma20 = _moving_average(rows, 20, current_i)
    prior_ma3 = _moving_average(rows, 3, current_i - 1)
    prior_ma20 = _moving_average(rows, 20, current_i - 1)
    if not (prior_ma3 <= prior_ma20 and ma3 > ma20):
        return None

    for second_i in range(current_i - 1, 3, -1):
        first_end = second_i - 2
        if first_end <= 0:
            continue
        first_i = min(range(first_end), key=lambda idx: rows[idx].low)
        first_low = rows[first_i].low
        drop_pct = (first_low / prev_close - 1.0) * 100.0
        if not config.audit_drop_floor_pct <= drop_pct <= config.max_drop_pct:
            continue
        middle = rows[first_i + 1:second_i]
        if not middle:
            continue
        neckline = max(bar.high for bar in middle)
        rebound_pct = (neckline / first_low - 1.0) * 100.0
        if rebound_pct < config.min_rebound_pct:
            continue
        second_low = rows[second_i].low
        second_drop_pct = (second_low / prev_close - 1.0) * 100.0
        low_difference_pct = (second_low / first_low - 1.0) * 100.0
        if abs(low_difference_pct) > config.low_tolerance_pct:
            continue
        if second_low >= neckline / 1.015:
            continue
        current = rows[current_i]
        if current.close < neckline:
            continue
        chase_pct = (current.close / second_low - 1.0) * 100.0
        if chase_pct > config.max_chase_pct:
            continue
        return {
            "first_low": first_low,
            "first_low_ts": rows[first_i].ts.isoformat(timespec="minutes"),
            "second_low": second_low,
            "second_low_ts": rows[second_i].ts.isoformat(timespec="minutes"),
            "neckline": neckline,
            "drop_pct": drop_pct,
            "second_drop_pct": second_drop_pct,
            "rebound_pct": rebound_pct,
            "low_difference_pct": low_difference_pct,
            "chase_pct": chase_pct,
            "ma3": ma3,
            "ma20": ma20,
            "confirm_ts": current.ts.isoformat(timespec="minutes"),
        }
    return None


class PullbackSignalMonitor:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []
        self.market_changes: Deque[tuple[datetime, float]] = deque(maxlen=720)

    def restore(self, payload: Mapping[str, Any], day: str) -> None:
        if str(payload.get("schema") or "") != SIGNAL_SCHEMA:
            return
        if str(payload.get("date") or "") != day:
            return
        for code, raw in (payload.get("codes") or {}).items():
            state = self.states.setdefault(str(code).zfill(6), CodeState())
            for row in raw.get("bars") or []:
                try:
                    state.bars.append(Bar(
                        ts=datetime.fromisoformat(row["ts"]),
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                        value=float(row.get("value") or 0),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            state.emission_count = int(raw.get("emission_count") or 0)
            state.emitted_anchors = set(raw.get("emitted_anchors") or [])

    def state_payload(self, now: datetime) -> dict[str, Any]:
        return {
            "schema": SIGNAL_SCHEMA,
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "codes": {
                code: {
                    "bars": [asdict(bar) for bar in state.bars],
                    "emission_count": state.emission_count,
                    "emitted_anchors": sorted(state.emitted_anchors),
                }
                for code, state in self.states.items()
            },
        }

    def update_minute(
        self,
        code: str,
        ts: datetime,
        raw: Mapping[str, Any],
    ) -> bool:
        state = self.states.setdefault(code, CodeState())
        bucket = _bucket_3m(ts)
        incoming = Bar(
            ts=bucket,
            open=_number(raw.get("o")),
            high=_number(raw.get("h")),
            low=_number(raw.get("l")),
            close=_number(raw.get("c")),
            value=_number(raw.get("value")),
        )
        if min(incoming.open, incoming.high, incoming.low, incoming.close) <= 0:
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
                value=max(state.building.value, incoming.value),
            )
            return False
        completed = state.building
        if not state.bars or completed.ts > state.bars[-1].ts:
            state.bars.append(completed)
        state.building = incoming
        return True

    def process_micro(
        self,
        code: str,
        name: str,
        point: MicroPoint,
        prev_close: float,
        *,
        market_fresh: bool,
        market_change: float,
        allow_signal: bool,
    ) -> tuple[dict[str, Any], bool]:
        state = self.states.setdefault(code, CodeState())
        if state.micro and (
            point.ts <= state.micro[-1].ts
            or point.buy_money_cum < state.micro[-1].buy_money_cum
            or point.sell_money_cum < state.micro[-1].sell_money_cum
            or (point.ts - state.micro[-1].ts).total_seconds() > 10
        ):
            state.micro.clear()
            state.rise_since = None
        if point.price > state.last_price > 0:
            if state.rise_since is None:
                state.rise_since = state.micro[-1].ts if state.micro else point.ts
        elif state.last_price > 0 and point.price < state.last_price:
            state.rise_since = None
        state.last_price = point.price
        state.micro.append(point)
        cutoff = point.ts.timestamp() - 45
        while state.micro and state.micro[0].ts.timestamp() < cutoff:
            state.micro.popleft()

        pattern = detect_deep_w(state.bars, prev_close=prev_close, config=self.config)
        if pattern is None:
            return self._row(code, name, point, "WAIT", "W_MA3_20_NECKLINE_WAIT"), False
        row = self._row(code, name, point, "WAIT", "MICRO_CONFIRM_WAIT", pattern)
        if min(
            pattern["drop_pct"],
            pattern["second_drop_pct"],
        ) < self.config.min_drop_pct:
            row["reason"] = "EXTREME_DROP_NEWS_RISK_UNRESOLVED"
            return row, False
        if not allow_signal:
            row["reason"] = "ENTRY_TIME_CLOSED"
            return row, False
        current_chase_pct = (
            point.price / float(pattern["second_low"]) - 1.0
        ) * 100.0
        row["current_chase_pct"] = round(current_chase_pct, 4)
        if (
            point.price < float(pattern["neckline"])
            or current_chase_pct > self.config.max_chase_pct
        ):
            row["reason"] = "LIVE_NECKLINE_OR_CHASE_FAILED"
            return row, False
        row["market_fresh"] = bool(market_fresh)
        if not market_fresh:
            row["reason"] = "MARKET_CONTEXT_STALE"
            return row, False
        market_min = min((value for _, value in self.market_changes), default=market_change)
        market_recovery_pct = market_change - market_min
        row["market_change_pct"] = round(market_change, 4)
        row["market_recovery_pct"] = round(market_recovery_pct, 4)
        if market_change < -0.5 and market_recovery_pct < 0.2:
            row["reason"] = "KOSDAQ_NOT_RECOVERING"
            return row, False
        exact_flow, buy_ratio, flow_sec = _flow_metrics(state.micro)
        row.update({
            "buy_ratio": round(buy_ratio, 4),
            "flow_observation_sec": round(flow_sec, 2),
        })
        if not exact_flow or buy_ratio < self.config.min_buy_ratio:
            row["reason"] = "EXACT_BUY_FLOW_WAIT"
            return row, False
        recent = [
            sample.bid_share for sample in state.micro
            if (point.ts - sample.ts).total_seconds() <= 30
        ]
        book_recovery = point.bid_share - min(recent, default=point.bid_share)
        row["book_recovery"] = round(book_recovery, 4)
        if (
            point.bid_share < self.config.min_bid_share
            or book_recovery < self.config.min_book_recovery
            or point.microprice_edge_bps <= 0
        ):
            row["reason"] = "ORDER_BOOK_RECOVERY_WAIT"
            return row, False
        if point.spread_bps > self.config.max_spread_bps:
            row["reason"] = "SPREAD_TOO_WIDE"
            return row, False
        rising_sec = (
            max(0.0, (point.ts - state.rise_since).total_seconds())
            if state.rise_since else 0.0
        )
        recent_prices = [
            sample.price for sample in state.micro
            if (point.ts - sample.ts).total_seconds() <= 5
        ]
        row["rising_sec"] = round(rising_sec, 2)
        if (
            rising_sec < self.config.min_price_rising_sec
            or point.price <= min(recent_prices, default=point.price)
        ):
            row["reason"] = "ELAPSED_PRICE_RECOVERY_WAIT"
            return row, False

        measured_target = pattern["neckline"] + (
            pattern["neckline"]
            - (pattern["first_low"] + pattern["second_low"]) / 2.0
        )
        target = min(prev_close, measured_target)
        gross_edge_pct = (target / point.ask_price - 1.0) * 100.0
        expected_cost_pct = 0.21 + (2.0 * point.spread_bps / 100.0) + 0.10
        row.update({
            "target_price": round(target, 2),
            "gross_edge_pct": round(gross_edge_pct, 4),
            "expected_cost_pct": round(expected_cost_pct, 4),
        })
        if gross_edge_pct < expected_cost_pct + self.config.min_edge_margin_pct:
            row["reason"] = "EDGE_AFTER_COST_TOO_SMALL"
            return row, False

        anchor_id = f"{pattern['second_low_ts']}:{pattern['second_low']:.4f}"
        if (
            anchor_id in state.emitted_anchors
            or state.emission_count >= self.config.max_signals_per_code
        ):
            row["reason"] = "ANCHOR_OR_CYCLE_ALREADY_USED"
            return row, False
        state.emission_count += 1
        state.emitted_anchors.add(anchor_id)
        row.update({
            "action": "BUY_READY",
            "reason": "DEEP_W_MA3_CROSS_NECKLINE+FLOW+BOOK+MARKET+COST",
            "anchor_id": anchor_id,
            "signal_sequence": state.emission_count,
            "algorithm": "S04_DEEP_W_PRO_V1",
        })
        return row, True

    @staticmethod
    def _row(
        code: str,
        name: str,
        point: MicroPoint,
        action: str,
        reason: str,
        pattern: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": action,
            "reason": reason,
            "price": point.price,
            "ask_price": point.ask_price,
            "book_bid_share": round(point.bid_share, 4),
            "spread_bps": round(point.spread_bps, 2),
            "microprice_edge_bps": round(point.microprice_edge_bps, 2),
            "mode": SIGNAL_MODE,
        }
        if pattern:
            row.update({
                key: (round(value, 4) if isinstance(value, float) else value)
                for key, value in pattern.items()
            })
        return row


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_events(path: Path, rows: Iterable[Mapping[str, Any]]) -> bool:
    rows = list(rows)
    if not rows:
        return True
    try:
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
        else:
            with path.open("a", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=fieldnames if read_ok else batch_fields,
                    restval="", extrasaction="ignore",
                )
                writer.writerows(rows)
    except OSError as exc:
        print(
            f"S04_EVENT_WRITE_WARNING path={path} error={type(exc).__name__}:{exc}",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = PullbackSignalMonitor(config)
    monitor.restore(_read_json(config.state_path), now.strftime("%Y%m%d"))
    last_state_save = ""
    # ★[2026-07-27 친구님 승인] 관문별 탈락 그림자 계측 — 판정 사유가 바뀔 때만 기록.
    last_reason: dict[str, str] = {}
    funnel_count = 0
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        watch = _read_json(config.watch_path)
        context = _read_json(config.context_path)
        day = now.strftime("%Y%m%d")
        watch_valid = str(watch.get("for_date") or "") == day
        codes = (
            {str(code).zfill(6) for code in watch.get("codes") or []}
            if watch_valid else set()
        )
        prev_close = _prev_close_map(watch, context)
        range_meta = _range_meta(watch, context)
        names = _name_map(_read_json(config.names_path))
        minute_ts, minute_rows = _minute_rows(_read_json(config.minute_path), now)
        bars_completed = False
        if minute_ts is not None and minute_ts.strftime("%Y%m%d") == day:
            for code in codes:
                raw = minute_rows.get(code)
                if isinstance(raw, Mapping):
                    bars_completed |= monitor.update_minute(code, minute_ts, raw)
        market_fresh, market_change = _market_context(
            _read_json(config.market_path), now, config.max_market_age_sec)
        if market_fresh:
            monitor.market_changes.append((now, market_change))
            market_cutoff = now.timestamp() - 7200
            while (
                monitor.market_changes
                and monitor.market_changes[0][0].timestamp() < market_cutoff
            ):
                monitor.market_changes.popleft()

        snapshot = _read_json(config.snapshot_path)
        new_signals: list[dict[str, Any]] = []
        funnel_rows: list[dict[str, Any]] = []
        valid_points = 0
        for code in codes:
            raw = (snapshot.get("codes") or {}).get(code)
            point = (
                _book_point(raw, now, config.max_snapshot_age_sec)
                if isinstance(raw, Mapping) else None
            )
            if point is None or prev_close.get(code, 0) <= 0:
                continue
            valid_points += 1
            row, fired = monitor.process_micro(
                code,
                names.get(code, code),
                point,
                prev_close[code],
                market_fresh=market_fresh,
                market_change=market_change,
                allow_signal=ENTRY_START <= point.ts.time() < ENTRY_END,
            )
            row.update(range_meta.get(code) or {})
            monitor.latest[code] = row
            reason = str(row.get("reason") or "")
            if last_reason.get(code) != reason and funnel_count < 50_000:
                last_reason[code] = reason
                funnel_count += 1
                funnel_rows.append(
                    {key: row.get(key, "") for key in FUNNEL_FIELDS})
            if fired:
                monitor.signals.append(dict(row))
                new_signals.append(dict(row))

        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": day,
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": SIGNAL_MODE,
            "status": (
                "WATCH_DATE_MISMATCH" if not watch_valid
                else "LIVE" if valid_points else "DATA_WAIT"
            ),
            "watch_count": len(codes),
            "valid_topbook_count": valid_points,
            "market_fresh": market_fresh,
            "market_change_pct": market_change,
            "entry_window": "10:00-12:00",
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
        }
        _write_json_atomic(config.output_path, payload)
        if bars_completed or last_state_save != now.strftime("%Y%m%d%H%M"):
            _write_json_atomic(config.state_path, monitor.state_payload(now))
            last_state_save = now.strftime("%Y%m%d%H%M")
        _append_events(
            config.event_dir / f"strategy_04_signals_{now:%Y%m%d}.csv",
            new_signals,
        )
        _append_events(
            config.event_dir / f"strategy_04_funnel_{now:%Y%m%d}.csv",
            funnel_rows,
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

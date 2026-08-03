# -*- coding: utf-8 -*-
"""새전략 01 장초반 급상승 초입 신호전용 실시간 감시기."""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
import time as time_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_open_surge_buy_v1 import (
    BuyAction,
    OpenSurgeBuyStrategy,
    OpenSurgeObservation,
)

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ShadowConfig:
    watch_path: Path = Path(os.environ.get(
        "S01_WATCH", r"C:\stock_bot\IPC\micro_watch_strategy_shared.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S01_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    board_path: Path = Path(os.environ.get(
        "S01_MONEY_BOARD", r"C:\stock_bot\data\micro_rank_board.json"))
    minute_path: Path = Path(os.environ.get(
        "S01_MINUTE", r"C:\stock_bot\data\돈맥_1분봉.json"))
    name_path: Path = Path(os.environ.get(
        "S01_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S01_OUTPUT", r"C:\stock_bot\data\strategy_01_open_surge_signal_v2.json"))
    event_dir: Path = Path(os.environ.get(
        "S01_EVENT_DIR", r"C:\stock_bot\data\shadow"))
    html_path: Path = Path(os.environ.get(
        "S01_HTML", r"C:\stock_bot\보고서\새전략01_급상승_신호감시.html"))
    loop_sec: float = float(os.environ.get("S01_LOOP_SEC", "1.0"))
    max_snapshot_age_sec: float = float(os.environ.get("S01_SNAPSHOT_MAX_AGE", "5"))
    max_board_age_sec: float = float(os.environ.get("S01_BOARD_MAX_AGE", "10"))
    max_signals_per_code: int = int(os.environ.get("S01_MAX_CYCLES_PER_CODE", "2"))


@dataclass(frozen=True)
class ShadowPoint:
    ts: datetime
    code: str
    name: str
    previous_close: float
    price: float
    money_speed_5s: float
    money_speed_30s: float
    buy_money_cum: float
    sell_money_cum: float
    exact_flow: bool
    theme_leader: bool = False
    open_hint: float = 0.0
    board_fresh: bool = True
    order_book_fresh: bool = False
    book_bid_share: float = 0.0
    spread_bps: float = 0.0
    microprice_edge_bps: float = 0.0


@dataclass(frozen=True)
class Sample:
    ts: datetime
    price: float
    buy_money_cum: float
    sell_money_cum: float
    exact_flow: bool


@dataclass
class CodeState:
    open_price: float = 0.0
    high_so_far: float = 0.0
    low_so_far: float = 0.0          # ★[2026-07-31] 되돌림 판정의 기준점(당일 저점)
    low_time: str = ""
    below_open_seen: bool = False
    premarket_gap: bool = False
    rise_since: datetime | None = None
    last_price: float = 0.0
    last_ts: datetime | None = None
    emission_count: int = 0
    ready_latched: bool = False
    samples: Deque[Sample] = field(default_factory=lambda: deque(maxlen=45))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _parse_dt(value: Any, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _minute_opens(payload: Mapping[str, Any], today: str) -> Dict[str, float]:
    if str(payload.get("ts") or "").replace("-", "")[:8] != today:
        return {}
    return {
        str(code).zfill(6): _safe_float((row or {}).get("op"))
        for code, row in (payload.get("m") or {}).items()
    }


def _money_rows(payload: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(row.get("code") or "").zfill(6): row
        for row in (payload.get("all_items") or [])
        if row.get("code")
    }


# 공통 컨텍스트(strategy_common_candidate_context_v1)가 all_meta 에 실어주는 고저폭 지표.
# 신호 행에 붙여 기록한다. ★2026-07-31 부터 감시대상 제한에도 쓴다(아래 참조).
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
)
# ★[2026-07-31 친구님 지시] S01 감시대상을 고저폭 TOP30(hr_rank 실린 종목)으로 제한.
#   되돌림 진입으로 규칙을 바꿨기 때문에 고저폭이 유리해진다 —
#   일봉 1년 전수(12.6만건·비용 0.38% 차감):
#     저가+1% 매수 → 당일종가:  고저폭 밖 +1.251%/58.8%  vs  고저폭 5일↑ +4.343%/81.4%
#     (옛 규칙인 시가 매수는 반대로 -0.748% → -1.472% 로 악화됐다)
#   익일 고저폭이 5.87% → 14.06% 로 2.4배 크고, 다음날에도 10%↑ 움직일 확률이
#   12.5% → 72.0%. 되돌림을 노리려면 되돌릴 만큼 움직이는 종목이어야 한다.
#   안전장치: 고저폭 지표가 통째로 비면 제한하지 않는다(fail-open).
#   롤백: setx S01_HIGH_RANGE_ONLY NO + 신호기 재기동
S01_HIGH_RANGE_ONLY = os.environ.get("S01_HIGH_RANGE_ONLY", "YES").strip().upper() == "YES"


def _range_meta(*sources: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Any] = {}
    for source in sources:
        merged.update(source.get("all_meta") or {})
    output: Dict[str, Dict[str, Any]] = {}
    for code, row in merged.items():
        if not isinstance(row, Mapping):
            continue
        picked = {key: row[key] for key in RANGE_KEYS if row.get(key) is not None}
        if picked:
            output[str(code).zfill(6)] = picked
    return output


def _name_map(payload: Mapping[str, Any]) -> Dict[str, str]:
    raw = payload.get("map", payload)
    return {str(code).zfill(6): str(name) for code, name in raw.items()}


def load_live_points(
    config: ShadowConfig,
    now: datetime,
) -> tuple[list[ShadowPoint], str, int, Dict[str, Dict[str, Any]]]:
    watch = _read_json(config.watch_path)
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "") != today:
        return [], "WATCH_DATE_MISMATCH", 0, {}
    codes = {str(code).zfill(6) for code in (watch.get("codes") or [])}
    meta = watch.get("all_meta") or watch.get("meta") or {}
    snapshot = _read_json(config.snapshot_path)
    board = _read_json(config.board_path)
    board_ts = _parse_dt(board.get("ts"), datetime.min)
    board_fresh = abs((now - board_ts).total_seconds()) <= config.max_board_age_sec
    board_rows = _money_rows(board) if board_fresh else {}
    opens = _minute_opens(_read_json(config.minute_path), today)
    names = _name_map(_read_json(config.name_path))
    range_meta = _range_meta(watch)
    # ★[2026-07-31] 고저폭 TOP30 제한 — range_meta 는 hr_* 가 실린 종목만 담는다.
    #   비어 있으면(고저폭 목록 생성 실패) 제한하지 않는다(fail-open·위 주석 참조).
    if S01_HIGH_RANGE_ONLY and range_meta:
        codes = {c for c in codes if c in range_meta}
    points = _points_from_payload(
        codes, meta, snapshot, board_rows, opens, names, now, config, board_fresh
    )
    status = "LIVE" if points else "DATA_WAIT"
    return points, status, len(codes), range_meta


def _points_from_payload(
    codes: set[str],
    meta: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    board_rows: Mapping[str, Mapping[str, Any]],
    opens: Mapping[str, float],
    names: Mapping[str, str],
    now: datetime,
    config: ShadowConfig,
    board_fresh: bool,
) -> list[ShadowPoint]:
    points = []
    for code, raw in (snapshot.get("codes") or {}).items():
        code = str(code).zfill(6)
        if code not in codes or code not in meta:
            continue
        point = _to_point(
            code, raw or {}, board_rows.get(code, {}), meta.get(code, {}),
            opens, names, now, config, board_fresh,
        )
        if point is not None:
            points.append(point)
    return points


def _to_point(
    code: str,
    raw: Mapping[str, Any],
    money: Mapping[str, Any],
    meta: Mapping[str, Any],
    opens: Mapping[str, float],
    names: Mapping[str, str],
    now: datetime,
    config: ShadowConfig,
    board_fresh: bool,
) -> ShadowPoint | None:
    ts = _parse_dt(raw.get("ts"), datetime.min)
    if abs((now - ts).total_seconds()) > config.max_snapshot_age_sec:
        return None
    previous = _safe_float(meta.get("prev_close"))
    price = _safe_float(raw.get("cur"))
    buy_cum = _safe_float(raw.get("buy_money_cum"), -1.0)
    sell_cum = _safe_float(raw.get("sell_money_cum"), -1.0)
    if previous <= 0 or price <= 0:
        return None
    exact = board_fresh and buy_cum >= 0 and sell_cum >= 0
    order_book_fresh, book_bid_share, spread_bps, microprice_edge_bps = (
        _book_telemetry(raw, now, config.max_snapshot_age_sec)
    )
    return ShadowPoint(
        ts=ts, code=code, name=names.get(code, code),
        previous_close=previous, price=price,
        money_speed_5s=_safe_float(money.get("money_speed_5s")),
        money_speed_30s=_safe_float(money.get("money_speed_30s")),
        buy_money_cum=buy_cum, sell_money_cum=sell_cum,
        exact_flow=exact, open_hint=opens.get(code, 0.0),
        board_fresh=board_fresh,
        order_book_fresh=order_book_fresh,
        book_bid_share=book_bid_share,
        spread_bps=spread_bps,
        microprice_edge_bps=microprice_edge_bps,
    )

def _book_telemetry(
    raw: Mapping[str, Any],
    now: datetime,
    max_age_sec: float,
) -> tuple[bool, float, float, float]:
    ob_ts = _parse_dt(raw.get("ob_ts"), datetime.min)
    ask_total = _safe_float(raw.get("ask_tot"))
    bid_total = _safe_float(raw.get("bid_tot"))
    ask = abs(_safe_float(raw.get("best_ask_px")))
    bid = abs(_safe_float(raw.get("best_bid_px")))
    ask_qty = _safe_float(raw.get("best_ask_qty"))
    bid_qty = _safe_float(raw.get("best_bid_qty"))
    fresh = (
        abs((now - ob_ts).total_seconds()) <= max_age_sec
        and ask_total > 0
        and bid_total > 0
    )
    if not fresh:
        return False, 0.0, 0.0, 0.0
    bid_share = bid_total / (ask_total + bid_total)
    if ask <= bid or bid <= 0 or ask_qty <= 0 or bid_qty <= 0:
        return True, bid_share, 0.0, 0.0
    midpoint = (ask + bid) / 2.0
    microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
    spread_bps = (ask - bid) / midpoint * 10_000.0
    microprice_edge_bps = (microprice - midpoint) / midpoint * 10_000.0
    return True, bid_share, spread_bps, microprice_edge_bps


class OpenSurgeShadowMonitor:
    def __init__(
        self,
        strategy: OpenSurgeBuyStrategy | None = None,
        *,
        max_signals_per_code: int = 2,
    ) -> None:
        self.strategy = strategy or OpenSurgeBuyStrategy()
        if max_signals_per_code != 2:
            raise ValueError("Strategy 01 requires exactly two opportunities per code")
        self.max_signals_per_code = max_signals_per_code
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []

    def restore_emitted(self, payload: Mapping[str, Any], today: str) -> None:
        if str(payload.get("date") or "") != today:
            return
        for row in payload.get("signals") or []:
            code = str(row.get("code") or "").zfill(6)
            if code:
                state = self.states.setdefault(code, CodeState())
                state.emission_count = max(
                    state.emission_count,
                    int(row.get("signal_sequence") or state.emission_count + 1),
                )
                self.signals.append(dict(row))
        for row in payload.get("candidates") or []:
            code = str(row.get("code") or "").zfill(6)
            if code:
                state = self.states.setdefault(code, CodeState())
                state.ready_latched = str(row.get("action") or "") == "BUY_READY"

    def process_points(self, points: Iterable[ShadowPoint]) -> list[Dict[str, Any]]:
        new_signals = []
        for point in points:
            row, fired = self.process_point(point)
            self.latest[point.code] = row
            if fired:
                # ★[2026-07-29 친구님 승인 "S01 고저폭 기록 누락도 고쳐"] 사본을 하나만 만들어
                #   누적목록(self.signals=출력 JSON)과 반환목록(new_signals=CSV·hr_ 병합 대상)이
                #   같은 객체를 공유하게 한다. 종전엔 사본을 둘 따로 떠서 tick() 의 고저폭(hr_*)
                #   병합이 반환목록에만 닿고 출력 JSON 의 signals 에는 영영 안 실렸다
                #   (S02·S04·S05 는 병합 후 append 라 정상). 8/3 고저폭 보고 자료용.
                #   롤백: *.bak_20260729_s01hr
                emitted = row.copy()
                self.signals.append(emitted)
                new_signals.append(emitted)
        return new_signals

    def process_point(self, point: ShadowPoint) -> tuple[Dict[str, Any], bool]:
        state = self.states.setdefault(point.code, CodeState())
        if point.ts.time() < time(9, 0):
            state.premarket_gap |= point.price >= point.previous_close * 1.03
            return self._row(point, "WAIT", "PREMARKET_TRACK", state), False
        if state.open_price <= 0:
            state.open_price = point.open_hint or point.price
        self._update_state(state, point)
        buy_ratio, exact_flow, flow_observation_sec = self._flow_ratio(state)
        rising_sec = self._rising_seconds(state, point.ts)
        observation = OpenSurgeObservation(
            observed_at=_as_kst(point.ts), code=point.code,
            previous_close=Decimal(str(point.previous_close)),
            open_price=Decimal(str(state.open_price)),
            current_price=Decimal(str(point.price)),
            high_so_far=Decimal(str(state.high_so_far)),
            low_so_far=Decimal(str(state.low_so_far)),
            buy_money_ratio=Decimal(str(buy_ratio)),
            money_speed_5s=Decimal(str(point.money_speed_5s)),
            money_speed_30s=Decimal(str(point.money_speed_30s)),
            price_rising_sec=int(rising_sec),
            flow_observation_sec=Decimal(str(flow_observation_sec)),
            exact_flow=exact_flow,
            in_prior_value_pool=True,
            in_premarket_gap_pool=state.premarket_gap,
            below_open_seen=state.below_open_seen,
            theme_leader=point.theme_leader,
        )
        decision = self.strategy.evaluate(observation)
        row = self._row(
            point, decision.action.value, decision.reason, state,
            buy_ratio, rising_sec, flow_observation_sec,
            float(decision.gap_pct), decision.priority_bonus,
        )
        ready = decision.action is BuyAction.BUY_READY
        fired = (
            ready
            and not state.ready_latched
            and state.emission_count < self.max_signals_per_code
        )
        if fired:
            state.emission_count += 1
            row["signal_sequence"] = state.emission_count
        state.ready_latched = ready
        return row, fired

    @staticmethod
    def _update_state(state: CodeState, point: ShadowPoint) -> None:
        if point.price < state.open_price:
            state.below_open_seen = True
        state.high_so_far = max(state.high_so_far, state.open_price, point.price)
        # ★[2026-07-31] 당일 저점 갱신 — 시가도 후보에 넣는다(개장가가 저점일 수 있다).
        if state.low_so_far <= 0:
            state.low_so_far = min(state.open_price, point.price) or point.price
            state.low_time = point.ts.strftime("%H:%M:%S")
        elif point.price < state.low_so_far:
            state.low_so_far = point.price
            state.low_time = point.ts.strftime("%H:%M:%S")
        if state.last_ts is not None:
            if point.price > state.last_price and state.rise_since is None:
                state.rise_since = state.last_ts
            elif point.price < state.last_price:
                state.rise_since = None
        state.last_price, state.last_ts = point.price, point.ts
        state.samples.append(Sample(
            point.ts, point.price, point.buy_money_cum,
            point.sell_money_cum, point.exact_flow,
        ))
        cutoff = point.ts.timestamp() - 35.0
        while state.samples and state.samples[0].ts.timestamp() < cutoff:
            state.samples.popleft()

    @staticmethod
    def _flow_ratio(state: CodeState) -> tuple[float, bool, float]:
        if len(state.samples) < 2:
            return 0.0, False, 0.0
        current = state.samples[-1]
        target = current.ts.timestamp() - 10.0
        eligible = [
            sample for sample in list(state.samples)[:-1]
            if sample.ts.timestamp() <= target
        ]
        base = eligible[-1] if eligible else state.samples[0]
        buy = current.buy_money_cum - base.buy_money_cum
        sell = current.sell_money_cum - base.sell_money_cum
        exact = current.exact_flow and base.exact_flow and buy >= 0 and sell >= 0
        total = buy + sell
        observed_sec = max(0.0, (current.ts - base.ts).total_seconds())
        return (buy / total if exact and total > 0 else 0.0), exact, observed_sec

    @staticmethod
    def _rising_seconds(state: CodeState, now: datetime) -> float:
        if state.rise_since is None:
            return 0.0
        return max(0.0, (now - state.rise_since).total_seconds())

    @staticmethod
    def _row(
        point: ShadowPoint,
        action: str,
        reason: str,
        state: CodeState,
        buy_ratio: float = 0.0,
        rising_sec: float = 0.0,
        flow_observation_sec: float = 0.0,
        gap_pct: float = 0.0,
        priority_bonus: int = 0,
    ) -> Dict[str, Any]:
        return {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": point.code, "name": point.name,
            "action": action, "reason": reason,
            "price": point.price, "open": state.open_price,
            "high_so_far": state.high_so_far,
            # ★[2026-07-31] 되돌림 판정 근거 — 저점·저점시각·깊이·반등폭
            "low_so_far": state.low_so_far, "low_time": state.low_time,
            "dip_pct": (round((state.low_so_far / state.open_price - 1) * 100, 2)
                        if state.open_price > 0 and state.low_so_far > 0 else 0.0),
            "rebound_pct": (round((point.price / state.low_so_far - 1) * 100, 2)
                            if state.low_so_far > 0 else 0.0),
            "gap_pct": round(gap_pct, 3),
            "buy_ratio": round(buy_ratio, 4),
            "money_speed_5s": round(point.money_speed_5s, 1),
            "money_speed_30s": round(point.money_speed_30s, 1),
            "rising_sec": round(rising_sec, 1),
            "flow_observation_sec": round(flow_observation_sec, 1),
            "order_book_fresh": point.order_book_fresh,
            "book_bid_share": round(point.book_bid_share, 4),
            "spread_bps": round(point.spread_bps, 2),
            "microprice_edge_bps": round(point.microprice_edge_bps, 2),
            "below_open_seen": state.below_open_seen,
            "premarket_gap": state.premarket_gap,
            "theme_bonus": priority_bonus,
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
        }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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


def _html_board(payload: Mapping[str, Any]) -> str:
    rows = sorted(
        payload.get("candidates") or [],
        key=lambda row: (row.get("action") == "BUY_READY", row.get("money_speed_5s", 0)),
        reverse=True,
    )
    body = "".join(
        "<tr><td>{}</td><td>{} {}</td><td>{}</td><td>{}</td>"
        "<td>{:,.0f}</td><td>{:.1%}</td><td>{:.1f}s</td><td>{}</td></tr>".format(
            html.escape(str(row.get("ts", ""))[-8:]),
            html.escape(str(row.get("code", ""))),
            html.escape(str(row.get("name", ""))),
            html.escape(str(row.get("action", ""))),
            html.escape(str(row.get("reason", ""))),
            float(row.get("price", 0)),
            float(row.get("buy_ratio", 0)),
            float(row.get("rising_sec", 0)),
            "👑" if row.get("theme_bonus") else "",
        )
        for row in rows
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="2"><title>새전략 01 급상승 신호감시</title>
<style>body{{font:16px sans-serif;background:#111;color:#eee;margin:24px}}
h1{{color:#76e6a5}}.warn{{color:#ffce67}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px;border-bottom:1px solid #444;text-align:right}}
th:nth-child(2),td:nth-child(2),th:nth-child(4),td:nth-child(4){{text-align:left}}
.ready{{color:#76e6a5;font-weight:bold}}</style></head><body>
<h1>새전략 01 장초반 급상승 — 신호전용</h1>
<p class="warn">실계좌 주문 기능 없음 · 상태 {html.escape(str(payload.get("status")))}</p>
<p>갱신 {html.escape(str(payload.get("updated_at")))} · 감시 {payload.get("watch_count", 0)}종목
· 수신 {payload.get("point_count", 0)}종목 · 오늘 신호 {len(payload.get("signals") or [])}개</p>
<table><thead><tr><th>시각</th><th>종목</th><th>판정</th><th>이유</th>
<th>현재가</th><th>매수비</th><th>상승</th><th>테마</th></tr></thead>
<tbody>{body}</tbody></table></body></html>"""


class ShadowRuntime:
    def __init__(self, config: ShadowConfig) -> None:
        self.config = config
        self.monitor = OpenSurgeShadowMonitor(
            max_signals_per_code=config.max_signals_per_code)
        existing = _read_json(config.output_path)
        self.monitor.restore_emitted(existing, datetime.now().strftime("%Y%m%d"))

    def tick(self, now: datetime) -> Dict[str, Any]:
        points, status, watch_count, range_meta = load_live_points(
            self.config, now)
        signals = self.monitor.process_points(points)
        for _code, _row in self.monitor.latest.items():
            if isinstance(_row, dict):
                _row.update(range_meta.get(str(_code).zfill(6)) or {})
        for _row in signals:
            if isinstance(_row, dict):
                _row.update(range_meta.get(str(_row.get("code") or "")) or {})
        payload = {
            "schema": "strategy_01_open_surge_signal_v2",
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "status": status,
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "watch_count": watch_count,
            "point_count": len(points),
            "signals": self.monitor.signals,
            "candidates": list(self.monitor.latest.values()),
        }
        _atomic_text(self.config.output_path, json.dumps(
            payload, ensure_ascii=False, indent=2))
        _atomic_text(self.config.html_path, _html_board(payload))
        event_path = self.config.event_dir / f"strategy_01_open_surge_signal_{now:%Y%m%d}.csv"
        _append_events(event_path, signals)
        return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    runtime = ShadowRuntime(ShadowConfig())
    while True:
        now = datetime.now()
        payload = runtime.tick(now)
        print(json.dumps({
            "updated_at": payload["updated_at"], "status": payload["status"],
            "watch_count": payload["watch_count"], "point_count": payload["point_count"],
            "signal_count": len(payload["signals"]),
        }, ensure_ascii=False), flush=True)
        if args.once or now.weekday() >= 5 or now.time() >= time(9, 20):
            return 0
        time_module.sleep(max(0.2, runtime.config.loop_sec))


if __name__ == "__main__":
    raise SystemExit(main())

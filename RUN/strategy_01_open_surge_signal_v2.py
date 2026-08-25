# -*- coding: utf-8 -*-
"""새전략 01 장초반 급상승 초입 신호전용 실시간 감시기."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import sys
import time as time_module
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, Mapping
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

EARLY_ENTRY_STAGE = "EARLY_FLOW"
STRONG_ENTRY_STAGE = "STRONG_FLOW"
EARLY_REBOUND_MIN_PCT = 1.0
EARLY_REBOUND_MAX_PCT = 1.5
EARLY_MIN_RISING_SEC = 5.0
STRONG_REBOUND_MIN_PCT = 1.5
STRONG_REBOUND_MAX_PCT = 2.5
SURGE_RECENT_SEC = 5.0
SURGE_PREVIOUS_SEC = 10.0
SURGE_MIN_BUY_RATE = 1_666_667.0
SURGE_BUY_ACCEL_MULT = 2.5
SURGE_BUY_OVER_SELL_MULT = 1.5
SURGE_MIN_VOLUME_RATE = 50.0
SURGE_VOLUME_ACCEL_MULT = 2.0
SURGE_MIN_CHE_STR = 105.0
SURGE_MIN_CHE_RISE = 5.0
SURGE_CONFIRM_TICKS = 2
from ma3_common_v1 import ma3_rows
# ★[2026-08-10] 시가 위 강세 종목은 실주문에 바로 연결하지 않고 별도 그림자로만 기록한다.
ABOVE_OPEN_REBREAK_SHADOW = (
    os.environ.get("S01_ABOVE_OPEN_REBREAK_SHADOW", "YES").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)
from strategy_01_entry_runtime_v3 import EntryRuntimeV3
from approval_manifest_writer_v1 import live_feature_enabled

ROCKET_LIVE_STAGE = "ROCKET"
ROCKET_LIVE_FEATURE = "S01_ROCKET"
# [S01 ABOVE-OPEN LIVE OBSERVATION 2026-08-14 owner approval]
# Five trading sessions after the 2026-08-17 substitute holiday.  The
# detector stays unchanged; only an already-confirmed shadow row can be
# promoted, at most once per day, for one share.  It expires automatically.
ABOVE_OPEN_REBREAK_LIVE_DATES = frozenset({
    "20260818", "20260819", "20260820", "20260821", "20260824",
})
ABOVE_OPEN_REBREAK_LIVE_START = time(9, 0)
ABOVE_OPEN_REBREAK_LIVE_END = time(9, 5)
ABOVE_OPEN_REBREAK_LIVE_MAX_SPREAD_BPS = 35.0
ABOVE_OPEN_REBREAK_LIVE_STAGE = "ABOVE_OPEN_REBREAK_LIVE"
# [S01 09:03 DELAY SHADOW 2026-08-18 owner approval]
# Compare only; it never changes or promotes a live signal.
DELAY_0903_SHADOW_DATES = frozenset({
    "20260819", "20260820", "20260821", "20260824", "20260825",
})
DELAY_0903_CUTOFF = time(9, 3)
from listed_turnover_common_v1 import listed_turnover_metrics

# ★[2026-08-06 친구님 지시 "1·2가 매매 방법은 같지만 매수 깊이만 서로 다른 거야"]
#   1번의 '저점 찾는 법'을 2번 모듈에 맡기는 다리.
#   판정을 베끼지 않는다 — 2번 모듈을 그대로 부른다. 2번이 바뀌면 1번도 자동으로 따라간다.
#   같은 방식으로 재생기(replay_buy_method_v1.py)가 8/6 실제 신호 4건을 소수점까지 재현했다.
#
#   같아지는 것 : 저점 찾는 법(죽은저점·재무장·60초 관찰·속도역전·1차반등 1.0/추격상한 2.0)
#   그대로인 것 : 매수 깊이 띠(-3%~+3%) · 시간대(09:00~09:20) · 슬롯 · 매도 · 감사기록
#
# ★[2026-08-10 배선 결함 수정]
#   기본값을 NO 로 되돌린다. S01 은 -3% 보다 깊으면 S02 영역으로 넘기는데,
#   연결된 S02 판정기는 아침에 시가 대비 최소 -3% 하락부터 추적을 시작한다.
#   두 관문의 교집합이 사실상 -3% 한 점뿐이라 S01 신호가 구조적으로 막혔다.
#   S01 기본 동작은 자체 5~10초 흐름 확인 + EARLY/STRONG 2단계 진입이다.
#   S02 다리는 비교 실험용으로만 남긴다.
#   실험 켜기: setx S01_USE_S02_LOWFIND YES   (프로세스 재기동 후 적용)
USE_S02_LOWFIND = (
    os.environ.get("S01_USE_S02_LOWFIND", "NO").strip().upper()
    in {"YES", "Y", "1", "TRUE", "ON"}
)


def _load_s02():
    """2번 판정기와 그 입력형을 늦게 불러온다(꺼져 있으면 아예 안 부른다)."""
    from 저점매수_매도소진 import MarketPoint  # noqa: E402
    import strategy_02_low_buy_signal_v1 as S02  # noqa: E402
    return MarketPoint, S02


def _to_market_point(point: ShadowPoint, market_point_cls):
    """1번 틱을 2번 틱으로 옮겨 담는다. 값을 새로 만들지 않고 그대로 옮기기만 한다."""
    return market_point_cls(
        ts=point.ts,
        price=point.price,
        cum_vol=point.cum_vol,
        che_str=point.che_str,
        ask_tot=point.ask_tot,
        bid_tot=point.bid_tot,
        buy_money_cum=point.buy_money_cum,
        sell_money_cum=point.sell_money_cum,
        buy_vol_cum=point.buy_vol_cum,
        sell_vol_cum=point.sell_vol_cum,
    )
SURGE_CONFIRM_MAX_GAP_SEC = 2.0


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
    rotation_state_path: Path = Path(os.environ.get(
        "S01_ROTATION_STATE",
        r"C:\stock_bot\data\strategy_01_rotation_state_v2.json",
    ))
    trend_priority_path: Path = Path(os.environ.get(
        "S01_TREND_PRIORITY_BOARD",
        r"C:\stock_bot\data\s01_trend_priority_board_v1.json",
    ))
    entry_v3_volume_path: Path = Path(os.environ.get(
        "S01_ENTRY_V3_VOLUME_BASELINE",
        r"C:\stock_bot\data\s01_open_volume_baseline_v3.json",
    ))
    entry_v3_replay_dir: Path = Path(os.environ.get(
        "S01_ENTRY_V3_REPLAY_DIR",
        r"C:\stock_bot\data\s01_entry_v3_exact_replay",
    ))
    adaptive_confirm_mode: str = os.environ.get(
        "S01_ADAPTIVE_CONFIRM_MODE", "SHADOW"
    ).strip().upper()


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
    high_range_rank: int = 0
    high_range_ready: bool = False
    che_str: float = 0.0
    cum_vol: float = 0.0
    theme_leader: bool = False
    open_hint: float = 0.0
    board_fresh: bool = True
    order_book_fresh: bool = False
    book_bid_share: float = 0.0
    spread_bps: float = 0.0
    microprice_edge_bps: float = 0.0
    # ★[2026-08-06] 2번 저점찾기에 넘기려고 실어 나른다. 스냅샷엔 원래 있던 값이고
    #   1번 자신의 판정에는 안 쓴다(기본값을 두어 종전 동작은 그대로다).
    #   거래량 누적은 '모르면 -1.0' 이 2번의 규약이다(없으면 그 조건을 통과시킨다).
    ask_tot: float = 0.0
    bid_tot: float = 0.0
    buy_vol_cum: float = -1.0
    sell_vol_cum: float = -1.0
    auction_expected_px: float = 0.0
    auction_expected_qty: float = 0.0


@dataclass(frozen=True)
class Sample:
    ts: datetime
    price: float
    buy_money_cum: float
    sell_money_cum: float
    exact_flow: bool
    che_str: float
    cum_vol: float


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
    emitted_stages: set[str] = field(default_factory=set)
    early_confirm_hits: int = 0
    early_last_confirm_ts: datetime | None = None
    above_open_peak: float = 0.0
    above_open_pullback_low: float = 0.0
    above_open_pullback_seen: bool = False
    above_open_confirm_hits: int = 0
    above_open_last_confirm_ts: datetime | None = None
    above_open_shadow_emitted: bool = False
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


def adaptive_confirm_ticks(
    state_payload: Mapping[str, Any], now: datetime,
) -> int:
    """Use three confirmations after two consecutive S01 opening losses."""
    closed: list[tuple[datetime, float]] = []
    for raw in state_payload.get("history") or []:
        if not isinstance(raw, Mapping) or raw.get("phase") != "CLOSED":
            continue
        if not bool(raw.get("real")):
            continue
        exit_at = _parse_dt(raw.get("exit_at"), now)
        if exit_at.date() != now.date() or not time(9, 0) <= exit_at.time() < time(9, 20):
            continue
        closed.append((
            exit_at,
            _safe_float(raw.get("estimated_net_return_pct_before_slippage")),
        ))
    closed.sort(key=lambda item: item[0])
    two_losses_seen = any(
        previous[1] < 0 and current[1] < 0
        for previous, current in zip(closed, closed[1:])
    )
    return 3 if two_losses_seen else 2


def entry_v3_loss_pause_until(
    state_payload: Mapping[str, Any], now: datetime,
) -> datetime | None:
    """Five-minute pause after the latest two consecutive real S01 losses."""
    closed: list[tuple[datetime, float]] = []
    for raw in state_payload.get("history") or []:
        if not isinstance(raw, Mapping) or raw.get("phase") != "CLOSED" or not bool(raw.get("real")):
            continue
        exit_at = _parse_dt(raw.get("exit_at"), now)
        if exit_at.date() != now.date():
            continue
        closed.append((exit_at, _safe_float(raw.get("estimated_net_return_pct_before_slippage"))))
    closed.sort(key=lambda item: item[0])
    if len(closed) < 2 or closed[-2][1] >= 0 or closed[-1][1] >= 0:
        return None
    pause_until = closed[-1][0] + timedelta(minutes=5)
    return pause_until if now < pause_until else None


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
    "hr_money_speed_ratio", "hr_turnover_pct", "hr_volatility_quality",
    "hr_quality_risks", "hr_live_status",
)
# ★[2026-08-13 친구님 승인] S01 감시대상을 고저폭 TOP40으로 제한.
#   되돌림 진입으로 규칙을 바꿨기 때문에 고저폭이 유리해진다 —
#   일봉 1년 전수(12.6만건·비용 0.38% 차감):
#     저가+1% 매수 → 당일종가:  고저폭 밖 +1.251%/58.8%  vs  고저폭 5일↑ +4.343%/81.4%
#     (옛 규칙인 시가 매수는 반대로 -0.748% → -1.472% 로 악화됐다)
#   익일 고저폭이 5.87% → 14.06% 로 2.4배 크고, 다음날에도 10%↑ 움직일 확률이
#   12.5% → 72.0%. 되돌림을 노리려면 되돌릴 만큼 움직이는 종목이어야 한다.
#   안전장치: 고저폭 지표가 통째로 비면 제한하지 않는다(fail-open).
#   롤백: setx S01_HIGH_RANGE_ONLY NO + 신호기 재기동
S01_HIGH_RANGE_ONLY = os.environ.get("S01_HIGH_RANGE_ONLY", "YES").strip().upper() == "YES"


def _is_top40_range_row(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False
    try:
        rank = int(row.get("hr_rank"))
    except (TypeError, ValueError):
        return False
    return 1 <= rank <= 40


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


def _trend_priority_meta(payload: Mapping[str, Any], today: str) -> Dict[str, Dict[str, Any]]:
    """Return only same-day, replayable A/B/C metadata; stale data fails open."""
    if (
        str(payload.get("schema") or "") != "s01_trend_priority_board_v1"
        or str(payload.get("for_date") or "") != today
        or str(payload.get("status") or "") != "READY"
    ):
        return {}
    output: Dict[str, Dict[str, Any]] = {}
    for code, raw in (payload.get("codes") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        tier = str(raw.get("s01_trend_tier") or "C").upper()
        if tier not in {"A", "B", "C"}:
            tier = "C"
        row = dict(raw)
        row["s01_trend_tier"] = tier
        row["s01_trend_source_date"] = str(payload.get("source_date") or "")
        output[str(code).zfill(6)] = row
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
    trend_meta = _trend_priority_meta(
        _read_json(config.trend_priority_path), today,
    )
    for code, row in trend_meta.items():
        range_meta.setdefault(code, {}).update(row)
    # ★[2026-08-13] 고저폭 TOP40 제한 — 실제 순위값까지 확인한다.
    #   비어 있으면(고저폭 목록 생성 실패) 제한하지 않는다(fail-open·위 주석 참조).
    if S01_HIGH_RANGE_ONLY and range_meta:
        codes = {c for c in codes if _is_top40_range_row(range_meta.get(c))}
    points = _points_from_payload(
        codes, meta, snapshot, board_rows, opens, names, now, config, board_fresh
    )
    points = [
        replace(
            point,
            high_range_rank=int(_safe_float(
                (range_meta.get(point.code) or {}).get("hr_rank")
            )),
            high_range_ready=_is_top40_range_row(range_meta.get(point.code)),
        )
        for point in points
    ]
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
        # ★[공통배관 2026-08-07 친구님 "전 전략이 다 같이 써야 돼"]
        #   분봉 시가가 없으면 거래소 시가(스냅샷 op = FID 16, 8/4 배선 통로)로 메운다.
        #   분봉 값이 있으면 종전 그대로 — 비교 기준선 보존.
        exact_flow=exact, open_hint=opens.get(code, 0.0) or _safe_float(raw.get("op")),
        che_str=_safe_float(raw.get("che_str")),
        cum_vol=_safe_float(raw.get("cum_vol")),
        board_fresh=board_fresh,
        order_book_fresh=order_book_fresh,
        book_bid_share=book_bid_share,
        spread_bps=spread_bps,
        microprice_edge_bps=microprice_edge_bps,
        # ★[2026-08-06] 2번 저점찾기용. 스냅샷에 이미 있던 열을 그대로 옮긴다.
        ask_tot=_safe_float(raw.get("ask_tot")),
        bid_tot=_safe_float(raw.get("bid_tot")),
        buy_vol_cum=_safe_float(raw.get("buy_vol_cum"), -1.0),
        sell_vol_cum=_safe_float(raw.get("sell_vol_cum"), -1.0),
        auction_expected_px=_safe_float(raw.get("auction_expected_px")),
        auction_expected_qty=_safe_float(raw.get("auction_expected_qty")),
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
        ma3_provider: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.strategy = strategy or OpenSurgeBuyStrategy()
        self.ma3_provider = ma3_provider or ma3_rows
        if max_signals_per_code != 2:
            raise ValueError("Strategy 01 requires exactly two opportunities per code")
        self.max_signals_per_code = max_signals_per_code
        self.confirm_ticks = SURGE_CONFIRM_TICKS
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []
        self.shadow_signals: list[Dict[str, Any]] = []
        self._pending_shadow_signals: list[Dict[str, Any]] = []
        # ★[2026-08-06] 2번 저점찾기를 쓸 때만 만든다. 종목마다 판정기 하나씩.
        self._s02_cls = None
        self._s02_mod = None
        self._s02_monitors: Dict[str, Any] = {}
        if USE_S02_LOWFIND:
            self._s02_cls, self._s02_mod = _load_s02()

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
                stage = str(row.get("entry_stage") or "")
                if stage:
                    state.emitted_stages.add(stage)
                else:
                    state.emitted_stages.update(
                        {EARLY_ENTRY_STAGE, STRONG_ENTRY_STAGE})
                self.signals.append(dict(row))
        for row in payload.get("candidates") or []:
            code = str(row.get("code") or "").zfill(6)
            if code:
                state = self.states.setdefault(code, CodeState())
                state.ready_latched = str(row.get("action") or "") == "BUY_READY"
        for row in payload.get("shadow_signals") or []:
            code = str(row.get("code") or "").zfill(6)
            if code:
                state = self.states.setdefault(code, CodeState())
                state.above_open_shadow_emitted = True
                self.shadow_signals.append(dict(row))

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
        if ABOVE_OPEN_REBREAK_SHADOW:
            self._track_above_open_rebreak_shadow(point, state, row)
        if USE_S02_LOWFIND:
            return self._process_with_s02_lowfind(point, state, row, decision)
        if getattr(self.strategy, "staged_entries", False):
            return self._process_staged_entry(
                point, state, row, decision.action is BuyAction.BUY_READY,
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

    def drain_shadow_signals(self) -> list[Dict[str, Any]]:
        rows = self._pending_shadow_signals
        self._pending_shadow_signals = []
        return rows

    # ★[2026-08-06] 1번의 '구조 관문'에서 걸린 사유들. 여기서 걸리면 2번에게 사도 되냐고
    #   물어보지도 않는다. 이 목록의 마지막이 깊이 띠(DIP_TOO_DEEP_S02_ZONE)이고,
    #   그 뒤의 사유들(반등·추격·돈흐름)이 바로 2번이 대신할 '저점 찾는 법'이다.
    S01_GATE_STOP_REASONS = frozenset({
        "OUTSIDE_ENTRY_WINDOW", "UNIVERSE_BLOCK", "NOT_IN_OPENING_POOL",
        "PRICE_BELOW_10000", "DAY_LOW_NOT_READY", "DIP_TOO_DEEP_S02_ZONE",
    })

    def _process_with_s02_lowfind(self, point, state, row, decision):
        """저점 찾기를 2번 모듈에 맡긴다(친구님: 방법은 같고 깊이만 다르다).

        1번의 관문(시간창·유니버스·가격·갭·깊이 띠)은 그대로 건다.
        2번에게는 매 틱을 빠짐없이 먹인다 — 저점 추적이 끊기면 죽은저점·재무장이 망가진다.
        다만 관문을 통과한 틱에서만 신호를 허용한다(allow_signal).
        """
        gate_ok = decision.reason not in self.S01_GATE_STOP_REASONS
        mon = self._s02_monitors.get(point.code)
        if mon is None:
            mon = self._s02_mod.LowBuySignalMonitor()
            self._s02_monitors[point.code] = mon
        s02_row, hit = mon.process_point(
            point.code, point.name, _to_market_point(point, self._s02_cls),
            allow_signal=gate_ok,
            # 1번 창(09:00~09:20)은 전부 09:30 이전이라 2번은 '시가 기준'으로 판정한다.
            # 같은 값을 두 곳에 주면 재현이 깨진다(재생기에서 확인한 사고).
            open_price=state.open_price,
            session_high=state.high_so_far,
        )
        s02_row = s02_row or {}
        row["s02_lowfind"] = "Y"
        row["s02_gate_ok"] = "Y" if gate_ok else "N"
        row["s02_reason"] = str(s02_row.get("reason") or "")
        row["s02_anchor_low"] = s02_row.get("anchor_low")
        if not hit or state.emission_count >= self.max_signals_per_code:
            return row, False
        state.emission_count += 1
        row.update({
            "action": BuyAction.BUY_READY.value,
            "reason": "S02_LOWFIND_CONFIRMED",
            "entry_stage": "S02_LOWFIND",
            "requested_quantity": 1,
            "signal_sequence": state.emission_count,
        })
        return row, True

    def _track_above_open_rebreak_shadow(
        self, point: ShadowPoint, state: CodeState, row: Dict[str, Any],
    ) -> None:
        """시가 위 첫 되밀림 뒤 재돌파를 기록만 한다. 실주문 신호는 만들지 않는다."""
        row["above_open_rebreak"] = "TRACKING"
        if (
            point.ts.time() < time(9, 0)
            or point.ts.time() >= time(9, 20)
            or state.open_price <= 0
            or state.low_so_far < state.open_price
            or state.above_open_shadow_emitted
        ):
            row["above_open_rebreak"] = "INELIGIBLE"
            return

        if state.above_open_peak <= 0:
            state.above_open_peak = max(state.open_price, point.price)
            return

        if not state.above_open_pullback_seen:
            if point.price > state.above_open_peak:
                state.above_open_peak = point.price
                return
            advance_pct = (
                (state.above_open_peak / state.open_price - 1.0) * 100.0
            )
            # 기존 EARLY 하한(1%)을 그대로 써서 새 퍼센트 문턱을 만들지 않는다.
            if advance_pct >= EARLY_REBOUND_MIN_PCT and point.price < state.above_open_peak:
                state.above_open_pullback_seen = True
                state.above_open_pullback_low = point.price
                row["above_open_rebreak"] = "PULLBACK_SEEN"
            return

        state.above_open_pullback_low = min(
            state.above_open_pullback_low or point.price, point.price)
        row["above_open_peak"] = round(state.above_open_peak, 4)
        row["above_open_pullback_low"] = round(state.above_open_pullback_low, 4)
        if point.price < state.above_open_peak:
            state.above_open_confirm_hits = 0
            state.above_open_last_confirm_ts = None
            row["above_open_rebreak"] = "WAIT_REBREAK"
            return

        if not self._surge_flow_ready(state, point):
            state.above_open_confirm_hits = 0
            state.above_open_last_confirm_ts = None
            row["above_open_rebreak"] = "REBREAK_FLOW_WAIT"
            return

        if (
            state.above_open_last_confirm_ts is None
            or (point.ts - state.above_open_last_confirm_ts).total_seconds()
            > SURGE_CONFIRM_MAX_GAP_SEC
        ):
            state.above_open_confirm_hits = 1
        else:
            state.above_open_confirm_hits += 1
        state.above_open_last_confirm_ts = point.ts
        row["above_open_confirm_hits"] = state.above_open_confirm_hits
        if state.above_open_confirm_hits < self.confirm_ticks:
            row["above_open_rebreak"] = "REBREAK_CONFIRM_WAIT"
            return

        state.above_open_shadow_emitted = True
        row["above_open_rebreak"] = "SHADOW_READY"
        # The live observation is still an S01 entry.  Capture the exact same
        # fail-closed 3-minute MA gate used by EARLY/STRONG before promotion.
        self._ma3_entry_trend_ready(point, row)
        shadow = row.copy()
        shadow.update({
            "action": "SHADOW_READY",
            "reason": "ABOVE_OPEN_REBREAK_CONFIRMED",
            "entry_stage": "ABOVE_OPEN_REBREAK_SHADOW",
            "requested_quantity": 0,
            "mode": "SHADOW_ORDER_ZERO",
        })
        self.shadow_signals.append(shadow)
        self._pending_shadow_signals.append(shadow)

    def _process_staged_entry(
        self,
        point: ShadowPoint,
        state: CodeState,
        row: Dict[str, Any],
        strong_flow_ready: bool,
    ) -> tuple[Dict[str, Any], bool]:
        rebound_pct = (
            (point.price / state.low_so_far - 1.0) * 100.0
            if state.low_so_far > 0 else 0.0
        )
        stage = ""
        if (
            STRONG_ENTRY_STAGE not in state.emitted_stages
            and EARLY_ENTRY_STAGE not in state.emitted_stages
            and self._early_flow_ready(state, point, rebound_pct)
        ):
            stage = EARLY_ENTRY_STAGE
            row["reason"] = "MONEY_SURGE_ONSET"
        elif (
            STRONG_ENTRY_STAGE not in state.emitted_stages
            and strong_flow_ready
            and STRONG_REBOUND_MIN_PCT <= rebound_pct <= STRONG_REBOUND_MAX_PCT
        ):
            stage = STRONG_ENTRY_STAGE
            row["reason"] = "STRONG_FLOW_CONFIRMED"

        if stage and not self._ma3_entry_trend_ready(point, row):
            return row, False
        if not stage or state.emission_count >= self.max_signals_per_code:
            return row, False
        state.emission_count += 1
        state.emitted_stages.add(stage)
        row.update({
            "action": BuyAction.BUY_READY.value,
            "entry_stage": stage,
            "requested_quantity": 1,
            "signal_sequence": state.emission_count,
        })
        return row, True

    def _ma3_entry_trend_ready(
        self, point: ShadowPoint, row: Dict[str, Any],
    ) -> bool:
        ma3 = self.ma3_provider(point.code)
        if not ma3:
            row.update({
                "reason": "MA3_ENTRY_TREND_DATA_MISSING",
                "ma3_entry_trend_ready": False,
                "ma5_value": 0.0,
                "ma5_prev_value": 0.0,
                "ma10_value": 0.0,
                "ma3_source": "",
            })
            return False
        ma5 = _safe_float(ma3.get("ma5"))
        ma5_prev = _safe_float(ma3.get("ma5_prev"))
        ma10 = _safe_float(ma3.get("ma10"))
        ready = bool(
            ma5 > 0 and ma5_prev > 0 and ma10 > 0
            and point.price > ma5 and ma5 > ma5_prev
            and point.price >= ma10
        )
        row.update({
            "ma3_entry_trend_ready": ready,
            "ma5_value": round(ma5, 4),
            "ma5_prev_value": round(ma5_prev, 4),
            "ma10_value": round(ma10, 4),
            "ma3_source": str(ma3.get("source") or ""),
        })
        if not ready:
            row["reason"] = "MA3_ENTRY_TREND_BLOCK"
        return ready

    def _early_flow_ready(
        self, state: CodeState, point: ShadowPoint, rebound_pct: float,
    ) -> bool:
        dip_pct = (
            (state.low_so_far / state.open_price - 1.0) * 100.0
            if state.open_price > 0 else 0.0
        )
        if (
            # ★[2026-08-06 친구님 지시 "1번은 -3~3%까지, 2번은 -3% 이하"] 부등호를 뒤집었다.
            #   종전 `> -3.0` 은 "-3% 보다 깊어야 통과" 였다 = 2번과 같은 구간.
            #   짝: strategy_01_open_surge_buy_v1.py 의 min_dip_pct 조건. 반드시 같이 간다.
            dip_pct < -3.0
            # ★[2026-08-10] EARLY_FLOW가 본 판정을 우회하지 못하게 같은 무눌림 관문을 둔다.
            or dip_pct >= 0.0
            or not EARLY_REBOUND_MIN_PCT <= rebound_pct <= EARLY_REBOUND_MAX_PCT
            # ★[2026-08-13] 장초 순간 반등 추격 방지: 조기진입도 5초 상승 지속 후 허용한다.
            or self._rising_seconds(state, point.ts) < EARLY_MIN_RISING_SEC
            or not point.order_book_fresh
        ):
            state.early_confirm_hits = 0
            state.early_last_confirm_ts = None
            return False
        if not self._surge_flow_ready(state, point):
            state.early_confirm_hits = 0
            state.early_last_confirm_ts = None
            return False
        if (
            state.early_last_confirm_ts is None
            or (point.ts - state.early_last_confirm_ts).total_seconds()
            > SURGE_CONFIRM_MAX_GAP_SEC
        ):
            state.early_confirm_hits = 1
        else:
            state.early_confirm_hits += 1
        state.early_last_confirm_ts = point.ts
        return state.early_confirm_hits >= self.confirm_ticks

    @classmethod
    def _surge_flow_ready(cls, state: CodeState, point: ShadowPoint) -> bool:
        rates = cls._surge_window_rates(state)
        if rates is None:
            return False
        (
            recent_buy, recent_sell, recent_volume,
            previous_buy, previous_volume, prior_che,
        ) = rates
        return (
            recent_buy >= SURGE_MIN_BUY_RATE
            and recent_buy >= previous_buy * SURGE_BUY_ACCEL_MULT
            and recent_buy >= recent_sell * SURGE_BUY_OVER_SELL_MULT
            and recent_volume >= SURGE_MIN_VOLUME_RATE
            and recent_volume >= previous_volume * SURGE_VOLUME_ACCEL_MULT
            and point.che_str >= SURGE_MIN_CHE_STR
            and point.che_str - prior_che >= SURGE_MIN_CHE_RISE
        )

    @staticmethod
    def _surge_window_rates(
        state: CodeState,
    ) -> tuple[float, float, float, float, float, float] | None:
        points = list(state.samples)
        if len(points) < 3:
            return None
        end = points[-1]
        recent_target = end.ts.timestamp() - SURGE_RECENT_SEC
        previous_target = recent_target - SURGE_PREVIOUS_SEC

        def at_or_before(target: float) -> Sample | None:
            return next(
                (row for row in reversed(points) if row.ts.timestamp() <= target),
                None,
            )

        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        tolerance = max(2.0, SURGE_RECENT_SEC * 0.4)
        if recent_start is None or previous_start is None:
            return None
        if (
            recent_target - recent_start.ts.timestamp() > tolerance
            or previous_target - previous_start.ts.timestamp() > tolerance
        ):
            return None
        recent_span = (end.ts - recent_start.ts).total_seconds()
        previous_span = (recent_start.ts - previous_start.ts).total_seconds()
        if recent_span <= 0 or previous_span <= 0:
            return None
        deltas = (
            end.buy_money_cum - recent_start.buy_money_cum,
            end.sell_money_cum - recent_start.sell_money_cum,
            end.cum_vol - recent_start.cum_vol,
            recent_start.buy_money_cum - previous_start.buy_money_cum,
            recent_start.cum_vol - previous_start.cum_vol,
        )
        if min(deltas) < 0:
            return None
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / recent_span,
            deltas[3] / previous_span,
            deltas[4] / previous_span,
            recent_start.che_str,
        )



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
            state.early_confirm_hits = 0
            state.early_last_confirm_ts = None
        if state.last_ts is not None:
            if point.price > state.last_price and state.rise_since is None:
                state.rise_since = state.last_ts
            elif point.price < state.last_price:
                state.rise_since = None
        state.last_price, state.last_ts = point.price, point.ts
        state.samples.append(Sample(
            point.ts, point.price, point.buy_money_cum,
            point.sell_money_cum, point.exact_flow,
            point.che_str, point.cum_vol,
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
        row = {
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
            "che_str": round(point.che_str, 2),
            "cum_vol": round(point.cum_vol, 0),
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
        row.update(listed_turnover_metrics(point.code, point.cum_vol))
        return row


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
        if not header:
            writer.writeheader()
        writer.writerows(rows)


def _capture_entry_v3_exact_input(
    path: Path, *, now: datetime, points: Iterable[ShadowPoint],
    minute_payload: Mapping[str, Any], trend_rows: Mapping[str, Mapping[str, Any]],
    volume_baseline_rows: Mapping[str, Mapping[str, Any]],
    allow_select: bool, loss_pause_until: datetime | None,
    expected_signals: Iterable[Mapping[str, Any]],
    expected_audit: Iterable[Mapping[str, Any]],
    production_files: Mapping[str, str],
) -> None:
    """Preserve the raw sequential inputs required by the current v3 runtime."""
    points = list(points)
    if not points or not time(8, 40) <= now.time() < time(9, 20):
        return
    codes = {point.code for point in points}
    raw_points = []
    for point in points:
        raw = asdict(point)
        raw["ts"] = point.ts.isoformat(timespec="microseconds")
        raw_points.append(raw)
    source_m = minute_payload.get("m") if isinstance(minute_payload.get("m"), Mapping) else {}
    record = {
        "schema": "s01_entry_v3_exact_input_v1",
        "captured_at": now.isoformat(timespec="microseconds"),
        "allow_select": allow_select,
        "loss_pause_until": loss_pause_until.isoformat(timespec="seconds") if loss_pause_until else "",
        "points": raw_points,
        "minute_payload": {"ts": minute_payload.get("ts"),
                           "m": {code: source_m.get(code) for code in codes if code in source_m}},
        "trend_rows": {code: trend_rows.get(code, {}) for code in codes},
        "volume_baseline_rows": {
            code: volume_baseline_rows.get(code, {}) for code in codes
        },
        "expected_signals": list(expected_signals),
        "expected_audit": list(expected_audit),
        "production_files": dict(production_files),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    except OSError:
        pass


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


def promote_above_open_rebreak_live(
    shadow_signals: Iterable[Mapping[str, Any]],
    existing_signals: Iterable[Mapping[str, Any]],
    now: datetime,
) -> Dict[str, Any] | None:
    """Promote one confirmed above-open shadow row during the approved trial."""
    if now.strftime("%Y%m%d") not in ABOVE_OPEN_REBREAK_LIVE_DATES:
        return None
    if any(
        str(row.get("entry_stage") or "") == ABOVE_OPEN_REBREAK_LIVE_STAGE
        for row in existing_signals
    ):
        return None

    eligible = []
    for source in shadow_signals:
        try:
            observed_at = datetime.fromisoformat(str(source.get("ts") or ""))
        except ValueError:
            continue
        observed_time = observed_at.time()
        if not (
            ABOVE_OPEN_REBREAK_LIVE_START
            <= observed_time
            < ABOVE_OPEN_REBREAK_LIVE_END
        ):
            continue
        fresh_value = source.get("order_book_fresh")
        order_book_fresh = (
            fresh_value.strip().upper() in {"YES", "Y", "1", "TRUE", "ON"}
            if isinstance(fresh_value, str)
            else bool(fresh_value)
        )
        if not order_book_fresh:
            continue
        ma_ready_value = source.get("ma3_entry_trend_ready")
        ma3_entry_trend_ready = (
            ma_ready_value.strip().upper() in {"YES", "Y", "1", "TRUE", "ON"}
            if isinstance(ma_ready_value, str)
            else bool(ma_ready_value)
        )
        if not ma3_entry_trend_ready:
            continue
        spread_bps = _safe_float(source.get("spread_bps"), float("inf"))
        if spread_bps > ABOVE_OPEN_REBREAK_LIVE_MAX_SPREAD_BPS:
            continue
        eligible.append(dict(source))
    if not eligible:
        return None

    selected = max(
        eligible,
        key=lambda row: (
            int(_safe_float(row.get("theme_bonus"))),
            int(_safe_float(row.get("listed_turnover_bonus"))),
            _safe_float(row.get("money_speed_5s")),
            _safe_float(row.get("buy_ratio")),
            str(row.get("code") or ""),
        ),
    )
    selected.update({
        "action": BuyAction.BUY_READY.value,
        "reason": "ABOVE_OPEN_REBREAK_LIVE_5D",
        "entry_stage": ABOVE_OPEN_REBREAK_LIVE_STAGE,
        "requested_quantity": 1,
        "signal_sequence": int(_safe_float(
            selected.get("signal_sequence"), 1)),
        "mode": "SIGNAL_ONLY_ORDER_ZERO",
    })
    return selected


def rocket_live_enabled() -> bool:
    """Require both the hashed launcher switch and the sealed owner grant."""
    env_enabled = (
        os.environ.get("S01_ROCKET_LIVE", "NO").strip().upper()
        in {"YES", "Y", "1", "TRUE", "ON"}
    )
    return env_enabled and live_feature_enabled(ROCKET_LIVE_FEATURE)


def promote_rocket_live(
    entry_v3_rows: Iterable[Mapping[str, Any]],
    existing_signals: Iterable[Mapping[str, Any]],
    *,
    enabled: bool | None = None,
) -> Dict[str, Any] | None:
    """Promote only the already-selected ROCKET lane; other v3 lanes stay shadow."""
    if enabled is None:
        enabled = rocket_live_enabled()
    if not enabled or any(
        str(row.get("entry_stage") or "") == ROCKET_LIVE_STAGE
        for row in existing_signals
    ):
        return None
    eligible = [
        dict(row) for row in entry_v3_rows
        if str(row.get("stage") or "") == ROCKET_LIVE_STAGE
        and str(row.get("action") or "") == BuyAction.BUY_READY.value
        and str(row.get("mode") or "") == "SIGNAL_ONLY_ORDER_ZERO"
    ]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda row: (
            _safe_float(row.get("score")),
            str(row.get("code") or ""),
        ),
    )
    selected.update({
        "entry_stage": ROCKET_LIVE_STAGE,
        "requested_quantity": 1,
        "signal_sequence": 1,
        "mode": "SIGNAL_ONLY_ORDER_ZERO",
    })
    return selected


def restore_entry_v3_emitted(
    runtime: EntryRuntimeV3,
    payload: Mapping[str, Any],
    today: str,
) -> list[Dict[str, Any]]:
    """Restore same-day v3 lane caps so a signal-process restart cannot refire."""
    if str(payload.get("date") or "") != today:
        return []
    restored: list[Dict[str, Any]] = []
    for raw in payload.get("entry_v3_signals") or []:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").zfill(6)
        stage = str(raw.get("stage") or "")
        if len(code) != 6 or not code.isdigit():
            continue
        if stage not in {"ROCKET", "PULLBACK", "ORB"}:
            continue
        key = (code, stage)
        if key in runtime.emitted:
            continue
        runtime.emitted.add(key)
        runtime.lane_counts[stage] += 1
        restored.append(dict(raw))
    return restored


def build_delay_0903_shadow(
    signals: Iterable[Mapping[str, Any]], now: datetime,
) -> list[Dict[str, Any]]:
    """Record which live signals a 09:03 delay would block; order capability zero."""
    if now.strftime("%Y%m%d") not in DELAY_0903_SHADOW_DATES:
        return []
    rows: list[Dict[str, Any]] = []
    for source in signals:
        try:
            observed_at = datetime.fromisoformat(str(source.get("ts") or ""))
        except ValueError:
            continue
        if observed_at.time() >= DELAY_0903_CUTOFF:
            continue
        shadow = dict(source)
        shadow.update({
            "action": "SHADOW_WOULD_BLOCK",
            "reason": "S01_DELAY_UNTIL_0903",
            "original_action": str(source.get("action") or ""),
            "original_entry_stage": str(source.get("entry_stage") or ""),
            "requested_quantity": 0,
            "mode": "SHADOW_ORDER_ZERO",
            "shadow_rule": "BLOCK_BEFORE_09:03",
            "observation_window": "20260819-20260825",
        })
        rows.append(shadow)
    return rows


class ShadowRuntime:
    def __init__(self, config: ShadowConfig) -> None:
        self.config = config
        self.monitor = OpenSurgeShadowMonitor(
            max_signals_per_code=config.max_signals_per_code)
        existing = _read_json(config.output_path)
        self.monitor.restore_emitted(existing, datetime.now().strftime("%Y%m%d"))
        self.entry_v3 = EntryRuntimeV3(_read_json(config.entry_v3_volume_path))
        replay_sources = (
            Path(__file__).resolve(),
            RUN_DIR / "strategy_01_entry_runtime_v3.py",
            RUN_DIR / "strategy_01_entry_policy_v3.py",
            RUN_DIR / "strategy_01_signal_contract_v2.py",
            RUN_DIR / "strategy_01_volume_baseline_v3.py",
        )
        self.entry_v3_production_files = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in replay_sources
        }
        self.entry_v3_signals = restore_entry_v3_emitted(
            self.entry_v3, existing, datetime.now().strftime("%Y%m%d"),
        )
        self._entry_v3_batch = -1

    def tick(self, now: datetime) -> Dict[str, Any]:
        rotation_state = _read_json(self.config.rotation_state_path)
        adaptive_required = adaptive_confirm_ticks(
            rotation_state, now,
        )
        loss_pause_until = entry_v3_loss_pause_until(rotation_state, now)
        adaptive_live = self.config.adaptive_confirm_mode == "LIVE"
        self.monitor.confirm_ticks = adaptive_required if adaptive_live else 2
        points, status, watch_count, range_meta = load_live_points(
            self.config, now)
        minute_payload = _read_json(self.config.minute_path)
        trend_payload = _read_json(self.config.trend_priority_path)
        batch_id = int(now.timestamp()) // 3
        allow_v3_select = batch_id != self._entry_v3_batch and loss_pause_until is None
        if allow_v3_select:
            self._entry_v3_batch = batch_id
        entry_v3_new, entry_v3_audit = self.entry_v3.process_batch(
            points, minute_payload, trend_payload.get("codes") or {},
            allow_select=allow_v3_select,
        )
        _capture_entry_v3_exact_input(
            self.config.entry_v3_replay_dir / f"s01_entry_v3_exact_inputs_{now:%Y%m%d}.jsonl",
            now=now, points=points, minute_payload=minute_payload,
            trend_rows=trend_payload.get("codes") or {},
            volume_baseline_rows=self.entry_v3.baseline,
            allow_select=allow_v3_select, loss_pause_until=loss_pause_until,
            expected_signals=entry_v3_new, expected_audit=entry_v3_audit,
            production_files=self.entry_v3_production_files,
        )
        self.entry_v3_signals.extend(entry_v3_new)
        signals = self.monitor.process_points(points)
        rocket_live = rocket_live_enabled()
        rocket_promoted = promote_rocket_live(
            entry_v3_new, self.monitor.signals, enabled=rocket_live,
        )
        if rocket_promoted is not None:
            self.monitor.signals.append(rocket_promoted)
            signals.append(rocket_promoted)
        shadow_signals = self.monitor.drain_shadow_signals()
        promoted = promote_above_open_rebreak_live(
            shadow_signals, self.monitor.signals, now)
        if promoted is not None:
            self.monitor.signals.append(promoted)
            signals.append(promoted)
        for _code, _row in self.monitor.latest.items():
            if isinstance(_row, dict):
                _row.update(range_meta.get(str(_code).zfill(6)) or {})
        for _row in signals:
            if isinstance(_row, dict):
                _row.update(range_meta.get(str(_row.get("code") or "")) or {})
        delay_0903_shadow = build_delay_0903_shadow(signals, now)
        payload = {
            "schema": "strategy_01_open_surge_signal_v2",
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "status": status,
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "watch_count": watch_count,
            "point_count": len(points),
            "adaptive_confirm_mode": self.config.adaptive_confirm_mode,
            "adaptive_confirm_ticks_active": self.monitor.confirm_ticks,
            "adaptive_confirm_ticks_observed": adaptive_required,
            "signals": self.monitor.signals,
            "shadow_signals": self.monitor.shadow_signals,
            "entry_v3_mode": "SHADOW",
            "rocket_live_mode": "LIVE" if rocket_live else "SHADOW",
            "entry_v3_loss_pause_until": (
                loss_pause_until.isoformat(timespec="seconds") if loss_pause_until else ""
            ),
            "entry_v3_signals": self.entry_v3_signals,
            "entry_v3_candidates": entry_v3_audit,
            "candidates": list(self.monitor.latest.values()),
        }
        _atomic_text(self.config.output_path, json.dumps(
            payload, ensure_ascii=False, indent=2))
        _atomic_text(self.config.html_path, _html_board(payload))
        event_path = self.config.event_dir / f"strategy_01_open_surge_signal_{now:%Y%m%d}.csv"
        _append_events(event_path, signals)
        shadow_path = (
            self.config.event_dir
            / f"strategy_01_above_open_rebreak_shadow_{now:%Y%m%d}.csv"
        )
        _append_events(shadow_path, shadow_signals)
        delay_path = (
            self.config.event_dir
            / f"strategy_01_delay_0903_shadow_{now:%Y%m%d}.csv"
        )
        _append_events(delay_path, delay_0903_shadow)
        entry_v3_path = (
            self.config.event_dir
            / f"strategy_01_entry_v3_shadow_{now:%Y%m%d}.csv"
        )
        _append_events(entry_v3_path, entry_v3_audit)
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

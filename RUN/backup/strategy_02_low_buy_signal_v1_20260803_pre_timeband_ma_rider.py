# -*- coding: utf-8 -*-
"""새전략 02 저점매수·매도소진 신호전용 감시기(주문 0)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time as time_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_02_signal_contract_v1 import SIGNAL_MODE, SIGNAL_SCHEMA
from 저점매수_매도소진 import BottomSignal, MarketPoint, detect_flow_book_exhaustion

KST = ZoneInfo("Asia/Seoul")
# ★[2026-07-31 친구님 지시 "시각 9시 05부터 14시 20"] 09:30 → 09:05.
#   7/31 실측: 고저폭 30종목의 당일 저점이 25개/30개가 09:10 이전에 형성됐다.
#   09:30 시작이면 그날 가장 좋은 자리를 통째로 놓친다.
ENTRY_START = time(9, 6)
MORNING_OPEN_REFERENCE_END = time(9, 20)
ENTRY_END = time(14, 20)

# ★[2026-07-31 친구님 지시 "2번 이렇게 바꿔"] 매수 판정 전면 교체.
#   폐기한 것 = detect_flow_book_exhaustion (하락파동 2개 + 약화지표 2개 + 첫저점 회복
#     + 매도압력 전환 + 총호가 매수우위 60% + 진입가 저점+1.5% 이내, 7개 동시 충족).
#   폐기 이유 — 두 달 가까이 신호 0건. 7/29 후보 264개·7/31 후보 231건이 전원
#     같은 자리(FLOW_BOOK_RECOVERY_WAIT)에서 죽었다.
#   7/31 단계별 실측(고저폭30·09:30~14:20):
#       하락파동 2개 이상        26/30 통과
#       + 두번째 저점이 더 낮음  25/30 통과
#       + 고점대비 낙폭 2%↑     25/30 통과
#       + 매도압력·호가·진입가   **0/30**   ← 전멸
#   병목은 "총호가 매수우위 60%"다. 바닥에서 사겠다면서 호가가 매수우위여야 한다는
#     건 서로 모순이다 — 매수우위로 바뀔 때쯤이면 값이 올라 진입가 제한(저점+1.5%)에
#     걸린다. 어느 쪽으로 가도 죽는 구조다.
#   새 규칙 = 1번(S01)에서 검증된 되돌림 3조건을 이 시간대에 이식.
#     7/31 재현: 27종목 체결 · 평균 +3.18% · 승률 93%  (기존 규칙은 0종목)
#     ⚠️기준점은 1번과 다르다 — 1번은 '시가 대비'(개장 직후라 시가가 기준),
#       2번은 '장중 고점 대비'(09:05 이후엔 시가가 이미 옛 값).
#     ⚠️밀림 문턱도 다르다 — 09:30 이후 되돌림은 09시대의 절반(중앙값 0.72% vs 1.64%).
#   롤백: setx S02_DIP_MODE NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260731_dipmode.py 복원
DIP_MODE = os.environ.get("S02_DIP_MODE", "YES").strip().upper() == "YES"
DIP_DROP_PCT = 3.0  # 시가 또는 장중 고점 대비 추적 시작
DEEPER_HANDOFF_OPEN_DROP_PCT = -4.0  # 시가 대비 전략 3 영역 인계
DIP_REBOUND_PCT = float(os.environ.get("S02_DIP_REBOUND_PCT", "0.5"))  # 저점 +X% 회복 = 신호
DIP_CHASE_CAP_PCT = float(os.environ.get("S02_DIP_CHASE_CAP", "3.0"))  # 저점 +X% 넘으면 추격 금지
# ★[2026-08-01 친구님 지시 "2번 저점매수 방법을 6번과 동일하게"] 6번식 매수 확인 이식.
#   ①관찰 60초 — 저점이 생기고 최소 60초는 지켜본다(덥썩 방지)
#   ②속도 역전 — 저점 전 180초는 매도 우위였다가, 저점 후에는 매수 속도가
#     매도 속도를 넘어야 산다(자료가 없어 판별 불가면 통과 — 조건 최소 원칙)
#   ③재무장 깊이 — 같은 종목 2번째 신호는 직전 신호 저점보다 1% 더 깊은
#     저점에서만(연속 가짜 반등에 2발을 다 쓰는 것 방지)
#   근거: 7/29 지엔씨에너지 분당 재생 — 속도 역전이 진짜 바닥을 정확히 갈랐고
#   (가짜 6개 전부 역전 없음), 6번에서 같은 규칙이 -2.18%→+0.98% 로 뒤집었다.
#   발동 기준(장중 고점 대비)·시간창·매도는 그대로 — 사는 "방법"만 6번식.
#   롤백: setx S02_SIX_STYLE NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260801_sixstyle.py 복원
# ★[2026-08-01 보안점검 중간6] 딥모드 롤백(S02_DIP_MODE=NO) 시 6번식도 함께
#   내려간다 — 옛 매도소진 판정에 확정대기 생략·재무장만 얹힌 잡종 조합 방지.
# ★[2026-08-03 보안점검] S02_SIX_STYLE 재연결 — 이 줄이 `SIX_STYLE = DIP_MODE` 로
#   바뀌면서 67줄이 안내하는 롤백(setx S02_SIX_STYLE NO)이 아무 효과가 없었다.
#   기본값 YES 라 환경변수 미설정 시 결과는 종전과 완전히 같다(DIP_MODE 그대로).
SIX_STYLE = (os.environ.get("S02_SIX_STYLE", "YES").strip().upper() == "YES") and DIP_MODE
SIX_OBSERVE_SEC = float(os.environ.get("S02_OBSERVE_SEC", "60"))
SIX_REARM_DEEPER_PCT = float(os.environ.get("S02_REARM_DEEPER_PCT", "1.0"))
SIX_FIRST_REBOUND_PCT = float(os.environ.get("S02_SIX_FIRST_REBOUND_PCT", "1.5"))
SIX_CHASE_CAP_PCT = float(os.environ.get("S02_SIX_CHASE_CAP_PCT", "2.0"))
SIX_PULLBACK_MIN_PCT = float(os.environ.get("S02_SIX_PULLBACK_MIN_PCT", "0.4"))
SIX_HIGHER_LOW_BUFFER_PCT = float(os.environ.get(
    "S02_SIX_HIGHER_LOW_BUFFER_PCT", "0.3"))
SIX_SECOND_REBOUND_PCT = float(os.environ.get(
    "S02_SIX_SECOND_REBOUND_PCT", "0.5"))
SIX_ENTRY_FLOOR_PCT = float(os.environ.get("S02_SIX_ENTRY_FLOOR_PCT", "1.0"))
SIX_FLOW_ACCEL_WINDOW_SEC = float(os.environ.get(
    "S02_SIX_FLOW_ACCEL_WINDOW_SEC", "10"))
SIX_OBSERVE_MAX_SEC = float(os.environ.get("S02_SIX_OBSERVE_MAX_SEC", "720"))
# 급락 직후 첫 장대양봉 초입을 잡는 별도 경로. 기존 6번식 계단 저점 경로는 유지한다.
MONEY_SURGE_ENABLED = (
    os.environ.get("S02_MONEY_SURGE_ENABLED", "YES").strip().upper() == "YES"
)
SURGE_DROP_WINDOW_SEC = float(os.environ.get("S02_SURGE_DROP_WINDOW_SEC", "30"))
SURGE_MIN_DROP_PCT = float(os.environ.get("S02_SURGE_MIN_DROP_PCT", "3.0"))
SURGE_MIN_DOWN_STEPS = int(os.environ.get("S02_SURGE_MIN_DOWN_STEPS", "3"))
SURGE_TURN_MAX_SEC = float(os.environ.get("S02_SURGE_TURN_MAX_SEC", "10"))
SURGE_REBOUND_MIN_PCT = float(os.environ.get("S02_SURGE_REBOUND_MIN_PCT", "0.5"))
SURGE_REBOUND_MAX_PCT = float(os.environ.get("S02_SURGE_REBOUND_MAX_PCT", "2.0"))
SURGE_CONFIRM_TICKS = int(os.environ.get("S02_SURGE_CONFIRM_TICKS", "2"))
SURGE_CONFIRM_MAX_GAP_SEC = float(os.environ.get("S02_SURGE_CONFIRM_MAX_GAP_SEC", "2"))
SURGE_RECENT_SEC = float(os.environ.get("S02_SURGE_RECENT_SEC", "5"))
SURGE_PREVIOUS_SEC = float(os.environ.get("S02_SURGE_PREVIOUS_SEC", "10"))
SURGE_BUY_ACCEL_MULT = float(os.environ.get("S02_SURGE_BUY_ACCEL_MULT", "2.5"))
SURGE_BUY_OVER_SELL_MULT = float(os.environ.get("S02_SURGE_BUY_OVER_SELL_MULT", "1.5"))
SURGE_VOLUME_ACCEL_MULT = float(os.environ.get("S02_SURGE_VOLUME_ACCEL_MULT", "2.0"))
SURGE_MIN_BUY_RATE = float(os.environ.get("S02_SURGE_MIN_BUY_RATE", "1666667"))
SURGE_MIN_VOLUME_RATE = float(os.environ.get("S02_SURGE_MIN_VOLUME_RATE", "50"))
SURGE_MIN_CHE_STR = float(os.environ.get("S02_SURGE_MIN_CHE_STR", "105"))
SURGE_MIN_CHE_RISE = float(os.environ.get("S02_SURGE_MIN_CHE_RISE", "5"))
# 공통 컨텍스트(strategy_common_candidate_context_v1)가 all_meta 에 실어주는 고저폭 지표.
# 신호 행에 그대로 붙여 기록한다. ★2026-07-31 부터 감시대상 제한에도 쓴다(아래 참조).
RANGE_KEYS = (
    "hr_prev_range", "hr_avg5_range", "hr_min5_range",
    "hr_streak", "hr_rank", "hr_crown",
)
# ★[2026-07-31 친구님 지시 "전략 2하고 3부터 고저폭으로 좁혀줘"]
#   S02 감시대상을 고저폭 TOP30(hr_rank 가 실린 종목)으로 제한한다.
#   근거 — 일봉 1년 코스닥 전수(12만건·왕복비용 0.38% 차감)로 S02 진입을 근사
#   (당일 저가 +1% 매수 → 당일 종가 매도) 했을 때:
#       고저폭 조건 밖   +1.251% / 승률 58.8%  (11.4만건)
#       고저폭 연속 1~2일 +3.292% / 승률 77.2%  (9,544건)
#       고저폭 연속 3~4일 +4.178% / 승률 80.5%  (1,904건)
#       고저폭 연속 5일↑  +4.343% / 승률 81.4%  (1,370건)
#     = 고저폭 안이 밖보다 3.5배. 이유는 익일 고저폭 자체가 5.87% → 14.06% 로
#       2.4배 크고, 다음날에도 10%↑ 로 움직일 확률이 12.5% → 72.0% 라서다.
#   ⚠️같은 자료에서 "시가 매수 → 당일 종가"(S01 급상승 근사)는 고저폭을 붙이면
#     오히려 나빠진다(-0.75% → -1.47%). 저점에서 사는 전략에만 유효한 제한이다.
#   안전장치: 고저폭 목록이 통째로 비면(08:40 생성 실패 등) 제한을 걸지 않는다
#     — 안 그러면 전 종목이 차단된다(fail-open).
#   롤백: setx S02_HIGH_RANGE_ONLY NO + 신호기 재기동
#         또는 backup\strategy_02_low_buy_signal_v1_20260731_hronly.py 복원
HIGH_RANGE_ONLY = os.environ.get("S02_HIGH_RANGE_ONLY", "YES").strip().upper() == "YES"


@dataclass(frozen=True)
class SignalConfig:
    watch_path: Path = Path(os.environ.get(
        "S02_WATCH", r"C:\stock_bot\IPC\micro_watch_strategy_shared.json"))
    snapshot_path: Path = Path(os.environ.get(
        "S02_SNAPSHOT", r"C:\stock_bot\IPC\live_micro_snapshot.json"))
    minute_path: Path = Path(os.environ.get(
        "S02_MINUTE_PATH", str(Path(r"C:\stock_bot\data") / "돈맥_1분봉.json")))
    names_path: Path = Path(os.environ.get(
        "S02_NAMES", r"C:\stock_bot\data\_code_name_cache.json"))
    output_path: Path = Path(os.environ.get(
        "S02_OUTPUT", r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json"))
    event_dir: Path = Path(os.environ.get(
        "S02_EVENT_DIR", r"C:\stock_bot\data\strategy_02_signal_v1"))
    loop_sec: float = float(os.environ.get("S02_LOOP_SEC", "1"))
    max_snapshot_age_sec: float = float(os.environ.get("S02_SNAPSHOT_MAX_AGE", "4"))
    max_signals_per_code: int = int(os.environ.get("S02_MAX_CYCLES_PER_CODE", "2"))
    min_price: float = float(os.environ.get("S02_MIN_PRICE", "10000"))
    confirm_sec: float = float(os.environ.get("S02_CONFIRM_SEC", "2"))
    confirm_points: int = int(os.environ.get("S02_CONFIRM_POINTS", "3"))
    max_spread_bps: float = float(os.environ.get("S02_MAX_SPREAD_BPS", "30"))
    min_microprice_edge_bps: float = float(os.environ.get(
        "S02_MIN_MICROPRICE_EDGE_BPS", "0"))
    min_best_bid_share: float = float(os.environ.get(
        "S02_MIN_BEST_BID_SHARE", "0.50"))
    max_confirm_chase_bps: float = float(os.environ.get(
        "S02_MAX_CONFIRM_CHASE_BPS", "25"))
    max_entry_gap_pct: float = float(os.environ.get(
        "S02_MAX_ENTRY_GAP_PCT", "1.50"))

    def __post_init__(self) -> None:
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 02 requires exactly two opportunities per code")


@dataclass
class CodeState:
    points: Deque[MarketPoint] = field(default_factory=lambda: deque(maxlen=360))
    emission_count: int = 0
    emitted_anchors: set[str] = field(default_factory=set)
    pending_anchor_id: str = ""
    pending_since: datetime | None = None
    pending_signal_price: float = 0.0
    pending_hits: int = 0
    last_signal_low: float = 0.0
    last_signal_high: float = 0.0
    six_phase: str = "IDLE"
    six_episode_high: float = 0.0
    six_low: float = 0.0
    six_low_ts: datetime | None = None
    six_low_buy_money: float = 0.0
    six_low_sell_money: float = 0.0
    six_pre_buy_rate: float = -1.0
    six_pre_sell_rate: float = -1.0
    six_reset_steps: int = 0
    six_dead_low: float = 0.0
    six_observe_since: datetime | None = None
    six_first_rebound_peak: float = 0.0
    six_pullback_seen: bool = False
    six_pullback_low: float = 0.0
    open_price: float = 0.0
    session_high: float = 0.0
    six_reference_price: float = 0.0
    six_reference_mode: str = ""
    handoff_to_s03_s06: bool = False
    surge_phase: str = "IDLE"
    surge_high: float = 0.0
    surge_low: float = 0.0
    surge_high_ts: datetime | None = None
    surge_low_ts: datetime | None = None
    surge_drop_steps: int = 0
    surge_confirm_hits: int = 0
    surge_last_confirm_ts: datetime | None = None


def _read_json(path: Path) -> Dict[str, Any]:
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
        try:
            parsed_time = datetime.strptime(text[:8], "%H:%M:%S").time()
            parsed = datetime.combine(now.date(), parsed_time)
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)
    return parsed


def _s01_taken_codes(today: str) -> set:
    """★[2026-07-31 친구님 지시 "1번 3번이 2번이 안 겹쳐야 돼"]
    오늘 1번(S01)·3번(S03)이 이미 신호를 낸 종목 집합.

    진입창을 09:05 로 당기면서 1번(09:00~09:20)·3번(09:00~14:30)과 시간이 겹치게
    됐다. 같은 종목을 여러 전략이 동시에 노리면 공용 6슬롯을 나눠 먹고, 계좌 중복매수
    차단에 걸려 뒤늦은 쪽이 헛수고를 한다.
    파일이 없거나 날짜가 다르면 빈 집합 = 제외하지 않는다(fail-open).
    """
    taken = set()
    for path in (r"C:\stock_bot\data\strategy_01_open_surge_signal_v2.json",
                 r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json"):
        payload = _read_json(Path(path))
        if str(payload.get("date") or "").replace("-", "")[:8] != today:
            continue
        for row in (payload.get("signals") or []):
            code = str(row.get("code") or "").zfill(6)
            if len(code) == 6:
                taken.add(code)
    return taken


def _name_map(payload: Mapping[str, Any]) -> Dict[str, str]:
    raw = payload.get("map", payload)
    return {str(code).zfill(6): str(name) for code, name in raw.items()}


def _minute_references(
    payload: Mapping[str, Any], today: str,
) -> Dict[str, Dict[str, float]]:
    if str(payload.get("ts") or "").replace("-", "")[:8] != today:
        return {}
    output: Dict[str, Dict[str, float]] = {}
    for code, raw in (payload.get("m") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        open_price = _number(raw.get("op"))
        highs = [open_price, _number(raw.get("h"))]
        for bar in raw.get("prev") or []:
            if isinstance(bar, (list, tuple)) and len(bar) >= 2:
                highs.append(_number(bar[1]))
        session_high = max((value for value in highs if value > 0), default=0.0)
        if open_price > 0 or session_high > 0:
            output[str(code).zfill(6)] = {
                "open": open_price,
                "high": session_high,
            }
    return output

def load_live_points(
    config: SignalConfig,
    now: datetime,
) -> tuple[list[tuple[str, str, MarketPoint]], str, int, Dict[str, Dict[str, Any]]]:
    watch = _read_json(config.watch_path)
    today = now.strftime("%Y%m%d")
    if str(watch.get("for_date") or "").replace("-", "")[:8] != today:
        return [], "WATCH_DATE_MISMATCH", 0, {}
    codes = {str(code).zfill(6) for code in (watch.get("codes") or [])}
    range_meta: Dict[str, Dict[str, Any]] = {}
    for meta_code, meta in (watch.get("all_meta") or {}).items():
        if not isinstance(meta, Mapping):
            continue
        picked = {
            key: meta[key] for key in RANGE_KEYS if meta.get(key) is not None
        }
        if picked:
            range_meta[str(meta_code).zfill(6)] = picked
    snapshot = _read_json(config.snapshot_path)
    names = _name_map(_read_json(config.names_path))
    s01_codes = _s01_taken_codes(today)          # ★1번이 오늘 잡은 종목(중복 방지)
    output: list[tuple[str, str, MarketPoint]] = []
    for code, raw in (snapshot.get("codes") or {}).items():
        code = str(code).zfill(6)
        if code not in codes or not isinstance(raw, Mapping):
            continue
        # ★[2026-07-31] 고저폭 TOP30 제한 — range_meta 는 hr_* 가 실린 종목만 담고 있다.
        #   range_meta 가 비면(고저폭 목록 실패) 제한하지 않는다(fail-open·위 주석 참조).
        if HIGH_RANGE_ONLY and range_meta and code not in range_meta:
            continue
        # ★[2026-07-31] 1번·3번이 오늘 이미 잡은 종목은 제외(_s01_taken_codes 주석 참조).
        if code in s01_codes:
            continue
        ts = _parse_dt(raw.get("ts"), now)
        ob_ts = _parse_dt(raw.get("ob_ts"), now)
        if ts is None or ob_ts is None:
            continue
        if not (
            -2 <= (now - ts).total_seconds() <= config.max_snapshot_age_sec
            and -2 <= (now - ob_ts).total_seconds() <= config.max_snapshot_age_sec
        ):
            continue
        price = abs(_number(raw.get("cur")))
        ask_tot = abs(_number(raw.get("ask_tot")))
        bid_tot = abs(_number(raw.get("bid_tot")))
        best_ask = abs(_number(raw.get("best_ask_px")))
        best_bid = abs(_number(raw.get("best_bid_px")))
        best_ask_qty = abs(_number(raw.get("best_ask_qty")))
        best_bid_qty = abs(_number(raw.get("best_bid_qty")))
        buy_cum = _number(raw.get("buy_money_cum"), -1)
        sell_cum = _number(raw.get("sell_money_cum"), -1)
        if (
            price < config.min_price
            or ask_tot <= 0
            or bid_tot <= 0
            or not best_ask > best_bid > 0
            or best_ask_qty <= 0
            or best_bid_qty <= 0
            or buy_cum < 0
            or sell_cum < 0
        ):
            continue
        output.append((code, names.get(code, code), MarketPoint(
            ts=ts,
            price=price,
            cum_vol=abs(_number(raw.get("cum_vol"))),
            che_str=abs(_number(raw.get("che_str"))),
            ask_tot=ask_tot,
            bid_tot=bid_tot,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            best_ask_px=best_ask,
            best_bid_px=best_bid,
            best_ask_qty=best_ask_qty,
            best_bid_qty=best_bid_qty,
        )))
    return output, ("LIVE" if output else "DATA_WAIT"), len(codes), range_meta


class LowBuySignalMonitor:
    def __init__(
        self,
        *,
        max_signals_per_code: int = 2,
        confirm_sec: float = 2.0,
        confirm_points: int = 3,
        max_spread_bps: float = 30.0,
        min_microprice_edge_bps: float = 0.0,
        min_best_bid_share: float = 0.50,
        max_confirm_chase_bps: float = 25.0,
        max_entry_gap_pct: float = 1.50,
    ) -> None:
        if max_signals_per_code != 2:
            raise ValueError("Strategy 02 requires exactly two opportunities per code")
        self.max_signals_per_code = max_signals_per_code
        self.confirm_sec = max(0.0, float(confirm_sec))
        self.confirm_points = max(2, int(confirm_points))
        self.max_spread_bps = float(max_spread_bps)
        self.min_microprice_edge_bps = float(min_microprice_edge_bps)
        self.min_best_bid_share = float(min_best_bid_share)
        self.max_confirm_chase_bps = float(max_confirm_chase_bps)
        self.max_entry_gap_pct = float(max_entry_gap_pct)
        self.states: Dict[str, CodeState] = {}
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.signals: list[Dict[str, Any]] = []

    @staticmethod
    def _clear_pending(state: CodeState) -> None:
        state.pending_anchor_id = ""
        state.pending_since = None
        state.pending_signal_price = 0.0
        state.pending_hits = 0

    def _book_telemetry(
        self, point: MarketPoint,
    ) -> tuple[bool, str, float, float, float]:
        ask = float(point.best_ask_px)
        bid = float(point.best_bid_px)
        ask_qty = float(point.best_ask_qty)
        bid_qty = float(point.best_bid_qty)
        if not (ask > bid > 0 and ask_qty > 0 and bid_qty > 0):
            return False, "EXACT_TOPBOOK_REQUIRED", 0.0, 0.0, 0.0
        midpoint = (ask + bid) / 2.0
        spread_bps = (ask - bid) / midpoint * 10_000.0
        microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
        edge_bps = (microprice - midpoint) / midpoint * 10_000.0
        best_bid_share = bid_qty / (bid_qty + ask_qty)
        if spread_bps > self.max_spread_bps:
            return False, "SPREAD_TOO_WIDE", spread_bps, edge_bps, best_bid_share
        if edge_bps < self.min_microprice_edge_bps:
            return False, "MICROPRICE_NOT_RECOVERED", spread_bps, edge_bps, best_bid_share
        if best_bid_share < self.min_best_bid_share:
            return False, "BEST_BID_NOT_DOMINANT", spread_bps, edge_bps, best_bid_share
        return True, "PASS", spread_bps, edge_bps, best_bid_share

    def restore(self, payload: Mapping[str, Any], today: str) -> None:
        if str(payload.get("schema") or "") != SIGNAL_SCHEMA:
            return
        if str(payload.get("date") or "") != today:
            return
        for raw in payload.get("signals") or []:
            code = str(raw.get("code") or "").zfill(6)
            if not code:
                continue
            row = dict(raw)
            state = self.states.setdefault(code, CodeState())
            state.emission_count = max(
                state.emission_count, int(row.get("signal_sequence") or 0))
            anchor = str(row.get("anchor_id") or "")
            if anchor:
                state.emitted_anchors.add(anchor)
            low_val = _number(row.get("anchor_low"))
            if low_val > 0:
                state.last_signal_low = low_val
            high_val = _number(row.get("dip_episode_high"))
            if high_val > 0:
                state.last_signal_high = high_val
            self.signals.append(row)

    @staticmethod
    def _clear_six_retest(state: CodeState) -> None:
        state.six_observe_since = None
        state.six_first_rebound_peak = 0.0
        state.six_pullback_seen = False
        state.six_pullback_low = 0.0

    @staticmethod
    def _reset_money_surge(state: CodeState) -> None:
        state.surge_phase = "IDLE"
        state.surge_high = 0.0
        state.surge_low = 0.0
        state.surge_high_ts = None
        state.surge_low_ts = None
        state.surge_drop_steps = 0
        state.surge_confirm_hits = 0
        state.surge_last_confirm_ts = None

    @staticmethod
    def _surge_window_rates(
        points: list[MarketPoint],
    ) -> tuple[float, float, float, float, float, float, float] | None:
        if len(points) < 3:
            return None
        end = points[-1]
        end_epoch = end.ts.timestamp()
        recent_target = end_epoch - SURGE_RECENT_SEC
        previous_target = recent_target - SURGE_PREVIOUS_SEC

        def at_or_before(target: float) -> MarketPoint | None:
            for row in reversed(points):
                if row.ts.timestamp() <= target:
                    return row
            return None

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
            recent_start.sell_money_cum - previous_start.sell_money_cum,
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
            deltas[5] / previous_span,
            recent_start.che_str,
        )

    def _detect_money_surge_onset(
        self, state: CodeState, points: list[MarketPoint],
    ) -> BottomSignal | None:
        if not MONEY_SURGE_ENABLED or not points:
            return None
        point = points[-1]
        if point.price <= 0:
            return None

        if state.surge_phase == "IDLE":
            cutoff = point.ts.timestamp() - SURGE_DROP_WINDOW_SEC
            window = [
                row for row in points
                if row.ts.timestamp() >= cutoff and row.price > 0
            ]
            if len(window) < SURGE_MIN_DOWN_STEPS + 1:
                return None
            high_idx = max(range(len(window)), key=lambda idx: window[idx].price)
            descent = window[high_idx:]
            if len(descent) < SURGE_MIN_DOWN_STEPS + 1:
                return None
            if point.price != min(row.price for row in descent):
                return None
            local_high = descent[0]
            local_drop_pct = (local_high.price / point.price - 1.0) * 100.0
            reference_drop_pct = (
                (state.six_reference_price / point.price - 1.0) * 100.0
                if state.six_reference_price > 0 else 0.0
            )
            down_steps = sum(
                1 for before, after in zip(descent, descent[1:])
                if after.price < before.price
            )
            if (
                local_drop_pct < SURGE_MIN_DROP_PCT
                or reference_drop_pct < DIP_DROP_PCT
                or down_steps < SURGE_MIN_DOWN_STEPS
            ):
                return None
            state.surge_phase = "ARMED"
            state.surge_high = local_high.price
            state.surge_low = point.price
            state.surge_high_ts = local_high.ts
            state.surge_low_ts = point.ts
            state.surge_drop_steps = down_steps
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        if state.surge_low <= 0 or state.surge_low_ts is None:
            self._reset_money_surge(state)
            return None
        if point.price < state.surge_low:
            state.surge_low = point.price
            state.surge_low_ts = point.ts
            state.surge_drop_steps += 1
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        turn_sec = (point.ts - state.surge_low_ts).total_seconds()
        rebound_pct = (point.price / state.surge_low - 1.0) * 100.0
        if turn_sec > SURGE_TURN_MAX_SEC or rebound_pct > SURGE_REBOUND_MAX_PCT:
            self._reset_money_surge(state)
            return None
        if rebound_pct < SURGE_REBOUND_MIN_PCT:
            return None

        rates = self._surge_window_rates(points)
        book_ok, _, _, _, _ = self._book_telemetry(point)
        if rates is None or not book_ok:
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None
        (
            recent_buy, recent_sell, recent_volume,
            previous_buy, _previous_sell, previous_volume, prior_che,
        ) = rates
        flow_ok = (
            recent_buy >= SURGE_MIN_BUY_RATE
            and recent_buy >= previous_buy * SURGE_BUY_ACCEL_MULT
            and recent_buy >= recent_sell * SURGE_BUY_OVER_SELL_MULT
            and recent_volume >= SURGE_MIN_VOLUME_RATE
            and recent_volume >= previous_volume * SURGE_VOLUME_ACCEL_MULT
            and point.che_str >= SURGE_MIN_CHE_STR
            and point.che_str - prior_che >= SURGE_MIN_CHE_RISE
        )
        if not flow_ok:
            state.surge_confirm_hits = 0
            state.surge_last_confirm_ts = None
            return None

        if (
            state.surge_last_confirm_ts is None
            or (point.ts - state.surge_last_confirm_ts).total_seconds()
            > SURGE_CONFIRM_MAX_GAP_SEC
        ):
            state.surge_confirm_hits = 1
        else:
            state.surge_confirm_hits += 1
        state.surge_last_confirm_ts = point.ts
        if state.surge_confirm_hits < SURGE_CONFIRM_TICKS:
            return None

        drop_pct = (state.surge_high / state.surge_low - 1.0) * 100.0
        self._last_dip_meta = {
            "dip_drop_pct": round(drop_pct, 4),
            "dip_episode_high": state.surge_high,
            "dip_low_reset_steps": state.surge_drop_steps,
            "surge_turn_sec": round(turn_sec, 3),
            "surge_rebound_pct": round(rebound_pct, 4),
            "surge_recent_buy_rate_5s": round(recent_buy, 3),
            "surge_recent_sell_rate_5s": round(recent_sell, 3),
            "surge_previous_buy_rate": round(previous_buy, 3),
            "surge_recent_volume_rate_5s": round(recent_volume, 3),
            "surge_previous_volume_rate": round(previous_volume, 3),
            "surge_che_str": round(point.che_str, 3),
            "surge_confirm_ticks": state.surge_confirm_hits,
        }
        return BottomSignal(
            algorithm="S02_MONEY_SURGE_ONSET_V1",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=state.surge_low_ts,
            anchor_low_price=state.surge_low,
            wave_count=state.surge_drop_steps + 1,
            reason=(
                f"MONEY_SURGE_ONSET drop={drop_pct:.2f}% "
                f"rebound={rebound_pct:.2f}%"
            ),
        )

    @classmethod
    def _reset_six_cycle(
        cls, state: CodeState, point: MarketPoint | None = None,
    ) -> None:
        state.six_phase = "IDLE"
        state.six_episode_high = point.price if point is not None else 0.0
        state.six_low = point.price if point is not None else 0.0
        state.six_low_ts = point.ts if point is not None else None
        state.six_low_buy_money = point.buy_money_cum if point is not None else 0.0
        state.six_low_sell_money = point.sell_money_cum if point is not None else 0.0
        state.six_pre_buy_rate = -1.0
        state.six_pre_sell_rate = -1.0
        state.six_reset_steps = 0
        state.six_dead_low = 0.0
        cls._clear_six_retest(state)

    @staticmethod
    def _six_pre_rates(
        points: list[MarketPoint], low_ts: datetime,
    ) -> tuple[float, float]:
        rows = [
            row for row in points
            if row.ts <= low_ts and 0 <= (low_ts - row.ts).total_seconds() <= 180.0
        ]
        if len(rows) < 2:
            return -1.0, -1.0
        span = (rows[-1].ts - rows[0].ts).total_seconds()
        if span < 30.0:
            return -1.0, -1.0
        return (
            max(0.0, rows[-1].buy_money_cum - rows[0].buy_money_cum) / span,
            max(0.0, rows[-1].sell_money_cum - rows[0].sell_money_cum) / span,
        )

    @staticmethod
    def _six_flow_acceleration(
        points: list[MarketPoint],
    ) -> tuple[str, float, float, float, float]:
        if len(points) < 3:
            return "", 0.0, 0.0, 0.0, 0.0
        window = SIX_FLOW_ACCEL_WINDOW_SEC
        end = points[-1]
        tolerance = max(3.0, window * 0.4)

        def at_or_before(target: float) -> MarketPoint | None:
            for row in reversed(points):
                if row.ts.timestamp() <= target:
                    return row
            return None

        end_epoch = end.ts.timestamp()
        middle_target = end_epoch - window
        start_target = end_epoch - 2.0 * window
        middle = at_or_before(middle_target)
        start = at_or_before(start_target)
        if middle is None or start is None:
            return "", 0.0, 0.0, 0.0, 0.0
        if (
            middle_target - middle.ts.timestamp() > tolerance
            or start_target - start.ts.timestamp() > tolerance
        ):
            return "", 0.0, 0.0, 0.0, 0.0
        previous_span = (middle.ts - start.ts).total_seconds()
        recent_span = (end.ts - middle.ts).total_seconds()
        if min(previous_span, recent_span) < window * 0.6:
            return "", 0.0, 0.0, 0.0, 0.0
        previous_buy = max(
            0.0, middle.buy_money_cum - start.buy_money_cum) / previous_span
        previous_sell = max(
            0.0, middle.sell_money_cum - start.sell_money_cum) / previous_span
        recent_buy = max(
            0.0, end.buy_money_cum - middle.buy_money_cum) / recent_span
        recent_sell = max(
            0.0, end.sell_money_cum - middle.sell_money_cum) / recent_span
        passed = (
            recent_buy > previous_buy
            and recent_buy > recent_sell
            and recent_sell <= previous_sell
        )
        return (
            "O" if passed else "X",
            previous_buy, recent_buy, previous_sell, recent_sell,
        )

    def _detect_six_staircase(
        self, state: CodeState, points: list[MarketPoint],
    ) -> BottomSignal | None:
        self._last_dip_meta = {}
        if not points:
            return None
        point = points[-1]
        if point.price <= 0:
            return None
        reference_price = state.six_reference_price
        if reference_price <= 0:
            return None
        if (
            state.six_episode_high <= 0
            or reference_price > state.six_episode_high
        ):
            self._reset_six_cycle(state, point)
        state.six_episode_high = reference_price

        if state.six_phase == "IDLE":
            if state.six_low <= 0 or point.price < state.six_low:
                state.six_low = point.price
                state.six_low_ts = point.ts
                state.six_low_buy_money = point.buy_money_cum
                state.six_low_sell_money = point.sell_money_cum
            drop_pct = (
                (state.six_episode_high - state.six_low)
                / state.six_episode_high * 100.0
            )
            if drop_pct < DIP_DROP_PCT:
                return None
            state.six_phase = "CHASE"
            state.six_low_ts = point.ts
            state.six_low_buy_money = point.buy_money_cum
            state.six_low_sell_money = point.sell_money_cum
            state.six_pre_buy_rate, state.six_pre_sell_rate = (
                self._six_pre_rates(points, point.ts)
            )
            return None

        if point.price < state.six_low:
            state.six_reset_steps += 1
            state.six_low = point.price
            state.six_low_ts = point.ts
            state.six_low_buy_money = point.buy_money_cum
            state.six_low_sell_money = point.sell_money_cum
            state.six_pre_buy_rate, state.six_pre_sell_rate = (
                self._six_pre_rates(points, point.ts)
            )
            state.six_phase = "CHASE"
            if state.six_dead_low <= 0 or point.price < state.six_dead_low:
                state.six_dead_low = 0.0
            self._clear_six_retest(state)
            return None

        if state.six_low <= 0 or state.six_low_ts is None:
            self._reset_six_cycle(state, point)
            return None
        if state.six_dead_low > 0 and state.six_low >= state.six_dead_low:
            return None

        rebound_floor = state.six_low * (1.0 + SIX_FIRST_REBOUND_PCT / 100.0)
        chase_ceiling = state.six_low * (1.0 + SIX_CHASE_CAP_PCT / 100.0)
        entry_floor = state.six_low * (1.0 + SIX_ENTRY_FLOOR_PCT / 100.0)
        higher_low_floor = state.six_low * (
            1.0 + SIX_HIGHER_LOW_BUFFER_PCT / 100.0)

        if state.six_phase == "CHASE":
            if point.price > chase_ceiling:
                state.six_dead_low = state.six_low
                return None
            if point.price >= rebound_floor:
                state.six_phase = "OBSERVE"
                state.six_observe_since = point.ts
                state.six_first_rebound_peak = point.price
                state.six_pullback_seen = False
                state.six_pullback_low = 0.0
            return None

        if state.six_observe_since is None or state.six_first_rebound_peak <= 0:
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None
        if point.price > chase_ceiling:
            state.six_dead_low = state.six_low
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None
        elapsed = (point.ts - state.six_observe_since).total_seconds()
        if elapsed > SIX_OBSERVE_MAX_SEC:
            state.six_dead_low = state.six_low
            state.six_phase = "CHASE"
            self._clear_six_retest(state)
            return None

        if not state.six_pullback_seen:
            state.six_first_rebound_peak = max(
                state.six_first_rebound_peak, point.price)
            pullback_trigger = state.six_first_rebound_peak * (
                1.0 - SIX_PULLBACK_MIN_PCT / 100.0)
            if point.price <= pullback_trigger:
                if point.price < higher_low_floor:
                    state.six_phase = "CHASE"
                    self._clear_six_retest(state)
                    return None
                state.six_pullback_seen = True
                state.six_pullback_low = point.price
        else:
            if point.price < higher_low_floor:
                state.six_phase = "CHASE"
                self._clear_six_retest(state)
                return None
            state.six_pullback_low = min(state.six_pullback_low, point.price)

        if elapsed < SIX_OBSERVE_SEC:
            return None
        if not state.six_pullback_seen or state.six_pullback_low <= 0:
            return None
        if point.price < state.six_pullback_low * (
            1.0 + SIX_SECOND_REBOUND_PCT / 100.0
        ):
            return None
        if point.price < entry_floor or point.price > chase_ceiling:
            return None

        flow_elapsed = max(1.0, (point.ts - state.six_low_ts).total_seconds())
        delta_buy = point.buy_money_cum - state.six_low_buy_money
        delta_sell = point.sell_money_cum - state.six_low_sell_money
        post_buy = max(0.0, delta_buy) / flow_elapsed
        post_sell = max(0.0, delta_sell) / flow_elapsed
        flow_flip = ""
        if (
            state.six_pre_buy_rate >= 0
            and state.six_pre_sell_rate >= 0
            and (state.six_pre_buy_rate + state.six_pre_sell_rate) > 0
            and (post_buy + post_sell) > 0
        ):
            flow_flip = "O" if (
                state.six_pre_sell_rate > state.six_pre_buy_rate
                and post_buy > post_sell
            ) else "X"
        acceleration = self._six_flow_acceleration(points)
        if flow_flip != "O" or acceleration[0] != "O":
            return None

        drop_pct = (
            (state.six_episode_high - state.six_low)
            / state.six_episode_high * 100.0
        )
        rebound_pct = (point.price / state.six_low - 1.0) * 100.0
        self._last_dip_meta = {
            "dip_low_reset_steps": state.six_reset_steps,
            "dip_buy_money_since_low": round(delta_buy, 1),
            "dip_sell_money_since_low": round(delta_sell, 1),
            "dip_buy_sell_ratio": (
                round(delta_buy / delta_sell, 3) if delta_sell > 0 else None),
            "dip_flow_obs_sec": round(flow_elapsed, 1),
            "dip_drop_pct": round(drop_pct, 3),
            "dip_episode_high": round(state.six_episode_high, 4),
            "dip_flow_flip": flow_flip,
            "flow_accel": acceleration[0],
            "previous_buy_rate_10s": round(acceleration[1], 1),
            "recent_buy_rate_10s": round(acceleration[2], 1),
            "previous_sell_rate_10s": round(acceleration[3], 1),
            "recent_sell_rate_10s": round(acceleration[4], 1),
            "first_rebound_peak": state.six_first_rebound_peak,
            "pullback_low": state.six_pullback_low,
            "observe_sec": round(elapsed, 1),
        }
        return BottomSignal(
            algorithm="S02_S06_STAIRCASE_RETEST_V1",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=state.six_low_ts,
            anchor_low_price=state.six_low,
            wave_count=state.six_reset_steps + 1,
            reason=(
                f"S06_STAIRCASE drop={drop_pct:.2f}% "
                f"rebound={rebound_pct:.2f}%"
            ),
        )

    def _detect_dip_rebound(self, points):
        if SIX_STYLE:
            state = getattr(self, "_detect_state", None)
            if state is None:
                return None
            surge_signal = self._detect_money_surge_onset(state, points)
            if surge_signal is not None:
                return surge_signal
            return self._detect_six_staircase(state, points)
        """★[2026-07-31] 되돌림 판정 — 장중 고점 대비 DIP_DROP_PCT 밀린 뒤
        저점에서 DIP_REBOUND_PCT 회복하면 신호. 저점 +DIP_CHASE_CAP_PCT 를 넘으면
        추격이라 보고 신호를 내지 않는다. 부작용 없음(테스트용 분리).

        기존 detect_flow_book_exhaustion 과 반환 형식(BottomSignal)이 같아
        이후 흐름(호가 확인·확정 대기·anchor 중복 방지)은 그대로 작동한다."""
        self._last_dip_meta = {}
        if len(points) < 3:
            return None
        high = points[0].price
        low = points[0].price
        low_ts = points[0].ts
        low_idx = 0                          # ★저점 리셋 지점(매수/매도 배수 기준)
        steps = 0                            # ★계단 수 = 저점이 새로 갱신된 횟수
        armed = False
        for idx, p in enumerate(points):
            if p.price <= 0:
                continue
            if p.price > high:              # 새 고점 → 되돌림 계산을 다시 시작
                high = low = p.price
                low_ts = p.ts
                low_idx = idx
                steps = 0
                armed = False
                continue
            if p.price < low:
                low = p.price
                low_ts = p.ts
                low_idx = idx               # ★저점 리셋
                steps += 1
            if high > 0 and (high - low) / high * 100.0 >= DIP_DROP_PCT:
                armed = True
        if not armed or low <= 0:
            return None
        last = points[-1]
        rebound = (last.price / low - 1.0) * 100.0
        # ★[2026-07-31 친구님 지시 "저점 리셋 매수매도 배수 기록 붙여줘"]
        #   당일 누적 매수비율은 아침부터의 전체가 섞여 바닥 순간의 변화를 못 본다.
        #   저점을 찍은 그 순간의 누적을 기준으로 삼고 그 뒤 증가분만 비교한다
        #   (저점매수 매도기의 '꼭지 리셋'과 같은 원리를 매수에 적용).
        #   지금은 매수 판정에 쓰지 않고 기록만 한다 — 문턱을 정할 근거가 아직 없다.
        #   3거래일쯤 쌓이면 "배수가 높았던 건이 실제로 더 올랐나"를 보고 문턱을 정한다.
        #   steps = 계단 수(저점이 몇 번 더 낮아졌나) → 계단식 하락을 사후에 걸러낼 자료.
        d_buy = last.buy_money_cum - points[low_idx].buy_money_cum
        d_sell = last.sell_money_cum - points[low_idx].sell_money_cum
        self._last_dip_meta = {
            "dip_low_reset_steps": steps,
            "dip_buy_money_since_low": round(d_buy, 1),
            "dip_sell_money_since_low": round(d_sell, 1),
            "dip_buy_sell_ratio": (round(d_buy / d_sell, 3) if d_sell > 0 else None),
            "dip_flow_obs_sec": round((last.ts - points[low_idx].ts).total_seconds(), 1),
            "dip_drop_pct": round((high - low) / high * 100.0, 3),
            "dip_episode_high": round(high, 4),
        }
        # ★[2026-08-01 "6번과 동일하게"] ①관찰 60초 ②속도 역전 (상단 SIX_STYLE 주석)
        if SIX_STYLE:
            obs_sec = (last.ts - points[low_idx].ts).total_seconds()
            if obs_sec < SIX_OBSERVE_SEC:
                return None
            flip = ""
            pre = [p for p in points[:low_idx + 1]
                   if (points[low_idx].ts - p.ts).total_seconds() <= 180.0]
            if len(pre) >= 2:
                span = (pre[-1].ts - pre[0].ts).total_seconds()
                if span >= 30.0:
                    pre_b = max(0.0, pre[-1].buy_money_cum - pre[0].buy_money_cum) / span
                    pre_s = max(0.0, pre[-1].sell_money_cum - pre[0].sell_money_cum) / span
                    post_b = max(0.0, d_buy) / max(1.0, obs_sec)
                    post_s = max(0.0, d_sell) / max(1.0, obs_sec)
                    if (pre_b + pre_s) > 0 and (post_b + post_s) > 0:
                        flip = "O" if (pre_s > pre_b and post_b > post_s) else "X"
            self._last_dip_meta["dip_flow_flip"] = flip
            if flip == "X":
                return None
        if rebound < DIP_REBOUND_PCT or rebound > DIP_CHASE_CAP_PCT:
            return None
        return BottomSignal(
            algorithm="S02_DIP_REBOUND_V1",
            signal_ts=last.ts,
            signal_price=last.price,
            anchor_low_ts=low_ts,
            anchor_low_price=low,
            wave_count=1,
            reason=(f"DIP_REBOUND drop={(high - low) / high * 100.0:.2f}% "
                    f"rebound={rebound:.2f}%"),
        )

    def process_point(
        self,
        code: str,
        name: str,
        point: MarketPoint,
        *,
        allow_signal: bool = True,
        open_price: float = 0.0,
        session_high: float = 0.0,
    ) -> tuple[Dict[str, Any], bool]:
        state = self.states.setdefault(code, CodeState())
        if open_price > 0:
            state.open_price = open_price
        state.session_high = max(state.session_high, session_high, point.price)
        if open_price > 0:
            state.open_price = open_price
        state.session_high = max(state.session_high, session_high, point.price)
        if state.points:
            last = state.points[-1]
            if point.ts <= last.ts:
                return self._wait_row(code, name, point, "DUPLICATE_SNAPSHOT"), False
            # ★[2026-07-30 친구님 지시] 관측창 리셋 문턱 10초 → 20초.
            #   증상: 7/27 이후 3거래일 신호 0건(회전엔진 로그 7/28·29·30 각 1줄=기동만).
            #   7/27은 매수 6건 + 신호 19건이 났다 → 매도소진 5개 조건은 통과 가능하다.
            #   바뀐 것은 조건이 아니라 들어오는 데이터. 7/28에 발견된 "전략 감시 종목이
            #   실시간 구독을 못 받는다(돈맥 195개가 상한 200 독점 → strategy 몫 0칸)"와 날짜가 맞다.
            #   실측(7/30 11:20): 스냅샷 1,477종목 중 66%가 6초↑, 38%가 5분↑ 낡음.
            #   그림자 3일치 대조(s02_window_shadow_2026072[8|9]·30):
            #     10초 = 리셋 하루 8천~2만회 / 창180초↑ 확보 평균 74.3%
            #     20초 = 리셋 1/3로 감소     / 창180초↑ 확보 평균 92.2%  (+17.9%p)
            #   ⚠ 근본 원인은 구독 슬롯 부족이다. 5분 이상 낡은 38%는 이 문턱으로 못 살린다.
            #   되돌리기: RUN\backup\strategy_02_low_buy_signal_v1_20260730_reset20s.py 복원(=10초 원본).
            # ★[2026-07-30 2차 지시] 20초 → 60초. 20초도 부족했다.
            #   실측(후보 175종목·40초 관측): 최대 갱신 간격 p50=8.2초·p90=22.6초.
            #   40초 안에 문턱 초과가 1번 이상 발생한 비율 = 6초 66.3% / 10초 40.0% /
            #   20초 13.1% / 30초 5.7% / 60초 0.0%.
            #   창 300초를 채우려면 약 150번 연속 공백이 없어야 한다 → 20초로는 거의 확실히 걸린다.
            #   60초가 안전한 이유: 실시간은 체결이 있을 때만 온다 → 공백 = 거래 없음 = 가격 불변.
            #   이 전략이 보는 종목은 micro_watch_strategy_shared(140)에 전부 포함돼 구독된다
            #   → "체결이 있었는데 놓친" 경우가 아니다. 누계 역전 조건은 그대로 남긴다(실측 0건).
            if (
                point.buy_money_cum < last.buy_money_cum
                or point.sell_money_cum < last.sell_money_cum
                or (point.ts - last.ts).total_seconds() > 60
            ):
                state.points.clear()
                if SIX_STYLE:
                    self._reset_six_cycle(state)
                    self._reset_money_surge(state)
        state.points.append(point)
        # ★[2026-07-30 친구님 지시] 관측창 300초(5분) → 1800초(30분).
        #   사유: 이 전략은 "늘어지는 하락의 매도 소진"을 잡는 설계인데, 매도 소진 판정은
        #   하락 파동 2개를 비교한다(previous_leg vs current_leg·약화 지표 2개 이상).
        #   창이 5분이면 각 파동이 2분 30초 이내여야 담긴다 → 실제로는 "5분 안에 두 번
        #   꺾이는 빠른 진동"만 포착했다. 설계 의도와 구현이 어긋나 있었다.
        #   실측 사례: 087010 펩트론이 09:30 136,800 → 09:56 129,000(26분에 -5.70%)로
        #   흘러내렸는데 파동 하나도 창에 못 담겨 FLOW_BOOK_RECOVERY_WAIT로 종일 대기.
        #   (이 종목은 급락이 아니라 늘어지는 하락이므로 전략03 소관이 아니라 이 전략 소관이다)
        #   ⚠ 부하: 루프당 순회가 약 3.6만 점 → 21만 점(6배). 재시작 직후 루프 속도로 검증한다.
        #     기준 = s02_window_shadow 의 loops/경과초. 재시작 전 0.979루프/초.
        #     0.5루프/초 아래로 떨어지면 판정 주기가 늘어져 신호를 놓치므로 되돌린다.
        #   되돌리기: RUN\backup\strategy_02_low_buy_signal_v1_20260730_reset20s.py 복원(=5분·10초 원본).
        cutoff = point.ts.timestamp() - 1800
        while state.points and state.points[0].ts.timestamp() < cutoff:
            state.points.popleft()

        if state.handoff_to_s03_s06:
            return self._wait_row(
                code, name, point, "OPEN_DROP_LE_4PCT_HANDOFF_S03_S06"), False
        open_drop_pct = (
            (point.price / state.open_price - 1.0) * 100.0
            if state.open_price > 0 else 0.0
        )
        if state.open_price > 0 and open_drop_pct <= DEEPER_HANDOFF_OPEN_DROP_PCT:
            state.handoff_to_s03_s06 = True
            state.six_phase = "DONE"
            self._clear_six_retest(state)
            self._clear_pending(state)
            return self._wait_row(
                code, name, point, "OPEN_DROP_LE_4PCT_HANDOFF_S03_S06"), False

        morning = point.ts.time() < MORNING_OPEN_REFERENCE_END
        reference_price = state.open_price if morning else state.session_high
        if reference_price <= 0:
            self._clear_pending(state)
            return self._wait_row(
                code, name, point, "REFERENCE_PRICE_MISSING"), False
        state.six_reference_price = reference_price
        state.six_reference_mode = "OPEN" if morning else "INTRADAY_HIGH"

        # ★[2026-07-31] 되돌림 판정으로 교체(위 DIP_MODE 주석 참조).
        #   S02_DIP_MODE=NO 로 두면 종전 매도소진 판정으로 즉시 복귀한다.
        if DIP_MODE:
            self._detect_state = state
            signal = self._detect_dip_rebound(list(state.points))
            wait_reason = (
                "S02_MONEY_SURGE_OR_STAIRCASE_WAIT" if SIX_STYLE
                else "DIP_REBOUND_WAIT"
            )
        else:
            signal = detect_flow_book_exhaustion(list(state.points))
            wait_reason = "FLOW_BOOK_RECOVERY_WAIT"
        if signal is None:
            self._clear_pending(state)
            return self._wait_row(code, name, point, wait_reason), False
        if abs((point.ts - signal.signal_ts).total_seconds()) > 1:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "STALE_DETECTOR_RESULT"), False
        anchor_id = (
            f"{signal.anchor_low_ts.isoformat(timespec='seconds')}:"
            f"{signal.anchor_low_price:.4f}"
        )
        book_ok, book_reason, spread_bps, edge_bps, best_bid_share = (
            self._book_telemetry(point)
        )
        if not book_ok and not SIX_STYLE:
            # ★[2026-08-01 친구님 "6번에 없는 건 넣지 마·똑같이"] 6번에는 호가 관문이
            #   없다 — SIX_STYLE 에서는 스프레드/호가 값은 기록만 하고 막지 않는다.
            self._clear_pending(state)
            return self._wait_row(code, name, point, book_reason), False
        if not allow_signal:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ENTRY_TIME_CLOSED"), False
        if (
            anchor_id in state.emitted_anchors
            or state.emission_count >= self.max_signals_per_code
        ):
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ANCHOR_OR_CYCLE_ALREADY_USED"), False
        # ★[2026-08-01 "6번과 동일하게"] ③재무장 깊이 — 2번째 신호는 직전 신호
        #   저점보다 SIX_REARM_DEEPER_PCT 만큼 더 깊은 저점에서만.
        # ★[2026-08-01 밤 친구님 "왜 장 고점에서 떨어져서 사는 건 하나도 없니"]
        #   예외 추가 — 직전 신호 뒤 "새 고점"을 갱신했다면 재무장 허용.
        #   더 깊은 저점만 요구하는 건 6번(폭포) 세계의 규칙이고, 2번의 본업
        #   (올라갔다 눌리는 놈)은 다음 눌림 저점이 더 높은 게 정상이라
        #   종전 규칙이 장 고점 눌림 매수를 전부 차단하고 있었다.
        episode_high = _number(
            (getattr(self, "_last_dip_meta", None) or {}).get("dip_episode_high"))
        made_new_high = (
            state.last_signal_high > 0 and episode_high > state.last_signal_high
        )
        if (
            SIX_STYLE
            and state.last_signal_low > 0
            and not made_new_high
            and signal.anchor_low_price
            >= state.last_signal_low * (1.0 - SIX_REARM_DEEPER_PCT / 100.0)
        ):
            self._clear_pending(state)
            return self._wait_row(code, name, point, "REARM_NEED_DEEPER_LOW"), False

        if SIX_STYLE:
            # ★[2026-08-01 친구님 "똑같이"] 6번에는 확정 대기가 없다 — 관찰 60초와
            #   속도 역전이 이미 그 역할을 했다. 곧장 발행 판정으로 간다.
            confirm_age_sec = 0.0
        else:
            if state.pending_anchor_id != anchor_id or state.pending_since is None:
                state.pending_anchor_id = anchor_id
                state.pending_since = point.ts
                state.pending_signal_price = point.price
                state.pending_hits = 1
                return self._wait_row(code, name, point, "ENTRY_CONFIRM_WAIT"), False

            chase_bps = (
                (point.price / state.pending_signal_price - 1.0) * 10_000.0
                if state.pending_signal_price > 0
                else 0.0
            )
            if chase_bps < 0 or chase_bps > self.max_confirm_chase_bps:
                state.pending_since = point.ts
                state.pending_signal_price = point.price
                state.pending_hits = 1
                return self._wait_row(
                    code, name, point, "ENTRY_CONFIRM_PRICE_RESET"), False

            state.pending_hits += 1
            confirm_age_sec = max(
                0.0, (point.ts - state.pending_since).total_seconds())
            if (
                confirm_age_sec < self.confirm_sec
                or state.pending_hits < self.confirm_points
            ):
                return self._wait_row(code, name, point, "ENTRY_CONFIRM_WAIT"), False

        entry_gap = (point.price / signal.anchor_low_price - 1) * 100
        # ★[2026-08-01 친구님 승인 "3건 다 고쳐줘"] 딥모드 실효 진입띠 수리 —
        #   판정(_detect_dip_rebound)은 저점 +3.0%(DIP_CHASE_CAP_PCT)까지 허용하는데
        #   여기 옛 1.5% 관문이 살아남아 [0.5, 1.5]% 로 좁히고 있었다(8/1 점검 발견 3.
        #   33행 폐기 목록의 "진입가 저점+1.5% 이내"가 실제로는 안 죽어 있던 것).
        #   딥모드에서만 상한을 3.0% 로 통일 — S02_DIP_MODE=NO 롤백 시엔 종전 1.5% 그대로.
        #   롤백: backup\strategy_02_low_buy_signal_v1_20260801_secfix.py 복원.
        entry_gap_cap = (
            SIX_CHASE_CAP_PCT if SIX_STYLE
            else DIP_CHASE_CAP_PCT if DIP_MODE
            else self.max_entry_gap_pct
        )
        if entry_gap > entry_gap_cap:
            self._clear_pending(state)
            return self._wait_row(code, name, point, "ENTRY_GAP_TOO_WIDE"), False

        state.emission_count += 1
        state.emitted_anchors.add(anchor_id)
        state.last_signal_low = float(signal.anchor_low_price)
        state.last_signal_high = _number(
            (getattr(self, "_last_dip_meta", None) or {}).get("dip_episode_high"),
            point.price)
        imbalance = (point.bid_tot - point.ask_tot) / (point.bid_tot + point.ask_tot)
        row = {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "BUY_READY",
            "reason": signal.reason,
            "price": point.price,
            "anchor_low": signal.anchor_low_price,
            "anchor_low_ts": signal.anchor_low_ts.isoformat(timespec="seconds"),
            "anchor_id": anchor_id,
            "entry_gap_pct": round(entry_gap, 4),
            "book_imbalance": round(imbalance, 4),
            "best_ask_price": point.best_ask_px,
            "spread_bps": round(spread_bps, 4),
            "microprice_edge_bps": round(edge_bps, 4),
            "best_bid_share": round(best_bid_share, 4),
            "confirm_age_sec": round(confirm_age_sec, 3),
            "confirm_points": state.pending_hits,
            "wave_count": signal.wave_count,
            "signal_sequence": state.emission_count,
            "algorithm": signal.algorithm,
            "mode": SIGNAL_MODE,
        }
        # ★[2026-07-31] 저점 리셋 기준 매수/매도 배수·계단 수 기록(판정에는 미사용)
        row.update(getattr(self, "_last_dip_meta", None) or {})
        self._clear_pending(state)
        state.points.clear()
        state.points.append(point)
        if SIX_STYLE:
            self._reset_six_cycle(state, point)
            self._reset_money_surge(state)
        return row, True

    @staticmethod
    def _wait_row(
        code: str,
        name: str,
        point: MarketPoint,
        reason: str,
    ) -> Dict[str, Any]:
        imbalance = (point.bid_tot - point.ask_tot) / (point.bid_tot + point.ask_tot)
        return {
            "ts": point.ts.isoformat(timespec="seconds"),
            "code": code,
            "name": name,
            "action": "WAIT",
            "reason": reason,
            "price": point.price,
            "book_imbalance": round(imbalance, 4),
            "mode": SIGNAL_MODE,
        }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(1, 4):
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
            return True
        except PermissionError as exc:
            if attempt >= 3:
                print(
                    f"ATOMIC_WRITE_RETRY_EXHAUSTED path={path} error={exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return False
            time_module.sleep(0.05 * attempt)
    return False

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


def run(config: SignalConfig, *, once: bool = False) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    monitor = LowBuySignalMonitor(
        max_signals_per_code=config.max_signals_per_code,
        confirm_sec=config.confirm_sec,
        confirm_points=config.confirm_points,
        max_spread_bps=config.max_spread_bps,
        min_microprice_edge_bps=config.min_microprice_edge_bps,
        min_best_bid_share=config.min_best_bid_share,
        max_confirm_chase_bps=config.max_confirm_chase_bps,
        max_entry_gap_pct=config.max_entry_gap_pct,
    )
    monitor.restore(_read_json(config.output_path), now.strftime("%Y%m%d"))
    while True:
        now = datetime.now(KST).replace(tzinfo=None)
        points, status, watch_count, range_meta = load_live_points(config, now)
        minute_refs = _minute_references(
            _read_json(config.minute_path), now.strftime("%Y%m%d"))
        new_signals = []
        for code, name, point in points:
            allow = ENTRY_START <= point.ts.time() < ENTRY_END
            reference = minute_refs.get(code) or {}
            row, fired = monitor.process_point(
                code, name, point, allow_signal=allow,
                open_price=_number(reference.get("open")),
                session_high=_number(reference.get("high")),
            )
            row.update(range_meta.get(code) or {})
            monitor.latest[code] = row
            if fired:
                monitor.signals.append(dict(row))
                new_signals.append(dict(row))
        payload = {
            "schema": SIGNAL_SCHEMA,
            "date": now.strftime("%Y%m%d"),
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": SIGNAL_MODE,
            "status": status,
            "watch_count": watch_count,
            "signals": monitor.signals[-1000:],
            "candidates": list(monitor.latest.values()),
        }
        _write_json_atomic(config.output_path, payload)
        _append_events(
            config.event_dir / f"strategy_02_signals_{now:%Y%m%d}.csv",
            new_signals,
        )
        if once or now.weekday() >= 5 or now.time() >= time(14, 21):
            return 0
        time_module.sleep(max(0.2, config.loop_sec))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return run(SignalConfig(), once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
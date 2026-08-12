# -*- coding: utf-8 -*-
"""Strategy 03 intraday crash-rebound buy-signal state machine.

This module has no broker or order imports.  It is deliberately separate from
OPEN_CRASH so the proven 09:00-09:20 detector remains unchanged.
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Protocol

# ★[2026-07-31 친구님 지시] 매수흐름 확인 관문 5개 폐기(근거는 gates 주석 참조).
FLOW_GATES_OFF = os.environ.get("S03_FLOW_GATES_OFF", "YES").strip().upper() == "YES"

from strategy_03_signal_contract_v1 import (
    INTRADAY_CRASH_ALGORITHM,
    INTRADAY_CRASH_LANE,
    INTRADAY_MAX_REBOUND_PCT,
    INTRADAY_MIN_DRAWDOWN_PCT,
    INTRADAY_MIN_REBOUND_PCT,
    SIGNAL_MODE,
)


class IntradayPoint(Protocol):
    ts: datetime
    price: float
    # ★[S03-OPENPRICE-FIX 2026-08-06 친구님 지시 "셋 다 고쳐"] 당일 시가.
    #   실제로 넘어오는 객체(골짜기_급반등.py MicroPoint)에는 원래 있었는데
    #   여기 규약에 없어서 신호 행에 안 실렸다. 그 결과 회전엔진 선별기가
    #   (strategy_03_rotation_engine_v1.py:141 `open_price <= 0` → continue)
    #   INTRADAY 레인 신호를 **전부** 버렸다 — S03 역대 매수 0건의 원인.
    open_price: float
    buy_volume_cum: float
    sell_volume_cum: float
    buy_money_cum: float
    sell_money_cum: float
    best_ask_px: float
    best_bid_px: float
    best_ask_qty: float
    best_bid_qty: float

    @property
    def book_valid(self) -> bool: ...


@dataclass(frozen=True)
class IntradayReboundConfig:
    # ★[2026-07-30 친구님 지시] 급락 판정 창 15분 → 10분.
    #   지시 원문: "골짜기는 급락이고 (…) 골짜기가 급락이면 5분이면 돼".
    #   사유: 전략03은 급락 전용이므로 창이 짧아야 한다. 창이 길면 천천히 흘러내린 하락까지
    #   급락으로 잡아 성격이 무너진다. 10분에 3% = 시간당 18% 속도가 최소 급락 기준이 된다.
    #   5분(300초)이 지시값이었으나 __post_init__ 검증이 600초 하한이라 10분이 허용 최소값.
    #   검증까지 완화하지 않기로 친구님이 결정("10분으로 해") — 수정 지점을 1곳으로 유지.
    #   ⚠ 같은 날 30분으로 늘렸던 것은 방향이 반대였다(오판). 087010 펩트론은 26분에 걸친
    #     -5.70% 하락이라 급락이 아니고, 전략02(저점매수·매도소진) 소관이다. 전략03 표적 아님.
    #   ⚠ 창이 짧아지면 3% 문턱이 엄격해져 신호가 더 줄어든다. 며칠 0건이 정상일 수 있다.
    #   ⚠ 이 검출기는 INTRADAY_CRASH 레인 전용 — OPEN_CRASH(RapidReboundDetector)는 무영향.
    #   되돌리기: RUN\backup\strategy_03_intraday_rebound_v1_20260730_window30m.py 복원(=15분 원본).
    # ★[2026-07-31 친구님 지시 "0.5%로 만들어줘 / 첫 양봉에 진입해야 돈이 돼"]
    #   09:21 이후 이 레인이 잡을 것 = "급락 후 장대양봉이 연속으로 크게 나오는 것"인데,
    #   양봉이 완성되기를 기다리면 이미 다 올라 먹을 게 없다. 첫 양봉 진행 중에 잡는다.
    #   7/31 실측(09:21~14:30 · 3분봉 음봉 뒤 첫 양봉에서 저점 대비 X% 회복 시 매수):
    #       저점 +0.5%  29종목 · **+4.11%** · 승률 86%   ← 채택
    #       저점 +1.0%  26종목 ·  +3.19%  · 승률 85%
    #       저점 +1.5%  19종목 ·  +2.29%  · 승률 84%
    #       저점 +2.0%   8종목 ·  +0.15%  · 승률 62%     ← 늦으면 무너진다
    #     (양봉 2개 완성 후 진입은 7종목 +4.13% — 평균은 같지만 건수가 4분의 1)
    #   낙폭 문턱 3.0 → 1.5: 3분봉 음봉 하나면 충분하다는 취지. 7/31 진단에서
    #     INTRADAY_DRAWDOWN_LT_3PCT 로 24건이 탈락했다(3% 낙폭이 09:21 이후엔 드물다).
    #   ⚠️하루 표본이고 3분봉을 분당 현재가로 근사해 잰 값이다.
    #   되돌리기: RUN\backup\strategy_03_intraday_rebound_v1_20260731_firstbull.py 복원
    high_window_sec: float = 10 * 60
    min_drawdown_pct: float = INTRADAY_MIN_DRAWDOWN_PCT
    min_rebound_pct: float = INTRADAY_MIN_REBOUND_PCT
    max_rebound_pct: float = INTRADAY_MAX_REBOUND_PCT
    # ★[S03-LANE2 2026-08-06 친구님 지시 "2초 관찰, 바로 상승해야 되고, 1분 안에 바로
    #   상승하지 않으면 매수 금지야. 급락 후 바로 급상승하는 거 잡기 위함이야"]
    #   관찰 3초 → 2초, 확인창 180초 → 60초. 저점이 생기고 1분 안에 반등(+0.5~1.0%)과
    #   매수 방법 확인(1레인 급행과 같은 감속+가속+우위)이 안 오면 그 저점은 폐기 —
    #   더 낮은 새 저점이 나와야 다시 자격을 얻는다(바닥에 닿자마자 튀는 것만 잡는다).
    #   닷새 캡처 전수(A안): 고저폭30 실전 우주 43건 · 손절 60.5% · 평균 +1.43%
    #   (8/4 +1.69% · 8/6 +1.31% — 1레인이 진 날에도 플러스). 우위 제외(B안)와 차이 없음
    #   (645건 vs 637건 · 평균 동일)이라 친구님 원설계("역매수세")대로 우위 포함.
    #   되돌리기: backup\s03_lane2_20260806\ 복원.
    low_stable_sec: float = 2.0
    max_confirm_sec: float = 60.0
    min_entry_money_krw: float = 10_000_000.0
    # ★[2026-07-31] 매수세 확인 문턱 0.58 → 0.50(사실상 해제).
    #   친구님 물음 "매도세가 급격히 떨어지고 매수세가 보이면 진입하나?" 에 대한 실측 답 —
    #   7/31(저점 +1.0% 기준) 매수세 조건을 더할수록 나빠졌다:
    #       조건 없음   26종목 · +3.19% · 85%
    #       매수비율 50%↑ 22종목 · +2.98% · 82%
    #       매수비율 55%↑ 16종목 · +2.51% · 88%
    #       매수비율 60%↑  9종목 · +2.80% · 89%
    #       매수비율 65%↑  2종목 · **-0.95%** · 50%
    #   매수세가 눈에 보일 때쯤이면 값이 이미 올라 있다 = 늦다. 승률은 조금 오르지만
    #   건수가 3분의 1로 줄어 총액이 준다. 0.50 = "매도 우위만 아니면 통과".
    #   ⚠️검증 로직(__post_init__)이 0.5 초과만 허용한다 → 0.51 = 허용 가능한 최소값.
    #     "매수가 매도보다 아주 조금이라도 우위" = 사실상 해제와 같다.
    min_buy_volume_ratio: float = 0.51
    min_buy_money_ratio: float = 0.51
    persistence_fraction: float = 0.80
    max_spread_bps: float = 35.0
    # ★[2026-07-30 친구님 지시] 데이터 공백 리셋 문턱 6초 → 60초.
    #   증상: INTRADAY 후보의 76~91%가 CUMULATIVE_REVERSE_OR_DATA_GAP_RESET 상태로 고정.
    #   원인(실측): 후보 175종목의 최대 갱신 간격 p50=8.2초·p90=22.6초.
    #     40초만 관측해도 6초 공백을 겪는 종목이 66.3%(10초 40.0% / 20초 13.1% / 60초 0.0%).
    #     창 600초를 채우려면 약 300번 연속으로 공백이 없어야 하는데 구조적으로 불가능하다.
    #   왜 60초가 안전한가:
    #     ① 실시간은 체결이 있을 때만 온다 → 공백 = 그 시간 동안 거래 없음 = 가격 불변.
    #        이어붙여도 파동이 왜곡되지 않는다.
    #     ② 이 전략이 보는 종목은 micro_watch_strategy_shared(140)에 전부 포함돼 구독된다
    #        → "체결이 있었는데 놓친" 경우가 아니다(구독 배분 실측으로 확인).
    #     ③ 누계 역전(reversed_counter)은 그대로 남긴다 — 실측 0건이지만 진짜 데이터 오류 감지용.
    #   되돌리기: RUN\backup\strategy_03_intraday_rebound_v1_20260730_window30m.py 복원(=6초·15분 원본).
    # ★[2026-07-31 친구님 승인] 60초 → 150초. 60초로도 여전히 부족했다.
    #   실측(7/31 11:43): 감시명단 116종목 중 50종목(43%)이 RESET 상태로 고정.
    #   그 50종목의 **재평가 간격 중앙값이 91초** — 60초 문턱을 볼 때마다 넘어
    #   이력이 매번 초기화되고 10분 창을 영영 못 채우는 자기강화 루프가 된다.
    #   ⚠ 원인은 데이터 부족이 아니다(같은 시각 스냅샷 갱신은 리셋군/정상군 동일:
    #     60초에 ts 21회·체결누계 7회). 누계 역전도 0건. 엔진 순회 6.7초.
    #     즉 "데이터는 오는데 엔진이 그 종목을 91초에 한 번만 집는" 상태였다.
    #   150초 근거 = 관측 중앙 91초 + 안전여유. 7/30 논리 그대로 적용:
    #     공백 = 그 시간 동안 체결 없음 = 가격 불변 → 이어붙여도 파동 왜곡 없음.
    #   ⚠ 백테 불가(실시간 도착 간격은 과거 자료에 없음) → 적용 후 실측으로만 검증.
    #   ⚠ OPEN_CRASH 레인(골짜기_급반등.py:53 max_gap_sec=6.0)은 건드리지 않았다.
    #   되돌리기: RUN\backup\strategy_03_intraday_rebound_v1_20260731_gap150.py 복원
    max_gap_sec: float = 150.0
    max_signals_per_code: int = 2

    def __post_init__(self) -> None:
        if self.high_window_sec < 600 or self.min_drawdown_pct <= 0:
            raise ValueError("invalid intraday crash window")
        if not 0 < self.min_rebound_pct < self.max_rebound_pct:
            raise ValueError("invalid rebound range")
        if self.low_stable_sec <= 0 or self.max_confirm_sec <= 30:
            raise ValueError("invalid rebound timing")
        if self.min_entry_money_krw <= 0:
            raise ValueError("min_entry_money_krw must be positive")
        if not all(0.5 < ratio < 1 for ratio in (
            self.min_buy_volume_ratio,
            self.min_buy_money_ratio,
            self.persistence_fraction,
        )):
            raise ValueError("invalid buy-flow ratio")
        if self.max_spread_bps <= 0 or self.max_gap_sec <= 0:
            raise ValueError("invalid market-data guard")
        if self.max_signals_per_code != 2:
            raise ValueError("Strategy 03 requires two opportunities per code")


@dataclass
class IntradayReboundState:
    points: Deque[IntradayPoint] = field(default_factory=deque)
    phase: str = "SCAN"
    high_price: float = 0.0
    high_ts: datetime | None = None
    low_point: IntradayPoint | None = None
    low_updated_at: datetime | None = None
    emission_count: int = 0
    last_emitted_low: float = 0.0
    low_reset_steps: int = 0        # ★[2026-07-31] 계단 수 = 저점이 더 낮게 갱신된 횟수
    # ★[S03-DAYHIGH-FIX 2026-08-06 친구님 지시 "장중 고점은 당일 고점으로"]
    #   종전 고점은 10분 창(points 덱) 안의 최대값이라 '당일 고점'이 아니었다.
    #   그래서 낙폭이 실제보다 얕게 나왔다(8/6 코스텍시스 -2.008% 로 신호).
    #   이 둘은 창과 무관하게 그날 내내 갱신만 하고 절대 줄지 않는다.
    #   자료 공백 리셋(_reset_history)에도 살아남는다 - 공백이 있었다고 그날 고점이
    #   사라지는 것은 아니다.
    day_high_price: float = 0.0
    day_high_ts: datetime | None = None
    # ★[2026-08-06 친구님 지시 "계기판 3종 그림자 기록 … 테스트 한번 해보고 배선하자"]
    #   판정에는 절대 안 쓰고 기록만 하는 저점 순간 계기판. 저점이 정해지는 순간
    #   (무장·계단 갱신) 한 번만 계산해 그 사이클의 모든 행에 실린다.
    #   출처: 헤지펀드 급락 저점 탐지 조사(8/6) — ①항복매도 클라이맥스 ②호가 대기열
    #   불균형(Gould·Bonart) ③매도 감속(호크스 연쇄 소진의 실전 근사).
    #   ⚠️조건 승격은 며칠 쌓아 "먹힌 저점 vs 가짜 저점"이 갈리는지 본 뒤에만(7/31 교훈).
    low_gauges: dict[str, Any] = field(default_factory=dict)
    # ★[S03-LANE2 2026-08-06] 폐기된 저점(확인창 60초 초과·추격상한 초과) — 이보다
    #   낮은 새 저점이 나와야 다시 무장한다. "1분 안에 안 튀면 그 저점은 매수 금지".
    dead_low: float = 0.0


class IntradayReboundDetector:
    def __init__(self, config: IntradayReboundConfig | None = None) -> None:
        self.config = config or IntradayReboundConfig()
        self.state = IntradayReboundState()

    def restore_emitted(self, sequence: int, anchor_low: float = 0.0) -> None:
        self.state.emission_count = max(
            self.state.emission_count, int(sequence or 1))
        self.state.last_emitted_low = max(
            self.state.last_emitted_low, float(anchor_low or 0))

    def _reset_history(self) -> None:
        count = self.state.emission_count
        last_low = self.state.last_emitted_low
        # ★[S03-DAYHIGH-FIX 2026-08-06] 당일 고점은 리셋에서 살린다.
        #   자료 공백이 있었다고 그날 찍은 고점이 없던 일이 되지 않는다.
        day_high = self.state.day_high_price
        day_high_ts = self.state.day_high_ts
        # ★[S03-LANE2 2026-08-06] 죽은 저점도 리셋에서 살린다 — 자료 공백이 있었다고
        #   "1분 안에 못 튄 저점"이 되살아나는 것은 아니다.
        dead = self.state.dead_low
        self.state = IntradayReboundState(
            emission_count=count,
            last_emitted_low=last_low,
            day_high_price=day_high,
            day_high_ts=day_high_ts,
            dead_low=dead,
        )

    def _append(self, point: IntradayPoint) -> str | None:
        state = self.state
        # ★[S03-DAYHIGH-FIX 2026-08-06] 당일 고점 갱신은 무조건 먼저 한다.
        #   아래 어느 갈래로 빠지든(중복·자료공백 리셋) 그날 찍힌 값은 기록으로 남긴다.
        if point.price > state.day_high_price:
            state.day_high_price = point.price
            state.day_high_ts = point.ts
        previous = state.points[-1] if state.points else None
        if previous is not None:
            if point.ts <= previous.ts:
                return "DUPLICATE_OR_OLD_SNAPSHOT"
            gap = (point.ts - previous.ts).total_seconds()
            reversed_counter = any((
                point.buy_volume_cum < previous.buy_volume_cum,
                point.sell_volume_cum < previous.sell_volume_cum,
                point.buy_money_cum < previous.buy_money_cum,
                point.sell_money_cum < previous.sell_money_cum,
            ))
            if reversed_counter or gap > self.config.max_gap_sec:
                self._reset_history()
                self.state.points.append(point)
                return "CUMULATIVE_REVERSE_OR_DATA_GAP_RESET"
        state.points.append(point)
        cutoff = point.ts.timestamp() - self.config.high_window_sec
        while state.points and state.points[0].ts.timestamp() < cutoff:
            state.points.popleft()
        return None

    def _money_rate(self, point: IntradayPoint, seconds: float) -> float:
        prior = [
            row for row in list(self.state.points)[:-1]
            if (point.ts - row.ts).total_seconds() >= seconds
        ]
        if not prior:
            return 0.0
        base = prior[-1]
        elapsed = (point.ts - base.ts).total_seconds()
        delta = point.buy_money_cum - base.buy_money_cum
        return max(0.0, delta) / elapsed if elapsed > 0 else 0.0

    def _sell_decel_buy_flip(self, point: IntradayPoint) -> bool:
        # ★[S03-LANE2 2026-08-06 친구님 지시 "레인 1번 저점 매수방법을 똑같이 공유"]
        #   1레인 급행과 같은 판정식(flow_accel: 10초 두 구간 — 매도 감속 + 매수 가속 +
        #   매수 우위)을 2레인 자료(points 덱)로 계산한다. 자료가 성겨 창이 안 채워지면
        #   False = 안 산다(fail-closed) — "바로 상승"만 잡는 창구라 침묵이 안전한 쪽.
        rows = self.state.points
        if len(rows) < 3:
            return False
        window = 10.0
        tolerance = max(3.0, window * 0.4)
        end = rows[-1]
        end_epoch = end.ts.timestamp()
        mid = nxt = None
        for row in reversed(rows):
            epoch = row.ts.timestamp()
            if mid is None and epoch <= end_epoch - window:
                mid = row
            if epoch <= end_epoch - 2.0 * window:
                nxt = row
                break
        if mid is None or nxt is None:
            return False
        if (end_epoch - window) - mid.ts.timestamp() > tolerance:
            return False
        if (end_epoch - 2.0 * window) - nxt.ts.timestamp() > tolerance:
            return False
        prev_span = (mid.ts - nxt.ts).total_seconds()
        recent_span = (end.ts - mid.ts).total_seconds()
        if min(prev_span, recent_span) < window * 0.6:
            return False
        prev_buy = max(0.0, mid.buy_money_cum - nxt.buy_money_cum) / prev_span
        prev_sell = max(0.0, mid.sell_money_cum - nxt.sell_money_cum) / prev_span
        recent_buy = max(0.0, point.buy_money_cum - mid.buy_money_cum) / recent_span
        recent_sell = max(0.0, point.sell_money_cum - mid.sell_money_cum) / recent_span
        return (
            recent_buy > prev_buy
            and recent_buy > recent_sell
            and recent_sell <= prev_sell
        )

    @staticmethod
    def _book_metrics(point: IntradayPoint) -> tuple[float, float]:
        if not point.book_valid:
            return 0.0, 0.0
        midpoint = (point.best_ask_px + point.best_bid_px) / 2.0
        microprice = (
            point.best_ask_px * point.best_bid_qty
            + point.best_bid_px * point.best_ask_qty
        ) / (point.best_bid_qty + point.best_ask_qty)
        return (
            (point.best_ask_px - point.best_bid_px) / midpoint * 10_000.0,
            (microprice / midpoint - 1.0) * 10_000.0,
        )

    def _lookback(self, low: IntradayPoint, seconds: float) -> IntradayPoint | None:
        for row in reversed(self.state.points):
            if (low.ts - row.ts).total_seconds() >= seconds:
                return row
        return None

    def _compute_low_gauges(self, low: IntradayPoint) -> dict[str, Any]:
        # ★[2026-08-06 친구님 지시 "계기판 3종 그림자 기록"] 판정에는 절대 안 쓴다.
        #   저점 갱신 순간에만 계산(틱마다 아님 — _money_rate 처럼 매 행 계산하면 낭비).
        #   못 재는 값은 None(CSV 빈칸) — 0 으로 꾸미면 "진짜 0"과 못 가른다.
        #   ① dip_climax_mult: 저점 직전 1분 거래대금 ÷ 당일 분당 평균.
        #      3~5배↑ = 항복매도 클라이맥스 후보. 중앙값 대신 평균인 이유: 누적대금
        #      두 개만으로 계산돼 분당 이력 상태가 필요 없다(그림자 단계에선 이걸로 충분).
        #   ② dip_book_imb: 저점 순간 최우선호가 대기열 불균형 = 매수잔량/(매수+매도).
        #      0.5 = 균형, 1 에 가까울수록 매수벽 우세(Gould·Bonart 대기열 불균형).
        #   ③ dip_sell_decel_10s: 저점 직전 10초 매도대금 증가분 ÷ 그 앞 10초.
        #      1 미만 = 매도가 저점으로 오며 감속(연쇄 소진). 자료가 성기면 None.
        base60 = self._lookback(low, 60.0)
        climax = None
        total_cum = low.buy_money_cum + low.sell_money_cum
        opened = low.ts.replace(hour=9, minute=0, second=0, microsecond=0)
        elapsed_min = (low.ts - opened).total_seconds() / 60.0
        if base60 is not None and total_cum > 0 and elapsed_min >= 1.0:
            minute_money = total_cum - (
                base60.buy_money_cum + base60.sell_money_cum)
            per_min_avg = total_cum / elapsed_min
            if per_min_avg > 0:
                climax = round(minute_money / per_min_avg, 3)
        book_imb = None
        if low.book_valid:
            book_imb = round(
                low.best_bid_qty / (low.best_bid_qty + low.best_ask_qty), 3)
        sell_decel = None
        p10 = self._lookback(low, 10.0)
        p20 = self._lookback(low, 20.0)
        if p10 is not None and p20 is not None and p20.ts < p10.ts:
            recent = low.sell_money_cum - p10.sell_money_cum
            prior = p10.sell_money_cum - p20.sell_money_cum
            if prior > 0:
                sell_decel = round(recent / prior, 3)
        return {
            "dip_climax_mult": climax,
            "dip_book_imb": book_imb,
            "dip_sell_decel_10s": sell_decel,
        }

    def _row(
        self,
        point: IntradayPoint,
        action: str,
        reason: str,
    ) -> dict[str, Any]:
        state = self.state
        low = state.low_point
        drawdown = (
            (low.price / state.high_price - 1.0) * 100.0
            if low is not None and state.high_price > 0 else 0.0
        )
        rebound = (
            (point.price / low.price - 1.0) * 100.0
            if low is not None and low.price > 0 else 0.0
        )
        spread_bps, microprice_edge_bps = self._book_metrics(point)
        # ★[2026-07-31 친구님 지시 "저점 리셋 매수매도 배수 기록 붙여줘"] 판정에는 안 쓰고
        #   기록만 한다. 저점(low)을 찍은 그 순간의 누적을 기준으로 그 뒤 증가분만 비교 —
        #   당일 누적 비율은 아침부터가 섞여 바닥 순간의 변화를 못 본다.
        #   3거래일쯤 쌓이면 "배수가 높았던 건이 실제로 더 올랐나"로 문턱을 정한다.
        #   S02 의 dip_* 와 같은 이름 규칙(판독 스크립트를 하나로 쓰기 위해).
        dip_meta: dict[str, Any] = {}
        if low is not None:
            d_buy = point.buy_money_cum - low.buy_money_cum
            d_sell = point.sell_money_cum - low.sell_money_cum
            dip_meta = {
                "dip_buy_money_since_low": round(d_buy, 1),
                "dip_sell_money_since_low": round(d_sell, 1),
                "dip_buy_sell_ratio": (round(d_buy / d_sell, 3) if d_sell > 0 else None),
                "dip_flow_obs_sec": round((point.ts - low.ts).total_seconds(), 1),
                "dip_low_reset_steps": state.low_reset_steps,
                "dip_drop_pct": round(drawdown, 3),
            }
            dip_meta.update(state.low_gauges)  # ★[2026-08-06] 계기판 3종(기록만)
        row: dict[str, Any] = {
            "ts": point.ts.isoformat(timespec="milliseconds"),
            "action": action,
            "reason": reason,
            "price": point.price,
            # ★[S03-OPENPRICE-FIX 2026-08-06] 회전엔진 선별기가 이 값으로 진입 가격대를
            #   다시 검산한다(OPEN_HANDOFF -8% ~ OPEN_ARM -4%). 없으면 신호가 통째로 버려진다.
            #   1번 레인(OPEN_CRASH)은 원래 싣고 있었다(골짜기_급반등.py:371) - 2번만 빠져 있었다.
            "open_price": getattr(point, "open_price", 0.0) or 0.0,
            # ★[S03-OPENPRICE-FIX 2026-08-06] 회전엔진이 "신호 낼 때보다 지금 매수세가 더
            #   붙었나"를 이 두 값과 스냅샷을 견줘 판정한다(rotation_engine:151~164).
            #   없으면 -1.0 으로 읽혀 즉시 탈락한다. 1번 레인은 싣고 있었다(골짜기:376~377).
            "current_buy_money_cum": point.buy_money_cum,
            "current_sell_money_cum": point.sell_money_cum,
            "entry_lane": INTRADAY_CRASH_LANE,
            "algorithm": INTRADAY_CRASH_ALGORITHM,
            "mode": SIGNAL_MODE,
            "long_flow_gates_enabled": not FLOW_GATES_OFF,
            "phase": state.phase,
            "intraday_high": state.high_price,
            "intraday_high_ts": (
                state.high_ts.isoformat(timespec="milliseconds")
                if state.high_ts else ""
            ),
            "anchor_low": low.price if low is not None else 0.0,
            "anchor_low_ts": (
                low.ts.isoformat(timespec="milliseconds") if low else ""
            ),
            "intraday_drawdown_pct": round(drawdown, 4),
            "rebound_pct": round(rebound, 4),
            "spread_bps": round(spread_bps, 4),
            "microprice_edge_bps": round(microprice_edge_bps, 4),
        }
        if low is not None:
            buy_volume = point.buy_volume_cum - low.buy_volume_cum
            sell_volume = point.sell_volume_cum - low.sell_volume_cum
            buy_money = point.buy_money_cum - low.buy_money_cum
            sell_money = point.sell_money_cum - low.sell_money_cum
            total_volume = buy_volume + sell_volume
            total_money = buy_money + sell_money
            row.update({
                "low_stable_sec": round(
                    (point.ts - (state.low_updated_at or point.ts)).total_seconds(),
                    2,
                ),
                "flow_observation_sec": round(
                    (point.ts - low.ts).total_seconds(), 2),
                "buy_volume_ratio": round(
                    buy_volume / total_volume if total_volume > 0 else 0.0, 4),
                "buy_money_ratio": round(
                    buy_money / total_money if total_money > 0 else 0.0, 4),
                "entry_money_krw": round(max(0.0, total_money), 2),
                "buy_money_rate_10s": round(self._money_rate(point, 10.0), 2),
                "buy_money_rate_30s": round(self._money_rate(point, 30.0), 2),
            })
        row.update(dip_meta)      # ★[2026-07-31] 저점 리셋 배수·계단 수 기록
        return row

    def feed(
        self,
        point: IntradayPoint,
        *,
        allow_signal: bool,
    ) -> dict[str, Any]:
        reset_reason = self._append(point)
        if reset_reason is not None:
            action = "WAIT" if reset_reason.startswith("DUPLICATE") else "RESET"
            return self._row(point, action, reset_reason)
        if min(
            point.price,
            point.buy_volume_cum,
            point.sell_volume_cum,
            point.buy_money_cum,
            point.sell_money_cum,
        ) < 0:
            return self._row(point, "WAIT", "INVALID_PRICE_OR_FLOW_CONTEXT")
        if not allow_signal:
            return self._row(point, "WAIT", "ENTRY_TIME_CLOSED")
        state = self.state
        if state.emission_count >= self.config.max_signals_per_code:
            return self._row(point, "DONE", "CODE_DAILY_ENTRY_LIMIT_2")

        if state.phase in {"SCAN", "EMITTED", "WAIT_NEW_LOW"}:
            # ★[S03-DAYHIGH-FIX 2026-08-06 친구님 "장중 고점 잘못된 거야 / 당일 고점으로"]
            #   종전: max(state.points) = 10분 창 안의 최대값 → 당일 고점이 아니다.
            #   지금: 그날 내내 갱신한 day_high_price.
            #   자료가 아직 없으면(0) 예전처럼 창 최대값으로 물러선다.
            if state.day_high_price > 0:
                high_price, high_ts = state.day_high_price, state.day_high_ts
            else:
                fallback = max(state.points, key=lambda row: row.price)
                high_price, high_ts = fallback.price, fallback.ts
            drawdown = (point.price / high_price - 1.0) * 100.0
            new_cycle_low = (
                state.last_emitted_low <= 0
                or point.price < state.last_emitted_low
            )
            if drawdown > -self.config.min_drawdown_pct or not new_cycle_low:
                state.phase = "SCAN"
                return self._row(point, "WAIT", "INTRADAY_DRAWDOWN_LT_3PCT")
            # ★[S03-LANE2 2026-08-06] 폐기된 저점보다 낮아져야만 새 사이클 —
            #   "1분 안에 안 튄 저점은 매수 금지"를 지키는 빗장.
            if state.dead_low > 0 and point.price >= state.dead_low:
                state.phase = "SCAN"
                return self._row(point, "WAIT", "DEAD_LOW_REQUIRES_LOWER_LOW")
            state.dead_low = 0.0
            state.phase = "LOW_CONFIRM"
            state.high_price = high_price
            state.high_ts = high_ts
            state.low_point = point
            state.low_updated_at = point.ts
            state.low_reset_steps = 0        # ★새 급락 시작 = 계단 수 초기화
            state.low_gauges = self._compute_low_gauges(point)  # ★계기판(기록만)
            return self._row(point, "ARMED", "INTRADAY_DROP_ARMED")

        low = state.low_point
        if low is None or state.high_price <= 0:
            state.phase = "SCAN"
            return self._row(point, "RESET", "INTRADAY_STATE_INVALID_RESET")
        if point.price < low.price:
            state.low_point = point
            state.low_updated_at = point.ts
            state.low_reset_steps += 1       # ★저점이 한 계단 더 내려감
            state.low_gauges = self._compute_low_gauges(point)  # ★계단마다 다시 잰다
            return self._row(point, "RESET", "INTRADAY_NEW_LOW_RESET")

        elapsed = (point.ts - low.ts).total_seconds()
        rebound = (point.price / low.price - 1.0) * 100.0
        if elapsed > self.config.max_confirm_sec:
            state.phase = "WAIT_NEW_LOW"
            state.dead_low = low.price      # ★[S03-LANE2] 1분 안에 못 튄 저점 = 폐기
            return self._row(point, "WAIT", "INTRADAY_CONFIRM_TIMEOUT")
        if rebound > self.config.max_rebound_pct:
            state.phase = "WAIT_NEW_LOW"
            state.dead_low = low.price      # ★[S03-LANE2] 우리 없이 튄 저점도 폐기
            return self._row(point, "WAIT", "REBOUND_CHASE_LIMIT")
        stable = (point.ts - (state.low_updated_at or point.ts)).total_seconds()
        row = self._row(point, "WAIT", "LOW_OR_REBOUND_CONFIRMING")
        if stable < self.config.low_stable_sec or rebound < self.config.min_rebound_pct:
            return row

        buy_volume = point.buy_volume_cum - low.buy_volume_cum
        sell_volume = point.sell_volume_cum - low.sell_volume_cum
        buy_money = point.buy_money_cum - low.buy_money_cum
        sell_money = point.sell_money_cum - low.sell_money_cum
        if min(buy_volume, sell_volume, buy_money, sell_money) < 0:
            state.phase = "SCAN"
            return self._row(point, "RESET", "EXACT_FLOW_COUNTER_RESET")
        total_volume = buy_volume + sell_volume
        total_money = buy_money + sell_money
        buy_volume_ratio = buy_volume / total_volume if total_volume > 0 else 0.0
        buy_money_ratio = buy_money / total_money if total_money > 0 else 0.0
        buy_rate10 = self._money_rate(point, 10.0)
        buy_rate30 = self._money_rate(point, 30.0)
        spread_bps, microprice_edge_bps = self._book_metrics(point)
        # ★[S03-LANE2 2026-08-06] 매수 방법 공유 관문 — 매도 감속 + 매수 가속 + 매수 우위
        #   (1레인 급행과 동일)가 이 순간 확인돼야만 산다. 닷새 전수 근거는 config 주석 참조.
        if not self._sell_decel_buy_flip(point):
            return self._row(point, "WAIT", "NO_SELL_DECEL_BUY_FLIP")
        # ★[2026-07-31 친구님 지시 "먼저 있던 것은 폐기해야 돼"] 8겹 관문 중
        #   '확인 조건' 5개를 폐기한다(FLOW_GATES_OFF=YES 가 기본).
        #   폐기 대상: 진입대금 1천만원 · 매수체결비중 · 매수대금비중 · 30초 매수흐름 ·
        #             10초/30초 지속성. 남기는 것: 호가 유효성 · 스프레드 · 마이크로프라이스
        #             (이 셋은 '살 수 있느냐'를 보는 체결 가능성 관문이라 성격이 다르다).
        #   근거(7/31 고저폭30 전수·밀림-2%+저점+0.5% = +5.62%/승률93% 기준):
        #     매수비율 55%↑ +2.51% · 65%↑ **-0.95%(승률 50%)**
        #     거래대금 2/3/5배 폭발 +4.80/+4.49/+4.25%
        #     체결강도 100/120/150↑ +4.24/+4.18/**+1.90%(승률 67%)**
        #     → 확인이 확실해질수록 진입가가 높아진다. 매수세가 눈에 보이면 이미 늦다.
        #   ⚠️7/31 은 상한가 13개짜리 상승일 하나뿐 — 하락장 표본이 없다.
        #     이 관문들은 하락장 방어용이므로, 하락장을 겪은 뒤 되살릴지 판단할 것.
        #   되돌리기: setx S03_FLOW_GATES_OFF NO + 신호기 재기동
        #             또는 backup\strategy_03_intraday_rebound_v1_20260731_firstbull.py 복원
        if FLOW_GATES_OFF:
            gates = (
                point.book_valid,
                0 < spread_bps <= self.config.max_spread_bps,
                microprice_edge_bps > 0,
            )
            reasons_map = ("TOP_OF_BOOK_MISSING", "SPREAD_GT_35BPS",
                           "MICROPRICE_EDGE_NOT_POSITIVE")
            if not all(gates):
                idx = gates.index(False)
                return self._row(point, "WAIT", reasons_map[idx])
            gates = (True,) * 8
        else:
            gates = (
                total_money >= self.config.min_entry_money_krw,
                buy_volume_ratio >= self.config.min_buy_volume_ratio,
                buy_money_ratio >= self.config.min_buy_money_ratio,
                buy_rate30 > 0,
                buy_rate10 >= self.config.persistence_fraction * buy_rate30,
                point.book_valid,
                0 < spread_bps <= self.config.max_spread_bps,
                microprice_edge_bps > 0,
            )
        if not all(gates):
            reasons = (
                "ENTRY_MONEY_LT_10M",
                "BUY_VOLUME_RATIO_LT_58",
                "BUY_MONEY_RATIO_LT_58",
                "BUY_MONEY_30S_NOT_READY",
                "BUY_MONEY_PERSISTENCE_WEAK",
                "TOP_OF_BOOK_MISSING",
                "SPREAD_GT_35BPS",
                "MICROPRICE_NOT_UP",
            )
            row["reason"] = next(
                reason for passed, reason in zip(gates, reasons) if not passed)
            return row

        state.emission_count += 1
        state.last_emitted_low = low.price
        state.phase = "EMITTED"
        row = self._row(
            point,
            "BUY_READY",
            "INTRADAY_CRASH+LOW_STABLE+EXACT_SHORT_BUY_DOMINANCE+BOOK_CONFIRM",
        )
        row["anchor_id"] = (
            f"{state.high_ts.isoformat(timespec='seconds') if state.high_ts else ''}:"
            f"{state.high_price:.4f}:"
            f"{low.ts.isoformat(timespec='seconds')}:{low.price:.4f}"
        )
        row["signal_sequence"] = state.emission_count
        return row

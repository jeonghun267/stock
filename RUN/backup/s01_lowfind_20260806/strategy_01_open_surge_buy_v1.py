# -*- coding: utf-8 -*-
"""새전략 01 — 장초반 되돌림 매수조건.

매수 판정만 담당한다. 주문을 제출하지 않으며 상승보유·매도는
strategy_common_hold_sell_v1의 공통 엔진에 위임한다.

★[2026-07-31 친구님 지시 "1번에다 이식해야지 / 먼저 있던거 그냥 지우란 말야"]
  기존 "급상승 초입 추격" 규칙을 폐기하고 "되돌림 진입"으로 교체했다.

  폐기 이유 — 실전 3거래일(7/29~7/31) 19전 2승 17패 **-32.51%**.
    손실의 83%가 하드스톱(11건·평균 -2.47%)이고, 19건 중 7건은 mfe=0
    (산 직후 단 한 번도 플러스가 안 됨) · 8건은 최고점이 왕복비용 0.38% 에도 못 미쳤다.
    ⇒ 매도를 아무리 고쳐도 흑자 불가: 꼭지에서 100% 정확히 팔아도 건당 +0.44%,
      최고점 절반만 확보하면 +0.03% = 0. **진입 자리 자체가 틀렸다.**

  틀린 이유 — 옛 규칙은 시가 밑으로 한 번이라도 내려가면 그날 영구 제외하고
    (LOW_BUY_IS_STRATEGY_02), 살 자리를 시가~시가+3% 띠로 묶었다.
    "안 밀린 놈만 산다" = 결국 밀리기 직전을 산다.
    7/31 실측: 고저폭 30종목 중 21개가 시가 밑으로 내려간 뒤 종일 올랐는데,
    S01 은 그것들을 전부 제외하고 "아직 안 내려간" 6종목을 사서 6전 6패.

  새 규칙 근거
    · 일봉 1년 코스닥 전수(12.6만건·왕복비용 0.38% 차감)
        저가+1% 매수 → 당일종가:  고저폭 밖 +1.251%/58.8%  vs  고저폭 5일↑ +4.343%/81.4%
        시가 매수  → 당일종가:  전체 -0.777%  ·  고저폭 5일↑ **-1.472%**(더 나빠짐)
      ⇒ 저점에서 사야 하고, 그때만 고저폭이 유리하다.
    · 7/31 09시대 분봉 재현: 되돌림 12종목 11승 1패 평균 +8.57%
      (같은 날 옛 규칙 실제 = 0승 6패 -1.60%)
    ⚠️09시대 분봉 검증은 7/31 하루뿐이다. 상한가 13개가 나온 강세일이라 과장 가능성 있음.

  진입창은 09:00~09:20 그대로 둔다 — 7/31 되돌림 12건 중 11건이 09:20 안에 들어와
    공용코어(rotation engine)의 창을 건드릴 이유가 없다.
  돈흐름 5조건(매수비중·속도·연속상승·폭발)은 검증한 적 없어 그대로 유지한다.

  롤백: backup\strategy_01_open_surge_buy_v1_20260731_dipmode.py 복원
        (신호기도 같이 backup\strategy_01_open_surge_signal_v2_20260731_dipmode.py)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum

from strategy_common_foundation_v1 import ContractError, as_decimal, as_kst
from strategy_common_hold_sell_v1 import StrategyId


# ★[2026-08-03 친구님 승인 "-3.0%로 해줘"] 밀림 문턱 -1.5% → -3.0%.
#   근거 — 분당기록 2일(7/31 폭등일·8/3 하락반등일) A/B 재현, 비용 0.35% 차감:
#       밀림 -1.5%(현행)  7/31 +2.30%(7건)  8/3 +2.54%(21건)  합산 +2.48%
#       밀림 -2.0%        7/31 +3.03%(5건)  8/3 +3.79%(15건)  합산 +3.60%
#       밀림 -3.0%(채택)  7/31 +3.04%(3건)  8/3 +3.95%(10건)  합산 +3.74%
#     성격이 반대인 두 날에서 방향이 같았고, 8/1 일봉·분봉 281 종목일 백테의
#     "밀림 깊을수록 좋다 · -1.5%는 너무 얕다"와도 일치한다.
#   재현 신뢰도: 현행값으로 8/3 을 재생하면 실제 신호 21종목과 21/21 일치했다.
#   구조 효과: 반등 문턱(+0.5%)·추격상한(저점+3%)이 그대로라 매수 가격대가
#     통째로 시가 아래로 내려간다(8/1 전수에서 시가 위 첫 눌림은 -3.32%/승률 27%로 최악).
#     09:00~09:01 장세판정 구멍도 좁아진다 — -3% 까지 밀리는 데 시간이 걸려
#     최초 신호가 7/31 09:03:01 · 8/3 09:03:00 이었다.
#   ⚠️분당기록 표본이 2일뿐이고, 신호 건수가 절반으로 줄어 슬롯 6개를 못 채우는
#     날이 생긴다(7/31 은 3건). 실전 로그로 재확인할 것.
#   롤백: setx S01_MIN_DIP_PCT 1.5 (프로세스 재기동 후 적용)
try:
    S01_MIN_DIP_PCT = abs(Decimal((os.environ.get("S01_MIN_DIP_PCT") or "3.0").strip()))
except InvalidOperation:
    S01_MIN_DIP_PCT = Decimal("3.0")


STRATEGY_NUMBER = 1
STRATEGY_ID = StrategyId.S01_OPEN_SURGE
STRATEGY_NAME = "새전략 01 — 장초반 급상승 초입"


class BuyAction(str, Enum):
    WAIT = "WAIT"
    BUY_READY = "BUY_READY"
    BLOCK = "BLOCK"


class EntryRoute(str, Enum):
    OPEN_SURGE = "OPEN_SURGE"
    GAP_SURGE = "GAP_SURGE"


@dataclass(frozen=True)
class OpenSurgeConfig:
    entry_start: time = time(9, 0)
    entry_end: time = time(9, 20)
    min_price: Decimal = Decimal("10000")
    gap_min_pct: Decimal = Decimal("3.0")
    # ★되돌림 3문턱 (2026-07-31 교체)
    min_dip_pct: Decimal = S01_MIN_DIP_PCT       # 당일저점이 시가 대비 이만큼은 밀려야 대상
    min_rebound_pct: Decimal = Decimal("0.5")    # 저점에서 이만큼 되돌아오면 매수
    max_rebound_pct: Decimal = Decimal("3.0")    # 저점에서 이만큼 넘게 올랐으면 추격 금지
    # ★[2026-07-31 친구님 지시 "매수 비중을 60%로 낮춰봐 — 눌림이니까 당연히 매도가
    #   많이 왔을 거고, 눌림 바닥에서 조금 올라서 살 거 아니냐"] 0.70 → 0.60.
    #   되돌림 진입은 방금 판 사람이 많았던 자리라 매수비중이 구조적으로 낮다.
    #   7/31 09시대 실측(고저폭30·가격조건 통과 11종목의 매수비중):
    #     70% 이상  2종목 → 슬롯 6개 중 2자리만 채움 · 평균 +10.24%
    #     60% 이상  6종목 → 슬롯 가득          · 평균  +7.05%(5승1패)
    #     55%/50%   통과만 늘고 슬롯 제한으로 매수 종목은 그대로 → 더 낮출 이유 없음
    #   ⇒ 총액 기준 60% 가 3배 이상. 60% 가 슬롯을 채우는 최소 지점이다.
    #   ⚠️하루 표본이고, 실측에 쓴 값은 그림자 CSV 의 매수비율(누적)이라 이 엔진이
    #     보는 '최근 10초 순간값'과 계산이 다르다 — 월요일 로그로 재확인할 것.
    #   롤백: backup\strategy_01_open_surge_buy_v1_20260731_dipmode.py 복원
    min_buy_money_ratio: Decimal = Decimal("0.60")
    min_money_speed_5s: Decimal = Decimal("1666667")
    min_burst_ratio: Decimal = Decimal("3.0")
    burst_waive_sec: int = 30
    min_flow_observation_sec: int = 5
    min_price_rising_sec: int = 3


@dataclass(frozen=True)
class OpenSurgeObservation:
    observed_at: datetime
    code: str
    previous_close: Decimal
    open_price: Decimal
    current_price: Decimal
    high_so_far: Decimal
    buy_money_ratio: Decimal
    money_speed_5s: Decimal
    money_speed_30s: Decimal
    price_rising_sec: int
    exact_flow: bool
    in_prior_value_pool: bool
    in_premarket_gap_pool: bool
    # ★[2026-07-31] 당일 저점(09:00 이후 관측 최저가). 되돌림 판정의 기준점.
    #   0 이면 아직 자료가 없다는 뜻 → 판정 보류(WAIT).
    low_so_far: Decimal = Decimal("0")
    flow_observation_sec: Decimal = Decimal("5")
    is_kosdaq: bool = True
    is_ordinary_share: bool = True
    below_open_seen: bool = False
    theme_leader: bool = False


@dataclass(frozen=True)
class BuyDecision:
    action: BuyAction
    reason: str
    strategy_id: StrategyId = STRATEGY_ID
    route: EntryRoute | None = None
    gap_pct: Decimal = Decimal("0")
    priority_bonus: int = 0


def _decision(
    action: BuyAction,
    reason: str,
    *,
    route: EntryRoute | None = None,
    gap_pct: Decimal = Decimal("0"),
    theme_leader: bool = False,
) -> BuyDecision:
    return BuyDecision(
        action=action,
        reason=reason,
        route=route,
        gap_pct=gap_pct,
        priority_bonus=1 if theme_leader else 0,
    )


def _validated_prices(
    observation: OpenSurgeObservation,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    previous = as_decimal(observation.previous_close)
    opening = as_decimal(observation.open_price)
    current = as_decimal(observation.current_price)
    high = as_decimal(observation.high_so_far)
    if min(previous, opening, current, high) <= 0:
        raise ContractError("Open-surge prices must be positive")
    if high < current:
        raise ContractError("high_so_far cannot be below current_price")
    return previous, opening, current, high


def _flow_block_reason(
    observation: OpenSurgeObservation,
    config: OpenSurgeConfig,
    open_elapsed_sec: float,
) -> str:
    buy_ratio = as_decimal(observation.buy_money_ratio)
    speed_5s = as_decimal(observation.money_speed_5s)
    flow_observation_sec = as_decimal(observation.flow_observation_sec)
    if flow_observation_sec < config.min_flow_observation_sec:
        return "FLOW_WINDOW_WARMING_UP"
    speed_30s = as_decimal(observation.money_speed_30s)
    if not observation.exact_flow:
        return "EXACT_FLOW_MISSING"
    if buy_ratio < config.min_buy_money_ratio:
        return "BUY_MONEY_RATIO_WEAK"
    if speed_5s < config.min_money_speed_5s:
        return "MONEY_SPEED_WEAK"
    if observation.price_rising_sec < config.min_price_rising_sec:
        return "PRICE_RISE_NOT_PERSISTENT"
    if open_elapsed_sec >= config.burst_waive_sec:
        if speed_30s <= 0 or speed_5s / speed_30s < config.min_burst_ratio:
            return "MONEY_BURST_WEAK"
    return ""


class OpenSurgeBuyStrategy:
    # Strategy 01 live monitor uses two one-share entry stages.
    staged_entries = True

    def __init__(self, config: OpenSurgeConfig | None = None) -> None:
        self.config = config or OpenSurgeConfig()

    def evaluate(self, observation: OpenSurgeObservation) -> BuyDecision:
        observed_at = as_kst(observation.observed_at)
        current_time = observed_at.time().replace(tzinfo=None)
        if not self.config.entry_start <= current_time < self.config.entry_end:
            return _decision(BuyAction.BLOCK, "OUTSIDE_ENTRY_WINDOW")
        if not observation.is_kosdaq or not observation.is_ordinary_share:
            return _decision(BuyAction.BLOCK, "UNIVERSE_BLOCK")

        previous, opening, current, high = _validated_prices(observation)
        gap_pct = (opening / previous - Decimal("1")) * Decimal("100")
        route = (
            EntryRoute.GAP_SURGE
            if gap_pct >= self.config.gap_min_pct
            else EntryRoute.OPEN_SURGE
        )
        candidate = (
            observation.in_prior_value_pool
            or observation.in_premarket_gap_pool
            or route is EntryRoute.GAP_SURGE
        )
        if not candidate:
            return _decision(BuyAction.BLOCK, "NOT_IN_OPENING_POOL", gap_pct=gap_pct)
        if current < self.config.min_price:
            return _decision(BuyAction.BLOCK, "PRICE_BELOW_10000", gap_pct=gap_pct)

        # ── 되돌림 판정 (2026-07-31 교체·머리말 참조) ────────────────────────
        # 옛 규칙(시가 밑 내려가면 영구 제외 + 시가~시가+3% 띠에서만 매수)은
        # 3일 -32.51% 로 폐기했다. 이제 기준점은 시가가 아니라 '당일 저점'이다.
        low = as_decimal(observation.low_so_far)
        if low <= 0:
            return _decision(BuyAction.WAIT, "DAY_LOW_NOT_READY", route=route, gap_pct=gap_pct)

        dip_pct = (low / opening - Decimal("1")) * Decimal("100")
        if dip_pct > -self.config.min_dip_pct:
            # 아직 충분히 안 밀렸다. 제외가 아니라 '때가 아님' — 밀리면 다시 본다.
            return _decision(BuyAction.WAIT, "DIP_NOT_DEEP_ENOUGH", route=route, gap_pct=gap_pct)

        rebound_pct = (current / low - Decimal("1")) * Decimal("100")
        if rebound_pct < self.config.min_rebound_pct:
            return _decision(BuyAction.WAIT, "REBOUND_NOT_CONFIRMED", route=route, gap_pct=gap_pct)
        if rebound_pct > self.config.max_rebound_pct:
            # 저점에서 이미 멀어졌다 = 추격. 옛 CHASE_ABOVE_OPEN_3PCT 의 자리.
            return _decision(BuyAction.BLOCK, "CHASE_ABOVE_LOW_3PCT", gap_pct=gap_pct)

        open_at = observed_at.replace(hour=9, minute=0, second=0, microsecond=0)
        flow_reason = _flow_block_reason(
            observation,
            self.config,
            (observed_at - open_at).total_seconds(),
        )
        if flow_reason:
            return _decision(
                BuyAction.WAIT, flow_reason, route=route, gap_pct=gap_pct
            )
        return _decision(
            BuyAction.BUY_READY,
            "DIP_REBOUND_CONFIRMED",
            route=route,
            gap_pct=gap_pct,
            theme_leader=observation.theme_leader,
        )


def strategy_label() -> str:
    return f"S-{STRATEGY_NUMBER:02d} {STRATEGY_NAME}"

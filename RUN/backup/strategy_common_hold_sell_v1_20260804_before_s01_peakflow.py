# -*- coding: utf-8 -*-
"""Common rising-hold and sell decision engine.

This module has no broker connection and never submits an order. Independent
entry strategies share one ordered decision engine while their proven
differences are kept in immutable strategy profiles.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from strategy_common_foundation_v1 import (
    ContractError,
    OrderIntent,
    OrderSide,
    as_decimal,
    as_kst,
    normalize_code,
)


STATE_SCHEMA = "strategy_common_hold_sell_v1"


class StrategyId(str, Enum):
    S01_OPEN_SURGE = "S01_OPEN_SURGE"
    S02_LOW_BUY_SELL_EXHAUSTION = "S02_LOW_BUY_SELL_EXHAUSTION"
    S04_PULLBACK = "S04_PULLBACK"
    S05_BASE_BREAKOUT = "S05_BASE_BREAKOUT"
    EARLY_DIRECT_ONSET = "EARLY_DIRECT_ONSET"
    EARLY_GAP_ONSET = "EARLY_GAP_ONSET"
    EARLY_DIP_RECLAIM = "EARLY_DIP_RECLAIM"
    RAID = "RAID"
    PULL = "PULL"
    BASE = "BASE"
    REACCEL = "REACCEL"
    VALLEY = "VALLEY"
    VALLEY_MORNING_CRASH = "VALLEY_MORNING_CRASH"
    VALLEY_BASE_BREAKOUT = "VALLEY_BASE_BREAKOUT"


class HoldSellAction(str, Enum):
    HOLD = "HOLD"
    WATCH = "WATCH"
    SELL = "SELL"
    EMERGENCY_SELL = "EMERGENCY_SELL"


class HoldPhase(str, Enum):
    HOLD = "HOLD"
    WATCH = "WATCH"


class PeakStage(str, Enum):
    UNARMED = "UNARMED"
    PROFIT_2 = "PROFIT_2"
    PROFIT_4 = "PROFIT_4"
    PROFIT_7 = "PROFIT_7"


class MA3Mode(str, Enum):
    NONE = "NONE"
    HOLD_LOCK = "HOLD_LOCK"
    SELL_OVERRIDE = "SELL_OVERRIDE"


class ExitPolicy(str, Enum):
    STANDARD = "STANDARD"
    TREND_REBOUND = "TREND_REBOUND"
    VALLEY = "VALLEY"
    VALLEY_MORNING_CRASH = "VALLEY_MORNING_CRASH"
    VALLEY_BASE_BREAKOUT = "VALLEY_BASE_BREAKOUT"


EARLY_STRATEGIES = {
    StrategyId.EARLY_DIRECT_ONSET,
    StrategyId.EARLY_GAP_ONSET,
    StrategyId.EARLY_DIP_RECLAIM,
}


@dataclass(frozen=True)
class StrategyExitProfile:
    strategy_id: StrategyId
    hard_stop_pct: Decimal
    strong_flow_hard_stop_pct: Decimal
    force_exit_at: time
    early_decision_at: Optional[time]
    ma3_mode: MA3Mode
    score_min_hold_sec: int
    exit_policy: ExitPolicy
    peak_insure_pct: Optional[Decimal]
    target_profit_pct: Optional[Decimal]
    flow_reversal_exit_enabled: bool = False
    # ★[2026-07-31 친구님 지시 "1번만 D로 바꿔줘"] 전략별 트레일 계단 덮어쓰기.
    #   None 이면 공용값(HoldSellConfig.trail_steps)을 그대로 쓴다 → 다른 전략 무영향.
    trail_steps: Optional[tuple] = None
    # ★[RIDER-ORDER 2026-08-03 친구님 지시] 상승보유를 트레일보다 앞에 둘지 (전략별).
    #   False(기본) 면 종전 순서 그대로 → 다른 전략 무영향.
    #   왜 필요한가: 7/29 에 트레일을 상승보유 앞에 뒀는데(그때는 이익실현 장치가
    #   아예 없어 전부 하드손절로 끝났기 때문), 그 뒤로 상승보유는 한 번도 도달하지
    #   못했다. 8/3 실측(2번 3건): 현행 +2.60% vs 상승보유 우선 +9.28%.
    #   코스모로보틱스(정배열·20선 우상향)는 +1.65% -> +10.28%, 티씨케이(5<10일선)는
    #   조건 미충족이라 트레일이 그대로 작동해 영향 없음 = 선별적으로 듣는다.
    #   ⚠️표본 3건이다. 그래서 2번에만 켠다.
    rider_before_trail: bool = False
    # ★[STOP-LADDER 2026-08-03 친구님 지시] 손절선 끌어올리기 계단 (전략별).
    #   ((고점수익률 문턱, 그때의 손절선), ...) — 넘을 때마다 손절선이 위로만 이동한다.
    #   None(기본)이면 종전 고정 손절 그대로 → 다른 전략 무영향.
    stop_ladder: Optional[tuple] = None
    # ★[TRAIL-FLOW 2026-08-03 친구님 지시] 트레일을 가격만으로 발동시키지 않는다.
    #   친구님 설계: "1분봉 양봉이면 계속 올라간다 → 보유. 음봉일 때만 수급을 보고,
    #   매수가 많거나 같으면 보유. 매도세가 강할 때만 -1% 에서 판다."
    #   왜: 종전 트레일은 가격만 보고 3분에 한 번 판정했다. 정상 호흡에도 잘리고,
    #   반대로 그 3분 사이에 얼마든지 추락할 수 있다(친구님 지적).
    #   구조는 5번 BASE_FAILURE_EXIT 를 그대로 본떴다 — 이미 만들어 검증된 형태다.
    #   True 면 트레일 문턱 도달 + 1분봉 음봉 + 수급 3종 전부 매도 우위일 때만 판다.
    trail_needs_sell_pressure: bool = False
    # 트레일 판정 주기 덮어쓰기(초). None 이면 공용값(180초).
    trail_eval_interval_sec: Optional[int] = None

    def stop_pct(self, buy_ratio_recent: Decimal) -> Decimal:
        if buy_ratio_recent > Decimal("0.50"):
            return self.strong_flow_hard_stop_pct
        return self.hard_stop_pct


# ★[2026-07-29 친구님 지시] 공통 하드손절 기본값 -2.0% → -3.0%.
#   사유: -2%가 정상 눌림에서 잘려나갔다(7/29 S01 실전 6건 전부 하드손절·익절 0건).
#   14거래일 검증(트레일 현행 포함·비용 0.38% 차감):
#     -2.0% → -0.292% / 승률 47.2% / 손절발생 271건
#     -3.0% → -0.226% / 승률 54.3% / 손절발생 187건   ← 채택
#     -4.0% → -0.141% / 승률 59.0%  (성과는 최고이나 건당 손실이 2배가 되어 -3.0% 선택)
#   함께 검증했으나 채택하지 않은 것:
#     · ATR 기반 동적 손절 — 일봉ATR 중앙값 5.18%라 대부분 상한에 몰려 고정폭과 결과 동일
#     · 최대보유시간 제한 — 짧게 자를수록 악화(트레일이 이미 조기 정리, 시간제한은 15건만 발동)
#     · 익절 목표(target_profit) — 승률은 오르나 총수익 감소
#   적용 범위: stop 을 명시하지 않은 전략(S01·S02·S04·S05 등). S03(-2.5)·PULL(-3.0)은 무관.
#   되돌리기: strategy_common_hold_sell_v1.py.bak_20260729_sellwiring 복원.
def _profile(
    strategy_id: StrategyId,
    *,
    stop: str = "-3.0",
    strong_stop: Optional[str] = None,
    force: time = time(15, 10),
    early: Optional[time] = None,
    ma3: MA3Mode = MA3Mode.NONE,
    score_min_hold_sec: int = 60,
    exit_policy: ExitPolicy = ExitPolicy.STANDARD,
    peak_insure: Optional[str] = None,
    target_profit: Optional[str] = None,
    flow_reversal_exit: bool = False,
    trail_steps: Optional[tuple] = None,
    rider_before_trail: bool = False,
    stop_ladder: Optional[tuple] = None,
    trail_needs_sell_pressure: bool = False,
    trail_eval_interval_sec: Optional[int] = None,
) -> StrategyExitProfile:
    return StrategyExitProfile(
        strategy_id=strategy_id,
        hard_stop_pct=Decimal(stop),
        strong_flow_hard_stop_pct=Decimal(strong_stop or stop),
        force_exit_at=force,
        early_decision_at=early,
        ma3_mode=ma3,
        score_min_hold_sec=score_min_hold_sec,
        exit_policy=exit_policy,
        peak_insure_pct=Decimal(peak_insure) if peak_insure is not None else None,
        target_profit_pct=Decimal(target_profit) if target_profit is not None else None,
        flow_reversal_exit_enabled=flow_reversal_exit,
        trail_steps=trail_steps,
        rider_before_trail=rider_before_trail,
        stop_ladder=stop_ladder,
        trail_needs_sell_pressure=trail_needs_sell_pressure,
        trail_eval_interval_sec=trail_eval_interval_sec,
    )


STRATEGY_PROFILES: Mapping[StrategyId, StrategyExitProfile] = {
    strategy: _profile(
        strategy,
        force=time(9, 30),
        early=time(9, 20),
    )
    for strategy in EARLY_STRATEGIES
}
STRATEGY_PROFILES = {
    **STRATEGY_PROFILES,
    # ★[2026-07-29 친구님 지시] 조기추세 이탈을 S01~S05 전부에 적용한다.
    #   지금까지 early=None 이라 _early_trend_rule 이 통과만 하고 한 번도 안 탔다.
    #   원래 캡틴2 초입레인(EARLY_*) 3종 전용이었고, 새 체계로 넘어오며 연결되지 않았다.
    #   (2026-07-27 에 끈 목록은 트레일·돈마름·점수매도·구조붕괴이며 조기추세는 그 목록에 없다)
    #   시각은 각 전략의 진입창 시작에 맞춘다. 그 이후 진입분은 진입 즉시 판정 대상이 되는데,
    #   전 전략이 15:10 청산의 한 시간 안팎 단타라 추세가 무너지면 바로 나오는 것이 맞다.
    #   판정 항목: VWAP 이탈 · 매수비율 저하 · 자금속도 저하 (MA3·구조붕괴·매도점수는 제외)
    # ★[2026-07-31 친구님 지시 "1번만 D로 바꿔줘"] S01 전용 트레일 계단.
    #   공용값 (1%→1%, 3%→1.5%, 6%→2%) 은 09시대 되돌림에 비해 너무 좁다.
    #   7/31 실측(고저폭30 종목의 고점 갱신 사이 되돌림):
    #       09:00~09:20  중앙값 1.64% · 70분위 2.66% · 90분위 4.11%
    #       09:30~14:20  중앙값 0.72% · 70분위 1.37% · 90분위 2.87%   ← 아침이 2.3배 거칠다
    #     ⇒ 공용 1.0% 트레일은 09시대 정상 되돌림의 65% 를 잘라낸다(34.6% 만 버팀).
    #   더 심각한 건 1단계가 본전 이하라는 것 — 최고 +1% 에서 고점 대비 -1% 면
    #     매도가가 매수가보다 낮다(10,100 × 0.99 = 9,999). 실전 PROFIT_TRAIL 7건이
    #     전부 마이너스(평균 -0.625%·최고 평균 +1.515%)였던 이유다.
    #   7/31 되돌림 매수 6종목에 매도규칙을 적용한 비교:
    #       공용 트레일  +2.12% (5승1패)   ※그냥 들고 있었으면 +7.05% — 70% 를 반납
    #       D안         +4.92% (6승0패)   ← 채택
    #       트레일 없음  +6.34% (5승1패)  ※마키나락스에서 -3.5% 를 맞아 D보다 위험
    #   D = 최고 +5% 찍어야 트레일 시작(고점 -3%), +10% 부터는 고점 -5%.
    #     +5% 전에는 트레일이 없고 하드손절 -3% 와 15:10 청산만 작동한다.
    #   ⚠️하루 표본이다. S02·S05 는 되돌림이 절반이라 공용값을 그대로 두고,
    #     고저폭 30 으로 좁힌 기록이 3거래일 쌓이면 같은 방식으로 재서 판단한다.
    #   롤백: backup\strategy_common_hold_sell_v1_20260731_s01trail.py 복원
    # ★[2026-08-03 저녁 친구님 지시 "조기추세 삭제해 / 상승보유는 트레일 앞으로"]
    #   S01 에서 조기추세 판정(early)을 없애고, 상승보유를 트레일보다 앞에 둔다.
    #   왜 — 조기추세는 09:20(진입창이 닫히는 시각)에 09:00~09:20 매수분 전체를
    #     한꺼번에 판정대에 올리고, VWAP 이탈·매수비율<52% 중 하나만 걸리면
    #     유예 없이 한 틱에 전량매도(래치)했다.
    #   실전 증거: 7/31 09:20:04 씨젠 "EARLY_TREND_EXIT VWAP,FLOW" 실제 체결(mfe=0.000%).
    #   재현(실제 매도엔진 호출·분당기록·밀림 -3.0% 매수·비용 0.35% 차감):
    #       8/3  10종목  현행 +0.70%(5승5패)  ->  조기추세 삭제 +3.47%(8승2패)
    #       7/31  3종목  현행 +0.96%          ->  조기추세 삭제 +2.27%
    #     8/3 는 10건 중 8건이 이 사유였고 7건이 09:20~09:24 에 몰렸다.
    #     최악은 로보티즈 — 09:20 +5.30% 로 잘렸고 그 종목은 13:10 +18.85% 까지 갔다.
    #   ⚠️정직 고지: rider_before_trail 은 재현상 효과가 0 이었다(6가지 조합 전부
    #     동일 결과). 상승보유가 성립하는 시점과 트레일이 자르는 시점이 어긋난다 —
    #     트레일은 고점 대비 -3% 되돌린 뒤에 발동하고, 그때는 선 지지·매수세도
    #     이미 꺾여 있어 상승보유가 참이 되지 않는다. 지시대로 배선만 해 두고,
    #     실효는 실전 로그로 확인한다.
    #   롤백: backup\strategy_common_hold_sell_v1_20260803_s01noearly.py 복원
    StrategyId.S01_OPEN_SURGE: _profile(
        StrategyId.S01_OPEN_SURGE,
        early=None,                 # 조기추세 삭제(종전 time(9, 20))
        rider_before_trail=True,    # 상승보유를 트레일 앞으로
        trail_steps=((Decimal("5"), Decimal("3")), (Decimal("10"), Decimal("5"))),
    ),
    StrategyId.S02_LOW_BUY_SELL_EXHAUSTION: _profile(
        StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
        # S02는 09:06~14:20 동안 신규 진입하므로 벽시계 09:30 조기판정을 쓰지 않는다.
        # -2%는 최종 보험으로 유지하고, 그 전의 확정 매도세 역전은 공통 규칙에서 판정한다.
        early=None,
        stop="-2.0",
        strong_stop="-2.0",
        flow_reversal_exit=True,
        # ★[RIDER-ORDER 2026-08-03] 2번만 상승보유를 트레일 앞에 둔다(위 필드 주석 참조).
        rider_before_trail=True,
        # ★[TRAIL-FLOW 2026-08-03 친구님 지시] 트레일에 수급 방향 확인을 붙이고
        #   판정 주기를 180초 -> 50초로 조인다("3분이면 그 사이 끝없이 추락한다").
        trail_needs_sell_pressure=True,
        trail_eval_interval_sec=50,
        # ★[STOP-LADDER 2026-08-03 철회] 손절선 끌어올리기는 넣었다가 지웠다.
        #   친구님 지적: "+2% 갔다가 본전만 찍어도 다 매도된다" — 장중 2% 오르내림은
        #   정상 호흡이라 승자를 본전에서 잘라낸다. 상승보유로 오래 들고 가자는
        #   같은 날 결정과 자기모순이다. stop_ladder 는 설정하지 않는다(=None, 고정 손절).
    ),
    StrategyId.S04_PULLBACK: _profile(
        StrategyId.S04_PULLBACK,
        early=time(10, 0),          # 진입창 10:00~ 시작
    ),
    StrategyId.S05_BASE_BREAKOUT: _profile(
        StrategyId.S05_BASE_BREAKOUT,
        ma3=MA3Mode.SELL_OVERRIDE,
        early=None,          # 진입창 09:30~14:30 시작
    ),
    StrategyId.RAID: _profile(StrategyId.RAID, ma3=MA3Mode.HOLD_LOCK),
    StrategyId.PULL: _profile(
        StrategyId.PULL,
        stop="-3.0",
        strong_stop="-4.0",
        ma3=MA3Mode.SELL_OVERRIDE,
        score_min_hold_sec=30,
    ),
    StrategyId.BASE: _profile(StrategyId.BASE, ma3=MA3Mode.SELL_OVERRIDE),
    StrategyId.REACCEL: _profile(StrategyId.REACCEL),
    StrategyId.VALLEY: _profile(
        StrategyId.VALLEY,
        stop="-2.5",
        exit_policy=ExitPolicy.VALLEY,
        peak_insure="-1.5",
    ),
    # ★[2026-07-29 친구님 지시] S03 하드손절 -2.0% → -1.0%.
    #   "골짜기 급반등은 한번에 치솟아 오르고 짧은 시간에 끝난다.
    #    -2%라고 하면 급반등에서는 그냥 1%를 버리는 것과 같다."
    #   급반등은 진입 후 곧바로 오르지 않으면 틀린 신호이므로 빨리 끊고 다음 기회를 본다.
    #   (force=09:30 은 Strategy03HoldSellEngine 이 15:10 으로 덮어쓴다)
    StrategyId.VALLEY_MORNING_CRASH: _profile(
        StrategyId.VALLEY_MORNING_CRASH,
        stop="-1.0",
        force=time(9, 30),
        exit_policy=ExitPolicy.VALLEY_MORNING_CRASH,
    ),
    StrategyId.VALLEY_BASE_BREAKOUT: _profile(
        StrategyId.VALLEY_BASE_BREAKOUT,
        stop="-1.5",
        exit_policy=ExitPolicy.VALLEY_BASE_BREAKOUT,
        target_profit="2.0",
    ),
}

STANDARD_STRATEGIES = frozenset(set(StrategyId) - {
    StrategyId.VALLEY,
    StrategyId.VALLEY_MORNING_CRASH,
    StrategyId.VALLEY_BASE_BREAKOUT,
})
VALLEY_STRATEGIES = frozenset(set(StrategyId) - set(STANDARD_STRATEGIES))



@dataclass(frozen=True)
class HoldSellConfig:
    watch_buy_ratio: Decimal = Decimal("0.52")
    sell_buy_ratio: Decimal = Decimal("0.48")
    watch_confirm_sec: int = 2
    sell_confirm_sec: int = 15
    ma_permit_confirm_mult: Decimal = Decimal("2.0")
    # ★[2026-07-29 친구님 지시] 꼭지점 매도 되살림. 발동선 2.0→1.0 · 하락폭 1.5→1.0.
    #   사유: 하드손절 -2%와 15:10 청산만 남아 이익 실현 장치가 아예 없었다.
    #   7/29 S01 실전 6건이 전부 하드손절(익절 0건)로 끝났다.
    #   14거래일 검증: 현재(-0.568%/승률18.5%) → 발동1.0·-1.0(+0.089%/승률47.2%).
    #   원래값(2.0/1.5)은 발동선이 높아 그날 최고수익 +1.44%·+1.78% 건도 발동 못 했다.
    #   하락폭은 친구님 지시로 -1.0% 채택(검증상 -0.7%와 성과 차이 0.01%p).
    #   되돌리기: strategy_common_hold_sell_v1.py.bak_20260729_sellwiring 복원.
    trail_steps: tuple[tuple[Decimal, Decimal], ...] = (
        (Decimal("1.0"), Decimal("1.0")),
        (Decimal("3.0"), Decimal("1.5")),
        (Decimal("6.0"), Decimal("2.0")),
    )
    # ★[2026-07-30 친구님 지시] 꼭지점 매도 판정 주기 1초→180초. 전 전략 공통 적용.
    #   사유: 7/30 S01 6건이 전부 매도 후 15분 내 상승(from_exit 6/6 플러스).
    #   3건은 고점 1.08~1.23%에서 곧바로 되돌림 1.0%에 걸렸다(1초 단위 진동에 반응).
    #   14거래일 검증: S01 +0.395%p · S02 +0.354%p · S03 +0.473%p.
    #   ⚠ S05(장중 베이스 돌파)는 검증에서 악화 — 친구님이 알고 공통 적용을 지시했다.
    #   S03(골짜기)은 exit_policy가 STANDARD가 아니라 이 규칙을 타지 않는다.
    #   문턱 숫자(trail_steps)는 건드리지 않는다 — 7/29 검증에서 현재값이 최선이었다.
    #   되돌리기: RUN\backup\strategy_common_hold_sell_v1_20260730_trailinterval.py 복원.
    # ★[TRAIL-INTERVAL 2026-08-03 친구님 지시] 180초 -> 60초 (전 전략 공용).
    #   "3분은 죽음의 계곡이다" — 3분에 한 번만 보면 그 사이 얼마가 빠지든 방치된다.
    #   트레일은 고점 대비 하락을 재는 규칙인데, 판정을 3분 쉬면 그 하락을 못 본다.
    #   ⚠️옛 검증(7/30)은 "주기를 1초->3~5분으로 늘리면 S01~S03 +0.35~0.47%p 유리"
    #     였다. 다만 그건 트레일이 '가격만' 보던 시절의 결과다. 지금은 S02 에 수급
    #     방향 확인이 붙어 함부로 안 팔리므로 전제가 달라졌다.
    #   되돌리기: 이 값을 180 으로.
    trail_eval_interval_sec: int = 60
    trail_guard_buy_ratio: Decimal = Decimal("0.90")
    flow_reversal_confirm_sec: int = 3
    # ★[MA5-AUX 2026-08-03 친구님 지시] "5일선은 매도 수단이 아니라 보조 수단".
    #   종전: daily_ma5_broken 이 AND 조건이라, 5일선 위에 있는 종목은 꼭지를 쳐도
    #   절대 못 팔았다(8/3 실측: 코스모로보틱스 주가 17,580 vs 5일선 14,714 = 25% 위.
    #   5일선까지 -16.3% 떨어져야 성립 → 꼭지 매도가 아니라 뒷북 매도).
    #   지금: 5일선을 관문에서 빼고 '민감도 조절'로만 쓴다.
    #     5일선 위(추세 살아있음) → 종전대로 엄격 (배수 1.5 · 확인 3초)
    #     5일선 아래(추세 꺾임)   → 완화 (배수 ×0.8 = 1.2 · 확인 1초)
    #   이 규칙은 flow_reversal_exit=True 인 S02 에만 걸린다(타 전략 무영향).
    flow_reversal_below_ma5_mult_scale: Decimal = Decimal("0.8")
    flow_reversal_below_ma5_confirm_sec: int = 1
    flow_reversal_sell_money_mult: Decimal = Decimal("1.5")
    flow_reversal_sell_volume_mult: Decimal = Decimal("1.5")
    flow_reversal_volume_accel_mult: Decimal = Decimal("1.5")
    flow_reversal_max_che_str: Decimal = Decimal("95")
    flow_reversal_min_che_drop: Decimal = Decimal("5")
    persistence_speed_fraction: Decimal = Decimal("0.50")
    dryup_fraction: Decimal = Decimal("0.20")
    dryup_confirm_sec: int = 60
    dryup_min_hold_sec: int = 60
    dryup_min_peak_money_per_sec: Decimal = Decimal("1000000")
    score_sell_enabled: bool = True
    score_sell_ready: Decimal = Decimal("75")
    score_confirm_sec: int = 5
    score_peak_min_money_per_sec: Decimal = Decimal("1000000")
    early_trend_min_buy_ratio: Decimal = Decimal("0.52")
    early_trend_speed_fraction: Decimal = Decimal("0.50")
    vwap_warn_exit_enabled: bool = True

    valley_watch_sec: int = 10
    valley_sell_score_threshold: int = 3
    valley_weak_ma_score_threshold: int = 2
    valley_morning_confirm_sec: int = 10

    def __post_init__(self) -> None:
        ratios = (
            self.watch_buy_ratio,
            self.sell_buy_ratio,
            self.trail_guard_buy_ratio,
            self.persistence_speed_fraction,
            self.dryup_fraction,
            self.early_trend_min_buy_ratio,
            self.early_trend_speed_fraction,
        )
        if any(value < 0 or value > 1 for value in ratios):
            raise ContractError("ratio configuration must be in [0, 1]")
        if self.sell_buy_ratio > self.watch_buy_ratio:
            raise ContractError("sell ratio must not exceed watch ratio")
        if not self.trail_steps:
            raise ContractError("at least one trail step is required")
        if self.trail_eval_interval_sec < 0:
            raise ContractError("trail_eval_interval_sec must not be negative")

        if self.valley_watch_sec <= 0 or self.valley_morning_confirm_sec <= 0:
            raise ContractError("Valley confirmation seconds must be positive")
        if not 1 <= self.valley_weak_ma_score_threshold <= self.valley_sell_score_threshold <= 4:
            raise ContractError("Valley sell score thresholds must be in [1, 4]")

@dataclass(frozen=True)
class HoldSellObservation:
    observed_at: datetime
    price: Decimal
    vwap: Decimal = Decimal("0")
    buy_ratio_recent: Decimal = Decimal("0.60")
    money_speed_5s: Decimal = Decimal("0")
    money_speed_10s: Decimal = Decimal("0")
    money_speed_30s: Decimal = Decimal("0")
    buy_money_per_sec_10s: Decimal = Decimal("0")
    sell_money_per_sec_10s: Decimal = Decimal("0")
    buy_money_per_sec_30s: Decimal = Decimal("0")
    sell_money_per_sec_30s: Decimal = Decimal("0")
    structure_broken: bool = False
    money_accelerating: bool = False
    ma3_permit: bool = False
    daily_ma_permit: bool = False
    daily_ma5_broken: bool = False
    recent_buy_money_rising: bool = False
    buy_volume_per_sec_5s: Decimal = Decimal("0")
    sell_volume_per_sec_5s: Decimal = Decimal("0")
    sell_volume_per_sec_previous_10s: Decimal = Decimal("0")
    che_str: Decimal = Decimal("0")
    che_str_change_5s: Decimal = Decimal("0")
    one_minute_bull_to_bear: bool = False
    # ★[TRAIL-FLOW 2026-08-03 친구님 지시] 진행 중 1분봉이 음봉인가(종가<시가).
    #   one_minute_bull_to_bear 는 "직전봉 양봉 -> 현재봉 음봉" 전환만 잡아서,
    #   연속 음봉으로 계속 흘러내릴 때 신호가 꺼진다(= 떨어지는데 못 판다).
    #   꼭지 판정에는 전환이 아니라 "지금 음봉인가"가 필요하다.
    one_minute_bearish: bool = False
    ma10_support: bool = False
    ma20_rising: bool = False

    valley_completed_bearish_1m: bool = False
    valley_strength_falling: bool = False
    valley_buy_flow_falling: bool = False
    valley_sell_flow_rising: bool = False
    valley_peak_reclaim_failed: bool = False
    valley_peak_reclaimed: bool = False
    valley_ma5_reclaimed_then_lost: bool = False
    valley_ma10_reclaimed_then_lost: bool = False
    valley_exact_flow_valid: bool = False
    valley_exact_sell_dominant: bool = False
    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_kst(self.observed_at))
        decimal_fields = (
            "price",
            "vwap",
            "buy_ratio_recent",
            "money_speed_5s",
            "money_speed_10s",
            "money_speed_30s",
            "buy_money_per_sec_10s",
            "sell_money_per_sec_10s",
            "buy_money_per_sec_30s",
            "sell_money_per_sec_30s",
            "buy_volume_per_sec_5s",
            "sell_volume_per_sec_5s",
            "sell_volume_per_sec_previous_10s",
            "che_str",
        )
        for name in decimal_fields:
            value = as_decimal(getattr(self, name))
            if value < 0 or (name == "price" and value <= 0):
                raise ContractError(f"{name} must be non-negative and price positive")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "che_str_change_5s", as_decimal(self.che_str_change_5s))
        if self.buy_ratio_recent > 1:
            raise ContractError("buy_ratio_recent must be in [0, 1]")

    @property
    def money_per_sec_30s(self) -> Decimal:
        return self.buy_money_per_sec_30s + self.sell_money_per_sec_30s

    @property
    def buy_ratio_10s(self) -> Decimal:
        total = self.buy_money_per_sec_10s + self.sell_money_per_sec_10s
        return self.buy_money_per_sec_10s / total if total > 0 else Decimal("0")


@dataclass
class HoldSellState:
    position_id: str
    strategy_id: StrategyId
    code: str
    quantity: int
    entry_price: Decimal
    entry_at: datetime
    peak_price: Decimal = Decimal("0")
    peak_stage: PeakStage = PeakStage.UNARMED
    phase: HoldPhase = HoldPhase.HOLD
    last_observed_at: Optional[datetime] = None
    watch_since: Optional[datetime] = None
    sell_condition_since: Optional[datetime] = None
    ma3_override_since: Optional[datetime] = None
    dryup_since: Optional[datetime] = None
    score_sell_since: Optional[datetime] = None
    flow_reversal_since: Optional[datetime] = None
    hold_peak_money_per_sec: Decimal = Decimal("0")
    valley_watch_since: Optional[datetime] = None
    valley_morning_break_since: Optional[datetime] = None
    hold_peak_speed_5s: Decimal = Decimal("0")
    sell_latched: bool = False
    sell_action: HoldSellAction = HoldSellAction.SELL
    sell_reason: str = ""
    sell_latched_at: Optional[datetime] = None
    sell_latched_price: Decimal = Decimal("0")
    last_trail_eval_at: Optional[datetime] = None
    entry_lane: str = ""

    def __post_init__(self) -> None:
        self.strategy_id = StrategyId(self.strategy_id)
        self.code = normalize_code(self.code)
        self.entry_at = as_kst(self.entry_at)
        self.entry_price = as_decimal(self.entry_price)
        self.peak_price = as_decimal(self.peak_price or self.entry_price)
        if not self.position_id.strip():
            raise ContractError("position_id is required")
        if self.quantity <= 0 or self.entry_price <= 0:
            raise ContractError("positive quantity and entry price are required")
        if self.peak_price < self.entry_price:
            self.peak_price = self.entry_price

    @property
    def order_key(self) -> str:
        return f"strategy-exit:{self.position_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "strategy_id": self.strategy_id.value,
            "code": self.code,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "entry_at": self.entry_at.isoformat(),
            "entry_lane": self.entry_lane,
            "peak_price": str(self.peak_price),
            "peak_stage": self.peak_stage.value,
            "phase": self.phase.value,
            "last_observed_at": _dt_text(self.last_observed_at),
            "watch_since": _dt_text(self.watch_since),
            "sell_condition_since": _dt_text(self.sell_condition_since),
            "ma3_override_since": _dt_text(self.ma3_override_since),
            "dryup_since": _dt_text(self.dryup_since),
            "score_sell_since": _dt_text(self.score_sell_since),
            "flow_reversal_since": _dt_text(self.flow_reversal_since),
            "hold_peak_money_per_sec": str(self.hold_peak_money_per_sec),
            "valley_watch_since": _dt_text(self.valley_watch_since),
            "valley_morning_break_since": _dt_text(self.valley_morning_break_since),
            "hold_peak_speed_5s": str(self.hold_peak_speed_5s),
            "sell_latched": self.sell_latched,
            "sell_action": self.sell_action.value,
            "sell_reason": self.sell_reason,
            "sell_latched_at": _dt_text(self.sell_latched_at),
            "sell_latched_price": str(self.sell_latched_price),
            "last_trail_eval_at": _dt_text(self.last_trail_eval_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HoldSellState":
        state = cls(
            position_id=str(payload["position_id"]),
            strategy_id=StrategyId(str(payload["strategy_id"])),
            code=str(payload["code"]),
            quantity=int(payload["quantity"]),
            entry_price=as_decimal(payload["entry_price"]),
            entry_at=datetime.fromisoformat(str(payload["entry_at"])),
            entry_lane=str(payload.get("entry_lane") or ""),
            peak_price=as_decimal(payload["peak_price"]),
        )
        state.peak_stage = PeakStage(str(payload.get("peak_stage") or "UNARMED"))
        state.phase = HoldPhase(str(payload.get("phase") or "HOLD"))
        for name in (
            "last_observed_at",
            "watch_since",
            "sell_condition_since",
            "ma3_override_since",
            "dryup_since",
            "score_sell_since",
            "flow_reversal_since",
            "sell_latched_at",
            "valley_watch_since",
            "valley_morning_break_since",
            "last_trail_eval_at",
        ):
            setattr(state, name, _parse_dt(payload.get(name)))
        state.hold_peak_money_per_sec = as_decimal(
            payload.get("hold_peak_money_per_sec") or "0"
        )
        state.hold_peak_speed_5s = as_decimal(payload.get("hold_peak_speed_5s") or "0")
        state.sell_latched = bool(payload.get("sell_latched"))
        state.sell_action = HoldSellAction(str(payload.get("sell_action") or "SELL"))
        state.sell_reason = str(payload.get("sell_reason") or "")
        state.sell_latched_price = as_decimal(payload.get("sell_latched_price") or "0")
        return state


@dataclass(frozen=True)
class HoldSellDecision:
    action: HoldSellAction
    reason: str
    strategy_id: StrategyId
    code: str
    observed_at: datetime
    price: Decimal
    order_key: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def should_sell(self) -> bool:
        return self.action in {
            HoldSellAction.SELL,
            HoldSellAction.EMERGENCY_SELL,
        }


def _dt_text(value: Optional[datetime]) -> str:
    return value.isoformat() if value is not None else ""


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    return as_kst(datetime.fromisoformat(text)) if text else None


class UnifiedHoldSellEngine:
    """One ordered hold/sell coordinator with strategy-specific profiles."""

    def __init__(self, config: Optional[HoldSellConfig] = None) -> None:
        self.config = config or HoldSellConfig()

    def evaluate(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        self._validate_sequence(state, observation)
        if state.sell_latched:
            return self._latched_decision(state)
        self._update_state_metrics(state, observation)
        profile = STRATEGY_PROFILES[state.strategy_id]
        if profile.exit_policy is not ExitPolicy.STANDARD:
            return self._evaluate_valley(state, observation, profile)
        # ★[2026-07-27 친구님 지시] 돈마름·점수매도·구조붕괴 매도는 끈다(조기매도 원인).
        # ★[2026-07-29 친구님 지시] 꼭지점 매도(PROFIT_TRAIL)만 되살린다.
        #   이익 실현 장치가 하나도 없어 7/29 S01 6건이 전부 하드손절로 끝났다.
        #   발동선을 2.0%→1.0%로 낮춘 새 trail_steps 기준으로 켠다.
        #   돈마름·점수매도·구조붕괴는 계속 꺼둔 상태 그대로다.
        #   상승보유보다 앞에 둔다 — 뒤에 두면 상승보유가 HOLD를 반환해 트레일이 안 탄다.
        # ★[RIDER-ORDER 2026-08-03 친구님 지시] rider_before_trail 인 전략(현재 S02)만
        #   상승보유를 트레일 앞으로 옮긴다. 하드손절·시간청산은 그대로 맨 앞이고,
        #   속도 역전 매도(진짜 꼭지)는 상승보유보다 앞에 둔다 — 상승보유가 HOLD 를
        #   반환하면 뒤 규칙에 도달하지 못하므로, 꼭지에서 못 파는 일이 없게 한다.
        #   나머지 전략은 rules_default 로 종전과 100% 동일하다.
        rules_default = (
            self._hard_stop_rule,
            self._time_exit_rule,
            self._profit_trail_rule,
            self._flow_reversal_exit_rule,
            self._early_trend_rule,
            self._daily_ma_hold_rule,
            self._ma3_rule,
        )
        rules_rider_first = (
            self._hard_stop_rule,
            self._time_exit_rule,
            self._daily_ma_hold_rule,        # 3분봉 10/20선 지지 = 상승보유 최우선
            self._flow_reversal_exit_rule,   # 이평 지지가 풀린 뒤 수급역전 확인
            self._profit_trail_rule,
            self._early_trend_rule,
            self._ma3_rule,
        )
        # ★[RIDER-FIRST-ALL 2026-08-03 친구님 지시 "5 10 20 이게 앞으로 가란 말야"]
        #   종전에는 rider_before_trail 인 전략(S01·S02)만 상승보유가 트레일 앞이었고
        #   나머지(S04·S05 등)는 트레일이 먼저 팔아버려 3분봉 5/10/20선이 무력했다.
        #   이제 전 전략이 상승보유를 먼저 본다. rules_default 는 참고용으로 남긴다.
        #   되돌리기: backup\strategy_common_hold_sell_v1_20260803_riderfirstall.py
        for rule in rules_rider_first:
            decision = rule(state, observation, profile)
            if decision is not None:
                return decision
        return self._decision(
            state, observation, HoldSellAction.HOLD, "HOLD_RIDING")

    def _flow_reversal_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        """S02 only: confirmed sell-flow reversal before the final -2% insurance."""
        if not profile.flow_reversal_exit_enabled:
            return None
        has_exact_data = (
            observation.buy_money_per_sec_10s > 0
            and observation.sell_money_per_sec_10s > 0
            and observation.buy_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_previous_10s > 0
            and observation.che_str > 0
        )
        # ★[MA5-AUX 2026-08-03 친구님 지시] 5일선은 관문이 아니라 민감도 조절용.
        #   아래에 있으면(추세 꺾임) 배수와 확인시간을 낮춰 빨리 판다.
        #   위에 있으면(추세 살아있음) 종전 값 그대로 엄격하게 본다.
        if observation.daily_ma5_broken:
            scale = self.config.flow_reversal_below_ma5_mult_scale
            confirm_sec = self.config.flow_reversal_below_ma5_confirm_sec
        else:
            scale = Decimal("1")
            confirm_sec = self.config.flow_reversal_confirm_sec
        reversal = (
            has_exact_data
            and observation.one_minute_bull_to_bear
            and observation.sell_money_per_sec_10s
            >= observation.buy_money_per_sec_10s
            * self.config.flow_reversal_sell_money_mult * scale
            and observation.sell_volume_per_sec_5s
            >= observation.buy_volume_per_sec_5s
            * self.config.flow_reversal_sell_volume_mult * scale
            and observation.sell_volume_per_sec_5s
            >= observation.sell_volume_per_sec_previous_10s
            * self.config.flow_reversal_volume_accel_mult * scale
            and observation.che_str <= self.config.flow_reversal_max_che_str
            and observation.che_str_change_5s
            <= -self.config.flow_reversal_min_che_drop
        )
        if not reversal:
            state.flow_reversal_since = None
            return None
        if observation.ma10_support and observation.ma20_rising:
            state.flow_reversal_since = None
            return self._decision(
                state, observation, HoldSellAction.HOLD,
                "S02_MA10_MA20_SUPPORT_HOLD",
            )
        if state.flow_reversal_since is None:
            state.flow_reversal_since = observation.observed_at
        age = (observation.observed_at - state.flow_reversal_since).total_seconds()
        # ★[MA5-AUX 2026-08-03] 확인시간도 5일선 위치로 조절한다(위 주석 참조).
        if age < confirm_sec:
            return self._decision(
                state, observation, HoldSellAction.WATCH,
                f"S02_FLOW_REVERSAL_CONFIRM {age:.0f}/{confirm_sec}s"
                f"{' below_ma5' if observation.daily_ma5_broken else ''}",
            )
        reason = (
            "S02_FLOW_REVERSAL_EXIT "
            f"money={observation.sell_money_per_sec_10s / observation.buy_money_per_sec_10s:.2f}x "
            f"volume={observation.sell_volume_per_sec_5s / observation.buy_volume_per_sec_5s:.2f}x "
            f"che={observation.che_str:.1f} age={age:.0f}s"
        )
        return self._latch(
            state, observation, HoldSellAction.SELL, reason)

    def _evaluate_valley(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        if profile.exit_policy is ExitPolicy.TREND_REBOUND:
            return self._evaluate_trend_rebound(state, observation, profile)
        if profile.exit_policy is ExitPolicy.VALLEY:
            return self._evaluate_regular_valley(state, observation, profile)
        if profile.exit_policy is ExitPolicy.VALLEY_MORNING_CRASH:
            return self._evaluate_valley_morning(state, observation, profile)
        return self._evaluate_valley_base(state, observation, profile)

    def _evaluate_trend_rebound(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        """Shared rebound exit: time/risk, rider(5/10/20), trail, MA5 break."""
        # ★[RIDER-FIRST-ALL 2026-08-03 친구님 지시 "5 10 20 이게 앞으로 가란 말야"]
        #   종전 순서: 시간 -> 트레일 -> 하드손절 -> 5선이탈 -> 상승보유.
        #   트레일과 5선이탈이 상승보유보다 앞이라, 3분봉 5/10/20선이 받쳐주는데도
        #   먼저 팔려나갔다. 이제 하드손절·시간청산 바로 뒤에 상승보유를 둔다.
        #   ⚠️하드손절은 계속 맨 앞이다(보험은 무엇보다 앞선다).
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision

        decision = self._daily_ma_hold_rule(state, observation, profile)
        if decision is not None:
            state.valley_morning_break_since = None
            return decision

        decision = self._profit_trail_rule(state, observation, profile)
        if decision is not None:
            return decision

        # ★[MA-AUX-ONLY 2026-08-03 친구님 지시]
        #   "원래 5 10 20은 보조적 수단으로 쓰는 거야. 매매 수단이 아냐."
        #   종전에는 여기서 5선을 깨면 곧바로 매도(DAILY_MA5_BREAK)했다 = 선을
        #   매매 수단으로 쓴 것. 제거한다. 5선은 흐름역전 민감도 조절
        #   (_flow_reversal_exit_rule 의 daily_ma5_broken)로만 남는다.
        #   매도 방아쇠는 하드손절·시간청산·수급(속도)·구조붕괴가 맡는다.

        if observation.structure_broken:
            if state.valley_morning_break_since is None:
                state.valley_morning_break_since = observation.observed_at
            age = (
                observation.observed_at - state.valley_morning_break_since
            ).total_seconds()
            if age < self.config.valley_morning_confirm_sec:
                return self._decision(
                    state,
                    observation,
                    HoldSellAction.WATCH,
                    f"TREND_REBOUND_BREAK_WATCH {age:.0f}/{self.config.valley_morning_confirm_sec}s",
                )
            return self._finish_valley_morning_watch(state, observation)

        state.valley_morning_break_since = None
        decision = self._early_trend_rule(state, observation, profile)
        if decision is not None:
            return decision
        return self._decision(
            state, observation, HoldSellAction.HOLD, "TREND_REBOUND_HOLD"
        )

    def _evaluate_regular_valley(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        peak_drop = (
            observation.price / state.peak_price - Decimal("1")
        ) * Decimal("100")
        if profile.peak_insure_pct is not None and peak_drop <= profile.peak_insure_pct:
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                f"VALLEY_PEAK_INSURE {peak_drop:.2f}% <= {profile.peak_insure_pct:.2f}%",
            )
        if observation.valley_ma10_reclaimed_then_lost:
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                "VALLEY_MA10_RECLAIM_LOST",
            )
        return self._valley_peak_watch_rule(state, observation)

    def _valley_peak_watch_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        if observation.valley_peak_reclaimed:
            state.valley_watch_since = None
            return self._decision(
                state, observation, HoldSellAction.HOLD, "VALLEY_PEAK_RECLAIM_HOLD"
            )
        if state.valley_watch_since is None:
            if not observation.valley_completed_bearish_1m:
                return self._decision(
                    state, observation, HoldSellAction.HOLD, "VALLEY_RISING_HOLD"
                )
            state.valley_watch_since = observation.observed_at
        age = (observation.observed_at - state.valley_watch_since).total_seconds()
        if age < self.config.valley_watch_sec:
            return self._decision(
                state,
                observation,
                HoldSellAction.WATCH,
                f"VALLEY_PEAK_WATCH {age:.0f}/{self.config.valley_watch_sec}s",
            )
        return self._finish_valley_peak_watch(state, observation)

    def _finish_valley_peak_watch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        points = {
            "STRENGTH_FALL": observation.valley_strength_falling,
            "BUY_FLOW_FALL": observation.valley_buy_flow_falling,
            "SELL_FLOW_RISE": observation.valley_sell_flow_rising,
            "PEAK_RECLAIM_FAIL": observation.valley_peak_reclaim_failed,
        }
        score = sum(1 for value in points.values() if value)
        threshold = (
            self.config.valley_weak_ma_score_threshold
            if observation.valley_ma5_reclaimed_then_lost
            else self.config.valley_sell_score_threshold
        )
        state.valley_watch_since = None
        if score >= threshold:
            hits = ",".join(name for name, hit in points.items() if hit)
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                f"VALLEY_PEAK_SELL score={score}/4 threshold={threshold} {hits}",
            )
        return self._decision(
            state,
            observation,
            HoldSellAction.HOLD,
            f"VALLEY_PEAK_WATCH_RELEASE score={score}/4 threshold={threshold}",
        )

    def _evaluate_valley_morning(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        # ★[RIDER-FIRST-ALL 2026-08-03 친구님 지시 "골짜기 이거 넣어 연결해"]
        #   S03(VALLEY_MORNING_CRASH)은 경로가 달라 상승보유가 아예 없었다.
        #   3분봉 5/10/20선을 계산만 하고 버리던 상태 → 하드손절 바로 뒤에 연결한다.
        #   ★5/10/20은 '보조 수단'이다 — 파는 근거가 아니라 안 팔게 잡아주는 것.
        #     그래서 여기서 하는 일은 HOLD 뿐이고, 매도는 아래 구조붕괴가 맡는다.
        #   하드손절·시간청산은 앞순위 그대로(보험은 무엇보다 앞선다).
        decision = self._daily_ma_hold_rule(state, observation, profile)
        if decision is not None:
            state.valley_morning_break_since = None
            return decision
        if not observation.structure_broken:
            state.valley_morning_break_since = None
            return self._decision(
                state, observation, HoldSellAction.HOLD, "VALLEY_MORNING_HOLD"
            )
        if state.valley_morning_break_since is None:
            state.valley_morning_break_since = observation.observed_at
        age = (
            observation.observed_at - state.valley_morning_break_since
        ).total_seconds()
        if age < self.config.valley_morning_confirm_sec:
            return self._decision(
                state,
                observation,
                HoldSellAction.WATCH,
                f"VALLEY_MORNING_BREAK_WATCH {age:.0f}/{self.config.valley_morning_confirm_sec}s",
            )
        return self._finish_valley_morning_watch(state, observation)

    def _finish_valley_morning_watch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        state.valley_morning_break_since = None
        exact_sell = (
            observation.valley_exact_flow_valid
            and observation.valley_exact_sell_dominant
        )
        if exact_sell:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                "VALLEY_MORNING_STRUCTURE_BREAK+EXACT_SELL_DOMINANT",
            )
        return self._decision(
            state, observation, HoldSellAction.HOLD, "VALLEY_MORNING_BREAK_CANCEL"
        )

    def _evaluate_valley_base(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        decision = self._profile_time_exit(state, observation, profile)
        decision = decision or self._hard_stop_rule(state, observation, profile)
        if decision is not None:
            return decision
        return_pct = self._return_pct(state, observation.price)
        if profile.target_profit_pct is not None and return_pct >= profile.target_profit_pct:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                f"VALLEY_BASE_TARGET {return_pct:.2f}% >= {profile.target_profit_pct:.2f}%",
            )
        return self._decision(
            state, observation, HoldSellAction.HOLD, "VALLEY_BASE_HOLD"
        )

    def _profile_time_exit(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time < profile.force_exit_at:
            return None
        return self._latch(
            state,
            observation,
            HoldSellAction.EMERGENCY_SELL,
            f"TIME_EXIT_{profile.force_exit_at.strftime('%H%M')}",
        )


    @staticmethod
    def _validate_sequence(
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> None:
        if observation.observed_at < state.entry_at:
            raise ContractError("observation precedes entry time")
        if state.last_observed_at and observation.observed_at < state.last_observed_at:
            raise ContractError("out-of-order observation rejected")

    def _update_state_metrics(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> None:
        state.last_observed_at = observation.observed_at
        state.peak_price = max(state.peak_price, observation.price)
        state.hold_peak_money_per_sec = max(
            state.hold_peak_money_per_sec,
            observation.money_per_sec_30s,
        )
        state.hold_peak_speed_5s = max(
            state.hold_peak_speed_5s,
            observation.money_speed_5s,
        )
        state.peak_stage = self._peak_stage(state)

    def _hard_stop_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        return_pct = self._return_pct(state, observation.price)
        stop_pct = profile.stop_pct(observation.buy_ratio_recent)
        # ★[STOP-LADDER 2026-08-03 친구님 지시] 손절선 끌어올리기(전략별).
        #   왜: 하드손절이 매수가 기준 고정이라, 이익이 났다가 되돌아와도 같은 자리에서
        #   잘린다 = 번 걸 다 토해내고 손실까지 본다. 8/3 실측: 코스모로보틱스 2회차가
        #   +2.10% 까지 갔다가 -2.05% 로 끝났다.
        #   계단을 켜면 고점 수익률이 문턱을 넘을 때마다 손절선이 위로 올라간다(내려가지 않음).
        #   같은 3건 재생: 합계 +9.40% -> +11.33%. 이익 나는 거래는 손절에 안 걸려 무영향,
        #   손실만 -2.05% -> -0.11% 로 줄었다.
        #   stop_ladder=None(기본)이면 종전과 100% 동일 → 다른 전략 무영향.
        if profile.stop_ladder:
            peak_return = self._return_pct(state, state.peak_price)
            for arm, raised in profile.stop_ladder:
                if peak_return >= arm and raised > stop_pct:
                    stop_pct = raised
        if return_pct <= stop_pct:
            reason = f"HARD_STOP {return_pct:.2f}% <= {stop_pct:.2f}%"
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                reason,
            )
        return None

    def _time_exit_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time >= profile.force_exit_at:
            reason = f"TIME_EXIT_{profile.force_exit_at.strftime('%H%M')}"
            return self._latch(
                state,
                observation,
                HoldSellAction.EMERGENCY_SELL,
                reason,
            )
        return None

    def _early_trend_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if profile.early_decision_at is None:
            return None
        local_time = observation.observed_at.timetz().replace(tzinfo=None)
        if local_time < profile.early_decision_at:
            return None
        failures = self._early_trend_failures(state, observation)
        if failures:
            return self._latch(
                state,
                observation,
                HoldSellAction.SELL,
                "EARLY_TREND_EXIT " + ",".join(failures),
            )
        return None

    def _early_trend_failures(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> list[str]:
        failures: list[str] = []
        # ★[2026-07-29 친구님 승인 "결손=보류"] vwap<=0 또는 price<=0 은 시세 결손이지
        #   추세이탈이 아니다(회전엔진은 체결누적 없는 스냅샷에 0/-1 을 넣는다 —
        #   구독 밀림 때 실제로 발생하는 유형). 종전 코드 `not (vwap>0 and price>vwap)` 는
        #   결손 한 틱을 이탈로 오판해 즉시 전량매도 래치(회복 불가)를 걸었다.
        #   값이 둘 다 있을 때만 판정하고, 없으면 이 항목은 보류(다음 틱 재판정).
        #   문턱 자체(price<=vwap = 이탈)는 종전과 동일. 롤백: *.bak_20260729_review45
        if observation.vwap > 0 and observation.price > 0 and observation.price <= observation.vwap:
            failures.append("VWAP")
        # ★[2026-07-29 친구님 지시] MA3 항목 제외.
        #   ma3_permit 을 채우는 코드가 현역 회전엔진에 없어 항상 False 다.
        #   그대로 두면 failures 에 "MA3"가 무조건 들어가고, 이 규칙은
        #   "하나라도 실패하면 매도"라서 조기추세를 켜는 즉시 전량 강제매도가 된다.
        #   1분봉 보관 봉수를 늘려 ma3_permit 을 살리면 그때 다시 넣는다.
        #   원래 코드:  if not observation.ma3_permit: failures.append("MA3")
        if observation.buy_ratio_recent < self.config.early_trend_min_buy_ratio:
            failures.append("FLOW")
        # ★[2026-07-29 친구님 지시] SPEED 항목 제외.
        #   "자금 유입속도가 준다고 매도하면 안 된다. 돈이 말랐어도 매수세가 우위면 끌고 간다.
        #    중요한 것은 매도세가 위가 되었느냐다."
        #   자금 속도 저하는 매도 근거가 못 되고, 매도세 우위 판정은 FLOW(매수비율)가 맡는다.
        #   원래 코드:
        #     speed_floor = self.config.early_trend_speed_fraction * observation.money_speed_30s
        #     if not (observation.money_speed_30s > 0
        #             and observation.money_speed_10s >= speed_floor):
        #         failures.append("SPEED")
        # ★[2026-07-29 친구님 지시] STRUCTURE·SELL_SCORE 항목 제외.
        #   구조붕괴 매도와 점수 매도는 2026-07-27 에 조기매도 원인으로 중단한 기능이다.
        #   조기추세 규칙 안에 들어 있어 이 규칙을 켜면 함께 되살아나므로 판정에서 뺀다.
        #   조기추세는 VWAP·FLOW·SPEED 세 항목으로만 판정한다.
        #   원래 코드:
        #     if observation.structure_broken: failures.append("STRUCTURE")
        #     if self._sell_score(state, observation) >= self.config.score_sell_ready:
        #         failures.append("SELL_SCORE")
        return failures

    def _daily_ma_hold_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        """상승보유 — 3분봉이 5일선을 횡보하고 10일선이 뒤를 받치며,
        10일선을 침범해도 20일선이 우상향으로 보조하면 매도하지 않는다.

        판정은 회전엔진이 daily_ma_permit으로 넘긴다. 모든 전략 공통.
        하드손절과 강제청산은 이 규칙보다 먼저 평가되므로 그대로 살아 있다.
        """
        if not observation.daily_ma_permit:
            return None
        self._reset_general_exit_timers(state)
        return self._decision(
            state, observation, HoldSellAction.HOLD, "DAILY_MA_RIDER_HOLD")

    def _ma3_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if not observation.ma3_permit or profile.ma3_mode is MA3Mode.NONE:
            state.ma3_override_since = None
            return None
        if profile.ma3_mode is MA3Mode.HOLD_LOCK:
            self._reset_general_exit_timers(state)
            return self._decision(state, observation, HoldSellAction.HOLD, "MA3_RIDER_HOLD")
        return self._ma3_override_rule(state, observation)

    def _ma3_override_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        self._reset_general_exit_timers(state)
        override = self._sell_dominant_break(observation)
        if not override:
            state.ma3_override_since = None
            return self._decision(state, observation, HoldSellAction.HOLD, "MA3_RIDER_HOLD")
        if state.ma3_override_since is None:
            state.ma3_override_since = observation.observed_at
        age = (observation.observed_at - state.ma3_override_since).total_seconds()
        if age >= self.config.sell_confirm_sec:
            reason = f"{state.strategy_id.value}_MA3_SELL_OVERRIDE {age:.0f}s"
            return self._latch(state, observation, HoldSellAction.SELL, reason)
        return self._decision(
            state,
            observation,
            HoldSellAction.WATCH,
            f"MA3_SELL_WATCH {age:.0f}/{self.config.sell_confirm_sec}s",
        )

    def _profit_trail_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        # ★[TRAIL-FLOW 2026-08-03 친구님 지시] 판정 주기를 전략별로 덮어쓴다.
        #   공용 180초는 "그 3분 사이에 끝없이 추락할 수 있어" 위험하다 → S02 는 50초.
        interval = int(
            _profile.trail_eval_interval_sec
            if _profile.trail_eval_interval_sec is not None
            else self.config.trail_eval_interval_sec
        )
        if interval > 0:
            since = state.last_trail_eval_at or state.entry_at
            if (observation.observed_at - since).total_seconds() < interval:
                return None
            state.last_trail_eval_at = observation.observed_at
        drop_threshold = self._trail_drop_threshold(state, _profile)
        if drop_threshold <= 0:
            return None
        peak_drop = (state.peak_price - observation.price) / state.peak_price * 100
        if peak_drop < drop_threshold or self._trail_money_guard(observation):
            return None
        # ★[TRAIL-FLOW 2026-08-03 친구님 지시] 가격만으로는 팔지 않는다.
        #   "1분봉 양봉이면 계속 올라간다 → 보유. 음봉일 때만 수급을 본다.
        #    그것도 매도세/매수세를 딱 정하는 게 아니라 속도가 올라가냐 떨어지냐를 본다."
        #   구조는 5번 BASE_FAILURE_EXIT 를 본떴다(이미 만들어 검증된 형태).
        #   3종 = ①매수 금액속도 하락(10초<30초) ②매도 금액속도 상승(10초>30초)
        #         ③매도 거래량 가속(5초>직전10초)
        #   자료가 없으면(전부 0) 팔지 않는다 — 판단 불가에 매도는 위험하다.
        if _profile.trail_needs_sell_pressure:
            if not observation.one_minute_bearish:
                return None                       # 양봉 = 아직 올라간다
            has_flow = (
                observation.buy_money_per_sec_30s > 0
                and observation.sell_money_per_sec_30s > 0
                and observation.sell_volume_per_sec_previous_10s > 0
            )
            buy_cooling = (
                observation.buy_money_per_sec_10s
                < observation.buy_money_per_sec_30s
            )
            sell_heating = (
                observation.sell_money_per_sec_10s
                > observation.sell_money_per_sec_30s
            )
            sell_accel = (
                observation.sell_volume_per_sec_5s
                > observation.sell_volume_per_sec_previous_10s
            )
            if not (has_flow and buy_cooling and sell_heating and sell_accel):
                return None
        peak_return = self._return_pct(state, state.peak_price)
        reason = (
            f"PROFIT_TRAIL peak={peak_return:.2f}% "
            f"drop={peak_drop:.2f}% threshold={drop_threshold:.2f}%"
        )
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _trail_money_guard(self, observation: HoldSellObservation) -> bool:
        speed_alive = (
            observation.money_speed_30s <= 0
            or observation.money_speed_10s
            >= self.config.persistence_speed_fraction * observation.money_speed_30s
        )
        return (
            observation.buy_ratio_10s >= self.config.trail_guard_buy_ratio
            and speed_alive
        )

    def _money_dryup_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        hold_age = (observation.observed_at - state.entry_at).total_seconds()
        peak = state.hold_peak_money_per_sec
        dry = (
            hold_age >= self.config.dryup_min_hold_sec
            and peak >= self.config.dryup_min_peak_money_per_sec
            and observation.money_per_sec_30s < self.config.dryup_fraction * peak
            and not observation.money_accelerating
            and observation.sell_money_per_sec_30s > observation.buy_money_per_sec_30s
        )
        if not dry:
            state.dryup_since = None
            return None
        if state.dryup_since is None:
            state.dryup_since = observation.observed_at
        age = (observation.observed_at - state.dryup_since).total_seconds()
        if age < self.config.dryup_confirm_sec:
            return None
        reason = f"MONEY_DRYUP sell_dominant {age:.0f}s"
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _score_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if not self.config.score_sell_enabled:
            return None
        score = self._sell_score(state, observation)
        hold_age = (observation.observed_at - state.entry_at).total_seconds()
        blocked = (
            score < self.config.score_sell_ready
            or observation.daily_ma_permit
            or hold_age < profile.score_min_hold_sec
            or observation.recent_buy_money_rising
        )
        if blocked:
            state.score_sell_since = None
            return None
        if state.score_sell_since is None:
            state.score_sell_since = observation.observed_at
        age = (observation.observed_at - state.score_sell_since).total_seconds()
        if age < self.config.score_confirm_sec:
            return None
        reason = f"SCORE_SELL score={score:.1f} age={age:.0f}s"
        return self._latch(state, observation, HoldSellAction.SELL, reason)

    def _sell_score(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> Decimal:
        score = Decimal("0")
        if observation.vwap > 0 and observation.price < observation.vwap:
            score += Decimal("25")
        peak = state.hold_peak_speed_5s
        if peak >= self.config.score_peak_min_money_per_sec:
            if observation.money_speed_5s < Decimal("0.20") * peak:
                score += Decimal("40")
            elif observation.money_speed_5s < Decimal("0.50") * peak:
                score += Decimal("25")
        total_30 = observation.money_per_sec_30s
        if total_30 > 0:
            buy_share = observation.buy_money_per_sec_30s / total_30
            if buy_share < Decimal("0.35"):
                score += Decimal("35")
            elif buy_share < Decimal("0.50"):
                score += Decimal("25")
        return score * Decimal("0.50") if observation.money_accelerating else score

    def _vwap_fallback_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> Optional[HoldSellDecision]:
        if self.config.score_sell_enabled or not self.config.vwap_warn_exit_enabled:
            return None
        speed_weak = (
            observation.money_speed_30s > 0
            and observation.money_speed_10s
            < self.config.persistence_speed_fraction * observation.money_speed_30s
        )
        should_sell = (
            observation.vwap > 0
            and observation.price < observation.vwap
            and observation.buy_ratio_recent <= self.config.sell_buy_ratio
            and speed_weak
            and not observation.money_accelerating
        )
        if not should_sell:
            return None
        return self._latch(
            state,
            observation,
            HoldSellAction.SELL,
            "VWAP_WARN_EXIT",
        )

    def _flow_structure_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        _profile: StrategyExitProfile,
    ) -> HoldSellDecision:
        flow_weak = observation.buy_ratio_recent < self.config.watch_buy_ratio
        if state.phase is HoldPhase.HOLD:
            if not flow_weak:
                return self._decision(state, observation, HoldSellAction.HOLD, "FLOW_HEALTHY")
            state.phase = HoldPhase.WATCH
            state.watch_since = observation.observed_at
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.WATCH, "FLOW_WEAK")
        if not flow_weak:
            state.phase = HoldPhase.HOLD
            state.watch_since = None
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.HOLD, "FLOW_RECOVERED")
        return self._watch_flow_rule(state, observation)

    def _watch_flow_rule(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ) -> HoldSellDecision:
        if not self._sell_dominant_break(observation):
            state.sell_condition_since = None
            return self._decision(state, observation, HoldSellAction.WATCH, "WATCH_CONTINUE")
        if state.sell_condition_since is None:
            state.sell_condition_since = observation.observed_at
        watch_age = (observation.observed_at - (state.watch_since or observation.observed_at)).total_seconds()
        condition_age = (observation.observed_at - state.sell_condition_since).total_seconds()
        multiplier = self.config.ma_permit_confirm_mult if observation.daily_ma_permit else Decimal("1")
        required = Decimal(self.config.sell_confirm_sec) * multiplier
        if watch_age >= self.config.watch_confirm_sec and Decimal(str(condition_age)) >= required:
            reason = f"FLOW_WEAK+STRUCTURE_BREAK {condition_age:.0f}s"
            return self._latch(state, observation, HoldSellAction.SELL, reason)
        return self._decision(
            state,
            observation,
            HoldSellAction.WATCH,
            f"SELL_CONFIRM {condition_age:.0f}/{required:.0f}s",
        )

    def _sell_dominant_break(self, observation: HoldSellObservation) -> bool:
        return (
            observation.buy_ratio_recent <= self.config.sell_buy_ratio
            and observation.structure_broken
            and not observation.money_accelerating
        )

    @staticmethod
    def _reset_general_exit_timers(state: HoldSellState) -> None:
        state.phase = HoldPhase.HOLD
        state.watch_since = None
        state.sell_condition_since = None
        state.dryup_since = None
        state.score_sell_since = None
        state.flow_reversal_since = None

    def _peak_stage(self, state: HoldSellState) -> PeakStage:
        peak_return = self._return_pct(state, state.peak_price)
        if peak_return >= Decimal("7"):
            return PeakStage.PROFIT_7
        if peak_return >= Decimal("4"):
            return PeakStage.PROFIT_4
        if peak_return >= Decimal("2"):
            return PeakStage.PROFIT_2
        return PeakStage.UNARMED

    def _trail_drop_threshold(
        self,
        state: HoldSellState,
        profile: Optional[StrategyExitProfile] = None,
    ) -> Decimal:
        """트레일 발동 폭. ★[2026-07-31] 전략 프로파일에 trail_steps 가 있으면 그것을,
        없으면 공용값을 쓴다(S01 만 별도값·다른 전략 무영향)."""
        peak_return = self._return_pct(state, state.peak_price)
        threshold = Decimal("0")
        steps = (profile.trail_steps if (profile and profile.trail_steps)
                 else self.config.trail_steps)
        for arm, drop in steps:
            if peak_return >= arm:
                threshold = drop
        return threshold

    @staticmethod
    def _return_pct(state: HoldSellState, price: Decimal) -> Decimal:
        return (as_decimal(price) / state.entry_price - Decimal("1")) * Decimal("100")

    def _latch(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        action: HoldSellAction,
        reason: str,
    ) -> HoldSellDecision:
        state.sell_latched = True
        state.sell_action = action
        state.sell_reason = reason
        state.sell_latched_at = observation.observed_at
        state.sell_latched_price = observation.price
        return self._latched_decision(state)

    def _latched_decision(self, state: HoldSellState) -> HoldSellDecision:
        if state.sell_latched_at is None or state.sell_latched_price <= 0:
            raise ContractError("latched sell state is incomplete")
        metadata = {
            "peak_price": str(state.peak_price),
            "peak_stage": state.peak_stage.value,
        }
        return HoldSellDecision(
            action=state.sell_action,
            reason=state.sell_reason,
            strategy_id=state.strategy_id,
            code=state.code,
            observed_at=state.sell_latched_at,
            price=state.sell_latched_price,
            order_key=state.order_key,
            metadata=metadata,
        )

    def _decision(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
        action: HoldSellAction,
        reason: str,
    ) -> HoldSellDecision:
        metadata = {
            "peak_price": str(state.peak_price),
            "peak_stage": state.peak_stage.value,
            "phase": state.phase.value,
        }
        return HoldSellDecision(
            action=action,
            reason=reason,
            strategy_id=state.strategy_id,
            code=state.code,
            observed_at=observation.observed_at,
            price=observation.price,
            order_key=state.order_key,
            metadata=metadata,
        )


def build_sell_intent(
    state: HoldSellState,
    decision: HoldSellDecision,
) -> Optional[OrderIntent]:
    """Build a deterministic sell intent; no broker call is made."""
    if not decision.should_sell:
        return None
    if decision.code != state.code or decision.strategy_id is not state.strategy_id:
        raise ContractError("decision and position state do not match")
    return OrderIntent(
        idempotency_key=decision.order_key,
        strategy_id=state.strategy_id.value,
        signal_id=decision.reason,
        code=state.code,
        side=OrderSide.SELL,
        quantity=state.quantity,
        reservation_price=decision.price,
        created_at=decision.observed_at,
    )


class JsonHoldSellStateStore:
    """Atomic persistence for restart-safe hold/sell decision state."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, states: Mapping[str, HoldSellState]) -> None:
        payload = {
            "schema": STATE_SCHEMA,
            "states": {
                normalize_code(code): state.to_dict()
                for code, state in sorted(states.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def load(self) -> dict[str, HoldSellState]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != STATE_SCHEMA:
            raise ContractError(f"unsupported state schema: {payload.get('schema')!r}")
        return {
            normalize_code(code): HoldSellState.from_dict(state)
            for code, state in dict(payload.get("states") or {}).items()
        }

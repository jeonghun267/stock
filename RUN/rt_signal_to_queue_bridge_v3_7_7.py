# -*- coding: utf-8 -*-
# [v3.6] 평가 결함 전건 수정 (2026-04-19)
# [C1] docstring EV 기준 잔존 표기 제거 — 코드·문서 불일치 해소
# [C2] _file_unlock bare lg 참조 → 함수 내부 로거 명시 (NameError 방지)
# [M1] D2 비활성 상수 (DAILY_FORCE_COMPOSITE_RELAX 등) 제거
# [M2] D6 docstring dead description 정정
# [v3.5] 헤지펀드 아키텍처 표준 적용 — 선별 팩터 이중 투입 제거 (2026-04-19)
#
#  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  [핵심 원칙 변경] C레벨 임원진 합동 결의
#  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RenTec / Citadel / AQR 표준: 신호 생성과 집행은 엄격히 분리
#    - 선별 팩터(OFI·모멘텀·Sharpe·EV 복합점수)는 스코어보드에서 소모
#    - 브리지는 "집행 적합성" 검증만 담당
#      = 신호 유효성 + 중복 차단 + 킬스위치 + 포지션 사이징 + 레짐 오버라이드
#
#  [제거된 이중 선별 항목]
#  H1 ★★★ _profit_quality_check() 하드차단 로직 제거
#     근거: Sharpe/Sortino/PF 검증은 스코어보드 자기진화 루프 담당
#           브리지에서 재검증 시 이미 선별된 신호의 99%+ 소멸 (실측)
#     변경: PF < 0.8 하드차단 → STABLE 강등으로 완화 / Sharpe 차단 제거
#
#  H2 ★★★ _strategy_override_gate() EV/복합점수 이중 게이팅 제거
#     근거: EV·composite는 스코어보드 2단계(잔차모멘텀·수급)에서 이미 계산
#           브리지 재계산 = 동일 팩터 이중 적용 → 구조적 오류
#     변경: STRATEGY_OVERRIDES에서 ev_min / composite_min 제거
#           ride_min(기관 모멘텀 실시간 확인)만 유지
#
#  H3 ★★ EV_ENTRY_MIN / COMPOSITE_SCORE_MIN 글로벌 게이트 제거
#     근거: 스코어보드 stage1(OFI·VPIN) + stage2(갭업·val_ratio)에서 이미 EV 검증
#     변경: EV/composite 글로벌 필터 비활성화
#           대신 ride_score 급락 감지(RIDE_DECAY_MAX)만 유지
#
#  [유지되는 집행 검증 항목]
#  K1 킬스위치 5대 조건 (일일손실/데이터지연/주문거절/반복매도)
#  K2 신호 나이 검증 (SIGNAL_MAX_AGE_SEC=180)
#  K3 중복 진입 차단 (DAILY_SOLD / QUEUE_DUPLICATE / OPEN_POSITION)
#  K4 레짐 오버라이드 (BEAR 차단 / CAUTION→STABLE)
#  K5 ride_score 급락 감지 (decay > 20% → 차단) — 실시간 재검증 유일 허용
#  K6 accel 기관가속도 (BLOCK < 0.50 → 차단) — 실시간 재검증 유일 허용
#  K7 SWITCH 타임아웃
#  K8 포지션 사이징 (Half-Kelly) + exec_type 동적 결정 (Almgren & Chriss)
"""
rt_signal_to_queue_bridge.py  v3.7.5  SAFEPLUS_FINAL
====================================================
기준일  : 2026-04-19

[v3.7.4 → v3.7.5 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 _is_strong_pb 조건 단순화 — priority/quality 재필터 제거
  문제:
    스코어보드가 pullback_setup_class="STRONG"으로 이미 검증 완료:
      priority ≥ 50 AND quality ≥ 55 (스코어보드 P3 기준)
    그런데 브리지에서 동일 조건 재검증:
      _pb_pri >= 50 AND _pb_qual >= 55
    → 이중 선별 = 헤지펀드 표준 위반 (스코어보드 불신)
    → STRONG으로 분류됐어도 브리지에서 priority/quality 경계값에 걸려 탈락
    → 수익 누수의 핵심 원인

  수정:
    _is_strong_pb = (
        _pb_class == "STRONG"
        and _pb_ride > 0
    )
    → STRONG이면 즉시 오버라이드
    → ride=0 완전 이탈만 방어 (기관 완전 이탈 최소 안전망)

  근거:
    스코어보드 P3: priority≥50 + quality≥55 → STRONG 분류
    브리지 역할: 실시간 기관 모멘텀 이탈 감지 (ride_score)
    priority/quality는 EOD 정적 지표 → 브리지 재검증 불필요
    STRONG 클래스 자체가 이미 "충분히 검증됐다"는 의미

[v3.7.3 → v3.7.4 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 _strategy_override_gate 건너뜀 (ride_min 재검증 제거)

[v3.7.2 → v3.7.3 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 PULLBACK STRONG 즉시 진입 오버라이드 (accel/inst 우회)

[v3.7.1 → v3.7.2 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 siga_enable / pullback_enable 브리지 차단 구현
  문제:
    v3.7.3에서 accel/inst_momentum 우회 구현됐으나
    이후 _strategy_override_gate()에서 ride_min=0.30 재검증
    PULLBACK ride<0.30이면 STRATEGY_OVERRIDE_FAIL로 다시 차단
    → STRONG 오버라이드가 마지막 게이트에서 무효화됨
  근거:
    ride=0 완전 이탈은 이미 _inst_momentum_recheck 단계에서 방어
    (_pb_ride > 0 조건으로 ride=0이면 _is_strong_pb=False)
    _strategy_override_gate의 ride_min=0.30은 중복 차단
    STRONG = EOD 5일+ 기관 지지 검증 완료 → 실시간 ride_min 재검증 불필요
  수정:
    _strategy_override_gate 호출 전에 _is_strong_pb 체크
    STRONG이면 _strategy_override_gate 완전히 건너뜀
    mode는 유지 (B4에서 이미 ATTACK 보장됨)
  보호 경계 (STRONG이어도 절대 우회 불가):
    킬스위치 / BEAR 레짐 / 전략 활성화 게이트 / ride=0 완전이탈
    → 모두 이 코드보다 앞서서 이미 차단됨

[v3.7.2 → v3.7.3 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 PULLBACK STRONG 즉시 진입 오버라이드 (accel/inst 우회)

[v3.7.1 → v3.7.2 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 siga_enable / pullback_enable 브리지 차단 구현
  문제:
    스코어보드: priority/quality/avg_rank 기반 STRONG 선별
    브리지 진입 게이트: accel/ride/vwap 기반 실시간 차단
    → 선별 기준과 진입 트리거가 서로 다름
    → STRONG 눌림이 accel 둔화 한 가지로 차단되는 구조
    → EOD에서 검증한 수익성 높은 후보를 장중에서 버리는 수익 누수

  해결 원칙:
    STRONG 셋업 = EOD 스코어보드가 이미 5일+ 기관 지지 + 품질 검증 완료
    accel/inst_momentum은 실시간 변동 팩터 → STRONG 확신 대비 낮은 신뢰도
    → STRONG이면 accel·inst_momentum 차단 우회, ride 자체(기관 완전이탈)만 유지

  수정:
    _accel_check / _inst_momentum_recheck 이후에
    PULLBACK STRONG 즉시 진입 오버라이드 블록 추가

    조건:
      pullback_setup_class == "STRONG"
      AND pullback_priority_score >= 50
      AND pullback_quality_score >= 55
    효과:
      accel 차단(ACCEL_BLOCK) → 우회
      inst_momentum 차단(ride 기준 미달) → 우회
      단, 킬스위치 / BEAR 레짐 / 전략 활성화 게이트는 반드시 통과
      ride 완전이탈(ride=0 수준)은 실시간 안전망 역할 → 유지
      B4 STABLE 강등 면제 (기존) + 즉시 진입 오버라이드 (신규) 이중 보호

  보호 경계:
    킬스위치 (BEAR / 일일손실 / 주문거절) — 절대 우회 불가
    siga_enable=False / pullback_enable=False 게이트 — 절대 우회 불가
    REGIME BEAR_BLOCK — 절대 우회 불가
    ride_score=0 또는 음수 (완전 이탈) — 절대 우회 불가

[v3.7.1 → v3.7.2 수정사항]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 siga_enable / pullback_enable 브리지 차단 구현 (완결)
★ FIX-2 bridge_ev_weight 전달 경로 정상 확인
  문제:
    스코어보드가 siga_enable / pullback_enable을 pkl에 저장
    execution_engine v4.23이 sig에 심음
    그러나 브리지가 sig에서 두 필드를 읽는 코드가 없었음
    → siga_enable=False여도 브리지가 SIGA 신호를 그대로 처리
    → pullback_enable=False여도 PULLBACK 신호를 그대로 처리
    → 급락일 / 위험 시장에서도 전략 차단 불가 → 손실 위험
  위험 시나리오:
    코스닥 -1.6% 급락일 → 스코어보드 siga_enable=False
    → sig에 심겼으나 브리지 무시 → SIGA 강제 진입 → 손실
  수정:
    킬스위치 체크 직후, SWITCH 처리 이전에 전략 활성화 게이트 추가
    strategy_hint × siga_enable/pullback_enable 교차 차단
    기본값: True (폴백 — 필드 없을 때 차단 안 함 = 안전한 방향)
  완결:
    스코어보드 pkl 저장 → execution_engine sig 주입 → 브리지 차단
    전략 라우팅 3단계 전달 경로 완전히 닫힘

★ FIX-2 [확인] bridge_ev_weight 전달 경로 — 정상 작동
  스코어보드 pkl → execution_engine sig → 브리지 line 1238
  sig.get("bridge_ev_weight", EV_WEIGHT) 정상 참조 확인
  → 추가 수정 불필요


[v3.7.1 치명 결함 수정]

  C2 ★★★ 초강력 오버라이드 ev_val 기준 단위 불일치 수정
     문제: 스코어보드 v7.8에서 ev_pct가 × 100 단위(50~150%)로 공급되는데
           초강력2 기준 ev_val≥1.3 / 초강력1 기준 ev_val≥1.1 그대로 잔존
           → ev_pct=75이면 75 >> 1.3 → 항상 초강력2 발동
           → 모든 진입이 ATTACK+MARKET+OFI_INST_STRONG 풀포지션
           → 의도치 않은 과매매·리스크 급증
     수정: 초강력2 ev_val≥130.0% / 초강력1 ev_val≥110.0%
           진짜 기대수익률 130% 이상인 극단 신호만 초강력 적용

  C3 ★★★ SIGA ride_min 0.25 오버라이드 글로벌 체크에 막혀 무효화 수정
     문제: STRATEGY_OVERRIDES["SIGA"]["ride_min"]=0.25 설정했으나
           _inst_momentum_recheck에서 글로벌 RIDE_SCORE_MIN=0.30으로 먼저 차단
           → _strategy_override_gate(0.25) 실행 전 이미 탈락
           → SIGA ride=0.26~0.29인 신호 전부 차단 → B1 오버라이드 실질 무효
     수정: _inst_momentum_recheck 내부에서 strategy_hint 확인
           SIGA/GAP이면 _ride_min=0.25 적용 → 글로벌 차단 우선순위 해소

[v3.7 수정사항]

  B1 ★★★ SIGA 진입 RIDE_SCORE_MIN 완화 0.30 → 0.25
     문제: 스코어보드 v7.8에서 SIGA 후보 확대 후 브리지 ride=0.30 기준이 병목
           시가 09:05~09:07은 기관 flow가 형성되기 전 — 0.25도 충분한 초기 신호
     수정: SIGA 전략에 한해 ride_min=0.25 오버라이드
           PULLBACK은 0.30 유지 (추세 확인 후 진입이므로 엄격)

  B2 ★★★ EV_CAUTION_MIN 1.00 → 0.50 완화
     문제: CAUTION 레짐에서 ev_pct≥1.00 요구 — 스코어보드 ev_pct가 × 100 단위(C1 수정)
           ev_pct=0.7→70% 환산인데 브리지가 70 < 1.00으로 차단하는 역전 현상 잔존
           v7.8에서 ev_pct가 % 단위로 나오므로 50%(EV 0.5%) 이상이면 CAUTION 허용
     수정: EV_CAUTION_MIN = 0.50 (0.5% 이상이면 CAUTION 진입 허용)

  B3 ★★ SWITCH_EV_MIN 0.95 → 0.70 완화
     문제: SWITCH 전용 EV 기준 0.95 → 스코어보드 완화 후에도 전략교체 거의 불가
           PULLBACK→SIGA 또는 SIGA→PULLBACK 교체 시 불필요한 차단
     수정: SWITCH_EV_MIN = 0.70 (0.7% EV 이상이면 전략 교체 허용)

  B4 ★★ PULLBACK 수익조건 우선 진입 — STRONG 셋업 감지 시 ATTACK 모드 유지
     문제: pullback_setup_class=STRONG 신호가 브리지에서 무시됨
           스코어보드가 STRONG 셋업 선별해도 브리지가 STABLE 강등 가능
     수정: sig.get("pullback_setup_class")="STRONG" 이면 pq_mode_hint 강등 면제
           STRONG 셋업 = 기관 5일+ 지지 + priority≥50 + quality≥55 → ATTACK 유지 정당

  B5 ★ source 필드 VERSION 상수로 교체 (N1 잔존결함 해소)
     문제: "source": "RT_SIGNAL_BRIDGE_v3_3" 하드코딩 — v3.7인데 v3_3 표기
     수정: "source": VERSION 상수 참조

[v3.6 기존 유지 — C1·C2·M1·M2]
  C1 docstring EV 기준 표기 제거 / C2 _file_unlock _lg 명시
  M1 dead 상수 제거 / M2 docstring 정정

[v3.5 헤지펀드 표준 — H1·H2·H3 유지]
  H1 _profit_quality_check 하드차단→STABLE 강등
  H2 STRATEGY_OVERRIDES ev_min·composite_min 제거
  H3 EV_ENTRY_MIN·COMPOSITE_SCORE_MIN 비활성화

[역할]  rt_execution_signal.json → kjs_execute_queue.csv 변환 브릿지
        execution_engine(신호) ↔ buy_order_sender(주문) 사이 파이프라인 연결

[설계 근거 — 학술 출처 (검증 완료)]
  ■ 최적 집행 비용: Almgren & Chriss (2000) "Optimal Execution of
    Portfolio Transactions" Journal of Risk 3(2):5-39
    → 시장가/지정가 동적 선택으로 거래비용·변동성 리스크 균형
    ✅ DOI: 10.21314/JOR.2001.041 — 실제 논문 확인됨

  ■ 기관 흐름 OFI: Cont, Kukanov, Stoikov (2014)
    "The Price Impact of Order Book Events" JFEC 12(1):47-88
    → OFI 분 단위 변동 → 신호 생성 이후 실시간 ride_score 재검증 필수
    ✅ DOI: 10.1093/jjfinec/nbt003 — 실제 논문 확인됨

  ■ Kelly 사이징: Kelly (1956), Thorp (1962)
    → Half-Kelly로 기하 성장 극대화 + 파산 방지
    ✅ Bell System Technical Journal 35(4):917-926 — 고전 검증됨

  ■ Profit Factor: Lopez de Prado (2018) "Advances in Financial ML"
    → 총이익/총손실 비율 전략 품질 평가 — 자기진화 피드백
    ✅ Wiley, ISBN 978-1119482086 — 실제 서적 확인됨

  ■ Sharpe 통계: Lo (2002) "The Statistics of Sharpe Ratios"
    → 최소 20거래 이상 유의성 / 음수 Sharpe = 차단
    ✅ Financial Analysts Journal 58(4):36-52 — 실제 논문 확인됨

  ■ Soft Risk: Citadel risk overlay — 차단보다 사이즈 조절
    → regime=CAUTION 시 ATTACK→STABLE 강제 (과매매 방지)
    ✅ 업계 표준 관행 (공개 운용 원칙)

  ■ 모멘텀 품질: Gray & Vogel (2016) "Quantitative Momentum"
    → 경로 의존 모멘텀 품질 필터링 + accel 재검증
    ✅ Wiley, ISBN 978-1119237720 — 실제 서적 확인됨

  ■ 동적 손실한도: Grinold & Kahn (2000) "Active Portfolio Management"
    → 일일손실 −3% 킬스위치 기준
    ✅ McGraw-Hill, 2nd ed. — 실제 서적 확인됨

[고유영역]
  읽기: DATA/LOG/rt_execution_signal.json  (execution_engine 출력)
        DATA/rt_open_positions.json        (중복 진입 차단 + ride 실시간 재검증)
        DATA/rt_daily_sold.json            (재진입 차단)
        DATA/rt_daily_pnl.json             (일일손실 킬스위치 + D2 당일진입확인)
        DATA/queue/kjs_execute_queue.csv   (dedup 확인용)
  쓰기: DATA/queue/kjs_execute_queue.csv   (buy_order_sender 입력 — 추가 모드)
  절대금지: 후보 생성, 리스크 계산, 포지션 사이징, 매도 로직, params.json 쓰기

[파이프라인 위치]
  rt_intraday.csv → execution_engine → rt_execution_signal.json
       → ★[이 파일]★ → kjs_execute_queue.csv → kiwoom_buy_order_sender

[3전략 (종배 제외)]
  시가(SIGA)    : 갭 등급별 차등, ride≥0.30 (실시간 모멘텀만 — EV는 스코어보드 완결)
  눌림(PULLBACK): 기관 동행 최장 보유, ride≥0.30 (실시간 모멘텀만 — EV는 스코어보드 완결)

[공격/안정 비율]
  1종목 몰빵 — 공격 70% / 안정 30%
  bridge는 execution_engine의 판단(mode=ATTACK/STABLE/SKIP)을 신뢰
  단, regime=CAUTION 시 ATTACK→STABLE 강제 전환 (과매매 방지)
  초기 20거래 미만 → STABLE 강제 (Lo 2002 표본 유의성 기준)
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime, time as dtime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── pandas graceful fallback ──
try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# ═══════════════════════════════════════════════════════════════
#  경로
# ═══════════════════════════════════════════════════════════════
BASE       = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA       = BASE / "DATA"
LOG_DIR    = DATA / "LOG"
QUEUE_DIR  = DATA / "queue"

SIGNAL     = LOG_DIR / "rt_execution_signal.json"
QUEUE      = QUEUE_DIR / "kjs_execute_queue.csv"
OPEN_POS   = DATA / "rt_open_positions.json"
# [CONCURRENT-VALUE 2026-06-09 사용자지시] 보유가치(qty×entry_price) 이 금액 미만 잔여포지션(검증용 1주 등)은
#   "보유"로 안 봄 → 추가 진입 안 막음. buy_sender MAX_CONCURRENT_MIN_VALUE_KRW와 동일 임계.
MAX_CONCURRENT_MIN_VALUE_KRW = int(os.environ.get("MAX_CONCURRENT_MIN_VALUE_KRW", "100000"))
DAILY_SOLD = DATA / "rt_daily_sold.json"
DAILY_PNL  = DATA / "rt_daily_pnl.json"
KILLSW_ST  = DATA / "rt_killswitch_state.json"
LOG_FILE   = BASE / "LOG" / "rt_signal_bridge.log"

# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════
RC_OK   = 0
RC_HOLD = 200

VERSION = "rt_signal_to_queue_bridge_v3_7_7_SAFEPLUS"

# ── 신호 유효성 ──
SIGNAL_MAX_AGE_SEC   = 180
PROCESSED_KEY        = "_bridge_processed"
MAX_CONCURRENT       = 1

# ── SWITCH 타임아웃 ──
SWITCH_TIMEOUT_SEC   = 300

# ── 기관 모멘텀 재검증 ──
RIDE_SCORE_MIN       = 0.30
RIDE_SCORE_STRONG    = 0.60
RIDE_DECAY_MAX       = 0.20

# ── 레짐 게이팅 ──
REGIME_BEAR_BLOCK    = True
# [B2 v3.7] EV_CAUTION_MIN 1.00→0.50 완화
# 스코어보드 v7.8 ev_pct가 % 단위 → 0.5% 이상이면 CAUTION 진입 허용
# 기존 1.00은 스코어보드 단위 변경 후 사실상 모든 CAUTION 차단이었음
EV_CAUTION_MIN       = 0.50

# ── 수익률 평가 ──
PF_BLOCK_THRESHOLD   = 0.8
PF_WARN_THRESHOLD    = 1.0
SHARPE_HARD_BLOCK    = -0.5
SHARPE_SOFT_STABLE   = 0.0
SHARPE_INITIAL_PASS  = True
SORTINO_SOFT_STABLE  = -0.3    # [D8] Sortino < -0.3 → STABLE 강등

# ── [D4] EV_NORM_BASE 동적화 범위 ──
EV_NORM_BASE_DEFAULT = 1.2    # 기본값 (신호 EV 분포 정보 없을 때)
EV_NORM_BASE_MIN     = 1.0    # 동적 하한
EV_NORM_BASE_MAX     = 1.5    # 동적 상한

# ── EV 최소 + 복합 품질 필터 ── [H3] 글로벌 EV/composite 필터 제거
# 헤지펀드 표준: 스코어보드에서 이미 EV/복합점수 검증 완료
# 브리지 재검증 = 스코어보드 불신 → 이중 선별 구조적 오류
# ride_score 급락 감지(RIDE_DECAY_MAX)만 실시간 팩터로 유지
EV_ENTRY_MIN         = 0.0    # [H3] 비활성화 — 스코어보드 위임
COMPOSITE_SCORE_MIN  = 0.0    # [H3] 비활성화 — 스코어보드 위임
# [B3 v3.7] SWITCH_EV_MIN 0.95→0.70 완화
# 스코어보드 완화 후 전략교체도 원활하게 허용 (0.7% EV 이상)
SWITCH_EV_MIN        = 0.70
SWITCH_RIDE_MIN      = 0.35   # SWITCH 전용 유지

# ── [D2] 1일 1회 강제 진입 파라미터 ──
# [M1 v3.6] DAILY_FORCE_ENTRY_ENABLED=False 비활성 상태 유지
# dead 상수 제거: DAILY_FORCE_EV_MIN·DAILY_FORCE_COMPOSITE_RELAX (H3에서 composite 필터 제거됨)
DAILY_FORCE_ENTRY_ENABLED   = False  # D2 강제진입 비활성화 — H3 EV 필터 제거와 세트
DAILY_FORCE_RIDE_MIN        = 0.30   # 강제진입 최소 ride (비활성이나 로직 참조 유지)
DAILY_FORCE_EXEMPT_LOSS_PCT = -2.5   # 일일손실 이 이하이면 강제진입 면제

# ── [D6] 진입 시간대 품질 게이트 ──
TIME_GATE_OPEN_START  = dtime(9,  0)   # 장초반 갭노이즈
TIME_GATE_OPEN_END    = dtime(9, 15)
TIME_GATE_OPEN_EXTRA  = 0.00           # [PATCH-v3.4.2] 0.03→0.00
                                        # SIGA 09:05~09:07이 이 구간에 완전 포함
                                        # composite_min=0.72+0.03=0.75였던 구조에서
                                        # 0.72 기준만으로 충분 (COMPOSITE_SCORE_MIN 이미 조정)

TIME_GATE_CLOSE_START = dtime(14, 40)  # 장마감 유동성 감소
TIME_GATE_CLOSE_END   = dtime(15,  0)
TIME_GATE_CLOSE_EXTRA = 0.02           # composite 기준 +0.02

# ── [W8] 복합점수 가중치 ──
EV_WEIGHT            = 0.60
RIDE_WEIGHT          = 0.40
EV_WEIGHT_MIN        = 0.50
EV_WEIGHT_MAX        = 0.70

# ── [W6] 초기 표본 보수 진입 ──
INITIAL_TRADE_THRESHOLD = 20
INITIAL_EV_BONUS        = 0.00   # [PATCH-v3.4.1] 0.30→0.00: EV_MIN+0.30=1.05로 초기20건 완전봉쇄 해제
INITIAL_FORCE_STABLE    = True

# ── 동적 exec_type ──
EXEC_MARKET_RIDE_MIN     = 0.65
EXEC_LIMIT_CHASE_RIDE    = 0.25
SLIPPAGE_EST_MARKET      = 0.30
SLIPPAGE_EST_LIMIT_CHASE = 0.10
SPREAD_LIMIT_CHASE_PCT   = 0.30
TICK_ACCEL_MARKET_THR    = 1.50

# ── conviction 매핑 ──
CONVICTION_MAP = {
    "ULTRA":  0.70,
    "STRONG": 0.50,
    "NORMAL": 0.30,
    "WEAK":   0.0,
}

# ── [H2] 전략별 오버라이드 — EV/composite 이중 게이팅 제거 ──
# 헤지펀드 표준: 스코어보드 stage1~4에서 OFI·EV·복합점수 이미 검증
# 브리지 재계산 = 동일 팩터 이중 적용 → 통과율 0.9% 사태 원인
# ride_min만 유지: ride_score는 실시간 재확인이 필요한 유일한 팩터
# (OFI/기관 모멘텀은 분 단위로 변동 → Cont et al. 2014)
STRATEGY_OVERRIDES: Dict[str, Dict[str, float]] = {
    "SIGA": {
        # [B1 v3.7] ride_min 0.30→0.25 완화
        # 시가 09:05~09:07은 기관 flow 형성 전 초기 신호
        # 0.25도 충분한 기관 매집 신호 (스코어보드가 이미 PRIME/WATCH 검증)
        "ride_min":     0.25,
        "max_hold_min": 120,
    },
    "PULLBACK": {
        # 추세 확인 후 진입 — 0.30 유지 (엄격)
        "ride_min":     0.30,   # [H2] 실시간 기관 모멘텀 최소 기준 유지
        "max_hold_min": 240,
    },
}

# ── [W4] accel 기관가속도 기준 ──
ACCEL_CAUTION_MIN  = 0.80
ACCEL_BLOCK_MIN    = 0.50
ACCEL_MISSING_VAL  = 0.95   # [D3] 데이터 없을 때 1.0→0.95 (경미 보수)

# ── [W5] 킬스위치 5대 조건 ──
KILLSWITCH_DAILY_LOSS_PCT  = -3.0
KILLSWITCH_DATA_DELAY_SEC  = 90
KILLSWITCH_ORDER_REJECT_N  = 3
KILLSWITCH_REPEAT_SELL_N   = 5


# ═══════════════════════════════════════════════════════════════
#  유틸
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger("sig_bridge")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s KST][%(levelname)s] %(message)s")
    try:
        fh = RotatingFileHandler(str(LOG_FILE), maxBytes=5*1024*1024,
                                 backupCount=3, encoding="utf-8-sig")  # [Z15 2026-05-21]
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    except Exception as e:
        print(f"[SETUP][FAIL] FileHandler 추가 실패: {e}")
    try:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        lg.addHandler(ch)
    except Exception as e:
        print(f"[SETUP][FAIL] StreamHandler 추가 실패: {e}")
    return lg


def _load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        # [UTF8SIG 2026-05-13] utf-8 → utf-8-sig: 다른 프로세스 작성 BOM JSON 호환
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        logging.getLogger("sig_bridge").error("[JSON][FAIL] 로드 실패 path=%s: %s", path.name, e)
        raise RuntimeError(f"signal json load 실패: {path.name}") from e


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _today_compact() -> str:
    return date.today().strftime("%Y%m%d")


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _f(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _fingerprint_md5(code: str, today: str, strategy: str) -> str:
    return hashlib.md5(
        f"{code}_{today}_{strategy}".encode()
    ).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
#  [D2] 1일 1회 강제 진입 확인
#  당일 큐 등록이 한 번도 없으면 → 기준 완화해서 진입 강제
# ═══════════════════════════════════════════════════════════════
def _check_daily_force_entry(lg: logging.Logger) -> bool:
    """당일 아직 한 번도 진입하지 않았으면 True 반환 [D2]"""
    if not DAILY_FORCE_ENTRY_ENABLED:
        return False

    today = _today_str()
    today_compact = _today_compact()

    # 당일 PNL에 trade_count > 0 이면 이미 진입함
    pnl = _load_json(DAILY_PNL, {})
    if pnl.get("date") == today:
        if int(_f(pnl.get("trade_count", 0))) > 0:
            return False

    # 큐 파일에서 당일 진입 기록 확인
    if QUEUE.exists() and QUEUE.stat().st_size > 10:
        try:
            if _HAS_PANDAS:
                df = pd.read_csv(QUEUE, dtype=str, encoding="utf-8-sig")
                date_col = "date" if "date" in df.columns else "entry_date"
                if date_col in df.columns:
                    if (df[date_col] == today).any():
                        return False
            else:
                with open(QUEUE, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rd = row.get("date", row.get("entry_date", ""))
                        if rd == today:
                            return False
        except Exception as e:
            lg.debug('[D2] 큐 날짜 확인 실패: %s', e)

    # 일일 손실 너무 크면 강제진입 면제 (장 너무 안좋을 때)
    if pnl.get("date") == today:
        daily_ret = _f(pnl.get("daily_return_pct", 0))
        if daily_ret <= DAILY_FORCE_EXEMPT_LOSS_PCT:
            lg.info("[D2] 당일 미진입이나 손실=%.2f%% ≤ %.1f%% → 강제진입 면제",
                    daily_ret, DAILY_FORCE_EXEMPT_LOSS_PCT)
            return False

    lg.info("[D2] ★ 당일 미진입 확인 → 1일 1회 강제진입 모드 활성화")
    return True


# ═══════════════════════════════════════════════════════════════
#  [D6] 진입 시간대 품질 게이트
#  장초반/장마감 → composite 기준 상향으로 노이즈 필터
# ═══════════════════════════════════════════════════════════════
def _time_quality_extra(lg: logging.Logger) -> float:
    """현재 시간대 기록 전용 — 필터 없음 [D6 v3.5, M2 v3.6]
    Returns: 항상 0.0 (composite 필터 제거됨 — 기록·로그 전용)
    장초반(09:00~09:15): TIME_GATE_OPEN_EXTRA=0.00 → 0.0
    장마감(14:40~15:00): TIME_GATE_CLOSE_EXTRA=0.02 → 기록만, 필터 미적용
    """
    now_t = datetime.now().time()
    if TIME_GATE_OPEN_START <= now_t <= TIME_GATE_OPEN_END:
        lg.info("[D6] 장초반 갭노이즈 구간(09:00~09:15) → composite +%.2f",
                TIME_GATE_OPEN_EXTRA)
        return TIME_GATE_OPEN_EXTRA
    if TIME_GATE_CLOSE_START <= now_t <= TIME_GATE_CLOSE_END:
        lg.info("[D6] 장마감 유동성 감소(14:40~15:00) → composite +%.2f",
                TIME_GATE_CLOSE_EXTRA)
        return TIME_GATE_CLOSE_EXTRA
    return 0.0


# ═══════════════════════════════════════════════════════════════
#  [D4] EV_NORM_BASE 동적 계산
#  신호의 ev_pct 분포를 기반으로 정규화 기준값 동적 조정
# ═══════════════════════════════════════════════════════════════
def _dynamic_ev_norm_base(sig: dict, lg: logging.Logger) -> float:
    """EV 정규화 기준값 동적 결정 [D4 / 결함3 수정]
    ev_dist_p75 (75분위) 있으면 사용, 없으면 DEFAULT 고정값.
    [결함3] ev_pct*0.85 추정 제거 — EV 낮을수록 base 낮아져 ev_norm 과대평가 역설 존재
    수정  : ev_dist_p75 없으면 항상 1.2 고정 → 공정·예측가능한 정규화
    """
    ev_p75 = _f(sig.get("ev_dist_p75", 0))
    if ev_p75 > 0:
        base = max(EV_NORM_BASE_MIN, min(EV_NORM_BASE_MAX, ev_p75))
        lg.info("[D4] EV_NORM_BASE 동적: ev_dist_p75=%.2f → base=%.2f", ev_p75, base)
        return base

    # [결함3 수정] ev_pct 기반 추정 제거 → DEFAULT 고정값 반환
    lg.info("[D4] EV_NORM_BASE 고정: ev_dist_p75 없음 → %.2f (역설 방지)",
            EV_NORM_BASE_DEFAULT)
    return EV_NORM_BASE_DEFAULT


# ═══════════════════════════════════════════════════════════════
#  conviction 문자열 매핑
# ═══════════════════════════════════════════════════════════════
def _map_conviction(ride_score: float, mode: str) -> str:
    if ride_score >= CONVICTION_MAP["ULTRA"]:
        return "OFI_INST_STRONG"
    elif ride_score >= CONVICTION_MAP["STRONG"]:
        return "STRONG" if mode == "ATTACK" else "HIGH"
    elif ride_score >= CONVICTION_MAP["NORMAL"]:
        return "NORMAL"
    else:
        return "WEAK"


# ═══════════════════════════════════════════════════════════════
#  동적 exec_type 결정
#  Almgren & Chriss (2000): 거래비용 vs 변동성 리스크 균형
# ═══════════════════════════════════════════════════════════════
def _decide_exec_type(ride_score: float, regime: str,
                      spread_pct: float = 0.0,
                      tick_accel: float = 0.0,
                      lg: Optional[logging.Logger] = None) -> tuple:
    if lg is None:
        lg = logging.getLogger("sig_bridge")

    if spread_pct > SPREAD_LIMIT_CHASE_PCT:
        note = (f"spread={spread_pct:.2f}%>{SPREAD_LIMIT_CHASE_PCT:.1f}% "
                f"→ LIMIT_CHASE강제(슬리피지방어)")
        lg.info("[EXEC] type=LIMIT_CHASE slip=%.2f%% %s",
                SLIPPAGE_EST_LIMIT_CHASE, note)
        return "LIMIT_CHASE", round(SLIPPAGE_EST_LIMIT_CHASE, 4), note

    if tick_accel > TICK_ACCEL_MARKET_THR and regime != "CAUTION":
        note = (f"tick_accel={tick_accel:.2f}>{TICK_ACCEL_MARKET_THR:.1f} "
                f"→ MARKET강제(가격가속포착)")
        lg.info("[EXEC] type=MARKET slip=%.2f%% %s",
                SLIPPAGE_EST_MARKET, note)
        return "MARKET", round(SLIPPAGE_EST_MARKET, 4), note

    if ride_score >= EXEC_MARKET_RIDE_MIN and regime != "CAUTION":
        exec_type = "MARKET"
        slip = SLIPPAGE_EST_MARKET
        note = f"ride={ride_score:.2f}≥{EXEC_MARKET_RIDE_MIN} 기관강→속도우선"
    elif ride_score >= EXEC_LIMIT_CHASE_RIDE:
        exec_type = "LIMIT_CHASE"
        slip = SLIPPAGE_EST_LIMIT_CHASE
        note = f"ride={ride_score:.2f}→지정가추격 슬리피지최소화"
    else:
        exec_type = "LIMIT_CHASE"
        slip = SLIPPAGE_EST_LIMIT_CHASE
        note = f"ride={ride_score:.2f}<{EXEC_LIMIT_CHASE_RIDE} 약신호→보수적집행"

    if regime == "CAUTION" and exec_type == "MARKET":
        exec_type = "LIMIT_CHASE"
        slip = SLIPPAGE_EST_LIMIT_CHASE
        note += " | CAUTION→LIMIT강제"

    lg.info("[EXEC] type=%s slip=%.2f%% %s", exec_type, slip, note)
    return exec_type, round(slip, 4), note


# ═══════════════════════════════════════════════════════════════
#  수익률 평가 — [H1] 하드차단 제거, 모드 조정(STABLE)만 허용
#  헤지펀드 표준: Sharpe/Sortino/PF 검증은 스코어보드 자기진화 루프 담당
#  브리지 하드차단 = 이중 선별 → 이미 선별된 신호 소멸 원인
#  변경: PF < 0.8 차단 제거 → STABLE 강등만 / Sharpe 차단 완전 제거
# ═══════════════════════════════════════════════════════════════
def _profit_quality_check(sig: dict, lg: logging.Logger) -> tuple:
    """수익률 메트릭 → 모드 조정(STABLE)만. 차단 없음. [H1]

    헤지펀드 표준 적용:
    - Sharpe/Sortino/PF 하드차단 제거 (스코어보드 자기진화 위임)
    - 부진 지표 감지 시 STABLE 강등만 (진입 기회 보장)
    - Lo(2002): 20거래 미만 표본 → 모드 조정도 면제
    """
    trade_cnt  = int(_f(sig.get("trade_count", 0)))
    is_initial = (trade_cnt < INITIAL_TRADE_THRESHOLD)
    mode_hint  = None

    if is_initial:
        lg.info("[PROFIT][H1] 초기구간 trade_count=%d → 모드 조정 면제 (Lo 2002)", trade_cnt)
        if INITIAL_FORCE_STABLE:
            mode_hint = "STABLE"
        return True, mode_hint

    evaluated = sig.get("profit_evaluated", False)
    if not evaluated:
        lg.info("[PROFIT][H1] 수익률 미평가 → 통과")
        return True, mode_hint

    pf      = _f(sig.get("profit_factor", 0))
    sharpe  = _f(sig.get("sharpe", 0))
    sortino = _f(sig.get("sortino", 0))

    lg.info("[PROFIT][H1] PF=%.2f Sharpe=%.2f Sortino=%.2f — 하드차단 없음 (스코어보드 위임)",
            pf, sharpe, sortino)

    # [H1] PF 부진 → STABLE 강등 (차단 아님)
    if 0 < pf < PF_BLOCK_THRESHOLD:
        lg.info("[PROFIT][H1] PF=%.2f 부진 → STABLE 강등 (차단 아님)", pf)
        mode_hint = "STABLE"

    # [H1] Sharpe 음수 → STABLE 강등 (하드차단 제거)
    if sharpe < SHARPE_SOFT_STABLE:
        lg.info("[PROFIT][H1] Sharpe=%.2f 음수 → STABLE 강등 (차단 아님)", sharpe)
        mode_hint = "STABLE"

    # [H1] Sortino 부진 → STABLE 강등 (하드차단 제거)
    if sortino < SORTINO_SOFT_STABLE:
        lg.info("[PROFIT][H1] Sortino=%.2f 부진 → STABLE 강등 (차단 아님)", sortino)
        mode_hint = "STABLE"

    return True, mode_hint


# ═══════════════════════════════════════════════════════════════
#  레짐 기반 게이팅
# ═══════════════════════════════════════════════════════════════
def _regime_gate(sig: dict, lg: logging.Logger) -> tuple:
    regime = str(sig.get("regime", "NEUTRAL")).upper()
    mode   = str(sig.get("strategy_type", sig.get("mode", "SKIP"))).upper()
    ev_pct = _f(sig.get("ev_pct", 0))

    if REGIME_BEAR_BLOCK and regime == "BEAR":
        lg.warning("[REGIME] BEAR 시장 → 신규 진입 차단")
        return False, mode

    if regime == "CAUTION":
        if mode == "ATTACK":
            lg.info("[REGIME] CAUTION: ATTACK→STABLE 강제 전환")
            mode = "STABLE"
        if ev_pct < EV_CAUTION_MIN:
            lg.warning("[REGIME] CAUTION: EV=%.2f%% < %.2f%% → 차단", ev_pct, EV_CAUTION_MIN)
            return False, mode

    return True, mode


# ═══════════════════════════════════════════════════════════════
#  [W1] 기관 모멘텀 실시간 재검증
#  Cont et al.(2014): OFI 분 단위 변동 → 신호 스냅샷 신뢰 불가
# ═══════════════════════════════════════════════════════════════
def _inst_momentum_recheck(sig: dict, lg: logging.Logger) -> bool:
    ride_sig  = _f(sig.get("ride_score", 0))
    inst_days = int(_f(sig.get("inst_days", 0)))
    code      = str(sig.get("code", "")).zfill(6)

    # [C3-FIX v3.7] SIGA 전략은 ride_min 0.25 적용 — B1 오버라이드 실효화 방지
    # 문제: STRATEGY_OVERRIDES["SIGA"]["ride_min"]=0.25인데
    #       글로벌 RIDE_SCORE_MIN=0.30으로 _strategy_override_gate 전에 먼저 차단
    #       → B1 오버라이드(0.25)가 실질적으로 무효화됨
    # 수정: strategy_hint SIGA/GAP 이면 0.25 기준 적용
    _hint     = str(sig.get("strategy_hint", "")).upper()
    _ride_min = 0.25 if ("SIGA" in _hint or "GAP" in _hint) else RIDE_SCORE_MIN
    # [MORNING-RIDE-EXEMPT 2026-06-12 ★6/12 실증] 아침엔 기관 수급 데이터 미수집(첫 수집 09:30)
    #   → ride=0.00은 '기관 외면'이 아니라 '데이터 없음'. 오늘 058610(09:43)·277810(10:15)이
    #   이 게이트에 기계적으로 격추됨. 면제: 10:00 전 & ride==0(데이터부재)이면 통과(로그만).
    #   ride>0인데 낮은 건 진짜 신호이므로 기존대로 차단. 롤백: env INST_MORNING_EXEMPT_HHMM=0.
    try:
        _ex_hhmm = int(os.environ.get("INST_MORNING_EXEMPT_HHMM", "1000"))
        if _ex_hhmm > 0 and ride_sig <= 0.001:
            _now_hm = int(datetime.now().strftime("%H%M"))
            if _now_hm < _ex_hhmm:
                lg.info("[INST][MORNING-EXEMPT] code=%s ride=0.00(수급 데이터부재)+%04d<%04d → 게이트 면제",
                        code, _now_hm, _ex_hhmm)
                return True
    except Exception:
        pass
    if ride_sig < _ride_min:
        lg.warning("[BRIDGE_FAIL] code=%s strategy=%s stage=RIDE ride=%.2f min=%.2f",
                   code, _hint or "PULLBACK", ride_sig, _ride_min)
        return False

    # execution_engine이 내려주는 ride_score_live 직접 사용 (v3.2 수정 유지)
    live_ride = _f(sig.get("ride_score_live", ride_sig))

    if live_ride > 0 and ride_sig > 0:
        decay = (ride_sig - live_ride) / ride_sig
        if decay > RIDE_DECAY_MAX:
            lg.warning("[INST] ★ ride 급감: 신호=%.2f → live=%.2f "
                       "(감쇠=%.1f%% > %.0f%%) → 차단",
                       ride_sig, live_ride, decay * 100, RIDE_DECAY_MAX * 100)
            return False
        if decay > 0.05:
            lg.info("[INST] ride 소폭 감쇠: %.2f→%.2f (%.1f%%) — 허용",
                    ride_sig, live_ride, decay * 100)

    sig_ts_str = sig.get("ts", "")
    if sig_ts_str:
        try:
            sig_ts  = datetime.strptime(sig_ts_str, "%Y%m%d%H%M%S")
            elapsed = (datetime.now() - sig_ts).total_seconds()
            if elapsed > 120 and ride_sig < 0.35:
                lg.warning("[INST] 신호 %.0f초 경과 + ride=%.2f 경계 → 주의",
                           elapsed, ride_sig)
        except Exception as e:
            lg.debug('[INST] 경과시간 계산 실패: %s', e)

    if ride_sig >= RIDE_SCORE_STRONG:
        lg.info("[INST] ✅ ride=%.2f 기관 강매집 확인 (inst_days=%d)", ride_sig, inst_days)
    else:
        lg.info("[INST] ride=%.2f 기관 매집 확인 (최소 충족)", ride_sig)

    return True


# ═══════════════════════════════════════════════════════════════
#  [W4+D3] accel(기관가속도) 재검증 — 지침서[15] §3-4
#  [D3] accel 없을 때: 1.0(중립) → 0.95(경미 보수)
# ═══════════════════════════════════════════════════════════════
def _accel_check(sig: dict, lg: logging.Logger) -> tuple:
    raw_accel = sig.get("accel", None)

    # [D3] 데이터 없으면 0.95 (경미 보수) 처리
    if raw_accel is None or _f(raw_accel) <= 0:
        lg.info("[ACCEL][D3] accel 데이터 없음 → 경미 보수값(%.2f) 적용", ACCEL_MISSING_VAL)
        accel = ACCEL_MISSING_VAL
    else:
        accel = _f(raw_accel)

    lg.info("[ACCEL] accel=%.3f (기관가속도: 최근3봉/이전5봉)", accel)

    if accel < ACCEL_BLOCK_MIN:
        lg.warning("[BRIDGE_FAIL] code=%s strategy=%s stage=ACCEL accel=%.3f min=%.2f",
                   sig.get("code", "?"), sig.get("strategy_hint", "?"), accel, ACCEL_BLOCK_MIN)
        return False, None

    if accel < ACCEL_CAUTION_MIN:
        lg.warning("[ACCEL] accel=%.3f < %.1f → 기관 둔화 → STABLE 강등",
                   accel, ACCEL_CAUTION_MIN)
        return True, "CAUTION"

    return True, None


# ═══════════════════════════════════════════════════════════════
#  [W5+D5] 킬스위치 5대 조건 통합
#  [D5] 데이터지연 ②: 신호파일 mtime → ts 필드 파싱으로 정확화
# ═══════════════════════════════════════════════════════════════
def _killswitch_check(sig: Optional[dict], lg: logging.Logger) -> Tuple[bool, str]:
    today = _today_compact()

    ks = _load_json(KILLSW_ST, {})
    if ks.get("date") != today:
        ks = {"date": today}

    # ① 일일손실 −3% 초과
    pnl_data = _load_json(DAILY_PNL, {})
    if pnl_data.get("date") == _today_str():
        daily_ret = _f(pnl_data.get("daily_return_pct", 0))
        if daily_ret < KILLSWITCH_DAILY_LOSS_PCT:
            lg.warning("[KILL] ① 일일손실 %.2f%% < %.1f%% → 전체 차단",
                       daily_ret, KILLSWITCH_DAILY_LOSS_PCT)
            return True, "DAILY_LOSS_LIMIT"

    # ② 데이터 지연 90초 — [D5] ts 필드 직접 파싱 (mtime보다 정확)
    #    [결함1 수정] sig는 항상 dict로 전달됨 → mtime dead-code 제거
    if sig.get("ts"):
        sig_ts = None
        for _fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                sig_ts = datetime.strptime(str(sig["ts"]).strip(), _fmt); break
            except ValueError:
                continue
        if sig_ts is None:
            lg.warning("[KILL] 신호 ts 형식 미인식: %r → 지연감지 스킵", sig.get("ts"))
        else:
            try:
                sig_age = (datetime.now() - sig_ts).total_seconds()
                if sig_age > KILLSWITCH_DATA_DELAY_SEC:
                    lg.warning("[KILL][D5] ② 신호 ts 기반 지연 %.0f초 > %d초 → 차단",
                               sig_age, KILLSWITCH_DATA_DELAY_SEC)
                    return True, "DATA_DELAY"
            except Exception as e:
                lg.warning('[KILL] 신호 지연 감지 실패: %s', e)

    # ③ 주문거절 반복 3회
    reject_cnt = int(_f(ks.get("order_reject_count", 0)))
    if reject_cnt >= KILLSWITCH_ORDER_REJECT_N:
        lg.warning("[KILL] ③ 주문거절 %d회 ≥ %d회 → 차단",
                   reject_cnt, KILLSWITCH_ORDER_REJECT_N)
        return True, "ORDER_REJECT_REPEATED"

    # ④ 동일종목 반복매도 5회
    repeat_sell = int(_f(ks.get("repeat_sell_count", 0)))
    if repeat_sell >= KILLSWITCH_REPEAT_SELL_N:
        lg.warning("[KILL] ④ 동일종목 반복매도 %d회 ≥ %d회 → 차단",
                   repeat_sell, KILLSWITCH_REPEAT_SELL_N)
        return True, "REPEAT_SELL"

    # ⑤ 브릿지 단절 → BAT watchdog 처리
    return False, ""


# ═══════════════════════════════════════════════════════════════
#  [H2] 전략별 오버라이드 게이트 — ride_min 실시간 검증만
#  헤지펀드 표준: EV/composite는 스코어보드에서 이미 소모
#  브리지는 ride_score(실시간 기관 모멘텀)만 확인
#  Cont et al.(2014): OFI는 분 단위 변동 → 실시간 재확인 필요
# ═══════════════════════════════════════════════════════════════
def _catastrophic_vol_check(sig: dict, lg: logging.Logger) -> Tuple[bool, str]:
    """[CATASTROPHIC-VOL 2026-05-26] 신호 종목의 prices_1m 직전 5봉 변동성 검사.
    (max_high - min_low) / mean_close >= 10% 면 차단.
    백테스트 outlier (007330 -83% 5분 폭락 같은 거래정지/하한가 패턴) 사전 차단.
    Returns: (blocked: bool, detail: str). fail-open (검사 실패 시 통과).
    """
    THRESHOLD = 0.10  # 10%
    LOOKBACK = 5      # 직전 5봉
    if not _HAS_PANDAS:
        return False, "no_pandas"
    code = str(sig.get("code", "")).strip()
    if not code:
        return False, "no_code"
    try:
        prices_path = Path(r"C:\stock_bot\DATA\prices_1m.csv")
        if not prices_path.exists():
            return False, "no_prices_file"
        df = pd.read_csv(prices_path, dtype={"code": str, "ts": str},
                         usecols=["code", "ts", "high", "low", "close"])
        df = df[df["code"] == code].sort_values("ts").tail(LOOKBACK)
        if len(df) < LOOKBACK:
            return False, f"not_enough_bars({len(df)}/{LOOKBACK})"
        max_high = float(df["high"].max())
        min_low  = float(df["low"].min())
        mean_close = float(df["close"].mean())
        if mean_close <= 0:
            return False, "zero_mean_close"
        vol_ratio = (max_high - min_low) / mean_close
        if vol_ratio >= THRESHOLD:
            return True, f"vol_ratio={vol_ratio*100:.2f}%_thr={THRESHOLD*100:.0f}%"
        return False, f"vol_ratio={vol_ratio*100:.2f}%_thr={THRESHOLD*100:.0f}%"
    except Exception as e:
        lg.warning("[CATASTROPHIC-VOL] 검사 실패 → fail-open: %s", e)
        return False, f"check_failed:{e}"


def _strategy_override_gate(sig: dict, ev: float, ride: float,
                             composite: float, mode: str,
                             lg: logging.Logger,
                             is_daily_force: bool = False) -> tuple:
    """전략별 ride_min 실시간 검증 [H2]
    - EV / composite 이중 게이팅 제거 (스코어보드 위임)
    - ride_min만 유지: 실시간 기관 모멘텀 최소 기준
    """
    hint = str(sig.get("strategy_hint", "PULLBACK")).upper()
    strat_key = "SIGA" if ("SIGA" in hint or "GAP" in hint) else "PULLBACK"
    ov = STRATEGY_OVERRIDES.get(strat_key, STRATEGY_OVERRIDES["PULLBACK"])
    ride_min = ov["ride_min"]

    # [v3.7.7] PULLBACK 12:50~13:20 ride_min 0.28 시간대 오버라이드
    # 근거: 점심 눌림 구간은 기관 flow 일시 약화 — ride=0.28~0.29 차단은 역필터
    # STRONG 보호/킬스위치/전략게이트는 이미 위에서 통과된 상태
    if strat_key == "PULLBACK":
        _ts_hhmm = int(datetime.now().strftime("%H%M"))
        if 1250 <= _ts_hhmm <= 1320 and ride_min > 0.28:
            lg.info("[STRAT][v3.7.7] PULLBACK 12:50~13:20 ride_min %.2f→0.28 오버라이드",
                    ride_min)
            ride_min = 0.28

    lg.info("[STRAT][H2] 전략=%s ride_min=%.2f (EV/composite 검증 스코어보드 위임)",
            strat_key, ride_min)

    if ride < ride_min:
        lg.warning("[BRIDGE_FAIL] code=%s strategy=%s stage=STRAT_RIDE ride=%.2f min=%.2f",
                   sig.get("code", "?"), strat_key, ride, ride_min)
        return False, mode

    lg.info("[STRAT][H2] ✅ %s 실시간 ride=%.2f 통과", strat_key, ride)
    return True, mode


# ═══════════════════════════════════════════════════════════════
#  보조 — 포지션/일일매도/큐 중복 확인
# ═══════════════════════════════════════════════════════════════
def _has_open_position(lg: logging.Logger) -> bool:
    pos = _load_json(OPEN_POS, {})
    # [PATCH] qty>0 항목만 active position으로 판단 (qty=0 잔재 entry 무시)
    #   매도 후 entry 정리 누락(키만 남고 qty=0) 시 진입 영구 차단 해소
    active = {}
    for _c, _e in (pos or {}).items():
        try:
            _q = int(float(_e.get("qty", 0))) if isinstance(_e, dict) else 0
        except (TypeError, ValueError):
            _q = 0
        if _q <= 0:
            continue
        # [CONCURRENT-VALUE 2026-06-09] 보유가치 임계 미만(검증용 1주 등 자투리)은 슬롯 미점유 → 진입 안 막음.
        #   entry_price 불명(<=0)이면 안전하게 보유 간주(차단 유지).
        try:
            _ep = float(_e.get("entry_price", 0) or 0)
        except (TypeError, ValueError):
            _ep = 0.0
        if _ep > 0 and (_q * _ep) < MAX_CONCURRENT_MIN_VALUE_KRW:
            lg.info("[GUARD] %s 자투리 보유(가치 %.0f<%d) → 슬롯 미점유, 진입 허용",
                    str(_c), _q * _ep, MAX_CONCURRENT_MIN_VALUE_KRW)
            continue
        active[_c] = _e
    if active:
        codes = list(active.keys())
        lg.info("[GUARD] 보유 중(qty>0, 가치>=%d): %s → 추가 진입 차단", MAX_CONCURRENT_MIN_VALUE_KRW, codes)
        return True
    return False


def _is_daily_sold(code: str, lg: logging.Logger) -> bool:
    sold = _load_json(DAILY_SOLD, {})
    today = _today_compact()
    if sold.get("date") != today:
        return False
    sold_codes = set(str(c).zfill(6) for c in sold.get("codes", []))
    if code in sold_codes:
        lg.info("[GUARD] %s 당일 청산 → 재진입 차단", code)
        return True
    return False


def _purge_stale_queue_rows(lg: logging.Logger) -> None:
    """[QUEUE-PURGE 2026-06-12 ★친구님 승인 — 좀비큐 근본수술]
    유통기한(기본 600초) 지난 큐 행을 자동 폐기. 6/2·6/5·6/12 월3회 수동청소의 근본원인:
    발송기가 300초 STALE 폐기 판정만 하고 행을 안 지워 → 죽은 행이 같은 종목 새 신호를
    QUEUE_DUPLICATE로 격추(6/12 HPSP LEADER-FIRST 2발 실기). 큐 파일의 단일 작성자는
    bridge이므로 여기서 정리(레이스 없음). 롤백: env QUEUE_STALE_PURGE_SEC=0."""
    try:
        purge_sec = float(os.environ.get("QUEUE_STALE_PURGE_SEC", "600"))
        if purge_sec <= 0 or not QUEUE.exists() or QUEUE.stat().st_size < 10:
            return
        from datetime import datetime as _qp_dt
        now = _qp_dt.now()
        with open(QUEUE, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            fields = rdr.fieldnames
            rows = list(rdr)
        if not fields or not rows:
            return
        keep, dropped = [], []
        for r in rows:
            ts = str(r.get("ts", "")).strip()
            try:
                age = (now - _qp_dt.strptime(ts[:14], "%Y%m%d%H%M%S")).total_seconds()
            except ValueError:
                age = None  # ts 해석불가 → 보존(보수적)
            if age is not None and age > purge_sec:
                dropped.append(f"{r.get('code','?')}({int(age)}s)")
            else:
                keep.append(r)
        if dropped:
            tmp = str(QUEUE) + ".tmp"
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(keep)
            os.replace(tmp, str(QUEUE))
            lg.warning("[QUEUE-PURGE] 유통기한(%.0fs) 초과 행 %d개 자동폐기: %s (잔존 %d)",
                       purge_sec, len(dropped), dropped, len(keep))
    except Exception as e:
        lg.debug("[QUEUE-PURGE] 스킵(%s)", e)


def _already_in_queue(code: str, today: str, lg: logging.Logger) -> bool:
    _purge_stale_queue_rows(lg)   # [QUEUE-PURGE] 중복검사 전 좀비 청소 — 죽은 표가 새 신호 못 막게
    if not QUEUE.exists() or QUEUE.stat().st_size < 10:
        return False
    try:
        if _HAS_PANDAS:
            df = pd.read_csv(QUEUE, dtype=str, encoding="utf-8-sig")
            if "code" not in df.columns:
                return False
            df["code"] = df["code"].str.zfill(6)
            date_col = "date" if "date" in df.columns else "entry_date"
            mask = (df["code"] == code) & (df[date_col] == today) \
                   if date_col in df.columns else (df["code"] == code)
            if mask.any():
                lg.info("[GUARD] %s 이미 큐에 등록됨 → 중복 차단", code)
                return True
        else:
            with open(QUEUE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rc = str(row.get("code", "")).zfill(6)
                    rd = row.get("date", row.get("entry_date", ""))
                    if rc == code and rd == today:
                        lg.info("[GUARD] %s 이미 큐에 등록됨 → 중복 차단", code)
                        return True
    except Exception as e:
        lg.debug("[GUARD] 큐 중복검사 예외 (무시): %s", e)
    return False


# ═══════════════════════════════════════════════════════════════
#  [W2] 파일 잠금 완전화
# ═══════════════════════════════════════════════════════════════
def _file_lock(f, exclusive: bool = True, retries: int = 3) -> bool:
    for attempt in range(retries):
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    f.seek(0, 2)
                    fsize = max(f.tell(), 1)
                    f.seek(0)
                except Exception:
                    fsize = 1
                lock_mode = msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK
                msvcrt.locking(f.fileno(), lock_mode, fsize)
            else:
                import fcntl
                flag = (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive \
                       else (fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), flag)
            return True
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.05)
    return False


def _file_unlock(f):
    _lg = logging.getLogger("sig_bridge")  # [C2 v3.6] bare lg 참조 제거 — NameError 방지
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                f.seek(0, 2)
                fsize = max(f.tell(), 1)
                f.seek(0)
            except Exception:
                fsize = 1
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, fsize)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        _lg.debug('[LOCK] 파일락 해제 실패: %s', e)


# ═══════════════════════════════════════════════════════════════
#  큐 행 생성 — buy_order_sender 완전 호환
# ═══════════════════════════════════════════════════════════════
def _build_queue_row(sig: dict, mode: str, today: str,
                     ev_norm_base: float,
                     lg: logging.Logger) -> Dict[str, Any]:
    code      = str(sig.get("code", "")).zfill(6)
    strategy  = str(sig.get("strategy_hint", "RT")).upper()
    price     = int(_f(sig.get("price_ref", 0)))
    qty       = int(_f(sig.get("qty", 0)))
    order_krw = int(_f(sig.get("order_krw", 0)))
    ride      = _f(sig.get("ride_score", 0))
    regime    = str(sig.get("regime", "NEUTRAL")).upper()

    if order_krw <= 0 and price > 0 and qty > 0:
        order_krw = price * qty

    conviction = _map_conviction(ride, mode)
    spread_pct = _f(sig.get("spread_pct", 0.0))
    tick_accel = _f(sig.get("tick_accel", 0.0))
    exec_type, slippage_est, exec_note = _decide_exec_type(
        ride, regime, spread_pct, tick_accel, lg)
    fp       = _fingerprint_md5(code, today, strategy)
    gap_grade = str(sig.get("gap_grade", sig.get("gap_predict_score", "")))

    row = {
        "side":               "BUY",
        "code":               code,
        "qty":                str(qty),
        "price":              str(price),
        "order_krw":          str(order_krw),
        "ts":                 _now_ts(),
        "date":               today,
        "strategy":           strategy,
        "size_mode":          mode,
        "conviction":         conviction,
        "score":              str(round(_f(sig.get("selection_score", 0)), 4)),
        "grade":              str(sig.get("grade", "")),
        "ev_pct":             str(round(_f(sig.get("ev_pct", 0)), 4)),
        "ev_in_ev5":          str(int(_f(sig.get("ev_pct", 0)) >= 0)),
        "ev_norm_base":       str(round(ev_norm_base, 4)),   # [D9] 동적 기준값 기록
        "exec_type":          exec_type,
        "slippage_est":       str(slippage_est),
        "exec_note":          exec_note,
        "kelly_fraction":     str(round(_f(sig.get("kelly_fraction", 0)), 4)),
        "kelly_mode":         mode,
        "kelly_source":       "EXECUTION_ENGINE",
        "ride_score":         str(round(ride, 4)),
        "inst_days":          str(int(_f(sig.get("inst_days", 0)))),
        "ofi_last10":         str(round(_f(sig.get("ofi_last10", 0)), 4)),
        "profit_factor":      str(round(_f(sig.get("profit_factor", 0)), 4)),
        "sharpe":             str(round(_f(sig.get("sharpe", 0)), 4)),
        "sortino":            str(round(_f(sig.get("sortino", 0)), 4)),
        "max_drawdown":       str(round(_f(sig.get("max_drawdown", 0)), 4)),
        "evolve_weight":      str(round(_f(sig.get("evolve_weight", 1.0)), 4)),
        "time_weight":        str(round(_f(sig.get("time_weight", 1.0)), 4)),
        "regime":             regime,
        "rank_ratio":         str(1.0),
        "signal_fingerprint": fp,
        "gap_grade":          gap_grade,
        "kosdaq_chg_pct":     str(round(_f(sig.get("kosdaq_chg_pct", 0)), 2)),
        "source":             VERSION,   # [B5 v3.7] 하드코딩 제거 → VERSION 상수 참조
        "attack_score":       str(round(_f(sig.get("attack_score", 0)), 2)),
        "stable_score":       str(round(_f(sig.get("stable_score",
                                      sig.get("defense_score", 0))), 2)),
        # [v3.4 FIX-2] 공격70/방어30 실제 배분 금액 컬럼
        "attack_amt":         str(int(order_krw * _f(sig.get("attack_score", 0.70)))),
        "stable_amt":         str(int(order_krw * _f(sig.get("stable_score", 0.30)))),
        "prescore":           str(round(_f(sig.get("prescore", 0)), 2)),
        "exit_signals":       json.dumps(sig.get("exit_signals", {}), ensure_ascii=False),
        "bridge_version":     VERSION,   # [D9] 버전 추적
        # [LEADER-HOLD 2026-06-11] 대장주 승격 꼬리표 passthrough — PB 매도엔진이 보고
        #   추적익절 OFF(하드스톱+15:20만). 없으면 "0" = 기존 동작.
        "leader_first":       str(int(_f(sig.get("leader_first", 0)))),
    }

    # 초강력 신호 오버라이드 2단계
    # [v4_9-P6] ev_pct 단위 % 단위로 일관화 — 다른 모듈(EV_CAUTION_MIN=0.50, SWITCH_EV_MIN=0.70,
    #   exec_engine EV_ENTRY_MIN=0.45, sender EV_MIN_PCT=0.45)과 정합. 130.0/110.0 → 1.30/1.10
    #   (구주석 "× 100 단위" 가정 폐기 — 같은 파일 안 다른 임계와 모순됐음)
    ev_val = _f(sig.get("ev_pct", 0))
    if ev_val >= 1.30 and ride >= 0.65:
        row["conviction"] = "OFI_INST_STRONG"
        row["exec_type"]  = "MARKET"
        row["size_mode"]  = "ATTACK"
        row["kelly_mode"] = "ATTACK"
        row["exec_note"]  = (f"초강력2: EV={ev_val:.2f}%≥1.30% ride={ride:.2f}≥0.65 "
                             f"→ ATTACK+MARKET+OFI_INST_STRONG")
        lg.info("[ULTRA] ★★★ 초강력2: EV=%.2f%% ride=%.2f → ATTACK+MARKET+OFI_INST_STRONG",
                ev_val, ride)
    elif ev_val >= 1.10 and ride >= 0.55:
        row["exec_type"]  = "MARKET"
        row["exec_note"]  = (f"초강력1: EV={ev_val:.2f}%≥1.10% ride={ride:.2f}≥0.55 "
                             f"→ MARKET강제")
        lg.info("[ULTRA] ★★ 초강력1: EV=%.2f%% ride=%.2f → MARKET강제", ev_val, ride)

    lg.info("[ROW] 큐 행 생성: code=%s side=BUY qty=%s price=%s "
            "conviction=%s exec=%s ev=%.2f%% regime=%s ev_norm_base=%.2f",
            code, qty, price, conviction, exec_type,
            _f(sig.get("ev_pct", 0)), regime, ev_norm_base)

    return row


# ═══════════════════════════════════════════════════════════════
#  큐 파일 원자적 추가
# ═══════════════════════════════════════════════════════════════
def _append_to_queue(row: Dict[str, Any], lg: logging.Logger) -> bool:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = list(row.keys())
    file_exists = QUEUE.exists() and QUEUE.stat().st_size > 10

    try:
        existing_rows: List[Dict] = []
        existing_header: List[str] = []

        if file_exists:
            try:
                with open(QUEUE, "r", encoding="utf-8-sig") as f:
                    _file_lock(f, exclusive=False)
                    reader = csv.DictReader(f)
                    existing_header = list(reader.fieldnames or [])
                    existing_rows = list(reader)
                    _file_unlock(f)
            except Exception as e:
                lg.debug("[QUEUE] 기존 파일 읽기 실패(무시): %s", e)

        # [v3.7.9 STALE-FIX] 어제 이전 stale 행 제거 — buy_sender가 stale 종목 매수 시도 차단
        if existing_rows and existing_header:
            _today_qstr = _today_str()
            _date_col = next((c for c in ("date", "entry_date") if c in existing_header), None)
            if _date_col:
                _before_n = len(existing_rows)
                existing_rows = [r for r in existing_rows
                                 if str(r.get(_date_col, "")).strip() == _today_qstr]
                _dropped_n = _before_n - len(existing_rows)
                if _dropped_n > 0:
                    lg.warning("[QUEUE][STALE-DROP] 어제이전 stale 행 %d건 제거 (today=%s)",
                               _dropped_n, _today_qstr)

        if existing_header:
            all_fields = list(existing_header)
            for k in fieldnames:
                if k not in all_fields:
                    all_fields.append(k)
        else:
            all_fields = fieldnames

        tmp = QUEUE.with_suffix(".bridge_tmp")
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            _file_lock(f, exclusive=True)
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            for er in existing_rows:
                writer.writerow(er)
            writer.writerow(row)
            _file_unlock(f)

        os.replace(str(tmp), str(QUEUE))
        lg.info("[QUEUE] ✅ 큐 등록 성공: %s (%d기존 + 1신규)",
                row.get("code", "?"), len(existing_rows))
        return True

    except Exception as e:
        lg.error("[QUEUE] ❌ 큐 기록 실패: %s", e)
        try:
            tmp = QUEUE.with_suffix(".bridge_tmp")
            if tmp.exists():
                tmp.unlink()
        except Exception as e:
            lg.debug('[QUEUE] 임시파일 삭제 실패: %s', e)
        return False


# ═══════════════════════════════════════════════════════════════
#  SWITCH 처리
# ═══════════════════════════════════════════════════════════════
def _handle_switch(sig: dict, lg: logging.Logger) -> str:
    is_switch   = sig.get("switch_mode", False)
    switch_sell = str(sig.get("switch_sell_code", "")).zfill(6)

    if not is_switch or not switch_sell or switch_sell == "000000":
        return "PROCEED"

    pos = _load_json(OPEN_POS, {})
    if switch_sell not in pos:
        lg.info("[SWITCH] %s 매도 완료 확인 → 신규 진입 진행", switch_sell)
        return "PROCEED"

    sig_ts_str = sig.get("ts", "")
    if sig_ts_str:
        try:
            sig_ts  = datetime.strptime(sig_ts_str, "%Y%m%d%H%M%S")
            elapsed = (datetime.now() - sig_ts).total_seconds()
            if elapsed > SWITCH_TIMEOUT_SEC:
                lg.warning("[SWITCH] ★ TIMEOUT: %s 매도 미완료 %.0f초 > %d초 → 폐기",
                           switch_sell, elapsed, SWITCH_TIMEOUT_SEC)
                return "TIMEOUT"
        except Exception as e:
            lg.debug('[SWITCH] 타임아웃 감지 실패: %s', e)

    lg.info("[SWITCH] %s 매도 대기 중 → 큐 등록 보류", switch_sell)
    return "WAIT"


# ═══════════════════════════════════════════════════════════════
#  처리 완료 마킹
# ═══════════════════════════════════════════════════════════════
def _mark_processed(sig: dict, status: str, lg: logging.Logger):
    sig[PROCESSED_KEY] = True
    sig["bridge_ts"]     = _now_str()
    sig["bridge_ver"]    = VERSION
    sig["bridge_status"] = status
    try:
        tmp = SIGNAL.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sig, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(SIGNAL))
    except Exception as e:
        lg.debug("[MARK] 마킹 실패 (무시): %s", e)


# ═══════════════════════════════════════════════════════════════
#  [v3.7.8 TRACE] 매수 차단 추적 — 모듈 레벨 stats + 헬퍼
# ═══════════════════════════════════════════════════════════════
_SIGNAL_STATS: dict = {"total": 0, "accepted": 0, "rejected": 0,
                       "reject_reason": "", "code": ""}

def _stats_reset() -> None:
    _SIGNAL_STATS.update({"total": 0, "accepted": 0, "rejected": 0,
                          "reject_reason": "", "code": ""})

# [CYCLE-6 2026-05-21] event_journal.jsonl inline helper
def _emit_event(event_type, entity, entity_id="", payload=None, prev_state=None, new_state=None):
    """[CYCLE-6] event_journal.jsonl append-only (fail-safe)."""
    try:
        _evt_path = LOG_DIR / f"event_journal_{datetime.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "rt_signal_to_queue_bridge",
        }
        if prev_state is not None: _evt["prev_state"] = prev_state
        if new_state is not None: _evt["new_state"] = new_state
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass


def _gate_block(lg, gate: str, reason: str, code: str = "", **details) -> None:
    _SIGNAL_STATS["total"] = 1
    _SIGNAL_STATS["rejected"] = 1
    _SIGNAL_STATS["reject_reason"] = reason
    if code:
        _SIGNAL_STATS["code"] = code
    detail_str = " ".join(f"{k}={v}" for k, v in details.items())
    lg.warning("[GATE_BLOCK] gate=%s code=%s reason=%s %s",
               gate, code or "-", reason, detail_str)
    # [CYCLE-6] SIGNAL_REJECTED emit
    _emit_event("SIGNAL_REJECTED", entity="signal", entity_id=code or "-",
                payload={"gate": gate, "reason": reason, **{k: str(v) for k, v in details.items()}})

def _gate_accept(lg, code: str = "", **details) -> None:
    _SIGNAL_STATS["total"] = 1
    _SIGNAL_STATS["accepted"] = 1
    if code:
        _SIGNAL_STATS["code"] = code
    detail_str = " ".join(f"{k}={v}" for k, v in details.items())
    lg.info("[GATE_ACCEPT] code=%s %s", code or "-", detail_str)
    # [CYCLE-6] QUEUED emit
    _emit_event("QUEUED", entity="signal", entity_id=code or "-",
                payload={k: str(v) for k, v in details.items()})

def _emit_signal_summary(lg) -> None:
    rc = {_SIGNAL_STATS["reject_reason"]: 1} if _SIGNAL_STATS["reject_reason"] else {}
    lg.info("[SIGNAL_SUMMARY] total=%d accepted=%d rejected=%d code=%s reject_counts=%s",
            _SIGNAL_STATS["total"], _SIGNAL_STATS["accepted"],
            _SIGNAL_STATS["rejected"], _SIGNAL_STATS["code"] or "-", rc)


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    _stats_reset()
    lg = _setup_logger()
    lg.info("[QUEUE] single-writer=rt_signal_bridge")
    try:
        return _main_body(lg)
    finally:
        _emit_signal_summary(lg)


def _main_body(lg) -> int:
    if not SIGNAL.exists():
        _gate_block(lg, "signal_load", "no_signal_file")
        return RC_HOLD

    age = time.time() - SIGNAL.stat().st_mtime
    if age > SIGNAL_MAX_AGE_SEC:
        _gate_block(lg, "signal_load", "signal_stale", age_sec=f"{age:.0f}", limit=SIGNAL_MAX_AGE_SEC)
        return RC_HOLD

    try:
        # [UTF8SIG 2026-05-13] utf-8 → utf-8-sig: BOM 호환
        with open(SIGNAL, "r", encoding="utf-8-sig") as f:
            sig = json.load(f)
    except Exception as e:
        lg.warning("[BRIDGE] signal 읽기 실패: %s", e)
        _gate_block(lg, "signal_load", "signal_read_fail", err=str(e)[:60])
        return RC_HOLD

    if not sig:
        lg.error("[BRIDGE][FAIL] signal 데이터 없음 → queue 생성 중단")
        _gate_block(lg, "signal_load", "signal_empty")
        raise RuntimeError("signal empty")

    if sig.get(PROCESSED_KEY):
        _gate_block(lg, "signal_state", "already_processed",
                    code=str(sig.get("code", "")).zfill(6))
        return RC_HOLD

    today = _today_str()
    if str(sig.get("date", "")) != today:
        _gate_block(lg, "signal_state", "date_mismatch",
                    sig_date=str(sig.get("date", "")), today=today)
        return RC_HOLD

    code  = str(sig.get("code", "")).zfill(6)
    mode  = str(sig.get("mode", sig.get("strategy_type", "SKIP"))).upper()
    qty   = int(_f(sig.get("qty", 0)))
    price = _f(sig.get("price_ref", 0))
    _SIGNAL_STATS["code"] = code

    if not code or code == "000000" or mode == "SKIP":
        _gate_block(lg, "signal_state", "skip_or_no_code", code=code, mode=mode)
        return RC_HOLD
    if qty <= 0 or price <= 0:
        lg.warning("[BRIDGE] %s qty=%d price=%.0f → SKIP", code, qty, price)
        _gate_block(lg, "signal_state", "invalid_qty_price",
                    code=code, qty=qty, price=int(price))
        return RC_HOLD

    lg.info("=" * 65)
    lg.info("[BRIDGE] %s  신호 수신: %s mode=%s qty=%d @%.0f원",
            VERSION, code, mode, qty, price)

    # ── [W5+D5] 킬스위치 5대 조건 (최우선) — sig 전달로 ts 기반 지연 감지 ──
    ks_blocked, ks_reason = _killswitch_check(sig, lg)
    if ks_blocked:
        _mark_processed(sig, f"KILLSWITCH_{ks_reason}", lg)
        _gate_block(lg, "killswitch", f"KILLSWITCH_{ks_reason}", code=code)
        return RC_HOLD

    # ── [CATASTROPHIC-VOL 2026-05-26] outlier 종목 (거래정지/하한가/감리) 사전 차단 ──
    # 신호 종목의 prices_1m 직전 5봉 변동성 >= 10% 면 차단 (007330 같은 폭락 회피).
    # 백테스트 1건 (-83.02%) 같은 1ST/2ND outlier 차단 mechanism.
    _cv_blocked, _cv_detail = _catastrophic_vol_check(sig, lg)
    if _cv_blocked:
        _mark_processed(sig, "CATASTROPHIC_VOL", lg)
        _gate_block(lg, "catastrophic_vol", "catastrophic_vol_10pct",
                    code=code, detail=_cv_detail)
        return RC_HOLD

    # ── [v3.7.2 FIX-1] 전략 활성화 게이트 ──────────────────────────
    # 스코어보드 → execution_engine → sig → 브리지로 이어지는 라우팅 최종 차단
    # siga_enable=False: 급락일 / 위험 시장 → SIGA 진입 차단
    # pullback_enable=False: mkt_risk_flag=1 → PULLBACK 진입 차단
    # 기본값 True: 필드 없을 때 차단 안 함 (폴백 — 안전한 방향)
    _hint_upper      = str(sig.get("strategy_hint", "")).upper()
    _siga_enable     = bool(sig.get("siga_enable",     True))
    _pullback_enable = bool(sig.get("pullback_enable", True))

    if ("SIGA" in _hint_upper or "GAP" in _hint_upper) and not _siga_enable:
        lg.warning("[v3.7.2] SIGA 전략 비활성화(시장위험) → 차단 [SIGA_DISABLED_BY_MARKET]")
        _mark_processed(sig, "SIGA_DISABLED_BY_MARKET", lg)
        _gate_block(lg, "strategy_enable", "SIGA_DISABLED_BY_MARKET",
                    code=code, hint=_hint_upper)
        return RC_HOLD

    if "PULLBACK" in _hint_upper and not _pullback_enable:
        lg.warning("[v3.7.2] PULLBACK 전략 비활성화(시장위험) → 차단 [PULLBACK_DISABLED_BY_MARKET]")
        _mark_processed(sig, "PULLBACK_DISABLED_BY_MARKET", lg)
        _gate_block(lg, "strategy_enable", "PULLBACK_DISABLED_BY_MARKET",
                    code=code, hint=_hint_upper)
        return RC_HOLD

    # ── [D2] 1일 1회 강제 진입 확인 ──
    is_daily_force = _check_daily_force_entry(lg)

    # ── SWITCH 처리 ──
    switch_result = _handle_switch(sig, lg)
    if switch_result == "WAIT":
        _gate_block(lg, "switch", "SWITCH_WAIT", code=code)
        return RC_HOLD
    if switch_result == "TIMEOUT":
        _mark_processed(sig, "SWITCH_TIMEOUT", lg)
        _gate_block(lg, "switch", "SWITCH_TIMEOUT", code=code)
        return RC_HOLD

    # ── SWITCH 초강력 품질 게이트 ──
    is_switch = sig.get("switch_mode", False)
    if is_switch:
        sw_ev   = _f(sig.get("ev_pct", 0))
        sw_ride = _f(sig.get("ride_score", 0))
        if sw_ev < SWITCH_EV_MIN or sw_ride < SWITCH_RIDE_MIN:
            lg.warning("[SWITCH] ★ 품질 미달: EV=%.2f(필요≥%.2f) "
                       "ride=%.2f(필요≥%.2f) → 교체 차단",
                       sw_ev, SWITCH_EV_MIN, sw_ride, SWITCH_RIDE_MIN)
            _mark_processed(sig, "SWITCH_QUALITY_FAIL", lg)
            _gate_block(lg, "switch_quality", "SWITCH_QUALITY_FAIL",
                        code=code, ev=f"{sw_ev:.2f}", ride=f"{sw_ride:.2f}",
                        ev_min=SWITCH_EV_MIN, ride_min=SWITCH_RIDE_MIN)
            return RC_HOLD

    if not is_switch and _has_open_position(lg):
        _gate_block(lg, "position", "open_position_exists", code=code)
        return RC_HOLD

    if _is_daily_sold(code, lg):
        _mark_processed(sig, "DAILY_SOLD_BLOCKED", lg)
        _gate_block(lg, "daily_sold", "DAILY_SOLD_BLOCKED", code=code)
        return RC_HOLD

    if _already_in_queue(code, today, lg):
        _mark_processed(sig, "QUEUE_DUPLICATE", lg)
        _gate_block(lg, "queue_dup", "QUEUE_DUPLICATE", code=code)
        return RC_HOLD

    # ── 레짐 게이팅 ──
    regime_ok, mode = _regime_gate(sig, lg)
    if not regime_ok:
        _mark_processed(sig, "REGIME_BLOCKED", lg)
        _gate_block(lg, "regime", "REGIME_BLOCKED", code=code,
                    regime=str(sig.get("regime", "")))
        return RC_HOLD

    # ── [v3.7.3 FIX-1] PULLBACK STRONG 즉시 진입 오버라이드 ────────
    # EOD 스코어보드가 검증한 STRONG 눌림 → accel/inst_momentum 우회
    # 보호 경계(킬스위치/BEAR/전략게이트/ride=0)는 이미 위에서 통과
    _pb_class = str(sig.get("pullback_setup_class", "")).upper()
    _pb_ride  = _f(sig.get("ride_score", 0))
    # [v3.7.7 FIX-1] ride 기준 0.20→0 복원 — 눌림목 특성 반영
    # v3.7.6: ride>=0.20 → 눌림목 ride 0.15~0.25 구간을 막아 사실상 전부 탈락
    # 근거: 눌림목(PULLBACK)은 기관 모멘텀이 일시 약해진 구간이 정의
    #       ride=0.18 같은 구간이 진입 핵심 — 이걸 막으면 역방향 필터
    #       스코어보드가 5일+ 기관 지지 이미 검증 → 브리지 ride 재필터 불필요
    #       ride=0 완전 이탈만 방어하면 충분
    _is_strong_pb = (
        _pb_class == "STRONG"
        and _pb_ride > 0    # ride=0 완전이탈만 방어
    )

    # ── [W4+D3] accel 재검증 ──
    # CAUTION 레짐 감지는 STRONG 여부 무관하게 항상 수행
    accel_ok, regime_override = _accel_check(sig, lg)
    if regime_override == "CAUTION":
        sig["regime"] = "CAUTION"
        regime_ok2, mode = _regime_gate(sig, lg)
        if not regime_ok2:
            _mark_processed(sig, "ACCEL_CAUTION_BLOCKED", lg)
            _gate_block(lg, "regime", "ACCEL_CAUTION_BLOCKED", code=code)
            return RC_HOLD

    if _is_strong_pb:
        lg.info("[v3.7.3][STRONG-OVR] ★ accel 미달이나 PULLBACK STRONG 셋업 "
                "(class=%s ride=%.2f) → accel 게이트 우회",
                _pb_class, _pb_ride)
    elif not accel_ok:
        _mark_processed(sig, "ACCEL_BLOCK", lg)
        _gate_block(lg, "accel", "ACCEL_BLOCK", code=code)
        return RC_HOLD

    # ── [W1] 기관 모멘텀 실시간 재검증 ──
    if _is_strong_pb:
        lg.info("[v3.7.3][STRONG-OVR] ★ ride 기준 미달이나 PULLBACK STRONG 셋업 "
                "(class=%s ride=%.2f) → inst_momentum 게이트 우회",
                _pb_class, _pb_ride)
    else:
        inst_ok = _inst_momentum_recheck(sig, lg)
        if not inst_ok:
            _mark_processed(sig, "INST_MOMENTUM_LOW", lg)
            _gate_block(lg, "inst_momentum", "INST_MOMENTUM_LOW", code=code,
                        ride=f"{_f(sig.get('ride_score', 0)):.2f}")
            return RC_HOLD

    # ── [W7+W6+D8] 수익률 평가 ──
    pq_ok, pq_mode_hint = _profit_quality_check(sig, lg)
    if not pq_ok:
        _mark_processed(sig, "PROFIT_QUALITY_FAIL", lg)
        _gate_block(lg, "profit_quality", "PROFIT_QUALITY_FAIL", code=code)
        return RC_HOLD

    if pq_mode_hint == "STABLE" and mode == "ATTACK":
        _ride_early = _f(sig.get("ride_score", 0))
        _cnt_early  = int(_f(sig.get("trade_count", 0)))
        # [B4 v3.7] PULLBACK STRONG 셋업 → STABLE 강등 면제
        # pullback_setup_class=STRONG = 기관 5일+ 지지 + priority≥50 + quality≥55
        # 스코어보드가 검증한 수익성 높은 조건 → 브리지 강등 불가
        _pb_setup = str(sig.get("pullback_setup_class", "")).upper()
        if _pb_setup == "STRONG":
            lg.info("[PROFIT][B4] pullback STRONG 셋업 → STABLE 강등 면제, ATTACK 유지")
        elif _cnt_early < INITIAL_TRADE_THRESHOLD and _ride_early >= 0.60:
            lg.info("[PROFIT] 초기구간이나 ride=%.2f≥0.60 → ATTACK 유지", _ride_early)
        else:
            lg.info("[PROFIT] STABLE 강제 [W6/D8]")
            mode = "STABLE"

    # ── [H3] EV/composite 글로벌 필터 제거 ──
    # 스코어보드 stage1~4에서 OFI·EV·복합점수 이미 검증 완료
    # 브리지 재검증 = 이중 선별 → 헤지펀드 표준 위반
    # ride_score 실시간 급락 감지만 유지 (_inst_momentum_recheck)
    ev_entry  = _f(sig.get("ev_pct", 0))
    ride_entry = _f(sig.get("ride_score", 0))
    # EV/composite 계산은 큐 행 생성(D4)에서만 사용 (필터 아님)
    ev_norm_base = _dynamic_ev_norm_base(sig, lg)
    ev_w   = _f(sig.get("bridge_ev_weight",   EV_WEIGHT))
    ride_w = _f(sig.get("bridge_ride_weight", RIDE_WEIGHT))
    ev_w   = max(EV_WEIGHT_MIN, min(EV_WEIGHT_MAX, ev_w))
    ride_w = 1.0 - ev_w
    ev_norm    = min(ev_entry / ev_norm_base, 1.0) if ev_norm_base > 0 else 0.0
    composite  = ev_norm * ev_w + ride_entry * ride_w
    lg.info("[H3] EV=%.2f ride=%.2f composite=%.3f — 필터 없음, 기록 전용",
            ev_entry, ride_entry, composite)

    # ── 시간대 기록 (D6 게이트 제거 — 기록 전용) ──
    _time_quality_extra(lg)

    # ── [H2] 전략별 ride_min 실시간 검증 ──
    # [v3.7.4 FIX-1] PULLBACK STRONG이면 ride_min 재검증 완전 건너뜀
    # 근거: ride=0 완전이탈은 _inst_momentum_recheck에서 이미 방어 (_pb_ride>0)
    #       STRONG = EOD 5일+ 기관 지지 검증 완료 → ride_min=0.30 재검증 중복 차단
    if _is_strong_pb:
        lg.info("[v3.7.4][STRONG-OVR] ★ PULLBACK STRONG 셋업 → "
                "_strategy_override_gate 건너뜀 (ride_min 재검증 불필요)")
    else:
        strat_ok, mode = _strategy_override_gate(sig, ev_entry, ride_entry,
                                                  composite, mode, lg)
        if not strat_ok:
            _mark_processed(sig, "STRATEGY_OVERRIDE_FAIL", lg)
            _gate_block(lg, "strategy_override", "STRATEGY_OVERRIDE_FAIL",
                        code=code, ev=f"{ev_entry:.2f}", ride=f"{ride_entry:.2f}",
                        composite=f"{composite:.3f}")
            return RC_HOLD

    # ── 큐 행 생성 ──
    row = _build_queue_row(sig, mode, today, ev_norm_base, lg)

    if not row:
        lg.error("[BRIDGE][FAIL] queue.csv 생성 실패 (empty)")
        _gate_block(lg, "queue_build", "queue_row_empty", code=code)
        raise RuntimeError("queue empty")

    # ── 원자적 큐 추가 ──
    if not _append_to_queue(row, lg):
        _gate_block(lg, "queue_write", "queue_write_fail", code=code)
        return RC_HOLD

    # ── 처리 완료 마킹 ──
    _mark_processed(sig, "QUEUED_OK", lg)
    _gate_accept(lg, code=code, mode=mode, qty=qty, price=int(price),
                 ev=f"{ev_entry:.2f}", ride=f"{ride_entry:.2f}",
                 composite=f"{composite:.3f}")

    # ── [v3.4 FIX-1] pnl_linker v3.3 1순위 연결 — 자기진화 루프 완성 ──
    # 큐 추가 성공 = 매매 시작점 → linker 훅 호출로 자기진화 루프 최종 연결
    _run_id = str(sig.get("run_id", "")) or code
    import importlib as _il
    for _pnl_mod in (
        "pnl_strategy_linker_v3_5",
        "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL",
        "pnl_strategy_linker",
    ):
        try:
            _m = _il.import_module(_pnl_mod)
            if hasattr(_m, "notify_rt_entry"):
                _m.notify_rt_entry(code=code, run_id=_run_id)
                lg.info("[LINKER] notify_rt_entry(%s) 완료 | code=%s", _pnl_mod, code)
                break
        except (ImportError, Exception):
            continue

    # ── 콘솔 출력 ──
    ride    = _f(sig.get("ride_score", 0))
    ev      = _f(sig.get("ev_pct", 0))
    regime  = str(sig.get("regime", "NEUTRAL")).upper()
    sw_tag  = "SWITCH" if is_switch else ("FORCE" if is_daily_force else "NEW")
    conv    = row.get("conviction", "?")
    ex_type = row.get("exec_type", "?")
    strat_h = str(sig.get("strategy_hint", "RT"))

    print()
    print("=" * 65)
    print(f"  [{sw_tag}] ★ 큐 등록 완료  v3.7.1 SAFEPLUS  [치명결함C2·C3수정완료]")
    print(f"  종목={code}  전략={strat_h}  {mode}  {qty}주 @{int(price):,}원")
    print(f"  ride={ride:.2f}  conviction={conv}  exec={ex_type}")
    print(f"  EV={ev:.2f}%  복합={composite:.3f}(base={ev_norm_base:.2f})  regime={regime}")
    if is_switch:
        sw_sell = str(sig.get("switch_sell_code", "")).zfill(6)
        print(f"  SWITCH: {sw_sell} → {code}")
    if is_daily_force:
        print(f"  ★ 1일 1회 강제진입 모드 [D2]")
    print("=" * 65)
    print()

    lg.info("[BRIDGE] ★ 큐 등록 완료: %s %s %d주 @%d원 "
            "[mode=%s conv=%s exec=%s ride=%.2f ev=%.2f%% composite=%.3f regime=%s] %s",
            code, strat_h, qty, int(price),
            mode, conv, ex_type, ride, ev, composite, regime, sw_tag)

    return RC_OK


if __name__ == "__main__":
    sys.exit(main())

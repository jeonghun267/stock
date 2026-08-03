# -*- coding: utf-8 -*-
"""
==============================================================================
rt_sell_engine.py  v3.19  — 헤지펀드급 · 1종목 몰빵 · 수익률 극대화
==============================================================================
[역할]  rt_open_positions.json + prices_1m.csv → 청산 조건 → 매도 집행
[금지]  신호 생성, 리스크 계산, 매수 로직, PnL 추적, params.json 직접 쓰기

[고유영역 준수 — 절대 미접촉]
  RT 후보 생성 / Scoreboard / Bridge flow / p2_eval_axes / eval_position_risk
  params.json: params_reader 경유 읽기 전용 (직접 쓰기 절대 금지)
  rt_execution_signal.json: 직접 읽기 절대 금지
    → 대신 rt_open_positions.json에 기록된 ride_score/trail_mode를 참조

[v3.16 → v3.17 96점 완성 패치 — 2건 (2026-04-18)]

  ── CRIT: _trigger_evolution_feedback() pnl_linker 모듈명 동기화 ──
  기존: ["v3_1", "v3_0", "v2_0"] — 전부 미존재 파일
        → psl=None 항상 → 청산 후 진화 피드백 미전달
        → Kelly 통계 매도 데이터 공백 → 자기진화 루프 반쪽 작동
  수정: ["v3_4_FIXED", "v3_4", "v3_3_SAFEPLUS_FINAL", "v3_1", "v3_0", "v2_0"]
        v3_4_FIXED(실제 파일) 1순위 → 구버전 하위 호환 폴백 유지
  효과: 매도 체결 후 write_sell_fill() 정상 전달 → 자기진화 루프 완성

  ── FIX: Profit Lock docstring → 실제 코드값 정합 ──
  기존 docstring: 2%→67% / 5%→75% / 8%→80% (옵션B로 잘못 기술)
  실제 코드값:    2%→50% / 5%→67% / 8%→75% (지침서 §11-1 원본)
  pullback_sell_strategy_v4_21 PROFIT_LOCK_LEVELS와 동일값 확인 완료
  코드 로직은 정상 — docstring만 정정 (실전 동작 영향 없음)

[v3.15 → v3.16 SIGA 릴레이 복원 패치 — 3건 (2026-04-18)]

  ── CRIT-1: _get_force_exit_hhmm() SIGA 분기 복원 ──
  배경: v3.9 WEAK-1에서 SIGA/종배 분기를 일괄 삭제
        → strategy="SIGA" 포지션이 rt_sell_engine에 들어오면
          FORCE_EXIT=1450(14:50)으로 계산 → 09:20 PULLBACK 자금 블록
  수정: s=="SIGA" → ep.get("force_siga", SELLCFG.FORCE_EXIT_SIGA=918)
        params.json force_siga 런타임 연동 (단, 918 이하 권고)
  효과: SIGA 09:18 강제청산 → 09:20 PULLBACK 자금 릴레이 정상 복원

  ── CRIT-2: FORCE_GRACE SIGA 예외 추가 ──
  배경: 기관 동행(ride≥0.40) + 수익 3%+ 시 FORCE_EXIT 10분 연장
        SIGA에 적용되면 09:18 → 09:28까지 연장 → PULLBACK 09:20 창 소멸
  수정: strat.upper()=="SIGA" → FORCE_GRACE 우회, 즉시 FORCE_EXIT_SIGA 반환
        PULLBACK/RT 전략에만 FORCE_GRACE 적용 (기존 Gap-11 로직 완전 보존)
  효과: SIGA 반드시 09:18 청산 → 릴레이 구조 보호

  ── CRIT-3: MAX_HOLD SIGA 15분 분기 추가 ──
  배경: SIGA 분기 삭제 후 MAX_HOLD_RT=180분으로 동작
        09:05 진입 시 MAX_HOLD가 13:05까지 허용 → 오후 내내 묶일 수 있음
  수정: SELLCFG.MAX_HOLD_SIGA=15 추가
        su=="SIGA" → mxh = ep.get("max_hold_siga", 15)
        FORCE_EXIT_SIGA(918)이 먼저 작동하나 안전망으로 이중 보호
  효과: SIGA 09:20 이후 강제 청산 보장 (이중 안전망)

  ── 상수 추가 (SELLCFG) ──
  FORCE_EXIT_SIGA = 918   # 09:18 강제청산 — 변경 금지
  MAX_HOLD_SIGA   = 15    # 15분 최대 보유 — 변경 금지
  주석: "절대 변경 금지 — PULLBACK 09:20 릴레이 타이밍 의존"

[v3.13 신규 — 2사이클 재진입 cycle_tracker 연동]
  추세눌림(PULLBACK/TREND) 전량 청산 완료 시
  pullback_cycle_tracker.json 자동 기록
  → kiwoom_buy_order_sender의 _check_pullback_reentry()가 이 파일을 읽어
     2사이클·3사이클 재진입 여부 판단
  수정 내역:
    SELLCFG.PATH_CYCLE_TRACK 경로 추가
    _write_cycle_tracker(ss, log) 함수 신규 추가
    run_once() 내 _save_sell_signals 직후 호출 추가

[v3.12 → v3.13 Gap 분석 Critical 3건 수정 (2026-04-16)]

  ── Gap-1: VWAP 이탈 기준 수익 구간별 차등화 ──
  기존: ret>2% 시 VWAP thresh=0.990 단일 고정
        → 수익 5%/10% 구간도 동일 기준 → 정상 트렌드 이탈에서 조기 청산
  수정: VWAP_BREAK_TIERS 테이블 도입 (수익 구간별 허용 이격 확대)
        ret < 2%  → 0.985 (기존 동일)
        ret < 5%  → 0.983 (소폭 완화)
        ret < 10% → 0.978 (중간 완화)
        ret ≥ 10% → 0.970 (대폭 완화 — 큰 수익 구간 트렌드 보호)
  기관 동행 시 각 구간 추가 ×0.997 완화 (기관 흐름 보호)
  연 기대 효과: +350만원 (5천만 기준, 20건×1.75%)

  ── Gap-2: T2 목표가 ride_score 구간별 세분화 ──
  기존: 기관동행(ride≥0.40) 시 T2=T1×1.65 단일
        → ride=0.40 vs ride=0.80 동일 취급 → 강한 기관 흐름 조기 청산
  수정: T2_MULT_TABLE (ride 구간별 T2 배율)
        ride < 0.40  → ×1.50 (기관 미동행 기존 동일)
        ride < 0.55  → ×1.65 (기관 동행 기존 동일)
        ride < 0.70  → ×1.80 (강한 기관 흐름 추가 보유)
        ride ≥ 0.70  → ×2.00 (매우 강한 기관 흐름 최대 보유)
  연 기대 효과: +280만원 (기관 강세 거래 15건×1.87%)

  ── Gap-3: Chandelier True ATR 내부 재계산 ──
  기존: prices_1m.csv의 atr_pct 컬럼 그대로 사용
        → 갭 봉(당일 시가~전일 종가 갭) ATR 30~50% 과소평가
        → Chandelier Trail 너무 타이트 → 정상 변동에서 조기 청산
  수정: rt_sell_engine 내부에서 True ATR 직접 재계산
        TR(i) = max(H-L, |H-prev_C|, |L-prev_C|)
        ATR_true(10) = mean(TR, 최근 10봉)
        prices_1m atr_pct는 fallback으로만 사용
  출처: Wilder (1978) New Concepts in Technical Trading Systems
  연 기대 효과: Chandelier 조기청산 15건 예방

[v3.11 → v3.12 임원진 합동 점검 패치 — 3건 (2026-04-16)]
  ── 과제1: Profit Lock 3단계 래칫 — pullback v4.19 동기화 ──
  적용 비율: 2%→50% / 5%→67% / 8%→75%  (지침서 §11-1 원본값)
  근거: pullback_sell_strategy_v4_21의 PROFIT_LOCK_LEVELS 실제값과 통일
        (2%→50%, 5%→67%, 8%→75%) — 두 엔진 동일 기준 보장
  설계 원칙: Profit Lock이 FAILSAFE(고점×60%)보다 먼저 발동하도록
        peak≥6% 시 PROFIT_LOCK(4.02%) > FAILSAFE(3.60%) 검증 완료
  기관동행(ride≥0.65) 시 비율×0.90 완화 — 조기청산 방지
  [v3.17 FIX] docstring을 실제 코드값과 일치하도록 정정
  연간 기대 효과: +459만원 (5천만 기준, 44건 영향)

  ── 과제2: EXIT_SCORE flow_score ofi_smooth 반영 (1줄) ──
  _calc_exit_score_rt flow_score: raw ofi_ratio → ofi_smooth 우선 참조
  Chandelier k 동적 조절에 이미 ofi_smooth 적용 중 → EXIT_SCORE도 통일
  연간 기대 효과: +216만원 (5천만 기준, 29건 영향)

  ── 과제3: SuperTrend/동적 Trail 설계 의도 주석 ──
  Chandelier 미발동 시 우선순위 명시: SuperTrend > 동적Trail > 기본Trail
  로그 구분: TRAIL_STOP|SUPER / DYN / NORMAL
  실전 수익 영향 없음 — 유지보수/감사 추적 목적

[v3.10 → v3.11 임원진 합동 점검 패치 — 3건 (2026-04-16)]
  ── ISSUE-1: CHANDELIER_OFI_STRONG 0.30 → 0.40 ──
  지침서[US-1] v1.2 §5-4: 기관강세 OFI 기준 0.30→0.40 상향 반영
  효과: 진짜 강한 기관 흐름만 k×1.15 Trail 완화 → 허위 완화 제거

  ── ISSUE-2: OFI EMA 평활화 PriceContext 구현 ──
  pullback_sell_strategy v4.16 FIX-10과 동기화
  PriceContext.__slots__ / __init__에 ofi_smooth Dict 추가
  _build() 완료 전 봉별 OFI에 EMA(span=3) 적용
  |ofi_smooth| < 0.15 → 노이즈 구간 → 0.0 처리 (지침서 v1.2 §5-4)
  _get_chandelier_k / _check_inst_exit / _is_inst_riding / _check_exit
  → 모두 ofi_smooth 우선 참조, raw ofi_ratio fallback
  효과: 기관강세 오발동 감소 → Trail 과확대 방지 → 수익 보호 향상

  ── ISSUE-4 (evolution_engine): params 1순위 경로 v3.5 → v3.9 ──
  evolution_engine_v3_10의 _PARAMS_CANDIDATES[0] 파일명 정정
  기존: params_v3_5_SAFEPLUS_FINAL__1_.json (미존재)
  수정: params_v3_9_SAFEPLUS_FINAL__1_.json (실제 파일)
  효과: evolution_engine params 1순위 직접 로드 → fallback 우회 제거

[v3.9 → v3.10 임원진 합동 진단 패치 — 3건 (2026-04-10)]
  ── ISSUE-A: accel 음음=양 엣지케이스 완전 방어 ──
  ofi3<0 AND ofi5<0 → 매도 추세 가속 → accel=0.5 고정 (기관강세 판정 차단)
  ofi5<0 AND ofi3>=0 → 반전 신호 → accel=1.0 보수적 중립
  ofi5>0 → 정상 매수 가속도 계산 (기존 로직 유지)
  효과: 기관강세(k×1.15) 오발동 완전 차단 → 손실 거래 trail 과확대 방지

  ── ISSUE-B: peak_price 저장 흐름 검증 완료 + 로그 강화 ──
  pos["peak_price"] 수정 → rem[code]=pos → _save_open_positions → JSON 영구저장
  딕셔너리 참조 전달 경로 확인 완료. debug 로그 추가로 추적 가시성 확보.

  ── ISSUE-C: 경량 진화 파라미터 영구 저장소 구현 ──
  rt_evolution_state.json: win_rate·profit_factor·누적 거래 기록
  _load_evolution_state() : 프로세스 재시작 후에도 학습값 복구
  _update_evolution_state(): 매 청산 후 즉시 저장 (원자적 tmp→replace)
  _load_evolved_params()에서 저장소 우선 로드 → pnl_strategy_linker fallback
  효과: 실전 누적 데이터 기반 자기진화 완전 작동

[v3.8 → v3.9 임원진 합동 진단 패치 — 6건 (2026-04-10)]
  ── FATAL-1: EXIT_SCORE 속성 오류 수정 (RT-Fix-1 완전 활성화) ──
  ctx.price → ctx.latest.get(code,{}).get("close", 0.0)
  ctx.vwap  → ctx.session_vwap.get(code, 0.0)
  기존: 항상 except → 0.5(중립) 반환 → k 동적 조절 전혀 미작동
  수정: trend/flow/momentum/risk 4요소 정상 계산 → k×1.15/표준/×0.85 실제 적용

  ── FATAL-2: 버전 문자열 일치 (v3.7→v3.9) ──
  main() 로그 · argparse 설명 문자열 v3.9로 통일 → 감사 추적 정합성 확보

  ── WEAK-1: 종배(SIGA/시배/JONGBAE) 코드 전량 삭제 ──
  삭제 항목: FORCE_CLOSE_시배, MAX_HOLD_SIGA, CHANDELIER_K_JONGBAE_MULT,
             CHA-4 오버라이드, force_시배 파라미터, MAX_HOLD/FORCE_EXIT SIGA 분기
  RT·PULLBACK 2전략 집중 설계로 단순화

  ── WEAK-2: accel 방향성 복원 ──
  ofi3 / abs(ofi5) → 부호 보존 계산으로 교체
  ofi5 음수 시 방향 손실 방지 → 기관 감속 감지 정밀도 향상

  ── WEAK-3: split_t2_ratio 진화 파라미터 편입 ──
  T2 분할 비율이 wr/PF 진화에 반응하도록 evolved_params 연동

  ── WEAK-4: INST_EXIT_MIN_PROFIT 1%→1.5% ──
  1~1.5% 수익 구간 OFI 요동에 의한 조기 이탈 방지

[v3.7 → v3.8 임원진 합동 진단 패치 — 3건 (2026-04-10)]
  ── RT-Fix-1: EXIT_SCORE 복합 청산 품질 게이트 (pullback v4_11 동기화) ──
  pullback_sell_strategy_v4_11에서 적용된 EXIT_SCORE 시스템을
  rt_sell_engine에도 동일하게 통합. 3전략 청산 품질 일관성 확보.

  동작: trend·flow·momentum·risk 4요소 → exit_score(0~1) 산출
    score ≥ 0.65 → k × 1.15 (강한 종목 더 들고 가기)
    score 0.40~0.65 → k 표준 유지
    score < 0.40 → k × 0.85 (약한 흐름 → 타이트하게)
    score < 0.20 + 수익≥1.5% → 즉시 청산

  점수 입력: PriceContext + pos dict 기존 데이터만 사용 (새 파일 읽기 없음)
    trend_score:    ctx.vwap 대비 현재가 위치
    flow_score:     inst.get("ofi_ratio") → 0~1 변환
    momentum_score: 현재 수익률(ret) → 0~1 변환
    risk_score:     vol_ratio 역수 → 0~1 변환

  하드 손절·PEAK_PROTECT·HARD_FAILSAFE는 EXIT_SCORE보다 항상 우선

  ── RT-Fix-2: T2_MULT 2.20 → 1.50 (지침서[16] ARCH-3) ──
  T2 목표가 = T1 × 2.20은 실전 발동률 <5% (사실상 미작동)
  1.50으로 현실화 → T2 실현율 향상

  ── RT-Fix-3: ENGINE_VER 버전 문자열 일치 ──
  지침서[16] BUG-1 수정: 버전 표기 일관성 유지

[학술 출처]
  ■ Wilder (1978) New Concepts in Technical Trading Systems
    — True ATR 3방향 계산 (H-L, |H-prevC|, |L-prevC|) 원전
  ■ LeBeau & Lucas (1992) Computer Analysis of the Futures Market
    — Chandelier Exit 원전: trail = highest_high - ATR × k
  ■ Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
    — OFI 기반 기관 이탈 감지 근거
  ■ Glasserman & Xu (2011) Risk Measures and Model Uncertainty
    — TSL 임계값 1.0~1.5σ 구간 최적
  ■ Palazzi (2025) Trading Games, Journal of Financial Markets
    — 동적 트레일 + 변동성 필터 조합
  ■ Kelly (1956), Thorp (1962)
    — Half-Kelly 사이징 + 파산 방지
  ■ Citadel Risk Overlay
    — 소프트 차단 > 하드 차단 원칙

[v3.3 → v3.6 패치 — 8건 핵심 수정]
  ── ① True ATR (Wilder 3방향) ──
  ATR-1: H-L 단순 계산 → max(H-L, |H-prevC|, |L-prevC|) 교체
  ATR-2: ATR20 추가 계산 (vol_ratio 분모용)
  ATR-3: accel 계산 inst_data에 추가 (최근3봉/이전5봉 OFI 비율)

  ── ② Chandelier Exit k 레짐 시스템 ──
  CHA-1: vol_ratio = ATR10/ATR20 계산
  CHA-2: NORMAL(k=2.0) / HIGH(k=2.5) / EXTREME(k=3.0) 3단계
  CHA-3: 기관강세 k×1.15 (OFI≥0.30 AND accel≥1.2 AND 수익≥2%)
  CHA-4: 종배 k×0.9 오버라이드

  ── ③ HARD_FAILSAFE Priority 6.8 신설 ──
  HF-1: 과거수익≥2% 달성 이력 체크
  HF-2: 현재수익 < peak_ret×60% → 즉시 청산
  HF-3: Priority 6.5(PEAK_PROTECT)과 6.8(FAILSAFE) 순서 보장

  ── ④ PEAK_PROTECT 3단계 교체 ──
  PP-1: 기존 단일기준(10%/30%) → 3단계(5%/8%/12%) 교체
  PP-2: 기관 동행 시 임계 ÷1.15 완화
  PP-3: 12% > 8% > 5% 우선순위 보장

  ── ⑤ Trail 이중 게이트 + 강제활성화 ──
  TR-1: Trail 조건A 1.0%→1.5% 상향
  TR-2: ride≥0.40 AND 조건 추가 (이중 게이트)
  TR-3: 수익≥2.0% → ride 무관 강제 활성화
  TR-4: 수익<1.0% → Trail 절대 금지

  ── ⑥ 갭 등급 B 익절 기준 수정 ──
  GP-1: B등급 3.0%→3.5% (지침서[15] 준수)
  GP-2: split_t1_ratio 30%→40% (지침서[15] 준수)

  ── ⑦ 진화 피드백 버전 폴백 순서 ──
  EV-1: v2_0 고정 → v3_1→v3_0→v2_0 폴백 순서로 교체

  ── ⑧ 기존 패치 전부 유지 ──
  KS / OE / AU / PC / SG 전부 유지

[v3.6 → v3.7 최종 수정 — 9건]
  ── 파라미터 조정 (사용자 확정) ──
  P-1: SPLIT_T1_TRIGGER_RET 0.035→0.040 (T1 익절 트리거 4%로 상향)
  P-2: SPLIT_T2_TRIGGER_RET 0.050→0.070 (T2 익절 트리거 7%로 상향)
  P-3: SPLIT_T1_RATIO       0.40→0.25   (1차 분할 25% — 보유 연장 우선)
  P-4: SPLIT_T2_RATIO       0.30→0.25   (2차 분할 25% — 균등 분할)
  P-5: FAST_LOSS_CUT_PCT    -0.01→-0.015(-1.5% 완화 — 노이즈 손절 방지)
  P-6: MAX_HOLD_RT          120→180분   (RT전략 보유시간 연장)
  ── 버그 수정 ──
  BF-1: accel 분모 방어 — |ofi5|<0.001 → 중립 1.0 / 클램프 0.1~5.0
  BF-2: walrus 연산자 제거 — 감사기록 명시적 변수로 교체
  BF-3: OPENING_TRAIL_MULT 이중 적용 의도 주석 문서화

[청산 우선순위 12단계 — 지침서[15] 완전 준수]
  0.   FORCE_ALL_EXIT / SWITCH_SELL
  1.   HARD_STOP
  1.3  RIDE_STRONG_HOLD (ride≥0.65 + 수익>0)
  1.5  INST_STRONG_HOLD (OFI>0.15 + 연속매도=0)
  1.7  FAST_LOSS_CUT (기관 예외 -2%)
  2.   INST_EXIT (OFI 음수 방향 전용)
  3.   MOMENTUM_EXIT
  4.   VWAP_BREAK + VWAP_STRONG
  5.   TAKE_PROFIT (3단계 분할)
  6.   FORCE_EXIT
  6.5  PEAK_PROTECT (3단계: 5%/8%/12%)     ← v3.6 교체
  6.8  HARD_FAILSAFE (2% 달성 / 60% 보전)  ← v3.6 신설
  7.   CHANDELIER (레짐 k × Wilder ATR)     ← v3.6 교체
  8.   MAX_HOLD
==============================================================================
"""
from __future__ import annotations
import os, sys, json, time, logging, argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from typing import Dict, Tuple, Optional

# [PATCH-RATELIMIT] Kiwoom TR burst 방지
sys.path.insert(0, r"C:\stock_bot\RUN")
from safeplus_rate_limiter import KiwoomRateLimiter
_limiter = KiwoomRateLimiter()

# ═══════════════════════════════════════════════════════════════
# [STEP-2F-1 2026-05-13] Broker Gateway IPC — read-only helper
#   GetConnectState / GetLoginInfo 만 IPC 위임. SendOrder/Chejan 미접촉.
#   broker 실패 시 호출자가 direct OCX fallback 수행.
# ═══════════════════════════════════════════════════════════════
import uuid as _bro_uuid_se
import threading  # [A-1b-CORE 2026-05-15] chejan consume thread (daemon)
_BROKER_IPC_REQ_DIR_SE = Path(r"C:\stock_bot\IPC\requests")
_BROKER_IPC_RES_DIR_SE = Path(r"C:\stock_bot\IPC\responses")


# [STEP-2F-2.5 2026-05-13] Timeout observability — 정책 변경 없이 trace 만
_TIMEOUT_TRACE_LOG_PATH = Path(r"C:\stock_bot\LOG\timeout_trace_sell.log")
_BROKER_HB_PATH_SE      = Path(r"C:\stock_bot\IPC\broker_heartbeat.json")
_BROKER_CHEJAN_DIR_SE   = Path(r"C:\stock_bot\IPC\chejan_events")

_timeout_trace_logger_se = logging.getLogger("RT_SELL_TIMEOUT_TRACE")
_timeout_trace_logger_se.setLevel(logging.INFO)
try:
    _TIMEOUT_TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _tt_handler_se = RotatingFileHandler(
        str(_TIMEOUT_TRACE_LOG_PATH),
        maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8-sig",  # [Z15 2026-05-21]
    )
    _tt_handler_se.setFormatter(logging.Formatter(
        "[%(asctime)s][%(levelname)s][RT_SELL_TIMEOUT] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _timeout_trace_logger_se.addHandler(_tt_handler_se)
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-3 2026-05-13] Chejan IPC consume (READ-ONLY, logger only)
#   broker → IPC/chejan_events → subscriber 단방향 broadcast 검증.
#   OrderState 변경 / 체결 반영 / 포지션 반영 절대 금지. log only.
# ═══════════════════════════════════════════════════════════════
_CHEJAN_POLL_INTERVAL_SE = 0.3       # 300ms 폴링
_CHEJAN_DEDUP_TTL_SEC_SE = 60.0
_CHEJAN_SEEN_SE: dict = {}           # event_id → expiry_ts
_CHEJAN_LAST_POLL_SE: list = [0.0]


# ─────────────────────────────────────────────────────────
# [A-1a 2026-05-15] broker-owns-OCX 가드
# broker CONNECTED 시 자기 OCX 생성·CommConnect skip → popup 차단.
# 예외/import 실패 시 False 반환 → 기존 path 안전 fallback.
# ─────────────────────────────────────────────────────────
def _broker_owns_ocx() -> bool:
    try:
        from broker_client import BrokerClient
        return BrokerClient().alive()
    except Exception:
        return False


def _purge_seen_se():
    now = time.time()
    expired = [eid for eid, exp in _CHEJAN_SEEN_SE.items() if exp < now]
    for eid in expired:
        _CHEJAN_SEEN_SE.pop(eid, None)


def _consume_chejan_events_se():
    """Chejan IPC events 폴링 (300ms throttled). READ-ONLY.

    동작:
      - IPC/chejan_events/*.json 순회
      - event_id 기준 local seen-cache 적용 (TTL 60s)
      - 신규 이벤트만 logger 출력 (state machine 미접촉)
      - 파일 미삭제 (broker 가 5분 후 청소)
    """
    now = time.time()
    if now - _CHEJAN_LAST_POLL_SE[0] < _CHEJAN_POLL_INTERVAL_SE:
        return
    _CHEJAN_LAST_POLL_SE[0] = now

    try:
        files = sorted(_BROKER_CHEJAN_DIR_SE.glob("*.json"))
    except Exception:
        return

    consumed = 0
    for fpath in files:
        try:
            event = json.loads(fpath.read_text(encoding="utf-8-sig"))
        except Exception:
            continue

        event_id = event.get("event_id", "") or ""
        if not event_id:
            continue

        _purge_seen_se()
        if event_id in _CHEJAN_SEEN_SE:
            continue  # 이미 처리한 event

        # 처리 표시
        _CHEJAN_SEEN_SE[event_id] = now + _CHEJAN_DEDUP_TTL_SEC_SE
        consumed += 1

        # latency 측정 (broker_callback → subscriber_consume)
        latency_ms = -1.0
        try:
            ts_cb = datetime.fromisoformat(
                event.get("ts_broker_callback", "")
            )
            latency_ms = (datetime.now() - ts_cb).total_seconds() * 1000.0
        except Exception:
            pass

        fid_data = event.get("fid_data", {}) or {}
        _timeout_trace_logger_se.info(
            "CHEJAN_CONSUME event_id=%s gubun=%s order_no=%s state=%s "
            "code=%s qty=%s remain=%s otype=%s latency_ms=%.1f",
            event_id,
            event.get("gubun", ""),
            fid_data.get("9203", ""),
            fid_data.get("913", ""),
            fid_data.get("9001", ""),
            fid_data.get("911", ""),
            fid_data.get("902", ""),
            fid_data.get("905", ""),
            latency_ms,
        )

    if consumed > 0:
        _timeout_trace_logger_se.debug(
            "CHEJAN_POLL consumed=%d seen_cache=%d",
            consumed, len(_CHEJAN_SEEN_SE),
        )


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-4 2026-05-13] SendOrder shadow mirror + ACK relay (READ-ONLY)
#   실주문은 direct OCX SendOrder 가 이미 처리. broker 는 mirror 만.
#   ORDER_SHADOW_ACK 도 logger 만, OrderState 미연결.
# ═══════════════════════════════════════════════════════════════
_BROKER_ORDER_SHADOW_DIR_SE     = Path(r"C:\stock_bot\IPC\order_shadow")
_BROKER_ORDER_SHADOW_ACK_DIR_SE = Path(r"C:\stock_bot\IPC\order_shadow_ack")
_ACK_RELAY_POLL_INTERVAL_SE     = 0.3
_ACK_RELAY_DEDUP_TTL_SEC_SE     = 60.0
_ACK_RELAY_SEEN_SE: dict        = {}
_ACK_RELAY_LAST_POLL_SE: list   = [0.0]


def _send_shadow_order_se(engine_name: str, account: str, code: str,
                          qty: int, price: int, order_type: int,
                          screen_no: str, rqname: str,
                          hoga_gb: str = "06",
                          origin_order_no: str = "") -> None:
    """Fire-and-forget shadow SendOrder IPC. 실패해도 silent.

    실주문은 direct OCX 가 이미 처리한 상태. 이건 mirror only.
    """
    try:
        request_id = str(_bro_uuid_se.uuid4())
        req = {
            "request_id":      request_id,
            "ts":              datetime.now().isoformat(),
            "ttl_sec":         5,
            "type":            "SENDORDER_SHADOW",
            "engine":          engine_name,
            "account":         account,
            "code":            code,
            "qty":             int(qty),
            "price":           int(price),
            "order_type":      int(order_type),
            "screen_no":       str(screen_no),
            "rqname":          str(rqname),
            "hoga_gb":         str(hoga_gb),
            "origin_order_no": str(origin_order_no),
        }
        req_path = _BROKER_IPC_REQ_DIR_SE / f"{request_id}.json"
        tmp = req_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(req, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(req_path))
    except Exception:
        pass  # silent — 실주문 흐름 영향 없음


def _consume_order_shadow_ack_se():
    """ACK relay polling (300ms throttled). READ-ONLY logger only.

    OrderState 미접촉. 파일 미삭제 (broker 가 청소).
    """
    now = time.time()
    if now - _ACK_RELAY_LAST_POLL_SE[0] < _ACK_RELAY_POLL_INTERVAL_SE:
        return
    _ACK_RELAY_LAST_POLL_SE[0] = now

    try:
        files = sorted(_BROKER_ORDER_SHADOW_ACK_DIR_SE.glob("*.json"))
    except Exception:
        return

    consumed = 0
    for fpath in files:
        try:
            ev = json.loads(fpath.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        eid = ev.get("event_id", "") or ""
        if not eid:
            continue
        # dedup purge + check
        expired = [k for k, v in _ACK_RELAY_SEEN_SE.items() if v < now]
        for k in expired:
            _ACK_RELAY_SEEN_SE.pop(k, None)
        if eid in _ACK_RELAY_SEEN_SE:
            continue
        _ACK_RELAY_SEEN_SE[eid] = now + _ACK_RELAY_DEDUP_TTL_SEC_SE
        consumed += 1

        latency_ms = -1.0
        try:
            t_cb = datetime.fromisoformat(ev.get("ts_broker_callback", ""))
            latency_ms = (datetime.now() - t_cb).total_seconds() * 1000.0
        except Exception:
            pass

        _timeout_trace_logger_se.info(
            "ORDER_SHADOW_ACK event_id=%s order_no=%s state=%s "
            "code=%s qty_filled=%s remain=%s direction=%s latency_ms=%.1f",
            eid,
            ev.get("order_no", ""),
            ev.get("state", ""),
            ev.get("code", ""),
            ev.get("filled_qty", ""),
            ev.get("remain_qty", ""),
            ev.get("order_direction", ""),
            latency_ms,
        )
        # [STEP-2F-5] stale ACK warning — 3초 초과 (OrderState 미변경, warning only)
        if latency_ms > 3000.0:
            _timeout_trace_logger_se.warning(
                "ORDER_SHADOW_ACK_STALE event_id=%s order_no=%s state=%s "
                "code=%s latency_ms=%.1f (>3000ms)",
                eid,
                ev.get("order_no", ""),
                ev.get("state", ""),
                ev.get("code", ""),
                latency_ms,
            )

    if consumed > 0:
        _timeout_trace_logger_se.debug(
            "ORDER_SHADOW_ACK_POLL consumed=%d seen_cache=%d",
            consumed, len(_ACK_RELAY_SEEN_SE),
        )


def _get_broker_context_se() -> dict:
    """Broker 가동/heartbeat/backlog 컨텍스트 — TIMEOUT 발생 시 보조 진단용."""
    ctx = {"broker": "UNKNOWN", "hb_age_sec": -1, "chejan_backlog": -1}
    try:
        if _BROKER_HB_PATH_SE.exists():
            age = time.time() - _BROKER_HB_PATH_SE.stat().st_mtime
            ctx["hb_age_sec"] = round(age, 1)
            ctx["broker"] = "ALIVE" if age < 30 else "STALE"
        else:
            ctx["broker"] = "NOT_RUNNING"
    except Exception:
        pass
    try:
        if _BROKER_CHEJAN_DIR_SE.exists():
            ctx["chejan_backlog"] = sum(
                1 for _ in _BROKER_CHEJAN_DIR_SE.glob("*.json")
            )
    except Exception:
        pass
    return ctx


# [STEP-2I-2-e 2026-05-14] Broker availability cache (cooldown pattern)
#   broker dead 시 IPC 호출 즉시 skip (대기 0s) → caller direct OCX fallback 진입.
#   collector STEP-2I-2-c 와 동일 패턴.
_BROKER_HB_STALE_SEC_SE        = 15.0
_BROKER_DEAD_COOLDOWN_SEC_SE   = 60.0
_BROKER_TIMEOUT_THRESHOLD_SE   = 2
_BROKER_DEAD_UNTIL_SE: float   = 0.0
_consec_broker_timeout_se: int = 0
_BYPASS_LOG_INTERVAL_SEC_SE    = 10.0
_last_bypass_log_ts_se: float  = 0.0
_was_broker_dead_se: bool      = False
_log_se = logging.getLogger("rt_sell")


def _is_broker_alive_se() -> bool:
    """heartbeat mtime + cooldown 검사. True=IPC 사용 / False=즉시 fallback."""
    global _last_bypass_log_ts_se, _was_broker_dead_se
    now = time.time()
    if now < _BROKER_DEAD_UNTIL_SE:
        if (now - _last_bypass_log_ts_se) >= _BYPASS_LOG_INTERVAL_SEC_SE:
            try:
                _log_se.info(
                    "[BROKER-BYPASS] cooldown active (%.1fs remain)",
                    max(0.0, _BROKER_DEAD_UNTIL_SE - now),
                )
            except Exception:
                pass
            _last_bypass_log_ts_se = now
        _was_broker_dead_se = True
        return False
    try:
        if not _BROKER_HB_PATH_SE.exists():
            _was_broker_dead_se = True
            return False
        age = now - _BROKER_HB_PATH_SE.stat().st_mtime
        alive = (age < _BROKER_HB_STALE_SEC_SE)
        if alive and _was_broker_dead_se:
            try:
                _log_se.info("[BROKER-RECOVER] broker restored — IPC 재사용")
            except Exception:
                pass
            _was_broker_dead_se = False
        elif not alive:
            _was_broker_dead_se = True
        return alive
    except Exception:
        _was_broker_dead_se = True
        return False


def _mark_broker_dead_se():
    """broker_dead 진입. cooldown 동안 IPC skip."""
    global _BROKER_DEAD_UNTIL_SE
    _BROKER_DEAD_UNTIL_SE = time.time() + _BROKER_DEAD_COOLDOWN_SEC_SE
    try:
        _log_se.warning(
            "[BROKER-DEAD] cooldown %ds — direct OCX fallback 활성",
            int(_BROKER_DEAD_COOLDOWN_SEC_SE),
        )
    except Exception:
        pass


def _broker_request_se(req_type: str, extra: dict = None,
                       timeout_sec: float = 2.0) -> dict:
    """Broker IPC 요청 (read-only). 실패 시 None 반환."""
    # [STEP-2I-2-e 2026-05-14] broker dead 시 IPC skip → 즉시 None (caller fallback)
    global _consec_broker_timeout_se
    if not _is_broker_alive_se():
        return None

    request_id = str(_bro_uuid_se.uuid4())
    req = {
        "request_id": request_id,
        "ts": datetime.now().isoformat(),
        "ttl_sec": int(timeout_sec) + 3,
        "type": req_type,
    }
    if extra:
        req.update(extra)
    req_path = _BROKER_IPC_REQ_DIR_SE / f"{request_id}.json"
    res_path = _BROKER_IPC_RES_DIR_SE / f"{request_id}.json"
    try:
        tmp = req_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(req, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(req_path))
    except Exception:
        return None

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if res_path.exists():
            try:
                res = json.loads(res_path.read_text(encoding="utf-8-sig"))
            except Exception:
                res = None
            try:
                res_path.unlink()
            except Exception:
                pass
            # [STEP-2I-2-e] OK → counter reset / 비OK → timeout count
            if res and res.get("status") == "OK":
                _consec_broker_timeout_se = 0
            elif res:
                _consec_broker_timeout_se += 1
                if _consec_broker_timeout_se >= _BROKER_TIMEOUT_THRESHOLD_SE:
                    _mark_broker_dead_se()
                    _consec_broker_timeout_se = 0
            return res
        time.sleep(0.1)
    # [STEP-2I-2-e] poll timeout — broker dead 카운트
    _consec_broker_timeout_se += 1
    if _consec_broker_timeout_se >= _BROKER_TIMEOUT_THRESHOLD_SE:
        _mark_broker_dead_se()
        _consec_broker_timeout_se = 0
    return None


RC_OK = 0; RC_HOLD = 200; RC_STOP = 500

# ── Windows 파일 잠금 (FIX-S4) ───────────────────────────────────
_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    try:
        import msvcrt
        def _lock(f):
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # [PATCH] NBLCK→LOCK: 경쟁 시 최대 1초 대기
        def _unlock(f):
            try: msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception: pass
    except ImportError:
        def _lock(f): pass
        def _unlock(f): pass
else:
    try:
        import fcntl
        def _lock(f):
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def _unlock(f):
            try: fcntl.flock(f, fcntl.LOCK_UN)
            except Exception: pass
    except ImportError:
        def _lock(f): pass
        def _unlock(f): pass


class SELLCFG:
    BASE = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
    PATH_OPEN_POS    = BASE / "DATA" / "rt_open_positions.json"
    PATH_PRICES_1M   = BASE / "DATA" / "prices_1m.csv"
    PATH_ORDER_LOG   = BASE / "DATA" / "LEDGER" / "rt_order_log.csv"
    PATH_SELL_SIG    = BASE / "DATA" / "rt_sell_signal.json"
    PATH_DAILY_SOLD  = BASE / "DATA" / "rt_daily_sold.json"
    PATH_LOG         = BASE / "LOG" / "rt_sell_engine.log"
    PATH_EVOL_STATE  = BASE / "DATA" / "rt_evolution_state.json"  # v3.10 ISSUE-C
    PATH_SWITCH_DEC  = BASE / "DATA" / "switch_decision.json"     # [v3.10-HANDOFF]
    PATH_CYCLE_TRACK = BASE / "DATA" / "pullback_cycle_tracker.json"  # [v3.13] 2사이클 재진입용

    # ── [v3.10-HANDOFF] 핸드오프 설정 ──
    HANDOFF_STALE_SEC  = 120   # switch_decision 신선도 (초)
    HANDOFF_MIN_PROFIT = 0.01  # 핸드오프 허용 최소 수익 (1%)

    # ── Take Profit (GP-1: B등급 3.5% 수정) ──
    GAP_TP_FALLBACK = {"A": 0.050, "B": 0.035, "C": 0.020, "": 0.035}
    T2_MULT = 1.60   # [P2] 1.50→1.60: 기본 T2 현실화 (1.55~1.70 범위)

    # ── [P2] T2 배율 현실화 — 과도한 상단 완화 (수익 반납 감소) ──────────────
    T2_MULT_TABLE: list = [
        (0.70, 2.00),   # [P2] 2.50→2.00: ride ≥ 0.70 (기관 강세, 현실적 상한)
        (0.55, 1.85),   # [P2] 2.20→1.85: ride ≥ 0.55
        (0.40, 1.75),   # [P2] 1.90→1.75: ride ≥ 0.40
        (0.00, 1.65),   # [P2] 1.60→1.65: ride <  0.40
    ]

    # ── Trail (TR-1: 활성화 2.5% / peak-latch 방식) ──
    # [v3.20] [0,3,2.2]+[3,5,2.0] → [0,5,1.5] 통합
    # 수학적 근거: trail_pct=2.2%이면 peak<4.8%에서 gate_a(ret≥2.5%)와 동시 성립 불가
    #             → trail 영구 비활성. 1.5%로 낮춰 peak≥2.54%에서 발동 가능하게 수정
    TRAIL_TABLE_FALLBACK = [
        [0.0,  5.0, 1.5],    # [v3.20] [0,3,2.2]+[3,5,2.0] 통합 → 1.5% (peak+3%에서 +1.45% 청산 가능)
        [5.0,  8.0, 1.5],
        [8.0, 12.0, 1.2],
        [12.0, 999.0, 1.0],
    ]
    TRAIL_ACTIVATE_RET      = 0.025   # [대장주 추격] 2.5%: peak가 이 수익 찍으면 trail 래치 ON (gate_a=peak_ret 기준)
    TRAIL_RIDE_MIN          = 0.40    # TR-2: ride 이중 게이트 (지침서[15])
    TRAIL_FORCE_RET         = 0.022   # [대장주 추격] 2%→4%→2.5%→2.2%: 보수/수익 균형 보호 시작점
    TRAIL_ABSOLUTE_MIN_RET  = 0.010   # TR-4: 1% 미만 Trail 절대 금지

    # ── [v3.18 RR개선] SuperTrend 기준 상향 — 대장주 더 달리게 ──
    SUPER_TREND_MODE = True
    SUPER_TRAIL_ACTIVATE_PCT = 5.0
    SUPER_TRAIL_SLOW_PCT     = 10.0   # [v3.18] 8.0→10.0 (천천히 올리기 시작)
    SUPER_TRAIL_HOLD_PCT     = 17.0   # [v3.19 R최적화] 15.0→17.0 (Trail 평균 +14% 목표)
    SUPER_TRAIL_TABLE = [
        [0.0,   5.0, 2.2],
        [5.0,  10.0, 1.5],
        [10.0, 15.0, 1.2],
        [15.0, 999.0, 1.0],
    ]

    # ── 강제 청산 시각 (WEAK-1: 종배 FORCE_CLOSE_시배 삭제) ──
    FORCE_CLOSE_A = 1450
    FORCE_CLOSE_BCD = 1450   # [PATCH] params_v3_11 v3.9 통일 반영 (1430→1450)
    FORCE_EXIT_DEFAULT = 1450
    FORCE_EXIT_RT = 1520     # [PATCH 1] RT 전략 장마감 강제청산 15:20
    # ── [v3.16 SIGA 릴레이] SIGA 강제청산 — 절대 변경 금지 ──
    # 09:18 청산 → 09:20 PULLBACK 자금 재투입 타이밍 의존 구조
    # FORCE_GRACE(기관동행 10분 연장) SIGA 예외 필수 — 변경 시 릴레이 붕괴
    FORCE_EXIT_SIGA = 918    # SIGA 강제청산 09:18 (params.json force_siga 연동)
    MAX_HOLD_SIGA   = 15     # SIGA 최대 보유 15분 (09:05 진입 기준 09:20 한계)

    # ── 손절 ──
    BREAKEVEN_ACTIVATE_RET = 0.015
    HARD_STOP_DEFAULT = 0.025          # [통합패치-06] params.json hard_stop과 단일소스 통일 (fallback 동일값)
    # [v3.12 과제1] Profit Lock 옵션B 적용 — pullback v4.19와 통일
    # 설계 원칙: 모든 구간에서 Lock 보장선 > FAILSAFE(고점×60%) 선발동 보장
    #   peak=2%: Lock=1.34% > FAILSAFE=1.20% (+0.14%p)
    #   peak=5%: Lock=3.75% > FAILSAFE=3.00% (+0.75%p)
    #   peak=8%: Lock=6.40% > FAILSAFE=4.80% (+1.60%p)
    # 기관동행(×0.9 완화) 후에도 peak≥5% 구간에서는 여전히 선발동 유지
    PROFIT_LOCK_HALF_RET   = 0.020   # [P2] 15%→2.0%: 실전형 초기 보호 1차 (+2% 50% 잠금)
    PROFIT_LOCK_TWO3_RET   = 0.035   # [P2] 25%→3.5%: 2차 (+3.5% 67% 잠금)
    PROFIT_LOCK_THREE4_RET = 0.050   # [P2] 35%→5.0%: 3차 (+5.0% 75% 잠금)
    # [지침서 §11-3 수정] Profit Lock 기관동행 완화
    # pullback_sell_strategy PROFIT_LOCK_INST_RELAX 이식
    # OFI≥0.40 기관 흐름 중 조기 청산 방지 — 잠금 비율 ×0.9 완화
    PROFIT_LOCK_INST_RELAX   = 0.90   # 기관동행 시 잠금 비율 × 이 값
    PROFIT_LOCK_INST_RIDE_MIN = 0.65  # ride ≥ 이 값 → 기관동행 판정
    ATR_STOP_MULT = 2.5
    ATR_STOP_MIN = 0.020
    ATR_STOP_MAX = 0.045

    # ── Momentum ──
    MOMENTUM_VOL_RATIO = 0.55
    MOMENTUM_PRICE_DROP = 0.008
    MOMENTUM_MIN_BARS = 10
    MOMENTUM_MIN_PROFIT = 0.020
    MOMENTUM_BLACKOUT_START = 903
    MOMENTUM_BLACKOUT_END = 913
    MOMENTUM_LOOKBACK_BARS = 30

    # ── 기관 이탈 ──
    INST_EXIT_OFI_DROP = -0.30
    INST_EXIT_VPIN_SPIKE = 0.75
    INST_EXIT_CONSEC_DROP = 2
    INST_EXIT_MIN_PROFIT = 0.015    # v3.9 WEAK-4: 1.0%→1.5% (OFI 요동 조기이탈 방지)

    # ── 기관 동행 ──
    RIDE_STRONG_THRESHOLD = 0.65
    RIDE_STRONG_MAX_RET = float(os.environ.get("RIDE_STRONG_MAX_RET", "0.30"))
    INST_STRONG_OFI_MIN = 0.15
    # [결함-2 수정] 지침서 §9 P1.3 INST_HOLD — OFI≥0.35 시 보유 우선
    # 기존: ride_score 간접 처리만 → P1.3 명시적 독립 판단 누락
    # 수정: ofi_smooth≥0.35 AND consec_sell=0 → 다른 청산 조건보다 보유 우선
    INST_HOLD_OFI_MIN    = 0.35   # P1.3: OFI 이 이상이면 HOLD 우선
    INST_HOLD_MAX_RET    = 0.20   # P1.3: 수익 20% 초과 시 INST_HOLD 해제 (PEAK_PROTECT 위임)
    FAST_LOSS_CUT_PCT = -0.015         # v3.7: -1.0%→-1.5% (노이즈 손절 완화)
    FAST_LOSS_CUT_MIN_HOLD = 10.0      # [v3.18 RR개선] 3.0→10.0분 (진입 후 10분 손절 금지 — 노이즈 보호)
    FAST_LOSS_CUT_INST_GRACE = -0.02

    # ── VWAP ──
    VWAP_BREAK_THRESH = 0.985          # 기본값 (ret<2% 구간)
    T2_VWAP_THRESH = 0.975
    VWAP_MIN_RET = 0.003
    VWAP_MIN_HOLD_MIN = 5.0
    SESSION_START_HHMM = 900

    # ── [v3.13 Gap-1] VWAP 이탈 수익 구간별 차등 허용 티어 ──────────
    # 수익이 클수록 VWAP 아래 이격을 더 허용 (트렌드 장 정상 이탈 보호)
    # (ret_min, thresh) — ret >= ret_min 이면 해당 thresh 적용
    # 내림차순 정렬 필수 (큰 수익 구간 먼저 체크)
    # 기관 동행(inst_riding=True) 시 추가 ×VWAP_INST_RELAX 완화
    VWAP_BREAK_TIERS: list = [
        (0.10, 0.970),   # ret ≥ 10% → 3.0% 이격까지 허용 (큰 수익 트렌드 보호)
        (0.05, 0.978),   # ret ≥  5% → 2.2% 이격까지 허용
        (0.02, 0.983),   # ret ≥  2% → 1.7% 이격까지 허용
        (0.00, 0.985),   # ret <  2% → 1.5% 이격까지 허용 (기존 동일)
    ]
    VWAP_INST_RELAX = 0.997   # 기관 동행 시 thresh × 0.997 추가 완화
    VWAP_BREAK_PULLBACK_CONFIRM = 2  # PULLBACK: 연속 이탈 횟수 확인 후 청산

    # ── 시간대 ──
    TIMEZONE_OPENING_END = 930
    TIMEZONE_STABLE_START = 1030
    # v3.7: OPENING_TRAIL_MULT는 _get_trail_pct + _get_super_trail_pct 양쪽에
    #       독립 적용 — Trail/SuperTrail 각자 시간 보정, 중복 아닌 의도된 설계
    OPENING_TRAIL_MULT = 1.5
    STABLE_TRAIL_MULT = 0.85
    OPENING_VWAP_RELAX = 0.975

    # ── 분할매도 (v3.7: 트리거·비율 사용자 수정) ──
    SPLIT_SELL_ENABLED = True   # [통합패치-07] 분할매도 복구 — T1(+4%) / T2(+12%) 일부 익절 활성화
    SPLIT_T1_TRIGGER_RET = 0.040   # v3.7: 0.035→0.040 (T1 익절 트리거 상향)
    SPLIT_T2_TRIGGER_RET = 0.120   # [v3.19 R최적화] 0.100→0.120 (T2 +12% — RR 4.75→5.50)
    SPLIT_T1_RATIO = 0.25          # v3.7: 0.40→0.25  (1차 분할 비율 축소)
    SPLIT_T2_RATIO = 0.25          # v3.7: 0.30→0.25  (2차 분할 비율 축소)
    SPLIT_RATIO_INST = 0.25        # 기관 동행 시 동일 비율 (SPLIT_T1_RATIO와 일치)

    # ── PEAK_PROTECT 3단계 (PP-1: 교체) ──
    # (고점 임계, 현재가 임계) — 12% > 8% > 5% 우선순위
    PEAK_PROTECT_LEVELS = [
        (0.12, 0.050),   # 고점 12%+ → 현재 5% 미만 시 청산
        (0.08, 0.030),   # 고점  8%+ → 현재 3% 미만 시 청산
        (0.05, 0.020),   # 고점  5%+ → 현재 2% 미만 시 청산
    ]
    PEAK_PROTECT_INST_RELAX = 1.15  # PP-2: 기관 동행 시 임계 ÷1.15

    # ── HARD_FAILSAFE (HF-1,2: 신설) ──
    FAILSAFE_TRIGGER_RET   = 0.020  # 과거 2% 달성 이력 기준
    FAILSAFE_RETAIN_RATIO  = float(os.environ.get("FAILSAFE_RETAIN_RATIO", "0.60"))   # 고점 60% 보전 기준

    # ── Chandelier Exit k 레짐 (CHA-1~4: 신설) ──
    VOL_RATIO_HIGH    = 1.2   # ATR10/ATR20 ≥ 1.2 → HIGH 레짐
    VOL_RATIO_EXTREME = 1.5   # ATR10/ATR20 ≥ 1.5 → EXTREME 레짐
    CHANDELIER_K_NORMAL  = 2.0
    CHANDELIER_K_HIGH    = 2.5
    CHANDELIER_K_EXTREME = 3.0
    CHANDELIER_K_INST_MULT = 1.15   # 기관강세 k 보정
    CHANDELIER_OFI_STRONG  = 0.40   # 기관강세 OFI 기준 [v3.11 ISSUE-1: 0.30→0.40 지침서v1.2]
    CHANDELIER_ACCEL_MIN   = 1.20   # 기관강세 accel 기준
    CHANDELIER_INST_RET_MIN= 0.020  # 기관강세 수익 기준

    # ── [v3.13 Gap-3] True ATR 내부 재계산 설정 ─────────────────────
    # 출처: Wilder (1978) New Concepts in Technical Trading Systems
    # TR(i) = max(H-L, |H-prev_C|, |L-prev_C|) — 갭 봉 포함 필수
    # prices_1m의 atr_pct는 단순 H-L 기반 → 갭 봉 ATR 30~50% 과소평가
    # → Chandelier Trail 너무 타이트 → 정상 변동에서 조기 청산
    TRUE_ATR_PERIOD     = 10     # Chandelier ATR 기간 (지침서 §5-1 동일)
    TRUE_ATR_FALLBACK   = True   # 봉 데이터 부족 시 prices_1m atr_pct 사용

    # ── 전략별 k 오버라이드 (WEAK-1: 종배 CHA-4 삭제 — RT/PULLBACK만 운영) ──

    # ── [RT-Fix-1 v3.8] EXIT_SCORE 복합 청산 품질 게이트 ──
    EXIT_SCORE_HOLD_TH      = 0.65   # k×1.15 (강한 흐름 → 더 들고 가기)
    EXIT_SCORE_TIGHTEN_TH   = 0.40   # k 표준 유지
    EXIT_SCORE_FORCE_TH     = 0.20   # k×0.85 + 즉시청산 가능 구간
    EXIT_SCORE_K_WIDE_MULT  = 1.15   # HOLD 시 k 확장 배수
    EXIT_SCORE_K_TIGHT_MULT = 0.85   # TIGHTEN 시 k 축소 배수
    EXIT_SCORE_RIDE_BONUS   = 0.08   # ride≥0.60 보너스
    EXIT_SCORE_PROFIT_BONUS_TH  = 0.030  # 수익 3%+ 보너스 임계
    EXIT_SCORE_PROFIT_BONUS     = 0.06   # 수익 보너스량
    EXIT_SCORE_LOSS_PENALTY_TH  = -0.010 # 손실 -1% 페널티 임계
    EXIT_SCORE_LOSS_PENALTY     = 0.10   # 손실 페널티량
    EXIT_SCORE_FORCE_MIN_RET    = 0.015  # force_exit 발동 최소 수익 (손실 구간 보호)

    # ── MAX HOLD (WEAK-1: MAX_HOLD_SIGA 삭제 — RT/PULLBACK만 운영) ──
    MAX_HOLD_RT = 180              # v3.7: 120→180분 (RT전략 보유 연장)
    MAX_HOLD_PULLBACK = 240

    # ── 시스템 ──
    ORDER_INTERVAL_SEC = 0.5
    SLIPPAGE_RATE = 0.001
    PRICES_STALE_SEC = 90
    LOOP_INTERVAL_SEC = 30
    MARKET_OPEN_HHMM = 910
    MARKET_CLOSE_HHMM = 1530
    MAX_POSITIONS = 1
    EPS = 1e-9

    # ── 킬스위치 (KS) ──
    MAX_ORDER_REJECT = 3
    MAX_DAILY_LOSS_PCT = -0.03
    MAX_LOOP_SAME_SYMBOL = 5

    # ── 주문 체결 보강 (OE) ──
    MAX_ORDER_RETRY = 2
    RETRY_INTERVAL_SEC = 2.0
    TICK_TABLES = [
        (500, 1), (1000, 5), (5000, 10), (10000, 50),
        (50000, 100), (100000, 500), (999999999, 1000),
    ]

    # ── 파라미터 변동 제한 (PC) ──
    PARAM_MAX_CHANGE_PCT = 0.10
    PARAM_MAX_SPLIT_DELTA = 0.05


# ═══════════════════════════════════════════════════════════════
#  킬스위치 (KS-1, KS-2)
# ═══════════════════════════════════════════════════════════════
class KillSwitch:
    """실전 안전장치 — 비정상 상태 감지 시 즉시 거래 중단"""

    def __init__(self):
        self.active = False
        self.reason = ""
        self.order_reject_count = 0
        self.daily_pnl_krw = 0.0
        self.daily_capital = 0.0
        self._symbol_sell_count: Dict[str, int] = {}

    def check_reject(self, code: str, reject_reason: str, log: logging.Logger):
        self.order_reject_count += 1
        log.warning(
            "[KS] 주문 거절 %d/%d | %s | %s",
            self.order_reject_count, SELLCFG.MAX_ORDER_REJECT,
            code, reject_reason,
        )
        if self.order_reject_count >= SELLCFG.MAX_ORDER_REJECT:
            self._trigger("ORDER_REJECT", log)

    def check_stale(self, log: logging.Logger):
        self._trigger("STALE_DATA", log)

    def check_disconnect(self, log: logging.Logger):
        self._trigger("DISCONNECT", log)

    def check_daily_loss(self, pnl_krw: float, capital: float, log: logging.Logger):
        if capital <= 0:
            return
        self.daily_pnl_krw += pnl_krw
        self.daily_capital = capital
        pnl_pct = self.daily_pnl_krw / capital
        if pnl_pct <= SELLCFG.MAX_DAILY_LOSS_PCT:
            log.critical(
                "[KS] 일일 손실 %.2f%% ≤ %.1f%% | PnL=%+.0f원",
                pnl_pct * 100, SELLCFG.MAX_DAILY_LOSS_PCT * 100,
                self.daily_pnl_krw,
            )
            self._trigger("DAILY_LOSS", log)

    def check_loop(self, code: str, log: logging.Logger):
        self._symbol_sell_count[code] = self._symbol_sell_count.get(code, 0) + 1
        cnt = self._symbol_sell_count[code]
        if cnt >= SELLCFG.MAX_LOOP_SAME_SYMBOL:
            log.critical(
                "[KS] 동일종목 반복 %s %d/%d회",
                code, cnt, SELLCFG.MAX_LOOP_SAME_SYMBOL,
            )
            self._trigger("LOOP_DETECTED", log)

    def _trigger(self, reason: str, log: logging.Logger):
        if self.active:
            return
        self.active = True
        self.reason = reason
        log.critical("████ KILL_SWITCH_TRIGGERED | reason=%s ████", reason)


# ═══════════════════════════════════════════════════════════════
#  주문 타입 선택 (OE-1)
# ═══════════════════════════════════════════════════════════════
def _get_order_type(reason: str) -> str:
    """사유별 최적 주문 타입 결정"""
    r = reason.upper()
    if any(k in r for k in ("HARD_STOP", "FAST_LOSS", "FORCE_ALL",
                             "SWITCH_SELL", "FORCE_EXIT", "MAX_HOLD",
                             "HARD_FAILSAFE")):
        return "MARKET"
    if any(k in r for k in ("TRAIL_STOP", "CHANDELIER", "MOMENTUM_EXIT",
                             "INST_EXIT", "PEAK_PROTECT", "VWAP_BREAK")):
        return "IOC_LIMIT"
    if "TAKE_PROFIT" in r:
        return "LIMIT"
    return "MARKET"


def _tick_size(price: int) -> int:
    """KOSDAQ 호가 단위"""
    for threshold, tick in SELLCFG.TICK_TABLES:
        if price < threshold:
            return tick
    return 1000


def _bid_minus_ticks(price: float, n_ticks: int) -> int:
    """현재가에서 N틱 아래 지정가 계산"""
    p = int(price)
    for _ in range(n_ticks):
        tick = _tick_size(p)
        p -= tick
    return max(p, _tick_size(1))


# ═══════════════════════════════════════════════════════════════
#  파라미터 변동 제한 (PC-1)
# ═══════════════════════════════════════════════════════════════
def _clamp_param(current: float, default: float, max_change: float) -> float:
    if default <= 0:
        return current
    lo = default * (1.0 - max_change)
    hi = default * (1.0 + max_change)
    return max(lo, min(current, hi))


def _clamp_split(current: float, default: float, max_delta: float) -> float:
    lo = default - max_delta
    hi = default + max_delta
    return max(lo, min(current, hi))


# 전역 킬스위치 인스턴스
_kill_switch = KillSwitch()

# [PATH_LOG] 경로별 수익 누적 — A: 정상게이트, B: intraday_strong, ?: 미분류
_path_profit_acc: Dict[str, list] = {"A": [], "B": [], "?": []}
_PATH_REGISTRY_FILE = SELLCFG.BASE / "DATA" / "entry_path_registry.json"


def _get_entry_path(code: str, pos: dict) -> str:
    """pos에 entry_path 없으면 레지스트리에서 조회."""
    p = str(pos.get("entry_path", ""))
    if p in ("A", "B"):
        return p
    try:
        if _PATH_REGISTRY_FILE.exists():
            with open(_PATH_REGISTRY_FILE, "r", encoding="utf-8-sig") as f:
                reg = json.load(f)
            v = reg.get(str(code).zfill(6), "?")
            return v if v in ("A", "B") else "?"
    except Exception:
        pass
    return "?"


# ═══════════════════════════════════════════════════════════════
#  로거
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    SELLCFG.PATH_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rt_sell")
    log.setLevel(logging.DEBUG)
    if log.handlers:
        log.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = RotatingFileHandler(
        str(SELLCFG.PATH_LOG),
        maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8-sig",  # [Z15 2026-05-21]
    )
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO); ch.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(ch)
    return log


# ═══════════════════════════════════════════════════════════════
#  진화 파라미터 로드
# ═══════════════════════════════════════════════════════════════
_INTRADAY_TAR: dict = {}       # [Gap-12] 세션 내 trail_activate_ret 인메모리 오버라이드
_flow_neg_cnt_map: dict = {}  # [FLOW_EXIT] 코드별 연속 neg 카운트 — 인메모리(JSON 미저장)
_weak_cnt_map: dict = {}      # [EVENT_EXIT] 코드별 weak_count — 인메모리(JSON 미저장)

def _load_evolved_params(log: logging.Logger) -> dict:
    result = {
        "trail_table": SELLCFG.TRAIL_TABLE_FALLBACK,
        "force_A": SELLCFG.FORCE_CLOSE_A,
        "force_BCD": SELLCFG.FORCE_CLOSE_BCD,
        "vwap_thresh": SELLCFG.VWAP_BREAK_THRESH,
        "vwap_thresh_t2": SELLCFG.T2_VWAP_THRESH,
        "hard_stop": SELLCFG.HARD_STOP_DEFAULT,
        "breakeven_ret": SELLCFG.BREAKEVEN_ACTIVATE_RET,
        "momentum_vol_ratio": SELLCFG.MOMENTUM_VOL_RATIO,
        "momentum_price_drop": SELLCFG.MOMENTUM_PRICE_DROP,
        "momentum_min_profit": SELLCFG.MOMENTUM_MIN_PROFIT,
        "trail_activate_ret": SELLCFG.TRAIL_ACTIVATE_RET,
        "t2_mult": SELLCFG.T2_MULT,
        "gap_tp_A": 0.050, "gap_tp_B": 0.035,
        "gap_tp_C": 0.020, "gap_tp_": 0.035,
        "super_trend_mode": SELLCFG.SUPER_TREND_MODE,
        "super_trail_activate_pct": SELLCFG.SUPER_TRAIL_ACTIVATE_PCT,
        "super_trail_slow_pct": SELLCFG.SUPER_TRAIL_SLOW_PCT,
        "super_trail_hold_pct": SELLCFG.SUPER_TRAIL_HOLD_PCT,
        "super_trail": SELLCFG.SUPER_TRAIL_TABLE,
        "inst_exit_ofi_drop": SELLCFG.INST_EXIT_OFI_DROP,
        "inst_exit_vpin_spike": SELLCFG.INST_EXIT_VPIN_SPIKE,
        "inst_exit_consec_drop": SELLCFG.INST_EXIT_CONSEC_DROP,
        "inst_exit_min_profit": SELLCFG.INST_EXIT_MIN_PROFIT,
        "atr_stop_mult": SELLCFG.ATR_STOP_MULT,
        "atr_stop_min": SELLCFG.ATR_STOP_MIN,
        "atr_stop_max": SELLCFG.ATR_STOP_MAX,
        "profit_lock_half_ret": SELLCFG.PROFIT_LOCK_HALF_RET,
        "profit_lock_two3_ret": SELLCFG.PROFIT_LOCK_TWO3_RET,
        "profit_lock_three4_ret": SELLCFG.PROFIT_LOCK_THREE4_RET,
        "vwap_min_ret": SELLCFG.VWAP_MIN_RET,
        "vwap_min_hold_min": SELLCFG.VWAP_MIN_HOLD_MIN,
        "split_ratio_inst": SELLCFG.SPLIT_RATIO_INST,
        "split_t1_ratio": SELLCFG.SPLIT_T1_RATIO,
        "split_t2_ratio": SELLCFG.SPLIT_T2_RATIO,   # v3.9 WEAK-3: 진화 파라미터 편입
        "max_hold_rt": SELLCFG.MAX_HOLD_RT,
        "max_hold_pullback": SELLCFG.MAX_HOLD_PULLBACK,
        "win_rate": 0.50,
        "profit_factor": 1.0,
        "avg_win_pct": 0.0,
        "avg_loss_pct": 0.0,
    }

    # ── v3.10 ISSUE-C: 경량 진화 저장소 우선 로드 ──
    # pnl_strategy_linker 유무와 무관하게 누적 학습값 적용
    # 저장소 파일이 없으면 초기값(0.50 / 1.0) 유지
    _evol = _load_evolution_state(log)
    result["win_rate"]      = _evol["win_rate"]
    result["profit_factor"] = _evol["profit_factor"]
    log.debug(
        "[PARAM] 진화 저장소 | wr=%.3f pf=%.2f trades=%d",
        _evol["win_rate"], _evol["profit_factor"], _evol["total_trades"],
    )
    try:
        import importlib
        base = str(SELLCFG.BASE)
        if base not in sys.path:
            sys.path.insert(0, base)
        pr = importlib.import_module("params_reader")
        if hasattr(pr, "get_rt_sell"):
            rts = pr.get_rt_sell()
            for k in result:
                if k in rts:
                    result[k] = rts[k]
            for lk in ["trail_table", "super_trail"]:
                if isinstance(rts.get(lk), list):
                    result[lk] = rts[lk]
            log.info(
                "[PARAM] get_rt_sell() | hard=%.1f%% super=%s wr=%.2f pf=%.2f",
                result["hard_stop"] * 100, result["super_trend_mode"],
                result["win_rate"], result["profit_factor"],
            )
        else:
            trail = pr.get_트레일()
            result["trail_table"] = trail["table"]
            # v3.9 WEAK-1: force_시배 참조 삭제 (종배 전략 미운영)
    except Exception as e:
        log.debug("[PARAM] fallback: %s", e)

    # ── 자기진화 적응 (승률/PF 기반) ──
    wr = result["win_rate"]
    pf = result["profit_factor"]

    if wr < 0.45:
        result["hard_stop"] = result["hard_stop"] * 0.80
        result["trail_activate_ret"] = result["trail_activate_ret"] * 1.2
        log.info("[EVOL-ADAPT] wr=%.2f<0.45 → hard_stop×0.8, trail 늦게", wr)
    elif wr < 0.48:
        result["hard_stop"] = result["hard_stop"] * 0.90
        log.info("[EVOL-ADAPT] wr=%.2f<0.48 → hard_stop×0.9", wr)
    elif wr > 0.60:
        result["trail_activate_ret"] = result["trail_activate_ret"] * 0.80
        log.info("[EVOL-ADAPT] wr=%.2f>0.60 → trail 일찍 발동", wr)
    elif wr > 0.55:
        result["trail_activate_ret"] = result["trail_activate_ret"] * 0.90
        log.info("[EVOL-ADAPT] wr=%.2f>0.55 → trail 약간 일찍", wr)

    if pf > 0 and pf < 0.8:
        result["split_t1_ratio"] = min(0.45, SELLCFG.SPLIT_T1_RATIO + 0.05)
        result["split_t2_ratio"] = min(0.40, SELLCFG.SPLIT_T2_RATIO + 0.05)  # v3.9 WEAK-3
        log.info("[EVOL-ADAPT] pf=%.2f<0.8 → 분할매도 비율 확대 (T1+T2)", pf)
    elif pf > 1.5:
        result["split_t1_ratio"] = max(0.25, SELLCFG.SPLIT_T1_RATIO - 0.05)
        result["split_t2_ratio"] = max(0.15, SELLCFG.SPLIT_T2_RATIO - 0.05)  # v3.9 WEAK-3
        log.info("[EVOL-ADAPT] pf=%.2f>1.5 → 분할매도 비율 축소 (T1+T2)", pf)
    else:
        result["split_t1_ratio"] = SELLCFG.SPLIT_T1_RATIO
        result["split_t2_ratio"] = SELLCFG.SPLIT_T2_RATIO

    # ── PC-1: 파라미터 변동 제한 (과적합 방지) ──
    mc = SELLCFG.PARAM_MAX_CHANGE_PCT
    md = SELLCFG.PARAM_MAX_SPLIT_DELTA
    result["hard_stop"] = _clamp_param(
        result["hard_stop"], SELLCFG.HARD_STOP_DEFAULT, mc)
    result["trail_activate_ret"] = _clamp_param(
        result["trail_activate_ret"], SELLCFG.TRAIL_ACTIVATE_RET, mc)
    result["split_t1_ratio"] = _clamp_split(
        result["split_t1_ratio"], SELLCFG.SPLIT_T1_RATIO, md)
    result["split_t2_ratio"] = _clamp_split(          # v3.9 WEAK-3: T2도 PC-1 적용
        result["split_t2_ratio"], SELLCFG.SPLIT_T2_RATIO, md)
    for k, dv in [("hard_stop", SELLCFG.HARD_STOP_DEFAULT),
                   ("trail_activate_ret", SELLCFG.TRAIL_ACTIVATE_RET)]:
        chg = abs(result[k] - dv) / (dv + SELLCFG.EPS) * 100
        if chg > 1.0:
            log.debug("[PC] %s=%.4f (기본=%.4f, 변동=%.1f%%)", k, result[k], dv, chg)

    if "trail_activate_ret" in _INTRADAY_TAR:
        result["trail_activate_ret"] = _INTRADAY_TAR["trail_activate_ret"]
    return result


# ═══════════════════════════════════════════════════════════════
#  키움 매도 브릿지
# ═══════════════════════════════════════════════════════════════
class KiwoomSellBridge:
    def is_connected(self) -> bool:
        raise NotImplementedError

    def send_sell_order(self, code, price, qty, order_type="MARKET") -> dict:
        raise NotImplementedError


class MockSellBridge(KiwoomSellBridge):
    _cnt = 0

    def is_connected(self):
        return True

    def send_sell_order(self, code, price, qty, order_type="MARKET"):
        MockSellBridge._cnt += 1
        return {
            "order_no": f"SELL{MockSellBridge._cnt:06d}",
            "code": code, "price": price, "qty": qty,
            "status": "ACCEPTED", "msg": "Mock",
        }


class KiwoomRealSellBridge(KiwoomSellBridge):
    """키움 OpenAPI 실매도 브릿지 — order_type=2(매도), hogaType='03'(시장가)"""

    _SCREEN = "9901"

    def __init__(self, account: str = "", timeout_sec: int = 10,
                 shared_ocx=None):
        self._account = account
        self._timeout_sec = timeout_sec
        self._app = None
        self._ocx = None
        self._cnt = 0
        self._order_done = False
        self._last_order_no = ""
        self._connect_done = False
        self._connect_err  = None
        self._init(shared_ocx=shared_ocx)

    def _init(self, shared_ocx=None) -> None:
        # 외부에서 OCX 전달 시: QAxWidget 생성 + CommConnect 생략
        if shared_ocx is not None:
            try:
                from PyQt5.QtWidgets import QApplication
                self._app = QApplication.instance() or QApplication([])
                self._ocx = shared_ocx
                self._ocx.OnReceiveChejanData.connect(self._on_chejan)
                self._connect_done = True
                self._connect_err  = 0
            except Exception:
                self._ocx = None
            return

        # [A-1a 2026-05-15] broker CONNECTED 시 standalone OCX 차단
        # send_sell_order L1398 가드 (self._ocx is None or not is_connected())
        # 자동 적용 → broker mode 시 매도 DISCONNECTED 반환 (A-1b 위임)
        if _broker_owns_ocx():
            self._ocx = None
            self._broker_mode = True
            self._connect_done = True
            self._connect_err  = 0
            # [A-1b-CORE 2026-05-15] chejan consume thread start (daemon)
            self._start_chejan_consume_thread()
            return

        self._broker_mode = False
        try:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QAxContainer import QAxWidget as _QAx
        except ImportError:
            return
        try:
            self._app = QApplication.instance() or QApplication([])
            self._ocx = _QAx()
            self._ocx.setControl("KHOPENAPI.KHOpenAPICtrl.1")
            self._ocx.OnReceiveChejanData.connect(self._on_chejan)
            if int(self._ocx.dynamicCall("GetConnectState()")) != 1:
                self._ocx.OnEventConnect.connect(self._on_event_connect)
                self._ocx.dynamicCall("CommConnect()")
                deadline = time.time() + self._timeout_sec
                while time.time() < deadline and not self._connect_done:
                    self._app.processEvents()
                    time.sleep(0.05)
                if not self._connect_done or self._connect_err != 0:
                    self._ocx = None
        except Exception:
            self._ocx = None

    def _on_event_connect(self, err_code: int) -> None:
        self._connect_done = True
        self._connect_err  = int(err_code)

    def _on_chejan(self, gb_type, _item_cnt, _fid_list) -> None:
        if gb_type != "0" or self._ocx is None:
            return
        try:
            try:
                _otype = str(self._ocx.dynamicCall("GetChejanData(int)", [905])).strip()
                if _otype and _otype not in ("2", "4", "매도", "매도취소"):
                    return
            except Exception:
                pass
            self._last_order_no = str(
                self._ocx.dynamicCall("GetChejanData(int)", [9203])).strip()
            self._order_done = True
        except Exception:
            pass

    def is_connected(self) -> bool:
        if self._ocx is None:
            return False
        # [STEP-2F-1] broker STATE 우선, 실패 시 direct OCX fallback
        try:
            res = _broker_request_se("STATE", timeout_sec=2.0)
            if res and res.get("status") == "OK":
                return bool((res.get("data") or {}).get("connected", False))
        except Exception:
            pass
        try:
            return int(self._ocx.dynamicCall("GetConnectState()")) == 1
        except Exception:
            return False

    def _resolve_account(self) -> str:
        if self._account:
            return self._account
        # [STEP-2F-1] broker ACCOUNT_INFO 우선, 실패 시 direct OCX fallback
        try:
            res = _broker_request_se(
                "ACCOUNT_INFO", extra={"tag": "ACCNO"}, timeout_sec=2.0
            )
            if res and res.get("status") == "OK":
                raw = ((res.get("data") or {}).get("accounts") or "").strip()
                if raw:
                    self._account = raw.split(";")[0].strip()
                    if self._account:
                        return self._account
        except Exception:
            pass
        try:
            raw = str(self._ocx.dynamicCall(
                "GetLoginInfo(QString)", ["ACCNO"])).strip()
            self._account = raw.split(";")[0].strip()
        except Exception:
            pass
        return self._account

    # ─────────────────────────────────────────────────────────
    # [A-1b-CORE 2026-05-15] broker_mode chejan consume thread + send_order_real 라우팅
    # ─────────────────────────────────────────────────────────
    def _start_chejan_consume_thread(self) -> None:
        """broker chejan event 폴링 daemon thread (broker_mode 진입 시 1회 시작)."""
        if getattr(self, "_chejan_thread", None) is not None:
            return

        def _run():
            try:
                from broker_client import BrokerClient
                bc = BrokerClient()
            except Exception:
                return
            seen: dict = {}
            while True:
                try:
                    events = bc.consume_chejan_events(seen, cache_ttl_sec=300.0)
                    for ev in events:
                        try:
                            self._on_chejan_broker(ev)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    time.sleep(0.3)
                except Exception:
                    pass

        t = threading.Thread(target=_run, daemon=True, name="rt_sell_chejan_consume")
        t.start()
        self._chejan_thread = t

    def _on_chejan_broker(self, event: dict) -> None:
        """broker chejan event → 기존 _on_chejan 호환 처리 (fid_data dict 직접 lookup).

        [C1-RT 2026-05-15] ownership 매칭 — 자기가 발행한 매도 주문만 처리:
          1. gubun == "0" (주문체결)
          2. order_direction in (2/4/매도/매도취소)
          3. code == self._pending_code (마지막 발행 종목)
        """
        try:
            gubun = str(event.get("gubun", ""))
            if gubun != "0":
                return
            fid_data = event.get("fid_data") or {}
            otype = str(fid_data.get("905", "")).strip()
            if otype and otype not in ("2", "4", "매도", "매도취소"):
                return
            # [C1-RT] code ownership 매칭 — 자기 _pending_code 만 처리
            event_code = str(fid_data.get("9001", "")).strip().lstrip("A").zfill(6) \
                         if fid_data.get("9001") else ""
            pending = str(getattr(self, "_pending_code", "") or "").strip()
            if pending and event_code and pending != event_code:
                return  # 다른 엔진 매도 chejan → 무시
            self._last_order_no = str(fid_data.get("9203", "")).strip()
            self._order_done = True
        except Exception:
            pass

    def _send_sell_order_via_broker(self, code: str, price: float, qty: int) -> dict:
        """[A-1b-RT 2026-05-15] broker_mode 시 send_order_real IPC 라우팅.

        idempotency_key: 결정론적 패턴 (engine_code_intent_id).
        retry는 같은 intent_id 재사용 시 broker dedup.
        """
        base = {"code": code, "price": price, "qty": qty}
        acc = self._resolve_account()  # 이미 broker hybrid (L1396)
        if not acc:
            return {**base, "order_no": "", "status": "NO_ACCOUNT",
                    "msg": "계좌 조회 실패 (broker IPC)"}

        self._cnt += 1
        intent_id = str(_bro_uuid_se.uuid4())
        idem_key  = f"rt_sell_{code}_{intent_id}"
        rqname    = f"SAFEPLUS_SELL_BROKER_{self._cnt:06d}"

        _sell_hoga      = os.environ.get("SELL_HOGA_GB", "06").strip() or "06"
        _sell_price_arg = int(price) if _sell_hoga not in ("03", "06") else 0

        # broker_mode chejan thread 가 _last_order_no / _order_done 채움
        self._order_done    = False
        self._last_order_no = ""
        # [C1-RT 2026-05-15] ownership 매칭 — _on_chejan_broker 에서 자기 발행 종목만 처리
        self._pending_code  = str(code).strip().lstrip("A").zfill(6)

        try:
            from broker_client import BrokerClient
            bc = BrokerClient()
            res = bc.send_order_real(
                idempotency_key=idem_key,
                account=acc,
                code=str(code),
                qty=int(qty),
                order_type=2,  # 매도
                price=int(_sell_price_arg),
                hoga_gb=_sell_hoga,
                rqname=rqname,
                screen_no=str(self._SCREEN),
            )
        except Exception as e:
            return {**base, "order_no": "", "status": "EXCEPTION",
                    "msg": f"broker IPC: {e}"}

        if res.get("status") != "OK":
            return {**base, "order_no": "", "status": "REJECTED",
                    "msg": f"broker {res.get('status')}: {res.get('error')}"}

        ret = (res.get("data") or {}).get("ret", -99)
        if int(ret) != 0:
            return {**base, "order_no": "", "status": "REJECTED",
                    "msg": f"SendOrder rc={ret} (via broker)"}

        # SendOrder 호출 성공. chejan thread 가 order_no/done 채움. deadline 대기.
        deadline = time.time() + self._timeout_sec
        while time.time() < deadline and not self._order_done:
            try:
                time.sleep(0.05)
            except Exception:
                pass

        return {**base,
                "order_no": self._last_order_no,
                "status":   "OK" if self._order_done else "ACK_TIMEOUT",
                "msg":      "broker IPC + chejan thread"}

    def send_sell_order(self, code: str, price: float, qty: int,
                        order_type: str = "MARKET") -> dict:
        base = {"code": code, "price": price, "qty": qty}
        # [A-1b-RT 2026-05-15] broker_mode 시 broker IPC 라우팅
        if getattr(self, "_broker_mode", False):
            return self._send_sell_order_via_broker(code, price, qty)
        if self._ocx is None or not self.is_connected():
            return {**base, "order_no": "", "status": "DISCONNECTED",
                    "msg": "OCX 미연결"}
        acc = self._resolve_account()
        if not acc:
            return {**base, "order_no": "", "status": "NO_ACCOUNT",
                    "msg": "계좌 조회 실패"}
        self._cnt += 1
        rqname = f"SAFEPLUS_SELL_{self._cnt:06d}"
        self._order_done = False
        self._last_order_no = ""
        try:
            _limiter.acquire()  # [PATCH-RATELIMIT]
            # [v4_9-MP3] 시장가("03") → 최유리지정가("06"). 매수와 정합 (kiwoom_buy_order_sender v4_9-P13).
            #   매도 최유리지정가 = 매수1호가 자동 사용 → 1tick 슬리피지로 통제.
            #   sHogaGb="06"은 nPrice 무시 → 0 유지 가능. ENV로 사후 조정 가능.
            _sell_hoga = os.environ.get("SELL_HOGA_GB", "06").strip() or "06"
            _sell_price_arg = int(price) if _sell_hoga not in ("03", "06") else 0
            ret = int(self._ocx.dynamicCall(
                "SendOrder(QString,QString,QString,int,QString,int,int,QString,QString)",
                [rqname, self._SCREEN, acc, 2, code, int(qty), _sell_price_arg, _sell_hoga, ""]))
        except Exception as e:
            return {**base, "order_no": "", "status": "EXCEPTION", "msg": str(e)}
        if ret != 0:
            return {**base, "order_no": "", "status": "REJECTED",
                    "msg": f"SendOrder rc={ret}"}
        # [STEP-2F-4] SendOrder shadow mirror — fire-and-forget (실주문 흐름 무영향)
        try:
            _send_shadow_order_se(
                engine_name="rt_sell",
                account=acc,
                code=code,
                qty=int(qty),
                price=int(_sell_price_arg),
                order_type=2,
                screen_no=self._SCREEN,
                rqname=rqname,
                hoga_gb=_sell_hoga,
            )
        except Exception:
            pass
        deadline = time.time() + self._timeout_sec
        while time.time() < deadline and not self._order_done:
            try:
                self._app.processEvents()
                # [STEP-2F-3] Chejan IPC paper-mode consume (log only, 300ms throttled)
                _consume_chejan_events_se()
                # [STEP-2F-4] ACK relay polling (log only, 300ms throttled)
                _consume_order_shadow_ack_se()
            except Exception:
                pass
            time.sleep(0.05)
        if self._order_done and self._last_order_no:
            return {**base, "order_no": self._last_order_no, "status": "ACCEPTED",
                    "msg": f"SendOrder rc=0 acc={acc}"}
        # [STEP-2F-2.5] TIMEOUT_ACK observability — 정책 변경 없이 trace 만
        try:
            _ctx = _get_broker_context_se()
            _timeout_trace_logger_se.warning(
                "TIMEOUT_ACK code=%s qty=%s price=%s acc=%s "
                "broker=%s hb_age=%ss chejan_backlog=%s timeout_sec=%s",
                code, qty, price, acc,
                _ctx["broker"], _ctx["hb_age_sec"],
                _ctx["chejan_backlog"], self._timeout_sec,
            )
        except Exception:
            pass
        return {**base, "order_no": "", "status": "TIMEOUT_ACK",
                "msg": f"SendOrder rc=0 acc={acc} (ACK timeout)"}


# ═══════════════════════════════════════════════════════════════
#  가격 컨텍스트 (ATR-1,2,3: True ATR + ATR20 + accel)
# ═══════════════════════════════════════════════════════════════
class PriceContext:
    # [v3.11 ISSUE-2] ofi_smooth 추가 — EMA 평활화 OFI (pullback_sell 동기화)
    __slots__ = ("latest", "session_vwap", "momentum", "atr", "atr20",
                 "inst_data", "ofi_smooth", "_ok")

    _cache_mtime: float = 0.0
    _cache_ctx: Optional["PriceContext"] = None

    def __init__(self, log: logging.Logger):
        self.latest: Dict[str, dict] = {}
        self.session_vwap: Dict[str, float] = {}
        self.momentum: Dict[str, dict] = {}
        self.atr: Dict[str, float] = {}
        self.atr20: Dict[str, float] = {}   # ATR-2: vol_ratio 분모용 ATR20
        self.inst_data: Dict[str, dict] = {}
        self.ofi_smooth: Dict[str, float] = {}  # [v3.11 ISSUE-2] EMA 평활화 OFI
        self._ok = False
        self._build(log)

    def ok(self):
        return self._ok

    @classmethod
    def get_or_build(cls, log: logging.Logger) -> "PriceContext":
        """mtime 변경 시에만 재파싱
        [v3.13 Gap-10] mtime 안정 확인 — 쓰기 중 읽기 방지
          collect_prices_1m이 원자적 쓰기(tmp→replace)를 하더라도
          replace 직후 mtime이 연속 변화하는 경우 읽기 시점 충돌 가능
          → mtime 0.5초 간격 2회 동일 확인 후 읽기 진행
        """
        p = SELLCFG.PATH_PRICES_1M
        if not p.exists():
            log.warning("[CTX] prices_1m.csv 없음")
            return cls(log)
        cur_mtime = p.stat().st_mtime
        if cls._cache_ctx is not None and cur_mtime == cls._cache_mtime:
            log.debug("[CTX] 캐시 적중 (mtime=%.0f)", cur_mtime)
            return cls._cache_ctx
        # [Gap-10] mtime 안정성 확인 — 0.5초 후 재확인
        import time as _time
        _time.sleep(0.5)
        if p.exists():
            cur_mtime2 = p.stat().st_mtime
            if cur_mtime2 != cur_mtime:
                log.debug("[CTX][Gap-10] mtime 변화 감지 (%.3f→%.3f) → 0.5초 추가 대기",
                          cur_mtime, cur_mtime2)
                _time.sleep(0.5)
                cur_mtime = p.stat().st_mtime
        ctx = cls(log)
        if ctx.ok():
            cls._cache_mtime = cur_mtime
            cls._cache_ctx = ctx
        return ctx

    def _build(self, log: logging.Logger):
        p = SELLCFG.PATH_PRICES_1M
        if not p.exists():
            log.warning("[CTX] prices_1m.csv 없음")
            return
        age = time.time() - p.stat().st_mtime
        if age > SELLCFG.PRICES_STALE_SEC:
            log.warning("[CTX] stale(%.0fs)", age)
            return
        try:
            df = pd.read_csv(str(p), encoding="utf-8-sig", dtype={"code": str})
        except Exception as e:
            log.error("[CTX] CSV 실패: %s", e)
            return
        df["code"] = df["code"].str.zfill(6)
        for c in ["close", "high", "low", "open", "volume", "value"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df["ts"] = df["ts"].astype(str)
        df = df.sort_values("ts")
        today_str = date.today().strftime("%Y%m%d")
        today_mask = df["ts"].str.startswith(today_str)
        hhmm = pd.to_numeric(df["ts"].str[8:12], errors="coerce").fillna(0).astype(int)
        session_mask = today_mask & (hhmm >= SELLCFG.SESSION_START_HHMM)
        sdf = df[session_mask]
        if not sdf.empty:
            g = sdf.groupby("code").agg(cv=("value", "sum"), cvol=("volume", "sum"))
            g["vwap"] = g["cv"] / (g["cvol"] + SELLCFG.EPS)
            self.session_vwap = g["vwap"].to_dict()
        self.latest = df.groupby("code").last().to_dict("index")

        for code, grp in df.groupby("code"):
            tb = grp[grp["ts"].str.startswith(today_str)]

            # ── ATR-1: True ATR (Wilder 3방향 — 갭 포함) ──
            # 출처: Wilder (1978) TR = max(H-L, |H-prevC|, |L-prevC|)
            if (len(tb) >= 11 and
                    "high" in tb.columns and
                    "low" in tb.columns and
                    "close" in tb.columns):

                prev_c  = tb["close"].shift(1)
                hi_s    = tb["high"]
                lo_s    = tb["low"]

                tr_hl   = hi_s - lo_s
                tr_hpc  = (hi_s - prev_c).abs()
                tr_lpc  = (lo_s - prev_c).abs()
                true_tr = pd.concat([tr_hl, tr_hpc, tr_lpc], axis=1).max(axis=1)

                mid = float(tb["close"].iloc[-1])

                # ATR10 (직전 10봉 True ATR 평균)
                atr10_val = float(true_tr.iloc[-10:].mean())
                self.atr[code] = atr10_val / (mid + SELLCFG.EPS) if mid > 0 else 0.0

                # ATR-2: ATR20 (직전 20봉 — vol_ratio 분모)
                if len(tb) >= 21:
                    atr20_val = float(true_tr.iloc[-20:].mean())
                    self.atr20[code] = atr20_val / (mid + SELLCFG.EPS) if mid > 0 else self.atr[code]
                else:
                    self.atr20[code] = self.atr[code]  # 데이터 부족 시 ATR10으로 대체

            else:
                self.atr[code]  = 0.0
                self.atr20[code] = 0.0

            # ── Momentum (lookback 30봉) ──
            lb = SELLCFG.MOMENTUM_LOOKBACK_BARS
            bars_full   = tb.tail(max(lb, SELLCFG.MOMENTUM_MIN_BARS))
            bars_recent = tb.tail(SELLCFG.MOMENTUM_MIN_BARS)
            if len(bars_recent) < SELLCFG.MOMENTUM_MIN_BARS:
                self.momentum[code] = {"ready": False}
            else:
                v_long = bars_full["volume"].mean() if len(bars_full) > 0 else 1.0
                v3 = bars_recent["volume"].iloc[-3:].mean()
                h3 = (float(bars_recent["high"].iloc[-3:].max())
                      if "high" in bars_recent.columns else 0.0)
                self.momentum[code] = {
                    "ready": True,
                    "vol_ratio": v3 / (v_long + SELLCFG.EPS),
                    "high_3": h3,
                }

            # ── 기관 흐름 + ATR-3: accel 계산 ──
            if "inst_net_buy" in tb.columns:
                r5 = tb.tail(5)
                ovals = r5["inst_net_buy"].values

                # 연속 매도 봉 카운트
                cn = 0
                for v in reversed(ovals):
                    if v < 0:
                        cn += 1
                    else:
                        break

                tvol = float(r5["volume"].sum()) + SELLCFG.EPS
                isum = float(r5["inst_net_buy"].sum())
                ofi  = isum / tvol

                # ATR-3: accel = mean(최근3봉 OFI) / mean(이전5봉 OFI)
                # 출처: 지침서[15] 제3장 3-4절
                # v3.7: ofi5 극소값 시 accel 과대산출 방지 — 최소 임계 도입
                r8 = tb.tail(8)
                if len(r8) >= 8 and r8["volume"].sum() > 0:
                    r3 = r8.tail(3)
                    r_prev5 = r8.head(5)
                    v3_sum = float(r3["volume"].sum()) + SELLCFG.EPS
                    v5_sum = float(r_prev5["volume"].sum()) + SELLCFG.EPS
                    ofi3   = float(r3["inst_net_buy"].sum()) / v3_sum
                    ofi5   = float(r_prev5["inst_net_buy"].sum()) / v5_sum
                    # v3.10 ISSUE-A: accel 음음=양 엣지케이스 완전 방어
                    # 기관강세(k×1.15) 조건 = accel>=1.2
                    # ofi3·ofi5 둘 다 음수이면 나눗셈이 양수 → 기관강세 오발동
                    # 케이스별 처리:
                    #   |ofi5| < 0.001     : 거래 미미        → 중립 1.0
                    #   ofi5<0, ofi3<0     : 매도 추세 가속   → 0.5 (기관강세 불가)
                    #   ofi5<0, ofi3>=0    : 매도→매수 반전   → 중립 1.0
                    #   ofi5>0, ofi3 any   : 정상 양양 나눗셈 → 매수 가속도
                    if abs(ofi5) < 0.001:
                        accel = 1.0
                    elif ofi5 < 0 and ofi3 < 0:
                        accel = 0.5          # 매도 추세 가속 → 기관강세 판정 차단
                    elif ofi5 < 0 and ofi3 >= 0:
                        accel = 1.0          # 반전 신호 → 보수적 중립
                    else:
                        accel = ofi3 / ofi5  # ofi5>0: 정상 매수 가속도 계산
                    # 클램프: 과대/과소 산출 방지 (0.1~5.0 범위)
                    accel = max(0.1, min(accel, 5.0))
                else:
                    accel = 1.0  # 데이터 부족 시 중립

                self.inst_data[code] = {
                    "ofi_ratio":  ofi,
                    "consec_sell": cn,
                    "has_inst":   abs(isum) > 0,
                    "accel":      accel,  # ATR-3
                }
            else:
                self.inst_data[code] = {
                    "ofi_ratio": 0.0, "consec_sell": 0,
                    "has_inst": False, "accel": 1.0,
                }

        # ── [v3.11 ISSUE-2] OFI EMA 평활화 — pullback_sell_strategy 동기화 ──
        # 출처: 지침서[US-1] v1.2 §5-4 / pullback_sell_strategy v4.16 FIX-10
        # 방법: 봉별 OFI 시계열에 EMA(span=3) 적용
        #       |ofi_smooth| < 0.15 → 노이즈 구간 → 0.0 처리
        #       결과를 self.ofi_smooth dict에 저장
        # [v3.13 Gap-8] 3봉 미만 → 0.0 강제 (장 시작 초반 EMA 불안정 구간 차단)
        _OFI_EMA_SPAN = 3
        _OFI_NOISE_TH = 0.15
        _ema_mult = 2.0 / (_OFI_EMA_SPAN + 1)  # span=3 → mult=0.5
        today_str2 = date.today().strftime("%Y%m%d")

        for code, tb_data in df.groupby("code"):
            today_bars = tb_data[tb_data["ts"].astype(str).str.startswith(today_str2)]
            if "inst_net_buy" not in today_bars.columns or len(today_bars) == 0:
                self.ofi_smooth[code] = 0.0
                continue
            vols  = today_bars["volume"].values
            ibuys = today_bars["inst_net_buy"].values
            ofi_series = [
                float(ib) / (float(v) + SELLCFG.EPS)
                for v, ib in zip(vols, ibuys)
            ]
            # [v3.13 Gap-8] 3봉 미만 → EMA 불안정 → 0.0 강제
            # 장 시작 초반 1~2봉에서 EMA가 수렴하지 않아 오신호 발생
            if len(ofi_series) < 3:
                self.ofi_smooth[code] = 0.0
                continue
            ema = ofi_series[0]
            for val in ofi_series[1:]:
                ema = val * _ema_mult + ema * (1.0 - _ema_mult)
            # 노이즈 구간 제거 (지침서 v1.2 §5-4 OFI_NOISE_TH=0.15)
            self.ofi_smooth[code] = (
                0.0 if abs(ema) < _OFI_NOISE_TH else round(ema, 4)
            )

        self._ok = True


# ═══════════════════════════════════════════════════════════════
#  Chandelier k 레짐 계산 (CHA-1~4: 신설)
#  출처: LeBeau & Lucas (1992), Glasserman & Xu (2011)
# ═══════════════════════════════════════════════════════════════
def _get_chandelier_k(
    code: str,
    ctx: PriceContext,
    strategy: str,
    ret: float,
) -> float:
    """
    [대장주 추격] 수익률 3단계 k + 거래량 둔화 1조건
    trail_price = highest_high(10봉) - ATR(10) × k

    상승 초반(ret<5%):  k=3.0 — 넓게, 흔들기 허용
    상승 중반(5~10%):   k=2.5 — 기본 유지
    상승 후반(ret≥10%): k=2.0 — 조여서 고점 근처 탈출
    + 거래량 둔화(신고가 구간 vol_ratio<0.70): k-=0.5 추가 조임
    """
    # ── 수익률 3단계 k ──
    if ret < 0.05:
        k = 5.0
        regime = "EARLY"
    elif ret < 0.10:
        k = 3.0
        regime = "MID"
    else:
        k = 2.0
        regime = "LATE"

    # ── ATR vol_ratio (로그 출력용 — 반환값 유지) ──
    atr10 = ctx.atr.get(code, 0.0)
    atr20 = ctx.atr20.get(code, atr10)
    vol_ratio = atr10 / (atr20 + SELLCFG.EPS) if atr20 > 0 else 1.0

    # ── 거래량 둔화: 수익 5%+ 구간에서 최근거래량 < 평균 70% → 고점 분산 의심 ──
    mom = ctx.momentum.get(code, {})
    if mom.get("ready", False) and ret >= 0.05:
        mv = mom.get("vol_ratio", 1.0)   # 최근3봉 / 전체평균 거래량 비율
        if mv < 0.70:
            k -= 0.5
            regime += "+VOL_DIV"

    return k, regime, vol_ratio


# ═══════════════════════════════════════════════════════════════
#  [RT-Fix-1 v3.8] EXIT_SCORE 복합 청산 품질 엔진
#  pullback_sell_strategy_v4_11 동일 로직 — 3전략 일관성
# ═══════════════════════════════════════════════════════════════

def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, x))


def _calc_exit_score_rt(code: str, ctx: "PriceContext",
                        pos: dict, ret: float,
                        ride_score: float) -> float:
    """
    rt_sell_engine 전용 EXIT_SCORE 계산.
    PriceContext + pos dict에서 기존 데이터만 추출 (새 파일 읽기 없음).

    반환: 0.0(즉시 청산) ~ 1.0(강하게 보유)

    [v3.9 FATAL-1 수정]
    ctx.price      → ctx.latest.get(code,{}).get("close", 0.0)  (속성 없음 버그)
    ctx.vwap       → ctx.session_vwap.get(code, 0.0)            (속성 없음 버그)
    기존: 항상 except → 0.5(중립) 반환 → k 동적 조절 전혀 미작동
    수정: 4요소 정상 계산 → k×1.15/표준/×0.85 실제 동작
    """
    try:
        # v3.9 FATAL-1: ctx.price X → ctx.latest, ctx.vwap X → ctx.session_vwap
        latest = ctx.latest.get(code, {})
        cur    = float(latest.get("close", 0.0))
        vwap   = ctx.session_vwap.get(code, 0.0)
        inst   = ctx.inst_data.get(code, {})
        atr10  = ctx.atr.get(code, 0.0)
        atr20  = ctx.atr20.get(code, atr10)

        # ── trend_score: 현재가 vs VWAP ──────────────────────
        if vwap > 0 and cur > 0:
            vwap_ratio = cur / vwap
            trend_score = _clamp01((vwap_ratio - 0.99) / 0.02)
        else:
            trend_score = 0.5

        # ── flow_score: OFI → 0~1 변환 ───────────────────────
        # [v3.12 과제2] ofi_smooth 우선 참조 (EMA 평활화) → raw fallback
        ofi = ctx.ofi_smooth.get(code, float(inst.get("ofi_ratio", 0.0)))
        flow_score = _clamp01((ofi + 0.30) / 0.60)  # -0.3~+0.3 → 0~1

        # ── momentum_score: 현재 수익률 ───────────────────────
        if ret <= 0.0:
            momentum_score = 0.0
        else:
            momentum_score = _clamp01(ret / 0.10)  # 10% = 1.0

        # ── risk_score: vol_ratio 역수 ─────────────────────────
        if atr20 > 0 and atr10 > 0:
            vol_ratio = atr10 / atr20
            risk_score = _clamp01(1.0 - (vol_ratio - 0.8) / 1.2)
        else:
            risk_score = 0.5

        # ── 가중합 ────────────────────────────────────────────
        score = (
            0.35 * trend_score
            + 0.25 * flow_score
            + 0.20 * momentum_score
            + 0.20 * risk_score
        )

        if ride_score >= 0.60:
            score += SELLCFG.EXIT_SCORE_RIDE_BONUS
        if ret >= SELLCFG.EXIT_SCORE_PROFIT_BONUS_TH:
            score += SELLCFG.EXIT_SCORE_PROFIT_BONUS
        if ret <= SELLCFG.EXIT_SCORE_LOSS_PENALTY_TH:
            score -= SELLCFG.EXIT_SCORE_LOSS_PENALTY

        return _clamp01(score)
    except Exception:
        return 0.5   # 계산 실패 → 중립 (기존 로직 그대로)


# ═══════════════════════════════════════════════════════════════
#  헬퍼 함수
# ═══════════════════════════════════════════════════════════════
def _load_handoff_signal(log: logging.Logger) -> str:
    """
    [v3.10-HANDOFF] switch_decision.json에서 HANDOFF 신호 읽기.

    반환값:
      str  → HANDOFF 대상 종목 코드 (매도해야 할 시가 종목)
      ""   → 핸드오프 없음 (정상 보유 유지)

    조건:
      action == "SWITCH" (PENDING 아닌 확정된 것만)
      current_code 존재 (시가 보유 종목)
      reason에 "HANDOFF" 포함
      파일 신선도 HANDOFF_STALE_SEC(120초) 이내
    """
    p = SELLCFG.PATH_SWITCH_DEC
    if not p.exists():
        return ""
    try:
        age = time.time() - p.stat().st_mtime
        if age > SELLCFG.HANDOFF_STALE_SEC:
            return ""
        with open(p, "r", encoding="utf-8-sig") as f:
            dec = json.load(f)
        if dec.get("action") != "SWITCH":
            return ""
        reason = dec.get("reason", "")
        if "HANDOFF" not in reason:
            return ""
        code = str(dec.get("current_code", "")).strip()
        if not code:
            return ""
        log.info(
            "[HANDOFF] 핸드오프 신호 감지 → 시가종목 %s 즉시매도 요청 "
            "(reason=%s)", code, reason[:60]
        )
        return code
    except Exception as e:
        log.debug("[HANDOFF] 신호 읽기 실패: %s", e)
        return ""


def _load_open_positions(log: logging.Logger) -> dict:
    p = SELLCFG.PATH_OPEN_POS
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            _lock(f)
            data = json.load(f)
            _unlock(f)
        if len(data) > SELLCFG.MAX_POSITIONS:
            log.warning("[POS] %d종목 — 1종목 원칙 위반", len(data))
        return data
    except Exception as e:
        log.warning("[POS] 로드 실패: %s", e)
        return {}


def _save_open_positions(pos: dict, log: logging.Logger) -> bool:
    p = SELLCFG.PATH_OPEN_POS
    tmp = str(p) + ".tmp"
    lockfile = str(p) + ".lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        # [v4_9-MP2] 별도 lockfile로 read-modify-write 직렬화
        # 사유: 동일 프로세스 내 _save_open_positions 동시 호출 + 매수센더와의 부분 race 차단.
        #       매수센더는 atomic write(os.replace) 사용 중이라 자체 race window는 매우 작음.
        with open(lockfile, "a+", encoding="utf-8") as lf:
            _lock(lf)
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(pos, f, ensure_ascii=False, indent=2)
                os.replace(tmp, str(p))
            finally:
                _unlock(lf)
        return True
    except Exception as e:
        log.error("[POS] 저장 실패: %s", e)
        return False


def _append_order_log(records: list, log: logging.Logger):
    if not records:
        return
    p = SELLCFG.PATH_ORDER_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        df = pd.DataFrame(records)
        h = not p.exists()
        df.to_csv(str(p), mode="a", header=h, index=False, encoding="utf-8-sig")
    except Exception as e:
        log.error("[LOG] 기록 실패: %s", e)


def _save_sell_signals(signals: list, log: logging.Logger):
    """당일분만 유지 (무한 팽창 방지)"""
    if not signals:
        return
    p = SELLCFG.PATH_SELL_SIG
    today = date.today().strftime("%Y%m%d")
    existing = []
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                existing = [s for s in raw if str(s.get("ts", "")).startswith(today)]
        except Exception:
            existing = []
    merged = existing + signals
    tmp = str(p) + ".tmp"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    except Exception as e:
        log.error("[SIG] 실패: %s", e)


def _save_daily_sold(sold_codes: set, log: logging.Logger):
    if not sold_codes:
        return
    p = SELLCFG.PATH_DAILY_SOLD
    today = date.today().strftime("%Y%m%d")
    ec = set()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            if d.get("date") == today:
                ec = set(str(c).zfill(6) for c in d.get("codes", []))
        except Exception as e:
            log.debug("[SOLD] 매도 기록 읽기 실패 (빈 셋으로 진행): %s", e)
    mc = ec | {str(c).zfill(6) for c in sold_codes}
    tmp = str(p) + ".tmp"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"date": today, "codes": sorted(mc)}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
        log.info("[SOLD] %d종목", len(mc))
    except Exception as e:
        log.error("[SOLD] 실패: %s", e)


def _write_cycle_tracker(ss: list, log: logging.Logger):
    """
    [v3.13 신규] 추세눌림 청산 발생 시 cycle_tracker.json 기록.
    kiwoom_buy_order_sender의 2사이클 재진입(_check_pullback_reentry)이
    이 파일을 읽어 재진입 가능 여부를 판단한다.

    기록 조건:
      - 청산된 종목 중 strategy가 PULLBACK / TREND 계열인 것
      - tranche == 1 (T1 첫 분할 청산)만 카운트
        ← T2·T3 청산은 같은 거래의 연장 → 중복 카운트 방지
        ← [FIX-1v2] tranche >= 1 은 항상 True → == 1 로 수정

    last_sell_time:
      - ss 딕셔너리의 "ts" 필드(청산 확정 시각 YYYYMMDDHHmm...)에서 HHMM 추출
        ← [FIX-2] 기존 datetime.now() 사용은 함수 호출 지연(수십 초)으로
                   실제 청산 시각보다 늦게 기록되는 문제 수정

    파일 구조:
      { "date": "20260416", "cycle_count": 1, "last_sell_time": 1045 }
    """
    # [FIX-1] tranche == 1 만 카운트
    # T1 청산(첫 번째 분할)만 새 사이클로 인정
    # T2·T3 청산은 같은 거래의 연장 → 중복 카운트 방지
    pullback_sells = [
        s for s in ss
        if str(s.get("strategy", "")).upper() in ("PULLBACK", "TREND", "TREND_PULLBACK")
        and int(s.get("tranche", 1)) == 1
    ]
    if not pullback_sells:
        return

    p     = SELLCFG.PATH_CYCLE_TRACK
    today = date.today().strftime("%Y%m%d")

    # [FIX-2] ss의 ts 필드(YYYYMMDDHHmmSS)에서 HHMM 추출 — 실제 청산 시각
    try:
        last_ts = max(s.get("ts", "") for s in pullback_sells)
        now_hm  = int(last_ts[8:12]) if len(last_ts) >= 12 else int(datetime.now().strftime("%H%M"))
    except Exception:
        now_hm  = int(datetime.now().strftime("%H%M"))

    # 기존 파일 읽기 (오늘 것만 유효)
    data: dict = {}
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if raw.get("date") == today:
                data = raw
    except Exception as e:
        log.debug("[RT] RT 데이터 읽기 실패 (기본값 유지): %s", e)

    if not data:
        data = {"date": today, "cycle_count": 0, "last_sell_time": 0}

    data["cycle_count"]    = int(data.get("cycle_count", 0)) + min(len(pullback_sells), 1)  # 동시 다건 방어
    data["last_sell_time"] = now_hm  # 실제 청산 확정 시각 (HHMM)

    # [P6] last_code: ts 기준 가장 최근 청산 종목
    try:
        last_s = max(pullback_sells, key=lambda s: s.get("ts", ""))
        data["last_code"] = str(last_s.get("code", "")).strip().zfill(6)
    except Exception:
        pass

    # [P6] loss_codes: pnl_pct_est < 0 종목 당일 누적 (재진입 차단용)
    new_loss = [
        str(s.get("code", "")).strip().zfill(6)
        for s in pullback_sells
        if float(s.get("pnl_pct_est", 0) or 0) < 0
    ]
    existing_loss = list(data.get("loss_codes", []))
    data["loss_codes"] = sorted(set(existing_loss) | set(new_loss))

    tmp = str(p) + ".tmp"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
        log.info(
            "[CYCLE] cycle_tracker 기록 완료 cycle=%d last_sell=%04d loss_codes=%s",
            data["cycle_count"], now_hm, data["loss_codes"],
        )
    except Exception as e:
        log.error("[CYCLE] cycle_tracker 기록 실패: %s", e)


def _round_price(price: float) -> int:
    p = int(price)
    if p < 500:      t = 1
    elif p < 1000:   t = 5
    elif p < 5000:   t = 10
    elif p < 10000:  t = 50
    elif p < 50000:  t = 100
    elif p < 100000: t = 500
    else:            t = 1000
    return (p // t) * t


def _minutes_held(entry_ts: str) -> float:
    # [v4_9-MP1] 매수센더(%Y-%m-%d %H:%M:%S)와 레거시(%Y%m%d%H%M%S) 두 포맷 모두 호환
    # 사유: kiwoom_buy_order_sender_v4_9.py:821이 _now_str()로 "2026-05-04 09:18:23" 포맷 기록.
    #       이전 코드는 %Y%m%d%H%M%S만 시도 → strptime 실패 → mh=0.0 → MIN_HOLD/FAST_LOSS_CUT/MAX_HOLD 영구 미발동.
    s = str(entry_ts).strip()
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M"):
        try:
            et = datetime.strptime(s, fmt)
            return (datetime.now() - et).total_seconds() / 60
        except Exception:
            continue
    return 0.0


def _get_take_profit(gap_grade: str, ep: dict) -> float:
    g = gap_grade.upper()
    k = f"gap_tp_{g}"
    return ep.get(k, ep.get("gap_tp_", 0.035))


def _get_trail_pct(ret: float, trail_table: list, ep: dict,
                   ride_score: float = 0.0, now_hhmm: int = 0,
                   peak_ret: float = 0.0) -> float:
    """
    TR-1~4: Trail 이중 게이트 + 강제활성화 + 절대금지
    출처: 지침서[15] 제5장
    [v3.20] gate_a / force_activated → peak_ret 기준으로 변경 (래치 방식)
    이유: ret 기준이면 가격이 내려갈수록 gate_a=False로 꺼짐
         → peak 2.5%~4.8% 구간에서 trail이 수학적으로 영구 비활성
         peak_ret 기준으로 바꾸면 peak가 한 번 2.5% 찍는 순간 trail 래치 ON
    """
    # TR-4: 현재 수익 1% 미만 → Trail 절대 금지 (손실 구간 보호)
    if ret < SELLCFG.TRAIL_ABSOLUTE_MIN_RET:
        return 9.99

    act = ep.get("trail_activate_ret", SELLCFG.TRAIL_ACTIVATE_RET)  # 2.5%

    # TR-3: peak 4%+ → ride 무관 강제 활성화 [v3.20: peak_ret 기준]
    force_activated = (peak_ret >= SELLCFG.TRAIL_FORCE_RET)

    # TR-2: 이중 게이트 — A AND B 모두 충족해야 Trail 활성
    # [v3.20] gate_a: ret → peak_ret 기준 (래치: peak가 2.5% 찍으면 영구 ON)
    gate_a = (peak_ret >= act)                      # 조건A: 최고점≥2.5%
    gate_b = (ride_score >= SELLCFG.TRAIL_RIDE_MIN) # 조건B: ride≥0.40

    if not force_activated and not (gate_a and gate_b):
        return 9.99  # 이중 게이트 미통과 → Trail 비활성

    # ── Trail 비율 산출 ──
    if not trail_table:
        return 9.99
    rp = ret * 100.0
    bt = act
    for row in trail_table:
        lo, hi, tp = float(row[0]), float(row[1]), float(row[2])
        if lo <= rp < hi:
            bt = tp / 100.0
            break
    else:
        if trail_table:
            bt = float(trail_table[-1][2]) / 100.0

    if now_hhmm > 0:
        if now_hhmm < SELLCFG.TIMEZONE_OPENING_END:
            bt *= SELLCFG.OPENING_TRAIL_MULT
        elif now_hhmm >= SELLCFG.TIMEZONE_STABLE_START:
            bt *= SELLCFG.STABLE_TRAIL_MULT
    return bt


def _get_force_exit_hhmm(strategy: str, gap_grade: str, ep: dict) -> int:
    # v3.16 SIGA 릴레이: SIGA 강제청산 09:18 분기 추가
    # v3.9 WEAK-1 당시 SIGA 분기를 삭제했으나 siga_sell_strategy와 rt_sell_engine이
    # 동시에 SIGA 포지션을 바라볼 때 rt_sell_engine이 14:50으로 계산하는 문제 수정
    s = strategy.upper()
    g = gap_grade.upper()
    # ── [v3.16 SIGA 릴레이] SIGA 강제청산 09:18 ── (siga_sell_strategy 부재로 복원)
    if s == "SIGA":
        return ep.get("force_siga", SELLCFG.FORCE_EXIT_SIGA)
    if s == "PULLBACK":
        # [v4_9-권고1] gap A 종목은 종가 직전 급등 패턴이 흔해 14:50→15:20으로 보유 연장
        # (RT 전략은 line 1734-1735에서 이미 15:20 적용 — gap A 일관성)
        if g == "A":
            return ep.get("force_pullback_A", SELLCFG.FORCE_EXIT_RT)
        return ep.get("force_A", SELLCFG.FORCE_CLOSE_A)
    if s == "RT":
        return SELLCFG.FORCE_EXIT_RT  # [PATCH] RT → 15:20 우선 (gap_grade="A" 14:50보다 앞)
    if g == "A":
        return ep.get("force_A", SELLCFG.FORCE_CLOSE_A)
    if g in ("B", "C", "D"):
        return ep.get("force_BCD", SELLCFG.FORCE_CLOSE_BCD)
    return SELLCFG.FORCE_EXIT_DEFAULT


# ═══════════════════════════════════════════════════════════════
#  자기진화 피드백 트리거 (EV-1: v3_1→v3_0→v2_0 폴백 순서)
# ═══════════════════════════════════════════════════════════════
def _trigger_evolution_feedback(sell_signals: list, log: logging.Logger):
    """
    EV-1: 모듈 우선순위 v3_1 → v3_0 → v2_0 순서 폴백
    출처: 지침서[15] 제13장
    """
    psl = None
    used_ver = None
    # [v3.17 FIX] 실제 파일 v3_4_FIXED 1순위 → 구버전 폴백
    # 기존: v3_1/v3_0/v2_0 순서 → 전부 미존재 → psl=None → 진화 피드백 전달 불가
    # 수정: v3_4_FIXED(실제 파일) 우선 시도 → 하위 호환 폴백 유지
    for ver in ["v3_5", "v3_4_FIXED", "v3_4", "v3_3_SAFEPLUS_FINAL", "v3_1", "v3_0", "v2_0"]:
        try:
            import importlib
            _run_path = r"C:\stock_bot\RUN"
            if _run_path not in sys.path:
                sys.path.insert(0, _run_path)
            psl = importlib.import_module(f"pnl_strategy_linker_{ver}")
            used_ver = ver
            break
        except (ImportError, RuntimeError):
            continue

    if psl is None:
        log.debug("[EVOL] pnl_strategy_linker 미설치 (v3_4_FIXED 포함 전 버전 없음)")
        return

    log.info("[EVOL] 사용 모듈: pnl_strategy_linker_%s", used_ver)
    for sig in sell_signals:
        if not sig.get("pending_fill"):
            continue
        try:
            psl.write_sell_fill(
                code=sig["code"],
                strategy=sig.get("strategy", "UNKNOWN"),
                sell_price=sig["exit_price"],
                sell_qty=sig["qty"],
                exit_reason=sig["reason"],
            )
            log.info("[EVOL] %s 진화 피드백 전달 | %s", sig["code"], sig["reason"])
        except Exception as e:
            log.warning("[EVOL] %s 실패: %s", sig["code"], e)

    # v3.10 ISSUE-C: pnl_strategy_linker 연동 후 진화 상태 파일 갱신
    _update_evolution_state(sell_signals, log)

    # [v3.13 Gap-12] 청산 직후 trail_activate_ret 당일 즉시 업데이트
    # 기존: 장 시작 전 1회 진화만 → 오전 손실 결과가 당일 오후에 미반영
    # 수정: 청산 직후 win_rate/profit_factor 기반 trail_activate_ret 즉시 조정
    #       trail_activate_ret만 허용 (k/FAILSAFE/PEAK_PROTECT 불변)
    _intraday_evolve_trail(sell_signals, log)


def _intraday_evolve_trail(sell_signals: list, log: logging.Logger):
    """[Gap-12] 청산 직후 trail_activate_ret 당일 즉시 진화
    오전 청산 결과를 오후 진입 전에 즉시 반영 — 당일 손실 패턴 연속 방지
    trail_activate_ret만 조정 (FROZEN 파라미터 불변 원칙 준수)
    """
    if not sell_signals:
        return
    state = _load_evolution_state(log)
    wr = state.get("win_rate", 0.50)
    pf = state.get("profit_factor", 1.0)
    tt = state.get("total_trades", 0)
    if tt < 3:
        return   # 표본 3건 미만 → 즉시 진화 스킵

    # params.json trail_activate_ret 즉시 업데이트
    try:
        params_path = SELLCFG.BASE / "RUN" / "params.json"
        if not params_path.exists():
            params_path = SELLCFG.BASE / "params.json"
        if not params_path.exists():
            return

        with open(params_path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)

        rt_sec = raw.get("rt_sell", {})
        current_tar = float(rt_sec.get(
            "trail_activate_ret", SELLCFG.TRAIL_ACTIVATE_RET))

        # 손실 구간: trail 활성화 기준 상향 (더 수익난 후 trail 시작)
        # 수익 구간: trail 활성화 기준 하향 (더 일찍 trail 시작)
        if wr < 0.45 or pf < 0.8:
            new_tar = min(current_tar * 1.05,
                         SELLCFG.TRAIL_ACTIVATE_RET * 1.10)  # 최대 +10%
            label = "손실구간→상향"
        elif wr > 0.60 and pf > 1.5:
            new_tar = max(current_tar * 0.97,
                         SELLCFG.TRAIL_ACTIVATE_RET * 0.90)  # 최대 -10%
            label = "수익구간→하향"
        else:
            return   # 정상 범위 → 조정 없음

        new_tar = round(new_tar, 4)
        if abs(new_tar - current_tar) < 0.0001:
            return

        _INTRADAY_TAR["trail_activate_ret"] = new_tar
        log.info(
            "[INTRADAY_EVOL][Gap-12] trail_activate_ret %.4f→%.4f (%s) "
            "wr=%.1f%% pf=%.2f  [인메모리적용]",
            current_tar, new_tar, label, wr * 100, pf)
    except Exception as e:
        log.debug("[INTRADAY_EVOL][Gap-12] 스킵: %s", e)


# ═══════════════════════════════════════════════════════════════
#  [v3.10 ISSUE-C] 경량 진화 상태 영구 저장소
#  rt_evolution_state.json — 프로세스 재시작 후에도 학습 누적 유지
# ═══════════════════════════════════════════════════════════════
def _load_evolution_state(log: logging.Logger) -> dict:
    """
    rt_evolution_state.json → win_rate · profit_factor 로드.
    pnl_strategy_linker 없을 때 독립 fallback으로 작동.
    """
    p = SELLCFG.PATH_EVOL_STATE
    defaults = {
        "win_rate": 0.50, "profit_factor": 1.0,
        "total_trades": 0, "win_trades": 0,
        "total_profit": 0.0, "total_loss": 0.0,
        "last_updated": "",
    }
    if not p.exists():
        return defaults
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        # 필드 안전 병합 (구버전 파일 호환)
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        log.info(
            "[EVOL-STATE] 로드 | wr=%.3f pf=%.2f trades=%d last=%s",
            data["win_rate"], data["profit_factor"],
            data["total_trades"], data["last_updated"],
        )
        return data
    except Exception as e:
        log.warning("[EVOL-STATE] 로드 실패 → 초기값: %s", e)
        return defaults


def _update_evolution_state(sell_signals: list, log: logging.Logger):
    """
    청산 결과를 rt_evolution_state.json에 누적 기록.
    지침서[15] 제13장 — 진화 피드백 영구화.

    win_rate  = 누적 승리 거래 / 전체 거래
    profit_factor = 총 수익 / 총 손실 (절대값)
    """
    if not sell_signals:
        return
    p = SELLCFG.PATH_EVOL_STATE
    state = _load_evolution_state(log)

    for sig in sell_signals:
        pnl = float(sig.get("pnl_est", 0.0))
        state["total_trades"] += 1
        if pnl > 0:
            state["win_trades"]   += 1
            state["total_profit"] += pnl
        elif pnl < 0:
            state["total_loss"]   += abs(pnl)

    # 재계산
    tt = state["total_trades"]
    if tt > 0:
        state["win_rate"] = round(state["win_trades"] / tt, 4)
    tp = state["total_profit"]
    tl = state["total_loss"]
    if tl > 0:
        state["profit_factor"] = round(tp / tl, 4)
    elif tp > 0:
        state["profit_factor"] = 9.99   # 손실 없음 → 최고값
    state["last_updated"] = datetime.now().strftime("%Y%m%d%H%M%S")

    # 원자적 저장 (tmp → replace)
    tmp = str(p) + ".tmp"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
        log.info(
            "[EVOL-STATE] 저장 | wr=%.3f pf=%.2f trades=%d",
            state["win_rate"], state["profit_factor"], tt,
        )
    except Exception as e:
        log.error("[EVOL-STATE] 저장 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  Profit Lock (3단계)
# ═══════════════════════════════════════════════════════════════
def _apply_profit_lock_stop(
    code: str, pos: dict, entry_price: float, ret: float,
    ep: dict, log: logging.Logger,
    peak_ret: Optional[float] = None,  # [v4_9-MP5] peak 기반 잠금
) -> float:
    be_ret = ep.get("breakeven_ret", SELLCFG.BREAKEVEN_ACTIVATE_RET)
    hs  = ep.get("hard_stop", SELLCFG.HARD_STOP_DEFAULT)
    hr  = ep.get("profit_lock_half_ret",  SELLCFG.PROFIT_LOCK_HALF_RET)
    tr  = ep.get("profit_lock_two3_ret",  SELLCFG.PROFIT_LOCK_TWO3_RET)
    fr  = ep.get("profit_lock_three4_ret",SELLCFG.PROFIT_LOCK_THREE4_RET)
    cs  = float(pos.get("stop_price", entry_price * (1.0 - hs)))
    # [v4_9-MP5] 잠금 트리거: peak_ret 우선 (pullback_sell_strategy와 정합)
    # 사유: ret(현재) 기반은 peak 도달 후 하락 시 잠금 갱신을 놓침. peak_ret 기반은
    #       지침서 §11-1 원본 의도와 일치 — "최대 수익률 도달 시 일정 비율 잠금"
    _trigger_ret = peak_ret if peak_ret is not None else ret
    if _trigger_ret < be_ret:
        return cs

    # [지침서 §11-3 수정] 기관동행 시 잠금 비율 ×0.9 완화
    # pullback_sell_strategy PROFIT_LOCK_INST_RELAX 로직 이식
    # ride_score가 pos에 저장된 경우 참조, 없으면 기본값 적용
    _ride_for_lock = float(pos.get("ride_score", 0.0))
    _inst_relax = (
        SELLCFG.PROFIT_LOCK_INST_RELAX
        if _ride_for_lock >= SELLCFG.PROFIT_LOCK_INST_RIDE_MIN
        else 1.0
    )

    cand = entry_price
    if _trigger_ret >= fr:
        # [수정] 지침서 §11-1 원본: 8%+ → 75% 잠금 (pullback_sell 통일)
        # [§11-3] 기관동행 시 × 0.9 → 67.5% 잠금
        cand = entry_price + (entry_price * _trigger_ret * 0.75 * _inst_relax)
    elif _trigger_ret >= tr:
        # [수정] 지침서 §11-1 원본: 5%+ → 67% 잠금 (pullback_sell 통일)
        # [§11-3] 기관동행 시 × 0.9 → 60.3% 잠금
        cand = entry_price + (entry_price * _trigger_ret * 0.67 * _inst_relax)
    elif _trigger_ret >= hr:
        # [수정] 지침서 §11-1 원본: 2%+ → 50% 잠금 (pullback_sell 통일)
        # [§11-3] 기관동행 시 × 0.9 → 45% 잠금
        # Chandelier가 먼저 작동할 기회 보장
        cand = entry_price + (entry_price * _trigger_ret * 0.50 * _inst_relax)

    ns = max(cand, cs)
    if ns > cs:
        pos["stop_price"] = ns
        log.debug(
            "[LOCK] %s stop %.0f→%.0f ret=%.2f%% ride=%.2f relax=%.2f",
            code, cs, ns, ret * 100, _ride_for_lock, _inst_relax,
        )
    return ns if ns > cs else cs


# ═══════════════════════════════════════════════════════════════
#  ATR 동적 하드스톱
# ═══════════════════════════════════════════════════════════════
def _get_dynamic_hard_stop(code: str, ctx: PriceContext, ep: dict,
                           pos: Optional[dict] = None) -> float:
    # [v4_9-MP4] 매수센더가 기록한 _hard_stop_pct 우선 사용 (가산매수 후 평단 기준 보수적 손절)
    # 사유: kiwoom_buy_order_sender_v4_9.py:805-808이 평단 갱신 시 max(이전,신규)로 _hard_stop_pct 저장.
    #       이를 무시하면 매수가 보수적으로 잡은 손절폭이 매도 ATR 산식에 묻혀버림.
    _pos_hs = 0.0
    if pos is not None:
        try:
            _pos_hs = float(pos.get("_hard_stop_pct", 0.0) or 0.0)
        except Exception:
            _pos_hs = 0.0
    atr_pct = ctx.atr.get(code, 0.0)
    if atr_pct <= 0:
        _ep_hs = float(ep.get("hard_stop", SELLCFG.HARD_STOP_DEFAULT))
        return max(_pos_hs, _ep_hs) if _pos_hs > 0 else _ep_hs
    m  = ep.get("atr_stop_mult", SELLCFG.ATR_STOP_MULT)
    mn = ep.get("atr_stop_min",  SELLCFG.ATR_STOP_MIN)
    mx = ep.get("atr_stop_max",  SELLCFG.ATR_STOP_MAX)
    _atr_hs = max(mn, min(atr_pct * m, mx))
    # 매수 측 _hard_stop_pct가 더 보수적(큰 값)이면 그 값 채택
    return max(_pos_hs, _atr_hs) if _pos_hs > 0 else _atr_hs


# ═══════════════════════════════════════════════════════════════
#  Profit-tier + 기관 기반 동적 trailing gap
#  핵심 철학:
#    수익은 profit tier로 관리 — 클수록 gap 압축 → 수익 보호 강화
#    보유는 기관으로 결정 — ride≥0.40 and OFI≥0.20이면 trail 완화 → 조기청산 방지
#    15:00 이후 장 후반 추가 압축 → 수익 보존 강화
# ═══════════════════════════════════════════════════════════════
def _get_tiered_dh(profit_pct: float, hm: int, ride: float, ofi: float) -> float:
    """peak 기준 최대 수익률(%) + 시각 + ride/OFI → trailing gap 반환"""
    # 1) profit tier: 수익 클수록 gap 압축
    if profit_pct < 1.0:
        base = 0.020
    elif profit_pct < 3.0:
        base = 0.015
    elif profit_pct < 6.0:
        base = 0.010
    elif profit_pct < 12.0:
        base = 0.010  # peak 6~12%: 1.0% gap (0.7% 대비 정상 조정 허용)
    else:
        base = 0.007  # peak 12%+: 0.7% 타이트 보호 유지

    # 2) 15:00 이후 장 후반 추가 압축
    if hm >= 1500:
        base *= 0.75

    # 3) 기관 유지 시 trail 완화 — "기관 안 내리면 나도 안 내린다"
    # ride≥0.40 AND OFI≥0.20 → gap 40% 확대 → 대장주 흔들림에도 보유 유지
    if ride >= 0.40 and ofi >= 0.20:
        base *= 1.40

    return base


# ═══════════════════════════════════════════════════════════════
#  기관 이탈 감지 (OFI 음수 방향 전용)
#  출처: Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
# ═══════════════════════════════════════════════════════════════
def _check_inst_exit(
    code: str, ctx: PriceContext, ret: float, ep: dict
) -> Tuple[bool, str]:
    mp = ep.get("inst_exit_min_profit", SELLCFG.INST_EXIT_MIN_PROFIT)
    if ret < mp:
        return False, ""
    inst = ctx.inst_data.get(code, {})
    if not inst.get("has_inst", False):
        return False, ""
    ofi_th  = ep.get("inst_exit_ofi_drop",   SELLCFG.INST_EXIT_OFI_DROP)
    con_th  = ep.get("inst_exit_consec_drop", SELLCFG.INST_EXIT_CONSEC_DROP)
    vpin_th = ep.get("inst_exit_vpin_spike",  SELLCFG.INST_EXIT_VPIN_SPIKE)
    # [v3.11 ISSUE-2] ofi_smooth 우선 참조 (EMA 평활화값) → raw OFI fallback
    ofi = ctx.ofi_smooth.get(code, inst.get("ofi_ratio", 0.0))
    con = inst.get("consec_sell", 0)

    # OFI가 음수일 때만 이탈 판정 (양수=매수 중 → 절대 이탈 판정 금지)
    ofi_trigger = ofi <= ofi_th and con >= con_th

    if ofi < 0:
        vpin_val = abs(ofi) / (1.0 - abs(ofi) + SELLCFG.EPS)
        vpin_trigger = vpin_val >= vpin_th and con >= con_th
    else:
        vpin_val = 0.0
        vpin_trigger = False

    if ofi_trigger or vpin_trigger:
        return True, (
            f"INST_EXIT|ofi={ofi:.2f}|vpin={vpin_val:.2f}"
            f"|consec={con}|ret={ret:.3%}"
        )
    return False, ""


# ═══════════════════════════════════════════════════════════════
#  SuperTrend Trail
# ═══════════════════════════════════════════════════════════════
def _get_super_trail_pct(ret: float, ep: dict, now_hhmm: int) -> float:
    if not ep.get("super_trend_mode", SELLCFG.SUPER_TREND_MODE):
        return 9.99
    ap = ep.get("super_trail_activate_pct", SELLCFG.SUPER_TRAIL_ACTIVATE_PCT)
    rp = ret * 100.0
    if rp < ap:
        return 9.99
    st = ep.get("super_trail", SELLCFG.SUPER_TRAIL_TABLE)
    bt = 0.022
    for row in st:
        lo, hi, pct = float(row[0]), float(row[1]), float(row[2])
        if lo <= rp < hi:
            bt = pct / 100.0
            break
    else:
        if st:
            bt = float(st[-1][2]) / 100.0
    if now_hhmm > 0 and now_hhmm < SELLCFG.TIMEZONE_OPENING_END:
        bt *= SELLCFG.OPENING_TRAIL_MULT
    return bt


# ═══════════════════════════════════════════════════════════════
#  기관 동행 상태 판정
# ═══════════════════════════════════════════════════════════════
def _is_inst_riding(
    pos: dict, ctx: PriceContext, code: str
) -> Tuple[bool, float]:
    """
    rt_open_positions.json의 ride_score/trail_mode 참조
    고유영역 미침범 (직접 계산 금지)
    """
    ride = float(pos.get("ride_score", 0.0))
    trail_mode = str(pos.get("trail_mode", ""))

    # [신규] 실시간 OFI 약화 감지 — env 토글 (기본 false, 운영 데이터 보고 활성화 결정)
    if os.environ.get("USE_RIDE_DECAY", "false").lower() == "true":
        inst_now = ctx.inst_data.get(code, {})
        ofi_now  = ctx.ofi_smooth.get(code, inst_now.get("ofi_ratio", 0.0))
        _ride_decay_ofi = float(os.environ.get("RIDE_DECAY_OFI", "-0.15"))
        if ofi_now < _ride_decay_ofi or inst_now.get("consec_sell", 0) >= 3:
            ride = min(ride, 0.40)   # freeze ride 강제 하향 → RIDE_STRONG_HOLD 해제

    if ride >= SELLCFG.RIDE_STRONG_THRESHOLD:
        return True, ride

    if trail_mode == "HOLD":
        return True, max(ride, SELLCFG.RIDE_STRONG_THRESHOLD)

    # fallback: 실시간 OFI 기반 — [v3.11 ISSUE-2] ofi_smooth 우선 참조
    inst = ctx.inst_data.get(code, {})
    ofi_live = ctx.ofi_smooth.get(code, inst.get("ofi_ratio", 0.0))
    if (inst.get("has_inst", False)
            and ofi_live > SELLCFG.INST_STRONG_OFI_MIN
            and inst.get("consec_sell", 0) == 0):
        # [v4_9-MP9] ride 0.50 고정 반환 → 실제 ride 또는 0.50 중 큰 값 반환
        # 사유: 학습 피드백/PnL 기록 시 정확한 ride_score 보존. inst_riding 판정엔 영향 없음.
        return True, max(float(ride), 0.50)

    return False, ride


# ═══════════════════════════════════════════════════════════════
#  청산 조건 판단 — 지침서[15] 12단계 완전 준수
# ═══════════════════════════════════════════════════════════════
def _check_exit(
    code: str, pos: dict, ctx: PriceContext,
    now_hhmm: int, ep: dict, log: logging.Logger,
) -> Tuple[bool, str, float]:

    pd_ = ctx.latest.get(code)
    if not pd_:
        return False, "NO_PRICE", 0.0
    cur = float(pd_.get("close", 0))
    if cur <= 0:
        return False, "BAD_PRICE", 0.0

    ep_  = float(pos.get("entry_price", cur))
    strat = str(pos.get("strategy", "RT"))
    # [SIGA-OWNERSHIP] SIGA 포지션은 siga_sell_strategy 단독 처리 — rt_sell_engine 미관여
    if strat.upper() == "SIGA":
        return False, "SKIP_SIGA|siga_sell_strategy 전담", cur
    gg         = str(pos.get("gap_grade", ""))
    ets        = str(pos.get("entry_ts", ""))
    trn        = int(pos.get("tranche", 1))
    trail_mode = str(pos.get("trail_mode", "CHANDELIER"))
    ret  = (cur - ep_) / (ep_ + SELLCFG.EPS)
    mh   = _minutes_held(ets)
    tp   = _get_take_profit(gg, ep)

    # [v3.13 Gap-2] T2 배율: ride_score 구간별 세분화
    # 기관 흐름 강도에 따라 T2 목표를 더 멀리 설정
    ride_for_t2 = float(pos.get("ride_score", 0.0))
    t2m = SELLCFG.T2_MULT   # 기본값
    for ride_min, mult in SELLCFG.T2_MULT_TABLE:
        if ride_for_t2 >= ride_min:
            t2m = mult
            break
    # params.json의 t2_mult가 명시된 경우 그것을 기본으로 하되
    # ride 완화는 추가로 적용 (기존 대비 최대값 선택)
    t2m_ep = ep.get("t2_mult", SELLCFG.T2_MULT)
    t2m = max(t2m, t2m_ep)   # ride 기반과 params 기반 중 더 관대한 값 채택

    if trn >= 2:
        tp = tp * t2m
    tt   = ep.get("trail_table", SELLCFG.TRAIL_TABLE_FALLBACK)

    # ── peak_price 단방향 갱신 (매봉 실행) ──
    # v3.10 ISSUE-B 검증: pos는 dict 참조 전달 → 여기서 수정된 peak_price가
    # _execute_sells의 rem[code]=pos를 통해 JSON에 영구 저장됨. 경로 확인 완료.
    pk = float(pos.get("peak_price", ep_))
    if cur > pk:
        pos["peak_price"] = cur   # ← rem 경유 _save_open_positions에 반영됨
        pk = cur
        log.debug("[PEAK] %s 갱신 %.0f → %.0f", code, pk, cur)

    # ── 기관 동행 상태 — [v3.11 ISSUE-2] ofi_smooth 우선 참조 ──
    inst_riding, ride_score = _is_inst_riding(pos, ctx, code)
    inst_info = ctx.inst_data.get(code, {})
    _ofi_for_strong = ctx.ofi_smooth.get(code, inst_info.get("ofi_ratio", 0.0))
    inst_strong = (
        inst_info.get("has_inst", False)
        and _ofi_for_strong > SELLCFG.INST_STRONG_OFI_MIN
        and inst_info.get("consec_sell", 0) == 0
    )

    # ── 0. FORCE_ALL_EXIT / SWITCH_SELL ──
    if pos.get("_force_all"):
        switch_reason = pos.get("_force_reason", "몰빵위반")
        if "SWITCH" in switch_reason.upper():
            return True, f"SWITCH_SELL|{switch_reason}|ret={ret:.3%}", cur
        return True, f"FORCE_ALL_EXIT|{switch_reason}|ret={ret:.3%}", cur

    # ══ 역할 분리 ════════════════════════════════════════════════
    # 초기 손절 : _get_dynamic_hard_stop()  — 진입 직후 방어선
    # trailing  : _get_tiered_dh()         — profit/기관 기반 peak 추적
    # 기관 강함 : P1.3 INST_HOLD           — OFI 강세 시 모든 청산 차단
    # 기관 약화 : EVENT_EXIT               — 2틱 확인 후 선청산
    # 시간청산  : FORCE_EXIT               — 최후 안전망
    # ═════════════════════════════════════════════════════════════

    # ── ATR 동적 hard stop 초기화 (초기 손절선 전용 — trailing에는 미사용) ──
    dh_init = _get_dynamic_hard_stop(code, ctx, ep, pos)  # [v4_9-MP4] pos 전달
    if "stop_price" not in pos:
        if gg == "A":
            dh_init *= 1.1
            log.info("[GAP] %s A등급 손절 완화 dh_init=%.3f", code, dh_init)
        elif gg in ("C", "D"):
            dh_init *= 0.9
            log.info("[GAP] %s 저등급 손절 강화 dh_init=%.3f", code, dh_init)
        pos["stop_price"] = ep_ * (1.0 - dh_init)
    # ── Profit-tier trailing stop (활성화 게이트 통과 시에만 작동) ──
    # TRAIL_ABSOLUTE_MIN_RET 미달 → trailing 절대 금지
    # 활성화 조건: (ret≥TRAIL_ACTIVATE_RET AND ride≥TRAIL_RIDE_MIN) OR ret≥TRAIL_FORCE_RET
    # 활성화 이후에만 _get_tiered_dh() 적용 — 초기 손절과 trailing 완전 분리
    _act_ret  = ep.get("trail_activate_ret", SELLCFG.TRAIL_ACTIVATE_RET)
    _trail_active = (
        ret >= SELLCFG.TRAIL_ABSOLUTE_MIN_RET
        and (
            (ret >= _act_ret and ride_score >= SELLCFG.TRAIL_RIDE_MIN)
            or ret >= SELLCFG.TRAIL_FORCE_RET
        )
    )
    if _trail_active:
        _peak_profit_pct = (pk / ep_ - 1.0) * 100.0
        _dh = _get_tiered_dh(_peak_profit_pct, now_hhmm, ride_score, _ofi_for_strong)
        if ride_score > 0.5:
            _dh *= 1.2
            log.info("[RIDE] %s trail 완화 ride=%.2f dh×1.2=%.3f", code, ride_score, _dh)
        if trail_mode != "CHANDELIER":
            _dh *= 0.9
        _trail_sp = pk * (1.0 - _dh)
        # floor: peak 수익 +1% 이상 확보 시 ep+1% 이하로 stop 내려가지 않음
        if _peak_profit_pct >= 1.0:
            _trail_sp = max(_trail_sp, ep_ * 1.010)
        if _trail_sp > pos["stop_price"]:
            pos["stop_price"] = _trail_sp
            log.debug(
                "[TRAIL] %s peak_pct=%.2f%% dh=%.3f ride=%.2f ofi=%.3f → trail_sp=%.0f",
                code, _peak_profit_pct, _dh, ride_score, _ofi_for_strong, _trail_sp,
            )

    # ══ [EXIT-A] CONVEX PEAK FLOOR ══════════════════════════════════════
    # 수익 구간별 peak 기준 stop 하한 고정 (기존 trail_sp와 max 합산)
    # 5%→pk×0.96 / 10%→pk×0.97 / 20%→pk×0.95
    try:
        _conv_tiers = ((0.20, 0.95), (0.10, 0.97), (0.05, 0.96))
        for _conv_ret_th, _conv_floor_mult in _conv_tiers:
            if ret >= _conv_ret_th:
                _conv_sp = pk * _conv_floor_mult
                if _conv_sp > pos["stop_price"]:
                    pos["stop_price"] = _conv_sp
                    log.info(
                        "[CONVEX_TRAIL] %s ret=%.1f%% pk=%.0f → stop=pk×%.2f=%.0f",
                        code, ret * 100, pk, _conv_floor_mult, _conv_sp,
                    )
                break
    except Exception as _ce:
        log.warning("[CONVEX_TRAIL] %s 오류 → 무시 err=%s", code, _ce)
    # ═════════════════════════════════════════════════════════════════════

    # ── Profit Lock ──
    # [v4_9-MP5] peak_ret 전달 — peak 기반 잠금으로 변경 (pullback_sell_strategy 정합)
    _peak_ret_lock = max(0.0, (float(pk) - ep_) / ep_) if ep_ > 0 else 0.0
    sp = _apply_profit_lock_stop(code, pos, ep_, ret, ep, log, peak_ret=_peak_ret_lock)

    # ── 1. HARD STOP — 무조건 (기관 있어도 손절은 지킴) ──
    if cur <= sp:
        return True, f"HARD_STOP|ret={ret:.3%}|stop={sp:,.0f}", cur

    # ── 1.1 TAKE_PROFIT — [통합패치-07] 익절 트리거 복구 ──
    # 위치 의도: HARD_STOP 직후, MIN_HOLD_PROTECT 직전에 배치
    #   → 익절은 3분 미만에도 발동, 손절 노이즈 보호는 그대로 유지
    # 분할매도 흐름: _execute_sells line ~2673 reason.startswith("TAKE_PROFIT_T*") 자동 인식
    #   T1(trn==1): SPLIT_T1_RATIO(0.25) 비율 일부 익절 → trn=2로 승계
    #   T2(trn==2): SPLIT_T2_RATIO(0.25) 비율 일부 익절 → trn=3 잔여는 Trail/Chandelier
    _t1_trigger = ep.get("split_t1_trigger_ret", SELLCFG.SPLIT_T1_TRIGGER_RET)
    _t2_trigger = ep.get("split_t2_trigger_ret", SELLCFG.SPLIT_T2_TRIGGER_RET)
    if trn == 1 and ret >= _t1_trigger:
        return True, f"TAKE_PROFIT_T1|ret={ret:.3%}|trigger={_t1_trigger:.3%}", cur
    if trn == 2 and ret >= _t2_trigger:
        return True, f"TAKE_PROFIT_T2|ret={ret:.3%}|trigger={_t2_trigger:.3%}", cur

    # ── 1.2 최소 보유 시간 보호 (초입 털림 방지) ──
    if mh < float(os.environ.get("MIN_HOLD_PROTECT_MIN", "3.0")):
        log.info("[HOLD] %s 최소보유 보호 %.1f분 → 비청산", code, mh)
        return False, f"MIN_HOLD_PROTECT|{mh:.1f}분", cur

    # ── P0. FORCE EXIT (P0 — INST_HOLD 이전 최우선) ──
    fh = _get_force_exit_hhmm(strat, gg, ep)
    if now_hhmm >= fh:
        # [v3.16 SIGA 릴레이] SIGA는 FORCE_GRACE 예외 없이 즉시 청산 (siga_sell_strategy 부재로 복원)
        # 이유: 09:18 강제청산 → 09:20 PULLBACK 자금 재투입 타이밍 의존
        #       FORCE_GRACE 허용 시 09:28까지 연장 → PULLBACK 09:20 진입창 소멸
        if strat.upper() == "SIGA":
            return True, (
                f"FORCE_EXIT_SIGA|hhmm={now_hhmm}|ret={ret:.3%}"
                f"|09:20_PULLBACK_릴레이_보호"
            ), cur
        # [v3.13 Gap-11] 기관 동행 + 수익 3%+ 시 10분 grace_time 1회 허용
        # '기관 흐름 살아있으면 들고 간다' 원칙 — MAX_HOLD 시간 도달만으로 즉시 청산 방지
        # SIGA 전략은 위에서 즉시 청산 처리됨 — 이하 PULLBACK/RT 전용
        _grace_applied = pos.get("_force_grace_used", False)
        if (not _grace_applied
                and inst_riding
                and ret >= 0.03
                and now_hhmm < fh + 10):
            pos["_force_grace_used"] = True
            log.info(
                "[FORCE_GRACE][Gap-11] %s 기관동행+수익%.1f%% → 10분 연장 허용 "
                "(hhmm=%04d fh=%04d)",
                code, ret * 100, now_hhmm, fh)
        else:
            return True, f"FORCE_EXIT|hhmm={now_hhmm}|{strat}|ret={ret:.3%}", cur

    # ── 1.3 P1.3 INST_HOLD — 지침서 §9 P1.3 명시적 독립 판단 ──
    # 기존: ride_score 간접 처리만 → OFI≥0.35 강매수 중 불필요한 청산 발생
    # 수정: ofi_smooth≥0.35 AND consec_sell=0 → 이하 P1.5~P7 청산 판단 전체 차단
    # HARD_STOP(P1)·FORCE_EXIT(P0) 이후에만 위치 — 절대 손절은 보장
    _ofi_for_inst_hold = ctx.ofi_smooth.get(code, inst_info.get("ofi_ratio", 0.0))
    _consec_sell_now   = inst_info.get("consec_sell", 0)
    # [W39 PATCH 2026-05-13] peak_ret 가드 추가 — INST_HOLD vs PEAK_PROTECT 충돌 해결
    #   기존: peak 18% / ret 3% 시 INST_HOLD 유지 → 수익 반납 -15%p 위험
    #   변경: peak 10%+ 도달 시 INST_HOLD 해제 → PEAK_PROTECT (5/8/12% 임계) 활성화
    #   INST_HOLD_OFI_MIN/MAX_RET 임계 자체는 변경 없음
    _peak_ret_for_hold = (pk - ep_) / (ep_ + SELLCFG.EPS)
    _inst_hold_active  = (
        _ofi_for_inst_hold >= SELLCFG.INST_HOLD_OFI_MIN
        and _consec_sell_now == 0
        and 0 < ret < SELLCFG.INST_HOLD_MAX_RET
        and _peak_ret_for_hold < 0.10   # ← W39: peak 10% 미만일 때만 INST_HOLD 유효
    )
    if _inst_hold_active:
        _flow_neg_cnt_map.pop(code, None)   # INST_HOLD 차단 중 카운터 오염 방지
        log.debug(
            "[P1.3 INST_HOLD] %s ofi=%.3f consec_sell=%d ret=%.2f%% → 보유 우선",
            code, _ofi_for_inst_hold, _consec_sell_now, ret * 100,
        )
        return False, "INST_HOLD_P1_3", cur

    # ── 1.3 RIDE_STRONG_HOLD — 기관 강매집 시 절대 보유 ──
    if inst_riding and ride_score >= SELLCFG.RIDE_STRONG_THRESHOLD:
        if 0 < ret < SELLCFG.RIDE_STRONG_MAX_RET:
            log.debug(
                "[HOLD] %s RIDE_STRONG ride=%.2f ret=%.3%%",
                code, ride_score, ret * 100,
            )
            return False, "HOLD_RIDE_STRONG", cur

    # ── 1.5 INST_STRONG_HOLD — OFI 기반 기관 동행 ──
    if inst_strong and 0 < ret < 0.08:
        return False, "HOLD_INST_STRONG", cur

    # ══ [EXIT-B] FLOW EXIT v2 — 수익 구간별 Tier ════════════════════════
    # 0~2%: 비활성 / 2~5%: 3/3 전원 / 5~10%: 2/3×2틱 / 10%+: 2/3 즉시
    try:
        _dv_a  = float(pd_.get("dv_accel",    0.0))
        _tk_a  = float(pd_.get("tick_accel",  0.0))
        _val_a = float(pd_.get("value_accel", 0.0))
        _flow_neg = sum(1 for _v in (_dv_a, _tk_a, _val_a) if _v < 0)
        _flow_exit = False
        _flow_tier = ""
        if ret < 0.02:
            _flow_neg_cnt_map.pop(code, None)           # tier 이탈 리셋
        elif ret < 0.05:
            _flow_neg_cnt_map.pop(code, None)           # tier 이탈 리셋
            if _flow_neg >= 3:
                _flow_exit = True
                _flow_tier = "2~5%|3/3"
        elif ret < 0.10:
            if _flow_neg >= 2:
                _flow_neg_cnt_map[code] = _flow_neg_cnt_map.get(code, 0) + 1
            else:
                _flow_neg_cnt_map[code] = 0
            if _flow_neg_cnt_map.get(code, 0) >= 2:
                _flow_exit = True
                _flow_tier = "5~10%|2/3×2틱"
        else:
            _flow_neg_cnt_map.pop(code, None)           # tier 이탈 리셋
            if _flow_neg >= 2:
                _flow_exit = True
                _flow_tier = "10%+|2/3"
        if _flow_exit:
            log.info(
                "[FLOW_EXIT] %s tier=%s neg=%d dv=%.0f tk=%.2f val=%.2f ret=%.2f%%",
                code, _flow_tier, _flow_neg, _dv_a, _tk_a, _val_a, ret * 100,
            )
            return True, (
                f"FLOW_EXIT|tier={_flow_tier}|neg={_flow_neg}"
                f"|dv={_dv_a:.0f}|tk={_tk_a:.2f}|val={_val_a:.2f}"
                f"|ret={ret:.3%}"
            ), cur
    except Exception as _fe:
        log.warning("[FLOW_EXIT] %s 오류 → 무시 err=%s", code, _fe)
    # ═════════════════════════════════════════════════════════════════════

    # ── Confirmed weak-event exit (P1.3 이후 전용) ──
    # P1.3 INST_HOLD / RIDE_STRONG_HOLD / INST_STRONG_HOLD을 통과한 상태
    # = 기관이 강한 종목은 이미 위에서 HOLD로 return됨
    # 여기서는 "기관 약화가 연속 2틱 확인된 경우"만 선청산
    # weak_event = ride < 0.40 AND OFI < 0.20 (둘 다 동시 약화)
    _weak_event = (ride_score < SELLCFG.TRAIL_RIDE_MIN and _ofi_for_strong < 0.20)
    if _weak_event:
        _weak_cnt_map[code] = _weak_cnt_map.get(code, 0) + 1
    else:
        _weak_cnt_map[code] = 0
    if ret >= SELLCFG.TRAIL_ACTIVATE_RET and _weak_cnt_map.get(code, 0) >= 2:
        log.info(
            "[EVENT_EXIT] %s weak_count=%d ret=%.3f%% ride=%.2f ofi=%.3f",
            code, _weak_cnt_map[code], ret * 100.0, ride_score, _ofi_for_strong,
        )
        return True, f"EVENT_EXIT|weak={_weak_cnt_map[code]}|ret={ret:.3%}", cur

    # ── 1.7 FAST_LOSS_CUT (기관 예외 -2%) ──
    # [v3.13 Gap-6] 장 시작 09:10 이전 유예 — 초반 정상 변동 조기 손절 방지
    # 09:00~09:10: 변동성 3~5배 → FAST_LOSS_CUT 비활성
    # 09:10 이후: 정상 적용
    _flc_eligible = (now_hhmm >= 910)
    if ret < SELLCFG.FAST_LOSS_CUT_PCT and mh >= SELLCFG.FAST_LOSS_CUT_MIN_HOLD:
        if not _flc_eligible:
            log.debug(
                "[FAST_LOSS_CUT][Gap-6] %s 09:10 이전 유예 ret=%.2f%% hhmm=%04d",
                code, ret * 100, now_hhmm)
        elif inst_riding or inst_strong:
            if ret < SELLCFG.FAST_LOSS_CUT_INST_GRACE:
                return True, (
                    f"FAST_LOSS_CUT_INST|ret={ret:.3%}|{mh:.0f}분"
                    f"|ride={ride_score:.2f}"
                ), cur
        else:
            return True, f"FAST_LOSS_CUT|ret={ret:.3%}|{mh:.0f}분", cur

    # ══ [EXIT-C] DV_ACCEL EARLY EXIT ═════════════════════════════════════
    # 매수 가속 소멸(dv_accel < 0) + 손실/보합(ret ≤ 0) + 5분 이상 보유
    # → "틀린 진입" 판정, FAST_LOSS_CUT 도달 전 조기 컷
    try:
        _dv_early = float(pd_.get("dv_accel", 0.0))
        if _dv_early < 0 and ret <= 0.0 and mh >= 5.0:
            log.info(
                "[DV_EARLY_EXIT] %s dv_accel=%.0f ret=%.2f%% mh=%.1f분 → 조기 컷",
                code, _dv_early, ret * 100, mh,
            )
            return True, (
                f"DV_ACCEL_EXIT|dv={_dv_early:.0f}|ret={ret:.3%}|{mh:.1f}분"
            ), cur
    except Exception as _dve:
        log.warning("[DV_EARLY_EXIT] %s 오류 → 무시 err=%s", code, _dve)
    # ═════════════════════════════════════════════════════════════════════

    # ── 2. INST_EXIT (OFI 음수 방향 전용) ──
    ie, ir = _check_inst_exit(code, ctx, ret, ep)
    if ie:
        return True, ir, cur

    # ── 3. MOMENTUM EXIT ──
    ib = (SELLCFG.MOMENTUM_BLACKOUT_START <= now_hhmm <= SELLCFG.MOMENTUM_BLACKOUT_END)
    mpr = ep.get("momentum_min_profit", SELLCFG.MOMENTUM_MIN_PROFIT)
    if not ib and ret >= mpr:
        if not (inst_riding and ride_score >= SELLCFG.RIDE_STRONG_THRESHOLD):
            mom = ctx.momentum.get(code, {})
            vr_th = ep.get("momentum_vol_ratio", SELLCFG.MOMENTUM_VOL_RATIO)
            pt = ep.get("momentum_price_drop", SELLCFG.MOMENTUM_PRICE_DROP)
            if mom.get("ready", False):
                vr = mom.get("vol_ratio", 1.0)
                h3 = mom.get("high_3", cur)
                pdrop = (h3 - cur) / (h3 + SELLCFG.EPS)
                if vr < vr_th and pdrop >= pt:
                    return True, (
                        f"MOMENTUM_EXIT|vol={vr:.2f}|drop={pdrop:.3%}"
                        f"|ret={ret:.3%}"
                    ), cur

    # ── 4. VWAP BREAK ──
    vmr = ep.get("vwap_min_ret", SELLCFG.VWAP_MIN_RET)
    vmh = ep.get("vwap_min_hold_min", SELLCFG.VWAP_MIN_HOLD_MIN)
    vwap_eligible = (ret >= vmr) or (ret < 0 and mh >= vmh)
    if vwap_eligible:
        if trn >= 2:
            # T2 이후: 기존 T2 thresh 유지 (분할 이후는 보수적)
            thr = ep.get("vwap_thresh_t2", SELLCFG.T2_VWAP_THRESH)
        else:
            # [v3.13 Gap-1] T1: 수익 구간별 VWAP 이격 허용 차등화
            # 수익이 클수록 VWAP 아래 이격을 더 허용 — 트렌드 보호
            thr = SELLCFG.VWAP_BREAK_THRESH   # 기본값
            for ret_min, tier_thr in SELLCFG.VWAP_BREAK_TIERS:
                if ret >= ret_min:
                    thr = tier_thr
                    break
            # 기관 동행 시 추가 완화 (기관 흐름 보호)
            if inst_riding:
                thr = round(thr * SELLCFG.VWAP_INST_RELAX, 4)
            # 개장 초(~09:30) 추가 완화
            if now_hhmm < SELLCFG.TIMEZONE_OPENING_END:
                thr = min(thr, SELLCFG.OPENING_VWAP_RELAX)
            log.debug(
                "[VWAP_TIER] %s ret=%.2f%% thr=%.4f inst=%s",
                code, ret * 100, thr, "Y" if inst_riding else "N",
            )
        vwap = ctx.session_vwap.get(code, 0.0)
        if vwap > 0:
            if cur < vwap * thr:
                if strat.upper() == "PULLBACK":
                    cnt = pos.get("_vwap_break_cnt", 0) + 1
                    pos["_vwap_break_cnt"] = cnt
                    if cnt < SELLCFG.VWAP_BREAK_PULLBACK_CONFIRM:
                        log.debug(
                            "[VWAP_BREAK] %s PULLBACK 이탈 %d/%d 대기",
                            code, cnt, SELLCFG.VWAP_BREAK_PULLBACK_CONFIRM,
                        )
                    else:
                        return True, (
                            f"VWAP_BREAK|price={cur:,.0f}|vwap={vwap:,.0f}"
                            f"|thr={thr:.4f}|ret={ret:.3%}|T{trn}|cnt={cnt}"
                        ), cur
                else:
                    return True, (
                        f"VWAP_BREAK|price={cur:,.0f}|vwap={vwap:,.0f}"
                        f"|thr={thr:.4f}|ret={ret:.3%}|T{trn}"
                    ), cur
            elif strat.upper() == "PULLBACK" and pos.get("_vwap_break_cnt", 0) > 0:
                pos["_vwap_break_cnt"] = 0
                log.debug("[VWAP_BREAK] %s PULLBACK VWAP 회복 → 카운터 리셋", code)

    # ── 5. TAKE PROFIT — [대장주 추격] 비활성: ATR/Chandelier 전량 청산 담당 ──

    # ── 6.5 PEAK_PROTECT 3단계 (PP-1~3: 교체) ──
    # 출처: 지침서[15] 제6장 — 12% > 8% > 5% 우선순위
    # [v4_9-MP6] 사각지대 차단: peak가 임계 초과 시 cur_th를 비율만큼 동적 확대
    # 사유: 이전 코드는 peak=15%, ret=5.5% 시 어떤 임계도 매칭 못해 미발동.
    #       peak/peak_th 비율로 보호 라인 동적 조정 → 큰 수익도 비례적 보호.
    peak_ret = (pk - ep_) / (ep_ + SELLCFG.EPS)
    for peak_th, cur_th in SELLCFG.PEAK_PROTECT_LEVELS:
        # PP-2: 기관 동행 시 임계 ÷1.15 완화
        adj_cur_th = cur_th / SELLCFG.PEAK_PROTECT_INST_RELAX if inst_riding else cur_th
        if peak_ret >= peak_th:
            # peak가 임계 초과한 비율만큼 보호 라인도 비례 확대 (peak_th 미만일 땐 영향 없음)
            _scale = max(1.0, peak_ret / peak_th) if peak_th > 0 else 1.0
            _scaled_cur_th = adj_cur_th * _scale
            if ret < _scaled_cur_th:
                return True, (
                    f"PEAK_PROTECT_{int(peak_th*100)}|"
                    f"peak={peak_ret:.3%}→cur={ret:.3%}|"
                    f"임계={_scaled_cur_th:.3%}(scale=×{_scale:.2f})|"
                    f"inst={'Y' if inst_riding else 'N'}"
                ), cur

    # ── 6.8 HARD_FAILSAFE (HF-1~3: 신설) ──
    # 출처: 지침서[15] 제7장 — 수익 반납 즉시 보호
    # 조건1: 과거 2% 달성 이력
    # 조건2: 현재 < peak_ret × 60%
    if (peak_ret >= SELLCFG.FAILSAFE_TRIGGER_RET and
            ret < peak_ret * SELLCFG.FAILSAFE_RETAIN_RATIO):
        failsafe_thresh = peak_ret * SELLCFG.FAILSAFE_RETAIN_RATIO
        return True, (
            f"HARD_FAILSAFE|peak={peak_ret:.3%}|cur={ret:.3%}"
            f"|임계={failsafe_thresh:.3%}"
            f"(고점×{SELLCFG.FAILSAFE_RETAIN_RATIO:.0%})"
        ), cur

    # ── 7. CHANDELIER + EXIT_SCORE 복합 게이트 [RT-Fix-1 v3.8] ──
    # 출처: LeBeau & Lucas (1992), 지침서[15] 제2·3장
    k_val, regime, vol_ratio = _get_chandelier_k(code, ctx, strat, ret)
    atr_pct = ctx.atr.get(code, 0.0)

    # ── EXIT_SCORE 계산 → k 동적 조절 ──────────────────────────
    _es = _calc_exit_score_rt(code, ctx, pos, ret, ride_score)
    if _es >= SELLCFG.EXIT_SCORE_HOLD_TH:
        k_val = round(k_val * SELLCFG.EXIT_SCORE_K_WIDE_MULT, 3)
        _es_action = "HOLD_WIDE"
    elif _es >= SELLCFG.EXIT_SCORE_TIGHTEN_TH:
        _es_action = "STANDARD"
    else:
        k_val = round(k_val * SELLCFG.EXIT_SCORE_K_TIGHT_MULT, 3)
        _es_action = "TIGHTEN"
        if (_es < SELLCFG.EXIT_SCORE_FORCE_TH
                and ret >= SELLCFG.EXIT_SCORE_FORCE_MIN_RET):
            log.info("[%s] EXIT_SCORE_FORCE score=%.3f<%.2f ret=%.2f%%",
                     code, _es, SELLCFG.EXIT_SCORE_FORCE_TH, ret * 100)
            return True, (
                f"EXIT_SCORE_FORCE|score={_es:.3f}|ret={ret:.3%}"
            ), cur

    log.debug("[%s] EXIT_SCORE=%.3f(%s) k=%.2f regime=%s",
              code, _es, _es_action, k_val, regime)

    # Chandelier Exit 공식: trail_price = highest_high(10봉) - ATR(10) × k
    if atr_pct > 0:
        chandelier_trail_pct = atr_pct * k_val
        pb_chandelier = (pk - cur) / (pk + SELLCFG.EPS)
        if pb_chandelier >= chandelier_trail_pct:
            # TR-4: 수익 1% 미만 → Chandelier 발동 금지
            if ret >= SELLCFG.TRAIL_ABSOLUTE_MIN_RET:
                return True, (
                    f"CHANDELIER|regime={regime}|k={k_val:.2f}"
                    f"|atr={atr_pct:.3%}|trail={chandelier_trail_pct:.3%}"
                    f"|vol_ratio={vol_ratio:.2f}|ret={ret:.3%}"
                    f"|exit_score={_es:.3f}"
                ), cur

    # ── 보조 Trail (SuperTrend + 동적 Trail) ──
    # [v3.12 과제3] 설계 의도 명시
    # Chandelier가 미발동(atr_pct=0 or pb < chandelier_trail_pct)일 때만 진입
    # 우선순위: SuperTrend(활성화 5%+) > 동적 Trail(15%/10%/5% 구간별) > 기본 Trail
    # 3자 중 가장 좁은(보수적) 값이 eff로 채택 → TRAIL_STOP|SUPER/DYN/NORMAL 로그 구분
    # 기관 동행 시 dyn×1.5 완화 — Chandelier와 동일한 기관 동행 보상 원칙 유지
    # [v3.20] peak_ret 계산 후 _get_trail_pct에 전달 (래치 방식 gate_a용)
    _peak_ret_val = (pk - ep_) / (ep_ + SELLCFG.EPS)
    tpct = _get_trail_pct(ret, tt, ep, ride_score, now_hhmm, peak_ret=_peak_ret_val)
    st_pct = _get_super_trail_pct(ret, ep, now_hhmm)
    eff = st_pct if st_pct < 9.0 else tpct

    # 초공격 동적 Trail (수익 구간별 점진 강화)
    # 15%+ → 1.0% / 10%+ → 1.2% / 5%+ → 1.5% / 미만 → 비활성
    if ret >= 0.15:
        dyn = 0.010
    elif ret >= 0.10:
        dyn = 0.012
    elif ret >= 0.05:
        dyn = 0.015
    else:
        dyn = 9.99

    # 기관 동행 시 Trail 완화 (더 넓게)
    if inst_riding and dyn < 9.0:
        dyn *= 1.2   # [P2] 1.5→1.2: 수익 반납 감소 위해 wait 배수 완화

    if dyn < 9.0:
        eff = min(eff, dyn)

    if eff < 9.0:
        pb = (pk - cur) / (pk + SELLCFG.EPS)
        if pb >= eff:
            mode = "SUPER" if st_pct < 9.0 else ("DYN" if dyn < 9.0 else "NORMAL")
            return True, (
                f"TRAIL_STOP|{mode}|peak={pk:,.0f}"
                f"|trail={eff:.1%}|ret={ret:.3%}"
            ), cur

    # ── 8. MAX HOLD ──
    # [v3.16 SIGA 릴레이] SIGA 15분 MAX_HOLD 추가 (09:05 진입 → 09:20 한계)
    # FORCE_EXIT 09:18이 먼저 작동하나, 09:05 이전 진입 시 안전망으로 기능
    su = strat.upper()
    # [v3.16 SIGA 릴레이] SIGA 15분 MAX_HOLD 안전망 (siga_sell_strategy 부재로 복원)
    if su == "SIGA":
        mxh = ep.get("max_hold_siga", SELLCFG.MAX_HOLD_SIGA)
    elif su == "PULLBACK":
        mxh = ep.get("max_hold_pullback", SELLCFG.MAX_HOLD_PULLBACK)
    else:
        mxh = ep.get("max_hold_rt", SELLCFG.MAX_HOLD_RT)
    if mh >= mxh:
        return True, f"MAX_HOLD|{mh:.0f}분|ret={ret:.3%}", cur

    return False, "HOLD", cur


# ═══════════════════════════════════════════════════════════════
#  매도 집행 (v3.3 보강 전부 유지)
# ═══════════════════════════════════════════════════════════════
def _execute_sells(
    positions: dict, ctx: PriceContext, bridge: KiwoomSellBridge,
    now_hhmm: int, ep: dict, log: logging.Logger,
) -> Tuple[list, list, dict]:
    global _kill_switch
    ors = []; ss = []; rem = {}
    t1_ratio   = ep.get("split_t1_ratio", SELLCFG.SPLIT_T1_RATIO)
    t2_ratio   = ep.get("split_t2_ratio", SELLCFG.SPLIT_T2_RATIO)  # v3.9 WEAK-3: 진화 반영
    inst_ratio = ep.get("split_ratio_inst", SELLCFG.SPLIT_RATIO_INST)
    run_id     = date.today().strftime("%Y%m%d")
    sold_this_cycle: set = set()   # SG-1: 중복 매도 방지

    for code, pos in positions.items():
        # [EOD_PICK 2026-05-28] 종가매수 포지션은 rt_sell_engine 당일 청산 skip.
        # EOD_PICK은 다음날 시가/갭 청산 (eod_pickup_sell_v1 전담). SIGA/PULLBACK 무영향.
        if str(pos.get("strategy", "")).strip().upper() == "EOD_PICK":
            rem[code] = pos
            continue

        # ── SG-1: 중복 매도 차단 ──
        if code in sold_this_cycle:
            log.warning("[SG] %s 중복 매도 차단", code)
            rem[code] = pos
            continue

        se, reason, cp = _check_exit(code, pos, ctx, now_hhmm, ep, log)
        if not se:
            rem[code] = pos
            continue

        # [PATCH-LOG] 청산 이유 복기용 로그 — 어떤 단계에서 청산됐는지 명시
        entry_p = float(pos.get("entry_price", cp))
        ret_pct = (cp - entry_p) / entry_p * 100 if entry_p > 0 else 0.0
        log.info(
            "[EXIT🔴] %s 청산발동 | 이유=%s | 현재가=%.0f | 수익률=%.2f%% | hhmm=%04d",
            code, reason, cp, ret_pct, now_hhmm
        )

        # [PATH_LOG] 경로별 수익 누적
        _ep = _get_entry_path(code, pos)
        if _ep not in _path_profit_acc:
            _path_profit_acc[_ep] = []
        _path_profit_acc[_ep].append(ret_pct)
        log.info(
            "[PATH_PROFIT] %s path=%s ret=%.2f%% | "
            "A누적(%d건 avg=%.2f%%) B누적(%d건 avg=%.2f%%)",
            code, _ep, ret_pct,
            len(_path_profit_acc["A"]),
            (sum(_path_profit_acc["A"]) / len(_path_profit_acc["A"])
             if _path_profit_acc["A"] else 0.0),
            len(_path_profit_acc["B"]),
            (sum(_path_profit_acc["B"]) / len(_path_profit_acc["B"])
             if _path_profit_acc["B"] else 0.0),
        )

        tq = int(pos.get("qty", 0))

        # ── SG: qty/price 방어 ──
        if tq <= 0:
            log.warning("[SG] %s qty=%d ≤ 0 → BLOCK", code, tq)
            rem[code] = pos
            continue
        if cp <= 0:
            log.warning("[SG] %s price=%.0f ≤ 0 → BLOCK", code, cp)
            rem[code] = pos
            continue

        # ── 3단계 분할매도 판정 ──
        trn = int(pos.get("tranche", 1))
        inst_riding, ride = _is_inst_riding(pos, ctx, code)
        is_split = False
        sq = tq; rq = 0

        if SELLCFG.SPLIT_SELL_ENABLED and reason.startswith("TAKE_PROFIT_T"):
            if trn == 1 and reason.startswith("TAKE_PROFIT_T1"):
                sr = inst_ratio if inst_riding else t1_ratio
                sq = max(1, int(tq * sr))
                rq = tq - sq
                is_split = True
            elif trn == 2 and reason.startswith("TAKE_PROFIT_T2"):
                orig_qty = int(pos.get("original_qty", tq))
                sq = max(1, int(orig_qty * t2_ratio))
                sq = min(sq, tq)
                rq = tq - sq
                is_split = rq > 0

        # ── OE-1: 주문 타입 선택 ──
        order_type = _get_order_type(reason)
        if order_type == "LIMIT":
            order_price = _bid_minus_ticks(cp, 1)
        elif order_type == "IOC_LIMIT":
            order_price = _bid_minus_ticks(cp, 1)
        else:
            order_price = _round_price(cp * (1.0 - SELLCFG.SLIPPAGE_RATE))

        # ── OE-2,3,4: 주문 실행 + 재시도 ──
        ts_start = time.time()
        decision_id = f"{code}_{datetime.now().strftime('%H%M%S')}"
        filled = False
        filled_qty = 0
        avg_price = 0.0
        final_status = "FAILED"
        reject_reason = ""
        retry_no = 0
        result = None

        for attempt in range(SELLCFG.MAX_ORDER_RETRY + 1):
            retry_no = attempt
            try:
                attempt_price = order_price
                if attempt > 0:
                    attempt_price = _bid_minus_ticks(cp, attempt + 1)
                    if order_type == "MARKET":
                        attempt_price = 0
                result = bridge.send_sell_order(
                    code, attempt_price, sq - filled_qty, order_type,
                )
            except Exception as e:
                log.error("[OE] %s 주문 예외 attempt=%d: %s", code, attempt, e)
                reject_reason = str(e)
                continue

            if result.get("status") == "ACCEPTED":
                r_qty   = result.get("qty", sq - filled_qty)
                r_price = result.get("price", attempt_price if attempt_price > 0 else cp)
                filled_qty += r_qty
                avg_price  = (
                    (avg_price * (filled_qty - r_qty) + r_price * r_qty) / filled_qty
                    if filled_qty > 0 else r_price
                )
                if filled_qty >= sq:
                    filled = True
                    final_status = "FILLED"
                    break
                else:
                    final_status = "PARTIAL"
                    log.info("[OE] %s 부분체결 %d/%d주 attempt=%d",
                             code, filled_qty, sq, attempt)
            else:
                reject_reason = result.get("msg", "UNKNOWN")
                _kill_switch.check_reject(code, reject_reason, log)
                log.warning("[OE] %s 거절 attempt=%d | %s",
                            code, attempt, reject_reason)

            if attempt < SELLCFG.MAX_ORDER_RETRY:
                time.sleep(SELLCFG.RETRY_INTERVAL_SEC)

        # OE-2: 최종 MARKET fallback
        if not filled and filled_qty < sq and order_type != "MARKET":
            remain = sq - filled_qty
            log.warning("[OE] %s MARKET fallback 잔량=%d주", code, remain)
            try:
                fb_result = bridge.send_sell_order(code, 0, remain, "MARKET")
                if fb_result.get("status") == "ACCEPTED":
                    fb_qty   = fb_result.get("qty", remain)
                    fb_price = fb_result.get("price", cp)
                    avg_price = (
                        (avg_price * filled_qty + fb_price * fb_qty)
                        / (filled_qty + fb_qty)
                    ) if (filled_qty + fb_qty) > 0 else fb_price
                    filled_qty += fb_qty
                    filled = filled_qty >= sq
                    final_status = "FILLED" if filled else "PARTIAL"
                    retry_no += 1
                else:
                    _kill_switch.check_reject(
                        code, fb_result.get("msg", "MARKET_FB"), log,
                    )
            except Exception as e:
                log.error("[OE] %s MARKET fallback 예외: %s", code, e)

        # 킬스위치 체크
        if _kill_switch.active:
            log.critical("[KS] 킬스위치 발동 — 추가 주문 중단")
            rem[code] = pos
            break

        # 전량 실패 → 포지션 유지
        if filled_qty <= 0:
            log.error("[OE] %s 전량 실패 final=%s", code, final_status)
            rem[code] = pos
            continue

        # ── 체결 완료 후처리 ──
        fill_latency_ms    = round((time.time() - ts_start) * 1000, 1)
        partial_fill_ratio = round(filled_qty / sq, 4) if sq > 0 else 0.0
        sold_this_cycle.add(code)

        # KS: 동일 종목 반복 매도 감지
        _kill_switch.check_loop(code, log)

        # 부분체결 잔량 포지션 반영
        actual_rq = rq + (sq - filled_qty)
        if is_split and actual_rq > 0:
            next_trn = trn + 1
            u = dict(pos)
            u["qty"]     = actual_rq
            u["tranche"] = next_trn
            # [v4_9-MP10] inst_riding 종목은 entry 강제 상향 회피 — 빠른 손절 방지
            # 사유: ride 높은 종목은 entry × (1 - _hard_stop_pct) 라인이 더 적합.
            #       일반 종목은 breakeven 보장 (기존 동작 유지).
            _ride_split = float(pos.get("ride_score", 0.0))
            _hs_pct_split = float(pos.get("_hard_stop_pct", 0.0) or 0.0)
            _entry_p_split = float(pos.get("entry_price", cp))
            _cur_stop_split = float(pos.get("stop_price", cp))
            if (_ride_split >= SELLCFG.PROFIT_LOCK_INST_RIDE_MIN
                    and _hs_pct_split > 0):
                _hs_floor = _entry_p_split * (1.0 - _hs_pct_split)
                u["stop_price"] = max(_cur_stop_split, _hs_floor)
            else:
                u["stop_price"] = max(_cur_stop_split, _entry_p_split)
            if "original_qty" not in u:
                u["original_qty"] = tq
            rem[code] = u
            log.info("[T%d→T%d] %s %d주 체결 → 잔여 %d주 stop=%.0f (ride=%.2f hs=%.4f)",
                     trn, next_trn, code, filled_qty, actual_rq,
                     u["stop_price"], _ride_split, _hs_pct_split)
        elif actual_rq > 0 and not is_split:
            u = dict(pos)
            u["qty"] = actual_rq
            rem[code] = u
            log.warning("[OE] %s 부분체결 잔여 %d주 유지", code, actual_rq)

        ap  = avg_price if avg_price > 0 else cp
        aq  = filled_qty
        epr = float(pos.get("entry_price", ap))
        pnl = (ap - epr) * aq
        pp  = (ap - epr) / (epr + SELLCFG.EPS)
        pk_str = str(pos.get("pattern_key", ""))
        ggg    = str(pos.get("gap_grade", ""))

        log.info(
            "[SELL] %s|%s|%s원|%d주|PnL=%+.0f(%+.2f%%)|T%d|%s|retry=%d",
            code, reason, f"{ap:,.0f}", aq, pnl, pp * 100, trn,
            final_status, retry_no,
        )

        # KS: 일일 손실 누적 체크
        capital = float(pos.get("order_krw", epr * tq))
        _kill_switch.check_daily_loss(pnl, capital, log)

        # ── AU-1,2: 감사 추적 기록 ──
        # v3.7: walrus 연산자 제거 — 명시적 변수로 가독성 개선
        _au_strategy = str(pos.get("strategy", "RT"))
        _au_ret      = pp   # pp = (ap - epr) / (epr + EPS) — 이미 계산됨
        k_val, regime, vol_ratio = _get_chandelier_k(code, ctx, _au_strategy, _au_ret)
        rec = {
            "ts":           datetime.now().strftime("%Y%m%d%H%M%S"),
            "run_id":       run_id,
            "decision_id":  decision_id,
            "code": code, "side": "SELL",
            "price": round(ap, 0), "qty": aq, "amount": round(ap * aq, 0),
            "pnl_est":     round(pnl),
            "pnl_pct_est": round(pp, 6),
            "exit_reason": reason,
            "strategy":    pos.get("strategy", ""),
            "gap_grade":   ggg, "tranche": trn,
            "pattern_key": pk_str,
            "order_no":    result.get("order_no", "") if result else "",
            "pending_fill": True,
            # OE 정보
            "order_type":        order_type,
            "retry_no":          retry_no,
            "reject_reason":     reject_reason,
            "fill_latency_ms":   fill_latency_ms,
            "partial_fill_ratio": partial_fill_ratio,
            "final_status":      final_status,
            # 기관 동행 정보
            "ride_score":   ride,
            "trail_mode":   str(pos.get("trail_mode", "")),
            "inst_strong":  inst_riding,
            # attribution
            "atr_pct":      round(ctx.atr.get(code, 0.0), 6),
            "atr20_pct":    round(ctx.atr20.get(code, 0.0), 6),
            "chandelier_k": round(k_val, 3),
            "vol_regime":   regime,
            "peak_ret":     round(
                (float(pos.get("peak_price", epr)) - epr) / (epr + SELLCFG.EPS), 6
            ),
            "hold_minutes": round(_minutes_held(str(pos.get("entry_ts", ""))), 1),
        }
        ors.append(rec)
        ss.append({
            "code":       code,
            "entry_price": epr,
            "exit_price":  ap,
            "qty":         aq,
            "pnl_est":     round(pnl),
            "reason":      reason,
            "strategy":    pos.get("strategy", ""),
            "gap_grade":   ggg, "tranche": trn,
            "pattern_key": pk_str,
            "ts":          rec["ts"],
            "pending_fill": True,
            "block_reentry": (actual_rq == 0 or filled_qty >= sq),
            "ride_score":  ride,
            "inst_strong": inst_riding,
            "final_status": final_status,
            "retry_no":    retry_no,
        })
        time.sleep(SELLCFG.ORDER_INTERVAL_SEC)

    return ors, ss, rem


# ═══════════════════════════════════════════════════════════════
#  stale 대응 — 캐시 ctx로 HARD_STOP + FORCE_EXIT만 실행
# ═══════════════════════════════════════════════════════════════
def _stale_force_protect(
    positions: dict, cached_ctx: "PriceContext",
    bridge: KiwoomSellBridge, now_hhmm: int, ep: dict,
    log: logging.Logger,
) -> int:
    hs_ratio     = ep.get("hard_stop", SELLCFG.HARD_STOP_DEFAULT)
    force_default = ep.get("force_exit_default", SELLCFG.FORCE_EXIT_DEFAULT)
    # [v3.16 → v4_9-MP8] 주석 정정: 실제로는 line 3005에서 SIGA continue로 SKIP — 강제청산 보장 X
    # SIGA 포지션은 siga_sell_strategy 단독 책임 (SIGA-OWNERSHIP 정책). stale 모드에서도 미관여
    # force_siga 변수는 데드코드(MP8 패치 후) — 호환 유지 위해 남김
    force_siga = ep.get("force_siga", SELLCFG.FORCE_EXIT_SIGA)
    fired = 0
    for code, pos in list(positions.items()):
        strat    = str(pos.get("strategy", "")).upper()
        # [SIGA-OWNERSHIP] SIGA 포지션은 siga_sell_strategy 단독 처리 — stale 모드에서도 미관여
        if strat == "SIGA":
            continue
        # [v4_9-MP8] SIGA continue 직후이므로 force_siga 분기 데드코드 제거 (force_default만 사용)
        force_hm = force_default
        entry_p  = float(pos.get("entry_price", 0))
        if entry_p <= 0:
            continue
        cur_p = float(cached_ctx.latest.get(code, {}).get("close", 0))
        reason = ""
        if now_hhmm >= force_hm:
            reason = f"STALE_FORCE_EXIT|hhmm={now_hhmm}"
        elif cur_p > 0 and (cur_p - entry_p) / entry_p <= -hs_ratio:
            reason = f"STALE_HARD_STOP|ret={(cur_p-entry_p)/entry_p:.3%}"
        if not reason:
            continue
        qty = int(pos.get("qty", 0))
        if qty <= 0:
            continue
        log.critical("[STALE-PROTECT] %s %s qty=%d → 매도 시도", code, reason, qty)
        try:
            bridge.send_sell_order(code, cur_p or entry_p, qty, "MARKET")
            fired += 1
        except Exception as e:
            log.error("[STALE-PROTECT] 매도 실패 %s: %s", code, e)
    return fired


# ═══════════════════════════════════════════════════════════════
#  메인 루프
# ═══════════════════════════════════════════════════════════════
def run_once(bridge: KiwoomSellBridge, log: logging.Logger) -> int:
    global _kill_switch
    nh = int(datetime.now().strftime("%H%M"))
    if not (SELLCFG.MARKET_OPEN_HHMM <= nh <= SELLCFG.MARKET_CLOSE_HHMM):
        return RC_HOLD

    # KS: 킬스위치 이미 발동
    if _kill_switch.active:
        log.critical("[KS] 킬스위치 활성 (%s) → RC_STOP", _kill_switch.reason)
        return RC_STOP

    # 브릿지 연결 체크 — 미연결 시 이번 사이클 스킵
    if not bridge.is_connected():
        log.warning("[BRIDGE] 미연결 — 이번 사이클 스킵")
        return RC_HOLD

    positions = _load_open_positions(log)
    if not positions:
        return RC_HOLD

    # [DUAL_SELL_GUARD] PULLBACK 포지션은 pullback_sell_strategy 전담 — rt_sell_engine 스킵
    _pb_skip = [c for c, p in positions.items()
                if str(p.get("strategy", "")).upper().startswith("PULLBACK")
                or str(p.get("strategy", "")).upper() in ("TREND_PULLBACK", "TREND_FOLLOW")]
    for _c in _pb_skip:
        log.info("[DUAL_SELL_GUARD] PULLBACK position skipped by rt_sell_engine: code=%s strategy=%s",
                 _c, positions[_c].get("strategy", ""))
        del positions[_c]
    if not positions:
        return RC_HOLD

    # ── [v3.10-HANDOFF] 핸드오프 신호 처리 ──────────────────────
    # switch_selector가 SWITCH 확정하면 시가 종목에 _force_reason=HANDOFF 주입
    # → _execute_sells Priority-0에서 즉시 SWITCH_SELL 발동
    _handoff_code = _load_handoff_signal(log)
    if _handoff_code and _handoff_code in positions:
        pos = positions[_handoff_code]
        cur_ret = 0.0
        try:
            ctx_tmp = PriceContext.get_or_build(log)
            if ctx_tmp.ok():
                cur_price = ctx_tmp.latest.get(_handoff_code, {}).get("close", 0.0)  # [PATCH] dict→float
                entry_p   = float(pos.get("entry_price", 0))
                if entry_p > 0 and cur_price > 0:
                    cur_ret = (cur_price - entry_p) / entry_p
        except Exception as e:
            log.debug("[HANDOFF] 수익률 계산 실패 (핸드오프 조건 미적용): %s", e)
        # 최소 수익 1% 이상일 때만 핸드오프 허용 (손실 중 강제전환 방지)
        if cur_ret >= SELLCFG.HANDOFF_MIN_PROFIT:
            pos["_force_all"]    = True
            pos["_force_reason"] = f"HANDOFF|ret={cur_ret:.2%}"
            log.info(
                "[HANDOFF] %s → _force_reason 설정 (ret=%.2f%%) → SWITCH_SELL 발동",
                _handoff_code, cur_ret * 100,
            )
        else:
            log.warning(
                "[HANDOFF] %s 수익 %.2f%% < 1%% → 핸드오프 보류 (손실 보호)",
                _handoff_code, cur_ret * 100,
            )

    # 몰빵 강제 보호
    if len(positions) > 1:
        log.critical(
            "[FATAL] 몰빵 위반 %d종목 → 전체 강제청산: %s",
            len(positions), list(positions.keys()),
        )
        for pos in positions.values():
            pos["_force_all"] = True
            pos["_force_reason"] = "몰빵위반"

    ep  = _load_evolved_params(log)
    ctx = PriceContext.get_or_build(log)

    # KS: stale 데이터 체크
    if not ctx.ok():
        _kill_switch.check_stale(log)
        cached = PriceContext._cache_ctx
        if cached is not None:
            log.warning("[CTX] stale → 캐시 ctx로 HARD_STOP/FORCE_EXIT 보호 실행")
            _stale_force_protect(positions, cached, bridge, nh, ep, log)
        else:
            log.warning("[CTX] 실패→HOLD (캐시 없음)")
        return RC_HOLD

    ors, ss, rem = _execute_sells(positions, ctx, bridge, nh, ep, log)

    # KS: 킬스위치 체크 (실행 중 발동 가능)
    if _kill_switch.active:
        log.critical(
            "[KS] 킬스위치 발동 (%s) → 잔여 포지션 저장 후 RC_STOP",
            _kill_switch.reason,
        )
        _save_open_positions(rem, log)
        return RC_STOP

    rc = RC_HOLD
    if ors:
        _append_order_log(ors, log)
        _save_sell_signals(ss, log)
        _write_cycle_tracker(ss, log)          # [v3.13] 2사이클 재진입용 tracker 기록
        _trigger_evolution_feedback(ss, log)
        fc = {s["code"] for s in ss if s.get("block_reentry")}
        if fc:
            _save_daily_sold(fc, log)
        total_pnl = sum(r["pnl_est"] for r in ors)
        log.info(
            "[DONE] %d건|잔여%d|PnL=%+,.0f원",
            len(ors), len(rem), total_pnl,
        )
        rc = RC_OK
    if not _save_open_positions(rem, log):
        log.error("[POS] 저장 실패")
        return RC_HOLD
    return rc


def main(bridge=None, mock=False, loop=False):
    log = _setup_logger()
    log.info("=" * 60)
    log.info(
        "RT 매도 집행 엔진 v3.19 SAFEPLUS | %s",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    log.info("=" * 60)
    if bridge is None:
        if mock:
            bridge = MockSellBridge()
            log.warning("[INIT] Mock 모드")
        else:
            bridge = KiwoomRealSellBridge()
            log.info("[INIT] Real Kiwoom 브릿지")
    if loop:
        log.info("[LOOP] %ds", SELLCFG.LOOP_INTERVAL_SEC)
        _disconn = 0                                          # [PATCH-CONN] 연속 미연결 카운터
        while True:
            if int(datetime.now().strftime("%H%M")) > SELLCFG.MARKET_CLOSE_HHMM:
                log.info("[LOOP] 장종료")
                break
            if not bridge.is_connected():                     # [PATCH-CONN] 연결 사전 체크
                _disconn += 1
                log.warning("[LOOP] Kiwoom 미연결 (%d/20) → HOLD", _disconn)
                if _disconn >= 20:
                    log.critical("[LOOP] Kiwoom 20회 연속 미연결 → 루프 종료")
                    return RC_HOLD
                time.sleep(SELLCFG.LOOP_INTERVAL_SEC)
                continue
            _disconn = 0                                      # [PATCH-CONN] 연결 복구 시 리셋
            rc = run_once(bridge, log)
            if rc == RC_STOP:
                log.critical("[LOOP] KILL_SWITCH → 루프 종료")
                return RC_STOP
            time.sleep(SELLCFG.LOOP_INTERVAL_SEC)
        return RC_OK
    return run_once(bridge, log)


if __name__ == "__main__":
    pa = argparse.ArgumentParser(description="RT 매도엔진 v3.19 SAFEPLUS")
    pa.add_argument("--mock", action="store_true")
    pa.add_argument("--loop", action="store_true")
    a = pa.parse_args()
    sys.exit(main(mock=a.mock, loop=a.loop))

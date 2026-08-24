# -*- coding: utf-8 -*-
"""
make_rt_intraday_from_prices_1m_v7_23.py
=======================================================
고유 영역  : prices_1m.csv + investor_daily.csv 읽기
             → rt_intraday.csv 출력 (다른 파일 영역 침범 없음)
의존      : params_reader.py (진화 파라미터 자동 반영)

리턴 코드
---------
RC_OK   = 0
RC_HOLD = 200

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  헤지펀드급 설계 근거 (출처 명시)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ■ 모멘텀 팩터: AQR "Value and Momentum Everywhere" (Asness 2013)
    → 가격 모멘텀 + 거래대금 가속도를 prescore 핵심 축으로 채용
  ■ OFI (Order Flow Imbalance): Cont, Kukanov, Stoikov (2014)
    "The Price Impact of Order Book Events"
    → 매수/매도 불균형 비율로 단기 가격 방향성 예측
  ■ ADX (Average Directional Index): Welles Wilder (1978)
    "New Concepts in Technical Trading Systems"
    → 추세 강도 측정, TREND/RANGE 국면 분류 핵심
  ■ RSI (Relative Strength Index): Welles Wilder (1978)
    → 과매수/과매도 필터로 진입 타이밍 검증
  ■ Bollinger Bands Squeeze: John Bollinger (2001)
    "Bollinger on Bollinger Bands"
    → 변동성 압축 후 폭발 패턴 감지
  ■ Kelly Criterion: Kelly (1956), Thorp (1962)
    → 자금 배분 최적화, evolution_engine에서 fraction 산출
  ■ ATR (Average True Range): Welles Wilder (1978)
    → 변동성 기반 리스크 정규화
  ■ VWAP: Berkowitz et al. (1988)
    → 기관 실행 벤치마크, 가격 우위 판단 기준
  ■ 기관 등타기 전략: 개인투자자 고유 전략
    → 기관/외국인 순매수 연속일 기반 모멘텀 라이드
    → "미리 내리기" = OFI 가속도 감소 시 선제 이탈 신호

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1종목 몰빵 전략 — 공격 70% / 안정 30% 아키텍처
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  prescore = attack_score × 0.70 + stable_score × 0.30

  attack_score (공격 — "지금 돈이 몰리는가?")
    axis_value   : 거래대금 절대량 + 가속도          (W_VALUE + W_ACCEL)
    axis_price   : 가격 포지션 + 고점 돌파 + VWAP 우위  (W_CP + W_HB + W_VWP)
    bonus_attack : OFI + ADX + 기관모멘텀 보너스

  stable_score (안정 — "내일 안 빠지는가?")
    axis_supply  : 수급 + 거래량 압력                (W_SUPPLY)
    axis_risk    : 과열 페널티 + 윗꼬리 페널티        (W_RISK)
    inst_ride    : 기관 연속매수일 기반 안정성 가산

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  공용 출력 계약 (시가 / 추세눌림 2전략 공유)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  이 파일의 rt_intraday.csv는 2개 downstream 전략이 공유한다:
    ① rt_execution_engine     (시가 = 시가갭매매)
    ② pullback_sell_engine     (추세눌림 = 장중 눌림목 매매)
  ★ v7_18: 종배(EOD/종가매매) 전략 삭제 — 시가·추세눌림 집중

  ★ 고유 영역 원칙: 이 파일은 rt_intraday.csv 생성만 담당
    downstream 전략별 점수/필터/매매는 각 모듈 고유 영역

  ★ 출력 컬럼 계약: 기존 컬럼 100% 유지 + strategy_hint 등 추가
    → downstream 호환성 절대 보장 (삭제 금지)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  자기 진화 지원 컬럼 (evolution_engine 피드백 루프)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  attack_score    : 공격 점수 (0~50)
  stable_score    : 안정 점수 (0~30)
  prescore_weighted : 가중합산 총점 (attack×atk_w + stable×stb_w)
  strategy_hint   : 권장 전략 (EOD / SIGA / PULLBACK / MULTI)
  inst_ride_score : 기관 라이드 점수 (0~5)

변경 이력
---------
v7_23 [2026-04-18] 진입율 병목 해소 — 2건
      [FIX-1] RVOL_MIN 2.0→1.5 복원
              ENTRY GATE 4개 AND와 결합 시 300→1.3개 수렴 문제 해소
              params.json RVOL_MIN으로 런타임 조정 가능
      [FIX-2] ENTRY GATE 4개 AND → 3개 이상 충족으로 완화
              기존: 4개 전부 AND → 1,700종목 중 1.3개 (300개 목표 불가)
              수정: 4개 중 3개 이상 → 약 27개 → 80→25→5→8→1 파이프라인 정상 작동
              대장주 선별 품질 유지 (3개 이상 = 충분한 기관 확인)
v7_22.1 [2026-04-18] params_reader 연결 완성 — 1건
      [CRIT] params_reader 폴백 체인 — v1_13_final 1순위 추가
             기존: from params_reader (suffix 없음) → _PR_AVAILABLE=False 항상
                   → 대장주 선별 27개 파라미터 기본값 고정 → 런타임 조정 불가
             수정: v1_13_final(실제파일) 1순위 → v1_12 → 구버전 폴백 체인
             효과: RVOL_MIN=2.0 런타임 조정, RS_TOP10_BONUS, SECTOR_LEADER_BONUS 정상 연동
v7_22 [2026-04-18] 96점 달성 — 버그수정 + 안정성 강화
      [BUG-FIX] wick_penalty 반전 버그 수정
                기존: (1.0 - upper_wick_ratio) × 20 → 윗꼬리 없는 좋은 봉에 페널티 최대 (반전!)
                수정: upper_wick_ratio × 20 → 윗꼬리 많은 나쁜 봉에 페널티 최대 (정상)
                영향: stable_score 계산 정상화 → 양봉 강세 종목 우선순위 회복
      [GUARD]   통과율 0.5% 미만 RC_HOLD 반환 (기존 경고만 → 이상 데이터 차단)
      [LOG]     마지막 로그 버전 문자열 v7_18 → v7_22 동기화
      [PARAM]   RVOL_MIN params_reader v1_13 연동 (런타임 조정 가능)
v7_21 [2026-04-18] 헤지펀드 대장주 선별 강화 — C레벨 임원진 회의 결과
      [RVOL-UP] RVOL_MIN 1.5→2.0 (헤지펀드 기준 상향)
      근거: 거래대금 2배 미만 = 기관 실진입 미확인 가능성 높음
            진입 횟수 소폭 감소(5~10%) 대비 대장주 적중률 향상 효과 큼
      연동: rt_intraday_trend_pullback_engine v5_11에서
            RS 상위 10% 점수 보너스 + 섹터 거래대금 1위 점수 보너스 동시 적용
v7_18 [2026-04-10] 종배(EOD) 완전 삭제 + 헤지펀드급 강화 — C레벨 임원진 회의 결과
      ─── 핵심 변경: 종배 삭제 ───
      strategy_hint에서 "EOD" 완전 제거
      _determine_strategy_hint: EOD 로직 삭제, 기본값 DOWN→"PULLBACK"
      HINT_EOD_HB_MIN 상수 삭제 (미사용)
      공용 출력 계약: 3전략→2전략 (시가+추세눌림만 공유)
      ─── 수익률 강화 ───
      DOWN 장 기본값: "EOD"→"PULLBACK" (더 안정적인 눌림 전략)
      PULLBACK 우선순위 추가 강화 (SIGA보다 PULLBACK 우선)
      ─── 학술근거 추가 강화 ───
      Jegadeesh & Titman (1993) 단기 역전 + 추세 동시 포착
      Berkowitz et al. (1988) VWAP 정밀도 강화
v7_17 [2026-04-09] 혼합형 EV 보강 — 주 1일 진입 유지 + 수익률 개선
      기반 파일: v7_15 (순수EV v7_16은 후보 20.5%로 진입 공백 위험 → 기각)
      ─── 핵심 변경: expected_edge 혼합형 교체 ───
      기존(v7_15): (edge×0.50 + ps×0.25 + inst×0.05 + bs×0.20) × risk_adj
      변경(v7_17): (0.60×old_edge + 0.25×ev_component + 0.15×breakout) × risk_adj

      old_edge_score = 기존 v7_15 랭킹 점수 (60% 유지 → 후보 91.8% 통과)
      ev_component   = prob_up × strength  (25% — EV 성분 추가)
      breakout_score = 0.15 별도 (돌파 직전 우선순위 보존)

      prob_up  = 0.35×bs + 0.25×hb_norm + 0.25×close_pos + 0.15×ps_norm
      strength = 0.45×va_norm + 0.35×ofi_l10_norm + 0.20×max(ofi,0)

      ─── 버그 4개 사전 수정 (명세서 scope 오류) ───
      ofi_map.get(code) → r.get('ofi')        [out_rows 루프에서 미접근]
      va_norm           → r.get('volume_accel')/2.5
      ofi_l10_norm      → (r.get('ofi_last10')+1)/2
      hb_norm/close_pos → r.get() 방식으로 통일

      ─── 진입 빈도 검증 (1만종목 시뮬레이션) ───
      v7_15: 98.9% 통과 (필터 없음)
      v7_17: 91.8% 통과 (매일 충분 — 1,561개/1700종목)
      v7_16: 20.5% 통과 (진입 공백 위험 → 기각)

      3전략 모두 통과 확인:
        종배(hb=0.99): 0.5277  시가(hb=0.98): 0.4195  눌림(hb=0.95): 0.2546
v7_15 [2026-04-09] 수익률 핵심 7개 패치 — C레벨 심의 채택
      ─── PATCH-1: expected_edge 구조 교체 (수익률 핵심) ───
      breakout_score = min(max((high_break-0.97)/0.03, 0.0), 1.0) 신설
      가중치: edge 0.55→0.50 / ps_norm 0.35→0.25 / inst_norm 0.10→0.05
              + breakout_score 0.20 추가 (고점 돌파 직전 종목 직결)
      ─── PATCH-2: edge 장세별 가중치 재배분 ───
      UP   : hb_norm 0.35→0.40(핵심강화) close 0.30→0.25 va 0.15→0.20 ofi 0.20→0.15
      DOWN : ofi_l10 0.30→0.40(핵심강화) close 0.35→0.30 wick 0.25→0.20 va 유지
      MIXED: hb_norm 0.25→0.30 ofi_l10 0.22→0.25 close 0.33→0.30 va 0.12→0.10 ofi 0.08→0.05
      ─── PATCH-3: risk_adj 완화 (절충값) ───
      floor 0.65→0.70 / ATR분모 15→18 / heat 0.03→0.02
      (원안 0.75/20은 과대 관대 → 0.70/18 절충으로 급등 초입 살리되 노이즈 차단 유지)
      ─── PATCH-4: edge_floor 완화 (초입 확대) ───
      EDGE_MIN_UP 0.18→0.15 / EDGE_MIN_DOWN 0.22→0.18
      ─── PATCH-5: volume penalty 축소 (초입 보호) ───
      SOFT_VOL_PENALTY_HIGH 3.0→2.0 / MID 1.5→1.0
      ─── PATCH-6: inst_norm 축소 → PATCH-1에 내포 ───
      ─── PATCH-7: TOP_N 절충 ───
      TOP_N 250→200 (원안 150은 3전략 공용 후보 부족 위험)
v7_14 [2026-04-09] 헤지펀드급 97점 달성 — C레벨 임원진 감사 결과 8개 수정
      ─── CRITICAL 수정 (4개) ───
      [CR-1] ATR 보정계수 1.4 → 상수 ATR_SCALE_FACTOR=1.0 으로 교체
             (Wilder 원공식 준수, 매도엔진 ATR과 통일 → 레짐판단 정확도 향상)
      [CR-2] OFI 계산 강화: 전봉 연속성 가중 추가 (_calc_ofi_enhanced)
             (단순 캔들방향 → 연속성 trend_weight 1.2/0.8 보정 → 포착 정밀도 향상)
      [CR-3] inst_accel 분모 로직 수정: abs() 제거, prev3 floor = MIN_ABS×0.5
             (과대평가 방지, 기관 가속도 신뢰도 향상)
      [CR-4] market_flag 이진→삼진: UP/DOWN/MIXED 추가 (±0.5% 완충 구간)
             (횡보장 매일 전략 전환 방지, MIXED: atk=0.56/stb=0.44)
      ─── MID 수정 (3개) ───
      [MID-1] edge_floor → out_rows[0] 참조 제거, market_flag 변수 직접 사용
      [MID-2] vol_5d_fallback 390 → 375 (한국 실유효거래시간 현실 반영)
      [MID-3] upper_wick 이중계산 제거: risk_adj에서 wick_bad 항목 삭제
              (prescore에서 이미 처리 → 3중 불이익 → 2중으로 교정)
      ─── LOW 수정 (1개) ───
      [LOW-1] strategy_hint PULLBACK 우선순위 조건 추가
              (TREND + 눌림구간이면 EOD보다 PULLBACK 먼저 → 추세눌림 기회 확대)
v7_13 [2026-04-05] 96→97.5점 통합패치 — 12개 항목 적용
      [T1]  DOWN 가중치 0.50/0.50→0.42/0.58 (하락장 안정 우선 강화)
      [T2]  DOWN edge 재배분: close_pos 0.35 / ofi_l10 0.30 / wick 0.25 / va 0.10
      [T3]  _load_investor_all() 기관가속도 절대금액 하한 추가 (INST_ACCEL_MIN_ABS=50M)
      [T4]  inst_accel_bonus 3단계화 (>=2.0:100% / >=1.5:75% / >=1.1:35%)
      [T5]  volume_pressure>5.0 하드컷 제거 → soft_volume_penalty (>6.0:3.0 / >5.0:1.5)
      [T6]  expected_edge 계산식 보강: edge 0.55 + ps 0.35 + inst_norm 0.10
      [T7]  risk_adj에 wick/heat 감쇠 추가 (floor 0.65 유지)
      [T8]  strategy_hint MULTI 남발 방지: EOD/SIGA 우선 반환 예외 추가
      [T9]  출력 컬럼 확장: soft_risk_penalty / soft_volume_penalty / wick_penalty / heat_penalty
      [T10] edge_confidence 컬럼 추가 (top1-top2 edge 차이, top1만 기록)
      [T11] TOP_N 기본값 400→250
      [T12] expected_edge 최소 하한: UP≥0.18 / DOWN≥0.22 (하한 미달 종목 제거)
      ─── 지적 문제 병행 수정 ───
      [FIX-A] stable_score 총액 상한 추가 (STABLE_SCORE_MAX=25.0)
      [FIX-B] INST_ACCEL_BONUS/THRESHOLD/VOL5D params_reader 연동 추가
      [FIX-C] VAL_NORM_BASE 기본값 100M→50M (KOSDAQ 1분봉 현실 반영)
v7_12 [2026-04-05] 헤지펀드급 96점 업그레이드 — C레벨 6인 회의 결과 반영
      ─── 크리티컬 버그 수정 (CB1~CB4) ───
      [CB1] axis_risk<-7 하드컷 제거 → soft_risk_penalty로 교체
            (기관 매수 종목이 윗꼬리 조금에 탈락하는 치명적 버그 수정)
      [CB2] wick_penalty 배율 50→20 완화 (3분 고가 기준 페널티 현실화)
      [CB3] inst_accel attack_bonus 미반영 버그 수정
            (기관 가속도를 계산만 하고 scoring에 안 쓰던 낭비 수정)
      [CB4] BB_SQUEEZE_BONUS, POC_RSI_BONUS params.json 연동 완성
            (params_reader에 있지만 v7_11에서 scoring에 미사용)
      ─── 수익률 강화 (P1~P4) ───
      [P1]  vol_5d_rel 보너스 추가 (5일 평균 대비 현재 거래량 신호)
      [P2]  DOWN 시장 ofi_last10 → [0,1] 정규화 (음수 패널티 제거)
      [P3]  UP 시장 high_break → 0.9 기준 정규화 (스케일 맞춤)
      [P4]  inst_accel_bonus: 기관 가속도 1.5 이상 시 attack 보너스
      ─── 안전 강화 (S1~S2) ───
      [S1]  soft_risk_penalty → prescore 가중 감점 (하드블록 → 소프트)
      [S2]  AXIS_RISK 음수 클램프 -12→-8로 강화 (과도 감점 방지 + 위험 감지 유지)
v7_9  [2026-03-27] 정리 프로토콜 적용
v7_10 [2026-04-02] P1 수정 — 수익률 직결 3대 버그 수정
      ① [FIX-H1] TOP_N=400 하드코딩 제거
      ② [FIX-H2] 보너스 하드캡 완화
      ③ [FIX-H3] investor_net 조건문 수정
      파라미터 77→27개, prescore 보너스 7→3개
v7_11 [2026-04-02] 헤지펀드급 업그레이드 + 지침서 P1~P8 통합
      ① prescore 공격70/안정30 명시적 분리
      ② strategy_hint 출력 (downstream 3전략 라우팅)
      ③ inst_ride_score + inst_accel 추가 (기관 등타기 + 가속도)
      ④ 자기진화 피드백 컬럼 확충 (attack/stable/prescore_weighted)
      ⑤ 과잉 최적화 방지 가드레일 (axis별 상한 클램프)
      ⑥ 버전 문자열 v7_11 통일
      ─── 지침서 통합 (P1~P8) ───
      [P1] MIN_VALUE 하드캡 방향 수정: min()→양방향 클램프
           evolution이 TREND=10M 설정하면 10M 그대로 적용
      [P2] W_CP/W_HB/W_VWP params_reader 개별 로드 + W_PRICE 분배 fallback
      [P3] investor_daily.csv 1회 읽기 통합 (_load_investor_all)
      [P4] 하락장 동적 공격/안정 비율 (DOWN=50/50, UP=70/30)
      [P5] ofi_last10 마감 10분 OFI 별도 계산
      [P6] VAL_NORM_BASE 파라미터화 (val_score 정규화 기준)
      [P7] confidence_margin 전체 순위 적용 (1등만→전원)
      [P8] strategy_hint 임계값 params_reader 연동
      ─── 버그 수정 (B1~B10) ───
      [B1]  W_PRICE 분배 로직 수정: 비율분배→배수적용 (prescore 붕괴 방지)
      [B2]  하락장 4중 과벌 → 2중으로 계층화 (후보 0건 방지)
      [B3]  inst_accel 상한 클램프 10.0 (분모 0 폭발 방지)
      [B4]  ATTACK+STABLE 합산 != 1.0 자동 정규화
      [B5]  strategy_hint EOD에 ofi_last10_zone 사용
      [B6]  volume_pressure > 5.0 reject 로그 추가
      [B7]  DOWN 거래대금 부족 reject 로그 추가
      [B8]  accel_score 분모 ACCEL_NORM_DIV 파라미터화
      [B9]  prescore_raw → prescore_weighted 이름 정확화
      [B10] global 변수 초기화 안전장치
      ─── 수익률 최종 개선 (C1~C7 + DOC 통합) ───
      [C1]  W_CP 배수를 _DEF 상수에서 적용 (global 누적 방지)
      [C2]  ACCEL_NORM_DIV global 선언 추가 (UnboundLocalError 방지)
      [C7]  W_CP/W_HB/W_VWP 하드캡 추가 (20/20/16)
      [DOC-1] expected_edge 컬럼 추가 + 최종 정렬 교체 (돈 되는 순)
      [DOC-2] inst_ride × 0.5 축소 (기관 과의존 방지)
      [DOC-3] DOWN risk 배율 1.8 → 1.4 완화 (하락장 후보 확보)
      [DOC-5] confidence_margin 순위감산 제거 → 실점수 차이 사용
      ─── 수익 구조 강화 (최종) ───
      [DOC-1+] expected_edge = (edge×0.6 + prescore_norm×0.4) × risk_adj
               prescore 0~1 정규화 (스케일 맞춤) + 정렬 tuple (edge, prescore)
      [DOC-ATR] risk_adj 완화 max(0.7, 1.0-atr/15) (급등주 진입 허용)
      [DOC-EXEC] exec_cond 3/3→2/3 완화 (초입 진입 가능)
      [DOC-4+] inst_ride × 0.3 + investor_bonus × 0.3 (기관 과의존 최소화)
"""
from __future__ import annotations

import csv
import logging
import math
import os
import sys
import time as _time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

# ── params_reader 연결 ────────────────────────────────────────
# [v7_22 FIX] params_reader 폴백 체인 — 실제 파일 v1_13_final 1순위
# 기존: from params_reader (suffix 없음) → 미존재 → _PR_AVAILABLE=False
#       → RVOL_MIN/RS_TOP10_BONUS/SECTOR_LEADER_BONUS 등 27개 파라미터 기본값 고정
#       → 대장주 선별 런타임 조정 완전 무력화
# 수정: v1_13_final(실제파일) 1순위 → 구버전 폴백
_PR_AVAILABLE = False
_get_선정_fn  = None
try:
    _RUN_DIR = Path(__file__).resolve().parent
    if str(_RUN_DIR) not in sys.path:
        sys.path.insert(0, str(_RUN_DIR))
    import importlib as _pr_il
    for _pr_ver in (
        "params_reader_v1_13_final",   # 실제 파일 1순위
        "params_reader_v1_12",
        "params_reader_",
        "params_reader",               # suffix 없음 최후 폴백
    ):
        try:
            _pr_mod = _pr_il.import_module(_pr_ver)
            _get_선정_fn = _pr_mod.get_선정
            _PR_AVAILABLE = True
            break
        except (ImportError, AttributeError):
            continue
except Exception:
    pass

def _get_선정():
    if _get_선정_fn is not None:
        return _get_선정_fn()
    return {}

RC_OK   = 0
RC_HOLD = 200

# ── 경로 (고유 영역 원칙) ─────────────────────────────────────
BASE_DIR       = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot"))
DATA_DIR       = BASE_DIR / "DATA"
LOG_DIR        = DATA_DIR / "LOG"
PRICES_PATH    = DATA_DIR / "prices_1m.csv"
INVESTOR_PATH  = DATA_DIR / "investor_daily.csv"
EOD_BARS_PATH  = DATA_DIR / "eod_daily_bars.csv"
RT_OUT_PATH      = DATA_DIR / "rt_intraday.csv"
LOG_PATH         = LOG_DIR  / "make_rt_intraday.log"

# ── 필터 시간 ─────────────────────────────────────────────────
FILTER_TIME_FROM = 900
FILTER_TIME_TO   = 1530

# ── 핵심 파라미터 27개 기본값 (params_reader 연결 실패 시 fallback) ──
MIN_VALUE_NOW  = 3_000_000   # [v7_B] 1000만→300만: 600종목 입력 기준 유동성 하한 완화
MIN_VALUE_3M   = 9_000_000   # [v7_B] 3000만→900만: 3분 누적 기준 비례 완화
MIN_PRICE      = 500

W_VALUE  = 20.0
W_ACCEL  = 12.0
W_CP     = 10.0
W_HB     = 10.0
W_VWP    =  8.0
W_SUPPLY = 10.0
W_RISK   =  1.0

BONUS_CAP = float(os.environ.get("BONUS_CAP", "12.0"))  # [v7_20 수정②] 8.0→10.0→12.0: 만점 종목 차별화
TOP_N     = 300   # [수정] 200→300: 헤지펀드 실전 기준 절충 (후보 부족 방지 + 품질 유지)
RVOL_MIN  = 1.5   # [T1-2 2026-05-05] 1.2→1.5 헤지펀드 기준 복원 (풀 노이즈 감소)

HEAT_STRONG_THRESHOLD = 6.0
HEAT_MILD_THRESHOLD   = 4.0
HEAT_STRONG_PENALTY   = 3.0
HEAT_MILD_PENALTY     = 3.0

COND2_MULT  = 1.8
COND3_RATIO = 0.995

ADX_TREND_THRESHOLD = 25
ADX_BONUS_STRONG    = 3.0
ADX_BONUS_TREND     = 2.0

RSI_GOOD_LOW  = 50.0
RSI_GOOD_HIGH = 70.0
RSI_OVER_LOW  = 30.0

# [v7_20] 기관 초입 ENTRY GATE 상수
# 문서 참조: "기관 + 흐름 + 돌파 직전" 동시 충족 시만 진입
OFI_ENTRY_MIN          = 0.30   # [패치1] intraday OFI ≥ 0.3 (기관 실매수 흐름)
INST_ACCEL_ENTRY_MIN   = 1.05   # [패치2] 기관 가속도 ≥ 1.05 (초입 포착 1.20→1.05)
HIGH_BREAK_ENTRY_MIN   = 0.93   # [패치3] 고점 대비 ≥ 93% (초입~중간 포착, 0.97→0.93)
INST_RATIO_ENTRY_MIN   = 0.02   # [패치4] 기관 순매수 / 거래대금 ≥ 2% (진짜 기관)

OFI_BONUS_STRONG = 2.0
OFI_BONUS_MILD   = 1.0
INVESTOR_BONUS   = 2.0

# ── [v7_12 NEW] BB_SQUEEZE / RSI / inst_accel 보너스 ─────────
BB_SQUEEZE_BONUS      = 3.0    # BB 스퀴즈 발생 시 안정 보너스
POC_RSI_BONUS         = 4.0    # RSI GOOD 구간 시 안정 보너스
# [v7_20 수정②] 기관 보너스 강화 — 지시의 의도(기관 종목 우선순위 상승)를 실제 구조에 맞게 적용
# 지시 공식 min(0.18, inst_accel*0.10)은 이 파일에 없는 변수 → INST_ACCEL_BONUS 상수 강화로 대체
INST_ACCEL_BONUS      = 3.0    # [v7_20] 2.0→3.0: 기관 가속도 보너스 50% 강화
INST_ACCEL_THRESHOLD  = 1.5    # 기관 가속도 임계값 (75% 보너스 기준, 2.0이상=100%)
VOL5D_BONUS_MAX       = 3.0    # 5일 평균 대비 거래량 급등 최대 보너스
VOL5D_BONUS_THRESHOLD = 2.0    # 5일 평균 대비 몇 배 이상이면 보너스 시작

# ── [v7_13 NEW] 통합패치 상수 ────────────────────────────────
INST_ACCEL_MIN_ABS    = 50_000_000  # [T3] 기관가속도 절대금액 하한 (50M 미만은 가속도=0)
STABLE_SCORE_MAX      = float(os.environ.get("STABLE_SCORE_MAX", "30.0"))        # [FIX-A] stable_score 총액 상한 (env: 가중치 의도 회복 25→30)
EDGE_MIN_UP           = 0.10        # [PATCH-4] 0.18→0.15→0.10: 초입 종목 유입 확대
EDGE_MIN_DOWN         = 0.10        # [PATCH-4] 0.22→0.18→0.10: DOWN 시장 초입 확대
SOFT_VOL_PENALTY_HIGH = 2.0         # [PATCH-5] 3.0→2.0: 거래 터지는 초입 보호
SOFT_VOL_PENALTY_MID  = 1.0         # [PATCH-5] 1.5→1.0: 거래 초입 보호

# ── [P6] val_score 정규화 기준 (evolution 대상) ──────────────
VAL_NORM_BASE    = 50_000_000    # [FIX-C] 100M→50M (KOSDAQ 1분봉 평균 3~5천만 현실 반영)

# ── [P1] MIN_VALUE 양방향 클램프 범위 ────────────────────────
MIN_VALUE_FLOOR  = 500_000       # 절대 하한 (유동성 부족 방지)
MIN_VALUE_CEIL   = 50_000_000    # 절대 상한 (과도 필터 방지)

# ── [P8] strategy_hint 임계값 (evolution 연동) ───────────────
# [v7_18] HINT_EOD_HB_MIN 삭제 — 종배(EOD) 전략 제거
HINT_PULLBACK_CP_LOW  = 0.30    # PULLBACK: close_position 하한
HINT_PULLBACK_CP_HIGH = 0.70    # PULLBACK: close_position 상한
HINT_SIGA_VA_MIN      = 1.2     # SIGA: volume_accel 최소

# ── [B8] accel_score 정규화 분모 (evolution 대상) ────────────
ACCEL_NORM_DIV        = 8.0     # val_accel_ratio / 이 값 으로 정규화

# ── [B3] inst_accel 상한 ─────────────────────────────────────
INST_ACCEL_MAX        = 10.0    # 비정상 폭발 방지

# ── [v7_22 ADD-1] 대장주 선별 강화 기본값 ────────────────────
RS_TOP10_BONUS       = float(os.environ.get("RS_TOP10_BONUS", "0.10"))   # RS 상위 10% expected_edge 보너스 (params.json 미설정 시 무효)
RS_TOP10_PERCENTILE  = 0.90  # ps_norm 기준 상위 10% 임계값
SECTOR_LEADER_BONUS  = 0.0   # 섹터 1위 보너스 (sector 데이터 없어 현재 미적용) — ee스케일 죽은슬롯

# [SECTOR_LEADER A안 2026-06-04] 테마 대장주(네이버 테마강도) prescore 보너스 — A방식(prescore 가산).
#   기존 SECTOR_LEADER_BONUS(ee스케일)는 적용코드 없던 죽은슬롯 → prescore(0~100) 스케일 별도 env로 안전 분리.
#   code_theme_strength.csv(is_leader & best_theme_rank<=MAX)면 prescore에 가산 → rt_risk Top1(prescore_weighted) 전파.
#   prescore 낮은 종목은 보너스 받아도 1등 안 됨(A방식=안전). 데이터 없으면 보너스0(기존 동작 fallback).
SECTOR_LEADER_ENABLE   = os.environ.get("SECTOR_LEADER_ENABLE", "YES").strip().upper() == "YES"
SECTOR_LEADER_RANK_MAX = int(os.environ.get("SECTOR_LEADER_RANK_MAX", "20"))     # 강테마 기준(theme_rank<=20)
SECTOR_LEADER_MAX_PTS  = float(os.environ.get("SECTOR_LEADER_MAX_PTS", "12.0"))   # [2026-06-06] 5→8→12: 사용자 확신(테마대장주 중요). 강제승격 대신 가점으로 실제 1등 가능 수준(rank≤6 강테마대장주가 모멘텀1등 제압 가능). prescore 스케일(rank1=full,rank20≈0). A방식=base 낮으면 여전히 1등 안 됨(과적합 방지·forward 추적기로 검증후 조정).
# [THEME-INJECT 1순위 2026-06-05] TOP_N(160) 컷에서 밀린 강테마 KOSDAQ 대장주를 rt_intraday 풀에 force-include.
#   거래대금/edge로 컷되는 대장주(예 080220 주성반도체)가 풀 진입 못해 SECTOR_LEADER 보너스 무의미하던 것 해소.
#   _pre_cut(KOSDAQ필터+정렬된 컷 전 전체)에서 잘린 대장주만 복원 → 신선+KOSDAQ분만(stale는 rt_execution서 재차 거름).
MAKE_RT_THEME_INJECT_ENABLE = os.environ.get("MAKE_RT_THEME_INJECT_ENABLE", "YES").strip().upper() == "YES"
MAKE_RT_THEME_INJECT_MAX    = int(os.environ.get("MAKE_RT_THEME_INJECT_MAX", "12"))   # [10→12 2026-06-07] 풀 force-include 상한. 수집기 THEME_LEADER_BUCKET_MAX(12)와 정렬 — 수집된 대장주가 160컷 밖으로 밀려도 전부 복원(수집해놓고 make_rt서 재누락 방지). 풀에 추가만(displace無). env복귀=10.

# [LEADER-ONLY 2026-06-14 ★친구님 설계] RT 출력(rt_intraday)을 '테마 대장주(테마마다 1등)'만으로 제한.
#   대장주 = theme_strength.csv leader_code (테마당 1명, KOSDAQ만). is_leader(좁은 61개) 아님 = 친구님 확인 165개.
#   친구님 의도: RT가 대장주만 뽑아 스코어보드+리스크 공통입력 → 리스크가 160→80→25→8로 그날 모멘텀 거름.
#   데이터없음/stale/대장 0개매칭 → 필터 스킵(전체유지=무영향, no-crash). 기본 OFF. 롤백 setx MAKE_RT_LEADER_ONLY NO.
#   ⚠rt_intraday는 스코어보드(종가매수)도 읽음 → 켜면 종가매수 후보도 대장주만(친구님 '둘 다' 의도).
MAKE_RT_LEADER_ONLY  = os.environ.get("MAKE_RT_LEADER_ONLY", "NO").strip().upper() == "YES"
_THEME_STRENGTH_FILE = Path(r"C:\stock_bot\data\theme\theme_strength.csv")
_THEME_LEADER_CACHE  = {"date": None, "set": set()}

# [INTENT-STAGE2 2026-06-07] W1/W2 fix — 2단(300→160)을 expected_edge 재컷(=가짜압축) 대신 '사용자 의도 점수'로 재경쟁.
#   W1: 기존 300컷·160컷이 같은 expected_edge라 600→160 단일컷과 동일(2단 무의미) → 2단을 intent_score로 재정렬.
#   W2: backbone 모멘텀(high_break)편향 → 테마대장주+기관등타기+장중수급+눌림위치로 재가중.
#   재정렬(soft)만, hard-cut 금지. 1단은 expected_edge 유지(넓게). THEME-INJECT/SECTOR_LEADER 유지. 컬럼추가 없이 로그만(스키마 무변).
MAKE_RT_INTENT_STAGE2_ENABLE = os.environ.get("MAKE_RT_INTENT_STAGE2_ENABLE", "YES").strip().upper() == "YES"  # OFF=기존 expected_edge 160컷
INTENT_W_THEME = float(os.environ.get("INTENT_W_THEME", "0.30"))   # 테마 대장주(절대: rank1=1.0)
INTENT_W_INST  = float(os.environ.get("INTENT_W_INST",  "0.25"))   # 기관 동행(ride/accel/net_buy/consec)
INTENT_W_FLOW  = float(os.environ.get("INTENT_W_FLOW",  "0.20"))   # 장중 수급(ofi/ofi10/vol_accel/cvr/l5a)
INTENT_W_POS   = float(os.environ.get("INTENT_W_POS",   "0.15"))   # 눌림/위치(vwap·close_position 밴드, 고점과근접 감점)
INTENT_W_BASE  = float(os.environ.get("INTENT_W_BASE",  "0.10"))   # 기존 품질 안전판(expected_edge 풀내 퍼센타일)
_SECTOR_THEME_FILE  = Path(r"C:\stock_bot\DATA\theme\code_theme_strength.csv")
_SECTOR_LEAD_CACHE  = {"date": None, "map": {}}

def _get_sector_leaders() -> Dict[str, tuple]:
    """code_theme_strength.csv(네이버 테마강도) → {code:(is_leader, theme_rank, strength)}. 일자 캐시.
    파일없음/3일 stale → 빈 dict(보너스0=기존 동작). 최신일 행만 사용."""
    _today = _time.strftime("%Y%m%d")
    if _SECTOR_LEAD_CACHE["date"] == _today:
        return _SECTOR_LEAD_CACHE["map"]
    m: Dict[str, tuple] = {}
    try:
        if _SECTOR_THEME_FILE.exists() and (_time.time() - _SECTOR_THEME_FILE.stat().st_mtime) / 86400.0 <= 3.0:
            with _SECTOR_THEME_FILE.open("r", encoding="utf-8-sig", errors="replace") as _f:
                _rows = list(csv.DictReader(_f))
            _latest = max((str(r.get("date", "")) for r in _rows), default="")
            # [KOSDAQ-ONLY 2026-06-08] 테마대장주도 KOSDAQ만 — 매수후보 KOSDAQ-FILTER와 일치.
            #   네이버 테마는 전체시장(KOSPI+KOSDAQ)이라 삼성전자/현대백화점 등 KOSPI 대형주가 상위 rank 점령 →
            #   우리 매수대상 KOSDAQ 대장주(기가비스 등) rank 밀려 가점 손해. KOSPI 제외 + KOSDAQ 내 rank 재계산.
            #   KOSDAQ셋 로드 실패시 _kdq=None → 전체 사용(기존 동작 fallback).
            import logging as _logging
            _kdq = _load_kosdaq_codes(_logging.getLogger("sector_leaders"))
            _cands = []
            for r in _rows:
                if str(r.get("date", "")) != _latest:
                    continue
                try:
                    c = str(r.get("code", "")).zfill(6)
                    if _kdq and c not in _kdq:   # KOSPI/ETF 제외 (KOSDAQ셋 로드된 경우만)
                        continue
                    _cands.append((c,
                                   str(r.get("is_leader", "0")).strip() == "1",
                                   int(float(r.get("best_theme_rank", 999) or 999)),
                                   float(r.get("best_strength", 0) or 0),
                                   float(r.get("strength_short", 0) or 0)))
                except (TypeError, ValueError):
                    pass
            # [KOSDAQ-ONLY] KOSDAQ 대장주(is_leader)만 테마순위로 재정렬 → 새 rank(1,2,...).
            #   KOSPI 빠진 만큼 KOSDAQ 대장주 rank 상향 = SECTOR_LEADER 가점 정상화.
            # [SHORT-RANK 2026-06-10] 장중 눌림은 단기(5-3-1) 테마성분이 예측력 핵심(백테 442건:
            #   단기+ 승률 29~31%/-0.67% vs 단기- 21~26%/-0.83~-1.10%, +0.3~0.44%p 일관) —
            #   기존 multi rank(장기 0.6 가중)는 단기신호 희석. 눌림용 rank를 strength_short 내림차순으로.
            #   롤백 env SECTOR_LEADER_RANK_MODE=MULTI(기존). 종가매수(signal_v2)는 별도 경로라 무영향.
            _rank_mode = os.environ.get("SECTOR_LEADER_RANK_MODE", "SHORT").strip().upper()
            if _rank_mode == "SHORT":
                _leaders_sorted = sorted([x for x in _cands if x[1]], key=lambda x: -x[4])
            else:
                _leaders_sorted = sorted([x for x in _cands if x[1]], key=lambda x: x[2])
            _new_rank = {x[0]: i for i, x in enumerate(_leaders_sorted, 1)}
            for c, _isl, _rk, _st, _ss in _cands:
                m[c] = (_isl, _new_rank.get(c, _rk), _st)
    except Exception:
        m = {}
    _SECTOR_LEAD_CACHE["date"] = _today
    _SECTOR_LEAD_CACHE["map"] = m
    return m


def _get_theme_leaders_full() -> set:
    """[LEADER-ONLY] 테마 대장주 명단 = theme_strength.csv leader_code (테마마다 1등), KOSDAQ만, 최신일.
    친구님 확인=165개(is_leader 61개 아님). 일자 캐시. 파일없음/3일stale/실패 → 빈 set(필터 스킵=무영향)."""
    _today = _time.strftime("%Y%m%d")
    if _THEME_LEADER_CACHE["date"] == _today:
        return _THEME_LEADER_CACHE["set"]
    s: set = set()
    try:
        if _THEME_STRENGTH_FILE.exists() and (_time.time() - _THEME_STRENGTH_FILE.stat().st_mtime) / 86400.0 <= 3.0:
            with _THEME_STRENGTH_FILE.open("r", encoding="utf-8-sig", errors="replace") as _f:
                _rows = list(csv.DictReader(_f))
            _latest = max((str(r.get("date", "")) for r in _rows), default="")
            import logging as _logging
            _kdq = _load_kosdaq_codes(_logging.getLogger("theme_leaders_full"))
            for r in _rows:
                if str(r.get("date", "")) != _latest:
                    continue
                c = str(r.get("leader_code", "")).strip().zfill(6)
                if not c or c == "000000":
                    continue
                if _kdq and c not in _kdq:   # KOSPI/ETF 제외 (KOSDAQ셋 로드된 경우만)
                    continue
                s.add(c)
    except Exception:
        s = set()
    _THEME_LEADER_CACHE["date"] = _today
    _THEME_LEADER_CACHE["set"] = s
    return s

# ── [CR-1] ATR 스케일 팩터 (Wilder 원공식 = 1.0, 매도엔진 통일) ──
# 기존 1.4 보정은 학술 근거 없음 → 1.0으로 교정
# 변경 시 rt_sell_engine ATR 기준과 통일 → 레짐 오분류 방지
ATR_SCALE_FACTOR        = 1.0

# ── [v7_24] 수집계층 안전 상수 ──────────────────────────────────
# PRICES_STALE_WARN_SEC / PRICES_STALE_HOLD_SEC 제거 [v7_24 B안]
# → age 초 기준 대신 mtime 날짜 기준으로 교체 (EOD 워크플로 호환)
PRICES_MIN_CODES        = 32    # [SANITY32 2026-05-11] 35→32 완화. 5/11 [SANITY-OBS] 분포 실측: 32+ 통과율 96.4% / 35+ 62.4%. 35는 over-rejection (37.6% 차단), 32~34 구간(34%) 회복으로 funnel 1차 게이트 완화. 27 이하는 여전히 RC_HOLD.
GAP_WARN_MIN            = 5     # 종목 내 최대 gap 경고 임계 (분)
GAP_HOLD_MIN            = 240   # 종목 내 최대 gap 제거 임계 (분)

# ── 고정 상수 (evolution 대상 아님) ──────────────────────────
ACCEL_CAP               = 50.0
VOL_ACCEL_PREV_FROM     = 1512
VOL_ACCEL_PREV_TO       = 1518
VOL_ACCEL_LAST_FROM     = 1518
VOL_ACCEL_LAST_TO       = 1523
# [2026-06-09 라이브 가속도] 고정 window(15:12-23)은 make_rt 장중실행 시 미래라 volume_accel=0(죽음).
#   YES면 아래서 코드별 최근5봉/직전5봉으로 재계산(라이브). 롤백 env PB_VACC_LIVE_WINDOW=NO.
PB_VACC_LIVE_WINDOW     = os.environ.get("PB_VACC_LIVE_WINDOW", "YES").strip().upper() == "YES"
PREV10_TIME_FROM        = 900
PREV10_TIME_TO          = 1030
MIN_WINDOW_VALUE        = 1_000_000
INVESTOR_FILTER_ENABLED = True
KOSPI_INDEX_CODES       = {"U001", "001", "0001", "KOSPI"}
KOSDAQ_INDEX_CODES      = {"U201", "101", "0101", "KOSDAQ"}
MARKET_FLAG_MA_PERIOD   = 200
MARKET_FALLBACK_TOP_N   = 50
MARKET_FALLBACK_MIN_VAL = 500_000_000
ATR_EMA_PERIOD          = 14
ADX_PERIOD              = 14
ADX_WEAK_THRESHOLD      = 20
RSI_PERIOD              = 14
BB_PERIOD               = 20
BB_STD_MULT             = 2.0
BB_SQUEEZE_WINDOW       = 50
BB_SQUEEZE_PCT          = 0.20
VOL_5D_EST_FROM         = 900
VOL_5D_EST_TO           = 1400

# ── [P5] 마감 구간 OFI 시간 범위 ─────────────────────────────
OFI_LAST10_FROM         = 1513   # 마감 10분 시작
OFI_LAST10_TO           = 1523   # 마감 10분 종료

# ── [v7_11] 공격70/안정30 비율 상수 ──────────────────────────
ATTACK_WEIGHT = 0.70
STABLE_WEIGHT = 0.30

# ── [v7_11] 기관 라이드 상수 ──────────────────────────────────
INST_RIDE_BONUS_PER_DAY = 0.8   # 연속 순매수 1일당 보너스
INST_RIDE_MAX           = 5.0   # 최대 기관 라이드 점수
INST_STRONG_DAYS        = 3     # "강한 기관" 최소 연속일

# ── [v7_11] 과잉 최적화 방지 가드레일 ────────────────────────
# 각 축이 prescore를 지배하지 못하도록 상한 클램프
AXIS_VALUE_MAX   = 30.0    # 거래대금축 상한 (과대 거래대금에 의한 왜곡 방지)
AXIS_PRICE_MAX   = 25.0    # 가격축 상한
AXIS_SUPPLY_MAX  = 18.0    # 수급축 상한
AXIS_RISK_FLOOR  = -8.0    # [v7_12] -12→-8: 소프트 전환으로 하드컷 제거 대신 감점 구간 좁힘

# ── 출력 헤더 (기존 + v7_11 확장) ─────────────────────────────
OUTPUT_HEADER = [
    "ts", "code",
    # [W55 PATCH 2026-05-13] price_now 절대 가격 컬럼 추가
    #   rt_execution L2414 best["row"].get("price_now", 0) 사용
    #   기존: rt_intraday 가격 컬럼 부재 → price=0 → RC_HOLD
    #   수정: 1분봉 close 값 (정수, 원 단위)
    "price_now",
    "value_now", "value_prev", "value_3m", "value_5m", "value_day",
    "price_vs_vwap", "price_vs_day_high",
    "accel_real", "volume_pressure", "price_break_strength", "close_pos_3m",
    "close_position", "high_break", "last3_ret",
    "upper_wick_ratio", "volume_accel", "close_value_ratio",
    "last5_value_accel",
    "pb_pullvol_ratio",   # [PULLVOL 2026-06-11] 눌림구간 거래량/직전상승 거래량 (폭증 눌림 차단용)
    "net_buy_flag",
    "exec_cond1", "exec_cond2", "exec_cond3",
    "trade_density_accel",
    "market_flag", "atr_pct", "vol_5d_avg",
    "adx", "adx_trend",
    "rsi", "rsi_zone",
    "bb_squeeze", "bb_width",
    "ofi", "ofi_zone",
    "confidence_margin",
    # ── v7_11 확장 컬럼 (자기진화 + downstream 라우팅) ──
    "attack_score",       # 공격 점수 (가중 전, 0~50)
    "stable_score",       # 안정 점수 (가중 전, 0~30)
    "prescore_weighted",   # [B9] 가중합산 총점 (attack×atk_w + stable×stb_w)
    "strategy_hint",      # 권장 전략 (EOD/SIGA/PULLBACK/MULTI)
    "inst_ride_score",    # 기관 라이드 점수 (0~5)
    "ofi_last10",         # [P5] 마감 10분 OFI (-1~1)
    "ofi_last10_zone",    # [P5] 마감 10분 OFI 구간
    "inst_accel",         # [P3] 기관 매집 가속도 (최근3일/이전3일)
    "expected_edge",      # [DOC-1] 기대수익 점수 (최종 정렬 기준)
    # ── v7_13 확장 컬럼 ──────────────────────────────────────
    "soft_risk_penalty",    # [T9] 리스크 소프트 패널티 (prescore 차감량)
    "soft_volume_penalty",  # [T9] 거래량 소프트 패널티 (prescore 차감량)
    "wick_penalty",         # [T9] 윗꼬리 페널티 (raw 값, 디버그용)
    "heat_penalty",         # [T9] 과열 페널티 (raw 값, 디버그용)
    "edge_confidence",      # [T10] top1 확신도 (top1-top2 edge 차이, top1만 기록)
    "gap_pct",              # [GAP] 당일 시가 갭 (%) = (시가-전일종가)/전일종가×100
    "dv_accel",             # [DV] 방향성 거래량 가속도 (최근10봉DV합/이전10봉DV합)
]


# ── 유틸 ──────────────────────────────────────────────────────
def _env_float(key: str, default: float) -> float:
    try:
        v = os.environ.get(key, "").strip()
        return float(v) if v else default
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        v = os.environ.get(key, "").strip()
        return int(float(v)) if v else default
    except Exception:
        return default

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("make_rt_intraday")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt); logger.addHandler(sh)
    except Exception:
        pass
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(LOG_PATH), maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt); logger.addHandler(fh)
    except Exception:
        pass
    return logger

def _normalize_code(x: Any) -> str:
    s = "" if x is None else str(x).strip().replace("'","").replace('"',"")
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) >= 6: digits = digits[-6:]
    if digits.isdigit() and 1 <= len(digits) <= 6:
        return digits.zfill(6)
    return s

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None: return None
        s = str(x).strip().replace(",","")
        return float(s) if s else None
    except Exception:
        return None

def _safe_makedirs(p: Path) -> None:
    try: p.mkdir(parents=True, exist_ok=True)
    except Exception: pass

def _atomic_write_csv(path: Path, header: List[str], rows: List[Dict]) -> None:
    tmp = Path(str(path) + ".tmp")
    _safe_makedirs(path.parent)
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
            f.flush(); os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            if tmp.exists(): tmp.unlink(missing_ok=True)
        except Exception: pass

def _iter_csv_rows(path: Path, logger: logging.Logger,
                   required_cols: Optional[List[str]] = None) -> Iterator[Dict]:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames: continue
                reader.fieldnames = [str(c).strip() for c in reader.fieldnames]
                if required_cols:
                    missing = [c for c in required_cols if c not in reader.fieldnames]
                    if missing:
                        logger.error("[FATAL] %s 필수 컬럼 없음: %s", path.name, missing)
                        return
                for row in reader: yield row
                return
        except UnicodeDecodeError: continue
        except Exception as e:
            logger.error("[FATAL] %s 읽기 실패: %s", path.name, e)
            return
    logger.error("[FATAL] %s 인코딩 모두 실패", path.name)

def _hhmm(ts: str) -> Optional[int]:
    try:
        digits = "".join(c for c in ts if c.isdigit())
        return int(digits[-6:-2]) if len(digits) >= 6 else None
    except Exception: return None

def _ts_int(ts: str) -> int:
    try: return int("".join(c for c in ts if c.isdigit()))
    except Exception: return 0


# ── [P3] investor_daily 통합 로드 (1회 읽기) ─────────────────
def _load_investor_all(logger: logging.Logger,
                       daily_value_map: Dict[str, float] = None) -> tuple:
    """
    investor_daily.csv 1회 읽기 → (순매수 dict, 연속일 dict, 가속도 dict) 반환
    [P3] 기존 _load_investor + _load_investor_consec 통합
    [경고-2 수정] daily_value_map: 종목별 일평균 거래대금 → 동적 INST_ACCEL_MIN_ABS
    """
    if daily_value_map is None:
        daily_value_map = {}

    investor_net: Dict[str, float] = {}
    inst_consec: Dict[str, int] = {}
    inst_accel: Dict[str, float] = {}
    inst_tier: Dict[str, float] = {}   # [MULTI-TIER 2026-06-02] 20일 대장주 + 5/3/1 단기 통합 기관점수

    if not INVESTOR_PATH.exists() or INVESTOR_PATH.stat().st_size == 0:
        logger.warning("[INVESTOR] %s 없음 또는 0바이트 → 수급 필터 스킵", INVESTOR_PATH)
        return investor_net, inst_consec, inst_accel, inst_tier
    # [신규] mtime 검사 — 경고만 (휴일 가능성 고려, 사용은 계속)
    import time as _t_inv
    _age_h = (_t_inv.time() - INVESTOR_PATH.stat().st_mtime) / 3600
    _stale_warn_h = float(os.environ.get("INVESTOR_STALE_WARN_H", "72"))
    if _age_h > _stale_warn_h:
        logger.warning("[INVESTOR] ⚠️ 데이터 stale %.1fh > %.0fh — 휴일 후 미갱신 가능", _age_h, _stale_warn_h)

    # 종목별 전체 기록 수집 (1회 읽기)
    history: Dict[str, List[tuple]] = {}
    for row in _iter_csv_rows(INVESTOR_PATH, logger,
                              required_cols=["code","foreign_net","inst_net"]):
        code = _normalize_code(row.get("code"))
        if code:
            code = str(code).zfill(6)
        if not code: continue
        date_str = str(row.get("date","")).strip()
        fnet = _to_float(row.get("foreign_net")) or 0.0
        inet = _to_float(row.get("inst_net"))    or 0.0
        history.setdefault(code, []).append((date_str, fnet + inet))

    _small_cap_relaxed = 0  # 소형주 완화 적용 카운트 로그용

    for code, records in history.items():
        records.sort(key=lambda x: x[0], reverse=True)  # 최신 먼저

        # ① 순매수: 가장 최근 날짜
        if records:
            investor_net[code] = records[0][1]

        # ② 연속 순매수일
        consec = 0
        for _, net in records:
            if net > 0:
                consec += 1
            else:
                break
        inst_consec[code] = consec

        # ③ 기관 매집 가속도: 최근 3일 / 이전 3일 순매수 금액 비교
        # [CR-3] v7_14 수정:
        #   - abs() 제거 (net>0 조건과 중복, 의도 불명확)
        #   - prev3=0일 때 분모 floor = INST_ACCEL_MIN_ABS×0.5 (기존 recent3×0.1 → 과대평가 방지)
        # [B3] 상한 INST_ACCEL_MAX 유지
        # [경고-2 수정] 종목별 일평균 거래대금 기반 동적 하한 적용
        _dyn_min = _get_dynamic_inst_accel_min(code, daily_value_map, INST_ACCEL_MIN_ABS)
        if _dyn_min < INST_ACCEL_MIN_ABS:
            _small_cap_relaxed += 1

        if len(records) >= 6:
            recent3 = sum(net for _, net in records[:3] if net > 0)
            prev3   = sum(net for _, net in records[3:6] if net > 0)
            if recent3 < _dyn_min:                    # [경고-2] 동적 하한
                inst_accel[code] = 0.0
            else:
                _prev3_floor = _dyn_min * 0.5         # [CR-3] prev3=0 과대평가 방지
                raw_accel = recent3 / max(prev3, _prev3_floor)
                inst_accel[code] = round(min(raw_accel, INST_ACCEL_MAX), 2)
        elif len(records) >= 3:
            recent3 = sum(net for _, net in records[:3] if net > 0)
            if recent3 < _dyn_min:                    # [경고-2] 동적 하한
                inst_accel[code] = 0.0
            else:
                inst_accel[code] = min(1.0, INST_ACCEL_MAX)
        else:
            inst_accel[code] = 0.0

        # [MULTI-TIER 2026-06-02] 사용자 설계 복원: 20일 대장주 체크 + 5/3/1 단기 진입 통합.
        #   records 최신순(0=오늘). short=5/3/1/오늘 가중(최근↑, 진입 신선도). long=최근20일 순매수비율(대장주 강도).
        #   ※ 오늘(0)은 장중 미집계(0) 흔함→net>0 자동처리. 데이터 누적후 20일 완전작동(현재 ~10거래일). env로 가중조정.
        _mt_long_win = int(os.environ.get("MULTI_TIER_LONG_DAYS", "20"))
        _mt_short = [(0, 0.30), (1, 0.30), (3, 0.25), (5, 0.15)]   # 오늘/1일전/3일전/5일전
        _mt_s = sum(_w for _i, _w in _mt_short if _i < len(records) and records[_i][1] > 0)
        _mt_win = records[:_mt_long_win]
        _mt_l = (sum(1 for _, _n in _mt_win if _n > 0) / len(_mt_win)) if _mt_win else 0.0
        inst_tier[code] = round(min(1.0, _mt_s * 0.6 + _mt_l * 0.4), 4)

    buy_count  = sum(1 for v in investor_net.values() if v > 0)
    sell_count = sum(1 for v in investor_net.values() if v <= 0)
    consec_3plus = sum(1 for v in inst_consec.values() if v >= INST_STRONG_DAYS)
    accel_up = sum(1 for v in inst_accel.values() if v > 1.0)
    logger.info("[INVESTOR] codes=%d 순매수=%d 순매도=%d 강한기관(≥%d일)=%d 가속=%d 소형주완화=%d",
                len(investor_net), buy_count, sell_count,
                INST_STRONG_DAYS, consec_3plus, accel_up, _small_cap_relaxed)
    _tier_strong = sum(1 for v in inst_tier.values() if v >= 0.30)
    logger.info("[MULTI-TIER] 20일+5/3/1 통합 기관점수: tier≥0.30(게이트통과가능)=%d종목 / 전체=%d",
                _tier_strong, len(inst_tier))
    return investor_net, inst_consec, inst_accel, inst_tier


def _load_kosdaq_codes(logger: logging.Logger) -> Optional[Set[str]]:
    """[KOSDAQ-FILTER 2026-06-01] rt 후보를 KOSDAQ로 제한하기 위한 코드셋.
    소스=eod_daily_bars.csv(날짜 오름차순) 최신 거래일 market==KOSDAQ + SKIP_KW(스팩/SPAC/ETN/ETF/리츠/우선주) name 제외.
    Why: KOSPI 대형주·ETF가 유동성/OFI가 커 expected_edge 상위·top20보호를 점령 → KOSDAQ 후보가 밀림.
         (정확성은 스코어보드 KOSDAQ 필터가 보장하나, rt 단계에서 거르면 KOSDAQ 후보 깊이↑·top20 보호가 진짜 대장주에)
    pandas 미사용(_iter_csv_rows 1-pass, 최신일 등장 시 set 리셋). 실패/빈셋(<100)이면 None → 필터 skip(fail-open)."""
    try:
        if not EOD_BARS_PATH.exists() or EOD_BARS_PATH.stat().st_size == 0:
            logger.warning("[KOSDAQ-FILTER] eod_daily_bars 없음 → 필터 skip")
            return None
        _skip = ("스팩", "SPAC", "ETN", "ETF", "리츠", "우선주")
        max_date = ""
        codes: Set[str] = set()
        for row in _iter_csv_rows(EOD_BARS_PATH, logger):
            d = str(row.get("date", "")).strip()
            if not d:
                continue
            if d > max_date:
                max_date = d
                codes = set()          # 더 최신 거래일 등장 → 리셋 (파일 날짜 오름차순)
            if d == max_date and str(row.get("market", "")).strip() == "KOSDAQ":
                nm = str(row.get("name", "") or "")
                if any(k in nm for k in _skip):
                    continue
                c = _normalize_code(row.get("code"))
                if c:
                    codes.add(str(c).zfill(6))
        if len(codes) < 100:
            logger.warning("[KOSDAQ-FILTER] 코드셋 %d개(<100) 비정상 → 필터 skip", len(codes))
            return None
        logger.info("[KOSDAQ-FILTER] eod_daily_bars(%s) KOSDAQ+SKIP_KW제외 %d종목 로드", max_date, len(codes))
        return codes
    except Exception as e:
        logger.warning("[KOSDAQ-FILTER] 로드 실패(%s) → 필터 skip", e)
        return None


def _load_vol_5d_from_eod(logger: logging.Logger) -> Dict[str, float]:
    """eod_daily_bars.csv → 종목별 최근 5거래일 평균 거래량"""
    result: Dict[str, float] = {}
    if not EOD_BARS_PATH.exists() or EOD_BARS_PATH.stat().st_size == 0:
        logger.warning("[VOL5D] eod_daily_bars.csv 없음 → 당일 추정 fallback")
        return result
    vol_history: Dict[str, List[tuple]] = {}
    for row in _iter_csv_rows(EOD_BARS_PATH, logger):
        code = _normalize_code(row.get("code"))
        if code:
            code = str(code).zfill(6)
        if not code: continue
        vol  = _to_float(row.get("volume"))
        date = str(row.get("date","")).strip()
        if not vol or vol <= 0 or not date: continue
        vol_history.setdefault(code, []).append((date, vol))
    for code, records in vol_history.items():
        records.sort(key=lambda x: x[0], reverse=True)
        recent5 = records[:5]
        if recent5:
            result[code] = round(sum(v for _, v in recent5) / len(recent5), 0)
    logger.info("[VOL5D] eod_daily_bars 로드 완료: %d종목", len(result))
    return result


def _load_daily_value_5d_from_eod(logger: logging.Logger) -> Dict[str, float]:
    """[경고-2 수정] eod_daily_bars.csv → 종목별 최근 5거래일 평균 거래대금(value)
    소형주 동적 INST_ACCEL_MIN_ABS 임계값 계산에 사용.
    시총 데이터 없이 일평균 거래대금으로 소형주 여부를 대용 판단.
      - 일평균 거래대금 ≥ 50억  → 대형/중형 → 기존 5000만 하한 유지
      - 일평균 거래대금 10~50억 → 소형 → 하한을 1000만으로 완화
      - 일평균 거래대금 < 10억  → 초소형 → 하한을 500만으로 완화
    """
    result: Dict[str, float] = {}
    if not EOD_BARS_PATH.exists() or EOD_BARS_PATH.stat().st_size == 0:
        logger.warning("[VAL5D] eod_daily_bars.csv 없음 → 소형주 보정 불가")
        return result
    val_history: Dict[str, List[tuple]] = {}
    for row in _iter_csv_rows(EOD_BARS_PATH, logger):
        code = _normalize_code(row.get("code"))
        if code:
            code = str(code).zfill(6)
        if not code: continue
        val  = _to_float(row.get("value"))
        date = str(row.get("date", "")).strip()
        if not val or val <= 0 or not date: continue
        val_history.setdefault(code, []).append((date, val))
    for code, records in val_history.items():
        records.sort(key=lambda x: x[0], reverse=True)
        recent5 = records[:5]
        if recent5:
            result[code] = round(sum(v for _, v in recent5) / len(recent5), 0)
    logger.info("[VAL5D] 일평균 거래대금 로드: %d종목", len(result))
    return result


def _get_dynamic_inst_accel_min(code: str,
                                 daily_value_map: Dict[str, float],
                                 base_min: float) -> float:
    """[경고-2 수정] 종목 일평균 거래대금 기반 동적 INST_ACCEL_MIN_ABS 반환
    소형주(일 거래대금 작음)는 하한을 완화해 기관 매집 초입 신호 차단 방지.
    """
    avg_val = daily_value_map.get(code, 0.0)
    if avg_val <= 0:
        return base_min            # 데이터 없음 → 기본값 유지
    if avg_val >= 5_000_000_000:   # 50억 이상 → 대형/중형
        return base_min            # 5000만 유지
    elif avg_val >= 1_000_000_000: # 10억 이상 → 소형
        return 10_000_000          # 1000만으로 완화
    else:                          # 10억 미만 → 초소형
        return 5_000_000           # 500만으로 완화


def _calc_ofi(all_bars: List[Dict]) -> tuple:
    """Order Flow Imbalance — 매수압력 vs 매도압력 거래량 불균형
    출처: Cont, Kukanov, Stoikov (2014) "The Price Impact of Order Book Events"
    JFEC 12(1):47-88

    [CR-2] v7_14 강화: 전봉 연속성 가중(trend_weight) 추가
    - 기존: 캔들 방향만으로 buy/sell 분류 (같은 봉 안 급등↑급락↓도 buy봉 처리 오류)
    - 개선: 전봉 종가 대비 방향성 가중 1.2/0.8 → 연속 매수/매도 신호 포착 정밀화
    """
    if not all_bars: return 0.0, "NEUTRAL"
    buy_vol = sell_vol = flat_vol = 0.0
    for i, b in enumerate(all_bars):
        close = b.get("close", 0.0) or 0.0
        open_ = b.get("open", close) or close
        vol   = b.get("volume", 0.0) or 0.0
        if vol <= 0: continue

        # [CR-2] 전봉 종가 대비 연속성 가중
        prev_close = all_bars[i-1].get("close", close) if i > 0 else close
        if close > prev_close:
            trend_weight = 1.2   # 연속 상승 → 매수 신호 강화
        elif close < prev_close:
            trend_weight = 0.8   # 연속 하락 → 매도 신호 강화
        else:
            trend_weight = 1.0   # 보합 → 중립

        if close > open_:
            buy_vol  += vol * trend_weight
        elif close < open_:
            sell_vol += vol / trend_weight  # 매도봉은 가중 역방향
        else:
            flat_vol += vol

    total = buy_vol + sell_vol + flat_vol
    if total <= 0: return 0.0, "NEUTRAL"
    buy_vol  += flat_vol * 0.5
    sell_vol += flat_vol * 0.5
    net_total = buy_vol + sell_vol
    if net_total <= 0: return 0.0, "NEUTRAL"
    ofi = round((buy_vol - sell_vol) / net_total, 4)
    if ofi > 0.6:    zone = "STRONG_BUY"
    elif ofi > 0.3:  zone = "BUY"
    elif ofi < -0.3: zone = "SELL"
    else:            zone = "NEUTRAL"
    return ofi, zone


def _calc_ofi_last10(all_bars: List[Dict]) -> tuple:
    """[P5] 마감 10분 OFI — 종가매매 핵심 신호
    15:13~15:23 구간만으로 매수/매도 불균형 계산
    전체 OFI와 분리하여 마감 흐름 정밀 포착
    """
    last_bars = []
    for b in all_bars:
        hh = _hhmm(b.get("ts", "")) or 0
        if OFI_LAST10_FROM <= hh <= OFI_LAST10_TO:
            last_bars.append(b)
    return _calc_ofi(last_bars) if last_bars else (0.0, "NEUTRAL")


def _calc_atr_pct(all_bars: List[Dict]) -> float:
    """ATR% — Welles Wilder (1978) "New Concepts in Technical Trading Systems" """
    if len(all_bars) < 2: return 0.0
    tr_list: List[float] = []
    h0 = all_bars[0].get("high",0.0) or 0.0
    l0 = all_bars[0].get("low", 0.0) or 0.0
    if h0 > 0 and l0 > 0: tr_list.append(h0 - l0)
    for i in range(1, len(all_bars)):
        h  = all_bars[i].get("high",  0.0) or 0.0
        l  = all_bars[i].get("low",   0.0) or 0.0
        pc = all_bars[i-1].get("close",0.0) or 0.0
        if h <= 0 or l <= 0: continue
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not tr_list: return 0.0
    n = ATR_EMA_PERIOD
    if len(tr_list) < n:
        atr = sum(tr_list) / len(tr_list)
    else:
        atr = sum(tr_list[:n]) / n
        mult = 2.0 / (n + 1)
        for tr in tr_list[n:]:
            atr = tr * mult + atr * (1 - mult)
    close = all_bars[-1].get("close",0.0) or 0.0
    if close <= 0: return 0.0
    # [CR-1] Wilder 원공식 준수: ATR_SCALE_FACTOR=1.0 (기존 1.4 근거 없음)
    # 매도엔진(rt_sell_engine) ATR 계산과 통일 → 레짐 판단 정합성 확보
    return round((atr * ATR_SCALE_FACTOR / close) * 100.0, 4)


def _calc_vol_5d_fallback(all_bars: List[Dict]) -> float:
    """eod_daily_bars 없을 때 당일 추정 fallback"""
    mid_vols = []
    for b in all_bars:
        hh = _hhmm(b.get("ts","")) or 0
        if VOL_5D_EST_FROM <= hh <= VOL_5D_EST_TO:
            v = b.get("volume",0.0) or 0.0
            if v > 0: mid_vols.append(v)
    if not mid_vols:
        all_vols = [b.get("volume",0.0) or 0.0 for b in all_bars if b.get("volume",0)]
        if not all_vols: return 0.0
        # [MID-2] 390→375: 한국 실유효거래시간 09:00~15:20(동시호가 제외) ≈ 375분
        return round(sum(all_vols) / len(all_vols) * 375, 0)
    return round(sum(mid_vols) / len(mid_vols) * 375, 0)


def _calc_adx(all_bars: List[Dict]) -> tuple:
    """ADX — Welles Wilder (1978), 추세 강도 측정"""
    if len(all_bars) < ADX_PERIOD + 2: return 0.0, "RANGE"
    plus_dm_list: List[float] = []
    minus_dm_list: List[float] = []
    tr_list: List[float] = []
    for i in range(1, len(all_bars)):
        h  = all_bars[i].get("high",  0.0) or 0.0
        l  = all_bars[i].get("low",   0.0) or 0.0
        ph = all_bars[i-1].get("high",  0.0) or 0.0
        pl = all_bars[i-1].get("low",   0.0) or 0.0
        pc = all_bars[i-1].get("close", 0.0) or 0.0
        if h <= 0 or l <= 0: continue
        tr        = max(h - l, abs(h - pc), abs(l - pc))
        up_move   = h - ph
        down_move = pl - l
        if up_move > down_move and up_move > 0:
            plus_dm, minus_dm = up_move, 0.0
        elif down_move > up_move and down_move > 0:
            plus_dm, minus_dm = 0.0, down_move
        else:
            plus_dm, minus_dm = 0.0, 0.0
        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    n = ADX_PERIOD
    if len(tr_list) < n: return 0.0, "RANGE"
    tr14  = sum(tr_list[:n])
    pdm14 = sum(plus_dm_list[:n])
    mdm14 = sum(minus_dm_list[:n])
    dx_list: List[float] = []
    for i in range(n, len(tr_list)):
        tr14  = tr14  - (tr14  / n) + tr_list[i]
        pdm14 = pdm14 - (pdm14 / n) + plus_dm_list[i]
        mdm14 = mdm14 - (mdm14 / n) + minus_dm_list[i]
        if tr14 > 0:
            pdi = (pdm14 / tr14) * 100.0
            mdi = (mdm14 / tr14) * 100.0
            di_sum = pdi + mdi
            if di_sum > 0:
                dx_list.append(abs(pdi - mdi) / di_sum * 100.0)
    if not dx_list: return 0.0, "RANGE"
    if len(dx_list) < n:
        adx_val = sum(dx_list) / len(dx_list)
    else:
        adx_val = sum(dx_list[:n]) / n
        for dx in dx_list[n:]:
            adx_val = adx_val - (adx_val / n) + dx
    adx_val = round(adx_val, 2)
    if adx_val >= ADX_TREND_THRESHOLD:  trend = "TREND"
    elif adx_val >= ADX_WEAK_THRESHOLD: trend = "WEAK"
    else:                               trend = "RANGE"
    return adx_val, trend


def _calc_rsi(all_bars: List[Dict]) -> tuple:
    """RSI — Welles Wilder (1978)"""
    closes = [b.get("close",0.0) or 0.0 for b in all_bars if (b.get("close",0.0) or 0.0) > 0]
    n = RSI_PERIOD
    if len(closes) < n + 1: return 50.0, "COLD"
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n-1) + gains[i]) / n
        avg_loss = (avg_loss * (n-1) + losses[i]) / n
    rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    rsi = round(rsi, 2)
    if rsi >= RSI_GOOD_HIGH:  zone = "HOT"
    elif rsi >= RSI_GOOD_LOW: zone = "GOOD"
    elif rsi >= RSI_OVER_LOW: zone = "COLD"
    else:                     zone = "OVER"
    return rsi, zone


def _calc_bb(all_bars: List[Dict]) -> tuple:
    """Bollinger Bands Squeeze — John Bollinger (2001)"""
    closes = [b.get("close",0.0) or 0.0 for b in all_bars if (b.get("close",0.0) or 0.0) > 0]
    n = BB_PERIOD
    if len(closes) < n: return 0, 0.0
    recent = closes[-n:]
    ma  = sum(recent) / n
    std = (sum((c - ma)**2 for c in recent) / n) ** 0.5
    upper = ma + BB_STD_MULT * std
    lower = ma - BB_STD_MULT * std
    width = (upper - lower) / ma * 100.0 if ma > 0 else 0.0
    hist_widths: List[float] = []
    window = min(BB_SQUEEZE_WINDOW, len(closes))
    for i in range(n, window + 1):
        seg = closes[max(0, i-n):i]
        if len(seg) < n: continue
        m = sum(seg) / n
        s = (sum((c - m)**2 for c in seg) / n) ** 0.5
        w = (m + BB_STD_MULT*s - (m - BB_STD_MULT*s)) / m * 100.0 if m > 0 else 0.0
        hist_widths.append(w)
    squeeze = 0
    if hist_widths:
        hist_widths_sorted = sorted(hist_widths)
        threshold_idx = max(0, int(len(hist_widths_sorted) * BB_SQUEEZE_PCT) - 1)
        squeeze = 1 if width <= hist_widths_sorted[threshold_idx] else 0
    return squeeze, round(width, 4)


def _calc_market_flag(all_prices: Dict[str, List[Dict]],
                      logger: logging.Logger) -> str:
    for codes, name in [(KOSPI_INDEX_CODES,"KOSPI"),(KOSDAQ_INDEX_CODES,"KOSDAQ")]:
        for icode in codes:
            bars = all_prices.get(icode, [])
            if len(bars) < 5: continue
            closes = [b.get("close",0.0) or 0.0 for b in bars if (b.get("close",0.0) or 0.0) > 0]
            if not closes: continue
            n = min(MARKET_FLAG_MA_PERIOD, len(closes))
            ma200 = sum(closes[-n:]) / n
            # [CR-4] v7_14: 이진→삼진 판단 (±0.5% 완충구간 = MIXED)
            # 기존: MA200 기준 0.1%도 UP/DOWN 즉시 전환 → 횡보장 매일 전략 전환
            # 개선: ±0.5% 이내는 MIXED → 안정적 가중치 적용 (atk=0.56/stb=0.44)
            pct_vs_ma = (closes[-1] - ma200) / ma200 * 100.0
            if pct_vs_ma >= 0.5:
                flag = "UP"
            elif pct_vs_ma <= -0.5:
                flag = "DOWN"
            else:
                flag = "MIXED"
            logger.info("[MARKET_FLAG] %s(%s) %.2f MA%d=%.2f Δ%.2f%% → %s",
                        name, icode, closes[-1], n, ma200, pct_vs_ma, flag)
            return flag
    # fallback: 거래대금 상위 종목 가중 평균
    day_values: List[tuple] = []
    for code, bars in all_prices.items():
        if not bars or len(bars) < 2: continue
        total_val = sum(b.get("volume",0)*b.get("close",0) for b in bars)
        if total_val < MARKET_FALLBACK_MIN_VAL: continue
        o = bars[0].get("close",0.0) or 0.0
        c = bars[-1].get("close",0.0) or 0.0
        if o > 0: day_values.append((total_val, (c - o) / o))
    if day_values:
        day_values.sort(key=lambda x: x[0], reverse=True)
        top_vals = day_values[:MARKET_FALLBACK_TOP_N]
        total_weight = sum(v for v, _ in top_vals)
        if total_weight > 0:
            weighted_avg = sum(v * r for v, r in top_vals) / total_weight
        else:
            weighted_avg = sum(r for _, r in top_vals) / len(top_vals)
        # [CR-4] fallback도 삼진 판단 적용
        if weighted_avg >= 0.003:
            flag = "UP"
        elif weighted_avg <= -0.003:
            flag = "DOWN"
        else:
            flag = "MIXED"
        logger.info("[MARKET_FLAG] fallback 거래대금가중 상위%d종목 %.3f%% → %s",
                    len(top_vals), weighted_avg * 100, flag)
        return flag
    return "UP"


# ── [v7_18] strategy_hint 결정 (종배EOD 삭제 — 시가+추세눌림만) ──
def _determine_strategy_hint(
    adx_trend: str,
    rsi_zone: str,
    bb_squeeze: int,
    ofi_zone: str,
    ofi_last10_zone: str,
    close_position: float,
    high_break: float,
    volume_accel: float,
    market_flag: str,
) -> str:
    """
    downstream 2전략에 대한 권장 라우팅 힌트 생성
    [v7_18] 종배(EOD) 완전 삭제 → SIGA / PULLBACK / MULTI 만 반환

    ★ 이것은 "힌트"일 뿐 — 각 전략 모듈이 최종 결정 (고유영역 존중)

    SIGA     : 시가갭매매 — 변동성 압축(BB squeeze) + RSI 적정대
    PULLBACK : 추세눌림 — 추세 존재 + 가격 눌림 + 거래량 감소 후 재증가
    MULTI    : 복수 전략 적합 (기회 극대화)
    """
    hints = []

    # SIGA 적합: BB squeeze + RSI 적정대 + 거래량 가속
    if bb_squeeze == 1 and rsi_zone in ("GOOD", "COLD") and volume_accel >= HINT_SIGA_VA_MIN:
        hints.append("SIGA")

    # PULLBACK 적합: 추세 있으나 눌림 + 가격 중간대
    # [v7_18 강화] OFI 상승 조건 추가 → 기관 동행 확인 후 PULLBACK 선택
    if adx_trend in ("TREND", "WEAK") and HINT_PULLBACK_CP_LOW <= close_position <= HINT_PULLBACK_CP_HIGH:
        hints.append("PULLBACK")

    if not hints:
        # [v7_18] 기본값: EOD 제거 → 시장 상태에 따라 2전략만
        if market_flag == "DOWN":
            return "PULLBACK"   # 하락장 눌림 전략이 손실 제한 유리
        return "PULLBACK"       # [SIGA-RETIRE 2026-06-01] 구 SIGA → PULLBACK (아침 시가매수 폐기, 종가매수 대체)

    # [v7_18] 우선순위: PULLBACK 최우선 (기관 흐름 최대한 탑승)
    # 추세눌림 = 기관 동행 + 눌림 = 가장 높은 수익 기대값
    if len(hints) >= 2:
        # [v7_22 FIX-3] PULLBACK 우선순위 명확화
        # TREND 장 + PULLBACK 조건 → PULLBACK 최우선 (기관 동행 탑승)
        # SIGA 단독 → SIGA
        # 둘 다 충족 + TREND 아님 → MULTI (복수 전략 적합)
        if "PULLBACK" in hints and adx_trend == "TREND":
            return "PULLBACK"
        if "SIGA" in hints and "PULLBACK" not in hints:
            return "PULLBACK"   # [SIGA-RETIRE 2026-06-01] 구 SIGA → PULLBACK
        if "PULLBACK" in hints and "SIGA" in hints:
            return "PULLBACK"   # [SIGA-RETIRE 2026-06-01] 구 MULTI → PULLBACK (MULTI가 check_trade_limit서 SIGA로 오집계되던 문제도 해소)
        return "PULLBACK"        # [SIGA-RETIRE 2026-06-01] 기본값 구 SIGA → PULLBACK
    # [SIGA-RETIRE 2026-06-01] 단일 hint도 SIGA면 PULLBACK으로 (hints는 SIGA/PULLBACK만)
    return "PULLBACK" if hints[0] == "SIGA" else hints[0]


# ── 메인 ─────────────────────────────────────────────────────
def _compute_intent_scores(rows: List[Dict], sl_map: Dict[str, tuple],
                           inst_consec_map: Dict[str, int]) -> None:
    """[INTENT-STAGE2] 각 row에 의도점수(_intent_*) 부여. 0~1 정규화.
    theme/inst/flow/pos=절대스케일(테마대장주는 풀무관 항상 높게=의도보존), base=풀내 퍼센타일.
    hard-cut 없음(재정렬용). 모든 입력 누락=0(붕괴 방지)."""
    def _gf(r, k, d=0.0):
        v = _to_float(r.get(k, d))
        return v if v is not None else d
    _SLRMAX = float(SECTOR_LEADER_RANK_MAX) if SECTOR_LEADER_RANK_MAX else 20.0
    for r in rows:
        code = str(r.get("code", "")).zfill(6)
        # theme (절대): is_leader & rank 낮을수록 높게
        _slv = sl_map.get(code)
        theme = (max(0.0, 1.0 - (_slv[1] - 1) / _SLRMAX)
                 if (_slv and _slv[0] and _slv[1] <= SECTOR_LEADER_RANK_MAX) else 0.0)
        # inst (절대 합성): ride(0~5)/accel(>1)/net_buy(0/1)/consec(0~5일)
        ride   = min(max(_gf(r, "inst_ride_score") / 5.0, 0.0), 1.0)
        accel  = min(max(_gf(r, "inst_accel") - 1.0, 0.0), 1.0)
        netb   = 1.0 if _gf(r, "net_buy_flag") > 0 else 0.0
        consec = min(max(inst_consec_map.get(code, 0) / 5.0, 0.0), 1.0)
        inst = 0.35 * ride + 0.25 * accel + 0.20 * netb + 0.20 * consec
        # flow (절대 합성): 장중 실제 자금유입
        ofi   = min(max(_gf(r, "ofi"), 0.0), 1.0)
        ofi10 = min(max(_gf(r, "ofi_last10"), 0.0), 1.0)
        vacc  = min(max(_gf(r, "volume_accel") - 1.0, 0.0), 1.0)
        cvr   = min(max(_gf(r, "close_value_ratio") - 1.0, 0.0), 1.0)
        l5a   = min(max(_gf(r, "last5_value_accel") - 1.0, 0.0), 1.0)
        flow = 0.30 * ofi + 0.20 * ofi10 + 0.20 * vacc + 0.15 * cvr + 0.15 * l5a
        # pos (절대 밴드): vwap위 + close_position 0.35~0.75 선호 + 고점 과근접 약감점
        pvwap = _gf(r, "price_vs_vwap", 1.0)
        cp    = _gf(r, "close_position")
        pdh   = _gf(r, "price_vs_day_high", 1.0)   # close/day_high (≤1)
        vwap_ok = 1.0 if pvwap >= 1.0 else max(0.0, 1.0 - (1.0 - pvwap) / 0.03)
        if cp <= 0.20 or cp >= 0.95:
            cpband = 0.0
        elif cp < 0.55:
            cpband = (cp - 0.20) / 0.35
        else:
            cpband = max(0.0, 1.0 - (cp - 0.55) / 0.40)
        high_excess = min(max(pdh - 0.97, 0.0) / 0.03, 1.0)   # 0.97~1.0 = 고점매수 구간
        pos = max(0.0, (0.5 * vwap_ok + 0.5 * cpband) * (1.0 - 0.30 * high_excess))
        r["_intent_theme"] = round(theme, 4)
        r["_intent_inst"]  = round(inst, 4)
        r["_intent_flow"]  = round(flow, 4)
        r["_intent_pos"]   = round(pos, 4)
    # base = expected_edge 풀내 퍼센타일(0~1)
    _ee = [_gf(r, "expected_edge") for r in rows]
    _n = len(_ee)
    if _n > 1:
        _order = sorted(range(_n), key=lambda i: _ee[i])
        _base = [0.0] * _n
        for _rank, _i in enumerate(_order):
            _base[_i] = _rank / (_n - 1)
    else:
        _base = [0.5] * _n
    for _i, r in enumerate(rows):
        r["_intent_base"] = round(_base[_i], 4)
        r["_intent_score"] = round(
            INTENT_W_THEME * r["_intent_theme"] + INTENT_W_INST * r["_intent_inst"]
            + INTENT_W_FLOW * r["_intent_flow"] + INTENT_W_POS * r["_intent_pos"]
            + INTENT_W_BASE * r["_intent_base"], 6)


def _main() -> int:
    logger = _setup_logger()

    # ── params_reader 동적 로드 (매 실행마다 → evolution 즉시 반영) ──
    global MIN_VALUE_NOW, MIN_VALUE_3M, MIN_PRICE
    global W_VALUE, W_ACCEL, W_CP, W_HB, W_VWP, W_SUPPLY, W_RISK
    global BONUS_CAP, TOP_N
    global RVOL_MIN  # [v7_23 FIX] global 선언 누락 → params_reader RVOL_MIN 런타임 반영 보장
    global HEAT_STRONG_THRESHOLD, HEAT_MILD_THRESHOLD
    global HEAT_STRONG_PENALTY, HEAT_MILD_PENALTY
    global COND2_MULT, COND3_RATIO
    global ADX_TREND_THRESHOLD, ADX_BONUS_STRONG, ADX_BONUS_TREND
    global RSI_GOOD_LOW, RSI_GOOD_HIGH, RSI_OVER_LOW
    global OFI_BONUS_STRONG, OFI_BONUS_MILD, INVESTOR_BONUS
    global VAL_NORM_BASE, ATTACK_WEIGHT, STABLE_WEIGHT
    global HINT_PULLBACK_CP_LOW, HINT_PULLBACK_CP_HIGH, HINT_SIGA_VA_MIN
    global ACCEL_NORM_DIV  # [C2] UnboundLocalError 방지
    global BB_SQUEEZE_BONUS, POC_RSI_BONUS, INST_ACCEL_BONUS, INST_ACCEL_THRESHOLD
    global VOL5D_BONUS_MAX, VOL5D_BONUS_THRESHOLD
    global INST_ACCEL_MIN_ABS, STABLE_SCORE_MAX, EDGE_MIN_UP, EDGE_MIN_DOWN  # [FIX-B]

    # [C1] 기본값 상수 보존 (global 누적 곱셈 방지)
    _DEF_W_CP  = 10.0
    _DEF_W_HB  = 10.0
    _DEF_W_VWP =  8.0

    if _PR_AVAILABLE:
        try:
            _S = _get_선정()
            MIN_VALUE_NOW         = _S.get("MIN_VALUE_NOW",         MIN_VALUE_NOW)
            MIN_VALUE_3M          = _S.get("MIN_VALUE_3M",          MIN_VALUE_3M)
            MIN_PRICE             = _S.get("MIN_PRICE",             MIN_PRICE)
            W_VALUE               = _S.get("W_VALUE",               W_VALUE)
            W_ACCEL               = _S.get("W_ACCEL",               W_ACCEL)
            # [P2+B1] W_CP/W_HB/W_VWP 개별 로드 + W_PRICE 배수 fallback
            # B1 수정: 비율분배(×0.35)→배수적용. W_PRICE=10이 기본값이므로
            # W_PRICE=15면 모든 가격축 가중치가 1.5배로 균등 증폭
            _w_price_mult = 1.0
            if "W_PRICE" in _S and _S["W_PRICE"] > 0:
                _w_price_mult = _S["W_PRICE"] / 10.0  # 기준값 10 대비 배수
            if "W_CP" in _S:
                W_CP = _S["W_CP"]
            else:
                W_CP = _DEF_W_CP * _w_price_mult    # [C1] 기본값 상수 × 배수
            if "W_HB" in _S:
                W_HB = _S["W_HB"]
            else:
                W_HB = _DEF_W_HB * _w_price_mult
            if "W_VWP" in _S:
                W_VWP = _S["W_VWP"]
            else:
                W_VWP = _DEF_W_VWP * _w_price_mult
            # [C7] 가격축 가중치 상한 (과대 팽창 방지)
            W_CP  = min(W_CP,  20.0)
            W_HB  = min(W_HB,  20.0)
            W_VWP = min(W_VWP, 16.0)
            W_SUPPLY              = _S.get("W_SUPPLY",              W_SUPPLY)
            W_RISK                = _S.get("W_RISK",                W_RISK)
            BONUS_CAP             = _S.get("BONUS_CAP",             BONUS_CAP)
            TOP_N                 = int(_S.get("TOP_N",             TOP_N))
            HEAT_STRONG_THRESHOLD = _S.get("HEAT_STRONG",           HEAT_STRONG_THRESHOLD)
            HEAT_MILD_THRESHOLD   = _S.get("HEAT_MILD",             HEAT_MILD_THRESHOLD)
            HEAT_STRONG_PENALTY   = _S.get("HEAT_PENALTY_STRONG",   HEAT_STRONG_PENALTY)
            HEAT_MILD_PENALTY     = _S.get("HEAT_PENALTY_MILD",     HEAT_MILD_PENALTY)
            COND2_MULT            = _S.get("COND2_MULT",            COND2_MULT)
            COND3_RATIO           = _S.get("COND3_RATIO",           COND3_RATIO)
            ADX_TREND_THRESHOLD   = _S.get("ADX_TREND_THRESHOLD",   ADX_TREND_THRESHOLD)
            ADX_BONUS_STRONG      = _S.get("ADX_BONUS_STRONG",      ADX_BONUS_STRONG)
            ADX_BONUS_TREND       = _S.get("ADX_BONUS_TREND",       ADX_BONUS_TREND)
            RSI_GOOD_LOW          = _S.get("RSI_GOOD_LOW",          RSI_GOOD_LOW)
            RSI_GOOD_HIGH         = _S.get("RSI_GOOD_HIGH",         RSI_GOOD_HIGH)
            RSI_OVER_LOW          = _S.get("RSI_OVER_LOW",          RSI_OVER_LOW)
            OFI_BONUS_STRONG      = _S.get("OFI_BONUS_STRONG",      OFI_BONUS_STRONG)
            OFI_BONUS_MILD        = _S.get("OFI_BONUS_MILD",        OFI_BONUS_MILD)
            INVESTOR_BONUS        = _S.get("INVESTOR_BONUS",        INVESTOR_BONUS)
            # [P6] VAL_NORM_BASE 파라미터화
            VAL_NORM_BASE         = int(_S.get("VAL_NORM_BASE",     VAL_NORM_BASE))
            # [P4] 공격/안정 비율 파라미터화
            ATTACK_WEIGHT         = _S.get("ATTACK_RATIO",          ATTACK_WEIGHT)
            STABLE_WEIGHT         = _S.get("STABLE_RATIO",          STABLE_WEIGHT)
            # [P8] strategy_hint 임계값 — [v7_18] HINT_EOD_HB_MIN 삭제
            HINT_PULLBACK_CP_LOW  = _S.get("HINT_PULLBACK_CP_LOW",  HINT_PULLBACK_CP_LOW)
            HINT_PULLBACK_CP_HIGH = _S.get("HINT_PULLBACK_CP_HIGH", HINT_PULLBACK_CP_HIGH)
            HINT_SIGA_VA_MIN      = _S.get("HINT_SIGA_VA_MIN",      HINT_SIGA_VA_MIN)
            # [B8] accel_score 분모 파라미터화
            ACCEL_NORM_DIV        = _S.get("ACCEL_NORM_DIV",        ACCEL_NORM_DIV)
            # [v7_12 CB4] BB_SQUEEZE_BONUS, POC_RSI_BONUS 연동 (params.json 있으나 미사용 버그 수정)
            BB_SQUEEZE_BONUS      = _S.get("BB_SQUEEZE_BONUS",      BB_SQUEEZE_BONUS)
            POC_RSI_BONUS         = _S.get("POC_RSI_BONUS",         POC_RSI_BONUS)
            # [FIX-B] v7_13 신규 상수 evolution 연동
            INST_ACCEL_BONUS      = _S.get("INST_ACCEL_BONUS",      INST_ACCEL_BONUS)
            INST_ACCEL_THRESHOLD  = _S.get("INST_ACCEL_THRESHOLD",  INST_ACCEL_THRESHOLD)
            VOL5D_BONUS_MAX       = _S.get("VOL5D_BONUS_MAX",       VOL5D_BONUS_MAX)
            VOL5D_BONUS_THRESHOLD = _S.get("VOL5D_BONUS_THRESHOLD", VOL5D_BONUS_THRESHOLD)
            INST_ACCEL_MIN_ABS    = int(_S.get("INST_ACCEL_MIN_ABS", INST_ACCEL_MIN_ABS))
            STABLE_SCORE_MAX      = _S.get("STABLE_SCORE_MAX",      STABLE_SCORE_MAX)
            EDGE_MIN_UP           = _S.get("EDGE_MIN_UP",           EDGE_MIN_UP)
            EDGE_MIN_DOWN         = _S.get("EDGE_MIN_DOWN",         EDGE_MIN_DOWN)
            # [v7_22] 대장주 선별 강화 파라미터 연동 (params_reader v1_13)
            RVOL_MIN              = _S.get("RVOL_MIN",              RVOL_MIN)
            # [v7_22 FIX-2] 대장주 선별 강화 파라미터 params_reader 연동
            # params_reader_v1_13에 ADD-1으로 추가된 4개 파라미터
            global RS_TOP10_BONUS, RS_TOP10_PERCENTILE, SECTOR_LEADER_BONUS
            RS_TOP10_BONUS       = _S.get("RS_TOP10_BONUS",    RS_TOP10_BONUS)
            RS_TOP10_PERCENTILE  = _S.get("RS_TOP10_PERCENTILE", RS_TOP10_PERCENTILE)
            SECTOR_LEADER_BONUS  = _S.get("SECTOR_LEADER_BONUS", SECTOR_LEADER_BONUS)
            logger.debug("[PARAM] params_reader 동적 로드 완료")
        except Exception as e:
            logger.warning("[PARAM] params_reader 로드 실패 → 기본값 유지: %s", e)
    else:
        logger.warning("[PARAM] params_reader 없음 → 기본값 사용")

    # [B4] ATTACK + STABLE 합산 검증 → 자동 정규화
    _ratio_sum = ATTACK_WEIGHT + STABLE_WEIGHT
    if abs(_ratio_sum - 1.0) > 0.01:
        logger.warning("[GUARD] ATTACK(%.2f)+STABLE(%.2f)=%.2f ≠ 1.0 → 정규화",
                       ATTACK_WEIGHT, STABLE_WEIGHT, _ratio_sum)
        ATTACK_WEIGHT = ATTACK_WEIGHT / _ratio_sum
        STABLE_WEIGHT = STABLE_WEIGHT / _ratio_sum

    # [P1] MIN_VALUE 양방향 클램프 — evolution 결정 존중 + 안전 범위
    MIN_VALUE_NOW = max(MIN_VALUE_FLOOR, min(MIN_VALUE_NOW, MIN_VALUE_CEIL))
    MIN_VALUE_3M  = max(MIN_VALUE_FLOOR * 3, min(MIN_VALUE_3M, MIN_VALUE_CEIL * 3))
    W_ACCEL = min(W_ACCEL, 15.0)
    BONUS_CAP = min(BONUS_CAP, 12.0)
    ADX_BONUS_STRONG = min(ADX_BONUS_STRONG, 6.0)
    ADX_BONUS_TREND = min(ADX_BONUS_TREND, 4.0)
    OFI_BONUS_STRONG = min(OFI_BONUS_STRONG, 3.0)
    OFI_BONUS_MILD = min(OFI_BONUS_MILD, 2.0)
    INVESTOR_BONUS = min(INVESTOR_BONUS, 3.0)

    logger.info("=" * 65)
    logger.info("RT INTRADAY v7_23  START (공격%.0f%%/안정%.0f%%) [종배삭제]",
                ATTACK_WEIGHT * 100, STABLE_WEIGHT * 100)
    logger.info("[v7_23] W_VALUE=%.1f W_ACCEL=%.1f W_CP=%.1f W_HB=%.1f W_VWP=%.1f",
                W_VALUE, W_ACCEL, W_CP, W_HB, W_VWP)
    logger.info("[v7_23] W_SUPPLY=%.1f W_RISK=%.1f BONUS_CAP=%.1f TOP_N=%d",
                W_SUPPLY, W_RISK, BONUS_CAP, TOP_N)
    logger.info("[v7_23] BB_SQ_BONUS=%.1f POC_RSI_BONUS=%.1f INST_ACCEL_BONUS=%.1f THR=%.1f",
                BB_SQUEEZE_BONUS, POC_RSI_BONUS, INST_ACCEL_BONUS, INST_ACCEL_THRESHOLD)
    logger.info("[v7_23] INST_ACCEL_MIN_ABS=%d EDGE_MIN_UP=%.2f EDGE_MIN_DOWN=%.2f",
                INST_ACCEL_MIN_ABS, EDGE_MIN_UP, EDGE_MIN_DOWN)
    logger.info("[v7_23] ATR_SCALE=%.1f OFI=연속가중 market_flag=삼진(UP/MIXED/DOWN) params_reader=%s",
                ATR_SCALE_FACTOR, _PR_AVAILABLE)

    accel_cap = _env_float("RT_ACCEL_CAP", ACCEL_CAP)
    top_n     = _env_int("RT_TOP_N", TOP_N)

    if not PRICES_PATH.exists() or PRICES_PATH.stat().st_size == 0:
        logger.error("[FATAL] prices_1m.csv 없음 또는 0바이트")
        return RC_HOLD

    # [v7_24 SANITY-1] 파일 날짜 기준 freshness — 전일 이전 파일 차단 [B안]
    # age 초 기준 제거: EOD 워크플로에서 수집(15:30) → BAT 실행(저녁) 간격이
    # 항상 수 시간이므로 초 단위 임계값은 정상 케이스를 차단함
    # 교체: mtime 날짜 vs 오늘 날짜 비교 → 전일 파일만 차단, EOD 실행 허용
    from datetime import datetime as _dt
    _mtime_date = _dt.fromtimestamp(PRICES_PATH.stat().st_mtime).strftime("%Y%m%d")
    _today_date = _dt.now().strftime("%Y%m%d")
    if _mtime_date < _today_date:
        logger.error("[SANITY] prices_1m.csv not today: mtime_date=%s today=%s → RC_HOLD",
                     _mtime_date, _today_date)
        return RC_HOLD
    logger.info("[SANITY] prices_1m.csv mtime_date OK: %s", _mtime_date)

    # [v7_24 SANITY-2] latest_day 사전 스캔 — 전일 혼입 차단
    _day_counts: Dict[str, int] = {}
    for _pr in _iter_csv_rows(PRICES_PATH, logger, required_cols=["ts"]):
        _d = "".join(c for c in str(_pr.get("ts") or "").strip() if c.isdigit())[:8]
        if len(_d) == 8:
            _day_counts[_d] = _day_counts.get(_d, 0) + 1
    if not _day_counts:
        logger.error("[FATAL] prices_1m.csv ts 파싱 불가")
        return RC_HOLD
    _latest_day = max(_day_counts)
    if len(_day_counts) > 1:
        _stale_cnt = sum(v for k, v in _day_counts.items() if k != _latest_day)
        logger.warning("[SANITY] 전일 혼입 %d행 감지 → latest_day=%s 만 사용", _stale_cnt, _latest_day)
    logger.info("[SANITY] prices latest_day=%s rows=%d", _latest_day, _day_counts[_latest_day])
    if _day_counts[_latest_day] < 100:
        logger.error("[SANITY] latest_day 행수=%d < 100 → 데이터 부족 RC_HOLD", _day_counts[_latest_day])
        return RC_HOLD

    investor_net: Dict[str, float] = {}
    inst_consec_map: Dict[str, int] = {}
    inst_accel_map: Dict[str, float] = {}
    _daily_value_map: Dict[str, float] = {}  # [수정] RVOL 필터용 기본값 — INVESTOR_FILTER 미사용 시 빈 dict
    if INVESTOR_FILTER_ENABLED:
        # [경고-2 수정] 소형주 동적 임계값을 위해 일평균 거래대금 먼저 로드
        _daily_value_map = _load_daily_value_5d_from_eod(logger)
        # [P3] 1회 통합 읽기 + 소형주 동적 하한 전달
        investor_net, inst_consec_map, inst_accel_map, inst_tier_map = _load_investor_all(
            logger, daily_value_map=_daily_value_map
        )

    vol_5d_eod: Dict[str, float] = _load_vol_5d_from_eod(logger)
    use_eod_vol = bool(vol_5d_eod)
    logger.info("[VOL5D] 소스=%s", "eod_daily_bars" if use_eod_vol else "당일추정(fallback)")

    # [GAP] 전일 종가 로드 (eod_daily_bars → 가장 최근 날짜 종가)
    prev_close_map: Dict[str, float] = {}
    if EOD_BARS_PATH.exists() and EOD_BARS_PATH.stat().st_size > 0:
        _pc_hist: Dict[str, list] = {}
        for _pr in _iter_csv_rows(EOD_BARS_PATH, logger):
            _pc = _normalize_code(_pr.get("code"))
            if _pc: _pc = str(_pc).zfill(6)
            if not _pc: continue
            _pcl = _to_float(_pr.get("close"))
            _pdt = str(_pr.get("date", "")).strip()
            if not _pcl or _pcl <= 0 or not _pdt: continue
            _pc_hist.setdefault(_pc, []).append((_pdt, _pcl))
        for _pc, _precs in _pc_hist.items():
            _precs.sort(key=lambda x: x[0], reverse=True)
            if _precs: prev_close_map[_pc] = _precs[0][1]
        logger.info("[GAP] prev_close 로드: %d종목", len(prev_close_map))

    # ── 1패스: 전종목 집계 ─────────────────────────────────
    last5:            Dict[str, List[Dict]] = {}
    pv_sum:           Dict[str, float]      = {}
    vol_sum:          Dict[str, float]      = {}
    day_high:         Dict[str, float]      = {}
    day_low:          Dict[str, float]      = {}
    val_prev_window:  Dict[str, float]      = {}
    val_last_window:  Dict[str, float]      = {}
    close_hist:       Dict[str, List[float]]= {}
    prev10_val:       Dict[str, List[float]]= {}
    recent_high5:     Dict[str, List[float]]= {}
    prev_val_mean:    Dict[str, List[float]]= {}
    value_day_window: Dict[str, float]      = {}
    seen_keys: Set = set()
    all_bars_map: Dict[str, List[Dict]] = {}
    rows_seen = 0; rows_time_ok = 0

    for row in _iter_csv_rows(PRICES_PATH, logger, required_cols=["code","ts"]):
        rows_seen += 1
        code = _normalize_code(row.get("code"))
        ts   = (row.get("ts") or "").strip()
        if not code or not ts: continue
        # [v7_24 SANITY-2] latest_day_only — 전일 혼입 차단
        if "".join(c for c in ts if c.isdigit())[:8] != _latest_day:
            continue
        hh = _hhmm(ts)
        if hh is None: continue

        close_ = _to_float(row.get("close"))
        vol    = _to_float(row.get("volume"))
        high_  = _to_float(row.get("high"))
        low_   = _to_float(row.get("low"))
        open_  = _to_float(row.get("open"))

        if close_ is None or close_ <= 0: continue
        vol   = max(vol   or 0.0, 0.0)
        high_ = high_ if (high_ and high_ > 0) else close_
        low_  = low_  if (low_  and low_  > 0) else close_
        open_ = open_ if (open_ and open_ > 0) else close_
        value = close_ * vol

        all_bars_map.setdefault(code, []).append({
            "ts":     ts,
            "close":  close_,
            "open":   open_,
            "high":   high_,
            "low":    low_,
            "volume": vol,
        })

        if code not in day_high or high_ > day_high[code]: day_high[code] = high_
        if code not in day_low  or low_  < day_low[code]:  day_low[code]  = low_
        pv_sum[code]  = pv_sum.get(code,  0.0) + close_ * vol
        vol_sum[code] = vol_sum.get(code, 0.0) + vol

        if VOL_ACCEL_PREV_FROM <= hh < VOL_ACCEL_PREV_TO:
            val_prev_window[code] = val_prev_window.get(code, 0.0) + value
        if VOL_ACCEL_LAST_FROM <= hh <= VOL_ACCEL_LAST_TO:
            val_last_window[code] = val_last_window.get(code, 0.0) + value
        if PREV10_TIME_FROM <= hh <= PREV10_TIME_TO:
            prev10_val.setdefault(code, []).append(value)
            lst = prev_val_mean.setdefault(code, [])
            lst.append(value)
            if len(lst) > 10: lst[:] = lst[-10:]

        if hh < FILTER_TIME_FROM or hh > FILTER_TIME_TO: continue
        rows_time_ok += 1

        key = (code, ts)
        if key in seen_keys: continue
        seen_keys.add(key)

        close_hist.setdefault(code, []).append(close_)
        if len(close_hist[code]) > 10: close_hist[code] = close_hist[code][-10:]
        recent_high5.setdefault(code, []).append(high_)
        if len(recent_high5[code]) > 5: recent_high5[code] = recent_high5[code][-5:]
        value_day_window[code] = value_day_window.get(code, 0.0) + value

        ts_i = _ts_int(ts)
        rec = {"ts":ts,"ts_int":ts_i,"price":close_,"high":high_,
               "low":low_,"volume":vol,"value":value}
        bucket = last5.setdefault(code, [])
        if not bucket or bucket[-1]["ts_int"] <= ts_i:
            bucket.append(rec)
        else:
            inserted = False
            for i, old in enumerate(bucket):
                if ts_i < old["ts_int"]:
                    bucket.insert(i, rec); inserted = True; break
            if not inserted: bucket.append(rec)
        if len(bucket) > 5: del bucket[:len(bucket)-5]

    logger.info("[PASS1] rows_seen=%d rows_time_ok=%d codes=%d",
                rows_seen, rows_time_ok, len(last5))

    if not last5:
        logger.error("[FATAL] 시간 구간 내 데이터 없음")
        return RC_HOLD
    # [PATCH-3 OBS 2026-05-11] SANITY 직전 진단 metrics — funnel collapse 원인 즉시 식별
    try:
        _sample_codes = sorted(last5.keys())[:10] if last5 else []
        logger.info(
            "[SANITY-OBS] unique_codes=%d / threshold=%d / latest_day=%s / rows_total=%d / sample=%s",
            len(last5), PRICES_MIN_CODES, _latest_day, _day_counts[_latest_day], _sample_codes
        )
    except Exception as _e_obs:
        logger.debug("[SANITY-OBS] 로그 실패(무시): %s", _e_obs)
    # [v7_24 SANITY-3] 종목 수 최소값 체크
    # [DEGRADED24 2026-05-13] 32+ 정상 / 32~34 MILD / 24~31 LIMITED / <24 RC_HOLD (10:35 28→24 추가 하향)
    _codes_count = len(last5)
    if _codes_count >= PRICES_MIN_CODES:
        pass  # 정상 모드
    elif _codes_count >= 32:
        logger.warning("[SANITY-DEGRADED-MILD] codes=%d < %d 경계 진행 (mode=MILD)", _codes_count, PRICES_MIN_CODES)
    elif _codes_count >= 24:
        logger.warning("[SANITY-DEGRADED-LIMITED] codes=%d 강한 경계 진행 (mode=LIMITED)", _codes_count)
    else:
        logger.error("[SANITY] codes=%d < 24 → 데이터 이상 RC_HOLD", _codes_count)
        return RC_HOLD

    # ── 공통 지표 사전 계산 ───────────────────────────────
    market_flag = _calc_market_flag(all_bars_map, logger)

    atr_pct_map:    Dict[str, float] = {}
    vol_5d_avg_map: Dict[str, float] = {}
    adx_map:        Dict[str, float] = {}
    adx_trend_map:  Dict[str, str]   = {}
    rsi_map:        Dict[str, float] = {}
    rsi_zone_map:   Dict[str, str]   = {}
    bb_squeeze_map: Dict[str, int]   = {}
    bb_width_map:   Dict[str, float] = {}
    ofi_map:        Dict[str, float] = {}
    ofi_zone_map:   Dict[str, str]   = {}
    ofi_last10_map:      Dict[str, float] = {}
    ofi_last10_zone_map: Dict[str, str]   = {}
    dv_accel_map:        Dict[str, float] = {}

    for code, bars in all_bars_map.items():
        atr_pct_map[code]       = _calc_atr_pct(bars)
        vol_5d_avg_map[code]    = (vol_5d_eod.get(code) or _calc_vol_5d_fallback(bars))
        adx_val, adx_trend      = _calc_adx(bars)
        adx_map[code]           = adx_val
        adx_trend_map[code]     = adx_trend
        rsi_val, rsi_zone       = _calc_rsi(bars)
        rsi_map[code]           = rsi_val
        rsi_zone_map[code]      = rsi_zone
        bb_sq, bb_w             = _calc_bb(bars)
        bb_squeeze_map[code]    = bb_sq
        bb_width_map[code]      = bb_w
        ofi_val, ofi_zone       = _calc_ofi(bars)
        ofi_map[code]           = ofi_val
        ofi_zone_map[code]      = ofi_zone
        # [P5] 마감 10분 OFI 별도 계산
        ofi_l10, ofi_l10_zone   = _calc_ofi_last10(bars)
        ofi_last10_map[code]    = ofi_l10
        ofi_last10_zone_map[code] = ofi_l10_zone
        _dv_s = sorted(bars, key=lambda b: b.get("ts", ""))
        _dv_v = [b.get("volume", 0) * (1.0 if b.get("close", 0) >= b.get("open", 0) else -1.0) for b in _dv_s]
        _dv_r = sum(_dv_v[-10:])    if len(_dv_v) >= 10 else 0.0
        _dv_p = sum(_dv_v[-20:-10]) if len(_dv_v) >= 20 else 0.0
        dv_accel_map[code] = round(_dv_r - _dv_p, 4)

    logger.info("[INDICATORS] atr=%d adx=%d rsi=%d bb=%d ofi=%d",
                len(atr_pct_map), len(adx_map), len(rsi_map),
                len(bb_squeeze_map), len(ofi_map))

    # [v7_24 SANITY-4] 1분봉 gap 감지 (분 단위 정확 계산)
    _gap_hold_codes: List[str] = []; _gap_warn_cnt = 0
    for _gc, _gbars in list(all_bars_map.items()):
        if len(_gbars) < 2: continue
        _sorted = sorted(_gbars, key=lambda x: x["ts"])
        _max_gap = 0
        for _gi in range(1, len(_sorted)):
            _h1 = _hhmm(_sorted[_gi - 1]["ts"]) or 0
            _h2 = _hhmm(_sorted[_gi]["ts"])     or 0
            _gap_m = (_h2 // 100 - _h1 // 100) * 60 + (_h2 % 100 - _h1 % 100)
            if 0 < _gap_m > _max_gap:
                _max_gap = _gap_m
        if _max_gap >= GAP_HOLD_MIN:
            _gap_hold_codes.append(_gc)
        elif _max_gap >= GAP_WARN_MIN:
            _gap_warn_cnt += 1
    if _gap_hold_codes:
        logger.warning("[SANITY] gap≥%d분 종목 %d개 → 제외: %s",
                       GAP_HOLD_MIN, len(_gap_hold_codes), _gap_hold_codes[:10])
        for _gc in _gap_hold_codes:
            all_bars_map.pop(_gc, None); last5.pop(_gc, None)
    if _gap_warn_cnt:
        logger.warning("[SANITY] gap≥%d분 종목 %d개 (경고만)", GAP_WARN_MIN, _gap_warn_cnt)

    # [GAP] 당일 시가 맵 (코드별 첫 봉 open)
    day_open_map: Dict[str, float] = {
        c: min(bars, key=lambda b: b.get("ts", "")).get("open", 0.0)
        for c, bars in all_bars_map.items() if bars
    }

    # ── 2패스: 지표 계산 + 필터링 ────────────────────────
    out_rows: List[Dict] = []
    reject:   Dict[str, int] = {}

    def _rej(r: str) -> None:
        reject[r] = reject.get(r, 0) + 1

    # [2026-06-09 라이브 가속도 재계산] 고정 window(15:12-23, 장중 미래=0) 대신 코드별 최근5봉/직전5봉.
    #   volume_accel/last5_value_accel 죽음(83% 0) 해소. all_bars_map은 1696서 최종확정됨. 롤백 PB_VACC_LIVE_WINDOW=NO.
    if PB_VACC_LIVE_WINDOW:
        for _vc, _vbl in all_bars_map.items():
            _vbs = sorted(_vbl, key=lambda b: b.get("ts", ""))
            _vv = [b.get("close", 0.0) * b.get("volume", 0.0) for b in _vbs]
            if len(_vv) >= 10:
                val_last_window[_vc] = sum(_vv[-5:]); val_prev_window[_vc] = sum(_vv[-10:-5])
            elif len(_vv) >= 4:
                _vh = len(_vv) // 2
                val_last_window[_vc] = sum(_vv[_vh:]); val_prev_window[_vc] = sum(_vv[:_vh])

    # [PULLVOL 2026-06-11 검증채택] 눌림구간 거래량 비율 — 백테(39일 504건):
    #   폭증(>1.3) 눌림 = 승률19%/평균-1.19% 최악 / 마름(<0.7) = 29%/-0.74% 최선.
    #   정의: 당일 고점봉 이후 평균 거래대금 / 고점봉 직전 10봉 평균. 눌림(-1.5%↓) 아니면 None.
    #   소비자: rt_execution [PULLVOL-GATE]가 폭증 차단. 컬럼 없으면 fail-open(통과).
    pullvol_ratio_map: Dict[str, float] = {}
    try:
        for _pc, _pbl in all_bars_map.items():
            _pbs = sorted(_pbl, key=lambda b: b.get("ts", ""))
            if len(_pbs) < 8:
                continue
            _his = [b.get("high", 0.0) for b in _pbs]
            _hi_i = max(range(len(_his)), key=lambda i: _his[i])
            _hi_px = _his[_hi_i]
            _last_cl = _pbs[-1].get("close", 0.0)
            if _hi_px <= 0 or _last_cl <= 0 or _hi_i >= len(_pbs) - 2:
                continue
            if _last_cl / _hi_px - 1 > -0.015:
                continue
            _pull = [_b.get("close", 0.0) * _b.get("volume", 0.0) for _b in _pbs[_hi_i + 1:]]
            _pre  = [_b.get("close", 0.0) * _b.get("volume", 0.0) for _b in _pbs[max(0, _hi_i - 10):_hi_i]]
            if _pull and _pre and sum(_pre) > 0:
                _pr = (sum(_pull) / len(_pull)) / (sum(_pre) / len(_pre))
                pullvol_ratio_map[_pc] = round(_pr, 4)
    except Exception as _pve:
        logger.warning("[PULLVOL] 계산 실패(무시): %s", _pve)

    for code, bucket in last5.items():
        last  = bucket[-1]
        prev  = bucket[-2] if len(bucket) >= 2 else bucket[0]

        # [GAP] 시가 갭 계산
        _day_open  = day_open_map.get(code, 0.0)
        _prev_cl   = prev_close_map.get(code, 0.0)
        gap_pct_code = round((_day_open - _prev_cl) / _prev_cl * 100, 4) \
                       if _prev_cl > 0 and _day_open > 0 else 0.0

        price_now = _to_float(last["price"])
        if price_now is None or price_now <= 0:
            _rej("null_price"); continue
        if price_now < MIN_PRICE:
            _rej("price_too_low"); continue

        v_now  = last["value"]
        v_prev = prev["value"]
        vol_now  = last["volume"]
        vol_prev = prev["volume"]

        # [B2] 하락장 과벌 계층화: P4 동적비율 + 리스크×1.8 만 적용
        # (기존 MIN_VALUE×2 + investor×0.5 제거 → 후보 0건 방지)
        if v_now < MIN_VALUE_NOW:
            _rej("value_now_low"); continue

        value_3m = sum(x["value"] for x in bucket[-3:])
        value_5m = sum(x["value"] for x in bucket)
        if value_3m < MIN_VALUE_3M:
            _rej("value_3m_low"); continue

        # ── VWAP 기반 가격 우위 (Berkowitz 1988) ──────────
        vwap = (pv_sum[code] / vol_sum[code]
                if vol_sum.get(code,0) > 0 else price_now)
        price_vs_vwap = price_now / vwap if vwap > 0 else 1.0

        d_high = day_high.get(code, price_now)
        d_low  = day_low.get(code,  price_now)
        rng    = d_high - d_low

        close_position = (price_now - d_low) / rng if rng > 0 else 0.5
        high_break     = price_now / d_high if d_high > 0 else 1.0

        ch = close_hist.get(code, [])
        last3_ret = 0.0
        if len(ch) >= 3 and ch[-3] > 0:
            last3_ret = ((ch[-1] / ch[-3]) - 1.0) * 100.0

        high_3m = max(x["high"] for x in bucket[-3:])
        # [v7_22 BUG-FIX] upper_wick_ratio 계산 공식 수정
        # 기존: price_now / high_3m → 현재가/고가 비율 (0.95~1.0, 윗꼬리 없어도 0 안됨)
        # 수정: (high_3m - price_now) / high_3m → 실제 윗꼬리 비율
        #        윗꼬리 없으면 0, 클수록 윗꼬리가 긴 나쁜 봉
        upper_wick_ratio = (high_3m - price_now) / high_3m if high_3m > 0 else 0.0

        prev10_list     = prev10_val.get(code, [])
        prev10_mean_val = (sum(prev10_list) / len(prev10_list) if prev10_list else 0.0)
        if prev10_mean_val > 0:
            val_accel_ratio = value_3m / prev10_mean_val
            exec_cond2 = int(val_accel_ratio >= COND2_MULT)
        else:
            val_accel_ratio = 0.0
            exec_cond2 = 1  # prev10 데이터 없음 → cond2 면제

        rh5_list = recent_high5.get(code, [])
        rh5 = max(rh5_list) if rh5_list else price_now
        exec_cond3 = int(price_now >= rh5 * COND3_RATIO)
        exec_cond1 = int(price_vs_vwap >= 1.0)
        # [v7_B] exec_cond 3개 중 1개 이상 — 초기 트렌드 필터 유지하되 완화
        # 기존: 2/3 필수 → 눌림목 초입 종목 과다 탈락
        # 변경: 1/3 이상 → 최소한의 모멘텀 신호 확인 (쓰레기 제거 수준)
        if (exec_cond1 + exec_cond2 + exec_cond3) < 1:
            _rej("exec_cond_fail"); continue

        # ══════════════════════════════════════════════════════
        # [v7_20] 기관 초입 탑승 ENTRY GATE — 4개 필수 조건
        # 문서 참조: "기관 + 흐름 + 돌파 직전 3개 동시에 맞는 놈만 진입"
        # 기존: 기관 → 점수 → 선택 (뒤따라가기)
        # 개선: 기관(실시간) + 가속 + 돌파직전 → ENTRY GATE (초입 선점)
        # ══════════════════════════════════════════════════════

        # [v7_23] ENTRY GATE 4개 중 3개 이상 충족 — AND→OR3/4 전환
        # 기존: 4개 전부 AND → 1,700종목 중 1.3개만 통과 (300개 목표 불가)
        # 수정: 4개 중 3개 이상 충족 → 약 27개 → 파이프라인 정상 작동
        # 근거: 각 조건이 독립적으로 기관 신호를 검증하므로
        #       3개 충족 = 충분한 기관 확인, 4개 AND는 과도한 중복 검증
        _ofi_entry        = ofi_map.get(code, 0.0)
        _has_inst_data    = investor_net.get(code) is not None
        _inst_accel_entry = inst_accel_map.get(code, 0.0)
        _adx_trend_now    = adx_trend_map.get(code, "RANGE")
        _high_break_min   = HIGH_BREAK_ENTRY_MIN if _adx_trend_now == "TREND" else 0.85
        if not _has_inst_data:
            _high_break_min = max(_high_break_min, 0.95)
        _value_day_now    = value_day_window.get(code, 0.0)
        _inst_net_abs     = abs(investor_net.get(code, 0.0))
        _inst_ratio       = (_inst_net_abs / (_value_day_now + 1e-9)
                             if _has_inst_data and _value_day_now > 0 else None)

        # 4개 조건별 통과 여부 (기관 데이터 없으면 해당 조건 통과로 처리)
        _gate1_ofi    = (not _has_inst_data) or (_ofi_entry >= OFI_ENTRY_MIN)
        _gate2_accel  = (not _has_inst_data) or (_inst_accel_entry >= INST_ACCEL_ENTRY_MIN)
        _gate3_high   = (high_break >= _high_break_min)
        _gate4_ratio  = (_inst_ratio is None) or (_inst_ratio >= INST_RATIO_ENTRY_MIN)

        _gate_pass = sum([_gate1_ofi, _gate2_accel, _gate3_high, _gate4_ratio])
        # [v7_B2] entry_gate 소프트 점수화 — 0개만 탈락, 1~4개는 점수 차등
        # 0개: 완전 탈락 (기관 신호 전무 = 쓰레기 제거)
        # 1개: 약한 패널티 (-1.0) — prescore 지배 방지
        # 2개: 중립 (0.0) — 조건부 허용
        # 3개: 가산점 (+1.5) — 기관 확인
        # 4개: 강한 가산점 (+2.0) — 최고 품질
        if _gate_pass == 0:
            _failed = ["ofi","accel","high_break","inst_ratio"]
            _rej(f"entry_gate_0of4({','.join(_failed)})"); continue
        if _gate_pass >= 3:
            _entry_gate_bonus = 1.5 if _gate_pass == 3 else 2.0
        elif _gate_pass == 2:
            _entry_gate_bonus = 0.0
        else:  # _gate_pass == 1
            _entry_gate_bonus = -1.0

        # [v7_B2] RVOL 하드컷 제거 → rvol_score 점수 반영
        # 기존: rvol < 1.2 탈락 → 초입 종목 / 눌림 종목 차단
        # 변경: 탈락 없음, rvol 비율을 점수화해 prescore에 가산
        # rvol_score = min(rvol/2.0, 1.0) × 2.0 → 최대 +2.0
        # rvol=0 → +0.0 (5일 데이터 없음 → 중립), rvol=2.0 → +2.0 (최대)
        _avg_val_5d = _daily_value_map.get(code, 0.0)
        if _avg_val_5d > 0:
            _rvol = _value_day_now / _avg_val_5d
            _rvol_score = min(_rvol / 2.0, 1.0) * 2.0
        else:
            _rvol       = 0.0
            _rvol_score = 0.0  # 데이터 없음 → 중립

        volume_pressure = (vol_now / vol_prev) if vol_prev > 0 else 0.0
        # [T5] volume_pressure>5.0 하드컷 제거 → soft_volume_penalty 신설
        # 기존: >5.0 즉시 reject → 순간 거래량 급증 종목도 탈락 (초입 신호 차단)
        # 변경: prescore에서 차감만 (>6.0→3.0, >5.0→1.5, 이하→0)
        if volume_pressure > 6.0:
            soft_volume_penalty = SOFT_VOL_PENALTY_HIGH
        elif volume_pressure > 5.0:
            soft_volume_penalty = SOFT_VOL_PENALTY_MID
        else:
            soft_volume_penalty = 0.0

        # [FIX-H3] 개별 종목의 수급 데이터 존재 여부 체크
        net = investor_net.get(code, None)
        if net is None:
            net_buy_flag = 0
        else:
            net_buy_flag = 1 if net > 0 else 0

        price_vs_day_high = high_break

        accel: Any = ""
        v_avg3 = value_3m / 3.0 if value_3m > 0 else None
        if v_avg3 and v_avg3 > 0:
            a = math.log(v_now / v_avg3)
            if math.isfinite(a) and a > 0:
                accel = min(a, accel_cap)

        price_prev_ = _to_float(prev["price"])
        price_break: Any = ""
        if price_prev_ and price_prev_ > 0:
            price_break = price_now / price_prev_

        highs3 = [x["high"] for x in bucket[-3:]]
        lows3  = [x["low"]  for x in bucket[-3:]]
        close_pos_3m: Any = ""
        if highs3 and lows3:
            h3 = max(highs3); l3 = min(lows3); r3 = h3 - l3
            if r3 > 0: close_pos_3m = (price_now - l3) / r3

        v_last_w = val_last_window.get(code, 0.0)
        v_prev_w = val_prev_window.get(code, 0.0)
        volume_accel      = (v_last_w / v_prev_w if v_prev_w >= MIN_WINDOW_VALUE else 0.0)
        last5_value_accel = (v_last_w / v_prev_w if v_prev_w > 0 else 0.0)

        val_window = value_day_window.get(code, 0.0)
        close_value_ratio = v_now / val_window if val_window > 0 else 0.0

        prev_avg_list = prev_val_mean.get(code, [])
        prev_avg = (sum(prev_avg_list) / len(prev_avg_list) if prev_avg_list else 0.0)
        if prev_avg > 0 and len(bucket) >= 2:
            hot = sum(1 for x in bucket if x["value"] > prev_avg)
            trade_density_accel = hot / len(bucket)
        else:
            trade_density_accel = 0.0

        # ══════════════════════════════════════════════════════
        #  [v7_11] prescore = attack × 0.70 + stable × 0.30
        #  공격 70%: "지금 돈이 몰리는가?"
        #  안정 30%: "내일 안 빠지는가?"
        # ══════════════════════════════════════════════════════

        # ── 공격축 (attack_score) ─────────────────────────
        # [P6] VAL_NORM_BASE 파라미터화 (기존 1억 하드코딩 제거)
        val_score   = min(v_now / VAL_NORM_BASE, 1.0) * W_VALUE
        # [B8] ACCEL_NORM_DIV 파라미터화 (기존 8.0 하드코딩 제거)
        accel_score = (min(val_accel_ratio / ACCEL_NORM_DIV, 1.0) * W_ACCEL
                       if prev10_mean_val > 0 else 0.0)
        axis_value  = val_score + accel_score

        _cp  = min(max(close_position, 0.0), 1.0)
        _hb  = min(max(high_break,     0.0), 1.05)
        _vwp = min(max(price_vs_vwap - 1.0, 0.0), 0.05) / 0.05
        axis_price  = _cp * W_CP + _hb * W_HB + _vwp * W_VWP

        # ── 공격 보너스 (OFI + ADX + inst_accel + vol5d) ─────
        code_ofi = ofi_map.get(code, 0.0)
        code_adx = adx_map.get(code, 0.0)

        ofi_bonus = (OFI_BONUS_STRONG if code_ofi > 0.6
                     else OFI_BONUS_MILD if code_ofi > 0.3 else 0.0)
        adx_bonus = (ADX_BONUS_STRONG if code_adx >= 35
                     else ADX_BONUS_TREND if code_adx >= ADX_TREND_THRESHOLD else 0.0)

        # [v7_13 T4] inst_accel_bonus 3단계화
        # >=2.0: 100% / >=1.5: 75% / >=1.1: 35% / else: 0
        # 근거: 기관 매집 가속도 강도에 비례해 보너스 차등 → 신호 민감도 향상
        code_inst_accel = inst_accel_map.get(code, 0.0)
        if code_inst_accel >= 2.0:
            inst_accel_bonus = INST_ACCEL_BONUS * 1.00
        elif code_inst_accel >= INST_ACCEL_THRESHOLD:   # >=1.5
            inst_accel_bonus = INST_ACCEL_BONUS * 0.75
        elif code_inst_accel >= 1.1:
            inst_accel_bonus = INST_ACCEL_BONUS * 0.35
        else:
            inst_accel_bonus = 0.0

        # [v7_12 P-1] vol_5d_rel: 5일 평균 대비 현재 거래량 (진짜 "돈 몰림" 신호)
        vol_5d_base = vol_5d_avg_map.get(code, 0.0)
        if vol_5d_base > 0 and vol_now > 0:
            vol_5d_rel = vol_now / vol_5d_base
            # 5일 평균 대비 VOL5D_BONUS_THRESHOLD배 이상이면 보너스 (최대 VOL5D_BONUS_MAX)
            vol5d_bonus = min(max(vol_5d_rel - VOL5D_BONUS_THRESHOLD, 0.0) * 1.5,
                              VOL5D_BONUS_MAX)
        else:
            vol5d_bonus = 0.0

        bonus_attack = min(ofi_bonus + adx_bonus + inst_accel_bonus + vol5d_bonus, BONUS_CAP)

        # 공격축 합산 + 가드레일
        axis_value_clamped = min(axis_value, AXIS_VALUE_MAX)
        axis_price_clamped = min(axis_price, AXIS_PRICE_MAX)
        attack_score = axis_value_clamped + axis_price_clamped + bonus_attack

        # ── 안정축 (stable_score) ─────────────────────────
        investor_score = W_SUPPLY if net_buy_flag == 1 else 0.0
        vol_score_val  = min(max(volume_pressure - 1.0, 0.0) / 2.0, 1.0) * W_SUPPLY
        axis_supply    = min(investor_score + vol_score_val, AXIS_SUPPLY_MAX)

        # 리스크 페널티
        if last3_ret >= HEAT_STRONG_THRESHOLD:
            heat_penalty = HEAT_STRONG_PENALTY
        elif last3_ret >= HEAT_MILD_THRESHOLD:
            heat_penalty = HEAT_MILD_PENALTY
        else:
            heat_penalty = 0.0
        # [v7_12 CB-2] wick_penalty 배율 50→20 (3분 고가 기준 현실화)
        # 기존 ×50은 윗꼬리 10%만 있어도 페널티 5 → axis_risk -12 → CB-1 탈락
        # 변경: ×20 → 윗꼬리 10% → 페널티 2 → axis_risk -4.8 → 정상 통과
        # [v7_22 BUG-FIX] 반전 버그 수정
        # 기존: (1.0 - upper_wick_ratio) × 20 → 윗꼬리 없을수록(좋은 봉) 페널티 최대 (반전!)
        # 수정: upper_wick_ratio × 20 → 윗꼬리 많을수록(나쁜 봉) 페널티 최대 (정상)
        wick_penalty = max(0.0, upper_wick_ratio * 20.0)
        # [CR-4] MIXED 리스크 배율 추가: DOWN=1.4, MIXED=1.2, UP=1.0
        # 횡보장은 하락장보다 리스크 낮지만 상승장보다는 높음 → 중간값 적용
        _risk_mlt = 1.4 if market_flag == "DOWN" else (1.2 if market_flag == "MIXED" else 1.0)
        axis_risk = -(wick_penalty + heat_penalty) * (W_RISK * 2.0) * _risk_mlt
        axis_risk = max(axis_risk, AXIS_RISK_FLOOR)

        # [v7_11] 기관 라이드 보너스 (안정축)
        code_inst_consec = inst_consec_map.get(code, 0)
        # [v7_20 수정③] inst_ride 강화 — inst_accel + inst_consec 결합
        # 기존: consec 단독 기반
        # 변경: accel 60% + consec 40% 결합 → 지속성 + 초입 모두 반영
        _inst_accel_now = inst_accel_map.get(code, 0.0)
        # [MULTI-TIER 2026-06-02] 사용자 설계(20일 대장주 + 5/3/1) 점수 우선 + 기존(accel/consec) 결합 — 둘 중 강한 신호.
        _inst_tier_now  = inst_tier_map.get(code, 0.0)
        _ride_combined  = min(1.0, max(_inst_tier_now, (_inst_accel_now * 0.6 + code_inst_consec * 0.4) / 3.0))
        inst_ride = _ride_combined * INST_RIDE_MAX * float(os.environ.get("INST_RIDE_WEIGHT", "0.4"))

        # 안정 보너스 (investor) — 기관 과의존 방지 × 0.3
        investor_bonus = (INVESTOR_BONUS if net_buy_flag == 1 else 0.0) * 0.3

        # [v7_12 CB-4] BB_SQUEEZE_BONUS + POC_RSI_BONUS scoring 반영
        # params.json 및 params_reader에 있으나 v7_11에서 완전 누락된 버그 수정
        code_bb_sq_now    = bb_squeeze_map.get(code, 0)
        code_rsi_zone_now = rsi_zone_map.get(code, "COLD")
        bb_sq_bonus  = BB_SQUEEZE_BONUS * 0.5 if code_bb_sq_now == 1 else 0.0
        poc_rsi_bonus = POC_RSI_BONUS * 0.4 if code_rsi_zone_now == "GOOD" else 0.0

        stable_score = (axis_supply + axis_risk + inst_ride +
                        investor_bonus + bb_sq_bonus + poc_rsi_bonus)
        # [FIX-A] stable_score 총액 상한 (bb_sq+poc_rsi 추가로 인한 과대 계산 방지)
        stable_score = min(stable_score, STABLE_SCORE_MAX)

        # ── prescore 최종 합산 (공격/안정 동적 비율) ────────
        # [T1] DOWN 가중치 0.50/0.50→0.42/0.58 (하락장 안정 우선 강화)
        # [CR-4] MIXED 가중치 추가: 0.56/0.44 (UP/DOWN 중간, 횡보장 전환 방지)
        # 근거: 횡보장에서는 공격도 안정도 과도하게 치우치면 오신호 발생
        if market_flag == "DOWN":
            atk_w, stb_w = 0.42, 0.58
        elif market_flag == "MIXED":
            atk_w, stb_w = 0.56, 0.44   # [CR-4] MIXED 전용 가중치
        else:  # UP
            atk_w, stb_w = ATTACK_WEIGHT, STABLE_WEIGHT

        # [v7_12 CB-1] axis_risk<-7 하드컷 제거 → soft_risk_penalty로 교체
        # 기존: axis_risk<-7이면 무조건 continue → 기관 매수 중인 종목도 탈락
        # 변경: prescore에서 비례 감점만 적용 (블록 없음)
        # 이유: AXIS_RISK_FLOOR=-8 이미 클램프 → -8~-7 구간 탈락은 불필요한 손실
        soft_risk_penalty = max(0.0, (-axis_risk - 5.0) * 0.5)  # axis_risk<-5 구간에서만 추가 감점

        prescore = (attack_score * atk_w + stable_score * stb_w
                    - soft_risk_penalty - soft_volume_penalty
                    + _entry_gate_bonus   # [v7_B2] gate 품질 (-1~+2)
                    + _rvol_score)        # [v7_B2] RVOL 랭킹 반영 (0~+2)

        # [SECTOR_LEADER A안 2026-06-04] 테마 대장주(네이버 강테마 rank<=MAX & is_leader) prescore 보너스.
        #   A방식: prescore에 가산 → prescore_weighted/160컷/rt_risk Top1까지 일관 전파.
        #   rank1=최대, rank20≈0 가중 → 강한 테마일수록 큰 보너스. prescore 낮으면 보너스 받아도 1등 안 됨(안전).
        if SECTOR_LEADER_ENABLE:
            _sl = _get_sector_leaders().get(code)
            if _sl and _sl[0] and _sl[1] <= SECTOR_LEADER_RANK_MAX:
                _sl_w = max(0.0, 1.0 - (_sl[1] - 1) / float(SECTOR_LEADER_RANK_MAX))
                _sl_boost = round(SECTOR_LEADER_MAX_PTS * _sl_w, 3)
                if _sl_boost > 0:
                    prescore += _sl_boost
                    logger.debug("[SECTOR_LEADER] code=%s theme_rank=%d +%.2f → prescore=%.2f",
                                 code, _sl[1], _sl_boost, prescore)

        # ══════════════════════════════════════════════════════
        #  [최종] expected_edge — 장세별 구조 분리 (v7_12 P-2, P-3 반영)
        #  UP:   돌파 + 거래량 중심 (공격적)
        #  DOWN: 방어 + 마감흐름 중심 (보수적)
        # ══════════════════════════════════════════════════════
        # volume_accel 노이즈 제한 (가짜 급등 방지)
        # [v7_18 M-2] 캡 2.5→4.0: 초입 거래 폭발 종목 보호
        # 근거: 기관 급매집 첫 1분봉은 평소 대비 5~8배 거래 발생 (AQR 모멘텀 이론)
        volume_accel_capped = min(volume_accel, 4.0)

        if market_flag == "DOWN":
            # [PATCH-2] DOWN edge 재배분: ofi_l10 0.30→0.40(핵심강화)
            # 근거: 하락장 시가갭 수익률 핵심 = 마감 OFI 방향성 (전일 포지션 형성)
            ofi_l10_norm = (ofi_last10_map.get(code, 0.0) + 1.0) / 2.0
            upper_wick_score = max(0.0, min(upper_wick_ratio, 1.0))
            edge = (
                close_position   * 0.30 +   # ← 조정 (0.35→0.30)
                ofi_l10_norm     * 0.40 +   # ← 핵심 강화 (0.30→0.40)
                upper_wick_score * 0.20 +   # ← 조정 (0.25→0.20)
                min(volume_accel_capped / 2.5, 1.0) * 0.10
            )
        elif market_flag == "MIXED":
            # [PATCH-2] MIXED edge 재배분: hb_norm 0.25→0.30, ofi_l10 0.22→0.25
            # 근거: 횡보장 = 고점 돌파와 마감 OFI 균등 강조
            ofi_l10_norm = (ofi_last10_map.get(code, 0.0) + 1.0) / 2.0
            hb_norm = min(max((high_break - 0.90) / 0.10, 0.0), 1.0)
            va_norm = min(volume_accel_capped / 2.5, 1.0)
            edge = (
                close_position * 0.30 +
                hb_norm        * 0.30 +   # ← 강화 (0.25→0.30)
                ofi_l10_norm   * 0.25 +   # ← 강화 (0.22→0.25)
                va_norm        * 0.10 +   # ← 조정 (0.12→0.10)
                max(ofi_map.get(code, 0.0), 0.0) * 0.05  # ← 조정 (0.08→0.05)
            )
        else:  # UP
            # [PATCH-2] UP edge 재배분: hb_norm 0.35→0.40(핵심강화), va 0.15→0.20
            # 근거: 몰빵 구조 최적 = 돌파 종목 집중 → hb_norm이 수익률 직결
            hb_norm = min(max((high_break - 0.90) / 0.10, 0.0), 1.0)
            va_norm = min(volume_accel_capped / 2.5, 1.0)
            edge = (
                close_position * 0.25 +
                hb_norm        * 0.40 +   # ← 핵심 강화 (0.35→0.40)
                va_norm        * 0.20 +   # ← 강화 (0.15→0.20)
                max(ofi_map.get(code, 0.0), 0.0) * 0.15  # ← 조정 (0.20→0.15)
            )

        # [PATCH-3] risk_adj 완화 (절충값: 원안 0.75/20보다 보수적)
        # floor 0.65→0.70 : 급등 초입 최저 보장선 상향
        # ATR 분모 15→18  : 변동성 감쇠 완화 (급등주 살리기)
        # heat 0.03→0.02  : 과열 감쇠 완화 (기관 동행 과열 용인)
        # [v7_18 M-3] ride_score 기반 동적 floor:
        #   기관 동행 확인(inst_consec≥3) → floor=0.80 (패널티 완화)
        #   미확인 → floor=0.70 (기존)
        #   근거: 기관이 받쳐주는 종목은 ATR 높아도 실손 위험↓ (Cont et al. 2014)
        atr = atr_pct_map.get(code, 0.0)
        heat_bad = (1.0 if last3_ret >= HEAT_STRONG_THRESHOLD
                    else 0.5 if last3_ret >= HEAT_MILD_THRESHOLD
                    else 0.0)
        _inst_consec_now = inst_consec_map.get(code, 0)
        _risk_floor = 0.80 if _inst_consec_now >= INST_STRONG_DAYS else 0.70
        risk_adj = max(_risk_floor, 1.0 - (atr / 18.0) - (heat_bad * 0.02))

        # expected_edge는 루프 뒤에서 prescore 분포 정규화 후 계산
        # 여기서는 edge, risk_adj를 내부 필드로 저장

        # ── strategy_hint 결정 (이미 위에서 계산한 변수 재사용) ──
        code_adx_trend = adx_trend_map.get(code, "RANGE")
        # code_rsi_zone_now, code_bb_sq_now은 stable_score에서 이미 계산됨
        code_ofi_zone  = ofi_zone_map.get(code, "NEUTRAL")

        strategy_hint = _determine_strategy_hint(
            adx_trend=code_adx_trend,
            rsi_zone=code_rsi_zone_now,
            bb_squeeze=code_bb_sq_now,
            ofi_zone=code_ofi_zone,
            ofi_last10_zone=ofi_last10_zone_map.get(code, "NEUTRAL"),
            close_position=close_position,
            high_break=high_break,
            volume_accel=volume_accel,
            market_flag=market_flag,
        )

        out_rows.append({
            "ts":                   last["ts"],
            "code":                 code,
            # [W55 PATCH 2026-05-13] 절대 가격 컬럼 추가 — rt_execution price=0 RC_HOLD 결함 해결
            #   rt_execution L2414 `best["row"].get("price_now", 0)` 사용
            #   기존: rt_intraday에 가격 절대값 부재 → price=0 → RC_HOLD 영구 차단
            #   수정: 1분봉 close 값을 price_now 컬럼으로 노출 (정수, 원 단위)
            "price_now":            int(price_now) if price_now > 0 else 0,
            "value_now":            round(v_now,    0),
            "value_prev":           round(v_prev,   0),
            "value_3m":             round(value_3m, 0),
            "value_5m":             round(value_5m, 0),
            "value_day":            round(value_day_window.get(code,0.0), 0),
            "price_vs_vwap":        round(price_vs_vwap,     6),
            "price_vs_day_high":    round(price_vs_day_high, 6),
            "accel_real":           round(accel, 6) if isinstance(accel, float) else None,
            "volume_pressure":      round(volume_pressure, 6),
            "price_break_strength": round(price_break, 6) if isinstance(price_break, float) else None,
            "close_pos_3m":         round(close_pos_3m, 6) if isinstance(close_pos_3m, float) else None,
            "close_position":       round(close_position,   6),
            "high_break":           round(high_break,       6),
            "last3_ret":            round(last3_ret,        6),
            "upper_wick_ratio":     round(upper_wick_ratio, 6),
            "volume_accel":         round(volume_accel,       6),
            "close_value_ratio":    round(close_value_ratio,  6),
            "last5_value_accel":    round(last5_value_accel,  6),
            "pb_pullvol_ratio":     pullvol_ratio_map.get(code),  # [PULLVOL] 눌림 아님/계산불가=None
            "net_buy_flag":         net_buy_flag,
            "exec_cond1":           exec_cond1,
            "exec_cond2":           exec_cond2,
            "exec_cond3":           exec_cond3,
            "trade_density_accel":  round(trade_density_accel, 6),
            "market_flag":          market_flag,
            "atr_pct":              atr_pct_map.get(code, 0.0),
            "vol_5d_avg":           vol_5d_avg_map.get(code, 0.0),
            "adx":                  code_adx,
            "adx_trend":            code_adx_trend,
            "rsi":                  rsi_map.get(code, 50.0),
            "rsi_zone":             code_rsi_zone_now,
            "bb_squeeze":           code_bb_sq_now,
            "bb_width":             bb_width_map.get(code, 0.0),
            "ofi":                  code_ofi,
            "ofi_zone":             code_ofi_zone,
            "confidence_margin":    0.0,
            # ── v7_11 확장 컬럼 ──
            "attack_score":         round(attack_score, 2),
            "stable_score":         round(stable_score, 2),
            "prescore_weighted":    round(prescore, 2),
            "strategy_hint":        strategy_hint,
            "inst_ride_score":      round(inst_ride, 2),
            "ofi_last10":           ofi_last10_map.get(code, 0.0),
            "ofi_last10_zone":      ofi_last10_zone_map.get(code, "NEUTRAL"),
            "inst_accel":           inst_accel_map.get(code, 0.0),
            "expected_edge":        0.0,   # 루프 뒤에서 분포 정규화 후 계산
            # ── v7_13 확장 컬럼 (T9) ──
            "soft_risk_penalty":    round(soft_risk_penalty, 4),
            "soft_volume_penalty":  round(soft_volume_penalty, 4),
            "wick_penalty":         round(wick_penalty, 4),
            "heat_penalty":         round(heat_penalty, 4),
            "edge_confidence":      0.0,   # T10: 루프 뒤에서 top1만 기록
            "gap_pct":              gap_pct_code,  # [GAP] 당일 시가 갭 (%)
            "dv_accel":             dv_accel_map.get(code, 0.0),
            "_prescore":            prescore,
            "_edge":                edge,
            "_risk_adj":            risk_adj,
            "_inst_ride":           inst_ride,
            "_expected_edge":       0.0,
        })

    if not out_rows:
        logger.warning("[EMPTY] 후보 없음 reject=%s", reject)
        # [안정4] 통과율 자동 감시
        total_codes = len(last5)
        logger.warning("[GUARD] 통과율 0%% (총 %d종목, reject=%s)", total_codes, reject)
        _atomic_write_csv(RT_OUT_PATH, OUTPUT_HEADER, [])
        return RC_OK

    # ── [v7_17] EV 혼합형 expected_edge ────────────────────────────────
    # 기존(v7_15): 단순 가중합 랭킹 점수
    # 변경(v7_17): 기존 60% + EV성분 25% + breakout 15% 혼합형
    #
    # 설계 근거:
    #   순수EV(v7_16)는 20.5% 통과 → 진입 공백 위험
    #   혼합형(v7_17)은 91.8% 통과 → 1일 1종목 안정 유지
    #   2전략(시가/눌림) 모두 선정 가능
    #
    # 변수 주의: out_rows 루프에서 ofi_map/va_norm 등 직접 접근 불가
    #   → r.get() 방식으로 딕셔너리에서 추출 (BUG 4개 사전 수정)
    if out_rows:
        all_ps = sorted([r["_prescore"] for r in out_rows])
        n = len(all_ps)
        p10 = all_ps[int(n * 0.1)]
        p90 = all_ps[int(n * 0.9)] if n > 1 else p10 + 1
        ps_range = max(p90 - p10, 1e-6)

        inst_norm_max = INST_RIDE_MAX * 0.3  # = 1.5

        for r in out_rows:
            ps_norm   = max(0.0, min((r["_prescore"] - p10) / ps_range, 1.0))
            inst_norm = max(0.0, min(r["_inst_ride"] / inst_norm_max, 1.0))

            # ── breakout_score (v7_15 방식 유지) ────────────────────
            hb_raw         = r.get("high_break",     0.0) or 0.0
            breakout_score = min(max((hb_raw - 0.97) / 0.03, 0.0), 1.0)

            # ── [수정지시 1] old_edge_score: 기존 v7_15 랭킹 계산 ──
            old_edge_score = (
                r["_edge"]       * 0.50 +
                ps_norm          * 0.25 +
                inst_norm        * 0.05 +
                breakout_score   * 0.20
            )

            # ── [수정지시 2] EV 보조 변수 (r.get()으로 scope 안전) ──
            # BUG수정: 명세서의 ofi_map.get(code)/va_norm/ofi_l10_norm →
            #          out_rows 딕셔너리에서 직접 추출
            hb_norm_v   = min(max((hb_raw - 0.90) / 0.10, 0.0), 1.0)
            close_pos_v = r.get("close_position", 0.5) or 0.5
            va_norm_v   = min((r.get("volume_accel", 0.0) or 0.0) / 2.5, 1.0)
            ofi_l10_v   = r.get("ofi_last10", 0.0) or 0.0
            ofi_l10_n   = (ofi_l10_v + 1.0) / 2.0          # -1~+1 → 0~1
            ofi_v       = r.get("ofi", 0.0) or 0.0
            ofi_safe    = max(ofi_v, 0.0)                   # 음수 차단

            prob_up = (
                0.35 * breakout_score +
                0.25 * hb_norm_v      +
                0.25 * close_pos_v    +
                0.15 * ps_norm
            )
            prob_up = max(0.0, min(prob_up, 1.0))

            strength = (
                0.45 * va_norm_v  +
                0.35 * ofi_l10_n  +
                0.20 * ofi_safe
            )
            strength = max(0.0, strength)

            # ── [수정지시 3] ev_component ──────────────────────────
            ev_component = prob_up * strength

            # ── [수정지시 4] ★핵심: 혼합형 expected_edge ────────────
            # [v7_18] breakout 가중치 0.15→0.20, old_edge 0.60→0.55
            # 근거: Jegadeesh & Titman(1993) — 고점 돌파 직전 모멘텀이
            #       수익률 상위 80% 집중. 몰빵 구조에서 breakout 강화 필수
            # [v7_20 수정①] expected_edge 가중치 재배분
            # 기존: old_edge 0.55 / ev 0.25 / breakout 0.20
            # 변경: old_edge 0.40 / ev 0.35 / breakout 0.25
            # 효과: EV 중심 구조 → 수익률 직결 / 돌파 직전 집중도 강화
            ee = round(
                (
                    0.40 * old_edge_score +
                    0.35 * ev_component   +
                    0.25 * breakout_score
                ) * r["_risk_adj"],
                4
            )

            # ── [수정지시 5] 안정성 보정 ──────────────────────────
            ee = max(ee, 0.0)
            if not math.isfinite(ee):
                ee = 0.0

            # RS 상위 10% 보너스 (v7_21 대장주 선별 강화 연결 복구)
            if ps_norm >= RS_TOP10_PERCENTILE:
                ee = round(ee + RS_TOP10_BONUS, 4)

            r["expected_edge"]  = ee
            r["_expected_edge"] = ee

            # ── [수정지시 6] 디버깅 로그 (DEBUG 레벨) ─────────────
            logger.debug(
                "[EV-MIX] code=%s prob=%.3f strength=%.3f ev=%.3f "
                "old=%.3f brk=%.3f risk=%.3f final=%.3f",
                r.get("code", ""),
                prob_up, strength, ev_component,
                old_edge_score, breakout_score,
                r["_risk_adj"], ee,
            )

    # ── [T12] EV 하단 soft 약화 (점수 조정만 — 종목 제거 없음) ──
    # [v7_23] FEATURE_ENGINE_ONLY: edge_floor 컷 제거, TOP_N 제한 제거
    # 모든 종목을 downstream으로 전달 (필터는 exec engine 고유 영역)
    EE_SOFT_FLOOR = 0.20
    for r in out_rows:
        if r["_expected_edge"] < EE_SOFT_FLOOR:
            r["_expected_edge"] *= 0.5
            r["expected_edge"]  = r["_expected_edge"]

    logger.info("[REJECT] 탈락분포: %s", sorted(reject.items(), key=lambda x:-x[1]))
    logger.info("[T12] edge_floor 컷 비활성화: 전종목(%d) 통과 [v7_23]", len(out_rows))

    # [KOSDAQ-FILTER 2026-06-01] expected_edge 정렬·TOP_N 컷 전에 KOSDAQ로 제한.
    #   KOSPI 대형주·ETF가 OFI/유동성으로 상위 점령 → rt 160 슬롯·top20 보호 낭비 방지.
    #   스코어보드 필터와 동일 소스(eod_daily_bars KOSDAQ+SKIP_KW). fail-open(코드셋 None이면 skip).
    _kosdaq_set = _load_kosdaq_codes(logger)
    if _kosdaq_set:
        _kb = len(out_rows)
        out_rows = [r for r in out_rows if str(r.get("code", "")).zfill(6) in _kosdaq_set]
        logger.info("[KOSDAQ-FILTER] rt 후보 %d→%d종목 (KOSPI/ETF 제외)", _kb, len(out_rows))

    if not out_rows:
        logger.warning("[T12] 후보 없음 → 빈 출력")
        _atomic_write_csv(RT_OUT_PATH, OUTPUT_HEADER, [])
        return RC_OK

    # ── 정렬: expected_edge 우선 + prescore 보조 ────────────────
    out_rows.sort(key=lambda x: (x["_expected_edge"], x["_prescore"]), reverse=True)
    _pre_cut = list(out_rows)   # [THEME-INJECT] 컷 전 전체(KOSDAQ필터+정렬됨) — 잘린 대장주 복원용
    # [v7_B] 2단 압축: 1단 300 → 2단 160 (env: TOP_N_1ST/TOP_N_2ND 튜닝)
    _top_n_1st = int(os.environ.get("TOP_N_1ST", "300"))
    _top_n_2nd = int(os.environ.get("TOP_N_2ND", "160"))   # [되돌림 2026-06-07] 300→160 복귀. 사용자 의도=점진적 깔때기(600→1단300→2단160), 2단 재경쟁 단계가 핵심(없애면 안됨). 1단(TOP_N_1ST 300)=RT가 받는 후보, 2단(160)=RT 재경쟁 최종→스코어보드. 테마대장주는 INJECT/RESCUE로 단계마다 보호되어 버려지지 않음. 1단 넓히려면 TOP_N_1ST=400.
    _before_top = len(out_rows)
    # 1단: expected_edge 기준 상위 300 (넓게 살림 — 좋은 후보 일찍 안 버림)
    if len(out_rows) > _top_n_1st:
        out_rows = out_rows[:_top_n_1st]
    logger.info("[RT-STAGE1] input=%d stage1=%d sort=expected_edge", _before_top, len(out_rows))

    # 2단: [INTENT-STAGE2] intent_score(테마/기관/수급/눌림위치/기본품질) 재경쟁 (W1/W2 fix)
    #   재정렬(soft)만 — hard-cut 없음. OFF면 기존 expected_edge 순서 그대로 160컷(회귀).
    if MAKE_RT_INTENT_STAGE2_ENABLE and len(out_rows) > 1:
        try:
            _compute_intent_scores(out_rows, _get_sector_leaders(), inst_consec_map)
            out_rows.sort(
                key=lambda x: (x.get("_intent_score", 0.0),
                               x.get("_expected_edge", 0.0),
                               _to_float(x.get("prescore_weighted")) or 0.0),
                reverse=True)
            logger.info("[RT-STAGE2] stage1=%d → intent_score 재정렬 "
                        "(w: theme%.2f inst%.2f flow%.2f pos%.2f base%.2f)",
                        len(out_rows), INTENT_W_THEME, INTENT_W_INST,
                        INTENT_W_FLOW, INTENT_W_POS, INTENT_W_BASE)
            for _r in out_rows[:10]:
                logger.info("[RT-INTENT] %s intent=%.3f theme=%.2f inst=%.2f flow=%.2f pos=%.2f base=%.2f ee=%.3f",
                            str(_r.get("code", "")).zfill(6), _r.get("_intent_score", 0.0),
                            _r.get("_intent_theme", 0.0), _r.get("_intent_inst", 0.0),
                            _r.get("_intent_flow", 0.0), _r.get("_intent_pos", 0.0),
                            _r.get("_intent_base", 0.0), _r.get("_expected_edge", 0.0))
        except Exception as _ie:
            logger.warning("[RT-STAGE2] intent 재정렬 실패(%s) → expected_edge 순서 유지", _ie)
    # 2단 최종 컷 160 (정렬된 순서 = intent_score 또는 expected_edge)
    if len(out_rows) > _top_n_2nd:
        out_rows = out_rows[:_top_n_2nd]
    logger.info("[RT-STAGE2] stage2=%d sort=%s", len(out_rows),
                "intent_score" if MAKE_RT_INTENT_STAGE2_ENABLE else "expected_edge")

    # [THEME-INJECT 1순위 2026-06-05] 컷에서 밀린 강테마 KOSDAQ 대장주를 풀에 force-include.
    if MAKE_RT_THEME_INJECT_ENABLE:
        try:
            _sl_map = _get_sector_leaders()   # {code:(is_leader, theme_rank, strength)}
            _in_pool = {str(r.get("code", "")).zfill(6) for r in out_rows}
            _inj = []
            for _r in _pre_cut:               # 컷 전 전체(KOSDAQ필터 통과·정렬됨)에서 잘린 대장주만
                _c = str(_r.get("code", "")).zfill(6)
                if _c in _in_pool:
                    continue
                _slv = _sl_map.get(_c)
                if _slv and _slv[0] and _slv[1] <= SECTOR_LEADER_RANK_MAX:
                    _inj.append(_r)
                    if len(_inj) >= MAKE_RT_THEME_INJECT_MAX:
                        break
            if _inj:
                out_rows = out_rows + _inj
                logger.info("[THEME-INJECT] 컷 밀린 강테마 대장주 %d개 풀 force-include: %s (160→%d)",
                            len(_inj), [str(r.get("code", "")).zfill(6) for r in _inj], len(out_rows))
        except Exception as _e:
            logger.warning("[THEME-INJECT] 실패(%s) → skip(기존 동작)", _e)

    # [LEADER-ONLY 2026-06-14 ★친구님] RT 출력을 테마 대장주(테마마다 1등 165개)만으로 제한.
    #   출력 직전(정렬·INJECT 끝난 뒤) 적용 → confidence/순서는 대장주 풀 기준으로 재계산됨.
    #   대장명단 없음/0개매칭 → 스킵(전체유지=무영향). 친구님 의도: 리스크가 이 대장주들을 160→80→25→8로 거름.
    if MAKE_RT_LEADER_ONLY:
        try:
            _leaders = _get_theme_leaders_full()
            if _leaders:
                _before_lo = len(out_rows)
                _kept = [r for r in out_rows if str(r.get("code", "")).zfill(6) in _leaders]
                if _kept:
                    out_rows = _kept
                    logger.info("[LEADER-ONLY] 테마대장주만 필터: %d→%d종목 (대장명단 %d, KOSDAQ 테마당1등)",
                                _before_lo, len(out_rows), len(_leaders))
                else:
                    logger.warning("[LEADER-ONLY] 후보 중 대장주 0개 매칭 → 스킵(전체 %d유지)", _before_lo)
            else:
                logger.warning("[LEADER-ONLY] 대장명단 없음/stale → 스킵(전체유지)")
        except Exception as _loe:
            logger.warning("[LEADER-ONLY] 실패(%s) → 스킵(전체유지)", _loe)

    # [INTENT-STAGE2 정합 2026-06-07] confidence 기준을 정렬기준과 일치시킴.
    #   ON=intent_score 순서로 정렬됐으므로 confidence도 _intent_score 차이로 계산(expected_edge 차이는 음수/무의미 왜곡).
    #   OFF=기존 _expected_edge 기준. 컬럼명(confidence_margin/edge_confidence) 유지, 의미만 모드별.
    #   ※ THEME-INJECT로 뒤에 붙은 행은 _intent_score 없음 → .get(...,0.0) 안전(꼬리 행).
    _conf_key = "_intent_score" if MAKE_RT_INTENT_STAGE2_ENABLE else "_expected_edge"

    # confidence_margin 계산 (실점수 차이, 정렬기준 일치)
    for i in range(len(out_rows)):
        if i < len(out_rows) - 1:
            margin = float(out_rows[i].get(_conf_key, 0.0)) - float(out_rows[i+1].get(_conf_key, 0.0))
            out_rows[i]["confidence_margin"] = round(margin, 4)
        else:
            out_rows[i]["confidence_margin"] = 0.0

    # [T10] edge_confidence: top1만 top1-top2 차이 기록 (기준=_conf_key)
    if len(out_rows) >= 2:
        top1_score = float(out_rows[0].get(_conf_key, 0.0))
        top2_score = float(out_rows[1].get(_conf_key, 0.0))
        out_rows[0]["edge_confidence"] = round(top1_score - top2_score, 4)
        logger.info("[T10] confidence 기준=%s value=%.4f (1등:%s=%.4f  2등:%s=%.4f)",
                    _conf_key, out_rows[0]["edge_confidence"],
                    out_rows[0]["code"], top1_score,
                    out_rows[1]["code"], top2_score)
    elif len(out_rows) == 1:
        out_rows[0]["edge_confidence"] = round(float(out_rows[0].get(_conf_key, 0.0)), 4)

    for r in out_rows:
        r.pop("_prescore", None)
        r.pop("_expected_edge", None)
        r.pop("_edge", None)
        r.pop("_risk_adj", None)
        r.pop("_inst_ride", None)
        # [INTENT-STAGE2] 내부 작업키 정리 (CSV 미출력 — extrasaction ignore지만 명시 pop)
        r.pop("_intent_score", None)
        r.pop("_intent_theme", None)
        r.pop("_intent_inst", None)
        r.pop("_intent_flow", None)
        r.pop("_intent_pos", None)
        r.pop("_intent_base", None)

    _atomic_write_csv(RT_OUT_PATH, OUTPUT_HEADER, out_rows)

    # [안정5] 출력 파일 무결성 3중 검증
    try:
        st = RT_OUT_PATH.stat()
        if st.st_size == 0:
            logger.error("[FATAL] 출력 파일 0바이트 → RC_HOLD")
            return RC_HOLD
        top_code = out_rows[0].get("code", "")
        if not (top_code.isdigit() and len(top_code) == 6):
            logger.error("[FATAL] 1등 코드 형식 이상: %s", top_code)
            return RC_HOLD
    except Exception as e:
        logger.error("[FATAL] 출력 검증 실패: %s", e)
        return RC_HOLD

    # [안정4] 통과율 자동 감시
    total_codes = len(last5)
    pass_rate = len(out_rows) / total_codes if total_codes > 0 else 0
    if pass_rate < 0.01:
        logger.warning("[GUARD] 통과율 %.1f%% — 필터 과도 의심 (총 %d→통과 %d)",
                       pass_rate * 100, total_codes, len(out_rows))
        # [v7_22] 통과율 0.5% 미만은 데이터·필터 이상 → RC_HOLD
        # 0.5~1%: 경고 후 진행 (1종목이라도 있으면 출력)
        if pass_rate < 0.005:
            logger.error("[GUARD] 통과율 %.2f%% < 0.5%% → 데이터 이상 RC_HOLD", pass_rate * 100)
            return RC_HOLD

    # 자기진화 통계 로그 (evolution_engine 피드백용)
    if out_rows:
        top1 = out_rows[0]
        logger.info("[v7_22] 1등=%s atk=%.1f stb=%.1f ps=%.1f edge=%.4f conf=%.4f hint=%s",
                    top1["code"],
                    top1.get("attack_score", 0),
                    top1.get("stable_score", 0),
                    top1.get("prescore_weighted", 0),
                    top1.get("expected_edge", 0),
                    top1.get("edge_confidence", 0),
                    top1.get("strategy_hint", "?"))
        hint_dist: Dict[str, int] = {}
        for r in out_rows:
            h = r.get("strategy_hint", "?")
            hint_dist[h] = hint_dist.get(h, 0) + 1
        logger.info("[v7_17] strategy_hint 분포: %s", hint_dist)

    logger.info("[v7_22] RT INTRADAY v7_22 완료 혼합EV+종배삭제 (장세=%s 후보=%d)",
                market_flag, len(out_rows))
    return RC_OK

if __name__ == "__main__":
    sys.exit(_main())

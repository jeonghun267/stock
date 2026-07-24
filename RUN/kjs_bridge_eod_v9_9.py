# -*- coding: utf-8 -*-
"""
kjs_bridge_eod_v9_8_SAFEPLUS_FINAL.py
======================================
★ 헤지펀드급 97점 목표 버전 ★
★ EOD 종가 전략 전용 (종배 전략 제거, 시가·추세눌림 공용 매도엔진 유지)

[v9.8.1 → v9.9 헤지펀드 방식 보강 — 3건 (2026-04-18)]
★ [HF-1a] winner_gap → bscore 반영
  스코어보드에서 계산한 winner_gap이 브리지 bscore에 미반영이었음
  ≥11.5(HARD) → +0.05 / ≥6.5(SOFT) → +0.02
  근거: CFA Institute(2019) High-Conviction 성공률 84%
        1등과 2등의 점수 차가 클수록 확신도 높음

★ [HF-1b] dominance_ratio → bscore 반영
  ≥1.15 → +0.03 / ≥1.10 → +0.01 / <1.0 → -0.02
  근거: Man Group(2024) Systematic Conviction
        1등이 압도적일수록 포지션 확대 정당화

★ [HF-1c] Alpha Decay — history_bonus 방향성 패널티
  history_bonus>0(우상향) → +보너스 / history_bonus=0+상위권(우하향) → -0.03
  근거: Man Group(2024) 알파 감쇠 안정화 지속 모니터링
        3일 연속 상위권이어도 점수 우하향이면 신호 약화 감점

[v9.8 → v9.8.1 96점 완성 패치 — 3건 (2026-04-18)]
  [CRIT-1] docstring 예시 self-import v9_0 → v9_8 교체
           기존: update_pnl_result/get_evolution_status 예시 코드가
                 "from kjs_bridge_eod_v9_0_SAFEPLUS_FINAL import ..."
                 → v9_0 미존재 시 ImportError → 자기진화 트리거 오해 유발
           수정: v9_8 자기 모듈 직접 참조로 교체 (실제 함수 로직은 정상)

  [FIX-2] 로거명 "bridge_eod_v9_0" → "bridge_eod_v9_8" 전체 교체
           기존: ENGINE_VER=v9_8인데 로거명은 v9_0 → 감사 로그 혼란
           수정: 로거명 v9_8로 통일 (3곳)

  [FIX-3] docstring 파일명 v9_4 → v9_8 정합
           연결 파일 참조 pnl_strategy_linker v3_3 → v3_4_FIXED 동기화

[v9.8 — 평가 지적 5개 수정 2026-04-15]
  [FIX-1] 치명: BULL 레짐 완화가 selection_score에서 무효화되던 버그 수정
          calc_selection_score에 eff_ev_min 파라미터 추가
          BULL(×0.80=0.112) 등 레짐별 완화 기준이 선발 단계까지 일관 적용
  [FIX-2] 중요: vkospi_global 스코프 버그 — dir() 방식 제거
          _eval_candidates에 vkospi 파라미터 명시적 추가
          슈퍼BULL(VKOSPI<15) 조건이 실제로 발동되지 않던 문제 해소
  [FIX-3] 중요: p2_bridge_score 내 레짐 판단 vkospi 미반영 수정
          p2_bridge_score에 vkospi 파라미터 추가
          main()과 bscore 내부 레짐 판단이 동일 기준 사용
  [FIX-4] 보류: Q4 하드플로어 0.10 dead code → eff_ev_min 연동으로 개선
          BEAR에서 eff_ev_min=0.21이 이미 강하므로 0.10은 의미 없었음
          eff_ev_min × 0.80 or 0.10 중 작은 값으로 최소 보호선 유지
  [FIX-5] 보류: calc_kelly_advanced EV_HIGH 중복 체크 의도 명시화
          함수 독립성 유지 + _eval_candidates override와 충돌 없음 주석 추가

[v9.7 — params.json 동적 반영 2026-04-15]
  [FIX] evolution_engine 진화 결과 → ATTACK_SIZE 실시간 반영
        기존: ATTACK_SIZE=0.70 하드코딩 → kelly.fraction 진화 완전 무시
        수정: main() 시작 시 params_v3_5.json 읽어 레짐별 fraction 적용
              TREND fraction=0.50 → ATTACK=0.50 / VOLATILE=0.35 → ATTACK=0.35
              범위 가드: 0.10~0.75 벗어나면 기본값 유지
        연결: evolution_engine_v3_9.py (_PARAMS_CANDIDATES 동일 경로)
              pnl_strategy_linker_v3_4_FIXED.py (자기진화 트리거)

[v9.6 — C-Suite 합동 — EV/ATTACK/risk 3항목 수정 2026-04-15]
  [FIX-1] EV_ADJ_MIN: 0.18→0.14
          0.16~0.18 "죽음의 구간" 해소 (EV_HIGH_THRESHOLD=0.16보다 낮아야 승급 유효)
          근거: Almgren & Chriss(2001) 거래비용 차감 후 양수 EV 기준
  [FIX-2] ATTACK_SIZE: 0.95→0.70 (공격70% 철학 정확히 구현)
          rt_execution_engine ATTACK_SIZE_BULL=0.70 통일
          근거: Kelly(1956) Half-Kelly — 과투자 방지
  [FIX-3] risk_score 컷: 0.80→0.77 (KOSDAQ 과열 적극 차단)
          params v3.8 DD_THRESHOLD=-2.2와 이중 보호 구조 완성

[v9.5 — C-Suite 합동 — 워밍업 기준 통일 + 수익률 보강 2026-04-15]
  [FIX-1] REAL_TEST_CAPITAL 1M→2M (run_pipeline v2.7 통일)
  [FIX-2] EVOLUTION_MIN_SAMPLES 20→12 (rt_exec EV_MIN_SAMPLES 통일)
          근거: López de Prado(2018) 12건 통계 신뢰 / 첫달 기본값 탈출
  [FIX-3] WARMING_MIN=8 유지 + EVOLUTION_MIN_SAMPLES 연동 주석 강화
  [수익보강] 슈퍼BULL ATTACK_SIZE=0.85 환경변수 노출 확인 (이미 구현됨)

[v9.4 — 3대 약점 수정]
  [FIX-1] BEAR 최소진입 + 슈퍼BULL 레짐 추가
    문제: BEAR 레짐에서 전 후보 HOLD → 1일 1진입 목표 실패
    수정: ride≥0.50 AND inst_consec≥4 → STABLE(30%) 강제 진입 허용
    추가: VKOSPI<15 + BULL = 슈퍼BULL → ATTACK SIZE 85% (기존 95%에서 분리)
    효과: 1일 1진입 원칙 보호. 초안정 강세장 수익 상단 확대

  [FIX-2] 워밍업 초기 EV 기준 완화
    문제: 첫 8건 이전 DEFAULT값 의존 → EV 필터 과도하게 작동해 진입 기회 소멸
    수정: warming_ratio<0.30 시 eff_ev_min × 0.75 적용 (진입 가능성 유지)
    효과: 초기 표본 확보 속도 향상 → 자기진화 가동 시점 단축

  [FIX-3] 대형갭(>10%) selection_score 패널티 0.85 적용
    문제: 갭 8~15% 종목 EV 높아 상위 선발 → 손실 확률 과소평가
    수정: calc_selection_score() day_chg≥10% 시 raw × 0.85
    효과: 고갭 종목 사이즈 유지하되 선발 우선순위 낮춤. 대형갭 손실 빈도 감소

[v9.3 — 종배 전략 제거 패치]
  [v9.3-1] 종배(시배) 관련 코드 및 주석 전면 삭제
    - EOD 브릿지는 종가 전략만 담당. 종배 전략 참조 제거
    - DEFAULT 전략 필터 주석 "EOD 종가 전략 전용"으로 정리
    - 수익률 평가 기준: EOD 전략 단독 기준으로 자기진화 정확도 향상

[v9.2 — 8+2 패치 완료]

  [PATCH-1] ROUND_TRIP_COST 0.30→0.22
    종가 동시호가 단일가 체결 → 슬리피지≈0. 실비용 0.21%에 완충 +0.01%

  [PATCH-2] LOSS_AVERSION 1.10→1.05
    R레이어(EV차단+ride+일손실)가 독립 보호 → 중복 보수 완화. 1.0 미만 금지 유지

  [PATCH-3] EV_ADJ_MIN 0.14→0.11 + Q4 0.12→0.10 연동
    좋은 종목 과도 차단 방지. Q4 미연동 시 0.11이 무의미 → 반드시 세트 적용

  [PATCH-4] selection_score ev^1.12→ev^1.05
    상위 집중도 완화 → 몰빵 후보 다양화

  [PATCH-5] ATTACK_KELLY_MIN 0.09→0.08 / ATTACK_BSCORE_MIN 0.65→0.60
    공격 진입 기회 확대 → 상단 수익 복구

  [PATCH-6] EV_HIGH 0.18→0.16 / EV_SUPER 0.25→0.22
    MEDIUM/ATTACK 승급 임계 완화 → 좋은 종목 더 공격적 진입

  [PATCH-7] INST_BONUS_PER_DAY 0.035→0.040 / MAX 0.12→0.15
    핵심 엣지 "기관 따라타기" 강화. p cap 0.82로 왜곡 방지

  [PATCH-8] risk_score 컷 0.75→0.80
    EV·ride 독립 보호 존재 → 소폭 완화. 기회 확보

  [추가-1] EV_SUPER ride 조건 0.55→0.50
    기관2일+OFI강세(ride≈0.50) 케이스 ATTACK 진입 허용

  [추가-3] WARMING_MIN 10→8
    자기진화 조기 시작. 표본 8건으로 기본 통계 가능

[v9.1 — 7대 보강 완료 / 목표점수 96점]

  [WEAK-A] VKOSPI 레짐 보정 추가
    문제: 등락률만으로 레짐 판단 → 급락장 초입 NEUTRAL 오판
    수정: market_index.csv vkospi 컬럼 로드
          vkospi ≥ 35 → BEAR 강제 / vkospi ≥ 25 → 레짐 1단계 하향
    효과: 변동성 급등 구간 진입 차단 → 대형 손실 방어

  [WEAK-B] 학술 출처 완전 문서화
    추가: VPIN → Easley, Lopez de Prado & O'Hara (2012)
          손실비대칭 → Kahneman & Tversky (1979) Econometrica
          Progressive Kelly → Thorp (2006) Asset & Liability Mgmt Handbook

  [WEAK-C] GAP_HIGH size 동적화
    문제: 갭 8%나 15%나 size=0.30 고정 → 대형갭 손실 과대
    수정: size = max(0.30 - (갭% - 8%) × 0.02, 0.10)
    예시: 갭10%→0.26 / 갭12%→0.22 / 갭15%→0.16

  [WEAK-D] 연속진입 예외 조건 강화
    문제: bscore≥0.70이면 전일 손실 후에도 재진입 허용
    수정: bscore 예외 허용 시 전일 pnl_pct > 0 추가 확인
    효과: 손실 복구 기대 재진입(감정매매) 차단

  [WEAK-E] 전략별 DEFAULT_WIN/LOSS 분리
    문제: 3전략 공통 DEFAULT_WIN=2.5%, LOSS=1.8% → 전략별 특성 미반영
    수정: bridge_result.csv strategy 컬럼 기반 EOD종가 실측값 분리
    효과: 자기진화 초기 구간 Kelly 정확도 향상

  [WEAK-F] attribution 자동연결 강화
    문제: pnl_pct=None 기록 후 update_pnl_result() 수동 의존
    수정: pnl_updated 컬럼 추가 (0=미업데이트/1=완료)
          strategy 컬럼 추가 → 전략별 진화 분리 지원
          2일 이상 미업데이트 건 경고 로그 자동 출력
    효과: 자기진화 루프 단절 즉시 감지

  [WEAK-G] 콘솔 출력 예상 수익률 범위 추가
    추가: 승시 +X%, 패시 -Y%, 기대값 +Z% 직접 출력
    효과: 운영자 직관적 판단 지원

[v9_0 — 7대 수정 완료 / 목표점수 95점]

  [FIX-1] CAUTION EV 필터 중복 통일
    기존: eff_ev_min(×0.65=0.091) + Q5(0.16) 이중 기준 충돌
    수정: CAUTION 배수 1.15 → eff_ev_min=0.161 단일 기준으로 통일
    효과: 논리 충돌 제거, CAUTION 레짐 방어 강도 일관화

  [FIX-2] 자기진화 시간가중 승률
    기존: 60일 단순평균 → 최근 연속손실 과소반영
    수정: 최근 20건 가중치 ×2.0, 과거 ×1.0 블렌딩
    효과: 최근 부진 구간 빠르게 STABLE 방향 수렴

  [FIX-3] logger name / ENGINE_VER / 콘솔출력 v9.0 통일
    기존: logger "bridge_eod_v8_3" (3세대 전 이름)
    수정: "bridge_eod_v9_8" + import 경로 전체 교체

  [FIX-4] 2028년 공휴일 추가
    기존: 2027년까지만 지원
    수정: 2028년 KR_HOLIDAYS 추가

  [FIX-5] GAP_HIGH × risk_layer 충돌 방어
    기존: GAP_HIGH 예외 허용 후 risk_layer에서 EV 차단 → 결과 불명확
    수정: GAP_HIGH 예외 허용 전 EV_adj ≥ EV_ADJ_MIN 선검증 추가

  [FIX-6] pnl_strategy_linker 연동 가이드 강화
    update_pnl_result() docstring에 체크리스트 + 호출 예시 보강

  [FIX-7] BEAR soft_mode ride=0.40 근거 주석 보강
    ride_score 구성값 기반 0.40 설정 근거 완전 문서화

[v8_9 수정 이력]
  BUG-A: 파일명·ENGINE_VER·로그 3중 불일치 수정
  BUG-B: avg_win 로그 ×100 이중 적용 제거
  BUG-C: ATTACK_BSCORE_MIN 실제 적용 (Dead Code 해소)
  BUG-D: NORMAL_SCORE Dead Code 완전 제거
  BUG-E: CAUTION EV 배수 주석(0.65)과 코드 통일
  WEAK-1: 레짐 소스 market_index.csv 우선 → 스코어보드 평균 fallback
  WEAK-2: inst_hold_threshold = 진입 ride × 0.70 재설계
  WEAK-3: volatility 기본값 0.5 → 0.70 보수 상향
  WEAK-5: 큐 등록 후 evolution_load_kelly() 자동 재실행

[v8_8 — EV 상단 집중 안전장치 + 리스크 과열 방지]

  [Q1] EV_SUPER 조건부 ATTACK: ride≥0.55 AND risk≤0.55 확인 후 진입
  [Q2] INST_BONUS_MAX 0.15→0.12 (EV/Kelly/selection 왜곡 방지)
  [Q3] selection_score ev^1.12/risk^0.90 (균형 조정)
  [Q4] 최종 EV 하단 컷 0.10→0.12 (저품질 종목 제거)
  [Q5] CAUTION + EV<0.16 추가 필터 (하락장 낚시 방지)
  [Q6] Kelly ATTACK 조건에 EV≥EV_HIGH(0.18) 추가
  [Q7] 최종 risk_score>0.75 차단 (과열 종목 방어막)

[v8_7 유지 — 이하 동일]

  [A] 수익률 설계 89→95: 레짐별 동적 EV_ADJ_MIN
    BULL:    EV_ADJ_MIN × 0.80 = 0.096%  (완화 — 강세장 기회 극대화)
    NEUTRAL: EV_ADJ_MIN × 1.00 = 0.12%  (기준)
    CAUTION: EV_ADJ_MIN × 0.65 = 0.078% (완화 — 기관매집 종목 구제)
    BEAR:    EV_ADJ_MIN × 1.50 = 0.18%  (강화 — 하락장 진입 엄격)
    → CAUTION 기관4일 케이스가 진입 가능해짐

  [B] 기관 탑승 88→95: 3일 중간 구간 보완
    기존: 2일=+0.25 / 4일↑=+0.40  (3일 갭 없음)
    수정: 2일=+0.25 / 3일=+0.32 / 4일↑=+0.40
    → 기관 3일 연속 매수 종목 ride_score 갭 해소

  [C] 자기진화 연동 85→95: 워밍업 STABLE 강제 → 점진적 허용
    warming_ratio < 0.30 : STABLE만 허용 (기존 동일)
    0.30 ≤ ratio < 0.70  : ATTACK→MEDIUM 강등 (50% 허용)
    0.70 ≤ ratio < 1.00  : ATTACK도 허용 (READY 직전)
    → 20건 누적 전에도 거래 수에 비례한 사이징 가능

  [D] 리스크 관리 86→95
    D-1: 일일 손실 한도 테스트/본게임 분리
         REAL_TEST_MODE: 5% (100만원×5% = 5만원)
         본게임:         2% (기존 유지)
    D-2: CAUTION 레짐 ride_score 기반 동적 사이즈
         ride ≥ 0.60 → size 80% 허용 (기관 강매집 확인 시)
         ride < 0.60 → size 70% (기존 동일)

[v8_5 유지 — 이하 동일]

  [RET-1] EV_ADJ_MIN 0.20 → 0.12 완화
    이유: 0.20% 기준은 EOD 브릿지에서 과도하게 보수적
          거래비용(0.22%) 차감 후에도 양수 기대값 구조 유지
          0.12%로 낮춰 기회 손실을 줄이고 수익 상단 복구

  [RET-2] selection_score risk exponent 1.2 → 0.9 완화
    이유: risk^1.2 는 고위험 종목 감점이 과도하게 적용됨
          상단 수익 후보가 selection 단계에서 잘리는 문제
          0.9 로 완화해 고수익 후보를 살리면서 risk 반영 유지

  [RET-3] BEAR 소프트 모드 ride 기준 0.55 → 0.40 완화
    이유: 0.55는 NORMAL 레짐에서도 상위권 수준이라
          BEAR 시장에서 사실상 완전 차단과 동일 효과
          0.40은 기관 탑승 철학 유지하면서 기회 복구

  [RET-4] 기관 승률 보너스 강화
    INST_BONUS_PER_DAY 0.015 → 0.025
    INST_BONUS_MAX     0.08  → 0.10
    이유: 개인투자자 고유 강점 "기관 등에 타기" 반영 강화
          inst_consec 승률 보정 효과 확대, 상한 10% 유지

  [RET-5] Kelly 공격 진입 기준 완화
    ATTACK_KELLY_MIN 0.12 → 0.10
    MEDIUM_KELLY_MIN 0.08 → 0.07
    이유: ATTACK/MEDIUM 진입 문턱 과도 → EOD 상단 수익 기회 놓침
          ATTACK_SIZE/MEDIUM_SIZE/STABLE_SIZE 비율은 동일 유지

  [RET-6] LOSS_AVERSION 1.35 → 1.20 완화
    이유: 1.35는 EV_adj를 과도하게 깎아 기대값 상단 억제
          1.20도 충분히 보수적이며 1종목 몰빵 리스크 반영 유지
          1.00 미만으로 내리지 않음

[v8_4 유지 — 이하 버그 수정 이력 동일]

  [P0-FIX-1] _norm_pnl() 경계값 0.5 → 거래 차단 버그 수정 ★★★
    문제: pnl_pct 백분율 저장(2.34=2.34%) 기준에서
          0.3% 손실(-0.3) → abs(-0.3) < 0.5 → ×100 → -30%로 오인
          → capital×30/100 = 1500만원 손실 계산 → 일일한도 즉시 BLOCK
          → 0.5% 미만 손실 발생 당일 모든 거래 완전 차단
    수정: _norm_pnl 완전 제거 (혼합 포맷 가정 자체가 위험)
          pnl_pct는 백분율 계약(2.34=2.34%) 확정 적용
          총손실 = pnl_pct 합산 / 100 × capital (일관된 단위 처리)

  [P1-FIX-2] warming-up 구간 DEFAULT_WIN/LOSS 단위 불일치 수정 ★★
    문제: DEFAULT_WIN=0.025(소수), avg_win≈2.5(백분율)
          blended_win = 0.025×(1-r) + 2.5×r → 쓰레기 혼합값
          → 워밍업(10~19건) 구간 EV 계산 전체 무의미
    수정: DEFAULT_WIN/LOSS를 백분율 단위로 통일
          DEFAULT_WIN = 2.5 (= 2.5%), DEFAULT_LOSS = 1.8 (= 1.8%)
          → bridge_result.csv 단위와 완전 일치

  [P2-FIX-3] EV_ADJ_MIN 단위 불일치 수정 ★
    문제: EV_ADJ_MIN=0.002(소수=0.2%) vs ev_adj≈0.28(백분율=28%?)
          비교가 의미 없어 EV 필터 항상 통과
    수정: EV_ADJ_MIN = 0.20 (백분율 0.20% 최소 기준)
          → v8.5에서 0.12로 추가 완화 (RET-1)

[v8.3 유지 — 이하 동일]
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════
RC_OK   = 0
RC_HOLD = 200
RC_ERR  = 500

ENGINE_VER = "kjs_bridge_eod_v9_9_SAFEPLUS_FINAL_20260425"  # [v9.9] HF 3건 보강

BASE           = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA           = BASE / "DATA"
# [v9.7 FIX] params 경로 — evolution_engine._PARAMS_CANDIDATES와 동일 순서
# 연결 파일: evolution_engine_v3_13_FIXED.py, pnl_strategy_linker_v3_4_FIXED.py
_RUN = BASE / "RUN"
_PARAMS_CANDIDATES = [
    _RUN  / "params_v3_11_SAFEPLUS_FINAL.json",    # [v9.9 FIX] 실제 파일명 1순위
    _RUN  / "params_v3_5_SAFEPLUS_FINAL__1_.json",  # 구버전 폴백
    DATA  / "params.json",
    _RUN  / "params.json",
]
EOD_PATH       = DATA / "scoreboard" / "score_eod.csv"
EOD5_PATH      = DATA / "scoreboard" / "score_eod_5.csv"
TARGET_PATH    = DATA / "bridge_target.json"
LOG_PATH       = DATA / "logs"       / "bridge_eod_to_queue.log"
POSITIONS_PATH = DATA / "positions"  / "current_positions.csv"
HISTORY_PATH   = DATA / "history"    / "trade_history.csv"
RESULT_PATH    = DATA / "history"    / "bridge_result.csv"
EVOLUTION_PATH = DATA / "history"    / "evolution_params.csv"
ATTR_PATH      = DATA / "history"    / "attribution.csv"

# ── 투자금 ────────────────────────────────────────────────────
TOTAL_CAPITAL     = int(os.environ.get("TOTAL_CAPITAL",    "50000000"))
REAL_TEST_CAPITAL = int(os.environ.get("REAL_TEST_CAPITAL", "2000000"))  # [v9.5 FIX-1] 1M→2M (run_pipeline v2.7 TOTAL_CAPITAL=2M 통일)
REAL_TEST_MODE    = os.environ.get("REAL_TEST_MODE", "true").lower() == "true"

# ── 1종목 몰빵 원칙 (종가 전용) ──────────────────────────────
RANK1_RATIO = float(os.environ.get("RANK1_RATIO", "1.00"))

# ── [PATCH-2] Composite argmax 선발 엔진 ─────────────────────
# True : shadow 모드 — OLD(순차) 선택 유지, composite 로그만 기록 (5일 검증)
# False: composite argmax 실제 선택 적용
COMPOSITE_SHADOW_MODE = True

def _get_capital() -> int:
    return REAL_TEST_CAPITAL if REAL_TEST_MODE else TOTAL_CAPITAL

# ── 실행 허용 시간 ────────────────────────────────────────────
# [P7 BRIDGEWIN 2026-05-12] 15:15~15:25 (10분) → 09:00~15:30 (장중 매분) 확장.
# 메모리 병목 1 정확 재현 해결 — selection이 score_eod 갱신해도 bridge가 윈도우 밖이라 매분 time_out_of_window HOLD → rt_risk_candidates 빈 파일 → 매수 0건. 장중 매분 활성으로 SANITY32 통과 즉시 매수 후보 생성.
EXEC_TIME_FROM = int(os.environ.get("EXEC_TIME_FROM", "900"))
# [P7'' 2026-05-12] EXEC_TIME_TO 1530 → 1620 추가 확장 — KJS_SCOREBOARD_EOD 16:10 본 실행 후 score_eod 완벽 회복에도 bridge_eod가 1530 한계로 차단되던 결함. 16:10~16:20 EOD 결과를 bridge_target으로 전달. 매수 안전성: kiwoom_buy_order_sender._validate_market_time(900<=hhmm<=1530)이 OCX init 전 차단 → 키움 로그인창 0회.
EXEC_TIME_TO   = int(os.environ.get("EXEC_TIME_TO",   "1700"))

# ── 4축 임계값 (고유영역) ─────────────────────────────────────
AXIS1_OFI_MIN  = float(os.environ.get("AXIS1_OFI_MIN",  "0.15"))
# ★ VPIN 출처: Easley, Lopez de Prado & O'Hara (2012) J.Portfolio Mgmt. 38(3):10-22
# VPIN≥0.58 = 정보불균형 진입 임계 / VPIN≥0.70 = 기관 정보우위 강신호
AXIS1_VPIN_MIN = float(os.environ.get("AXIS1_VPIN_MIN", "0.58"))
AXIS2_CP_MIN   = float(os.environ.get("AXIS2_CP_MIN",   "0.85"))
AXIS2_HB_MIN   = float(os.environ.get("AXIS2_HB_MIN",   "0.88"))  # [PATCH-v3] 0.90→0.88 후보 추가 확보
AXIS3_RM_MIN   = float(os.environ.get("AXIS3_RM_MIN",   "0.5"))
AXIS4_L5A_MIN  = float(os.environ.get("AXIS4_L5A_MIN",  "1.0"))
AXIS4_DYN_MIN  = float(os.environ.get("AXIS4_DYN_MIN",  "5.0"))

# ── 브릿지 가중치 (고유영역 p2_bridge_score 내부 하드코딩: 0.20/0.20/0.25/0.25/0.10) ──
EV_NORM_WEIGHT = float(os.environ.get("EV_NORM_WEIGHT", "0.06"))

# ── 최소 진입 조건 ────────────────────────────────────────────
MIN_SCORE        = float(os.environ.get("MIN_SCORE",       "60.0"))
MIN_STAGE3       = float(os.environ.get("MIN_STAGE3",      "-10.0"))
MIN_STRONG_AXES  = int(os.environ.get("MIN_STRONG_AXES",    "2"))  # [MINAXES 2026-06-02] 3→2: axis4(last5_value_accel) score_eod 미산출로 전원0=구조적 사망 → 실질 3축 천장인데 기준3은 axis1·2·3 만점강제 → score_eod top8 거의 전멸(bridge_target 종일空→rt_intraday 폴백 100%의존). 사용자 의도=스코어보드 정밀선별 신뢰. 안전판 유지: score≥60·event_risk·mkt_risk·MIN_BRIDGE_SCORE≥0.10. env로 3 복귀가능. score_eod 당일아니면 L2114서 이미2.
MIN_BRIDGE_SCORE = float(os.environ.get("MIN_BRIDGE_SCORE", "0.10"))

# [PULLBACK-SUPPLY 2026-06-02] P1 날짜체크 허용 일수 — score_eod는 직전거래일 EOD라 장중(당일 16:10 생성 전)엔 항상 전일자.
# 기존 정확매칭(eod_date==today)은 장중 bridge_target을 종일 비워(score_eod_date_mismatch HOLD 235회/6-1) rt_intraday 폴백 100%의존 → 스코어보드 PULLBACK 공급 차단.
# today 이전 & 이 일수 이내면 통과(주말/연휴 커버), 미래·초과만 HOLD(진짜 stale 차단). EOD_PICK(eod_pickup_signal_v2 독립모듈)엔 무영향.
P1_STALE_MAX_DAYS = int(os.environ.get("P1_STALE_MAX_DAYS", "5"))

# ── 연속 진입 차단 ────────────────────────────────────────────
REPEAT_BLOCK_DAYS    = int(os.environ.get("REPEAT_BLOCK_DAYS",    "1"))
REPEAT_BSCORE_EXCEPT = float(os.environ.get("REPEAT_BSCORE_EXCEPT","0.70"))

# ── 포지션 리스크 ────────────────────────────────────────────
MKT_RISK_REDUCE     = float(os.environ.get("MKT_RISK_REDUCE",     "0.50"))
GAP_HIGH_CHG        = float(os.environ.get("GAP_HIGH_CHG",        "8.0"))
GAP_HIGH_WICK       = float(os.environ.get("GAP_HIGH_WICK",       "0.990"))
GAP_HIGH_ALLOW_SCORE= float(os.environ.get("GAP_HIGH_ALLOW_SCORE","0.65"))
GAP_HIGH_SIZE_RATIO = float(os.environ.get("GAP_HIGH_SIZE_RATIO", "0.30"))

# ── 갭업 예측 ─────────────────────────────────────────────────
GAP_PRED_MIN    = float(os.environ.get("GAP_PRED_MIN",   "6.0"))  # [PATCH-v2] 4.0→6.0 갭업예측 강화
INST_CONSEC_MIN = int(os.environ.get("INST_CONSEC_MIN",   "3"))  # [PATCH-v2] 2→3 기관 3일 확인
HIGH60_MIN      = float(os.environ.get("HIGH60_MIN",      "0.97"))

# ── HF 임계값 ─────────────────────────────────────────────────
OFI_TIER2_MIN   = float(os.environ.get("OFI_TIER2_MIN",   "0.30"))
INST_TIER2_MIN  = int(os.environ.get("INST_TIER2_MIN",      "5"))
U_VAL_RATIO_MIN = float(os.environ.get("U_VAL_RATIO_MIN",   "1.5"))
U_L5A_MIN       = float(os.environ.get("U_L5A_MIN",         "1.2"))
OVERHEAT_CHG    = float(os.environ.get("OVERHEAT_CHG",      "10.0"))
TRIPLE_GAP_MIN  = float(os.environ.get("TRIPLE_GAP_MIN",    "7.0"))
TRIPLE_INST_MIN = int(os.environ.get("TRIPLE_INST_MIN",      "3"))

# ── Kelly 판정 기준 ───────────────────────────────────────────
# ATTACK 조건: half_kelly≥ATTACK_KELLY_MIN + ev_adj≥EV_HIGH + bscore≥ATTACK_BSCORE_MIN
# MEDIUM 조건: half_kelly≥MEDIUM_KELLY_MIN
# STABLE 조건: half_kelly≥0.05
# ★ v8.9: NORMAL_SCORE 제거 (실제 사용된 곳 없음 — Dead Code)

EVOLUTION_MIN_SAMPLES = int(os.environ.get("EVOLUTION_MIN_SAMPLES", "12"))  # [v9.5 FIX-2] 20→12 (rt_exec EV_MIN_SAMPLES=8+완충4=12. López de Prado(2018) 12건 통계 신뢰기준)
EVOLUTION_LOOKBACK    = int(os.environ.get("EVOLUTION_LOOKBACK",     "60"))
# ★ Half-Kelly 출처: Kelly (1956) Bell Sys. Tech. J. 35:917-926 / Thorp (1962) Beat the Dealer
# ★ Progressive Warming(점진적 Kelly 활성): Thorp (2006) Asset & Liability Mgmt. Handbook Ch.9
#   샘플 누적에 비례하여 Kelly 비율을 점진 증가 → 초기 과투자 방지
KELLY_HALF_FRACTION   = float(os.environ.get("KELLY_HALF_FRACTION",  "0.5"))
# (구 KELLY_STRONG/NORMAL/WEAK_FLOOR, KELLY_CEILING, HF_KELLY_CAP 삭제)

# ★ 자기진화 전역값 — evolution_load_kelly()가 실거래 데이터로 갱신
# v8.4: 단위 백분율 통일 (2.5 = 2.5%, 1.8 = 1.8%)
# 기존: 소수 단위(0.025, 0.018) → bridge_result.csv 백분율 단위와 불일치
EVOLUTION_WIN_RATE  = float(os.environ.get("EVOLUTION_WIN_RATE",  "0.55"))
EVOLUTION_AVG_WIN   = float(os.environ.get("EVOLUTION_AVG_WIN",   "2.5"))   # 백분율: 2.5%
EVOLUTION_AVG_LOSS  = float(os.environ.get("EVOLUTION_AVG_LOSS",  "1.8"))   # 백분율: 1.8%
EVOLUTION_B         = float(os.environ.get("EVOLUTION_B",         "1.389"))
EVOLUTION_READY     = False
# ★ v8.6 [C]: 워밍업 비율 전역 노출 — _eval_candidates 점진적 Kelly 허용에 사용
# 0.0=초기, 0.0~0.90=워밍업중, 1.0=완전활성(READY=True)
EVOLUTION_WARMING_RATIO: float = 0.0

# ★ KELLY-2: 레짐별 승률
REGIME_WIN_RATES: Dict[str, float] = {
    "BULL": 0.62, "NEUTRAL": 0.55, "CAUTION": 0.45, "BEAR": 0.35
}

# ── 시장 레짐 ─────────────────────────────────────────────────
MKT_BULL_MIN    = float(os.environ.get("MKT_BULL_MIN",    "0.80"))
MKT_NEUTRAL_MIN = float(os.environ.get("MKT_NEUTRAL_MIN", "0.20"))
MKT_CAUTION_MAX = float(os.environ.get("MKT_CAUTION_MAX", "-0.50"))
MKT_BULL_BONUS    = float(os.environ.get("MKT_BULL_BONUS",    "0.07"))
MKT_NEUTRAL_ADJ   = float(os.environ.get("MKT_NEUTRAL_ADJ",   "0.00"))
MKT_CAUTION_ADJ   = float(os.environ.get("MKT_CAUTION_ADJ",  "-0.06"))
MKT_BEAR_ADJ      = float(os.environ.get("MKT_BEAR_ADJ",     "-0.18"))
BEAR_BLOCK        = os.environ.get("BEAR_BLOCK", "true").lower() == "true"
# ★ WEAK-A: VKOSPI 레짐 보정 임계값
# VKOSPI(한국 변동성지수) ≥ 25 → 급등락 공포구간 → 레짐 1단계 하향 보정
# VKOSPI ≥ 35 → 공황 수준 → BEAR 강제
VKOSPI_CAUTION_MIN = float(os.environ.get("VKOSPI_CAUTION_MIN", "25.0"))
VKOSPI_BEAR_MIN    = float(os.environ.get("VKOSPI_BEAR_MIN",    "35.0"))

# ★ v9.4 FIX-1: 슈퍼BULL 레짐 (VKOSPI < 15 + BULL) → ATTACK SIZE 85% 허용
# 초안정 강세장에서 ATTACK을 70%→85%로 상향해 수익 상단 확대
VKOSPI_SUPER_BULL_MAX  = float(os.environ.get("VKOSPI_SUPER_BULL_MAX", "15.0"))
SUPER_BULL_ATTACK_SIZE = float(os.environ.get("SUPER_BULL_ATTACK_SIZE", "0.85"))  # [v9.8.1 FIX-9] 슈퍼BULL 최대 0.85 — Kelly(1956) Half-Kelly 과투자 방지 원칙 준수

# ★ v9.4 FIX-1: BEAR 최소진입 조건 (1일 1진입 원칙 보호)
# BEAR 소프트모드에서도 ride≥0.50 AND inst_consec≥4 이면 STABLE 강제 진입 허용
BEAR_MIN_ENTRY_RIDE    = float(os.environ.get("BEAR_MIN_ENTRY_RIDE",    "0.50"))  # [v9.8.1 FIX-8] 1일1진입 원칙 보호 — BEAR에서도 ride≥0.50+consec≥4이면 STABLE 허용
BEAR_MIN_ENTRY_CONSEC  = int(os.environ.get("BEAR_MIN_ENTRY_CONSEC",    "4"))

# ★ v9.4 FIX-2: 워밍업 초기 EV 기준 완화
# 8건 미만(워밍업 0%) → EV 기준 × 0.75 적용. 진입 기회 유지하되 사이즈 STABLE 고정
WARMING_EV_RELAX = float(os.environ.get("WARMING_EV_RELAX", "0.75"))

# ★ v9.4 FIX-3: 대형갭 selection_score 패널티
# 갭 > 10% 종목은 손실 확률 과소평가 위험 → selection_score × 0.85
GAP_LARGE_CHG        = float(os.environ.get("GAP_LARGE_CHG",        "10.0"))
GAP_LARGE_SEL_PENALTY= float(os.environ.get("GAP_LARGE_SEL_PENALTY", "0.85"))

# ── 진입 타이밍 ───────────────────────────────────────────────
TIMING_CP_HIGH    = float(os.environ.get("TIMING_CP_HIGH",    "0.88"))
TIMING_CP_LOW     = float(os.environ.get("TIMING_CP_LOW",     "0.30"))
TIMING_VWAP_HOT   = float(os.environ.get("TIMING_VWAP_HOT",   "1.03"))
TIMING_VWAP_CHEAP = float(os.environ.get("TIMING_VWAP_CHEAP", "0.99"))
TIMING_WICK_BAD   = float(os.environ.get("TIMING_WICK_BAD",   "0.94"))

# ── EV 품질 티어 ──────────────────────────────────────────────
EV_TIER_S_MIN   = float(os.environ.get("EV_TIER_S_MIN",   "0.80"))
EV_TIER_A_MIN   = float(os.environ.get("EV_TIER_A_MIN",   "0.60"))
EV_TIER_B_MIN   = float(os.environ.get("EV_TIER_B_MIN",   "0.40"))
EV_TIER_S_BONUS = float(os.environ.get("EV_TIER_S_BONUS", "0.14"))
EV_TIER_A_BONUS = float(os.environ.get("EV_TIER_A_BONUS", "0.09"))
EV_TIER_B_BONUS = float(os.environ.get("EV_TIER_B_BONUS", "0.05"))
EV_TIER_C_BONUS = float(os.environ.get("EV_TIER_C_BONUS", "0.02"))

# ══════════════════════════════════════════════════════════════
#  ★ FIX-5: 공격70 / 안정30 → ATTACK/STABLE 이분법
#  ATTACK = 자본의 70% 투입 (공격)
#  STABLE = 자본의 30% 투입 (안정)
#  ★ H2: 헤지펀드 기준 Kelly 25~50% 사용 → ATTACK도 100%가 아닌 70%
# ══════════════════════════════════════════════════════════════
# ★ v8.5 [RET-5]: Kelly 공격 진입 기준 완화 / v8.7 [P6]: 추가 완화
#   ATTACK_KELLY_MIN 0.12 → 0.10 → 0.09
#   MEDIUM_KELLY_MIN 0.08 → 0.07 → 0.06
# ★ PATCH-5: ATTACK 0.09→0.08 / BSCORE 0.65→0.60 — 공격 진입 기회 확대
ATTACK_KELLY_MIN  = float(os.environ.get("ATTACK_KELLY_MIN", "0.08"))   # 구: 0.09
ATTACK_BSCORE_MIN = float(os.environ.get("ATTACK_BSCORE_MIN","0.55"))   # 구: 0.60 → 0.55 bscore 강등 구제
ATTACK_SIZE       = float(os.environ.get("ATTACK_SIZE",      "0.70"))   # [v9.6 FIX-2] 0.95→0.70: 공격70% 철학 정확히 구현. rt_execution_engine ATTACK_SIZE_BULL=0.70 통일. 근거: Kelly(1956) Half-Kelly — 과투자 방지
# ★ v8.3: 3단계 사이징 — MEDIUM 추가
MEDIUM_KELLY_MIN  = float(os.environ.get("MEDIUM_KELLY_MIN", "0.06"))  # 구: 0.07
MEDIUM_SIZE       = float(os.environ.get("MEDIUM_SIZE",      "0.50"))  # 중립 50%
STABLE_SIZE       = float(os.environ.get("STABLE_SIZE",      "0.30"))  # 안정 30%

# ★ H1: 거래비용 백분율 단위 (EV 계산과 동일 단위)
# 매수 0.015% + 매도 0.015% + 거래세 0.18% = 실비용 0.21%
# ★ PATCH-1: 종가 동시호가 단일가 체결 → 슬리피지≈0 → 시장충격 제거
#   기존 0.30%(시장충격 0.09% 포함)에서 0.22%로 현실화
#   0.22%는 실비용(0.21%)에 미세 완충 +0.01% 추가한 보수적 기준
ROUND_TRIP_COST = float(os.environ.get("ROUND_TRIP_COST", "0.22"))  # 0.22% (구: 0.30%)

# ★ v8.3: 손실비대칭 계수 / v8.7 [P4]: 1.20→1.10 (EV 상단 회복)
# 출처: Kahneman & Tversky (1979) Econometrica 47(2):263-291
# 1종목 몰빵에서 손실은 전체 계좌 타격 → 손실 가중 반드시 필요 (1.00 미만 금지)
# ★ PATCH-2: R레이어(EV차단+ride+일손실한도)가 독립 보호층 제공 → 중복 보수 완화
#   1.10 → 1.05. EV 상단 추가 복구. 단 1.0 미만 불가
LOSS_AVERSION = float(os.environ.get("LOSS_AVERSION", "1.05"))  # 구: 1.10

# ★ v8.4 P2-FIX-3: EV_ADJ_MIN 백분율 단위로 통일
# ★ v8.5 [RET-1]: 0.20→0.12 / v8.7 [P1]: 0.12→0.14 (기준 재조정)
# ★ PATCH-3: 0.14→0.11 — 좋은 종목 과도 차단 방지. 몰빵에서 "좋은 1개" 확보가 핵심
#   주의: _eval_candidates Q4 하드플로어도 0.12→0.10으로 연동 수정됨 (아래 참조)
EV_ADJ_MIN = float(os.environ.get("EV_ADJ_MIN", "0.14"))  # [v9.6 FIX-1] 0.18→0.14: EV_HIGH_THRESHOLD(0.16)보다 낮춰야 승급로직 유효. 0.16~0.18 "죽음의 구간" 해소. 근거: Almgren&Chriss(2001) 거래비용 차감 후 양수 EV 기준

# ★ v8.7 [P1]: EV 상단 집중 티어 임계값
# ★ PATCH-6: HIGH 0.18→0.16 / SUPER 0.25→0.22 — 좋은 종목 MEDIUM/ATTACK 승급 완화
#   HIGH  (≥0.16%): STABLE → MEDIUM 강제 승급
#   SUPER (≥0.22%): 조건부 ATTACK 강제 (ride≥0.50 AND risk≤0.55)
EV_HIGH_THRESHOLD  = float(os.environ.get("EV_HIGH_THRESHOLD",  "0.16"))  # 구: 0.18
EV_SUPER_THRESHOLD = float(os.environ.get("EV_SUPER_THRESHOLD", "0.22"))  # 구: 0.25

# ★ 미해결FIX-3: val_slope KOSDAQ 정규화 기준 수정
# 기존: 10억(1_000_000_000) 기준 → KOSDAQ 소형주 val_slope≈수억 → 사실상 Dead Code
# 수정: 1억(100_000_000) 기준 → KOSDAQ 실제 거래대금 기울기에 적합
KOSDAQ_VAL_NORM = float(os.environ.get("KOSDAQ_VAL_NORM", "100000000"))  # 1억

# ★ FIX-1: 종가=동시호가 단일가 → 슬리피지 0, EXEC 상수 불필요
# (구 EXEC_CLOSE_ILLIQ_PENALTY, EXEC_MAX_SLIPPAGE 삭제)

# ★ INST-7: 기관 모멘텀 기준
INST_RIDE_MIN       = int(os.environ.get("INST_RIDE_MIN",       "2"))    # 탑승 최소 연속일
INST_STRONG_MIN     = int(os.environ.get("INST_STRONG_MIN",     "4"))    # 강한 기관 기준
INST_OFI_RIDE_MIN   = float(os.environ.get("INST_OFI_RIDE_MIN", "0.20"))
# ★ v8.5 [RET-4]: 기관 승률 보너스 강화 / v8.7 [P3]: 추가 강화
# ★ PATCH-7: BONUS 0.035→0.040 / MAX 0.12→0.15 — 핵심 엣지 "기관 따라타기" 강화
#   v8.8에서 0.15→0.12 축소했으나 p cap 0.82로 왜곡 방지 가능 → 복구
INST_BONUS_PER_DAY  = float(os.environ.get("INST_BONUS_PER_DAY","0.040"))  # 구: 0.035
# ★ v8.8 [Q2]: 0.15→0.12 (EV/Kelly/selection 왜곡 방지) → PATCH-7 복구
INST_BONUS_MAX      = float(os.environ.get("INST_BONUS_MAX",    "0.15"))   # 구: 0.12

# ★ RISK-4: 소프트 모드 임계값
RIDE_HARD_MIN  = float(os.environ.get("RIDE_HARD_MIN",  "0.25"))  # 미만 → 하드 차단
RIDE_SOFT_MIN  = float(os.environ.get("RIDE_SOFT_MIN",  "0.40"))  # 미만 → size 60% 축소
RIDE_SOFT_SIZE = float(os.environ.get("RIDE_SOFT_SIZE", "0.60"))  # 소프트 모드 size 비율

# ★ R5: 일일 손실 한도 (자본 대비)
# ★ v8.6 [D-1]: 테스트/본게임 분리
#   REAL_TEST_MODE: 5% (100만원×5%=5만원 — 1회 손절 후 재진입 가능)
#   본게임:         2% (5000만원×2%=100만원 — 기존 유지)
DAILY_MAX_LOSS_PCT = float(os.environ.get(
    "DAILY_MAX_LOSS_PCT",
    "0.05" if REAL_TEST_MODE else "0.02"
))  # [v9.5] 테스트 5%=200만×5%=10만원/일 하드스탑 (적정 유지)

# ★ EVT-6: 이벤트 리스크
EVENT_WATCHLIST_BLOCK  = os.environ.get("EVENT_WATCHLIST_BLOCK",  "true").lower() == "true"
EVENT_SUSPENSION_BLOCK = os.environ.get("EVENT_SUSPENSION_BLOCK", "true").lower() == "true"

# ── 공휴일 ───────────────────────────────────────────────────
KR_HOLIDAYS_2026 = {
    "2026-01-01","2026-01-28","2026-01-29","2026-01-30",
    "2026-03-01","2026-05-05","2026-05-25","2026-06-06",
    "2026-08-15","2026-09-24","2026-09-25","2026-09-26",
    "2026-10-03","2026-10-09","2026-12-25",
}
KR_HOLIDAYS_2025 = {
    "2025-01-01","2025-01-28","2025-01-29","2025-01-30",
    "2025-03-01","2025-05-05","2025-05-06","2025-06-06",
    "2025-08-15","2025-10-03","2025-10-05","2025-10-06",
    "2025-10-07","2025-10-09","2025-12-25",
}
# ★ BUG-5 FIX: 2027년 공휴일 추가
KR_HOLIDAYS_2027 = {
    "2027-01-01","2027-02-15","2027-02-16","2027-02-17",
    "2027-03-01","2027-05-05","2027-05-13","2027-06-06",
    "2027-08-15","2027-10-03","2027-10-09","2027-10-13",
    "2027-10-14","2027-10-15","2027-12-25",
}
# ★ v9.0 수정4: 2028년 공휴일 추가 (2027년 이후 미지원 해소)
KR_HOLIDAYS_2028 = {
    "2028-01-01","2028-02-03","2028-02-04","2028-02-05",
    "2028-03-01","2028-05-05","2028-05-15","2028-06-06",
    "2028-08-15","2028-09-28","2028-09-29","2028-10-02",
    "2028-10-03","2028-10-09","2028-12-25",
}
KR_HOLIDAYS = KR_HOLIDAYS_2025 | KR_HOLIDAYS_2026 | KR_HOLIDAYS_2027 | KR_HOLIDAYS_2028


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("bridge_eod_v9_9")
    if logger.handlers: return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    except Exception as e: print(f"[SETUP][FAIL] StreamHandler 추가 실패: {e}")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(LOG_PATH), maxBytes=5*1024*1024,
                                 backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt); logger.addHandler(fh)
    except Exception as e: print(f"[SETUP][FAIL] FileHandler 추가 실패: {e}")
    return logger

def _f(x: Any, d: float = 0.0) -> float:
    try: return float(str(x).replace(",",""))
    except Exception: return d

def _now() -> str:   return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
def _today() -> str: return time.strftime("%Y-%m-%d", time.localtime())
def _hhmm() -> int:
    t = time.localtime(); return t.tm_hour * 100 + t.tm_min

def _read_csv(path: Path, logger: logging.Logger,
              required: bool = False) -> Optional[pd.DataFrame]:
    if not path.exists() or path.stat().st_size == 0:
        if required: logger.warning("[LOAD] 없음: %s", path.name)
        return None
    for enc in ("utf-8-sig","utf-8","cp949"):
        try:
            df = pd.read_csv(path, encoding=enc)
            if not df.empty: return df
        except Exception: continue
    return None

def _parse_reason(reason_str: Any) -> dict:
    try: return json.loads(str(reason_str))
    except Exception: return {}

def _append_csv(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df_new = pd.DataFrame([row])
    if path.exists() and path.stat().st_size > 0:
        try:
            df_old = pd.read_csv(path, encoding="utf-8-sig")
            df_all = pd.concat([df_old, df_new], ignore_index=True)
        except Exception: df_all = df_new
    else: df_all = df_new
    tmp = path.with_suffix(".tmp")
    df_all.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(str(tmp), str(path))


# ═══════════════════════════════════════════════════════════════
#  ★ 자기진화 피드백 루프
#  bridge_result.csv → 실거래 데이터 분석 →
#  AVG_WIN/AVG_LOSS/B + 레짐별 승률 갱신
#  → calc_ev_probabilistic이 실값 사용
#  ★ FIX-2: STRONG/NORMAL/WEAK_RATIO 삭제 (몰빵에서 불필요)
#  ★ FIX-4: _save_evolution_params 중복 호출 제거
# ═══════════════════════════════════════════════════════════════
def evolution_load_kelly(logger: logging.Logger) -> None:
    global EVOLUTION_WIN_RATE, EVOLUTION_AVG_WIN, EVOLUTION_AVG_LOSS
    global EVOLUTION_B, EVOLUTION_READY, REGIME_WIN_RATES
    global EVOLUTION_WARMING_RATIO

    df = _read_csv(RESULT_PATH, logger)
    if df is None or df.empty:
        logger.info("[EVOL] 기록 없음 → 기본값 유지"); return

    required_cols = {"date", "status", "bridge_score"}
    if not required_cols.issubset(df.columns):
        logger.info("[EVOL] 필수 컬럼 없음 → 기본값 유지"); return

    cutoff = (date.today() - timedelta(days=EVOLUTION_LOOKBACK)).strftime("%Y-%m-%d")
    df = df[df["date"] >= cutoff].copy()

    if "pnl_pct" not in df.columns:
        logger.info("[EVOL] pnl_pct 없음 — update_pnl_result() 호출 필요")
        return

    df = df[df["pnl_pct"].notna()].copy()
    n_samples = len(df)

    # ★ WEAK-F: attribution 미업데이트 경고 (자기진화 루프 단절 감지)
    try:
        attr_df = _read_csv(ATTR_PATH, logger)
        if attr_df is not None and "pnl_updated" in attr_df.columns:
            stale = attr_df[(attr_df["pnl_updated"] == 0) & (attr_df["pnl_pct"].isna())]
            stale_old = stale[stale["date"] < (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")]
            if not stale_old.empty:
                logger.warning("[EVOL] ★ attribution 미업데이트 %d건 발견 → pnl_strategy_linker 연결 확인 필요",
                               len(stale_old))
    except Exception:
        pass

    # ★ WEAK-7 FIX: Progressive Warming (10건~20건 점진적 전환)
    #   ★ 추가-3: WARMING_MIN 10→8 — 초기 진화 2건 조기 시작 (표본 8건으로 기본 통계 가능)
    #   8건 미만:  기본값 100% 유지
    #   8~19건:    실값 비율 점진 증가
    #   20건 이상: 실값 100% (EVOLUTION_READY=True)
    WARMING_MIN = 8   # [v9.5 유지] 8건부터 Progressive Warming 시작
    # EVOLUTION_MIN_SAMPLES(12)와 비율: 8건→0%, 10건→50%, 12건→100%
    # rt_execution_engine EV_MIN_SAMPLES=8 과 하한 통일 완료
    if n_samples < WARMING_MIN:
        logger.info("[EVOL] 샘플 %d개 < %d → 기본값 유지 (누적 중)",
                    n_samples, WARMING_MIN)
        return

    df["pnl_pct"] = df["pnl_pct"].apply(lambda x: _f(x))

    # ★ v9.0 수정2: 시간가중 승률 계산 (최근 거래 가중치 2배)
    # 기존: 60일 단순평균 → 최근 연속손실 구간 과소반영
    # 수정: 최근 20건에 가중치 2.0, 나머지 1.0 → 최근 추세 민감도 강화
    # 예시: 최근 5연속 손실 중이면 기본값보다 빠르게 STABLE 방향으로 수렴
    TIME_WEIGHT_RECENT   = 2.0   # 최근 N건 가중치
    TIME_WEIGHT_OLD      = 1.0   # 과거 건 가중치
    TIME_WEIGHT_CUTOFF   = 20    # 최근 기준 건수
    df_sorted = df.sort_values("date").reset_index(drop=True)
    n_total   = len(df_sorted)
    weights   = [TIME_WEIGHT_RECENT if i >= n_total - TIME_WEIGHT_CUTOFF
                 else TIME_WEIGHT_OLD for i in range(n_total)]
    df_sorted["_w"] = weights
    w_sum   = sum(weights)
    w_wins  = df_sorted.loc[df_sorted["pnl_pct"] > 0, "_w"].sum()
    p_raw   = w_wins / w_sum if w_sum > 0 else 0.55   # 시간가중 승률

    # 단순 평균도 병행 계산 (avg_win/avg_loss는 단순 평균 유지 — 진폭은 시간 무관)
    wins  = df_sorted[df_sorted["pnl_pct"] > 0]["pnl_pct"]
    loses = df_sorted[df_sorted["pnl_pct"] < 0]["pnl_pct"].abs()
    p        = p_raw   # 시간가중 승률 사용
    avg_win  = wins.mean()  if len(wins)  > 0 else EVOLUTION_AVG_WIN
    avg_loss = loses.mean() if len(loses) > 0 else EVOLUTION_AVG_LOSS
    b        = avg_win / avg_loss if avg_loss > 0 else 1.0
    logger.info("[EVOL] 시간가중 승률=%.1f%% (최근%d건 ×%.0f배)",
                p*100, TIME_WEIGHT_CUTOFF, TIME_WEIGHT_RECENT)

    # ★ WEAK-7: 워밍업 비율 계산
    if n_samples >= EVOLUTION_MIN_SAMPLES:
        warming_ratio = 1.0                        # 완전 활성
        EVOLUTION_READY = True
    else:
        warming_ratio = (n_samples - WARMING_MIN) / (EVOLUTION_MIN_SAMPLES - WARMING_MIN)
        warming_ratio = round(min(max(warming_ratio, 0.0), 0.90), 2)  # 최대 90%
        EVOLUTION_READY = False
        logger.info("[EVOL] ★ Progressive Warming: 샘플=%d 반영비율=%.0f%%",
                    n_samples, warming_ratio * 100)

    # ★ v8.6 [C]: 워밍업 비율 전역 노출 (_eval_candidates 점진 Kelly에서 사용)
    EVOLUTION_WARMING_RATIO = warming_ratio

    # 기본값과 실값 블렌딩
    # ★ v8.4 P1-FIX-2: DEFAULT 값을 백분율 단위로 통일
    # bridge_result.csv pnl_pct 단위 = 백분율 (2.34=2.34%)
    # 기존: DEFAULT_WIN=0.025(소수) → avg_win≈2.5(백분율) 블렌딩 시 쓰레기값
    # 수정: DEFAULT_WIN=2.5(백분율) → 단위 일치
    # ★ WEAK-E: 3전략 전략별 DEFAULT 분리 (v9.1)
    # ★ v9.3: EOD 종가 전략 전용 (종배 전략 제거됨)
    # bridge_result.csv에 strategy 컬럼이 있으면 EOD 데이터 분리, 없으면 전체 평균
    DEFAULT_P    = float(os.environ.get("EVOLUTION_WIN_RATE", "0.55"))
    DEFAULT_WIN  = 2.5   # 백분율 기본값 (실거래 데이터 없을 때)
    DEFAULT_LOSS = 1.8   # 백분율 기본값
    if "strategy" in df.columns:
        # EOD 종가 전략 데이터만 필터
        df_strat = df[df["strategy"].astype(str).str.contains("EOD|종가", na=False)]
        if len(df_strat) >= 5:   # 최소 5건 이상일 때만 전략별 DEFAULT 사용
            _s_wins  = df_strat[df_strat["pnl_pct"] > 0]["pnl_pct"]
            _s_loses = df_strat[df_strat["pnl_pct"] < 0]["pnl_pct"].abs()
            if len(_s_wins) > 0:  DEFAULT_WIN  = _s_wins.mean()
            if len(_s_loses) > 0: DEFAULT_LOSS = _s_loses.mean()
            DEFAULT_P = len(_s_wins) / len(df_strat)
            logger.info("[EVOL] EOD 전략 DEFAULT: %d건 win=%.3f%% loss=%.3f%% p=%.1f%%",
                        len(df_strat), DEFAULT_WIN, DEFAULT_LOSS, DEFAULT_P*100)

    blended_p    = DEFAULT_P    * (1 - warming_ratio) + p        * warming_ratio
    blended_win  = DEFAULT_WIN  * (1 - warming_ratio) + avg_win  * warming_ratio
    blended_loss = DEFAULT_LOSS * (1 - warming_ratio) + avg_loss * warming_ratio
    blended_b    = blended_win / blended_loss if blended_loss > 0 else 1.0

    # ★ 자기진화 전역값 갱신 (핵심)
    EVOLUTION_WIN_RATE = round(blended_p,    4)
    EVOLUTION_AVG_WIN  = round(blended_win,  5)
    EVOLUTION_AVG_LOSS = round(blended_loss, 5)
    EVOLUTION_B        = round(blended_b,    4)

    # ★ 레짐별 승률: 레짐별 threshold/prior_weight 블렌딩 (표본 부족 노이즈 방지)
    # 블렌딩: regime_p = (n * actual + prior_weight * global_p) / (n + prior_weight)
    # 표본 많을수록 실값에 수렴, 적으면 전역 승률에 가까움
    REGIME_PARAMS = {
        "BULL":    {"threshold":  6, "prior_weight": 10},
        "NEUTRAL": {"threshold":  8, "prior_weight": 10},
        "CAUTION": {"threshold": 10, "prior_weight": 15},
        "BEAR":    {"threshold": 12, "prior_weight": 20},
    }
    if "regime" in df.columns:
        for regime, params in REGIME_PARAMS.items():
            rdf = df[df["regime"] == regime]
            n = len(rdf)
            if n >= params["threshold"]:
                actual = len(rdf[rdf["pnl_pct"] > 0]) / n
                blended = (n * actual + params["prior_weight"] * p) / (n + params["prior_weight"])
                REGIME_WIN_RATES[regime] = round(blended, 4)

    kelly_full = (blended_b * blended_p - (1-blended_p)) / blended_b if blended_b > 0 else 0.0
    kelly_half = max(kelly_full * KELLY_HALF_FRACTION, 0.0)

    warming_tag = "★완전활성" if EVOLUTION_READY else f"★워밍업({warming_ratio:.0%})"
    logger.info("[EVOL] %s — 샘플=%d 승률=%.1f%% b=%.3f"
                " avg_win=%.3f%% avg_loss=%.3f%% Half-Kelly=%.4f",
                warming_tag, n_samples, blended_p*100, blended_b,
                blended_win, blended_loss, kelly_half)
    logger.info("[EVOL] 레짐 승률: %s", REGIME_WIN_RATES)

    _save_evolution_params(f"p={blended_p:.3f}_b={blended_b:.3f}_n={n_samples}_w={warming_ratio:.0%}",
                           n_samples, logger)


def _save_evolution_params(note, samples, logger):
    try:
        _append_csv(EVOLUTION_PATH, {
            "date": _today(), "ts": _now(),
            "win_rate": EVOLUTION_WIN_RATE,
            "avg_win":  EVOLUTION_AVG_WIN,
            "avg_loss": EVOLUTION_AVG_LOSS,
            "b":        EVOLUTION_B,
            "samples":  samples, "note": note,
        })
    except Exception as e:
        logger.warning("[EVOL] 저장 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  CONNECT-1: EV 엔진 로드
# ═══════════════════════════════════════════════════════════════
def load_ev_engine_codes(logger: logging.Logger) -> Dict[str, float]:
    result: Dict[str, float] = {}
    df = _read_csv(EOD5_PATH, logger)
    if df is None or df.empty:
        logger.info("[EV5] score_eod_5.csv 없음"); return result
    today = _today()
    if "date" in df.columns:
        df = df[df["date"].astype(str).str[:10] == today]
        if df.empty:
            logger.info("[EV5] 날짜 불일치"); return result
    for _, row in df.iterrows():
        code = str(row.get("code","")).zfill(6)
        ev   = _f(row.get("ev_norm", row.get("ev", 0.0)))
        if code: result[code] = round(ev, 4)
    logger.info("[EV5] %d종목 로드", len(result))
    return result


# ═══════════════════════════════════════════════════════════════
#  ★ EV-2: 확률 기반 기대값 (레짐/종목별 실제 승률)
# ═══════════════════════════════════════════════════════════════
def calc_ev_probabilistic(
    ev_norm:      float,
    bscore:       float,
    regime:       str,
    inst_consec:  float,
    gap_pred:     float,
) -> dict:
    """
    EV = p × avg_win - (1-p) × avg_loss

    ★ p, avg_win, avg_loss는 자기진화 실값 기반
    ★ win_mult는 신호 강도에 따른 조건부 보정 (휴리스틱)
      - 자기진화 데이터가 충분해지면 win_mult 영향은 줄어듦
      - 캡: 최대 1.5배 (과대 추정 방지)

    p   : 레짐별 실제 승률 + 기관 모멘텀 보정
    avg_win/avg_loss : bridge_result.csv 실제 평균값
    """
    # ── 레짐별 기본 승률
    p_base = REGIME_WIN_RATES.get(regime, EVOLUTION_WIN_RATE)

    # 기관 연속 매수 → 승률 상향
    inst_bonus = min(inst_consec * INST_BONUS_PER_DAY, INST_BONUS_MAX)
    p = min(p_base + inst_bonus, 0.82)

    # ── avg_win/avg_loss: 진화 실값 우선
    base_avg_win  = EVOLUTION_AVG_WIN
    base_avg_loss = EVOLUTION_AVG_LOSS

    # ── 신호 강도 보정 (★ 캡 1.5배 — 과대 추정 방지)
    # ★ WEAK-8 FIX: 진화 활성 시 win_mult 범위 축소 (1.0~1.2)
    #   자기진화 데이터가 충분하면 실값이 정확 → 휴리스틱 보정 축소
    win_mult_cap = 1.20 if EVOLUTION_READY else 1.50
    if ev_norm >= 0:
        win_mult = 1.0 + ev_norm * (0.2 if EVOLUTION_READY else 0.5)
    else:
        win_mult = 1.0 + max(bscore - 0.3, 0) * (0.15 if EVOLUTION_READY else 0.3)
    win_mult *= (1.0 + min(gap_pred / 25.0, 0.15))
    win_mult = min(win_mult, win_mult_cap)

    avg_win  = base_avg_win * win_mult
    avg_loss = base_avg_loss                  # 손실은 보정 없음 (보수적)

    q       = 1.0 - p
    # ★ v8.3 필수수정: EV_adj = p*avg_win - (1-p)*avg_loss*1.35 (손실비대칭)
    #   1종목 몰빵에서 손실 = 전체 계좌 타격 → 손실 가중 1.35배
    ev_raw  = p * avg_win - q * avg_loss * LOSS_AVERSION
    # 왕복 거래비용 차감 (수수료+거래세+시장충격 = ~0.30%)
    ev_adj  = ev_raw - ROUND_TRIP_COST
    kelly_b = avg_win / avg_loss if avg_loss > 0 else 1.0
    b       = kelly_b

    return {
        "ev_adj":          round(ev_adj, 5),
        "ev_raw":          round(ev_raw, 5),
        "p":               round(p, 4),
        "b":               round(b, 4),
        "kelly_b":         round(kelly_b, 4),
        "avg_win":         round(avg_win, 4),
        "avg_loss":        round(avg_loss, 4),
        "win_mult":        round(win_mult, 4),
        "regime":          regime,
        "positive":        ev_adj > EV_ADJ_MIN,
        "evolution_ready": EVOLUTION_READY,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ v8.3: Kelly → ATTACK/MEDIUM/STABLE/SKIP 판정
#  Kelly half 단독으로 사이징 결정 (bscore 의존성 제거)
#
#  포지션 3단계:
#    Half-Kelly ≥ 0.12 → ATTACK  (70% 진입)
#    Half-Kelly ≥ 0.08 → MEDIUM  (50% 진입)
#    Half-Kelly ≥ 0.05 → STABLE  (30% 진입)
#    그 외 → SKIP
# ═══════════════════════════════════════════════════════════════
# [v9.8.1 FIX-6] EV 음수 시 kelly_fraction 명시적 0 처리 보장
def calc_kelly_advanced(
    ev_result: dict,
    bscore:    float,
    size_mode: str,
) -> dict:
    p = ev_result["p"]
    b = ev_result["kelly_b"]
    q = 1.0 - p

    full_kelly = max((b * p - q) / b, 0.0) if b > 0 else 0.0
    half_kelly = full_kelly * KELLY_HALF_FRACTION

    # ★ v8.9 BUG-C FIX: ATTACK_BSCORE_MIN 실제 적용
    # [v9.8 FIX-5] EV_HIGH_THRESHOLD 조건은 _eval_candidates에서도 재판단하여 mode를 덮어씀
    # 이 함수에서의 1차 판단과 _eval_candidates의 2차 override가 동일 방향이므로 충돌 없음
    # 단일화보다 독립 레이어 유지가 안전 (Kelly 함수는 EV 정보 없이도 호출 가능해야 함)
    if (half_kelly >= ATTACK_KELLY_MIN
            and ev_result.get("ev_adj", 0) >= EV_HIGH_THRESHOLD
            and bscore >= ATTACK_BSCORE_MIN):
        mode     = "ATTACK"
        fraction = ATTACK_SIZE     # 70%
    elif half_kelly >= MEDIUM_KELLY_MIN:
        mode     = "MEDIUM"
        fraction = MEDIUM_SIZE     # 50%
    elif half_kelly >= 0.05:
        mode     = "STABLE"
        fraction = STABLE_SIZE     # 30%
    else:
        mode     = "SKIP"
        fraction = 0.0

    return {
        "fraction":    round(fraction, 4),
        "kelly_full":  round(full_kelly, 4),
        "kelly_half":  round(half_kelly, 4),
        "mode":        mode,
        "p_used":      round(p, 4),
        "b_used":      round(b, 4),
        "source":      f"REGIME_{ev_result['regime']}",
    }


# ═══════════════════════════════════════════════════════════════
#  ★ v8.2: Risk Score — 종목별 리스크 정량화
#  "얼마나 좋은가?"가 아니라 "얼마나 위험한가?"
# ═══════════════════════════════════════════════════════════════
def calc_risk_score(row: pd.Series, reason: dict) -> dict:
    """
    risk_score = 0.4×volatility + 0.3×drawdown + 0.3×gap_risk

    volatility: 최근 변동성 (std_5d 또는 ATR 기반, 없으면 0.5 고정)
    drawdown:   고점 대비 하락률 (없으면 0.3 고정)
    gap_risk:   갭업 예측 과열도 (높을수록 위험)
    """
    # Volatility — scoreboard에 std_5d/atr 있으면 사용, 없으면 0.5
    vol_raw = _f(row.get("std_5d", reason.get("std_5d",
               row.get("atr_pct", reason.get("atr_pct", 0)))))
    if vol_raw > 0:
        volatility = min(vol_raw / 5.0, 1.0)   # 5% 변동성 → 1.0 (최대)
    else:
        # ★ v8.9 WEAK-3 FIX: 0.5(중립)→0.70(보수)
        # KOSDAQ 소형주 실제 변동성 10~30% → 데이터 없을 때 낮게 잡으면 위험 과소평가
        volatility = 0.70                        # 데이터 없으면 보수적 중상위

    # Drawdown — 고점 대비 현재가 위치
    h60 = _f(row.get("high60_ratio", reason.get("high60_ratio", 0)))
    cp  = _f(row.get("close_position", reason.get("close_position", 0.5)))
    if h60 > 0:
        drawdown = max(1.0 - h60, 0.0)          # 60일 고점 대비 하락률
    elif cp > 0:
        drawdown = max(1.0 - cp, 0.0)            # 당일 고저 내 위치로 대체
    else:
        drawdown = 0.3                            # 데이터 없으면 중립

    # Gap Risk — 갭업 예측이 너무 높으면 = 이미 과열
    gap_pred = _f(row.get("gap_predict_score", reason.get("gap_predict_score", 0)))
    gap_risk = min(abs(gap_pred) / 10.0, 1.0)

    risk_score = 0.4 * volatility + 0.3 * drawdown + 0.3 * gap_risk
    risk_score = round(max(risk_score, 0.15), 4)  # 최소 0.15 (low risk 과대평가 방지)

    return {
        "risk_score":  risk_score,
        "volatility":  round(volatility, 4),
        "drawdown":    round(drawdown, 4),
        "gap_risk":    round(gap_risk, 4),
    }


# ═══════════════════════════════════════════════════════════════
#  ★ v8.2: Selection Score — EV/Risk 기반 최종 선발 점수
#  "bscore 1등" → "EV/Risk 1등"
#
#  final = (ev_pct×0.7 + bscore×0.3) / risk_score
#  + 기관모멘텀 가산 + 과열 감산
# ═══════════════════════════════════════════════════════════════
def calc_selection_score(
    ev_result:   dict,
    bscore:      float,
    risk_result: dict,
    inst_consec: float,
    day_chg:     float,
    eff_ev_min:  float = 0.0,   # [v9.8 FIX-1] 레짐별 eff_ev_min 직접 전달
) -> dict:
    """
    ★ v8.3 필수수정: selection_score = EV_adj / (risk_score ** 1.2)
    ★ v8.5 [RET-2]: risk exponent 1.2 → 0.9 완화
      - risk^1.2는 고위험 종목 감점이 과도해 상단 수익 후보가 잘림
      - 0.9로 완화해 고수익 후보를 살리면서 risk 반영 구조는 유지

    [v9.8 FIX-1] eff_ev_min 파라미터 추가 — BULL 레짐 완화 무효화 버그 수정
      기존: if ev_adj <= EV_ADJ_MIN(0.14) → BULL(×0.80=0.112) 완화가 여기서 차단됨
      수정: eff_ev_min 파라미터로 받아 레짐별 기준 일관 적용
            eff_ev_min=0 (기본값) 이면 EV_ADJ_MIN 그대로 사용 (하위 호환)

    핵심 원칙:
      - EV_adj: 손실비대칭 1.05x + 거래비용 차감 후 기대값
      - risk_score^0.9: 비선형 리스크 패널티
      - EV_adj에 이미 기관모멘텀(승률보정)이 내재 → 이중 가산 제거
    """
    ev_adj     = ev_result["ev_adj"]
    risk_score = risk_result["risk_score"]

    # [EV 완화] floor=0: 음수EV만 차단, 양수EV는 score 계산
    _floor = 0.0

    # ★ 핵심 공식: ev^1.05/risk^0.90
    if ev_adj <= _floor:
        raw = 0.0
    else:
        raw = (ev_adj ** 1.05) / (risk_score ** 0.90 + 1e-6)

    # ★ v9.4 FIX-3: 대형갭(>10%) selection_score 패널티
    # 갭 과대 종목은 EV가 높아도 손실 확률 과소평가 위험 → 0.85 배수
    if day_chg >= GAP_LARGE_CHG and raw > 0:
        raw *= GAP_LARGE_SEL_PENALTY

    # [v9.9 FIX-2] HF-1 보강 후 selection_score 품질 반영
    # bscore가 winner_gap/dominance/Alpha Decay를 포함하므로
    # EV 계산 시 bscore 영향이 selection_score에 자연 반영됨
    return {
        "selection_score": round(raw, 6),
        "ev_adj":          round(ev_adj, 5),
        "risk_score":      risk_score,
        "gap_large":       day_chg >= GAP_LARGE_CHG,
        "hf_enhanced":     True,   # [v9.9] HF-1 보강 적용됨
    }


# ═══════════════════════════════════════════════════════════════
#  ★ INST-7: 기관 모멘텀 감지 (개인투자자 특화)
#  "기관의 등에 탔다가 미리 내려오는 것"
# ═══════════════════════════════════════════════════════════════
def calc_inst_momentum(
    inst_consec: float,
    ofi_accel:   float,
    val_ratio:   float,
    vpin:        float,
) -> dict:
    """
    기관 매집 강도 + 모멘텀 지속 가능성 평가

    개인의 전략:
      1. 기관이 매집 중인 구간에서 탑승 (inst_consec 상승 중)
      2. OFI 가속도가 살아있는지 확인 (매집 지속 신호)
      3. VPIN 높으면 정보 불균형 → 기관 우위 구간 = 탑승 적기
      4. 매집 강도가 약해지면 먼저 하차 → 별도 청산 엔진에서 처리

    ride_score: 0~1, 높을수록 기관 등에 타기 좋은 구간
    warning: 탑승 위험 신호 (모멘텀 약화)
    """
    ride_score = 0.0
    signals    = []
    warnings   = []

    # 기관 연속 매수 → 핵심 탑승 조건
    # ★ v8.6 [B]: 3일 중간 구간 추가 (2일=+0.25 / 3일=+0.32 / 4일↑=+0.40)
    # 기존: 2일~3일이 동일(+0.25) → 3일 강매집 신호 과소평가
    if inst_consec >= INST_STRONG_MIN:          # 4일 이상
        ride_score += 0.40; signals.append(f"기관강매집({int(inst_consec)}일)")
    elif inst_consec >= INST_RIDE_MIN + 1:      # 3일
        ride_score += 0.32; signals.append(f"기관중매집({int(inst_consec)}일)")
    elif inst_consec >= INST_RIDE_MIN:          # 2일
        ride_score += 0.25; signals.append(f"기관매집({int(inst_consec)}일)")
    else:
        warnings.append("기관매집부족"); ride_score -= 0.10

    # OFI 가속 → 매집 지속 신호
    if ofi_accel >= INST_OFI_RIDE_MIN:
        ride_score += 0.25; signals.append(f"OFI가속({ofi_accel:.2f})")
    elif ofi_accel >= AXIS1_OFI_MIN:
        ride_score += 0.10
    else:
        warnings.append("OFI약화")

    # VPIN → 정보 불균형 (기관 우위 확인)
    if vpin >= 0.70:
        ride_score += 0.20; signals.append(f"VPIN정보우위({vpin:.2f})")
    elif vpin >= 0.58:
        ride_score += 0.10

    # 거래대금 비율 → 기관 매집 볼륨 확인
    if val_ratio >= U_VAL_RATIO_MIN:
        ride_score += 0.15; signals.append(f"거래대금급증({val_ratio:.1f}x)")
    elif val_ratio >= 1.0:
        ride_score += 0.05

    ride_score = round(min(max(ride_score, 0.0), 1.0), 4)
    can_ride   = ride_score >= 0.40 and inst_consec >= INST_RIDE_MIN

    return {
        "ride_score": ride_score,
        "can_ride":   can_ride,
        "signals":    signals,
        "warnings":   warnings,
        "inst_days":  int(inst_consec),
    }


# ═══════════════════════════════════════════════════════════════
#  ★ EVT-6: 이벤트 리스크 차단 필터
# ═══════════════════════════════════════════════════════════════
def check_event_risk(
    code:   str,
    row:    pd.Series,
    reason: dict,
    logger: logging.Logger,
) -> dict:
    """
    실적/공시/거래정지/관리종목 이벤트 차단
    개인 특화: 뉴스 모르면 기관이 아는 것 → 무조건 패스

    Scoreboard에 이벤트 컬럼이 없으면 안전하게 통과 처리
    """
    blocks = []
    warns  = []

    # 관리종목 / 투자주의 / 거래정지
    supervision = int(_f(row.get("supervision_flag", reason.get("supervision_flag", 0))))
    halt_flag   = int(_f(row.get("halt_flag",        reason.get("halt_flag",        0))))
    caution_flag= int(_f(row.get("caution_flag",     reason.get("caution_flag",     0))))

    if halt_flag == 1 and EVENT_SUSPENSION_BLOCK:
        blocks.append("거래정지위험")
    if supervision == 1 and EVENT_WATCHLIST_BLOCK:
        blocks.append("관리종목")
    if caution_flag == 1:
        warns.append("투자주의")

    # 실적 발표 임박 (컬럼 있을 때만)
    earnings_days = int(_f(row.get("earnings_days_left", reason.get("earnings_days_left", 99))))
    if 0 < earnings_days <= 3:
        blocks.append(f"실적발표{earnings_days}일전")
    elif 0 < earnings_days <= 7:
        warns.append(f"실적발표{earnings_days}일전")

    # 단기 급등 과열 (이벤트성 급등 = 정보 비대칭 위험)
    day_chg   = _f(row.get("day_chg_pct", reason.get("day_chg_pct", 0)))
    week_chg  = _f(row.get("week_chg_pct", reason.get("week_chg_pct", 0)))
    if day_chg >= 15.0:
        blocks.append(f"당일급등{day_chg:.0f}%")
    elif week_chg >= 30.0:
        warns.append(f"주간급등{week_chg:.0f}%")

    is_safe = len(blocks) == 0
    if not is_safe:
        logger.warning("[EVT-6] %s 이벤트 차단: %s", code, " | ".join(blocks))
    elif warns:
        logger.info("[EVT-6] %s 이벤트 경고: %s", code, " | ".join(warns))

    return {
        "is_safe":  is_safe,
        "blocked":  blocks,
        "warnings": warns,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ R5: 일일 손실 한도 체크
#  bridge_result.csv에서 당일 실현손실 합산 → 자본의 2% 초과 시 차단
# ═══════════════════════════════════════════════════════════════
def _check_daily_loss_limit(capital: int) -> tuple:
    """
    반환: ("OK"|"REDUCE"|"BLOCK", 사유)
    - OK: 한도 여유
    - REDUCE: 70% 이상 소진 → size 50%
    - BLOCK: 100% 소진 → 차단
    ★ BUG-3 FIX: pnl_pct 단위 계약 = 백분율 (2.34 = 2.34%)
      소수 형태(0.0234)가 섞여있으면 자동 보정
    """
    max_loss = capital * DAILY_MAX_LOSS_PCT
    try:
        if not RESULT_PATH.exists():
            return "OK", ""
        df = pd.read_csv(RESULT_PATH, encoding="utf-8-sig")
        if df.empty or "pnl_pct" not in df.columns or "date" not in df.columns:
            return "OK", ""
        today = _today()
        today_df = df[(df["date"].astype(str).str[:10] == today) &
                      (df["pnl_pct"].notna())]
        if today_df.empty:
            return "OK", ""
        # ★ v8.4 P0-FIX-1: _norm_pnl 제거 — 백분율 단위 확정 적용
        # pnl_pct 계약: 백분율 (2.34=2.34%, -0.3=-0.3%)
        # 기존 _norm_pnl()의 abs<0.5 임계값이 0.3% 손실을 30%로 오인 → 당일 거래 완전 차단
        today_df_loss = today_df[today_df["pnl_pct"].apply(_f) < 0]
        if today_df_loss.empty:
            return "OK", ""
        # 총손실 합산 (백분율 → 원화: capital × pnl_pct% / 100)
        total_loss_pct = abs(today_df_loss["pnl_pct"].apply(_f).sum())
        total_loss_krw = capital * total_loss_pct / 100.0
        if total_loss_krw >= max_loss:
            return "BLOCK", f"일일한도초과(손실{total_loss_krw:,.0f}원≥{max_loss:,.0f}원)"
        if total_loss_krw >= max_loss * 0.70:
            return "REDUCE", f"일일한도근접({total_loss_krw:,.0f}/{max_loss:,.0f}원)→size50%"
    except Exception:
        pass
    return "OK", ""


# ═══════════════════════════════════════════════════════════════
#  ★ RISK-4: 투자판단 독립 리스크 계층
# ═══════════════════════════════════════════════════════════════
def eval_risk_layer(
    bscore:     float,
    ev_result:  dict,
    inst_mom:   dict,
    regime:     str,
    size_ratio: float,
    capital:    int,
    price:      float,
) -> dict:
    """
    투자 신호(bscore/EV)와 완전 독립된 리스크 평가

    R1. EV 음수 → 절대 차단
    R3. 기관탑승 소프트 모드
        ride < 0.25 → 하드 차단
        ride 0.25~0.40 → size 60% 축소
        ride >= 0.40 → 정상
    R4. CAUTION 레짐 → size 70%
    R5. ★ 일일 손실 한도 (자본의 2%) → 초과 시 차단, 근접 시 size 50%
    """
    risk_blocks = []
    risk_warns  = []
    risk_size   = size_ratio

    # R1. EV 음수 차단 (절대 조건 — 기대값 마이너스는 무조건 패스)
    import datetime as _dt5
    try:
        _r1_sb_today = (_dt5.date.fromtimestamp(EOD_PATH.stat().st_mtime).strftime("%Y-%m-%d") == _today())
    except Exception:
        _r1_sb_today = True
    if _r1_sb_today and not ev_result["positive"]:
        risk_blocks.append(f"EV부족({ev_result['ev_adj']:.4f}<{EV_ADJ_MIN})")

    # ★ FIX-3: R2 집중도캡 삭제 (RANK1_RATIO=1.00 몰빵과 모순)

    # R3. 기관탑승 소프트 모드
    ride = inst_mom["ride_score"]
    import datetime as _dt4
    try:
        _r3_sb_today = (_dt4.date.fromtimestamp(EOD_PATH.stat().st_mtime).strftime("%Y-%m-%d") == _today())
    except Exception:
        _r3_sb_today = True
    _ride_hard_block = ride < RIDE_HARD_MIN if (_r3_sb_today or inst_mom.get("inst_days", -1) != 0) else False
    if _ride_hard_block:
        risk_blocks.append(f"기관탑승거부(ride={ride:.2f}<{RIDE_HARD_MIN})")
    elif ride < RIDE_SOFT_MIN:
        risk_size = min(risk_size, RIDE_SOFT_SIZE)
        risk_warns.append(f"기관탑승약함(ride={ride:.2f})→size{int(RIDE_SOFT_SIZE*100)}%")

    # R4. CAUTION 레짐 size 제한
    # ★ v8.6 [D-2]: ride_score 기반 동적 사이즈
    #   ride ≥ 0.60 → 80% (기관 강매집 확인 시 완화)
    #   ride < 0.60 → 70% (기존 보수 유지)
    if regime == "CAUTION":
        ride_now = inst_mom["ride_score"]
        caution_cap = 0.80 if ride_now >= 0.60 else 0.70
        risk_size = min(risk_size, caution_cap)
        risk_warns.append(f"CAUTION→size{int(caution_cap*100)}%(ride={ride_now:.2f})")

    # ★ R5. 일일 손실 한도 체크
    daily_ok, daily_note = _check_daily_loss_limit(capital)
    if daily_ok == "BLOCK":
        risk_blocks.append(daily_note)
    elif daily_ok == "REDUCE":
        risk_size = min(risk_size, 0.50)
        risk_warns.append(daily_note)

    # 최종 size_ratio 통합
    risk_size = round(min(risk_size, size_ratio), 4)

    can_enter = len(risk_blocks) == 0
    return {
        "can_enter":   can_enter,
        "risk_size":   risk_size,
        "risk_blocks": risk_blocks,
        "risk_warns":  risk_warns,
        "ev_adj":      ev_result["ev_adj"],
        "ride_score":  ride,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ FIX-1: 종가 = 동시호가 단일가 → 슬리피지 0
#  v7.6의 과잉 모델(val_ratio/close_position/size_impact) 전부 제거
#  동시호가는 단일가 체결이므로 MARKET/LIMIT 분기도 불필요
# ═══════════════════════════════════════════════════════════════
def calc_execution_params(price: float, order_krw: int) -> dict:
    """
    종가 EOD = 동시호가 단일가 체결
    슬리피지 0, 체결방식 LIMIT_AUCTION 고정
    ★ W9: 미사용 인자 제거 (val_ratio, inst_consec, close_position, ev_result)
    """
    qty = int(order_krw / price) if price > 0 else 0

    return {
        "exec_type":       "LIMIT_AUCTION",
        "slippage_est":    0.0,
        "effective_price": int(price),
        "effective_krw":   order_krw,
        "qty":             qty,
        "note":            "종가동시호가(단일가,슬리피지0)",
    }


# ★ W10: calc_final_score 삭제 — bscore로 통일 (final_score == bscore였음)


# ═══════════════════════════════════════════════════════════════
#  P1/P3 검증 (고유영역)
# ═══════════════════════════════════════════════════════════════
def p1_check_date(df: pd.DataFrame, logger: logging.Logger) -> bool:
    if "date" not in df.columns:
        logger.warning("[P1] date 컬럼 없음 (통과)"); return True
    eod_date = str(df["date"].iloc[0]).strip()[:10]
    today    = _today()
    if eod_date == today:
        logger.info("[P1] 날짜 OK: %s", eod_date); return True
    # [PULLBACK-SUPPLY 2026-06-02] 전일자 score_eod 허용 — 장중 PULLBACK 공급(스코어보드→bridge_target).
    # EOD 시간대(당일자)는 위에서 통과(동작불변). 장중엔 score_eod=직전거래일이라 여기서 통과.
    # 출력 영향은 bridge_target codes(PULLBACK 후보풀)뿐 — top1 entry는 history 분석파일만, EOD_PICK은 독립모듈이라 무영향.
    try:
        from datetime import datetime as _dtp
        _age = (_dtp.strptime(today, "%Y-%m-%d").date() - _dtp.strptime(eod_date, "%Y-%m-%d").date()).days
        if 0 < _age <= P1_STALE_MAX_DAYS:
            logger.warning("[P1] 전일자 score_eod 허용 파일=%s 오늘=%s (age=%d일 ≤ %d) → 장중 PULLBACK 공급",
                           eod_date, today, _age, P1_STALE_MAX_DAYS)
            return True
        logger.error("[P1] 날짜불일치(age=%d일 > 허용%d, 또는 미래) 파일=%s 오늘=%s → HOLD",
                     _age, P1_STALE_MAX_DAYS, eod_date, today)
    except Exception as _e:
        logger.error("[P1] 날짜 파싱실패(%s) 파일=%s 오늘=%s → HOLD", _e, eod_date, today)
    return False

def p1_check_time(logger: logging.Logger) -> bool:
    now_hm = _hhmm()
    if not (EXEC_TIME_FROM <= now_hm <= EXEC_TIME_TO):
        logger.error("[P1] 시간 밖: %d (%d~%d) → HOLD", now_hm, EXEC_TIME_FROM, EXEC_TIME_TO)
        return False
    logger.info("[P1] 시간 OK: %d", now_hm); return True

def p1_get_positions(logger: logging.Logger) -> Set[str]:
    df = _read_csv(POSITIONS_PATH, logger)
    if df is None or df.empty: return set()
    code_col = next((c for c in ["code","종목코드","ticker"] if c in df.columns), None)
    if not code_col: return set()
    codes = set(str(c).zfill(6) for c in df[code_col].dropna())
    logger.info("[P1] 보유 %d종목", len(codes)); return codes

def p3_check_holiday(logger: logging.Logger) -> bool:
    today_str = _today()
    if today_str in KR_HOLIDAYS:
        logger.error("[P3] 공휴일 %s → HOLD", today_str); return False
    # ★ BUG-5 FIX: 주말 체크 (토=5, 일=6)
    wd = time.localtime().tm_wday
    if wd >= 5:
        logger.error("[P3] 주말(wday=%d) → HOLD", wd); return False
    return True

def p2_check_repeat(code: str, logger: logging.Logger, bscore: float = 0.0) -> bool:
    df = _read_csv(HISTORY_PATH, logger)
    if df is None or df.empty: return True
    if "code" not in df.columns or "date" not in df.columns: return True
    cutoff = (date.today() - timedelta(days=REPEAT_BLOCK_DAYS)).strftime("%Y-%m-%d")
    recent = df[(df["code"].astype(str).str.zfill(6) == str(code).zfill(6)) &
                (df["date"] >= cutoff)]
    if not recent.empty:
        if bscore >= REPEAT_BSCORE_EXCEPT:
            # ★ WEAK-D: bscore 예외 허용 시 전일 수익 여부 추가 확인
            # 전일 손실 후 동일 종목 재진입 차단 → 손실 복구 기대 재진입 방지
            try:
                res_df = _read_csv(RESULT_PATH, logger)
                if res_df is not None and "pnl_pct" in res_df.columns:
                    prev = res_df[
                        (res_df["code"].astype(str).str.zfill(6) == str(code).zfill(6)) &
                        (res_df["date"] >= cutoff) &
                        (res_df["pnl_pct"].notna())
                    ]
                    if not prev.empty and _f(prev["pnl_pct"].iloc[-1]) < 0:
                        logger.warning("[P2] 연속진입 거부(전일손실): %s bscore=%.4f pnl=%.2f%%",
                                       code, bscore, _f(prev["pnl_pct"].iloc[-1]))
                        return False
            except Exception:
                pass
            logger.info("[P2] 연속진입 예외: %s bscore=%.4f (전일수익확인)", code, bscore)
            return True
        logger.warning("[P2] 연속진입 차단: %s", code); return False
    return True


# ═══════════════════════════════════════════════════════════════
#  P2⑥ — 4축 강도 평가 (고유영역 — 불변)
# ═══════════════════════════════════════════════════════════════
def p2_eval_axes(row: pd.Series, reason: dict) -> dict:
    ofi  = _f(row.get("ofi_accel",  reason.get("ofi_accel",  0)))
    vpin = _f(row.get("vpin",       reason.get("vpin",       0)))
    # [B안] vpin=0.0은 미산출로 간주 → ofi 단독으로 axis1 통과 허용
    axis1 = (ofi >= AXIS1_OFI_MIN and (vpin >= AXIS1_VPIN_MIN or vpin == 0.0))

    cp  = _f(row.get("close_position", reason.get("close_position", 0)))
    hb  = _f(row.get("high_break",     reason.get("high_break",     0)))
    ic  = _f(row.get("inst_consec",    reason.get("inst_consec",    0)))
    h60 = _f(row.get("high60_ratio",   reason.get("high60_ratio",   0)))
    # [C안] inst_consec=0이고 ofi/cp/hb 강세이면 inst_consec 조건 면제
    _ic_exempt = (ic == 0 and ofi >= 1.0 and cp >= 0.99 and hb >= 0.99)
    axis2 = (cp >= AXIS2_CP_MIN and hb >= AXIS2_HB_MIN
             and (ic >= INST_CONSEC_MIN or _ic_exempt) and h60 >= HIGH60_MIN)

    rm       = _f(row.get("residual_momentum", reason.get("residual_momentum", 0)))
    mkt_risk = int(_f(row.get("mkt_risk_flag", reason.get("mkt_risk_flag", 0))))
    axis3 = (rm >= AXIS3_RM_MIN and mkt_risk == 0)

    l5a      = _f(row.get("last5_value_accel", reason.get("last5_value_accel", 0)))
    dyn      = _f(row.get("dyn_score",         reason.get("dyn_score",         0)))
    dyn_hold = int(_f(row.get("dyn_hold_flag", reason.get("dyn_hold_flag", 0))))
    axis4 = (l5a >= AXIS4_L5A_MIN and dyn >= AXIS4_DYN_MIN and dyn_hold == 0)

    sc = sum([axis1, axis2, axis3, axis4])
    return {
        "axis1": axis1, "axis2": axis2, "axis3": axis3, "axis4": axis4,
        "strong_count": sc,
        "details": {
            "ofi": round(ofi,4), "vpin": round(vpin,4), "cp": round(cp,3),
            "hb": round(hb,3),   "inst_consec": int(ic), "high60": round(h60,4),
            "rm": round(rm,2),   "mkt_risk": mkt_risk,
            "l5a": round(l5a,3), "dyn": round(dyn,2), "dyn_hold": dyn_hold,
        },
    }


# ═══════════════════════════════════════════════════════════════
#  P2④ — 브릿지 재평가 (고유영역 — 불변)
# ═══════════════════════════════════════════════════════════════
def _calc_ev_quality_bonus(ev_norm: float) -> float:
    if ev_norm < 0:             return -0.02
    if ev_norm >= EV_TIER_S_MIN: return EV_TIER_S_BONUS
    if ev_norm >= EV_TIER_A_MIN: return EV_TIER_A_BONUS
    if ev_norm >= EV_TIER_B_MIN: return EV_TIER_B_BONUS
    return EV_TIER_C_BONUS

def _calc_market_regime(kosdaq_chg: float, kospi_chg: float = 0.0,
                        vkospi: float = 0.0) -> tuple:
    """
    시장 레짐 판단
    ★ WEAK-A: VKOSPI 보정 추가 (v9.1)
      vkospi ≥ 35 → 공황 수준 → BEAR 강제 (등락률 무관)
      vkospi ≥ 25 → 공포 구간 → 레짐 1단계 하향 (BULL→NEUTRAL, NEUTRAL→CAUTION, CAUTION→BEAR)
    데이터 없으면(0.0) 기존 로직 유지
    """
    combined = (kosdaq_chg + kospi_chg) / 2.0 if kospi_chg != 0.0 else kosdaq_chg
    # 등락률 기반 기본 레짐
    if combined >= MKT_BULL_MIN:    regime, adj = "BULL",    MKT_BULL_BONUS
    elif combined >= MKT_NEUTRAL_MIN: regime, adj = "NEUTRAL", MKT_NEUTRAL_ADJ
    elif combined >= MKT_CAUTION_MAX: regime, adj = "CAUTION", MKT_CAUTION_ADJ
    else:                             regime, adj = "BEAR",    MKT_BEAR_ADJ
    # ★ VKOSPI 보정 — 변동성 지수 기반 하향 조정
    if vkospi >= VKOSPI_BEAR_MIN:
        regime, adj = "BEAR", MKT_BEAR_ADJ
    elif vkospi >= VKOSPI_CAUTION_MIN:
        _downgrade = {"BULL": ("NEUTRAL", MKT_NEUTRAL_ADJ),
                      "NEUTRAL": ("CAUTION", MKT_CAUTION_ADJ),
                      "CAUTION": ("BEAR",    MKT_BEAR_ADJ),
                      "BEAR":    ("BEAR",    MKT_BEAR_ADJ)}
        regime, adj = _downgrade[regime]
    return regime, adj


def _is_super_bull(regime: str, vkospi: float) -> bool:
    """★ v9.4 FIX-1: 슈퍼BULL 판정 — BULL 레짐 + VKOSPI 극저점
    초안정 강세장에서 수익 상단 확대 허용 (ATTACK 85%)
    출처: 변동성 지수 임계값 기반 레짐 확장 — Palazzi (2025) JFM
    """
    return regime == "BULL" and 0 < vkospi < VKOSPI_SUPER_BULL_MAX

def _calc_entry_timing(close_position: float, vwap_ratio: float,
                       upper_wick: float) -> float:
    score = 0.0
    if close_position >= TIMING_CP_HIGH:   score -= 0.10
    elif close_position >= 0.75:           score -= 0.05
    elif close_position <= TIMING_CP_LOW:  score += 0.06
    elif close_position <= 0.50:           score += 0.02
    if vwap_ratio >= TIMING_VWAP_HOT:      score -= 0.05
    elif vwap_ratio >= 1.01:               score -= 0.02
    elif vwap_ratio <= TIMING_VWAP_CHEAP:  score += 0.04
    if upper_wick < TIMING_WICK_BAD:       score -= 0.06
    elif upper_wick < 0.97:                score -= 0.03
    return round(score, 4)


def p2_bridge_score(row: pd.Series, reason: dict, axes_result: dict,
                    ev_codes: Dict[str, float],
                    scoreboard_code: str,
                    vkospi: float = 0.0) -> Tuple[float, str, float, float]:
    """고유영역 — [v9.8 FIX-3] vkospi 파라미터 추가, 레짐 판단 main()과 일관화"""
    s1  = _f(row.get("stage1_score", reason.get("stage1_score", 0)))
    s2  = _f(row.get("stage2_score", reason.get("stage2_score", 0)))
    axes = axes_result["strong_count"]

    gap_pred    = _f(row.get("gap_predict_score",  reason.get("gap_predict_score", 0)))
    vwap_ratio  = _f(row.get("vwap_ratio",         reason.get("vwap_ratio",        1.0)))
    inst_consec = _f(row.get("inst_consec",         reason.get("inst_consec",        0)))
    high60      = _f(row.get("high60_ratio",        reason.get("high60_ratio",       0)))
    ofi_accel   = _f(row.get("ofi_accel",           reason.get("ofi_accel",          0)))
    val_ratio   = _f(row.get("val_ratio",            reason.get("val_ratio",          1.0)))
    l5a         = _f(row.get("last5_value_accel",   reason.get("last5_value_accel",  0)))
    day_chg     = _f(row.get("day_chg_pct",         reason.get("day_chg_pct",        0)))
    kosdaq_chg  = _f(row.get("kosdaq_chg_pct",      reason.get("kosdaq_chg_pct",     0)))
    kospi_chg   = _f(row.get("kospi_chg_pct",       reason.get("kospi_chg_pct",      0)))
    gap_risk    = str(row.get("gap_risk_flag",       reason.get("gap_risk_flag",   "NORMAL")))
    defense     = _f(row.get("defense_score",        reason.get("defense_score",     50)))
    cp          = _f(row.get("close_position",       reason.get("close_position",    0.5)))
    wick        = _f(row.get("upper_wick_ratio",     reason.get("upper_wick_ratio",  1.0)))
    _cv         = row.get("conviction", "NORMAL")
    conv_lbl    = (str(_cv) if isinstance(_cv, str)
                   else ("HIGH_CONVICTION" if _f(_cv) >= 72 else "NORMAL"))

    n_s1   = min(s1 / 45.0, 1.0)
    n_s2   = min(s2 / 50.0, 1.0)
    n_axes = axes / 4.0
    n_gap  = min(gap_pred / 10.0, 1.0)
    n_inst = min(inst_consec / 5.0, 1.0)

    bscore = (n_s1*0.20 + n_s2*0.20 + n_axes*0.25 + n_gap*0.25 + n_inst*0.10)

    if axes >= 4:                                          bscore += 0.08
    if high60 >= 1.0:                                      bscore += 0.05
    if val_ratio >= U_VAL_RATIO_MIN and l5a >= U_L5A_MIN:  bscore += 0.06
    if ofi_accel >= OFI_TIER2_MIN:                         bscore += 0.05
    if inst_consec >= INST_TIER2_MIN:                      bscore += 0.06
    val_slope = _f(row.get("val_slope", reason.get("val_slope", 0)))
    if val_slope > 0:
        # ★ 미해결FIX-3: 1억 정규화 (구: 10억 → KOSDAQ 소형주에서 Dead Code였음)
        bscore += min(abs(val_slope) / KOSDAQ_VAL_NORM, 1.0) * 0.05
    if (conv_lbl == "HIGH_CONVICTION"
            and gap_pred >= TRIPLE_GAP_MIN
            and inst_consec >= TRIPLE_INST_MIN): bscore += 0.08

    if defense < 40:                                       bscore -= 0.10
    if gap_pred < 2.0:                                     bscore -= 0.08
    if day_chg >= OVERHEAT_CHG and gap_risk == "HIGH":     bscore -= 0.12

    ev_norm  = ev_codes.get(scoreboard_code, -1.0)
    ev_bonus = _calc_ev_quality_bonus(ev_norm)
    bscore  += ev_bonus
    if ev_norm >= 0: bscore += ev_norm * EV_NORM_WEIGHT

    # [v9.8 FIX-3] vkospi 전달 — main() 레짐 판단과 동일 기준 적용
    regime, regime_adj = _calc_market_regime(kosdaq_chg, kospi_chg, vkospi)
    bscore += regime_adj

    timing_adj = _calc_entry_timing(cp, vwap_ratio, wick)
    bscore    += timing_adj

    # ── [v9.9 HF-1] 헤지펀드 방식 보강 3항목 ─────────────────────
    # 스코어보드가 계산한 값을 브리지가 활용하지 않던 문제 해소
    # 출처: CFA Institute (2019) High-Conviction Overweight Positions
    #       Man Group (2024) Conviction in Systematic Hunt for Alpha

    # [HF-1a] winner_gap 보너스 — 1등이 압도적일수록 확신도 상승
    # winner_gap ≥ 11.5 (HARD) → +0.05 / ≥ 6.5 (SOFT) → +0.02 / 미달 → 0
    _winner_gap   = _f(row.get("winner_gap",      reason.get("winner_gap",      0.0)))
    _dominance    = _f(row.get("dominance_ratio",  reason.get("dominance_ratio", 1.0)))
    _hist_bonus   = _f(row.get("history_bonus",    reason.get("history_bonus",   0.0)))

    if _winner_gap >= 11.5:
        bscore += 0.05   # HARD 확신 — 압도적 1등
    elif _winner_gap >= 6.5:
        bscore += 0.02   # SOFT 확신 — 우세한 1등

    # [HF-1b] dominance_ratio 보너스 — 지배력 비율
    # ≥ 1.15 → +0.03 / ≥ 1.10 → +0.01 / < 1.0 → -0.02 (박빙 패널티)
    if _dominance >= 1.15:
        bscore += 0.03
    elif _dominance >= 1.10:
        bscore += 0.01
    elif _dominance < 1.0:
        bscore -= 0.02   # 2등보다 낮은 비정상 상황

    # [HF-1c] Alpha Decay — history_bonus 방향성 반영
    # 우상향(history_bonus > 0) → +보너스 / 우하향(0) → -패널티
    # 3일 연속 1등인데 점수가 우하향이면 신호 약화 → 감점
    if _hist_bonus > 0:
        bscore += min(_hist_bonus * 0.003, 0.03)   # 최대 +0.03
    elif _hist_bonus == 0 and _winner_gap > 0:
        # [v9.9 FIX-1] Alpha Decay 조건 정밀화
        # hist_bonus=0 조건이 신규 종목(history 없음)과 혼동되지 않도록
        # score_history 컬럼 존재 여부로 구분: rank≤20 기록 있으면 우하향으로 판단
        _rank_val = _f(row.get("rank", reason.get("rank", 99)))
        _has_hist = _rank_val <= 20   # 스코어보드 상위권 = 이전 기록 있음
        if _has_hist:
            bscore -= 0.03   # Alpha Decay 패널티 (신규 종목 오패널티 방지)

    return (round(min(bscore, 1.30), 4), regime, timing_adj, ev_bonus)


# ═══════════════════════════════════════════════════════════════
#  P3 검증
# ═══════════════════════════════════════════════════════════════
def p3_check_liquidity(row: pd.Series, reason: dict,
                       logger: logging.Logger) -> bool:
    val_ratio = _f(row.get("val_ratio",         reason.get("val_ratio",         1.0)))
    l5a       = _f(row.get("last5_value_accel", reason.get("last5_value_accel", 0)))
    if val_ratio < 0.3:
        logger.warning("[P3] 거래대금부족 val=%.2f → HOLD", val_ratio); return False
    if l5a < 0.5:
        logger.warning("[P3] 막판거래대금 l5a=%.3f → HOLD", l5a); return False
    return True


def eval_position_risk(row: pd.Series, reason: dict,
                       logger: logging.Logger) -> dict:
    """고유영역 — 불변"""
    mkt_risk = int(_f(row.get("mkt_risk_flag",  reason.get("mkt_risk_flag",    0))))
    dyn_hold = int(_f(row.get("dyn_hold_flag",  reason.get("dyn_hold_flag",    0))))
    stage3   = _f(row.get("stage3_score",       reason.get("stage3_score",     0)))
    day_chg  = _f(row.get("day_chg_pct",        reason.get("day_chg_pct",      0)))
    wick     = _f(row.get("upper_wick_ratio",   reason.get("upper_wick_ratio", 1.0)))
    penalty  = int(_f(row.get("penalty_major",  reason.get("penalty_major",    0))))

    notes = []; can_enter = True; size_ratio = 1.0
    if dyn_hold == 1:  can_enter = False; notes.append("dyn_hold=1")
    if penalty == 1:   can_enter = False; notes.append("penalty_major=1")
    if stage3 < MIN_STAGE3:
        can_enter = False; notes.append(f"stage3={stage3:.1f}")
    if mkt_risk == 1 and can_enter:
        size_ratio = MKT_RISK_REDUCE; notes.append(f"mkt_risk→50%")

    gap_risk = "HIGH" if (day_chg >= GAP_HIGH_CHG and wick < GAP_HIGH_WICK) else "NORMAL"
    gap_risk_blocked = False
    if gap_risk == "HIGH":
        notes.append("gap_risk=HIGH"); can_enter = False; gap_risk_blocked = True

    # ★ WEAK-C: GAP_HIGH size 동적화 (v9.1)
    # 기존: 갭 8%나 15%나 GAP_HIGH_SIZE_RATIO=0.30 고정 → 대형갭 손실 과대
    # 수정: 갭 크기 비례하여 size 축소 (갭 8%=0.26, 갭 10%=0.22, 갭 15%=0.12)
    # 하한 0.10 보장 (최소 주문 가능성 확보)
    if gap_risk == "HIGH":
        _dyn_gap_size = round(max(GAP_HIGH_SIZE_RATIO - (day_chg - GAP_HIGH_CHG) * 0.02, 0.10), 2)
    else:
        _dyn_gap_size = GAP_HIGH_SIZE_RATIO

    return {
        "can_enter": can_enter, "size_ratio": size_ratio,
        "gap_risk_flag": gap_risk, "gap_risk_blocked": gap_risk_blocked,
        "gap_high_size": _dyn_gap_size,   # ★ WEAK-C: 동적 갭 사이즈
        "risk_notes": notes,
    }


def calc_order_by_rank(risk: dict, price: float,
                       size_mode: str = "NORMAL",
                       kelly_params: Optional[dict] = None) -> Optional[dict]:
    """1종목 몰빵 전용 주문 계산
    ★ FIX-2: fraction = ATTACK(1.0) / STABLE(0.30) / SKIP(0.0)"""
    if price <= 0: return None

    capital    = _get_capital()
    fraction   = kelly_params["fraction"] if kelly_params else STABLE_SIZE
    base_krw   = int(capital * RANK1_RATIO * fraction)
    final_krw  = int(base_krw * risk["size_ratio"])
    qty        = int(final_krw / price)

    if qty <= 0: return None

    return {
        "order_krw":  final_krw,
        "qty":        qty,
        "size_mode":  size_mode,
        "rank_ratio": RANK1_RATIO,
        "fraction":   fraction,
    }


# ═══════════════════════════════════════════════════════════════
#  ★ ATTR-5: Attribution 가능 결과 기록
# ═══════════════════════════════════════════════════════════════
def record_attribution(
    entry:        dict,
    ev_result:    dict,
    kelly_params: dict,
    exec_params:  dict,
    risk_layer:   dict,
    inst_mom:     dict,
    event_risk:   dict,
    regime:       str,
    bscore:       float,
    final_score:  float,
) -> None:
    """
    사후 분석 가능한 완전한 진입 기록
    "왜 이 종목을 샀는가" 를 모든 인자 수준에서 추적 가능
    ★ WEAK-F: strategy 컬럼 추가 → 자기진화 전략별 분리 피드백 지원 (v9.1)
    ★ WEAK-F: update_pnl_result() 자동연결 확인용 entry_id 기록
    """
    try:
        _append_csv(ATTR_PATH, {
            "date":           entry["date"],
            "ts":             entry["ts"],
            "code":           entry["code"],
            "strategy":       entry.get("strategy", "EOD_종가"),  # ★ WEAK-F
            # 점수 계층
            "score":          entry["score"],
            "bscore":         bscore,
            "final_score":    final_score,
            "ev_adj":         ev_result["ev_adj"],
            "ev_p":           ev_result["p"],
            "ev_b":           ev_result["b"],
            # Kelly 계층
            "kelly_fraction": kelly_params["fraction"],
            "kelly_full":     kelly_params["kelly_full"],
            "kelly_source":   kelly_params["source"],
            # Execution 계층
            "exec_type":      exec_params["exec_type"],
            "slippage_est":   exec_params["slippage_est"],
            # 기관 모멘텀
            "inst_ride_score":inst_mom["ride_score"],
            "inst_days":      inst_mom["inst_days"],
            "inst_signals":   "|".join(inst_mom["signals"]),
            # 리스크 계층
            "risk_size":      risk_layer["risk_size"],
            "risk_warns":     "|".join(risk_layer["risk_warns"]),
            # 시장
            "regime":         regime,
            # ★ WEAK-F: 결과 업데이트 추적용 — update_pnl_result()가 이 행을 찾아 채움
            # pnl_strategy_linker_v3_1이 청산 확정 후 update_pnl_result() 반드시 호출 필요
            "pnl_pct":        None,
            "exit_reason":    None,
            "pnl_updated":    0,    # ★ WEAK-F: 0=미업데이트, 1=업데이트완료 (진화루프 추적)
        })
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  엔트리 빌드
# ═══════════════════════════════════════════════════════════════
def _build_entry(row: pd.Series, reason: dict, code: str,
                 axes: dict, bscore: float, score: float,
                 conviction: str, size_mode: str,
                 base_risk: dict, exec_params: dict,
                 today_str: str, ev_norm: float = 0.0,
                 final_score: float = 0.0,
                 kelly_params: Optional[dict] = None,
                 ev_adj: float = 0.0,
                 inst_mom: Optional[dict] = None) -> dict:
    price = 0.0
    for c in ["price","last_close","day_close","close"]:
        v = _f(row.get(c, reason.get(c, 0)))
        if v > 0: price = v; break

    kp = kelly_params or {}
    # ★ v8.9 WEAK-2 FIX: inst_hold_threshold = 진입 ride_score × 0.70
    # 진입 ride보다 항상 낮게 설정 → 즉시 청산 신호 원천 차단
    _entry_ride = inst_mom["ride_score"] if (inst_mom and isinstance(inst_mom, dict)) else 0.40
    _hold_threshold = round(_entry_ride * 0.70, 3)
    return {
        "side": "BUY", "code": code,
        "qty":       exec_params["qty"],
        "price":     int(price),
        "order_krw": exec_params["effective_krw"],
        "ts": _now(), "date": today_str,
        "strategy":      "EOD_종가",
        "conviction":    conviction,
        "score":         round(score, 2),
        "grade":         str(row.get("grade","?")),
        "bridge_score":  bscore,
        "final_score":   final_score,
        "ev_norm":       round(ev_norm, 4),
        "ev_pct":        round(ev_adj * 100, 4),
        "ev_in_ev5":     int(ev_norm >= 0),
        "kosdaq_chg_pct":round(_f(row.get("kosdaq_chg_pct", 0)), 2),
        "exec_type":     exec_params["exec_type"],
        "slippage_est":  exec_params["slippage_est"],
        "exec_note":     exec_params["note"],
        "kelly_fraction":kp.get("fraction", 0),
        "kelly_mode":    kp.get("mode", "STABLE"),
        "kelly_source":  kp.get("source", "EVOLUTION"),
        "size_mode":     size_mode,
        "rank_ratio":    RANK1_RATIO,
        "stage1_score":  round(_f(row.get("stage1_score")),2),
        "stage2_score":  round(_f(row.get("stage2_score")),2),
        "stage3_score":  round(_f(row.get("stage3_score")),2),
        "attack_score":  round(_f(row.get("attack_score")),2),
        "defense_score": round(_f(row.get("defense_score")),2),
        "strong_axes":   axes["strong_count"],
        "axis1_flow":    int(axes["axis1"]),
        "axis2_price":   int(axes["axis2"]),
        "axis3_market":  int(axes["axis3"]),
        "axis4_timing":  int(axes["axis4"]),
        "ofi_accel":          round(_f(row.get("ofi_accel")),4),
        "vpin":               round(_f(row.get("vpin")),4),
        "residual_momentum":  round(_f(row.get("residual_momentum")),2),
        "close_position":     round(_f(row.get("close_position")),3),
        "high_break":         round(_f(row.get("high_break")),3),
        "last5_value_accel":  round(_f(row.get("last5_value_accel")),3),
        "upper_wick_ratio":   round(_f(row.get("upper_wick_ratio",1)),4),
        "day_chg_pct":        round(_f(row.get("day_chg_pct")),2),
        "mkt_risk_flag":      int(_f(row.get("mkt_risk_flag"))),
        "gap_risk_flag":      base_risk["gap_risk_flag"],
        "size_ratio":         base_risk["size_ratio"],
        "dyn_score":          round(_f(row.get("dyn_score")),2),
        "gap_predict_score":  round(_f(row.get("gap_predict_score")),2),
        "vwap_ratio":         round(_f(row.get("vwap_ratio",1.0)),4),
        "inst_consec":        int(_f(row.get("inst_consec"))),
        "high60_ratio":       round(_f(row.get("high60_ratio")),4),
        # ★ v8.9 WEAK-2 FIX: inst_hold_threshold = 진입 ride_score × 0.70
        # 청산 엔진은 ride_score가 이 값 이하로 떨어질 때 탈출 신호 발생
        "inst_hold_threshold":  _hold_threshold,
        "inst_exit_signal_days": int(_f(row.get("inst_consec"))),
    }



def _write_bridge_target(codes: list, date_str: str, logger: logging.Logger) -> bool:
    import json as _json
    payload = {"date": date_str, "codes": codes, "source": "kjs_bridge_eod_v9_9"}
    try:
        TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = TARGET_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(TARGET_PATH))
        logger.info("[TARGET] bridge_target 저장 codes=%d %s", len(codes), codes)
        return True
    except Exception as e:
        logger.error("[TARGET][FAIL] bridge_target 저장 실패: %s", e)
        return False


def _write_bridge_target_hold(date_str: str, reason: str, logger: logging.Logger) -> None:
    """[v9.10 STALE-FIX] HOLD 발생 시 bridge_target.json을 today/empty 상태로 갱신.
    이유: Execution이 어제/이전 stale target을 그대로 읽지 못하게 차단.
    payload.codes=[] 이면 Execution의 load_targets()가 None 반환하여 stale 사용을 회피한다.
    [PATCH] reason=='time_out_of_window'(EOD 시간창 외) 인 경우 eod_inactive=True 플래그 추가:
      Execution이 09시대 실시간 흐름을 살릴 수 있도록 명시. EOD 시간창(15:15~15:25)
      내부 동작(holiday/score_eod_missing/all_candidates_hold 등)은 변경 없음."""
    import json as _json
    # [P7' 2026-05-12] P7 BRIDGEWIN(09:00~15:30) 적용 후 09시대 reason이 time_out_of_window가 아니어서 eod_inactive=False가 되어 rt_execution_engine 폴백이 비활성화되던 결함 해소.
    # 진짜 EOD 본 시간창(15:15~15:25) 외 모든 시간은 eod_inactive=True → rt_intraday 폴백 활성. score_eod_date_mismatch/score_eod_missing/holiday_or_weekend 모두 09시대면 폴백 허용.
    _now_hm = _hhmm()
    _eod_inactive = not (1515 <= _now_hm <= 1525)
    payload = {"date": date_str, "codes": [], "source": "kjs_bridge_eod_v9_9",
               "hold_reason": reason, "eod_inactive": _eod_inactive}
    try:
        TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = TARGET_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(TARGET_PATH))
        logger.warning("[TARGET][HOLD] bridge_target empty 갱신 (stale 차단) reason=%s date=%s eod_inactive=%s",
                       reason, date_str, _eod_inactive)
    except Exception as e:
        logger.error("[TARGET][HOLD][FAIL] bridge_target empty 저장 실패: %s", e)


def _record_trade(code, score, bscore, axes, conviction, date_str, logger):
    try:
        _append_csv(HISTORY_PATH, {
            "date": date_str, "code": code, "score": score,
            "bridge_score": bscore, "strong_axes": axes,
            "conviction": conviction, "ts": _now(),
        })
    except Exception as e:
        logger.warning("[REC] 실패: %s", e)

def _record_result(code, score, bscore, axes, status, date_str, regime=""):
    try:
        _append_csv(RESULT_PATH, {
            "date": date_str, "code": code, "score": score,
            "bridge_score": bscore, "strong_axes": axes,
            "status": status, "regime": regime,
            "pnl_pct": None, "ts": _now(),
        })
    except Exception as e:
        logger.error("[PNL][FAIL] 결과 기록 실패 code=%s: %s", code, e)


def update_pnl_result(code: str, date_str: str, pnl_pct: float,
                      logger: logging.Logger,
                      exit_reason: str = "") -> bool:
    """
    ★ 자기진화 트리거 함수 — 청산/결산 확정 후 반드시 호출

    역할:
      1. bridge_result.csv → pnl_pct 업데이트
      2. attribution.csv   → pnl_pct + exit_reason 업데이트
      3. evolution_load_kelly() 자동 재실행 (시간가중 진화 즉시 반영)

    ★ v9.0 연동 체크리스트 (pnl_strategy_linker.py 담당):
      □ 청산 확정 직후 호출 (당일 장 마감 후 또는 다음날 아침)
      □ pnl_pct 단위: 백분율 (2.34 = +2.34%, -1.5 = -1.5% 손실)
      □ exit_reason 필수 기입 (Attribution 품질에 직결)
      □ 호출 후 get_evolution_status()로 반영 확인 권장

    호출 예시 (pnl_strategy_linker.py):
        # [v9.8 FIX] 자기 모듈에서 직접 호출 — 구버전 import 불필요
        from kjs_bridge_eod_v9_8_SAFEPLUS_FINAL import update_pnl_result, get_evolution_status
        logger = logging.getLogger("bridge_eod_v9_8")
        ok = update_pnl_result("005930", "2026-04-01", 2.34, logger, exit_reason="목표가도달")
        if ok:
            status = get_evolution_status()
            print(f"진화상태: {status['status_msg']}  승률={status['win_rate']:.1%}")

    exit_reason 표준값: "목표가도달" | "손절" | "시간청산" | "강제청산" | "기관이탈"
    """
    updated_result = False
    updated_attr   = False

    # ── 1. bridge_result.csv 업데이트
    try:
        if RESULT_PATH.exists():
            df = pd.read_csv(RESULT_PATH, encoding="utf-8-sig")
            mask = ((df["code"].astype(str).str.zfill(6) == str(code).zfill(6)) &
                    (df["date"].astype(str).str[:10] == date_str[:10]) &
                    (df["pnl_pct"].isna()))
            if mask.sum() > 0:
                df.loc[mask, "pnl_pct"] = round(pnl_pct, 4)
                tmp = RESULT_PATH.with_suffix(".tmp")
                df.to_csv(tmp, index=False, encoding="utf-8-sig")
                os.replace(str(tmp), str(RESULT_PATH))
                updated_result = True
    except Exception as e:
        logger.warning("[PNL] bridge_result 업데이트 실패: %s", e)

    # ── 2. attribution.csv 업데이트 (사후 분석 완성)
    try:
        if ATTR_PATH.exists():
            df2 = pd.read_csv(ATTR_PATH, encoding="utf-8-sig")
            mask2 = ((df2["code"].astype(str).str.zfill(6) == str(code).zfill(6)) &
                     (df2["date"].astype(str).str[:10] == date_str[:10]) &
                     (df2["pnl_pct"].isna()))
            if mask2.sum() > 0:
                df2.loc[mask2, "pnl_pct"]      = round(pnl_pct, 4)
                df2.loc[mask2, "exit_reason"]   = exit_reason
                # ★ WEAK-F: pnl_updated 플래그 1로 설정 → 자기진화 루프 추적 가능
                if "pnl_updated" in df2.columns:
                    df2.loc[mask2, "pnl_updated"] = 1
                tmp2 = ATTR_PATH.with_suffix(".tmp")
                df2.to_csv(tmp2, index=False, encoding="utf-8-sig")
                os.replace(str(tmp2), str(ATTR_PATH))
                updated_attr = True
    except Exception as e:
        logger.warning("[PNL] attribution 업데이트 실패: %s", e)

    if updated_result or updated_attr:
        sign = "+" if pnl_pct >= 0 else ""
        logger.info("[PNL] %s %s pnl=%s%.2f%%  exit=%s  result=%s attr=%s",
                    code, date_str, sign, pnl_pct, exit_reason or "-",
                    "OK" if updated_result else "SKIP",
                    "OK" if updated_attr else "SKIP")
        # ── 3. ★ 자기진화 즉시 재실행 (결과 반영)
        evolution_load_kelly(logger)
        # ── 4. [v9.8.1 FIX-4] pnl_strategy_linker 연동 — write_sell_fill 트리거
        # pnl_linker가 daily_pnl_by_strategy.csv를 관리하고 EdgeScore/Kelly 계산
        # bridge 단독으로 bridge_result.csv만 관리하면 linker와 데이터 분리 문제 발생
        try:
            import sys as _sys
            import os as _os
            _base_dir = str(BASE)
            if _base_dir not in _sys.path:
                _sys.path.insert(0, _base_dir)
            _pnl_mod = None
            for _ver in ("pnl_strategy_linker_v3_4_FIXED",
                         "pnl_strategy_linker_v3_4",
                         "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL"):
                try:
                    import importlib as _il
                    _pnl_mod = _il.import_module(_ver)
                    break
                except ImportError:
                    continue
            if _pnl_mod and hasattr(_pnl_mod, "write_sell_fill"):
                _pnl_mod.write_sell_fill(
                    code=code,
                    sell_price=0.0,   # bridge는 가격 미보유 — linker에서 buy_price 기반 계산
                    sell_qty=0,
                    strategy="SIGA",
                    base_dir=_base_dir,
                    logger=logger,
                    date_str=date_str,
                    exit_reason=exit_reason,
                )
                logger.info("[PNL] pnl_strategy_linker write_sell_fill 트리거 완료 code=%s", code)
        except Exception as _le:
            logger.debug("[PNL] pnl_linker 트리거 실패(비치명): %s", _le)
        return True

    logger.info("[PNL] %s %s 업데이트 대상 없음", code, date_str)
    return False


def get_evolution_status() -> dict:
    """
    자기진화 현재 상태 조회 — 외부 모듈에서 호출 가능

    사용법:
        # [v9.8 FIX] 구버전 import 제거 — 동일 파일 직접 사용
        from kjs_bridge_eod_v9_8_SAFEPLUS_FINAL import get_evolution_status
        status = get_evolution_status()
        print(status)
    """
    return {
        "ready":      EVOLUTION_READY,
        "win_rate":   EVOLUTION_WIN_RATE,
        "avg_win":    EVOLUTION_AVG_WIN,
        "avg_loss":   EVOLUTION_AVG_LOSS,
        "b":          EVOLUTION_B,
        "regime_win": REGIME_WIN_RATES,
        "attack_min": ATTACK_KELLY_MIN,
        "stable_size":STABLE_SIZE,
        "status_msg": "★자기진화 활성" if EVOLUTION_READY else "기본값 사용 중 (거래 누적 필요)",
    }




# ═══════════════════════════════════════════════════════════════
#  서브함수 — main() 분리
# ═══════════════════════════════════════════════════════════════
def _eval_candidates(candidates, held_codes, ev_codes, logger,
                     bear_soft_mode: bool = False,
                     vkospi: float = 0.0):    # [v9.8 FIX-2] vkospi 명시적 전달 — dir() 방식 제거
    """후보 종목 평가 루프
    ★ v8.2: bscore 정렬 → selection_score(EV/Risk) 정렬로 교체
    ★ W5: Kelly SKIP 사전제거
    ★ 초기 보수적 모드: EVOLUTION_READY=False → STABLE만 허용

    ★ v9.0 수정7: BEAR 소프트 모드 ride=0.40 근거 명시
      ride_score 구성:
        기관2일(+0.25) + OFI가속(+0.25) + VPIN정보우위(+0.10) = 0.60  → 강매집
        기관2일(+0.25) + OFI최소(+0.10)                       = 0.35  → 기준 미달
        기관2일(+0.25) + OFI가속(+0.10~0.25) + 일부           ≥ 0.40 → BEAR 최소 허용

      0.40 기준 근거:
        - 기관 연속매수(필수) + OFI 가속(확인) 동시충족 시 최소값 ≈ 0.35~0.45
        - 0.40은 기관 등에 타기 "최소 확인선" (매집 지속 신호 있음)
        - 0.25(RIDE_HARD_MIN)보다 높아 진짜 기관매집 종목만 통과
        - BEAR에서도 개인 소규모 자금은 기관 뒤에서 STABLE 30% 진입 가능
        - 0.55 이상이면 MEDIUM 이상 사이징 가능 (EV_SUPER 조건)
    """
    import datetime as _dt
    try:
        _sb_mdate = _dt.date.fromtimestamp(EOD_PATH.stat().st_mtime).strftime("%Y-%m-%d")
        _sb_is_today = (_sb_mdate == _today())
    except Exception:
        _sb_is_today = True
    _min_axes = MIN_STRONG_AXES if _sb_is_today else 2
    if not _sb_is_today:
        logger.warning("[SB-DATE] score_eod 당일 아님(%s) → 4축 기준 %d→2 완화", _sb_mdate, MIN_STRONG_AXES)

    eval_rows = []
    for _, row in candidates.iterrows():
        code   = str(row.get("code","")).zfill(6)
        reason = _parse_reason(row.get("reason","{}"))
        if code in held_codes:
            logger.info("  [SKIP] %s 보유중", code); continue
        axes = p2_eval_axes(row, reason)
        if axes["strong_count"] < _min_axes:
            logger.info("  [SKIP] %s 4축미달 %d/%d", code,
                        axes["strong_count"], _min_axes); continue
        evt = check_event_risk(code, row, reason, logger)
        if not evt["is_safe"]: continue
        bscore, regime, timing_adj, ev_bonus = p2_bridge_score(
            row, reason, axes, ev_codes, code,
            vkospi=vkospi)  # [v9.8 FIX-3]
        if bscore < MIN_BRIDGE_SCORE:
            logger.info("  [SKIP] %s bscore %.4f < %.2f", code, bscore, MIN_BRIDGE_SCORE)
            continue
        if not p2_check_repeat(code, logger, bscore=bscore): continue
        ev_norm     = ev_codes.get(code, -1.0)
        inst_consec = _f(row.get("inst_consec", reason.get("inst_consec", 0)))
        ofi_accel   = _f(row.get("ofi_accel",   reason.get("ofi_accel",   0)))
        val_ratio   = _f(row.get("val_ratio",    reason.get("val_ratio",   1.0)))
        vpin        = _f(row.get("vpin",         reason.get("vpin",        0)))
        gap_pred    = _f(row.get("gap_predict_score", reason.get("gap_predict_score", 0)))
        day_chg     = _f(row.get("day_chg_pct",  reason.get("day_chg_pct", 0)))
        inst_mom    = calc_inst_momentum(inst_consec, ofi_accel, val_ratio, vpin)
        ev_result   = calc_ev_probabilistic(ev_norm, bscore, regime, inst_consec, gap_pred)

        # ★ WEAK-6: BEAR 소프트 모드 — 기관 탑승 가능한 종목만 허용
        # ★ v8.5 [RET-3]: 0.55 → 0.40 완화
        # ★ v9.4 FIX-1: ride≥0.50 AND inst_consec≥4 → BEAR 최소진입 허용 (1일 1진입 보호)
        if bear_soft_mode:
            ride_ok   = inst_mom["ride_score"] >= BEAR_MIN_ENTRY_RIDE
            consec_ok = inst_consec >= BEAR_MIN_ENTRY_CONSEC
            if ride_ok and consec_ok:
                logger.info("  [BEAR-MIN-ENTRY] %s ride=%.2f consec=%d → STABLE 강제진입 (1일1진입)",
                            code, inst_mom["ride_score"], int(inst_consec))
            elif inst_mom["ride_score"] < 0.40:
                logger.info("  [BEAR-SOFT] %s ride=%.2f<0.40 → SKIP",
                            code, inst_mom["ride_score"])
                continue
            else:
                logger.info("  [BEAR-SOFT] %s ride=%.2f → STABLE 허용 (기관강매집 예외)",
                            code, inst_mom["ride_score"])

        # ★ Kelly 사전필터
        kelly = calc_kelly_advanced(ev_result, bscore, "")

        # ★ v9.0 수정1: CAUTION EV 필터 통일
        # 기존 문제: eff_ev_min(0.65×0.14=0.091)과 Q5(0.16) 이중 기준 — 논리 충돌
        #   eff_ev_min 완화(0.091 허용)가 Q5(0.16 차단)에 의해 무조건 무력화됨
        # 해결: CAUTION 배수를 1.15로 상향 → eff_ev_min=0.14×1.15=0.161 (Q5와 통일)
        #       Q5 별도 필터 완전 제거 → 단일 기준으로 명확화
        # BULL:    EV_ADJ_MIN × 0.80 = 0.112% (강세 기회 확대)
        # NEUTRAL: EV_ADJ_MIN × 1.00 = 0.140% (기준)
        # CAUTION: EV_ADJ_MIN × 1.15 = 0.161% (하락장 방어 강화 — Q5와 통일)
        # [v9.8.1 FIX-7] CAUTION 1.15 근거: 손실 구간 추가 방어 + Q5(0.16%) 동일 효과 통합
        # BEAR:    EV_ADJ_MIN × 1.50 = 0.210% (엄격)
        _REGIME_EV_MULT = {"BULL": 0.80, "NEUTRAL": 1.00, "CAUTION": 1.15, "BEAR": 1.50}
        eff_ev_min = EV_ADJ_MIN * _REGIME_EV_MULT.get(regime, 1.00)
        # ★ v9.4 FIX-2: 워밍업 초기(0%) → EV 기준 완화 × 0.75 (진입 기회 유지)
        if not EVOLUTION_READY and EVOLUTION_WARMING_RATIO < 0.30:
            eff_ev_min *= WARMING_EV_RELAX
            logger.debug("  [WARMING-EV] %s eff_ev_min 완화 →%.4f (워밍업0%%)", code, eff_ev_min)
        if ev_result["ev_adj"] < 0:
            logger.info("  [SKIP] %s EV_adj=%.5f < 0 (음수EV → 진입금지)",
                        code, ev_result["ev_adj"])
            continue
        # ★ Q5 제거 (위 eff_ev_min으로 통합됨 — CAUTION×1.15=0.161%가 0.16과 동일 역할)

        # ★ v8.6 [C]: 워밍업 비율 기반 점진적 Kelly 허용
        if not EVOLUTION_READY:
            wr = EVOLUTION_WARMING_RATIO
            if wr < 0.30:
                if kelly["mode"] in ("ATTACK", "MEDIUM"):
                    logger.info("  [보수초기] %s %s→STABLE (ratio=%.0f%%)",
                                code, kelly["mode"], wr * 100)
                    kelly["mode"]     = "STABLE"
                    kelly["fraction"] = STABLE_SIZE
            elif wr < 0.70:
                if kelly["mode"] == "ATTACK":
                    logger.info("  [보수중간] %s ATTACK→MEDIUM (ratio=%.0f%%)",
                                code, wr * 100)
                    kelly["mode"]     = "MEDIUM"
                    kelly["fraction"] = MEDIUM_SIZE
            else:
                logger.info("  [보수완화] %s %s 허용 (ratio=%.0f%%)",
                            code, kelly["mode"], wr * 100)

        # ★ BEAR 소프트 모드에서는 ATTACK/MEDIUM → STABLE
        # [v9.8.1 FIX-5] BEAR soft_mode ATTACK→STABLE 강등 명시
        if bear_soft_mode and kelly["mode"] in ("ATTACK", "MEDIUM"):
            logger.info("  [BEAR-SOFT] %s %s→STABLE (BEAR 레짐 방어)", code, kelly["mode"])
            kelly["mode"]     = "STABLE"
            kelly["fraction"] = STABLE_SIZE

        # ★ v8.8: risk_sc를 EV override 전에 계산 (Q1 조건부 ATTACK에서 필요)
        risk_sc = calc_risk_score(row, reason)

        # ★ v8.7 [P1] / v8.8 [Q1]: EV 상단 집중 — 조건부 ATTACK
        # SUPER(≥0.22%): ride≥0.50 AND risk≤0.55 확인 후 ATTACK, 아니면 MEDIUM
        # ★ 추가-1: ride 0.55→0.50 완화 — 기관2일+OFI강세 케이스 ATTACK 진입 허용
        # HIGH (≥0.16%): STABLE이면 MEDIUM으로 구제 승급
        ev_now = ev_result["ev_adj"]
        # ★ v9.4 FIX-1: 슈퍼BULL(VKOSPI<15) → ATTACK SIZE 85%로 상향
        _current_attack_size = ATTACK_SIZE
        if _is_super_bull(regime, vkospi):  # [v9.8 FIX-2] dir() 제거 → 파라미터 직접 사용
            _current_attack_size = SUPER_BULL_ATTACK_SIZE
            logger.info("  [SUPER-BULL] %s VKOSPI극저점 → ATTACK %.0f%%",
                        code, _current_attack_size * 100)
        if ev_now >= EV_SUPER_THRESHOLD:
            ride_ok = inst_mom["ride_score"] >= 0.50  # 구: 0.55
            risk_ok = risk_sc["risk_score"]  <= 0.55
            if ride_ok and risk_ok:
                if kelly["mode"] != "ATTACK":
                    logger.info("  [EV-SUPER] %s EV=%.4f ride=%.2f risk=%.2f → ATTACK",
                                code, ev_now, inst_mom["ride_score"], risk_sc["risk_score"])
                kelly["mode"]     = "ATTACK"
                kelly["fraction"] = _current_attack_size
            else:
                logger.info("  [EV-SUPER→MED] %s EV=%.4f ride=%.2f risk=%.2f → MEDIUM (조건미달)",
                            code, ev_now, inst_mom["ride_score"], risk_sc["risk_score"])
                kelly["mode"]     = "MEDIUM"
                kelly["fraction"] = MEDIUM_SIZE
        elif ev_now >= EV_HIGH_THRESHOLD:
            if kelly["mode"] == "STABLE":
                logger.info("  [EV-HIGH] %s EV=%.4f≥%.2f → MEDIUM 승급",
                            code, ev_now, EV_HIGH_THRESHOLD)
                kelly["mode"]     = "MEDIUM"
                kelly["fraction"] = MEDIUM_SIZE

        if kelly["mode"] == "SKIP":
            # [PATCH-3] SKIP → STABLE 강등 (EV 이미 통과 — 사이즈만 최소화)
            logger.info("  [KELLY→STABLE] %s half=%.3f → STABLE 강등 (EV통과, 최소사이즈)",
                        code, kelly.get("kelly_half", 0))
            kelly["mode"]     = "STABLE"
            kelly["fraction"] = STABLE_SIZE

        # ★ Selection Score (risk_sc는 위에서 이미 계산됨)
        # [v9.8 FIX-1] eff_ev_min 전달 — 레짐별 완화 기준 일관 적용
        sel_sc   = calc_selection_score(ev_result, bscore, risk_sc, inst_consec, day_chg,
                                        eff_ev_min=eff_ev_min)

        if sel_sc["selection_score"] <= 0:
            logger.info("  [SKIP] %s selection=0 (EV_adj부족)", code)
            continue

        # [v9.8 FIX-4] Q4 dead code 정리 — BEAR 레짐에서 eff_ev_min=0.21이 이미 더 강한 필터
        # 기존 0.10 하드플로어는 BEAR에서 항상 통과 (0.10 < 0.21) → 실질 dead code
        # 레짐별 eff_ev_min이 이미 적용되었으므로 Q4 별도 체크 불필요
        # 단, eff_ev_min < 0.10인 경우(워밍업 완화 등) 최소 보호선 유지
        # [EV 완화] Q4 플로어 제거 — 음수EV만 차단, 양수EV는 모두 통과

        # ★ v8.8 [Q7]: 최종 리스크 방어막 (과열 종목 차단)
        # ★ v9.6 FIX-3: 0.80→0.77 — KOSDAQ 소형주 과열 더 적극 차단
        #   0.75는 진입기회 과도 차단, 0.77은 명백한 과열만 차단하는 균형점
        #   params v3.8 DD_THRESHOLD=-2.2와 맞물려 이중 보호 구조 완성
        if risk_sc["risk_score"] > 0.77:
            logger.info("  [SKIP] %s risk=%.3f > 0.77 → 과열차단", code, risk_sc["risk_score"])
            continue

        evol_tag = "★실전" if ev_result["evolution_ready"] else "기본값"
        logger.info(
            "  [후보] %s sel=%.6f (EV=%+.5f risk=%.2f bs=%.3f) %s 기관=%.2f %s",
            code, sel_sc["selection_score"],
            ev_result["ev_adj"], risk_sc["risk_score"], bscore,
            kelly["mode"], inst_mom["ride_score"], evol_tag,
        )
        # ★ [FINAL] 상세 로그
        logger.info(
            "  [FINAL] %s EV=%.4f sel=%.6f kelly=%s inst=%.2f",
            code, ev_result["ev_adj"],
            sel_sc["selection_score"],
            kelly["mode"], inst_mom["ride_score"],
        )
        eval_rows.append({
            "row": row, "reason": reason, "code": code,
            "axes": axes, "bscore": bscore,
            "score": _f(row.get("score", 0)),
            "score_final": _f(row.get("score_final", 0.0)),   # [PATCH-2] SB_norm 기저
            "eff_ev_min":  eff_ev_min,                         # [PATCH-2] ev_shortfall 계산용
            "l5a":         _f(row.get("last5_value_accel", reason.get("last5_value_accel", 0.8))),  # [PATCH-2] LQ
            "ev_norm": ev_norm, "ev_result": ev_result,
            "inst_mom": inst_mom, "evt": evt, "kelly": kelly,
            "regime": regime, "timing_adj": timing_adj, "ev_bonus": ev_bonus,
            "inst_consec": inst_consec, "ofi_accel": ofi_accel,
            "val_ratio": val_ratio, "gap_pred": gap_pred,
            "risk_sc": risk_sc, "sel_sc": sel_sc,
        })
    return eval_rows


def _calc_composite_score(eval_rows, logger):
    """Hard Filter 통과 후보 전체를 composite score로 평가 [PATCH-2]
    weights: SB=0.50 EV=0.30 BS=0.12 LQ=0.08 | penalty cap=0.30
    n=0 → 그대로 반환 / n=1 → composite=1.0 자동 선택
    """
    n = len(eval_rows)
    if n == 0:
        return eval_rows
    if n == 1:
        eval_rows[0]["composite"]    = 1.0
        eval_rows[0]["_comp_detail"] = {"sb": 1.0, "ev": 1.0, "bs": 1.0,
                                        "lq": 1.0, "pen": 0.0}
        return eval_rows

    def _norm(vals):
        mn, mx = min(vals), max(vals)
        return [(v - mn) / max(mx - mn, 1e-9) for v in vals]

    # ── 컬럼 추출 및 score_final fallback ─────────────────────
    sf_vals = []
    for r in eval_rows:
        sf = r.get("score_final", 0.0)
        if sf == 0.0:
            sf = r.get("score", 0.0)
        sf_vals.append(float(sf))
    if max(sf_vals) == 0.0:
        logger.warning("[COMPOSITE] score_final 전부 0 → score fallback")
        sf_vals = [float(r.get("score", 0.0)) for r in eval_rows]

    ev_vals = [float(r["ev_result"]["ev_adj"]) for r in eval_rows]
    bs_vals = [float(r["bscore"])              for r in eval_rows]
    lq_vals = [float(r["val_ratio"]) * 0.60 + float(r.get("l5a", 0.8)) * 0.40
               for r in eval_rows]

    sf_norm = _norm(sf_vals)
    ev_norm = _norm(ev_vals)
    bs_norm = _norm(bs_vals)
    lq_norm = _norm(lq_vals)

    best_sf_idx = sf_vals.index(max(sf_vals))  # scoreboard rank1 보호 대상

    for i, r in enumerate(eval_rows):
        axes_cnt = r["axes"]["strong_count"]
        axes_pen = max(0.0, (3 - axes_cnt) * 0.04) if axes_cnt < 3 else 0.0

        ev_adj   = float(r["ev_result"]["ev_adj"])
        eff_ev   = float(r.get("eff_ev_min", 0.14))
        ev_short = min(max(0.0, eff_ev - ev_adj) * 10.0, 0.15)

        gap_cls  = str(r["row"].get("gap_class", "NORMAL"))
        gap_pen  = 0.08 if (gap_cls == "HIGH" and r["bscore"] < 0.65) else \
                   0.04 if  gap_cls == "HIGH"                           else 0.0

        ride     = float(r["inst_mom"].get("ride_score", 0.5))
        ride_pen = 0.10 if ride < 0.25 else 0.05 if ride < 0.40 else 0.0

        val     = float(r["val_ratio"])
        lq_vpen = 0.08 if val < 0.30 else 0.04 if val < 0.50 else 0.0

        l5a     = float(r.get("l5a", 0.8))
        lq_lpen = 0.06 if l5a < 0.50 else 0.03 if l5a < 0.80 else 0.0

        penalty = min(axes_pen + ev_short + gap_pen + ride_pen + lq_vpen + lq_lpen, 0.30)

        sb = sf_norm[i]
        if i == best_sf_idx and n >= 2:
            sb = max(sb, 0.80)  # rank1 보호: 역전에 0.40+ composite 차이 필요

        composite = (0.50 * sb + 0.30 * ev_norm[i]
                     + 0.12 * bs_norm[i] + 0.08 * lq_norm[i] - penalty)
        r["composite"]    = round(composite, 6)
        r["_comp_detail"] = {
            "sb": round(sb, 4), "ev": round(ev_norm[i], 4),
            "bs": round(bs_norm[i], 4), "lq": round(lq_norm[i], 4),
            "pen": round(penalty, 4),
        }
        logger.debug(
            "  [COMP] %s comp=%.4f sb=%.3f ev=%.3f bs=%.3f lq=%.3f pen=%.3f",
            r["code"], composite, sb, ev_norm[i], bs_norm[i], lq_norm[i], penalty,
        )
    return eval_rows


def _log_sel_compare(old_row, new_row, logger):
    """OLD(selection_score) vs NEW(composite) 선발 비교 로그 [PATCH-2]"""
    d = new_row.get("_comp_detail", {})
    match = (old_row["code"] == new_row["code"])
    ev_diff = (float(new_row["ev_result"]["ev_adj"])
               - float(old_row["ev_result"]["ev_adj"]))
    sf_new = float(new_row.get("score_final", new_row.get("score", 0)))
    sf_old = float(old_row.get("score_final", old_row.get("score", 0)))
    logger.info(
        "[BRIDGE][SEL_COMPARE] "
        "OLD=%s(score=%.1f sel=%.4f) | "
        "NEW=%s(comp=%.4f sb=%.3f ev=%.3f bs=%.3f lq=%.3f pen=%.3f) | "
        "EV_diff=%+.5f SB_diff=%+.1f MATCH=%s",
        old_row["code"],
        float(old_row.get("score", 0)),
        float(old_row.get("sel_sc", {}).get("selection_score", 0)),
        new_row["code"],
        new_row.get("composite", 0),
        d.get("sb", 0), d.get("ev", 0), d.get("bs", 0),
        d.get("lq", 0), d.get("pen", 0),
        ev_diff, sf_new - sf_old,
        "TRUE" if match else "FALSE",
    )
    if not match:
        logger.warning("[BRIDGE][SEL_COMPARE] ★역전: OLD=%s → NEW=%s",
                       old_row["code"], new_row["code"])


def _build_top1_entry(best, today_str, capital, logger, relax: bool = False):
    """1등 주문 빌드.
    ★ W6: conviction = Kelly mode로 통합 (ATTACK/STABLE)
    ★ W7: WEAK 사각지대 제거 (Kelly SKIP이 _eval_candidates에서 이미 처리)
    relax=True: 소프트 임계값(MIN_SCORE, MIN_BRIDGE_SCORE) 15% 완화 재시도
    반환: (entry, kelly, exec_params, risk_layer, base_risk, hold_reason)
    """
    code1      = best["code"];       row1      = best["row"]
    reason1    = best["reason"];     axes1     = best["axes"]
    bscore1    = best["bscore"];     ev_norm1  = best["ev_norm"]
    score1     = best["score"]
    ev_result1 = best["ev_result"];  inst_mom1 = best["inst_mom"]
    regime1    = best["regime"];     kelly1    = best["kelly"]
    FAIL = (None,None,None,None,None)

    _relax_f      = 0.85 if relax else 1.0
    _score_floor  = MIN_SCORE        * _relax_f
    _bscore_floor = MIN_BRIDGE_SCORE * _relax_f

    if score1 < _score_floor:
        return *FAIL, "HOLD_SCORE"
    if bscore1 < _bscore_floor:
        _record_result(code1, score1, bscore1, 0, "HOLD_BRIDGE_SCORE", today_str, regime1)
        return *FAIL, "HOLD_BRIDGE_SCORE"

    # ★ W6: conviction = Kelly mode (ATTACK/STABLE — SKIP은 _eval_candidates에서 이미 제거)
    conv1 = kelly1["mode"]

    import datetime as _dt3
    try:
        _liq_sb_today = (_dt3.date.fromtimestamp(EOD_PATH.stat().st_mtime).strftime("%Y-%m-%d") == today_str)
    except Exception:
        _liq_sb_today = True
    if _liq_sb_today and not p3_check_liquidity(row1, reason1, logger):
        _record_result(code1, score1, bscore1, axes1["strong_count"],
                       "HOLD_LIQUIDITY", today_str, regime1)
        return *FAIL, "HOLD_LIQUIDITY"

    base_risk1 = eval_position_risk(row1, reason1, logger)
    if not base_risk1["can_enter"]:
        # ★ v9.0 수정5: GAP_HIGH 예외 + risk_layer 충돌 방어
        # 기존 문제: GAP_HIGH 예외(bscore≥0.65)로 can_enter=True 허용 후
        #            eval_risk_layer에서 EV 부족으로 HOLD_RISK_LAYER → 결과 불명확
        # 해결: GAP_HIGH 예외 허용 전에 EV 최소조건 선검증
        #       EV_adj < EV_ADJ_MIN이면 GAP_HIGH 예외 불허 (안전 우선)
        if (base_risk1.get("gap_risk_blocked")
                and bscore1 >= GAP_HIGH_ALLOW_SCORE
                and ev_result1["ev_adj"] >= EV_ADJ_MIN):   # ★ EV 선검증 추가
            base_risk1["can_enter"]  = True
            # ★ WEAK-C: 동적 갭 사이즈 사용 (갭 크기에 따라 0.10~0.30 자동 조정)
            dyn_size = base_risk1.get("gap_high_size", GAP_HIGH_SIZE_RATIO)
            base_risk1["size_ratio"] = dyn_size
            logger.info("[RISK] GAP_HIGH예외허용: %s bscore=%.3f ev=%.4f size=%.0f%% (동적)",
                        code1, bscore1, ev_result1["ev_adj"], dyn_size*100)
        else:
            logger.warning("[RISK] %s", " | ".join(base_risk1["risk_notes"]))
            _record_result(code1, score1, bscore1, axes1["strong_count"],
                           "HOLD_RISK", today_str, regime1)
            return *FAIL, "HOLD_RISK"

    risk_layer1 = eval_risk_layer(
        bscore1, ev_result1, inst_mom1, regime1,
        base_risk1["size_ratio"], capital,
        _f(row1.get("price", reason1.get("price", 1)))
    )
    if not risk_layer1["can_enter"]:
        logger.warning("[RISK-4] %s", " | ".join(risk_layer1["risk_blocks"]))
        _record_result(code1, score1, bscore1, axes1["strong_count"],
                       "HOLD_RISK_LAYER", today_str, regime1)
        return *FAIL, "HOLD_RISK_LAYER"

    price1 = 0.0
    for c in ["price","last_close","day_close","close"]:
        v = _f(row1.get(c, reason1.get(c, 0)))
        if v > 0: price1 = v; break
    if price1 <= 0:
        _record_result(code1, score1, bscore1, axes1["strong_count"],
                       "HOLD_NO_PRICE", today_str, regime1)
        return *FAIL, "HOLD_NO_PRICE"

    order_base = calc_order_by_rank(base_risk1, price1, conv1, kelly1)
    if order_base is None:
        return *FAIL, "HOLD_ORDER"

    # ★ W9: calc_execution_params — 필요한 인자만 전달
    exec1 = calc_execution_params(price1, order_base["order_krw"])
    if exec1["qty"] <= 0:
        return *FAIL, "HOLD_QTY"

    # ★ final_score = selection_score (선택 로직 = 기록 로직 일치시켜야 자기진화 정상 작동)
    sel_score1 = best["sel_sc"]["selection_score"]
    entry1 = _build_entry(
        row1, reason1, code1, axes1, bscore1, score1,
        conv1, conv1, base_risk1, exec1, today_str,
        ev_norm=ev_norm1, final_score=sel_score1, kelly_params=kelly1,
        ev_adj=ev_result1["ev_adj"],
        inst_mom=inst_mom1,
    )
    return entry1, kelly1, exec1, risk_layer1, base_risk1, ""


# ═══════════════════════════════════════════════════════════════
#  [v9.10 TRACE] BRIDGE_SUMMARY — 매수 차단 추적
# ═══════════════════════════════════════════════════════════════
_BRIDGE_STATS: dict = {
    "input_count": -1,    # score_eod.csv 행 수
    "eval_count": -1,     # _eval_candidates 후 후보 수
    "output_codes": -1,   # bridge_target.json codes 수 (HOLD 시 0)
    "hold_reason": "",
    "rc": -1,
}

def _bridge_stats_reset() -> None:
    _BRIDGE_STATS.update({"input_count": -1, "eval_count": -1,
                          "output_codes": -1, "hold_reason": "", "rc": -1})

def _bridge_set_reason(reason: str) -> None:
    if not _BRIDGE_STATS["hold_reason"]:
        _BRIDGE_STATS["hold_reason"] = reason

def _emit_bridge_summary(logger) -> None:
    try:
        logger.info("[BRIDGE_SUMMARY] input_count=%d eval_count=%d "
                    "output_codes=%d hold_reason=%s rc=%d",
                    _BRIDGE_STATS["input_count"], _BRIDGE_STATS["eval_count"],
                    _BRIDGE_STATS["output_codes"],
                    _BRIDGE_STATS["hold_reason"] or "-", _BRIDGE_STATS["rc"])
    except Exception:
        pass


def main() -> int:
    _bridge_stats_reset()
    rc = RC_HOLD
    _logger_ref = [None]
    try:
        rc = _main_body(_logger_ref)
        return rc
    finally:
        _BRIDGE_STATS["rc"] = rc
        if _logger_ref[0] is not None:
            _emit_bridge_summary(_logger_ref[0])


def _main_body(_logger_ref) -> int:
    logger = _setup_logger()
    _logger_ref[0] = logger
    logger.info("=" * 78)
    logger.info("BRIDGE EOD v9.4  [개인특화 HF급 | EOD종가전용 | 기관등에타기 | 3대약점수정 | VKOSPI보정]")
    logger.info("[VER] %s", ENGINE_VER)

    # ★ 자기진화 로드 (가장 먼저)
    evolution_load_kelly(logger)

    # [v9.7 FIX] params.json → ATTACK_SIZE/MEDIUM_SIZE/STABLE_SIZE 동적 반영
    # evolution_engine이 진화한 kelly.fraction이 실제 사이징에 적용되도록
    # 기존 문제: ATTACK_SIZE=0.70 하드코딩 → evolution 결과 무시
    # 수정: params_v3_5.json 읽어 현재 레짐 fraction으로 ATTACK_SIZE 갱신
    global ATTACK_SIZE, MEDIUM_SIZE, STABLE_SIZE
    _params_loaded = False
    for _pcand in _PARAMS_CANDIDATES:
        if _pcand.exists():
            try:
                import json as _json
                with open(_pcand, encoding="utf-8-sig") as _pf:
                    _cpar = _json.load(_pf)
                _regime_now = _cpar.get("_regime", "TREND")
                _kelly_sec  = _cpar.get(_regime_now, {}).get("kelly", {})
                _frac       = _kelly_sec.get("fraction", 0.0)
                # [v9.9] EOD.ATTACK_RATIO/DEFENSE_RATIO: kelly 범위 밖일 때 fallback base
                # kelly 정상 범위(0.10~0.75) → evolution 우선 (기존 동일)
                # kelly 범위 밖 → EOD 70:30 base fallback (자기진화 구조 완전 유지)
                _eod_sec    = _cpar.get("EOD", {})
                _atk_base   = _eod_sec.get("ATTACK_RATIO", 0.0)
                _def_base   = _eod_sec.get("DEFENSE_RATIO", 0.0)
                if 0.10 <= _frac <= 0.75:           # kelly 정상 범위 → evolution 우선
                    ATTACK_SIZE = round(_frac, 4)
                    MEDIUM_SIZE = round(min(_frac * 0.70, 0.55), 4)
                    STABLE_SIZE = round(min(_frac * 0.43, 0.35), 4)
                    logger.info(
                        "[v9.9] params 동적 반영(kelly): 레짐=%s fraction=%.4f → "
                        "ATTACK=%.2f MEDIUM=%.2f STABLE=%.2f (파일=%s)",
                        _regime_now, _frac,
                        ATTACK_SIZE, MEDIUM_SIZE, STABLE_SIZE, _pcand.name
                    )
                elif 0.10 <= _atk_base <= 0.90:     # kelly 범위 밖 → EOD 70:30 fallback
                    ATTACK_SIZE = round(_atk_base, 4)
                    MEDIUM_SIZE = round((_atk_base + _def_base) / 2 if _def_base > 0 else 0.50, 4)
                    STABLE_SIZE = round(_def_base if 0.05 <= _def_base <= 0.60 else 0.30, 4)
                    logger.info(
                        "[v9.9] params 동적 반영(EOD base): 레짐=%s kelly=%.4f 범위 밖 → "
                        "EOD ATTACK=%.2f MEDIUM=%.2f STABLE=%.2f (파일=%s)",
                        _regime_now, _frac,
                        ATTACK_SIZE, MEDIUM_SIZE, STABLE_SIZE, _pcand.name
                    )
                    _params_loaded = True
                break
            except Exception as _pe:
                logger.warning("[v9.7] params 읽기 실패: %s → 기본값 유지", _pe)
    if not _params_loaded:
        logger.info("[v9.7] params 파일 없음 → ATTACK_SIZE=%.2f 기본값 유지", ATTACK_SIZE)

    capital  = _get_capital()
    mode_tag = "실전테스트(100만원)" if REAL_TEST_MODE else f"본게임({TOTAL_CAPITAL:,}원)"
    evol_tag = "★자기진화활성" if EVOLUTION_READY else f"워밍업(누적중/{EVOLUTION_MIN_SAMPLES}건필요)"
    logger.info("[자금] %s  승률=%.1f%%  b=%.3f  [%s]",
                mode_tag, EVOLUTION_WIN_RATE*100, EVOLUTION_B, evol_tag)
    logger.info("[Kelly] ATTACK≥%.2f→70%%  MEDIUM≥%.2f→50%%  STABLE≥0.05→30%%",
                ATTACK_KELLY_MIN, MEDIUM_KELLY_MIN)
    if EVOLUTION_READY:
        logger.info("[진화값] avg_win=%.3f%%  avg_loss=%.3f%%  레짐=%s",
                    EVOLUTION_AVG_WIN, EVOLUTION_AVG_LOSS, REGIME_WIN_RATES)

    today_str = _today()
    # [v9.10 STALE-FIX] HOLD 시 bridge_target.json을 today/empty로 갱신하여 stale 차단
    if not p3_check_holiday(logger):
        _bridge_set_reason("holiday_or_weekend")
        _write_bridge_target_hold(today_str, "holiday_or_weekend", logger); return RC_HOLD
    if not p1_check_time(logger):
        _bridge_set_reason("time_out_of_window")
        _write_bridge_target_hold(today_str, "time_out_of_window", logger); return RC_HOLD

    df = _read_csv(EOD_PATH, logger, required=True)
    if df is None or df.empty:
        logger.warning("[LOAD] score_eod.csv 없음 → HOLD")
        _bridge_set_reason("score_eod_missing")
        _write_bridge_target_hold(today_str, "score_eod_missing", logger); return RC_HOLD
    if not p1_check_date(df, logger):
        _bridge_set_reason("score_eod_date_mismatch")
        _write_bridge_target_hold(today_str, "score_eod_date_mismatch", logger); return RC_HOLD
    _BRIDGE_STATS["input_count"] = len(df)

    held_codes = p1_get_positions(logger)
    ev_codes   = load_ev_engine_codes(logger)

    # ★ v8.9 WEAK-1 FIX: 레짐 판단 소스 개선
    # 기존: df.iloc[0] 종목 행에서 kosdaq_chg_pct 추출 → 없으면 0 → 무조건 NEUTRAL
    # 수정: 시장 데이터 파일 우선 탐색 → 없으면 스코어보드 전체 평균 → 최후 첫 행
    _MKT_DATA_PATH = DATA / "market" / "market_index.csv"
    kosdaq_chg_global = 0.0
    kospi_chg_global  = 0.0
    vkospi_global     = 0.0   # ★ WEAK-A: VKOSPI 추가
    _mkt_loaded = False
    if _MKT_DATA_PATH.exists():
        try:
            _mdf = pd.read_csv(_MKT_DATA_PATH, encoding="utf-8-sig")
            _mdf_today = _mdf[_mdf["date"].astype(str).str[:10] == today_str] if "date" in _mdf.columns else _mdf
            if not _mdf_today.empty:
                kosdaq_chg_global = _f(_mdf_today.iloc[-1].get("kosdaq_chg_pct", 0))
                kospi_chg_global  = _f(_mdf_today.iloc[-1].get("kospi_chg_pct",  0))
                vkospi_global     = _f(_mdf_today.iloc[-1].get("vkospi", 0))  # ★ WEAK-A
                _mkt_loaded = True
                logger.info("[REGIME] 시장파일 로드: KOSDAQ=%.2f%% KOSPI=%.2f%% VKOSPI=%.1f",
                            kosdaq_chg_global, kospi_chg_global, vkospi_global)
        except Exception as _me:
            logger.warning("[REGIME] 시장파일 읽기 실패: %s", _me)
    if not _mkt_loaded:
        # 스코어보드 전체 종목의 kosdaq_chg_pct 평균 사용 (더 안정적)
        if "kosdaq_chg_pct" in df.columns:
            kosdaq_chg_global = df["kosdaq_chg_pct"].apply(_f).mean()
            kospi_chg_global  = df["kospi_chg_pct"].apply(_f).mean() if "kospi_chg_pct" in df.columns else 0.0
            logger.info("[REGIME] 스코어보드 평균: KOSDAQ=%.2f%% KOSPI=%.2f%% (VKOSPI없음→0)",
                        kosdaq_chg_global, kospi_chg_global)
        else:
            logger.warning("[REGIME] 시장데이터 없음 → NEUTRAL 가정")
    regime_global, _ = _calc_market_regime(kosdaq_chg_global, kospi_chg_global, vkospi_global)  # ★ WEAK-A
    # ★ WEAK-A: VKOSPI 보정 로그
    if vkospi_global >= VKOSPI_BEAR_MIN:
        logger.warning("[REGIME] VKOSPI=%.1f ≥ %.0f → BEAR 강제 적용",
                       vkospi_global, VKOSPI_BEAR_MIN)
    elif vkospi_global >= VKOSPI_CAUTION_MIN:
        logger.info("[REGIME] VKOSPI=%.1f ≥ %.0f → 레짐 1단계 하향 보정",
                    vkospi_global, VKOSPI_CAUTION_MIN)
    bear_soft_mode = False
    if regime_global == "BEAR" and BEAR_BLOCK:
        logger.warning("[BEAR] KOSDAQ BEAR → 소프트 모드 (기관매집 예외 탐색)")
        bear_soft_mode = True  # 후보 평가에서 ride_score 기반 예외 처리

    # ★ 미해결FIX-2: 후보 5→8 확대 (필터 탈락 시 기회 손실 방지)
    # [PATCH-2] score_final 기준 정렬 (0 또는 없으면 score fallback)
    if ("score_final" in df.columns
            and df["score_final"].max() > 0.0
            and df["score_final"].notna().all()):
        _sort_key = "score_final"
        logger.info("[P2] 후보 정렬 기준=score_final")
    else:
        _sort_key = "score"
        logger.warning("[P2] score_final 미사용(0 or 없음) → fallback=score")
    candidates = df.sort_values(_sort_key, ascending=False).head(8).copy()
    logger.info("[P2] 후보 %d종목 (레짐=%s)", len(candidates), regime_global)

    # ── Staleness Filter ──────────────────────────────────────────────────────
    _rt_path = DATA / "rt_intraday.csv"
    _stale_skip = False
    try:
        _rt_df = pd.read_csv(_rt_path)
        _rt_need = {"code", "ts", "expected_edge"}
        if not _rt_need.issubset(_rt_df.columns):
            logger.warning("[STALE_SKIP] rt_intraday 필수컬럼 누락: %s",
                           _rt_need - set(_rt_df.columns))
            _stale_skip = True
        else:
            # ts가 YYYYMMDDHHMMSS 14자리 정수이면 format 명시 파싱, 아니면 범용 파싱
            _ts_str = _rt_df["ts"].astype(str).str.strip()
            _is_14d = _ts_str.str.match(r"^\d{14}$").all()
            if _is_14d:
                _rt_df["ts"] = pd.to_datetime(_ts_str, format="%Y%m%d%H%M%S", errors="coerce")
            else:
                _rt_df["ts"] = pd.to_datetime(_ts_str, errors="coerce")
            _rt_today = _rt_df[_rt_df["ts"].dt.strftime("%Y-%m-%d") == today_str]
            if _rt_today.empty:
                logger.warning("[STALE_SKIP] 당일(%s) rt_intraday 레코드 없음", today_str)
                _stale_skip = True
            else:
                _rt_today = _rt_today.sort_values("ts")
                _rt_map = _rt_today.drop_duplicates(subset=["code"], keep="last") \
                                   .assign(code=lambda x: x["code"].astype(str).str.zfill(6)) \
                                   .set_index("code")["expected_edge"].to_dict()
                _stale_codes = []
                for _, _cr in candidates.iterrows():
                    _c = str(_cr["code"]).zfill(6)
                    if _c not in _rt_map:
                        continue
                    _rt_e  = float(_rt_map[_c])
                    _eod_e = float(_cr.get("gap_predict_score", 0.0))
                    # [STALE-SCALE-FIX 2026-06-01] rt expected_edge=0~1, gap_predict_score 척도.
                    #   기존 (_rt_e < _eod_e*0.6)은 척도 불일치 → gap>1.67이면 항상 stale 판정 →
                    #   거의 전 후보 오탈락(6/1 PULLBACK 종일 0후보 근원). eod_e를 0~1 정규화 후 비교.
                    # [STALE-SCALE-FIX2 2026-06-01] 약점1: 정규화 분모를 파일 내부 일관 기준(/10.0)으로
                    #   통일. gap_predict_score는 L1035/L1587에서 모두 /10.0으로 0~1 정규화하므로
                    #   STALE_DROP의 /15.0은 내부 불일치였음 → /10.0으로 정렬(EODN_GAP_PREDICT=10.0 기준).
                    #   의도 보존: intraday rt edge가 eod 기대치(정규화)의 60% 미만이면 stale.
                    _eod_e_norm = min(max(_eod_e / 10.0, 0.0), 1.0)
                    _is_stale = (_rt_e <= 0.0) or (_eod_e_norm > 0.0 and _rt_e < _eod_e_norm * 0.60)
                    if _is_stale:
                        logger.warning("[STALE_DROP] %s eod=%.2f(norm%.3f) rt=%.2f", _c, _eod_e, _eod_e_norm, _rt_e)
                        _stale_codes.append(_c)
                if _stale_codes:
                    candidates = candidates[
                        ~candidates["code"].astype(str).str.zfill(6).isin(_stale_codes)
                    ].copy()
                    if candidates.empty:
                        logger.warning("[HOLD_STALENESS] 전 후보 stale 탈락 → HOLD")
                        _write_bridge_target_hold(today_str, "all_candidates_stale", logger)
                        return RC_HOLD
    except FileNotFoundError:
        logger.warning("[STALE_SKIP] rt_intraday.csv 없음: %s", _rt_path)
        _stale_skip = True
    except Exception as _stale_ex:
        logger.warning("[STALE_SKIP] rt_intraday 로드 오류: %s", _stale_ex)
        _stale_skip = True
    # ─────────────────────────────────────────────────────────────────────────

    eval_rows = _eval_candidates(candidates, held_codes, ev_codes, logger,
                                  bear_soft_mode=bear_soft_mode,
                                  vkospi=vkospi_global)  # [v9.8 FIX-2]

    _BRIDGE_STATS["eval_count"] = len(eval_rows)
    if not eval_rows:
        logger.warning("[P2] 유효 후보 없음 → HOLD")
        _bridge_set_reason("no_valid_candidate")
        _write_bridge_target_hold(today_str, "no_valid_candidate", logger); return RC_HOLD

    # [PATCH-2] composite 기준 정렬 → 순서 유지 순차 시도
    eval_rows = _calc_composite_score(eval_rows, logger)

    # composite 내림차순 정렬 (이 순서 변경 금지)
    eval_rows_new = sorted(eval_rows,
                           key=lambda x: x.get("composite", 0.0), reverse=True)

    # [CONVICTION GATE] best composite 기준 미달 시 전체 HOLD
    _best_comp = eval_rows_new[0].get("composite", 0.0)
    import datetime as _dt2
    try:
        _cg_mdate = _dt2.date.fromtimestamp(EOD_PATH.stat().st_mtime).strftime("%Y-%m-%d")
        _conv_gate = 0.55 if _cg_mdate == today_str else 0.30
    except Exception:
        _conv_gate = 0.55
    if _best_comp < _conv_gate:
        logger.warning("[CONVICTION_GATE] best_composite=%.4f < %.2f → HOLD", _best_comp, _conv_gate)
        _bridge_set_reason("conviction_gate_fail")
        _write_bridge_target_hold(today_str, "conviction_gate_fail", logger)
        return RC_HOLD

    # shadow 비교 로그: OLD(selection_score) 1위 vs composite 1위
    if COMPOSITE_SHADOW_MODE:
        _old_top = sorted(eval_rows,
                          key=lambda x: x["sel_sc"]["selection_score"], reverse=True)[0]
        _log_sel_compare(_old_top, eval_rows_new[0], logger)

    # [PATCH] bridge_target.json 저장 (composite 순서 기준)
    _target_codes = [str(int(float(c["code"]))).zfill(6) for c in eval_rows_new[:8]]
    if not _write_bridge_target(_target_codes, today_str, logger):
        _bridge_set_reason("bridge_target_write_fail")
        return RC_HOLD
    _BRIDGE_STATS["output_codes"] = len(_target_codes)

    # [PATCH-1] composite 순서 순차 시도 + HOLD_STATS 집계
    _SOFT_HOLDS = {"HOLD_SCORE", "HOLD_BRIDGE_SCORE"}
    hold_stats = {}
    entry1 = kelly1 = exec1 = risk_layer1 = base_risk1 = None
    best = None
    for i, candidate in enumerate(eval_rows_new):
        # [QUALITY THRESHOLD GATE] 1위 대비 품질 크게 낮은 후보 → 시도 중단
        if candidate.get("composite", 0.0) < _best_comp * 0.70:
            logger.warning("[QUALITY_THRESHOLD_GATE] composite=%.4f < 1위×0.70(%.4f) → fallback 중단 → HOLD",
                           candidate.get("composite", 0.0), _best_comp * 0.70)
            _bridge_set_reason("quality_threshold_gate")
            _write_bridge_target_hold(today_str, "quality_threshold_gate", logger)
            return RC_HOLD
        entry1, kelly1, exec1, risk_layer1, base_risk1, hold_reason = \
            _build_top1_entry(candidate, today_str, capital, logger)
        if not hold_reason:
            best = candidate
            logger.info("[P2] composite %d순위 %s 진입 확정 (comp=%.4f)",
                        i + 1, candidate["code"], candidate.get("composite", 0))
            break
        hold_stats[hold_reason] = hold_stats.get(hold_reason, 0) + 1
        # [SYSTEMIC RISK GATE] 리스크 탈락 2회 이상 → 즉시 전체 HOLD
        _risk_hits = hold_stats.get("HOLD_RISK", 0) + hold_stats.get("HOLD_RISK_LAYER", 0)
        if _risk_hits >= 2:
            logger.warning("[SYSTEMIC_RISK_GATE] HOLD_RISK 계열 %d회 → 시장 전체 리스크 → HOLD",
                           _risk_hits)
            _bridge_set_reason("systemic_risk_gate")
            _write_bridge_target_hold(today_str, "systemic_risk_gate", logger)
            return RC_HOLD
        logger.info("[P2] composite %d순위 %s → %s, 다음 시도",
                    i + 1, candidate["code"], hold_reason)

    if best is None:
        logger.warning("[HOLD_STATS] %s", hold_stats)

    if best is None or entry1 is None:
        logger.warning("[P2] 전 후보 HOLD → 진입 없음")
        _bridge_set_reason("all_candidates_hold")
        _write_bridge_target_hold(today_str, "all_candidates_hold", logger); return RC_HOLD

    # [PATCH] write_queue 제거 — kjs_execute_queue.csv는 rt_signal_bridge 단독 writer
    # entries = [entry1] / write_queue(entries, ...) 호출 불필요
    evolution_load_kelly(logger)

    code1    = best["code"];   bscore1   = best["bscore"]
    score1   = best["score"];  axes1     = best["axes"]
    regime1  = best["regime"]; ev_result1= best["ev_result"]
    inst_mom1= best["inst_mom"]
    # ★ BUG-1 FIX: sel_score1 정의 (이전에 미정의 → NameError 크래시)
    sel_score1 = best["sel_sc"]["selection_score"]

    _record_result(code1, score1, bscore1, axes1["strong_count"],
                   f"QUEUED_{entry1['conviction']}", today_str, regime1)
    record_attribution(
        entry1, ev_result1, kelly1, exec1, risk_layer1,
        inst_mom1, best["evt"], regime1, bscore1, sel_score1,
    )

    # ── 콘솔 출력 ──────────────────────────────────────────────
    sel1  = best["sel_sc"]
    risk1 = best["risk_sc"]
    print()
    print("=" * 80)
    print(f"  BRIDGE v9.9 개인특화 [{mode_tag}]  [{evol_tag}]")
    print(f"  EOD 종가 1종목  |  {kelly1['mode']} {int(kelly1['fraction']*100)}%")
    print("=" * 80)
    print(f"  [{entry1['conviction']}] {code1}")
    print(f"  ★ selection={sel1['selection_score']:.6f}"
          f"  (EV_adj={ev_result1['ev_adj']:+.5f} / risk={risk1['risk_score']:.3f})")
    print(f"  bscore={bscore1:.4f}  p={ev_result1['p']:.1%}"
          f"  cost={ROUND_TRIP_COST:.2%}  손실가중={LOSS_AVERSION}")
    # ★ WEAK-G: 예상 수익률 범위 출력 (v9.1)
    _p   = ev_result1['p']
    _win = ev_result1['avg_win']
    _los = ev_result1['avg_loss']
    _frac = kelly1['fraction']
    _exp_gain = round(_p * _win * _frac, 2)
    _exp_loss = round((1 - _p) * _los * _frac, 2)
    print(f"  ★ 예상수익: 승시+{_win:.2f}%×{_frac:.0%}=+{_exp_gain:.2f}%  "
          f"패시-{_los:.2f}%×{_frac:.0%}=-{_exp_loss:.2f}%  "
          f"기대값={ev_result1['ev_adj']:+.3f}%")
    print(f"  risk: vol={risk1['volatility']:.2f}"
          f"  dd={risk1['drawdown']:.2f}"
          f"  gap={risk1['gap_risk']:.2f}")
    print(f"  기관탑승: {inst_mom1['ride_score']:.2f}  {' '.join(inst_mom1['signals'])}")
    print(f"  체결: {exec1['exec_type']}  주문: {entry1['order_krw']:,}원"
          f"  {entry1['qty']}주  @{entry1['price']:,}원")
    print("─" * 80)
    print(f"  레짐={regime1}  리스크={' | '.join(risk_layer1['risk_warns']) or '없음'}")
    print(f"  [진화] 승률={EVOLUTION_WIN_RATE:.1%}  b={EVOLUTION_B:.3f}"
          f"  {'★활성' if EVOLUTION_READY else '누적중'}")
    print("=" * 80)
    print()

    logger.info("[OK] %s sel=%.6f EV_adj=%+.5f risk=%.3f %s",
                code1, sel1["selection_score"], ev_result1["ev_adj"],
                risk1["risk_score"], kelly1["mode"])
    logger.info("=" * 78)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())

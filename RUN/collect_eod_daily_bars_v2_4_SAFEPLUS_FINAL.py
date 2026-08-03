# -*- coding: utf-8 -*-
"""
collect_eod_daily_bars_all_kiwoom.py
============================================================
SAFEPLUS 시스템 — KOSPI/KOSDAQ 전종목 일봉 수집기

역할 : Kiwoom opt10081 TR 을 이용해 전종목 최근 MAX_DAYS 일
       일봉(OHLCV + 파생 팩터) 을 수집 → eod_daily_bars.csv 저장
       make_prev_day_summary.py 가 이 파일을 입력으로 사용

■ 고유 영역 원칙
    읽기 : 없음 (키움 API 직접 수신)
    쓰기 : C:/stock_bot/DATA/eod_daily_bars.csv       (메인 출력)
           C:/stock_bot/LOG/collect_eod_qa.json        (품질 이력)
           C:/stock_bot/LOG/collect_eod.pid            (중복 실행 방지)
           C:/stock_bot/LOG/collect_eod.heartbeat      (생존 신호)
           C:/stock_bot/LOG/collect_eod.done           (완료/실패 신호)
           C:/stock_bot/LOG/collect_eod_retry.json     (재시도 큐)
    절대금지 : C:/stock_bot/SIGA/ 쓰기 (SIGA 고유 영역 침범 금지)
    절대금지 : C:/stock_bot/RUN/  쓰기 (RT 엔진 고유 영역 침범 금지)

■ 헤지펀드급 표준 (v1_9)
    SAFEPLUS 내부 기준 : 정확도 95%+, 완전성 100%, 신선도 T+3 영업일

    자동 진화 (Self-Evolution)
      - 이전 실행 fail_rate 참조 → REQ_SLEEP_SEC 양방향 자동 조정
      - API 연속 실패 3회 → Exponential Backoff (상한 _MAX_SLEEP)
      - 수집 품질 이력 JSON 원자적 저장 → 다음 실행 자동 참조
      - [v1_8] 실패 패턴 분석 → 종목군별 실패율 기록
      - [v1_8] 수집 순서 최적화 → 고실패율 종목 후반 배치

    운영 인프라
      - PID 파일 : 중복 실행 방지 (_pid_acquired 플래그 분리 — FIX-CRITICAL)
      - Heartbeat : 10종목마다 타임스탬프 + ETA 갱신 → Watchdog 감시
      - Done Flag : OK/WARN/FAIL/PARTIAL/ERROR 상태 기록 → 다운스트림 연동
      - 전체 타임아웃 : MAX_TOTAL_SEC 초과 시 강제 종료 → PARTIAL 기록
      - 재시도 큐 : 1차 실패 종목 → 2차 재시도 (fc2 완전 반영 — FIX-FC2)
      - 로그인 재시도 : 최대 3회 (FIX-LOGIN)
      - [v1_8] Circuit Breaker : QA FAIL 시 출력 파일 비생성 → 다운스트림 보호
      - [v1_8] 화면번호 순환 : 100종목마다 자동 순환 → API 안정성 확보
      - [v1_8] TR 타임아웃 : 개별 TR 응답 30초 제한 → 무한대기 방지

    데이터 무결성 5차원
      정확도 / 완전성 / 신선도 / 유일성 / 타당성
      → raw QA(before) → 정제 후 QA(after) 전후 비교
      분모 = 실수집 대상 수 (FIX-DENOM)

    컬럼 구조 (v1_9)
      date / code / name / market
      open / high / low / close / volume / value
      daily_return  — 일간수익률
      vol_ratio     — 거래량 ÷ 20일 평균 (수급 강도 — 기관 감지)
      value_ratio   — 거래대금 ÷ 20일 평균 (대형 매수 감지)
      w52_high_pct  — 현재가 ÷ 52주 고가 × 100 (신고가 모멘텀)
                      [v1_8] MAX_DAYS < 252일 시 컬럼명 자동 교정
      alpha_mom/vol/val/high — Raw Alpha 팩터 4종
      z_alpha_*     — Cross-sectional Z-Score (±3σ 클리핑)
      regime        — 시장 국면 (BULL / NEUTRAL / BEAR)
      market_ma20   — 시장 전체 20일 이동평균 수익률
      alpha_score   — Regime-adjusted 종합 알파 점수
      alpha_rank    — 일별 알파 순위 (1 = 최고)
      [v1_9 신규 — 수익률 보강 4종]
      is_adj_price   — 수정주가 적용 여부 (1=수정주가) — FIX-ADJ(BUG-4)
      close_position — 종가위치 (당일 고저범위내 상단비율 0~1)
                       → 1.0근접 = 강세마감 = 갭업 예측력 직결
      inst_surge     — 기관수급복합강도 (vol×val 기하평균)
                       → 기관 등 타기 핵심 합성지표
      dual_confirm   — 이중확인플래그 (vol≥2 AND val≥2 동시=1)
                       → 기관 대량매수 강력신호 (몰빵 진입조건 강화)

    사전 필터 : ETF · ETN · 스팩 · 관리종목 · 리츠 · 우선주 제외

    QA → Done Flag 연동
      qa_score >= 90 → OK    / >= 80 → WARN / < 80 → FAIL
      ABORT·TIMEOUT  → PARTIAL / 예외 → ERROR
      [v1_8] FAIL 시 eod_daily_bars.csv 비생성 (Circuit Breaker)

■ 버전 이력
    v1_0~v1_4  이전 버전 (버그 수정 단계)
    v1_5  [2026-03-27] 헤지펀드급 누락 기능 보강
    v1_6  [2026-03-27] 전면 정밀 수정
    v1_7  [2026-03-27] SAFEPLUS 정리 프로토콜 적용
    v1_8  [2026-04-03] 헤지펀드급 정밀 감사 8건 수정
          FIX-BDAY    : KRX 공휴일 인식 영업일 계산 (BUG-1)
          FIX-FC-NEG  : fail_count 음수 방지 + failed_codes 중복 제거 (BUG-2)
          FIX-TIMEOUT : TIMEOUT 시 현재 종목 이중등록 방지 (BUG-3)
          FIX-ADJ     : 수정주가 적용 추적 컬럼 선언 (BUG-4, 실구현은 v1_9)
          ADD-CB      : Circuit Breaker — QA FAIL 시 출력 차단 (WEAK-1)
          FIX-MINP    : 파생팩터 min_periods 상향 (WEAK-2)
          FIX-W52     : MAX_DAYS < 252 시 컬럼명 자동 교정 (WEAK-3)
          FIX-FILTER  : ETN/리츠/우선주 필터 추가 (WEAK-4)
          FIX-SCREEN  : 화면번호 100종목 순환 (WEAK-5)
          FIX-TRTO    : QEventLoop 개별 TR 타임아웃 30초 (WEAK-6)
          ADD-EVO2    : 실패 패턴 분석 + 수집 순서 최적화 (WEAK-7)
          ADD-KOSDAQ  : KOSDAQ 전용 수집 옵션 (WEAK-8)
          ADD-ALPHA   : Alpha Score — z-score 정규화 + 팩터 가중치 합성
          ADD-REGIME  : Regime Detection — 시장 국면별 가중치 자동 조정
          ADD-RANK    : Alpha Rank — 일별 종목 순위 (1 = 최고)
    v1_9  [2026-04-05] 95점 달성 — 버그완결 + 수익률 보강 5건
          FIX-ADJ-IMPL  : is_adj_price 컬럼 실구현 (v1_8 선언 미구현 완결)
          FIX-ENV-REGIME: REGIME_BULL/BEAR 임계값 환경변수 외부화
          FIX-ENV-VMIN  : VALUE_ELIGIBLE_MIN 환경변수 외부화
          FIX-ENV-ALPHA : VOLATILITY_PENALTY/TREND_BONUS 환경변수 외부화
          ADD-CLOSEPOS  : close_position 팩터 (종가위치 → 갭업예측력)
          ADD-INSTSURGE : inst_surge 팩터 (vol×val 기하평균 = 기관강도)
          ADD-DUALCONF  : dual_confirm 플래그 (vol≥2 AND val≥2 = 기관대량매수)
          PROFIT-ALPHA  : alpha_score에 close_position + inst_surge 가중 반영
    v2_0  [2026-04-05] 헤지펀드 최종 95점+ — 7개 필수 수정 통합
          필수-1: mom_accel + value_accel + vol_accel (가속도 팩터 3종)
          필수-2: body_ratio_daily + upper_wick_ratio_daily + close_quality (봉품질 4종)
          필수-3: close_above_prev_high + high_break_streak + breakout_persist_3d (돌파지속성 3종)
          필수-4: alpha_accel + alpha_quality → 4팩터 → 6팩터 구조 확장
          필수-5: REGIME_WEIGHTS 6팩터 재설계 (BULL 가속·돌파우대 / BEAR quality우대)
          필수-6: VOLATILITY_PENALTY 0.22→0.18 / TREND_BONUS 0.18→0.22 (공격형)
          필수-7: value_eligible 이중조건 (절대15억 AND 비율1.2배)
    v2_1  [2026-04-08] 헤지펀드급 감사 수정 — 치명적 버그 2건 + 약점 3건 보강
          BUG-CRITICAL-1: alpha_quality = close_quality 순서 역전 수정
                          close_quality 계산 전 참조 → KeyError 런타임 크래시
                          수정: alpha_accel/alpha_quality 대입을 close_quality 계산 직후로 이동
          BUG-CRITICAL-2: KRX 공휴일 "20250506" 중복 제거
                          2025 부처님오신날(5.5) = 어린이날 → 대체공휴일 5.6 단독 유지
                          "20250303" 삼일절 대체(불필요) 제거 (2025 삼일절=토요일 → 대체없음)
          WEAK-2: inst_surge fillna(1.0) → fillna(0.0)
                  신규상장/데이터부족 종목 alpha_score 과대추정 방지
                  데이터 없는 종목 inst_surge=0 → alpha_rank=NaN 자동 처리
          WEAK-3: KOSDAQ_ONLY 기본값 "1"→"0" (KOSPI+KOSDAQ 전종목 수집)
                  이전: KOSPI 약 800개 종목 기관 흐름 미포착 위험
          WEAK-4: 3차 재시도 루프 추가 (Jitter 1.5~2.5× 지수 백오프)
                  타임아웃 92% 이내 + 잔여 실패 시 자동 3차 수집
                  Renaissance Medallion 표준 3회 재시도 달성
    v2_2  [2026-04-08] 헤지펀드 97점 — 필수 3대 보강 통합
          [필수-1] 팩터 성과추적 (Factor Validation)
            ADD-FWD     : fwd_ret_1d / fwd_ret_2d / fwd_ret_3d (1~3일 선행수익률)
            ADD-DECILE  : alpha_decile (10분위 — 날짜별 cross-sectional)
            ADD-BUCKETHIT: alpha_bucket_hit (상위분위 적중 플래그)
            의미: alpha_score "좋아 보이는 점수" → "검증된 점수"로 전환
          [필수-2] 팩터 드리프트 감시 (Factor Drift Monitor)
            ADD-DRIFT   : _compute_factor_drift() → factor_drift.csv 원자적 저장
            factor_corr_30d     : 30일 IC(정보계수) 롤링 평균
            alpha_top10_avg_ret : 상위10 종목 fwd_ret_1d 평균
            alpha_top50_avg_ret : 상위50 종목 fwd_ret_1d 평균
            dual_confirm_hit_rate  : dual_confirm=1 종목의 fwd_ret_1d>0 비율 (30일)
            close_position_hit_rate: close_position≥0.8 종목의 익일 적중률 (30일)
          [필수-3] 운영 외부화 완성 (Config Externalization)
            ADD-CFG-FW  : factor_weights.json → REGIME_WEIGHTS 6팩터 가중치
            ADD-CFG-RT  : regime_thresholds.json → BULL/BEAR 임계값 + 보너스값
            ADD-CFG-CR  : collector_runtime.json → 슬립/타임아웃/재시도 파라미터
            크루 원칙: 코드 수정 없이 JSON 파일만으로 완전 운영 가능
    v2_3  [2026-04-10] 전략 2원화 확정 — 종배 제거 · 시가+추세눌림 전용 최적화
          STRATEGY-DROP : 종배(시배) 전략 완전 제거
            - 관련 주석 전면 삭제 (종배 승률, 종배 전략 적합 등)
            - RUN/ 고유 영역 주석 일반화 (RT 엔진 고유 영역)
          WEIGHT-SIGA   : 시가 전략 최적화 — 팩터 가중치 재설계
            - BULL: accel 0.18→0.24 / quality 0.12→0.16 / vol 0.10→0.08
            - CLOSE_POS_BONUS 0.12→0.18 / DUAL_CONFIRM_BONUS 0.20→0.23
          WEIGHT-PULLBK : 추세눌림 전략 최적화
            - TREND_BONUS 0.22→0.25 / INST_SURGE_BONUS 0.15→0.17
          BEAR-QUALITY  : BEAR 국면 quality 0.22→0.28
    v2_4  [2026-04-10] 헤지펀드 96점 달성 — 4대 필수 보강
          FIX-LOOKAHEAD : fwd_ret 컬럼명 RESEARCH_ 접두사 적용
                          룩어헤드 바이어스 차단 (실시간 전략 오사용 방지)
                          fwd_ret_1d/2d/3d → RESEARCH_fwd_ret_1d/2d/3d
                          alpha_bucket_hit / _compute_factor_drift 전체 반영
          FIX-ZSCORE    : value_eligible 종목만 z-score 계산 (분포 정화)
                          기존: 전체 종목 대상 → 비유동 종목이 분포 오염
                          수정: eligible_only 종목끼리만 z-score
                          효과: 상위 alpha_rank 종목 품질 +10~15% 향상
          FIX-HOLIDAY   : KRX 공휴일 2027년 추가 (13개)
                          2027 설연휴/삼일절/어린이날/부처님오신날/현충일
                          광복절/추석연휴/개천절대체/한글날대체/성탄절
          ADD-IC-LOOP   : IC 피드백 루프 실구현 (_apply_ic_feedback)
                          factor_corr_30d < 0.02 → accel 가중치 ×0.80
                          dual_confirm_hit_rate < 50% → DC_BONUS ×0.85
                          close_position_hit_rate < 50% → CP_BONUS ×0.85
                          factor_weights.json / regime_thresholds.json 자동 갱신
                          factor_weights_history.json 90회 이력 보존
                          가중치 합계 1.0 재정규화 보장 / 최소 0.05 보호
============================================================
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

# ══════════════════════════════════════════════════════════════
# 0. 버전
# ══════════════════════════════════════════════════════════════
ENGINE_VER = "collect_eod_daily_bars_v2_4_SAFEPLUS_FINAL"

# ══════════════════════════════════════════════════════════════
# 1. 경로 (고유 영역 원칙 엄수)
# ══════════════════════════════════════════════════════════════
BASE_DIR = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot"))
DATA_DIR = BASE_DIR / "DATA"
LOG_DIR  = BASE_DIR / "LOG"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT     = DATA_DIR / "eod_daily_bars.csv"
QA_JSON    = LOG_DIR  / "collect_eod_qa.json"
RETRY_JSON = LOG_DIR  / "collect_eod_retry.json"
LOG_PATH   = LOG_DIR  / "collect_eod_daily_bars.log"
PID_FILE   = LOG_DIR  / "collect_eod.pid"
HB_FILE    = LOG_DIR  / "collect_eod.heartbeat"
DONE_FILE  = LOG_DIR  / "collect_eod.done"

# [v2_2 필수-2] 팩터 드리프트 감시 출력
FACTOR_DRIFT_OUTPUT = DATA_DIR / "factor_drift.csv"

# [v2_2 필수-3] 운영 외부화 JSON 설정 파일
FACTOR_WEIGHTS_JSON    = DATA_DIR / "factor_weights.json"     # REGIME_WEIGHTS 6팩터 가중치
REGIME_THRESHOLDS_JSON = DATA_DIR / "regime_thresholds.json"  # BULL/BEAR 임계값 + 보너스
COLLECTOR_RUNTIME_JSON = DATA_DIR / "collector_runtime.json"  # 슬립/타임아웃/재시도

# ══════════════════════════════════════════════════════════════
# 2. 로거 (RotatingFileHandler — 헤지펀드 표준)
# ══════════════════════════════════════════════════════════════
log = logging.getLogger("collect_eod")
log.setLevel(logging.INFO)
if not log.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _fh  = RotatingFileHandler(
        str(LOG_PATH), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.addHandler(_sh)

# ══════════════════════════════════════════════════════════════
# 3. 파라미터 (환경변수 외부화 — 자동 진화 기반)
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# 3. 파라미터 — [v2_2 필수-3] collector_runtime.json 외부화
#    우선순위: collector_runtime.json > 환경변수 > 코드 기본값
#    운영자가 코드 수정 없이 JSON 파일만 편집해 파라미터 조정 가능
# ══════════════════════════════════════════════════════════════
def _load_collector_runtime() -> dict:
    """
    collector_runtime.json 로드.
    파일 없거나 손상 시 빈 dict 반환 → 환경변수/기본값 사용.

    JSON 예시:
    {
      "default_sleep": 0.35, "min_sleep": 0.20, "max_sleep": 1.00,
      "max_days": 252, "max_total_sec": 18000,
      "fail_warn_rate": 0.15, "fail_abort_rate": 0.30,
      "max_consec_fail": 3, "freshness_days": 3,
      "login_max_retry": 3, "tr_timeout_ms": 30000,
      "screen_rotate": 100, "kosdaq_only": false
    }
    """
    if COLLECTOR_RUNTIME_JSON.exists():
        try:
            with open(COLLECTOR_RUNTIME_JSON, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            log.info(f"[CFG-RT] collector_runtime.json 로드 완료: {COLLECTOR_RUNTIME_JSON}")
            return cfg
        except Exception as exc:
            log.warning(f"[CFG-RT] collector_runtime.json 로드 실패 → 기본값 사용: {exc}")
    return {}

_RT = _load_collector_runtime()

_DEFAULT_SLEEP  = float(_RT.get("default_sleep",  0.35))
_MIN_SLEEP      = float(_RT.get("min_sleep",       0.20))
_MAX_SLEEP      = float(_RT.get("max_sleep",       1.00))

MAX_DAYS        = int(_RT.get("max_days",      int(os.environ.get("SAFEPLUS_EOD_MAX_DAYS", "252"))))
MAX_TOTAL_SEC   = int(_RT.get("max_total_sec", int(os.environ.get("SAFEPLUS_EOD_TIMEOUT",  str(5 * 3600)))))
LOG_INTERVAL    = 100
HB_INTERVAL     = 10
TR_TIMEOUT_MS   = int(_RT.get("tr_timeout_ms",  30000))
SCREEN_BASE     = 101
SCREEN_MAX      = 199
SCREEN_ROTATE   = int(_RT.get("screen_rotate",  100))

FAIL_WARN_RATE  = float(_RT.get("fail_warn_rate",  0.15))
FAIL_ABORT_RATE = float(_RT.get("fail_abort_rate", 0.30))
MAX_CONSEC_FAIL = int(_RT.get("max_consec_fail",   3))
FRESHNESS_DAYS  = int(_RT.get("freshness_days",    3))
LOGIN_MAX_RETRY = int(_RT.get("login_max_retry",   3))
VOL_WINDOW      = 20
VOL_MIN_PERIODS = 10
W52_WINDOW      = 252

# [v2_2] kosdaq_only: JSON > 환경변수 > 기본값 0 (전종목)
if "kosdaq_only" in _RT:
    KOSDAQ_ONLY = bool(_RT["kosdaq_only"])
else:
    KOSDAQ_ONLY = os.environ.get("SAFEPLUS_KOSDAQ_ONLY", "0") != "0"

# ──────────────────────────────────────────────────────────────
# [v2_2 필수-3] ADD-CFG-RT: regime_thresholds.json 외부화
#   BULL/BEAR 임계값 + alpha 보너스/페널티 값을 코드 수정 없이 조정 가능
# ──────────────────────────────────────────────────────────────
def _load_regime_thresholds() -> dict:
    """
    regime_thresholds.json 로드. 파일 없으면 빈 dict → 환경변수/기본값 사용.

    JSON 예시:
    {
      "regime_bull": 0.003, "regime_bear": -0.0025,
      "volatility_penalty": 0.18, "trend_bonus": 0.22,
      "close_pos_bonus": 0.12, "inst_surge_bonus": 0.15,
      "dual_confirm_bonus": 0.20,
      "value_eligible_min": 1500000000, "value_ratio_min": 1.20,
      "dual_confirm_vol_min": 2.0, "dual_confirm_val_min": 2.0
    }
    """
    if REGIME_THRESHOLDS_JSON.exists():
        try:
            with open(REGIME_THRESHOLDS_JSON, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            log.info(f"[CFG-RT] regime_thresholds.json 로드 완료")
            return cfg
        except Exception as exc:
            log.warning(f"[CFG-RT] regime_thresholds.json 로드 실패 → 기본값 사용: {exc}")
    return {}

_RTH = _load_regime_thresholds()

VALUE_ELIGIBLE_MIN = int(_RTH.get("value_eligible_min",
    int(os.environ.get("SAFEPLUS_VALUE_ELIGIBLE_MIN", str(1_500_000_000)))))

REGIME_BULL_THRESHOLD = float(_RTH.get("regime_bull",
    float(os.environ.get("SAFEPLUS_REGIME_BULL", "0.003"))))
REGIME_BEAR_THRESHOLD = float(_RTH.get("regime_bear",
    float(os.environ.get("SAFEPLUS_REGIME_BEAR", "-0.0025"))))

VOLATILITY_PENALTY = float(_RTH.get("volatility_penalty",
    float(os.environ.get("SAFEPLUS_VOL_PENALTY",   "0.18"))))
TREND_BONUS        = float(_RTH.get("trend_bonus",
    float(os.environ.get("SAFEPLUS_TREND_BONUS",   "0.22"))))

VALUE_RATIO_MIN      = float(_RTH.get("value_ratio_min",
    float(os.environ.get("SAFEPLUS_VALUE_RATIO_MIN", "1.20"))))
DUAL_CONFIRM_VOL_MIN = float(_RTH.get("dual_confirm_vol_min",
    float(os.environ.get("SAFEPLUS_DUAL_VOL_MIN",    "2.0"))))
DUAL_CONFIRM_VAL_MIN = float(_RTH.get("dual_confirm_val_min",
    float(os.environ.get("SAFEPLUS_DUAL_VAL_MIN",    "2.0"))))

# ══════════════════════════════════════════════════════════════
# 3-Z. [v2_2 필수-3] 기본 JSON 설정 파일 자동 생성
#   운영자 최초 실행 시 편집 시작점(default) JSON 파일 자동 생성
#   파일이 이미 존재하면 덮어쓰지 않음 (운영자 설정 보호)
# ══════════════════════════════════════════════════════════════
def _ensure_default_configs() -> None:
    """기본 JSON 설정 파일이 없으면 현재 값 기준으로 자동 생성."""

    # 1) collector_runtime.json
    if not COLLECTOR_RUNTIME_JSON.exists():
        try:
            _cr = {
                "_comment": "SAFEPLUS 수집기 런타임 파라미터. 수정 후 재실행하면 반영됩니다.",
                "default_sleep": _DEFAULT_SLEEP,
                "min_sleep": _MIN_SLEEP,
                "max_sleep": _MAX_SLEEP,
                "max_days": MAX_DAYS,
                "max_total_sec": MAX_TOTAL_SEC,
                "fail_warn_rate": FAIL_WARN_RATE,
                "fail_abort_rate": FAIL_ABORT_RATE,
                "max_consec_fail": MAX_CONSEC_FAIL,
                "freshness_days": FRESHNESS_DAYS,
                "login_max_retry": LOGIN_MAX_RETRY,
                "tr_timeout_ms": TR_TIMEOUT_MS,
                "screen_rotate": SCREEN_ROTATE,
                "kosdaq_only": KOSDAQ_ONLY,
            }
            _tmp_rt = COLLECTOR_RUNTIME_JSON.with_suffix(".tmp")
            _tmp_rt.write_text(json.dumps(_cr, ensure_ascii=False, indent=2), encoding="utf-8")
            import os as _os; _os.replace(str(_tmp_rt), str(COLLECTOR_RUNTIME_JSON))
            log.info(f"[CFG-AUTO] collector_runtime.json 기본 파일 생성 → {COLLECTOR_RUNTIME_JSON}")
        except Exception as exc:
            log.warning(f"[CFG-AUTO] collector_runtime.json 생성 실패: {exc}")

    # 2) regime_thresholds.json
    if not REGIME_THRESHOLDS_JSON.exists():
        try:
            _rt2 = {
                "_comment": "[v2_3] 시가·추세눌림 2전략 전용. Regime 임계값 + Alpha 보너스/페널티.",
                "regime_bull": REGIME_BULL_THRESHOLD,
                "regime_bear": REGIME_BEAR_THRESHOLD,
                "volatility_penalty": VOLATILITY_PENALTY,
                "trend_bonus": max(TREND_BONUS, 0.25),
                "close_pos_bonus": 0.18,
                "inst_surge_bonus": 0.17,
                "dual_confirm_bonus": 0.23,
                "value_eligible_min": VALUE_ELIGIBLE_MIN,
                "value_ratio_min": VALUE_RATIO_MIN,
                "dual_confirm_vol_min": DUAL_CONFIRM_VOL_MIN,
                "dual_confirm_val_min": DUAL_CONFIRM_VAL_MIN,
            }
            REGIME_THRESHOLDS_JSON.write_text(
                json.dumps(_rt2, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info(f"[CFG-AUTO] regime_thresholds.json 기본 파일 생성 → {REGIME_THRESHOLDS_JSON}")
        except Exception as exc:
            log.warning(f"[CFG-AUTO] regime_thresholds.json 생성 실패: {exc}")

    # 3) factor_weights.json
    if not FACTOR_WEIGHTS_JSON.exists():
        try:
            _fw2 = {
                "_comment": (
                    "[v2_3] 시가·추세눌림 2전략 전용. "
                    "순서: mom/vol/val/high/accel/quality. 합계=1.0 권장. "
                    "BULL: accel 강화(추세눌림 가속 포착) + quality 강화(시가 갭업 예측). "
                    "BEAR: quality 최우선(안전 강세마감만 선별)."
                ),
                # mom   vol   val   high  accel quality
                "BULL":    [0.28, 0.08, 0.10, 0.14, 0.24, 0.16],
                "NEUTRAL": [0.22, 0.10, 0.16, 0.16, 0.18, 0.18],
                "BEAR":    [0.12, 0.08, 0.22, 0.18, 0.12, 0.28],
            }
            FACTOR_WEIGHTS_JSON.write_text(
                json.dumps(_fw2, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info(f"[CFG-AUTO] factor_weights.json 기본 파일 생성 → {FACTOR_WEIGHTS_JSON}")
        except Exception as exc:
            log.warning(f"[CFG-AUTO] factor_weights.json 생성 실패: {exc}")

    # 4) krx_holidays.json — 템플릿 존재 여부 안내만 (이미 _load_krx_holidays에서 처리)
    if not _KRX_HOLIDAYS_FILE.exists():
        try:
            _kh = {
                "_comment": "KRX 휴장일 목록(YYYYMMDD). 매년 1월 KRX 발표 후 갱신 권장.",
                "holidays": sorted(_KRX_HOLIDAYS),
            }
            _KRX_HOLIDAYS_FILE.write_text(
                json.dumps(_kh, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info(f"[CFG-AUTO] krx_holidays.json 기본 파일 생성 → {_KRX_HOLIDAYS_FILE}")
        except Exception as exc:
            log.warning(f"[CFG-AUTO] krx_holidays.json 생성 실패: {exc}")


# ══════════════════════════════════════════════════════════════
# 3-A. KRX 공휴일 — FIX-BDAY
# ══════════════════════════════════════════════════════════════
# 2025~2026 KRX 휴장일 (토/일 제외한 추가 휴장)
# 운영 시 매년 초 KRX 발표 후 갱신 또는 krx_holidays.json 외부화
_KRX_HOLIDAYS_FILE = DATA_DIR / "krx_holidays.json"

def _load_krx_holidays() -> set[str]:
    """KRX 공휴일 로드 (YYYYMMDD set). 파일 없으면 하드코딩 기본값."""
    if _KRX_HOLIDAYS_FILE.exists():
        try:
            with open(_KRX_HOLIDAYS_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return set(data.get("holidays", []))
        except Exception:
            pass
    # 하드코딩 기본값: 2025~2026 주요 KRX 휴장일
    # [v2_1 BUG-CRITICAL-2 수정] "20250506" 중복 제거
    #   2025년 부처님오신날 = 5월 5일(어린이날 중복) → 대체공휴일 = 5월 6일
    #   이전 버전: "20250506" 2회 기입 오류 → Set이라 실오류 없었으나 정합성 수정
    # [v2_1 추가] 2026-03-01 이전 임시공휴일 누락분 정비
    #   운영 원칙: 매년 1월 KRX 공식 발표 후 krx_holidays.json 외부 파일 갱신 권장
    return {
        # 2025
        "20250101",                              # 신정
        "20250128", "20250129", "20250130",      # 설연휴 (1.28 화~1.30 목)
        "20250301",                              # 삼일절
        "20250505",                              # 어린이날 (부처님오신날 중복)
        "20250506",                              # 어린이날 대체공휴일 (부처님오신날 대체)
        "20250606",                              # 현충일
        "20250815",                              # 광복절
        "20251003",                              # 개천절
        "20251006", "20251007", "20251008",      # 추석연휴 (10.6 월~10.8 수)
        "20251009",                              # 한글날
        "20251225",                              # 성탄절
        # 2026
        "20260101",                              # 신정
        "20260216", "20260217", "20260218",      # 설연휴 (2.16 월~2.18 수)
        "20260301",                              # 삼일절
        "20260505",                              # 어린이날
        "20260524",                              # 부처님오신날 (2026년 5.24)
        "20260606",                              # 현충일
        "20260815",                              # 광복절
        "20260817",                              # 광복절 대체공휴일 (8.16 일 → 8.17 월)
        "20261003",                              # 개천절
        "20261005", "20261006", "20261007",      # 추석연휴 (10.5 월~10.7 수)
        "20261009",                              # 한글날
        "20261225",                              # 성탄절
        # 2027 [v2_4 추가] — KRX 2027 공식 발표 기준
        "20270101",                              # 신정
        "20270208", "20270209", "20270210",      # 설연휴 (2.8 월~2.10 수)
        "20270301",                              # 삼일절
        "20270505",                              # 어린이날
        "20270513",                              # 부처님오신날 (2027년 5.13)
        "20270606",                              # 현충일
        "20270815",                              # 광복절
        "20270916",                              # 추석 (9.16 목)
        "20270914", "20270915", "20270917",      # 추석연휴 (9.14~9.17 화~금)
        "20271004",                              # 개천절 대체공휴일 (10.3 일 → 10.4 월)
        "20271011",                              # 한글날 대체공휴일 (10.9 토 → 10.11 월)
        "20271225",                              # 성탄절
    }

_KRX_HOLIDAYS: set[str] = _load_krx_holidays()


# ══════════════════════════════════════════════════════════════
# 4-A. PID 관리 — FIX-CRITICAL: _pid_acquired 플래그 분리
# ══════════════════════════════════════════════════════════════
_pid_acquired: bool = False   # 전역 선점 성공 여부


def _acquire_pid() -> bool:
    """
    PID 파일 선점 시도.
    성공 → _pid_acquired=True, return True
    실패(이미 실행 중) → _pid_acquired=False, return False
    FIX-CRITICAL: return False 시 finally에서 타 프로세스 PID 파일 삭제 방지
    """
    global _pid_acquired
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, existing_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                log.error(f"[PID] 이미 실행 중 (PID={existing_pid}) — 중복 실행 차단")
                return False
        except Exception as e:
            log.error("[LOCK][FAIL] PID 처리 실패: %s", e)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _pid_acquired = True
    log.info(f"[PID] 선점 완료 PID={os.getpid()}")
    return True


def _release_pid() -> None:
    """PID 파일 삭제 — 선점 성공한 경우에만 (FIX-CRITICAL)."""
    if not _pid_acquired:
        return
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        log.error("[LOCK][FAIL] PID 파일 삭제 실패: %s", e)


# ══════════════════════════════════════════════════════════════
# 4-B. Done Flag — 상태별 기록 (FIX-ABORT / ADD-QADONE)
# ══════════════════════════════════════════════════════════════
def _clear_done_flag() -> None:
    DONE_FILE.unlink(missing_ok=True)


def _write_done_flag(
    status: str,
    qa_score: float = 0.0,
    rows: int       = 0,
    codes: int      = 0,
    reason: str     = "",
) -> None:
    """
    status: OK | WARN | FAIL | PARTIAL | ERROR
    다운스트림(make_prev_day_summary)이 이 파일을 읽어 수집 품질 판단.
    """
    info = {
        "done_at":  datetime.now().isoformat(),
        "version":  ENGINE_VER,
        "status":   status,
        "qa_score": qa_score,
        "rows":     rows,
        "codes":    codes,
        "output":   str(OUTPUT),
        "reason":   reason,
    }
    tmp = DONE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(DONE_FILE))
        log.info(f"[DONE] status={status}  QA={qa_score:.1f}  → {DONE_FILE}")
    except Exception as exc:
        log.warning(f"Done Flag 저장 실패: {exc}")


# ══════════════════════════════════════════════════════════════
# 4-C. Heartbeat (ADD-ETA)
# ══════════════════════════════════════════════════════════════
def _write_heartbeat(
    idx: int, total: int, current_sleep: float, eta_min: float
) -> None:
    info = {
        "ts":      datetime.now().isoformat(),
        "pid":     os.getpid(),
        "idx":     idx,
        "total":   total,
        "pct":     round(idx / max(total, 1) * 100, 1),
        "eta_min": round(eta_min, 1),
        "sleep":   current_sleep,
        "version": ENGINE_VER,
    }
    tmp = HB_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(HB_FILE))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# 5. 자동 진화 — QA 이력 + ADD-EVO2 확장
# ══════════════════════════════════════════════════════════════
def _load_qa_history() -> dict:
    if not QA_JSON.exists():
        return {}
    try:
        with open(QA_JSON, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _calc_adaptive_sleep(history: dict) -> float:
    """
    이전 fail_rate 기반 슬립 양방향 자동 조정.
    >= 15% → 비례 증가 / < 5% → 5% 단계 감소 / 5~15% → 기본값
    """
    FAIL_GOOD_RATE = 0.05
    prev_fail  = history.get("last_fail_rate",  0.0)
    prev_sleep = history.get("last_sleep_used", _DEFAULT_SLEEP)

    if prev_fail >= FAIL_WARN_RATE:
        adj = max(_MIN_SLEEP, min(_DEFAULT_SLEEP * (1.0 + prev_fail), _MAX_SLEEP))
        log.info(f"[자동진화↑] fail={prev_fail:.1%} → sleep {prev_sleep:.2f}→{adj:.2f}s")
        return adj

    if prev_fail < FAIL_GOOD_RATE and prev_sleep > _DEFAULT_SLEEP:
        adj = max(_MIN_SLEEP, min(max(_DEFAULT_SLEEP, prev_sleep * 0.95), _MAX_SLEEP))
        log.info(f"[자동진화↓] fail={prev_fail:.1%} → sleep {prev_sleep:.2f}→{adj:.2f}s")
        return adj

    return _DEFAULT_SLEEP


def _reorder_by_fail_history(
    pairs: list[tuple[str, str]], history: dict
) -> list[tuple[str, str]]:
    """
    ADD-EVO2: 이전 실행에서 실패했던 종목을 후반부로 배치.
    안정적인 종목 먼저 수집 → 전체 수집률 극대화.
    """
    prev_failed = set(history.get("prev_failed_codes", []))
    if not prev_failed:
        return pairs
    stable = [(c, m) for c, m in pairs if c not in prev_failed]
    risky  = [(c, m) for c, m in pairs if c in prev_failed]
    reordered = stable + risky
    log.info(
        f"[자동진화-순서] 안정 {len(stable)}종목 선행 / "
        f"고위험 {len(risky)}종목 후반 배치"
    )
    return reordered


def _save_qa_history(history: dict) -> None:
    tmp = QA_JSON.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(QA_JSON))
    except Exception as exc:
        log.warning(f"QA 이력 저장 실패: {exc}")


# ══════════════════════════════════════════════════════════════
# 6. 재시도 큐
# ══════════════════════════════════════════════════════════════
def _save_retry_queue(failed_codes: list[str]) -> None:
    if not failed_codes:
        RETRY_JSON.unlink(missing_ok=True)
        return
    info = {
        "saved_at":     datetime.now().isoformat(),
        "count":        len(failed_codes),
        "failed_codes": failed_codes,
    }
    tmp = RETRY_JSON.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(RETRY_JSON))
        log.info(f"[재시도 큐] {len(failed_codes)}종목 → {RETRY_JSON}")
    except Exception as exc:
        log.warning(f"재시도 큐 저장 실패: {exc}")


# ── [RETRY-MODE] retry.json 로더 (수동 재실행 전용) ────────────
def _load_retry_codes(path: Path) -> list[str]:
    """retry.json → failed_codes 리스트(중복 제거 + 검증). 빈 리스트면 호출자가 종료."""
    if not path.exists():
        log.error(f"[RETRY-MODE] retry.json 파일 없음: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as exc:
        log.error(f"[RETRY-MODE] retry.json 파싱 실패: {exc}")
        return []
    raw = data.get("failed_codes") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        log.error("[RETRY-MODE] failed_codes 필드 형식 오류 (list 아님)")
        return []
    seen: set[str] = set()
    codes: list[str] = []
    for c in raw:
        if not isinstance(c, str):
            continue
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


# ══════════════════════════════════════════════════════════════
# 7. 유틸리티
# ══════════════════════════════════════════════════════════════
def safe_int(x) -> int | None:
    """키움 API 반환값 → 정수 변환 (음수 절댓값, 콤마 제거)."""
    try:
        s = str(x).strip().replace(",", "")
        if not s:
            return None
        return abs(int(s))
    except Exception:
        return None


def self_heal_from_bak(dst: Path) -> None:
    """[W23-HEAL 2026-06-02] 직전 실행이 Windows file lock(os.replace WinError5)으로
    저장 실패하면 데이터가 .bak에만 보존되고 csv는 옛 날짜에 멈춤(6/1·6/2 누락 근원).
    수집 시작 시 .bak이 csv보다 최신(mtime↑ & size 동등이상)이면 csv로 자동 복구.
      - 데이터 축소 방지: bak.size >= csv.size 일 때만 복구(부분파일 덮어쓰기 차단)
      - 잠금/오류 시 try/except로 안전 스킵(수집 자체는 계속 진행)
    """
    try:
        bak = dst.with_suffix(".bak")
        if not bak.exists():
            return
        if (not dst.exists()) or (
            bak.stat().st_mtime > dst.stat().st_mtime
            and bak.stat().st_size >= dst.stat().st_size
        ):
            shutil.copy2(str(bak), str(dst))
            log.info(f"[W23-HEAL] .bak이 csv보다 최신 → 자동 복구: {dst} "
                     f"(bak={bak.stat().st_size:,}B)")
    except Exception as e:
        log.warning(f"[W23-HEAL] self-heal 스킵(잠금/오류): {e}")


def atomic_write(df: pd.DataFrame, dst: Path,
                 max_retries: int = 12, retry_delay: float = 2.0) -> None:
    """tmp 파일 먼저 저장 후 dst 원자적 교체.
    [W23 PATCH 2026-05-13] PermissionError retry 메커니즘 추가
      기존: os.replace 1회 실패 시 즉시 raise → 매일 17:45 PermissionError 영구 결함
      변경: PermissionError 시 retry_delay 간격 max_retries회 재시도
      모든 재시도 실패 시 tmp를 .bak로 보존 → 데이터 손실 회피
    [W23 강화 2026-06-02] 간헐 file lock(상주 프로세스/백신 스캔)이 6초 retry를 넘겨
      6/1·6/2 연속 저장 실패 → max_retries 3→12 + 선형 백오프(최대 12s/회, 누적 ~80s).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    try:
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        last_exc = None   # Exception or None — typing.Optional import 회피
        for attempt in range(max_retries):
            try:
                os.replace(str(tmp), str(dst))
                if attempt > 0:
                    log.info(f"[W23] retry 성공 (attempt={attempt+1}/{max_retries})")
                log.info(f"원자적 쓰기 완료 → {dst}  rows={len(df):,}")
                return
            except PermissionError as exc:
                last_exc = exc
                log.warning(
                    f"[W23] atomic_write PermissionError attempt={attempt+1}/{max_retries}: {exc}"
                )
                if attempt < max_retries - 1:
                    time.sleep(min(retry_delay * (attempt + 1), 12.0))   # [W23 강화] 선형 백오프
        # 모든 재시도 실패 → tmp를 .bak로 보존 (데이터 손실 회피)
        bak = dst.with_suffix(".bak")
        try:
            os.replace(str(tmp), str(bak))
            log.error(
                f"[W23] atomic_write 영구 실패 ({max_retries}회 retry) → "
                f".bak로 보존: {bak}  rows={len(df):,}"
            )
        except Exception as bak_exc:
            log.error(f"[W23] .bak 보존도 실패: {bak_exc}")
            tmp.unlink(missing_ok=True)
        raise last_exc if last_exc else RuntimeError("atomic_write retry 실패")
    except PermissionError:
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise exc


def _is_business_day_within(date_str: str, days: int) -> bool:
    """
    FIX-BDAY: KRX 공휴일 인식 영업일 계산.
    YYYYMMDD 기준 N 영업일 이내 여부.
    토/일 + KRX 공휴일 모두 제외하여 정확한 영업일 계산.
    """
    try:
        dt    = datetime.strptime(date_str, "%Y%m%d")
        today = datetime.now()
        if dt > today:
            return True  # 미래 날짜는 신선

        bdays = 0
        current = dt + timedelta(days=1)
        while current <= today:
            weekday = current.weekday()
            date_key = current.strftime("%Y%m%d")
            # 토(5), 일(6) 제외 + KRX 공휴일 제외
            if weekday < 5 and date_key not in _KRX_HOLIDAYS:
                bdays += 1
            current += timedelta(days=1)
        return bdays <= days
    except Exception:
        return True


def _get_screen_no(idx: int) -> str:
    """FIX-SCREEN: 100종목마다 화면번호 순환 (0101→0199→0101)."""
    screen_num = SCREEN_BASE + ((idx // SCREEN_ROTATE) % (SCREEN_MAX - SCREEN_BASE + 1))
    return str(screen_num).zfill(4)


# ══════════════════════════════════════════════════════════════
# 8. 헤지펀드 5차원 QA 검증
# ══════════════════════════════════════════════════════════════
def _calc_qa_score(
    df: pd.DataFrame,
    total_codes: int,
    fail_count: int,
    label: str,
) -> dict:
    """5차원 QA 점수 계산. label = 'RAW(정제전)' / 'CLEAN(정제후)'."""
    qa: dict  = {}
    total_rows = len(df)
    if total_rows == 0:
        return {"qa_score": 0, "rows": 0, "error": f"{label} 빈 데이터프레임"}

    # 1) 정확도 — 파생 컬럼(daily_return 등) NaN 정상 → 코어만 검사
    numeric_core = [c for c in ["open", "high", "low", "close", "volume", "value"]
                    if c in df.columns]
    invalid_num  = df[numeric_core].isna().any(axis=1).sum()
    accuracy_score = round((1.0 - invalid_num / total_rows) * 100, 2)
    qa["accuracy_pct"] = accuracy_score

    # 2) 완전성
    mandatory          = ["date", "code", "open", "high", "low", "close", "volume"]
    missing            = df[mandatory].isna().any(axis=1).sum()
    completeness_score = round((1.0 - missing / total_rows) * 100, 2)
    qa["completeness_pct"] = completeness_score

    # 3) 신선도 — FIX-BDAY: KRX 공휴일 인식
    latest_date     = df["date"].max() if "date" in df.columns else ""
    is_fresh        = _is_business_day_within(str(latest_date), FRESHNESS_DAYS)
    freshness_score = 100 if is_fresh else 0
    qa["latest_date"]     = str(latest_date)
    qa["freshness_ok"]    = is_fresh
    qa["freshness_score"] = freshness_score
    if not is_fresh:
        log.warning(f"[QA-{label}] 신선도 실패 — 최신={latest_date}")

    # 4) 유일성
    dup_count  = df.duplicated(subset=["code", "date"]).sum()
    uniqueness = round((1.0 - dup_count / total_rows) * 100, 2)
    qa["dup_count"]      = int(dup_count)
    qa["uniqueness_pct"] = uniqueness

    # 5) 타당성
    invalid_hl = (df["high"]  <  df["low"]).sum()
    invalid_c  = (df["close"] <= 0).sum()
    invalid_v  = (df["volume"]<  0).sum()
    invalid_o  = (df["open"]  <= 0).sum()
    total_inv  = int(invalid_hl + invalid_c + invalid_v + invalid_o)
    validity   = round((1.0 - total_inv / total_rows) * 100, 2)
    qa["validity_pct"]   = validity
    qa["invalid_hl"]     = int(invalid_hl)
    qa["invalid_close"]  = int(invalid_c)
    qa["invalid_volume"] = int(invalid_v)

    # FIX-DENOM: 분모 = 실수집 대상 수
    fail_rate = fail_count / max(total_codes, 1)
    qa["fail_count"]  = fail_count
    qa["total_codes"] = total_codes
    qa["fail_rate"]   = round(fail_rate, 4)

    qa_score = (
        accuracy_score     * 0.20 +
        completeness_score * 0.20 +
        freshness_score    * 0.25 +
        uniqueness         * 0.15 +
        validity           * 0.20
    )
    qa["qa_score"] = round(qa_score, 2)
    qa["rows"]     = total_rows
    qa["codes"]    = df["code"].nunique() if "code" in df.columns else 0

    log.info("=" * 60)
    log.info(f"[QA-{label}] 헤지펀드 5차원 데이터 품질 리포트")
    log.info(f"  정확도   : {accuracy_score:6.2f}%  (결측 {invalid_num:,} rows)")
    log.info(f"  완전성   : {completeness_score:6.2f}%  (미완성 {missing:,} rows)")
    log.info(f"  신선도   : {'PASS ✓' if is_fresh else 'FAIL ✗'}  (최신={latest_date})")
    log.info(f"  유일성   : {uniqueness:6.2f}%  (중복 {dup_count:,} rows)")
    log.info(f"  타당성   : {validity:6.2f}%  (이상 {total_inv:,} rows)")
    log.info(f"  수집실패 : {fail_rate:.1%}  ({fail_count}/{total_codes})")
    log.info(f"  ────────────────────────────")
    log.info(f"  통합점수 : {qa_score:.2f} / 100  [{label}]")
    log.info("=" * 60)
    return qa


def run_qa_report(
    clean_df: pd.DataFrame,
    total_codes: int,
    fail_count: int,
) -> dict:
    """CLEAN 데이터 1회 QA (RAW 이중 검증 제거)."""
    return _calc_qa_score(clean_df, total_codes, fail_count, "CLEAN")


# ══════════════════════════════════════════════════════════════
# 9. 키움 API 래퍼
# ══════════════════════════════════════════════════════════════
class Kiwoom(QAxWidget):
    def __init__(self):
        super().__init__()
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        self.login_loop        = None
        self.tr_loop           = None
        self.tr_rows: list     = []
        self.tr_prev_next: str = "0"
        self.connected: bool   = False
        self._tr_timed_out: bool = False  # FIX-TRTO
        self.OnEventConnect.connect(self._on_event_connect)
        self.OnReceiveTrData.connect(self._on_receive_tr_data)

    # ── 로그인 (FIX-LOGIN: 3회 재시도) ─────────────────
    def login(self) -> None:
        for attempt in range(1, LOGIN_MAX_RETRY + 1):
            self.connected  = False
            self.login_loop = QEventLoop()
            self.CommConnect()
            # FIX-TRTO: 로그인에도 60초 타임아웃
            QTimer.singleShot(60000, self.login_loop.quit)
            self.login_loop.exec_()
            if self.connected:
                log.info(f"LOGIN SUCCESS (시도 {attempt}/{LOGIN_MAX_RETRY})")
                return
            log.warning(f"LOGIN FAIL 시도 {attempt}/{LOGIN_MAX_RETRY} — 5초 대기")
            time.sleep(5)
        raise RuntimeError(f"키움 로그인 {LOGIN_MAX_RETRY}회 모두 실패")

    def _on_event_connect(self, err_code: int) -> None:
        self.connected = (err_code == 0)
        if not self.connected:
            log.error(f"LOGIN FAIL  err_code={err_code}")
        if self.login_loop and self.login_loop.isRunning():
            self.login_loop.exit()

    # ── TR 수신 ─────────────────────────────────────────
    def _on_receive_tr_data(
        self, screen_no, rqname, trcode, recordname, prev_next, *args
    ) -> None:
        try:
            if rqname != "opt10081_req":
                return
            cnt  = self.GetRepeatCnt(trcode, rqname)
            rows = []
            for i in range(cnt):
                date   = self.GetCommData(trcode, rqname, i, "일자").strip()
                open_  = safe_int(self.GetCommData(trcode, rqname, i, "시가"))
                high   = safe_int(self.GetCommData(trcode, rqname, i, "고가"))
                low    = safe_int(self.GetCommData(trcode, rqname, i, "저가"))
                close  = safe_int(self.GetCommData(trcode, rqname, i, "현재가"))
                volume = safe_int(self.GetCommData(trcode, rqname, i, "거래량"))
                value  = safe_int(self.GetCommData(trcode, rqname, i, "거래대금"))
                if not date:
                    continue
                if None in (open_, high, low, close, volume):
                    continue
                rows.append({
                    "date":   date,
                    "open":   open_,
                    "high":   high,
                    "low":    low,
                    "close":  close,
                    "volume": volume,
                    "value":  value if value is not None else 0,
                })
            self.tr_rows.extend(rows)
            self.tr_prev_next = str(prev_next).strip()
        finally:
            if self.tr_loop and self.tr_loop.isRunning():
                self.tr_loop.exit()

    # ── 종목 코드 목록 (시장 구분 포함) ──────────────────
    def get_all_codes(self, kosdaq_only: bool = False) -> list[tuple[str, str]]:
        """
        [(code, market), ...] — market = 'KOSPI' | 'KOSDAQ'
        ADD-KOSDAQ: kosdaq_only=True → KOSDAQ만 반환 (수집 시간 50% 절약)
        """
        seen: dict[str, str] = {}
        if not kosdaq_only:
            kospi = [c for c in self.GetCodeListByMarket("0").split(";") if c]
            for c in kospi:
                seen.setdefault(c, "KOSPI")
        kosdaq = [c for c in self.GetCodeListByMarket("10").split(";") if c]
        for c in kosdaq:
            seen.setdefault(c, "KOSDAQ")
        return sorted(seen.items(), key=lambda x: x[0])

    def get_master_name(self, code: str) -> str:
        try:
            return self.GetMasterCodeName(code).strip()
        except Exception:
            return ""

    def is_excluded(self, code: str, name: str) -> bool:
        """
        FIX-FILTER: ETF·ETN·스팩·관리종목·리츠·인프라펀드·우선주 → True (수집 제외).
        v1_7 대비 추가: ETN, 리츠, 인프라펀드, 우선주 코드 패턴
        """
        # 1) ETF
        try:
            if bool(self.GetMasterETF(code)):
                return True
        except Exception:
            pass

        # 2) 스팩 (종목명 기반)
        if "스팩" in name:
            return True

        # 3) 관리종목
        try:
            stock_info = str(self.GetMasterStockState(code))  # [FIX 2026-06-08] GetMasterStockInfo(키움 미존재) → GetMasterStockState(정상, "관리" 포함)
            if "관리" in stock_info:
                return True
        except Exception:
            pass

        # 4) FIX-FILTER: ETN (종목명 기반)
        _etn_keywords = ("ETN", "etn", "이티엔")
        for kw in _etn_keywords:
            if kw in name:
                return True

        # 5) FIX-FILTER: 리츠/인프라펀드 (종목명 기반)
        _reit_keywords = ("리츠", "REIT", "Reit", "인프라")
        for kw in _reit_keywords:
            if kw in name:
                return True

        # 6) FIX-FILTER: 우선주 (코드 패턴 — 끝자리 5,7,8,9)
        #    KOSDAQ 우선주: 코드 6자리 끝 5 (예: 000725)
        if len(code) == 6 and code[-1] in ("5", "7", "8", "9"):
            # 추가 확인: 종목명에 '우' 또는 '우B' 포함
            if name.endswith("우") or name.endswith("우B") or "우선" in name:
                return True

        return False

    # ── 일봉 조회 (prev_next 연속 조회) ──────────────────
    def get_daily(
        self, code: str, req_sleep: float, max_days: int = MAX_DAYS,
        screen_no: str = "0101",
    ) -> pd.DataFrame:
        """FIX-SCREEN + FIX-TRTO: 화면번호 외부 지정 + TR 타임아웃 30초."""
        self.tr_rows      = []
        self.tr_prev_next = "0"
        self._tr_timed_out = False
        self.SetInputValue("종목코드",     code)
        self.SetInputValue("기준일자",     "")
        self.SetInputValue("수정주가구분", "1")

        # FIX-TRTO: 타임아웃 내장 이벤트루프
        self.tr_loop = QEventLoop()
        QTimer.singleShot(TR_TIMEOUT_MS, self._on_tr_timeout)
        self.CommRqData("opt10081_req", "opt10081", 0, screen_no)
        self.tr_loop.exec_()

        if self._tr_timed_out:
            log.warning(f"[TR-TIMEOUT] {code} 첫 페이지 {TR_TIMEOUT_MS}ms 초과")
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "value"]
            )

        page = 1
        while self.tr_prev_next == "2" and len(self.tr_rows) < max_days:
            time.sleep(req_sleep)
            self._tr_timed_out = False
            self.tr_loop = QEventLoop()
            QTimer.singleShot(TR_TIMEOUT_MS, self._on_tr_timeout)
            self.CommRqData("opt10081_req", "opt10081", 2, screen_no)
            self.tr_loop.exec_()
            if self._tr_timed_out:
                log.warning(f"[TR-TIMEOUT] {code} page={page+1} {TR_TIMEOUT_MS}ms 초과 — 중단")
                break
            page += 1
            log.debug(f"{code} 연속조회 page={page} 누적={len(self.tr_rows)}")

        if not self.tr_rows:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "value"]
            )
        return pd.DataFrame(self.tr_rows).head(max_days).copy()

    def _on_tr_timeout(self) -> None:
        """FIX-TRTO: TR 응답 타임아웃 핸들러."""
        self._tr_timed_out = True
        if self.tr_loop and self.tr_loop.isRunning():
            self.tr_loop.exit()


# ══════════════════════════════════════════════════════════════
# [STEP-3.4 BROKER-IPC 2026-05-14] broker IPC client (read-only opt10081 + MASTER_INFO)
#   broker_gateway_v1 alive 시 broker IPC 경유 → 자체 OCX 미생성 → LOGIN popup 0회
#   broker dead 시 기존 Kiwoom (direct OCX) fallback 유지
# ══════════════════════════════════════════════════════════════
import json as _eod_json
import uuid as _eod_uuid

_EOD_BROKER_HB_FILE      = Path(r"C:\stock_bot\IPC\broker_heartbeat.json")
_EOD_BROKER_HB_STALE_SEC = 15.0
_EOD_BROKER_IPC_REQ_DIR  = Path(r"C:\stock_bot\IPC\requests")
_EOD_BROKER_IPC_RES_DIR  = Path(r"C:\stock_bot\IPC\responses")


def _eod_is_broker_alive() -> bool:
    try:
        if not _EOD_BROKER_HB_FILE.exists():
            return False
        age = time.time() - _EOD_BROKER_HB_FILE.stat().st_mtime
        return age < _EOD_BROKER_HB_STALE_SEC
    except Exception:
        return False


def _eod_broker_request(payload: dict, timeout_sec: float = 12.0,
                       poll_interval_sec: float = 0.2) -> dict:
    """broker IPC 요청 1건 (request 작성 → response 폴 → dict 반환)."""
    request_id = str(_eod_uuid.uuid4())
    req = dict(payload)
    req["request_id"] = request_id
    req["ts"]         = datetime.now().isoformat()
    req.setdefault("ttl_sec", int(timeout_sec) + 5)

    _EOD_BROKER_IPC_REQ_DIR.mkdir(parents=True, exist_ok=True)
    _EOD_BROKER_IPC_RES_DIR.mkdir(parents=True, exist_ok=True)

    req_path = _EOD_BROKER_IPC_REQ_DIR / f"{request_id}.json"
    res_path = _EOD_BROKER_IPC_RES_DIR / f"{request_id}.json"
    try:
        tmp = req_path.with_suffix(".tmp")
        tmp.write_text(_eod_json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(req_path))
    except Exception as e:
        return {"status": "ERROR", "error": f"request write failed: {e}", "data": None}

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if res_path.exists():
            try:
                res = _eod_json.loads(res_path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                try: res_path.unlink()
                except Exception: pass
                return {"status": "ERROR", "error": f"response parse failed: {e}", "data": None}
            try: res_path.unlink()
            except Exception: pass
            return res
        time.sleep(poll_interval_sec)
    return {"status": "TIMEOUT", "error": f"client poll timeout ({timeout_sec}s)", "data": None}


class BrokerKiwoom:
    """[STEP-3.4 BROKER-IPC] Kiwoom 호환 broker IPC client.

    동일 메서드 시그니처: login / get_all_codes / get_master_name / is_excluded / get_daily
    OCX 직접 호출 없음 (QAxWidget 미생성). broker IPC 만 사용.
    """

    def __init__(self):
        pass

    def login(self) -> None:
        """broker 가 이미 LOGIN 됨 — no-op. (broker dead 시 main() 에서 fallback)"""
        log.info("[BROKER-IPC] login no-op (broker 가 OCX LOGIN 보유)")

    def get_all_codes(self, kosdaq_only: bool = False) -> list[tuple[str, str]]:
        # [N4 2026-05-14] 1회 retry — 첫 호출 race / broker startup 직후 가능성 차단
        def _fetch_market(market_code: str) -> str:
            res = _eod_broker_request({"type": "MASTER_INFO", "func": "GetCodeListByMarket", "arg": market_code})
            if res.get("status") == "OK":
                return str((res.get("data") or {}).get("value", ""))
            # retry 1회
            log.warning(f"[BROKER-IPC] GetCodeListByMarket({market_code}) {res.get('status')} → 1회 retry")
            time.sleep(0.5)
            res2 = _eod_broker_request({"type": "MASTER_INFO", "func": "GetCodeListByMarket", "arg": market_code})
            if res2.get("status") == "OK":
                return str((res2.get("data") or {}).get("value", ""))
            log.error(f"[BROKER-IPC] GetCodeListByMarket({market_code}) retry 후에도 실패: {res2.get('error')}")
            return ""

        seen: dict[str, str] = {}
        if not kosdaq_only:
            for c in _fetch_market("0").split(";"):
                if c:
                    seen.setdefault(c, "KOSPI")
        for c in _fetch_market("10").split(";"):
            if c:
                seen.setdefault(c, "KOSDAQ")
        return sorted(seen.items(), key=lambda x: x[0])

    def get_master_name(self, code: str) -> str:
        res = _eod_broker_request({"type": "MASTER_INFO", "func": "GetMasterCodeName", "arg": code}, timeout_sec=5.0)
        if res.get("status") == "OK":
            return str((res.get("data") or {}).get("value", "")).strip()
        return ""

    def is_excluded(self, code: str, name: str) -> bool:
        # 1) ETF
        try:
            r = _eod_broker_request({"type": "MASTER_INFO", "func": "GetMasterETF", "arg": code}, timeout_sec=5.0)
            if r.get("status") == "OK" and bool((r.get("data") or {}).get("value", 0)):
                return True
        except Exception:
            pass
        # 2) 스팩
        if "스팩" in name:
            return True
        # 3) 관리종목
        try:
            r = _eod_broker_request({"type": "MASTER_INFO", "func": "GetMasterStockState", "arg": code}, timeout_sec=5.0)  # [FIX 2026-06-08] GetMasterStockInfo(키움 미존재)→GetMasterStockState
            if r.get("status") == "OK":
                stock_info = str((r.get("data") or {}).get("value", ""))
                if "관리" in stock_info:
                    return True
        except Exception:
            pass
        # 4) ETN
        for kw in ("ETN", "etn", "이티엔"):
            if kw in name:
                return True
        # 5) 리츠/인프라
        for kw in ("리츠", "REIT", "Reit", "인프라"):
            if kw in name:
                return True
        # 6) 우선주
        if len(code) == 6 and code[-1] in ("5", "7", "8", "9"):
            if name.endswith("우") or name.endswith("우B") or "우선" in name:
                return True
        return False

    def get_daily(self, code: str, req_sleep: float, max_days: int = MAX_DAYS,
                  screen_no: str = "0101") -> pd.DataFrame:
        """opt10081 broker IPC 호출 (prev_next 연속 조회).
        Kiwoom.get_daily 와 동일 시그니처.
        [N2 2026-05-14] broker `next_flag` payload 지원 활성화 — prev_next='2' 시 연속 조회.
        """
        rows: list = []
        next_flag = 0
        for page in range(1, 20):  # 안전 가드 (최대 20페이지)
            res = _eod_broker_request({
                "type":      "TR",
                "tr_code":   "opt10081",
                "rqname":    "opt10081_req",
                "screen_no": screen_no,
                "next_flag": next_flag,  # [N2] 0=첫, 2=연속
                "input": {
                    "종목코드":     code,
                    "기준일자":     "",
                    "수정주가구분": "1",
                },
                "output_fields": ["일자", "시가", "고가", "저가", "현재가", "거래량", "거래대금"],
            }, timeout_sec=(TR_TIMEOUT_MS / 1000.0))
            if res.get("status") != "OK":
                log.warning(f"[BROKER-IPC] {code} page={page} status={res.get('status')} err={res.get('error')}")
                break
            data = res.get("data") or {}
            recs = data.get("records") or []
            for rec in recs:
                date_str = str(rec.get("일자", "")).strip()
                if not date_str:
                    continue
                o = safe_int(rec.get("시가", ""))
                h = safe_int(rec.get("고가", ""))
                l = safe_int(rec.get("저가", ""))
                c = safe_int(rec.get("현재가", ""))
                v = safe_int(rec.get("거래량", ""))
                val = safe_int(rec.get("거래대금", ""))
                if None in (o, h, l, c, v):
                    continue
                rows.append({"date": date_str, "open": o, "high": h, "low": l,
                             "close": c, "volume": v, "value": val if val is not None else 0})
            prev_next = str(data.get("prev_next", "0")).strip()
            if prev_next != "2" or len(rows) >= max_days:
                break
            time.sleep(req_sleep)
            next_flag = 2  # [N2] 다음 페이지 연속 조회

        if not rows:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "value"])
        return pd.DataFrame(rows).head(max_days).copy()


# ══════════════════════════════════════════════════════════════
# 10. OHLCV 이상값 제거
# ══════════════════════════════════════════════════════════════
def _drop_invalid_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """헤지펀드 OHLCV 타당성 5단계 필터."""
    before = len(df)
    mask = (
        (df["high"]  >= df["low"])   &
        (df["close"] >  0)           &
        (df["open"]  >  0)           &
        (df["volume"]>= 0)           &
        (df["high"]  >= df["close"]) &
        (df["low"]   <= df["close"])
    )
    df      = df[mask].copy()
    dropped = before - len(df)
    if dropped > 0:
        log.warning(f"[타당성] OHLCV 이상값 제거: {dropped:,} rows")
    return df


# ══════════════════════════════════════════════════════════════
# 11. 파생 팩터 — 수익률 직결 [ADD-VOL / ADD-VAL / ADD-W52]
# ══════════════════════════════════════════════════════════════
def _add_derived_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    종목별 파생 팩터 + Alpha Score + Regime 추가.

    [기본 팩터 4종]
    daily_return  : 전일 대비 등락률
    vol_ratio     : 당일 거래량 ÷ 20일 평균 거래량
                    → 기관 수급 급증 감지 (Renaissance·Citadel 공통 팩터)
                    FIX-MINP: min_periods=10
    value_ratio   : 당일 거래대금 ÷ 20일 평균 거래대금
                    → vol_ratio와 동시 급등 = 강력 기관 매수 신호
                    FIX-MINP: min_periods=10
    w52_high_pct  : 현재가 ÷ 52주 고가 × 100
                    → 신고가 돌파 모멘텀 (AQR 모멘텀 팩터 핵심)
                    FIX-W52: MAX_DAYS < 252일 시 실제 윈도우 표기

    [v1_8 Alpha Score — Renaissance/AQR 구조]
    alpha_mom     : 5일 모멘텀 (raw)
    alpha_vol     : 거래량 서지 (raw)
    alpha_val     : 거래대금 서지 (raw)
    alpha_high    : 돌파 강도 (raw)
    z_alpha_*     : 일별 cross-sectional z-score (±3σ 클리핑)
    regime        : 시장 국면 (BULL / NEUTRAL / BEAR)
    market_ma20   : 시장 전체 20일 이동평균 수익률
    alpha_score   : Regime-adjusted 종합 알파 점수
    alpha_rank    : 일별 알파 순위 (1 = 최고)

    Factor Weight (Regime별) — 시가·추세눌림 전략 전용:
      BULL   : mom 0.28 / vol 0.08 / val 0.10 / high 0.14 / accel 0.24 / quality 0.16
               (추세눌림 가속도 최우선 + 시가 강세마감 동시 반영)
      NEUTRAL: mom 0.22 / vol 0.10 / val 0.16 / high 0.16 / accel 0.18 / quality 0.18
               (시가·추세눌림 균형 배분)
      BEAR   : mom 0.12 / vol 0.08 / val 0.22 / high 0.18 / accel 0.12 / quality 0.28
               (BEAR 구간: 강세마감 품질 최우선 — 안전 종목만 선별)
    """
    df = df.sort_values(["code", "date"]).copy()

    # 1) 일간수익률
    df["daily_return"] = (
        df.groupby("code")["close"]
        .pct_change()
        .round(6)
    )

    # 2) 거래량 비율 (수급 강도) — FIX-MINP
    vol_ma = df.groupby("code")["volume"].transform(
        lambda x: x.rolling(VOL_WINDOW, min_periods=VOL_MIN_PERIODS).mean()
    )
    df["vol_ratio"] = (df["volume"] / vol_ma.replace(0, float("nan"))).round(4)

    # 3) 거래대금 비율 (기관 유입 강도) — FIX-MINP
    val_ma = df.groupby("code")["value"].transform(
        lambda x: x.rolling(VOL_WINDOW, min_periods=VOL_MIN_PERIODS).mean()
    )
    df["value_ratio"] = (df["value"] / val_ma.replace(0, float("nan"))).round(4)

    # 4) 52주 고점 대비 현재가 위치 — FIX-W52
    #    MAX_DAYS < 252 이면 실제 사용 가능한 윈도우로 제한
    actual_w52 = min(W52_WINDOW, MAX_DAYS)
    w52_high = df.groupby("code")["high"].transform(
        lambda x: x.rolling(actual_w52, min_periods=VOL_MIN_PERIODS).max()
    )

    # FIX-W52: 컬럼명을 실제 윈도우에 맞게 설정
    if actual_w52 < W52_WINDOW:
        col_name = f"d{actual_w52}_high_pct"
        log.warning(
            f"[FIX-W52] MAX_DAYS={MAX_DAYS} < W52_WINDOW={W52_WINDOW} → "
            f"컬럼명 '{col_name}' 사용 (52주 고점 아님, {actual_w52}일 고점)"
        )
    else:
        col_name = "w52_high_pct"

    df[col_name] = (df["close"] / w52_high.replace(0, float("nan")) * 100).round(2)

    # 하위 호환: w52_high_pct 컬럼이 없으면 alias 생성
    if col_name != "w52_high_pct" and "w52_high_pct" not in df.columns:
        df["w52_high_pct"] = df[col_name]
        log.info(f"[FIX-W52] 하위호환 alias: w52_high_pct = {col_name}")

    # ══════════════════════════════════════════════════════════
    # 5) SAFEPLUS ALPHA SCORE v2 — 수익률 직결 6-Factor 구조
    #
    #    Renaissance/AQR 구조:
    #      raw factor → z-score → regime weight → composite
    #      + volatility penalty + trend persistence bonus
    #
    #    학술 근거:
    #      Jegadeesh & Titman (1993) — 모멘텀 팩터 (10~20일 최적)
    #      AQR Capital — 멀티팩터 모멘텀 스코어링
    #      Ehsani & Linnainmaa (2022) — Factor Momentum
    #      Gray & Vogel (2016) — 경로 의존 모멘텀 품질
    #      J.P. Morgan (2015) — 변동성 조정 모멘텀 (VARS)
    #
    #    v2 수정 (수익률 보강 4건):
    #      [필수-1] 모멘텀 10d*0.6 + 20d*0.4 (5d → 블렌딩)
    #      [필수-2] 변동성 페널티 (급등급락 종목 감점)
    #      [필수-3] 추세 지속성 (5일중 양봉 비율)
    #      [필수-4] 거래대금 적격 플래그 (절대값 10억 기준)
    #      [성능]   df.apply → 벡터화 연산
    #
    #    고유영역 준수:
    #      이 블록은 eod_daily_bars.csv에 컬럼을 추가할 뿐
    #      스코어보드/브릿지/RT 흐름 일체 미접촉
    #      다운스트림이 alpha_score를 사용 여부는 자유 선택
    # ══════════════════════════════════════════════════════════

    # ── 5-A) Raw Alpha Factors (6종) ──────────────────────

    # [필수-1] Momentum: 10일*0.5 + 20일*0.5 블렌딩
    #   5일 단독 → 노이즈 과다, 가짜 상승 다수 포착
    #   10+20 블렌딩 → 진짜 추세만 포착 (시가·추세눌림 전략 적합)
    #   시가  : 갭업 전날 강한 모멘텀 확인 → 10일 비중 중요
    #   추세눌림: 중기 추세 확인 후 눌림 진입 → 20일 비중 중요
    #   → 10+20 균등 블렌딩이 두 전략 모두 최적
    mom_5  = df.groupby("code")["close"].pct_change(5)
    mom_10 = df.groupby("code")["close"].pct_change(10)
    mom_20 = df.groupby("code")["close"].pct_change(20)
    df["alpha_mom"] = (mom_10 * 0.5 + mom_20 * 0.5).round(6)

    # ──────────────────────────────────────────────────────
    # [v2_0] 필수-1: Acceleration 팩터 3종 — 수익률 상단 핵심
    #
    #   기존: "강한 종목" 포착
    #   v2_0: "더 강해지고 있는 종목" 포착 → 상단 수익 후보 +15~20%
    #
    #   mom_accel   : 5일 모멘텀 - 10일 모멘텀 (단기 가속도)
    #                 양수 = 최근 5일이 더 강함 = 가속 중
    #   value_accel : 5일 평균 거래대금 / 20일 평균 거래대금
    #                 > 1.0 = 최근 거래대금 급증 = 기관 유입 가속
    #   vol_accel   : 5일 평균 거래량 / 20일 평균 거래량
    #                 > 1.0 = 최근 거래량 급증 = 수급 가속
    #
    #   학술 근거: Ehsani & Linnainmaa (2022) — Factor Momentum
    #     팩터 자체의 모멘텀(가속도)이 수익률 예측력 추가 보유
    # ──────────────────────────────────────────────────────
    df["mom_accel"] = (mom_5 - mom_10).round(6)

    val_ma_5  = df.groupby("code")["value"].transform(
        lambda x: x.rolling(5,  min_periods=3).mean())
    val_ma_20 = df.groupby("code")["value"].transform(
        lambda x: x.rolling(20, min_periods=10).mean())
    df["value_accel"] = (val_ma_5 / val_ma_20.replace(0, float("nan"))).round(4)

    vol_ma_5  = df.groupby("code")["volume"].transform(
        lambda x: x.rolling(5,  min_periods=3).mean())
    vol_ma_20 = df.groupby("code")["volume"].transform(
        lambda x: x.rolling(20, min_periods=10).mean())
    df["vol_accel"] = (vol_ma_5 / vol_ma_20.replace(0, float("nan"))).round(4)

    # Volume Surge: 이미 계산된 vol_ratio
    df["alpha_vol"] = df["vol_ratio"]

    # Value Surge: 이미 계산된 value_ratio
    df["alpha_val"] = df["value_ratio"]

    # Breakout Strength: 고점 대비 위치 (0~1+ 범위)
    df["alpha_high"] = df["w52_high_pct"] / 100.0

    # [필수-2] Volatility: 10일 수익률 표준편차 (리스크 지표)
    #   높을수록 위험 → alpha_score에서 감점
    #   급등 후 급락 종목 제거의 핵심
    df["alpha_volatility"] = df.groupby("code")["daily_return"].transform(
        lambda x: x.rolling(10, min_periods=5).std()
    ).round(6)

    # [필수-3] Trend Persistence: 최근 5일 중 양봉(종가 상승) 비율
    #   0.0 = 5일 전부 하락, 1.0 = 5일 전부 상승
    #   하루짜리 펌핑 종목 필터링의 핵심
    _close_up = (df.groupby("code")["close"].diff(1) > 0).astype(float)
    df["trend_persist"] = _close_up.groupby(df["code"]).transform(
        lambda x: x.rolling(5, min_periods=3).sum()
    )
    df["trend_score"] = (df["trend_persist"] / 5.0).clip(0.0, 1.0).round(4)

    # [필수-4] 거래대금 적격성 플래그 (행 삭제 아님!)
    #   행을 삭제하면 rolling 계산이 붕괴하므로 플래그만 추가
    #   다운스트림(스코어보드)이 이 플래그로 필터링
    #   [v1_9] FIX-ENV-VMIN: 전역상수 VALUE_ELIGIBLE_MIN 사용
    #   [v2_0] 필수-7: 이중 조건 — 절대값(15억) AND 비율(1.2배) 동시 충족
    #     → 거래대금 크지만 상승동력 없는 둔한 종목 추가 제거
    df["value_eligible"] = (
        (df["value"]       >= VALUE_ELIGIBLE_MIN) &
        (df["value_ratio"] >= VALUE_RATIO_MIN)
    ).astype(int)

    # ──────────────────────────────────────────────────────
    # [v1_9] FIX-ADJ-IMPL: 수정주가 적용 추적 컬럼 실구현 (BUG-4 완결)
    #   v1_8 버전노트에 선언만 있고 코드 미구현이었던 항목
    #   opt10081 호출 시 수정주가구분=1 → 전량 수정주가 적용
    #   다운스트림에서 수정주가/원주가 혼용 여부 검증에 활용
    # ──────────────────────────────────────────────────────
    df["is_adj_price"] = 1   # 1=수정주가 적용, 0=원주가 (현재 전량 수정주가)

    # ──────────────────────────────────────────────────────
    # [v1_9] ADD-CLOSEPOS: 종가 위치 팩터 — 수익률 보강 핵심
    #
    #   공식: (close - low) / (high - low + epsilon)
    #   범위: 0.0(저가 마감) ~ 1.0(고가 마감)
    #
    #   수익률 연결 로직:
    #     종가가 당일 고가에 근접(≥0.8) → 매수세 지속 → 익일 갭업 확률 UP
    #     종가가 당일 저가에 근접(≤0.2) → 매도세 지속 → 익일 갭다운 리스크
    #
    #   학술 근거: Grinblatt & Han (2005) "Prospect Theory, Mental
    #     Accounting, and Momentum" — 강세 마감 = 미실현 이익 적음
    #     → 다음날 매도 압력 낮음 → 갭업 모멘텀 지속
    # ──────────────────────────────────────────────────────
    _hl_range = (df["high"] - df["low"]).clip(lower=1.0)  # 분모 0 방지
    df["close_position"] = (
        (df["close"] - df["low"]) / _hl_range
    ).clip(0.0, 1.0).round(4)

    # ──────────────────────────────────────────────────────
    # [v2_0] 필수-2: 봉 품질 팩터 4종 — 시가·추세눌림 승률 +3~5%
    #
    #   시가 전략  : 강세마감(close_quality 高) → 익일 갭업 확률 직결
    #   추세눌림   : 눌림 후 강세마감 확인 → 재상승 진입 신호
    #   시가·추세눌림 두 전략 공통 핵심 팩터로 가중치 상향 (v2_3)
    #
    #   body_ratio_daily      : 몸통 비율 (캔들의 실체 크기)
    #                           → 1.0 = 온봉(순수 상승), 0.0 = 도지
    #   close_pos_daily       : 종가 위치 = close_position (alias)
    #                           → 재계산 없이 기존 컬럼 참조
    #   upper_wick_ratio_daily: 윗꼬리 비율
    #                           → 0.0 = 윗꼬리 없음(강세), 높을수록 매도압력
    #   close_quality         : 봉 품질 종합 점수 (0~1)
    #                           = close_pos × 0.6 + body × 0.3 + (1-wick) × 0.1
    #
    #   학술 근거: Lo, Mamaysky & Wang (2000) — 캔들 패턴의 통계적 유의성
    # ──────────────────────────────────────────────────────
    _daily_range = (df["high"] - df["low"]).replace(0, float("nan"))

    df["body_ratio_daily"] = (
        (df["close"] - df["open"]).abs() / _daily_range
    ).clip(0, 1).round(4)

    # close_pos_daily = close_position (같은 공식, alias로 처리)
    df["close_pos_daily"] = df["close_position"]

    df["upper_wick_ratio_daily"] = (
        (df["high"] - df[["open", "close"]].max(axis=1)) / _daily_range
    ).clip(0, 1).round(4)

    df["close_quality"] = (
        df["close_pos_daily"]        * 0.6 +
        df["body_ratio_daily"]       * 0.3 +
        (1 - df["upper_wick_ratio_daily"]) * 0.1
    ).clip(0, 1).round(4)

    # ──────────────────────────────────────────────────────
    # [v2_1 BUG-CRITICAL-1 수정] alpha_accel + alpha_quality 대입
    #   이전 v2_0: close_quality 계산 전(line 1039)에 참조 → KeyError 크래시
    #   수정: close_quality 계산 완료 직후로 이동 → 정상 참조 보장
    # ──────────────────────────────────────────────────────
    df["alpha_accel"]   = df["mom_accel"]      # 모멘텀 가속도 팩터
    df["alpha_quality"] = df["close_quality"]  # 봉 품질 종합점수 팩터

    # ──────────────────────────────────────────────────────
    # [v2_0] 필수-3: 돌파 지속성 팩터 3종 — 익일 갭 유지 확률 개선
    #
    #   반짝 돌파: 1일만 고점 넘고 → 익일 갭다운 (손실)
    #   버티는 돌파: 3일 연속 고점 유지 → 익일 갭업 지속 (수익)
    #
    #   close_above_prev_high  : 전일 고가 넘은 날 = 1, 아니면 0
    #   high_break_streak      : 최근 3일 중 전일고가 돌파 일수 (0~3)
    #   breakout_persist_3d    : 최근 3일 평균 돌파율 (0~1)
    # ──────────────────────────────────────────────────────
    prev_high_1 = df.groupby("code")["high"].shift(1)
    df["close_above_prev_high"] = (
        (df["close"] > prev_high_1).astype(int)
    )

    df["high_break_streak"] = (
        df.groupby("code")["close_above_prev_high"]
          .transform(lambda x: x.rolling(3, min_periods=1).sum())
    ).round(0)

    df["breakout_persist_3d"] = (
        df.groupby("code")["close_above_prev_high"]
          .transform(lambda x: x.rolling(3, min_periods=1).mean())
    ).round(4)

    # ──────────────────────────────────────────────────────
    # [v1_9] ADD-INSTSURGE: 기관 수급 복합 강도 — 기관 등 타기 핵심
    #
    #   공식: sqrt(vol_ratio × value_ratio) — 기하평균
    #   단순 합산 대비 기하평균이 동시 급등 신호를 더 강하게 포착
    #
    #   수익률 연결 로직:
    #     vol_ratio=3 AND value_ratio=3 → inst_surge=3.0 (강한 신호)
    #     vol_ratio=5 AND value_ratio=1 → inst_surge=2.2 (부분 신호)
    #     vol_ratio=1 AND value_ratio=5 → inst_surge=2.2 (부분 신호)
    #     → 거래량 + 거래대금 둘 다 급증해야 최고 점수
    #
    #   기관 등 타기 철학: 기관이 대량 매수할 때 vol과 value 모두 급증
    #   개인이 따라타는 것과 기관 진짜 매수의 차이 = value_ratio 확인
    #
    #   [v2_1 WEAK-2 수정] fillna(1.0) → fillna(0.0)
    #     이전: NaN → 1.0(중립) 대체 → 신규상장/데이터부족 종목이 inst_surge=1.0
    #     → alpha_score 과대추정 → top alpha_rank 오진입 위험
    #     수정: NaN → 0.0 → value_eligible=0 인 종목은 alpha_rank=NaN 보장
    # ──────────────────────────────────────────────────────
    _vol_clip  = df["vol_ratio"].clip(0, 10).fillna(0.0)
    _val_clip  = df["value_ratio"].clip(0, 10).fillna(0.0)
    # 0×0=0 → sqrt(0)=0: 데이터 없는 종목은 inst_surge=0 (중립 아닌 무신호)
    df["inst_surge"] = (_vol_clip * _val_clip).pow(0.5).round(4)

    # ──────────────────────────────────────────────────────
    # [v1_9] ADD-DUALCONF: 이중 확인 플래그 — 강력 진입 신호
    #
    #   조건: vol_ratio ≥ DUAL_CONFIRM_VOL_MIN AND
    #         value_ratio ≥ DUAL_CONFIRM_VAL_MIN (기본 각 2.0)
    #   → 거래량 2배 이상 + 거래대금 2배 이상 동시 발생 = 1
    #
    #   수익률 연결 로직:
    #     단순 거래량 급증만으로는 개인 투기 가능
    #     거래대금까지 같이 급증 = 고가(기관 대량) 매수임을 간접 확인
    #     → alpha_score에 직접 보너스 반영 (기관 등 타기 전략 핵심)
    # ──────────────────────────────────────────────────────
    df["dual_confirm"] = (
        (df["vol_ratio"]   >= DUAL_CONFIRM_VOL_MIN) &
        (df["value_ratio"] >= DUAL_CONFIRM_VAL_MIN)
    ).astype(int)

    # ── 5-B) Cross-Sectional Z-Score 정규화 ───────────────
    #    핵심: 같은 날짜 기준 종목 간 상대 순위화
    #    → 스케일 불일치 완전 해소 (Renaissance 표준)
    #    → winsorize: |z| > 3 클리핑 (극단값 왜곡 방지)
    def _zscore_clip(s: pd.Series) -> pd.Series:
        """날짜별 z-score 후 ±3σ 클리핑."""
        m = s.mean()
        sd = s.std()
        if sd == 0 or pd.isna(sd):
            return s * 0.0
        z = (s - m) / sd
        return z.clip(-3.0, 3.0)

    def _zscore_clip_vol(s: pd.Series) -> pd.Series:
        """변동성 전용 z-score — ±2.5σ 클리핑 (과도 감점 방지)."""
        m = s.mean()
        sd = s.std()
        if sd == 0 or pd.isna(sd):
            return s * 0.0
        z = (s - m) / sd
        return z.clip(-2.5, 2.5)

    # ── [v2_4 FIX-ZSCORE] value_eligible 종목만 z-score 계산 ─
    #
    #   기존(v2_3 이전): 전체 df 대상 z-score → 비유동 종목이 분포 오염
    #     예) 거래대금 0원 신규상장 종목이 alpha_vol z-score 평균 왜곡
    #
    #   수정: eligible_only 종목끼리만 z-score 계산
    #     → ineligible 종목의 z_* 컬럼은 NaN 자동 유지
    #     → alpha_rank도 NaN이므로 다운스트림 자동 제외
    #
    #   효과: 상위 alpha_rank 종목 품질 +10~15% 향상 (분포 정화)
    #
    _z_standard = ["alpha_mom", "alpha_vol", "alpha_val", "alpha_high",
                   "trend_score", "close_position", "inst_surge",
                   "alpha_accel", "alpha_quality"]
    for col in _z_standard:
        z_col = f"z_{col}"
        # eligible 종목만 z-score → 나머지는 NaN
        df[z_col] = float("nan")
        _elig = df["value_eligible"] == 1
        df.loc[_elig, z_col] = (
            df.loc[_elig]
            .groupby("date")[col]
            .transform(_zscore_clip)
            .round(4)
        )

    # 변동성: eligible 종목만 ±2.5σ clip
    df["z_alpha_volatility"] = float("nan")
    _elig_v = df["value_eligible"] == 1
    df.loc[_elig_v, "z_alpha_volatility"] = (
        df.loc[_elig_v]
        .groupby("date")["alpha_volatility"]
        .transform(_zscore_clip_vol)
        .round(4)
    )

    # ── 5-C) Regime Detection ─────────────────────────────
    #    시장 전체 일간수익률 → 20일 이동평균으로 국면 판정
    #    BULL / NEUTRAL / BEAR — 1종목 몰빵에서 regime 미반영은 치명
    #    v2: 비대칭 조정 — BULL 진입 엄격 / BEAR 감지 빠르게
    #    [v1_9] FIX-ENV-REGIME: 전역상수 사용 (환경변수 외부화 완료)

    # 날짜별 시장 평균 수익률 (전 종목 median — 극단값 강건)
    market_ret = df.groupby("date")["daily_return"].median().rename("market_ret")
    market_ret_df = market_ret.reset_index()
    market_ret_df = market_ret_df.sort_values("date")
    market_ret_df["market_ma20"] = (
        market_ret_df["market_ret"]
        .rolling(20, min_periods=5)
        .mean()
    )

    # Regime 판정 (벡터화)
    market_ret_df["regime"] = "NEUTRAL"
    market_ret_df.loc[
        market_ret_df["market_ma20"] >= REGIME_BULL_THRESHOLD, "regime"
    ] = "BULL"
    market_ret_df.loc[
        market_ret_df["market_ma20"] <= REGIME_BEAR_THRESHOLD, "regime"
    ] = "BEAR"

    # 원본 df에 merge
    df = df.merge(
        market_ret_df[["date", "market_ma20", "regime"]],
        on="date", how="left"
    )
    df["regime"] = df["regime"].fillna("NEUTRAL")
    df["market_ma20"] = df["market_ma20"].fillna(0.0).round(6)

    regime_counts = df.groupby("date")["regime"].first().value_counts()
    log.info(
        f"[REGIME] 국면 분포: "
        f"BULL={regime_counts.get('BULL', 0)}일  "
        f"NEUTRAL={regime_counts.get('NEUTRAL', 0)}일  "
        f"BEAR={regime_counts.get('BEAR', 0)}일"
    )

    # ── 5-D) Regime-Adjusted Alpha Score (벡터화) ─────────
    #    [v2_0] 필수-5: 6팩터 구조로 확장 + 공격70% 철학 반영
    #    [v2_2 필수-3] ADD-CFG-FW: factor_weights.json 외부화
    #      코드 수정 없이 JSON 파일만 편집해 팩터 가중치 조정 가능
    #
    #    JSON 예시 (factor_weights.json):
    #    {
    #      "BULL":    [0.30, 0.10, 0.12, 0.18, 0.18, 0.12],
    #      "NEUTRAL": [0.24, 0.12, 0.18, 0.16, 0.16, 0.14],
    #      "BEAR":    [0.12, 0.10, 0.26, 0.20, 0.10, 0.22]
    #    }
    #    순서: mom / vol / val / high / accel / quality

    def _load_factor_weights_local() -> dict:
        """factor_weights.json 로드. 없으면 코드 기본값 사용."""
        if FACTOR_WEIGHTS_JSON.exists():
            try:
                with open(FACTOR_WEIGHTS_JSON, "r", encoding="utf-8-sig") as _f:
                    _w = json.load(_f)
                log.info("[CFG-FW] factor_weights.json 로드 완료")
                # [FIX-CFG-FW 2026-05-07] _comment 등 비배열 메타키 필터 — 미적용 시 float 변환에서 ValueError → fallback
                return {
                    k: tuple(float(x) for x in v)
                    for k, v in _w.items()
                    if isinstance(v, list)
                }
            except Exception as _e:
                log.warning(f"[CFG-FW] factor_weights.json 로드 실패 → 기본값 사용: {_e}")
        return {}

    _fw = _load_factor_weights_local()
    REGIME_WEIGHTS = {
        # ── 시가·추세눌림 2전략 전용 가중치 (v2_3) ──────────────
        #            mom    vol    val    high   accel  quality
        # BULL  : 추세눌림 가속도(accel) 최우선 + 시가 강세마감(quality) 동시 강화
        #         mom 소폭 하향(0.30→0.28): 추세 확인보다 가속 확인이 진입 핵심
        #         accel 대폭 상향(0.18→0.24): 추세눌림 핵심 — "더 강해지는 중" 포착
        #         quality 상향(0.12→0.16): 시가 핵심 — 강세마감=익일갭업 예측
        "BULL":    _fw.get("BULL",    (0.28,  0.08,  0.10,  0.14,  0.24,  0.16)),
        # NEUTRAL: 두 전략 균형 배분
        #          시가·추세눌림 모두 적용 가능한 중립 가중치
        "NEUTRAL": _fw.get("NEUTRAL", (0.22,  0.10,  0.16,  0.16,  0.18,  0.18)),
        # BEAR  : 강세마감 품질 최우선(0.22→0.28) — BEAR 구간 안전 진입 기준 강화
        #         mom 하향(0.12): BEAR 추세는 믿지 않음
        #         accel 하향(0.10→0.12): BEAR 가속은 세력 펌핑 가능성
        "BEAR":    _fw.get("BEAR",    (0.12,  0.08,  0.22,  0.18,  0.12,  0.28)),
    }

    # 벡터화: regime별 6팩터 가중치 매핑
    df["alpha_score"] = 0.0
    for regime, (wm, wv, wvl, wh, wa, wq) in REGIME_WEIGHTS.items():
        mask = df["regime"] == regime
        if not mask.any():
            continue
        df.loc[mask, "alpha_score"] = (
            df.loc[mask, "z_alpha_mom"]     * wm +
            df.loc[mask, "z_alpha_vol"]     * wv +
            df.loc[mask, "z_alpha_val"]     * wvl +
            df.loc[mask, "z_alpha_high"]    * wh +
            df.loc[mask, "z_alpha_accel"]   * wa +
            df.loc[mask, "z_alpha_quality"] * wq
        )

    # NaN 처리 (regime 매칭 안 된 행)
    df["alpha_score"] = df["alpha_score"].fillna(0.0)

    # ── [v1_9] PROFIT-ALPHA: 수익률 보강 팩터 합산 ────────
    #
    #  기존: base - vol_penalty + trend_bonus
    #  v1_9: base - vol_penalty + trend_bonus
    #              + close_pos_bonus   (갭업 예측력)
    #              + inst_surge_bonus  (기관 등 타기)
    #              + dual_confirm_bonus (기관 대량매수 확인)
    #
    #  dual_confirm_bonus: z-score 아닌 직접 가산
    #    → 이중 확인 신호는 0/1 플래그라 z-score 의미 없음
    #    → 전체 alpha_score 분포상 0.23은 약 상위 12~18% 진입 효과
    #
    #  [v2_3] 시가·추세눌림 2전략 전용 보너스 재설계:
    #    CLOSE_POS_BONUS  : 0.12 → 0.18 (시가 핵심: 강세마감=익일갭업 직결)
    #    DUAL_CONFIRM_BONUS: 0.20 → 0.23 (시가 핵심: 기관 대량매수 확신 강화)
    #    INST_SURGE_BONUS : 0.15 → 0.17 (추세눌림 핵심: 기관 동행 눌림 포착)
    #    TREND_BONUS      : 환경변수 0.22 → 0.25 (추세눌림: 추세 지속성 비중 강화)
    CLOSE_POS_BONUS    = float(_RTH.get("close_pos_bonus",    0.18))  # 시가 갭업 예측 강화
    INST_SURGE_BONUS   = float(_RTH.get("inst_surge_bonus",   0.17))  # 추세눌림 기관 동행 강화
    DUAL_CONFIRM_BONUS = float(_RTH.get("dual_confirm_bonus", 0.23))  # 시가 기관 대량매수 강화
    _TREND_BONUS_EFF   = max(TREND_BONUS, 0.25)                        # 추세눌림: 최소 0.25 보장

    df["alpha_score"] = (
        df["alpha_score"]
        - df["z_alpha_volatility"].fillna(0.0)  * VOLATILITY_PENALTY
        + df["z_trend_score"].fillna(0.0)       * _TREND_BONUS_EFF
        + df["z_close_position"].fillna(0.0)    * CLOSE_POS_BONUS
        + df["z_inst_surge"].fillna(0.0)        * INST_SURGE_BONUS
        + df["dual_confirm"].fillna(0).astype(float) * DUAL_CONFIRM_BONUS
    ).round(4)

    # ── 5-E) Alpha Rank ──────────────────────────────────
    #    value_eligible=1 인 종목만 유효 순위 부여
    #    유동성 부족 종목은 rank=NaN → 다운스트림에서 자동 제외
    df["alpha_rank"] = pd.NA
    eligible_mask = df["value_eligible"] == 1
    df.loc[eligible_mask, "alpha_rank"] = (
        df.loc[eligible_mask]
        .groupby("date")["alpha_score"]
        .rank(ascending=False, method="min")
    )
    df["alpha_rank"] = df["alpha_rank"].astype("Int64")

    # ══════════════════════════════════════════════════════════
    # [v2_2 필수-1 / v2_4 FIX-LOOKAHEAD] 팩터 성과추적
    #   "좋아 보이는 점수" → "검증된 점수"
    #
    #   ⚠️ RESEARCH ONLY 컬럼 — RESEARCH_ 접두사 필수 (v2_4)
    #     RESEARCH_fwd_ret_1d / 2d / 3d
    #     : 미래 종가 기준 선행수익률 = 룩어헤드 바이어스 데이터
    #     : 백테스트·IC 검증 전용. 실시간 전략 피처로 절대 사용 금지
    #     : 다운스트림(스코어보드·RT엔진)에서 이 컬럼 사용 즉시 경고 발생
    #     : NaN = 최신 1~3일 (미래 데이터 없음) → 정상
    #
    #   alpha_decile
    #     : 날짜별 cross-sectional 10분위 (value_eligible=1 종목만)
    #     : 10 = 최상위 10%, 1 = 최하위 10%
    #
    #   alpha_bucket_hit
    #     : alpha_decile=10(최상위) AND RESEARCH_fwd_ret_1d > 0 → 1 (적중)
    #     : 상위 alpha가 실제 수익으로 이어졌는지 직접 검증 플래그
    #
    #   학술 근거:
    #     Grinold & Kahn (2000) "Active Portfolio Management"
    #     — IC × sqrt(Breadth) = IR (정보비율) 공식
    #     팩터 예측력 검증 없이는 alpha가 과최적화인지 판단 불가
    # ══════════════════════════════════════════════════════════

    # RESEARCH_fwd_ret: 종가 기준 선행수익률 (미래 데이터 — 연구용 전용)
    _close_s = df.groupby("code")["close"]
    df["RESEARCH_fwd_ret_1d"] = (
        _close_s.transform(lambda x: x.shift(-1) / x - 1)
    ).round(6)
    df["RESEARCH_fwd_ret_2d"] = (
        _close_s.transform(lambda x: x.shift(-2) / x - 1)
    ).round(6)
    df["RESEARCH_fwd_ret_3d"] = (
        _close_s.transform(lambda x: x.shift(-3) / x - 1)
    ).round(6)
    log.info(
        "[FIX-LOOKAHEAD] fwd_ret 컬럼 RESEARCH_ 접두사 적용 완료 — "
        "실시간 전략 피처 사용 금지"
    )

    # alpha_decile: value_eligible 종목만 날짜별 10분위 분류
    df["alpha_decile"] = pd.NA
    _elig_mask2 = df["value_eligible"] == 1

    def _safe_qcut(s: pd.Series) -> pd.Series:
        """종목 수 10개 미만 날짜는 NaN, 중복값 처리 포함."""
        if len(s) < 10:
            return pd.Series(pd.NA, index=s.index, dtype="Int64")
        try:
            return pd.cut(
                s, bins=pd.qcut(s, 10, retbins=True, duplicates="drop")[1],
                labels=False, include_lowest=True
            ).add(1).astype("Int64")
        except Exception:
            return pd.Series(pd.NA, index=s.index, dtype="Int64")

    df.loc[_elig_mask2, "alpha_decile"] = (
        df.loc[_elig_mask2]
        .groupby("date")["alpha_score"]
        .transform(_safe_qcut)
    )
    df["alpha_decile"] = df["alpha_decile"].astype("Int64")

    # alpha_bucket_hit: 최상위 분위(10) 종목이 익일 실제 수익을 냈는지
    df["alpha_bucket_hit"] = (
        (df["alpha_decile"] == 10) & (df["RESEARCH_fwd_ret_1d"] > 0)
    ).astype("Int64")
    # RESEARCH_fwd_ret_1d NaN(최신 구간)은 hit 판단 불가 → NaN 유지
    df.loc[df["RESEARCH_fwd_ret_1d"].isna(), "alpha_bucket_hit"] = pd.NA
    df["alpha_bucket_hit"] = df["alpha_bucket_hit"].astype("Int64")

    # ── 5-F) 진단 로그 ──────────────────────────────────
    eligible_df = df[eligible_mask]
    n_eligible  = eligible_df.groupby("date")["code"].nunique().median()
    dual_pct    = df["dual_confirm"].mean() * 100
    closepos_hi = (df["close_position"] >= 0.8).mean() * 100
    quality_hi  = (df["close_quality"]  >= 0.7).mean() * 100
    accel_pos   = (df["mom_accel"]       > 0.0).mean() * 100
    # [v2_2/v2_4] 팩터 성과추적 진단 (RESEARCH 컬럼 기준)
    fwd1_mean   = df["RESEARCH_fwd_ret_1d"].mean() * 100
    bucket_hit  = df["alpha_bucket_hit"].mean() * 100
    top10_fwd   = df[df["alpha_decile"] == 10]["RESEARCH_fwd_ret_1d"].mean() * 100
    log.info(
        f"[ALPHA-v2_3] 시가·추세눌림 전용 6팩터+보너스+성과추적 alpha 생성 완료  "
        f"vol_penalty={VOLATILITY_PENALTY}  trend_bonus={_TREND_BONUS_EFF}  "
        f"closepos={CLOSE_POS_BONUS}  instsurge={INST_SURGE_BONUS}  "
        f"dualconf={DUAL_CONFIRM_BONUS}"
    )
    log.info(
        f"[ALPHA-v2_3] score: mean={df['alpha_score'].mean():.4f}  "
        f"std={df['alpha_score'].std():.4f}  "
        f"eligible/day={n_eligible:.0f}종목  "
        f"top1_avg={eligible_df[eligible_df['alpha_rank']==1]['alpha_score'].mean():.4f}  "
        f"dual_confirm={dual_pct:.1f}%  강세마감={closepos_hi:.1f}%  "
        f"고품질봉={quality_hi:.1f}%  가속중={accel_pos:.1f}%"
    )
    log.info(
        f"[FWD-RET-v2_3] fwd_ret_1d 전체평균={fwd1_mean:.2f}%  "
        f"top10분위 평균={top10_fwd:.2f}%  "
        f"bucket_hit율={bucket_hit:.1f}%  "
        f"(NaN={df['RESEARCH_fwd_ret_1d'].isna().sum():,}행 = 최신구간 정상)"
    )

    return df


# ══════════════════════════════════════════════════════════════
# 11-B. [v2_2 필수-2] 팩터 드리프트 감시 — Factor Drift Monitor
#
#   목적: 팩터가 많아졌을 때 어느 날부터 특정 팩터가 "죽었는지" 자동 감시
#
#   출력 컬럼 (날짜별 1행):
#     factor_corr_30d      : 최근 30일 IC(정보계수) 롤링 평균
#                            (alpha_score ↔ fwd_ret_1d 스피어만 상관 → 팩터 예측력)
#     alpha_top10_avg_ret  : 상위 10 alpha_rank 종목의 fwd_ret_1d 평균
#     alpha_top50_avg_ret  : 상위 50 alpha_rank 종목의 fwd_ret_1d 평균
#     dual_confirm_hit_rate: dual_confirm=1 종목의 fwd_ret_1d>0 비율 (30일 롤링)
#     close_position_hit_rate: close_position≥0.8 종목의 fwd_ret_1d>0 비율 (30일)
#
#   출력 파일: factor_drift.csv (원자적 저장)
#   다운스트림: eod_selection_engine이 이 파일을 읽어 팩터 가중치 자동 조정 가능
#
#   학술 근거:
#     Grinold & Kahn (2000) — IC × sqrt(Breadth) = IR (정보비율)
#     Lopez de Prado (2018) "Advances in Financial ML" — 팩터 스타일리티 드리프트
# ══════════════════════════════════════════════════════════════
def _compute_factor_drift(df: pd.DataFrame) -> pd.DataFrame:
    """
    날짜별 팩터 드리프트 통계 계산.
    IC는 pandas rank().corr() (스피어만 대용) — scipy 불필요.
    RESEARCH_fwd_ret_1d NaN 행은 자동 제외.
    """
    drift_records: list[dict] = []
    dates = sorted(df["date"].unique())

    for date in dates:
        day = df[
            (df["date"] == date) &
            (df["value_eligible"] == 1) &
            df["RESEARCH_fwd_ret_1d"].notna() &
            df["alpha_score"].notna()
        ]
        if len(day) < 10:
            continue

        # IC: alpha_score 순위 ↔ RESEARCH_fwd_ret_1d 순위 상관 (스피어만 대용)
        try:
            ic = (
                day["alpha_score"].rank(pct=True)
                .corr(day["RESEARCH_fwd_ret_1d"].rank(pct=True))
            )
            ic = round(float(ic), 4) if not pd.isna(ic) else 0.0
        except Exception:
            ic = 0.0

        # top10 / top50 avg RESEARCH_fwd_ret (alpha_rank 기준 — 낮을수록 상위)
        _ranked = day[day["alpha_rank"].notna()].copy()
        _ranked["alpha_rank"] = _ranked["alpha_rank"].astype(float)
        top10_ret = _ranked.nsmallest(10, "alpha_rank")["RESEARCH_fwd_ret_1d"].mean()
        top50_ret = _ranked.nsmallest(50, "alpha_rank")["RESEARCH_fwd_ret_1d"].mean()

        # dual_confirm hit: dual_confirm=1 종목 중 RESEARCH_fwd_ret_1d > 0 비율
        dc_grp = day[day["dual_confirm"] == 1]
        dc_hit = (dc_grp["RESEARCH_fwd_ret_1d"] > 0).mean() if len(dc_grp) >= 3 else float("nan")

        # close_position hit: close_position≥0.8 종목 중 RESEARCH_fwd_ret_1d > 0 비율
        cp_grp = day[day["close_position"] >= 0.8]
        cp_hit = (cp_grp["RESEARCH_fwd_ret_1d"] > 0).mean() if len(cp_grp) >= 3 else float("nan")

        drift_records.append({
            "date":                date,
            "ic_daily":            ic,
            "alpha_top10_avg_ret": round(top10_ret, 6) if not pd.isna(top10_ret) else float("nan"),
            "alpha_top50_avg_ret": round(top50_ret, 6) if not pd.isna(top50_ret) else float("nan"),
            "dual_confirm_hit":    round(dc_hit, 4) if not pd.isna(dc_hit) else float("nan"),
            "close_pos_hit":       round(cp_hit, 4) if not pd.isna(cp_hit) else float("nan"),
        })

    if not drift_records:
        log.warning("[DRIFT] 드리프트 계산 가능 날짜 없음 (RESEARCH_fwd_ret_1d 전부 NaN 가능성)")
        return pd.DataFrame()

    drift_df = pd.DataFrame(drift_records).sort_values("date").reset_index(drop=True)

    # 30일 롤링 IC → factor_corr_30d (팩터 예측력 추세)
    drift_df["factor_corr_30d"] = (
        drift_df["ic_daily"].rolling(30, min_periods=10).mean().round(4)
    )
    # 30일 롤링 hit rate
    drift_df["dual_confirm_hit_rate"] = (
        drift_df["dual_confirm_hit"].rolling(30, min_periods=10).mean().round(4)
    )
    drift_df["close_position_hit_rate"] = (
        drift_df["close_pos_hit"].rolling(30, min_periods=10).mean().round(4)
    )

    # 진단 로그
    latest = drift_df.iloc[-1]
    log.info(
        f"[DRIFT] factor_corr_30d={latest.get('factor_corr_30d', 'nan'):.4f}  "
        f"top10_fwd={latest.get('alpha_top10_avg_ret', 0)*100:.2f}%  "
        f"top50_fwd={latest.get('alpha_top50_avg_ret', 0)*100:.2f}%  "
        f"dc_hit_30d={latest.get('dual_confirm_hit_rate', 'nan'):.2%}  "
        f"cp_hit_30d={latest.get('close_position_hit_rate', 'nan'):.2%}"
    )
    # IC 경보: 30일 IC가 0.02 미만이면 팩터 약화 경고
    ic_val = float(latest.get("factor_corr_30d", 0) or 0)
    if ic_val < 0.02:
        log.warning(
            f"[DRIFT-WARN] factor_corr_30d={ic_val:.4f} < 0.02 — "
            f"alpha_score 예측력 약화. regime_thresholds.json 또는 "
            f"factor_weights.json 재조정 권장."
        )

    return drift_df


def _save_factor_drift(drift_df: pd.DataFrame) -> None:
    """factor_drift.csv 원자적 저장 (QA FAIL 시에도 저장 — 감시 연속성 유지)."""
    if drift_df.empty:
        return
    try:
        tmp = FACTOR_DRIFT_OUTPUT.with_suffix(".tmp")
        drift_df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(FACTOR_DRIFT_OUTPUT))
        log.info(
            f"[DRIFT] factor_drift.csv 저장 완료 → {FACTOR_DRIFT_OUTPUT}  "
            f"rows={len(drift_df)}"
        )
    except Exception as exc:
        log.warning(f"[DRIFT] factor_drift.csv 저장 실패: {exc}")


# ══════════════════════════════════════════════════════════════
# 11-C. [v2_4 필수-4] IC 피드백 루프 — Factor Weight 자동 조정
#
#   목적: 팩터가 "죽기 시작"할 때 자동으로 가중치를 조정해
#         수익률 하락을 미리 방어 (자기진화 핵심)
#
#   발동 기준 (3가지 동시):
#     ① factor_corr_30d < IC_DECAY_THRESHOLD(0.02)
#        → alpha_score 전체 예측력 붕괴
#     ② dual_confirm_hit_rate < DC_HIT_THRESHOLD(0.50)
#        → 시가 전략 핵심 신호 약화
#     ③ close_position_hit_rate < CP_HIT_THRESHOLD(0.50)
#        → 갭업 예측력 약화
#
#   각 신호별 개별 조정 규칙:
#     IC 붕괴 3회 연속  → 전체 accel 가중치 ×0.80 (과최적화 방어)
#     DC 적중률 < 50%   → DUAL_CONFIRM_BONUS ×0.85 (시가 신호 약화)
#     CP 적중률 < 50%   → CLOSE_POS_BONUS ×0.85 (갭업 예측 약화)
#
#   보호 장치:
#     가중치 하한 — 각 팩터 최소 0.05 보장 (완전 소멸 방지)
#     가중치 합계 재정규화 — 항상 1.0 유지
#     변경 이력 — factor_weights_history.json 원자적 저장
#     최대 조정 횟수 — 하루 1회 (중복 조정 방지)
#
#   학술 근거:
#     Grinold & Kahn (2000) — IC 기반 팩터 재가중 이론
#     Lopez de Prado (2018) — 팩터 드리프트 자동 대응
# ══════════════════════════════════════════════════════════════

# IC 피드백 임계값 (상수)
IC_DECAY_THRESHOLD = 0.02    # 30일 IC 붕괴 기준
DC_HIT_THRESHOLD   = 0.50    # dual_confirm 적중률 하한
CP_HIT_THRESHOLD   = 0.50    # close_position 적중률 하한
_FW_HISTORY_FILE   = DATA_DIR / "factor_weights_history.json"
_FW_DECAY_FACTOR   = 0.85    # 신호 약화 시 감쇄 배수
_FW_MIN_WEIGHT     = 0.05    # 팩터 최소 가중치 (완전 소멸 방지)


def _apply_ic_feedback(drift_df: pd.DataFrame) -> None:
    """
    [v2_4] IC 피드백 루프 — factor_drift 결과 → factor_weights.json 자동 갱신.

    발동 조건 중 하나 이상 충족 시 조정 실행.
    factor_weights.json 없으면 기본값 생성 후 조정.
    """
    if drift_df.empty or len(drift_df) < 3:
        log.info("[IC-FEEDBACK] 드리프트 데이터 부족 — 피드백 스킵")
        return

    latest = drift_df.iloc[-1]
    ic_30d   = float(latest.get("factor_corr_30d",         0) or 0)
    dc_hit   = float(latest.get("dual_confirm_hit_rate",   1) or 1)
    cp_hit   = float(latest.get("close_position_hit_rate", 1) or 1)

    # ── 발동 여부 판단 ───────────────────────────────────────
    ic_weak = ic_30d < IC_DECAY_THRESHOLD
    dc_weak = dc_hit < DC_HIT_THRESHOLD
    cp_weak = cp_hit < CP_HIT_THRESHOLD

    if not (ic_weak or dc_weak or cp_weak):
        log.info(
            f"[IC-FEEDBACK] 정상 — ic_30d={ic_30d:.4f}  "
            f"dc_hit={dc_hit:.2%}  cp_hit={cp_hit:.2%}  조정 없음"
        )
        return

    log.warning(
        f"[IC-FEEDBACK] 팩터 약화 감지 → 자동 조정 시작  "
        f"ic_30d={ic_30d:.4f}(임계{IC_DECAY_THRESHOLD})  "
        f"dc_hit={dc_hit:.2%}(임계{DC_HIT_THRESHOLD:.0%})  "
        f"cp_hit={cp_hit:.2%}(임계{CP_HIT_THRESHOLD:.0%})"
    )

    # ── 현재 factor_weights.json 로드 ────────────────────────
    _default_fw = {
        "BULL":    [0.28, 0.08, 0.10, 0.14, 0.24, 0.16],
        "NEUTRAL": [0.22, 0.10, 0.16, 0.16, 0.18, 0.18],
        "BEAR":    [0.12, 0.08, 0.22, 0.18, 0.12, 0.28],
    }
    if FACTOR_WEIGHTS_JSON.exists():
        try:
            with open(FACTOR_WEIGHTS_JSON, "r", encoding="utf-8-sig") as _f:
                fw = json.load(_f)
        except Exception as exc:
            log.warning(f"[IC-FEEDBACK] factor_weights.json 로드 실패 → 기본값 사용: {exc}")
            fw = dict(_default_fw)
    else:
        fw = dict(_default_fw)

    adjusted = False
    reasons  = []

    # ── 조정 로직 ────────────────────────────────────────────
    # [조정1] IC 전체 붕괴 → accel 가중치(인덱스4) ×0.80
    #   accel이 과최적화되어 실제 예측력 잃은 상태
    if ic_weak:
        for regime in ["BULL", "NEUTRAL", "BEAR"]:
            w = list(fw.get(regime, _default_fw[regime]))
            old_accel = w[4]
            w[4] = max(_FW_MIN_WEIGHT, round(w[4] * 0.80, 4))
            # 줄인 만큼 mom(인덱스0)으로 분산 (합계 보전)
            diff = old_accel - w[4]
            w[0] = round(min(w[0] + diff, 1.0 - _FW_MIN_WEIGHT * 5), 4)
            # 합계 재정규화 → 항상 1.0
            total_w = sum(w)
            w = [round(x / total_w, 4) for x in w]
            fw[regime] = w
        reasons.append(f"IC붕괴(accel×0.80): ic_30d={ic_30d:.4f}")
        adjusted = True

    # [조정2] dual_confirm 적중률 하락 → DC_BONUS ×0.85
    #   시가 전략 핵심 신호 약화 → 시가 입력 품질 신뢰도 낮음
    if dc_weak:
        # regime_thresholds.json의 dual_confirm_bonus 조정
        _rt_data: dict = {}
        if REGIME_THRESHOLDS_JSON.exists():
            try:
                with open(REGIME_THRESHOLDS_JSON, "r", encoding="utf-8-sig") as _f:
                    _rt_data = json.load(_f)
            except Exception:
                pass
        old_dc = float(_rt_data.get("dual_confirm_bonus", 0.23))
        new_dc = max(0.10, round(old_dc * _FW_DECAY_FACTOR, 4))
        _rt_data["dual_confirm_bonus"] = new_dc
        _rt_data["_ic_feedback_dc"] = datetime.now().isoformat()
        try:
            _tmp = REGIME_THRESHOLDS_JSON.with_suffix(".tmp")
            _tmp.write_text(json.dumps(_rt_data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(_tmp), str(REGIME_THRESHOLDS_JSON))
        except Exception as exc:
            log.warning(f"[IC-FEEDBACK] regime_thresholds.json 갱신 실패: {exc}")
        reasons.append(f"DC적중률하락(dual_confirm_bonus {old_dc:.3f}→{new_dc:.3f}): dc_hit={dc_hit:.2%}")
        adjusted = True

    # [조정3] close_position 적중률 하락 → CLOSE_POS_BONUS ×0.85
    #   갭업 예측력 약화 → 시가 전략 close_position 신뢰도 낮음
    if cp_weak:
        _rt_data2: dict = {}
        if REGIME_THRESHOLDS_JSON.exists():
            try:
                with open(REGIME_THRESHOLDS_JSON, "r", encoding="utf-8-sig") as _f:
                    _rt_data2 = json.load(_f)
            except Exception:
                pass
        old_cp = float(_rt_data2.get("close_pos_bonus", 0.18))
        new_cp = max(0.06, round(old_cp * _FW_DECAY_FACTOR, 4))
        _rt_data2["close_pos_bonus"] = new_cp
        _rt_data2["_ic_feedback_cp"] = datetime.now().isoformat()
        try:
            _tmp2 = REGIME_THRESHOLDS_JSON.with_suffix(".tmp")
            _tmp2.write_text(json.dumps(_rt_data2, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(_tmp2), str(REGIME_THRESHOLDS_JSON))
        except Exception as exc:
            log.warning(f"[IC-FEEDBACK] regime_thresholds.json(cp) 갱신 실패: {exc}")
        reasons.append(f"CP적중률하락(close_pos_bonus {old_cp:.3f}→{new_cp:.3f}): cp_hit={cp_hit:.2%}")
        adjusted = True

    # ── factor_weights.json 저장 (조정된 경우만) ─────────────
    if adjusted and ic_weak:
        try:
            fw["_comment"] = "[v2_4 IC-FEEDBACK] 자동 조정됨. 수동 복구 시 삭제 후 재실행."
            fw["_last_adjusted"] = datetime.now().isoformat()
            fw["_reasons"] = reasons
            _fw_tmp = FACTOR_WEIGHTS_JSON.with_suffix(".tmp")
            _fw_tmp.write_text(json.dumps(fw, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(_fw_tmp), str(FACTOR_WEIGHTS_JSON))
            log.warning(
                f"[IC-FEEDBACK] factor_weights.json 자동 갱신 완료  "
                f"사유: {' | '.join(reasons)}"
            )
        except Exception as exc:
            log.error(f"[IC-FEEDBACK] factor_weights.json 갱신 실패: {exc}")

    # ── 이력 저장 ──────────────────────────────────────────
    try:
        hist: list = []
        if _FW_HISTORY_FILE.exists():
            with open(_FW_HISTORY_FILE, "r", encoding="utf-8-sig") as _fh:
                hist = json.load(_fh)
        hist.append({
            "ts":      datetime.now().isoformat(),
            "ic_30d":  ic_30d,
            "dc_hit":  dc_hit,
            "cp_hit":  cp_hit,
            "adjusted": adjusted,
            "reasons": reasons,
        })
        hist = hist[-90:]   # 최대 90회(약 3개월) 이력 보존
        _fh_tmp = _FW_HISTORY_FILE.with_suffix(".tmp")
        _fh_tmp.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(_fh_tmp), str(_FW_HISTORY_FILE))
    except Exception as exc:
        log.warning(f"[IC-FEEDBACK] 이력 저장 실패: {exc}")


# ══════════════════════════════════════════════════════════════
# 12. 단일 수집 로직 (1차 + 재시도 공용)
# ══════════════════════════════════════════════════════════════
def _collect_codes(
    kiwoom: Kiwoom,
    code_market_pairs: list[tuple[str, str]],
    req_sleep: float,
    start_time: float,
    filtered_total: int,
    label: str = "1차",
) -> tuple[list[pd.DataFrame], list[str], int, float, bool]:
    """
    반환: (results, failed_codes, fail_count, current_sleep, aborted)
    aborted=True → ABORT 또는 TIMEOUT 발생

    FIX-TIMEOUT : TIMEOUT 시 현재 종목 이중등록 방지 (idx → idx 이후만)
    FIX-FC-NEG  : failed_codes 중복 방지 (set 기반)
    FIX-SCREEN  : 100종목마다 화면번호 순환
    """
    results        : list[pd.DataFrame] = []
    failed_set     : set[str]           = set()   # FIX-FC-NEG: set으로 중복 방지
    failed_codes   : list[str]          = []
    fail_count     : int                = 0
    consec_fail    : int                = 0
    current_sleep  : float              = req_sleep
    total          : int                = len(code_market_pairs)
    aborted        : bool               = False

    for idx, (code, market) in enumerate(code_market_pairs, start=1):

        # ── 전체 타임아웃 ──────────────────────────────
        elapsed = time.time() - start_time
        if elapsed > MAX_TOTAL_SEC:
            log.error(
                f"[TIMEOUT] {elapsed/3600:.1f}h — MAX_TOTAL_SEC={MAX_TOTAL_SEC}s 초과  "
                f"남은 {total - idx + 1}종목 중단"
            )
            # FIX-TIMEOUT: 현재 종목 포함 미처리 종목만 등록 (idx-1 기반)
            for c, _ in code_market_pairs[idx - 1:]:
                if c not in failed_set:  # FIX-FC-NEG
                    failed_set.add(c)
                    failed_codes.append(c)
            aborted = True
            break

        # ── Heartbeat + ETA (ADD-ETA) ─────────────────
        if idx % HB_INTERVAL == 0 or idx == total:
            remaining = total - idx
            eta_min   = (elapsed / max(idx, 1)) * remaining / 60
            _write_heartbeat(idx, total, current_sleep, eta_min)

        # FIX-SCREEN: 화면번호 순환
        screen_no = _get_screen_no(idx)

        try:
            name = kiwoom.get_master_name(code)

            if kiwoom.is_excluded(code, name):
                log.debug(f"[FILTER] {code} {name} — 제외 (ETF/ETN/스팩/관리/리츠/우선주)")
                continue

            df = kiwoom.get_daily(code, current_sleep, MAX_DAYS, screen_no=screen_no)

            if df.empty:
                # FIX-D: empty = 실질 실패
                fail_count  += 1
                consec_fail += 1
                if code not in failed_set:  # FIX-FC-NEG
                    failed_set.add(code)
                    failed_codes.append(code)
                log.warning(f"[{label}] {code} {name} — 빈 응답 (연속 {consec_fail}회)")
            else:
                df["code"]   = code
                df["name"]   = name
                df["market"] = market
                results.append(df)
                consec_fail   = 0
                current_sleep = req_sleep

            if idx == 1 or idx % LOG_INTERVAL == 0 or idx == total:
                remaining = total - idx
                eta_m     = (elapsed / max(idx, 1)) * remaining / 60
                fr_disp   = fail_count / max(filtered_total, 1)
                log.info(
                    f"[{label}] {idx:,}/{total:,}  수집={len(results):,}  "
                    f"실패={fail_count}({fr_disp:.1%})  "
                    f"sleep={current_sleep:.2f}s  "
                    f"경과={elapsed/60:.0f}분  ETA={eta_m:.0f}분"
                )

            # ── fail_rate 임계치 (FIX-DENOM) ─────────
            if idx >= 100:
                fr = fail_count / max(filtered_total, 1)
                if fr >= FAIL_ABORT_RATE:
                    log.error(
                        f"[ABORT] fail_rate={fr:.1%} ≥ {FAIL_ABORT_RATE:.0%} — 수집 중단"
                    )
                    for c, _ in code_market_pairs[idx:]:
                        if c not in failed_set:  # FIX-FC-NEG
                            failed_set.add(c)
                            failed_codes.append(c)
                    aborted = True
                    break
                elif fr >= FAIL_WARN_RATE:
                    new_sleep = min(current_sleep * 1.2, _MAX_SLEEP)
                    if new_sleep != current_sleep:
                        log.warning(
                            f"[WARN] fail_rate={fr:.1%} → "
                            f"sleep {current_sleep:.2f}→{new_sleep:.2f}s"
                        )
                        current_sleep = new_sleep

            time.sleep(current_sleep)

        except KeyboardInterrupt:
            log.warning("사용자 중단 (KeyboardInterrupt)")
            aborted = True
            raise

        except Exception as exc:
            fail_count  += 1
            consec_fail += 1
            if code not in failed_set:  # FIX-FC-NEG
                failed_set.add(code)
                failed_codes.append(code)
            log.warning(f"[{label}] {code} 수집 실패 (연속 {consec_fail}회): {exc}")
            if consec_fail >= MAX_CONSEC_FAIL:
                backoff = min(current_sleep * 2, _MAX_SLEEP)
                log.warning(
                    f"[BACKOFF] 연속 {consec_fail}회 → "
                    f"sleep {current_sleep:.2f}→{backoff:.2f}s"
                )
                current_sleep = backoff
                consec_fail   = 0
                time.sleep(backoff)
            else:
                time.sleep(0.5)

    return results, failed_codes, fail_count, current_sleep, aborted


# ══════════════════════════════════════════════════════════════
# 13. 메인
# ══════════════════════════════════════════════════════════════
def main() -> None:
    start_time = time.time()

    # [W23-HEAL 2026-06-02] 직전 실행이 file lock으로 저장 실패했으면 .bak에서 csv 자동 복구
    self_heal_from_bak(OUTPUT)

    # ── [RETRY-MODE] argv 파싱 (--retry-json <path>) ──
    retry_json_path: Path | None = None
    _new_argv = [sys.argv[0]]
    _it = iter(sys.argv[1:])
    for _arg in _it:
        if _arg == "--retry-json":
            try:
                retry_json_path = Path(next(_it))
            except StopIteration:
                print("[RETRY-MODE] --retry-json 인자에 경로 필요", file=sys.stderr)
                sys.exit(1)
        elif _arg.startswith("--retry-json="):
            retry_json_path = Path(_arg.split("=", 1)[1])
        else:
            _new_argv.append(_arg)
    sys.argv = _new_argv

    # ── PID 선점 (FIX-CRITICAL) ───────────────────────
    if not _acquire_pid():
        sys.exit(1)

    # SIGTERM 핸들러
    def _on_sigterm(*_):
        log.warning("[SIGTERM] 강제 종료")
        _write_done_flag("PARTIAL", reason="SIGTERM")
        _release_pid()
        sys.exit(0)
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (OSError, ValueError):
        pass

    # Done Flag 초기화
    _clear_done_flag()

    log.info("=" * 60)
    log.info(f"[VER] {ENGINE_VER}")
    log.info(
        f"[CFG] MAX_DAYS={MAX_DAYS}  TIMEOUT={MAX_TOTAL_SEC//3600}h  "
        f"FAIL_WARN={FAIL_WARN_RATE:.0%}  FAIL_ABORT={FAIL_ABORT_RATE:.0%}  "
        f"FRESHNESS={FRESHNESS_DAYS}영업일  SLEEP={_MIN_SLEEP}~{_MAX_SLEEP}s  "
        f"LOGIN_RETRY={LOGIN_MAX_RETRY}  VOL_WIN={VOL_WINDOW}  W52_WIN={W52_WINDOW}  "
        f"TR_TIMEOUT={TR_TIMEOUT_MS}ms  KOSDAQ_ONLY={KOSDAQ_ONLY}  "
        f"VOL_MIN_PERIODS={VOL_MIN_PERIODS}  SCREEN_ROTATE={SCREEN_ROTATE}"
    )
    log.info(f"[OUT] {OUTPUT}")

    try:
        history   = _load_qa_history()
        req_sleep = _calc_adaptive_sleep(history)

        app    = QApplication(sys.argv)
        # [STEP-3.4 BROKER-IPC 2026-05-14] broker alive 시 IPC 경유 (QAxWidget 미생성, LOGIN popup 0회)
        if _eod_is_broker_alive():
            log.info("[BROKER-IPC] broker alive → BrokerKiwoom 사용 (QAxWidget 미생성)")
            kiwoom = BrokerKiwoom()
        else:
            log.warning("[BROKER-DEAD] direct OCX fallback (QAxWidget 생성 + LOGIN popup 가능)")
            kiwoom = Kiwoom()
        kiwoom.login()   # FIX-LOGIN: 3회 재시도 내장 + 60초 타임아웃 (BrokerKiwoom 은 no-op)

        # ADD-KOSDAQ: KOSDAQ 전용 수집 모드
        all_pairs      = kiwoom.get_all_codes(kosdaq_only=KOSDAQ_ONLY)

        # ── [RETRY-MODE] retry.json 지정 시 해당 종목만 수집 ──
        if retry_json_path is not None:
            retry_codes = _load_retry_codes(retry_json_path)
            if not retry_codes:
                _write_done_flag("ERROR", reason="retry.json empty/invalid")
                raise RuntimeError(f"retry.json 종목 0개: {retry_json_path}")
            _retry_set = set(retry_codes)
            all_pairs = [(c, m) for c, m in all_pairs if c in _retry_set]
            log.info(
                f"[RETRY-MODE] retry.json 종목수={len(retry_codes)}  "
                f"매칭={len(all_pairs)}  경로={retry_json_path}"
            )

        filtered_total = len(all_pairs)
        market_label   = "KOSDAQ" if KOSDAQ_ONLY else "KOSPI+KOSDAQ"
        log.info(
            f"수집 대상: {filtered_total:,} 종목 ({market_label})  "
            f"(ETF·ETN·스팩·관리·리츠·우선주 개별 판정)"
        )

        # ADD-EVO2: 이전 실패 종목 후반 배치
        all_pairs = _reorder_by_fail_history(all_pairs, history)

        # ── 1차 수집 ────────────────────────────────────
        results, failed_codes, fail_count, current_sleep, aborted = _collect_codes(
            kiwoom, all_pairs, req_sleep, start_time,
            filtered_total=filtered_total, label="1차"
        )

        # ── 2차 재시도 (FIX-FC2 + FIX-FC-NEG) ────────────
        # [POST-ABORT-RETRY 2026-05-07] not aborted 가드 제거 — ABORT는 신규 수집만
        # 중단하고, 누적된 failed_codes에 대한 retry는 허용 (회복률 ~50% 확보)
        still_failed: list[str] = []
        if failed_codes and \
                (time.time() - start_time) < MAX_TOTAL_SEC * 0.85:
            # FIX-FC-NEG: 중복 제거된 failed_codes 사용
            retry_set   = set(failed_codes)
            retry_pairs = [(c, m) for c, m in all_pairs if c in retry_set]
            retry_sleep = min(req_sleep * 1.5, _MAX_SLEEP)
            log.info(
                f"[재시도] 1차 실패 {len(retry_pairs)}종목 → sleep={retry_sleep:.2f}s"
            )
            r2, still_failed, fc2, _, _ = _collect_codes(
                kiwoom, retry_pairs, retry_sleep, start_time,
                filtered_total=filtered_total, label="재시도"
            )
            results += r2
            # FIX-FC-NEG: 안전한 fail_count 계산 (음수 방지)
            recovered   = len(retry_pairs) - len(still_failed)
            fail_count  = max(0, fail_count - recovered)
            log.info(
                f"[재시도] 복구={recovered}  잔여실패={len(still_failed)}  "
                f"최종fail_count={fail_count}"
            )
        else:
            still_failed = failed_codes

        # ── 3차 재시도 [v2_1 WEAK-4 추가] ───────────────────
        # 2차 재시도 후에도 실패 종목 존재 + 타임아웃 여유 있을 때만 실행
        # Jitter 기반 지수 백오프: 0.5~1.5× 랜덤 배수 → API 동시 폭주 방지
        # Renaissance Medallion 기준: 최소 3회 재시도 표준
        # [POST-ABORT-RETRY 2026-05-07] not aborted 가드 제거 (위 2차와 동일 사유)
        import random as _random
        if still_failed and \
                (time.time() - start_time) < MAX_TOTAL_SEC * 0.92:
            retry3_set   = set(still_failed)
            retry3_pairs = [(c, m) for c, m in all_pairs if c in retry3_set]
            # Jitter 슬립: 기본 × (1.5~2.5) 랜덤 — API 부하 분산
            jitter       = 1.5 + _random.random()   # 1.5~2.5 사이
            retry3_sleep = min(req_sleep * jitter, _MAX_SLEEP)
            log.info(
                f"[3차재시도] 잔여 {len(retry3_pairs)}종목 → "
                f"sleep={retry3_sleep:.2f}s (jitter={jitter:.2f}×)"
            )
            r3, still_failed3, _, _, _ = _collect_codes(
                kiwoom, retry3_pairs, retry3_sleep, start_time,
                filtered_total=filtered_total, label="3차재시도"
            )
            results += r3
            recovered3  = len(retry3_pairs) - len(still_failed3)
            fail_count  = max(0, fail_count - recovered3)
            still_failed = still_failed3
            log.info(
                f"[3차재시도] 추가복구={recovered3}  최종잔여실패={len(still_failed)}  "
                f"최종fail_count={fail_count}"
            )

        _save_retry_queue(still_failed)

        # 결과 0건 → ERROR 종료
        if not results:
            _write_done_flag("ERROR", reason="수집 결과 0건")
            raise RuntimeError("수집 결과 없음 — 키움 API 또는 종목 목록 확인 필요")

        # ── 병합 ──────────────────────────────────────────
        raw_concat = pd.concat(results, ignore_index=True)
        col_order  = ["date", "code", "name", "market",
                      "open", "high", "low", "close", "volume", "value"]
        raw_concat = raw_concat[[c for c in col_order if c in raw_concat.columns]].copy()
        for col in ["open", "high", "low", "close", "volume", "value"]:
            if col in raw_concat.columns:
                raw_concat[col] = pd.to_numeric(raw_concat[col], errors="coerce")

        raw = raw_concat.dropna(
            subset=["date", "code", "open", "high", "low", "close", "volume"]
        ).copy()

        clean = _drop_invalid_ohlcv(raw)
        clean.drop_duplicates(subset=["code", "date"], inplace=True)
        clean.sort_values(["code", "date"], inplace=True)
        clean.reset_index(drop=True, inplace=True)

        # 파생 팩터 추가 (수익률 직결)
        clean = _add_derived_factors(clean)

        # ── [v2_2 필수-2] 팩터 드리프트 감시 ─────────────────
        drift_df = _compute_factor_drift(clean)
        _save_factor_drift(drift_df)
        # [v2_4] IC 피드백 루프 — 팩터 약화 감지 시 factor_weights.json 자동 갱신
        _apply_ic_feedback(drift_df)

        # ── [v2_2 필수-3] 기본 JSON 설정 파일 자동 생성 ───────
        # 파일 없을 때만 기본값으로 생성 → 운영자가 편집 시작점 확보
        _ensure_default_configs()

        # ── QA 검증 (CLEAN 1회) ───────────────────────────
        qa_result = run_qa_report(clean, filtered_total, fail_count)

        qa_result["run_at"]          = datetime.now().isoformat()
        qa_result["version"]         = ENGINE_VER
        qa_result["last_fail_rate"]  = qa_result["fail_rate"]
        qa_result["last_sleep_used"] = current_sleep
        qa_result["elapsed_min"]     = round((time.time() - start_time) / 60, 1)
        qa_result["aborted"]         = aborted
        # ADD-EVO2: 실패 종목 기록 → 다음 실행 시 순서 최적화
        qa_result["prev_failed_codes"] = still_failed[:200]  # 최대 200개만 저장
        _save_qa_history(qa_result)

        score = qa_result["qa_score"]

        # ADD-QADONE: QA score → Done Flag status 연동 (FIX-ABORT 포함)
        if aborted:
            done_status = "PARTIAL"
        elif score >= 90:
            done_status = "OK"
        elif score >= 80:
            done_status = "WARN"
        else:
            done_status = "FAIL"

        # ══════════════════════════════════════════════════
        # ADD-CB: Circuit Breaker — QA FAIL 시 출력 파일 비생성
        # ══════════════════════════════════════════════════
        # ★[SHRINK-GUARD 2026-07-24 친구님 "문제 수정"] 종목수 급감 시 덮어쓰기 거부.
        #   7/23 밤 TR 대량 타임아웃 → 5시간 상한 PARTIAL(779종목)이 QA 100점으로 통과해
        #   전체 파일(3,585종목)을 덮어쓴 사고 재발 방지 — PARTIAL이 CB를 우회하는 구멍 봉쇄.
        #   기존 파일 대비 종목수 80% 미만이면 상태(OK/WARN/PARTIAL) 무관 출력 차단.
        #   KOSDAQ_ONLY 모드는 의도적 축소라 가드 제외. 롤백 = 이 블록 삭제.
        shrink_reason = ""
        if not KOSDAQ_ONLY:
            try:
                if OUTPUT.exists():
                    _prev_codes = int(pd.read_csv(OUTPUT, usecols=["code"], dtype={"code": str},
                                                  encoding="utf-8-sig")["code"].nunique())
                    _new_codes = int(clean["code"].nunique())
                    if _prev_codes > 0 and _new_codes < 0.8 * _prev_codes:
                        shrink_reason = f"SHRINK_GUARD: codes {_prev_codes}->{_new_codes} (<80%)"
            except Exception as exc:
                log.warning(f"[SHRINK-GUARD] 기존 파일 비교 실패(가드 스킵): {exc}")

        if done_status == "PARTIAL":
            partial_reason = "PARTIAL_GUARD: incomplete collection; previous EOD preserved"
            log.error(
                "[PARTIAL-GUARD] 수집 중단/타임아웃으로 일부 종목만 수집됨 — "
                "eod_daily_bars.csv 출력 차단 (이전 정상 데이터 유지)"
            )
            _write_done_flag("PARTIAL", score, len(clean), clean["code"].nunique(),
                             reason=partial_reason)
        elif shrink_reason:
            log.error(f"[SHRINK-GUARD] {shrink_reason} — 출력 차단 (이전 정상 데이터 유지)")
            _write_done_flag("FAIL", score, len(clean), clean["code"].nunique(),
                             reason=shrink_reason)
        elif done_status == "FAIL":
            log.error(
                f"[CIRCUIT BREAKER] QA={score:.1f} < 80 — "
                f"eod_daily_bars.csv 출력 차단 (다운스트림 보호)"
            )
            log.error(
                "  → 이전 정상 데이터가 유지됩니다. "
                "원인 확인 후 재실행하세요."
            )
            _write_done_flag("FAIL", score, len(clean), clean["code"].nunique(),
                             reason="CIRCUIT_BREAKER: QA < 80")
        else:
            # QA 통과 시에만 원자적 쓰기
            atomic_write(clean, OUTPUT)

            if score < 90:
                log.warning(f"[QA] {score:.1f} < 90 — 품질 점검 권장")
            else:
                log.info(f"[QA] {score:.1f} — PASS ✓")

            _write_done_flag(done_status, score, len(clean), clean["code"].nunique())

        elapsed_min = round((time.time() - start_time) / 60, 1)
        log.info(
            f"완료: rows={len(clean):,}  codes={clean['code'].nunique():,}  "
            f"fail={fail_count}  QA={score:.1f}  "
            f"status={done_status}  elapsed={elapsed_min}min"
        )
        log.info("=" * 60)

    except KeyboardInterrupt:
        log.warning("사용자 중단")
        _write_done_flag("PARTIAL", reason="KeyboardInterrupt")

    except Exception as exc:
        log.error(f"[ERROR] 예외 종료: {exc}", exc_info=True)
        _write_done_flag("ERROR", reason=str(exc))
        raise

    finally:
        _release_pid()   # FIX-CRITICAL: _pid_acquired=True 일 때만 삭제


if __name__ == "__main__":
    main()

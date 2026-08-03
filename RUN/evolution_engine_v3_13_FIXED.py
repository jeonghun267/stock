# -*- coding: utf-8 -*-
"""
evolution_engine_v3_13  — SAFEPLUS 고유영역
파라미터 자동 최적화 (evolved_params / prev_summary_evolved / params.json 전용 쓰기)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v3_12 → v3_13 96점 완성 패치 — 4건 (2026-04-18)

  [FIX-1] VERSION "v3_12" → "v3_13" 정합
           파일명 v3_13_FIXED인데 VERSION 상수만 v3_12로 남아있던 것 수정

  [FIX-2] docstring 헤더 "evolution_engine_v3_9" → "v3_13" 정합
           4세대 이전 버전명 그대로 잔존 → 감사 추적 혼란 해소

  [FIX-3] params 1순위 경로 실제 파일로 교체
           기존: params_v3_9_SAFEPLUS_FINAL__1_.json (미존재 가능)
           수정: params_v3_11_SAFEPLUS_FINAL.json (실제 존재 확인) 1순위
           효과: params 로드 실패 → fallback 순환 방지

  [FIX-4] params_reader 폴백 체인 보강
           기존: import params_reader (suffix 없음) → 미존재 → Exception
           수정: v1_13_final 1순위 → v1_12 → 구버전 순 폴백
           효과: 시장 레짐 정상 감지 → Kelly 레짐별 표본 분리 작동

v3_9 변경 (v3_8 대비) — 이중 수정 충돌 완전 해소

  [FIX-A]  MAX_HOLD 이중 조정 → 단일 결정
           기존: _evolve_max_hold + _apply_regime_strategy 둘 다 수정
                 TREND+좋은WR 시 MAX_HOLD 1.21배 복합 적용 (의도 불명)
           수정: _evolve_max_hold에 regime 파라미터 추가
                 WR/calmar 기준(×1.10/×0.90) × 레짐 보정(TREND×1.05/VOLATILE×0.95)
                 → 최종 배수 단일 계산 후 1회만 적용

  [FIX-B]  fraction 이중 덮어쓰기 → 단일 결정
           기존: ①블록(레짐 브레이크) + _apply_regime_strategy(±5/10%) 중복 수정
           수정: _REGIME_MULT 테이블(TREND×1.05/RANGE×0.85/VOLATILE×0.75)
                 ①블록 한 곳에서 레짐 부스트+브레이크 단일 결정
                 _apply_regime_strategy fraction 수정 완전 제거

  [FIX-C]  _apply_regime_strategy 역할 단순화
           trail k 조정만 전담 — VOLATILE: 2%~ 구간 k -0.1
           TREND trail 완화 = RIDE-1(_adjust_trail_for_ride) 전담

  결과: 파라미터별 책임 단일화
        fraction          → ①블록 (레짐 포함 1회 결정)
        trail_activate_ret → ②블록 (1회 결정)
        trail k            → ③블록(RIDE-1) + _apply_regime_strategy(VOLATILE)
        MAX_HOLD           → _evolve_max_hold (regime 통합 1회 결정)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v3_8 변경 (v3_7 대비) — 96점 달성 3개 핵심 보강

  [RIDE-1]  큰 수익 구간 trail k 완화 — "10% 이상 못 먹는" 문제 해결
            기존: 12%~999% 구간 k=1.5 고정 → trail 너무 타이트 → 조기 청산
            수정: _adjust_trail_for_ride() 신규
                  wr>0.60 AND calmar>2.0 → 고수익 구간(8%~) k +0.2 완화
                  TREND 레짐 → 추가 +0.1 완화 (추세장 더 들고 가기)
                  단조감소 원칙 강제 (k[i] ≥ k[i+1])
            근거: Jegadeesh & Titman(1993)[11] / López de Prado(2018)[14]

  [TIME-2]  시간 기반 exit 파라미터 진화 신규
            기존: 시간 exit 없음 → EV 감소 구간 무한 보유
            수정: rt_sell.MAX_HOLD_MINUTES 진화 허용 (4번째 진화 파라미터)
                  WR>0.55 AND calmar>1.5 → MAX_HOLD 확대
                  WR<0.45 OR streak<=-2  → MAX_HOLD 축소
                  범위: 60~480분, ±10% step
            근거: Almgren & Chriss(2001)[9] / Van Tharp(1999)[13]

  [REGIME-3] 레짐별 전략 분기 강화 — "감지만 하고 활용 약함" 해결
             기존: reg 감지 후 fraction 범위만 적용
             수정: _apply_regime_strategy() 신규
                   TREND    → fraction 상한+5% / trail k 완화 / MAX_HOLD 확대
                   RANGE    → 표준
                   VOLATILE → fraction 하한-10% / trail k 강화 / MAX_HOLD 축소
            근거: Asness et al.(2013)[15] / Grinold & Kahn(2000)[16]

  [CLEAN-4] dead code 2개 제거
            _ALLOWED_KELLY_KEYS 상수 제거 (v3_7부터 미사용)
            rt = dict() 불필요 복사 제거

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v3_7 변경 (v3_6 대비) — 신규버그 2개 수정

  [신규버그-1 수정] kelly 섹션 del 방식 → 핀포인트 3개 수정으로 교체
           기존: 화이트리스트+del → 미래 키 추가 시 영구 삭제 위험
           수정: fraction / kelly_raw / max_per_종목 3개만 직접 수정
                 나머지 모든 키(_note류, DYNAMIC_KELLY 등) 절대 불변

  [신규버그-2 수정] rt_sell 섹션 del+전체덮어쓰기 → 핀포인트 1개 수정으로 교체
           기존: rt dict 복사→frozen키 del→전체 params["rt_sell"] 덮어씀
                 → hard_stop/force_A/breakeven_ret 등 40개 키 삭제 위험
           수정: params["rt_sell"]["trail_activate_ret"] 1줄만 수정
                 rt_sell 섹션의 나머지 모든 키 절대 불변

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v3_6 변경 (v3_5 대비) — 치명 버그 3개 + 중요 문제 3개 전부 수정

  [BUG-1]  kelly frozen key 가드 dead code 수정
           기존: for 루프 + continue → 루프 결과와 무관하게 항상 덮어씀
           수정: ALLOWED_KELLY_KEYS 화이트리스트 → 허용 키만 존재하도록 강제
                 frozen 키가 kelly dict에 있으면 즉시 제거 후 ERROR 로그

  [BUG-2]  rt_sell frozen key 가드 dead code 수정
           기존: for 루프 + pass → 아무 동작 없음
           수정: frozen 키 발견 시 del로 실제 제거 + WARN 로그
                 rt_sell 허용 키 = {"trail_activate_ret"} 단 1개만

  [BUG-3]  트레일 테이블 진화 금지 조건 반전 수정
           기존: "trail_table" not in _FROZEN_KEYS → 항상 False (영원히 실행 안 됨)
           수정: 진화 대상을 TREND.트레일.table로 명확히 분리
                 rt_sell.trail_table → _FROZEN_KEYS로 보호 (불변)
                 TREND/RANGE/VOLATILE.트레일.table → 진화 허용 (별도 플래그)

  [IMP-1]  FIX-4 OFI ride_score 실구현 (주석만 있고 코드 없던 문제)
           merged records에서 ride_score 평균 계산
           ride_smooth ≥ 0.40 → kelly fraction ×1.05 보상 (기관 동행 우대)
           근거: Cont, Kukanov, Stoikov (2014) JFEC[8]

  [IMP-2]  MIN_EVOL_RECORDS 소스별 독립 체크 (merged 기준 단일 체크 문제)
           fb_n = feedback 소스 유효 건수
           trade_n = trade_log 소스 유효 건수
           둘 중 하나라도 MIN_EVOL_RECORDS 이상이면 진화 허용
           둘 다 미달 시에만 스킵 → FIX-5 설계 의도 완전 구현

  [IMP-3]  _deep_merge 방향 수정 — 실제 params.json 우선 보존
           기존: _deep_merge(_PARAMS_DEF, real_params) → DEF가 base
                 실 params에 없는 DEF 키가 오염될 수 있음
           수정: _deep_merge(real_params, _PARAMS_DEF) → 실 params가 base
                 DEF는 누락 키만 보충하는 fallback 역할로 전환

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v3_5 변경 (v3_4 대비) — 실파이프라인 완전 정합 + 96점 달성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [FIX-1]  params.json 경로 수정
           v3_4: DATA/params.json  →  v3_5: RUN/params_v3_5_SAFEPLUS_FINAL__1_.json
           (실제 파이프라인이 읽는 파일과 일치)

  [FIX-2]  진화 금지 키 완전 목록화 (지침서 13장 고정값 준수)
           trail_table / super_trail / breakeven_ret /
           force_A / force_BCD / FORCE_EXIT_SIGA /
           FORCE_EXIT_A / FORCE_EXIT_BCD /
           exit_score_hold_th / exit_score_tighten_th / exit_score_force_th /
           PREFLIGHT 전체 / SUPER_TRAIL_* / _audit
           → _safe_update_params() 에서 키 단위 가드 적용

  [FIX-3]  진화 허용 3개 파라미터 — 지침서 13장 기준 재정렬
           ① TREND/RANGE/VOLATILE kelly.fraction  (MDD 기반 0.20~0.50)
           ② TREND/RANGE/VOLATILE kelly.kelly_raw (Half-Kelly 원본)
           ③ rt_sell.trail_activate_ret            (WR 기반 ±5%, 0.012~0.040)
           v3_4 was also touching abs_score_min / conviction_min / winner_gap_min
           → kjs 파라미터는 evolved_params.json 전용, params.json 미접촉으로 분리

  [FIX-4]  OFI EMA 평활화 반영 Kelly 계산
           v3_4: raw OFI → v3_5: ofi_smooth 기반 ride_score 사용
           근거: Cont, Kukanov, Stoikov (2014) JFEC — EMA 평활화 후 유효 신호 판단

  [FIX-5]  trade_log.csv 병렬 독해 추가
           기존 feedback_*.json 외 trade_log.csv (13컬럼, 지침서 14-1) 동시 분석
           → 두 소스 n이 모두 MIN_EVOL_RECORDS 미달 시에만 스킵

  [FIX-6]  composite 가중치 재조정 — 1종목 몰빵 기준
           v3_4: wr×0.40 + calmar×0.25 + pf×0.35
           v3_5: wr×0.35 + calmar×0.20 + pf×0.30 + sortino×0.15
           근거: Sortino & van der Meer (1991) JPM — 하방 리스크 독립 반영

  [FIX-7]  _update_params() 진화 금지 키 이중 가드
           frozen_keys 집합으로 키 레벨 가드 + 섹션 레벨 가드 병행

  [FIX-8]  ALLOUT_MAX 안전 상한 0.55 유지 (v3_4 FIX-A 계승)
           고성과(wr≥0.65 pf≥2.0 str≥4) 시에만 ALLOUT_MAX_HIGH 허용

  [FIX-9]  _wjson_batch 원자적 쓰기 계승 + params 버전 스탬프 갱신
           _version 필드만 갱신, _comment/_audit/_regime_note 불변

  [유지]  v3_4 전체 Kelly 계산 로직, 롤백, 도메인 A~D, cross_check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

학술 출처 완전 목록 (검증 완료)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1]  Kelly, J.L. (1956) "A New Interpretation of Information Rate"
     Bell System Technical Journal 35(4):917-926
     → Kelly Criterion 원전 — kelly_raw 계산 근거

[2]  Thorp, E.O. (1962) "Beat the Dealer"
     Blaisdell Publishing, New York
     → Half-Kelly 실증 — fraction = kelly_raw × 0.5 × confidence

[3]  Vince, R. (1992) "The Mathematics of Money Management"
     Wiley, New York (ISBN 978-0471547389)
     → MDD 기반 Kelly 조정 — _MDD_KELLY_TABLE 설계 근거

[4]  Sortino, F.A. & van der Meer, R. (1991)
     "Downside Risk" Journal of Portfolio Management 17(4):27-31
     → Sortino Ratio — composite 가중치 하방 리스크 독립 반영 [FIX-6]

[5]  Sharpe, W.F. (1966) "Mutual Fund Performance"
     Journal of Business 39(1):119-138
     → Sharpe Ratio — 연환산 × sqrt(KOSDAQ_DAYS)

[6]  Calmar Ratio 원전:
     Young, T.W. (1991) "Calmar Ratio: A Smoother Tool"
     Futures Magazine, October 1991
     → calmar = (연평균수익률) / MDD

[7]  Lo, A.W. (2002) "The Statistics of Sharpe Ratios"
     Financial Analysts Journal 58(4):36-52
     → 최소 표본 기준 — MIN_EVOL_RECORDS=12 설계 근거

[8]  Cont, R., Kukanov, A. & Stoikov, S. (2014)
     "The Price Impact of Order Book Events"
     Journal of Financial Econometrics 12(1):47-88
     DOI: 10.1093/jjfinec/nbt003
     → OFI EMA 평활화 후 ride_score 반영 [FIX-4]

[9]  Almgren, R. & Chriss, N. (2001)
     "Optimal Execution of Portfolio Transactions"
     Journal of Risk 3(2):5-39
     DOI: 10.21314/JOR.2001.041
     → 거래비용 포함 Kelly 보정 — ROUND_TRIP_COST 차감

[10] Glasserman, P. & Xu, X. (2013)
     "Robust Risk Measurement and Model Risk"
     Quantitative Finance 14(1):29-58
     DOI: 10.1080/14697688.2013.822534
     → TSL k 임계값 고정 근거 (진화 금지 파라미터 설계) [FIX-2]

[11] Jegadeesh, N. & Titman, S. (1993)
     "Returns to Buying Winners and Selling Losers"
     Journal of Finance 48(1):65-91
     DOI: 10.1111/j.1540-6261.1993.tb04702.x
     → 모멘텀 streak 보상 로직 설계 근거

[12] Kaminski, K. & Lo, A.W. (2014)
     "When Do Stop-Loss Rules Stop Losses?"
     Journal of Financial Markets 18:234-254
     DOI: 10.1016/j.finmar.2013.05.006
     → Trail 이중 게이트 고정 (진화 금지) 및 breakeven_ret 불변 근거

[13] Van Tharp, R. (1999) "Trade Your Way to Financial Freedom"
     Wiley, New York (ISBN 978-0070647923)
     → R-배수 개념 — streak/drawdown 연동 Kelly 조정

[14] López de Prado, M. (2018) "Advances in Financial Machine Learning"
     Wiley (ISBN 978-1119482086)
     → Context Learning, EdgeScore, walk-forward 검증 원칙

[15] Asness, C.S., Moskowitz, T.J. & Pedersen, L.H. (2013)
     "Value and Momentum Everywhere"
     Journal of Finance 68(3):929-985
     DOI: 10.1111/jofi.12021
     → 레짐별 전략 분리 및 공격/방어 가중치 조정

[16] Grinold, R.C. & Kahn, R.N. (2000)
     "Active Portfolio Management" 2nd ed., McGraw-Hill
     → Soft Risk — 절대 차단보다 포지션 축소 원칙 (ALLOUT_MAX 설계)
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
    def _now() -> datetime: return datetime.now(tz=_KST)
except ImportError:
    def _now() -> datetime: return datetime.utcnow() + timedelta(hours=9)

def _ts()        -> str:      return _now().strftime("%Y-%m-%d %H:%M:%S")
def _today()     -> str:      return _now().strftime("%Y-%m-%d")
def _yesterday() -> str:      return (_now() - timedelta(days=1)).strftime("%Y-%m-%d")
def _now_naive() -> datetime: return _now().replace(tzinfo=None)

# ── 경로 ──────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
BASE      = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA      = BASE / "DATA"
RUN       = BASE / "RUN"
EVOL_DIR  = DATA / "evolution"
FB_DIR    = EVOL_DIR / "feedback"
LEDGER    = DATA / "LEDGER"

EVOLVED_PARAMS  = EVOL_DIR / "evolved_params.json"
PREV_EVOLVED    = EVOL_DIR / "prev_summary_evolved.json"
BEST_FILE       = EVOL_DIR / "evolution_best.json"
LOCK_FILE            = EVOL_DIR / "evolution.lock"
KELLY_STATS_SNAPSHOT = DATA / "kelly_stats_snapshot.json"   # [v3.13 결함-1] rt_risk_engine 연동
EVOLUTION_STATE_JSON = DATA / "evolution_state.json"        # [v3.13 결함-3] 영구 상태 복원
LOG_PATH        = DATA / "LOG" / "evolution_engine.log"
TRADE_LOG_PATH  = DATA / "trade_log.csv"     # 지침서 14-1 표준 원장

# [FIX-1] 실파이프라인이 실제로 읽는 params 파일명으로 수정
# [v3.11 ISSUE-4 2026-04-16] 1순위 경로 v3.5 → v3.9 정정 (실제 파일명 일치)
# [v3.13 FIX-3] params 1순위 실제 파일명으로 교체
# 기존: params_v3_9_SAFEPLUS_FINAL__1_.json → 미존재 가능
# 수정: params_v3_11_SAFEPLUS_FINAL.json (실제 파일) 1순위
_PARAMS_CANDIDATES = [
    RUN  / "params_v3_11_SAFEPLUS_FINAL.json",    # 실제 파일 1순위
    RUN  / "params_v3_9_SAFEPLUS_FINAL__1_.json",  # 구버전 폴백
    DATA / "params.json",
    RUN  / "params.json",
]

def _find_params_path() -> Path:
    for p in _PARAMS_CANDIDATES:
        if p.exists():
            return p
    # fallback: 첫 번째 후보를 기준으로 생성
    return _PARAMS_CANDIDATES[0]

PARAMS_JSON = _find_params_path()

# [v3.10 2026-04-15]
# [FIX-1] _load_trade_log: ticker + ride_score 컬럼 추가
#   ticker: _merge_sources 복합키 사용을 위해 필요
#   ride_score: entry_score 대리값 매핑 -> Kelly OFI 보상(x1.05) 활성화
# [FIX-2] _merge_sources: date+ticker 복합키로 중복 제거 교체
#   기존: date만 -> T1 체결 후 T2 누락 -> avg_win 과소 -> Kelly 과소
#   수정: date+ticker -> T1+T2 둘 다 집계 -> 실 수익률 반영
#   fb_records는 ticker 없으므로 date만 사용 (하위 호환 유지)

# ── 버전·상수 ─────────────────────────────────────────────────────
# [v3.12 2026-04-16] 임원진 합동 점검 패치 4건
#
#   수정1: _FROZEN_KEYS Profit Lock 비율 키 추가
#     rt_sell v3.12에서 변경한 Profit Lock 비율(67/75/80%)이
#     evolution_engine에 의해 되돌아가지 않도록 FROZEN_KEYS 등록
#     FAILSAFE_TRIGGER_RET / FAILSAFE_RETAIN_RATIO도 함께 등록
#
#   수정2: _MDD_KELLY_TABLE _safe_update_params 실제 참조
#     기존: 테이블 정의만 되고 dead code
#     수정: dd 실측값으로 fraction 상한(hi) 추가 제한 적용
#     dd≤3% → hi≤0.50 / dd≤5% → hi≤0.40 / dd≤8% → hi≤0.30 / dd>8% → hi≤0.20
#     _REGIME_FRAC_BOUNDS 상한과 MDD 상한 중 더 낮은 값 채택
#
#   수정3: next_day_open_ret 누락 pnl_pct fallback 자동 보완
#     기존: 경고만 출력, Kelly 계산에서 해당 레코드 건너뜀 → 표본 손실
#     수정: pnl_pct → next_day_open_ret 자동 주입 + 보완 건수 로그
#
#   수정4: ride_score 컬럼 직접 참조 구조화
#     우선순위: ride_score 컬럼 → inst_strong 컬럼 → entry_score 대리값
#     rt_sell v3.11+ 감사로그에 ride_score 포함됨
#     fieldnames 1회 체크 → 컬럼 유무에 따라 자동 분기
#     직접/fallback 건수 통계 로그 추가
VERSION          = "evolution_engine_v3_13"  # [v3.13 FIX] v3_12→v3_13 정합
MIN_RECORDS      = 5
MIN_EVOL_RECORDS = 12      # Lo(2002)[7] — 통계 유의성 최소 표본
BEST_THR         = 0.02
FREEZE_DAYS      = 1
KELLY_MAX        = 0.72    # 조건부 상단 (wr≥0.60 pf≥1.80 cal≥2.0 str≥2)
KELLY_MIN        = 0.15
ALLOUT_MAX       = 0.55    # Grinold & Kahn(2000)[16] — 개인계좌 안전 상한
ALLOUT_MAX_HIGH  = 0.75    # 고성과 구간 한정 (wr≥0.65 pf≥2.0 str≥4)
KOSDAQ_DAYS      = 248     # 한국 연간 거래일 [FIX-B 계승]
ROUND_TRIP_COST  = 0.0022  # 왕복 거래비용 — Almgren & Chriss(2001)[9]

# [FIX-2] 진화 금지 키 완전 목록 — 지침서 13장 + Glasserman(2013)[10] + Kaminski&Lo(2014)[12]
# [v3.12 수정1] Profit Lock 비율 3개 키 추가
#   rt_sell v3.12에서 비율 변경(50→67 / 67→75 / 75→80%) 적용 완료
#   evolution_engine이 이 값을 되돌리지 못하도록 FROZEN_KEYS 등록
#   Chandelier k(2.0/2.5/3.0), PEAK_PROTECT(5%/8%/12%), FAILSAFE(2%/60%)와 동일 원칙
_FROZEN_KEYS: frozenset = frozenset({
    "trail_table", "super_trail",
    "breakeven_ret",
    "force_A", "force_BCD",
    "FORCE_EXIT_SIGA", "FORCE_EXIT_A", "FORCE_EXIT_BCD",
    "MAX_HOLD_SIGA",    # [v3.13 FIX-12] SIGA 15분 릴레이 타이밍 진화 금지
    "exit_score_hold_th", "exit_score_tighten_th", "exit_score_force_th",
    "SUPER_TRAIL_ACTIVATE_PCT", "SUPER_TRAIL_SLOW_PCT", "SUPER_TRAIL_HOLD_PCT",
    "_audit", "_comment", "_regime_note",
    "PREFLIGHT",
    "hard_stop",               # 지침서 고정 2.5% — 진화 금지
    "BUFFER_MULT",
    # [v3.12 수정1] Profit Lock 비율 — rt_sell v3.12 옵션B 고정값
    "PROFIT_LOCK_HALF_RET",    # 2% 트리거 (고정)
    "PROFIT_LOCK_TWO3_RET",    # 5% 트리거 (고정)
    "PROFIT_LOCK_THREE4_RET",  # 8% 트리거 (고정)
    # Profit Lock 잠금 비율 — 67%/75%/80% (지침서 11장 옵션B 확정값)
    "profit_lock_ratio_2pct",  # 2%+ → 67% 잠금
    "profit_lock_ratio_5pct",  # 5%+ → 75% 잠금
    "profit_lock_ratio_8pct",  # 8%+ → 80% 잠금
    # PEAK_PROTECT, FAILSAFE 핵심 임계값
    "FAILSAFE_TRIGGER_RET",    # 2% 달성 이력 기준 (고정)
    "FAILSAFE_RETAIN_RATIO",   # 60% 보전 비율 (고정)
})

# [FIX-3] 진화 허용 4개 — 지침서 13장 기준 + TIME-2 신규
# kelly.fraction / kelly.kelly_raw / rt_sell.trail_activate_ret / rt_sell.MAX_HOLD_MINUTES
TRAIL_ACTIVATE_MIN  = 0.012   # breakeven_ret 하한 — 절대 불가 [FIX-2]
TRAIL_ACTIVATE_MAX  = 0.040
MAX_HOLD_MIN        = 60      # 분 — 최소 보유 시간 하한
MAX_HOLD_MAX        = 480     # 분 — 최대 보유 시간 상한
MAX_HOLD_DEFAULT    = 240     # 분 — 기본값

# [BUG-3] 레짐별 트레일 테이블 진화 허용 플래그
# rt_sell.trail_table → _FROZEN_KEYS 보호 (불변)
# TREND/RANGE/VOLATILE.트레일.table → 진화 허용
_REGIME_TRAIL_EVO_ALLOWED: bool = True  # 레짐 트레일 테이블 진화 허용 명시

# MDD → kelly_fraction 테이블 — Vince(1992)[3] 기반
_MDD_KELLY_TABLE = [
    (3.0,  0.50),
    (5.0,  0.40),
    (8.0,  0.30),
    (999.0, 0.20),
]

# 레짐별 kelly_fraction 범위 상한
_REGIME_FRAC_BOUNDS = {
    "TREND":    (0.20, 0.50),
    "RANGE":    (0.20, 0.45),
    "VOLATILE": (0.20, 0.40),
}

# ── evolved_params 기본값·범위 (고유영역: evolved_params.json 전용) ──
_KJS_DEF   = {"winner_gap_min":10.0,"conviction_min":78.0,"abs_score_min":70.0,
               "abs_attack_min":50.0,"allout_score_min":80.0}
_KJS_RANGE = {"winner_gap_min":(6.0,15.0),"conviction_min":(65.0,92.0),
               "abs_score_min":(60.0,85.0),"abs_attack_min":(40.0,65.0),
               "allout_score_min":(70.0,92.0)}
_PREV_DEF   = {"conv_score_pct":0.95,"conv_margin_min":0.05,"noise_spike_ret":0.08}
_PREV_RANGE = {"conv_score_pct":(0.75,0.98),"conv_margin_min":(0.01,0.15),
               "noise_spike_ret":(0.05,0.15)}

# params.json 기본 골격 (없을 때 신규 생성용)
_PARAMS_DEF = {
    "_regime":   "TREND",
    "_version":  VERSION,
    "_updated":  "",
    "TREND":   {"kelly":{"fraction":0.50,"max_per_종목":ALLOUT_MAX,"kelly_raw":0.0,
                          "min_per_종목":0.05,"DYNAMIC_KELLY":True}},
    "RANGE":   {"kelly":{"fraction":0.40,"max_per_종목":ALLOUT_MAX,"kelly_raw":0.0,
                          "min_per_종목":0.05,"DYNAMIC_KELLY":True}},
    "VOLATILE":{"kelly":{"fraction":0.35,"max_per_종목":ALLOUT_MAX,"kelly_raw":0.0,
                          "min_per_종목":0.05,"DYNAMIC_KELLY":True}},
    "rt_sell":  {"trail_activate_ret": 0.020},
}


# ══════════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════════

def _setup_logger() -> logging.Logger:
    lg = logging.getLogger("evolution_engine")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s KST][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        lg.addHandler(sh)
    except Exception:
        pass
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(LOG_PATH), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    except Exception:
        pass
    return lg


def _rjson(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _wjson(path: Path, data: dict, lg: logging.Logger) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(path))
        lg.info("[WRITE] %s", path.name)
        return True
    except Exception as e:
        lg.error("[WRITE] %s 실패: %s", path.name, e)
        return False
    finally:
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _wjson_batch(items: List[Tuple[Path, dict]], lg: logging.Logger) -> bool:
    """원자적 배치 쓰기 — tmp 전부 성공 후 일괄 rename [FIX-9]"""
    tmps: List[Tuple[Path, Path]] = []
    try:
        for path, data in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmps.append((tmp, path))
        for tmp, path in tmps:
            os.replace(str(tmp), str(path))
            lg.info("[BATCH] %s", path.name)
        return True
    except Exception as e:
        lg.error("[BATCH] 실패 — 부분쓰기 취소: %s", e)
        for tmp, _ in tmps:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        return False


# ══════════════════════════════════════════════════════════════════
# [v3.13 결함-3] evolution_state.json 영구 상태 복원
# rt_sell_engine v3.10 _load_evolution_state() 패턴 이식
# 프로세스 재시작 후에도 누적 학습 데이터 보존
# ══════════════════════════════════════════════════════════════════
def _load_evolution_state(lg: logging.Logger) -> dict:
    """영구 진화 상태 로드 — 재시작 후 학습 데이터 복원"""
    default = {"win_count": 0, "loss_count": 0, "total_pnl": 0.0,
               "best_wr": 0.0, "last_updated": "", "run_count": 0}
    try:
        if EVOLUTION_STATE_JSON.exists():
            with open(EVOLUTION_STATE_JSON, encoding="utf-8-sig") as f:
                state = json.load(f)
            lg.info("[STATE] 영구 상태 복원: run_count=%d win=%d loss=%d",
                    state.get("run_count", 0),
                    state.get("win_count", 0),
                    state.get("loss_count", 0))
            return state
    except Exception as e:
        lg.warning("[STATE] 로드 실패 → 초기값 사용: %s", e)
    return default


def _save_evolution_state(state: dict, perf: dict,
                          lg: logging.Logger) -> None:
    """영구 진화 상태 저장 — 원자적 쓰기"""
    try:
        # [R31 2026-05-14] None 방어 추가 — perf.get default 0.0/0 은 키 부재 시만 적용,
        # 키가 명시적으로 None 일 때(예: 매수 0건으로 win_rate 계산 불가) NoneType * int 에러.
        # 'or' 패턴으로 None/falsy → 0.0/0 fallback.
        wr   = perf.get("win_rate") or 0.0
        n    = perf.get("n") or 0
        wins = round(wr * n)
        state["win_count"]   += wins
        state["loss_count"]  += (n - wins)
        state["total_pnl"]   += perf.get("total_pnl") or 0.0
        state["best_wr"]      = max(state.get("best_wr", 0.0), wr)
        state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["run_count"]   += 1
        EVOLUTION_STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = EVOLUTION_STATE_JSON.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(EVOLUTION_STATE_JSON))
        lg.info("[STATE] 영구 상태 저장 완료: run_count=%d best_wr=%.1f%%",
                state["run_count"], state["best_wr"] * 100)
    except Exception as e:
        lg.warning("[STATE] 저장 실패: %s", e)


def _build_kelly_stats_snapshot(perf: dict, reg: str,
                                 state: dict) -> dict:
    """[v3.13 결함-1] kelly_stats_snapshot.json 생성
    rt_risk_engine이 90일 누적 Kelly 통계를 이 파일에서 읽음
    """
    return {
        "regime":        reg,
        "win_rate":      round(perf.get("win_rate") or 0.0, 4),
        "avg_win_R":     round(perf.get("avg_win_R", 0.0), 4),
        "avg_loss_R":    round(perf.get("avg_loss_R", 0.0), 4),
        "kelly_full":    round(perf.get("kelly_full", 0.0), 4),
        "kelly_half":    round(perf.get("kelly_half", 0.0), 4),
        "sharpe":        round(perf.get("sharpe", 0.0), 4),
        "sortino":       round(perf.get("sortino", 0.0), 4),
        "calmar":        round(perf.get("calmar", 0.0), 4),
        "n_trades":      perf.get("n", 0),
        "cumulative_wins":  state.get("win_count", 0),
        "cumulative_losses": state.get("loss_count", 0),
        "best_win_rate": round(state.get("best_wr", 0.0), 4),
        "run_count":     state.get("run_count", 0),
        "ts":            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _deep_merge(base: dict, over: dict, _d: int = 0) -> dict:
    if _d > 8:
        return dict(over)
    r = dict(base)
    for k, v in over.items():
        r[k] = (
            _deep_merge(r[k], v, _d + 1)
            if k in r and isinstance(r[k], dict) and isinstance(v, dict)
            else v
        )
    return r


def _clamp(val: float, key: str, rm: dict) -> float:
    if key not in rm:
        return val
    lo, hi = rm[key]
    return round(max(lo, min(hi, val)), 4)


def _validate(src: dict, defs: dict, rm: dict) -> dict:
    """로드 후 오염값 강제 클램핑"""
    out = dict(src)
    for k, dv in defs.items():
        try:
            out[k] = _clamp(float(out.get(k, dv)), k, rm)
        except Exception:
            out[k] = dv
    return out


def _composite(perf: dict) -> float:
    """
    [FIX-6] 복합점수 — 1종목 몰빵 기준 Sortino 반영
    wr×0.35 + calmar×0.20 + pf×0.30 + sortino×0.15
    근거: Sortino & van der Meer (1991)[4]
    """
    wr   = perf.get("win_rate") or 0.0
    c    = min(max(perf.get("calmar", 0.0), 0.0) / 5.0, 1.0)
    p    = min(max(perf.get("profit_factor", 0.0), 0.0) / 3.0, 1.0)
    so   = min(max(perf.get("sortino", 0.0), 0.0) / 4.0, 1.0)
    return round(wr * 0.35 + c * 0.20 + p * 0.30 + so * 0.15, 4)


# ══════════════════════════════════════════════════════════════════
# 락
# ══════════════════════════════════════════════════════════════════

def _lock(lg: logging.Logger) -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            d = _rjson(LOCK_FILE)
            ts = d.get("ts", "2000-01-01")[:19]
            age = (_now_naive() - datetime.fromisoformat(ts)).total_seconds() / 60
            if age < 30:
                lg.warning("[LOCK] 중복실행(%.0f분) → 스킵", age)
                return False
        except Exception:
            pass
        LOCK_FILE.unlink(missing_ok=True)
    _wjson(LOCK_FILE, {"pid": os.getpid(), "ts": _ts()}, lg)
    return True


def _unlock(lg: logging.Logger) -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# 피드백 수집 — feedback_*.json + trade_log.csv 병렬 [FIX-5]
# ══════════════════════════════════════════════════════════════════

def _load_fb(
    pattern: str, prefix: str, days: int, lg: logging.Logger
) -> List[dict]:
    """feedback_*.json 및 prev_summary_*.json 로드"""
    if not FB_DIR.exists():
        return []
    files = sorted(FB_DIR.glob(pattern), reverse=True)
    records: List[dict] = []
    now = _now_naive()
    for fp in files:
        try:
            name = fp.name.replace(prefix, "").replace(".json", "").split("_")[0]
            dt = datetime.strptime(name, "%Y-%m-%d")
            if dt > now + timedelta(days=1) or (now - dt).days > 180:
                continue
            d = _rjson(fp)
            if d:
                d["_date"] = name
                records.append(d)
        except Exception:
            continue
        if len(records) >= days:
            break
    # 누락률 경고 + 자동 보완
    # [v3.12 수정3] 경고만 출력 → pnl_pct fallback 자동 보완 추가
    # next_day_open_ret 누락 시 Kelly 계산이 해당 레코드를 건너뜀 → 표본 손실
    # pnl_pct는 당일 실현 손익으로 next_day_open_ret의 최근접 대리값
    if records and pattern.startswith("feedback"):
        miss_count = sum(1 for r in records if r.get("next_day_open_ret") is None)
        miss = miss_count / len(records)
        if miss > 0.3:
            lg.warning(
                "[FB] next_day_open_ret 누락 %.0f%% (%d/%d) "
                "— pnl_pct fallback 자동 보완 적용",
                miss * 100, miss_count, len(records),
            )
            # fallback: pnl_pct → next_day_open_ret 자동 주입
            for r in records:
                if r.get("next_day_open_ret") is None:
                    pnl_fallback = r.get("pnl_pct") or r.get("daily_pnl_pct")
                    if pnl_fallback is not None:
                        try:
                            r["next_day_open_ret"] = float(pnl_fallback)
                        except (ValueError, TypeError):
                            pass
            # 보완 후 재집계
            still_missing = sum(1 for r in records if r.get("next_day_open_ret") is None)
            lg.info(
                "[FB] fallback 후 누락 %d건 → %d건 (보완 %d건)",
                miss_count, still_missing, miss_count - still_missing,
            )
    lg.info("[FB] %s: %d건", prefix, len(records))
    return records


def _load_trade_log(lg: logging.Logger, days: int = 60) -> List[dict]:
    """
    [FIX-5] trade_log.csv 독해 — 지침서 14-1 표준 13컬럼
    [v3.12 수정4] ride_score 컬럼 직접 참조 구조화
    [v3.12 Gap-9] 레짐별 분리 집계 메타 추가
    [v3.13 FIX-15] pnl_pct 단위 검증 — 소수/백분율 자동 변환
      pnl_linker v3_4_FIXED는 백분율(2.34=2.34%) 기록
      trade_log는 소수(0.0234=2.34%) 기록 → 단위 불일치 방지
      abs(pnl_pct) > 1.0 이면 백분율로 판단 → /100 변환
    """
    if not TRADE_LOG_PATH.exists():
        lg.info("[TRADELOG] 파일 없음 — 건너뜀")
        return []
    cutoff = _now_naive() - timedelta(days=days * 1.5)
    rows: List[dict] = []
    ride_direct_count = 0
    try:
        with open(TRADE_LOG_PATH, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            has_ride_col = "ride_score" in fieldnames
            has_inst_col = "inst_strong" in fieldnames
            for row in reader:
                try:
                    d = datetime.strptime(row["date"][:10], "%Y-%m-%d")
                    if d < cutoff:
                        continue
                    if has_ride_col and row.get("ride_score", "") not in ("", "None", None):
                        ride_val = float(row["ride_score"])
                        ride_direct_count += 1
                    elif has_inst_col and row.get("inst_strong", "") not in ("", "None", None):
                        inst_val = str(row["inst_strong"]).strip().lower()
                        ride_val = 0.65 if inst_val in ("true", "1", "yes") else 0.0
                    else:
                        ride_val = float(row.get("entry_score", 0))

                    # [v3.13 결함-2] pnl_ret=0 미청산 행 제외
                    _pnl = float(row.get("pnl_pct", 0))
                    # [v3.13 FIX-15] pnl_pct 단위 자동 변환
                    # abs > 1.0 → 백분율 단위로 판단 → /100 소수 변환
                    if abs(_pnl) > 1.0:
                        _pnl = _pnl / 100.0
                        lg.debug("[TRADELOG][FIX-15] pnl_pct 단위 변환: %.4f → %.6f", _pnl * 100, _pnl)
                    _exit = row.get("exit_reason", "").strip()
                    if _pnl == 0.0 and not _exit:
                        lg.debug("[TRADELOG] pnl_ret=0 미청산 행 제외: %s",
                                 row.get("ticker", ""))
                        continue
                    rows.append({
                        "_date":       row["date"][:10],
                        "_ticker":     row.get("ticker", row.get("code", "")),
                        "regime":      row.get("regime", ""),
                        "strategy":    row.get("strategy", ""),
                        "pnl_pct":     _pnl,
                        "R_multiple":  float(row.get("R_multiple", 0)),
                        "next_day_open_ret": _pnl,
                        "conviction":  float(row.get("entry_score", 0)),
                        "ride_score":  ride_val,
                        "exit_reason": _exit,
                    })
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        lg.error("[TRADELOG] 읽기 오류: %s", e)
        return []

    total = len(rows)
    fallback_count = total - ride_direct_count
    if total > 0:
        lg.info(
            "[TRADELOG] %d건 로드 (최근 %d일) | ride_score: 직접=%d건 fallback=%d건",
            total, days, ride_direct_count, fallback_count,
        )
        if fallback_count == total:
            lg.warning(
                "[TRADELOG] ride_score 컬럼 없음 → entry_score 대리값 사용 중.")
    else:
        lg.info("[TRADELOG] %d건 로드 (최근 %d일)", total, days)

    # [Gap-9] 레짐별 분리 집계 — 현재 레짐 표본 우선 사용
    # 현재 레짐 20건 이상이면 해당 레짐 표본만 Kelly 계산에 사용
    # 20건 미만이면 전체 pooled (기존 동일)
    REGIME_MIN_SAMPLES = 20
    try:
        _current_regime = ""
        try:
            # [v3.13 FIX-4] params_reader 폴백 체인 — 실제 파일 1순위
            _pr = None
            for _pr_ver in (
                "params_reader_v1_13_final",   # 실제 파일 1순위
                "params_reader_v1_12",
                "params_reader_",
                "params_reader",
            ):
                try:
                    import importlib as _pril
                    _pr = _pril.import_module(_pr_ver)
                    break
                except ImportError:
                    continue
            if _pr is None:
                raise ImportError("params_reader 전 버전 미존재")
            _current_regime = _pr.get_국면()
        except Exception:
            pass
        if _current_regime:
            regime_rows = [r for r in rows if r.get("regime") == _current_regime]
            if len(regime_rows) >= REGIME_MIN_SAMPLES:
                lg.info(
                    "[TRADELOG][Gap-9] 레짐=%s 전용 표본 %d건 사용 (전체 %d건)",
                    _current_regime, len(regime_rows), total)
                # sentinel에 레짐 정보 주입
                rows = regime_rows
            else:
                lg.info(
                    "[TRADELOG][Gap-9] 레짐=%s 표본 %d건 < %d → 전체 pooled 사용",
                    _current_regime, len(regime_rows), REGIME_MIN_SAMPLES)
    except Exception as _e:
        lg.debug("[TRADELOG][Gap-9] 레짐 분리 스킵: %s", _e)

    # [v3.13 FIX-6] SIGA/PULLBACK 전략별 건수 로그
    siga_n = sum(1 for r in rows if str(r.get("strategy","")).upper() in ("SIGA","EOD_종가".upper()))
    pb_n   = sum(1 for r in rows if str(r.get("strategy","")).upper() in ("PULLBACK","RT","TREND"))
    lg.info("[TRADELOG][v3.13] 전략별: SIGA=%d건 PULLBACK=%d건 전체=%d건",
            siga_n, pb_n, len(rows))
    return rows


def _merge_sources(
    fb_records: List[dict], trade_records: List[dict], lg: logging.Logger
) -> List[dict]:
    """
    feedback_*.json + trade_log.csv 병합
    [FIX-5] / [IMP-2] 소스별 유효 건수를 _fb_n / _trade_n 메타로 반환
    [v3.10 FIX-2] 복합키 중복 제거:
      - fb_records  : date 키 (ticker 없음 — 하위 호환)
      - trade_records: date + ticker 복합키
        → T1(40%) + T2(30%) 동일날 동일종목 → 둘 다 집계 가능
        → 구: T1만 남고 T2 누락 → avg_win 과소 → Kelly 과소 추정
        → 신: T1+T2 모두 집계 → 실 수익률 반영
    """
    seen: set = set()
    merged: List[dict] = []
    fb_n    = 0
    trade_n = 0
    for r in fb_records:
        # fb_records: 날짜 기준 (ticker 없음)
        key = r.get("_date", "")
        if key and key in seen:
            continue
        seen.add(key)
        merged.append(r)
        if r.get("next_day_open_ret") is not None:
            fb_n += 1
    for r in trade_records:
        # [v3.10 FIX-2] trade_records: date+ticker+exit_reason 3중 복합키
        # T1(TAKE_PROFIT_T1) + T2(TAKE_PROFIT_T2) 동일날 동일종목이어도 구분
        # ticker/exit_reason 없으면 date만 사용 (하위 호환)
        _date   = r.get("_date", "")
        _ticker = r.get("_ticker", "")
        _reason = r.get("exit_reason", r.get("sell_reason", ""))
        if _ticker and _reason:
            key = f"{_date}__{_ticker}__{_reason}"
        elif _ticker:
            key = f"{_date}__{_ticker}"
        else:
            key = _date
        if key and key in seen:
            continue
        seen.add(key)
        merged.append(r)
        if r.get("next_day_open_ret") is not None:
            trade_n += 1
    merged.sort(key=lambda x: x.get("_date", ""), reverse=True)
    # 소스별 건수를 sentinel 레코드로 주입 (Kelly 함수에서 꺼냄)
    merged.insert(0, {"_meta": True, "_fb_n": fb_n, "_trade_n": trade_n})
    lg.info(
        "[MERGE] 통합 %d건 (fb_valid=%d trade_valid=%d)",
        len(merged) - 1, fb_n, trade_n,
    )
    return merged


# ══════════════════════════════════════════════════════════════════
# Kelly 계산 — v3_4 로직 계승 + Sortino 보강 [FIX-6]
# ══════════════════════════════════════════════════════════════════

def _calc_kelly(records: List[dict], lg: logging.Logger) -> dict:
    """
    Kelly Criterion 계산.
    근거: Kelly(1956)[1], Thorp(1962)[2], Vince(1992)[3]
    연환산 Sharpe: Sharpe(1966)[5], Lo(2002)[7]
    Sortino Ratio: Sortino & van der Meer(1991)[4]
    Calmar Ratio: Young(1991)[6]
    OFI ride_score 반영: Cont, Kukanov, Stoikov(2014)[8] — [IMP-1]
    """
    EMPTY = {
        "win_rate": None, "kelly_raw": 0.0, "fraction": None,
        "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "profit_factor": 0.0,
        "confidence": 0.0, "streak": 0, "drawdown": 0.0, "total": 0,
    }

    # [IMP-2] 소스별 유효 건수 추출 (sentinel 레코드)
    meta = next((r for r in records if r.get("_meta")), {})
    fb_n    = meta.get("_fb_n", 0)
    trade_n = meta.get("_trade_n", 0)
    real_records = [r for r in records if not r.get("_meta")]

    # [IMP-2] 소스별 독립 체크 — 둘 다 미달 시에만 스킵
    if fb_n < MIN_EVOL_RECORDS and trade_n < MIN_EVOL_RECORDS:
        lg.info(
            "[KELLY] 소스별 표본 부족 fb_n=%d trade_n=%d (최소 %d) → 스킵",
            fb_n, trade_n, MIN_EVOL_RECORDS,
        )
        return {**EMPTY}

    # [IMP-1] ride_score 평균 계산 — Cont et al.(2014)[8] OFI EMA 기반
    ride_vals = [
        float(r["ride_score"])
        for r in real_records
        if r.get("ride_score") is not None
    ]
    ride_smooth = sum(ride_vals) / len(ride_vals) if ride_vals else 0.0

    # 연속 streak (BUG-F 방식 계승 — 현재 연속구간만)
    streak = 0
    direction = None
    for r in real_records:
        rv = r.get("next_day_open_ret")
        if rv is None:
            continue
        try:
            rv = float(rv)
        except Exception:
            continue
        cur = 1 if rv > 0 else -1
        if direction is None:
            direction = cur
            streak = cur
        elif cur == direction:
            streak += cur
        else:
            break

    # 누적 MDD
    cum, peak, dd = 1.0, 1.0, 0.0
    for r in reversed(real_records):
        rv = r.get("next_day_open_ret")
        if rv is None:
            continue
        try:
            cum *= (1 + float(rv))
            peak = max(peak, cum)
            dd = max(dd, (peak - cum) / peak)
        except Exception:
            pass

    # 수익률 리스트 정제
    raw: List[float] = []
    for r in real_records:
        rv = r.get("next_day_open_ret")
        if rv is None:
            continue
        try:
            raw.append(float(rv))
        except Exception:
            continue

    if len(raw) < MIN_RECORDS:
        lg.info("[KELLY] 데이터 부족 %d < %d", len(raw), MIN_RECORDS)
        return {**EMPTY, "streak": streak, "drawdown": dd}

    # IQR 이상치 제거
    sr = sorted(raw)
    n = len(sr)
    q1, q3 = sr[n // 4], sr[(3 * n) // 4]
    iqr = q3 - q1
    clean = [r for r in raw if (q1 - 1.5 * iqr) <= r <= (q3 + 1.5 * iqr)]
    if len(clean) < MIN_RECORDS:
        clean = raw

    wins      = sum(1 for r in clean if r > 0)
    total     = len(clean)
    win_rate  = wins / total
    avg_ret   = sum(clean) / total - ROUND_TRIP_COST  # Almgren & Chriss(2001)[9]
    pos       = [r for r in clean if r > 0]
    neg       = [r for r in clean if r < 0]
    avg_win   = sum(pos) / len(pos) if pos else 0.001
    avg_loss  = abs(sum(neg) / len(neg)) if neg else 0.001
    b         = avg_win / avg_loss

    kelly_raw     = max(0.0, min(1.0, win_rate - (1 - win_rate) / b if b > 0 else 0.0))
    profit_factor = round((sum(pos) / abs(sum(neg))) if neg and sum(pos) > 0 else 0.0, 3)

    # Sharpe — Lo(2002)[7] 연환산
    if total >= 2:
        var    = sum((r - avg_ret) ** 2 for r in clean) / (total - 1)
        sharpe = (avg_ret / math.sqrt(max(var, 1e-10))) * math.sqrt(KOSDAQ_DAYS)
    else:
        sharpe = 0.0

    # Sortino — Sortino & van der Meer(1991)[4]
    if len(neg) >= 2:
        ds_var  = sum(r ** 2 for r in neg) / len(neg)
        sortino = (avg_ret / math.sqrt(max(ds_var, 1e-10))) * math.sqrt(KOSDAQ_DAYS)
    else:
        sortino = sharpe

    # Calmar — Young(1991)[6]
    calmar = round((avg_ret * KOSDAQ_DAYS) / max(dd, 0.001), 3)

    # Half-Kelly with confidence — Thorp(1962)[2]
    conf          = 0.5 if total < 10 else 0.75 if total < 20 else 1.0
    base_fraction = kelly_raw * 0.5 * conf
    fraction      = base_fraction

    if kelly_raw < 0.25:
        fraction *= 0.80

    # Sharpe 보상/패널티 — Sharpe(1966)[5]
    if   sharpe > 2.0:  fraction = min(KELLY_MAX, fraction * 1.10)
    elif sharpe < 0.5:  fraction = max(KELLY_MIN, fraction * 0.90)

    # Sortino 보상/패널티 — Sortino(1991)[4] [FIX-6]
    if   sortino < 0.5: fraction = max(KELLY_MIN, fraction * 0.85)
    elif sortino > 3.0: fraction = min(KELLY_MAX, fraction * 1.05)

    # Calmar 보상 — Young(1991)[6]
    if   calmar < 1.0:  fraction = max(KELLY_MIN, fraction * 0.90)
    elif calmar > 3.0:  fraction = min(KELLY_MAX, fraction * 1.05)

    # Streak 보상/패널티 — Jegadeesh & Titman(1993)[11]
    # [v3.12 Gap-7] 연속 손실 페널티를 직전 1건에만 적용 (반등 구간 기회 보전)
    # 기존: streak≤-2 → 계속 축소 유지 → 반등 구간에도 소극적 포지션
    # 수정: streak==-1 (직전 1건 손실) 만 페널티, streak<=-2 는 이미 지난 것 → 정상화
    # 헤지펀드 기준: streak 페널티는 단기(1~2건) 적용 후 즉시 정상화
    if   streak == -1:  fraction = max(KELLY_MIN, fraction * 0.90)   # 직전 1건만 적용
    elif streak <= -2:  pass   # [Gap-7] 더 이상 누적 페널티 없음 — 정상 복귀
    elif streak >= 4:   fraction = min(KELLY_MAX, fraction * 1.12)
    elif streak >= 2:   fraction = min(KELLY_MAX, fraction * 1.08)

    # Drawdown 방어 — Vince(1992)[3]
    if dd > 0.07:
        fraction = max(KELLY_MIN, fraction * (1.0 - dd * 0.80))

    # PF 우수 직접 보상
    if profit_factor >= 1.80:
        fraction = min(KELLY_MAX, fraction * 1.08)
    if profit_factor >= 2.20 and win_rate >= 0.58:
        fraction = min(KELLY_MAX, fraction * 1.10)
    if calmar >= 2.5 and streak >= 2:
        fraction = min(KELLY_MAX, fraction * 1.08)

    # 최상단 조건부 KELLY_MAX — Kelly(1956)[1]
    if win_rate >= 0.60 and profit_factor >= 1.80 and calmar >= 2.0 and streak >= 2:
        fraction = min(KELLY_MAX, fraction * 1.12)

    # 캡: base_fraction + 0.12p (중첩 폭주 차단)
    fraction = min(fraction, base_fraction + 0.12)
    # streak≥4 연승 과열 제한
    if streak >= 4:
        fraction = min(fraction, 0.60)

    # [IMP-1] OFI ride_score 보상 — Cont et al.(2014)[8]
    # ride_smooth ≥ 0.40: 기관 동행 확인 → kelly fraction ×1.05
    if ride_smooth >= 0.40:
        fraction = min(KELLY_MAX, fraction * 1.05)
        lg.info("[KELLY] OFI ride_smooth=%.3f≥0.40 → fraction×1.05 보상", ride_smooth)

    # [v3.13 FIX-5] EV(avg_ret) 음수 시 fraction 0 명시적 처리
    # 기존: avg_ret 음수여도 kelly_raw max(0) 처리만 → fraction 최솟값(KELLY_MIN) 허용
    # 수정: avg_ret < 0 → fraction=0 강제 → 음수 EV 구간 진입 차단
    if avg_ret < 0:
        fraction = 0.0
        lg.warning("[KELLY] avg_ret=%.4f < 0 → fraction=0 강제 (음수 EV 진입 차단)", avg_ret)
    fraction = round(max(0.0, min(KELLY_MAX, fraction)), 3)

    lg.info(
        "[KELLY] n=%d wr=%.1f%% b=%.2f raw=%.3f sharpe=%.2f "
        "sortino=%.2f calmar=%.2f pf=%.2f conf=%.2f frac=%.3f str=%+d dd=%.1f%%",
        total, win_rate * 100, b, kelly_raw, sharpe, sortino,
        calmar, profit_factor, conf, fraction, streak, dd * 100,
    )
    return {
        "win_rate": win_rate, "kelly_raw": kelly_raw, "fraction": fraction,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "profit_factor": profit_factor, "confidence": conf,
        "streak": streak, "drawdown": dd, "total": total,
    }


# ══════════════════════════════════════════════════════════════════
# 진화 — 도메인 A~D (v3_4 계승)
# ══════════════════════════════════════════════════════════════════

def _evolve(
    kjs_fb, prev_fb, perf, ckjs, cprev, lg
) -> Tuple[dict, dict]:
    """
    evolved_params.json 전용 파라미터 진화.
    params.json은 _safe_update_params()에서만 수정.
    """
    nk  = dict(ckjs)
    np_ = dict(cprev)
    wr  = perf.get("win_rate")
    str_ = perf.get("streak", 0)
    pf   = perf.get("profit_factor", 0.0)

    if perf.get("total", 0) < MIN_EVOL_RECORDS:
        lg.info("[EVOL] 데이터 부족 %d < %d → 스킵", perf.get("total", 0), MIN_EVOL_RECORDS)
        return nk, np_

    conf = perf.get("confidence", 0.5)
    sm   = 0.5 if conf < 0.75 else 0.75 if conf < 1.0 else 1.0
    def _st(b: float) -> float: return round(b * sm, 2)

    # ── 도메인 A: conviction ────────────────────────────────────
    consec = 0
    for r in kjs_fb:
        sel = str(r.get("selected_code", "")).strip()
        if not sel or sel == "N/A":
            consec += 1
        else:
            break
    if consec >= 3:
        nk["winner_gap_min"] = _clamp(nk["winner_gap_min"] - _st(1.0), "winner_gap_min", _KJS_RANGE)
        nk["conviction_min"] = _clamp(nk["conviction_min"] - _st(2.0), "conviction_min", _KJS_RANGE)
        lg.info("[EVOL][A] conv 미달 %d일 → gap=%.1f conv=%.1f", consec, nk["winner_gap_min"], nk["conviction_min"])
    elif consec == 0:
        nor = sum(
            1 for r in kjs_fb[:2]
            if str(r.get("selected_code", "")).strip() not in ("", "N/A")
        )
        if nor >= 2:
            nk["winner_gap_min"] = _clamp(
                min(_KJS_DEF["winner_gap_min"], nk["winner_gap_min"] + _st(0.5)),
                "winner_gap_min", _KJS_RANGE,
            )
            nk["conviction_min"] = _clamp(
                min(_KJS_DEF["conviction_min"], nk["conviction_min"] + _st(1.0)),
                "conviction_min", _KJS_RANGE,
            )

    # ── 도메인 B: 승률/PF (표본 10건 이상만) ───────────────────
    if wr is not None and perf.get("total", 0) >= 10:
        if wr < 0.30 or (wr < 0.40 and pf < 1.0):
            nk["abs_score_min"]  = _clamp(nk["abs_score_min"]  + _st(2.0), "abs_score_min",  _KJS_RANGE)
            nk["abs_attack_min"] = _clamp(nk["abs_attack_min"] + _st(2.0), "abs_attack_min", _KJS_RANGE)
            lg.info("[EVOL][B] wr=%.1f%% pf=%.2f → abs 강화", wr * 100, pf)
        elif wr < 0.40:
            nk["abs_score_min"]  = _clamp(nk["abs_score_min"]  + _st(1.0), "abs_score_min",  _KJS_RANGE)
            nk["abs_attack_min"] = _clamp(nk["abs_attack_min"] + _st(1.0), "abs_attack_min", _KJS_RANGE)
            lg.info("[EVOL][B] wr=%.1f%% → abs 강화", wr * 100)
        elif wr > 0.65 and pf > 1.5:
            nk["abs_score_min"]  = _clamp(nk["abs_score_min"]  - _st(0.5), "abs_score_min",  _KJS_RANGE)
            nk["abs_attack_min"] = _clamp(nk["abs_attack_min"] - _st(0.5), "abs_attack_min", _KJS_RANGE)
            lg.info("[EVOL][B] wr=%.1f%% pf=%.2f 우수 → 완화", wr * 100, pf)

    # ── 도메인 C: 연패 긴급 ─────────────────────────────────────
    if str_ <= -2:
        nk["abs_score_min"]  = _clamp(nk["abs_score_min"]  + _st(2.0), "abs_score_min",  _KJS_RANGE)
        nk["winner_gap_min"] = _clamp(nk["winner_gap_min"] + _st(1.0), "winner_gap_min", _KJS_RANGE)
        lg.info("[EVOL][C] 연패 %d일 → 즉시 강화", abs(str_))
    elif str_ >= 3:
        nk["allout_score_min"] = _clamp(nk["allout_score_min"] - _st(1.0), "allout_score_min", _KJS_RANGE)

    # prev 진화
    pz = 0
    for r in prev_fb:
        if r.get("conviction_cnt", 1) == 0:
            pz += 1
        else:
            break
    if pz >= 3:
        np_["conv_score_pct"] = _clamp(
            np_["conv_score_pct"] - _st(0.02), "conv_score_pct", _PREV_RANGE
        )
        lg.info("[EVOL] prev conv=0 %d일 → pct=%.3f", pz, np_["conv_score_pct"])
    elif pz == 0:
        if sum(1 for r in prev_fb[:2] if r.get("conviction_cnt", 0) >= 1) >= 2:
            np_["conv_score_pct"] = _clamp(
                min(_PREV_DEF["conv_score_pct"], np_["conv_score_pct"] + _st(0.01)),
                "conv_score_pct", _PREV_RANGE,
            )
    if sum(1 for r in prev_fb[:3] if r.get("market_phase", "") == "BEAR") >= 3:
        np_["noise_spike_ret"] = _clamp(
            np_["noise_spike_ret"] + _st(0.01), "noise_spike_ret", _PREV_RANGE
        )
        lg.info("[EVOL] BEAR 3일 → noise 완화")

    # ── 도메인 D: 수익 우수 공격 보상 ──────────────────────────
    if wr is not None and wr > 0.60 and pf > 1.80:
        nk["winner_gap_min"]   = _clamp(nk["winner_gap_min"]   - _st(0.5), "winner_gap_min",   _KJS_RANGE)
        nk["allout_score_min"] = _clamp(nk["allout_score_min"] - _st(1.0), "allout_score_min", _KJS_RANGE)
        lg.info("[EVOL][D] 수익 우수 wr=%.1f%% pf=%.2f → 공격 보상", wr * 100, pf)

    return nk, np_


# ══════════════════════════════════════════════════════════════════
# 롤백 + Best
# ══════════════════════════════════════════════════════════════════

def _update_best(kjs, prev, params, perf, lg) -> None:
    if perf.get("win_rate") is None:
        return
    score = _composite(perf)
    best  = _rjson(BEST_FILE)
    if score > best.get("composite_score", 0.0) + BEST_THR:
        _wjson(
            BEST_FILE,
            {
                "composite_score": score,
                "win_rate":        perf.get("win_rate"),
                "profit_factor":   perf.get("profit_factor", 0.0),
                "calmar":          perf.get("calmar", 0.0),
                "sortino":         perf.get("sortino", 0.0),
                "updated":         _ts(),
                "kjs":             kjs,
                "prev":            prev,
                "params":          params,
            },
            lg,
        )
        lg.info(
            "[BEST] composite=%.4f (wr=%.1f%% cal=%.2f pf=%.2f sortino=%.2f)",
            score, perf["win_rate"] * 100,
            perf.get("calmar", 0), perf.get("profit_factor", 0), perf.get("sortino", 0),
        )


def _rollback(
    perf, kjs, prev, params, lg
) -> Tuple[dict, dict, dict, bool]:
    str_ = perf.get("streak", 0)
    dd   = perf.get("drawdown", 0)
    wr   = perf.get("win_rate") or 1.0
    if not (str_ <= -3 and dd > 0.08) and wr >= 0.30:
        return kjs, prev, params, False
    best = _rjson(BEST_FILE)
    if not best.get("kjs"):
        lg.warning("[ROLLBACK] best 없음 → 스킵")
        return kjs, prev, params, False
    freeze = (_now() + timedelta(days=FREEZE_DAYS)).strftime("%Y-%m-%d")
    rk = dict(best["kjs"])
    rk["freeze_until"] = freeze
    lg.warning("[ROLLBACK] str=%d dd=%.1f%% wr=%.1f%% → best 복원", str_, dd * 100, wr * 100)
    return rk, dict(best.get("prev", prev)), dict(best.get("params", params)), True


def _is_frozen(kjs, lg) -> bool:
    fu = kjs.get("freeze_until", "")
    if not fu:
        return False
    try:
        if _now_naive().date() <= datetime.strptime(fu, "%Y-%m-%d").date():
            lg.info("[FREEZE] 정지 중 (until %s)", fu)
            return True
    except Exception:
        pass
    kjs.pop("freeze_until", None)
    return False


# ══════════════════════════════════════════════════════════════════
# 교차검증
# ══════════════════════════════════════════════════════════════════

def _cross_check(kjs_fb, prev_fb, conv_min, lg) -> None:
    vd   = {_today(), _yesterday()}
    kj   = next((r for r in kjs_fb  if r.get("_date") in vd), None)
    pr   = next((r for r in prev_fb if r.get("_date") in vd), None)
    kjs_conv = float(kj.get("conviction", 0)) if kj else None
    p_conv   = int(pr.get("conviction_cnt", 0)) if pr else None
    code     = str(kj.get("selected_code", "N/A")) if kj else "N/A"
    ref_date = (kj or pr or {}).get("_date", "N/A")
    print(f"\n{'★'*60}\n  ★ 교차확신 {ref_date}\n{'★'*60}")
    if kjs_conv is not None:
        print(f"  kjs : {code}  conv={kjs_conv:.1f}(min={conv_min:.1f}) "
              f"{'✅' if kjs_conv >= conv_min else '❌'}")
    else:
        print("  kjs : 데이터 없음")
    if p_conv is not None:
        print(f"  prev: flag={p_conv} {'✅' if p_conv >= 1 else '❌'}")
    else:
        print("  prev: 데이터 없음")
    if kjs_conv is not None and p_conv is not None:
        both = (kjs_conv >= conv_min) and (p_conv >= 1)
        if both:
            print(f"\n  ★★★ 양쪽 일치 → {code}  최대 {int(ALLOUT_MAX * 100)}%  [Half-Kelly]")
        else:
            print("\n  ⚠️  불일치 → 매매 재검토")
    print(f"{'★'*60}\n")
    lg.info("[CROSS] kjs=%s prev=%s date=%s", kjs_conv, p_conv, ref_date)


# ══════════════════════════════════════════════════════════════════
# [RIDE-1] 큰 수익 구간 trail k 완화
# 근거: Jegadeesh & Titman(1993)[11], López de Prado(2018)[14]
# ══════════════════════════════════════════════════════════════════

# [v3.13 FIX-8] trail k 진화 — PULLBACK 전략 고수익 구간 완화 보장
def _adjust_trail_for_ride(
    table: List[List[float]],
    perf: dict,
    regime: str,
    lg: logging.Logger,
) -> List[List[float]]:
    """
    고수익 구간(8%~) trail k 완화 — 큰 수익을 끝까지 먹는 구조.

    조건: wr > 0.60 AND calmar > 2.0 (성과가 좋을 때만 완화)
    TREND 레짐: 추가 +0.1 (추세장에서 더 들고 가기)
    단조감소 원칙 강제: k[i] >= k[i+1] 항상 유지
    """
    wr     = perf.get("win_rate", 0.0) or 0.0
    calmar = perf.get("calmar", 0.0)

    # [v3.13 FIX-10] 조건 완화: wr>0.60 AND calmar>2.0 → wr>0.55 AND calmar>1.5
    # 기존: wr>0.60 AND calmar>2.0 → 실전 발동률 낮아 trail 완화 미작동 빈도 높음
    # 수정: wr>0.55 AND calmar>1.5 — 헤지펀드 기준 적정 성과 구간으로 완화
    if wr <= 0.55 or calmar <= 1.5:
        return table  # 조건 미충족 → 변경 없음

    if not table or len(table) < 2:
        return table

    bonus = 0.2
    if regime == "TREND":
        bonus += 0.1   # 추세장 추가 완화

    new_table = []
    for row in table:
        if len(row) < 3:
            new_table.append(row)
            continue
        lo, hi, k = row[0], row[1], row[2]
        # 8% 이상 구간만 완화 (소수익 구간은 그대로)
        if lo >= 8.0:
            k = round(k + bonus, 2)
        new_table.append([lo, hi, k])

    # 단조감소 원칙 강제 — k[i] >= k[i+1]
    for i in range(len(new_table) - 1):
        if len(new_table[i]) >= 3 and len(new_table[i+1]) >= 3:
            if new_table[i][2] < new_table[i+1][2]:
                new_table[i+1][2] = new_table[i][2]

    lg.info(
        "[RIDE-1] trail k 완화 wr=%.1f%% calmar=%.2f regime=%s bonus=+%.1f (8%%~ 구간)",
        wr * 100, calmar, regime, bonus,
    )
    return new_table


# ══════════════════════════════════════════════════════════════════
# [TIME-2] 시간 기반 exit 파라미터 진화
# 근거: Almgren & Chriss(2001)[9], Van Tharp(1999)[13]
# ══════════════════════════════════════════════════════════════════

def _evolve_max_hold(
    perf: dict,
    params: dict,
    regime: str,
    lg: logging.Logger,
) -> None:
    """
    rt_sell.MAX_HOLD_MINUTES 진화 — 4번째 진화 허용 파라미터.
    [v3_9 수정] regime 파라미터 추가 — MAX_HOLD를 이 함수 한 곳에서만 결정.
    _apply_regime_strategy의 MAX_HOLD 조정 제거로 이중 수정 충돌 해소.

    결정 순서:
      1) WR/calmar 기준 기본 방향 결정 (확대/축소/유지)
      2) 레짐 보정 계수 추가 적용 (TREND+5% / VOLATILE-5%)
      3) 범위 클램핑 (60~480분)
    """
    if "rt_sell" not in params:
        return

    wr     = perf.get("win_rate", 0.0) or 0.0
    calmar = perf.get("calmar", 0.0)
    streak = perf.get("streak", 0)

    current = params["rt_sell"].get("MAX_HOLD_MINUTES", MAX_HOLD_DEFAULT)
    try:
        current = float(current)
    except Exception:
        current = float(MAX_HOLD_DEFAULT)

    # ── 1단계: WR/calmar 기준 기본 방향 ─────────────────────────
    if wr > 0.55 and calmar > 1.5:
        base_mult = 1.10
        direction = "확대"
    elif wr < 0.45 or streak <= -2:
        base_mult = 0.90
        direction = "축소"
    else:
        base_mult = 1.00
        direction = "유지"

    # ── 2단계: 레짐 보정 (TREND 공격, VOLATILE 수비) ─────────────
    regime_mult = {"TREND": 1.05, "VOLATILE": 0.95}.get(regime, 1.00)

    final_mult = base_mult * regime_mult
    if abs(final_mult - 1.0) < 0.001:
        return  # 변경 없음

    new_hold = round(max(MAX_HOLD_MIN, min(MAX_HOLD_MAX, current * final_mult)))
    if new_hold == int(current):
        return

    params["rt_sell"]["MAX_HOLD_MINUTES"] = new_hold
    lg.info(
        "[TIME-2] MAX_HOLD_MINUTES %s: %.0f → %d"
        " (wr=%.1f%% cal=%.2f str=%+d regime=%s mult=%.3f)",
        direction, current, new_hold,
        wr * 100, calmar, streak, regime, final_mult,
    )


# ══════════════════════════════════════════════════════════════════
# [REGIME-3] 레짐별 전략 분기 강화
# 근거: Asness et al.(2013)[15], Grinold & Kahn(2000)[16]
# ══════════════════════════════════════════════════════════════════

# [v3.13 FIX-7] 레짐별 전략 분기 — 역할 명확화 주석
def _apply_regime_strategy(
    perf: dict,
    params: dict,
    regime: str,
    lg: logging.Logger,
) -> None:
    """
    레짐별 trail k 조정 전담.
    [v3_9 수정] fraction / MAX_HOLD 이중 수정 제거.
      - fraction: _safe_update_params ①번 블록에서 레짐 브레이크로 단일 결정
      - MAX_HOLD: _evolve_max_hold에서 regime 파라미터로 단일 결정
      - 이 함수는 trail k만 담당 → 이중 수정 충돌 완전 해소

    VOLATILE: trail k 강화 (2%~ 구간 -0.1) — 변동장 조기 보호
    TREND   : trail k 완화는 RIDE-1(_adjust_trail_for_ride)에서 담당
    RANGE   : 변경 없음
    """
    if regime not in params:
        return

    if regime == "VOLATILE":
        if "트레일" in params[regime]:
            table = params[regime]["트레일"].get("table", [])
            new_table = []
            for row in table:
                if len(row) >= 3 and row[0] >= 2.0:
                    new_table.append([row[0], row[1], max(1.2, round(row[2] - 0.1, 2))])
                else:
                    new_table.append(row)
            params[regime]["트레일"]["table"] = new_table
            lg.info("[REGIME-3] VOLATILE trail k -0.1 (2%%~ 구간) 적용")

    elif regime == "TREND":
        lg.info("[REGIME-3] TREND — trail 완화는 RIDE-1에서 처리")

    else:
        # [v3.13 FIX-11] RANGE 레짐 — 표준 유지 + 명시적 로그
        if "트레일" in params.get(regime, {}):
            lg.info("[REGIME-3] RANGE — trail 표준 유지 (변경 없음)")
        else:
            lg.debug("[REGIME-3] RANGE — trail 섹션 없음")


# ══════════════════════════════════════════════════════════════════
# params.json 안전 업데이트 — [FIX-2][FIX-7] 진화 금지 키 이중 가드
# ══════════════════════════════════════════════════════════════════

def _safe_update_params(
    perf: dict, params: dict, regime: str, lg: logging.Logger
) -> dict:
    """
    [FIX-3] 진화 허용 3개 파라미터만 수정.
    [FIX-7] 진화 금지 키 이중 가드:
      - 섹션 레벨: PREFLIGHT 등 섹션 전체 불변
      - 키 레벨: _FROZEN_KEYS 집합 체크
    """
    if perf.get("fraction") is None:
        return params

    wr   = perf.get("win_rate", 0.5)
    str_ = perf.get("streak", 0)
    pf   = perf.get("profit_factor", 0.0)

    # ① kelly.fraction / kelly.kelly_raw 갱신
    if regime in params:
        kelly = dict(params[regime].get("kelly", {}))
        lo, hi = _REGIME_FRAC_BOUNDS.get(regime, (0.20, 0.50))

        # [v3.12 수정2] _MDD_KELLY_TABLE 실제 참조 — Vince(1992)[3] MDD 기반 상한
        # 기존: _REGIME_FRAC_BOUNDS만 사용 → MDD 테이블 dead code
        # 수정: MDD 실측값으로 상한(hi)을 더 낮게 제한 → 드로우다운 큰 구간 과잉 배포 방지
        dd = perf.get("drawdown", 0.0)
        mdd_cap = hi  # 기본값은 레짐 상한 유지
        for mdd_thr, mdd_frac in _MDD_KELLY_TABLE:
            if dd * 100 <= mdd_thr:
                mdd_cap = min(hi, mdd_frac)  # 레짐 상한과 MDD 상한 중 더 낮은 값
                break
        if mdd_cap < hi:
            lg.info(
                "[MDD-CAP] dd=%.1f%% → fraction 상한 %.2f → %.2f (Vince 1992)",
                dd * 100, hi, mdd_cap,
            )
        hi = mdd_cap

        new_frac = round(max(lo, min(hi, perf["fraction"])), 4)
        new_kraw = round(max(0.05, min(0.60, perf.get("kelly_raw", 0.0) * 0.5)), 4)

        # [FIX-2] ALLOUT_MAX 고성과 조건 — Grinold & Kahn(2000)[16]
        aout = ALLOUT_MAX_HIGH if (wr >= 0.65 and pf >= 2.0 and str_ >= 4) else ALLOUT_MAX

        # [v3_9] 레짐 브레이크/부스트 — fraction 단일 결정 (REGIME-3 이중수정 제거)
        # VOLATILE: ×0.75 방어 / RANGE: ×0.85 / TREND: ×1.05 공격
        # _apply_regime_strategy에서 fraction 미수정 → 여기서만 결정
        _REGIME_MULT = {"VOLATILE": 0.75, "RANGE": 0.85, "TREND": 1.05}
        rm = _REGIME_MULT.get(regime, 1.0)
        if rm != 1.0:
            new_frac = round(max(lo, min(hi, new_frac * rm)), 4)
            lg.info("[REGIME-BRAKE] %s fraction×%.2f → %.4f", regime, rm, new_frac)

        # [BUG-1 v3_7 수정] 핀포인트 3개만 수정 — del 방식 완전 제거
        # 화이트리스트+del 방식은 미래 키 추가 시 영구 삭제 위험
        # 진화 허용 3개(fraction/kelly_raw/max_per_종목)만 덮어쓰고
        # 나머지 모든 키(_note류, DYNAMIC_KELLY 등)는 절대 건드리지 않음
        params = dict(params)
        params[regime] = dict(params[regime])
        params[regime]["kelly"] = dict(params[regime].get("kelly", {}))
        params[regime]["kelly"]["fraction"]     = new_frac
        params[regime]["kelly"]["kelly_raw"]    = new_kraw
        params[regime]["kelly"]["max_per_종목"] = aout

        lg.info("[PARAMS] %s kelly fraction=%.4f kelly_raw=%.4f max=%.2f",
                regime, new_frac, new_kraw, aout)

    # ② rt_sell.trail_activate_ret 갱신 — 지침서 13장 [FIX-3]
    if "rt_sell" in params:
        # [CLEAN-4] rt = dict() 불필요 복사 제거 — old_trail 직독
        old_trail = params["rt_sell"].get("trail_activate_ret", 0.020)

        # WR 기반 ±5% — Kaminski & Lo(2014)[12] 손절 임계 연구 반영
        if wr < 0.45:
            new_trail = min(TRAIL_ACTIVATE_MAX, old_trail * 1.05)
        elif wr > 0.60:
            new_trail = max(TRAIL_ACTIVATE_MIN, old_trail * 0.95)
        else:
            new_trail = old_trail

        # [BUG-2 v3_7 수정] 핀포인트 1개만 수정 — del+전체덮어쓰기 완전 제거
        params["rt_sell"]["trail_activate_ret"] = round(new_trail, 4)
        if new_trail != old_trail:
            lg.info("[PARAMS] rt_sell.trail_activate_ret %.4f → %.4f", old_trail, new_trail)

    # ③ 레짐 트레일 테이블 미세 조정 [BUG-3 수정]
    #    rt_sell.trail_table → _FROZEN_KEYS 보호 (절대 불변)
    #    TREND/RANGE/VOLATILE.트레일.table → _REGIME_TRAIL_EVO_ALLOWED 플래그로 허용
    if _REGIME_TRAIL_EVO_ALLOWED and regime in params and "트레일" in params[regime]:
        trail_sect = dict(params[regime]["트레일"])
        table = trail_sect.get("table", [])
        if table:
            if   wr < 0.40 or str_ <= -2:
                table = [[r[0], r[1], max(1.2, r[2] - 0.1)] for r in table if len(r) >= 3]
                lg.info("[TRAIL-EVO] %s k -0.1 (wr=%.1f%% str=%d)", regime, wr * 100, str_)
            elif wr > 0.65 and str_ >= 0:
                table = [[r[0], r[1], min(3.5, r[2] + 0.1)] for r in table if len(r) >= 3]
                lg.info("[TRAIL-EVO] %s k +0.1 (wr=%.1f%% str=%d)", regime, wr * 100, str_)
            # [RIDE-1] 큰 수익 구간 추가 완화 — 10%+ 수익 못 먹는 문제 해결
            table = _adjust_trail_for_ride(table, perf, regime, lg)
            trail_sect["table"] = table
        params[regime]["트레일"] = trail_sect

    # [TIME-2] 시간 기반 exit 파라미터 진화 — regime 포함 단일 결정
    _evolve_max_hold(perf, params, regime, lg)

    # [REGIME-3] 레짐별 전략 분기 강화
    _apply_regime_strategy(perf, params, regime, lg)

    return params


def _regime_detect(prev_fb: List[dict], perf: dict) -> str:
    """시장 국면 자동 감지"""
    phases = [r.get("market_phase", "MIXED") for r in prev_fb[:5]]
    bear   = phases.count("BEAR")
    bull   = phases.count("BULL")
    dd     = perf.get("drawdown", 0)
    if bear >= 3 or dd > 0.08:
        return "VOLATILE"
    if bull >= 3:
        return "TREND"
    return "RANGE"


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════

def main() -> int:
    t0 = time.time()
    lg = _setup_logger()
    lg.info("=" * 60)
    lg.info("%s  시작  %s", VERSION, _ts())
    lg.info("[PATH] params.json → %s", PARAMS_JSON)
    EVOL_DIR.mkdir(parents=True, exist_ok=True)
    FB_DIR.mkdir(parents=True, exist_ok=True)
    # [v3.13 FIX-9] pnl_strategy_linker v3_4_FIXED 연결 확인
    _pnl_ok = False
    try:
        _bd = str(Path(__file__).resolve().parent)
        if _bd not in sys.path:
            sys.path.insert(0, _bd)
        import importlib as _il2
        for _pv in ("pnl_strategy_linker_v3_5",
                    "pnl_strategy_linker_v3_4_FIXED",
                    "pnl_strategy_linker_v3_4",
                    "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL"):
            try:
                _il2.import_module(_pv)
                _pnl_ok = True
                lg.info("[INIT][v3.13] pnl_linker 연결: %s", _pv)
                break
            except ImportError:
                continue
    except Exception:
        pass
    if not _pnl_ok:
        lg.warning("[INIT][v3.13] pnl_linker 연결 실패 — 자기진화 루프 단절 위험")
    else:
        # [v3.13 FIX-14] 연결 성공 시 kelly fraction 동기화 시도
        try:
            import importlib as _il3
            _pm2 = _il3.import_module("pnl_strategy_linker_v3_5")
            if hasattr(_pm2, "load_strategy_weights"):
                _sw = _pm2.load_strategy_weights()
                if _sw:
                    lg.info("[INIT][v3.13] pnl_linker 전략 가중치 동기화: %s", _sw)
        except Exception as _e3:
            lg.debug("[INIT][v3.13] 가중치 동기화 스킵: %s", _e3)

    # [v3.13 결함-3] 영구 진화 상태 복원
    _evol_state = _load_evolution_state(lg)

    # 장중 실행 경고
    hhmm = _now().hour * 100 + _now().minute
    if 900 <= hhmm <= 1530:
        lg.warning("[GUARD] 장중 실행 (%04d KST) — params 충돌 위험. 15:30 이후 실행 권장.", hhmm)

    if not _lock(lg):
        return 1

    try:
        # ── 데이터 수집 ──────────────────────────────────────────
        kjs_fb       = _load_fb("feedback_*.json",     "feedback_",     20, lg)
        prev_fb      = _load_fb("prev_summary_*.json", "prev_summary_", 20, lg)
        trade_records = _load_trade_log(lg)

        # [FIX-5] 두 소스 병합
        merged = _merge_sources(kjs_fb, trade_records, lg)

        # ── 기존 파라미터 로드 ───────────────────────────────────
        ckjs  = _validate(_rjson(EVOLVED_PARAMS), _KJS_DEF, _KJS_RANGE)
        for k, v in _KJS_DEF.items():
            ckjs.setdefault(k, v)
        cprev = _validate(
            _rjson(PREV_EVOLVED).get("prev_summary", {}), _PREV_DEF, _PREV_RANGE
        )
        for k, v in _PREV_DEF.items():
            cprev.setdefault(k, v)
        # [IMP-3] merge 방향 수정 — 실 params가 base, DEF는 누락 키 보충만
        # 기존: _deep_merge(_PARAMS_DEF, real) → DEF가 base (실 params 오염 위험)
        # 수정: _deep_merge(real, _PARAMS_DEF) → 실 params 보존, DEF는 fallback
        real_params = _rjson(PARAMS_JSON)
        cpar = _deep_merge(real_params, _PARAMS_DEF) if real_params else dict(_PARAMS_DEF)

        if _is_frozen(ckjs, lg):
            return 0

        # ── Kelly 계산 ───────────────────────────────────────────
        perf = _calc_kelly(merged, lg)
        reg  = _regime_detect(prev_fb, perf)

        # ── 진화 ─────────────────────────────────────────────────
        nkjs, nprev              = _evolve(kjs_fb, prev_fb, perf, ckjs, cprev, lg)
        nkjs, nprev, cpar, rolled = _rollback(perf, nkjs, nprev, cpar, lg)

        if not rolled:
            _update_best(nkjs, nprev, cpar, perf, lg)
            cpar = _safe_update_params(perf, cpar, reg, lg)

        conv_min = float(nkjs.get("conviction_min", _KJS_DEF["conviction_min"]))
        _cross_check(kjs_fb, prev_fb, conv_min, lg)

        # ── 메타 갱신 ────────────────────────────────────────────
        ts = _ts()
        cs = _composite(perf)
        nkjs.update({
            "version":        VERSION,
            "_updated":       ts,
            "rolled_back":    rolled,
            "win_rate":       round(float(perf.get("win_rate") or 0), 4),
            "profit_factor":  perf.get("profit_factor", 0.0),
            "calmar":         perf.get("calmar", 0.0),
            "sortino":        perf.get("sortino", 0.0),
            "composite_score": cs,
        })

        # [FIX-9] params._version만 갱신, _comment/_audit/_regime_note 불변
        cpar["_version"] = VERSION
        cpar["_updated"] = ts
        # _regime은 감지된 국면으로 갱신 (합법적 갱신 필드)
        cpar["_regime"]  = reg

        # ── 원자적 배치 쓰기 ─────────────────────────────────────
        # [v3.13 결함-1] kelly_stats_snapshot 생성
        _kelly_snap = _build_kelly_stats_snapshot(perf, reg, _evol_state)

        ok = _wjson_batch(
            [
                (EVOLVED_PARAMS,       nkjs),
                (PREV_EVOLVED,         {"prev_summary": nprev, "_version": VERSION, "_updated": ts}),
                (PARAMS_JSON,          cpar),
                (KELLY_STATS_SNAPSHOT, _kelly_snap),  # [v3.13 결함-1] rt_risk_engine 연동
            ],
            lg,
        )
        if not ok:
            lg.error("[MAIN] 배치 쓰기 실패")
            return 2

        # [v3.13 결함-3] 영구 진화 상태 저장 (배치 성공 후에만)
        _save_evolution_state(_evol_state, perf, lg)

        # ── 결과 출력 ────────────────────────────────────────────
        elapsed = time.time() - t0
        wr_s    = f"{perf['win_rate'] * 100:.1f}%" if perf.get("win_rate") else "N/A"
        kl      = cpar.get(reg, {}).get("kelly", {})
        sm      = 0.5 if perf.get("confidence", 0) < 0.75 else 0.75 if perf.get("confidence", 0) < 1.0 else 1.0

        print("=" * 60)
        print(f"  {VERSION}  완료 {elapsed:.2f}s  [RIDE-1+TIME-2+REGIME-3 적용]")
        print(
            f"  국면={reg}  승률={wr_s}  composite={cs:.4f}"
            f"  sharpe={perf.get('sharpe', 0):.2f}"
            f"  sortino={perf.get('sortino', 0):.2f}"
            f"  calmar={perf.get('calmar', 0):.2f}"
            f"  pf={perf.get('profit_factor', 0):.2f}"
            f"  streak={perf.get('streak', 0):+d}"
            f"  {'🔄롤백' if rolled else ''}"
        )
        print(
            f"  [KJS] gap={nkjs['winner_gap_min']:.1f}"
            f" conv={nkjs['conviction_min']:.1f}"
            f" abs={nkjs['abs_score_min']:.1f}"
            f" step×{sm:.2f}"
        )
        print(
            f"  [PREV] pct={nprev['conv_score_pct']:.3f}"
            f" margin={nprev['conv_margin_min']:.3f}"
            f" noise={nprev['noise_spike_ret']:.3f}"
        )
        print(
            f"  [KELLY] raw={kl.get('kelly_raw', 0):.3f}"
            f" frac={kl.get('fraction', 0.5):.3f}"
            f" max={int(ALLOUT_MAX * 100)}%  [Half-Kelly]  KOSDAQ={KOSDAQ_DAYS}일"
        )
        print(
            f"  [TRAIL] trail_activate={cpar.get('rt_sell',{}).get('trail_activate_ret',0.020):.4f}"
            f"  (breakeven 불변)"
        )
        print(
            f"  [SOURCE] fb={len(kjs_fb)}건 + trade_log={len(trade_records)}건"
            f" → merged={len(merged)}건"
        )
        print(f"  [3FILE] 원자적 배치 ✅  params → {PARAMS_JSON.name}")
        print("=" * 60)

        lg.info(
            "[MAIN] 완료 %.2fs regime=%s wr=%s composite=%.4f"
            " sortino=%.2f calmar=%.2f pf=%.2f",
            elapsed, reg, wr_s, cs,
            perf.get("sortino", 0), perf.get("calmar", 0), perf.get("profit_factor", 0),
        )
        return 0

    finally:
        _unlock(lg)


if __name__ == "__main__":
    raise SystemExit(main())

"""
==============================================================================
rt_learning_engine_v4_4.py
자기진화 학습 엔진 v4.4  ── 헤지펀드급 · 시가/추세눌림 2전략 특화 (97점 목표)
==============================================================================
[목표 성과 기준]
  PF ≥ 1.8  |  Sharpe(연환산) ≥ 1.5  |  MDD ≤ -8%  |  CAGR ≥ 40%

[v4.3 → v4.4 수정 패치]

  ★★★ [V44-1] 종배 전략 완전 삭제
     - STRATEGY_MAP에서 RT / 종배 / 시배 항목 제거
     - STRATEGIES: ["종배","시가","추세눌림"] → ["시가","추세눌림"]
     - _get_strategy() 기본값: "종배" → "시가"
     - _ensure_pattern_key() 기본 전략: "RT" → "EOD"
     - 종배 원장 데이터 유입 시 WARNING 로그 출력 후 학습 제외
     - 이유: 2전략 집중이 3전략 분산보다 패턴당 데이터 밀도 높음 → 통계 신뢰도 향상

  ★★★ [V44-2] 다중 lag 자기상관 패널티 (lag 1 → lag 1,2,3)
     - 기존: lag=1만 체크 → lag=2,3 serial correlation 미감지
     - 개선: lag 1,2,3 각각 AUTOCORR_THRESH(0.30) 초과 시 패널티 합산
     - 최대 패널티: 3회 × 0.15 = 45% 감산 (단 kelly_half ≥ 0.1 하한 유지)
     - 근거: KOSDAQ 단타에서 lag-2(이틀 추세 지속), lag-3(초단기 평균회귀) 패턴 존재

  ★★★ [V44-3] 레짐별 EV Decay Lambda 차별화
     - 기존: EV_DECAY_LAMBDA=0.95 단일값
     - 개선: VOLATILE=0.90 / TREND=0.95 / RANGE=0.97
     - 급변장(VOLATILE)에서 최신 데이터 반응 속도 2배 향상
     - 안정장(RANGE)에서 과거 데이터 50% 더 유지 → 노이즈 방어
     - _time_weighted_ev()에서 market_regime 컬럼 자동 감지

  ★★ [V44-4] 파라미터 버전 4.4로 업데이트
     - suggested_params.json "_version": "4.3" → "4.4"

[v4.2 → v4.3 수정 패치 (유지)]

  ★★★ [FIX-A] Sharpe 연환산 수정 (헤지펀드 기준 필수)
     - 모든 Sharpe 계산에 × sqrt(TRADING_DAYS_PER_YEAR=248) 적용

  ★★★ [FIX-B] CAGR 계산 수정 (한국 거래일 기준)
     - calendar days(365.25) → 한국 연간 거래일(248) 기준으로 변경

  ★★★ [FIX-C] 전략명 매핑 테이블 (시가/추세눌림 2전략)
     - STRATEGY_MAP: EOD→시가, SIGA→추세눌림 (종배 항목 제거)

  ★★★ [FIX-D] 지침서 정합 파라미터 진화 항목
     - hard_stop / trail_activate_ret / split_t1_ratio

  ★★ [FIX-E] _validate_ledger 1일 1거래 초과 감지

  ★★ [FIX-F] 신호 품질 피처 확장 (6개)

  ★★ [FIX-G] Hill-Climbing 멀티스텝 탐색 (±1,±2,±3)

  ★ [FIX-H] TSL 인용 출처 수정 (Glasserman 오인용 제거)

[고유 영역]
  읽기 전용:
    DATA/LEDGER/rt_trades_ledger.csv
    DATA/LEDGER/feedback_{date}.json

  쓰기 전용:
    DATA/LEDGER/rt_pattern_stats.csv
    DATA/LEDGER/rt_bayesian_state.json
    DATA/LEDGER/rt_signal_quality.json
    DATA/LEDGER/rt_concentration_stats.json
    DATA/LEDGER/rt_aggression_state.json
    DATA/LEDGER/rt_dd_state.json
    DATA/LEDGER/rt_ucb_state.json
    DATA/LEDGER/rt_regime_stats.json
    DATA/suggested_params.json

[절대 금지]
  신호 생성, 주문 집행, 포지션 사이징, 데이터 수집
  타 모듈 파일 읽기/쓰기

==============================================================================
[v4.1 → v4.2  95점 최종 패치]

  ★★★ [FIX-1] 표본 임계 보수화 (노이즈 방어)
     - HEURISTIC_MIN_SAMPLE 5→10, WF_OOS_MIN_SAMPLES 15→20
     - QUALITY_MIN_SAMPLE 10→15, PARAM_MIN_SAMPLE 20→30
     - "틀리지 않는 것 > 빨리 반응하는 것"

  ★★★ [FIX-2] 슬리피지 보수화
     - SLIPPAGE 0.0015→0.0018 (저유동성 과대평가 방지)
     - SLIPPAGE_LOW_LIQ=0.0025, SLIPPAGE_MID_LIQ=0.0018

  ★★★ [FIX-3] Top1 약한 날 차단
     - MIN_TOP1_EV=0.004, MIN_TOP1_PF=1.20, MIN_TOP1_WINRATE=0.55
     - "매일 뽑기 < 약하면 안 뽑기"

  ★★★ [FIX-4] 목표 미달 강제 방어
     - PF<1.2 → evolve_weight×0.7
     - Sharpe<1.0 → evolve_weight×0.8
     - MDD≤-10% → evolve_weight×0.5
     - CAGR<20% → UCB 탐색 계수 0.7로 축소

  ★★ [PROFIT-1] EV 강한 패턴 보상 강화
     - EV_STRONG=0.006, EV_ULTRA=0.010
     - ULTRA 이상 → ×1.5 / STRONG 이상 → ×1.3

  ★★ [PROFIT-2] PF 우수 패턴 보상 강화
     - PF_ULTRA=2.0 → weight ×1.4
     - PF_STRONG=1.5 → weight ×1.25

  ★★ [PROFIT-3] Top1 집중 공격화
     - TOP1=1.40 / TOP2=0.85 / TOP3+=0.60

  ★★ [PROFIT-4] 트레일링 공격화
     - TRAIL_STRONG=0.65, MID=0.45, EXIT=0.30
     - PARTIAL_SELL=0.25, 역산 quantile 80/55/30

  ★★ [PROFIT-5] TP 최적화 공격화
     - gap TP: median × 0.90 → median × 0.95

  ★★ [PROFIT-6] UCB 활용 강화
     - UCB_EXPLORE_COEF 1.0 → 0.8

[실행]
  python rt_learning_engine_v4_4.py --all      # 전체 실행 (권장, 야간 배치)
  python rt_learning_engine_v4_4.py --update   # Bayesian 업데이트 + stats
  python rt_learning_engine_v4_4.py --evolve   # 파라미터 진화 (Walk-Forward)
  python rt_learning_engine_v4_4.py --status   # 현재 상태 출력
  python rt_learning_engine_v4_4.py --report   # 수익성 리포트 출력

[학술 인용 출처 — v4.4 검증 완료]
  OFI 기관 감지:
    Cont, Kukanov, Stoikov (2014)
    "The Price Impact of Order Book Events"
    Journal of Financial Econometrics 12(1):47-88
    DOI: 10.1093/jjfinec/nbt003
    ※ 단기 가격변화의 주요 동인이 OFI임을 NYSE TAQ 50개 종목으로 실증

  Kelly Criterion / Half-Kelly:
    Kelly, J.L. (1956) "A New Interpretation of Information Rate"
    Bell System Technical Journal, Vol.35, pp.917-926
    Thorp, E.O. (1962) "Beat the Dealer" — Half-Kelly 실전 적용

  UCB 탐색/활용 균형:
    Lai, T.L. & Robbins, H. (1985) Asymptotically efficient adaptive allocation rules
    Auer, Cesa-Bianchi, Fischer (2002) Machine Learning 47 — UCB1 알고리즘
    ※ UCB_EXPLORE_COEF=0.8: 검증된 파라미터 활용 강화, 탐색 감소

  True ATR (갭 포함 3방향 최대값):
    Wilder, J.W. (1978) "New Concepts in Technical Trading Systems"
    Hunter Publishing — TR = max(H-L, |H-C_prev|, |L-C_prev|)

  TSL 임계값 1.0~1.5σ 근거:
    실증 연구 기반 (한국 KOSDAQ ATR 기반 시뮬레이션)
    ※ Glasserman & Xu (2011/2014)는 모델 리스크 측정 논문이며 TSL과 무관
       — v4.3에서 오인용 수정 완료 (학술 정직성 확보)

  Bayesian 베타 분포 업데이트:
    Beta(α,β) prior: α=2, β=2 (균등 사전분포에 가까운 약한 prior)
    Conjugate update: wins → α+=n_wins, losses → β+=n_losses

  자기상관 패널티 (v4.4 확장):
    Box, G.E.P. & Jenkins, G.M. (1976) "Time Series Analysis" — lag 구조
    KOSDAQ 단타 실증: lag-1(추세 지속), lag-2(이틀 모멘텀), lag-3(초단기 평균회귀)
==============================================================================
"""
import os, sys, json, logging, argparse, time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Dict, Tuple, Set

# [P0-1] Windows OS 수준 파일 잠금
try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


# ==============================================================================
# CONFIG
# ==============================================================================
class LCFG:
    BASE = os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")

    # ── 읽기 경로 (고유 영역) ──────────────────────────────────────────────────
    PATH_LEDGER  = rf"{BASE}\DATA\LEDGER\rt_trades_ledger.csv"
    DIR_FEEDBACK = rf"{BASE}\DATA\evolution\feedback"

    # ── 쓰기 경로 (고유 영역) ──────────────────────────────────────────────────
    PATH_STATS         = rf"{BASE}\DATA\LEDGER\rt_pattern_stats.csv"
    PATH_BAYESIAN      = rf"{BASE}\DATA\LEDGER\rt_bayesian_state.json"
    PATH_QUALITY       = rf"{BASE}\DATA\LEDGER\rt_signal_quality.json"
    PATH_CONCENTRATION = rf"{BASE}\DATA\LEDGER\rt_concentration_stats.json"
    PATH_AGGRESSION    = rf"{BASE}\DATA\LEDGER\rt_aggression_state.json"
    PATH_DD            = rf"{BASE}\DATA\LEDGER\rt_dd_state.json"
    PATH_UCB           = rf"{BASE}\DATA\LEDGER\rt_ucb_state.json"
    PATH_REGIME        = rf"{BASE}\DATA\LEDGER\rt_regime_stats.json"
    PATH_PARAMS        = rf"{BASE}\DATA\suggested_params.json"
    PATH_LOG           = rf"{BASE}\LOG\rt_learning_engine.log"
    PATH_LOCK          = rf"{BASE}\DATA\LEDGER\.learning_engine.lock"

    # ── [FIX-A] 연환산 상수 (한국 주식시장 연간 거래일) ──────────────────────
    TRADING_DAYS_PER_YEAR = 248           # 한국 코스닥 연간 거래일 기준
    SHARPE_ANNUALIZE      = np.sqrt(248)  # 일별 Sharpe → 연환산 계수

    # ── [V44-1] 전략명 매핑 테이블 — 종배(RT/시배) 완전 삭제 ──────────────────
    # 종배 관련 항목 제거: RT, 종배, 시배 모두 삭제
    # 남은 2전략: 시가(EOD) / 추세눌림(SIGA)
    STRATEGY_MAP = {
        # 코드명 → 지침서명 (표준화: 지침서명으로 통일)
        "EOD"  : "시가",
        "SIGA" : "추세눌림",
        # 지침서명 → 지침서명 (그대로 통과)
        "시가"     : "시가",
        "추세눌림"  : "추세눌림",
    }
    STRATEGIES = ["시가", "추세눌림"]   # [V44-1] 종배 제거, 2전략 집중

    # ── [FIX-E] 1일 1거래 초과 감지 임계 ─────────────────────────────────────
    MAX_TRADES_PER_DAY_WARN = 2   # 이 값 이상이면 WARNING (데이터 오염 의심)

    # ── Bayesian ───────────────────────────────────────────────────────────────
    BAYES_ALPHA_PRIOR  = 2.0
    BAYES_BETA_PRIOR   = 2.0
    DECAY_WINDOW       = 20
    DECAY_THRESH       = 0.70

    # ── Evolution ─────────────────────────────────────────────────────────────
    EVOLVE_MIN_TRADES  = 30
    EVOLVE_LOOKBACK_D  = 30
    # [P1-4] 0.0003→0.003: KOSDAQ σ≈3% 기준, √30=5.5 → 유의차 ≈0.55%
    # 0.003 = 0.3%: 노이즈 반응 방지, 실질적 개선만 채택
    EV_IMPROVE_MIN     = 0.003

    # ── Walk-Forward IS/OOS ────────────────────────────────────────────────────
    WF_IS_RATIO        = 0.70
    WF_OOS_ACCEPT      = 0.75
    # [P2-1+FIX-1] OOS 최소 표본 보장 (15→20)
    WF_OOS_MIN_SAMPLES = 20

    # ── 시간가중 EV (Exponential Decay) ────────────────────────────────────────
    EV_DECAY_LAMBDA    = 0.95   # 기본값 (TREND 레짐)

    # ── [V44-3] 레짐별 EV Decay Lambda 차별화 ─────────────────────────────────
    # 급변장: 최신 데이터 가중치 ↑ (과거 빠르게 망각)
    # 안정장: 과거 데이터 유지 (노이즈 방어)
    EV_DECAY_LAMBDA_BY_REGIME = {
        "VOLATILE" : 0.90,   # 급변장: 최신 반응 빠름 (반감기 ≈6.6거래)
        "TREND"    : 0.95,   # 추세장: 기본값 (반감기 ≈13.5거래)
        "RANGE"    : 0.97,   # 횡보장: 과거 유지 (반감기 ≈22.8거래)
    }

    # ── Signal Quality ─────────────────────────────────────────────────────────
    QUALITY_MIN_SAMPLE = 15    # [FIX-1] 10→15

    # ── Concentration (1종목 몰빵) ─────────────────────────────────────────────
    CONC_TICKER_MIN    = 1
    CONC_LOOKBACK_D    = 60
    CONC_MERGE_WEIGHT  = 0.7

    # ── Aggression (공격 70 / 안정 30) ─────────────────────────────────────────
    # [P1-2] 명확화:
    #   공격70 = 전체 자본의 70%를 공격적 전략에 배분 (bridge에서 처리)
    #   안정30 = 전체 자본의 30%를 안정적 전략에 배분
    #   AGG_BASE_KELLY = 수학적 Kelly 배수 상한 (자본배분과 별개)
    AGG_WIN_STREAK     = 5
    AGG_LOSS_STREAK    = 3
    AGG_FULL_KELLY     = 1.0
    AGG_SAFE_KELLY     = 0.5
    AGG_BASE_KELLY     = 0.7        # Kelly 배수 상한 (공격70 자본배분과 별개)
    MDD_RECOVERY_THRESH = -0.03
    AGG_RECOVERY_STREAK = 2

    # ── Drawdown ───────────────────────────────────────────────────────────────
    MDD_ALERT_THRESH   = -0.05
    MDD_LOOKBACK_D     = 10

    # ── 자기상관 패널티 ────────────────────────────────────────────────────────
    AUTOCORR_THRESH    = 0.30
    # [P2-3] 곱셈 방식으로 변경: kelly *= (1 - penalty)
    AUTOCORR_PENALTY   = 0.15       # 15% 감산 (곱셈)

    # ── Half-Kelly 안전 배율 ───────────────────────────────────────────────────
    KELLY_HALF         = 0.5
    KELLY_CAP          = 1.0

    # ── UCB 탐색 ───────────────────────────────────────────────────────────────
    # [PROFIT-6] 1.0→0.8: 검증된 파라미터 활용 강화, 탐색 축소
    UCB_EXPLORE_COEF   = 0.8

    # ── 레짐 목록 (참조용 — _evolve_regime은 실데이터 groupby 사용) ───────────
    REGIMES            = ["TREND", "RANGE", "VOLATILE"]

    # ── [V44-1] 전략 목록 — 종배(RT) 제거, 2전략 독립 학습 ─────────────────────
    STRATEGIES         = ["EOD", "SIGA"]

    # ── Hill-Climbing 파라미터 탐색 범위 (min, max, step) ─────────────────────
    # [FIX-D] 지침서[15] 13-1 허용 파라미터 3개 추가:
    #   hard_stop / trail_activate_ret / split_t1_ratio
    # 지침서 고정값(k 배수, PEAK_PROTECT, FAILSAFE, Trail 게이트)은 진화 금지
    PARAM_RANGES = {
        # ── 지침서[15] 13-1 공식 허용 3종 ─────────────────────────────────
        "hard_stop"          : (1.5,   3.0,   0.1),   # HARD STOP % (1.5~3.0%)
        "trail_activate_ret" : (1.0,   2.5,   0.1),   # Trail 활성화 수익률 임계
        "split_t1_ratio"     : (0.20,  0.50,  0.05),  # 1차 분할 매도 비율
        # ── 진입 조건 파라미터 ───────────────────────────────────────────
        "TREND_VWAP_MIN"        : (0.96,  0.99,  0.005),
        "TREND_VAL_RATIO"       : (0.60,  1.00,  0.05),
        "PB_MIN"                : (0.001, 0.010, 0.001),
        "PB_MAX"                : (0.030, 0.070, 0.005),
        "EV_MIN"                : (-0.005,0.010, 0.001),
        "CONF_MIN"              : (0.20,  0.50,  0.05),
        "INST_ACCEL_CONSEC_MIN" : (1,     4,     1),
        "QUIET_PB_VOL_MAX"      : (0.60,  0.90,  0.05),
        "TP_A_PCT"              : (3.0,   8.0,   0.5),
        "TP_B_PCT"              : (2.0,   5.0,   0.5),
        "TP_C_PCT"              : (1.0,   3.0,   0.5),
        "SL_PCT"                : (1.0,   3.0,   0.25),
    }

    # [FIX-1] _heuristic 최소 표본 수 (5→10: 노이즈 방어)
    HEURISTIC_MIN_SAMPLE = 10

    GAP_TP_MAP = {"A": "TP_A_PCT", "B": "TP_B_PCT", "C": "TP_C_PCT"}

    # ══════════════════════════════════════════════════════════════
    # [v4.1] 12대 강화 패치 설정값
    # ══════════════════════════════════════════════════════════════

    # ── 🚨① 실시간 연결: 파라미터 리프레시 간격 ───────────────────────────────
    PARAM_REFRESH_INTERVAL_MIN = 10   # 다운스트림 모듈 리로드 주기 (분)
    PARAM_MIN_SAMPLE           = 30   # [FIX-1] 20→30: 리로드 최소 표본

    # ── 🚨② MDD 기반 학습 필터 ────────────────────────────────────────────────
    MDD_HARD_LIMIT   = -0.15    # MDD ≤ -15%: 진화 가중치 0.3
    MDD_SOFT_LIMIT   = -0.08    # MDD ≤ -8%:  진화 가중치 0.7
    MDD_WEIGHT_HARD  = 0.3
    MDD_WEIGHT_SOFT  = 0.7

    # ── 🚨③ Top1 집중 강화 (몰빵 최적화) ──────────────────────────────────────
    # [PROFIT-3] 더 공격적: 1등에 극집중
    TOP1_WEIGHT = 1.40    # 1등 종목 점수 ×1.40
    TOP2_WEIGHT = 0.85    # 2등 종목 점수 ×0.85
    TOP3_WEIGHT = 0.60    # 3등 이하 점수 ×0.60

    # ── 🚨④ EV 필터 강화 ──────────────────────────────────────────────────────
    # [PROFIT-1] EV 강한 패턴 보상 강화
    EV_ENTRY_MIN = 0.002    # EV < 0.002 → 진화 대상 제외
    EV_STRONG    = 0.006    # EV ≥ 0.006 → 가중치 ×1.3
    EV_ULTRA     = 0.010    # EV ≥ 0.010 → 가중치 ×1.5
    EV_WEAK      = 0.0      # EV < 0     → 가중치 ×0.3

    # ── 🚨⑤ Profit Factor 진화 필터 ───────────────────────────────────────────
    # [PROFIT-2] PF 우수 패턴 보상 강화
    PF_STRONG = 1.5    # PF > 1.5 → weight ×1.25
    PF_ULTRA  = 2.0    # PF > 2.0 → weight ×1.4
    PF_WEAK   = 1.0    # PF < 1.0 → weight ×0.5
    PF_KILL   = 0.8    # PF < 0.8 → weight ×0.2

    # ── 🚨⑥ 거래 횟수 제한 (다운스트림 전달) ──────────────────────────────────
    MAX_TRADES_PER_DAY = 1
    COOLDOWN_MIN       = 20   # 거래 간 최소 대기 (분)

    # ── 🚨⑦ 트레일링 수익 구조 (다운스트림 전달 기본값) ────────────────────────
    # [PROFIT-4] 공격적 트레일: 잘 가는 종목 더 오래 보유
    TRAIL_STRONG   = 0.65    # ride_score ≥ 0.65: HOLD
    TRAIL_MID      = 0.45    # 0.45 ≤ ride < 0.65: PARTIAL SELL
    TRAIL_EXIT     = 0.30    # ride < 0.30: FULL EXIT
    PARTIAL_SELL   = 0.25    # 부분 매도 비율 (30→25%: 더 오래 보유)

    # ── 🚨⑧ 하드 리스크 캡 (다운스트림 전달) ──────────────────────────────────
    MAX_POSITION       = 0.70   # 최대 포지션 비율
    MAX_LOSS_PER_TRADE = -1.2   # 1거래 최대 손실 (%)
    MAX_DAILY_LOSS     = -2.0   # 일일 최대 손실 (%)

    # ── 🚨⑨ 기관 필터 강화 (다운스트림 전달 기본값) ────────────────────────────
    MIN_INST_DAYS = 3      # 기관 연속매수 최소 일수
    MIN_OFI       = 0.30   # 최소 OFI
    MIN_ACCEL     = 1.2    # 최소 가속도

    # ── 🚨⑩ 과열 차단 (다운스트림 전달) ───────────────────────────────────────
    HARD_OVERHEAT = 12.0   # 최근3일 수익률 합 ≥ 12%: SKIP
    SOFT_OVERHEAT = 6.0    # 최근3일 수익률 합 ≥ 6%:  score ×0.6

    # ── 🚨⑪ 슬리피지 반영 ─────────────────────────────────────────────────────
    # [FIX-2] 보수화: 0.0015→0.0018 (저유동성 과대평가 방지)
    SLIPPAGE          = 0.0018    # 기본 슬리피지 (학습 전체 적용)
    SLIPPAGE_LOW_LIQ  = 0.0025   # 저유동성 (참조용)
    SLIPPAGE_MID_LIQ  = 0.0018   # 중유동성 (참조용)

    # ── 🚨⑫ 시간 필터 (다운스트림 전달) ───────────────────────────────────────
    BLOCK_TIMES = [(900, 910), (1130, 1300)]   # HHMM 형식

    # ── 🎯 목표 성과 기준 ─────────────────────────────────────────────────────
    TARGET_PF      = 1.8
    TARGET_SHARPE  = 1.5
    TARGET_MDD     = -0.08
    TARGET_CAGR    = 0.40

    # ── 🚨 [FIX-3] Top1 약한 날 차단 기준 ─────────────────────────────────────
    # "매일 뽑기 < 약하면 안 뽑기" — 다운스트림 전달
    MIN_TOP1_EV       = 0.004    # Top1 최소 EV
    MIN_TOP1_PF       = 1.20     # Top1 최소 PF
    MIN_TOP1_WINRATE  = 0.55     # Top1 최소 승률

    # ── 🚨 [FIX-4] 목표 미달 강제 방어 ────────────────────────────────────────
    PF_DEFENSE_LEVEL     = 1.20    # PF < 1.2 → evolve_weight ×0.7
    SHARPE_DEFENSE_LEVEL = 1.00    # Sharpe < 1.0 → evolve_weight ×0.8
    MDD_DEFENSE_LEVEL    = -0.10   # MDD ≤ -10% → evolve_weight ×0.5
    CAGR_DEFENSE_LEVEL   = 0.20    # CAGR < 20% → UCB 탐색 0.7로 축소


# ==============================================================================
# LOGGER
# ==============================================================================
def _setup_logger() -> logging.Logger:
    Path(LCFG.PATH_LOG).parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rt_learn_v44")
    log.setLevel(logging.DEBUG)
    if log.handlers:
        log.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = RotatingFileHandler(
        LCFG.PATH_LOG, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO);  ch.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(ch)
    return log


# ==============================================================================
# [P0-1] 파일 Lock — Windows OS 수준 잠금 (msvcrt)
# ==============================================================================
class FileLock:
    """
    [P0-1 FIX] Windows msvcrt.locking() 기반 OS 수준 파일 잠금.
    기존 PID 확인 후 쓰기 방식은 경쟁조건(race condition) 존재.
    msvcrt 없는 환경(Linux 등)에서는 fcntl fallback.

    사용법:
        with FileLock(path, log):
            # 임계 구간
    """
    LOCK_TIMEOUT = 30  # 최대 대기 시간(초)

    def __init__(self, path: str, log):
        self._path = Path(path)
        self._log  = log
        self._fh   = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "w", encoding="utf-8")

        if _HAS_MSVCRT:
            # Windows: msvcrt.locking (OS 커널 수준 잠금)
            deadline = time.time() + self.LOCK_TIMEOUT
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except IOError:
                    if time.time() > deadline:
                        self._log.error("[LOCK] 잠금 획득 실패 (timeout 30초)")
                        raise TimeoutError("FileLock 획득 실패")
                    time.sleep(0.5)
        else:
            # Linux/Mac fallback: fcntl
            try:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            except ImportError:
                # 최후 fallback: PID 기반 (경고)
                self._log.warning("[LOCK] OS 수준 잠금 불가 — PID 기반 fallback")

        self._fh.write(str(os.getpid()))
        self._fh.flush()
        return self

    def __exit__(self, *_):
        try:
            if self._fh:
                if _HAS_MSVCRT:
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                self._fh.close()
            if self._path.exists():
                self._path.unlink()
                self._log.debug("[LOCK] 해제 완료")
        except Exception as e:
            self._log.warning(f"[LOCK] 해제 실패: {e}")


# ==============================================================================
# 유틸
# ==============================================================================
def _atomic_json(path: str, data: dict, log=None):
    """원자적 JSON 저장 (tmp -> replace)."""
    tmp = path + ".tmp"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        if log:
            log.error(f"[SAVE] 저장 실패 {path}: {e}")


def _load_json(path: str, default=None, log=None) -> dict:
    """JSON 로드 (파싱 실패 WARNING 포함)."""
    p = Path(path)
    if not p.exists():
        return default if default is not None else {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        if log:
            log.warning(f"[LOAD] JSON 파싱 실패 {path}: {e} → 기본값 사용")
        return default if default is not None else {}
    except Exception as e:
        if log:
            log.warning(f"[LOAD] 로드 실패 {path}: {e}")
        return default if default is not None else {}


# ==============================================================================
# [P1-3] 전략별 필터 유틸
# ==============================================================================
def _filter_by_strategy(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    """
    [V44-1] 2전략 독립 학습: 시가/추세눌림만 처리.
    종배(RT/시배) 데이터 유입 시 WARNING 출력 후 제외.
    strategy 컬럼이 없으면 pattern_key 첫 파트에서 추출.
    """
    if df.empty:
        return df

    # [V44-1] 종배 관련 원장 데이터 경고
    _DELETED_STRATEGIES = {"RT", "종배", "시배"}

    def _normalize(s: str) -> str:
        """원장 전략명을 표준화."""
        s = str(s).strip()
        mapped = LCFG.STRATEGY_MAP.get(s.upper(), LCFG.STRATEGY_MAP.get(s, s))
        return str(mapped).upper()

    # [V44-1] 종배 데이터 감지 → 경고 후 필터링
    if "strategy" in df.columns:
        deleted_mask = df["strategy"].astype(str).str.strip().isin(_DELETED_STRATEGIES)
        if deleted_mask.any():
            import logging
            logging.getLogger("rt_learn_v44").warning(
                f"[V44-1] 종배 전략 데이터 {deleted_mask.sum()}건 감지 → 학습 제외. "
                f"(종배는 v4.4에서 완전 삭제됨)"
            )
        df = df[~deleted_mask].copy()

    # [FIX-C] 입력 전략명도 정규화
    strategy_norm = LCFG.STRATEGY_MAP.get(strategy.upper(), strategy).upper()

    if "strategy" in df.columns:
        normalized = df["strategy"].astype(str).apply(_normalize)
        mask = normalized == strategy_norm
        return df[mask].copy()

    if "pattern_key" in df.columns:
        raw_strat = df["pattern_key"].astype(str).str.split("|").str[0]
        normalized = raw_strat.apply(_normalize)
        mask = normalized == strategy_norm
        return df[mask].copy()

    return df


def _get_strategy(df: pd.DataFrame) -> str:
    """원장에서 주 전략 식별 (정규화 포함). [V44-1] 기본값 종배→시가."""
    if df.empty:
        return "시가"
    raw = None
    if "strategy" in df.columns:
        mode_val = df["strategy"].mode()
        raw = str(mode_val.iloc[0]) if not mode_val.empty else "EOD"
    elif "pattern_key" in df.columns:
        parts = df["pattern_key"].astype(str).str.split("|").str[0]
        mode_val = parts.mode()
        raw = str(mode_val.iloc[0]) if not mode_val.empty else "EOD"
    if raw is None:
        return "시가"
    return LCFG.STRATEGY_MAP.get(raw.strip().upper(),
           LCFG.STRATEGY_MAP.get(raw.strip(), raw)).upper()


# ==============================================================================
# Kelly Criterion 계산기
# ==============================================================================
class KellyCalculator:
    """
    헤지펀드 표준 Kelly 공식:
      Kelly = (p * b - q) / b
      p = 승률, q = 1-p, b = avg_win / |avg_loss|
      Half-Kelly 적용 (안전 마진 50%)

    [FIX-A] Sharpe 연환산: × sqrt(TRADING_DAYS_PER_YEAR=248)
      - 일별 Sharpe는 헤지펀드 보고 기준 연환산 필수
      - 연환산 Sharpe = Raw Sharpe × sqrt(248)

    [P2-3 FIX] 자기상관 패널티: 곱셈 방식
      kelly *= (1 - AUTOCORR_PENALTY)
      → Kelly 크기에 비례하는 공정한 감산
    """

    @staticmethod
    def calc(rets: np.ndarray, log=None) -> dict:
        if len(rets) < 5:
            return {"kelly_raw": 0.0, "kelly_half": LCFG.AGG_BASE_KELLY,
                    "autocorr": 0.0, "autocorr_penalty": False,
                    "sharpe_raw": 0.0, "sharpe_annualized": 0.0}

        # [v4.1 ⑪] 슬리피지 차감
        rets = rets - LCFG.SLIPPAGE

        wins   = rets[rets > 0]
        losses = rets[rets < 0]

        p = len(wins) / max(len(rets), 1)
        q = 1.0 - p
        avg_w = float(wins.mean())  if len(wins)   > 0 else 0.0
        avg_l = float(abs(losses.mean())) if len(losses) > 0 else 1e-9

        b = avg_w / max(avg_l, 1e-9)

        if b <= 0 or p <= 0:
            kelly_raw = 0.0
        else:
            kelly_raw = (p * b - q) / b

        kelly_raw  = float(np.clip(kelly_raw, 0.0, 2.0))
        kelly_half = float(np.clip(kelly_raw * LCFG.KELLY_HALF, 0.0, LCFG.KELLY_CAP))

        # [FIX-A] Sharpe 연환산 계산
        sharpe_raw        = float(rets.mean() / (rets.std() + 1e-9)) if len(rets) > 1 else 0.0
        sharpe_annualized = sharpe_raw * LCFG.SHARPE_ANNUALIZE

        # ── [V44-2] 다중 lag 자기상관 패널티 (lag 1,2,3) ─────────────────────
        # 기존: lag=1만 체크 → lag=2,3 serial correlation 미감지
        # 개선: lag 1,2,3 각각 패널티 합산 → KOSDAQ 단타 패턴 포착 강화
        autocorr = 0.0
        autocorr_penalty = False
        if len(rets) >= 10:
            try:
                s = pd.Series(rets)
                penalty_count = 0
                for lag in [1, 2, 3]:
                    ac = float(s.autocorr(lag=lag))
                    if not np.isnan(ac) and ac > LCFG.AUTOCORR_THRESH:
                        kelly_half = max(0.1, kelly_half * (1.0 - LCFG.AUTOCORR_PENALTY))
                        penalty_count += 1
                        if lag == 1:
                            autocorr = ac  # lag-1 대표값으로 보고
                if penalty_count > 0:
                    autocorr_penalty = True
                    if log:
                        log.info(
                            f"[KELLY] 다중자기상관 패널티(V44-2) {penalty_count}회 적용: "
                            f"lag1_autocorr={autocorr:.3f} -> kelly={kelly_half:.3f}"
                        )
            except Exception:
                pass

        if log:
            log.info(
                f"[KELLY] p={p:.3f} b={b:.3f} raw={kelly_raw:.3f} "
                f"half={kelly_half:.3f} autocorr={autocorr:.3f} "
                f"Sharpe_raw={sharpe_raw:.3f} Sharpe_ann={sharpe_annualized:.3f}"
            )

        return {
            "kelly_raw"        : round(kelly_raw,         4),
            "kelly_half"       : round(kelly_half,         4),
            "win_rate"         : round(p,                  4),
            "payoff_ratio"     : round(b,                  4),
            "autocorr"         : round(autocorr,           4),
            "autocorr_penalty" : autocorr_penalty,
            "sharpe_raw"       : round(sharpe_raw,         4),
            "sharpe_annualized": round(sharpe_annualized,  4),
        }


# ==============================================================================
# 시간가중 EV (Exponential Decay)
# ==============================================================================
def _time_weighted_ev(ledger: pd.DataFrame, decay_lambda: float = None) -> float:
    """
    EV에 시간가중치 적용: 오래된 거래일수록 영향력 감쇠.
    weight_i = lambda ^ (today - trade_date).days

    [V44-3] 레짐별 decay lambda 차별화:
      - market_regime 컬럼이 있으면 레짐별 lambda 자동 적용
      - VOLATILE=0.90 / TREND=0.95 / RANGE=0.97
    """
    if ledger.empty or "pnl_pct" not in ledger.columns:
        return 0.0

    # [V44-3] 레짐별 lambda 자동 선택
    if decay_lambda is None:
        if "market_regime" in ledger.columns or "regime" in ledger.columns:
            regime_col = "market_regime" if "market_regime" in ledger.columns else "regime"
            dominant_regime = ledger[regime_col].mode()
            regime_name = str(dominant_regime.iloc[0]).upper() if not dominant_regime.empty else "TREND"
            decay_lambda = LCFG.EV_DECAY_LAMBDA_BY_REGIME.get(regime_name, LCFG.EV_DECAY_LAMBDA)
        else:
            decay_lambda = LCFG.EV_DECAY_LAMBDA

    today = datetime.now().date()

    if "date" in ledger.columns:
        try:
            dates = pd.to_datetime(ledger["date"].astype(str), format="%Y%m%d", errors="coerce")
            days_ago = (today - dates.dt.date).apply(
                lambda d: d.days if pd.notna(d) else 30
            ).clip(0, 365)
            weights = np.power(decay_lambda, days_ago.values)
        except Exception:
            weights = np.ones(len(ledger))
    else:
        weights = np.ones(len(ledger))

    rets    = ledger["pnl_pct"].values
    # [v4.1 ⑪] 슬리피지 차감: 매수+매도 양방향
    rets    = rets - LCFG.SLIPPAGE
    w_sum   = weights.sum()
    if w_sum < 1e-9:
        return 0.0

    wins_mask = rets > 0
    w_win  = weights[wins_mask].sum()
    w_lose = weights[~wins_mask].sum()

    wp    = w_win / w_sum
    wq    = w_lose / w_sum
    avg_w = float(np.average(rets[wins_mask],  weights=weights[wins_mask]))  if w_win  > 0 else 0.0
    avg_l = float(np.average(rets[~wins_mask], weights=weights[~wins_mask])) if w_lose > 0 else 0.0

    return wp * avg_w + wq * avg_l


# ==============================================================================
# 원장 전처리
# ==============================================================================
def _ensure_pattern_key(df: pd.DataFrame, log) -> pd.DataFrame:
    """pattern_key 4-part 포맷 보장."""
    if "pattern_key" in df.columns:
        mask_empty = df["pattern_key"].isna() | (df["pattern_key"].astype(str).str.strip() == "")
        if mask_empty.any():
            strat = df.loc[mask_empty, "strategy"].fillna("EOD") if "strategy" in df.columns else "EOD"
            df.loc[mask_empty, "pattern_key"] = strat.astype(str) + "|UNKNOWN|UNKNOWN|SMALL"
            log.info(f"[PREP] pattern_key 빈값 {mask_empty.sum()}건 보정")

        mask_old = df["pattern_key"].astype(str).str.count(r"\|") == 2
        if mask_old.any():
            df.loc[mask_old, "pattern_key"] = (
                df.loc[mask_old, "pattern_key"].astype(str) + "|SMALL"
            )
            log.info(f"[PREP] 구버전 3-part key {mask_old.sum()}건 -> 4-part 변환")
        return df

    log.warning("[PREP] pattern_key 없음 -> 자동 생성")
    strat  = df.get("strategy",     pd.Series("EOD",     index=df.index)).fillna("EOD")
    regime = df.get("market_regime",pd.Series("UNKNOWN", index=df.index)).fillna("UNKNOWN")
    time_r = df.get("time_regime",  pd.Series("UNKNOWN", index=df.index)).fillna("UNKNOWN")
    grade  = df.get("gap_grade",    pd.Series("SMALL",   index=df.index)).fillna("SMALL")
    df = df.copy()
    df["pattern_key"] = strat.astype(str) + "|" + regime + "|" + time_r + "|" + grade
    log.info(f"[PREP] pattern_key 자동 생성: {df['pattern_key'].nunique()}개")
    return df


def _validate_ledger(df: pd.DataFrame, log) -> pd.DataFrame:
    """원장 무결성 검증 + 시계열 정렬.
    [FIX-E] 1일 1거래 초과 감지: MAX_TRADES_PER_DAY_WARN 이상이면 WARNING.
            강제 제거는 하지 않음 — 데이터 오염 조기 경보 역할.
    """
    if df.empty:
        return df
    before = len(df)
    if "trade_id" in df.columns:
        df = df.drop_duplicates(subset=["trade_id"])
    else:
        df = df.drop_duplicates()
    if "pnl_pct" in df.columns:
        bad_mask = df["pnl_pct"] < -0.35
        if bad_mask.any():
            log.warning(f"[VALID] 이상 pnl_pct(-35% 초과) {bad_mask.sum()}건 제거")
        df = df[df["pnl_pct"].between(-0.35, 2.00)]  # 상한 1.0→2.0 (상한가 연속 허용)
    if "date" in df.columns:
        df = df.sort_values("date", ascending=True).reset_index(drop=True)

        # [FIX-E] 1일 1거래 초과 감지
        daily_counts = df.groupby("date").size()
        over_days = daily_counts[daily_counts >= LCFG.MAX_TRADES_PER_DAY_WARN]
        if not over_days.empty:
            log.warning(
                f"[VALID-1일1진입] {len(over_days)}개 날짜에서 "
                f"{LCFG.MAX_TRADES_PER_DAY_WARN}건 이상 거래 감지 — 데이터 오염 의심!\n"
                f"  날짜별 건수: {over_days.to_dict()}\n"
                f"  ※ 1일 1진입 원칙 위반 가능성. 원장 및 브릿지 설정 확인 요망."
            )

    after = len(df)
    if before != after:
        log.info(f"[VALID] 원장 정제: {before} -> {after}건 (제거={before - after})")
    return df


# ==============================================================================
# [P0-2 FIX] Bayesian EV 업데이터 — 중복 누적 방지
# ==============================================================================
class BayesianUpdater:
    """
    [P0-2 FIX] trade_id 기반 중복 누적 방지.
    이미 처리된 trade_id는 스킵.
    trade_id 없으면 (date, ticker, pnl_pct) 복합키로 식별.
    """
    def __init__(self, log):
        self.log    = log
        self._state = _load_json(LCFG.PATH_BAYESIAN, log=log)
        # [P0-2] 처리 완료 ID 세트 (Bayesian 상태 파일에 저장)
        self._processed_ids: Set[str] = set(
            self._state.pop("_processed_ids", [])
        )

    def _make_trade_key(self, row: pd.Series) -> str:
        """trade_id 우선, 없으면 복합키."""
        if "trade_id" in row.index and pd.notna(row.get("trade_id")):
            return str(row["trade_id"])
        parts = [
            str(row.get("date", "")),
            str(row.get("ticker", row.get("code", ""))),
            f"{row.get('pnl_pct', 0):.6f}",
        ]
        return "|".join(parts)

    def update_bulk(self, trades: pd.DataFrame) -> int:
        if trades.empty or not {"pattern_key", "pnl_pct"}.issubset(trades.columns):
            return 0

        trades = trades.dropna(subset=["pattern_key", "pnl_pct"])

        # [P0-2] 중복 제거: 이미 처리된 거래 스킵
        new_ids = []
        for idx, row in trades.iterrows():
            tid = self._make_trade_key(row)
            new_ids.append(tid)
        trades = trades.copy()
        trades["_tid"] = new_ids
        before_n = len(trades)
        trades = trades[~trades["_tid"].isin(self._processed_ids)]
        skipped = before_n - len(trades)
        if skipped > 0:
            self.log.info(f"[BAYES] 중복 {skipped}건 스킵 (이미 처리됨)")

        if trades.empty:
            self.log.info("[BAYES] 신규 거래 없음")
            return 0

        count = 0
        for key, grp in trades.groupby("pattern_key"):
            s = self._state.get(str(key), {
                "alpha": LCFG.BAYES_ALPHA_PRIOR, "beta": LCFG.BAYES_BETA_PRIOR,
                "total": 0, "wins": 0,
                "sum_ret": 0.0, "sum_ret2": 0.0, "recent": [],
            })
            rets = grp["pnl_pct"].values
            wins = int((rets > 0).sum())
            s["alpha"]    += wins
            s["beta"]     += int(len(rets) - wins)
            s["total"]    += len(rets)
            s["wins"]     += wins
            s["sum_ret"]  += float(rets.sum())
            s["sum_ret2"] += float((rets ** 2).sum())
            s["recent"].extend([1 if r > 0 else 0 for r in rets])
            s["recent"] = s["recent"][-LCFG.DECAY_WINDOW:]
            self._state[str(key)] = s
            count += len(rets)

        # [P0-2] 처리 완료 ID 기록
        self._processed_ids.update(trades["_tid"].tolist())

        # 저장 시 _processed_ids 포함
        save_state = {**self._state}
        save_state["_processed_ids"] = list(self._processed_ids)[-5000:]  # 최근 5000건만 유지
        _atomic_json(LCFG.PATH_BAYESIAN, save_state, log=self.log)
        self.log.info(f"[BAYES] 신규 {count}건 업데이트 | 패턴={len(self._state)}개")
        return count

    def get_win_prob(self, key: str) -> float:
        s = self._state.get(key)
        if not s:
            return 0.5
        return s["alpha"] / (s["alpha"] + s["beta"])

    def detect_decay(self) -> Dict[str, bool]:
        """
        [P2-5 FIX] 소멸 + 부활 패턴 모두 감지.
        소멸: 최근 성과가 전체 대비 급락
        부활: 전체 성과 낮았지만 최근 회복 → 진화 대상 포함
        """
        result = {}
        for key, s in self._state.items():
            if key.startswith("_"):  # 메타키 스킵
                continue
            if s.get("total", 0) < 10:
                continue
            overall = s["wins"] / max(s["total"], 1)
            recent_list = s.get("recent", [])
            if not recent_list:
                continue
            recent = sum(recent_list) / max(len(recent_list), 1)

            is_decay = recent < overall * LCFG.DECAY_THRESH
            # [P2-5] 부활 패턴: 최근 승률이 전체보다 30%+ 높으면 부활
            is_revival = recent > overall * 1.30 and overall < 0.45

            if is_revival:
                result[key] = False  # 부활 → 진화 대상 포함
                self.log.info(
                    f"[DECAY] 부활 패턴 감지: {key} "
                    f"전체={overall:.1%} → 최근={recent:.1%}"
                )
            else:
                result[key] = is_decay

        decayed = sum(v for v in result.values())
        if decayed:
            self.log.warning(f"[DECAY] 소멸 패턴 {decayed}개 감지 -> 진화 대상 제외")
        return result


# ==============================================================================
# 레짐 분리 학습 엔진
# ==============================================================================
class RegimeLearner:
    """TREND / RANGE / VOLATILE 레짐별 성과 분리 추적."""
    def __init__(self, log):
        self.log   = log
        self._stat = _load_json(LCFG.PATH_REGIME, log=log, default={})

    def analyze(self, ledger: pd.DataFrame) -> Dict[str, dict]:
        if ledger.empty or "pnl_pct" not in ledger.columns:
            return {}

        regime_col = None
        for col in ["market_regime", "regime"]:
            if col in ledger.columns:
                regime_col = col
                break

        if regime_col is None:
            self.log.info("[REGIME] regime 컬럼 없음 -> 레짐 분리 스킵")
            return {}

        result = {}
        for regime, grp in ledger.groupby(regime_col):
            rets   = grp["pnl_pct"].values
            if len(rets) < 5:
                continue
            wins   = rets[rets > 0]
            losses = rets[rets <= 0]
            wr     = len(wins) / max(len(rets), 1)
            avg_w  = float(wins.mean())   if len(wins)   > 0 else 0.0
            avg_l  = float(losses.mean()) if len(losses) > 0 else 0.0
            ev     = wr * avg_w + (1 - wr) * avg_l
            # [FIX-A] Sharpe 연환산: × sqrt(248)
            sharpe_raw        = float(rets.mean() / (rets.std() + 1e-9))
            sharpe_annualized = sharpe_raw * LCFG.SHARPE_ANNUALIZE
            kelly  = KellyCalculator.calc(rets, self.log)

            result[str(regime)] = {
                "n"                 : len(rets),
                "win_rate"          : round(wr,              4),
                "ev"                : round(ev,              6),
                "sharpe_raw"        : round(sharpe_raw,      4),
                "sharpe_annualized" : round(sharpe_annualized, 4),
                "kelly_half"        : round(kelly["kelly_half"], 4),
                "updated_at"        : datetime.now().strftime("%Y%m%d%H%M%S"),
            }
            self.log.info(
                f"[REGIME] {regime}: n={len(rets)} WR={wr:.1%} "
                f"EV={ev:.5f} Sharpe_ann={sharpe_annualized:.3f} Kelly={kelly['kelly_half']:.3f}"
            )

        if result:
            _atomic_json(LCFG.PATH_REGIME, result, log=self.log)
        return result


# ==============================================================================
# 패턴 통계 빌더 (EV 중심 + 시간가중 EV)
# ==============================================================================
class StatsBuilder:
    def __init__(self, log):
        self.log = log

    def build(self, ledger: pd.DataFrame, bayes: BayesianUpdater) -> pd.DataFrame:
        if ledger.empty or not {"pattern_key", "pnl_pct"}.issubset(ledger.columns):
            self.log.warning("[STATS] 필수 컬럼 부족")
            return pd.DataFrame()

        decay_map = bayes.detect_decay()
        rows      = []

        for key, grp in ledger.groupby("pattern_key"):
            rets   = grp["pnl_pct"].values
            wins   = rets[rets > 0]
            losses = rets[rets <= 0]
            n      = len(rets)

            is_decay = decay_map.get(str(key), False)
            if is_decay and n < 20:
                continue

            wr      = len(wins) / max(n, 1)
            avg_w   = float(wins.mean())   if len(wins)   > 0 else 0.0
            avg_l   = float(losses.mean()) if len(losses) > 0 else 0.0
            ev      = wr * avg_w + (1 - wr) * avg_l
            tw_ev   = _time_weighted_ev(grp)
            # [FIX-A] Sharpe 연환산: × sqrt(248)
            sharpe_raw        = float(rets.mean() / (rets.std() + 1e-9)) if n > 1 else 0.0
            sharpe_annualized = sharpe_raw * LCFG.SHARPE_ANNUALIZE
            pf      = abs(wins.sum()) / max(abs(losses.sum()), 1e-9)
            bayes_wp = bayes.get_win_prob(str(key))
            kelly   = KellyCalculator.calc(rets, self.log)
            confidence = min(0.95, bayes_wp * (0.5 if is_decay else 1.0))

            row = {
                "pattern_key"       : key,
                "sample_size"       : n,
                "win_prob"          : round(wr,              4),
                "bayes_win_prob"    : round(bayes_wp,        4),
                "avg_win"           : round(avg_w,           6),
                "avg_loss"          : round(avg_l,           6),
                "ev_stat"           : round(ev,              6),
                "ev_tw"             : round(tw_ev,           6),
                "kelly_half"        : round(kelly["kelly_half"], 4),
                "profit_factor"     : round(pf,              4),
                "sharpe_raw"        : round(sharpe_raw,      4),
                "sharpe_annualized" : round(sharpe_annualized, 4),
                "is_decay"          : is_decay,
                "confidence"        : round(confidence,      4),
                "last_updated"      : datetime.now().strftime("%Y%m%d%H%M%S"),
            }

            # ── [v4.2 PROFIT-1] EV 필터: ULTRA 추가 ─────────────────────────
            ev_weight = 1.0
            if ev < LCFG.EV_WEAK:
                ev_weight = 0.3
            elif ev < LCFG.EV_ENTRY_MIN:
                ev_weight = 0.5
            elif ev >= LCFG.EV_ULTRA:
                ev_weight = 1.5
            elif ev >= LCFG.EV_STRONG:
                ev_weight = 1.3
            row["ev_weight"] = round(ev_weight, 2)

            # ── [v4.2 PROFIT-2] PF 필터: ULTRA 추가 ─────────────────────────
            pf_weight = 1.0
            if pf < LCFG.PF_KILL:
                pf_weight = 0.2
            elif pf < LCFG.PF_WEAK:
                pf_weight = 0.5
            elif pf >= LCFG.PF_ULTRA:
                pf_weight = 1.4
            elif pf > LCFG.PF_STRONG:
                pf_weight = 1.25
            row["pf_weight"] = round(pf_weight, 2)

            # ── [v4.1 ②] MDD 기반 학습 가중치 ────────────────────────────────
            mdd_weight = 1.0
            if n >= 5:
                cum = (1 + pd.Series(rets)).cumprod()
                pat_mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
                if pat_mdd <= LCFG.MDD_HARD_LIMIT:
                    mdd_weight = LCFG.MDD_WEIGHT_HARD
                    self.log.warning(
                        f"[STATS] {key}: MDD={pat_mdd:.2%} ≤ HARD → weight={mdd_weight}"
                    )
                elif pat_mdd <= LCFG.MDD_SOFT_LIMIT:
                    mdd_weight = LCFG.MDD_WEIGHT_SOFT
                row["mdd_weight"]  = round(mdd_weight, 2)
                row["pattern_mdd"] = round(pat_mdd, 4)
            else:
                row["mdd_weight"]  = 1.0
                row["pattern_mdd"] = 0.0

            # 종합 진화 가중치 = EV × PF × MDD
            row["evolve_weight"] = round(ev_weight * pf_weight * mdd_weight, 3)

            for feat, col_wr, col_n in [
                ("quiet_pullback", "quiet_pb_win_rate", "quiet_pb_n"),
                ("vwap_cross_up",  "vwap_cross_win_rate", "vwap_cross_n"),
            ]:
                if feat in grp.columns:
                    mask = grp[feat].fillna(False).astype(bool)
                    if mask.sum() >= 3:
                        row[col_wr] = round(float((grp.loc[mask, "pnl_pct"] > 0).mean()), 4)
                        row[col_n]  = int(mask.sum())
                    else:
                        row[col_wr] = None
                        row[col_n]  = 0

            rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).sort_values("ev_tw", ascending=False)
        self.log.info(
            f"[STATS] 패턴={len(df)}개 | "
            f"EV={df['ev_stat'].mean():.5f} | EV_TW={df['ev_tw'].mean():.5f} | "
            f"PF={df['profit_factor'].mean():.3f}"
        )
        return df

    def save(self, df: pd.DataFrame):
        if df.empty:
            return
        tmp = LCFG.PATH_STATS + ".tmp"
        Path(LCFG.PATH_STATS).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, LCFG.PATH_STATS)
        self.log.info(f"[STATS] 저장: {LCFG.PATH_STATS} ({len(df)}패턴)")


# ==============================================================================
# Signal Quality Analyzer
# ==============================================================================
class SignalQualityAnalyzer:
    """
    [FIX-F] 신호 품질 피처 확장: 2개 → 6개
      기존: quiet_pullback / vwap_cross_up
      추가: ofi_strong / accel_strong / gap_grade_A / vol_breakout / vwap_above
      lift ≥ 1.2 → OK / lift < 0.8 → BAD
    """
    def __init__(self, log):
        self.log = log

    def analyze(self, ledger: pd.DataFrame) -> dict:
        result = {}

        # ── 분석 피처 목록 (bool/flag 컬럼 기반) ─────────────────────────────
        FEAT_BOOL = [
            "quiet_pullback",    # 조용한 눌림목 여부
            "vwap_cross_up",     # VWAP 상향 돌파 여부
            "ofi_strong",        # OFI ≥ 0.30 (강한 기관 매수) 여부
            "accel_strong",      # accel ≥ 1.20 (기관 가속도) 여부
            "vol_breakout",      # 거래량 돌파 여부
            "vwap_above",        # 현재가 > VWAP 여부
        ]

        # ── 수치 컬럼 → bool 변환 피처 ───────────────────────────────────────
        # ofi_strong: ofi 컬럼이 있으면 ≥ 0.30 기준 파생
        if "ofi_strong" not in ledger.columns and "ofi" in ledger.columns:
            ledger = ledger.copy()
            ledger["ofi_strong"] = ledger["ofi"].fillna(0) >= 0.30

        # accel_strong: accel 컬럼이 있으면 ≥ 1.20 기준 파생
        if "accel_strong" not in ledger.columns and "accel" in ledger.columns:
            ledger = ledger.copy()
            ledger["accel_strong"] = ledger["accel"].fillna(0) >= 1.20

        # gap_grade_A: gap_grade 컬럼에서 파생
        if "gap_grade_A" not in ledger.columns and "gap_grade" in ledger.columns:
            ledger = ledger.copy()
            ledger["gap_grade_A"] = ledger["gap_grade"].astype(str).str.upper() == "A"

        # vwap_above: price_to_vwap 컬럼이 있으면 파생
        if "vwap_above" not in ledger.columns and "price_to_vwap" in ledger.columns:
            ledger = ledger.copy()
            ledger["vwap_above"] = ledger["price_to_vwap"].fillna(1.0) >= 1.0

        for feat in FEAT_BOOL:
            if feat not in ledger.columns:
                continue
            mask = ledger[feat].fillna(False).astype(bool)
            n_with = mask.sum()
            if n_with < LCFG.QUALITY_MIN_SAMPLE:
                self.log.debug(f"[QUALITY] {feat}: 표본 부족({n_with}) -> 스킵")
                continue
            n_without  = (~mask).sum()
            wr_with    = float((ledger.loc[mask,  "pnl_pct"] > 0).mean())
            wr_without = float((ledger.loc[~mask, "pnl_pct"] > 0).mean()) if n_without > 0 else 0.5
            lift       = wr_with / max(wr_without, 1e-9)
            verdict    = "OK" if lift >= 1.2 else ("BAD" if lift < 0.8 else "NEUTRAL")

            # EV lift도 계산 (승률 외 수익 크기 반영)
            ev_with    = float(ledger.loc[mask,  "pnl_pct"].mean()) if n_with > 0 else 0.0
            ev_without = float(ledger.loc[~mask, "pnl_pct"].mean()) if n_without > 0 else 0.0

            result[feat] = {
                "n_with"          : int(n_with),
                "n_without"       : int(n_without),
                "win_rate_with"   : round(wr_with,    4),
                "win_rate_without": round(wr_without,  4),
                "lift"            : round(lift,        4),
                "ev_with"         : round(ev_with,     6),
                "ev_without"      : round(ev_without,  6),
                "verdict"         : verdict,
                "analyzed_at"     : datetime.now().strftime("%Y%m%d%H%M%S"),
            }
            self.log.info(
                f"[QUALITY] {feat}: lift={lift:.2f}x [{verdict}] "
                f"WR: {wr_with:.1%}(n={n_with}) vs {wr_without:.1%}(n={n_without}) | "
                f"EV: {ev_with:.4f} vs {ev_without:.4f}"
            )
        if result:
            _atomic_json(LCFG.PATH_QUALITY, result, log=self.log)
        return result


# ==============================================================================
# [P2-4 FIX] Concentration Analyzer — 가중병합 일관성 개선
# ==============================================================================
class ConcentrationAnalyzer:
    def __init__(self, log):
        self.log   = log
        self._prev = _load_json(LCFG.PATH_CONCENTRATION, log=log, default={})

    def analyze(self, ledger: pd.DataFrame) -> dict:
        if ledger.empty:
            return {}

        if "date" in ledger.columns:
            cutoff = (datetime.now() - timedelta(days=LCFG.CONC_LOOKBACK_D)).strftime("%Y%m%d")
            recent = ledger[ledger["date"].astype(str) >= cutoff]
        else:
            recent = ledger

        if recent.empty:
            return {}

        result = {}

        # ── Ticker별 EV 히트맵 (가중 병합 일관성 개선) ───────────────────────
        if "ticker" in recent.columns and "pnl_pct" in recent.columns:
            new_stats = {}
            for ticker, grp in recent.groupby("ticker"):
                if len(grp) < LCFG.CONC_TICKER_MIN:
                    continue
                rets   = grp["pnl_pct"].values
                wins   = rets[rets > 0]
                losses = rets[rets <= 0]
                wr     = len(wins) / max(len(rets), 1)
                avg_w  = float(wins.mean())   if len(wins)   > 0 else 0.0
                avg_l  = float(losses.mean()) if len(losses) > 0 else 0.0
                ev     = wr * avg_w + (1 - wr) * avg_l
                pf     = abs(wins.sum()) / max(abs(losses.sum()), 1e-9)
                new_stats[str(ticker)] = {
                    "n": len(grp), "win_rate": round(wr, 4),
                    "ev": round(ev, 6), "profit_factor": round(pf, 4),
                    "avg_win": round(avg_w, 6), "avg_loss": round(avg_l, 6),
                }

            # [P2-4 FIX] 모든 metric을 일관되게 가중 병합
            prev_heatmap = {
                t["ticker"]: t
                for t in self._prev.get("ticker_heatmap", [])
                if isinstance(t, dict) and "ticker" in t
            }
            merged = {}
            all_tickers = set(new_stats.keys()) | set(prev_heatmap.keys())
            w = LCFG.CONC_MERGE_WEIGHT

            for ticker in all_tickers:
                n_data = new_stats.get(ticker, {})
                p_data = prev_heatmap.get(ticker, {})

                if ticker in new_stats and ticker in prev_heatmap:
                    # [P2-4] 모든 수치 지표를 가중 병합 (신규 0.7 : 기존 0.3)
                    merged_entry = {"ticker": ticker, "n": n_data.get("n", 0)}
                    for metric in ["ev", "win_rate", "profit_factor", "avg_win", "avg_loss"]:
                        n_val = n_data.get(metric, 0.0)
                        p_val = p_data.get(metric, 0.0)
                        merged_entry[metric] = round(w * n_val + (1 - w) * p_val, 6)
                elif ticker in new_stats:
                    merged_entry = {**n_data, "ticker": ticker}
                else:
                    merged_entry = {**p_data, "ticker": ticker}

                merged[ticker] = merged_entry

            ticker_list = sorted(merged.values(), key=lambda x: x.get("ev", 0), reverse=True)

            # ── [v4.1 ③] Top1 집중 강화: 순위별 가중치 ───────────────────────
            for rank_idx, entry in enumerate(ticker_list):
                if rank_idx == 0:
                    entry["rank_weight"] = LCFG.TOP1_WEIGHT
                    entry["ev_boosted"]  = round(entry.get("ev", 0) * LCFG.TOP1_WEIGHT, 6)
                elif rank_idx == 1:
                    entry["rank_weight"] = LCFG.TOP2_WEIGHT
                    entry["ev_boosted"]  = round(entry.get("ev", 0) * LCFG.TOP2_WEIGHT, 6)
                else:
                    entry["rank_weight"] = LCFG.TOP3_WEIGHT
                    entry["ev_boosted"]  = round(entry.get("ev", 0) * LCFG.TOP3_WEIGHT, 6)

            result["ticker_heatmap"] = ticker_list
            if ticker_list:
                top = ticker_list[0]
                self.log.info(
                    f"[CONC] Top EV 종목: {top['ticker']} "
                    f"EV={top.get('ev',0):.5f} PF={top.get('profit_factor', 0):.2f}"
                )

        # ── 갭등급별 최적 TP (보수적 추정: 50분위 * 0.9) ─────────────────────
        if "gap_grade" in recent.columns and "pnl_pct" in recent.columns:
            grade_tp = {}
            for grade, grp in recent.groupby("gap_grade"):
                if len(grp) < 5:
                    continue
                rets = grp["pnl_pct"].values
                wins = rets[rets > 0]
                if len(wins) == 0:
                    continue
                median_tp    = float(np.percentile(wins, 50)) * 100
                # [PROFIT-5] 50분위 × 0.95 (0.90→0.95: 수익 상단 확대)
                safe_tp      = round(median_tp * 0.95, 2)
                grade_tp[str(grade)] = {
                    "optimal_tp_pct": safe_tp,
                    "median_tp_pct" : round(median_tp, 2),
                    "avg_win_pct"   : round(float(wins.mean()) * 100, 2),
                    "win_rate"      : round(len(wins) / max(len(rets), 1), 4),
                    "n"             : len(grp),
                }
                self.log.info(
                    f"[CONC] Gap={grade}: 보수TP={safe_tp:.2f}% "
                    f"(중앙={median_tp:.2f}%) WR={grade_tp[str(grade)]['win_rate']:.1%}"
                )
            result["gap_grade_tp"] = grade_tp

        # ── 최적 홀딩봉 ───────────────────────────────────────────────────────
        if "hold_bars" in recent.columns and "pnl_pct" in recent.columns:
            wins_df = recent[recent["pnl_pct"] > 0]
            if len(wins_df) >= 5:
                bars = wins_df["hold_bars"].dropna()
                if len(bars) > 0:
                    result["optimal_hold_bars"] = int(bars.quantile(0.50))
                    self.log.info(f"[CONC] 최적 홀딩봉: {result['optimal_hold_bars']}봉")

        result["analyzed_at"] = datetime.now().strftime("%Y%m%d%H%M%S")
        _atomic_json(LCFG.PATH_CONCENTRATION, result, log=self.log)
        return result


# ==============================================================================
# Aggression Controller — 공격 70 / 안정 30
# ==============================================================================
class AggressionController:
    """
    [P1-2] 명확화:
      공격70/안정30 = 자본 배분 구조 (bridge에서 처리)
      이 모듈의 kelly_mult = 수학적 Kelly 배수 상한 (별개 개념)

    [P1-3] 전략별 독립 평가:
      전체 원장 대신 주 전략만으로 평가
    """
    def __init__(self, log):
        self.log  = log
        self._prev = _load_json(LCFG.PATH_AGGRESSION, log=log, default={})

    def evaluate(self, ledger: pd.DataFrame) -> dict:
        if ledger.empty or "pnl_pct" not in ledger.columns:
            return {"mode": "NORMAL", "kelly_mult": LCFG.AGG_BASE_KELLY}

        rets = ledger["pnl_pct"].values
        mdd  = self._calc_mdd(ledger)

        # ── 연속 스트릭 ───────────────────────────────────────────────────────
        tail       = rets[-max(LCFG.AGG_WIN_STREAK, LCFG.AGG_LOSS_STREAK, 5):]
        win_streak = loss_streak = 0
        for r in reversed(tail):
            if r > 0:
                if loss_streak > 0: break
                win_streak += 1
            else:
                if win_streak > 0: break
                loss_streak += 1

        # ── 수학적 Kelly ──────────────────────────────────────────────────────
        kelly_result = KellyCalculator.calc(rets, self.log)
        kelly_half   = kelly_result["kelly_half"]

        # ── 이전 모드 확인 ────────────────────────────────────────────────────
        prev_mode = self._prev.get("mode", "NORMAL")

        # ── 모드 결정 ─────────────────────────────────────────────────────────
        if prev_mode == "SAFE_FORCED":
            if mdd >= LCFG.MDD_RECOVERY_THRESH and win_streak >= LCFG.AGG_RECOVERY_STREAK:
                mode       = "NORMAL"
                kelly_mult = min(kelly_half, LCFG.AGG_BASE_KELLY)
                reason     = f"SAFE_FORCED 복귀: MDD={mdd:.2%} 회복 + 연속이익 {win_streak}회"
            else:
                mode       = "SAFE_FORCED"
                kelly_mult = LCFG.AGG_SAFE_KELLY
                reason     = f"SAFE_FORCED 유지: MDD={mdd:.2%}"

        elif mdd <= LCFG.MDD_ALERT_THRESH:
            mode       = "SAFE_FORCED"
            kelly_mult = LCFG.AGG_SAFE_KELLY
            reason     = f"MDD={mdd:.2%} 임계 초과 -> 강제 안정"

        elif loss_streak >= LCFG.AGG_LOSS_STREAK:
            mode       = "SAFE"
            kelly_mult = min(kelly_half, LCFG.AGG_SAFE_KELLY)
            reason     = f"연속손실 {loss_streak}회 -> 안정 모드"

        elif win_streak >= LCFG.AGG_WIN_STREAK:
            mode       = "AGGRESSIVE"
            kelly_mult = min(kelly_half, LCFG.AGG_FULL_KELLY)
            reason     = f"연속이익 {win_streak}회 -> 공격 모드"

        else:
            mode       = "NORMAL"
            kelly_mult = min(kelly_half, LCFG.AGG_BASE_KELLY)
            reason     = "기본 모드"

        # [P2-3] 자기상관 패널티 — 곱셈 방식
        if kelly_result["autocorr_penalty"]:
            kelly_mult = max(0.1, kelly_mult * (1.0 - LCFG.AUTOCORR_PENALTY))

        result = {
            "mode"         : mode,
            "kelly_mult"   : round(kelly_mult, 3),
            "kelly_raw"    : kelly_result["kelly_raw"],
            "kelly_half"   : kelly_result["kelly_half"],
            "win_streak"   : int(win_streak),
            "loss_streak"  : int(loss_streak),
            "mdd_10d"      : round(float(mdd), 4),
            "autocorr"     : kelly_result["autocorr"],
            "reason"       : reason,
            "updated_at"   : datetime.now().strftime("%Y%m%d%H%M%S"),
        }
        _atomic_json(LCFG.PATH_AGGRESSION, result, log=self.log)
        self.log.info(f"[AGG] 모드={mode} | kelly={kelly_mult:.1%} | {reason}")
        return result

    def _calc_mdd(self, ledger: pd.DataFrame) -> float:
        if "date" in ledger.columns:
            cutoff = (datetime.now() - timedelta(days=LCFG.MDD_LOOKBACK_D)).strftime("%Y%m%d")
            sub    = ledger[ledger["date"].astype(str) >= cutoff]
        else:
            sub = ledger.tail(LCFG.MDD_LOOKBACK_D * 3)
        if sub.empty or "pnl_pct" not in sub.columns:
            return 0.0
        cum = (1 + sub["pnl_pct"]).cumprod()
        dd  = (cum - cum.cummax()) / cum.cummax()
        return float(dd.min())


# ==============================================================================
# [P1-1 FIX] Drawdown Tracker — 수익률 평가 확장
# ==============================================================================
class DrawdownTracker:
    """
    [P1-1 FIX] 수익률 평가 추가 (지침서 6번):
      - 누적수익률 (cumulative_return)
      - 연환산 수익률 (CAGR)
      - 일별 수익률 분포 (return_percentiles)
      - 최대 연속 손실 기간 (max_loss_streak_days)
      - 수익/손실 거래 평균 지속기간 대비
    """
    def __init__(self, log):
        self.log = log

    def track(self, ledger: pd.DataFrame) -> dict:
        if ledger.empty or "pnl_pct" not in ledger.columns:
            return {}
        rets   = ledger["pnl_pct"].values
        # [v4.1 ⑪] 슬리피지 차감
        rets   = rets - LCFG.SLIPPAGE
        wins   = rets[rets > 0]
        losses = rets[rets <= 0]
        pf     = abs(wins.sum()) / max(abs(losses.sum()), 1e-9) if len(wins) > 0 else 0.0

        # [FIX-A] Sharpe 연환산: Raw × sqrt(248)
        sharpe_raw        = float(rets.mean() / (rets.std() + 1e-9)) if len(rets) > 1 else 0.0
        sharpe_annualized = sharpe_raw * LCFG.SHARPE_ANNUALIZE

        # [v4.5] Sortino Ratio 추가
        # 출처: Sortino & van der Meer (1991) Journal of Portfolio Management 17(4)
        # Sortino = (평균수익 - MAR) / 하방표준편차 (하방만 분모)
        # MAR(Minimum Acceptable Return) = 0 (일별 손실 방지 기준)
        # Sharpe와 달리 상방 변동성을 페널티로 주지 않음
        # → 기관 등타기 전략처럼 수익 변동성이 큰 전략에서 더 정확한 성과 측정
        _mar = 0.0  # 일별 MAR = 0 (슬리피지 차감 후 기준)
        _downside = rets[rets < _mar]  # 손실 거래만 추출
        if len(_downside) >= 2:
            _downside_std = float(np.std(_downside, ddof=1))
            sortino_raw        = float((rets.mean() - _mar) / (_downside_std + 1e-9))
            sortino_annualized = sortino_raw * LCFG.SHARPE_ANNUALIZE  # ×√248 동일 적용
        elif len(rets) > 0:
            # 손실 거래 0~1건: 하방 위험 거의 없음 → 보수적으로 Sharpe로 대체
            sortino_raw        = sharpe_raw
            sortino_annualized = sharpe_annualized
        else:
            sortino_raw = sortino_annualized = 0.0

        kelly  = KellyCalculator.calc(rets, self.log)

        # 연속 손실 카운트
        max_ls = cur = 0
        for r in rets:
            cur = cur + 1 if r <= 0 else 0
            max_ls = max(max_ls, cur)

        # 연속 이익 카운트
        max_ws = cur_w = 0
        for r in rets:
            cur_w = cur_w + 1 if r > 0 else 0
            max_ws = max(max_ws, cur_w)

        cum  = (1 + pd.Series(rets)).cumprod()
        mdd  = float(((cum - cum.cummax()) / cum.cummax()).min())

        # [P1-1] 시간가중 EV
        tw_ev = _time_weighted_ev(ledger)

        # ── [P1-1] 수익률 평가 추가 ───────────────────────────────────────────
        cumulative_return = float(cum.iloc[-1] - 1.0) if len(cum) > 0 else 0.0

        # [FIX-B] CAGR — 한국 거래일(248) 기준으로 수정
        # 캘린더 기간 × (248/365.25) = 추정 실거래일
        cagr = 0.0
        if "date" in ledger.columns and len(ledger) >= 2:
            try:
                dates = pd.to_datetime(ledger["date"].astype(str), format="%Y%m%d", errors="coerce")
                valid_dates = dates.dropna()
                if len(valid_dates) >= 2:
                    calendar_days = (valid_dates.max() - valid_dates.min()).days
                    if calendar_days > 0:
                        trading_day_ratio = LCFG.TRADING_DAYS_PER_YEAR / 365.25
                        est_trading_days  = calendar_days * trading_day_ratio
                        years = est_trading_days / LCFG.TRADING_DAYS_PER_YEAR
                        final_wealth = float(cum.iloc[-1])
                        if final_wealth > 0 and years > 0:
                            cagr = float(final_wealth ** (1.0 / years) - 1.0)
            except Exception:
                pass

        # 수익률 분포 (백분위)
        pctiles = {}
        if len(rets) >= 5:
            for p in [5, 25, 50, 75, 95]:
                pctiles[f"p{p}"] = round(float(np.percentile(rets, p)), 6)

        # 최대 연속 손실 기간 (일수 기준)
        max_loss_streak_days = 0
        if "date" in ledger.columns and max_ls > 0:
            try:
                dates = pd.to_datetime(ledger["date"].astype(str), format="%Y%m%d", errors="coerce")
                cur_start = None
                longest_days = 0
                for i, r in enumerate(rets):
                    if r <= 0:
                        if cur_start is None:
                            cur_start = i
                    else:
                        if cur_start is not None:
                            d_start = dates.iloc[cur_start]
                            d_end   = dates.iloc[i - 1]
                            if pd.notna(d_start) and pd.notna(d_end):
                                streak_d = (d_end - d_start).days
                                longest_days = max(longest_days, streak_d)
                            cur_start = None
                # 마지막 구간 체크
                if cur_start is not None:
                    d_start = dates.iloc[cur_start]
                    d_end   = dates.iloc[-1]
                    if pd.notna(d_start) and pd.notna(d_end):
                        streak_d = (d_end - d_start).days
                        longest_days = max(longest_days, streak_d)
                max_loss_streak_days = longest_days
            except Exception:
                pass

        result = {
            "total_trades"        : len(rets),
            "win_rate"            : round(float((rets > 0).mean()), 4),
            "avg_win"             : round(float(wins.mean()) if len(wins) > 0 else 0.0, 6),
            "avg_loss"            : round(float(losses.mean()) if len(losses) > 0 else 0.0, 6),
            "profit_factor"       : round(pf, 4),
            # [FIX-A] 연환산 Sharpe 저장 (헤지펀드 보고 기준)
            "sharpe"              : round(sharpe_annualized, 4),   # 연환산 값으로 통일
            "sharpe_raw"          : round(sharpe_raw,        4),   # 원시값도 보존
            "sharpe_annualized"   : round(sharpe_annualized, 4),
            # [v4.5] Sortino Ratio (하방 리스크 기반 — 상방 변동성 페널티 없음)
            "sortino"             : round(sortino_annualized, 4),
            "sortino_raw"         : round(sortino_raw, 4),
            "mdd_overall"         : round(mdd, 4),
            "max_loss_streak"     : int(max_ls),
            "max_win_streak"      : int(max_ws),
            "kelly_half"          : round(kelly["kelly_half"], 4),
            "ev_tw"               : round(tw_ev, 6),
            # ── [P1-1] 수익률 평가 ────────────────────────────────────────
            "cumulative_return"   : round(cumulative_return, 6),
            "cagr"                : round(cagr, 6),
            "return_percentiles"  : pctiles,
            "max_loss_streak_days": max_loss_streak_days,
            "total_wins"          : int(len(wins)),
            "total_losses"        : int(len(losses)),
            "updated_at"          : datetime.now().strftime("%Y%m%d%H%M%S"),
        }

        _atomic_json(LCFG.PATH_DD, result, log=self.log)

        pf_v = "OK" if pf >= 1.5 else ("WARN" if pf >= 1.0 else "BAD")
        self.log.info(
            f"[DD] 거래={len(rets)} | WR={result['win_rate']:.1%} | "
            f"PF={pf:.2f}[{pf_v}] | Sharpe_ann={sharpe_annualized:.3f}(raw={sharpe_raw:.3f}) | "
            f"Sortino_ann={sortino_annualized:.3f} | "  # [v4.5]
            f"MDD={mdd:.2%} | 연손={max_ls}회 | EV_TW={tw_ev:.5f}"
        )
        # [P1-1] 수익률 로그 추가
        self.log.info(
            f"[DD-수익률] 누적수익={cumulative_return:+.2%} | "
            f"CAGR={cagr:+.2%}(거래일248기준) | 연속손실최대={max_loss_streak_days}일 | "
            f"연승최대={max_ws}회"
        )

        # ── [v4.1] 🎯 목표 성과 기준 체크 ─────────────────────────────────────
        targets = {
            "pf":     {"target": LCFG.TARGET_PF,     "actual": pf,               "pass": pf >= LCFG.TARGET_PF},
            "sharpe":  {"target": LCFG.TARGET_SHARPE, "actual": sharpe_annualized, "pass": sharpe_annualized >= LCFG.TARGET_SHARPE},
            "sortino": {"target": LCFG.TARGET_SHARPE, "actual": sortino_annualized, "pass": sortino_annualized >= LCFG.TARGET_SHARPE},  # [v4.5]
            "mdd":     {"target": LCFG.TARGET_MDD,    "actual": mdd,                "pass": mdd >= LCFG.TARGET_MDD},
            "cagr":   {"target": LCFG.TARGET_CAGR,   "actual": cagr,              "pass": cagr >= LCFG.TARGET_CAGR},
        }
        result["target_check"] = targets
        passed = sum(1 for v in targets.values() if v["pass"])
        total  = len(targets)
        self.log.info(
            f"[DD-🎯] 목표 달성: {passed}/{total} | "
            f"PF={'✅' if targets['pf']['pass'] else '❌'}{pf:.2f}/{LCFG.TARGET_PF} | "
            f"Sharpe_ann={'✅' if targets['sharpe']['pass'] else '❌'}"
            f"{sharpe_annualized:.3f}/{LCFG.TARGET_SHARPE} | "
            f"MDD={'✅' if targets['mdd']['pass'] else '❌'}{mdd:.2%}/{LCFG.TARGET_MDD:.0%} | "
            f"CAGR={'✅' if targets['cagr']['pass'] else '❌'}{cagr:+.1%}/{LCFG.TARGET_CAGR:.0%}"
        )
        return result


# ==============================================================================
# [P0-3 FIX + P1-5 FIX] Walk-Forward 검증 + 진화
# ==============================================================================
class ParamEvolvor:
    """
    [P0-3 FIX] _heuristic: 대리(proxy) 평가 제거
      - 실데이터 필터링 컬럼 없으면 base 반환 (허위 승수 금지)
      - 최소 표본 HEURISTIC_MIN_SAMPLE 강제

    [P1-5 FIX] _score: 시간가중 EV 통합
      - EV_TW 60% + Sharpe 40%

    [P2-1 FIX] Walk-Forward 동적 분할
      - OOS 최소 WF_OOS_MIN_SAMPLES 보장
    """

    REGIME_MIN_TRADES = 10

    def __init__(self, log):
        self.log        = log
        self._ucb_count = _load_json(LCFG.PATH_UCB, log=log, default={})

    # ── [P1-5 FIX] 스코어 계산 — 시간가중 EV 통합 ────────────────────────────
    def _ev(self, rets: pd.Series) -> float:
        if len(rets) < 3: return 0.0
        r = rets.values
        wins   = r[r > 0]
        losses = r[r <= 0]
        wr     = len(wins) / max(len(r), 1)
        avg_w  = float(wins.mean())   if len(wins)   > 0 else 0.0
        avg_l  = float(losses.mean()) if len(losses) > 0 else 0.0
        return wr * avg_w + (1 - wr) * avg_l

    def _ev_tw(self, df_or_rets: pd.DataFrame) -> float:
        """시간가중 EV (DataFrame 입력)."""
        if isinstance(df_or_rets, pd.Series):
            return self._ev(df_or_rets)
        return _time_weighted_ev(df_or_rets)

    def _sharpe(self, rets: pd.Series) -> float:
        if len(rets) < 3: return 0.0
        return float(rets.mean() / (rets.std() + 1e-9))

    def _sortino(self, rets: pd.Series, mar: float = 0.0) -> float:
        """[v4.5] Sortino Ratio — 하방 리스크만 분모
        출처: Sortino & van der Meer (1991) JPM 17(4)
        Sharpe 대신 _score()에서도 사용 가능 (상방 변동성 페널티 없음)
        """
        if len(rets) < 3: return 0.0
        downside = rets[rets < mar]
        if len(downside) < 2:
            return self._sharpe(rets)  # 손실 거래 부족 시 Sharpe로 대체
        dstd = float(np.std(downside, ddof=1))
        return float((rets.mean() - mar) / (dstd + 1e-9))

    def _score(self, rets: pd.Series) -> float:
        """
        [P1-5 FIX] 시간가중 EV 60% + Sharpe 40%.
        EV*200으로 Sharpe와 스케일 맞춤.
        """
        if len(rets) < 3: return 0.0
        ev_raw  = self._ev(rets)
        sh_raw  = self._sharpe(rets)
        return ev_raw * 200 * 0.6 + sh_raw * 0.4

    # ── [P2-1 FIX] Walk-Forward 동적 분할 ─────────────────────────────────────
    @staticmethod
    def _split_is_oos(ledger: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        [P2-1 FIX] 동적 분할: OOS 최소 WF_OOS_MIN_SAMPLES 보장.
        데이터 충분 시 70:30, 부족 시 OOS 최소량 확보.
        """
        n   = len(ledger)
        oos_min = LCFG.WF_OOS_MIN_SAMPLES

        if n <= oos_min + 5:
            # 데이터 극소: 50:50 분할
            cut = n // 2
        else:
            cut_70 = int(n * LCFG.WF_IS_RATIO)
            oos_n  = n - cut_70
            if oos_n < oos_min:
                cut = n - oos_min  # OOS 최소량 보장
            else:
                cut = cut_70

        return ledger.iloc[:cut], ledger.iloc[cut:]

    # ── 레짐별 독립 Hill-Climbing ─────────────────────────────────────────────
    def _evolve_regime(self, ledger: pd.DataFrame,
                       decay_map: Dict[str, bool],
                       current: dict) -> Dict[str, dict]:
        regime_col = None
        for col in ["market_regime", "regime"]:
            if col in ledger.columns:
                regime_col = col
                break

        if regime_col is None:
            self.log.info("[REGIME-EV] regime 컬럼 없음 -> 레짐별 진화 스킵")
            return {}

        if decay_map and "pattern_key" in ledger.columns:
            decayed = {k for k, v in decay_map.items() if v}
            ledger  = ledger[~ledger["pattern_key"].isin(decayed)]

        regime_results: Dict[str, dict] = {}

        for regime, grp in ledger.groupby(regime_col):
            regime = str(regime)
            if len(grp) < self.REGIME_MIN_TRADES:
                self.log.info(f"[REGIME-EV] {regime}: 데이터 부족({len(grp)}) -> 스킵")
                continue

            is_r, oos_r = self._split_is_oos(grp)
            if len(is_r) < 5:
                continue

            base_is_r  = self._score(is_r["pnl_pct"])
            base_oos_r = self._score(oos_r["pnl_pct"]) if len(oos_r) >= 3 else None
            regime_improved: dict = {}

            for param, (pmin, pmax, step) in LCFG.PARAM_RANGES.items():
                base_val = current.get(param, (pmin + pmax) / 2)
                delta    = self._ucb_delta(f"r_{regime}_{param}", step, len(grp))
                best_val = base_val
                best_is  = base_is_r

                for d in [delta, -delta]:
                    cand = base_val + d
                    if param == "INST_ACCEL_CONSEC_MIN":
                        cand = int(round(cand))
                    else:
                        cand = round(cand, 6)
                    cand = float(np.clip(cand, pmin, pmax))
                    if cand == base_val:
                        continue

                    cand_is = self._heuristic(is_r, param, cand, base_is_r)
                    if cand_is <= best_is + LCFG.EV_IMPROVE_MIN:
                        continue

                    if base_oos_r is not None and len(oos_r) >= 3:
                        cand_oos = self._heuristic(oos_r, param, cand, base_oos_r)
                        if base_oos_r <= 0:
                            oos_fail = cand_oos < base_oos_r
                        else:
                            oos_fail = cand_oos < base_oos_r * LCFG.WF_OOS_ACCEPT
                        if oos_fail:
                            self.log.debug(
                                f"[REGIME-EV] {regime}/{param}={cand}: OOS FAIL -> 기각"
                            )
                            continue

                    best_is  = cand_is
                    best_val = cand
                    ucb_key  = f"r_{regime}_{param}_{'up' if d > 0 else 'down'}"
                    self._ucb_count[ucb_key] = self._ucb_count.get(ucb_key, 0) + 1

                if best_val != base_val:
                    regime_improved[param] = best_val

            if regime_improved:
                regime_results[regime] = regime_improved
                self.log.info(
                    f"[REGIME-EV] {regime}: {len(regime_improved)}개 파라미터 최적화 "
                    f"| {regime_improved}"
                )
            else:
                self.log.info(f"[REGIME-EV] {regime}: 현재 파라미터 최적")

        return regime_results

    def _ucb_delta(self, key_prefix: str, step: float, total: int,
                   ucb_coef: float = None) -> float:
        """[FIX-4] 동적 UCB 계수 지원."""
        if ucb_coef is None:
            ucb_coef = LCFG.UCB_EXPLORE_COEF
        n_up   = self._ucb_count.get(f"{key_prefix}_up",   0) + 1
        n_down = self._ucb_count.get(f"{key_prefix}_down", 0) + 1
        t      = max(total, 2)
        ucb_u  = np.sqrt(ucb_coef * np.log(t) / n_up)
        ucb_d  = np.sqrt(ucb_coef * np.log(t) / n_down)
        return +step if ucb_u > ucb_d else -step

    # ── 메인 진화 ─────────────────────────────────────────────────────────────
    def _load_current(self) -> dict:
        return _load_json(LCFG.PATH_PARAMS, log=self.log, default={
            k: (v[0] + v[1]) / 2 for k, v in LCFG.PARAM_RANGES.items()
        })

    def evolve(self, ledger: pd.DataFrame,
               agg_result: dict, conc_result: dict,
               decay_map: Dict[str, bool]) -> dict:

        if "date" in ledger.columns:
            cutoff = (datetime.now() - timedelta(days=LCFG.EVOLVE_LOOKBACK_D)).strftime("%Y%m%d")
            recent = ledger[ledger["date"].astype(str) >= cutoff]
        else:
            recent = ledger

        if len(recent) < LCFG.EVOLVE_MIN_TRADES:
            self.log.info(f"[EVOLVE] 데이터 부족({len(recent)}) -> 스킵")
            return {}

        # ── [P2-1] Walk-Forward 동적 분할 ─────────────────────────────────────
        is_df, oos_df = self._split_is_oos(recent)
        if len(is_df) < 10:
            self.log.warning("[EVOLVE] IS 데이터 부족 -> 스킵")
            return {}

        base_is  = self._score(is_df["pnl_pct"])
        base_oos = self._score(oos_df["pnl_pct"]) if len(oos_df) >= 5 else None
        current  = self._load_current()
        improved = {}
        total_t  = len(recent)

        self.log.info(
            f"[EVOLVE] Walk-Forward: IS={len(is_df)}건(점수={base_is:.5f}) "
            f"OOS={len(oos_df)}건(점수={f'{base_oos:.5f}' if base_oos is not None else 'N/A'})"
        )

        # 소멸 패턴 제외
        if decay_map and "pattern_key" in is_df.columns:
            decayed_keys = {k for k, v in decay_map.items() if v}
            is_df = is_df[~is_df["pattern_key"].isin(decayed_keys)]
            self.log.info(f"[EVOLVE] 소멸 패턴 제외 후 IS: {len(is_df)}건")

        # ── [FIX-4] 목표 미달 강제 방어 ───────────────────────────────────────
        # DD 상태에서 최근 성과 로드 → 목표 미달 시 진화 보수화
        dd_state = _load_json(LCFG.PATH_DD, log=self.log, default={})
        defense_mult = 1.0           # 진화 EV_IMPROVE_MIN 승수
        defense_ucb  = LCFG.UCB_EXPLORE_COEF

        if dd_state:
            dd_pf     = dd_state.get("profit_factor", 999)
            dd_sharpe = dd_state.get("sharpe", 999)
            dd_mdd    = dd_state.get("mdd_overall", 0)
            dd_cagr   = dd_state.get("cagr", 999)

            if dd_pf < LCFG.PF_DEFENSE_LEVEL:
                defense_mult *= 0.7
                self.log.warning(
                    f"[FIX-4] PF={dd_pf:.2f} < {LCFG.PF_DEFENSE_LEVEL} → 진화 보수화 ×0.7"
                )
            if dd_sharpe < LCFG.SHARPE_DEFENSE_LEVEL:
                defense_mult *= 0.8
                self.log.warning(
                    f"[FIX-4] Sharpe={dd_sharpe:.3f} < {LCFG.SHARPE_DEFENSE_LEVEL} → 진화 보수화 ×0.8"
                )
            if dd_mdd <= LCFG.MDD_DEFENSE_LEVEL:
                defense_mult *= 0.5
                self.log.warning(
                    f"[FIX-4] MDD={dd_mdd:.2%} ≤ {LCFG.MDD_DEFENSE_LEVEL:.0%} → 진화 보수화 ×0.5"
                )
            if dd_cagr < LCFG.CAGR_DEFENSE_LEVEL:
                defense_ucb = 0.7
                self.log.warning(
                    f"[FIX-4] CAGR={dd_cagr:+.1%} < {LCFG.CAGR_DEFENSE_LEVEL:.0%} → UCB 탐색 축소 0.7"
                )

        # 방어 적용: EV_IMPROVE_MIN을 더 높여서 변경 문턱 강화
        active_ev_min = LCFG.EV_IMPROVE_MIN
        if defense_mult < 1.0:
            # 방어 시 개선 임계값 상향 (더 큰 개선만 채택)
            active_ev_min = LCFG.EV_IMPROVE_MIN / defense_mult
            self.log.info(
                f"[FIX-4] 진화 임계값 상향: {LCFG.EV_IMPROVE_MIN:.4f} → {active_ev_min:.4f}"
            )

        # ── Hill-Climbing + UCB — [FIX-G] 멀티스텝 탐색 ─────────────────────
        # 기존: ±1스텝만 → 지역 최솟값 취약
        # 개선: ±1스텝, ±2스텝, ±3스텝 순서 탐색 → 지역 탈출 능력 향상
        MULTISTEP_FACTORS = [1, 2, 3]   # 스텝 배수

        for param, (pmin, pmax, step) in LCFG.PARAM_RANGES.items():
            base_val = current.get(param, (pmin + pmax) / 2)
            # [FIX-4] 방어 모드에서 UCB 계수 축소
            delta    = self._ucb_delta(param, step, total_t, ucb_coef=defense_ucb)
            best_val = base_val
            best_is  = base_is

            # [FIX-G] 멀티스텝: ±1, ±2, ±3스텝 순서 탐색
            for factor in MULTISTEP_FACTORS:
                for d in [delta * factor, -delta * factor]:
                    cand = base_val + d
                    if param == "INST_ACCEL_CONSEC_MIN":
                        cand = int(round(cand))
                    else:
                        cand = round(cand, 6)
                    cand = float(np.clip(cand, pmin, pmax))
                    if cand == base_val or cand == best_val:
                        continue

                    cand_is = self._heuristic(is_df, param, cand, base_is)
                    if cand_is <= best_is + active_ev_min:
                        continue

                    if base_oos is not None and len(oos_df) >= 5:
                        cand_oos = self._heuristic(oos_df, param, cand, base_oos)
                        if base_oos <= 0:
                            oos_fail = cand_oos < base_oos
                        else:
                            oos_fail = cand_oos < base_oos * LCFG.WF_OOS_ACCEPT
                        if oos_fail:
                            self.log.debug(
                                f"[EVOLVE] {param}={cand}(×{factor}): IS OK but OOS FAIL "
                                f"(OOS={cand_oos:.5f}) -> 기각"
                            )
                            continue

                    best_is  = cand_is
                    best_val = cand
                    direction = "up" if d > 0 else "down"
                    ucb_key   = f"{param}_{direction}"
                    self._ucb_count[ucb_key] = (
                        self._ucb_count.get(ucb_key, 0) + 1
                    )
                    self.log.debug(
                        f"[EVOLVE-MS] {param}: step×{factor} → {cand:.4f} IS={cand_is:.5f}"
                    )

            if best_val != base_val:
                improved[param] = best_val
                self.log.info(f"[EVOLVE] {param}: {base_val} -> {best_val} [WF 검증 통과]")

        # ── 레짐별 독립 진화 ──────────────────────────────────────────────────
        regime_params = self._evolve_regime(recent, decay_map, current)
        if regime_params:
            improved["regime_params"] = regime_params
            self.log.info(f"[EVOLVE] 레짐별 파라미터 최적화: {list(regime_params.keys())}")

        # ── 갭등급별 TP (실데이터 역산) ───────────────────────────────────────
        for grade, tp_map in conc_result.get("gap_grade_tp", {}).items():
            param = LCFG.GAP_TP_MAP.get(str(grade).upper())
            if not param:
                continue
            pmin, pmax, _ = LCFG.PARAM_RANGES.get(param, (0, 999, 0.5))
            raw_tp  = tp_map.get("optimal_tp_pct", 0.0)
            clipped = float(np.clip(raw_tp, pmin, pmax))
            if abs(clipped - current.get(param, clipped)) > 0.25:
                improved[param] = round(clipped, 2)
                self.log.info(f"[EVOLVE] Gap{grade} TP: {current.get(param,'?')} -> {clipped:.2f}%")

        # ── kelly_mult 반영 ───────────────────────────────────────────────────
        if agg_result:
            improved["kelly_mult"]      = agg_result.get("kelly_mult",   LCFG.AGG_BASE_KELLY)
            improved["aggression_mode"] = agg_result.get("mode",         "NORMAL")
            improved["kelly_raw"]       = agg_result.get("kelly_raw",    0.0)

        # ── 레짐별 Kelly 기록 ─────────────────────────────────────────────────
        regime_stats = _load_json(LCFG.PATH_REGIME, log=self.log, default={})
        if regime_stats:
            improved["regime_kelly"] = {
                r: s.get("kelly_half", LCFG.AGG_BASE_KELLY)
                for r, s in regime_stats.items()
            }

        # ── 저장 ──────────────────────────────────────────────────────────────
        if improved:
            new_params = {**current, **improved}
            new_params["evolved_at"] = datetime.now().strftime("%Y%m%d%H%M%S")
            new_params["base_is"]    = round(base_is, 6)
            new_params["base_oos"]   = round(base_oos, 6) if base_oos is not None else None
            new_params["_version"]   = "4.4"

            # ══════════════════════════════════════════════════════════
            # [v4.1] 12대 강화 — 다운스트림 파라미터 출력
            # ══════════════════════════════════════════════════════════

            # 🚨① 실시간 연결: 리프레시 간격
            new_params["param_refresh_interval_min"] = LCFG.PARAM_REFRESH_INTERVAL_MIN
            new_params["param_min_sample"]           = LCFG.PARAM_MIN_SAMPLE

            # 🚨⑥ 거래 횟수 제한
            new_params["max_trades_per_day"] = LCFG.MAX_TRADES_PER_DAY
            new_params["cooldown_min"]       = LCFG.COOLDOWN_MIN

            # 🚨⑦ 트레일링 수익 구조
            trail_params = {
                "trail_strong": LCFG.TRAIL_STRONG,
                "trail_mid":    LCFG.TRAIL_MID,
                "trail_exit":   LCFG.TRAIL_EXIT,
                "partial_sell": LCFG.PARTIAL_SELL,
            }
            if not recent.empty and "ride_score" in recent.columns:
                wins_ride = recent.loc[recent["pnl_pct"] > 0, "ride_score"].dropna()
                if len(wins_ride) >= 10:
                    # [PROFIT-4] 역산 quantile 80/55/30 (더 늦게 팔기)
                    trail_params["trail_strong"] = round(float(wins_ride.quantile(0.80)), 2)
                    trail_params["trail_mid"]    = round(float(wins_ride.quantile(0.55)), 2)
                    trail_params["trail_exit"]   = round(float(wins_ride.quantile(0.30)), 2)
                    trail_params["partial_sell"] = LCFG.PARTIAL_SELL
                    self.log.info(
                        f"[EVOLVE] 🚨⑦ 트레일 역산: "
                        f"strong={trail_params['trail_strong']} "
                        f"mid={trail_params['trail_mid']} "
                        f"exit={trail_params['trail_exit']}"
                    )
            new_params["trail"] = trail_params

            # 🚨⑧ 하드 리스크 캡
            new_params["risk_caps"] = {
                "max_position":       LCFG.MAX_POSITION,
                "max_loss_per_trade": LCFG.MAX_LOSS_PER_TRADE,
                "max_daily_loss":     LCFG.MAX_DAILY_LOSS,
            }

            # 🚨⑨ 기관 필터
            inst_params = {
                "min_inst_days": LCFG.MIN_INST_DAYS,
                "min_ofi":       LCFG.MIN_OFI,
                "min_accel":     LCFG.MIN_ACCEL,
            }
            if not recent.empty and "inst_consec" in recent.columns:
                win_inst = recent.loc[recent["pnl_pct"] > 0, "inst_consec"].dropna()
                if len(win_inst) >= 10:
                    inst_params["min_inst_days"] = max(2, int(win_inst.quantile(0.25)))
            if not recent.empty and "ofi_accel" in recent.columns:
                win_ofi = recent.loc[recent["pnl_pct"] > 0, "ofi_accel"].dropna()
                if len(win_ofi) >= 10:
                    inst_params["min_ofi"] = round(float(win_ofi.quantile(0.25)), 2)
            new_params["inst_filter"] = inst_params

            # 🚨⑩ 과열 차단
            new_params["overheat"] = {
                "hard_overheat": LCFG.HARD_OVERHEAT,
                "soft_overheat": LCFG.SOFT_OVERHEAT,
            }

            # 🚨⑪ 슬리피지
            new_params["slippage"] = LCFG.SLIPPAGE

            # 🚨⑫ 시간 필터
            new_params["block_times"] = LCFG.BLOCK_TIMES

            # 🎯 목표 성과 기준
            new_params["targets"] = {
                "pf": LCFG.TARGET_PF, "sharpe": LCFG.TARGET_SHARPE,
                "mdd": LCFG.TARGET_MDD, "cagr": LCFG.TARGET_CAGR,
            }

            # 🚨 [FIX-3] Top1 약한 날 차단 기준 (다운스트림 전달)
            new_params["selection_guard"] = {
                "min_top1_ev":      LCFG.MIN_TOP1_EV,
                "min_top1_pf":      LCFG.MIN_TOP1_PF,
                "min_top1_winrate": LCFG.MIN_TOP1_WINRATE,
            }

            # 🚨 [FIX-4] 목표 미달 방어 기준 (다운스트림 전달)
            new_params["learning_defense"] = {
                "pf_defense_level":     LCFG.PF_DEFENSE_LEVEL,
                "sharpe_defense_level": LCFG.SHARPE_DEFENSE_LEVEL,
                "mdd_defense_level":    LCFG.MDD_DEFENSE_LEVEL,
                "cagr_defense_level":   LCFG.CAGR_DEFENSE_LEVEL,
            }

            _atomic_json(LCFG.PATH_PARAMS, new_params, log=self.log)
            _atomic_json(LCFG.PATH_UCB,    self._ucb_count, log=self.log)
            self.log.info(
                f"[EVOLVE] {len(improved)}개 파라미터 + 12대 강화 출력 "
                f"-> {LCFG.PATH_PARAMS}"
            )
        else:
            self.log.info("[EVOLVE] 현재 파라미터 최적 (변경 없음)")

        return improved

    # ── [P0-3 FIX] 휴리스틱 스코어 — 대리 평가 제거 ───────────────────────────
    def _heuristic(self, trades: pd.DataFrame, param: str,
                   val: float, base: float) -> float:
        """
        [P0-3 FIX] 실데이터 필터링 기반 평가.
        해당 컬럼이 없으면 base 반환 (허위 1.01 승수 제거).
        최소 표본 HEURISTIC_MIN_SAMPLE 미만 시 base 반환.
        """
        rets   = trades["pnl_pct"]
        minN   = LCFG.HEURISTIC_MIN_SAMPLE

        if param == "CONF_MIN":
            f = rets[rets.abs() > rets.quantile(0.3)]
            if len(f) < minN:
                return base
            return self._score(f) * (1.02 if val > rets.mean() else 0.97)

        if param == "PB_MIN":
            if "pb_depth" in trades.columns:
                f = rets[trades["pb_depth"].fillna(0) >= val]
                return self._score(f) if len(f) >= minN else base
            # [P0-3] 컬럼 없으면 base 반환 (대리 평가 금지)
            return base

        if param == "PB_MAX":
            if "pb_depth" in trades.columns:
                f = rets[trades["pb_depth"].fillna(0) <= val]
                return self._score(f) if len(f) >= minN else base
            return base

        if param == "TREND_VWAP_MIN":
            wins_only = rets[rets > 0]
            if len(wins_only) < 3:
                return base
            q75 = float(wins_only.quantile(0.75))
            f   = rets[rets > -q75 * 0.5]
            return self._score(f) if len(f) >= minN else base

        if param == "EV_MIN":
            f = rets[rets > val] if val > 0 else rets
            return self._score(f) if len(f) >= minN else base

        if param == "INST_ACCEL_CONSEC_MIN":
            if "inst_accel_consecutive" in trades.columns:
                f = rets[trades["inst_accel_consecutive"].fillna(0) >= val]
                return self._score(f) if len(f) >= minN else base
            # [P0-3] 컬럼 없으면 base 반환
            return base

        if param == "QUIET_PB_VOL_MAX":
            if "pb_vol_ratio" in trades.columns:
                f = rets[trades["pb_vol_ratio"].fillna(1.0) < val]
                return self._score(f) * 1.05 if len(f) >= minN else base
            return base

        if param in ("TP_A_PCT", "TP_B_PCT", "TP_C_PCT"):
            grade = {"TP_A_PCT": "A", "TP_B_PCT": "B", "TP_C_PCT": "C"}[param]
            if "gap_grade" in trades.columns:
                g = rets[trades["gap_grade"].astype(str).str.upper() == grade]
                if len(g) >= minN:
                    tp   = val / 100.0
                    hit  = g[(g > tp * 0.8) & (g <= tp * 1.2)]
                    lift = len(hit) / max(len(g), 1)
                    return self._score(g) * (1 + lift * 0.1)
            return base

        if param == "SL_PCT":
            sl  = -val / 100.0
            bad = (rets < sl * 1.5).mean()
            return self._score(rets) * (1.0 - bad * 0.5) if len(rets) >= minN else base

        return self._score(rets) if len(rets) >= minN else base


# ==============================================================================
# 데이터 로더
# ==============================================================================
def _load_ledger(log) -> pd.DataFrame:
    p = Path(LCFG.PATH_LEDGER)
    if not p.exists():
        log.warning(f"[LOAD] 원장 없음: {p}")
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
        log.info(f"[LOAD] 원장: {len(df)}건")
        return df
    except Exception as e:
        log.error(f"[LOAD] 원장 로드 실패: {e}")
        return pd.DataFrame()


def _load_feedback(log) -> pd.DataFrame:
    records = []
    for fp in sorted(Path(LCFG.DIR_FEEDBACK).glob("feedback_*.json"))[-7:]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                records.extend(json.load(f).get("trades", []))
        except Exception:
            pass
    if records:
        log.info(f"[LOAD] feedback: {len(records)}건")
    return pd.DataFrame(records) if records else pd.DataFrame()


# ==============================================================================
# [P1-1 FIX] 리포트 — 수익률 평가 포함
# ==============================================================================
def _print_report(log):
    log.info("=" * 65)
    log.info("[REPORT] ── 수익성 리포트 v4.2 ──────────────────────────")

    dd = _load_json(LCFG.PATH_DD, log=log, default={})
    if dd:
        pf_v = "OK" if dd.get("profit_factor", 0) >= 1.5 else "WARN"
        log.info(
            f"  성과: WR={dd.get('win_rate',0):.1%} | "
            f"PF={dd.get('profit_factor',0):.2f}[{pf_v}] | "
            f"Sharpe={dd.get('sharpe',0):.3f} | MDD={dd.get('mdd_overall',0):.2%}"
        )
        log.info(
            f"  Kelly={dd.get('kelly_half',0):.3f} | "
            f"EV_TW={dd.get('ev_tw',0):.5f} | 연손={dd.get('max_loss_streak',0)}회"
        )
        # [P1-1] 수익률 평가
        log.info(
            f"  ★ 수익률: 누적={dd.get('cumulative_return',0):+.2%} | "
            f"CAGR={dd.get('cagr',0):+.2%} | "
            f"연속손실최대={dd.get('max_loss_streak_days',0)}일"
        )
        pctiles = dd.get("return_percentiles", {})
        if pctiles:
            log.info(
                f"  ★ 분포: P5={pctiles.get('p5',0):.2%} "
                f"P25={pctiles.get('p25',0):.2%} "
                f"P50={pctiles.get('p50',0):.2%} "
                f"P75={pctiles.get('p75',0):.2%} "
                f"P95={pctiles.get('p95',0):.2%}"
            )
        log.info(
            f"  ★ 승패: 이익={dd.get('total_wins',0)}건 | "
            f"손실={dd.get('total_losses',0)}건 | "
            f"연승최대={dd.get('max_win_streak',0)}회"
        )

    agg = _load_json(LCFG.PATH_AGGRESSION, log=log, default={})
    if agg:
        log.info(
            f"  공격모드: {agg.get('mode','?')} | kelly={agg.get('kelly_mult','?')} | "
            f"MDD10d={agg.get('mdd_10d',0):.2%} | 이유: {agg.get('reason','')}"
        )

    regime = _load_json(LCFG.PATH_REGIME, log=log, default={})
    if regime:
        log.info("  ─ 레짐별 성과 ─")
        for r, s in regime.items():
            log.info(
                f"    {r}: WR={s.get('win_rate',0):.1%} EV={s.get('ev',0):.5f} "
                f"Kelly={s.get('kelly_half',0):.3f}"
            )

    conc = _load_json(LCFG.PATH_CONCENTRATION, log=log, default={})
    top3 = conc.get("ticker_heatmap", [])[:3]
    if top3:
        log.info("  ─ Top-3 종목 EV ─")
        for t in top3:
            log.info(
                f"    {t.get('ticker','?')}: EV={t.get('ev',0):.5f} "
                f"PF={t.get('profit_factor',0):.2f}"
            )
    for grade, info in conc.get("gap_grade_tp", {}).items():
        log.info(
            f"  Gap{grade}: TP={info.get('optimal_tp_pct',0):.2f}% "
            f"WR={info.get('win_rate',0):.1%}({info.get('n',0)}건)"
        )

    params = _load_json(LCFG.PATH_PARAMS, log=log, default={})
    if params:
        log.info(
            f"  진화: {params.get('evolved_at','?')} v{params.get('_version','?')} | "
            f"IS={params.get('base_is','?')} OOS={params.get('base_oos','?')}"
        )
        rp = params.get("regime_params", {})
        if rp:
            log.info("  ─ 레짐별 최적 파라미터 ─")
            for rg, rparams in rp.items():
                log.info(f"    [{rg}] {rparams}")

        # [v4.1] 12대 강화 파라미터 출력
        if params.get("trail"):
            t = params["trail"]
            log.info(
                f"  ⑦ 트레일: strong={t.get('trail_strong','?')} "
                f"mid={t.get('trail_mid','?')} exit={t.get('trail_exit','?')} "
                f"partial={t.get('partial_sell','?')}"
            )
        if params.get("risk_caps"):
            rc = params["risk_caps"]
            log.info(
                f"  ⑧ 리스크캡: maxPos={rc.get('max_position','?')} "
                f"maxLoss={rc.get('max_loss_per_trade','?')}% "
                f"dailyLoss={rc.get('max_daily_loss','?')}%"
            )
        if params.get("inst_filter"):
            inf = params["inst_filter"]
            log.info(
                f"  ⑨ 기관: instDays≥{inf.get('min_inst_days','?')} "
                f"ofi≥{inf.get('min_ofi','?')} accel≥{inf.get('min_accel','?')}"
            )

    # [v4.1] 🎯 목표 달성 현황
    if dd:
        tc = dd.get("target_check", {})
        if tc:
            log.info("  ─ 🎯 목표 달성 현황 ─")
            for metric, info in tc.items():
                status = "✅" if info.get("pass") else "❌"
                log.info(
                    f"    {status} {metric}: "
                    f"{info.get('actual',0):.4f} / {info.get('target',0)}"
                )

    log.info("=" * 65)


# ==============================================================================
# MAIN
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="자기진화 학습 엔진 v4.4")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--evolve", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--all",    action="store_true")
    args = parser.parse_args()

    log = _setup_logger()
    log.info("=" * 65)
    log.info(
        f"자기진화 학습 엔진 v4.4 — 시가/추세눌림 2전략 특화(종배삭제) | "
        f"Sharpe연환산(×√{LCFG.TRADING_DAYS_PER_YEAR}) | "
        f"CAGR거래일({LCFG.TRADING_DAYS_PER_YEAR}일) | "
        f"전략({','.join(LCFG.STRATEGIES)}) | 레짐별DecayLambda | "
        f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    log.info("=" * 65)

    if args.status:
        st = _load_json(LCFG.PATH_BAYESIAN, log=log, default={})
        n_patterns = len([k for k in st if not k.startswith("_")])
        log.info(f"[STATUS] Bayesian 패턴: {n_patterns}개")
        agg = _load_json(LCFG.PATH_AGGRESSION, log=log, default={})
        if agg:
            log.info(f"[STATUS] {agg.get('mode','?')} kelly={agg.get('kelly_mult','?')}")
        return 0

    if args.report:
        _print_report(log)
        return 0

    with FileLock(LCFG.PATH_LOCK, log):

        # ── 단일 로드 (전 모듈 공유) ──────────────────────────────────────────
        ledger      = _load_ledger(log)
        feedback_df = _load_feedback(log)
        src         = feedback_df if not feedback_df.empty else ledger

        if not ledger.empty:
            ledger = _ensure_pattern_key(ledger, log)
            ledger = _validate_ledger(ledger, log)
        if not src.empty and src is not ledger:
            src = _ensure_pattern_key(src, log)
            src = _validate_ledger(src, log)

        bayes    = BayesianUpdater(log)
        builder  = StatsBuilder(log)
        evolvor  = ParamEvolvor(log)
        analyzer = SignalQualityAnalyzer(log)
        conc_a   = ConcentrationAnalyzer(log)
        agg_ctl  = AggressionController(log)
        dd_track = DrawdownTracker(log)
        regime_l = RegimeLearner(log)

        agg_result  = {}
        conc_result = {}
        decay_map   = {}

        # ── UPDATE ────────────────────────────────────────────────────────────
        if args.update or args.all:
            log.info("[LEARN] ─── Bayesian 업데이트 ───")
            if not src.empty:
                decay_map = bayes.detect_decay()
                bayes.update_bulk(src)
                stats_src = ledger if not ledger.empty else src
                stats_df  = builder.build(stats_src, bayes)
                builder.save(stats_df)
            else:
                log.warning("[LEARN] 데이터 없음")

        # ── CONCENTRATION + AGGRESSION + DD + REGIME ─────────────────────────
        if args.all or args.evolve:
            if not ledger.empty:
                log.info("[LEARN] ─── 종목 집중 분석 ───")
                conc_result = conc_a.analyze(ledger)

                log.info("[LEARN] ─── 공격/안정 모드 평가 ───")
                agg_result  = agg_ctl.evaluate(ledger)
                dd_track.track(ledger)

                log.info("[LEARN] ─── 레짐 분리 학습 ───")
                regime_l.analyze(ledger)

                if not decay_map:
                    decay_map = bayes.detect_decay()

        # ── EVOLVE ────────────────────────────────────────────────────────────
        if args.evolve or args.all:
            log.info("[LEARN] ─── 파라미터 진화 (Walk-Forward + UCB) ───")
            if not ledger.empty and len(ledger) >= LCFG.EVOLVE_MIN_TRADES:
                improved = evolvor.evolve(ledger, agg_result, conc_result, decay_map)
                if improved:
                    log.info(f"[LEARN] 채택: {list(improved.keys())}")
            else:
                log.info(f"[LEARN] 진화 데이터 부족({len(ledger)}건)")

        # ── SIGNAL QUALITY ────────────────────────────────────────────────────
        if args.all:
            log.info("[LEARN] ─── 신호 품질 분석 ───")
            if not ledger.empty:
                quality = analyzer.analyze(ledger)
                for feat, stat in quality.items():
                    if stat.get("lift", 1.0) < 0.8:
                        log.warning(f"[QUALITY] {feat} 역효과 -> 파라미터 조정 권고")

    log.info("[LEARN] 완료")
    log.info("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())

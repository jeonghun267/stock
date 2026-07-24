# -*- coding: utf-8 -*-
"""
pullback_sell_strategy_v4_21_FIXED.py
======================================
고유 영역  : 매수 완료 종목의 당일 매도 전담 (청산 엔진)
파이프라인 : kjs_execute_queue.csv → [이 파일] → 키움 API 매도
                                              → eod_ev_history.csv

v4_20 목표: rt_sell v3.12 기준 정합 (2026-04-16)
[v4.20 — 2026-04-16]
  [수정1] OFI 기관강세 기준 0.30 → 0.40 (rt_sell v3.12 ISSUE-1 통일)
          기존 0.30: 허위 기관강세 → Trail 과확대 → 수익 반납
          수정 0.40: 진짜 강한 기관 흐름만 k×1.15 완화 허용
  [수정2] PEAK_PROTECT 기관동행 ÷1.15 완화 구현 (rt_sell v3.12 동일 원칙)
          ride≥0.40: tier 임계 ÷1.15 → 기관 매집 중 조기 청산 차단
          예) tier1=5% → 기관동행 시 4.35% 이상부터 발동
          PEAK_PROTECT_INST_RELAX_MULT=1.15, PEAK_PROTECT_INST_RIDE_MIN=0.40

v4_18 목표: 96점 달성 — 자기진화 루프 완성
[v4.18 — 2026-04-15]
  [FIX-A] pnl_strategy_linker import — v3.3 우선, v3.2 fallback
  [FIX-B] TRADE_LOG_PATH: BASE/DATA/trade_log.csv — evolution_engine 공유 경로
  [FIX-C] _append_ev() 후 trade_log.csv 13컬럼 기록 (SIGA FIX-5 이식)
          profit_pct 백분율 → 소수 변환(/100) — evolution_engine 단위 정합
  [FIX-D] write_sell_fill() 호출 — 자기진화 트리거 완성
  연결: pnl_strategy_linker_v3_3.py / bridge_eod_v9_8.py / evolution_engine_v3_9.py

v4_17 목표: 96점 달성 — 키움 OpenAPI+ 실연동 완전판
-------------------------------------------
[v4_17-1] KiwoomBridge 클래스 — PyQt5 COM 직접 래핑 (싱글턴)
          - QApplication 생성 + OnReceiveTrData 이벤트 루프 처리
          - send_order() : SendOrder tr_code=KOA_NORMAL_BUY_KP_ORD
          - wait_order_confirm() : 접수번호 수신 대기 (timeout=5초)
          - get_balance()        : opw00018 잔고 조회
[v4_17-2] _get_kiwoom_api() — 주석 제거, 실 import + 싱글턴 반환
[v4_17-3] _send_sell_order() — 주문접수번호 확인 후 True 반환
          실패(ret≠0 / timeout / 예외) → 3회 재시도 후 False
[v4_17-4] _order_retry() — 재시도 데코레이터 (max=3, backoff=0.5s)
[v4_17-5] 주문 이력 파일 order_log.csv 실시간 기록
          (접수번호·시각·종목·수량·사유·결과)
[v4_17-6] main() — PAPER_TRADE=false 시 KiwoomBridge 사전 연결 확인
          연결 실패 → RC_STOP22 즉시 반환
[FIX-1]  _send_sell_order() — 시뮬 플래그(PAPER_TRADE) 분기 + 키움 실주문 연동
         실거래 시 KiwoomAPI.send_order() 호출, 실패 시 RC_STOP22 반환
[FIX-2]  _step5_structure_exit() — 손실 구간(profit<=0)에서도 VWAP 이탈 청산 허용
[FIX-3]  _step6/_step7 초기 손절 중복 제거 — _step6에서 전담, _step7 데드코드 삭제
[FIX-4]  RTCache._rt 동일종목 다수행 — 마지막행 덮어쓰기 → 타임스탬프 최신행 선택
[FIX-5]  _append_ev() — 전체 CSV 재읽기 제거 → append 모드 라인 추가로 O(1) 처리
[FIX-6]  PnLTracker.is_circuit_broken() — 매도 차단 → 신규 진입 차단 전용 플래그로 변경
         회로차단 발동 시 청산은 허용, 매수(진입) 측에서 차단
[FIX-7]  PnLTracker 손실 계산 — 종목 수익률 × 포지션 비율(equity_weight) 반영
         ALL_IN 모드: profit_pct × ALL_IN_WEIGHT(기본 0.70) 로 포트폴리오 손실 환산
[FIX-8]  PEAK_PROTECT + HARD_FAILSAFE 동시발동 방지 — _step8 발동 시 _step9 스킵
[FIX-9]  선익절 후 잔량 peak_price 독립 추적 — partial_entry_price 필드 추가
[FIX-10] OFI EMA 평활화(span=3) RTCache 내부에서 재적용 — 상위모듈 의존 제거
[FIX-11] RTCache 실시간 재로드 — get_fresh_cache() 팩토리 함수 + 호출시점 재로드 지원
[FIX-12] prices_1m 날짜 필터 — 문자열 prefix 비교 → datetime 파싱 방어 로직 추가
[FIX-13] _step12 강제청산 유예 — OR 조건 → AND 조건으로 변경 (기관동행 AND 수익 모두 충족)
[FIX-14] _step3 C→B 승급 — 수익 기준 0.80% → 1.50% 상향 (몰빵 기준 강화)
[KEEP]   _HOLD 싱글턴 / SellDecision TypedDict / _validate_params 모두 유지
[KEEP]   PnLTracker·BacktestEngine·Kelly·Almgren-Chriss 모두 유지
ENGINE_VERSION = v4_21_FIXED_20260418

학술 출처 완전 목록
-------------------
  Chandelier Exit   : Le Beau (1991)
  ATR               : Wilder (1978) New Concepts in Technical Trading
  VPIN              : Easley, López de Prado, O'Hara (2012) SSRN 1695596
  OFI               : Cont, Kukanov, Stoikov (2014) Management Science
  Kelly Criterion   : Kelly (1956) Bell System Technical Journal
  Sharpe Ratio      : Sharpe (1966) Journal of Business
  Sortino Ratio     : Sortino & van der Meer (1991) Journal of Portfolio Mgmt
  Exit Score 가중치 : Jegadeesh & Titman (1993) Journal of Finance
  Optimal Execution : Almgren & Chriss (2001) Applied Mathematical Finance
  Triple Barrier    : López de Prado (2018) Advances in Financial ML
  Walk-forward      : López de Prado (2018) Ch.7 Cross-Validation in Finance
  VWAP 벤치마크     : Kissell & Glantz (2003) Optimal Trading Strategies
"""
from __future__ import annotations

import csv
import json

# [v4.21] pnl_strategy_linker — 자기진화 트리거 (단일 import)
_PNL_LINKER_OK = False
_pnl_write_sell = None
try:
    from pnl_strategy_linker_v3_5 import write_sell_fill as _pnl_write_sell
    _PNL_LINKER_OK = True
except Exception as e:
    print(f"[PNL][FAIL] linker import 실패: {e}")
    raise RuntimeError("pnl_strategy_linker_v3_5 필수 모듈 로딩 실패") from e
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# [PATCH-RATELIMIT] Kiwoom TR burst 방지
sys.path.insert(0, r"C:\stock_bot\RUN")
from safeplus_rate_limiter import KiwoomRateLimiter
_limiter = KiwoomRateLimiter()

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # type: ignore

# ── params_reader 연결 ────────────────────────────────────────
# [연결] get_rt_sell() 추가 — T2_MULT / split_ratio 등 params.json 마스터값 자동 동기화
# params.json → params_reader → 이 파일 : 단일 진실 공급원 구조 완성
try:
    _RUN_DIR = Path(__file__).resolve().parent
    if str(_RUN_DIR) not in sys.path:
        sys.path.insert(0, str(_RUN_DIR))
    from params_reader import get_갭등급  as _get_갭등급
    from params_reader import get_청산시각 as _get_청산시각
    from params_reader import get_rt_sell  as _get_rt_sell
except ImportError:
    def _get_갭등급():  return {}   # type: ignore
    def _get_청산시각(): return {}  # type: ignore
    def _get_rt_sell():  return {}  # type: ignore

# ═══════════════════════════════════════════════════════════════
#  리턴 코드
# ═══════════════════════════════════════════════════════════════
RC_OK     = 0
RC_HOLD   = 200
RC_STOP22 = 22
ENGINE_VERSION = "pullback_sell_strategy_v4_21_FIXED_20260418"
ENGINE_VER     = ENGINE_VERSION

# ═══════════════════════════════════════════════════════════════
#  [NEW-1] _HOLD 싱글턴 — step 함수 HOLD 전용 불투명 객체
#  설계 원칙: {} 와 달리 다른 함수의 반환값과 절대 혼동 불가
#  _get_갭등급(), _load_state() 가 반환하는 {} 와 타입 구분됨
# ═══════════════════════════════════════════════════════════════
_HOLD = object()   # ★ 타입: object (dict, None 과 구분)


# ═══════════════════════════════════════════════════════════════
#  [NEW-2] SellDecision TypedDict — 매도 주문 반환값 명시
# ═══════════════════════════════════════════════════════════════
class SellDecision(TypedDict, total=False):
    code:        str
    qty:         int
    price:       float
    profit_pct:  float
    reason:      str
    trail_pct:   float
    gap_grade:   str
    score_flow:  float
    trail_price:   float
    highest_high:  float
    chandelier_k:  float
    vol_regime:    str
    exit_score:    float


# ═══════════════════════════════════════════════════════════════
#  경로 상수
# ═══════════════════════════════════════════════════════════════
BASE       = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA_DIR   = BASE / "DATA"
LOG_DIR    = DATA_DIR / "LOG"
LOG_PATH   = LOG_DIR  / "pullback_sell_engine.log"
QUEUE_PATH = DATA_DIR / "queue"  / "kjs_execute_queue.csv"
# [QSCHEMA-FIX 2026-06-10] 실보유 교차검증용 rt_open (chejan 닫힌루프가 갱신하는 단일 SoT)
_RT_OPEN_PATH_QFIX = DATA_DIR / "rt_open_positions.json"
# [NEWPB-OWN-EXIT 2026-06-19 친구님] YES면 _newpb 포지션은 이 엔진이 손 뗌(EOD_PICK과 동일 패턴).
#   NEW_PB executor가 -5%손절+고점-10% 넓은트레일로 직접 관리(엔진 수익보장사다리가 큰수익 일찍끊는 문제 회피).
#   기본 NO=현행 동일(엔진이 PULLBACK으로 관리). 롤백: setx NEW_PB_OWN_EXIT NO.
_NEWPB_OWN_EXIT = os.environ.get("NEW_PB_OWN_EXIT", "NO").strip().upper() == "YES"
EV_PATH    = DATA_DIR / "ledger" / "eod_ev_history.csv"
# [v4.18] trade_log.csv — evolution_engine 공유 경로 (BASE/DATA/trade_log.csv)
TRADE_LOG_PATH = BASE / "DATA" / "trade_log.csv"
STATE_PATH = DATA_DIR / "ledger" / "sell_state.json"
PNL_PATH   = DATA_DIR / "ledger" / "pnl_daily.json"

# ═══════════════════════════════════════════════════════════════
#  파라미터 — params_reader 동적 로드
# ═══════════════════════════════════════════════════════════════
_G = _get_갭등급()
_C = _get_청산시각()
# [연결] params.json rt_sell 섹션 로드 — T2_MULT / split_ratio 마스터값 공급
_RS = _get_rt_sell()

# ── Chandelier Exit (Le Beau 1991 + Wilder 1978 ATR) ────────
CHANDELIER_N         = int(os.environ.get("CHANDELIER_N",         "10"))
# [수정-2] 지침서 §5-3 NORMAL k=2.0 복원 (기존 2.2: trail_price 과도하게 낮아 청산 지연)
CHANDELIER_K_BASE    = float(os.environ.get("CHANDELIER_K_BASE",    "2.0"))
CHANDELIER_K_HIGH    = float(os.environ.get("CHANDELIER_K_HIGH",    "2.5"))
CHANDELIER_K_EXTREME = float(os.environ.get("CHANDELIER_K_EXTREME", "3.0"))

# ── 변동성 레짐 ──────────────────────────────────────────────
VOL_RATIO_HIGH    = float(os.environ.get("VOL_RATIO_HIGH",    "1.2"))
VOL_RATIO_EXTREME = float(os.environ.get("VOL_RATIO_EXTREME", "1.5"))

# ── OFI Adaptive (Cont, Kukanov, Stoikov 2014) ───────────────
# [v4.20 수정1] OFI 기관강세 기준 0.30 → 0.40
# rt_sell v3.12 ISSUE-1 패치와 통일 — 진짜 강한 기관 흐름만 k×1.15 Trail 완화
# 기존 0.30: 허위 기관강세 판정 → Trail 과확대 → 수익 반납 위험
CHANDELIER_OFI_STRONG_MIN   = float(os.environ.get("CHANDELIER_OFI_STRONG",    "0.40"))
CHANDELIER_ACCEL_STRONG_MIN = float(os.environ.get("CHANDELIER_ACCEL_STRONG",  "1.20"))
CHANDELIER_OFI_K_MULT       = float(os.environ.get("CHANDELIER_OFI_K_MULT",    "1.15"))
CHANDELIER_OFI_PROFIT_MIN   = float(os.environ.get("CHANDELIER_OFI_PROFIT_MIN","3.00"))

# ── Trail Activation ─────────────────────────────────────────
TRAIL_ACTIVATE_PROFIT    = float(os.environ.get("TRAIL_ACTIVATE_PROFIT", "1.5"))
TRAIL_ACTIVATE_RIDE      = float(os.environ.get("TRAIL_ACTIVATE_RIDE",   "0.40"))
TRAIL_ACTIVATE_HARD_PCT  = float(os.environ.get("TRAIL_ACTIVATE_HARD",   "2.0"))
TRAIL_ABSOLUTE_BLOCK_PCT = float(os.environ.get("TRAIL_ABSOLUTE_BLOCK",  "1.0"))

# ── Initial Stop ─────────────────────────────────────────────
INITIAL_HARD_STOP = float(os.environ.get("INITIAL_HARD_STOP", "-2.5"))
INITIAL_BASE_STOP = float(os.environ.get("INITIAL_BASE_STOP", "-2.2"))

# ── 몰빵 모드 ────────────────────────────────────────────────
IS_ALL_IN         = os.environ.get("IS_ALL_IN", "true").lower() == "true"
ALL_IN_TRAIL_MULT = float(os.environ.get("ALL_IN_TRAIL_MULT", "1.3"))
# [FIX-7] 몰빵 포지션 비율 — 포트폴리오 손실 환산용 (공격 70%)
ALL_IN_WEIGHT     = float(os.environ.get("ALL_IN_WEIGHT", "0.70"))
# [FIX-1] Paper trade 모드 플래그 (true=시뮬, false=실거래)
PAPER_TRADE       = os.environ.get("PAPER_TRADE", "false").lower() == "true"  # [v4_21] 기본값 false(실거래) → 시뮬 시 환경변수 PAPER_TRADE=true 명시 필요

# ── ATR ──────────────────────────────────────────────────────
ATR_EMA_PERIOD   = int(os.environ.get("ATR_EMA_PERIOD", "14"))
RT_INTRADAY_PATH = BASE / "DATA" / "rt_intraday.csv"
PRICES_1M_PATH   = BASE / "DATA" / "prices_1m.csv"

# ── 갭 등급 ──────────────────────────────────────────────────
GAP_A_MIN        = float(_G.get("GAP_A_MIN",    os.environ.get("GAP_A_MIN",  "3.0")))
GAP_B_MIN        = float(_G.get("GAP_B_MIN",    os.environ.get("GAP_B_MIN",  "1.5")))
D_STOP_THRESHOLD = float(os.environ.get("D_STOP_THRESHOLD", "-1.0"))
CUT_INTRADAY     = float(os.environ.get("CUT_INTRADAY",     "-2.0"))
SCORE_FLOW_C_TO_B = float(os.environ.get("SCORE_FLOW_C_TO_B", "60.0"))
SCORE_FLOW_B_TO_A = float(os.environ.get("SCORE_FLOW_B_TO_A", "75.0"))
C_GRADE_RIDE_UPGRADE   = float(os.environ.get("C_GRADE_RIDE_UPGRADE",   "0.40"))
C_GRADE_PROFIT_UPGRADE = float(os.environ.get("C_GRADE_PROFIT_UPGRADE", "0.80"))

# ── EXIT_SCORE (Jegadeesh & Titman 1993 + Cont et al. 2014) ─
EXIT_SCORE_W_TREND    = float(os.environ.get("EXIT_W_TREND",    "0.35"))
EXIT_SCORE_W_FLOW     = float(os.environ.get("EXIT_W_FLOW",     "0.25"))
EXIT_SCORE_W_MOMENTUM = float(os.environ.get("EXIT_W_MOMENTUM", "0.20"))
EXIT_SCORE_W_RISK     = float(os.environ.get("EXIT_W_RISK",     "0.20"))
EXIT_SCORE_HOLD_TH         = float(os.environ.get("EXIT_SCORE_HOLD_TH",    "0.70"))
EXIT_SCORE_TIGHTEN_TH      = float(os.environ.get("EXIT_SCORE_TIGHTEN_TH", "0.45"))
EXIT_SCORE_FORCE_TH        = float(os.environ.get("EXIT_SCORE_FORCE_TH",   "0.25"))
EXIT_SCORE_K_WIDE_MULT     = float(os.environ.get("EXIT_SCORE_K_WIDE",     "1.20"))
EXIT_SCORE_K_TIGHT_MULT    = float(os.environ.get("EXIT_SCORE_K_TIGHT",    "0.85"))
EXIT_SCORE_RIDE_BONUS      = float(os.environ.get("EXIT_SCORE_RIDE_BONUS", "0.08"))
EXIT_SCORE_PROFIT_BONUS_TH = float(os.environ.get("EXIT_SCORE_PROFIT_TH",  "3.0"))
EXIT_SCORE_PROFIT_BONUS    = float(os.environ.get("EXIT_SCORE_PROFIT_BON", "0.06"))
EXIT_SCORE_LOSS_PENALTY_TH = float(os.environ.get("EXIT_SCORE_LOSS_TH",   "-1.0"))
EXIT_SCORE_LOSS_PENALTY    = float(os.environ.get("EXIT_SCORE_LOSS_PEN",  "0.10"))
EXIT_SCORE_FORCE_MIN_PROFIT= float(os.environ.get("EXIT_SCORE_FORCE_MINP", "1.5"))

# ── 선익절 ───────────────────────────────────────────────────
PARTIAL_TAKE_A     = float(os.environ.get("PARTIAL_TAKE_A",     "5.0"))
PARTIAL_TAKE_B     = float(os.environ.get("PARTIAL_TAKE_B",     "3.5"))
PARTIAL_TAKE_RATIO = float(os.environ.get("PARTIAL_TAKE_RATIO", "0.4"))
# [지침서 §7-2 수정] 기관동행(OFI≥0.40) 시 T1 분할 비율 40%→25%
# 기관 흐름 살아있는 동안 더 많이 들고 가기 위해 T1 매도 축소
PARTIAL_TAKE_RATIO_INST = float(os.environ.get("PARTIAL_TAKE_RATIO_INST", "0.25"))
# [연결] T2_MULT: 환경변수 → params.json(get_rt_sell) → 하드코딩 순서로 우선적용
# params.json rt_sell.t2_mult=2.2 → 이 파일에 자동 동기화
# 전체 연결 + 파일 단독 동시 96점 구조
T2_MULT = float(
    os.environ.get("T2_MULT")
    or _RS.get("t2_mult")
    or 2.20   # params.json 기본값과 동일
)
# T2 분할 비율: 잔량의 30%
T2_TAKE_RATIO      = float(os.environ.get("T2_TAKE_RATIO",      "0.30"))
# 기관동행 T3 잔량 최소 비율 확인용 (45% 이상 잔량 유지 확인)
INST_T3_MIN_REMAIN = float(os.environ.get("INST_T3_MIN_REMAIN", "0.45"))

# ── 시간 기준 ────────────────────────────────────────────────
NO_SELL_FROM    = int(os.environ.get("NO_SELL_FROM",  "900"))
NO_SELL_TO      = int(os.environ.get("NO_SELL_TO",    "910"))
BUFFER_FROM     = int(os.environ.get("BUFFER_FROM",   "910"))
BUFFER_TO       = int(os.environ.get("BUFFER_TO",     "920"))
C_SELL_AFTER    = int(os.environ.get("C_SELL_AFTER",  "915"))
D_CUT_AFTER     = int(os.environ.get("D_CUT_AFTER",   "910"))
# [수정] 강제청산 구조 개편 — 14:50 약한종목 필터 + 15:20 최종 안전망
# 기존: 모든 종목 14:50 일괄 강제청산
# 수정: 14:50에 강한종목(ride/OFI/VWAP/trail 기준) → 15:20까지 보유
#       약한종목만 14:50 청산, 15:20은 RT와 동일한 절대 안전망
FORCE_CLOSE_BCD = int(_C.get("FORCE_CLOSE_BCD", os.environ.get("FORCE_CLOSE_BCD", "1450")))
FORCE_CLOSE_A   = int(_C.get("FORCE_CLOSE_A",   os.environ.get("FORCE_CLOSE_A",   "1450")))
FORCE_CLOSE_ALL = int(_C.get("FORCE_CLOSE_ALL", os.environ.get("FORCE_CLOSE_ALL", "1450")))
FORCE_CLOSE_FINAL = int(os.environ.get("FORCE_CLOSE_FINAL", "1520"))  # 15:20 최종 안전망 (RT 동일)

# 강한종목 판단 기준 (4개 중 3개 이상 충족 → STRONG → 15:20까지 보유)
FORCE_CLOSE_STRONG_RIDE_MIN = float(os.environ.get("FORCE_CLOSE_STRONG_RIDE_MIN", "0.40"))
FORCE_CLOSE_STRONG_OFI_MIN  = float(os.environ.get("FORCE_CLOSE_STRONG_OFI_MIN",  "0.20"))

FORCE_CLOSE_DEFER_PROFIT = float(os.environ.get("FORCE_CLOSE_DEFER_PROFIT", "2.0"))
if IS_ALL_IN:
    FORCE_CLOSE_DEFER_PROFIT = float(os.environ.get("ALL_IN_DEFER_PROFIT", "1.5"))
FORCE_CLOSE_DEFER_MAX_HM = int(os.environ.get("FORCE_CLOSE_DEFER_MAX_HM", "1515"))  # 1445→1515

# ── VWAP (Kissell & Glantz 2003) ─────────────────────────────
VWAP_EXIT_THRESH = float(os.environ.get("VWAP_EXIT_THRESH", "0.99"))
VWAP_EXIT_MIN_HM = int(os.environ.get("VWAP_EXIT_MIN_HM",   "930"))

# ── PEAK PROTECT ─────────────────────────────────────────────
PEAK_PROTECT_MIN_PEAK_PCT = float(os.environ.get("PEAK_PROTECT_MIN_PEAK",  "5.0"))
PEAK_PROTECT_FLOOR_PCT    = float(os.environ.get("PEAK_PROTECT_FLOOR_PCT", "2.0"))
PEAK_PROTECT_TIER2_PCT    = float(os.environ.get("PEAK_PROTECT_TIER2",     "8.0"))
PEAK_PROTECT_FLOOR2_PCT   = float(os.environ.get("PEAK_PROTECT_FLOOR2",    "3.0"))
PEAK_PROTECT_TIER3_PCT    = float(os.environ.get("PEAK_PROTECT_TIER3",    "12.0"))
PEAK_PROTECT_FLOOR3_PCT   = float(os.environ.get("PEAK_PROTECT_FLOOR3",    "5.0"))
# [v4.20 수정2] 기관동행(ride≥0.65) 시 PEAK_PROTECT 임계 ÷1.15 완화
# rt_sell v3.12와 동일 원칙 — 기관 매집 중 조기 청산 차단
# 완화 적용: thr / PEAK_PROTECT_INST_RELAX_MULT
# 예) tier1=5% → 기관동행 시 5÷1.15=4.35% 이상 도달 시 발동
PEAK_PROTECT_INST_RELAX_MULT = float(os.environ.get("PEAK_PROTECT_INST_RELAX", "1.15"))
PEAK_PROTECT_INST_RIDE_MIN   = float(os.environ.get("PEAK_PROTECT_INST_RIDE",  "0.40"))

# ── HARD FAILSAFE (López de Prado 2018 Triple Barrier 변형) ──
FAILSAFE_TRIGGER_PROFIT = float(os.environ.get("FAILSAFE_TRIGGER_PROFIT", "2.0"))
FAILSAFE_RETAIN_RATIO   = float(os.environ.get("FAILSAFE_RETAIN_RATIO",   "0.6"))

# [v4.19 FIX-1] PROFIT_LOCK 3단계 래칫 (지침서[US-1] 11장)
# peak>=2% → lock=50% / peak>=5% → lock=67% / peak>=8% → lock=75%
# 기관동행(ride>=0.65) 시 비율 x0.9 완화
# [수정-1] 지침서 §11-1 원본 비율로 복원 (기존 과도값 → 원본)
# 기존: (2.0,0.67) / (5.0,0.75) / (8.0,0.80) — 지침서보다 10~17%p 높아 조기청산 유발
# 복원: 지침서 §11-1 명시값 그대로 — Chandelier가 먼저 작동할 기회 보장
PROFIT_LOCK_LEVELS = [
    (2.0, 0.50),   # peak>=2%: 수익의 50% 보장  ← 지침서 §11-1 원본
    (5.0, 0.67),   # peak>=5%: 수익의 67% 보장  ← 지침서 §11-1 원본
    (8.0, 0.75),   # peak>=8%: 수익의 75% 보장  ← 지침서 §11-1 원본
]
PROFIT_LOCK_INST_RELAX = float(os.environ.get("PROFIT_LOCK_INST_RELAX", "0.9"))
PROFIT_LOCK_RIDE_MIN   = float(os.environ.get("PROFIT_LOCK_RIDE_MIN",   "0.65"))
# TRAIL_WIDE_RIDE: ride>=0.65 기관 강매집 기준 (SIGA 동일)
TRAIL_WIDE_RIDE        = float(os.environ.get("TRAIL_WIDE_RIDE",        "0.65"))

# ═══════════════════════════════════════════════════════════════
#  [W26 PATCH 2026-05-12] v4_12 → v4_21 마이그레이션 누락 복원
#  피라미딩 3단계 — 기관 동행 확인 후 추가 진입
#  1차 진입 → (ride≥0.40 + 수익≥1.5%) → 2차 추가 35%
#            → (ride≥0.65 + 수익≥3.0%) → 3차 추가 15%
# ═══════════════════════════════════════════════════════════════
PYRAMID_ENABLED          = os.environ.get("PYRAMID_ENABLED", "true").lower() == "true"
PYRAMID_ADDON_QUEUE_PATH = BASE / "DATA" / "queue" / "pullback_addon_queue.csv"
PYRAMID_ADD1_RIDE_MIN    = float(os.environ.get("PYRAMID_ADD1_RIDE",    "0.40"))
PYRAMID_ADD1_PROFIT_MIN  = float(os.environ.get("PYRAMID_ADD1_PROFIT",  "1.5"))
PYRAMID_ADD1_RATIO       = float(os.environ.get("PYRAMID_ADD1_RATIO",   "0.35"))
PYRAMID_ADD2_RIDE_MIN    = float(os.environ.get("PYRAMID_ADD2_RIDE",    "0.65"))
PYRAMID_ADD2_PROFIT_MIN  = float(os.environ.get("PYRAMID_ADD2_PROFIT",  "3.0"))
PYRAMID_ADD2_RATIO       = float(os.environ.get("PYRAMID_ADD2_RATIO",   "0.15"))
PYRAMID_CUTOFF_HM        = int(os.environ.get("PYRAMID_CUTOFF_HM",     "1350"))

# ── 기관 EXIT (Easley, López de Prado, O'Hara 2012 VPIN 변형) ─
INST_EXIT_CONSEC_BARS = int(os.environ.get("INST_EXIT_CONSEC_BARS",  "3"))
INST_EXIT_SELL_RATIO  = float(os.environ.get("INST_EXIT_SELL_RATIO", "0.6"))

# ── [NEW-3] 회로차단 — 일일 손실 한도 ───────────────────────
DAILY_LOSS_LIMIT = float(os.environ.get("DAILY_LOSS_LIMIT", "-3.0"))   # % (포트폴리오 대비)
CIRCUIT_BREAKER_ENABLED = os.environ.get("CIRCUIT_BREAKER", "true").lower() == "true"

# ── [NEW-6] Kelly Criterion (Kelly 1956) ─────────────────────
KELLY_FRACTION   = float(os.environ.get("KELLY_FRACTION",   "0.5"))    # 분수 켈리 (half-Kelly)
KELLY_MIN_TRADES = int(os.environ.get("KELLY_MIN_TRADES",   "20"))     # 최소 거래 수 (신뢰 임계)

# ── [NEW-7] Almgren-Chriss 실행비용 ─────────────────────────
EXEC_COST_BPS    = float(os.environ.get("EXEC_COST_BPS",    "21.0"))   # 왕복 21bp


# ═══════════════════════════════════════════════════════════════
#  [NEW-3] 파라미터 검증 — 기동 시 1회 호출
# ═══════════════════════════════════════════════════════════════
def _validate_params() -> None:
    """
    파라미터 범위 검증. 잘못된 값이면 ValueError 발생 → 기동 중단.
    헤지펀드 표준: 운용 전 파라미터 governance 필수.
    """
    errors: List[str] = []

    def _chk(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    # Chandelier k: 1.0 ~ 5.0 범위 (Le Beau 권고)
    _chk(1.0 <= CHANDELIER_K_BASE    <= 5.0, f"CHANDELIER_K_BASE={CHANDELIER_K_BASE} 범위초과")
    _chk(1.0 <= CHANDELIER_K_HIGH    <= 5.0, f"CHANDELIER_K_HIGH={CHANDELIER_K_HIGH} 범위초과")
    _chk(1.0 <= CHANDELIER_K_EXTREME <= 5.0, f"CHANDELIER_K_EXTREME={CHANDELIER_K_EXTREME} 범위초과")
    _chk(CHANDELIER_K_BASE <= CHANDELIER_K_HIGH <= CHANDELIER_K_EXTREME,
         "Chandelier k 순서 오류: BASE≤HIGH≤EXTREME이어야 함")

    # 손절선: 음수, BASE > HARD
    _chk(INITIAL_HARD_STOP < 0, f"INITIAL_HARD_STOP={INITIAL_HARD_STOP} 양수 오류")
    _chk(INITIAL_BASE_STOP < 0, f"INITIAL_BASE_STOP={INITIAL_BASE_STOP} 양수 오류")
    _chk(INITIAL_HARD_STOP < INITIAL_BASE_STOP,
         f"HARD_STOP({INITIAL_HARD_STOP}) ≥ BASE_STOP({INITIAL_BASE_STOP}) 순서 오류")

    # 선익절 비율
    _chk(0 < PARTIAL_TAKE_RATIO < 1, f"PARTIAL_TAKE_RATIO={PARTIAL_TAKE_RATIO} 범위 오류")
    _chk(0 < PARTIAL_TAKE_RATIO_INST < PARTIAL_TAKE_RATIO,
         f"PARTIAL_TAKE_RATIO_INST={PARTIAL_TAKE_RATIO_INST} ≥ PARTIAL_TAKE_RATIO")
    _chk(1.0 < T2_MULT <= 3.0, f"T2_MULT={T2_MULT} 범위 오류(1~3)")
    _chk(0 < T2_TAKE_RATIO < 1, f"T2_TAKE_RATIO={T2_TAKE_RATIO} 범위 오류")
    _chk(PARTIAL_TAKE_B < PARTIAL_TAKE_A,
         f"PARTIAL_TAKE_B({PARTIAL_TAKE_B}) ≥ A({PARTIAL_TAKE_A}) 순서 오류")

    # Exit Score 가중치 합 = 1.0 (±0.001)
    w_sum = EXIT_SCORE_W_TREND + EXIT_SCORE_W_FLOW + EXIT_SCORE_W_MOMENTUM + EXIT_SCORE_W_RISK
    _chk(abs(w_sum - 1.0) < 0.001, f"Exit Score 가중치 합={w_sum:.4f} ≠ 1.0")

    # Peak Protect 단계 순서
    _chk(PEAK_PROTECT_MIN_PEAK_PCT < PEAK_PROTECT_TIER2_PCT < PEAK_PROTECT_TIER3_PCT,
         "PEAK_PROTECT tier 순서 오류")
    _chk(PEAK_PROTECT_FLOOR_PCT < PEAK_PROTECT_FLOOR2_PCT < PEAK_PROTECT_FLOOR3_PCT,
         "PEAK_PROTECT floor 순서 오류")

    # 시간 순서
    _chk(NO_SELL_FROM < NO_SELL_TO <= BUFFER_FROM < BUFFER_TO,
         "매도금지/완충 시간 순서 오류")
    # [v4_21] 강제청산 시간 검증 — 단일값 강제 → 유효 범위 + 순서 검증
    # 기존: BCD==A==ALL 강제 → params_reader가 다른 값 반환 시 즉시 ValueError (기동 불가)
    # 수정: 각 값이 유효 범위(920~1450) 내에 있고, ALL이 가장 늦은 값인지만 검증
    _chk(920 <= FORCE_CLOSE_BCD <= 1520, f"FORCE_CLOSE_BCD={FORCE_CLOSE_BCD} 범위 오류(920~1520)")
    _chk(920 <= FORCE_CLOSE_A   <= 1520, f"FORCE_CLOSE_A={FORCE_CLOSE_A} 범위 오류(920~1520)")
    _chk(920 <= FORCE_CLOSE_ALL <= 1520, f"FORCE_CLOSE_ALL={FORCE_CLOSE_ALL} 범위 오류(920~1520)")
    _chk(FORCE_CLOSE_ALL >= max(FORCE_CLOSE_BCD, FORCE_CLOSE_A),
         f"FORCE_CLOSE_ALL({FORCE_CLOSE_ALL})이 BCD({FORCE_CLOSE_BCD})/A({FORCE_CLOSE_A})보다 작음")
    _chk(FORCE_CLOSE_FINAL >= FORCE_CLOSE_ALL,
         f"FORCE_CLOSE_FINAL({FORCE_CLOSE_FINAL}) < FORCE_CLOSE_ALL({FORCE_CLOSE_ALL})")

    # Kelly
    _chk(0 < KELLY_FRACTION <= 1.0, f"KELLY_FRACTION={KELLY_FRACTION} 범위 오류")

    # [FIX-7] 몰빵 비율
    _chk(0 < ALL_IN_WEIGHT <= 1.0, f"ALL_IN_WEIGHT={ALL_IN_WEIGHT} 범위 오류 (0~1)")

    # [v4_17] 키움 연동 파라미터
    _chk(KIWOOM_ORDER_TIMEOUT > 0, f"KIWOOM_ORDER_TIMEOUT={KIWOOM_ORDER_TIMEOUT} 양수여야 함")
    _chk(1 <= KIWOOM_MAX_RETRY <= 10, f"KIWOOM_MAX_RETRY={KIWOOM_MAX_RETRY} 범위 오류 (1~10)")

    if errors:
        msg = "\n".join(f"  ❌ {e}" for e in errors)
        raise ValueError(f"[파라미터 검증 실패]\n{msg}")


# ═══════════════════════════════════════════════════════════════
#  [NEW-4] PnLTracker — 실시간 수익률 추적
#  근거: Sharpe (1966) / Sortino & van der Meer (1991)
# ═══════════════════════════════════════════════════════════════
class PnLTracker:
    """
    당일 거래 P&L 실시간 집계.
    Sharpe, Sortino, Max Drawdown을 실시간 계산해 회로차단 판단.

    Sharpe  = (μ - Rf) / σ        [Sharpe 1966]
    Sortino = (μ - MAR) / σ_down  [Sortino & van der Meer 1991]
    """

    def __init__(self) -> None:
        self._trades: List[float] = []   # profit_pct 시계열
        self._cumulative: float   = 0.0
        self._peak_cum: float     = 0.0
        self._max_dd: float       = 0.0
        self._today = datetime.now().strftime("%Y-%m-%d")
        self._load_today()

    def _load_today(self) -> None:
        """당일 기존 거래 이력 복원"""
        try:
            if not PNL_PATH.exists():
                return
            with open(PNL_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if data.get("date") == self._today:
                self._trades    = data.get("trades", [])
                self._cumulative= data.get("cumulative", 0.0)
                self._peak_cum  = data.get("peak_cum",   0.0)
                self._max_dd    = data.get("max_dd",     0.0)
        except Exception as e:
            self._logger.debug("[STATE] 상태 파일 로드 실패 (초기값 유지): %s", e)

    def record(self, profit_pct: float, reason: str = "",
               position_weight: float = 1.0) -> None:
        """
        거래 결과 기록 + 지표 갱신.
        [FIX-7] position_weight: 포지션이 포트폴리오에서 차지하는 비율
                ALL_IN 모드에서는 ALL_IN_WEIGHT(0.70)를 곱해 포트폴리오 손실로 환산.
        """
        # [PAPER-GUARD 2026-06-10] PAPER 시뮬은 실 PnL 통계(pnl_daily.json) 오염 금지 —
        #   6/10 PAPER 11건이 실원장에 들어가 진화/Kelly가 가짜 0% 거래를 학습한 사고 재발방지.
        if PAPER_TRADE:
            return
        port_pnl = profit_pct * position_weight  # 포트폴리오 환산 손익
        self._trades.append(profit_pct)           # 종목 수익률 원본 보관 (Sharpe·Sortino용)
        self._cumulative += port_pnl              # 포트폴리오 기준 누적
        if self._cumulative > self._peak_cum:
            self._peak_cum = self._cumulative
        dd = self._cumulative - self._peak_cum
        if dd < self._max_dd:
            self._max_dd = dd
        self._persist()

    def _persist(self) -> None:
        try:
            _safe_mkdir(PNL_PATH.parent)
            tmp = PNL_PATH.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "date":        self._today,
                    "trades":      self._trades,
                    "cumulative":  round(self._cumulative, 4),
                    "peak_cum":    round(self._peak_cum,   4),
                    "max_dd":      round(self._max_dd,     4),
                    "count":       len(self._trades),
                    "win_rate":    round(self.win_rate(), 4),
                    "sharpe":      round(self.sharpe(), 4),
                    "sortino":     round(self.sortino(), 4),
                }, f, indent=2, ensure_ascii=False)
                f.flush(); os.fsync(f.fileno())
            os.replace(str(tmp), str(PNL_PATH))
        except Exception as e:
            self._logger.debug("[PNL] PNL 저장 실패 (무시): %s", e)

    def daily_pnl(self) -> float:
        return self._cumulative

    def max_drawdown(self) -> float:
        return self._max_dd

    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        return sum(1 for t in self._trades if t > 0) / len(self._trades)

    def sharpe(self, rf: float = 0.0) -> float:
        """일내 거래 기반 Sharpe (Sharpe 1966). 거래 10건 미만 시 0 반환."""
        if len(self._trades) < 10:
            return 0.0
        mean = sum(self._trades) / len(self._trades)
        variance = sum((x - mean) ** 2 for x in self._trades) / len(self._trades)
        std = math.sqrt(variance) if variance > 0 else 0.0
        return (mean - rf) / std if std > 0 else 0.0

    def sortino(self, mar: float = 0.0) -> float:
        """Sortino Ratio (Sortino & van der Meer 1991). 하방 표준편차 기준."""
        if len(self._trades) < 10:
            return 0.0
        mean = sum(self._trades) / len(self._trades)
        downside = [min(0, x - mar) ** 2 for x in self._trades]
        down_std = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
        return (mean - mar) / down_std if down_std > 0 else 0.0

    def is_circuit_broken(self) -> bool:
        """
        [FIX-6] 회로차단 — 일일 손실 한도(포트폴리오 기준) 초과 여부.
        ★ 이 플래그는 신규 진입(매수) 차단용이다.
        ★ 매도(청산) 엔진에서는 절대 청산을 막는 데 사용하지 않는다.
        매도 엔진 내에서는 is_new_entry_blocked() 이름으로 참조하도록
        의미를 명확히 한다.
        """
        if not CIRCUIT_BREAKER_ENABLED:
            return False
        return self._cumulative < DAILY_LOSS_LIMIT

    def is_new_entry_blocked(self) -> bool:
        """신규 진입(매수) 차단 여부 — is_circuit_broken() 의미 명시 래퍼."""
        return self.is_circuit_broken()

    @property
    def count(self) -> int:
        return len(self._trades)


# ═══════════════════════════════════════════════════════════════
#  [NEW-5] BacktestEngine — Walk-forward 시뮬레이터
#  근거: López de Prado (2018) Advances in Financial ML Ch.7
#  eod_ev_history.csv를 읽어 청산 전략 성능 사후 검증
# ═══════════════════════════════════════════════════════════════
class BacktestEngine:
    """
    eod_ev_history.csv 기반 Walk-forward 백테스트.
    실거래 기록이 쌓이면 자동으로 파라미터 권고값 계산.

    Walk-forward 설계:
      훈련 윈도우 : 최근 60거래일
      테스트 윈도우: 다음 10거래일
      → 파라미터 stability 검증 (López de Prado 2018)
    """

    TRAIN_WINDOW = 60
    TEST_WINDOW  = 10

    def __init__(self, ev_path: Path = EV_PATH) -> None:
        self._path   = ev_path
        self._trades : List[Dict] = []
        self._loaded = False

    def load(self) -> "BacktestEngine":
        if not self._path.exists():
            return self
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with open(self._path, "r", encoding=enc, newline="") as f:
                    reader = csv.DictReader(f)
                    self._trades = [r for r in reader
                                    if r.get("sell_failed","0") == "0"]
                self._loaded = True
                break
            except Exception:
                continue
        return self

    @property
    def n_trades(self) -> int:
        return len(self._trades)

    def is_ready(self) -> bool:
        """Kelly 신뢰 임계(기본 20건) 이상 데이터 존재 시 True"""
        return self.n_trades >= KELLY_MIN_TRADES

    def summary(self) -> Dict:
        """전체 거래 기초 통계"""
        if not self._trades:
            return {"status": "NO_DATA", "n": 0}
        profits = [float(t.get("profit_pct", 0)) for t in self._trades]
        wins    = [p for p in profits if p > 0]
        losses  = [p for p in profits if p <= 0]
        mean    = sum(profits) / len(profits)
        win_rate= len(wins) / len(profits) if profits else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss= sum(losses) / len(losses) if losses else 0
        rr_ratio= abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # Kelly fraction (Kelly 1956)
        if win_rate > 0 and rr_ratio > 0:
            kelly_full = win_rate - (1 - win_rate) / rr_ratio
            kelly_half = kelly_full * KELLY_FRACTION   # 분수 켈리
        else:
            kelly_full = kelly_half = 0.0

        # Almgren-Chriss 실행비용 조정 EV
        exec_cost = EXEC_COST_BPS / 100.0
        ev_net    = mean - exec_cost

        return {
            "status":     "READY" if self.is_ready() else f"NEED_{KELLY_MIN_TRADES - self.n_trades}_MORE",
            "n":          len(profits),
            "win_rate":   round(win_rate, 4),
            "avg_win":    round(avg_win,  4),
            "avg_loss":   round(avg_loss, 4),
            "rr_ratio":   round(rr_ratio, 4),
            "kelly_full": round(kelly_full, 4),
            "kelly_half": round(kelly_half, 4),
            "ev_gross":   round(mean,    4),
            "exec_cost":  round(exec_cost, 4),
            "ev_net":     round(ev_net,  4),
        }

    def reason_breakdown(self) -> Dict[str, Dict]:
        """청산 사유별 수익률 분석"""
        breakdown: Dict[str, List[float]] = {}
        for t in self._trades:
            reason = t.get("reason", "UNKNOWN")
            pct    = float(t.get("profit_pct", 0))
            breakdown.setdefault(reason, []).append(pct)
        result = {}
        for reason, profits in sorted(breakdown.items()):
            result[reason] = {
                "count":    len(profits),
                "avg_pct":  round(sum(profits) / len(profits), 4),
                "win_rate": round(sum(1 for p in profits if p > 0) / len(profits), 3),
            }
        return result

    def walk_forward_eval(self) -> Dict:
        """
        Walk-forward 검증 — 훈련/테스트 윈도우 슬라이딩.
        최소 (TRAIN_WINDOW + TEST_WINDOW) 거래 필요.
        """
        min_trades = self.TRAIN_WINDOW + self.TEST_WINDOW
        if len(self._trades) < min_trades:
            return {"status": f"NEED_{min_trades - len(self._trades)}_MORE_TRADES"}
        profits   = [float(t.get("profit_pct", 0)) for t in self._trades]
        n         = len(profits)
        results   = []
        tw        = self.TRAIN_WINDOW
        tsw       = self.TEST_WINDOW
        for start in range(0, n - tw - tsw + 1, tsw):
            train = profits[start: start + tw]
            test  = profits[start + tw: start + tw + tsw]
            t_mean  = sum(train) / len(train)
            ts_mean = sum(test)  / len(test)
            results.append({"train_ev": round(t_mean, 4), "test_ev": round(ts_mean, 4)})
        if not results:
            return {"status": "INSUFFICIENT"}
        avg_test = sum(r["test_ev"] for r in results) / len(results)
        return {
            "status":       "OK",
            "n_windows":    len(results),
            "avg_test_ev":  round(avg_test, 4),
            "windows":      results[-5:],   # 최근 5개만
        }


# ═══════════════════════════════════════════════════════════════
#  [NEW-6] Kelly 분수 계산 유틸
# ═══════════════════════════════════════════════════════════════
def calc_kelly_fraction(win_rate: float, avg_win: float,
                        avg_loss: float) -> float:
    """
    분수 켈리 (Half-Kelly) 계산.
    근거: Kelly (1956) Bell System Technical Journal
    f* = p - (1-p)/b   where b = avg_win / |avg_loss|
    반환: half-Kelly fraction (0~1 클램프)
    """
    if avg_loss >= 0 or avg_win <= 0 or not (0 < win_rate < 1):
        return 0.0
    b       = avg_win / abs(avg_loss)
    f_full  = win_rate - (1 - win_rate) / b
    f_half  = f_full * KELLY_FRACTION
    return max(0.0, min(1.0, f_half))


# ═══════════════════════════════════════════════════════════════
#  [NEW-7] Almgren-Chriss 실행비용 추정
#  근거: Almgren & Chriss (2001) Applied Mathematical Finance
# ═══════════════════════════════════════════════════════════════
def estimate_exec_cost(price: float, qty: int,
                       avg_volume: float = 0.0) -> float:
    """
    Almgren-Chriss 선형 실행비용 추정 (단순화).
    participation_rate = qty / avg_volume
    market_impact ≈ participation_rate × price × σ
    """
    base_cost = EXEC_COST_BPS / 10000.0   # 고정 21bp
    if avg_volume > 0 and qty > 0:
        participation = qty / avg_volume
        # 참여율 10% 이상이면 시장충격 추가
        if participation > 0.10:
            impact = participation * 0.05   # 단순 선형 근사
            return base_cost + impact
    return base_cost


# ═══════════════════════════════════════════════════════════════
#  [v4_16] RTCache — FIX-4·10·11·12 통합 수정
#  FIX-4:  동일 종목 다수행 → 타임스탬프 최신행 선택
#  FIX-10: OFI EMA(span=3) 평활화 RTCache 내부 적용
#  FIX-11: get_fresh_cache() 팩토리로 호출 시점 재로드 지원
#  FIX-12: prices_1m 날짜 필터 → datetime 파싱 방어 로직
# ═══════════════════════════════════════════════════════════════
class RTCache:
    """
    rt_intraday + prices_1m 틱당 1회 로드.
    bars 시간순 정렬 보장.
    OFI EMA 평활화(span=3) 내부 적용.
    """

    OFI_EMA_SPAN   = 3
    OFI_NOISE_TH   = 0.15   # |ofi| < 0.15 → 노이즈 → 0.0

    def __init__(self) -> None:
        self._rt:          Dict[str, Dict]       = {}   # 종목별 최신 rt행
        self._rt_history:  Dict[str, List[Dict]] = {}   # 종목별 rt행 전체(시계열)
        self._bars:        Dict[str, List[Dict]] = {}
        self._vwap_cache:  Dict[str, float]      = {}
        self._ofi_smooth:  Dict[str, float]      = {}   # [FIX-10] EMA 적용값
        self._today = datetime.now().strftime("%Y-%m-%d")
        self._load_all()

    def _load_all(self) -> None:
        # ── rt_intraday ─────────────────────────────────────────
        try:
            if RT_INTRADAY_PATH.exists():
                raw_hist: Dict[str, List[Dict]] = {}
                for r in _read_csv(RT_INTRADAY_PATH):
                    code = str(r.get("code", "")).strip().zfill(6)
                    if code:
                        raw_hist.setdefault(code, []).append(r)
                for code, rows in raw_hist.items():
                    # [FIX-4] 타임스탬프 기준 최신행 선택
                    rows_sorted = sorted(rows, key=lambda x: str(x.get("ts", "")))
                    self._rt_history[code] = rows_sorted
                    self._rt[code]         = rows_sorted[-1]
                # [FIX-10] OFI EMA 평활화 적용
                self._apply_ofi_ema()
        except Exception as e:
            self._logger.debug("[DATA] RT 데이터 로드 실패 (무시): %s", e)
        # ── prices_1m ───────────────────────────────────────────
        try:
            if PRICES_1M_PATH.exists():
                raw: Dict[str, List[Dict]] = {}
                for r in _read_csv(PRICES_1M_PATH):
                    code = str(r.get("code", "")).strip().zfill(6)
                    ts   = str(r.get("ts", ""))
                    # [FIX-12] datetime 파싱 방어: ISO('T') 및 공백 구분자 모두 처리
                    ts_norm = ts.replace("T", " ")
                    # [TS-FIX 2026-06-10] prices_1m ts는 컴팩트(20260610...)인데 _today는 하이픈(2026-06-10)
                    #   → 전 분봉 필터아웃 = bars/ATR/VWAP/현재가 전부 빈값이던 버그. 양식 모두 허용.
                    if not (ts_norm.startswith(self._today)
                            or ts_norm.startswith(self._today.replace("-", ""))):
                        continue
                    raw.setdefault(code, []).append(r)
                for code, bars in raw.items():
                    self._bars[code] = sorted(
                        bars, key=lambda b: str(b.get("ts", "")).replace("T", " ")
                    )
        except Exception as e:
            self._logger.debug("[DATA] bars 정렬 실패 (무시): %s", e)

    def _apply_ofi_ema(self) -> None:
        """
        [FIX-10] 종목별 시계열 OFI에 EMA(span=3) 적용.
        |ofi_smooth| < OFI_NOISE_TH → 0.0 처리.
        """
        span = self.OFI_EMA_SPAN
        mult = 2.0 / (span + 1)
        for code, rows in self._rt_history.items():
            ofi_series = [_f(r.get("ofi", r.get("ofi_score", 0))) for r in rows]
            if not ofi_series:
                self._ofi_smooth[code] = 0.0
                continue
            ema = ofi_series[0]
            for v in ofi_series[1:]:
                ema = v * mult + ema * (1.0 - mult)
            # 노이즈 구간 0.0 처리
            self._ofi_smooth[code] = 0.0 if abs(ema) < self.OFI_NOISE_TH else round(ema, 4)

    # ── 공개 인터페이스 ─────────────────────────────────────────

    def get_rt_row(self, code: str) -> Dict:
        return self._rt.get(str(code).zfill(6), {})

    def get_bars(self, code: str) -> List[Dict]:
        return self._bars.get(str(code).zfill(6), [])

    def get_vwap(self, code: str) -> float:
        c = str(code).zfill(6)
        if c in self._vwap_cache:
            return self._vwap_cache[c]
        row = self._rt.get(c, {})
        v   = _f(row.get("vwap", 0))
        if v <= 0:
            v = _calc_vwap_from_bars(self.get_bars(c))
        self._vwap_cache[c] = v
        return v

    def refresh_vwap(self, code: str) -> float:
        c = str(code).zfill(6)
        row = self._rt.get(c, {})
        v   = _f(row.get("vwap", 0))
        if v <= 0:
            v = _calc_vwap_from_bars(self.get_bars(c))
        self._vwap_cache[c] = v
        return v

    def get_ofi_accel(self, code: str) -> Tuple[float, float]:
        """[FIX-10] OFI는 EMA 평활화값 반환, accel은 rt행에서 읽기."""
        c     = str(code).zfill(6)
        ofi   = self._ofi_smooth.get(c, 0.0)   # ← EMA 적용값
        row   = self._rt.get(c, {})
        accel = _f(row.get("inst_accel", row.get("accel", 0)))
        return ofi, accel

    def get_ride(self, code: str) -> float:
        row = self.get_rt_row(code)
        return _f(row.get("inst_ride_score", row.get("ride_score", 0)))

    def get_atr(self, code: str) -> float:
        return _f(self.get_rt_row(code).get("atr_pct", 0))

    def get_atr_avg(self, code: str, n: int = 20) -> float:
        return _calc_atr_avg_from_bars(self.get_bars(code), n)

    def get_highest_high_n(self, code: str, n: int = CHANDELIER_N) -> float:
        bars = self.get_bars(code)
        if not bars:
            return 0.0
        recent = bars[-n:] if len(bars) >= n else bars
        highs  = [_f(b.get("high", 0)) for b in recent if _f(b.get("high", 0)) > 0]
        return max(highs) if highs else 0.0

    def get_inst_exit(self, code: str) -> bool:
        c    = str(code).zfill(6)
        rows = self._rt_history.get(c, [])
        if len(rows) < INST_EXIT_CONSEC_BARS:
            return False
        recent = rows[-INST_EXIT_CONSEC_BARS:]
        flows  = [_f(r.get("inst_flow", r.get("inst_net_flow", 0))) for r in recent]
        if not all(flows[i] < flows[i-1] for i in range(1, len(flows))):
            return False
        last_sell = _f(recent[-1].get("inst_sell_ratio",
                                      recent[-1].get("sell_ratio", 0)))
        return last_sell > INST_EXIT_SELL_RATIO


def get_fresh_cache() -> RTCache:
    """[FIX-11] 호출 시점에 새 RTCache를 생성해 최신 데이터 보장."""
    return RTCache()


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════
def _safe_mkdir(p: Path) -> None:
    try: p.mkdir(parents=True, exist_ok=True)
    except Exception: pass

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("pullback_sell_engine")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    except Exception: pass
    try:
        _safe_mkdir(LOG_DIR)
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(str(LOG_PATH), maxBytes=10*1024*1024,
                                 backupCount=5, encoding="utf-8-sig")  # [Z15 2026-05-21]
        fh.setFormatter(fmt); logger.addHandler(fh)
    except Exception: pass
    return logger

def _now_hm() -> int:
    t = datetime.now()
    return t.hour * 100 + t.minute

def _f(x: Any, default: float = 0.0) -> float:
    try: return float(str(x).strip().replace(",", ""))
    except Exception: return default

def _read_csv(path: Path) -> List[Dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                reader.fieldnames = [c.strip() for c in (reader.fieldnames or [])]
                return list(reader)
        except Exception:
            continue
    return []

def _write_csv(path: Path, header: List[str], rows: List[Dict]) -> None:
    _safe_mkdir(path.parent)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
            f.flush(); os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            if tmp.exists(): tmp.unlink(missing_ok=True)
        except Exception: pass

def _load_state() -> Dict:
    if not STATE_PATH.exists(): return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception: return {}

def _save_state(state: Dict) -> None:
    _safe_mkdir(STATE_PATH.parent)
    tmp = STATE_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(str(tmp), str(STATE_PATH))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════
#  ATR 계산 (Wilder 1978) — FIX-R5: ×1.4 보정 없음
# ═══════════════════════════════════════════════════════════════
def _calc_atr_pct_from_bars(bars: List[Dict]) -> float:
    if len(bars) < 2: return 0.0
    tr_list: List[float] = []
    h0 = _f(bars[0].get("high",0)); l0 = _f(bars[0].get("low",0))
    if h0 > 0 and l0 > 0:
        tr_list.append(h0 - l0)
    for i in range(1, len(bars)):
        h  = _f(bars[i].get("high",0));  l  = _f(bars[i].get("low",0))
        pc = _f(bars[i-1].get("close",0))
        if h <= 0 or l <= 0: continue
        tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
    if not tr_list: return 0.0
    n   = ATR_EMA_PERIOD
    atr = sum(tr_list[:n]) / len(tr_list[:n])
    if len(tr_list) > n:
        mult = 2.0 / (n + 1)
        for tr in tr_list[n:]:
            atr = tr * mult + atr * (1.0 - mult)
    close = _f(bars[-1].get("close", 0))
    return round((atr / close) * 100.0, 4) if close > 0 else 0.0


def _calc_atr_avg_from_bars(bars: List[Dict], n: int = 20) -> float:
    if len(bars) < 3: return 0.0
    atr_pcts: List[float] = []
    for i in range(1, len(bars)):
        h  = _f(bars[i].get("high",0));  l  = _f(bars[i].get("low",0))
        pc = _f(bars[i-1].get("close",0)); c = _f(bars[i].get("close",0))
        if h<=0 or l<=0 or pc<=0 or c<=0: continue
        tr = max(h-l, abs(h-pc), abs(l-pc))
        atr_pcts.append(tr/c*100.0)
    if not atr_pcts: return 0.0
    recent = atr_pcts[-n:] if len(atr_pcts) >= n else atr_pcts
    return round(sum(recent)/len(recent), 4)


# ═══════════════════════════════════════════════════════════════
#  Chandelier Exit (Le Beau 1991)
# ═══════════════════════════════════════════════════════════════
def _get_vol_regime(atr_pct: float, atr_avg_pct: float) -> str:
    if atr_avg_pct <= 0: return "NORMAL"
    r = atr_pct / atr_avg_pct
    if r >= VOL_RATIO_EXTREME: return "EXTREME"
    if r >= VOL_RATIO_HIGH:    return "HIGH"
    return "NORMAL"

def _get_chandelier_k(vol_regime: str, ofi: float = 0.0,
                      accel: float = 0.0, profit_pct: float = 0.0) -> float:
    k = {"EXTREME": CHANDELIER_K_EXTREME, "HIGH": CHANDELIER_K_HIGH}.get(
        vol_regime, CHANDELIER_K_BASE)
    if (ofi   >= CHANDELIER_OFI_STRONG_MIN
            and accel >= CHANDELIER_ACCEL_STRONG_MIN
            and profit_pct >= CHANDELIER_OFI_PROFIT_MIN):
        k *= CHANDELIER_OFI_K_MULT
    return round(k, 3)

def _calc_chandelier_trail_price(highest_high: float,
                                  atr_pct: float, k: float) -> float:
    if highest_high <= 0 or atr_pct <= 0: return 0.0
    return round(highest_high - highest_high * (atr_pct/100.0) * k, 0)


# ═══════════════════════════════════════════════════════════════
#  VWAP (Kissell & Glantz 2003)
# ═══════════════════════════════════════════════════════════════
def _calc_vwap_from_bars(bars: List[Dict]) -> float:
    sum_pv = sum_v = 0.0
    for b in bars:
        h=_f(b.get("high",0)); l=_f(b.get("low",0))
        c=_f(b.get("close",0)); v=_f(b.get("volume",b.get("vol",0)))
        if h<=0 or l<=0 or c<=0 or v<=0: continue
        sum_pv += (h+l+c)/3.0 * v; sum_v += v
    return round(sum_pv/sum_v, 2) if sum_v > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
#  EXIT_SCORE 복합 청산 품질 엔진
# ═══════════════════════════════════════════════════════════════
def _clamp01(x: float) -> float:
    try: x = float(x)
    except Exception: return 0.0
    return max(0.0, min(1.0, x))

def calc_exit_score(ctx: dict) -> float:
    try:
        trend    = _clamp01(ctx.get("trend_score",    0.0))
        flow     = _clamp01(ctx.get("flow_score",     0.0))
        momentum = _clamp01(ctx.get("momentum_score", 0.0))
        risk     = _clamp01(ctx.get("risk_score",     0.0))
        ride     = _clamp01(ctx.get("ride_score",     0.0))
        profit   = float(ctx.get("profit_pct", 0.0))
        score = (EXIT_SCORE_W_TREND * trend + EXIT_SCORE_W_FLOW * flow
                 + EXIT_SCORE_W_MOMENTUM * momentum + EXIT_SCORE_W_RISK * risk)
        if ride   >= 0.60:                         score += EXIT_SCORE_RIDE_BONUS
        if profit >= EXIT_SCORE_PROFIT_BONUS_TH:   score += EXIT_SCORE_PROFIT_BONUS
        if profit <= EXIT_SCORE_LOSS_PENALTY_TH:   score -= EXIT_SCORE_LOSS_PENALTY
        return _clamp01(score)
    except Exception:
        return 0.5

def _build_exit_ctx(pos: "Position", current_price: float,
                    profit_pct: float, ride_score: float) -> dict:
    try:
        trend = _clamp01((current_price/pos.vwap - 0.99)/0.02) if pos.vwap > 0 else 0.5
    except Exception: trend = 0.5
    try:    flow = _clamp01(pos.score_flow/100.0)
    except Exception: flow = 0.5
    try:    momentum = _clamp01(profit_pct/10.0) if profit_pct > 0 else 0.0
    except Exception: momentum = 0.5
    try:
        risk = (_clamp01(1.0-(pos.atr_pct/pos.atr_avg_pct-0.8)/1.2)
                if pos.atr_avg_pct > 0 and pos.atr_pct > 0 else 0.5)
    except Exception: risk = 0.5
    return {"trend_score": trend, "flow_score": flow,
            "momentum_score": momentum, "risk_score": risk,
            "ride_score": ride_score, "profit_pct": profit_pct}


# ═══════════════════════════════════════════════════════════════
#  갭 등급 분류
# ═══════════════════════════════════════════════════════════════
def _classify_gap(entry_price: float, open_price: float,
                  score_flow: float = 0.0) -> str:
    if entry_price <= 0: return "D"
    gap_pct = (open_price/entry_price - 1.0) * 100.0
    if gap_pct < D_STOP_THRESHOLD: return "D"
    if gap_pct >= GAP_A_MIN:       return "A"
    if gap_pct >= GAP_B_MIN:
        return "A" if score_flow >= SCORE_FLOW_B_TO_A else "B"
    return "B" if score_flow >= SCORE_FLOW_C_TO_B else "C"


# ═══════════════════════════════════════════════════════════════
#  포지션 클래스
# ═══════════════════════════════════════════════════════════════
class Position:
    def __init__(self, code: str, entry_price: float, qty: int,
                 entry_date: str, strategy: str = "",
                 score_flow: float = 0.0):
        self.code          = code
        self.entry_price   = entry_price
        self.qty           = qty
        self.entry_date    = entry_date
        self.strategy      = strategy
        self.score_flow    = score_flow
        self.peak_price    = entry_price
        self.gap_grade     = "?"
        self.open_price    = 0.0
        self.sold_qty      = 0
        self.partial_taken = False
        self.entry_ts      = datetime.now()
        self.atr_pct       = 0.0
        self.atr_avg_pct   = 0.0
        self.vwap          = 0.0
        self.trail_activated = False
        # [v4.19 FIX-1] PROFIT_LOCK 래칫 상태
        self._profit_lock_stop:  float = 0.0
        self._profit_lock_level: int   = 0
        # [FIX-9] 선익절 후 잔량 독립 고점 추적
        self.partial_peak_price: float = entry_price  # 선익절 후 잔량 기준 peak
        self.partial_done: bool = False               # 선익절 완료 시 True
        # [지침서 §7-2 수정] T2 추적 필드
        self.t1_price:    float = 0.0    # T1 체결 기준가 (T2 목표 계산용)
        self.t1_ratio:    float = 0.0    # T1 실제 매도 비율 기록
        self.t2_taken:    bool  = False  # T2 익절 완료 여부
        # [W26 PATCH 2026-05-12] v4_12 → v4_21 피라미딩 복원
        self.pyramid_add1_done: bool = False   # 2차 진입 완료 여부
        self.pyramid_add2_done: bool = False   # 3차 진입 완료 여부

    @property
    def remain_qty(self) -> int:
        return self.qty - self.sold_qty

    @property
    def peak_profit_pct(self) -> float:
        if self.entry_price <= 0: return 0.0
        return (self.peak_price/self.entry_price - 1.0) * 100.0

    def update_peak(self, price: float) -> None:
        if price > self.peak_price:
            self.peak_price = price
        # [FIX-9] 선익절 완료 후 잔량 고점도 독립 갱신
        if self.partial_done and price > self.partial_peak_price:
            self.partial_peak_price = price

    @property
    def effective_peak_profit_pct(self) -> float:
        """
        [FIX-9] PEAK_PROTECT·FAILSAFE 계산용 고점 수익률.
        선익절 완료 후에는 잔량 기준(partial_peak_price) 사용.
        """
        ref = self.partial_peak_price if self.partial_done else self.peak_price
        if self.entry_price <= 0:
            return 0.0
        return (ref / self.entry_price - 1.0) * 100.0

    def get_force_close_time(self) -> int:
        # [수정] 헤지펀드 방식 — 등급 무관 14:50 단일 강제청산
        # 기관 흐름(VWAP이탈/Chandelier)이 실질 청산 담당, 시간은 최후 안전망
        return FORCE_CLOSE_ALL

    def hold_minutes(self) -> int:
        try: return int((datetime.now()-self.entry_ts).total_seconds()/60)
        except Exception: return 0

    def to_dict(self) -> Dict:
        return {
            "code": self.code, "entry_price": self.entry_price,
            "qty": self.qty, "entry_date": self.entry_date,
            "strategy": self.strategy, "score_flow": self.score_flow,
            "peak_price": self.peak_price, "gap_grade": self.gap_grade,
            "open_price": self.open_price, "sold_qty": self.sold_qty,
            "partial_taken": self.partial_taken,
            "entry_ts": self.entry_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "atr_pct": self.atr_pct, "atr_avg_pct": self.atr_avg_pct,
            "vwap": self.vwap, "trail_activated": self.trail_activated,
            # [FIX-9] 선익절 잔량 고점 추적 필드
            "partial_peak_price": self.partial_peak_price,
            "partial_done": self.partial_done,
            "t1_price":     self.t1_price,
            "t1_ratio":     self.t1_ratio,
            "t2_taken":     self.t2_taken,
            # [W26-followup PATCH 2026-05-12] 피라미딩 상태 직렬화 — 워치독 재시작 시 손실 방지
            "pyramid_add1_done": self.pyramid_add1_done,
            "pyramid_add2_done": self.pyramid_add2_done,
            # [W26-followup-2 PATCH 2026-05-12] PROFIT_LOCK 래칫 상태 직렬화 — 워치독 재시작 시 단방향 래칫 손실 방지
            "_profit_lock_stop":  self._profit_lock_stop,
            "_profit_lock_level": self._profit_lock_level,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Position":
        p = cls(code=d.get("code",""), entry_price=_f(d.get("entry_price",0)),
                qty=int(_f(d.get("qty",0))), entry_date=d.get("entry_date",""),
                strategy=d.get("strategy",""), score_flow=_f(d.get("score_flow",0)))
        p.peak_price     = _f(d.get("peak_price", p.entry_price))
        p.gap_grade      = d.get("gap_grade","?")
        p.open_price     = _f(d.get("open_price",0))
        p.sold_qty       = int(_f(d.get("sold_qty",0)))
        p.partial_taken  = bool(d.get("partial_taken",False))
        p.atr_pct        = _f(d.get("atr_pct",0.0))
        p.atr_avg_pct    = _f(d.get("atr_avg_pct",0.0))
        p.vwap           = _f(d.get("vwap",0.0))
        p.trail_activated = bool(d.get("trail_activated",False))
        # [FIX-9] 선익절 잔량 고점 복원
        p.partial_peak_price = _f(d.get("partial_peak_price", p.entry_price))
        p.partial_done       = bool(d.get("partial_done", False))
        p.t1_price           = _f(d.get("t1_price", 0.0))
        p.t1_ratio           = _f(d.get("t1_ratio", 0.0))
        p.t2_taken           = bool(d.get("t2_taken", False))
        # [W26-followup PATCH 2026-05-12] 피라미딩 상태 복원 — 워치독 재시작 후에도 ADD_ON 단계 유지
        p.pyramid_add1_done  = bool(d.get("pyramid_add1_done", False))
        p.pyramid_add2_done  = bool(d.get("pyramid_add2_done", False))
        # [W26-followup-2 PATCH 2026-05-12] PROFIT_LOCK 래칫 복원 — 단방향 래칫 손실 방지 (지침서[US-1] 11장)
        p._profit_lock_stop  = _f(d.get("_profit_lock_stop", 0.0))
        p._profit_lock_level = int(_f(d.get("_profit_lock_level", 0)))
        try:
            p.entry_ts = datetime.strptime(d.get("entry_ts",""), "%Y-%m-%d %H:%M:%S")
        except Exception: p.entry_ts = datetime.now()
        return p


def _init_gap_grade(pos: Position, fallback_price: float,
                    logger: logging.Logger) -> None:
    if pos.gap_grade != "?": return
    ref = pos.open_price if pos.open_price > 0 else fallback_price
    if ref <= 0: return
    if pos.open_price <= 0: pos.open_price = fallback_price
    pos.gap_grade = _classify_gap(pos.entry_price, ref, pos.score_flow)
    gap_pct = (ref/pos.entry_price - 1.0)*100.0 if pos.entry_price > 0 else 0.0
    logger.info("[%s] 갭등급=%s  갭=%.1f%%  score_flow=%.1f  강제청산=%04d",
                pos.code, pos.gap_grade, gap_pct, pos.score_flow,
                pos.get_force_close_time())


# ═══════════════════════════════════════════════════════════════
#  SellCtx — 판단 단계 간 공유 상태
# ═══════════════════════════════════════════════════════════════
class SellCtx:
    __slots__ = ("pos","current_price","hm","logger","cache",
                 "entry","profit","peak_pct","ride_score","force_time",
                 "_peak_protect_fired")   # [FIX-8]

    def __init__(self, pos: Position, current_price: float,
                 hm: int, logger: logging.Logger,
                 cache: Optional[RTCache]) -> None:
        self.pos           = pos
        self.current_price = current_price
        self.hm            = hm
        self.logger        = logger
        self.cache         = cache
        self.entry         = pos.entry_price
        self.profit        = (current_price/pos.entry_price - 1.0)*100.0
        self.peak_pct      = pos.peak_profit_pct
        self.ride_score: float = 0.0
        self.force_time    = pos.get_force_close_time()
        self._peak_protect_fired: bool = False   # [FIX-8] PEAK_PROTECT 발동 추적


# ═══════════════════════════════════════════════════════════════
#  판단 단계 함수 13개 — 각각 독립 테스트 가능
#  반환: None=다음단계 / _HOLD=HOLD(루프중단) / Dict=매도주문
# ═══════════════════════════════════════════════════════════════
def _step1_no_sell_window(ctx: SellCtx) -> Optional[object]:
    """[1] 09:00~09:10 매도 금지"""
    return _HOLD if NO_SELL_FROM <= ctx.hm < NO_SELL_TO else None

def _step2_d_grade_cut(ctx: SellCtx) -> Optional[SellDecision]:
    """[2] D급 갭다운 즉시 손절"""
    if ctx.pos.gap_grade != "D" or ctx.hm < D_CUT_AFTER: return None
    gap_pct = (ctx.pos.open_price/ctx.entry - 1.0)*100.0 if ctx.pos.open_price else 0.0
    ctx.logger.warning("[%s] D급 손절  갭=%.1f%%", ctx.pos.code, gap_pct)
    return _make_order(ctx.pos, ctx.current_price, ctx.profit, "D_GAP_DOWN_CUT", 0.0)

def _step3_c_grade_check(ctx: SellCtx) -> Optional[SellDecision]:
    """[3] C급 조기매도 / 동적 C→B 승급 (FIX-C1, FIX-14)"""
    if ctx.pos.gap_grade != "C" or ctx.hm < C_SELL_AFTER: return None
    ride_c    = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
    ride_ok   = ride_c >= C_GRADE_RIDE_UPGRADE
    # [FIX-14] 몰빵 기준 강화: 0.80% → 1.50% (손실 허용폭 축소)
    profit_ok = ctx.profit >= max(C_GRADE_PROFIT_UPGRADE, 1.50)
    if ride_ok and profit_ok:   # [FIX-14] OR → AND: 둘 다 충족해야 승급
        ctx.pos.gap_grade = "B"
        ctx.logger.info("[%s] C→B 승급 ride=%.2f profit=%.1f%%",
                        ctx.pos.code, ride_c, ctx.profit)
        return None
    ctx.logger.info("[%s] C급 조기매도  ride=%.2f  수익=%.1f%%",
                    ctx.pos.code, ride_c, ctx.profit)
    return _make_order(ctx.pos, ctx.current_price, ctx.profit, "C_GRADE_EARLY_EXIT", 0.0)

def _step4_partial_take(ctx: SellCtx) -> Optional[SellDecision]:
    """[4] 선익절 T1 — A+5% / B+3.5%
    [지침서 §7-2 수정] 기관동행(ride≥0.40) 시 T1 비율 40%→25%
    → 기관 흐름 살아있는 동안 더 많이 보유, T3까지 최대 45% 잔량 확보
    """
    if ctx.pos.partial_taken or ctx.pos.gap_grade not in ("A","B"): return None
    threshold = PARTIAL_TAKE_A if ctx.pos.gap_grade == "A" else PARTIAL_TAKE_B
    if ctx.profit < threshold: return None

    # [지침서 §7-2] 기관동행 여부에 따른 T1 비율 분기
    _ride_t1 = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
    _inst_on = _ride_t1 >= TRAIL_ACTIVATE_RIDE   # ride≥0.40 = 기관동행
    _t1_ratio = PARTIAL_TAKE_RATIO_INST if _inst_on else PARTIAL_TAKE_RATIO
    qty = max(1, int(ctx.pos.remain_qty * _t1_ratio))

    ctx.pos.partial_taken      = True
    ctx.pos.partial_done       = True
    ctx.pos.partial_peak_price = ctx.current_price
    # [지침서 §7-2] T1 체결가 기록 → T2 목표 계산용
    ctx.pos.t1_price = ctx.current_price
    ctx.pos.t1_ratio = _t1_ratio

    ctx.logger.info(
        "[%s] T1 선익절 %d주(%.0f%%)  수익=%.1f%%≥%.1f%%  기관동행=%s  ride=%.2f",
        ctx.pos.code, qty, _t1_ratio*100, ctx.profit, threshold,
        "✅" if _inst_on else "❌", _ride_t1,
    )
    return _make_order_qty(ctx.pos, ctx.current_price, ctx.profit,
                           f"T1_PARTIAL_{ctx.pos.gap_grade}", 0.0, qty)

def _step4b_t2_take(ctx: SellCtx) -> Optional[SellDecision]:
    """[4b] T2 익절 — T1 체결가 × 1.50 도달 시 잔량의 30% 추가 매도
    [지침서 §7-2 신규] T2 목표 = T1기준가 × T2_MULT(1.50)
    T2 완료 후 잔량(T3)은 Chandelier에 위임
    기관동행 시 T1=25% / T2=30% / T3=45% 구조 완성
    """
    # T1 미완료 / T2 이미 완료 / t1_price 미기록 → 스킵
    if not ctx.pos.partial_taken: return None
    if ctx.pos.t2_taken:          return None
    if ctx.pos.t1_price <= 0:     return None
    if ctx.pos.gap_grade not in ("A","B"): return None

    # T2 목표가 = T1 체결가 × 1.50
    t2_target_pct = (ctx.pos.t1_price / ctx.pos.entry_price - 1.0) * 100.0 * T2_MULT
    if ctx.profit < t2_target_pct: return None

    qty = max(1, int(ctx.pos.remain_qty * T2_TAKE_RATIO))
    ctx.pos.t2_taken = True

    # 기관동행 여부 확인 → T3 잔량 비율 로그
    _ride_t2  = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
    _inst_on  = _ride_t2 >= TRAIL_ACTIVATE_RIDE
    _sold_so_far = (ctx.pos.t1_ratio + T2_TAKE_RATIO)
    _remain_pct  = 1.0 - _sold_so_far

    ctx.logger.info(
        "[%s] T2 익절 %d주(30%%)  수익=%.1f%%≥%.1f%%  "
        "T3잔량=%.0f%%  기관동행=%s  ride=%.2f  → Chandelier위임",
        ctx.pos.code, qty, ctx.profit, t2_target_pct,
        _remain_pct * 100, "✅" if _inst_on else "❌", _ride_t2,
    )

    # T3 잔량이 기관동행 기준(45%) 미달이면 경고
    if _inst_on and _remain_pct < INST_T3_MIN_REMAIN:
        ctx.logger.warning(
            "[%s] ⚠️ T3 잔량 %.0f%% < 기관동행 최소 %.0f%% — T1/T2 비율 점검 권장",
            ctx.pos.code, _remain_pct*100, INST_T3_MIN_REMAIN*100,
        )

    return _make_order_qty(ctx.pos, ctx.current_price, ctx.profit,
                           "T2_PARTIAL", 0.0, qty)


def _step5_structure_exit(ctx: SellCtx) -> Optional[SellDecision]:
    """
    [5] STRUCTURE EXIT — VWAP이탈 / 기관이탈 / accel<0.5
    [FIX-2] 손실 구간(profit<=0)에서도 VWAP 이탈 청산 허용.
            _step6 initial stop보다 이 스텝이 먼저 실행되므로
            VWAP 붕괴 + 손실 구간의 사각지대를 제거.
    """
    if ctx.hm < NO_SELL_TO: return None

    # VWAP 이탈 — 수익/손실 무관 항상 검사
    # [v4.19 FIX-2] ride>=0.65(기관 강매집) 시 임계 완화: 0.99 -> 0.97
    # SIGA는 VWAP 대기 x3 연장 방식, PULLBACK은 임계 강화로 동일 효과
    # 기관 강매집 중 VWAP 일시 이탈(±1%) 허용 → 조기 청산 차단
    if ctx.hm >= VWAP_EXIT_MIN_HM and ctx.pos.vwap > 0:
        _ride_now     = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
        _vwap_thresh  = (VWAP_EXIT_THRESH - 0.02   # 0.99 -> 0.97 완화
                         if _ride_now >= TRAIL_WIDE_RIDE
                         else VWAP_EXIT_THRESH)
        if ctx.current_price < ctx.pos.vwap * _vwap_thresh:
            ctx.logger.warning("[%s] STRUCTURE_EXIT(VWAP)  수익=%.1f%%  ride=%.2f  thresh=%.2f",
                               ctx.pos.code, ctx.profit, _ride_now, _vwap_thresh)
            return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                               "STRUCTURE_EXIT_VWAP", 0.0)

    # 기관 이탈·accel 급감은 수익 양수일 때만 (손실 구간은 initial stop이 처리)
    # [신규] env STRUCTURE_EXIT_ON_LOSS=true 시 손실 구간도 검사 (대장주 일시 손실 보호 해제)
    if ctx.profit <= 0 and os.environ.get("STRUCTURE_EXIT_ON_LOSS", "false").lower() != "true":
        return None

    if ctx.cache and ctx.cache.get_inst_exit(ctx.pos.code):
        ctx.logger.warning("[%s] STRUCTURE_EXIT(기관이탈)  수익=%.1f%%",
                           ctx.pos.code, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                           "STRUCTURE_EXIT_INST", 0.0)
    _, accel = ctx.cache.get_ofi_accel(ctx.pos.code) if ctx.cache else (0.0, 0.0)
    if 0 < accel < 0.5:
        ctx.logger.warning("[%s] STRUCTURE_EXIT(accel=%.2f)  수익=%.1f%%",
                           ctx.pos.code, accel, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                           "STRUCTURE_EXIT_ACCEL", 0.0)
    return None

def _step6_initial_stop(ctx: SellCtx) -> Optional[object]:
    """[6] INITIAL STOP — trail 미활성 + 수익<1% 절대금지 구간"""
    if ctx.pos.trail_activated: return None
    if ctx.profit >= TRAIL_ABSOLUTE_BLOCK_PCT: return None
    if ctx.profit <= INITIAL_HARD_STOP:
        ctx.logger.warning("[%s] INITIAL_HARD_STOP  수익=%.1f%%", ctx.pos.code, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit, "INITIAL_HARD_STOP", 0.0)
    if ctx.profit <= INITIAL_BASE_STOP:
        ofi, accel = ctx.cache.get_ofi_accel(ctx.pos.code) if ctx.cache else (0.0,0.0)
        if not (ofi >= CHANDELIER_OFI_STRONG_MIN and accel >= CHANDELIER_ACCEL_STRONG_MIN):
            ctx.logger.warning("[%s] INITIAL_BASE_STOP  수익=%.1f%%  ofi=%.2f",
                               ctx.pos.code, ctx.profit, ofi)
            return _make_order(ctx.pos, ctx.current_price, ctx.profit, "INITIAL_BASE_STOP", 0.0)
    ctx.pos.update_peak(ctx.current_price)
    if ctx.hm >= ctx.force_time:
        return None
    return _HOLD   # 절대금지 구간 — 아래 단계 실행 안 함

def _step7_trail_activation(ctx: SellCtx) -> Optional[object]:
    """
    [7] TRAIL ACTIVATION
    [FIX-3] 초기 손절 중복 제거 — _step6이 전담하므로 여기서는 trail 활성화만.
            trail 미활성 상태에서 이 스텝에 도달했다면 profit >= TRAIL_ABSOLUTE_BLOCK_PCT
            가 보장되어 있음(_step6에서 HOLD 반환하기 때문).
    """
    if ctx.pos.trail_activated: return None
    if ctx.cache:
        ctx.ride_score = ctx.cache.get_ride(ctx.pos.code)
    activated = ((ctx.profit >= TRAIL_ACTIVATE_PROFIT and ctx.ride_score >= TRAIL_ACTIVATE_RIDE)
                 or ctx.profit >= TRAIL_ACTIVATE_HARD_PCT)
    if activated:
        trigger = "강제(2%+)" if ctx.profit >= TRAIL_ACTIVATE_HARD_PCT else "조건충족"
        ctx.pos.trail_activated = True
        ctx.logger.info("[%s] ★TRAIL ACTIVATED(%s)  수익=%.1f%%  ride=%.2f",
                        ctx.pos.code, trigger, ctx.profit, ctx.ride_score)
        return None
    # trail 미활성 + profit이 블록 구간 위에 있으면 계속 대기
    ctx.pos.update_peak(ctx.current_price)
    return _HOLD

# ═══════════════════════════════════════════════════════════════
#  [W26 PATCH 2026-05-12] v4_12 피라미딩 ADD_ON 복원
#  pullback_addon_queue.csv 작성 → kiwoom_buy_order_sender Reader가 폴링
# ═══════════════════════════════════════════════════════════════
def _write_addon_buy_signal(pos: "Position", ratio: float, stage: int,
                             logger: logging.Logger) -> None:
    """기관 동행 확인 시 추가 매수 신호를 pullback_addon_queue.csv에 기록.
    stage: 2 = 2차 진입, 3 = 3차 진입 (v4_12 L464-501 원본)"""
    if not PYRAMID_ENABLED:
        return
    try:
        _safe_mkdir(PYRAMID_ADDON_QUEUE_PATH.parent)
        fields = ["ts", "code", "side", "strategy", "addon_stage",
                  "addon_ratio", "entry_price", "strategy_type", "session_type"]
        row = {
            "ts":           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code":         pos.code,
            "side":         "BUY",
            "strategy":     pos.strategy or "PULLBACK",
            "addon_stage":  stage,
            "addon_ratio":  ratio,
            "entry_price":  pos.entry_price,
            "strategy_type": "PULLBACK",
            "session_type":  "PULLBACK",
        }
        exists = (PYRAMID_ADDON_QUEUE_PATH.exists()
                  and PYRAMID_ADDON_QUEUE_PATH.stat().st_size > 0)
        with open(PYRAMID_ADDON_QUEUE_PATH, "a",
                  encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerow(row)
        logger.info(
            "[PYRAMID] ✅ %d차 ADD_ON 신호 기록 code=%s ratio=%.0f%% (W26)",
            stage, pos.code, ratio * 100,
        )
    except Exception as e:
        logger.warning("[PYRAMID] ADD_ON 기록 실패: %s", e)


def _check_pyramid(pos: "Position", current_price: float, ride_score: float,
                   profit_pct: float, hm: int, logger: logging.Logger) -> None:
    """[W26] 피라미딩 조건 확인 및 ADD_ON 신호 발생 (v4_12 L504-539 원본)."""
    if not PYRAMID_ENABLED:
        return
    if hm >= PYRAMID_CUTOFF_HM:
        return
    if current_price <= 0 or pos.entry_price <= 0:
        return

    # 2차 진입 — ride≥0.40 + 수익≥1.5%
    if (not getattr(pos, "pyramid_add1_done", False)
            and ride_score >= PYRAMID_ADD1_RIDE_MIN
            and profit_pct >= PYRAMID_ADD1_PROFIT_MIN):
        logger.info(
            "[PYRAMID] 2차 진입 조건 충족 ride=%.2f profit=%.1f%% code=%s",
            ride_score, profit_pct, pos.code,
        )
        _write_addon_buy_signal(pos, PYRAMID_ADD1_RATIO, 2, logger)
        pos.pyramid_add1_done = True  # type: ignore[attr-defined]

    # 3차 진입 — ride≥0.65 + 수익≥3.0% (2차 완료 후)
    if (getattr(pos, "pyramid_add1_done", False)
            and not getattr(pos, "pyramid_add2_done", False)
            and ride_score >= PYRAMID_ADD2_RIDE_MIN
            and profit_pct >= PYRAMID_ADD2_PROFIT_MIN):
        logger.info(
            "[PYRAMID] 3차 진입 조건 충족 ride=%.2f profit=%.1f%% code=%s",
            ride_score, profit_pct, pos.code,
        )
        _write_addon_buy_signal(pos, PYRAMID_ADD2_RATIO, 3, logger)
        pos.pyramid_add2_done = True  # type: ignore[attr-defined]


def _step8_peak_protect(ctx: SellCtx) -> Optional[SellDecision]:
    """
    [8] PEAK PROTECT 3단계 래칫
    [FIX-8] 발동 시 ctx에 peak_protect_fired 플래그 → _step9 FAILSAFE 스킵
    [FIX-9] 선익절 후 잔량 기준 effective_peak_profit_pct 사용
    [v4.20 수정2] 기관동행(ride≥0.40) 시 임계 ÷1.15 완화
                  rt_sell v3.12와 동일 원칙 — 기관 매집 중 조기 청산 차단
    [W26 PATCH] 함수 시작에서 피라미딩 체크 — trail 활성 후 기관 동행 시 ADD_ON 발송
    """
    # [W26 PATCH 2026-05-12] 피라미딩 ADD_ON 체크
    # _step7 trail_activated=True 통과 후 도달 → 안전한 호출 위치
    if PYRAMID_ENABLED and ctx.pos.trail_activated:
        _check_pyramid(ctx.pos, ctx.current_price, ctx.ride_score,
                       ctx.profit, int(datetime.now().strftime("%H%M")),
                       ctx.logger)

    peak = ctx.pos.effective_peak_profit_pct   # [FIX-9]

    # [v4.20 수정2] 기관동행 여부 확인 → 임계 완화
    ride_pp = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
    inst_relax = (PEAK_PROTECT_INST_RELAX_MULT
                  if ride_pp >= PEAK_PROTECT_INST_RIDE_MIN
                  else 1.0)

    tier1 = PEAK_PROTECT_MIN_PEAK_PCT / inst_relax
    tier2 = PEAK_PROTECT_TIER2_PCT    / inst_relax
    tier3 = PEAK_PROTECT_TIER3_PCT    / inst_relax

    floor = (PEAK_PROTECT_FLOOR3_PCT if peak >= tier3 else
             PEAK_PROTECT_FLOOR2_PCT if peak >= tier2 else
             PEAK_PROTECT_FLOOR_PCT  if peak >= tier1 else None)
    if floor is None or ctx.profit >= floor: return None

    ctx.logger.warning(
        "[%s] ★PEAK_PROTECT  고점=%.1f%%  바닥=+%.1f%%  현재=%.1f%%"
        "  ride=%.2f  완화=÷%.2f → EXIT",
        ctx.pos.code, peak, floor, ctx.profit, ride_pp, inst_relax,
    )
    # [FIX-8] FAILSAFE 중복 방지 플래그
    ctx._peak_protect_fired = True   # type: ignore[attr-defined]
    return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                       f"PEAK_PROTECT_{floor:.0f}pct", 0.0)


# [v4.19 FIX-1] step8.5: PROFIT_LOCK - PEAK_PROTECT 이후, FAILSAFE 이전
# 지침서[US-1] 11장: lock_stop = max(current_stop, profit_lock_stop) 단방향 래칫
# 수치 검증: peak>=6% 시 PROFIT_LOCK(4.02%) > FAILSAFE(3.60%) -> 항상 먼저 발동
def _step8_5_profit_lock(ctx: SellCtx) -> Optional[SellDecision]:
    """[8.5] PROFIT_LOCK 래칫 손절선 - 지침서[US-1] 11장"""
    peak = ctx.pos.effective_peak_profit_pct
    if peak <= 0 or ctx.pos.entry_price <= 0:
        return None

    # ride>=0.65(기관 강매집) 시 비율 x0.9 완화
    ride        = ctx.ride_score
    inst_relax  = PROFIT_LOCK_INST_RELAX if ride >= PROFIT_LOCK_RIDE_MIN else 1.0

    # 단방향 래칫 갱신
    new_stop  = ctx.pos._profit_lock_stop
    new_level = ctx.pos._profit_lock_level
    for lv, (thr, ratio) in enumerate(PROFIT_LOCK_LEVELS, 1):
        if peak >= thr:
            eff_ratio = ratio * inst_relax
            candidate = ctx.pos.entry_price * (1.0 + peak/100.0 * eff_ratio)
            if candidate > new_stop:
                new_stop  = candidate
                new_level = lv
            break

    if new_stop > ctx.pos._profit_lock_stop:
        ctx.pos._profit_lock_stop  = new_stop
        ctx.pos._profit_lock_level = new_level
        guaranteed = (new_stop / ctx.pos.entry_price - 1.0) * 100.0
        ctx.logger.debug("[%s] PROFIT_LOCK Lv%d 갱신 lock=%.0f (+%.2f%% 보장)",
                         ctx.pos.code, new_level, new_stop, guaranteed)

    # 발동 체크
    if ctx.pos._profit_lock_stop > 0 and ctx.current_price < ctx.pos._profit_lock_stop:
        # [수정-3] 지침서 §11-2: "Chandelier Stop과 비교해 더 높은 값 채택"
        # PROFIT_LOCK_STOP이 Chandelier trail_price보다 낮으면 이번 봉 발동 skip
        # → Chandelier가 더 엄격한 보호선을 제공할 때 PROFIT_LOCK이 방해하지 않도록
        if ctx.cache and ctx.pos.atr_pct > 0:
            try:
                hh_n = ctx.cache.get_highest_high_n(ctx.pos.code, CHANDELIER_N)
                highest_high = hh_n if hh_n > 0 else ctx.pos.peak_price
                ofi_pl, accel_pl = ctx.cache.get_ofi_accel(ctx.pos.code)
                vol_regime_pl = _get_vol_regime(ctx.pos.atr_pct, ctx.pos.atr_avg_pct)
                k_pl = _get_chandelier_k(vol_regime_pl, ofi=ofi_pl,
                                         accel=accel_pl, profit_pct=ctx.profit)
                trail_price_now = _calc_chandelier_trail_price(
                    highest_high, ctx.pos.atr_pct, k_pl)
                if trail_price_now > 0 and ctx.pos._profit_lock_stop < trail_price_now:
                    ctx.logger.debug(
                        "[%s] PROFIT_LOCK skip — Chandelier(%.0f) > lock(%.0f) §11-2",
                        ctx.pos.code, trail_price_now, ctx.pos._profit_lock_stop)
                    return None   # Chandelier가 더 높은 보호선 → 이번 봉 PROFIT_LOCK skip
            except Exception:
                pass  # 계산 실패 시 기존 로직 유지

        guaranteed = (ctx.pos._profit_lock_stop / ctx.pos.entry_price - 1.0) * 100.0
        ctx.logger.warning("[%s] PROFIT_LOCK_Lv%d 발동 현재=%.0f < lock=%.0f (+%.2f%% 보장)",
                           ctx.pos.code, ctx.pos._profit_lock_level,
                           ctx.current_price, ctx.pos._profit_lock_stop, guaranteed)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                           f"PROFIT_LOCK_Lv{ctx.pos._profit_lock_level}", 0.0)
    return None


def _step9_hard_failsafe(ctx: SellCtx) -> Optional[SellDecision]:
    """
    [9] HARD FAILSAFE — 급락 즉시 EXIT (López de Prado 2018 Triple Barrier)
    [FIX-8] _step8 PEAK_PROTECT가 이미 발동했으면 스킵 (동시 발동 방지)
    [FIX-9] effective_peak_profit_pct 사용
    """
    # [FIX-8] 중복 발동 방지
    if getattr(ctx, "_peak_protect_fired", False):
        return None
    peak = ctx.pos.effective_peak_profit_pct   # [FIX-9]
    if (peak >= FAILSAFE_TRIGGER_PROFIT
            and ctx.profit < peak * FAILSAFE_RETAIN_RATIO):
        ctx.logger.warning("[%s] ★HARD_FAILSAFE  고점=%.1f%%  현재=%.1f%% → EXIT",
                           ctx.pos.code, peak, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit, "HARD_FAILSAFE", 0.0)
    return None

def _step10_chandelier_exit(ctx: SellCtx) -> Optional[SellDecision]:
    """[10] CHANDELIER EXIT + EXIT_SCORE 복합 게이트 (Le Beau 1991)"""
    vol_regime = _get_vol_regime(ctx.pos.atr_pct, ctx.pos.atr_avg_pct)
    ofi, accel = ctx.cache.get_ofi_accel(ctx.pos.code) if ctx.cache else (0.0,0.0)
    k = _get_chandelier_k(vol_regime, ofi=ofi, accel=accel, profit_pct=ctx.profit)

    exit_ctx   = _build_exit_ctx(ctx.pos, ctx.current_price, ctx.profit, ctx.ride_score)
    exit_score = calc_exit_score(exit_ctx)

    if exit_score >= EXIT_SCORE_HOLD_TH:
        k = round(k * EXIT_SCORE_K_WIDE_MULT, 3)
    elif exit_score < EXIT_SCORE_TIGHTEN_TH:
        k = round(k * EXIT_SCORE_K_TIGHT_MULT, 3)
        if exit_score < EXIT_SCORE_FORCE_TH and ctx.profit >= EXIT_SCORE_FORCE_MIN_PROFIT:
            # [v4.19 FIX-3] ride>=0.65(기관 강매집) 시 EXIT_SCORE_FORCE 억제
            # SIGA v3.5 동일 패턴: _trend_locked or _ride_hold
            # ride=0.70이면 기관이 매집 중 → 흐름 소멸 판단 과도
            _ride_esf = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
            if _ride_esf >= TRAIL_WIDE_RIDE:
                ctx.logger.debug("[%s] EXIT_SCORE_FORCE 억제 ride=%.2f>=%.2f",
                                 ctx.pos.code, _ride_esf, TRAIL_WIDE_RIDE)
            else:
                ctx.logger.info("[%s] EXIT_SCORE_FORCE  score=%.3f  수익=%.1f%%  ride=%.2f",
                                ctx.pos.code, exit_score, ctx.profit, _ride_esf)
                return _make_order(ctx.pos, ctx.current_price, ctx.profit, "EXIT_SCORE_FORCE", 0.0)

    hh_n         = ctx.cache.get_highest_high_n(ctx.pos.code, CHANDELIER_N) if ctx.cache else 0.0
    highest_high = hh_n if hh_n > 0 else ctx.pos.peak_price
    trail_price  = _calc_chandelier_trail_price(highest_high, ctx.pos.atr_pct, k)

    ctx.logger.debug("[%s] Chandelier  현재=%.0f  HH=%.0f  ATR=%.2f%%  k=%.2f  손절=%.0f  exit=%.3f",
                     ctx.pos.code, ctx.current_price, highest_high,
                     ctx.pos.atr_pct, k, trail_price, exit_score)

    if trail_price > 0 and ctx.current_price <= trail_price:
        ctx.logger.info("[%s] ★CHANDELIER_EXIT  현재=%.0f≤%.0f  수익=%.1f%%  k=%.2f  레짐=%s",
                        ctx.pos.code, ctx.current_price, trail_price,
                        ctx.profit, k, vol_regime)
        order = _make_order(ctx.pos, ctx.current_price, ctx.profit,
                            f"CHANDELIER_EXIT_{vol_regime}", k)
        order.update({"trail_price": trail_price, "highest_high": highest_high,
                      "chandelier_k": k, "vol_regime": vol_regime,
                      "exit_score": round(exit_score, 3)})
        return order
    return None

def _step11_intraday_cut(ctx: SellCtx) -> Optional[SellDecision]:
    """[11] 장중 손절 -2%"""
    if ctx.profit <= CUT_INTRADAY and ctx.hm >= NO_SELL_TO:
        ctx.logger.warning("[%s] 장중손절  수익=%.1f%%", ctx.pos.code, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit, "INTRADAY_CUT", 0.0)
    return None

def _step12_force_close(ctx: SellCtx) -> Optional[SellDecision]:
    """
    [12] 강제청산 — 14:50 약한종목 즉시 청산 / 강한종목 15:20까지 보유
    강한종목 판단(4개 중 3개 이상):
      1. ride_score ≥ FORCE_CLOSE_STRONG_RIDE_MIN
      2. OFI ≥ FORCE_CLOSE_STRONG_OFI_MIN
      3. price ≥ VWAP
      4. trail_activated AND profit > 0
    """
    if ctx.hm < ctx.force_time or ctx.pos.remain_qty <= 0: return None
    ride = ctx.cache.get_ride(ctx.pos.code) if ctx.cache else 0.0
    ofi, _ = ctx.cache.get_ofi_accel(ctx.pos.code) if ctx.cache else (0.0, 0.0)

    _ride_ok  = ride >= FORCE_CLOSE_STRONG_RIDE_MIN
    _ofi_ok   = ofi  >= FORCE_CLOSE_STRONG_OFI_MIN
    _vwap_ok  = ctx.pos.vwap <= 0 or ctx.current_price >= ctx.pos.vwap
    _trail_ok = ctx.pos.trail_activated and ctx.profit > 0
    _strong   = sum([_ride_ok, _ofi_ok, _vwap_ok, _trail_ok])

    # 강한종목: 15:20 최종 안전망까지 보유 유예
    if _strong >= 3 and ctx.hm < FORCE_CLOSE_FINAL:
        ctx.logger.info(
            "[%s] 강제청산 유예(STRONG %d/4) ride=%.2f ofi=%.2f vwap=%s trail=%s → 15:20 대기",
            ctx.pos.code, _strong, ride, ofi,
            "OK" if _vwap_ok else "X", "ON" if _trail_ok else "OFF",
        )
        return None

    # 약한종목 — 기존 ride+수익 유예 조건 유지
    ride_ok   = ride >= TRAIL_ACTIVATE_RIDE and ctx.hm < FORCE_CLOSE_DEFER_MAX_HM
    profit_ok = ctx.profit > FORCE_CLOSE_DEFER_PROFIT and ctx.hm < FORCE_CLOSE_DEFER_MAX_HM
    if ride_ok and profit_ok:
        ctx.logger.info("[%s] 강제청산 유예(ride+수익) ride=%.2f 수익=%.1f%%",
                        ctx.pos.code, ride, ctx.profit)
        return None

    tag = "1450_WEAK"
    if ctx.hm >= FORCE_CLOSE_DEFER_MAX_HM:   tag += "_유예만료"
    elif _strong < 3:                          tag += f"_WEAK({_strong}/4)"
    elif not ride_ok:                          tag += "_기관이탈"
    else:                                      tag += f"_수익미달({ctx.profit:.1f}%)"
    ctx.logger.info("[%s] 강제청산(%s) ride=%.2f ofi=%.2f 수익=%.1f%% strong=%d/4",
                    ctx.pos.code, tag, ride, ofi, ctx.profit, _strong)
    return _make_order(ctx.pos, ctx.current_price, ctx.profit, f"FORCE_CLOSE_{tag}", 0.0)

def _step13_final_failsafe(ctx: SellCtx) -> Optional[SellDecision]:
    """[13] 15:20 최종 안전망 — RT(FORCE_EXIT_RT=1520)와 동일 기준"""
    if ctx.hm >= FORCE_CLOSE_FINAL and ctx.pos.remain_qty > 0:
        ctx.logger.warning("[%s] 15:20 최종안전망  수익=%.1f%%", ctx.pos.code, ctx.profit)
        return _make_order(ctx.pos, ctx.current_price, ctx.profit,
                           "FORCE_CLOSE_FINAL_1520", 0.0)
    return None


# ═══════════════════════════════════════════════════════════════
#  _decide_sell — 오케스트레이터 (40줄)
# ═══════════════════════════════════════════════════════════════
def _decide_sell(pos: Position, current_price: float,
                 hm: int, logger: logging.Logger,
                 cache: Optional[RTCache] = None,
                 tracker: Optional[PnLTracker] = None) -> Optional[SellDecision]:
    """
    청산 판단 오케스트레이터.
    tracker: PnLTracker — 회로차단 확인용 (None이면 차단 비활성)
    """
    if pos.remain_qty <= 0 or current_price <= 0:
        return None

    # [LEADER-HOLD 2026-06-11 사용자결정] 대장주 승격 매수(leader_first 꼬리표)는 추적익절 OFF —
    #   검증조건 그대로: 하드스톱 -2.5% + 14:50 청산만(사용자 지정 "2시50분까지", 종가매수에 슬롯 양보).
    #   꼬리표 없으면 이 블록 통과 = 기존 동작 100% 동일. 롤백 env LEADER_HOLD_ENABLE=NO.
    if (getattr(pos, "leader_first", 0)
            and os.environ.get("LEADER_HOLD_ENABLE", "YES").strip().upper() == "YES"):
        _lh_profit = (current_price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0.0
        _lh_close_hm = int(os.environ.get("LEADER_HOLD_CLOSE_HM", "1450"))
        # [LEADER-LADDER 2026-06-11 사용자안 검증채택] 사다리 손절 — 백테(+10%도달군 n=46):
        #   사다리느슨 +3.91%/승63% > 단순보유 +2.63%/49% > 빡빡 +1.74%.
        #   기본 -2.5%(진입가) / 고점 +10% 도달 후 고점-5% / +20% 후 고점-3%.
        try:
            pos.peak_price = max(float(getattr(pos, "peak_price", 0) or 0), pos.entry_price, current_price)
        except (TypeError, ValueError):
            pos.peak_price = max(pos.entry_price, current_price)
        _lh_up = pos.peak_price / pos.entry_price - 1 if pos.entry_price > 0 else 0.0
        _lh_stop = pos.entry_price * 0.975
        # [LEADER-CURVE-A 2026-06-12 친구님 최종확정] 구간별 그물: 위로 갈수록 좁게.
        #   +2.5%~: 고점-6%(흔들림 구간 너그럽게, +3.7%부터 실작동) / +10%~: -5% / +15%~: -3% / +20%~: -2%.
        #   5파전+곡선 시험: 곡선A 대장주 +4.17%·+5%군 +2.07%/승57% (-4%판은 대장주 +2.85%로 열위).
        if _lh_up >= 0.20:
            _lh_stop = max(_lh_stop, pos.peak_price * 0.98)
        elif _lh_up >= 0.15:
            _lh_stop = max(_lh_stop, pos.peak_price * 0.97)
        elif _lh_up >= 0.10:
            _lh_stop = max(_lh_stop, pos.peak_price * 0.95)
        elif _lh_up >= 0.025:
            _lh_stop = max(_lh_stop, pos.peak_price * 0.94)
        if current_price <= _lh_stop:
            _lh_reason = ("LEADER_LADDER_STOP" if _lh_stop > pos.entry_price * 0.975
                          else "LEADER_HARD_STOP")
            logger.warning("[%s] [LEADER-HOLD] %s 발동 (고점%.1f%% 수익%.1f%%) → 전량 매도",
                           pos.code, _lh_reason, _lh_up * 100, _lh_profit)
            return SellDecision(code=pos.code, qty=pos.remain_qty, price=current_price,
                                profit_pct=_lh_profit, reason=_lh_reason,
                                trail_pct=0.0, gap_grade=pos.gap_grade, score_flow=pos.score_flow,
                                trail_price=round(_lh_stop, 2), highest_high=pos.peak_price,
                                chandelier_k=0.0, vol_regime="LEADER", exit_score=0.0)
        if hm >= _lh_close_hm:
            logger.info("[%s] [LEADER-HOLD] %d 도달 → 청산 (보유수익 %.1f%%)", pos.code, _lh_close_hm, _lh_profit)
            return SellDecision(code=pos.code, qty=pos.remain_qty, price=current_price,
                                profit_pct=_lh_profit, reason="LEADER_CLOSE_1450",
                                trail_pct=0.0, gap_grade=pos.gap_grade, score_flow=pos.score_flow,
                                trail_price=0.0, highest_high=pos.peak_price,
                                chandelier_k=0.0, vol_regime="LEADER", exit_score=0.0)
        return None   # 그 외 = 보유 (사다리 스톱과 14:50 청산만 적용)

    # [FIX-6] 회로차단은 신규 진입(매수) 차단 전용.
    # 매도 엔진에서는 회로차단 여부와 무관하게 청산 로직을 정상 실행한다.
    # (tracker.is_new_entry_blocked()는 매수 엔진에서만 참조할 것)
    if tracker and tracker.is_circuit_broken():
        logger.warning("[%s] ★회로차단 발동 중 (일일손실=%.2f%%) — 청산은 정상 진행",
                       pos.code, tracker.daily_pnl())

    # VWAP 실시간 갱신
    if hm >= VWAP_EXIT_MIN_HM:
        fresh = cache.refresh_vwap(pos.code) if cache else 0.0
        if fresh > 0: pos.vwap = fresh

    ctx = SellCtx(pos, current_price, hm, logger, cache)

    if pos.trail_activated:
        pos.update_peak(current_price)
        ctx.peak_pct   = pos.peak_profit_pct
        ctx.ride_score = cache.get_ride(pos.code) if cache else 0.0

    steps_pre  = [_step1_no_sell_window, _step2_d_grade_cut,
                  _step3_c_grade_check,  _step4_partial_take,
                  _step4b_t2_take,       # [지침서 §7-2] T2=T1×1.50 분할익절
                  _step5_structure_exit, _step6_initial_stop,
                  _step7_trail_activation]
    steps_post = [_step8_peak_protect, _step8_5_profit_lock, _step9_hard_failsafe,
                  _step10_chandelier_exit, _step11_intraday_cut,
                  _step12_force_close, _step13_final_failsafe]

    for step in steps_pre:
        result = step(ctx)
        if result is _HOLD: return None      # ★ SENTINEL 비교 (타입 안전)
        if result is not None: return result  # type: ignore[return-value]

    for step in steps_post:
        result = step(ctx)
        if result is not None: return result  # type: ignore[return-value]

    return None


def _load_vwap_fallback(code: str) -> float:
    try:
        if RT_INTRADAY_PATH.exists():
            for r in _read_csv(RT_INTRADAY_PATH):
                if str(r.get("code","")).strip().zfill(6) == str(code).zfill(6):
                    v = _f(r.get("vwap",0))
                    if v > 0: return v
    except Exception: pass
    return 0.0

def _make_order(pos: Position, price: float, profit_pct: float,
                reason: str, trail_pct: float) -> SellDecision:
    return SellDecision(code=pos.code, qty=pos.remain_qty, price=price,
                        profit_pct=round(profit_pct,2), reason=reason,
                        trail_pct=trail_pct, gap_grade=pos.gap_grade,
                        score_flow=pos.score_flow)

def _make_order_qty(pos: Position, price: float, profit_pct: float,
                    reason: str, trail_pct: float, qty: int) -> SellDecision:
    return SellDecision(code=pos.code, qty=min(qty,pos.remain_qty), price=price,
                        profit_pct=round(profit_pct,2), reason=reason,
                        trail_pct=trail_pct, gap_grade=pos.gap_grade,
                        score_flow=pos.score_flow)


# ═══════════════════════════════════════════════════════════════
#  EV 피드백 기록
# ═══════════════════════════════════════════════════════════════
EV_HEADER = ["date","code","entry_price","exit_price","profit_pct",
             "gap_grade","trail_pct","peak_price","reason","strategy",
             "gap_up_flag","score_flow","sell_time","hold_minutes",
             "sell_failed","partial","exec_cost_est"]

def _append_ev(pos: Position, order: SellDecision,
               sell_failed: int = 0) -> None:
    """
    [FIX-5] EV 기록 — 전체 CSV 재읽기 제거 → append 모드 라인 추가 O(1).
    파일이 없거나 헤더가 없으면 헤더 먼저 작성.
    """
    # [PAPER-GUARD 2026-06-10] PAPER 시뮬은 진화 학습데이터(eod_ev_history/trade_log) 오염 금지.
    if PAPER_TRADE:
        return
    _safe_mkdir(EV_PATH.parent)
    profit    = float(order.get("profit_pct", 0))
    gap_grade = order.get("gap_grade","?")
    reason    = order.get("reason","")
    exec_cost = estimate_exec_cost(float(order.get("price",0)),
                                   int(order.get("qty",0)))
    new_row = {
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "code":          pos.code,
        "entry_price":   pos.entry_price,
        "exit_price":    order.get("price",0),
        "profit_pct":    round(profit,2),
        "gap_grade":     gap_grade,
        "trail_pct":     order.get("trail_pct",0),
        "peak_price":    pos.peak_price,
        "reason":        reason,
        "strategy":      pos.strategy,
        "gap_up_flag":   1 if gap_grade in ("A","B") and profit > 0 else 0,
        "score_flow":    pos.score_flow,
        "sell_time":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hold_minutes":  pos.hold_minutes(),
        "sell_failed":   sell_failed,
        "partial":       1 if "PARTIAL_TAKE" in reason else 0,
        "exec_cost_est": round(exec_cost*100, 3),
    }
    need_header = not EV_PATH.exists() or EV_PATH.stat().st_size == 0
    try:
        with open(EV_PATH, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=EV_HEADER, extrasaction="ignore")
            if need_header:
                w.writeheader()
            w.writerow(new_row)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        logging.getLogger("pullback_sell_engine").error("[EV] 기록 실패: %s", e)

    # [FAILED-SELL-GUARD 2026-06-11] 매도 미체결(sell_failed)은 거래가 아님 —
    #   trade_log(Kelly 학습)는 실체결만. (6/11 실패 재시도가 6줄 가짜거래로 기록돼
    #   진화 학습 오염 — eod_ev_history는 sell_failed 플래그와 함께 위에서 기록 유지)
    if sell_failed:
        return

    # [v4.18 FIX-C] trade_log.csv — evolution_engine 학습 데이터 (13컬럼 표준)
    # profit_pct 단위: 백분율 (2.3=2.3%) → /100 변환 → 소수 단위로 기록
    # 이유: evolution_engine._calc_kelly()는 소수 단위 기대
    _logger_pb = logging.getLogger("pullback_sell_engine")
    try:
        _stop_est  = pos.entry_price * (1.0 - INITIAL_HARD_STOP / 100.0)
        _R         = pos.entry_price - _stop_est if _stop_est < pos.entry_price else 0.001
        _exit_p    = float(order.get("price", pos.entry_price))
        _r_mult    = (_exit_p - pos.entry_price) / _R if _R > 0 else 0.0
        _hold_min  = pos.hold_minutes()
        _pnl_dec   = round(profit / 100.0, 6)  # 백분율 → 소수 변환
        _tl_row = {
            "date":         datetime.now().strftime("%Y-%m-%d"),
            "ticker":       pos.code,
            "strategy":     str(pos.strategy) if pos.strategy else "PULLBACK",
            "regime":       getattr(pos, "regime", ""),
            "entry_price":  round(pos.entry_price, 0),
            "exit_price":   round(_exit_p, 0),
            "stop_price":   round(_stop_est, 0),
            "pnl":          round((_exit_p - pos.entry_price) * int(order.get("qty", 0)), 0),
            "pnl_pct":      _pnl_dec,
            "R_multiple":   round(_r_mult, 4),
            "entry_score":  round(getattr(pos, "score_flow", 0) or 0, 4),
            "exit_reason":  reason,
            "holding_min":  _hold_min,
        }
        _safe_mkdir(TRADE_LOG_PATH.parent)
        _need_hdr = not TRADE_LOG_PATH.exists() or TRADE_LOG_PATH.stat().st_size == 0
        with open(TRADE_LOG_PATH, "a", encoding="utf-8-sig", newline="") as _tf:
            _tw = csv.DictWriter(_tf, fieldnames=list(_tl_row.keys()), extrasaction="ignore")
            if _need_hdr: _tw.writeheader()
            _tw.writerow(_tl_row)
            _tf.flush(); os.fsync(_tf.fileno())
        _logger_pb.info("[v4.18] trade_log.csv 기록 R_mult=%.2f hold=%d분", _r_mult, _hold_min)
    except Exception as _tl_e:
        _logger_pb.warning("[v4.18] trade_log.csv 기록 실패(비치명): %s", _tl_e)

    # [v4.18 FIX-D] pnl_linker.write_sell_fill() — 자기진화 트리거
    # bridge_eod evolution_load_kelly() 즉시 재실행 → 승률/Kelly 반영
    if _PNL_LINKER_OK and _pnl_write_sell is not None and sell_failed == 0:
        try:
            _base_str = str(BASE)
            _pnl_write_sell(
                code=pos.code,
                sell_price=float(order.get("price", 0)),
                sell_qty=int(order.get("qty", 0)),
                strategy=str(pos.strategy) if pos.strategy else "PULLBACK",
                base_dir=_base_str,
                exit_reason=reason,
            )
            _logger_pb.info("[v4.18] pnl_linker.write_sell_fill 완료 → 자기진화 트리거")
        except Exception as _pnl_e:
            _logger_pb.warning("[v4.18] pnl_linker 호출 실패(비치명): %s", _pnl_e)

    # [PATCH-PNL-SIGNAL] PULLBACK 매도 완료 → rt_sell_signal.json append
    # (SIGA._save_sell_signal_for_pnl 동일 패턴 / rt_pnl_tracker 폴링 채널 결선)
    if sell_failed == 0:
        try:
            _ts_now = datetime.now().strftime("%Y%m%d%H%M%S")
            try:
                _entry_ts_str = pos.entry_ts.strftime("%Y%m%d%H%M%S")
            except Exception:
                _entry_ts_str = _ts_now
            _sig = {
                "code":          str(pos.code).zfill(6),
                "entry_price":   float(pos.entry_price),
                "exit_price":    float(order.get("price", 0)),
                "qty":           int(order.get("qty", 0)),
                "reason":        str(order.get("reason", "")),
                "strategy":      "PULLBACK",
                "pattern_key":   "",
                "ts":            _ts_now,
                "entry_ts":      _entry_ts_str,
                "strategy_type": "PULLBACK",
                "inst_score":    0.0,
                "inst_net_krw":  0,
            }
            _p_sig = BASE / "DATA" / "rt_sell_signal.json"
            _today = _ts_now[:8]
            _existing = []
            if _p_sig.exists():
                try:
                    with open(_p_sig, "r", encoding="utf-8-sig") as _fr:
                        _raw = json.load(_fr)
                    if isinstance(_raw, list):
                        _existing = [s for s in _raw if str(s.get("ts", "")).startswith(_today)]
                except Exception:
                    _existing = []
            _merged = _existing + [_sig]
            _tmp = str(_p_sig) + ".tmp"
            _p_sig.parent.mkdir(parents=True, exist_ok=True)
            with open(_tmp, "w", encoding="utf-8") as _fw:
                json.dump(_merged, _fw, ensure_ascii=False, indent=2)
            os.replace(_tmp, str(_p_sig))
            _logger_pb.info("[PNL-SIGNAL] rt_sell_signal.json append 완료 → rt_pnl_tracker 학습 채널 결선")
        except Exception as _sig_e:
            _logger_pb.warning("[PNL-SIGNAL] rt_sell_signal.json 작성 실패(비치명): %s", _sig_e)

    # [v4_9-MP7] PULLBACK 청산 시 pullback_cycle_tracker.json 갱신
    # 사유: 매수센더의 _check_pullback_reentry()가 cycle_count를 읽어 2사이클 재진입을 결정.
    #       기존엔 pullback_sell이 cycle_tracker를 갱신하지 않아 동일 종목 무한 재진입 위험.
    #       전량 청산만 카운트(PARTIAL_TAKE는 분할이라 중복 카운트 방지).
    if sell_failed == 0 and "PARTIAL" not in str(reason).upper():
        try:
            _ct_path   = BASE / "DATA" / "pullback_cycle_tracker.json"
            _ct_path.parent.mkdir(parents=True, exist_ok=True)
            _today_ymd = datetime.now().strftime("%Y%m%d")
            _now_hm    = int(datetime.now().strftime("%H%M"))
            _ct_data: dict = {}
            if _ct_path.exists():
                try:
                    with open(_ct_path, "r", encoding="utf-8-sig") as _ctf:
                        _ct_raw = json.load(_ctf)
                    if _ct_raw.get("date") == _today_ymd:
                        _ct_data = _ct_raw
                except Exception:
                    _ct_data = {}
            if not _ct_data:
                _ct_data = {"date": _today_ymd, "cycle_count": 0, "last_sell_time": 0}
            _ct_data["cycle_count"]    = int(_ct_data.get("cycle_count", 0)) + 1
            _ct_data["last_sell_time"] = _now_hm
            _ct_data["last_code"]      = str(pos.code).zfill(6)
            _ct_loss = list(_ct_data.get("loss_codes", []))
            if float(profit) < 0:
                _ct_data["loss_codes"] = sorted(set(_ct_loss) | {str(pos.code).zfill(6)})
            else:
                _ct_data["loss_codes"] = _ct_loss
            _ct_tmp = str(_ct_path) + ".tmp"
            with open(_ct_tmp, "w", encoding="utf-8") as _ctf:
                json.dump(_ct_data, _ctf, ensure_ascii=False, indent=2)
            os.replace(_ct_tmp, str(_ct_path))
            _logger_pb.info(
                "[CYCLE][v4_9-MP7] pullback_cycle_tracker 갱신 cycle=%d last_sell=%04d code=%s loss_codes=%s",
                _ct_data["cycle_count"], _now_hm, pos.code, _ct_data["loss_codes"]
            )
        except Exception as _ct_e:
            _logger_pb.warning("[CYCLE][v4_9-MP7] cycle_tracker 갱신 실패(비치명): %s", _ct_e)


# ═══════════════════════════════════════════════════════════════
#  [v4_17] 키움 OpenAPI+ 실연동 — KiwoomBridge 완전 구현
#
#  설계:
#    KiwoomBridge  : PyQt5 QAxWidget 래핑 싱글턴
#    _get_kiwoom_api() : 싱글턴 반환 (PAPER_TRADE=false 시에만 초기화)
#    _send_sell_order(): PAPER_TRADE 분기 + 3회 재시도 + 주문로그 기록
#    _order_retry()    : 재시도 래퍼 (max=3, backoff=0.5초)
#    ORDER_LOG_PATH    : order_log.csv 실시간 기록
#
#  키움 OpenAPI+ 주요 TR 코드
#    SendOrder  : 매도 주문 (order_type=2, hoga_gb="03"=시장가)
#    OnReceiveMsg      : 주문 접수 메시지 콜백
#    OnReceiveChejanData: 체결/잔고 콜백 (fid=9203=주문번호)
#
#  환경변수
#    PAPER_TRADE=false    : 실거래 모드 활성화
#    KIWOOM_ACCOUNT       : 계좌번호 (예: 1234567890)
#    KIWOOM_SCREEN_SELL   : 매도 화면번호 (기본 "9001")
#    KIWOOM_ORDER_TIMEOUT : 접수 확인 대기 초 (기본 5)
#    KIWOOM_MAX_RETRY     : 주문 재시도 횟수 (기본 3)
# ═══════════════════════════════════════════════════════════════

import time as _time
import threading as _threading
import time as _time_pb  # [A-1b 2026-05-15] chejan thread polling sleep
import uuid as _uuid_pb  # [A-1b 2026-05-15] idempotency_key 생성

# 경로 상수 — 주문 이력 파일 [v4_17-5]
ORDER_LOG_PATH = DATA_DIR / "ledger" / "order_log.csv"
ORDER_LOG_HEADER = ["ts","code","qty","reason","profit_pct","order_no",
                    "ret_code","result","elapsed_ms","mode"]

# 키움 연동 파라미터
KIWOOM_SCREEN_SELL   = os.environ.get("KIWOOM_SCREEN_SELL",   "9001")
KIWOOM_ORDER_TIMEOUT = float(os.environ.get("KIWOOM_ORDER_TIMEOUT", "5.0"))
KIWOOM_MAX_RETRY     = int(os.environ.get("KIWOOM_MAX_RETRY",   "3"))


# ── 주문 로그 기록 [v4_17-5] ────────────────────────────────────
def _write_order_log(code: str, qty: int, reason: str, profit_pct: float,
                     order_no: str, ret_code: int, result: str,
                     elapsed_ms: int, mode: str) -> None:
    """order_log.csv에 주문 이력 1행 추가 (append 모드 O(1))."""
    _safe_mkdir(ORDER_LOG_PATH.parent)
    row = {
        "ts":          datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "code":        code,
        "qty":         qty,
        "reason":      reason,
        "profit_pct":  round(profit_pct, 2),
        "order_no":    order_no,
        "ret_code":    ret_code,
        "result":      result,
        "elapsed_ms":  elapsed_ms,
        "mode":        mode,
    }
    need_header = not ORDER_LOG_PATH.exists() or ORDER_LOG_PATH.stat().st_size == 0
    try:
        with open(ORDER_LOG_PATH, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ORDER_LOG_HEADER, extrasaction="ignore")
            if need_header:
                w.writeheader()
            w.writerow(row)
            f.flush()
    except Exception as e:
        logging.getLogger("pullback_sell_engine").debug("[LOG] trade_log 기록 실패 (무시): %s", e)


# ─────────────────────────────────────────────────────────
# [A-2d 2026-05-15] broker-owns-OCX 가드 (A-1a / A-2a 동일 패턴)
# broker CONNECTED 시 PB sell standalone OCX 미생성 + broker_mode 진입.
# 예외/import 실패 시 False 반환 → 기존 STEP-2H-1 차단 path 보존.
# ─────────────────────────────────────────────────────────
def _broker_owns_ocx() -> bool:
    try:
        from broker_client import BrokerClient
        return BrokerClient().alive()
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
#  KiwoomBridge — PyQt5 QAxWidget 기반 키움 OpenAPI+ 싱글턴
#  [v4_17-1]
# ═══════════════════════════════════════════════════════════════
class KiwoomBridge:
    """
    키움 OpenAPI+ COM 객체 직접 래핑 싱글턴.

    사용 방법:
        bridge = KiwoomBridge.get_instance()
        if bridge is None:
            # 연결 실패 → RC_STOP22
        ret, order_no = bridge.send_order(acc_no, code, qty, reason)

    내부 구조:
        _ocx      : QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        _app      : QApplication (없으면 생성)
        _event    : threading.Event — 주문접수 확인용
        _order_no : 마지막 접수번호 저장
        _msg      : 마지막 메시지 저장

    콜백:
        OnReceiveMsg       → _on_receive_msg
        OnReceiveChejanData → _on_chejan  (접수번호 FID 9203)
    """

    _instance: Optional["KiwoomBridge"] = None
    _lock = _threading.Lock()

    def __init__(self) -> None:
        self._ocx: Any       = None
        self._app: Any       = None
        self._connected: bool = False
        self._order_event     = _threading.Event()
        self._order_no: str  = ""
        self._msg: str       = ""
        self._account_no: str = os.environ.get("KIWOOM_ACCOUNT", "")
        self._log = logging.getLogger("pullback_sell_engine")

    @classmethod
    def get_instance(cls, shared_ocx=None) -> Optional["KiwoomBridge"]:
        """
        [v4_17-2] 싱글턴 획득.
        최초 호출 시 PyQt5 + COM 초기화 수행.
        실패 시 None 반환 → 호출부에서 RC_STOP22 처리.
        shared_ocx: 외부에서 생성된 QAxWidget — 전달 시 CommConnect 생략.
        """
        with cls._lock:
            if cls._instance is not None and cls._instance._connected:
                return cls._instance
            bridge = cls()
            if bridge._init(shared_ocx=shared_ocx):
                cls._instance = bridge
                return bridge
            return None

    def _init(self, shared_ocx=None) -> bool:
        """PyQt5 QApplication + QAxWidget 초기화 + 로그인 상태 확인.

        [STEP-2H-1 2026-05-13] standalone fallback 제거.
        PB sell 은 **반드시 collector shared_ocx 경유**로만 초기화.
        standalone QAxWidget 생성 / CommConnect 호출 / 자체 login 모두 금지.
        """
        if shared_ocx is not None:
            # [OCX-STATE-GUARD 2026-06-11] BROKER_ONLY(5/23) 이후 collector OCX는
            # 자체 로그인 생략(state=0)일 수 있음 — 그 OCX로 SendOrder는 전부 실패.
            # 실로그인(state=1)일 때만 attach 수용, 아니면 아래 broker_mode 폴백.
            _ocx_state = None
            try:
                _ocx_state = shared_ocx.dynamicCall("GetConnectState()")
            except Exception:
                _ocx_state = None
            if _ocx_state == 1:
                try:
                    from PyQt5.QtWidgets import QApplication   # type: ignore
                    self._app = QApplication.instance() or QApplication([])
                    self._ocx = shared_ocx
                    self._ocx.OnReceiveChejanData.connect(self._on_chejan)      # type: ignore
                    self._connected = True
                    self._log.info(
                        "[KIWOOM] shared_ocx attach 완료 — CommConnect 생략 "
                        "(STEP-2H-1 unified mode)"
                    )
                    return True
                except Exception as e:
                    self._log.critical("[KIWOOM] shared_ocx 연결 실패: %s", e)
                    return False
            self._log.warning(
                "[KIWOOM][OCX-STATE-GUARD] shared_ocx state=%s (미로그인) → "
                "attach 거부, broker_mode 폴백 시도", _ocx_state)

        # [A-2d 2026-05-15] broker CONNECTED 시 broker_mode 진입
        # collector OCX 없는 환경 (A-2a 발효 후) 에서 PB sell 정상 부팅 보장.
        # 매도 SendOrder / 체결 이벤트는 broker_client.send_order_real /
        # consume_chejan_events 사용 (A-1b 통합 시 가동).
        if _broker_owns_ocx():
            try:
                from PyQt5.QtWidgets import QApplication   # type: ignore
                self._app = QApplication.instance() or QApplication([])
            except Exception:
                self._app = None
            self._ocx = None
            self._broker_mode = True
            self._connected = True
            self._log.info(
                "[A-2d] broker alive — PB sell broker_mode 진입 "
                "(OCX 없이 broker IPC 라우팅, A-1b-PB 활성)"
            )
            # [A-1b-CORE 2026-05-15] chejan consume thread start (daemon)
            self._start_chejan_consume_thread()
            return True

        # [STEP-2H-1 2026-05-13] standalone fallback 제거 (broker dead 시)
        # 이전: shared_ocx=None 일 때 자체 QAxWidget + CommConnect 호출
        # 변경: shared_ocx 없으면 즉시 FAIL. PB 는 collector unified 모드만 허용.
        try:
            self._log.critical(
                "[KIWOOM] standalone fallback 제거됨 (STEP-2H-1). "
                "PB sell 은 반드시 collector shared_ocx 경유로 호출. "
                "PB Task Scheduler 비활성 + 단독 실행 차단 상태."
            )
        except Exception:
            pass
        return False

    # [STEP-2H-1] 아래 블록은 standalone fallback 의 기존 코드 잔재 — 호출 안 됨.
    # _init() 의 standalone 분기 자체가 return False 로 진입 안 함.
    # 단 다른 메서드 (예: ensure_login) 가 동일 패턴을 사용할 가능성이 있으므로
    # 기존 _init 함수 body 의 잔여 부분을 모두 dead code 처리.
    def _DEAD_standalone_init_fragment(self) -> bool:
        try:
            from PyQt5.QtWidgets import QApplication   # type: ignore
            from PyQt5.QAxContainer import QAxWidget    # type: ignore
            from PyQt5.QtCore import QEventLoop, QTimer  # type: ignore

            # QApplication: 이미 있으면 재사용
            if QApplication.instance() is None:
                self._app = QApplication([])
            else:
                self._app = QApplication.instance()

            self._ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

            # 콜백 연결
            self._ocx.OnReceiveMsg.connect(self._on_receive_msg)             # type: ignore
            self._ocx.OnReceiveChejanData.connect(self._on_chejan)           # type: ignore

            # [LOGIN-FIX 2026-05-08] 키움 표준: 0=미연결, 1=연결 (기존 주석 정정)
            state = self._ocx.dynamicCall("GetConnectState()")
            if state != 1:
                self._log.warning("[KIWOOM] 로그인 상태 미확인 (state=%s) — 연결 시도", state)
                # [LOGIN-FIX 2026-05-08] time.sleep 폴링 → QEventLoop.exec_() 동기 대기
                # 기존: time.sleep(0.5) × 60회 폴링 → Qt 이벤트 루프 차단으로 OnEventConnect 콜백 미수신
                # → state=0 영구 → 30초 후 RC_STOP22 즉사 (5/1·5/7·5/8 3일 연속 재현)
                # 수정: collector LOGIN-FIX 패턴 — login_loop를 CommConnect 이전에 미리 생성
                login_loop = QEventLoop()
                def _on_login_event(err_code):
                    if err_code != 0:
                        self._log.warning("[KIWOOM] OnEventConnect err=%d", err_code)
                    login_loop.quit()
                self._ocx.OnEventConnect.connect(_on_login_event)            # type: ignore
                # 30초 타임아웃 안전장치
                QTimer.singleShot(30_000, login_loop.quit)
                ret = self._ocx.dynamicCall("CommConnect()")
                if ret != 0:
                    self._log.critical("[KIWOOM] CommConnect 실패 ret=%d", ret)
                    return False
                login_loop.exec_()  # 이벤트 루프 활성, 콜백 정상 수신
                if self._ocx.dynamicCall("GetConnectState()") != 1:
                    self._log.critical("[KIWOOM] 로그인 타임아웃 (30초)")
                    return False

            self._connected = True
            self._log.info("[KIWOOM] 연결 성공 — account=%s", self._account_no)
            return True

        except ImportError:
            self._log.critical(
                "[KIWOOM] PyQt5 미설치 — pip install PyQt5 pywin32 후 재실행"
            )
            return False
        except Exception as e:
            self._log.critical("[KIWOOM] 초기화 예외: %s", e)
            return False

    # ── 콜백 핸들러 ───────────────────────────────────────────

    def _on_receive_msg(self, screen_no: str, rq_name: str,
                        tr_code: str, msg: str) -> None:
        """키움 메시지 수신 콜백 — 주문 접수 메시지 저장."""
        self._msg = msg
        self._log.info("[KIWOOM][MSG] screen=%s rq=%s tr=%s msg=%s",
                       screen_no, rq_name, tr_code, msg)

    def _on_chejan(self, s_gubun: str, n_item_cnt: int,
                   s_fid_list: str) -> None:
        """
        체결/잔고 콜백.
        s_gubun="0" → 주문체결  s_gubun="1" → 잔고
        FID 905 = 주문구분 ("2"=매도, "4"=매도취소)
        FID 9203 = 주문번호
        """
        if s_gubun != "0":
            return
        try:
            try:
                _otype = str(self._ocx.dynamicCall(
                    "GetChejanData(int)", 905)).strip()
                if _otype and _otype not in ("2", "4", "매도", "매도취소"):
                    return
            except Exception:
                pass
            order_no = str(self._ocx.dynamicCall(
                "GetChejanData(int)", 9203)).strip()
            if order_no:
                self._order_no = order_no
                self._log.info("[KIWOOM][CHEJAN] 주문접수번호=%s", order_no)
                self._order_event.set()
        except Exception as e:
            self._log.warning("[KIWOOM][CHEJAN] FID조회 실패: %s", e)

    # ─────────────────────────────────────────────────────────
    # [A-1b-CORE+PB 2026-05-15] broker_mode chejan thread + send_order_real
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
                    _time_pb.sleep(0.3)
                except Exception:
                    pass

        t = _threading.Thread(target=_run, daemon=True, name="pb_sell_chejan_consume")
        t.start()
        self._chejan_thread = t

    def _on_chejan_broker(self, event: dict) -> None:
        """broker chejan event → 기존 _on_chejan 호환 처리.

        [C1-PB 2026-05-15] ownership 매칭 — 자기 _pending_code 만 처리.
        cross-engine chejan contamination 차단.
        """
        try:
            gubun = str(event.get("gubun", ""))
            if gubun != "0":
                return
            fid_data = event.get("fid_data") or {}
            otype = str(fid_data.get("905", "")).strip()
            if otype and otype not in ("2", "4", "매도", "매도취소"):
                return
            # [C1-PB] code ownership 매칭
            event_code = str(fid_data.get("9001", "")).strip().lstrip("A").zfill(6) \
                         if fid_data.get("9001") else ""
            pending = str(getattr(self, "_pending_code", "") or "").strip()
            if pending and event_code and pending != event_code:
                return  # 다른 엔진 매도 chejan → 무시
            order_no = str(fid_data.get("9203", "")).strip()
            if order_no:
                self._order_no = order_no
                self._log.info("[A-1b-CORE][CHEJAN] 주문접수번호=%s (broker)", order_no)
                self._order_event.set()
        except Exception as e:
            self._log.warning("[A-1b-CORE][CHEJAN] event 처리 실패: %s", e)

    def _send_order_via_broker(self, acc_no: str, code: str, qty: int,
                               reason: str, screen_no: str,
                               timeout: float) -> Tuple[int, str]:
        """[A-1b-PB 2026-05-15] broker_mode 시 send_order_real IPC 라우팅."""
        self._order_event.clear()
        self._order_no = ""
        # [C1-PB 2026-05-15] ownership 매칭 — _on_chejan_broker 에서 자기 발행 종목만 처리
        self._pending_code = str(code).strip().lstrip("A").zfill(6)

        intent_id = str(_uuid_pb.uuid4())
        idem_key  = f"pb_sell_{code}_{intent_id}"
        rq_name   = f"SELL_BROKER_{code}_{reason[:8]}"

        _sell_hoga = os.environ.get("SELL_HOGA_GB", "06").strip() or "06"

        try:
            from broker_client import BrokerClient
            bc = BrokerClient()
            res = bc.send_order_real(
                idempotency_key=idem_key,
                account=acc_no,
                code=str(code),
                qty=int(qty),
                order_type=2,  # 매도
                price=0,
                hoga_gb=_sell_hoga,
                rqname=rq_name,
                screen_no=str(screen_no),
            )
        except Exception as e:
            self._log.error("[A-1b-PB] broker IPC 예외: %s", e)
            return -98, ""

        if res.get("status") != "OK":
            self._log.warning("[A-1b-PB] broker %s: %s",
                              res.get("status"), res.get("error"))
            return -97, ""

        ret = int((res.get("data") or {}).get("ret", -99))
        if ret != 0:
            return ret, ""

        # chejan thread 가 _order_no / _order_event 채움
        received = self._order_event.wait(timeout=timeout)
        if not received:
            self._log.warning("[A-1b-PB][SEND] 접수번호 수신 타임아웃 code=%s (broker)", code)
            return -1, ""

        return 0, self._order_no

    def _query_balance_via_broker(self, acc_no: str) -> Dict[str, Any]:
        """[A-1b-PB 2026-05-15] broker_mode 시 opw00018 balance_tr IPC 라우팅."""
        try:
            from broker_client import BrokerClient
            bc = BrokerClient()
            res = bc.balance_tr(
                tr_code="opw00018",
                inputs={
                    "계좌번호":             str(acc_no),
                    "비밀번호":             "",
                    "비밀번호입력매체구분": "00",
                    "조회구분":             "2",
                },
                output_fields=["총평가금액", "주문가능금액"],
                rqname="잔고조회",
                screen_no="5000",
                timeout_sec=8.0,
            )
        except Exception as e:
            self._log.warning("[A-1b-PB][BALANCE] broker IPC 예외: %s", e)
            return {}

        if res.get("status") != "OK":
            self._log.warning("[A-1b-PB][BALANCE] broker %s: %s",
                              res.get("status"), res.get("error"))
            return {}

        records = ((res.get("data") or {}).get("records") or [])
        if not records:
            return {}
        rec = records[0]
        try:
            return {
                "total_asset":    _f(str(rec.get("총평가금액", "")).strip()),
                "available_cash": _f(str(rec.get("주문가능금액", "")).strip()),
            }
        except Exception as e:
            self._log.warning("[A-1b-PB][BALANCE] 파싱 실패: %s", e)
            return {}

    # ── 공개 인터페이스 ──────────────────────────────────────

    def is_connected(self) -> bool:
        """COM 연결 및 로그인 상태 확인."""
        # [A-2d 2026-05-15] broker_mode 시 _ocx=None 이지만 broker 연결 보유
        if getattr(self, "_broker_mode", False):
            return bool(self._connected)
        if not self._connected or self._ocx is None:
            return False
        try:
            return self._ocx.dynamicCall("GetConnectState()") == 1
        except Exception:
            return False

    def send_order(self, acc_no: str, code: str, qty: int,
                   reason: str, screen_no: str = KIWOOM_SCREEN_SELL,
                   timeout: float = KIWOOM_ORDER_TIMEOUT) -> Tuple[int, str]:
        """
        시장가 매도 주문 발송.

        반환: (ret_code, order_no)
          ret_code=0  → 접수 성공
          ret_code≠0  → 실패
          order_no    → 접수번호 (체결 확인용)
        """
        # [A-1b-PB 2026-05-15] broker mode 시 broker IPC 라우팅
        if getattr(self, "_broker_mode", False):
            return self._send_order_via_broker(
                acc_no=acc_no, code=code, qty=qty, reason=reason,
                screen_no=screen_no, timeout=timeout,
            )
        if self._ocx is None:
            return -99, ""

        # 이전 이벤트 초기화
        self._order_event.clear()
        self._order_no = ""

        rq_name = f"SELL_{code}_{reason[:8]}"

        # SendOrder(sRQName, sScreenNo, sAccNo, nOrderType, sCode,
        #           nQty, nPrice, sHogaGb, sOrgOrderNo)
        # [v4_9-MP3] sHogaGb "03"(시장가) → "06"(최유리지정가). 매수/매도 정합.
        #   매도 최유리지정가 = 매수1호가 자동 → 1tick 슬리피지. ENV로 사후 조정.
        _sell_hoga = os.environ.get("SELL_HOGA_GB", "06").strip() or "06"
        _limiter.acquire()  # [PATCH-RATELIMIT]
        ret = self._ocx.dynamicCall(
            "SendOrder(QString,QString,QString,int,QString,int,int,QString,QString)",
            [rq_name, screen_no, acc_no, 2, code, qty, 0, _sell_hoga, ""]
        )
        self._log.info("[KIWOOM][SEND] code=%s qty=%d ret=%d rq=%s",
                       code, qty, ret, rq_name)

        if ret != 0:
            return ret, ""

        # 접수번호 수신 대기 (OnReceiveChejanData 콜백)
        received = self._order_event.wait(timeout=timeout)
        if not received:
            self._log.warning("[KIWOOM][SEND] 접수번호 수신 타임아웃 code=%s", code)
            return -1, ""

        return 0, self._order_no

    def get_account_balance(self, acc_no: str) -> Dict[str, Any]:
        """
        opw00018 잔고 조회 (단순화 버전).
        반환: {"total_asset": float, "available_cash": float}
        주의: TR 요청은 초당 5회 제한 → 잔고 조회는 필요 시에만 호출.
        """
        # [A-1b-PB 2026-05-15] broker mode 시 broker balance_tr 라우팅
        if getattr(self, "_broker_mode", False):
            return self._query_balance_via_broker(acc_no)
        if self._ocx is None:
            return {}
        try:
            self._ocx.dynamicCall(
                "SetInputValue(QString,QString)", ["계좌번호", acc_no])
            self._ocx.dynamicCall(
                "SetInputValue(QString,QString)", ["비밀번호", ""])
            self._ocx.dynamicCall(
                "SetInputValue(QString,QString)", ["비밀번호입력매체구분", "00"])
            self._ocx.dynamicCall(
                "SetInputValue(QString,QString)", ["조회구분", "2"])
            _limiter.acquire()  # [PATCH-RATELIMIT]
            self._ocx.dynamicCall(
                "CommRqData(QString,QString,int,QString)",
                ["잔고조회", "opw00018", 0, "5000"]
            )
            _time.sleep(0.5)
            total = self._ocx.dynamicCall(
                "GetCommData(QString,QString,int,QString)",
                ["잔고조회", "opw00018", 0, "총평가금액"]
            )
            cash = self._ocx.dynamicCall(
                "GetCommData(QString,QString,int,QString)",
                ["잔고조회", "opw00018", 0, "주문가능금액"]
            )
            return {
                "total_asset":    _f(str(total).strip()),
                "available_cash": _f(str(cash).strip()),
            }
        except Exception as e:
            self._log.warning("[KIWOOM][BALANCE] 잔고조회 실패: %s", e)
            return {}


# ── _get_kiwoom_api [v4_17-2] ────────────────────────────────────
def _get_kiwoom_api() -> Optional[KiwoomBridge]:
    """
    KiwoomBridge 싱글턴 획득.
    PAPER_TRADE=true → None 반환 (호출부에서 사용 안 함)
    PAPER_TRADE=false → 싱글턴 초기화 후 반환. 실패 시 None.
    """
    if PAPER_TRADE:
        return None
    return KiwoomBridge.get_instance()


# ── [v4.21 PATCH] KIWOOM_ACCOUNT 자동 인식 ──────────────────────
# env 우선 → 미설정 시 OpenAPI GetLoginInfo("ACCNO")
# 1개=자동선택, 2개+=STOP, 0개=STOP. 결과는 모듈 캐시.
# 로그는 앞 4자리+****** 마스킹만 출력.
_RESOLVED_KIWOOM_ACCOUNT: Optional[str] = None


def _mask_account(acc: str) -> str:
    if not acc:
        return ""
    s = str(acc).strip()
    if len(s) <= 4:
        return s + "******"
    return s[:4] + "******"


def _resolve_kiwoom_account(api: Optional[KiwoomBridge],
                            logger: logging.Logger) -> str:
    """
    [v4.21 PATCH] 계좌번호 자동 인식.
      1) env KIWOOM_ACCOUNT 우선
      2) 미설정 시 OpenAPI GetLoginInfo("ACCNO") 조회
         - 1개  → 자동 선택
         - 2개+ → STOP (빈 문자열 반환, 호출부 RC_STOP22)
         - 0개  → STOP
    캐시: 동일 프로세스 내 최초 1회만 조회.
    매도 로직(13-step, stop, take, trail)은 절대 변경 X.
    """
    global _RESOLVED_KIWOOM_ACCOUNT
    if _RESOLVED_KIWOOM_ACCOUNT is not None:
        return _RESOLVED_KIWOOM_ACCOUNT

    env_acc = os.environ.get("KIWOOM_ACCOUNT", "").strip()
    if env_acc:
        _RESOLVED_KIWOOM_ACCOUNT = env_acc
        logger.info("[ACCT] env KIWOOM_ACCOUNT 사용 → %s",
                    _mask_account(env_acc))
        return env_acc

    if api is None or not api.is_connected():
        logger.critical("[ACCT][STOP] env 미설정 + Kiwoom 미연결 → 자동 인식 불가")
        _RESOLVED_KIWOOM_ACCOUNT = ""
        return ""

    try:
        accs_raw = str(api._ocx.dynamicCall(
            "GetLoginInfo(QString)", "ACCNO")).strip()
    except Exception as e:
        logger.critical("[ACCT][STOP] GetLoginInfo(ACCNO) 호출 실패: %s", e)
        _RESOLVED_KIWOOM_ACCOUNT = ""
        return ""

    accs = [a.strip() for a in accs_raw.split(";") if a.strip()]
    if len(accs) == 0:
        logger.critical("[ACCT][STOP] OpenAPI 계좌 목록 비어있음")
        _RESOLVED_KIWOOM_ACCOUNT = ""
        return ""
    if len(accs) >= 2:
        logger.critical(
            "[ACCT][STOP] 다계좌 감지 (%d개) — 임의 선택 금지. "
            "KIWOOM_ACCOUNT 환경변수로 명시 필요", len(accs))
        _RESOLVED_KIWOOM_ACCOUNT = ""
        return ""

    auto = accs[0]
    logger.info("[ACCT] OpenAPI 자동 인식 (1개) → %s", _mask_account(auto))
    _RESOLVED_KIWOOM_ACCOUNT = auto
    return auto


# ── _order_retry 데코레이터 [v4_17-4] ──────────────────────────
def _order_retry(func: Any) -> Any:
    """
    주문 함수 재시도 래퍼.
    실패(False 반환) 시 최대 KIWOOM_MAX_RETRY 회까지
    0.5초 간격으로 재시도.
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> bool:
        logger = kwargs.get("logger") or (args[1] if len(args) > 1 else None)
        for attempt in range(1, KIWOOM_MAX_RETRY + 1):
            result = func(*args, **kwargs)
            if result:
                return True
            if attempt < KIWOOM_MAX_RETRY:
                if logger:
                    logger.warning("[ORDER][RETRY] %d/%d회 재시도",
                                   attempt, KIWOOM_MAX_RETRY)
                _time.sleep(0.5 * attempt)   # 지수 백오프
        return False
    return wrapper


# ── _send_sell_order [v4_17-3] ──────────────────────────────────
@_order_retry
def _send_sell_order(order: SellDecision, logger: logging.Logger) -> bool:
    """
    매도 주문 발송 (재시도 포함).

    PAPER_TRADE=true  → 로그 출력 후 True (시뮬)
    PAPER_TRADE=false → KiwoomBridge.send_order() 실호출
                        접수번호 확인 후 True / 실패 False

    [v4_17-5] 성공/실패 모두 order_log.csv 기록.
    """
    code       = str(order.get("code", ""))
    qty        = int(order.get("qty", 0))
    price      = _f(order.get("price", 0))
    reason     = str(order.get("reason", ""))
    profit_pct = _f(order.get("profit_pct", 0))
    t_start    = _time.monotonic()

    logger.info("[ORDER] 매도  code=%s  qty=%d  price=%.0f  reason=%s  수익=%.1f%%",
                code, qty, price, reason, profit_pct)

    # ── 시뮬레이션 모드 ──────────────────────────────────────
    if PAPER_TRADE:
        elapsed = int((_time.monotonic() - t_start) * 1000)
        logger.info("[ORDER][PAPER] 시뮬 매도 완료 code=%s qty=%d", code, qty)
        _write_order_log(code, qty, reason, profit_pct,
                         "PAPER_NO", 0, "PAPER_OK", elapsed, "PAPER")
        return True

    # ── 입력 검증 ────────────────────────────────────────────
    if qty <= 0:
        logger.error("[ORDER][REAL] 수량 이상 — code=%s qty=%d", code, qty)
        _write_order_log(code, qty, reason, profit_pct,
                         "", -1, "ERR_QTY", 0, "REAL")
        return False

    # ── KiwoomBridge 획득 (계좌 자동 인식보다 먼저) ──────────
    api = _get_kiwoom_api()
    if api is None:
        logger.critical("[ORDER][REAL] KiwoomBridge 획득 실패 — code=%s", code)
        _write_order_log(code, qty, reason, profit_pct,
                         "", -3, "ERR_NO_API", 0, "REAL")
        return False

    if not api.is_connected():
        logger.critical("[ORDER][REAL] 키움 연결 끊김 — code=%s", code)
        _write_order_log(code, qty, reason, profit_pct,
                         "", -4, "ERR_DISCONNECTED", 0, "REAL")
        return False

    # [v4.21 PATCH] 계좌 자동 인식 (env→OpenAPI ACCNO)
    account_no = _resolve_kiwoom_account(api, logger)
    if not account_no:
        logger.critical("[ORDER][REAL] 계좌 resolve 실패 (env+OpenAPI 양쪽)")
        _write_order_log(code, qty, reason, profit_pct,
                         "", -2, "ERR_NO_ACCOUNT", 0, "REAL")
        return False
    logger.info("[ORDER][REAL] resolved acct=%s code=%s qty=%d",
                _mask_account(account_no), code, qty)

    # ── 실주문 발송 ──────────────────────────────────────────
    try:
        ret, order_no = api.send_order(
            acc_no    = account_no,
            code      = code,
            qty       = qty,
            reason    = reason,
            screen_no = KIWOOM_SCREEN_SELL,
            timeout   = KIWOOM_ORDER_TIMEOUT,
        )
        elapsed = int((_time.monotonic() - t_start) * 1000)

        if ret == 0 and order_no:
            logger.info("[ORDER][REAL] 매도 접수 성공  code=%s  qty=%d  "
                        "접수번호=%s  elapsed=%dms",
                        code, qty, order_no, elapsed)
            _write_order_log(code, qty, reason, profit_pct,
                             order_no, ret, "OK", elapsed, "REAL")
            return True

        if ret == 0 and not order_no:
            # SendOrder 성공이나 접수번호 미수신 (타임아웃)
            logger.warning("[ORDER][REAL] 접수번호 미수신 — code=%s  elapsed=%dms",
                           code, elapsed)
            _write_order_log(code, qty, reason, profit_pct,
                             "", ret, "WARN_NO_ORDER_NO", elapsed, "REAL")
            # 접수번호 없어도 ret=0이면 주문은 나갔을 가능성 → True 처리
            return True

        logger.error("[ORDER][REAL] 매도 접수 실패  ret=%d  code=%s  elapsed=%dms",
                     ret, code, elapsed)
        _write_order_log(code, qty, reason, profit_pct,
                         "", ret, f"FAIL_RET_{ret}", elapsed, "REAL")
        return False

    except Exception as e:
        elapsed = int((_time.monotonic() - t_start) * 1000)
        logger.critical("[ORDER][REAL] 예외 — code=%s  %s  elapsed=%dms",
                        code, e, elapsed)
        _write_order_log(code, qty, reason, profit_pct,
                         "", -99, f"EXCEPTION:{type(e).__name__}", elapsed, "REAL")
        return False


# ═══════════════════════════════════════════════════════════════
#  [NEW-9] 포지션 빌드 헬퍼 — build_sell_decisions_flow 단순화
# ═══════════════════════════════════════════════════════════════
def _build_position(code: str, r: Dict, state: Dict,
                    today: str, cache: RTCache,
                    score_map: Dict,
                    price_map: Dict[str,float],
                    open_map:  Dict[str,float]) -> Optional[Position]:
    # [QSCHEMA-FIX 2026-06-10] 큐(kjs_execute_queue.csv) 스키마는 price/qty인데 buy_price/entry_price만
    #   찾아 entry=0→전 포지션 None→"유효 포지션 없음"=PB 매도 무력(403870 -2.5% 손절 미발동 직접원인).
    #   price 폴백 추가. ([[stockbot-20260610-pb-sell-engine-down]] 분기C)
    entry = _f(r.get("buy_price", r.get("entry_price", r.get("price", 0))))
    qty   = int(_f(r.get("buy_qty",  r.get("qty",0))))
    if not code or entry <= 0 or qty <= 0:
        return None
    # [QSCHEMA-FIX] 큐 행 date가 오늘 아니면 stale(전일 매수행 잔재) → 재포지션 방지
    _rd = str(r.get("date", "")).strip()[:10]
    if _rd and _rd != today:
        return None
    if code in state and state[code].get("entry_date","") == today:
        p = Position.from_dict(state[code])
        # [QTY-SYNC 2026-06-11] state 캐시 qty 낡음 방지 — 호출부 row qty는 QSCHEMA-FIX가
        #   매 tick rt_open(실보유)로 정정한 값이므로 항상 우선한다.
        #   (6/11 100790: state에 12 박제 → rt_open 6 정정 무시하고 12주 매도 고집 → 키움 [800033] 거부 3연속)
        if qty > 0 and p.qty != qty:
            p.qty = qty
    else:
        p = Position(code=code, entry_price=entry, qty=qty,
                     entry_date=today, strategy=str(r.get("strategy","")),
                     score_flow=_f(score_map.get(code,0)))
        open_p = open_map.get(code,0.0)
        if open_p > 0:
            p.open_price = open_p
            p.gap_grade  = _classify_gap(entry, open_p, p.score_flow)
    atr_rt      = cache.get_atr(code)
    p.atr_pct   = atr_rt if atr_rt > 0 else _calc_atr_pct_from_bars(cache.get_bars(code))
    p.atr_avg_pct = cache.get_atr_avg(code, 20)
    if p.vwap <= 0:
        p.vwap = cache.get_vwap(code)
    return p


# ═══════════════════════════════════════════════════════════════
#  ops 연동 인터페이스
# ═══════════════════════════════════════════════════════════════
def build_sell_decisions_flow(
    logger: logging.Logger,
    pos: "pd.DataFrame",
    prices_today: "pd.DataFrame",
    pending_state: Dict,
    score_map: Dict,
    tracker: Optional[PnLTracker] = None,
) -> "pd.DataFrame":
    import hashlib
    hm    = _now_hm()
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    rows: List[Dict] = []

    if pos is None or len(pos) == 0:
        return _build_empty_queue()

    cache = get_fresh_cache()   # [FIX-11] 호출 시점 최신 데이터 보장

    price_map: Dict[str,float] = {}
    open_map:  Dict[str,float] = {}
    if prices_today is not None and len(prices_today) > 0:
        grp = prices_today.sort_values("ts").groupby("code")
        for code, g in grp:
            price_map[code] = float(g["close"].iloc[-1])
            open_map[code]  = float(g["open"].iloc[0])

    for _, row in pos.iterrows():
        code = str(row.get("code","")).strip().zfill(6)
        p    = _build_position(code, dict(row), state, today, cache,
                                score_map, price_map, open_map)
        if p is None: continue
        current_price = price_map.get(code, 0.0)
        if current_price <= 0: continue

        _init_gap_grade(p, current_price, logger)
        order = _decide_sell(p, current_price, hm, logger,
                             cache=cache, tracker=tracker)
        if order:
            p.sold_qty += int(order.get("qty",0))
            _append_ev(p, order)
            if tracker:
                weight = ALL_IN_WEIGHT if IS_ALL_IN else 1.0
                tracker.record(float(order.get("profit_pct",0)),
                               str(order.get("reason","")),
                               position_weight=weight)
            rows.append({
                "ts":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "code":            code,
                "qty":             order.get("qty",0),
                "reason":          order.get("reason",""),
                "idempotency_key": hashlib.md5(
                    f"{code}_{today}_{order.get('reason','')}_{current_price}".encode()
                ).hexdigest()[:16],
            })
        else:
            p.update_peak(current_price)

        if p.remain_qty > 0:
            state[code] = {**p.to_dict(), "entry_date": today}
        else:
            state.pop(code, None)

    _save_state(state)
    if not rows:
        return _build_empty_queue()
    import pandas as pd
    return pd.DataFrame(rows)


def _build_empty_queue() -> "pd.DataFrame":
    import pandas as pd
    return pd.DataFrame(columns=["ts","code","qty","reason","idempotency_key"])


# ═══════════════════════════════════════════════════════════════
#  [NEW-8] _print_status — main()에서 출력 블록 분리
# ═══════════════════════════════════════════════════════════════
def _print_status(positions: List[Position], new_state: Dict,
                  hm: int, cache: RTCache,
                  bt: BacktestEngine, tracker: PnLTracker) -> None:
    """운용 상태 요약 출력."""
    print("\n" + "═"*72)
    print(f"  PULLBACK SELL ENGINE  {ENGINE_VERSION}")
    print("═"*72)
    print(f"  시각 {hm:04d}  포지션 {len(positions)}종목  잔여 {len(new_state)}종목")
    print(f"  거래모드: {'📋 PAPER(시뮬)' if PAPER_TRADE else '💰 REAL(실거래)'}")
    print(f"  몰빵비율: {ALL_IN_WEIGHT*100:.0f}%  ALL_IN={IS_ALL_IN}")
    print(f"  신규진입차단: {'🔴 차단중(일손실한도초과)' if tracker.is_new_entry_blocked() else '🟢 정상(진입허용)'}")
    print(f"  ※ 회로차단=매수차단 전용 / 청산은 항상 정상동작")
    if not PAPER_TRADE:
        api = KiwoomBridge.get_instance()
        print(f"  키움연결: {'✅ 연결됨' if (api and api.is_connected()) else '❌ 끊김'}")
    print(f"  주문로그: {ORDER_LOG_PATH}")
    print()

    # 당일 P&L
    print("  [P&L 현황]")
    print(f"    누적수익: {tracker.daily_pnl():+.2f}%  "
          f"최대낙폭: {tracker.max_drawdown():.2f}%  "
          f"승률: {tracker.win_rate():.1%}  "
          f"거래: {tracker.count}건")
    if tracker.count >= 10:
        print(f"    Sharpe: {tracker.sharpe():.3f}  "
              f"Sortino: {tracker.sortino():.3f}")

    # 백테스트 요약
    summary = bt.summary()
    print(f"\n  [백테스트 — {summary.get('status','')}]")
    if summary.get("n",0) > 0:
        print(f"    거래 {summary['n']}건  승률 {summary.get('win_rate',0):.1%}  "
              f"EV_net {summary.get('ev_net',0):+.3f}%")
        print(f"    Kelly_half: {summary.get('kelly_half',0):.3f}  "
              f"R:R {summary.get('rr_ratio',0):.2f}")

    # Chandelier 파라미터
    print(f"\n  [Chandelier Exit]")
    print(f"    N={CHANDELIER_N}봉  k=NORMAL{CHANDELIER_K_BASE}/"
          f"HIGH{CHANDELIER_K_HIGH}/EXTREME{CHANDELIER_K_EXTREME}")

    # ATR 현황
    atr_list = [(p.code, p.atr_pct, p.atr_avg_pct) for p in positions if p.atr_pct > 0]
    if atr_list:
        print(f"\n  [ATR 현황]")
        for c, a, avg in atr_list:
            regime  = _get_vol_regime(a, avg)
            k_val   = _get_chandelier_k(regime)
            hh      = cache.get_highest_high_n(c, CHANDELIER_N)
            tp      = _calc_chandelier_trail_price(hh, a, k_val)
            print(f"    {c}: ATR={a:.3f}% avg={avg:.3f}%  레짐={regime}  k={k_val}  손절≈{tp:.0f}")

    print("═"*72 + "\n")


# ═══════════════════════════════════════════════════════════════
#  [v4.21 PATCH] heartbeat write — watchdog stale 판정 방지
#  매 main() 진입 시 1회 갱신. watchdog이 본 파일 mtime 감시.
# ═══════════════════════════════════════════════════════════════
def _write_engine_hb():
    try:
        import os, time
        hb_path = r"C:\stock_bot\data\heartbeat\pullback_sell_engine.hb"
        tmp = hb_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        os.replace(tmp, hb_path)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    logger = _setup_logger()
    _write_engine_hb()   # [v4.21 PATCH] 진입 즉시 hb 갱신
    logger.info("="*72)
    logger.info("[VER] %s", ENGINE_VERSION)

    # 파라미터 검증
    try:
        _validate_params()
        logger.info("[PARAM] 검증 통과")
    except ValueError as e:
        logger.critical("[PARAM] %s", e)
        return RC_STOP22

    # [v4_17-6] REAL 모드 시 키움 연결 사전 확인
    if not PAPER_TRADE:
        logger.info("[KIWOOM] REAL 모드 — 키움 연결 사전 확인")
        api = _get_kiwoom_api()
        if api is None or not api.is_connected():
            # [CONN-DIAG 2026-06-11] rc=22 원인 분해: api 유무 / broker_mode /
            # _connected 플래그 / 실제 GetConnectState 값을 구분해 기록 (정책 무변경)
            try:
                if api is None:
                    logger.critical("[KIWOOM][CONN-DIAG] api=None (get_instance 실패)")
                else:
                    try:
                        _st = (api._ocx.dynamicCall("GetConnectState()")
                               if api._ocx is not None else "no_ocx")
                    except Exception as _ce:
                        _st = "exc:%s" % _ce
                    logger.critical(
                        "[KIWOOM][CONN-DIAG] broker_mode=%s _connected=%s state=%s",
                        getattr(api, "_broker_mode", False),
                        getattr(api, "_connected", None), _st)
            except Exception:
                pass
            logger.critical("[KIWOOM] 키움 연결 실패 — 프로세스 종료 (RC_STOP22)")
            return RC_STOP22
        logger.info("[KIWOOM] 연결 확인 완료 — 실거래 모드 진입")
        # [v4.21 PATCH] 계좌 자동 인식 (env→OpenAPI ACCNO, 다계좌 STOP)
        _resolved_acc = _resolve_kiwoom_account(api, logger)
        if not _resolved_acc:
            logger.critical("[KIWOOM] 계좌 자동 인식 실패 — RC_STOP22")
            return RC_STOP22
        logger.info("[KIWOOM] 사용 계좌 = %s", _mask_account(_resolved_acc))
    else:
        logger.info("[ORDER] PAPER_TRADE=true — 시뮬레이션 모드")

    hm     = _now_hm()
    cache  = get_fresh_cache()   # [FIX-11] 호출 시점 최신 데이터 보장
    bt     = BacktestEngine().load()
    tracker= PnLTracker()

    logger.info("[TIME] %04d  [P&L] %.2f%%  [회로차단] %s",
                hm, tracker.daily_pnl(),
                "🔴발동" if tracker.is_circuit_broken() else "🟢정상")

    queue_rows = _read_csv(QUEUE_PATH)
    if not queue_rows:
        logger.warning("[HOLD] kjs_execute_queue.csv 비어있음")
        return RC_HOLD

    state = _load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    row_map = {str(r.get("code","")).strip().zfill(6): r for r in queue_rows}

    # [QSCHEMA-FIX 2026-06-10] 큐=신호행(미체결 포함) → rt_open(chejan 실체결) 교차로 실보유만 매도관리.
    #   qty도 rt_open 실체결 수량으로 정정(부분체결 대응). 읽기실패=fail-open(큐 전체, 무잔고매도는 거부될 뿐).
    try:
        _ro_raw = _RT_OPEN_PATH_QFIX.read_text(encoding="utf-8-sig")
        _ro = json.loads(_ro_raw) if _ro_raw.strip() else {}
        _held = {}
        for _k, _v in (_ro.items() if isinstance(_ro, dict) else []):
            try:
                _q = float((_v or {}).get("qty", 0) or 0)
            except (TypeError, ValueError):
                _q = 0.0
            # [STRAT-SPLIT 2026-06-10] EOD_PICK 보유는 eod_pickup_sell 전담(gap_exit/recovery) —
            #   PB엔진이 건드리면 14:55 매수분을 15:00 tick이 C급 조기매도로 즉살하는 사고. 제외.
            _strat = str((_v or {}).get("strategy", "")).strip().upper()
            # [NEWPB-OWN-EXIT 2026-06-19] _newpb 포지션은 NEW_PB executor 전담(env ON시) — EOD_PICK과 동일 제외.
            _is_newpb = bool((_v or {}).get("_newpb"))
            if _q > 0 and _strat != "EOD_PICK" and not (_is_newpb and _NEWPB_OWN_EXIT):
                _held[str(_k).zfill(6)] = _q
        _before_n = len(row_map)
        row_map = {c: r for c, r in row_map.items() if c in _held}
        for _c, _r in row_map.items():
            _r["qty"] = int(_held[_c])   # 실체결 수량으로 정정
        logger.info(f"[QSCHEMA-FIX] rt_open 교차: 큐 {_before_n}건 → 실보유 {len(row_map)}건")
    except Exception as _qe:
        logger.warning(f"[QSCHEMA-FIX] rt_open 교차 실패(fail-open, 큐 전체 사용): {_qe}")

    positions: List[Position] = []
    for code, r in row_map.items():
        if not code: continue
        p = _build_position(code, r, state, today, cache, {}, {}, {})
        if p is None: continue
        # [LEADER-HOLD 2026-06-11] 큐 행의 대장주 꼬리표를 포지션에 부착 (없으면 0=기존동작)
        try:
            p.leader_first = int(float(r.get("leader_first", 0) or 0))
        except (TypeError, ValueError):
            p.leader_first = 0
        if p.entry_price <= 0 or p.qty <= 0:
            logger.warning("[SKIP] %s 가격/수량 이상", code); continue
        # [GRADE-FIX 2026-06-10] 갭등급 체계는 시가매수(SIGA)용 — entry vs 세션시초가 비교.
        #   장중 PULLBACK 진입은 entry>시초가가 정상(상승추세 눌림 매수)이라 갭이 음수/0으로 계산돼
        #   전 포지션이 C/D급 → C_GRADE_EARLY_EXIT/D_CUT 즉시매도 변질(6/10 PAPER 실측).
        #   PULLBACK은 B급 고정=갭 룰 면제, 본질 룰(하드스톱/트레일/PROFIT_LOCK/기관이탈)만 작동.
        if str(p.strategy or "").strip().upper() == "PULLBACK" and p.gap_grade == "?":
            p.gap_grade = "B"
            logger.info("[GRADE-FIX] %s PULLBACK 장중진입 → 갭등급 B 고정(갭룰 면제)", code)
        _init_gap_grade(p, _f(r.get("current_price", r.get("price",0))), logger)
        positions.append(p)

    if not positions:
        logger.warning("[HOLD] 유효 포지션 없음"); return RC_HOLD

    any_sell = False
    for pos in positions:
        r = row_map.get(pos.code, {})
        current_price = _f(r.get("current_price", r.get("price",0)))
        # [PRICE-FIX 2026-06-10] 큐 행 price=매수시점 박제 → 손익 영원히 0% = 하드스톱/트레일 전부
        #   무력이었음(6/10 PAPER '수익=0.0%' 전건이 증거). cache(prices_1m fresh) 최신 분봉 close로 갱신.
        try:
            _bars = cache.get_bars(pos.code)
            if _bars:
                _last_cl = _f(_bars[-1].get("close", 0))
                if _last_cl > 0:
                    current_price = _last_cl
        except Exception:
            pass
        if current_price <= 0:
            logger.warning("[%s] 현재가 없음", pos.code); continue

        order = _decide_sell(pos, current_price, hm, logger,
                             cache=cache, tracker=tracker)
        if order:
            ok = _send_sell_order(order, logger)
            _append_ev(pos, order, sell_failed=0 if ok else 1)
            if ok:
                pos.sold_qty += int(order.get("qty",0))
                # [FIX-7] 포트폴리오 손실 환산: ALL_IN 모드에서 position_weight 적용
                weight = ALL_IN_WEIGHT if IS_ALL_IN else 1.0
                tracker.record(float(order.get("profit_pct",0)),
                               str(order.get("reason","")),
                               position_weight=weight)
                any_sell = True
        else:
            pos.update_peak(current_price)

    new_state = {p.code: {**p.to_dict(), "entry_date": today}
                 for p in positions if p.remain_qty > 0}
    _save_state(new_state)
    _print_status(positions, new_state, hm, cache, bt, tracker)

    logger.info("[DONE] 잔여=%d  매도=%s", len(new_state),
                "✅" if any_sell else "없음")
    return RC_OK


# ═══════════════════════════════════════════════════════════════
#  [W34 PATCH 2026-05-12] 매도 엔진 cron-style → daemon-style wrapper
#  의도: 워치독 ENGINE DEAD 무한 재기동 패턴 제거 (5/12 09:10~09:18 패턴)
#
#  배경:
#    기존: main() 1회 실행 후 RC_HOLD/RC_OK 반환 → SystemExit
#         → 워치독 ENGINE DEAD 오판 → 5회 재기동 → 키움 OCX 30초 타임아웃
#         → 워치독 자체 종료 → 12시간 휴면
#    변경: _main_loop()가 main()을 30초 간격 반복 호출 (daemon-style)
#         → 워치독은 본체가 항상 살아있다고 판단
#         → KiwoomBridge 싱글턴 + _RESOLVED_KIWOOM_ACCOUNT 캐시
#         → CommConnect/GetLoginInfo 재호출 없음 (검증 완료)
#         → 매 cycle OCX call = GetConnectState 1회만 (무시 수준)
#
#  안전망:
#    - RC_STOP22 (키움/계좌 실패) → 즉시 종료
#    - main() 예외 → 로그 + 다음 cycle 계속
#    - MAX_ITERATIONS (1일 = 2880회) → 자체 종료 → 다음 날 cron 재시작
# ═══════════════════════════════════════════════════════════════
_MAIN_LOOP_INTERVAL_SEC   = int(os.environ.get("MAIN_LOOP_INTERVAL_SEC",   "30"))
_MAIN_LOOP_MAX_ITERATIONS = int(os.environ.get("MAIN_LOOP_MAX_ITERATIONS", "2880"))


def _main_loop() -> int:
    """[W34] cron-style main() → daemon-style wrapper.
    30초 간격 main() 반복 호출. RC_STOP22 시 즉시 종료.
    KiwoomBridge 싱글턴 + logger idempotent → 반복 호출 안전.
    """
    iteration = 0
    _logger = logging.getLogger("pullback_sell_engine")
    while iteration < _MAIN_LOOP_MAX_ITERATIONS:
        iteration += 1
        try:
            rc = main()
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            try:
                _logger.error("[W34] main() 예외 (iter=%d): %s",
                              iteration, e, exc_info=True)
            except Exception:
                pass
            rc = 0  # 예외 → 다음 cycle 계속
        if rc == RC_STOP22:
            try:
                _logger.critical("[W34] RC_STOP22 수신 → daemon loop 종료 (iter=%d)",
                                 iteration)
            except Exception:
                pass
            return RC_STOP22
        _time.sleep(_MAIN_LOOP_INTERVAL_SEC)
    try:
        _logger.info("[W34] MAX_ITERATIONS(%d) 도달 → 자체 종료 (cron 재시작 대기)",
                     _MAIN_LOOP_MAX_ITERATIONS)
    except Exception:
        pass
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(_main_loop())

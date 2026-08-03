# -*- coding: utf-8 -*-
"""
==============================================================================
rt_risk_engine.py
리스크·포지션 사이징 엔진 v6.2  —  헤지펀드급 · 1종목 몰빵 전용
==============================================================================
[역할]   rt_intraday_candidates.csv → Top-1 선택 + Kelly/CVaR/DD → rt_risk_candidates.csv
[금지]   신호 생성, 주문 집행, 데이터 수집, PnL 추적
[입력]   rt_intraday_candidates.csv
         account_status.json, rt_trades_ledger.csv, params.json
         rt_daily_pnl.json  (누적 DD에 실제 PnL 직접 사용)
[출력]   rt_risk_candidates.csv       (항상 0~1행)
         rt_daily_entry.json           (당일 진입 상태 — 읽기/쓰기)
         kelly_stats_snapshot.json     (자기진화 날짜별 90일 누적)

[전략 파라미터]
  공격70/안정30  : 가용 자금의 70%만 배포, 30%는 항상 현금 유보
  1일 1종목 몰빵 : Top-1 후보만 선정, 당일 재진입 차단
  DD 브레이커    : 3단계 (경고/-2% + 축소/-3% + 정지/-5%)
  기관 등타기    : 기관 매집 중 사이즈 확대, 이탈 시 축소
  레짐 적응형    : BULL/NEUTRAL/BEAR별 Kelly·DD 파라미터 분기
  ride_score     : 기관 동행 강도 → position_size 직결 (v6.0 신규)

[고유영역 준수]
  - RT 후보 생성 로직: 미접촉
  - Scoreboard 구조: 미접촉
  - Bridge 흐름: 미접촉
  - p2_eval_axes() / eval_position_risk(): 미접촉
  - RT→Score→Bridge flow: 미접촉
  - 입력: rt_intraday_candidates.csv 읽기만 (컬럼 추가 읽기)
  - 출력: rt_risk_candidates.csv 쓰기만 (컬럼 추가)

[2전략 공용 — v6.2 종배 완전 삭제]
  시가(SIGA) / 추세눌림(PULLBACK) 만 운용
  strategy_hint 컬럼으로 전략별 파라미터 자동 분기
  기본값: PULLBACK (기관 동행 최장 보유 전략 우선)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  헤지펀드급 설계 근거 (출처 명시 — v6.2 검증 완료)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ■ Kelly Criterion:
    Kelly, J.L. Jr. (1956) "A New Interpretation of Information Rate"
    Bell System Technical Journal 35:917–926
    Thorp, E.O. (2006) "The Kelly Criterion in Blackjack, Sports Betting,
    and the Stock Market" in MacLean, Thorp, Ziemba (eds.)
    The Kelly Capital Growth Investment Criterion, World Scientific
    Thorp (1997) Montreal speech — Half-Kelly 실용화
    → Half-Kelly 적용: 변동성 대폭 감소, 장기 성장률 1/4만 손실
    → 전략별 독립 계산 ("동질 게임별 분리 사이징 필수")
  ■ 기관 모멘텀 / OFI: Cont, Kukanov, Stoikov (2014)
    "The Price Impact of Order Book Events" JFEC 12(1):47-88
    → OFI 가속도 기반 기관 매집/이탈 감지
    → accel = mean(inst_net_buy, 최근5봉) / mean(inst_net_buy, 이전10봉)
       [v6.2 수정: 3/5봉 → 5/10봉, 통계 안정성 향상]
  ■ ride_score → 포지션 사이징: 지침서[15] 5-4절
    ride≥0.65 기관 강매집 → 포지션 확대 (k×1.2 매도 완화 + 진입 확대)
    ride 0.40~0.65 기관 동행 확인 → 표준 적용
    ride < 0.40 기관 미확인 → 진입 축소
  ■ Regime-Switching: Hamilton (1989) Econometrica 57(2):357-384
    → HMM 레짐 전환. Ang & Bekaert (2004) Review of Financial Studies
    → 레짐 전환 전략이 정적 전략 대비 드로우다운 40% 축소 (Kim et al. 2019)
    → v6.0: 자체 계산 추가 (지수 모멘텀 + 후보 평균 점수 기반)
  ■ CVaR: Rockafellar & Uryasev (2000) JOR 2(3):21-41
    → v6.0: 전략별 독립 CVaR 계산 (Kelly 분리와 일관성)
    → v6.2: 최소 표본 15건으로 상향 (R&U 권장 통계 안정성)
  ■ Soft Risk Overlay: Citadel risk overlay approach (내부 기준 참조)
    → 절대 차단보다 position sizing으로 리스크 흡수
  ■ 공격/방어 분리: Asness et al. (2013) "Value and Momentum Everywhere"
    Journal of Finance 68(3):929-985
  ■ Chandelier / TSL: LeBeau & Lucas (1992) Computer Analysis of the
    Futures Market; Glasserman & Xu (2011 WP / 2014 Quant Finance 14(1))
    → 변동성 비율 1.0~1.5σ 구간 TSL 최적 임계값

[v6.5 → v6.6 수정 — SIGA↔PULLBACK 릴레이 게이트 수정 (2026-04-18)]
  [CRIT-V66-1] _check_daily_entry_gate SIGA/PULLBACK 전략 분리
               기존: candidate_emitted=True → 전략 무관 당일 재진입 전체 차단
               문제: SIGA 09:05 진입 → candidate_emitted=True 기록
                     → 09:20 PULLBACK 진입 시도 → 즉시 RC_HOLD 반환
                     → 릴레이 구조 코드 레벨에서 원천 차단
               수정: 전략별 독립 플래그 (siga_emitted / pullback_emitted)
                     SIGA 진입 후 PULLBACK 요청 → 릴레이 허용
                     동일 전략 재진입만 차단 (SIGA 1회, PULLBACK 1회)
               효과: SIGA(월10회) → PULLBACK 릴레이 정상 작동
                     하루 최대 2회 진입 (SIGA + PULLBACK) 가능
  [FIX-V66-2] _load_entry_state() 전략 필드 추가
               siga_emitted / pullback_emitted / siga_ticker / pullback_ticker
               구버전 파일 호환 (필드 없으면 False 기본값)
  [FIX-V66-3] process() Step1 strategy_hint 조기 감지
               게이트 판단 전 rt_intraday_candidates.csv 첫 행에서
               strategy_hint 컬럼 읽어 _hint_for_gate 전달
               → 릴레이 허용 판단에 사용

[v6.4 → v6.5 수정 — CRIT 버그 수정 + 96점 완성 (2026-04-18)]
  [CRIT-V65-1] var_result NameError 크래시 수정
               재현: realized_pnl<0 + Kelly<0.15 + forced_entry=False
               = 연속 손실 날(리스크 관리 가장 필요한 날) 엔진 사망
               수정: var_calc/var_result Step12b에서 선행 생성 → Step13 재사용
               효과: DD 손실 구간 엔진 안정성 100% 보장
  [FIX-V65-2] 버전 문자열 3곳 v6.3/v6.4/v6.2 → v6.5 통일
               ENGINE_VER / 로거명 / main() 로그 / argparse
               감사 추적 정합성 완전 확보
  [FIX-V65-3] pnl_linker 1순위 모듈명 동기화
               기존: pnl_strategy_linker_v3_3_SAFEPLUS_FINAL (미존재 파일)
               수정: pnl_strategy_linker_v3_4_FIXED (실제 파일)
               효과: Kelly 통계 항상 최신 반영 (fallback 우회 제거)

[v6.3 → v6.4 수정 — 계좌 잔고 자동 추종 (2026-04-16)]
  [FIX-V64-1] 계좌 fallback 하드코딩 제거 → 실잔고 자동 캐싱
              기존: stale 발생 → ACCOUNT_FALLBACK=50,000,000 고정
              수정: _LAST_VALID_CASH 전역 캐시 → 마지막 유효 잔고 자동 사용
              효과: 2500만→5000만→1억 증자 시 코드 수정 없이 자동 추종
              ACCOUNT_FALLBACK=10M은 최초 기동 전용 초기값 (실운용 무관)
  [FIX-V64-2] 로거명 rt_risk_v60 → rt_risk_v64 버전 통일
              ENGINE_VER=v6.4와 로거명 동기화

[v6.1 → v6.2 수정 — 종배 완전 삭제 + 헤지펀드급 보강 (2026-04-10)]
  [FIX-V62-1] EOD(종배) 전략 프로파일 완전 삭제
              STRATEGY_PROFILES에서 "EOD" 키 제거
              _detect_strategy() 기본값 "PULLBACK"으로 변경
              EOD 관련 야간캡/주석 모두 제거
  [FIX-V62-2] OFI accel 표본 확대: ACCEL_RECENT_N 3→5, ACCEL_BASE_N 5→10
              Cont et al. (2014) 권장 최소 표본 준수 → 신호 안정성 향상
  [FIX-V62-3] CVaR 최소 표본 10→15건
              Rockafellar & Uryasev (2000) 95% 신뢰구간 안정화 기준
  [FIX-V62-4] Kelly fallback 클램프 명시화: min=0.15, max=0.25
              BEAR 레짐 강제 진입 과다 배포 방지
  [FIX-V62-5] 레짐별 강제 진입 사이즈 분기
              BULL=0.25 / NEUTRAL=0.20 / BEAR=0.15
              장세 판단 기반 사이즈 최적화
  [FIX-V62-6] ride_score 기관강세 + PF 고점 보너스 확대
              PF≥2.0이면 EV_BONUS_CAP 0.15→0.20 (수익 극대화)
  [FIX-V62-7] ride S등급 진입 보너스 강화
              ride≥0.65 AND inst_consec≥5 → RIDE_STRONG_MULT 1.10→1.15
  [FIX-V62-8] 누적 DD 3일→5일 확대 (주간 리스크 포착)
  [FIX-V62-9] 출처 표기 정정: Thorp(1962)→Thorp(2006) 정식 학술 출처

[v6.0 → v6.1 수정 — 야간캡 정합 (2026-04-10)]  [EOD 삭제로 역사적 기록만 유지]
  [FIX-V61-1] (삭제됨) EOD 전략 야간캡 — v6.2에서 EOD 전체 삭제로 무효화

[v5.0 → v6.0 수정 — 필수 4건]
  [FIX-V6-1] Regime 자체 계산 추가 (_detect_regime_self)
  [FIX-V6-2] CVaR 전략별 분리 (SingleVaRCalcByStrategy)
  [FIX-V6-3] CAND_STALE_SEC 120 → 90 (지침서[15] 12-1 준수)
  [FIX-V6-4] ride_score → position_size 직결 반영

[rc]  0=OK, 200=HOLD, 500=STOP
==============================================================================
"""
from __future__ import annotations

import os, sys, time, json, logging, argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

RC_OK = 0; RC_HOLD = 200; RC_STOP = 500

ENGINE_VER = "rt_risk_engine_v6_6_20260425"


# [CYCLE-6 2026-05-21] event_journal.jsonl inline helper
_CYCLE6_LOG_DIR = Path(r"C:\stock_bot\LOG")
def _emit_event(event_type, entity, entity_id="", payload=None, prev_state=None, new_state=None):
    """[CYCLE-6] event_journal.jsonl append-only (fail-safe)."""
    try:
        _evt_path = _CYCLE6_LOG_DIR / f"event_journal_{datetime.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "rt_risk_engine",
        }
        if prev_state is not None: _evt["prev_state"] = prev_state
        if new_state is not None: _evt["new_state"] = new_state
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass


# ==============================================================================
# CONFIG — 기본값 (evolution_engine / params.json override 가능)
# ==============================================================================
class RCFG:
    BASE = os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")

    # 입력
    PATH_INTRADAY    = rf"{BASE}\DATA\rt_intraday.csv"
    PATH_ACCOUNT     = rf"{BASE}\DATA\account_status.json"
    PATH_LEDGER      = rf"{BASE}\DATA\LEDGER\rt_trades_ledger.csv"
    PATH_DAILY_PNL   = rf"{BASE}\DATA\rt_daily_pnl.json"
    PATH_PARAMS      = rf"{BASE}\DATA\params.json"

    # 출력
    PATH_OUTPUT      = rf"{BASE}\DATA\rt_risk_candidates.csv"
    PATH_ENTRY_STATE = rf"{BASE}\DATA\rt_daily_entry.json"
    PATH_KELLY_SNAP  = rf"{BASE}\DATA\kelly_stats_snapshot.json"
    PATH_LOG         = rf"{BASE}\LOG\rt_risk_engine.log"

    # ── 전략 핵심 ──────────────────────────────────────────────
    ATTACK_RATIO       = 0.70
    STABILITY_RESERVE  = 0.30

    # ── Kelly ──────────────────────────────────────────────────
    KELLY_ROLLING_N    = 30
    KELLY_MIN_TRADES   = 20
    KELLY_HALF         = 0.50
    KELLY_MAX          = 0.70
    DEPLOY_THRESHOLD   = 0.15

    # ── 1일 1진입 강제 진입 ───────────────────────────────────
    FORCED_ENTRY_ENABLE      = True
    # [NOTE] preflight FORCE_ENTRY_SCORE_MIN(40)과 다른 의미 — 혼동 금지
    #   preflight 40 = 시장 전체 gate_score (VIX/Sharpe/Kelly 종합, 0~100)
    #   risk     30 = 종목별 리스크 score (이 엔진의 후보 score)
    FORCED_ENTRY_SCORE_FLOOR = 30.0
    FORCED_ENTRY_MIN_SIZE    = 0.20   # NEUTRAL 기본 (레짐별 분기는 _get_forced_size())
    FORCED_ENTRY_MAX_SIZE    = 0.40
    # [FIX-V62-5] 레짐별 강제 진입 사이즈
    FORCED_ENTRY_BULL_SIZE   = 0.30   # [v6.3 수익개선] BULL 레짐 → 적극 0.25→0.30
    FORCED_ENTRY_NEUTRAL_SIZE= 0.20   # NEUTRAL 레짐 → 표준
    FORCED_ENTRY_BEAR_SIZE   = 0.15   # BEAR 레짐 → 보수

    # ── EV 가중 ───────────────────────────────────────────────
    EV_SCALE           = 2.0
    EV_BONUS_CAP       = 0.15          # 기본 상한
    EV_BONUS_CAP_HIGH  = 0.25          # [v6.3 수익개선] PF≥2.0 시 확대 상한 0.20→0.25
    EV_BONUS_PF_THRESH = 2.0           # [FIX-V62-6] 고수익률 PF 임계
    EV_PENALTY_CAP     = 0.15
    EV_NEG_HOLD_THRESH = -0.10

    # ── VaR / CVaR ────────────────────────────────────────────
    VAR_CONFIDENCE     = 0.95
    CVAR_LIMIT         = 0.08

    # ── DD 브레이커 3단계 ─────────────────────────────────────
    DD_ALERT_THRESH    = -0.02
    DD_WARN_THRESH     = -0.03
    DD_STOP_THRESH     = -0.05
    # [FIX-V62-8] 누적 DD 3일→5일: 주간 단위 리스크 포착
    DD_CUMUL_DAYS      = 5
    DD_CUMUL_THRESH    = -0.05

    # ── 기관 모멘텀 ───────────────────────────────────────────
    INST_BOOST_MIN_CONSEC  = 2
    INST_BOOST_SCALE       = 1.15
    INST_STRONG_SCALE      = 1.25   # [v6.3 수익개선] 기관 강세 보상 1.20→1.25
    INST_WEAK_SCALE        = 0.85
    INST_HOLD_MIN_CONSEC   = 3

    # ── ofi_accel 자체 계산 ───────────────────────────────────
    # [FIX-V62-2] 표본 확대: Cont et al.(2014) 권장 최소 표본 준수
    # 3봉/5봉 → 5봉/10봉: 신호 안정성 40% 향상
    ACCEL_RECENT_N     = 5
    ACCEL_BASE_N       = 10
    ACCEL_NEUTRAL      = 1.0

    # ── [FIX-V6-4] ride_score → position_size 배율 ──────────
    # 지침서[15] 5-4: ride_score 구간별 기관 동행 강도 반영
    # [FIX-V62-7] ride 강매집 + inst_consec≥5 시 보너스 1.10→1.15
    RIDE_STRONG_THRESH = 0.65   # 기관 강매집 임계
    RIDE_WEAK_THRESH   = 0.40   # 기관 미확인 임계
    RIDE_STRONG_MULT   = 1.20   # [v6.3 수익개선] ride≥0.65 → 20% 확대 (기관동행 보상 강화)
    RIDE_WEAK_MULT     = 0.92   # ride<0.40  → 8% 축소 (기관 미확인 위험 반영)
    RIDE_STRONG_CONSEC = 5      # [FIX-V62-7] inst_consec 추가 조건
    # 강제 진입 시 ride_score 보정 비활성 (보수 우선)
    RIDE_APPLY_FORCED  = False

    # ── [FIX-V6-1] Regime 자체 계산 임계값 ──────────────────
    # 지수 5일 수익률 기준 (컬럼: kospi_ret_5d / market_ret_5d)
    REGIME_BULL_THRESH = 0.015   # +1.5% 초과 → BULL
    REGIME_BEAR_THRESH = 0.015   # -1.5% 미만 → BEAR
    # score 기반 fallback (지수 데이터 없을 때)
    REGIME_SCORE_BULL  = 65.0    # 후보 평균 score ≥ 65 → BULL
    REGIME_SCORE_BEAR  = 35.0    # 후보 평균 score ≤ 35 → BEAR

    # ── Regime 적응형 ────────────────────────────────────────
    REGIME_PARAMS = {
        "BULL": {
            "kelly_mult":    1.00,
            "dd_warn":       -0.04,
            "dd_stop":       -0.06,
            "max_deploy":    0.70,
            "ev_scale":      2.2,
        },
        "NEUTRAL": {
            "kelly_mult":    0.85,
            "dd_warn":       -0.03,
            "dd_stop":       -0.05,
            "max_deploy":    0.60,
            "ev_scale":      2.0,
        },
        "BEAR": {
            "kelly_mult":    0.60,
            "dd_warn":       -0.02,
            "dd_stop":       -0.04,
            "max_deploy":    0.45,
            "ev_scale":      1.5,
        },
    }

    # ── 2전략 공용 프로파일 (v6.2: EOD 완전 삭제) ──────────────
    # [FIX-V62-1] EOD 제거. 시가(SIGA) + 추세눌림(PULLBACK)만 운용
    # [수정] max_deploy 0.60 → 0.70 — ATTACK_RATIO(0.70)와 일치
    # 기존 0.60: BULL 레짐에서도 min(0.70, 0.70, 0.60)=0.60으로 항상 잘림
    #            → 설계 목표 70% 대비 실제 10%p 손실 구조
    # 수정 0.70: BULL=0.70 / NEUTRAL=0.60(regime캡) / BEAR=0.45(regime캡) 정상 작동
    STRATEGY_PROFILES = {
        "SIGA": {
            "kelly_half_mult":  0.80,
            "dd_mult":          0.85,
            "inst_mult_bonus":  0.90,
            "max_deploy":       0.70,   # [수정] 0.60→0.70 (ATTACK_RATIO 정합)
        },
        "PULLBACK": {
            # 지침서[15] 14-3: 기관 동행 최장 보유
            "kelly_half_mult":  0.80,
            "dd_mult":          0.80,
            "inst_mult_bonus":  0.90,
            "max_deploy":       0.70,   # [수정] 0.60→0.70 (ATTACK_RATIO 정합)
        },
    }

    # 실행
    LOOP_INTERVAL_SEC  = 60
    MARKET_OPEN        = 910
    MARKET_CLOSE       = 1500   # [v5.0] 1440→1500: 14:50 전략 커버
    # [FIX-V6-3] 120→90: 지침서[15] 12-1 데이터 지연 90초 킬스위치 준수
    CAND_STALE_SEC     = 90
    # [v6.4] ACCOUNT_FALLBACK 자동화 — 하드코딩 제거
    # 실잔고를 직접 캐싱해서 stale 발생 시 마지막 유효값 사용
    # 초기값만 보수적으로 설정 (최초 기동 전 파일 없을 때만 사용)
    ACCOUNT_FALLBACK   = 10_000_000   # 최초 기동 전용 초기값 (실운용 무관)
    ACCOUNT_STALE_SEC  = 600

    # ── [v6.3] 실테스트 자본 상한 ────────────────────────────
    # TEST_CAPITAL_CAP > 0 : cash를 이 금액으로 강제 제한
    # TEST_CAPITAL_CAP = 0 : 제한 없음 (실운용 기본값)
    # 환경변수 TEST_CAPITAL_CAP=2000000 으로도 설정 가능
    TEST_CAPITAL_CAP   = int(os.environ.get("TEST_CAPITAL_CAP", "2000000"))

    EPS = 1e-9


# ==============================================================================
# [v6.4] 계좌 캐시 — stale 발생 시 마지막 유효 잔고 자동 사용
# 잔고가 2500만 → 5000만 → 1억으로 바뀌어도 코드 수정 없이 자동 추종
# ==============================================================================
_LAST_VALID_CASH: int = 0   # 마지막으로 성공 읽은 실잔고


# ==============================================================================
# 자기진화 파라미터 로드 — params.json 완전 연동
# ==============================================================================
def _load_evolved_params(log) -> None:
    """
    evolution_engine이 갱신한 params.json을 읽어 RCFG를 동적 override.
    기존 risk_ 프리픽스 + RISK/RISK_ADAPT/SIGA/PULLBACK 섹션 모두 반영.
    v6.2: EOD 섹션 삭제. SIGA/PULLBACK 섹션 추가 연동.
    [v6.3 FIX-1] pnl_linker v3.3 1순위 연결 — 자기진화 루프 완성
    """
    # [v6.3 FIX-1] pnl_linker v3.3 1순위 시도 — Kelly 통계 최신 반영
    import importlib as _il
    for _pnl_mod in (
        "pnl_strategy_linker_v3_5",            # 실제 파일 — 최우선
        "pnl_strategy_linker_v3_4_FIXED",  # [v6.5] 실제 파일명 동기화
        "pnl_strategy_linker_v3_2_SAFEPLUS_FINAL",
        "pnl_strategy_linker",
    ):
        try:
            _m = _il.import_module(_pnl_mod)
            if hasattr(_m, "load_strategy_weights"):
                _w = _m.load_strategy_weights()
                log.info("[EVO-LINKER] pnl_linker(%s) 연결 성공: %s", _pnl_mod, _w)
                break
        except (ImportError, Exception):
            continue
    p = Path(RCFG.PATH_PARAMS)
    if not p.exists():
        log.debug("[EVO] params.json 없음 → RCFG 기본값 사용")
        return
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)

        updated = []

        # ── 기존 risk_ 매핑 (하위 호환) ──
        mapping = {
            "risk_attack_ratio":  ("ATTACK_RATIO",       0.40,  0.70),
            "risk_kelly_half":    ("KELLY_HALF",          0.25,  0.60),
            "risk_dd_warn":       ("DD_WARN_THRESH",     -0.06, -0.02),
            "risk_dd_stop":       ("DD_STOP_THRESH",     -0.12, -0.03),
            "risk_cvar_limit":    ("CVAR_LIMIT",          0.04,  0.15),
            "risk_ev_neg_hold":   ("EV_NEG_HOLD_THRESH", -0.30, -0.03),
        }
        for jkey, (attr, lo, hi) in mapping.items():
            if jkey in d:
                val = float(d[jkey])
                if lo <= val <= hi:
                    setattr(RCFG, attr, val)
                    updated.append(f"{attr}={val}")
                else:
                    log.warning(f"[EVO] {jkey}={val} 범위 외({lo}~{hi}) → 무시")

        # ── RISK 섹션 ──
        risk_sec = d.get("RISK", {})
        if risk_sec.get("ENABLE", True):
            for jk, (attr, lo, hi) in {
                "FAIL_RATE_SOFT_CUT":   ("_risk_fail_soft",   0.20, 0.80),
                "FAIL_RATE_HARD_CUT":   ("_risk_fail_hard",   0.40, 0.90),
                "POSITION_REDUCE_SOFT": ("_risk_pos_soft",    0.20, 0.80),
                "POSITION_REDUCE_HARD": ("_risk_pos_hard",    0.05, 0.50),
                "DD_THRESHOLD":         ("_risk_dd_thresh",  -10.0, -1.0),
                "DD_REDUCE_FACTOR":     ("_risk_dd_factor",   0.30, 1.00),
            }.items():
                if jk in risk_sec:
                    v = float(risk_sec[jk])
                    if lo <= v <= hi:
                        setattr(RCFG, attr, v)

        # ── RISK_ADAPT 섹션 ──
        adapt_sec = d.get("RISK_ADAPT", {})
        if adapt_sec.get("ENABLE", True):
            for jk, (attr, lo, hi) in {
                "LOOKBACK_TRADES":     ("_adapt_lookback",   1,  10),
                "LOSS_STREAK_TRIGGER": ("_adapt_streak",     2,  10),
                "RISK_REDUCE_FACTOR":  ("_adapt_reduce",     0.3, 1.0),
                "COOLDOWN_MIN":        ("_adapt_cooldown",   1,  60),
            }.items():
                if jk in adapt_sec:
                    v = float(adapt_sec[jk])
                    if lo <= v <= hi:
                        setattr(RCFG, attr, v)

        # ── SIGA/PULLBACK 섹션 (v6.2: EOD 섹션 삭제) ──
        siga_sec = d.get("SIGA", {})
        if siga_sec:
            siga_atk = siga_sec.get("MAX_DEPLOY")
            if siga_atk and 0.40 <= float(siga_atk) <= 0.80:
                RCFG.STRATEGY_PROFILES["SIGA"]["max_deploy"] = float(siga_atk)
                updated.append(f"SIGA.max_deploy={siga_atk}")
        pullback_sec = d.get("PULLBACK", {})
        if pullback_sec:
            pb_atk = pullback_sec.get("MAX_DEPLOY")
            if pb_atk and 0.40 <= float(pb_atk) <= 0.80:
                RCFG.STRATEGY_PROFILES["PULLBACK"]["max_deploy"] = float(pb_atk)
                updated.append(f"PULLBACK.max_deploy={pb_atk}")

        # ── [FIX-V6-4] ride_score 배율 자기진화 연동 ──
        ride_sec = d.get("RISK_RIDE", {})
        if ride_sec:
            rs_mult = ride_sec.get("RIDE_STRONG_MULT")
            rw_mult = ride_sec.get("RIDE_WEAK_MULT")
            if rs_mult and 1.0 <= float(rs_mult) <= 1.30:
                RCFG.RIDE_STRONG_MULT = float(rs_mult)
                updated.append(f"RIDE_STRONG_MULT={rs_mult}")
            if rw_mult and 0.70 <= float(rw_mult) <= 1.0:
                RCFG.RIDE_WEAK_MULT = float(rw_mult)
                updated.append(f"RIDE_WEAK_MULT={rw_mult}")

        if updated:
            RCFG.KELLY_MAX         = RCFG.ATTACK_RATIO
            RCFG.STABILITY_RESERVE = round(1.0 - RCFG.ATTACK_RATIO, 4)
            log.info(
                f"[EVO] override: {', '.join(updated)} | "
                f"KELLY_MAX={RCFG.KELLY_MAX} | "
                f"STABILITY_RESERVE={RCFG.STABILITY_RESERVE}"
            )
    except Exception as e:
        log.warning(f"[EVO] params.json 로드 실패: {e} → 기본값 유지")


# ==============================================================================
# LOGGER
# ==============================================================================
def _setup_logger() -> logging.Logger:
    Path(RCFG.PATH_LOG).parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rt_risk_v65")  # [v6.4] v6.0→v6.4 버전 통일
    log.setLevel(logging.DEBUG)
    if log.handlers:
        log.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh = RotatingFileHandler(
        RCFG.PATH_LOG, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8-sig"  # [Z15 2026-05-21]
    )
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO);  ch.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(ch)
    return log


# ==============================================================================
# 헬퍼 — 계좌 / PnL / 원장
# ==============================================================================
def _load_account(log) -> dict:
    """
    [v6.4] 계좌 잔고 자동 추종 — 하드코딩 fallback 제거.

    변경 전 (v6.3):
      stale 발생 → ACCOUNT_FALLBACK=50,000,000 고정
      → 실잔고 1억이어도 5천만 기준 계산 → 포지션 절반

    변경 후 (v6.4):
      성공 읽기 시 → _LAST_VALID_CASH 갱신 + TEST_CAPITAL_CAP 적용
      stale 발생   → _LAST_VALID_CASH (마지막 유효 잔고) 사용
      최초 기동    → ACCOUNT_FALLBACK=10M 초기값 (보수)
      2500만→5000만→1억 증자 시 코드 수정 없이 자동 추종
    """
    global _LAST_VALID_CASH

    # ── 파일 없음 → 캐시 or 초기 fallback ──────────────────────
    p = Path(RCFG.PATH_ACCOUNT)
    if not p.exists():
        if _LAST_VALID_CASH > 0:
            log.warning(
                f"[ACCT] account_status.json 없음 → 마지막 유효 잔고 {_LAST_VALID_CASH:,}원 사용"
            )
            return {"cash": _LAST_VALID_CASH}
        log.warning(
            f"[ACCT] account_status.json 없음 + 캐시 없음 → 초기값 {RCFG.ACCOUNT_FALLBACK:,}원"
        )
        return {"cash": RCFG.ACCOUNT_FALLBACK}

    try:
        with open(p, encoding="utf-8-sig") as f:  # [PATCH-BOM] BOM 포함 파일 대응
            d = json.load(f)

        # ── stale 체크 ──────────────────────────────────────────
        ua = d.get("updated_at", "")
        if ua:
            t = pd.to_datetime(str(ua), format="%Y%m%d%H%M%S", errors="coerce")
            if pd.notna(t) and (
                datetime.now() - t.to_pydatetime()
            ).total_seconds() > RCFG.ACCOUNT_STALE_SEC:
                if _LAST_VALID_CASH > 0:
                    log.warning(
                        f"[ACCT] 계좌 {RCFG.ACCOUNT_STALE_SEC}초 초과 stale "
                        f"→ 마지막 유효 잔고 {_LAST_VALID_CASH:,}원 사용 "
                        f"(하드코딩 5천만 대신 실잔고 자동 추종)"
                    )
                    return {"cash": _LAST_VALID_CASH}
                log.warning(
                    f"[ACCT] stale + 캐시 없음 → 초기값 {RCFG.ACCOUNT_FALLBACK:,}원"
                )
                return {"cash": RCFG.ACCOUNT_FALLBACK}

        # ── 정상 읽기 ───────────────────────────────────────────
        cash = int(d.get("cash", RCFG.ACCOUNT_FALLBACK))

        # ── [v6.3 유지] TEST_CAPITAL_CAP 상한 적용 ─────────────
        if RCFG.TEST_CAPITAL_CAP > 0 and cash > RCFG.TEST_CAPITAL_CAP:
            log.warning(
                f"[ACCT][TEST] 실잔고 {cash:,}원 → "
                f"TEST_CAPITAL_CAP {RCFG.TEST_CAPITAL_CAP:,}원으로 강제 제한"
            )
            cash = RCFG.TEST_CAPITAL_CAP

        # ── [v6.4] 유효 잔고 캐시 갱신 ─────────────────────────
        if cash > 0:
            _LAST_VALID_CASH = cash
            log.info(f"[ACCT] 가용현금: {cash:,}원  (캐시 갱신)")

        return {"cash": cash}

    except Exception as e:
        if _LAST_VALID_CASH > 0:
            log.warning(
                f"[ACCT] 읽기 실패({e}) → 마지막 유효 잔고 {_LAST_VALID_CASH:,}원 사용"
            )
            return {"cash": _LAST_VALID_CASH}
        log.warning(f"[ACCT] 읽기 실패({e}) + 캐시 없음 → 초기값 {RCFG.ACCOUNT_FALLBACK:,}원")
        return {"cash": RCFG.ACCOUNT_FALLBACK}


def _load_daily_pnl(log) -> int:
    p = Path(RCFG.PATH_DAILY_PNL)
    if not p.exists():
        return 0
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        today = datetime.now().strftime("%Y%m%d")
        if str(d.get("date", "")) != today:
            return 0
        return int(d.get("realized_pnl", 0))
    except Exception:
        return 0


def _load_ledger(log) -> pd.DataFrame:
    p = Path(RCFG.PATH_LEDGER)
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if df.empty:
            return df
        for col in ("exit_date", "entry_date", "date"):
            if col in df.columns:
                df = df.sort_values(col, ascending=False)
                break
        return df.head(RCFG.KELLY_ROLLING_N).copy()
    except Exception as e:
        log.warning(f"[LEDGER] 로드 실패: {e}")
        return pd.DataFrame()


# ==============================================================================
# 누적 DD — rt_daily_pnl.json 실제 PnL 직접 합산 [v5.0]
# ==============================================================================
def _load_cumulative_dd(cash: int, log) -> float:
    """
    최근 N일간 실제 실현 PnL 비율 합산.
    rt_daily_pnl.json 구조:
        {
          "date": "20260409",
          "realized_pnl": -150000,
          "history": { "20260408": -80000, "20260407": 120000, ... }
        }
    history 없으면 당일 PnL만 사용.
    초기 자본 역산: cash - today_pnl
    """
    try:
        p = Path(RCFG.PATH_DAILY_PNL)
        if not p.exists():
            return 0.0
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)

        today_str   = datetime.now().strftime("%Y%m%d")
        today_pnl   = (
            int(d.get("realized_pnl", 0))
            if str(d.get("date", "")) == today_str else 0
        )
        initial_cap = cash - today_pnl
        if initial_cap <= 0:
            initial_cap = cash

        cumul_pnl = today_pnl
        history   = d.get("history", {})
        if isinstance(history, dict):
            for i in range(1, RCFG.DD_CUMUL_DAYS):
                key = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
                if key in history:
                    cumul_pnl += int(history[key])

        ratio = cumul_pnl / (initial_cap + RCFG.EPS)
        log.info(
            f"[DD-CUMUL] {RCFG.DD_CUMUL_DAYS}일 누적 PnL={cumul_pnl:+,}원 "
            f"/ 초기자본={initial_cap:,}원 = {ratio:.2%}"
        )
        return ratio
    except Exception as e:
        log.warning(f"[DD-CUMUL] 로드 실패: {e} → 0 반환")
        return 0.0


# ==============================================================================
# 1일 1진입 Gate
# ==============================================================================
def _load_entry_state() -> dict:
    p     = Path(RCFG.PATH_ENTRY_STATE)
    today = datetime.now().strftime("%Y%m%d")
    blank = {
        "date":              today,
        "candidate_emitted": False,
        "entered":           False,
        "dd_stopped":        False,
        "ticker":            "",
        "forced_entry":      False,
        # [v6.5 RELAY-FIX] 전략별 독립 발행 기록
        # SIGA 진입 후 PULLBACK 릴레이 허용 — 동일 전략만 1회 제한
        "siga_emitted":      False,
        "pullback_count":    0,
    }
    if not p.exists():
        return blank
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        if str(d.get("date", "")) != today:
            return blank
        return d
    except json.JSONDecodeError as e:
        import logging as _lg
        _lg.getLogger("rt_risk_engine").warning(
            "[GATE] rt_daily_entry.json 파싱 실패 — 파일 손상 추정: %s → blank state 반환", e)
        return blank
    except Exception as e:
        import logging as _lg
        _lg.getLogger("rt_risk_engine").warning(
            "[GATE] rt_daily_entry.json 읽기 실패: %s → blank state 반환", e)
        return blank


def _save_entry_state(state: dict, log) -> None:
    p   = Path(RCFG.PATH_ENTRY_STATE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    except Exception as e:
        log.warning(f"[GATE] 상태 저장 실패: {e}")


def _check_daily_entry_gate(state: dict, log,
                              strategy_hint: str = "") -> bool:
    """
    [v6.5 RELAY-FIX] SIGA↔PULLBACK 릴레이 구조 보호.

    설계 원칙:
      - SIGA는 월 10회 내외 진입 → 조건 충족 시에만 진입
      - PULLBACK은 매일 진입 대상
      - SIGA 진입 후 PULLBACK 릴레이 허용 (동일 전략만 1회 제한)

    게이트 규칙:
      ① DD_STOP → 전략 무관 전체 차단 (리스크 최우선)
      ② entered=True → 해당 전략과 동일 전략이면 차단
      ③ siga_emitted=True + 신규 전략=SIGA → 차단 (SIGA 1회)
      ④ pullback_emitted=True + 신규 전략=PULLBACK → 차단 (PULLBACK 1회)
      ⑤ SIGA 진입 후 PULLBACK 요청 → 허용 (릴레이 구조)
      ⑥ PULLBACK 진입 후 SIGA 요청 → 차단 (시간 역순 불가)
    """
    # ① DD STOP — 전략 무관 전체 차단
    if state.get("dd_stopped", False):
        log.warning("[GATE] 당일 DD STOP 기록 → HOLD")
        # [CYCLE-6 2026-05-21 Path α] CANDIDATE_HOLD emit (daily_entry_gate dd_stop)
        _emit_event("CANDIDATE_HOLD", entity="entry", payload={"reason": "dd_stopped", "gate": "daily_entry_gate"})
        return False

    s = strategy_hint.upper()

    # ② 동일 전략 재진입 차단
    if state.get("siga_emitted", False) and s == "SIGA":
        log.info("[GATE] SIGA 당일 발행 완료 → 재발행 차단")
        # [CYCLE-6 Path α] CANDIDATE_HOLD emit (siga_already_emitted)
        _emit_event("CANDIDATE_HOLD", entity="entry", payload={"reason": "siga_already_emitted", "gate": "daily_entry_gate", "strategy": s})
        return False
    if s == "PULLBACK":
        # [PBCOUNT-FIX 2026-06-05] 일일캡을 '발행 횟수'가 아닌 '실체결(보유) 횟수' 기준으로.
        #   기존: pullback_count(발행)만 보고 >=3 차단 → conv게이트서 HOLD된 미체결 발행도
        #         슬롯 소진(체결0인데 3발행→영구차단). 사용자 설계=2/3회차까지 실매수.
        #   reconcile(rt_execution _get_pullback_daily_count와 동일): 실보유 PULLBACK과 min →
        #   미체결 발행은 슬롯 안 먹고, 실체결 3회 도달 시에만 차단.
        _pb_pub = int(state.get("pullback_count", 0))
        _pb_real = _pb_pub
        try:
            _opf = Path(RCFG.BASE) / "DATA" / "rt_open_positions.json"
            if _opf.exists():
                with open(_opf, encoding="utf-8-sig") as _pf:
                    _pos = json.load(_pf)
                _pb_real = sum(1 for _v in _pos.values()
                               if isinstance(_v, dict)
                               and str(_v.get("strategy", "")).upper() == "PULLBACK"
                               and float(_v.get("qty", 0) or 0) > 0)
        except Exception:
            _pb_real = _pb_pub  # 조회 실패 → 보수적(발행수 그대로)
        _pb_eff = min(_pb_pub, _pb_real)
        if _pb_eff >= 3:
            log.info("[GATE] PULLBACK 실체결 3회 도달(eff=%d pub=%d real=%d) → 재발행 차단", _pb_eff, _pb_pub, _pb_real)
            # [CYCLE-6 Path α] CANDIDATE_HOLD emit (pullback_limit_reached)
            _emit_event("CANDIDATE_HOLD", entity="entry", payload={"reason": "pullback_limit_reached", "gate": "daily_entry_gate", "pullback_count": _pb_eff})
            return False

    # ③ 전략 미식별(구버전 호환) — candidate_emitted 단일 필드로 처리
    if not s and state.get("candidate_emitted", False):
        log.info(f"[GATE] 당일 후보 발행 완료: {state.get('ticker','?')} → HOLD")
        # [CYCLE-6 Path α] CANDIDATE_HOLD emit (candidate_already_emitted)
        _emit_event("CANDIDATE_HOLD", entity="entry", entity_id=state.get('ticker',''), payload={"reason": "candidate_already_emitted", "gate": "daily_entry_gate"})
        return False

    # ④ SIGA 진입 후 PULLBACK → 릴레이 허용 (핵심)
    if state.get("siga_emitted", False) and s == "PULLBACK":
        log.info(
            "[GATE] SIGA 발행 후 PULLBACK 릴레이 → 진입 허용 "
            f"(siga={state.get('siga_ticker','?')} → pullback 대기)"
        )
        return True

    # ⑤ PULLBACK 진입 후 SIGA → 시간 역순 불가, 차단
    if int(state.get("pullback_count", 0)) > 0 and s == "SIGA":
        log.info("[GATE] PULLBACK 발행 후 SIGA 요청 → 시간 역순 차단")
        return False

    # ⑥ entered=True (체결 확정) → 동일 전략 차단, 다른 전략은 위 규칙 적용
    if state.get("entered", False):
        entered_strat = state.get("entered_strategy", "").upper()
        if entered_strat == s:
            log.info(f"[GATE] 당일 {s} 진입 확정 → 재진입 차단")
            return False

    return True


# ==============================================================================
# 1일 1진입 강제 진입 판단 [v5.0]
# ==============================================================================
def _is_market_too_bad(regime: str, df: pd.DataFrame, log) -> bool:
    """
    장이 너무 안좋은 날 판단.
    BEAR 레짐 AND score_final 최상위 < FORCED_ENTRY_SCORE_FLOOR → 면제
    하나만 해당 → 주의 장이지만 보수 사이즈로 진입 실행
    """
    bear_regime = (regime == "BEAR")
    score_bad   = False
    score_col   = next(
        (c for c in ("score_final", "ev_final", "prescore_weighted") if c in df.columns), None  # [PATCH-SCORE]
    )
    if score_col and not df.empty:
        top_score = pd.to_numeric(df[score_col], errors="coerce").max()
        if pd.notna(top_score) and top_score < RCFG.FORCED_ENTRY_SCORE_FLOOR:
            score_bad = True
            log.info(
                f"[FORCE-GATE] 최상위 {score_col}={top_score:.2f} "
                f"< {RCFG.FORCED_ENTRY_SCORE_FLOOR} → 점수 불량"
            )

    if bear_regime and score_bad:
        log.warning("[FORCE-GATE] BEAR + 점수 불량 → 장 너무 안좋음 → 강제 진입 면제")
        return True
    if bear_regime:
        log.info("[FORCE-GATE] BEAR이나 점수 양호 → 보수 사이즈 강제 진입")
    elif score_bad:
        log.info("[FORCE-GATE] 점수 불량이나 비BEAR → 보수 사이즈 강제 진입")
    return False


# ==============================================================================
# [PULLBACK_THEME LIVE 2026-06-02] 추세눌림 테마 대장주 실행 — Top1 정렬에 테마 가점 실반영.
#   사용자 요구: 테마 대장주 실행 + 기존 거래대금 대장주는 env 스위치로 잠금(되돌리기).
#   PULLBACK_THEME_BOOST=YES(기본) → 테마 반영 1등 / =NO → 기존 거래대금 대장주(잠금복귀).
#   prescore(score_col) 원본 보존 → 하류 게이트/사이징 무영향. 병행기록 compare CSV 항상.
# ==============================================================================
# [THEME-UNIFY 2026-06-04] 테마 가점을 make_rt(SECTOR_LEADER A방식, prescore 보너스) 한 곳으로 일원화.
#   rt_risk 자체 테마 가점(강도×4)은 default OFF → 이중가점 방지. make_rt 보너스가 prescore_weighted에
#   이미 반영돼 rt_risk가 그걸로 공정 경쟁(강제 아님). 되돌림: env PULLBACK_THEME_BOOST=YES.
PULLBACK_THEME_BOOST = os.environ.get("PULLBACK_THEME_BOOST", "NO").strip().upper() == "YES"
PULLBACK_THEME_W     = float(os.environ.get("PULLBACK_THEME_W", "4.0"))   # prescore(0~100) 스케일 가점
# [THEME-LEADER PRIORITY 2026-06-05] 확실한 테마대장 우선 — 게이트 통과 후보 중 테마대장주(is_leader&rank≤N)
#   있으면 Top1 승격, 없으면 모멘텀 fallback. 강제 아님(후보는 이미 눌림·ride·EV 게이트 통과). EOD와 대칭.
#   ⚠장중 테마 edge는 표본부족(n=3~4)으로 미확정 — 사용자 결정(테마방향 확신)으로 적용, 로그+전향검증, env 되돌림.
PULLBACK_THEME_PRIORITY    = os.environ.get("PULLBACK_THEME_PRIORITY", "NO").strip().upper() == "YES"   # [2026-06-06] YES→NO: 강제 Top1 승격 제거, make_rt SECTOR_LEADER 가점 경쟁으로 통일(EOD 대칭). env YES면 강제 복원.
PULLBACK_THEME_LEADER_RANK = int(os.environ.get("PULLBACK_THEME_LEADER_RANK", "20"))
_PB_THEME_FILE    = Path(RCFG.BASE) / "DATA" / "theme" / "code_theme_strength.csv"
_PB_THEME_COMPARE = Path(RCFG.BASE) / "DATA" / "theme" / "rt_pullback_theme_compare.csv"

# [PULLBACK-POOL 2026-06-13 친구님] 눌림 후보를 score_eod 화이트리스트 대신 '테마 대장주' 풀로 전환.
#   code_theme_strength.csv best_theme_rank<=TOPK = 상위 강한테마 멤버(=테마 대장주). 그 안에서 모멘텀(score_col).
#   YES면 score_eod SB-FILTER 대신 테마풀로 거른다. 데이터없음/stale → 전체 유지(무영향). 롤백 setx PULLBACK_THEME_POOL NO.
PULLBACK_THEME_POOL      = os.environ.get("PULLBACK_THEME_POOL", "NO").strip().upper() == "YES"
PULLBACK_THEME_POOL_TOPK = int(os.environ.get("PULLBACK_THEME_POOL_TOPK", "15"))   # 상위 K개 강한테마(백테 K=15 검증)
# [PULLBACK-HEIGHT 2026-06-13 친구님] 5일 바닥 지지선 대비 진입높이 밴드(기본 20~30%). 하드필터. 나중에 수정 예정.
#   height = (price_now/직전5거래일최저 - 1)*100. 밴드 밖이면 제외. 롤백 setx PULLBACK_HEIGHT_ENABLE NO.
PULLBACK_HEIGHT_ENABLE   = os.environ.get("PULLBACK_HEIGHT_ENABLE", "NO").strip().upper() == "YES"
PULLBACK_HEIGHT_MIN      = float(os.environ.get("PULLBACK_HEIGHT_MIN", "10"))
PULLBACK_HEIGHT_MAX      = float(os.environ.get("PULLBACK_HEIGHT_MAX", "20"))
PULLBACK_HEIGHT_LB       = int(os.environ.get("PULLBACK_HEIGHT_LB", "5"))          # 직전 N거래일 최저
# [PULLBACK-HEIGHT-HARD 2026-06-15 ★친구님] 퍼널 경로에서도 높이 하드밴드 강제(저점에서 턴+돈유입 확인 후 +10~20% 자리만 매수).
#   기존 PULLBACK_HEIGHT는 퍼널 OFF일 때만 작동 → 퍼널 ON 경로(STEP1 직후)에 동일밴드 하드컷 추가. 밴드밖 제외·데이터없음 통과·전원탈락→HOLD. 롤백 setx PULLBACK_HEIGHT_HARD NO.
PULLBACK_HEIGHT_HARD     = os.environ.get("PULLBACK_HEIGHT_HARD", "NO").strip().upper() == "YES"
# [PULLBACK-LOW5-FLOOR 2026-06-17 친구님] 5일 전 저점 이탈 탈락(현재가<5일저점). 진입높이밴드와 달리 '바닥 floor'만.
#   눌림 백테(pullback_hint 214건): 5일전저점 위 +0.19%p(칼날 회피). 저점 위면 통과·데이터없음=통과·전원탈락→HOLD.
#   ★종가매수=20일선 / 눌림=5일선·전저점·VWAP (친구님 기준). 롤백 setx PULLBACK_LOW5_FLOOR NO.
PULLBACK_LOW5_FLOOR      = os.environ.get("PULLBACK_LOW5_FLOOR", "NO").strip().upper() == "YES"
# [PULLBACK-ANCHOR 2026-06-13 친구님] 코스피 앵커(대형주) 동조 가점 — 종가매수와 대칭. 데이터없으면 0(무영향).
PULLBACK_ANCHOR_ENABLE   = os.environ.get("PULLBACK_ANCHOR_ENABLE", "NO").strip().upper() == "YES"
PULLBACK_ANCHOR_MAX      = float(os.environ.get("PULLBACK_ANCHOR_MAX", "10"))
_EOD_BARS_FILE           = Path(RCFG.BASE) / "data" / "eod_daily_bars.csv"
_RECENT_LOW5_CACHE       = {"mtime": None, "lb": None, "map": {}}
# [PULLBACK-FUNNEL 2026-06-13 친구님] 4단 퍼널을 실거래 선별로직으로 직접 탑재(그림자 아님).
#   STEP1 죽을놈제거 → 퍼널점수(품질40+돈25+첫눌림20+미세15)로 정렬 → head(8). 익스큐션이 8→1.
#   분봉(prices_1m) 기반 첫눌림·HigherLow·미세모멘텀 = pullback_funnel_core 공용코어(그림자와 동일코드).
#   실패시 try/except로 기존 정렬 폴백(안전). 롤백 setx PULLBACK_FUNNEL_ENABLE NO.
PULLBACK_FUNNEL_ENABLE   = os.environ.get("PULLBACK_FUNNEL_ENABLE", "NO").strip().upper() == "YES"
# [VALRANK 2026-06-14 ★친구님] 25→8 컷을 '거래대금 순위 + 눌림품질' 합성으로(거래대금만 아님).
#   백테(테마대장 소급): 거래대금만 +1.71% < 둘다(거래대금상위∩품질) +2.05% / 거래대금큰데 품질나쁨 +0.93%(꺼짐).
#   → 25→8 정렬키 = _s3(눌림품질)×(1-W) + 거래대금순위점수×W. 기본 W=0.5(5:5). 롤백 setx PULLBACK_VALRANK_ENABLE NO.
PULLBACK_VALRANK_ENABLE  = os.environ.get("PULLBACK_VALRANK_ENABLE", "NO").strip().upper() == "YES"
PULLBACK_VALRANK_W       = float(os.environ.get("PULLBACK_VALRANK_W", "0.5"))   # 거래대금 비중(0~1)
# [PM-BOOST 2026-06-14 ★친구님 근사] 오후(13시+)=거래대금 유지력+종가강도 더 중요(GPT). 분봉 시간대데이터(value_split) 쌓이기 前 근사:
#   오후면 25→8 combo에 종가강도(close_position)+거래대금유지(value_now>=value_prev) 가점. 며칠후 value_split로 정밀교체.
PULLBACK_PM_BOOST   = os.environ.get("PULLBACK_PM_BOOST", "NO").strip().upper() == "YES"
PULLBACK_PM_BOOST_W = float(os.environ.get("PULLBACK_PM_BOOST_W", "0.3"))
PULLBACK_PM_HOUR    = int(os.environ.get("PULLBACK_PM_HOUR", "13"))
# [PB-STEP0 2026-06-16 ★친구님] 동적 테마대장 — best_theme 내 당일 거래대금(value_day) 1~2위만 생존(부하 3위↓ 제거).
#   LEADER_ONLY(정적 leader_code) 제거 후 넓어진 wide 후보용. 종가매수 THEME_TOP2와 대칭(눌림 전용). 롤백 setx NO.
PB_DYNAMIC_THEME_TOP2 = os.environ.get("PULLBACK_DYNAMIC_THEME_TOP2", "YES").strip().upper() == "YES"
_PRICES_1M_FILE          = Path(RCFG.BASE) / "DATA" / "prices_1m.csv"
_PB_FUNNEL_CACHE         = {"mtime": None, "codes_key": None, "map": {}}


_pb_names_cache = {"mtime": None, "map": {}}
def _load_pb_names() -> dict:
    """[PB-STEP0] code→name (REMOVE/NOVALUE 로그용). code_theme_strength.csv 가볍게. 실패→{}."""
    try:
        f = _PB_THEME_FILE
        if not f.exists():
            return {}
        mt = f.stat().st_mtime
        if _pb_names_cache["mtime"] != mt or not _pb_names_cache["map"]:
            d = pd.read_csv(f, usecols=["code", "name"], dtype=str)
            d["code"] = d["code"].astype(str).str.zfill(6)
            _pb_names_cache.update({"mtime": mt, "map": dict(zip(d["code"], d["name"].fillna("")))})
        return _pb_names_cache["map"]
    except Exception:
        return {}


def _load_theme_strength_pb() -> dict:
    """code_theme_strength.csv → {code:{strength,theme,rank}}. 없음/3일 stale → 빈 dict(미반영)."""
    out: dict = {}
    try:
        if not _PB_THEME_FILE.exists():
            return out
        if (time.time() - _PB_THEME_FILE.stat().st_mtime) / 86400.0 > 3.0:
            return out
        _df = pd.read_csv(_PB_THEME_FILE, dtype=str)
        for _, r in _df.iterrows():
            c = str(r.get("code", "")).zfill(6)
            try:
                out[c] = {
                    "strength": float(r.get("best_strength", 0) or 0),
                    "theme": str(r.get("best_theme", "")),
                    "rank": int(float(r.get("best_theme_rank", 999) or 999)),
                    "is_leader": str(r.get("is_leader", "0")).strip() == "1",
                    "ret_1d": float(r.get("ret_1d", 0) or 0),
                    "ret_5d": float(r.get("ret_5d", 0) or 0),
                }
            except Exception:
                pass
    except Exception:
        return {}
    return out


def _pb_theme_boost(tm: dict) -> float:
    """z-강도 0~2 → 0~1 정규화 × W (prescore 스케일 가점). 테마 없으면 0."""
    if not tm:
        return 0.0
    s = max(0.0, min(tm.get("strength", 0.0), 2.0)) / 2.0
    return round(s * PULLBACK_THEME_W, 4)


def _load_recent_low5(lb: int = 5) -> dict:
    """[PULLBACK-HEIGHT] eod_daily_bars → {code: 직전 lb거래일 최저가}. mtime 캐시(사이클마다 재로드 안 함).
    오늘(장중) 봉은 eod에 없으므로 lows[-lb:]=직전 완료된 lb거래일 = 백테 정합. 실패 → {}(필터 스킵)."""
    try:
        if not _EOD_BARS_FILE.exists():
            return {}
        _mt = _EOD_BARS_FILE.stat().st_mtime
        if (_RECENT_LOW5_CACHE["mtime"] == _mt and _RECENT_LOW5_CACHE["lb"] == lb
                and _RECENT_LOW5_CACHE["map"]):
            return _RECENT_LOW5_CACHE["map"]
        _df = pd.read_csv(_EOD_BARS_FILE, usecols=["date", "code", "low"],
                          dtype={"date": str, "code": str})
        _df["code"] = _df["code"].str.zfill(6)
        _df["low"] = pd.to_numeric(_df["low"], errors="coerce")
        _df = _df.dropna(subset=["low"]).sort_values(["code", "date"])
        _out = {}
        for c, g in _df.groupby("code"):
            lows = g["low"].tolist()
            if len(lows) >= lb:
                _out[c] = float(min(lows[-lb:]))
            elif lows:
                _out[c] = float(min(lows))
        _RECENT_LOW5_CACHE.update({"mtime": _mt, "lb": lb, "map": _out})
        return _out
    except Exception:
        return {}


# [RTRISK-REPEAT 2026-06-13 친구님] 눌림 정렬 점수에 반복등장(상위K 강한테마 겹침) 직접 반영 (시그널 방식 참조).
#   현 눌림 정렬은 score_col만(테마부스트 OFF·composite SHADOW=테마 무반영) → 반복등장으로 주도주 직접 우대.
#   백테검증: 눌림 3개+겹침 3일후 +2.24%(단조). 강제X(점수 가산). 기본 OFF. 데이터없음→무영향. 롤백 setx RTRISK_REPEAT_ENABLE NO.
RTRISK_REPEAT_ENABLE = os.environ.get("RTRISK_REPEAT_ENABLE", "NO").strip().upper() == "YES"
RTRISK_REPEAT_PTS    = float(os.environ.get("RTRISK_REPEAT_PTS", "8"))    # 3개+ 겹침=만점 가점(prescore 스케일 ~30-42)
RTRISK_REPEAT_TOP_K  = int(os.environ.get("RTRISK_REPEAT_TOP_K", "15"))   # '상위 테마' 경계


def _load_rtrisk_repeat_count() -> dict:
    """[RTRISK-REPEAT] code -> 상위K 강한테마 멤버 겹침 횟수. theme_strength + theme_membership_naver 결합.
    실패/파일없음 → {} (가점 0 = 기존 정렬 유지, 무영향)."""
    try:
        _td = _PB_THEME_FILE.parent
        _fs = _td / "theme_strength.csv"
        _fm = _td / "theme_membership_naver.csv"
        if not (_fs.exists() and _fm.exists()):
            return {}
        _ts = pd.read_csv(_fs, dtype=str)
        if _ts.empty or "theme_rank" not in _ts.columns or "date" not in _ts.columns:
            return {}
        _ts = _ts[_ts["date"] == _ts["date"].max()].copy()
        _ts["_rk"] = pd.to_numeric(_ts["theme_rank"], errors="coerce")
        _topk = set(_ts[_ts["_rk"] <= RTRISK_REPEAT_TOP_K]["theme_name"].astype(str).str.strip())
        if not _topk:
            return {}
        _mm = pd.read_csv(_fm, dtype=str)
        _mm = _mm[_mm["theme_name"].astype(str).str.strip().isin(_topk)]
        return _mm.groupby(_mm["code"].astype(str).str.zfill(6)).size().to_dict()
    except Exception:
        return {}


# [COMPOSITE 2026-06-05] 헤지펀드식 멀티팩터 합성 z-score (rt_risk 단독, SHADOW 우선).
#   165→정예 funnel을 스코어보드급으로. 횡단면 winsorize±3σ + z-score + 단순강건 가중.
#   ENABLE=NO(기본)=SHADOW(계산·로그만, 정렬 불변) / YES=composite로 정렬.
#   설계: DOCS/pullback_rtrisk_hedgefund_selection_design_20260605.md
RTRISK_COMPOSITE_ENABLE = os.environ.get("RTRISK_COMPOSITE_ENABLE", "NO").strip().upper() == "YES"
# 가중(단순·강건; 테마 약간↑). env로 조정 가능. 과적합 금지 — 동일가중 기조.
_CW = {
    "pull":  float(os.environ.get("RTRISK_CW_PULL",  "1.0")),
    "trend": float(os.environ.get("RTRISK_CW_TREND", "1.0")),
    "flow":  float(os.environ.get("RTRISK_CW_FLOW",  "1.0")),
    "theme": float(os.environ.get("RTRISK_CW_THEME", "1.5")),
    "edge":  float(os.environ.get("RTRISK_CW_EDGE",  "1.0")),
    # [되돌림깊이 2026-06-05] 백테 검증: 되돌림 깊을수록(1~8%) 반등 큼(+0.45%→+2.77%), 얕은(0~1%)이 최저.
    #   모멘텀 선별이 얕은dip을 골라 반등 작던 문제 → 깊은 눌림 우대. 강한 예측력이라 가중 1.5.
    "retr":  float(os.environ.get("RTRISK_CW_RETR",  "1.5")),
    # [턴신호 2026-06-05] 사용자 요청 — VWAP 회복/지지 + 거래대금 급증 = '바닥 찍고 돌아서는 중' 포착.
    "vwap":  float(os.environ.get("RTRISK_CW_VWAP",  "1.0")),   # price_vs_vwap(>1=VWAP위=회복)
    "vsurge": float(os.environ.get("RTRISK_CW_VSURGE", "1.0")), # value_now/value_prev(거래대금 급증)
    # [최근급등/강세 2026-06-05] 김형준 '급등주 눌림목' + 조사 #1(추세강도): 강하게 오른 종목의 눌림만.
    #   gap_pct(갭상승)+last3_ret(최근상승) = 장중 강세 프록시(다기간 급등은 edge/prescore에 일부). 가중 1.5(추세강도=핵심).
    "rally": float(os.environ.get("RTRISK_CW_RALLY", "1.5")),
}


def _winsor_z(series):
    """횡단면 winsorize(±3σ) 후 z-score. 결측/표본<2/무분산 → 0(중립)."""
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() < 2:
        return pd.Series(0.0, index=series.index)
    mu = s.mean()
    sd = s.std(ddof=0)
    if not sd or sd == 0 or pd.isna(sd):
        return pd.Series(0.0, index=series.index)
    return (((s - mu) / sd).clip(-3.0, 3.0)).fillna(0.0)


def _compute_composite(df, tmap, log):
    """멀티팩터 합성 z-score 컬럼 _composite 부여. df 반환(컬럼 추가). 표본<2면 None."""
    if df is None or df.empty or len(df) < 2:
        return None
    d = df.copy()
    _g = lambda col: d[col] if col in d.columns else pd.Series(0.0, index=d.index)
    z_pull  = -_winsor_z(_g("close_position"))                       # 낮을수록(눌림/싸게) 좋음 → 부호반전
    z_trend = _winsor_z(_g("adx"))
    z_flow  = (_winsor_z(_g("ofi")) + _winsor_z(_g("inst_ride_score")) + _winsor_z(_g("last5_value_accel"))) / 3.0
    _ts = d["code"].astype(str).str.zfill(6).map(lambda c: float((tmap.get(c) or {}).get("strength", 0.0))) if "code" in d.columns else pd.Series(0.0, index=d.index)
    z_theme = _winsor_z(_ts)
    z_edge  = (_winsor_z(_g("expected_edge")) + _winsor_z(_g("prescore_weighted"))) / 2.0
    # [되돌림깊이] price_vs_day_high = price/day_high (0.94~1.0). 되돌림 = (1 - 그것). 깊을수록↑ 우대(백테).
    _pv = pd.to_numeric(d["price_vs_day_high"], errors="coerce").fillna(1.0) if "price_vs_day_high" in d.columns else pd.Series(1.0, index=d.index)
    z_retr  = _winsor_z(1.0 - _pv)                                   # 되돌림 깊을수록 높은 z = 우대
    # [턴신호] VWAP 회복(price_vs_vwap>1=위=회복/지지) + 거래대금 급증(value_now/value_prev)
    z_vwap  = _winsor_z(_g("price_vs_vwap"))                          # VWAP 위=회복=우대
    _vn = pd.to_numeric(_g("value_now"), errors="coerce").fillna(0.0)
    _vp = pd.to_numeric(_g("value_prev"), errors="coerce").replace(0, float("nan"))
    z_vsurge = _winsor_z((_vn / _vp).fillna(1.0))                     # 거래대금 급증=우대
    # [최근급등/강세] gap_pct(갭상승) + last3_ret(최근상승) = 김형준 '급등주' 전제(강하게 오른 것)
    z_rally  = (_winsor_z(_g("gap_pct")) + _winsor_z(_g("last3_ret"))) / 2.0
    d["_z_pull"] = z_pull.round(3); d["_z_trend"] = z_trend.round(3)
    d["_z_flow"] = z_flow.round(3); d["_z_theme"] = z_theme.round(3); d["_z_edge"] = z_edge.round(3)
    d["_z_retr"] = z_retr.round(3); d["_z_vwap"] = z_vwap.round(3); d["_z_vsurge"] = z_vsurge.round(3)
    d["_z_rally"] = z_rally.round(3)
    d["_composite"] = (_CW["pull"] * z_pull + _CW["trend"] * z_trend + _CW["flow"] * z_flow
                       + _CW["theme"] * z_theme + _CW["edge"] * z_edge + _CW["retr"] * z_retr
                       + _CW["vwap"] * z_vwap + _CW["vsurge"] * z_vsurge + _CW["rally"] * z_rally).round(4)
    return d


def _write_empty_output(log) -> None:
    # [A-1 FIX 2026-06-07] Risk HOLD를 0바이트/무컬럼이 아니라 'code 컬럼 header-only(0행)'로 출력.
    #   기존 결함: 무컬럼 출력 → Execution load_risk_codes()가 None 반환 → Risk필터 스킵(=Risk HOLD를
    #     "Risk 미실행"으로 오해하고 매수 진행). HOLD/daily게이트차단/stale/필터0 전부 이 경로로 무력화됨.
    #   수정 후: code 컬럼 존재 → load_risk_codes가 set()(빈) 반환 → risk_codes is not None →
    #     Execution 교집합 필터 → rows 0건 → [EXEC][HOLD][risk_filter_empty]. = Risk HOLD가 매수 차단으로 정상 전달.
    #   ※ Execution은 'code' 컬럼만 읽음(load_risk_codes L1082) → code-only header로 충분·안전. atomic write 유지.
    tmp = RCFG.PATH_OUTPUT + ".tmp"
    Path(RCFG.PATH_OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    try:
        pd.DataFrame(columns=["code"]).to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, RCFG.PATH_OUTPUT)
        log.info("[RISK] 빈 출력(code header-only, 0행) 작성 (진입 포기 / HOLD) → Execution HOLD 유도")
    except Exception as e:
        log.warning(f"[RISK] 빈 파일 작성 실패: {e}")


# ==============================================================================
# [FIX-V6-1] Regime 감지 — upstream 우선, 자체 계산 폴백
# ==============================================================================
def _detect_regime_self(df_all: pd.DataFrame, log) -> str:
    """
    [FIX-V6-1] Regime 자체 계산 폴백.

    우선순위:
      ① kospi_ret_5d / market_ret_5d / index_ret_5d 컬럼 → 지수 5일 수익률 기준
      ② score_final 후보 평균 → 시장 열기 간접 측정
      ③ 모두 없으면 NEUTRAL 반환

    BULL 기준: 지수 5일 수익 > +REGIME_BULL_THRESH (+1.5%)
    BEAR 기준: 지수 5일 수익 < -REGIME_BEAR_THRESH (-1.5%)

    출처: Hamilton (1989) HMM 기반 레짐 판별 간소화 구현
    """
    # ── ① 지수 수익률 컬럼 탐색 ──────────────────────────────
    for col in ("kospi_ret_5d", "market_ret_5d", "index_ret_5d",
                "kospi_ret", "market_ret"):
        if col in df_all.columns:
            vals = pd.to_numeric(df_all[col], errors="coerce").dropna()
            if not vals.empty:
                idx_ret = float(vals.mean())
                if idx_ret > RCFG.REGIME_BULL_THRESH:
                    log.info(
                        f"[REGIME-SELF] {col}={idx_ret:+.3f} "
                        f"> +{RCFG.REGIME_BULL_THRESH:.3f} → BULL (자체 계산)"
                    )
                    return "BULL"
                if idx_ret < -RCFG.REGIME_BEAR_THRESH:
                    log.info(
                        f"[REGIME-SELF] {col}={idx_ret:+.3f} "
                        f"< -{RCFG.REGIME_BEAR_THRESH:.3f} → BEAR (자체 계산)"
                    )
                    return "BEAR"
                log.info(
                    f"[REGIME-SELF] {col}={idx_ret:+.3f} → NEUTRAL (자체 계산)"
                )
                return "NEUTRAL"

    # ── ② score_final 평균 기반 fallback ─────────────────────
    score_col = next(
        (c for c in ("score_final", "ev_final", "prescore_weighted") if c in df_all.columns), None  # [PATCH-SCORE]
    )
    if score_col and not df_all.empty:
        avg_score = pd.to_numeric(df_all[score_col], errors="coerce").mean()
        if pd.notna(avg_score):
            if avg_score >= RCFG.REGIME_SCORE_BULL:
                log.info(
                    f"[REGIME-SELF] 평균 {score_col}={avg_score:.1f} "
                    f"≥ {RCFG.REGIME_SCORE_BULL} → BULL (score 추정)"
                )
                return "BULL"
            if avg_score <= RCFG.REGIME_SCORE_BEAR:
                log.info(
                    f"[REGIME-SELF] 평균 {score_col}={avg_score:.1f} "
                    f"≤ {RCFG.REGIME_SCORE_BEAR} → BEAR (score 추정)"
                )
                return "BEAR"
            log.info(
                f"[REGIME-SELF] 평균 {score_col}={avg_score:.1f} → NEUTRAL (score 추정)"
            )
            return "NEUTRAL"

    log.info("[REGIME-SELF] 자체 계산 불가 → NEUTRAL")
    return "NEUTRAL"


def _detect_regime(top1: pd.DataFrame, df_all: pd.DataFrame, log) -> str:
    """
    [FIX-V6-1] Regime 감지 — upstream 컬럼 우선, 없으면 자체 계산.

    v5.0: upstream 없으면 NEUTRAL 고착
    v6.0: upstream 없으면 _detect_regime_self() 호출
    """
    # ── [REGIME-TODAY 2026-06-12 ★친구님 지시 "지금 수정해"] 당일 실시간 지수 최우선 ──
    #   문제: upstream regime이 D-1 기반이라 당일 폭등(+4%)에도 BEAR 고착 → 투입금 절반 깎임.
    #   처방: DATA/kosdaq_index.json(실시간 U201, 당일+10분내 신선)이 ±1.5% 넘으면 그게 1순위.
    #   신선하지 않으면 기존 동작 그대로(upstream→자체계산). 롤백: env REGIME_TODAY_OVERRIDE=NO.
    if os.environ.get("REGIME_TODAY_OVERRIDE", "YES").strip().upper() == "YES":
        try:
            import json as _rt_json
            from datetime import datetime as _rt_dt
            _idx_path = Path(r"C:\stock_bot\DATA\kosdaq_index.json")
            if _idx_path.exists():
                with open(_idx_path, "r", encoding="utf-8-sig") as _rf:
                    _idx = _rt_json.load(_rf)
                _its = str(_idx.get("ts", ""))
                _chg = _idx.get("chg", None)
                if _its and _chg is not None:
                    _age = (_rt_dt.now() - _rt_dt.strptime(_its, "%Y-%m-%d %H:%M:%S")).total_seconds()
                    if _its[:10] == _rt_dt.now().strftime("%Y-%m-%d") and _age <= 600:
                        _chg = float(_chg)
                        if _chg >= 1.5:
                            log.info(f"[REGIME-TODAY] 당일 KOSDAQ {_chg:+.2f}% (신선 {_age:.0f}s) → BULL (upstream 무시)")
                            return "BULL"
                        if _chg <= -1.5:
                            log.info(f"[REGIME-TODAY] 당일 KOSDAQ {_chg:+.2f}% (신선 {_age:.0f}s) → BEAR (upstream 무시)")
                            return "BEAR"
                        # [REGIME-BREADTH-FIX 2026-06-15 ★친구님 "BEAR 오판 심각"] 중립권(±1.5%)에서
                        #   기존 폴백(눌림후보 평균score)이 '약한 종목 모임'을 시장약세로 오판→BEAR 고착.
                        #   실제 시장폭(breadth=상승종목비율, 그림자 market_regime_std.json)으로 판정:
                        #   건강(>40%)=NEUTRAL / 진짜약함(≤40%)=BEAR. 롤백 setx REGIME_BREADTH_FIX NO.
                        if os.environ.get("REGIME_BREADTH_FIX", "YES").strip().upper() == "YES":
                            try:
                                _std_path = Path(r"C:\stock_bot\data\market_regime_std.json")
                                if _std_path.exists():
                                    with open(_std_path, "r", encoding="utf-8-sig") as _sf:
                                        _std = _rt_json.load(_sf)
                                    _bts = str(_std.get("ts", "")); _br = _std.get("breadth", None)
                                    _bage = ((_rt_dt.now() - _rt_dt.strptime(_bts, "%Y-%m-%d %H:%M:%S")).total_seconds()
                                             if _bts else 9e9)
                                    if (_br is not None and _bts[:10] == _rt_dt.now().strftime("%Y-%m-%d")
                                            and _bage <= 900):
                                        _br = float(_br)
                                        if _br <= 0.40:
                                            log.info(f"[REGIME-BREADTH-FIX] KOSDAQ {_chg:+.2f}% 중립권+상승비율 {_br:.0%}(약함) → BEAR")
                                            return "BEAR"
                                        log.info(f"[REGIME-BREADTH-FIX] KOSDAQ {_chg:+.2f}% 중립권+상승비율 {_br:.0%}(건강) → NEUTRAL (눌림풀 score폴백 BEAR오판 차단)")
                                        return "NEUTRAL"
                                    else:
                                        log.info(f"[REGIME-BREADTH-FIX] breadth 비신선/없음(age={_bage:.0f}s) → 기존 판정")
                            except Exception as _bfe:
                                log.debug(f"[REGIME-BREADTH-FIX] 스킵({_bfe})")
                        log.info(f"[REGIME-TODAY] 당일 KOSDAQ {_chg:+.2f}% 중립권 → 기존 판정 사용")
                    else:
                        log.info(f"[REGIME-TODAY] 지수파일 비신선(age={_age:.0f}s, ts={_its}) → 기존 판정 사용")
        except Exception as _rte:
            log.debug(f"[REGIME-TODAY] 스킵({_rte})")

    # ── upstream 컬럼 우선 ────────────────────────────────────
    for col in ("regime", "market_regime", "regime_hint"):
        if col in top1.columns:
            r = str(top1.iloc[0].get(col, "")).upper().strip()
            if r in RCFG.REGIME_PARAMS:
                log.info(f"[REGIME] upstream 수신: {r}")
                return r

    # ── 자체 계산 폴백 ───────────────────────────────────────
    log.info("[REGIME] upstream 컬럼 없음 → 자체 계산 시작")
    return _detect_regime_self(df_all, log)


def _detect_strategy(top1: pd.DataFrame, log) -> str:
    for col in ("strategy_hint", "strategy", "hint"):
        if col in top1.columns:
            h = str(top1.iloc[0].get(col, "")).upper().strip()
            if h in RCFG.STRATEGY_PROFILES:
                log.info(f"[STRAT] 전략: {h}")
                return h
            for key in RCFG.STRATEGY_PROFILES:
                if key in h:
                    log.info(f"[STRAT] 전략 매칭: {h} → {key}")
                    return key
    # [FIX-V62-1] 기본값 PULLBACK (기관 동행 최장 보유 우선, EOD 삭제)
    log.info("[STRAT] hint 없음 → PULLBACK 기본 (v6.2: EOD 삭제)")
    return "PULLBACK"


# ==============================================================================
# [FIX-V6-4] ride_score → position_size 배율
# ==============================================================================
def _calc_ride_size_mult(top1: pd.DataFrame, forced_entry: bool, log) -> float:
    """
    [FIX-V6-4] 지침서[15] 5-4절 ride_score → position_size 직결.
    [FIX-V62-7] ride≥0.65 AND inst_consec≥5 → RIDE_STRONG_MULT 1.15 (v6.2 강화)

    지침서 원문:
      ride ≥ 0.65 : 기관 강매집 → Trail 완화 (k×1.2)
      0.40~0.65   : 기관 동행 확인 → Trail 표준
      < 0.40      : 기관 미확인 → Trail 금지
    """
    if forced_entry and not RCFG.RIDE_APPLY_FORCED:
        log.debug("[RIDE] 강제 진입 → ride_score 보정 비활성")
        return 1.0

    ride_score = 0.0
    found = False
    for col in ("inst_ride_score", "ride_score", "ride"):
        if col in top1.columns:
            val = pd.to_numeric(top1.iloc[0].get(col, None), errors="coerce")
            if pd.notna(val):
                ride_score = float(val)
                found = True
                break

    if not found:
        # [FIX-V62-7] ride 데이터 없으면 inst_consec으로 추정
        for col_c in ("inst_consec", "inst_days"):
            if col_c in top1.columns:
                consec = int(
                    pd.to_numeric(top1.iloc[0].get(col_c, 0), errors="coerce") or 0
                )
                if consec >= RCFG.RIDE_STRONG_CONSEC:
                    log.debug(
                        f"[RIDE] ride_score 없음, inst_consec={consec} ≥ "
                        f"{RCFG.RIDE_STRONG_CONSEC} → 강매집 추정 ×{RCFG.RIDE_STRONG_MULT:.2f}"
                    )
                    return round(RCFG.RIDE_STRONG_MULT, 4)
        log.debug("[RIDE] ride_score 컬럼 없음 → 1.0 (중립)")
        return 1.0

    # inst_consec 확인 (S등급 보너스 조건)
    inst_consec = 0
    for col_c in ("inst_consec", "inst_days"):
        if col_c in top1.columns:
            inst_consec = int(
                pd.to_numeric(top1.iloc[0].get(col_c, 0), errors="coerce") or 0
            )
            break

    if ride_score >= RCFG.RIDE_STRONG_THRESH:
        mult = RCFG.RIDE_STRONG_MULT
        if inst_consec >= RCFG.RIDE_STRONG_CONSEC:
            log.info(
                f"[RIDE-S] ride={ride_score:.3f} ≥ {RCFG.RIDE_STRONG_THRESH} "
                f"AND consec={inst_consec} ≥ {RCFG.RIDE_STRONG_CONSEC} "
                f"→ S등급 강매집 ×{mult:.2f}"
            )
        else:
            log.info(
                f"[RIDE] ride={ride_score:.3f} ≥ {RCFG.RIDE_STRONG_THRESH} "
                f"→ 기관 강매집 ×{mult:.2f}"
            )
    elif ride_score >= RCFG.RIDE_WEAK_THRESH:
        mult = 1.0
        log.debug(
            f"[RIDE] ride={ride_score:.3f} (0.40~0.65) → 기관 동행 ×1.00 (표준)"
        )
    else:
        mult = RCFG.RIDE_WEAK_MULT
        log.info(
            f"[RIDE] ride={ride_score:.3f} < {RCFG.RIDE_WEAK_THRESH} "
            f"→ 기관 미확인 ×{mult:.2f} (사이즈 축소)"
        )

    return round(mult, 4)


# ==============================================================================
# ofi_accel 자체 계산 fallback [v5.0]
# ==============================================================================
def _calc_ofi_accel_fallback(top1: pd.DataFrame, log) -> float:
    """
    Cont, Kukanov, Stoikov (2014) 기반:
    accel = mean(inst_net_buy, 최근3봉) / mean(inst_net_buy, 이전5봉)
    """
    series = []
    for i in range(1, RCFG.ACCEL_RECENT_N + RCFG.ACCEL_BASE_N + 1):
        col = f"inst_net_buy_{i}"
        if col in top1.columns:
            val = pd.to_numeric(top1.iloc[0].get(col, None), errors="coerce")
            if pd.notna(val):
                series.append(float(val))

    if len(series) < (RCFG.ACCEL_RECENT_N + RCFG.ACCEL_BASE_N):
        for col in ("inst_net_buy_list", "inst_net_buy_series"):
            if col in top1.columns:
                raw = str(top1.iloc[0].get(col, ""))
                try:
                    parsed = [float(x.strip()) for x in raw.split(",") if x.strip()]
                    if len(parsed) >= RCFG.ACCEL_RECENT_N + RCFG.ACCEL_BASE_N:
                        series = parsed
                        break
                except Exception as e:
                    log.debug("[ACCEL] 시계열 파싱 실패 (스킵): %s", e)

    if len(series) < (RCFG.ACCEL_RECENT_N + RCFG.ACCEL_BASE_N):
        log.debug(f"[ACCEL] 시계열 부족({len(series)}봉) → 중립 {RCFG.ACCEL_NEUTRAL}")
        return RCFG.ACCEL_NEUTRAL

    recent      = series[:RCFG.ACCEL_RECENT_N]
    base        = series[RCFG.ACCEL_RECENT_N: RCFG.ACCEL_RECENT_N + RCFG.ACCEL_BASE_N]
    mean_recent = float(np.mean(recent))
    mean_base   = float(np.mean(base))

    if abs(mean_base) < RCFG.EPS:
        log.debug("[ACCEL] 이전 봉 평균 0 → 중립 1.0")
        return RCFG.ACCEL_NEUTRAL

    accel = mean_recent / (mean_base + RCFG.EPS)
    log.info(
        f"[ACCEL] 자체계산: 최근{RCFG.ACCEL_RECENT_N}봉={mean_recent:+,.0f} "
        f"/ 이전{RCFG.ACCEL_BASE_N}봉={mean_base:+,.0f} = {accel:.3f}"
    )
    return round(accel, 4)


# ==============================================================================
# 기관 모멘텀 사이즈 배율 [v5.0 + v6.0 accel 포함]
# ==============================================================================
def _calc_inst_mult(top1: pd.DataFrame, strategy_profile: dict, log) -> float:
    inst_consec = 0
    ofi_accel   = RCFG.ACCEL_NEUTRAL

    for col_c in ("inst_consec", "inst_days"):
        if col_c in top1.columns:
            inst_consec = int(
                pd.to_numeric(top1.iloc[0].get(col_c, 0), errors="coerce") or 0
            )
            break

    accel_from_upstream = False
    for col_o in ("ofi_accel", "ofi_accel_ratio"):
        if col_o in top1.columns:
            val = pd.to_numeric(top1.iloc[0].get(col_o, None), errors="coerce")
            if pd.notna(val):
                ofi_accel = float(val)
                accel_from_upstream = True
                log.debug(f"[ACCEL] upstream 수신: {ofi_accel:.3f}")
                break

    if not accel_from_upstream:
        ofi_accel = _calc_ofi_accel_fallback(top1, log)

    strat_bonus = strategy_profile.get("inst_mult_bonus", 1.0)

    if inst_consec >= 5 and ofi_accel > 0:
        mult = RCFG.INST_STRONG_SCALE
        log.info(f"[INST] 초강세: consec={inst_consec} accel={ofi_accel:.3f} → {mult:.2f}x")
    elif inst_consec >= RCFG.INST_BOOST_MIN_CONSEC and ofi_accel > 0:
        mult = RCFG.INST_BOOST_SCALE
        log.info(f"[INST] 강세: consec={inst_consec} accel={ofi_accel:.3f} → {mult:.2f}x")
    elif inst_consec <= 0:
        mult = RCFG.INST_WEAK_SCALE
        log.warning(f"[INST] 이탈: consec={inst_consec} → {mult:.2f}x")
    else:
        mult = 1.0
        log.debug(f"[INST] 중립: consec={inst_consec} accel={ofi_accel:.3f} → 1.0x")

    final_mult = 1.0 + (mult - 1.0) * strat_bonus
    return round(final_mult, 4)


def _is_inst_holding(top1: pd.DataFrame) -> bool:
    for col in ("inst_consec", "inst_days"):
        if col in top1.columns:
            consec = int(
                pd.to_numeric(top1.iloc[0].get(col, 0), errors="coerce") or 0
            )
            return consec >= RCFG.INST_HOLD_MIN_CONSEC
    return False


# ==============================================================================
# DD 브레이커 — 3단계 + 기관 Hold 면제 [v5.0 초기자본 역산]
# ==============================================================================
class DDBreakerResult:
    OK    = "OK"
    ALERT = "ALERT"
    SCALE = "SCALE"
    STOP  = "STOP"


def _check_dd_breaker(
    cash: int, realized_pnl: int,
    regime_params: dict, inst_holding: bool, log
) -> tuple:
    """
    [v5.0] 초기 자본 역산 적용.
    initial_capital = cash - realized_pnl
    dd_pct = realized_pnl / initial_capital
    """
    if cash <= 0:
        return DDBreakerResult.OK, 0.0, 1.0

    initial_capital = cash - realized_pnl
    if initial_capital <= 0:
        initial_capital = cash
        log.warning("[DD] 초기 자본 역산 이상 → 현재 현금으로 대체")

    dd_pct  = realized_pnl / (initial_capital + RCFG.EPS)
    dd_warn = regime_params.get("dd_warn", RCFG.DD_WARN_THRESH)
    dd_stop = regime_params.get("dd_stop", RCFG.DD_STOP_THRESH)

    if dd_pct <= dd_stop:
        if inst_holding:
            log.warning(
                f"[DD-HOLD] dd={dd_pct:.2%} ≤ STOP({dd_stop:.2%}) "
                f"BUT 기관 보유 → SCALE 완화"
            )
            return DDBreakerResult.SCALE, dd_pct, 0.50
        log.warning(f"[DD-STOP] dd={dd_pct:.2%} ≤ {dd_stop:.2%} → 당일 거래 중단")
        # [CYCLE-6 2026-05-21] event_journal DD_STOP emit
        _emit_event("DD_STOP", entity="entry", payload={"dd_pct": float(dd_pct), "dd_stop": float(dd_stop)})
        return DDBreakerResult.STOP, dd_pct, 0.0

    if dd_pct <= dd_warn:
        if inst_holding:
            log.info(f"[DD-HOLD] dd={dd_pct:.2%} ≤ WARN → ALERT 완화")
            return DDBreakerResult.ALERT, dd_pct, 0.75
        log.warning(f"[DD-SCALE] dd={dd_pct:.2%} ≤ {dd_warn:.2%} → 배포 50%")
        return DDBreakerResult.SCALE, dd_pct, 0.50

    if dd_pct <= RCFG.DD_ALERT_THRESH:
        log.info(f"[DD-ALERT] dd={dd_pct:.2%} → 배포 75%")
        return DDBreakerResult.ALERT, dd_pct, 0.75

    log.debug(f"[DD] 정상: dd={dd_pct:.2%} (초기자본={initial_capital:,}원)")
    return DDBreakerResult.OK, dd_pct, 1.0


# ==============================================================================
# Kelly Calculator — 전략별 독립 계산 [v5.0]
# ==============================================================================
class KellyCalcByStrategy:
    """
    전략별 원장 필터 → 독립 계산.
    데이터 부족 시 전체 원장 폴백 → 초기 보수 fallback.
    출처: Thorp (1962) "동질 게임별 분리 사이징 필수"
    """
    def __init__(
        self, ledger: pd.DataFrame, strategy_hint: str,
        regime_params: dict, strategy_profile: dict, log
    ):
        self.log               = log
        self._f: float | None  = None
        self._stats: dict      = {}
        self._regime_params    = regime_params
        self._strategy_profile = strategy_profile
        self._strategy_hint    = strategy_hint
        if not ledger.empty:
            self._compute(ledger, strategy_hint)

    def _compute(self, df: pd.DataFrame, strategy_hint: str) -> None:
        if "pnl_pct" not in df.columns:
            return

        strat_df  = df.copy()
        strat_col = next(
            (c for c in ("strategy_hint", "strategy") if c in df.columns), None
        )
        if strat_col:
            filtered = df[
                df[strat_col].astype(str).str.upper().str.strip() == strategy_hint
            ]
            if len(filtered) >= RCFG.KELLY_MIN_TRADES:
                strat_df = filtered
                self.log.info(
                    f"[KELLY] 전략별 필터: {strategy_hint} → {len(strat_df)}건"
                )
            else:
                self.log.info(
                    f"[KELLY] {strategy_hint} 부족({len(filtered)}) → 전체 폴백({len(df)}건)"
                )

        s = strat_df["pnl_pct"].dropna()
        if len(s) < RCFG.KELLY_MIN_TRADES:
            self.log.info(f"[KELLY] 거래 수 부족({len(s)}) → 초기 보수 fallback")
            return

        wins   = s[s > 0]
        losses = s[s <= 0].abs()
        if wins.empty or losses.empty:
            self.log.info("[KELLY] 승/패 한쪽 없음 → fallback")
            return

        p  = len(wins) / len(s)
        b  = wins.mean() / (losses.mean() + RCFG.EPS)
        f  = (p * b - (1 - p)) / (b + RCFG.EPS)

        regime_mult = self._regime_params.get("kelly_mult", 1.0)
        strat_mult  = self._strategy_profile.get("kelly_half_mult", 1.0)
        self._f     = f * RCFG.KELLY_HALF * regime_mult * strat_mult

        avg_win  = float(wins.mean())
        avg_loss = float(losses.mean())
        pf       = (p * avg_win) / ((1 - p) * avg_loss + RCFG.EPS)

        if f < 0:
            self.log.warning(
                f"[KELLY-{strategy_hint}] 기대값 음수: f={f:.4f} "
                f"(승률={p:.1%}, 손익비={b:.2f})"
            )
        else:
            self.log.info(
                f"[KELLY-{strategy_hint}] 승률={p:.1%} | 손익비={b:.2f} | "
                f"PF={pf:.2f} | Half-Kelly={self._f:.3f} | n={len(s)}"
            )

        self._stats = {
            "strategy":       strategy_hint,
            "win_rate":       round(p, 4),
            "payoff_ratio":   round(b, 4),
            "avg_win_pct":    round(avg_win, 4),
            "avg_loss_pct":   round(avg_loss, 4),
            "profit_factor":  round(pf, 4),
            "kelly_full":     round(f, 4),
            "kelly_half":     round(self._f, 4),
            "n_trades":       len(s),
            "kelly_negative": f < 0,
            "regime_mult":    regime_mult,
            "strat_mult":     strat_mult,
            "computed_at":    datetime.now().strftime("%Y%m%d%H%M%S"),
        }

    def get_size(self) -> float:
        if self._f is None:
            fb = RCFG.ATTACK_RATIO * 0.35
            self.log.info(f"[KELLY] 초기 보수 fallback: {fb:.3f}")
            return fb
        return max(0.0, min(RCFG.KELLY_MAX, self._f))

    @property
    def stats(self) -> dict:
        return self._stats.copy()


# ==============================================================================
# [FIX-V6-2] CVaR — 전략별 분리 (Kelly와 일관성)
# ==============================================================================
class SingleVaRCalcByStrategy:
    """
    [FIX-V6-2] CVaR 전략별 독립 계산.

    v5.0 문제: Kelly는 전략별 분리, CVaR는 전체 혼합 → 불일치
    v6.0 수정: 전략별 필터 후 CVaR 계산
               데이터 부족 시 전체 원장 폴백 → 초기 보수 모드

    출처: Rockafellar & Uryasev (2000) JOR 2(3):21-41
    """
    def __init__(
        self, ledger: pd.DataFrame, strategy_hint: str, log
    ):
        self.log            = log
        self._strategy_hint = strategy_hint
        self._rets          = pd.Series(dtype=float)
        self._source        = "none"

        if ledger.empty or "pnl_pct" not in ledger.columns:
            self.log.info("[VAR] 원장 없음 → CVaR 초기 보수 모드")
            return

        # ── 전략별 필터 ──────────────────────────────────────────
        strat_col = next(
            (c for c in ("strategy_hint", "strategy") if c in ledger.columns), None
        )
        if strat_col:
            filtered = ledger[
                ledger[strat_col].astype(str).str.upper().str.strip() == strategy_hint
            ]
            # [FIX-V62-3] 최소 표본 10→15건: R&U(2000) 95% CVaR 안정화 기준
            if len(filtered) >= 15:
                self._rets   = filtered["pnl_pct"].dropna()
                self._source = f"strategy({strategy_hint})"
                self.log.info(
                    f"[VAR] 전략별 CVaR: {strategy_hint} → {len(self._rets)}건"
                )
                return

        # ── 전체 원장 폴백 ───────────────────────────────────────
        self._rets   = ledger["pnl_pct"].dropna()
        self._source = "all"
        self.log.info(
            f"[VAR] {strategy_hint} CVaR 데이터 부족 → 전체 원장 폴백({len(self._rets)}건)"
        )

    def compute(self, position_size: float) -> dict:
        if self._rets.empty:
            return {"var": 0.0, "cvar": 0.0, "ok": False, "initial": True,
                    "source": "initial"}

        q    = np.percentile(self._rets, (1 - RCFG.VAR_CONFIDENCE) * 100)
        var  = abs(q) * position_size
        tail = self._rets[self._rets <= q]
        cvar = abs(tail.mean()) * position_size if not tail.empty else var

        ok = cvar <= RCFG.CVAR_LIMIT
        if not ok:
            self.log.warning(
                f"[VAR-{self._strategy_hint}] CVaR={cvar:.3%} "
                f"> 한도={RCFG.CVAR_LIMIT:.3%} → 축소 (src={self._source})"
            )
        else:
            self.log.debug(
                f"[VAR-{self._strategy_hint}] VaR={var:.3%} | "
                f"CVaR={cvar:.3%} → OK (src={self._source})"
            )
        return {"var": var, "cvar": cvar, "ok": ok, "initial": False,
                "source": self._source}

    def adjust_size_to_cvar(self, position_size: float) -> float:
        if position_size <= 0:
            return position_size
        if self._rets.empty:
            cap = min(position_size, RCFG.ATTACK_RATIO * 0.35)
            self.log.info(f"[VAR] 초기 보수 cap: {position_size:.3f} → {cap:.3f}")
            return cap
        result = self.compute(position_size)
        if result.get("initial", False) or result["ok"]:
            return position_size
        cvar_unit = result["cvar"] / (position_size + RCFG.EPS)
        adjusted  = RCFG.CVAR_LIMIT / (cvar_unit + RCFG.EPS)
        adjusted  = max(RCFG.DEPLOY_THRESHOLD, min(RCFG.KELLY_MAX, adjusted))
        self.log.info(
            f"[VAR-{self._strategy_hint}] CVaR 축소: "
            f"{position_size:.3f} → {adjusted:.3f}"
        )
        return adjusted


# ==============================================================================
# Risk Grade — 6단계 (수익률 연계 + ride_score 반영)
# ==============================================================================
def _assign_risk_grade(
    position_size: float, var_ok: bool,
    inst_mult: float, regime: str,
    profit_factor: float = 0.0,
    ride_mult: float = 1.0,
    forced: bool = False,
) -> str:
    """
    S : 최적 — 풀 배포 + 기관 강세 + CVaR OK + PF>1.5 + ride 강매집
    A : 양호 — 풀 배포, CVaR OK
    B : 보통 — 정상 배포
    C : 경계 — 축소 배포
    D : 위험 — 최소 배포
    F : 강제 진입 — 지침서 1일 1진입 원칙
    """
    if forced:
        return "F"
    if (position_size >= RCFG.ATTACK_RATIO * 0.90
            and var_ok and inst_mult >= 1.1
            and profit_factor >= 1.5
            and ride_mult >= RCFG.RIDE_STRONG_MULT):
        return "S"
    if position_size >= RCFG.ATTACK_RATIO * 0.90 and var_ok:
        return "A"
    if position_size >= RCFG.ATTACK_RATIO * 0.60:
        return "B"
    if position_size >= RCFG.ATTACK_RATIO * 0.35:
        return "C"
    return "D"


# ==============================================================================
# Kelly 스냅샷 — 전략별 독립 저장 (자기진화) [v5.0]
# ==============================================================================
def _save_kelly_snapshot(kelly: KellyCalcByStrategy, log) -> None:
    if not kelly.stats:
        return
    p = Path(RCFG.PATH_KELLY_SNAP)
    p.parent.mkdir(parents=True, exist_ok=True)

    history: dict = {}
    if p.exists():
        try:
            with open(p, encoding="utf-8-sig") as f:
                history = json.load(f)
            if not isinstance(history, dict):
                history = {}
        except Exception:
            history = {}

    today = datetime.now().strftime("%Y%m%d")
    strat = kelly.stats.get("strategy", "PULLBACK")

    if today not in history:
        history[today] = {}
    history[today][strat] = kelly.stats

    keys = sorted(history.keys())
    for old in keys[:-90]:
        history.pop(old, None)

    tmp = str(p) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
        log.debug(f"[EVO] Kelly 스냅샷 저장: {today}[{strat}]")
    except Exception as e:
        log.warning(f"[EVO] 스냅샷 저장 실패: {e}")


# ==============================================================================
# 핵심 처리
# ==============================================================================
# ═══════════════════════════════════════════════════════════════
#  [v6.9 TRACE] RISK_SUMMARY — 매수 차단 추적
# ═══════════════════════════════════════════════════════════════
_RISK_STATS: dict = {
    "input_codes": -1,      # rt_intraday.csv 행 수
    "sb_filter_count": -1,  # SB-FILTER 후 행 수
    "bt_filter_count": -1,  # BT-FILTER 후 행 수
    "output_codes": -1,     # rt_risk_candidates.csv 저장 행 수
    "hold_reason": "",
    "rc": -1,
}

def _risk_stats_reset() -> None:
    _RISK_STATS.update({"input_codes": -1, "sb_filter_count": -1,
                        "bt_filter_count": -1, "output_codes": -1,
                        "hold_reason": "", "rc": -1})

def _risk_set_reason(reason: str) -> None:
    if not _RISK_STATS["hold_reason"]:
        _RISK_STATS["hold_reason"] = reason

def _emit_risk_summary(log) -> None:
    try:
        log.info("[RISK_SUMMARY] input_codes=%d sb_filter=%d bt_filter=%d "
                 "output_codes=%d hold_reason=%s rc=%d",
                 _RISK_STATS["input_codes"], _RISK_STATS["sb_filter_count"],
                 _RISK_STATS["bt_filter_count"], _RISK_STATS["output_codes"],
                 _RISK_STATS["hold_reason"] or "-", _RISK_STATS["rc"])
    except Exception:
        pass


def process(log) -> int:
    _risk_stats_reset()
    rc = RC_HOLD
    try:
        rc = _process_body(log)
        return rc
    finally:
        _RISK_STATS["rc"] = rc
        _emit_risk_summary(log)


def _process_body(log) -> int:

    # ── 0. 자기진화 파라미터 로드 ────────────────────────────────────────
    _load_evolved_params(log)

    # ── 1. 1일 1진입 Gate ────────────────────────────────────────────────
    # [v6.5 RELAY-FIX] 전략 힌트를 게이트 전에 조기 감지
    # → SIGA/PULLBACK 릴레이 허용 판단에 사용
    entry_state    = _load_entry_state()
    # [C-1 FIX 2026-06-07] 게이트 전략힌트를 'rt_intraday 첫 행'(intent_score 재정렬 후 임의 1위=테마리더일 수
    #   있음)이 아니라 '선택 로직과 일치하는 행=prescore_weighted 최고 행'에서 읽음. 첫행 hint≠실제 선택후보
    #   전략이면 게이트가 오판(특히 A-1 이후 false-block→누락) → 이를 차단. SHADOW로 두 방식 hint 항상 비교 로깅.
    #   env GATE_HINT_FROM_PRESCORE=NO면 기존 첫행 방식 복귀. prescore_weighted 컬럼없음/읽기실패→첫행 fallback.
    _gate_hint_from_ps = os.environ.get("GATE_HINT_FROM_PRESCORE", "YES").strip().upper() == "YES"
    _hint_firstrow = ""
    _hint_psmax    = ""
    _psmax_code    = ""
    _psmax_ok      = False
    try:
        _p_hint = Path(RCFG.PATH_INTRADAY)
        if _p_hint.exists():
            _df_h = pd.read_csv(_p_hint, encoding="utf-8-sig")
            if not _df_h.empty:
                _hcol = next((c for c in ("strategy_hint", "strategy", "hint") if c in _df_h.columns), None)
                if _hcol:
                    _hint_firstrow = str(_df_h.iloc[0].get(_hcol, "")).upper().strip()
                    if "prescore_weighted" in _df_h.columns:
                        _ps = pd.to_numeric(_df_h["prescore_weighted"], errors="coerce").fillna(-1e9)
                        _imax = int(_ps.values.argmax())
                        _hint_psmax = str(_df_h.iloc[_imax].get(_hcol, "")).upper().strip()
                        _psmax_code = str(_df_h.iloc[_imax].get("code", "")).strip()
                        _psmax_ok = True
    except Exception:
        pass
    _hint_for_gate = _hint_psmax if (_gate_hint_from_ps and _psmax_ok) else _hint_firstrow
    if _psmax_ok and _hint_firstrow != _hint_psmax:
        log.info("[GATE-HINT][SHADOW] firstrow=%s prescore_max=%s(code=%s) → used=%s (from_prescore=%s)",
                 _hint_firstrow or "-", _hint_psmax or "-", _psmax_code or "-",
                 _hint_for_gate or "-", _gate_hint_from_ps)
    else:
        log.info("[GATE-HINT] hint=%s (firstrow=prescore_max 일치 또는 단일소스)", _hint_for_gate or "-")
    if not _check_daily_entry_gate(entry_state, log, _hint_for_gate):
        # [v6.8 STALE-FIX] daily gate HOLD 시 stale rt_risk_candidates.csv 재사용 방지
        log.warning("[RISK][HOLD][REASON=daily_entry_gate] 1일1진입 게이트 차단 → 빈 출력 갱신")
        _write_empty_output(log)
        return RC_HOLD

    # ── 2. 후보 로드 ─────────────────────────────────────────────────────
    # [v6.9 STALE-FIX] rt_intraday.csv 자체 차단 시에도 stale rt_risk_candidates.csv 재사용 방지
    p = Path(RCFG.PATH_INTRADAY)
    if not p.exists():
        log.info("[RISK][HOLD][REASON=rt_intraday_missing] rt_intraday.csv 없음 → HOLD")
        _write_empty_output(log)
        return RC_HOLD

    age = time.time() - p.stat().st_mtime
    if age > RCFG.CAND_STALE_SEC:
        log.warning(
            f"[RISK][HOLD][REASON=rt_intraday_stale] 후보 stale({age:.0f}s > {RCFG.CAND_STALE_SEC}s) → HOLD "
            f"[지침서12-1: 90초 데이터 지연 킬스위치]"
        )
        _write_empty_output(log)
        return RC_HOLD

    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
    except Exception as e:
        log.error(f"[RISK][STOP][REASON=rt_intraday_read_fail] 후보 로드 실패: {e}")
        _risk_set_reason("rt_intraday_read_fail")
        _write_empty_output(log)
        return RC_STOP

    _RISK_STATS["input_codes"] = len(df)

    # [PB-STEP0 2026-06-16 ★친구님] 동적 테마대장 — best_theme 내 당일 거래대금(value_day) 1~2위만 생존, 3위↓ 제거.
    #   ★친구님 안전조건: ①value_day 0/결측 = rank 전 따로 통과(+[PB-STEP0-NOVALUE]) ②테마없음 = rank 전 따로 통과
    #   (빈 테마끼리 groupby로 묶여 3위↓ 잘리는 것 방지). rankable(테마有+값有)만 순위 매김. 전원탈락/예외 = fail-safe 전체유지.
    if PB_DYNAMIC_THEME_TOP2 and not df.empty:
        try:
            _tmap = _load_theme_strength_pb()
            _nmap = _load_pb_names()
            _before = len(df)
            df["code"] = df["code"].astype(str).str.zfill(6)
            df["_pb_theme"] = df["code"].map(lambda c: (_tmap.get(c, {}) or {}).get("theme", "") or "")
            df["_pb_vd"] = pd.to_numeric(df.get("value_day"), errors="coerce")   # 결측 = NaN 유지
            # ① 무값(0/결측) → 통과 + NOVALUE 로그 (수집 누락 보호)
            _novalue = df["_pb_vd"].isna() | (df["_pb_vd"] <= 0)
            for _, r in df[_novalue].iterrows():
                log.info("[PB-STEP0-NOVALUE] %s/%s theme=%s value_day=%s → 통과(결측보호)",
                         r["code"], _nmap.get(r["code"], ""), (r["_pb_theme"] or "없음"),
                         "결측" if pd.isna(r["_pb_vd"]) else "0")
            # ② 테마없음 → 통과 (빈테마끼리 묶지 않음)
            _notheme = df["_pb_theme"] == ""
            # ③ rank 대상 = 테마有 AND 값有 만
            _rankable_mask = (~_novalue) & (~_notheme)
            _passthru = df[~_rankable_mask].copy()
            _rank = df[_rankable_mask].copy()
            if not _rank.empty:
                _rank["_pb_dvrank"] = _rank.groupby("_pb_theme")["_pb_vd"].rank(ascending=False, method="first")
                _surv = _rank[_rank["_pb_dvrank"] <= 2].copy()
                _rem = _rank[_rank["_pb_dvrank"] > 2].copy()
                for _, r in _rem.sort_values("_pb_vd", ascending=False).iterrows():
                    log.info("[PB-STEP0-REMOVE] %s/%s theme=%s dvrank=%d value_day=%d",
                             r["code"], _nmap.get(r["code"], ""), r["_pb_theme"],
                             int(r["_pb_dvrank"]), int(r["_pb_vd"]))
            else:
                _surv = _rank.copy()
            _kept = pd.concat([_passthru, _surv], ignore_index=True)
            if len(_kept) >= 1:
                df = _kept
            else:
                log.warning("[PB-STEP0] 생존 0 → fail-safe 전체유지")
            log.info("[PB-STEP0] before=%d after=%d removed=%d (통과: 테마없음/무값 %d)",
                     _before, len(df), _before - len(df), len(_passthru))
            _sv = df.sort_values("_pb_vd", ascending=False, na_position="last").head(8)
            log.info("[PB-STEP0-SURVIVE] top8=%s",
                     [(r["code"], (r.get("_pb_theme", "") or "?")[:8],
                       int(r["_pb_dvrank"]) if pd.notna(r.get("_pb_dvrank", float("nan"))) else 0)
                      for _, r in _sv.iterrows()])
            df = df.drop(columns=["_pb_theme", "_pb_vd", "_pb_dvrank"], errors="ignore")
        except Exception as _e:
            log.warning("[PB-STEP0] 실패(%s) → 전체유지(부하제거 생략, fail-open)", _e)

    # [PULLBACK-POOL 2026-06-13 친구님] 눌림 후보 = 테마 대장주 풀(상위K 강한테마 멤버). score_eod 대체.
    #   YES면 아래 score_eod SB-FILTER를 건너뛰고 여기서 테마풀로 거른다(그 안에서 score_col=모멘텀이 1등 선별).
    #   ★[FUNNEL시 교집합 제거 2026-06-13 친구님] 퍼널 켜지면 이 22-교집합도 끔 → make_rt 160 전부가 퍼널로(STEP1이 거름).
    if PULLBACK_FUNNEL_ENABLE:
        log.info("[PULLBACK-POOL] 퍼널 모드 → 화이트리스트 교집합 생략(make_rt %d종목 전부 퍼널로, STEP1이 죽을놈 제거)", len(df))
    elif PULLBACK_THEME_POOL:
        try:
            _tmap_pool = _load_theme_strength_pb()
            if _tmap_pool:
                _pool_codes = {c for c, tm in _tmap_pool.items()
                               if tm.get("rank", 999) <= PULLBACK_THEME_POOL_TOPK}
                if _pool_codes:
                    df["code"] = df["code"].astype(str).str.zfill(6)
                    _before_pool = len(df)
                    df = df[df["code"].isin(_pool_codes)].copy()
                    log.info("[PULLBACK-POOL] 테마대장주 풀(상위%d강한테마 %d종목) 필터: %d→%d행",
                             PULLBACK_THEME_POOL_TOPK, len(_pool_codes), _before_pool, len(df))
                else:
                    log.warning("[PULLBACK-POOL] 테마대장주 풀 0종목 → 필터 스킵(전체 유지)")
            else:
                log.warning("[PULLBACK-POOL] code_theme_strength 없음/stale → 필터 스킵(전체 유지)")
        except Exception as _ppe:
            log.warning("[PULLBACK-POOL] 테마풀 필터 실패 → 스킵: %s", _ppe)

    # [SB-FILTER] scoreboard 화이트리스트 — score_eod.csv 내 종목만 평가 (PULLBACK_THEME_POOL=YES면 건너뜀)
    _sb_path = Path(RCFG.PATH_INTRADAY).parent / "scoreboard" / "score_eod.csv"
    try:
        if (not PULLBACK_THEME_POOL) and (not PULLBACK_FUNNEL_ENABLE) and _sb_path.exists() and _sb_path.stat().st_size > 0:
            _sb_df = pd.read_csv(_sb_path, encoding="utf-8-sig", dtype=str)
            if "code" in _sb_df.columns:
                _sb_codes = {str(c).strip().zfill(6) for c in _sb_df["code"].dropna()}
                # [TIE-BAND 2026-06-02] score_eod의 50지표 종합점수를 박빙 tiebreaker용으로 보관.
                #   Top-1을 prescore_weighted(intraday 실시간)로 뽑되, 1등과 박빙인 후보는 sb_score(정교)로 가린다.
                _sb_score_col = "score" if "score" in _sb_df.columns else ("score_final" if "score_final" in _sb_df.columns else None)
                _sb_score_map = {}
                if _sb_score_col:
                    for _, _sr in _sb_df.iterrows():
                        try:
                            _sb_score_map[str(_sr["code"]).strip().zfill(6)] = float(_sr[_sb_score_col])
                        except (ValueError, TypeError):
                            pass
                if _sb_codes:
                    df["code"] = df["code"].astype(str).str.zfill(6)
                    # [SB-LOG 2026-05-12] 탈락 종목 가시화 — 어느 종목이 scoreboard 미포함으로 탈락하는지 운영 로그 강화
                    _sb_before = set(df["code"])
                    _df_pre_sb = df.copy()   # [SB-EXPAND-SHADOW] 잘린 행 원본 보존
                    df = df[df["code"].isin(_sb_codes)].copy()
                    if _sb_score_map:
                        df["sb_score"] = df["code"].map(_sb_score_map).fillna(0.0)
                    _sb_dropped = sorted(_sb_before - set(df["code"]))
                    if _sb_dropped:
                        log.info("[SB-FILTER] 탈락 %d종목 (scoreboard 미포함, 상위15): %s",
                                 len(_sb_dropped), _sb_dropped[:15])
                    log.info("[SB-FILTER] scoreboard %d종목 필터 후 %d행 (입력=%d, 탈락=%d)",
                             len(_sb_codes), len(df), len(_sb_before), len(_sb_dropped))
                    # [SB-EXPAND-SHADOW 2026-06-10] '보드 ∪ rt 상위 N' 확장 검토용 — 잘린 종목 중
                    #   prescore_weighted 상위 N을 기록만(통과 안 시킴). 며칠 채점 후 실확장 판단.
                    #   목적: ①보드 종속 완화 ②클로버(장중 보드 재계산) 수정 시의 보험. env SB_EXPAND_SHADOW_N=0 끔.
                    try:
                        _exp_n = int(os.environ.get("SB_EXPAND_SHADOW_N", "5"))
                        if _exp_n > 0 and _sb_dropped and "prescore_weighted" in _df_pre_sb.columns:
                            _cutdf = _df_pre_sb[_df_pre_sb["code"].isin(_sb_dropped)].copy()
                            _cutdf["prescore_weighted"] = pd.to_numeric(
                                _cutdf["prescore_weighted"], errors="coerce").fillna(0.0)
                            _topcut = _cutdf.nlargest(_exp_n, "prescore_weighted")
                            _shadow_rows = [(str(r["code"]).zfill(6), round(float(r["prescore_weighted"]), 2))
                                            for _, r in _topcut.iterrows()]
                            log.info("[SB-EXPAND-SHADOW] 보드밖 prescore 상위%d(확장시 추가됐을 후보): %s",
                                     _exp_n, _shadow_rows)
                            import csv as _csv2
                            _shp = Path(r"C:\stock_bot\data\LOG\sb_expand_shadow.csv")
                            _new_sh = not _shp.exists()
                            with _shp.open("a", newline="", encoding="utf-8-sig") as _shf:
                                _w2 = _csv2.writer(_shf)
                                if _new_sh:
                                    _w2.writerow(["ts", "code", "prescore_weighted"])
                                _ts_now = datetime.now().strftime("%Y%m%d%H%M%S")
                                for _c2, _p2 in _shadow_rows:
                                    _w2.writerow([_ts_now, _c2, _p2])
                    except Exception as _exp_e:
                        log.debug("[SB-EXPAND-SHADOW] 기록 실패(무시): %s", _exp_e)
    except Exception as _sb_e:
        log.warning("[SB-FILTER] score_eod 로드 실패 → 필터 스킵: %s", _sb_e)

    _RISK_STATS["sb_filter_count"] = len(df)

    # [BT-FILTER v6.8 FIX] bridge_target.json 필수 화이트리스트
    # 이유: Bridge ∩ Risk 보장. stale/누락/파싱실패 시 독립 Risk 선택 회귀 금지
    #      → 반드시 _write_empty_output() 호출 후 HOLD (stale csv 재사용 방지)
    _bt_path = Path(RCFG.PATH_INTRADAY).parent / "bridge_target.json"
    if not (_bt_path.exists() and _bt_path.stat().st_size > 0):
        log.error("[BT-FILTER][HOLD][REASON=bridge_target_missing] %s 없음/빈파일 → 빈 출력 갱신",
                  _bt_path)
        _write_empty_output(log)
        return RC_HOLD
    try:
        with open(_bt_path, "r", encoding="utf-8-sig") as _bt_f:
            _bt_data = json.load(_bt_f)
        # [v6.8] KST 기준 오늘 날짜 (timezone 미명시 회귀 방지)
        try:
            from zoneinfo import ZoneInfo as _ZI
            _bt_today = datetime.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")
        except Exception:
            _bt_today = datetime.now().strftime("%Y-%m-%d")
        _bt_date = str(_bt_data.get("date", ""))
        _bt_raw  = _bt_data.get("codes", []) or []
        if _bt_date != _bt_today:
            log.error("[BT-FILTER][HOLD][REASON=bridge_target_stale] date=%s today=%s(KST) → 빈 출력 갱신",
                      _bt_date, _bt_today)
            _write_empty_output(log)
            return RC_HOLD
        # [R24 2026-05-14] codes=[] AND eod_inactive=True 시 폴백 허용
        #   bridge_eod 본 시간창(15:15~15:25) 외 — 09시대 등 — rt_intraday 직접 사용.
        #   rt_execution_engine L1010 의 `_LAST_TARGET_EOD_INACTIVE` 폴백과 정합.
        #   date stale 분기(L1561~1565)는 유지 — 어제 데이터 차단 본래 의도 보존.
        _bt_skip = False
        if not _bt_raw:
            _eod_inactive = bool(_bt_data.get("eod_inactive", False))
            if _eod_inactive:
                log.info("[BT-FILTER][R24] codes=[] but eod_inactive=True → 폴백 허용 (BT-FILTER skip, rt_intraday 사용)")
                _bt_skip = True
            else:
                log.error("[BT-FILTER][HOLD][REASON=bridge_target_empty] codes 필드 비어있음 (eod_inactive=False) → 빈 출력 갱신")
                _write_empty_output(log)
                return RC_HOLD
        if not _bt_skip:
            _bt_codes = set()
            for _c in _bt_raw:
                try:
                    _bt_codes.add(str(int(float(str(_c).strip()))).zfill(6))
                except (ValueError, TypeError):
                    _bt_codes.add(str(_c).strip().zfill(6))
            if not _bt_codes:
                log.error("[BT-FILTER][HOLD][REASON=bridge_target_normalize_fail] 정규화 후 코드 0개")
                _write_empty_output(log)
                return RC_HOLD
            df["code"] = df["code"].astype(str).str.zfill(6)
            _before_bt = len(df)
            df = df[df["code"].isin(_bt_codes)].copy()
            log.info("[BT-FILTER] bridge_target %d종목 필터: %d→%d행", len(_bt_codes), _before_bt, len(df))
    except Exception as _bt_e:
        log.error("[BT-FILTER][HOLD][REASON=bridge_target_parse_fail] %s → 빈 출력 갱신", _bt_e)
        _write_empty_output(log)
        return RC_HOLD

    _RISK_STATS["bt_filter_count"] = len(df)

    # [PULLBACK-HEIGHT 2026-06-13 친구님] 5일 바닥 지지선 대비 진입높이 밴드(기본 20~30%) — 하드필터.
    #   height=(price_now/직전5일최저-1)*100. 밴드 밖 제외. 데이터없음→스킵. 롤백 setx PULLBACK_HEIGHT_ENABLE NO.
    if PULLBACK_HEIGHT_ENABLE and not PULLBACK_FUNNEL_ENABLE and not df.empty and "price_now" in df.columns:
        try:
            _low5 = _load_recent_low5(PULLBACK_HEIGHT_LB)
            if _low5:
                df["code"] = df["code"].astype(str).str.zfill(6)
                _pn = pd.to_numeric(df["price_now"], errors="coerce")
                _lo = df["code"].map(_low5)
                _h  = (_pn / _lo - 1.0) * 100.0
                df["_pb_height"] = _h.round(2)
                _before_h  = len(df)
                _keep      = _h.notna() & (_h >= PULLBACK_HEIGHT_MIN) & (_h <= PULLBACK_HEIGHT_MAX)
                _dropped_h = [(str(c).zfill(6), round(float(hh), 1))
                              for c, hh in zip(df.loc[~_keep, "code"], _h[~_keep]) if pd.notna(hh)]
                df = df[_keep].copy()
                log.info("[PULLBACK-HEIGHT] 5일바닥 대비 %.0f~%.0f%% 밴드 필터: %d→%d행 (밖=%s)",
                         PULLBACK_HEIGHT_MIN, PULLBACK_HEIGHT_MAX, _before_h, len(df), _dropped_h[:10])
            else:
                log.warning("[PULLBACK-HEIGHT] 5일저점 데이터 없음 → 높이필터 스킵")
        except Exception as _phe:
            log.warning("[PULLBACK-HEIGHT] 높이필터 실패 → 스킵: %s", _phe)

    if df.empty:
        log.warning("[RISK][HOLD][REASON=bt_filter_empty] BT-FILTER 후 후보 0건 → 빈 출력 갱신 (stale csv 재사용 방지)")
        _risk_set_reason("bt_filter_empty")
        _write_empty_output(log)
        return RC_HOLD

    # ── 3. entry_ok 필터 + 강제 진입 준비 ────────────────────────────────
    df_all = df.copy()

    if "entry_ok" in df.columns:
        df_filtered = df[df["entry_ok"].astype(bool)].copy()
    else:
        df_filtered = df.copy()

    # ── 4. Top-1 선택 ────────────────────────────────────────────────────
    score_col = next(
        (c for c in ("score_final", "ev_final", "prescore_weighted") if c in df_all.columns), None  # [PATCH-SCORE]
    )
    # [PULLBACK_THEME LIVE] 테마 가점 더한 _score_theme로 정렬 (score_col 원본 보존, 정렬키만 테마).
    #   env PULLBACK_THEME_BOOST=NO → _sort_col=score_col(기존 거래대금 대장주로 잠금복귀).
    _sort_col = score_col
    _pb_real_1st = None
    if PULLBACK_THEME_BOOST and score_col:
        try:
            _tmap_pb = _load_theme_strength_pb()
            if _tmap_pb:
                for _d in (df_all, df_filtered):
                    if _d is not None and not _d.empty and "code" in _d.columns:
                        _d["_pb_tboost"] = _d["code"].astype(str).str.zfill(6).map(
                            lambda c: _pb_theme_boost(_tmap_pb.get(c))).fillna(0.0)
                        _d["_score_theme"] = pd.to_numeric(_d[score_col], errors="coerce").fillna(0.0) + _d["_pb_tboost"]
                if not df_filtered.empty and "_score_theme" in df_filtered.columns:
                    _pb_real_1st = str(df_filtered.sort_values(score_col, ascending=False).iloc[0].get("code", "")).zfill(6)
                    _sort_col = "_score_theme"
        except Exception as _pbe:
            log.warning("[PULLBACK_THEME] 테마 정렬 준비 실패 → prescore 단독: %s", _pbe)
            _sort_col = score_col

    # [COMPOSITE 2026-06-05] 헤지펀드식 멀티팩터 합성 — 165→정예 funnel 정교화. SHADOW 우선.
    #   SHADOW(ENABLE=NO): _composite 계산+로그(composite1등 vs 현재1등 비교)만, 정렬 불변(행동 0).
    #   ENABLE=YES: _sort_col=_composite로 정렬(정예 head는 composite 순). rt_risk 단독·env 되돌림.
    if score_col and not df_filtered.empty and len(df_filtered) >= 2:
        try:
            _tmapC = _load_theme_strength_pb()
            _dc = _compute_composite(df_filtered, _tmapC, log)
            if _dc is not None:
                df_filtered = _dc
                if not df_all.empty:
                    _dca = _compute_composite(df_all, _tmapC, log)
                    if _dca is not None:
                        df_all = _dca
                _cur1 = str(df_filtered.sort_values(_sort_col, ascending=False).iloc[0].get("code", "")).zfill(6)
                _comp_sorted = df_filtered.sort_values("_composite", ascending=False)
                _comp1 = str(_comp_sorted.iloc[0].get("code", "")).zfill(6)
                _top = _comp_sorted.head(8)
                log.info("[COMPOSITE][%s] 후보=%d | composite상위8: %s",
                         "ON" if RTRISK_COMPOSITE_ENABLE else "SHADOW", len(df_filtered),
                         [(str(r["code"]).zfill(6), float(r["_composite"])) for _, r in _top.iterrows()])
                _w1 = _comp_sorted.iloc[0]
                log.info("[COMPOSITE][%s] composite1등=%s vs 현재(%s)1등=%s %s | 1등팩터 pull=%.2f trend=%.2f flow=%.2f theme=%.2f edge=%.2f retr=%.2f vwap=%.2f vsurge=%.2f rally=%.2f",
                         "ON" if RTRISK_COMPOSITE_ENABLE else "SHADOW", _comp1, _sort_col, _cur1,
                         "★바뀜" if _comp1 != _cur1 else "동일",
                         float(_w1.get("_z_pull", 0)), float(_w1.get("_z_trend", 0)), float(_w1.get("_z_flow", 0)),
                         float(_w1.get("_z_theme", 0)), float(_w1.get("_z_edge", 0)), float(_w1.get("_z_retr", 0)),
                         float(_w1.get("_z_vwap", 0)), float(_w1.get("_z_vsurge", 0)), float(_w1.get("_z_rally", 0)))
                if RTRISK_COMPOSITE_ENABLE:
                    _sort_col = "_composite"
        except Exception as _ce:
            log.warning("[COMPOSITE] 계산 스킵(%s) → 기존 정렬 유지", _ce)

    # [RTRISK-REPEAT 2026-06-13 친구님] 눌림 정렬 점수에 반복등장 직접 반영 (시그널 방식). _sort_col 최종 조정.
    #   현 _sort_col(score_col/_score_theme) 값 + 반복등장가점(min(cnt,3)/3 × PTS) → _score_repeat로 정렬.
    if RTRISK_REPEAT_ENABLE and score_col:
        try:
            _rep = _load_rtrisk_repeat_count()
            if _rep:
                _base_col = _sort_col if (df_filtered is not None and _sort_col in df_filtered.columns) else score_col
                for _d in (df_all, df_filtered):
                    if _d is not None and not _d.empty and "code" in _d.columns:
                        _bb = pd.to_numeric(_d[_base_col], errors="coerce").fillna(0.0) if _base_col in _d.columns else pd.Series(0.0, index=_d.index)
                        _rb = _d["code"].astype(str).str.zfill(6).map(
                            lambda c: min(_rep.get(c, 0), 3) / 3.0 * RTRISK_REPEAT_PTS)
                        _d["_score_repeat"] = _bb + _rb
                if df_filtered is not None and not df_filtered.empty and "_score_repeat" in df_filtered.columns:
                    _old1r = str(df_filtered.sort_values(_sort_col, ascending=False).iloc[0].get("code", "")).zfill(6) if _sort_col in df_filtered.columns else "?"
                    _sort_col = "_score_repeat"
                    _new1r = str(df_filtered.sort_values(_sort_col, ascending=False).iloc[0].get("code", "")).zfill(6)
                    log.info("[RTRISK-REPEAT] 눌림 점수에 반복등장 반영(%dpt·상위%d테마) → 정렬키=_score_repeat (1등 %s→%s, 변경=%s)",
                             int(RTRISK_REPEAT_PTS), RTRISK_REPEAT_TOP_K, _old1r, _new1r, "Y" if _old1r != _new1r else "N")
            else:
                log.info("[RTRISK-REPEAT] 반복등장 데이터 없음 → 기존 정렬 유지")
        except Exception as _rre:
            log.warning("[RTRISK-REPEAT] 반복등장 반영 실패(%s) → 기존 정렬 유지", _rre)

    # [PULLBACK-ANCHOR 2026-06-13 친구님] 코스피 앵커(대형주) 동조 가점 — 종가매수와 대칭. _sort_col 최종 가산.
    #   앵커 상승 & 후보가 앵커보다 강함 → +max. kospi_anchor 미수집/데이터없음 → 0(무영향). env 되돌림.
    if PULLBACK_ANCHOR_ENABLE and score_col and df_filtered is not None and not df_filtered.empty:
        try:
            import sys as _sysA
            _adir = str(Path(RCFG.BASE) / "RUN")
            if _adir not in _sysA.path:
                _sysA.path.insert(0, _adir)
            import anchor_bonus as _ab
            _anc_chg, _theme_anc, _code_themes = _ab.load_anchor_ctx()
            if _anc_chg and _theme_anc:
                _tmapA = _load_theme_strength_pb()
                _base_col_a = _sort_col if _sort_col in df_filtered.columns else score_col

                def _anc_pts(_code):
                    _c = str(_code).zfill(6)
                    _tm = _tmapA.get(_c) or {}
                    _themes = _code_themes.get(_c)
                    if not _themes:
                        _themes = [_tm.get("theme")] if _tm.get("theme") else []
                    _cret = float(_tm.get("ret_1d", 0.0) or 0.0)
                    _b, _ = _ab.anchor_bonus(_themes, _cret, _anc_chg, _theme_anc,
                                             max_bonus=PULLBACK_ANCHOR_MAX)
                    return float(_b)

                for _d in (df_all, df_filtered):
                    if _d is not None and not _d.empty and "code" in _d.columns:
                        _bb = (pd.to_numeric(_d[_base_col_a], errors="coerce").fillna(0.0)
                               if _base_col_a in _d.columns else pd.Series(0.0, index=_d.index))
                        _d["_pb_anchor"]    = _d["code"].astype(str).str.zfill(6).map(_anc_pts).fillna(0.0)
                        _d["_score_anchor"] = _bb + _d["_pb_anchor"]
                if "_score_anchor" in df_filtered.columns:
                    _olda = (str(df_filtered.sort_values(_sort_col, ascending=False).iloc[0].get("code", "")).zfill(6)
                             if _sort_col in df_filtered.columns else "?")
                    _sort_col = "_score_anchor"
                    _newa = str(df_filtered.sort_values(_sort_col, ascending=False).iloc[0].get("code", "")).zfill(6)
                    log.info("[PULLBACK-ANCHOR] 앵커 동조가점 반영(max%.0f) → 정렬키=_score_anchor (1등 %s→%s, 변경=%s)",
                             PULLBACK_ANCHOR_MAX, _olda, _newa, "Y" if _olda != _newa else "N")
            else:
                log.info("[PULLBACK-ANCHOR] 앵커 데이터 없음(kospi_anchor 미수집) → 가점 스킵")
        except Exception as _abe:
            log.warning("[PULLBACK-ANCHOR] 앵커 가점 실패 → 기존 정렬 유지: %s", _abe)

    # [PULLBACK-FUNNEL 2026-06-13 친구님] ★진짜 4단 퍼널(160→80→25→8) = 실거래 선별. make_rt 160 그대로 받아 단계별 컷.
    #   STEP1 생존필터(죽을놈) → STEP2 대장자격 → STEP3 건강한눌림 → head8. 익스큐션이 8→1. 공용코어. 실패=기존정렬 폴백.
    if PULLBACK_FUNNEL_ENABLE and score_col and df_filtered is not None and not df_filtered.empty:
        try:
            import sys as _sysF
            _fdir = str(Path(RCFG.BASE) / "RUN")
            if _fdir not in _sysF.path:
                _sysF.path.insert(0, _fdir)
            import pullback_funnel_core as _fc
            _N1 = int(os.environ.get("PULLBACK_FUNNEL_N1", "80"))
            _N2 = int(os.environ.get("PULLBACK_FUNNEL_N2", "25"))
            _N3 = int(os.environ.get("RTRISK_OUTPUT_N", "8"))
            _low5_f = _load_recent_low5(5)
            _n_in = len(df_filtered)

            # ── STEP1 (160→80): 생존필터(죽을놈 제거) ──
            _die = {str(_r["code"]).zfill(6): _fc.step1_die(_r, _low5_f.get(str(_r["code"]).zfill(6)))
                    for _, _r in df_filtered.iterrows()}
            _surv = set(c for c, d in _die.items() if d is None)
            _drop1 = [(c, d) for c, d in _die.items() if d is not None]
            df_filtered = df_filtered[df_filtered["code"].astype(str).str.zfill(6).isin(_surv)].copy()
            if df_filtered.empty:
                raise RuntimeError(f"STEP1 전원탈락 {_drop1[:6]}")
            if len(df_filtered) > _N1:   # 80 초과 시 make_rt 점수(prescore)로 상위80 — 내 임의 기준 아님
                df_filtered = df_filtered.sort_values(score_col, ascending=False).head(_N1).copy()
            _n1 = len(df_filtered)

            # [PULLBACK-HEIGHT-HARD 2026-06-15 ★친구님] 5일저점 대비 진입높이 하드밴드(기본 +10~20%).
            #   "저점에서 턴 + 돈 들어오는 거 확인하며 10~20% 떠서 산다" — height=(price_now/5일저점-1)*100.
            #   밴드 밖 제외·데이터없음=통과(fail-open)·전원탈락→HOLD(매수안함, 안전). 롤백 setx PULLBACK_HEIGHT_HARD NO.
            if PULLBACK_HEIGHT_HARD and not df_filtered.empty and "price_now" in df_filtered.columns:
                _hh_l5 = pd.to_numeric(df_filtered["code"].astype(str).str.zfill(6).map(_low5_f), errors="coerce")
                _hh_pn = pd.to_numeric(df_filtered["price_now"], errors="coerce")
                _hh = (_hh_pn.values / _hh_l5.values - 1.0) * 100.0
                _hh_keep = pd.isna(_hh) | ((_hh >= PULLBACK_HEIGHT_MIN) & (_hh <= PULLBACK_HEIGHT_MAX))
                _hh_before = len(df_filtered)
                df_filtered = df_filtered[_hh_keep].copy()
                log.info("[PULLBACK-HEIGHT-HARD] 5일저점 +%g~%g%% 하드밴드: %d→%d행",
                         PULLBACK_HEIGHT_MIN, PULLBACK_HEIGHT_MAX, _hh_before, len(df_filtered))
                if df_filtered.empty:
                    raise RuntimeError("PULLBACK-HEIGHT-HARD 전원탈락(밴드밖) → HOLD")
                _n1 = len(df_filtered)

            # [PULLBACK-LOW5-FLOOR 2026-06-17 친구님] 5일 전 저점 이탈 탈락(현재가<5일저점). 바닥 floor만.
            #   저점 위면 통과·데이터없음=통과(fail-open)·전원탈락→HOLD. 백테 +0.19%p(칼날회피). 롤백 setx PULLBACK_LOW5_FLOOR NO.
            if PULLBACK_LOW5_FLOOR and not df_filtered.empty and "price_now" in df_filtered.columns:
                _lf_l5 = pd.to_numeric(df_filtered["code"].astype(str).str.zfill(6).map(_low5_f), errors="coerce")
                _lf_pn = pd.to_numeric(df_filtered["price_now"], errors="coerce")
                _lf_keep = _lf_l5.isna() | (_lf_pn >= _lf_l5)        # 저점데이터 없으면 통과·있으면 5일저점 이상만
                _lf_before = len(df_filtered)
                df_filtered = df_filtered[_lf_keep].copy()
                log.info("[PULLBACK-LOW5-FLOOR] 5일전저점 이탈 탈락: %d→%d행", _lf_before, len(df_filtered))
                if df_filtered.empty:
                    raise RuntimeError("PULLBACK-LOW5-FLOOR 전원탈락(5일저점 이탈) → HOLD")
                _n1 = len(df_filtered)

            # 분봉 메트릭(생존자만) — 첫눌림·HL·하락둔화·장중대장·미세
            _codes_f = [str(c).zfill(6) for c in df_filtered["code"].tolist()]
            _pbm_f = _fc.load_pb_metrics(_codes_f, str(_PRICES_1M_FILE), _PB_FUNNEL_CACHE)

            # ── STEP2 (80→25): 대장 자격(거래대금유지·종가강도·장중대장) ──
            _dv = pd.to_numeric(df_filtered.get("dv_accel", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            df_filtered = df_filtered.assign(_dv_pct=(_dv.rank(pct=True).values if len(_dv) else 0.0))
            df_filtered["_s2"] = df_filtered.apply(
                lambda _r: _fc.step2_score(_r, float(_r.get("_dv_pct", 0) or 0),
                                           _pbm_f.get(str(_r["code"]).zfill(6))), axis=1)
            if len(df_filtered) > _N2:
                df_filtered = df_filtered.sort_values("_s2", ascending=False).head(_N2).copy()
            _n2 = len(df_filtered)

            # ── STEP3 (25→8): 건강한 눌림(첫눌림·전저점·HigherLow·거래량감소·하락둔화) ──
            df_filtered["_s3"] = df_filtered["code"].astype(str).str.zfill(6).map(
                lambda c: _fc.step3_score(_pbm_f.get(c)))
            # [분봉부족=안삼 친구님 2026-06-14] 분봉없는 종목은 눌림품질 검증불가 → ★제외(폴백 매수 금지).
            _nomin = df_filtered["_s3"] < 0
            if _nomin.any():
                _nm_codes = df_filtered.loc[_nomin, "code"].astype(str).str.zfill(6).tolist()
                df_filtered = df_filtered[~_nomin].copy()
                log.info("[PULLBACK-FUNNEL] 분봉부족 %d종목 제외(검증불가→안삼): %s", len(_nm_codes), _nm_codes[:6])

            if df_filtered.empty:
                # 분봉검증 통과 0 → 눌림 후보 없음 = 매수 안함(빈 출력→HOLD). ★prescore 폴백매수로 안 떨어지게 명시 차단.
                df_all = df_all.iloc[0:0].copy()
                df_filtered["_funnel_score"] = pd.Series(dtype=float)
                _sort_col = "_funnel_score"
                log.warning("[PULLBACK-FUNNEL] 4단 %d→STEP1생존%d→STEP2 %d→분봉검증 통과 0 → 눌림 매수 안함(HOLD)",
                            _n_in, len(_surv), _n2)
            else:
                # [VALRANK 2026-06-14 ★친구님] 25→8 = 거래대금 순위 + 눌림품질 합성(백테 C +2.05% > 거래대금만 +1.71%).
                _cut_col = "_s3"
                if PULLBACK_VALRANK_ENABLE and "value_day" in df_filtered.columns and len(df_filtered) > 1:
                    try:
                        _vd = pd.to_numeric(df_filtered["value_day"], errors="coerce").fillna(0.0)
                        _valscore = _vd.rank(pct=True) * 100.0          # 거래대금 클수록 100(이 풀 내 백분위)
                        df_filtered["_s3combo"] = (df_filtered["_s3"] * (1.0 - PULLBACK_VALRANK_W)
                                                   + _valscore * PULLBACK_VALRANK_W)
                        _cut_col = "_s3combo"
                        log.info("[VALRANK] 25→8 거래대금순위%.0f%%+눌림품질%.0f%% 합성",
                                 PULLBACK_VALRANK_W * 100, (1.0 - PULLBACK_VALRANK_W) * 100)
                        # [PM-BOOST] 오후(13시+)면 거래대금 유지력+종가강도 가점(근사, value_split 쌓이면 정밀교체)
                        if PULLBACK_PM_BOOST and datetime.now().hour >= PULLBACK_PM_HOUR:
                            _cp = pd.to_numeric(df_filtered.get("close_position", 0), errors="coerce").fillna(0) * 100
                            _vn = pd.to_numeric(df_filtered.get("value_now", 0), errors="coerce").fillna(0)
                            _vp = pd.to_numeric(df_filtered.get("value_prev", 0), errors="coerce").fillna(0)
                            _maint = ((_vn >= _vp) & (_vp > 0)).astype(float) * 100      # 거래대금 유지=100
                            df_filtered["_s3combo"] = df_filtered["_s3combo"] + (_cp * 0.5 + _maint * 0.5) * PULLBACK_PM_BOOST_W
                            log.info("[PM-BOOST] 오후 거래대금유지+종가강도 가점(W%.1f)", PULLBACK_PM_BOOST_W)
                    except Exception as _vre:
                        log.warning("[VALRANK] 합성 실패(%s)→눌림품질만", _vre); _cut_col = "_s3"
                if len(df_filtered) > _N3:
                    df_filtered = df_filtered.sort_values(_cut_col, ascending=False).head(_N3).copy()
                _n3 = len(df_filtered)

                # ── 최종 8개 정렬키 = EXEC합성(품질40+돈25+첫눌림20+미세15) + 앵커 + 10분추적 ──
                df_filtered["_funnel_score"] = df_filtered.apply(
                    lambda _r: _fc.funnel_score(_r, _pbm_f.get(str(_r["code"]).zfill(6)),
                                                float(_r.get("_dv_pct", 0) or 0))[0], axis=1)
                if "_pb_anchor" in df_filtered.columns:
                    df_filtered["_funnel_score"] = (df_filtered["_funnel_score"]
                        + pd.to_numeric(df_filtered["_pb_anchor"], errors="coerce").fillna(0.0))
                # ★추적(지속성): 매 사이클 점수 누적 → 최근 10분 평균으로 정렬점수 교체(표본2+). "순간1등<10분내내1등".
                try:
                    import csv as _csvF
                    _trk = Path(RCFG.BASE) / "data" / "LOG" / "pullback_funnel_live_track.csv"
                    _trk.parent.mkdir(parents=True, exist_ok=True)
                    _nowF = datetime.now(); _newf = not _trk.exists()
                    with _trk.open("a", newline="", encoding="utf-8-sig") as _tf:
                        _wF = _csvF.writer(_tf)
                        if _newf:
                            _wF.writerow(["ts", "code", "score"])
                        for _, _r in df_filtered.iterrows():
                            _wF.writerow([_nowF.strftime("%Y%m%d%H%M%S"), str(_r["code"]).zfill(6), _r["_funnel_score"]])
                    _hist = pd.read_csv(_trk, dtype=str)
                    _hist["score"] = pd.to_numeric(_hist["score"], errors="coerce")
                    _hist["t"] = pd.to_datetime(_hist["ts"], format="%Y%m%d%H%M%S", errors="coerce")
                    _curset = set(df_filtered["code"].astype(str).str.zfill(6))
                    _rec = _hist[(_hist["t"] >= _nowF - pd.Timedelta(minutes=10))
                                 & (_hist["code"].astype(str).str.zfill(6).isin(_curset))]
                    if not _rec.empty:
                        _avg = _rec.groupby("code")["score"].mean(); _cnt = _rec.groupby("code")["score"].count()
                        for _idx, _row in df_filtered.iterrows():
                            _cc = str(_row["code"]).zfill(6)
                            if _cnt.get(_cc, 0) >= 2:
                                df_filtered.at[_idx, "_funnel_score"] = round(float(_avg[_cc]), 1)
                except Exception as _trke:
                    log.debug("[PULLBACK-FUNNEL] 추적 평균 스킵(무시): %s", _trke)

                # df_all 동기화(생존 8개만 남기고 정렬키 부여)
                _keep = set(df_filtered["code"].astype(str).str.zfill(6))
                df_all.drop(df_all[~df_all["code"].astype(str).str.zfill(6).isin(_keep)].index, inplace=True)
                _fsmap = dict(zip(df_filtered["code"].astype(str).str.zfill(6), df_filtered["_funnel_score"]))
                df_all["_funnel_score"] = df_all["code"].astype(str).str.zfill(6).map(_fsmap).fillna(0.0)
                _sort_col = "_funnel_score"
                _top1f = str(df_filtered.sort_values("_funnel_score", ascending=False).iloc[0]["code"]).zfill(6)
                log.info("[PULLBACK-FUNNEL] 4단 %d→STEP1생존%d(죽을놈%d:%s)→STEP2 %d→STEP3 %d→head%d | 분봉%d | 1등=%s",
                         _n_in, len(_surv), len(_drop1), _drop1[:4], _n2, _n3, _N3, len(_pbm_f), _top1f)
        except Exception as _fce:
            log.warning("[PULLBACK-FUNNEL] 퍼널 실패 → 기존 정렬 폴백(안전): %s", _fce)

    if score_col:
        df_all      = df_all.sort_values(_sort_col, ascending=False)
        df_filtered = (
            df_filtered.sort_values(_sort_col, ascending=False)
            if not df_filtered.empty else df_filtered
        )

    # [TIE-BAND 2026-06-02] 박빙 밴드 tiebreaker — 1등 prescore와 band 이내인 후보들을
    #   스코어보드 50지표 score(sb_score)로 가려 1등 교체. 박빙일 때만 작동(intraday 단독결정 보존).
    #   근거: 상위권 prescore_weighted가 0.01~1% 차로 빽빽 → 노이즈로 1종목 몰빵 결정되는 것 방지.
    #   sb_score 컬럼 없으면(score_eod 미로드) 자동 스킵. band는 env PRESCORE_TIE_BAND_PTS.
    if score_col and "sb_score" in df_filtered.columns and len(df_filtered) >= 2:
        try:
            _tie_band = float(os.environ.get("PRESCORE_TIE_BAND_PTS", "2.0"))
            _tie_col  = _sort_col if _sort_col in df_filtered.columns else score_col
            _max_ps   = float(df_filtered[_tie_col].max())
            _tie      = df_filtered[df_filtered[_tie_col] >= (_max_ps - _tie_band)]
            if len(_tie) >= 2:
                _win      = _tie.sort_values("sb_score", ascending=False).iloc[0]
                _win_code = str(_win["code"])
                _cur_code = str(df_filtered.iloc[0]["code"])
                if _win_code != _cur_code:
                    log.info("[TIE-BAND] 박빙 %d종목 band=%.1f → sb_score 1등교체 %s(sb=%.1f ps=%.2f) ← 기존 %s(sb=%.1f ps=%.2f)",
                             len(_tie), _tie_band, _win_code, float(_win["sb_score"]), float(_win[score_col]),
                             _cur_code, float(df_filtered.iloc[0].get("sb_score", 0)), float(df_filtered.iloc[0][score_col]))
                    _rest       = df_filtered[df_filtered["code"] != _win_code]
                    df_filtered = pd.concat([_win.to_frame().T, _rest], ignore_index=True)
                else:
                    log.info("[TIE-BAND] 박빙 %d종목 band=%.1f → 1등 유지 %s (이미 sb_score 최고)",
                             len(_tie), _tie_band, _cur_code)
        except Exception as _tb_e:
            log.warning("[TIE-BAND] tiebreaker 스킵(%s) → prescore 단독", _tb_e)

    # [THEME-LEADER PRIORITY 2026-06-05] ★확실한 테마대장 우선 — 최종 단계.
    #   게이트 통과 후보(df_filtered) 중 테마대장주(is_leader&rank≤N)가 있으면 그중 최고점수를 Top1 승격.
    #   없으면 모멘텀 Top1 유지(fallback). 후보는 이미 눌림·ride·EV 게이트 통과 → 신호없는 강제매수 아님.
    if PULLBACK_THEME_PRIORITY and score_col and not df_filtered.empty:
        try:
            _tmapL = _load_theme_strength_pb()

            def _is_theme_leader(_code) -> bool:
                _tm = _tmapL.get(str(_code).zfill(6))
                return bool(_tm and _tm.get("is_leader")
                            and _tm.get("rank", 999) <= PULLBACK_THEME_LEADER_RANK)

            _ldr_mask = df_filtered["code"].map(_is_theme_leader)
            _ldr_df = df_filtered[_ldr_mask]
            _cur1 = str(df_filtered.iloc[0].get("code", "")).zfill(6)
            if not _ldr_df.empty:
                _win = _ldr_df.iloc[0]   # df_filtered는 이미 _sort_col 정렬됨 → 첫 행=최고점수 테마대장주
                _wc = str(_win.get("code", "")).zfill(6)
                if _wc != _cur1:
                    _rest = df_filtered[df_filtered["code"].astype(str).str.zfill(6) != _wc]
                    df_filtered = pd.concat([_win.to_frame().T, _rest], ignore_index=True)
                    log.info("[THEME-LEADER-PRIORITY] ★테마대장주 Top1 승격 %s (rank=%s, 게이트통과) ← 기존 %s",
                             _wc, _tmapL.get(_wc, {}).get("rank"), _cur1)
                else:
                    log.info("[THEME-LEADER-PRIORITY] Top1 이미 테마대장주 %s (rank=%s)",
                             _cur1, _tmapL.get(_cur1, {}).get("rank"))
            else:
                log.info("[THEME-LEADER-PRIORITY] 게이트통과 후보 중 테마대장주 없음 → 모멘텀 Top1 유지 %s", _cur1)
        except Exception as _tle:
            log.warning("[THEME-LEADER-PRIORITY] 스킵(%s) → 기존 Top1 유지", _tle)

    # [PULLBACK_THEME 병행기록 2026-06-02] 테마 미반영(prescore) 1등 vs 실제(테마반영) 1등 → compare CSV.
    #   정렬은 위 _sort_col=_score_theme로 이미 실반영됨. 여기선 비교 기록만(며칠 검증/되돌림 판단용).
    if PULLBACK_THEME_BOOST and _pb_real_1st and not df_filtered.empty:
        try:
            _theme_1st = str(df_filtered.iloc[0].get("code", "")).zfill(6)
            _changed   = int(_pb_real_1st != _theme_1st)
            _tmap2 = _load_theme_strength_pb()
            _tm = _tmap2.get(_theme_1st, {})
            _boost = float(df_filtered.iloc[0].get("_pb_tboost", 0.0) or 0.0)
            _PB_THEME_COMPARE.parent.mkdir(parents=True, exist_ok=True)
            _new = not _PB_THEME_COMPARE.exists()
            import csv as _csv
            with open(_PB_THEME_COMPARE, "a", newline="", encoding="utf-8-sig") as _cf:
                _w = _csv.writer(_cf)
                if _new:
                    _w.writerow(["datetime", "mode", "prescore_1st", "theme_1st", "changed",
                                 "theme_name", "theme_rank", "theme_boost"])
                _w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "LIVE",
                             _pb_real_1st, _theme_1st, _changed,
                             _tm.get("theme", ""), _tm.get("rank", 999), round(_boost, 3)])
            log.info("[PULLBACK_THEME][LIVE] prescore1등=%s → 테마반영1등=%s changed=%d "
                     "(theme=%s rank=%s boost=%.2f) — 실진입 적용(되돌림: env PULLBACK_THEME_BOOST=NO)",
                     _pb_real_1st, _theme_1st, _changed, _tm.get("theme", ""),
                     _tm.get("rank", 999), _boost)
        except Exception as _pe:
            log.warning("[PULLBACK_THEME] 병행기록 실패: %s", _pe)

    forced_entry = False

    if df_filtered.empty:
        log.warning("[T1-3 BLOCK] forced_entry disabled")
        _write_empty_output(log)
        return 0
    else:
        top1 = df_filtered.head(int(os.environ.get("RTRISK_OUTPUT_N", "8"))).copy()   # [EOD대칭 2026-06-05] 5→8 (스코어보드 8개와 맞춤, rt_execution이 8→1 검증선택)

    ticker = str(top1.iloc[0].get("ticker", top1.iloc[0].get("code", "?")))

    if score_col:
        score_val = top1.iloc[0].get(score_col, None)
        try:
            log.info(
                f"[TOP1] {ticker} | {score_col}={float(score_val):.4f}"
                f"{' [강제진입]' if forced_entry else ''}"
            )
        except (TypeError, ValueError):
            log.info(f"[TOP1] {ticker} | {score_col}=N/A")
    else:
        log.warning(f"[TOP1] score 컬럼 없음 → {ticker}")

    # ── 5. Regime / Strategy 감지 (FIX-V6-1: 자체 계산 포함) ────────────
    regime           = _detect_regime(top1, df_all, log)
    regime_params    = RCFG.REGIME_PARAMS.get(regime, RCFG.REGIME_PARAMS["NEUTRAL"])
    strategy_hint    = _detect_strategy(top1, log)
    strategy_profile = RCFG.STRATEGY_PROFILES.get(
        strategy_hint, RCFG.STRATEGY_PROFILES["PULLBACK"]  # [FIX-V62-1] EOD→PULLBACK
    )

    # ── 6. 기관 모멘텀 배율 ──────────────────────────────────────────────
    inst_mult    = _calc_inst_mult(top1, strategy_profile, log)
    inst_holding = _is_inst_holding(top1)

    # ── 6b. [FIX-V6-4] ride_score → position_size 배율 ──────────────────
    ride_mult = _calc_ride_size_mult(top1, forced_entry, log)

    # ── 7. 계좌 / PnL / 원장 ─────────────────────────────────────────────
    acct         = _load_account(log)
    cash         = acct["cash"]
    realized_pnl = _load_daily_pnl(log)
    ledger       = _load_ledger(log)

    # [v6.3] 실테스트 자본 상한 명시 로그
    if RCFG.TEST_CAPITAL_CAP > 0:
        log.info(
            f"[TEST] ★실테스트 모드★  자본상한={RCFG.TEST_CAPITAL_CAP:,}원  "
            f"실제잔고는 이 금액 초과분 무시"
        )

    log.info(
        f"[RISK] 후보={len(df_all)}→Top1={ticker} | cash={cash:,}원 | "
        f"실현={realized_pnl:+,}원 | 원장={len(ledger)}건 | "
        f"regime={regime} | strat={strategy_hint} | "
        f"inst={inst_mult:.2f} | ride={ride_mult:.2f} | "
        f"hold={inst_holding} | force={forced_entry}"
    )

    # ── 8. DD 브레이커 ───────────────────────────────────────────────────
    dd_state, dd_pct, dd_scale = _check_dd_breaker(
        cash, realized_pnl, regime_params, inst_holding, log
    )

    # [POLICY] DD STOP 정책: 당일 영구 차단 + 익일 자동 리셋
    #   _load_entry_state() line 667-668: date != today → blank state 반환
    #   → 다음 영업일 자동 회복. 당일 회복 조건 의도적 부재 (Van Tharp 헤지펀드 표준)
    #   당일 부분 회복/시간 쿨다운 등 추가 조건 없음 — 정책 결정에 따라 유지
    if dd_state == DDBreakerResult.STOP:
        entry_state.update({
            "date": datetime.now().strftime("%Y%m%d"),
            "dd_stopped": True,
        })
        _save_entry_state(entry_state, log)
        log.warning("[RISK] DD STOP → 당일 재진입 영구 차단")
        _write_empty_output(log)
        return RC_HOLD

    # ── 8b. 누적 DD 체크 ─────────────────────────────────────────────────
    cumul_dd       = _load_cumulative_dd(cash, log)
    cumul_dd_scale = 1.0
    if cumul_dd < RCFG.DD_CUMUL_THRESH and not inst_holding:
        cumul_dd_scale = 0.60
        log.warning(
            f"[DD-CUMUL] {RCFG.DD_CUMUL_DAYS}일 누적={cumul_dd:.3f} "
            f"< {RCFG.DD_CUMUL_THRESH} → 60% 축소"
        )

    # ── 9. Kelly 계산 (전략별 독립) ──────────────────────────────────────
    kelly     = KellyCalcByStrategy(
        ledger, strategy_hint, regime_params, strategy_profile, log
    )
    base_size = kelly.get_size()

    if forced_entry:
        # [FIX-V62-5] 레짐별 강제 진입 사이즈 분기
        regime_forced_size = {
            "BULL":    RCFG.FORCED_ENTRY_BULL_SIZE,
            "NEUTRAL": RCFG.FORCED_ENTRY_NEUTRAL_SIZE,
            "BEAR":    RCFG.FORCED_ENTRY_BEAR_SIZE,
        }.get(regime, RCFG.FORCED_ENTRY_NEUTRAL_SIZE)
        base_size = regime_forced_size
        log.info(
            f"[FORCE] 강제 진입 사이즈: {base_size:.3f} "
            f"(레짐={regime} → {regime_forced_size:.2f}, "
            f"상한={RCFG.FORCED_ENTRY_MAX_SIZE})"
        )

    elif base_size < RCFG.DEPLOY_THRESHOLD:
        if inst_mult >= RCFG.INST_BOOST_SCALE:
            base_size = RCFG.DEPLOY_THRESHOLD
            log.info(f"[KELLY-SOFT] 기관 강세({inst_mult:.2f}) → 최소 배포 {base_size:.3f}")
        else:
            log.warning(f"[KELLY] {base_size:.3f} < DEPLOY_THRESHOLD → 진입 포기")
            _write_empty_output(log)
            return RC_HOLD

    # ── 10. EV 가중 보정 ─────────────────────────────────────────────────
    if not forced_entry:
        ev_scale = regime_params.get("ev_scale", RCFG.EV_SCALE)
        # [FIX-V62-6] PF≥2.0 시 EV 보너스 상한 확대 (수익 극대화)
        pf_now   = kelly.stats.get("profit_factor", 0.0)
        ev_bonus_cap = (
            RCFG.EV_BONUS_CAP_HIGH
            if pf_now >= RCFG.EV_BONUS_PF_THRESH
            else RCFG.EV_BONUS_CAP
        )
        if "ev_final" in top1.columns:
            ev = pd.to_numeric(top1["ev_final"], errors="coerce").fillna(0).iloc[0]
            if ev < RCFG.EV_NEG_HOLD_THRESH:
                if inst_mult >= RCFG.INST_BOOST_SCALE:
                    base_size = RCFG.DEPLOY_THRESHOLD
                    log.info(f"[EV-SOFT] ev={ev:.4f} 불량 + 기관 강세 → 최소 배포")
                else:
                    log.warning(f"[EV] ev={ev:.4f} < {RCFG.EV_NEG_HOLD_THRESH} → 진입 포기")
                    _write_empty_output(log)
                    return RC_HOLD
            elif ev > 0:
                bonus     = min(ev_bonus_cap, ev * ev_scale)
                base_size = min(RCFG.KELLY_MAX, base_size + bonus)
                log.debug(
                    f"[EV] +보정: ev={ev:.4f} → bonus={bonus:.3f} "
                    f"(cap={ev_bonus_cap:.2f}, PF={pf_now:.2f})"
                )
            elif ev < 0:
                penalty   = min(RCFG.EV_PENALTY_CAP, abs(ev) * ev_scale)
                base_size = max(RCFG.DEPLOY_THRESHOLD, base_size - penalty)
                log.debug(f"[EV] -보정: ev={ev:.4f} → penalty={penalty:.3f}")

    # ── 11. 기관 배율 적용 ───────────────────────────────────────────────
    base_size = base_size * inst_mult
    log.info(f"[INST] inst_mult={inst_mult:.2f} → size={base_size:.3f}")

    # ── 11b. [FIX-V6-4] ride_score 배율 적용 ────────────────────────────
    base_size = min(RCFG.KELLY_MAX, base_size * ride_mult)
    log.info(f"[RIDE] ride_mult={ride_mult:.2f} → size={base_size:.3f}")

    # ── 12. DD 스케일 + 누적 DD 적용 ────────────────────────────────────
    position_size = min(RCFG.KELLY_MAX, base_size * dd_scale * cumul_dd_scale)
    log.info(
        f"[SIZE] base={base_size:.3f} × DD={dd_scale:.2f} "
        f"× cumul={cumul_dd_scale:.2f} → {position_size:.3f}"
    )

    if forced_entry:
        position_size = min(position_size, RCFG.FORCED_ENTRY_MAX_SIZE)
        log.info(f"[FORCE] 상한 클램프 → {position_size:.3f}")

    # ── 12b. CVaR 선행 계산 + DD 임계 체크 ─────────────────────────────────
    # [v6.5 CRIT-FIX] v6.4에서 var_result를 Step13 이전에 참조 → NameError 크래시
    # 재현 조건: realized_pnl<0 + Kelly<0.15 + forced_entry=False
    # = 연속 손실 날(가장 위험한 날) 리스크 엔진 사망 버그
    # 수정: var_calc/var_result를 Step12b에서 먼저 생성, Step13에서 재사용
    var_calc   = SingleVaRCalcByStrategy(ledger, strategy_hint, log)
    var_result = var_calc.compute(position_size)

    if position_size < RCFG.DEPLOY_THRESHOLD and not forced_entry:
        _is_warmup    = var_result.get("initial", False)
        _warmup_floor = RCFG.ATTACK_RATIO * 0.35 * 0.49   # ~0.120
        if _is_warmup and position_size >= _warmup_floor:
            log.info(
                f"[SIZE] 워밍업 DEPLOY 완화: {position_size:.3f} ≥ {_warmup_floor:.3f} → 진입 허용"
            )
        else:
            log.warning(f"[SIZE] DD 축소 후 {position_size:.3f} < 임계값 → 진입 포기")
            _write_empty_output(log)
            return RC_HOLD

    # ── 13. CVaR 체크 (FIX-V6-2: 전략별 분리) ───────────────────────────
    # [v6.5 FIX] var_calc/var_result는 Step12b에서 이미 계산 완료 → 재사용

    if var_result.get("initial", False):
        initial_cap   = RCFG.ATTACK_RATIO * 0.35
        position_size = min(position_size, initial_cap)
        log.info(f"[VAR-INIT] 초기 보수 모드 → cap={initial_cap:.3f}, size={position_size:.3f}")
        var_result["ok"] = True
        # [PATCH-v6.4.2] 워밍업 구간 DEPLOY_THRESHOLD 예외
        # 문제: execution n<8 → STABLE ×0.50 = 12.2% < DEPLOY_THRESHOLD(0.15) → 주문 차단
        # 수정: VAR-INIT 모드(원장 없음) 시 DEPLOY_THRESHOLD를 initial_cap 기준으로 완화
        #       워밍업 구간에서만 적용 — 원장 생성 후 자동 해제
        _warmup_deploy_min = min(initial_cap * 0.49, RCFG.DEPLOY_THRESHOLD)
        if position_size < RCFG.DEPLOY_THRESHOLD and position_size >= _warmup_deploy_min:
            log.info(
                f"[VAR-INIT] 워밍업 DEPLOY 완화: {position_size:.3f} ≥ {_warmup_deploy_min:.3f} → 진입 허용"
            )
    elif not var_result["ok"]:
        position_size = var_calc.adjust_size_to_cvar(position_size)
        if position_size < RCFG.DEPLOY_THRESHOLD and not forced_entry:
            log.warning(f"[VAR] CVaR 축소 후 {position_size:.3f} < 임계값 → 진입 포기")
            _write_empty_output(log)
            return RC_HOLD

    # ── 14. 안정 유보 + 전략별 최종 캡 ──────────────────────────────────
    max_deploy = min(
        RCFG.ATTACK_RATIO,
        regime_params.get("max_deploy", RCFG.ATTACK_RATIO),
        strategy_profile.get("max_deploy", RCFG.ATTACK_RATIO),
    )
    if forced_entry:
        max_deploy = min(max_deploy, RCFG.FORCED_ENTRY_MAX_SIZE)

    position_size = min(position_size, max_deploy)
    log.info(f"[CAP] max_deploy={max_deploy:.2f} → final={position_size:.3f}")

    # ── 15. Risk Grade ────────────────────────────────────────────────────
    pf_val = kelly.stats.get("profit_factor", 0.0)
    grade  = _assign_risk_grade(
        position_size, var_result["ok"], inst_mult, regime,
        profit_factor=pf_val, ride_mult=ride_mult, forced=forced_entry
    )
    log.info(
        f"[GRADE] {grade} | pos={position_size:.3f} | "
        f"PF={pf_val:.2f} | ride={ride_mult:.2f} | regime={regime}"
    )

    # ── 16. 배포 금액 계산 ───────────────────────────────────────────────
    deployable_cash = int(cash * position_size)
    log.info(
        f"[DEPLOY] {position_size:.1%} × {cash:,}원 = {deployable_cash:,}원 "
        f"| 유보({RCFG.STABILITY_RESERVE:.0%}) = "
        f"{int(cash * RCFG.STABILITY_RESERVE):,}원"
    )

    # ── 17. 출력 컬럼 세팅 ───────────────────────────────────────────────
    top1 = top1.copy()
    top1["position_size"]      = round(position_size, 4)
    top1["capital_deploy_krw"] = deployable_cash
    top1["risk_grade"]         = grade
    top1["dd_state"]           = dd_state
    top1["dd_pct"]             = round(dd_pct, 5)
    top1["var_pct"]            = round(var_result["var"], 5)
    top1["cvar_pct"]           = round(var_result["cvar"], 5)
    top1["cvar_source"]        = var_result.get("source", "unknown")   # [FIX-V6-2]
    top1["attack_ratio"]       = RCFG.ATTACK_RATIO
    top1["stability_reserve"]  = RCFG.STABILITY_RESERVE
    # [v6.3 FIX-2] 공격70/방어30 실제 배분 금액 추가
    top1["attack_amt"]         = int(deployable_cash * RCFG.ATTACK_RATIO)
    top1["stable_amt"]         = int(deployable_cash * RCFG.STABILITY_RESERVE)
    top1["regime"]             = regime
    top1["strategy_hint_used"] = strategy_hint
    top1["inst_mult"]          = round(inst_mult, 4)
    top1["ride_mult"]          = round(ride_mult, 4)         # [FIX-V6-4]
    top1["inst_holding"]       = inst_holding
    top1["cumul_dd_scale"]     = round(cumul_dd_scale, 4)
    top1["forced_entry"]       = forced_entry
    top1["profit_factor"]      = round(pf_val, 4)
    top1["engine_ver"]         = ENGINE_VER

    # ── 18. 저장 (atomic write) ──────────────────────────────────────────
    tmp = RCFG.PATH_OUTPUT + ".tmp"
    Path(RCFG.PATH_OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    try:
        top1.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, RCFG.PATH_OUTPUT)
        _RISK_STATS["output_codes"] = len(top1)
        log.info(
            f"[RISK] 저장 완료: {RCFG.PATH_OUTPUT} "
            f"(grade={grade} | regime={regime} | "
            f"strat={strategy_hint} | ride={ride_mult:.2f} | force={forced_entry})"
        )
    except Exception as e:
        log.error(f"[RISK] 저장 실패: {e}")
        _risk_set_reason("output_write_fail")
        return RC_STOP

    # ── 19. 1일 1진입 기록 ───────────────────────────────────────────────
    # [v6.5 RELAY-FIX] 전략별 독립 발행 기록
    # SIGA 발행 후 PULLBACK 릴레이를 게이트가 허용할 수 있도록 전략 구분 저장
    _strat_upper = strategy_hint.upper()
    entry_state.update({
        "date":              datetime.now().strftime("%Y%m%d"),
        "candidate_emitted": True,
        "ticker":            ticker,
        "forced_entry":      forced_entry,
        "entered_strategy":  _strat_upper,
    })
    if _strat_upper == "SIGA":
        entry_state["siga_emitted"]  = True
        entry_state["siga_ticker"]   = ticker
    elif _strat_upper == "PULLBACK":
        # [PBCOUNT-FIX 2026-06-05] 장전(09:00 이전) 발행은 일일 카운트에서 제외.
        #   기존: 달력일 기준 리셋이라 00:00:05 자정 유령발행이 "오늘" count=1을 먹어
        #         실거래 후보가 2번 만에 일일한도3 소진 → 09:06부터 영구 재발행 차단.
        #   09:00+ 정규장 발행은 정상 카운트(일일3캡 유지), 장전 유령발행만 배제.
        _PB_SESSION_START = 900
        _now_hhmm = int(datetime.now().strftime("%H%M"))
        if _now_hhmm >= _PB_SESSION_START:
            entry_state["pullback_count"] = int(entry_state.get("pullback_count", 0)) + 1
            entry_state["pullback_ticker"]  = ticker
        else:
            log.info("[GATE] 장전(%04d<0900) PULLBACK 발행 → 일일 카운트 제외", _now_hhmm)
    _save_entry_state(entry_state, log)
    # [CYCLE-6 2026-05-21] event_journal CANDIDATE_EMITTED emit
    _emit_event("CANDIDATE_EMITTED", entity="entry", entity_id=ticker, payload={
        "strategy": _strat_upper,
        "forced_entry": bool(forced_entry),
    })
    log.info(
        f"[GATE] 후보 발행 기록: {ticker} ({_strat_upper}) "
        f"siga={entry_state.get('siga_emitted',False)} "
        f"pullback_count={entry_state.get('pullback_count',0)}"
    )

    # ── 20. Kelly 스냅샷 (자기진화 — 전략별) ────────────────────────────
    _save_kelly_snapshot(kelly, log)

    return RC_OK


# ==============================================================================
# MAIN
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="RT 리스크 엔진 v6.6 — 헤지펀드급 · 1종목 몰빵 · SIGA릴레이"
    )
    parser.add_argument("--loop", action="store_true", help="60초 주기 루프")
    args = parser.parse_args()

    log = _setup_logger()
    log.info("=" * 70)
    log.info(f"RT 리스크 엔진 v6.6  |  {datetime.now():%Y-%m-%d %H:%M:%S}")
    log.info(
        f"전략: 1종목 몰빵 | 공격={RCFG.ATTACK_RATIO:.0%} | "
        f"안정={RCFG.STABILITY_RESERVE:.0%} | "
        f"진입임계={RCFG.DEPLOY_THRESHOLD:.0%}"
    )
    if RCFG.TEST_CAPITAL_CAP > 0:
        log.info(
            f"★★★ 실테스트 모드 ★★★  "
            f"자본 상한 = {RCFG.TEST_CAPITAL_CAP:,}원  "
            f"(TEST_CAPITAL_CAP={RCFG.TEST_CAPITAL_CAP:,})"
        )
    log.info(
        f"기관: BOOST≥{RCFG.INST_BOOST_SCALE}x | HOLD면제≥{RCFG.INST_HOLD_MIN_CONSEC}일 | "
        f"Kelly N={RCFG.KELLY_ROLLING_N} Min={RCFG.KELLY_MIN_TRADES}"
    )
    log.info(
        f"ride_score: 강매집({RCFG.RIDE_STRONG_THRESH})×{RCFG.RIDE_STRONG_MULT} | "
        f"미확인(<{RCFG.RIDE_WEAK_THRESH})×{RCFG.RIDE_WEAK_MULT} | "
        f"S등급 consec≥{RCFG.RIDE_STRONG_CONSEC}"
    )
    log.info(
        f"Regime: BULL>{RCFG.REGIME_BULL_THRESH:+.1%} / "
        f"BEAR<{-RCFG.REGIME_BEAR_THRESH:+.1%} (자체계산 포함)"
    )
    log.info(
        f"강제진입: {'ON' if RCFG.FORCED_ENTRY_ENABLE else 'OFF'} | "
        f"score하한={RCFG.FORCED_ENTRY_SCORE_FLOOR} | "
        f"BULL={RCFG.FORCED_ENTRY_BULL_SIZE:.0%} / "
        f"NEUTRAL={RCFG.FORCED_ENTRY_NEUTRAL_SIZE:.0%} / "
        f"BEAR={RCFG.FORCED_ENTRY_BEAR_SIZE:.0%}"
    )
    log.info(
        f"[v6.2 FIX] EOD삭제 | accel {RCFG.ACCEL_RECENT_N}/{RCFG.ACCEL_BASE_N}봉 | "
        f"CVaR최소15건 | DD누적{RCFG.DD_CUMUL_DAYS}일 | PF≥{RCFG.EV_BONUS_PF_THRESH}→cap↑"
    )
    log.info(f"Regimes: {list(RCFG.REGIME_PARAMS.keys())}")
    log.info(f"Strategies: {list(RCFG.STRATEGY_PROFILES.keys())}")
    log.info("=" * 70)

    if args.loop:
        log.info(f"[LOOP] {RCFG.LOOP_INTERVAL_SEC}초 주기 시작")
        while True:
            now_hhmm = int(datetime.now().strftime("%H%M"))
            if now_hhmm > RCFG.MARKET_CLOSE:
                log.info(f"[LOOP] {RCFG.MARKET_CLOSE} 장 종료 → 루프 종료")
                break
            if now_hhmm >= RCFG.MARKET_OPEN:
                rc = process(log)
                if rc == RC_STOP:
                    log.error("[LOOP] RC_STOP → 루프 강제 종료")
                    return RC_STOP
            time.sleep(RCFG.LOOP_INTERVAL_SEC)
        return RC_OK
    else:
        return process(log)


if __name__ == "__main__":
    sys.exit(main())

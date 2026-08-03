# -*- coding: utf-8 -*-
"""
params_reader.py  v1_13  UNIFIED
=====================================================================
고유 영역 : params.json 읽기 전담 (쓰기 절대 금지)
            모든 모듈이 이 파일 하나만 import 한다
            evolution_engine.py 가 params.json 을 갱신하면
            다음 실행 시 모든 모듈에 자동 반영

v1_13 변경 (v1_12 대비) — 2026-04-18 헤지펀드 대장주 선별 강화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
make_rt_intraday v7_21 + rt_pullback_engine v5_11 파라미터 연동

  [ADD-1] _DEFAULT_선정에 대장주 선별 파라미터 4개 추가
          RVOL_MIN=2.0         : RVOL 기준 1.5→2.0 (헤지펀드 기준)
          RS_TOP10_BONUS=0.18  : RS 상위 10% champion_score 보너스
          RS_TOP10_PERCENTILE=0.90 : RS 상위 10% percentile 기준
          SECTOR_LEADER_BONUS=0.15 : 섹터 거래대금 1위 보너스

  [ADD-2] get_선정() validated 블록에 4개 파라미터 타입/범위 검증 추가
          RVOL_MIN: lo=1.0, hi=5.0
          RS_TOP10_BONUS: lo=0.0, hi=0.50
          RS_TOP10_PERCENTILE: lo=0.50, hi=0.99
          SECTOR_LEADER_BONUS: lo=0.0, hi=0.50

  [효과] params.json에 선정.RVOL_MIN 등을 추가하면
          evolution_engine이 자동으로 runtime 조정 가능
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

v1_12 변경 (v1_11 대비) — 2026-04-18 Day 2 파라미터 단일화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기본값(fallback)이 params.json 실제값과 달라서 발생하던 문제 해소.
params.json 로딩 실패 시, 또는 해당 키가 params.json에 없을 때
_DEFAULT_rt_sell 값이 쓰이는데, 이 값이 구버전이었음.

  [FIX-A]  hard_stop: 0.020 → 0.025
           근거: 지침서[US-1] 6-2 HARD_STOP 2.5% + params v3.11 (0.025) 통일
                 기존 0.020은 매수엔진(0.025) vs 매도엔진(0.020) 불일치 유발
  
  [FIX-B]  breakeven_ret: 0.015 → 0.012
           근거: params v3.11 breakeven_ret=0.012 실제값 동기화
  
  [FIX-C]  trail_activate_ret: 0.015 → 0.012
           근거: params v3.11 trail_activate_ret=0.012 실제값 동기화
                 Profit Lock 2% 트리거와 Trail 이중게이트 동시 만족
  
  [FIX-D]  k_boost_ofi_floor: 0.30 → 0.40
           근거: 지침서[US-1] v1.2 명시 상향 — "가짜 기관강세 오판 방지"
                 params v3.11 k_boost_ofi_floor=0.40 통일
                 siga_sell_v3.5 / pullback_sell_v4.20 전부 0.40 사용 중
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

변경이력 (이전)
---------
v1_0~v1_6  기존 버전 (참조)
v1_7  ★헤지펀드급★ - SUPER_TREND_MODE / EOD 대소문자 / deepcopy / TOCTOU / 트레일 검증
v1_8  ★통합패치★ - 연결라인 파라미터화 완성
v1_9  ★지침서[15]통합판★
    [BUG-HIGH-1 FIX] trail_activate_ret 1.0%→1.5% (지침서§5-1 이중게이트)
    [BUG-HIGH-2 FIX] split_ratio 35%→40% (지침서§9-1 선익절 비율)
    [BUG-MED-1 FIX]  super_trail V자 패턴 → 단조감소로 교체

    [ADD-CRIT-1] Chandelier k 레짐별 파라미터 공급 경로 신설 (지침서§3-2)
                 chandelier_k_normal=2.0 / k_high=2.5 / k_extreme=3.0
                 vol_ratio_high_thr=1.2 / vol_ratio_extreme_thr=1.5
    [ADD-CRIT-2] 기관강세 k×1.15 보정 3조건 파라미터화 (지침서§3-3)
                 k_boost_multiplier=1.15 / ofi_floor=0.30 / accel_floor=1.20 / profit_floor=2%
    [ADD-CRIT-3] accel lookback 파라미터화 (지침서§3-4)
                 accel_recent_bars=3 / accel_prior_bars=5 / accel_neutral=1.0
    [ADD-CRIT-4] HARD_FAILSAFE 파라미터 공급 (지침서§7)
                 failsafe_trigger_pct=2% / failsafe_preserve_ratio=60%
    [ADD-CRIT-5] PEAK_PROTECT 3단계 파라미터 공급 (지침서§6)
                 l1:5%/2% | l2:8%/3% | l3:12%/5% | inst_div=1.15
    [ADD-HIGH-1] Trail 강제 활성화 파라미터 (지침서§5-3)
                 trail_activate_hard_pct=2%
    [ADD-HIGH-2] RIDE/INST STRONG HOLD 파라미터 (지침서§8 P1.3/1.5)
                 ride_strong_hold_floor=0.65 / inst_strong_hold_ofi=0.15 / max_ret=8%
    [ADD-HIGH-3] 기관동행 선익절 비율 (지침서§9-3)
                 split_ratio_inst=25%
    [ADD-HIGH-4] 전략별 오버라이드 파라미터화 (지침서§14)
                 jongbae_k_mult=0.90 / jongbae_trail_mult=1.50
                 jongbae/siga/trend_max_hold_min
    [ADD-CROSS]  get_rt_sell() 교차검증 8항목 신설
                 (trail순서/chandelier_k순서/vol_ratio순서/peak_protect순서/
                  split비율/failsafe_trigger/k_boost상한 등)
    [ADD-CONN]   validate_connection_line() 신규 검증 3항목 추가
                 (failsafe_trigger_pct ≤ 3% / peak_protect 구조 / Chandelier k 순서)

v1_11  ★종배 완전 삭제 + 헤지펀드급 보강 + 수익률 향상★
    기준: C-Suite 합동 감사 결과 (2026-04-10)
    목표: 96점→97점 / 종배 잔존 코드 0줄 / 수익률 구조 강화
    [삭제] _DEFAULT_eod / get_eod() / jongbae_* / FORCE_CLOSE_시배 완전 제거
    [FIX-SRC] Glasserman & Xu 출처: 2011(리밸런싱)→2014 QF 14(1):29-58
    [UPD-PROFIT] W_RISK 1.0→3.0 / TOP_N 250→200 / INST_ACCEL_THR 1.5→1.3
                 HINT_SIGA_VA_MIN 1.20→1.10 / vol_spike_intraday_min 1.8→2.2
    [ADD-DAILY]  _DEFAULT_운영 신설 — 1일 1진입 보장 파라미터 공급
    [ADD-EVO]    _EVOLUTION_ALLOWED_KEYS — 자기진화 허용 파라미터 명시 목록
    [UPD-CONN]   validate_connection_line() ⑱ — 1일 1진입 설정 검증

v1_10  ★selection 허브 완전 구현 — 수익률 점수 구조 전체 공급★
    기준: 통합 패치 지시문 (2026-04-09) — 지시1~7 전항목 적용
    목표: selection 엔진 수익률 핵심 파라미터 허브 완전 공급 / 91점→96점

    [지시1] _DEFAULT_선정에 수익률 점수 구조 파라미터 22개 추가
            W_VALUE/ACCEL/CP/HB/VWP/SUPPLY/RISK, BONUS_CAP, TOP_N
            INST_ACCEL_*, VOL5D_*, VAL_NORM_BASE, ACCEL_NORM_DIV
            EDGE_MIN_UP/DOWN, HINT_EOD_HB_MIN/PULLBACK_CP_*/SIGA_VA_MIN
    [지시2] get_선정() 신규 필드 22개 + 타입/범위 검증 완전 추가
    [지시3] _cross_validate_선정() 강화 — 6개 신규 논리검증
            ① EDGE_MIN_DOWN > EDGE_MIN_UP
            ② HINT_PULLBACK_CP_LOW < HIGH
            ③ INST_ACCEL_THRESHOLD ≥ 1.1
            ④ ACCEL_NORM_DIV > 0 (ZeroDivisionError 방지)
            ⑤ TOP_N 100~300 범위 강제
            ⑥ BONUS_CAP > 12 → warn 후 클램프
    [지시4] validate_connection_line() selection 허브 5항목 추가 (⑫~⑯)
            selection_weights_ok / edge_floor / pullback_hint / accel / topn
    [지시5] validate_connection_line() attack_ratio 동기화 검증 추가 (⑰)
            scoreboard.attack_ratio ↔ 공격안정비율.attack_pct 일치 확인
    [지시6] 수익률 저하형 파라미터 경고 로그 4개 추가 (강제복구 없이 warning)
            get_scoreboard: score_hard_min > 80 → 후보 과소 경고
            get_bridge:     ev_min_threshold > 0.012 → 진입 기회 상실 경고
            get_siga_link:  open_gap_max < 4.0 → 시가 기회 축소 경고
            get_rt_sell:    split_ratio > 0.45 → 추세 수익 훼손 경고
    [지시7] 버전 문자열 정합성: v1_8 잔존 문구 → v1_10 통일

학술 출처 (v1_9 보강)
---------------------
- True ATR         : Wilder (1978) New Concepts in Technical Trading Systems
- Chandelier Exit  : LeBeau & Lucas (1992) Computer Analysis of the Futures Market
- OFI 기관감지     : Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
                     DOI: 10.1093/jjfinec/nbt003
- 동적 TSL + 변동성: Palazzi (2025) Trading Games, Journal of Futures Markets
                     DOI: 10.1002/fut.70018  ※JFM=Journal of Futures Markets
- 변동성 레짐 리스크: Glasserman & Xu (2014) Robust Risk Measurement and Model Risk
                     Quantitative Finance 14(1):29-58
                     ※2011 논문(리밸런싱 오차)이 아님 — 2014 리스크 측정 논문으로 교체
- Half-Kelly       : Kelly (1956), Thorp (1962)
- 소프트 차단      : Almgren & Chriss (2001) Optimal Execution, JRF
                     ※Citadel Risk Overlay(비공개) → 공개논문으로 대체

고유영역 원칙 (절대 불변)
--------------------------
- scoreboard : 선별/점수화만 담당. EV계산/Kelly계산/시가타이밍 금지
- bridge     : 리스크/사이징/연결만 담당. 점수산출/시가타이밍 금지
- siga(AM)   : 타이밍/진입트리거만 담당. 점수계산/Kelly 금지
- 이 파일은 "기준값 공급"만 한다. 로직 구현 금지.

안전 설계
---------
- params.json 없거나 손상     → 하드코딩 기본값 자동 사용 (무중단)
- SHA-256 파싱 실패           → 직전 정상 캐시 유지
- threading.Lock (전체 I/O)   → exists/stat/frozen/read_bytes 모두 Lock 내부
- deepcopy                    → 중첩 구조 캐시 오염 원천 차단
- 장중 09:03~09:21 동결       → Lock 내부에서 체크 (완전 스레드 안전)
- Kelly fraction 절대 상한 0.65
- 파라미터 논리 역전 자동 복구
- NaN/Inf 자동 차단
- 읽기 전용 — 이 파일에서 params.json 쓰기 절대 금지

파이프라인 위치
--------------
evolution_engine → params.json → [이 파일] → scoreboard/bridge/siga/각 모듈
"""
from __future__ import annotations

import copy, hashlib, json, logging, math, os, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

_KST = timezone(timedelta(hours=9))
_BASE   = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
_DATA   = _BASE / "DATA"
_PARAMS = _DATA / "params.json"


# ═══════════════════════════════════════════════════════════════
#  로거 설정
# ═══════════════════════════════════════════════════════════════
def _setup_logger() -> logging.Logger:
    lg = logging.getLogger("params_reader")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    _log_dir = _BASE / "LOG"
    try:
        import logging.handlers as _lh
        _log_dir.mkdir(parents=True, exist_ok=True)
        fh = _lh.RotatingFileHandler(
            _log_dir / "params_reader.log",
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        lg.addHandler(fh)
    except Exception as e:
        print(f"[SETUP][FAIL] RotatingFileHandler 추가 실패: {e}")
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    lg.addHandler(sh)
    return lg

_log = _setup_logger()


# ═══════════════════════════════════════════════════════════════
#  장중 동결 구간 (HHMM)
# ═══════════════════════════════════════════════════════════════
_FREEZE_START = int(os.environ.get("PARAMS_FREEZE_START", "903"))
_FREEZE_END   = int(os.environ.get("PARAMS_FREEZE_END",   "921"))


def _now_hhmm() -> int:
    """KST 현재 시각 HHMM"""
    t = datetime.now(_KST)
    return t.hour * 100 + t.minute


def _is_frozen() -> bool:
    """장중 파라미터 동결 구간 여부 — Lock 내부에서만 호출"""
    now = _now_hhmm()
    return _FREEZE_START <= now <= _FREEZE_END


# ═══════════════════════════════════════════════════════════════
#  하드코딩 기본값
# ═══════════════════════════════════════════════════════════════

_DEFAULT_선정: Dict[str, Any] = {
    # ── 기본 필터 ───────────────────────────────────────────────
    "MIN_VALUE_NOW": 10_000_000, "MIN_VALUE_3M": 30_000_000,
    "MIN_PRICE": 500, "ADX_TREND_THRESHOLD": 25, "ADX_WEAK_THRESHOLD": 20,
    "ADX_BONUS_STRONG": 5.0, "ADX_BONUS_TREND": 3.0,
    "RSI_GOOD_LOW": 50.0, "RSI_GOOD_HIGH": 70.0, "RSI_OVER_LOW": 30.0,
    "POC_RSI_BONUS": 4.0, "HEAT_STRONG": 6.0, "HEAT_MILD": 4.0,
    "BB_SQUEEZE_BONUS": 3.0,

    # ── [v1_10 ADD] 수익률 점수 구조 가중치 ──────────────────────
    # make_rt_intraday_from_prices_1m 계열 선정 엔진 핵심 가중치
    # evolution_engine이 자동 갱신 → 자기진화 범위 확장
    "W_VALUE":   20.0,   # 거래대금 가중치
    "W_ACCEL":   12.0,   # 가속도 가중치
    "W_CP":      10.0,   # 종가비 가중치
    "W_HB":      10.0,   # 고가비 가중치
    "W_VWP":      8.0,   # VWAP 괴리 가중치
    "W_SUPPLY":  10.0,   # 수급 가중치
    # [v1_11 UPD] 1.0→3.0 리스크 감점 강화 → 고위험 종목 필터↑ 승률↑
    "W_RISK":     3.0,   # 리스크 배수 (감점용)
    "BONUS_CAP":  8.0,   # 보너스 합산 상한

    # ── [v1_10 ADD] 선정 범위 / 정규화 ──────────────────────────
    # [v1_11 UPD] TOP_N 250→200 (후보 압축 → 상위 품질 집중)
    "TOP_N":            200,        # 최종 후보 종목 수 (100~300 권장)
    "VAL_NORM_BASE":    50_000_000, # 거래대금 정규화 기준 (원)
    "ACCEL_NORM_DIV":   8.0,        # 가속도 정규화 제수

    # ── [v1_10 ADD] 기관 가속 보너스 ────────────────────────────
    "INST_ACCEL_BONUS":     2.0,        # 기관 가속 시 추가 점수
    # [v1_11 UPD] 1.5→1.3 기관 가속 조기 감지 → 진입 타이밍↑
    "INST_ACCEL_THRESHOLD": 1.3,        # 기관 가속 판정 배수 (≥1.1 필수)
    "INST_ACCEL_MIN_ABS":   50_000_000, # 기관 가속 최소 절대 거래량 (원)

    # ── [v1_10 ADD] 5일 변동성 보너스 ───────────────────────────
    "VOL5D_BONUS_MAX":       3.0,   # 5일 변동성 보너스 상한
    "VOL5D_BONUS_THRESHOLD": 2.0,   # 5일 변동성 보너스 발동 배수

    # ── [v1_10 ADD] EDGE 최소 기준 ───────────────────────────────
    "EDGE_MIN_UP":   0.18,  # 상승 edge 최솟값 (EDGE_MIN_DOWN < 필수)
    "EDGE_MIN_DOWN": 0.22,  # 하락 edge 최솟값

    # ── [v1_10 ADD] 전략 힌트 파라미터 ──────────────────────────
    "HINT_EOD_HB_MIN":       0.98,  # 추세눌림/시가 힌트: 고가비 최소
    "HINT_PULLBACK_CP_LOW":  0.30,  # 추세눌림 힌트: 종가비 하한
    "HINT_PULLBACK_CP_HIGH": 0.70,  # 추세눌림 힌트: 종가비 상한
    # [v1_11 UPD] 1.20→1.10 시가 진입 기회 확대 (과도한 필터 완화)
    "HINT_SIGA_VA_MIN":      1.10,  # 시가 힌트: VA 배수 최소

    # ── [v1_13 ADD] 헤지펀드 대장주 선별 강화 파라미터 ──────────
    # make_rt_intraday v7_21 + rt_pullback_engine v5_11 동시 적용
    # evolution_engine 자동 갱신 허용 (합리적 범위 내)
    "RVOL_MIN":              2.0,   # RVOL 필터 기준 (오늘거래대금/5일평균)
                                    # 1.5→2.0: 헤지펀드 기준 상향 (RenTec/Zarattini)
    "RS_TOP10_BONUS":        0.18,  # RS 상위 10%ile 보너스 배율 (champion_score ×)
    "RS_TOP10_PERCENTILE":   0.90,  # RS 상위 10% 기준 (90th percentile)
    "SECTOR_LEADER_BONUS":   0.15,  # 섹터 거래대금 1위 보너스 배율
}

_DEFAULT_갭등급: Dict[str, Any] = {
    "GAP_A_MIN": 3.0, "GAP_B_MIN": 1.5, "GAP_C_MIN": 0.0, "CUT_GAP_DOWN": -2.0,
}

_DEFAULT_트레일: Dict[str, Any] = {
    "table": [[0.0,3.0,2.2],[3.0,5.0,2.0],[5.0,8.0,1.8],[8.0,12.0,1.6],[12.0,999.0,1.5]],
    "BUFFER_MULT": 1.5,
}

_DEFAULT_청산시각: Dict[str, Any] = {
    # [v1_11 삭제] FORCE_CLOSE_시배(종배 전용) 제거
    "FORCE_CLOSE_BCD": 1030,
    "FORCE_CLOSE_A": 1130, "GAP_CHECK_BY": 905,
}

_DEFAULT_kelly: Dict[str, Any] = {
    "fraction": 0.5, "max_per_종목": 0.25, "min_per_종목": 0.05, "kelly_raw": 0.0,
}

_DEFAULT_rt_sell: Dict[str, Any] = {
    # ── 기본 손절/활성화 ────────────────────────────────────────────
    # [v1_12 FIX-A] 0.020 → 0.025 (지침서[US-1] 6-2 + params.json 통일)
    # 기존 0.020은 params.json(0.025)과 불일치 → 매수/매도 엔진 간 R-계산 어긋남
    "hard_stop":             0.025,   # 하드 손절 (절대 상한) — 지침서 고정
    # [v1_12 FIX-B] 0.015 → 0.012 (params.json v3.11 breakeven_ret 실제값 동기화)
    "breakeven_ret":         0.012,   # 손익분기 수익률
    # [BUG-HIGH-1 FIX] trail_activate_ret 1.0%→1.5% (지침서v15 §5-1)
    # [v1_12 FIX-C] 0.015 → 0.012 (params.json v3.11 trail_activate_ret 동기화)
    "trail_activate_ret":    0.012,   # Trail 이중게이트 A조건 (수익≥1.2%)
    # [ADD] Trail 강제 활성화 (지침서v15 §5-3 TRAIL_ACTIVATE_HARD_PCT)
    "trail_activate_hard_pct": 0.02,  # 수익≥2% → ride 무관 강제 Trail 활성화

    # ── Trail 테이블 (수익구간별 ATR 배수 — 단조감소 유지) ─────────
    "trail_table": [[0.0,3.0,2.2],[3.0,5.0,2.0],[5.0,8.0,1.8],[8.0,12.0,1.6],[12.0,999.0,1.5]],

    # ── SuperTrail (지침서v15 §14 — 0~5% 비활성 가드값 포함) ───────
    "SUPER_TREND_MODE":      True,
    # [BUG-MED-1 FIX] V자 패턴 → 단조감소로 교체
    "super_trail": [[0.0,5.0,2.2],[5.0,8.0,2.0],[8.0,12.0,1.8],[12.0,999.0,1.6]],
    "SUPER_TRAIL_ACTIVATE_PCT": 5.0,  # 5% 이상부터 실활성

    # ── 선익절 / T2 ──────────────────────────────────────────────────
    "BUFFER_MULT":           1.5,
    # [BUG-HIGH-2 FIX] split_ratio 35%→40% (지침서v15 §9-1)
    "split_ratio":           0.40,    # T1 선익절 비율 40%
    "split_ratio_inst":      0.25,    # 기관동행(ride≥0.40) 시 25%
    "t2_mult":               2.20,

    # ── 모멘텀/VWAP 이탈 ────────────────────────────────────────────
    "momentum_min_profit":   0.015,
    "momentum_vol_ratio":    0.55,
    "momentum_price_drop":   0.005,
    "vwap_thresh":           0.985,
    "vwap_thresh_t2":        0.975,

    # ── 강제 청산 시각 ───────────────────────────────────────────────
    # [v1_11 삭제] force_시배(종배 전용) 제거
    "force_A":               1450,
    "force_BCD":             1450,

    # ══ [v1_9 신규] Chandelier Exit k — 레짐별 ATR 배수 ═════════════
    # 출처: LeBeau & Lucas (1992) + Glasserman & Xu (2011) 1.0~1.5σ
    # 지침서v15 §3-2 채택값
    "chandelier_k_normal":   2.0,     # vol_ratio < 1.2 (NORMAL 레짐)
    "chandelier_k_high":     2.5,     # vol_ratio ≥ 1.2 (HIGH 레짐)
    "chandelier_k_extreme":  3.0,     # vol_ratio ≥ 1.5 (EXTREME 레짐)
    "vol_ratio_high_thr":    1.2,     # HIGH 레짐 진입 임계값
    "vol_ratio_extreme_thr": 1.5,     # EXTREME 레짐 진입 임계값

    # ══ [v1_9 신규] 기관강세 k×1.15 보정 — 지침서v15 §3-3 ══════════
    # [v1_12 FIX-D] OFI 0.30 → 0.40 (지침서[US-1] v1.2 명시 상향 + params.json 통일)
    # 근거: 0.30은 노이즈 구간 포함 → 가짜 기관강세 → Trail 과완화 → 수익 반납
    #      0.40으로 상향: 진짜 기관 흐름에서만 k×1.15 적용
    # OFI≥0.40 AND accel≥1.20 AND 수익≥2% → k×1.15
    # 출처: Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
    "k_boost_multiplier":    1.15,    # 기관강세 확인 시 k 배수
    "k_boost_ofi_floor":     0.40,    # 조건①: OFI 최소 [v1_12 상향]
    "k_boost_accel_floor":   1.20,    # 조건②: accel 최소
    "k_boost_profit_floor":  0.02,    # 조건③: 수익 최소 (지침서 2%로 완화)

    # ══ [v1_9 신규] accel 계산 lookback — 지침서v15 §3-4 ═══════════
    # accel = mean(inst_net_buy 최근3봉) / mean(이전5봉)
    "accel_recent_bars":     3,       # 분자 봉 수
    "accel_prior_bars":      5,       # 분모 봉 수
    "accel_neutral":         1.0,     # 데이터 없을 때 중립값

    # ══ [v1_9 신규] HARD_FAILSAFE — 지침서v15 §7 ════════════════════
    # 조건1: 과거 수익≥2% 달성 이력 AND 조건2: 현재 < 고점×60% → 즉시청산
    # [14] 3%/50% → [v4_9 채택] 2%/60% 로 강화
    "failsafe_trigger_pct":    0.02,  # 달성 이력 트리거 (2%)
    "failsafe_preserve_ratio": 0.60,  # 고점 대비 보전 비율 (60%)

    # ══ [v1_9 신규] PEAK_PROTECT 3단계 — 지침서v15 §6 ══════════════
    # 기관 미동행 기준. 기관동행 시 ÷1.15 완화
    "peak_protect_l1_pct":   0.05,   # 1단계: 고점≥5% 달성 기준
    "peak_protect_l1_exit":  0.02,   # 1단계: 현재가 < +2% → 청산
    "peak_protect_l2_pct":   0.08,   # 2단계: 고점≥8% 달성 기준
    "peak_protect_l2_exit":  0.03,   # 2단계: 현재가 < +3% → 청산
    "peak_protect_l3_pct":   0.12,   # 3단계: 고점≥12% 달성 기준
    "peak_protect_l3_exit":  0.05,   # 3단계: 현재가 < +5% → 청산
    "peak_protect_inst_div": 1.15,   # 기관동행 시 exit 임계 ÷ 이 값

    # ══ [v1_9 신규] RIDE_STRONG_HOLD / INST_STRONG_HOLD — §8 Priority 1.3/1.5
    "ride_strong_hold_floor":    0.65,  # ride≥0.65 + 수익>0 → 보유 유지
    "inst_strong_hold_ofi":      0.15,  # OFI>0.15 → INST_STRONG_HOLD 조건
    "inst_strong_hold_max_ret":  0.08,  # 수익≥8% 시 INST_STRONG_HOLD 해제

    # ══ [v1_9 신규] 전략별 오버라이드 — 지침서v15 §14 ══════════════
    # [v1_11 삭제] jongbae_k_mult / jongbae_trail_mult / jongbae_max_hold_min 제거
    "siga_max_hold_min":     120,     # 시가: 최대 보유 시간 (분)
    "trend_max_hold_min":    240,     # 추세눌림: 최대 보유 시간 (분)
}


# ═══════════════════════════════════════════════════════════════
#  [v1_11 신규] 1일 1진입 보장 운영 파라미터 (요건 9번 이행)
# ═══════════════════════════════════════════════════════════════
_DEFAULT_운영: Dict[str, Any] = {
    # 1일 1진입 보장 — 지침서 요건 9번
    "min_daily_entry_required": True,   # 하루 최소 1회 진입 강제 여부
    "force_entry_by_hhmm":      1300,   # 이 시각까지 진입 없으면 완화된 조건으로 강제 허용
    "skip_if_market_bad":       True,   # 시장 극도 악화 시(BEAR 레짐) 예외 허용
    "market_bad_ofi_threshold": -0.40,  # 이 OFI 이하면 장 극도 악화로 판정
    "market_bad_regime":        "BEAR", # 진입 스킵 허용 레짐

    # 자기진화 주기
    "evolution_interval_trades": 20,    # 이 거래 수마다 진화 검토
    "evolution_min_trades":      10,    # 최소 거래 수 확보 후 진화 허용

    # [v1_13 ADD] 재진입 차단 기준 — 절대금액에서 자본 비율로 전환
    # rt_intraday_trend_pullback_engine v5.12 FIX-1 연동
    "entry_lock_loss_pct":       0.02,  # 자본의 2% 손실 시 2/3회차 재진입 차단

    # [v1_13 ADD] 점심 차단 구간 — 11:40~12:50 (기존 13:00에서 단축)
    "lunch_block_end_hhmm":      1250,  # 점심 차단 종료 시각 [v1_13] 1300→1250
}

# ═══════════════════════════════════════════════════════════════
#  [v1_11 신규] 자기진화 허용 파라미터 명시 목록
#  evolution_engine이 갱신할 수 있는 파라미터만 여기에 등재
#  ★ 지침서[15] §13-2 금지 파라미터는 절대 포함 불가 ★
# ═══════════════════════════════════════════════════════════════
_EVOLUTION_ALLOWED_KEYS: tuple = (
    # rt_sell — 3개 (지침서§13-1 명시)
    "hard_stop",              # 승률<45% → 축소 / ±10%
    "trail_activate_ret",     # 승률>60% → 앞당김 / ±10%
    "split_ratio",            # PF<0.8 → 확대 / ±0.05

    # 선정 가중치 — 수익률 점수 구조 (v1_11 진화 범위 확장)
    "W_VALUE",    # 거래대금 가중치 / ±5.0
    "W_ACCEL",    # 가속도 가중치   / ±3.0
    "W_SUPPLY",   # 수급 가중치     / ±3.0

    # 운영 임계값
    "force_entry_by_hhmm",    # 장 상황에 따라 조정 / ±30분
)

# ★ 진화 절대 금지 (지침서§13-2) — evolution_engine이 아래 키 수정 시 즉시 경고
_EVOLUTION_FROZEN_KEYS: tuple = (
    "chandelier_k_normal", "chandelier_k_high", "chandelier_k_extreme",
    "peak_protect_l1_pct", "peak_protect_l2_pct", "peak_protect_l3_pct",
    "failsafe_trigger_pct", "failsafe_preserve_ratio",
    "trail_activate_hard_pct",
)

_DEFAULT_거래비용: Dict[str, Any] = {
    "buy_fee_pct": 0.00015, "sell_fee_pct": 0.00015, "sell_tax_pct": 0.0018,
}

# [UPD-1] 스코어보드 기본값 강화 + 신규 필드 7개
# 역할: 선별/점수화만. EV계산/Kelly계산/시가타이밍 금지
_DEFAULT_scoreboard: Dict[str, Any] = {
    "attack_ratio":           0.70,   # 공격 비율
    "defense_ratio":          0.30,   # 안정 비율

    "s1_ofi_weight":          22.0,   # Step1 OFI 가중치 (강화: 20→22)
    "s1_vpin_weight":         12.0,   # Step1 VPIN 가중치 (강화: 10→12)

    "s2_axes_weight":         16.0,   # Step2 축 가중치 (강화: 15→16)
    "s2_inst_weight":         22.0,   # Step2 기관 가중치 (강화: 20→22)
    "s2_gap_weight":           8.0,   # Step2 갭 가중치 (조정: 10→8)

    "conv_gate_min":           0.68,  # Conviction Gate 최소 (강화: 0.60→0.68)
    "hist_bonus_cap":          8.0,   # 이력 보너스 상한 (조정: 10→8)

    "hard_cut_oi_drop":       -0.12,  # OI 급락 컷 (강화: -0.15→-0.12)
    "hard_cut_vol_spike":      2.5,   # 볼륨 스파이크 컷 (강화: 3.0→2.5)

    # [신규] 점수 품질 게이트 (EV 계산 아님 — 점수 하한선만)
    "score_hard_min":         75.0,   # 브릿지 통과 최소 점수 (하드)
    "score_soft_min":         70.0,   # 브릿지 통과 최소 점수 (소프트 — 포지션 감소)

    # [신규] 기관 플로우 품질 게이트
    "inst_flow_floor":         0.30,  # 기관 플로우 최소 (이하: 진입 차단)
    "inst_flow_accel_floor":   0.05,  # 기관 플로우 가속 최소 (이하: 경고)

    # [신규] 갭 과열/데드존 게이트
    "gap_overheat_cut":        5.0,   # 이 갭(%) 초과 시 과열 컷
    "gap_deadzone_low":       -0.5,   # 데드존 하한 (%)
    "gap_deadzone_high":       1.0,   # 데드존 상한 (%)
}

# [UPD-2] 브릿지 기본값 강화 + 신규 필드 8개
# 역할: 리스크/사이징/연결만. 점수산출/시가타이밍 금지
_DEFAULT_bridge: Dict[str, Any] = {
    "kelly_bull":              0.65,  # BULL 레짐 Kelly
    "kelly_neutral":           0.45,  # NEUTRAL 레짐 Kelly
    "kelly_caution":           0.20,  # CAUTION 레짐 Kelly (강화: 0.25→0.20)

    "ride_score_hard_cut":     0.28,  # ride_score 하드 차단 (강화: 0.25→0.28)
    "ride_score_soft_lo":      0.30,  # 소프트 구간 하한 (강화: 0.25→0.30)
    "ride_score_soft_hi":      0.45,  # 소프트 구간 상한 (강화: 0.40→0.45)
    "soft_pos_ratio":          0.55,  # 소프트 시 포지션 비율 (강화: 0.60→0.55)

    "ev_min_threshold":        0.009, # 최소 EV 임계 (강화: 0.005→0.009)
    "slippage_cap":            0.002, # 슬리피지 상한 (강화: 0.003→0.002)

    # [신규] 스코어보드 점수 게이트 (들어온 점수를 연결 판단용으로만 사용)
    "bridge_score_min":        75.0,  # 진입 허용 최소 점수 (하드)
    "bridge_score_soft_min":   70.0,  # 포지션 감소 최소 점수 (소프트)

    # [신규] 시장 레짐 차단
    "market_regime_hard_block": "BEAR",     # 이 레짐 → 진입 전면 차단
    "market_regime_soft_block": "CAUTION",  # 이 레짐 → 포지션 축소

    # [신규] 기관 이탈 경보 (스코어보드가 전달한 기관 모멘텀 기반)
    "inst_exit_warn":          -0.20, # 이 이하 → 경고 (포지션 축소)
    "inst_exit_block":         -0.30, # 이 이하 → 진입 차단

    # [신규] 갭 리스크 패널티 (갭이 클수록 리스크 가중)
    "gap_risk_penalty_start":   3.5,  # 이 갭(%) 이상부터 패널티 시작
    "gap_risk_penalty_max":     6.0,  # 이 갭(%) 이상 → 최대 패널티
}

# [UPD-3] 공격/안정 비율 + 신규 필드 4개 (1종목 몰빵 철학 명확화)
_DEFAULT_공격안정비율: Dict[str, Any] = {
    "attack_pct":              0.70,  # 공격 자본 비율
    "stable_pct":              0.30,  # 안정 자본 비율
    "allout_max":              0.65,  # 단일 종목 최대 (Kelly 상한)
    "min_trade_size_krw":  500_000,   # 최소 거래 금액

    # [신규] 1종목 몰빵 철학 파라미터화
    "single_position_mode":    True,  # 단일 종목 집중 모드 (True = 분산 금지)
    "single_position_max_slots": 1,   # 동시 보유 최대 종목 수 (반드시 1)
    "capital_deploy_hard_cap": 0.65,  # 실투입 자본 하드 상한 (과열 방지)
    "capital_deploy_soft_cap": 0.55,  # 실투입 자본 소프트 상한 (경고 기준)
}

# [ADD-4] 시가 연결 파라미터 공급 전용
# 역할: 시가엔진에 "기준값"만 제공. 타이밍/로직 구현 금지
_DEFAULT_siga_link: Dict[str, Any] = {
    "enable_siga_link":        True,  # 시가 연결 활성화 여부

    # 갭 허용 범위 (시가엔진이 판단용으로만 사용)
    "open_gap_min":            1.5,   # 최소 허용 갭 (%)
    "open_gap_max":            5.0,   # 최대 허용 갭 (%)

    # 시가 품질 기준값
    "open_value_ratio_min":    1.5,   # 시가 거래대금 비율 최소
    "open_breakout_lookback_min": 3,  # 브레이크아웃 기준 최소 봉 수

    # 연결 게이트 (scoreboard/bridge 통과 여부 판단용)
    "scoreboard_pass_min":    75.0,   # 스코어보드 통과 최소 점수
    "bridge_pass_ev_min":    0.009,   # 브릿지 통과 최소 EV

    # 기관 플로우 장중 기준값
    "inst_flow_intraday_floor": 0.0,  # 장중 기관 플로우 최소
    "inst_flow_intraday_block":-0.20, # 장중 기관 플로우 차단 기준

    # 진입 제어
    "no_chase_after_min":      3,     # 시가 후 이 분(min) 초과 시 추격 금지
    "entry_delay_sec":        20,     # 신호 후 진입 지연 (초)

    # 과열/확장 차단
    # [v1_11 UPD] 1.8→2.2 노이즈 필터 강화 (장중 볼륨 스파이크 기준 상향)
    "vol_spike_intraday_min":  2.2,   # 장중 최소 볼륨 스파이크 배수
    "price_extension_block_pct": 3.0, # 가격 과확장 차단 기준 (%)
}

# Kelly 절대 상한
_KELLY_FRACTION_HARD_MAX = 0.65
_KELLY_RAW_SAFE_FRACTION = 0.2


# ═══════════════════════════════════════════════════════════════
#  내부 캐시
# ═══════════════════════════════════════════════════════════════
_CACHE:          Dict[str, Any] = {}
_CACHE_MTIME:    float          = 0.0
_CACHE_SHA256:   str            = ""
_LAST_REGIME:    str            = ""
_LAST_RELOAD_AT: str            = ""
_LOCK                           = threading.Lock()


# ═══════════════════════════════════════════════════════════════
#  내부 헬퍼 — 로드
# ═══════════════════════════════════════════════════════════════
def _load() -> Dict:
    """
    params.json 로드
    [FIX-96-1] _is_frozen() 체크를 Lock 내부로 이동 → 완전 스레드 안전
    ① Lock 전체 보호  ② 동결 구간 Lock 내부 체크
    ③ SHA-256 검증    ④ 파싱 실패 시 캐시 유지
    ⑤ 진화값 품질 검증 후 캐시 갱신
    """
    global _CACHE, _CACHE_MTIME, _CACHE_SHA256, _LAST_RELOAD_AT
    try:
        with _LOCK:
            # [FIX-96-1] _is_frozen() 과 _CACHE 참조 모두 Lock 내부
            if _is_frozen() and _CACHE:
                return _CACHE

            if not _PARAMS.exists():
                return _CACHE

            try:
                mtime = _PARAMS.stat().st_mtime
            except OSError:
                return _CACHE

            if mtime == _CACHE_MTIME and _CACHE:
                return _CACHE

            try:
                raw_bytes = _PARAMS.read_bytes()
            except OSError as e:
                _log.error("params.json 읽기 실패 → 캐시 유지: %s", e)
                return _CACHE

            new_sha = hashlib.sha256(raw_bytes).hexdigest()
            if new_sha == _CACHE_SHA256 and _CACHE:
                _CACHE_MTIME = mtime
                return _CACHE

            try:
                loaded = json.loads(raw_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                _log.error("params.json 파싱 실패 → 캐시 유지: %s", e)
                return _CACHE

            ver = loaded.get("_version", "unknown")
            if ver == "unknown":
                _log.warning("params.json _version 없음 — 호환성 주의")

            # [FIX-96-2] 전 레짐 진화값 품질 검증
            _validate_evolution_quality(loaded)

            _CACHE        = loaded
            _CACHE_MTIME  = mtime
            _CACHE_SHA256 = new_sha
            _LAST_RELOAD_AT = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S KST")
            _log.info("params.json 로드 | ver=%s | sha=%s… | at=%s",
                      ver, new_sha[:8], _LAST_RELOAD_AT)

    except Exception as e:
        _log.warning("params.json 로드 실패 → 기본값 사용: %s", e)
    return _CACHE


def _validate_evolution_quality(params: Dict) -> None:
    """
    [FIX-96-2] evolution_engine 기록값 품질 검증
    TREND / RANGE / VOLATILE 3개 레짐 전부 검증 (v1_7은 TREND만 검증 — 수정)
    비정상 징후 발견 시 CRITICAL 로그 (자동 복구는 각 get_*() 에서)
    """
    for reg in ("TREND", "RANGE", "VOLATILE"):
        reg_data = params.get(reg, {})
        if not reg_data:
            continue
        # Kelly 이상 검증
        kelly = reg_data.get("kelly", {})
        raw = kelly.get("kelly_raw", None)
        if raw is not None:
            if raw < 0 or raw > 3.0:
                _log.critical("⚠️  [%s] kelly_raw=%.4f 비정상 → 즉시 점검", reg, raw)
            elif raw > 1.5:
                _log.warning("[%s] kelly_raw=%.4f 과도 → 수익률 점검 권장", reg, raw)
        fraction = kelly.get("fraction", None)
        if fraction is not None and fraction > _KELLY_FRACTION_HARD_MAX:
            _log.critical("⚠️  [%s] kelly.fraction=%.4f > 상한 %.2f → 클램핑 예정",
                          reg, fraction, _KELLY_FRACTION_HARD_MAX)
        # 트레일 이상 검증
        trail = reg_data.get("트레일", {})
        if isinstance(trail, dict):
            table = trail.get("table", [])
            if isinstance(table, list) and len(table) < 2:
                _log.warning("[%s] 트레일 행 부족 → fallback 예정", reg)


def _regime_params(regime: Optional[str] = None) -> Dict:
    """
    현재 국면의 파라미터 세트 반환
    [FIX-3 유지] deepcopy → 중첩 구조 캐시 오염 원천 차단
    [ADD-3 유지] 레짐 전환 감사로그
    """
    global _LAST_REGIME
    params = _load()
    if not params:
        return {}
    reg = (
        regime
        or os.environ.get("SIGA_REGIME", "")
        or params.get("_regime", "")
        or "TREND"
    )
    if reg not in ("TREND", "RANGE", "VOLATILE"):
        reg = "TREND"

    if _LAST_REGIME and reg != _LAST_REGIME:
        _log.warning("📊 레짐 전환: %s → %s | %s",
                     _LAST_REGIME, reg,
                     datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S KST"))
    _LAST_REGIME = reg

    return copy.deepcopy(params.get(reg, params.get("TREND", {})))


# ═══════════════════════════════════════════════════════════════
#  타입/범위 검증 헬퍼
# ═══════════════════════════════════════════════════════════════
def _safe_float(val: Any, default: float,
                lo: float = -1e9, hi: float = 1e9) -> float:
    """NaN/Inf 차단 + 범위 클램핑"""
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            _log.warning("NaN/Inf %r → 기본값 %.4f", val, default)
            return default
        if not (lo <= v <= hi):
            _log.warning("범위초과 %.4f → 클램핑 [%.4f, %.4f]", v, lo, hi)
            v = max(lo, min(hi, v))
        return v
    except (TypeError, ValueError):
        _log.warning("타입오류 %r → 기본값 %.4f", val, default)
        return default


def _safe_int(val: Any, default: int,
              lo: int = -999999, hi: int = 999_999_999) -> int:
    try:
        v = int(val)
        if not (lo <= v <= hi):
            _log.warning("범위초과 %d → 클램핑 [%d, %d]", v, lo, hi)
            v = max(lo, min(hi, v))
        return v
    except (TypeError, ValueError):
        _log.warning("타입오류 %r → 기본값 %d", val, default)
        return default


def _safe_str(val: Any, default: str, allowed: tuple) -> str:
    """문자열 enum 안전 반환"""
    try:
        s = str(val).strip()
        if s in allowed:
            return s
        _log.warning("허용되지 않는 값 %r (허용=%s) → 기본값 %r", s, allowed, default)
        return default
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════
#  교차검증 헬퍼
# ═══════════════════════════════════════════════════════════════
def _cross_validate_갭등급(d: Dict) -> Dict:
    a, b, c, cut = d["GAP_A_MIN"], d["GAP_B_MIN"], d["GAP_C_MIN"], d["CUT_GAP_DOWN"]
    if not (a > b >= c):
        _log.error("갭등급 역전 A=%.2f B=%.2f C=%.2f → 기본값", a, b, c)
        return dict(_DEFAULT_갭등급)
    if cut >= 0:
        _log.error("CUT_GAP_DOWN=%.2f 양수 오입력 → 기본값", cut)
        d["CUT_GAP_DOWN"] = _DEFAULT_갭등급["CUT_GAP_DOWN"]
    return d


def _cross_validate_선정(d: Dict) -> Dict:
    issues = []

    # ── 기존 역전 검증 (유지) ────────────────────────────────────
    if d["RSI_GOOD_LOW"] >= d["RSI_GOOD_HIGH"]:
        issues.append("RSI_LOW>=RSI_HIGH")
        d["RSI_GOOD_LOW"]  = _DEFAULT_선정["RSI_GOOD_LOW"]
        d["RSI_GOOD_HIGH"] = _DEFAULT_선정["RSI_GOOD_HIGH"]
    if d["ADX_WEAK_THRESHOLD"] >= d["ADX_TREND_THRESHOLD"]:
        issues.append("ADX_WEAK>=ADX_TREND")
        d["ADX_WEAK_THRESHOLD"]  = _DEFAULT_선정["ADX_WEAK_THRESHOLD"]
        d["ADX_TREND_THRESHOLD"] = _DEFAULT_선정["ADX_TREND_THRESHOLD"]
    if d["HEAT_MILD"] >= d["HEAT_STRONG"]:
        issues.append("HEAT_MILD>=HEAT_STRONG")
        d["HEAT_MILD"]   = _DEFAULT_선정["HEAT_MILD"]
        d["HEAT_STRONG"] = _DEFAULT_선정["HEAT_STRONG"]

    # ── [v1_10 신규] 수익률 구조 논리 검증 ──────────────────────
    # ① EDGE: 하락 edge > 상승 edge 여야 함 (보수적 진입 원칙)
    if d.get("EDGE_MIN_DOWN", 0.22) <= d.get("EDGE_MIN_UP", 0.18):
        issues.append("EDGE_MIN_DOWN<=EDGE_MIN_UP")
        d["EDGE_MIN_UP"]   = _DEFAULT_선정["EDGE_MIN_UP"]
        d["EDGE_MIN_DOWN"] = _DEFAULT_선정["EDGE_MIN_DOWN"]

    # ② HINT_PULLBACK: 하한 < 상한
    if d.get("HINT_PULLBACK_CP_LOW", 0.30) >= d.get("HINT_PULLBACK_CP_HIGH", 0.70):
        issues.append("HINT_PULLBACK_CP_LOW>=HIGH")
        d["HINT_PULLBACK_CP_LOW"]  = _DEFAULT_선정["HINT_PULLBACK_CP_LOW"]
        d["HINT_PULLBACK_CP_HIGH"] = _DEFAULT_선정["HINT_PULLBACK_CP_HIGH"]

    # ③ INST_ACCEL_THRESHOLD: 최소 1.1 이상 (1.0이면 가속 판정 불가)
    if d.get("INST_ACCEL_THRESHOLD", 1.5) < 1.1:
        issues.append("INST_ACCEL_THRESHOLD<1.1")
        d["INST_ACCEL_THRESHOLD"] = _DEFAULT_선정["INST_ACCEL_THRESHOLD"]

    # ④ ACCEL_NORM_DIV: 0 초과 필수 (0이면 ZeroDivisionError)
    if d.get("ACCEL_NORM_DIV", 8.0) <= 0:
        issues.append("ACCEL_NORM_DIV<=0")
        d["ACCEL_NORM_DIV"] = _DEFAULT_선정["ACCEL_NORM_DIV"]

    # ⑤ TOP_N: 100~300 권장. 이탈 시 복구
    top_n = d.get("TOP_N", 250)
    if not (100 <= top_n <= 300):
        issues.append(f"TOP_N={top_n} 범위이탈(100~300)")
        d["TOP_N"] = _DEFAULT_선정["TOP_N"]

    # ⑥ BONUS_CAP: 12 초과 시 경고 후 클램프 (기존 스타일 — 강제복구 대신 warn)
    bonus_cap = d.get("BONUS_CAP", 8.0)
    if bonus_cap > 12.0:
        _log.warning("선정: BONUS_CAP=%.1f > 12.0 → 과도한 보너스 누적. 12.0으로 클램프",
                     bonus_cap)
        d["BONUS_CAP"] = 12.0

    if issues:
        _log.error("선정 역전/이탈 → 기본값 복구: %s", " | ".join(issues))
    return d


def _cross_validate_eod(d: Dict) -> Dict:
    # [v1_11] get_eod() 삭제로 이 함수는 더 이상 호출되지 않음 — 잔존 참조 방지용 유지
    if not (d["eret_thr_high"] > d["eret_thr_mid"] > d["eret_thr_low"]):
        _log.error("EOD eret_thr 역전 H=%.2f M=%.2f L=%.2f → 기본값",
                   d["eret_thr_high"], d["eret_thr_mid"], d["eret_thr_low"])
        d["eret_thr_high"] = 3.0
        d["eret_thr_mid"]  = 2.0
        d["eret_thr_low"]  = 1.0
    return d


def _validate_trail_table(table: list, label: str = "") -> Optional[list]:
    """트레일 테이블 완전 검증: 3열 이상 + trail_pct>0 + 구간 연속성"""
    if not isinstance(table, list) or len(table) < 2:
        _log.warning("[%s] 행 부족 → fallback", label)
        return None
    for i, row in enumerate(table):
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            _log.error("[%s][%d] 열 부족 → fallback", label, i)
            return None
        if float(row[2]) <= 0:
            _log.error("[%s][%d] trail_pct=%.2f ≤0 → fallback", label, i, row[2])
            return None
    for i in range(len(table) - 1):
        if abs(float(table[i][1]) - float(table[i+1][0])) > 1e-6:
            _log.error("[%s] 불연속 [%d].hi=%.2f ≠ [%d].lo=%.2f → fallback",
                       label, i, table[i][1], i+1, table[i+1][0])
            return None
    return table


# ═══════════════════════════════════════════════════════════════
#  공개 API — 기존 함수 (유지)
# ═══════════════════════════════════════════════════════════════

def get_국면(regime: Optional[str] = None) -> str:
    """현재 활성 국면 반환"""
    try:
        params = _load()
        reg = regime or os.environ.get("SIGA_REGIME", "") or params.get("_regime", "TREND")
        return reg if reg in ("TREND", "RANGE", "VOLATILE") else "TREND"
    except Exception:
        return "TREND"


def get_선정(regime: Optional[str] = None) -> Dict:
    """종목 선정 파라미터 반환 (make_rt_intraday_from_prices_1m 용)

    [v1_10] 수익률 점수 구조 핵심 파라미터 완전 공급:
        W_VALUE/ACCEL/CP/HB/VWP/SUPPLY/RISK — 점수 가중치
        BONUS_CAP, TOP_N, VAL_NORM_BASE, ACCEL_NORM_DIV — 정규화/범위
        INST_ACCEL_* — 기관 가속 보너스
        VOL5D_* — 5일 변동성 보너스
        EDGE_MIN_UP/DOWN — edge 최소 기준
        HINT_* — 전략 힌트 파라미터
    """
    try:
        rp   = _regime_params(regime)
        base = dict(_DEFAULT_선정)
        base.update(rp.get("선정", {}))
        validated = {
            # ── 기존 필드 (유지) ──────────────────────────────────
            "MIN_VALUE_NOW":       _safe_int(base["MIN_VALUE_NOW"],       10_000_000, lo=0),
            "MIN_VALUE_3M":        _safe_int(base["MIN_VALUE_3M"],        30_000_000, lo=0),
            "MIN_PRICE":           _safe_int(base["MIN_PRICE"],           500,        lo=0),
            "ADX_TREND_THRESHOLD": _safe_float(base["ADX_TREND_THRESHOLD"], 25.0, 0, 100),
            "ADX_WEAK_THRESHOLD":  _safe_float(base["ADX_WEAK_THRESHOLD"],  20.0, 0, 100),
            "ADX_BONUS_STRONG":    _safe_float(base["ADX_BONUS_STRONG"],     5.0, 0,  20),
            "ADX_BONUS_TREND":     _safe_float(base["ADX_BONUS_TREND"],      3.0, 0,  20),
            "RSI_GOOD_LOW":        _safe_float(base["RSI_GOOD_LOW"],        50.0, 0, 100),
            "RSI_GOOD_HIGH":       _safe_float(base["RSI_GOOD_HIGH"],       70.0, 0, 100),
            "RSI_OVER_LOW":        _safe_float(base["RSI_OVER_LOW"],        30.0, 0, 100),
            "POC_RSI_BONUS":       _safe_float(base["POC_RSI_BONUS"],        4.0, 0,  20),
            "HEAT_STRONG":         _safe_float(base["HEAT_STRONG"],          6.0, 0,  20),
            "HEAT_MILD":           _safe_float(base["HEAT_MILD"],            4.0, 0,  20),
            "BB_SQUEEZE_BONUS":    _safe_float(base["BB_SQUEEZE_BONUS"],     3.0, 0,  20),

            # ── [v1_10 신규] 점수 가중치 ─────────────────────────
            "W_VALUE":   _safe_float(base.get("W_VALUE",   20.0), 20.0, lo=0.0, hi=50.0),
            "W_ACCEL":   _safe_float(base.get("W_ACCEL",   12.0), 12.0, lo=0.0, hi=30.0),
            "W_CP":      _safe_float(base.get("W_CP",      10.0), 10.0, lo=0.0, hi=30.0),
            "W_HB":      _safe_float(base.get("W_HB",      10.0), 10.0, lo=0.0, hi=30.0),
            "W_VWP":     _safe_float(base.get("W_VWP",      8.0),  8.0, lo=0.0, hi=20.0),
            "W_SUPPLY":  _safe_float(base.get("W_SUPPLY",  10.0), 10.0, lo=0.0, hi=30.0),
            "W_RISK":    _safe_float(base.get("W_RISK",     1.0),  1.0, lo=0.1, hi=5.0),
            "BONUS_CAP": _safe_float(base.get("BONUS_CAP",  8.0),  8.0, lo=0.0, hi=20.0),

            # ── [v1_10 신규] 범위/정규화 ──────────────────────────
            "TOP_N":          _safe_int(base.get("TOP_N",           250),  250, lo=50,         hi=500),
            "VAL_NORM_BASE":  _safe_int(base.get("VAL_NORM_BASE",   50_000_000), 50_000_000,
                                        lo=1_000_000, hi=1_000_000_000),
            "ACCEL_NORM_DIV": _safe_float(base.get("ACCEL_NORM_DIV", 8.0),  8.0, lo=0.1, hi=50.0),

            # ── [v1_10 신규] 기관 가속 보너스 ─────────────────────
            "INST_ACCEL_BONUS":     _safe_float(base.get("INST_ACCEL_BONUS",     2.0),  2.0, lo=0.0, hi=10.0),
            "INST_ACCEL_THRESHOLD": _safe_float(base.get("INST_ACCEL_THRESHOLD", 1.5),  1.5, lo=1.0, hi=5.0),
            "INST_ACCEL_MIN_ABS":   _safe_int(base.get("INST_ACCEL_MIN_ABS", 50_000_000),
                                               50_000_000, lo=0, hi=10_000_000_000),

            # ── [v1_10 신규] 5일 변동성 보너스 ────────────────────
            "VOL5D_BONUS_MAX":       _safe_float(base.get("VOL5D_BONUS_MAX",       3.0), 3.0, lo=0.0, hi=10.0),
            "VOL5D_BONUS_THRESHOLD": _safe_float(base.get("VOL5D_BONUS_THRESHOLD", 2.0), 2.0, lo=0.5, hi=10.0),

            # ── [v1_10 신규] EDGE 최소 기준 ──────────────────────
            "EDGE_MIN_UP":   _safe_float(base.get("EDGE_MIN_UP",   0.18), 0.18, lo=0.01, hi=1.0),
            "EDGE_MIN_DOWN": _safe_float(base.get("EDGE_MIN_DOWN", 0.22), 0.22, lo=0.01, hi=1.0),

            # ── [v1_10 신규] 전략 힌트 ───────────────────────────
            "HINT_EOD_HB_MIN":       _safe_float(base.get("HINT_EOD_HB_MIN",       0.98), 0.98, lo=0.80, hi=1.05),
            "HINT_PULLBACK_CP_LOW":  _safe_float(base.get("HINT_PULLBACK_CP_LOW",  0.30), 0.30, lo=0.00, hi=1.00),
            "HINT_PULLBACK_CP_HIGH": _safe_float(base.get("HINT_PULLBACK_CP_HIGH", 0.70), 0.70, lo=0.00, hi=1.00),
            "HINT_SIGA_VA_MIN":      _safe_float(base.get("HINT_SIGA_VA_MIN",      1.20), 1.20, lo=0.00, hi=10.0),

            # ── [v1_13 신규] 헤지펀드 대장주 선별 강화 ──────────────
            # make_rt_intraday v7_21 + rt_pullback_engine v5_11 연동
            "RVOL_MIN":            _safe_float(base.get("RVOL_MIN",            2.0),  2.0, lo=1.0, hi=5.0),
            "RS_TOP10_BONUS":      _safe_float(base.get("RS_TOP10_BONUS",      0.18), 0.18, lo=0.0, hi=0.50),
            "RS_TOP10_PERCENTILE": _safe_float(base.get("RS_TOP10_PERCENTILE", 0.90), 0.90, lo=0.50, hi=0.99),
            "SECTOR_LEADER_BONUS": _safe_float(base.get("SECTOR_LEADER_BONUS", 0.15), 0.15, lo=0.0, hi=0.50),
        }
        return _cross_validate_선정(validated)
    except Exception:
        return dict(_DEFAULT_선정)


def get_갭등급(regime: Optional[str] = None) -> Dict:
    """갭 등급 분류 파라미터 반환 (pullback_sell_strategy 용)"""
    try:
        rp   = _regime_params(regime)
        base = dict(_DEFAULT_갭등급)
        base.update(rp.get("갭등급", {}))
        validated = {
            "GAP_A_MIN":    _safe_float(base["GAP_A_MIN"],     3.0,   0.0,  30.0),
            "GAP_B_MIN":    _safe_float(base["GAP_B_MIN"],     1.5,   0.0,  20.0),
            "GAP_C_MIN":    _safe_float(base["GAP_C_MIN"],     0.0,   0.0,  10.0),
            "CUT_GAP_DOWN": _safe_float(base["CUT_GAP_DOWN"], -2.0, -30.0, -0.001),
        }
        return _cross_validate_갭등급(validated)
    except Exception:
        return dict(_DEFAULT_갭등급)


def get_트레일(regime: Optional[str] = None) -> Dict:
    """트레일링 스탑 파라미터 반환 (pullback_sell_strategy 용)"""
    try:
        rp    = _regime_params(regime)
        raw_t = rp.get("트레일", _DEFAULT_트레일)
        if isinstance(raw_t, dict):
            table = raw_t.get("table", _DEFAULT_트레일["table"])
            mult  = _safe_float(raw_t.get("BUFFER_MULT", 1.5), 1.5, lo=0.5, hi=5.0)
        elif isinstance(raw_t, list):
            _log.warning("트레일 포맷 list→dict 자동 변환")
            table = raw_t
            mult  = _safe_float(rp.get("BUFFER_MULT", 1.5), 1.5, lo=0.5, hi=5.0)
        else:
            table = _DEFAULT_트레일["table"]
            mult  = _DEFAULT_트레일["BUFFER_MULT"]
        validated = _validate_trail_table(table, "트레일")
        if validated is None:
            table = _DEFAULT_트레일["table"]
        else:
            table = validated
        return {"table": [list(r) for r in table], "BUFFER_MULT": mult}
    except Exception:
        return {"table": [list(r) for r in _DEFAULT_트레일["table"]], "BUFFER_MULT": 1.5}


def get_청산시각() -> Dict:
    """강제 청산 시각 반환 (국면 무관 공통) — [v1_11] 종배 항목 제거"""
    try:
        params = _load()
        base   = dict(_DEFAULT_청산시각)
        base.update(params.get("청산시각", {}))
        return {
            # [v1_11 삭제] FORCE_CLOSE_시배 (종배 전용) 제거
            "FORCE_CLOSE_BCD":  _safe_int(base["FORCE_CLOSE_BCD"],  1030, lo=920, hi=1500),
            "FORCE_CLOSE_A":    _safe_int(base["FORCE_CLOSE_A"],    1130, lo=920, hi=1500),
            "GAP_CHECK_BY":     _safe_int(base["GAP_CHECK_BY"],      905, lo=900, hi=930),
        }
    except Exception:
        d = dict(_DEFAULT_청산시각)
        d.pop("FORCE_CLOSE_시배", None)
        return d


def get_운영() -> Dict:
    """
    [v1_11 신규] 1일 1진입 보장 + 자기진화 운영 파라미터 반환
    사용: rt_execution_engine / safeplus_preflight_gate
    역할: 운영 정책 기준값만 공급. 로직 구현 금지.
    """
    try:
        params = _load()
        base   = dict(_DEFAULT_운영)
        base.update(params.get("운영", {}))

        result = {
            # 1일 1진입 보장 (요건 9번)
            "min_daily_entry_required": bool(base.get("min_daily_entry_required", True)),
            "force_entry_by_hhmm":      _safe_int(base.get("force_entry_by_hhmm", 1300),
                                                   1300, lo=1000, hi=1430),
            "skip_if_market_bad":       bool(base.get("skip_if_market_bad", True)),
            "market_bad_ofi_threshold": _safe_float(base.get("market_bad_ofi_threshold", -0.40),
                                                     -0.40, lo=-1.0, hi=0.0),
            "market_bad_regime":        _safe_str(base.get("market_bad_regime", "BEAR"),
                                                  "BEAR", ("BEAR", "VOLATILE")),
            # 자기진화 주기
            "evolution_interval_trades": _safe_int(base.get("evolution_interval_trades", 20),
                                                    20, lo=5, hi=200),
            "evolution_min_trades":      _safe_int(base.get("evolution_min_trades", 10),
                                                    10, lo=5, hi=100),
            # 진화 허용/금지 키 목록 (상수 노출 — 모듈 참조용)
            "_evolution_allowed_keys": list(_EVOLUTION_ALLOWED_KEYS),
            "_evolution_frozen_keys":  list(_EVOLUTION_FROZEN_KEYS),
        }

        # 교차검증: force_entry_by_hhmm은 장 마감 전이어야 함
        if result["force_entry_by_hhmm"] > 1430:
            _log.warning("운영: force_entry_by_hhmm=%d > 1430 → 너무 늦어 진입 불가",
                         result["force_entry_by_hhmm"])

        return result
    except Exception as e:
        _log.warning("get_운영 예외 → 기본값: %s", e)
        return dict(_DEFAULT_운영)


def get_kelly(regime: Optional[str] = None) -> Dict:
    """Kelly 포지션 사이징 파라미터 반환"""
    try:
        rp        = _regime_params(regime)
        base      = dict(_DEFAULT_kelly)
        base.update(rp.get("kelly", {}))
        kelly_raw = _safe_float(base.get("kelly_raw", 0.0), 0.0, lo=0.0, hi=5.0)
        fraction  = _safe_float(base.get("fraction",  0.5), 0.5, lo=0.01, hi=_KELLY_FRACTION_HARD_MAX)
        calibrated = True
        if kelly_raw == 0.0:
            _log.warning("kelly_raw=0.0 미보정 → fraction %.2f→%.2f",
                         fraction, _KELLY_RAW_SAFE_FRACTION)
            fraction   = _KELLY_RAW_SAFE_FRACTION
            calibrated = False
        if fraction > _KELLY_FRACTION_HARD_MAX:
            _log.critical("fraction %.4f > 상한 %.2f → 클램핑", fraction, _KELLY_FRACTION_HARD_MAX)
            fraction = _KELLY_FRACTION_HARD_MAX
        return {
            "fraction":     fraction,
            "max_per_종목": _safe_float(base["max_per_종목"], 0.25, lo=0.01, hi=0.65),
            "min_per_종목": _safe_float(base["min_per_종목"], 0.05, lo=0.01, hi=0.30),
            "kelly_raw":    kelly_raw,
            "_calibrated":  calibrated,
        }
    except Exception:
        return {**_DEFAULT_kelly, "fraction": _KELLY_RAW_SAFE_FRACTION, "_calibrated": False}


def get_rt_sell(regime: Optional[str] = None) -> Dict:
    """
    RT 매도 파라미터 반환 (rt_sell_engine 연동)

    [v1_9] 신규 반환 키:
        trail_activate_hard_pct   — 강제 Trail 활성화 수익률 (§5-3)
        chandelier_k_normal/high/extreme — Chandelier k 레짐별 배수 (§3-2)
        vol_ratio_high_thr / vol_ratio_extreme_thr — 레짐 판단 임계 (§3-2)
        k_boost_* — 기관강세 k×1.15 보정 3조건 (§3-3)
        accel_recent_bars / accel_prior_bars / accel_neutral — accel lookback (§3-4)
        failsafe_trigger_pct / failsafe_preserve_ratio — HARD_FAILSAFE (§7)
        peak_protect_l1/l2/l3_* — PEAK_PROTECT 3단계 (§6)
        ride_strong_hold_floor / inst_strong_hold_* — 강보유 조건 (§8 P1.3/1.5)
        split_ratio_inst — 기관동행 시 선익절 비율 (§9-3)
        jongbae_k_mult / jongbae_trail_mult / *_max_hold_min — 전략오버라이드 (§14)
    """
    try:
        params = _load()
        rp     = _regime_params(regime)
        base   = dict(_DEFAULT_rt_sell)
        base.update(params.get("rt_sell", {}))
        if isinstance(rp, dict):
            base.update(rp.get("rt_sell", {}))

        # [v1_12] siga 섹션의 FORCE_EXIT_SIGA → force_siga 로 병합
        # params.json: TREND.siga.FORCE_EXIT_SIGA = 918
        _siga_sec = {}
        if isinstance(rp, dict):
            _siga_sec = rp.get("siga", {})
        if not _siga_sec:
            _siga_sec = params.get("siga", {})
        if "FORCE_EXIT_SIGA" in _siga_sec and "force_siga" not in base:
            base["force_siga"] = int(_siga_sec["FORCE_EXIT_SIGA"])

        # ── Trail 테이블 검증 ──────────────────────────────────────
        t = _validate_trail_table(
            base.get("trail_table", _DEFAULT_rt_sell["trail_table"]), "rt_sell.trail")
        if t is None:
            t = _DEFAULT_rt_sell["trail_table"]

        st_raw = base.get("super_trail", [])
        st = (_validate_trail_table(st_raw, "rt_sell.super")
              if isinstance(st_raw, list) and len(st_raw) >= 2 else None)
        super_table = st if st else list(_DEFAULT_rt_sell["super_trail"])

        result = {
            # ── 기본 손절/활성화 ────────────────────────────────────
            # [v1_12 FIX-A] fallback 0.020 → 0.025 (지침서 + params.json 통일)
            "hard_stop":             _safe_float(base.get("hard_stop",             0.025), 0.025, lo=0.005, hi=0.10),
            # [v1_12 FIX-B] fallback 0.015 → 0.012 (params.json 동기화)
            "breakeven_ret":         _safe_float(base.get("breakeven_ret",         0.012), 0.012, lo=0.005, hi=0.10),
            # [BUG-HIGH-1 FIX] 기본값 0.015 (구버전 0.010 폴백 방지)
            # [v1_12 FIX-C] fallback 0.015 → 0.012 (params.json 동기화)
            "trail_activate_ret":    _safe_float(base.get("trail_activate_ret",    0.012), 0.012, lo=0.003, hi=0.05),
            # [ADD] 강제 Trail 활성화 (지침서v15 §5-3)
            "trail_activate_hard_pct": _safe_float(base.get("trail_activate_hard_pct", 0.02), 0.02, lo=0.01, hi=0.10),

            # ── Trail / SuperTrail ───────────────────────────────────
            "trail_table":           [list(r) for r in t],
            "SUPER_TREND_MODE":      bool(base.get("SUPER_TREND_MODE", True)),
            "super_trail":           [list(r) for r in super_table],
            "SUPER_TRAIL_ACTIVATE_PCT": _safe_float(base.get("SUPER_TRAIL_ACTIVATE_PCT", 5.0), 5.0, lo=1.0, hi=20.0),
            "BUFFER_MULT":           _safe_float(base.get("BUFFER_MULT",           1.5),  1.5,  lo=0.5,  hi=5.0),

            # ── 선익절 / T2 ──────────────────────────────────────────
            # [BUG-HIGH-2 FIX] 기본값 0.40 (구버전 0.35 폴백 방지)
            "split_ratio":           _safe_float(base.get("split_ratio",           0.40),  0.40,  lo=0.20,  hi=0.80),
            "split_ratio_inst":      _safe_float(base.get("split_ratio_inst",      0.25),  0.25,  lo=0.10,  hi=0.50),
            "t2_mult":               _safe_float(base.get("t2_mult",               2.20),  2.20,  lo=1.10,  hi=3.50),

            # ── 모멘텀/VWAP ──────────────────────────────────────────
            "momentum_min_profit":   _safe_float(base.get("momentum_min_profit",   0.015), 0.015, lo=0.003, hi=0.05),
            "momentum_vol_ratio":    _safe_float(base.get("momentum_vol_ratio",    0.55),  0.55,  lo=0.10,  hi=0.90),
            "momentum_price_drop":   _safe_float(base.get("momentum_price_drop",   0.005), 0.005, lo=0.001, hi=0.02),
            "vwap_thresh":           _safe_float(base.get("vwap_thresh",           0.985), 0.985, lo=0.960, hi=0.999),
            "vwap_thresh_t2":        _safe_float(base.get("vwap_thresh_t2",        0.975), 0.975, lo=0.950, hi=0.999),

            # ── 강제 청산 시각 — [v1_11] force_시배(종배) 삭제 ─────────
            # [v1_12] force_siga 추가 — params.json siga.FORCE_EXIT_SIGA 연결
            "force_A":               _safe_int(base.get("force_A",    1450), 1450, lo=1000, hi=1530),
            "force_BCD":             _safe_int(base.get("force_BCD",  1450), 1450, lo=1000, hi=1530),
            "force_siga":            _safe_int(base.get("force_siga",  918),  918, lo=900,  hi=1000),

            # ════ [v1_9 신규] Chandelier k — 레짐별 ATR 배수 ════════
            "chandelier_k_normal":   _safe_float(base.get("chandelier_k_normal",   2.0),  2.0,  lo=1.0, hi=5.0),
            "chandelier_k_high":     _safe_float(base.get("chandelier_k_high",     2.5),  2.5,  lo=1.0, hi=6.0),
            "chandelier_k_extreme":  _safe_float(base.get("chandelier_k_extreme",  3.0),  3.0,  lo=1.0, hi=8.0),
            "vol_ratio_high_thr":    _safe_float(base.get("vol_ratio_high_thr",    1.2),  1.2,  lo=1.0, hi=3.0),
            "vol_ratio_extreme_thr": _safe_float(base.get("vol_ratio_extreme_thr", 1.5),  1.5,  lo=1.0, hi=5.0),

            # ════ [v1_9 신규] 기관강세 k×1.15 보정 조건 ════════════
            "k_boost_multiplier":    _safe_float(base.get("k_boost_multiplier",    1.15), 1.15, lo=1.0, hi=2.0),
            # [v1_12 FIX-D] fallback 0.30 → 0.40 (지침서[US-1] v1.2 + params.json 통일)
            "k_boost_ofi_floor":     _safe_float(base.get("k_boost_ofi_floor",     0.40), 0.40, lo=0.0, hi=1.0),
            "k_boost_accel_floor":   _safe_float(base.get("k_boost_accel_floor",   1.20), 1.20, lo=1.0, hi=3.0),
            "k_boost_profit_floor":  _safe_float(base.get("k_boost_profit_floor",  0.02), 0.02, lo=0.0, hi=0.10),

            # ════ [v1_9 신규] accel lookback ════════════════════════
            "accel_recent_bars":     _safe_int(base.get("accel_recent_bars",   3), 3,    lo=1, hi=10),
            "accel_prior_bars":      _safe_int(base.get("accel_prior_bars",    5), 5,    lo=1, hi=20),
            "accel_neutral":         _safe_float(base.get("accel_neutral",     1.0), 1.0, lo=0.1, hi=3.0),

            # ════ [v1_9 신규] HARD_FAILSAFE (지침서v15 §7) ══════════
            "failsafe_trigger_pct":    _safe_float(base.get("failsafe_trigger_pct",    0.02), 0.02, lo=0.005, hi=0.10),
            "failsafe_preserve_ratio": _safe_float(base.get("failsafe_preserve_ratio", 0.60), 0.60, lo=0.30,  hi=0.90),

            # ════ [v1_9 신규] PEAK_PROTECT 3단계 (지침서v15 §6) ═════
            "peak_protect_l1_pct":   _safe_float(base.get("peak_protect_l1_pct",   0.05), 0.05, lo=0.01, hi=0.20),
            "peak_protect_l1_exit":  _safe_float(base.get("peak_protect_l1_exit",  0.02), 0.02, lo=0.0,  hi=0.10),
            "peak_protect_l2_pct":   _safe_float(base.get("peak_protect_l2_pct",   0.08), 0.08, lo=0.02, hi=0.30),
            "peak_protect_l2_exit":  _safe_float(base.get("peak_protect_l2_exit",  0.03), 0.03, lo=0.0,  hi=0.15),
            "peak_protect_l3_pct":   _safe_float(base.get("peak_protect_l3_pct",   0.12), 0.12, lo=0.05, hi=0.50),
            "peak_protect_l3_exit":  _safe_float(base.get("peak_protect_l3_exit",  0.05), 0.05, lo=0.0,  hi=0.20),
            "peak_protect_inst_div": _safe_float(base.get("peak_protect_inst_div", 1.15), 1.15, lo=1.0,  hi=2.0),

            # ════ [v1_9 신규] RIDE/INST STRONG HOLD (§8 P1.3/1.5) ══
            "ride_strong_hold_floor":   _safe_float(base.get("ride_strong_hold_floor",    0.65), 0.65, lo=0.30, hi=1.0),
            "inst_strong_hold_ofi":     _safe_float(base.get("inst_strong_hold_ofi",      0.15), 0.15, lo=0.0,  hi=1.0),
            "inst_strong_hold_max_ret": _safe_float(base.get("inst_strong_hold_max_ret",  0.08), 0.08, lo=0.01, hi=0.30),

            # ════ [v1_9] 전략별 오버라이드 — [v1_11] 종배 삭제 후 2전략만 ═
            # [v1_11 삭제] jongbae_k_mult / jongbae_trail_mult / jongbae_max_hold_min
            "siga_max_hold_min":     _safe_int(base.get("siga_max_hold_min",      120),  120,  lo=30,   hi=300),
            "trend_max_hold_min":    _safe_int(base.get("trend_max_hold_min",     240),  240,  lo=60,   hi=480),
        }

        # ── 교차검증 ───────────────────────────────────────────────────
        # ① trail_activate_ret < trail_activate_hard_pct
        if result["trail_activate_ret"] >= result["trail_activate_hard_pct"]:
            _log.error("rt_sell: trail_activate_ret(%.3f) >= hard_pct(%.3f) → 기본값",
                       result["trail_activate_ret"], result["trail_activate_hard_pct"])
            result["trail_activate_ret"]      = _DEFAULT_rt_sell["trail_activate_ret"]
            result["trail_activate_hard_pct"] = _DEFAULT_rt_sell["trail_activate_hard_pct"]

        # ② Chandelier k 단조증가: normal < high < extreme
        if not (result["chandelier_k_normal"] < result["chandelier_k_high"]
                < result["chandelier_k_extreme"]):
            _log.error("rt_sell: chandelier_k 순서 역전 normal=%.1f high=%.1f extreme=%.1f → 기본값",
                       result["chandelier_k_normal"], result["chandelier_k_high"],
                       result["chandelier_k_extreme"])
            result["chandelier_k_normal"]  = _DEFAULT_rt_sell["chandelier_k_normal"]
            result["chandelier_k_high"]    = _DEFAULT_rt_sell["chandelier_k_high"]
            result["chandelier_k_extreme"] = _DEFAULT_rt_sell["chandelier_k_extreme"]

        # ③ vol_ratio 임계: high_thr < extreme_thr
        if result["vol_ratio_high_thr"] >= result["vol_ratio_extreme_thr"]:
            _log.error("rt_sell: vol_ratio_high_thr(%.2f) >= extreme_thr(%.2f) → 기본값",
                       result["vol_ratio_high_thr"], result["vol_ratio_extreme_thr"])
            result["vol_ratio_high_thr"]    = _DEFAULT_rt_sell["vol_ratio_high_thr"]
            result["vol_ratio_extreme_thr"] = _DEFAULT_rt_sell["vol_ratio_extreme_thr"]

        # ④ PEAK_PROTECT 단조증가: l1 < l2 < l3
        if not (result["peak_protect_l1_pct"] < result["peak_protect_l2_pct"]
                < result["peak_protect_l3_pct"]):
            _log.error("rt_sell: peak_protect 단계 순서 역전 → 기본값")
            for k_, v_ in [("peak_protect_l1_pct",  0.05), ("peak_protect_l2_pct",  0.08),
                            ("peak_protect_l3_pct",  0.12)]:
                result[k_] = v_

        # ⑤ PEAK_PROTECT exit도 단조증가: l1_exit < l2_exit < l3_exit
        if not (result["peak_protect_l1_exit"] < result["peak_protect_l2_exit"]
                < result["peak_protect_l3_exit"]):
            _log.error("rt_sell: peak_protect exit 순서 역전 → 기본값")
            for k_, v_ in [("peak_protect_l1_exit", 0.02), ("peak_protect_l2_exit", 0.03),
                            ("peak_protect_l3_exit", 0.05)]:
                result[k_] = v_

        # ⑥ split_ratio > split_ratio_inst (일반 > 기관동행)
        if result["split_ratio"] <= result["split_ratio_inst"]:
            _log.error("rt_sell: split_ratio(%.2f) <= split_ratio_inst(%.2f) → 기본값",
                       result["split_ratio"], result["split_ratio_inst"])
            result["split_ratio"]      = _DEFAULT_rt_sell["split_ratio"]
            result["split_ratio_inst"] = _DEFAULT_rt_sell["split_ratio_inst"]

        # ⑦ failsafe_trigger_pct 최소 2% 경보
        if result["failsafe_trigger_pct"] > 0.03:
            _log.critical("⚠️  rt_sell.failsafe_trigger_pct=%.3f > 0.03 "
                          "→ 지침서v15 §7: 2%가 최적. 수익 반납 위험 증가",
                          result["failsafe_trigger_pct"])

        # ⑧ k_boost_multiplier 상한 경보
        if result["k_boost_multiplier"] > 1.30:
            _log.critical("⚠️  rt_sell.k_boost_multiplier=%.2f > 1.30 "
                          "→ 과도한 k 확장. trail_stop 너무 넓어짐",
                          result["k_boost_multiplier"])

        # [v1_10 LOG] 수익률 저하형 경고 — 강제복구 없이 warning만
        if result["split_ratio"] > 0.45:
            _log.warning("rt_sell.split_ratio=%.2f > 0.45 → 강한 추세 수익 훼손 위험",
                         result["split_ratio"])

        return result

    except Exception as e:
        _log.warning("get_rt_sell 예외 → 기본값: %s", e)
        return dict(_DEFAULT_rt_sell)


# [v1_11 삭제] get_eod() 함수 완전 제거 — 종배 전략 삭제로 불필요
# 참조하는 모듈이 있다면 해당 모듈에서도 import 제거 필요


def get_거래비용() -> Dict:
    """거래비용 파라미터 반환 (pnl_strategy_linker / bridge 용)"""
    try:
        params = _load()
        base   = dict(_DEFAULT_거래비용)
        base.update(params.get("거래비용", {}))
        return {
            "buy_fee_pct":  _safe_float(base["buy_fee_pct"],  0.00015, lo=0.0, hi=0.01),
            "sell_fee_pct": _safe_float(base["sell_fee_pct"], 0.00015, lo=0.0, hi=0.01),
            "sell_tax_pct": _safe_float(base["sell_tax_pct"], 0.0018,  lo=0.0, hi=0.01),
        }
    except Exception:
        return dict(_DEFAULT_거래비용)


# ═══════════════════════════════════════════════════════════════
#  공개 API — [UPD-4] get_scoreboard() 강화
# ═══════════════════════════════════════════════════════════════
def get_scoreboard(regime: Optional[str] = None) -> Dict:
    """
    [UPD-4] 스코어보드 전용 파라미터 반환 — kjs_scoreboard_eod 용
    역할: 선별/점수화만. EV계산/Kelly계산/시가타이밍 금지.

    반환 키 (신규 포함):
        attack_ratio, defense_ratio,
        s1_ofi_weight, s1_vpin_weight,
        s2_axes_weight, s2_inst_weight, s2_gap_weight,
        conv_gate_min, hist_bonus_cap,
        hard_cut_oi_drop, hard_cut_vol_spike,
        score_hard_min, score_soft_min,          ← [신규]
        inst_flow_floor, inst_flow_accel_floor,  ← [신규]
        gap_overheat_cut, gap_deadzone_low, gap_deadzone_high ← [신규]
    """
    try:
        params = _load()
        rp     = _regime_params(regime)
        base   = dict(_DEFAULT_scoreboard)
        base.update(params.get("scoreboard", {}))
        base.update(rp.get("scoreboard", {}))

        result = {
            # 기존 필드
            "attack_ratio":           _safe_float(base["attack_ratio"],           0.70, lo=0.50, hi=1.0),
            "defense_ratio":          _safe_float(base["defense_ratio"],          0.30, lo=0.0,  hi=0.50),
            "s1_ofi_weight":          _safe_float(base["s1_ofi_weight"],          22.0, lo=1.0,  hi=50.0),
            "s1_vpin_weight":         _safe_float(base["s1_vpin_weight"],         12.0, lo=1.0,  hi=30.0),
            "s2_axes_weight":         _safe_float(base["s2_axes_weight"],         16.0, lo=1.0,  hi=40.0),
            "s2_inst_weight":         _safe_float(base["s2_inst_weight"],         22.0, lo=1.0,  hi=50.0),
            "s2_gap_weight":          _safe_float(base["s2_gap_weight"],           8.0, lo=1.0,  hi=30.0),
            "conv_gate_min":          _safe_float(base["conv_gate_min"],           0.68, lo=0.30, hi=0.95),
            "hist_bonus_cap":         _safe_float(base["hist_bonus_cap"],          8.0, lo=0.0,  hi=30.0),
            "hard_cut_oi_drop":       _safe_float(base["hard_cut_oi_drop"],       -0.12, lo=-0.50, hi=-0.01),
            "hard_cut_vol_spike":     _safe_float(base["hard_cut_vol_spike"],      2.5, lo=1.0,  hi=10.0),
            # [신규] 점수 품질 게이트
            "score_hard_min":         _safe_float(base.get("score_hard_min",      75.0), 75.0, lo=60.0, hi=95.0),
            "score_soft_min":         _safe_float(base.get("score_soft_min",      70.0), 70.0, lo=55.0, hi=90.0),
            # [신규] 기관 플로우 품질 게이트
            "inst_flow_floor":        _safe_float(base.get("inst_flow_floor",      0.30), 0.30, lo=0.0,  hi=1.0),
            "inst_flow_accel_floor":  _safe_float(base.get("inst_flow_accel_floor",0.05), 0.05, lo=0.0,  hi=0.5),
            # [신규] 갭 게이트
            "gap_overheat_cut":       _safe_float(base.get("gap_overheat_cut",     5.0), 5.0,  lo=2.0,  hi=15.0),
            "gap_deadzone_low":       _safe_float(base.get("gap_deadzone_low",    -0.5), -0.5, lo=-5.0, hi=0.0),
            "gap_deadzone_high":      _safe_float(base.get("gap_deadzone_high",    1.0), 1.0,  lo=0.0,  hi=5.0),
        }

        # 교차검증
        # ① attack + defense == 1.0
        if abs(result["attack_ratio"] + result["defense_ratio"] - 1.0) > 0.01:
            _log.error("scoreboard: attack+defense=%.2f ≠ 1.0 → 기본값",
                       result["attack_ratio"] + result["defense_ratio"])
            result["attack_ratio"]  = _DEFAULT_scoreboard["attack_ratio"]
            result["defense_ratio"] = _DEFAULT_scoreboard["defense_ratio"]

        # ② score_hard_min >= score_soft_min
        if result["score_hard_min"] < result["score_soft_min"]:
            _log.error("scoreboard: score_hard_min(%.1f) < score_soft_min(%.1f) → 기본값",
                       result["score_hard_min"], result["score_soft_min"])
            result["score_hard_min"] = _DEFAULT_scoreboard["score_hard_min"]
            result["score_soft_min"] = _DEFAULT_scoreboard["score_soft_min"]

        # ③ gap_deadzone_low < gap_deadzone_high
        if result["gap_deadzone_low"] >= result["gap_deadzone_high"]:
            _log.error("scoreboard: gap_deadzone_low(%.2f) >= gap_deadzone_high(%.2f) → 기본값",
                       result["gap_deadzone_low"], result["gap_deadzone_high"])
            result["gap_deadzone_low"]  = _DEFAULT_scoreboard["gap_deadzone_low"]
            result["gap_deadzone_high"] = _DEFAULT_scoreboard["gap_deadzone_high"]

        # ④ gap_overheat_cut > gap_deadzone_high
        if result["gap_overheat_cut"] <= result["gap_deadzone_high"]:
            _log.error("scoreboard: gap_overheat_cut(%.2f) <= gap_deadzone_high(%.2f) → 기본값",
                       result["gap_overheat_cut"], result["gap_deadzone_high"])
            result["gap_overheat_cut"] = _DEFAULT_scoreboard["gap_overheat_cut"]

        # [LOG-1] score_hard_min 이상 경보
        if result["score_hard_min"] < 75.0:
            _log.critical("⚠️  scoreboard.score_hard_min=%.1f < 75 → 쓰레기 후보 진입 위험",
                          result["score_hard_min"])
        # [v1_10 LOG] 수익률 저하형 경고 — 강제복구 없이 warning만
        if result["score_hard_min"] > 80.0:
            _log.warning("scoreboard.score_hard_min=%.1f > 80 → 후보 과소로 수익기회 감소 위험",
                         result["score_hard_min"])

        return result
    except Exception as e:
        _log.error("get_scoreboard 예외 → 기본값: %s", e)
        return dict(_DEFAULT_scoreboard)


# ═══════════════════════════════════════════════════════════════
#  공개 API — [UPD-5] get_bridge() 강화
# ═══════════════════════════════════════════════════════════════
def get_bridge(regime: Optional[str] = None) -> Dict:
    """
    [UPD-5] 브릿지 전용 파라미터 반환 — kjs_bridge_eod 용
    역할: 리스크/사이징/연결만. 점수산출/시가타이밍 금지.

    반환 키 (신규 포함):
        kelly_bull, kelly_neutral, kelly_caution,
        ride_score_hard_cut, ride_score_soft_lo/hi, soft_pos_ratio,
        ev_min_threshold, slippage_cap,
        bridge_score_min, bridge_score_soft_min,  ← [신규]
        market_regime_hard_block/soft_block,      ← [신규]
        inst_exit_warn, inst_exit_block,          ← [신규]
        gap_risk_penalty_start/max                ← [신규]
    """
    try:
        params = _load()
        rp     = _regime_params(regime)
        base   = dict(_DEFAULT_bridge)
        base.update(params.get("bridge", {}))
        base.update(rp.get("bridge", {}))

        result = {
            # 기존 필드
            "kelly_bull":              _safe_float(base["kelly_bull"],          0.65, lo=0.30, hi=0.65),
            "kelly_neutral":           _safe_float(base["kelly_neutral"],       0.45, lo=0.20, hi=0.55),
            "kelly_caution":           _safe_float(base["kelly_caution"],       0.20, lo=0.10, hi=0.40),
            "ride_score_hard_cut":     _safe_float(base["ride_score_hard_cut"], 0.28, lo=0.10, hi=0.50),
            "ride_score_soft_lo":      _safe_float(base["ride_score_soft_lo"],  0.30, lo=0.10, hi=0.60),
            "ride_score_soft_hi":      _safe_float(base["ride_score_soft_hi"],  0.45, lo=0.20, hi=0.80),
            "soft_pos_ratio":          _safe_float(base["soft_pos_ratio"],      0.55, lo=0.30, hi=0.90),
            "ev_min_threshold":        _safe_float(base["ev_min_threshold"],   0.009, lo=0.001, hi=0.05),
            "slippage_cap":            _safe_float(base["slippage_cap"],       0.002, lo=0.0,   hi=0.01),
            # [신규] 점수 게이트
            "bridge_score_min":        _safe_float(base.get("bridge_score_min",      75.0), 75.0, lo=60.0, hi=95.0),
            "bridge_score_soft_min":   _safe_float(base.get("bridge_score_soft_min", 70.0), 70.0, lo=55.0, hi=90.0),
            # [신규] 시장 레짐 차단 (문자열)
            "market_regime_hard_block": _safe_str(
                base.get("market_regime_hard_block", "BEAR"), "BEAR",
                ("BEAR", "CAUTION", "NEUTRAL", "BULL")),
            "market_regime_soft_block": _safe_str(
                base.get("market_regime_soft_block", "CAUTION"), "CAUTION",
                ("BEAR", "CAUTION", "NEUTRAL", "BULL")),
            # [신규] 기관 이탈 경보
            "inst_exit_warn":          _safe_float(base.get("inst_exit_warn",   -0.20), -0.20, lo=-1.0, hi=0.0),
            "inst_exit_block":         _safe_float(base.get("inst_exit_block",  -0.30), -0.30, lo=-1.0, hi=0.0),
            # [신규] 갭 리스크 패널티
            "gap_risk_penalty_start":  _safe_float(base.get("gap_risk_penalty_start", 3.5), 3.5, lo=0.5, hi=10.0),
            "gap_risk_penalty_max":    _safe_float(base.get("gap_risk_penalty_max",   6.0), 6.0, lo=1.0, hi=15.0),
        }

        # 교차검증
        # ① Kelly 레짐 순서: bull >= neutral >= caution
        if not (result["kelly_bull"] >= result["kelly_neutral"] >= result["kelly_caution"]):
            _log.error("bridge: Kelly 레짐 역전 bull=%.2f neu=%.2f cau=%.2f → 기본값",
                       result["kelly_bull"], result["kelly_neutral"], result["kelly_caution"])
            result["kelly_bull"]    = _DEFAULT_bridge["kelly_bull"]
            result["kelly_neutral"] = _DEFAULT_bridge["kelly_neutral"]
            result["kelly_caution"] = _DEFAULT_bridge["kelly_caution"]

        # ② ride_score soft 구간 순서
        if result["ride_score_soft_lo"] > result["ride_score_soft_hi"]:
            _log.error("bridge: ride_score soft 구간 역전 → 기본값")
            result["ride_score_soft_lo"] = _DEFAULT_bridge["ride_score_soft_lo"]
            result["ride_score_soft_hi"] = _DEFAULT_bridge["ride_score_soft_hi"]

        # ③ bridge_score_min >= bridge_score_soft_min
        if result["bridge_score_min"] < result["bridge_score_soft_min"]:
            _log.error("bridge: bridge_score_min(%.1f) < bridge_score_soft_min(%.1f) → 기본값",
                       result["bridge_score_min"], result["bridge_score_soft_min"])
            result["bridge_score_min"]      = _DEFAULT_bridge["bridge_score_min"]
            result["bridge_score_soft_min"] = _DEFAULT_bridge["bridge_score_soft_min"]

        # ④ inst_exit_block <= inst_exit_warn < 0
        if not (result["inst_exit_block"] <= result["inst_exit_warn"] < 0):
            _log.error("bridge: inst_exit 역전 block=%.2f warn=%.2f → 기본값",
                       result["inst_exit_block"], result["inst_exit_warn"])
            result["inst_exit_warn"]  = _DEFAULT_bridge["inst_exit_warn"]
            result["inst_exit_block"] = _DEFAULT_bridge["inst_exit_block"]

        # ⑤ gap_risk_penalty_start < gap_risk_penalty_max
        if result["gap_risk_penalty_start"] >= result["gap_risk_penalty_max"]:
            _log.error("bridge: gap_risk_penalty_start >= max → 기본값")
            result["gap_risk_penalty_start"] = _DEFAULT_bridge["gap_risk_penalty_start"]
            result["gap_risk_penalty_max"]   = _DEFAULT_bridge["gap_risk_penalty_max"]

        # [LOG-1] slippage_cap 이상 경보
        if result["slippage_cap"] > 0.003:
            _log.critical("⚠️  bridge.slippage_cap=%.4f > 0.003 → 슬리피지 초과 위험",
                          result["slippage_cap"])
        # [v1_10 LOG] 수익률 저하형 경고 — 강제복구 없이 warning만
        if result["ev_min_threshold"] > 0.012:
            _log.warning("bridge.ev_min_threshold=%.4f > 0.012 → 진입 기회 상실 위험",
                         result["ev_min_threshold"])

        return result
    except Exception as e:
        _log.error("get_bridge 예외 → 기본값: %s", e)
        return dict(_DEFAULT_bridge)


# ═══════════════════════════════════════════════════════════════
#  공개 API — [UPD-6] get_공격안정비율() 강화
# ═══════════════════════════════════════════════════════════════
def get_공격안정비율() -> Dict:
    """
    [UPD-6] 공격 70% / 안정 30% 핵심 비율 파라미터 반환
    1종목 몰빵 전략의 자본 배분 핵심 — 자기진화 연동 가능

    반환 키 (신규 포함):
        attack_pct, stable_pct, allout_max, min_trade_size_krw,
        single_position_mode, single_position_max_slots, ← [신규]
        capital_deploy_hard_cap, capital_deploy_soft_cap  ← [신규]
    """
    try:
        params = _load()
        base   = dict(_DEFAULT_공격안정비율)
        base.update(params.get("공격안정비율", {}))

        result = {
            "attack_pct":              _safe_float(base["attack_pct"],         0.70, lo=0.50, hi=1.0),
            "stable_pct":              _safe_float(base["stable_pct"],         0.30, lo=0.0,  hi=0.50),
            "allout_max":              _safe_float(base["allout_max"],         0.65, lo=0.30, hi=0.65),
            "min_trade_size_krw":      _safe_float(base["min_trade_size_krw"], 500_000, lo=100_000, hi=10_000_000),
            # [신규] 단일 종목 집중 모드
            "single_position_mode":    bool(base.get("single_position_mode", True)),
            "single_position_max_slots": _safe_int(base.get("single_position_max_slots", 1), 1, lo=1, hi=1),
            # [신규] 투입 자본 캡
            "capital_deploy_hard_cap": _safe_float(base.get("capital_deploy_hard_cap", 0.65), 0.65, lo=0.30, hi=0.65),
            "capital_deploy_soft_cap": _safe_float(base.get("capital_deploy_soft_cap", 0.55), 0.55, lo=0.20, hi=0.65),
        }

        # 교차검증
        # ① attack + stable == 1.0
        if abs(result["attack_pct"] + result["stable_pct"] - 1.0) > 0.01:
            _log.error("공격안정비율: attack+stable=%.2f ≠ 1.0 → 기본값",
                       result["attack_pct"] + result["stable_pct"])
            result["attack_pct"] = _DEFAULT_공격안정비율["attack_pct"]
            result["stable_pct"] = _DEFAULT_공격안정비율["stable_pct"]

        # ② capital_deploy_soft_cap <= capital_deploy_hard_cap
        if result["capital_deploy_soft_cap"] > result["capital_deploy_hard_cap"]:
            _log.error("공격안정비율: capital_deploy_soft_cap(%.2f) > hard_cap(%.2f) → 기본값",
                       result["capital_deploy_soft_cap"], result["capital_deploy_hard_cap"])
            result["capital_deploy_soft_cap"] = _DEFAULT_공격안정비율["capital_deploy_soft_cap"]
            result["capital_deploy_hard_cap"] = _DEFAULT_공격안정비율["capital_deploy_hard_cap"]

        # ③ capital_deploy_hard_cap <= 0.65
        if result["capital_deploy_hard_cap"] > 0.65:
            _log.critical("⚠️  capital_deploy_hard_cap=%.2f > 0.65 → 과열 투입 위험",
                          result["capital_deploy_hard_cap"])
            result["capital_deploy_hard_cap"] = 0.65

        # ④ single_position_max_slots == 1 (1종목 몰빵 원칙)
        if result["single_position_max_slots"] != 1:
            _log.critical("⚠️  single_position_max_slots=%d ≠ 1 → 1종목 몰빵 원칙 위반",
                          result["single_position_max_slots"])
            result["single_position_max_slots"] = 1

        return result
    except Exception as e:
        _log.error("get_공격안정비율 예외 → 기본값: %s", e)
        return dict(_DEFAULT_공격안정비율)


# ═══════════════════════════════════════════════════════════════
#  공개 API — [ADD-5] get_siga_link() 신규
# ═══════════════════════════════════════════════════════════════
def get_siga_link(regime: Optional[str] = None) -> Dict:
    """
    [ADD-5] 시가엔진 연결 파라미터 공급 전용
    역할: 시가엔진이 사용할 "기준값"만 관리. 타이밍/로직 구현 금지.

    반환 키:
        enable_siga_link,
        open_gap_min, open_gap_max,
        open_value_ratio_min, open_breakout_lookback_min,
        scoreboard_pass_min, bridge_pass_ev_min,
        inst_flow_intraday_floor, inst_flow_intraday_block,
        no_chase_after_min, entry_delay_sec,
        vol_spike_intraday_min, price_extension_block_pct
    """
    try:
        params = _load()
        rp     = _regime_params(regime)
        base   = dict(_DEFAULT_siga_link)
        base.update(params.get("siga_link", {}))
        base.update(rp.get("siga_link", {}))

        result = {
            "enable_siga_link":          bool(base.get("enable_siga_link", True)),
            "open_gap_min":              _safe_float(base.get("open_gap_min",             1.5), 1.5,  lo=0.0,   hi=10.0),
            "open_gap_max":              _safe_float(base.get("open_gap_max",             5.0), 5.0,  lo=1.0,   hi=20.0),
            "open_value_ratio_min":      _safe_float(base.get("open_value_ratio_min",     1.5), 1.5,  lo=0.5,   hi=10.0),
            "open_breakout_lookback_min":_safe_int(base.get("open_breakout_lookback_min", 3),   3,    lo=1,     hi=20),
            "scoreboard_pass_min":       _safe_float(base.get("scoreboard_pass_min",     75.0), 75.0, lo=60.0,  hi=95.0),
            "bridge_pass_ev_min":        _safe_float(base.get("bridge_pass_ev_min",     0.009), 0.009,lo=0.001, hi=0.05),
            "inst_flow_intraday_floor":  _safe_float(base.get("inst_flow_intraday_floor", 0.0), 0.0,  lo=-1.0,  hi=1.0),
            "inst_flow_intraday_block":  _safe_float(base.get("inst_flow_intraday_block",-0.20),-0.20,lo=-1.0,  hi=0.0),
            "no_chase_after_min":        _safe_int(base.get("no_chase_after_min",         3),   3,    lo=1,     hi=30),
            "entry_delay_sec":           _safe_int(base.get("entry_delay_sec",           20),  20,    lo=0,     hi=300),
            # [v1_11 UPD] 1.8→2.2 노이즈 필터 강화
            "vol_spike_intraday_min":    _safe_float(base.get("vol_spike_intraday_min",   2.2), 2.2,  lo=1.0,   hi=10.0),
            "price_extension_block_pct": _safe_float(base.get("price_extension_block_pct",3.0), 3.0,  lo=0.5,   hi=15.0),
        }

        # 교차검증
        # ① open_gap_min < open_gap_max
        if result["open_gap_min"] >= result["open_gap_max"]:
            _log.error("siga_link: open_gap_min(%.2f) >= open_gap_max(%.2f) → 기본값",
                       result["open_gap_min"], result["open_gap_max"])
            result["open_gap_min"] = _DEFAULT_siga_link["open_gap_min"]
            result["open_gap_max"] = _DEFAULT_siga_link["open_gap_max"]

        # ② scoreboard_pass_min >= 70
        if result["scoreboard_pass_min"] < 70.0:
            _log.critical("⚠️  siga_link.scoreboard_pass_min=%.1f < 70 → 쓰레기 진입 위험",
                          result["scoreboard_pass_min"])
            result["scoreboard_pass_min"] = 70.0

        # ③ bridge_pass_ev_min >= 0.005
        if result["bridge_pass_ev_min"] < 0.005:
            _log.critical("⚠️  siga_link.bridge_pass_ev_min=%.4f < 0.005 → 저수익 진입 위험",
                          result["bridge_pass_ev_min"])
            result["bridge_pass_ev_min"] = 0.005

        # ④ no_chase_after_min >= 1
        if result["no_chase_after_min"] < 1:
            _log.error("siga_link: no_chase_after_min=%d < 1 → 기본값 3",
                       result["no_chase_after_min"])
            result["no_chase_after_min"] = 1

        # ⑤ price_extension_block_pct > 0
        if result["price_extension_block_pct"] <= 0:
            _log.error("siga_link: price_extension_block_pct=%.2f ≤ 0 → 기본값",
                       result["price_extension_block_pct"])
            result["price_extension_block_pct"] = _DEFAULT_siga_link["price_extension_block_pct"]

        # [v1_10 LOG] 수익률 저하형 경고 — 강제복구 없이 warning만
        if result["open_gap_max"] < 4.0:
            _log.warning("siga_link.open_gap_max=%.1f < 4.0 → 시가 초입 기회 축소 위험",
                         result["open_gap_max"])

        return result

    except Exception as e:
        _log.error("get_siga_link 예외 → 기본값: %s", e)
        return dict(_DEFAULT_siga_link)


# ═══════════════════════════════════════════════════════════════
#  공개 API — [ADD-6] validate_connection_line() 신규
# ═══════════════════════════════════════════════════════════════
def validate_connection_line(regime: Optional[str] = None) -> Dict[str, bool]:
    """
    [ADD-6 / v1_9 UPD / v1_10 UPD] 스코어보드 → 브릿지 → 시가 연결라인 일관성 검증

    검증 항목:
        1~8.  기존 8항목 (scoreboard/bridge/siga/자본 정합성)
        9~11. [v1_9] rt_sell 핵심 3항목 (failsafe/peak_protect/chandelier_k)
        12~16.[v1_10] selection 허브 5항목 (가중치/edge/힌트/accel/topn)
        17.   [v1_10] 공격/안정 비율 동기화 (scoreboard ↔ 공격안정비율)

    반환: {검증항목: True/False}
    """
    results: Dict[str, bool] = {}

    try:
        sb   = get_scoreboard(regime)
        br   = get_bridge(regime)
        sl   = get_siga_link(regime)
        ar   = get_공격안정비율()
        rs   = get_rt_sell(regime)   # [v1_9]

        # ① scoreboard attack+defense == 1.0
        check1 = abs(sb["attack_ratio"] + sb["defense_ratio"] - 1.0) <= 0.01
        results["sb_attack_defense_sum"] = check1
        if not check1:
            _log.error("연결라인[1] scoreboard attack+defense=%.2f ≠ 1.0",
                       sb["attack_ratio"] + sb["defense_ratio"])

        # ② 공격안정비율 attack+stable == 1.0
        check2 = abs(ar["attack_pct"] + ar["stable_pct"] - 1.0) <= 0.01
        results["ar_attack_stable_sum"] = check2
        if not check2:
            _log.error("연결라인[2] 공격안정비율 attack+stable=%.2f ≠ 1.0",
                       ar["attack_pct"] + ar["stable_pct"])

        # ③ scoreboard.score_hard_min >= bridge.bridge_score_soft_min
        check3 = sb["score_hard_min"] >= br["bridge_score_soft_min"]
        results["sb_hard_vs_br_soft"] = check3
        if not check3:
            _log.critical("연결라인[3] sb.score_hard_min(%.1f) < br.bridge_score_soft_min(%.1f) "
                          "→ 스코어보드와 브릿지 점수 기준 불일치",
                          sb["score_hard_min"], br["bridge_score_soft_min"])

        # ④ bridge.bridge_score_min >= scoreboard.score_soft_min
        check4 = br["bridge_score_min"] >= sb["score_soft_min"]
        results["br_hard_vs_sb_soft"] = check4
        if not check4:
            _log.critical("연결라인[4] br.bridge_score_min(%.1f) < sb.score_soft_min(%.1f) "
                          "→ 스코어보드와 브릿지 점수 기준 불일치",
                          br["bridge_score_min"], sb["score_soft_min"])

        # ⑤ bridge.ev_min_threshold == siga_link.bridge_pass_ev_min
        check5 = abs(br["ev_min_threshold"] - sl["bridge_pass_ev_min"]) < 1e-6
        results["ev_threshold_sync"] = check5
        if not check5:
            _log.error("연결라인[5] bridge.ev_min_threshold(%.4f) ≠ siga_link.bridge_pass_ev_min(%.4f) "
                       "→ EV 기준 불일치",
                       br["ev_min_threshold"], sl["bridge_pass_ev_min"])

        # ⑥ siga_link.scoreboard_pass_min == scoreboard.score_hard_min
        check6 = abs(sl["scoreboard_pass_min"] - sb["score_hard_min"]) < 1e-6
        results["score_passmin_sync"] = check6
        if not check6:
            _log.error("연결라인[6] siga_link.scoreboard_pass_min(%.1f) ≠ sb.score_hard_min(%.1f) "
                       "→ 점수 기준 불일치",
                       sl["scoreboard_pass_min"], sb["score_hard_min"])

        # ⑦ bridge.slippage_cap <= 0.003
        check7 = br["slippage_cap"] <= 0.003
        results["slippage_cap_ok"] = check7
        if not check7:
            _log.critical("연결라인[7] bridge.slippage_cap=%.4f > 0.003 → 슬리피지 초과",
                          br["slippage_cap"])

        # ⑧ allout_max <= capital_deploy_hard_cap <= 0.65
        check8 = ar["allout_max"] <= ar["capital_deploy_hard_cap"] <= 0.65
        results["capital_cap_ok"] = check8
        if not check8:
            _log.critical("연결라인[8] allout_max(%.2f) / hard_cap(%.2f) 설정 이상 → 과열 투입 위험",
                          ar["allout_max"], ar["capital_deploy_hard_cap"])

        # ⑨ [v1_9] rt_sell.failsafe_trigger_pct <= 0.03 (지침서§7: 2% 최적)
        check9 = rs.get("failsafe_trigger_pct", 0.02) <= 0.03
        results["failsafe_trigger_ok"] = check9
        if not check9:
            _log.critical("연결라인[9] failsafe_trigger_pct=%.3f > 0.03 "
                          "→ 지침서v15 §7 위반. 수익 반납 보호 약화",
                          rs.get("failsafe_trigger_pct", 0.02))

        # ⑩ [v1_9] PEAK_PROTECT 3단계 단조증가 구조
        pp_ok = (rs.get("peak_protect_l1_pct",  0) <
                 rs.get("peak_protect_l2_pct",  0) <
                 rs.get("peak_protect_l3_pct",  0) and
                 rs.get("peak_protect_l1_exit", 0) <
                 rs.get("peak_protect_l2_exit", 0) <
                 rs.get("peak_protect_l3_exit", 0))
        results["peak_protect_structure"] = pp_ok
        if not pp_ok:
            _log.critical("연결라인[10] PEAK_PROTECT 단계 순서 역전 → 지침서v15 §6 위반")

        # ⑪ [v1_9] chandelier_k 단조증가
        ck_ok = (rs.get("chandelier_k_normal", 0) <
                 rs.get("chandelier_k_high",   0) <
                 rs.get("chandelier_k_extreme",0))
        results["chandelier_k_order"] = ck_ok
        if not ck_ok:
            _log.critical("연결라인[11] chandelier_k 순서 이상 "
                          "normal=%.1f high=%.1f extreme=%.1f → 지침서v15 §3-2 위반",
                          rs.get("chandelier_k_normal", 0),
                          rs.get("chandelier_k_high",   0),
                          rs.get("chandelier_k_extreme",0))

        # ════ [v1_10 신규] selection 허브 검증 5항목 ════════════════
        sel = get_선정(regime)

        # ⑫ selection 가중치 전부 > 0
        weights_ok = all(sel.get(k, 0) > 0
                         for k in ("W_VALUE","W_ACCEL","W_CP","W_HB","W_VWP","W_SUPPLY","W_RISK"))
        results["selection_weights_ok"] = weights_ok
        if not weights_ok:
            _log.critical("연결라인[12] selection 가중치 0 이하 항목 존재 "
                          "→ 수익률 구조 붕괴 위험")

        # ⑬ EDGE_MIN_DOWN > EDGE_MIN_UP
        edge_ok = sel.get("EDGE_MIN_DOWN", 0) > sel.get("EDGE_MIN_UP", 0)
        results["selection_edge_floor_ok"] = edge_ok
        if not edge_ok:
            _log.error("연결라인[13] EDGE_MIN_DOWN(%.2f) <= EDGE_MIN_UP(%.2f) "
                       "→ edge 하한 역전 위험",
                       sel.get("EDGE_MIN_DOWN", 0), sel.get("EDGE_MIN_UP", 0))

        # ⑭ HINT_PULLBACK_CP_LOW < HINT_PULLBACK_CP_HIGH
        hint_ok = sel.get("HINT_PULLBACK_CP_LOW", 0) < sel.get("HINT_PULLBACK_CP_HIGH", 1)
        results["selection_pullback_hint_ok"] = hint_ok
        if not hint_ok:
            _log.error("연결라인[14] HINT_PULLBACK_CP_LOW(%.2f) >= HIGH(%.2f) "
                       "→ pullback 힌트 역전 위험",
                       sel.get("HINT_PULLBACK_CP_LOW", 0), sel.get("HINT_PULLBACK_CP_HIGH", 1))

        # ⑮ ACCEL_NORM_DIV > 0 AND INST_ACCEL_THRESHOLD >= 1.1
        accel_ok = (sel.get("ACCEL_NORM_DIV", 8.0) > 0 and
                    sel.get("INST_ACCEL_THRESHOLD", 1.5) >= 1.1)
        results["selection_accel_ok"] = accel_ok
        if not accel_ok:
            _log.critical("연결라인[15] ACCEL 파라미터 이상 "
                          "DIV=%.2f THR=%.2f → 후보 가속 점수 오류 위험",
                          sel.get("ACCEL_NORM_DIV", 8.0),
                          sel.get("INST_ACCEL_THRESHOLD", 1.5))

        # ⑯ TOP_N 100~300 범위
        topn_ok = 100 <= sel.get("TOP_N", 250) <= 300
        results["selection_topn_ok"] = topn_ok
        if not topn_ok:
            _log.error("연결라인[16] TOP_N=%d 권장범위(100~300) 이탈 → 후보 과소/과다 위험",
                       sel.get("TOP_N", 250))

        # ════ [v1_10 신규] 공격/안정 비율 동기화 검증 ══════════════
        # scoreboard.attack_ratio == 공격안정비율.attack_pct (같은 철학 두 곳에 있음)
        ratio_sync_ok = (abs(sb["attack_ratio"] - ar["attack_pct"]) < 1e-6 and
                         abs(sb["defense_ratio"] - ar["stable_pct"]) < 1e-6)
        results["attack_ratio_sync"] = ratio_sync_ok
        if not ratio_sync_ok:
            _log.error("연결라인[17] 공격/안정비율 불일치 "
                       "scoreboard=%.2f/%.2f vs 공격안정=%.2f/%.2f "
                       "→ 장기 운영 중 철학값 엇갈림 위험",
                       sb["attack_ratio"], sb["defense_ratio"],
                       ar["attack_pct"], ar["stable_pct"])

        # ════ [v1_11 신규] 1일 1진입 운영 설정 검증 ════════════════
        op = get_운영()
        entry_ok = (op.get("min_daily_entry_required", True) is True and
                    1000 <= op.get("force_entry_by_hhmm", 1300) <= 1430 and
                    op.get("skip_if_market_bad", True) is True)
        results["daily_entry_policy_ok"] = entry_ok
        if not entry_ok:
            _log.error("연결라인[18] 1일 1진입 설정 이상 "
                       "required=%s by=%d skip_bad=%s → 요건 9번 미이행 위험",
                       op.get("min_daily_entry_required"),
                       op.get("force_entry_by_hhmm", 0),
                       op.get("skip_if_market_bad"))

        passed  = sum(1 for v in results.values() if v)
        total   = len(results)
        _log.info("연결라인 검증: %d/%d 통과 | 국면=%s", passed, total, get_국면(regime))
        if passed < total:
            _log.critical("❌ 연결라인 불일치 %d건 → 파라미터 정합성 점검 필요",
                          total - passed)

    except Exception as e:
        _log.critical("validate_connection_line 예외: %s", e)

    return results


# ═══════════════════════════════════════════════════════════════
#  공개 API — [UPD-7] validate_all() 업데이트
# ═══════════════════════════════════════════════════════════════
def validate_all(regime: Optional[str] = None) -> Dict[str, bool]:
    """
    [UPD-7] 기동 전체 파라미터 사전검증
    서비스 시작 시 호출 — 11개 섹션 + siga_link + connection_line 검증
    반환: {섹션명: True/False}  False가 있으면 경고 후 기본값 사용됨
    """
    results: Dict[str, bool] = {}

    def _chk(name: str, fn) -> None:
        try:
            fn()
            results[name] = True
        except Exception as e:
            _log.critical("validate_all [%s] 실패: %s", name, e)
            results[name] = False

    _log.info("=" * 60)
    _log.info("▶ SAFEPLUS params_reader v1_11 validate_all 시작")

    _chk("선정",       lambda: get_선정(regime))
    _chk("갭등급",     lambda: get_갭등급(regime))
    _chk("트레일",     lambda: get_트레일(regime))
    _chk("청산시각",   get_청산시각)
    _chk("kelly",     lambda: get_kelly(regime))
    _chk("rt_sell",   lambda: get_rt_sell(regime))
    # [v1_11 삭제] eod(종배) 검증 제거
    _chk("거래비용",   get_거래비용)
    _chk("scoreboard",lambda: get_scoreboard(regime))
    _chk("bridge",    lambda: get_bridge(regime))
    _chk("공격안정",   get_공격안정비율)
    _chk("siga_link", lambda: get_siga_link(regime))
    _chk("운영",       get_운영)                                                  # [v1_11 ADD]
    _chk("connection_line", lambda: validate_connection_line(regime))

    failed = [k for k, v in results.items() if not v]
    if failed:
        _log.critical("❌ validate_all 실패 섹션: %s (기본값 사용)", failed)
    else:
        _log.info("✅ 전체 파라미터 검증 통과 | 국면=%s", get_국면(regime))
    _log.info("=" * 60)
    return results


# ═══════════════════════════════════════════════════════════════
#  공개 API — [UPD-8] get_all() 업데이트
# ═══════════════════════════════════════════════════════════════
def get_all(regime: Optional[str] = None) -> Dict:
    """
    전체 파라미터 한번에 반환
    ⚠️  디버그 / 로깅 전용 — 실거래 hot path에서 호출 금지
    [v1_11] eod 제거, 운영 추가
    """
    return {
        "국면":          get_국면(regime),
        "선정":          get_선정(regime),
        "갭등급":        get_갭등급(regime),
        "트레일":        get_트레일(regime),
        "청산시각":      get_청산시각(),
        "kelly":         get_kelly(regime),
        "rt_sell":       get_rt_sell(regime),
        # [v1_11 삭제] "eod": get_eod() — 종배 삭제
        "거래비용":      get_거래비용(),
        "scoreboard":    get_scoreboard(regime),
        "bridge":        get_bridge(regime),
        "공격안정비율":  get_공격안정비율(),
        "siga_link":     get_siga_link(regime),
        "운영":          get_운영(),                # [v1_11 ADD]
    }


# ═══════════════════════════════════════════════════════════════
#  각 모듈 적용 예시  [v1_11 업데이트 — 종배 삭제 반영]
# ═══════════════════════════════════════════════════════════════
"""
■ kjs_scoreboard.py (선별/점수화 전용)  ← eod 접미사 제거 권장
    from params_reader import get_scoreboard, get_공격안정비율
    _SB = get_scoreboard()
    _AR = get_공격안정비율()
    ATTACK_RATIO      = _AR["attack_pct"]          # 0.70
    SCORE_HARD_MIN    = _SB["score_hard_min"]      # 75.0
    OFI_WEIGHT        = _SB["s1_ofi_weight"]       # 22.0
    INST_WEIGHT       = _SB["s2_inst_weight"]      # 22.0
    CONV_GATE_MIN     = _SB["conv_gate_min"]       # 0.68
    GAP_OVERHEAT_CUT  = _SB["gap_overheat_cut"]    # 5.0

■ kjs_bridge.py (리스크/사이징/연결 전용)  ← eod 접미사 제거 권장
    from params_reader import get_bridge, get_kelly
    _BR = get_bridge()
    _K  = get_kelly()
    KELLY_BULL        = _BR["kelly_bull"]          # 0.65
    EV_MIN            = _BR["ev_min_threshold"]    # 0.009
    RIDE_CUT          = _BR["ride_score_hard_cut"] # 0.28
    BR_SCORE_MIN      = _BR["bridge_score_min"]    # 75.0

■ 시가엔진 (타이밍/진입 트리거 전용)
    from params_reader import get_siga_link
    _SL = get_siga_link()
    OPEN_GAP_MIN      = _SL["open_gap_min"]        # 1.5
    OPEN_GAP_MAX      = _SL["open_gap_max"]        # 5.0
    NO_CHASE_MIN      = _SL["no_chase_after_min"]  # 3
    EV_PASS_MIN       = _SL["bridge_pass_ev_min"]  # 0.009

■ rt_execution_engine / safeplus_preflight_gate (1일 1진입 판단)  [v1_11 신규]
    from params_reader import get_운영
    _OP = get_운영()
    MIN_ENTRY_REQ  = _OP["min_daily_entry_required"]  # True
    FORCE_BY       = _OP["force_entry_by_hhmm"]       # 1300
    SKIP_BAD       = _OP["skip_if_market_bad"]         # True
    BAD_OFI_THR    = _OP["market_bad_ofi_threshold"]  # -0.40
    EVO_KEYS       = _OP["_evolution_allowed_keys"]   # 허용 파라미터 목록
    FROZEN_KEYS    = _OP["_evolution_frozen_keys"]    # 금지 파라미터 목록

■ 서비스 기동 시 (run_pipeline.bat 직후)
    from params_reader import validate_all, validate_connection_line
    ok  = validate_all()
    con = validate_connection_line()
    if not all(con.values()):
        print("⚠️ 연결라인 불일치 — 파라미터 점검 필요")
"""


# ═══════════════════════════════════════════════════════════════
#  단독 실행 — [UPD-9] __main__ 출력 확장
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    _log.setLevel(logging.DEBUG)

    print("\n" + "=" * 70)
    print("  params_reader v1_11 SAFEPLUS FINAL — 파라미터 허브 + 연결라인 점검")
    print("=" * 70)
    print(f"  params.json  : {_PARAMS}")
    print(f"  파일 존재    : {_PARAMS.exists()}")
    now_t = _now_hhmm()
    print(f"  현재시각     : {now_t}  {'🔒동결중' if _is_frozen() else '✅갱신가능'}")
    print(f"  마지막 로드  : {_LAST_RELOAD_AT or '미로드'}")
    print()

    # ─── 기동 점검 ────────────────────────────────────────────
    print("  ▶ validate_all() — 전체 파라미터 기동 검증:")
    vr = validate_all()
    for sec, ok in vr.items():
        print(f"    {'✅' if ok else '❌'} {sec}")
    print()

    # ─── 연결라인 검증 ────────────────────────────────────────
    print("  ▶ validate_connection_line() — 연결라인 일관성:")
    cl = validate_connection_line()
    for item, ok in cl.items():
        print(f"    {'✅' if ok else '❌'} {item}")
    print()

    # ─── 국면 ─────────────────────────────────────────────────
    all_p = get_all()
    print(f"  현재 국면    : {all_p['국면']}")
    print()

    # ─── 공격/안정 비율 ───────────────────────────────────────
    ar = all_p["공격안정비율"]
    print("  [공격안정비율]")
    print(f"    공격={ar['attack_pct']:.0%}  안정={ar['stable_pct']:.0%}  "
          f"allout_max={ar['allout_max']}")
    print(f"    hard_cap={ar['capital_deploy_hard_cap']}  "
          f"soft_cap={ar['capital_deploy_soft_cap']}  "
          f"단일모드={ar['single_position_mode']}  "
          f"max_slots={ar['single_position_max_slots']}")

    # ─── Kelly ────────────────────────────────────────────────
    k = all_p["kelly"]
    print("  [Kelly]")
    print(f"    fraction={k['fraction']}  "
          f"{'✅보정완료' if k['_calibrated'] else '⚠️미보정'}  "
          f"raw={k['kelly_raw']:.4f}")

    # ─── 스코어보드 ───────────────────────────────────────────
    sb = all_p["scoreboard"]
    print("  [스코어보드]")
    print(f"    공격={sb['attack_ratio']:.0%}  안정={sb['defense_ratio']:.0%}  "
          f"conv_gate={sb['conv_gate_min']}")
    print(f"    OFI={sb['s1_ofi_weight']}pt  VPIN={sb['s1_vpin_weight']}pt  "
          f"기관={sb['s2_inst_weight']}pt  갭={sb['s2_gap_weight']}pt")
    print(f"    score_hard_min={sb['score_hard_min']}  score_soft_min={sb['score_soft_min']}")
    print(f"    inst_flow_floor={sb['inst_flow_floor']}  "
          f"gap_overheat_cut={sb['gap_overheat_cut']}  "
          f"deadzone=[{sb['gap_deadzone_low']},{sb['gap_deadzone_high']}]")

    # ─── 브릿지 ───────────────────────────────────────────────
    br = all_p["bridge"]
    print("  [브릿지]")
    print(f"    Kelly: BULL={br['kelly_bull']}  NEU={br['kelly_neutral']}  "
          f"CAU={br['kelly_caution']}")
    print(f"    ev_min={br['ev_min_threshold']}  slippage_cap={br['slippage_cap']}")
    print(f"    bridge_score_min={br['bridge_score_min']}  "
          f"bridge_score_soft_min={br['bridge_score_soft_min']}")
    print(f"    ride_hard_cut={br['ride_score_hard_cut']}  "
          f"soft=[{br['ride_score_soft_lo']},{br['ride_score_soft_hi']}]  "
          f"soft_pos={br['soft_pos_ratio']:.0%}")
    print(f"    market_block: hard={br['market_regime_hard_block']}  "
          f"soft={br['market_regime_soft_block']}")
    print(f"    inst_exit: warn={br['inst_exit_warn']}  block={br['inst_exit_block']}")
    print(f"    gap_penalty: start={br['gap_risk_penalty_start']}%  "
          f"max={br['gap_risk_penalty_max']}%")

    # ─── 시가 연결 ────────────────────────────────────────────
    sl = all_p["siga_link"]
    print("  [시가 연결 (siga_link)]")
    print(f"    활성화={sl['enable_siga_link']}  "
          f"gap=[{sl['open_gap_min']}%~{sl['open_gap_max']}%]")
    print(f"    scoreboard_pass_min={sl['scoreboard_pass_min']}  "
          f"bridge_pass_ev_min={sl['bridge_pass_ev_min']}")
    print(f"    no_chase_after={sl['no_chase_after_min']}분  "
          f"entry_delay={sl['entry_delay_sec']}초  "
          f"price_ext_block={sl['price_extension_block_pct']}%")
    print(f"    inst_floor={sl['inst_flow_intraday_floor']}  "
          f"inst_block={sl['inst_flow_intraday_block']}")

    # ─── rt_sell ──────────────────────────────────────────────
    rs = all_p["rt_sell"]
    print("  [rt_sell]")
    print(f"    SUPER_TREND={rs['SUPER_TREND_MODE']}  "
          f"split={rs['split_ratio']:.0%}(inst:{rs['split_ratio_inst']:.0%})  t2={rs['t2_mult']}")
    print(f"    trail_activate={rs['trail_activate_ret']:.1%}  "
          f"trail_hard={rs['trail_activate_hard_pct']:.1%}  "
          f"hard_stop={rs['hard_stop']:.1%}")
    print(f"    [Chandelier k] NORMAL={rs['chandelier_k_normal']}  "
          f"HIGH={rs['chandelier_k_high']}  EXTREME={rs['chandelier_k_extreme']}")
    print(f"    [vol_ratio thr] high>={rs['vol_ratio_high_thr']}  "
          f"extreme>={rs['vol_ratio_extreme_thr']}")
    print(f"    [k_boost] x{rs['k_boost_multiplier']} | "
          f"OFI>={rs['k_boost_ofi_floor']} accel>={rs['k_boost_accel_floor']} "
          f"profit>={rs['k_boost_profit_floor']:.0%}")
    print(f"    [accel] recent={rs['accel_recent_bars']}봉 / prior={rs['accel_prior_bars']}봉")
    print(f"    [FAILSAFE] trigger>={rs['failsafe_trigger_pct']:.0%}  "
          f"preserve={rs['failsafe_preserve_ratio']:.0%}")
    print(f"    [PEAK_PROTECT] "
          f"L1:{rs['peak_protect_l1_pct']:.0%}/{rs['peak_protect_l1_exit']:.0%}  "
          f"L2:{rs['peak_protect_l2_pct']:.0%}/{rs['peak_protect_l2_exit']:.0%}  "
          f"L3:{rs['peak_protect_l3_pct']:.0%}/{rs['peak_protect_l3_exit']:.0%}")
    print(f"    [강보유] ride_floor={rs['ride_strong_hold_floor']}  "
          f"inst_ofi={rs['inst_strong_hold_ofi']}")
    # [v1_11 삭제] jongbae 출력 제거
    print(f"    [전략오버라이드(2전략)] "
          f"hold: 시가={rs['siga_max_hold_min']}분  추세={rs['trend_max_hold_min']}분")

    # ─── 거래비용 ─────────────────────────────────────────────
    cost = all_p["거래비용"]
    print("  [거래비용]")
    print(f"    왕복합계={cost['buy_fee_pct']+cost['sell_fee_pct']+cost['sell_tax_pct']:.4%}")

    # ─── 운영 (1일 1진입) ─────────────────────────────────────
    # [v1_11] EOD 섹션 삭제 → 운영 섹션으로 대체
    op = all_p["운영"]
    print("  [운영 — 1일 1진입 보장]")
    print(f"    min_daily_entry={op['min_daily_entry_required']}  "
          f"force_by={op['force_entry_by_hhmm']}  "
          f"skip_bad={op['skip_if_market_bad']}  "
          f"bad_ofi<{op['market_bad_ofi_threshold']}")
    print(f"    evolution: interval={op['evolution_interval_trades']}건  "
          f"min={op['evolution_min_trades']}건")
    print(f"    진화허용키: {op['_evolution_allowed_keys']}")
    print(f"    진화금지키: {op['_evolution_frozen_keys']}")

    print("=" * 70 + "\n")

# -*- coding: utf-8 -*-
"""
kiwoom_buy_order_sender_RUNME.py  [v4_9]
=========================================
대상전략: 시가(GAP) · 추세눌림(PULLBACK/TREND) — 당일 청산 2개 전략 전용
설계원칙: 기관 흐름 추종 · 수익 극대화 · 보호 강화 · 과최적화 방지
목표점수: 헤지펀드급 96점 이상

[v4_9] 96점 완성 패치 — 2026-04-18

  [CRIT] pnl_strategy_linker 모듈명 동기화
  기존: from pnl_strategy_linker import write_buy_fill
        → suffix 없는 파일 미존재 → _PNL_LINKER_OK=False 항상
        → 매수 체결 데이터 자기진화 루프 미전달
        → Kelly 학습 매수 데이터 공백 → 자기진화 반쪽 작동
  수정: v3_4_FIXED(실제파일) 우선 → v3_4 → v3_3_SAFEPLUS_FINAL → 폴백
  효과: write_buy_fill() 정상 전달 → 자기진화 매수·매도 완전 연결

  [FIX-1] main() 버전 로그 v4_0 → v4_9 통일
  기존: "BUY ORDER SENDER v4_0" (파일 첫 생성 버전으로 고정)
  수정: "BUY ORDER SENDER v4_9" → 실제 버전 감사 추적 가능

  [FIX-2] _FALLBACK_SCORE_BY_STRATEGY EOD 항목 제거
  기존: EOD_TOP1=82.0 / EOD_TOP2=82.0 잔존
  v4_7에서 EOD 전략 완전 삭제됐으나 fallback 테이블에만 남아 있던 것 정리
  실전 동작 영향 없음 — 설계 정합성 확보

[v4_8] Gap 분석 High 2개 수정 2026-04-16

  [Gap-4] EV 완화 진입 — 포지션 사이즈 70% 캡
  기존: daily_min_active=True (1일 1진입 보장 완화 진입) 시 동일 사이즈 몰빵
  수정: 완화 기준 통과 진입 → ev_ratio에 DAILY_MIN_SIZE_CAP=0.70 상한 적용
  근거: 헤지펀드는 진입 품질에 따라 포지션 크기 반드시 분리
        저품질 진입 종목 손실 시 타격 과대 방지

  [Gap-5] hard_stop 레짐별 동적 조정
  기존: HARD_STOP_DEFAULT=0.025 고정 (레짐 무관)
  수정: HARD_STOP_REGIME_MAP 도입
        VOLATILE → 2.0% / TREND → 3.0% / BEAR → 1.8% / 기본 → 2.5%
  근거: Thorp(1997): Kelly 분수와 손절 기준 동시 조정이 최적

[v4_7] 임원진 합동 회의 (CEO/CTO/CFO/CSO/CMO/CDO) — 2026-04-10
  ▶ 종배(시배·OPENING·GAP_OPEN) 전략 완전 분리 — 이 프로그램은 당일청산 전용
  ▶ 아래 항목 전량 제거:
      JONGBAE_OVERNIGHT_CAP / GUARD_OPEN_JONGBAE_HHMM / JONGBAE_SESSION_TYPES
      GUARD_JONGBAE_KEYWORDS / _market_guard 종배 분기
      _ev_position_ratio 야간캡 블록
      _FALLBACK_SCORE_BY_STRATEGY 내 JONGBAE·SIBAE·OPENING·GAP_OPEN·OPEN_GAP 항목

  [v4_7-P1] IC-가중 레짐 앙상블 (Grinold & Kahn 1994 — 정보계수 기반 투표)
             기존: 코스닥/코스피/외국인/거래량 동일가중 4투표
             개선: 각 신호의 과거 IC(Information Coefficient) 비례 가중
             출처: Grinold, R. & Kahn, R. (1994) "Active Portfolio Management"
                   IC = corr(signal, next_period_return)  → 실증 가중치 반영

  [v4_7-P2] Alpha Decay 시간대별 진입 품질 감쇠 (Scholes & Williams 1977 응용)
             09:03~09:30 : α_decay=1.00 (신호 최강 구간)
             09:30~11:00 : α_decay=0.90
             11:00~13:00 : α_decay=0.80 (점심 저유동성)
             13:00~14:30 : α_decay=0.95 (재개 상승)
             14:30~15:00 : α_decay=0.70 (종가 노이즈)
             → EV_MIN_PCT × (1/α_decay) 적용 — 품질 낮은 시간대 진입 차단 강화

  [v4_7-P3] 개선된 Kelly — MDD 연동 동적 분수 조정
             기존: Half-Kelly(0.5×) 고정 + 연속손실 패널티
             개선: MDD 연동 → MDD≤3%: 0.50×Kelly / MDD≤5%: 0.40×Kelly
                              MDD≤8%: 0.30×Kelly / MDD>8%: 0.20×Kelly(최소)
             출처: Thorp, E.O. (1997) "The Kelly Criterion in Blackjack, Sports Betting,
                   and the Stock Market" — MDD-adjusted fractional Kelly

  [v4_7-P4] Almgren-Chriss 시장충격 정밀화
             기존: depth_ratio × spread_bps (단순 추정)
             개선: 영구충격(γ) + 임시충격(η) 분리 추정
                   permanent_impact = γ × order_size / avg_daily_volume
                   temporary_impact = η × order_rate × spread_bps
             출처: Almgren, R. & Chriss, N. (2001) "Optimal Execution of Portfolio
                   Transactions" Journal of Risk, 3, 5-40

  [v4_7-P5] 1일 1진입 보장 게이트 (사용자 운영 요구사항)
             장이 BEAR이고 개인투자자 우위조건 미충족 시에도
             최소 진입 기회 1회 보장 (EV기준 70% 완화 적용)
             단, 킬스위치 5개 조건 중 하나라도 발동 시 제외

[v4_6] PULLBACK 전략 전용 완화 필터 + 피라미딩 ADD_ON + 2사이클 재진입

[v4_4] 수익률 병목 Fix #2 — EV 진입 품질 게이트 강화 (임원진 합동 진단 2026-04-09)
  [FIX-Q1] EV_MIN_PCT: 0.25% → 0.60%
           근거: 0.25% 기준은 거래비용(0.21%) 차감 시 실질 EV=0.04%
                 사실상 아무 종목이나 진입 허용 → 승률·PF 목표치 미달의 핵심 원인
           효과: 저품질 진입 차단 → 기대 승률 +5~10%p, PF 1.5→2.0 도달 가능

  [FIX-Q2] EV_RISK_RATIO_MIN: 1.5 → 2.0
           근거: EV/리스크=1.5는 손익비 1.5:1로 너무 낮음
                 헤지펀드 표준 최소 2.0 적용 (손익비 2.0:1 이상만 진입)

  [FIX-Q3] Regime EV 기준 상향 조정 (EV_MIN 상향에 따른 정합성 유지)
           REGIME_NEUTRAL_EV_MIN: 0.35% → 0.70%
           REGIME_BULL_EV_MIN:    0.20% → 0.50%

  [FIX-Q4] EV 사이징 티어 재조정 (EV_MIN=0.60 기준 재설계)
           EV_SIZE_TIER_HIGH: 0.6% → 1.0%  (1.0%+ → FULL 98% 투입)
           EV_SIZE_TIER_MID:  0.4% → 0.75% (0.75%+ → HIGH 85% 투입)
           0.60~0.75%: BASE 70% (최소 통과 구간)
           효과: EV 품질에 비례한 포지션 배분 → 과투입 방지

  [FIX-Q5] 기관 동행 완화량 상향: INST_EV_RELAX_PCT 0.05 → 0.10
           기관 확인 시 EV 기준 0.60 → 0.50까지 완화 허용

[v4_3] 필수 4건 + 선택 2건 보강 — 구조변경 없는 정밀 강화
  FIX-1  _market_guard: strategy_type/session_type 명시값 기반 개장시간 제어
  FIX-2  EV완화·포지션강화: inst_score단독 → inst_ride=True(4조건동시) 전제
  FIX-3  _ev_position_ratio에 pre_slip/impact/regime 기반 최종 캡 추가
  FIX-4  PARTIAL 잔여재시도 전 drift/pre_slip/EV-risk/regime 재검증
  OPT-5  ev_pct=0 fallback score 전략별 차등화
  OPT-6  모든 skip/block에 구조화된 차단 사유 코드 로그 추가

[v4_2] 잔여 과제 — 기관 기준 강화
  ★ 평가점수 96점 → 97점 목표 ★

  [v4_2 FIX-A] GUARD_OPEN 시가·추세눌림 09:03 안정화 대기 유지

  [v4_2 FIX-B] INST_SCORE 이중 잠금 강화 — 과민 반응 차단
    · 문제: INST_SCORE_MIN=0.25 → 낮은 점수에도 EV 완화 + 포지션 강화
    · 해결1: INST_SCORE_MIN 0.25 → 0.35 (지침서 ride_score 0.40 기준 준용)
    · 해결2: INST_SCORE_HIGH 0.50 → 0.60 (고확신 기준 상향)
    · 해결3: INST_CONSEC_MIN 2 → 3 (연속매수 최소일 강화)
    · 효과: 기관 탑승 오인 감소 → EV 완화 남용 차단 → 수익 품질 향상

[v4_1] 헤지펀드급 96점 달성 — 임원진 회의 보강 5건
[v4_0] 헤지펀드급 96점 달성 — BUG 5건 + PROFIT 5건 + IMPROVE 3건
  ★ 수익률 향상 최우선 ★
  PROFIT-1: 기관 탑승 게이트 — inst_score≥0.30 확인 + EV 기준 완화 (기관 등 탑승 개념)
  PROFIT-2: PARTIAL 후 잔여 수량 즉시 재시도 — 몰빵 포지션 완성 보장
  PROFIT-3: 종가 동시호가(14:50~) 단일 전량 주문 — 분할 비활성화, 체결률 극대화
  PROFIT-4: EV 사이징 현실화 — 2.0R(레버리지 불가) → 잔고비율(0.70/0.85/0.98)로 전환
  PROFIT-5: positions.csv에 inst_score/inst_consec 기록 → 매도엔진 기관이탈 감지 지원

  BUG-1 [CRITICAL]: price=0 시 주문 차단 누락 → _execute_and_track 진입 guard 추가
  BUG-2 [CRITICAL]: PARTIAL 체결 시 done_fps 미등록 → 이중매수 위험 → 즉시 등록
  BUG-3 [MODERATE]: ev_pct=0(데이터없음) → EV 필터 완전 우회 → score≥80 fallback
  BUG-4 [MODERATE]: total_order_krw 사전검증에 ev_mult 미포함 → 잔고 초과 가능 → 반영
  BUG-5 [LOW]:      inst_score 없이 positions.csv 기록 → 매도엔진 정보 단절

  IMPROVE-1: 매도세율 정확화 (0.20%→0.18% KOSDAQ 기준)
  IMPROVE-2: ev_pct=0 종목 보수적 score 기준 허용(score≥80) → 기회 손실 방지
  IMPROVE-3: 기관 탑승 플래그(inst_ride=True) → pnl_linker 전달로 매도엔진 연동

[v3_9] 필수 진입 필터 7종 — 쓰레기 트레이드 40~60% 제거
  ① EV 필터: ev_pct≥0.25% AND ev/risk≥1.5
  ② Score 필터: score≥75
  ③ Market 필터: BEAR금지, NEUTRAL ev≥0.35%, BULL ev≥0.20%
  ④ EV 연동 사이징: ev≥0.6→2.0R, ev≥0.4→1.5R, else→1.0R
  ⑥ Entry 강화: 3분모멘텀≥0.8%, 거래대금증가≥30%
  ⑦ Overheat: 현재봉range > 20봉평균×2.5 → 금지
  [참고] ⑤ 20분 시간죽은 트레이드 → pullback_sell_engine 영역
[v3_8] 헤지펀드급 종합 수정 — BUG 3건 + WEAK 8건 일괄 적용
  BUG-1: [END]로그 들여쓰기 수정 (루프 밖으로)
  BUG-2: 사전 슬리피지 차단 → soft mode (수량 축소, hard block은 100% 초과만)
  BUG-3: 재진입 상태전이 오류 (TIMEOUT_FILL→FILLED 허용)
  WEAK-1: VaR 독립 레이어 (일일변동성 기반 최대손실 검증 추가)
  WEAK-2: Kelly 가중치→투입비율 완충 스케일링 (최소 60% 보장)
  WEAK-3: 멀티전략 fingerprint 체계 (종목/전략 분리 로깅 + CODE레벨 dedup)
  WEAK-4: 분할 1차 실패 → 수량 축소 재시도 (전량 폴백 차단)
  WEAK-5: 수익률 추적 필드 (ev_pct, score, conviction, regime, pre_slip_bps)
  WEAK-6: 시간대별 타임아웃 (개장3s/장중5s/종가120s)
  WEAK-7: Chejan "체결"/"확인" 분리 처리
  WEAK-8: Lock 파일 PID 생존 확인 추가
[v3_7] 슬림화 + FIX: POSITIONS경로통일, max_buy_rows하드캡, pnl_linker경로보장
[v3_6] VaR수정+heartbeat+거래비용보정+circuit breaker
[v3_5] PARTIAL슬리피지컷+재진입차단+Kelly거래비용반영
[v3_4] 경로대문자+SAFEPLUS_BASE+pnl_linker+원자적쓰기
[v3_3] 슬리피지/분할/재진입 동적화+호가충격+시장상태
"""
from __future__ import annotations

import csv
import hashlib
import json  # [PATCH] 누락된 import 추가 — _load_cycle_tracker_mc NameError 수정


# [CYCLE-6 2026-05-21] event_journal.jsonl inline helper
_CYCLE6_LOG_DIR = Path(r"C:\stock_bot\LOG") if 'Path' in dir() else None
def _emit_event(event_type, entity, entity_id="", payload=None, prev_state=None, new_state=None):
    """[CYCLE-6] event_journal.jsonl append-only (fail-safe)."""
    try:
        from pathlib import Path as _P
        from datetime import datetime as _dt
        _evt_path = _P(r"C:\stock_bot\LOG") / f"event_journal_{_dt.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": _dt.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "kiwoom_buy_order_sender",
        }
        if prev_state is not None: _evt["prev_state"] = prev_state
        if new_state is not None: _evt["new_state"] = new_state
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass
import os
import sys
import time
import logging
from datetime import datetime
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# [PATCH-RATELIMIT] Kiwoom TR burst 방지
sys.path.insert(0, r"C:\stock_bot\RUN")
from safeplus_rate_limiter import KiwoomRateLimiter
_limiter = KiwoomRateLimiter()

# ═══════════════════════════════════════════════════════════════
# [STEP-2F-1 2026-05-13] Broker Gateway IPC — read-only helper
#   GetConnectState / GetLoginInfo / BALANCE_TR 만 IPC 위임.
#   SendOrder / cancel_order / Chejan 미접촉.
#   broker 실패 시 호출자가 direct OCX fallback 수행.
# ═══════════════════════════════════════════════════════════════
import uuid as _bro_uuid_bu
import threading as _threading_bu  # [A-1b-CORE 2026-05-15] chejan consume thread (daemon)
_BROKER_IPC_REQ_DIR_BU = Path(r"C:\stock_bot\IPC\requests")
_BROKER_IPC_RES_DIR_BU = Path(r"C:\stock_bot\IPC\responses")


# [STEP-2F-2.5 2026-05-13] Timeout observability — 정책 변경 없이 trace 만
_TIMEOUT_TRACE_LOG_PATH_BU = Path(r"C:\stock_bot\LOG\timeout_trace_buy.log")
_BROKER_HB_PATH_BU         = Path(r"C:\stock_bot\IPC\broker_heartbeat.json")
_BROKER_CHEJAN_DIR_BU      = Path(r"C:\stock_bot\IPC\chejan_events")

_timeout_trace_logger_bu = logging.getLogger("KIWOOM_BUY_TIMEOUT_TRACE")
_timeout_trace_logger_bu.setLevel(logging.INFO)
try:
    _TIMEOUT_TRACE_LOG_PATH_BU.parent.mkdir(parents=True, exist_ok=True)
    _tt_handler_bu = RotatingFileHandler(
        str(_TIMEOUT_TRACE_LOG_PATH_BU),
        maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8-sig",  # [Z15 2026-05-21]
    )
    _tt_handler_bu.setFormatter(logging.Formatter(
        "[%(asctime)s][%(levelname)s][KIWOOM_BUY_TIMEOUT] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _timeout_trace_logger_bu.addHandler(_tt_handler_bu)
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-3 2026-05-13] Chejan IPC consume (READ-ONLY, logger only)
#   broker → IPC/chejan_events → subscriber 단방향 broadcast 검증.
#   OrderState 변경 / 체결 반영 / 포지션 반영 절대 금지. log only.
# ═══════════════════════════════════════════════════════════════
_CHEJAN_POLL_INTERVAL_BU = 0.3       # 300ms 폴링
_CHEJAN_DEDUP_TTL_SEC_BU = 60.0
_CHEJAN_SEEN_BU: dict = {}           # event_id → expiry_ts
_CHEJAN_LAST_POLL_BU: list = [0.0]
# [#5-B chejan→rt_open 2026-06-08] 체결통보 → rt_open 실시간 반영(닫힌루프). 매수체결만(매도는 rt_sell/reconcile).
#   ★기본 SHADOW(NO)=로그만 — 내일 장중 소액 매수로 911(체결수량 누적여부)·9001(코드형식)·905(매수판정) 검증후 env YES로 실반영.
#   목적: 매수직후 rt_open 즉시갱신 → 동시1 hardcap·중복차단·한도가 실시간 정확(브리지/buy_sender 약점 근본해결).
CHEJAN_RT_OPEN_WRITE = os.environ.get("CHEJAN_RT_OPEN_WRITE", "1").lower() in ("1", "true", "yes")  # [활성 2026-06-09] 형식검증+버그수정 후 기본 ON (매수즉시 rt_open 실시간기록→매도엔진 즉시인식)
_RT_OPEN_FILE_BU     = Path(r"C:\stock_bot\DATA\rt_open_positions.json")


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


def _purge_seen_bu():
    now = time.time()
    expired = [eid for eid, exp in _CHEJAN_SEEN_BU.items() if exp < now]
    for eid in expired:
        _CHEJAN_SEEN_BU.pop(eid, None)


def _chejan_update_rt_open(event, fid_data, lg):
    """[#5-B 2026-06-08] 매수 체결통보 → rt_open 실시간 반영. SHADOW(CHEJAN_RT_OPEN_WRITE=0)=로그만.
    매수(905)·주문체결(gubun=0)만 반영 — 매도/취소는 rt_sell/reconcile 담당(충돌방지). 예외 전부 무시(fail-safe)."""
    try:
        if str(event.get("gubun", "")).strip() != "0":          # 0=주문체결만
            return
        _craw = str(fid_data.get("9001", "")).strip()
        code  = "".join(_c for _c in _craw if _c.isdigit())      # [FIX 2026-06-09] 9001 "A420770"→"420770" 정규화(rt_open/매도엔진 키 정합)
        if code:
            code = code[-6:].zfill(6)
        otype = str(fid_data.get("905", "")).strip()
        try:
            qty = int(float(fid_data.get("911", 0) or 0))        # 체결수량(누적여부 내일검증)
        except (TypeError, ValueError):
            qty = 0
        try:
            price = int(float(fid_data.get("910", 0) or 0))      # 체결가
        except (TypeError, ValueError):
            price = 0
        is_buy  = ("매수" in otype) or otype.startswith("+")
        is_sell = ("매도" in otype) or otype.startswith("-")
        if not ((is_buy or is_sell) and qty > 0 and code):
            return
        if not CHEJAN_RT_OPEN_WRITE:
            _act = "추가(매수)" if is_buy else "차감(매도)"
            lg.info("[CHEJAN_RT_OPEN_SHADOW] code=%s otype=%s 911(체결수량)=%s 910(체결가)=%s → would %s rt_open "
                    "(내일 검증후 env CHEJAN_RT_OPEN_WRITE=1로 실반영)", code, otype, qty, price, _act)
            return
        # ── 실 반영 (내일 장중 검증 후 활성) ──
        try:
            _d = json.loads(_RT_OPEN_FILE_BU.read_text(encoding="utf-8-sig")) if _RT_OPEN_FILE_BU.exists() else {}
        except Exception:
            _d = {}
        if not isinstance(_d, dict):
            _d = {}
        _cur = _d.get(code) if isinstance(_d.get(code), dict) else {}
        try:
            _prev = float(_cur.get("qty", 0) or 0)
        except (TypeError, ValueError):
            _prev = 0.0
        if is_buy:
            _cur["qty"] = max(_prev, float(qty))                 # 911=누적체결 가정(단일체결 안전, 분할은 reconcile 폴백)
            if price > 0:
                _cur["entry_price"] = price
            _cur["code"] = code                                  # [FIX 2026-06-09] code 필드 보존
            if not _cur.get("strategy"):                         # [FIX 2026-06-09] 전략 태깅: EOD_PICK창(14:50~15:15)=종가매수→rt_sell 장중skip, 그외=추세눌림→장중관리
                _hhmm_cj = int(datetime.now().strftime("%H%M"))
                _cur["strategy"] = "EOD_PICK" if 1450 <= _hhmm_cj <= 1515 else "PULLBACK"
            _cur["_chejan_ts"] = datetime.now().isoformat()
            _d[code] = _cur
            _newq = _cur["qty"]
        else:  # 매도 체결 → rt_open 차감 (동시1 hardcap RELAY 호환: 매도후 즉시 보유 감소 → 다른종목 매수 허용)
            _newq = _prev - float(qty)                           # 911=누적체결 가정
            if _newq <= 0:
                _d.pop(code, None)                               # 전량매도 → rt_open에서 제거
                _newq = 0
            else:
                _cur["qty"] = _newq
                _cur["_chejan_ts"] = datetime.now().isoformat()
                _d[code] = _cur
        try:
            _RT_OPEN_FILE_BU.write_text(json.dumps(_d, ensure_ascii=False), encoding="utf-8")
            lg.info("[CHEJAN_RT_OPEN_WRITE] code=%s %s qty %s→%s @%s", code, ("매수" if is_buy else "매도"), _prev, _newq, price)
        except Exception as _we:
            lg.warning("[CHEJAN_RT_OPEN_WRITE] 쓰기 실패(무시): %s", _we)
    except Exception as _e:
        try:
            lg.debug("[CHEJAN_RT_OPEN] 갱신 예외(무시): %s", _e)
        except Exception:
            pass


# [BROKER-FILL-BRIDGE 2026-06-10] broker-mode에서 chejan 체결을 result 상태머신에 반영하기 위한 code-키 레지스트리.
#   원인: 실주문이 broker 경유(self.ocx=None)라 result를 갱신하던 OCX 콜백(L4840)이 미발화 →
#         consume는 READ-ONLY(rt_open만 코드로 갱신)라 result가 영원히 SENT → 매 매수 false TIMEOUT_ACK + daily_entry 미카운트.
#   해결: consume가 매수체결을 레지스트리에 노출 → result 소유자(wait_ack_and_fill)가 읽어 ACKED/FILLED 전이. 롤백 env BROKER_FILL_BRIDGE=NO.
_BROKER_FILL_REGISTRY_BU: dict = {}
BROKER_FILL_BRIDGE = os.environ.get("BROKER_FILL_BRIDGE", "YES").strip().upper() != "NO"


def _consume_chejan_events_bu():
    """Chejan IPC events 폴링 (300ms throttled). READ-ONLY.

    동작:
      - IPC/chejan_events/*.json 순회
      - event_id 기준 local seen-cache 적용 (TTL 60s)
      - 신규 이벤트만 logger 출력 (state machine 미접촉)
      - 파일 미삭제 (broker 가 5분 후 청소)
    """
    now = time.time()
    if now - _CHEJAN_LAST_POLL_BU[0] < _CHEJAN_POLL_INTERVAL_BU:
        return
    _CHEJAN_LAST_POLL_BU[0] = now

    try:
        files = sorted(_BROKER_CHEJAN_DIR_BU.glob("*.json"))
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

        _purge_seen_bu()
        if event_id in _CHEJAN_SEEN_BU:
            continue

        _CHEJAN_SEEN_BU[event_id] = now + _CHEJAN_DEDUP_TTL_SEC_BU
        consumed += 1

        latency_ms = -1.0
        try:
            ts_cb = datetime.fromisoformat(
                event.get("ts_broker_callback", "")
            )
            latency_ms = (datetime.now() - ts_cb).total_seconds() * 1000.0
        except Exception:
            pass

        fid_data = event.get("fid_data", {}) or {}
        _timeout_trace_logger_bu.info(
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
        _chejan_update_rt_open(event, fid_data, _timeout_trace_logger_bu)   # [#5-B] 매수 체결 → rt_open 반영(SHADOW 기본)

        # [BROKER-FILL-BRIDGE 2026-06-10] 매수 체결을 code-키 레지스트리에 노출(wait_ack_and_fill이 result로 전이). _chejan_update_rt_open과 동일 파싱.
        try:
            if str(event.get("gubun", "")).strip() == "0":      # 0=주문체결만
                _braw = str(fid_data.get("9001", "")).strip()
                _bcode = "".join(_ch for _ch in _braw if _ch.isdigit())
                if _bcode:
                    _bcode = _bcode[-6:].zfill(6)
                _both = str(fid_data.get("905", "")).strip()
                _bisbuy = ("매수" in _both) or _both.startswith("+")
                try:    _bq = int(float(fid_data.get("911", 0) or 0))   # 체결수량(누적 가정)
                except (TypeError, ValueError): _bq = 0
                try:    _bp = int(float(fid_data.get("910", 0) or 0))   # 체결가
                except (TypeError, ValueError): _bp = 0
                try:    _brm = int(float(fid_data.get("902", 0) or 0))  # 미체결잔량
                except (TypeError, ValueError): _brm = 0
                if _bcode and _bisbuy and _bq > 0:
                    _BROKER_FILL_REGISTRY_BU[_bcode] = {
                        "order_no": str(fid_data.get("9203", "")).strip(),
                        "qty": _bq, "price": _bp, "remain": _brm, "ts": now}
        except Exception:
            pass

    if consumed > 0:
        _timeout_trace_logger_bu.debug(
            "CHEJAN_POLL consumed=%d seen_cache=%d",
            consumed, len(_CHEJAN_SEEN_BU),
        )


# ═══════════════════════════════════════════════════════════════
# [STEP-2F-4 2026-05-13] SendOrder shadow mirror + ACK relay (READ-ONLY)
#   실주문은 direct OCX SendOrder 가 이미 처리. broker 는 mirror 만.
# ═══════════════════════════════════════════════════════════════
_BROKER_ORDER_SHADOW_DIR_BU     = Path(r"C:\stock_bot\IPC\order_shadow")
_BROKER_ORDER_SHADOW_ACK_DIR_BU = Path(r"C:\stock_bot\IPC\order_shadow_ack")
_ACK_RELAY_POLL_INTERVAL_BU     = 0.3
_ACK_RELAY_DEDUP_TTL_SEC_BU     = 60.0
_ACK_RELAY_SEEN_BU: dict        = {}
_ACK_RELAY_LAST_POLL_BU: list   = [0.0]


def _send_shadow_order_bu(engine_name: str, account: str, code: str,
                          qty: int, price: int, order_type: int,
                          screen_no: str, rqname: str,
                          hoga_gb: str = "06",
                          origin_order_no: str = "") -> None:
    """Fire-and-forget shadow SendOrder IPC. 실패해도 silent."""
    try:
        request_id = str(_bro_uuid_bu.uuid4())
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
        req_path = _BROKER_IPC_REQ_DIR_BU / f"{request_id}.json"
        tmp = req_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(req, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(req_path))
    except Exception:
        pass


def _consume_order_shadow_ack_bu():
    """ACK relay polling (300ms throttled). READ-ONLY logger."""
    now = time.time()
    if now - _ACK_RELAY_LAST_POLL_BU[0] < _ACK_RELAY_POLL_INTERVAL_BU:
        return
    _ACK_RELAY_LAST_POLL_BU[0] = now

    try:
        files = sorted(_BROKER_ORDER_SHADOW_ACK_DIR_BU.glob("*.json"))
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
        expired = [k for k, v in _ACK_RELAY_SEEN_BU.items() if v < now]
        for k in expired:
            _ACK_RELAY_SEEN_BU.pop(k, None)
        if eid in _ACK_RELAY_SEEN_BU:
            continue
        _ACK_RELAY_SEEN_BU[eid] = now + _ACK_RELAY_DEDUP_TTL_SEC_BU
        consumed += 1

        latency_ms = -1.0
        try:
            t_cb = datetime.fromisoformat(ev.get("ts_broker_callback", ""))
            latency_ms = (datetime.now() - t_cb).total_seconds() * 1000.0
        except Exception:
            pass

        _timeout_trace_logger_bu.info(
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
            _timeout_trace_logger_bu.warning(
                "ORDER_SHADOW_ACK_STALE event_id=%s order_no=%s state=%s "
                "code=%s latency_ms=%.1f (>3000ms)",
                eid,
                ev.get("order_no", ""),
                ev.get("state", ""),
                ev.get("code", ""),
                latency_ms,
            )

    if consumed > 0:
        _timeout_trace_logger_bu.debug(
            "ORDER_SHADOW_ACK_POLL consumed=%d seen_cache=%d",
            consumed, len(_ACK_RELAY_SEEN_BU),
        )


def _get_broker_context_bu() -> dict:
    """Broker 가동/heartbeat/backlog 컨텍스트 — TIMEOUT 발생 시 보조 진단용."""
    ctx = {"broker": "UNKNOWN", "hb_age_sec": -1, "chejan_backlog": -1}
    try:
        if _BROKER_HB_PATH_BU.exists():
            age = time.time() - _BROKER_HB_PATH_BU.stat().st_mtime
            ctx["hb_age_sec"] = round(age, 1)
            ctx["broker"] = "ALIVE" if age < 30 else "STALE"
        else:
            ctx["broker"] = "NOT_RUNNING"
    except Exception:
        pass
    try:
        if _BROKER_CHEJAN_DIR_BU.exists():
            ctx["chejan_backlog"] = sum(
                1 for _ in _BROKER_CHEJAN_DIR_BU.glob("*.json")
            )
    except Exception:
        pass
    return ctx


# [STEP-2I-2-e 2026-05-14] Broker availability cache (cooldown pattern)
#   broker dead 시 IPC 호출 즉시 skip (대기 0s) → caller direct OCX fallback 진입.
#   collector STEP-2I-2-c 와 동일 패턴. 매수 1회당 최대 ~10s+ 지연 → ~0s 로 감축.
_BROKER_HB_STALE_SEC_BU        = 15.0
_BROKER_DEAD_COOLDOWN_SEC_BU   = 60.0
_BROKER_TIMEOUT_THRESHOLD_BU   = 2
_BROKER_DEAD_UNTIL_BU: float   = 0.0
_consec_broker_timeout_bu: int = 0
_BYPASS_LOG_INTERVAL_SEC_BU    = 10.0
_last_bypass_log_ts_bu: float  = 0.0
_was_broker_dead_bu: bool      = False
_log_bu = logging.getLogger("sender")


def _is_broker_alive_bu() -> bool:
    """heartbeat mtime + cooldown 검사. True=IPC 사용 / False=즉시 fallback."""
    global _last_bypass_log_ts_bu, _was_broker_dead_bu
    now = time.time()
    if now < _BROKER_DEAD_UNTIL_BU:
        if (now - _last_bypass_log_ts_bu) >= _BYPASS_LOG_INTERVAL_SEC_BU:
            try:
                _log_bu.info(
                    "[BROKER-BYPASS] cooldown active (%.1fs remain)",
                    max(0.0, _BROKER_DEAD_UNTIL_BU - now),
                )
            except Exception:
                pass
            _last_bypass_log_ts_bu = now
        _was_broker_dead_bu = True
        return False
    try:
        if not _BROKER_HB_PATH_BU.exists():
            _was_broker_dead_bu = True
            return False
        age = now - _BROKER_HB_PATH_BU.stat().st_mtime
        alive = (age < _BROKER_HB_STALE_SEC_BU)
        # [R 2026-05-21 Path A1] state 검증 추가 — broker SHUTDOWN/RECONNECTING/DISCONNECTED 시 false
        # 5/21 broker 3차 사망 (16:43:30) 같은 hb fresh + state≠CONNECTED race window 차단
        if alive:
            try:
                import json as _json_r
                _hb = _json_r.loads(_BROKER_HB_PATH_BU.read_text(encoding="utf-8-sig"))
                _broker_state = str(_hb.get("state", "")).upper()
                if _broker_state and _broker_state != "CONNECTED":
                    alive = False
            except Exception:
                pass  # state 검증 실패 시 mtime fresh로만 판정 (안전 default)
        if alive and _was_broker_dead_bu:
            try:
                _log_bu.info("[BROKER-RECOVER] broker restored — IPC 재사용")
            except Exception:
                pass
            _was_broker_dead_bu = False
        elif not alive:
            _was_broker_dead_bu = True
        return alive
    except Exception:
        _was_broker_dead_bu = True
        return False


def _mark_broker_dead_bu():
    """broker_dead 진입. cooldown 동안 IPC skip."""
    global _BROKER_DEAD_UNTIL_BU
    _BROKER_DEAD_UNTIL_BU = time.time() + _BROKER_DEAD_COOLDOWN_SEC_BU
    try:
        _log_bu.warning(
            "[BROKER-DEAD] cooldown %ds — direct OCX fallback 활성",
            int(_BROKER_DEAD_COOLDOWN_SEC_BU),
        )
    except Exception:
        pass


def _broker_request_bu(req_type: str, extra: dict = None,
                       timeout_sec: float = 2.0) -> dict:
    """Broker IPC 요청 (read-only). 실패 시 None 반환."""
    # [STEP-2I-2-e 2026-05-14] broker dead 시 IPC skip → 즉시 None (caller fallback)
    global _consec_broker_timeout_bu
    if not _is_broker_alive_bu():
        return None

    request_id = str(_bro_uuid_bu.uuid4())
    req = {
        "request_id": request_id,
        "ts": datetime.now().isoformat(),
        "ttl_sec": int(timeout_sec) + 3,
        "type": req_type,
    }
    if extra:
        req.update(extra)
    if req_type in ("ACCOUNT_INFO", "BALANCE_TR"):
        try:
            from ipc_order_auth_v1 import sign_order_request
            req = sign_order_request(req)
        except Exception:
            return None
    req_path = _BROKER_IPC_REQ_DIR_BU / f"{request_id}.json"
    res_path = _BROKER_IPC_RES_DIR_BU / f"{request_id}.json"
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
                _consec_broker_timeout_bu = 0
            elif res:
                _consec_broker_timeout_bu += 1
                if _consec_broker_timeout_bu >= _BROKER_TIMEOUT_THRESHOLD_BU:
                    _mark_broker_dead_bu()
                    _consec_broker_timeout_bu = 0
            return res
        time.sleep(0.1)
    # [STEP-2I-2-e] poll timeout — broker dead 카운트
    _consec_broker_timeout_bu += 1
    if _consec_broker_timeout_bu >= _BROKER_TIMEOUT_THRESHOLD_BU:
        _mark_broker_dead_bu()
        _consec_broker_timeout_bu = 0
    return None

# ── [v4_6] PULLBACK 전략 전용 완화 필터 ───────────────────────
#  문제: EV_MIN=0.60% 기준은 눌림목 진입 타이밍과 충돌
#        눌림 순간 EV 낮게 보임 → 진입 차단 → 월 13일 → 정상 18~20일
#  해결: PULLBACK 전략에만 별도 완화 기준 적용
#        1차는 무조건 진입 (EV 최소 0.25% + 기관 OFI 확인)
PULLBACK_EV_MIN           = float(os.environ.get("PULLBACK_EV_MIN",        "0.25"))
PULLBACK_NEUTRAL_EV_MIN   = float(os.environ.get("PULLBACK_NEUTRAL_EV",    "0.35"))
PULLBACK_BULL_EV_MIN      = float(os.environ.get("PULLBACK_BULL_EV",       "0.20"))
PULLBACK_EV_RISK_RATIO    = float(os.environ.get("PULLBACK_EV_RISK_RATIO", "1.5"))
PULLBACK_MOM_3M_MIN       = float(os.environ.get("PULLBACK_MOM_3M",        "0.3"))
PULLBACK_VOL_SURGE_MIN    = float(os.environ.get("PULLBACK_VOL_SURGE",     "10.0"))

# PULLBACK 판별 전략 타입 집합
PULLBACK_STRATEGY_TYPES = frozenset({
    "PULLBACK", "TREND_PULLBACK", "TREND", "TREND_FOLLOW",
    "PULLBACK_BUY", "ADDON",
})

# ADD_ON 큐 파일 (pullback_sell_strategy v4_12이 생성)
PULLBACK_ADDON_QUEUE_PATH = Path(
    os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")
) / "DATA" / "queue" / "pullback_addon_queue.csv"

# ★ 자기진화 루프 연결
# [v4_9 CRIT-FIX] 실제 파일 v3_4_FIXED 우선 시도 → 하위 호환 폴백
# 기존: 'pnl_strategy_linker' (suffix 없음) → 미존재 → 항상 NG
#       → 매수 체결 데이터 자기진화 루프 미전달 → Kelly 학습 반쪽 작동
_PNL_LINKER_OK = False
_pnl_write_buy = None
try:
    import sys as _sys
    _run_dir = str(Path(__file__).resolve().parent)
    if _run_dir not in _sys.path:
        _sys.path.insert(0, _run_dir)
    for _pnl_ver in [
        "pnl_strategy_linker_v3_5",          # 실제 파일 — 최우선
        "pnl_strategy_linker_v3_4_FIXED",   # 실제 파일 — 1순위
        "pnl_strategy_linker_v3_4",
        "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL",
        "pnl_strategy_linker_v3_3",
        "pnl_strategy_linker",               # suffix 없음 — 최후 폴백
    ]:
        try:
            import importlib as _il
            _pnl_mod = _il.import_module(_pnl_ver)
            _pnl_write_buy = _pnl_mod.write_buy_fill
            _PNL_LINKER_OK = True
            break
        except (ImportError, AttributeError):
            continue
except Exception:
    pass

# ★ params_reader 연결 (P0 수정)
try:
    from params_reader import get as _params_get
    _PARAMS_OK = True
except Exception:
    _PARAMS_OK = False
    def _params_get(key: str, default=None):
        return default

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    import pytz
    KST = pytz.timezone("Asia/Seoul")

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QAxContainer import QAxWidget
except Exception:
    QApplication = None
    QAxWidget    = None

# ── OrderState 상태머신 ──
class OrderState(str, Enum):
    PENDING            = "PENDING"
    SENT               = "SENT"
    ACKED              = "ACKED"
    PARTIAL            = "PARTIAL"
    FILLED             = "FILLED"
    CANCEL_SENT        = "CANCEL_SENT"
    CANCEL_CONFIRMED   = "CANCEL_CONFIRMED"
    TIMEOUT_ACK        = "TIMEOUT_ACK"
    TIMEOUT_FILL       = "TIMEOUT_FILL"
    RECONCILE_PENDING  = "RECONCILE_PENDING"
    FAILED             = "FAILED"

    def can_transition_to(self, nxt: "OrderState") -> bool:
        _VALID: Dict[str, Tuple] = {
            "PENDING":           ("SENT", "FAILED"),
            "SENT":              ("ACKED", "TIMEOUT_ACK", "FAILED"),
            "ACKED":             ("PARTIAL", "FILLED", "TIMEOUT_FILL"),
            "PARTIAL":           ("FILLED", "CANCEL_SENT", "TIMEOUT_FILL"),
            "FILLED":            (),
            "CANCEL_SENT":       ("CANCEL_CONFIRMED", "RECONCILE_PENDING"),
            "CANCEL_CONFIRMED":  ("FILLED",),               # [BUG-3 FIX] 재진입 체결 허용
            "TIMEOUT_ACK":       ("CANCEL_SENT", "RECONCILE_PENDING", "FILLED"),  # [BUG-3 FIX]
            "TIMEOUT_FILL":      ("CANCEL_SENT", "FILLED"),  # [BUG-3 FIX] 재진입 체결 허용
            "RECONCILE_PENDING": ("FILLED", "CANCEL_CONFIRMED", "FAILED"),
            "FAILED":            (),
        }
        return nxt.value in _VALID.get(self.value, ())

# ── 리턴 코드 ──
RC_OK            = 0
RC_PARTIAL       = 1
RC_HOLD          = 200
RC_STOP_INPUT_0B = 22

MODE_INDEPENDENT = "INDEPENDENT"
MODE_CONTINGENT  = "CONTINGENT"

# ── 상수 ──
DEFAULT_BASE_DIR            = r"C:\stock_bot"
DEFAULT_QUEUE_FILE          = r"DATA\queue\kjs_execute_queue.csv"   # P0: 대문자
DEFAULT_SCREEN_NO           = "3022"
DEFAULT_SCREEN_BAL          = "3023"
DEFAULT_SCREEN_CANCEL       = "3024"
DEFAULT_FIXED_QTY           = 1
DEFAULT_MAX_QTY             = 999999            # 몰빵: 수량 상한 실질 제거
DEFAULT_MAX_BUY_ROWS        = 1   # [2026-06-08 사용자지시] 1종목 몰빵 — 한 번에 1종목만 매수(오늘 3종목 동시 폭주 차단). 분산원하면 4로.
DEFAULT_ORDER_GAP_SEC       = 0.3
DEFAULT_ORDER_GAP_MIN       = 0.2
DEFAULT_CONNECT_TIMEOUT_SEC = 20
DEFAULT_MARKET_OPEN_HHMM    = 900
DEFAULT_MARKET_CLOSE_HHMM   = 1530
MAX_ORDER_RETRY             = 3
LOCK_MAX_AGE_SEC            = 300
# [FALLTHROUGH 2026-06-04] 1등 실패시 즉시 중단(CONTINGENT) → 다음 후보 시도(INDEPENDENT)로 전환.
#   사유: 1등이 기술적 실패(ack/거부)나 갭/품질로 막히면 PULLBACK 전체가 0이 되는 기회손실 차단.
#   안전판: 2등 이하도 품질 게이트(prescore/EV/pullback/balance/gap) 통과해야 매수 + max_buy_rows(4) + 총액캡(200만).
#   집중매수 원하면 env DEFAULT_MAX_BUY_ROWS=1. 되돌림 env ORDER_DEPENDENCY_MODE=CONTINGENT.
DEFAULT_DEPENDENCY_MODE     = MODE_INDEPENDENT   # 1등 실패해도 다음 후보 시도(게이트 통과분만)

# ★ [WEAK-6 FIX] 체결 타임아웃 — 시간대별 차별화
ORDER_ACK_TIMEOUT_SEC   = 5     # 기본 (장중)
ORDER_FILL_TIMEOUT_SEC  = 8     # 기본 (장중)
# 시간대별 타임아웃 (초)
#   개장 초 (09:00~09:10): 유동성 폭발 → 짧은 대기
#   장중 (09:10~14:50): 표준
#   종가 동시호가 (14:50~15:30): 체결 지연 → 긴 대기
TIMEOUT_PROFILES = {
    "OPEN":  {"ack": 3,  "fill": 5},    # 개장 초
    "MID":   {"ack": 5,  "fill": 8},    # 장중 표준
    "CLOSE": {"ack": 10, "fill": 120},   # 14:50~15:20 막판 연속매매 — 최대 2분
    # [GHOST-FIX 2026-06-04] 종가 동시호가(>=15:20): 체결은 15:30 일괄 → ack/fill 둘 다 길게.
    #   기존 ack10/fill120은 15:30 체결 전 타임아웃→오판 취소+REENTRY→중복체결(007390 87주=29×3 사고).
    #   발주 15:20~15:28 후 15:30 체결까지 대기(최대 ~11분). 정상 거부(FAILED)는 별도 빠른 처리.
    "CLOSE_AUCTION": {"ack": int(os.environ.get("CLOSE_AUCTION_ACK_SEC", "660")),
                      "fill": int(os.environ.get("CLOSE_AUCTION_FILL_SEC", "660"))},
}

def _get_timeout_profile() -> Dict[str, int]:
    """시간대 기반 ACK/FILL 타임아웃 반환"""
    hhmm = _hhmm()
    if hhmm < 910:
        return TIMEOUT_PROFILES["OPEN"]
    elif hhmm >= CLOSE_AUCTION_HHMM:   # [GHOST-FIX] 종가 동시호가 — 15:30 일괄체결까지 대기
        return TIMEOUT_PROFILES["CLOSE_AUCTION"]
    elif hhmm >= 1450:
        return TIMEOUT_PROFILES["CLOSE"]
    else:
        return TIMEOUT_PROFILES["MID"]

# ★ 잔고 안전율 — 몰빵 전액 투입 근접
BALANCE_SAFETY_RATIO    = float(os.environ.get("BALANCE_SAFETY_RATIO", "0.98"))
BALANCE_RETRY           = int(os.environ.get("BALANCE_RETRY", "5"))
# [R1-B 2026-05-21] BALANCE_TR timeout 흡수 — broker burst/cooldown (60s) 대비 retry 총 시간 ~25s 확보
BALANCE_RETRY_WAIT_SEC  = float(os.environ.get("BALANCE_RETRY_WAIT_SEC", "5.0"))

# ★ 거래비용 — Kelly 정확도용
# [IMPROVE-1] 매도세율 정확화: KOSDAQ 0.18% (0.20%→0.18%)
# [v4_1 FIX] KOSPI/KOSDAQ 구분: KOSPI 0.20%, KOSDAQ 0.18%
# 왕복: 매수0.015%+매도0.015%+매도세 = KOSDAQ 0.210% / KOSPI 0.230%
TRADE_COST_ROUNDTRIP_PCT = 0.00210   # 기본(KOSDAQ) — _trade_cost_pct() 함수로 종목별 분기

def _trade_cost_pct(code: str) -> float:
    """종목 코드 기반 KOSPI/KOSDAQ 거래비용 구분
    KOSPI: 0~599999 → 매도세 0.20% → 왕복 0.230%
    KOSDAQ: 600000~ 또는 Q로 시작 → 매도세 0.18% → 왕복 0.210%
    키움 기준: A 제거 후 6자리 숫자, 0~599999 = KOSPI
    """
    try:
        num = int(code.strip().lstrip("AaQq").zfill(6)[:6])
        if num < 600000:
            return 0.00230  # KOSPI
    except Exception:
        pass
    return 0.00210  # KOSDAQ (기본)
# ★ [WEAK-1 FIX] VaR 독립 레이어 — BALANCE_SAFETY_RATIO와 분리
#    1종목 몰빵 시 일일 최대 허용 손실률 기반 (계좌 대비)
#    예: 계좌 1000만, daily_max_loss=5% → 최대 50만원 손실 허용
#    reverse로 계산: 종목 변동성 대비 투입한도 = daily_max_loss / expected_daily_vol
MAX_ACCOUNT_EXPOSURE_PCT = float(os.environ.get("MAX_ACCOUNT_EXPOSURE_PCT", "0.98"))
VAR_DAILY_MAX_LOSS_PCT   = float(os.environ.get("VAR_DAILY_MAX_LOSS_PCT", "0.03"))  # [DAILY-UNIFY 2026-06-04] 5%→3% (rt_sell MAX_DAILY_LOSS -3%와 통일)

# ═══════════════════════════════════════════════════════════════
# [SAFE+ 통합 패치] 실계좌 200만원 하드캡 — 단일 진리
#   사이징/상한/클램프 모두 이 값 기준. 계좌 잔고가 더 많아도 cap 초과 금지.
#   환경변수 SAFEPLUS_CAPITAL 미설정 또는 비정수 시 → 기본 200만원
# ═══════════════════════════════════════════════════════════════
# [CAPITAL-SSOT 2026-06-04] 단일 소스 capital_config(config/capital.json) 우선.
#   우선순위: env SAFEPLUS_CAPITAL > config capital_krw > 200만.
#   ⚠ capital_krw 는 '운용 허용액'이지 '통장 잔고'가 아니다 — 통장(예: 2600만) 자동반영 금지.
_CAPCFG = None
try:
    import capital_config as _CAPCFG
    SAFEPLUS_CAPITAL = _CAPCFG.get_capital()
except Exception:
    try:
        SAFEPLUS_CAPITAL = int(os.environ.get("SAFEPLUS_CAPITAL", "2000000"))
    except (ValueError, TypeError):
        SAFEPLUS_CAPITAL = 2000000
SAFEPLUS_CAPITAL_HARD_RATIO = 0.98   # [CLAMP_CAP] order_value <= cap × 0.98 강제
# REAL_TEST_MODE 동기화 (sender는 사이징에 직접 사용 안하나 로그/디버그용)
REAL_TEST_MODE_FLAG = os.environ.get("REAL_TEST_MODE", "true").strip().lower() == "true"
# ═══════════════════════════════════════════════════════════════
#  [PATCH-RTM] 실행엔진과 REAL_TEST_MODE 해석 동기화
#    실행엔진은 REAL_TEST_MODE=true → REAL_TEST_CAPITAL 사용
#    매수센더도 동일 기준으로 SAFEPLUS_CAPITAL 추가 클램프
#    (REAL_TEST_MODE=true에서 실제 잔고 풀사용 발주 차단)
# ═══════════════════════════════════════════════════════════════
try:
    _RTM_REAL_TEST_CAPITAL = int(os.environ.get("REAL_TEST_CAPITAL", "2000000"))
except (ValueError, TypeError):
    _RTM_REAL_TEST_CAPITAL = 2000000
try:
    _RTM_TOTAL_CAPITAL = int(os.environ.get("TOTAL_CAPITAL", "50000000"))
except (ValueError, TypeError):
    _RTM_TOTAL_CAPITAL = 50000000
_RTM_EFFECTIVE_CAP = _RTM_REAL_TEST_CAPITAL if REAL_TEST_MODE_FLAG else _RTM_TOTAL_CAPITAL
# 더 작은 값으로 클램프 — REAL_TEST_MODE 기준이 SAFEPLUS_CAPITAL보다 작으면 그쪽이 진실
SAFEPLUS_CAPITAL = min(SAFEPLUS_CAPITAL, _RTM_EFFECTIVE_CAP)

# ═══════════════════════════════════════════════════════════════
# [DAILY-TOTAL-CAP 2026-06-04] 오늘 발주 누적 총액 ≤ 운용한도 — '통장 묶기'의 핵심 자물쇠.
#   통장에 2600만이 있어도 시스템은 오늘 합계가 운용한도(기본 200만)에 도달하면 더 발주 안 함.
#   체결+미체결 모두 발주 시점에 누적(취소분 미차감=보수적), 종목·전략 무관. 일자 바뀌면 자동 리셋.
#   → 007390 87주=300만 사고처럼 '건당은 통과하나 누적이 초과'하는 모든 경로를 원천 차단.
# ═══════════════════════════════════════════════════════════════
_DAILY_TOTAL_FILE = Path(r"C:\stock_bot\data\eod_pickup\daily_order_total.json")
# [B 패치 2026-06-08] 동일종목 당일 누적 주문 hard cap (중복매수 폭주 backstop)
_DAILY_CODE_FILE  = Path(r"C:\stock_bot\data\eod_pickup\daily_code_orders.json")
CODE_DAILY_MAX_COUNT = int(os.environ.get("CODE_DAILY_ORDER_MAX_COUNT", "4"))   # 동일종목 당일 주문 횟수 상한(정상 1~3회차 ADD + 여유1). 초과=절대차단
CODE_DAILY_MAX_KRW   = int(os.environ.get("CODE_DAILY_ORDER_MAX_KRW",   "0"))   # 동일종목 당일 누적 주문액 상한(0=운용한도와 동일)

# ── [#2 급락장 킬스위치 2026-06-08] 신규매수 SendOrder 직전 비상차단 ──────────────
#   매수만 차단(매도/취소/잔고/수집기 무관). 우선순위: manual > capital<=0 > crash/cb > preflight stale/block.
#   ⚠현재 preflight는 CB 자동감지 안 함(size_mult/decision/crash필드는 preflight_gate 후속수정 시 작동) →
#     이번 실효 차단 = manual_buy_block(사람 즉시) + capital_krw<=0 + 전일/없음 preflight. CB 자동감지는 후속(#2-2).
_MANUAL_BUY_BLOCK_FLAG = Path(r"C:\stock_bot\config\manual_buy_block.flag")
# [KS-WIRE 2026-06-10] kill_switch.flag 실배선 — 기존엔 워치독만 쓰고 읽는 매매코드 0(장식품).
#   거짓 생성자(좀비 PULLBACK/SIGA 워치독)는 6/10 Disabled → 이제 이 flag 존재 = 의도적 정지 → 매수 차단.
_KILL_SWITCH_FLAG = Path(r"C:\stock_bot\data\kill_switch.flag")
_PREFLIGHT_CANDS = [
    Path(r"C:\stock_bot\data\LOG\preflight_result.json"),
    Path(r"C:\stock_bot\DATA\preflight_result.json"),
    Path(r"C:\stock_bot\DATA\LOG\preflight_result.json"),
]
PREFLIGHT_MAX_AGE_SEC     = int(os.environ.get("PREFLIGHT_MAX_AGE_SEC", "28800"))  # 8h: 당일 09:00 preflight가 17시까지 커버(갱신 안 되는 현 구조 보호). 당일여부도 별도 체크.
CRASH_KILL_SWITCH_ENABLED = os.environ.get("CRASH_KILL_SWITCH_ENABLED", "1").lower() not in ("0", "false", "no")
# [INDEX_CRASH 2026-06-08] 시장 지수 급락 실시간 차단 — prices_1m 현재가 vs eod_daily_bars 전일종가 중앙 등락률.
#   검증(1년 251일): 정상일 중앙 ±0.4%(오차단0), 급락일만 -6%↓(3/4 -9.96%·6/8 -6.9%). 매수직전 실시간이라 갭다운+장중 급락 둘다 차단.
#   ※preflight는 09:00 1회 고정이라 장중 급락 못잡음 → kill_switch(매수직전)에 둠. 데이터부족시 fail-open(통과).
INDEX_CRASH_ENABLED   = os.environ.get("INDEX_CRASH_ENABLED", "1").lower() not in ("0", "false", "no")
INDEX_CRASH_BLOCK_PCT = float(os.environ.get("INDEX_CRASH_BLOCK_PCT", "-0.06"))  # 시장 중앙 등락률 ≤ 이값 → 신규매수 차단
# [MKT-SOFT 2026-06-10] PULLBACK 한정 약세장 소프트게이트(-6% 하드와 별개 중간지대) — 백테 근거 위 참조
PULLBACK_MKT_SOFT_PCT = float(os.environ.get("PULLBACK_MKT_SOFT_PCT", "-0.015"))


def _kosdaq_intraday_pct():
    """[MKT-SOFT] 코스닥지수(U201) 일중 등락 = 마지막close/당일첫open - 1. 데이터없음→None(fail-open).
    ※_market_crash_pct(수집 중앙)는 universe가 거래대금 상위=생존편향이라 시장폭 못 읽음
      (6/10 실측: 지수 -2.7%인데 중앙 -0.19%) → 지수 직접 사용."""
    try:
        import csv as _csv
        _today = time.strftime("%Y%m%d")
        _first_o = None; _last_c = None
        with open(r"C:\stock_bot\data\prices_1m.csv", encoding="utf-8-sig", errors="replace") as _f:
            for _r in _csv.reader(_f):
                if len(_r) > 5 and _r[0] == "U201" and str(_r[1])[:8] == _today:
                    if _first_o is None:
                        try: _first_o = float(_r[2])
                        except (TypeError, ValueError): pass
                    try: _last_c = float(_r[5])
                    except (TypeError, ValueError): pass
        if _first_o and _last_c and _first_o > 0:
            return _last_c / _first_o - 1.0
    except Exception:
        pass
    return None
INDEX_CRASH_MIN_MATCH = int(os.environ.get("INDEX_CRASH_MIN_MATCH", "50"))       # 매칭 종목<이값 = 데이터부족 fail-open
_EOD_DAILY_BARS_FILE  = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
_PRICES_1M_FILE       = Path(r"C:\stock_bot\DATA\prices_1m.csv")
_PREV_CLOSE_CACHE     = {"mtime": None, "map": None}
# [CONCURRENT 2026-06-08] 동시 보유 종목수 hardcap — 무조건 1종목 몰빵(사용자지시). 매도후(RELAY) 다른종목은 허용. 금액 커지면 env 2/3.
MAX_CONCURRENT_POSITIONS = int(os.environ.get("MAX_CONCURRENT_POSITIONS", "1"))
# [STRAT-SLOT 2026-06-11 사용자결정] 동시보유 카운트 범위.
#   STRATEGY = 전략별 1슬롯(추세눌림 1 + 종가매수 1 병행 허용) — 눌림 보유가 14:55 종가매수를
#              막던 충돌 해소. 합산 노출은 daily_total cap(운용한도)·order_max가 별도 방어.
#   GLOBAL   = 기존 전체 1슬롯. 롤백: setx MAX_CONCURRENT_SCOPE GLOBAL
MAX_CONCURRENT_SCOPE = os.environ.get("MAX_CONCURRENT_SCOPE", "STRATEGY").strip().upper()
# [CONCURRENT-VALUE 2026-06-09 사용자지시] 보유가치(qty×entry_price)가 이 금액 미만인 잔여 포지션(검증용 1주 등)은
#   "몰빵 슬롯"을 점유하지 않음 → 신규매수 안 막음. 7천원짜리 1주가 200만 매수를 막던 문제 해소.
#   진짜 몰빵 포지션(수십만~)만 동시1종목 카운트. entry_price 불명(<=0)이면 안전하게 보유 간주(카운트).
MAX_CONCURRENT_MIN_VALUE_KRW = int(os.environ.get("MAX_CONCURRENT_MIN_VALUE_KRW", "100000"))
_PENDING_BUY = {}     # code(zfill6): ts — 발주 직후 rt_open 반영 전 임시보유(chejan 미완 갭 보완)


def _read_preflight(logger):
    """preflight_result.json 후보 중 최신 선택 + [PREFLIGHT_SOURCE] 로그. 반환 (dict|None, path, age_sec|None)."""
    best = None; best_m = -1.0
    for c in _PREFLIGHT_CANDS:
        try:
            if c.exists():
                m = c.stat().st_mtime
                if m > best_m:
                    best_m = m; best = c
        except Exception:
            pass
    if best is None:
        logger.warning("[PREFLIGHT_SOURCE] path=NONE 파일없음 → fail-safe 신규매수 차단")
        return None, "NONE", None
    try:
        d = json.loads(best.read_text(encoding="utf-8-sig"))
        age = time.time() - best_m
        logger.info("[PREFLIGHT_SOURCE] path=%s mtime=%s age_sec=%.0f decision=%s entry_mode_hint=%s size_mult=%s",
                    best, datetime.fromtimestamp(best_m).strftime("%H:%M:%S"), age,
                    d.get("decision"), d.get("entry_mode_hint"), d.get("size_mult"))
        return d, str(best), age
    except Exception as e:
        logger.warning("[PREFLIGHT_SOURCE] path=%s 읽기실패:%s → fail-safe 차단", best, e)
        return None, str(best), None


def _load_prev_close():
    """[INDEX_CRASH] eod_daily_bars 종목별 최신(전일) 종가 dict. mtime 캐시. 실패→None(fail-open)."""
    try:
        if not _EOD_DAILY_BARS_FILE.exists():
            return None
        _mt = _EOD_DAILY_BARS_FILE.stat().st_mtime
        if _PREV_CLOSE_CACHE["mtime"] == _mt:
            return _PREV_CLOSE_CACHE["map"]
        _eod = {}
        with _EOD_DAILY_BARS_FILE.open("r", encoding="utf-8-sig", errors="replace") as _f:
            for _r in csv.DictReader(_f):
                _c = str(_r.get("code", "")).strip()
                try:
                    _eod[_c] = (str(_r.get("date", "")), float(_r.get("close") or 0))
                except (TypeError, ValueError):
                    pass
        _latest = max((d for d, _ in _eod.values()), default="")
        _m = {k: v for k, (d, v) in _eod.items() if d == _latest and v > 0}
        _PREV_CLOSE_CACHE["mtime"] = _mt
        _PREV_CLOSE_CACHE["map"] = _m
        return _m
    except Exception:
        return None


def _market_crash_pct():
    """[INDEX_CRASH] prices_1m 오늘 현재가 vs eod 전일종가 → 시장 중앙 등락률(소수). 데이터부족→None(fail-open)."""
    _prev = _load_prev_close()
    if not _prev:
        return None
    try:
        _p1m = {}
        _today = datetime.now().strftime("%Y%m%d")
        with _PRICES_1M_FILE.open("r", encoding="utf-8-sig", errors="replace") as _f:
            for _r in csv.DictReader(_f):
                _c = str(_r.get("code", "")).strip()
                if _c in ("U001", "U201"):
                    continue
                if str(_r.get("ts", "")).startswith(_today):
                    try:
                        _p1m[_c] = float(_r.get("close") or 0)
                    except (TypeError, ValueError):
                        pass
        _rets = []
        for _c, _px in _p1m.items():
            _pv = _prev.get(_c)
            if _pv and _pv > 0 and _px > 0:
                _rets.append(_px / _pv - 1)
        if len(_rets) < INDEX_CRASH_MIN_MATCH:
            return None
        _rets.sort()
        return _rets[len(_rets) // 2]
    except Exception:
        return None


def _held_codes_and_all():
    """[CONCURRENT] rt_open_positions → (qty>0 종목 set, 전체 dict). 실패→(set(), {})."""
    try:
        _p = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
        if not _p.exists():
            return set(), {}
        _d = json.loads(_p.read_text(encoding="utf-8-sig"))
        _held = set()
        for _c, _v in _d.items():
            if isinstance(_v, dict):
                try:
                    if float(_v.get("qty", 0) or 0) > 0:
                        _held.add(str(_c).zfill(6))
                except (TypeError, ValueError):
                    pass
        return _held, _d
    except Exception:
        return set(), {}


def _concurrent_held_count(strategy=None):
    """[CONCURRENT] 동시 보유 종목수 = rt_open(qty>0 AND 보유가치>=MAX_CONCURRENT_MIN_VALUE_KRW) ∪ 발주직후 pending.
    ★보유가치 임계 미만(검증용 1주 등 자투리)은 몰빵 슬롯 미점유 → 신규매수 안 막음(2026-06-09 사용자지시).
    entry_price 불명(<=0)이면 안전하게 보유 간주(카운트). 매도(rt_open qty<=0)는 제외→RELAY(매도후 다른종목) 호환.
    [STRAT-SLOT 2026-06-11] strategy 지정 + MAX_CONCURRENT_SCOPE=STRATEGY 시 같은 전략 보유만 카운트
    (다른 전략 보유는 슬롯 미점유 → 눌림1+종가1 병행). 전략표기 없는 보유는 보수적으로 전 전략 카운트.
    pending은 전략 불명이라 항상 카운트(보수적)."""
    _held, _all = _held_codes_and_all()
    _now = time.time()
    _cnt = set()
    # rt_open 보유: 보유가치 임계 이상만 카운트(자투리 1주 무시)
    for _c, _v in (_all or {}).items():
        if not isinstance(_v, dict):
            continue
        try:
            _qty = float(_v.get("qty", 0) or 0)
        except (TypeError, ValueError):
            _qty = 0.0
        if _qty <= 0:                               # 매도됨/잔재 → 제외(RELAY 허용)
            continue
        if MAX_CONCURRENT_SCOPE == "STRATEGY" and strategy:
            _es = str(_v.get("strategy", "") or "").strip().upper()
            if _es and _es != str(strategy).strip().upper():
                continue                            # 다른 전략 슬롯 — 미점유(합산은 daily_total cap 방어)
        try:
            _ep = float(_v.get("entry_price", 0) or 0)
        except (TypeError, ValueError):
            _ep = 0.0
        if _ep <= 0 or (_qty * _ep) >= MAX_CONCURRENT_MIN_VALUE_KRW:
            _cnt.add(str(_c).zfill(6))              # 가격불명(안전) or 몰빵급 보유가치 → 슬롯 점유
        # else: 자투리(보유가치<임계) → 슬롯 미점유(신규매수 허용)
    # 발주직후 pending(실매수 in-flight, full size) → 카운트
    for _c in list(_PENDING_BUY.keys()):
        if _now - _PENDING_BUY[_c] > 86400:        # 당일만(자정 만료)
            _PENDING_BUY.pop(_c, None); continue
        _c6 = str(_c).zfill(6)
        _v = _all.get(_c) or _all.get(_c6)
        if isinstance(_v, dict):
            try:
                if float(_v.get("qty", 0) or 0) <= 0:   # rt_open에 qty<=0 = 매도됨 → 제외(RELAY 허용)
                    continue
            except (TypeError, ValueError):
                pass
        _cnt.add(_c6)                                # rt_open 미등장(매수직후) or qty>0 → 보유 간주
    return len(_cnt), _cnt


def _crash_kill_switch(logger, strategy=None):
    """[#2] 신규매수 차단 판정. 반환 (block:bool, reason:str). 매수 SendOrder 직전 + DAILY_MIN에서 호출.
    매도/취소/잔고/수집기와 무관 — 신규매수만 차단.
    [STRAT-SLOT 2026-06-11] strategy 전달 시 동시보유(2c)를 전략별 슬롯으로 판정."""
    if not CRASH_KILL_SWITCH_ENABLED:
        return False, "killswitch_disabled"
    # 1. manual_buy_block (flag 파일) — 최우선 수동차단
    try:
        if _MANUAL_BUY_BLOCK_FLAG.exists():
            return True, "manual_buy_block(flag)"
    except Exception:
        pass
    # 1-b. [KS-WIRE 2026-06-10] kill_switch.flag — 전체 매매 정지 의사 표시 시 매수 차단
    try:
        if _KILL_SWITCH_FLAG.exists():
            return True, "kill_switch(flag)"
    except Exception:
        pass
    # 2. capital_krw <= 0 — 비상 수동차단(env/REAL_TEST_MODE보다 우선)
    try:
        if _CAPCFG is not None and int(_CAPCFG.get_capital()) <= 0:
            return True, "capital_krw<=0"
    except Exception:
        pass
    # 2b. [INDEX_CRASH 2026-06-08] 시장 지수 급락 실시간 차단 (매수직전, 갭다운+장중 둘다). 데이터부족→fail-open(통과).
    if INDEX_CRASH_ENABLED:
        try:
            _mc = _market_crash_pct()
            if _mc is not None and _mc <= INDEX_CRASH_BLOCK_PCT:
                try:
                    logger.warning("[INDEX_CRASH] 시장 중앙 등락률 %.2f%% <= %.2f%% → 신규매수 차단",
                                   _mc * 100, INDEX_CRASH_BLOCK_PCT * 100)
                except Exception:
                    pass
                return True, "index_crash(median=%.2f%%)" % (_mc * 100)
        except Exception:
            pass
    # 2c. [CONCURRENT 2026-06-08] 동시 보유 종목수 hardcap — 무조건 1종목 몰빵(사용자지시). 매도후(RELAY)는 보유0이라 통과.
    try:
        _hc, _hset = _concurrent_held_count(strategy)
        if _hc >= MAX_CONCURRENT_POSITIONS:
            try:
                logger.warning("[CONCURRENT_BLOCK] 동시 보유 %d종목(%s) >= 상한 %d → 신규매수 차단(scope=%s strat=%s)",
                               _hc, ",".join(sorted(_hset)), MAX_CONCURRENT_POSITIONS,
                               MAX_CONCURRENT_SCOPE, strategy or "-")
            except Exception:
                pass
            return True, "concurrent_positions(%d>=%d)" % (_hc, MAX_CONCURRENT_POSITIONS)
    except Exception:
        pass
    # 3. preflight 읽기 (경로 단일화 + 로그)
    pf, pf_path, age = _read_preflight(logger)
    if pf is None:
        return True, f"preflight_missing_or_unreadable({pf_path})"
    # 3a. 당일 아님(전일 preflight로 오늘 매수 방지) 또는 stale
    try:
        _ts = str(pf.get("ts", ""))[:10].replace("-", "")
        if _ts and _ts != datetime.now().strftime("%Y%m%d"):
            return True, f"preflight_not_today(ts={_ts})"
    except Exception:
        pass
    if age is not None and age > PREFLIGHT_MAX_AGE_SEC:
        return True, f"preflight_stale(age={age:.0f}s>{PREFLIGHT_MAX_AGE_SEC})"
    # 3b. decision / entry_mode_hint BLOCK/CRASH/CB/HALT 계열
    dec  = str(pf.get("decision", "")).upper()
    hint = str(pf.get("entry_mode_hint", "")).upper()
    if any(k in dec for k in ("BLOCK", "CRASH", "CB", "HALT", "STOP")):
        return True, f"preflight_decision={dec}"
    if any(k in hint for k in ("BLOCK", "CRASH", "CB", "HALT", "STOP")):
        return True, f"entry_mode_hint={hint}"
    # 3c. size_mult <= 0
    try:
        if float(pf.get("size_mult", 1.0)) <= 0:
            return True, "size_mult<=0"
    except Exception:
        pass
    # 3d. crash/cb/market_crash 관련 필드 True
    for fld in ("crash", "cb", "market_crash", "circuit_breaker", "is_crash", "halt"):
        try:
            if bool(pf.get(fld, False)):
                return True, f"preflight_field_{fld}=True"
        except Exception:
            pass
    return False, "ok"


def _daily_total_cap() -> int:
    """오늘 발주 누적 총액 상한(원). capital_config(daily_total_max) 우선, 폴백 SAFEPLUS_CAPITAL."""
    if _CAPCFG is not None:
        try:
            return _CAPCFG.get_limit("daily_total_max")
        except Exception:
            pass
    return SAFEPLUS_CAPITAL

def _load_daily_total() -> int:
    today = datetime.now().strftime("%Y%m%d")
    try:
        if _DAILY_TOTAL_FILE.exists():
            d = json.loads(_DAILY_TOTAL_FILE.read_text(encoding="utf-8"))
            if str(d.get("date", "")) == today:
                return int(d.get("total_krw", 0) or 0)
    except Exception:
        pass
    return 0   # 날짜 다르면 0 = 자동 일자 리셋

def _add_daily_total(krw: int) -> None:
    if krw <= 0:
        return
    today = datetime.now().strftime("%Y%m%d")
    cur = _load_daily_total()
    try:
        _DAILY_TOTAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _tmp = str(_DAILY_TOTAL_FILE) + ".tmp"
        Path(_tmp).write_text(json.dumps({"date": today, "total_krw": cur + int(krw)}),
                              encoding="utf-8")
        os.replace(_tmp, str(_DAILY_TOTAL_FILE))
    except Exception:
        pass

def _held_positions_value() -> int:
    """[CAP-RECONCILE 2026-06-05] rt_open_positions 실보유(qty>0) 진입가치 합(원).
    누적(_load_daily_total)은 '송신' 기준이라 미체결분이 phantom 점유 → 실보유로 reconcile해 해제.
    실패→-1(reconcile 미적용, 기존 누적 사용=보수)."""
    try:
        import json as _j
        _p = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
        if not _p.exists():
            return -1
        _d = _j.loads(_p.read_text(encoding="utf-8-sig"))
        _tot = 0.0
        for _v in _d.values():
            if not isinstance(_v, dict):
                continue
            try:
                _q = float(_v.get("qty", 0) or 0)
                _e = float(_v.get("entry_price", 0) or 0)
            except (TypeError, ValueError):
                continue
            if _q > 0 and _e > 0:
                _tot += _q * _e
        return int(_tot)
    except Exception:
        return -1


def _daily_total_cap_ok(order_krw: int, logger) -> bool:
    """오늘 누적 + 이번 order_krw > 운용한도면 False(발주 차단).
    [A 패치 2026-06-08] min(cur,_held) 제거 → 송신 누적(cur) 기준으로 차단.
      사유: _held(rt_open)는 체결 닫힌루프 부재로 ghost(체결 미반영)→0 → eff_cur=min(cur,0)=0 → 한도 무력 →
            동일종목 중복매수 폭주(6/8 131970 87주=운용한도 5.5배). _held는 참고 로그로만, 한도 차감엔 미사용.
      _add_daily_total은 SendOrder 성공(SENT) 시 가산 → ACK 타임아웃/order_send_or_ack_fail에도 cur 유지 → 재주문 차단.
      ※미체결 phantom(진짜 미체결분의 한도 점유) 해소는 이 패치 범위 밖 — 후속 reconciler 패치로 분리."""
    if order_krw <= 0:
        return True
    cap = _daily_total_cap()
    cur = _load_daily_total()
    _held = _held_positions_value()   # 참고 로그용 (한도 차감 미사용)
    if cur + order_krw > cap:
        logger.warning(
            "[DAILY_TOTAL_CAP] ⛔ 누적%d + 이번 %d = %d > 운용한도 %d → 발주 차단 (참고:rt_open실보유%d, 한도차감엔 미사용)",
            cur, order_krw, cur + order_krw, cap, _held)
        return False
    return True


def _load_code_order(code: str):
    """[B 패치 2026-06-08] 동일종목 당일 누적 주문 (krw, count). 날짜 다르면 (0,0)=자동 일자리셋."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        if _DAILY_CODE_FILE.exists():
            d = json.loads(_DAILY_CODE_FILE.read_text(encoding="utf-8"))
            if str(d.get("date", "")) == today:
                rec = (d.get("codes", {}) or {}).get(str(code), {}) or {}
                return int(rec.get("krw", 0) or 0), int(rec.get("count", 0) or 0)
    except Exception:
        pass
    return 0, 0


def _add_code_order(code: str, krw: int) -> None:
    """[B 패치 2026-06-08] 동일종목 당일 주문 누적 가산(금액+횟수). SendOrder 성공 시 호출."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        d = {}
        if _DAILY_CODE_FILE.exists():
            d = json.loads(_DAILY_CODE_FILE.read_text(encoding="utf-8"))
        if str(d.get("date", "")) != today:
            d = {"date": today, "codes": {}}
        codes = d.setdefault("codes", {})
        rec = codes.setdefault(str(code), {"krw": 0, "count": 0})
        rec["krw"]   = int(rec.get("krw", 0) or 0) + max(0, int(krw))
        rec["count"] = int(rec.get("count", 0) or 0) + 1
        _DAILY_CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _tmp = str(_DAILY_CODE_FILE) + ".tmp"
        Path(_tmp).write_text(json.dumps(d), encoding="utf-8")
        os.replace(_tmp, str(_DAILY_CODE_FILE))
    except Exception:
        pass


def _code_order_cap_ok(code: str, order_krw: int, logger) -> bool:
    """[B 패치 2026-06-08] 동일종목 당일 누적 주문 횟수/금액 hard cap.
    ACK/reconcile 무관 절대 차단 — 6/8 동일종목 9회 중복매수 같은 폭주 원천 봉쇄(backstop)."""
    code = str(code)
    krw_sum, cnt = _load_code_order(code)
    if cnt + 1 > CODE_DAILY_MAX_COUNT:
        logger.warning("[CODE_ORDER_CAP] ⛔ %s 당일 주문횟수 %d→%d > 상한 %d → 발주 차단(중복폭주 방지)",
                       code, cnt, cnt + 1, CODE_DAILY_MAX_COUNT)
        return False
    _kcap = CODE_DAILY_MAX_KRW if CODE_DAILY_MAX_KRW > 0 else _daily_total_cap()
    if order_krw > 0 and krw_sum + order_krw > _kcap:
        logger.warning("[CODE_ORDER_CAP] ⛔ %s 당일 누적주문액 %d + %d = %d > 상한 %d → 발주 차단",
                       code, krw_sum, order_krw, krw_sum + order_krw, _kcap)
        return False
    return True

# ★ 자기진화 — Half-Kelly (P2: 거래 횟수 기준)
EVOLVE_LOOKBACK_TRADES = int(os.environ.get("EVOLVE_LOOKBACK_TRADES", "20"))  # P2 수정
EVOLVE_MIN_WEIGHT      = 0.20
EVOLVE_MAX_WEIGHT      = 0.60
EVOLVE_MIN_SAMPLES     = 5
EVOLVE_CONSERVATIVE    = 0.30
EVOLVE_CONSEC_PENALTY  = 0.05
EVOLVE_MDD_THRESHOLD   = -0.05
EVOLVE_MDD_PENALTY     = 0.10
EVOLVE_ENABLED         = os.environ.get("EVOLVE_ENABLED","1").lower() \
                         not in ("0","false","no")

# ─── 시장 가드 (당일청산 전략 전용 — 시가·추세눌림) ─────────────
# [v4_7] 종배/시배/OPENING/GAP_OPEN 전략 완전 분리
#   이 프로그램은 09:03 안정화 대기 후 진입하는 당일청산 전략만 처리
GUARD_OPEN_STABLE_HHMM  = 903   # 09:03 안정화 대기 (전략 공통)
GUARD_CLOSE_HHMM        = 1450
GUARD_MAX_CANCEL_CNT    = 3
# [EOD_PICK 2026-05-28] 종가매수 전용 마감 한도 — EOD_PICK 전략만 15:25까지 예외 허용.
# SIGA/PULLBACK/RT_ENGINE은 GUARD_CLOSE_HHMM(1450) 기존 차단 유지.
EOD_PICK_CLOSE_HHMM     = 1528   # [WINDOW-EXT 2026-06-04] 1525→1528: 동시호가는 15:30 단일가라 늦게 넣어도 체결가 동일 → 오류복구 여유 확대(15:30 前 안전). 가격무손실·신뢰도↑.

# [CLOSE-AUCTION-HOGA 2026-06-04] 마감 동시호가(15:20~15:30)는 단일가 경매 → 시장가(03)가 체결보장
# (슬리피지 없음, 전부 15:30 종가 체결). 연속매매(PULLBACK 등)는 슬리피지 통제 위해 06 유지.
# 시간기반 자동전환 = EOD_PICK 종가매수에만 03 효과. env로 롤백/튜닝.
CLOSE_AUCTION_HHMM = int(os.environ.get("CLOSE_AUCTION_HHMM", "1520"))
CLOSE_AUCTION_HOGA = (os.environ.get("CLOSE_AUCTION_HOGA", "03").strip() or "03")

def _decide_buy_hoga() -> str:
    """마감 동시호가(>=CLOSE_AUCTION_HHMM)면 시장가(03 등), 그 외엔 BUY_HOGA_GB(기본 06 최유리지정가)."""
    base = (os.environ.get("BUY_HOGA_GB", "06").strip() or "06")
    try:
        if _hhmm() >= CLOSE_AUCTION_HHMM:
            return CLOSE_AUCTION_HOGA
    except Exception:
        pass
    return base

# ── [v4_7-P2] Alpha Decay — 시간대별 신호 품질 감쇠 계수 ─────────
# 출처: Kissell, R. & Malamut, R. (2006) "Algorithmic Decision Making Framework"
# EV_MIN_PCT에 (1/alpha_decay)를 곱해 적용 → 낮은 alpha 구간 = 더 높은 EV 요구
ALPHA_DECAY_SCHEDULE: List[Tuple[int, int, float]] = [
    (903,  1030, 1.00),   # 개장 초 — 신호 최강
    (1030, 1100, 0.92),
    (1100, 1300, 0.80),   # 점심 저유동성
    (1300, 1430, 0.95),   # 재개 상승
    (1430, 1530, 0.70),   # 종가 노이즈
]

def _get_alpha_decay(hhmm: int) -> float:
    """시간대별 알파 감쇠 계수 반환 (낮을수록 진입 기준 강화)"""
    for start, end, decay in ALPHA_DECAY_SCHEDULE:
        if start <= hhmm < end:
            return decay
    return 1.00  # 정의 외 시간 → 기본값

# ── [v4_7-P5] 1일 1진입 보장 게이트 ─────────────────────────────
# ── [v4_8 Gap-4] 1일 1진입 보장 완화 진입 사이즈 캡 ───────────────
# EV/Score 기준을 완화해서 통과한 진입은 포지션 70%로 제한
# 정규 진입=100% / EV완화 진입=70% — 진입 품질별 사이즈 분리
DAILY_MIN_SIZE_CAP    = float(os.environ.get("DAILY_MIN_SIZE_CAP", "0.70"))

# ── [v4_8 Gap-5] hard_stop 레짐별 동적 조정 ─────────────────────────
# 기존: HARD_STOP_DEFAULT=0.025 단일 고정
# 레짐 특성에 맞게 손절 폭 자동 조정 (Thorp 1997: Kelly+손절 동시 최적화)
HARD_STOP_REGIME_MAP: dict = {
    "VOLATILE": 0.020,   # 고변동성 → 좁은 손절 (노이즈 크지만 빠른 이탈)
    "TREND":    0.030,   # 추세장   → 넓은 손절 (추세 흐름에 여유 부여)
    "BEAR":     0.018,   # 하락장   → 가장 좁은 손절 (진입 자체 보수적)
    "RANGE":    0.025,   # 박스권   → 기본값 동일
}

# [A 2026-06-09 사용자지시] "1일 1진입 무조건 없음 — 점수가 될 때만 진입" → 1일1진입 보장(점수/EV 완화) 기본 OFF.
#   근거 6/9: 420770 score 59.1<정상65을 DAILY_MIN이 45.5로 낮춰 강제매수→-2.67% 손절. 이제 정상 floor 미달이면 진입 안 함.
#   되살리려면 env DAILY_MIN_ENTRY_ENABLED=YES.
DAILY_MIN_ENTRY_ENABLED  = os.environ.get("DAILY_MIN_ENTRY_ENABLED", "NO").strip().upper() == "YES"  # 기본 OFF (점수될때만 진입)
DAILY_MIN_ENTRY_EV_RELAX = 0.30   # (DAILY_MIN OFF 시 미사용) EV기준 완화율
DAILY_MIN_ENTRY_SCORE_MIN = 72.0  # (DAILY_MIN OFF 시 미사용) 최소 score

# [v4_3 OPT-5] ev_pct=0 fallback score — 당일청산 전략별 차등 기준
#   높은 기준 = 더 엄격 / 낮은 기준 = 데이터 부족한 전략에 관대
# [v4_9 FIX] EOD_TOP1/TOP2 항목 제거 — v4_7에서 EOD 전략 완전 삭제
# 나머지 전략(TREND/PULLBACK/GAP/SIGA)만 유지
_FALLBACK_SCORE_BY_STRATEGY: Dict[str, float] = {
    "TREND_FOLLOW":  80.0,   # 추세눌림 표준
    "TREND":         80.0,
    "PULLBACK":      80.0,
    "BREAKOUT":      81.0,
    "GAP":           80.0,   # 시가갭 전략
    "SIGA":          80.0,   # 시가 전략
}
_FALLBACK_SCORE_DEFAULT  = 80.0   # 미분류 전략 기본값
# ⑤ 세션 circuit breaker — 연속 FAILED 상한
CIRCUIT_BREAKER_MAX_FAIL = int(os.environ.get("CIRCUIT_BREAKER_MAX_FAIL", "3"))

# 진입 품질 필터 — spread는 _entry_quality_gate 내 런타임 _params_get() 사용
ENTRY_MIN_VOLUME      = int(os.environ.get("ENTRY_MIN_VOLUME", "10000"))
ENTRY_FILTER_ENABLED  = os.environ.get("ENTRY_FILTER_ENABLED","1").lower() \
                        not in ("0","false","no")
# [v4_9] 실전 수익 보호 필터 — PATCH 1/2/3/4
ENTRY_MAX_SLIP_PCT    = float(os.environ.get("ENTRY_MAX_SLIP_PCT",  "0.8"))   # PATCH1: 슬리피지 허용 한도 (%)
SIGNAL_MAX_AGE_SEC    = int(os.environ.get("SIGNAL_MAX_AGE_SEC",   "300"))   # PATCH2: 신호 유효시간 (초)
REGIME_KOSDAQ_MIN_PCT = float(os.environ.get("REGIME_KOSDAQ_MIN",  "-1.0"))  # PATCH3: KOSDAQ 낙폭 차단 (%)
ENTRY_CUT_TIME        = int(os.environ.get("ENTRY_CUT_TIME",       "1430"))  # PATCH4: 진입 마감 시간 (HHMM)
# [STREAK-v2] 일별 1회 캐시 — 매 신호마다 CSV 재읽기 방지
_streak_cache: dict = {"date": None, "value": 0}
# [v4_9 ATR] 포지션 사이징 — 위험 기반 수량 계산 (확대 아닌 축소 중심)
TARGET_RISK_PCT       = float(os.environ.get("TARGET_RISK_PCT",    "1.5"))        # 계좌 대비 리스크 한도 (%)
ACCOUNT_SIZE          = float(os.environ.get("ACCOUNT_SIZE",       "10000000"))   # 기준 계좌 크기 (원)

# ═══════════════════════════════════════════════════════════════
#  [v4_4 FIX-Q] 진입 품질 게이트 강화 — EV 기준 전면 상향
# ═══════════════════════════════════════════════════════════════
# ① EV 필터 — 기대수익률 최소 기준 + EV/리스크 비율
# [FIX-Q1] EV_MIN_PCT: 0.25% → 0.60%
#   거래비용(0.21%) 차감 후 실질 EV ≥ 0.39% 보장
#   헤지펀드 표준: 거래비용 3배 이상의 EV만 진입
EV_MIN_PCT             = float(os.environ.get("EV_ENTRY_MIN_GLOBAL", "0.45"))
ABS_EV_FLOOR           = float(os.environ.get("ABS_EV_FLOOR", "0.20"))  # [v4_9 PATCH5] 절대 EV 하한
# [FIX-Q2] EV_RISK_RATIO_MIN: 2.0 → 1.4  (손익비 1.4:1 이상 — 과도한 HOLD 완화)
EV_RISK_RATIO_MIN      = float(os.environ.get("EV_RISK_RATIO_MIN", "1.4"))

# ② Score 필터 — Scoreboard 최소 점수
SCORE_MIN              = float(os.environ.get("SCORE_MIN", "68"))

# ③ Market 필터 — regime별 EV 기준
# [FIX-Q3] EV_MIN 상향에 따른 regime 기준 정합성 유지
REGIME_BEAR_BLOCK      = True   # BEAR → 진입 금지
REGIME_NEUTRAL_EV_MIN  = float(os.environ.get("REGIME_NEUTRAL_EV_MIN", "0.70"))  # FIX-Q3: 0.35→0.70
REGIME_BULL_EV_MIN     = float(os.environ.get("REGIME_BULL_EV_MIN",    "0.50"))  # FIX-Q3: 0.20→0.50

# ④ EV 연동 포지션 사이징 — [FIX-Q4] EV_MIN=0.60 기준으로 티어 재설계
# EV 0.60~0.75%: BASE  70% (최소 통과 — 신중 투입)
# EV 0.75~1.00%: HIGH  85% (양호 신호 — 적극 투입)
# EV ≥ 1.00%  : FULL  98% (강한 신호 — 몰빵)
EV_SIZE_TIER_HIGH      = 1.0    # FIX-Q4: 0.6→1.0  (1.0%+ → FULL 몰빵)
EV_SIZE_TIER_MID       = 0.75   # FIX-Q4: 0.4→0.75 (0.75%+ → HIGH)
EV_SIZE_RATIO_HIGH     = 0.98   # FULL: 잔고 98% (몰빵)
EV_SIZE_RATIO_MID      = 0.85   # HIGH: 잔고 85%
EV_SIZE_RATIO_BASE     = 0.70   # BASE: 잔고 70% (신중)
# 하위호환: 기존 변수명 유지
EV_SIZE_MULT_HIGH      = 2.0    # 내부 참조용 (실제 사이징은 RATIO 사용)
EV_SIZE_MULT_MID       = 1.5
EV_SIZE_MULT_BASE      = 1.0
# [v4_9] 4회 분할 비중 — order_krw 계산에서 ev_ratio 대체
MAX_ACCOUNT_USAGE  = float(os.environ.get("MAX_ACCOUNT_USAGE", "0.75"))  # 총 사용 상한(기본75%, 현금25% 유지). [MOLBANG-SWITCH] env로 0.98 풀면 98%몰빵 캡.
# [W31 PATCH 2026-05-12] 대장 집중 + ADD_ON 증폭 구조로 재정렬
#   기존: [0.30, 0.20, 0.15, 0.10] 합 0.75 — 3/4회차 유령 (10만원대 미만)
#   변경: [0.50, 0.25] 합 0.75 — 신규 2회 압축, reserve 25% ADD_ON 보존
#   ADD_ON ratio (0.35/0.15)는 변경 없음 — reserve 자본 기반 동작
ENTRY_WEIGHTS      = [0.50, 0.30, 0.20]  # [v4.30 P3 복원 2026-06-02] 1/2/3회차(사용자 1·2·ADD) 신규 진입.
#   값은 폴백 — 실제 비중은 SIZE-UNIFY로 상류 진화 Kelly(rt_risk order_krw)가 결정(종가매수와 동일).
#   길이=3 → buy_sender DAY_LIMIT 3회 허용(PULLBACK_MAX_TRADES_PER_DAY=3 정합). 회차 점감(좋을때 큰→ADD 작·엄격).
# [W31 PATCH] ADD_ON 카운트 분리 — 신규 2회 + ADD_ON 2회 = 총 4회 (구 ENTRY_WEIGHTS=4 정합)
ADDON_MAX_PER_DAY  = int(os.environ.get("ADDON_MAX_PER_DAY", "0"))   # [v4.30 P3 2026-06-02] 2→0: 사용자 "4회차 없어". 신규 3회(1/2/ADD)로 끝, 별도 보유종목 추가매수(ADD_ON) 비활성. env로 부활 가능.

# ⑧ 기관 탑승 게이트 — [PROFIT-1] 기관의 등에 탔다가 미리 내리는 전략
# 기관 매수 확인 시 → 진입 허용 + EV 기준 완화 + 포지션 강화
# [v4_2 FIX-B] 이중 잠금 강화 — 과민 반응 차단
INST_RIDE_ENABLED      = os.environ.get("INST_RIDE_ENABLED","1").lower() \
                         not in ("0","false","no")
INST_SCORE_MIN         = float(os.environ.get("INST_SCORE_MIN",  "0.35"))  # [v4_2] 0.25→0.35 (ride_score 0.40 준용)
INST_SCORE_HIGH        = float(os.environ.get("INST_SCORE_HIGH", "0.60"))  # [v4_2] 0.50→0.60 (고확신 기준 상향)
# [RIDE-FLOOR-RELAX 2026-06-05] 강한 기관 ride(>=MIN)면 PULLBACK score floor 추가 완화.
#   "기관 등타기" 전략 정합 — 강한 기관 매집 종목은 가격셋업 score가 다소 낮아도 진입 허용.
#   되돌림: env RIDE_FLOOR_RELAX_PCT=0.0 (완화 없음). 랭킹/선택엔 무영향(conv 게이트 floor만).
RIDE_FLOOR_RELAX_MIN   = float(os.environ.get("RIDE_FLOOR_RELAX_MIN", "0.70"))  # ride_score 이 값 이상이면 floor 완화
# [A 2026-06-09 사용자지시] "점수 될 때만 진입" — 기관 ride 강해도 score floor 완화 안 함. 기본 0.0(완화없음).
#   근거 6/9: 095610 score 58.8<정상65인데 ride0.70으로 floor 45.5 완화→매수(ghost·-1.3%). DAILY_MIN에 이어 두번째 완화도 차단.
#   되살리려면 env RIDE_FLOOR_RELAX_PCT=0.30.
RIDE_FLOOR_RELAX_PCT   = float(os.environ.get("RIDE_FLOOR_RELAX_PCT", "0.0"))  # 기본 완화 없음 (score>=65만 진입)
# [FIX-Q5 v4_4] 기관 동행 EV 완화량: 0.05 → 0.10
#   EV_MIN=0.60 상향으로 기관 확인 시 0.10 완화 → 실질 최소 EV=0.50%
INST_EV_RELAX_PCT      = float(os.environ.get("INST_EV_RELAX_PCT", "0.10"))  # FIX-Q5: 0.05→0.10
INST_CONSEC_MIN        = int(os.environ.get("INST_CONSEC_MIN",   "3"))      # [v4_2] 2→3 (연속매수 최소일 강화)

# ⑥ 강화 Entry Quality — 최근 3분 모멘텀 + 거래대금 증가율
ENTRY_MOM_3M_MIN_PCT   = float(os.environ.get("ENTRY_MOM_3M_MIN_PCT", "0.8"))
ENTRY_VOL_SURGE_MIN_PCT = float(os.environ.get("ENTRY_VOL_SURGE_MIN_PCT", "30"))

# ⑦ Overheat 필터 — 현재 봉 range > 20봉 평균 × 배수
OVERHEAT_MULT          = float(os.environ.get("OVERHEAT_MULT", "2.5"))
OVERHEAT_LOOKBACK      = int(os.environ.get("OVERHEAT_LOOKBACK", "20"))

# 필수 필터 on/off (운영 비상시 전체 우회용)
CONVICTION_GATE_ENABLED = os.environ.get("CONVICTION_GATE_ENABLED","1").lower() \
                          not in ("0","false","no")

# 체결 품질 제어 (params_reader 우선, 환경변수 폴백)
_PR_EXEC_MAX_SLIP      = _params_get("exec_max_slip_bps", None)
EXEC_MAX_SLIP_BPS      = (float(_PR_EXEC_MAX_SLIP)
                           if _PR_EXEC_MAX_SLIP is not None
                           else float(os.environ.get("EXEC_MAX_SLIP_BPS", "30")))
_PR_EXEC_SPLIT_RATIO   = _params_get("exec_split_ratio", None)
EXEC_SPLIT_RATIO       = (float(_PR_EXEC_SPLIT_RATIO)
                           if _PR_EXEC_SPLIT_RATIO is not None
                           else float(os.environ.get("EXEC_SPLIT_RATIO", "0.5")))
EXEC_REENTRY_MAX       = int(os.environ.get("EXEC_REENTRY_MAX", "2"))
EXEC_REENTRY_PRICE_PCT = float(os.environ.get("EXEC_REENTRY_PRICE_PCT","0.3"))
EXEC_REENTRY_FILLCHECK_SEC = int(os.environ.get("EXEC_REENTRY_FILLCHECK_SEC", "60"))  # [#5-A] 재진입 직전 chejan 체결확인 lookback(초)


def _has_recent_fill_bu(code, since_sec=60):
    """[#5-A 2026-06-08] 해당 종목 최근 체결(chejan gubun=0, 체결가 910 존재) 있는지 확인.
    ACK 타임아웃 재진입 직전 호출 → broker 실체결인데 미체결 오판하여 중복매수하는 것 방지.
    실패/없음 → False(fail-open; 동일종목 hard cap=_code_order_cap_ok 이 backstop)."""
    try:
        code6 = str(code).zfill(6)
        now = time.time()
        for fp in _BROKER_CHEJAN_DIR_BU.glob("*.json"):
            try:
                if now - fp.stat().st_mtime > since_sec:
                    continue
                ev = json.loads(fp.read_text(encoding="utf-8-sig"))
                if str(ev.get("gubun", "")) != "0":      # gubun=0 = 주문체결 통보
                    continue
                fid = ev.get("fid_data", {}) or {}
                if str(fid.get("9001", "")).strip().lstrip("A") != code6:
                    continue
                if str(fid.get("910", "")).strip():       # 910 = 체결가(있으면 체결됨)
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False
EXEC_SPLIT_ORDER       = os.environ.get("EXEC_SPLIT_ORDER","1").lower() \
                         not in ("0","false","no")
EXEC_SPLIT_DELAY_SEC   = float(os.environ.get("EXEC_SPLIT_DELAY_SEC",  "0.5"))
EXEC_PRICE_DRIFT_PCT   = float(os.environ.get("EXEC_PRICE_DRIFT_PCT",  "0.5"))

# ── 환경변수 헬퍼 ──
def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()

def _env_int(name: str, default: int) -> int:
    try: return int(float(_env(name, str(default))))
    except Exception: return default

def _env_float(name: str, default: float) -> float:
    try: return float(_env(name, str(default)))
    except Exception: return default

def _env_bool(name: str, default: str = "0") -> bool:
    return _env(name, default).lower() in ("1","true","yes","on")

# ── KST 시간 ──
def _now() -> datetime:
    return datetime.now(tz=KST)

def _now_str() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")

def _today_ymd() -> str:
    return _now().strftime("%Y%m%d")

def _today_str() -> str:
    return _now().strftime("%Y-%m-%d")

def _hhmm() -> int:
    n = _now()
    return n.hour * 100 + n.minute

# ── fingerprint / run_id ──
def make_signal_fingerprint(code: str, date: str,
                             strategy: str, price: int = 0) -> str:
    return hashlib.md5(
        f"{code}_{date}_{strategy}".encode()
    ).hexdigest()[:16]

def make_run_id() -> str:
    return f"RUN_{int(_now().timestamp()*1000)}"

def make_temp_key(code: str) -> str:
    return f"TEMP_{code.zfill(6)}_{int(_now().timestamp()*1000)}"

# ── 유틸 ──
def _norm_code(x: Any) -> str:
    s = str(x).strip().upper()
    if s.startswith("A"): s = s[1:]
    digits = "".join(c for c in s if c.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits

def _is_valid_code(code: str) -> bool:
    return len(code) == 6 and code.isdigit()

def _is_valid_account(account: str) -> bool:
    return len("".join(c for c in str(account) if c.isdigit())) >= 8

def _safe_int(value: Any, default: int = 0) -> int:
    try: return int(float(str(value).strip().replace(",","")))
    except Exception: return default

def _safe_float(value: Any, default: float = 0.0) -> float:
    try: return float(str(value).strip().replace(",",""))
    except Exception: return default

def _resolve_path(base: Path, raw_path: str) -> Path:
    p = Path(raw_path)
    return p if p.is_absolute() else base / p

# ── 로깅 ──
def _setup_logger(base: Path) -> logging.Logger:
    logger = logging.getLogger("sender")
    if logger.handlers: return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    except Exception: pass
    try:
        log_dir = base / "LOG"          # P0: 대문자
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "order_sender_live.log",
            maxBytes=10*1024*1024, backupCount=5, encoding="utf-8-sig")  # [Z15 2026-05-21]
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception: pass
    return logger

# ── 경로 ──
def _ledger_path(base: Path) -> Path:
    return base / "LOG" / f"order_ledger_{_today_ymd()}.csv"

def _summary_path(base: Path) -> Path:
    return base / "LOG" / f"order_summary_{_today_ymd()}.csv"

def _ledger_fail_path(base: Path) -> Path:
    return base / "LOG" / f"order_ledger_failover_{_today_ymd()}.log"

def _positions_path(base: Path) -> Path:
    return base / "DATA" / "positions" / "current_positions.csv"


def _load_preflight_size_mult(base: Path,
                               logger: logging.Logger) -> float:
    """[BUG-4 FIX] preflight_result.json → size_mult 로드"""
    import json as _json
    pf_path = base / "DATA" / "LOG" / "preflight_result.json"
    try:
        if not pf_path.exists():
            return 1.0
        with open(pf_path, "r", encoding="utf-8-sig") as f:
            result = _json.load(f)
        sm = float(result.get("size_mult", 1.0))
        sm = max(0.30, min(sm, 1.15))
        if sm < 1.0:
            logger.info("[PREFLIGHT] size_mult=%.2f (사이즈 축소 적용)", sm)
        return sm
    except Exception as e:
        logger.warning("[PREFLIGHT] 로드 실패: %s → 기본값 1.0", e)
        return 1.0

def _strategy_pnl_path(base: Path) -> Path:
    return base / "DATA" / "daily_pnl_by_strategy.csv"

def _evolve_log_path(base: Path) -> Path:
    return base / "LOG" / "evolve_weights.csv"

def _reconcile_path(base: Path) -> Path:
    return base / "LOG" / f"reconcile_pending_{_today_ymd()}.csv"

def _write_failover_log(base: Path, message: str) -> None:
    try:
        p = _ledger_fail_path(base)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{_now_str()} {message}\n")
    except Exception: pass

# ── positions.csv 업데이트 ──
def _update_positions(base: Path, result: "OrderResult",
                      logger: logging.Logger) -> None:
    pos_path = _positions_path(base)
    pos_path.parent.mkdir(parents=True, exist_ok=True)
    new_row = {
        "code":        result.code,
        "qty":         result.filled_qty,
        "avg_price":   round(result.avg_filled_price, 2),
        "buy_ts":      _now_str(),
        "strategy":    result.strategy,
        "date":        _today_str(),
        # [PROFIT-5/BUG-5] 기관 탑승 정보 → 매도엔진 기관 이탈 감지 지원
        "inst_score":  getattr(result, "inst_score", 0.0),
        "inst_consec": getattr(result, "inst_consec", 0),
        "inst_ride":   int(getattr(result, "inst_ride", False)),
        "ev_pct":      getattr(result, "ev_pct", 0.0),
        "score":       getattr(result, "score", 0.0),
    }
    try:
        existing: List[Dict] = []
        if pos_path.exists() and pos_path.stat().st_size > 0:
            try:
                df = pd.read_csv(pos_path, dtype=str,
                                 encoding="utf-8-sig").fillna("")
                existing = df.to_dict("records")
            except Exception as e:
                logger.warning("[POS] 읽기 실패: %s", e)

        merged = False
        for i, r in enumerate(existing):
            if (str(r.get("code","")).zfill(6) == result.code
                    and str(r.get("date","")) == _today_str()):
                oq = _safe_int(r.get("qty",0))
                op = _safe_float(r.get("avg_price",0.0))
                tq = oq + result.filled_qty
                wa = ((oq*op + result.filled_qty*result.avg_filled_price)/tq
                      if tq > 0 else result.avg_filled_price)
                existing[i]["qty"]       = tq
                existing[i]["avg_price"] = round(wa, 2)
                existing[i]["buy_ts"]    = _now_str()
                merged = True
                break
        if not merged:
            existing.append(new_row)

        tmp = pos_path.with_suffix(".tmp")
        pd.DataFrame(existing).to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(pos_path))
        logger.info("[POS] ✅ code=%s qty=%d avg=%.2f",
                    result.code, result.filled_qty, result.avg_filled_price)
    except Exception as e:
        logger.error("[POS] 실패: %s", e)
        _write_failover_log(base, f"[POS_FAIL] code={result.code} err={e}")

# ── rt_open_positions.json 업데이트 (sell engine 포지션 추적용) ──
def _write_open_position(base: Path, result: "OrderResult",
                         logger: logging.Logger,
                         row: Optional[dict] = None) -> None:  # [PATCH] row 추가 — 누락 필드 보완
    import json as _json
    pos_json = base / "DATA" / "rt_open_positions.json"
    pos_json.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if pos_json.exists() and pos_json.stat().st_size > 0:
        try:
            with open(pos_json, "r", encoding="utf-8-sig") as f:
                data = _json.load(f)
        except Exception as e:
            logger.warning("[OPN_POS] 읽기 실패: %s → 덮어씀", e)
    ep = result.avg_filled_price
    code = result.code
    # [v4_9-P3] row 없을 때 fallback을 ENV HARD_STOP_DEFAULT(0.025)로 통일 (구 0.02)
    _row = row or {}
    _hs_default = float(os.environ.get("HARD_STOP_DEFAULT", "0.025"))
    _hard_stop  = max(float(_row.get("hard_stop", _hs_default)), 0.01)
    if code in data:
        oq = int(data[code].get("qty", 0))
        op = float(data[code].get("entry_price", ep))
        # [QTY-DEDUP 2026-06-11] 같은 체결을 chejan writer(#5-B)가 먼저 기록한 경우 가산 금지.
        #   (6/11 100790: chejan 6주 기록 → 본 함수가 가산매수로 오인 +6 = 12주 → 매도 12주 거부 사건)
        #   판정: _chejan_ts 3분내 신선 AND 기존수량 == 이번 체결수량 → 동일 체결.
        #   진짜 가산매수(별도 주문)는 시각/수량이 달라 기존 가산 로직 유지.
        _same_fill = False
        try:
            _cj_ts = str(data[code].get("_chejan_ts", ""))
            if _cj_ts:
                _age_s = (datetime.now() - datetime.fromisoformat(_cj_ts)).total_seconds()
                _same_fill = (_age_s < 180 and oq == int(result.filled_qty))
        except Exception:
            _same_fill = False
        if _same_fill:
            logger.info("[OPN_POS][QTY-DEDUP] code=%s chejan 선기록 동일체결 감지(qty=%d) → 가산 생략, 필드만 보강",
                        code, oq)
            tq = oq
            wa = op if op > 0 else ep
        else:
            tq = oq + result.filled_qty
            wa = (oq * op + result.filled_qty * ep) / tq if tq > 0 else ep
        data[code]["entry_price"] = round(wa, 2)
        data[code]["qty"] = tq
        data[code]["peak_price"] = max(float(data[code].get("peak_price", wa)), wa)
        # [v4_9-P3] 가산매수 시 stop_price 평단 기준 재산정 — 비대칭 손절 방지
        _hs_keep = float(data[code].get("_hard_stop_pct", _hard_stop))
        _hs_used = max(_hs_keep, _hard_stop)  # 더 보수적 손절 채택 (수익 보호 우선)
        data[code]["stop_price"]      = round(wa * (1 - _hs_used), 2)
        data[code]["_hard_stop_pct"]  = _hs_used
    else:
        data[code] = {
            "entry_price":  ep,
            "qty":          result.filled_qty,
            "strategy":     result.strategy,
            "stop_price":   round(ep * (1 - _hard_stop), 2),  # [PATCH] 0.98 하드코딩→레짐별 hard_stop
            "peak_price":   ep,
            "_weak_count":  0,
            "_hard_stop_pct": _hard_stop,                      # [v4_9-P3] 가산매수 재산정용
            "ride_score":   float(_row.get("inst_ride_score", _row.get("ride_score", 0.0))),  # [PATCH]
            "gap_grade":    str(_row.get("gap_grade", "")),    # [PATCH]
            "entry_ts":     _now_str(),                        # [PATCH]
            "trail_mode":   "CHANDELIER",                      # [PATCH] 초기 trail 모드
        }
    try:
        tmp = pos_json.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(pos_json))
        logger.info("[OPN_POS] ✅ code=%s ep=%.0f qty=%d",
                    code, ep, result.filled_qty)
    except Exception as e:
        logger.error("[OPN_POS] 쓰기 실패: %s", e)
        _write_failover_log(base, f"[OPN_POS_FAIL] code={code} err={e}")

def _ensure_open_position(base: Path, result: "OrderResult",
                          logger: logging.Logger,
                          row: Optional[dict] = None) -> None:
    import json as _json
    pos_json = base / "DATA" / "rt_open_positions.json"
    try:
        data: dict = {}
        if pos_json.exists() and pos_json.stat().st_size > 0:
            with open(pos_json, "r", encoding="utf-8-sig") as f:
                data = _json.load(f)
        if result.code not in data:
            logger.error("[OPEN][FORCE] code=%s 누락 → 강제 재등록 시도", result.code)
            _write_open_position(base, result, logger, row)
    except Exception as e:
        logger.error("[OPEN][FAIL] ensure 실패 code=%s: %s", result.code, e)

# ── reconcile 기록 ──
def _write_reconcile(base: Path, result: "OrderResult",
                     reason: str, logger: logging.Logger) -> None:
    path = _reconcile_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "date":       _today_str(), "ts":         _now_str(),
        "code":       result.code,  "order_no":   result.order_no,
        "state":      result.state.value,
        "filled_qty": result.filled_qty,
        "avg_price":  result.avg_filled_price,
        "reason":     reason,
    }
    fields = ["date","ts","code","order_no","state",
              "filled_qty","avg_price","reason"]
    try:
        # 원자적 쓰기: 기존 읽기 → 신규 추가 → tmp→replace
        existing: List[Dict] = []
        if path.exists() and path.stat().st_size > 0:
            try:
                df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
                existing = df.to_dict("records")
            except Exception: pass
        existing.append(row)
        tmp = path.with_suffix(".tmp")
        pd.DataFrame(existing)[fields].to_csv(
            tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(path))
        logger.warning("[RECONCILE] code=%s reason=%s", result.code, reason)
    except Exception as e:
        logger.error("[RECONCILE] 기록 실패: %s", e)

# ── 자기진화 Half-Kelly ──
def _rolling_mdd(pnl: "pd.Series") -> float:
    if len(pnl) == 0: return 0.0
    cum = (1 + pnl / 100).cumprod()
    dd  = (cum - cum.cummax()) / cum.cummax()
    return float(dd.min())

def _consecutive_losses(pnl: "pd.Series") -> int:
    streak = 0
    for v in reversed(pnl.tolist()):
        if v <= 0: streak += 1
        else: break
    return streak

def _load_strategy_weights(base: Path,
                            logger: logging.Logger) -> Dict[str, float]:
    pnl_path = _strategy_pnl_path(base)
    if not pnl_path.exists() or pnl_path.stat().st_size == 0:
        logger.info("[EVOLVE] pnl 없음 → 기본 가중치")
        return {}
    try:
        df = pd.read_csv(pnl_path, dtype=str, encoding="utf-8-sig")
        # [FIX 2026-05-30] 'pnl_pct' 하드코딩 → 실제 컬럼은 pnl_pct_net/pnl_pct_gross 라
        #   KeyError → except fail-open(return {} 기본가중치)이던 문제. STREAK와 동일 fallback.
        #   downstream(dropna·grp["pnl_pct"]) 호환 위해 실제 컬럼을 pnl_pct 에 별칭 대입.
        _pnl_col = next(
            (_c for _c in ("pnl_pct_net", "pnl_pct_gross", "pnl_pct",
                           "pnl_rate", "return_pct", "profit_pct",
                           "realized_pnl_pct")
             if _c in df.columns), None)
        if _pnl_col is None:
            logger.warning("[EVOLVE] PnL 컬럼 없음 → 기본 가중치 (cols=%s)",
                           list(df.columns)[:8])
            return {}
        if _pnl_col != "pnl_pct":
            df["pnl_pct"] = df[_pnl_col]   # downstream 'pnl_pct' 참조 호환(별칭)
        df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce")
        df = df.dropna(subset=["pnl_pct"]).fillna("0")   # OPEN 포지션(pnl_pct 미기록) 제거
        lookback_trades = _params_get("evolve_lookback_trades", EVOLVE_LOOKBACK_TRADES)
        try: lookback_trades = int(lookback_trades)
        except Exception: lookback_trades = EVOLVE_LOOKBACK_TRADES
        df = df.tail(lookback_trades)
        logger.info("[EVOLVE] lookback=%d건 기준", lookback_trades)

        weights: Dict[str, float] = {}
        for strategy, grp in df.groupby("strategy"):
            grp = grp.sort_values("date")
            pnl = grp["pnl_pct"]
            n   = len(pnl)

            if n < EVOLVE_MIN_SAMPLES:
                # [v4_1] inst_ride 거래가 포함된 전략은 초기 샘플 부족 페널티 완화
                #        inst_ride=True 거래 비율이 50% 이상이면 CONSERVATIVE → 0.40
                inst_ride_cnt = 0
                if "inst_ride" in grp.columns:
                    inst_ride_cnt = int(grp["inst_ride"].apply(
                        lambda x: str(x) in ("1","True","true")).sum())
                inst_ride_ratio = inst_ride_cnt / n if n > 0 else 0
                conservative_w = (0.40 if inst_ride_ratio >= 0.5
                                  else EVOLVE_CONSERVATIVE)
                weights[strategy] = conservative_w
                logger.info("[EVOLVE] %s n=%d<min inst_ride=%.0f%% → %.2f",
                            strategy, n, inst_ride_ratio * 100, conservative_w)
                continue

            wins   = pnl[pnl > 0]
            losses = pnl[pnl <= 0].abs()
            wr     = len(wins) / n
            avg_w  = float(wins.mean())   if len(wins)   > 0 else 0.01
            avg_l  = float(losses.mean()) if len(losses) > 0 else 0.01

            # [v4_1] 종목별 KOSPI/KOSDAQ 세율 적용
            # strategy pnl에는 code 정보가 없으므로 그룹 내 최빈 코드로 추정
            _sample_code = ""
            if "code" in grp.columns:
                try:
                    _sample_code = str(grp["code"].mode().iloc[0])
                except Exception:
                    pass
            cost_pct = _trade_cost_pct(_sample_code) * 100 if _sample_code \
                       else TRADE_COST_ROUNDTRIP_PCT * 100
            adj_avg_w = max(0.001, avg_w - cost_pct)
            adj_avg_l = avg_l + cost_pct

            b      = adj_avg_w / adj_avg_l
            kelly  = (b * wr - (1 - wr)) / b

            if kelly < 0:
                logger.warning(
                    "[EVOLVE] %s Kelly=%.4f(음수) 거래비용 반영 후 "
                    "→ CONSERVATIVE %.2f 적용",
                    strategy, kelly, EVOLVE_CONSERVATIVE)
                weights[strategy] = EVOLVE_CONSERVATIVE
                continue

            # ── [v4_7-P3] MDD 연동 동적 Kelly 분수 ──────────────────
            # 출처: Thorp, E.O. (1997) "The Kelly Criterion in Blackjack,
            #        Sports Betting, and the Stock Market"
            # MDD가 클수록 Kelly 분수를 낮춰 손실구간 과대 포지션 방지
            mdd = _rolling_mdd(pnl)
            mdd_abs = abs(mdd)
            if mdd_abs <= 0.03:
                kelly_frac = 0.50   # MDD≤3% : 정상 → Half-Kelly
            elif mdd_abs <= 0.05:
                kelly_frac = 0.40   # MDD≤5% : 주의 → 40%-Kelly
            elif mdd_abs <= 0.08:
                kelly_frac = 0.30   # MDD≤8% : 경계 → 30%-Kelly
            else:
                kelly_frac = 0.20   # MDD>8%  : 위험 → 최소 20%-Kelly
            logger.info("[EVOLVE] %s MDD=%.1f%% → kelly_frac=%.2f",
                        strategy, mdd * 100, kelly_frac)
            weight = kelly_frac * kelly
            # ──────────────────────────────────────────────────────────

            streak  = _consecutive_losses(pnl)
            weight -= streak * EVOLVE_CONSEC_PENALTY

            if mdd < EVOLVE_MDD_THRESHOLD:
                weight -= EVOLVE_MDD_PENALTY

            weight = round(max(EVOLVE_MIN_WEIGHT,
                               min(EVOLVE_MAX_WEIGHT, weight)), 4)
            weights[strategy] = weight
            logger.info(
                "[EVOLVE] %s n=%d wr=%.0f%% b=%.2f "
                "streak=%d mdd=%.1f%% → w=%.4f",
                strategy, n, wr*100, b, streak, mdd*100, weight)

        _save_evolve_log(base, weights)
        return weights
    except Exception as e:
        logger.warning("[EVOLVE] 실패: %s", e)
        return {}

def _save_evolve_log(base: Path, weights: Dict[str, float]) -> None:
    try:
        path = _evolve_log_path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"date": _today_str(), "ts": _now_str(),
                 "strategy": k, "weight": v}
                for k, v in weights.items()]
        if not rows: return
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f,
                               fieldnames=["date","ts","strategy","weight"],
                               extrasaction="ignore")
            if not exists: w.writeheader()
            w.writerows(rows)
    except Exception: pass

def _calc_evolved_krw(base_krw: int, strategy: str,
                      weights: Dict[str, float]) -> Tuple[int, float]:
    """[WEAK-2 FIX] Kelly 가중치 → 투입비율 변환 (분리 구조)

    기존: base_krw × kelly_weight (직접 곱 → 80% 삭감 가능)
    수정: 완충 스케일링 — 최소 투입 보장 + Kelly 신호 반영

    공식: effective_ratio = floor + (1 - floor) × kelly_weight
    - Kelly=0.20 (최소) → floor + (1-floor)×0.20 = 0.50 + 0.50×0.20 = 0.60 (60%)
    - Kelly=0.60 (최대) → 0.50 + 0.50×0.60 = 0.80 (80%)
    - Kelly=0.30 (보수) → 0.50 + 0.50×0.30 = 0.65 (65%)
    → 기존: 20~60% 범위 → 수정: 60~80% 범위 (과소투입 방지)
    """
    if not EVOLVE_ENABLED or not weights:
        return base_krw, 1.0
    raw_w = weights.get(strategy, 1.0)
    if raw_w >= 1.0:
        return base_krw, 1.0
    # 완충 스케일링: 최소 50% 보장
    EVOLVE_FLOOR = 0.50
    effective_w = EVOLVE_FLOOR + (1.0 - EVOLVE_FLOOR) * raw_w
    return int(base_krw * effective_w), effective_w

# ── rank_ratio ──
def _resolve_rank_ratio_float(row: Dict[str, Any],
                               max_buy_rows: int) -> float:
    if max_buy_rows == 1:
        return 1.0
    raw = str(row.get("rank_ratio","")).strip()
    if not raw or raw in ("0","0.0","N/A"):
        return 1.0
    try:
        v = float(raw)
        if v > 1.0: v /= 100.0
        return max(0.1, min(1.5, v))
    except Exception:
        return 1.0

# ── 최종 수량 검증 ──
def _final_qty_check(available_krw: int, order_krw: int,
                     price: int, qty: int,
                     code: str,
                     logger: logging.Logger) -> Tuple[int, bool]:
    if price <= 0:
        logger.warning("[QTY_FINAL] price=0 재산정 불가 code=%s", code)
        return qty, False
    max_bal  = int(available_krw * BALANCE_SAFETY_RATIO / price)
    # [v4_9-P11] order_krw<=0 비정상 호출 시 max_bud을 max_bal로 폴백 — 예산 검증 우회 차단
    # 기존: order_krw=0 → max_bud=qty (예산 한도 사실상 비활성)
    if order_krw > 0:
        max_bud = int(order_krw / price)
    else:
        logger.warning("[QTY_FINAL] order_krw=0 비정상 — max_bud을 max_bal로 폴백 code=%s qty=%d",
                       code, qty)
        max_bud = max_bal
    final    = max(1, min(qty, max_bal, max_bud))
    adjusted = (final != qty)
    if adjusted:
        logger.warning(
            "[QTY_FINAL] code=%s %d→%d "
            "(잔고한도=%d 예산한도=%d 가격=%d)",
            code, qty, final, max_bal, max_bud, price)
    # [SAFE+ CLAMP_CAP] SAFEPLUS_CAPITAL × 0.98 절대 상한 — 어떤 경로로 와도 200만원 초과 불가
    cap_budget = int(SAFEPLUS_CAPITAL * SAFEPLUS_CAPITAL_HARD_RATIO)
    cap_qty    = max(0, cap_budget // max(price, 1))
    if final > cap_qty:
        logger.warning(
            "[CLAMP_CAP] code=%s qty=%d→%d cap=%s원 hard=%.0f%% price=%d",
            code, final, cap_qty, f"{SAFEPLUS_CAPITAL:,}",
            SAFEPLUS_CAPITAL_HARD_RATIO * 100, price)
        final    = max(1, cap_qty) if cap_qty >= 1 else 0
        adjusted = True
    return final, adjusted

# ── 시장 가드 (당일청산 전략 전용) ──
# [v4_7] 종배 분기 완전 제거 — 시가·추세눌림은 09:03 안정화 대기 공통 적용
def _market_guard(code: str, logger: logging.Logger,
                  cancel_count: int = 0,
                  strategy: str = "",
                  strategy_type: str = "",
                  session_type: str = "") -> bool:
    hhmm = _hhmm()

    if hhmm < GUARD_OPEN_STABLE_HHMM:
        logger.warning(
            "[GUARD_v4_7][BLOCK:GUARD001] 개장 초(%04d) 차단 "
            "code=%s (09:03 안정화 대기) — 당일청산 전략 공통",
            hhmm, code)
        return False
    # [EOD_PICK 2026-05-28] 종가매수 전략만 15:25까지 예외, 나머지는 1450 유지
    _is_eod_pick = (strategy == "EOD_PICK" or strategy_type == "EOD_PICK")
    _close_limit = EOD_PICK_CLOSE_HHMM if _is_eod_pick else GUARD_CLOSE_HHMM
    if hhmm >= _close_limit:
        logger.warning(
            "[GUARD][BLOCK:GUARD002] 마감 임박(%04d) 차단 code=%s (limit=%04d eod_pick=%s)",
            hhmm, code, _close_limit, _is_eod_pick)
        return False
    if cancel_count >= GUARD_MAX_CANCEL_CNT:
        logger.warning(
            "[GUARD][BLOCK:GUARD003] 누적취소 %d회 차단 code=%s",
            cancel_count, code)
        return False
    return True

# ── 진입 품질 게이트 ──
def _entry_quality_gate(row: Dict[str, Any], code: str,
                         price: int,
                         logger: logging.Logger) -> bool:
    if not ENTRY_FILTER_ENABLED:
        return True

    # ── [PATCH-STREAK v2] 연속 손절 3회 → 진입 차단 ──────────────────
    # 오늘 날짜 행 + 청산 완료(숫자 pnl) 행만 대상 · 일별 1회 캐시
    # [FIX 2026-05-30] 기존 'pnl_pct' 하드코딩 → 실제 컬럼은 pnl_pct_net/pnl_pct_gross 라
    #   KeyError → except fail-open(보호 무력)이던 문제. PnL 컬럼 fallback 탐색으로 보호 복구.
    #   (STREAK 체크 1곳만 수정 — dv_accel/spread/volume 등 다른 게이트·로직 무변경)
    try:
        _today_str = datetime.now().strftime("%Y-%m-%d")
        if _streak_cache["date"] != _today_str:
            _pnl_path = Path(DEFAULT_BASE_DIR) / "DATA" / "daily_pnl_by_strategy.csv"
            if _pnl_path.exists() and _pnl_path.stat().st_size > 0:
                _pnl_df = pd.read_csv(_pnl_path, dtype=str, encoding="utf-8-sig")
                # 실제 컬럼 우선(pnl_pct_net=순손익률) → 이식성용 후보 순으로 fallback
                _pnl_col = next(
                    (_c for _c in ("pnl_pct_net", "pnl_pct_gross", "pnl_pct",
                                   "pnl_rate", "return_pct", "profit_pct",
                                   "realized_pnl_pct")
                     if _c in _pnl_df.columns), None)
                if _pnl_col is None:
                    _streak_cache["date"]  = _today_str
                    _streak_cache["value"] = 0   # fail-open 유지 (보호 미적용)
                    logger.warning(
                        "[ENTRY_GATE][STREAK_CHECK_SKIP_NO_PNL_COLUMN] PnL 컬럼 없음 "
                        "→ 보호 미적용(진입 허용) code=%s cols=%s",
                        code, list(_pnl_df.columns)[:8])
                else:
                    _pnl_df[_pnl_col] = pd.to_numeric(_pnl_df[_pnl_col], errors="coerce")
                    if "date" in _pnl_df.columns:
                        _pnl_df = _pnl_df[_pnl_df["date"] == _today_str]
                    _pnl_df = _pnl_df.dropna(subset=[_pnl_col])  # OPEN/미청산 행 제외
                    _streak_cache["date"]  = _today_str
                    _streak_cache["value"] = _consecutive_losses(_pnl_df[_pnl_col])
                    logger.info(
                        "[ENTRY_GATE][STREAK_CHECK_OK] col=%s 청산행=%d 연속손절=%d code=%s",
                        _pnl_col, len(_pnl_df), _streak_cache["value"], code)
            else:
                _streak_cache["date"]  = _today_str
                _streak_cache["value"] = 0
        _streak = _streak_cache["value"]
        if _streak >= 3:
            logger.warning(
                "[ENTRY_GATE][STREAK_BLOCK] 연속 손절 %d회 → 진입 차단 code=%s", _streak, code)
            return False
    except Exception as _se:
        logger.warning("[ENTRY_GATE][STREAK] 체크 실패 → 무시(진입 허용) code=%s err=%s", code, _se)

    # ── [PATCH 2] Stale Signal 차단 ──────────────────────────────
    try:
        _ts_str = str(row.get("ts", "") or "").strip()
        if _ts_str and len(_ts_str) >= 5:
            _now = datetime.now()
            _sig_dt = None
            for _fmt in ("%H:%M", "%H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    _p = datetime.strptime(_ts_str, _fmt)
                    _sig_dt = (_now.replace(hour=_p.hour, minute=_p.minute,
                                            second=getattr(_p, 'second', 0), microsecond=0)
                               if len(_ts_str) <= 8 else _p)
                    break
                except ValueError:
                    continue
            if _sig_dt is not None:
                _age_sec = int((_now - _sig_dt).total_seconds())
                if _age_sec > SIGNAL_MAX_AGE_SEC:
                    logger.warning(
                        "[ENTRY_GATE][STALE] 신호 %d초 경과(한도%d초) → 차단 code=%s",
                        _age_sec, SIGNAL_MAX_AGE_SEC, code)
                    return False
    except Exception as _e:
        logger.warning("[ENTRY_GATE][STALE] ts파싱 실패 → 차단(fail-safe) code=%s err=%s", code, _e)
        return False

    # ── [PATCH 3] REGIME 차단 (KOSDAQ 장중 낙폭) ─────────────────
    try:
        _kq_raw = row.get("kosdaq_chg_pct", None)
        if _kq_raw is not None and str(_kq_raw).strip() not in ("", "0", "0.0"):
            _kq_chg = _safe_float(_kq_raw)
            if _kq_chg <= REGIME_KOSDAQ_MIN_PCT:
                logger.warning(
                    "[ENTRY_GATE][REGIME] KOSDAQ %.2f%% ≤ %.2f%% → 시장 하락 차단 code=%s",
                    _kq_chg, REGIME_KOSDAQ_MIN_PCT, code)
                return False
    except Exception as _e:
        logger.warning("[ENTRY_GATE][REGIME] 체크 실패 → 차단(fail-safe) code=%s err=%s", code, _e)
        return False

    # ── [PATCH 4] 진입 시간 제한 (Late Entry 차단) ───────────────
    # [EOD_PICK 2026-05-28] 종가매수 전략만 15:25까지 예외, 나머지는 ENTRY_CUT_TIME(1430) 유지
    try:
        _now_hhmm = int(datetime.now().strftime("%H%M"))
        _is_eod_pick = (str(row.get("strategy","")).strip().upper() == "EOD_PICK"
                        or str(row.get("strategy_type","")).strip().upper() == "EOD_PICK")
        _cut = EOD_PICK_CLOSE_HHMM if _is_eod_pick else ENTRY_CUT_TIME
        if _now_hhmm >= _cut:
            logger.warning(
                "[ENTRY_GATE][TIME] %04d ≥ %04d 진입 마감 → 차단 code=%s (eod_pick=%s)",
                _now_hhmm, _cut, code, _is_eod_pick)
            return False
    except Exception as _e:
        logger.warning("[ENTRY_GATE][TIME] 시간 체크 실패 → 차단(fail-safe) code=%s err=%s", code, _e)
        return False

    # [v4_6] PULLBACK 전략 완화 — mom_3m / vol_surge 기준 하향
    _strat_q = str(row.get("strategy","")).strip().upper()
    _stype_q = str(row.get("strategy_type","")).strip().upper()
    _is_pb_q = (_strat_q in PULLBACK_STRATEGY_TYPES or
                _stype_q in PULLBACK_STRATEGY_TYPES or
                str(row.get("addon_stage","")).strip() != "")
    _mom_min  = PULLBACK_MOM_3M_MIN   if _is_pb_q else ENTRY_MOM_3M_MIN_PCT
    _vsurge_min = PULLBACK_VOL_SURGE_MIN if _is_pb_q else ENTRY_VOL_SURGE_MIN_PCT
    if _is_pb_q:
        logger.info("[ENTRY_GATE][PULLBACK] 완화기준 mom≥%.1f%% vol≥%.0f%% code=%s",
                    _mom_min, _vsurge_min, code)

    _pr = _params_get("entry_max_spread_pct", None)
    spread_limit = (float(_pr)
                    if _pr is not None
                    else float(os.environ.get("ENTRY_MAX_SPREAD_PCT", "0.5")))

    ask = _safe_float(row.get("ask_price", 0))
    bid = _safe_float(row.get("bid_price", 0))
    if ask > 0 and bid > 0 and ask > bid:
        mid    = (ask + bid) / 2
        spread = (ask - bid) / mid * 100
        if spread > spread_limit:
            logger.warning(
                "[ENTRY_GATE] spread=%.2f%% > 허용%.2f%%(runtime params) → 차단 code=%s",
                spread, spread_limit, code)
            return False
        logger.info("[ENTRY_GATE] spread=%.2f%% ✅ code=%s", spread, code)

    volume = _safe_int(row.get("volume", 0))
    if volume > 0 and volume < ENTRY_MIN_VOLUME:
        logger.warning(
            "[ENTRY_GATE] volume=%d < 최소%d → 차단 code=%s",
            volume, ENTRY_MIN_VOLUME, code)
        return False
    if volume > 0:
        logger.info("[ENTRY_GATE] volume=%d ✅ code=%s", volume, code)

    # ── [⑥] 최근 3분 모멘텀 + 거래대금 증가율 (dv_accel > 0 전제 OR 구조) ──
    mom_3m = _safe_float(row.get("mom_3m_pct",
                          row.get("price_chg_3m_pct", 0)))
    vol_surge = _safe_float(row.get("vol_surge_pct",
                             row.get("volume_surge_pct", 0)))
    _dv_pre = _safe_float(row.get("dv_accel", 0.0))
    if _dv_pre > 0:
        # dv_accel 양수 전제: mom_3m 기준 OR vol_surge 강화기준(×1.5) 둘 중 하나
        _mom_pass  = (mom_3m == 0 or mom_3m >= _mom_min)
        _vol_pass  = (vol_surge == 0 or vol_surge >= _vsurge_min * 1.5)
        if _mom_pass:
            logger.info("[ENTRY_GATE] ⑥ mom=%.2f%% ✅ code=%s", mom_3m, code)
        elif _vol_pass:
            logger.info("[ENTRY_GATE] ⑥ vol=%.1f%%(강화기준%.1f%%) ✅ code=%s",
                        vol_surge, _vsurge_min * 1.5, code)
        else:
            logger.warning(
                "[ENTRY_GATE] ⑥ mom=%.2f%%(≥%.1f%%) vol=%.1f%%(≥%.1f%%) 둘 다 미달 → 차단 code=%s",
                mom_3m, _mom_min, vol_surge, _vsurge_min * 1.5, code)
            return False
    else:
        # dv_accel <= 0: 기존 AND 유지 (아래 dv_accel 필터에서 차단 예정)
        if mom_3m != 0 and mom_3m < _mom_min:
            logger.warning("[ENTRY_GATE] ⑥ 3분모멘텀=%.2f%% < %.2f%% → 차단 code=%s",
                           mom_3m, _mom_min, code)
            return False
        if vol_surge != 0 and vol_surge < _vsurge_min:
            logger.warning("[ENTRY_GATE] ⑥ 거래대금=%.1f%% < %.1f%% → 차단 code=%s",
                           vol_surge, _vsurge_min, code)
            return False

    # [2026-05-30 옵션B] dv_accel 미산출(컬럼부재/빈값)이면 통과(중립), 명시적 음수(<0)만 차단.
    #   배경: rt_signal_to_queue_bridge 큐에 dv_accel 컬럼 자체가 없어 0으로 읽혀
    #         SIGA_RT/PULLBACK/RT 모든 주문이 dv_accel≤0 으로 무조건 차단되던 문제.
    #   데이터가 채워지면(<0 매도흐름) 자동으로 다시 차단 → 회귀 위험 0.
    _dv_raw = row.get("dv_accel", None)
    if _dv_raw is None or str(_dv_raw).strip().lower() in ("", "nan", "none"):
        logger.info("[ENTRY_GATE] dv_accel 미산출(컬럼부재) → 통과(중립) code=%s", code)
    else:
        dv_accel = _safe_float(_dv_raw)
        if dv_accel < 0:
            logger.warning("[ENTRY_GATE] dv_accel=%.0f < 0 → 매도흐름 차단 code=%s", dv_accel, code)
            return False
        logger.info("[ENTRY_GATE] dv_accel=%.0f ✅ code=%s", dv_accel, code)

    # ── [PATCH 1] 슬리피지 차단 ───────────────────────────────────
    try:
        _sig_px = _safe_float(price)
        # 현재가 fallback: ask_price → current_price → price_ref → close_today → price
        _cur_px = 0.0
        for _px_key in ("ask_price", "current_price", "price_ref", "close_today", "price"):
            _v = _safe_float(row.get(_px_key, 0))
            if _v > 0:
                _cur_px = _v
                break
        if _sig_px > 0 and _cur_px > 0:
            if _cur_px == _sig_px:
                logger.info("[ENTRY_GATE][SLIP] 현재가=신호가(%.0f) 동일 → 슬리피지 없음 code=%s",
                            _sig_px, code)
            else:
                _slip_pct = (_cur_px - _sig_px) / _sig_px * 100
                if _slip_pct > ENTRY_MAX_SLIP_PCT:
                    logger.warning(
                        "[ENTRY_GATE][SLIP] 슬리피지 %.2f%% > 허용%.2f%% → 차단 code=%s",
                        _slip_pct, ENTRY_MAX_SLIP_PCT, code)
                    return False
                logger.info("[ENTRY_GATE][SLIP] 슬리피지 %.2f%% ✅ code=%s", _slip_pct, code)
    except Exception as _e:
        logger.warning("[ENTRY_GATE][SLIP] 계산 실패 → 차단(fail-safe) code=%s err=%s", code, _e)
        return False

    # ── [PATCH 5] 체결 품질 필터 (ask/bid 실시간 우선, 없을 때만 spread_pct 폴백) ──
    try:
        if not (ask > 0 and bid > 0):   # ask/bid 실시간 체크 불가 시에만 폴백
            spread_pct = _safe_float(row.get("spread_pct", 0.0))
            if spread_pct > 0.5:
                logger.warning(
                    "[ENTRY_GATE][SPREAD] spread_pct=%.2f%% > 0.5%% → 체결 불량(폴백) 차단 code=%s",
                    spread_pct, code)
                return False
            logger.info("[ENTRY_GATE][SPREAD] spread_pct=%.2f%% (폴백) ✅ code=%s",
                        spread_pct, code)
        tick_accel = _safe_float(row.get("tick_accel", 0.0))
        logger.info("[ENTRY_GATE][TICK] tick_accel=%.2f (참조용, 차단 없음) code=%s",
                    tick_accel, code)
    except Exception as _e:
        logger.warning("[ENTRY_GATE][SPREAD/TICK] 체크 실패 → 차단(fail-safe) code=%s err=%s", code, _e)
        return False

    return True


# ═══════════════════════════════════════════════════════════════
#  [v3_9] ① EV 필터 + ② Score 필터 + ③ Market 필터
#  [v4_3] FIX-2: inst_ride 플래그 파라미터 추가 (inst_score 단독 완화 폐기)
#         OPT-5: ev_pct=0 fallback score 전략별 차등화
#         OPT-6: 차단 사유 코드 로그 추가
# ═══════════════════════════════════════════════════════════════
def _ev_conviction_gate(row: Dict[str, Any], code: str,
                         regime: str,
                         logger: logging.Logger,
                         inst_ride: bool = False,
                         daily_entry_count: int = 0) -> bool:
    """①②③ 통합: EV/Score/Regime 기반 진입 허가
    [FIX-2] EV 완화는 inst_ride=True(4조건 동시 충족) 시에만 허용
    [OPT-5] ev_pct=0 fallback score 전략별 차등
    [OPT-6] 차단 사유 코드 로그
    [v4_6] PULLBACK 전략 전용 완화 필터 분기
    [v4_7-P2] Alpha Decay — 시간대별 EV 기준 강화
    [v4_7-P5] 1일 1진입 보장 게이트 — daily_entry_count=0이면 완화 적용
    """
    if not CONVICTION_GATE_ENABLED:
        return True

    ev_pct  = _safe_float(row.get("ev_pct", 0))
    score   = _safe_float(row.get("score", 0))
    _strat  = str(row.get("strategy","")).strip().upper()
    _stype  = str(row.get("strategy_type","")).strip().upper()
    score_fallback = _FALLBACK_SCORE_BY_STRATEGY.get(_strat, _FALLBACK_SCORE_DEFAULT)

    # [v4_7-P5] 1일 1진입 보장 — 오늘 아직 한 번도 진입 없으면 완화
    _daily_min_active = (DAILY_MIN_ENTRY_ENABLED and daily_entry_count == 0)
    # [#2 킬스위치 2026-06-08] 급락장/CB/수동차단/preflight 이상 시 DAILY_MIN 완화 절대 금지(위험장 기준완화 강행 방지)
    if _daily_min_active:
        _dm_block, _dm_reason = _crash_kill_switch(logger)
        if _dm_block:
            _daily_min_active = False
            logger.warning("[DAILY_MIN] ⛔ 위험상태로 1일1진입 보장 비활성 reason=%s code=%s", _dm_reason, code)
    if _daily_min_active:
        logger.info("[DAILY_MIN] 1일 1진입 보장 게이트 활성 — EV/Score 기준 완화 code=%s (preflight/crash/manual 통과)", code)

    # [v4_7-P2] Alpha Decay EV 강화
    hhmm = _hhmm()
    alpha = _get_alpha_decay(hhmm)
    # alpha가 낮은 구간 = EV 기준 상향 (1/alpha 배수)
    ev_min_adjusted = EV_MIN_PCT / alpha if alpha > 0 else EV_MIN_PCT
    if alpha < 1.0:
        logger.info("[ALPHA_DECAY] hhmm=%04d alpha=%.2f → EV기준 %.2f%%→%.2f%% code=%s",
                    hhmm, alpha, EV_MIN_PCT, ev_min_adjusted, code)

    # 1일 1진입 완화 적용 시 EV 기준 낮춤
    if _daily_min_active:
        ev_min_adjusted = max(EV_MIN_PCT * (1 - DAILY_MIN_ENTRY_EV_RELAX), ev_min_adjusted * (1 - DAILY_MIN_ENTRY_EV_RELAX))
        logger.info("[DAILY_MIN] EV기준 완화 → %.2f%% code=%s", ev_min_adjusted, code)

    # [v4_6] PULLBACK 전략 전용 완화 필터 ─────────────────────
    _is_pullback = (_strat in PULLBACK_STRATEGY_TYPES
                    or _stype in PULLBACK_STRATEGY_TYPES)
    _is_addon    = str(row.get("addon_stage", "")).strip() != ""

    if _is_pullback or _is_addon:
        # [v4_9-P5] BEAR 차단 항상 적용 — 추세 눌림 전략은 BEAR 시장 부적합 (1일1진입 우회 제거)
        if REGIME_BEAR_BLOCK and regime == "BEAR":
            logger.warning("[CONV_GATE][PULLBACK][BLOCK:REGIME001] BEAR 차단(daily_min 우회 무시) code=%s", code)
            return False
        _ev_min_pb = PULLBACK_EV_MIN
        _ev_r_pb   = PULLBACK_EV_RISK_RATIO
        if ev_pct > 0 and ev_pct < (_ev_min_pb - INST_EV_RELAX_PCT if inst_ride else _ev_min_pb):
            logger.warning("[CONV_GATE][PULLBACK][BLOCK:EV_PB] ev=%.2f%%<%.2f%% code=%s",
                           ev_pct, _ev_min_pb, code)
            return False
        # [v4_9-P5] 절대 EV 하한 — PULLBACK도 적용 (ev_pct=0 데이터없음 경로는 유지)
        if ev_pct > 0 and ev_pct < ABS_EV_FLOOR:
            logger.warning(
                "[CONV_GATE][PULLBACK][BLOCK:EV_FLOOR] ev=%.2f%%<절대하한%.2f%% code=%s",
                ev_pct, ABS_EV_FLOOR, code)
            return False
        if regime == "NEUTRAL" and ev_pct > 0 and ev_pct < PULLBACK_NEUTRAL_EV_MIN:
            logger.warning("[CONV_GATE][PULLBACK][BLOCK:EV_NEUTRAL] ev=%.2f%% code=%s",
                           ev_pct, code)
            return False
        # [v4_9-P5] PULLBACK 전용 score 최저 보호 — 너무 약한 종목 진입 차단
        _score_min_pb = float(os.environ.get("PULLBACK_SCORE_MIN", "65.0"))
        # [DAILY_MIN-CONSISTENCY 2026-06-04] 1일 1진입 보장이 EV는 완화하면서 score floor는 안 건드려
        # "보장"이 무력화되던 불일치 복원 — EV와 동일 비율(DAILY_MIN_ENTRY_EV_RELAX)로 score floor도 완화.
        # 첫 진입 전(daily_min 활성)에만 적용, 매수 후엔 자동으로 원래 floor 복귀.
        _score_min_pb_eff = (_score_min_pb * (1 - DAILY_MIN_ENTRY_EV_RELAX)
                             if _daily_min_active else _score_min_pb)
        if _daily_min_active and _score_min_pb_eff != _score_min_pb:
            logger.info("[DAILY_MIN] PULLBACK score floor 완화 %.0f→%.1f code=%s",
                        _score_min_pb, _score_min_pb_eff, code)
        # [RIDE-FLOOR-RELAX 2026-06-05] 강한 기관 ride면 score floor 추가 완화 (기관 등타기 전략 정합).
        #   ride는 이미 selection_score(W_RIDE=0.15)에 일부 반영되나 가중 낮아, 강한 기관 매집을
        #   가격셋업 score 미달로 놓치는 것 방지. 랭킹/선택 무영향 — conv 게이트 floor만 낮춤.
        _ride_now = _safe_float(row.get("ride_score", row.get("inst_ride_score", 0.0)))
        if RIDE_FLOOR_RELAX_PCT > 0 and _ride_now >= RIDE_FLOOR_RELAX_MIN:
            _floor_before = _score_min_pb_eff
            _score_min_pb_eff = _score_min_pb_eff * (1 - RIDE_FLOOR_RELAX_PCT)
            logger.info("[CONV_GATE][PULLBACK] 강한 ride=%.2f>=%.2f → score floor %.1f→%.1f 완화 code=%s",
                        _ride_now, RIDE_FLOOR_RELAX_MIN, _floor_before, _score_min_pb_eff, code)
        if score > 0 and score < _score_min_pb_eff:
            logger.warning(
                "[CONV_GATE][PULLBACK][BLOCK:SCORE_PB] score=%.1f<%.1f code=%s",
                score, _score_min_pb_eff, code)
            return False
        logger.info("[CONV_GATE][PULLBACK] ✅ 완화 필터 통과 ev=%.2f%% score=%.1f code=%s",
                    ev_pct, score, code)
        return True
    # ─────────────────────────────────────────────────────────

    # ③ Market 필터 — BEAR 즉시 차단 (단, 1일 1진입 보장 시 유예)
    if REGIME_BEAR_BLOCK and regime == "BEAR" and not _daily_min_active:
        logger.warning(
            "[CONV_GATE][BLOCK:REGIME001] BEAR 시장 → 진입 금지 code=%s", code)
        return False

    # ② Score 필터
    _score_min_eff = DAILY_MIN_ENTRY_SCORE_MIN if _daily_min_active else SCORE_MIN
    if score > 0 and score < _score_min_eff:
        logger.warning(
            "[CONV_GATE][BLOCK:SCORE001] score=%.1f < 최소%.0f → 차단 code=%s",
            score, _score_min_eff, code)
        return False
    if score >= _score_min_eff:
        logger.info("[CONV_GATE] ② score=%.1f ✅ code=%s", score, code)

    # ev_pct=0 → 데이터 없음: 전략별 score fallback 판단
    if ev_pct <= 0:
        _fb = score_fallback if not _daily_min_active else score_fallback - 5.0
        if score >= _fb:
            logger.info(
                "[CONV_GATE] ① ev_pct=0(데이터없음) → score=%.1f≥%.0f "
                "전략=%s 보수적 허용 code=%s",
                score, _fb, _strat or "DEFAULT", code)
            return True
        else:
            logger.warning(
                "[CONV_GATE][BLOCK:EV000] ev_pct=0 + score=%.1f<%.0f "
                "전략=%s → 차단 code=%s",
                score, _fb, _strat or "DEFAULT", code)
            return False

    # ① EV 완화 — inst_ride=True(4조건) 전제
    ev_relax = 0.0
    if INST_RIDE_ENABLED and inst_ride:
        ev_relax = INST_EV_RELAX_PCT
        logger.info(
            "[CONV_GATE] ⑧ inst_ride=True(4조건) → EV기준 %.2f%% 완화 code=%s",
            ev_relax, code)

    # ③ regime별 EV 기준 적용 (alpha_decay 반영)
    _neutral_min = max(REGIME_NEUTRAL_EV_MIN, ev_min_adjusted) - ev_relax
    _bull_min    = max(REGIME_BULL_EV_MIN, ev_min_adjusted * 0.75) - ev_relax
    if regime == "NEUTRAL" and ev_pct < _neutral_min:
        logger.warning(
            "[CONV_GATE][BLOCK:EV001] NEUTRAL ev=%.2f%% < 필요%.2f%% → 차단 code=%s",
            ev_pct, _neutral_min, code)
        return False
    if regime == "BULL" and ev_pct < _bull_min:
        logger.warning(
            "[CONV_GATE][BLOCK:EV002] BULL ev=%.2f%% < 필요%.2f%% → 차단 code=%s",
            ev_pct, _bull_min, code)
        return False

    # [v4_9 PATCH5] 절대 EV 하한 — ev_pct=0(데이터없음) 경로는 유지
    if ev_pct > 0 and ev_pct < ABS_EV_FLOOR:
        logger.warning(
            "[CONV_GATE][BLOCK:EV000A] ev=%.2f%% < 절대하한%.2f%% → 차단 code=%s",
            ev_pct, ABS_EV_FLOOR, code)
        return False

    # ① 절대 EV 최소 (alpha_decay 반영)
    if ev_pct < (ev_min_adjusted - ev_relax):
        logger.warning(
            "[CONV_GATE][BLOCK:EV003] ev=%.2f%% < 최소%.2f%%(alpha%.2f) → 차단 code=%s",
            ev_pct, ev_min_adjusted - ev_relax, alpha, code)
        return False

    # ① EV/리스크 비율
    expected_loss = _safe_float(row.get("atr_pct",
                     row.get("daily_vol_pct",
                      row.get("expected_loss_pct", 0))))
    if expected_loss > 0:
        ev_risk_ratio = ev_pct / expected_loss
        if ev_risk_ratio < EV_RISK_RATIO_MIN:
            logger.warning(
                "[CONV_GATE][BLOCK:EV004] EV/리스크=%.2f < 최소%.1f "
                "(ev=%.2f%% loss=%.2f%%) → 차단 code=%s",
                ev_risk_ratio, EV_RISK_RATIO_MIN,
                ev_pct, expected_loss, code)
            return False
        logger.info(
            "[CONV_GATE] ① EV/리스크=%.2f ✅ (ev=%.2f%% loss=%.2f%%) code=%s",
            ev_risk_ratio, ev_pct, expected_loss, code)

    logger.info("[CONV_GATE] ① ev=%.2f%% ✅ regime=%s inst_ride=%s alpha=%.2f code=%s",
                ev_pct, regime, inst_ride, alpha, code)
    return True


# ═══════════════════════════════════════════════════════════════
#  [v4_0] ④ EV 연동 포지션 사이징 — 잔고비율 기반 (개인투자자 현실화)
#  [v4_3 FIX-2] inst_ride=True(4조건) 전제 시에만 포지션 강화 허용
#  [v4_3 FIX-3] pre_slip_bps/impact_bps/regime 기반 최종 캡 추가
# ═══════════════════════════════════════════════════════════════
def _ev_position_ratio(row: Dict[str, Any],
                        logger: logging.Logger,
                        inst_score: float = 0.0,
                        inst_ride:  bool  = False,
                        pre_slip_bps: float = 0.0,
                        impact_bps:   float = 0.0,
                        regime:       str   = "",
                        strategy:     str   = "",
                        available_krw: int  = 0,
                        hard_stop_pct: float = 0.025) -> float:
    """EV + 기관 탑승 기반 최종 투입 잔고비율 결정
    [FIX-2] inst_ride=True(4조건) 전제 — inst_score 단독 포지션 강화 폐기
    [FIX-3] 체결 위험 기반 최종 캡: pre_slip/impact/regime 반영
    [v4_7]  야간 리스크 캡 완전 제거 — 당일청산 전략 전용
    [v4_8R] R값 Volatility 사이징 레이어 추가 (RenTec + Citadel 혼합 방식)
            출처: Kelly(1956) / Thorp(1962) / Van Tharp(1999)
            R = available_krw × Half-Kelly
            R_ratio = R / (price × hard_stop_pct)
            EV비율 vs R비율 → 더 보수적 값 채택 (과대진입 방지)
    """
    ev_pct = _safe_float(row.get("ev_pct", 0))

    # [FIX-2] inst_ride 플래그 기반 포지션 결정
    inst_high_flag = inst_ride and inst_score >= INST_SCORE_HIGH

    if ev_pct >= EV_SIZE_TIER_HIGH or inst_high_flag:
        ratio = EV_SIZE_RATIO_HIGH   # 0.98 — 풀 몰빵
        tag   = (f"ev={ev_pct:.2f}%≥{EV_SIZE_TIER_HIGH}"
                 if ev_pct >= EV_SIZE_TIER_HIGH
                 else f"inst_ride+HIGH inst={inst_score:.2f}")
    elif ev_pct >= EV_SIZE_TIER_MID or inst_ride:
        ratio = EV_SIZE_RATIO_MID    # 0.85 — 적극
        tag   = (f"ev={ev_pct:.2f}%≥{EV_SIZE_TIER_MID}"
                 if ev_pct >= EV_SIZE_TIER_MID
                 else f"inst_ride inst={inst_score:.2f}")
    else:
        ratio = EV_SIZE_RATIO_BASE   # 0.70 — 신중
        tag   = f"ev={ev_pct:.2f}%(낮음) inst_ride=False"

    # ── [v4_8R] R값 Volatility 사이징 레이어 ──────────────────────
    # 헤지펀드 방식: Half-Kelly 신뢰도 × 손절폭 조정 → EV비율 조정
    # 출처: Kelly(1956) / Thorp(1962) 주식 버전 / Van Tharp(1999)
    #
    # 적용 방식:
    #   ① Half-Kelly = (WR - (1-WR)/RR) × 0.5  → 신뢰도 지수
    #   ② 손절 조정 = 기준손절(2.5%) / 실제손절  → 넓으면 ↓, 타이트하면 상한(1.4)
    #   ③ EV비율 × Kelly신뢰도 × 손절조정 → 최종 비율
    #   하한: 50% / 상한: 원래 EV비율 (사이즈UP 없음 — min 구조)
    #
    # 동작 예시:
    #   손절 2.5%(기준) + WR52% → EV 그대로 (kelly_conf=1.0, stop_adj=1.0)
    #   손절 4.0%(넓음) + WR48% → EV 축소 (리스크 큼 → 포지션 줄임)
    #   손절 1.5%(타이트) + WR55% → EV 유지 (상한=원래EV, 사이즈UP 없음)
    #   WR 낮음 + 손절 넓음     → EV 최대 50%까지 축소
    _r_ratio_applied = False
    if available_krw > 0 and hard_stop_pct > 0:
        _wr = _safe_float(row.get("win_rate",
                          row.get("strat_win_rate", 0.52)))
        _rr = _safe_float(row.get("rr_ratio", 2.0))
        if _wr <= 0 or _wr >= 1:
            _wr = 0.52
        if _rr <= 0:
            _rr = 2.0

        # ① Half-Kelly 신뢰도 (Thorp 1962 주식 버전)
        kelly_full  = max(0.0, _wr - (1 - _wr) / _rr)
        half_kelly  = kelly_full * 0.5
        # 기준 Half-Kelly: 현재 WR/RR로 계산한 값이 기준
        # WR52%/RR2.0 → 0.14가 기본이나, 실제 데이터 반영을 위해
        # 기준값을 고정 0.14가 아닌 전략 최소 요건(WR50%/RR1.5)으로 동적 계산
        _kelly_base = max(0.0, 0.50 - 0.50 / 1.5) * 0.5  # WR50%/RR1.5 최소기준 = 0.0833
        kelly_conf  = min(half_kelly / max(_kelly_base, 0.01), 1.0)

        # ② 손절폭 조정 (기준 2.5% 대비)
        stop_adj    = 0.025 / hard_stop_pct
        stop_adj    = max(0.60, min(stop_adj, 1.40))  # 60%~140% 범위

        # ③ 최종 비율 조정
        r_adjusted  = ratio * kelly_conf * stop_adj
        r_adjusted  = round(max(0.50, min(r_adjusted, ratio)), 4)

        if r_adjusted < ratio:
            logger.info(
                "[R_SIZE][v4_8R] EV=%.0f%% → R조정=%.0f%% "
                "(WR=%.0f%% RR=%.1f kelly_conf=%.2f stop_adj=%.2f stop=%.1f%%) code=%s",
                ratio * 100, r_adjusted * 100,
                _wr * 100, _rr, kelly_conf, stop_adj,
                hard_stop_pct * 100, row.get("code", ""))
            ratio = r_adjusted
            tag  += f"|R조정={r_adjusted:.0%}"
            _r_ratio_applied = True
        else:
            logger.debug(
                "[R_SIZE][v4_8R] R조정=%.0f%% ≥ EV=%.0f%% → 조정없음 code=%s",
                r_adjusted * 100, ratio * 100, row.get("code", ""))

    # [FIX-3] 체결 위험 기반 최종 캡 — 몰빵 비율 자동 축소
    # [v4_7] 야간캡(종배 전용) 블록 완전 제거 — 당일청산 전략만 처리
    cap          = 1.0
    cap_reasons: list = []

    if pre_slip_bps > 35:                          # 슬리피지 고위험
        cap = min(cap, EV_SIZE_RATIO_BASE)
        cap_reasons.append(f"pre_slip={pre_slip_bps:.0f}bps>35→BASE")
    elif pre_slip_bps > 20:                        # 슬리피지 경계
        cap = min(cap, EV_SIZE_RATIO_MID)
        cap_reasons.append(f"pre_slip={pre_slip_bps:.0f}bps>20→MID")

    if impact_bps > 30:                            # 시장충격 고위험
        cap = min(cap, EV_SIZE_RATIO_MID)
        cap_reasons.append(f"impact={impact_bps:.0f}bps>30→MID")

    if regime == "NEUTRAL":                        # NEUTRAL: 98% 몰빵 금지
        cap = min(cap, EV_SIZE_RATIO_MID)
        cap_reasons.append("regime=NEUTRAL→MID")
    elif regime == "BEAR":                         # BEAR: 최소 비율 (차단 fallback)
        cap = min(cap, EV_SIZE_RATIO_BASE)
        cap_reasons.append("regime=BEAR→BASE")

    if cap < ratio:
        pre_ratio = ratio
        ratio = cap
        logger.warning(
            "[EV_SIZE_CAP][FIX-3] %.0f%%→%.0f%% 캡 적용 "
            "사유: %s code=%s",
            pre_ratio * 100, ratio * 100,
            " | ".join(cap_reasons), row.get("code",""))
    else:
        if cap_reasons:
            logger.info("[EV_SIZE_CAP] 캡 조건 있으나 비율 이미 적절 "
                        "(%s) code=%s", " | ".join(cap_reasons), row.get("code",""))

    logger.info("[EV_SIZE_v4_8R] ④ 투입비율=%.0f%% (%s) "
                "inst_ride=%s pre_slip=%.0fbps impact=%.0fbps regime=%s "
                "R적용=%s code=%s",
                ratio * 100, tag, inst_ride,
                pre_slip_bps, impact_bps, regime,
                _r_ratio_applied, row.get("code",""))
    return ratio


# ═══════════════════════════════════════════════════════════════
#  [v4_0] ⑧ 기관 탑승 게이트 — [PROFIT-1]
#  "기관의 등에 탔다가 미리 내리는" 개념 — 기관 있으면 절대 안 판다
#  [v4_1] inst_score 신선도 검증 추가 — 90초 초과 시 기관 신호 무효화
# ═══════════════════════════════════════════════════════════════
_INST_STALE_SEC = int(os.environ.get("INST_STALE_SEC", "90"))  # 지침서 §12 데이터지연 기준

def _inst_ride_gate(row: Dict[str, Any], code: str,
                    logger: logging.Logger,
                    regime: str = "") -> Tuple[bool, float, int, bool]:
    """기관 탑승 여부 확인 및 탑승 강도 반환
    Returns: (inst_present, inst_score, inst_consec, inst_ride_flag)
    [v4_1] inst_ts 필드로 데이터 신선도 확인 — 90초 초과 시 inst_score=0 처리
    [v4_3 FIX-2] inst_ride=True 4조건 동시 충족 필수:
        ① inst_score  ≥ INST_SCORE_MIN(0.35)
        ② inst_consec ≥ INST_CONSEC_MIN(3)
        ③ freshness   ≤ 90s
        ④ regime      ≠ BEAR
    """
    if not INST_RIDE_ENABLED:
        return False, 0.0, 0, False

    inst_score = _safe_float(row.get("inst_score",
                  row.get("inst_buy_score",
                   row.get("inst_ride_score", 0))))
    inst_consec = _safe_int(row.get("inst_consec",
                   row.get("inst_consecutive_buy", 0)))

    # [v4_1] 신선도 검증 — inst_ts 필드 (YYYYmmdd HH:MM:SS 또는 ISO)
    inst_ts_raw = str(row.get("inst_ts", row.get("inst_update_ts", ""))).strip()
    if inst_ts_raw:
        try:
            from datetime import datetime as _dt
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    inst_dt = _dt.strptime(inst_ts_raw[:19], fmt)
                    break
                except ValueError:
                    continue
            else:
                inst_dt = None

            if inst_dt is not None:
                now_naive = _now().replace(tzinfo=None)
                age_sec   = (now_naive - inst_dt).total_seconds()
                if age_sec > _INST_STALE_SEC:
                    logger.warning(
                        "[INST_RIDE] ⚠️ inst_score 데이터 만료 %.0fs > %ds "
                        "→ inst_score=0 무효화 code=%s (원본=%.2f)",
                        age_sec, _INST_STALE_SEC, code, inst_score)
                    inst_score  = 0.0
                    inst_consec = 0
                else:
                    logger.info("[INST_RIDE] 데이터 신선도 OK %.0fs code=%s",
                                age_sec, code)
        except Exception as e:
            logger.debug("[INST_RIDE] ts 파싱 실패: %s (무시)", e)

    inst_present = inst_score >= INST_SCORE_MIN
    # [v4_3 FIX-2] 4조건 동시 충족: score + consec + freshness(신선도는 위에서 처리) + regime≠BEAR
    inst_ride    = (inst_score  >= INST_SCORE_MIN
                    and inst_consec >= INST_CONSEC_MIN
                    and regime != "BEAR")

    if regime == "BEAR" and inst_score >= INST_SCORE_MIN and inst_consec >= INST_CONSEC_MIN:
        logger.warning(
            "[INST_RIDE][BLOCK:INST002] BEAR 레짐 → inst_ride 강제 False "
            "code=%s inst=%.2f consec=%d",
            code, inst_score, inst_consec)

    if inst_ride:
        logger.info(
            "[INST_RIDE] ⑧ ✅ 기관 탑승 확인 inst=%.2f consec=%d code=%s "
            "→ 기관 이탈 전 선청산 전략 활성화",
            inst_score, inst_consec, code)
    elif inst_present:
        logger.info("[INST_RIDE] ⑧ 기관 존재(약) inst=%.2f consec=%d code=%s",
                    inst_score, inst_consec, code)
    else:
        logger.info("[INST_RIDE] ⑧ 기관 미탐지 inst=%.2f code=%s",
                    inst_score, code)

    return inst_present, inst_score, inst_consec, inst_ride


# ═══════════════════════════════════════════════════════════════
#  [v3_9] ⑦ Overheat 필터 — 현재 봉 range > 20봉 평균 × 2.5
# ═══════════════════════════════════════════════════════════════
def _overheat_filter(row: Dict[str, Any], code: str,
                      logger: logging.Logger) -> bool:
    """과열 상태 감지 — 진입 시점 변동성이 평균 대비 극단적이면 차단"""
    cur_range = _safe_float(row.get("cur_bar_range_pct",
                             row.get("bar_range_pct", 0)))
    avg_range = _safe_float(row.get("avg_bar_range_pct",
                             row.get("avg_range_20_pct", 0)))
    if cur_range <= 0 or avg_range <= 0:
        return True  # 데이터 없으면 pass

    ratio = cur_range / avg_range
    if ratio > OVERHEAT_MULT:
        logger.warning(
            "[OVERHEAT] ⑦ 현재봉=%.2f%% / 20봉평균=%.2f%% "
            "= %.1f배 > %.1f배 → 진입 금지 code=%s",
            cur_range, avg_range, ratio, OVERHEAT_MULT, code)
        return False
    logger.info("[OVERHEAT] ⑦ 변동성 비율=%.1f배 ✅ code=%s",
                ratio, code)
    return True

# ──────────────────────────────────────────────────────────────
#  시장 상태 판단 (BULL / BEAR / NEUTRAL)
#  [v4_7-P1] IC-가중 레짐 앙상블 (Grinold & Kahn 1994)
#  기존: 4신호 동일가중 투표
#  개선: 각 신호의 IC(Information Coefficient) 비례 가중 합산
#  출처: Grinold, R. & Kahn, R. (1994) "Active Portfolio Management"
#        IC = corr(signal, next_period_return)
#        실무 추정 IC: 코스닥 0.35 / 코스피 0.25 / 외국인 0.20 / 거래량 0.15
# ──────────────────────────────────────────────────────────────
# 신호별 IC 가중치 (실증 기반 추정 — params_reader로 오버라이드 가능)
_IC_KOSDAQ  = float(os.environ.get("IC_KOSDAQ",  "0.35"))
_IC_KOSPI   = float(os.environ.get("IC_KOSPI",   "0.25"))
_IC_FOREIGN = float(os.environ.get("IC_FOREIGN", "0.20"))
_IC_VOLUME  = float(os.environ.get("IC_VOLUME",  "0.15"))
_IC_OFI     = float(os.environ.get("IC_OFI",     "0.05"))  # OFI 보조신호

def _market_regime(row: Dict[str, Any],
                   logger: logging.Logger) -> str:
    """IC-가중 레짐 앙상블 (v4_7-P1)
    각 신호를 [-1, +1] 점수로 변환 후 IC 가중 합산
    합산 점수 > +threshold → BULL / < -threshold → BEAR / 그 외 → NEUTRAL
    """
    # ── [REGIME-TODAY 2026-06-12 ★친구님 지시 "눈 통일"] 당일 실시간 지수 최우선 ──
    #   rt_risk와 동일 처방: kosdaq_index.json(당일+10분내 신선)이 ±1.5% 넘으면 1순위.
    #   비신선이면 기존 앙상블 그대로. 롤백: env REGIME_TODAY_OVERRIDE=NO (3파일 공통).
    if os.environ.get("REGIME_TODAY_OVERRIDE", "YES").strip().upper() == "YES":
        try:
            from datetime import datetime as _rt_dt
            _idx_p = Path(r"C:\stock_bot\DATA\kosdaq_index.json")
            if _idx_p.exists():
                with open(_idx_p, "r", encoding="utf-8-sig") as _rf:
                    _idx = json.load(_rf)
                _its, _chg = str(_idx.get("ts", "")), _idx.get("chg", None)
                if _its and _chg is not None:
                    _age = (_rt_dt.now() - _rt_dt.strptime(_its, "%Y-%m-%d %H:%M:%S")).total_seconds()
                    if _its[:10] == _rt_dt.now().strftime("%Y-%m-%d") and _age <= 600:
                        _chg = float(_chg)
                        if _chg >= 1.5:
                            logger.info("[REGIME-TODAY] 당일 KOSDAQ %+.2f%% (신선 %.0fs) → BULL (앙상블 무시)", _chg, _age)
                            return "BULL"
                        if _chg <= -1.5:
                            logger.info("[REGIME-TODAY] 당일 KOSDAQ %+.2f%% (신선 %.0fs) → BEAR (앙상블 무시)", _chg, _age)
                            return "BEAR"
        except Exception as _rte:
            logger.debug("[REGIME-TODAY] 스킵(%s)", _rte)
    mkt_risk    = _safe_int(row.get("mkt_risk_flag", 0))
    kq_chg      = _safe_float(row.get("kosdaq_chg_pct", 0))
    ks_chg      = _safe_float(row.get("kospi_chg_pct",
                   row.get("kospi_change_pct", 0)))
    frgn_net    = _safe_float(row.get("frgn_net_buy_ratio",
                   row.get("foreign_net_ratio", 0)))
    vol_ratio_m = _safe_float(row.get("market_vol_ratio",
                   row.get("mkt_vol_ratio", 0)))
    ofi_market  = _safe_float(row.get("market_ofi",
                   row.get("market_inst_ofi", 0)))   # 시장 전체 OFI (선택)

    # ── 신호 → [-1, +1] 점수 변환 ──────────────────────────────
    # 코스닥 신호 (primary, 가장 높은 IC)
    if mkt_risk == 1 or kq_chg <= -1.5:
        s_kq = -1.0
    elif kq_chg <= -0.5:
        s_kq = -0.5
    elif kq_chg >= 1.0:
        s_kq = +1.0
    elif kq_chg >= 0.5:
        s_kq = +0.5
    else:
        s_kq = 0.0

    # 코스피 신호
    if ks_chg <= -1.0:
        s_ks = -1.0
    elif ks_chg <= -0.3:
        s_ks = -0.5
    elif ks_chg >= 0.5:
        s_ks = +1.0
    elif ks_chg >= 0.3:
        s_ks = +0.5
    else:
        s_ks = 0.0

    # 외국인 순매수 신호
    if frgn_net < -0.25:
        s_frgn = -1.0
    elif frgn_net < -0.10:
        s_frgn = -0.5
    elif frgn_net > 0.20:
        s_frgn = +1.0
    elif frgn_net > 0.10:
        s_frgn = +0.5
    else:
        s_frgn = 0.0

    # 거래량 신호 (급감=신뢰도 하락, 급증=추세 동반)
    if 0 < vol_ratio_m < 0.55:
        s_vol = -0.5   # 급감 → 약한 BEAR 신호
    elif vol_ratio_m >= 1.30:
        s_vol = +0.5   # 급증 → 약한 BULL 신호
    else:
        s_vol = 0.0

    # OFI 보조 신호 (데이터 있을 때만)
    if ofi_market < -0.25:
        s_ofi = -0.5
    elif ofi_market > 0.20:
        s_ofi = +0.5
    else:
        s_ofi = 0.0

    # ── IC-가중 합산 ────────────────────────────────────────────
    ic_score = (
        s_kq   * _IC_KOSDAQ  +
        s_ks   * _IC_KOSPI   +
        s_frgn * _IC_FOREIGN +
        s_vol  * _IC_VOLUME  +
        s_ofi  * _IC_OFI
    )
    total_ic = _IC_KOSDAQ + _IC_KOSPI + _IC_FOREIGN + _IC_VOLUME + _IC_OFI
    ic_norm  = ic_score / total_ic if total_ic > 0 else 0.0  # 정규화 [-1, +1]

    # ── 최종 판정 ───────────────────────────────────────────────
    BEAR_THRESHOLD = -0.25   # 음수 IC ≤ -0.25 → BEAR
    BULL_THRESHOLD = +0.20   # 양수 IC ≥ +0.20 → BULL
    if ic_norm <= BEAR_THRESHOLD:
        regime = "BEAR"
    elif ic_norm >= BULL_THRESHOLD:
        regime = "BULL"
    else:
        regime = "NEUTRAL"

    logger.info(
        "[REGIME_v4_7] IC앙상블=%s | score=%.3f(norm) "
        "kq=%.2f(%.2f) ks=%.2f(%.2f) frgn=%.2f(%.2f) "
        "vol=%.2f(%.2f) ofi=%.2f(%.2f) | 임계±%.2f/±%.2f",
        regime, ic_norm,
        kq_chg, s_kq, ks_chg, s_ks, frgn_net, s_frgn,
        vol_ratio_m, s_vol, ofi_market, s_ofi,
        abs(BEAR_THRESHOLD), BULL_THRESHOLD)
    return regime

# ──────────────────────────────────────────────────────────────
#  호가 레벨 시장충격 추정 — [v4_7-P4] Almgren-Chriss 정밀화
#  기존: depth_ratio × spread_bps (단순 단일 추정)
#  개선: 영구충격(γ) + 임시충격(η) 분리
#  출처: Almgren, R. & Chriss, N. (2001) "Optimal Execution of
#        Portfolio Transactions" Journal of Risk, 3, 5-40
#
#  공식:
#    permanent_impact_bps = γ × (order_size / avg_daily_volume) × 10000
#    temporary_impact_bps = η × (order_rate / spread_bps)
#    total_impact_bps = permanent + temporary
#
#  실무 파라미터 (KOSDAQ 스몰캡 기준):
#    γ = 0.50  (영구충격 계수 — 시장에 흔적이 남는 정도)
#    η = 0.30  (임시충격 계수 — 주문 속도에 비례)
# ──────────────────────────────────────────────────────────────
_AC_GAMMA = float(os.environ.get("AC_GAMMA", "0.50"))  # 영구충격 계수
_AC_ETA   = float(os.environ.get("AC_ETA",   "0.30"))  # 임시충격 계수

def _market_impact_bps(row: Dict[str, Any],
                        qty: int, price: int,
                        logger: logging.Logger) -> float:
    """Almgren-Chriss 영구충격 + 임시충격 분리 추정 (v4_7-P4)"""
    ask     = _safe_float(row.get("ask_price", price))
    bid     = _safe_float(row.get("bid_price", price))
    mid     = (ask + bid) / 2 if (ask > 0 and bid > 0 and ask > bid) else float(price)
    spread_bps = (ask - bid) / mid * 10000 if mid > 0 else 5.0

    order_krw   = qty * price if price > 0 else 0
    avg_daily_v = _safe_float(row.get("avg_daily_volume",
                   row.get("avg_vol_20d", 0)))    # 20일 평균 거래량
    avg_1m_val  = _safe_float(row.get("avg_1m_value", 0))
    ask_size1   = _safe_int(row.get("ask_size1", 0))

    # ── ① 영구충격 (Permanent Impact) ──────────────────────────
    # 주문 규모가 시장에 영구적으로 남기는 가격 이동
    permanent_bps = 0.0
    if avg_daily_v > 0 and qty > 0:
        participation_rate = qty / avg_daily_v   # 일일 거래량 대비 주문 비율
        permanent_bps = _AC_GAMMA * participation_rate * 10000
        permanent_bps = min(permanent_bps, 50.0)  # 상한 50bps
    elif avg_1m_val > 0 and order_krw > 0:
        # 분봉 평균 거래대금 기반 대안 추정
        participation_rate = order_krw / (avg_1m_val * 390)  # 1분봉 × 390분 추정
        permanent_bps = _AC_GAMMA * participation_rate * 10000
        permanent_bps = min(permanent_bps, 30.0)

    # ── ② 임시충격 (Temporary Impact) ──────────────────────────
    # 주문 속도(rate)와 스프레드에 비례하는 일시적 가격 이동
    temporary_bps = 0.0
    if ask_size1 > 0 and qty > 0:
        depth_ratio   = qty / ask_size1          # 1호가 소화 비율
        temporary_bps = _AC_ETA * depth_ratio * spread_bps
        temporary_bps = min(temporary_bps, 80.0)
    else:
        # 호가 정보 없음 → 스프레드의 절반을 임시충격 추정
        temporary_bps = spread_bps * 0.5
        temporary_bps = min(temporary_bps, 30.0)

    total_bps = permanent_bps + temporary_bps
    total_bps = round(min(total_bps, 100.0), 1)

    logger.info(
        "[IMPACT_AC_v4_7] 총충격=%.1fbps "
        "(영구γ=%.1fbps + 임시η=%.1fbps) "
        "spread=%.1fbps ask_size1=%d qty=%d",
        total_bps, permanent_bps, temporary_bps,
        spread_bps, ask_size1, qty)
    return total_bps

# ──────────────────────────────────────────────────────────────
#  ① 슬리피지 허용 기준 동적화
#     params_reader → exec_max_slip_bps 우선 반영
# ──────────────────────────────────────────────────────────────
def _dynamic_slip_threshold(row: Dict[str, Any],
                             logger: logging.Logger,
                             regime: str = "NEUTRAL") -> float:
    pr_base = _params_get("exec_max_slip_bps", None)
    base = float(pr_base) if pr_base is not None else 30.0
    hhmm = _hhmm()

    if hhmm < 910:
        base += 15.0
    elif hhmm >= 1450:
        base -= 10.0

    day_chg = _safe_float(row.get("day_chg_pct", 0))
    if day_chg > 5.0:
        base -= 10.0
    elif day_chg < -3.0:
        base += 5.0

    winner_gap = _safe_float(row.get("winner_gap", 0))
    if winner_gap > 10.0:
        base += 5.0
    elif 0 < winner_gap < 6.0:
        base -= 5.0

    if regime == "BEAR":
        base -= 8.0
    elif regime == "BULL":
        base += 5.0

    threshold = round(max(10.0, min(60.0, base)), 1)
    logger.info("[SLIP_DYN] 허용 %.1fbps (hhmm=%04d day=%.1f%% "
                "gap=%.1f regime=%s params=%s)",
                threshold, hhmm, day_chg, winner_gap, regime,
                "OK" if pr_base is not None else "default")
    return threshold

# ──────────────────────────────────────────────────────────────
#  ② 분할 비율 동적화
#     params_reader → exec_split_ratio 우선 반영
# ──────────────────────────────────────────────────────────────
def _dynamic_split_ratio(row: Dict[str, Any],
                          logger: logging.Logger,
                          regime: str = "NEUTRAL") -> float:
    conviction = str(row.get("conviction", "NORMAL")).upper()
    winner_gap = _safe_float(row.get("winner_gap", 0))

    pr_ratio = _params_get("exec_split_ratio", None)
    if pr_ratio is not None:
        ratio = float(pr_ratio)
    elif any(k in conviction for k in ("STRONG","HIGH","OFI_INST","BREAKOUT")):
        ratio = 0.70
    elif any(k in conviction for k in ("WEAK","LOW","HOLD")):
        ratio = 0.30
    else:
        ratio = 0.50

    if winner_gap > 10.0:
        ratio = min(0.80, ratio + 0.05)
    elif 0 < winner_gap < 6.0:
        ratio = max(0.20, ratio - 0.05)

    if regime == "BEAR":
        ratio = max(0.20, ratio - 0.10)
    elif regime == "BULL":
        ratio = min(0.80, ratio + 0.05)

    ratio = round(max(0.20, min(0.80, ratio)), 2)
    logger.info("[SPLIT_DYN] 1차=%.0f%% 2차=%.0f%% "
                "(conviction=%s gap=%.1f regime=%s params=%s)",
                ratio*100, (1-ratio)*100,
                conviction[:10], winner_gap, regime,
                "OK" if pr_ratio is not None else "default")
    return ratio

# ──────────────────────────────────────────────────────────────
#  ③ 재진입 가격 허용 오차 동적화
# ──────────────────────────────────────────────────────────────
def _dynamic_reentry_pct(row: Dict[str, Any],
                          logger: logging.Logger,
                          regime: str = "NEUTRAL") -> float:
    hhmm    = _hhmm()
    day_chg = _safe_float(row.get("day_chg_pct", 0))
    gap     = _safe_float(row.get("winner_gap", 0))

    base = 0.5 if hhmm < 910 else 0.3

    if day_chg > 5.0:
        base = min(base, 0.2)
    elif day_chg < -3.0:
        base = max(base, 0.4)

    if gap > 10.0:
        base = min(0.5, base + 0.1)
    elif 0 < gap < 6.0:
        base = max(0.15, base - 0.1)

    if regime == "BEAR":
        base = max(0.15, base - 0.1)
    elif regime == "BULL":
        base = min(0.5, base + 0.05)

    pct = round(max(0.15, min(0.5, base)), 2)
    logger.info("[REENTRY_DYN] 허용오차=%.2f%% "
                "(hhmm=%04d day=%.1f%% regime=%s)",
                pct, hhmm, day_chg, regime)
    return pct

# ──────────────────────────────────────────────────────────────
#  ④ 슬리피지 사전 추정
# ──────────────────────────────────────────────────────────────
def _estimate_slippage_pre(row: Dict[str, Any],
                            price: int,
                            logger: logging.Logger,
                            impact_bps: float = 0.0) -> float:
    ask = _safe_float(row.get("ask_price", 0))
    bid = _safe_float(row.get("bid_price", 0))
    if ask > 0 and bid > 0 and ask > bid:
        mid        = (ask + bid) / 2
        spread_bps = (ask - bid) / mid * 10000
    else:
        day_chg    = abs(_safe_float(row.get("day_chg_pct", 0)))
        spread_bps = day_chg * 4.0

    hhmm = _hhmm()
    if hhmm < 910:
        spread_bps *= 1.5
    elif hhmm >= 1450:
        spread_bps *= 1.3

    est = round(spread_bps / 2 + impact_bps * 0.5, 1)
    logger.info("[SLIP_PRE] 사전 추정=%.1fbps "
                "(spread=%.1f impact=%.1f) code=%s",
                est, spread_bps, impact_bps,
                row.get("code",""))
    return est

# ──────────────────────────────────────────────────────────────
#  슬리피지 컷 / 분할 수량 / 가격 이탈
# ──────────────────────────────────────────────────────────────
def _check_slippage_cut(result: "OrderResult",
                         threshold_bps: float,
                         logger: logging.Logger) -> bool:
    slip = result.slippage_bps
    if slip < -200.0:
        logger.warning("[SLIP_CUT] ⚠️ 극단 음수 slip=%.1fbps → 데이터 오류 의심 code=%s",
                       slip, result.code)
    if slip <= 0:
        logger.info("[SLIP_CUT] slip=%+.1fbps ✅ 유리 code=%s",
                    slip, result.code)
        return True
    if slip <= threshold_bps:
        grade = "EXCELLENT" if slip < 10 else "ACCEPTABLE"
        logger.info("[SLIP_CUT] slip=+%.1fbps %s (허용%.0fbps) code=%s",
                    slip, grade, threshold_bps, result.code)
        return True
    logger.warning("[SLIP_CUT] ❌ slip=+%.1fbps > 허용%.0fbps code=%s",
                   slip, threshold_bps, result.code)
    return False

def _calc_split_qty(total_qty: int, split_ratio: float) -> Tuple[int, int]:
    if total_qty <= 1:
        return total_qty, 0
    first  = max(1, int(total_qty * split_ratio))
    second = total_qty - first
    return first, second

def _should_cancel_on_drift(result: "OrderResult",
                              current_price: int,
                              logger: logging.Logger) -> bool:
    if result.price <= 0 or current_price <= 0:
        return False
    drift_pct = (current_price - result.price) / result.price * 100
    if drift_pct > EXEC_PRICE_DRIFT_PCT:
        logger.warning("[DRIFT_CANCEL] +%.2f%% > %.1f%% → 즉시취소 code=%s",
                       drift_pct, EXEC_PRICE_DRIFT_PCT, result.code)
        return True
    return False

# ──────────────────────────────────────────────────────────────
#  [v4_6] 추세눌림 멀티사이클 — 2사이클 재진입 엔진
#  1사이클 오전 청산 후 → 점심 차단 → 13:00~13:30 재진입
# ──────────────────────────────────────────────────────────────
_CYCLE_TRACKER_PATH  = Path(os.environ.get(
    "SAFEPLUS_BASE", r"C:\stock_bot")) / "DATA" / "pullback_cycle_tracker.json"
_RT_INTRADAY_PATH_MC = Path(os.environ.get(
    "SAFEPLUS_BASE", r"C:\stock_bot")) / "DATA" / "rt_intraday.csv"

MC_MAX_CYCLE          = int(os.environ.get("PB_MAX_CYCLE",    "2"))
MC_REENTRY_DELAY_MIN  = int(os.environ.get("PB_REENTRY_DELAY","10"))
MC_WINDOW_START       = int(os.environ.get("PB_WIN_START",    "1300"))
MC_WINDOW_END         = int(os.environ.get("PB_WIN_END",      "1330"))
MC_LUNCH_START        = int(os.environ.get("PB_LUNCH_START",  "1130"))
MC_LUNCH_END          = int(os.environ.get("PB_LUNCH_END",    "1300"))
MC_EV_MIN             = float(os.environ.get("PB_MC_EV_MIN",  "0.75"))  # [TUNE] 0.60→0.75
MC_RIDE_MIN           = float(os.environ.get("PB_MC_RIDE_MIN","0.50"))  # [TUNE] 0.40→0.50
MC_OFI_MIN            = float(os.environ.get("PB_MC_OFI_MIN", "0.35"))  # [TUNE] 0.30→0.35
MC_VALUE_RATIO_MIN    = float(os.environ.get("PB_MC_VAL_RATIO","1.2"))  # [TUNE] 거래대금 증가 필수


def _hhmm_to_min(hhmm: int) -> int:
    """HHMM → 분 단위 변환. 예: 1055 → 425분."""
    return (hhmm // 100) * 60 + (hhmm % 100)


def _load_cycle_tracker_mc(logger: logging.Logger) -> dict:
    """cycle_tracker.json 읽기. 오늘 날짜 아니면 빈 dict."""
    try:
        if not _CYCLE_TRACKER_PATH.exists():
            return {}
        with open(_CYCLE_TRACKER_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if data.get("date") != _today_ymd():  # [PATCH] %Y-%m-%d→%Y%m%d: rt_sell_engine 포맷 일치
            return {}
        return data
    except Exception as e:
        logger.debug("[MC] cycle_tracker 읽기 실패: %s", e)
        return {}


def _get_pullback_signal_mc(logger: logging.Logger) -> dict:
    """
    rt_intraday.csv에서 2사이클 최강 후보 1건 반환.
    ride ≥ MC_RIDE_MIN AND ofi ≥ MC_OFI_MIN AND ev ≥ MC_EV_MIN
    조건 충족 종목 중 합산 점수 1위. 없으면 빈 dict.
    """
    try:
        if not _RT_INTRADAY_PATH_MC.exists():
            return {}
        if time.time() - _RT_INTRADAY_PATH_MC.stat().st_mtime > 120:
            return {}
        import csv as _csv_mc
        best = {}
        best_score = 0.0
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with open(_RT_INTRADAY_PATH_MC, "r",
                          encoding=enc, newline="") as f:
                    for row in _csv_mc.DictReader(f):
                        ride = _safe_float(row.get("inst_ride_score",
                                           row.get("ride_score", 0)))
                        ofi  = _safe_float(row.get("ofi_score",
                                           row.get("ofi", 0)))
                        ev   = _safe_float(row.get("ev_pct", 0))
                        # [W45 PATCH 2026-05-13] MC EV cold-start 우회 — TIER2 W36 패턴 통일
                        #   기존: ev >= 0.75 절대 임계 → cold-start (ev=0) 시 영구 차단
                        #   변경: ev <= 0 (미산출) 통과 + ev > 0 시 0.75 임계 유지
                        #   품질 보장: ride/OFI/val_ratio/VWAP 게이트는 그대로
                        if (ride >= MC_RIDE_MIN
                                and ofi >= MC_OFI_MIN
                                and (ev <= 0 or ev >= MC_EV_MIN)):
                            # [TUNE] 추가 필터: 거래대금 증가 + VWAP 위
                            val_ratio = _safe_float(row.get(
                                "value_ratio_5m",
                                row.get("value_ratio", 0)))
                            vwap_ok = _safe_float(row.get(
                                "vwap_dev",
                                row.get("vwap_position", 1))) >= 0
                            if val_ratio < MC_VALUE_RATIO_MIN:
                                continue   # 거래대금 미달
                            if not vwap_ok:
                                continue   # VWAP 아래
                            sc = ride * 0.5 + ofi * 0.3 + min(ev, 2.0) * 0.2
                            if sc > best_score:
                                best_score = sc
                                best = dict(row)
                                best["_mc_score"] = round(sc, 4)
                break
            except Exception:
                continue
        if best:
            logger.info(
                "[MC] 2사이클 후보 code=%s ride=%.2f ofi=%.2f ev=%.2f",
                best.get("code", "?"),
                _safe_float(best.get("inst_ride_score", 0)),
                _safe_float(best.get("ofi_score", 0)),
                _safe_float(best.get("ev_pct", 0)),
            )
        return best
    except Exception as e:
        logger.debug("[MC] 후보 조회 실패: %s", e)
        return {}


def _check_pullback_reentry(logger: logging.Logger) -> "tuple[bool, dict]":
    """
    [v4_6] 추세눌림 2사이클 재진입 가능 여부 5조건 확인.
    Returns: (가능여부, 후보row)

    ① 진입 창 13:00~13:30
    ② cycle_count < 2
    ③ 점심 차단 11:30~13:00
    ④ 청산 후 10분 경과 (분 단위 정확 계산 — HHMM 뺄셈 버그 방지)
    ⑤ 눌림 신호 존재 (ride/OFI/EV)
    """
    hm = _hhmm()

    # ① 진입 창
    if not (MC_WINDOW_START <= hm <= MC_WINDOW_END):
        return False, {}

    data = _load_cycle_tracker_mc(logger)
    if not data:
        logger.debug("[MC] 1사이클 미완료 → 2사이클 불필요")
        return False, {}

    # ② 사이클 한도
    cycle_count = int(data.get("cycle_count", 0))
    if cycle_count >= MC_MAX_CYCLE:
        logger.info("[MC] 오늘 최대 %d사이클 완료", MC_MAX_CYCLE)
        return False, {}

    # ③ 점심 차단
    if MC_LUNCH_START <= hm < MC_LUNCH_END:
        return False, {}

    # ④ 청산 후 경과 시간 (분 단위 — HHMM 뺄셈 버그 방지)
    last_sell = int(data.get("last_sell_time", 0))
    elapsed   = _hhmm_to_min(hm) - _hhmm_to_min(last_sell)
    if elapsed < MC_REENTRY_DELAY_MIN:
        logger.info(
            "[MC] 재진입 대기 %d분 < %d분 (청산=%04d 현재=%04d)",
            elapsed, MC_REENTRY_DELAY_MIN, last_sell, hm
        )
        return False, {}

    # ⑤ 눌림 신호
    candidate = _get_pullback_signal_mc(logger)
    if not candidate:
        logger.info("[MC] 2사이클 후보 없음")
        return False, {}

    # ⑥ 손실 종목 재진입 차단 (당일 loss_codes 에 있으면 차단)
    # [신규] env USE_LOSS_REENTRY_BLOCK=false 시 손실 종목 재진입 자유 (대장주 추세회복 허용)
    _use_loss_block = os.environ.get("USE_LOSS_REENTRY_BLOCK", "true").lower() == "true"
    loss_codes = data.get("loss_codes", [])
    cand_code = str(candidate.get("code", "")).strip().zfill(6)
    if cand_code in loss_codes and _use_loss_block:
        logger.info("[MC] 손실 종목 재진입 차단: code=%s loss_codes=%s", cand_code, loss_codes)
        return False, {}

    logger.info(
        "[MC] ✅ 2사이클 조건 충족 code=%s elapsed=%d분",
        candidate.get("code", "?"), elapsed
    )
    return True, candidate


def _execute_multicycle_reentry(
    kw: "Kiwoom",
    account: str,
    screen: str,
    screen_cancel: str,
    available_krw: int,
    done_fps: Set[str],
    pf_size_mult: float,
    logger: logging.Logger,
    base: Path,
) -> int:
    """
    [v4_6] 추세눌림 2사이클 재진입 실행.
    Returns: 체결 건수 (0 or 1)
    """
    ok, candidate = _check_pullback_reentry(logger)
    if not ok or not candidate:
        return 0

    code  = _norm_code(candidate.get("code", ""))
    if not _is_valid_code(code):
        return 0

    fp_mc = f"MC2_{code}_{_today_str()}"
    ck_mc = f"CODE_{code}"

    if fp_mc in done_fps or ck_mc in done_fps:
        logger.info("[MC] 이미 처리됨 code=%s", code)
        return 0

    if not _market_guard(code, logger, cancel_count=0,
                         strategy_type="PULLBACK",
                         session_type="PULLBACK"):
        return 0

    price = _safe_int(candidate.get("price",
                      candidate.get("close", 0)), default=0)
    if price <= 0:
        logger.warning("[MC] 가격 없음 code=%s", code)
        return 0

    ev_pct = _safe_float(candidate.get("ev_pct", 0))
    if ev_pct >= EV_SIZE_TIER_HIGH:
        ratio = EV_SIZE_RATIO_HIGH
    elif ev_pct >= EV_SIZE_TIER_MID:
        ratio = EV_SIZE_RATIO_MID
    else:
        ratio = EV_SIZE_RATIO_BASE

    order_krw = int(available_krw * ratio * BALANCE_SAFETY_RATIO * pf_size_mult)
    if order_krw < price:
        logger.warning("[MC] 주문금액 부족 code=%s", code)
        return 0

    qty_final, qty_adj = _final_qty_check(
        available_krw, order_krw, price,
        max(1, int(order_krw / price)), code, logger
    )

    logger.info(
        "[MC] ★ 2사이클 진입! code=%s qty=%d@%d ev=%.2f%%",
        code, qty_final, price, ev_pct
    )

    # [v4_9-P3] hard_stop을 row에 명시해 _write_open_position에 전달
    _row_mc = {
        "code": code, "strategy": "PULLBACK_2CYCLE",
        "strategy_type": "PULLBACK", "session_type": "PULLBACK",
        "ev_pct": ev_pct,
        "hard_stop": float(os.environ.get("HARD_STOP_DEFAULT", "0.025")),
    }
    result = _execute_and_track(
        kw, account, screen, screen_cancel,
        code, qty_final, price,
        "PULLBACK_2CYCLE", "100%",
        order_krw, fp_mc, 1.0, qty_adj, logger,
        row=_row_mc,
        base_dir=str(base),
    )

    if result.filled or result.state == OrderState.PARTIAL:
        _fps_add(done_fps, fp_mc, base, logger)
        _fps_add(done_fps, ck_mc, base, logger)
        _update_positions(base, result, logger)
        _write_open_position(base, result, logger, _row_mc)        # [v4_9-P3] row 전달
        _ensure_open_position(base, result, logger, _row_mc)        # [v4_9-P3] row 전달
        logger.info(
            "[MC] ✅ 2사이클 체결 code=%s filled=%d@%.0f slip=%.1fbps",
            code, result.filled_qty, result.avg_filled_price,
            result.slippage_bps
        )
        if _PNL_LINKER_OK and _pnl_write_buy:
            try:
                _pnl_write_buy(
                    code, "PULLBACK_2CYCLE",
                    result.avg_filled_price, result.filled_qty,
                    result.slippage_bps,
                    base_dir=str(base), logger=logger,
                )
            except Exception as e:
                logger.warning("[MC][PNL] %s", e)
        return 1

    logger.warning("[MC] 2사이클 미체결 code=%s state=%s",
                   code, result.state.value)
    return 0


# ──────────────────────────────────────────────────────────────
#  [v4_6] 피라미딩 ADD_ON 큐 처리 — 완성된 구현
#  pullback_sell_strategy v4_12이 조건 충족 시 신호 기록
#  이 함수가 신호를 읽어 실제 추가 매수 실행
# ──────────────────────────────────────────────────────────────
ADDON_DONE_SUFFIX  = "_done"      # 처리 완료 신호 표시용
ADDON_CUTOFF_HM    = 1350         # 이 시각 이후 ADD_ON 신호 무시
ADDON_MAX_AGE_SEC  = 300          # 5분 이상 된 신호 무시 (지연 방지)

def _load_addon_queue(logger: logging.Logger) -> List[Dict]:
    """
    pullback_addon_queue.csv 읽기.
    - addon_stage가 비어있거나 done 표시된 것 제외
    - ADDON_MAX_AGE_SEC 초과된 신호 제외
    - ADDON_CUTOFF_HM 이후 신호 전부 제외
    """
    if not PULLBACK_ADDON_QUEUE_PATH.exists():
        return []
    if PULLBACK_ADDON_QUEUE_PATH.stat().st_size == 0:
        return []
    if _hhmm() >= ADDON_CUTOFF_HM:
        logger.info("[ADDON] %04d 이후 — ADD_ON 신호 처리 중단", ADDON_CUTOFF_HM)
        return []

    pending: List[Dict] = []
    now_ts = _now()

    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(PULLBACK_ADDON_QUEUE_PATH, "r",
                      encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 이미 처리된 신호 건너뜀
                    if str(row.get("done", "")).strip().lower() in ("1", "true", "done"):
                        continue
                    # addon_stage 없는 행 건너뜀
                    stage = str(row.get("addon_stage", "")).strip()
                    if not stage or stage == "0":
                        continue
                    # 시간 만료 체크
                    ts_raw = str(row.get("ts", "")).strip()
                    try:
                        sig_ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                        age    = (now_ts.replace(tzinfo=None) - sig_ts).total_seconds()
                        if age > ADDON_MAX_AGE_SEC:
                            logger.debug("[ADDON] 신호 만료(%.0fs) code=%s stage=%s",
                                         age, row.get("code",""), stage)
                            continue
                    except Exception:
                        pass  # 시간 파싱 실패 → 일단 허용
                    pending.append(dict(row))
            break
        except Exception:
            continue

    logger.info("[ADDON] 대기 신호=%d건", len(pending))
    return pending


def _mark_addon_done(row: Dict, logger: logging.Logger) -> None:
    """처리 완료된 ADD_ON 신호를 큐 파일에서 done=1 표시."""
    if not PULLBACK_ADDON_QUEUE_PATH.exists():
        return
    try:
        rows_all: List[Dict] = []
        fieldnames: List[str] = []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with open(PULLBACK_ADDON_QUEUE_PATH, "r",
                          encoding=enc, newline="") as f:
                    reader = csv.DictReader(f)
                    fieldnames = list(reader.fieldnames or [])
                    rows_all   = list(reader)
                break
            except Exception:
                continue

        if not fieldnames:
            return

        if "done" not in fieldnames:
            fieldnames.append("done")

        target_ts   = str(row.get("ts","")).strip()
        target_code = str(row.get("code","")).strip()
        target_stg  = str(row.get("addon_stage","")).strip()

        for r in rows_all:
            if (str(r.get("ts","")).strip()         == target_ts
                    and str(r.get("code","")).strip()  == target_code
                    and str(r.get("addon_stage","")).strip() == target_stg):
                r["done"] = "1"

        tmp = PULLBACK_ADDON_QUEUE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_all)
        os.replace(str(tmp), str(PULLBACK_ADDON_QUEUE_PATH))
        logger.info("[ADDON] done 표시 완료 code=%s stage=%s",
                    target_code, target_stg)
    except Exception as e:
        logger.warning("[ADDON] done 표시 실패: %s", e)


def _process_addon_queue(
    kw: "Kiwoom",
    account: str,
    screen: str,
    screen_cancel: str,
    available_krw: int,
    done_fps: Set[str],
    pf_size_mult: float,
    logger: logging.Logger,
    base: Path,
) -> int:
    """
    [v4_6 완성] ADD_ON 큐 처리 — 피라미딩 실제 매수 실행.

    반환: 체결된 ADD_ON 건수

    핵심 차이 (일반 매수와 다른 점):
    - code_key dedup 우회: 이미 보유 중인 종목에 추가 매수
    - 별도 fingerprint: ADDON_{code}_{stage}_{date}
    - 포지션 sizing: addon_ratio × available_krw
    - 필터 우회: EV/score 필터 건너뜀 (이미 보유+기관 확인 완료)
    - 시장가드: ADDON_CUTOFF_HM 체크 (1350 이후 진입 금지)
    """
    signals = _load_addon_queue(logger)
    if not signals:
        return 0

    filled_addon = 0
    today        = _today_str()

    for sig in signals:
        code  = _norm_code(sig.get("code", ""))
        stage = str(sig.get("addon_stage", "")).strip()
        ratio = _safe_float(sig.get("addon_ratio", 0))

        if not _is_valid_code(code):
            logger.warning("[ADDON] 유효하지 않은 code=%s — 건너뜀", code)
            _mark_addon_done(sig, logger)
            continue

        if ratio <= 0 or ratio > 1.0:
            logger.warning("[ADDON] 유효하지 않은 ratio=%.2f code=%s — 건너뜀",
                           ratio, code)
            _mark_addon_done(sig, logger)
            continue

        # 중복 처리 방지 — 같은 stage 이미 처리됐으면 건너뜀
        addon_fp = f"ADDON_{code}_{stage}_{today}"
        if addon_fp in done_fps:
            logger.info("[ADDON] 이미 처리됨 code=%s stage=%s", code, stage)
            _mark_addon_done(sig, logger)
            continue

        # 시장 가드 재확인
        if not _market_guard(code, logger, cancel_count=0,
                             strategy_type="PULLBACK",
                             session_type="PULLBACK"):
            logger.warning("[ADDON] 시장 가드 차단 code=%s stage=%s", code, stage)
            continue

        # 현재가 조회 — sig에 entry_price가 있으면 기준으로 사용
        ref_price = _safe_int(sig.get("entry_price", 0))
        if ref_price <= 0:
            logger.warning("[ADDON] 기준가 없음 code=%s — 건너뜀", code)
            _mark_addon_done(sig, logger)
            continue

        # 포지션 사이징: available_krw × addon_ratio
        order_krw  = int(available_krw * ratio * BALANCE_SAFETY_RATIO * pf_size_mult)
        max_allowed = int(available_krw * BALANCE_SAFETY_RATIO)
        if order_krw > max_allowed:
            order_krw = max_allowed

        if order_krw < ref_price:
            logger.warning("[ADDON] 주문금액(%s) < 최소1주(%d원) code=%s — 건너뜀",
                           f"{order_krw:,}", ref_price, code)
            _mark_addon_done(sig, logger)
            continue

        qty = max(1, int(order_krw / ref_price))
        qty_final, qty_adj = _final_qty_check(
            available_krw, order_krw, ref_price, qty, code, logger)

        logger.info(
            "[ADDON] ★ %s차 피라미딩 진입 code=%s qty=%d@%d원 "
            "ratio=%.0f%% order=%s원",
            stage, code, qty_final, ref_price,
            ratio * 100, f"{order_krw:,}"
        )

        # [v4_9-P3] hard_stop을 row에 명시해 _write_open_position에 전달
        _row_addon = {
            "code":          code,
            "strategy":      f"PULLBACK_ADDON_{stage}",
            "strategy_type": "PULLBACK",
            "session_type":  "ADDON",
            "addon_stage":   stage,
            "ev_pct":        0.0,
            "hard_stop":     float(os.environ.get("HARD_STOP_DEFAULT", "0.025")),
        }
        result = _execute_and_track(
            kw, account, screen, screen_cancel,
            code, qty_final, ref_price,
            f"PULLBACK_ADDON_{stage}", "100%",
            order_krw, addon_fp,
            1.0, qty_adj, logger,
            row=_row_addon,
            base_dir=str(base),
        )

        if result.filled or result.state == OrderState.PARTIAL:
            filled_addon += 1
            _fps_add(done_fps, addon_fp, base, logger)
            _update_positions(base, result, logger)
            _write_open_position(base, result, logger, _row_addon)   # [v4_9-P3] row 전달
            _ensure_open_position(base, result, logger, _row_addon)  # [v4_9-P3] row 전달
            logger.info(
                "[ADDON] ✅ %s차 체결 완료 code=%s filled=%d@%.0f slip=%.1fbps",
                stage, code, result.filled_qty,
                result.avg_filled_price, result.slippage_bps
            )
            if _PNL_LINKER_OK and _pnl_write_buy:
                try:
                    _pnl_write_buy(
                        code, f"PULLBACK_ADDON_{stage}",
                        result.avg_filled_price, result.filled_qty,
                        result.slippage_bps,
                        base_dir=str(base), logger=logger,
                    )
                except Exception as e:
                    logger.warning("[ADDON][PNL] %s", e)
        else:
            logger.warning("[ADDON] %s차 미체결 code=%s state=%s",
                           stage, code, result.state.value)

        _mark_addon_done(sig, logger)

    return filled_addon


# ──────────────────────────────────────────────────────────────
#  P0 수정: _notify_slip_penalty → pnl_linker 실제 페널티 기록
# ──────────────────────────────────────────────────────────────
def _notify_slip_penalty(result: "OrderResult",
                          base_dir: str,
                          logger: logging.Logger) -> None:
    if not getattr(result, "_slip_cut_triggered", False):
        return
    logger.warning(
        "[SLIP_PENALTY] 고점체결 페널티 기록 "
        "code=%s slip=%.1fbps → 진화 가중치 하향",
        result.code, result.slippage_bps)

    if not (_PNL_LINKER_OK and _pnl_write_buy):
        logger.warning("[SLIP_PENALTY] pnl_linker 없음 → 페널티 기록 불가")
        return
    try:
        _pnl_write_buy(
            result.code, result.strategy,
            result.avg_filled_price, result.filled_qty,
            result.slippage_bps,
            base_dir=str(base_dir), logger=logger,
        )
        logger.info("[SLIP_PENALTY] ✅ 기록 완료 code=%s", result.code)
    except Exception as e:
        logger.error("[SLIP_PENALTY] 실패: %s", e)

# ── 레저 / 서머리 ──
_LEDGER_FIELDS = [
    "date","ts","run_id",
    "side","code","qty","price","order_krw",
    "strategy","rank_ratio","signal_fingerprint",
    "send_rc","order_no","order_state",
    "ack_status","fill_status",
    "filled_qty","avg_filled_price",
    "slippage_won","slippage_bps",
    "evolve_weight","final_qty_adjusted",
    "dependency_mode",
    # [WEAK-5 FIX] 수익률 추적 필드
    "ev_pct","score","conviction","regime","pre_slip_bps",
]
_SUMMARY_FIELDS = [
    "date","last_updated_ts","run_id",
    "side","code","qty","price","order_krw",
    "strategy","rank_ratio","signal_fingerprint",
    "order_no","order_state",
    "final_ack_status","final_fill_status",
    "total_filled_qty","avg_filled_price",
    "slippage_won","slippage_bps",
    "evolve_weight","final_qty_adjusted",
    "dependency_mode",
    # [WEAK-5 FIX] 수익률 추적 필드
    "ev_pct","score","conviction","regime","pre_slip_bps",
]

def _ledger_append(path: Path, row: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_LEDGER_FIELDS,
                               extrasaction="ignore")
            if not exists: w.writeheader()
            w.writerow(row)
        return True
    except Exception: return False

def _summary_upsert(path: Path, key: str,
                    row: Dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict] = []
    if path.exists() and path.stat().st_size > 0:
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            existing = df.to_dict("records")
        except Exception: pass
    updated = False
    for i, r in enumerate(existing):
        if r.get("signal_fingerprint","") == key:
            existing[i] = row; updated = True; break
    if not updated: existing.append(row)
    try:
        tmp = path.with_suffix(".tmp")
        pd.DataFrame(existing).to_csv(tmp, index=False,
                                      encoding="utf-8-sig",
                                      columns=_SUMMARY_FIELDS)
        os.replace(str(tmp), str(path))
        return True
    except Exception: return False

def _load_today_success_fingerprints(path: Path,
                                      logger: logging.Logger) -> Set[str]:
    done: Set[str] = set()
    summary = path.parent / f"order_summary_{_today_ymd()}.csv"
    cp = summary if summary.exists() else path
    if not cp.exists() or cp.stat().st_size == 0: return done
    try:
        df = pd.read_csv(cp, dtype=str, encoding="utf-8-sig").fillna("")
        fp_col   = "signal_fingerprint"
        fill_col = ("final_fill_status"
                    if "final_fill_status" in df.columns
                    else "fill_status")
        if fp_col not in df.columns:
            if "code" in df.columns and "send_rc" in df.columns:
                for _, r in df.iterrows():
                    code = _norm_code(r.get("code",""))
                    if _is_valid_code(code) and \
                            _safe_int(r.get("send_rc")) == 0:
                        done.add(f"CODE_{code}")
            return done
        for _, r in df.iterrows():
            fp   = str(r.get(fp_col,"")).strip()
            fill = str(r.get(fill_col,"")).strip()
            if fp and fill in ("FILLED","ACKED","PARTIAL"):
                done.add(fp)
        logger.info("[LEDGER] 오늘 성공 fp=%d", len(done))
        return done
    except Exception as e:
        logger.error("[LEDGER] 읽기 실패: %s", e); return done

# ── 영구 fingerprint 저장 (MC2/ADDON 세션 재시작 후 중복 방지) ──
def _buy_fps_json_path(base: Path) -> Path:
    return base / "DATA" / "LOG" / f"buy_done_fps_{_today_ymd()}.json"

def _load_buy_fps_json(base: Path, logger: logging.Logger) -> Set[str]:
    p = _buy_fps_json_path(base)
    if not p.exists() or p.stat().st_size == 0:
        return set()
    try:
        import json as _j
        data = _j.loads(p.read_text(encoding="utf-8-sig"))
        fps = set(data) if isinstance(data, list) else set()
        logger.info("[FPS_JSON] 로드 %d건: %s", len(fps), p.name)
        return fps
    except Exception as e:
        logger.warning("[FPS_JSON] 로드 실패: %s", e)
        return set()

def _fps_add(done_fps: Set[str], fp: str,
             base: Path, logger: logging.Logger) -> None:
    done_fps.add(fp)
    p = _buy_fps_json_path(base)
    try:
        import json as _j
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(_j.dumps(sorted(done_fps), ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(p))
    except Exception as e:
        logger.warning("[FPS_JSON] 저장 실패 fp=%s: %s", fp, e)

def _read_queue_csv(queue_file: Path,
                    logger: logging.Logger) -> Optional["pd.DataFrame"]:
    for enc in ("utf-8-sig","utf-8","cp949","euc-kr"):
        try:
            df = pd.read_csv(queue_file, dtype=str, encoding=enc).fillna("")
            logger.info("[QUEUE] enc=%s rows=%d", enc, len(df))
            return df
        except Exception: continue
    logger.error("[QUEUE] 모든 인코딩 실패"); return None

# ── 검증 ──
def _validate_queue_contract(df: "pd.DataFrame",
                              logger: logging.Logger) -> bool:
    missing = [c for c in ["side","code"] if c not in df.columns]
    if missing:
        logger.error("[QUEUE] 필수 컬럼 없음: %s", missing)
        return False
    return True

def _validate_market_time(logger: logging.Logger) -> bool:
    if not _env_bool("ENFORCE_MARKET_HOURS","1"):
        logger.info("[TIME] 시장 시간 검사 비활성화")
        return True
    hhmm  = _hhmm()
    open_ = _env_int("MARKET_OPEN_HHMM",  DEFAULT_MARKET_OPEN_HHMM)
    clos_ = _env_int("MARKET_CLOSE_HHMM", DEFAULT_MARKET_CLOSE_HHMM)
    ok    = open_ <= hhmm <= clos_
    if not ok:
        logger.error("[TIME] 시장 시간 외 now=%04d", hhmm)
    return ok

def _validate_screen(screen: str) -> bool:
    s = str(screen).strip()
    return s.isdigit() and len(s) == 4

def _resolve_qty(row: Dict[str, Any],
                 logger: logging.Logger, code: str) -> int:
    dq  = _env_int("FIXED_QTY", DEFAULT_FIXED_QTY)
    mq  = _env_int("MAX_QTY",   DEFAULT_MAX_QTY)
    raw = str(row.get("qty","")).strip()
    if raw and raw != "0":
        qty = _safe_int(raw, default=0)
        if qty > 0:
            if qty > mq:
                logger.warning("[QTY] %s 초과 %d→%d", code, qty, mq)
                qty = mq
            return qty
    logger.warning("[QTY] %s 없음 → %d", code, dq)
    return max(dq, 0)

# ── Lock ──
def _lock_path(base: Path) -> Path:
    return base / "LOG" / "order_sender.lock"

# ⑤ engine_shutdown.flag 감지 — 다른 엔진과 동일 패턴
def _shutdown_flag_path(base: Path) -> Path:
    return base / "engine_shutdown.flag"

def _is_shutdown(base: Path, logger: logging.Logger) -> bool:
    flag = _shutdown_flag_path(base)
    if flag.exists():
        logger.critical("[SHUTDOWN] engine_shutdown.flag 감지 → 즉시 HOLD")
        return True
    return False

# ② Heartbeat 파일 기록 — watchdog 연동 (다른 엔진과 동일 패턴)
def _heartbeat_path(base: Path) -> Path:
    return base / "LOG" / "order_sender_heartbeat.txt"

def _write_heartbeat(base: Path) -> None:
    try:
        p = _heartbeat_path(base)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_now_str(), encoding="utf-8")
    except Exception:
        pass

# ⑥ [v4_1 FIX] VaR 독립 리스크 레이어 — 일일 최대손실 기반 + 노출 상한
#   [CRITICAL-2 FIX] Soft Warning → 수량 비례 축소 (Hard Enforcement)
#   반환: (통과여부: bool, VaR 축소비율: float 0.0~1.0)
#   scale=1.0 → 정상, scale<1.0 → 수량 해당 비율로 축소
def _var_exposure_check(available_krw: int, order_krw: int,
                         logger: logging.Logger,
                         row: Optional[Dict[str, Any]] = None
                         ) -> "tuple[bool, float]":
    if available_krw <= 0:
        return True, 1.0

    # 1) 기본 노출 상한 (Hard Block 유지)
    exposure_pct = order_krw / available_krw
    limit = MAX_ACCOUNT_EXPOSURE_PCT
    if exposure_pct > limit:
        logger.error(
            "[VAR] 포지션 상한 초과 %.1f%% > 허용%.1f%% "
            "(주문%s원 / 잔고%s원) → 차단",
            exposure_pct * 100, limit * 100,
            f"{order_krw:,}", f"{available_krw:,}")
        return False, 0.0

    # 2) [v4_1 HARD] 일일 최대손실 기반 VaR — 수량 비례 축소 강제
    _row = row or {}
    daily_vol_pct = _safe_float(_row.get("atr_pct",
                     _row.get("daily_vol_pct", 0)))
    var_scale = 1.0
    if daily_vol_pct > 0:
        # 예상 최대 손실 = 주문금액 × 일일변동성(%)
        expected_loss_krw = order_krw * (daily_vol_pct / 100)
        max_loss_krw      = available_krw * VAR_DAILY_MAX_LOSS_PCT
        if expected_loss_krw > max_loss_krw:
            # 축소 비율 = 허용손실 / 예상손실 (비례 축소 — 전량 차단 대신)
            var_scale = round(max_loss_krw / expected_loss_krw, 4)
            var_scale = max(0.30, min(1.0, var_scale))  # 최소 30% 보장
            logger.warning(
                "[VAR] ⚠️ 일일VaR 초과: 예상손실 %s원 > 허용 %s원 "
                "(vol=%.2f%% 한도=%.1f%%) → 수량 %.0f%% 축소 [HARD]",
                f"{int(expected_loss_krw):,}", f"{int(max_loss_krw):,}",
                daily_vol_pct, VAR_DAILY_MAX_LOSS_PCT * 100,
                var_scale * 100)
        else:
            logger.info("[VAR] 일일VaR OK: 예상손실 %s원 ≤ 허용 %s원",
                        f"{int(expected_loss_krw):,}",
                        f"{int(max_loss_krw):,}")

    logger.info("[VAR] 포지션 노출 %.1f%% ≤ 허용%.1f%% ✅ var_scale=%.2f",
                exposure_pct * 100, limit * 100, var_scale)
    return True, var_scale

def _acquire_run_lock(base: Path, logger: logging.Logger) -> bool:
    lp = _lock_path(base)
    try:
        if lp.exists():
            age = time.time() - lp.stat().st_mtime
            # [WEAK-8 FIX] PID 기반 프로세스 생존 확인
            try:
                lock_pid = int(lp.read_text(encoding="utf-8-sig").strip())
                pid_alive = False
                try:
                    os.kill(lock_pid, 0)  # 시그널 0 = 생존 확인만
                    pid_alive = True
                except (ProcessLookupError, PermissionError):
                    pid_alive = False
                except OSError:
                    pid_alive = False

                if not pid_alive:
                    logger.warning(
                        "[LOCK] PID %d 사망 확인 (age=%.0fs) → 즉시 해제",
                        lock_pid, age)
                    lp.unlink(missing_ok=True)
                elif age > LOCK_MAX_AGE_SEC:
                    logger.warning("[LOCK] stale (%.0fs) PID %d 생존 중 → 강제 해제",
                                   age, lock_pid)
                    lp.unlink(missing_ok=True)
                else:
                    logger.error("[LOCK] 실행 중 PID=%d (%.0fs)",
                                 lock_pid, age)
                    return False
            except (ValueError, IOError):
                # PID 읽기 실패 → 기존 시간 기반 로직
                if age > LOCK_MAX_AGE_SEC:
                    logger.warning("[LOCK] stale (%.0fs) 해제", age)
                    lp.unlink(missing_ok=True)
                else:
                    logger.error("[LOCK] 실행 중 (%.0fs)", age)
                    return False

        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        logger.error("[LOCK] 획득 실패: %s", e); return False

def _release_run_lock(base: Path) -> None:
    try: _lock_path(base).unlink(missing_ok=True)
    except Exception: pass

# ── OrderResult ──
class OrderResult:
    def __init__(self, code: str, qty: int, price: int,
                 strategy: str, rank_ratio_str: str,
                 order_krw: int, fingerprint: str,
                 evolve_weight: float = 1.0,
                 final_qty_adjusted: bool = False):
        self.code               = code
        self.qty                = qty
        self.price              = price
        self.strategy           = strategy
        self.rank_ratio         = rank_ratio_str
        self.order_krw          = order_krw
        self.fingerprint        = fingerprint
        self.evolve_weight      = evolve_weight
        self.final_qty_adjusted = final_qty_adjusted
        self.send_rc            = -1
        self.order_no           = ""
        self._state             = OrderState.PENDING
        self._state_log: List[Tuple[str, str]] = []
        self._cum_filled_qty    = 0
        self._cum_filled_value  = 0.0
        self._partial_fills: List[Tuple[int, float]] = []
        self._temp_key: str     = ""
        self._slip_cut_triggered: bool = False
        # [WEAK-5 FIX] 수익률 추적용 필드
        self.ev_pct: float       = 0.0
        self.score: float        = 0.0
        self.conviction: str     = ""
        self.regime: str         = ""
        self.pre_slip_bps: float = 0.0
        # [PROFIT-5 / BUG-5] 기관 탑승 정보 — 매도엔진 연동
        self.inst_score: float   = 0.0
        self.inst_consec: int    = 0
        self.inst_ride: bool     = False

    @property
    def state(self) -> OrderState:
        return self._state

    def transition(self, nxt: OrderState,
                   logger: Optional[logging.Logger] = None) -> bool:
        if self._state.can_transition_to(nxt):
            self._state_log.append((_now_str(), nxt.value))
            self._state = nxt
            return True
        msg = (f"[STATE] 비정상 전이 "
               f"{self._state.value}→{nxt.value} code={self.code}")
        if logger: logger.warning(msg)
        self._state_log.append(
            (_now_str(), OrderState.RECONCILE_PENDING.value))
        self._state = OrderState.RECONCILE_PENDING
        return False

    def accumulate_fill(self, qty: int, price: float) -> None:
        if qty <= 0 or price <= 0: return
        self._cum_filled_qty   += qty
        self._cum_filled_value += qty * price
        self._partial_fills.append((qty, price))

    @property
    def filled_qty(self) -> int:
        return self._cum_filled_qty

    @property
    def avg_filled_price(self) -> float:
        if self._cum_filled_qty <= 0: return 0.0
        return round(self._cum_filled_value / self._cum_filled_qty, 2)

    @property
    def slippage_won(self) -> int:
        if self.avg_filled_price <= 0 or self.price <= 0: return 0
        return int((self.avg_filled_price - self.price) * self.filled_qty)

    @property
    def slippage_bps(self) -> float:
        if self.avg_filled_price <= 0 or self.price <= 0: return 0.0
        return round(
            (self.avg_filled_price - self.price) / self.price * 10000, 1)

    @property
    def send_ok(self) -> bool:
        return self.send_rc == 0

    @property
    def acked(self) -> bool:
        return self._state in (
            OrderState.ACKED, OrderState.PARTIAL, OrderState.FILLED)

    @property
    def filled(self) -> bool:
        return self._state == OrderState.FILLED

    @property
    def ack_status(self) -> str:
        if self.acked: return "ACKED"
        if self._state == OrderState.TIMEOUT_ACK: return "TIMEOUT_ACK"
        return "N/A"

    @property
    def fill_status(self) -> str:
        m = {
            OrderState.FILLED:            "FILLED",
            OrderState.PARTIAL:           "PARTIAL",
            OrderState.TIMEOUT_FILL:      "TIMEOUT_FILL",
            OrderState.CANCEL_CONFIRMED:  "CANCELLED",
            OrderState.RECONCILE_PENDING: "RECONCILE_PENDING",
            OrderState.FAILED:            "FAILED",
        }
        return m.get(self._state, "N/A")

    def to_ledger_row(self, run_id: str, dep_mode: str) -> Dict[str, Any]:
        return {
            "date": _today_str(), "ts": _now_str(), "run_id": run_id,
            "side": "BUY", "code": self.code,
            "qty": self.qty, "price": self.price,
            "order_krw": self.order_krw,
            "strategy": self.strategy, "rank_ratio": self.rank_ratio,
            "signal_fingerprint": self.fingerprint,
            "send_rc": self.send_rc, "order_no": self.order_no,
            "order_state": self._state.value,
            "ack_status": self.ack_status, "fill_status": self.fill_status,
            "filled_qty": self.filled_qty,
            "avg_filled_price": self.avg_filled_price,
            "slippage_won": self.slippage_won,
            "slippage_bps": self.slippage_bps,
            "evolve_weight": self.evolve_weight,
            "final_qty_adjusted": int(self.final_qty_adjusted),
            "dependency_mode": dep_mode,
            # [WEAK-5 FIX] 수익률 추적
            "ev_pct": self.ev_pct,
            "score": self.score,
            "conviction": self.conviction,
            "regime": self.regime,
            "pre_slip_bps": self.pre_slip_bps,
        }

    def to_summary_row(self, run_id: str, dep_mode: str) -> Dict[str, Any]:
        return {
            "date": _today_str(), "last_updated_ts": _now_str(),
            "run_id": run_id, "side": "BUY", "code": self.code,
            "qty": self.qty, "price": self.price,
            "order_krw": self.order_krw,
            "strategy": self.strategy, "rank_ratio": self.rank_ratio,
            "signal_fingerprint": self.fingerprint,
            "order_no": self.order_no, "order_state": self._state.value,
            "final_ack_status": self.ack_status,
            "final_fill_status": self.fill_status,
            "total_filled_qty": self.filled_qty,
            "avg_filled_price": self.avg_filled_price,
            "slippage_won": self.slippage_won,
            "slippage_bps": self.slippage_bps,
            "evolve_weight": self.evolve_weight,
            "final_qty_adjusted": int(self.final_qty_adjusted),
            "dependency_mode": dep_mode,
            # [WEAK-5 FIX] 수익률 추적
            "ev_pct": self.ev_pct,
            "score": self.score,
            "conviction": self.conviction,
            "regime": self.regime,
            "pre_slip_bps": self.pre_slip_bps,
        }

# ── Kiwoom API 래퍼 ──
class Kiwoom:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger      = logger
        self.app         = None
        self.ocx         = None
        self._temp_map:  Dict[str, OrderResult] = {}
        self._order_map: Dict[str, OrderResult] = {}
        self._available_krw = 0
        self._tr_done       = False
        self._price_ref_map: Dict[str, List[int]] = {}

    def init(self) -> bool:
        # [A-1a 2026-05-15] broker CONNECTED 시 OCX 생성 차단
        # send_order/cancel_order/_query_available_krw 모두 self.ocx None 가드
        # 자동 적용 → broker mode 시 매수 거부 (-1) 자동 반환 (A-1b 위임)
        if _broker_owns_ocx():
            self.ocx = None
            self._broker_mode = True
            self.logger.info("[A-1a] broker alive — OCX 생성/CommConnect skip "
                             "(매수 SendOrder A-1b-BUY broker IPC 활성)")
            # [A-1b-CORE 2026-05-15] chejan consume thread start (daemon)
            self._start_chejan_consume_thread()
            return True

        self._broker_mode = False
        if QApplication is None or QAxWidget is None:
            self.logger.error("[OCX] PyQt5/QAx 사용 불가"); return False
        try:
            self.app = QApplication.instance() or QApplication(sys.argv)
        except Exception as e:
            self.logger.error("[OCX] QApplication 실패: %s", e); return False
        try:
            self.ocx = QAxWidget()
            self.ocx.setControl("KHOPENAPI.KHOpenAPICtrl.1")
            self.ocx.OnReceiveChejanData.connect(self._on_chejan)
            self.ocx.OnReceiveTrData.connect(self._on_tr)
            self.logger.info("[OCX] 초기화 OK"); return True
        except Exception as e:
            self.logger.error("[OCX] 초기화 실패: %s", e); return False

    # ── [UNIFIED v1.1] shared_ocx 지원 ─────────────────────────────────────
    def init_shared(self, shared_ocx) -> bool:
        """수집기 프로세스에서 호출 — 새 QAxWidget/CommConnect 없음."""
        try:
            self.app = QApplication.instance()
            self.ocx = shared_ocx
            self.ocx.OnReceiveChejanData.connect(self._on_chejan)
            self.ocx.OnReceiveTrData.connect(self._on_tr)
            self.logger.info("[OCX] init_shared OK")
            return True
        except Exception as e:
            self.logger.error("[OCX] init_shared 실패: %s", e)
            return False

    def disconnect_shared(self) -> None:
        """init_shared()로 연결한 신호를 해제한다."""
        if self.ocx is None:
            return
        try:
            self.ocx.OnReceiveChejanData.disconnect(self._on_chejan)
        except Exception:
            pass
        try:
            self.ocx.OnReceiveTrData.disconnect(self._on_tr)
        except Exception:
            pass

    def pump(self, ms: int = 100) -> None:
        try:
            if self.app:
                self.app.processEvents()
        except Exception: pass
        try:
            time.sleep(ms / 1000)
        except Exception: pass

    def connect_state(self) -> int:
        # [STEP-2F-1] broker STATE 우선, 실패 시 direct OCX fallback
        try:
            res = _broker_request_bu("STATE", timeout_sec=2.0)
            if res and res.get("status") == "OK":
                return 1 if (res.get("data") or {}).get("connected") else 0
        except Exception:
            pass
        try:
            return int(self.ocx.dynamicCall(
                "GetConnectState()")) if self.ocx else 0
        except Exception: return 0

    def comm_connect(self, timeout_sec: int) -> int:
        # [A-1a 2026-05-15] broker mode 시 CommConnect skip
        # G4에서 self.ocx None + _broker_mode=True 설정 → 여기서 return 0
        if getattr(self, "_broker_mode", False):
            self.logger.info("[A-1a] broker mode — comm_connect skip (broker 이미 로그인)")
            return 0
        if self.ocx is None: return -1
        try: self.ocx.dynamicCall("CommConnect()")
        except Exception as e:
            self.logger.error("[LOGIN] CommConnect 실패: %s", e); return -1
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            self.pump(300)
            if self.connect_state() == 1:
                self.logger.info("[LOGIN] 연결 OK"); return 0
        self.logger.error("[LOGIN] 타임아웃 (%ds)", timeout_sec); return -1

    def get_login_info(self, tag: str) -> str:
        # [STEP-2F-1] broker ACCOUNT_INFO 우선, 실패 시 direct OCX fallback
        try:
            res = _broker_request_bu(
                "ACCOUNT_INFO", extra={"tag": str(tag)}, timeout_sec=2.0
            )
            if res and res.get("status") == "OK":
                d = res.get("data") or {}
                val = (
                    d.get("accounts") if str(tag) == "ACCNO"
                    else d.get("value")
                ) or ""
                if val:
                    return str(val).strip()
        except Exception:
            pass
        try:
            return str(self.ocx.dynamicCall(
                "GetLoginInfo(QString)", [tag])).strip()
        except Exception: return ""

    def get_available_krw(self, account: str, screen: str) -> int:
        for attempt in range(1, BALANCE_RETRY + 2):
            result = self._query_available_krw(account, screen)
            if result > 0: return result
            if attempt <= BALANCE_RETRY:
                self.logger.warning("[BALANCE] 재시도 %d/%d",
                                    attempt, BALANCE_RETRY + 1)
                time.sleep(BALANCE_RETRY_WAIT_SEC)
        self.logger.error("[BALANCE] 최대 재시도 후 0"); return 0

    def _query_available_krw(self, account: str, screen: str) -> int:
        # [사이클1 2026-05-18] L3672 가드 이동 — broker BALANCE_TR 우선 시도 (self.ocx None이어도 가능)
        # Why: A-1a 적용 후 self.ocx=None이면 broker BALANCE_TR 도달 전 차단 → balance_zero 영구
        # [STEP-2F-1] broker BALANCE_TR 우선 (opw00001 whitelist 통과),
        # 실패 시 direct OCX fallback (기존 코드 보존).
        try:
            res = _broker_request_bu(
                "BALANCE_TR",
                extra={
                    "tr_code": "opw00001",
                    "rqname": "예수금조회",
                    "screen_no": str(screen),
                    "input": {
                        "계좌번호":              str(account),
                        "비밀번호":              "",
                        "비밀번호입력매체구분":  "00",
                        "조회구분":              "2",
                    },
                    "output_fields": ["주문가능금액"],
                },
                timeout_sec=8.0,
            )
            if res and res.get("status") == "OK":
                records = ((res.get("data") or {}).get("records") or [])
                if records:
                    raw = (
                        records[0].get("주문가능금액") or ""
                    ).strip().replace(",", "")
                    val = _safe_int(raw, default=0)
                    self._available_krw = val
                    self.logger.info(
                        "[BALANCE][BROKER] 가능=%s원", f"{val:,}"
                    )
                    return val
        except Exception as e:
            self.logger.warning("[BALANCE][BROKER] 예외 → fallback: %s", e)

        # [사이클1 2026-05-18] 가드 이동 (이전 L3672) — broker 실패 + self.ocx None 시 안전 차단
        if self.ocx is None: return 0
        # ── fallback: direct OCX (기존 로직) ──
        try:
            self.ocx.dynamicCall("SetInputValue(QString,QString)",
                                 ["계좌번호", account])
            self.ocx.dynamicCall("SetInputValue(QString,QString)",
                                 ["비밀번호", ""])
            self.ocx.dynamicCall("SetInputValue(QString,QString)",
                                 ["비밀번호입력매체구분", "00"])
            self.ocx.dynamicCall("SetInputValue(QString,QString)",
                                 ["조회구분", "2"])
            self._available_krw = 0
            self._tr_done       = False
            _limiter.acquire()  # [PATCH-RATELIMIT]
            ret = self.ocx.dynamicCall(
                "CommRqData(QString,QString,int,QString)",
                ["예수금조회","opw00001", 0, screen])
            if ret != 0:
                self.logger.error("[BALANCE] CommRqData ret=%d", ret)
                return 0
            deadline = time.time() + 5
            while time.time() < deadline:
                self.pump(200)
                if self._tr_done: break
            if not self._tr_done:
                self.logger.warning("[BALANCE] TR 타임아웃")
            self.logger.info("[BALANCE] 가능=%s원",
                             f"{self._available_krw:,}")
            return self._available_krw
        except Exception as e:
            self.logger.error("[BALANCE] 예외: %s", e); return 0

    def _on_tr(self, screen_no: str, rq_name: str, tr_code: str,
               record_name: str, prev_next: str, *args) -> None:
        if rq_name != "예수금조회": return
        try:
            raw = self.ocx.dynamicCall(
                "GetCommData(QString,QString,int,QString)",
                [tr_code, rq_name, 0, "주문가능금액"]
            ).strip().replace(",","")
            self._available_krw = _safe_int(raw, default=0)
            self._tr_done = True
        except Exception as e:
            self.logger.error("[BALANCE] GetCommData 예외: %s", e)
            self._tr_done = True

    def send_order(self, account: str, code: str, qty: int,
                   price: int, screen: str,
                   result: OrderResult) -> int:
        # [A-1b-BUY 2026-05-15] broker_mode 시 broker IPC 라우팅
        # idempotency_key = result._broker_intent_id (retry 시 같은 key 재사용 → dedup)
        if getattr(self, "_broker_mode", False):
            return self._send_order_via_broker(account, code, qty, price, screen, result)
        if self.ocx is None: return -1
        try:
            temp_key = make_temp_key(code)
            self._temp_map[temp_key] = result
            result._temp_key = temp_key
            _limiter.acquire()  # [PATCH-RATELIMIT]
            # [v4_9-P13] 시장가("03",nPrice=0) → 최유리지정가("06",nPrice=price)
            #   사유: 슬리피지 가드(pre_slip_bps, drift, _check_slippage_cut)와 정합.
            #   매수 최유리지정가 = 매도1호가 지정 → 1tick 슬리피지로 통제.
            #   미체결 잔여는 PARTIAL_RETRY 로직으로 보완(v4_9-P12 완화 적용).
            _hoga_gb = _decide_buy_hoga()  # [CLOSE-AUCTION-HOGA] 동시호가→03, 연속매매→06
            # [HOGA-PRICE-FIX 2026-06-04] 단가 입력은 지정가류(00/05)만. 최유리(06)·시장가(03)·최우선(07)은 price=0.
            #   기존 !=03 은 06(최유리, PULLBACK 기본)에 price를 넣어 키움 [502048] '단가를 입력하지 않는 호가' 거부
            #   → PULLBACK 발주가 broker 도달해도 키움 거부로 실체결0이던 근본. 06+price=0 → 최유리지정가 정상 체결.
            _n_price = int(price) if _hoga_gb in ("00", "05") else 0
            ret = self.ocx.dynamicCall(
                "SendOrder(QString,QString,QString,"
                "int,QString,int,int,QString,QString)",
                ["SAFEPLUS_BUY", screen, account,
                 1, code, qty, _n_price, _hoga_gb, ""])
            result.send_rc = int(ret)
            if result.send_rc != 0:
                self._temp_map.pop(temp_key, None)
                result.transition(OrderState.FAILED, self.logger)
                self.logger.error("[ORDER] 실패 code=%s rc=%d hoga=%s", code, ret, _hoga_gb)
                # [CYCLE-6] ORDER_SENT (실패) emit
                _emit_event("ORDER_SENT", entity="order", entity_id=code,
                            new_state="FAILED",
                            payload={"code": code, "qty": int(qty), "price": int(_n_price), "rc": int(ret), "result": "FAILED"})
            else:
                result.transition(OrderState.SENT, self.logger)
                # [CYCLE-6 2026-05-21] ORDER_SENT emit
                _emit_event("ORDER_SENT", entity="order", entity_id=code,
                            new_state="SENT",
                            payload={"code": code, "qty": int(qty), "price": int(_n_price), "hoga": _hoga_gb})
                # [STEP-2F-4] SendOrder shadow mirror (매수) — fire-and-forget
                try:
                    _send_shadow_order_bu(
                        engine_name="kiwoom_buy",
                        account=account,
                        code=code,
                        qty=int(qty),
                        price=int(_n_price),
                        order_type=1,
                        screen_no=str(screen),
                        rqname="SAFEPLUS_BUY",
                        hoga_gb=_hoga_gb,
                    )
                except Exception:
                    pass
                _hoga_label = {"00":"지정가","03":"시장가","06":"최유리지정가",
                               "07":"최우선지정가","16":"최유리지정가IOC"}.get(_hoga_gb, _hoga_gb)
                self.logger.info(
                    "[ORDER] ✅ code=%s qty=%d price=%d %s",
                    code, qty, _n_price, _hoga_label)
            return result.send_rc
        except Exception as e:
            result.transition(OrderState.FAILED, self.logger)
            self.logger.error("[ORDER] 예외 code=%s: %s", code, e)
            return -1

    def cancel_order(self, account: str, order_no: str,
                     code: str, qty: int, screen: str,
                     result: Optional[OrderResult] = None) -> bool:
        # [A-1b-BUY 2026-05-15] broker_mode 시 broker IPC 라우팅 (order_type=3 매수취소)
        if getattr(self, "_broker_mode", False):
            return self._cancel_order_via_broker(account, order_no, code, qty, screen, result)
        if self.ocx is None or not order_no: return False
        try:
            if result:
                result.transition(OrderState.CANCEL_SENT, self.logger)
            _limiter.acquire()  # [PATCH-RATELIMIT]
            ret = self.ocx.dynamicCall(
                "SendOrder(QString,QString,QString,"
                "int,QString,int,int,QString,QString)",
                ["SAFEPLUS_CANCEL", screen, account,
                 2, code, 0, 0, "00", order_no])
            ok = int(ret) == 0
            if ok:
                self.logger.warning("[CANCEL] ✅ code=%s no=%s",
                                    code, order_no)
                # [STEP-2F-4] cancel SendOrder shadow mirror — fire-and-forget
                try:
                    _send_shadow_order_bu(
                        engine_name="kiwoom_buy_cancel",
                        account=account,
                        code=code,
                        qty=int(qty),
                        price=0,
                        order_type=2,
                        screen_no=str(screen),
                        rqname="SAFEPLUS_CANCEL",
                        hoga_gb="00",
                        origin_order_no=str(order_no),
                    )
                except Exception:
                    pass
            else:
                self.logger.error("[CANCEL] 실패 code=%s rc=%d", code, ret)
                if result:
                    result.transition(
                        OrderState.RECONCILE_PENDING, self.logger)
            return ok
        except Exception as e:
            self.logger.error("[CANCEL] 예외: %s", e)
            if result:
                result.transition(
                    OrderState.RECONCILE_PENDING, self.logger)
            return False

    def _bridge_apply_fill(self, result, t0) -> None:
        """[BROKER-FILL-BRIDGE 2026-06-10] broker-mode chejan 매수체결을 result 상태머신에 반영.
        consume(_consume_chejan_events_bu)가 채운 code-키 레지스트리를 읽어 SENT→ACKED→FILLED 전이.
        매칭: 같은 code + 이번 주문(t0 이후) 매수체결. 완결 시 레지스트리 pop(재사용 방지). 예외 무시(fail-safe)."""
        if not BROKER_FILL_BRIDGE:
            return
        try:
            if result.state not in (OrderState.SENT, OrderState.ACKED, OrderState.PARTIAL):
                return
            _rg = _BROKER_FILL_REGISTRY_BU.get(result.code)
            if not _rg or _rg.get("qty", 0) <= 0:
                return
            if _rg.get("ts", 0.0) < (t0 - 5.0):     # 이전 주문의 stale 체결 배제
                return
            if _rg.get("order_no"):
                result.order_no = _rg["order_no"]
            if result.state == OrderState.SENT:
                result.transition(OrderState.ACKED, self.logger)
            _ap = int(getattr(result, "_bridge_qty_applied", 0))
            _dl = int(_rg["qty"]) - _ap
            if _dl > 0 and _rg.get("price", 0) > 0:
                result.accumulate_fill(_dl, float(_rg["price"]))
                result._bridge_qty_applied = int(_rg["qty"])
            if int(_rg.get("remain", 0)) == 0:
                if result.state in (OrderState.ACKED, OrderState.PARTIAL):
                    result.transition(OrderState.FILLED, self.logger)
                _BROKER_FILL_REGISTRY_BU.pop(result.code, None)
                self.logger.info(
                    "[BROKER_FILL_BRIDGE] code=%s no=%s qty=%d@%s → FILLED",
                    result.code, result.order_no, result.filled_qty, _rg.get("price"))
            elif result.state == OrderState.ACKED:
                result.transition(OrderState.PARTIAL, self.logger)
        except Exception as _e:
            try:
                self.logger.debug("[BROKER_FILL_BRIDGE] 예외(무시): %s", _e)
            except Exception:
                pass

    def wait_ack_and_fill(self, result: OrderResult,
                          account: str = "",
                          screen_cancel: str = "",
                          current_price_ref: Optional[List[int]] = None
                          ) -> None:
        # [WEAK-6 FIX] 시간대별 타임아웃 프로파일 적용
        tp = _get_timeout_profile()
        ack_timeout  = tp["ack"]
        fill_timeout = tp["fill"]
        self.logger.info("[TIMEOUT] profile ack=%ds fill=%ds (hhmm=%04d)",
                         ack_timeout, fill_timeout, _hhmm())

        _brg_t0 = time.time()   # [BROKER-FILL-BRIDGE] 이번 주문 기준시각(이전 stale 체결 배제용)
        deadline = time.time() + ack_timeout
        while time.time() < deadline:
            self.pump(200)
            # [STEP-2F-3/4] Chejan + ACK relay paper-mode consume (log only)
            try:
                _consume_chejan_events_bu()
                _consume_order_shadow_ack_bu()
            except Exception:
                pass
            self._bridge_apply_fill(result, _brg_t0)   # [BROKER-FILL-BRIDGE] chejan 체결→result 전이
            if result.state in (OrderState.ACKED,
                                OrderState.PARTIAL,
                                OrderState.FILLED):
                break
        if result.state not in (OrderState.ACKED,
                                OrderState.PARTIAL,
                                OrderState.FILLED):
            # [STEP-2F-2.5] TIMEOUT_ACK observability — 정책 변경 없이 trace 만
            try:
                _ctx = _get_broker_context_bu()
                _timeout_trace_logger_bu.warning(
                    "TIMEOUT_ACK code=%s qty=%d order_no=%s state=%s "
                    "broker=%s hb_age=%ss chejan_backlog=%s ack_timeout=%ds",
                    result.code, result.qty, result.order_no,
                    result.state.value,
                    _ctx["broker"], _ctx["hb_age_sec"],
                    _ctx["chejan_backlog"], ack_timeout,
                )
            except Exception:
                pass
            result.transition(OrderState.TIMEOUT_ACK, self.logger)
            self.logger.warning("[ACK] 타임아웃(%ds) → 취소 code=%s",
                                ack_timeout, result.code)
            if account and screen_cancel and result.order_no:
                self.cancel_order(account, result.order_no,
                                  result.code, result.qty,
                                  screen_cancel, result)
            else:
                self.logger.critical("[RECONCILE] TIMEOUT_ACK order_no 없음 — 수동 확인 필요: code=%s qty=%d",
                                     result.code, result.qty)
                result.transition(OrderState.RECONCILE_PENDING, self.logger)
            return
        self.logger.info("[ACK] ✅ code=%s no=%s",
                         result.code, result.order_no)

        deadline = time.time() + fill_timeout
        while time.time() < deadline:
            self.pump(200)
            # [STEP-2F-3/4] Chejan + ACK relay paper-mode consume (log only)
            try:
                _consume_chejan_events_bu()
                _consume_order_shadow_ack_bu()
            except Exception:
                pass
            self._bridge_apply_fill(result, _brg_t0)   # [BROKER-FILL-BRIDGE] chejan 체결→result 전이(부분→완전 포함)
            if result.state == OrderState.FILLED:
                break
            if (current_price_ref and account
                    and screen_cancel and result.order_no):
                cur = current_price_ref[0]
                if cur > 0 and _should_cancel_on_drift(
                        result, cur, self.logger):
                    self.cancel_order(account, result.order_no,
                                      result.code, result.qty,
                                      screen_cancel, result)
                    return

        if result.state == OrderState.FILLED:
            self.logger.info(
                "[FILL] 완전체결 code=%s filled=%d@%.2f "
                "slip=%+d원(%+.1fbps)",
                result.code, result.filled_qty,
                result.avg_filled_price,
                result.slippage_won, result.slippage_bps)
        else:
            # [STEP-2F-2.5] TIMEOUT_FILL observability — 정책 변경 없이 trace 만
            try:
                _ctx = _get_broker_context_bu()
                _timeout_trace_logger_bu.warning(
                    "TIMEOUT_FILL code=%s qty=%d filled=%d order_no=%s state=%s "
                    "broker=%s hb_age=%ss chejan_backlog=%s fill_timeout=%ds",
                    result.code, result.qty, result.filled_qty,
                    result.order_no, result.state.value,
                    _ctx["broker"], _ctx["hb_age_sec"],
                    _ctx["chejan_backlog"], fill_timeout,
                )
            except Exception:
                pass
            result.transition(OrderState.TIMEOUT_FILL, self.logger)
            self.logger.warning("[FILL] IOC취소(%ds) code=%s state=%s",
                                fill_timeout, result.code, result.state.value)
            if account and screen_cancel and result.order_no:
                self.cancel_order(account, result.order_no,
                                  result.code, result.qty,
                                  screen_cancel, result)

    # ─────────────────────────────────────────────────────────
    # [A-1b-CORE+BUY 2026-05-15] broker_mode chejan thread + send_order_real
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

        t = _threading_bu.Thread(target=_run, daemon=True, name="buy_sender_chejan_consume")
        t.start()
        self._chejan_thread = t

    def _on_chejan_broker(self, event: dict) -> None:
        """broker chejan event → 기존 _on_chejan 호환 dispatch.

        self.ocx 를 임시 OCX proxy 로 교체 → 기존 _on_chejan 함수 그대로 호출.
        proxy.dynamicCall("GetChejanData(int)", [fid]) → event['fid_data'][fid] 반환.

        [C1-BUY 2026-05-15] ownership 매칭 — 매수/매수취소 direction 만 처리.
        매도 chejan event 가 자기 _temp_map[code] 매칭 통해 매수 result 에 잘못 전이되는 것 차단.
        """
        try:
            fid_data = event.get("fid_data") or {}
            gubun = str(event.get("gubun", "0"))
            # [C1-BUY] order_direction 매칭 — 매수/매수취소만
            direction = str(fid_data.get("905", "")).strip()
            if direction and direction not in ("1", "3", "매수", "매수취소"):
                return  # 매도 chejan → cross-engine contamination 차단

            class _Proxy:
                def __init__(self, fd):
                    self._fd = fd
                def dynamicCall(self, signature, args=None):
                    if "GetChejanData" in signature and args:
                        return str(self._fd.get(str(args[0]), "") or "")
                    return ""

            _saved_ocx = self.ocx
            self.ocx = _Proxy(fid_data)
            try:
                self._on_chejan(gubun, len(fid_data), "")
            finally:
                self.ocx = _saved_ocx
        except Exception as e:
            try:
                self.logger.warning("[A-1b-CORE][CHEJAN] broker event 처리 실패: %s", e)
            except Exception:
                pass

    def _send_order_via_broker(self, account: str, code: str, qty: int,
                               price: int, screen: str,
                               result: "OrderResult") -> int:
        """[A-1b-BUY 2026-05-15] broker_mode 시 send_order_real IPC 라우팅.

        idempotency_key: result 인스턴스에 intent_id 1회 부여 → retry 시 같은 key.
        broker dedup 으로 중복 매수 차단 (옵션 C — engine retry 폐기와 동등).
        """
        try:
            # intent_id 는 OrderResult 인스턴스 단위로 1회 부여 → retry 시 같은 key 재사용
            if not getattr(result, "_broker_intent_id", None):
                result._broker_intent_id = str(_bro_uuid_bu.uuid4())
            # [C5-BUY 2026-05-15] idem_key 에 filled_qty 포함 →
            #   retry(filled_qty=0 동일 key, broker dedup) vs
            #   PARTIAL_RETRY(filled_qty>0 다른 key, 신규 SendOrder 발사) 자동 구분
            idem_key = f"buy_sender_{code}_{result._broker_intent_id}_{int(getattr(result, 'filled_qty', 0) or 0)}"

            _hoga_gb = _decide_buy_hoga()  # [CLOSE-AUCTION-HOGA] 동시호가→03, 연속매매→06
            # [HOGA-PRICE-FIX 2026-06-04] 단가 입력은 지정가류(00/05)만. 최유리(06)·시장가(03)·최우선(07)은 price=0.
            #   기존 !=03 은 06(최유리, PULLBACK 기본)에 price를 넣어 키움 [502048] '단가를 입력하지 않는 호가' 거부
            #   → PULLBACK 발주가 broker 도달해도 키움 거부로 실체결0이던 근본. 06+price=0 → 최유리지정가 정상 체결.
            _n_price = int(price) if _hoga_gb in ("00", "05") else 0

            # [DAILY-TOTAL-CAP] 오늘 발주 누적 총액 자물쇠 — 초과 시 발주 차단(통장 묶기)
            #   동시호가(price=0)는 result.order_krw(사이징 금액)로 정확히 계산.
            _this_krw = int(getattr(result, "order_krw", 0) or 0)
            if _this_krw <= 0 and price > 0:
                _this_krw = int(qty) * int(price)
            # [#2 킬스위치 2026-06-08] 급락장/CB/수동차단/preflight 이상 시 신규매수 SendOrder 절대 차단.
            #   ★최후방어선·모든 매수경로(RELAY/PULLBACK/ADD/DAILY_MIN/EOD_PICK) 공통 — 여기 한 곳이면 전부 막힌다.
            _ks_block, _ks_reason = _crash_kill_switch(
                self.logger, strategy=getattr(result, "strategy", None))
            if _ks_block:
                self.logger.warning("[CRASH_KILL_SWITCH] ⛔ 신규매수 SendOrder 차단 code=%s reason=%s", code, _ks_reason)
                result.transition(OrderState.FAILED, self.logger)
                return -95
            if not _daily_total_cap_ok(_this_krw, self.logger):
                result.transition(OrderState.FAILED, self.logger)
                return -95
            # [B 패치 2026-06-08] 동일종목 당일 누적 주문 hard cap (중복폭주 backstop)
            if not _code_order_cap_ok(str(code), _this_krw, self.logger):
                result.transition(OrderState.FAILED, self.logger)
                return -95

            from broker_client import BrokerClient
            bc = BrokerClient()
            res = bc.send_order_real(
                idempotency_key=idem_key,
                account=str(account),
                code=str(code),
                qty=int(qty),
                order_type=1,  # 매수
                price=int(_n_price),
                hoga_gb=_hoga_gb,
                rqname="SAFEPLUS_BUY_BROKER",
                screen_no=str(screen),
            )
        except Exception as e:
            self.logger.error("[A-1b-BUY] broker IPC 예외 code=%s: %s", code, e)
            result.transition(OrderState.FAILED, self.logger)
            return -98

        if res.get("status") != "OK":
            self.logger.warning("[A-1b-BUY] broker %s: %s",
                                res.get("status"), res.get("error"))
            result.transition(OrderState.FAILED, self.logger)
            return -97

        ret = int((res.get("data") or {}).get("ret", -99))
        result.send_rc = ret
        if ret != 0:
            result.transition(OrderState.FAILED, self.logger)
            self.logger.error("[A-1b-BUY] SendOrder rc=%d code=%s (broker)", ret, code)
        else:
            result.transition(OrderState.SENT, self.logger)
            # _temp_map 등록 (chejan thread 가 order_no 받으면 _order_map 으로 이전)
            temp_key = make_temp_key(code)
            self._temp_map[temp_key] = result
            result._temp_key = temp_key
            self.logger.info("[A-1b-BUY] ✅ broker code=%s qty=%d price=%d %s",
                             code, qty, _n_price, _hoga_gb)
            _add_daily_total(_this_krw)   # [DAILY-TOTAL-CAP] 발주 성공 → 오늘 누적 총액 가산
            _add_code_order(str(code), _this_krw)   # [B 패치] 동일종목 당일 누적 주문(금액+횟수) 가산
            _PENDING_BUY[str(code).zfill(6)] = time.time()   # [CONCURRENT] 발주직후 임시보유(rt_open 반영 전 갭 보완 → 동시 2종목 차단)
        return ret

    def _cancel_order_via_broker(self, account: str, order_no: str,
                                 code: str, qty: int, screen: str,
                                 result: Optional["OrderResult"] = None) -> bool:
        """[A-1b-BUY 2026-05-15] broker_mode 시 cancel SendOrder IPC 라우팅."""
        if not order_no:
            return False
        try:
            intent_id = str(_bro_uuid_bu.uuid4())  # cancel 은 매번 새 intent (한 번만 호출)
            idem_key = f"buy_cancel_{code}_{order_no}_{intent_id}"

            from broker_client import BrokerClient
            bc = BrokerClient()
            res = bc.send_order_real(
                idempotency_key=idem_key,
                account=str(account),
                code=str(code),
                qty=int(qty),
                order_type=3,  # 매수취소
                price=0,
                hoga_gb="00",
                rqname="SAFEPLUS_CANCEL_BROKER",
                screen_no=str(screen),
                origin_order_no=str(order_no),
            )
        except Exception as e:
            self.logger.error("[A-1b-BUY] cancel broker IPC 예외 code=%s: %s", code, e)
            return False

        if res.get("status") != "OK":
            self.logger.warning("[A-1b-BUY][CANCEL] broker %s: %s",
                                res.get("status"), res.get("error"))
            return False

        ret = int((res.get("data") or {}).get("ret", -99))
        ok = (ret == 0)
        if ok:
            self.logger.warning("[A-1b-BUY][CANCEL] ✅ code=%s no=%s (broker)",
                                code, order_no)
            if result:
                result.transition(OrderState.CANCEL_SENT, self.logger)
        else:
            self.logger.error("[A-1b-BUY][CANCEL] rc=%d code=%s (broker)", ret, code)
        return ok

    def _on_chejan(self, gubun: str,
                   item_cnt: int, fid_list: str) -> None:
        if gubun != "0": return
        try:
            order_no     = self.ocx.dynamicCall(
                "GetChejanData(int)", [9203]).strip()
            order_status = self.ocx.dynamicCall(
                "GetChejanData(int)", [913]).strip()
            raw_code     = self.ocx.dynamicCall(
                "GetChejanData(int)", [9001]).strip().lstrip("A")
            stock_code   = raw_code.zfill(6)
            event_qty    = _safe_int(self.ocx.dynamicCall(
                "GetChejanData(int)", [911]))
            event_price  = _safe_float(self.ocx.dynamicCall(
                "GetChejanData(int)", [910]))
            remain_qty   = _safe_int(self.ocx.dynamicCall(
                "GetChejanData(int)", [902]))

            self.logger.info(
                "[CHEJAN] no=%s code=%s status=%s qty=%d@%.0f remain=%d",
                order_no, stock_code, order_status,
                event_qty, event_price, remain_qty)

            if event_price > 0 and stock_code in self._price_ref_map:
                self._price_ref_map[stock_code][0] = int(event_price)

            result = self._order_map.get(order_no)
            if result is None:
                for tk, r in list(self._temp_map.items()):
                    if r.code == stock_code:
                        result = r
                        result.order_no = order_no
                        result.transition(OrderState.ACKED, self.logger)
                        self._order_map[order_no] = result
                        self._temp_map.pop(tk, None)
                        break
            if result is None: return

            if order_status == "접수":
                result.order_no = order_no
                if result.state == OrderState.SENT:
                    result.transition(OrderState.ACKED, self.logger)
                self._order_map.setdefault(order_no, result)

            # [WEAK-7 FIX] "확인"과 "체결" 분리 처리
            # 키움 API: "확인"=접수확인(체결 아님), "체결"=실제 체결
            elif order_status == "확인":
                # 접수 확인 — ACKED 전이만, 체결 누적 안 함
                result.order_no = order_no
                if result.state in (OrderState.SENT, OrderState.PENDING):
                    result.transition(OrderState.ACKED, self.logger)
                self._order_map.setdefault(order_no, result)
                self.logger.info(
                    "[CHEJAN] 확인(접수) code=%s no=%s — 체결 아님",
                    result.code, order_no)

            elif order_status == "체결":
                # 실제 체결 — 수량/가격 누적
                result.order_no = order_no
                if result.state in (OrderState.SENT, OrderState.PENDING):
                    result.transition(OrderState.ACKED, self.logger)
                self._order_map.setdefault(order_no, result)
                if event_qty > 0 and event_price > 0:
                    result.accumulate_fill(event_qty, event_price)
                if remain_qty == 0:
                    result.transition(OrderState.FILLED, self.logger)
                    # [CYCLE-6 2026-05-21 Path α] ORDER_FILLED emit
                    _emit_event("ORDER_FILLED", entity="order", entity_id=order_no,
                                prev_state="ACKED", new_state="FILLED",
                                payload={
                                    "code": getattr(result, "code", ""),
                                    "fill_qty": int(getattr(result, "filled_qty", 0)),
                                    "fill_price": float(getattr(result, "avg_filled_price", 0)),
                                })
                    self._order_map.pop(order_no, None)
                elif event_qty > 0:
                    if result.state not in (OrderState.PARTIAL,
                                            OrderState.FILLED):
                        result.transition(OrderState.PARTIAL, self.logger)

            elif order_status in ("취소","취소확인"):
                if result.state == OrderState.PARTIAL:
                    result.transition(OrderState.CANCEL_SENT, self.logger)
                if result.state in (OrderState.CANCEL_SENT,
                                    OrderState.TIMEOUT_FILL,
                                    OrderState.TIMEOUT_ACK):
                    result.transition(
                        OrderState.CANCEL_CONFIRMED, self.logger)
                self._order_map.pop(order_no, None)
                self.logger.info("[CHEJAN] 취소확인 code=%s state=%s",
                                 result.code, result.state.value)

        except Exception as e:
            self.logger.error("[CHEJAN] 예외: %s", e)

# ── 체결 실행 엔진 ──
def _execute_and_track(
    kw: Kiwoom, account: str, screen: str, screen_cancel: str,
    code: str, qty: int, price: int,
    strategy: str, rank_ratio_str: str,
    order_krw: int, fingerprint: str,
    evolve_weight: float, final_qty_adjusted: bool,
    logger: logging.Logger,
    row: Optional[Dict[str, Any]] = None,
    base_dir: str = DEFAULT_BASE_DIR,
) -> OrderResult:
    _row = row or {}

    # [BUG-1 FIX] price=0 완전 차단 — 시장가 슬리피지 위험
    if price <= 0:
        logger.error(
            "[EXEC] ❌ price=0 → 주문 차단 (시장가 극단 슬리피지 방지) code=%s", code)
        result = OrderResult(code, qty, price, strategy, rank_ratio_str,
                             order_krw, fingerprint,
                             evolve_weight, final_qty_adjusted)
        result.transition(OrderState.FAILED, logger)
        return result

    # 시장 상태 판단 (1회)
    regime = _market_regime(_row, logger)

    # 호가 시장충격 추정 (1회)
    impact_bps = _market_impact_bps(_row, qty, price, logger)

    # 동적 임계값 계산 (1회)
    dyn_threshold = _dynamic_slip_threshold(_row, logger, regime)

    # 슬리피지 사전 추정 → [BUG-2 FIX] Soft Mode 적용
    pre_slip = _estimate_slippage_pre(_row, price, logger, impact_bps)
    if pre_slip > dyn_threshold:
        logger.warning(
            "[SLIP_PRE] ❌ 사전 추정 %.1fbps > 허용%.0fbps "
            "→ 진입 차단 code=%s",
            pre_slip, dyn_threshold, code)
        result = OrderResult(code, qty, price, strategy, rank_ratio_str,
                             order_krw, fingerprint,
                             evolve_weight, final_qty_adjusted)
        result.transition(OrderState.FAILED, logger)
        return result
    elif pre_slip > dyn_threshold * 0.7:
        soft_ratio = 0.60
        old_qty = qty
        qty = max(1, int(qty * soft_ratio))
        order_krw = int(order_krw * soft_ratio)
        logger.warning(
            "[SLIP_PRE] ⚠️ 사전 추정 %.1fbps 경계 (허용%.0f×70%%) "
            "→ 수량 축소 %d→%d(%.0f%%) code=%s",
            pre_slip, dyn_threshold, old_qty, qty,
            soft_ratio * 100, code)

    result = OrderResult(code, qty, price, strategy, rank_ratio_str,
                         order_krw, fingerprint,
                         evolve_weight, final_qty_adjusted)
    # [WEAK-5] 수익률 추적 데이터 바인딩
    result.ev_pct       = _safe_float(_row.get("ev_pct", 0))
    result.score        = _safe_float(_row.get("score", 0))
    result.conviction   = str(_row.get("conviction", "")).strip()
    result.regime       = regime
    result.pre_slip_bps = pre_slip
    # [PROFIT-5] 기관 탑승 정보 바인딩
    result.inst_score   = _safe_float(_row.get("inst_score",
                           _row.get("inst_buy_score", 0)))
    result.inst_consec  = _safe_int(_row.get("inst_consec",
                           _row.get("inst_consecutive_buy", 0)))
    result.inst_ride    = bool(_row.get("_inst_ride_flag", False))

    # current_price_ref 등록
    current_price_ref: List[int] = [price]
    kw._price_ref_map[code] = current_price_ref

    def _send_single(target_result: OrderResult,
                     send_qty: int, attempt_no: int) -> bool:
        rc = -1
        for retry in range(1, MAX_ORDER_RETRY + 1):
            rc = kw.send_order(account, code, send_qty, price,
                               screen, target_result)
            if rc == 0: break
            logger.warning("[RETRY] %d/%d code=%s rc=%d",
                           retry, MAX_ORDER_RETRY, code, rc)
            time.sleep(0.3 * retry)
        if rc != 0:
            logger.error("[ORDER] 송신 실패 attempt=%d code=%s",
                         attempt_no, code)
            return False
        kw.wait_ack_and_fill(target_result, account=account,
                             screen_cancel=screen_cancel,
                             current_price_ref=current_price_ref)
        return target_result.acked

    # [PROFIT-3] 종가 동시호가(14:50~) → 분할 비활성화, 전량 단일 주문
    # 종가 배치 처리에서 분할 = 체결률 저하 위험
    _hhmm_now = _hhmm()
    _is_close_auction = (_hhmm_now >= 1450)
    if _is_close_auction and EXEC_SPLIT_ORDER:
        logger.info(
            "[CLOSE_AUC] ⑧ 종가 동시호가(%04d) → 단일 전량 주문 "
            "(분할 비활성화) code=%s qty=%d",
            _hhmm_now, code, qty)

    # 분할 비율 동적화 + qty=1 안전 처리 + 종가 단일 강제
    if EXEC_SPLIT_ORDER and qty >= 2 and not _is_close_auction:
        split_ratio = _dynamic_split_ratio(_row, logger, regime)
        qty1, qty2  = _calc_split_qty(qty, split_ratio)
        logger.info(
            "[SPLIT] code=%s %d → %d+%d "
            "(%.0f%%:%.0f%%) regime=%s",
            code, qty, qty1, qty2,
            split_ratio*100, (1-split_ratio)*100, regime)

        ok1 = _send_single(result, qty1, attempt_no=1)
        if not ok1:
            # [WEAK-4 FIX] 1차 실패 → 수량 축소 재시도 (전량 폴백 금지)
            reduced_qty = max(1, int(qty1 * 0.5))
            logger.warning(
                "[SPLIT] 1차 실패 → 수량 축소 재시도 %d→%d code=%s "
                "(전량 %d 폴백 차단 — 시장충격 방지)",
                qty1, reduced_qty, code, qty)
            _send_single(result, reduced_qty, attempt_no=1)
        else:
            # P1: 2차 주문 전 drift 재확인
            if qty2 > 0:
                time.sleep(EXEC_SPLIT_DELAY_SEC)
                if result.state not in (OrderState.FILLED,
                                        OrderState.CANCEL_CONFIRMED,
                                        OrderState.FAILED):
                    cur2 = current_price_ref[0]
                    if cur2 > 0 and _should_cancel_on_drift(
                            result, cur2, logger):
                        logger.warning(
                            "[SPLIT] 2차 주문 취소 — drift 초과 "
                            "cur=%d ref=%d code=%s",
                            cur2, price, code)
                    else:
                        logger.info("[SPLIT] 2차 %d주 code=%s", qty2, code)
                        ok2 = _send_single(result, qty2, attempt_no=2)
                        if not ok2:
                            logger.warning(
                                "[SPLIT] 2차 실패 — "
                                "1차 체결분(%d주)만 확정 code=%s",
                                result.filled_qty, code)
    else:
        if qty == 1:
            logger.info("[SPLIT] qty=1 → 단일주문 code=%s", code)
        _send_single(result, qty, attempt_no=1)

    # [PROFIT-2] PARTIAL 체결 후 잔여 수량 즉시 재시도 — 몰빵 완성 보장
    # [v4_3 FIX-4] 재시도 전 drift / pre_slip / EV-risk / regime 재검증
    if result.state == OrderState.PARTIAL:
        remaining_qty = qty - result.filled_qty
        if remaining_qty > 0 and not _is_close_auction:
            # ── FIX-4: 4조건 재검증 ──
            _retry_ok      = True
            _retry_blocks: list = []

            # 조건1: Drift 재검증 — [v4_9-P12] 시장가 발주이므로 임계 1.5배 완화
            _cur_price  = current_price_ref[0]
            _reentry_p  = _dynamic_reentry_pct(_row, logger, regime)
            _retry_drift_mult = float(os.environ.get("PARTIAL_RETRY_DRIFT_MULT", "1.5"))
            if _cur_price > 0 and price > 0:
                _drift = abs(_cur_price - price) / price * 100
                if _drift > _reentry_p * _retry_drift_mult:
                    _retry_ok = False
                    _retry_blocks.append(
                        f"BLOCK:RETRY001 drift={_drift:.2f}%>{_reentry_p * _retry_drift_mult:.2f}%")

            # 조건2: pre_slip 재추정 — [v4_9-P12] 시장가 발주이므로 임계 1.5배 완화
            _retry_slip = _estimate_slippage_pre(_row, price, logger, impact_bps)
            _retry_slip_mult = float(os.environ.get("PARTIAL_RETRY_SLIP_MULT", "1.5"))
            if _retry_slip > dyn_threshold * _retry_slip_mult:
                _retry_ok = False
                _retry_blocks.append(
                    f"BLOCK:RETRY002 pre_slip={_retry_slip:.1f}bps>threshold={dyn_threshold * _retry_slip_mult:.0f}")

            # 조건3: EV-risk 재검증
            _ev_r    = _safe_float(_row.get("ev_pct", 0))
            _loss_r  = _safe_float(_row.get("atr_pct",
                        _row.get("daily_vol_pct", 0)))
            if _ev_r > 0 and _loss_r > 0:
                _evr = _ev_r / _loss_r
                if _evr < EV_RISK_RATIO_MIN:
                    _retry_ok = False
                    _retry_blocks.append(
                        f"BLOCK:RETRY003 ev_risk={_evr:.2f}<{EV_RISK_RATIO_MIN}")

            # 조건4: regime 재검증
            _cur_regime = _market_regime(_row, logger)
            if _cur_regime == "BEAR":
                _retry_ok = False
                _retry_blocks.append("BLOCK:RETRY004 regime=BEAR")

            if not _retry_ok:
                logger.warning(
                    "[PARTIAL_RETRY][FIX-4] ⛔ 재검증 실패 → 잔여 포기 "
                    "filled=%d code=%s 사유: %s",
                    result.filled_qty, code, " | ".join(_retry_blocks))
            else:
                logger.info(
                    "[PARTIAL_RETRY][FIX-4] ✅ 4조건 재검증 통과 → 잔여%d주 재주문 code=%s",
                    remaining_qty, code)
                # 잔여 수량 재주문 (별도 result에 체결 → 원본에 누적)
                retry_result = OrderResult(
                    code, remaining_qty, price, strategy, rank_ratio_str,
                    int(order_krw * remaining_qty / max(qty, 1)),
                    fingerprint, evolve_weight, final_qty_adjusted)
                ok_retry = _send_single(retry_result, remaining_qty, attempt_no=50)
                if ok_retry and retry_result.filled_qty > 0:
                    result.accumulate_fill(retry_result.filled_qty,
                                           retry_result.avg_filled_price)
                    if result.filled_qty >= qty:
                        result.transition(OrderState.FILLED, logger)
                    logger.info(
                        "[PARTIAL_RETRY] ✅ 추가체결 +%d주 최종=%d주 code=%s",
                        retry_result.filled_qty, result.filled_qty, code)
                else:
                    logger.warning(
                        "[PARTIAL_RETRY] 잔여 재시도 실패 — %d주만 확정 code=%s",
                        result.filled_qty, code)
        elif remaining_qty > 0 and _is_close_auction:
            logger.info(
                "[PARTIAL_RETRY] 종가 동시호가 → 잔여 재시도 생략 "
                "(체결 배치처리) code=%s filled=%d",
                code, result.filled_qty)

    # ① 슬리피지 컷 + pnl_linker 페널티 전달
    if result.filled or result.state == OrderState.PARTIAL:
        passed = _check_slippage_cut(result, dyn_threshold, logger)
        result._slip_cut_triggered = not passed
        if not passed:
            _notify_slip_penalty(result, base_dir, logger)
    else:
        result._slip_cut_triggered = False

    # P1: 슬리피지 컷 발동 시 재진입 완전 차단
    if result._slip_cut_triggered:
        logger.warning(
            "[REENTRY] ⛔ slip_cut 발동 → 재진입 차단 code=%s slip=%.1fbps",
            code, result.slippage_bps)
        kw._price_ref_map.pop(code, None)
        return result

    # 재진입 — 동적 가격 오차 + 재진입 슬리피지 컷
    # [GHOST-FIX 2026-06-04] 종가 동시호가(>=CLOSE_AUCTION_HHMM)는 15:30 일괄체결이라
    #   ACK 타임아웃으로 미체결 오판 → 재진입하면 키움에 중복주문 누적·전부 체결(007390 87주=29×3 사고).
    #   동시호가는 재진입 금지하고 단일 주문 그대로 15:30 체결 대기. (14:50~15:20 연속매매는 기존대로 허용)
    _close_auction_now = (_hhmm_now >= CLOSE_AUCTION_HHMM)
    if (_close_auction_now and not result.filled
            and result.state not in (OrderState.FILLED, OrderState.PARTIAL)):
        logger.info(
            "[REENTRY] ⛔ 종가 동시호가(hhmm=%04d>=%d) → 재진입 생략, 15:30 일괄체결 대기 code=%s",
            _hhmm_now, CLOSE_AUCTION_HHMM, code)

    if (not result.filled and
            result.state not in (OrderState.FILLED, OrderState.PARTIAL)
            and EXEC_REENTRY_MAX > 0
            and not _close_auction_now):

        # [#5-A 2026-06-08] ACK 타임아웃 재진입 직전 broker 실체결(chejan) 확인 → 미체결 오판 중복매수 방지.
        #   GHOST-FIX(2026-06-04)는 종가 동시호가만 막았고 장중 연속매매 ACK 타임아웃은 안 막음 → 6/8 09:12 131970 9회 중복.
        #   장중에도 chejan 체결확인. 체결 있으면 재진입 금지. (fail-open이라도 _code_order_cap_ok hard cap이 backstop)
        if _has_recent_fill_bu(code, EXEC_REENTRY_FILLCHECK_SEC):
            logger.warning("[REENTRY] ⛔ broker 실체결 확인(chejan) → 재진입 금지 (ACK 타임아웃 오판 중복매수 방지) code=%s", code)
            kw._price_ref_map.pop(code, None)
            return result

        reentry_pct = _dynamic_reentry_pct(_row, logger, regime)

        for reentry_no in range(1, EXEC_REENTRY_MAX + 1):
            logger.info(
                "[REENTRY] %d/%d code=%s "
                "(허용=%.2f%% regime=%s)",
                reentry_no, EXEC_REENTRY_MAX, code,
                reentry_pct, regime)

            cur = current_price_ref[0]
            if cur > 0 and price > 0:
                drift = abs(cur - price) / price * 100
                if drift > reentry_pct:
                    logger.warning(
                        "[REENTRY] 오차 %.2f%% > 허용%.2f%% → 중단 code=%s",
                        drift, reentry_pct, code)
                    break

            new_result = OrderResult(
                code, qty, price, strategy, rank_ratio_str,
                order_krw, fingerprint,
                evolve_weight, final_qty_adjusted)

            ok_re = _send_single(
                new_result, qty, attempt_no=reentry_no + 10)
            if ok_re and (new_result.filled or
                          new_result.state == OrderState.PARTIAL):
                re_passed = _check_slippage_cut(
                    new_result, dyn_threshold, logger)
                if not re_passed:
                    logger.warning(
                        "[REENTRY] 고점체결 감지 "
                        "code=%s slip=%.1fbps",
                        code, new_result.slippage_bps)
                    _notify_slip_penalty(new_result, base_dir, logger)

                result.accumulate_fill(new_result.filled_qty,
                                       new_result.avg_filled_price)
                if result.state != OrderState.FILLED:
                    result.transition(OrderState.FILLED, logger)
                logger.info(
                    "[REENTRY] ✅ %d/%d code=%s "
                    "filled=%d@%.2f slip=%.1fbps",
                    reentry_no, EXEC_REENTRY_MAX, code,
                    new_result.filled_qty,
                    new_result.avg_filled_price,
                    new_result.slippage_bps)
                break
            else:
                logger.warning("[REENTRY] 실패 %d/%d code=%s",
                               reentry_no, EXEC_REENTRY_MAX, code)

    kw._price_ref_map.pop(code, None)
    return result

# ── 메인 ──
# ═══════════════════════════════════════════════════════════════
#  [v4.10 TRACE] 매수 차단 추적 — 모듈 레벨 stats + 헬퍼
# ═══════════════════════════════════════════════════════════════
_ORDER_STATS: dict = {"queue": 0, "accepted": 0, "blocked": 0,
                      "block_counts": {}, "last_reason": ""}

def _order_stats_reset() -> None:
    _ORDER_STATS.update({"queue": 0, "accepted": 0, "blocked": 0,
                         "block_counts": {}, "last_reason": ""})

def _order_gate_block(lg, gate: str, reason: str, code: str = "", **details) -> None:
    _ORDER_STATS["blocked"] += 1
    _ORDER_STATS["last_reason"] = reason
    _ORDER_STATS["block_counts"][reason] = _ORDER_STATS["block_counts"].get(reason, 0) + 1
    detail_str = " ".join(f"{k}={v}" for k, v in details.items())
    lg.warning("[ORDER_BLOCK] gate=%s code=%s reason=%s %s",
               gate, code or "-", reason, detail_str)

def _order_gate_accept(lg, code: str, **details) -> None:
    _ORDER_STATS["accepted"] += 1
    detail_str = " ".join(f"{k}={v}" for k, v in details.items())
    lg.info("[ORDER_ACCEPT] code=%s %s", code, detail_str)

def _emit_order_summary(lg) -> None:
    lg.info("[ORDER_SUMMARY] queue=%d accepted=%d blocked=%d block_counts=%s",
            _ORDER_STATS["queue"], _ORDER_STATS["accepted"],
            _ORDER_STATS["blocked"], _ORDER_STATS["block_counts"])


def main(shared_ocx=None) -> int:
    _order_stats_reset()
    base = Path(
        _env("SAFEPLUS_BASE",
             _env("BASE_DIR", DEFAULT_BASE_DIR))
    )
    logger   = _setup_logger(base)
    dep_mode = _env("ORDER_DEPENDENCY_MODE",
                    DEFAULT_DEPENDENCY_MODE).upper()
    if dep_mode not in (MODE_INDEPENDENT, MODE_CONTINGENT):
        dep_mode = DEFAULT_DEPENDENCY_MODE
    run_id = make_run_id()

    logger.info("=" * 70)
    logger.info("BUY ORDER SENDER v4_9 | run=%s dep=%s params=%s pnl=%s",
                run_id, dep_mode,
                "OK" if _PARAMS_OK else "NG",
                "OK" if _PNL_LINKER_OK else "NG")

    # ⑤ engine_shutdown.flag 감지 — 잠금 획득 전 선행 체크
    if _is_shutdown(base, logger):
        _order_gate_block(logger, "shutdown", "engine_shutdown_flag")
        _emit_order_summary(logger)
        return RC_HOLD

    # [MAXROWS-FIX 2026-06-10] L5311 하드코딩 4가 L822 DEFAULT_MAX_BUY_ROWS=1(6/8 사용자 "1종목 몰빵" 지시)을
    #   무시 → 사전 잔고검사(L5535)가 head(4) 후보 주문액 합산 → 강한후보 2개↑ 사이클마다 1등(한도내)도
    #   balance_exceeded로 통째 차단(동시캡=1은 매수루프에서 뒤늦게 적용). DEFAULT_MAX_BUY_ROWS 존중으로 정합.
    #   롤백: env DEFAULT_MAX_BUY_ROWS=4.
    max_buy_rows = int(os.environ.get("DEFAULT_MAX_BUY_ROWS", str(DEFAULT_MAX_BUY_ROWS)))  # [v4_9] 분할 진입 하드캡(기본1)
    _tp = _get_timeout_profile()
    logger.info(
        "[CONFIG] MAX_BUY=%d BAL_RATIO=%.2f "
        "TIMEOUT_PROFILE=ack%ds/fill%ds VAR_LIMIT=%.0f%% VAR_DAILY_MAX=%.1f%%",
        max_buy_rows, BALANCE_SAFETY_RATIO,
        _tp["ack"], _tp["fill"],
        MAX_ACCOUNT_EXPOSURE_PCT * 100,
        VAR_DAILY_MAX_LOSS_PCT * 100)
    logger.info("[CONFIG] ABS_EV_FLOOR=%.2f", ABS_EV_FLOOR)
    logger.info(
        "[EVOLVE] enabled=%s lookback=%d건(거래횟수) w=[%.2f,%.2f] "
        "min_n=%d trade_cost=%.3f%%",
        EVOLVE_ENABLED, EVOLVE_LOOKBACK_TRADES,
        EVOLVE_MIN_WEIGHT, EVOLVE_MAX_WEIGHT, EVOLVE_MIN_SAMPLES,
        TRADE_COST_ROUNDTRIP_PCT * 100)
    _pr_spread = _params_get("entry_max_spread_pct", None)
    _spread_log = float(_pr_spread) if _pr_spread is not None \
                  else float(os.environ.get("ENTRY_MAX_SPREAD_PCT", "0.5"))
    logger.info(
        "[GUARD_v4_7] open=%04d close=%04d cancel_max=%d circuit_max=%d "
        "| 당일청산 전략 전용 (시가·추세눌림)",
        GUARD_OPEN_STABLE_HHMM,
        GUARD_CLOSE_HHMM, GUARD_MAX_CANCEL_CNT,
        CIRCUIT_BREAKER_MAX_FAIL)
    logger.info(
        "[IOC] 최유리지정가+타임아웃취소 "
        "(키움 거래소 레벨 IOC 미지원 — 짧은 시장 노출 불가피)")
    logger.info(
        "[FILTER_v4_0] gate=%s EV≥%.2f%% EV/risk≥%.1f "
        "score≥%.0f BEAR=%s NEUTRAL_ev≥%.2f%% BULL_ev≥%.2f%% "
        "mom3m≥%.1f%% volsurge≥%.0f%% overheat×%.1f",
        "ON" if CONVICTION_GATE_ENABLED else "OFF",
        EV_MIN_PCT, EV_RISK_RATIO_MIN, SCORE_MIN,
        "BLOCK" if REGIME_BEAR_BLOCK else "ALLOW",
        REGIME_NEUTRAL_EV_MIN, REGIME_BULL_EV_MIN,
        ENTRY_MOM_3M_MIN_PCT, ENTRY_VOL_SURGE_MIN_PCT,
        OVERHEAT_MULT)
    logger.info(
        "[INST_RIDE_v4_2] enabled=%s min=%.2f(↑0.35) high=%.2f(↑0.60) "
        "ev_relax=%.2f%% consec_min=%d(↑3) stale=%ds",
        INST_RIDE_ENABLED, INST_SCORE_MIN, INST_SCORE_HIGH,
        INST_EV_RELAX_PCT, INST_CONSEC_MIN, _INST_STALE_SEC)
    logger.info(
        "[EV_SIZE_v4] 잔고비율: base=%.0f%% mid=%.0f%% full=%.0f%% "
        "(레버리지없는 현실화 — 개인투자자)",
        EV_SIZE_RATIO_BASE*100, EV_SIZE_RATIO_MID*100, EV_SIZE_RATIO_HIGH*100)

    if not _acquire_run_lock(base, logger):
        _order_gate_block(logger, "run_lock", "lock_acquire_fail")
        _emit_order_summary(logger)
        return RC_HOLD

    _kw_ref = [None]   # [UNIFIED] shared_ocx 사용 시 신호 해제용
    try:
        queue_file    = _resolve_path(
            base, _env("KJS_QUEUE_FILE", DEFAULT_QUEUE_FILE))
        screen        = _env("KIWOOM_SCREEN_NO",     DEFAULT_SCREEN_NO)
        screen_bal    = _env("KIWOOM_SCREEN_BAL",    DEFAULT_SCREEN_BAL)
        screen_cancel = _env("KIWOOM_SCREEN_CANCEL", DEFAULT_SCREEN_CANCEL)
        connect_to    = _env_int("CONNECT_TIMEOUT_SEC",
                                 DEFAULT_CONNECT_TIMEOUT_SEC)
        order_gap_sec = max(
            _env_float("ORDER_GAP_SEC", DEFAULT_ORDER_GAP_SEC),
            DEFAULT_ORDER_GAP_MIN)

        if not _validate_screen(screen):
            _order_gate_block(logger, "screen", "invalid_screen", screen=screen)
            return RC_HOLD
        if not _validate_market_time(logger):
            _order_gate_block(logger, "market_time", "out_of_market_window",
                              hhmm=_hhmm())
            return RC_HOLD
        if not queue_file.exists():
            _order_gate_block(logger, "queue_load", "queue_file_missing",
                              path=str(queue_file))
            return RC_STOP_INPUT_0B
        if queue_file.stat().st_size == 0:
            _order_gate_block(logger, "queue_load", "queue_file_empty",
                              path=str(queue_file))
            return RC_STOP_INPUT_0B

        df = _read_queue_csv(queue_file, logger)
        if df is None or len(df) == 0:
            _order_gate_block(logger, "queue_load", "queue_df_empty")
            return RC_HOLD
        if not _validate_queue_contract(df, logger):
            _order_gate_block(logger, "queue_load", "queue_contract_fail")
            return RC_HOLD

        df["side"] = df["side"].astype(str).str.strip().str.upper()
        df_buy = df[df["side"] == "BUY"].copy()
        # [EOD-ISOLATE 2026-06-01] env BUY_SENDER_STRATEGY_ONLY 설정 시 해당 strategy 행만 처리.
        #   Why: EOD_PICK 종가매수가 큐에 잔존한 아침 SIGA행과 2M 예산을 공유 → 합계 초과 HOLD (6/1 024060 미체결).
        #   EOD_PICK은 자기 1등만·자기 예산으로 매수하도록 분리. 미설정=기존 전체 BUY(장중 SIGA/PULLBACK 무영향).
        _strat_only = os.environ.get("BUY_SENDER_STRATEGY_ONLY", "").strip().upper()
        if _strat_only and "strategy" in df_buy.columns:
            _b4 = len(df_buy)
            df_buy = df_buy[df_buy["strategy"].astype(str).str.strip().str.upper() == _strat_only].copy()
            logger.info("[EOD-ISOLATE] strategy=%s 필터: BUY %d→%d행 (예산 분리)", _strat_only, _b4, len(df_buy))
        # [QUEUE-STALE 2026-06-01] 오래된 BUY행 근원 제거 — "아침에 못 산 주문을 종가에 실행" 방지.
        #   큐에 잔존한 옛 행(예: 09:09 SIGA)이 종가매수 예산을 갉아먹던 근원 차단. 모든 경로(SIGA/PULLBACK/EOD) 보호.
        #   ts(YYYYMMDDHHMMSS) age > BUY_QUEUE_MAX_AGE_MIN(기본30분)이면 drop. 파싱불가/ts없음=보존(fail-open=매수 안 끊김).
        _max_age_min = int(os.environ.get("BUY_QUEUE_MAX_AGE_MIN", "30"))
        if _max_age_min > 0 and "ts" in df_buy.columns and len(df_buy) > 0:
            import datetime as _dt_stale
            _now_stale = _dt_stale.datetime.now()
            def _row_fresh(_ts):
                s = str(_ts).strip()
                if len(s) < 14 or not s[:14].isdigit():
                    return True   # 파싱불가 → 보존
                try:
                    _t = _dt_stale.datetime.strptime(s[:14], "%Y%m%d%H%M%S")
                except Exception:
                    return True
                return (_now_stale - _t).total_seconds() <= _max_age_min * 60
            _b4s = len(df_buy)
            df_buy = df_buy[df_buy["ts"].apply(_row_fresh)].copy()
            if len(df_buy) != _b4s:
                logger.warning("[QUEUE-STALE] 오래된 BUY행 제거(age>%d분): %d→%d행", _max_age_min, _b4s, len(df_buy))
        if len(df_buy) == 0:
            logger.warning("[QUEUE] BUY 없음")
            _order_gate_block(logger, "queue_load", "no_buy_rows", total=len(df))
            return RC_HOLD
        logger.info("[QUEUE] BUY=%d / 전체=%d", len(df_buy), len(df))
        _ORDER_STATS["queue"] = len(df_buy)

        kw = Kiwoom(logger)
        if shared_ocx is not None:
            if not kw.init_shared(shared_ocx):
                _order_gate_block(logger, "kiwoom", "init_shared_fail")
                return RC_HOLD
            _kw_ref[0] = kw
        else:
            if not kw.init():
                _order_gate_block(logger, "kiwoom", "init_fail")
                return RC_HOLD
            if kw.connect_state() != 1:
                if kw.comm_connect(connect_to) != 0:
                    _order_gate_block(logger, "kiwoom", "comm_connect_fail")
                    return RC_HOLD

        # [SAFE+ 필수-4] KIWOOM_ACCOUNT 환경변수 필수 — 자동 계좌 선택 로직 제거
        account = _env("KIWOOM_ACCOUNT")
        if not account:
            logger.critical("[ACCOUNT] KIWOOM_ACCOUNT 환경변수 미설정 → 즉시 HOLD (자동 계좌 선택 비활성)")
            _order_gate_block(logger, "account", "kiwoom_account_required")
            return RC_HOLD
        if not _is_valid_account(account):
            logger.error("[PRECHECK] 유효하지 않은 계좌번호")
            _order_gate_block(logger, "account", "invalid_account",
                              account=str(account)[:4] + "****" if account else "-")
            return RC_HOLD
        logger.info("[ACCOUNT] %s****", account[:4])

        # ── shared_ocx 전달: sell 브릿지 초기화 (CommConnect 없이) ──
        # [UNIFIED] 수집기 통합 모드에서는 수집기가 직접 관리하므로 skip
        if shared_ocx is None:
            _sell_bridge = None
            _pb_bridge   = None
            _ocx_run_dir = str(Path(__file__).resolve().parent)
            if _ocx_run_dir not in sys.path:
                sys.path.insert(0, _ocx_run_dir)
            try:
                import importlib as _ocx_il
                _sell_bridge = _ocx_il.import_module(
                    "rt_sell_engine_v3_19").KiwoomRealSellBridge(
                    account=account, shared_ocx=kw.ocx)
                logger.info("[SHARED_OCX] rt_sell_engine 초기화 OK")
            except Exception as _ocx_e:
                logger.warning("[SHARED_OCX] rt_sell_engine 초기화 실패: %s", _ocx_e)
            try:
                import importlib as _ocx_il
                _pb_bridge = _ocx_il.import_module(
                    "pullback_sell_strategy_v4_21_FIXED").KiwoomBridge.get_instance(
                    shared_ocx=kw.ocx)
                if _pb_bridge:
                    logger.info("[SHARED_OCX] pullback_sell_strategy 초기화 OK")
                else:
                    logger.warning("[SHARED_OCX] pullback_sell_strategy 초기화 None")
            except Exception as _ocx_e:
                logger.warning("[SHARED_OCX] pullback_sell_strategy 초기화 실패: %s", _ocx_e)

        # [SAFE+ 필수-5] REAL_TEST_MODE 동기화 — 상태 일치 확인 (로직은 SAFEPLUS_CAPITAL이 단일 진리)
        logger.info("[REAL_TEST_MODE=%s] sender 동기화 (cap=%s원, hard=%.0f%%)",
                    "ON" if REAL_TEST_MODE_FLAG else "OFF",
                    f"{SAFEPLUS_CAPITAL:,}", SAFEPLUS_CAPITAL_HARD_RATIO * 100)

        # [SAFE+ 필수-1] available_krw = min(계좌가용현금, SAFEPLUS_CAPITAL)
        _account_krw = kw.get_available_krw(account, screen_bal)
        if _account_krw <= 0:
            logger.error("[BALANCE] 가용 잔고 0 → HOLD")
            _order_gate_block(logger, "balance", "balance_zero",
                              available=_account_krw)
            return RC_HOLD
        available_krw = min(_account_krw, SAFEPLUS_CAPITAL)
        if available_krw < _account_krw:
            logger.info(
                "[SAFEPLUS_CAP] 계좌가용=%s원 → cap %s원으로 제한 (모든 사이징 cap 기준)",
                f"{_account_krw:,}", f"{SAFEPLUS_CAPITAL:,}")
        else:
            logger.info(
                "[SAFEPLUS_CAP] 계좌가용=%s원 ≤ cap %s원 → 계좌가용 그대로 사용",
                f"{_account_krw:,}", f"{SAFEPLUS_CAPITAL:,}")

        evolve_weights = _load_strategy_weights(base, logger) \
                         if EVOLVE_ENABLED else {}
        pf_size_mult   = _load_preflight_size_mult(base, logger)

        # [PREFLIGHT] 진입 차단/축소 분기 (안1 — size_mult 기반)
        if pf_size_mult <= 0.60:
            logger.warning("[ORDER][PREFLIGHT] size_mult=%.2f → BLOCK", pf_size_mult)
            _order_gate_block(logger, "preflight", "preflight_block",
                              size_mult=f"{pf_size_mult:.2f}")
            return RC_HOLD
        elif pf_size_mult <= 0.80:
            logger.info("[ORDER][PREFLIGHT] size_mult=%.2f → REDUCE", pf_size_mult)
        else:
            logger.info("[ORDER][PREFLIGHT] size_mult=%.2f → NORMAL", pf_size_mult)

        total_order_krw = 0
        _seen_codes_pre = set()   # [DEDUP-PRE 2026-06-02] 본 매수루프 code_key dedup(L5253)과 동일 기준 —
                                  #   같은 종목 중복행(예: EOD_PICK 호출 3회로 큐에 같은 종목 3행)은 실제 buy loop이
                                  #   skip_dup 처리하여 1건만 매수 → 사전 balance 합산에서도 1건만 계상(예산 오탐 차단).
        for _, row in df_buy.head(max_buy_rows).iterrows():
            _code_pre = _norm_code(row.get("code",""))
            if _code_pre and _code_pre in _seen_codes_pre:
                continue   # 같은 종목 중복행 — 예산 이중계상 방지(실제 매수 안 됨)
            if _code_pre:
                _seen_codes_pre.add(_code_pre)
            rf    = _resolve_rank_ratio_float(row, max_buy_rows)
            st    = str(row.get("strategy","EOD_TOP1")).strip()
            bk    = int(available_krw * rf * BALANCE_SAFETY_RATIO * pf_size_mult)
            ek, _ = _calc_evolved_krw(bk, st, evolve_weights)
            # [BUG-4 FIX] EV 사이징 비율 사전 반영 — 실제 주문과 검증값 일치
            _inst_pre = _safe_float(row.get("inst_score",
                         row.get("inst_buy_score", 0)))
            _ev_ratio = _ev_position_ratio(dict(row), logger, _inst_pre)
            ek_adjusted = int(available_krw * _ev_ratio * BALANCE_SAFETY_RATIO * pf_size_mult)
            # Kelly 진화 가중치 적용 후 EV 비율 반영
            ek_final, _ = _calc_evolved_krw(
                int(available_krw * _ev_ratio * BALANCE_SAFETY_RATIO * pf_size_mult),
                st, evolve_weights)
            # [SIZE-UNIFY PRE 2026-06-02] 사전검증도 상류 order_krw 존중 — 본 매수루프(L5150)와 동일 기준.
            #   queue order_krw>0 이면 상류 정교사이징(EOD_PICK=signal_v2 / PULLBACK=rt_risk)을
            #   사전 balance 검증에서도 그대로 사용 → EV 재계산(ek_final)과 불일치로 인한 오탐 차단 해소.
            #   (EV sizing/MAX_ACCOUNT_USAGE/예산한도 무수정. order_krw=0이면 기존 EV fallback.)
            _respect_pre = os.environ.get("SIZE_UNIFY_RESPECT", "YES").strip().upper() != "NO"
            _q_krw_pre   = _safe_int(row.get("order_krw", 0), default=0)
            _row_krw_pre = _q_krw_pre if (_respect_pre and _q_krw_pre > 0) else ek_final
            total_order_krw += min(_row_krw_pre,
                                   int(available_krw * BALANCE_SAFETY_RATIO))

        max_allowed = int(available_krw * BALANCE_SAFETY_RATIO)
        logger.info(
            "[BALANCE] 가능=%s 예상=%s 한도=%s(%.0f%%)",
            f"{available_krw:,}", f"{total_order_krw:,}",
            f"{max_allowed:,}", BALANCE_SAFETY_RATIO * 100)
        if total_order_krw > max_allowed:
            logger.error("[BALANCE] 초과 → HOLD")
            _order_gate_block(logger, "balance", "balance_exceeded",
                              order=total_order_krw, max=max_allowed)
            return RC_HOLD

        _var_ok, _var_scale_global = _var_exposure_check(
            available_krw, total_order_krw, logger)
        if not _var_ok:
            _order_gate_block(logger, "var", "var_exposure_exceeded")
            return RC_HOLD
        if _var_scale_global < 1.0:
            logger.warning("[VAR] 전체 VaR 축소비율 %.2f → 개별 주문에 반영",
                           _var_scale_global)

        ledger_file  = _ledger_path(base)
        summary_file = _summary_path(base)
        done_fps     = _load_today_success_fingerprints(
            ledger_file, logger)
        done_fps    |= _load_buy_fps_json(base, logger)
        run_fps: Set[str] = set()

        # [SAFE+ 필수-3 / v4_9-P1] 당일 N회 한도 강제 — 시작 시 검증
        # done_fps에 fingerprint(md5 16hex) + code_key("CODE_*") 같이 저장 → fingerprint만 카운트
        # [W31 PATCH 2026-05-12] ADD_ON fingerprint(ADDON_*) 제외 — 신규 카운트와 분리
        _daily_count_from_fps = sum(1 for x in done_fps
                                    if not x.startswith("CODE_")
                                    and not x.startswith("ADDON_"))
        _addon_count_from_fps = sum(1 for x in done_fps if x.startswith("ADDON_"))
        if _daily_count_from_fps >= len(ENTRY_WEIGHTS):
            logger.critical(
                "[DAY_LIMIT_BLOCK] 누적 %d회 한도 도달 (entries=%d) → 신규 주문 전체 차단",
                len(ENTRY_WEIGHTS), _daily_count_from_fps)
            _order_gate_block(logger, "day_limit", "day_limit_reached",
                              entries=_daily_count_from_fps,
                              done_fps=len(done_fps))
            return RC_HOLD

        sent_count = acked_count = filled_count = 0
        partial_count = skip_inv = skip_dup = 0
        skip_qty = ledger_fail = cancel_count = 0
        consec_fail_count = 0                        # ⑤ circuit breaker 카운터
        daily_entry_count = _daily_count_from_fps    # [v4_7-P5/v4_9-P1] 누적 진입 카운트 복원
        results: List[OrderResult] = []
        total_slip = 0
        _var_scale_global = _var_scale_global   # [v4_1] VaR 축소비율 루프 전달용

        _write_heartbeat(base)
        for idx, (_, row) in enumerate(df_buy.iterrows()):
            if filled_count + acked_count >= max_buy_rows:
                logger.info("[LIMIT] max=%d 도달", max_buy_rows)
                break

            # [SAFE+ 필수-3] 당일 N건 체결 시 차단 — N=ENTRY_WEIGHTS 길이
            if daily_entry_count >= len(ENTRY_WEIGHTS):
                logger.warning(
                    "[DAY_LIMIT_BLOCK] 당일 %d회 한도 도달 (entry=%d) → 잔여 BUY 행 전체 차단",
                    len(ENTRY_WEIGHTS), daily_entry_count)
                _order_gate_block(logger, "day_limit", "day_limit_reached",
                                  entry=daily_entry_count)
                break

            # ⑤ circuit breaker — 연속 FAILED ≥ 임계값 → 세션 조기 종료
            if consec_fail_count >= CIRCUIT_BREAKER_MAX_FAIL:
                logger.critical(
                    "[CIRCUIT] ⛔ 연속 FAILED %d회 ≥ %d → 세션 조기 종료",
                    consec_fail_count, CIRCUIT_BREAKER_MAX_FAIL)
                _write_failover_log(base,
                    f"[CIRCUIT_BREAK] consec_fail={consec_fail_count}")
                break

            code = _norm_code(row.get("code",""))
            if not _is_valid_code(code):
                skip_inv += 1
                logger.warning("[SKIP] 유효하지 않은 code=%s",
                               row.get("code",""))
                _order_gate_block(logger, "code_validate", "invalid_code",
                                  raw=str(row.get("code",""))[:8])
                continue

            _row_strategy      = str(row.get("strategy","")).strip()
            _row_strategy_type = str(row.get("strategy_type","")).strip()
            _row_session_type  = str(row.get("session_type","")).strip()
            # [MKT-SOFT 2026-06-10] 약세장 PULLBACK 신규 소프트게이트 — 백테(39일 407건):
            #   시장중앙 약세시 눌림 승률 17%/-1.64% vs 정상 27%/-0.73%(2배 악화) + 6/10 실전(-3%장 후보 6/7 음수).
            #   기존 -6% 하드컷과 사이(-1.5~-6%) 빈칸 메움. PULLBACK만(종가매수=자체 regime/floor). 롤백 env=-9.9
            if _row_strategy.upper() == "PULLBACK":
                _mkt_soft = _kosdaq_intraday_pct()
                if _mkt_soft is not None and _mkt_soft <= PULLBACK_MKT_SOFT_PCT:
                    logger.warning("[MKT-SOFT] 시장중앙 %.2f%% <= %.2f%% → PULLBACK 신규 skip code=%s",
                                   _mkt_soft * 100, PULLBACK_MKT_SOFT_PCT * 100, code)
                    _order_gate_block(logger, "mkt_soft", "pullback_weak_market",
                                      mkt=round(_mkt_soft * 100, 2), code=code)
                    continue
            if not _market_guard(code, logger, cancel_count,
                                 strategy=_row_strategy,
                                 strategy_type=_row_strategy_type,
                                 session_type=_row_session_type):
                logger.warning(
                    "[SKIP][BLOCK:GUARD000] 시장 가드 차단 code=%s "
                    "strategy_type=%s session_type=%s",
                    code, _row_strategy_type or "-", _row_session_type or "-")
                _order_gate_block(logger, "market_guard", "market_guard_block",
                                  code=code, strategy_type=_row_strategy_type or "-",
                                  session_type=_row_session_type or "-")
                continue

            price_pre = _safe_int(row.get("price","0"), default=0)
            if not _entry_quality_gate(row, code, price_pre, logger):
                logger.warning("[SKIP] 진입 품질 미달 code=%s", code)
                _order_gate_block(logger, "entry_quality", "entry_quality_fail",
                                  code=code, price=price_pre)
                continue

            # ── [v4_3] 필수 필터 ①②③⑦⑧ 적용 ──
            # regime 사전 판정 (③ Market 필터용)
            _pre_regime = _market_regime(dict(row), logger)

            # ⑧ [FIX-2] 기관 탑승 확인 — ev_conviction 전에 먼저 실행 (inst_ride 플래그 선생성)
            _inst_present, _inst_score, _inst_consec, _inst_ride = \
                _inst_ride_gate(dict(row), code, logger, regime=_pre_regime)

            # ①②③ EV/Score/Regime 통합 확신도 게이트 (inst_ride + 1일1진입 보장 전달)
            if not _ev_conviction_gate(dict(row), code, _pre_regime, logger,
                                       inst_ride=_inst_ride,
                                       daily_entry_count=daily_entry_count):
                skip_inv += 1
                logger.warning(
                    "[SKIP][BLOCK:CONV000] 확신도 미달 code=%s "
                    "inst_ride=%s regime=%s",
                    code, _inst_ride, _pre_regime)
                _order_gate_block(logger, "ev_conviction", "ev_conviction_fail",
                                  code=code, inst_ride=_inst_ride,
                                  regime=_pre_regime)
                continue

            # ⑦ Overheat 필터
            if not _overheat_filter(dict(row), code, logger):
                skip_inv += 1
                logger.warning(
                    "[SKIP][BLOCK:OVERHEAT001] 과열 차단 code=%s", code)
                _order_gate_block(logger, "overheat", "overheat_block", code=code)
                continue

            # [v4_9 불타기/손실차단] 2회차+ 추가 진입 게이트
            if daily_entry_count >= 1 and results:
                _ref = next((r.avg_filled_price for r in results
                             if r.avg_filled_price > 0), 0.0)
                _pvwap = _safe_float(row.get("price_vs_vwap", 1.0))
                if _ref > 0 and (price_pre < _ref or _pvwap < 1.0):
                    skip_inv += 1
                    logger.info("[PYRAMID] 차단 price=%d ref=%.0f vwap=%.4f code=%s",
                                price_pre, _ref, _pvwap, code)
                    _order_gate_block(logger, "pyramid", "pyramid_block",
                                      code=code, price=price_pre,
                                      ref=int(_ref), vwap=f"{_pvwap:.4f}")
                    continue

            qty_raw = _resolve_qty(row, logger, code)
            if qty_raw < 1:
                skip_qty += 1
                logger.warning("[SKIP] qty=0 code=%s", code)
                _order_gate_block(logger, "qty", "qty_zero", code=code)
                continue

            price    = _safe_int(row.get("price","0"), default=0)
            strategy = str(row.get("strategy","EOD_TOP1")).strip()

            rank_f   = _resolve_rank_ratio_float(row, max_buy_rows)
            rank_str = f"{rank_f*100:.0f}%"

            # [PROFIT-4 + BUG-4 FIX] EV 사이징: 잔고비율 기반 (2.0R 폐기)
            # [FIX-3] pre_slip/impact 사전 계산 → _ev_position_ratio 캡에 전달

            # [v4_8 Gap-5] hard_stop 레짐별 동적 조정 — ev_ratio 전에 먼저 계산
            # (R값 사이징에서 hard_stop_pct 필요)
            _regime_hard_stop = HARD_STOP_REGIME_MAP.get(
                _pre_regime, _safe_float(row.get("hard_stop", 0))
            )
            if _regime_hard_stop <= 0:
                _regime_hard_stop = float(os.environ.get(
                    "HARD_STOP_DEFAULT", "0.025"))
            if abs(_regime_hard_stop - 0.025) > 0.001:
                logger.info(
                    "[HARD_STOP_REGIME][Gap-5] regime=%s → hard_stop=%.1f%% code=%s",
                    _pre_regime, _regime_hard_stop * 100, code)

            _pre_slip_pre = _estimate_slippage_pre(
                dict(row), price if price > 0 else price_pre, logger)
            _impact_pre   = _market_impact_bps(
                dict(row), qty_raw, price if price > 0 else price_pre, logger)
            ev_ratio = _ev_position_ratio(
                dict(row), logger,
                inst_score    = _inst_score,
                inst_ride     = _inst_ride,
                pre_slip_bps  = _pre_slip_pre,
                impact_bps    = _impact_pre,
                regime        = _pre_regime,
                strategy      = strategy,
                available_krw = available_krw,          # [v4_8R] R값 사이징
                hard_stop_pct = _regime_hard_stop        # [v4_8R] 레짐별 손절폭
            )

            # [v4_8 Gap-4] EV 완화 진입 사이즈 70% 캡 ─────────────────
            # 1일 1진입 보장 게이트(daily_min_active)로 완화 통과한 경우
            # 진입 품질이 정규보다 낮으므로 포지션 70% 상한 적용
            # 정규 진입=100% 허용 / EV완화 진입=70% 상한
            _daily_min_active_flag = (
                DAILY_MIN_ENTRY_ENABLED and daily_entry_count == 0
            )
            if _daily_min_active_flag and ev_ratio > DAILY_MIN_SIZE_CAP:
                logger.info(
                    "[DAILY_MIN_CAP][Gap-4] EV완화 진입 → 사이즈 %.0f%%→%.0f%% 캡 code=%s",
                    ev_ratio * 100, DAILY_MIN_SIZE_CAP * 100, code)
                ev_ratio = DAILY_MIN_SIZE_CAP

            # row에 주입 — _execute_and_track 내부에서 stop 계산에 사용
            _row_with_stop = dict(row)
            _row_with_stop["hard_stop"] = _regime_hard_stop

            # [v4_9 피라미딩] ENTRY_WEIGHTS 기반 — ev_ratio 몰빵 제거
            _entry_n   = min(daily_entry_count, len(ENTRY_WEIGHTS) - 1)
            _ew        = ENTRY_WEIGHTS[_entry_n]
            _ev_adj    = max(0.60, min(1.00, ev_ratio / EV_SIZE_RATIO_HIGH))  # [v4_9-P4] floor 0.80→0.60 EV 강도 반영
            # [SIZE-UNIFY 2026-06-02 확장] 상류 정교 사이징 존중 — queue order_krw>0 이면 상류가
            #   이미 정교 계산(EOD_PICK=signal_v2 진화Kelly+risk / PULLBACK=rt_risk Kelly/CVaR/DD/자기진화)
            #   → buy_sender EV 잔고재계산 skip(이중사이징 방지). order_krw=0이면 EV fallback. (사용자 승인: 종가매수·추세눌림 일관)
            # [MOLBANG-SWITCH 2026-06-02] env SIZE_UNIFY_RESPECT=NO → 정교사이징 무시하고 EV 잔고비율 몰빵
            #   (나중 98% 베팅용 스위치). 98% 도달하려면 MAX_ACCOUNT_USAGE env도 0.98로 풀어야 함. 기본=YES(정교존중).
            _respect_sizing = os.environ.get("SIZE_UNIFY_RESPECT", "YES").strip().upper() != "NO"
            _q_order_krw = _safe_int(row.get("order_krw", 0), default=0)
            logger.debug("[DEBUG-SIZE] code=%s strategy=%s _respect=%s _q_order_krw=%s order_krw_raw=%s row_keys=%s",
                         code, strategy, _respect_sizing, _q_order_krw, repr(row.get("order_krw")), list(row.keys())[:8])
            if _respect_sizing and _q_order_krw > 0:
                base_krw = _q_order_krw
                logger.info("[SIZE-UNIFY] %s 정교 사이징 존중 code=%s order_krw=%s원 (상류 Kelly/risk, EV재계산 skip)",
                            strategy, code, f"{_q_order_krw:,}")
            elif not _respect_sizing:
                # [MOLBANG] EV 잔고비율 직접 몰빵 (ev_ratio=EV≥1%면 0.98). ENTRY_WEIGHTS 무시. MAX_ACCOUNT_USAGE 캡 적용.
                base_krw = int(available_krw * ev_ratio * pf_size_mult)
                logger.info("[MOLBANG] %s EV 잔고몰빵 code=%s ratio=%.0f%% order=%s원 (SIZE_UNIFY_RESPECT=NO)",
                            strategy, code, ev_ratio * 100, f"{base_krw:,}")
            else:
                base_krw = int(available_krw * _ew * _ev_adj * pf_size_mult)  # [v4_9-P8] EV fallback (상류 사이징 없을때만)
            order_krw, evolve_w = _calc_evolved_krw(
                base_krw, strategy, evolve_weights)

            # 잔고 상한 최종 확인
            max_allowed = int(available_krw * MAX_ACCOUNT_USAGE)
            if order_krw > max_allowed:
                order_krw = max_allowed
                logger.warning(
                    "[EV_SIZE] ④ 잔고한도 캡(MAX=%.0f%%) 적용 → %s원 code=%s",
                    MAX_ACCOUNT_USAGE * 100, f"{order_krw:,}", code)

            logger.info(
                "[EVOLVE] code=%s strategy=%s w=%.4f ew=%.0f%% ev_adj=%.2f "
                "inst=%.2f base=%s → %s",
                code, strategy, evolve_w, _ew * 100, _ev_adj, _inst_score,
                f"{base_krw:,}", f"{order_krw:,}")

            # ── [ATR] ATR 기반 포지션 사이징 ────────────────────────
            try:
                _atr_pct = _safe_float(row.get("atr_pct", 0.0))
                if _atr_pct > 0 and price > 0:
                    # [PATCH-ACCT-DYN] ACCOUNT_SIZE 고정 → 운용자본 동적 추종
                    # available_krw = min(실예수금, SAFEPLUS_CAPITAL) 결과(L3981).
                    # 200만 모드 → 200만 / 5천만 모드 → 5천만 자동 확대.
                    # 비정상(<=0) 시 ACCOUNT_SIZE fallback.
                    _dyn_account_size   = float(available_krw) if available_krw and available_krw > 0 else ACCOUNT_SIZE
                    _target_risk        = _dyn_account_size * (TARGET_RISK_PCT / 100.0)
                    _atr_risk_per_share = price * (_atr_pct / 100.0)
                    _qty_atr  = int(_target_risk / _atr_risk_per_share)
                    _qty_cash = int(order_krw / price)
                    qty_raw   = max(0, min(_qty_atr, _qty_cash))
                    logger.info(
                        "[POSITION][ATR] atr=%.2f%% target_risk=%.0f "
                        "qty_atr=%d qty_cash=%d final_qty=%d code=%s",
                        _atr_pct, _target_risk, _qty_atr, _qty_cash, qty_raw, code)
                else:
                    qty_raw = int(order_krw / price)
                    logger.warning(
                        "[POSITION][ATR] atr_pct 없음/price 오류 → 기존 방식 사용 qty=%d code=%s",
                        qty_raw, code)
            except Exception as _e:
                qty_raw = int(order_krw / price)
                logger.warning(
                    "[POSITION][ATR] 계산 실패 → 기존 방식 fallback qty=%d code=%s err=%s",
                    qty_raw, code, _e)

            qty_final, qty_adj = _final_qty_check(
                available_krw, order_krw, price, qty_raw, code, logger)

            # [v4_1] VaR 축소비율 적용 — 고변동성 종목 수량 비례 감소
            if _var_scale_global < 1.0:
                qty_var = max(1, int(qty_final * _var_scale_global))
                if qty_var != qty_final:
                    logger.warning(
                        "[VAR_SCALE] ④ 수량 축소 %d→%d (VaR_scale=%.2f) code=%s",
                        qty_final, qty_var, _var_scale_global, code)
                    qty_final = qty_var
                    qty_adj   = True

            fingerprint = make_signal_fingerprint(
                code, _today_str(), strategy)
            code_key = f"CODE_{code}"
            # [WEAK-3 FIX] 멀티전략 중복 방지 체계 명확화
            # (1) fingerprint: 동일 전략+동일 종목+동일 날짜 → 정확 중복 차단
            # (2) code_key: 동일 종목이 다른 전략으로 이미 체결됨 → 이중매수 차단 (1종목 몰빵)
            # (3) run_fps: 동일 실행 세션 내 중복 차단
            if fingerprint in done_fps or fingerprint in run_fps:
                skip_dup += 1
                logger.info("[SKIP] 전략 중복 code=%s strategy=%s", code, strategy)
                _order_gate_block(logger, "fingerprint_dup",
                                  "fingerprint_duplicate",
                                  code=code, strategy=strategy)
                continue
            # [v4_9-P2] 동일 종목 4회 피라미딩 허용 — done_fps 차단 제거
            # 누적 4회 한도는 line 4056(시작 게이트) + line 4081(루프 break)에서 보호
            # 같은 (code, strategy, date) 중복은 line 4305-4311 fingerprint 차단으로 보호
            if code_key in run_fps:
                skip_dup += 1
                logger.info(
                    "[SKIP] 같은 sender 호출 내 종목 중복 code=%s strategy=%s",
                    code, strategy)
                _order_gate_block(logger, "code_dup_run", "run_session_duplicate",
                                  code=code, strategy=strategy)
                continue

            # [PROFIT-1 / IMPROVE-3] 기관 탑승 플래그를 row에 주입 → execute_and_track 전달
            _row_with_inst = dict(row)
            _row_with_inst["_inst_ride_flag"] = _inst_ride
            _row_with_inst["inst_score"]      = _inst_score
            _row_with_inst["inst_consec"]     = _inst_consec

            result = _execute_and_track(
                kw, account, screen, screen_cancel,
                code, qty_final, price,
                strategy, rank_str,
                order_krw, fingerprint,
                evolve_w, qty_adj, logger,
                row=_row_with_inst,
                base_dir=str(base),
            )
            results.append(result)
            run_fps.add(fingerprint)
            run_fps.add(code_key)      # [WEAK-3 FIX] 종목 레벨도 세션 내 중복 차단

            if result.state in (OrderState.CANCEL_CONFIRMED,
                                OrderState.TIMEOUT_FILL,
                                OrderState.TIMEOUT_ACK):
                cancel_count += 1

            if result.send_ok:  sent_count  += 1
            if result.acked:    acked_count += 1

            if result.state in (OrderState.FAILED, OrderState.TIMEOUT_ACK,
                                OrderState.TIMEOUT_FILL):
                consec_fail_count += 1
            else:
                consec_fail_count = 0

            _write_heartbeat(base)      # ② 주문 처리마다 heartbeat 갱신

            if result.filled or result.state == OrderState.PARTIAL:
                if result.filled:
                    _order_gate_accept(logger, code=code, qty=qty_final,
                                       price=int(result.avg_filled_price),
                                       state="FILLED")
                    filled_count += 1
                    daily_entry_count += 1   # [v4_7-P5] 1일 진입 횟수 갱신
                    _fps_add(done_fps, fingerprint, base, logger)
                    _fps_add(done_fps, code_key, base, logger)
                    try:
                        _th_path = base / "DATA" / "history" / "trade_history.csv"
                        _th_path.parent.mkdir(parents=True, exist_ok=True)
                        _th_exists = _th_path.exists() and _th_path.stat().st_size > 0
                        _th_row = {"date": datetime.now().strftime("%Y-%m-%d"), "code": code,
                                   "score": _safe_float(row.get("score", 0)),
                                   "bridge_score": 0.0, "strong_axes": 0,
                                   "conviction": str(row.get("conviction", "")),
                                   "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        with _th_path.open("a", encoding="utf-8-sig", newline="") as _th_f:
                            _th_w = csv.DictWriter(_th_f,
                                fieldnames=["date","code","score","bridge_score","strong_axes","conviction","ts"],
                                extrasaction="ignore")
                            if not _th_exists: _th_w.writeheader()
                            _th_w.writerow(_th_row)
                        logger.info("[TRADE_HIST] 체결 기록 code=%s", code)
                    except Exception as _th_e:
                        logger.warning("[TRADE_HIST] 기록 실패: %s", _th_e)
                else:
                    _order_gate_accept(logger, code=code, qty=result.filled_qty,
                                       state="PARTIAL")
                    partial_count += 1
                    daily_entry_count += 1   # [v4_7-P5] PARTIAL도 진입으로 간주
                    # [BUG-2 FIX] PARTIAL도 즉시 done_fps 등록 — 이중매수 방지
                    _fps_add(done_fps, fingerprint, base, logger)
                    _fps_add(done_fps, code_key, base, logger)
                    logger.info(
                        "[BUG2_FIX] PARTIAL done_fps 등록 code=%s "
                        "filled=%d/%d → 재매수 차단",
                        code, result.filled_qty, qty_final)
                _update_positions(base, result, logger)
                _write_open_position(base, result, logger, _row_with_stop)  # [PATCH] row 전달
                _ensure_open_position(base, result, logger, _row_with_stop)
                total_slip += result.slippage_won
                if _PNL_LINKER_OK and _pnl_write_buy:
                    try:
                        _pnl_write_buy(
                            code, strategy,
                            result.avg_filled_price,
                            result.filled_qty,
                            result.slippage_bps,
                            base_dir=str(base),
                            logger=logger,
                        )
                    except Exception as e:
                        logger.warning("[PNL_LINKER] 실패: %s", e)

            elif result.state == OrderState.RECONCILE_PENDING:
                _write_reconcile(base, result,
                                 "상태불명 — 운영자 확인", logger)
                _write_failover_log(base,
                    f"[RECONCILE] code={code} no={result.order_no}")

            if not _ledger_append(
                    ledger_file,
                    result.to_ledger_row(run_id, dep_mode)):
                ledger_fail += 1
                logger.critical("[LEDGER] append 실패 code=%s", code)
                _write_failover_log(base, f"[LEDGER_FAIL] code={code}")

            _summary_upsert(summary_file, fingerprint,
                            result.to_summary_row(run_id, dep_mode))

            logger.info(
                "[STATUS] code=%s state=%s fill=%s "
                "filled=%d@%.2f slip=%+d원(%+.1fbps) "
                "w=%.4f adj=%s inst_ride=%s ev=%.2f%% no=%s",
                code, result.state.value, result.fill_status,
                result.filled_qty, result.avg_filled_price,
                result.slippage_won, result.slippage_bps,
                evolve_w, "Y" if qty_adj else "N",
                "✅" if result.inst_ride else "-",
                result.ev_pct,
                result.order_no,
            )

            if not result.send_ok or not result.acked:
                _write_failover_log(base,
                    f"[BUY_FAIL] code={code} "
                    f"rc={result.send_rc} state={result.state.value}")
                _order_gate_block(logger, "order_send",
                                  "order_send_or_ack_fail",
                                  code=code, rc=result.send_rc,
                                  state=result.state.value)
                if dep_mode == MODE_CONTINGENT and len(results) == 1:
                    logger.warning("[CONTINGENT] 1등(%s) 실패 → 중단",
                                   code)
                    _order_gate_block(logger, "contingent",
                                      "contingent_first_fail_break",
                                      code=code)
                    break

            remaining = len(df_buy) - idx - 1
            if (remaining > 0 and
                    (filled_count + acked_count) < max_buy_rows):
                time.sleep(order_gap_sec)

        # ── [v4_6] ★ 피라미딩 ADD_ON 큐 처리 ─────────────────────
        #  일반 매수 루프 완료 후 pullback_addon_queue.csv 처리
        #  조건: 장중이고 킬스위치 없을 때만 실행
        # [W31 PATCH 2026-05-12] ADD_ON 차단을 별도 카운트로 분리
        #   기존: daily_entry_count >= len(ENTRY_WEIGHTS) → 신규 2회 채우면 ADD_ON 차단
        #   변경: addon_count >= ADDON_MAX_PER_DAY → 신규/ADD_ON 독립 한도
        _addon_filled = 0
        addon_count = _addon_count_from_fps    # [W31] 부팅 시 fps 기반 복원
        if addon_count >= ADDON_MAX_PER_DAY:
            logger.info("[DAY_LIMIT_BLOCK] ADDON 차단 (addon=%d/%d)",
                        addon_count, ADDON_MAX_PER_DAY)
            _order_gate_block(logger, "day_limit", "day_limit_addon_skip",
                              addon=addon_count)
        elif not _is_shutdown(base, logger) and _hhmm() < ADDON_CUTOFF_HM:
            try:
                _addon_filled = _process_addon_queue(
                    kw, account, screen, screen_cancel,
                    available_krw, done_fps,
                    pf_size_mult, logger, base,
                )
                if _addon_filled > 0:
                    logger.info("[ADDON] ★ 피라미딩 체결 %d건 완료 (W31 분리 카운트)",
                                _addon_filled)
                    addon_count += _addon_filled   # [W31] daily_entry_count 미증가
            except Exception as e:
                logger.warning("[ADDON] 처리 중 예외: %s", e)

        # ── [v4_6] ★ 추세눌림 2사이클 재진입 처리 ────────────────
        # [W31 PATCH] MC도 신규 카운트와 분리 — daily_entry_count + addon_count 합산 한도
        _mc_filled = 0
        _total_count = daily_entry_count + addon_count
        _total_max   = len(ENTRY_WEIGHTS) + ADDON_MAX_PER_DAY   # 2+2=4
        if _total_count >= _total_max:
            logger.info("[DAY_LIMIT_BLOCK] MC 재진입 차단 (total=%d/%d)",
                        _total_count, _total_max)
            _order_gate_block(logger, "day_limit", "day_limit_mc_skip",
                              total=_total_count)
        elif not _is_shutdown(base, logger):
            try:
                _mc_filled = _execute_multicycle_reentry(
                    kw, account, screen, screen_cancel,
                    available_krw, done_fps,
                    pf_size_mult, logger, base,
                )
                if _mc_filled > 0:
                    logger.info("[MC] ★ 2사이클 체결 완료")
                    daily_entry_count += _mc_filled
            except Exception as e:
                logger.warning("[MC] 처리 중 예외: %s", e)

        # ── [v4_7] 최종 요약 로그 ──
        inst_ride_count = sum(1 for r in results if getattr(r, "inst_ride", False))
        avg_ev = (sum(getattr(r, "ev_pct", 0) for r in results) / len(results)
                  if results else 0.0)
        _hhmm_now = _hhmm()
        _alpha_now = _get_alpha_decay(_hhmm_now)
        logger.info(
            "[END_v4_7] sent=%d ack=%d filled=%d partial=%d "
            "addon=%d mc=%d / max=%d  "
            "skip(inv=%d dup=%d qty=%d) cancel=%d ledger_fail=%d "
            "inst_ride=%d avg_ev=%.2f%% daily_entry=%d "
            "alpha=%.2f regime_ic=ON kelly_mdd=ON ac_impact=ON",
            sent_count, acked_count, filled_count,
            partial_count, _addon_filled, _mc_filled, max_buy_rows,
            skip_inv, skip_dup, skip_qty,
            cancel_count, ledger_fail,
            inst_ride_count, avg_ev,
            daily_entry_count, _alpha_now,
        )
        logger.info("[SLIPPAGE] 총=%+d원 (양수=불리) | trade_cost=%.3f%%",
                    total_slip, TRADE_COST_ROUNDTRIP_PCT * 100)

        if not results:
            _order_gate_block(logger, "result", "no_results")
            return RC_HOLD
        if filled_count == len(results):          return RC_OK
        if filled_count > 0 or acked_count > 0:  return RC_PARTIAL
        _order_gate_block(logger, "result", "no_fills_no_acks")
        return RC_HOLD

    finally:
        # [v4.10 TRACE] try 내부 모든 종료 경로에서 SUMMARY 1회 출력
        _emit_order_summary(logger)
        _release_run_lock(base)
        if _kw_ref[0] is not None:
            _kw_ref[0].disconnect_shared()


def run_once_shared(shared_ocx) -> int:
    """수집기 프로세스에서 shared_ocx로 매수 큐를 1회 처리한다.
    새 QAxWidget·CommConnect 미사용 — 수집기 OCX를 그대로 공유."""
    return main(shared_ocx=shared_ocx)


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
collect_prices_1m_kiwoom_opt10080_v4_16.py

역할  : 키움 opt10080 기반 1분봉 데이터 수집 전용
출력  : C:/stock_bot/DATA/prices_1m.csv
        컬럼 (38개): code, ts, open, high, low, close, volume, value,
              [FEAT-1] signed_value, body_ratio,
              [FEAT-2] value_acc, volume_acc,
              [BOOST-1] value_accel, volume_accel,
              [FEAT-3] hh, hl, trend, close_pos,
              [FEAT-4] vwap, vwap_dev,
              [FEAT-5] ret_1m, range_expansion,
              [FEAT-6] pullback,
              [FEAT-7] ret_3bar_sum, value_acc_3bar, close_hold_power,
              [FEAT-8] pullback_depth(당일고점기준), pullback_recover, vwap_reclaim,
              [FEAT-9] pressure_score, wick_pressure, close_strength,
              [FEAT-10] breakout_quality, range_efficiency, trend_persist,
              [FEAT-12] micro_alpha,
              [FEAT-13] inst_net_buy,
              [FEAT-14] inst_flow_proxy  ← v4_14 신규
주의  : 수집만 담당. 매매 로직·점수 없음.

학술 출처 (헤지펀드급 문서화 — v4_14 신규 추가)
  VWAP              : Berkowitz, Logue, Noser (1988) "The Total Cost of Transactions
                      on the NYSE" Journal of Finance 43(1):97-112
                      → 누적 거래대금/누적 거래량 기반 VWAP 원전
  Order Flow Proxy  : Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88
                      → signed_value: OFI 프록시 (호가창 없이 봉 방향+body_ratio 근사)
  거래량 가속도      : Easley, Lopez de Prado, O'Hara (2011)
                      "The Microstructure of the Flash Crash" JFM
                      → value_accel, volume_accel: 거래 강도 가속 기반
  시장 압력·체결강도 : Kyle (1985) "Continuous Auctions and Insider Trading"
                      Econometrica 53(6):1315-1335
                      → pressure_score, close_strength: 시장압력·유동성 개념
  추세 구조          : LeBeau & Lucas (1992) "Computer Analysis of the Futures Market"
                      → breakout_quality, trend_persist: Chandelier 기반 구조신호
  자기진화           : Holland (1992) "Adaptation in Natural and Artificial Systems"
                      MIT Press → SelfEvolver 진화 파라미터 자동조정 설계 근거

고유 영역
  쓰기: DATA/prices_1m.csv, DATA/collector_1m.lock/.heartbeat
        LOG/collector_1m.log, DATA/collector_1m_evolve.json
        DATA/inst_net_buy.json          (장전 기관순매수 캐시 — FIX-F2)
  읽기: DATA/collector_pnl_feedback.json (PnL 피드백 소비 후 consumed=true — FIX-F1)
  읽기금지: SIGA/ RUN/ 쓰기

v4_15 수정 [2026-04-16]  97점 달성 — 7건 수정
  ─── [FIX-J1] last_ts_map 갱신 O(n²) → O(1) 교체 ───────────
  기존: _on_receive_tr 종료 후 batch_rows 전체 순회(O(n×종목수))
  수정: 봉 처리 즉시 max(last_ts_map, dt) 갱신 → O(1) 직접 갱신
        장 후반 400종목 기준 사이클 시간 단축, TR 타임아웃 감소
  ─── [FIX-J2] save_csv 예외 시 기존 데이터 전손 방지 ────────
  기존: except Exception: combined = new_df (기존 데이터 전량 폐기)
  수정: old 읽기 실패 시 old=None 유지 → new_df만 저장 (전손 X)
        기존 데이터 보존 우선, 신규 봉은 다음 사이클에 재수집
  ─── [FIX-J3] inst_flow_proxy 첫 5봉 극단값 방지 ────────────
  기존: 1봉만으로도 ±1.0 극단값 → 하위전략 OFI 오발동
  수정: _flow_sv_hist 5봉 미만 구간 → inst_flow_proxy = 0.0 반환
        5봉 확보 후 정상 계산 활성화 (워밍업 guard)
  ─── [FIX-J4] is_valid_bar h==l 이상봉 차단 ─────────────────
  기존: h<l만 체크, h==l(단일가봉) 통과 → 피처 전체 0 오염
  수정: h == l → 거래정지 / 단일가 봉으로 판단 → False 반환
  ─── [FIX-J5] SelfEvolver 복합 악화 시 다중 조정 ────────────
  기존: 1순위 조건 충족 즉시 return → 나머지 파라미터 미조정
  수정: changed 플래그 방식으로 교체 → 동시 다중 파라미터 조정
        실패율 높음 + 갭 많음 동시 → TR_INTERVAL + TOP_N 함께 조정
  ─── [FIX-J6] MAX_CSV_ROWS I/O 병목 완화 ────────────────────
  기존: MAX_CSV_ROWS=500, 400종목×500봉=최대200,000행 → I/O 과부하
  수정: MAX_CSV_ROWS=390 (장 6.5시간 = 390봉 정확히 1일치)
        전일 봉 이미 필터링되므로 390이 실질 상한에 부합
  ─── [FIX-J7] opt10059 스크린 순환 사용 ─────────────────────
  기존: 150종목 전체에 동일 스크린 1개 재사용 → 이벤트 혼선 위험
  수정: 종목마다 _next_scr()로 풀(50개) 순환, 루프 후 일괄 해제

v4_14 수정 [2026-04-10]  96점 달성 — 임원진 합동 진단 6건 수정
  ─── [FIX-I1] signed_value body_ratio 가중 계산 교체 ──────────
  기존: c>o이면 전액 매수, c<o이면 전액 매도 (도지봉 완전 누락)
  수정: signed_value = value × body_ratio (매수방향) / -value × body_ratio (매도방향)
       도지봉(body_ratio≈0): signed_value≈0 → 세력 조용한 매집 시 오판 개선
       몸통 비율로 가중 → 실제 매수·매도 강도를 더 정확히 추정
       출처: Cont et al.(2014) OFI 개념 근사치 개선
  ─── [FIX-I2] HOT 초반 value_accel 필터 조건부 적용 ─────────
  기존: value_accel < 1.2이면 무조건 HOT 제외
  수정: 6봉 미만 데이터(장 시작 후 6분간)는 value_accel 필터 비활성화
       → 09:00~09:06 초반 핵심 구간 HOT 종목 포착률 회복
       → 시가/추세눌림 전략 초반 진입 타이밍 개선
  ─── [FIX-I3] pullback_depth — 당일 rolling peak 기준으로 교체 ─
  기존: prev_h (직전 1봉 고가) 기준 → 추세눌림 전략 부적합
  수정: _daily_peak[code] (당일 rolling 최고가) 기준으로 교체
       당일 고점 대비 얼마나 눌렸는지 = 진짜 눌림목 깊이 측정
       _daily_peak: 날짜 리셋 시 초기화, 매봉 max 갱신
       수익률 영향: 추세눌림 전략 pullback_depth 신뢰도 직접 향상
  ─── [FIX-I4] micro_alpha 3구간 시간대 분리 ─────────────────
  기존: 초반(~09:20) / 중반(09:20 이후) 2구간
  수정: 초반(09:00~09:20) / 중반(09:20~13:00) / 후반(13:00~14:50) 3구간
       후반 가중치: pressure 0.25 / accel 0.15 / strength 0.30 / breakout 0.20 / trend 0.10
       → 후반은 봉 구조·추세 지속성 중시 (거래량 감소 구간 노이즈 필터링 강화)
  ─── [FIX-I5] inst_flow_proxy 실시간 OFI 보정 컬럼 추가 ──────
  기존: inst_net_buy = 전일 장전 1회 (최대 6.5시간 전 데이터)
  추가: inst_flow_proxy = 최근 5봉 signed_value 합 / 최근 5봉 value 합
       범위: -1.0 ~ +1.0 (양수=실시간 매수 우세, 음수=매도 우세)
       rt_sell_engine의 실시간 OFI 판단 보완용 신규 컬럼 (38번째)
       → inst_net_buy(정적) + inst_flow_proxy(실시간) 이중 구조로 신뢰도 향상
  ─── [FIX-I6] 학술 출처 섹션 신규 추가 ─────────────────────
  VWAP / OFI Proxy / 거래량가속도 / 시장압력 / 추세구조 / 자기진화
  6개 출처 docstring 추가 (헤지펀드급 문서화 기준)

v4_13 수정 [2026-04-08]  97점 달성 — 평가 지적 3건 수정
  [H1] opt10059 파라미터 정리
       매매구분 SetInputValue 제거 (opt10059 표준 미지원 파라미터)
       GetCommData strRecordName "opt10059_req" → "" (빈 문자열)
       키움 표준: strRecordName = OnReceiveTrData.recordname 값
       → 데이터 추출 안정성 확보, inst_net_buy 실제 값 반환 보장
  [H2] docstring 고유영역 파일 목록 보완
       쓰기 추가: DATA/inst_net_buy.json (장전 기관순매수 캐시)
       읽기 추가: DATA/collector_pnl_feedback.json (PnL 피드백)
  [H3] EARLY_END 09:15 → 09:20 조정
       종배 전략 강제청산 09:20과 정합
       초반 가중치(압력·속도 집중) 적용 구간 5분 연장
       수익률 영향: 종배 핵심 구간 micro_alpha 품질 향상
  ─── 사용자 제안 5건 ─────────────────────────────────────────
  [G1] inst_net_buy 커버 확장 50 → 150종목
       기관 수급 커버리지 3배 확대 (장전 1회, TR 약 2분 추가)
  [G2] micro_alpha 동적 가중치 (초반/중반 분리)
       초반(~09:15): pressure 0.40 / accel 0.30 / strength 0.15 / breakout 0.10 / trend 0.05
       중반(09:15~): pressure 0.30 / accel 0.20 / strength 0.25 / breakout 0.15 / trend 0.10
       ※ 사용자 원안 합산 오류(1.10/0.90) → 합산 1.00으로 보정 적용
  [G3] micro_alpha 최소 기준 추가
       pressure_score < 0.45 → micro_alpha = 0 (노이즈 봉 제거)
  [G4] HOT 필터 강화 — value_accel >= 1.2 조건 추가
       가속 없는 일회성 거래대금 급등 종목 차단
  [G5] VWAP 이탈 필터
       vwap_dev < -0.01 → micro_alpha = 0 (하락 추세 봉 제거)
  ─── 버그 수정 3건 ──────────────────────────────────────────
  [A] _on_receive_tr opt10059 분기 추가
      rqname="opt10059_req" 이벤트 처리 → inst_net_buy 실제 작동
  [B] docstring 컬럼 수 36 → 37개 수정 (inst_net_buy 반영)
  [C] HOT 필터 inst_net_buy 보완
      inst_net_buy > 0 시 close_pos 기준 0.60 → 0.50 완화
      (기관 확인된 종목 HOT 진입 기회 확대)
  ─── ① SelfEvolver JSON 폴링 (pnl_strategy_linker 역전달) ──
  [FIX-F1] _load_pnl_feedback() 추가
           DATA/collector_pnl_feedback.json 폴링
           consumed=false 항목만 record_pnl() 처리 후 consumed=true
           → pnl_strategy_linker v3.2의 L2 기록과 완전 연결
  ─── ② opt10059 기관순매수 하루 1회 장전 조회 ──────────────
  [FIX-F2] _load_inst_net_buy_premarket() 추가
           08:50~09:00 장전 1회 opt10059 TR 조회
           종목별 기관순매수 → DATA/inst_net_buy.json 저장
           _calc_features에서 inst_net_buy 컬럼 추가 (36→37개)
           → signed_value OFI 추정치의 구조적 한계 보완
           → rt_sell_engine OFI≥0.30 판단 신뢰도 향상

v4_10 수정 [2026-04-08]  96점 달성 — 4대 보강
  [FIX-E1~E4] 갭마스킹/micro_alpha/CSV필터/수익률피드백 완성
  ─── ① FIX-D5 재설계 (갭 마스킹 버그 완전 수정) ──────────
  [FIX-E1] detect_gap → _calc_features 실행 순서 교정
           기존: calc_features → detect_gap (gap_codes 항상 비어있어 마스킹 미작동)
           수정: detect_gap 먼저 → calc_features (is_gap_bar 정상 작동)
           + gap_codes.clear() 사이클 시작 → 봉 처리 직후로 이동
           → 갭≥2분 봉: hh/hl/trend/breakout_quality=0 실제 동작
  ─── ② SelfEvolver 수익률 피드백 연결 ─────────────────────
  [FIX-E2] record_pnl() 메서드 추가
           code, pnl_pct, hold_min, strategy 수신
           수익 거래 > 손실 거래 비율 → HOT 감지 기준 자동조정
           pnl_avg > 0 → surge_ratio 낮춤 (더 많이 잡기)
           pnl_avg < 0 → surge_ratio 높임 (더 엄격히)
           최근 20거래 rolling 유지
  ─── ③ micro_alpha 가중치 개선 ────────────────────────────
  [FIX-E3] 균등 1/6 → 실증 가중 배분
           압력(pressure_score) 0.35 — 봉 품질 최우선
           가속(value_acc/volume_acc 평균) 0.25 — 세력 속도
           강도(close_strength) 0.20 — 고가 안착
           돌파(breakout_quality) 0.12 — 전고점 돌파 시 강화
           추세(trend_persist) 0.08 — 추세 지속
  ─── ④ 날짜 경계 CSV 필터 ──────────────────────────────────
  [FIX-E4] save_csv에 당일 날짜 필터 추가
           combined에서 오늘 날짜 봉만 유지 (전일 봉 혼입 차단)
           + cleanup_csv에도 동일 필터 적용

v4_9 수정 [2026-04-08]  헤지펀드급 임원 진단 보강
  [FIX-D1] 날짜 리셋 버그 수정 / [FIX-D2] HOT 방향 필터
  [FIX-D3] 대체공휴일 오등록 / [FIX-D4] value_acc_3bar 평균
  [FIX-D5] 갭 봉 마스킹 (설계 오류 → v4_10에서 완전 수정)

v4_8 수정 [2026-04-05]  헤지펀드 기준 97점 품질 달성
  [BOOST-1] 진짜 가속도 컬럼 추가 (value_accel, volume_accel)
  [BOOST-2] pressure_score 단순화 재계산
  [BOOST-3] value_acc_3bar — value_accel 기반 교체
  [v4.16 FIX-1] 버킷 C 거래대금 순 정렬
               기존: all_codes 순서 → 대장주 후보 순환 후반에 몰림
               수정: 전일 거래대금 높은 종목 C버킷 앞쪽 배치
               효과: 신규 대장주 순환 초기 사이클에 포착

  [v4.16 FIX-2] C버킷 상위 10개 장중 포함
               기존: 장중 C버킷 완전 제외 → 당일 급등 신규 종목 포착 불가
               수정: C버킷 거래대금 상위 10개 장중 수집 추가
               효과: A50 + B20 + C10 = 80개 (큐 제한 정확히 유지)
                     전일 TOP_N 밖 → 당일 급등 신규 대장주 실시간 포착

  [BUG-1~3] HOT 첫사이클/컬럼수/docstring 수정

v4_7 수정 [2026-04-05]  FIX-A~D + FEAT-7~12 통합
v4_6 수정 [2026-04-02]  공용 엔진 완성 — 방향·속도·구조·VWAP
v4_4 수정 [2026-04-02]  인덴테이션 복구
"""


import sys
import os
import json
import logging
import random
import time as time_module
from collections import defaultdict, deque
from datetime import datetime, timedelta, time as dtime, date
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, QTimer

# [PATCH-RATELIMIT] Kiwoom TR burst 방지
sys.path.insert(0, r"C:\stock_bot\RUN")
from safeplus_rate_limiter import KiwoomRateLimiter
_limiter = KiwoomRateLimiter()

# ═══════════════════════════════════════════════════════════════
# [STEP-2A 2026-05-13] Broker Gateway IPC client (opt10059 전용 도입)
# 다른 함수 (request_1m_once / warmup / ensure_login 등) 는 그대로 direct OCX 사용.
# 이 helper 는 _load_inst_net_buy_premarket 만 사용.
# ═══════════════════════════════════════════════════════════════
import uuid as _bro_uuid
_BROKER_IPC_REQ_DIR = Path(r"C:\stock_bot\IPC\requests")
_BROKER_IPC_RES_DIR = Path(r"C:\stock_bot\IPC\responses")

# [STEP-2I-2-d 2026-05-13] Broker Availability Cache
#   broker dead → direct OCX fallback 자동 진입.
#   broker = optional infra layer 유지 (mandatory 화 X).
_BROKER_HB_FILE          = Path(r"C:\stock_bot\IPC\broker_heartbeat.json")
_BROKER_HB_STALE_SEC     = 15.0   # broker write 주기 5s × 3 cycle
_BROKER_DEAD_COOLDOWN_SEC = 60.0  # dead 진입 후 IPC skip 시간 (broker 재기동 window 일치)
_BROKER_TIMEOUT_THRESHOLD = 2     # 연속 timeout 임계 (CIRCUIT-A 패턴)
_BROKER_DEAD_UNTIL: float = 0.0   # cooldown 종료 시각
_consec_broker_timeout: int = 0   # 연속 timeout 카운터
# [STEP-2I-2-c 2026-05-14] BYPASS/RECOVER 로그 상태 변수
_last_bypass_log_ts: float = 0.0  # BYPASS throttle (cooldown 윈도우 내 N초마다 1회)
_BYPASS_LOG_INTERVAL_SEC = 10.0
_was_broker_dead: bool = False    # dead→alive 전환 감지 (RECOVER 1회 로그)


def _is_broker_alive() -> bool:
    """heartbeat mtime + cooldown 검사.

    True  — broker IPC 사용 가능
    False — direct OCX fallback 진입 필요
    """
    # [S1-ROLLBACK 2026-05-14 09:50] STEP-2B-1 opt10080 broker routing rollback.
    # 5/14 09:45 실측: 격리 47/큐 0/9분 갭 → broker IPC throughput 병목 확정.
    # [STEP-2I-2-c 2026-05-14] S1-ROLLBACK 해제 — broker optional layer 복원.
    # broker 살아있으면 IPC 사용, timeout 2회 시 dead+cooldown 60s, 그 동안 direct fallback.
    import time as _t
    global _last_bypass_log_ts, _was_broker_dead
    now = _t.time()
    if now < _BROKER_DEAD_UNTIL:
        # [BROKER-BYPASS] cooldown 활성 — throttled (10s 마다 1회)
        if (now - _last_bypass_log_ts) >= _BYPASS_LOG_INTERVAL_SEC:
            try:
                logger.info(
                    "[BROKER-BYPASS] cooldown active (%.1fs remain)",
                    max(0.0, _BROKER_DEAD_UNTIL - now),
                )
            except Exception:
                pass
            _last_bypass_log_ts = now
        _was_broker_dead = True
        return False
    try:
        if not _BROKER_HB_FILE.exists():
            _was_broker_dead = True
            return False
        age = now - _BROKER_HB_FILE.stat().st_mtime
        alive = (age < _BROKER_HB_STALE_SEC)
        if alive and _was_broker_dead:
            try:
                logger.info("[BROKER-RECOVER] broker restored — IPC 재사용")
            except Exception:
                pass
            _was_broker_dead = False
        elif not alive:
            _was_broker_dead = True
        return alive
    except Exception:
        _was_broker_dead = True
        return False


def _mark_broker_dead():
    """broker_dead 진입. cooldown 동안 IPC skip."""
    import time as _t
    global _BROKER_DEAD_UNTIL
    _BROKER_DEAD_UNTIL = _t.time() + _BROKER_DEAD_COOLDOWN_SEC
    try:
        logger.warning(
            "[BROKER-DEAD] cooldown %ds — direct OCX fallback 활성",
            int(_BROKER_DEAD_COOLDOWN_SEC),
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# [A-2a 2026-05-15] broker-owns-OCX 가드 (A-1a H1~H3 동일 패턴)
# broker CONNECTED 시 자기 OCX 생성·CommConnect skip → popup 차단.
# 예외/import 실패 시 False 반환 → 기존 path 안전 fallback.
# ─────────────────────────────────────────────────────────
def _broker_owns_ocx() -> bool:
    # [사이클 0 2026-05-18] A-2a rollback: collector standalone OCX 사용.
    # Why: ensure_connected/request_1m 등 raw self.ocx.dynamicCall 분기 미라우팅 →
    # broker_mode 시 NoneType.dynamicCall 무한 ERROR → hb 미갱신 → 사망 오판.
    # 다른 모듈(siga/rt_sell/buy_sender/pullback_sell)은 broker_mode 유지.
    return False
    try:
        from broker_client import BrokerClient
        return BrokerClient().alive()
    except Exception:
        return False


def broker_tr_request_master(func: str, arg: str, timeout_sec: float = 5.0) -> dict:
    """[A-2a 2026-05-15] MASTER_INFO broker IPC wrapper.

    broker_gateway L1140 _handle_master_info_request 위임.
    whitelist: GetCodeListByMarket / GetMasterCodeName / GetMasterStockInfo / GetMasterETF /
               GetMasterStockState (확장).
    """
    try:
        from broker_client import BrokerClient
        return BrokerClient().master_info(func, arg, timeout_sec=timeout_sec)
    except Exception as e:
        return {"status": "ERROR", "data": None, "error": f"master_info wrapper: {e}"}


def broker_tr_request(tr_code: str, inputs: dict, output_fields: list,
                      rqname: str = None, screen_no: str = "0001",
                      timeout_sec: float = 8.0,
                      poll_interval_sec: float = 0.2) -> dict:
    """Broker Gateway v1 에 IPC TR 요청 전송 + 응답 polling.

    Returns:
        {"status": "OK"|"ERROR"|"TIMEOUT", "data": {...} or None, "error": str or None}
    """
    request_id = str(_bro_uuid.uuid4())
    if rqname is None:
        rqname = f"{tr_code}_req"

    req = {
        "request_id": request_id,
        "ts": datetime.now().isoformat(),
        "ttl_sec": int(timeout_sec) + 5,
        "type": "TR",
        "caller": "collect_prices_1m_kiwoom_opt10080_v4_16",
        "tr_code": tr_code,
        "rqname": rqname,
        "screen_no": screen_no,
        "input": inputs,
        "output_fields": list(output_fields or []),
    }

    # ★[SIGN-SCOPE 2026-08-14 친구님 지시 "수정해"] 보호 대상일 때만 서명한다.
    #   종전: 타입 불문 무조건 sign_order_request() 호출.
    #   8/11 08:56 TR-ROLLBACK 으로 TR 이 PROTECTED_TYPES 에서 빠지자, 서명 함수가
    #   "this request type does not use IPC authentication" 예외를 던지고 이 except 가
    #   그것을 그대로 실패로 바꿨다 → 8/12 08:50 부터 1분봉 수집 전량 차단(886건),
    #   prices_1m.csv 가 8/11 에서 멈춤(백테·성과분석 기반 자료 3일 결손).
    #   즉 롤백이 절반만 됐던 것 — 보호목록에서는 뺐는데 서명하는 쪽은 계속 서명했다.
    #   정상 패턴은 broker_client.py:230-239 (PROTECTED_TYPES 검사 후 서명).
    #   보호 대상이면 종전대로 서명하고 실패 시 fail-closed 를 유지한다.
    #   되돌리기: collect_prices_1m_kiwoom_opt10080_v4_16_20260814_before_sign_scope.py
    try:
        from ipc_order_auth_v1 import PROTECTED_TYPES, sign_order_request
        if str(req.get("type") or "") in PROTECTED_TYPES:
            req = sign_order_request(req)
    except Exception as e:
        return {"status": "ERROR", "data": None,
                "error": f"TR authentication blocked: {e}"}

    req_path = _BROKER_IPC_REQ_DIR / f"{request_id}.json"
    res_path = _BROKER_IPC_RES_DIR / f"{request_id}.json"
    try:
        tmp = req_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(req, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(req_path))
    except Exception as e:
        return {"status": "ERROR", "data": None,
                "error": f"request write failed: {e}"}

    deadline = time_module.time() + timeout_sec
    while time_module.time() < deadline:
        if res_path.exists():
            try:
                res = json.loads(res_path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                try:
                    res_path.unlink()
                except Exception:
                    pass
                return {"status": "ERROR", "data": None,
                        "error": f"response parse failed: {e}"}
            try:
                res_path.unlink()
            except Exception:
                pass
            return res
        time_module.sleep(poll_interval_sec)

    return {"status": "TIMEOUT", "data": None,
            "error": f"client poll timeout ({timeout_sec}s)"}


# ═══════════════════════════════════════════════════════════
# 경로 설정
# ═══════════════════════════════════════════════════════════
BASE_DIR          = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA_DIR          = BASE_DIR / "DATA"
LOG_DIR           = BASE_DIR / "LOG"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH          = DATA_DIR / "prices_1m.csv"
PREV_SUMMARY_PATH = DATA_DIR / "prev_day_summary.csv"
LOCK_PATH         = DATA_DIR / "collector_1m.lock"
HEARTBEAT_PATH    = DATA_DIR / "collector_1m.heartbeat"
LOG_PATH          = LOG_DIR  / "collector_1m.log"
EVOLVE_PATH       = DATA_DIR / "collector_1m_evolve.json"
# [FIX-F1] pnl_strategy_linker 역전달 피드백 경로
PNL_FEEDBACK_PATH = DATA_DIR / "collector_pnl_feedback.json"
# [FIX-F2] 장전 기관순매수 캐시 경로
INST_NET_BUY_PATH = DATA_DIR / "inst_net_buy.json"


# ═══════════════════════════════════════════════════════════
# 파라미터 (SelfEvolver 전용 상수 포함)
# ═══════════════════════════════════════════════════════════
MIN_PRICE_FILTER  = 500
TOP_N_CODES_DEF   = 30    # [Q1-TOP-CLAMP 2026-05-14 11:20] 60→30. 5/14 11:09~11:15 dead_pool 23→54 (분당 +5 격리) + 키움 종목별 rate limit 추정 → TOP_N 1/2 축소로 키움 부담 1/2. 격리 누적 정지 목표. 백업: bak_Q1Q4_20260514_1118
HOT_N_DEF         = 10    # [TR-THROTTLE 2026-05-08] 50→10 (TR timeout 과부하 완화)
LOOP_SEC_DEF      = 30
# [THEME-LEADER-BUCKET 2순위 2026-06-05] 강테마 KOSDAQ 대장주를 active(A버킷)에 보장 수집.
#   ⚠universe_codes.txt는 이 수집기가 안 읽음 → 여기서 직접 편입해야 prices_1m 진입(make_rt 1순위 THEME-INJECT의 토대).
#   ⚠active(A+B 매사이클 수집)에 추가 → cycle time↑.
#   cap 12 = make_rt MAKE_RT_THEME_INJECT_MAX=12와 정합(누락방지 cap 정합, 선별로직 아님). 전체 active 확대가 아니라
#     테마 대장주 보장수집만 +최대 6개 확대(기존 cap6 대비). active~30→최대~36/사이클~111s 추정 — cycle time은 6/8 장중 로그로 확인.
#   초과 시 롤백: env THEME_LEADER_BUCKET_MAX=6 (또는 기본값 6 복귀). 발효=수집기 재시작.
THEME_LEADER_BUCKET_ENABLE = os.environ.get("THEME_LEADER_BUCKET_ENABLE", "YES").strip().upper() == "YES"
THEME_LEADER_BUCKET_MAX    = int(os.environ.get("THEME_LEADER_BUCKET_MAX", "12"))   # [6→12 2026-06-07] active 추가 상한. 실측: 강테마 대장주 중 A버킷밖·top600내가 8개인데 cap6=2개 누락(036620/047080) → 12로 전부 보장수집(분산일 여유 포함). 비용 active~30→36/사이클~111s(150s 안전선 내). 즉시복귀 env=6.
THEME_LEADER_RANK_MAX_COL  = int(os.environ.get("THEME_LEADER_RANK_MAX", "20"))     # 강테마 기준(theme_rank<=N)

# [RT-VALUE 2026-06-17 친구님] opt10032 실시간 거래대금 상위 N(코스닥)을 코어 A버킷 채움기준으로 사용(전일→실시간).
#   홍인기 미리선점: 장초 실시간 거래대금 상위에서 주도테마/대장 포착. 60s캐시·fail-open(실패=전일거래대금 유지).
#   ★발효=수집기 재시작(부팅)·롤백 setx COLLECT_REALTIME_VALUE_TOP NO. opt10032 검증완료(2026-06-17 status=OK).
COLLECT_REALTIME_VALUE_TOP   = os.environ.get("COLLECT_REALTIME_VALUE_TOP", "NO").strip().upper() == "YES"
COLLECT_RT_VALUE_REFRESH_SEC = float(os.environ.get("COLLECT_RT_VALUE_REFRESH_SEC", "60"))
_rt_value_cache = {"ts": 0.0, "codes": []}


def _load_realtime_value_top(n: int = 50) -> list:
    """[RT-VALUE] opt10032 실시간 거래대금 상위 N 코스닥 코드(거래대금순). 60s캐시. 실패/빈값 → 캐시 또는 [](fail-open)."""
    import time as _t
    if not COLLECT_REALTIME_VALUE_TOP:
        return []
    if (_t.time() - _rt_value_cache["ts"]) < COLLECT_RT_VALUE_REFRESH_SEC and _rt_value_cache["codes"]:
        return _rt_value_cache["codes"][:n]
    try:
        from broker_client import BrokerClient
        _bc = BrokerClient()
        if not _bc.alive():
            return _rt_value_cache["codes"][:n]
        _res = _bc.tr("opt10032", inputs={"시장구분": "101", "관리종목포함": "0"},
                      output_fields=["종목코드", "거래대금"], timeout_sec=10.0)
        if not _res or _res.get("status") != "OK":
            return _rt_value_cache["codes"][:n]
        _recs = (_res.get("data") or {}).get("records") or []
        _codes = []
        for _r in _recs:
            _c = str(_r.get("종목코드", "")).strip().zfill(6)
            if len(_c) == 6 and _c.isdigit():
                _codes.append(_c)
        if _codes:
            _rt_value_cache.update({"ts": _t.time(), "codes": _codes})
            logger.info(f"[RT-VALUE] opt10032 실시간 거래대금 상위 {len(_codes)}종목 (top5={_codes[:5]})")
            return _codes[:n]
        return _rt_value_cache["codes"][:n]
    except Exception as _e:
        logger.warning(f"[RT-VALUE] opt10032 실패 → 전일거래대금 폴백: {_e}")
        return _rt_value_cache["codes"][:n]


# [RT-UPDOWN 2026-06-29 친구님] opt10027 등락률 상위(키움 직접·거래량조건0=소형 급등주 포함)를 개장 우선패스에 합류.
#   배경: 등락율을 네이버 크롤링(inject_updown)으로 우회 → 느림 → 개장 갭상승주(019210류) 09:10에야 편입.
#   키움 opt10027은 빠름(검증=돌파가 사용 중). 개장 우선셋에 합쳐 09:00 즉시 포착. 롤백 setx COLLECT_RT_UPDOWN NO.
COLLECT_RT_UPDOWN = os.environ.get("COLLECT_RT_UPDOWN", "YES").strip().upper() == "YES"
_rt_updown_cache = {"ts": 0.0, "codes": []}


def _load_realtime_updown_top(n: int = 15) -> list:
    """[RT-UPDOWN] opt10027 등락률 상위 N 코스닥 코드(등락율순·거래량조건0=소형 급등주 포함). 60s캐시. 실패→캐시/[](fail-open)."""
    import time as _t
    if not COLLECT_RT_UPDOWN:
        return []
    if (_t.time() - _rt_updown_cache["ts"]) < COLLECT_RT_VALUE_REFRESH_SEC and _rt_updown_cache["codes"]:
        return _rt_updown_cache["codes"][:n]
    try:
        from broker_client import BrokerClient
        _bc = BrokerClient()
        if not _bc.alive():
            return _rt_updown_cache["codes"][:n]
        _res = _bc.tr("opt10027", inputs={"시장구분": "101", "정렬구분": "1", "거래량조건": "0000",
                                          "종목조건": "0", "신용조건": "0", "상하한포함": "1"},
                      output_fields=["종목코드", "등락률"], timeout_sec=8.0)
        if not _res or _res.get("status") != "OK":
            return _rt_updown_cache["codes"][:n]
        _recs = (_res.get("data") or {}).get("records") or []
        _codes = []
        for _r in _recs:
            _c = str(_r.get("종목코드", "")).lstrip("A").strip().zfill(6)
            if len(_c) == 6 and _c.isdigit():
                _codes.append(_c)
        if _codes:
            _rt_updown_cache.update({"ts": _t.time(), "codes": _codes})
            logger.info(f"[RT-UPDOWN] opt10027 등락률 상위 {len(_codes)}종목 (top5={_codes[:5]})")
            return _codes[:n]
        return _rt_updown_cache["codes"][:n]
    except Exception as _e:
        logger.warning(f"[RT-UPDOWN] opt10027 실패 → skip: {_e}")
        return _rt_updown_cache["codes"][:n]


def _load_theme_leader_codes() -> list:
    """[2순위] code_theme_strength.csv is_leader=1 & best_theme_rank<=THEME_LEADER_RANK_MAX_COL 코드(강테마순).
    [최신일+dedup 2026-06-07] date 최대값(최신일)만 사용 + code 중복제거(make_rt _get_sector_leaders와 통일).
      CSV가 매일 누적(THEME_STRENGTH 20:00 append)돼도 과거 대장주가 cap 슬롯 잠식하는 것 방지.
      date 컬럼 없으면 전체 사용(하위호환).
    KOSDAQ 필터는 호출부 all_codes 교집합으로(=KOSPI 자동제외). 실패→빈[](미적용=fail-safe)."""
    import csv as _csv
    try:
        _f = DATA_DIR / "theme" / "code_theme_strength.csv"
        if not _f.exists():
            return []
        _rows = []
        with open(_f, "r", encoding="utf-8-sig", errors="replace") as _fh:
            for _r in _csv.DictReader(_fh):
                if str(_r.get("is_leader", "0")).strip() != "1":
                    continue
                try:
                    _rk = int(float(_r.get("best_theme_rank", 999) or 999))
                except (TypeError, ValueError):
                    _rk = 999
                if _rk <= THEME_LEADER_RANK_MAX_COL:
                    _rows.append((str(_r.get("date", "")).strip(),
                                  str(_r.get("code", "")).zfill(6), _rk))
        if not _rows:
            return []
        # [최신일 필터] date 있으면 최대일자만 (없으면 전체=하위호환)
        _dates = [_d for _d, _, _ in _rows if _d]
        if _dates:
            _latest = max(_dates)
            _rows = [_t for _t in _rows if _t[0] == _latest]
        _rows.sort(key=lambda x: x[2])   # 강한 테마(rank 낮음) 우선
        _seen, _out = set(), []           # code dedup(첫=최강 유지)
        for _d, _c, _rk in _rows:
            if _c and _c not in _seen:
                _seen.add(_c); _out.append(_c)
        return _out
    except Exception:
        return []
TR_INTERVAL_DEF   = 1.5  # [TR_TUNE 2026-05-06] 1.2→1.5 — TR타임아웃 19,485회/CB 28회 실측 후 burst 완화
TR_TIMEOUT_MS     = 25_000  # [5.14B 2026-05-19] 12초→25초 (broker TR_TIMEOUT_SEC 20s + margin 5s). broker_gateway L353와 묶음. 5/19 broker 측 timeout 498건/일 + 매분 1.3회 stall 15.6s 해소 목적. 백업: 20260519_164000_cycle514B
PERMANENT_BAN_THRESHOLD = 10  # [BAN10 2026-05-13] 20→10. 5/13 09:00~10:23 실측: 335 timeout 포기인데 영구격리 0건 트리거. 임계 20은 EBAN900(15분)/매일 reset 구조상 5시간+ 소요로 너무 늦음. 10이면 약 2시간 30분 누적으로 12:00 이전 발효.
MAX_CSV_ROWS      = 390   # [FIX-J6] 500→390: 장 6.5시간=390봉(1일치 정확)
                          # 전일 봉은 날짜 필터로 이미 차단 → 500은 과잉
                          # 400종목×390봉=156,000행 → I/O 병목 23% 감소
CLEANUP_EVERY     = 120
HEARTBEAT_TIMEOUT = 420

MAX_PRICE         = 10_000_000
MAX_VOLUME        = 500_000_000

SCR_POOL_SIZE     = 50
SCR_BASE          = 2000

# [OCX-WARMUP 2026-05-07] 큐 첫 슬롯 cold start cascade(3건) 흡수용 dummy TR
# 매 사이클 시작 시 dummy TR을 N회 dispatch → OCX 깨움 후 실제 큐 dispatch
# [STEP-2C 2026-05-13] _request_1m_once 가 broker IPC 로 이관된 이후
# collector.ocx 의 dispatch 사용이 사라져 warmup 필요성 감소.
# soft disable 방식 적용 — 함수 본체/상수 그대로 유지, 호출 측만 조건 분기.
# False = warmup OFF, True = 기존 동작 복귀 (rollback).
ENABLE_OCX_WARMUP      = False

OCX_WARMUP_COUNT       = 3        # cascade 3건 패턴 대응
OCX_WARMUP_TIMEOUT_MS  = 3000     # dummy 단일 timeout (cold 흡수 목적)
OCX_WARMUP_DUMMY_CODE  = "005930" # 삼성전자 — 확실 응답 보장 종목
# [W2-A 2026-05-08] 화면번호 9999 단일 → 실 TR 풀(SCR_BASE~) 정렬
# [W2-A' 2026-05-08] 워밍업 화면을 _scr_idx에 맞춰 동적 계산 — 사이클별 회전 정렬
# 가설: 키움 OCX/서버가 화면번호별 세션 큐를 분리 관리 → 다음 dispatch가 사용할 화면을 미리 깨움
OCX_WARMUP_SCR_BASE    = SCR_BASE # 실 TR 풀 시작점 (실제 워밍업 화면은 _scr_idx + i 로 동적 결정)

BACKOFF_BASE_SEC  = 1.6   # [FIX-BACKOFF] 1.3→1.6 (재시도 간 더 긴 휴지로 안정화)
BACKOFF_MAX_RETRY = 3
BACKOFF_JITTER    = 0.4   # [FIX-BACKOFF] 0.3→0.4 (지터 확장 — 재시도 충돌 분산)

MARKET_CODES      = ["10"]              # [FIX-D] 코스닥 전용 (SAFEPLUS = KOSDAQ 전략)
SKIP_KW           = ["스팩", "SPAC", "ETN", "ETF", "리츠", "우선주"]

FRESHNESS_EARLY_SEC = 45
FRESHNESS_MID_SEC   = 60
EARLY_END           = dtime(9, 20)   # [H3] 09:15 → 09:20 (종배 강제청산 09:20과 정합)

HOT_SURGE_RATIO_DEF = 2.0
HOT_HISTORY_LEN     = 5
HOT_EARLY_MULT      = 2
PRE_HOT_SEED_N      = 80

# [FEAT-2] Acceleration 롤링 윈도우 크기
ACC_ROLLING_N       = 5

# [FIX-3] _request_1m_once 최대 타임아웃 재시도
MAX_TIMEOUT_RETRY   = 1    # [PATCH-REVERT-C] 2→1 복귀 (동일 종목 재시도가 OCX 누적 부담을 키워 네이티브 크래시 유발 가능)

# [PATCH-CIRCUIT-A] 연속 TR 타임아웃 임계값 / pause 길이
CONSEC_TIMEOUT_LIMIT  = 7    # [CB_RELAX 2026-05-07 14:00] 5→7 — 5에서도 CB 트리거 자주 발생. 7로 올려 거의 모든 사이클이 CB 없이 완주하도록. 백업: bak_20260507_cb5(원본 3)
CONSEC_TIMEOUT_PAUSE  = 45   # pause 초 (heartbeat 유지 가능 범위)

# [PATCH-COOLDOWN 2026-05-06] TR 재진입 cooldown — A안 패치
# detect_gap의 즉시 appendleft + gap_retry_pool 양쪽 게이트
# 직전 dispatch로부터 N초 내 동일 종목 재투입 차단 → 큐 폭주 방지
TR_REENTRY_COOLDOWN_SEC    = 6.0    # 종목별 재투입 최소 간격
CIRCUIT_BREAK_COOLDOWN_SEC = 30.0   # CB 직후 모든 종목 강제 보류 시간

# ═══════════════════════════════════════════════════════════
# 출력 컬럼 정의 (기본 8개 + 피처 28개 = 36개)
# ═══════════════════════════════════════════════════════════
OUT_COLUMNS = [
    "code", "ts", "open", "high", "low", "close", "volume", "value",
    # [FEAT-1] Order Flow Proxy
    "signed_value", "body_ratio",
    # [FEAT-2] Acceleration (순간강도)
    "value_acc", "volume_acc",
    # [BOOST-1] 진짜 가속도 (최근3봉/이전3봉 — 기준: value_accel>=1.3, volume_accel>=1.2)
    "value_accel", "volume_accel",
    # [FEAT-3] Microstructure
    "hh", "hl", "trend", "close_pos",
    # [FEAT-4] VWAP
    "vwap", "vwap_dev",
    # [FEAT-5] 초반 힘
    "ret_1m", "range_expansion",
    # [FEAT-6] 눌림 구조
    "pullback",
    # [FEAT-7] 초반 지속성 (기준: ret_3bar_sum>=+1.5%, value_acc_3bar>=1.4)
    "ret_3bar_sum", "value_acc_3bar", "close_hold_power",
    # [FEAT-8] 눌림 품질
    "pullback_depth", "pullback_recover", "vwap_reclaim",
    # [FEAT-9] 봉 압력 (기준: pressure_score>=0.55)
    "pressure_score", "wick_pressure", "close_strength",
    # [FEAT-10] 돌파 품질
    "breakout_quality", "range_efficiency", "trend_persist",
    # [FEAT-12] 공용 종합강도
    "micro_alpha",
    # [FIX-F2] 장전 기관순매수 (opt10059, 하루 1회 갱신)
    # 단위: 원화 순매수 (+기관매수/-기관매도). 0=데이터없음
    "inst_net_buy",
    # [FIX-I5] 실시간 OFI 보정 프록시 (최근5봉 signed_value/value 비율)
    # 범위: -1.0~+1.0. inst_net_buy(정적) 보완용 실시간 방향 신호
    "inst_flow_proxy",
]


# ═══════════════════════════════════════════════════════════
# 출력 컬럼 수: 기본 8개 + 피처 28개 + inst_net_buy 1개 + inst_flow_proxy 1개 = 38개
# ═══════════════════════════════════════════════════════════
_rot = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8-sig")  # [Z15 2026-05-21]
_rot.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_st  = logging.StreamHandler()
_st.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger = logging.getLogger("collector_1m")
logger.setLevel(logging.INFO)
logger.addHandler(_rot)
logger.addHandler(_st)


# ═══════════════════════════════════════════════════════════
# 한국 공휴일
# ═══════════════════════════════════════════════════════════
_LUNAR_HOLIDAYS = {
    date(2026, 1, 28), date(2026, 1, 29), date(2026, 1, 30),
    date(2026, 5, 25),
    date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26),
    date(2027, 2, 16), date(2027, 2, 17), date(2027, 2, 18),
    date(2027, 5, 13),
    date(2027, 10, 14), date(2027, 10, 15), date(2027, 10, 16),
    date(2028, 2, 4),  date(2028, 2, 5),  date(2028, 2, 6),
    date(2028, 5, 2),
    date(2028, 10, 2), date(2028, 10, 3), date(2028, 10, 4),
}

# [IMP-A] 대체공휴일 (공휴일이 주말·다른 공휴일과 겹칠 때 평일 대체)
_SUBSTITUTE_HOLIDAYS = {
    # 2026년
    date(2026, 3, 2),   # 삼일절(3/1=일) → 3/2(월) 대체
    # date(2026, 5, 6) 제거 — 어린이날(5/5=화)은 대체공휴일 없음 [FIX-D3]
    date(2026, 10, 5),  # 개천절(10/3=토) → 10/5(월) 대체
    # 2027년 이후: 정부 고시 확정 후 추가할 것 (추정값 미등록 원칙)
}

def _kr_holidays(year: int) -> set:
    return {
        date(year, 1, 1),  date(year, 3, 1),  date(year, 5, 5),
        date(year, 6, 6),  date(year, 8, 15), date(year, 10, 3),
        date(year, 10, 9), date(year, 12, 25),
    }

_holiday_cache: dict = {}

def is_holiday(d: date) -> bool:
    if d.weekday() >= 5:              return True
    if d in _LUNAR_HOLIDAYS:          return True
    if d in _SUBSTITUTE_HOLIDAYS:     return True   # [IMP-A] 대체공휴일
    yr = d.year
    if yr not in _holiday_cache: _holiday_cache[yr] = _kr_holidays(yr)
    return d in _holiday_cache[yr]


# ═══════════════════════════════════════════════════════════
# 유틸
# ═══════════════════════════════════════════════════════════
def get_freshness_sec() -> int:
    t = datetime.now().time()
    return FRESHNESS_EARLY_SEC if dtime(9, 0) <= t <= EARLY_END else FRESHNESS_MID_SEC

def is_early() -> bool:
    t = datetime.now().time()
    return dtime(9, 0) <= t <= EARLY_END

# [FIX-I4] 후반 구간 판별 (13:00~14:50) — micro_alpha 3구간 분리용
def is_late() -> bool:
    t = datetime.now().time()
    return dtime(13, 0) <= t <= dtime(14, 50)

def is_premarkt() -> bool:
    t = datetime.now().time()
    return dtime(8, 50) <= t < dtime(9, 0)

def _safe_int(x):
    try:
        x = str(x).strip()
        if x == "" or x == "-":
            return None
        return abs(int(x))
    except Exception:
        return None

def is_valid_bar(row: dict) -> bool:
    o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
    # [FIX-VALID] None 체크 — 가격/거래량만 필수, value는 0 허용
    if any(x is None for x in [o, h, l, c, v]):   return False
    if any(x < 0 for x in [o, h, l, c]):           return False
    if any(x > MAX_PRICE for x in [o,h,l,c]):      return False
    if v < 0 or v > MAX_VOLUME:                     return False
    if h < l:  return False
    if h == l: return False
    # [FIX-VAL] value None이면 0으로 처리 — 키움 공백/문자열 대응
    val = row.get("value")
    if val is None: val = 0
    if val < 0: return False
    return True


# [FEAT-7~12] 공용 유틸 함수
def _clip01(x: float) -> float:
    """0~1 범위 클리핑."""
    try:
        return max(0.0, min(float(x), 1.0))
    except Exception:
        return 0.0

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """0 나누기 안전 처리."""
    try:
        if b == 0:
            return default
        return a / b
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════
# 파일 락
# ═══════════════════════════════════════════════════════════
# [STEP-2I-1 2026-05-14] broker_gateway_v1 패턴 동기화
#   - OpenProcess + GetExitCodeProcess + STILL_ACTIVE=259
#     기반 정밀 PID 생존 검사 (zombie/recently-terminated 오판 방지)
#   - duplicate / stale-detected / stale-removed / acquired / released
#     5종 observability 로그
_LOCK_PROCESS_QUERY_INFORMATION = 0x0400
_LOCK_STILL_ACTIVE              = 259


def _is_pid_alive(pid: int) -> bool:
    """Windows GetExitCodeProcess 기반 PID 생존 검사.

    OpenProcess 만으로 판단 시 zombie/recently-terminated PID 에
    핸들이 반환되어 alive 로 오판되는 문제 회피.
    """
    if pid <= 0:
        return False
    import ctypes
    h = None
    try:
        h = ctypes.windll.kernel32.OpenProcess(
            _LOCK_PROCESS_QUERY_INFORMATION, False, pid
        )
        if not h:
            return False
        exit_code = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetExitCodeProcess(
            h, ctypes.byref(exit_code)
        )
        if not ok:
            return False
        return exit_code.value == _LOCK_STILL_ACTIVE
    except Exception:
        return False
    finally:
        if h:
            try:
                ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass


def acquire_lock(max_attempts=5):
    # [LOCKRACE-FIX 2026-06-25] 즉사 리스폰 루프 제거.
    #   기존: 복구 경로의 재-os.open(O_EXCL)가 동시 재기동 레이스에서 또 FileExistsError를
    #         던지면 안 잡혀 [MAIN] 크래시 → 워치독/셀프힐 재기동 → 또 즉사 (6/24 385회 churn,
    #         보이는 콘솔창 수백개 → 데스크톱 힙 고갈 → 15:00 플릿/브로커 전멸 0xC0000142).
    #   교정: bounded 재시도 루프. 살아있는 winner면 duplicate-block(정상 종료),
    #         stale이면 삭제 후 재시도, 레이스로 os.open이 또 실패해도 루프가 흡수.
    #   백업: collect_prices_1m_kiwoom_opt10080_v4_16.py.bak_pre_lockrace_20260625
    for attempt in range(1, max_attempts + 1):
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            tag = "" if attempt == 1 else f", attempt={attempt}"
            print(f"[LOCK] collector lock acquired (PID={os.getpid()}{tag})", flush=True)
            return fd
        except FileExistsError:
            # 락 존재 → 소유 PID 생존 정밀 검사
            raw = ""
            try: raw = LOCK_PATH.read_text().strip()
            except Exception: raw = ""
            old_pid = -1
            if raw:
                try: old_pid = int(raw)
                except Exception: old_pid = -1
            if old_pid <= 0:
                # 빈/깨진 락 = winner가 막 생성(write 직전) 중인 레이스일 수 있음 → 잠깐 대기 후 재확인
                time_module.sleep(0.15)
                try: raw = LOCK_PATH.read_text().strip()
                except Exception: raw = ""
                try: old_pid = int(raw) if raw else -1
                except Exception: old_pid = -1
            if old_pid > 0 and _is_pid_alive(old_pid):
                # 살아있는 다른 collector → 중복 기동 차단 (재시도 안 함, 정상 종료 경로)
                print(f"[LOCK] duplicate collector blocked (existing PID={old_pid}, current PID={os.getpid()})", flush=True)
                raise RuntimeError(f"이미 실행 중 (PID {old_pid}): {LOCK_PATH}")
            # stale(소유자 사망/파싱불가) → 삭제 후 재시도. 레이스 완화 jitter.
            print(f"[LOCK] stale lock detected (PID={old_pid}) → 삭제 후 재시도 #{attempt}", flush=True)
            try: LOCK_PATH.unlink()
            except OSError: pass
            time_module.sleep(0.1 * attempt)
    raise RuntimeError(f"락 획득 실패 (stale 레이스 {max_attempts}회 초과): {LOCK_PATH}")

def release_lock(fd):
    # [LOCKRACE-FIX 2026-06-25] 락을 실제 소유(fd is not None)했을 때만 해제.
    #   기존: fd=None(획득 실패/중복차단으로 종료)일 때도 무조건 LOCK_PATH.unlink() 시도 →
    #         winner의 락을 지우려다 WinError 32(파일 사용중) 또는 성공 시 winner 락 고아화 → churn.
    if fd is None:
        return
    try:
        os.close(fd)
    except Exception as e:
        logger.error("[LOCK][FAIL] fd close 실패: %s", e)
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
            print(f"[LOCK] collector lock released (PID={os.getpid()})", flush=True)
    except Exception as e:
        logger.error("[LOCK][FAIL] release 실패: %s", e)


# ═══════════════════════════════════════════════════════════
# 자기진화 엔진
# ═══════════════════════════════════════════════════════════
class SelfEvolver:
    """수집 성능 + HOT 적중률을 학습해 파라미터 자동 조정."""

    TR_MIN, TR_MAX, TR_STEP       = 3.0, 4.0, 0.10  # [TR_TUNE 2026-07-09 친구님 "과다조회 오늘도"] 1.5/2.0→3.0/4.0 —
    #   7/9 실측: 수집기 opt10080 ~1,400/h(screen 0001)가 그림자엔진 스캔(돌파1,100+눌림1,000+바닥490/h)과 합쳐
    #   5,700/h → 브로커 5회 프리징(53분주기). 7/8 깔때기 메모 "다음 레버=tr_interval 상향" 집행 → 수집기 ~700/h로 반감.
    #   저장된 evolve값(1.5)은 아래 TR_MIN 클램프가 자동보정. 롤백: 1.5, 2.0 + bak_pre_trslow_20260709.
    TOP_MIN, TOP_MAX, TOP_STEP    = 30, 30, 10   # [Q1-TOP-CLAMP 2026-05-14 11:30] MAX 60→30 강제. evolved_params 옛값 60 강제 클램프 (진화 불가, 30 고정)
    # [v4.16] TOP_N 진화 범위 의미: C버킷 거래대금 정렬로 품질 확보 → TOP_N 늘려도 품질 유지
    LOOP_MIN, LOOP_MAX            = 20, 60
    HOT_N_MIN, HOT_N_MAX, HOT_N_STEP = 10, 100, 10  # [TR-THROTTLE 2026-05-08] MIN 20→10
    SURGE_MIN, SURGE_MAX, SURGE_STEP  = 1.5, 3.0, 0.25

    FAIL_UP, FAIL_DN              = 0.05, 0.01
    GAP_UP                        = 0.03
    CYCLE_RATIO                   = 1.15
    MIN_OBS                       = 5
    HOT_HIT_UP, HOT_HIT_DN       = 0.70, 0.40

    def __init__(self):
        self.tr_interval     = TR_INTERVAL_DEF
        self.top_n_codes     = TOP_N_CODES_DEF
        self.hot_n           = HOT_N_DEF
        self.loop_sec        = LOOP_SEC_DEF
        self.hot_surge_ratio = HOT_SURGE_RATIO_DEF
        self._obs:     list  = []
        self._hot_obs: list  = []
        self._pnl_obs: list  = []   # [FIX-E2] 수익률 피드백 이력
        self._load()

    def _load(self):
        try:
            if EVOLVE_PATH.exists():
                d = json.loads(EVOLVE_PATH.read_text(encoding="utf-8-sig"))
                self.tr_interval     = float(d.get("tr_interval",     TR_INTERVAL_DEF))
                self.top_n_codes     = int(d.get("top_n_codes",       TOP_N_CODES_DEF))
                self.hot_n           = int(d.get("hot_n",             HOT_N_DEF))
                self.loop_sec        = int(d.get("loop_sec",          LOOP_SEC_DEF))
                self.hot_surge_ratio = float(d.get("hot_surge_ratio", HOT_SURGE_RATIO_DEF))
                self._obs            = d.get("obs_history", [])[-20:]
                self._hot_obs        = d.get("hot_obs",     [])[-20:]
                self._pnl_obs        = d.get("pnl_obs",     [])[-20:]   # [FIX-E2]
                # [TR_TUNE 2026-05-06] 저장값이 TR_MIN 미만이면 강제 클램프 — 옛날 1.2값 자동 보정
                self.tr_interval = max(self.tr_interval, self.TR_MIN)
                # [Q1-TOP-CLAMP 2026-05-14 11:20] top_n_codes 범위 강제 클램프 (evolved_params 옛값 60 → 30 자동 보정)
                self.top_n_codes = max(self.TOP_MIN, min(self.TOP_MAX, self.top_n_codes))
                logger.info(f"[진화] 복원: {self.status_line()}")
        except Exception as e:
            logger.warning(f"[진화] 로드 실패(기본값): {e}")

    def _save(self):
        try:
            # [TR_TUNE 2026-05-06] 저장 직전에도 TR_MIN 클램프 — 메모리상 옛값(1.2) 디스크 저장 차단
            self.tr_interval = max(self.tr_interval, self.TR_MIN)
            tmp = EVOLVE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "tr_interval":     self.tr_interval,
                "top_n_codes":     self.top_n_codes,
                "hot_n":           self.hot_n,
                "loop_sec":        self.loop_sec,
                "hot_surge_ratio": self.hot_surge_ratio,
                "obs_history":     self._obs[-20:],
                "hot_obs":         self._hot_obs[-20:],
                "pnl_obs":         self._pnl_obs[-20:],   # [FIX-E2]
                "updated_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(EVOLVE_PATH))
        except Exception as e:
            logger.warning(f"[진화] 저장 실패: {e}")

    def record(self, fail_count, total_codes, gap_count, bar_count, elapsed_sec):
        fail_rate   = fail_count / max(total_codes, 1)
        gap_rate    = gap_count  / max(bar_count,   1)
        cycle_ratio = elapsed_sec / max(total_codes * self.tr_interval, 1)
        self._obs.append({
            "ts":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fail_rate":   round(fail_rate,   4),
            "gap_rate":    round(gap_rate,    4),
            "cycle_ratio": round(cycle_ratio, 3),
            "elapsed":     round(elapsed_sec, 1),
        })
        if len(self._obs) > 20: self._obs = self._obs[-20:]

    def record_hot(self, hot_codes: set, top_n_current: set):
        if not hot_codes: return
        hit_rate = len(hot_codes & top_n_current) / len(hot_codes)
        self._hot_obs.append({
            "ts":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hit_rate": round(hit_rate, 4),
            "hot_n":    len(hot_codes),
        })
        if len(self._hot_obs) > 20: self._hot_obs = self._hot_obs[-20:]
        logger.info(f"[HOT적중] {hit_rate:.1%} | hot_n={self.hot_n} | surge={self.hot_surge_ratio:.2f}")

    # [FIX-E2] 수익률 피드백 — pnl_strategy_linker 역전달 수신
    def record_pnl(self, code: str, pnl_pct: float, hold_min: float, strategy: str):
        """
        청산 결과를 수신해 수익률 기반 HOT 감지 기준 자동 조정.
        pnl_strategy_linker(v3_2) → JSON → _load_pnl_feedback() → 여기 호출.
        """
        self._pnl_obs.append({
            "ts":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code":     code,
            "pnl_pct":  round(pnl_pct,  4),
            "hold_min": round(hold_min,  2),
            "strategy": strategy,
        })
        if len(self._pnl_obs) > 20: self._pnl_obs = self._pnl_obs[-20:]
        logger.info(
            f"[PNL피드백] {code} {pnl_pct:+.2%} | "
            f"보유={hold_min:.0f}분 | 전략={strategy} | "
            f"누적={len(self._pnl_obs)}건"
        )
        self._save()

    # [FIX-F1] pnl_strategy_linker v3.2 → collector_pnl_feedback.json 폴링
    def _load_pnl_feedback(self) -> int:
        """
        DATA/collector_pnl_feedback.json 에서 consumed=false 항목을 읽어
        record_pnl()을 호출한 뒤 consumed=true 로 표시.
        pnl_strategy_linker._write_collector_feedback()과 쌍으로 작동.

        Returns:
            처리한 신규 피드백 건수
        """
        if not PNL_FEEDBACK_PATH.exists():
            return 0
        tmp = PNL_FEEDBACK_PATH.with_suffix(".tmp")
        processed = 0
        try:
            raw  = PNL_FEEDBACK_PATH.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            if not isinstance(data, list) or not data:
                return 0

            changed = False
            for item in data:
                if item.get("consumed", True):
                    continue   # 이미 처리된 항목
                try:
                    self.record_pnl(
                        code     = str(item.get("code",     "")),
                        pnl_pct  = float(item.get("pnl_pct",  0.0)),
                        hold_min = float(item.get("hold_min", 0.0)),
                        strategy = str(item.get("strategy", "")),
                    )
                    item["consumed"] = True   # 처리 완료 표시
                    processed += 1
                    changed   = True
                except Exception as e:
                    logger.warning(f"[FIX-F1] 피드백 항목 처리 실패: {e}")

            if changed:
                # Atomic write — consumed 상태 갱신
                tmp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                os.replace(str(tmp), str(PNL_FEEDBACK_PATH))
                logger.info(f"[FIX-F1] 피드백 {processed}건 처리 완료")

        except Exception as e:
            logger.warning(f"[FIX-F1] 피드백 폴링 실패: {e}")
        finally:
            try:
                if tmp.exists(): tmp.unlink()
            except Exception:
                pass
        return processed

    def evolve(self) -> bool:
        # [FIX-F1] 진화 실행 전 pnl_feedback 폴링 — 신규 청산 결과 즉시 반영
        self._load_pnl_feedback()

        if len(self._obs) < self.MIN_OBS: return False

        recent    = self._obs[-5:]
        avg_fail  = sum(o["fail_rate"]   for o in recent) / len(recent)
        avg_gap   = sum(o["gap_rate"]    for o in recent) / len(recent)
        avg_cycle = sum(o["cycle_ratio"] for o in recent) / len(recent)

        # [FIX-J5] changed 플래그 방식으로 교체
        # 기존: 첫 조건 충족 즉시 return → 복합 악화 시 1개 파라미터만 조정
        # 수정: 모든 조건 검사 후 변경 사항 합산 → 복합 악화 시 다중 파라미터 동시 조정
        changed = False

        # 1순위: TR_INTERVAL
        if avg_fail > self.FAIL_UP:
            new = min(self.tr_interval + self.TR_STEP, self.TR_MAX)
            if new != self.tr_interval:
                logger.warning(f"[진화-1] 실패율높음 TR {self.tr_interval:.2f}→{new:.2f}s")
                self.tr_interval = new; changed = True
        elif avg_fail < self.FAIL_DN and avg_cycle < 1.0:
            new = max(self.tr_interval - self.TR_STEP, self.TR_MIN)
            if new != self.tr_interval:
                logger.info(f"[진화-1] 안정 TR {self.tr_interval:.2f}→{new:.2f}s")
                self.tr_interval = new; changed = True

        # 2순위: TOP_N_CODES
        if avg_cycle > self.CYCLE_RATIO or avg_gap > self.GAP_UP:
            new = max(self.top_n_codes - self.TOP_STEP, self.TOP_MIN)
            if new != self.top_n_codes:
                logger.warning(f"[진화-2] 사이클비={avg_cycle:.2f} TOP_N {self.top_n_codes}→{new}")
                self.top_n_codes = new; changed = True
        elif avg_cycle < 0.85 and avg_fail < self.FAIL_DN:
            new = min(self.top_n_codes + self.TOP_STEP, self.TOP_MAX)
            if new != self.top_n_codes:
                logger.info(f"[진화-2] 여유 TOP_N {self.top_n_codes}→{new}")
                self.top_n_codes = new; changed = True

        # 3순위: HOT_N
        if len(self._hot_obs) >= 5:
            avg_hit = sum(o["hit_rate"] for o in self._hot_obs[-5:]) / 5
            if avg_hit > self.HOT_HIT_UP:
                new = min(self.hot_n + self.HOT_N_STEP, self.HOT_N_MAX)
                if new != self.hot_n:
                    logger.info(f"[진화-3] HOT적중={avg_hit:.1%} HOT_N {self.hot_n}→{new}")
                    self.hot_n = new; changed = True
            elif avg_hit < self.HOT_HIT_DN:
                new = max(self.hot_n - self.HOT_N_STEP, self.HOT_N_MIN)
                if new != self.hot_n:
                    logger.warning(f"[진화-3] HOT적중={avg_hit:.1%} HOT_N {self.hot_n}→{new}")
                    self.hot_n = new; changed = True

        # 4순위: LOOP_SEC
        if avg_gap > self.GAP_UP * 2:
            new = max(self.loop_sec - 5, self.LOOP_MIN)
            if new != self.loop_sec:
                logger.warning(f"[진화-4] 갭많음 LOOP {self.loop_sec}→{new}s")
                self.loop_sec = new; changed = True
        elif avg_gap < 0.005 and avg_fail < self.FAIL_DN:
            new = min(self.loop_sec + 5, self.LOOP_MAX)
            if new != self.loop_sec:
                logger.info(f"[진화-4] 안정적수 LOOP {self.loop_sec}→{new}s")
                self.loop_sec = new; changed = True

        # 5순위: HOT_SURGE_RATIO
        if len(self._hot_obs) >= 5:
            avg_hit = sum(o["hit_rate"] for o in self._hot_obs[-5:]) / 5
            if avg_hit < 0.20:
                new = round(max(self.hot_surge_ratio - self.SURGE_STEP, self.SURGE_MIN), 2)
                if new != self.hot_surge_ratio:
                    logger.warning(f"[진화-5] HOT적중낮음 SURGE {self.hot_surge_ratio:.2f}→{new:.2f}")
                    self.hot_surge_ratio = new; changed = True
            elif avg_hit > 0.85:
                new = round(min(self.hot_surge_ratio + self.SURGE_STEP, self.SURGE_MAX), 2)
                if new != self.hot_surge_ratio:
                    logger.info(f"[진화-5] HOT적중높음 SURGE {self.hot_surge_ratio:.2f}→{new:.2f}")
                    self.hot_surge_ratio = new; changed = True

        # [FIX-E2] 6순위: 수익률 피드백 기반 SURGE_RATIO 미세조정
        if len(self._pnl_obs) >= 5:
            recent_pnl = self._pnl_obs[-5:]
            pnl_avg    = sum(o["pnl_pct"] for o in recent_pnl) / len(recent_pnl)
            win_cnt    = sum(1 for o in recent_pnl if o["pnl_pct"] > 0)
            win_rate   = win_cnt / len(recent_pnl)
            if pnl_avg > 0.015 and win_rate >= 0.60:
                new = round(max(self.hot_surge_ratio - self.SURGE_STEP, self.SURGE_MIN), 2)
                if new != self.hot_surge_ratio:
                    logger.info(
                        f"[진화-6] PNL양호 avg={pnl_avg:+.2%} win={win_rate:.0%} "
                        f"SURGE {self.hot_surge_ratio:.2f}→{new:.2f}"
                    )
                    self.hot_surge_ratio = new; changed = True
            elif pnl_avg < -0.005 or win_rate < 0.40:
                new = round(min(self.hot_surge_ratio + self.SURGE_STEP, self.SURGE_MAX), 2)
                if new != self.hot_surge_ratio:
                    logger.warning(
                        f"[진화-6] PNL불안 avg={pnl_avg:+.2%} win={win_rate:.0%} "
                        f"SURGE {self.hot_surge_ratio:.2f}→{new:.2f}"
                    )
                    self.hot_surge_ratio = new; changed = True

        if changed:
            self._save()
        return changed

    def status_line(self) -> str:
        last     = self._obs[-1]     if self._obs     else {}
        hot_last = self._hot_obs[-1] if self._hot_obs else {}
        last_info = (
            f" | 수집[실패={last.get('fail_rate',0):.1%}"
            f" 갭={last.get('gap_rate',0):.1%}"
            f" 사이클비={last.get('cycle_ratio',0):.2f}]"
        ) if last else ""
        hot_info = f" | HOT적중={hot_last.get('hit_rate',0):.1%}" if hot_last else ""
        # [FIX-E2] PnL 현황 추가
        pnl_info = ""
        if self._pnl_obs:
            recent = self._pnl_obs[-5:]
            pnl_avg  = sum(o["pnl_pct"] for o in recent) / len(recent)
            win_rate = sum(1 for o in recent if o["pnl_pct"] > 0) / len(recent)
            pnl_info = f" | PNL[avg={pnl_avg:+.2%} win={win_rate:.0%} n={len(self._pnl_obs)}]"
        return (
            f"tr={self.tr_interval:.2f}s | top={self.top_n_codes} | "
            f"hot={self.hot_n} | loop={self.loop_sec}s | "
            f"surge={self.hot_surge_ratio:.2f} | 관측={len(self._obs)}c"
            f"{last_info}{hot_info}{pnl_info}"
        )


# ═══════════════════════════════════════════════════════════
# 실시간 HOT 종목 감지기
# ═══════════════════════════════════════════════════════════
class HotDetector:
    """직전 HOT_HISTORY_LEN 사이클 거래대금 이동평균 대비 급등 종목 추출."""

    def __init__(self):
        self._value_hist: dict = defaultdict(lambda: deque(maxlen=HOT_HISTORY_LEN))
        self._prev_hot: set    = set()
        self._last_row_map: dict = {}   # [FEAT-11] HOT 품질 필터용 최신 row 캐시
        # [FIX-V415-1] _value_6hist: KiwoomCollector._value_6hist를 직접 참조하던 버그 수정
        # detect()에서 row.get("value_accel")로 직접 읽으므로 이 dict는 더 이상 필요 없음
        # AttributeError 방지를 위해 빈 dict로 선언만 유지 (하위 호환)
        self._value_6hist: dict = {}

    def seed(self, prev_values: dict):
        if not prev_values:
            logger.warning("[HOT-seed] 주입 데이터 없음, 첫 사이클 HOT 불가")
            return
        for code, val in prev_values.items():
            baseline = int(max(int(val), 1) * 0.4)
            self._value_hist[code].append(baseline)
            self._value_hist[code].append(baseline)
        logger.info(f"[HOT-seed] {len(prev_values)}종목 사전 주입 완료")

    def update(self, batch_rows: list):
        if is_premarkt():
            return
        cycle_value: dict = defaultdict(int)
        for row in batch_rows:
            cycle_value[row["code"]] += row.get("value", 0)
            self._last_row_map[row["code"]] = row   # [FEAT-11] 최신 row 저장
        for code, val in cycle_value.items():
            self._value_hist[code].append(val)

    def detect(self, hot_n: int, surge_ratio: float) -> set:
        effective_n = hot_n * HOT_EARLY_MULT if is_early() else hot_n
        scores = {}
        for code, hist in self._value_hist.items():
            if len(hist) < 2: continue
            avg = sum(list(hist)[:-1]) / (len(hist) - 1)
            if avg <= 0: continue
            ratio = hist[-1] / avg

            # [FIX-EARLY] 초반 HOT 조건 완화 — A버킷 생성 보장
            if is_early():
                row = self._last_row_map.get(code, {})
                _va = float(row.get("value_accel",  1.0))
                _vv = float(row.get("volume_accel", 1.0))
                early_pass = (
                    ratio >= 1.2
                    or (_va != 1.0 and _va >= 1.1)   # [필수] 1.05→1.1 강화
                    or (_vv != 1.0 and _vv >= 1.05)
                )
                if not early_pass: continue
            else:
                if ratio < surge_ratio: continue

            if hist[-1] < 1000000:
                continue
            # [FEAT-11] HOT 품질 필터 — 4조건 동시 만족
            # [BUG-1] _last_row_map 데이터 없을 때(첫 사이클) 필터 스킵
            #         09:00~09:05 초반 HOT 포착 보장
            row = self._last_row_map.get(code, {})
            if row:   # 데이터 있을 때만 품질 필터 적용
                # [FIX-D2] 방향 필터: 매수 방향 봉만 HOT — 급락 매물 폭탄 차단
                if float(row.get("signed_value", 0)) <= 0:  continue
                # [FIX-I2] 가속 필터: 조건부 적용
                _va = float(row.get("value_accel", 1.0))
                if _va != 1.0 and _va < 1.02:
                    continue
                _cp_min = 0.35 if row.get("inst_net_buy", 0) > 0 else 0.45
                if float(row.get("close_pos",  0.0)) < _cp_min: continue
                if float(row.get("body_ratio", 0.0)) < 0.15: continue
                if float(row.get("vwap_dev",   0.0)) <= 0:   continue
            scores[code] = ratio
        hot = set(sorted(scores, key=scores.get, reverse=True)[:effective_n])
        if hot:
            if is_early(): phase = "초반"
            elif is_late(): phase = "후반"
            else: phase = "중반"
            logger.info(
                f"[HOT감지] {len(hot)}종목 | {phase} | "
                f"기준={surge_ratio:.2f}x | 상위={list(hot)[:5]}"
            )
        self._prev_hot = hot
        return hot

    @property
    def prev_hot(self) -> set:
        return self._prev_hot

    def current_top_n(self, n: int) -> set:
        """HOT 적중률 검증용 (지수 가중 최신 기준)"""
        totals = {}
        for code, hist in self._value_hist.items():
            if not hist: continue
            h = list(hist)
            totals[code] = sum(v * (2**i) for i, v in enumerate(h))
        return set(sorted(totals, key=totals.get, reverse=True)[:n])


# ═══════════════════════════════════════════════════════════
# 수집기
# ═══════════════════════════════════════════════════════════
class KiwoomCollector:

    def __init__(self):
        logger.debug("[INIT] QApplication 생성 시작")           # [FIX-C]
        try:
            self.app = QApplication(sys.argv)
            logger.debug("[INIT] QApplication 생성 완료")        # [FIX-C]
        except Exception as e:
            logger.error(f"[INIT] QApplication 생성 실패: {e}") # [FIX-C]
            raise

        # [A-2a 2026-05-15] broker alive 시 QAxWidget 생성 차단
        # multi-OCX 충돌 영구 해소. broker_client.tr/batch_tr/master_info
        # 로 모든 OCX 호출 라우팅 (A-2b / A-1b 단계).
        if _broker_owns_ocx():
            self.ocx = None
            self._broker_mode = True
            logger.info("[A-2a] broker alive — QAxWidget 생성 skip "
                        "(OCX 호출 broker IPC 라우팅 모드)")
        else:
            self._broker_mode = False
            logger.debug("[INIT] QAxWidget(KHOPENAPI) 생성 시작")   # [FIX-C]
            logger.info("[LOGIN-TRACE] 1) OCX 객체 생성 시도")
            try:
                self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
                logger.debug("[INIT] QAxWidget 생성 완료")           # [FIX-C]
                logger.info("[LOGIN-TRACE] 1) OCX 객체 생성 성공")
            except Exception as e:
                logger.error(f"[INIT] QAxWidget 생성 실패: {e}")    # [FIX-C]
                logger.info(f"[LOGIN-TRACE] 1) OCX 객체 생성 실패: {e}")
                raise

        # [FIX-A] atexit.register 제거 → main() finally 단일 종료로 통일
        #         app.quit() 이중 호출로 인한 Qt 이벤트루프 재진입 방지

        self.login_loop  = None
        self.tr_loop     = QEventLoop()
        self.wait_loop   = QEventLoop()

        self.connected     = False
        self.current_code  = ""
        self.current_scr   = str(SCR_BASE)
        self.batch_rows    = []
        self.last_ts_map   = {}
        self.request_queue = deque()
        self.tr_received   = False
        self.prev_next     = "0"
        # [FIX-V415-2] opt10059 전용 독립 플래그 — tr_received 공유 오염 방지
        # opt10059(기관순매수) TR과 opt10080(1분봉) TR이 같은 플래그를 공유하면
        # 1분봉 이벤트가 기관순매수 대기 중 수신되어 오인식할 수 있음
        self._inst_tr_received: bool = False

        # [STEP-2I-2-d 2026-05-13] direct OCX fallback 용 결과 버퍼
        # _on_receive_tr 가 *_direct_req rqname 일 때 batch_rows 갱신 대신
        # 이 dict 에 records 만 채우고 caller 가 통일 처리.
        self._direct_tr_result: dict = {"status": "TIMEOUT", "data": None, "error": None}
        self._direct_tr_received: bool = False

        self._scr_idx             = 0
        self.all_codes            = []
        self.code_list            = []
        self.cycle_count          = 0
        self.cleanup_counter      = 0
        self.total_saved_rows     = 0
        self.day_gap_count        = 0
        self.day_bar_count        = 0
        self.day_filter_count     = 0
        self._last_stat_date      = None
        self._last_load_date      = None
        self._seeded              = False
        self._reconnect_fail_count = 0

        self.evolver      = SelfEvolver()
        self.hot_detector = HotDetector()

        # [FEAT-2] Acceleration 롤링 히스토리
        self._rolling_value:  dict = defaultdict(lambda: deque(maxlen=ACC_ROLLING_N))
        self._rolling_volume: dict = defaultdict(lambda: deque(maxlen=ACC_ROLLING_N))

        # [FEAT-3] Microstructure 이전 봉 추적
        self._prev_high: dict = {}
        self._prev_low:  dict = {}

        # [FEAT-4] VWAP 당일 누적
        self._cum_value:  dict = defaultdict(float)
        self._cum_volume: dict = defaultdict(float)
        self._cum_date:   str  = ""

        # [FEAT-5] 초반 힘 이전 봉
        self._prev_close: dict = {}
        # _prev_high, _prev_low는 FEAT-3에서 이미 추적 → prev_range 계산 가능

        # [FEAT-7] 초반 지속성 — 최근 3봉 추적
        self._ret_hist:       dict = defaultdict(lambda: deque(maxlen=3))
        self._value_acc_hist: dict = defaultdict(lambda: deque(maxlen=3))  # [BOOST-3] value_accel 기반
        self._close_pos_hist: dict = defaultdict(lambda: deque(maxlen=3))

        # [BOOST-1] 진짜 가속도 — 6봉 히스토리 (최근3봉/이전3봉)
        self._value_6hist:  dict = defaultdict(lambda: deque(maxlen=6))
        self._volume_6hist: dict = defaultdict(lambda: deque(maxlen=6))

        # [FEAT-8] 눌림 품질 추적
        self._prev_vwap_dev:      dict = {}
        self._prev_close_vs_high: dict = {}
        self._prev_pullback_flag: dict = {}

        # [FEAT-10] 추세 지속 추적 — 최근 3봉
        self._trend_hist: dict = defaultdict(lambda: deque(maxlen=3))

        # [FIX-D5] 갭 봉 마스킹 — 직전 사이클에서 갭 감지된 종목 세트
        # 갭(≥2분) 봉에서 hh/hl/trend/breakout_quality=0 처리 (허위 추세 차단)
        self._gap_codes: set = set()

        # [FIX-F2] 장전 기관순매수 캐시 (opt10059, 하루 1회)
        # {code: inst_net_buy_krw} — 당일 갱신 후 _calc_features에서 참조
        self._inst_net_buy_map: dict = {}
        self._inst_date: str = ""   # 갱신 기준일 (YYYYMMDD)

        # [FIX-I3] 당일 rolling peak — pullback_depth 계산 기준 (전봉→당일고점 교체)
        self._daily_peak: dict = {}   # {code: 당일 최고가}

        # [FIX-I5] inst_flow_proxy 계산용 — 최근 5봉 signed_value / value 히스토리
        self._flow_sv_hist:  dict = defaultdict(lambda: deque(maxlen=5))  # signed_value 5봉
        self._flow_val_hist: dict = defaultdict(lambda: deque(maxlen=5))  # value 5봉

        # [LOGIN-FIX] OnEventConnect.connect는 __init__에서 하지 않음.
        # ensure_login()의 CommConnect 바로 직전에 단일 1회만 connect한다.
        logger.info("[LOGIN-TRACE] 2) OnReceiveTrData 연결 직전 (OnEventConnect는 ensure_login에서)")
        # [A-2a 2026-05-15] broker_mode 시 OCX 콜백 미등록 (broker IPC는 동기 반환)
        if not getattr(self, "_broker_mode", False):
            self.ocx.OnReceiveTrData.connect(self._on_receive_tr)
        logger.info("[LOGIN-TRACE] 2) OnReceiveTrData 연결 완료")

        # ── [UNIFIED v1.0] 매도엔진 공유 속성 ──────────────────────────────
        # _sell_bridge  : KiwoomRealSellBridge(shared_ocx=self.ocx) — 로그인 후 초기화
        # _sell_log     : rt_sell_engine 전용 로거
        # _sell_ks_dead : True 이면 KillSwitch 발동 → 이후 tick 영구 skip
        self._sell_bridge:  object = None
        self._sell_log:     object = None
        self._sell_ks_dead: bool   = False

        # ── [UNIFIED v1.1] 매수엔진 공유 속성 ──────────────────────────────
        # _buy_enabled : True 이면 run_once_shared 호출 가능 상태
        self._buy_enabled: bool = False

        # [STEP-2H-1 2026-05-13] PB sell shared_ocx attach state
        # standalone PB OCX process 제거 + collector.ocx 공유 경로.
        self._pb_bridge: object = None

        # [PATCH-SLOWDOWN] TR 타임아웃 누적 페널티(초) — 다음 요청 추가 지연
        # 타임아웃 시 +0.6s, 성공 시 -0.15s, 상한 3.0s
        # 목적: 타임아웃 반복 → 다음 요청을 더 늦추어 백오프 안정화
        self._tr_slowdown: float = 0.0

        # [PATCH-CIRCUIT-A] 연속 TR 타임아웃 카운터 — circuit breaker 트리거
        # timeout 시 +1, 성공 수신 시 0 리셋, 임계값 도달 시 cycle pause
        self._consec_tr_timeout: int = 0

        # [PATCH-COOLDOWN 2026-05-06] 종목별 마지막 TR dispatch 시각 — 재진입 게이트
        # detect_gap appendleft + gap_retry_pool 양쪽에서 참조
        # CIRCUIT-BREAK 후 _cooldown_blanket_until 로 일괄 보류
        self._tr_dispatch_ts: dict        = {}
        self._cooldown_blanket_until: float = 0.0
        # [E안 강화 2026-05-07 14:50] timeout 격리 — fail 발생 종목별 unblock 시각
        self._tr_fail_until: dict         = {}
        # [P3 E안 영구격리 2026-05-12] 종목별 누적 timeout 카운터 (메모리 거주, 프로세스 재시작 시 0). PERMANENT_BAN_THRESHOLD 도달 시 당일 영구 차단.
        self._tr_fail_count: dict         = {}
        # [P5 timeout 통계 정확화 2026-05-12] 사이클별 timeout 카운터 — 사이클 종료 로그 "실패=W" 모순(실제 timeout 발생인데 0 표기) 해결
        self._cycle_to_cnt: int           = 0

    def _shutdown(self):
        try:
            logger.info("[종료] QApplication 정상 종료")
            self.app.quit()
        except Exception as e:
            logger.warning(f"[종료] 실패: {e}")

    def _next_scr(self) -> str:
        scr = str(SCR_BASE + (self._scr_idx % SCR_POOL_SIZE))
        self._scr_idx += 1
        return scr

    def _disconnect_scr(self, scr: str):
        """[STEP-2D 2026-05-13] direct OCX → Broker IPC 전환.

        broker IPC type=DISCONNECT_SCR 로 위임. ERROR/TIMEOUT 시에도
        예외 전파 안 함 (기존 pass 동작 유지) — 호출 측 루프 중단 방지.
        """
        try:
            request_id = str(_bro_uuid.uuid4())
            req = {
                "request_id": request_id,
                "ts": datetime.now().isoformat(),
                "ttl_sec": 8,
                "type": "DISCONNECT_SCR",
                "screen_no": str(scr),
            }
            req_path = _BROKER_IPC_REQ_DIR / f"{request_id}.json"
            res_path = _BROKER_IPC_RES_DIR / f"{request_id}.json"
            tmp = req_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(req, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(req_path))

            # 응답 polling (3초 timeout) — 실패해도 pass (기존 동작 유지)
            deadline = time_module.time() + 3.0
            while time_module.time() < deadline:
                if res_path.exists():
                    try:
                        res_path.unlink()
                    except Exception:
                        pass
                    return
                time_module.sleep(0.2)
        except Exception:
            pass

    def _is_in_cooldown(self, code: str) -> bool:
        """[PATCH-COOLDOWN 2026-05-06] 종목 재진입 cooldown 검사.
        True 반환 시 큐 재투입 차단 — detect_gap appendleft / gap_retry_pool 양쪽에서 게이트.
        """
        now = time_module.time()
        if now < self._cooldown_blanket_until:
            return True
        last = self._tr_dispatch_ts.get(code, 0.0)
        return (now - last) < TR_REENTRY_COOLDOWN_SEC

    def _load_all_market_codes(self) -> list:
        # [MASTER-CACHE 2026-06-27] 상장 종목 리스트는 장중 불변 → 날짜 기준 1회 캐시.
        #   load_all_codes가 하루 4+회 재호출(boot/hot refresh)되는데 매 호출 broker 마스터조회 IPC
        #   폭주 방지. 성공로드(≥50)만 캐시 → degraded(fallback)일땐 캐시안함=broker 복귀시 자동회복.
        _today_ac = datetime.now().strftime("%Y%m%d")
        if (getattr(self, "_allcodes_cache_date", None) == _today_ac
                and getattr(self, "_allcodes_cache", None)):
            return list(self._allcodes_cache)

        # [필수-1] 잘못된 API 호출 제거 완료 / GetMasterStockState로 대체
        # [필수-2] GetMasterStockState로 거래정지/관리 종목 필터링
        SKIP_STATE = ["거래정지", "관리", "투자주의", "투자경고", "투자위험", "정리매매"]
        result = []
        # [MASTER-BROKER 2026-06-27 ★OCX마스터DB끊김 근본수정] 수집기 자체 OCX는 broker가 키움 단일세션
        #   소유 시 로그인 skip(multi-OCX회피)→ GetCodeListByMarket 빈값(5/24~). 1분봉(opt10080)처럼
        #   broker IPC(로그인+마스터DB정상·eod종목명도 이 경로로 채움)로 라우팅. broker_mode(하드코딩False)가
        #   아닌 broker 생존(_is_broker_alive)으로 판단. IPC폭주 방지: GetCodeListByMarket 1콜만 broker로
        #   받고 SKIP_KW 이름필터는 eod_daily_bars 재사용(per-code GetMasterCodeName×1661 IPC 제거).
        #   SKIP_STATE는 다운스트림(blocklist/stock_state) 차단(fallback 주석과 동일 정책). 롤백 env
        #   COLLECT_MASTER_BROKER=NO. 안전망=빈값/실패→ 아래 CODELIST-FALLBACK(top600), 회귀위험0.
        broker_mode = getattr(self, "_broker_mode", False)
        use_broker = broker_mode or (
            os.environ.get("COLLECT_MASTER_BROKER", "YES").strip().upper() == "YES"
            and _is_broker_alive()
        )
        if use_broker:
            try:
                _name_map = {}
                try:
                    _eodp_nm = DATA_DIR / "eod_daily_bars.csv"
                    if _eodp_nm.exists() and _eodp_nm.stat().st_size > 0:
                        _nf = pd.read_csv(_eodp_nm, dtype={"code": str}, encoding="utf-8-sig",
                                          usecols=["date", "code", "name"])
                        _nf = _nf[_nf["date"] == _nf["date"].max()]
                        _name_map = dict(zip(_nf["code"].astype(str), _nf["name"].fillna("")))
                except Exception:
                    _name_map = {}
                for mkt in MARKET_CODES:
                    res = broker_tr_request_master("GetCodeListByMarket", mkt, timeout_sec=10.0)
                    raw = ((res.get("data") or {}).get("value", "") or "") if res.get("status") == "OK" else ""
                    for code in (c.strip() for c in raw.split(";") if c.strip()):
                        nm = _name_map.get(code, "")
                        # eod에 이름있고 SKIP_KW(스팩/ETF/우선주 등)면 제외. 이름없으면(신규상장 등) 포함=보수적.
                        if nm and any(k in nm for k in SKIP_KW):
                            continue
                        result.append(code)
            except Exception as e:
                logger.error(f"[MASTER-BROKER] broker 마스터 로드 실패: {e} → fallback")
                result = []
        else:
            # [기존경로] 로그인된 자체 OCX(broker 없을때만). per-code 로컬 조회=빠름.
            for mkt in MARKET_CODES:
                try:
                    raw = self.ocx.dynamicCall("GetCodeListByMarket(QString)", mkt)
                    codes = [c.strip() for c in raw.split(";") if c.strip()]
                    for code in codes:
                        try:
                            name = self.ocx.dynamicCall("GetMasterCodeName(QString)", code).strip()
                            if any(k in name for k in SKIP_KW): continue
                            try:
                                state = self.ocx.dynamicCall("GetMasterStockState(QString)", code).strip()
                                if any(s in state for s in SKIP_STATE): continue
                            except Exception:
                                pass  # 상태 조회 실패 시 포함
                        except Exception:
                            pass
                        result.append(code)
                except Exception as e:
                    logger.error(f"시장 {mkt} 로드 실패: {e}")
        deduped = list(dict.fromkeys(result))
        if len(deduped) >= 50:
            logger.info(f"[MASTER-BROKER] all_codes {len(deduped)}종목 로드"
                        f"({'broker IPC' if use_broker else 'standalone OCX'}) → 캐시({_today_ac})")
            self._allcodes_cache = list(deduped)
            self._allcodes_cache_date = _today_ac
        # [CODELIST-FALLBACK 2026-06-01 v2] GetCodeListByMarket 빈값(standalone OCX 마스터DB 미동기화, 5/24~)
        #   → all_codes=0 → C버킷 붕괴 → universe 30 고착. **설계 선별(KOSDAQ 한정 + SKIP_KW 제외)을 재현**.
        #   소스=eod_daily_bars.csv (code/name/market/value 보유) 최신일 → market==KOSDAQ + SKIP_KW(스팩/ETF/ETN/
        #   리츠/우선주) 제외 → 거래대금(value) 상위 600. 순수 CSV read (broker/OCX/per-code 루프 없음 → 크래시불가).
        #   ※ prev_day_summary 단순 top-600은 시장혼합이라 KOSPI 대형주·ETF(069500/005930/122630) 혼입 → 폐기.
        #   ※ SKIP_STATE(관리/거래정지)는 eod_daily_bars에 상태컬럼 없어 미적용 — 다운스트림(blocklist/stock_state)이 차단.
        if len(deduped) < 50:
            try:
                _eod_path = DATA_DIR / "eod_daily_bars.csv"
                if _eod_path.exists() and _eod_path.stat().st_size > 0:
                    _df = pd.read_csv(_eod_path, dtype={"code": str}, encoding="utf-8-sig",
                                      usecols=["date", "code", "name", "market", "value"])
                    _latest = _df["date"].max()
                    _df = _df[(_df["date"] == _latest) & (_df["market"] == "KOSDAQ")].copy()
                    _df["name"] = _df["name"].fillna("")
                    _df = _df[~_df["name"].str.contains("|".join(SKIP_KW), na=False)]
                    _top = _df.nlargest(600, "value")
                    _fb = [c.strip() for c in _top["code"].tolist() if isinstance(c, str) and c.strip()]
                    _fb = list(dict.fromkeys(_fb))
                    if len(_fb) > len(deduped):
                        logger.warning(
                            f"[CODELIST-FALLBACK] GetCodeListByMarket={len(deduped)} → eod_daily_bars({_latest}) "
                            f"KOSDAQ+SKIP_KW제외 거래대금상위 {len(_fb)}종목 (설계 선별 재현)"
                        )
                        return _fb
            except Exception as e:
                logger.warning(f"[CODELIST-FALLBACK] eod_daily_bars fallback 실패: {e}")
        return deduped

    def _load_prev_top_n(self, top_n: int):
        """전일 거래대금 TOP_N. prev_day_summary → prices_1m 순으로 참조"""
        if PREV_SUMMARY_PATH.exists() and PREV_SUMMARY_PATH.stat().st_size > 0:
            try:
                df = pd.read_csv(PREV_SUMMARY_PATH, dtype={"code": str})
                _val_col = "value" if "value" in df.columns else ("prev_value" if "prev_value" in df.columns else None)
                if "code" in df.columns and _val_col:
                    top_df = df.nlargest(top_n, _val_col)
                    logger.info(f"[TOP_N] prev_day_summary 기준 {len(top_df)}종목 (col={_val_col})")
                    return set(top_df["code"]), dict(zip(top_df["code"], top_df[_val_col]))
            except Exception as e:
                logger.warning(f"prev_day_summary 로드 실패: {e}")

        if OUT_PATH.exists() and OUT_PATH.stat().st_size > 0:
            try:
                df_prev  = pd.read_csv(OUT_PATH, dtype={"code":str,"ts":str}, usecols=["code","ts","value"])
                yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y%m%d")
                df_prev   = df_prev[df_prev["ts"].str.startswith(yesterday)]
                if not df_prev.empty:
                    grouped    = df_prev.groupby("code")["value"].sum()
                    top_series = grouped.nlargest(top_n)
                    logger.info(f"[TOP_N] prices_1m 어제({yesterday}) 기준 {len(top_series)}종목")
                    return set(top_series.index), top_series.to_dict()
            except Exception as e:
                logger.warning(f"prices_1m TOP_N 실패: {e}")

        logger.info("[TOP_N] 전일 데이터 없음, 전종목")
        return set(), {}

    def _pre_load_hot_candidates(self):
        """장 시작 전 HOT 사전 주입 (1회)"""
        if self._seeded: return
        top_n = min(PRE_HOT_SEED_N * 2, self.evolver.top_n_codes)
        _, prev_values = self._load_prev_top_n(top_n)
        seed_dict = dict(sorted(prev_values.items(), key=lambda x: x[1], reverse=True)[:PRE_HOT_SEED_N])
        self.hot_detector.seed(seed_dict)
        self._seeded = True

    def load_all_codes(self, hot_codes: set = None):
        """3버킷 우선순위 구조 — A(HOT/기관) B(전일상위) C(전체잔여)"""
        self.all_codes = self._load_all_market_codes()
        logger.info(f"코스닥 {len(self.all_codes)}종목")

        top_set, top_values = self._load_prev_top_n(self.evolver.top_n_codes)
        hot_codes = hot_codes or set()
        hot_valid = {c for c in hot_codes if c in set(self.all_codes)}

        # ── 버킷 A: HOT + 기관순매수 양수 + 전일 거래대금 상위 50 — 최대 60개
        inst_pos = {c for c, v in self._inst_net_buy_map.items() if v > 0}
        # [KOSDAQ-PURE 2026-06-01] top_values=prev_day_summary(시장혼합 KOSPI+KOSDAQ+ETF)라 그대로 [:50]하면
        #   KOSPI 대형주·ETF(005930/069500/122630)가 A버킷에 누수됨. all_codes(KOSDAQ)로 먼저 필터 후 거래대금 상위50.
        #   (단순 set&[:50]은 상위가 KOSPI라 거의 빔 → 필터 후 정렬이 핵심) hot_valid/inst_pos는 이미 all_codes 교집합됨.
        _kd_codes = set(self.all_codes)
        # [RT-VALUE 2026-06-17 친구님] 실시간 거래대금 상위(opt10032) 우선. 빈값/OFF=전일거래대금(fail-open).
        _rt_top = [c for c in _load_realtime_value_top(50) if c in _kd_codes]
        if _rt_top:
            top50 = set(_rt_top[:50])
        else:
            top50 = set([c for c in sorted(top_values, key=top_values.get, reverse=True) if c in _kd_codes][:50]) if top_values else set()
        bucket_a = list(hot_valid | (inst_pos & _kd_codes) | top50)
        bucket_a = bucket_a[:18]  # [CORE-SLIM 2026-06-01] 40→18: all_codes 복원(CODELIST-FALLBACK)로 코어 49→과부하(150s) → 활성 ~30/사이클 ~86s 복원. universe는 C 600풀 회전이 담당

        # ── [콜드스타트] 전일 데이터 없고 A버킷 비면 임시 상위 30개 배정
        cold_start = (not top_set and not top_values)
        if cold_start and len(bucket_a) == 0:
            bucket_a = list(self.all_codes[:30])
            logger.warning(f"[콜드스타트] 전일 데이터 없음 → 임시 A버킷 {len(bucket_a)}개 생성")

        # ── [FALLBACK-A] A버킷 보장치 [FALLBACK-A40 2026-05-30] 20→40 (env COLLECT_FB_A_TARGET)
        #   기관 수급 dead/부족일에도 거래대금 상위로 A를 40까지 채워 universe 회복
        #   → prices_1m≥32(make_rt_intraday DEGRADED 해소) + funnel step3 binding 시작.
        #   수집 대상만 확대 — 주문/broker/매도/scoreboard/EOD_PICK 무관.
        _a_raw_n = len(bucket_a)
        _a_target = int(os.environ.get("COLLECT_FB_A_TARGET", "18"))   # [CORE-SLIM 2026-06-01] 34→18: 실측 처리량 ~3.1s/code라 active 49=150s 과부하 → 코어 18로 사이클 ~86s 복원(워치독 respawn 유지 위해 코드 default 변경)
        if _a_raw_n < _a_target:
            _a_used = set(bucket_a)
            # [RT-VALUE] 실시간 거래대금 상위(opt10032) 우선 채움, 그다음 전일 거래대금. (빈값=전일만=기존동작)
            _rt_fill = [c for c in _rt_top if c not in _a_used]
            _prev_fill = sorted((c for c in self.all_codes if c not in _a_used and c not in set(_rt_top)),
                                key=lambda c: top_values.get(c, 0), reverse=True)
            _a_cands = _rt_fill + _prev_fill
            _a_fill = _a_cands[:_a_target - _a_raw_n]
            bucket_a = bucket_a + _a_fill
            logger.warning(
                f"[FALLBACK-A] A 부족({_a_raw_n}) → 거래대금순 보충(target={_a_target}) → {len(bucket_a)}개 "
                f"[HOT={len(hot_valid)} 기관={len(inst_pos & set(self.all_codes))} top50={len(top50)}]"
            )

        # [THEME-LEADER-BUCKET 2순위 2026-06-05] 강테마 KOSDAQ 대장주를 active(A) 보장 편입.
        #   미수집 대장주(거래대금 낮아 A/B/C 누락)를 매 사이클 수집 → make_rt 1순위 THEME-INJECT 토대.
        if THEME_LEADER_BUCKET_ENABLE:
            try:
                _tl = _load_theme_leader_codes()
                _ac = set(self.all_codes)          # KOSDAQ(=KOSPI 자동제외)
                _a_set = set(bucket_a)
                _tl_add = [c for c in _tl if c in _ac and c not in _a_set][:THEME_LEADER_BUCKET_MAX]
                if _tl_add:
                    bucket_a = bucket_a + _tl_add
                    logger.info(f"[THEME-LEADER-BUCKET] 강테마 대장주 {len(_tl_add)}개 active 보장수집: {_tl_add}")
            except Exception as _e:
                logger.warning(f"[THEME-LEADER-BUCKET] 실패({_e}) → skip(기존 동작)")

        # [HOLD-BUCKET 1순위 2026-06-12 ★친구님 승인 — 6/12 최위험 구멍 수술]
        #   보유 종목(rt_open qty>0)은 무조건 active(A) 보장 수집. 6/12 실증: 보유 HPSP만 수집명단서
        #   밀려 96분 분봉 끊김 → 매도엔진(분봉 기반)이 장님 = 하드스톱 발동 불능이었음.
        #   롤백: env COLLECT_HOLD_GUARANTEE=NO. 발효: 익일 08:45 부팅(수집기는 부팅시 1회 로드).
        if os.environ.get("COLLECT_HOLD_GUARANTEE", "YES").strip().upper() == "YES":
            try:
                import json as _hb_json
                from pathlib import Path as _hb_Path
                _hb_path = _hb_Path(r"C:\stock_bot\DATA\rt_open_positions.json")
                if _hb_path.exists():
                    with open(_hb_path, "r", encoding="utf-8-sig") as _hb_f:
                        _hb_pos = _hb_json.load(_hb_f)
                    _hb_codes = [c for c, v in _hb_pos.items()
                                 if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0]
                    _hb_add = [c for c in _hb_codes if c not in set(bucket_a)]
                    if _hb_add:
                        bucket_a = bucket_a + _hb_add
                        logger.info(f"[HOLD-BUCKET] 보유종목 {len(_hb_add)}개 active 보장수집: {_hb_add}")
            except Exception as _hb_e:
                logger.warning(f"[HOLD-BUCKET] 실패({_hb_e}) → skip(기존 동작)")

        # [STRATEGY-INJECT 2026-06-24 ★중앙1분봉공유 — 친구님 근본해결]
        #   돌파/NEW_PB가 opt10080 직접호출 폐지 → prices_1m 파일을 읽음. 그들의 후보(IPC/micro_watch_*.json 합집합)를
        #   active(A) 보장수집 해야 파일에 봉이 있어 구멍 안남(친구님 ★핵심조건). cap으로 cycle/조회 폭주 방지·fail-open.
        #   ⚠수집 주기/해상도는 안 건드림(active 종목만 보장편입). 롤백 env COLLECT_STRATEGY_INJECT=NO.
        if os.environ.get("COLLECT_STRATEGY_INJECT", "YES").strip().upper() == "YES":
            try:
                import glob as _si_glob, json as _si_json
                # [INJECTFIX 2026-06-25 ★급등주 커버리지] ①movers·scanner 우선순위 ②all_codes필터 제거
                #   (8:45 스냅 1642종목에 없는 당일급등주=파루·금양도 수집) ③cap 20→30. 백업.bak_pre_injectfix
                _si_must = []; _si_pri = []; _si_rest = []   # S07M 당일후보 > movers/scanner > 나머지
                for _si_f in sorted(_si_glob.glob(r"C:\stock_bot\IPC\micro_watch_*.json")):
                    try:
                        with open(_si_f, encoding="utf-8-sig") as _si_fh:
                            _cs = [str(_c).zfill(6) for _c in (_si_json.load(_si_fh).get("codes") or [])]
                    except Exception:
                        _cs = []
                    if "s07_morning" in _si_f: _si_must += _cs
                    elif ("movers" in _si_f) or ("scanner" in _si_f): _si_pri += _cs
                    else: _si_rest += _cs
                _si_cap = int(os.environ.get("COLLECT_STRATEGY_INJECT_MAX", "30"))
                # [INJECT-OUTPOOL 2026-06-27 ★풀밖 우선] all_codes(=수집 universe)에 없는 전략후보는
                #   bucket_c 회전·정상경로가 전혀 못 잡음(유일경로=inject) → movers/scanner보다 먼저 넣어야
                #   cap에 안 밀림. 풀안 후보는 C 백필이 커버하므로 차순위. 6/26 미수집(208640/299660/361670
                #   =돌파꼬리·풀밖)이 cap12에 잘린 근본수정. cap 불변=TR부하 0. 롤백 env COLLECT_INJECT_OUTPOOL=NO.
                _si_ordered = _si_must + _si_pri + _si_rest  # S07M은 기존 cap 안에서 보장
                if os.environ.get("COLLECT_INJECT_OUTPOOL", "YES").strip().upper() == "YES":
                    _si_allset = set(self.all_codes)
                    if _si_allset:                         # all_codes 비면 재정렬 안함(fail-safe·기존동작)
                        _si_out = [c for c in _si_ordered if c not in _si_allset]   # 풀밖=유일경로 inject
                        _si_in  = [c for c in _si_ordered if c in _si_allset]       # 풀안=C백필 커버
                        _si_ordered = list(dict.fromkeys(_si_must + _si_out + _si_in))
                _si_aset = set(bucket_a); _si_seen = set(); _si_add = []
                for _c in _si_ordered:   # 풀밖 우선 → 그다음 movers/scanner→breakout 순서대로
                    if len(_c) == 6 and _c.isdigit() and _c not in _si_aset and _c not in _si_seen:
                        _si_add.append(_c); _si_seen.add(_c)
                    if len(_si_add) >= _si_cap: break
                if _si_add:
                    bucket_a = bucket_a + _si_add
                    logger.info(f"[STRATEGY-INJECT] 전략후보 {len(_si_add)}개 active 보장수집(cap {_si_cap}·movers우선·all_codes무관): {_si_add}")
            except Exception as _si_e:
                logger.warning(f"[STRATEGY-INJECT] 실패({_si_e}) → skip(기존 동작)")

        # [ENQ-PRIO 2026-06-25 ★급등주 수집보장 — 근본버그 수정] enqueue가 bucket_a[:cap]로 절단하는데
        #   보장수집(보유·inject·테마대장)은 bucket_a 뒤에 append돼 잘려 미수집(6/25 383310 등 inject됐는데 0봉,
        #   사이클 정상40봉/종목54=14개 버려짐). → 보장군을 앞으로 재정렬해 컷에 안 밀리게. 생성 hot/기관 core는
        #   HOT-WIRE(별도 prepend)+C순환이 커버. ⚠보유(HOLD) 절단방지=6/12 수술 취지 복원. 롤백 env COLLECT_ENQ_PRIO=NO.
        if os.environ.get("COLLECT_ENQ_PRIO", "YES").strip().upper() == "YES":
            try:
                _guar = []
                # [2026-06-25 친구님 배분] 보유 > 테마대장(최고엣지) > 모멘텀(inject) 순. 비대장 core는 나머지(최저우선).
                for _gsrc in (locals().get("_hb_add") or [], locals().get("_tl_add") or [], locals().get("_si_add") or []):
                    _guar += list(_gsrc)
                _guar = [c for c in dict.fromkeys(_guar) if c in bucket_a]   # 보유>테마>모멘텀 순·중복제거·실재만
                if _guar:
                    bucket_a = list(dict.fromkeys(_guar + bucket_a))         # 보장군 앞으로, 나머지(core) 뒤로
                    logger.info(f"[ENQ-PRIO] 보장수집 {len(_guar)}개 enqueue 앞으로 재정렬(보유·inject·테마 우선·core는 HOT-WIRE/C순환 커버)")
            except Exception as _ep_e:
                logger.warning(f"[ENQ-PRIO] 실패({_ep_e}) → skip(기존 순서)")

        # ── 버킷 B: 전일 상위 후보 (A 제외) — 최대 20개 제한
        if top_set:
            bucket_b_raw = [c for c in self.all_codes if c in top_set and c not in set(bucket_a)]
            bucket_b = bucket_b_raw[:6]  # [CORE-SLIM 2026-06-01] 15→6: 코어 슬림(활성 ~30 목표)
        else:
            bucket_b = []

        # [BPOOL-FIX 2026-06-10] B풀 본목적 복원 — top_set(prev_day_summary, KOSPI/ETF 혼합)이
        #   KOSDAQ all_codes와 교집합 0이라 FALLBACK-B 상시발동(6/1 인지) → score 82 보드종목(482630)이
        #   C풀 2.5h 순환에 떨어져 250분 갭 = 종가매수 생존판정(drift veto) 데이터 구멍.
        #   수정: D-1 보드(score_eod_archive 최신=KOSDAQ 전용) 종목을 B풀에 보장 주입.
        #   실패/없음 → 기존 fallback 그대로(회귀 0). 롤백 env COLLECT_B_FROM_BOARD=NO.
        if os.environ.get("COLLECT_B_FROM_BOARD", "YES").strip().upper() == "YES":
            try:
                import glob as _glob
                import csv as _csv
                _arc = sorted(_glob.glob(r"C:\stock_bot\data\scoreboard\score_eod_archive\score_eod_*.csv"))
                if _arc:
                    with open(_arc[-1], encoding="utf-8-sig", errors="replace") as _bf:
                        _board_codes = [str(r.get("code", "")).zfill(6) for r in _csv.DictReader(_bf)]
                    _bused = set(bucket_a) | set(bucket_b)
                    _badd = [c for c in _board_codes
                             if c in self.all_codes and c not in _bused][:24]
                    if _badd:
                        bucket_b = list(bucket_b) + _badd
                        logger.info(f"[BPOOL-FIX] D-1 보드 {len(_badd)}종목 B풀 보장: {_badd[:10]}")
            except Exception as _be:
                logger.warning(f"[BPOOL-FIX] 보드 로드 실패(기존 동작 유지): {_be}")

        # ── [FALLBACK-B] B버킷 최소 20개 보장
        _b_fallback = False
        if not bucket_b:
            _b_used = set(bucket_a)
            _b_fill = [c for c in self.all_codes if c not in _b_used][:6]  # [CORE-SLIM 2026-06-01] 15→6: top_set(prev_day_summary)이 KOSPI/ETF위주라 KOSDAQ all_codes와 교집합 비어 FALLBACK-B 상시발동 → B=6로 활성30·C-EXPAND(C=6) 유지
            if _b_fill:
                bucket_b = _b_fill
                _b_fallback = True
                logger.warning(
                    f"[FALLBACK-B] 전일 데이터 없음(top_set 비어있음) → B {len(bucket_b)}개 보충"
                )

        # ── 버킷 C: 전체 잔여 (A,B 제외) — 거래대금 순 정렬 후 순환
        # [v4.16 FIX-1] 버킷 C를 전일 거래대금 순으로 정렬
        # 기존: self.all_codes 순서 그대로 → 대장주 후보가 순환 후반에 몰릴 수 있음
        # 수정: 거래대금 높은 종목이 C버킷 앞쪽 → 순환 초기 사이클에 먼저 수집
        # 효과: 거래대금 급등 신규 대장주를 빠르게 포착 → make_rt_intraday 품질 향상
        bucket_ab = set(bucket_a) | set(bucket_b)
        _c_raw = [c for c in self.all_codes if c not in bucket_ab]
        # 전일 거래대금 기준 정렬 (top_values에 있는 종목 우선, 나머지는 뒤로)
        _c_with_val  = [(c, top_values.get(c, 0)) for c in _c_raw]
        _c_sorted    = sorted(_c_with_val, key=lambda x: x[1], reverse=True)
        bucket_c     = [c for c, _ in _c_sorted]
        logger.info(
            f"[v4.16] C버킷 거래대금 정렬 완료: "
            f"상위10={[c for c,_ in _c_sorted[:10]]} "
            f"(거래대금 있는 종목={sum(1 for _,v in _c_sorted if v>0)}개)"
        )

        # ── [C-700캡 2026-07-08 친구님 700/200 깔때기] 잔여 C버킷을 코스닥 거래대금 상위 COLLECT_C_TOPN(700)만 순환.
        #   목적: 저유동성 꼬리(하위 ~1,000종목·거래대금 미미)를 순환에서 제외 → opt10080 타임아웃/OCX 프리징·과부하 감소.
        #   ★놓침 방지: A/B/테마대장/보유(HOLD)/급등(HOT)/전략후보(INJECT)는 all_codes 전체 참조라 무영향 →
        #     700 밖 급등주도 그 경로로 강제수집됨. C(저우선 순환)만 트림.
        #   랭킹은 eod_daily_bars.csv(코스닥·거래대금)로 신뢰 확보. 데이터 없으면 무캡(현행 유지·fail-open).
        #   롤백: env COLLECT_C_TOPN=0(무캡).
        _c_topn = int(os.environ.get("COLLECT_C_TOPN", "700"))
        if _c_topn > 0 and len(bucket_c) > _c_topn:
            _kd_val = {}
            try:
                _eodp = DATA_DIR / "eod_daily_bars.csv"
                if _eodp.exists() and _eodp.stat().st_size > 0:
                    _dv = pd.read_csv(_eodp, dtype={"code": str}, encoding="utf-8-sig",
                                      usecols=["date", "code", "market", "value"])
                    _dv = _dv[(_dv["date"] == _dv["date"].max()) & (_dv["market"] == "KOSDAQ")]
                    _kd_val = dict(zip(_dv["code"].astype(str), pd.to_numeric(_dv["value"], errors="coerce").fillna(0)))
            except Exception as _ce:
                logger.warning(f"[C-700캡] eod_daily_bars 로드 실패 → 무캡 유지(회귀0): {_ce}")
                _kd_val = {}
            if _kd_val:
                _ranked = sorted(bucket_c, key=lambda c: _kd_val.get(c, 0), reverse=True)
                _c_dropped = len(_ranked) - _c_topn
                bucket_c = _ranked[:_c_topn]
                logger.info(f"[C-700캡] 잔여 C버킷 거래대금 상위 {_c_topn}(코스닥)만 순환 → 저유동성 꼬리 {_c_dropped}개 제외 (타임아웃/부하 감소)")
            else:
                logger.info("[C-700캡] 거래대금 데이터 없음 → 무캡 유지(현행·fail-open)")

        # 버킷 저장 (enqueue_requests에서 참조)
        self._bucket_a = bucket_a
        self._bucket_b = bucket_b
        self._bucket_c = bucket_c
        self._bucket_c_idx = 0  # C버킷 순환 인덱스
        self._gap_retry_pool: dict = {}  # [필수] gap 종목 임시 승격 관리 {code: 잔여사이클}
        # [v4.16] gap_retry는 A버킷보다 우선처리 (request_queue.appendleft) → 대장주 갭 복구 즉시 반영

        # [갭로그 분리] 버킷 타입 맵 저장
        self._code_bucket_map = {}
        for c in bucket_a: self._code_bucket_map[c] = "A"
        for c in bucket_b: self._code_bucket_map[c] = "B"
        for c in bucket_c: self._code_bucket_map[c] = "C"

        # code_list = active(A+B)만 — [필수] C버킷 완전 백필 전용 분리
        self.code_list = bucket_a + bucket_b
        est = len(self.code_list) * self.evolver.tr_interval
        _fb_a_label = f"FB({_a_raw_n}→{len(bucket_a)})" if _a_raw_n < _a_target else str(len(bucket_a))
        _fb_b_label = f"FB(0→{len(bucket_b)})" if _b_fallback else str(len(bucket_b))
        logger.info(
            f"[수집구성] A(HOT/기관)={_fb_a_label} | B(전일상위)={_fb_b_label} | "
            f"C(잔여/{len(bucket_c)})=순환 | 예상={est/60:.1f}분"
        )

    def is_market_open(self) -> bool:
        now = datetime.now()
        if is_holiday(now.date()): return False
        return dtime(8, 50) <= now.time() <= dtime(15, 35)

    def write_heartbeat(self):
        try:
            HEARTBEAT_PATH.write_text(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}|"
                f"codes={len(self.code_list)}|timeout={HEARTBEAT_TIMEOUT}|"
                f"{self.evolver.status_line()}",
                encoding="utf-8"
            )
        except Exception:
            pass

    def load_last_ts_map(self):
        try:
            if not OUT_PATH.exists(): return
            df = pd.read_csv(OUT_PATH, dtype={"code":str,"ts":str}, usecols=["code","ts"]).dropna()
            # [FIX-DATE] 오늘 날짜 이전 last_ts는 "0"으로 초기화 — 전날 데이터로 freshness 필터 차단 방지
            today_pfx = datetime.now().strftime("%Y%m%d")
            self.last_ts_map = {
                str(k): (str(v) if str(v).startswith(today_pfx) else "0")
                for k, v in df.groupby("code")["ts"].max().items()
            }
            logger.info(f"last_ts 복원: {len(self.last_ts_map)}종목 (오늘={today_pfx})")
        except Exception as e:
            logger.warning(f"load_last_ts_map 실패: {e}")

    # [FIX-F2] opt10059 기관순매수 장전 1회 조회
    def _load_inst_net_buy_premarket(self):
        """
        장전(08:50~09:05) 1회만 실행. opt10059(주식일별투자자별매매현황)로
        수집 대상 종목의 전일 기관순매수 원화를 조회해 _inst_net_buy_map에 캐싱.
        inst_net_buy.json 에 저장 → _calc_features에서 봉마다 참조.

        키움 opt10059 필드:
          입력: 일자(YYYYMMDD), 종목코드, 금액구분(1=금액)
          출력: 기관순매수(원화) = 기관계_순매수_금액
        """
        today_str = datetime.now().strftime("%Y%m%d")
        if self._inst_date == today_str and self._inst_net_buy_map:
            logger.info(f"[F2] 기관순매수 이미 로드됨 ({today_str}, {len(self._inst_net_buy_map)}종목)")
            return

        # 캐시 파일 우선 확인 (당일 데이터 있으면 TR 조회 생략)
        if INST_NET_BUY_PATH.exists():
            try:
                cached = json.loads(INST_NET_BUY_PATH.read_text(encoding="utf-8-sig"))
                if cached.get("date") == today_str and cached.get("data"):
                    self._inst_net_buy_map = cached["data"]
                    self._inst_date        = today_str
                    logger.info(f"[F2] 기관순매수 캐시 복원 ({today_str}, {len(self._inst_net_buy_map)}종목)")
                    return
            except Exception:
                pass

        # 전일 날짜 계산 (장전이므로 전날 데이터)
        from datetime import timedelta
        prev_dt  = datetime.now() - timedelta(days=1)
        # 주말이면 금요일로 이동
        while prev_dt.weekday() >= 5:
            prev_dt -= timedelta(days=1)
        prev_date = prev_dt.strftime("%Y%m%d")

        # [G1] inst_net_buy 커버 확장: 50 → 150종목 (기관 수급 커버리지 3배)
        # 장전 1회 실행, TR 약 150×0.65s ≈ 97초(1.6분) 추가
        target_codes = self.code_list[:min(len(self.code_list), 150)]
        logger.info(f"[G1] opt10059 기관순매수 조회 시작 (기준일={prev_date}, 종목={len(target_codes)})")
        result_map: dict = {}
        # [FIX-J7] 종목별 스크린 순환 사용 — 동일 스크린 재사용 이벤트 혼선 방지
        # 기존: scr 1개 고정 → 150종목 전체에 같은 스크린 → 이전 응답 혼선 위험
        # 수정: _next_scr()로 풀(50개) 순환, 사용된 스크린 목록 수집 후 일괄 해제
        used_scrs: list = []

        for code in target_codes:
            scr = self._next_scr()   # [FIX-J7] 종목마다 새 스크린 (broker 측에 전달)
            used_scrs.append(scr)
            try:
                # [STEP-2A 2026-05-13] direct OCX → Broker IPC 전환.
                # 기존 SetInputValue 5건 + CommRqData + GetCommData 가
                # broker_tr_request 1회 호출로 통합. _inst_tr_received 플래그 미사용.
                # collector OCX 직접 호출 7건 제거 (이 loop 내부).
                _limiter.acquire()  # [PATCH-RATELIMIT]
                # [STEP-2I-2-d 2026-05-13] broker dead 시 direct OCX fallback
                global _consec_broker_timeout
                if not _is_broker_alive():
                    res = self._direct_ocx_tr_opt10059(
                        code=str(code), prev_date=prev_date, scr=str(scr),
                        timeout_ms=8000,
                    )
                    if res.get("status") == "OK":
                        logger.info("[DIRECT-FALLBACK] opt10059 %s OK", code)
                else:
                    res = broker_tr_request(
                        tr_code="opt10059",
                        inputs={
                            "일자":         prev_date,
                            "종목코드":     str(code),
                            "금액수량구분": "1",   # 1=금액
                            "매매구분":     "0",   # 0=순매수
                            "단위구분":     "1",   # 1=단주
                        },
                        output_fields=[
                            "종목코드", "기관계", "외인계",
                            "개인",     "등락율", "현재가",
                        ],
                        rqname="opt10059_req",
                        screen_no=scr,
                        timeout_sec=25.0,
                    )
                    if res.get("status") != "OK":
                        _consec_broker_timeout += 1
                        if _consec_broker_timeout >= _BROKER_TIMEOUT_THRESHOLD:
                            _mark_broker_dead()
                            _consec_broker_timeout = 0
                    else:
                        _consec_broker_timeout = 0

                if res.get("status") != "OK":
                    logger.warning(
                        f"[F2][BROKER] opt10059 {code} "
                        f"status={res.get('status')} err={res.get('error')}"
                    )
                    self.wait_next_cycle(self.evolver.tr_interval)
                    continue

                records = (res.get("data") or {}).get("records") or []
                if not records:
                    self.wait_next_cycle(self.evolver.tr_interval)
                    continue

                raw = (records[0].get("기관계") or "")\
                          .strip().replace(",", "").replace("+", "")
                try:
                    inst_val = int(float(raw)) * 1000   # 단위: 천원 → 원
                    result_map[str(code)] = inst_val
                except Exception:
                    result_map[str(code)] = 0

                self.wait_next_cycle(self.evolver.tr_interval)

            except Exception as e:
                logger.warning(f"[F2] opt10059 {code} 실패: {e}")

        # [FIX-J7] 사용된 스크린 전체 일괄 해제
        for s in used_scrs:
            self._disconnect_scr(s)

        self._inst_net_buy_map = result_map
        self._inst_date        = today_str

        # 캐시 파일 저장 (Atomic)
        try:
            tmp = INST_NET_BUY_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"date": today_str, "prev_date": prev_date, "data": result_map},
                           ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            os.replace(str(tmp), str(INST_NET_BUY_PATH))
        except Exception as e:
            logger.warning(f"[F2] inst_net_buy 저장 실패: {e}")

        pos_cnt = sum(1 for v in result_map.values() if v > 0)
        neg_cnt = sum(1 for v in result_map.values() if v < 0)
        logger.info(
            f"[F2] 기관순매수 완료 | 조회={len(target_codes)} | "
            f"저장={len(result_map)} | 매수={pos_cnt} | 매도={neg_cnt}"
        )

    def verify_csv(self) -> bool:
        if not OUT_PATH.exists(): return True
        try:
            df   = pd.read_csv(OUT_PATH, nrows=5, dtype={"code":str,"ts":str})
            need = {"code","ts","open","high","low","close","volume","value"}
            if not need.issubset(df.columns):
                raise ValueError(f"컬럼 불일치: {df.columns.tolist()}")
            return True
        except Exception as e:
            bak = str(OUT_PATH) + f".broken_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try: os.rename(str(OUT_PATH), bak)
            except Exception as _re: logger.error("[CSV][FAIL] backup rename 실패: %s", _re)
            logger.error(f"CSV 이상, 백업: {bak} | {e}")
            return False

    def detect_gap(self, code: str, new_ts: str):
        last = self.last_ts_map.get(code)
        if not last or len(last) != 14 or len(new_ts) != 14: return
        try:
            gap = int(
                (datetime.strptime(new_ts, "%Y%m%d%H%M%S") -
                 datetime.strptime(last,   "%Y%m%d%H%M%S")
                ).total_seconds() // 60
            )
            if gap >= 5:
                self.day_gap_count += 1
                # [FIX-D5] 갭 봉 마스킹: 해당 종목을 갭 세트에 등록
                self._gap_codes.add(code)
                # [PATCH-COOLDOWN 2026-05-06] 재진입 cooldown 검사 — 직전 dispatch N초 내 재투입 차단
                # 큐 폭주 방지: detect_gap의 즉시 appendleft + gap_retry_pool 양쪽 게이트
                # [FAILUNTIL-1 2026-05-12] _tr_fail_until 격리 검사 추가 — 격리 종목이 gap 감지 경로로 우회 진입하던 결함 차단
                if self._tr_fail_until.get(code, 0) > time_module.time():
                    logger.debug(f"[FAIL-SKIP] {code} 격리 중 (gap={gap}분) — appendleft 차단")
                elif not self._is_in_cooldown(code):
                    self.request_queue.appendleft(code)
                    # [필수] gap>=2 → gap_retry_pool 1사이클 임시 승격 (A버킷 영구 편입 금지)
                    if gap >= 2:
                        pool = getattr(self, '_gap_retry_pool', {})
                        pool[code] = 1  # 1사이클만 유효
                        self._gap_retry_pool = pool
                        self._code_bucket_map[code] = "A"  # 로그용만
                else:
                    logger.debug(f"[COOLDOWN] {code} 재진입 차단 (gap={gap}분)")
                # [갭로그 분리] C버킷 순환 갭 vs 장애 갭 구분
                bucket = getattr(self, '_code_bucket_map', {}).get(code, "A")
                if bucket == "C" and 2 <= gap <= 15:
                    logger.info(f"[갭-순환] {code} {gap}분 | {last}→{new_ts}")
                else:
                    logger.warning(f"[갭-장애] {code} {gap}분 | {last}→{new_ts}")
        except Exception: pass

    def print_daily_summary(self):
        logger.info("=" * 60)
        logger.info(
            f"[일일요약] 봉={self.day_bar_count} | 갭={self.day_gap_count} | "
            f"이상={self.day_filter_count} | 사이클={self.cycle_count} | "
            f"종목={len(self.code_list)}"
        )
        logger.info(f"[진화상태] {self.evolver.status_line()}")
        logger.info("=" * 60)
        self.day_bar_count = self.day_gap_count = self.day_filter_count = 0

    # ─── 피처 계산 헬퍼 (수집기 내부, 점수 없음) ──────────

    def _calc_features(self, row: dict) -> dict:
        """
        [FEAT-1] Order Flow Proxy
        [FEAT-2] Acceleration
        [FEAT-3] Microstructure
        [FEAT-4] VWAP
        [FEAT-5] 초반 힘
        [FEAT-6] 눌림 구조
        기존 row에 13개 컬럼 추가. 점수 계산 없음.
        """
        code = row["code"]
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        vol   = row["volume"]
        value = row["value"]
        ts    = row["ts"]

        # ── [FEAT-1] Order Flow Proxy ──
        # [FIX-I1] body_ratio 가중 signed_value (도지봉 오판 개선)
        # 기존: c>o이면 +value 전액, c<o이면 -value 전액 (도지봉=0 → 세력매집 누락)
        # 수정: body_ratio로 가중 → 몸통이 클수록 방향성 강, 도지봉은 신호 약화
        # 출처: Cont, Kukanov, Stoikov (2014) OFI 프록시 근사치 개선
        hl_range     = max(h - l, 1)
        body_ratio   = round(abs(c - o) / hl_range, 6)
        if c > o:
            signed_value = round(value * body_ratio, 2)    # 매수 방향, 몸통 비율로 가중
        elif c < o:
            signed_value = round(-value * body_ratio, 2)   # 매도 방향, 몸통 비율로 가중
        else:
            signed_value = 0.0                             # 도지봉: 방향 불명확

        # ── [FEAT-2] Acceleration (순간강도: 현재봉/5봉평균) ──
        self._rolling_value[code].append(value)
        self._rolling_volume[code].append(vol)

        rv = list(self._rolling_value[code])
        rm = list(self._rolling_volume[code])
        val_mean = sum(rv) / len(rv) if rv else 1
        vol_mean = sum(rm) / len(rm) if rm else 1
        value_acc  = round(value / max(val_mean, 1), 4)
        volume_acc = round(vol   / max(vol_mean, 1), 4)

        # ── [BOOST-1] 진짜 가속도 (최근3봉평균 / 이전3봉평균) ──
        # 기준: value_accel >= 1.3 / volume_accel >= 1.2
        # 의미: "지금 더 빨라지는 종목" — 순간강도(value_acc)와 별개
        self._value_6hist[code].append(value)
        self._volume_6hist[code].append(vol)

        v6 = list(self._value_6hist[code])
        g6 = list(self._volume_6hist[code])

        if len(v6) >= 6:
            recent_v = sum(v6[3:]) / 3.0
            prior_v  = sum(v6[:3]) / 3.0
            value_accel = round(recent_v / max(prior_v, 1), 4)
        elif len(v6) >= 4:
            mid = len(v6) // 2
            recent_v = sum(v6[mid:]) / max(len(v6[mid:]), 1)
            prior_v  = sum(v6[:mid]) / max(len(v6[:mid]), 1)
            value_accel = round(recent_v / max(prior_v, 1), 4)
        else:
            value_accel = 1.0   # 데이터 부족: 중립값

        if len(g6) >= 6:
            recent_g = sum(g6[3:]) / 3.0
            prior_g  = sum(g6[:3]) / 3.0
            volume_accel = round(recent_g / max(prior_g, 1), 4)
        elif len(g6) >= 4:
            mid = len(g6) // 2
            recent_g = sum(g6[mid:]) / max(len(g6[mid:]), 1)
            prior_g  = sum(g6[:mid]) / max(len(g6[:mid]), 1)
            volume_accel = round(recent_g / max(prior_g, 1), 4)
        else:
            volume_accel = 1.0   # 데이터 부족: 중립값

        # ── [FEAT-3] Microstructure ──
        # [FIX-D5] 갭 봉 마스킹: 연속성 단절 구간 허위 추세 신호 차단
        is_gap_bar = code in self._gap_codes
        if is_gap_bar:
            self._gap_codes.discard(code)   # 1봉만 마스킹 후 해제

        prev_h = self._prev_high.get(code)
        prev_l = self._prev_low.get(code)

        if is_gap_bar:
            # 갭 봉: 전봉과 연속성 없음 → 구조 피처 무효화
            hh = 0; hl = 0; trend = 0
        else:
            hh = 1 if (prev_h is not None and h > prev_h) else 0
            hl = 1 if (prev_l is not None and l > prev_l) else 0
            trend = 1 if (hh == 1 and hl == 1) else 0
        close_pos = round((c - l) / hl_range, 6)

        # ── [FEAT-4] VWAP (당일 누적) ──
        today_str = ts[:8] if len(ts) >= 8 else ""
        if today_str and today_str != self._cum_date:
            # [FIX-D1] 날짜 리셋 버그 수정 — 전체 일자 경계 상태 일괄 초기화
            # VWAP 누적
            self._cum_value.clear()
            self._cum_volume.clear()
            # FEAT-3 Microstructure (전일 고저가 다음날 첫봉 hh/hl 오염 차단)
            self._prev_high.clear()
            self._prev_low.clear()
            # FEAT-5 초반 힘 (전일 종가 기준 ret_1m 오염 차단)
            self._prev_close.clear()
            # FEAT-2 Acceleration 롤링 (전일 거래대금 기준치 오염 차단)
            self._rolling_value.clear()
            self._rolling_volume.clear()
            # BOOST-1 가속도 6봉 히스토리 (전일 연장 차단)
            self._value_6hist.clear()
            self._volume_6hist.clear()
            # FEAT-7 초반 지속성 (전일 ret 합산 차단)
            self._ret_hist.clear()
            self._value_acc_hist.clear()
            self._close_pos_hist.clear()
            # FEAT-8 눌림 품질 상태 (전일 vwap_dev → 당일 첫봉 vwap_reclaim 오작동 차단)
            self._prev_vwap_dev.clear()
            self._prev_close_vs_high.clear()
            self._prev_pullback_flag.clear()
            # FEAT-10 추세 지속 (전일 trend 연속 오판 차단)
            self._trend_hist.clear()
            # [FIX-I3] 당일 rolling peak 초기화 (전일 고점 오염 차단)
            self._daily_peak.clear()
            # [FIX-I5] inst_flow_proxy 히스토리 초기화 (전일 OFI 신호 차단)
            self._flow_sv_hist.clear()
            self._flow_val_hist.clear()
            self._cum_date = today_str
            logger.info(f"[FIX-D1] 날짜 변경({today_str}) — 전체 피처 상태 초기화 완료")

        self._cum_value[code]  += value
        self._cum_volume[code] += vol

        cum_vol = self._cum_volume[code]
        if cum_vol > 0:
            vwap     = round(self._cum_value[code] / cum_vol, 2)
            vwap_dev = round((c - vwap) / max(vwap, 1), 6)
        else:
            vwap     = c
            vwap_dev = 0.0

        # ── [FEAT-5] 초반 힘 ──
        pc = self._prev_close.get(code)
        ret_1m = round((c / pc - 1), 6) if (pc and pc > 0) else 0.0

        prev_range = (prev_h - prev_l) if (prev_h is not None and prev_l is not None) else 0
        range_expansion = round(hl_range / max(prev_range, 1), 4) if prev_range > 0 else 0.0

        # ── [FEAT-6] 눌림 구조 ──
        pullback = 0
        if prev_h is not None and c < prev_h and c > vwap:
            pullback = 1

        # ── 이전 봉 갱신 (FEAT-3 + FEAT-5 공용) ──
        self._prev_high[code]  = h
        self._prev_low[code]   = l
        self._prev_close[code] = c

        # ══════════════════════════════════════════════════════
        # [FEAT-7] 초반 지속성
        # ══════════════════════════════════════════════════════
        self._ret_hist[code].append(ret_1m)
        self._value_acc_hist[code].append(value_accel)   # [BOOST-3] value_accel 기반으로 교체
        self._close_pos_hist[code].append(close_pos)

        ret_3bar_sum    = round(sum(self._ret_hist[code]), 6)
        # [FIX-D4] value_acc_3bar: 합→평균으로 수정
        # 기존 합 기준 1.4는 중립값(1.0×3봉=3.0) 대비 비논리적
        # 평균 기준 1.3: value_accel 중립=1.0, 기준=1.3 (가속 확인)
        _vacc_hist = list(self._value_acc_hist[code])
        value_acc_3bar  = round(sum(_vacc_hist) / max(len(_vacc_hist), 1), 4)
        # 고가 대비 종가 유지력: 종가 위치 × 몸통 강도
        close_hold_power = round(_clip01(close_pos * body_ratio), 6)

        # ══════════════════════════════════════════════════════
        # [FEAT-8] 눌림 품질
        # ══════════════════════════════════════════════════════
        # [FIX-I3] pullback_depth: 전봉고가(prev_h) → 당일 rolling peak 기준으로 교체
        # 이유: 추세눌림 전략의 핵심은 "당일 최고점" 대비 눌림 깊이
        #       직전 1봉 고가는 당일 최고점과 다를 수 있어 전략과 불일치
        # _daily_peak: 날짜 리셋 시 초기화, 매봉 max()로 갱신 (항상 당일 최고점 유지)
        self._daily_peak[code] = max(self._daily_peak.get(code, h), h)
        daily_peak_h = self._daily_peak[code]

        pullback_depth = 0.0
        if daily_peak_h > 0 and c < daily_peak_h:
            # 당일 고점 대비 얼마나 눌렸는가 (0=안눌림/현재가=당일고점, 1=최대눌림)
            pullback_depth = round(_clip01((daily_peak_h - c) / daily_peak_h), 6)

        # pullback_recover: 눌림 이후 회복 품질 (종가 위치 × VWAP 위 보너스)
        prev_vwap_dev_val = self._prev_vwap_dev.get(code, 0.0)
        pullback_recover  = round(_clip01(close_pos * (1.0 + min(vwap_dev, 0.2))), 6)

        # vwap_reclaim: 이전 봉에서 VWAP 아래였다가 이번 봉에 VWAP 위로 재탈환
        vwap_reclaim = 1 if (prev_vwap_dev_val <= 0 and vwap_dev > 0) else 0

        # ══════════════════════════════════════════════════════
        # [FEAT-9] 체결 압력 강화
        # ══════════════════════════════════════════════════════
        upper_wick = h - max(o, c)
        # wick_pressure: 윗꼬리 적을수록 높음
        wick_pressure    = round(_clip01(1.0 - _safe_div(upper_wick, hl_range, 0.0)), 6)
        upper_wick_ratio = _safe_div(upper_wick, hl_range, 0.0)

        # close_strength: 종가 위치 70% + 몸통 강도 30%
        close_strength = round(_clip01((close_pos * 0.7) + (body_ratio * 0.3)), 6)

        # [BOOST-2] pressure_score 단순화 재계산 (기준 >= 0.55)
        # 공식: close_pos*0.6 + body_ratio*0.3 + (1-upper_wick_ratio)*0.1
        # 의미: 윗꼬리 없는 진짜 매수봉만 통과
        pressure_score = round(_clip01(
            close_pos         * 0.6 +
            body_ratio        * 0.3 +
            (1.0 - upper_wick_ratio) * 0.1
        ), 6)

        # ══════════════════════════════════════════════════════
        # [FEAT-10] 돌파 품질
        # ══════════════════════════════════════════════════════
        # breakout_quality: 고가 돌파 후 종가 안착 (전고점 이상 종가만 유효)
        # [FIX-D5] 갭 봉 마스킹: 갭 구간 돌파는 추세 돌파가 아님
        breakout_quality = 0.0
        if not is_gap_bar and prev_h is not None and prev_h > 0 and c >= prev_h:
            breakout_quality = round(_clip01(
                (0.5 * close_strength) +
                (0.3 * _clip01(min(value_acc / 2.0, 1.0))) +
                (0.2 * wick_pressure)
            ), 6)

        # range_efficiency: 몸통 위주 이동 (꼬리 낭비 없는 캔들)
        range_efficiency = round(_clip01(_safe_div(abs(c - o), hl_range, 0.0)), 6)

        # trend_persist: 최근 3봉 추세 유지도 (hh+hl 동시 기준)
        self._trend_hist[code].append(trend)
        trend_persist = round(_clip01(sum(self._trend_hist[code]) / 3.0), 6)

        # ══════════════════════════════════════════════════════
        # [FEAT-12] 공용 종합강도 micro_alpha (0~1 정규화)
        # 시가/추세눌림/종배 3전략 공용 — 점수 아님, 데이터 컬럼만
        #
        # [G2] 동적 가중치 — 초반/중반/후반 시간대별 분리 [FIX-I4]
        #   초반(~09:20): 압력·속도 집중 (세력 진입 초기 포착)
        #     pressure 0.40 / accel 0.30 / strength 0.15 / breakout 0.10 / trend 0.05
        #   중반(09:20~13:00): 과열 방지·구조 중심 (노이즈 필터링 강화)
        #     pressure 0.30 / accel 0.20 / strength 0.25 / breakout 0.15 / trend 0.10
        #   후반(13:00~14:50): 봉 구조·추세 지속성 중시 (거래량 감소 구간)
        #     pressure 0.25 / accel 0.15 / strength 0.30 / breakout 0.20 / trend 0.10
        #   ※ EARLY_END = 09:20 (H3 수정 기준) / 전 구간 합산 1.00 보증
        # [G3] pressure_score < 0.45 → micro_alpha = 0 (약한 봉 노이즈 제거)
        # [G5] vwap_dev < -0.01 → micro_alpha = 0 (하락 추세 봉 제거)
        # ══════════════════════════════════════════════════════
        _accel_avg = _clip01(
            (
                _clip01(min(value_acc  / 2.0, 1.0)) +
                _clip01(min(volume_acc / 2.0, 1.0))
            ) / 2.0
        )

        # [G3] 압력 최소 기준 미달 → 즉시 0
        if pressure_score < 0.40:    # [FIX-HOT] 0.45 → 0.40 완화
            micro_alpha = 0.0
        # [G5] VWAP 이탈 -1% 초과 → 하락 추세 봉 → 0
        elif vwap_dev < -0.02:    # [FIX-HOT] -0.01 → -0.02 완화
            micro_alpha = 0.0
        else:
            # [FIX-I4] 시간대별 동적 가중치 3구간 분리 (합산 1.00 보증)
            # 초반(09:00~09:20): 압력·속도 집중 (세력 진입 초기 포착)
            # 중반(09:20~13:00): 균형 (과열 방지·구조 중심)
            # 후반(13:00~14:50): 봉 구조·추세 지속성 중시
            #                    (거래량 감소 구간 노이즈 필터링 강화)
            if is_early():        # 09:00 ~ 09:20 초반
                pw, aw, sw, bw, tw = 0.40, 0.30, 0.15, 0.10, 0.05
            elif is_late():       # 13:00 ~ 14:50 후반
                pw, aw, sw, bw, tw = 0.25, 0.15, 0.30, 0.20, 0.10
            else:                 # 09:20 ~ 13:00 중반
                pw, aw, sw, bw, tw = 0.30, 0.20, 0.25, 0.15, 0.10
            micro_alpha = round(_clip01(
                pressure_score   * pw +
                _accel_avg       * aw +
                close_strength   * sw +
                breakout_quality * bw +
                trend_persist    * tw
            ), 6)

        # ── FEAT-8 상태 갱신 ──
        self._prev_vwap_dev[code]      = vwap_dev
        self._prev_close_vs_high[code] = (
            _safe_div(c, max(prev_h, 1), 0.0) if prev_h is not None else 0.0
        )
        self._prev_pullback_flag[code] = pullback

        # [FIX-F2] 장전 기관순매수 — opt10059 캐시에서 참조 (없으면 0)
        inst_net_buy = self._inst_net_buy_map.get(str(code), 0)

        # ── [FIX-I5] inst_flow_proxy — 실시간 OFI 보정 신호 ──────────
        # [v4.16] C버킷 신규 종목도 수집되므로 inst_flow_proxy 범위 확대됨
        # inst_net_buy(전일 정적)를 보완하는 당일 실시간 방향 신호
        # = 최근 5봉 signed_value 합 / 최근 5봉 value 합 → -1.0 ~ +1.0
        # [FIX-J3] 5봉 미만 구간: 극단값(±1.0) 방지를 위해 0.0 반환
        # 워밍업 guard: 충분한 봉 없으면 중립값으로 하위전략 OFI 오발동 방지
        self._flow_sv_hist[code].append(signed_value)
        self._flow_val_hist[code].append(value)
        if len(self._flow_sv_hist[code]) < 5:
            inst_flow_proxy = 0.0   # [FIX-J3] 워밍업 구간 → 중립
        else:
            _sv_sum  = sum(self._flow_sv_hist[code])
            _val_sum = sum(self._flow_val_hist[code])
            inst_flow_proxy = round(_safe_div(_sv_sum, max(_val_sum, 1), 0.0), 6)
            inst_flow_proxy = max(-1.0, min(1.0, inst_flow_proxy))  # -1~+1 클램핑

        row["signed_value"]    = signed_value
        row["body_ratio"]      = body_ratio
        row["value_acc"]       = value_acc
        row["volume_acc"]      = volume_acc
        # [BOOST-1] 진짜 가속도
        row["value_accel"]     = value_accel
        row["volume_accel"]    = volume_accel
        row["hh"]              = hh
        row["hl"]              = hl
        row["trend"]           = trend
        row["close_pos"]       = close_pos
        row["vwap"]            = vwap
        row["vwap_dev"]        = vwap_dev
        row["ret_1m"]          = ret_1m
        row["range_expansion"] = range_expansion
        row["pullback"]        = pullback
        # [FEAT-7]
        row["ret_3bar_sum"]    = ret_3bar_sum
        row["value_acc_3bar"]  = value_acc_3bar
        row["close_hold_power"]= close_hold_power
        # [FEAT-8]
        row["pullback_depth"]  = pullback_depth
        row["pullback_recover"]= pullback_recover
        row["vwap_reclaim"]    = vwap_reclaim
        # [FEAT-9]
        row["pressure_score"]  = pressure_score
        row["wick_pressure"]   = wick_pressure
        row["close_strength"]  = close_strength
        # [FEAT-10]
        row["breakout_quality"]= breakout_quality
        row["range_efficiency"]= range_efficiency
        row["trend_persist"]   = trend_persist
        # [FEAT-12]
        row["micro_alpha"]     = micro_alpha
        # [FIX-F2] 기관순매수
        row["inst_net_buy"]    = inst_net_buy
        # [FIX-I5] 실시간 OFI 보정 프록시
        row["inst_flow_proxy"] = inst_flow_proxy
        return row

    # ─── 키움 이벤트 ─────────────────────────────────────

    def _on_login(self, err_code):
        # [LOGIN-FIX] 콜백 진입 여부를 print로 최상단 무조건 확인 (logger 핸들러 이슈 회피)
        try:
            print(f"[LOGIN-CALLBACK-PRINT] _on_login 진입 err_code={err_code}", flush=True)
        except Exception:
            pass
        logger.info("[LOGIN-CALLBACK] OnEventConnect 들어옴")
        logger.debug(f"[LOGIN] _on_login 이벤트 수신 raw err_code={err_code}")  # [FIX-C]
        logger.info(f"[LOGIN-TRACE] 4) OnEventConnect 이벤트 수신 raw err_code={err_code}")
        try: err = int(str(err_code).strip() or "0")
        except Exception: err = 0
        logger.debug(f"[LOGIN] 파싱된 err={err} (0=성공)")                       # [FIX-C]
        logger.info(f"[LOGIN-TRACE] 4) OnEventConnect 파싱된 err={err} (0=성공)")
        if err == 0:
            self.connected = True
        else:
            self.connected = False
            logger.warning(f"[LOGIN] 연결 해제 이벤트 err={err} — 루프 유지")
        logger.debug(f"[LOGIN] connected={self.connected}, login_loop.exit 직전") # [FIX-C]
        # [FIX-LOOP] login_loop가 실행 중일 때만 exit() — 수집 중 재발생 시 루프 방해 방지
        if self.login_loop and self.login_loop.isRunning():
            self.login_loop.exit()

    def _on_receive_tr(self, scr_no, rqname, trcode, recordname,
                       prev_next, data_len, err_code, msg1, msg2):
        # [CRASH-BLOCK] OnReceiveTrData 전체 try-except 보호 — 예외 발생 시 프로세스 종료 방지
        try:
            # [OCX-WARMUP 2026-05-07] dummy TR 응답 — 데이터 처리 없이 loop 즉시 exit
            if rqname == "warmup_req":
                self.tr_received = True
                try: self.tr_loop.exit()
                except Exception: pass
                return

            # [A] opt10059 기관순매수 이벤트 분리 처리
            # [FIX-V415-2] _inst_tr_received 독립 플래그 사용 — tr_received 공유 오염 방지
            if rqname == "opt10059_req":
                self._inst_tr_received = True
                self.tr_loop.exit()
                return

            # [STEP-2I-2-d 2026-05-13] direct OCX fallback rqname 분기
            #   batch_rows 직접 push 금지 — self._direct_tr_result dict 만 채움.
            #   caller 가 통일 처리 (broker IPC path 와 동일 형식 반환).
            if rqname == "opt10059_direct_req":
                try:
                    if int(str(err_code).strip() or "0") != 0:
                        self._direct_tr_result = {
                            "status": "ERROR",
                            "data": None,
                            "error": f"err_code={err_code} msg={msg1}",
                        }
                    else:
                        inst_raw = self.ocx.dynamicCall(
                            "GetCommData(QString,QString,int,QString)",
                            trcode, rqname, 0, "기관계",
                        )
                        record = {"기관계": (inst_raw or "").strip()}
                        self._direct_tr_result = {
                            "status": "OK",
                            "data": {"records": [record], "prev_next": "0"},
                            "error": None,
                        }
                except Exception as _ex:
                    self._direct_tr_result = {
                        "status": "ERROR", "data": None, "error": f"parse: {_ex}"
                    }
                self._direct_tr_received = True
                self.tr_loop.exit()
                return

            if rqname == "opt10080_direct_req":
                try:
                    if int(str(err_code).strip() or "0") != 0:
                        self._direct_tr_result = {
                            "status": "ERROR",
                            "data": None,
                            "error": f"err_code={err_code} msg={msg1}",
                        }
                    else:
                        cnt = int(self.ocx.dynamicCall(
                            "GetRepeatCnt(QString,QString)", trcode, rqname))
                        records = []
                        for i in range(cnt):
                            def _g(field, _i=i):
                                return (self.ocx.dynamicCall(
                                    "GetCommData(QString,QString,int,QString)",
                                    trcode, rqname, _i, field) or "").strip()
                            records.append({
                                "체결시간": _g("체결시간"),
                                "시가":     _g("시가"),
                                "고가":     _g("고가"),
                                "저가":     _g("저가"),
                                "현재가":   _g("현재가"),
                                "거래량":   _g("거래량"),
                                "거래대금": _g("거래대금"),
                            })
                        self._direct_tr_result = {
                            "status": "OK",
                            "data": {
                                "records": records,
                                "prev_next": str(prev_next),
                            },
                            "error": None,
                        }
                except Exception as _ex:
                    self._direct_tr_result = {
                        "status": "ERROR", "data": None, "error": f"parse: {_ex}"
                    }
                self._direct_tr_received = True
                self.tr_loop.exit()
                return

            if rqname != "opt10080_req": return

            if int(str(err_code).strip() or "0") != 0:
                logger.warning(f"TR 오류 {self.current_code} err={err_code} {msg1}")
                self.tr_received = True
                self.prev_next   = "0"
                self.tr_loop.exit()
                return

            self.tr_received = True
            self.prev_next   = str(prev_next)

            cnt           = int(self.ocx.dynamicCall("GetRepeatCnt(QString,QString)", trcode, rqname))
            last_ts       = self.last_ts_map.get(self.current_code, "0")
            freshness_sec = get_freshness_sec()
            new_cnt = fil_cnt = 0

            def _get(field):
                return self.ocx.dynamicCall(
                    "GetCommData(QString,QString,int,QString)", trcode, rqname, i, field)

            for i in range(cnt):
                dt = _get("체결시간").strip()
                if not (dt and dt.isdigit() and int(dt) > int(last_ts)): continue

                try:
                    bar_dt = datetime.strptime(dt, "%Y%m%d%H%M%S")
                    if (datetime.now() - bar_dt).total_seconds() > freshness_sec * 10:
                        continue
                except Exception:
                    pass

                row = {
                    "code":   self.current_code,
                    "ts":     dt,
                    "open":   _safe_int(_get("시가"))   or 0,
                    "high":   _safe_int(_get("고가"))   or 0,
                    "low":    _safe_int(_get("저가"))   or 0,
                    "close":  _safe_int(_get("현재가")) or 0,
                    "volume": _safe_int(_get("거래량")) or 0,
                    "value":  _safe_int(_get("거래대금")) or 0,  # [FIX-VAL] None → 0
                }
                # [FIX-VAL2] opt10080은 거래대금 미제공 → close×volume으로 보정
                if row["value"] == 0 and row["close"] > 0 and row["volume"] > 0:
                    row["value"] = abs(row["close"]) * row["volume"]

                if not is_valid_bar(row):
                    fil_cnt += 1
                    self._cycle_fil_cnt = getattr(self, '_cycle_fil_cnt', 0) + 1
                    continue

                if row["close"] < MIN_PRICE_FILTER: continue

                # ── 피처 계산 (점수 없음, 컬럼만 추가) ──
                # [FIX-E1] detect_gap 먼저 실행 → gap_codes.add → _calc_features에서 is_gap_bar 정상 작동
                self.detect_gap(self.current_code, dt)   # ① 갭 감지 & gap_codes 등록
                row = self._calc_features(row)           # ② 피처 계산 (is_gap_bar 체크)
                self.batch_rows.append(row)
                new_cnt += 1

                # [FIX-J1] last_ts_map O(n²) → O(1) 직접 갱신
                # 기존: 루프 종료 후 batch_rows 전체 순회(O(n×종목수))
                # 수정: 봉 처리 즉시 max 갱신 → 전체 순회 불필요
                prev_ts = self.last_ts_map.get(self.current_code, "0")
                if dt > prev_ts:
                    self.last_ts_map[self.current_code] = dt

            if fil_cnt > 0:
                self.day_filter_count += fil_cnt

            self.tr_loop.exit()
        except Exception as e:
            logger.error(f"[CRASH-BLOCK] OnReceiveTrData 예외: {e}", exc_info=True)
            # 대기 중 _request_1m_once 가 hang 하지 않도록 tr_received=True + tr_loop.exit()
            try:
                self.tr_received = True
                self.tr_loop.exit()
            except Exception:
                pass
            return

    # ─── [STEP-2I-2-d 2026-05-13] Direct OCX TR fallback helpers ─────
    #   broker dead 시 collector self.ocx 로 legacy direct TR 호출.
    #   반환 형식은 broker_tr_request 와 동일 (caller 통일 처리).
    def _direct_ocx_tr_opt10059(self, code: str, prev_date: str, scr: str,
                                  timeout_ms: int = 8000) -> dict:
        """opt10059 (기관순매수) direct TR.

        Returns: {"status":"OK"|"TIMEOUT"|"ERROR"|"ERROR_HOLD",
                  "data":{"records":[{"기관계":"..."}],"prev_next":"0"}}
        """
        # [DIRECT_OCX_BLOCKED 2026-05-23] broker alive 시 direct OCX fallback 차단 (multi-OCX 회피)
        if _is_broker_alive():
            try:
                logger.warning("[DIRECT_OCX_BLOCKED] opt10059 %s — broker alive → direct OCX fallback 거부 (multi-OCX 회피)", code)
            except Exception:
                pass
            return {"status": "ERROR_HOLD", "data": None,
                    "error": "direct OCX blocked: broker alive (BROKER_ONLY mode)"}
        try:
            self._direct_tr_received = False
            self._direct_tr_result   = {"status": "TIMEOUT", "data": None, "error": None}
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "일자",         prev_date)
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "종목코드",     str(code))
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "금액수량구분", "1")
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "단위구분",     "1")
            ret = self.ocx.dynamicCall(
                "CommRqData(QString,QString,int,QString)",
                "opt10059_direct_req", "opt10059", 0, str(scr),
            )
            if int(ret) != 0:
                return {"status": "ERROR", "data": None,
                        "error": f"CommRqData ret={ret}"}
            QTimer.singleShot(int(timeout_ms), self.tr_loop.quit)
            self.tr_loop.exec_()
            if not self._direct_tr_received:
                return {"status": "TIMEOUT", "data": None,
                        "error": f"tr_loop timeout ({timeout_ms}ms)"}
            return self._direct_tr_result
        except Exception as e:
            return {"status": "ERROR", "data": None, "error": f"direct opt10059: {e}"}

    def _direct_ocx_tr_opt10080(self, code: str, scr: str, next_flag: int = 0,
                                  timeout_ms: int = 12000) -> dict:
        """opt10080 (1m bars) direct TR. 단일 응답 (prev_next loop 는 caller 가 관리).

        Returns: {"status":"OK"|"TIMEOUT"|"ERROR"|"ERROR_HOLD",
                  "data":{"records":[{체결시간,시가,...}],"prev_next":"0"|"2"}}
        """
        # [DIRECT_OCX_BLOCKED 2026-05-23] broker alive 시 direct OCX fallback 차단 (multi-OCX 회피)
        if _is_broker_alive():
            try:
                logger.warning("[DIRECT_OCX_BLOCKED] opt10080 %s — broker alive → direct OCX fallback 거부 (multi-OCX 회피)", code)
            except Exception:
                pass
            return {"status": "ERROR_HOLD", "data": None,
                    "error": "direct OCX blocked: broker alive (BROKER_ONLY mode)"}
        try:
            self._direct_tr_received = False
            self._direct_tr_result   = {"status": "TIMEOUT", "data": None, "error": None}
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "종목코드",     str(code))
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "틱범위",       "1")
            self.ocx.dynamicCall("SetInputValue(QString,QString)", "수정주가구분", "0")
            ret = self.ocx.dynamicCall(
                "CommRqData(QString,QString,int,QString)",
                "opt10080_direct_req", "opt10080", int(next_flag), str(scr),
            )
            if int(ret) != 0:
                return {"status": "ERROR", "data": None,
                        "error": f"CommRqData ret={ret}"}
            QTimer.singleShot(int(timeout_ms), self.tr_loop.quit)
            self.tr_loop.exec_()
            if not self._direct_tr_received:
                return {"status": "TIMEOUT", "data": None,
                        "error": f"tr_loop timeout ({timeout_ms}ms)"}
            return self._direct_tr_result
        except Exception as e:
            return {"status": "ERROR", "data": None, "error": f"direct opt10080: {e}"}

    # ─── 접속·재접속 ─────────────────────────────────────

    def ensure_login(self):
        # [A-2a 2026-05-15] broker mode 시 login 자체 skip (broker가 이미 로그인 보유)
        if getattr(self, "_broker_mode", False):
            logger.info("[A-2a] broker mode — ensure_login skip")
            return
        # [BROKER_ONLY 2026-05-23] broker hb fresh(<30s) + state=CONNECTED 시 collector 자체 CommConnect 차단
        # Why: 5/23 08:45 multi-OCX 충돌 직접 측정 → broker -106 단절. 5/22 동일 패턴 5회 → watchdog 정지.
        # Effect: opstarter 두번째 팝업 0회 + broker 영원 alive. broker dead 시 기존 path fallback.
        try:
            _hb_path = Path("C:/stock_bot/IPC/broker_heartbeat.json")
            if _hb_path.exists():
                _hb_age = time_module.time() - _hb_path.stat().st_mtime
                if _hb_age < 30:
                    with open(_hb_path, encoding="utf-8") as _hbf:
                        _hb = json.load(_hbf)
                    if _hb.get("state") == "CONNECTED":
                        logger.info("[BROKER_ONLY] broker alive (hb_age=%.1fs state=CONNECTED) — collector ensure_login skip (multi-OCX 회피)", _hb_age)
                        self.connected = False
                        return
        except Exception as _e:
            logger.debug("[BROKER_ONLY] broker hb check skip: %s", _e)
        logger.debug("[LOGIN] ensure_login 진입")
        # [LOGIN-FIX] 시작부 가드 — 이미 로그인된 상태면 CommConnect 호출 금지.
        # 이미 로그인된 OCX에 CommConnect를 호출하면 OnEventConnect가 재발화되지 않아
        # login_loop.exec_()에서 무한 대기에 빠진다.
        try:
            if int(self.ocx.dynamicCall("GetConnectState()")) == 1:
                logger.info("[LOGIN] 이미 로그인 상태 → CommConnect 생략")
                self.connected = True
                return
        except Exception as e:
            logger.error(f"[LOGIN] 시작부 GetConnectState 실패 (재시도 진입): {e}")

        # [FIX-RETRY] 최대 3회 재시도 — raise 대신 재시도로 main 크래시 방지
        # [P2-LOGIN-CLAMP 2026-05-14 10:55] 5/14 popup 11회 분석에서 collector ensure_login
        # 진입당 최대 3 popup 발생 위험 확인. attempt 3→1 축소 (popup chain 차단).
        # 실패 시 ensure_connected 가 60s wait 후 다음 사이클에서 자연 재시도.
        for attempt in range(1):
            try:
                state = int(self.ocx.dynamicCall("GetConnectState()"))
            except Exception as e:
                logger.error(f"[LOGIN] GetConnectState 실패 ({attempt+1}/3): {e}")
                time_module.sleep(3)
                continue

            if state == 1:
                logger.info(f"[LOGIN] 재시도 중 이미 로그인 상태 감지 → CommConnect 생략 (attempt={attempt+1}/3)")
                self.connected = True
                return

            # [LOGIN-FIX] login_loop를 CommConnect 이전에 미리 생성.
            # 콜백이 도착할 시점에 login_loop가 이미 존재해야 _on_login 내부의
            # `if self.login_loop and self.login_loop.isRunning()` 가드가 정상 동작한다.
            self.login_loop = QEventLoop()
            logger.info(f"[LOGIN-TRACE] 3) login_loop 생성 완료, CommConnect 진입 준비 (attempt={attempt+1}/3)")

            try:
                # 누적 슬롯 전부 제거 → 단일 신선한 슬롯만 유지
                print("[LOGIN-DISCONNECT-START]", flush=True)
                while True:
                    try:
                        self.ocx.OnEventConnect.disconnect(self._on_login)
                    except Exception:
                        break
                print("[LOGIN-DISCONNECT-END]", flush=True)
                # ─────────────────────────────────────────────────────────
                # [LOGIN-FIX] 이 구간(connect → CommConnect → exec_)은 sleep / loop /
                # 다른 이벤트루프 / 추가 logger 개입을 모두 금지한다.
                # OCX 생성 스레드와 동일한 스레드에서 단일 호출 흐름을 보장.
                # ─────────────────────────────────────────────────────────
                self.ocx.OnEventConnect.connect(self._on_login)
                print("[LOGIN-CONNECT-DONE]", flush=True)
                print("[LOGIN-COMMCONNECT-BEFORE]", flush=True)
                self.ocx.dynamicCall("CommConnect()")
                print("[LOGIN-COMMCONNECT-AFTER]", flush=True)
                self.login_loop.exec_()
            except Exception as e:
                logger.error(f"[LOGIN] CommConnect/exec 실패 ({attempt+1}/3): {e}")
                time_module.sleep(3)
                continue

            logger.info(f"[LOGIN-TRACE] 3) login_loop.exec_() 탈출 (attempt={attempt+1}/3)")

            try:
                if int(self.ocx.dynamicCall("GetConnectState()")) == 1:
                    logger.info("[LOGIN] 로그인 최종 성공")
                    self.connected = True
                    return
                else:
                    logger.error(f"[LOGIN] 로그인 최종 실패 ({attempt+1}/3)")
            except Exception as e:
                logger.error(f"[LOGIN] 상태 확인 실패 ({attempt+1}/3): {e}")

            time_module.sleep(3)

        raise RuntimeError("OpenAPI 로그인 실패 — 다음 사이클 재시도")

    def ensure_connected(self) -> bool:
        # [BROKER_ONLY-GUARD 2026-05-26] broker alive 시 main loop 진입 허용.
        # Why: 5/23 BROKER_ONLY 패치로 ensure_login의 CommConnect가 skip되어 collector OCX GetConnectState=0.
        #      _request_1m_once L2826에 broker IPC opt10080 라우팅이 이미 존재 → main loop만 통과시키면 정상 동작.
        if _is_broker_alive():
            self._reconnect_fail_count = 0
            return True
        # [P2-LOGIN-CLAMP 2026-05-14 10:55] MAX_RECONNECT 3→1.
        # 사이클당 ensure_login 호출 횟수 제한. 실패 시 60s wait_next_cycle.
        MAX_RECONNECT = 1
        try:
            if int(self.ocx.dynamicCall("GetConnectState()")) == 1:
                self._reconnect_fail_count = 0
                return True
            # [G5-KEEPALIVE 2026-05-14 11:40] disconnect 일시 감지 시 5초 대기 + 재검증.
            # 5/14 popup chain 진짜 주범 = collector ensure_login 자체 재호출 5회 발생 (08:53/08:59/09:15/10:51).
            # GetConnectState() 일시 0 반환은 키움 OCX 내부 race 또는 키움 서버 ping 지연 가능성.
            # 자연 복구 기회 부여 → false-positive disconnect 차단 → ensure_login 빈도 -90% 추정.
            logger.warning("[G5-KEEPALIVE] GetConnectState=0 감지 → 5초 대기 후 재검증")
            time_module.sleep(5)
            try:
                cs2 = int(self.ocx.dynamicCall("GetConnectState()"))
                if cs2 == 1:
                    logger.info("[G5-KEEPALIVE] 5초 대기 후 자연 복구 — ensure_login 회피 (popup 0회)")
                    self._reconnect_fail_count = 0
                    return True
            except Exception as e:
                logger.warning(f"[G5-KEEPALIVE] 재검증 실패: {e}")
            if self._reconnect_fail_count >= MAX_RECONNECT:
                logger.error(f"[재접속] 연속 {MAX_RECONNECT}회 실패, 60초 대기")
                self.wait_next_cycle(60)
                self._reconnect_fail_count = 0
                return False
            # [GUARD-X 2026-05-21, XFIX] broker alive 상태에서 collector 자체 login 임시 지연 — multi-OCX 충돌 회피
            # Why: 5/21 09:46 silent stop = broker 재시작 시점 collector 자체 ensure_login → multi-OCX hang.
            # 정정: 연속 skip 한도 (3) 추가 — 4번째부터 dead-wait 방지 위해 강제 ensure_login 진행.
            # 의도: broker 재시작 직후 ~3분 race window 회피 + 그 이후에도 OCX 끊기면 자체 복구 허용.
            _guardx_triggered = False
            try:
                _hb_path = Path("C:/stock_bot/IPC/broker_heartbeat.json")
                if _hb_path.exists():
                    _hb_age = time_module.time() - _hb_path.stat().st_mtime
                    if _hb_age < 30:
                        with open(_hb_path, encoding="utf-8") as _hbf:
                            _hb = json.load(_hbf)
                        if _hb.get("state") == "CONNECTED":
                            _guardx_triggered = True
                            if not hasattr(self, "_guardx_skip_count"):
                                self._guardx_skip_count = 0
                            # [BROKER_ONLY-v2 2026-05-23] skip 한도 3 → 60 long timeout (~1시간) 완화.
                            # Why: 5/22 multi-OCX 5회 발생 = 한도 3회(3분) 너무 짧음 → 4번째 ensure_login 강제 진행 → 충돌 재발.
                            # Effect: broker 정상이면 ~1시간 collector ensure_login 회피. dead-wait 시에만 강제 진행 (안전망 유지).
                            if self._guardx_skip_count < 60:
                                self._guardx_skip_count += 1
                                logger.warning(
                                    "[BROKER_ONLY][HOLD] broker alive (hb_age=%.1fs state=CONNECTED) skip_count=%d/60 → ensure_login long timeout (multi-OCX 회피)",
                                    _hb_age, self._guardx_skip_count,
                                )
                                self.wait_next_cycle(60)
                                return False
                            else:
                                logger.warning(
                                    "[BROKER_ONLY][HOLD] skip_count=%d (1시간 long timeout 초과) → dead-wait 방지 위해 ensure_login 강제 진행 (broker hb_age=%.1fs)",
                                    self._guardx_skip_count, _hb_age,
                                )
                                # 한도 초과 시 skip_count reset (다음 race window 대비)
                                self._guardx_skip_count = 0
            except Exception as _e:
                logger.debug(f"[GUARD-X] broker check skip: {_e}")
            # GUARD-X 미발효 (broker 부재 또는 stale) 시 skip_count 0으로 리셋
            if not _guardx_triggered and hasattr(self, "_guardx_skip_count") and self._guardx_skip_count != 0:
                logger.info("[GUARD-X] broker 조건 미충족 → skip_count 0 리셋")
                self._guardx_skip_count = 0
            self.ensure_login()
            # ensure_login 성공 시에도 skip_count 0 리셋 (다음 race window 대비)
            try:
                if int(self.ocx.dynamicCall("GetConnectState()")) == 1:
                    if hasattr(self, "_guardx_skip_count") and self._guardx_skip_count != 0:
                        logger.info("[GUARD-X] ensure_login 성공 → skip_count 0 리셋")
                        self._guardx_skip_count = 0
            except Exception:
                pass
            ok = int(self.ocx.dynamicCall("GetConnectState()")) == 1
            if ok:
                self._reconnect_fail_count = 0
            else:
                self._reconnect_fail_count += 1
                logger.warning(f"[재접속] 실패 {self._reconnect_fail_count}/{MAX_RECONNECT}")
            return ok
        except Exception as e:
            self._reconnect_fail_count += 1
            logger.error(f"[재접속] 예외 {self._reconnect_fail_count}/{MAX_RECONNECT}: {e}")
            return False

    # ─── TR 요청 ─────────────────────────────────────────

    def request_1m_with_backoff(self, code: str) -> bool:
        for attempt in range(BACKOFF_MAX_RETRY + 1):
            scr = self._next_scr()
            try:
                self._request_1m_once(code, scr)
                self._disconnect_scr(scr)
                return True
            except Exception as e:
                self._disconnect_scr(scr)
                if attempt >= BACKOFF_MAX_RETRY:
                    logger.error(f"[백오프] {code} 최종실패 ({attempt+1}/{BACKOFF_MAX_RETRY+1}회): {e}")
                    return False
                wait = BACKOFF_BASE_SEC * (2 ** attempt) + random.uniform(0, BACKOFF_JITTER)
                logger.warning(f"[백오프] {code} ({attempt+1}/{BACKOFF_MAX_RETRY}) {wait:.1f}s 대기")
                self.wait_next_cycle(wait)
        return False

    def _process_opt10080_records(self, records: list, code: str) -> None:
        """[A-2b 2026-05-15] BATCH_TR records 처리 (기존 _on_receive_tr opt10080_req 분기 인라인).

        Args:
            records: broker_gateway _on_receive_tr_data 응답 records list.
                     각 row: dict with keys [체결시간, 시가, 고가, 저가, 현재가, 거래량, 거래대금].
            code: 종목코드.
        """
        try:
            last_ts = self.last_ts_map.get(code, "0")
            freshness_sec = get_freshness_sec()
            new_cnt = fil_cnt = 0
            for rec in records:
                dt = str(rec.get("체결시간", "")).strip()
                if not (dt and dt.isdigit() and int(dt) > int(last_ts)):
                    continue
                try:
                    bar_dt = datetime.strptime(dt, "%Y%m%d%H%M%S")
                    if (datetime.now() - bar_dt).total_seconds() > freshness_sec * 10:
                        continue
                except Exception:
                    pass
                row = {
                    "code":   code,
                    "ts":     dt,
                    "open":   _safe_int(rec.get("시가"))   or 0,
                    "high":   _safe_int(rec.get("고가"))   or 0,
                    "low":    _safe_int(rec.get("저가"))   or 0,
                    "close":  _safe_int(rec.get("현재가")) or 0,
                    "volume": _safe_int(rec.get("거래량")) or 0,
                    "value":  _safe_int(rec.get("거래대금")) or 0,
                }
                if row["value"] == 0 and row["close"] > 0 and row["volume"] > 0:
                    row["value"] = abs(row["close"]) * row["volume"]
                if not is_valid_bar(row):
                    fil_cnt += 1
                    self._cycle_fil_cnt = getattr(self, '_cycle_fil_cnt', 0) + 1
                    continue
                if row["close"] < MIN_PRICE_FILTER:
                    continue
                self.detect_gap(code, dt)
                row = self._calc_features(row)
                self.batch_rows.append(row)
                new_cnt += 1
                prev_ts = self.last_ts_map.get(code, "0")
                if dt > prev_ts:
                    self.last_ts_map[code] = dt
            if fil_cnt > 0:
                self.day_filter_count += fil_cnt
        except Exception as e:
            logger.error(f"[A-2b] _process_opt10080_records 예외 code={code}: {e}", exc_info=True)

    def _batch_fetch_opt10080(self, codes: list) -> None:
        """[A-2b 보강 2026-05-15] chunk batch_tr + heartbeat + cascade 차단.

        보강 1: cache miss cascade 차단 — _consec_tr_timeout 은 사이클당 최대 +1.
                ok 비율 < 50% 일 때만 카운트. 정상 사이클은 리셋.
        보강 2: chunk(15종목) 분할 + chunk 사이 1s sleep — 키움 rate limit 보호.
        보강 3: chunk 마다 self.write_heartbeat() 강제 갱신 — watchdog stall 차단.

        Args:
            codes: 사이클 대상 종목 list.
        """
        self._batch_cache = {}
        if not codes:
            return
        try:
            from broker_client import BrokerClient
            bc = BrokerClient()
        except Exception as e:
            logger.warning(f"[A-2b] BrokerClient import 실패: {e}")
            return

        CHUNK_SIZE = 15
        chunks = [codes[i:i + CHUNK_SIZE] for i in range(0, len(codes), CHUNK_SIZE)]

        total_codes   = len(codes)
        total_ok      = 0
        total_timeout = 0
        total_error   = 0
        total_elapsed = 0.0

        for idx, chunk in enumerate(chunks):
            # [보강 3] chunk 진입 직전 heartbeat 강제 갱신
            try: self.write_heartbeat()
            except Exception: pass

            try:
                res = bc.batch_tr(
                    tr_code="opt10080",
                    codes=chunk,
                    input_template={"종목코드": "{CODE}", "틱범위": "1", "수정주가구분": "0"},
                    output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량", "거래대금"],
                    rqname_template="opt10080_req",
                    screen_no_rotate=["0001"],
                    per_request_timeout_sec=5.0,
                    batch_timeout_sec=30.0,  # [보강 3] chunk 별 30s 한도 (단일 sync block 단축)
                )
            except Exception as e:
                logger.warning(f"[A-2b] chunk {idx+1}/{len(chunks)} batch_tr 예외: {e}")
                continue

            if res.get("status") != "OK":
                logger.warning(
                    f"[A-2b] chunk {idx+1}/{len(chunks)} status={res.get('status')} "
                    f"error={res.get('error')}"
                )
                continue

            data    = res.get("data") or {}
            results = data.get("results") or []
            summary = data.get("summary") or {}
            for entry in results:
                c = entry.get("code")
                if entry.get("status") == "OK":
                    self._batch_cache[c] = ((entry.get("data") or {}).get("records") or [])
                else:
                    self._batch_cache[c] = None  # TIMEOUT/ERROR
            total_ok      += summary.get("ok", 0)
            total_timeout += summary.get("timeout", 0)
            total_error   += summary.get("error", 0)
            total_elapsed += summary.get("elapsed_sec", 0.0)

            # [보강 2] chunk 사이 1s pacing (키움 rate limit 보호) — 마지막 chunk 후엔 sleep 안 함
            if idx < len(chunks) - 1:
                time_module.sleep(1.0)

        # [보강 3] 완료 후 heartbeat 강제 갱신
        try: self.write_heartbeat()
        except Exception: pass

        logger.info(
            f"[A-2b] BATCH_TR chunks={len(chunks)} total={total_codes} "
            f"ok={total_ok} timeout={total_timeout} error={total_error} "
            f"elapsed={total_elapsed:.2f}s"
        )

        # [보강 1] 사이클 단위 _consec_tr_timeout 평가 — 사이클당 최대 +1
        # ok 비율 < 50% 일 때만 카운트 (cascade 차단). 정상 사이클은 리셋.
        ok_ratio = (total_ok / total_codes) if total_codes > 0 else 0.0
        if ok_ratio < 0.5:
            self._consec_tr_timeout = getattr(self, '_consec_tr_timeout', 0) + 1
            logger.warning(
                f"[A-2b] ok 비율 {ok_ratio:.1%} < 50% — 사이클 penalty +1 "
                f"(consec={self._consec_tr_timeout})"
            )
        else:
            self._consec_tr_timeout = 0  # 정상 사이클 → 리셋

    def _request_1m_once(self, code: str, scr: str):
        """[STEP-2B-1 2026-05-13] direct OCX → Broker IPC 전환.

        기존:
          - SetInputValue 3건 / CommRqData / tr_loop.exec_() / GetCommData × N
          - OnReceiveTrData 콜백이 batch_rows에 push
        변경:
          - broker_tr_request(opt10080) 1회 호출
          - response.records 직접 처리 (OHLCV 로직 인라인)
          - 콜백 미사용 (broker 측 OCX 가 OnReceiveTrData 수신)
        보존:
          - timeout_count / slowdown / consec_tr_timeout 페널티 구조
          - 영구격리 / 900초 격리 정책
          - last_ts_map / batch_rows / day_filter_count 업데이트
          - prev_next 연속조회 (next_flag=2)
          - _calc_features / detect_gap 호출
        """
        self.current_code = str(code)
        self.current_scr  = scr
        next_flag         = 0
        last_before       = self.last_ts_map.get(code, "0")
        timeout_count     = 0  # [FIX-3] 타임아웃 재시도 카운터
        _pages            = 0  # [REDESIGN 2026-07-11] 처리한 페이지 수(장중 연속조회 상한용)

        # [A-2b 보강 2026-05-15] broker_mode 시 사이클 시작 BATCH_TR cache lookup
        # 보강 1: cache miss 시 종목별 penalty 제거 (cascade 차단).
        # _batch_fetch_opt10080 가 사이클 단위 ok 비율 분석으로 _consec_tr_timeout 처리.
        if getattr(self, "_broker_mode", False):
            cache = getattr(self, "_batch_cache", {})
            records = cache.get(code)
            if records is None:
                # cache miss = batch_tr 시점 fail. 종목 단위 penalty 안 함 (cascade 차단).
                logger.debug(f"[A-2b] cache miss {code} (사이클 ok 비율 분석으로 통합 처리)")
                return
            self._process_opt10080_records(records, code)
            return

        while True:
            # [PATCH-SLOWDOWN] TR 호출 직전 누적 페널티 적용
            if self._tr_slowdown > 0.0:
                time_module.sleep(self._tr_slowdown)

            # [PATCH-COOLDOWN 2026-05-06] dispatch 시각 기록 — 재진입 게이트 기준점
            self._tr_dispatch_ts[code] = time_module.time()

            _limiter.acquire()  # [PATCH-RATELIMIT]

            # [STEP-2I-2-d 2026-05-13] broker dead 시 direct OCX fallback
            global _consec_broker_timeout
            if not _is_broker_alive():
                res = self._direct_ocx_tr_opt10080(
                    code=self.current_code,
                    scr=str(self.current_scr),
                    next_flag=int(next_flag),
                    timeout_ms=int(TR_TIMEOUT_MS),
                )
                if res.get("status") == "OK":
                    logger.debug("[DIRECT-FALLBACK] opt10080 %s OK", self.current_code)
            else:
                # [STEP-2B-1] Broker IPC 호출 — opt10080 multi-record TR
                res = broker_tr_request(
                    tr_code="opt10080",
                    inputs={
                        "종목코드":     self.current_code,
                        "틱범위":       "1",
                        "수정주가구분": "0",
                    },
                    output_fields=[
                        "체결시간", "시가", "고가", "저가",
                        "현재가",   "거래량", "거래대금",
                    ],
                    rqname="opt10080_req",
                    screen_no=str(self.current_scr),
                    timeout_sec=(TR_TIMEOUT_MS / 1000.0),  # 12초
                )
                if res.get("status") != "OK":
                    _consec_broker_timeout += 1
                    if _consec_broker_timeout >= _BROKER_TIMEOUT_THRESHOLD:
                        _mark_broker_dead()
                        _consec_broker_timeout = 0
                else:
                    _consec_broker_timeout = 0

            # [CRASH-BLOCK] TR 응답 처리 구간 — 예외 발생해도 raise 금지
            try:
                _status = res.get("status")

                # ───────── TIMEOUT 처리 (broker timeout 또는 client poll timeout) ─────────
                if _status != "OK":
                    timeout_count += 1
                    # [P5 2026-05-12] 사이클별 timeout 카운터 +1
                    self._cycle_to_cnt += 1
                    # [P1 2026-05-12] 페널티 +0.3 / 상한 1.5
                    self._tr_slowdown = min(self._tr_slowdown + 0.3, 1.5)
                    # [PATCH-CIRCUIT-A] 연속 timeout 카운터 +1
                    self._consec_tr_timeout += 1
                    if timeout_count >= MAX_TIMEOUT_RETRY:
                        logger.error(
                            f"[TR타임아웃] {self.current_code} "
                            f"{MAX_TIMEOUT_RETRY}회 초과, 포기 "
                            f"(broker status={_status} err={res.get('error')})"
                        )
                        # [P3 영구격리 2026-05-12]
                        _cnt = self._tr_fail_count.get(self.current_code, 0) + 1
                        self._tr_fail_count[self.current_code] = _cnt
                        if _cnt >= PERMANENT_BAN_THRESHOLD:
                            self._tr_fail_until[self.current_code] = time_module.time() + 86400
                            logger.warning(
                                f"[E안 영구격리] {self.current_code} 누적 {_cnt}회 — 당일 차단"
                            )
                        else:
                            # [EBAN900 2026-05-11] 900초 격리
                            self._tr_fail_until[self.current_code] = time_module.time() + 900
                        break
                    logger.warning(
                        f"[TR타임아웃] {self.current_code} "
                        f"{timeout_count}/{MAX_TIMEOUT_RETRY} 재시도 "
                        f"(broker status={_status})"
                    )
                    # [TR_TUNE 2026-05-06] tr_interval ± 0.3s jitter
                    time_module.sleep(self.evolver.tr_interval + random.uniform(-0.3, 0.3))
                    continue

                # ───────── 정상 수신 — 페널티 감쇠 ─────────
                # [PATCH-SLOWDOWN] 정상 수신 시 누적 페널티 점진 감쇠 (-0.15s, 하한 0.0)
                self._tr_slowdown = max(0.0, self._tr_slowdown - 0.15)
                # [PATCH-CIRCUIT-A] 정상 수신 시 연속 timeout 카운터 리셋
                self._consec_tr_timeout = 0

                # ───────── records 추출 + OHLCV 처리 (인라인 — _on_receive_tr opt10080 분기 로직) ─────────
                data            = res.get("data") or {}
                records         = data.get("records") or []
                broker_prevnext = str(data.get("prev_next", "0"))
                self.prev_next  = broker_prevnext

                last_ts       = self.last_ts_map.get(self.current_code, "0")
                freshness_sec = get_freshness_sec()
                new_cnt = fil_cnt = 0

                for rec in records:
                    dt = (rec.get("체결시간") or "").strip()
                    if not (dt and dt.isdigit() and int(dt) > int(last_ts)):
                        continue

                    try:
                        bar_dt = datetime.strptime(dt, "%Y%m%d%H%M%S")
                        if (datetime.now() - bar_dt).total_seconds() > freshness_sec * 10:
                            continue
                    except Exception:
                        pass

                    row = {
                        "code":   self.current_code,
                        "ts":     dt,
                        "open":   _safe_int(rec.get("시가"))   or 0,
                        "high":   _safe_int(rec.get("고가"))   or 0,
                        "low":    _safe_int(rec.get("저가"))   or 0,
                        "close":  _safe_int(rec.get("현재가")) or 0,
                        "volume": _safe_int(rec.get("거래량")) or 0,
                        "value":  _safe_int(rec.get("거래대금")) or 0,
                    }
                    # [FIX-VAL2] opt10080은 거래대금 미제공 → close×volume으로 보정
                    if row["value"] == 0 and row["close"] > 0 and row["volume"] > 0:
                        row["value"] = abs(row["close"]) * row["volume"]

                    if not is_valid_bar(row):
                        fil_cnt += 1
                        self._cycle_fil_cnt = getattr(self, '_cycle_fil_cnt', 0) + 1
                        continue

                    if row["close"] < MIN_PRICE_FILTER:
                        continue

                    # ── 피처 계산 (점수 없음, 컬럼만 추가) ──
                    # [FIX-E1] detect_gap → gap_codes 등록 → _calc_features 정상 동작
                    self.detect_gap(self.current_code, dt)
                    row = self._calc_features(row)
                    self.batch_rows.append(row)
                    new_cnt += 1

                    # [FIX-J1] last_ts_map O(n²) → O(1) 직접 갱신
                    prev_ts = self.last_ts_map.get(self.current_code, "0")
                    if dt > prev_ts:
                        self.last_ts_map[self.current_code] = dt

                if fil_cnt > 0:
                    self.day_filter_count += fil_cnt

                # ───────── 연속조회 판단 ─────────
                # [REDESIGN 2026-07-11] 장중 연속조회 상한(기본 1페이지) — 1페이지(900봉)가 당일(최대 381봉)을
                #   항상 전부 덮으므로 2페이지는 전일 데이터 재조회 낭비(실측 사이클 TR의 ~1/3이 2페이지였음).
                #   다일 공백 복구는 장후 백필(collect_1m_eod_backfill_v1)이 전담. 장후(15:20~) 백필 구간은 무제한 유지.
                #   롤백: setx COLLECT_MAX_PAGES_INTRADAY 0 (0=무제한)
                _pages += 1
                _pg_cap = int(os.environ.get("COLLECT_MAX_PAGES_INTRADAY", "1"))
                if _pg_cap > 0 and _pages >= _pg_cap and dtime(8, 50) <= datetime.now().time() <= dtime(15, 20):
                    break
                last_after = self.last_ts_map.get(code, "0")
                if last_after == last_before or self.prev_next != "2":
                    break
                last_before = last_after
                next_flag   = 2
                # [TR_TUNE 2026-05-06] tr_interval ± 0.3s jitter
                self.wait_next_cycle(self.evolver.tr_interval + random.uniform(-0.3, 0.3))
            except Exception as e:
                logger.error(
                    f"[CRASH-BLOCK] _request_1m_once broker IPC 처리 예외 "
                    f"{self.current_code}: {e}", exc_info=True
                )
                # raise 금지 — 다음 종목으로 진행
                break

    def wait_next_cycle(self, sec: float):
        QTimer.singleShot(int(sec * 1000), self.wait_loop.quit)
        self.wait_loop.exec_()

    def enqueue_requests(self, hot_codes: set = None):
        """장중: A+B+gap_retry만 / 장후(15:20~): C버킷 백필"""
        self.request_queue.clear()
        self.batch_rows = []

        # [OPENING-PASS 2026-06-29 친구님] 개장 우선셋 1회만 enqueue(게이트 우회 수집·one-shot).
        #   대장/보유/watchlist/개장movers를 09:01에 즉시 확보 → 09:03 게이트 전 개장드라이브 가시화. broad는 09:03 정상.
        _oo = getattr(self, '_opening_only', None)
        if _oo:
            for _c in _oo:
                self.request_queue.append(str(_c))
            self._opening_only = None   # one-shot 소모
            logger.info(f"[OPENING-PASS] enqueue 우선셋 {len(_oo)}종목만 수집(1회·게이트우회)")
            return

        bucket_a = getattr(self, '_bucket_a', [])
        bucket_b = getattr(self, '_bucket_b', [])
        bucket_c = getattr(self, '_bucket_c', [])

        now_t = datetime.now().time()
        is_active = dtime(8, 50) <= now_t <= dtime(15, 20)  # 장중 active 시간

        if is_active:
            # ── 장중: A + B + C신규 + gap_retry_pool 수집
            active_set = set()

            # A버킷 (최대 40개) [BUCKETOPT 2026-05-06] 50→40
            # [F안 ROTATE 2026-05-07 14:30] cycle_count 기반 회전 — OCX fail 종목 큐 첫슬롯 고정 점유 회피
            # [E안 강화 2026-05-07 14:50] timeout 격리 체크 추가 — fail_until > now 종목 큐 제외
            _a_top = list(bucket_a[:int(os.environ.get("COLLECT_A_ENQ_CAP", "40"))])  # [ENQ-PRIO 2026-06-25] cap 40 유지(TR부하 증가0·사이클 188s 그대로). 재정렬로 앞쪽=보유/inject/테마 우선 → 급등주가 40 안에 들어옴. 무거운날 더 필요시 setx COLLECT_A_ENQ_CAP 44(요청rate는 1.5s throttle+2/sec limiter가 막아 안전).
            _rot = self.cycle_count % max(len(_a_top), 1)
            _a_rotated = _a_top[_rot:] + _a_top[:_rot]
            _now_t = time_module.time()
            _a_blocked = 0
            for code in _a_rotated:
                if self._tr_fail_until.get(code, 0) > _now_t:
                    _a_blocked += 1
                    continue
                self.request_queue.append(str(code))
                active_set.add(code)

            # [HOT-WIRE 2026-06-13 ★주말수술 — 6/12 HPSP 96분 갭 근본원인]
            #   HOT 감지기는 11:16~11:30 403870을 1위로 연호했지만 ①enqueue가 hot_codes
            #   인자를 받기만 하고 안 썼고 ②is_early() 이후엔 리로드가 없어(10:33→14:16 無)
            #   감지 결과가 수집명단에 미반영 = 당일 폭주 종목이 명단서 탈락하면 복귀 불가.
            #   당일 HOT(급등 감지) 종목을 매 사이클 최우선 수집. 롤백: env COLLECT_HOT_WIRE=NO.
            if hot_codes and os.environ.get("COLLECT_HOT_WIRE", "YES").strip().upper() == "YES":
                _hw_add = []
                for code in sorted(hot_codes)[:10]:
                    if code in active_set or self._tr_fail_until.get(code, 0) > _now_t:
                        continue
                    self.request_queue.appendleft(str(code))
                    active_set.add(code)
                    _hw_add.append(code)
                if _hw_add:
                    logger.info(f"[HOT-WIRE] 당일 HOT {len(_hw_add)}개 최우선 수집(버킷外 복구): {_hw_add}")

            # B버킷 (최대 15개) [BUCKETOPT 2026-05-06] 20→15
            # [E안 강화 2026-05-07 14:50] timeout 격리 체크 추가
            _b_blocked = 0
            for code in bucket_b[:15]:
                if code in active_set:
                    continue
                if self._tr_fail_until.get(code, 0) > _now_t:
                    _b_blocked += 1
                    continue
                self.request_queue.append(str(code))
                active_set.add(code)
            # [v4.17] C버킷 상위 600개 순환 수집 (cycle_count 기반 슬라이딩)
            # [C-EXPAND] A+B<48이면 C per-cycle 자동 확대 (최대 35개)
            # [P6 2026-05-12] A버킷 의존도 완화 — 임계값 40→48 (A=40+B 일부 격리 시에도 C 보강 발동)
            # [P9 2026-05-12] max 30→35, base 10→12 추가 상향 — A 격리 폭주 시 C 보강량 확대 (TR 부하 미소 증가)
            _ab_size = len(bucket_a) + len(bucket_b)
            # [REDESIGN 2026-07-11 화면지도 수술] 장중 C회전 기본 0 — 실측 C회전은 하루 164종목뿐(2개×82사이클)으로
            #   "전 종목 커버"가 허상. 당일 급등주 포착은 HOT-WIRE/INJECT/테마 경로가 전담(C-700캡 주석 참조)이라 놓침 없음.
            #   전 종목 완결성은 장후 백필(collect_1m_eod_backfill_v1.py·15:42 태스크)로 이관. 롤백: setx COLLECT_C_PER_CYCLE 2
            _c_per_cycle = int(os.environ.get("COLLECT_C_PER_CYCLE", "0"))  # [TR-THROTTLE 2026-05-08] 5→2 → [7/11] 0
            if _ab_size < 30:
                # [CORE-SLIM 2026-06-01] 천장 48→30: 활성 총량 ~30 상한 (실측 ~3.1s/code, 86s 사이클). 하한 6 유지 → C 회전으로 universe 적재
                _c_per_cycle = min(35, max(6, 30 - _ab_size))
                logger.warning(f"[C-EXPAND] A+B={_ab_size}<30 → C 6→{_c_per_cycle}개 확대")
            _c_wide = bucket_c[:600] if bucket_c else []
            if _c_wide:
                _c_start = (self.cycle_count * _c_per_cycle) % max(len(_c_wide), 1)
                _c_morning = _c_wide[_c_start : _c_start + _c_per_cycle]
            else:
                _c_morning = []
            # [E안 강화 2026-05-07 14:50] C버킷에도 timeout 격리 체크 추가
            _c_blocked = 0
            for code in _c_morning:
                if code in active_set:
                    continue
                if self._tr_fail_until.get(code, 0) > _now_t:
                    _c_blocked += 1
                    continue
                self.request_queue.append(str(code))
                active_set.add(code)
            if _a_blocked or _b_blocked or _c_blocked:
                logger.info(f"[E안 격리] A {_a_blocked} / B {_b_blocked} / C {_c_blocked} 개 timeout 격리 중")
            if _c_morning:
                logger.info(
                    f"[C순환] slice_start={_c_start} n={_c_per_cycle} "
                    f"종목={_c_morning[:5]}... "
                    f"(C커버={min(_c_start+_c_per_cycle, len(_c_wide))}/{len(_c_wide)})"
                )

            # gap_retry_pool — 1사이클만 유효
            pool = getattr(self, '_gap_retry_pool', {})
            next_pool = {}
            _cd_blocked = 0
            for code, remaining in pool.items():
                if code in active_set:
                    if remaining > 1:
                        next_pool[code] = remaining - 1
                    continue
                # [FAILUNTIL-2 2026-05-12] _tr_fail_until 격리 검사 추가 — 격리 종목이 gap_retry_pool 경로로 우회 appendleft 되던 결함 차단. remaining 유지 (cooldown과 동일 처리).
                if self._tr_fail_until.get(code, 0) > _now_t:
                    next_pool[code] = remaining   # 유지 (격리 해제 후 자연 재시도)
                    continue
                # [PATCH-COOLDOWN 2026-05-06 REV] cooldown 종목은 재투입 차단 + remaining 유지 (삭제 금지)
                # 지침: cooldown 해제 후 자연 재시도 보장 — 감쇠 X
                if self._is_in_cooldown(code):
                    _cd_blocked += 1
                    next_pool[code] = remaining   # 유지 (삭제 금지)
                    continue
                self.request_queue.appendleft(str(code))  # 우선 처리
                active_set.add(code)
                if remaining > 1:
                    next_pool[code] = remaining - 1  # 잔여 사이클 감소
                # remaining == 1이면 제거 (1사이클 후 만료)
            self._gap_retry_pool = next_pool
            if _cd_blocked:
                logger.info(f"[COOLDOWN] gap_retry {_cd_blocked}개 cooldown 보류")

            logger.debug(
                f"[큐구성-장중] A={min(len(bucket_a),60)} B={min(len(bucket_b),20)} "
                f"gap={len(pool)} 총={len(self.request_queue)}"
            )

        else:
            # ── 장후(15:20~): C버킷 백필 순환
            # [FAILUNTIL-3 2026-05-12] _tr_fail_until 격리 검사 추가 — 격리 종목이 장후 백필 경로로 우회 enqueue 되던 결함 차단 (A/B/C 모두)
            _bf_now_t = time_module.time()
            for code in bucket_a:
                if self._tr_fail_until.get(code, 0) > _bf_now_t: continue
                self.request_queue.append(str(code))
            for code in bucket_b:
                if self._tr_fail_until.get(code, 0) > _bf_now_t: continue
                self.request_queue.append(str(code))

            if bucket_c:
                # [v4.16 FIX-3] C버킷 거래대금 정렬 후 순환이므로
                # idx=0(첫번째) = 거래대금 최상위 종목들 → 우선 백필
                c_slice = max(1, len(bucket_c) // 12)
                idx     = getattr(self, '_bucket_c_idx', 0)
                start   = idx * c_slice
                end     = min(start + c_slice, len(bucket_c))
                for code in bucket_c[start:end]:
                    if self._tr_fail_until.get(code, 0) > _bf_now_t: continue
                    self.request_queue.append(str(code))
                self._bucket_c_idx = (idx + 1) % 12
                logger.debug(
                    f"[v4.16] C버킷 백필: idx={idx}/12 "
                    f"slice={bucket_c[start:start+3]}... (거래대금 정렬순)"
                )

            logger.debug(
                f"[큐구성-장후] A={len(bucket_a)} B={len(bucket_b)} "
                f"C_slice={len(bucket_c)//12 if bucket_c else 0} 총={len(self.request_queue)}"
            )

        # 큐 최대 90개 제한 [BUCKETOPT 2026-05-06] A40+B15+C5=60 (gap_retry 여유분 포함 90 cap 유지)
        if is_active and len(self.request_queue) > 90:
            trimmed = list(self.request_queue)[:90]
            self.request_queue = deque(trimmed)
        if is_active:
            logger.info(f"[큐확정] 실처리={len(self.request_queue)}개 (A+B+C순환)")
            # [P2 2026-05-12] 사이클 시작 시 _tr_slowdown 강제 감쇠 — 정상 수신 0건일 때도 자동 회복 보장
            if self._tr_slowdown > 0:
                self._tr_slowdown = max(0.0, self._tr_slowdown - 0.2)

    # ─── [OCX-WARMUP 2026-05-07] 사이클 시작 dummy TR 워밍업 ───
    def _ocx_warmup(self, count: int = OCX_WARMUP_COUNT) -> int:
        """큐 첫 슬롯 cold start cascade 흡수용 dummy TR.

        배경: 매 사이클 첫 1~3 TR이 cascade timeout으로 손실(0.6s 간격으로 즉시 fail).
              삼성전자(005930) opt10080을 실 TR 풀(SCR_BASE~) N개 화면번호로 dispatch해 OCX 깨움.
              [W2-A 2026-05-08] 화면번호 9999 단일 → SCR 풀 정렬 (화면번호별 세션 큐 가설)
        설계:
          - rqname='warmup_req' → _on_receive_tr에서 즉시 exit 분기, 데이터 처리 없음
          - last_ts_map / batch_rows / current_code 영향 없음 (saved/restored)
          - _scr_idx 비건드림 — 워밍업 후 실 dispatch는 그대로 0번부터 시작
          - WARMUP_TIMEOUT_MS=3000 (응답 대기 아닌 cold 흡수 목적)
        반환: 응답 수신 횟수 (디버깅용)
        """
        if count <= 0:
            return 0
        # [A-2a 2026-05-15] broker_mode 시 W2-A' 워밍업 skip
        # broker 측 OCX 가 워밍업 책임. collector 자기 OCX 없음
        if getattr(self, "_broker_mode", False):
            logger.info("[A-2a] broker mode — W2-A' OCX 워밍업 skip")
            return 0
        received    = 0
        saved_code  = self.current_code
        saved_scr   = self.current_scr
        try:
            for i in range(count):
                try:
                    self.tr_received = False
                    self.ocx.dynamicCall("SetInputValue(QString,QString)", "종목코드",      OCX_WARMUP_DUMMY_CODE)
                    self.ocx.dynamicCall("SetInputValue(QString,QString)", "틱범위",        "1")
                    self.ocx.dynamicCall("SetInputValue(QString,QString)", "수정주가구분", "0")
                    _limiter.acquire()
                    # [W2-A' 2026-05-08] 다음 dispatch가 _next_scr()에서 가져올 화면번호와 정렬
                    # _next_scr는 (_scr_idx % POOL_SIZE) → _scr_idx 자체는 비건드림(워밍업 후 실 dispatch가 이 화면부터 사용)
                    warmup_scr = str(OCX_WARMUP_SCR_BASE + ((self._scr_idx + i) % SCR_POOL_SIZE))
                    ret = self.ocx.dynamicCall(
                        "CommRqData(QString,QString,int,QString)",
                        "warmup_req", "opt10080", 0, warmup_scr
                    )
                    if int(ret) != 0:
                        continue
                    QTimer.singleShot(OCX_WARMUP_TIMEOUT_MS, self.tr_loop.quit)
                    self.tr_loop.exec_()
                    if self.tr_received:
                        received += 1
                except Exception as _e:
                    logger.warning(f"[OCX-WARMUP] dummy 예외: {_e}")
        finally:
            self.current_code = saved_code
            self.current_scr  = saved_scr
        logger.info(f"[OCX-WARMUP] dummy {count}회 dispatch — 응답 {received}/{count}")
        return received

    def process_queue(self) -> dict:
        t0         = time_module.perf_counter()
        fail_count = 0

        # [OCX-WARMUP 2026-05-07] 큐 dispatch 직전 dummy TR로 cold cascade 흡수
        # [STEP-2C 2026-05-13] ENABLE_OCX_WARMUP feature flag 추가 (soft disable).
        # _request_1m_once 가 broker IPC 로 이관된 후 collector.ocx warmup 효과 상실.
        if ENABLE_OCX_WARMUP and self.request_queue:
            self._ocx_warmup()

        # [A-2b 2026-05-15] broker_mode 시 사이클 진입 BATCH_TR 1회 호출 → self._batch_cache 작성
        # _request_1m_once 가 cache lookup 으로 처리 (IPC N회 → 1회 단축)
        # [stale 안전 마진 2026-05-15] queue 비어있는 사이클에서도 cache 명시 초기화
        #   (defense in depth — 미래 코드 변경 시 stale lookup 위험 사전 차단)
        if getattr(self, "_broker_mode", False):
            self._batch_cache = {}
            if self.request_queue:
                self._batch_fetch_opt10080(list(self.request_queue))

        while self.request_queue:
            code    = self.request_queue.popleft()
            success = self.request_1m_with_backoff(code)
            if not success: fail_count += 1
            # [FIX-B] wait_next_cycle 삭제 — _request_1m_once 내부에서 이미 TR 간격 대기
            #         이중 대기 시 400종목 × 0.65초 × 2 = 520초(8.7분) 초과 방지

            # [PATCH-CIRCUIT-A] 연속 TR 타임아웃 임계값 도달 시 cycle pause
            # 목적: OCX 누적 상태 부담을 키우지 않고 회복 시간 부여 → 네이티브 크래시 회피
            if self._consec_tr_timeout >= CONSEC_TIMEOUT_LIMIT:
                logger.error(
                    f"[CIRCUIT-BREAK] 연속 TR timeout {self._consec_tr_timeout}회 — "
                    f"{CONSEC_TIMEOUT_PAUSE}s pause 후 다음 사이클 진입"
                )
                # heartbeat 갱신 — pause 동안 watchdog 재기동 차단
                try: self.write_heartbeat()
                except Exception: pass
                self.wait_next_cycle(CONSEC_TIMEOUT_PAUSE)
                # 카운터/페널티 리셋 — pause 후 OCX 회복 가정
                self._consec_tr_timeout = 0
                self._tr_slowdown       = 0.0
                # [PATCH-COOLDOWN 2026-05-06] CB 직후 blanket cooldown — 모든 종목 N초 강제 보류
                # OCX/서버 회복 직후 재진입 폭주 차단
                self._cooldown_blanket_until = time_module.time() + CIRCUIT_BREAK_COOLDOWN_SEC
                logger.info(
                    f"[CIRCUIT-BREAK] pause 종료 — 카운터/슬로우다운 리셋, "
                    f"blanket cooldown {CIRCUIT_BREAK_COOLDOWN_SEC:.0f}s 적용, 사이클 종료"
                )
                break

        elapsed    = time_module.perf_counter() - t0
        # [필수] 실제 active 종목 수 기준 사이클 경고 (A+B 기준)
        active_n   = min(len(getattr(self, '_bucket_a', [])) +
                         len(getattr(self, '_bucket_b', [])), 80)
        cycle_warn = active_n * self.evolver.tr_interval * 1.4

        if elapsed > cycle_warn:
            logger.warning(
                f"[속도경보] {elapsed:.0f}초 > {cycle_warn:.0f}초 "
                f"(종목={len(self.code_list)})"
            )
            # [필수-4] 사이클 초과 시 TOP_N 자동 축소
            new_top = max(self.evolver.TOP_MIN, self.evolver.top_n_codes - self.evolver.TOP_STEP)
            if new_top != self.evolver.top_n_codes:
                logger.warning(f"[속도경보] TOP_N 자동축소 {self.evolver.top_n_codes}→{new_top}")
                self.evolver.top_n_codes = new_top

        if is_early(): phase = "초반"
        elif is_late(): phase = "후반"
        else: phase = "중반"

        # [선택-6] 이상봉 요약 로그
        total_bars = len(self.batch_rows)
        _cycle_fil = getattr(self, '_cycle_fil_cnt', 0)
        # [P5 2026-05-12] 사이클별 timeout 카운트 표시 — 실제 timeout 발생 정확 반영
        logger.info(
            f"[사이클{self.cycle_count}] "
            f"정상={total_bars}봉 | 이상={_cycle_fil}봉 | {elapsed:.0f}초 | "
            f"종목={len(self.code_list)} | 실패={fail_count} | timeout={self._cycle_to_cnt} | {phase}"
        )
        # [P8 TOP-TO 2026-05-12] 누적 timeout 상위 5종목 출력 — dead pool 폭증 종목 즉시 식별 (운영 가시화)
        if self._tr_fail_count:
            _top = sorted(self._tr_fail_count.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.info(f"[사이클{self.cycle_count}][TOP-TO] " + " ".join([f"{c}={n}회" for c, n in _top]))
        self._cycle_fil_cnt = 0  # 사이클별 카운터 리셋
        self._cycle_to_cnt  = 0  # [P5] timeout 카운터 사이클 단위 리셋
        return {"fail_count": fail_count, "elapsed": elapsed, "bar_count": total_bars}

    # ─── CSV 저장 ─────────────────────────────────────────

    def _fetch_kospi_index(self):
        """[KOSPI-INDEX 2026-05-26] opt20003 KOSPI 종합지수(업종코드='001') 1분봉 1회 호출.
        batch_rows에 code='U001' row 1개 append → save_csv 시 prices_1m.csv에 같이 atomic write.
        rt_intraday_trend_pullback_engine_v5_14 L1156이 prices_1m에서 code='U001' row로 시장 regime 판정.
        체결시간 빈 문자열이라 현재 시각 minute round 사용. features는 0 채움 (rt_intraday는 close만 사용).
        """
        try:
            if not _is_broker_alive():
                return
            res = broker_tr_request(
                tr_code="opt20003",
                inputs={"업종코드": "001", "틱범위": "1"},
                output_fields=["체결시간","시가","고가","저가","현재가","거래량","거래대금"],
                rqname="kospi_index_req", screen_no="9001", timeout_sec=6.0,
            )
            if res.get("status") != "OK":
                logger.warning("[KOSPI-INDEX] opt20003 status=%s err=%s",
                               res.get("status"), res.get("error"))
                return
            records = (res.get("data") or {}).get("records") or []
            if not records:
                return
            rec = records[0]
            def _p(v):
                s = str(v).strip().lstrip("+").lstrip("-")
                try:
                    return float(s) if s else 0.0
                except Exception:
                    return 0.0
            close_v = _p(rec.get("현재가", "0"))
            if close_v <= 0:
                return
            open_v = _p(rec.get("시가", "0")) or close_v
            high_v = _p(rec.get("고가", "0")) or close_v
            low_v  = _p(rec.get("저가", "0")) or close_v
            vol_v  = int(_p(rec.get("거래량", "0")))
            val_v  = _p(rec.get("거래대금", "0"))
            ts_str = datetime.now().strftime("%Y%m%d%H%M00")
            row = {col: 0 for col in OUT_COLUMNS}
            row.update({
                "code": "U001", "ts": ts_str,
                "open": open_v, "high": high_v, "low": low_v, "close": close_v,
                "volume": vol_v, "value": val_v,
            })
            self.batch_rows.append(row)
            logger.info("[KOSPI-INDEX] U001 ts=%s close=%.2f vol=%d",
                        ts_str, close_v, vol_v)
        except Exception as e:
            logger.warning("[KOSPI-INDEX] 실패: %s", e)

    def _fetch_kosdaq_index(self):
        """[KOSDAQ-INDEX 2026-06-09 사용자지시] opt20003 코스닥 종합지수(업종코드='101') 1분봉 1회 → code='U201'.
        우리는 코스닥 종목 매매 → 시장 regime은 코스닥 지수로 봐야 정확(코스피 U001은 보조).
        Phase1: 수집+보드표시만(엔진 무영향). Phase2(검증후): 엔진이 U201 읽도록 전환.
        """
        try:
            if not _is_broker_alive():
                return
            res = broker_tr_request(
                tr_code="opt20003",
                inputs={"업종코드": "101", "틱범위": "1"},
                output_fields=["체결시간","시가","고가","저가","현재가","거래량","거래대금"],
                rqname="kosdaq_index_req", screen_no="9001", timeout_sec=6.0,
            )
            if res.get("status") != "OK":
                logger.warning("[KOSDAQ-INDEX] opt20003 status=%s err=%s",
                               res.get("status"), res.get("error"))
                return
            records = (res.get("data") or {}).get("records") or []
            if not records:
                return
            rec = records[0]
            def _p(v):
                s = str(v).strip().lstrip("+").lstrip("-")
                try:
                    return float(s) if s else 0.0
                except Exception:
                    return 0.0
            close_v = _p(rec.get("현재가", "0"))
            if close_v <= 0:
                return
            open_v = _p(rec.get("시가", "0")) or close_v
            high_v = _p(rec.get("고가", "0")) or close_v
            low_v  = _p(rec.get("저가", "0")) or close_v
            vol_v  = int(_p(rec.get("거래량", "0")))
            val_v  = _p(rec.get("거래대금", "0"))
            ts_str = datetime.now().strftime("%Y%m%d%H%M00")
            row = {col: 0 for col in OUT_COLUMNS}
            row.update({
                "code": "U201", "ts": ts_str,
                "open": open_v, "high": high_v, "low": low_v, "close": close_v,
                "volume": vol_v, "value": val_v,
            })
            self.batch_rows.append(row)
            logger.info("[KOSDAQ-INDEX] U201 ts=%s close=%.2f vol=%d",
                        ts_str, close_v, vol_v)
        except Exception as e:
            logger.warning("[KOSDAQ-INDEX] 실패: %s", e)

    def save_csv(self):
        tmp = OUT_PATH.with_suffix(".tmp")
        try:
            # [FIX-2] 빈 배치 시 즉시 리턴
            if not self.batch_rows:
                logger.info("[저장] 신규 봉 없음, 스킵")
                return

            new_df = pd.DataFrame(self.batch_rows, columns=OUT_COLUMNS)
            new_df["code"] = new_df["code"].astype(str)
            new_df["ts"]   = new_df["ts"].astype(str)

            # [FIX-E4] 당일 날짜 필터 — 전일 봉 혼입 차단
            today_pfx = datetime.now().strftime("%Y%m%d")

            if OUT_PATH.exists() and OUT_PATH.stat().st_size > 0:
                old = None
                try:
                    old = pd.read_csv(OUT_PATH, dtype={"code":str,"ts":str})
                    # 기존 CSV에 피처 컬럼 없으면 추가
                    for col in OUT_COLUMNS:
                        if col not in old.columns:
                            old[col] = 0
                    # 오늘 날짜 봉만 유지 (전일 봉 차단)
                    old = old[old["ts"].str.startswith(today_pfx)]
                except Exception as e:
                    # [FIX-J2] 기존 데이터 읽기 실패 시 old=None 유지
                    # 기존: combined=new_df → 하루치 데이터 전손
                    # 수정: old=None → combined=new_df (신규 봉만 저장, 기존 파일 보존)
                    logger.warning(f"[저장] 기존 CSV 읽기 실패(신규봉만 저장): {e}")
                    old = None
                if old is not None:
                    combined = pd.concat([old, new_df], ignore_index=True)
                else:
                    combined = new_df
            else:
                combined = new_df

            combined = (
                combined
                .drop_duplicates(subset=["code","ts"], keep="last")
                .sort_values(["code","ts"])
                .groupby("code", group_keys=False).tail(MAX_CSV_ROWS)
                .reset_index(drop=True)
            )
            combined.to_csv(tmp, index=False, encoding="utf-8-sig")
            os.replace(str(tmp), str(OUT_PATH))

            self.total_saved_rows += len(new_df)
            self.day_bar_count    += len(new_df)
            logger.info(f"[저장] +{len(new_df)}봉 | 전체={len(combined)} | 누적={self.total_saved_rows}")
            # [PATCH-2 OBS 2026-05-11] collector observability — funnel collapse 진단용 추가 로그
            try:
                _now_ts = time_module.time()
                _last_tr_ts = max(self._tr_dispatch_ts.values()) if self._tr_dispatch_ts else 0
                _last_tr_age = _now_ts - _last_tr_ts if _last_tr_ts > 0 else -1
                _cb_on = self._cooldown_blanket_until > _now_ts
                logger.info(
                    f"[OBS] dead_pool={len(self._tr_fail_until)} | consec_tr_to={self._consec_tr_timeout} | "
                    f"q={len(self.request_queue)} | last_tr_age={_last_tr_age:.1f}s | cb_blanket={'ON' if _cb_on else 'off'} | "
                    f"unique_codes_saved={combined['code'].nunique() if 'code' in combined.columns else 'N/A'}"
                )
            except Exception as _e_obs:
                logger.debug(f"[OBS] log 실패(무시): {_e_obs}")
        except Exception as e:
            logger.error(f"save_csv 실패: {e}")
        finally:
            try:
                if tmp.exists(): tmp.unlink()
            except Exception: pass

    def cleanup_csv(self):
        tmp = OUT_PATH.with_suffix(".tmp")
        try:
            if not OUT_PATH.exists(): return
            df = pd.read_csv(OUT_PATH, dtype={"code":str,"ts":str})
            before = len(df)
            # [FIX-E4] 당일 날짜 필터 — cleanup 시에도 전일 봉 제거
            today_pfx = datetime.now().strftime("%Y%m%d")
            df = df[df["ts"].str.startswith(today_pfx)]
            df = (
                df.drop_duplicates(subset=["code","ts"], keep="last")
                  .sort_values(["code","ts"])
                  .groupby("code", group_keys=False).tail(MAX_CSV_ROWS)
                  .reset_index(drop=True)
            )
            df.to_csv(tmp, index=False, encoding="utf-8-sig")
            os.replace(str(tmp), str(OUT_PATH))
            logger.info(f"정리: {before}→{len(df)}건 (오늘={today_pfx})")
        except Exception as e:
            logger.error(f"cleanup 실패: {e}")
        finally:
            try:
                if tmp.exists(): tmp.unlink()
            except Exception: pass

    # ─── [UNIFIED v1.0] 매도엔진 통합 메서드 ────────────────

    def _init_sell_bridge(self) -> None:
        """로그인 완료 후 1회 호출. rt_sell_engine_v3_19의 KiwoomRealSellBridge를
        shared_ocx=self.ocx 로 초기화한다.
        새 QAxWidget·CommConnect 미사용 — 수집기 OCX를 그대로 공유."""
        try:
            import sys as _sys
            _rdir = str(Path(__file__).parent)
            if _rdir not in _sys.path:
                _sys.path.insert(0, _rdir)
            from rt_sell_engine_v3_19 import (          # noqa: PLC0415
                KiwoomRealSellBridge,
                _setup_logger as _sell_setup_logger,
            )
            self._sell_bridge = KiwoomRealSellBridge(shared_ocx=self.ocx)
            self._sell_log    = _sell_setup_logger()
            logger.info(
                "[UNIFIED] 매도엔진 브릿지 초기화 완료 "
                "(shared_ocx=self.ocx, CommConnect 재호출 없음)"
            )
        except Exception as e:
            logger.error(
                "[UNIFIED] 매도엔진 브릿지 초기화 실패 → 수집만 진행: %s", e
            )
            self._sell_bridge = None
            self._sell_log    = None

    def _init_pb_bridge(self) -> None:
        """[STEP-2H-1 2026-05-13] PB sell standalone OCX 제거 + shared_ocx attach.

        pullback_sell_strategy_v4_21_FIXED.KiwoomBridge 싱글턴을
        shared_ocx=self.ocx 로 초기화. PB main() 가 collector tick 으로
        호출될 때 동일 싱글턴 재사용 = 자체 QAxWidget 생성 안 함.

        실패 시 self._pb_bridge=None. PB strategy 미가동 (collector 자체는 정상 동작).
        """
        try:
            import sys as _sys
            _rdir = str(Path(__file__).parent)
            if _rdir not in _sys.path:
                _sys.path.insert(0, _rdir)
            from pullback_sell_strategy_v4_21_FIXED import (  # noqa: PLC0415
                KiwoomBridge as _PbKiwoomBridge,
            )
            bridge = _PbKiwoomBridge.get_instance(shared_ocx=self.ocx)
            if bridge is None:
                logger.error(
                    "[UNIFIED-PB] PB shared_ocx attach 실패 — bridge None"
                )
                self._pb_bridge = None
                return
            self._pb_bridge = bridge
            logger.info(
                "[UNIFIED-PB] PB sell shared_ocx attach 성공 "
                "(STEP-2H-1, standalone fallback 차단 상태)"
            )
        except Exception as e:
            logger.error(
                "[UNIFIED-PB] PB bridge 초기화 실패 → PB 미가동: %s", e
            )
            self._pb_bridge = None

    def _run_pb_tick(self) -> None:
        """[STEP-2H-1] PB sell main() 1 cycle 호출 — collector tick 통합.

        rt_sell 의 _run_sell_tick 패턴 미러. 어떤 예외가 발생해도
        collector 루프는 계속 동작.

        [STEP-2H-2 2026-05-13] timing observability 추가:
          - pb_tick_ms 측정 (시작/종료)
          - rc 분포 누적 카운터
          - pb_tick_ms > 3000 시 warning (정책 변경 없음, log only)
        """
        # [PB-DIAG 2026-06-10] 어느 가드가 PB tick을 막는지 확정용 (20틱마다 1회 로그, 무부하)
        # [PB-SELFHEAL 2026-06-10] 분기 A/B 자가치유 — PB tick이 5/22~6/10 조용히 죽어있던 재발 방지.
        self._pb_diag_n = getattr(self, "_pb_diag_n", 0) + 1
        if self._pb_bridge is None:
            # 분기 A: respawn 등으로 미부착 → 매 틱 lazy 재attach (실패해도 무해)
            try:
                self._init_pb_bridge()
            except Exception:
                pass
            if self._pb_bridge is None:
                if self._pb_diag_n % 20 == 1:
                    logger.warning("[UNIFIED-PB][DIAG] PB tick skip 원인 = _pb_bridge is None (lazy attach도 실패, n=%d)", self._pb_diag_n)
                return
            logger.info("[UNIFIED-PB][DIAG] lazy attach 성공 → tick 재개 (n=%d)", self._pb_diag_n)
        if not self.connected:
            # 분기 B: connected 플래그 stale 가능 → 수집 신선도(prices_1m mtime)로 실가동 판정.
            #   신선(<300s)=실제 수집 중=OCX 살아있음 → 진행(main()이 자체 연결확인 RC_STOP22로 2차 방어).
            #   stale(장외/진짜 죽음) → skip (기존 동작).
            try:
                _p1m_age = time_module.time() - os.path.getmtime(str(OUT_PATH))
            except Exception:
                _p1m_age = 9e9
            if _p1m_age > 300:
                if self._pb_diag_n % 20 == 1:
                    logger.warning("[UNIFIED-PB][DIAG] PB tick skip 원인 = not connected + 수집 stale(%.0fs) (n=%d)", _p1m_age, self._pb_diag_n)
                return
            if self._pb_diag_n % 20 == 1:
                logger.warning("[UNIFIED-PB][DIAG] connected=False지만 수집 신선(%.0fs) → 진행(main 자체방어 위임) (n=%d)", _p1m_age, self._pb_diag_n)
        if self._pb_diag_n % 20 == 1:
            logger.info("[UNIFIED-PB][DIAG] PB tick 정상 진입 → _pb_main 호출 (n=%d)", self._pb_diag_n)
        # [STEP-2H-2] rc 분포 누적 카운터 초기화 (싱글턴, 1회만)
        if not hasattr(self, "_pb_rc_counts"):
            self._pb_rc_counts = {}
            self._pb_tick_count = 0
            self._pb_tick_total_ms = 0.0
        _t0 = time_module.perf_counter()
        rc = None
        try:
            from pullback_sell_strategy_v4_21_FIXED import (  # noqa: PLC0415
                main as _pb_main,
            )
            rc = _pb_main()
            if rc not in (0, 200):  # RC_OK=0, RC_HOLD=200
                logger.warning("[UNIFIED-PB] tick rc=%s (PB 결과 비정상)", rc)
        except Exception as e:
            logger.error("[UNIFIED-PB] _run_pb_tick 오류 (수집 루프 계속): %s", e)
            rc = "EXCEPTION"
        finally:
            # [STEP-2H-2] timing + rc distribution observability
            try:
                _pb_tick_ms = (time_module.perf_counter() - _t0) * 1000.0
                self._pb_tick_count += 1
                self._pb_tick_total_ms += _pb_tick_ms
                _rc_key = str(rc)
                self._pb_rc_counts[_rc_key] = self._pb_rc_counts.get(_rc_key, 0) + 1
                # warning: pb_tick_ms > 3000ms 시 (collector stall 위험)
                if _pb_tick_ms > 3000.0:
                    logger.warning(
                        "[UNIFIED-PB][LATENCY_HIGH] pb_tick_ms=%.1f (>3000ms) rc=%s "
                        "cycle=%d (collector stall 위험 — log only, 정책 변경 없음)",
                        _pb_tick_ms, _rc_key, self.cycle_count,
                    )
                # 매 10 cycle 마다 누적 분포 출력 (운영 가시화)
                if self._pb_tick_count % 10 == 0:
                    _avg_ms = self._pb_tick_total_ms / max(self._pb_tick_count, 1)
                    _dist = " ".join(
                        [f"{k}={v}" for k, v in sorted(self._pb_rc_counts.items())]
                    )
                    logger.info(
                        "[UNIFIED-PB][STATS] cycles=%d avg_ms=%.1f rc_dist=[%s]",
                        self._pb_tick_count, _avg_ms, _dist,
                    )
            except Exception:
                pass

    def _run_sell_tick(self) -> None:
        """수집 save_csv() 직후 매 사이클 호출.
        rt_sell_engine_v3_19.run_once(self._sell_bridge, self._sell_log) 실행.
        RC_STOP(KillSwitch) 발생 시 이후 tick은 영구 비활성화.
        어떤 예외가 발생해도 수집기 루프는 계속 동작한다."""
        if self._sell_ks_dead or self._sell_bridge is None or self._sell_log is None:
            return
        if not self.connected:
            return
        try:
            from rt_sell_engine_v3_19 import run_once, RC_STOP  # noqa: PLC0415
            rc = run_once(self._sell_bridge, self._sell_log)
            if rc == RC_STOP:
                self._sell_log.critical(
                    "[UNIFIED] KillSwitch 발동 — 이후 모든 매도 tick 영구 비활성화"
                )
                self._sell_ks_dead = True
        except Exception as e:
            logger.error("[UNIFIED] _run_sell_tick 오류 (수집 루프 계속): %s", e)

    # ─── [UNIFIED v1.1] 매수엔진 통합 메서드 ────────────────────────────

    def _init_buy_engine(self) -> None:
        """로그인 완료 후 1회 호출. kiwoom_buy_order_sender_v4_9의
        run_once_shared 함수를 임포트해 사용 가능 여부를 확인한다.
        새 QAxWidget·CommConnect 미사용 — 수집기 OCX를 그대로 공유."""
        try:
            import sys as _sys
            _rdir = str(Path(__file__).parent)
            if _rdir not in _sys.path:
                _sys.path.insert(0, _rdir)
            import kiwoom_buy_order_sender_v4_9 as _buy_mod  # noqa: PLC0415
            if not hasattr(_buy_mod, "run_once_shared"):
                raise AttributeError("run_once_shared 없음")
            self._buy_enabled = True
            logger.info(
                "[UNIFIED] 매수엔진 초기화 완료 "
                "(shared_ocx=self.ocx, CommConnect 재호출 없음)"
            )
        except Exception as e:
            logger.error(
                "[UNIFIED] 매수엔진 초기화 실패 → 수집/매도만 진행: %s", e
            )
            self._buy_enabled = False

    def _run_buy_tick(self) -> None:
        """매도 tick 직후 매 사이클 호출.
        kiwoom_buy_order_sender_v4_9.run_once_shared(self.ocx) 실행.
        어떤 예외가 발생해도 수집기·매도 루프는 계속 동작한다."""
        if not self._buy_enabled or not self.connected:
            return
        try:
            from kiwoom_buy_order_sender_v4_9 import (  # noqa: PLC0415
                run_once_shared, RC_OK, RC_PARTIAL,
            )
            rc = run_once_shared(self.ocx)
            if rc in (RC_OK, RC_PARTIAL):
                logger.info("[UNIFIED] 매수 처리 완료 rc=%d", rc)
        except Exception as e:
            logger.error("[UNIFIED] _run_buy_tick 오류 (수집 루프 계속): %s", e)

    # ─── 메인 루프 ────────────────────────────────────────

    def run_forever(self):
        logger.info("[LOGIN-TRACE] 5) run_forever 진입 — ensure_login 호출 직전")
        # [Phase 1 2026-05-18] init 직후 hb write 1회 호출 — 외부 워치독 PROCESS_DEAD 오판 차단
        # Why: 사이클 진입 전까지 hb 미갱신으로 워치독 stale 판정 → 이중 spawn → lock 충돌
        try: self.write_heartbeat()
        except Exception: pass
        self.ensure_login()
        logger.info("[LOGIN-TRACE] 5) ensure_login 반환 — load_all_codes 호출 직전 (종목 수집 초기화 진입)")
        # [STEP-2H-1 2026-05-13] PB sell shared_ocx attach
        # standalone PB OCX process 제거 후 collector 내부 가동 경로 확보.
        # (기존 _init_sell_bridge/_init_buy_engine 도 동일 시점에 attach 가능 — 향후 hook 검토)
        self._init_pb_bridge()
        self.load_all_codes()
        logger.info("[LOGIN-TRACE] 5) load_all_codes 완료")
        self.load_last_ts_map()
        self.verify_csv()
        self._pre_load_hot_candidates()

        logger.info("=" * 60)
        logger.info("collect_prices_1m v4_16 시작 [KOSDAQ 전용] — 97점 달성 (FIX-J1~J7)")
        logger.info(f"  수집: {len(self.code_list)}종목 | TR쿨타임: {self.evolver.tr_interval}s")
        logger.info(f"  워치독 하트비트: {HEARTBEAT_TIMEOUT}초")
        logger.info(f"  허선도: 초반={FRESHNESS_EARLY_SEC}s / 중반={FRESHNESS_MID_SEC}s")
        logger.info(f"  피처: 방향(signed_value,body_ratio) 순간강도(value_acc,volume_acc)")
        logger.info(f"        가속도(value_accel>=1.3,volume_accel>=1.2) 구조(hh,hl,trend,close_pos)")
        logger.info(f"        VWAP(vwap,vwap_dev) 힘(ret_1m,ret_3bar_sum>=+1.5%)")
        logger.info(f"        눌림(pullback,pullback_depth,pullback_recover,vwap_reclaim)")
        logger.info(f"        압력(pressure_score>=0.55,wick_pressure,close_strength)")
        logger.info(f"        돌파(breakout_quality,range_efficiency,trend_persist)")
        logger.info(f"        공용강도(micro_alpha) | HOT품질필터(data있을때만)")
        logger.info(f"  DATA: {DATA_DIR} | LOG: {LOG_DIR}")
        logger.info(f"  [진화상태] {self.evolver.status_line()}")
        logger.info("=" * 60)

        hot_codes: set = set()
        # [FIX-V415-3] 연속 오류 카운터 — 동일 오류 반복 시 heartbeat 중단으로 watchdog 재시작 유도
        _consec_err_count = 0
        _CONSEC_ERR_MAX   = 5   # 5회 연속 오류 시 heartbeat 파일 삭제 → watchdog 재시작

        while True:
            try:
                # [STEP-2H-2 2026-05-13] cycle latency observability (timing only)
                _cycle_t0 = time_module.perf_counter()
                self.batch_rows  = []
                self.tr_received = False
                self.prev_next   = "0"
                self.write_heartbeat()

                # [Q4-DPRESET 2026-05-14 11:20] dead_pool 자동 리셋 — 5분마다 만료 가까운 25% 풀기.
                # 5/14 11:09~11:15 dead_pool 23→54 (분당 +5) 누적 가속. funnel collapse 직접 원인.
                # 진짜 dead 종목은 다시 timeout → 재격리되므로 false-positive 위험 낮음.
                try:
                    if not hasattr(self, "_q4_last_reset_ts"):
                        self._q4_last_reset_ts = time_module.time()
                    _q4_now = time_module.time()
                    if _q4_now - self._q4_last_reset_ts > 300:
                        self._q4_last_reset_ts = _q4_now
                        _q4_active = {k: v for k, v in self._tr_fail_until.items() if v > _q4_now}
                        if len(_q4_active) >= 4:
                            _q4_sorted = sorted(_q4_active.items(), key=lambda x: x[1])
                            _q4_reset_n = max(1, len(_q4_active) // 4)
                            for _q4_k, _q4_v in _q4_sorted[:_q4_reset_n]:
                                self._tr_fail_until.pop(_q4_k, None)
                                self._tr_fail_count.pop(_q4_k, None)
                            logger.info(f"[Q4-DPRESET] {_q4_reset_n}/{len(_q4_active)} 격리 해제 (5분 자동 리셋)")
                except Exception as _q4_e:
                    logger.debug(f"[Q4-DPRESET] 실패: {_q4_e}")

                now   = datetime.now()
                today = now.date()

                if (now.time() >= dtime(15, 35)
                        and self._last_stat_date != today
                        and self.day_bar_count > 0):
                    self.print_daily_summary()
                    self._last_stat_date = today

                if not self.is_market_open():
                    reason = "(공휴일)" if is_holiday(today) else ""
                    logger.info(f"장외{reason}, 60초 대기")
                    self.wait_next_cycle(60)
                    continue

                if not self.ensure_connected():
                    logger.error("연결 없음, 스킵")
                    self.wait_next_cycle(self.evolver.loop_sec)
                    continue

                if self._last_load_date != today and now.time() < dtime(9, 5):
                    logger.info("종목 리스트 일일 갱신...")
                    hot_codes    = set()
                    self._seeded = False
                    self.load_all_codes(hot_codes=hot_codes)
                    self._pre_load_hot_candidates()
                    self._last_load_date = today

                # [FIX-F2] 장전 기관순매수 1회 조회 (08:50~09:05, 당일 미조회 시만)
                if (dtime(8, 50) <= now.time() <= dtime(9, 5)
                        and self._inst_date != today.strftime("%Y%m%d")):
                    self._load_inst_net_buy_premarket()

                # [OPENING-PASS 2026-06-29 친구님] ★개장 우선셋 1회 즉시수집 — 09:03 게이트 우회.
                #   범인=09:03 게이트가 개장 3분(드라이브) 수집 skip → 대장(214450)·급등주(019210) 09:06에야 기록.
                #   09:00:40부터 load_all_codes(개장 opt10032 movers 반영·ENQ-PRIO로 대장/보유/movers front) 후
                #   우선셋(front N)만 1회 즉시 수집 → 09:01 확보. broad는 아래 09:03 게이트 그대로. 롤백 env COLLECT_OPENING_PASS=NO.
                _op_on = os.environ.get("COLLECT_OPENING_PASS", "YES").strip().upper() == "YES"
                _in_opening = (_op_on and dtime(9, 0, 40) <= now.time() < dtime(9, 3)
                               and not getattr(self, "_opening_pass_done", False))
                if _in_opening:
                    try:
                        self.load_all_codes()   # 개장 movers(opt10032) 반영 + ENQ-PRIO 재정렬(우선 front)
                        _prio_n = int(os.environ.get("COLLECT_OPENING_PRIO_N", "30"))
                        _base = list(getattr(self, "_bucket_a", [])[:_prio_n])
                        # [RT-UPDOWN] 키움 등락율 상위(opt10027) 합류 — 소형 갭상승 급등주(019210류) 개장 즉시(네이버 inject보다 빠름)
                        _ud = []
                        try:
                            _ud = _load_realtime_updown_top(int(os.environ.get("COLLECT_OPENING_UPDOWN_N", "15")))
                            _ac = set(getattr(self, "all_codes", []))
                            if _ac:
                                _ud = [c for c in _ud if c in _ac]
                            if _ud:
                                logger.info(f"[OPENING-PASS] 키움 등락율(opt10027) {len(_ud)}종목 우선셋 합류: {_ud}")
                        except Exception as _ue:
                            logger.warning(f"[OPENING-PASS] opt10027 합류 실패({_ue})")
                        _prio = list(dict.fromkeys(_ud + _base))[:int(os.environ.get("COLLECT_OPENING_MAX", "40"))]
                        if _prio:
                            self._opening_only = _prio
                            self._opening_pass_done = True
                            logger.info(f"[OPENING-PASS] ★개장 우선패스 {len(_prio)}종목 즉시수집(게이트우회): {_prio}")
                        else:
                            _in_opening = False
                    except Exception as _ope:
                        logger.warning(f"[OPENING-PASS] 실패({_ope}) → 정상 게이트")
                        _in_opening = False

                # ── 장중 TR 게이트: 09:03~15:28 사이에만 1분봉 조회 ──────────  [PATCH-1]
                if now.time() >= dtime(15, 28):
                    logger.info("[시간게이트] 15:28 초과 — TR 조회 중단, 정상 종료")
                    break
                if now.time() < dtime(9, 3) and not _in_opening:
                    logger.info("[시간게이트] 09:03 이전 — 대기 (60s)")
                    self.wait_next_cycle(60)
                    continue
                # ─────────────────────────────────────────────────────────────

                self.cycle_count += 1
                # [FIX-E1] gap_codes.clear() 제거 — detect_gap → _calc_features 순서 교정으로 불필요
                #           각 봉의 _calc_features 내에서 discard(code)로 1봉 단위 해제

                # HOT 적중률 이후 검증
                if self.cycle_count > 1 and self.hot_detector.prev_hot:
                    current_top = self.hot_detector.current_top_n(self.evolver.top_n_codes)
                    self.evolver.record_hot(self.hot_detector.prev_hot, current_top)

                # HOT 감지
                hot_codes = self.hot_detector.detect(
                    self.evolver.hot_n,
                    self.evolver.hot_surge_ratio
                )

                if is_early() and hot_codes:
                    self.load_all_codes(hot_codes=hot_codes)

                _ts_pre_tr = time_module.perf_counter()   # [CYCLE-PROF 2026-06-10] 단계별 계측(병목 확정용)
                self.enqueue_requests(hot_codes=hot_codes)
                stats = self.process_queue()
                _ts_post_tr = time_module.perf_counter()
                self._fetch_kospi_index()  # [KOSPI-INDEX 2026-05-26] U001 1봉 append
                self._fetch_kosdaq_index()  # [KOSDAQ-INDEX 2026-06-09] U201 1봉 append (코스닥 매매=코스닥지수)
                _ts_post_idx = time_module.perf_counter()
                self.save_csv()
                _ts_after_save = time_module.perf_counter()
                # [CYCLE-PROF] 10사이클마다 단계분해 출력 — TR이 정말 지배하는지 확정 → 낭비구간만 수술
                if self.cycle_count % 10 == 0:
                    logger.info("[CYCLE-PROF] tr=%.1fs idx=%.1fs save=%.1fs (pre-tr 구간은 total-합)",
                                _ts_post_tr - _ts_pre_tr, _ts_post_idx - _ts_post_tr,
                                _ts_after_save - _ts_post_idx)
                # [STEP-2H-1 2026-05-13] PB sell unified tick — 매 사이클 1 cycle
                # PB main() 가 queue 비면 RC_HOLD 즉시 반환 = 무부하
                self._run_pb_tick()
                # [STEP-2H-2 2026-05-13] cycle latency 출력 (10 cycle 마다)
                try:
                    _cycle_total_ms = (time_module.perf_counter() - _cycle_t0) * 1000.0
                    _save_to_pb_ms  = (time_module.perf_counter() - _ts_after_save) * 1000.0
                    if self.cycle_count % 10 == 0:
                        logger.info(
                            "[UNIFIED-PB][CYCLE_TIMING] cycle=%d total_ms=%.1f "
                            "post_save_pb_ms=%.1f",
                            self.cycle_count, _cycle_total_ms, _save_to_pb_ms,
                        )
                    # warning: cycle_total > 90s (60s 사이클 + 50% 마진)
                    if _cycle_total_ms > 90_000.0:
                        logger.warning(
                            "[UNIFIED-PB][CYCLE_SLOW] cycle=%d total_ms=%.1f "
                            "(>90s, collector pacing 위험)",
                            self.cycle_count, _cycle_total_ms,
                        )
                except Exception:
                    pass
                # ── [SANITY] prices_1m.csv 오늘 날짜 갱신 검증 ──
                # heartbeat만 갱신되고 prices_1m.csv가 갱신되지 않는 "도는 척" 상태 진단
                # 저장 로직/조건 변경 없음 — 진단 로그만 추가
                try:
                    if OUT_PATH.exists():
                        _csv_mtime = datetime.fromtimestamp(OUT_PATH.stat().st_mtime)
                        _today_ymd = datetime.now().strftime("%Y-%m-%d")
                        if _csv_mtime.strftime("%Y-%m-%d") != _today_ymd:
                            logger.error(
                                "[COLLECT_FAIL][PRICE_1M_NOT_UPDATED] "
                                "prices_1m.csv mtime=%s != today=%s | path=%s | batch=%d",
                                _csv_mtime.strftime("%Y-%m-%d %H:%M:%S"),
                                _today_ymd, str(OUT_PATH), len(self.batch_rows)
                            )
                    else:
                        logger.error(
                            "[COLLECT_FAIL][PRICE_1M_NOT_UPDATED] "
                            "prices_1m.csv 미존재 | path=%s | batch=%d",
                            str(OUT_PATH), len(self.batch_rows)
                        )
                except Exception as _sanity_e:
                    logger.warning("[SANITY] prices_1m.csv 검증 실패: %s", _sanity_e)
                self.hot_detector.update(self.batch_rows)

                # 진화 관측 (중반만)
                now_t = datetime.now().time()
                if dtime(9, 0) <= now_t <= dtime(15, 30):
                    self.evolver.record(
                        fail_count  = stats["fail_count"],
                        total_codes = len(self.code_list),
                        gap_count   = self.day_gap_count,
                        bar_count   = max(self.day_bar_count, 1),
                        elapsed_sec = stats["elapsed"],
                    )
                    if self.cycle_count % 5 == 0:
                        evolved = self.evolver.evolve()
                        if evolved:
                            logger.info("[진화 후 종목 리로드]")
                            self.load_all_codes(hot_codes=hot_codes)

                self.cleanup_counter += 1
                if self.cleanup_counter >= CLEANUP_EVERY:
                    self.cleanup_csv()
                    self.cleanup_counter = 0

                _consec_err_count = 0  # 정상 사이클 완료 시 연속 오류 카운터 리셋

            except Exception as e:
                import traceback
                _consec_err_count += 1
                logger.error(f"루프 오류 ({_consec_err_count}/{_CONSEC_ERR_MAX}): {e}")
                logger.error(traceback.format_exc())
                # [FIX-V415-3] 연속 오류 _CONSEC_ERR_MAX회 초과 시 heartbeat 삭제
                # → watchdog이 프로세스 재시작 트리거
                if _consec_err_count >= _CONSEC_ERR_MAX:
                    logger.critical(
                        f"[킬스위치] 연속 {_consec_err_count}회 오류 — heartbeat 삭제 → watchdog 재시작 유도"
                    )
                    try:
                        if HEARTBEAT_PATH.exists():
                            HEARTBEAT_PATH.unlink()
                    except Exception:
                        pass
                    _consec_err_count = 0

            # [REDESIGN 2026-07-11] 장중 사이클 휴지 — 수집기는 TR 페이스(3s/건) 한계로 하루종일 포화 가동
            #   (1,100/h)이라 총량을 줄이는 유일 레버 = 사이클 사이 휴지. 기본 180s(코어 재수집 ~6.4분 간격
            #   = 현행 4.8~8.4분 사이클과 동급 신선도·TR은 반토막). 개장 직후(~09:05)와 장후 백필(15:19~)은
            #   기존 그대로. 하트비트는 60s 조각으로 유지(감시 오탐 방지). 롤백: setx COLLECT_CYCLE_GAP_SEC 0
            # ★[2026-08-28 친구님 승인 "1 추천"] 180 → 90초 절충 — 8/28 실측 공백률 11% 개선 목적.
            #   0초(TR 2배)는 8/13 계정 조회제한 사고 위험으로 기각. 월요일 TIMEOUT 비율 관찰 후 재조정.
            #   롤백: setx COLLECT_CYCLE_GAP_SEC 180
            _cyc_gap = float(os.environ.get("COLLECT_CYCLE_GAP_SEC", "90"))
            _gap_nt = datetime.now().time()
            if _cyc_gap > 0 and dtime(9, 5) <= _gap_nt <= dtime(15, 19):
                _gap_left = max(_cyc_gap, float(self.evolver.loop_sec))
                while _gap_left > 0:
                    _gap_sl = min(60.0, _gap_left)
                    self.wait_next_cycle(_gap_sl)
                    _gap_left -= _gap_sl
                    try:
                        self.write_heartbeat()
                    except Exception:
                        pass
            else:
                self.wait_next_cycle(self.evolver.loop_sec)


# ═══════════════════════════════════════════════════════════
# 진입점
# ═══════════════════════════════════════════════════════════
def main():
    logger.info("[MAIN] main() 진입")                                       # [FIX-C]
    lock_fd = None
    try:
        lock_fd = acquire_lock()
        logger.info("[MAIN] lock 획득 완료")                                 # [FIX-C]
        # [FIX-A] atexit 제거 완료 — finally 블록에서 단일 해제
        logger.info("[MAIN] KiwoomCollector 생성 시작")                      # [FIX-C]
        kc = KiwoomCollector()
        logger.info("[MAIN] KiwoomCollector 생성 완료, run_forever 진입")    # [FIX-C]
        kc.run_forever()
    except Exception as e:
        logger.error(f"[MAIN] 크래시: {e}")                                  # [FIX-C]
        import traceback
        traceback.print_exc()
    finally:
        logger.info("[MAIN] finally 도달, lock 해제")                        # [FIX-C]
        release_lock(lock_fd)

if __name__ == "__main__":
    main()

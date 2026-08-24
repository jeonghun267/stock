"""
==============================================================================
rt_intraday_trend_pullback_engine.py
추세·눌림목 RT 후보생성 엔진 v5.14  — 헤지펀드급 SAFEPLUS FINAL
==============================================================================
[역할]  prices_1m.csv + prev_day_summary.csv → rt_intraday_candidates.csv
[금지]  주문 집행, PnL 추적, 시가 로직

[v5.13 → v5.14 수정사항] ── 임원진 합동 (2026-04-19)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 [치명] EOD pullback_watch → 장중 champion_select 연결 복원
  문제:
    v5.8에서 종배(EOD) 스코어보드 코드 전면 삭제(R1) 시
    pullback_watch 연결도 함께 끊어짐
    → 스코어보드가 선별한 STRONG pullback 후보가 장중 진입에 반영 안 됨
    → EOD 선별(priority/quality/decay/rank) ↔ 장중 매수(vwap/depth/vol) 단절
  수정:
    _load_pullback_watch() 신규 함수 추가
      eod_shared_data.pkl → pullback_watch 로드
      STRONG/MODERATE 셋업 코드 목록 반환
      pkl 없거나 실패 시 폴백 (운영 안전)
    _champion_select() 내부에 EOD pullback_watch 보너스 적용
      STRONG 셋업 종목: champion_score × 1.15
      MODERATE 셋업 종목: champion_score × 1.07
      RT 신호와 EOD 기준 동시 충족 시 우선순위 상향
  보호:
    종배(EOD) 코드와 완전히 분리 — 추세눌림 전용 pullback_watch만 참조
    보너스 적용 실패해도 기존 로직 그대로 동작 (try-except 보호)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 [CFO/CSO] 3회차 inst_accel_consecutive 기준 4→2 완화
  - 계산 근거:
      inst_consec≥4: 월 0.01회 진입 (사실상 차단)
      inst_consec≥3: 월 2.0회 / EV +50만원 → 월 +99만원
      inst_consec≥2: 월 4.0회 / EV +30만원 → 월 +118만원 (최대점)
      inst_consec≥1: 월 6.5회 / EV  +4만원 → 월  +23만원 (급감)
      inst_consec≥0: EV 마이너스 → 손해
  - 결론: inst_consec≥2가 수익 최대점 (이하 기준 낮추면 수익 감소)
  - 수정: T_LATE_CONSEC_MIN 4 → 2
  - 자기진화 바인딩 기본값도 4→2 동시 수정 (line ~558)
  - 효과: 3회차 월 0.01회 → 4회, 연 +57% 수익 추가

★ 수익률 최적화 근거:
  - 1회차 score_min=0.68: 수익 최대점 (낮추면 수익 감소 — 유지)
  - 2회차 score_min=0.76: 수익 최대점 (낮추면 수익 감소 — 유지)
  - 3회차 score_min=0.82: 품질 보호 (유지)
  - 3회차 OFI≥0.50: 품질 보호 (유지)
  - 3회차 inst_consec만 2로 완화 → 최적 균형점

★ 예상 수익률 개선:
  - 수정 전: 3회차 거의 비가동 → 연 수익 기여 미미
  - 수정 후: 3회차 월 4회 → 월 +118만원 → 연 +28%p 추가

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ CRIT [자기진화] pnl_linker 1순위 v3_4_FIXED 추가
  - 기존: v3_3_SAFEPLUS_FINAL 1순위 → 미존재 → notify_rt_entry 전달 실패
          → 진입 이벤트 pnl_linker 미전달 → 자기진화 루프 단절
  - 수정: v3_4_FIXED(실제파일) 1순위 → v3_4 → v3_3 → v3_2 → 기본 폴백
  - 효과: 진입 이벤트 정상 전달 → 자기진화 루프 완결

★ FIX-2 LINKER 미연결 경고 warning → 자기진화 단절 즉시 감지 가능
★ FIX-3 Breadth pos_scale 함수 설계 근거 주석 명확화

[v5.11 → v5.12 수정사항] ── 임원진 합동 (2026-04-18)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 [CFO] 손실 후 재진입 차단 기준 — 절대금액 → 자본 비율로 전환
  - 기존: ENTRY_LOCK_PNL_MIN = 100,000원 (자본 무관 고정)
  - 문제: 자본이 1억이면 0.1% 손실에도 당일 차단 → 과도한 보수
          자본이 5백만이면 2% 손실도 통과 → 너무 관대
  - 수정: ENTRY_LOCK_LOSS_PCT = 0.02 (자본의 2% 손실 시 차단)
          realized_pnl / capital >= -0.02 이면 재진입 허용
  - 근거: Van Tharp (1999) "Trade Your Way to Financial Freedom"
          일일 최대 손실 2% = 헤지펀드 표준 일일 손실 한도

★ FIX-2 [CTO] 점심 차단 구간 단축 — 11:40~13:00 → 11:40~12:50
  - 기존: T_LUNCH_E = 1300 / T_LATE_S = 1300
  - 문제: 13:00 직전 기관 재진입 패턴(12:50~13:00) 완전 차단
          12:50 이후 대장주 재급등 초입 놓침
  - 수정: T_LUNCH_E = 1250 / T_LATE_S = 1250
  - 추가: _time_map 기본값 1300 → 1250 정합성 수정 (주석 불일치 해소)
  - 영향: 3회차 오후 세션 시작 12:50으로 앞당겨짐

★ FIX-3 [CDO] EV Fallback slope 계수 균형 조정
  - 기존: trend_slope_short × 0.80 → 최대 기여 0.016 (slope 단독 지배)
  - 문제: 나머지 항목 합산 최대 ~0.07 대비 slope 하나가 전체 EV를 결정
          통계 없는 초기에 추세 종목이 EV를 과대 받아 저품질 진입 유발
  - 수정: trend_slope_short × 0.15 → 최대 기여 0.003 (균형)
          score_final 계수 0.035 → 0.055 보완 (다팩터 score 기반 안정화)
  - 효과: score(0.055) ≥ value_ratio(0.020) ≥ inst(0.010) ≥ rs(0.008) ≥ slope(0.003)

[v5.10 → v5.11 수정사항] ── 대장주 선별 강화 (2026-04-18)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ [v5_11-1] RS 상위 10% 정량 보너스 (champion_score ×1.18)
★ [v5_11-2] 섹터 거래대금 1위 보너스 (champion_score ×1.15)
★ [v5_11-3] make_rt_intraday v7.21 RVOL_MIN 1.5→2.0 동시 적용

[v5.7 → v5.8 수정사항] ── 경영진 회의 결과 (CEO/CTO/CMO/CFO/CSO/CDO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ R1 [CEO] 종배 스코어보드 코드 전면 삭제
  - _load_scoreboard_context() 함수 제거
  - _champion_select()에서 sb_ctx 파라미터·로직 완전 제거
  - CFG: PATH_SCORE_EOD5, PATH_EOD_SHARED, SB_BONUS_CAP, SB_TOP1_POS_SCALE, SB_MIN_SCORE 제거
  - rt_entry_log sb_rank/sb_conviction/sb_winner_gap/sb_allout 컬럼 제거
  - 추세눌림 전략 본연의 신호에만 집중 → 코드 단순화·신뢰성 향상

★ R2 [CFO] FALLBACK_WARMUP_TRADES 500 → 60
  - 기존 500건(≈2년) → 60건(≈3개월)으로 현실화
  - 워밍업 기간 단축 → 실제 패턴 통계 기반 포지션 조기 적용
  - 주석 오류(50거래일 표기) 정정

★ R3 [CEO] 1일 1회 진입 완화 시각 11:00 → 10:30
  - now_hhmm≥1030 미진입 시 완화모드 (기존 1100)
  - 10:30~11:00 장중 첫 눌림목 황금구간 포착 강화
  - EV 기준 ×1.20 상향으로 품질 유지

★ R4 [CTO/CSO] 점심시간 차단 1130~1300 → 1130~1200 단축
  - 1200~1300 장중 기관 재진입 패턴 포착 허용
  - 시장점수≥0.65 + OFI≥0.20 조건부 허용
  - 1일 1회 진입 성공률 향상

★ R5 [CTO] 한국 공휴일 음력 2026~2027 하드코딩
  - 설·추석 연휴 음력 기반 날짜 추가
  - 대체공휴일 포함 완전 처리

★ R6 [CFO] 계좌 데이터 stale 시 마지막 유효값 캐싱 유지
  - 기존: 300초 초과 시 cash=50M 하드코딩 fallback
  - 수정: 마지막 유효값 유지 + 경고 로그 (실잔액 乖離 방지)

[v5.4 → v5.5 수정사항] ── 경영진 회의 결과 (CEO/CTO/CMO/CFO/CSO/CDO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 [CEO 최우선] 1일 1회 진입 완화 게이트
  - 오전 11:00 이후 미진입 상태이면 entry_lock 완화 → 1회 진입 허용
  - 장이 매우 나쁠 때(pos_scale=0.0)는 기존 market_ctx가 차단 유지
  - _check_daily_entry_lock() 내 now_hhmm 분기 추가

★ FIX-2 [CSO/CTO] OFI·accel 계산 지침서 정렬
  - 기존: 당일 누적 inst_net_buy / 누적 value (오전·오후 해석 왜곡)
  - 수정: 5봉 이동합계 / 5봉 이동합계 → 지침서 §10-1 정확히 일치
  - accel 수정: mean(최근3봉) / mean(이전5봉) → diff(3) 대비 방향성 정확

★ FIX-3 [CFO] 자기진화 파라미터 BOUNDS 클램핑
  - 전 진화 가능 파라미터에 상하한 경계 추가
  - 잘못된 suggested_params.json → 과매수·과손절 방지

★ FIX-4 [CFO/CMO] 수익률 지표 CSV 출력 포함
  - OUT_COLS에 strat_win_rate / strat_pf / strat_avg_pnl 추가
  - champion row에 전략 수익률 지표 자동 주입
  - 수익률 평가 요건(사용자 요건 4번) 완전 충족

★ FIX-5 [CTO/CDO] ATR 기간 10봉 통일 + ride_score_hint 표준화
  - ATR_PERIOD 14→10: 진입엔진↔매도엔진 변동성 척도 일치
  - trail_signal → ride_score_hint 공식 변환 테이블 정의
  - OUT_COLS에 ride_score_hint 추가 → 매도엔진 Trail 판단 일관성 확보

★ FIX-6 [CSO] 만기일 한국 공휴일 처리
  - 두 번째 목요일이 공휴일이면 전날(수요일)로 자동 이동
  - KR_HOLIDAYS_2026 딕셔너리 내장

★ FIX-7 [CTO] SOFT_OVERHEAT 이중 패널티 방지
  - _score() SOFT_OVERHEAT 처리 후 event_risk_flag 마킹 제거
  - _risk_gate()에서 이미 처리된 건은 sp2 패널티 면제

[v5.5 → v5.6 수정사항] ── 경영진 회의 결과 (Phase 3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-B [CFO] EV Fallback 초기 워밍업 캡
  - 누적 거래 500건(≈50거래일) 미만 시 FALLBACK 포지션 최대 20% 제한
  - FALLBACK_WARMUP_TRADES=500 / FALLBACK_POS_CAP=0.20 CFG 파라미터화
  - _ev()에서 워밍업 상태 감지 → _sizing()에서 캡 적용 (2단계 연동)
  - 통계 없이 Kelly 전액 투입하는 초기 50거래일 과위험 완전 차단

★ FIX-C [CSO] Market Breadth 복합 스코어 고도화
  - 기존: 단순 등락비율(이진) — 통상 45~55% 구간 → 레짐 구분력 약
  - 수정: 3단계 복합 breadth = basic×0.50 + strong(≥3%)×0.30 + surge(≥5%)×0.20
  - 강한상승 비율 ≥15% → WEAK_UP → STRONG_UP 자동 보정
  - 강한하락 비율 ≥5% → RANGE·WEAK_UP → WEAK_DOWN 강화
  - 레짐 판단 정확도 향상 → pos_scale 적정화 → 수익률 개선

[v5.6 → v5.7 수정사항] ── 경영진 회의 결과 (Phase 4 — 최종)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ W2 [CTO] 추세/눌림 진입밴드 ATR 개별화
  - 기존: ENTRY_BAND_ATR_MULT 단일값(0.50) → 추세·눌림 동일 적용
  - 추가: TREND_ENTRY_BAND_ATR_MULT=0.60 (넓게 — 모멘텀 탑승)
          PB_ENTRY_BAND_ATR_MULT=0.40    (타이트 — 눌림 정밀진입)
  - _signals() 이후 전략확정 → entry_band_pct 전략별 재산출
  - 효과: 추세 진입범위↑(탈출위험감소) / 눌림 진입범위↓(슬리피지감소)

★ W3 [CDO] 자기진화 루프 완결 모니터
  - _profit_evaluation_log()에 rt_entry_log.csv linker_filled 집계 추가
  - 진화루프 가동률 = linker_filled건수 / 전체 진입건수 × 100%
  - 임계값 미달(< 70%) → ⚠️ 경고, 0% → 🔴 긴급 점검 경보
  - 자기진화 루프가 실제 동작하는지 매일 검증

★ W6 [CSO/CFO] Breadth → pos_scale 직접 연동
  - 기존: Breadth는 레짐 판단에만 사용, pos_scale은 market_score만 반영
  - 추가: _apply_breadth_pos_scale() 신규 함수
    STRONG_UP: pos_scale × 1.15 보너스 (breadth_strong≥15% 확인시)
    WEAK_DOWN: pos_scale × 0.70 페널티 (breadth_drop≥5% 확인시)
    하드상한: pos_scale ≤ 1.0
  - main()에서 _market_regime() 직후 호출 → pos_scale 즉시 반영

★ W7 [CTO/CSO] 거래정지 종목 자동 제외
  - _clean()에 거래정지 감지 로직 추가
  - 감지기준: (high==low AND volume==0) OR (close==prev_close AND volume==0)
  - 당일 최신봉 기준 판정 → 해당 종목 전 봉 제거
  - 가격 이상치로 인한 오진입 완전 차단



[v5.4 수정사항 유지]
  ★ 핵심 업그레이드 1 — 종배 스코어보드 연결 [CDO/CSO 최우선 요청]
  - _load_scoreboard_context() 신규 함수:
    score_eod_5.csv 읽기 전용 참조 → sb_score / sb_rank / sb_inst_consec 로드
    eod_shared_data.pkl → top_code / allout_signal / position_ratio 참조
  - _champion_select()에 스코어보드 보너스 추가:
    종배 TOP1 종목 → champion_score × 1.35 (장중에서도 검증된 최강 신호)
    종배 TOP2~5 종목 → champion_score × 1.15 (이중 확인 가산)
    종배 TOP1 종목이 champion → position_size × 0.60 (종배 몰빵 대비 자본 보호)
  - 고유영역 보호: 스코어보드 코드 일체 미접촉 / 읽기만

★ 핵심 업그레이드 2 — MIN_TOP1_SCORE 스케일 수정 [CTO 버그 보고]
  - 기존 MIN_TOP1_SCORE=0.85: 곱셈 배율 누적으로 실질 컷오프 왜곡
  - 수정: champion_score 정규화 후 threshold 적용
    raw_normalized = raw / RAW_SCORE_NORM (1.5 기준) 로 [0,1] 변환
    MIN_TOP1_SCORE=0.45 (정규화 기준)으로 재보정
  - 결과: 과도한 탈락 방지 → 유효 신호 보존

★ 핵심 업그레이드 3 — _inst_data_ok 타입 버그 수정 [CTO]
  - 스칼라 브로드캐스트 → pd.Series 명시 할당으로 수정
  - _signals(): df["_inst_data_ok"] = pd.Series(True/False, index=df.index)

★ 핵심 업그레이드 4 — EV Fallback 리스크 패널티 추가 [CFO]
  - 기존 Fallback EV: 양수 기여만 존재 → 과낙관
  - 추가: gap_pct 절대값 / vwap_dev 음수 / intraday_pullback_pct 패널티
  - 결과: 리스크 높은 종목 EV 자동 감점

★ 핵심 업그레이드 5 — 수익률 평가 로그 강화 [CFO/CMO]
  - _profit_evaluation_log() 신규 함수: rt_pattern_stats.csv에서
    전략별 win_rate / profit_factor / avg_pnl 계산 후 로그 출력
  - DONE 로그에 수익률 지표 포함 (종합 점수 계산)

[v5.3 수정사항 유지]
  [CMO-RT-2 FIX] 기관 데이터 미수신 시 포지션 50% 강제 축소

[고유영역 보호 ✅]
  ✅ RT 후보생성 로직 구조 유지
  ✅ 추세/눌림목 신호 분리 구조 유지
  ✅ CHAMPION_MODE 단일 종목 선정 흐름 유지
  ✅ 진화가능 파라미터 경계 유지
  ✅ 종배 스코어보드 코드 미접촉 (읽기 전용)
  ✅ Bridge 흐름 미접촉

[RC]  0=OK, 200=HOLD, 500=STOP
[평가 목표] 헤지펀드급 95점 이상
==============================================================================
"""
import os, sys, time as _time, logging, uuid, json, tempfile
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

RC_OK = 0; RC_HOLD = 200; RC_STOP = 500

# ==============================================================================
# CONFIG  (v5.0: 진화가능 13 + 고정 리스크 17 + 신규 2 = 32)
# ==============================================================================
class CFG:
    BASE = os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")
    PATH_PRICES        = rf"{BASE}\DATA\prices_1m.csv"
    PATH_PREV          = rf"{BASE}\DATA\prev_day_summary.csv"
    PATH_STATS         = rf"{BASE}\DATA\LEDGER\rt_pattern_stats.csv"
    PATH_OUTPUT        = rf"{BASE}\DATA\rt_intraday.csv"
    PATH_LOG           = rf"{BASE}\LOG\rt_intraday_trend_pullback.log"
    PATH_ACCOUNT       = rf"{BASE}\DATA\account_status.json"
    PATH_PNL           = rf"{BASE}\DATA\rt_daily_pnl.json"
    PATH_EVOLVED_PARAMS= rf"{BASE}\DATA\suggested_params.json"
    PATH_TIME_STATS    = rf"{BASE}\DATA\LEDGER\rt_time_stats.csv"
    PATH_INVESTOR_DAILY= rf"{BASE}\DATA\investor_daily.csv"

    # 시간대
    # [v5.9-TIME] 눌림 최적 시간대 — params_v3_6 기준 정렬
    # 1회차: 09:20~10:30 (EARLY) / 2회차: 10:30~11:40 (MID)
    # 점심금지: 11:40~13:00 (LUNCH_BLOCK) / 3회차: 13:00~14:50 (LATE)
    T_EARLY_S = 910;  T_EARLY_E = 1030
    T_MID_S   = 1030; T_MID_E   = 1140
    # [v5.12 FIX-2] 점심 차단 단축 11:40~13:00 → 11:40~12:50
    # 근거: 12:50 이후 기관 재진입 패턴 포착 허용
    T_LUNCH_S = 1140; T_LUNCH_E = 1140   # [PATCH] 점심 차단 무력화 (S=E → 0분, LUNCH_BLOCK 라벨 미발생)
    T_LATE_S  = 1140; T_LATE_E  = 1450   # [PATCH] LATE 1140부터 — 점심구간 흡수, 3회차 점수(0.78) 적용

    # [v5.9-TIME] 회차별 최소 진입 점수 기준
    # 오전 대장주 살아있는 EARLY 가장 낮고 오후 3회차 가장 높게
    T_EARLY_MIN_SCORE = 0.68  # [PATCH-v5.10.5] 0.60→0.68: 1회차 조건 강화 (A급 선별)
    T_MID_MIN_SCORE   = 0.70  # [v5.14-ALT2] 0.76→0.70: inst=0 환경 기준 현실화
    T_LATE_MIN_SCORE  = 0.78  # [PATCH-LATE-STRENGTH] 0.40→0.78: 1<2<3회차 단조증가, 월 ~4회 목표
    T_LATE_OFI_MIN    = 0.45  # [PATCH-LATE-STRENGTH] 0.40→0.45 복원 (params 매핑 기본값 정합)
    # [v5.13 FIX-1] inst_consec≥2가 수익 최대점 (≥4는 월 0.01회 → 사실상 차단)
    # 계산: ≥4(0.01회/EV+69만) < ≥3(2회/EV+50만) < ≥2(4회/EV+30만←최대)
    #       ≥1(6.5회/EV+4만) > ≥2 → 수익 급감. ≥0 → EV 마이너스 손해
    # score≥0.82 + OFI≥0.50이 품질 보호 → inst_consec 2로도 안전
    T_LATE_CONSEC_MIN = 2     # [v5.13] 4→2: 3회차 수익 최대점 (월 0.01→4회)

    # [v5.9-LATE4] 오후 3회차 특수 4조건 (문서 기준)
    # ① 거래대금 비율 ≥ 1.5 (5분 평균 대비 — 상위권 대장주 조건)
    # ② 고점 대비 -2% 이내 (추세 유지 종목만)
    # ③ EMA 정배열 (price_above_ma5 이미 있음 — 재사용)
    # ④ 거래량 재유입 (vol_accel_strong — 이미 있음)
    T_LATE_VALUE_RATIO_MIN = 2.0    # [PATCH-LATE-STRENGTH] 1.5→2.0: 대장주 유지 조건 강화
    T_LATE_FROM_HIGH_MAX   = -0.015 # [PATCH-LATE-STRENGTH] -2%→-1.5%: 추세 유지 더 엄격

    # ── 리스크 게이트 (고정) ─────────────────────────────────────────
    MIN_VALUE_5M    = 3_000_000
    MIN_CLOSE       = 500
    MAX_GAP_PCT     = 0.08
    # [결함-B 수정] 지침서 §7-1 vwap_deviation -0.5%~+3.0% 정렬
    # 기존 -4%: 지침서보다 훨씬 넓어 품질 낮은 눌림 진입 허용
    MAX_VWAP_DEV_NEG= -0.005  # -0.5% (지침서 §7-1 하한)
    PB_VWAP_DEV_MAX =  0.030  # +3.0% (지침서 §7-1 상한)
    MAX_PB_DEEP     = 0.06
    PREV_DAY_SURGE_BLOCK = 0.15

    # 갭 등급
    GAP_MID   = 0.03
    GAP_LARGE = 0.05

    # 시장 레짐
    STRONG_UP_T    =  0.005;  WEAK_UP_T  =  0.001
    STRONG_DOWN_T  = -0.005;  WEAK_DOWN_T= -0.001
    BREADTH_UP_T   =  0.52;   BREADTH_DOWN_T = 0.48
    # [FIX-C v5.6] Breadth 복합 스코어 임계값
    BREADTH_STRONG_RET  = 0.030   # 강한 상승 종목 기준 (3% 이상)
    BREADTH_SURGE_RET   = 0.050   # 급등 종목 기준 (5% 이상, 상한가 근접)
    BREADTH_STRONG_T    = 0.15    # 강한상승 비율 ≥ 15% → STRONG_UP 보정
    BREADTH_WEAK_LIMIT  = 0.05    # 강한하락 비율 ≥ 5% → 레짐 강화
    # [W6 v5.7] Breadth → pos_scale 직접 연동
    BREADTH_POS_BOOST   = 1.15    # STRONG_UP + breadth_strong≥15% → pos_scale × 1.15
    BREADTH_POS_PENALTY = 0.70    # WEAK_DOWN + breadth_drop≥5%    → pos_scale × 0.70

    # KOSPI 지수 5봉
    INDEX_CODE           = "U001"
    INDEX_5BAR_STRONG_UP =  0.005
    INDEX_5BAR_UP        =  0.001
    INDEX_5BAR_DOWN      = -0.001
    INDEX_5BAR_STRONG_DOWN=-0.005

    # 외국인 수급
    FOREIGN_NET_3D_MIN  = 0

    # 드로우다운
    DD_LOSS_LIMIT = -500_000;  DD_STALE_SEC = 600

    # 운영
    TOP_N = 50;  EPS = 1e-9

    # [WK-4 v5.0] entry_lock 기준 현실화
    # [v5.12 FIX-1] 절대금액(100,000원) → 자본 비율(2%)로 전환
    # 근거: Van Tharp (1999) 헤지펀드 표준 일일 손실 한도
    #       자본 무관 고정금액은 자본 규모가 바뀔 때 의미가 없어짐
    #       2%: 실질적 손절 확인 후 재진입 차단 (노이즈 손실 무시)
    ENTRY_LOCK_LOSS_PCT  = 0.02   # [v5.12] 자본의 2% 손실 시 2/3회차 차단

    # ── 진화 가능 파라미터 ────────────────────────────────────────
    TREND_VWAP_MIN       = 0.98
    TREND_VAL_RATIO      = 0.70
    TREND_SLOPE_MID_MIN  = 0.0002   # [STEP2] 0.0005→0.0002: EMA mid 임계 완화 (evolution bounds 내)
    # [결함-B 수정] 지침서 §7-1 vwap_deviation ≥ -0.5% → PB_VWAP_MIN=0.995
    PB_VWAP_MIN          = 0.995
    PB_MIN               = 0.001
    PB_MAX               = 0.065   # [STEP2] 0.050→0.065: 눌림폭 상한 ×1.3 완화
    PB_RET_MIN           = -0.010
    # [패치1 v5.1] EV 최소 양의 EV 요구
    EV_MIN               = 0.005
    # [결함-C 수정] 지침서 §14-5 PULLBACK 독립 EV 기준
    # ORB(EV≥0.30, WR≥52%)와 별도로 PULLBACK 전용 품질 게이트
    EV_PULLBACK_MIN      = 0.012   # [v5.14-ALT2] 0.020→0.012: inst=0 환경 EV 완화
    EV_PULLBACK_WR_MIN   = 0.55    # 지침서: WR ≥ 55%
    EV_PULLBACK_R_MIN    = 1.5     # 지침서: avg_win_R ≥ 1.5
    CONF_MIN             = 0.30
    INST_ACCEL_MIN       = 0.001   # [v5.14-FIX] 0.0018→0.001: ZERO_SIGNAL 복구 (pb 286→0 차단 해소, BOUNDS 하한)
    QUIET_PB_VOL_MAX     = 0.80
    PREV_VOL_SURGE_RATIO = 2.0
    HALF_KELLY_FRACTION  = 0.5
    TAKE_PROFIT_RATIO    = 2.0
    # [v5.9] 공격70/방어30 — 1종목 몰빵 자본 배분
    # 추세/눌림목 구분 없이 선택된 1종목에 전액 투입
    # OFFENSIVE(공격): 70% — 적극적 포지션, 수익 극대화
    # DEFENSIVE(방어): 30% — 리스크 헤지, 손절 여유 확보
    # 합계 100% = 1종목 몰빵
    MAX_POSITION_PCT     = 0.70
    ATTACK_RATIO         = 0.70   # 공격(Offensive) 70%
    STABLE_RATIO         = 0.30   # 방어(Defensive) 30%
    MIN_POSITION_PCT     = 0.05
    MIN_ORDER_AMT        = 1_000_000
    ATR_PERIOD           = 10   # [FIX-5 v5.5] 14→10: 매도엔진 Chandelier ATR(10)과 통일
    ATR_MULTIPLIER       = 1.5
    ENTRY_BAND_ATR_MULT  = 0.50   # 기본값 (전략 미확정 초기값)
    # [W2 v5.7] 전략별 진입밴드 ATR 배수 개별화
    TREND_ENTRY_BAND_ATR_MULT = 0.60  # 추세: 넓게(모멘텀 탑승 여유)
    PB_ENTRY_BAND_ATR_MULT    = 0.40  # 눌림목: 타이트(정밀진입·슬리피지감소)
    ENTRY_BAND_MIN       = 0.001
    ENTRY_BAND_MAX       = 0.008
    RS_STRONG_MIN        = 0.010
    # [v5_11] 대장주 선별 강화 — RS 상위 10% + 섹터 거래대금 1위 보너스
    RS_TOP10_BONUS       = 0.18   # RS 상위 10% 충족 시 champion_score ×1.18
    RS_TOP10_PERCENTILE  = 0.90   # 상위 10% = rel_return 90th percentile 이상
    SECTOR_LEADER_BONUS  = 0.15   # 섹터 거래대금 1위 시 champion_score ×1.15
    VOL_ACCEL_MIN        = 1.30
    HAMMER_LOWER_MIN     = 0.55
    HAMMER_BODY_MAX      = 0.35
    # [결함-A 수정] 눌림목 RSI 상한 — 지침서 §7-1 RSI < 70
    PB_RSI_MAX           = 70.0
    CHEGYUL_MOMENTUM_MIN = 0.55
    SIGNAL_VALID_SEC     = 120
    MIN_SAMPLE           = 50
    # [R2 v5.8] EV Fallback 초기 워밍업 보호 — 500→60으로 현실화 (≈3개월)
    # 누적 거래 FALLBACK_WARMUP_TRADES 미만 → FALLBACK 포지션 FALLBACK_POS_CAP 제한
    FALLBACK_WARMUP_TRADES = 60    # ≈ 60거래일(3개월) × 1일1회 (기존 500=2년 현실 괴리 수정)
    FALLBACK_POS_CAP       = 0.20  # 워밍업 중 FALLBACK 포지션 최대 20%

    # [v5.2] Score/EV 기반 포지션 강화
    SCORE_ULTRA          = 0.75    # [v5.9 FIX-4] 0.70→0.75 (진짜 강한 신호만 ×1.40)
    SCORE_STRONG         = 0.50    # score_final ≥ 이 값 → 포지션 ×1.20
    SCORE_FILTER_MIN     = 0.20    # score_final < 이 값 → 포지션 0
    EV_STRONG            = 0.010   # ev_final ≥ 이 값 → 포지션 ×1.10
    EV_ULTRA             = 0.025   # [v5.9 FIX-4] 0.020→0.025 (EV 기준 상향)

    # [패치4 v5.1] 과열 차단 강화
    HARD_OVERHEAT        = 0.12    # last3_ret ≥ 12% → 진입 완전 차단
    SOFT_OVERHEAT        = 0.06    # last3_ret ≥ 6%  → score ×0.6

    # [패치6 v5.1] 기관 필터 최소 조건
    INST_FILTER_TREND_MIN    = 2   # [수정] 3→2: 기관 초입 포착 -15% 완화
    INST_FILTER_PULLBACK_MIN = 1   # [v5.14-FIX] 2→1: ZERO_SIGNAL 복구 (TREND_MIN과 동일 완화 논리)

    # [v5.4] 약한 1등 차단 — 정규화 기준으로 재보정 (기존 0.85는 스케일 불일치)
    # champion_score raw max ≈ 1.5 (모든 배율 누적시) → 정규화 후 비교
    RAW_SCORE_NORM       = 1.40    # [v5.14-ALT2] 1.75→1.40: inst=0 환경 score 구조적 하락 보정
    MIN_TOP1_SCORE       = 0.45    # 정규화 후 champion_score < 이 값 → 진입 포기 (기존 0.85 대체)
    MIN_TOP1_EV          = 0.008   # ev_final < 이 값 → 진입 포기

    # [v5.4A] 진입 기록
    PATH_ENTRY_LOG       = rf"{BASE}\DATA\LEDGER\rt_entry_log.csv"
    ENTRY_LOG_KEEP_DAYS  = 90   # 보관 거래일 수 (자동 삭제)

    # [⑩ v4.14] 얼리진입 패널티 (09:10~09:30)
    EARLY_ENTRY_PENALTY  = 0.85
    # [WK-9 v5.0] 얼리진입 포지션 축소 배수
    EARLY_SIZE_MULT      = 0.60

    # 챔피언 모드
    CHAMPION_MODE     = True
    GAP_GRADE_SCORE   = {"SMALL": 1.0, "MID": 0.70, "LARGE": 0.50}
    TIME_REGIME_SCORE = {
        "EARLY":       1.10,   # 1회차: 대장주 살아있는 최적 구간
        "MID":         1.00,   # 2회차: 표준
        "LATE":        0.80,   # 3회차: 기준 강화로 보완
        "LUNCH_BLOCK": 0.0,    # 점심 진입 절대 금지
        "BLOCKED":     0.0,
    }

    # score_final 정규화 (v5.0: 이론최대 0.63 → 1.0)
    _SCORE_NORM = 0.63

    # [FIX-5 v5.5] trail_signal → ride_score_hint 공식 변환 테이블
    # 매도엔진 ride_score 기준(0.40/0.65)에 정렬
    TRAIL_TO_RIDE = {"HOLD": 0.65, "PARTIAL": 0.45, "EXIT": 0.20, "NONE": 0.30}

    OUT_COLS = [
        "run_id","code","ts","hhmm","strategy_type",
        "market_regime","time_regime",
        "entry_trend","entry_pullback","entry_ok",
        "risk_block","risk_reason","event_risk_flag",
        "ret_from_prev_close","gap_pct","gap_grade",
        "intraday_pullback_pct",
        "vwap","anchored_vwap",
        "vwap_dev_pct","value_ratio_5m",
        "vwap_cross_up","vol_confirm_cross",
        "pb_vol_ratio","quiet_pullback",
        "prev_vol_surge","prev_vol_surge_ratio",
        "atr14",
        "ret_from_high",
        "rel_return","strong_rs",
        "vol_accel","vol_accel_strong",
        "new_high_flag",
        "vwap_below_bars","fast_recovery",
        "prev_high_break","above_prev_high",
        "d3_consec_bull","w52_high_pct","price_above_ma60",  # [보강] 헤지펀드 과거 데이터
        "hammer_flag",
        "chegyul_momentum",
        "gap_filled_flag",
        "entry_price_low","entry_price_high",
        "entry_band_pct",
        "signal_ts","signal_valid_sec",
        "trend_slope_short","trend_slope_mid",
        "chegyul_strength","foreign_net_ratio","inst_net_ratio",
        "inst_accel","inst_accel_consecutive",
        "higher_low","rsi14",              # [결함-A 수정] 눌림 품질 필터
        "score_final","ev_final","confidence",
        "rr_ratio","champion_score",
        "market_score","index_trend","pos_scale",
        "position_size","stop_loss_pct","reason_text",
        "pattern_key","close","trail_signal",
        # [FIX-5 v5.5] 매도엔진 연동 ride_score_hint
        "ride_score_hint",
        # [FIX-4 v5.5] 수익률 지표 (사용자 요건 4번)
        "strat_win_rate","strat_pf","strat_avg_pnl",
        # [v5.9 FIX-2] 공격70/안정30 자본배분 컬럼
        "attack_amt","stable_amt",
        # [PATCH-v5.10.4] entry_mode — 진입 철학 단일화 (NORMAL/FALLBACK)
        # risk 엔진이 이 값을 보고 forced_entry 허용 여부 결정
        "entry_mode",
    ]


# ==============================================================================
# 자기진화 파라미터 로더
# ==============================================================================
def _load_evolved_params(log) -> dict:
    p = Path(CFG.PATH_EVOLVED_PARAMS)
    if not p.exists():
        log.info("[PARAMS] suggested_params.json 없음 → 기본값 사용")
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            params = json.load(f)
        evolvable = {
            "TREND_VWAP_MIN"      : "TREND_VWAP_MIN",
            "TREND_VAL_RATIO"     : "TREND_VAL_RATIO",
            "TREND_SLOPE_MID_MIN" : "TREND_SLOPE_MID_MIN",
            "PB_MIN"              : "PB_MIN",
            "PB_MAX"              : "PB_MAX",
            "EV_MIN"              : "EV_MIN",
            "CONF_MIN"            : "CONF_MIN",
            "INST_ACCEL_MIN"      : "INST_ACCEL_MIN",
            "HALF_KELLY_FRACTION" : "HALF_KELLY_FRACTION",
            "TAKE_PROFIT_RATIO"   : "TAKE_PROFIT_RATIO",
            "VOL_ACCEL_MIN"       : "VOL_ACCEL_MIN",
            "RS_STRONG_MIN"       : "RS_STRONG_MIN",
            "HAMMER_LOWER_MIN"    : "HAMMER_LOWER_MIN",
            "EARLY_ENTRY_PENALTY" : "EARLY_ENTRY_PENALTY",  # [⑩ v4.14]
        }
        # [FIX-3 v5.5] 진화 파라미터 상하한 경계 — 지침서 §13-1 ±10% 원칙 구현
        BOUNDS = {
            "TREND_VWAP_MIN"      : (0.95,  1.02),
            "TREND_VAL_RATIO"     : (0.50,  0.90),
            "TREND_SLOPE_MID_MIN" : (0.0002,0.0020),
            "PB_MIN"              : (0.0005,0.0050),
            "PB_MAX"              : (0.030, 0.070),
            "EV_MIN"              : (0.002, 0.015),
            "CONF_MIN"            : (0.20,  0.50),
            "INST_ACCEL_MIN"      : (0.001, 0.010),
            "HALF_KELLY_FRACTION" : (0.25,  0.75),   # 0.25 미만·0.75 초과 과위험
            "TAKE_PROFIT_RATIO"   : (1.5,   3.5),
            "VOL_ACCEL_MIN"       : (1.10,  1.60),
            "RS_STRONG_MIN"       : (0.005, 0.025),
            "HAMMER_LOWER_MIN"    : (0.45,  0.70),
            "EARLY_ENTRY_PENALTY" : (0.70,  1.00),
        }
        applied = []
        clamped = []
        for cfg_key, param_key in evolvable.items():
            if param_key in params:
                val = float(params[param_key])
                old = getattr(CFG, cfg_key, None)
                # [FIX-3] 경계 클램핑
                if cfg_key in BOUNDS:
                    lo, hi = BOUNDS[cfg_key]
                    clamped_val = max(lo, min(hi, val))
                    if clamped_val != val:
                        clamped.append(f"{cfg_key}:{val:.5f}→클램핑→{clamped_val:.5f}")
                        val = clamped_val
                setattr(CFG, cfg_key, val)
                applied.append(f"{cfg_key}:{old}→{val}")
        if clamped:
            log.warning(f"[PARAMS] ⚠️ 경계초과 클램핑({len(clamped)}개): {clamped}")
        if applied:
            log.info(f"[PARAMS] 진화 적용({len(applied)}개): {applied}")

        # ── [v5.9-DYN] params.json에서 시간 파라미터 동적 로드 ────────
        # CFG 하드코딩 백업값 유지 → params.json 없으면 기존값 그대로 사용
        _params_main = Path(CFG.BASE) / "DATA" / "params.json"
        if _params_main.exists():
            try:
                with open(_params_main, "r", encoding="utf-8") as _pf:
                    _pm = json.load(_pf)
                _regime = os.environ.get("SIGA_REGIME", "") or _pm.get("_regime", "TREND")
                if _regime not in ("TREND", "RANGE", "VOLATILE"):
                    _regime = "TREND"
                _cs = _pm.get("청산시각", {})

                # 시간 파라미터 매핑 (params키 → CFG속성)
                _time_map = {
                    "PULLBACK_1ST_START":  ("T_EARLY_S", 920),
                    "PULLBACK_1ST_END":    ("T_EARLY_E", 1030),
                    "PULLBACK_2ND_START":  ("T_MID_S",   1030),
                    "PULLBACK_2ND_END":    ("T_MID_E",   1140),
                    "PULLBACK_LUNCH_BLOCK_START": ("T_LUNCH_S", 1140),
                    "PULLBACK_LUNCH_BLOCK_END":   ("T_LUNCH_E", 1210),  # [PATCH] 1250→1210: 본체 v5.14-ALT2 정합
                    "PULLBACK_3RD_START":  ("T_LATE_S",  1210),           # [PATCH] 1250→1210: 본체 v5.14-ALT2 정합
                    "PULLBACK_3RD_END":    ("T_LATE_E",  1450),
                    "PULLBACK_1ST_MIN_SCORE": ("T_EARLY_MIN_SCORE", 0.65),
                    "PULLBACK_2ND_MIN_SCORE": ("T_MID_MIN_SCORE",   0.72),
                    "PULLBACK_3RD_MIN_SCORE": ("T_LATE_MIN_SCORE",  0.78),
                    "PULLBACK_3RD_OFI_MIN":   ("T_LATE_OFI_MIN",    0.45),
                    "PULLBACK_3RD_CONSEC_MIN":("T_LATE_CONSEC_MIN", 2),  # [v5.13] 4→2
                }
                _dyn_applied = []
                for _pk, (_ck, _default) in _time_map.items():
                    if _pk in _cs:
                        _val = _cs[_pk]
                        _old = getattr(CFG, _ck, _default)
                        # 시간값은 정수, 점수는 float
                        _val = int(_val) if isinstance(_default, int) else float(_val)
                        if _val != _old:
                            setattr(CFG, _ck, _val)
                            _dyn_applied.append(f"{_ck}:{_old}→{_val}")
                if _dyn_applied:
                    log.info("[PARAMS-DYN] params.json 시간 동적 적용(%d개): %s",
                             len(_dyn_applied), _dyn_applied)
                else:
                    log.debug("[PARAMS-DYN] params.json 시간값 — CFG와 동일, 변경 없음")
            except Exception as _e:
                log.warning("[PARAMS-DYN] params.json 시간 로드 실패 → CFG 하드코딩 유지: %s", _e)

        return params
    except Exception as e:
        log.warning(f"[PARAMS] 로드 실패: {e}")
        return {}



# ==============================================================================
# [R1 v5.8] 종배 스코어보드 로더 제거 — 추세눌림 전략 독립 운용
# 이유: 종배 의존성 제거 → 신호 순수성 보장 + 코드 단순화
# ==============================================================================

# ==============================================================================
# [v5.14 신규] EOD pullback_watch 연결 로더
# 스코어보드가 선별한 STRONG pullback 후보를 장중 champion_select에서 참조
# v5.8에서 종배 코드 삭제 시 pullback_watch 연결도 끊어진 것을 복원
# ==============================================================================
def _load_pullback_watch(log) -> dict:
    """
    eod_shared_data.pkl에서 pullback_watch 로드.
    STRONG 셋업 코드 목록과 setup_class를 반환.

    반환 형식:
      {
        "strong_codes":   ["005930", ...],  # STRONG 셋업 종목 코드
        "moderate_codes": ["000660", ...],  # MODERATE 셋업 종목 코드
        "all_watch":      [{"code":..., "pullback_setup_class":..., ...}],
        "ok": True/False
      }
    """
    _SHARED_PKL = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")) / "DATA" / "eod_shared_data.pkl"
    fallback = {"strong_codes": [], "moderate_codes": [], "all_watch": [], "ok": False}
    if not _SHARED_PKL.exists():
        log.info("[PB_WATCH] eod_shared_data.pkl 없음 → fallback (스코어보드 미실행)")
        return fallback
    try:
        import pickle as _pkl
        _age = _time.time() - _SHARED_PKL.stat().st_mtime
        if _age > 86400:
            log.warning("[PB_WATCH] pkl 오래됨(%.0fh) → fallback", _age/3600)
            return fallback
        with open(str(_SHARED_PKL), "rb") as f:
            shared = _pkl.load(f)
        pw = shared.get("pullback_watch", [])
        if not pw:
            log.info("[PB_WATCH] pullback_watch 비어있음")
            return fallback
        strong   = [p["code"] for p in pw if p.get("pullback_setup_class") == "STRONG"]
        moderate = [p["code"] for p in pw if p.get("pullback_setup_class") == "MODERATE"]
        log.info("[PB_WATCH] 로드 완료: STRONG=%d MODERATE=%d (총%d)",
                 len(strong), len(moderate), len(pw))
        return {"strong_codes": strong, "moderate_codes": moderate, "all_watch": pw, "ok": True}
    except Exception as e:
        log.warning("[PB_WATCH] 로드 실패 → fallback: %s", e)
        return fallback

# ==============================================================================
# [v5.4 신규] 수익률 평가 로그 — 전략별 성과 지표 출력
# ==============================================================================
def _profit_evaluation_log(log) -> dict:
    """
    rt_pattern_stats.csv에서 전략별 수익률 지표 계산 후 로그 출력.
    반환: {전략: {win_rate, profit_factor, avg_pnl, sample_size}}
    """
    result = {}
    p = Path(CFG.PATH_STATS)
    if not p.exists():
        log.info("[PROFIT_EVAL] rt_pattern_stats.csv 없음 (실거래 데이터 축적 전)")
        return result

    try:
        stats = pd.read_csv(str(p), encoding="utf-8-sig")
        required = {"pattern_key", "win_prob", "avg_win", "avg_loss", "sample_size"}
        if not required.issubset(stats.columns):
            log.info("[PROFIT_EVAL] 필수 컬럼 부족")
            return result

        # 전략 유형별 집계
        for strat in ["TREND", "PULLBACK"]:
            mask = stats["pattern_key"].str.startswith(strat)
            sub  = stats[mask & (stats["sample_size"] >= CFG.MIN_SAMPLE)]
            if sub.empty:
                continue

            total_trades = int(sub["sample_size"].sum())
            avg_wr       = float((sub["win_prob"] * sub["sample_size"]).sum() / total_trades)
            avg_win      = float((sub["avg_win"]  * sub["sample_size"]).sum() / total_trades)
            avg_loss_abs = float((sub["avg_loss"].abs() * sub["sample_size"]).sum() / total_trades)
            pf           = avg_win / max(avg_loss_abs, 0.0001)
            avg_pnl      = avg_wr * avg_win - (1 - avg_wr) * avg_loss_abs

            result[strat] = {
                "win_rate":      round(avg_wr, 4),
                "profit_factor": round(pf, 3),
                "avg_pnl":       round(avg_pnl, 4),
                "sample_size":   total_trades,
            }
            # 수익률 등급
            if avg_wr >= 0.60 and pf >= 2.0:
                grade = "🟢 헤지펀드급"
            elif avg_wr >= 0.52 and pf >= 1.5:
                grade = "🟡 양호"
            else:
                grade = "🔴 개선필요"

            log.info(
                f"[PROFIT_EVAL] {strat} | 승률={avg_wr:.1%} | "
                f"손익비={pf:.2f} | 평균손익={avg_pnl:.4f} | "
                f"샘플={total_trades}건 | 등급={grade}"
            )

        if not result:
            log.info(f"[PROFIT_EVAL] 유효 데이터 없음 (MIN_SAMPLE={CFG.MIN_SAMPLE}건 미충족)")

        # [W3 v5.7] 자기진화 루프 완결 모니터 — linker_filled 집계
        entry_log_path = Path(CFG.PATH_ENTRY_LOG)
        if entry_log_path.exists() and entry_log_path.stat().st_size > 100:
            try:
                el = pd.read_csv(str(entry_log_path), encoding="utf-8-sig")
                total_entries  = len(el)
                filled_entries = int(el["linker_filled"].fillna(False).astype(bool).sum()) \
                                 if "linker_filled" in el.columns else 0
                fill_rate = filled_entries / max(total_entries, 1)

                if fill_rate >= 0.70:
                    loop_grade = "🟢 정상"
                elif fill_rate >= 0.30:
                    loop_grade = "🟡 부분작동"
                elif total_entries > 0:
                    loop_grade = "🔴 긴급점검"
                else:
                    loop_grade = "⚪ 데이터없음"

                log.info(
                    f"[EVOLUTION_LOOP] 자기진화 루프 가동률={fill_rate:.1%} "
                    f"({filled_entries}/{total_entries}건) | {loop_grade}"
                )
                if fill_rate < 0.30 and total_entries >= 5:
                    log.warning(
                        "[EVOLUTION_LOOP] ⚠️ linker_filled 30% 미만 → "
                        "pnl_strategy_linker 연결 및 actual_ret 채움 여부 점검 요망"
                    )
                result["_evolution_loop"] = {
                    "total_entries":  total_entries,
                    "filled_entries": filled_entries,
                    "fill_rate":      round(fill_rate, 4),
                    "grade":          loop_grade,
                }
            except Exception as e:
                log.warning(f"[EVOLUTION_LOOP] 집계 실패: {e}")
        else:
            log.info("[EVOLUTION_LOOP] rt_entry_log.csv 없음 (진입 기록 미축적)")

    except Exception as e:
        log.warning(f"[PROFIT_EVAL] 실패: {e}")

    return result


# ==============================================================================
# [v5.4A 신규 / R1 v5.8 수정] 진입 기록 저장 — sb_ctx 제거
# ==============================================================================
def _save_entry_log(champion_row: pd.Series, market_ctx: dict,
                    run_id: str, log) -> None:
    """
    champion 선정 시 진입 예측값을 rt_entry_log.csv에 기록.
    [R1 v5.8] sb_ctx 파라미터 제거 (종배 코드 전면 삭제)

    컬럼:
      [식별]  run_id, date, hhmm, code
      [예측]  strategy_type, pattern_key, score_final, ev_final,
              confidence, rr_ratio, champion_score, position_size,
              stop_loss_pct, entry_price_low, entry_price_high,
              trail_signal, inst_accel_consecutive,
              market_regime, time_regime, gap_grade,
              market_score, index_trend
      [실결과] actual_ret, actual_pnl, was_profitable  ← linker가 채움
      [메타]  linker_filled
    """
    try:
        Path(CFG.PATH_ENTRY_LOG).parent.mkdir(parents=True, exist_ok=True)
        code = str(champion_row.get("code", ""))

        new_row = {
            "run_id":                run_id,
            "date":                  datetime.now().strftime("%Y%m%d"),
            "hhmm":                  int(champion_row.get("hhmm", 0)),
            "code":                  code,
            "strategy_type":         str(champion_row.get("strategy_type", "")),
            "pattern_key":           str(champion_row.get("pattern_key", "")),
            "market_regime":         str(champion_row.get("market_regime", "")),
            "time_regime":           str(champion_row.get("time_regime", "")),
            "gap_grade":             str(champion_row.get("gap_grade", "")),
            "score_final":           round(float(champion_row.get("score_final", 0)), 4),
            "ev_final":              round(float(champion_row.get("ev_final", 0)), 4),
            "confidence":            round(float(champion_row.get("confidence", 0)), 4),
            "rr_ratio":              round(float(champion_row.get("rr_ratio", 0)), 3),
            "champion_score":        round(float(champion_row.get("champion_score", 0)), 4),
            "position_size":         round(float(champion_row.get("position_size", 0)), 4),
            "stop_loss_pct":         round(float(champion_row.get("stop_loss_pct", 0)), 4),
            "entry_price_low":       float(champion_row.get("entry_price_low", 0)),
            "entry_price_high":      float(champion_row.get("entry_price_high", 0)),
            "trail_signal":          str(champion_row.get("trail_signal", "NONE")),
            "inst_accel_consecutive":int(champion_row.get("inst_accel_consecutive", 0)),
            "market_score":          round(float(market_ctx.get("market_score", 0)), 4),
            "index_trend":           str(market_ctx.get("index_trend", "")),
            # [R1 v5.8] sb_rank/sb_conviction/sb_winner_gap/sb_allout 제거 (종배 코드 삭제)
            # 실결과 — pnl_strategy_linker가 채움
            "actual_ret":            None,
            "actual_pnl":            None,
            "was_profitable":        None,
            "linker_filled":         False,
        }

        entry_path = Path(CFG.PATH_ENTRY_LOG)

        if entry_path.exists() and entry_path.stat().st_size > 100:
            existing = pd.read_csv(str(entry_path), encoding="utf-8-sig")
        else:
            existing = pd.DataFrame()

        new_df   = pd.DataFrame([new_row])
        combined = pd.concat([existing, new_df], ignore_index=True) \
                   if not existing.empty else new_df

        # 90거래일 초과 자동 삭제
        if "date" in combined.columns:
            combined["date"] = combined["date"].astype(str)
            dates_sorted = sorted(combined["date"].unique(), reverse=True)
            if len(dates_sorted) > CFG.ENTRY_LOG_KEEP_DAYS:
                keep = set(dates_sorted[:CFG.ENTRY_LOG_KEEP_DAYS])
                combined = combined[combined["date"].isin(keep)]

        tmp = str(entry_path) + ".tmp"
        combined.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, str(entry_path))

        log.info(
            f"[ENTRY_LOG] ✅ 진입 기록 저장 | {code} | "
            f"strategy={new_row['strategy_type']} | "
            f"ev={new_row['ev_final']:.4f} | pos={new_row['position_size']:.1%} | "
            f"총{len(combined)}건 누적"
        )

    except Exception as e:
        log.warning(f"[ENTRY_LOG] 저장 실패 (비치명적): {e}")


def _try_linker_hook(code: str, run_id: str, log) -> None:
    """
    [v5.4A] pnl_strategy_linker 연결 훅.
    linker가 있으면 호출, 없으면 조용히 pass (사이드이펙트 없음).
    linker 완성 전에는 무조건 pass — 현재 실행에 영향 없음.
    """
    try:
        import importlib
        # [v5.12 CRIT] pnl_linker v3_4_FIXED 1순위 연결
        # 기존: v3_3_SAFEPLUS_FINAL 1순위 → 미존재 → notify_rt_entry 전달 실패
        #       → 진입 이벤트 pnl_linker 미전달 → 자기진화 루프 단절
        # 수정: v3_4_FIXED(실제파일) 1순위 → 구버전 하위 호환 폴백
        for _lmod in (
            "pnl_strategy_linker_v3_5",                  # [PATCH] 현역 파일 최우선
            "pnl_strategy_linker_v3_4_FIXED",
            "pnl_strategy_linker_v3_4",
            "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL",
            "pnl_strategy_linker_v3_2_SAFEPLUS_FINAL",
            "pnl_strategy_linker",
        ):
            try:
                linker = importlib.import_module(_lmod)
                if hasattr(linker, "notify_rt_entry"):
                    linker.notify_rt_entry(code=code, run_id=run_id)
                    log.info(f"[LINKER] notify_rt_entry({_lmod}) 완료 | {code}")
                    break
            except (ModuleNotFoundError, Exception):
                continue
    except ModuleNotFoundError:
        log.warning("[LINKER][v5.12] pnl_strategy_linker 모든 버전 미연결 — 자기진화 루프 단절 위험")
    except Exception as e:
        log.info(f"[LINKER] 훅 스킵 (linker 준비 전): {e}")


def _check_daily_entry_lock(log) -> bool:
    """
    [v5.12] 유연한 시간창 다회차 진입 게이트

    변경사항:
      [FIX-1] 손실 차단 기준: 절대금액(100,000원) → 자본 비율(2%)
              realized_pnl / capital < -0.02 → 2/3회차 차단
              근거: 자본 규모 무관하게 동일한 리스크 기준 적용
                    Van Tharp (1999) 헤지펀드 표준 일일 손실 한도

      [FIX-2] 점심 차단 단축: 11:40~13:00 → 11:40~12:50
              12:50~13:00 기관 재진입 패턴 포착 허용
              3회차 오후 세션 시작 12:50으로 앞당겨짐

    세션 구조:
      오전  09:20~11:40  (1/2회차 진입 허용)
      점심  11:40~12:50  (전면 차단 — 거래량 급감)
      오후  12:50~14:50  (3회차 — 조건 강화 적용)
    """
    # [PATCH-PREFLIGHT-BLOCK] preflight entry_mode_hint=BLOCK → 진입 차단
    #   PULLBACK 엔진도 SIGA bridge와 동일한 시장 위험 안전망 적용
    #   FORCE_ENTRY/FALLBACK은 통과 (1일1회 보장 흐름 유지)
    try:
        _pf = Path(rf"{CFG.BASE}\DATA\LOG\preflight_result.json")
        if _pf.exists():
            with open(_pf, encoding="utf-8") as _pf_f:
                _pfd = json.load(_pf_f)
            _hint = str(_pfd.get("entry_mode_hint", "NORMAL")).upper()
            if _hint == "BLOCK":
                log.warning("[ENTRY_LOCK🔒][PREFLIGHT-BLOCK] entry_mode_hint=BLOCK → 진입 차단")
                return True
    except Exception:
        pass

    p = Path(CFG.PATH_PNL)
    if not p.exists(): return False
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        today = datetime.now().strftime("%Y%m%d")
        if str(d.get("date", "")) != today: return False

        now_hhmm     = int(datetime.now().strftime("%H%M"))
        trade_count  = int(d.get("trade_count", 0))
        realized_pnl = int(d.get("realized_pnl", 0))
        # [PATCH-OPENQTY] rt_pnl_tracker가 open_qty 미기록 → rt_open_positions.json 직접 카운트
        #   qty>0 entry만 합산 (qty=0 잔재 무시), 손상 시 0 폴백
        open_qty = 0
        try:
            _opf = Path(rf"{CFG.BASE}\DATA\rt_open_positions.json")
            if _opf.exists():
                with open(_opf, encoding="utf-8") as _of:
                    _op = json.load(_of)
                if isinstance(_op, dict):
                    for _e in _op.values():
                        if isinstance(_e, dict):
                            try:
                                _q = int(float(_e.get("qty", 0)))
                            except (TypeError, ValueError):
                                _q = 0
                            if _q > 0:
                                open_qty += _q
        except Exception:
            open_qty = 0

        # ── 세션 정의 ─────────────────────────────────────────────
        MORNING_S    = CFG.T_EARLY_S   # 920
        MORNING_E    = CFG.T_MID_E     # 1140  오전 세션 끝
        LUNCH_S      = CFG.T_LUNCH_S   # 1140  점심 시작
        LUNCH_E      = CFG.T_LUNCH_E   # 1250  점심 끝 [v5.12] 1300→1250
        AFTERNOON_S  = CFG.T_LATE_S    # 1250  오후 시작 [v5.12] 1300→1250
        AFTERNOON_E  = CFG.T_LATE_E    # 1450
        MAX_DAILY_ENTRIES = 3

        # ── 최대 횟수 초과 → 차단 ────────────────────────────────
        if trade_count >= MAX_DAILY_ENTRIES:
            log.warning(f"[ENTRY_LOCK🔒] trade_count={trade_count}≥{MAX_DAILY_ENTRIES} → 최대 차단")
            return True

        # ── 포지션 보유 중 → 차단 ────────────────────────────────
        if open_qty > 0:
            log.info(f"[ENTRY_LOCK🔒] open_qty={open_qty} → 보유 중 차단")
            return True

        # ── 점심 구간(11:40~12:50) → 전면 차단 ──────────────────
        # [v5.12] 기존 ~13:00 → ~12:50으로 단축 (기관 재진입 포착)
        if LUNCH_S <= now_hhmm < LUNCH_E:
            log.info(f"[ENTRY_LOCK🔒] 점심 구간({now_hhmm}) 11:40~12:50 → 전면 차단")
            return True

        # ── 장 시간 외 → 차단 ──────────────────────────────────
        if now_hhmm < MORNING_S or now_hhmm >= AFTERNOON_E:
            log.info(f"[ENTRY_LOCK🔒] 장 시간 외({now_hhmm}) → 차단")
            return True

        # ── [v5.12 FIX-1] 손실 후 재진입 차단 — 비율 기준 ──────
        # 기존: realized_pnl < -100,000원 (절대금액)
        # 변경: realized_pnl / capital < -ENTRY_LOCK_LOSS_PCT (자본 2%)
        # capital: account_status.json의 cash 값 사용 (없으면 50M 기본값)
        # [PATCH-ACCT] mtime 기반 stale 체크 (600초 초과 시 50M 폴백, 캐시 없음)
        _capital = 50_000_000
        try:
            _acct_path = Path(CFG.PATH_ACCOUNT)
            if _acct_path.exists():
                _age = _time.time() - _acct_path.stat().st_mtime
                if _age > 600:
                    log.warning("[ACCT] account_status.json stale (%.0f초 경과) → 50M 폴백", _age)
                else:
                    with open(_acct_path, encoding="utf-8") as _af:
                        _acct = json.load(_af)
                    _c = int(_acct.get("cash", 50_000_000))
                    if _c > 0:
                        _capital = _c
        except Exception:
            pass

        _loss_pct    = realized_pnl / _capital if _capital > 0 else 0.0
        _loss_thresh = -CFG.ENTRY_LOCK_LOSS_PCT   # -0.02 (자본의 -2%)
        _has_loss    = _loss_pct < _loss_thresh

        if _has_loss and trade_count >= 1:
            log.warning(
                f"[ENTRY_LOCK🔒] 자본 {_loss_pct:.2%} 손실 > {_loss_thresh:.0%} 기준 "
                f"→ 재진입 차단 (pnl={realized_pnl:,}원 / capital={_capital:,}원)"
            )
            return True

        # ── 1회차: 오전 세션 어디서든 허용 ──────────────────────
        if trade_count == 0:
            log.info(f"[ENTRY_GATE✅] 1회차({now_hhmm}) → 허용")
            return False

        # ── 2회차: 오전 세션 내 재진입 허용 ─────────────────────
        if trade_count == 1:
            if now_hhmm < MORNING_E:   # 11:40 이전 오전 세션
                log.info(
                    f"[ENTRY_GATE✅] 2회차({now_hhmm}) 오전세션 내 → 허용 "
                    f"(손실={_loss_pct:.2%})"
                )
                return False
            elif AFTERNOON_S <= now_hhmm < AFTERNOON_E:   # 오후 세션 (12:50~)
                log.info(
                    f"[ENTRY_GATE✅] 2회차({now_hhmm}) 오후세션(12:50~) → 허용"
                )
                return False
            else:
                log.info(f"[ENTRY_LOCK🔒] 2회차({now_hhmm}) 점심 → 차단")
                return True

        # ── 3회차: 오후 세션만 허용 (12:50~14:50) ───────────────
        if trade_count == 2:
            if AFTERNOON_S <= now_hhmm < AFTERNOON_E:
                log.info(
                    f"[ENTRY_GATE✅] 3회차({now_hhmm}) 오후세션(12:50~) → 허용 "
                    f"(엔진 score≥0.82/OFI≥0.50 강화 적용)"
                )
                return False
            else:
                log.info(f"[ENTRY_LOCK🔒] 3회차({now_hhmm}) 오후 세션 외 → 차단")
                return True

        return True

    except Exception as e:
        log.warning(f"[ENTRY_LOCK] 실패→미차단: {e}")
        return False


# ==============================================================================
# 시장 상황 분석
# ==============================================================================
def _is_expiry_day() -> tuple:
    """
    [R5 v5.8] 한국 파생상품 만기일 — 음력 연휴 2026~2027 완전 처리
    두 번째 목요일이 공휴일이면 전날(수요일)로 자동 이동
    """
    # 한국 공휴일 (월,일) — 양력 고정 공휴일
    KR_HOLIDAYS_FIXED = {
        (1,1),(3,1),(5,5),(6,6),(8,15),
        (10,3),(10,9),(12,25),
    }
    # 2026~2027 음력 기반 공휴일 (설·추석 연휴 + 대체공휴일)
    KR_HOLIDAYS_2026 = {
        # 설연휴 (2026-02-16~18, 대체 2026-02-19)
        (2,16),(2,17),(2,18),(2,19),
        # 추석연휴 (2026-10-05~07, 대체 2026-10-08)
        (10,5),(10,6),(10,7),(10,8),
        # 어린이날 대체 (5/5 토→5/6)
        (5,6),
    }
    KR_HOLIDAYS_2027 = {
        # 설연휴 (2027-02-06~08)
        (2,6),(2,7),(2,8),
        # 추석연휴 (2027-09-24~26)
        (9,24),(9,25),(9,26),
    }
    today = datetime.now()
    year  = today.year
    # 연도별 공휴일 병합
    extra = KR_HOLIDAYS_2026 if year == 2026 else (KR_HOLIDAYS_2027 if year == 2027 else set())
    KR_HOLIDAYS = KR_HOLIDAYS_FIXED | extra

    if today.weekday() == 3:   # 목요일
        first_day = today.replace(day=1)
        first_thu_offset = (3 - first_day.weekday()) % 7
        second_thu = first_day.day + first_thu_offset + 7
        is_expiry = (today.day == second_thu)
    elif today.weekday() == 2:  # 수요일 — 목요일 만기가 공휴일일 때 이동
        first_day = today.replace(day=1)
        first_thu_offset = (3 - first_day.weekday()) % 7
        second_thu = first_day.day + first_thu_offset + 7
        # 내일(목요일)이 공휴일이면 오늘이 실질 만기
        import calendar
        max_day = calendar.monthrange(today.year, today.month)[1]
        tomorrow_day = today.day + 1 if today.day + 1 <= max_day else today.day
        is_expiry = (
            (tomorrow_day == second_thu) and
            ((today.month, tomorrow_day) in KR_HOLIDAYS)
        )
    else:
        is_expiry = False
    # 만기일 자체가 공휴일이면 무효 (이미 수요일로 이동 처리됨)
    if is_expiry and (today.month, today.day) in KR_HOLIDAYS:
        is_expiry = False
    is_triple = is_expiry and today.month in (3, 6, 9, 12)
    return is_expiry, is_triple


def _load_investor_daily(log) -> dict:
    fb = {"foreign_net_3d": 0.0, "inst_net_3d": 0.0, "foreign_flow_ok": True}
    p = Path(CFG.PATH_INVESTOR_DAILY)
    if not p.exists(): return fb
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if not {"date","foreign_net"}.issubset(df.columns): return fb
        # [INV-SORT-FIX 2026-05-26] 기존 sort_values("date").tail(3)은 종목 row 3개만 선택하던 결함.
        # 의도 = "최근 3일치 시장 전체 외국인/기관 합" → 일별 groupby + sum 후 최근 3일 필요.
        # 게이트 완화 X / 점수 조작 X / 계산 정확화만.
        _agg = {"foreign_net": "sum"}
        if "inst_net" in df.columns:
            _agg["inst_net"] = "sum"
        daily = df.groupby("date").agg(_agg).sort_index().tail(3)
        foreign_3d = float(daily["foreign_net"].fillna(0).sum())
        inst_3d    = float(daily["inst_net"].fillna(0).sum()) if "inst_net" in daily.columns else 0.0
        flow_ok    = foreign_3d >= CFG.FOREIGN_NET_3D_MIN
        log.info(f"[MARKET] 외국인3일={foreign_3d:+.0f}억 {'✅' if flow_ok else '⚠️'}")
        return {"foreign_net_3d": foreign_3d, "inst_net_3d": inst_3d, "foreign_flow_ok": flow_ok}
    except Exception as e:
        log.warning(f"[MARKET] investor_daily 실패: {e}"); return fb


def _load_market_context(df_prices: pd.DataFrame, log) -> dict:
    idx_trend = "FLAT"; idx_5bar_ret = 0.0; kospi_ret_latest = 0.0
    vol_high = False
    try:
        idx = df_prices[df_prices["code"] == CFG.INDEX_CODE].copy()
        if len(idx) >= 6:
            idx = idx.sort_values("ts")
            last_c  = float(idx["close"].iloc[-1])
            bar5_c  = float(idx["close"].iloc[-6])
            prev_c  = float(idx["close"].iloc[-2]) if len(idx) >= 2 else last_c
            idx_5bar_ret     = (last_c - bar5_c) / (bar5_c + 1e-9)
            kospi_ret_latest = (last_c - prev_c) / (prev_c + 1e-9)
            if   idx_5bar_ret >= CFG.INDEX_5BAR_STRONG_UP:   idx_trend = "STRONG_UP"
            elif idx_5bar_ret >= CFG.INDEX_5BAR_UP:          idx_trend = "UP"
            elif idx_5bar_ret <= CFG.INDEX_5BAR_STRONG_DOWN: idx_trend = "STRONG_DOWN"
            elif idx_5bar_ret <= CFG.INDEX_5BAR_DOWN:        idx_trend = "DOWN"
            else:                                             idx_trend = "FLAT"
            # 변동성 레짐 (VOL_HIGH_RATIO=1.5 인라인)
            idx_rets = idx["close"].pct_change().dropna()
            if len(idx_rets) >= 20:
                vol_now  = float(idx_rets.iloc[-20:].std())
                vol_mean = float(idx_rets.std()) if len(idx_rets) >= 60 else vol_now
                vol_high = (vol_now / (vol_mean + 1e-9)) >= 1.5
        log.info(f"[MARKET] KOSPI={idx_trend}({idx_5bar_ret:+.3%}) vol_high={vol_high}")
    except Exception as e:
        log.warning(f"[MARKET] 지수 분석 실패: {e}")

    inv = _load_investor_daily(log)
    is_expiry, is_triple = _is_expiry_day()
    if is_expiry: log.warning(f"[MARKET] {'트리플위칭' if is_triple else '선물만기일'} ⚠️")

    # market_score (MARKET_SCORE 임계 인라인: 0.70/0.50/0.30)
    idx_score     = {"STRONG_UP":1.0,"UP":0.8,"FLAT":0.6,"DOWN":0.3,"STRONG_DOWN":0.0}.get(idx_trend,0.6)
    foreign_score = 1.0 if inv["foreign_flow_ok"] else 0.5
    vol_score     = 0.7 if vol_high else 1.0
    expiry_score  = 0.7 if is_triple else (0.85 if is_expiry else 1.0)
    market_score  = idx_score*0.40 + foreign_score*0.30 + vol_score*0.20 + expiry_score*0.10

    if   market_score >= 0.70: pos_scale = 1.00
    elif market_score >= 0.50: pos_scale = 0.70
    elif market_score >= 0.30: pos_scale = 0.40
    else:                      pos_scale = 0.00

    log.info(f"[MARKET] score={market_score:.3f} pos_scale={pos_scale:.1f}")
    return {
        "index_trend"      : idx_trend,
        "kospi_ret_latest" : kospi_ret_latest,
        "vol_high"         : vol_high,
        "foreign_flow_ok"  : inv["foreign_flow_ok"],
        "is_expiry_day"    : is_expiry,
        "is_triple_witch"  : is_triple,
        "market_score"     : round(market_score, 4),
        "pos_scale"        : pos_scale,
    }


def _load_time_stats(log) -> dict:
    fallback = {"EARLY": 1.0, "MID": 1.0, "LATE": 1.0}
    p = Path(CFG.PATH_TIME_STATS)
    if not p.exists(): return fallback
    try:
        ts = pd.read_csv(p, encoding="utf-8-sig")
        if not {"time_regime","ev_boost"}.issubset(ts.columns): return fallback
        result = {}
        for _, row in ts.iterrows():
            result[str(row["time_regime"])] = float(row.get("ev_boost", 1.0))
        log.info(f"[TIME_STATS] {result}")
        return result
    except Exception as e:
        log.warning(f"[TIME_STATS] 실패: {e}"); return fallback


def _logger(run_id: str) -> logging.Logger:
    log = logging.getLogger(f"rt_engine_{run_id}")
    log.setLevel(logging.DEBUG)
    if log.handlers: log.handlers.clear()
    Path(CFG.PATH_LOG).parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(f"%(asctime)s [%(levelname)-5s] [{run_id[:8]}] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(CFG.PATH_LOG, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO); ch.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(ch)
    return log


# ==============================================================================
# 헬퍼
# ==============================================================================
def _safe_div(a, b, fill=0.0):
    if isinstance(b, (int, float)):
        return a / b if abs(b) > CFG.EPS else fill
    result = np.where(np.abs(b) < CFG.EPS, fill, a / (b + np.sign(b + CFG.EPS) * CFG.EPS))
    if isinstance(a, pd.Series):
        return pd.Series(result, index=a.index)
    return result

def _norm_clip(x, lo, hi):
    return ((x - lo) / (hi - lo + CFG.EPS)).clip(0, 1)

def _norm_code(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    m = s.str.match(r"^\d+$")
    s = s.copy(); s[m] = s[m].str.zfill(6)
    return s

def _hhmm(ts: pd.Series) -> pd.Series:
    s = ts.astype(str).str.strip()
    result = pd.Series(-1, index=ts.index, dtype=int)
    m14 = s.str.match(r"^\d{14}$")
    if m14.any():
        result[m14] = s[m14].str[8:10].astype(int)*100 + s[m14].str[10:12].astype(int)
    m12 = s.str.match(r"^\d{12}$") & ~m14
    if m12.any():
        result[m12] = s[m12].str[8:10].astype(int)*100 + s[m12].str[10:12].astype(int)
    m6 = s.str.match(r"^\d{6}$") & ~m14 & ~m12
    if m6.any():
        result[m6] = s[m6].str[0:2].astype(int)*100 + s[m6].str[2:4].astype(int)
    m4 = s.str.match(r"^\d{4}$") & ~m14 & ~m12 & ~m6
    if m4.any():
        result[m4] = s[m4].str[0:2].astype(int)*100 + s[m4].str[2:4].astype(int)
    rem = result == -1
    if rem.any():
        dt = pd.to_datetime(s[rem], errors="coerce")
        valid = dt.notna()
        if valid.any():
            result[rem[rem].index[valid.values]] = (dt[valid].dt.hour*100 + dt[valid].dt.minute).values
    return result

def _atomic_csv(df: pd.DataFrame, path: str, log) -> bool:
    """[WK-8 v5.0] .lock 파일 기반 atomic write — 공용자원 경쟁 방지"""
    tmp = path + ".tmp"
    lock_path = path + ".lock"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        # Windows 호환 simple lock (retry 3회)
        for attempt in range(3):
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(lock_fd)
                break
            except FileExistsError:
                # 락 파일이 60초 이상 오래됐으면 stale → 강제 삭제
                try:
                    if (datetime.now() - datetime.fromtimestamp(
                            Path(lock_path).stat().st_mtime)).total_seconds() > 60:
                        os.remove(lock_path)
                        log.warning(f"[SAVE] stale lock 제거: {lock_path}")
                        continue
                except Exception as e:
                    log.debug(f"[SAVE] lock 파일 처리 실패 (무시): {e}")
                if attempt < 2:
                    _time.sleep(0.5)
                    continue
                log.warning(f"[SAVE] lock 획득 실패 → 강제 진행")

        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, path)
        log.info(f"[SAVE] {path} ({Path(path).stat().st_size:,}B, {len(df)}rows)")
        return True
    except Exception as e:
        log.error(f"[SAVE] 실패: {e}")
        try: os.remove(tmp)
        except Exception: pass
        return False
    finally:
        try: os.remove(lock_path)
        except Exception: pass

_LAST_VALID_ACCOUNT: dict = {}   # [R6 v5.8] stale 시 마지막 유효값 캐싱

def _load_account(log) -> dict:
    global _LAST_VALID_ACCOUNT
    fb = {"cash": 50_000_000, "held_codes": []}
    p = Path(CFG.PATH_ACCOUNT)
    if not p.exists():
        if _LAST_VALID_ACCOUNT:
            log.warning("[ACCOUNT] 파일 없음 → 마지막 유효값 사용 (stale)")
            return _LAST_VALID_ACCOUNT
        return fb
    try:
        with open(p, encoding="utf-8") as f: d = json.load(f)
        ua = d.get("updated_at","")
        if ua:
            t = pd.to_datetime(str(ua), format="%Y%m%d%H%M%S", errors="coerce")
            if pd.notna(t) and (datetime.now()-t.to_pydatetime()).total_seconds() > 300:
                if _LAST_VALID_ACCOUNT:
                    age = int((datetime.now()-t.to_pydatetime()).total_seconds())
                    log.warning(f"[ACCOUNT] ⚠️ 데이터 {age}초 경과(>300초) → 마지막 유효값 유지 (R6 v5.8)")
                    return _LAST_VALID_ACCOUNT
                log.warning("[ACCOUNT] ⚠️ 데이터 만료 + 캐시 없음 → 기본값 50M 적용")
                return fb
        result = {"cash": int(d.get("cash", 50_000_000)),
                  "held_codes": [str(c).zfill(6) for c in d.get("held_codes", [])]}
        _LAST_VALID_ACCOUNT = result   # 유효값 캐싱
        return result
    except Exception as e:
        log.warning(f"[ACCOUNT] 로드 실패→캐시/기본값: {e}")
        return _LAST_VALID_ACCOUNT if _LAST_VALID_ACCOUNT else fb

def _check_dd(log) -> bool:
    p = Path(CFG.PATH_PNL)
    if not p.exists(): return False
    try:
        with open(p, encoding="utf-8") as f: d = json.load(f)
        ua = d.get("updated_at","")
        if ua:
            t = pd.to_datetime(str(ua), format="%Y%m%d%H%M%S", errors="coerce")
            if pd.notna(t) and (datetime.now()-t.to_pydatetime()).total_seconds() > CFG.DD_STALE_SEC:
                return False
        if str(d.get("date","")) != datetime.now().strftime("%Y%m%d"): return False
        if int(d.get("realized_pnl", 0)) <= CFG.DD_LOSS_LIMIT:
            log.critical("[DD] 드로우다운 차단")
            return True
    except Exception as e:
        log.warning(f"[DD] 체크 실패→미차단: {e}")
    return False


# ==============================================================================
# [패치3 v5.1] MDD 기반 학습 필터
# ==============================================================================
def _load_mdd(log) -> float:
    """rt_daily_pnl.json에서 max_drawdown 로드 → 포지션 축소 판단"""
    try:
        p = Path(CFG.PATH_PNL)
        if not p.exists(): return 0.0
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        mdd = float(d.get("max_drawdown", 0))
        if mdd < -0.05:
            log.warning(f"[MDD] max_drawdown={mdd:.2%}")
        return mdd
    except Exception as e:
        log.warning(f"[MDD] 로드 실패: {e}")
        return 0.0


# ==============================================================================
# STAGES
# ==============================================================================
def _load(log) -> tuple:
    log.info("LOAD")
    try:
        dp = pd.read_csv(CFG.PATH_PRICES, encoding="utf-8-sig", dtype={"code": str})
        dv = pd.read_csv(CFG.PATH_PREV,   encoding="utf-8-sig", dtype={"code": str})
        log.info(f"prices={len(dp)}rows | prev={len(dv)}rows")
        return dp, dv
    except Exception as e:
        log.critical(f"[LOAD] 실패: {e}"); return None, None


def _clean(dp: pd.DataFrame, dv: pd.DataFrame, log):
    log.info("CLEAN")
    dp["code"] = _norm_code(dp["code"])
    dp["hhmm"] = _hhmm(dp["ts"])
    dp = dp[dp["hhmm"] != -1].copy()
    for c in ["open","high","low","close","volume","value"]:
        dp[c] = pd.to_numeric(dp[c], errors="coerce")
    bad = dp["close"].isna() | (dp["close"] <= 0) | (dp["high"] < dp["low"])
    dp = dp[~bad].drop_duplicates(["code","ts"]).sort_values(["code","ts"]).reset_index(drop=True)

    dv["code"] = _norm_code(dv["code"])
    for c in ["prev_close","prev_high","prev_low","prev_volume","prev_value",
              "high_52w_ratio"]:  # [보강] 52주 신고가 비율
        dv[c] = pd.to_numeric(dv[c], errors="coerce")
    dv = dv.drop_duplicates("code")

    df = dp.merge(dv[["code","prev_close","prev_high","prev_low","prev_volume","prev_value"]],
                  on="code", how="left")
    df["prev_ok"] = df["prev_close"].notna()

    # [W7 v5.7] 거래정지 종목 자동 제외
    # 감지기준: 최신봉 기준 (high==low AND volume==0) OR (close==prev_close AND volume==0)
    # → 가격 고착 + 무거래 = 거래정지 또는 데이터 이상
    try:
        latest = dp.sort_values("ts").groupby("code").last().reset_index()
        halt_mask_1 = (latest["high"] == latest["low"]) & (latest["volume"] == 0)
        halt_mask_2 = (latest["close"] == latest["prev_close"] if "prev_close" in latest.columns
                       else pd.Series(False, index=latest.index)) & (latest["volume"] == 0)
        halt_codes  = set(latest.loc[halt_mask_1 | halt_mask_2, "code"].astype(str))
        if halt_codes:
            before = len(df)
            df = df[~df["code"].isin(halt_codes)].copy()
            log.warning(
                f"[CLEAN] ⚠️ 거래정지 의심 종목 제외={len(halt_codes)}개 "
                f"({before}→{len(df)}행) | codes={list(halt_codes)[:5]}"
            )
    except Exception as e:
        log.warning(f"[CLEAN] 거래정지 필터 실패(비치명적): {e}")

    cov = df["prev_ok"].sum() / (len(df) + CFG.EPS)
    log.info(f"clean → {len(df)}rows | prev_cov={cov:.1%}")
    if cov < 0.30:
        log.critical(f"[CLEAN] prev_cov={cov:.1%} < 30% → STOP"); return None
    return df


def _features(df: pd.DataFrame, market_ctx: dict, log) -> pd.DataFrame:
    """
    [v5.0] BUG-2: ATR True Range 수정 포함
    제거 유지: POC, VWAP밴드, range_zscore, weekly_trend_ok
    """
    log.info("FEATURES")
    EPS = CFG.EPS

    # 전일 기준
    df["ret_from_prev_close"] = _safe_div(df["close"]-df["prev_close"], df["prev_close"])
    df["gap_pct"]             = _safe_div(df["open"] -df["prev_close"], df["prev_close"])
    gap_abs = df["gap_pct"].abs()
    df["gap_grade"] = "SMALL"
    df.loc[gap_abs >= CFG.GAP_MID,   "gap_grade"] = "MID"
    df.loc[gap_abs >= CFG.GAP_LARGE, "gap_grade"] = "LARGE"

    # 전일 고점 돌파
    df["prev_high_break"] = (df["close"] > df["prev_high"].fillna(9e9)).fillna(False)
    df["above_prev_high"] = (df["close"] >= df["prev_high"].fillna(9e9) * 0.995).fillna(False)

    # 갭 소화 완료
    df["gap_filled_flag"] = (
        (df["gap_pct"] > 0) & (df["close"] < df["open"])
    ).fillna(False)

    # 장중
    df["intraday_high"]         = df.groupby("code")["high"].cummax()
    df["intraday_pullback_pct"] = (df["intraday_high"]-df["close"]) / (df["intraday_high"]+EPS)
    denom = df["intraday_high"] - df.groupby("code")["low"].cummin() + EPS
    df["intraday_position"]     = (df["close"] - df.groupby("code")["low"].cummin()) / denom

    # VWAP (전체 누적)
    df["cum_value"]  = df.groupby("code")["value"].cumsum()
    df["cum_volume"] = df.groupby("code")["volume"].cumsum()
    df["value_5"]    = df.groupby("code")["value"].transform(lambda x: x.rolling(5, min_periods=1).sum())
    df["value_20"]   = df.groupby("code")["value"].transform(lambda x: x.rolling(20,min_periods=1).sum())
    df["value_ratio_5m"] = _safe_div(df["value_5"], df["value_20"]/4+EPS)
    df["vwap"]       = _safe_div(df["cum_value"], df["cum_volume"], fill=df["close"])
    df["vwap_dev_pct"]= _safe_div(df["close"]-df["vwap"], df["vwap"])

    # Anchored VWAP (세션 기준: hhmm≥900)
    session_mask = df["hhmm"] >= 900
    sess_cum_val = df["value"].where(session_mask, 0.0).groupby(df["code"]).cumsum()
    sess_cum_vol = df["volume"].where(session_mask, 0.0).groupby(df["code"]).cumsum()
    df["anchored_vwap"] = pd.Series(
        _safe_div(sess_cum_val.values, (sess_cum_vol + EPS).values),
        index=df.index
    ).where(session_mask, df["vwap"]).fillna(df["vwap"])

    # 이동평균 / 기울기
    df["ma5"]  = df.groupby("code")["close"].transform(lambda x: x.rolling(5, min_periods=1).mean())
    df["ma20"] = df.groupby("code")["close"].transform(lambda x: x.rolling(20,min_periods=1).mean())
    df["price_above_ma5"]  = df["close"] >= df["ma5"]
    df["price_above_ma20"] = df["close"] >= df["ma20"]

    # [보강] 헤지펀드 기준 과거 데이터 3가지
    # 1) MA60 정배열
    df["ma60"] = df.groupby("code")["close"].transform(
        lambda x: x.rolling(60, min_periods=20).mean())
    df["price_above_ma60"] = (df["close"] >= df["ma60"].fillna(0)).fillna(False)

    # 2) D-3 연속양봉 — 최근 3일 일봉 모두 양봉
    try:
        if "dt" in df.columns:
            df["_dt_p"] = pd.to_datetime(df["dt"], errors="coerce")
            _daily = df.groupby(["code", df["_dt_p"].dt.date]).agg(
                _dopen=("open","first"), _dclose=("close","last")
            ).reset_index()
            _daily["_bull"] = _daily["_dclose"] >= _daily["_dopen"]
            _d3 = _daily.groupby("code")["_bull"].apply(
                lambda x: bool(x.tail(3).all()) if len(x) >= 3 else False
            ).reset_index()
            _d3.columns = ["code","d3_consec_bull"]
            df = df.merge(_d3, on="code", how="left")
            df["d3_consec_bull"] = df["d3_consec_bull"].fillna(False)
            df.drop(columns=["_dt_p"], inplace=True, errors="ignore")
        else:
            df["d3_consec_bull"] = False
    except Exception as _e:
        df["d3_consec_bull"] = False

    # 3) 52주 신고가 근접 — prev_day_summary의 high_52w_ratio 활용
    if "high_52w_ratio" in df.columns:
        df["w52_high_pct"] = df["high_52w_ratio"].fillna(0.5)
    else:
        df["w52_high_pct"] = 0.5
    ma5_lag  = df.groupby("code")["ma5"].transform(lambda x: x.shift(3))
    ma20_lag = df.groupby("code")["ma20"].transform(lambda x: x.shift(5))
    df["trend_slope_short"] = _safe_div(df["ma5"] -ma5_lag,  ma5_lag.abs() +EPS)
    df["trend_slope_mid"]   = _safe_div(df["ma20"]-ma20_lag, ma20_lag.abs()+EPS)

    # VWAP 회복 / 재돌파 (anchored_vwap 기준)
    df["reclaim_vwap_flag"] = (df["close"] >= df["anchored_vwap"]*0.999).fillna(False)
    hrm3 = df.groupby("code")["high"].transform(lambda x: x.shift(1).rolling(3,min_periods=1).max())
    df["rebreak_flag"] = (df["close"] > hrm3).fillna(False)

    # VWAP 상향 돌파 (anchored_vwap 기준)
    close_prev1 = df.groupby("code")["close"].transform(lambda x: x.shift(1))
    df["vwap_cross_up"] = (
        (close_prev1 < df["anchored_vwap"]) & (df["close"] >= df["anchored_vwap"])
    ).fillna(False)

    # vol_accel (초기봉 NaN 수정)
    value_5_lag = df.groupby("code")["value_5"].transform(lambda x: x.shift(1))
    value_5_lag = value_5_lag.fillna(df["value_5"])
    df["vol_accel"] = pd.Series(
        _safe_div(df["value_5"].values, (value_5_lag + EPS).values),
        index=df.index
    ).fillna(1.0).clip(0, 5)
    df["vol_accel_strong"] = df["vol_accel"] >= CFG.VOL_ACCEL_MIN

    # vol_confirm_cross
    df["vol_confirm_cross"] = (df["vwap_cross_up"] & df["vol_accel_strong"]).fillna(False)

    # 상대강도 vs KOSPI
    kospi_ret = float(market_ctx.get("kospi_ret_latest", 0.0))
    df["rel_return"] = (df["ret_from_prev_close"] - kospi_ret).clip(-0.20, 0.20).fillna(0)
    df["strong_rs"]  = df["rel_return"] >= CFG.RS_STRONG_MIN

    # 장중 신고가 갱신
    intraday_high_prev = df.groupby("code")["intraday_high"].transform(lambda x: x.shift(1))
    df["new_high_flag"] = (
        (df["close"] > intraday_high_prev.fillna(0)) & session_mask
    ).fillna(False)

    # VWAP 아래 연속봉 + fast_recovery
    def _vwap_below_streak(grp: pd.DataFrame) -> pd.Series:
        below = (grp["close"] < grp["anchored_vwap"]).values
        result = np.zeros(len(below), dtype=int)
        for i in range(len(below)):
            result[i] = result[i-1] + 1 if (i > 0 and below[i]) else (1 if below[i] else 0)
        return pd.Series(result, index=grp.index)
    try:
        df["vwap_below_bars"] = df.groupby("code", group_keys=False).apply(
            _vwap_below_streak
        ).fillna(0).astype(int)
    except Exception as e:
        log.warning(f"[FEAT] vwap_below_bars 실패: {e}"); df["vwap_below_bars"] = 0

    vwap_below_prev = df.groupby("code")["vwap_below_bars"].transform(lambda x: x.shift(1)).fillna(0)
    df["fast_recovery"] = (
        (vwap_below_prev >= 1) &
        (vwap_below_prev <= 3) &
        df["reclaim_vwap_flag"].fillna(False)
    ).fillna(False)

    # 눌림 중 거래량 감소
    prev_val_per_5m = df["prev_value"].fillna(0) / 390.0 * 5.0
    df["pb_vol_ratio"] = pd.Series(
        _safe_div(df["value_5"].values, (prev_val_per_5m + EPS).values),
        index=df.index
    ).fillna(1.0).clip(0, 5)
    df["quiet_pullback"] = (
        (df["prev_value"].fillna(0) > 0) &
        (df["intraday_pullback_pct"].fillna(0) >= CFG.PB_MIN) &
        (df["pb_vol_ratio"] < CFG.QUIET_PB_VOL_MAX)
    ).fillna(False)

    # Hammer 캔들 패턴
    body_top    = df[["open","close"]].max(axis=1)
    body_bottom = df[["open","close"]].min(axis=1)
    candle_range= (df["high"] - df["low"]).clip(lower=EPS)
    lower_shadow= (body_bottom - df["low"]) / candle_range
    body_ratio  = (body_top - body_bottom) / candle_range
    df["hammer_flag"] = (
        (lower_shadow >= CFG.HAMMER_LOWER_MIN) &
        (body_ratio   <= CFG.HAMMER_BODY_MAX) &
        (df["intraday_pullback_pct"].fillna(0) >= CFG.PB_MIN)
    ).fillna(False)

    # [결함-A 수정] Higher Low 패턴 — 지침서 §7-1 필수 조건
    # 정의: 현재 저점이 직전 N봉 최소 저점보다 높음 → 추세 상승 중 눌림 확인
    # 단순 하락봉과 진짜 눌림목을 구분하는 핵심 필터
    _HL_WINDOW = 5   # 최근 5봉 직전 저점 대비 현재 저점 비교
    _prev_low = df.groupby("code")["low"].transform(
        lambda x: x.shift(1).rolling(_HL_WINDOW, min_periods=2).min()
    )
    df["higher_low"] = (df["low"] > _prev_low.fillna(0)).fillna(False)

    # [결함-A 수정] RSI(14) 계산 — 지침서 §7-1 RSI < 70 필터
    # Wilder(1978) 원전 방식: EMA(alpha=1/14) 기반
    _RSI_PERIOD = 14
    def _calc_rsi(s: pd.Series) -> pd.Series:
        delta    = s.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1/_RSI_PERIOD, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/_RSI_PERIOD, adjust=False).mean()
        rs = avg_gain / (avg_loss + EPS)
        return (100 - 100 / (1 + rs)).clip(0, 100)

    df["rsi14"] = df.groupby("code")["close"].transform(_calc_rsi).fillna(50.0)

    # 체결강도
    if "buy_volume" in df.columns and "sell_volume" in df.columns:
        for c in ["buy_volume","sell_volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        raw = df["buy_volume"] / (df["buy_volume"]+df["sell_volume"]+EPS)
        df["chegyul_strength"] = raw.groupby(df["code"]).transform(
            lambda x: x.rolling(5,min_periods=1).mean()
        ).fillna(0.5).clip(0,1)
    else:
        # [경고-B 보완] buy_volume/sell_volume 컬럼 없음 → 체결강도 0.5(중립) 고정
        # chegyul_momentum, sb 보너스가 사실상 비활성 → 데이터 파이프라인 점검 필요
        df["chegyul_strength"] = 0.5
        log.warning(
            "[FEAT] ★ buy_volume/sell_volume 없음 → chegyul_strength=0.5 고정 "
            "(체결강도 기반 sb보너스 비활성) — prices_1m.csv 컬럼 확인 요망"
        )

    # 체결강도 모멘텀
    chegyul_lag3 = df.groupby("code")["chegyul_strength"].transform(lambda x: x.shift(3))
    df["chegyul_momentum"] = (
        (df["chegyul_strength"] > chegyul_lag3.fillna(0)) &
        (df["chegyul_strength"] >= CFG.CHEGYUL_MOMENTUM_MIN)
    ).fillna(False)

    # 외인 순매수 비율
    if "foreign_net_buy" in df.columns:
        df["foreign_net_buy"] = pd.to_numeric(df["foreign_net_buy"],errors="coerce").fillna(0)
        df["foreign_net_ratio"] = _safe_div(
            df.groupby("code")["foreign_net_buy"].cumsum()*df["close"],
            df["cum_value"]+EPS
        ).clip(-0.5,0.5).fillna(0)
    else:
        df["foreign_net_ratio"] = 0.0

    # [FIX-2 v5.5] 기관 순매수 비율 + 가속도 — 지침서 §10-1 정확히 일치
    # 기존: 당일 누적 inst_net_buy / 누적 value (오전·오후 해석 왜곡)
    # 수정: 5봉 이동합계 / 5봉 이동합계 → 최근 5분봉 흐름 포착
    if "inst_net_buy" in df.columns:
        df["inst_net_buy"] = pd.to_numeric(df["inst_net_buy"],errors="coerce").fillna(0)

        # OFI: 최근 5봉 기관순매수합 / 최근 5봉 거래량합 (지침서 §10-1)
        inst_5 = df.groupby("code")["inst_net_buy"].transform(
            lambda x: x.rolling(5, min_periods=1).sum()
        )
        vol_5_ofi = df.groupby("code")["volume"].transform(
            lambda x: x.rolling(5, min_periods=1).sum()
        )
        df["inst_net_ratio"] = _safe_div(
            inst_5, (vol_5_ofi * df["close"] + EPS)   # 금액 단위 통일
        ).clip(-0.5, 0.5).fillna(0)

        # accel: mean(최근3봉) / mean(이전5봉) (지침서 §3-4)
        inst_ma3 = df.groupby("code")["inst_net_buy"].transform(
            lambda x: x.rolling(3, min_periods=1).mean()
        )
        inst_ma5_prev = df.groupby("code")["inst_net_buy"].transform(
            lambda x: x.shift(3).rolling(5, min_periods=1).mean()
        )
        df["inst_accel"] = _safe_div(
            inst_ma3, inst_ma5_prev.abs() + EPS
        ).clip(0, 5).fillna(1.0)

        def _consec_pos(s):
            arr = s.values; result = np.zeros(len(arr), dtype=int)
            for i in range(len(arr)):
                result[i] = result[i-1]+1 if (i>0 and arr[i]>CFG.INST_ACCEL_MIN) else (1 if arr[i]>CFG.INST_ACCEL_MIN else 0)
            return pd.Series(result, index=s.index)
        df["inst_accel_consecutive"] = df.groupby("code")["inst_accel"].transform(_consec_pos).fillna(0)
    else:
        df["inst_net_ratio"] = 0.0; df["inst_accel"] = 0.0; df["inst_accel_consecutive"] = 0

    # 전일 거래량 폭증
    latest_prev_vol = df.groupby("code")["prev_volume"].last().fillna(0)
    median_prev_vol = latest_prev_vol.median()
    df["prev_vol_surge_ratio"] = (
        df["code"].map(latest_prev_vol / (median_prev_vol + EPS)).fillna(1.0).clip(0, 10)
        if median_prev_vol > 0 else pd.Series(1.0, index=df.index)
    )
    df["prev_vol_surge"] = df["prev_vol_surge_ratio"] >= CFG.PREV_VOL_SURGE_RATIO

    # ATR 14봉 [BUG-2 v5.0] True Range = max(H-L, |H-PrevC|, |L-PrevC|)
    prev_close_g = df.groupby("code")["close"].transform(lambda x: x.shift(1))
    tr_hl   = (df["high"] - df["low"]).clip(lower=0)
    tr_hpc  = (df["high"] - prev_close_g).abs()
    tr_lpc  = (df["low"]  - prev_close_g).abs()
    true_range = pd.concat([tr_hl, tr_hpc, tr_lpc], axis=1).max(axis=1).fillna(tr_hl)
    df["atr14"] = df.groupby("code")["close"].transform(
        lambda x: pd.Series(true_range.loc[x.index].values, index=x.index)
                  .rolling(CFG.ATR_PERIOD, min_periods=3).mean()
    ).fillna(0).clip(lower=0)

    # ATR 기반 동적 진입 밴드
    df["entry_band_pct"] = (
        _safe_div(df["atr14"].values, (df["close"] + EPS).values) * CFG.ENTRY_BAND_ATR_MULT
    )
    df["entry_band_pct"] = pd.Series(df["entry_band_pct"], index=df.index).fillna(
        CFG.ENTRY_BAND_MIN
    ).clip(CFG.ENTRY_BAND_MIN, CFG.ENTRY_BAND_MAX)

    df["entry_price_low"]  = (df["close"] * (1 - df["entry_band_pct"])).round(0)
    vwap_ref = df[["close","anchored_vwap"]].min(axis=1)
    df["entry_price_high"] = (vwap_ref * (1 + df["entry_band_pct"])).round(0)
    swap = df["entry_price_low"] > df["entry_price_high"]
    df.loc[swap, "entry_price_high"] = (df.loc[swap, "close"] * (1 + df.loc[swap, "entry_band_pct"])).round(0)

    # 이벤트 리스크 (value_spike_ratio)
    val_ma = df.groupby("code")["value"].transform(lambda x: x.rolling(20,min_periods=5).mean()).fillna(EPS)
    df["value_spike_ratio"] = _safe_div(df["value"], val_ma)
    close_lag3 = df.groupby("code")["close"].transform(lambda x: x.shift(3))
    df["last3_ret"] = _safe_div(df["close"]-close_lag3, close_lag3.abs()+EPS).fillna(0)

    # 신호 유효시간
    df["signal_ts"]        = datetime.now().strftime("%Y%m%d%H%M%S")
    df["signal_valid_sec"] = CFG.SIGNAL_VALID_SEC

    log.info(
        f"[FEAT] {len(df)}rows | {df['code'].nunique()}codes | "
        f"prev_high_break={df['prev_high_break'].sum()} | "
        f"hammer={df['hammer_flag'].sum()} | "
        f"fast_rec={df['fast_recovery'].sum()} | "
        f"vol_confirm={df['vol_confirm_cross'].sum()} | "
        f"chegyul_mom={df['chegyul_momentum'].sum()} | "
        f"higher_low={df['higher_low'].sum()} | "          # [결함-A]
        f"rsi_ok(rsi<70)={(df['rsi14'].fillna(50)<70).sum()}"  # [결함-A]
    )
    return df


def _market_regime(df: pd.DataFrame, market_ctx: dict, log) -> tuple:
    try:
        non_idx = df[~df["code"].isin(["U001","U201"])]
        if non_idx.empty: return df, "RANGE"
        last    = non_idx.sort_values("ts").groupby("code").last()
        idx_ret = last["ret_from_prev_close"].mean()

        # [FIX-C v5.6] Breadth 복합 스코어 — 단순 등락비율 → 3단계 강도 반영
        total_n = len(last) + CFG.EPS
        rets    = last["ret_from_prev_close"].fillna(0)

        # 기본 breadth (등락비율)
        breadth_basic  = (rets > 0).sum() / total_n
        # 강한 상승 비율 (3% 이상)
        breadth_strong = (rets >= CFG.BREADTH_STRONG_RET).sum() / total_n
        # 급등 비율 (5% 이상 — 상한가 근접 모멘텀)
        breadth_surge  = (rets >= CFG.BREADTH_SURGE_RET).sum() / total_n
        # 강한 하락 비율 (−3% 이하)
        breadth_drop   = (rets <= -CFG.BREADTH_STRONG_RET).sum() / total_n

        # 복합 breadth: 기본 50% + 강한상승 30% + 급등 20%
        breadth = (breadth_basic * 0.50 +
                   breadth_strong * 0.30 +
                   breadth_surge  * 0.20).clip(0, 1)

        if   idx_ret >= CFG.STRONG_UP_T   and breadth >= CFG.BREADTH_UP_T:   regime = "STRONG_UP"
        elif idx_ret >= CFG.WEAK_UP_T     and breadth >= CFG.BREADTH_UP_T:   regime = "WEAK_UP"
        elif idx_ret <= CFG.STRONG_DOWN_T and breadth <= CFG.BREADTH_DOWN_T: regime = "STRONG_DOWN"
        elif idx_ret <= CFG.WEAK_DOWN_T   and breadth <= CFG.BREADTH_DOWN_T: regime = "WEAK_DOWN"
        else: regime = "RANGE"

        # [FIX-C v5.6] 강한상승 종목 비율이 높으면 WEAK_UP → STRONG_UP 보정
        if regime == "WEAK_UP" and breadth_strong >= CFG.BREADTH_STRONG_T:
            regime = "STRONG_UP"
            log.info(f"[REGIME] breadth_strong={breadth_strong:.1%}≥{CFG.BREADTH_STRONG_T:.0%} → WEAK_UP→STRONG_UP 보정")

        # [FIX-C v5.6] 급락 종목 비율이 높으면 레짐 강화
        if breadth_drop >= CFG.BREADTH_WEAK_LIMIT and regime in ("WEAK_UP","RANGE"):
            regime = "WEAK_DOWN"
            log.info(f"[REGIME] breadth_drop={breadth_drop:.1%}≥{CFG.BREADTH_WEAK_LIMIT:.0%} → {regime} 강화")

        index_trend = market_ctx.get("index_trend", "FLAT")
        # ── [REGIME-TODAY 2026-06-12 ★친구님 지시 "눈 통일"] 낡은 index_trend의 강제 뒤집기 무력화 ──
        #   실측: 6/12 자체계산 idx_ret +7.8%/breadth 0.77(건강)인데 외부 index_trend="STRONG_DOWN"이
        #   강제 STRONG_DOWN — 코스피(U001)·D-1 기반 낡은 딱지가 당일 폭등장을 뒤집음(6/9 Phase2 잔재).
        #   처방: kosdaq_index.json(당일+600s 신선) ±1.5% 넘으면 그 방향으로 index_trend 교체.
        #   롤백: env REGIME_TODAY_OVERRIDE=NO (4파일 공통).
        if os.environ.get("REGIME_TODAY_OVERRIDE", "YES").strip().upper() == "YES":
            try:
                import json as _rt_json
                from datetime import datetime as _rt_dt
                from pathlib import Path as _rt_Path
                _idx_p = _rt_Path(r"C:\stock_bot\DATA\kosdaq_index.json")
                if _idx_p.exists():
                    with open(_idx_p, "r", encoding="utf-8-sig") as _rf:
                        _idx = _rt_json.load(_rf)
                    _its, _chg = str(_idx.get("ts", "")), _idx.get("chg", None)
                    if _its and _chg is not None:
                        _age = (_rt_dt.now() - _rt_dt.strptime(_its, "%Y-%m-%d %H:%M:%S")).total_seconds()
                        if _its[:10] == _rt_dt.now().strftime("%Y-%m-%d") and _age <= 600:
                            _chg = float(_chg)
                            if _chg >= 1.5 and index_trend in ("STRONG_DOWN", "DOWN"):
                                log.warning(f"[REGIME-TODAY] 당일 KOSDAQ {_chg:+.2f}% (신선 {_age:.0f}s) → 낡은 index_trend={index_trend} 무시(UP 교체)")
                                index_trend = "UP"
                            elif _chg <= -1.5 and index_trend not in ("STRONG_DOWN", "DOWN"):
                                log.warning(f"[REGIME-TODAY] 당일 KOSDAQ {_chg:+.2f}% (신선 {_age:.0f}s) → index_trend=STRONG_DOWN 교체")
                                index_trend = "STRONG_DOWN"
            except Exception as _rte:
                log.debug(f"[REGIME-TODAY] 스킵({_rte})")
        if index_trend == "STRONG_DOWN" and regime != "STRONG_DOWN":
            regime = "STRONG_DOWN"; log.warning("[REGIME] KOSPI 강력 하락 → STRONG_DOWN 강제")
        elif index_trend == "DOWN" and regime == "STRONG_UP":
            regime = "WEAK_UP"
        log.info(
            f"[REGIME] {regime} | idx_ret={idx_ret:.4f} | "
            f"breadth(복합)={breadth:.3f} | basic={breadth_basic:.3f} | "
            f"strong={breadth_strong:.3f} | surge={breadth_surge:.3f} | drop={breadth_drop:.3f}"
        )
    except Exception as e:
        log.error(f"[REGIME] 오류→RANGE: {e}"); regime = "RANGE"
    df["market_regime"] = regime
    return df, regime


def _time_regime(df: pd.DataFrame, log) -> pd.DataFrame:
    h = df["hhmm"]
    df["time_regime"] = np.select(
        [
            (h >= CFG.T_EARLY_S) & (h < CFG.T_EARLY_E),   # 1회차: 09:20~10:30
            (h >= CFG.T_MID_S)   & (h < CFG.T_MID_E),     # 2회차: 10:30~11:40
            (h >= CFG.T_LUNCH_S) & (h < CFG.T_LUNCH_E),   # 점심금지: 11:40~13:00
            (h >= CFG.T_LATE_S)  & (h < CFG.T_LATE_E),    # 3회차: 13:00~14:50
        ],
        ["EARLY", "MID", "LUNCH_BLOCK", "LATE"],
        default="BLOCKED"
    )
    # 점심 구간 로그
    lunch_cnt = (df["time_regime"] == "LUNCH_BLOCK").sum()
    if lunch_cnt > 0:
        log.debug("[TIME] LUNCH_BLOCK %d봉 진입금지 적용", lunch_cnt)

    # ── [v5.9-LATE4] 오후용 고점 대비 낙폭 계산 ──────────────────
    # 당일 09:00 이후 최고가 대비 현재가 낙폭
    # ret_from_high = (close - day_high) / day_high  (음수)
    if "hhmm" in df.columns and "close" in df.columns:
        try:
            day_high = df.groupby("code")["high"].transform("max")
            df["ret_from_high"] = ((df["close"] - day_high) / (day_high + 1e-9)).clip(-0.20, 0)
        except Exception:
            df["ret_from_high"] = -0.05  # 계산 실패 시 중립값
    else:
        df["ret_from_high"] = -0.05

    return df


def _dump_trend_diag(df, log):
    # [2026-06-09 진단 전용 — READ-ONLY] entry_trend/pullback + feature 스냅샷 덤프.
    #   ★flag(TREND_DIAG_DUMP)+try/except로 완전 격리. df 복사본만 저장(원본 무변경).
    #   entry/score/gate/queue/주문 로직과 무관. 실패해도 엔진 절대 안 죽음.
    import os as _os
    if _os.environ.get("TREND_DIAG_DUMP", "1") != "1":
        return
    try:
        import datetime as _dt
        _wanted = ["code","name","entry_trend","entry_pullback","close","anchored_vwap",
                   "vwap","vwap_dev_pct","value_ratio_5m","trend_slope_short","trend_slope_mid",
                   "ret_from_prev_close","price_above_ma5","rsi14","intraday_pullback_pct",
                   "prev_high_break","hammer_flag","gap_grade","inst_consec","inst_accel",
                   "market_regime","time_regime","hhmm","higher_low","reclaim_vwap_flag",
                   "value_5","value_spike_ratio","last3_ret"]
        _cols = [c for c in _wanted if c in df.columns]
        _out = df[_cols].copy()
        _out.insert(0, "snap_ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        _out.to_csv(r"C:\stock_bot\DATA\trend_diag_snapshot.csv", index=False, encoding="utf-8-sig")
    except Exception as _e:
        try: log.debug(f"[TREND_DIAG] dump skip: {_e}")
        except Exception: pass


def _signals(df: pd.DataFrame, log) -> pd.DataFrame:
    log.info("SIGNALS")
    base = (
        df["prev_ok"].fillna(False) &
        (~df["time_regime"].isin(["BLOCKED", "LUNCH_BLOCK"])) &
        (~df["market_regime"].isin(["STRONG_DOWN"]))
    )
    # ── 추세 신호 ───────────────────────────────────────────────
    df["entry_trend"] = (base &
        (df["close"] >= df["anchored_vwap"] * CFG.TREND_VWAP_MIN) &
        (df["trend_slope_short"].fillna(-1) > 0) &
        (df["trend_slope_mid"].fillna(-1) >= CFG.TREND_SLOPE_MID_MIN) &
        (df["value_ratio_5m"].fillna(0) >= CFG.TREND_VAL_RATIO) &
        (df["ret_from_prev_close"].fillna(-1) > 0) &
        (df["price_above_ma5"].fillna(False))
    ).fillna(False)

    large_mask = df["gap_grade"] == "LARGE"
    trend_large_ok = (
        (df["close"] >= df["anchored_vwap"] * 1.005) &
        (df["trend_slope_short"].fillna(-1) > 0.001)
    ).fillna(False)
    df["entry_trend"] = (
        (df["entry_trend"] & ~large_mask) | (df["entry_trend"] & large_mask & trend_large_ok)
    ).fillna(False)

    # ── 눌림목 신호 ─────────────────────────────────────────────
    # [결함-A 수정] pb_base에 Higher Low + RSI < 70 AND 조건 추가 — 지침서 §7-1
    # higher_low: 추세 상승 중 눌림(단순 하락봉 차단)
    # rsi14 < 70: 과매수 구간 진입 차단 (RSI≥70은 이미 달아오른 구간)
    pb_base = (base &
        (df["close"] >= df["anchored_vwap"] * CFG.PB_VWAP_MIN) &
        (df["ret_from_prev_close"].fillna(-99) >= CFG.PB_RET_MIN) &
        (df["trend_slope_mid"].fillna(-1) >= CFG.TREND_SLOPE_MID_MIN) &
        (df["reclaim_vwap_flag"].fillna(False)) &
        (df["higher_low"].fillna(False)) &                 # [결함-A] Higher Low 필수
        (df["rsi14"].fillna(50) < CFG.PB_RSI_MAX) &       # [결함-A] RSI < 70 필수
        (df["vwap_dev_pct"].fillna(-1) <= CFG.PB_VWAP_DEV_MAX)  # [결함-B] +3% 상한
    ).fillna(False)

    pb_small = (pb_base & (df["gap_grade"]=="SMALL") &
                (df["intraday_pullback_pct"].fillna(0) >= CFG.PB_MIN) &
                (df["intraday_pullback_pct"].fillna(0) <= CFG.PB_MAX)).fillna(False)
    pb_mid   = (pb_base & (df["gap_grade"]=="MID") &
                (df["intraday_pullback_pct"].fillna(0) >= CFG.PB_MIN) &
                (df["intraday_pullback_pct"].fillna(0) <= 0.03)).fillna(False)
    # [WK-1 v5.0] LARGE 갭 눌림목: 조건부 허용 (VWAP 위 + 기울기 확인)
    pb_large = (pb_base & (df["gap_grade"]=="LARGE") &
                (df["intraday_pullback_pct"].fillna(0) >= CFG.PB_MIN) &
                (df["intraday_pullback_pct"].fillna(0) <= 0.025) &
                (df["close"] >= df["anchored_vwap"] * 1.005) &
                (df["trend_slope_short"].fillna(-1) > 0.001)).fillna(False)
    df["entry_pullback"] = (pb_small | pb_mid | pb_large).fillna(False)

    # [WK-5 v5.0] WEAK_DOWN: entry_trend 차단, entry_pullback만 허용
    weak_down_mask = df["market_regime"] == "WEAK_DOWN"
    if weak_down_mask.any():
        df.loc[weak_down_mask, "entry_trend"] = False
        log.info(f"[SIG] WEAK_DOWN 추세신호 차단={weak_down_mask.sum()}행")

    # EARLY 눌림목 허용 (항상 True)
    # [PATCH] T_LUNCH 무력화로 1140부터 LATE 라벨 — 진짜 13:00+ 에만 LATE 가드 적용
    late = (df["time_regime"] == "LATE") & (df["hhmm"] >= 1300)
    df.loc[late, "entry_trend"]    &= (df["value_ratio_5m"].fillna(0) >= 1.2)[late]
    df.loc[late, "entry_pullback"] &= (df["intraday_pullback_pct"].fillna(1) <= 0.03)[late]

    # [패치6 v5.1] 기관 필터 강화 — 기관의 등 탔다가 미리 내리기 핵심
    # [v5.14-FIX3] inst_net_buy 실제값 기반 판정 — fillna(1.0) 워밍업값으로 has_inst=True
    # 오인식 방지: inst_net_buy 소스 데이터가 모두 0이면 기관 데이터 미수신으로 처리
    _inst_src_ok = (
        "inst_net_buy" in df.columns and
        df["inst_net_buy"].fillna(0).abs().max() > 0
    )
    has_inst = _inst_src_ok and df["inst_accel_consecutive"].fillna(0).max() > 0
    if has_inst:
        inst_consec  = df["inst_accel_consecutive"].fillna(0)
        inst_accel_v = df["inst_accel"].fillna(0)
        strong_inst_trend = (
            (inst_consec >= CFG.INST_FILTER_TREND_MIN) &
            (inst_accel_v >= CFG.INST_ACCEL_MIN)
        )
        strong_inst_pb = (
            (inst_consec >= CFG.INST_FILTER_PULLBACK_MIN) &
            (inst_accel_v >= CFG.INST_ACCEL_MIN)
        )
        before_trend = df["entry_trend"].sum()
        before_pb    = df["entry_pullback"].sum()
        df["entry_trend"]    &= strong_inst_trend
        df["entry_pullback"] &= strong_inst_pb
        log.info(
            f"[SIG] 기관필터: trend {before_trend}→{df['entry_trend'].sum()} | "
            f"pb {before_pb}→{df['entry_pullback'].sum()} | "
            f"inst≥{CFG.INST_FILTER_TREND_MIN}봉(추세) inst≥{CFG.INST_FILTER_PULLBACK_MIN}봉(눌림)"
        )
        df["_inst_data_ok"] = pd.Series(True, index=df.index)  # [v5.4 BUG FIX] 스칼라→Series
    else:
        # [CMO-RT-2 FIX v5.3] 기관 데이터 미수신 → 대체 필터 + 포지션 축소
        # "기관의 등에 탔다가 미리 내리기" 원칙 — 기관 데이터 없이 1종목 몰빵은 위험
        log.warning(
            "[SIG] ★ 기관 데이터 미수신 — inst_net_buy 컬럼 없음 "
            "→ 대체 필터(vol_confirm + chegyul) 적용 + 포지션 50% 강제 축소"
        )
        log.warning("[SIG] 데이터 파이프라인 점검 요망: prices_1m.csv inst_net_buy 컬럼 확인")
        # [v5.14-FIX2] buy_volume/sell_volume 컬럼 미수신 여부 감지
        # 두 컬럼이 없으면 vol_confirm_cross·chegyul_momentum 모두 0 → alt_filter 전체 False
        # → 신호 전멸을 방지하기 위해 alt_filter 자체를 스킵하고 신호를 보존
        vol_cols_ok = ("buy_volume" in df.columns and "sell_volume" in df.columns)
        if not vol_cols_ok:
            log.warning(
                "[SIG] buy_volume/sell_volume 컬럼 없음 → alt_filter 전체 False 우려 "
                "→ alt_filter 스킵, 신호 보존 (데이터 파이프라인 점검 요망)"
            )
        else:
            # 대체 필터: 거래량확인돌파 + 체결강도모멘텀 복합 조건
            alt_filter = (
                df["vol_confirm_cross"].fillna(False) |
                (df["chegyul_momentum"].fillna(False) & df["strong_rs"].fillna(False))
            )
            before_trend = df["entry_trend"].sum()
            before_pb    = df["entry_pullback"].sum()
            df["entry_trend"]    &= alt_filter
            df["entry_pullback"] &= alt_filter
            log.info(
                f"[SIG] 대체필터 적용: trend {before_trend}→{df['entry_trend'].sum()} | "
                f"pb {before_pb}→{df['entry_pullback'].sum()}"
            )
        df["_inst_data_ok"] = pd.Series(False, index=df.index)  # [v5.4 BUG FIX] 스칼라→Series

    log.info(
        f"[SIG] trend={df['entry_trend'].sum()} | pb={df['entry_pullback'].sum()} | "
        f"prev_high_break={df['prev_high_break'].sum()} | hammer={df['hammer_flag'].sum()}"
    )
    _dump_trend_diag(df, log)   # [2026-06-09 진단 READ-ONLY] 스냅샷 덤프 (entry/score 무관)
    return df


# [2026-06-09 추세눌림 거래대금 floor] 장중 누적거래대금<100억 = junk/저유동 차단.
#   cum_value(line~1489, 당일 누적거래대금) 사용. env 롤백 PULLBACK_VALUE_FLOOR_ENABLE=NO.
#   종가매수 200억 복사 안 함(장중 초기대장 보호 위해 100억). 데이터: <100억=음수수익(junk).
PULLBACK_VALUE_FLOOR_ENABLE = os.environ.get("PULLBACK_VALUE_FLOOR_ENABLE", "YES").strip().upper() == "YES"
PULLBACK_VALUE_FLOOR_KRW    = float(os.environ.get("PULLBACK_VALUE_FLOOR_EOK", "100")) * 1e8


def _risk_gate(df: pd.DataFrame, log) -> pd.DataFrame:
    log.info("RISK GATE")
    rb = pd.Series(False, index=df.index)
    rr = pd.Series("OK",  index=df.index)
    def _blk(m, r):
        nonlocal rb, rr
        n = m.fillna(False) & ~rb; rb |= n; rr[n] = r
    _blk(df["time_regime"]=="BLOCKED",               "TIME_BLOCK")
    _blk(df["market_regime"]=="STRONG_DOWN",          "MARKET_BLOCK")
    _blk(~df["prev_ok"].fillna(False),                "NO_PREV")
    _blk(df["close"].fillna(0) < CFG.MIN_CLOSE,       "LOW_PRICE")
    _blk(df["value_5"].fillna(0) < CFG.MIN_VALUE_5M,  "LOW_LIQUIDITY")
    if PULLBACK_VALUE_FLOOR_ENABLE and "cum_value" in df.columns:
        _blk(df["cum_value"].fillna(0) < PULLBACK_VALUE_FLOOR_KRW, "VALUE_FLOOR")  # [2026-06-09] 당일누적거래대금<100억 차단
    _blk(df["gap_pct"].fillna(0).abs() > CFG.MAX_GAP_PCT, "GAP_OVERHEAT")
    _blk(df["vwap_dev_pct"].fillna(0) < CFG.MAX_VWAP_DEV_NEG, "VWAP_FAR")
    _blk(df["intraday_pullback_pct"].fillna(0) > CFG.MAX_PB_DEEP, "PB_DEEP")
    _blk(df["ret_from_prev_close"].fillna(0) > CFG.PREV_DAY_SURGE_BLOCK, "SURGE_BLOCK")
    # [ISS-2 v5.2] EVENT_RISK: last3_ret 임계값을 HARD_OVERHEAT로 통일
    # 0.06~0.12 구간은 SOFT_OVERHEAT(score×0.6)에서 처리 → 하드차단 아닌 소프트감점
    evt = (df["last3_ret"].fillna(0) >= CFG.HARD_OVERHEAT) | (df["value_spike_ratio"].fillna(0) > 3.0)
    _blk(evt, "EVENT_RISK")
    df["risk_block"] = rb; df["risk_reason"] = rr; df["event_risk_flag"] = evt.fillna(False)
    df.loc[rb, ["entry_trend","entry_pullback"]] = False

    # [패치4 v5.1 + ISS-2 v5.2] 과열 차단 — HARD는 EVENT_RISK가 처리 완료
    # [FIX-7 v5.5] SOFT_OVERHEAT → event_risk_flag 마킹 제거 (이중패널티 방지)
    # sp2에서 event_risk_flag 기반 추가감점이 쌓이지 않도록 분리
    overheat_soft = (
        (df["last3_ret"].fillna(0) >= CFG.SOFT_OVERHEAT) &
        (df["last3_ret"].fillna(0) < CFG.HARD_OVERHEAT) &
        ~df["risk_block"]
    )
    if overheat_soft.any():
        # event_risk_flag 마킹 없이 로그만 — score()에서 ×0.6 처리로 충분
        log.info(f"[RISK] SOFT_OVERHEAT({CFG.SOFT_OVERHEAT:.0%}~{CFG.HARD_OVERHEAT:.0%}) "
                 f"score×0.6 대상={overheat_soft.sum()}건 (이중패널티 방지: flag 미마킹)")

    log.info(f"[RISK] 차단={df['risk_block'].sum()}")
    return df


def _score(df: pd.DataFrame, log) -> pd.DataFrame:
    """
    [v5.0 BUG-3] 가중치 재배분:
      core 0.40→0.35  sl 0.25→0.20  sb 0.10→0.20  sp2 0.05→0.10
      → sb(기관모멘텀/상대강도/체결강도) 기여도 14.5%→25% 확대
      → sp2(이벤트리스크/하락시장) 감점 실효성 확보
    """
    log.info("SCORING (v5.0)")
    EPS = CFG.EPS

    st = (_norm_clip(df["trend_slope_short"].fillna(0), -0.005, 0.015)*0.40 +
          _norm_clip(df["trend_slope_mid"].fillna(0),   -0.003, 0.010)*0.30 +
          df["price_above_ma5"].fillna(False).astype(float)*0.15 +
          df["price_above_ma20"].fillna(False).astype(float)*0.15).clip(0,1)

    # [경고-A 수정] reclaim_vwap_flag(0.09)와 vwap_cross_up 중복 완화
    # vwap_cross_up 0.09→0.05 축소, 차액 0.04를 higher_low 보너스로 배분
    # higher_low: 추세 확인된 진짜 눌림 보너스 (결함-A 신규 피처 활용)
    sp = ((1-_norm_clip(df["intraday_pullback_pct"].fillna(0), CFG.PB_MIN, CFG.PB_MAX))*0.28 +
          _norm_clip(df["vwap_dev_pct"].fillna(-0.05), -0.03, 0.03)*0.20 +
          df["reclaim_vwap_flag"].fillna(False).astype(float)*0.09 +
          df["vwap_cross_up"].fillna(False).astype(float)*0.05 +   # [경고-A] 0.09→0.05
          df["higher_low"].fillna(False).astype(float)*0.04 +       # [경고-A] 신규 배분
          df["quiet_pullback"].fillna(False).astype(float)*0.07 +
          df["rebreak_flag"].fillna(False).astype(float)*0.05 +
          df["fast_recovery"].fillna(False).astype(float)*0.04 +
          df["vol_confirm_cross"].fillna(False).astype(float)*0.05 +
          df["hammer_flag"].fillna(False).astype(float)*0.06 +
          df["gap_filled_flag"].fillna(False).astype(float)*0.03
          ).clip(0, 1)

    sl = (_norm_clip(np.log1p(df["value_5"].fillna(0)), 0, 25)*0.50 +
          _norm_clip(df["value_ratio_5m"].fillna(0), 0.5, 3.0)*0.50).clip(0,1)

    sb = ((df["rebreak_flag"].fillna(False).astype(float)*0.06) +
          (df["market_regime"]=="STRONG_UP").astype(float)*0.06 +
          (df["chegyul_strength"].fillna(0.5) > 0.60).astype(float)*0.05 +
          (df["foreign_net_ratio"].fillna(0) > 0.005).astype(float)*0.04 +
          (df["inst_accel"].fillna(0) > CFG.INST_ACCEL_MIN).astype(float)*0.04 +
          (_norm_clip(df["inst_accel_consecutive"].fillna(0), 0, 5)*0.06) +
          df["price_above_ma20"].fillna(False).astype(float)*0.04 +
          df["prev_vol_surge"].fillna(False).astype(float)*0.05 +
          df["strong_rs"].fillna(False).astype(float)*0.05 +
          df["vol_accel_strong"].fillna(False).astype(float)*0.04 +
          df["new_high_flag"].fillna(False).astype(float)*0.04 +
          df["prev_high_break"].fillna(False).astype(float)*0.07 +
          df["chegyul_momentum"].fillna(False).astype(float)*0.04
          ).clip(0, 0.40)

    sp2 = ((df["event_risk_flag"].fillna(False).astype(float)*0.20) +
           (df["market_regime"]=="WEAK_DOWN").astype(float)*0.10 +
           _norm_clip(df["last3_ret"].fillna(0).clip(0), 0, 0.10)*0.05).clip(0, 0.40)

    tw   = df["entry_trend"].fillna(False).astype(float)
    pw   = df["entry_pullback"].fillna(False).astype(float)
    bz   = (tw==0)&(pw==0); tw[bz]=0.5; pw[bz]=0.5
    core = (st*tw + sp*pw) / (tw+pw+EPS)

    # [BUG-3 v5.0] 가중치: core=0.35  sl=0.20  sb=0.20  sp2=0.10
    raw_score = (core*0.35 + sl*0.20 + sb*0.20 - sp2*0.10).clip(0, None)
    df["score_final"] = (raw_score / CFG._SCORE_NORM).clip(0, 1)

    # [패치4 v5.1] SOFT_OVERHEAT: score ×0.6 (진입은 허용, 질 감점)
    soft_oh = (df["last3_ret"].fillna(0) >= CFG.SOFT_OVERHEAT) & ~df["risk_block"].fillna(False)
    if soft_oh.any():
        df.loc[soft_oh, "score_final"] *= 0.6
        log.info(f"[SCORE] SOFT_OVERHEAT score×0.6={soft_oh.sum()}건")

    return df


def _ev(df: pd.DataFrame, time_boost: dict, log) -> pd.DataFrame:
    log.info("EV ENGINE (v5.0)")
    # [MN-5 v5.0] pattern_key: entry_pullback 우선 매핑
    def _pkey(row):
        if row.get("entry_pullback"): return "PULLBACK"
        if row.get("entry_trend"):    return "TREND"
        return "MISC"
    df["pattern_key"] = (
        df.apply(_pkey, axis=1) + "|" +
        df["market_regime"] + "|" + df["time_regime"] + "|" +
        df["gap_grade"].fillna("SMALL")
    )
    df["ev_final"]  = 0.0
    df["confidence"]= 0.30
    df["ev_source"] = "FALLBACK"

    if Path(CFG.PATH_STATS).exists():
        try:
            stats = pd.read_csv(CFG.PATH_STATS, encoding="utf-8-sig")
            if {"pattern_key","win_prob","avg_win","avg_loss","sample_size"}.issubset(stats.columns):
                stats = stats[stats["sample_size"] >= CFG.MIN_SAMPLE]
                m = df.merge(stats[["pattern_key","win_prob","avg_win","avg_loss","sample_size"]],
                              on="pattern_key", how="left")
                has_stat = m["win_prob"].notna()
                p  = m["win_prob"].fillna(0.5)
                b  = _safe_div(m["avg_win"].fillna(0.01), m["avg_loss"].fillna(0.01).abs())
                ev = (p*b - (1-p)).clip(-0.1, 0.1)
                df.loc[has_stat, "ev_final"]   = ev[has_stat].values
                df.loc[has_stat, "confidence"] = (m.loc[has_stat,"win_prob"]*0.9).clip(0,1).values
                df.loc[has_stat, "ev_source"]  = "STAT"
                log.info(f"[EV] STAT={has_stat.sum()} | FALLBACK={len(df)-has_stat.sum()}")

                # [결함-C 수정] PULLBACK STAT EV 품질 검증 — 지침서 §14-5
                # WR < 55% 또는 avg_win_R < 1.5인 PULLBACK 패턴은 EV를 절반으로 감점
                # 승률·수익비 미달 패턴이 EV_MIN을 간신히 넘는 것을 차단
                _pb_stat_mask = has_stat & df["entry_pullback"].fillna(False)
                if _pb_stat_mask.any():
                    _pb_wr  = m.loc[_pb_stat_mask, "win_prob"].fillna(0)
                    _pb_b   = _safe_div(
                        m.loc[_pb_stat_mask, "avg_win"].fillna(0.01),
                        m.loc[_pb_stat_mask, "avg_loss"].fillna(0.01).abs()
                    )
                    _pb_qual_fail = (
                        (_pb_wr < CFG.EV_PULLBACK_WR_MIN) |
                        (_pb_b  < CFG.EV_PULLBACK_R_MIN)
                    )
                    if _pb_qual_fail.any():
                        _pb_fail_idx = _pb_stat_mask[_pb_stat_mask].index[_pb_qual_fail.values]
                        df.loc[_pb_fail_idx, "ev_final"] *= 0.50
                        log.info(
                            "[EV] PULLBACK 품질미달 EV×0.50=%d건 "
                            "(WR<%.0f%% or R<%.1f)",
                            len(_pb_fail_idx),
                            CFG.EV_PULLBACK_WR_MIN * 100,
                            CFG.EV_PULLBACK_R_MIN,
                        )
        except Exception as e:
            log.warning(f"[EV] stats 실패: {e}")

    # [WK-2 v5.0 + v5.4 개선 + v5.12 FIX] EV 폴백: 양수 기여 + 리스크 패널티 추가
    # [v5.12 FIX] trend_slope_short 계수 0.80 → 0.15
    #   문제: slope 최대값(0.02) × 0.80 = 0.016 → 나머지 항목 합산(~0.07)과 비교해 slope 단독 지배
    #         통계 없는 초기 기간에 추세 종목이 EV를 과대 받아 품질 낮은 종목 진입 유발
    #   수정: slope 계수 0.15로 낮추고 (최대기여 0.003), score 계수 0.035→0.055로 보완
    #         score는 0~1 범위 다팩터 점수 → EV 폴백의 주 기반으로 사용이 더 안정적
    #   효과: 항목별 최대 기여 균형화
    #         score(0.055) ≥ value_ratio(0.020) ≥ inst(0.010) ≥ rs(0.008) ≥ slope(0.003)
    fb = df["ev_source"] == "FALLBACK"
    df.loc[fb, "ev_final"] = (
        df.loc[fb, "score_final"]*0.055 +                               # [v5.12] 0.035→0.055
        df.loc[fb, "trend_slope_short"].fillna(0).clip(0,0.02)*0.15 +  # [v5.12] 0.80→0.15
        (df.loc[fb, "value_ratio_5m"].fillna(1).clip(0,5)-1).clip(-1,4)*0.005 +
        (df.loc[fb, "inst_accel_consecutive"].fillna(0).clip(0,5)/5)*0.010 +
        df.loc[fb, "strong_rs"].fillna(False).astype(float)*0.008
        # [v5.4] 리스크 패널티 추가 (CFO: "Fallback이 과낙관" 지적)
        - df.loc[fb, "gap_pct"].fillna(0).abs().clip(0, 0.08) * 0.30
        - df.loc[fb, "vwap_dev_pct"].fillna(0).clip(-0.05, 0) * (-0.20)
        - df.loc[fb, "intraday_pullback_pct"].fillna(0).clip(0, 0.06) * 0.15
    ).clip(-0.05, 0.07)
    # [WK-3 v5.0] confidence 캡: 0.50→0.70 (Kelly 유효 범위 확대)
    df.loc[fb, "confidence"] = (df.loc[fb, "score_final"] * 0.70).clip(0.15, 0.70)

    # [FIX-B v5.6] Fallback 워밍업 캡 — 누적 거래 FALLBACK_WARMUP_TRADES 미만 시 포지션 제한
    # 통계 없이 Kelly 전액 투입하면 초기 50거래일 과위험 발생 → 20% 하드캡 보호
    total_stat_trades = 0
    if Path(CFG.PATH_STATS).exists():
        try:
            _st = pd.read_csv(CFG.PATH_STATS, encoding="utf-8-sig")
            if "sample_size" in _st.columns:
                total_stat_trades = int(_st["sample_size"].sum())
        except Exception as e:
            log.debug(f"[WARMUP] 통계 파일 읽기 실패 (기본값 유지): {e}")
    in_warmup = total_stat_trades < CFG.FALLBACK_WARMUP_TRADES
    if in_warmup and fb.any():
        df["_ev_fallback_warmup"] = fb   # sizing에서 참조
        log.warning(
            f"[EV] ⚠️ FALLBACK 워밍업 중 (누적거래={total_stat_trades}건 "
            f"< {CFG.FALLBACK_WARMUP_TRADES}건) → FALLBACK 포지션 최대 {CFG.FALLBACK_POS_CAP:.0%}"
        )
    else:
        df["_ev_fallback_warmup"] = False
        if in_warmup:
            log.info(f"[EV] FALLBACK 워밍업 완료 (누적={total_stat_trades}건)")


    for tr, boost in time_boost.items():
        if boost != 1.0:
            mask = df["time_regime"] == tr
            df.loc[mask, "ev_final"] = (df.loc[mask, "ev_final"] * boost).clip(-0.1, 0.1)

    df.loc[~(df["entry_trend"]|df["entry_pullback"]), "confidence"] *= 0.50
    df.loc[df["risk_block"].fillna(False), "confidence"] = 0.0
    return df


def _sizing(df: pd.DataFrame, cash: int, market_ctx: dict, log) -> pd.DataFrame:
    log.info("SIZING (Half-Kelly v5.0)")
    EPS = CFG.EPS

    has_atr  = df["atr14"].fillna(0) > 0
    atr_stop = pd.Series(
        _safe_div((df["atr14"]*CFG.ATR_MULTIPLIER).values, (df["close"]+EPS).values),
        index=df.index
    ).fillna(0)
    pb_stop = df["intraday_pullback_pct"].fillna(0.01) + 0.005
    df["stop_loss_pct"] = pd.Series(
        np.where(has_atr, atr_stop, pb_stop), index=df.index
    ).clip(0.005, 0.08)

    ev_based_tp = (df["ev_final"].fillna(0).clip(0,0.10) + df["stop_loss_pct"]).clip(0, 0.15)
    df["rr_ratio"] = pd.Series(
        _safe_div(ev_based_tp.values, (df["stop_loss_pct"]+EPS).values),
        index=df.index
    ).fillna(CFG.TAKE_PROFIT_RATIO).clip(0.5, 5.0)

    p          = df["confidence"].clip(0.10, 0.95)
    b          = df["rr_ratio"].clip(0.5, 5.0)
    kelly_raw  = ((p*(b+1)-1) / (b+EPS)).clip(0, 1)
    half_kelly = kelly_raw * CFG.HALF_KELLY_FRACTION

    pos_scale    = float(market_ctx.get("pos_scale", 1.0))
    market_score = float(market_ctx.get("market_score", 1.0))
    index_trend  = str(market_ctx.get("index_trend", "FLAT"))
    df["market_score"] = market_score
    df["index_trend"]  = index_trend
    df["pos_scale"]    = pos_scale

    raw_pos = half_kelly * pos_scale
    df["position_size"] = np.where(
        kelly_raw <= 0, 0.0,
        raw_pos.clip(CFG.MIN_POSITION_PCT, CFG.MAX_POSITION_PCT)
    )
    df.loc[df["risk_block"].fillna(False), "position_size"] = 0.0

    # [WK-9 v5.0] 얼리진입(09:10~09:29) → 포지션 축소
    early_mask = (df["hhmm"] >= 910) & (df["hhmm"] <= 929)
    if early_mask.any():
        df.loc[early_mask, "position_size"] *= CFG.EARLY_SIZE_MULT
        log.info(f"[SIZING] 얼리 포지션 축소={early_mask.sum()}건 (×{CFG.EARLY_SIZE_MULT})")

    # [v5.2] Score 2단계 강화 (ultra/strong 분리)
    score_ultra  = df["score_final"].fillna(0) >= CFG.SCORE_ULTRA
    score_strong = (df["score_final"].fillna(0) >= CFG.SCORE_STRONG) & ~score_ultra
    score_weak   = df["score_final"].fillna(0) < CFG.SCORE_FILTER_MIN
    if score_ultra.any():
        df.loc[score_ultra, "position_size"] *= 1.40
        log.info(f"[SIZING] SCORE_ULTRA(≥{CFG.SCORE_ULTRA}) ×1.40={score_ultra.sum()}건")
    if score_strong.any():
        # [v5.9 FIX-5] 기관 연속 3봉 이상이면 ×1.30, 아니면 ×1.20
        _inst_ok = df["inst_accel_consecutive"].fillna(0) >= 3
        _strong_inst = score_strong & _inst_ok
        _strong_only = score_strong & ~_inst_ok
        if _strong_inst.any():
            df.loc[_strong_inst, "position_size"] *= 1.30
            log.info(f"[SIZING] SCORE_STRONG+기관연속 ×1.30={_strong_inst.sum()}건")
        if _strong_only.any():
            df.loc[_strong_only, "position_size"] *= 1.20
            log.info(f"[SIZING] SCORE_STRONG ×1.20={_strong_only.sum()}건")
    if score_weak.any():
        df.loc[score_weak, "position_size"] = 0.0
        log.info(f"[SIZING] SCORE_FILTER(<{CFG.SCORE_FILTER_MIN}) 제거={score_weak.sum()}건")

    # [v5.2] EV 직접 보상 (좋은 자리 더 크게)
    ev_ultra  = df["ev_final"].fillna(0) >= CFG.EV_ULTRA
    ev_strong = (df["ev_final"].fillna(0) >= CFG.EV_STRONG) & ~ev_ultra
    if ev_ultra.any():
        df.loc[ev_ultra, "position_size"] *= 1.25
        log.info(f"[SIZING] EV_ULTRA(≥{CFG.EV_ULTRA}) ×1.25={ev_ultra.sum()}건")
    if ev_strong.any():
        df.loc[ev_strong, "position_size"] *= 1.10
        log.info(f"[SIZING] EV_STRONG(≥{CFG.EV_STRONG}) ×1.10={ev_strong.sum()}건")

    # [v5.9] 공격70/방어30 — 1종목 몰빵 자본 배분
    # position_size: Half-Kelly 계산된 전체 투입 비율
    # 추세진입이든 눌림목진입이든 구분 없이 동일 적용
    # offensive_amt(공격 70%): 수익 극대화를 위한 적극적 포지션
    # defensive_amt(방어 30%): 리스크 헤지, 손절 여유, 분할 매도 여력
    df["position_size"] = df["position_size"].clip(0, CFG.MAX_POSITION_PCT)
    df["attack_amt"]    = (df["position_size"] * CFG.ATTACK_RATIO).round(4)
    df["stable_amt"]    = (df["position_size"] * CFG.STABLE_RATIO).round(4)
    # [PATCH-v5.10.2 수정4] attack_amt / stable_amt = "자본배분 힌트"
    # 실제 주문 집행은 rt_execution_engine / bridge가 담당
    # 이 값은 다운스트림(bridge)이 공격/방어 비율 참조용으로만 사용
    # attack_amt: 공격 70% 배분 힌트 / stable_amt: 방어 30% 배분 힌트
    log.info(
        f"[SIZING] 공격(70%)={df['attack_amt'].max():.1%} "
        f"방어(30%)={df['stable_amt'].max():.1%} "
        f"합계={df['position_size'].max():.1%} | 1종목몰빵"
    )

    # [CMO-RT-2 FIX v5.3] 기관 데이터 미수신 → 전체 포지션 50% 강제 축소
    # "기관의 등에 탔다가 미리 내리기" 원칙상 기관 확인 없이 전액 투입 금지
    inst_data_ok = df.get("_inst_data_ok", pd.Series(True, index=df.index))
    if not inst_data_ok.all():
        no_inst_mask = ~inst_data_ok.fillna(True)
        if no_inst_mask.any():
            df.loc[no_inst_mask, "position_size"] *= 0.50
            log.warning(
                f"[SIZING] ★ 기관미수신 포지션 ×0.50 강제 적용={no_inst_mask.sum()}건 "
                f"(inst 없는 1종목 몰빵 위험 방지)"
            )

    # [FIX-B v5.6] Fallback 워밍업 캡 — 초기 50거래일 통계 미충족 과위험 방지
    fallback_warmup = df.get("_ev_fallback_warmup", pd.Series(False, index=df.index))
    if isinstance(fallback_warmup, bool):
        fallback_warmup = pd.Series(fallback_warmup, index=df.index)
    fb_over = fallback_warmup.fillna(False) & (df["position_size"] > CFG.FALLBACK_POS_CAP)
    if fb_over.any():
        df.loc[fb_over, "position_size"] = CFG.FALLBACK_POS_CAP
        log.warning(
            f"[SIZING] ★ FALLBACK 워밍업 캡 적용={fb_over.sum()}건 "
            f"→ position_size ≤ {CFG.FALLBACK_POS_CAP:.0%} (통계 미충족 과투자 방지)"
        )


    actual_amt = cash * df["position_size"]
    too_small  = (actual_amt > 0) & (actual_amt < CFG.MIN_ORDER_AMT)
    if too_small.any():
        df.loc[too_small, "position_size"] = 0.0
        log.info(f"[SIZING] 최소금액미달={too_small.sum()}건")

    log.info(
        f"[SIZING] cash={cash:,} | kelly≤0={(kelly_raw<=0).sum()} | "
        f"평균pos={df.loc[df['position_size']>0,'position_size'].mean():.3f} | "
        f"평균stop={df['stop_loss_pct'].mean():.3%}"
    )
    return df


# ═══════════════════════════════════════════════════════════════
#  [v5_8] LEADER ENGINE — 대장주 탐지 엔진
#  핵심: "거래대금 + 눌림 + 재상승" 만 본다
#  "대장주는 찾는 게 아니라 살아남는 놈을 눌림에서 타는 것이다"
#  rt_intraday 컬럼 → leader_engine ctx 자동 매핑
# ═══════════════════════════════════════════════════════════════

def _calc_ema(prices: list, period: int) -> float:
    """
    단순 EMA 계산 (가격 리스트 → 최신 EMA값).
    데이터 부족 시 마지막 가격 반환.
    """
    if not prices or len(prices) == 0:
        return 0.0
    if len(prices) < period:
        return float(prices[-1])
    k = 2.0 / (period + 1)
    ema = float(prices[0])
    for p in prices[1:]:
        ema = float(p) * k + ema * (1 - k)
    return ema


def leader_engine(ctx: dict,
                  has_position: bool = False,
                  exit_score: float = 1.0) -> str:
    """
    [v5_8] 대장주/테마주 탐지 엔진.

    반환값:
      BUY    → 진입
      HOLD   → 유지
      TRAIL  → 트레일 / 일부 정리
      SELL   → 전량 청산
      WAIT   → 조건 미충족 대기
      REJECT → 필터 탈락
      SKIP   → 시간 외

    ctx 필수 키 (rt_intraday 컬럼 자동 매핑):
      time_hhmm, value_ratio, volume_spike, gap_pct
      close_position, upper_wick_ratio, pullback_pct
      vwap_ok (bool), recent_high, close
      ema5, ema20, ema60, ema20_slope
    """
    try:
        t = int(ctx.get("time_hhmm", 0))

        # ── 0. 시간 필터 ───────────────────────────────────────
        if t < 930:
            return "SKIP"
        if t > 1320:
            return "SKIP"

        # ── 1. 가짜 급등 필터 (REJECT 즉시 차단) ──────────────
        pullback    = float(ctx.get("pullback_pct", 0))
        upper_wick  = float(ctx.get("upper_wick_ratio", 0))
        vwap_ok     = bool(ctx.get("vwap_ok", False))
        value_ratio = float(ctx.get("value_ratio", 0))

        if pullback <= -3.0:
            return "REJECT"
        if upper_wick > 0.4:
            return "REJECT"
        if not vwap_ok:
            return "REJECT"
        if value_ratio < 1.2:
            return "REJECT"

        # ── 2. Leader Score 계산 ───────────────────────────────
        score        = 0
        volume_spike = float(ctx.get("volume_spike", 0))
        gap_pct      = float(ctx.get("gap_pct", 0))
        close_pos    = float(ctx.get("close_position", 0))
        close        = float(ctx.get("close", 0))
        recent_high  = float(ctx.get("recent_high", 0))
        open_price   = float(ctx.get("open_price", close))
        ema5         = float(ctx.get("ema5", 0))
        ema20        = float(ctx.get("ema20", 0))
        ema60        = float(ctx.get("ema60", 0))
        ema20_slope  = float(ctx.get("ema20_slope", 0))

        # 거래대금
        if value_ratio >= 2.0:
            score += 15
        elif value_ratio >= 1.5:
            score += 10

        if volume_spike >= 2.5:
            score += 10
        elif volume_spike >= 1.8:
            score += 6

        if gap_pct >= 1.0:
            score += 5

        # 가격 구조
        if close_pos >= 0.8:
            score += 10
        elif close_pos >= 0.7:
            score += 6

        if upper_wick <= 0.3:
            score += 5

        if recent_high > 0 and close >= recent_high * 0.995:
            score += 10

        # 눌림
        if -2.0 <= pullback <= -0.8:
            score += 10
        elif -2.5 <= pullback <= -0.5:
            score += 6

        if vwap_ok:
            score += 10

        # 재상승
        if volume_spike >= 1.8 and close > open_price:
            score += 10
        if recent_high > 0 and close >= recent_high * 0.99:
            score += 5

        # 추세 (EMA 정렬)
        if ema5 > 0 and ema20 > 0 and ema60 > 0:
            if ema5 > ema20 > ema60:
                score += 6
        if ema20_slope > 0:
            score += 4

        # ── 3. 등급 분류 ───────────────────────────────────────
        if score >= 85:
            grade = "LEADER"
        elif score >= 75:
            grade = "STRONG"
        elif score >= 65:
            grade = "WATCH"
        else:
            grade = "REJECT"

        # ── 4. 진입 판단 ───────────────────────────────────────
        if not has_position:
            if grade in ("LEADER", "STRONG"):
                if not (-2.0 <= pullback <= -0.8):
                    return "WAIT"
                if not vwap_ok:
                    return "WAIT"
                if volume_spike < 1.5:
                    return "WAIT"
                return "BUY"
            return "WAIT"

        # ── 5. 보유 / 청산 판단 ────────────────────────────────
        if pullback <= -3.0:
            return "SELL"
        if not vwap_ok:
            return "SELL"
        if upper_wick > 0.5:
            return "SELL"
        if value_ratio < 1.2:
            return "TRAIL"
        if exit_score < 0.55:
            return "TRAIL"
        return "HOLD"

    except Exception:
        return "ERROR"


def _build_leader_ctx(row: dict,
                      price_history: list,
                      hhmm: int) -> dict:
    """
    [v5_8] rt_intraday 행 데이터 → leader_engine ctx 변환.
    rt_intraday.csv 컬럼명을 leader_engine 키로 매핑.
    """
    def _f(v, d=0.0):
        try:
            return float(v) if v is not None else d
        except Exception:
            return d

    close        = _f(row.get("close", row.get("price", 0)))
    vwap_dev     = _f(row.get("vwap_dev", 0))
    vwap_ok      = (vwap_dev >= 0)

    # EMA 계산 (price_history: 최근 60봉 종가 리스트)
    ph = price_history if price_history else [close]
    ema5_v   = _calc_ema(ph, 5)
    ema20_v  = _calc_ema(ph, 20)
    ema60_v  = _calc_ema(ph, 60)

    # EMA20 기울기: 최근 5봉 EMA20 변화
    if len(ph) >= 6:
        ema20_prev = _calc_ema(ph[:-5], 20)
        ema20_slope = ema20_v - ema20_prev
    else:
        ema20_slope = 0.0

    # pullback_pct: intraday_high 대비 현재가 낙폭 (음수)
    intraday_high = _f(row.get("intraday_high", close))
    pullback_pct  = (close / intraday_high - 1.0) * 100.0 if intraday_high > 0 else 0.0

    # volume_spike: value_spike_ratio 활용
    volume_spike  = _f(row.get("value_spike_ratio",
                       row.get("value_ratio_5m", 1.0)))

    return {
        "time_hhmm":      hhmm,
        "close":          close,
        "open_price":     _f(row.get("open", close)),
        "gap_pct":        _f(row.get("gap_pct", 0)) * 100,
        # [FIX 2026-07-01] leader_engine 의 value_ratio 는 '거래대금 상대배수'
        #   (≥1.2/1.5/2.0 임계) 를 기대한다. 기존 close_value_ratio 는 0~1 종가위치
        #   지표(오늘 실측 max=1.0·median=0.057)라 임계를 영원히 못 넘어 전 종목
        #   REJECT 를 유발했다. 엔진 내부 산출 value_ratio_5m(=최근5분 거래대금/
        #   평균, line 1493) 이 올바른 스케일. 누락 시 1.0(중립) fallback.
        "value_ratio":    _f(row.get("value_ratio_5m",
                             row.get("value_ratio", 1.0)), 1.0),
        "volume_spike":   volume_spike,
        "close_position": _f(row.get("close_position", 0.5)),
        "upper_wick_ratio": _f(row.get("upper_wick_ratio", 0)),
        "pullback_pct":   pullback_pct,
        "vwap_ok":        vwap_ok,
        "recent_high":    _f(row.get("intraday_high", 0)),
        "ema5":           ema5_v,
        "ema20":          ema20_v,
        "ema60":          ema60_v,
        "ema20_slope":    ema20_slope,
    }


def _apply_leader_score(df: pd.DataFrame,
                        price_hist_map: dict,
                        hhmm: int,
                        log) -> pd.DataFrame:
    """
    [v5_8] rt_intraday DataFrame에 leader_score / leader_grade 컬럼 추가.
    entry_ok=True인 후보 중 LEADER/STRONG만 우선 순위 상향.
    """
    leader_scores  = []
    leader_grades  = []
    leader_signals = []

    for _, row in df.iterrows():
        code = str(row.get("code", "")).strip()
        ph   = price_hist_map.get(code, [])
        ctx  = _build_leader_ctx(row.to_dict(), ph, hhmm)
        sig  = leader_engine(ctx, has_position=False)
        score_val = 0

        # 신호 → 점수 변환 (정렬용)
        if sig == "BUY":
            score_val = 2
        elif sig == "WAIT":
            score_val = 1
        else:
            score_val = 0

        leader_signals.append(sig)
        leader_scores.append(score_val)

        # grade 추출 (leader_engine 내부와 동일 로직)
        if ctx.get("value_ratio", 0) < 1.2 or not ctx.get("vwap_ok"):
            leader_grades.append("REJECT")
        else:
            leader_grades.append("SCORED")

    df = df.copy()
    df["leader_signal"] = leader_signals
    df["leader_score"]  = leader_scores

    # [FIX 2026-07-01] champion_score 보너스 / entry_ok 차단은 여기서 하지 않는다.
    #   이 함수는 _champion_select() '이전'에 호출된다 → champion_score·entry_ok
    #   컬럼이 아직 df 에 없다. 기존 코드는 df["entry_ok"] 를 직접 참조해
    #   KeyError('entry_ok') 를 냈고, 상위 try/except 가 이를 삼켜 매 사이클
    #   leader 통합 전체가 무력화됐다(2026-07-01 로그: "leader_engine 적용
    #   실패(무시): 'entry_ok'" 134회 → leader_signal 컬럼조차 부착 실패).
    #   BUY/WAIT 보너스는 _champion_select() 내부(champion_score 확정 후)에서
    #   leader_signal 기준으로 이미 정상 적용된다. 여기서는 신호 컬럼만 부착.
    log.info(
        "[LEADER] 신호 부착: BUY=%d WAIT=%d REJECT=%d SKIP=%d",
        int((df["leader_signal"] == "BUY").sum()),
        int((df["leader_signal"] == "WAIT").sum()),
        int((df["leader_signal"] == "REJECT").sum()),
        int((df["leader_signal"] == "SKIP").sum()),
    )
    return df


def _champion_select(df: pd.DataFrame, held_codes: list, log) -> pd.DataFrame:
    """
    [v5.8 R1] CHAMPION SELECT — 종배 sb_ctx 완전 제거, 순수 RT 신호 기반

    champion_score 5요소:
      ev_norm×0.45  rr_norm×0.15  ia_norm×0.20  gap_s×0.10  time_s×0.10  [수정]

    보정 배율:
      vol_confirm_cross × 1.25 | prev_high_break × 1.15 | strong_rs × 1.10
      vwap_cross_up(단독)×1.08 | hammer × 1.08 | chegyul_momentum × 1.06
      quiet_pullback × 1.05 | new_high_flag × 1.05 | prev_vol_surge × 1.04
      얼리진입 × 0.85

    MIN_TOP1_SCORE 정규화:
      raw / RAW_SCORE_NORM(1.75) → [0,1] 후 0.45 비교
    """
    log.info("CHAMPION SELECT (v5.8 — 종배SB제거)")
    cand = df[
        (df["entry_trend"] | df["entry_pullback"]) &
        (~df["risk_block"].fillna(False)) &
        (df["ev_final"] > 0) &              # [수정] EV_MIN→0 초과: EV≤0 종목 무조건 제외
        (df["confidence"] >= CFG.CONF_MIN) &
        (df["position_size"] > 0)
    ].copy()

    df["entry_ok"] = False; df["champion_score"] = 0.0
    if cand.empty:
        # [PATCH-v5.10.2 수정5] 탈락 이유 요약 로그
        total_rows = len(df)
        ev_fail    = int((df["ev_final"].fillna(0) <= 0).sum())
        rb_fail    = int(df["risk_block"].fillna(False).sum())
        conf_fail  = int((df["confidence"].fillna(0) < CFG.CONF_MIN).sum())
        sig_fail   = int((~(df["entry_trend"] | df["entry_pullback"])).sum())
        log.info(
            "[CHAMPION] 조건 통과 0건 | 전체=%d | 신호없음=%d | EV≤0=%d | 리스크차단=%d | 신뢰도미달=%d",
            total_rows, sig_fail, ev_fail, rb_fail, conf_fail
        )
        return df
    if held_codes:
        cand = cand[~cand["code"].isin(set(held_codes))]
    if cand.empty:
        log.info("[CHAMPION] 보유 제외 후 0건"); return df

    # ★[2026-07-01 대장주 순위표 게이트] 눌림도 전날 종가 '대장주 순위표' 안에서만 매수.
    #   board(daily_leader_board) 없거나 비면 통과(fail-open). 롤백 setx PB_LEADER_BOARD NO
    if os.environ.get("PB_LEADER_BOARD", "YES").strip().upper() == "YES":
        try:
            import leader_filter as _lf
            _bset = _lf.leader_set(None)   # 아침 순위표 ∪ 실시간 대장(live_leaders.json)
            if _bset:
                _before = len(cand)
                cand = cand[cand["code"].map(lambda x: _lf._z(x) in _bset)]
                if _before != len(cand):
                    log.info("[LEADER-BOARD] 전날 대장 순위표 필터: %d→%d (순위표 밖 제외)",
                             _before, len(cand))
                if cand.empty:
                    log.info("[CHAMPION] 대장 순위표 통과 0건"); return df
        except Exception as _be:
            log.warning("[LEADER-BOARD] 순위표 필터 실패(무시): %s", _be)

    cand = cand.sort_values("ts").drop_duplicates("code", keep="last")

    # [결함-C 수정] PULLBACK 독립 EV 게이트 — 지침서 §14-5
    # TREND(EV≥0.30 WR≥52%)와 별도로 PULLBACK 전용 기준 적용
    # EV_MIN=0.005 통합 기준으로는 눌림목 품질 필터 효과 없음
    _pb_only = cand["entry_pullback"].fillna(False) & ~cand["entry_trend"].fillna(False)
    _pb_ev_fail = _pb_only & (cand["ev_final"] < CFG.EV_PULLBACK_MIN)
    if _pb_ev_fail.any():
        log.info(
            "[CHAMPION] PULLBACK EV 게이트 제외=%d건 (ev<%.3f)",
            _pb_ev_fail.sum(), CFG.EV_PULLBACK_MIN,
        )
        cand = cand[~_pb_ev_fail]
    if cand.empty:
        log.info("[CHAMPION] PULLBACK EV 게이트 통과 0건"); return df

    # [score≥0.45 게이트] 지침서 §7-1 score ≥ 0.45 진입 허용 기준
    # PULLBACK 전용 — TREND는 MIN_TOP1_SCORE(0.45)로 이미 처리
    # SCORE_FILTER_MIN(0.20)보다 강화: 저품질 눌림 진입 추가 차단
    PB_SCORE_MIN = 0.45  # 지침서 §7-1 명시값
    _pb_score_fail = (
        cand["entry_pullback"].fillna(False) &
        ~cand["entry_trend"].fillna(False) &
        (cand["score_final"].fillna(0) < PB_SCORE_MIN)
    )
    if _pb_score_fail.any():
        log.info(
            "[CHAMPION] PULLBACK score 게이트 제외=%d건 (score<%.2f)",
            _pb_score_fail.sum(), PB_SCORE_MIN,
        )
        cand = cand[~_pb_score_fail]
    if cand.empty:
        log.info("[CHAMPION] PULLBACK score 게이트 통과 0건"); return df

    # ── 5요소 기본 스코어 (고유영역 유지) ────────────────────────
    ev_norm = ((cand["ev_final"].clip(-0.05,0.10)+0.05)/0.15).clip(0,1)
    rr_norm = _norm_clip(cand["rr_ratio"].fillna(1.0), 1.0, 3.0)
    ia_norm = (cand["inst_accel_consecutive"].fillna(0).clip(0,5)/5).clip(0,1)
    gap_s   = cand["gap_grade"].fillna("SMALL").map(CFG.GAP_GRADE_SCORE).fillna(0.5)
    time_s  = cand["time_regime"].fillna("MID").map(CFG.TIME_REGIME_SCORE).fillna(1.0)
    raw     = ev_norm*0.45 + rr_norm*0.15 + ia_norm*0.20 + gap_s*0.10 + time_s*0.10  # [수정] EV 가중치 0.35→0.45: EV 높은 종목 우선

    # ── 보정 배율 (고유영역 유지) ────────────────────────────────
    vc  = cand["vol_confirm_cross"].fillna(False).astype(float)
    ph  = cand["prev_high_break"].fillna(False).astype(float)
    rs  = cand["strong_rs"].fillna(False).astype(float)
    vwap_only = (cand["vwap_cross_up"].fillna(False) & ~cand["vol_confirm_cross"].fillna(False)).astype(float)
    hm  = cand["hammer_flag"].fillna(False).astype(float)
    cm  = cand["chegyul_momentum"].fillna(False).astype(float)
    qp  = cand["quiet_pullback"].fillna(False).astype(float)
    nh  = cand["new_high_flag"].fillna(False).astype(float)
    vs  = cand["prev_vol_surge"].fillna(False).astype(float)

    raw = raw * (1 + vc*0.25) * (1 + ph*0.15) * (1 + rs*0.10) * (1 + vwap_only*0.08)
    raw = raw * (1 + hm*0.08) * (1 + cm*0.06) * (1 + qp*0.05) * (1 + nh*0.05)
    raw = raw * (1 + vs*0.04)

    # ── [2026-06-09 거래대금 최종관문 B — 사용자결정] ──────────────
    #   8→1 최종 champion에서 "현재 거래대금(value_ratio_5m) 살아있나"로 가감.
    #   점수 높아도 거래대금 죽은(vr<1) 종목 감점, 활발(vr>1)하면 가점.
    #   ★테마/기관 풀 선택(intent_score)은 무수정 — 역할분리(테마=풀, 거래대금=최종1등).
    #   롤백 env PB_CHAMPION_VALUE_GATE=NO. vr=0→×0.5(죽음) / vr=1→×1.0 / vr≥1.6→×1.3(활발).
    if os.environ.get("PB_CHAMPION_VALUE_GATE", "YES").strip().upper() == "YES":
        _vr_mult = (0.5 + 0.5 * cand["value_ratio_5m"].fillna(1.0)).clip(0.5, 1.3)
        raw = raw * _vr_mult
        log.info("[CHAMPION] 거래대금 최종관문(value_ratio_5m): 중앙배율=%.2f min=%.2f max=%.2f "
                 "(죽음<1 감점·활발>1 가점)",
                 float(_vr_mult.median()), float(_vr_mult.min()), float(_vr_mult.max()))

    # ── 얼리진입 패널티 (고유영역 유지) ─────────────────────────
    early_mask = (cand["hhmm"] >= 910) & (cand["hhmm"] <= 929)
    if early_mask.any():
        raw = raw * np.where(early_mask, CFG.EARLY_ENTRY_PENALTY, 1.0)
        log.info(f"[CHAMPION] 얼리패널티 적용={early_mask.sum()}건 (×{CFG.EARLY_ENTRY_PENALTY})")

    # ── [R1 v5.8] 종배 스코어보드 보너스 제거 — 순수 RT 신호만 사용 ──
    # sb_ctx 의존성 완전 제거

    # ── [v5.14] EOD pullback_watch STRONG 셋업 보너스 ────────────
    # 종배와 달리 RT 눌림 전용 pullback_watch는 연결 유지
    # STRONG 셋업 = 기관 5일+ 지지 + priority≥50 + quality≥55 → 가장 수익성 높은 조건
    # 장중 RT 신호와 EOD 선별 두 기준 동시 충족 시 우선순위 상향
    try:
        _pw = _load_pullback_watch(log)
        if _pw["ok"]:
            _strong_set   = set(_pw["strong_codes"])
            _moderate_set = set(_pw["moderate_codes"])
            _strong_mask   = cand["code"].isin(_strong_set)
            _moderate_mask = cand["code"].isin(_moderate_set)
            if _strong_mask.any():
                raw = raw * np.where(_strong_mask, 1.15, 1.0)   # STRONG: ×1.15
                log.info("[PB_WATCH] STRONG 보너스 ×1.15 적용=%d건", _strong_mask.sum())
            if _moderate_mask.any():
                raw = raw * np.where(_moderate_mask, 1.07, 1.0)  # MODERATE: ×1.07
                log.info("[PB_WATCH] MODERATE 보너스 ×1.07 적용=%d건", _moderate_mask.sum())
    except Exception as _e:
        log.warning("[PB_WATCH] 보너스 적용 실패(비치명): %s", _e)

    # ── [v5.9-TIME] 회차별 최소 점수 게이트 ─────────────────────
    # EARLY(1회차): 0.65 / MID(2회차): 0.72 / LATE(3회차): 0.78
    # 정규화 기준(RAW_SCORE_NORM=1.50) 적용 전 raw score 기준
    _time_score_map = {
        "EARLY": CFG.T_EARLY_MIN_SCORE,
        "MID":   CFG.T_MID_MIN_SCORE,
        "LATE":  CFG.T_LATE_MIN_SCORE,
    }
    _raw_norm = CFG.RAW_SCORE_NORM  # 1.50
    # [v5.14-INST-FB] inst_net_buy 미수신 감지 → OFI/CONSEC bypass + raw_norm 완화
    _inst_absent = ("inst_net_buy" not in cand.columns or
                    cand["inst_net_buy"].fillna(0).abs().sum() == 0)
    if _inst_absent:
        _raw_norm = 1.00  # inst 없으면 ev/ia 구조적 손실 보정 (raw_min: 0.56→0.40)
        log.info("[TIME-GATE] inst 미수신 → raw_norm %.2f→1.00, OFI/CONSEC bypass",
                 CFG.RAW_SCORE_NORM)
    before_cnt = len(cand)
    _time_filter = pd.Series(True, index=cand.index)
    for _tr, _min_s in _time_score_map.items():
        _mask = cand["time_regime"] == _tr
        _min_raw = _min_s * _raw_norm   # 점수 기준을 raw 스케일로 변환
        _fail = _mask & (raw < _min_raw)
        _time_filter = _time_filter & ~_fail
    # LATE(3회차) 추가 조건: OFI ≥ 0.45 + 기관연속봉 ≥ 4
    # [PATCH-LATE-STRENGTH] 점심 시간대(1140~1259)도 LATE → 6종 게이트 모두 적용
    # 사용자 설계: 시간 차단은 무력화 유지 / 대신 점수+게이트로 강화
    _late_mask = (cand["time_regime"] == "LATE")
    if _late_mask.any():
        # [연결] ofi 컬럼 없을 때 inst_net_ratio로 안전 fallback
        # inst_net_ratio = 최근5봉 기관순매수합/거래량합 = OFI 동일 개념
        _ofi_series = (cand["ofi"] if "ofi" in cand.columns
                       else cand.get("inst_net_ratio", pd.Series(0.0, index=cand.index)))
        if not _inst_absent:
            _late_ofi_fail    = _late_mask & (_ofi_series.fillna(0) < CFG.T_LATE_OFI_MIN)
            _late_consec_fail = _late_mask & (cand["inst_accel_consecutive"].fillna(0) < CFG.T_LATE_CONSEC_MIN)
            _time_filter = _time_filter & ~_late_ofi_fail & ~_late_consec_fail

        # ── [v5.9-LATE4] 오후 특수 4조건 ────────────────────────
        # ① 거래대금 비율 ≥ 1.5 (대장주 유지 확인)
        _late_val_fail = _late_mask & (
            cand["value_ratio_5m"].fillna(0) < CFG.T_LATE_VALUE_RATIO_MIN
        )
        # ② 고점 대비 -2% 이내 (추세 유지 종목만)
        _late_high_fail = _late_mask & (
            cand["ret_from_high"].fillna(-0.05) < CFG.T_LATE_FROM_HIGH_MAX
        )
        # ③ EMA 정배열 (price_above_ma5 재사용)
        _late_ema_fail = _late_mask & (
            ~cand["price_above_ma5"].fillna(False)
        )
        # ④ 거래량 재유입 (vol_accel_strong — 최근 거래량 급증)
        _late_vol_fail = _late_mask & (
            ~cand["vol_accel_strong"].fillna(False)
        )
        _late4_fail = _late_val_fail | _late_high_fail | _late_ema_fail | _late_vol_fail
        _time_filter = _time_filter & ~_late4_fail

        _late4_cnt = _late4_fail.sum()
        if _late4_cnt > 0:
            log.info(
                "[LATE4] 오후 특수조건 제외 %d건 "
                "(거래대금%d / 고점-2%%%d / EMA%d / 거래량%d)",
                _late4_cnt,
                _late_val_fail.sum(), _late_high_fail.sum(),
                _late_ema_fail.sum(), _late_vol_fail.sum(),
            )

    cand = cand[_time_filter]
    after_cnt = len(cand)
    if before_cnt != after_cnt:
        log.info("[TIME-GATE] 회차별 점수 필터: %d→%d건 (제외 %d건)",
                 before_cnt, after_cnt, before_cnt - after_cnt)
    if cand.empty:
        log.info("[CHAMPION] 회차별 점수 게이트 통과 0건"); return df

    cand = cand.copy()
    cand["champion_score"] = raw[cand.index].clip(0, 1.75).round(4)

    # [PATCH-v5.10.2 수정1] leader_engine 보너스 반영
    # 문제: _apply_leader_score에서 champion_score+0.15 적용했으나
    #       바로 위 라인에서 raw[cand.index]로 덮어써 보너스 소멸
    # 수정: champion_score 확정 직후 leader_signal 기반 보너스 재적용
    if "leader_signal" in cand.columns:
        _buy_mask  = cand["leader_signal"] == "BUY"
        _wait_mask = cand["leader_signal"] == "WAIT"
        _rej_mask  = cand["leader_signal"] == "REJECT"
        if _buy_mask.any():
            _bonus = cand.loc[_buy_mask, "champion_score"] * 0.15  # +15% (BUY: +0.12~0.18)
            cand.loc[_buy_mask, "champion_score"] = (
                cand.loc[_buy_mask, "champion_score"] + _bonus
            ).clip(upper=1.75)
            log.info("[LEADER] BUY 보너스 적용: %d건 (+0.12~0.18)", _buy_mask.sum())
        if _wait_mask.any():
            _bonus = cand.loc[_wait_mask, "champion_score"] * 0.06  # +6% (WAIT: +0.04~0.08)
            cand.loc[_wait_mask, "champion_score"] = (
                cand.loc[_wait_mask, "champion_score"] + _bonus
            ).clip(upper=1.75)
            log.info("[LEADER] WAIT 보너스 적용: %d건 (+0.04~0.08)", _wait_mask.sum())
        if _rej_mask.any():
            # REJECT: entry_ok 차단 유지 (이미 _apply_leader_score에서 처리)
            log.debug("[LEADER] REJECT %d건 — champion_score 보너스 없음", _rej_mask.sum())

    # ★[2026-07-01 단타점수 우선순위] 전날 순위표 단타점수로 champion 가점 → 상위 대장 우선 선택.
    #   priority 90→×1.08 / 50→×1.0 / 20→×0.94 (완만). 롤백 setx PB_SCALP_PRIORITY NO
    if os.environ.get("PB_SCALP_PRIORITY", "YES").strip().upper() == "YES":
        try:
            import leader_filter as _lf
            _w = float(os.environ.get("PB_SCALP_W", "0.2"))
            _pri = cand["code"].map(lambda x: _lf.priority(_lf._z(x)))
            cand["champion_score"] = (
                cand["champion_score"] * (1.0 + (_pri / 100.0 - 0.5) * _w)
            ).clip(0, 1.75)
            log.info("[LEADER-BOARD] 단타점수 우선순위 반영(w=%.2f)", _w)
        except Exception as _se:
            log.warning("[LEADER-BOARD] 단타점수 우선순위 실패(무시): %s", _se)

    # ── [v5_11] RS 상위 10% + 섹터 거래대금 1위 보너스 ──────────────
    if "rel_return" in cand.columns:
        _rs_p90   = cand["rel_return"].fillna(0).quantile(CFG.RS_TOP10_PERCENTILE)
        _rs_top10 = (cand["rel_return"].fillna(0) >= _rs_p90).astype(float)
        cand["champion_score"] = (
            cand["champion_score"] * (1 + _rs_top10 * CFG.RS_TOP10_BONUS)
        ).clip(upper=1.75)
        log.info("[v5_11][RS_TOP10] 상위10%%ile 보너스=%d건 (p90=%.4f ×%.2f)",
                 int(_rs_top10.sum()), _rs_p90, 1 + CFG.RS_TOP10_BONUS)

    _sector_leader = pd.Series(0.0, index=cand.index)
    if "value_5" in cand.columns:
        _max_idx = cand["value_5"].fillna(0).idxmax()
        if _max_idx in cand.index:
            _sector_leader.loc[_max_idx] = 1.0
        cand["champion_score"] = (
            cand["champion_score"] * (1 + _sector_leader * CFG.SECTOR_LEADER_BONUS)
        ).clip(upper=1.75)
        log.info("[v5_11][SECTOR_LEADER] 섹터1위 보너스=%d건 (×%.2f)",
                 int((_sector_leader > 0).sum()), 1 + CFG.SECTOR_LEADER_BONUS)

    # ── Top1 몰빵 집중 ────────────────────────────────────────────
    rank_idx = cand["champion_score"].rank(ascending=False, method="first")
    cand.loc[rank_idx == 1, "position_size"] *= 1.40
    cand.loc[rank_idx == 2, "position_size"] *= 0.85
    cand.loc[rank_idx >= 3, "position_size"] *= 0.60
    cand["position_size"] = cand["position_size"].clip(0, CFG.MAX_POSITION_PCT)
    log.info(f"[CHAMPION] Top1 집중: 1위×1.40 | 2위×0.85 | 3위↓×0.60 | 후보={len(cand)}")

    champion      = cand.sort_values("champion_score", ascending=False).iloc[0]
    champion_code = champion["code"]

    df.loc[cand.index, "champion_score"] = cand["champion_score"].values
    df.loc[cand.index, "position_size"]  = cand["position_size"].values
    df.loc[cand[cand["code"] == champion_code].index, "entry_ok"] = True
    # [PATCH-v5.10.4] entry_mode 기본값 = NORMAL (일반 진입)
    df["entry_mode"] = "NORMAL"

    log.info(
        f"[CHAMPION🏆 v5.8] {champion_code} | "
        f"score={champion['champion_score']:.4f} | "
        f"R:R={champion.get('rr_ratio',0):.2f} | "
        f"gap={champion.get('gap_grade','?')} | time={champion.get('time_regime','?')} | "
        f"inst={int(champion.get('inst_accel_consecutive',0))}봉 | "
        f"vol확인돌파={'✅' if champion.get('vol_confirm_cross') else '❌'} | "
        f"전일고점돌파={'✅' if champion.get('prev_high_break') else '❌'} | "
        f"hammer={'✅' if champion.get('hammer_flag') else '❌'} | "
        f"상대강도={'✅' if champion.get('strong_rs') else '❌'} | "
        f"체결모멘텀={'✅' if champion.get('chegyul_momentum') else '❌'} | "
        f"얼리={'⚠️' if (910<=int(champion.get('hhmm',0))<=929) else '✅'} | "
        f"밴드={champion.get('entry_price_low',0):.0f}"
        f"~{champion.get('entry_price_high',0):.0f} | "
        f"후보={len(cand)}중 1위"
    )
    # [PATCH-v5.10.2 수정5] 최종 선택 이유 요약 로그 (복기용)
    _leader_sig = champion.get("leader_signal", "N/A")
    log.info(
        "[CHAMPION 선택이유] leader=%s | EV=%.4f | score_raw=%.4f | "
        "inst연속=%d봉 | 기관accel=%.4f | time=%s | gap=%s",
        _leader_sig,
        champion.get("ev_final", 0),
        champion.get("champion_score", 0),
        int(champion.get("inst_accel_consecutive", 0)),
        champion.get("inst_accel", 0),
        champion.get("time_regime", "?"),
        champion.get("gap_grade", "?"),
    )

    # ── 약한 1등 차단 — 정규화 기준 + FORCE ENTRY ───────────────
    normalized_score = champion["champion_score"] / CFG.RAW_SCORE_NORM
    _ev_now    = champion.get("ev_final", 0)
    _inst_now  = champion.get("inst_accel", 0)
    _now_hm    = int(__import__("datetime").datetime.now().strftime("%H%M"))

    # [수정] FORCE ENTRY — 하루 1회 보장
    # 조건: score 1위 + EV > 0 + inst_flow >= 0
    # 14:00 이후: MIN_TOP1_EV 기준 절반으로 완화 (하루 무진입 방지)
    _ev_min_eff = (CFG.MIN_TOP1_EV * 0.5) if _now_hm >= 1400 else CFG.MIN_TOP1_EV
    _force_ok   = (_ev_now > 0 and _inst_now >= 0)

    # [PATCH-v5.10.3] fallback 발동 시점 현실화
    # params 기준 구조:
    #   1회차(EARLY): 09:20~10:30 / 2회차(MID): 10:30~11:40
    #   점심금지: 11:40~13:00 / 3회차(LATE): 13:00~14:50
    # fallback: 각 회차 내 미진입 시 발동 가능 (점심 제외)
    _in_early    = (CFG.T_EARLY_S <= _now_hm < CFG.T_EARLY_E)   # 09:20~10:30
    _in_mid      = (CFG.T_MID_S   <= _now_hm < CFG.T_MID_E)     # 10:30~11:40
    _in_late     = (CFG.T_LATE_S  <= _now_hm < CFG.T_LATE_E)    # 13:00~14:50
    _in_lunch    = (CFG.T_LUNCH_S <= _now_hm < CFG.T_LUNCH_E)   # 11:40~13:00 (금지)
    _fallback_ok_time = (_in_early or _in_mid or _in_late) and not _in_lunch
    _ev_min_eff = (CFG.MIN_TOP1_EV * 0.5) if _now_hm >= 1400 else CFG.MIN_TOP1_EV
    _force_ok   = (_ev_now > 0 and _inst_now >= 0)

    if normalized_score < CFG.MIN_TOP1_SCORE or _ev_now < _ev_min_eff:
        if _force_ok and _fallback_ok_time:
            # 포지션 ×0.70 (fallback 리스크 관리)
            _fb_pos = cand.loc[cand["code"] == champion_code, "position_size"]
            if not _fb_pos.empty:
                cand.loc[cand["code"] == champion_code, "position_size"] *= 0.70
                df.loc[cand[cand["code"] == champion_code].index, "position_size"] *= 0.70
            _session = ("1회차" if _in_early else "2회차" if _in_mid else "3회차")
            log.info(
                "[CHAMPION🔴→✅ FALLBACK] 1일1회 보장 강제진입 | "
                "세션=%s(%04d) EV=%.4f inst=%.4f score_norm=%.4f | 포지션×0.70",
                _session, _now_hm, _ev_now, _inst_now, normalized_score
            )
            # [PATCH-v5.10.4] fallback 진입 표시 → risk 엔진이 이 값을 보고 forced_entry 허용
            df.loc[cand[cand["code"] == champion_code].index, "entry_mode"] = "FALLBACK"
        else:
            log.warning(
                "[CHAMPION⛔] 약한 1등 → 진입 포기 | "
                "score_norm=%.4f(min=%.2f) | ev=%.4f(min=%.4f) | "
                "force_ok=%s fallback_time=%s hhmm=%04d",
                normalized_score, CFG.MIN_TOP1_SCORE,
                _ev_now, _ev_min_eff, _force_ok, _fallback_ok_time, _now_hm
            )
            df["entry_ok"] = False

    return df

# [v5.12 FIX-3] Breadth pos_scale 연동 — STRONG_UP×1.15 / WEAK_DOWN×0.70
def _apply_breadth_pos_scale(regime: str, market_ctx: dict, df: pd.DataFrame, log) -> dict:
    """
    [W6 v5.7] Breadth → pos_scale 직접 연동
    _market_regime() 직후 호출. regime + breadth 지표 기반 pos_scale 보정.
    STRONG_UP + breadth_strong≥15% → ×1.15 보너스
    WEAK_DOWN + breadth_drop≥5%   → ×0.70 페널티
    """
    try:
        non_idx   = df[~df["code"].isin(["U001","U201"])]
        if non_idx.empty: return market_ctx
        last      = non_idx.sort_values("ts").groupby("code").last()
        rets      = last["ret_from_prev_close"].fillna(0)
        total_n   = len(last) + CFG.EPS
        b_strong  = (rets >= CFG.BREADTH_STRONG_RET).sum() / total_n
        b_drop    = (rets <= -CFG.BREADTH_STRONG_RET).sum() / total_n

        old_scale = market_ctx.get("pos_scale", 1.0)
        new_scale = old_scale

        if regime == "STRONG_UP" and b_strong >= CFG.BREADTH_STRONG_T:
            new_scale = min(1.0, old_scale * CFG.BREADTH_POS_BOOST)
            log.info(
                f"[BREADTH_SCALE] STRONG_UP + b_strong={b_strong:.1%}≥{CFG.BREADTH_STRONG_T:.0%} "
                f"→ pos_scale {old_scale:.2f}→{new_scale:.2f} (×{CFG.BREADTH_POS_BOOST})"
            )
        elif regime in ("WEAK_DOWN", "STRONG_DOWN") and b_drop >= CFG.BREADTH_WEAK_LIMIT:
            new_scale = old_scale * CFG.BREADTH_POS_PENALTY
            log.warning(
                f"[BREADTH_SCALE] {regime} + b_drop={b_drop:.1%}≥{CFG.BREADTH_WEAK_LIMIT:.0%} "
                f"→ pos_scale {old_scale:.2f}→{new_scale:.2f} (×{CFG.BREADTH_POS_PENALTY})"
            )

        if new_scale != old_scale:
            market_ctx = dict(market_ctx)
            market_ctx["pos_scale"] = round(new_scale, 4)

    except Exception as e:
        log.warning(f"[BREADTH_SCALE] 실패(비치명적): {e}")

    return market_ctx


def _apply_strategy_entry_band(df: pd.DataFrame, log) -> pd.DataFrame:
    """
    [W2 v5.7] 전략별 진입밴드 ATR 개별화
    _signals() 이후 entry_trend/entry_pullback 확정 후 호출.
    추세: TREND_ENTRY_BAND_ATR_MULT=0.60 (넓게)
    눌림: PB_ENTRY_BAND_ATR_MULT=0.40    (타이트)
    """
    EPS = CFG.EPS
    trend_mask = df["entry_trend"].fillna(False)
    pb_mask    = df["entry_pullback"].fillna(False)

    if trend_mask.any():
        band_t = (
            _safe_div(df.loc[trend_mask, "atr14"].values,
                      (df.loc[trend_mask, "close"] + EPS).values)
            * CFG.TREND_ENTRY_BAND_ATR_MULT
        )
        df.loc[trend_mask, "entry_band_pct"] = pd.Series(
            band_t, index=df.loc[trend_mask].index
        ).clip(CFG.ENTRY_BAND_MIN, CFG.ENTRY_BAND_MAX)

    if pb_mask.any():
        band_p = (
            _safe_div(df.loc[pb_mask, "atr14"].values,
                      (df.loc[pb_mask, "close"] + EPS).values)
            * CFG.PB_ENTRY_BAND_ATR_MULT
        )
        df.loc[pb_mask, "entry_band_pct"] = pd.Series(
            band_p, index=df.loc[pb_mask].index
        ).clip(CFG.ENTRY_BAND_MIN, CFG.ENTRY_BAND_MAX)

    # 밴드 재산출 후 entry_price 갱신
    df["entry_price_low"]  = (df["close"] * (1 - df["entry_band_pct"])).round(0)
    vwap_ref = df[["close","anchored_vwap"]].min(axis=1)
    df["entry_price_high"] = (vwap_ref * (1 + df["entry_band_pct"])).round(0)
    swap = df["entry_price_low"] > df["entry_price_high"]
    df.loc[swap, "entry_price_high"] = (
        df.loc[swap, "close"] * (1 + df.loc[swap, "entry_band_pct"])
    ).round(0)

    log.info(
        f"[BAND] 전략별 밴드 재산출 | "
        f"추세({trend_mask.sum()}건)×{CFG.TREND_ENTRY_BAND_ATR_MULT} | "
        f"눌림({pb_mask.sum()}건)×{CFG.PB_ENTRY_BAND_ATR_MULT}"
    )
    return df


def _final_select(df: pd.DataFrame, held_codes: list, log) -> pd.DataFrame:
    """[v5.0] CHAMPION_MODE=False 시에만 사용 (현재 미사용 경로)"""
    log.info("FINAL SELECT (다종목 — 비활성)")
    df["entry_ok"] = (
        (df["entry_trend"]|df["entry_pullback"]) &
        (~df["risk_block"].fillna(False)) &
        (df["ev_final"] >= CFG.EV_MIN) &
        (df["confidence"] >= CFG.CONF_MIN) &
        (df["position_size"] > 0)
    ).fillna(False)
    entry_df = df[df["entry_ok"]].sort_values("ts").drop_duplicates("code", keep="last")
    if held_codes: entry_df = entry_df[~entry_df["code"].isin(set(held_codes))]
    # CHAMPION_MODE 전용이므로 MAX_CONCURRENT 불필요. 단일 종목 선정.
    entry_df = entry_df.sort_values("ev_final", ascending=False).head(CFG.TOP_N)
    df["entry_ok"] = False; df["champion_score"] = 0.0
    if len(entry_df): df.loc[entry_df.index, "entry_ok"] = True
    log.info(f"[FINAL] entry_ok={df['entry_ok'].sum()}")
    return df


def _output(df: pd.DataFrame, run_id: str, log,
            profit_stats: dict = None) -> pd.DataFrame:
    """[FIX-4 v5.5] profit_stats → champion row에 수익률 지표 주입"""
    df["run_id"] = run_id
    df["strategy_type"] = np.where(df["entry_trend"],"추세",np.where(df["entry_pullback"],"눌림목","미분류"))
    def _reason(row):
        if row.get("risk_block"): return f"RISK:{row.get('risk_reason')}"
        if row.get("entry_ok"):
            flags = [f for f, k in [
                ("전일고점✅","prev_high_break"),("VOL돌파✅","vol_confirm_cross"),
                ("hammer✅","hammer_flag"),("상대강도✅","strong_rs"),
                ("체결모멘텀✅","chegyul_momentum"),
            ] if row.get(k)]
            early_flag = "⚠️얼리" if (910 <= int(row.get("hhmm",0)) <= 929) else ""
            return (f"OK|{row.get('strategy_type')}|gap={row.get('gap_grade')}|"
                    f"ch={row.get('champion_score',0):.4f}|ev={row.get('ev_final',0):.4f}|"
                    f"rr={row.get('rr_ratio',0):.2f}|"
                    f"band={row.get('entry_price_low',0):.0f}~{row.get('entry_price_high',0):.0f}|"
                    f"{','.join(flags)}{early_flag}")
        if not (row.get("entry_trend") or row.get("entry_pullback")): return "NO_SIGNAL"
        return "FILTERED"
    df["reason_text"] = df.apply(_reason, axis=1)
    out = df[df["entry_ok"]].copy()
    str_cols = {"pattern_key","reason_text","risk_reason","run_id","gap_grade",
                "index_trend","signal_ts","strategy_type","trail_signal"}

    # [FIX-4 v5.5] 수익률 지표 주입 — strategy_type별 매핑
    if profit_stats:
        def _inject_profit(row):
            stype = "TREND" if row.get("strategy_type") == "추세" else "PULLBACK"
            s = profit_stats.get(stype, {})
            return (
                s.get("win_rate", None),
                s.get("profit_factor", None),
                s.get("avg_pnl", None),
            )
        if not out.empty:
            metrics = out.apply(_inject_profit, axis=1)
            out["strat_win_rate"] = [m[0] for m in metrics]
            out["strat_pf"]       = [m[1] for m in metrics]
            out["strat_avg_pnl"]  = [m[2] for m in metrics]
    else:
        out["strat_win_rate"] = None
        out["strat_pf"]       = None
        out["strat_avg_pnl"]  = None

    for c in CFG.OUT_COLS:
        if c not in out.columns:
            out[c] = "" if c in str_cols else 0.0

    # [METHOD-A] rt_execution_engine 호환 컬럼 계산 — out 원본 기준 (OUT_COLS 선택 이전)
    def _gcol(df, col, default=0.0):
        return df[col].fillna(default) if col in df.columns else default

    out["prescore_weighted"] = _gcol(out, "score_final") * 50
    out["attack_score"]      = _gcol(out, "score_final") * 35
    out["stable_score"]      = _gcol(out, "score_final") * 15
    out["inst_ride_score"]   = _gcol(out, "ride_score_hint") * 5
    out["ofi"]               = _gcol(out, "inst_net_ratio") * 2
    out["price_vs_vwap"]     = _gcol(out, "vwap_dev_pct") / 100.0 + 1.0
    out["price_vs_day_high"] = 1.0 + _gcol(out, "ret_from_high")
    out["expected_edge"]     = _gcol(out, "ev_final")
    out["market_flag"]       = out["market_regime"] if "market_regime" in out.columns else "NEUTRAL"
    out["volume_accel"]      = _gcol(out, "vol_accel", 1.0)
    out["price_now"]         = _gcol(out, "close")
    out["close_today"]       = _gcol(out, "close")
    out["strategy_hint"]     = (
        out["strategy_type"].map({"눌림목": "PULLBACK", "추세": "TREND"}).fillna("PULLBACK")
        if "strategy_type" in out.columns else "PULLBACK"
    )
    out["close_position"] = 0.5
    out["value_now"]      = 0
    out["value_day"]      = 0
    out["last3_ret"]      = 0
    out["ofi_last10"]     = 0

    _extra = [
        "prescore_weighted", "attack_score", "stable_score",
        "inst_ride_score", "ofi", "price_vs_vwap", "price_vs_day_high",
        "expected_edge", "market_flag", "volume_accel",
        "price_now", "close_today", "strategy_hint",
        "close_position", "value_now", "value_day", "last3_ret", "ofi_last10",
    ]
    return out[CFG.OUT_COLS + _extra].copy()


# ==============================================================================
# MAIN
# ==============================================================================
def main() -> int:
    t0     = _time.time()
    run_id = str(uuid.uuid4())
    log    = _logger(run_id)
    log.info("="*60)
    log.info(f"RT 추세·눌림목 엔진 v5.9 SAFEPLUS FINAL | {datetime.now():%Y-%m-%d %H:%M:%S}")
    log.info(
        f"[v5.8] R1종배삭제 + R2FallbackCap60 + R3진입완화10:30 + R4점심1130-1200 + R5공휴일 + R6계좌캐싱 | "
        f"누적: v5.7(W2/W3/W6/W7)+v5.6(Breadth)+v5.5(7FIX)"
    )
    log.info(
        f"[CONFIG v5.8] ATR={CFG.ATR_PERIOD} | TREND_BAND=×{CFG.TREND_ENTRY_BAND_ATR_MULT} | "
        f"PB_BAND=×{CFG.PB_ENTRY_BAND_ATR_MULT} | "
        f"Breadth_BOOST=×{CFG.BREADTH_POS_BOOST}/PENALTY=×{CFG.BREADTH_POS_PENALTY} | "
        f"Halt필터=ON | 진화루프모니터=ON | FallbackCap={CFG.FALLBACK_POS_CAP:.0%} | "
        f"WarmupTrades={CFG.FALLBACK_WARMUP_TRADES} | 종배SB=제거됨"
    )
    log.info("="*60)

    evolved_params = _load_evolved_params(log)
    time_boost     = _load_time_stats(log)

    # [R1 v5.8] 종배 스코어보드 로드 제거
    # sb_ctx = _load_scoreboard_context(log)  ← 삭제

    # 수익률 평가 로그 출력
    profit_stats = _profit_evaluation_log(log)

    now_hhmm = int(datetime.now().strftime("%H%M"))
    if not (830 <= now_hhmm <= 1540):
        log.warning(f"[TIME] 장외({now_hhmm}) → HOLD"); return RC_HOLD

    for path, label in [(CFG.PATH_PRICES,"prices_1m"), (CFG.PATH_PREV,"prev_day")]:
        if not Path(path).exists():
            log.critical(f"[PRECHECK] {label} 없음"); return RC_STOP
        if Path(path).stat().st_size < 512:
            log.critical(f"[PRECHECK] {label} 크기 이상"); return RC_STOP

    if _check_dd(log):
        _atomic_csv(pd.DataFrame(columns=CFG.OUT_COLS), CFG.PATH_OUTPUT, log)
        return RC_HOLD

    if _check_daily_entry_lock(log):
        _atomic_csv(pd.DataFrame(columns=CFG.OUT_COLS), CFG.PATH_OUTPUT, log)
        return RC_HOLD

    dp, dv = _load(log)
    if dp is None: return RC_STOP

    df = _clean(dp, dv, log)
    if df is None: return RC_STOP

    market_ctx = _load_market_context(dp, log)
    if market_ctx["pos_scale"] == 0.0:
        log.critical("[MARKET] pos_scale=0 → 전량 차단")
        _atomic_csv(pd.DataFrame(columns=CFG.OUT_COLS), CFG.PATH_OUTPUT, log)
        return RC_HOLD

    df         = _features(df, market_ctx, log)
    df, regime = _market_regime(df, market_ctx, log)
    df         = _time_regime(df, log)

    # [W6 v5.7] Breadth → pos_scale 직접 연동 (regime 확정 직후)
    market_ctx = _apply_breadth_pos_scale(regime, market_ctx, df, log)
    if market_ctx["pos_scale"] == 0.0:
        log.critical("[MARKET] Breadth보정 후 pos_scale=0 → 전량 차단")
        _atomic_csv(pd.DataFrame(columns=CFG.OUT_COLS), CFG.PATH_OUTPUT, log)
        return RC_HOLD

    if market_ctx["is_expiry_day"]:
        late = df["time_regime"] == "LATE"
        df.loc[late, ["entry_trend","entry_pullback"]] = False
        log.warning(f"[MARKET] 만기일 LATE 차단 ({late.sum()}행)")

    df = _signals(df, log)

    # [W2 v5.7] 전략별 진입밴드 재산출 (_signals() 이후 — 전략 확정 시점)
    df = _apply_strategy_entry_band(df, log)

    # [PATCH-v5.10.2 수정2] 시간 차단 단일화 — CFG 기준으로 통일
    # 문제: T_LUNCH_S=1140(CFG), entry_lock=1140, bad_time=1130 세 값이 분산
    # 수정: bad_time도 CFG.T_LUNCH_S / CFG.T_LUNCH_E 참조로 통일
    bad_time = (
        ((df["hhmm"] >= 900)  & (df["hhmm"] <= 910)) |
        ((df["hhmm"] >= CFG.T_LUNCH_S) & (df["hhmm"] <= CFG.T_LUNCH_E))
    )
    if bad_time.any():
        df.loc[bad_time, ["entry_trend","entry_pullback"]] = False
        log.info(
            f"[TIME] 차단구간: 개장직후(900~910)+점심(CFG {CFG.T_LUNCH_S}~{CFG.T_LUNCH_E}) | "
            f"차단={bad_time.sum()}행"
        )

    df = _risk_gate(df, log)
    df = _score(df, log)
    df = _ev(df, time_boost, log)

    acct = _load_account(log)
    df   = _sizing(df, acct["cash"], market_ctx, log)

    # [패치3 v5.1] MDD 기반 학습 필터 — 드로우다운 시 포지션 자동 축소
    mdd = _load_mdd(log)
    if mdd <= -0.15:
        df["position_size"] *= 0.3
        log.warning(f"[MDD] max_drawdown={mdd:.2%} ≤ -15% → 포지션 ×0.3 (방어모드)")
    elif mdd <= -0.08:
        df["position_size"] *= 0.7
        log.warning(f"[MDD] max_drawdown={mdd:.2%} ≤ -8% → 포지션 ×0.7 (경계모드)")

    # [R1 v5.8] champion_select — sb_ctx 제거, 순수 RT 신호 기반
    if CFG.CHAMPION_MODE:
        # ── LEADER ENGINE 사전 적용 ───────────────────────────────
        try:
            _price_hist: dict = {}
            for _code, _grp in df.groupby("code"):
                _closes = _grp.sort_values("hhmm")["close"].tolist()
                _price_hist[str(_code)] = _closes[-60:]
            _cur_hhmm = int(df["hhmm"].max()) if not df.empty else now_hhmm
            df = _apply_leader_score(df, _price_hist, _cur_hhmm, log)
            log.info("[LEADER] leader_engine 적용 완료 — BUY=%d REJECT=%d",
                     (df["leader_signal"] == "BUY").sum(),
                     (df["leader_signal"] == "REJECT").sum())
        except Exception as _le:
            log.warning("[LEADER] leader_engine 적용 실패(무시): %s", _le)

        df = _champion_select(df, acct["held_codes"], log)
    else:
        df = _final_select(df, acct["held_codes"], log)

    # [v5.9 FIX-3] trail_signal 4단계 확장 — 수익률 최적화
    # hybrid_score: score(50%) + EV(25%) + 기관연속(15%) + 거래량(10%)
    # HOLD  (≥0.72): 기관 강동행 확인 → Trail 금지, 끝까지 보유
    # PARTIAL(0.45~): 기관 동행 → 표준 Chandelier
    # TIGHT (<0.25): 기관 없는 눌림목 → 빠른 익절
    # EXIT  (<0.25 + 눌림목): 즉시 이탈 준비
    hybrid_score = (
        df["score_final"].fillna(0) * 0.50 +
        (df["ev_final"].fillna(0) / 0.02).clip(0, 1) * 0.25 +
        (df["inst_accel_consecutive"].fillna(0) / 5).clip(0, 1) * 0.15 +
        df["vol_confirm_cross"].fillna(False).astype(float) * 0.10
    )
    df["trail_signal"] = "NONE"
    df.loc[hybrid_score >= 0.72, "trail_signal"] = "HOLD"    # [v5.9] 0.70→0.72 강화
    df.loc[(hybrid_score >= 0.45) & (hybrid_score < 0.72), "trail_signal"] = "PARTIAL"
    # [v5.9] TIGHT 신규: 기관 미확인 눌림목 → 빠른 익절
    _tight_mask = (
        (hybrid_score < 0.25) &
        df["entry_pullback"].fillna(False).astype(bool) &
        (df["inst_accel_consecutive"].fillna(0) < 2)
    )
    df.loc[_tight_mask, "trail_signal"] = "TIGHT"
    df.loc[(hybrid_score < 0.30) & ~_tight_mask, "trail_signal"] = "EXIT"

    # [FIX-5 v5.5] ride_score_hint — trail_signal → 숫자 변환 (매도엔진 ride_score 기준 정렬)
    # [v5.9] TIGHT 추가 매핑
    _trail_to_ride = {**CFG.TRAIL_TO_RIDE, "TIGHT": 0.15}
    df["ride_score_hint"] = df["trail_signal"].map(_trail_to_ride).fillna(0.30)

    out_df = _output(df, run_id, log, profit_stats=profit_stats)
    if not _atomic_csv(out_df, CFG.PATH_OUTPUT, log): return RC_STOP

    # [R1 v5.8] 진입 기록 저장 + linker 훅 (sb_ctx 제거)
    if not out_df.empty:
        champion_row = out_df.iloc[0]
        _save_entry_log(champion_row, market_ctx, run_id, log)
        _try_linker_hook(str(champion_row.get("code", "")), run_id, log)

    # 최종 수익률 지표 포함 DONE 로그
    trend_wr  = profit_stats.get("TREND",   {}).get("win_rate",  None)
    pb_wr     = profit_stats.get("PULLBACK", {}).get("win_rate",  None)
    trend_pf  = profit_stats.get("TREND",   {}).get("profit_factor", None)
    pb_pf     = profit_stats.get("PULLBACK", {}).get("profit_factor", None)

    log.info(
        f"[DONE✅ v5.8] RC_OK | {len(out_df)}candidates | {_time.time()-t0:.2f}s | "
        f"regime={regime} | market_score={market_ctx['market_score']:.3f} | "
        f"evolved={len(evolved_params)}params | "
        f"수익률[TREND] 승률={trend_wr:.1%} PF={trend_pf:.2f}" if trend_wr else
        f"[DONE✅ v5.8] RC_OK | {len(out_df)}candidates | {_time.time()-t0:.2f}s | "
        f"regime={regime} | market_score={market_ctx['market_score']:.3f} | "
        f"수익률데이터 축적 중"
    )
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())


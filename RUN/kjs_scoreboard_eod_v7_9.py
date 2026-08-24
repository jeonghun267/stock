# -*- coding: utf-8 -*-
"""
kjs_scoreboard_eod_v7_1_SAFEPLUS_FINAL.py
==========================================
고유 영역  : 코스닥 종가매매 전용 스코어보드
파이프라인 : prices_3m / prices_1m / investor_daily → score_eod.csv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
설계 원칙 (헤지펀드 다단계 선별 - Renaissance/AQR/Citadel 기준)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
각 단계는 서로 다른 질문을 한다 - 같은 점수로 반복 자르지 않는다

1단계 400→50  "지금 돈이 몰리고 있는가?" → 공격(시장 흐름)
  OFI 가속도 20점 + 거래대금 기울기 15점 + VPIN 10점 = 45점

2단계 50→20   "가격 구조가 탄탄한가?" → 공격(구조+수급)
  잔차모멘텀 10점 + 60일 신고가 15점 + 기관 연속 순매수 28점(최대)
  + 갭업예측 15점 + val_ratio 10점 + 전일고점돌파 5점 + 추세지속 8점
  → clip(0, 75) [v6_7: 65→75 상향, 팩터 변별력 복구]

3단계 20→5    "내일 안 빠질 종목인가?" → 방어(생존 여부)
  Hard Cut 강제 탈락 + 갭하락 위험 감점 + 마감 강도 가점
  [v6_7: 변동성 패널티 step3 내부 통합 - 이중계산 제거]

4단계 5→1     "1등이 압도적인가?" → 확신 검증 (몰빵 전용 강화)
  매수 직전 10분 동태(15:08~15:18) + Conviction Gate (소프트/하드 2단계)
  SOFT: winner_gap ≥ 7.0 + conviction ≥ 70 → position_ratio × 0.80
  HARD: winner_gap ≥ 11.5 + conviction ≥ 82 → position_ratio 유지
  [v6_7: 단일 하드차단 → 2단계화, 매매기회 +30~40일/년 확보]

최종점수 = (공격점수×0.70) + (방어조정×0.30) + history_bonus(최대+8)
  history_bonus = 3일연속 상위권 +5 + 스코어 우상향 기울기 +3
  → 갑자기 튄 종목 억제, 기관이 꾸준히 쌓는 종목 우대

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
자기 진화 연동 (evolution_engine 피드백 루프)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행 시 evolved_params.json 자동 로딩 → 핵심 파라미터 오버라이드
선정 후 feedback_{date}.json 기록 → evolution_engine 학습 입력

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v7_1 수정사항 (2026-04-05) - 몰빵 정밀화 11항목 전수 적용
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[필수-1] Top1 단독 몰빵 방지 추가 게이트 ★★★
  dominance_ratio < 1.15 → position_ratio × 0.75
  winner_gap      < 8.0  → position_ratio × 0.85
  둘 다 해당      → position_ratio × 0.65  (allout 시 면제)

[필수-2] score_final에 시장 상태 직접 반영 ★★★
  market_adj 컬럼 신규: mkt_risk=1 → -3 / kosdaq≤-1.5 → -2 / kosdaq≥+1 → +1

[필수-3] 갭 실패 리스크 직접 감점 ★★★
  gap_fail_penalty 컬럼 신규
  gap_predict < 5.0 → -2 / < 3.0 → -4
  close_pos < 0.78 AND wick < 0.985 동시 → 추가 -2  (최대 -6)

[필수-4] dyn_score 비중 강화 ★★
  score*0.88+dyn*0.12  →  score*0.82+dyn*0.18

[필수-5] score_final 중복 바이어스 정리 ★★
  SCORE_FINAL_PRIOR_MULT 6.0→5.0
  SCORE_FINAL_CONV_HIGH  2.0→1.5
  SCORE_FINAL_CONV_MID   1.0→0.7

[필수-6] history_bonus 상한 축소 ★★
  HIST_CONSEC_BONUS 5.0→4.0
  HIST_SLOPE_BONUS  3.0→2.0

[필수-7] Hard Cut "저질 종가 체류" 추가 ★★
  close_position < 0.74 AND close_value_ratio < 0.18 AND last5_value_accel < 0.90 동시충족

[필수-8] position_ratio 최종 캡 세분화 ★★
  risk_penalty >= 4.0   → min(pos, 0.70)
  gap_predict  < 4.0    → min(pos, 0.60)
  dominance    < 1.10   → min(pos, 0.65)  (allout 시 면제)

[필수-9] score_final 최종식 확장 ★★★
  score_final = score + prior×5 + conv_bonus + dyn_bonus
              - risk_penalty - gap_fail_penalty + market_adj

[선택-1] prior_class 기준 미세강화
  STRONG: rank<=3 and score>=82 (이전 80)
  MID:    rank<=5 and score>=76 (이전 75)

[선택-2] EOD-PRIOR 로그 score_final 우선 출력 통일

[v7_0 수정사항 유지]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[BUG-A] score_final 이중 정의 충돌 완전 해소 ★★★
  문제: step4b가 임시 동태혼합값에 score_final 이름 사용
        → _build_output이 이를 score로 덮어씌운 뒤
        → _calc_score_final이 다시 score_final 계산 → 3중 혼선
  수정: step4b 임시 중간값 변수명 score_dyn_blend로 변경
        score_final 컬럼은 _calc_score_final()에서만 단독 생성

[BUG-B] score_history-pullback_watch 단절 해소 ★★★
  문제: score_history에는 TOP_5만 저장(rank 1~5)되는데
        pullback_watch는 avg_rank ≤ 15 조회 → 항상 빈 결과
  수정: pullback_watch 조회 기준 avg_rank ≤ 5로 수정 (실제 데이터와 일치)

[BUG-C] score 상한 108 → 100 통일 ★★
  문제: clip(0, 108)로 score가 100 초과 가능
        grade("S"=88+) 체계가 100점 기준인데 108점 종목 존재 → 체계 붕괴
  수정: clip(0, 100) - score_final과 스케일 통일

[BUG-D] CONV_SOFT_POSITION 진화 상한 0.90 → 0.85 ★★
  문제: evolved_params soft_position=0.90 적용 시
        SOFT 모드(확신 약함)에도 90% 포지션 → HARD와 차이 10%뿐
        지침 9번(과해서 손해) 위반 위험
  수정: max 상한 0.85로 제한 - SOFT/HARD 의미 차이 최소 15%p 보장

[W1] attack_score 상대정규화 절대 하한 보완 ★
  문제: 시장 약세일 s12_max가 낮아도 1등에게 attack_score 100점
        → 기대수익률 낮은 날 과대평가
  수정: s12_max에 절대 하한 55 적용 → 절대 품질 미달 시 자동 감점

[W2] pnl_strategy_linker 연결 단절 조기 경고 ★
  문제: linker 미작동 시 evolution feedback 수익률 영구 None
        자기진화가 형식만 존재하게 됨
  수정: 빌드 시작 시 feedback 파일 중 수익률 채워진 것 비율 점검
        5일 이상 미연결 시 [EVOL-WARN] 로그 출력

[W3] kosdaq_chg 중앙값 통일 ★
  문제: 리스크 판단(kosdaq_chg)에 평균 사용 → 극단 급등 종목으로 왜곡
  수정: kosdaq_chg도 중앙값 기준으로 통일
        (mkt_avg_raw 는 참고값으로만 유지)

[W4] Conviction Gate 주석 3곳 불일치 수정 ★
  수정: docstring / 함수내부주석 / 상수값 7.0/70 으로 전부 통일

[v6_9 수정사항 유지]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[SCORE-1] score_final 도입 - prior_weight·conviction·risk 통합 최종 점수
  score_final = score(history_bonus 포함)
              + prior_weight × 6.0 (최대 +6.6)
              + conviction 가산 (≥82→+2, ≥72→+1)
              - risk_penalty (윗꼬리/거래대금/종가위치 3항목)
[SCORE-2] conviction 가산 - 압도적 1등을 순위에서 한 번 더 밀어줌
[SCORE-3] risk_penalty - 다음날 실패 가능 종목 사전 감점
[SUPPLY-1] top5_map 6개 필드 확장 - gap_predict/close_pos/upper_wick/
           last5_value_accel/close_value_ratio/dominance_ratio 추가
[SUPPLY-2] siga_candidates 교체 - priority/gap_fail/open_drive 스코어링,
           entry_class(PRIME/WATCH/SKIP) + block_flag 필터, 최대 3개
[SUPPLY-3] pullback_watch 교체 - priority/quality/decay_risk 스코어링,
           setup_class(STRONG/MODERATE/WEAK_SETUP) + block_flag 필터, 최대 5개
[SUPPLY-4] market_state 확장 - market_bias_class/market_attack_scale/
           siga_enable/pullback_enable 추가 (3전략 활성화 라우팅)
[LOG] [SIGA-PRIOR],[SIGA-BLOCK],[PULLBACK-PRIOR],[PULLBACK-BLOCK] 로그 추가

[v6_8 수정사항 유지]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v6_8 수정사항 (2026-04-05) - RT·시가 연결 prior 데이터 공급기 완성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ADD-1] prior_class / prior_weight / eod_pick_flag / schema_version 4필드 신규
  prior_class: ULTRA/STRONG/MID/WEAK - RT·시가가 참조 우선도 즉시 판단
  prior_weight: 순위+allout+conviction+score 복합 가중치 (max 1.10)
  eod_pick_flag: rank≤5 → "Y", 나머지 → "N"
  schema_version: "scoreboard_eod_rtlink_v1" - 버전 안전 확인용

[ADD-2] eod_shared_data.pkl top5_map 구조 고정
  code → {rank,score,grade,winner_gap,conviction,attack_score,defense_score,
           allout_signal,position_ratio,prior_class,prior_weight,
           mkt_risk_flag,strategy} dict
  RT·시가가 CSV 안 읽고도 바로 참조 가능

[ADD-3] RT 참조 친화 로그 추가
  [EOD-PRIOR] - 상위 5개 전부 기록 (code/rank/score/conviction/prior_class)
  [RT-LINK-READY] - top1·top5·schema 한 줄 요약

[ADD-4] 출력 안정성 강화
  저장 직전 필수 컬럼 검증 → 누락 시 빈 기본값 채워 저장
  top5 < 5개 시 [WARN] 로그
  top1 부재 시 pkl에 top1_code="" 안전 저장

[v6_7 수정사항 유지]
v6_7 수정사항 (2026-04-05) - 전수 감사 8개 버그/약점 전부 수정
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[FIX-1] OUT_COLUMNS에 history_bonus 추가 ★★★
  문제: score에 history_bonus 더해지지만 컬럼 미포함 → 브릿지 전달 안됨
        자기진화 피드백 데이터 오염
  수정: OUT_COLUMNS에 "history_bonus" 추가, evolution 피드백에도 기록

[FIX-2] score 이중 재계산 완전 제거 ★★★
  문제: step3_defense에서 완성된 score를 _build_output 이후
        변동성 패널티로 또 재계산 → 방어비중 실질 왜곡
  수정: 변동성 패널티를 build_scoreboard에서 step3 결과에 직접 적용(1회),
        _build_output 이후 재계산 블록 완전 제거

[FIX-3] Conviction Gate 소프트/하드 2단계화 ★★★
  문제: winner_gap≥11.5 + conviction≥82 단일 하드차단
        → 연간 매매일 70% HOLD, 자기진화 데이터 축적 불가
  수정: SOFT(gap≥8 & conv≥72) → 80% 포지션 진입
        HARD(gap≥11.5 & conv≥82) → 풀 포지션
        하드차단: gap<8 OR conv<72 (기존 대비 크게 완화)

[FIX-4] position_ratio에 inst_consec 복합 반영 ★★
  문제: gap_predict 단독 → 기관 5일 연속매수여도 60% 투입
        "기관의 등에 탔다" 원칙 위배
  수정: inst_boost = min(inst_consec/5, 1.0)×0.15 추가
        allout=1 시 여전히 100% 강제

[FIX-5] stage2_score clip 65 → 75 ★★
  문제: 이론최대 91점이 65로 잘려 잔차모멘텀·신고가·val_ratio 변별력 소실
  수정: clip(0, 75) → 팩터 간 실질 차별화 복구

[FIX-6] eod_shared_data.pkl - 3전략 공유 섹션 추가 ★★
  문제: 시가·추세눌림 엔진이 pkl 미사용, 기관 정보 단절
  수정: siga_candidates(inst_consec≥2 top5),
        pullback_watch(hist 연속 상위권 종목),
        market_state(공용 시장상태) 섹션 추가

[FIX-7] 마켓 리스크 순서 수정 ★
  문제: STOCK_MIN_CHG 컷이 mkt_risk_flag 설정 이후 적용
        → 브릿지가 잘못된 종목 수로 리스크 판단
  수정: STOCK_MIN_CHG 컷 → mkt_risk_flag 설정 순서로 재배치

[FIX-8] OFI/BUY 윈도우 확장 ★
  문제: OFI_END=1523, BUY_END=1523 - 코스닥 단일가(15:20~15:30) 데이터 손실
  수정: OFI_END=1528, BUY_START=1520, BUY_END=1528 → 마지막 세력 진입 포착

[파라미터] 29개 (기존 26 + CONV_SOFT_GAP_MIN/CONV_SOFT_CONV_MIN/
                              CONV_SOFT_POSITION_RATIO 3개 신규)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd
from logging.handlers import RotatingFileHandler


# ═══════════════════════════════════════════════════════════════
#  리턴 코드
# ═══════════════════════════════════════════════════════════════
RC_OK     = 0
RC_STOP22 = 22
RC_HOLD   = 200

ENGINE_VER = "kjs_scoreboard_eod_v7_9_SAFEPLUS_FINAL_20260419"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v7.9 수정사항 (2026-04-19) — 중요결함 3번 수정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3번] ★★ siga_open_drive_bias를 siga_priority_score에 직접 반영
#   문제: open_drive_bias(vpin×30 + inst_consec×40 + close_pos×30)가
#         계산만 되고 로그·출력에만 쓰임
#         siga_priority_score는 prior_class·conviction·winner_gap·
#         close_pos·gap_predict만 사용 → 시가 강세 편향 신호 미반영
#   근거: 1종목 몰빵 구조에서 SIGA는 "좋은 날만 정확히" 진입해야 함
#         open_drive_bias = 기관 당일 매집강도(vpin) + 지속성(inst_consec)
#                         + 종가위치(close_pos) 복합 → 시가 강세 예측력 높음
#         기존 5점(close_pos 단독)을 10점으로 확대하고
#         open_drive_bias 10점을 priority에 직접 반영
#   수정:
#         siga_priority_score 공식 재조정 (총합 100 유지):
#           prior_class × 15 → max 60 (유지)
#           conviction  × 20 → max 20 (유지)
#           winner_gap  × 10 → max 10 (유지)
#           close_pos   × 5  → max  5 (유지)
#           gap_predict × 5  → max  5 (유지)
#           open_drive_bias / 10.0 × 10 → max 10 (신규 — 기존 합계 95→100으로 조정)
#         PRIME 기준 65→55 (이미 v7.8에서 완화, 유지)
#   효과: vpin 높고 inst_consec 많고 종가 위치 좋은 날 → 우선순위 상향
#         그렇지 않은 날 → WATCH/SKIP 강등 → 진입 억제
#         결과: PRIME 선별 정확도 향상 → 승률 개선 기대
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v7.8 수정사항 (2026-04-19) — SIGA 월 10회 보장 + PULLBACK 수익조건 집중
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# [설계 목표 근거]
#   SIGA: 월 10회 = 연간 120회 진입 → 단회 EV 1.25% × 85% 투입
#         = 월 +531,250원 × 10회 = +5,312,500원 → 연 +127% (5천만 기준)
#   PULLBACK: 1회차 일 1회(21회/월) + 장 좋은 날 2~3회
#         = 월 35~40회 → EV 1.77% × 75% = 월 +2,300만원 → 연 +553%
#   두 전략 합산 연 수익률 목표: +500% 이상
#
# ─────────────────────────────────────────────────────────────────
# [SIGA] 월 10회 보장 — block_flag 핵심 병목 3개 완화
# ─────────────────────────────────────────────────────────────────
# S1 ★★★ dominance 기준 1.10 → 1.00 제거
#    근거: dominance<1.10이 전체 block의 35% 차지 (최대 병목)
#          Conviction Gate(winner_gap≥6.5)가 이미 압도성 검증
#          dominance는 포지션 캡(POS_CAP_DOM_THR=1.08)으로 별도 제한
#          제거 후 winner_gap·conviction이 압도성 판단 역할 승계
#
# S2 ★★★ winner_gap 기준 5.0 → 3.5 완화
#    근거: gap<5.0이 block의 25% 차지 (2위 병목)
#          step4b Conviction Gate(SOFT: gap≥6.5)를 통과한 종목이
#          여기서 다시 gap≥5.0으로 걸리는 이중 차단 → 헤지펀드 표준 위반
#          3.5: Conviction Gate SOFT(6.5) 대비 여유 확보하며 병목 해소
#
# S3 ★★★ conviction 기준 65.0 → 58.0 완화
#    근거: step4b에서 SOFT_CONV_MIN=68.0 통과한 종목이 여기서 65.0에 걸림
#          실질적으로 68→65 차이가 아닌 68→65 통과율 추가 제거 구조
#          58.0: prior_class·winner_gap·upper_wick이 실질 품질 보호
#
# S4 ★★ siga_entry_class PRIME 기준 완화 (priority 70→55, gap_fail 3.0→4.5)
#    근거: PRIME 조건이 너무 엄격해서 WATCH만 생성 → 결국 SKIP 처리
#          priority≥55+gap_fail<4.5: 품질은 충분, 후보 수 2배 확보
#    추가: WATCH 기준도 완화 (priority 50→40, gap_fail 5.0→6.0)
#
# ─────────────────────────────────────────────────────────────────
# [PULLBACK] 수익률 높은 조건 — 스코어보드가 선별해서 넘겨주기
# ─────────────────────────────────────────────────────────────────
# P1 ★★★ pullback_watch avg_rank 기준 ≤5 → ≤8 완화
#    근거: avg_rank≤5가 "5일 연속 1~5위" 조건으로 너무 희귀
#          ≤8: 5일간 8위 이내 = 꾸준한 상위권 = 실전 대장주 기준
#          pullback 수익이 높은 조건 = 5일 이상 기관이 꾸준히 지지하는 종목
#
# P2 ★★★ pullback_block_flag inst_consec 기준 ≥1 → ≥0 (제거)
#    근거: inst_consec=0이어도 당일 강한 기관 유입 종목 존재
#          pullback_watch 자체가 5일 avg_rank≤8 = 이미 기관 검증됨
#          inst_consec<1 제거 → decay_risk·upper_wick이 품질 보호 유지
#
# P3 ★★ pullback_quality_score → pullback_setup_class STRONG 기준 완화
#    근거: priority≥60+quality≥60 동시 충족은 약 15% 수준
#          STRONG 기준: priority≥50+quality≥55로 완화
#          수익률 높은 STRONG 셋업 월 3~4회 확보 가능
#
# P4 ★★ pullback_priority_score 가중치 재조정 — 기관 지속성 강화
#    근거: 눌림 수익 높은 조건 실증 분석
#          inst_consec 지속(5일+ 기관)이 승률 가장 높음 → 가중치 20→25
#          close_pos(종가 위치) → 10→8로 소폭 축소
#          score 기반 → 30→27 (기관 가중치 확보를 위한 재배분)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v7.7 수정사항 (2026-04-19) — 평가 결함 C1·C2·C3·M1·M2 전건 수정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [C1] ★★★ ev_pct 단위 통일 — 브리지 EV_CAUTION_MIN=1.00과 일치
#   문제: 기존 공식 결과값 범위 0~1.5 (비율) ↔ 브리지는 EV%로 해석 (단위 불일치)
#         siga ev_pct=0.7 → 브리지 CAUTION 조건(≥1.0) 미달 → 정상 신호 차단
#   수정: ev_pct 공식에 × 100 적용 → 실제 기대수익률 % 단위로 통일
#         SIGA: 범위 0~150% / PULLBACK: 동일
#         브리지 EV_CAUTION_MIN=1.00과 호환 (1% 이상이면 통과)
#
# [C2] ★★★ pullback_watch inst_consec 최소 기준 추가 (v7.7 당시)
#   → [P2 v7.8]에서 제거됨: avg_rank≤8 자체가 5일 기관 지지 검증 역할 승계
#   현재 pullback_block_flag에 inst_consec 조건 없음 (P2 의도적 제거)
#
# [C3] ★★★ ev_pct·sharpe_proxy OUT_COLUMNS 추가 → score_eod.csv 반영
#   문제: ev_pct·sharpe_proxy가 pkl에만 존재, score_eod.csv·OUT_COLUMNS 미포함
#         execution_engine이 CSV 경로로 읽으면 필드 누락 → EV 공급 단절
#   수정: OUT_COLUMNS에 "siga_ev_pct"·"pullback_sharpe_proxy" 추가
#         _build_output에서 top1 기준값 채워 CSV 저장
#
# [M1] ★★ bridge_ev_weight → execution_engine 경유 sig 전달 경로 명시
#   문제: bridge_ev_weight가 market_state pkl에만 있고 rt_execution_signal.json 미전달
#         브리지 `sig.get("bridge_ev_weight")` 조회 시 항상 기본값 사용
#   수정: _build_shared_cache에서 market_state["bridge_ev_weight"] 필드명 유지
#         + 코드 주석으로 execution_engine이 sig에 심어야 함을 명시
#
# [M2] ★ sharpe_proxy 상한 클리핑 추가
#   문제: score_final=100·decay_risk=0이면 sharpe_proxy=2.0 → 상한 없음
#         evolution_engine이 Sharpe 값으로 오해할 경우 기준 충돌 위험
#   수정: sharpe_proxy = min(계산값, 2.0) 명시적 클리핑 추가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v7_3 수정사항 (2026-04-08) - 수익 극대화 파라미터 튜닝 10항목
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [TUNE-1] Soft Gate 완화 → 연간 진입일 +15~20% 확보
#   CONV_SOFT_GAP_MIN 7.0→6.5 / CONV_SOFT_CONV_MIN 70.0→68.0
#   CONV_SOFT_POSITION 0.80→0.85 (BUG-D 상한 0.85에 맞닿음)
#
# [TUNE-2] 몰빵 방지 게이트 완화 → 진입 가능 케이스 확대
#   DOMINANCE_SOFT_THR 1.12→1.10→1.15 / WINNER_GAP_SOFT_THR 8.0→7.0
#
# [TUNE-3] position cap 완화 → 확신 종목 투입 비율 상향
#   POS_CAP_RISK (4.0/0.70) → (4.5/0.75)
#   POS_CAP_GAP  (4.0/0.60) → (3.5/0.65)
#   POS_CAP_DOM  (1.10/0.65) → (1.08/0.70)
#
# [TUNE-4] score_final 상단 강화 → 1등 차별화 심화
#   PRIOR_MULT 5.0→5.8 / CONV_HIGH 1.5→2.0 / CONV_MID 0.7→1.0
#   ※ v7.2에서 history_bonus 이중증폭 차단 완료로 5.8 수용 안전
#
# [TUNE-5] risk_penalty 완화 → 진입 기회 확대
#   WICK_PEN 2.0→1.5 / L5A_PEN 1.5→1.0 / CP_PEN 1.5→1.0
#
# [TUNE-6] gap_fail_penalty 완화 → 미세 조정
#   LOW_THR 5.0→4.5 / VERY_LOW_THR 3.0→2.5
#   COMBO_CP 0.78→0.76 / COMBO_WICK 0.985→0.982
#
# [TUNE-7] allout 기준 완화 → 몰빵 신호 빈도 +20~30%
#   ALLOUT_SCORE_MIN 80.0→78.0 / ALLOUT_GAP_MIN 12.0→10.5
#
# [TUNE-8] prior_class 완화 → STRONG/MID 진입 문턱 미세 하향
#   PRIOR_STRONG_SCORE 82.0→81.0 / PRIOR_MID_SCORE 76.0→75.0
#
# [TUNE-9] market_adj 수정 → 패널티 완화 + 상승장 보너스 강화
#   mkt_flag=-2.0 / kosdaq≤-1.5=-1.0 / kosdaq≥+1.0=+1.5
#   [추가] kosdaq≥+2.5=+2.5 (강한 상승장 추가 레벨)
#
# [ADD-V73] allout + MKT_WARN 동시 시 position 0.90 캡 ★★
#   근거: allout=1이어도 코스닥 경고(-1.5%) 시 100% 투입은 과함
#         지침서 원칙 "과해서 손해 보는 일 없도록" 적용
#   적용: step4b_conviction 내 allout 처리 직후 MKT_WARN 캡 추가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v7_2 수정사항 (2026-04-08) - 헤지펀드급 6개 보강 (85점→96점)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [FIX-V72-1] ABS_S12_FLOOR 주석-코드 불일치 수정 40.0→55.0 ★★★
#   문제: [W1] 주석은 55 적용이라 하는데 실제 코드는 40.0 → 낮은 품질 종목 과대평가
#   수정: ABS_S12_FLOOR = 55.0 (주석·의도와 일치)
#
# [FIX-V72-2] 급락일 HOLD 피드백 추가 ★★★
#   문제: kosdaq_chg <= MKT_HALT_PCT 급락 강제 HOLD 시 피드백 미기록
#         → 급락일 학습 데이터 영구 누락, 자기진화 리스크 학습 불가
#   수정: _write_hold_feedback("mkt_halt", ...) 호출 추가
#
# [FIX-V72-3] VPIN 명칭 주석 정확화 ★★
#   문제: 코드 VPIN = 상승봉 거래대금 비율 → Easley et al.(2012) 논문 VPIN과 다름
#         명칭 혼동 → 자기진화 팩터 해석 오류 위험
#   수정: 함수 내부 주석 "buy_pressure_ratio (VPIN 근사치)" 로 명확히 표기
#
# [FIX-V72-4] conviction 상한 클리핑 추가 ★★
#   문제: winner_gap이 커지면 conviction = winner_gap×5.0 → unbounded
#         CONV_CONVICTION_MIN=82 기준이 무의미해질 수 있음
#   수정: conviction = min(conviction, 120.0) 클리핑 추가
#
# [FIX-V72-5] history_bonus 이중 증폭 차단 ★★★
#   문제: history_bonus → score에 가산 → prior_weight 상승 → score_final×5 재가산
#         → history_bonus 효과가 score_final에서 이중 증폭
#   수정: score는 pre_bonus 값 유지하여 prior_class/weight 계산에 사용
#         history_bonus는 score_final 산식에서 직접 1회만 가산
#
# [FIX-V72-6] score_history top5→top10 확장 ★★
#   문제: pullback_watch가 score_history top5만 추적 → 6~10위 급부상 종목 포착 불가
#   수정: _save_score_history에서 out_df 상위 10종목 저장
#
# [FIX-V72-7] 자기진화 단절 시 파라미터 동결 플래그 ★★
#   문제: pnl_linker 5일+ 미연결 시 경고만 출력, 수익률 None 상태에서도 파라미터 계속 변경
#         → 잘못된 데이터 기반 진화 위험
#   수정: none_count >= 5 이면 EVOL_FREEZE=True → _load_evolved_params에서 진화 스킵
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCHEMA_VERSION = "scoreboard_eod_rtlink_v1"  # [ADD-1]

# ═══════════════════════════════════════════════════════════════
#  경로
# ═══════════════════════════════════════════════════════════════
BASE        = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA_DIR    = BASE / "DATA"
OUT_DIR     = DATA_DIR / "scoreboard"
OUT_PATH     = OUT_DIR / "score_eod.csv"
OUT_PRE_PATH = OUT_DIR / "score_eod_pre.csv"   # [PATCH-1] Save-1 복구용 (브리지 사용 금지)
OUT_FULL_PATH = OUT_DIR / "score_eod_full.csv"  # [THEME-LEADER 2026-06-04] 상위 N행 전체지표 (EOD_PICK 테마 대장주 주입용)
EOD_FULL_TOP_N = int(os.environ.get("EOD_FULL_TOP_N", "160"))  # [WIDEN 2026-06-05] 40→160 (PULLBACK 후보풀과 일치, 테마 대장주 주입 범위 확대). 다운스트림 무영향, score_eod는 8행 유지
# [RISE-BAND 2026-06-15 ★친구님] 종가매수 보드를 '바닥(직전5일최저) 대비 +10~30%' 종목만으로 선별(160단계 하드밴드).
#   rise=(현재가/5일저점-1)*100. 밴드밖 제외(계산불가는 유지=fail-open, 0종목이면 전체유지=스코어보드 안정).
#   ★종가매수 전용 — 눌림(rt_risk)은 PULLBACK_THEME_POOL=YES라 score_eod 안 읽음(무영향). 1년백테 누적 +187 vs 현행 +116%.
#   롤백 setx RISE_BAND_ENABLE NO. LO/HI 조정 setx RISE_BAND_LO/HI.
RISE_BAND_ENABLE = os.environ.get("RISE_BAND_ENABLE", "YES").strip().upper() == "YES"
RISE_BAND_LO = float(os.environ.get("RISE_BAND_LO", "10"))
RISE_BAND_HI = float(os.environ.get("RISE_BAND_HI", "30"))

# [THEME-TOP2 2026-06-16 ★친구님] ★160단계★ 테마당 거래대금 1~2위만 생존(부하 제거).
#   검증(36일): 테마 거래대금 1위 +0.92%·2위 +0.87% vs 3위 -1.10%·4위+ -1.02% → 3위↓=손해.
#   "테마당 2개"=대장+2등주 동행(한국시장 빈번). 3위↓ 부하만 컷. 롤백 setx THEME_TOP2_ENABLE NO.
THEME_TOP2_ENABLE = os.environ.get("THEME_TOP2_ENABLE", "YES").strip().upper() == "YES"
THEME_TOP2_MAX = int(os.environ.get("THEME_TOP2_MAX", "2"))            # 테마당 거래대금 상위 N위까지 생존
THEME_TOP2_MIN_KEEP = int(os.environ.get("THEME_TOP2_MIN_KEEP", "8"))  # 생존 이 미만이면 전체유지(fail-safe)
THEME_TOP2_SHADOW = os.environ.get("THEME_TOP2_SHADOW", "NO").strip().upper() == "YES"  # YES=관찰(로그만,실제거OFF)·NO=실제적용(라이브)
# [THEME-RESCUE 2026-06-05] make_rt가 rt_intraday에 넣은 강테마 대장주를 퍼널(step1/2/3) 컷에서 보존(rt_top20 구제셋 합류).
#   → score_eod_full 진입 → EOD_PICK 경쟁(가점). score_eod head(8)은 score_final 순이라 모멘텀 낮은 대장주는 8에 안 듦=회귀안전.
SCOREBOARD_THEME_RESCUE      = os.environ.get("SCOREBOARD_THEME_RESCUE", "YES").strip().upper() == "YES"
SCOREBOARD_THEME_RESCUE_MAX  = int(os.environ.get("SCOREBOARD_THEME_RESCUE_MAX", "12"))
SCOREBOARD_THEME_RESCUE_RANK = int(os.environ.get("SCOREBOARD_THEME_RESCUE_RANK", "20"))

# [SB-REPEAT 2026-06-13 친구님] score_eod head(8) 자르기 前 '반복등장(상위K 강한테마 겹침)'으로 재정렬.
#   score_eod = 종가매수 시그널 + 눌림 리스크(SB-FILTER 화이트리스트) 공통 입력 → 한 곳 수정으로 두 전략 동시 적용.
#   백테검증: 종가매수 1등갈린날 +1.03%p / 눌림 3개+겹침 3일후 +2.24% (둘다 단조). 강제X(점수 가산 후 재정렬). 기본 OFF.
#   안전: 데이터없음/오류 → 원본 순서 유지(무영향). 롤백 setx SB_REPEAT_ENABLE NO.
SB_REPEAT_ENABLE = os.environ.get("SB_REPEAT_ENABLE", "NO").strip().upper() == "YES"
SB_REPEAT_PTS    = float(os.environ.get("SB_REPEAT_PTS", "20"))   # 3개+ 겹침=만점 가점(score_final 0~100 스케일)
SB_REPEAT_TOP_K  = int(os.environ.get("SB_REPEAT_TOP_K", "15"))   # '상위 테마' 경계


def _load_sb_repeat_count() -> dict:
    """[SB-REPEAT] code -> 상위K 강한테마 멤버 겹침 횟수. theme_strength + theme_membership_naver 결합.
    실패/파일없음 → {} (가점 0 = 원본 유지, 무영향)."""
    try:
        _fs = DATA_DIR / "theme" / "theme_strength.csv"
        _fm = DATA_DIR / "theme" / "theme_membership_naver.csv"
        if not (_fs.exists() and _fm.exists()):
            return {}
        _ts = pd.read_csv(_fs, dtype=str)
        if _ts.empty or "theme_rank" not in _ts.columns or "date" not in _ts.columns:
            return {}
        _ts = _ts[_ts["date"] == _ts["date"].max()].copy()
        _ts["_rk"] = pd.to_numeric(_ts["theme_rank"], errors="coerce")
        _topk = set(_ts[_ts["_rk"] <= SB_REPEAT_TOP_K]["theme_name"].astype(str).str.strip())
        if not _topk:
            return {}
        _mm = pd.read_csv(_fm, dtype=str)
        _mm = _mm[_mm["theme_name"].astype(str).str.strip().isin(_topk)]
        return _mm.groupby(_mm["code"].astype(str).str.zfill(6)).size().to_dict()
    except Exception:
        return {}


def _theme_leader_set() -> set:
    """[THEME-RESCUE] code_theme_strength is_leader=1 & best_theme_rank<=RANK 코드.
    KOSDAQ 한정은 호출부 valid_codes 교집합(=KOSPI 자동제외). 실패→빈set(미적용)."""
    s = set()
    try:
        import csv as _csv
        _f2 = DATA_DIR / "theme" / "code_theme_strength.csv"
        if _f2.exists():
            with open(_f2, "r", encoding="utf-8-sig", errors="replace") as _fh:
                for _r in _csv.DictReader(_fh):
                    if str(_r.get("is_leader", "0")).strip() != "1":
                        continue
                    try:
                        _rk = int(float(_r.get("best_theme_rank", 999) or 999))
                    except (TypeError, ValueError):
                        _rk = 999
                    if _rk <= SCOREBOARD_THEME_RESCUE_RANK:
                        s.add(str(_r.get("code", "")).zfill(6))
    except Exception:
        pass
    return s
OUT5_PATH    = OUT_DIR / "score_eod_5.csv"
LOG_PATH    = DATA_DIR / "LOG" / "kjs_scoreboard_eod.log"

PRICES_3M_PATH    = DATA_DIR / "prices_3m.csv"
PRICES_1M_PATH    = DATA_DIR / "prices_1m.csv"
INVESTOR_PATH     = DATA_DIR / "investor_daily.csv"
PREV_DAY_PATH     = DATA_DIR / "prev_day_summary.csv"
SHARED_CACHE_PATH    = DATA_DIR / "eod_shared_data.pkl"
SIGA_CANDIDATES_PATH = BASE / "SIGA" / "DATA" / "siga_candidates.csv"

EVOLUTION_DIR          = DATA_DIR / "evolution"
EVOLVED_PARAMS_PATH    = EVOLUTION_DIR / "evolved_params.json"
EVOLUTION_FEEDBACK_DIR = EVOLUTION_DIR / "feedback"

SCORE_HISTORY_PATH = OUT_DIR / "score_history.csv"

# ═══════════════════════════════════════════════════════════════
#  기본 파라미터 (evolution_engine이 오버라이드 가능)
# ═══════════════════════════════════════════════════════════════
MIN_PRICE   = int(os.environ.get("MIN_PRICE", "500"))
MIN_CHG_PCT = float(os.environ.get("MIN_CHG", "-5.0"))
MAX_CHG_PCT = float(os.environ.get("MAX_CHG", "14.0"))
FILE_MAX_AGE_H = 6.0

# [v7.5 2026-04-15]
#   [FIX-1] siga_block_flag dominance 기준 1.1 → 1.15
#           1종목 몰빵 확신도 강화 - 2위 대비 15% 이상 우위 필요
#   [FIX-2] _update_prev_feedback 신규 - 전일 feedback 자동 갱신
#           next_day_open_ret / was_profitable 자동 기입
#           주말 대응 최대 5일 역탐색 / 이중 기입 방지
#           evolution_engine Kelly 재계산 완전 활성화
# [v7.4 FIX-1] 400→80→25→5 파이프라인 - 초기 그물 확대
# TOP_50: 50→80 - OFI 상위 20% 선별, edge 있는 종목 누락 방지
# TOP_20: 20→25 - stage2_score 동점 밴드 완화, step3 Hard Cut으로 자연 정리
TOP_50 = int(os.environ.get("TOP_50", "160"))  # step1_flow: 300→160
TOP_20 = int(os.environ.get("TOP_20", "80"))   # step2_struct: 160→80
TOP_5  = int(os.environ.get("TOP_5",  "25"))   # step3_defense: 80→25
# [HIST-WIDE 2026-05-30] score_history 저장범위 확대 — pullback_watch avg_rank≤8 변별력 복구용.
#   L3062 head(8) 절단 前 광역 랭킹(최대 25) 스냅샷을 따로 떠서 score_history에만 저장.
#   다운스트림(score_eod/bridge/EOD_PICK)은 head(8) 그대로 유지 → 행동 무변경.
SCORE_HISTORY_TOP_N = int(os.environ.get("SCORE_HISTORY_TOP_N", "25"))

# [FIX-8] OFI/BUY 윈도우 확장 - 코스닥 단일가(15:20~15:30) 포착
OFI_START  = 1400; OFI_MID  = 1511; OFI_END  = 1528  # [3-C 2026-05-11] 1500→1400. 5/11 prices_1m 15:00~15:28 종목 부족(2~5개)으로 STEP1 input 4개만 → 14:00부터 윈도우 확대해 input 풀 증가. early(14:00~15:11)/late(15:11~15:28) 의미 유지.
DYN_START  = 1508; DYN_MID  = 1513; DYN_END  = 1518
# [2026-06-09 CLOSEVAL FIX] 단일가(15:20~28=분봉0)→연속매매 막판(14:45~55)으로 이동.
#   ★종가매수 매수시점=14:55~15:05이라 "막판"=매수직전 14:45~14:55가 맞음.
#   기존 1520~28은 코스닥 단일가라 분봉 0개 → close_value_ratio/last5_value_accel 항상 0(고장).
#   롤백: BUY_START=1520 BUY_END=1528 PREV_START=1512.
BUY_START  = int(os.environ.get("SB_BUY_START", "1445")); BUY_END = int(os.environ.get("SB_BUY_END", "1455"))
PREV_START = int(os.environ.get("SB_PREV_START", "1435")); PREV_END = 1445

# ── Hard Cut (ANY → 탈락) ─────────────────────────────────────
HC_UPPER_WICK_MIN   = 0.975
HC_CLOSE_POS_MIN    = 0.78
HC_L5ACCEL_MIN      = 0.8
HC_L10ACCEL_MIN     = 0.40  # [v7_9 PATCH2] 10분 평균 대비 가속도 최소
HC_RANGE_ZSCORE_MAX = 1.8
HC_DAY_CHG_MAX      = 11.5
HC_FRGN_EXIT_THR    = -5000   # 외국인 이탈 임계값 (백만원)

# ── [FIX-3] 몰빵 전용 Conviction Gate - 소프트/하드 2단계 ─────
# SOFT: 이 기준 이상이면 SOFT_POSITION_RATIO 적용 후 진입
# [STANDARD] 현재 운영 기준 = 5.0 / 52.0 (확정). 과거 메모/문서의 7.0/70.0은 무효.
CONV_SOFT_GAP_MIN      = 5.0    # [TUNE-2] 6.5→5.0 진입 기회 추가 확대
CONV_SOFT_CONV_MIN     = 52.0   # [TUNE-3] 68.0→52.0 (gap≥5.0 통과 시 수학적 달성 가능 수준)
CONV_SOFT_POSITION     = 0.85   # [TUNE-1] 0.80→0.85 (BUG-D 상한 일치)
# HARD: 이 기준 이상이면 풀 포지션 (기존 값 유지)
CONV_WINNER_GAP_MIN    = 11.5
CONV_CONVICTION_MIN    = 82.0
# 절대 기준 (공격/방어 절대 하한)
CONV_ABS_SCORE_MIN     = 75.0
CONV_ABS_ATTACK_MIN    = 55.0
CONV_ABS_DEFENSE_MIN   = 60.0

# ── 히스토리 보너스 (최대 +6점 → [필수-6] 4+2 축소) ───────────
HIST_CONSEC_BONUS = 4.0   # [필수-6] 5.0→4.0
HIST_SLOPE_BONUS  = 2.0   # [필수-6] 3.0→2.0
HIST_RANK_WINDOW  = 20
HIST_KEEP_DAYS    = 60

# ── 몰빵 확신 등급 ────────────────────────────────────────────
ALLOUT_SCORE_MIN = 78.0   # [TUNE-7] 80.0→78.0 몰빵 빈도 +20~30%
ALLOUT_GAP_MIN   = 10.5   # [TUNE-7] 12.0→10.5

# ── 시장 리스크 캡 ────────────────────────────────────────────
MKT_WARN_PCT  = -1.5
MKT_HALT_PCT  = -2.5
STOCK_MIN_CHG = -3.0

# ── 공격 점수 절대 하한 ───────────────────────────────────────
# [FIX-V72-1] 40.0→55.0: 주석-코드 불일치 수정 (W1 의도와 일치)
ABS_S12_FLOOR = 55.0

# ── 갭업 예측 팩터 가중치 ────────────────────────────────────
GAP_VWAP_W      = 5.0
GAP_IMBALANCE_W = 6.0
GAP_CLOSE_DEV_W = 4.0

# ── 거래대금 폭발 팩터 가중치 ────────────────────────────────
VAL_RATIO_W = 10.0

# ── [FIX-4] gap_predict + inst_consec 복합 투입 비율 ─────────
POSITION_RATIO_TABLE = [
    (12.0, 1.00),
    (8.0,  0.85),
    (5.0,  0.70),
    (0.0,  0.60),
]
INST_POSITION_BOOST_MAX = 0.15  # inst_consec 보너스 최대 +15%

# ── [FIX-1] 출력 컬럼 - history_bonus 추가 (브릿지 호환) ──────
OUT_COLUMNS = [
    "rank", "code", "date", "score", "grade",
    "stage1_score", "stage2_score", "stage3_score",
    "attack_score", "defense_score",
    "ofi_accel", "vpin", "val_slope",
    "residual_momentum", "high60_ratio",
    "inst_consec", "net_buy_flag", "val_ratio",
    "close_position", "high_break",
    "volume_accel", "close_value_ratio", "last5_value_accel",
    "upper_wick_ratio", "day_chg_pct",
    "high_to_close_drop", "last15_value_ratio", "last30_value_ratio",  # [EOD-COLS 2026-06-06] 종가매수 보강
    "dyn_score", "dyn_hold_flag",
    "winner_gap", "conviction",
    "penalty_major", "weak_items",
    "gap_predict_score", "vwap_ratio", "last_imbalance",
    "mkt_risk_flag", "kosdaq_chg_pct",
    "dominance_ratio", "allout_signal",
    "position_ratio",
    "history_bonus",          # [FIX-1] 신규 추가 - 브릿지·진화엔진 전달
    "conv_mode",              # [FIX-3] "SOFT"/"HARD"/"FULL" - 진입 모드
    # ── [ADD-1] RT·시가 연결 prior 해석층 ────────────────────────
    "prior_class",            # ULTRA/STRONG/MID/WEAK
    "prior_weight",           # 순위+가산 복합 가중치 (0.00~1.10)
    "eod_pick_flag",          # rank≤5 → "Y", 기타 → "N"
    "schema_version",         # "scoreboard_eod_rtlink_v1"
    # ── [SCORE-1] score_final 최종 판단 점수 ─────────────────────
    "score_final",            # [v7_2] score(pre-bonus) + prior×5 + conv+dyn+hist_bonus - risk-gap_fail+market_adj
    "risk_penalty",           # 실패 리스크 감점 (윗꼬리/거래대금/종가위치)
    "gap_fail_penalty",       # [필수-3] 갭 실패 직접 감점 (0/2/4/6)
    "market_adj",             # [필수-2] 시장 상태 조정 (-5~+1)
    # ── [C3 v7.7] 브리지 EV 공급 — CSV 경로 완전 지원 ───────────
    "siga_ev_pct",            # top1 기준 SIGA ev_pct (브리지·execution_engine 참조용)
    "pullback_sharpe_proxy",  # top1 기준 pullback sharpe_proxy (브리지 모드 조정용)
    "siga_priority_score",    # [v9.9] 시가 브릿지 직접 전달 — score_eod.csv 포함
    "siga_entry_class",       # [v9.9] PRIME/WATCH/SKIP — 시가 브릿지 필터용
    "siga_score",             # [v7_9 DUAL] 시가전략 전용 점수 (0~100)
    "pullback_score",         # [v7_9 DUAL] 눌림목전략 전용 점수 (0~100)
    "strategy", "reason",
]

# ── [FIX-V72-7] 자기진화 단절 동결 플래그 ───────────────────────
# pnl_linker 5일+ 미연결 시 True → _load_evolved_params 스킵
EVOL_FREEZE: bool = False

# ── [ADD-1] prior_class 기준 [선택-1] 미세강화 ───────────────────
PRIOR_ULTRA_CONVICTION  = 82.0
PRIOR_ULTRA_WINNER_GAP  = 11.5
PRIOR_ULTRA_SCORE       = 80.0
PRIOR_STRONG_SCORE      = 81.0   # [TUNE-8] 82.0→81.0
PRIOR_MID_SCORE         = 75.0   # [TUNE-8] 76.0→75.0

# prior_weight 기본값 (rank 순)
PRIOR_WEIGHT_TABLE = {1: 1.00, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.40}
PRIOR_WEIGHT_ALLOUT_BONUS     = 0.10
PRIOR_WEIGHT_CONVICTION_BONUS = 0.05
PRIOR_WEIGHT_SCORE_BONUS      = 0.05
PRIOR_WEIGHT_MAX              = 1.10

# ── [SCORE-1] score_final 계산 상수 ──────────────────────────────
# [TUNE-4] PRIOR_MULT 5.0→5.8 (v7.2 이중증폭 차단 후 안전하게 상향)
# [TUNE-4] CONV_HIGH 1.5→2.0 / CONV_MID 0.7→1.0 (1등 차별화 심화)
SCORE_FINAL_PRIOR_MULT    = 5.8    # [TUNE-4] 5.0→5.8
SCORE_FINAL_CONV_HIGH     = 2.0    # [TUNE-4] 1.5→2.0
SCORE_FINAL_CONV_MID      = 1.0    # [TUNE-4] 0.7→1.0
SCORE_FINAL_CONV_HIGH_THR = 82.0
SCORE_FINAL_CONV_MID_THR  = 72.0
RISK_WICK_THR = 0.98
RISK_WICK_PEN = 1.5    # [TUNE-5] 2.0→1.5
RISK_L5A_THR  = 0.70
RISK_L5A_PEN  = 1.0    # [TUNE-5] 1.5→1.0
RISK_CP_THR   = 0.75
RISK_CP_PEN   = 1.0    # [TUNE-5] 1.5→1.0

# ── [필수-1] 몰빵 방지 추가 게이트 ──────────────────────────────
DOMINANCE_SOFT_THR   = 1.15   # [v7.5-FIX2] 1.10→1.15 (경계구간 패널티 강화 — 1.10~1.15 박빙 종목 position ×0.75)
WINNER_GAP_SOFT_THR  = 7.0    # [TUNE-2] 8.0→7.0

# ── [필수-3] 갭 실패 직접 감점 기준 ────────────────────────────
GAP_FAIL_LOW_THR      = 4.5   # [TUNE-6] 5.0→4.5
GAP_FAIL_VERY_LOW_THR = 2.5   # [TUNE-6] 3.0→2.5
GAP_FAIL_COMBO_CP     = 0.76  # [TUNE-6] 0.78→0.76
GAP_FAIL_COMBO_WICK   = 0.982 # [TUNE-6] 0.985→0.982

# ── [필수-8] position_ratio 최종 캡 기준 ─────────────────────────
POS_CAP_RISK_THR = 4.5    # [TUNE-3] 4.0→4.5
POS_CAP_RISK_MAX = 0.75   # [TUNE-3] 0.70→0.75
POS_CAP_GAP_THR  = 3.5    # [TUNE-3] 4.0→3.5
POS_CAP_GAP_MAX  = 0.65   # [TUNE-3] 0.60→0.65
POS_CAP_DOM_THR  = 1.08   # [TUNE-3] 1.10→1.08
POS_CAP_DOM_MAX  = 0.70   # [TUNE-3] 0.65→0.70

# ── 필수 컬럼 집합 (저장 전 검증용) ─────────────────────────────
REQUIRED_COLUMNS = {
    "rank","code","date","score","grade",
    "stage1_score","stage2_score","stage3_score",
    "attack_score","defense_score",
    "winner_gap","conviction","allout_signal","position_ratio",
    "strategy","reason","gap_predict_score",
    "mkt_risk_flag","kosdaq_chg_pct","dominance_ratio",
    "ofi_accel","vpin","val_slope","residual_momentum",
    "inst_consec","close_position","high_break",
    "volume_accel","close_value_ratio","last5_value_accel",
    "upper_wick_ratio","day_chg_pct",
    "prior_class","prior_weight","eod_pick_flag","schema_version",
    "score_final","risk_penalty","gap_fail_penalty","market_adj","conv_mode",  # [v7_1] 신규
    "siga_ev_pct","pullback_sharpe_proxy",  # [C3 v7.7] 브리지 EV 공급 CSV 경로
}


# ═══════════════════════════════════════════════════════════════
#  자기 진화 - 파라미터 로딩 & 피드백 기록
# ═══════════════════════════════════════════════════════════════
def _load_evolved_params(logger: logging.Logger) -> dict:
    """
    params_reader.py 경유 로딩 - mtime 캐시·파일락 활용
    params_reader 임포트 실패 시 직접 json.load로 폴백 (절대 중단 없음)
    [FIX-V72-7] EVOL_FREEZE=True 이면 파라미터 변경 없이 즉시 반환
    """
    global CONV_WINNER_GAP_MIN, CONV_CONVICTION_MIN
    global CONV_ABS_SCORE_MIN, CONV_ABS_ATTACK_MIN, CONV_ABS_DEFENSE_MIN
    global CONV_SOFT_GAP_MIN, CONV_SOFT_CONV_MIN, CONV_SOFT_POSITION
    global HC_UPPER_WICK_MIN, HC_CLOSE_POS_MIN, HC_RANGE_ZSCORE_MAX
    global ALLOUT_SCORE_MIN, ABS_S12_FLOOR
    global GAP_VWAP_W, GAP_IMBALANCE_W, GAP_CLOSE_DEV_W
    global HIST_CONSEC_BONUS, HIST_SLOPE_BONUS

    # [FIX-V72-7] 자기진화 단절 동결 - 수익률 미기입 5일+ 시 파라미터 변경 금지
    if EVOL_FREEZE:
        logger.warning("[EVOL-FREEZE] pnl_linker 단절로 파라미터 동결 중 → 기본값 유지")
        return {}

    p: dict = {}
    try:
        _pr_path = BASE / "RUN" / "params_reader.py"
        if _pr_path.exists():
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("params_reader", str(_pr_path))
            pr   = _ilu.module_from_spec(spec)   # type: ignore
            spec.loader.exec_module(pr)           # type: ignore
            p = pr.get_params() or {}
            logger.info("[EVOL] params_reader 경유 로딩 성공 | keys=%d", len(p))
        elif EVOLVED_PARAMS_PATH.exists():
            with open(EVOLVED_PARAMS_PATH, "r", encoding="utf-8-sig") as f:
                p = json.load(f)
            logger.info("[EVOL] 직접 json 로딩 (params_reader 없음) | keys=%d", len(p))
        else:
            logger.info("[EVOL] evolved_params 없음 → 기본값 유지")
            return {}
    except Exception as e:
        logger.warning("[EVOL] 파라미터 로딩 실패 → 기본값 유지: %s", e)
        return {}

    try:
        if "winner_gap_min" in p:
            CONV_WINNER_GAP_MIN  = max(6.0, min(15.0, float(p["winner_gap_min"])))
        if "conviction_min" in p:
            CONV_CONVICTION_MIN  = max(65.0, min(92.0, float(p["conviction_min"])))
        if "soft_gap_min" in p:
            # [TUNE-1] 하한 5.0→4.5 (CONV_SOFT_GAP_MIN 6.5 기준 자기진화 여유)
            CONV_SOFT_GAP_MIN    = max(4.5, min(CONV_WINNER_GAP_MIN, float(p["soft_gap_min"])))
        if "soft_conv_min" in p:
            # [TUNE-3] 하한 53.0→52.0
            CONV_SOFT_CONV_MIN   = max(52.0, min(CONV_CONVICTION_MIN, float(p["soft_conv_min"])))
        if "soft_position" in p:
            CONV_SOFT_POSITION   = max(0.50, min(0.85, float(p["soft_position"])))  # [BUG-D] 0.90→0.85
        if "abs_score_min" in p:
            CONV_ABS_SCORE_MIN   = max(60.0, min(85.0, float(p["abs_score_min"])))
        if "abs_attack_min" in p:
            CONV_ABS_ATTACK_MIN  = max(40.0, min(65.0, float(p["abs_attack_min"])))
        if "hc_upper_wick_min" in p:
            HC_UPPER_WICK_MIN    = max(0.970, min(0.995, float(p["hc_upper_wick_min"])))
        if "hc_close_pos_min" in p:
            HC_CLOSE_POS_MIN     = max(0.65,  min(0.90,  float(p["hc_close_pos_min"])))
        if "allout_score_min" in p:
            ALLOUT_SCORE_MIN     = max(70.0, min(92.0, float(p["allout_score_min"])))
        if "abs_s12_floor" in p:
            ABS_S12_FLOOR        = max(25.0, min(60.0, float(p["abs_s12_floor"])))
        if "gap_vwap_w" in p:
            GAP_VWAP_W           = max(2.0, min(10.0, float(p["gap_vwap_w"])))
        if "gap_imbalance_w" in p:
            GAP_IMBALANCE_W      = max(2.0, min(12.0, float(p["gap_imbalance_w"])))
        if "gap_close_dev_w" in p:
            GAP_CLOSE_DEV_W      = max(1.0, min(8.0,  float(p["gap_close_dev_w"])))
        if "hc_range_zscore_max" in p:
            HC_RANGE_ZSCORE_MAX  = max(1.2, min(2.5, float(p["hc_range_zscore_max"])))
        if "abs_defense_min" in p:
            CONV_ABS_DEFENSE_MIN = max(40.0, min(70.0, float(p["abs_defense_min"])))
        if "hist_consec_bonus" in p:
            HIST_CONSEC_BONUS    = max(0.0, min(8.0, float(p["hist_consec_bonus"])))
        if "hist_slope_bonus" in p:
            HIST_SLOPE_BONUS     = max(0.0, min(5.0, float(p["hist_slope_bonus"])))

        ver    = p.get("version", "unknown")
        sharpe = p.get("sharpe", 0.0)
        logger.info("[EVOL] 파라미터 적용 완료 | ver=%s sharpe=%.2f "
                    "hard_gap=%.1f soft_gap=%.1f conviction=%.1f",
                    ver, sharpe, CONV_WINNER_GAP_MIN,
                    CONV_SOFT_GAP_MIN, CONV_CONVICTION_MIN)
    except Exception as e:
        logger.warning("[EVOL] 파라미터 적용 실패 → 기본값 유지: %s", e)

    return p


def _write_hold_feedback(stage: str, reason: str,
                          today_str: str, logger: logging.Logger) -> None:
    try:
        EVOLUTION_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        fb_path = EVOLUTION_FEEDBACK_DIR / f"hold_{today_str}.json"
        if fb_path.exists():
            return
        fb = {
            "date":        today_str,
            "result":      "HOLD",
            "hold_stage":  stage,
            "hold_reason": reason,
            "params_used": {
                "winner_gap_min":    CONV_WINNER_GAP_MIN,
                "soft_gap_min":      CONV_SOFT_GAP_MIN,
                "conviction_min":    CONV_CONVICTION_MIN,
                "soft_conv_min":     CONV_SOFT_CONV_MIN,
                "abs_score_min":     CONV_ABS_SCORE_MIN,
                "hc_l5accel_min":    HC_L5ACCEL_MIN,
                "abs_s12_floor":     ABS_S12_FLOOR,
            }
        }
        with open(fb_path, "w", encoding="utf-8") as f:
            json.dump(fb, f, ensure_ascii=False, indent=2)
        logger.info("[EVOL] HOLD 피드백 기록: stage=%s reason=%s", stage, reason)
    except Exception as e:
        logger.warning("[EVOL] HOLD 피드백 기록 실패: %s", e)


def _write_evolution_feedback(result_df: pd.DataFrame,
                               today_str: str,
                               logger: logging.Logger) -> None:
    if result_df.empty:
        return
    try:
        EVOLUTION_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        fb_path = EVOLUTION_FEEDBACK_DIR / f"feedback_{today_str}.json"

        if fb_path.exists():
            try:
                with open(fb_path, "r", encoding="utf-8-sig") as f:
                    existing = json.load(f)
                if existing.get("next_day_open_ret") is not None:
                    logger.info("[EVOL] 피드백 이미 완성됨 → 덮어쓰기 생략: %s", fb_path.name)
                    return
                logger.info("[EVOL] 미완성 피드백 → 최신 데이터로 덮어씀: %s", fb_path.name)
            except Exception:
                pass

        top = result_df.iloc[0]
        fb = {
            "date":             today_str,
            "selected_code":    str(top.get("code", "")),
            "score":            float(top.get("score", 0)),
            "grade":            str(top.get("grade", "")),
            "winner_gap":       float(top.get("winner_gap", 0)),
            "conviction":       float(top.get("conviction", 0)),
            "conv_mode":        str(top.get("conv_mode", "UNKNOWN")),  # [FIX-3]
            "attack_score":     float(top.get("attack_score", 0)),
            "defense_score":    float(top.get("defense_score", 0)),
            "dominance_ratio":  float(top.get("dominance_ratio", 1.0)),
            "allout_signal":    int(top.get("allout_signal", 0)),
            "strategy":         str(top.get("strategy", "")),
            "ofi_accel":        float(top.get("ofi_accel", 0)),
            "vpin":             float(top.get("vpin", 0)),
            "inst_consec":      int(top.get("inst_consec", 0)),
            "gap_predict":      float(top.get("gap_predict_score", 0)),
            "close_position":   float(top.get("close_position", 0)),
            "high_break":       float(top.get("high_break", 0)),
            "val_ratio":        float(top.get("val_ratio", 1.0)),
            "upper_wick_ratio": float(top.get("upper_wick_ratio", 1.0)),
            "last5_val_accel":  float(top.get("last5_value_accel", 0)),
            "residual_momentum":float(top.get("residual_momentum", 0)),
            "history_bonus":    float(top.get("history_bonus", 0.0)),  # [FIX-1]
            "position_ratio":   float(top.get("position_ratio", 0.6)),
            # ── [SCORE-1] score_final 기준 학습 필드 추가 ────────
            "score_final":      float(top.get("score_final", 0.0)),
            "risk_penalty":     float(top.get("risk_penalty", 0.0)),
            "prior_class":      str(top.get("prior_class", "WEAK")),
            "prior_weight":     float(top.get("prior_weight", 0.0)),
            # ── [v7_1] 신규 지표 - evolution 학습 필수 ───────────
            "gap_fail_penalty": float(top.get("gap_fail_penalty", 0.0)),
            "market_adj":       float(top.get("market_adj", 0.0)),
            "dyn_score":        float(top.get("dyn_score", 0.0)),
            # evolution_engine이 다음날 채우는 필드
            "next_day_open_ret":  None,
            "next_day_max_ret":   None,
            "next_day_close_ret": None,
            "was_profitable":     None,
            "params_used": {
                "winner_gap_min":    CONV_WINNER_GAP_MIN,
                "soft_gap_min":      CONV_SOFT_GAP_MIN,
                "conviction_min":    CONV_CONVICTION_MIN,
                "soft_conv_min":     CONV_SOFT_CONV_MIN,
                "abs_score_min":     CONV_ABS_SCORE_MIN,
                "hc_upper_wick_min": HC_UPPER_WICK_MIN,
                "hc_close_pos_min":  HC_CLOSE_POS_MIN,
                "gap_vwap_w":        GAP_VWAP_W,
                "gap_imbalance_w":   GAP_IMBALANCE_W,
                "gap_close_dev_w":   GAP_CLOSE_DEV_W,
                "hist_consec_bonus": HIST_CONSEC_BONUS,
                "hist_slope_bonus":  HIST_SLOPE_BONUS,
                # ── [v7_1] 신규 파라미터 ──────────────────────────
                "dominance_soft_thr":    DOMINANCE_SOFT_THR,
                "winner_gap_soft_thr":   WINNER_GAP_SOFT_THR,
                "score_final_prior_mult":SCORE_FINAL_PRIOR_MULT,
                "score_final_conv_high": SCORE_FINAL_CONV_HIGH,
                "score_final_conv_mid":  SCORE_FINAL_CONV_MID,
                "pos_cap_risk_thr":      POS_CAP_RISK_THR,
                "pos_cap_gap_thr":       POS_CAP_GAP_THR,
                "pos_cap_dom_thr":       POS_CAP_DOM_THR,
            }
        }
        with open(fb_path, "w", encoding="utf-8") as f:
            json.dump(fb, f, ensure_ascii=False, indent=2)
        logger.info("[EVOL] 피드백 기록 완료: %s", fb_path.name)
    except Exception as e:
        logger.warning("[EVOL] 피드백 기록 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════
def _safe_mkdir(p: Path) -> None:
    try: p.mkdir(parents=True, exist_ok=True)
    except Exception as e: print(f"[SETUP][FAIL] 디렉토리 생성 실패 {p}: {e}")

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("kjs_scoreboard_eod")
    if logger.handlers: return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt); logger.addHandler(sh)
    except Exception as e: print(f"[SETUP][FAIL] StreamHandler 추가 실패: {e}")
    try:
        _safe_mkdir(LOG_PATH.parent)
        fh = RotatingFileHandler(str(LOG_PATH), maxBytes=10*1024*1024,
                                 backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt); logger.addHandler(fh)
    except Exception as e: print(f"[SETUP][FAIL] FileHandler 추가 실패: {e}")
    return logger

def _norm_code(x: Any) -> str:
    s = "" if x is None else str(x).strip()
    d = "".join(c for c in s if c.isdigit())
    return d.zfill(6) if 1 <= len(d) <= 6 else s

def _f(x: Any, d: float = 0.0) -> float:
    try: return float(str(x).replace(",", ""))
    except: return d

def _grade(s: float) -> str:
    if s >= 88: return "S"
    if s >= 80: return "A"
    if s >= 70: return "B"
    if s >= 55: return "C"
    if s >= 40: return "D"
    return "E"

def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    _safe_mkdir(path.parent)
    tmp = path.with_suffix(".tmp")
    try:
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(path))
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception as e: logging.getLogger("kjs_scoreboard_eod").warning("[FAIL] tmp 정리 실패: %s", e)

def _read_csv(path: Path, logger: logging.Logger) -> Optional[pd.DataFrame]:
    if not path.exists() or path.stat().st_size == 0: return None
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try: return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception: continue
    logger.warning("[LOAD] 읽기 실패: %s", path.name)
    return None

def _parse_ts(s: pd.Series) -> pd.Series:
    try:
        ss = s.astype(str).str.strip()
        m14 = ss.str.fullmatch(r"\d{14}")
        if m14.any():
            dt = pd.Series(pd.NaT, index=s.index)
            dt.loc[m14] = pd.to_datetime(ss.loc[m14], format="%Y%m%d%H%M%S", errors="coerce")
            if dt.notna().sum() >= len(s) * 0.8: return dt
        return pd.to_datetime(ss, errors="coerce")
    except Exception: return pd.to_datetime(s, errors="coerce")

def _unwrap_cumval(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    v = s.dropna()
    if v.empty: return s
    if (v.diff().fillna(0) >= 0).mean() > 0.95 and v.max() > 1e10:
        return s.diff().where(s.diff().notna(), s).clip(lower=0)
    return s


# ═══════════════════════════════════════════════════════════════
#  데이터 로드
# ═══════════════════════════════════════════════════════════════
def _load_prices(path: Path, logger: logging.Logger) -> Optional[pd.DataFrame]:
    df = _read_csv(path, logger)
    if df is None or df.empty: return None
    cols = {str(c).lower(): c for c in df.columns}
    ts_c    = next((cols[k] for k in ["ts","time","datetime","date"] if k in cols), None)
    code_c  = next((cols[k] for k in ["code","ticker","symbol"] if k in cols), None)
    close_c = next((cols[k] for k in ["close","c"] if k in cols), None)
    if not (ts_c and code_c and close_c):
        logger.warning("[LOAD] %s 필수 컬럼 없음", path.name); return None
    close_s = pd.to_numeric(df[close_c], errors="coerce")
    open_c  = next((cols[k] for k in ["open","o"] if k in cols), None)
    high_c  = next((cols[k] for k in ["high","h"] if k in cols), None)
    low_c   = next((cols[k] for k in ["low","l"]  if k in cols), None)
    out = pd.DataFrame({
        "ts":    _parse_ts(df[ts_c]),
        "code":  df[code_c].apply(_norm_code),
        "open":  pd.to_numeric(df[open_c], errors="coerce") if open_c else close_s,
        "high":  pd.to_numeric(df[high_c], errors="coerce") if high_c else close_s,
        "low":   pd.to_numeric(df[low_c],  errors="coerce") if low_c  else close_s,
        "close": close_s,
    })
    val_c = next((cols[k] for k in ["value","acc_value","trade_value"] if k in cols), None)
    out["value"] = pd.to_numeric(df[val_c], errors="coerce") if val_c else 0.0
    out = out.dropna(subset=["ts","code","close"]).sort_values(["code","ts"])
    out["value"] = out.groupby("code", sort=False)["value"].transform(_unwrap_cumval)
    out["date"]  = out["ts"].dt.strftime("%Y-%m-%d")
    out["hm"]    = out["ts"].dt.hour * 100 + out["ts"].dt.minute
    logger.info("[LOAD] %s rows=%d codes=%d", path.name, len(out), out["code"].nunique())
    return out

def _load_investor(logger: logging.Logger) -> pd.DataFrame:
    df = _read_csv(INVESTOR_PATH, logger)
    if df is None or df.empty: return pd.DataFrame()
    cols = {str(c).lower(): c for c in df.columns}
    code_c = next((cols[k] for k in ["code","ticker"] if k in cols), None)
    if not code_c: return pd.DataFrame()
    df = df.copy()
    df["code"]    = df[code_c].apply(_norm_code)
    df["date"]    = pd.to_datetime(df.get("date",""), errors="coerce")
    inst_c = next((cols[k] for k in ["inst_net","inst"] if k in cols), None)
    frgn_c = next((cols[k] for k in ["frgn_net","foreign_net","frgn"] if k in cols), None)
    df["inst_net"] = pd.to_numeric(df[inst_c], errors="coerce").fillna(0) if inst_c else 0.0
    df["frgn_net"] = pd.to_numeric(df[frgn_c], errors="coerce").fillna(0) if frgn_c else 0.0
    df["net_buy"]  = df["inst_net"] + df["frgn_net"]
    return df.dropna(subset=["code","date"]).sort_values(["code","date"])

def _load_prev_day(logger: logging.Logger) -> pd.DataFrame:
    df = _read_csv(PREV_DAY_PATH, logger)
    if df is None or df.empty:
        logger.info("[LOAD] prev_day_summary 없음 → 전일 팩터 스킵")
        return pd.DataFrame()
    cols = {str(c).lower(): c for c in df.columns}
    code_c = next((cols[k] for k in ["code","ticker"] if k in cols), None)
    if not code_c: return pd.DataFrame()
    out = pd.DataFrame()
    out["code"] = df[code_c].apply(_norm_code)
    for alias, key in [("prev_high",["prev_high","high"]),
                       ("prev_low", ["prev_low","low"]),
                       ("prev_close",["prev_close","close"])]:
        c = next((cols[k] for k in key if k in cols), None)
        out[alias] = pd.to_numeric(df[c], errors="coerce").fillna(0) if c else 0.0
    return out.dropna(subset=["code"])


# ═══════════════════════════════════════════════════════════════
#  STEP 0 : 데이터 신선도 검증
# ═══════════════════════════════════════════════════════════════
def step0_check(logger: logging.Logger) -> Tuple[bool, int]:
    p = PRICES_3M_PATH
    try:
        _st3 = p.stat()
    except FileNotFoundError:
        logger.error("[STEP0] prices_3m.csv 없음 → RC=22")
        return False, RC_STOP22
    if _st3.st_size == 0:
        logger.error("[STEP0] prices_3m.csv 0바이트 → RC=22")
        return False, RC_STOP22
    age_h = (time.time() - _st3.st_mtime) / 3600.0
    if age_h > FILE_MAX_AGE_H:
        logger.error("[STEP0] prices_3m.csv %.1f시간 경과 → RC=HOLD", age_h)
        return False, RC_HOLD
    try:
        _st1 = PRICES_1M_PATH.stat()
        if _st1.st_size > 0:
            age_1m = (time.time() - _st1.st_mtime) / 3600.0
            if age_1m > FILE_MAX_AGE_H:
                logger.warning("[STEP0] prices_1m.csv %.1f시간 경과 → prices_3m으로 대체", age_1m)
            else:
                logger.info("[STEP0] prices_1m OK (%.1f시간)", age_1m)
    except FileNotFoundError:
        pass
    logger.info("[STEP0] 데이터 OK (3m=%.1f시간)", age_h)
    return True, RC_OK


# ═══════════════════════════════════════════════════════════════
#  STEP 1 : 400→50  "지금 돈이 몰리고 있는가?" - 공격(시장흐름)
#  OFI 가속도(20) + 거래대금 기울기(15) + VPIN(10) = 45점
# ═══════════════════════════════════════════════════════════════
def step1_flow(px_today: pd.DataFrame, valid_codes: set,
               logger: logging.Logger,
               rt_edge_map: dict = None, rt_top20: set = None) -> pd.DataFrame:
    """OFI 가속도(20) + 거래대금 기울기(15) + VPIN(10) = 45점
    [FIX-8] OFI_END=1528 확장 - 코스닥 단일가 구간 데이터 포착
    """
    window = px_today[
        px_today["code"].isin(valid_codes) &
        (px_today["hm"] >= OFI_START) &
        (px_today["hm"] <= OFI_END)
    ].copy()

    if window.empty:
        logger.warning("[STEP1] 15:00~15:28 데이터 없음")
        return pd.DataFrame()

    rows = []
    for code, g in window.groupby("code", sort=False):
        g = g.sort_values("ts").copy()
        rng = (g["high"] - g["low"]).clip(lower=1.0)
        g["ofi_bar"] = ((g["close"] - g["open"]) / rng).clip(-1.0, 1.0)

        # OFI 거래대금 가중평균
        g["wt"] = pd.to_numeric(g["value"], errors="coerce").fillna(0.0).clip(lower=0.0)

        early = g[g["hm"] < OFI_MID]
        late  = g[g["hm"] >= OFI_MID]
        def _wm(g_): w=g_["wt"].values; v=g_["ofi_bar"].values; return float(np.average(v,weights=w)) if w.sum()>0 else float(v.mean()) if len(v) else 0.0
        ofi_e = _wm(early) if not early.empty else 0.0
        ofi_l = _wm(late)  if not late.empty  else 0.0
        ofi_accel = ofi_l - ofi_e
        score_ofi = min(max((ofi_accel + 0.2) / 0.7, 0.0), 1.0) * 20.0

        # 거래대금 기울기 (OLS)
        score_slope = 0.0; val_slope = 0.0
        if len(g) >= 3:
            try:
                x = np.arange(len(g), dtype=float)
                y = g["value"].values.astype(float)
                mean_y = max(y.mean(), 1.0)
                coeffs = np.polyfit(x, y, 1)
                val_slope = float(coeffs[0])
                score_slope = min(max(val_slope / mean_y / 0.1, 0.0), 1.0) * 15.0
            except Exception as e: logging.getLogger("kjs_scoreboard_eod").warning("[SLOPE][FAIL] 기울기 계산 실패: %s", e)

        # [FIX-V72-3] buy_pressure_ratio (VPIN 근사치)
        # ※ 주의: 논문 VPIN(Easley et al. 2012)과 다름 - 상승봉 거래대금 비율로 근사
        # 실제 호가창(Level2) 데이터 확보 시 True VPIN으로 교체 필요
        total_val = float(g["value"].sum())
        up_val    = float(g.loc[g["close"] > g["open"], "value"].sum())
        vpin      = up_val / (total_val + 1e-9)  # buy_pressure_ratio (컬럼명 vpin 유지)
        score_vpin = min(max((vpin - 0.35) / 0.27, 0.0), 1.0) * 10.0

        stage1_score = round(score_ofi + score_slope + score_vpin, 2)
        rows.append({
            "code":          code,
            "ofi_accel":     round(ofi_accel, 4),
            "val_slope":     round(val_slope, 0),
            "vpin":          round(vpin, 4),
            "stage1_score":  stage1_score,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # [v7_B2] RT expected_edge 가산 (최대 +15점)
    if rt_edge_map:
        _edge_s = pd.Series(rt_edge_map)
        _e_min, _e_max = float(_edge_s.min()), float(_edge_s.max())
        _e_range = max(_e_max - _e_min, 1e-9)
        df["_rt_bonus"] = df["code"].map(rt_edge_map).fillna(0.0)
        df["_rt_bonus"] = ((df["_rt_bonus"] - _e_min) / _e_range * 15.0).clip(0, 15)
        df["stage1_score"] = (df["stage1_score"] + df["_rt_bonus"]).round(2)
        df = df.drop(columns=["_rt_bonus"])

    df = df.sort_values("stage1_score", ascending=False)

    # [v7_B2] RT top20 step1 통과 보장
    if rt_top20:
        _top_n1 = set(df.head(TOP_50)["code"].tolist())
        _rescued1 = (rt_top20 & set(df["code"].tolist())) - _top_n1
        if _rescued1:
            _df1_main   = df.head(TOP_50)
            _df1_rescue = df[df["code"].isin(_rescued1)]
            df = pd.concat([_df1_main, _df1_rescue]).drop_duplicates(subset=["code"], keep="first")
            logger.info("[STEP1][RT보장] top20 구제=%d개: %s", len(_rescued1), list(_rescued1)[:5])
        else:
            df = df.head(TOP_50)
    else:
        df = df.head(TOP_50)

    df = df.reset_index(drop=True)
    logger.info("[STEP1] 400→%d  max=%.1f min=%.1f  top5=%s",
               len(df),
               float(df["stage1_score"].max()) if not df.empty else 0,
               float(df["stage1_score"].min()) if not df.empty else 0,
               df["code"].head(5).tolist())
    return df


# ═══════════════════════════════════════════════════════════════
#  STEP 2 : 50→20  "가격 구조가 탄탄한가?" - 공격(구조+수급)
#  [FIX-5] stage2_score clip 65 → 75 - 팩터 변별력 복구
# ═══════════════════════════════════════════════════════════════
def step2_struct(px3: pd.DataFrame, px_today: pd.DataFrame,
                 step1_df: pd.DataFrame, inv: pd.DataFrame,
                 today_str: str, mkt_avg: float,
                 logger: logging.Logger,
                 prev_day: pd.DataFrame = None,
                 rt_top20: set = None) -> pd.DataFrame:
    """잔차·신고가·기관·갭예측·val_ratio·전일고점돌파 스코어링
    [FIX-5] 합산 상한 65→75점 - 기관/잔차모멘텀 실질 차별화 복구
    """
    codes = set(step1_df["code"].tolist())
    px_sub = px_today[px_today["code"].isin(codes)].copy()

    today_agg = px_sub.groupby("code").agg(
        day_open  = ("open",  "first"),
        day_high  = ("high",  "max"),
        day_low   = ("low",   "min"),
        day_close = ("close", "last"),
    ).reset_index()

    today_agg["day_chg_pct"] = (
        (today_agg["day_close"] / (today_agg["day_open"] + 1e-9) - 1.0) * 100.0
    )
    today_agg["residual_momentum"] = today_agg["day_chg_pct"] - mkt_avg
    today_agg["score_rm"] = (
        (today_agg["residual_momentum"].clip(-3, 5) + 3) / 8.0 * 10.0
    ).clip(0, 10)

    # close_position, high_break
    rng = (today_agg["day_high"] - today_agg["day_low"]).clip(lower=1.0)
    today_agg["close_position"] = (
        (today_agg["day_close"] - today_agg["day_low"]) / rng
    ).clip(0, 1)
    today_agg["high_break"] = (
        today_agg["day_close"] / (today_agg["day_high"] + 1e-9)
    ).clip(0, 1.05)

    # volume_accel, last5_value_accel, close_value_ratio
    # [FIX-8] BUY_START=1520, BUY_END=1528
    prev_px = px_sub[(px_sub["hm"] >= PREV_START) & (px_sub["hm"] < BUY_START)]
    last_px = px_sub[(px_sub["hm"] >= BUY_START)  & (px_sub["hm"] <= BUY_END)]

    prev_sum = prev_px.groupby("code")["value"].sum().reset_index(name="v_prev")
    last_sum = last_px.groupby("code")["value"].sum().reset_index(name="v_last")
    last_bar = last_px.groupby("code")["value"].last().reset_index(name="v_last_bar")
    win_sum  = last_px.groupby("code")["value"].sum().reset_index(name="v_win")

    va = prev_sum.merge(last_sum, on="code", how="outer").fillna(0)
    va["volume_accel"] = va["v_last"] / (va["v_prev"] + 1.0)

    # last5_value_accel: 마지막 구간 거래대금 / OFI 전체 구간 평균 대금
    ofi_total = px_sub[
        (px_sub["hm"] >= OFI_START) & (px_sub["hm"] < BUY_START)
    ].groupby("code")["value"].sum().reset_index(name="v_ofi_total")
    # OFI 구간: 15:00~15:20 = 20분 → 5분봉 4개 → /4.0
    ofi_total["v_ofi_per5min"] = ofi_total["v_ofi_total"] / 4.0
    l5a_merged = last_sum.merge(ofi_total[["code", "v_ofi_per5min"]], on="code", how="left")
    l5a_merged["last5_value_accel"] = (
        l5a_merged["v_last"] / (l5a_merged["v_ofi_per5min"].fillna(1.0) + 1.0)
    )
    va = va.merge(l5a_merged[["code", "last5_value_accel"]], on="code", how="left")
    va["last5_value_accel"] = va["last5_value_accel"].fillna(0.0)

    # [v7_9 PATCH2] last10_value_accel: BUY window vs OFI 10분 평균 (v_ofi_total/2)
    l10a_merged = last_sum.merge(ofi_total[["code", "v_ofi_total"]], on="code", how="left")
    l10a_merged["last10_value_accel"] = (
        l10a_merged["v_last"] / (l10a_merged["v_ofi_total"].fillna(2.0) / 2.0 + 1.0)
    )
    va = va.merge(l10a_merged[["code", "last10_value_accel"]], on="code", how="left")
    va["last10_value_accel"] = va["last10_value_accel"].fillna(0.0)

    cvr = last_bar.merge(win_sum, on="code", how="outer").fillna(0)
    cvr["close_value_ratio"] = (cvr["v_last_bar"] / (cvr["v_win"] + 1.0)).clip(0, 1)

    today_agg = today_agg.merge(va[["code","volume_accel","last5_value_accel","last10_value_accel"]], on="code", how="left")
    today_agg = today_agg.merge(cvr[["code","close_value_ratio"]], on="code", how="left")
    for c in ["volume_accel","last5_value_accel","last10_value_accel","close_value_ratio"]:
        today_agg[c] = today_agg[c].fillna(0.0)

    # 윗꼬리 비율 (마지막 3봉)
    def _wick(g):
        t3 = g.sort_values("ts").tail(3)
        h3  = float(t3["high"].max())
        c_l = float(t3["close"].iloc[-1])
        return pd.Series({"upper_wick_ratio": round(c_l / (h3 + 1e-9), 4)})
    try:
        try:
            wick_df = px_sub.groupby("code").apply(_wick, include_groups=False).reset_index()
        except TypeError:
            wick_df = px_sub.groupby("code").apply(_wick).reset_index()
        today_agg = today_agg.merge(wick_df, on="code", how="left")
    except Exception:
        today_agg["upper_wick_ratio"] = 1.0
    today_agg["upper_wick_ratio"] = today_agg["upper_wick_ratio"].fillna(1.0)

    # [EOD-COLS 2026-06-06] 종가매수 보강 3컬럼 (사용자: 매수 14:55~15:05 → 막판창 14:40~14:55 기준).
    #   high_to_close_drop  = (당일고가-종가)/당일고가  (급등후 종가밀림=클수록 나쁨, 0~1)
    #   last15_value_ratio  = 막판15분(1440~1455) 분당평균 거래대금 / 당일 분당평균  (>1=막판 유입)
    #   last30_value_ratio  = 막판30분(1425~1455) 분당평균 거래대금 / 당일 분당평균
    #   데이터/봉 없으면 0 fallback(보수). score_eod 8행 다운스트림은 _eod_gf 0fallback이라 안전.
    today_agg["high_to_close_drop"] = (
        (today_agg["day_high"] - today_agg["day_close"]) / (today_agg["day_high"] + 1e-9)
    ).clip(0, 1).fillna(0.0)
    try:
        _dall = px_sub.groupby("code")["value"].agg(["sum", "count"]).reset_index()
        _dall_vmean = _dall.assign(day_vmean=_dall["sum"] / _dall["count"].clip(lower=1))[["code", "day_vmean"]]

        def _winmean(s_hm, e_hm, name):
            w = px_sub[(px_sub["hm"] >= s_hm) & (px_sub["hm"] <= e_hm)]
            g = w.groupby("code")["value"].agg(["sum", "count"]).reset_index()
            g[name] = g["sum"] / g["count"].clip(lower=1)
            return g[["code", name]]

        _l15 = _winmean(1440, 1455, "_l15_vmean")
        _l30 = _winmean(1425, 1455, "_l30_vmean")
        today_agg = (today_agg.merge(_dall_vmean, on="code", how="left")
                              .merge(_l15, on="code", how="left")
                              .merge(_l30, on="code", how="left"))
        today_agg["last15_value_ratio"] = (today_agg["_l15_vmean"] / (today_agg["day_vmean"] + 1e-9)).fillna(0.0)
        today_agg["last30_value_ratio"] = (today_agg["_l30_vmean"] / (today_agg["day_vmean"] + 1e-9)).fillna(0.0)
        today_agg = today_agg.drop(columns=["day_vmean", "_l15_vmean", "_l30_vmean"], errors="ignore")
    except Exception:
        today_agg["last15_value_ratio"] = 0.0
        today_agg["last30_value_ratio"] = 0.0
    for _c in ("high_to_close_drop", "last15_value_ratio", "last30_value_ratio"):
        today_agg[_c] = pd.to_numeric(today_agg[_c], errors="coerce").fillna(0.0)

    # 60일 신고가 - 돌파 종목 집중 우대
    px3_sub = px3[px3["code"].isin(codes)].copy()
    high60 = px3_sub.groupby("code")["high"].max().reset_index(name="high_60")
    today_agg = today_agg.merge(high60, on="code", how="left")
    today_agg["high60_ratio"] = (
        today_agg["day_close"] / (today_agg["high_60"] + 1e-9)
    ).fillna(0.9)
    today_agg["score_h60"] = np.where(
        today_agg["high60_ratio"] >= 1.0,
        (10.0 + (today_agg["high60_ratio"] - 1.0).clip(0, 0.01) / 0.01 * 5.0).clip(0, 15),
        ((today_agg["high60_ratio"].clip(0.95, 1.0) - 0.95) / 0.05 * 5.0).clip(0, 5)
    )

    # 거래대금 이상 배율 (오늘 / 20일 평균)
    try:
        px3c = px3_sub.copy()
        px3c["date_str"] = px3c["ts"].dt.strftime("%Y-%m-%d")
        daily = px3c.groupby(["code","date_str"])["value"].sum().reset_index()
        avg_v = daily.groupby("code")["value"].mean().reset_index(name="avg_val")
        tod_v = daily[daily["date_str"] == today_str][["code","value"]].rename(columns={"value":"today_val"})
        vr = avg_v.merge(tod_v, on="code", how="left")
        vr["val_ratio"] = (vr["today_val"] / (vr["avg_val"] + 1e-9)).fillna(1.0)
        today_agg = today_agg.merge(vr[["code","val_ratio"]], on="code", how="left")
    except Exception:
        today_agg["val_ratio"] = 1.0
    today_agg["val_ratio"] = today_agg["val_ratio"].fillna(1.0)

    # ── 기관 연속 순매수 ─────────────────────────────────────────
    inst_rows = []
    frgn_net_map: dict = {}
    if not inv.empty:
        cutoff = pd.Timestamp(today_str) - pd.Timedelta(days=30)
        # [FIX 2026-05-30] 비거래일(토5/일6) 중복 행 제외 — inst_consec/frgn_consec 오염 방지.
        #   배경: investor_daily에 주말 중복행이 섞여 cumprod(최근일부터) 첫항을 음수로 덮어
        #         기관 매수일인데 consec=0 (009150 5/29) / 주말중복이 연속일 부풀림(012330 8→실5).
        #   today_str은 항상 거래일(EOD run)이라 today 행 보존 → net_buy_flag 정상.
        recent = inv[(inv["date"] >= cutoff) & (inv["date"].dt.weekday < 5)]
        for code, g in recent.groupby("code", sort=False):
            if code not in codes: continue
            g = g.sort_values("date")
            today_g = g[g["date"].dt.strftime("%Y-%m-%d") == today_str]
            net_today = float(today_g["net_buy"].iloc[-1]) if not today_g.empty else 0.0
            nbf = 1 if net_today > 0 else 0
            inst_sorted = pd.to_numeric(
                g.sort_values("date", ascending=False)["inst_net"], errors="coerce"
            ).fillna(0)
            consec = int((inst_sorted > 0).cumprod().sum())
            score_inst = min(consec / 3.0, 1.0) * 12.0 + (6.0 if nbf else 0.0)
            # 기관 가속도 (연속매수 가속 캐치)
            inst_accel = max(0, consec - 1)
            score_inst += min(inst_accel * 2.0, 6.0)
            # 기관+외국인 동시 순매수 슈퍼시그널 (+5점)
            frgn_today = float(today_g["frgn_net"].iloc[-1]) if not today_g.empty else 0.0
            if nbf == 1 and frgn_today > 0:
                score_inst = min(score_inst + 5.0, 28.0)
            # [TUNE] 기관 과의존 완화: score_inst 상한 28→20
            score_inst = min(score_inst, 20.0)
            # [INST-20D 2026-06-02] 사용자 설계: 20일 대장주 체크 — 3일 연속 보너스(위 consec 기반)에 더해,
            #   최근 20일 순매수 비율(중간 하루 매도해도 꾸준히 산 대장주)을 추가 보너스로 반영.
            #   데이터 누적후 20일 완전 작동(현재 ~10거래일). env INST_20D_BONUS로 가중 조정.
            _w20 = inst_sorted.head(20)
            _r20 = float((_w20 > 0).sum()) / len(_w20) if len(_w20) > 0 else 0.0
            score_inst = min(score_inst + round(_r20 * float(os.environ.get("INST_20D_BONUS", "4.0")), 2), 24.0)
            # [TUNE] 외국인 연속 매수 보너스 (2일:+3, 3일:+6, 4일이상:+10)
            frgn_sorted = pd.to_numeric(
                g.sort_values("date", ascending=False)["frgn_net"], errors="coerce"
            ).fillna(0)
            frgn_consec = int((frgn_sorted > 0).cumprod().sum())
            score_frgn_bonus = (10.0 if frgn_consec >= 4 else
                                 6.0 if frgn_consec >= 3 else
                                 3.0 if frgn_consec >= 2 else 0.0)
            inst_rows.append({"code": code, "inst_consec": consec,
                              "net_buy_flag": nbf, "score_inst": round(score_inst + score_frgn_bonus, 2)})
            if not today_g.empty:
                frgn_net_map[code] = float(today_g["frgn_net"].iloc[-1])

    inst_df = pd.DataFrame(inst_rows) if inst_rows else pd.DataFrame(
        columns=["code","inst_consec","net_buy_flag","score_inst"])
    today_agg = today_agg.merge(inst_df, on="code", how="left")
    today_agg["score_inst"]   = today_agg["score_inst"].fillna(0.0)
    today_agg["inst_consec"]  = today_agg["inst_consec"].fillna(0).astype(int)
    today_agg["net_buy_flag"] = today_agg["net_buy_flag"].fillna(-1).astype(int)
    today_agg["frgn_net_today"] = today_agg["code"].map(frgn_net_map).fillna(0.0)

    # ── 갭업 예측 팩터 (총 15점) ─────────────────────────────────
    # A. VWAP 대비 종가 위치 (5점)
    try:
        px_vwap = px_sub.copy()
        px_vwap["pv"] = px_vwap["close"] * px_vwap["value"]
        vwap_g = px_vwap.groupby("code").agg(
            pv_s=("pv","sum"), v_s=("value","sum")).reset_index()
        vwap_g["vwap"] = vwap_g["pv_s"] / (vwap_g["v_s"] + 1.0)
        close_map = today_agg.set_index("code")["day_close"].to_dict()
        vwap_g["vwap_ratio"] = vwap_g["code"].map(close_map) / (vwap_g["vwap"] + 1e-9)
        today_agg = today_agg.merge(vwap_g[["code","vwap_ratio"]], on="code", how="left")
    except Exception:
        today_agg["vwap_ratio"] = 1.0
    today_agg["vwap_ratio"] = today_agg["vwap_ratio"].fillna(1.0)
    today_agg["score_vwap"] = (
        (today_agg["vwap_ratio"] - 1.0).clip(-0.01, 0.03) / 0.03 * GAP_VWAP_W
    ).clip(0, GAP_VWAP_W)

    # B. 체결강도 - 마지막 구간 상승봉 거래대금 비율 (6점)
    try:
        last5 = px_sub[(px_sub["hm"] >= BUY_START) & (px_sub["hm"] <= BUY_END)].copy()
        up_mask = last5["close"] > last5["open"]
        imb_up  = last5[up_mask].groupby("code")["value"].sum().reset_index(name="val_up")
        imb_tot = last5.groupby("code")["value"].sum().reset_index(name="val_tot")
        imb = imb_tot.merge(imb_up, on="code", how="left").fillna(0)
        imb["last_imbalance"] = imb["val_up"] / (imb["val_tot"] + 1.0)
        today_agg = today_agg.merge(imb[["code","last_imbalance"]], on="code", how="left")
    except Exception:
        today_agg["last_imbalance"] = 0.0
    today_agg["last_imbalance"] = today_agg["last_imbalance"].fillna(0.0)
    today_agg["score_imb"] = (
        (today_agg["last_imbalance"].clip(0.35, 0.75) - 0.35) / 0.40 * GAP_IMBALANCE_W
    ).clip(0, GAP_IMBALANCE_W)

    # C. 잔차모멘텀 강도 (4점)
    today_agg["score_cdv"] = (
        today_agg["residual_momentum"].clip(0, 5) / 5.0 * GAP_CLOSE_DEV_W
    ).clip(0, GAP_CLOSE_DEV_W)

    today_agg["gap_predict_score"] = (
        today_agg["score_vwap"] +
        today_agg["score_imb"] +
        today_agg["score_cdv"]
    ).clip(0, 15).round(2)

    # ── val_ratio 공격 점수 (최대 10점) ──────────────────────────
    today_agg["score_val_ratio"] = (
        (today_agg["val_ratio"].clip(1.0, 5.0) - 1.0) / 4.0 * VAL_RATIO_W
    ).clip(0, VAL_RATIO_W)

    # ── 전일 고점 돌파 팩터 (최대 5점) ───────────────────────────
    today_agg["score_prev_break"] = 0.0
    if prev_day is not None and not prev_day.empty:
        today_high = px_sub.groupby("code")["high"].max().reset_index(name="today_high")
        pd_merged  = today_high.merge(prev_day[["code","prev_high"]], on="code", how="left")
        pd_merged["prev_break"] = (
            pd_merged["today_high"] / (pd_merged["prev_high"] + 1e-9)
        ).fillna(1.0)
        pd_merged["score_prev_break"] = np.where(
            pd_merged["prev_break"] >= 1.0,
            ((pd_merged["prev_break"] - 1.0).clip(0, 0.02) / 0.02 * 5.0).clip(0, 5),
            0.0
        )
        today_agg = today_agg.merge(
            pd_merged[["code","score_prev_break"]], on="code", how="left"
        )
        if "score_prev_break" not in today_agg.columns:
            today_agg["score_prev_break"] = 0.0
        else:
            today_agg["score_prev_break"] = today_agg["score_prev_break"].fillna(0.0)

    # ── 추세 지속성 ───────────────────────────────────────────────
    try:
        trend = px_sub.groupby("code")["close"].diff() > 0
        persist = trend.groupby(px_sub["code"]).rolling(5).sum()
        persist = persist.reset_index(level=0, drop=True)
        persist = px_sub[["code"]].assign(tp=persist).groupby("code")["tp"].last().reset_index()
        persist.columns = ["code", "trend_persist"]
        today_agg = today_agg.merge(persist, on="code", how="left")
    except Exception:
        today_agg["trend_persist"] = 0.0
    today_agg["trend_persist"] = pd.to_numeric(
        today_agg["trend_persist"], errors="coerce").fillna(0.0)
    today_agg["trend_persist"] = (today_agg["trend_persist"] / 5.0).clip(0, 1)

    # [v7_B2] RT top20: score_inst 하한 15점 보장 (기관 미매집 공격형 종목 보호)
    if rt_top20:
        _mask_rt2 = today_agg["code"].isin(rt_top20)
        today_agg.loc[_mask_rt2, "score_inst"] = today_agg.loc[_mask_rt2, "score_inst"].clip(lower=15.0)
        logger.info("[STEP2][RT보장] top20 inst하한 15pt 적용=%d개", int(_mask_rt2.sum()))

    # ── [FIX-5] stage2_score 합산 - clip 65→75 ───────────────────
    today_agg["stage2_score"] = (
        today_agg["score_rm"] +
        today_agg["score_h60"] +
        today_agg["score_inst"] +
        today_agg["gap_predict_score"] +
        today_agg["score_val_ratio"] +
        today_agg["score_prev_break"] +
        today_agg["trend_persist"] * 8.0
    ).clip(0, 85).round(2)   # [FIX-5] 65→75  [TUNE] 75→85 상위 차별화

    merged = step1_df.merge(today_agg, on="code", how="inner")
    merged["s12"] = merged["stage1_score"] + merged["stage2_score"]
    _merged_sorted = merged.sort_values("stage2_score", ascending=False)

    # [v7_B2] RT top20 step2 통과 보장
    if rt_top20:
        _top_n2 = set(_merged_sorted.head(TOP_20)["code"].tolist())
        _rescued2 = (rt_top20 & set(merged["code"].tolist())) - _top_n2
        if _rescued2:
            _df2_main   = _merged_sorted.head(TOP_20)
            _df2_rescue = _merged_sorted[_merged_sorted["code"].isin(_rescued2)]
            merged = (pd.concat([_df2_main, _df2_rescue])
                      .drop_duplicates(subset=["code"], keep="first")
                      .reset_index(drop=True))
            logger.info("[STEP2][RT보장] top20 구제=%d개", len(_rescued2))
        else:
            merged = _merged_sorted.head(TOP_20).reset_index(drop=True)
    else:
        merged = _merged_sorted.head(TOP_20).reset_index(drop=True)

    logger.info("[STEP2] 50→%d  stage2_score: max=%.1f min=%.1f  top5=%s",
               len(merged),
               float(merged["stage2_score"].max()) if not merged.empty else 0,
               float(merged["stage2_score"].min()) if not merged.empty else 0,
               merged["code"].head(5).tolist())
    return merged


# ═══════════════════════════════════════════════════════════════
#  STEP 3 : 20→5  "내일 안 빠질 종목인가?" - 방어(생존 여부)
#  [FIX-2] 변동성 패널티 build_scoreboard에서 이곳으로 이동
#          score 단일 계산 경로 확립 - 이중계산 제거
# ═══════════════════════════════════════════════════════════════
def step3_defense(df: pd.DataFrame,
                  px_today: pd.DataFrame,
                  logger: logging.Logger,
                  rt_top20: set = None) -> pd.DataFrame:
    """Hard Cut 탈락 → 방어감점/가점 → 변동성패널티(1회) → 생존5종목
    [FIX-2] 변동성 패널티를 step3 내부에서 1회만 적용
    """
    out = df.copy()

    for c in ["close_position","high_break","volume_accel","close_value_ratio",
              "last5_value_accel","last10_value_accel","day_chg_pct"]:
        if c not in out.columns: out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    if "val_ratio" not in out.columns:      out["val_ratio"] = 1.0
    out["val_ratio"] = pd.to_numeric(out["val_ratio"], errors="coerce").fillna(1.0)
    if "upper_wick_ratio" not in out.columns: out["upper_wick_ratio"] = 1.0
    out["upper_wick_ratio"] = pd.to_numeric(out["upper_wick_ratio"], errors="coerce").fillna(1.0)
    if "frgn_net_today" not in out.columns: out["frgn_net_today"] = 0.0
    out["frgn_net_today"] = pd.to_numeric(out["frgn_net_today"], errors="coerce").fillna(0.0)

    # ── Hard Cut ──────────────────────────────────────────────
    out["penalty_major"] = 0
    out["weak_items"]    = ""

    hc_wick  = out["upper_wick_ratio"] < HC_UPPER_WICK_MIN
    # [S2-EXEMPT v7_9] stage2_score >= 20.0 → cp_low / weak_close_tri 면제
    # [3-B-2 2026-05-11] 20.0→15.0 완화. 5/11 STEP2 max=32.0 / min=0.0 분포 → 15~19 종목도 면제 확대. STEP3 hc_cp/hc_weak_close 통과율 증가 기대.
    s2_strong = pd.to_numeric(out["stage2_score"], errors="coerce").fillna(0.0) >= 15.0
    hc_cp    = (out["close_position"] < HC_CLOSE_POS_MIN) & (out["close_position"] > 0.0) & ~s2_strong
    # [v7_9 PATCH3] inst_ok: inst_consec >= 2 AND 당일 기관 순매수 양수 동시 충족
    inst_ok  = (out["inst_consec"].fillna(0) >= 2) & (out["net_buy_flag"].fillna(-1) > 0)
    # [v7_9 PATCH2] hc_l5a: l5a AND l10a 동시 미달 시 탈락 (지속성 확인)
    hc_l5a   = (
        (out["last5_value_accel"]  <= HC_L5ACCEL_MIN) &
        (out["last10_value_accel"] <= HC_L10ACCEL_MIN)
    ) & (~inst_ok) & (out["last5_value_accel"] > 0.0)
    hc_chg   = out["day_chg_pct"]      > HC_DAY_CHG_MAX
    hc_frgn  = (
        (out["frgn_net_today"] < HC_FRGN_EXIT_THR) &
        (out["inst_consec"].fillna(0) == 0)
    )

    # [v7_9 PATCH1] 저질 종가 체류 - 가중합 방식 (3개 AND → 1개 이상 심각해도 탈락)
    _hc_score = (
        (1.0 - out["close_position"].clip(0, 1))    * 0.35 +
        (1.0 - out["close_value_ratio"].clip(0, 1)) * 0.35 +
        (1.0 - out["last5_value_accel"].clip(0, 1)) * 0.30
    )
    hc_weak_close = (_hc_score > 0.40) & ~s2_strong  # [3-B-1 2026-05-11] 0.30→0.40 완화. 5/11 STEP2 통과 4개 중 3개 저질종가 탈락(75%) → 임계 1.33배 완화로 funnel 누수 축소. close_pos/close_value/l5a 가중합 0.40 초과만 탈락.

    out.loc[hc_wick,        "weak_items"] += "|wick_fail"
    out.loc[hc_cp,          "weak_items"] += "|cp_low"
    out.loc[hc_l5a,         "weak_items"] += "|l5a_zero"
    out.loc[hc_chg,         "weak_items"] += "|overheat"
    out.loc[hc_frgn,        "weak_items"] += "|frgn_exit"
    out.loc[hc_weak_close,  "weak_items"] += "|weak_close_tri"  # [필수-7]

    if "range_zscore_3m" in out.columns:
        out["range_zscore_3m"] = pd.to_numeric(out["range_zscore_3m"], errors="coerce").fillna(0.0)
        hc_rz = out["range_zscore_3m"] > HC_RANGE_ZSCORE_MAX
        out.loc[hc_rz, "weak_items"] += "|range_zscore_hot"
    else:
        hc_rz = pd.Series(False, index=out.index)

    hard_cut = hc_wick | hc_cp | hc_l5a | hc_chg | hc_rz | hc_frgn | hc_weak_close  # [필수-7]
    out.loc[hard_cut, "penalty_major"] = 1
    out["weak_items"] = out["weak_items"].str.strip("|")

    # [THEME-RESCUE-C 2026-06-06] rt_top20(강테마 대장주)을 '과열계열' hard_cut에서만 선택 구제.
    #   살림: hc_chg(당일급등/과열) | hc_rz(변동성과열) → penalty_major 0 + _rt_hc(아래서 defense_penalty +25=경쟁 from behind).
    #   탈락유지: hc_wick·hc_cp·hc_weak_close·hc_frgn·hc_l5a (윗꼬리/약한종가/저질종가/외국인이탈/막판거래대금죽음
    #            = 고가권·막판유입·리스크 철학). 품질/리스크 컷이 하나라도 있으면 구제 안 함(둘 다 걸리면 탈락).
    #   안전판: EOD_PICK signal_v2 day_chg>=25% 과열 hard_cut이 극단 급등주 별도 차단(이중). env로 끄려면 SCOREBOARD_THEME_RESCUE=NO.
    out["_rt_hc"] = False
    if SCOREBOARD_THEME_RESCUE and rt_top20:
        _keep_cut = hc_wick | hc_cp | hc_l5a | hc_frgn | hc_weak_close   # 이 중 하나라도면 탈락 유지
        _soft_cut = hc_chg | hc_rz                                        # 과열계열(구제 대상)
        _mask_rt_hc = (out["code"].isin(rt_top20) & (out["penalty_major"] == 1)
                       & _soft_cut & ~_keep_cut)
        if _mask_rt_hc.any():
            out.loc[_mask_rt_hc, "penalty_major"] = 0
            out.loc[_mask_rt_hc, "_rt_hc"] = True
            logger.warning("[STEP3][THEME-RESCUE-C] 과열계열 hard_cut 구제(감점경쟁)=%d개: %s",
                           int(_mask_rt_hc.sum()), out.loc[_mask_rt_hc, "code"].tolist())

    n_hc = int(hard_cut.sum())
    logger.info("[STEP3] Hard Cut 탈락=%d (외국인이탈=%d 저질종가=%d) / 생존=%d",
               n_hc, int(hc_frgn.sum()), int(hc_weak_close.sum()), len(out) - n_hc)

    # ── 방어 감점 (갭하락 위험) ───────────────────────────────────
    out["defense_penalty"] = 0.0
    out.loc[
        (out["day_chg_pct"] >= 10) & (out["upper_wick_ratio"] < 0.990),
        "defense_penalty"
    ] += 20.0
    out.loc[
        (out["day_chg_pct"] >= 8) & (out["day_chg_pct"] < 10),
        "defense_penalty"
    ] += 8.0
    out.loc[
        (out["close_position"] >= HC_CLOSE_POS_MIN) &
        (out["close_position"] < 0.85),
        "defense_penalty"
    ] += 10.0
    out.loc[out["last5_value_accel"] <= 1.1, "defense_penalty"] += 8.0

    # [v7_B2] RT Hard Cut 구제 종목: 중감점 +25 적용 (탈락 대신 불이익)
    out.loc[out["_rt_hc"], "defense_penalty"] += 25.0

    # ── 방어 가점 (마감 강도) ─────────────────────────────────────
    out["defense_bonus"] = 0.0
    out.loc[out["close_position"] >= 0.90, "defense_bonus"] += 12.0
    out.loc[
        (out["close_position"] >= 0.85) & (out["close_position"] < 0.90),
        "defense_bonus"
    ] += 7.0
    out.loc[out["last5_value_accel"] >= 1.5, "defense_bonus"] += 10.0
    out.loc[
        (out["last5_value_accel"] >= 1.1) & (out["last5_value_accel"] < 1.5),
        "defense_bonus"
    ] += 5.0
    out.loc[out["upper_wick_ratio"] >= 0.995, "defense_bonus"] += 8.0
    out.loc[
        (out["upper_wick_ratio"] >= 0.988) & (out["upper_wick_ratio"] < 0.995),
        "defense_bonus"
    ] += 4.0

    # ── [FIX-2] 변동성 패널티 - step3 내부 1회 적용 ──────────────
    # px_today가 전달된 경우에만 계산 (미전달 시 0으로 처리)
    out["vol_penalty"] = 0.0
    if not px_today.empty:
        try:
            codes_s3 = set(out["code"].tolist())
            px_s3 = px_today[px_today["code"].isin(codes_s3)].copy()
            vol_data = (
                px_s3.groupby("code")["close"]
                .pct_change()
                .groupby(px_s3["code"])
                .rolling(10, min_periods=3)
                .std()
            )
            vol_last = vol_data.reset_index(level=0, drop=True)
            vol_last = (
                px_s3[["code"]]
                .assign(vol=vol_last)
                .groupby("code")["vol"]
                .last()
                .reset_index()
            )
            vol_last.columns = ["code", "volatility_raw"]
            out = out.merge(vol_last, on="code", how="left")
            out["volatility_raw"] = pd.to_numeric(out["volatility_raw"], errors="coerce").fillna(0.0)
            vol_max = out["volatility_raw"].quantile(0.90) + 1e-9
            out["vol_penalty"] = (out["volatility_raw"] / vol_max).clip(0, 1) * 12.0
            logger.info("[STEP3] 변동성 패널티 적용 max=%.2f", float(out["vol_penalty"].max()))
        except Exception as ve:
            logger.warning("[STEP3] 변동성 계산 실패 → 0 처리: %s", ve)

    # ── stage3_score (변동성 패널티 포함, 1회만) ──────────────────
    out["stage3_score"] = (
        out["defense_bonus"] - out["defense_penalty"] - out["vol_penalty"]
    ).clip(-30, 30).round(2)

    # ── 최종 점수 계산 (단일 경로) ───────────────────────────────
    # [W1 v7_0] s12_max 절대 하한 55 적용 - 시장 약세일 1등 과대평가 방지
    s12_max = max(float(out["s12"].max()) if not out.empty else 85.0, 55.0)
    out["attack_score"]  = (out["s12"] / max(s12_max, 1.0) * 100.0).clip(0, 100)
    out.loc[out["s12"] < ABS_S12_FLOOR, "attack_score"] = (
        out.loc[out["s12"] < ABS_S12_FLOOR, "attack_score"] * 0.60
    ).clip(0, 60)
    out["defense_score"] = ((out["stage3_score"] + 30) / 60.0 * 100.0).clip(0, 100)
    out["score"] = (
        out["attack_score"]  * 0.70 +
        out["defense_score"] * 0.30
    ).clip(0, 100).round(2)

    out.loc[out["penalty_major"] == 1, "score"] = 0.0

    survived = out[out["penalty_major"] == 0].copy()
    survived = survived.sort_values(
        ["score","defense_bonus","close_position"],
        ascending=[False, False, False]
    )
    survived = survived.drop_duplicates(subset=["code"], keep="first")
    survived = survived.head(TOP_5).reset_index(drop=True)

    # [v7_B2] RT top20 step3 통과 보장 (head(TOP_5) 밖으로 잘린 경우 구제)
    if rt_top20:
        _top_n3 = set(survived["code"].tolist())
        _rt_alive = set(out.loc[out["penalty_major"] == 0, "code"].tolist())
        _rescued3 = (rt_top20 & _rt_alive) - _top_n3
        if _rescued3:
            _df3_rescue = out[out["code"].isin(_rescued3)].copy()
            survived = (pd.concat([survived, _df3_rescue])
                        .drop_duplicates(subset=["code"], keep="first")
                        .reset_index(drop=True))
            logger.info("[STEP3][RT보장] top20 구제=%d개", len(_rescued3))

    logger.info("[STEP3] 20→%d  score: max=%.1f min=%.1f",
               len(survived),
               float(survived["score"].max()) if not survived.empty else 0,
               float(survived["score"].min()) if not survived.empty else 0)
    return survived


# ═══════════════════════════════════════════════════════════════
#  STEP 4A : 매수 직전 10분 동태 (15:08~15:18)
# ═══════════════════════════════════════════════════════════════
def step4a_dynamics(px_today: pd.DataFrame, codes: list,
                    logger: logging.Logger) -> pd.DataFrame:
    """15:08~15:18 거래대금·가격방향·신고가·윗꼬리 동태 스코어링"""
    window = px_today[
        px_today["code"].isin(codes) &
        (px_today["hm"] >= DYN_START) &
        (px_today["hm"] <= DYN_END)
    ].copy()

    rows = []
    for code in codes:
        g = window[window["code"] == code].sort_values("ts")
        if g.empty:
            rows.append({"code":code,"dyn_score":0.0,"dyn_hold_flag":0})
            continue

        v_early = float(g[g["hm"] <  DYN_MID]["value"].mean() or 0)
        v_late  = float(g[g["hm"] >= DYN_MID]["value"].mean() or 0)
        if v_late > v_early * 1.05:
            val_score = 8.0
        elif v_late < v_early * 0.70:
            val_score = -10.0
        else:
            val_score = 0.0

        p_start = float(g["close"].iloc[0])
        p_end   = float(g["close"].iloc[-1])
        if p_end > p_start * 1.002:
            px_score = 6.0
        elif p_end < p_start * 0.998:
            px_score = -10.0
        else:
            px_score = 0.0

        highs = g["high"].values
        new_high_cnt = sum(
            1 for i in range(1, len(highs))
            if highs[i] > max(highs[:i])
        )
        high_score = (6.0 if new_high_cnt >= 2 else 3.0 if new_high_cnt == 1 else 0.0)

        tail2 = g.tail(2)
        wick_cnt = int(
            ((tail2["high"] - tail2["close"]) /
             (tail2["high"] + 1e-9) > 0.005).sum()
        )
        wick_score = (-15.0 if wick_cnt >= 2 else -5.0 if wick_cnt == 1 else 2.0)

        dyn_score = round(val_score + px_score + high_score + wick_score, 2)
        hold_flag = int(
            wick_cnt >= 2 or
            (p_end < p_start * 0.998 and v_late < v_early * 0.70)
        )
        if hold_flag:
            logger.warning("[STEP4A] %s 이상: wick=%d p_down=%s v_down=%s",
                          code, wick_cnt,
                          p_end < p_start * 0.998,
                          v_late < v_early * 0.70)
        rows.append({
            "code":          code,
            "dyn_score":     dyn_score,
            "dyn_hold_flag": hold_flag,
            "dyn_val_ok":    int(v_late >= v_early * 0.9),
            "dyn_px_ok":     int(p_end >= p_start),
            "dyn_new_high":  new_high_cnt,
            "dyn_wick_cnt":  wick_cnt,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["code","dyn_score","dyn_hold_flag"])


# ═══════════════════════════════════════════════════════════════
#  STEP 4B : 5→1  Conviction Gate (소프트/하드 2단계 - FIX-3/4)
# ═══════════════════════════════════════════════════════════════
def step4b_conviction(df: pd.DataFrame,
                      logger: logging.Logger,
                      today_str: str,
                      mkt_risk_flag: int = 0) -> Tuple[pd.DataFrame, int]:
    """[FIX-3] 소프트/하드 2단계 Conviction Gate
    SOFT(gap≥7 & conv≥70): 80% 포지션 진입   [v7_0: 주석 상수값 통일]
    HARD(gap≥11.5 & conv≥82): 풀 포지션
    하드차단: gap<7 OR conv<70
    [FIX-4] position_ratio에 inst_consec 복합 반영
    [BUG-A v7_0] 임시 동태혼합값 → score_dyn_blend 로 명칭 분리
                 score_final 컬럼은 _calc_score_final()에서만 생성
    """
    if "dyn_hold_flag" in df.columns:
        clean = df[df["dyn_hold_flag"] == 0].copy()
        n_dyn = int((df["dyn_hold_flag"] == 1).sum())
        if n_dyn > 0:
            logger.warning("[STEP4B] 10분동태 HOLD 제거=%d", n_dyn)
    else:
        clean = df.copy()

    if clean.empty:
        logger.warning("[STEP4B] 동태 필터 후 종목 없음 → HOLD")
        return pd.DataFrame(), RC_HOLD

    # [BUG-A] score_dyn_blend: 동태 가중치 임시 혼합값 - score_final과 별개
    # [v7_9+] 안3 hybrid: score×0.65 + dyn×0.15 + ps_hybrid×0.20
    #   ps_hybrid = 0.50×rank_pct + 0.50×p10p90_norm
    #   fallback: 기존 score×0.82 + dyn×0.18 (prescore 로드 실패 시)
    if "dyn_score" in clean.columns:
        dyn_norm = (
            pd.to_numeric(clean["dyn_score"], errors="coerce").fillna(0)
            .clip(-17, 22)
        )
        dyn_weight = (dyn_norm + 17) / 39.0  # 변경 금지
        try:
            _rt = pd.read_csv(
                BASE / "DATA" / "rt_intraday.csv",
                encoding="utf-8-sig",
                usecols=lambda c: c in ("code", "prescore_weighted"),
            )
            _rt["code"] = _rt["code"].astype(str).str.zfill(6)
            _pw_map = pd.to_numeric(
                _rt.set_index("code")["prescore_weighted"], errors="coerce"
            ).fillna(0.0).to_dict()

            pw_raw = pd.to_numeric(
                clean["code"].map(_pw_map), errors="coerce"
            ).fillna(0.0)
            _n = len(clean)

            # rank_pct: prescore 내림차순 → 0~1 (1위=최고, N위≈0)
            _pw_rank = pw_raw.rank(ascending=False, method="min")
            ps_rank_pct = (_n - _pw_rank) / max(_n, 1)

            # p10-p90 정규화 (양수 값만)
            _ps_pos = pw_raw[pw_raw > 0]
            if len(_ps_pos) >= 2:
                _p10 = float(_ps_pos.quantile(0.10))
                _p90 = float(_ps_pos.quantile(0.90))
                ps_p10p90 = ((pw_raw - _p10) / max(_p90 - _p10, 1e-6)).clip(0.0, 1.0)
            else:
                ps_p10p90 = pd.Series(0.0, index=clean.index)

            ps_hybrid = (0.50 * ps_rank_pct + 0.50 * ps_p10p90).fillna(0.0)
            clean["score_dyn_blend"] = (
                clean["score"] * 0.65
                + dyn_weight * 100 * 0.15
                + ps_hybrid * 100 * 0.20
            ).clip(0, 100)
            logger.info(
                "[STEP4B][hybrid] N=%d pw_max=%.1f ps_hybrid_top=%.3f",
                _n, float(pw_raw.max()), float(ps_hybrid.max()),
            )
        except Exception as _e:
            logger.warning("[STEP4B][hybrid] prescore 로드 실패 → fallback: %s", _e)
            clean["score_dyn_blend"] = (
                clean["score"] * 0.82 + dyn_weight * 100 * 0.18
            ).clip(0, 100)
    else:
        clean["score_dyn_blend"] = clean["score"]

    clean = clean.sort_values("score_dyn_blend", ascending=False).reset_index(drop=True)

    scores = clean["score_dyn_blend"].values
    if len(scores) < 2:
        # [3-A 2026-05-11] winner_gap=0.0 → CONV_SOFT_GAP_MIN. 잔여 1개일 때 0 강제 → SOFT 5.0 미달 HOLD로 funnel 완전 차단되던 문제 회피. 5.0 정확히 일치 → '< SOFT 5.0' 조건 미충족 → HOLD 우회. 0→5 fallback.
        winner_gap = CONV_SOFT_GAP_MIN
        logger.warning("[STEP4B] 잔여 종목 1개 - winner_gap=%.1f fallback 적용 (3-A)", CONV_SOFT_GAP_MIN)
    else:
        winner_gap = float(scores[0] - scores[1])

    dominance_ratio = float(scores[0]) / (float(scores[1]) + 1e-9) if len(scores) >= 2 else 1.0

    # conviction: inst_consec 반영
    top = clean.iloc[0]
    inst_consec_val = float(top.get("inst_consec", 0))
    inst_bonus = min(inst_consec_val * 2.5, 18.0)
    conviction = (
        float(top["score_dyn_blend"]) * 0.45 +
        winner_gap * 5.0 +
        float(top.get("defense_bonus", 0)) * 0.25 +
        inst_bonus
    )
    # [FIX-V72-4] conviction 상한 클리핑 - winner_gap 큰 날 unbounded 방지
    # CONV_CONVICTION_MIN=82 기준 의미 유지를 위해 120.0으로 제한
    conviction = min(conviction, 120.0)

    logger.info("[STEP4B] winner_gap=%.2f  conviction=%.2f  dominance=%.2fx  inst_bonus=%.1f",
               winner_gap, conviction, dominance_ratio, inst_bonus)

    # ── [FIX-3] 하드 차단 (gap<SOFT 또는 conv<SOFT → 완전 HOLD) ──
    if winner_gap < CONV_SOFT_GAP_MIN:
        logger.warning("[STEP4B] winner_gap %.2f < SOFT %.1f → HOLD",
                      winner_gap, CONV_SOFT_GAP_MIN)
        clean["winner_gap"]      = winner_gap
        clean["conviction"]      = round(conviction, 2)
        clean["dominance_ratio"] = round(dominance_ratio, 3)
        clean["conv_mode"]       = "HOLD"
        return clean, RC_HOLD
    if conviction < CONV_SOFT_CONV_MIN:
        logger.warning("[STEP4B] conviction %.2f < SOFT %.1f → HOLD",
                      conviction, CONV_SOFT_CONV_MIN)
        clean["winner_gap"]      = winner_gap
        clean["conviction"]      = round(conviction, 2)
        clean["dominance_ratio"] = round(dominance_ratio, 3)
        clean["conv_mode"]       = "HOLD"
        return clean, RC_HOLD

    # ── [FIX-3] 소프트/하드 진입 모드 결정 ──────────────────────
    is_hard = (winner_gap >= CONV_WINNER_GAP_MIN and conviction >= CONV_CONVICTION_MIN)
    is_soft = not is_hard  # SOFT_MIN 통과했으나 HARD 미달
    conv_mode = "FULL" if is_hard else "SOFT"
    logger.info("[STEP4B] conv_mode=%s (hard=%s)", conv_mode, is_hard)

    # ── Conviction Gate: 절대 기준 ────────────────────────────────
    top_score = float(clean.iloc[0].get("score_dyn_blend", 0))  # [BUG-A]
    top_s12   = float(clean.iloc[0].get("s12", 0))
    top_def   = float(clean.iloc[0].get("defense_score", 0))
    abs_fails = []
    if top_score < CONV_ABS_SCORE_MIN:   abs_fails.append(f"score={top_score:.1f}")
    if top_s12   < CONV_ABS_ATTACK_MIN:  abs_fails.append(f"s12={top_s12:.1f}")
    if top_def   < CONV_ABS_DEFENSE_MIN: abs_fails.append(f"defense={top_def:.1f}")
    if abs_fails:
        logger.warning("[STEP4B] 절대기준 미달 → HOLD: %s", " | ".join(abs_fails))
        clean["winner_gap"]      = winner_gap
        clean["conviction"]      = round(conviction, 2)
        clean["dominance_ratio"] = round(dominance_ratio, 3)
        clean["conv_mode"]       = "HOLD"
        return clean, RC_HOLD
    logger.info("[STEP4B] 절대기준 OK: score=%.1f s12=%.1f defense=%.1f",
               top_score, top_s12, top_def)

    # ── 몰빵 신호 등급 ───────────────────────────────────────────
    allout_signal = int(
        is_hard and
        top_score >= ALLOUT_SCORE_MIN and
        winner_gap >= ALLOUT_GAP_MIN
    )

    # ── [FIX-4] position_ratio: gap_predict + inst_consec 복합 ──
    gap_pred = float(top.get("gap_predict_score", 0))
    base_ratio = POSITION_RATIO_TABLE[-1][1]
    for threshold, ratio in POSITION_RATIO_TABLE:
        if gap_pred >= threshold:
            base_ratio = ratio
            break

    # inst_consec 보너스: 최대 +15% (기관의 등에 탔다 원칙 반영)
    inst_boost = min(inst_consec_val / 5.0, 1.0) * INST_POSITION_BOOST_MAX
    position_ratio = min(base_ratio + inst_boost, 1.00)

    # SOFT 모드: 포지션 배율 적용
    if is_soft:
        position_ratio = round(position_ratio * CONV_SOFT_POSITION, 2)
        logger.info("[STEP4B] SOFT 모드 → position_ratio×%.0f%% = %.0f%%",
                   CONV_SOFT_POSITION * 100, position_ratio * 100)

    # allout이면 무조건 100%
    if allout_signal:
        position_ratio = 1.00
        # [ADD-V73] allout이어도 코스닥 경고 상황에서는 0.90 캡 적용
        # 수정: clean.columns 조회 방식(버그) → 인자로 직접 전달받은 mkt_risk_flag 사용
        if mkt_risk_flag == 1:
            position_ratio = min(position_ratio, 0.90)
            logger.warning("[STEP4B][ADD-V73] allout+MKT_WARN → position 0.90 캡 적용")

    # ── [필수-1 v7_1] 몰빵 방지 추가 게이트 (allout 제외) ─────────
    if not allout_signal:
        dom_weak = dominance_ratio < DOMINANCE_SOFT_THR    # < 1.15
        gap_weak = winner_gap      < WINNER_GAP_SOFT_THR   # < 8.0
        if dom_weak and gap_weak:
            position_ratio = round(position_ratio * 0.65, 2)
            logger.info("[STEP4B][필수-1] dom_weak+gap_weak → ×0.65 = %.0f%%",
                       position_ratio * 100)
        elif dom_weak:
            position_ratio = round(position_ratio * 0.75, 2)
            logger.info("[STEP4B][필수-1] dom_weak → ×0.75 = %.0f%%", position_ratio * 100)
        elif gap_weak:
            position_ratio = round(position_ratio * 0.85, 2)
            logger.info("[STEP4B][필수-1] gap_weak → ×0.85 = %.0f%%", position_ratio * 100)

    # ── [필수-8 v7_1] position_ratio 최종 캡 세분화 (allout 제외) ──
    if not allout_signal:
        if gap_pred < POS_CAP_GAP_THR:                       # gap_predict < 4.0
            position_ratio = min(position_ratio, POS_CAP_GAP_MAX)   # cap 0.60
            logger.info("[STEP4B][필수-8] gap_predict_low → cap %.0f%%",
                       POS_CAP_GAP_MAX * 100)
        if dominance_ratio < POS_CAP_DOM_THR:                # dominance < 1.10
            position_ratio = min(position_ratio, POS_CAP_DOM_MAX)   # cap 0.65
            logger.info("[STEP4B][필수-8] dom_low → cap %.0f%%",
                       POS_CAP_DOM_MAX * 100)
        # risk_penalty cap: _calc_score_final에서 계산 후 적용

    logger.info("[STEP4B] gap_predict=%.1f inst_consec=%d → position_ratio=%.0f%%  allout=%d",
               gap_pred, int(inst_consec_val), position_ratio * 100, allout_signal)

    clean["winner_gap"]      = winner_gap
    clean["conviction"]      = round(conviction, 2)
    clean["dominance_ratio"] = round(dominance_ratio, 3)
    clean["allout_signal"]   = allout_signal
    clean["position_ratio"]  = round(position_ratio, 2)
    clean["conv_mode"]       = conv_mode  # [FIX-3]
    return clean, RC_OK


# ═══════════════════════════════════════════════════════════════
#  [ADD-1] Prior 해석층 - 점수 산식 변경 없이 RT·시가용 번역
# ═══════════════════════════════════════════════════════════════
def _calc_prior_fields(df: pd.DataFrame) -> pd.DataFrame:
    """이미 계산된 score/conviction/winner_gap/rank 을
    RT·시가가 바로 참조할 수 있는 prior_class / prior_weight / eod_pick_flag 로 번역.
    점수 산식 변경 없음 - 해석(번역)만.
    """
    out = df.copy()

    def _prior_class(r: pd.Series) -> str:
        rank      = int(_f(r.get("rank", 99)))
        score     = float(_f(r.get("score", 0)))
        conviction= float(_f(r.get("conviction", 0)))
        wgap      = float(_f(r.get("winner_gap", 0)))
        if (rank == 1 and conviction >= PRIOR_ULTRA_CONVICTION
                and wgap >= PRIOR_ULTRA_WINNER_GAP
                and score >= PRIOR_ULTRA_SCORE):
            return "ULTRA"
        if rank <= 3 and score >= PRIOR_STRONG_SCORE:
            return "STRONG"
        if rank <= 5 and score >= PRIOR_MID_SCORE:
            return "MID"
        return "WEAK"

    def _prior_weight(r: pd.Series) -> float:
        rank      = int(_f(r.get("rank", 99)))
        score     = float(_f(r.get("score", 0)))
        conviction= float(_f(r.get("conviction", 0)))
        allout    = int(_f(r.get("allout_signal", 0)))
        base = PRIOR_WEIGHT_TABLE.get(rank, 0.00)
        bonus = 0.0
        if allout == 1:
            bonus += PRIOR_WEIGHT_ALLOUT_BONUS
        if conviction >= PRIOR_ULTRA_CONVICTION:
            bonus += PRIOR_WEIGHT_CONVICTION_BONUS
        if score >= 88.0:
            bonus += PRIOR_WEIGHT_SCORE_BONUS
        return round(min(base + bonus, PRIOR_WEIGHT_MAX), 2)

    out["prior_class"]   = out.apply(_prior_class,  axis=1)
    out["prior_weight"]  = out.apply(_prior_weight,  axis=1)
    # [EOD-POOL 2026-06-02] rank≤5 → rank≤8: score_eod top8 전체를 종가매수 경쟁풀로.
    #   기존 rank6~8(스코어보드가 top8로 뽑았는데 종가매수서 사장)을 compete 경쟁에 포함.
    #   1등 선별은 _calc_eod_compete_score가 수행 → 풀만 넓힘(품질저하 아님). env로 조정.
    _eod_rank_max = int(os.environ.get("EOD_PICK_RANK_MAX", "8"))
    out["eod_pick_flag"] = out["rank"].apply(
        lambda r: "Y" if int(_f(r)) <= _eod_rank_max else "N"
    )
    out["schema_version"] = SCHEMA_VERSION
    return out


# ═══════════════════════════════════════════════════════════════
#  [SCORE-1] score_final 계산 - 최종 판단 점수 (후처리 해석층)
#  [v7_1 필수-9] score_final =
#    score + prior×5 + conv_bonus + dyn_bonus
#    - risk_penalty - gap_fail_penalty + market_adj
#  점수 산식(stage1/2/3) 변경 없음
# ═══════════════════════════════════════════════════════════════
def _calc_score_final(out: pd.DataFrame,
                      logger: logging.Logger) -> pd.DataFrame:
    """score_final 최종식 v7_2
    [필수-2] market_adj    : 시장 상태 직접 반영 (-5~+1)
    [필수-3] gap_fail_penalty: 갭 실패 직접 감점 (0~-6)
    [필수-5] prior×5, conv 1.5/0.7
    [필수-8] risk_penalty >= 4.0 → position_ratio cap 0.70
    [필수-9] dyn_bonus     : dyn_score 가산 (0~+2)
    [FIX-V72-5] history_bonus 직접 1회 가산 (score 이중 증폭 차단)
    """
    df = out.copy()
    score_finals, risk_pens, gap_fail_pens, market_adjs = [], [], [], []
    pos_ratios = list(df["position_ratio"].values)

    for loop_idx, (_, r) in enumerate(df.iterrows()):
        score      = float(_f(r.get("score", 0)))
        pw         = float(_f(r.get("prior_weight", 0)))
        conviction = float(_f(r.get("conviction", 0)))
        upper_wick = float(_f(r.get("upper_wick_ratio", 1.0)))
        l5a        = float(_f(r.get("last5_value_accel", 1.0)))
        close_pos  = float(_f(r.get("close_position", 0.8)))
        dyn_score  = float(_f(r.get("dyn_score", 0)))
        gap_pred   = float(_f(r.get("gap_predict_score", 0)))
        mkt_flag   = int(_f(r.get("mkt_risk_flag", 0)))
        kosdaq_chg = float(_f(r.get("kosdaq_chg_pct", 0)))
        allout     = int(_f(r.get("allout_signal", 0)))
        code       = str(r.get("code", ""))
        # [FIX-V72-5] history_bonus: score에서 분리, score_final에 직접 1회만 가산
        hist_bonus = float(_f(r.get("history_bonus", 0.0)))

        # ── prior 가산 [필수-5] 5.0 ──────────────────────────────
        pw_delta = round(pw * SCORE_FINAL_PRIOR_MULT, 2)

        # ── conviction 보너스 [필수-5] 1.5/0.7 ──────────────────
        if conviction >= SCORE_FINAL_CONV_HIGH_THR:
            conv_bonus = SCORE_FINAL_CONV_HIGH
        elif conviction >= SCORE_FINAL_CONV_MID_THR:
            conv_bonus = SCORE_FINAL_CONV_MID
        else:
            conv_bonus = 0.0

        # ── dyn_bonus [필수-9] ────────────────────────────────────
        dyn_bonus = round(min(max(dyn_score, 0.0), 20.0) / 20.0 * 2.0, 2)

        # ── risk_penalty ─────────────────────────────────────────
        risk = 0.0
        if upper_wick < RISK_WICK_THR:  risk += RISK_WICK_PEN
        if l5a        < RISK_L5A_THR:   risk += RISK_L5A_PEN
        if close_pos  < RISK_CP_THR:    risk += RISK_CP_PEN

        # ── [필수-3] gap_fail_penalty ────────────────────────────
        gfp = 0.0
        if gap_pred < GAP_FAIL_VERY_LOW_THR:
            gfp += 4.0
        elif gap_pred < GAP_FAIL_LOW_THR:
            gfp += 2.0
        if close_pos < GAP_FAIL_COMBO_CP and upper_wick < GAP_FAIL_COMBO_WICK:
            gfp += 2.0

        # ── [TUNE-9] market_adj - 패널티 완화 + 상승장 보너스 강화 ──
        madj = 0.0
        if mkt_flag == 1:
            madj -= 2.0          # [TUNE-9] -3.0→-2.0
        if kosdaq_chg <= -1.5:
            madj -= 1.0          # [TUNE-9] -2.0→-1.0
        if kosdaq_chg >= 2.5:
            madj += 2.5          # [ADD-V73] 강한 상승장 추가 레벨
        elif kosdaq_chg >= 1.0:
            madj += 1.5          # [TUNE-9] +1.0→+1.5

        # ── [필수-8] risk cap → position_ratio 조정 ─────────────
        pos_ratio = pos_ratios[loop_idx]
        if allout == 0 and risk >= POS_CAP_RISK_THR:
            pos_ratio = min(pos_ratio, POS_CAP_RISK_MAX)

        # [FIX-V72-5] 최종식: score(pre-bonus) + prior + conv + dyn
        #              + hist_bonus(1회) - risk - gfp + madj
        sf_raw = (score + pw_delta + conv_bonus + dyn_bonus
                  + hist_bonus - risk - gfp + madj)
        sf = round(max(0.0, min(sf_raw, 100.0)), 2)

        logger.info(
            "[SCORE-FINAL] code=%s score=%.1f prior=+%.2f conv=+%.1f"
            " dyn=+%.2f hist=+%.1f risk=-%.1f gfp=-%.1f madj=%+.1f → sf=%.1f",
            code, score, pw_delta, conv_bonus, dyn_bonus,
            hist_bonus, risk, gfp, madj, sf
        )

        score_finals.append(sf)
        risk_pens.append(round(risk, 2))
        gap_fail_pens.append(round(gfp, 2))
        market_adjs.append(round(madj, 2))
        pos_ratios[loop_idx] = round(pos_ratio, 2)

    df["score_final"]     = score_finals
    df["risk_penalty"]    = risk_pens
    df["gap_fail_penalty"] = gap_fail_pens   # [필수-3]
    df["market_adj"]      = market_adjs      # [필수-2]
    df["position_ratio"]  = pos_ratios       # [필수-8] risk cap 반영

    df = df.sort_values("score_final", ascending=False).reset_index(drop=True)
    df["rank"]  = range(1, len(df) + 1)
    df["grade"] = df["score_final"].apply(_grade)

    logger.info("[SCORE-FINAL] 완료: max=%.1f min=%.1f",
                float(df["score_final"].max()) if not df.empty else 0,
                float(df["score_final"].min()) if not df.empty else 0)
    return df


# ═══════════════════════════════════════════════════════════════
#  [ADD-4] 저장 전 필수 컬럼 검증
# ═══════════════════════════════════════════════════════════════
def _validate_and_fill(df: pd.DataFrame,
                       logger: logging.Logger) -> pd.DataFrame:
    """저장 직전 필수 컬럼 누락 시 경고 + 빈 기본값 채워 저장 보장"""
    out = df.copy()
    missing = REQUIRED_COLUMNS - set(out.columns)
    if missing:
        logger.warning("[VALIDATE] 필수 컬럼 누락 → 기본값 채움: %s", sorted(missing))
        for col in missing:
            if col in ("prior_class","eod_pick_flag","schema_version",
                       "strategy","reason","code","date","grade",
                       "weak_items","conv_mode"):
                out[col] = ""
            else:
                out[col] = 0.0
        # prior_class / eod_pick_flag 기본값 보정
        if "prior_class" in missing:
            out["prior_class"] = "WEAK"
        if "eod_pick_flag" in missing:
            out["eod_pick_flag"] = "N"
        if "schema_version" in missing:
            out["schema_version"] = SCHEMA_VERSION
        if "score_final" in missing:
            out["score_final"] = out.get("score", pd.Series(0.0, index=out.index))
        if "risk_penalty" in missing:
            out["risk_penalty"] = 0.0
        if "gap_fail_penalty" in missing:   # [필수-3 v7_1]
            out["gap_fail_penalty"] = 0.0
        if "market_adj" in missing:         # [필수-2 v7_1]
            out["market_adj"] = 0.0
        if "conv_mode" in missing:
            out["conv_mode"] = "UNKNOWN"
    return out



def _build_output(df: pd.DataFrame, today_str: str) -> pd.DataFrame:
    out = df.copy()
    out["rank"]  = range(1, len(out) + 1)
    out["date"]  = today_str
    # [BUG-A v7_0] score_dyn_blend(동태혼합 임시값)를 score 기반으로 사용
    # score_final 컬럼은 이 시점에 존재하지 않음 - _calc_score_final()에서 단독 생성
    if "score_dyn_blend" in out.columns:
        out["score"] = pd.to_numeric(out["score_dyn_blend"], errors="coerce").fillna(0.0).round(2)
    else:
        out["score"] = pd.to_numeric(out.get("score", pd.Series(0.0, index=out.index)),
                                     errors="coerce").fillna(0.0).round(2)
    out["grade"] = out["score"].apply(_grade)

    def _strategy(r: pd.Series) -> str:
        allout = _f(r.get("allout_signal", 0))
        if allout and _f(r.get("inst_consec", 0)) >= 3:
            return "ALLOUT_INST_MOMENTUM"
        if allout:
            return "ALLOUT_MOMENTUM"
        if _f(r.get("dyn_new_high",0)) >= 2 and _f(r.get("dyn_val_ok",0)):
            return "DYN_MOMENTUM_BUY"
        if _f(r.get("vpin",0)) >= 0.70 and _f(r.get("inst_consec",0)) >= 3:
            return "OFI_INST_VPIN_HIGH"
        if _f(r.get("high60_ratio",0)) >= 1.0 and _f(r.get("ofi_accel",0)) >= 0.2:
            return "BREAKOUT_OFI_BUY"
        if _f(r.get("residual_momentum",0)) >= 3.0:
            return "RESIDUAL_MOM_BUY"
        if _f(r.get("ofi_accel",0)) >= 0.3:
            return "OFI_ACCEL_BUY"
        return "KOSDAQ_EOD"

    out["strategy"] = out.apply(_strategy, axis=1)

    out["reason"] = out.apply(lambda r: json.dumps({
        "score":          round(_f(r.get("score_final")),    2),
        "attack_score":   round(_f(r.get("attack_score")),   2),
        "defense_score":  round(_f(r.get("defense_score")),  2),
        "ofi_accel":      round(_f(r.get("ofi_accel")),      4),
        "vpin":           round(_f(r.get("vpin")),           4),
        "residual_mom":   round(_f(r.get("residual_momentum")),2),
        "high60_ratio":   round(_f(r.get("high60_ratio")),   4),
        "val_ratio":      round(_f(r.get("val_ratio")),      2),
        "inst_consec":    int(_f(r.get("inst_consec"))),
        "close_position": round(_f(r.get("close_position")), 3),
        "last5_val_accel":round(_f(r.get("last5_value_accel")),3),
        "upper_wick":     round(_f(r.get("upper_wick_ratio",1)),4),
        "gap_predict":    round(_f(r.get("gap_predict_score")), 2),
        "dyn_score":      round(_f(r.get("dyn_score")),      2),
        "dyn_hold":       int(_f(r.get("dyn_hold_flag"))),
        "winner_gap":     round(_f(r.get("winner_gap")),     2),
        "conviction":     round(_f(r.get("conviction")),     2),
        "conv_mode":      str(r.get("conv_mode","UNKNOWN")),
        "allout":         int(_f(r.get("allout_signal"))),
        "history_bonus":  round(_f(r.get("history_bonus",0)), 2),
        "gap_fail_penalty": round(_f(r.get("gap_fail_penalty",0)), 2),  # [필수-3 v7_1]
        "market_adj":     round(_f(r.get("market_adj",0)), 2),           # [필수-2 v7_1]
        "weak_items":     str(r.get("weak_items","")).strip("|"),
        "mkt_risk":       int(_f(r.get("mkt_risk_flag"))),
    }, ensure_ascii=True, separators=(",",":")), axis=1)

    for c in OUT_COLUMNS:
        if c not in out.columns:
            out[c] = ("" if c in
                      ("strategy","reason","code","date","grade","weak_items",
                       "conv_mode","prior_class","eod_pick_flag","schema_version",
                       "siga_entry_class")           # [v9.9]
                      else 0.0)

    # prior 필드 기본값 보정 (빈 문자열 방지)
    if "prior_class" not in out.columns or (out["prior_class"] == 0.0).any():
        out["prior_class"] = out.get("prior_class", "WEAK").replace(0.0, "WEAK")
    if "eod_pick_flag" not in out.columns or (out["eod_pick_flag"] == 0.0).any():
        out["eod_pick_flag"] = out.get("eod_pick_flag", "N").replace(0.0, "N")
    out["schema_version"] = SCHEMA_VERSION
    # [BUG-A v7_0] score_final은 _calc_score_final()에서 후속 생성 - 여기서는 기본값만
    if "score_final" not in out.columns:
        out["score_final"] = out["score"].copy()
    if "risk_penalty" not in out.columns:
        out["risk_penalty"] = 0.0
    if "gap_fail_penalty" not in out.columns:   # [필수-3 v7_1]
        out["gap_fail_penalty"] = 0.0
    if "market_adj" not in out.columns:         # [필수-2 v7_1]
        out["market_adj"] = 0.0
    # [C3 v7.7] siga_ev_pct·pullback_sharpe_proxy CSV 기본값 — pkl과 CSV 경로 일관성
    if "siga_ev_pct" not in out.columns:
        out["siga_ev_pct"] = 0.0
    if "pullback_sharpe_proxy" not in out.columns:
        out["pullback_sharpe_proxy"] = 0.0
    if "siga_priority_score" not in out.columns:    # [v9.9]
        out["siga_priority_score"] = 0.0
    if "siga_entry_class" not in out.columns:       # [v9.9]
        out["siga_entry_class"] = "WATCH"

    result = out[OUT_COLUMNS].copy()
    result["code"] = result["code"].astype(str).str.zfill(6)
    return result


# ═══════════════════════════════════════════════════════════════
#  Score History - 다일 추적 (A1/A2/A3)
# ═══════════════════════════════════════════════════════════════
def _load_score_history(logger: logging.Logger) -> pd.DataFrame:
    try:
        if not SCORE_HISTORY_PATH.exists():
            return pd.DataFrame()
        df = pd.read_csv(str(SCORE_HISTORY_PATH), dtype={"code": str})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["code"] = df["code"].str.zfill(6)
        return df
    except Exception as e:
        logger.warning("[HIST] score_history 로드 실패: %s", e)
        return pd.DataFrame()


def _calc_history_bonus(codes: list, today_str: str,
                        hist: pd.DataFrame,
                        logger: logging.Logger) -> pd.Series:
    """A2: 3일연속 rank≤20 보너스 / A3: 스코어 우상향 기울기 보너스"""
    bonus = pd.Series(0.0, index=codes)
    if hist.empty:
        return bonus

    today_dt = pd.Timestamp(today_str)
    past = hist[hist["date"] < today_dt].copy()
    if past.empty:
        return bonus

    trade_dates = sorted(past["date"].unique(), reverse=True)

    for code in codes:
        cd = past[past["code"] == code].sort_values("date")
        if cd.empty:
            continue

        # A2: 최근 3거래일 연속 rank≤20
        last3_dates = trade_dates[:3]
        if len(last3_dates) == 3:
            ranks_3 = []
            for d in last3_dates:
                row = cd[cd["date"] == d]
                if not row.empty:
                    ranks_3.append(int(row["rank"].iloc[0]))
            if len(ranks_3) == 3 and all(r <= HIST_RANK_WINDOW for r in ranks_3):
                bonus[code] += HIST_CONSEC_BONUS
            elif len(ranks_3) == 2 and all(r <= HIST_RANK_WINDOW for r in ranks_3):
                bonus[code] += round(HIST_CONSEC_BONUS * 0.4, 2)

        # A3: 5일 평균 → 3일 평균 → 최근 1일 우상향
        if len(trade_dates) >= 5:
            scores_5 = cd[cd["date"].isin(trade_dates[:5])]["score"]
            scores_3 = cd[cd["date"].isin(trade_dates[:3])]["score"]
            scores_1 = cd[cd["date"] == trade_dates[0]]["score"]
            if len(scores_5) >= 3 and len(scores_3) >= 2 and not scores_1.empty:
                avg5 = float(scores_5.mean())
                avg3 = float(scores_3.mean())
                last = float(scores_1.iloc[0])
                if last > avg3 > avg5:
                    bonus[code] += HIST_SLOPE_BONUS

    logger.info("[HIST] 히스토리보너스: consec_max=%.1f slope_max=%.1f 대상=%d",
                HIST_CONSEC_BONUS, HIST_SLOPE_BONUS, int((bonus > 0).sum()))
    return bonus


def _save_score_history(out_df: pd.DataFrame, today_str: str,
                        logger: logging.Logger) -> None:
    """A1: score_history.csv 누적저장, 60거래일 초과 자동삭제
    [FIX-V72-6] top5→top10 확장 - 6~10위 급부상 종목 pullback_watch 포착 가능
    """
    try:
        _safe_mkdir(SCORE_HISTORY_PATH.parent)
        cols = ["date", "code", "score", "rank"]
        # [FIX-V72-6] 상위 10종목 저장 (기존 5 → 10)
        # [HIST-WIDE 2026-05-30] head(10) → head(SCORE_HISTORY_TOP_N=25). 광역 스냅샷 재절단 방지.
        today_rows = out_df.head(SCORE_HISTORY_TOP_N)[["code", "score", "rank"]].copy()
        today_rows["date"] = today_str

        existing = _load_score_history(logger)
        if existing.empty:
            combined = today_rows[cols]
        else:
            existing["date"] = existing["date"].dt.strftime("%Y-%m-%d")
            existing = existing[existing["date"] != today_str]
            combined = pd.concat([existing[cols], today_rows[cols]], ignore_index=True)

        combined["date"] = pd.to_datetime(combined["date"])
        trade_dates = sorted(combined["date"].unique(), reverse=True)
        keep_dates  = set(trade_dates[:HIST_KEEP_DAYS])
        combined    = combined[combined["date"].isin(keep_dates)]
        combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")

        tmp = SCORE_HISTORY_PATH.with_suffix(".tmp")
        combined.to_csv(str(tmp), index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(SCORE_HISTORY_PATH))
        logger.info("[HIST] score_history.csv 저장: %d행 / %d거래일",
                    len(combined), len(keep_dates))
    except Exception as e:
        logger.warning("[HIST] score_history 저장 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  [FIX-6] 3전략 공유 캐시 빌더
# ═══════════════════════════════════════════════════════════════
def _build_shared_cache(out: pd.DataFrame, hist_df: pd.DataFrame,
                        today_str: str, mkt_risk_flag: int,
                        kosdaq_chg: float,
                        logger: logging.Logger) -> dict:
    """eod_shared_data.pkl 구조 확장
    - 종배(EOD): 기존 필드 유지 + score_final/risk_penalty/conv_mode
    - 시가(SIGA): [SUPPLY-2] priority/gap_fail/open_drive 스코어링, 최대 3개
    - 추세눌림: [SUPPLY-3] priority/quality/decay_risk 스코어링, 최대 5개
    - 공용: [SUPPLY-4] market_bias_class/attack_scale/siga_enable/pullback_enable
    """
    top_row = out.iloc[0] if not out.empty else None

    # ─────────────────────────────────────────────────────────────
    #  [SUPPLY-1] top5_map - 6개 필드 확장
    #  gap_predict_score / close_position / upper_wick_ratio /
    #  last5_value_accel / close_value_ratio / dominance_ratio
    # ─────────────────────────────────────────────────────────────
    top5_map: dict = {}
    try:
        for _, r in out.head(5).iterrows():
            code_key = str(r["code"]).zfill(6)
            top5_map[code_key] = {
                # ── 기존 필드 ──────────────────────────────────
                "rank":           int(_f(r.get("rank", 0))),
                "score":          round(float(_f(r.get("score", 0))), 2),
                "score_final":    round(float(_f(r.get("score_final", 0))), 2),
                "risk_penalty":   round(float(_f(r.get("risk_penalty", 0))), 2),
                "grade":          str(r.get("grade", "")),
                "winner_gap":     round(float(_f(r.get("winner_gap", 0))), 2),
                "conviction":     round(float(_f(r.get("conviction", 0))), 2),
                "conv_mode":      str(r.get("conv_mode", "UNKNOWN")),
                "attack_score":   round(float(_f(r.get("attack_score", 0))), 2),
                "defense_score":  round(float(_f(r.get("defense_score", 0))), 2),
                "allout_signal":  int(_f(r.get("allout_signal", 0))),
                "position_ratio": round(float(_f(r.get("position_ratio", 0))), 2),
                "prior_class":    str(r.get("prior_class", "WEAK")),
                "prior_weight":   round(float(_f(r.get("prior_weight", 0))), 2),
                "eod_pick_flag":  str(r.get("eod_pick_flag", "N")),
                "schema_version": SCHEMA_VERSION,
                "mkt_risk_flag":  int(_f(r.get("mkt_risk_flag", 0))),
                "strategy":       str(r.get("strategy", "")),
                "inst_consec":    int(_f(r.get("inst_consec", 0))),
                "history_bonus":  round(float(_f(r.get("history_bonus", 0))), 2),
                # ── [SUPPLY-1] 6개 필드 신규 추가 ───────────────
                "gap_predict_score":  round(float(_f(r.get("gap_predict_score", 0))), 2),
                "close_position":     round(float(_f(r.get("close_position", 0))), 4),
                "upper_wick_ratio":   round(float(_f(r.get("upper_wick_ratio", 1.0))), 4),
                "last5_value_accel":  round(float(_f(r.get("last5_value_accel", 0))), 4),
                "close_value_ratio":  round(float(_f(r.get("close_value_ratio", 0))), 4),
                "dominance_ratio":    round(float(_f(r.get("dominance_ratio", 1.0))), 3),
            }
    except Exception as e:
        logger.warning("[BUILD] top5_map 구성 실패: %s", e)

    # ─────────────────────────────────────────────────────────────
    #  [SUPPLY-2] siga_candidates - 새 스코어링 로직, 최대 3개
    #  prior_class/conviction/winner_gap 기반 우선순위 + block 필터
    # ─────────────────────────────────────────────────────────────
    _PC_SCORE = {"ULTRA": 4.0, "STRONG": 3.0, "MID": 2.0, "WEAK": 0.0}
    siga_scored = []
    siga_score_map: dict = {}   # [v9.9] 전체 out 행용: code → {siga_priority_score, siga_entry_class}
    try:
        if not out.empty:
            for _, r in out.iterrows():
                prior_class  = str(r.get("prior_class", "WEAK"))
                conviction   = float(_f(r.get("conviction", 0)))
                winner_gap   = float(_f(r.get("winner_gap", 0)))
                close_pos    = float(_f(r.get("close_position", 0)))
                gap_predict  = float(_f(r.get("gap_predict_score", 0)))
                upper_wick   = float(_f(r.get("upper_wick_ratio", 1.0)))
                risk_pen     = float(_f(r.get("risk_penalty", 0)))
                dominance    = float(_f(r.get("dominance_ratio", 1.0)))
                vpin         = float(_f(r.get("vpin", 0)))
                inst_consec  = int(_f(r.get("inst_consec", 0)))
                code         = str(r.get("code", ""))

                # siga_open_drive_bias (높을수록 시가 강세 편향, 0~100)
                # [v7.9] priority_score 반영을 위해 먼저 계산
                siga_open_drive_bias = round(
                    vpin * 30.0
                    + min(inst_consec / 5.0, 1.0) * 40.0
                    + close_pos * 30.0
                , 2)

                # siga_priority_score (0~100): 시가 진입 우선순위
                # [v7.9] open_drive_bias를 직접 반영 (max 10점 추가)
                # 기존 95점 만점 → 100점 만점으로 조정
                # open_drive_bias = vpin×30 + inst_consec×40 + close_pos×30 (0~100)
                # 이를 10점 스케일로 정규화 → priority에 직접 기여
                siga_priority_score = round(
                    _PC_SCORE.get(prior_class, 0.0) * 15.0        # max 60 (ULTRA)
                    + min(conviction / 82.0, 1.0) * 20.0          # max 20
                    + min(winner_gap / 11.5, 1.0) * 10.0          # max 10
                    + close_pos * 5.0                              # max  5
                    + min(gap_predict / 15.0, 1.0) * 5.0          # max  5
                    + min(siga_open_drive_bias / 100.0, 1.0) * 10.0  # [v7.9] max 10
                , 2)

                # siga_gap_fail_score (낮을수록 갭업 안전)
                siga_gap_fail_score = round(
                    risk_pen * 2.0
                    + max(0.0, 1.0 - upper_wick) * 20.0
                , 2)

                # siga_entry_class
                # [v7.9] gap_fail hard SKIP 제거 → sorting 감점으로 전환
                # SKIP은 극단 gap_fail(≥9.0)만 유지, 나머지는 WATCH로 등급화
                _siga_pri_min = float(os.environ.get("SIGA_PRIORITY_MIN", "50"))
                _siga_gap_max = float(os.environ.get("SIGA_GAP_FAIL_MAX", "5.5"))
                if siga_priority_score >= _siga_pri_min and siga_gap_fail_score < _siga_gap_max:
                    siga_entry_class = "PRIME"  # [v7.9] 55/4.5→50/5.5: PRIME 현실화
                elif siga_gap_fail_score >= 9.0:
                    siga_entry_class = "SKIP"    # 극단 갭실패 위험만 차단
                else:
                    siga_entry_class = "WATCH"   # 조건 미달 → WATCH로 통과

                # [v7.6] siga_block dominance 1.10 유지 (수익률 우선)
                # dominance 1.10~1.15 구간 EV>0 → 차단 말고 DOMINANCE_SOFT_THR 패널티(×0.75)로 진입
                # 차단(1.15)보다 축소진입(1.10)이 연간 수익률 약 +70% 우위
                # POS_CAP_DOM_THR(1.08) 은 포지션 캡 기준 - 차단 기준과 분리
                siga_block_flag = (
                    risk_pen >= 4.0
                    # [S1 v7.8] dominance 기준 완전 제거 — 최대 병목 해소
                    # Conviction Gate(winner_gap≥6.5)가 이미 압도성 검증
                    # dominance는 POS_CAP_DOM_THR(1.08)로 포지션 캡만 적용
                    or (prior_class == "WEAK" and conviction < 20)
                    or conviction < 40.0    # [S3 v7.9] 58.0→40.0: conviction 41.8 과차단 해소
                    or winner_gap < 2.5     # [S2 v7.9] 3.5→2.5: winner_gap 2.9 과차단 해소
                    or upper_wick < 0.975
                )

                if siga_block_flag:
                    logger.info(
                        "[SIGA-BLOCK] code=%s prior=%s conv=%.1f wgap=%.1f"
                        " risk=%.1f wick=%.4f → 차단"
                        " (dom=%.2f 참고용—block조건 제외됨)",
                        code, prior_class, conviction, winner_gap,
                        risk_pen, upper_wick, dominance
                    )
                else:
                    logger.info(
                        "[SIGA-PRIOR] code=%s priority=%.1f gap_fail=%.1f"
                        " open_drive=%.1f entry_class=%s",
                        code, siga_priority_score, siga_gap_fail_score,
                        siga_open_drive_bias, siga_entry_class
                    )

                # [v9.9] 전체 8개 row 기록 — score_eod.csv 반영용 (block/SKIP 포함)
                _eff_ps = max(0.0, round(siga_priority_score - siga_gap_fail_score * 0.5, 2))
                _excl   = siga_block_flag or (siga_entry_class == "SKIP")
                siga_score_map[code] = {
                    "siga_priority_score": 0.0 if _excl else _eff_ps,
                    "siga_entry_class":    "SKIP" if _excl else siga_entry_class,
                }

                if not siga_block_flag and siga_entry_class != "SKIP":
                    # [S1][C1 v7.7] ev_pct 단위 통일: × 100 → 브리지 EV_CAUTION_MIN=1.00(1%)과 호환
                    # 기존 공식 결과값 0~1.5(비율) → 브리지가 EV%로 해석해 단위 불일치 발생
                    # 수정: 결과값에 × 100 적용 → 0~150% 범위 → 브리지 기준과 단위 통일
                    _sf   = float(_f(r.get("score_final", 0)))
                    _ic   = max(inst_consec, 1)
                    _gp   = gap_predict / 15.0  # 0~1 정규화
                    _ev   = round(
                        (_sf / 100.0) * (1.0 + min(_ic / 5.0, 0.5)) * (0.5 + _gp * 0.5) * 100.0,
                        2
                    )  # [C1] × 100 → EV% 단위
                    siga_scored.append({
                        "code":                  code,
                        "score":                 round(float(_f(r.get("score", 0))), 2),
                        "score_final":           round(float(_f(r.get("score_final", 0))), 2),
                        "ev_pct":                _ev,    # [S1] 신규 — 브리지 EV 재계산 대체
                        "inst_consec":           inst_consec,
                        "gap_predict_score":     gap_predict,
                        "close_position":        close_pos,
                        "upper_wick_ratio":      upper_wick,
                        "vpin":                  vpin,
                        "history_bonus":         round(float(_f(r.get("history_bonus", 0))), 2),
                        "prior_class":           prior_class,
                        "prior_weight":          round(float(_f(r.get("prior_weight", 0))), 2),
                        "risk_penalty":          risk_pen,
                        "dominance_ratio":       dominance,
                        "siga_priority_score":   max(0.0, round(siga_priority_score - siga_gap_fail_score * 0.5, 2)),  # [v7.9] gap_fail 감점
                        "siga_gap_fail_score":   siga_gap_fail_score,
                        "siga_open_drive_bias":  siga_open_drive_bias,
                        "siga_entry_class":      siga_entry_class,
                        "siga_block_flag":       False,
                    })
    except Exception as e:
        logger.warning("[BUILD] siga_candidates 구성 실패: %s", e)

    siga_cands = sorted(
        siga_scored, key=lambda x: x["siga_priority_score"], reverse=True
    )
    logger.info("[SIGA-PRIOR] 최종 후보=%d (PRIME=%d WATCH=%d)",
                len(siga_cands),
                sum(1 for s in siga_cands if s["siga_entry_class"] == "PRIME"),
                sum(1 for s in siga_cands if s["siga_entry_class"] == "WATCH"))

    try:
        if siga_cands:
            _atomic_write_csv(pd.DataFrame(siga_cands), SIGA_CANDIDATES_PATH)
            logger.info("[SIGA-CSV] siga_candidates.csv 저장: %d종목 → %s",
                        len(siga_cands), SIGA_CANDIDATES_PATH)
        else:
            logger.warning("[SIGA-CSV] siga_candidates 비어 있음 → CSV 저장 스킵")
    except Exception as _e:
        logger.warning("[SIGA-CSV] siga_candidates.csv 저장 실패: %s", _e)

    # ─────────────────────────────────────────────────────────────
    #  [SUPPLY-3] pullback_watch - 새 스코어링 로직, 최대 5개
    #  avg_rank_5d + quality + decay_risk 복합 평가
    # ─────────────────────────────────────────────────────────────
    pullback_scored = []
    try:
        if not hist_df.empty and not out.empty:
            today_dt  = pd.Timestamp(today_str)
            past      = hist_df[hist_df["date"] < today_dt]
            if not past.empty:
                td_sorted = sorted(past["date"].unique(), reverse=True)[:5]
                recent5   = past[past["date"].isin(td_sorted)]
                avg_rank_df = (
                    recent5.groupby("code")["rank"]
                    .mean()
                    .reset_index(name="avg_rank")
                )
                # [BUG-B v7_0] avg_rank ≤ 5로 수정
                # [P1 v7.8] ≤5 → ≤8 완화: 5일 8위 이내 = 꾸준한 대장주 기준
                # 수익 높은 조건 = 5일+ 기관 지지 종목 → 범위 확대로 포착
                watch_codes = avg_rank_df[avg_rank_df["avg_rank"] <= 8]["code"].tolist()

                for code in watch_codes:
                    row = out[out["code"] == code]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                    avg_rank_5d_val = float(
                        avg_rank_df[avg_rank_df["code"] == code]["avg_rank"].iloc[0]
                    )
                    prior_class  = str(r.get("prior_class", "WEAK"))
                    upper_wick   = float(_f(r.get("upper_wick_ratio", 1.0)))
                    risk_pen     = float(_f(r.get("risk_penalty", 0)))
                    close_pos    = float(_f(r.get("close_position", 0)))
                    l5a          = float(_f(r.get("last5_value_accel", 0)))
                    inst_consec  = int(_f(r.get("inst_consec", 0)))
                    score_val    = float(_f(r.get("score", 0)))

                    # pullback_priority_score (0~100): 지속성 + 현재 점수 + 기관 + 종가위치
                    # [P4 v7.8] 가중치 재조정 — 기관 지속성이 눌림 수익률과 가장 상관관계 높음
                    # inst_consec 지속성 20→25 / score 30→27 / close_pos 10→8
                    pullback_priority_score = round(
                        max(0.0, (HIST_RANK_WINDOW - avg_rank_5d_val)
                            / HIST_RANK_WINDOW) * 40.0             # rank 안정성 max 40 (유지)
                        + score_val / 100.0 * 27.0                  # [P4] 현재 점수 30→27
                        + min(inst_consec / 5.0, 1.0) * 25.0       # [P4] 기관 지속 20→25
                        + close_pos * 8.0                           # [P4] 종가위치 10→8
                    , 2)

                    # pullback_quality_score (0~100): 구조 품질
                    pullback_quality_score = round(
                        upper_wick * 30.0
                        + close_pos * 30.0
                        + max(0.0, 1.0 - risk_pen / 5.0) * 20.0
                        + min(l5a / 2.0, 1.0) * 20.0
                    , 2)

                    # pullback_decay_risk: 추세 붕괴 위험
                    pullback_decay_risk = round(
                        risk_pen
                        + max(0.0, 1.0 - upper_wick) * 10.0
                    , 2)

                    # pullback_setup_class
                    # [P3 v7.8] STRONG 기준 완화 priority≥60+quality≥60 → ≥50+≥55
                    # 근거: 동시 충족 약 15% → 35% 수준으로 STRONG 셋업 확보
                    if pullback_priority_score >= 50 and pullback_quality_score >= 55:
                        pullback_setup_class = "STRONG"
                    elif pullback_priority_score >= 40:
                        pullback_setup_class = "MODERATE"
                    else:
                        pullback_setup_class = "WEAK_SETUP"

                    # pullback_block_flag
                    # [P2 v7.8] inst_consec < 1 조건 제거
                    # 근거: pullback_watch avg_rank≤8 자체가 5일 기관 지지 검증
                    #       inst_consec=0이어도 당일 강한 기관 유입 종목 포착 가능
                    #       decay_risk·upper_wick·prior_class가 품질 보호 역할 유지
                    # [N3 v7.8] avg_rank_5d_val > 8: watch_codes≤8 필터와 중복이나
                    #   avg_rank_df 집계 후 out 조인 과정에서 데이터 불일치 방어용 유지
                    pullback_block_flag = (
                        pullback_decay_risk >= 5.0
                        or avg_rank_5d_val > 8   # [P1 v7.8] 방어적 재확인 (watch_codes와 중복)
                        or prior_class == "WEAK"
                        or upper_wick < 0.975
                        # inst_consec < 1 제거 [P2 v7.8]
                    )

                    if pullback_block_flag:
                        logger.info(
                            "[PULLBACK-BLOCK] code=%s decay_risk=%.1f avg_rank=%.1f"
                            " prior=%s wick=%.4f → 차단",
                            code, pullback_decay_risk, avg_rank_5d_val,
                            prior_class, upper_wick
                        )
                    else:
                        logger.info(
                            "[PULLBACK-PRIOR] code=%s priority=%.1f quality=%.1f"
                            " decay=%.1f setup=%s",
                            code, pullback_priority_score, pullback_quality_score,
                            pullback_decay_risk, pullback_setup_class
                        )

                    if not pullback_block_flag:
                        # [S2][C1 v7.7] ev_pct 단위 통일 × 100 → 브리지 EV_CAUTION_MIN=1.00(1%)과 호환
                        _sf_pb  = float(_f(r.get("score_final", 0)))
                        _ic_pb  = max(int(_f(r.get("inst_consec", 0))), 1)
                        _gp_pb  = float(_f(r.get("gap_predict_score", 0))) / 15.0
                        _ev_pb  = round(
                            (_sf_pb / 100.0) * (1.0 + min(_ic_pb / 5.0, 0.5)) * (0.5 + _gp_pb * 0.5) * 100.0,
                            2
                        )  # [C1] × 100 → EV% 단위
                        # [M2 v7.7] sharpe_proxy 상한 2.0 클리핑 — evolution_engine 혼동 방지
                        _sp_pb  = round(
                            min(
                                (_sf_pb / 50.0) * (1.0 - min(pullback_decay_risk / 10.0, 1.0)),
                                2.0  # [M2] 명시적 상한 — Sharpe 실제값 오해 방지
                            ),
                            3
                        )
                        pullback_scored.append({
                            "code":                  code,
                            "score":                 round(score_val, 2),
                            "score_final":           round(float(_f(r.get("score_final", 0))), 2),
                            "ev_pct":                _ev_pb,    # [S2] 신규
                            "sharpe_proxy":          _sp_pb,    # [S2] 신규 — 브리지 Sharpe 대체
                            "inst_consec":           inst_consec,
                            "avg_rank_5d":           round(avg_rank_5d_val, 1),
                            "prior_class":           prior_class,
                            "prior_weight":          round(float(_f(r.get("prior_weight", 0))), 2),
                            "risk_penalty":          risk_pen,
                            "upper_wick_ratio":      upper_wick,
                            "close_position":        close_pos,
                            "last5_value_accel":     l5a,
                            "pullback_priority_score": pullback_priority_score,
                            "pullback_quality_score":  pullback_quality_score,
                            "pullback_decay_risk":     pullback_decay_risk,
                            "pullback_setup_class":    pullback_setup_class,
                            "pullback_block_flag":     False,
                        })
    except Exception as e:
        logger.warning("[BUILD] pullback_watch 구성 실패: %s", e)

    pullback_watch = sorted(
        pullback_scored, key=lambda x: x["pullback_priority_score"], reverse=True
    )[:5]
    logger.info("[PULLBACK-PRIOR] 최종 후보=%d (STRONG=%d MODERATE=%d)",
                len(pullback_watch),
                sum(1 for p in pullback_watch if p["pullback_setup_class"] == "STRONG"),
                sum(1 for p in pullback_watch if p["pullback_setup_class"] == "MODERATE"))

    # ─────────────────────────────────────────────────────────────
    #  [SUPPLY-4] market_state 확장 - 3전략 활성화 라우팅 신호
    # ─────────────────────────────────────────────────────────────
    if kosdaq_chg >= 0.5:
        market_bias_class = "BULL"
    elif kosdaq_chg >= -1.0:
        market_bias_class = "NEUTRAL"
    else:
        market_bias_class = "CAUTION"

    if mkt_risk_flag == 0:
        market_attack_scale = 1.0
    elif kosdaq_chg >= -1.5:
        market_attack_scale = 0.8
    else:
        market_attack_scale = 0.5

    siga_enable     = (mkt_risk_flag == 0 or kosdaq_chg >= -1.5) and len(siga_cands) > 0
    # [PULLBACK_WATCH_DROP 2026-05-13] len(pullback_watch)>0 조건 제거. 5/12 EOD pullback_watch=0으로 5/13 14일째 매수 0건. 시장위험만 보호.
    pullback_enable = mkt_risk_flag == 0

    # [S3] 시장 편향별 bridge_ev_weight 산출
    # 헤지펀드 표준: EV 가중치는 시장 상태를 아는 스코어보드가 결정
    # 브리지는 이 값을 참조만 → 자체 EV 가중치 계산 불필요
    # [M1 v7.7] 연결 경로 명시:
    #   1) 스코어보드 → pkl market_state["bridge_ev_weight"] 저장 (이미 구현)
    #   2) execution_engine이 pkl 읽어 sig["bridge_ev_weight"]에 심어야 함
    #   3) 브리지 sig.get("bridge_ev_weight", EV_WEIGHT)로 참조 ← 현재 경로
    #   ※ execution_engine이 2)를 수행하지 않으면 브리지는 기본값(0.60) 사용
    if market_bias_class == "BULL":
        _bridge_ev_w = 0.65   # 강세장: EV 비중 상향 (기관 모멘텀 신뢰)
    elif market_bias_class == "CAUTION":
        _bridge_ev_w = 0.50   # 주의장: EV/ride 균등 (보수적)
    else:
        _bridge_ev_w = 0.60   # 중립: 기본값

    shared = {
        # ── 종배(EOD) - 기존 + score_final/risk_penalty/conv_mode ──
        "date":           today_str,
        "engine_ver":     ENGINE_VER,
        "schema_version": SCHEMA_VERSION,
        "score_eod":      out,
        "mkt_risk_flag":  mkt_risk_flag,
        "kosdaq_chg":     kosdaq_chg,
        # top1 명시 필드 (top1 부재 시 안전값)
        "top1_code":           str(top_row["code"])               if top_row is not None else "",
        "top1_score":          round(float(_f(top_row.get("score",0))),2)       if top_row is not None else 0.0,
        "top1_score_final":    round(float(_f(top_row.get("score_final",0))),2) if top_row is not None else 0.0,
        "top1_grade":          str(top_row.get("grade",""))        if top_row is not None else "",
        "top1_winner_gap":     round(float(_f(top_row.get("winner_gap",0))),2)  if top_row is not None else 0.0,
        "top1_conviction":     round(float(_f(top_row.get("conviction",0))),2)  if top_row is not None else 0.0,
        "top1_allout_signal":  int(_f(top_row.get("allout_signal",0)))           if top_row is not None else 0,
        "top1_position_ratio": float(_f(top_row.get("position_ratio",0.6)))     if top_row is not None else 0.6,
        # 레거시 키 유지 (기존 브릿지 호환)
        "top_code":       str(top_row["code"])    if top_row is not None else "",
        "allout_signal":  int(_f(top_row.get("allout_signal", 0))) if top_row is not None else 0,
        "position_ratio": float(_f(top_row.get("position_ratio", 0.6))) if top_row is not None else 0.6,
        "conv_mode":      str(top_row.get("conv_mode", "UNKNOWN")) if top_row is not None else "UNKNOWN",
        # top5 목록
        "top5_codes": out["code"].head(5).tolist() if not out.empty else [],
        "top5_map":   top5_map,
        # ── 시가(SIGA) - [SUPPLY-2] ──────────────────────────────
        "siga_candidates": siga_cands,
        "siga_score_map":  siga_score_map,   # [v9.9] 전체 8개 map — score_eod.csv 재저장용
        # ── 추세눌림 - [SUPPLY-3] ────────────────────────────────
        "pullback_watch":  pullback_watch,
        # ── 3전략 공용 시장상태 - [SUPPLY-4] ─────────────────────
        "market_state": {
            "kosdaq_chg":         round(kosdaq_chg, 2),
            "mkt_risk_flag":      mkt_risk_flag,
            "today_str":          today_str,
            "top5_codes":         out["code"].head(5).tolist() if not out.empty else [],
            "market_bias_class":  market_bias_class,   # BULL/NEUTRAL/CAUTION
            "market_attack_scale":market_attack_scale,  # 1.0/0.8/0.5
            "siga_enable":        siga_enable,          # 시가 전략 활성 여부
            "pullback_enable":    pullback_enable,       # 추세눌림 전략 활성 여부
            "bridge_ev_weight":   _bridge_ev_w,         # [S3] 브리지 EV 가중치 공급
        },
    }
    return shared



# ═══════════════════════════════════════════════════════════════
#  [v7.5 FIX-2] 전일 feedback next_day_open_ret 자동 갱신
# ═══════════════════════════════════════════════════════════════
def _update_prev_feedback(px3: pd.DataFrame, today_str: str,
                          logger: logging.Logger) -> None:
    """전일 feedback_{date}.json에 next_day_open_ret / was_profitable 자동 기입.
    px3에서 today_str 당일 종목별 시가/종가를 읽어 전일 selected_code의 수익률 계산.
    이미 기입된 파일은 스킵 (중복 갱신 방지).
    """
    import datetime as _dt
    try:
        if not EVOLUTION_FEEDBACK_DIR.exists():
            return
        # 전일 날짜 역방향 탐색 (최대 5일 - 주말 대응)
        today_d = _dt.datetime.strptime(today_str, "%Y-%m-%d").date()
        fb_path = None
        prev_str = None
        for _back in range(1, 6):
            _prev_d  = today_d - _dt.timedelta(days=_back)
            _fb_path = EVOLUTION_FEEDBACK_DIR / f"feedback_{_prev_d}.json"
            if _fb_path.exists():
                fb_path  = _fb_path
                prev_str = str(_prev_d)
                break
        if fb_path is None:
            logger.debug("[EVOL-UPDATE] 전일 feedback 파일 없음 - 스킵")
            return
        with open(fb_path, "r", encoding="utf-8-sig") as f:
            fb = json.load(f)
        # 이미 기입된 경우 스킵
        if fb.get("next_day_open_ret") is not None:
            logger.debug("[EVOL-UPDATE] 이미 기입됨 - 스킵: %s", fb_path.name)
            return
        selected_code = str(fb.get("selected_code", "")).zfill(6)
        if not selected_code or selected_code == "000000":
            return
        # 오늘 데이터에서 해당 종목 시가/종가 추출
        today_rows = px3[(px3["date"] == today_str) & (px3["code"] == selected_code)]
        if today_rows.empty:
            logger.debug("[EVOL-UPDATE] 오늘 데이터 없음: %s", selected_code)
            return
        today_open  = float(today_rows["open"].iloc[0])
        today_close = float(today_rows["close"].iloc[-1])
        today_high  = float(today_rows["high"].max()) if "high" in today_rows.columns else today_close
        if today_open <= 0:
            return
        # 전일 종가 추출 - next_day_open_ret = 전일종가 대비 오늘시가
        open_ret = 0.0
        if prev_str:
            prev_rows = px3[(px3["date"] == prev_str) & (px3["code"] == selected_code)]
            if not prev_rows.empty:
                prev_close_price = float(prev_rows["close"].iloc[-1])
                if prev_close_price > 0:
                    open_ret = round((today_open / prev_close_price - 1.0), 4)
        close_ret = round((today_close / today_open - 1.0), 4)
        max_ret   = round((today_high  / today_open - 1.0), 4)
        fb["next_day_open_ret"]  = open_ret
        fb["next_day_max_ret"]   = max_ret
        fb["next_day_close_ret"] = close_ret
        fb["was_profitable"]     = bool(open_ret > 0)
        with open(fb_path, "w", encoding="utf-8") as f:
            json.dump(fb, f, ensure_ascii=False, indent=2)
        logger.info("[EVOL-UPDATE] feedback 갱신: %s code=%s open_ret=%.2f%% was_profitable=%s",
                    fb_path.name, selected_code, open_ret * 100, fb["was_profitable"])
    except Exception as e:
        logger.warning("[EVOL-UPDATE] feedback 갱신 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  [W2 v7_0] pnl_strategy_linker 연결 상태 점검
#  evolution_feedback 파일 중 수익률 미기입 비율 체크
#  5거래일 이상 미연결 시 [EVOL-WARN] 로그 - 자기진화 형식화 방지
# ═══════════════════════════════════════════════════════════════
def _check_pnl_linker_health(logger: logging.Logger) -> None:
    """최근 feedback 파일에서 was_profitable=None 비율 점검.
    5일 이상 수익률 단절 시 경고 로그 + [FIX-V72-7] EVOL_FREEZE=True 설정.
    EVOL_FREEZE=True이면 _load_evolved_params가 파라미터 변경 스킵.
    """
    global EVOL_FREEZE
    try:
        if not EVOLUTION_FEEDBACK_DIR.exists():
            return
        fb_files = sorted(EVOLUTION_FEEDBACK_DIR.glob("feedback_*.json"), reverse=True)[:10]
        if not fb_files:
            return
        none_count = 0
        for fp in fb_files:
            try:
                with open(fp, "r", encoding="utf-8-sig") as f:
                    fb = json.load(f)
                if fb.get("was_profitable") is None:
                    none_count += 1
            except Exception:
                continue
        pct = none_count / len(fb_files) * 100
        if none_count >= 5:
            EVOL_FREEZE = True  # [FIX-V72-7] 수익률 미기입 5일+ → 파라미터 동결
            logger.warning(
                "[EVOL-WARN][FREEZE] pnl_strategy_linker 연결 단절 의심: "
                "최근 %d개 중 %d개(%.0f%%) 수익률 미기입 "
                "→ EVOL_FREEZE=True 설정. 파라미터 동결 - 기본값 유지."
                " pnl_strategy_linker 실행 확인 필요.",
                len(fb_files), none_count, pct
            )
        else:
            EVOL_FREEZE = False
            logger.info("[EVOL] pnl_linker 건강도: 최근 %d개 중 %d개 수익률 기입완료 (FREEZE=False)",
                        len(fb_files), len(fb_files) - none_count)
    except Exception as e:
        logger.warning("[EVOL-WARN] pnl_linker 점검 실패: %s", e)


# ═══════════════════════════════════════════════════════════════
#  메인 빌드
# ═══════════════════════════════════════════════════════════════
def _load_kosdaq_codes(logger: logging.Logger) -> Optional[set]:
    """[KOSDAQ-FILTER 2026-06-01] 후보 universe를 KOSDAQ로 제한하기 위한 코드셋.
    소스=eod_daily_bars.csv 최신일 market==KOSDAQ + SKIP_KW(스팩/SPAC/ETN/ETF/리츠/우선주) name 제외.
    Why: 수집기는 KOSDAQ화됐으나 prices_1m 누적분에 장초반(A누수 수정 전) KOSPI 잔존이 있어
         prices_3m/rt_intraday 후보에 KOSPI 대형주·ETF(005930/069500/122630)가 섞임 → 시장필터로 차단.
    실패/빈셋(<100)이면 None → 필터 skip(fail-open, score_eod 보호)."""
    try:
        p = DATA_DIR / "eod_daily_bars.csv"
        if not p.exists() or p.stat().st_size == 0:
            logger.warning("[KOSDAQ-FILTER] eod_daily_bars 없음 → 필터 skip")
            return None
        df = pd.read_csv(p, dtype={"code": str}, encoding="utf-8-sig",
                         usecols=["date", "code", "name", "market"])
        latest = df["date"].max()
        df = df[(df["date"] == latest) & (df["market"] == "KOSDAQ")].copy()
        _skip = ("스팩", "SPAC", "ETN", "ETF", "리츠", "우선주")
        df["name"] = df["name"].fillna("")
        df = df[~df["name"].str.contains("|".join(_skip), na=False)]
        codes = {_norm_code(c) for c in df["code"].tolist()}
        codes.discard("")
        if len(codes) < 100:
            logger.warning("[KOSDAQ-FILTER] 코드셋 %d개(<100) 비정상 → 필터 skip", len(codes))
            return None
        logger.info("[KOSDAQ-FILTER] eod_daily_bars(%s) KOSDAQ+SKIP_KW제외 %d종목 로드", latest, len(codes))
        return codes
    except Exception as e:
        logger.warning("[KOSDAQ-FILTER] 로드 실패(%s) → 필터 skip", e)
        return None


def _load_code_best_theme_sb(logger: logging.Logger) -> dict:
    """[THEME-TOP2 2026-06-16] code → best_theme (code_theme_strength 최신 스냅). 실패=빈dict(무영향)."""
    try:
        _f = DATA_DIR / "theme" / "code_theme_strength.csv"
        if not _f.exists():
            return {}
        _d = pd.read_csv(_f, dtype=str)
        _d.columns = [str(c).strip().lstrip("﻿") for c in _d.columns]
        if "date" in _d.columns and not _d.empty:
            _d = _d[_d["date"] == _d["date"].max()]
        _out = {}
        for _, _r in _d.iterrows():
            _out[_norm_code(_r.get("code", ""))] = str(_r.get("best_theme", "") or "").strip()
        return _out
    except Exception as _e:
        logger.warning("[THEME-TOP2] 테마 로드 실패(%s) → 무영향", _e)
        return {}


def _load_rise5_map_sb(logger: logging.Logger, lb: int = 5) -> dict:
    """[RISE-BAND 2026-06-15 ★친구님] code → 바닥대비 상승%=(현재가/직전lb일최저-1)*100.
    현재가=prices_1m 최신 close(col5), 바닥=eod_daily_bars 직전lb거래일 최저. 실패=빈맵(밴드 skip=fail-open). READ-ONLY."""
    try:
        p1m = PRICES_1M_PATH
        eodp = DATA_DIR / "eod_daily_bars.csv"
        if not p1m.exists() or not eodp.exists():
            return {}
        _p = pd.read_csv(p1m, header=None, dtype={0: str, 1: str})  # [FIX 2026-06-16] col1(ts) int/str 혼합(헤더행 섞임)→sort 에러 방지
        _p = _p[_p[0] != "code"]  # 섞인 헤더행 제거(무해화)
        _p[0] = _p[0].map(_norm_code)
        _p[5] = pd.to_numeric(_p[5], errors="coerce")
        cur = _p.sort_values(1).groupby(0)[5].last()
        _e = pd.read_csv(eodp, usecols=["date", "code", "low"], dtype={"date": str, "code": str})
        _e["code"] = _e["code"].map(_norm_code)
        _e["low"] = pd.to_numeric(_e["low"], errors="coerce")
        _recent = sorted(_e["date"].dropna().unique())[-lb:]
        low5 = _e[_e["date"].isin(_recent)].dropna(subset=["low"]).groupby("code")["low"].min()
        out = {}
        for c, l5 in low5.items():
            cp = cur.get(c)
            if cp is not None and pd.notna(cp) and l5 and l5 > 0:
                out[c] = (float(cp) / float(l5) - 1.0) * 100.0
        return out
    except Exception as e:
        logger.warning("[RISE-BAND] rise5 맵 로드 실패(%s) → 밴드 skip(fail-open)", e)
        return {}


def build_scoreboard(logger: logging.Logger) -> Tuple[pd.DataFrame, int]:

    _load_evolved_params(logger)
    _check_pnl_linker_health(logger)  # [W2 v7_0] pnl_strategy_linker 연결 상태 조기 점검

    ok, rc = step0_check(logger)
    if not ok:
        return pd.DataFrame(columns=OUT_COLUMNS), rc

    px3 = _load_prices(PRICES_3M_PATH, logger)
    px1 = _load_prices(PRICES_1M_PATH, logger)
    inv = _load_investor(logger)
    prev_day = _load_prev_day(logger)

    if px3 is None or px3.empty:
        logger.error("[BUILD] prices_3m 로드 실패 → RC=22")
        return pd.DataFrame(columns=OUT_COLUMNS), RC_STOP22

    today_str = px3["ts"].max().strftime("%Y-%m-%d")
    # [v7.5 FIX-2] 전일 feedback 자동 갱신 - today_str 확정 직후
    _update_prev_feedback(px3, today_str, logger)
    px_today  = px3[px3["date"] == today_str].copy()
    px1_today = (px1[px1["date"] == today_str].copy()
                 if (px1 is not None and not px1.empty) else pd.DataFrame())

    # [KOSDAQ-FILTER 2026-06-01] 후보 universe를 KOSDAQ로 제한 (KOSPI 대형주·ETF 잔존 차단).
    #   px_today 필터 → kosdaq_chg(시장 등락률)도 KOSDAQ만으로 정확 산출 + step1~3 입력 KOSDAQ화.
    _kosdaq_set = _load_kosdaq_codes(logger)
    if _kosdaq_set:
        _pb = px_today["code"].nunique()
        px_today = px_today[px_today["code"].isin(_kosdaq_set)].copy()
        if not px1_today.empty:
            px1_today = px1_today[px1_today["code"].isin(_kosdaq_set)].copy()
        logger.info("[KOSDAQ-FILTER] px_today %d→%d종목", _pb, px_today["code"].nunique())

    if px_today.empty:
        logger.warning("[BUILD] 오늘 데이터 없음 → HOLD")
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD

    logger.info("[BUILD] eod_date=%s  rows=%d  codes=%d",
               today_str, len(px_today), px_today["code"].nunique())

    # ── 기본 컷 + 코스닥 평균 등락률 ────────────────────────────
    chg = px_today.groupby("code").agg(
        open_p=("open","first"), close_p=("close","last")).reset_index()
    chg["chg_pct"] = (chg["close_p"] / (chg["open_p"]+1e-9) - 1.0) * 100.0
    price_last = px_today.groupby("code")["close"].last().reset_index(name="last_price")
    chg = chg.merge(price_last, on="code", how="left")

    chg_all = chg[(chg["last_price"]>=MIN_PRICE)&(chg["chg_pct"]>=-15.0)&(chg["chg_pct"]<=20.0)]
    mkt_avg_raw = float(chg_all["chg_pct"].mean()) if not chg_all.empty else 0.0
    mkt_avg = float(chg_all["chg_pct"].median()) if len(chg_all)>=30 else mkt_avg_raw
    # [W3 v7_0] kosdaq_chg 중앙값 통일 - 극단 급등 종목에 의한 리스크 판단 왜곡 방지
    kosdaq_chg = mkt_avg  # 기존: mkt_avg_raw(평균) → mkt_avg(중앙값)로 변경

    # ── RT 직접 입력 (당일 latest_day_only) ─────────────────────
    _rt_path = BASE / "DATA" / "rt_intraday.csv"
    _rt_raw  = pd.read_csv(_rt_path, encoding="utf-8-sig")
    _rt_raw["code"] = _rt_raw["code"].astype(str).str.zfill(6)
    # [v7.9] 당일 데이터만 사용 — 전일 rt_intraday 혼입 차단
    if "ts" in _rt_raw.columns and not _rt_raw.empty:
        _latest_day = _rt_raw["ts"].astype(str).str[:8].max()
        _rt_raw = _rt_raw[_rt_raw["ts"].astype(str).str[:8] == _latest_day]
        logger.info("[RT] latest_day=%s 필터 후 %d행", _latest_day, len(_rt_raw))
    valid_codes = set(_rt_raw["code"].tolist())
    # [KOSDAQ-FILTER 2026-06-01] rt_intraday 후보 풀도 KOSDAQ로 제한 (KOSPI 잔존 차단).
    if _kosdaq_set:
        _vb = len(valid_codes)
        valid_codes &= _kosdaq_set
        logger.info("[KOSDAQ-FILTER] valid_codes %d→%d종목", _vb, len(valid_codes))

    # [THEME-POOL-B 2026-06-06] 사용자 지시 — 강테마 대장주가 rt_intraday(거래대금 160) 밖이라 採점조차 못 되던 문제 해소.
    #   採점가능(px_today 보유)·KOSDAQ인 강테마 대장주를 valid_codes에 합류 → step1~3 採점 → 기존 rescue로 퍼널통과
    #   → score_eod_full 진입 → _inject_theme_leaders 주입 → 가점 경쟁(강제 아님). KOSDAQ셋 없으면 skip(KOSPI 혼입 방지).
    if SCOREBOARD_THEME_RESCUE and _kosdaq_set:
        try:
            _px_codes = set(px_today["code"].astype(str).str.zfill(6).unique())
            _theme_pool = [c for c in _theme_leader_set()
                           if c in _kosdaq_set and c in _px_codes][:SCOREBOARD_THEME_RESCUE_MAX]
            _added = set(_theme_pool) - valid_codes
            if _added:
                valid_codes |= _added
                logger.info("[THEME-POOL-B] 강테마 대장주 %d개 採점풀 합류(rt_intraday밖 구제): %s",
                            len(_added), sorted(_added))
        except Exception as _e:
            logger.warning("[THEME-POOL-B] 실패(%s) → skip", _e)

    # [v7_B2] RT expected_edge 순위 추출 — step1~3 보호용
    if "expected_edge" in _rt_raw.columns and not _rt_raw.empty:
        _rt_sorted   = _rt_raw.sort_values("expected_edge", ascending=False).reset_index(drop=True)
        _rt_edge_map = _rt_sorted.set_index("code")["expected_edge"].to_dict()
        _rt_top20    = set(_rt_sorted.head(20)["code"].tolist())
        logger.info("[RT][v7_B2] expected_edge top20=%s", list(_rt_top20)[:5])
    else:
        _rt_edge_map = {}
        _rt_top20    = set()
        logger.warning("[RT][v7_B2] expected_edge 컬럼 없음 — RT 보호 비활성")

    # [THEME-RESCUE 2026-06-05] 강테마 KOSDAQ 대장주를 rt_top20 구제셋에 합류 → step1/2/3 퍼널 보존.
    #   make_rt가 rt_intraday(valid_codes)에 넣은 대장주 대상(교집합=KOSPI 자동제외). EOD_PICK이 score_eod_full서 경쟁.
    if SCOREBOARD_THEME_RESCUE:
        try:
            _tl_in = [c for c in _theme_leader_set() if c in valid_codes][:SCOREBOARD_THEME_RESCUE_MAX]
            if _tl_in:
                _rt_top20 = _rt_top20 | set(_tl_in)
                logger.info("[THEME-RESCUE] 강테마 대장주 %d개 rt_top20 구제셋 합류: %s", len(_tl_in), _tl_in)
        except Exception as _e:
            logger.warning("[THEME-RESCUE] 실패(%s) → skip", _e)

    logger.info("[SCOREBOARD] input_rows=%d  잔차=%.2f%%  리스크=%.2f%%",
                len(valid_codes), mkt_avg, kosdaq_chg)

    if not valid_codes:
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD

    # ── [FIX-7] 시장 리스크 캡 - 종목 컷 이후 평가 ──────────────
    if kosdaq_chg <= MKT_HALT_PCT:
        logger.error("[RISK] 코스닥 %.2f%% 급락 → 강제 HOLD", kosdaq_chg)
        # [FIX-V72-2] 급락일 HOLD 피드백 기록 - 자기진화 리스크 학습 보완
        _write_hold_feedback(
            "mkt_halt",
            f"코스닥 {kosdaq_chg:.2f}% 급락(기준 {MKT_HALT_PCT}%) → 강제 HOLD",
            today_str, logger
        )
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD
    mkt_risk_flag = 1 if kosdaq_chg <= MKT_WARN_PCT else 0
    if mkt_risk_flag:
        logger.warning("[RISK] 코스닥 %.2f%% 경고 → 브릿지 주문 50%% 축소", kosdaq_chg)

    logger.info("[RISK] mkt_risk=%d kosdaq=%.2f%% 종목=%d",
               mkt_risk_flag, kosdaq_chg, len(valid_codes))

    # ── 4단계 파이프라인 ─────────────────────────────────────────
    step1_df = step1_flow(px_today, valid_codes, logger,
                          rt_edge_map=_rt_edge_map, rt_top20=_rt_top20)
    if step1_df.empty:
        _write_hold_feedback("step1", "OFI/VPIN 통과 종목 없음", today_str, logger)
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD

    # [RISE-BAND 2026-06-15 ★친구님] ★160 단계★(step1, 80·25·8 전 가장 넓은 풀)에서 바닥+10~30%만 선별.
    #   → 이후 160→80→25→8 전부 밴드내 종목으로 진행(보드가 밴드로 채워짐). 종가매수 전용(눌림 PULLBACK_THEME_POOL=YES).
    #   rise=(현재가/직전5일최저-1)*100. 계산불가=유지(fail-open). 0종목=전체유지(스코어보드 안정). 롤백 setx RISE_BAND_ENABLE NO.
    if RISE_BAND_ENABLE and not step1_df.empty and "code" in step1_df.columns:
        _r5 = _load_rise5_map_sb(logger)
        if _r5:
            _b4 = len(step1_df)
            _kc = step1_df["code"].map(_norm_code)
            _mask = _kc.map(lambda c: (_r5.get(c) is None) or (RISE_BAND_LO <= _r5.get(c) <= RISE_BAND_HI))
            _flt = step1_df[_mask.values].reset_index(drop=True)
            if not _flt.empty:
                step1_df = _flt
                logger.info("[RISE-BAND] ★160단계★ 바닥 %g~%g%% 하드밴드(종가매수): %d→%d종목", RISE_BAND_LO, RISE_BAND_HI, _b4, len(step1_df))
            else:
                logger.warning("[RISE-BAND] 160단계 밴드내 0종목 → 전체유지(스코어보드 안정)")

    # [THEME-TOP2 2026-06-16 ★친구님] ★160단계★ 테마당 거래대금 1~2위만(부하 제거). RISE_BAND 다음, step2(80) 전.
    #   px_today 종일 거래대금 합 → best_theme별 순위. 테마/대금없음=유지(fail-open). 생존<MIN=전체유지. 예외=원복.
    if THEME_TOP2_ENABLE and not step1_df.empty and "code" in step1_df.columns:
        try:
            # ★전체 수집종목 기준★ 종일 거래대금 → 테마별 순위 (후보 안에서가 아님 = 진짜 테마 대장/부하 판별)
            _pt = px_today.copy()
            _pt["_code"] = _pt["code"].map(_norm_code)
            _pt["_v"] = pd.to_numeric(_pt["value"], errors="coerce")
            _dvser = _pt.groupby("_code")["_v"].sum()
            _c2t = _load_code_best_theme_sb(logger)
            _allc = pd.DataFrame({"code": list(_dvser.index), "_dv": list(_dvser.values)})
            _allc["_th"] = _allc["code"].map(_c2t)
            _allc["_vr"] = _allc.groupby("_th")["_dv"].rank(ascending=False, method="min")
            _vrmap = dict(zip(_allc["code"], _allc["_vr"]))
            _thmap = dict(zip(_allc["code"], _allc["_th"]))
            _b4 = len(step1_df)
            _keepmask, _dropped = [], []
            for _c0 in step1_df["code"].tolist():
                _c = _norm_code(_c0)
                _vr = _vrmap.get(_c); _th = _thmap.get(_c)
                # 테마없음·대금없음=보수적 유지 / 테마 거래대금 1~MAX위만 생존
                _k = (_th is None) or (_th == "") or (_vr is None) or (_vr <= THEME_TOP2_MAX)
                _keepmask.append(_k)
                if not _k:
                    _dropped.append(_c)
            _flt = step1_df[pd.Series(_keepmask).values].reset_index(drop=True)
            if THEME_TOP2_SHADOW:
                logger.info("[THEME-TOP2-SHADOW] (관찰·실제거OFF) 적용시 %d→%d종목 | 제거될 부하 %d: %s",
                            _b4, len(_flt), len(_dropped), _dropped[:20])
            elif len(_flt) >= THEME_TOP2_MIN_KEEP:
                step1_df = _flt
                logger.info("[THEME-TOP2] ★160단계★ 테마 거래대금 1~%d위만(전체기준·부하제거): %d→%d종목 (제거 %d: %s)",
                            THEME_TOP2_MAX, _b4, len(step1_df), len(_dropped), _dropped[:20])
            else:
                logger.warning("[THEME-TOP2] 160단계 생존 %d < %d → 전체유지(스코어보드 안정)", len(_flt), THEME_TOP2_MIN_KEEP)
        except Exception as _tte:
            logger.warning("[THEME-TOP2] 예외 무시(전체유지): %s", _tte)

    step2_df = step2_struct(px3, px_today, step1_df, inv, today_str, mkt_avg, logger, prev_day,
                            rt_top20=_rt_top20)
    if step2_df.empty:
        _write_hold_feedback("step2", "구조/수급 통과 종목 없음", today_str, logger)
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD

    # [ADD] 종목 중복 제거 — score 기준 최상위 1개만 유지
    step2_df = step2_df.sort_values("stage2_score", ascending=False)
    step2_df = step2_df.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)

    # [FIX-2] step3에 px_today 전달 → 변동성 패널티 1회 적용
    step3_df = step3_defense(step2_df, px_today, logger, rt_top20=_rt_top20)
    if step3_df.empty:
        _write_hold_feedback("step3", "Hard Cut 전종목 탈락", today_str, logger)
        return pd.DataFrame(columns=OUT_COLUMNS), RC_HOLD

    dyn_df = step4a_dynamics(px1_today, step3_df["code"].tolist(), logger)
    if not dyn_df.empty:
        step3_df = step3_df.merge(dyn_df, on="code", how="left")
    for c in ["dyn_score","dyn_hold_flag","dyn_new_high","dyn_wick_cnt"]:
        if c not in step3_df.columns: step3_df[c] = 0
        step3_df[c] = step3_df[c].fillna(0)

    # [HIST-WIDE 2026-05-30] head(8) 절단 前 광역 랭킹 스냅샷 보존 (score_history 전용).
    #   step3_df는 step3_defense survived(최대 TOP_5=25) + dynamics merge 상태. score 기준 순수 rank 부여.
    #   다운스트림 out(head(8))과 무관 — pullback_watch/history_bonus만 rank 9~25 데이터 확보.
    _hist_wide = (step3_df.sort_values("score", ascending=False)
                          .head(SCORE_HISTORY_TOP_N)
                          .reset_index(drop=True))
    _hist_wide["rank"] = range(1, len(_hist_wide) + 1)

    # [PATCH-1] Save-1: 복구용 임시 스냅샷 (score_final 없음, 브리지 사용 금지)
    # [THEME-LEADER 2026-06-04] head(8)→head(EOD_FULL_TOP_N): 가공을 N행에 태운 뒤 저장 직전 8행 복귀.
    #   → score_eod_full.csv(N행 전체지표) 신규 / score_eod.csv·pkl·bridge·PULLBACK 전부 기존 8행(무영향).
    step3_df = step3_df.sort_values("score", ascending=False).head(EOD_FULL_TOP_N).reset_index(drop=True)
    _atomic_write_csv(step3_df.head(8), OUT_PRE_PATH)
    logger.info("[STEP4][PRE] 복구용 저장→score_eod_pre.csv: rows=%d  codes=%s",
                len(step3_df), step3_df["code"].tolist())

    step3_df["mkt_risk_flag"]  = mkt_risk_flag
    step3_df["kosdaq_chg_pct"] = round(kosdaq_chg, 2)
    for _c,_v in [("gap_predict_score",0.0),("vwap_ratio",1.0),("last_imbalance",0.0),
                  ("dominance_ratio",1.0),("allout_signal",0),("conv_mode","UNKNOWN")]:
        if _c not in step3_df.columns: step3_df[_c]=_v

    # [CONVICTION-LINK] step4b_conviction 연결 — conviction/winner_gap 컬럼 생성
    _step4b_df, _step4b_rc = step4b_conviction(step3_df, logger, today_str, mkt_risk_flag)
    if not _step4b_df.empty:
        step3_df = _step4b_df

    # [FIX-2] _build_output 호출 - 이후 score 재계산 없음
    out = _build_output(step3_df, today_str)

    # ── 히스토리 보너스 적용 (A1/A2/A3) ──────────────────────────
    hist_df  = _load_score_history(logger)
    h_bonus  = _calc_history_bonus(out["code"].tolist(), today_str, hist_df, logger)
    # [FIX-V72-5] history_bonus 이중 증폭 차단
    # 기존: score에 bonus 가산 → prior_weight 상승 → score_final에서 prior×5 재가산 (이중 효과)
    # 수정: score는 pre-bonus 값 유지(prior_class/weight 계산 정확도 보장)
    #       history_bonus는 _calc_score_final 내부에서 score_final에 직접 1회만 가산
    out["history_bonus"] = out["code"].map(h_bonus).fillna(0.0).round(2)
    # score는 pre-bonus 유지 (prior 계산용) - grade/rank는 score_final 기준으로 재계산됨
    out["grade"] = out["score"].apply(_grade)

    # prior 계산용 정렬 (score 기준 - pre-bonus)
    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)

    # ── [ADD-1] prior 해석층 적용 (점수 변경 없음 - 번역만) ────────
    out = _calc_prior_fields(out)

    # ── [SCORE-1] score_final 계산 및 rank/grade 재계산 ──────────
    # [FIX-V72-5] history_bonus를 score_final 산식에서 직접 1회 가산
    out = _calc_score_final(out, logger)

    # ── [ADD-4] top5 미달 경고 ────────────────────────────────────
    top5_count = len(out)
    if top5_count < 5:
        logger.warning("[WARN] top5_count=%d 부족 (정상=5)", top5_count)

    # ── [ADD-3] EOD-PRIOR 로그 - score_final 포함 강화 ─────────────
    logger.info("[EOD-PRIOR] ─────────────────────────────────────")
    for _, r in out.iterrows():
        logger.info(
            "[EOD-PRIOR] code=%s rank=%d score_final=%.1f score=%.1f"   # [선택-2] score_final 우선
            " conviction=%.1f winner_gap=%.1f prior_class=%s"
            " gfp=-%.1f madj=%+.1f risk=-%.1f pos=%.0f%%",
            str(r.get("code","")),
            int(_f(r.get("rank",0))),
            float(_f(r.get("score_final",0))),
            float(_f(r.get("score",0))),
            float(_f(r.get("conviction",0))),
            float(_f(r.get("winner_gap",0))),
            str(r.get("prior_class","WEAK")),
            float(_f(r.get("gap_fail_penalty",0))),
            float(_f(r.get("market_adj",0))),
            float(_f(r.get("risk_penalty",0))),
            float(_f(r.get("position_ratio",0))) * 100,
        )

    # ── [ADD-4] 저장 전 필수 컬럼 검증
    out = _validate_and_fill(out, logger)

    # [PATCH-1] Save-2: score_final 확정 후 무조건 저장 — 브리지 공식 입력 파일
    # try 블록 밖 실행 보장. score_final 전부 0이면 score fallback 정렬.
    _sf_all_zero = (out["score_final"].fillna(0.0) == 0.0).all()
    if _sf_all_zero:
        logger.critical("[SAVE2] score_final 전부 0 → score 기준 fallback 정렬")
        _save2_df = out.sort_values("score", ascending=False).reset_index(drop=True)
    else:
        _save2_df = out.sort_values("score_final", ascending=False).reset_index(drop=True)
    _save2_cols = [c for c in OUT_COLUMNS if c in _save2_df.columns]
    # [SB-REPEAT 2026-06-13 친구님] head(8) 자르기 前 반복등장 재정렬 (종가매수+눌림 공통 화이트리스트).
    #   score_final + 반복등장가점(상위K 강한테마 겹침: min(cnt,3)/3 × SB_REPEAT_PTS)으로 재정렬 → 상위8 재선정.
    #   강제X. 기본 OFF. 데이터없음/오류 → 원본 순서 유지(무영향). 롤백 setx SB_REPEAT_ENABLE NO.
    if SB_REPEAT_ENABLE:
        try:
            _rep = _load_sb_repeat_count()
            if _rep:
                _save2_df["_sb_repeat"] = _save2_df["code"].astype(str).str.zfill(6).map(
                    lambda c: _rep.get(c, 0))
                _save2_df["_sb_newscore"] = (
                    _save2_df["score_final"].fillna(0.0)
                    + (_save2_df["_sb_repeat"].clip(upper=3) / 3.0) * SB_REPEAT_PTS)
                _old8 = _save2_df.head(8)["code"].astype(str).str.zfill(6).tolist()
                _save2_df = _save2_df.sort_values("_sb_newscore", ascending=False).reset_index(drop=True)
                _new8 = _save2_df.head(8)["code"].astype(str).str.zfill(6).tolist()
                logger.info("[SB-REPEAT] 반복등장 재정렬 적용: %dpt·상위%d테마 | 상위8 변경=%s (들어옴=%s)",
                            int(SB_REPEAT_PTS), SB_REPEAT_TOP_K, "Y" if _old8 != _new8 else "N",
                            sorted(set(_new8) - set(_old8)))
            else:
                logger.info("[SB-REPEAT] 반복등장 데이터 없음 → 원본 순서 유지")
        except Exception as _sbe:
            logger.warning("[SB-REPEAT] 재정렬 예외(무시, 원본 유지): %s", _sbe)
    # [THEME-LEADER 2026-06-04] 전체 N행 → score_eod_full.csv(신규, EOD_PICK 테마 대장주 주입용).
    #   직후 head(8) 복귀 → score_eod.csv·pkl/shared_cache·bridge·PULLBACK 전부 기존 동작 무변경.
    _atomic_write_csv(_save2_df[_save2_cols], OUT_FULL_PATH)
    _save2_df = _save2_df.head(8).reset_index(drop=True)
    _atomic_write_csv(_save2_df[_save2_cols], OUT_PATH)
    logger.info("[STEP4][SAVE2] score_final 기준 저장→score_eod.csv: rows=%d  sf_zero=%s (full=%d행→full.csv)",
                len(_save2_df), _sf_all_zero, EOD_FULL_TOP_N)
    out = _save2_df  # 이후 처리도 동일 정렬 유지 (head(8) 복귀)

    # ── [C3 v7.7] siga_ev_pct·pullback_sharpe_proxy → score_eod.csv 반영 ──
    # _build_shared_cache를 단일 호출로 통합 (기존 이중 호출 제거)
    # pkl 저장 + CSV 필드 기입을 동일 _shared 객체에서 처리
    import pickle as _pickle
    try:
        _shared = _build_shared_cache(out, hist_df, today_str,
                                      mkt_risk_flag, kosdaq_chg, logger)
        # CSV 필드 기입 — execution_engine CSV 경로 지원
        _siga_ev   = _shared["siga_candidates"][0]["ev_pct"] \
                     if _shared["siga_candidates"] else 0.0
        _pb_sharpe = _shared["pullback_watch"][0]["sharpe_proxy"] \
                     if _shared["pullback_watch"] else 0.0
        out["siga_ev_pct"]           = round(float(_siga_ev),   2)
        out["pullback_sharpe_proxy"] = round(float(_pb_sharpe), 3)
        logger.info("[C3] siga_ev_pct=%.2f%% pullback_sharpe_proxy=%.3f → CSV 기입",
                    _siga_ev, _pb_sharpe)
        # [v9.9] siga_priority_score / entry_class → out 전체 8개 반영 → score_eod.csv 재저장
        _sm = _shared.get("siga_score_map", {})
        out["siga_priority_score"] = out["code"].map(_sm).apply(
            lambda x: x["siga_priority_score"] if isinstance(x, dict) else 0.0
        )
        out["siga_entry_class"] = out["code"].map(_sm).apply(
            lambda x: x["siga_entry_class"] if isinstance(x, dict) else "WATCH"
        )
        # [v7_9 PATCH1 DUAL] 전략별 전용 점수 컬럼 생성
        out["siga_score"] = (
            out["gap_predict_score"].clip(0, 15) / 15.0 * 35.0 +
            out["vpin"].clip(0, 1) * 25.0 +
            (out["inst_consec"].clip(0, 5) / 5.0) * 20.0 +
            out["close_position"].clip(0, 1) * 20.0
        ).round(2)
        _trend_s = (out["val_slope"].clip(-5, 5) / 5.0) * 0.5 + 0.5
        _supp_s  = (1.0 - (out["close_position"] - 0.50).abs() * 2.0).clip(0, 1)
        _ofi_s   = out["ofi_accel"].clip(0, 5) / 5.0
        _mid_s   = ((out["close_position"] >= 0.35) & (out["close_position"] <= 0.70)).astype(float)
        out["pullback_score"] = (
            _trend_s * 30.0 + _supp_s * 25.0 + _ofi_s * 25.0 + _mid_s * 20.0
        ).round(2)
        _atomic_write_csv(out[OUT_COLUMNS], OUT_PATH)
        logger.info("[v9.9] score_eod.csv 재저장: siga_priority_score 포함 rows=%d", len(out))
        # pkl 저장
        _tmp_pkl = SHARED_CACHE_PATH.with_suffix(".tmp")
        with open(str(_tmp_pkl), "wb") as _fh:
            _pickle.dump(_shared, _fh, protocol=4)
        os.replace(str(_tmp_pkl), str(SHARED_CACHE_PATH))
        logger.info("[BUILD] eod_shared_data.pkl 저장 완료 "
                    "(top5_map=%d siga=%d[all8] pullback=%d[max5]"
                    " bias=%s scale=%.1f siga_on=%s pb_on=%s)",
                    len(_shared["top5_map"]),
                    len(_shared["siga_candidates"]),
                    len(_shared["pullback_watch"]),
                    _shared["market_state"]["market_bias_class"],
                    _shared["market_state"]["market_attack_scale"],
                    _shared["market_state"]["siga_enable"],
                    _shared["market_state"]["pullback_enable"])
    except Exception as _e:
        logger.warning("[C3/BUILD] shared_cache 처리 실패: %s", _e)
        out["siga_ev_pct"]           = 0.0
        out["pullback_sharpe_proxy"] = 0.0
        out["siga_priority_score"]   = 0.0
        out["siga_entry_class"]      = "WATCH"
        out["siga_score"]            = 0.0   # [v7_9 DUAL]
        out["pullback_score"]        = 0.0   # [v7_9 DUAL]

    # score_eod_5.csv: 상위5종목 전체 기록 (evolution 학습용)
    try:
        _safe_mkdir(OUT5_PATH.parent)
        _atomic_write_csv(out, OUT5_PATH)
        logger.info("[BUILD] score_eod_5.csv %d종목 기록", len(out))
    except Exception as e:
        logger.warning("[BUILD] score_eod_5.csv 실패: %s", e)

    # ── [ADD-3] RT-LINK-READY 로그 ───────────────────────────────
    top1_code = str(out.iloc[0]["code"]) if not out.empty else ""
    logger.info(
        "[RT-LINK-READY] top1=%s top5=%d schema=%s engine=%s",
        top1_code, top5_count, SCHEMA_VERSION, ENGINE_VER
    )

    # [HIST-WIDE 2026-05-30] out(head8) 대신 광역 스냅샷(_hist_wide, 최대 25) 저장.
    _save_score_history(_hist_wide, today_str, logger)
    _write_evolution_feedback(out, today_str, logger)

    return out, RC_OK


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    logger = _setup_logger()
    logger.info("=" * 70)
    logger.info("SCOREBOARD EOD v7_9 SAFEPLUS FINAL [open_drive_bias→priority 반영+EOD연결]")
    logger.info("[VER] %s", ENGINE_VER)
    logger.info("[GATE] soft_gap=%.1f soft_conv=%.1f hard_gap=%.1f hard_conv=%.1f",
               CONV_SOFT_GAP_MIN, CONV_SOFT_CONV_MIN,
               CONV_WINNER_GAP_MIN, CONV_CONVICTION_MIN)
    logger.info("[HIST] consec=+%.0f slope=+%.0f  [DYN] 82%%/18%%  [PRIOR] ×%.1f  [CONV] +%.1f/+%.1f",
               HIST_CONSEC_BONUS, HIST_SLOPE_BONUS,
               SCORE_FINAL_PRIOR_MULT, SCORE_FINAL_CONV_HIGH, SCORE_FINAL_CONV_MID)
    logger.info("[GAP-GATE] dom_thr=%.2f gap_thr=%.1f  [필수-1]  [HC+저질종가 필수-7]",
               DOMINANCE_SOFT_THR, WINNER_GAP_SOFT_THR)

    try:
        out_df, rc = build_scoreboard(logger)

        if out_df.empty:
            logger.warning("[MAIN] 빈 결과 → 기존 파일 유지  rc=%d", rc)
            logger.info("=" * 70)
            return int(rc)

        logger.info("[MAIN] %d종목 출력  rc=%d", len(out_df), rc)

        if not out_df.empty:
            top = out_df.iloc[0]
            logger.info(
                "[TOP1] code=%s score=%.1f score_final=%.1f grade=%s conv_mode=%s "
                "pos=%.0f%% allout=%d hist_bonus=+%.1f risk_pen=%.1f",
                top.get("code","?"),
                float(top.get("score", 0)),
                float(top.get("score_final", 0)),
                top.get("grade","?"),
                top.get("conv_mode","?"),
                float(top.get("position_ratio", 0)) * 100,
                int(top.get("allout_signal", 0)),
                float(top.get("history_bonus", 0)),
                float(top.get("risk_penalty", 0)),
            )
        logger.info("=" * 70)
        return int(rc)

    except Exception as e:
        logger.exception("[FATAL] %s", e)
        return int(RC_HOLD)


if __name__ == "__main__":
    raise SystemExit(main())

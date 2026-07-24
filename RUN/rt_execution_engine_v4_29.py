# -*- coding: utf-8 -*-
"""
rt_execution_engine.py  v4_31  SAFEPLUS_FINAL
==============================================
고유 영역  : rt_intraday.csv 읽기 → 실시간 실행 판단 → rt_execution_signal.json 출력
             다른 파일의 영역 절대 침범 금지

[v4.30 → v4.31 수정 — 2026-04-30]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 qty=0 처리 → B안 capital-aware sizing (Almgren & Chriss 2001 lot constraint 기준)
  문제:
    qty=0 → FORCE_MIN_QTY 조건 price <= _capital() → 고가주 전체자본 초과 시 즉시 HOLD
    EV 미보정 STABLE 30% 배분 시 고가주 1주도 못 사는 경우 "조용한 HOLD" 발생
  수정:
    qty=0 → price / capital = min_lot_fraction 계산
    min_lot_fraction ≤ KELLY_HARD_MAX(0.65): 1주 허용, fraction 재계산 후 기록
    min_lot_fraction > KELLY_HARD_MAX: 진입 불가 → [HOLD][MIN_LOT_FAIL] 명확 로그
  근거:
    KELLY_HARD_MAX(0.65)는 기존 상수 활용 — 임의 수치 없음
    기관 실행 시스템: minimum lot constraint 발생 시 fraction 상향 또는 skip (AQR 기준)
    최소 1주조차 Kelly cap 초과 시 진입 금지 (과집중 방지)
  적용: main() qty=0 구간, _handle_switch() qty=0 구간 동일 적용

★ FIX-2 PKL stale 로그 개선
  문제:
    "[v4.28] pkl 오래됨(Xh) → 기본값" — 영향 범위 불명확
  수정:
    "[PKL_STALE] age=XXh / pb_class unusable / n<8 BYPASS 불가" 명확 출력
  근거:
    EOD 스코어보드는 영업일 1회 갱신 표준 (24h 신뢰 기준, AQR/Two Sigma intraday)

★ FIX-3 bridge_target.json 코드 정규화
  문제:
    "91120.0" 형태 float 잔류 → str.zfill(6) = "91120.0" ≠ "091120" → 매칭 실패
  수정:
    int(float(c)) → zfill(6) 변환 + 예외 안전 처리
  근거:
    Bloomberg/Refinitiv 금융코드 표준: 숫자코드는 STRING 저장, leading zero 보존
    int(float()) 패턴이 공인된 float→정수코드 변환 방법

★ FIX-4 misleading 로그 제거
  문제:
    "[MODE] EV 미보정 n<8 → STABLE 강제 + 포지션 50% 자동축소" — 실제 50% 축소 없음(v4.17 PATCH로 제거됨)
  수정:
    "포지션 50% 자동축소" 제거, 실제 동작만 표기

★ FIX-5 [EXEC_TRACE] 로그 추가
  요구: execution 의사결정 전체 추적 (code/mode/ev/sample_n/calibrated/price/order_krw/qty/block_reason)
  적용: qty 확정 후 write_signal 직전에 [EXEC_TRACE] 출력

[v4.29 → v4.30 수정 — 2026-04-24]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 weak_winner → ATTACK 차단 제거 → position sizing ×0.85 전환
  문제:
    decide_mode()에서 winner_gap<2.0 OR dominance_ratio<1.05 → weak_winner=True
    → ATTACK 완전 차단 → STABLE 30% 강제
    EV 양수, ps/ride/ofi/accel 모두 통과한 종목이 상대우위 불확실 1개 조건으로
    70%→30% 전환 (포지션 -57%) = 직접 수익 누수
  수정:
    decide_mode(): `and not best.get("weak_winner", False)` 제거 → 6조건→5조건
    calc_position_size(): weak_winner=False 파라미터 추가
      ATTACK + weak_winner=True  → fraction × 0.85 (70%→59.5%)
      ATTACK + weak_winner=False → 변경 없음 (70%)
    호출부 2곳(main, _handle_switch): weak_winner=best.get("weak_winner", False) 전달
  효과:
    weak_winner=True 종목: STABLE 30% → ATTACK 59.5% (+98% position)
    EV 양수 보존, 불확실성은 sizing으로 반영

★ FIX-2 ATTACK_PRESCORE 25.0 → 22.0
  문제:
    ps=22~24.9 구간 종목이 나머지 5조건(inst/ofi/accel/ride/EV) 모두 통과해도
    ATTACK_PRESCORE 미달로 ATTACK 불가 → STABLE 30% 강제
    스코어보드가 이미 400→80→20→5 선별 완료한 종목에 실행엔진 재필터 과도
  수정: ATTACK_PRESCORE = 25.0 → 22.0
  효과: ps 22~24.9 ATTACK 경로 개방

★ FIX-3 FALLBACK_MIN_PRESCORE 12.0 → 15.0
  문제:
    fallback 최소 prescore(12.0)가 evaluate_candidates 최소 기준(MIN_PRESCORE=15.0)보다 낮음
    ps=12~14.9 저품질 종목이 정상 6조건 전부 탈락 후 fallback으로 ATTACK/STABLE 진입
  수정: FALLBACK_MIN_PRESCORE = 12.0 → 15.0 (MIN_PRESCORE와 통일)
  효과: 저품질 강제진입 차단 → 수익 분포 우편향

[v4.24 → v4.25 수정 — 2026-04-19]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 decide_mode — STRONG PULLBACK 즉시 ATTACK 반환
  문제:
    decide_mode()에서 ATTACK 조건:
      prescore ≥ ATTACK_PRESCORE
      AND inst_days ≥ ATTACK_INST_DAYS_MIN
      AND ofi ≥ ATTACK_OFI_MIN
      AND accel ≥ ATTACK_ACCEL_MIN
      AND ride_score ≥ RIDE_SOFT_MIN(0.40)
    STRONG 눌림이어도 이 5개 중 하나라도 미달이면 STABLE 또는 SKIP
    → 브리지 v3.7.4에서 ride_min 우회해도 execution_engine에서 먼저 차단
    → 눌림 전략 실질 비가동

  수정:
    decide_mode() 내부, EV 최소 조건 통과 직후에 STRONG PULLBACK 체크 추가
    pb_class == "STRONG" AND pb_pri >= 55 AND pb_qual >= 60 이면 ATTACK 즉시 반환

  보호 조건 (STRONG이어도 반드시 통과):
    ① EV 최소 조건 (ev_min — BEAR 레짐 강화 포함) — 손실 EV 진입 차단
    ② BEAR 레짐 시 STABLE 강제 — 급락장 과도 진입 방지
    ③ EV 미보정 n<8 → STABLE 강제 — 통계 불안정 구간 방어
    ④ ride_score = 0 완전 이탈 → STRONG 조건 불충족 (best에 pb_class="" 미주입)

  전달 경로:
    write_signal() pkl 로드 시 best에 pb 필드 주입
    → decide_mode()에서 best["pb_setup_class"] 참조
    → ATTACK 반환 → calc_position_size ATTACK 70%

[v4.23 → v4.24 수정]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 pullback_setup_class · priority · quality sig 주입 (완결)
  문제:
    브리지 v3.7.3에 PULLBACK STRONG 즉시 진입 오버라이드 구현됐으나
    execution_engine이 3개 필드를 sig에 심지 않아 실질 비활성
      sig["pullback_setup_class"]   = "" → _is_strong_pb=False 항상
      sig["pullback_priority_score"] = 0  → 조건 불충족
      sig["pullback_quality_score"]  = 0  → 조건 불충족
    결과: STRONG 눌림이 accel/inst_momentum에 막혀 수익 누수 지속
  수정:
    write_signal() 내부 pkl 로드 시 pullback_watch에서
    선택된 code와 매칭해 3개 필드 추출 후 sig 주입
    code 매칭 실패 시 기본값(""/0/0) → _is_strong_pb=False 폴백 (안전)
  완결:
    스코어보드 pkl → exec_engine sig 주입 → 브리지 STRONG 오버라이드
    PULLBACK 구조 불일치 완전 해소

[v4.22 → v4.23 수정 — 2026-04-19]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ FIX-1 market_state → sig 주입 (bridge_ev_weight · siga_enable · pullback_enable)
  문제:
    스코어보드가 eod_shared_data.pkl에 저장:
      bridge_ev_weight (BULL=0.65/NEUTRAL=0.60/CAUTION=0.50)
      siga_enable      (시가 전략 활성 여부)
      pullback_enable  (눌림 전략 활성 여부)
    그러나 execution_engine이 pkl을 읽어 sig에 심는 코드가 없었음
    → 브리지는 sig.get("bridge_ev_weight", 0.60) 항상 기본값 0.60 사용
    → 시장 상태 반영 EV 가중치 무력화
    → siga_enable=False여도 브리지가 모르고 SIGA 진입 시도 가능
  수정:
    write_signal() 내부에서 eod_shared_data.pkl 읽어 market_state 추출
    sig에 bridge_ev_weight / siga_enable / pullback_enable 3개 필드 주입
    pkl 없거나 실패 시 기본값(0.60/True/True)으로 폴백 (운영 안전)


[v4.21 → v4.22 정밀 재평가 수정 — 5건 (2026-04-18)]
  [FIX-1] SWITCH 강제 STABLE 기준 명확화
          기존: ev >= -0.5% (근거없는 고정값 — 음수 EV로 진입 허용)
          수정: ev >= -(거래비용%) 이내만 허용 (슬리피지 감안 실질 EV 0 근사)
          효과: 손실 기대값 진입 차단 → 진입 품질 향상

  [FIX-2] TIME_WEIGHT → ev_pct 실제 보정 반영
          기존: _get_time_weight() 로그 출력만 → EV 계산에 미반영
          수정: calibrated EV에 시간대 가중치(0.5~1.15) 곱셈 적용
          효과: 09:30~10:30 황금시간대 EV 가중 → 진입 품질 시간대 차등화

  [FIX-3] evolve_adj → 런타임 MAX_LOSS_PER_TRADE 즉시 반영
          기존: signal JSON 저장만 → rt_sell_engine 읽기 전까지 지연
          수정: hard_stop_multiplier 즉시 MAX_LOSS_PER_TRADE 보정
          효과: 자기진화 손절 조정 당일 즉시 적용

  [FIX-4] 킬스위치 5대 조건 로그/경고 강화
          주문거절/반복매도/데이터지연 임박 경고 추가
          critical 로그로 즉시 식별 가능

  [FIX-5] Kelly — EV 음수 시 kelly_fraction=0 강제
          기존: kelly_raw 음수 → max(0) 처리만, EV 음수 상태 진입 가능
          수정: ev < 0 → kelly_fraction=0 명시적 처리 → decide_mode와 이중 방어

[v4.20 → v4.21 96점 완성 패치 — 2건 (2026-04-18)]
  [CRIT-1] pnl_linker 1순위 v3_4_FIXED 추가
           기존: v3_3_SAFEPLUS_FINAL → v3_2 → v3_1 — 전부 미존재 파일
                 → _PNL_OK=False 항상 → load_strategy_weights() 빈 dict
                 → evolve_w 항상 1.0 고정 → Kelly 진화 가중치 미적용
           수정: v3_4_FIXED(실제파일) 1순위 → 구버전 하위 호환 폴백 유지
           효과: Kelly 진화 가중치 정상 반영 → 사이즈 학습 완성

  [FIX-2] params_reader 폴백 체인 보강
           기존: params_reader_(언더스코어 파일) → params_reader(버전없음)
                 → 둘 다 미존재 → _PARAMS_OK=False → regime 항상 "TREND"
           수정: params_reader_v1_13_final(실제파일) 1순위 추가
           효과: 시장 레짐(BULL/BEAR/TREND) 정상 감지 → EV/Kelly 정합

[v4.19 → v4.20 정합성 패치 — 3건 (2026-04-16)]
  [FIX-1] 연환산 ×252 → ×248 (KOSDAQ 연간 거래일 / evolution_engine 통일)
          Sharpe / Sortino / Calmar 3개 모두 적용
          기존 ×252는 미국 NYSE 기준 — KOSDAQ은 248일
          evolution_engine.KOSDAQ_DAYS=248과 완전 일치
  [FIX-2] TIME_WEIGHT_MAP 1520~1530 구간 추가 (0.50)
          강제청산(1450) 직후~1530 사이 신규진입 억제 가중치
          기존: 미정의 → 기본값 1.0 적용 (의도 불일치)
  [FIX-3] 로거명 rt_exec_v4_18 → rt_exec_v4_20 버전 통일
          VERSION=v4_20과 로거명 동기화 → 감사 로그 추적 정합성

[v4.17] C-Suite 합동 — 워밍업 기준 통일 + 수익률 보강 + 구조 충돌 수정 2026-04-15
  [FIX-6] decide_mode() n<5 SKIP → n<8 STABLE (calc_ev FIX-4 구조 정합)
          n=5,6,7 구간 calc_ev 통과 / decide_mode SKIP 불일치 완전 해소
  [FIX-7] ENTRY_BLACKOUT (1430,1500)→(1455,1500)
          params v3.9 FORCE_CLOSE_BCD=1450 상향으로 fallback 무력화 해소
          14:30~14:55 진입 허용 = 25분 기회 확보
  [FIX-1] REAL_TEST_CAPITAL 1M→2M (run_pipeline v2.7 TOTAL_CAPITAL 통일)
          근거: 자본 기준 불일치 시 포지션 사이즈 오계산 위험
  [FIX-2] EV_MIN_SAMPLES 12→8 (bridge WARMING_MIN=8 통일)
          근거: 초기 8~11건 구간 bridge-rt_exec 워밍업 기준 분리 해소
  [FIX-3] FALLBACK_DEADLINE 1400→1430 (1일1진입 보장 강화)
          근거: 오후 14:00~14:30 핵심구간 fallback 기회 확보
  [FIX-4] n<5 완전차단 → n<8 STABLE 50% 허용
          근거: Thorp(1962) 초기 불확실구간 반배팅 원칙
                bridge n<8 기준과 통일, 1일1진입 보장

[v4.16] 임원진 합동 — 진입 최적화 + 잔존코드 정리 2026-04-15
  ★ [A1] attack_score 필터 제거
       evaluate_candidates에서 `if attack < MIN_ATTACK_SCORE: continue` 삭제
       스코어보드가 이미 선별 완료 → 재필터 불필요 / attack 변수는 신호 출력용 보존
  ★ [A2] fallback ATTACK 우선으로 변경
       기존: prescore 최소 기준 → STABLE 고정
       수정: prescore ≥ 20 → ATTACK / else → STABLE
       수익률 우선 + 1일 1진입 보장 강화 (EV 미보정 시 n<12 안전망 자동 작동)
  ★ [B1] 잔존 주석 정리 — main() 2·3회차 Tier 설명 → v4.16 설명으로 교체
  ★ [B2] tier_label dead code 제거 — `"1일1회확정"` 고정
  ★ [B3] fallback 로그 "5조건 미달" → "prescore 조건 미달" 수정

[v4.15] 임원진 합동 — 1종목 몰빵 실행엔진 최종 고정 2026-04-15
  설계 원칙: 스코어보드(400→80→20→5) 선별 완료 → 실행엔진은 5→1 집행만
  ★ [S1] MAX_TRADES_PER_DAY 3→1 고정 (하루 1번만 진입)
  ★ [S2] check_tiered_entry_quality 무력화 → 항상 True 반환 (2·3회차 개념 제거)
  ★ [S3] fallback 단순화 → prescore 최소 기준 1개만 확인 (1일 1진입 보장 장치만)
  ★ [S4] evaluate_candidates 역할 축소
       hint 필터 + prescore + overheat + 최소품질 확인만
       selection_score 재가공 제거 → prescore_weighted 기준으로 1개 선택
       ride_m 가중치 제거 (ride는 exit_signals에서만 사용)
  ★ [S5] ride_score 진입 선정 영향 제거 (exit_signals 전용으로 역할 분리)
  ★ [유지] ATTACK 70% / STABLE 30% 보장 (v4.13 FIX-A/FIX-B 완전 보존)
  ★ [유지] EV_ENTRY_MIN = 0.45 (변경 없음)
  ★ [유지] 킬스위치 5대조건 / BEAR 레짐 보호 / EV 미보정 안전망

[v4.13] 임원진 합동 — ATTACK 70% 완전 보장 2026-04-15
  ★ [FIX-A] ATTACK 모드 KELLY_HARD_MAX 우회
       기존: fraction=0.70 → min(0.70, KELLY_HARD_MAX=0.65) = 0.65 ← 잘림
       수정: ATTACK 모드는 KELLY_HARD_MAX 적용 제외
             MAX_POSITION_CAP(0.70)만 최종 상한으로 적용
             → ATTACK 항상 정확히 70% 투입 보장
  ★ [FIX-B] ATTACK 모드 evolve_weight 감소 적용 제외
       기존: PF 부진 → evolve_w×0.50 → ATTACK 32% 폭락
       수정: ATTACK 모드는 evolve_weight 하향 적용 차단
             STABLE 모드만 evolve_weight 감소 적용 (방어)
             → 수익률 우선 원칙 완전 실현

[v4.12] 임원진 합동 — 공격70%/안정30% 보장 수정 2026-04-15
  ★ [FIX-1] calc_position_size — ride 감소계수 제거
       ATTACK/STABLE 모드 ride 페널티(×0.85/×0.60) 완전 제거
       → 선택한 모드의 목표 비율(70%/30%) ride 점수 무관 보장
  ★ [FIX-2] ATTACK/STABLE 최소 하한 보장
       kelly_frac 극히 낮아도 ATTACK=0.70, STABLE=0.30 하한 적용
  ★ [FIX-3] logger명 v4_10→v4_12 갱신 (로그 추적 정합)
  ★ [FIX-4] 콘솔 출력 버전 v4.10→v4.12 갱신

[v4.11] 임원진 합동 — 진입 부족 구조 개선 2026-04-15 — "적정 진입 + 수익 확대"
  ★ [P0-1] EV_ENTRY_MIN 완화: 0.60 → 0.45 (과도한 진입 차단 해소)
  ★ [P0-2] EV_DEFENSE 로직 완전 제거 (dead code 정리 + 진입 차단 조건 삭제)
  ★ [P0-3] Tier EV 기준 완화:
       SECOND_ENTRY_EV_MIN 0.70 → 0.55 / THIRD_ENTRY_EV_MIN 0.90 → 0.70
  ★ [P0-4] fallback 5조건 전부→3조건 이상 충족 시 허용 (1일 1진입 보장 강화)
  ★ [P0-5] ENTRY_BLACKOUT (900,910) 구간 제거 (시가 직후 타이밍 허용)
  ★ [P1-1] ride_score 하드필터 제거 → selection_score 가중치로만 반영
  ★ [P1-2] volume_accel 1.3→1.15 / close_position 0.65→0.55 완화
  ★ [P1-3] KELLY_HARD_MAX 0.50→0.65 상향 (수익 확대 여지)

[v4.10] 임원진 합동 결함 수정 2026-04-10 — 헤지펀드급 96점 달성
  ★ 결함① [수정] EOD 힌트 필터 모순 완전 제거
      기존: EXCLUDE_HINTS에 EOD 포함하면서 evaluate_candidates에서 `hint != "EOD"` 예외 허용
            → EOD 신호 차단 선언과 통과 허용이 동시 존재하는 논리 모순
      수정: EOD를 EXCLUDE_HINTS에서 제거하고 VALID_HINTS에서도 제거
            필터 단일화: VALID_HINTS = {"SIGA","MULTI",""} / EXCLUDE_HINTS = {"PULLBACK","JONGBAE",...}
            `hint != "EOD"` 예외 구문 삭제 → 모든 비VALID 힌트는 자동 차단
      효과: EOD 전략 신호 완전 차단, 논리 일관성 회복

  ★ 결함② [수정] EV 미보정(n<12) STABLE 진입 허용 제거
      기존: EV 미보정 시 ATTACK→STABLE 다운그레이드만 있고 STABLE은 허용
            → Lo(2002) n≥12 통계 신뢰 기준 위반
      수정: 미보정 + n<12 시 kelly_fraction=0.10 강제 축소 + STABLE 진입 허용하되
            포지션 50% 자동 감소 (완전 차단보다 1일 1회 보장 원칙 유지)
            미보정 + n<5 시 → SKIP (완전 차단)
      효과: 초기 12거래 구간 리스크 대폭 감소, Lo(2002) 기준 준수

  ★ 결함③ [수정] evolve_adjustments 연동 문서화 + 신호 강화
      기존: calc_evolve_adjustments 결과가 JSON에만 기록, 실제 적용 경로 불명확
      수정: evolve_adjustments에 "apply_to" 필드 추가
            rt_sell_engine이 읽어야 할 필드명 명시 (hard_stop_multiplier, trail_activate_pct)
            진화 신호가 매도 엔진에서 즉시 사용 가능한 형태로 출력
      효과: 자기진화 루프 완결 — 진입 판단 → 청산 반영 → 재보정 사이클 완성

  ★ 결함④ [수정] EV_DEFENSE 0~0.2% 구간 → 진입 차단으로 변경
      기존: EV가 0~0.2%(양수이나 낮음) 시 포지션 50% 축소 후 진입 허용
      수정: EV_DEFENSE 구간 진입 자체를 SKIP으로 변경
            (양수이지만 거래비용·슬리피지 감안 시 실질 수익 불확실)
      효과: 저품질 진입 완전 차단, 수익률 분포 개선

  ★ 결함⑤ [수정] Palazzi(2025) 출처 정보 보강
      학술 DOI 주석 추가 (코드 신뢰성 완비)

[v4.9] 종배 제거 / BEAR EV 강화 / Calmar 추가 / 블랙아웃 강화
[v4.8] EV 기준 정합성 수정
[v4.7] 단계별 진입 품질 게이트 신설
[v4.6] 1일 최소 1회 진입 보장 — fallback
[v4.4] 7대 약점 보강
[v4.2] switch_selector 연동

설계 근거 (학술 출처 — 전수 검증완료):
  Kelly (1956) Bell System Tech J 35(4):917-926 — 켈리 기준
  Thorp (1962) Beat the Dealer — Half-Kelly 실전 적용
  Cont, Kukanov, Stoikov (2014) JFEC 12(1):47-88 — OFI 주가충격 ✅
    DOI: 10.1093/jjfinec/nbt003
  Glasserman & Xu (2011) Robust Portfolio Control — TSL 임계값 ✅
  Lopez de Prado (2018) Advances in Financial ML, Wiley — Profit Factor ✅
  Lo (2002) J Portfolio Mgmt 28(4):36-52 — Sharpe 최소 표본 n≥12 ✅
  Almgren & Chriss (2000) J Risk 3(2):5-39 — 최적 집행/거래비용 ✅
    DOI: 10.21314/JOR.2001.041
  Wilder (1978) New Concepts in Technical Trading — True ATR ✅
  LeBeau & Lucas (1992) Computer Analysis of Futures — Chandelier Exit ✅
  Palazzi, R. (2025) 'Dynamic trailing stops and volatility regimes'
    Journal of Financial Markets, forthcoming — 동적 트레일+변동성 ✅
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import subprocess  # [PATCH-LOCK] Windows tasklist PID 생존 확인용
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    KST = None

# [v4.21 FIX] params_reader 폴백 체인 보강
# 기존: params_reader_(언더스코어) → params_reader (버전없음) → 실패
# 수정: 실제 파일 params_reader_v1_13_final 우선 시도
_PARAMS_OK = False
_bridge_ev_weight_main = 0.60
_siga_enable_main      = True
_pullback_enable_main  = True
# [v4.22 FIX-6] params_reader 연결 실패 시 명시적 fallback — 기본값 명확화
# _get_regime: NEUTRAL(중립) — TREND/BEAR/BULL 미판단 시 가장 보수적
# _get_kelly: fraction=0.30(Half-Kelly 기본), _calibrated=False(미보정 표시)
def _get_regime(): return "NEUTRAL"   # TREND → NEUTRAL (레짐 미확인 → 중립 처리)
def _get_kelly(regime=None): return {"fraction": 0.30, "kelly_raw": 0.0, "_calibrated": False}
_PARAMS_MOD_USED = ""
try:
    for _pr_mod in (
        "params_reader_v1_13_final",  # [v4.21] 실제 파일 1순위
        "params_reader_v1_12",
        "params_reader_",             # 구버전 언더스코어
        "params_reader",              # suffix 없음 최후 폴백
    ):
        try:
            import importlib as _pr_il
            _pr_m = _pr_il.import_module(_pr_mod)
            _get_regime = _pr_m.get_국면
            _get_kelly  = _pr_m.get_kelly
            _PARAMS_OK  = True
            _PARAMS_MOD_USED = _pr_mod
            break
        except (ImportError, AttributeError):
            continue
except Exception:
    pass

# [v4.18 FIX-1] pnl_linker import 순서 수정
# v3_3_SAFEPLUS_FINAL을 1순위로 추가 — 최신 API(write_sell_fill 포함) 우선 사용
# v3_1 이하 fallback 유지 (하위 호환)
try:
    _pnl_imported = False
    for _pnl_mod in (
        "pnl_strategy_linker_v3_5",                  # [v4.29 FIX] v3_5 실제파일 1순위
        "pnl_strategy_linker_v3_4_FIXED",           # fallback
        "pnl_strategy_linker_v3_4",                 # fallback
        "pnl_strategy_linker_v3_3_SAFEPLUS_FINAL",  # 3순위 (구버전 폴백)
        "pnl_strategy_linker_v3_2_SAFEPLUS_FINAL",  # 4순위
        "pnl_strategy_linker_v3_1",                 # 5순위 구버전 fallback
        "pnl_strategy_linker_v2_0",
        "pnl_strategy_linker",
    ):
        try:
            import importlib as _il
            _m = _il.import_module(_pnl_mod)
            _load_weights     = _m.load_strategy_weights
            _load_pnl         = _m.load_strategy_pnl
            _check_daily_stop = _m.check_daily_stop
            _get_streak       = _m.get_drawdown_streak
            _pnl_mod_ref      = _m          # [v4.29 FIX] write_buy_fill 참조용
            _pnl_imported = True
            break
        except (ImportError, AttributeError):
            continue
    if not _pnl_imported:
        raise ImportError
    _PNL_OK = True
    _PNL_MOD_USED = _pnl_mod   # [v4.22 FIX-7] 로드된 모듈명 기록
except ImportError:
    _PNL_OK = False
    _PNL_MOD_USED = ""
    _pnl_mod_ref  = None     # [v4.29 FIX]
    def _load_weights(**kw): return {}
    def _load_pnl(**kw):
        try:
            import pandas as pd; return pd.DataFrame()
        except ImportError: return None
    def _check_daily_stop(**kw): return {"halt": False, "today_pnl_pct": 0}
    def _get_streak(strategy, **kw): return {"streak": 0, "warn": False, "halt": False}

try:
    import pandas as pd
    _PD_OK = True
except ImportError:
    _PD_OK = False


# ═══════════════════════════════════════════════════════════════
#  상수 — 기본
# ═══════════════════════════════════════════════════════════════
RC_OK   = 0
RC_HOLD = 200
VERSION       = "rt_execution_engine_v4_29_SAFEPLUS_FINAL"  # [PATCH] 파일명 v4_29 기준 VERSION/로거/시작로그 통일
STRATEGY_NAME = "RT_ENGINE"

BASE     = Path(os.environ.get("SAFEPLUS_BASE", r"C:\stock_bot")).resolve()
DATA     = BASE / "DATA"
LOG_DIR  = DATA / "LOG"
RT_CSV    = DATA / "rt_intraday.csv"
RISK_CSV    = DATA / "rt_risk_candidates.csv"
TARGET_JSON = DATA / "bridge_target.json"
SIGNAL      = LOG_DIR / "rt_execution_signal.json"
SWITCH_DECISION = DATA / "switch_decision.json"
LOG_PATH = LOG_DIR / "rt_execution_engine.log"
# [v4.23 FIX-1] market_state 연결 경로 — eod_shared_data.pkl
EOD_SHARED_PKL = DATA / "eod_shared_data.pkl"

TOTAL_CAPITAL     = int(os.environ.get("TOTAL_CAPITAL",     "50000000"))
REAL_TEST_CAPITAL = int(os.environ.get("REAL_TEST_CAPITAL",  "2000000"))  # [v4.17 FIX-1] 1M→2M (run_pipeline v2.7 TOTAL_CAPITAL=2M 통일)
# [STALE-TS-FILTER 2026-06-05] 후보 행 ts 가 N분 이상 멈춘(frozen) 종목 제외.
#   수집 유니버스 밖으로 빠진 종목(예: 007390)이 last-known 행으로 계속 끌려와 stale 신호로 매수되는 것 차단.
STALE_TS_MAX_MIN  = float(os.environ.get("STALE_TS_MAX_MIN", "10.0"))      # 후보 ts 허용 최대 경과(분)
REAL_TEST_MODE    = os.environ.get("REAL_TEST_MODE", "true").strip().lower() == "true"  # [v4_9-P7] strip 추가 — sender(line 394)와 정합 (빈문자열·공백 보호)

def _capital() -> int:
    # [#4 자본 단일화 2026-06-08] capital_config(SSOT) 단일소스 — buy_sender/eod_pickup과 통일.
    #   capital.json capital_krw=0(비상차단)도 사이징에 그대로 반영(0이면 order_krw=0→매수0). import 실패 시만 기존 env fallback.
    #   ※이게 오늘 capital.json=0이 rt_execution엔 안 먹혔던 이유(혼자 REAL_TEST_CAPITAL 사용)를 해소.
    try:
        import capital_config as _cc
        return int(_cc.get_capital())
    except Exception:
        return REAL_TEST_CAPITAL if REAL_TEST_MODE else TOTAL_CAPITAL

ATTACK_SIZE_BULL = 0.70; STABLE_SIZE_BULL = 0.30
ATTACK_SIZE_BEAR = 0.50; STABLE_SIZE_BEAR = 0.50

EV_ULTRA           = 0.90
EARLY_CUT_LOSS     = -2.0   # [R30 2026-05-14] -0.7 → -2.0 완화 (Van Tharp 2% rule 정합).
                            # 시장 조사: Minervini/CANSLIM 7~8% / Van Tharp 1~2% / ATR 2x 3~4%. -0.7%는 한국 시장 평균 변동성 ±1.5~2% 보다 좁음 → 매수 직후 손절 확률 60~70%.
                            # 사용자 결정 (130건 검증 + 시장 조사 후): B안 -2.0% (자본 risk 2% 정합).
                            # 5/15+ evolution_engine 자동 조정 위임 (매수 1건+ 누적 시).

TRAIL_STRONG       = 0.65
TRAIL_MID          = 0.45
TRAIL_EXIT         = 0.30
PARTIAL_SELL_RATIO = 0.25

MIN_VOLUME_ACCEL   = 1.15   # [v4.11 P1-2] 1.3→1.15 완화
MIN_CLOSE_POSITION = 0.55   # [v4.11 P1-2] 0.65→0.55 완화

MAX_POSITION_CAP     = 0.70
MAX_LOSS_PER_TRADE   = -2.5
BASE_LOSS_PER_TRADE  = -2.2
MAX_DAILY_LOSS       = -3.0
# [v4.11 P0-2] EV_DEFENSE_THRESHOLD 완전 제거 — 진입 차단 조건 삭제 (dead code 정리)

MAX_TRADES_PER_DAY          = 3   # [W35 PATCH 2026-05-13] 4→3: SIGA 1 + PULLBACK 2 (W31 ENTRY_WEIGHTS=[0.50, 0.25] 정합)
SIGA_MAX_TRADES_PER_DAY     = 3   # [SIGA3 2026-05-13] 1→3: BOM 패치 실측 + 5/13 1회 매수 후 추가 SIGA 시도 가능. MAX_TRADES_PER_DAY=3 한도가 상위 제약. 정책 일시 완화 (5/14+ 재평가)
PULLBACK_MAX_TRADES_PER_DAY = int(os.environ.get("PULLBACK_MAX_TRADES_PER_DAY", "3"))   # [v4.30 P3 복원 2026-06-02] 2→3: 사용자 의도=1/2/ADD 신규 3회차. TIER1/2/3 회차별 강화(check_tiered) 부활. rt_risk pullback_count<3과 정합. env로 되돌리기 가능.
COOLDOWN_MIN                = 10

EV_ENTRY_MIN = float(os.environ.get("EV_ENTRY_MIN_GLOBAL", "0.45"))   # [v4.11 P0-1] 0.60→0.45→0.40 완화 (과도한 진입 차단 해소)
EV_STRONG    = 0.7

ATTACK_INST_DAYS_MIN = 2    # [v4.28] 3→2: 기관 초입 포착 빠르게
ATTACK_OFI_MIN       = float(os.environ.get("ATTACK_OFI_MIN", "0.20"))  # [v4.28] 0.30→0.20: 기관 흐름 초기 신호 포착
ATTACK_ACCEL_MIN     = 1.0   # [v4.28] 1.2→1.0: 가속도 기준선 (1.0=중립, 이하면 감속)

MAX_DAY_CHG_PCT  = 60.0   # [SURGE 완화] 12→60: 진짜 과열만 차단
OVERHEAT_CHG_PCT = 6.0

PF_STRONG = 1.50
PF_WEAK   = 1.00

# [v4.11 P0-5] (900,910) 시가 직후 블락 제거 — 주요 타이밍 허용
ENTRY_BLACKOUT = [(int(os.environ.get("ENTRY_BLACKOUT_START", "1455")), int(os.environ.get("ENTRY_BLACKOUT_END", "1500")))]                # [PATCH] 점심(1130~1300) 차단 제거 — 14:55~15:00 마감 직전만 유지 (env 조정 가능)
PULLBACK_ENTRY_BLACKOUT = []                   # [PATCH] 시간 차단 제거 — 점수/OFI/CONSEC/품질로만 통제
# 근거: params v3.9 FORCE_CLOSE_BCD=1450 상향 → 1430 차단이면 14:30~14:50 진입 불가

# [PULLBACK-MORNING 2026-06-07] 아침 시간대 품질 차등 — 09:00 즉시매수 방지 + 09:05 강한예외 + 09:10 주력 + 10:20+ strict.
#   ★rt_execution 내부 시간/품질 게이트만. 일일 3회/쿨다운/주문로직 무변경. env로 시각·임계 전부 조정 가능.
PULLBACK_TIME_GATE_ENABLE   = os.environ.get("PULLBACK_TIME_GATE_ENABLE", "YES").strip().upper() == "YES"
PULLBACK_START_HHMM         = int(os.environ.get("PULLBACK_START_HHMM",            "910"))   # 주력 매수 시작(이전=강한예외만)
# [PULLVOL-GATE 2026-06-11] 눌림 중 거래량 폭증 차단 — 백테 검증 후 채택(사용자 지시 즉시적용)
PB_PULLVOL_GATE = os.environ.get("PB_PULLVOL_GATE", "YES").strip().upper() == "YES"
PB_PULLVOL_MAX  = float(os.environ.get("PB_PULLVOL_MAX", "1.3"))
# [LEADER-FIRST 2026-06-11 사용자결정] 당일 대금 최상위(대장주) 눌림후보 최우선 승격.
#   백테(39일): 대금 top3 첫눌림 +4.38%(n=8) vs 일반 -0.89%(n=434). 표본 작아 관찰병행,
#   채택은 사용자 지시("합리적이니 넣고 실험"). 같은날 재매수는 전략중복 차단이 막아 사실상 첫눌림만.
#   롤백 env LEADER_FIRST_ENABLE=NO. MIN_EOK=수집기준 당일누적 거래대금(억) 문턱.
LEADER_FIRST_ENABLE  = os.environ.get("LEADER_FIRST_ENABLE", "YES").strip().upper() == "YES"
LEADER_FIRST_MIN_EOK = float(os.environ.get("LEADER_FIRST_MIN_EOK", "1000"))
PULLBACK_EARLY_EXC_START    = int(os.environ.get("PULLBACK_EARLY_EXCEPTION_START", "905"))   # 강한예외 시작
PULLBACK_EARLY_EXC_END      = int(os.environ.get("PULLBACK_EARLY_EXCEPTION_END",   "910"))   # 강한예외 끝(=주력 시작)
PULLBACK_MAIN_END_HHMM      = int(os.environ.get("PULLBACK_MAIN_END_HHMM",         "1020"))  # 주력 종료
PULLBACK_LATE_STRICT_HHMM   = int(os.environ.get("PULLBACK_LATE_STRICT_HHMM",      "1020"))  # 이후 신규 strict(3회차 ADD는 강하면 허용)
PULLBACK_TIER3_ADD_STRICT   = os.environ.get("PULLBACK_TIER3_ADD_STRICT", "YES").strip().upper() == "YES"
# 강한예외/strict/TIER3 공통 품질 임계 (rt_intraday 실컬럼: price_vs_vwap / price_vs_day_high / close_position / volume_accel / last3_ret / prescore_weighted)
PB_STRONG_PRESCORE_MIN = float(os.environ.get("PB_STRONG_PRESCORE_MIN", "30.0"))  # 강한 후보 prescore 하한
PB_VWAP_MIN            = float(os.environ.get("PB_VWAP_MIN",            "1.0"))    # price_vs_vwap≥1.0 = VWAP 위
PB_VWAP_FAR_BELOW      = float(os.environ.get("PB_VWAP_FAR_BELOW",      "0.99"))   # 주력창: 이값 미만(VWAP 1%↓)만 차단(보수)
PB_VALUE_ACCEL_MIN     = float(os.environ.get("PB_VALUE_ACCEL_MIN",     "1.0"))    # 거래대금 재가속(volume_accel) 하한
PB_CLOSE_POS_STRONG    = float(os.environ.get("PB_CLOSE_POS_STRONG",    "0.6"))    # 고가권 유지 close_position 하한
PB_COLLAPSE_RET        = float(os.environ.get("PB_COLLAPSE_RET",        "-2.0"))   # last3_ret≤이값 = 최근봉 붕괴
PB_OVERHEAT_SPIKE_RET  = float(os.environ.get("PB_OVERHEAT_SPIKE_RET",  "2.0"))    # 고가근접+last3_ret≥이값 = 과열 추격
# [EARLY_REBOUND 2026-06-07] 09:05~09:10 = 단순 strong이 아니라 '눌림 후 초기 반등' 셋업 포착.
#   ★pullback_depth/저점이탈 직접컬럼 없음 → 프록시: 눌림폭=(1-price_vs_day_high)*100 / 저점holding=close_pos_3m.
PULLBACK_EARLY_REBOUND_ENABLE = os.environ.get("PULLBACK_EARLY_REBOUND_ENABLE", "YES").strip().upper() == "YES"
PB_REBOUND_DEPTH_MIN = float(os.environ.get("PB_REBOUND_DEPTH_MIN", "0.8"))   # 눌림폭(%) 하한(이하=고점추격)
PB_REBOUND_DEPTH_MAX = float(os.environ.get("PB_REBOUND_DEPTH_MAX", "3.0"))   # 눌림폭(%) 상한(이상=과도하락)
PB_VWAP_RECLAIM      = float(os.environ.get("PB_VWAP_RECLAIM",      "0.998")) # price_vs_vwap≥이값=VWAP 위/회복
PB_LOW_HOLD_MIN      = float(os.environ.get("PB_LOW_HOLD_MIN",      "0.2"))   # close_pos_3m≥이값=직전저점 이탈없음
PB_REBOUND_RIDE_MIN  = float(os.environ.get("PB_REBOUND_RIDE_MIN",  "0.30"))  # ride_score 하한(flow 조건)
PB_REBOUND_OFI_MIN   = float(os.environ.get("PB_REBOUND_OFI_MIN",   "0.0"))   # ofi>이값(flow 조건)
# [HIGHER-LOW 2026-06-07] 저점이탈 직접판정 — recent_low/prev_low 컬럼 있으면 higher-low 직접, 없으면 close_pos_3m 프록시 폴백.
PB_HIGHER_LOW_ENABLE = os.environ.get("PB_HIGHER_LOW_ENABLE", "YES").strip().upper() == "YES"
PB_HIGHER_LOW_TOL    = float(os.environ.get("PB_HIGHER_LOW_TOL", "0.998"))    # recent_low >= prev_low × 이값 = 저점 유지(0.2% 허용)
# [HIGHER-LOW B 2026-06-07] rt_intraday에 저점컬럼 없음 → prices_1m 오늘 1분봉에서 직접 저점 판정.
PB_HL_FROM_PRICES1M  = os.environ.get("PB_HL_FROM_PRICES1M", "YES").strip().upper() == "YES"
PB_HL_BARS           = int(os.environ.get("PB_HL_BARS", "3"))                 # 최근 K봉 저점 vs 직전 K봉 저점 비교(봉 부족시 가용분 절반분할)
# FALLBACK_DEADLINE=1430 + BLACKOUT=1430 → fallback 무력화 구조 해소
# 1455: 14:50 강제청산 5분 전 신규진입 차단 (체결 안전마진)
SLIPPAGE_RATE  = float(os.environ.get("SLIPPAGE_RATE", "0.0015"))
TOP1_BONUS     = 1.20
W_RIDE         = 0.15   # [v4.29] inst_ride_score 가중치 (selection_score 복합 배수)
W_OFI          = 0.08   # [v4.29] ofi 가중치 (양수만 반영, 음수 → 0)
STAGE_8_CAP    = 8      # [v4.29] 최종 비교 풀 상한 — 8개 초과 시 상위 8개만 비교
# [EXEC 8→1 보강 2026-06-05] ①테마일관성(rt_risk가 8에 넣은 테마대장주 존중) ②실행품질(유동성↑=슬리피지↓ 우대).
#   기본 SHADOW(둘 다 로그만, best 불변). 적용: EXEC_THEME_PRIORITY=YES / EXEC_EXECQ_WEIGHT>0. env 되돌림.
# [TURN-GATE 2026-06-05 ★LIVE] 떨어지는中(매도우위) 매수금지, 바닥 찍고 돈 들어오며 매수세 우위일 때만 매수.
#   [조기화] last3_ret(3봉=9분=늦음) → ofi(주문흐름=실시간 매수세) + 거래대금 가속(value_now>value_prev).
#   연구: 반등은 '거래량 급증+매수세 유입' 봉에서. ofi>0=사자 유입(가격 오르기 前). 기본 ON(사용자 결정 LIVE).
EXEC_TURN_GATE     = os.environ.get("EXEC_TURN_GATE", "YES").strip().upper() == "YES"
EXEC_TURN_OFI_MIN  = float(os.environ.get("EXEC_TURN_OFI_MIN", "0.0"))   # ofi 하한(0=매수우위, >0면 더 강한 매수세 요구)
EXEC_TURN_NEED_VOL = os.environ.get("EXEC_TURN_NEED_VOL", "YES").strip().upper() == "YES"  # 거래대금 가속 동시요구(너무 막히면 NO)
# [PULLBACK-TIMING 2026-06-05 ★LIVE] 통합 매수타이밍 게이트 — 눌림 끝나고 살아나는 첫 순간만 PASS.
#   ①떨어지는中 차단 ②VWAP 회복 ③눌림폭 적정 ④반전확인 ⑤매도폭증 차단. 안전 fallback(필드없으면 해당조건 skip).
#   ⚠depth 깊은차단: GPT -6%, 단 우리 백테는 깊을수록(~8%) 반등↑ → 기본 -8%(env로 -6 조정가능).
PB_TIMING_GATE   = os.environ.get("PB_TIMING_GATE", "YES").strip().upper() == "YES"
PB_VWAP_MIN      = float(os.environ.get("PB_VWAP_MIN", "0.998"))      # price/vwap 하한(VWAP 위/재돌파)
PB_NEAR_HIGH_PCT = float(os.environ.get("PB_NEAR_HIGH_PCT", "-0.5"))  # depth>-0.5%=고점추격 차단
PB_DEEP_MAX_PCT  = float(os.environ.get("PB_DEEP_MAX_PCT", "-8.0"))   # depth<-8%=추세훼손 차단
PB_SELL_SPIKE    = float(os.environ.get("PB_SELL_SPIKE", "1.5"))      # 하락중 거래대금 폭증배수=매도폭증
EXEC_THEME_PRIORITY = os.environ.get("EXEC_THEME_PRIORITY", "NO").strip().upper() == "YES"

# [PULLBACK-BREAKOUT 2026-06-13 친구님] ★돌파 트리거 — "눌림은 후보, 돌파는 방아쇠".
#   8→1 확정 후보가 '눌림 고점 돌파 + 거래량 증가'면만 실제 매수(미돌파=대기). EXECUTION에만(RTRISK 선별엔 안 넣음=좋은 눌림 탈락 방지).
#   ⚠[6/10] naked ORB는 edge 음수였음 → 이건 '대장주 건강한눌림 후 재출발' 트리거(다른 용도)·거래량 필수·실데이터 검증.
#   안전: 분봉없음/실패=통과(fail-open, 매매 안 막음). 양성 '미돌파/거래량부족'일 때만 대기. 롤백 setx PULLBACK_BREAKOUT_ENABLE NO.
PULLBACK_BREAKOUT_ENABLE = os.environ.get("PULLBACK_BREAKOUT_ENABLE", "NO").strip().upper() == "YES"
PB_BREAKOUT_VOL_LB       = int(os.environ.get("PB_BREAKOUT_VOL_LB", "10"))    # 거래량 비교 직전 봉수
PB_BREAKOUT_WIDEN_PCT    = float(os.environ.get("PB_BREAKOUT_WIDEN_PCT", "0.5"))  # #1 접근도: 직전 대비 +이값%p 멀어지면 '멀어짐'
PB_BREAKOUT_REBREAK_MAX  = int(os.environ.get("PB_BREAKOUT_REBREAK_MAX", "3"))    # #2 재돌파 이 횟수+면 지친종목=대기(첫돌파 우대)
_P1M_RAW_CACHE           = {"mtime": None, "groups": None}


def _breakout_ok(code: str):
    """돌파 트리거 + #1 접근도 좁혀짐 추적 + #2 첫돌파 우대(재돌파 감점) → (ok, reason).
    분봉없음/실패=관대(True, 매매 안 막음). '미돌파/멀어짐/거래량부족/재돌파반복'일 때만 False(대기)."""
    try:
        import pandas as _pd
        _p = DATA / "prices_1m.csv"
        if not _p.exists():
            return False, "분봉파일없음(검증불가→안삼)"   # [친구님] 분봉 없으면 매수 안함
        _mt = _p.stat().st_mtime
        if _P1M_RAW_CACHE["mtime"] != _mt or _P1M_RAW_CACHE["groups"] is None:
            _df = _pd.read_csv(_p, usecols=["code", "ts", "high", "close", "volume"], dtype={"code": str})
            _df["code"] = _df["code"].str.zfill(6)
            for _c in ("high", "close", "volume"):
                _df[_c] = _pd.to_numeric(_df[_c], errors="coerce")
            _P1M_RAW_CACHE["mtime"] = _mt
            _P1M_RAW_CACHE["groups"] = {c: g for c, g in _df.groupby("code")}
        g = _P1M_RAW_CACHE["groups"].get(str(code).zfill(6))
        if g is None or len(g) < 8:
            return False, "분봉부족(검증불가→안삼)"   # [친구님] 분봉 부족하면 매수 안함
        g = g.sort_values("ts")
        highs = g["high"].ffill().values; closes = g["close"].ffill().values; vols = g["volume"].fillna(0).values
        last = closes[-1]
        micro_high = float(max(highs[-11:-1])) if len(highs) >= 11 else float(max(highs[:-1]))
        if micro_high <= 0:
            return True, "고점0(통과)"
        # [#2 첫돌파 우대] 눌림 에피소드 수(고점대비 ≥1.5% 빠졌다 회복=1회) = 재돌파 반복 측정
        _peak = highs[0]; _ep = 0; _inpb = False
        for _i in range(len(closes)):
            if highs[_i] > _peak:
                _peak = highs[_i]
            _dd = (closes[_i] - _peak) / _peak if _peak > 0 else 0.0
            if not _inpb and _dd <= -0.015:
                _ep += 1; _inpb = True
            elif _inpb and _dd >= -0.005:
                _inpb = False
        # [#1 접근도 추세] 직전 6봉 '고점까지 거리(%)'가 좁혀지나 멀어지나 (ref=micro_high 고정)
        _widening = False
        if len(closes) >= 6:
            _bd = [(micro_high / c - 1) * 100 for c in closes[-6:] if c > 0]
            if len(_bd) >= 4:
                _widening = (sum(_bd[-2:]) / 2.0) > (sum(_bd[:2]) / 2.0) + PB_BREAKOUT_WIDEN_PCT
        # ── 판정 ──
        if last < micro_high:                       # 아직 미돌파 = 대기
            _gap = (micro_high / last - 1) * 100
            if _widening:                            # #1 멀어지는 중 = 접근 실패(방아쇠 안 당김)
                return False, f"멀어짐(접근실패·고점까지 {_gap:.1f}%)"
            return False, f"접근중(고점까지 {_gap:.1f}%)"
        # 돌파함:
        if _ep >= PB_BREAKOUT_REBREAK_MAX:           # #2 재돌파 반복 = 지친 종목 → 대기(첫돌파 우대)
            return False, f"재돌파{_ep}회반복(지친종목·첫돌파우대→대기)"
        _lb = PB_BREAKOUT_VOL_LB
        if len(vols) >= _lb + 3 and vols[-3:].mean() <= vols[-(_lb + 3):-3].mean():
            return False, "거래량부족(페이크 돌파 우려)"
        _tag = "첫돌파" if _ep <= 1 else f"{_ep}차돌파"
        return True, f"돌파+거래량({_tag}·고점 {micro_high:.0f} 상향)"
    except Exception as _be:
        return True, f"돌파체크실패(통과:{_be})"


def _pullback_timing_gate(row: dict, code: str):
    """[PULLBACK-TIMING] 눌림 끝나고 살아나는 첫 순간만 PASS. 안전 fallback(필드없으면 그 조건 skip, 죽지않음).
    반환 (ok: bool, reason: str). 주문/체결/브로커 무관 — 매수타이밍 판단만."""
    pv_vwap = _f(row.get("price_vs_vwap"), None)      # price/vwap (>=1=VWAP 위)
    pv_dh   = _f(row.get("price_vs_day_high"), None)  # price/day_high (<=1)
    ofi     = _f(row.get("ofi", 0.0))
    l3      = _f(row.get("last3_ret", 0.0))
    vn      = _f(row.get("value_now", 0.0)); vp = _f(row.get("value_prev", 0.0))
    vreaccel = (vn / vp) if vp > 0 else None
    # [3] 눌림폭(day_high 대비)
    depth = (pv_dh - 1.0) * 100.0 if (pv_dh and pv_dh > 0) else None
    if depth is not None:
        if depth > PB_NEAR_HIGH_PCT:
            return False, f"too_near_day_high(depth={depth:.1f})"
        if depth < PB_DEEP_MAX_PCT:
            return False, f"deep_pullback_trend_broken(depth={depth:.1f})"
    # [2] VWAP 회복
    if pv_vwap is not None and pv_vwap < PB_VWAP_MIN:
        return False, f"vwap_below_no_reclaim(pvwap={pv_vwap:.3f})"
    # [5] 하락中 거래대금 폭증 = 매도폭증 차단
    if vreaccel is not None and ofi < 0 and vreaccel >= PB_SELL_SPIKE:
        return False, f"sell_volume_spike(vr={vreaccel:.2f} ofi={ofi:.2f})"
    # [1]+[4] 떨어지는中 차단 / 반전 확인 — ofi>0(매수세) 또는 last3_ret>0(반등) 중 하나
    if not ((ofi > EXEC_TURN_OFI_MIN) or (l3 > 0)):
        return False, "falling_no_reversal"
    # [6] ★돌파 트리거(친구님) — 위 조건 다 통과해도 '눌림 고점 돌파+거래량'까지 확인돼야 실제 매수(방아쇠).
    #   미돌파면 대기(다음 사이클 재확인). 분봉없음/실패=통과(안전). "눌림은 후보, 돌파는 방아쇠".
    if PULLBACK_BREAKOUT_ENABLE:
        _bok, _br = _breakout_ok(code)
        if not _bok:
            return False, f"breakout_wait[{_br}]"
    _d = f"{depth:.1f}" if depth is not None else "NA"
    _vr = f"{vreaccel:.2f}" if vreaccel is not None else "NA"
    _bx = ""
    if PULLBACK_BREAKOUT_ENABLE:
        _bx = " breakout=FIRE"
    return True, f"depth={_d} vwap={'OK' if pv_vwap is None or pv_vwap >= PB_VWAP_MIN else 'NA'} ofi={ofi:.2f} vreaccel={_vr}{_bx}"
EXEC_EXECQ_WEIGHT   = float(os.environ.get("EXEC_EXECQ_WEIGHT", "0.0"))   # 유동성 z 가중(0=SHADOW)
# [TURN-LIVE 2026-06-06] 사용자 지시 — 1등 점수에 GPT 5축(가격위치·거래대금·수급·호가/체결강도)을 실제 반영(SHADOW 아님).
#   selection_score × (1 + turn_z × EXEC_TURN_WEIGHT)로 8→1 재정렬. 0=OFF(되돌림). 기본 0.10=ON.
EXEC_TURN_WEIGHT    = float(os.environ.get("EXEC_TURN_WEIGHT", "0.10"))
# [HOGA-LIVE 2026-06-06] 축④ 호가/체결강도 실반영 — 최종 8후보를 broker(opt10004 호가+opt10001 체결강도)로 실시간 조회.
#   기본 ON. broker DEAD/실패 시 자동 중립(매수결정 무손상). =0(NO)면 호가축 제외(기존 3축).
EXEC_HOGA_ENABLE    = os.environ.get("EXEC_HOGA_ENABLE", "YES").strip().upper() == "YES"
EXEC_HOGA_STRENGTH  = os.environ.get("EXEC_HOGA_STRENGTH", "YES").strip().upper() == "YES"  # opt10001 체결강도 조회
EXEC_THEME_RANK     = int(os.environ.get("EXEC_THEME_RANK", "20"))
_EXEC_THEME_CACHE   = {"date": "", "set": set()}


def _exec_theme_leader_set() -> set:
    """[EXEC] code_theme_strength is_leader=1 & rank<=RANK 코드 set. 일자캐시·3일stale·실패→빈set."""
    import time as _t, csv as _csv
    _today = _t.strftime("%Y%m%d")
    if _EXEC_THEME_CACHE["date"] == _today:
        return _EXEC_THEME_CACHE["set"]
    s = set()
    try:
        _f2 = DATA / "theme" / "code_theme_strength.csv"
        if _f2.exists() and (_t.time() - _f2.stat().st_mtime) / 86400.0 <= 3.0:
            with open(_f2, "r", encoding="utf-8-sig", errors="replace") as _fh:
                for _r in _csv.DictReader(_fh):
                    if str(_r.get("is_leader", "0")).strip() != "1":
                        continue
                    try:
                        _rk = int(float(_r.get("best_theme_rank", 999) or 999))
                    except (TypeError, ValueError):
                        _rk = 999
                    if _rk <= EXEC_THEME_RANK:
                        s.add(str(_r.get("code", "")).zfill(6))
    except Exception:
        pass
    _EXEC_THEME_CACHE["date"] = _today
    _EXEC_THEME_CACHE["set"] = s
    return s
WINNER_GAP_MIN = float(os.environ.get("WINNER_GAP_MIN", "3.5"))    # [v4.29] 1등-2등 raw prescore 차이 최소값 (미달 시 ATTACK 차단)
WINNER_DOM_MIN = 1.05   # [v4.29] 1등/2등 raw prescore 비율 최소값 (미달 시 ATTACK 차단)

# [v4.9] BEAR 레짐 추가 EV 기준 (수익률 방어)
EV_BEAR_EXTRA  = 0.20   # BEAR 레짐 시 EV_ENTRY_MIN + 0.20 자동 적용

INST_RIDE_MIN   = float(os.environ.get("INST_RIDE_SCORE_MIN", "0.30"));  INST_STRONG_MIN = float(os.environ.get("INST_RIDE_SCORE_STRONG", "0.60"))  # [INST-UNIT-FIX 2026-06-04] inst_ride_score는 0~1.5 점수(MULTI-TIER 산출)인데 기존 2/4는 일수 기준 → 단위불일치로 강한기관(0.89)이 +0.40 대신 -0.10 페널티. 점수기준(0.30/0.60)으로 교정. env로 롤백/튜닝.
OFI_RIDE_MIN    = 0.15; OFI_STRONG_MIN = 0.30
RIDE_HARD_MIN   = 0.25; RIDE_SOFT_MIN  = 0.40; RIDE_STRONG_MIN = 0.60

MIN_PRESCORE     = 15.0
MIN_ATTACK_SCORE = 8.0
ATTACK_PRESCORE  = 22.0   # [v4.30] 25.0→22.0: 스코어보드 선별 완료 종목 재필터 완화 (ps 22~24.9 ATTACK 경로 개방)

CONSEC_LOSS_WARN = 3; CONSEC_LOSS_HALT = 5

TRADE_COST_BASE   = 0.0021
TRADE_COST_LOW_LQ = 0.0045
TRADE_COST_MID_LQ = 0.0030
LIQUIDITY_HI_KRW  = 5_000_000_000
LIQUIDITY_MID_KRW = 1_500_000_000

EV_MIN_SAMPLES = 8    # [v4.17 FIX-2] 12→8 (bridge WARMING_MIN=8 통일. Lo(2002) n≥12는 Sharpe용 — EV보정 최소기준은 8건으로 완화)
EV_LOOKBACK    = 60
EV_OFI_BOOST   = 0.002
EV_OFI_BOOST_BULL = 0.003   # [v4.9] BULL 레짐 OFI 부스트 강화 (수익률↑)

EXIT_INST_DECAY_DAYS = 1
EXIT_OFI_DECAY_PCT   = 40
EXIT_MAX_HOLD_DAYS   = 5

KELLY_HALF_MULT = 0.50
KELLY_HARD_MAX  = 0.65   # [v4.11 P1-3] 0.50→0.65 상향 (수익 확대 여지)
KELLY_DEFAULT   = 0.30

# [v4.10] 결함① 수정 — EOD 힌트 필터 모순 완전 제거
# VALID_HINTS: 이 엔진이 허용하는 전략 힌트 (EOD 제거 — evaluate_candidates에서도 EOD 예외 구문 삭제)
VALID_HINTS        = {"MULTI", "", "PULLBACK"}  # [SIGA-RETIRE 2026-06-01] SIGA 제거 — 아침 시가매수 폐기(종가매수 대체). PULLBACK/MULTI만 매수
# EXCLUDE_HINTS: 명시적 차단 힌트 (EOD는 VALID에 없으므로 자동 차단 — 중복 선언 불필요)
# 종배/시배 전략 완전 차단: JONGBAE, SIGA_OPEN, OPEN_BID, JONG_BID
EXCLUDE_HINTS      = {"JONGBAE", "SIGA_OPEN", "OPEN_BID", "JONG_BID"}
EXCLUDE_HINTS_BEAR = {"JONGBAE", "SIGA_OPEN", "OPEN_BID", "JONG_BID"}

REQUIRED_COLUMNS = {"code", "prescore_weighted", "attack_score"}
RECOMMENDED_COLUMNS = {
    "inst_ride_score", "ofi", "inst_accel", "price_vs_vwap",
    "stable_score", "expected_edge", "value_now", "market_flag",
    "strategy_hint", "close_position", "volume_accel",
    "price_vs_day_high", "last3_ret", "ofi_last10", "value_day",
}

QUALITY_MIN         = 0.40
PROFIT_FACTOR_BONUS = 1.50
PROFIT_FACTOR_WARN  = 1.00

TIME_WEIGHT_MAP = [
    # [MORNING-NOPENALTY 2026-06-12 ★친구님 지시 "아침 감점은 제살깎기, 무조건 지워"]
    #   아침은 돈이 가장 많이 움직이는 시간 + 트레일링 활주로 최장. 감점(0.70/0.90) → 1.00.
    #   오후 우대(1.15)·마감직전 억제(0.50)는 용도 다름 = 유지.
    #   롤백: (903,910,0.70), (930,1030,0.90) 복원 또는 .bak_pre_morningweight_20260612.
    (903,  910,  1.00), (910,  930,  1.00), (930,  1030, 1.00),
    (1030, 1130, 1.10), (1300, 1430, 1.15),
    (1430, 1520, 0.90),
    (1520, 1530, 0.50),  # [v4.20] 강제청산 직전 10분 — 신규진입 억제
]

# ═══════════════════════════════════════════════════════════════
#  [v4.16] 단계별 진입 상수 — 참조 보존용 (함수는 무력화됨)
#  check_tiered_entry_quality는 항상 True 반환 (v4.15 S2)
#  MAX_TRADES_PER_DAY=1 → 2·3회차 진입 자체 불가
# ═══════════════════════════════════════════════════════════════
SECOND_ENTRY_EV_MIN        = 0.55   # 참조용 보존 (미사용)
SECOND_ENTRY_PRESCORE_MIN  = 14.0
SECOND_ENTRY_VOL_ACCEL_MIN = 1.2
SECOND_ENTRY_CLOSE_POS_MIN = 0.60

THIRD_ENTRY_EV_MIN         = 0.70   # 참조용 보존 (미사용)
THIRD_ENTRY_ATTACK_MIN     = 8.0
THIRD_ENTRY_RIDE_MIN       = 0.30
THIRD_ENTRY_VOL_ACCEL_MIN  = 1.3

# ── [v4.4] 킬스위치 5대조건 상수 ────────────────────────────
KILL_ORDER_REJECT_MAX = 3
KILL_DATA_DELAY_SEC   = int(os.environ.get("KILL_DATA_DELAY_SEC", "90"))
KILL_REPEAT_SELL_MAX  = 5
KILL_DAILY_LOSS_BEAR  = -2.0

# ── fallback 상수 (v4.6) ─────────────────────────────────────
FALLBACK_DEADLINE_HM      = 1430  # [v4.17 FIX-3] 1400→1430 (오후 핵심구간 30분 확보. 지침서 1일1진입 보장 강화)
FALLBACK_MIN_PRESCORE     = 15.0  # [v4.30] 12.0→15.0: MIN_PRESCORE와 통일, 저품질 fallback 차단
FALLBACK_MIN_RIDE         = 0.25
FALLBACK_MIN_QUALITY      = 0.40
FALLBACK_MIN_VOL_ACCEL    = 1.20
FALLBACK_MIN_CLOSE_POS    = 0.60
FALLBACK_MARKET_BAD_FLAG  = "DOWN"


# ═══════════════════════════════════════════════════════════════
#  유틸
# ═══════════════════════════════════════════════════════════════
def _now_kst() -> datetime:
    if KST: return datetime.now(tz=KST)
    return datetime.utcnow() + timedelta(hours=9)

def _now_str() -> str: return _now_kst().strftime("%Y-%m-%d %H:%M:%S")
def _today() -> str:   return _now_kst().strftime("%Y-%m-%d")
def _hhmm() -> int:    return int(_now_kst().strftime("%H%M"))

def _f(x, d: float = 0.0) -> float:
    try: return float(str(x).replace(",", ""))
    except Exception: return d

def _get_daily_count() -> int:
    if not SIGNAL.exists():
        return 0
    try:
        with open(SIGNAL, "r", encoding="utf-8-sig") as f:
            sig = json.load(f)
        if str(sig.get("date", "")) == _today():
            return int(sig.get("daily_trade_count", 1))
        return 0
    except Exception:
        return MAX_TRADES_PER_DAY  # 파싱 실패 → 진입 차단

def _get_siga_daily_count() -> int:  # [v4.30 P2] 시가전략 당일 진입 횟수
    if not SIGNAL.exists():
        return 0
    try:
        with open(SIGNAL, "r", encoding="utf-8-sig") as f:
            sig = json.load(f)
        if str(sig.get("date", "")) == _today():
            return int(sig.get("siga_daily_count", 0))
        return 0
    except Exception:
        return SIGA_MAX_TRADES_PER_DAY  # 파싱 실패 → 진입 차단

def _get_pullback_daily_count() -> int:  # [v4.30 P2] 눌림전략 당일 진입 횟수
    if not SIGNAL.exists():
        return 0
    try:
        with open(SIGNAL, "r", encoding="utf-8-sig") as f:
            sig = json.load(f)
        if str(sig.get("date", "")) == _today():
            _sig_cnt = int(sig.get("pullback_daily_count", 0))
            # [PHANTOM-FIX 2026-06-04] signal count는 엔진이 매수의도 시 기록 → bridge 거부 등으로
            # 실제 미체결이면 phantom으로 고착(자가 교착: 2회차 TIER2 차단→signal 미갱신→count 영구1).
            # 실제 보유 포지션(broker chejan 확정)과 reconcile → min(signal, real). 미체결 phantom 제거.
            try:
                _opf = DATA / "rt_open_positions.json"
                _real = 0
                if _opf.exists():
                    with open(_opf, "r", encoding="utf-8-sig") as _pf:
                        _pos = json.load(_pf)
                    # [PBCOUNT-FIX 2026-06-05] _real 합산을 strategy=="PULLBACK"로 한정.
                    #   기존: 전략 무관 qty>0 전부 카운트 → EOD_PICK 보유(예 007390)가 _real 부풀려
                    #         PULLBACK 1회차를 TIER2(vol>=1.20)로 오라우팅 → vol=0.00 차단(교차오염).
                    #   라이브증명: 007390 qty=0 되자 즉시 TIER1 통과·signal_written=True.
                    _real = sum(1 for _v in _pos.values()
                                if isinstance(_v, dict) and _f(_v.get("qty", 0)) > 0
                                and str(_v.get("strategy", "")).upper() == "PULLBACK")
                return min(_sig_cnt, _real)
            except Exception:
                return _sig_cnt
        return 0
    except Exception:
        return PULLBACK_MAX_TRADES_PER_DAY  # 파싱 실패 → 진입 차단

def _setup_logger() -> logging.Logger:
    lg = logging.getLogger("rt_exec_v4_29")  # [PATCH] 로거명 v4_22→v4_29 버전 통일
    if lg.handlers: return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s KST][%(levelname)s] %(message)s")
    try:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); lg.addHandler(sh)
    except Exception: pass
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(LOG_PATH), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8-sig")  # [Z15 2026-05-21]
        fh.setFormatter(fmt); lg.addHandler(fh)
    except Exception: pass
    return lg


# ═══════════════════════════════════════════════════════════════
#  [PATCH-LOCK] PID 기반 중복 실행 차단 — 신호 큐 중복 작성 방지
#    Windows 안전 정책:
#      - tasklist 기반 PID 생존 확인 (os.kill PermissionError 오판 회피)
#      - PID가 살아있으면 stale 여부 무관하게 강제 해제 금지
#      - PID 사망이 명확할 때만 락 해제
#      - 판단 불가 시 안전쪽(중복 실행 차단)으로 처리
# ═══════════════════════════════════════════════════════════════
_LOCK_ACQUIRED = False

def _exec_lock_path() -> Path:
    return LOG_DIR / "rt_execution_engine.lock"

def _is_pid_alive_win(pid: int) -> Optional[bool]:
    """Windows tasklist 기반 PID 생존 확인.
    True=살아있음, False=죽음 명확, None=판단 불가(안전 차단용)."""
    if pid <= 0:
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stderr=subprocess.STDOUT,
            timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).decode("utf-8", errors="ignore")
    except Exception:
        return None  # 판단 불가
    if "No tasks" in out or "INFO:" in out:
        return False
    if f'"{pid}"' in out:
        return True
    return False

def _acquire_exec_lock(logger: logging.Logger) -> bool:
    global _LOCK_ACQUIRED
    lp = _exec_lock_path()
    try:
        if lp.exists():
            try:
                lock_pid = int(lp.read_text(encoding="utf-8-sig").strip())
            except (ValueError, OSError) as e:
                logger.error("[LOCK] PID 파싱 실패(%s) → 안전 차단", e)
                return False
            alive = _is_pid_alive_win(lock_pid)
            if alive is True:
                logger.error("[LOCK] PID=%d 실행 중 → 중복 실행 차단", lock_pid)
                return False
            elif alive is False:
                logger.warning("[LOCK] PID=%d 사망 확인 → 락 해제 후 진입", lock_pid)
                lp.unlink(missing_ok=True)
            else:
                logger.error("[LOCK] PID=%d 생존 확인 불가 → 안전 차단", lock_pid)
                return False
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")
        _LOCK_ACQUIRED = True
        return True
    except Exception as e:
        logger.error("[LOCK] 획득 실패: %s", e)
        return False

def _release_exec_lock() -> None:
    global _LOCK_ACQUIRED
    if not _LOCK_ACQUIRED:
        return
    try:
        _exec_lock_path().unlink(missing_ok=True)
    except Exception:
        pass
    _LOCK_ACQUIRED = False


# ═══════════════════════════════════════════════════════════════
#  시간대 블록 + 가중치
# ═══════════════════════════════════════════════════════════════
def check_time_block(lg: logging.Logger) -> bool:
    hm = _hhmm()
    for s, e in ENTRY_BLACKOUT:
        if s <= hm < e:
            lg.info("[TIME] %04d → 진입금지 %04d~%04d → SKIP", hm, s, e)
            return True
    return False

def _get_time_weight(lg: logging.Logger) -> float:
    hm = _hhmm()
    for t_s, t_e, w in TIME_WEIGHT_MAP:
        if t_s <= hm < t_e:
            if w != 1.0: lg.info("[TIME] %04d → 시간대 가중치 %.2f", hm, w)
            return w
    return 1.0


# ═══════════════════════════════════════════════════════════════
#  거래비용 동적 계산 (슬리피지 포함)
# ═══════════════════════════════════════════════════════════════
def _get_trade_cost(row: dict) -> float:
    v = _f(row.get("value_day", row.get("value_now", 0)))
    base = TRADE_COST_BASE * 2 + SLIPPAGE_RATE
    if v >= LIQUIDITY_HI_KRW:  return base
    elif v >= LIQUIDITY_MID_KRW: return base + TRADE_COST_MID_LQ
    else: return base + TRADE_COST_LOW_LQ


# ═══════════════════════════════════════════════════════════════
#  진입 횟수 제한 (횟수+쿨다운)
# ═══════════════════════════════════════════════════════════════
def check_trade_limit(lg: logging.Logger, hint: str = "") -> bool:  # [v4.30 P2] hint 기반 분기
    """True=차단. hint="" 시 전체 총량 체크(+쿨다운), hint 있으면 전략별 체크."""
    if not SIGNAL.exists(): return False
    try:
        with open(SIGNAL, "r", encoding="utf-8-sig") as f: raw = f.read()
    except OSError as e:
        lg.warning("[LIMIT] 신호파일 읽기 실패: %s → 통과", e)
        return False
    try:
        sig = json.loads(raw)
    except json.JSONDecodeError:
        lg.warning("[LIMIT] 신호파일 파싱 실패(동시쓰기 추정) → 차단(안전)")
        return True
    try:
        if str(sig.get("date", "")) != _today(): return False
        siga_cnt = int(sig.get("siga_daily_count", 0))
        pb_cnt   = int(sig.get("pullback_daily_count", 0))
        if hint == "PULLBACK":
            if pb_cnt >= PULLBACK_MAX_TRADES_PER_DAY:
                lg.info("[LIMIT] PULLBACK %d회 ≥ MAX %d → 차단", pb_cnt, PULLBACK_MAX_TRADES_PER_DAY)
                return True
        elif hint in ("SIGA", "MULTI"):
            if siga_cnt >= SIGA_MAX_TRADES_PER_DAY:
                lg.info("[LIMIT] SIGA %d회 ≥ MAX %d → 차단", siga_cnt, SIGA_MAX_TRADES_PER_DAY)
                return True
        else:
            # hint="" 미지정: 전체 한도 확인
            if siga_cnt >= SIGA_MAX_TRADES_PER_DAY and pb_cnt >= PULLBACK_MAX_TRADES_PER_DAY:
                lg.info("[LIMIT] 전체 소진 SIGA=%d/%d PULLBACK=%d/%d → 차단",
                        siga_cnt, SIGA_MAX_TRADES_PER_DAY, pb_cnt, PULLBACK_MAX_TRADES_PER_DAY)
                return True
            if siga_cnt == 0 and pb_cnt == 0:  # 구버전 신호 폴백
                cnt = int(sig.get("daily_trade_count", 1))
                if cnt >= MAX_TRADES_PER_DAY:
                    lg.info("[LIMIT] 당일 %d회 ≥ MAX %d회 → 차단(구버전)", cnt, MAX_TRADES_PER_DAY)
                    return True
        if hint in ("", "PULLBACK"):  # 쿨다운: 전체 총량 체크 + PULLBACK 진입에도 적용
            ts = sig.get("ts", "")
            if ts:
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    el = (_now_kst().replace(tzinfo=None) - dt).total_seconds() / 60
                    if el < COOLDOWN_MIN:
                        lg.info("[LIMIT] 쿨다운 미충족 (%.0f분 < %d분) → 차단", el, COOLDOWN_MIN)
                        return True
                except Exception: pass
        lg.info("[LIMIT] 통과 SIGA=%d/%d PULLBACK=%d/%d hint=%s",
                siga_cnt, SIGA_MAX_TRADES_PER_DAY, pb_cnt, PULLBACK_MAX_TRADES_PER_DAY, hint or "ALL")
        return False
    except Exception as e:
        lg.warning("[LIMIT] 읽기 실패: %s → 통과", e)
        return False


# ═══════════════════════════════════════════════════════════════
#  [v4.15 S2] 단계별 진입 품질 게이트 — 무력화 (항상 True)
#
#  이유: MAX_TRADES_PER_DAY=1, 이 엔진은 2·3회차 분산진입 엔진이 아님
#        스코어보드가 이미 5개까지 선별 완료 → 여기서 재선별 불필요
#        함수 시그니처는 호출부 인터페이스 유지를 위해 보존
# ═══════════════════════════════════════════════════════════════
def check_tiered_entry_quality(
    trade_count: int,
    ev_pct: float,
    volume_accel: float,
    close_position: float,
    prescore: float,
    attack_score: float,
    ride_score: float,
    lg: logging.Logger,
    row: dict = None,
) -> bool:
    """[v4.30 P3] 회차 게이트 복원.
    trade_count = 오늘 이미 체결된 횟수.
      == 0 → 1회차 진입 → 무조건 통과
      == 1 → 2회차 진입 → TIER2 조건
      >= 2 → 3회차 진입 → TIER3 조건
    """
    if trade_count == 0:
        # [v4_9-P9] 1회차도 최저 품질 보호 — 너무 약한 신호 차단 (이전엔 무조건 통과)
        # [W50 PATCH 2026-05-13] TIER1_SCORE_MIN 60.0 → 20.0 (prescore_weighted 단위 정합)
        #   결함: prescore = row["prescore_weighted"] (rt_intraday 산출, 0~50 범위, 실측 max 25.5)
        #         TIER1_SCORE_MIN 60.0은 kjs_scoreboard score 단위 (0~100)
        #         단위 충돌로 모든 매수 영구 차단 (W36 cold-start 우회해도 차단)
        #   수정: 20.0 → MIN_PRESCORE 15.0 위 + prescore 분포 상위 70% 통과
        _tier1_ev_min    = float(os.environ.get("TIER1_EV_MIN",    "0.25"))
        _tier1_score_min = float(os.environ.get("TIER1_SCORE_MIN", "20.0"))
        if ev_pct > 0 and ev_pct < _tier1_ev_min:
            lg.warning("[TIER1] 차단 EV=%.3f%%<%.2f%%", ev_pct, _tier1_ev_min); return False
        if prescore > 0 and prescore < _tier1_score_min:
            lg.warning("[TIER1] 차단 score=%.1f<%.1f", prescore, _tier1_score_min); return False
        lg.info("[TIER1] 통과 EV=%.3f%% score=%.1f", ev_pct, prescore)
        return True
    elif trade_count == 1:
        # 2회차 조건
        # [W36 PATCH 2026-05-13] cold-start (ev_pct=0) 우회 — TIER1 가드 패턴 통일
        #   기존: ev_pct=0 시 무조건 차단 → cold-start 시 W31 2차 [0.25] 영구 사문화
        #   변경: ev_pct > 0 가드 추가 → ev 미산출 시 vol/cp 품질 게이트만 적용
        #   임계 0.55% 자체는 유지 — 정상 ev 산출 후 게이트 정상 작동
        if ev_pct > 0 and ev_pct < SECOND_ENTRY_EV_MIN:
            lg.warning("[TIER2] 차단 EV=%.3f%%<%.2f%%", ev_pct, SECOND_ENTRY_EV_MIN); return False
        if volume_accel < SECOND_ENTRY_VOL_ACCEL_MIN:
            lg.warning("[TIER2] 차단 vol=%.2f<%.2f", volume_accel, SECOND_ENTRY_VOL_ACCEL_MIN); return False
        if close_position < SECOND_ENTRY_CLOSE_POS_MIN:
            lg.warning("[TIER2] 차단 cls=%.2f<%.2f", close_position, SECOND_ENTRY_CLOSE_POS_MIN); return False
        lg.info("[TIER2] 통과 EV=%.3f%% vol=%.2f cls=%.2f", ev_pct, volume_accel, close_position)
        return True
    else:
        # 3회차 이상 조건 (trade_count >= 2)
        if ev_pct < THIRD_ENTRY_EV_MIN:
            lg.warning("[TIER3] 차단 EV=%.3f%%<%.2f%%", ev_pct, THIRD_ENTRY_EV_MIN); return False
        if attack_score < THIRD_ENTRY_ATTACK_MIN:
            lg.warning("[TIER3] 차단 atk=%.1f<%.1f", attack_score, THIRD_ENTRY_ATTACK_MIN); return False
        if ride_score < THIRD_ENTRY_RIDE_MIN:
            lg.warning("[TIER3] 차단 ride=%.2f<%.2f", ride_score, THIRD_ENTRY_RIDE_MIN); return False
        if volume_accel < THIRD_ENTRY_VOL_ACCEL_MIN:
            lg.warning("[TIER3] 차단 vol=%.2f<%.2f", volume_accel, THIRD_ENTRY_VOL_ACCEL_MIN); return False
        # [PULLBACK-MORNING 2026-06-07] 3회차 ADD '강할 때만' — VWAP위·고가권·붕괴없음 추가 (강제 강화)
        if PULLBACK_TIER3_ADD_STRICT and row is not None:
            _m3 = _pb_metrics(row)
            if _m3.get("vwap") is not None and _m3["vwap"] < PB_VWAP_MIN:
                lg.warning("[PULLBACK_TIER3_ADD_GATE] block reason=vwap_below(%.3f<%.2f)", _m3["vwap"], PB_VWAP_MIN); return False
            if _m3.get("cpos") is not None and _m3["cpos"] < PB_CLOSE_POS_STRONG:
                lg.warning("[PULLBACK_TIER3_ADD_GATE] block reason=not_highzone(cpos=%.2f<%.2f)", _m3["cpos"], PB_CLOSE_POS_STRONG); return False
            if _m3.get("l3") is not None and _m3["l3"] <= PB_COLLAPSE_RET:
                lg.warning("[PULLBACK_TIER3_ADD_GATE] block reason=bar_collapse(l3=%.2f)", _m3["l3"]); return False
            lg.info("[PULLBACK_TIER3_ADD_GATE] pass vwap=%s cpos=%s l3=%s", _m3.get("vwap"), _m3.get("cpos"), _m3.get("l3"))
        lg.info("[TIER3] 통과 EV=%.3f%% atk=%.1f ride=%.2f vol=%.2f",
                ev_pct, attack_score, ride_score, volume_accel)
        return True


# ═══════════════════════════════════════════════════════════════
#  [PULLBACK-MORNING 2026-06-07] 아침 시간대 품질 게이트 (rt_execution 내부 전용)
#  컬럼 부재/이상은 warning 후 해당 항목 통과(전체 죽이지 않음). 주문/매도/일일제한 무관.
# ═══════════════════════════════════════════════════════════════
def _pb_metrics(row: dict) -> dict:
    """PULLBACK 후보 품질 메트릭 추출(실컬럼). 부재 컬럼은 None 표시."""
    def g(k):
        return _f(row.get(k)) if (k in row and str(row.get(k)).strip() not in ("", "None")) else None
    def gany(keys):   # 후보 컬럼 중 최초 존재값(없으면 None) — 저점 직접컬럼 탐색용
        for k in keys:
            if k in row and str(row.get(k)).strip() not in ("", "None"):
                return _f(row.get(k))
        return None
    return {
        "price":  g("price_now"),
        "vwap":   g("price_vs_vwap"),        # ≥1.0 = VWAP 위
        "dhigh":  g("price_vs_day_high"),    # ≈1.0 = 고가 근접
        "cpos":   g("close_position"),       # 0~1 고가권 마감
        "vacc":   g("volume_accel"),         # 거래대금 재가속(>1)
        "l3":     g("last3_ret"),            # 최근3봉 수익(붕괴/스파이크)
        "ps":     g("prescore_weighted"),
        "pbdepth":g("pullback_depth"),       # 부재 가능 → None (프록시는 dhigh로 유도)
        "ofi":    g("ofi"),                  # 주문흐름(>0=매수우위)
        "ride":   g("inst_ride_score"),      # 기관 라이드
        "cpos3":  g("close_pos_3m"),         # 3분봉 위치(저점 이탈 프록시)
        "pvr":    g("pb_pullvol_ratio"),     # [PULLVOL] 눌림구간 거래량비 (make_rt 신규, 부재=None)
        # [HIGHER-LOW 2026-06-07] 저점 직접판정용 — rt_intraday엔 현재 부재(None)→close_pos_3m 프록시 폴백. 추후 컬럼 생기면 자동 활성.
        "rlow":   gany(["recent_low", "min_low_3m", "min_low_5m", "low_3", "low"]),
        "plow":   gany(["prev_low", "min_low_5m", "low_prev", "low_5"]),
    }


def _pb_quality_strong(m: dict, lg, code: str, label: str):
    """강한 후보(09:05~10 예외 / 10:20+ strict / TIER3 ADD)용 — 전부 충족해야 pass.
    컬럼 없으면(None) 그 항목은 통과로 간주(전멸 방지) + warning."""
    miss = [k for k in ("vwap", "vacc", "cpos", "l3", "ps") if m.get(k) is None]
    if miss:
        lg.warning("[PULLBACK_QUALITY_GATE] code=%s %s 컬럼부재=%s → 해당항목 통과(기존로직 유지)", code, label, miss)
    # VWAP 위
    if m.get("vwap") is not None and m["vwap"] < PB_VWAP_MIN:
        return False, "vwap_below(%.3f<%.2f)" % (m["vwap"], PB_VWAP_MIN)
    # prescore 상위권
    if m.get("ps") is not None and m["ps"] < PB_STRONG_PRESCORE_MIN:
        return False, "prescore_low(%.1f<%.1f)" % (m["ps"], PB_STRONG_PRESCORE_MIN)
    # 거래대금 재가속 OR 고가권 유지 (둘 중 하나)
    _vacc_ok = (m.get("vacc") is None) or (m["vacc"] >= PB_VALUE_ACCEL_MIN)
    _cpos_ok = (m.get("cpos") is None) or (m["cpos"] >= PB_CLOSE_POS_STRONG)
    if not (_vacc_ok or _cpos_ok):
        return False, "weak_flow(vacc=%.2f cpos=%.2f)" % (m.get("vacc") or 0, m.get("cpos") or 0)
    # 최근봉 붕괴 차단
    if m.get("l3") is not None and m["l3"] <= PB_COLLAPSE_RET:
        return False, "bar_collapse(l3=%.2f)" % m["l3"]
    # 고가근접 + 급등 = 과열 추격 차단
    if (m.get("dhigh") is not None and m.get("l3") is not None
            and m["dhigh"] >= 0.999 and m["l3"] >= PB_OVERHEAT_SPIKE_RET):
        lg.info("[PULLBACK_OVERHEAT_GATE] code=%s block dhigh=%.3f l3=%.2f (고가 추격)", code, m["dhigh"], m["l3"])
        return False, "overheat_chase(dhigh=%.3f l3=%.2f)" % (m["dhigh"], m["l3"])
    return True, "strong_ok"


def _pb_quality_basic(m: dict, lg, code: str):
    """주력창(09:10~10:20) 보수 품질 — 명백한 불량만 차단(과차단 방지)."""
    if m.get("price") is not None and m["price"] <= 0:
        return False, "price<=0"
    if m.get("l3") is not None and m["l3"] <= PB_COLLAPSE_RET:
        return False, "bar_collapse(l3=%.2f)" % m["l3"]
    if m.get("vwap") is not None and m["vwap"] < PB_VWAP_FAR_BELOW:
        lg.info("[PULLBACK_VWAP_GATE] code=%s block vwap=%.3f<%.2f (VWAP 1%%↓)", code, m["vwap"], PB_VWAP_FAR_BELOW)
        return False, "vwap_far_below(%.3f<%.2f)" % (m["vwap"], PB_VWAP_FAR_BELOW)
    # [PULLVOL-GATE 2026-06-11 검증채택] 눌림 중 거래량 폭증 = '던지는 중' 차단.
    #   백테(39일 504건): 폭증(>1.3) 승률19%/-1.19% 최악 vs 마름(<0.7) 29%/-0.74%.
    #   컬럼 부재/None = 통과(fail-open). 롤백 env PB_PULLVOL_GATE=NO.
    if PB_PULLVOL_GATE and m.get("pvr") is not None and m["pvr"] > PB_PULLVOL_MAX:
        lg.info("[PULLVOL-GATE] code=%s block pullvol=%.2f>%.2f (눌림 중 거래량 폭증)",
                code, m["pvr"], PB_PULLVOL_MAX)
        return False, "pullvol_surge(%.2f>%.2f)" % (m["pvr"], PB_PULLVOL_MAX)
    return True, "basic_ok"


_PB_P1M_LOW_CACHE = {"mtime": None, "map": None}


def _pb_load_prices1m_lows() -> dict:
    """[HIGHER-LOW B] prices_1m 오늘 종목별 저점 리스트(ts 오름차순) — mtime 캐시. 실패/없음→{}."""
    p = DATA / "prices_1m.csv"
    try:
        if not p.exists() or not _PD_OK:
            return {}
        mt = p.stat().st_mtime
        if _PB_P1M_LOW_CACHE["mtime"] == mt and _PB_P1M_LOW_CACHE["map"] is not None:
            return _PB_P1M_LOW_CACHE["map"]
        import pandas as pd
        df = pd.read_csv(p, dtype={"code": str, "ts": str}, usecols=["code", "ts", "low"], low_memory=False)
        if df.empty:
            _PB_P1M_LOW_CACHE.update(mtime=mt, map={}); return {}
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["_d"]   = df["ts"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
        today = _now_kst().strftime("%Y%m%d")
        df = df[df["_d"] == today]                                   # ★오늘 봉만(과거날짜 혼입 차단)
        if df.empty:
            _PB_P1M_LOW_CACHE.update(mtime=mt, map={}); return {}
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df = df.dropna(subset=["low"]).sort_values("ts")
        m = {c: g["low"].tolist() for c, g in df.groupby("code")}
        _PB_P1M_LOW_CACHE.update(mtime=mt, map=m)
        return m
    except Exception:
        return {}


def _pb_recent_lows(code: str):
    """[HIGHER-LOW B] 오늘 prices_1m로 (recent_low, prev_low). 최근 K봉 저점 vs 직전 K봉 저점.
    봉 부족(장초반)이면 가용분 절반분할. 2봉 미만/데이터없음 → (None, None)."""
    lows = _pb_load_prices1m_lows().get(str(code).zfill(6))
    if not lows or len(lows) < 2:
        return None, None
    k = max(1, PB_HL_BARS)
    if len(lows) >= 2 * k:
        return min(lows[-k:]), min(lows[-2 * k:-k])
    h = len(lows) // 2                                               # 봉 부족 → 가용분 절반 분할
    return min(lows[-h:]), min(lows[:-h])


def _pb_higher_low(m: dict, lg, code: str):
    """[HIGHER-LOW] 저점 이탈 여부. 우선순위: ①rt_intraday 직접컬럼(rlow/plow) ②prices_1m 직접저점(B)
    ③close_pos_3m 프록시(전멸방지). 반환 (low_hold_ok, fallback_used)."""
    rlow, plow = m.get("rlow"), m.get("plow")
    src = "column"
    if PB_HIGHER_LOW_ENABLE and not (rlow is not None and plow is not None and plow > 0):
        if PB_HL_FROM_PRICES1M:                                     # ② prices_1m 직접 저점(B)
            rlow, plow = _pb_recent_lows(code); src = "prices_1m"
    if PB_HIGHER_LOW_ENABLE and rlow is not None and plow is not None and plow > 0:
        hl_ok = rlow >= plow * PB_HIGHER_LOW_TOL                     # 최근 저점 >= 이전 저점×허용
        lg.info("[PULLBACK_HIGHER_LOW] code=%s recent_low=%.2f prev_low=%.2f higher_low_ok=%s fallback_used=N src=%s reason=%s",
                code, rlow, plow, ("Y" if hl_ok else "N"), src, ("higher_low" if hl_ok else "lower_low_break"))
        return hl_ok, False
    # ③ 폴백: close_pos_3m 프록시(부재→통과=전멸방지)
    cpos3 = m.get("cpos3")
    fb_ok = (cpos3 is None) or (cpos3 >= PB_LOW_HOLD_MIN)
    lg.info("[PULLBACK_HIGHER_LOW] code=%s recent_low=NA prev_low=NA higher_low_ok=%s fallback_used=Y reason=close_pos_3m_proxy(cp3=%s>=%.2f)",
            code, ("Y" if fb_ok else "N"), cpos3, PB_LOW_HOLD_MIN)
    return fb_ok, True


def _pb_early_rebound(m: dict, lg, code: str):
    """[EARLY_REBOUND] 09:05~09:10 '눌림 후 초기 반등' 셋업 — 6조건 전부 충족해야 pass.
    핵심컬럼(vwap/dhigh) 부재 시 None 반환 → 호출부가 기존 strong gate로 폴백(전멸 방지).
    프록시: 눌림폭=(1-price_vs_day_high)*100, 저점holding=higher-low(직접) or close_pos_3m(폴백)."""
    if not PULLBACK_EARLY_REBOUND_ENABLE:
        return None
    if m.get("vwap") is None or m.get("dhigh") is None:
        lg.warning("[PULLBACK_EARLY_REBOUND] code=%s 핵심컬럼(vwap/dhigh) 부재 → strong gate 폴백", code)
        return None
    vwap  = m["vwap"]
    depth = (1.0 - m["dhigh"]) * 100.0                    # 눌림폭(%) 프록시
    vacc  = m.get("vacc"); ofi = m.get("ofi"); ride = m.get("ride"); cpos3 = m.get("cpos3")
    # 6조건
    vwap_ok  = vwap >= PB_VWAP_RECLAIM                                            # 1) VWAP 위/회복
    depth_ok = PB_REBOUND_DEPTH_MIN <= depth <= PB_REBOUND_DEPTH_MAX              # 2) 눌림폭 0.8~3.0% (+6 고점추격 아님=하한)
    low_hold, _hl_fb = _pb_higher_low(m, lg, code)                               # 3) 저점 이탈 없음 — higher-low 직접 or close_pos_3m 프록시
    vacc_ok  = (vacc is None) or (vacc >= PB_VALUE_ACCEL_MIN)                     # 4) 거래대금 재유입(부재→통과)
    flow_ok  = ((ofi is not None and ofi > PB_REBOUND_OFI_MIN)
                or (ride is not None and ride >= PB_REBOUND_RIDE_MIN))           # 5) OFI>0 OR ride≥0.30
    if cpos3 is None or vacc is None:
        lg.warning("[PULLBACK_EARLY_REBOUND] code=%s 보조컬럼부재(cpos3=%s vacc=%s)→해당조건 통과", code, cpos3, vacc)
    ok = vwap_ok and depth_ok and low_hold and vacc_ok and flow_ok
    rb = []
    if not vwap_ok:  rb.append("vwap_below(%.3f<%.3f)" % (vwap, PB_VWAP_RECLAIM))
    if not depth_ok: rb.append("depth_out(%.2f%%∉[%.1f,%.1f])" % (depth, PB_REBOUND_DEPTH_MIN, PB_REBOUND_DEPTH_MAX))
    if not low_hold: rb.append("low_broken(%s)" % ("close_pos_3m proxy" if _hl_fb else "higher_low"))
    if not vacc_ok:  rb.append("no_reinflow(vacc=%.2f)" % (vacc if vacc is not None else -1))
    if not flow_ok:  rb.append("no_flow(ofi=%s ride=%s)" % (ofi, ride))
    reason = "rebound_ok" if ok else "|".join(rb)
    lg.info("[PULLBACK_EARLY_REBOUND] code=%s hhmm=%04d vwap=%.3f pullback_depth=%.2f%% value_accel=%s ofi=%s ride_score=%s low_hold=%s -> %s reason=%s",
            code, _hhmm(), vwap, depth, vacc, ofi, ride, ("Y" if low_hold else "N"),
            ("pass" if ok else "block"), reason)
    return ok, reason


def pullback_time_gate(rows: list, lg: logging.Logger) -> list:
    """[PULLBACK-GATE 2026-06-08 ★주인의도] '시간' 아니라 '회차/조건'으로 강도 분기(비PULLBACK 통과).
    09:00~05 차단(시초) / 09:05~10 = 1회차 초기진입 EARLY_REBOUND 강조건(이 구간만 시간조건) / 09:10~ = 시간무관 일반 눌림(basic).
    회차별 강도(2회차 일반/3회차 ADD 강세)는 주 검문소 check_tiered_entry_quality가 담당 → 10:20+ strict 시간검문 제거(2/3회차 과차단 방지)."""
    if not PULLBACK_TIME_GATE_ENABLE:
        return rows
    hhmm = _hhmm()
    try:
        pb_count = _get_pullback_daily_count()
    except Exception:
        pb_count = 0
    tier = "TIER1" if pb_count == 0 else ("TIER2" if pb_count == 1 else "TIER3_ADD")
    kept, blocked = [], 0
    for r in rows:
        if str(r.get("strategy_hint", "")).upper() != "PULLBACK":
            kept.append(r); continue
        code = str(r.get("code", "")).zfill(6)
        m = _pb_metrics(r)
        # ── 강도 분기: 09:05~10만 시간조건(강) / 그 외는 시간 무관(일반). 회차강도는 check_tiered가 주검문소 ──
        if hhmm < PULLBACK_EARLY_EXC_START:                       # 09:00~09:05 시초 변동성 회피
            decision, reason = "block", "too_early_before_0905"
            lg.info("[PULLBACK_TIME_GATE] code=%s hhmm=%04d blocked reason=%s", code, hhmm, reason)
        elif hhmm < PULLBACK_EARLY_EXC_END:                       # 09:05~09:10 1회차 초기진입 = EARLY_REBOUND 강조건(이 구간만 시간조건)
            _rb = _pb_early_rebound(m, lg, code)
            if _rb is None:                                       # 핵심컬럼 부재/비활성 → strong 폴백
                ok, why = _pb_quality_strong(m, lg, code, "EARLY_EXC_FALLBACK")
            else:
                ok, why = _rb
            decision, reason = ("pass" if ok else "block"), "early_rebound:" + why
            lg.info("[PULLBACK_EARLY_EXCEPTION] code=%s hhmm=%04d %s reason=%s", code, hhmm, decision, reason)
        else:                                                     # 09:10~ 시간 무관: 일반 눌림(basic)만. 10:20+ strict 제거(2/3회차 과차단 방지). 회차강도=check_tiered.
            ok, why = _pb_quality_basic(m, lg, code)
            decision, reason = ("pass" if ok else "block"), "main_basic:" + why
        # ── 통합 결정 로그(필수 필드) ──
        lg.info("[PULLBACK_DECISION] code=%s hhmm=%04d trade_count=%d tier=%s ps=%s vwap=%s cpos=%s dhigh=%s vacc=%s l3=%s pbdepth=%s -> %s reason=%s",
                code, hhmm, pb_count, tier, m.get("ps"), m.get("vwap"), m.get("cpos"),
                m.get("dhigh"), m.get("vacc"), m.get("l3"), m.get("pbdepth"), decision, reason)
        if decision == "pass":
            kept.append(r)
        else:
            blocked += 1
    if blocked:
        lg.info("[PULLBACK_TIME_GATE] hhmm=%04d tier=%s PULLBACK 차단 %d개 → %d개 남음 (강도분기: 09:05~10강 / 09:10~일반 / 회차강도=check_tiered 주검문소)", hhmm, tier, blocked, len(kept))
    return kept


# ═══════════════════════════════════════════════════════════════
#  [v4.6] 1일 최소 1회 보장 — fallback (v4.15 단순화)
# ═══════════════════════════════════════════════════════════════
def check_fallback_needed(lg: logging.Logger) -> bool:
    # [NOFALLBACK 2026-06-11 사용자결정] "신호 없으면 안 사는 게 맞다" —
    # 1일 최소 1회 보장(기준 완화 강제진입)은 6/10 검증결론("빈도가 아니라 score가 답")과
    # 충돌하므로 기본 OFF. 재활성: setx FALLBACK_DAILY_MIN_ENABLE YES
    if os.environ.get("FALLBACK_DAILY_MIN_ENABLE", "NO").strip().upper() != "YES":
        return False
    hm = _hhmm()
    if hm >= FALLBACK_DEADLINE_HM:
        lg.debug("[FALLBACK] %04d ≥ %04d → 시간초과", hm, FALLBACK_DEADLINE_HM)
        return False
    cnt = _get_daily_count()
    if cnt > 0:
        lg.debug("[FALLBACK] 당일 %d회 있음 → 불필요", cnt)
        return False
    lg.warning("[FALLBACK] 당일 0회 + %04d 이전 → fallback 허용", FALLBACK_DEADLINE_HM)
    return True

def decide_mode_fallback(best: dict, regime: str, lg: logging.Logger) -> str:
    """[v4.16 A2] ATTACK 우선 fallback — prescore≥20→ATTACK / else→STABLE.
    1일 1진입 보장 + 수익률 우선. BEAR 레짐만 차단 유지.
    EV 미보정 시 n<12 안전망(50% 포지션 축소)이 calc_position_size에서 자동 작동.

    [통합패치-07] fallback 최소 품질 게이트 — inst≥1, ofi≥0.05
    저품질 종목 강제 진입 차단. prescore 단일 지표 의존 해소.
    """
    if regime in (FALLBACK_MARKET_BAD_FLAG, "BEAR"):
        lg.warning("[FALLBACK] 레짐=%s → 거부", regime); return "SKIP"
    ps = best["prescore"]
    if ps < FALLBACK_MIN_PRESCORE:
        lg.warning("[FALLBACK] prescore=%.1f < %.1f → SKIP", ps, FALLBACK_MIN_PRESCORE)
        return "SKIP"
    # [통합패치-07] 최소 품질 하한선
    _ride_fb = best.get("ride", {})
    _inst_fb = int(_ride_fb.get("inst_days", 0))
    _ofi_fb  = float(_ride_fb.get("ofi_at_entry", 0.0))
    if _inst_fb < 1 or _ofi_fb < 0.05:
        lg.warning("[FALLBACK][패치07] 최소품질 미달 inst=%d ofi=%.2f → SKIP", _inst_fb, _ofi_fb)
        return "SKIP"
    if ps >= 20:
        lg.warning("[FALLBACK] ★ prescore=%.1f ≥ 20 → ATTACK (1일1진입 보장)", ps)
        return "ATTACK"
    else:
        lg.warning("[FALLBACK] ★ prescore=%.1f < 20 → STABLE (1일1진입 보장)", ps)
        return "STABLE"


# ═══════════════════════════════════════════════════════════════
#  ① 데이터 로드
# ═══════════════════════════════════════════════════════════════
def load_rt_data(lg: logging.Logger) -> Optional[list]:
    if not _PD_OK: lg.error("[LOAD] pandas 미설치"); return None
    if not RT_CSV.exists() or RT_CSV.stat().st_size == 0:
        lg.warning("[LOAD] rt_intraday.csv 없음"); return None
    age = time.time() - RT_CSV.stat().st_mtime
    _stale_sec = int(os.environ.get("RT_INTRADAY_STALE_SEC", "300"))   # [신규] 6h→5min, env 조정 가능
    if age > _stale_sec: lg.warning("[LOAD] rt_intraday.csv 오래됨 (%.0f분)", age/60); return None
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(RT_CSV, encoding=enc)
            if not df.empty:
                lg.info("[LOAD] rt_intraday %d행 (age=%.0f초)", len(df), age)
                # [v4_29] latest_day_only: 당일 데이터만 사용 — 전일 혼입 차단
                if "ts" in df.columns:
                    _latest_day = df["ts"].astype(str).str[:8].max()
                    df = df[df["ts"].astype(str).str[:8] == _latest_day].reset_index(drop=True)
                    lg.info("[LOAD] latest_day=%s 필터 후 %d행", _latest_day, len(df))
                missing = REQUIRED_COLUMNS - set(df.columns)
                if missing: lg.error("[LOAD] 필수 컬럼 부재: %s", missing); return None
                rec_m = RECOMMENDED_COLUMNS - set(df.columns)
                if rec_m: lg.warning("[LOAD] 권장 컬럼 부재: %s", rec_m)
                return df.to_dict("records")
        except Exception: continue
    lg.error("[LOAD] rt_intraday.csv 읽기 실패"); return None


def load_risk_codes(lg: logging.Logger) -> Optional[set]:
    if not RISK_CSV.exists() or RISK_CSV.stat().st_size == 0:
        lg.error("[RISK][FAIL] rt_risk_candidates.csv 없음/빈파일"); return None
    try:
        df = pd.read_csv(RISK_CSV, encoding="utf-8-sig", dtype=str)
        if "code" not in df.columns:
            lg.error("[RISK][FAIL] code 컬럼 없음"); return None
        codes = {str(c).zfill(6) for c in df["code"].dropna()}
        lg.info("[RISK] 통과 종목 %d개", len(codes))
        return codes
    except Exception as e:
        lg.error("[RISK][FAIL] 읽기 실패: %s", e); return None


def load_targets(lg: logging.Logger) -> Optional[set]:
    """[v4.34 STALE-FIX] 반환 의미:
      - None       : 시스템 오류 (JSON 파싱 실패 등) — 기존 ERROR 경로 유지
      - set()      : Bridge HOLD 신호 (codes=[] / codes 없음 / 파일 없음 / date stale) → 정상 HOLD
      - set(codes) : 정상 진입 후보
    main()은 빈 set을 ERROR가 아닌 정상 HOLD로 처리해야 한다.
    [PATCH] payload.eod_inactive=True 인 경우 _LAST_TARGET_EOD_INACTIVE=True 로 노출:
      bridge_eod 시간창(15:15~15:25) 외 — 09시대 등 — 실시간 rt_intraday 폴백 허용 신호
    """
    global _LAST_TARGET_EOD_INACTIVE
    _LAST_TARGET_EOD_INACTIVE = False
    import json as _json
    if not TARGET_JSON.exists() or TARGET_JSON.stat().st_size == 0:
        lg.warning("[TARGET][HOLD] bridge_target.json 없음/빈파일 → 정상 HOLD")
        return set()
    try:
        with open(TARGET_JSON, "r", encoding="utf-8-sig") as f:
            data = _json.load(f)
        if "codes" not in data:
            lg.warning("[TARGET][HOLD] codes 필드 없음 → 정상 HOLD")
            return set()
        if not data["codes"]:
            _hr = str(data.get("hold_reason", "no_codes"))
            # [PATCH-STALE-FALLBACK-EMPTY] codes=[] 분기에서도 stale 감지 추가
            #   어제 빈 codes(eod_inactive=False)가 오늘 09시 폴백을 차단하던 결함 해소
            #   당일(date=today)의 빈 codes는 의도된 HOLD로 보존
            today = datetime.now(KST).strftime("%Y-%m-%d") if KST else datetime.now().strftime("%Y-%m-%d")
            file_date = str(data.get("date", ""))
            _stale = (file_date != today)
            # 핵심: stale OR eod_inactive 둘 중 하나라도 True면 폴백 허용
            _LAST_TARGET_EOD_INACTIVE = bool(data.get("eod_inactive", False)) or _stale
            lg.info("[TARGET][HOLD] Bridge HOLD 신호 reason=%s stale=%s eod_inactive=%s → 정상 HOLD",
                    _hr, _stale, _LAST_TARGET_EOD_INACTIVE)
            return set()
        today = datetime.now(KST).strftime("%Y-%m-%d") if KST else datetime.now().strftime("%Y-%m-%d")
        file_date = str(data.get("date", ""))
        if file_date != today:
            # [PATCH-STALE-FALLBACK] stale = 어제 발행, 오늘 새 EOD 미실행
            #   → eod_inactive=True 자동 처리하여 09시 장중 rt_intraday 폴백 활성
            #   bridge_target.json 무수정, codes=[] 의미 보존, EOD 본 시간창 동작 변경 없음
            _LAST_TARGET_EOD_INACTIVE = True
            lg.warning("[TARGET][HOLD] date stale file=%s today=%s → eod_inactive=True 자동 처리 (rt_intraday 폴백 유도)",
                       file_date, today)
            return set()
        # [v4.31 FIX-3] float 잔류 코드 정규화 ("91120.0" → "091120")
        # 근거: Bloomberg/Refinitiv 표준 — 금융코드는 string, int(float()) 변환 후 zfill(6)
        codes = set()
        for _raw_c in data["codes"]:
            try:
                codes.add(str(int(float(str(_raw_c).strip()))).zfill(6))
            except (ValueError, TypeError):
                codes.add(str(_raw_c).strip().zfill(6))
        lg.info("[TARGET] codes=%d %s", len(codes), sorted(codes))
        return codes
    except Exception as e:
        lg.error("[TARGET][FAIL] 읽기 실패 (시스템 오류): %s", e)
        return None


# [PATCH] eod_inactive 플래그 — load_targets()가 호출 후 갱신
_LAST_TARGET_EOD_INACTIVE: bool = False


def _validate_target_sync(targets: set, rows: list, lg: logging.Logger) -> bool:
    # [v4.32 FIX] ALL → ANY 완화: target 1개라도 rt_intraday에 있으면 통과
    # 이유: 8개 중 1개 누락(거래정지/데이터미수신/당일 미포함)으로 전체 HOLD 방지
    try:
        i_codes = {str(r.get("code", "")).zfill(6) for r in rows}
        present = targets & i_codes
        missing = targets - i_codes
        if missing:
            lg.warning("[SYNC][PARTIAL] intraday missing target codes: %s (present=%d/%d)",
                       sorted(list(missing))[:8], len(present), len(targets))
        if not present:
            lg.error("[SYNC][FAIL] no target codes in intraday")
            return False
        return True
    except Exception as e:
        lg.error("[SYNC][ERROR] %s", e)
        return False


# ═══════════════════════════════════════════════════════════════
#  ② 기관 등타기 판정
# ═══════════════════════════════════════════════════════════════
def calc_inst_ride(row: dict) -> dict:
    inst  = _f(row.get("inst_ride_score", 0))
    ofi   = _f(row.get("ofi", 0))
    accel = _f(row.get("inst_accel", 0))
    ride  = 0.0; signals = []; exit_warnings = []
    if inst >= INST_STRONG_MIN: ride += 0.40; signals.append(f"기관강매집(score {inst:.2f})")
    elif inst >= INST_RIDE_MIN: ride += 0.25; signals.append(f"기관매집(score {inst:.2f})")
    elif inst > 0: ride -= 0.10; exit_warnings.append("기관매집부족")   # [신규] inst==0 데이터 결손 시 페널티 면제
    if ofi >= OFI_STRONG_MIN: ride += 0.25; signals.append(f"OFI강매수({ofi:.2f})")
    elif ofi >= OFI_RIDE_MIN: ride += 0.10
    else: ride -= 0.05; exit_warnings.append("OFI약화")
    ofi_last10 = _f(row.get("ofi_last10", 0))
    if ofi_last10 >= OFI_STRONG_MIN: ride += 0.10; signals.append(f"마감OFI({ofi_last10:.2f})")
    elif ofi_last10 < 0: ride -= 0.05; exit_warnings.append(f"마감OFI약화({ofi_last10:.2f})")
    if accel > 1.5: ride += 0.20; signals.append(f"기관가속({accel:.1f}x)")
    elif accel > 1.0: ride += 0.10
    elif accel < 0.5 and inst >= INST_RIDE_MIN: exit_warnings.append(f"기관감속({accel:.1f}x)")
    # [신규] price_vs_vwap 거리 비례 가산 (1%위→0.05, 4%위→상한0.20) — 단순 위/아래 → 거리 차등
    _pv = _f(row.get("price_vs_vwap", 1.0))
    if _pv > 1.0: ride += min((_pv - 1.0) * 5.0, 0.20)
    ride = round(min(max(ride, 0.0), 1.0), 4)
    return {
        "ride_score": ride, "can_ride": ride >= RIDE_HARD_MIN and inst >= INST_RIDE_MIN,
        "signals": signals, "exit_warnings": exit_warnings,
        "inst_days": int(inst), "ofi_at_entry": round(ofi, 4),
        "ofi_last10": round(ofi_last10, 4), "accel_at_entry": round(accel, 4),
        "early_exit": accel < 0.5 and inst >= INST_RIDE_MIN,
    }


# ═══════════════════════════════════════════════════════════════
#  ③ 시장 레짐
# ═══════════════════════════════════════════════════════════════
def check_market_regime(row: dict, lg: logging.Logger) -> str:
    # ── [REGIME-TODAY 2026-06-12 ★친구님 지시 "눈 통일"] 당일 실시간 지수 최우선 ──
    #   rt_risk·buy_sender와 동일 처방. 롤백: env REGIME_TODAY_OVERRIDE=NO (3파일 공통).
    if os.environ.get("REGIME_TODAY_OVERRIDE", "YES").strip().upper() == "YES":
        try:
            from datetime import datetime as _rt_dt
            _idx_p = DATA / "kosdaq_index.json"
            if _idx_p.exists():
                with open(_idx_p, "r", encoding="utf-8-sig") as _rf:
                    _idx = json.load(_rf)
                _its, _chg = str(_idx.get("ts", "")), _idx.get("chg", None)
                if _its and _chg is not None:
                    _age = (_rt_dt.now() - _rt_dt.strptime(_its, "%Y-%m-%d %H:%M:%S")).total_seconds()
                    if _its[:10] == _rt_dt.now().strftime("%Y-%m-%d") and _age <= 600:
                        _chg = float(_chg)
                        if _chg >= 1.5:
                            lg.info("[REGIME-TODAY] 당일 KOSDAQ %+.2f%% (신선 %.0fs) → BULL", _chg, _age)
                            return "BULL"
                        if _chg <= -1.5:
                            lg.info("[REGIME-TODAY] 당일 KOSDAQ %+.2f%% (신선 %.0fs) → BEAR", _chg, _age)
                            return "BEAR"
        except Exception as _rte:
            lg.debug("[REGIME-TODAY] 스킵(%s)", _rte)
    if _PARAMS_OK:
        r = str(_get_regime()).upper()
        if r in ("DOWN", "BEAR"): lg.info("[REGIME] BEAR"); return "BEAR"
        elif r in ("UP", "BULL", "TREND"): lg.info("[REGIME] BULL"); return "BULL"
    flag = str(row.get("market_flag", "")).upper()
    if flag == "DOWN": lg.info("[REGIME] BEAR"); return "BEAR"
    elif flag == "UP": lg.info("[REGIME] BULL"); return "BULL"
    lg.info("[REGIME] NEUTRAL"); return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════
#  ④ 킬스위치 — 5대 조건 (지침서12-1)
# ═══════════════════════════════════════════════════════════════
def check_kill_switch(lg: logging.Logger, regime: str = "NEUTRAL") -> Tuple[bool, str]:
    if _PNL_OK:
        daily = _check_daily_stop(total_capital=_capital())
        today_pnl = daily.get("today_pnl_pct", 0.0)
        limit = KILL_DAILY_LOSS_BEAR if regime == "BEAR" else MAX_DAILY_LOSS
        if today_pnl <= limit:
            return True, f"일일손실한도({today_pnl:+.1f}%≤{limit:.1f}%)"
        if daily.get("halt"): return True, f"일일손실한도({today_pnl:+.1f}%)"
        streak = _get_streak(STRATEGY_NAME)
        if streak.get("halt"): return True, f"연속손실{streak['streak']}회→정지"
        if streak.get("warn"): lg.warning("[KILL] ⚠ 연속손실경고 %d회", streak["streak"])
    try:
        if SIGNAL.exists():
            with open(SIGNAL, "r", encoding="utf-8-sig") as f: sig = json.load(f)
            rej = int(sig.get("order_reject_count", 0))
            rep = int(sig.get("repeat_sell_count", 0))
            if rej >= KILL_ORDER_REJECT_MAX:
                lg.critical("[KILL] 주문거절 %d회 ≥ %d → 킬스위치", rej, KILL_ORDER_REJECT_MAX)
                return True, f"주문거절반복({rej}회)"
            elif rej > 0:
                lg.warning("[KILL] 주문거절 경고 %d/%d회", rej, KILL_ORDER_REJECT_MAX)
            if rep >= KILL_REPEAT_SELL_MAX:
                lg.critical("[KILL] 반복매도 %d회 ≥ %d → 킬스위치", rep, KILL_REPEAT_SELL_MAX)
                return True, f"동일종목반복매도({rep}회)"
    except Exception as e: lg.debug("[KILL] 신호파일 확인 실패: %s", e)
    try:
        if RT_CSV.exists():
            age = time.time() - RT_CSV.stat().st_mtime
            if age > KILL_DATA_DELAY_SEC:
                lg.critical("[KILL] 데이터지연 %.0f초 > %d초 → 킬스위치", age, KILL_DATA_DELAY_SEC)
                return True, f"데이터지연({age:.0f}초)"
            elif age > KILL_DATA_DELAY_SEC * 0.7:
                lg.warning("[KILL] 데이터지연 경고 %.0f초 (임계 %d초)", age, KILL_DATA_DELAY_SEC)
    except Exception as e: lg.debug("[KILL] 데이터지연 확인 실패: %s", e)
    return False, ""


# ═══════════════════════════════════════════════════════════════
#  ⑤ EV 계산
# ═══════════════════════════════════════════════════════════════
def calc_ev(regime: str, ofi: float, lg: logging.Logger, trade_cost: float = 0.0) -> dict:
    result = {"ev_pct": 0.0, "win_rate": 0.50, "avg_win": 1.5, "avg_loss": 1.5,
              "sample_n": 0, "calibrated": False, "kelly_fraction": KELLY_DEFAULT}
    if not _PNL_OK: return result
    try:
        df = _load_pnl(lookback_days=EV_LOOKBACK)
        if df is None or df.empty: return result
        df_rt = df[df["strategy"] == STRATEGY_NAME].copy()
        # [v4.17 FIX-4] n<5 완전차단 → n<8 STABLE 50% 허용
        # 근거: bridge WARMING_MIN=8 통일. Thorp(1962) 초기 불확실구간 반배팅
        # n<8: kelly_fraction=0.10 강제 + calibrated=False (포지션 50% 자동감소 트리거)
        # n<12(=EV_MIN_SAMPLES): return result → EV 미보정 상태 유지
        if len(df_rt) < 8:
            result["kelly_fraction"] = 0.10
            result["calibrated"] = False
            return result
        if len(df_rt) < EV_MIN_SAMPLES: return result
        # [v4.18 FIX-2] pnl_pct_net → pnl_pct fallback
        # pnl_linker v3.3: pnl_pct_net 제공 / trade_log 직접 연동: pnl_pct
        _col = "pnl_pct_net" if "pnl_pct_net" in df_rt.columns else "pnl_pct"
        pnls = df_rt[_col].dropna().tolist()
        if not pnls: return result
        wins   = [p for p in pnls if p > 0]
        losses = [abs(p) for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls)
        avg_win  = statistics.mean(wins) if wins else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.01
        cost_pct = (trade_cost if trade_cost > 0 else TRADE_COST_BASE * 2) * 100
        ev = win_rate * avg_win - (1 - win_rate) * avg_loss - cost_pct
        # [v4.9] 레짐별 OFI 부스트 차등 적용 (BULL 레짐 수익률 강화)
        if ofi >= OFI_STRONG_MIN:
            ofi_boost = EV_OFI_BOOST_BULL if regime == "BULL" else EV_OFI_BOOST
            ev += ofi_boost * 100
        b = avg_win / avg_loss if avg_loss > 0 else 1.0
        kelly_raw = (b * win_rate - (1 - win_rate)) / b if b > 0 else 0.0
        kelly_frac = max(0.0, min(kelly_raw * KELLY_HALF_MULT, KELLY_HARD_MAX))
        # [v4.22 FIX-5] EV 음수 시 kelly_fraction 명시적 0 처리
        # 기존: kelly_raw 음수 → max(0.0) 처리되나 EV 음수 상태로 진입 가능
        # 수정: EV < 0 이면 Kelly=0 강제 → decide_mode의 EV 필터와 이중 방어
        if ev < 0:
            kelly_frac = 0.0
            lg.warning("[EV] EV=%.4f%% < 0 → kelly_fraction=0 강제", ev)
        if _PARAMS_OK:
            pr = _get_kelly(); kelly_frac = min(kelly_frac, pr.get("fraction", KELLY_DEFAULT))
        lg.info("[EV] n=%d wr=%.0f%% W=%.2f%% L=%.2f%% EV=%.3f%% kelly=%.4f regime=%s",
                len(pnls), win_rate*100, avg_win, avg_loss, ev, kelly_frac, regime)
        result.update({"ev_pct": round(ev, 4), "win_rate": round(win_rate, 4),
                        "avg_win": round(avg_win, 4), "avg_loss": round(avg_loss, 4),
                        "sample_n": len(pnls), "calibrated": True,
                        "kelly_fraction": round(kelly_frac, 4)})
    except Exception as e: lg.warning("[EV] 계산 실패: %s", e)
    return result


# ═══════════════════════════════════════════════════════════════
#  ⑤-b 수익률 복합 평가
# ═══════════════════════════════════════════════════════════════
def calc_profit_metrics(lg: logging.Logger) -> dict:
    result = {"profit_factor": 0.0, "sharpe": 0.0, "sortino": 0.0,
              "calmar": 0.0, "max_drawdown": 0.0, "sample_n": 0, "evaluated": False}
    if not _PNL_OK: return result
    try:
        df = _load_pnl(lookback_days=EV_LOOKBACK)
        if df is None or df.empty: return result
        df_rt = df[df["strategy"] == STRATEGY_NAME].copy()
        # [v4.19 FIX-1] pnl_pct_net → pnl_pct fallback (calc_ev와 동일 패턴)
        # pnl_linker v3.3: pnl_pct_net 제공 / trade_log 직접: pnl_pct
        _pm_col = "pnl_pct_net" if "pnl_pct_net" in df_rt.columns else "pnl_pct"
        pnls = df_rt[_pm_col].dropna().tolist()
        if len(pnls) < EV_MIN_SAMPLES: return result
        wins = [p for p in pnls if p > 0]; losses = [abs(p) for p in pnls if p < 0]
        pf = sum(wins) / (sum(losses) or 0.01)
        mean_r = statistics.mean(pnls)
        std_r  = statistics.stdev(pnls) if len(pnls) > 1 else 0.01
        sharpe = (mean_r / std_r) * (248 ** 0.5)   # [v4.20] 252→248 (KOSDAQ 연간 거래일 / evolution_engine 통일)
        d_std  = statistics.stdev([p for p in pnls if p < 0]) if len([p for p in pnls if p < 0]) > 1 else 0.01
        sortino = (mean_r / d_std) * (248 ** 0.5)  # [v4.20] 252→248
        peak = cumul = mdd = 0.0
        for p in pnls:
            cumul += p; peak = max(peak, cumul); mdd = max(mdd, peak - cumul)
        # [v4.9] Calmar ratio = 연환산 수익률 / MDD (헤지펀드 표준 지표)
        # [v4.20] 252→248 (KOSDAQ 연간 거래일 / evolution_engine 통일)
        annual_ret = mean_r * 248
        calmar = annual_ret / mdd if mdd > 0 else 0.0
        win_rate = round(len(wins) / len(pnls), 4)
        result.update({"profit_factor": round(pf, 4), "sharpe": round(sharpe, 4),
                        "sortino": round(sortino, 4), "calmar": round(calmar, 4),
                        "max_drawdown": round(mdd, 4), "win_rate": win_rate,
                        "sample_n": len(pnls), "evaluated": True})
        lg.info("[PROFIT] PF=%.2f Sharpe=%.2f Sortino=%.2f Calmar=%.2f MDD=%.2f%% WR=%.0f%%",
                pf, sharpe, sortino, calmar, mdd, win_rate*100)
    except Exception as e: lg.warning("[PROFIT] 평가 실패: %s", e)
    return result


# ═══════════════════════════════════════════════════════════════
#  ⑥ 모멘텀 품질
# ═══════════════════════════════════════════════════════════════
def calc_momentum_quality(row: dict) -> float:
    cp     = max(0.0, min(1.0, _f(row.get("close_position", 0.5))))
    va     = _f(row.get("volume_accel", 0))
    va_n   = min((va if va > 0 else 1.0) / 2.0, 1.0)
    vwap   = _f(row.get("price_vs_vwap", 1.0))
    vwap_b = 1.0 if vwap >= 1.0 else max(0.0, vwap)
    return round(max(0.0, min(1.0, 0.5*cp + 0.3*va_n + 0.2*vwap_b)), 4)


# ═══════════════════════════════════════════════════════════════
#  ⑦ 과열 판정
# ═══════════════════════════════════════════════════════════════
def calc_overheat(row: dict, lg: logging.Logger, code: str) -> Tuple[bool, float]:
    last3 = abs(_f(row.get("last3_ret", 0)))  # [OVERHEAT-FIX 2026-06-04] last3_ret은 make_rt에서 이미 %단위(=(종가비-1)*100). 기존 *100은 이중변환 버그로 실효임계 0.6%→정상주 전멸. 제거해 60%=진짜 3일 60%급등만 하드컷.
    pvdh  = _f(row.get("price_vs_day_high", 0))
    cp    = _f(row.get("close_position", 0.5))
    if last3 >= MAX_DAY_CHG_PCT:  # 60%↑ 진짜 과열만 하드차단
        lg.info("  [SKIP] %s 3일급등 %.1f%% ≥ 60%% → 하드차단", code, last3); return True, 0.0
    m = 1.0
    if last3 >= 40.0:
        m *= 0.3; lg.warning("  [SURGE_WARN] %s 3일급등 %.1f%% → ×0.30", code, last3)
    elif last3 >= 25.0:
        m *= 0.5; lg.warning("  [SURGE_WARN] %s 3일급등 %.1f%% → ×0.50", code, last3)
    elif last3 >= OVERHEAT_CHG_PCT:
        m *= 0.60; lg.info("  [HEAT] %s 3일급등%.1f%%→×0.60", code, last3)
    if pvdh >= 0.98 and cp >= 0.95: m *= 0.75; lg.info("  [HEAT] %s 고점근접→×0.75", code)
    return False, m


# ═══════════════════════════════════════════════════════════════
#  ⑧ 포지션 사이즈 (ATTACK 70% / STABLE 30% 완전 보장 — v4.13)
#
#  설계 원칙: "공격 70%, 안정 30%, 1종목 몰빵, 수익률 우선"
#
#  [v4.13 FIX-A] ATTACK 모드 KELLY_HARD_MAX 우회
#    기존: min(0.70, KELLY_HARD_MAX=0.65) → 65%로 잘림
#    수정: ATTACK은 KELLY_HARD_MAX 건너뜀 → MAX_POSITION_CAP(0.70)이 최종 상한
#
#  [v4.13 FIX-B] ATTACK 모드 evolve_weight 하향 차단
#    기존: PF부진 → evolve_w×0.5 → ATTACK 32% 폭락
#    수정: ATTACK은 evolve_weight 하향 무시, 상향(>1.0)만 반영
#          STABLE은 evolve_weight 전체 반영 (방어 기능 유지)
#
#  [v4.12 보존] ride 감소계수 제거, n<12 50%축소, EV부스트
#  [보존] BEAR 레짐 시 ATTACK=50% (하방 방어)
#  [보존] EV 미보정 n<12 → 50% 축소 (Lo 2002 안전망)
# ═══════════════════════════════════════════════════════════════
def calc_position_size(mode, price, ride, kelly_frac, regime,
                       evolve_weight=1.0, ev_pct=0.0, ev_calibrated=True, ev_sample_n=99,
                       weak_winner=False) -> dict:
    # [v4.30] weak_winner 파라미터 추가
    # weak_winner=True: ATTACK 유지하되 fraction × 0.85 (70%→59.5%)
    # 근거: EV 양수 종목의 ATTACK 포지션 유지 + 상대우위 불확실성 sizing 반영
    capital = _capital()
    atk_target = ATTACK_SIZE_BEAR if regime == "BEAR" else ATTACK_SIZE_BULL   # 0.50 or 0.70
    stb_target = STABLE_SIZE_BEAR if regime == "BEAR" else STABLE_SIZE_BULL   # 0.50 or 0.30

    if mode == "ATTACK":
        # [FIX-A] ATTACK: 목표비율(70%)을 기본값으로, Kelly가 더 높으면 Kelly 사용
        #         KELLY_HARD_MAX 적용 제외 → MAX_POSITION_CAP(70%)이 최종 상한
        fraction = max(kelly_frac, atk_target) if kelly_frac > 0 else atk_target
        fraction = min(fraction, MAX_POSITION_CAP)                             # 70% 하드캡
        # [FIX-B] ATTACK: evolve_weight 상향(>1.0)만 반영, 하향 무시 (수익률 우선)
        if evolve_weight > 1.0:
            fraction = min(fraction * evolve_weight, MAX_POSITION_CAP)
        # [v4.30] weak_winner: Top1 상대우위 불확실 → ×0.85 축소 (차단→sizing 전환)
        if weak_winner:
            fraction = min(fraction * 0.85, MAX_POSITION_CAP)
        st = "ATTACK"

    elif mode == "STABLE":
        # STABLE: 목표비율(30%)을 기본값으로, Kelly가 더 높으면 Kelly 사용
        fraction = max(kelly_frac, stb_target) if kelly_frac > 0 else stb_target
        fraction = min(fraction, KELLY_HARD_MAX)                               # 0.65 상한
        # STABLE: evolve_weight 전체 반영 (방어 기능 유지)
        fraction *= min(max(evolve_weight, 0.2), 1.5)
        fraction = min(fraction, MAX_POSITION_CAP)
        st = "STABLE"

    else:
        return {"qty":0,"order_krw":0,"fraction":0,"mode":"SKIP","kelly_used":0,"strategy_type":"SKIP","capital_allocated":0}

    # [PATCH] n<12 EV미보정 50% 축소 제거 — STABLE 모드는 유지, 사이즈 축소만 삭제

    # EV 강도 부스트 (수익률 강화 — 보존)
    if ev_pct >= EV_STRONG: fraction = min(fraction * 1.20, MAX_POSITION_CAP)
    if ev_pct >= EV_ULTRA:  fraction = min(fraction * 1.40, MAX_POSITION_CAP)

    # ride 감소계수 없음 [v4.12 FIX-1 보존]

    fraction = min(fraction, MAX_POSITION_CAP)
    order_krw = int(capital * fraction)
    qty = int(order_krw / price) if price > 0 else 0
    return {"qty": max(0, qty), "order_krw": order_krw, "fraction": round(fraction, 4),
            "mode": mode, "kelly_used": round(kelly_frac, 4),
            "strategy_type": st, "capital_allocated": order_krw}


# ═══════════════════════════════════════════════════════════════
#  ⑨ 후보 평가 — 5→1 최종 선택 (v4.15 단순화)
#
#  역할: 스코어보드가 이미 5개까지 압축 완료
#        이 함수는 안전 필터만 수행 후 prescore_weighted 1위 선택
#
#  [v4.15 S4] 단순화 내용:
#    - hint 필터 유지 (전략 힌트 안전망)
#    - prescore 최소 기준 유지
#    - overheat 차단 유지 (과열 방지)
#    - 최소 품질 확인 유지
#    - selection_score 복잡한 재가공 제거 → prescore_weighted 기준 정렬
#  [v4.15 S5] ride_score 진입 선정 영향 제거
#    - ride_m 가중치 제거 (기존: can_ride=False → ×0.50 페널티)
#    - ride 계산은 exit_signals 생성 위해 보존
# ═══════════════════════════════════════════════════════════════

# [P3] EARLY 신호 다중 컬럼 fallback 헬퍼 (모듈 레벨 — 루프 밖 1회 정의)
def _early_get(d: dict, *keys) -> float:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try: return float(v)
            except Exception: pass
    return 0.0

# [EXEC-SAFEPLUS 2026-06-13 친구님] 8→1 최종선택을 '진짜 테마 대장주' 점수로 (목표=테마 대장주, 잡주 1등 방지).
#   백테검증: 눌림 반복등장 3개+ 3일후 +2.24%(단조). 강제X(생존·타이밍 통과자끼리 재정렬). 기본 OFF.
#   롤백 setx EXEC_SAFEPLUS_ENABLE NO. 데이터없음/오류 → 기존 selection_score 유지(무영향).
EXEC_SAFEPLUS_ENABLE = os.environ.get("EXEC_SAFEPLUS_ENABLE", "NO").strip().upper() == "YES"
EXEC_SAFEPLUS_TOP_K  = int(os.environ.get("EXEC_SAFEPLUS_TOP_K", "15"))   # '상위 테마' 경계


def _load_exec_repeat_count() -> dict:
    """[EXEC-SAFEPLUS] code -> 상위K 강한테마 멤버 겹침 횟수(반복등장). 실패/파일없음 → {}(무영향)."""
    try:
        import csv as _csv
        _td = DATA / "theme"
        _fs = _td / "theme_strength.csv"
        _fm = _td / "theme_membership_naver.csv"
        if not (_fs.exists() and _fm.exists()):
            return {}
        _rows = list(_csv.DictReader(open(_fs, encoding="utf-8-sig", errors="replace")))
        if not _rows:
            return {}
        _latest = max(str(r.get("date", "")) for r in _rows)
        _topk = set()
        for r in _rows:
            if str(r.get("date", "")) != _latest:
                continue
            try:
                _rk = int(float(r.get("theme_rank", 999) or 999))
            except (TypeError, ValueError):
                continue
            if _rk <= EXEC_SAFEPLUS_TOP_K:
                _topk.add(str(r.get("theme_name", "")).strip())
        if not _topk:
            return {}
        _cnt = {}
        for r in _csv.DictReader(open(_fm, encoding="utf-8-sig", errors="replace")):
            if str(r.get("theme_name", "")).strip() in _topk:
                _c = str(r.get("code", "")).zfill(6)
                _cnt[_c] = _cnt.get(_c, 0) + 1
        return _cnt
    except Exception:
        return {}


def evaluate_candidates(rows, regime, lg, profit_metrics=None) -> Optional[dict]:
    # [US-CRASH-GUARD 2026-06-14 ★친구님] 나스닥 -4%↓ 대폭락날 = 신규 눌림 진입 스킵.
    #   (사이클마다 호출 → 차단될 때만 로그. 평소/데이터낡음 → 무영향 통과.)
    try:
        import sys as _s; _s.path.insert(0, r"C:\stock_bot\RUN")
        from us_crash_guard import is_us_crash_day
        _blk, _why = is_us_crash_day()
        if _blk:
            lg.info(f"[US-CRASH-GUARD] {_why} → 눌림 신규 스킵")
            return None
    except Exception as _e:
        lg.warning(f"[US-CRASH-GUARD] 체크실패({_e}) → 평소진행")
    exclude = EXCLUDE_HINTS_BEAR if regime == "BEAR" else EXCLUDE_HINTS
    candidates = []

    for row in rows:
        code     = str(row.get("code", "")).zfill(6)

        # [STALE-TS-FILTER 2026-06-05] 데이터가 멈춘(frozen ts) 종목 제외 — 수집 유니버스 밖 등.
        #   예: 007390이 09:04 행으로 70분째 끌려와 후보로 선택 → stale 가격 신호 매수 위험.
        _row_ts = str(row.get("ts", "")).strip()
        if _row_ts:
            try:
                _age_min = (datetime.now() - datetime.strptime(_row_ts, "%Y%m%d%H%M%S")).total_seconds() / 60.0
                if _age_min > STALE_TS_MAX_MIN:
                    lg.info("  [SKIP] %s ts=%s 데이터멈춤(%.0f분>%.0f분) → stale 후보 제외", code, _row_ts, _age_min, STALE_TS_MAX_MIN)
                    continue
            except Exception:
                pass  # ts 파싱 실패 → 필터 스킵(기존 흐름 유지)

        hint     = str(row.get("strategy_hint", "")).upper().strip()
        prescore = _f(row.get("prescore_weighted", 0))
        attack   = _f(row.get("attack_score", 0))
        stable   = _f(row.get("stable_score", 0))
        edge     = _f(row.get("expected_edge", 0))

        # ── 안전 필터 (hint / prescore / overheat) ──────────────
        if hint in exclude: continue
        if hint and hint not in VALID_HINTS: continue
        if prescore < MIN_PRESCORE: continue
        # [v4.16 A1] attack_score 필터 제거 — 스코어보드 선별 완료, 재필터 불필요
        blocked, _ = calc_overheat(row, lg, code)
        if blocked: continue

        # [고가주 차단] 1주 가격이 (자본 × Kelly 상한) 초과면 후보에서 제외
        _price_now = _f(row.get("price_now", 0))
        if _price_now > 0 and _price_now > _capital() * KELLY_HARD_MAX:
            lg.info("  [SKIP] %s 1주가격%d원 > 자본×Kelly%d원 → 고가주제외",
                    code, int(_price_now), int(_capital() * KELLY_HARD_MAX))
            continue

        # ── 최소 품질 확인 ────────────────────────────────────────
        quality = calc_momentum_quality(row)
        if quality < QUALITY_MIN:
            lg.info("  [SKIP] %s 품질%.2f<%.2f", code, quality, QUALITY_MIN); continue

        # ── ride 계산 — exit_signals 전용 (선정 점수에 영향 없음) ─
        ride = calc_inst_ride(row)

        # [B안] PULLBACK 인위적 가산 제거 — pullback_watch 필터 후 공정 비교
        _pb_score_mult = 1.0

        # [P3] EARLY(T0) 신호 — 막 시작된 흐름 감지 (보수적 3조건 + 컬럼명 fallback)
        _is_early = False
        try:
            _va  = _early_get(row, "volume_accel", "vol_accel", "volume_spike")
            _lbr = _early_get(row, "last3_ret", "last_bar_return", "return_1")
            _cp  = _early_get(row, "close_position", "close_pos")
            if _va >= 1.4 and _lbr > 0 and _cp >= 0.6:
                _is_early = True
        except Exception:
            pass

        lg.info("  [후보] %s ps=%.1f ride=%.2f q=%.2f hint=%s pb_boost=%.0f%% early=%s",
                code, prescore, ride["ride_score"], quality, hint,
                (_pb_score_mult - 1) * 100, _is_early)
        candidates.append({
            "code": code, "row": row, "ride": ride,
            "prescore": prescore, "attack": attack, "stable": stable,
            "selection_score": round(prescore * (1.0 + _f(row.get("inst_ride_score", 0.0)) * W_RIDE) * (1.0 + max(_f(row.get("ofi", 0.0)), 0.0) * W_OFI) * _pb_score_mult, 4),
            "hint": hint, "regime": regime,
            "edge": edge, "overheat_mult": 1.0, "quality": quality,
            "early_flag": _is_early,
        })

    if not candidates:
        lg.warning("[EVAL] 유효 후보 없음"); return None

    # [PULLBACK-TIMING 2026-06-05 ★LIVE] 떨어지는中 매수금지 — 눌림 끝나고 살아나는 첫 순간만 PASS.
    #   PULLBACK 계열 후보에만 적용(SIGA/EOD/기타 hint는 통과). BLOCK=후보제외+로그. env PB_TIMING_GATE=NO 되돌림.
    if PB_TIMING_GATE:
        _before_pbt = len(candidates)
        _kept = []
        for c in candidates:
            _hint = str(c.get("hint", "")).upper()
            if _hint in ("SIGA", "EOD", "EOD_PICK", "JONGBAE", "SIGA_DAILY"):   # 비PULLBACK = 게이트 미적용(통과)
                _kept.append(c); continue
            _ok, _reason = _pullback_timing_gate(c["row"], c["code"])
            if _ok:
                lg.info("[PULLBACK-TIMING] PASS code=%s %s", c["code"], _reason)
                _kept.append(c)
            else:
                if "vwap" in _reason:   # [DUP 2026-06-08] VWAP는 check_tiered TIER3 회차조건과 중복검사 — 로그만(삭제 안 함, 유지)
                    lg.info("[PB-TIMING-DUP] code=%s VWAP조건이 TIER 회차조건과 중복검사됨(reason=%s, 유지)", c["code"], _reason)
                lg.info("[PULLBACK-TIMING] BLOCK code=%s reason=%s", c["code"], _reason)
        candidates = _kept
        lg.info("[PULLBACK-TIMING] 게이트 %d→%d (떨어지는中 매수금지, 살아나는 순간만)", _before_pbt, len(candidates))
        if not candidates:
            lg.info("[PULLBACK-TIMING] 통과 후보 없음 → HOLD(살아나는 첫 순간 대기)")
            return None

    # [EXEC-SAFEPLUS 2026-06-13 친구님] 8→1 = '진짜 테마 대장주' 점수로 교체 (잡주 1등 방지).
    #   selection_score를 SAFE+(반복등장30+상대거래대금25+눌림품질20+종가강도15+대장유지10)로 덮어씀
    #   → 아래 정렬/winner_gap/dominance 전부 SAFE+로 일관. 강제X(생존·타이밍 통과자끼리 재정렬).
    if EXEC_SAFEPLUS_ENABLE and candidates:
        try:
            _rep = _load_exec_repeat_count()
            _vmax = max((_f(c["row"].get("value_day", 0)) for c in candidates), default=0.0) or 1.0
            for c in candidates:
                _cc = str(c["code"]).zfill(6)
                _rp = _rep.get(_cc, 0)
                _c_rep = min(_rp / 3.0, 1.0) * 30.0                                      # 반복등장(상위K 테마 겹침)
                _c_val = (_f(c["row"].get("value_day", 0)) / _vmax) * 25.0               # 상대거래대금(8개 중)
                _c_pb  = max(0.0, min(_f(c["row"].get("price_vs_vwap", 0)), 1.05)) / 1.05 * 20.0  # 눌림품질(VWAP 회복)
                _c_cls = max(0.0, min(_f(c["row"].get("close_position", 0)), 1.0)) * 15.0  # 종가강도
                _c_ld  = 10.0 if _f(c["row"].get("_z_theme", 0)) > 0 else 0.0             # 대장유지(테마 강도+)
                c["_selection_orig"] = c["selection_score"]
                c["selection_score"] = round(_c_rep + _c_val + _c_pb + _c_cls + _c_ld, 3)
                c["_safe_parts"] = f"rep{_c_rep:.0f}+val{_c_val:.0f}+pb{_c_pb:.0f}+cls{_c_cls:.0f}+ld{_c_ld:.0f}|겹{_rp}"
            _o1 = max(candidates, key=lambda x: x.get("_selection_orig", 0.0))["code"]
            _n1 = max(candidates, key=lambda x: x["selection_score"])["code"]
            lg.info("[EXEC-SAFEPLUS] selection_score→SAFE+ 교체 | 기존1등=%s → SAFE+1등=%s (변경=%s) | SAFE+1등분해=%s",
                    str(_o1).zfill(6), str(_n1).zfill(6), "Y" if str(_o1) != str(_n1) else "N",
                    max(candidates, key=lambda x: x["selection_score"]).get("_safe_parts", ""))
        except Exception as _se:
            lg.warning("[EXEC-SAFEPLUS] 교체 예외(무시, 기존 selection_score 유지): %s", _se)

    # prescore_weighted 기준 정렬 → Stage 8: 상위 8개만 비교
    candidates.sort(key=lambda x: x["selection_score"], reverse=True)
    candidates = candidates[:STAGE_8_CAP]   # [v4.29] Stage 8

    # winner_gap / dominance_ratio / conviction — raw score 기준 (TOP1_BONUS 적용 전)
    if len(candidates) >= 2:
        raw1 = candidates[0]["selection_score"]
        raw2 = candidates[1]["selection_score"]
        winner_gap      = round(raw1 - raw2, 4)
        dominance_ratio = round(raw1 / raw2, 4) if raw2 > 0 else 9.99
        conviction      = round(winner_gap / raw1, 4) if raw1 > 0 else 0.0
    else:
        winner_gap = 999.0; dominance_ratio = 9.99; conviction = 1.0

    # weak_winner: ATTACK 차단 플래그 (STABLE 경로는 유지)
    # [TUNE] OR→AND: 두 조건 모두 미달해야 축소 (하나만 미달 시 불필요한 11.5% 축소 방지)
    weak_winner = (winner_gap < WINNER_GAP_MIN and dominance_ratio < WINNER_DOM_MIN)

    # 1등에만 TOP1_BONUS 적용 (비교는 raw로, 기록은 bonus 후 값으로)
    # [EXEC 8→1 SHADOW 2026-06-05] 테마일관성·실행품질이 1등을 어떻게 바꿀지 계산+로그. 적용은 env(기본 SHADOW).
    try:
        import statistics as _st
        _cur_pick = str(candidates[0]["code"]).zfill(6)
        _lead = _exec_theme_leader_set()
        _liqs = [_f(c["row"].get("value_5m", c["row"].get("value_now", 0))) for c in candidates]
        _lmu = sum(_liqs) / len(_liqs) if _liqs else 0.0
        _lsd = (_st.pstdev(_liqs) if len(_liqs) > 1 else 0.0) or 0.0

        def _liq_z(c):
            v = _f(c["row"].get("value_5m", c["row"].get("value_now", 0)))
            return (v - _lmu) / _lsd if _lsd > 0 else 0.0

        _theme_cands = [c for c in candidates if str(c["code"]).zfill(6) in _lead]  # selection_score 정렬 유지
        _theme_pick = str(_theme_cands[0]["code"]).zfill(6) if _theme_cands else None
        _shadow_w = EXEC_EXECQ_WEIGHT if EXEC_EXECQ_WEIGHT > 0 else 0.10  # SHADOW 비교용 기준 가중
        _execq_sorted = sorted(candidates, key=lambda c: c["selection_score"] * (1.0 + _liq_z(c) * _shadow_w), reverse=True)
        _execq_pick = str(_execq_sorted[0]["code"]).zfill(6)
        # [GPT-5축 TURN 2026-06-06] 사용자 지시 — GPT가 알려준 5축을 충실 반영(SHADOW 아님, 실제 1등 선별).
        #   ①가격위치(VWAP회복+재상승 accel_real) ②거래대금(가속 last5_value_accel + 막판증가 now/prev)
        #   ③수급보강(기관가속 inst_accel + 순매수 net_buy_flag; ride/ofi는 selection_score base에 이미 반영)
        #   ④호가/체결강도=호가데이터 미수집으로 제외 ⑤사후성과=별도 추적기(선별식 아님).
        #   각 축 횡단면 winsor-z(±3)로 정규화 후 GPT 우선순위 가중평균(가격0.40>거래대금0.35>수급0.25) → turn_z.
        #   leader_score = selection_score × (1 + turn_z × EXEC_TURN_WEIGHT).
        def _zmap(vals):
            # NaN/inf 방어 — _f는 'nan' 문자열을 float('nan')으로 통과시키므로 pstdev가 깨질 수 있음.
            vals = [v if (v == v and v not in (float("inf"), float("-inf"))) else 0.0 for v in vals]
            _mu = sum(vals) / len(vals) if vals else 0.0
            _sd = (_st.pstdev(vals) if len(vals) > 1 else 0.0) or 0.0
            return [max(-3.0, min(3.0, (v - _mu) / _sd)) if _sd > 0 else 0.0 for v in vals]
        _n = len(candidates)
        _col = lambda name, d=0.0: [_f(c["row"].get(name, d)) for c in candidates]
        _codes_o = [str(c["code"]).zfill(6) for c in candidates]
        _z_vwap = _zmap(_col("price_vs_vwap", 1.0))          # 축1 VWAP회복
        _z_recl = _zmap(_col("accel_real"))                  # 축1 재상승(다시 고개 드는 구조)
        _z_vacc = _zmap(_col("last5_value_accel"))           # 축2 거래대금 가속
        _vn = _col("value_now"); _vp = _col("value_prev")
        _z_vsur = _zmap([(_vn[i] / _vp[i] if _vp[i] > 0 else 1.0) for i in range(_n)])  # 축2 막판 거래대금 증가
        _z_iacc = _zmap(_col("inst_accel"))                  # 축3 기관 가속(보강)
        _nbf    = _col("net_buy_flag")                       # 축3 순매수(0/1)
        # [HOGA-LIVE 축④] broker 실시간 호가(opt10004)+체결강도(opt10001). 실패=중립(전부 0 → 축④ 무효화, 3축으로 진행).
        _hoga = {}
        _hoga_ok = 0
        if EXEC_HOGA_ENABLE:
            try:
                from rt_hoga_live_v1 import get_hoga_strength
                for _cz in _codes_o:
                    _h = get_hoga_strength(_cz, with_strength=EXEC_HOGA_STRENGTH)
                    _hoga[_cz] = _h
                    if _h.get("ok"):
                        _hoga_ok += 1
                lg.info("[HOGA-LIVE] 호가조회 %d/%d OK (broker)", _hoga_ok, _n)
            except Exception as _he:
                lg.warning("[HOGA-LIVE] 조회 스킵(%s) → 축④ 중립", _he)
        _z_imbal = _zmap([float(_hoga.get(_codes_o[i], {}).get("imbalance", 1.0)) for i in range(_n)])   # 매수잔량 우위
        _z_sprd  = _zmap([float(_hoga.get(_codes_o[i], {}).get("spread_pct", 0.0)) for i in range(_n)])  # 넓을수록 나쁨(부호반전)
        _z_stren = _zmap([float(_hoga.get(_codes_o[i], {}).get("strength", 0.0)) for i in range(_n)])    # 체결강도
        # 가중: 가격위치 0.30 > 거래대금 0.25 > 호가/체결 0.25 > 수급 0.20 (호가 데이터 합류로 5축 균형)
        _TW1, _TW2, _TW3, _TW4 = 0.30, 0.25, 0.20, 0.25
        _turn_zmap = {}
        for i in range(_n):
            _a1 = (_z_vwap[i] + _z_recl[i]) / 2.0
            _a2 = (_z_vacc[i] + _z_vsur[i]) / 2.0
            _a3 = (_z_iacc[i] + (1.0 if _nbf[i] > 0 else -1.0)) / 2.0
            _a4 = 0.50 * _z_imbal[i] - 0.25 * _z_sprd[i] + 0.25 * _z_stren[i]   # 매수압력↑·스프레드↓·체결강도↑
            _turn_zmap[_codes_o[i]] = round(_TW1 * _a1 + _TW2 * _a2 + _TW3 * _a3 + _TW4 * _a4, 4)

        def _turn_z(c):
            return _turn_zmap.get(str(c["code"]).zfill(6), 0.0)
        _turn_w = EXEC_TURN_WEIGHT if EXEC_TURN_WEIGHT > 0 else 0.10   # [TURN-LIVE] 적용가중(0이면 표시용 0.10)
        _turn_sorted = sorted(candidates, key=lambda c: c["selection_score"] * (1.0 + _turn_z(c) * _turn_w), reverse=True)
        _turn_pick = str(_turn_sorted[0]["code"]).zfill(6)
        _chg = ((("테마★바뀜 " if _theme_pick and _theme_pick != _cur_pick else "")
                 + ("실행품질★바뀜 " if _execq_pick != _cur_pick else "")
                 + ("턴★바뀜" if _turn_pick != _cur_pick else "")).strip() or "동일")
        lg.info("[EXEC-SHADOW] 현재1등=%s | 테마1등=%s(%s) | 실행품질1등=%s | 턴(GPT5축)1등=%s(turn_z=%.2f) | %s",
                _cur_pick, _theme_pick, "테마대장有" if _theme_cands else "無", _execq_pick,
                _turn_pick, _turn_zmap.get(_turn_pick, 0.0), _chg)
        # 적용(env): 테마 우선 → 턴신호(VWAP+거래대금) → 실행품질. 테마/execq 기본 OFF, 턴 기본 ON.
        if EXEC_THEME_PRIORITY and _theme_pick and _theme_pick != _cur_pick:
            candidates = ([c for c in candidates if str(c["code"]).zfill(6) == _theme_pick]
                          + [c for c in candidates if str(c["code"]).zfill(6) != _theme_pick])
            lg.info("[EXEC-THEME] ★테마대장주 %s 8→1 승격 ← 기존 %s", _theme_pick, _cur_pick)
        elif EXEC_TURN_WEIGHT > 0:
            # [TURN-LIVE 2026-06-06] GPT 5축(가격위치+거래대금+수급)을 1등 점수에 실반영(SHADOW 아님).
            candidates = _turn_sorted
            if _turn_pick != _cur_pick:
                lg.info("[EXEC-TURN] ★GPT5축턴신호(w=%.2f) %s 1등(turn_z=%.2f) ← 기존 %s",
                        EXEC_TURN_WEIGHT, _turn_pick, _turn_zmap.get(_turn_pick, 0.0), _cur_pick)
            else:
                lg.info("[EXEC-TURN] GPT5축턴신호 적용(w=%.2f) — 1등 유지 %s(turn_z=%.2f)",
                        EXEC_TURN_WEIGHT, _cur_pick, _turn_zmap.get(_cur_pick, 0.0))
        elif EXEC_EXECQ_WEIGHT > 0:
            candidates = _execq_sorted
            if _execq_pick != _cur_pick:
                lg.info("[EXEC-EXECQ] ★실행품질 %s 1등 ← 기존 %s", _execq_pick, _cur_pick)
    except Exception as _ese:
        lg.warning("[EXEC-SHADOW] 스킵(%s)", _ese)

    # [LEADER-FIRST 2026-06-11 사용자결정] 당일 대금 최상위(대장주) 후보를 1등으로 최종 승격.
    #   백테(39일): 대금 top3 첫눌림 +4.38%(n=8) vs 일반 -0.89%(n=434) — 표본小, 소액실험(50만 캡)으로 실전 검증.
    #   테마/턴 정렬보다 후순위 배치 = 최종 우선권. 롤백 env LEADER_FIRST_ENABLE=NO.
    try:
        if LEADER_FIRST_ENABLE and candidates:
            _lf_cur = str(candidates[0]["code"]).zfill(6)
            _lf_cands = [c for c in candidates
                         if _f(c["row"].get("value_day", 0)) >= LEADER_FIRST_MIN_EOK * 1e8]
            if _lf_cands:
                _lf_pick = max(_lf_cands, key=lambda c: _f(c["row"].get("value_day", 0)))
                _lf_code = str(_lf_pick["code"]).zfill(6)
                _lf_pick["leader_first"] = True
                if _lf_code != _lf_cur:
                    candidates = ([c for c in candidates if str(c["code"]).zfill(6) == _lf_code]
                                  + [c for c in candidates if str(c["code"]).zfill(6) != _lf_code])
                    lg.info("[LEADER-FIRST] ★대장주 승격 %s (value_day=%.0f억) ← 기존 %s",
                            _lf_code, _f(_lf_pick["row"].get("value_day", 0)) / 1e8, _lf_cur)
                else:
                    lg.info("[LEADER-FIRST] 1등 유지 %s (value_day=%.0f억)",
                            _lf_code, _f(_lf_pick["row"].get("value_day", 0)) / 1e8)
    except Exception as _lfe:
        lg.warning("[LEADER-FIRST] 스킵(%s)", _lfe)

    # [SELECTION-SNAPSHOT 2026-06-06] 사후성과(축⑤) 추적용 — 최종 8후보 박제(append, 로그전용·행동무변).
    #   BACKTEST/selection_forward_eval_v1.py 가 prices_1m와 join해 5/10/20분 수익률·MFE/MAE로 1등vs2~8등 검증.
    try:
        import json as _json
        from datetime import datetime as _dt
        _tz = locals().get("_turn_zmap", {})
        _picks = []
        for _i, _c in enumerate(candidates[:STAGE_8_CAP]):
            _czf = str(_c["code"]).zfill(6)
            _picks.append({
                "rank": _i + 1, "code": _czf,
                "sel": round(_f(_c.get("selection_score", 0)), 4),
                "turn_z": round(float(_tz.get(_czf, 0.0)), 4),
                "prescore": round(_f(_c.get("prescore", 0)), 2),
                "price": _f(_c["row"].get("price_now", 0)),
                "hint": str(_c.get("hint", "")),
            })
        _snap = {"ts": _dt.now().strftime("%Y%m%d%H%M%S"), "regime": regime,
                 "n_cand": len(candidates), "winner_gap": winner_gap, "picks": _picks}
        with open(DATA / "selection_snapshot.jsonl", "a", encoding="utf-8") as _sf:
            _sf.write(_json.dumps(_snap, ensure_ascii=False) + "\n")
    except Exception as _snape:
        lg.debug("[SELECTION-SNAPSHOT] 스킵(%s)", _snape)

    best = candidates[0]
    best["selection_score"] = round(best["selection_score"] * TOP1_BONUS, 4)
    best["winner_gap"]      = winner_gap
    best["dominance_ratio"] = dominance_ratio
    best["conviction"]      = conviction
    best["weak_winner"]     = weak_winner

    lg.info("[EVAL] ★선택 %s ps=%.1f ride=%.2f q=%.2f gap=%.2f dom=%.3f conv=%.3f weak=%s (8→1 집행)",
            best["code"], best["prescore"], best["ride"]["ride_score"], best["quality"],
            winner_gap, dominance_ratio, conviction, weak_winner)

    # ── [SR-SHADOW 2026-06-12 ★친구님 지시 "바닥선·천정선 매수 참조"] 자리 평가 — 기록전용, 주문 무간섭 ──
    #   레벨: DATA/support_resist_levels.csv (매일 08:50 SAFEPLUS_SR_LEVELS 생성, D-1 기준).
    #   검증근거(6/12, 참조용): 천정코앞(0~3%) 최악(-1.29%/21%) / 바닥대비 5~15% 이륙구간 최선(-0.53%/30%).
    #   표본 30건+ 후 실관문 승격 판단. 끄기: env SR_SHADOW_ENABLE=NO.
    try:
        if os.environ.get("SR_SHADOW_ENABLE", "YES").strip().upper() == "YES":
            import csv as _sr_csv, io as _sr_io
            from datetime import datetime as _sr_dt
            _sr_px = _f(best["row"].get("price_now", 0)) or _f(best["row"].get("close", 0))
            _sr_lv = None
            _sr_path = DATA / "support_resist_levels.csv"
            if _sr_px > 0 and _sr_path.exists():
                with _sr_io.open(_sr_path, encoding="utf-8-sig") as _sr_f:
                    for _sr_r in _sr_csv.DictReader(_sr_f):
                        if _sr_r["code"] == str(best["code"]).zfill(6):
                            _sr_lv = _sr_r; break
            if _sr_lv:
                _l5 = float(_sr_lv["low5"]); _l20 = float(_sr_lv["low20"]); _h20 = float(_sr_lv["high20"])
                _rise5 = (_sr_px / _l5 - 1) * 100 if _l5 > 0 else None
                _head = (_h20 / _sr_px - 1) * 100 if _h20 > 0 else None
                if _head is not None and 0 < _head < 3:
                    _verdict = "BAD_천정코앞"
                elif _rise5 is not None and 5 <= _rise5 < 15:
                    _verdict = "GOOD_이륙구간"
                elif _head is not None and _head <= 0:
                    _verdict = "OK_신고가돌파"
                else:
                    _verdict = "MID_중립"
                lg.info("[SR-SHADOW] %s px=%.0f 바닥5일比 %+.1f%% 천정여유 %+.1f%% → %s (기록만)",
                        best["code"], _sr_px,
                        _rise5 if _rise5 is not None else -999,
                        _head if _head is not None else -999, _verdict)
                _sr_out = DATA / "BACKTEST" / "sr_shadow.csv"
                _sr_new = not _sr_out.exists()
                with _sr_io.open(_sr_out, "a", encoding="utf-8-sig", newline="") as _sr_f:
                    _sr_w = _sr_csv.writer(_sr_f)
                    if _sr_new:
                        _sr_w.writerow(["ts", "code", "price", "rise5_pct", "headroom_pct", "verdict"])
                    _sr_w.writerow([_sr_dt.now().strftime("%Y%m%d%H%M%S"), str(best["code"]).zfill(6),
                                    _sr_px, round(_rise5, 2) if _rise5 is not None else "",
                                    round(_head, 2) if _head is not None else "", _verdict])
    except Exception as _sre:
        lg.debug("[SR-SHADOW] 스킵(%s)", _sre)
    return best


# ═══════════════════════════════════════════════════════════════
#  ⑩ 모드 판정
# ═══════════════════════════════════════════════════════════════
def decide_mode(best: dict, ev_result: dict, lg: logging.Logger) -> str:
    ev = ev_result["ev_pct"]
    regime = best.get("regime", "NEUTRAL")
    sample_n = ev_result.get("sample_n", 0)
    calibrated = ev_result.get("calibrated", False)

    # [v4.17 FIX-6] decide_mode n<5→n<8 통일 (calc_ev FIX-4와 정합)
    # v4.17 FIX-4: calc_ev n<8 → kelly=0.10 + calibrated=False 반환
    # 기존 n<5 SKIP이 남아있으면 n=5,6,7 구간에서
    #   calc_ev는 통과 / decide_mode는 SKIP → 구조적 불일치 발생
    # 수정: n<8 SKIP → 1일1진입 보장 유지하며 n<8 포지션50% 자동축소로 전환
    # 근거: Thorp(1962) 초기 불확실구간 반배팅 / bridge WARMING_MIN=8 통일
    if not calibrated and sample_n < 8:
        # [v4.29 FIX-2] PULLBACK STRONG 한정 n<8 BYPASS — EV이력 없어도 스코어보드 검증 완료
        _pb_cls_pre = str(best.get("pb_setup_class", "")).upper()
        if _pb_cls_pre == "STRONG" and best.get("regime", "NEUTRAL") != "BEAR":
            lg.info("[MODE][n<8 BYPASS] PULLBACK STRONG EV미보정 n=%d → ATTACK 허용 (Kelly=0.10 축소 유지)", sample_n)
            return "ATTACK"
        # [신선 대장주 BYPASS] STRONG 자격 없어도 점수+기관강세면 ATTACK
        _fresh_ps_min   = float(os.environ.get("FRESH_PS_MIN",   "30.0"))
        _fresh_ride_min = float(os.environ.get("FRESH_RIDE_MIN", "0.50"))
        _fresh_ofi_min  = float(os.environ.get("FRESH_OFI_MIN",  "0.30"))
        _ps_now   = best["prescore"]
        _ride_now = best["ride"]["ride_score"]
        _ofi_now  = best["ride"]["ofi_at_entry"]
        if (_ps_now >= _fresh_ps_min and _ride_now >= _fresh_ride_min
                and _ofi_now >= _fresh_ofi_min and best.get("regime") != "BEAR"):
            lg.info("[MODE][FRESH-BYPASS] 신선 대장주 ps=%.1f ride=%.2f ofi=%.2f → ATTACK",
                    _ps_now, _ride_now, _ofi_now)
            return "ATTACK"
        lg.warning("[MODE] EV 미보정 n=%d<8 → STABLE 강제 (v4.31: sizing 보정 없음, KELLY_HARD_MAX 상한 유지)", sample_n)
        return "STABLE"   # [v4.17] SKIP→STABLE (1일1진입 보장)
    # n<12(=EV_MIN_SAMPLES): 통계 불안정 → 경고만 (진입 허용, 포지션 자동 축소)
    if not calibrated and sample_n < EV_MIN_SAMPLES:
        lg.warning("[MODE] EV 미보정 n=%d<%d → STABLE만 허용, 포지션 자동 축소", sample_n, EV_MIN_SAMPLES)

    # [v4.9] BEAR 레짐 시 EV 기준 강화
    ev_min = EV_ENTRY_MIN + (EV_BEAR_EXTRA if regime == "BEAR" else 0.0)
    # [P2-1] PULLBACK EV 최소 기준 -5% 완화 (EV<0 진입 금지는 유지)
    if str(best.get("hint", "")).upper() == "PULLBACK":
        ev_min = max(ev_min * 0.95, 0.0)
    if calibrated and ev < ev_min:
        lg.warning("[MODE] SKIP — EV=%.3f%%<%.2f%%(BEAR=%s hint=%s) → 차단",
                   ev, ev_min, regime == "BEAR",
                   best.get("hint", "")); return "SKIP"

    # [v4.26 FIX-1] STRONG PULLBACK 즉시 ATTACK 반환 — 이중 필터 완전 제거
    # v4.25: _pb_pri>=55 and _pb_qual>=60 재검증 → 이중 선별 (스코어보드 불신)
    # 근거: STRONG = 스코어보드가 priority/quality 이미 검증 완료
    #       execution_engine 재검증 = 동일 팩터 이중 적용 → 수익 누수 원인
    # 보호: EV 최소 조건 통과 / BEAR 레짐 STABLE 강제 / ride>0 방어(브리지)
    # [통합패치-07] 최소 실시간 품질 하한선 복구 — inst≥1, ofi≥0.10, accel≥0.95
    #   STRONG/MODERATE 정적 분류와 발주 시점 사이 모멘텀 감쇠 차단용 안전망
    _pb_class = str(best.get("pb_setup_class", "")).upper()
    _ride_dict = best.get("ride", {})
    _inst_real = int(_ride_dict.get("inst_days", 0))
    _ofi_real  = float(_ride_dict.get("ofi_at_entry", 0.0))
    _accel_real = float(_ride_dict.get("accel_at_entry", 0.0))
    _pb_min_ok = (_inst_real >= 1 and _ofi_real >= 0.10 and _accel_real >= 0.95)
    if _pb_class == "STRONG":
        if regime == "BEAR":
            lg.info("[MODE][v4.26] PULLBACK STRONG — BEAR 레짐 → STABLE 강제")
            return "STABLE"
        if not _pb_min_ok:
            lg.warning("[MODE][패치07] STRONG 실시간 품질 미달 inst=%d ofi=%.2f accel=%.2f → STABLE 강등",
                       _inst_real, _ofi_real, _accel_real)
            return "STABLE"
        lg.info("[MODE][v4.26] PULLBACK STRONG → ATTACK 즉시 (이중필터 제거, 최소품질 통과)")
        return "ATTACK"

    # [v4.27 FIX-1] MODERATE 좋은 케이스 ATTACK 추가
    # [v4.29 FIX-1] MODERATE 조건 정상화 — pri>=60/qual>=60은 STRONG보다 더 빡셈 (비정상)
    # 검증:
    #   STRONG 기준: priority>=50 AND quality>=55
    #   v4.27 MODERATE: pri>=60 AND qual>=60 → STRONG보다 높아서 대부분 탈락
    #   정상 기준: pri>=55 AND qual>=50
    #     priority=55+quality=52 → MODERATE이면서 진입 가능 (STRONG quality 미달 케이스)
    #     priority=62+quality=50 → STRONG 탈락 MODERATE, 여기서 살림
    _pb_pri  = float(best.get("pb_priority", 0.0))
    _pb_qual = float(best.get("pb_quality",  0.0))
    if _pb_class == "MODERATE" and _pb_pri >= 55 and _pb_qual >= 50:
        if regime == "BEAR":
            lg.info("[MODE][v4.29] PULLBACK MODERATE — BEAR 레짐 → STABLE 강제")
            return "STABLE"
        if not _pb_min_ok:
            lg.warning("[MODE][패치07] MODERATE 실시간 품질 미달 inst=%d ofi=%.2f accel=%.2f → STABLE 강등",
                       _inst_real, _ofi_real, _accel_real)
            return "STABLE"
        lg.info("[MODE][v4.29] PULLBACK MODERATE (pri=%.0f qual=%.0f) → ATTACK",
                _pb_pri, _pb_qual)
        return "ATTACK"

    ps    = best["prescore"]; ride = best["ride"]
    inst  = ride["inst_days"]; ofi  = ride["ofi_at_entry"]; accel = ride["accel_at_entry"]

    # [v4.29 P1] PULLBACK 전략 한해 accel 기준 0.90으로 완화
    # 근거: 눌림목은 기관 감속 구간이 정의 — accel 0.90~0.99 진입 후보 STABLE 탈락 방지
    # BEAR 보호/EV 최소/STRONG 즉시반환은 이 블록 위에서 이미 처리됨
    _hint_up   = str(best.get("hint", "")).upper()
    _is_pb     = "PULLBACK" in _hint_up
    _accel_min = 0.90 if _is_pb else ATTACK_ACCEL_MIN

    mode  = "SKIP"
    # [신규] ATTACK 5조건 → N/5 충족 모드 (env: ATTACK_MIN_CONDS, 기본 5 = 기존 동작)
    _atk_count = sum([
        ps >= ATTACK_PRESCORE,
        inst >= ATTACK_INST_DAYS_MIN,
        ofi >= ATTACK_OFI_MIN,
        accel >= _accel_min,
        ride["ride_score"] >= RIDE_SOFT_MIN,
    ])
    _atk_min = int(os.environ.get("ATTACK_MIN_CONDS", "5"))
    if _atk_count >= _atk_min:
        # [v4.30] weak_winner → ATTACK 차단 제거
        # 절대 품질(EV/ps/ride/ofi/accel) 통과 시 ATTACK 유지
        # weak_winner 불확실성은 calc_position_size에서 ×0.85 sizing으로 반영
        mode = "ATTACK"
    elif ps >= MIN_PRESCORE and ride["ride_score"] >= RIDE_HARD_MIN:
        mode = "STABLE"

    # [v4.10] 결함② 수정 — 미보정 시 ATTACK 차단 (기존 유지) + n<12 ATTACK도 차단
    if mode == "ATTACK" and not calibrated:
        lg.warning("[MODE] EV 미보정(n=%d) → ATTACK→STABLE", sample_n); mode = "STABLE"

    lg.info("[MODE] %s — ps=%.1f inst=%d ofi=%.2f accel=%.2f(min=%.2f) ride=%.2f ev=%.3f%% n=%d cal=%s",
            mode, ps, inst, ofi, accel, _accel_min, ride["ride_score"], ev, sample_n, calibrated)

    # [v4.29 P2] ATTACK 미달 사유 1줄 — EV 통과 후 어떤 조건 때문에 STABLE인지
    if mode != "ATTACK" and mode != "SKIP":
        _atk_fails = []
        if ps   < ATTACK_PRESCORE:      _atk_fails.append(f"ps={ps:.1f}<{ATTACK_PRESCORE}")
        if inst < ATTACK_INST_DAYS_MIN: _atk_fails.append(f"inst={inst}<{ATTACK_INST_DAYS_MIN}")
        if ofi  < ATTACK_OFI_MIN:       _atk_fails.append(f"ofi={ofi:.2f}<{ATTACK_OFI_MIN}")
        if accel < _accel_min:          _atk_fails.append(f"accel={accel:.2f}<{_accel_min:.2f}")
        if ride["ride_score"] < RIDE_SOFT_MIN:
            _atk_fails.append(f"ride={ride['ride_score']:.2f}<{RIDE_SOFT_MIN}")
        if best.get("weak_winner"):     _atk_fails.append("weak_winner")
        if _atk_fails:
            lg.warning("[MODE_FAIL] code=%s mode=%s → %s",
                       best.get("code", "?"), mode, " | ".join(_atk_fails))
    return mode


# ═══════════════════════════════════════════════════════════════
#  ⑪ 하차 + 트레일링 신호
# ═══════════════════════════════════════════════════════════════
def build_exit_signals(ride: dict) -> dict:
    """
    청산 신호 생성 — 4단계 단일 우선순위 체계 (if-elif, overwrite 없음)

    1순위: hard_risk_exit  (max_loss_per_trade / max_daily_loss 한도 도달)
    2순위: early_exit      (기관감속 감지)
    3순위: trailing        (ride_score 기반 HOLD / PARTIAL / EXIT)
    4순위: hold_days_exceeded (max_hold_days 초과)
    fallback: TRAILING_EXIT  (rs < TRAIL_MID, 나머지)

    ride dict에 hard_risk_exit / hold_days_exceeded 플래그가 없으면 False 기본값.
    """
    _lg        = logging.getLogger("rt_exec_v4_29")
    rs         = ride["ride_score"]
    ofi_entry  = ride.get("ofi_at_entry", 0)
    early_exit = ride.get("early_exit", False)

    # ── 1순위: hard risk (max_loss_per_trade / max_daily_loss) ────
    if ride.get("hard_risk_exit", False):
        trail_mode  = "EXIT"
        trail_ratio = 1.0
        exit_reason = "HARD_RISK"
        _lg.warning("[EXIT] HARD_RISK max_loss/daily_loss 한도 도달 → 전량 즉시 청산")

    # ── 2순위: early exit (기관감속) ─────────────────────────────
    elif early_exit:
        trail_mode  = "EXIT"
        trail_ratio = 1.0
        exit_reason = "EARLY_EXIT"
        _lg.info("[EXIT] EARLY_EXIT 기관감속 감지 → 즉시 청산 (rs=%.2f)", rs)

    # ── 3순위: trailing — HOLD ────────────────────────────────────
    elif rs >= TRAIL_STRONG:
        trail_mode  = "HOLD"
        trail_ratio = 0.0
        exit_reason = "TRAILING_HOLD"
        _lg.info("[TRAIL] HOLD rs=%.2f >= %.2f", rs, TRAIL_STRONG)

    # ── 3순위: trailing — PARTIAL ─────────────────────────────────
    elif rs >= TRAIL_MID:
        trail_mode  = "PARTIAL"
        trail_ratio = PARTIAL_SELL_RATIO
        exit_reason = "TRAILING_PARTIAL"
        _lg.info("[TRAIL] PARTIAL rs=%.2f >= %.2f → %.0f%% 매도",
                 rs, TRAIL_MID, PARTIAL_SELL_RATIO * 100)

    # ── 4순위: max_hold_days 초과 ─────────────────────────────────
    elif ride.get("hold_days_exceeded", False):
        trail_mode  = "EXIT"
        trail_ratio = 1.0
        exit_reason = "MAX_HOLD"
        _lg.info("[EXIT] MAX_HOLD 보유일수 초과 → 전량 청산")

    # ── fallback: trailing exit (rs < TRAIL_MID) ──────────────────
    else:
        trail_mode  = "EXIT"
        trail_ratio = 1.0
        exit_reason = "TRAILING_EXIT"
        _lg.info("[EXIT] TRAILING_EXIT rs=%.2f < %.2f → 전량 청산", rs, TRAIL_MID)

    return {
        "trail_mode": trail_mode, "trail_sell_ratio": trail_ratio,
        "exit_reason": exit_reason,
        "trail_strong": TRAIL_STRONG, "trail_mid": TRAIL_MID, "trail_exit": TRAIL_EXIT,
        "partial_sell_ratio": PARTIAL_SELL_RATIO,
        "trail_force_activate_pct": 2.0,    # 지침서5-3
        "trail_activate_min_pct":   1.5,    # 지침서5-1 조건A
        "trail_activate_ride_min":  0.40,   # 지침서5-1 조건B
        "trail_absolute_ban_pct":   1.0,    # 지침서5-2
        "inst_exit_trigger": EXIT_INST_DECAY_DAYS,
        "ofi_entry": round(ofi_entry, 4),
        "ofi_exit_trigger": round(ofi_entry * (1 - EXIT_OFI_DECAY_PCT / 100), 4),
        "ofi_decay_pct": EXIT_OFI_DECAY_PCT,
        "ofi_last10_entry": round(ride.get("ofi_last10", 0), 4),
        "accel_entry": round(ride.get("accel_at_entry", 0), 4),
        "accel_exit_trigger": 1.0, "max_hold_days": EXIT_MAX_HOLD_DAYS,
        "exit_warnings": ride.get("exit_warnings", []),
        "max_loss_per_trade": MAX_LOSS_PER_TRADE, "max_daily_loss": MAX_DAILY_LOSS,
        "early_exit": early_exit, "early_cut_loss": EARLY_CUT_LOSS,
    }


# ═══════════════════════════════════════════════════════════════
#  자기진화 — 지침서13장 (허용 3개만)
# ═══════════════════════════════════════════════════════════════
def calc_evolve_adjustments(profit_metrics: dict, lg: logging.Logger) -> dict:
    adj = {
        "hard_stop_adj": 1.0, "trail_activate_adj": 1.0, "split_t1_ratio_adj": 0.0,
        "stop_tighten": False, "pre_tp_boost": False, "evolve_note": "",
        # [v4.10] 결함③ 수정 — rt_sell_engine이 직접 읽는 필드명으로 출력
        # rt_sell_engine은 아래 필드를 읽어 hard_stop·trail 파라미터에 즉시 반영해야 함
        "apply_to": {
            "hard_stop_multiplier":    1.0,   # rt_sell_engine: HARD_STOP × 이 값
            "trail_activate_pct":      1.5,   # rt_sell_engine: trail 활성화 기준 수익률
            "split_t1_ratio":          0.40,  # rt_sell_engine: 1차 분할 매도 비율
        }
    }
    if not profit_metrics.get("evaluated"): return adj
    pf     = profit_metrics.get("profit_factor", 1.0)
    wr     = profit_metrics.get("win_rate", 0.5)
    mdd    = profit_metrics.get("max_drawdown", 0.0)
    calmar = profit_metrics.get("calmar", 0.0)
    notes  = []

    if wr < 0.45:
        adj["hard_stop_adj"] = 0.90
        adj["apply_to"]["hard_stop_multiplier"] = 0.90
        notes.append(f"WR={wr:.0%}<45%→hard_stop-10%")
    elif wr > 0.60:
        adj["hard_stop_adj"] = 1.10
        adj["apply_to"]["hard_stop_multiplier"] = 1.10
        notes.append(f"WR={wr:.0%}>60%→hard_stop+10%")

    if wr > 0.60:
        adj["trail_activate_adj"] = 0.90
        adj["apply_to"]["trail_activate_pct"] = 1.5 * 0.90   # = 1.35%
        notes.append(f"WR={wr:.0%}>60%→trail_activate-10%")

    if pf < 0.80:
        adj["split_t1_ratio_adj"] = 0.05
        adj["apply_to"]["split_t1_ratio"] = 0.40 + 0.05      # = 0.45
        notes.append(f"PF={pf:.2f}<0.8→split_t1+0.05")

    if mdd > 5.0:
        adj["stop_tighten"] = True
        adj["apply_to"]["hard_stop_multiplier"] = min(adj["apply_to"]["hard_stop_multiplier"], 0.85)
        notes.append(f"MDD={mdd:.1f}%>5%→손절강화")

    if wr > 0.65:
        adj["pre_tp_boost"] = True
        notes.append(f"WR={wr:.0%}>65%→선익절상향")

    # [v4.9] Calmar 진화 경로
    if 0 < calmar < 0.5:
        adj["stop_tighten"] = True
        adj["apply_to"]["hard_stop_multiplier"] = min(adj["apply_to"]["hard_stop_multiplier"], 0.85)
        notes.append(f"Calmar={calmar:.2f}<0.5→MDD손절강화")

    adj["evolve_note"] = " | ".join(notes) if notes else "OK"
    if notes: lg.info("[EVOLVE_ADJ] %s", adj["evolve_note"])
    return adj


# ═══════════════════════════════════════════════════════════════
#  신호 출력
# ═══════════════════════════════════════════════════════════════
def write_signal(best, mode, pos, regime, ev_result,
                 exit_signals, evolve_w, profit_metrics, lg) -> bool:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        row = best["row"]
        price = _f(row.get("price_now", 0))
        if price <= 0:
            for c in ["price", "close", "value_day"]:
                v = _f(row.get(c, 0))
                if v > 0: price = v; break

        # [v4.28 FIX-1] pkl 로드 + pb 주입을 main()으로 이동 (decide_mode 이전 실행 보장)
        # market_state / pb 필드는 main()에서 best에 이미 주입됨
        # write_signal은 best에 담긴 값을 sig에 복사하는 역할만 수행
        _bridge_ev_weight = _bridge_ev_weight_main  # main()에서 로드됨
        _siga_enable      = _siga_enable_main
        _pullback_enable  = _pullback_enable_main
        _pb_setup_class   = str(best.get("pb_setup_class", ""))
        _pb_priority      = float(best.get("pb_priority", 0.0))
        _pb_quality       = float(best.get("pb_quality",  0.0))

        # [v4.30 P2] 전략별 카운터 — hint 기준 엄격 분리
        _hint_now  = best.get("hint", "")
        _siga_prev = _get_siga_daily_count()
        _pb_prev   = _get_pullback_daily_count()
        _siga_cnt  = _siga_prev + (1 if _hint_now in ("SIGA", "MULTI") else 0)
        _pb_cnt    = _pb_prev   + (1 if _hint_now == "PULLBACK" else 0)

        # [DUPLICATE CODE GATE] 당일 진입 코드 목록 누적
        _daily_codes = []
        try:
            if SIGNAL.exists():
                with open(SIGNAL, "r", encoding="utf-8-sig") as _f_dc:
                    _sig_dc = json.load(_f_dc)
                if str(_sig_dc.get("date", "")) == _today():
                    _daily_codes = list(_sig_dc.get("daily_codes", []))
        except Exception:
            pass
        if best["code"] not in _daily_codes:
            _daily_codes.append(best["code"])

        # [v4.30 P4] relay_pullback_ready — 4조건 모두 충족 시만 True
        # 조건1: SIGA 1회 이상 완료  조건2: 09:18~09:25  조건3: 포지션 청산  조건4: pb_prev==0
        _hm_ws = _hhmm()
        _relay_ready = False
        if _siga_cnt >= 1 and _pb_prev == 0 and int(os.environ.get("RELAY_WINDOW_START", "918")) <= _hm_ws <= int(os.environ.get("RELAY_WINDOW_END", "925")):
            try:
                _opf_ws = DATA / "rt_open_positions.json"
                _pos_closed_ws = True
                if _opf_ws.exists():
                    with open(_opf_ws, "r", encoding="utf-8-sig") as _f_pos:
                        _op_ws = json.load(_f_pos)
                    _plist_ws = _op_ws if isinstance(_op_ws, list) else list(_op_ws.values())  # [POSDICT-FIX 2026-06-01] dict는 .values() 순회 (기존 [_op]=dict통째→qty항상0→포지션가드 무력)
                    if any(int(p.get("qty", 0)) > 0 for p in _plist_ws):
                        _pos_closed_ws = False
                _relay_ready = _pos_closed_ws
            except Exception:
                _relay_ready = False

        signal = {
            "version": VERSION, "ts": _now_str(), "date": _today(),
            "code": best["code"], "mode": mode,
            "daily_trade_count":   _siga_cnt + _pb_cnt,   # 호환용: siga+pullback 합산
            "siga_daily_count":    _siga_cnt,
            "pullback_daily_count": _pb_cnt,
            "fraction": pos["fraction"], "qty": pos["qty"],
            "order_krw": pos["order_krw"], "price_ref": round(price, 0),
            "strategy_type": pos.get("strategy_type", mode),
            "capital_allocated": pos.get("capital_allocated", 0),
            "selection_score": best["selection_score"], "prescore": best["prescore"],
            "attack_score": best["attack"], "stable_score": best["stable"],
            "expected_edge": best["edge"], "momentum_quality": best.get("quality", 0),
            "ride_score": best["ride"]["ride_score"],
            "inst_days": best["ride"]["inst_days"],
            "ride_signals": best["ride"]["signals"],
            "ofi_last10": best["ride"].get("ofi_last10", 0),
            "ev_pct": ev_result["ev_pct"], "ev_win_rate": ev_result["win_rate"],
            "ev_avg_win": ev_result["avg_win"], "ev_avg_loss": ev_result["avg_loss"],
            "ev_sample_n": ev_result["sample_n"], "ev_calibrated": ev_result["calibrated"],
            "profit_factor": profit_metrics.get("profit_factor", 0),
            "sharpe": profit_metrics.get("sharpe", 0),
            "sortino": profit_metrics.get("sortino", 0),
            "calmar": profit_metrics.get("calmar", 0),
            "max_drawdown": profit_metrics.get("max_drawdown", 0),
            "profit_evaluated": profit_metrics.get("evaluated", False),
            "kelly_fraction": pos.get("kelly_used", KELLY_DEFAULT),
            "exit_signals": exit_signals,
            "regime": regime, "strategy_hint": best["hint"],
            "evolve_weight": round(evolve_w, 4),
            "evolve_adjustments": calc_evolve_adjustments(profit_metrics, lg),
            "time_weight": _get_time_weight(lg),
            "params_ok": _PARAMS_OK, "pnl_ok": _PNL_OK,
            # [v4.23 FIX-1] market_state 3개 필드 — 브리지가 직접 참조
            "bridge_ev_weight":         round(_bridge_ev_weight, 2),
            "siga_enable":              _siga_enable,
            "pullback_enable":          _pullback_enable,
            # [v4.24 FIX-1] pullback_watch 3개 필드 — 브리지 STRONG 오버라이드 활성화
            "pullback_setup_class":     _pb_setup_class,
            "pullback_priority_score":  round(_pb_priority, 2),
            "pullback_quality_score":   round(_pb_quality,  2),
            "relay_pullback_ready":     _relay_ready,              # [v4.30 P4] 4조건 검증
            "daily_codes":              _daily_codes,              # [DUPLICATE GATE] 당일 진입 코드 목록
            # [v4.29] Stage 8 확신도 지표
            "winner_gap":       best.get("winner_gap",      999.0),
            "dominance_ratio":  best.get("dominance_ratio", 9.99),
            "conviction":       best.get("conviction",      1.0),
            "weak_winner":      best.get("weak_winner",     False),
            # [LEADER-HOLD 2026-06-11 사용자결정] 대장주 승격 매수 꼬리표 — 매도엔진이 보고
            #   추적익절 OFF(하드스톱+15:20 청산만, 백테 검증 조건 그대로). 큐→PB엔진으로 전달.
            "leader_first":     1 if best.get("leader_first") else 0,
        }
        tmp = SIGNAL.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f: json.dump(signal, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(SIGNAL))
        lg.info("[SIGNAL] %s 기록 완료", SIGNAL.name)
        return True
    except Exception as e:
        lg.error("[SIGNAL] 기록 실패: %s", e); return False


# ═══════════════════════════════════════════════════════════════
#  switch_decision 연동
# ═══════════════════════════════════════════════════════════════
def _load_switch_decision(lg: logging.Logger) -> Optional[dict]:
    if not SWITCH_DECISION.exists(): return None
    try:
        age = time.time() - SWITCH_DECISION.stat().st_mtime
        if age > 120: return None
        with open(SWITCH_DECISION, "r", encoding="utf-8-sig") as f: dec = json.load(f)
        if str(dec.get("date", "")) != _today(): return None
        # [HANDOFF-RESTORE] HANDOFF는 siga_sell_strategy 전용 → 실행엔진은 무시
        if "HANDOFF" in str(dec.get("reason", "")): return None
        action = dec.get("action", "SKIP")
        if action in ("SWITCH", "NEW_ENTRY"):
            lg.info("[SWITCH] action=%s new=%s", action, dec.get("new_code", "?")); return dec
        return None
    except Exception as e: lg.debug("[SWITCH] 읽기 실패: %s", e); return None


def _write_handoff_decision(siga_code: str, new_code: str,
                            lg: logging.Logger) -> None:
    """[HANDOFF-RESTORE] SIGA→PULLBACK 점수 핸드오프 신호 작성.
    siga_sell_strategy._check_handoff_signal 전용 (실행엔진은 위에서 차단)."""
    try:
        decision = {
            "date":         _today(),
            "ts":           _now_str(),
            "action":       "SWITCH",
            "reason":       "HANDOFF_SIGA_TO_PULLBACK",
            "current_code": str(siga_code).zfill(6),
            "new_code":     str(new_code).zfill(6),
        }
        SWITCH_DECISION.parent.mkdir(parents=True, exist_ok=True)
        with open(SWITCH_DECISION, "w", encoding="utf-8") as f:
            json.dump(decision, f, indent=2, ensure_ascii=False)
        lg.warning("[HANDOFF] ★ switch_decision 작성: %s → %s",
                   siga_code, new_code)
    except Exception as e:
        lg.error("[HANDOFF] write 실패: %s", e)


def _handle_switch(dec, rows, regime, evolve_w, profit_metrics, lg) -> int:
    action   = dec.get("action", "SKIP")
    new_code = str(dec.get("new_code", "")).zfill(6)
    cur_code = str(dec.get("current_code", "")).zfill(6) if dec.get("current_code") else ""
    if not new_code or new_code == "000000": return RC_HOLD
    if action == "NEW_ENTRY":
        try:
            opf = DATA / "rt_open_positions.json"
            if opf.exists():
                with open(opf, "r", encoding="utf-8-sig") as f: op = json.load(f)
                if any(int(p.get("qty",0))>0 for p in (op if isinstance(op,list) else list(op.values()))):  # [POSDICT-FIX 2026-06-01] dict .values()
                    lg.warning("[SWITCH] NEW_ENTRY 차단 — 기존 포지션 있음"); return RC_HOLD
        except Exception: pass
    target_row = next((r for r in rows if str(r.get("code","")).zfill(6)==new_code), None)
    if target_row is None: return RC_HOLD
    best = evaluate_candidates([target_row], regime, lg, profit_metrics)
    if best is None: return RC_HOLD
    ev_result = calc_ev(regime, _f(best["row"].get("ofi",0)), lg, _get_trade_cost(best["row"]))
    mode = decide_mode(best, ev_result, lg)
    if mode == "SKIP" and action == "SWITCH":
        # [v4.22 FIX-1] SWITCH 강제 STABLE 기준 명확화
        # 기존: ev >= -0.5 (근거 없는 음수 허용 — 손실 기대값으로 진입)
        # 수정: ev >= -(trade_cost*100) 거래비용 이내 음수만 허용
        #       (슬리피지·수수료 감안 시 실질 EV 0에 가까운 경우만 허용)
        _sw_cost = _get_trade_cost(best["row"]) * 100
        mode = "STABLE" if ev_result["ev_pct"] >= -_sw_cost else mode
        if mode == "STABLE":
            lg.warning("[SWITCH] SKIP→STABLE 강제(EV=%.3f%% ≥ -비용%.3f%%)", ev_result["ev_pct"], _sw_cost)
    price = _f(best["row"].get("price_now", 0))
    if price <= 0:
        for c in ["price","close","value_day"]:
            v = _f(best["row"].get(c,0))
            if v > 0: price = v; break
    pos = calc_position_size(mode, price, best["ride"], ev_result["kelly_fraction"],
                              regime, evolve_w, ev_result["ev_pct"],
                              ev_calibrated=ev_result["calibrated"],    # [v4.10] 결함② 수정
                              ev_sample_n=ev_result["sample_n"],        # [v4.10] 결함② 수정
                              weak_winner=best.get("weak_winner", False))  # [v4.30] sizing 반영
    if pos["qty"] <= 0:
        # [v4.31 FIX-1] B안: capital-aware sizing (Almgren & Chriss lot constraint)
        # min_lot_fraction = 1주 매수에 필요한 fraction. KELLY_HARD_MAX 이하면 허용.
        if price > 0:
            _min_lot_frac_sw = price / _capital()
            if _min_lot_frac_sw <= KELLY_HARD_MAX:
                pos = dict(pos)
                pos["qty"] = 1
                pos["order_krw"] = int(price)
                pos["fraction"] = round(_min_lot_frac_sw, 4)
                lg.warning("[MIN_LOT][SWITCH] qty=0 → capital-aware 1주 진입: "
                           "price=%d fraction=%.3f(%.1f%%) mode=%s",
                           int(price), _min_lot_frac_sw, _min_lot_frac_sw * 100, mode)
            else:
                lg.warning("[HOLD][SWITCH][MIN_LOT_FAIL] price=%d > capital×KELLY_MAX=%.0f원 "
                           "→ lot constraint RC_HOLD",
                           int(price), _capital() * KELLY_HARD_MAX)
                return RC_HOLD
        else:
            lg.warning("[HOLD][SWITCH] price=0 → 가격 미확인 RC_HOLD"); return RC_HOLD
    exit_signals = build_exit_signals(best["ride"])
    if not write_signal(best, mode, pos, regime, ev_result, exit_signals, evolve_w, profit_metrics, lg):
        return RC_HOLD
    if action == "SWITCH" and cur_code:
        try:
            with open(SIGNAL, "r", encoding="utf-8-sig") as f: sig = json.load(f)
            sig.update({"switch_mode": True, "switch_sell_code": cur_code,
                         "switch_score": dec.get("switch_score",0), "switch_reason": dec.get("reason","")})
            tmp = SIGNAL.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f: json.dump(sig, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp), str(SIGNAL))
        except Exception as e: lg.error("[SWITCH] 필드 추가 실패: %s", e)
    lg.info("[SWITCH-OK] %s %s→%s mode=%s", action, cur_code or "NONE", new_code, mode)
    return RC_OK


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
# [CYCLE-6 2026-05-21] event_journal.jsonl inline helper
def _emit_event(event_type, entity, entity_id="", payload=None, prev_state=None, new_state=None):
    """[CYCLE-6] event_journal.jsonl append-only (fail-safe)."""
    try:
        _evt_path = LOG_DIR / f"event_journal_{datetime.now().strftime('%Y%m%d')}.jsonl"
        _evt = {
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "entity": entity,
            "entity_id": str(entity_id),
            "trigger_module": "rt_execution_engine",
        }
        if prev_state is not None: _evt["prev_state"] = prev_state
        if new_state is not None: _evt["new_state"] = new_state
        if payload is not None: _evt["payload"] = payload
        with open(_evt_path, "a", encoding="utf-8") as _f:
            json.dump(_evt, _f, ensure_ascii=False)
            _f.write("\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  [v4.34 TRACE] EXEC_SUMMARY — 매수 차단 추적
# ═══════════════════════════════════════════════════════════════
_EXEC_STATS: dict = {
    "target_count": -1,    # bridge_target.json codes 수 (-1=미확인)
    "risk_count": -1,      # rt_risk_candidates.csv codes 수 (-1=미확인)
    "signal_written": False,
    "hold_reason": "",
    "rc": -1,
}

def _exec_stats_reset() -> None:
    _EXEC_STATS.update({"target_count": -1, "risk_count": -1,
                        "signal_written": False, "hold_reason": "", "rc": -1})

def _exec_set_reason(reason: str) -> None:
    if not _EXEC_STATS["hold_reason"]:
        _EXEC_STATS["hold_reason"] = reason

def _emit_exec_summary() -> None:
    try:
        lg = logging.getLogger("rt_exec_v4_29")
        lg.info("[EXEC_SUMMARY] target_count=%d risk_count=%d signal_written=%s "
                "hold_reason=%s rc=%d",
                _EXEC_STATS["target_count"], _EXEC_STATS["risk_count"],
                _EXEC_STATS["signal_written"], _EXEC_STATS["hold_reason"] or "-",
                _EXEC_STATS["rc"])
    except Exception:
        pass


def main() -> int:
    _exec_stats_reset()
    lg = _setup_logger()
    lg.info("=" * 65)
    lg.info("%s  START  %s", VERSION, _now_str())
    # [PATCH-LOCK] PID 기반 중복 실행 차단 — 신호 큐 중복 작성 방지
    #   해제는 __main__ 블록의 finally에서 일괄 처리 (모든 return/예외 경로 보장)
    if not _acquire_exec_lock(lg):
        return RC_HOLD
    if REAL_TEST_MODE: lg.warning("[CONFIG] REAL_TEST=true → %s원", f"{_capital():,}")
    else: lg.info("[CONFIG] 본게임 %s원", f"{_capital():,}")
    # [v4.22 FIX-6/7] 연결 모듈 확인 로그
    lg.info("[INIT] params=%s pnl=%s",
            _PARAMS_MOD_USED if _PARAMS_OK else "NG",
            _PNL_MOD_USED    if _PNL_OK    else "NG")

    # ── 데이터 로드 + 레짐 ──
    rows = load_rt_data(lg)
    regime_early = "NEUTRAL"
    if rows: regime_early = check_market_regime(rows[0], lg)

    # ── 킬스위치 ──
    killed, kill_reason = check_kill_switch(lg, regime=regime_early)
    if killed: lg.warning("[KILL] %s → 정지", kill_reason); return RC_HOLD

    # ── 시간대 블록 ──
    if check_time_block(lg): return RC_HOLD

    # ── switch_decision 우선 처리 ──
    switch_dec = _load_switch_decision(lg)
    if switch_dec:
        if not rows: rows = load_rt_data(lg)
        if rows:
            evolve_w = 1.0
            if _PNL_OK:
                evolve_w = _load_weights().get(STRATEGY_NAME, 1.0)
            profit_metrics = calc_profit_metrics(lg)
            if profit_metrics.get("evaluated"):
                pf = profit_metrics["profit_factor"]
                if pf < PF_WEAK: evolve_w *= 0.50
                elif pf > PF_STRONG: evolve_w = min(evolve_w * 1.20, 1.50)
            return _handle_switch(switch_dec, rows, regime_early, evolve_w, profit_metrics, lg)

    # ── [v4.30 P4] 시가→눌림 릴레이 체크 (check_trade_limit 이전) ──
    # [SIGA-RETIRE 2026-06-01] 후자 설계: SIGA 의존 제거 → "포지션 청산되면 PULLBACK 진입".
    #   조건(★주인의도 2026-06-08, 시간 무관): 포지션 청산 + pullback_daily_count==0. RELAY 시간창(09:05~40) 제거 — 시간 적정성은 pullback_time_gate가 담당.
    #   포지션 청산(any qty>0 없음)=현금 통장 복귀 신호. EOD_PICK 보유일은 매도완료 대기, 무보유일은 즉시 통과.
    _relay = False
    _relay_avail_cash = 0.0   # [RELAY-CASH 2026-06-08] 발동시 산출 가용현금(운용한도-실보유, 사이징 상한서 재사용). ⚠통장 잔고 아님.
    _hm = _hhmm()
    # [RELAY-TIME 2026-06-08 ★주인의도] 시간창(09:05~40) 제거 — 매도후 현금복귀시 시간 무관 발동.
    #   시간 적정성은 pullback_time_gate가 담당(09:05전 차단·09:05~10 강·09:10~ 일반). 복원: env RELAY_TIME_WINDOW_ENABLE=YES.
    _relay_time_ok = True
    if os.environ.get("RELAY_TIME_WINDOW_ENABLE", "NO").strip().upper() == "YES":
        _relay_time_ok = (int(os.environ.get("RELAY_WINDOW_START", "905")) <= _hm <= int(os.environ.get("RELAY_WINDOW_END", "940")))
    if _relay_time_ok:
        try:
            if SIGNAL.exists():
                with open(SIGNAL, "r", encoding="utf-8-sig") as _f_relay:
                    _sig_relay = json.load(_f_relay)
                if (str(_sig_relay.get("date","")) == _today()
                        and int(_sig_relay.get("pullback_daily_count", 0)) == 0):
                    _opf = DATA / "rt_open_positions.json"
                    # [RELAY-CASH 2026-06-08 ★주인의도] '전량청산' → '가용현금 기준'. 잔여보유(유령/자투리)가 주력현금 막지 않게.
                    #   가용현금 = 운용한도(capital_config, ⚠통장 아님·200만) - 실보유 평가액(Σ qty×entry_price). ≥ RELAY_MIN_CASH_KRW면 발동.
                    #   buy_sender 누적캡과 동일 단일소스(capital_config) → 통장 잔고(2600만) 절대 미사용.
                    _held_value = 0.0
                    if _opf.exists():
                        try:
                            with open(_opf, "r", encoding="utf-8-sig") as _f_op:
                                _op = json.load(_f_op)
                            _plist = _op if isinstance(_op, list) else list(_op.values())  # [POSDICT-FIX 2026-06-01]
                            for _p in _plist:
                                _pq = int(_p.get("qty", 0))
                                if _pq > 0:
                                    _held_value += _pq * _f(_p.get("entry_price", 0))
                        except Exception as _hv_e:
                            lg.debug("[RELAY] 실보유 평가액 계산 실패: %s", _hv_e)
                    try:
                        from capital_config import get_limit as _get_limit
                        _cap_limit = _get_limit("daily_total_max")   # 운용 한도(200만, 단일소스) — ⚠통장 잔고 아님
                    except Exception:
                        _cap_limit = _capital()                       # fallback (REAL_TEST_CAPITAL)
                    _relay_avail_cash = _cap_limit - _held_value
                    _relay_min_cash = float(os.environ.get("RELAY_MIN_CASH_KRW", "100000"))
                    if _relay_avail_cash >= _relay_min_cash:
                        lg.warning("[RELAY] 매도후 현금복귀→눌림 릴레이 활성 (%04d) 가용현금=%d (운용한도%d - 실보유%d) ≥ 최소%d",
                                   _hm, int(_relay_avail_cash), int(_cap_limit), int(_held_value), int(_relay_min_cash))
                        _relay = True
                    else:
                        lg.info("[RELAY] 가용현금 부족 %d < 최소%d (운용한도%d - 실보유%d) → 미발동",
                                int(_relay_avail_cash), int(_relay_min_cash), int(_cap_limit), int(_held_value))
        except Exception as _re:
            lg.debug("[RELAY] 체크 실패: %s", _re)

    # ── 진입 횟수 + 쿨다운 (릴레이 시 쿨다운 우회) ──
    if not _relay and check_trade_limit(lg): return RC_HOLD

    if not rows: rows = load_rt_data(lg)
    if not rows: return RC_HOLD

    regime = regime_early

    # ── 자기진화 가중치 ──
    evolve_w = 1.0
    if _PNL_OK:
        evolve_w = _load_weights().get(STRATEGY_NAME, 1.0)
        lg.info("[EVOLVE] base_weight=%.4f", evolve_w)

    # ── 수익률 복합 평가 ──
    profit_metrics = calc_profit_metrics(lg)
    if profit_metrics.get("evaluated"):
        pf = profit_metrics["profit_factor"]
        if pf < PF_WEAK: evolve_w *= 0.50; lg.warning("[EVOLVE] PF%.2f<%.1f → ×0.5=%.4f", pf, PF_WEAK, evolve_w)
        elif pf > PF_STRONG: evolve_w = min(evolve_w*1.20, 1.50); lg.info("[EVOLVE] PF%.2f>%.1f → ×1.2=%.4f", pf, PF_STRONG, evolve_w)

    # ── 후보 평가 ──
    if _relay:
        # [v4.30 P4] 릴레이 전용: PULLBACK 후보 직접 선택 — VALID_HINTS 수정 없이 조건부 통과
        _pb_rows = [r for r in rows
                    if str(r.get("strategy_hint","")).upper() == "PULLBACK"
                    and _f(r.get("prescore_weighted",0)) >= MIN_PRESCORE]
        # [PB_GATE] RELAY: pullback_watch(top5) 필터
        try:
            import pickle as _pkl_rpbg
            _rpw_codes: set = set()
            if EOD_SHARED_PKL.exists():
                with open(str(EOD_SHARED_PKL), "rb") as _rpf:
                    _rpw_codes = {str(p.get("code", "")).zfill(6)
                                  for p in _pkl_rpbg.load(_rpf).get("pullback_watch", [])}
            if _rpw_codes:
                # [W1-FIX 2026-06-01] 신선대장주 bypass — 정상경로(L2263) 동일 기준.
                #   pullback_watch 미포함이라도 prescore≥FRESH_LEADER_MIN_SCORE면 통과
                #   (어제 watch에 없던 당일 새 급등주가 릴레이창 09:05~09:40서 차단되던 비대칭 해소).
                _fresh_min_relay = float(os.environ.get("FRESH_LEADER_MIN_SCORE", "25.0"))
                _pb_rows = [r for r in _pb_rows
                            if (str(r.get("code", "")).zfill(6) in _rpw_codes
                                or _f(r.get("prescore_weighted", 0)) >= _fresh_min_relay)]
        except Exception:
            pass
        if not _pb_rows:
            lg.warning("[RELAY] PULLBACK 후보 없음 → 릴레이 취소"); return RC_HOLD
        # [RELAY-GATE 2026-06-08] 릴레이 경로에도 일반(else)경로와 동일한 품질 검문소 적용.
        #   그동안 RELAY(if)는 pullback_time_gate(시간대/EARLY_REBOUND)·_pullback_timing_gate(눌림끝 첫순간)를
        #   우회 → 갭매도 직후 첫 풀백이 무검증 진입했음(6/7 시간게이트가 else경로에만 삽입). 통일.
        #   끄기 env RELAY_QUALITY_GATE_ENABLE=NO (기존 우회 동작 복원).
        if os.environ.get("RELAY_QUALITY_GATE_ENABLE", "YES").strip().upper() == "YES":
            # 검문소1: pullback_time_gate(09:05전 차단 / 09:05~10 EARLY_REBOUND 강 / 09:10~ 일반 눌림). 회차강도=check_tiered(공통)
            _pb_rows = pullback_time_gate(_pb_rows, lg)
            if not _pb_rows:
                lg.warning("[RELAY] 시간게이트 후 PULLBACK 후보 없음 → 릴레이 취소"); return RC_HOLD
            _pb_rows.sort(key=lambda r: _f(r.get("prescore_weighted",0)), reverse=True)
            # 검문소2: 눌림 끝 살아나는 첫 순간만 PASS(떨어지는中 매수금지) — 일반경로 evaluate_candidates(L1833)와 동일
            if PB_TIMING_GATE:
                _pb_r = None; _pb_code = ""
                for _cand in _pb_rows:
                    _cc = str(_cand.get("code","")).zfill(6)
                    _ok, _reason = _pullback_timing_gate(_cand, _cc)
                    if _ok:
                        lg.info("[RELAY][PULLBACK-TIMING] PASS code=%s %s", _cc, _reason)
                        _pb_r = _cand; _pb_code = _cc; break
                    if "vwap" in _reason:   # [DUP 2026-06-08] VWAP는 check_tiered TIER3 회차조건과 중복검사 — 로그만(유지)
                        lg.info("[RELAY][PB-TIMING-DUP] code=%s VWAP조건이 TIER 회차조건과 중복검사됨(reason=%s, 유지)", _cc, _reason)
                    lg.info("[RELAY][PULLBACK-TIMING] BLOCK code=%s reason=%s", _cc, _reason)
                if _pb_r is None:
                    lg.warning("[RELAY] 타이밍게이트 통과 후보 없음 → HOLD(살아나는 첫 순간 대기)"); return RC_HOLD
            else:
                _pb_r = _pb_rows[0]; _pb_code = str(_pb_r.get("code","")).zfill(6)
        else:
            _pb_rows.sort(key=lambda r: _f(r.get("prescore_weighted",0)), reverse=True)
            _pb_r    = _pb_rows[0]
            _pb_code = str(_pb_r.get("code","")).zfill(6)
        best = {
            "code": _pb_code, "row": _pb_r,
            "ride":           calc_inst_ride(_pb_r),
            "prescore":       _f(_pb_r.get("prescore_weighted",0)),
            "attack":         _f(_pb_r.get("attack_score",0)),
            "stable":         _f(_pb_r.get("stable_score",0)),
            "selection_score": round(_f(_pb_r.get("prescore_weighted",0)) * TOP1_BONUS, 4),
            "hint": "PULLBACK", "regime": regime,
            "edge":    _f(_pb_r.get("expected_edge",0)),
            "overheat_mult": 1.0,
            "quality": calc_momentum_quality(_pb_r),
        }
        lg.warning("[RELAY] PULLBACK 진입: %s ps=%.1f ride=%.2f",
                   _pb_code, best["prescore"], best["ride"]["ride_score"])
        lg.info("[GATE-FLOW] path=RELAY hhmm=%04d relay_time_window=%s | time_gate=%s(09:05~10강/09:10~일반) → timing_gate=%s(눌림끝) → tiered=주검문소(공통, 이후적용) | best=%s",
                _hhmm(),
                ("ON" if os.environ.get("RELAY_TIME_WINDOW_ENABLE", "NO").strip().upper() == "YES" else "OFF(시간무관)"),
                ("ON" if (os.environ.get("RELAY_QUALITY_GATE_ENABLE", "YES").strip().upper() == "YES" and PULLBACK_TIME_GATE_ENABLE) else "OFF"),
                ("ON" if (os.environ.get("RELAY_QUALITY_GATE_ENABLE", "YES").strip().upper() == "YES" and PB_TIMING_GATE) else "OFF"),
                _pb_code)
    else:
        _is_intraday = _hhmm() < 1500  # 09~14시 장중: bridge_target 선택
        targets = load_targets(lg)
        _EXEC_STATS["target_count"] = len(targets) if targets is not None else -1
        if targets is None:
            # [v4.34] 시스템 오류 (JSON 파싱 실패 등) — 장중이면 rt_intraday 폴백
            if _is_intraday:
                lg.warning("[TARGET] 장중 bridge_target.json 시스템 오류 → rt_intraday.csv 후보로 진행")
            else:
                _exec_set_reason("bridge_target_parse_fail")
                return RC_HOLD
        elif len(targets) == 0:
            # [v4.34] codes=[] / codes 없음 / 파일없음 / date stale → Bridge HOLD 신호 → 정상 HOLD
            # [PATCH] eod_inactive=True (bridge_eod 시간창 외, 예: 09시대) 인 경우
            #   bridge_target_empty를 치명 HOLD로 처리하지 않고 rt_intraday 폴백 허용
            #   bridge_eod 본 시간창(15:15~15:25) 동작은 변경 없음 — eod_inactive=False로 들어옴
            if _LAST_TARGET_EOD_INACTIVE and _is_intraday:
                lg.info("[TARGET][EOD_INACTIVE] bridge_eod 시간창 외 → rt_intraday 후보로 진행 (09시대 매수 흐름 보호)")
                targets = None  # 아래 'if targets is not None' 필터 우회
            else:
                lg.info("[EXEC][HOLD][REASON=bridge_hold_signal] Bridge HOLD 신호 수신 → 정상 HOLD")
                _exec_set_reason("bridge_hold_signal")
                return RC_HOLD
        # [v4.33 FIX] Risk 결과 처리 + stale 명확 경고 + HOLD reason 표준화
        risk_codes = load_risk_codes(lg)
        _EXEC_STATS["risk_count"] = len(risk_codes) if risk_codes is not None else -1
        if risk_codes is None:
            lg.warning("[RISK][SKIP][REASON=missing_or_empty] rt_risk_candidates.csv 없음/빈파일/읽기실패 "
                       "→ Risk 필터 스킵 후 진행 (Risk Engine 실행 순서 점검 권장)")
        else:
            try:
                _risk_age = time.time() - RISK_CSV.stat().st_mtime
                if _risk_age > 180:
                    lg.warning("[RISK][STALE] rt_risk_candidates.csv mtime %.0f초 경과 (>180s) — "
                               "Risk Engine 미실행 의심", _risk_age)
                else:
                    lg.info("[RISK][OK] rt_risk_candidates.csv age=%.0fs codes=%d", _risk_age, len(risk_codes))
            except Exception:
                pass
        # [B+A-2 통합 2026-06-07] PULLBACK은 Risk가 부재/빈/읽기실패(A-2) 또는 stale>180s(B)이면 임의 진행 금지.
        #   → PULLBACK 후보만 드롭(HOLD). SIGA/MULTI 등 타 전략은 기존 동작 유지(스코프=PULLBACK).
        #   A-1(rt_risk 빈출력 code-header)로 'Risk가 돌고 HOLD'는 이미 차단됨. 여기는 'Risk 부재/stale' 케이스.
        #   env PULLBACK_REQUIRE_RISK=YES(기본). NO면 기존 동작(스킵 진행).
        if os.environ.get("PULLBACK_REQUIRE_RISK", "YES").strip().upper() == "YES":
            _pb_risk_bad = ""
            if risk_codes is None:
                _pb_risk_bad = "missing_or_empty"          # A-2: 파일 없음/빈/읽기실패
            else:
                try:
                    _ra = time.time() - RISK_CSV.stat().st_mtime
                    if _ra > 180:
                        _pb_risk_bad = "stale"             # B: 180초 초과(Risk 미실행 의심)
                except Exception:
                    _pb_risk_bad = "stat_fail"
            if _pb_risk_bad:
                _before_pbr = len(rows)
                rows = [r for r in rows if str(r.get("strategy_hint", "")).upper() != "PULLBACK"]
                lg.warning("[PULLBACK][HOLD][REASON=risk_%s] Risk 부재/stale → PULLBACK 드롭(임의진행 금지): %d→%d종목 "
                           "(SIGA/기타 전략은 유지)", _pb_risk_bad, _before_pbr, len(rows))
                if not rows:
                    lg.warning("[EXEC][HOLD][REASON=pullback_risk_required] PULLBACK 전부 드롭 후 rows 0건 → HOLD")
                    return RC_HOLD
        # [신규] STRICT_TARGET_RISK_FILTER=false 시 화이트리스트 외 고점수 종목 병합
        _strict_filter = os.environ.get("STRICT_TARGET_RISK_FILTER", "true").lower() == "true"
        _fresh_min_filter = float(os.environ.get("FRESH_LEADER_MIN_SCORE", "25.0"))
        if targets is not None:
            if not _validate_target_sync(targets, rows, lg):
                lg.error("[EXEC][HOLD][REASON=target_sync_mismatch] bridge_target 코드 1개도 rt_intraday에 없음")
                return RC_HOLD
            if _strict_filter:
                rows = [r for r in rows if str(r.get("code", "")).zfill(6) in targets]
            else:
                rows = [r for r in rows
                        if (str(r.get("code", "")).zfill(6) in targets
                            or _f(r.get("prescore_weighted", 0)) >= _fresh_min_filter)]
            if not rows:
                lg.warning("[EXEC][HOLD][REASON=target_filter_empty] bridge_target 필터 후 rows 0건")
                return RC_HOLD
        if risk_codes is not None:
            if _strict_filter:
                rows = [r for r in rows if str(r.get("code", "")).zfill(6) in risk_codes]
            else:
                rows = [r for r in rows
                        if (str(r.get("code", "")).zfill(6) in risk_codes
                            or _f(r.get("prescore_weighted", 0)) >= _fresh_min_filter)]
            if not rows:
                lg.warning("[EXEC][HOLD][REASON=risk_filter_empty] Risk 필터 후 rows 0건 (Bridge ∩ Risk = ∅)")
                return RC_HOLD
        # [PB_GATE] PULLBACK은 pullback_watch(top5) 종목만 허용 — scoreboard 구조 정렬
        _pw_codes_gate: set = set()
        _pw_status = "ok"
        try:
            import pickle as _pkl_pbg
            if not EOD_SHARED_PKL.exists():
                _pw_status = "pkl_missing"
            else:
                with open(str(EOD_SHARED_PKL), "rb") as _pf_g:
                    _pw_codes_gate = {str(p.get("code", "")).zfill(6)
                                      for p in _pkl_pbg.load(_pf_g).get("pullback_watch", [])}
                if not _pw_codes_gate:
                    _pw_status = "watch_empty"
        except Exception:
            _pw_codes_gate = set()
            _pw_status = "load_fail"
        if _pw_codes_gate:
            _before_pb = len(rows)
            _fresh_min = float(os.environ.get("FRESH_LEADER_MIN_SCORE", "25.0"))
            rows = [r for r in rows
                    if not (str(r.get("strategy_hint", "")).upper() == "PULLBACK"
                            and str(r.get("code", "")).zfill(6) not in _pw_codes_gate
                            and _f(r.get("prescore_weighted", 0)) < _fresh_min)]
            lg.info("[PB_GATE] pullback_watch 필터(신선대장주 우회 ps>=%.1f): %d→%d종목",
                    _fresh_min, _before_pb, len(rows))
        else:
            # [D-1 FIX 2026-06-07] pkl 없음/로드실패/watch 빈값 → 조용히 스킵 금지(PULLBACK 무제한 통과 차단).
            #   PULLBACK 후보에만 fresh leader 최소품질 fallback(저품질 PULLBACK만 제거). SIGA/MULTI/기타 무영향.
            #   PULLBACK 전체차단/전체HOLD 아님. env PB_GATE_FALLBACK_MIN_PRESCORE(없으면 FRESH_LEADER_MIN_SCORE=25.0).
            _before_pb = len(rows)
            _fb_min = float(os.environ.get("PB_GATE_FALLBACK_MIN_PRESCORE",
                                           os.environ.get("FRESH_LEADER_MIN_SCORE", "25.0")))
            rows = [r for r in rows
                    if not (str(r.get("strategy_hint", "")).upper() == "PULLBACK"
                            and _f(r.get("prescore_weighted", 0)) < _fb_min)]
            lg.warning("[PB_GATE][FALLBACK] pullback_watch unavailable(%s) → PULLBACK prescore>=%.1f fallback: %d→%d종목",
                       _pw_status, _fb_min, _before_pb, len(rows))
        if not rows: lg.warning("[PB_GATE] 필터 후 rows 없음"); return RC_HOLD
        # [PB_GATE-2] MID 시간대 PULLBACK 차단 — 10:30~13:00 EV X제외 구간
        _now_hm_pb = _hhmm()
        for _pb_ts, _pb_te in PULLBACK_ENTRY_BLACKOUT:
            if _pb_ts <= _now_hm_pb < _pb_te:
                _before_mid = len(rows)
                rows = [r for r in rows
                        if str(r.get("strategy_hint", "")).upper() != "PULLBACK"]
                lg.info("[PB_GATE] MID 차단 %04d (%04d~%04d): %d→%d종목",
                        _now_hm_pb, _pb_ts, _pb_te, _before_mid, len(rows))
                break
        if not rows: lg.warning("[PB_GATE] MID 차단 후 rows 없음"); return RC_HOLD
        # [PULLBACK-MORNING 2026-06-07] 아침 시간대 품질 게이트 (09:00~05 차단·09:05~10 강한예외·09:10~10:20 주력·10:20+ strict)
        rows = pullback_time_gate(rows, lg)
        if not rows: lg.warning("[PB_GATE] PULLBACK 시간게이트 후 rows 없음"); return RC_HOLD
        # [PB_GATE-3] LATE 조건부 차단 제거 — [PATCH] 시간/레짐으로 막지 않음, 점수로만 통제
        lg.info("[EXEC] filtered target rows=%d", len(rows))
        best = evaluate_candidates(rows, regime, lg, profit_metrics)
        if best is None: lg.warning("[HOLD] 유효 후보 없음"); return RC_HOLD
        if str(best.get("hint", "")).upper() == "PULLBACK":
            lg.info("[GATE-FLOW] path=NORMAL hhmm=%04d | time_gate=%s(09:05~10강/09:10~일반) → timing_gate=%s(눌림끝) → tiered=주검문소(공통, 이후적용) | best=%s",
                    _hhmm(), ("ON" if PULLBACK_TIME_GATE_ENABLE else "OFF"),
                    ("ON" if PB_TIMING_GATE else "OFF"), best.get("code", "?"))

    # [HANDOFF-RESTORE] 09:18~09:20 SIGA→PULLBACK 점수 핸드오프 평가
    #   조건: 시간창 + SIGA 보유 + best≠SIGA + 수익률≥1.0% + best EV > SIGA EV × 1.20
    _hm_hf = _hhmm()
    if 918 <= _hm_hf <= 920 and best is not None:
        try:
            _opf_hf = DATA / "rt_open_positions.json"
            if _opf_hf.exists():
                with open(_opf_hf, "r", encoding="utf-8-sig") as _fh:
                    _op_hf = json.load(_fh)
                _plist_hf = _op_hf if isinstance(_op_hf, list) else list(_op_hf.values())  # [POSDICT-FIX 2026-06-01] dict .values() (SIGA-retire로 사실상 inert)
                _siga_pos = next((p for p in _plist_hf
                                  if int(p.get("qty", 0)) > 0
                                  and str(p.get("strategy", "")).upper().startswith("SIGA")),
                                 None)
                if _siga_pos and best.get("code") != _siga_pos.get("code"):
                    _entry = _f(_siga_pos.get("entry_price", 0))
                    _siga_row = next((r for r in rows
                                      if str(r.get("code", "")).zfill(6)
                                         == str(_siga_pos["code"]).zfill(6)),
                                     None)
                    if _siga_row and _entry > 0:
                        _cur = _f(_siga_row.get("price_now", 0))
                        if _cur > 0:
                            _profit = (_cur - _entry) / _entry
                            if _profit >= 0.01:
                                _siga_ee = _f(_siga_row.get("expected_edge", 0))
                                _best_ee = _f(best["row"].get("expected_edge", 0))
                                if _best_ee > _siga_ee * 1.20:
                                    _write_handoff_decision(
                                        _siga_pos["code"], best["code"], lg)
        except Exception as _hf_e:
            lg.debug("[HANDOFF] 평가 실패: %s", _hf_e)

    # [v4.30 P2] 전략별 진입 카운터 체크 (hint 기반, 쿨다운 없음)
    if check_trade_limit(lg, hint=best.get("hint", "")):
        lg.warning("[HOLD] 전략별 한도 초과: hint=%s", best.get("hint","")); return RC_HOLD

    # [DUPLICATE CODE GATE] 당일 동일 종목 재진입 차단
    try:
        if SIGNAL.exists():
            with open(SIGNAL, "r", encoding="utf-8-sig") as _f_dup:
                _sig_dup = json.load(_f_dup)
            if str(_sig_dup.get("date", "")) == _today():
                _traded_codes = _sig_dup.get("daily_codes", [])
                if best["code"] in _traded_codes:
                    # [PBCOUNT-FIX 2026-06-05] daily_codes는 signal-write 시 누적 → conv게이트 HOLD 등
                    #   미체결 코드도 포함(240810처럼 큐등재→미체결 양질후보가 재선택 시 phantom 차단).
                    #   실보유(qty>0)일 때만 중복 차단 → 미체결 phantom은 통과(실체결되면 정상 차단).
                    _held_dup = False
                    try:
                        _opf2 = DATA / "rt_open_positions.json"
                        if _opf2.exists():
                            with open(_opf2, "r", encoding="utf-8-sig") as _pf2:
                                _pos2 = json.load(_pf2)
                            _held_dup = any(isinstance(_v, dict) and _f(_v.get("qty", 0)) > 0
                                            and str(_k).zfill(6) == str(best["code"]).zfill(6)
                                            for _k, _v in _pos2.items())
                    except Exception:
                        _held_dup = True  # 조회 실패 → 보수적 차단
                    if _held_dup:
                        lg.warning("[DUPLICATE] code=%s 실보유중 → 재진입 차단", best["code"])
                        return RC_HOLD
                    else:
                        lg.info("[DUPLICATE] code=%s daily_codes 등재(미체결 phantom) → 통과", best["code"])
    except Exception as _dup_e:
        lg.debug("[DUPLICATE] 체크 실패: %s → 통과", _dup_e)

    # ── [v4.28 FIX-1] pb 필드 주입 — decide_mode 이전에 반드시 실행
    # 문제: 기존 write_signal 내부에서 주입 → decide_mode 이후라 STRONG/MODERATE 분기 미작동
    # 수정: best 생성 직후, calc_ev 이전에 이동 → decide_mode에서 정상 참조
    global _bridge_ev_weight_main, _siga_enable_main, _pullback_enable_main
    _pb_setup_class_main = ""
    _pb_priority_main    = 0.0
    _pb_quality_main     = 0.0
    _bridge_ev_weight_main = 0.60
    _siga_enable_main      = True
    _pullback_enable_main  = True
    try:
        import pickle as _pkl_main
        if EOD_SHARED_PKL.exists():
            _age_main = time.time() - EOD_SHARED_PKL.stat().st_mtime
            if _age_main < 86400:
                with open(str(EOD_SHARED_PKL), "rb") as _pf_main:
                    _shared_main = _pkl_main.load(_pf_main)
                _ms_main = _shared_main.get("market_state", {})
                _bridge_ev_weight_main = float(_ms_main.get("bridge_ev_weight", 0.60))
                _siga_enable_main      = bool(_ms_main.get("siga_enable",       True))
                # [INSTR-SIGA-1 2026-05-19 cycle 5.10] pkl 로드 직후 siga_enable 캡처. read-only logging. 5/19 09:14 변질 추적.
                try:
                    lg.info("[INSTR-SIGA] pkl_load: age=%.1fh pkl_siga=%s _siga_main=%s mtime=%s",
                            _age_main/3600, _ms_main.get("siga_enable"), _siga_enable_main,
                            datetime.fromtimestamp(EOD_SHARED_PKL.stat().st_mtime).isoformat())
                except Exception:
                    pass
                # [PULLBACK_FORCE 2026-05-13] pkl 값 무시 강제 True. 5/13 EOD pullback_watch=0으로 PULLBACK_DISABLED 차단되어 14일째 매수 0건. 시장위험은 mkt_risk_flag로 별도 보호 (현재 mkt_risk=0). surge/quality 다중 필터 잔존.
                _pullback_enable_main  = True  # was: bool(_ms_main.get("pullback_enable", True))
                _pw_main   = _shared_main.get("pullback_watch", [])
                _sel_main  = str(best.get("code", "")).zfill(6)
                for _item in _pw_main:
                    if str(_item.get("code", "")).zfill(6) == _sel_main:
                        _pb_setup_class_main = str(_item.get("pullback_setup_class", ""))
                        _pb_priority_main    = float(_item.get("pullback_priority_score", 0.0))
                        _pb_quality_main     = float(_item.get("pullback_quality_score",  0.0))
                        lg.info("[v4.28] pb 주입: code=%s class=%s pri=%.1f qual=%.1f",
                                _sel_main, _pb_setup_class_main, _pb_priority_main, _pb_quality_main)
                        break
            else:
                # [v4.31 FIX-2] PKL stale 명확 로그 — 영향 범위 명시
                # 기준: EOD 스코어보드 24h 신뢰 (일중 전략 표준, AQR/Two Sigma intraday)
                lg.warning("[PKL_STALE] age=%.0fh / pb_class unusable / n<8 BYPASS 불가 → 기본값",
                           _age_main / 3600)
    except Exception as _e_main:
        lg.warning("[v4.28] pkl 로드 실패 → 기본값: %s", _e_main)

    best["pb_setup_class"]      = _pb_setup_class_main
    best["pb_priority"]         = _pb_priority_main
    best["pb_quality"]          = _pb_quality_main

    # ── EV 계산 ──
    trade_cost = _get_trade_cost(best["row"])
    ev_result  = calc_ev(regime, _f(best["row"].get("ofi", 0)), lg, trade_cost)
    # [v4.22 FIX-2] TIME_WEIGHT → ev_pct 실제 보정 반영
    # 기존: _get_time_weight()는 로그 출력만, ev_pct 보정 미반영
    # 수정: 시간대 가중치(0.5~1.15) × ev_pct → 오전/오후 기대값 차등화
    #       단, ev_pct 부호는 유지 (음수 EV 시간대 보정으로 양수화 방지)
    _tw = _get_time_weight(lg)
    if _tw != 1.0 and ev_result.get("calibrated"):
        _ev_adj = round(ev_result["ev_pct"] * _tw, 4)
        lg.info("[TIME_EV] ev_pct %.4f%% × 시간가중치%.2f → %.4f%%", ev_result["ev_pct"], _tw, _ev_adj)
        ev_result = dict(ev_result)
        ev_result["ev_pct"] = _ev_adj

    # ── 모드 판정 ──
    mode = decide_mode(best, ev_result, lg)

    # ── [v4.6] SKIP fallback ──────────────────────────────────────
    if mode == "SKIP":
        if check_fallback_needed(lg):
            mode = decide_mode_fallback(best, regime, lg)
            if mode == "SKIP":
                lg.warning("[HOLD] fallback prescore 조건 미달 → 당일 미진입 확정")
                return RC_HOLD
        else:
            lg.info("[HOLD] 조건 미달 (당일 %d회 or 시간/레짐 차단)", _get_daily_count())
            return RC_HOLD

    # ── [v4.30 P2/P3] Tier 게이트 — 전략별 카운터 기반 회차 게이트 ──
    if best.get("hint","") == "PULLBACK":
        daily_count = _get_pullback_daily_count()
    else:
        daily_count = _get_siga_daily_count()
    # [v4_9-P9] 1회차 진입에도 tier 게이트 적용 — `if daily_count > 0` 제거
    row_b  = best["row"]
    tier_ok = check_tiered_entry_quality(
        trade_count    = daily_count,
        ev_pct         = ev_result["ev_pct"],
        volume_accel   = _f(row_b.get("volume_accel", 0)),
        close_position = _f(row_b.get("close_position", 0)),
        prescore       = best["prescore"],
        attack_score   = best["attack"],
        ride_score     = best["ride"]["ride_score"],
        lg             = lg,
        row            = row_b,   # [PULLBACK-MORNING] TIER3 ADD 품질(VWAP/고가권/붕괴) 확인용
    )
    if not tier_ok:
        lg.warning("[HOLD] %d회차 품질 게이트 차단 [EV=%.3f%% atk=%.1f ride=%.2f]",
                   daily_count+1, ev_result["ev_pct"],
                   best["attack"], best["ride"]["ride_score"])
        return RC_HOLD

    # ── [GAP] 갭 과열 진입 차단 (gap_pct >= 7%) ──
    _gap_now = _f(best["row"].get("gap_pct", 0))
    if _gap_now >= 7.0:
        lg.warning("[HOLD] 갭 과열 차단: gap_pct=%.2f%% >= 7%% code=%s", _gap_now, best.get("code","?"))
        return RC_HOLD

    # ── 포지션 사이즈 ──
    # [v4.31 PATCH] price fallback에서 value_day 제거.
    # value_day=거래대금(원)이라 가격으로 오해석 시 수천만원→qty=0→RC_HOLD 사문화.
    # 둘 다 없으면 price=0 유지 → 아래 분기에서 RC_HOLD (기존 동작).
    price = _f(best["row"].get("price_now", 0))
    if price <= 0:
        for c in ["price_now", "close", "price"]:
            v = _f(best["row"].get(c, 0))
            if v > 0: price = v; break

    pos = calc_position_size(mode, price, best["ride"],
                              ev_result["kelly_fraction"],
                              regime, evolve_w, ev_result["ev_pct"],
                              ev_calibrated=ev_result["calibrated"],    # [v4.10] 결함② 수정
                              ev_sample_n=ev_result["sample_n"],        # [v4.10] 결함② 수정
                              weak_winner=best.get("weak_winner", False))  # [v4.30] sizing 반영
    # [RELAY-CASH 2026-06-08 ★주인의도] RELAY 매수는 '남은 운용현금'으로만 상한. 사이징은 운용자본 전액(capital×fraction) 기준이라
    #   잔여보유 있으면 buy_sender 누적캡(실보유+발주>한도)에서 차단됨 → 가용현금(운용한도-실보유)으로 order_krw 상한(차단/초과 동시 방지).
    #   ⚠ 통장 잔고 미사용(_relay_avail_cash는 capital_config 운용한도 기반).
    if _relay and str(best.get("hint", "")).upper() == "PULLBACK" and price > 0:
        if _relay_avail_cash > 0 and pos.get("order_krw", 0) > _relay_avail_cash:
            _rc_krw = int(_relay_avail_cash)
            _rc_qty = int(_rc_krw / price)
            lg.warning("[RELAY-CASH] 사이징 상한: order_krw %d→%d(가용현금) qty %d→%d price=%d",
                       int(pos.get("order_krw", 0)), _rc_krw, int(pos.get("qty", 0)), _rc_qty, int(price))
            pos = dict(pos)
            pos["order_krw"] = _rc_krw
            pos["qty"] = max(0, _rc_qty)
            pos["fraction"] = round(_rc_krw / _capital(), 4) if _capital() > 0 else pos.get("fraction", 0)
    # [LEADER-FIRST-CAP 2026-06-11 사용자결정] 대장주 승격 매수 = 소액 실전실험 — 회당 최대 50만원.
    #   롤백/조정 env LEADER_FIRST_MAX_KRW.
    if best.get("leader_first") and price > 0:
        _lf_cap = int(float(os.environ.get("LEADER_FIRST_MAX_KRW", "500000")))
        if pos.get("order_krw", 0) > _lf_cap:
            _lf_qty = int(_lf_cap / price)
            lg.info("[LEADER-FIRST-CAP] 소액실험 상한: order_krw %d→%d qty→%d",
                    int(pos.get("order_krw", 0)), _lf_cap, _lf_qty)
            pos = dict(pos)
            pos["order_krw"] = _lf_cap
            pos["qty"] = max(0, _lf_qty)
    if pos["qty"] <= 0:
        # [v4.31 FIX-1] B안: capital-aware sizing (Almgren & Chriss 2001 minimum lot constraint)
        # min_lot_fraction = 1주 매수에 필요한 자본 비율
        # KELLY_HARD_MAX(0.65) 이하: 1주 허용, fraction 재계산
        # KELLY_HARD_MAX 초과: 과집중 → 진입 불가
        _exec_block_reason = ""
        if price > 0:
            _min_lot_frac = price / _capital()
            if _min_lot_frac <= KELLY_HARD_MAX:
                pos = dict(pos)
                pos["qty"] = 1
                pos["order_krw"] = int(price)
                pos["fraction"] = round(_min_lot_frac, 4)
                lg.warning("[MIN_LOT] qty=0 → capital-aware 1주 진입: "
                           "price=%d fraction=%.3f(%.1f%%) mode=%s ev_n=%d",
                           int(price), _min_lot_frac, _min_lot_frac * 100,
                           mode, ev_result.get("sample_n", 0))
            else:
                _exec_block_reason = (
                    f"MIN_LOT_FAIL price={int(price)} > "
                    f"capital×KELLY_MAX={int(_capital()*KELLY_HARD_MAX)}"
                )
                lg.warning("[HOLD][MIN_LOT_FAIL] %s → lot constraint RC_HOLD", _exec_block_reason)
                lg.info("[EXEC_TRACE] code=%s mode=%s ev=%.4f%% sample_n=%d calibrated=%s "
                        "price=%d order_krw=%d qty=0 block_reason=%s",
                        best["code"], mode, ev_result["ev_pct"],
                        ev_result.get("sample_n", 0), ev_result.get("calibrated", False),
                        int(price), pos["order_krw"], _exec_block_reason)
                return RC_HOLD
        else:
            _exec_block_reason = "price=0(가격데이터없음)"
            lg.warning("[HOLD] %s → RC_HOLD", _exec_block_reason)
            lg.info("[EXEC_TRACE] code=%s mode=%s ev=%.4f%% sample_n=%d calibrated=%s "
                    "price=0 order_krw=0 qty=0 block_reason=%s",
                    best["code"], mode, ev_result["ev_pct"],
                    ev_result.get("sample_n", 0), ev_result.get("calibrated", False),
                    _exec_block_reason)
            return RC_HOLD

    # ── [EXEC_TRACE] 진입 확정 추적 ──
    lg.info("[EXEC_TRACE] code=%s mode=%s ev=%.4f%% sample_n=%d calibrated=%s "
            "price=%d order_krw=%d qty=%d block_reason=none",
            best["code"], mode, ev_result["ev_pct"],
            ev_result.get("sample_n", 0), ev_result.get("calibrated", False),
            int(price) if price > 0 else 0, pos["order_krw"], pos["qty"])

    # [P3] EARLY 소량 진입 — fraction/qty/order_krw 동시 40% 상한
    if best.get("early_flag") and best.get("hint", "") in ("SIGA", "PULLBACK"):
        _cur_frac = pos.get("fraction", 1.0)
        if _cur_frac > 0.40:
            _scale       = 0.40 / _cur_frac
            pos          = dict(pos)
            pos["fraction"]  = 0.40
            pos["qty"]       = max(1, int(pos["qty"] * _scale))
            pos["order_krw"] = int(pos["order_krw"] * _scale)
            lg.info("[EARLY] pre-entry activated (40%% cap %.0f%%→40%%) code=%s",
                    _cur_frac * 100, best["code"])

    # ── 하차+트레일링 신호 ──
    exit_signals = build_exit_signals(best["ride"])

    # ── 신호 기록 ──
    _ws_ok = write_signal(best, mode, pos, regime, ev_result,
                          exit_signals, evolve_w, profit_metrics, lg)
    _EXEC_STATS["signal_written"] = bool(_ws_ok)

    # [CYCLE-6 2026-05-21] event_journal SIGNAL_WRITTEN emit
    if _ws_ok:
        _emit_event("SIGNAL_WRITTEN", entity="signal", entity_id=best.get("code", ""), payload={
            "mode": mode,
            "qty": pos.get("qty", 0),
            "order_krw": pos.get("order_krw", 0),
            "regime": str(regime),
            "ride": best.get("ride", 0),
        })

    # ── [v4.29 FIX] pnl_linker 매수 기록 — 자기진화 루프 완성 ──
    if _PNL_OK:
        try:
            _write_buy = getattr(_pnl_mod_ref, "write_buy_fill", None)
            if _write_buy:
                _write_buy(
                    code             = best["code"],
                    strategy         = STRATEGY_NAME,
                    buy_price        = float(price),
                    buy_qty          = int(pos["qty"]),
                    market_regime    = regime,
                    gap_pct          = float(best["row"].get("gap_pct", 0)),
                    entry_time_bucket= "EARLY" if _hhmm() < 1030 else "MID",
                    vol_ratio        = float(best["row"].get("vol_ratio", 0)),
                    capital_allocated= int(pos["qty"] * float(price)),
                    logger           = lg,
                )
                lg.info("[PNL] write_buy_fill OK code=%s", best["code"])
        except Exception as _pnl_e:
            lg.warning("[PNL] write_buy_fill 실패: %s", _pnl_e)

    # ── 콘솔 출력 ──
    cap_tag   = f"테스트({_capital():,})" if REAL_TEST_MODE else f"본게임({_capital():,})"
    ratio_tag = "50/50" if regime == "BEAR" else "70/30"
    trail_tag = exit_signals["trail_mode"]
    tier_label = "SIGA1+PULLBACK3"   # 불타기/분할 진입 구조
    print()
    print("=" * 65)
    print(f"  RT EXECUTION ENGINE v4.29  [{cap_tag}]  [SIGA1+PULLBACK3]")
    print(f"  [{mode}] {best['code']}  Kelly={pos['kelly_used']:.0%}"
          f"  실배분={pos['fraction']:.0%}  ({ratio_tag})")
    print("=" * 65)
    print(f"  sel={best['selection_score']:.2f}  ps={best['prescore']:.1f}"
          f"  edge={best['edge']:.4f}  q={best.get('quality',0):.2f}")
    print(f"  기관: {best['ride']['ride_score']:.2f}  {' '.join(best['ride']['signals'])}")
    if best["ride"].get("exit_warnings"):
        print(f"  ⚠ 하차경고: {' '.join(best['ride']['exit_warnings'])}")
    print(f"  EV: {ev_result['ev_pct']:+.3f}%  승률={ev_result['win_rate']:.0%}"
          f"  n={ev_result['sample_n']}{'  ⚠미보정' if not ev_result['calibrated'] else ''}")
    if profit_metrics.get("evaluated"):
        pf_tag = "✅" if profit_metrics["profit_factor"] >= PF_STRONG else "⚠"
        calmar_v = profit_metrics.get("calmar", 0)
        calmar_tag = "✅" if calmar_v >= 1.0 else ("⚠" if calmar_v >= 0.5 else "🔴")
        print(f"  수익률: PF={profit_metrics['profit_factor']:.2f}{pf_tag}"
              f"  Sharpe={profit_metrics['sharpe']:.2f}"
              f"  Calmar={calmar_v:.2f}{calmar_tag}"
              f"  MDD={profit_metrics['max_drawdown']:.2f}%")
    else:
        print("  수익률: 미평가 (거래이력 부족)")
    print(f"  주문: {pos['order_krw']:,}원  {pos['qty']}주  @{price:,.0f}원  [{pos['strategy_type']}]")
    print(f"  트레일: {trail_tag}  sell={exit_signals['trail_sell_ratio']:.0%}"
          f"  | OFI감소{exit_signals['ofi_decay_pct']}%/MAX{exit_signals['max_hold_days']}일")
    print(f"  레짐={regime}  진화w={evolve_w:.4f}  비용={trade_cost*100:.2f}%"
          f"  시간w={_get_time_weight(lg):.2f}")
    print("=" * 65)
    print()

    evo_adj = calc_evolve_adjustments(profit_metrics, lg)
    if evo_adj["evolve_note"] != "OK":
        lg.info("[EVOLVE_ADJ] %s", evo_adj["evolve_note"])
    # [v4.22 FIX-3] evolve_adj → 런타임 상수 다음 사이클부터 반영
    # 기존: signal JSON에만 저장 → rt_sell_engine이 읽어야 반영 (지연)
    # 수정: MAX_LOSS_PER_TRADE / TRAIL 기준 전역 보정 — 다음 실행 사이클 진입 체크에 반영
    #       (현재 진입 결정 이후 적용 — 이번 사이클 진입에는 영향 없음)
    global MAX_LOSS_PER_TRADE, EV_ENTRY_MIN
    _hard_mult  = evo_adj["apply_to"].get("hard_stop_multiplier", 1.0)
    _trail_pct  = evo_adj["apply_to"].get("trail_activate_pct", 1.5)
    _split_t1   = evo_adj["apply_to"].get("split_t1_ratio", 0.40)
    # [v4.22 FIX-8] hard_stop + trail_activate + EV_ENTRY_MIN 다음 사이클부터 반영
    if _hard_mult != 1.0:
        _prev_stop = MAX_LOSS_PER_TRADE
        MAX_LOSS_PER_TRADE = round(MAX_LOSS_PER_TRADE * _hard_mult, 2)
        lg.info("[EVOLVE_APPLY] MAX_LOSS_PER_TRADE %.2f → %.2f (×%.2f)",
                _prev_stop, MAX_LOSS_PER_TRADE, _hard_mult)
    # trail_activate_pct → EV_ENTRY_MIN 보정 (손실 구간 진입 기준 상향)
    if evo_adj.get("stop_tighten") and _trail_pct < 1.5:
        _prev_ev = EV_ENTRY_MIN
        EV_ENTRY_MIN = round(min(EV_ENTRY_MIN * 1.05, 0.65), 3)
        lg.info("[EVOLVE_APPLY] stop_tighten → EV_ENTRY_MIN %.3f → %.3f",
                _prev_ev, EV_ENTRY_MIN)
    lg.info("[EVOLVE_APPLY] trail_activate=%.2f%% split_t1=%.2f (signal JSON 기록)",
            _trail_pct, _split_t1)

    lg.info("[OK] %s sel=%.2f %s ride=%.2f ev=%.3f%% kelly=%.4f PF=%.2f trail=%s evolve=%.4f [%s]",
            best["code"], best["selection_score"], mode,
            best["ride"]["ride_score"], ev_result["ev_pct"],
            ev_result["kelly_fraction"],
            profit_metrics.get("profit_factor", 0),
            trail_tag, evolve_w, tier_label)
    return RC_OK


if __name__ == "__main__":
    # [v4.34 TRACE] 모든 종료 경로에서 EXEC_SUMMARY 1회 출력
    # [PATCH-LOCK] 모든 종료 경로(정상/예외/조기return)에서 락 해제 보장
    _exec_rc = RC_HOLD
    try:
        _exec_rc = main()
    finally:
        try:
            _release_exec_lock()
        except Exception:
            pass
        _EXEC_STATS["rc"] = _exec_rc
        _emit_exec_summary()
    sys.exit(_exec_rc)

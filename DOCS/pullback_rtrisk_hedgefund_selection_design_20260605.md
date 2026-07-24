# PULLBACK 헤지펀드식 선별 설계 — rt_risk 단독 (다른 모듈 무수정)
작성: 2026-06-05 / 대상 파일: **RUN/rt_risk_engine_v6_6.py 한 곳만**
목적: rt_risk가 받는 165개를 "스코어보드급 정교함"으로 선별해 테마대장주 우선 Top1을 정예 출력.
제약: ★make_rt·수집기·스코어보드·rt_execution **일절 수정 금지.** rt_risk 내부에서만.

---

## 0. 왜 rt_risk 단독으로 가능한가 (확인됨)
- 흐름: `make_rt(165) → rt_intraday.csv → rt_risk[선별→rt_risk_candidates.csv] → rt_execution[risk_codes 안에서만 집행]`
- rt_execution L2280-2282: `rows = [r for r in rows if code in risk_codes]` → **rt_execution은 rt_risk 출력 안에서만 집행.**
- ∴ rt_risk가 정예 Top1을 출력하면 그게 집행됨. **rt_risk = PULLBACK의 스코어보드 역할 자리.**

## 1. 현황 (거친 선별)
- rt_risk: rt_intraday(165) 읽음 → 하드게이트 → `score_col`(prescore_weighted/score_final) **단일 점수 정렬** → Top1 → ~5개 출력.
- 정규화·다팩터 합성 없음(raw). 테마는 약한 보너스(+가점 티어 신규). → 165→1이 거침(사용자 지적).
- EOD 스코어보드는 165→80→25→8 정교 / PULLBACK은 1단 = 비대칭.

## 2. 헤지펀드 방법론 (조사 요약)
멀티팩터 합성(mega-alpha): 약한 알파들을 **횡단면 z-score 정규화 + winsorize + 가중 합성** / 다단계 퍼널 / 리스크조정(IR·Kelly·CVaR) / 레짐 조건부 가중. (AQR·WorldQuant 계열)
출처: arXiv 1708.02984(Quant Alphas), ExtractAlpha, Aurum quant primer, GS AM.

## 3. 설계 — rt_risk 내부 다단계 composite 퍼널
```
[rt_risk 내부, 전부 한 파일]
Stage 0  입력 165 (rt_intraday.csv)  [기존 로드]
Stage 1  하드게이트(품질): 눌림(pullback)·ride≥min·EV>0·gap<7%·spread/vol·과열X·stale X  [기존 df_filtered]
Stage 2  ★멀티팩터 합성 z-score (신규 핵심) — 횡단면(오늘 유효후보 내) winsorize ±3σ + z:
           F1 눌림품질  : close_position 낮을수록↑(싸게), vwap_dev, body_strength
           F2 추세강도  : adx_14, trend_slope, vwap_rising
           F3 수급흐름  : ofi, inst_ride_score, value_accel
           F4 ★테마리더십: best_strength(다기간 20-14-5-3-1) + is_leader(rank≤20)
           F5 엣지/엔트리: expected_edge, prescore_weighted
         composite = Σ wᵢ·z(Fᵢ)   (레짐별 wᵢ, 기본은 단순·강건 가중)
Stage 3  ★테마대장 우선 티어(게이트 통과 테마대장주 있으면 #1) + 리스크조정(Kelly/CVaR/DD)  [티어 신규적용됨]
Stage 4  정예 Top1(+소수 백업) → rt_risk_candidates.csv 출력 → rt_execution 집행
```

## 4. 팩터 정의·사용 컬럼 (rt_intraday에서 rt_risk가 읽음)
⚠구현 시 rt_intraday.csv 헤더로 최종 확인. 예상 가용:
- F1: `close_position`(낮음=눌림=가점), `vwap_dev`, `body_strength_3m`
- F2: `adx_14`, `trend_slope_mag`, `vwap_rising`
- F3: `ofi`(또는 ofi_roll3), `inst_ride_score`, `value_accel`
- F4: `_load_theme_strength_pb()` → best_strength·rank·is_leader (이미 rt_risk에 있음)
- F5: `expected_edge`, `prescore_weighted`
정규화: 각 팩터 오늘 유효후보 횡단면 winsorize(±3σ)→z-score. 결측=0(중립). 부호 일관(높을수록 좋음, close_position은 반전).

## 5. 구현 위치 (전부 rt_risk_engine_v6_6.py)
- Stage2 composite: Top-1 정렬부(현 `_sort_col` 계산 직전, L~1730) 앞에 `_compute_composite(df_filtered)` 추가 → `_composite` 컬럼 → `_sort_col = "_composite"`.
- winsorize/z: pandas로 df_filtered 내 계산(횡단면). 외부 의존 없음.
- 레짐 가중: 기존 `_detect_regime` 결과로 wᵢ 딕셔너리 선택.
- Stage3 테마티어: 이미 추가됨(THEME-LEADER-PRIORITY). composite 위에서 동작.
- 출력: 기존 rt_risk_candidates 작성부 그대로(정렬키만 composite).

## 6. env 토글 + 병행 로그(SHADOW) + 검증
- `RTRISK_COMPOSITE_ENABLE`(기본 NO=SHADOW 먼저): NO면 composite 계산·로그만, 정렬은 기존 score_col(행동 무변경). YES면 composite로 정렬.
- 로그: 후보별 `[COMPOSITE] code z_pullback/z_trend/z_flow/z_theme/z_edge → composite` + `기존1등 vs composite1등 비교`.
- 검증: SHADOW 며칠 → composite 1등이 기존보다 익일/장중 나은지(theme_flow·실체결) → YES 전환.
- 가중치: 처음엔 **단순(동일가중 or F4 테마 약간↑)**, 과적합 금지. 튜닝은 전향 데이터 후.

## 7. 캐비엇 (정직)
- 알파는 약함 — 30일로 가중 과적합 위험 → 단순·강건 가중부터.
- 장중 테마 edge 표본부족(n=3~4) 미확정 → composite는 테마를 "한 축"으로 녹이되 과대가중 금지.
- 횡단면 z는 후보수 적으면(<5) 불안정 → 후보 적을 땐 기존 score_col 폴백.
- SHADOW 선검증 필수(행동 무변경으로 시작).

## 8. 단계적 적용
1. Stage2 `_compute_composite` + SHADOW 로그(RTRISK_COMPOSITE_ENABLE=NO). 행동 무변경, 비교 누적.
2. 며칠 검증(composite vs 기존 1등, 익일/장중 수익) → 유의하면 ENABLE=YES.
3. 레짐별 가중·팩터 정제는 전향 데이터 후.
각 단계 py_compile(32/64)·백업·회귀(기존 Top1 변화 0 확인 from SHADOW).

## 9. 제약 재확인
- ✅ rt_risk_engine_v6_6.py **단독 수정**.
- ❌ make_rt·수집기·스코어보드·rt_execution·buy_sender 무수정.
- 입력(rt_intraday.csv)·출력(rt_risk_candidates.csv) 인터페이스 불변 — 다른 모듈 영향 0.
- env 되돌림(RTRISK_COMPOSITE_ENABLE=NO).

## 10. 관련
- 테마: [[stockbot-20260605-theme-leader-pool-entry-bottleneck]] (make_rt 주입·rt_risk 티어 적용됨)
- EOD 대칭: 스코어보드 THEME-RESCUE + signal_v2 tilt/cp (DOCS/... close_position)
- 근본 SoT: DOCS/execution_truth_reconcile_design_20260605.md

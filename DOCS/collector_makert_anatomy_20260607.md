# 수집기 + make_rt 완전 해부서 (2026-06-07, 코드 정독·추정 없음)

대상: `RUN/collect_prices_1m_kiwoom_opt10080_v4_16.py` (3951줄) · `RUN/make_rt_intraday_from_prices_1m_v7_23.py` (2357줄)

---

## A. 수집기 (collect_prices_1m) — "선별기"가 아니라 "데이터 적재기"

### A-1. 실행 골격
- `main()`(L3931) → `KiwoomCollector.run_forever()`(L3704)
- 진입 1회: write_heartbeat → ensure_login → _init_pb_bridge → **load_all_codes()** → load_last_ts_map → verify_csv → _pre_load_hot_candidates
- `while True` 루프(L3743) 매 사이클:
  1. write_heartbeat (워치독용)
  2. Q4-DPRESET: 5분마다 timeout격리(dead_pool) 25% 해제 (L3759)
  3. 장개장 체크(08:50~15:35, 휴일제외) (L3781)
  4. 09:05 이전 1회 종목리스트 갱신 load_all_codes (L3792)
  5. 08:50~09:05 장전 기관순매수 1회 (L3801)
  6. **TR 게이트: 09:03~15:28만 수집** (>15:28 break, <09:03 대기) (L3805)
  7. HOT 감지 → enqueue_requests → **process_queue(실제 TR)** → _fetch_kospi_index → **save_csv** → PB tick (L3825~3840)

### A-2. 종목 풀(universe) = `_load_all_market_codes()` (L1430)
- `GetCodeListByMarket(MARKET_CODES)` 시도 → **5/24~ 빈값** → **CODELIST-FALLBACK**(L1459):
  - 소스 = `eod_daily_bars.csv` 최신일
  - 조건 = `market==KOSDAQ` **AND** SKIP_KW(스팩/ETF/ETN/리츠/우선주) 제외 **AND** 거래대금(value) **nlargest(600)** (L1469)
- 결과 `self.all_codes` = **KOSDAQ 거래대금 상위 600** (KOSPI/ETF 자동 제외)
- ※ SKIP_STATE(거래정지/관리/투자경고)는 OCX 경로일 때만(폴백엔 컬럼없어 미적용, 다운스트림 blocklist가 차단)

### A-3. 버킷 구성 = `load_all_codes()` (L1535~1635)
매일 09:05 전 1회. all_codes(600)를 3버킷으로:
- **bucket_a (코어, 매사이클 신선수집)**:
  - 소스 = `hot_valid(거래량HOT) ∪ (기관순매수>0 ∩ KOSDAQ) ∪ 거래대금top50` (L1536)
  - `bucket_a = bucket_a[:18]` (L1552, CORE-SLIM: 40→18, 사이클타임 보호)
  - FALLBACK-A: 부족 시 거래대금순으로 18까지 보충 (L1551)
  - **THEME-LEADER-BUCKET**(L1565): 강테마 KOSDAQ 대장주(code_theme_strength is_leader & rank≤20)를 A에 보장편입, **cap=12** (6/7 6→12), all_codes 교집합 필요
- **bucket_b**: 전일 상위(top_set) 중 A 제외 `[:6]` (L1580)
- **bucket_c**: 잔여 전부, **거래대금 내림차순 정렬** (L1596~1606). C가 universe 600 회전 담당
- `code_list = bucket_a + bucket_b` (L1628, active = 매사이클)

### A-4. 매 사이클 수집 대상 = `enqueue_requests()` (L3078) ★핵심
**장중(08:50~15:20)** 큐 구성:
- A: `bucket_a[:40]` cycle_count 회전 + timeout격리 제외 (실제 ~18~30) (L3097)
- B: `bucket_b[:15]` (실제 ~6) (L3112)
- **C: `_c_per_cycle = 2`** (평소). 단 **A+B<30이면 C를 min(35, 30−AB)로 확대** (L3125~3128). C는 `bucket_c[:600]`을 cycle_count×2 슬라이딩 순환 (L3130~3133)
- gap_retry_pool: appendleft 우선처리 (L3174)
- **큐 cap = 90** (L3221)
- **장후(15:20~)**: C버킷 12분할 백필 (L3199)

→ **결론: 매 사이클 ~30~38종목 신선수집(A+B 전부 + C 2개) + 600풀은 C 2개/사이클로 세션 내내 순환.** 수집기는 600→N 선별을 하지 않는다. 데이터를 모은다.

### A-5. 출력 = `save_csv()` (L3422)
- batch_rows(이번 사이클 신규봉) → 기존 prices_1m append → **당일ts 필터** → **(code,ts) dedup keep=last** → code별 **최근 390봉**(MAX_CSV_ROWS) 유지 → `DATA/prices_1m.csv` atomic write
- 누적이므로 **prices_1m엔 세션 동안 수집된 모든 종목(최대 ~600)** 데이터가 쌓임 → make_rt 입력

---

## B. make_rt (make_rt_intraday) — 진짜 "선별기" (600→300→160)

### B-1. 셋업 = `_main()` (L1204)
- **params_reader 동적로드**(L1230~): TOP_N·W_*·HEAT·OFI·SECTOR_LEADER 등 27+ 파라미터를 매 실행 evolution 반영 + 상한 클램프
- prices_1m freshness: mtime 당일(L1363) + ts latest_day 필터(L1378) + 당일 ≥100행(L1383), 아니면 RC_HOLD

### B-2. 입력 적재 (L1387~1418)
- investor_daily → investor_net / inst_consec / inst_accel / inst_tier (`_load_investor_all`)
- eod_daily_bars → vol_5d / prev_close / daily_value_5d
- prices_1m 1패스 집계(L1437~): `all_bars_map`(code별 봉), day_high/low, pv_sum, vol_sum, 시간창 거래대금(val_prev/last_window), prev10_val 등

### B-3. 후보 점수화 (per-code 2패스 루프) ★선별조건의 실체
각 종목마다:
- **attack_score / stable_score** (공격·안정 다지표 합성)
- **prescore**(L1938) = attack×atk_w + stable×stb_w − soft_risk − soft_vol + entry_gate_bonus + rvol_score
  - **+ SECTOR_LEADER 보너스**(L1946~1954): 강테마 대장주(is_leader & rank≤20) → `+12 × (1−(rank−1)/20)` (rank1=+12, rank20≈+0.6)
- **edge**(L1995): close_position×0.25 + high_break×0.40 + volume_accel×0.20 + ofi×0.15
- **risk_adj**(L2016): floor(기관동행 inst_consec≥3 → 0.80, 아니면 0.70) − ATR/18 − 과열×0.02
- **expected_edge = (edge×0.6 + prescore_norm×0.4) × risk_adj** (L260 문서 / 루프 뒤 정규화 후 계산)

### B-4. 선별 컷 (600→300→160) (L2219~2278) ★
1. edge_floor 컷 **비활성**(v7_23, 전종목 통과) (L2219)
2. **KOSDAQ-FILTER**: KOSPI/ETF 제외 (L2230)
3. **정렬: `(expected_edge, prescore)` 내림차순** (L2245). `_pre_cut`=정렬된 전체 보관
4. **2단 압축**:
   - 1단 `TOP_N_1ST=300` → 상위 300 (L2248~2253)
   - 2단 `TOP_N_2ND=160` → 상위 160 (L2254~2256)
5. **THEME-INJECT**(L2258): 컷에서 밀린 강테마 대장주를 `_pre_cut`에서 풀에 force 복원, **cap=12**(6/7 10→12). out_rows에 추가만(displace 없음)
   - 결과 rt_intraday ≈ **160 + inject(~5) = 165종목**

### B-5. 출력 = `_atomic_write_csv(RT_OUT_PATH...)` (L2307)
- 내부필드(_prescore/_expected_edge/_edge/_risk_adj) 제거 후 `DATA/rt_intraday.csv` 작성
- 무결성 3중검증(0바이트·1등코드형식) + **통과율 가드**(<0.5%면 RC_HOLD) (L2326)
- 컬럼: code, prescore_weighted, expected_edge, attack/stable_score, strategy_hint, confidence_margin 등

→ **rt_intraday = 165종목** → 다운스트림 2곳 공유: ① rt_execution(PULLBACK) ② kjs_scoreboard(EOD, valid_codes로 50지표 재점수)

---

## C. 전체 흐름 한눈에 (실측·추정없음)

```
키움 opt10080(분봉)
  │  수집기: universe=KOSDAQ거래대금top600(SKIP제외)
  │         매사이클 A(~18,HOT/기관/거래대금top50)+테마대장주(cap12)+B(~6)+C(2,600풀순환)
  │         → prices_1m.csv 누적(세션내 최대~600종목, code별 390봉)
  ▼
make_rt: prices_1m 전종목 점수화(prescore+SECTOR_LEADER+12 / edge / expected_edge)
  │      KOSDAQ필터 → (expected_edge,prescore) 정렬
  │      2단압축 300(1단)→160(2단) + THEME-INJECT(cap12)
  ▼  rt_intraday.csv ≈ 165종목
  ├─▶ rt_execution (PULLBACK 추세눌림)
  └─▶ kjs_scoreboard (EOD: 50지표 재점수 → score_eod top8 → 종가매수)
```

### 핵심 사실 (사용자 오해 정정)
- **"600→400→300"의 400은 코드에 없음** = CORE-SLIM(6/1) 이전 옛 active~400 주석 잔재. 현재 active~30.
- **"100 사라짐" 없음**: 600은 수집 풀, make_rt가 300→160 단계 압축. 수집기↔make_rt 간 별도 400→300 핸드오프 없음.
- **선별조건은 make_rt에 다축으로 실재**: 거래대금·가격위치·고점돌파·거래량가속·주문흐름(ofi)·공격/안정·테마대장주·위험조정. (inst_consec만 약함=universe-writer 회복중)
- **2단(300→160)은 같은 expected_edge 재정렬(압축)**. 다축 "재경쟁"(새 조건)은 그 다음 — scoreboard 50지표 + rt_risk + signal compete.
- 테마대장주 보호 cap 전 체인 12로 정렬: 수집기 버킷12 → make_rt INJECT12 → scoreboard POOL-B/RESCUE12.

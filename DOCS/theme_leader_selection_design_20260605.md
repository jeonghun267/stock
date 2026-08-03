# 테마 대장주 선별력 개선 설계 (1·2·3순위)
작성: 2026-06-05 / 상태: **설계 완료, 적용은 백테스트·승인 후** / read-only 진단 기반

---

## 0. 배경 / 문제 정의
- 사용자 전략: 강한 테마의 **대장주(leader)** 우선 매수 (기관 등타기 시너지).
- 학술 근거(메모리): Moskowitz&Grinblatt(1999) 섹터 모멘텀이 개별주 모멘텀 60~73% 설명. 단 장기(6~12M)≠한국단타, 꼭지/과적합 경계.
- **핵심 진단(6/5 read-only)**: 테마 메커니즘은 구축됐으나(네이버 265테마, theme_strength_v2 다기간, KOSDAQ leader, make_rt SECTOR_LEADER 보너스 + EOD_PICK 주입) **선별력이 약함**. 근본 원인 2가지:
  1. **후보풀 진입 실패** — 강테마 대장주 대부분이 PULLBACK 후보풀(rt_intraday)에 못 들어옴.
  2. **후발주 vs 대장주** — 풀에 들어와도 시스템이 대장주가 아닌 후발주를 선택.

---

## 1. 측정 결과 (read-only, 백테스트①·②)

### ① 풀 진입율 퍼널 (universe → prices_1m → rt_intraday 160)
| 강도 | universe | 수집 | 풀(rt) | 갭: universe밖(2순위)/수집후컷(1순위) |
|---|---|---|---|---|
| rank≤10 (최강 8) | 1/8(12%) | 1/8(12%) | **0/8(0%)** | universe밖 7 / 컷 1 |
| rank≤20 (18) | 8/18(44%) | 9/18(50%) | 4/18(22%) | universe밖 10 / 컷 5 |
| rank≤30 (24) | 12/24 | 13/24 | 5/24(20%) | universe밖 12 / 컷 8 |

- 🔴 **rank≤10 최강 대장주 8개 풀 진입 0%** = 시스템이 최강 테마 대장주를 하나도 못 올림.
- ★ **"universe 있는데 미수집=0"(전구간)** → universe 넣으면 100% 수집(버킷캡 무손실). **2순위는 universe_codes.txt union만으로 충분**(전용버킷 불필요).
- 적용 시 예상: rank≤10 0→~100%, rank≤20 22→~100%.

### ② changed 시뮬 (Top1 선정에 테마 반영되나)
- 오늘 rt_risk Top1 81회 중 **테마 대장주 15회(18.5%)**(078600·080220) = make_rt SECTOR_LEADER **이미 작동**(메모리 "changed=0"은 옛 EOD_PICK 기준).
- ⭐ **지배적 1등 403870(49%)은 온디바이스AI(rank12) 강테마지만 is_leader=0 후발주.** 그 테마 대장주 080220(ret_20d+89%)은 4회뿐. → **후발주 vs 대장주 문제(3순위) 데이터 입증.**
- 보너스(~+5)는 Top1과 5점내 근접 후보만 뒤집음(A방식 안전 = 약한 대장주 강제매수X).
- 한계: 미수집 대장주 changed는 base prescore 미상 → read-only 산출 불가(전향 필요).

---

## 2. 설계

### 데이터 흐름 / 순서
```
[2순위] universe_codes.txt에 테마대장주 추가
  → 수집기 prices_1m 수집(real-time 확보)
    → [1순위] make_rt가 160 컷에서 수집된 신선 대장주 force-include
      → rt_intraday 진입 → SECTOR_LEADER 보너스(is_leader)
        → [3순위] rt_risk Top1에서 후발주 대신 대장주 선호(SHADOW 검증 후)
```
※ 2순위가 전제(데이터 없으면 make_rt 주입해도 stale 필터가 거름).

### 2순위 — universe-writer에 테마 대장주 포함
- 파일: `CORE/COLLECT/update_universe_codes_v1.py` `_load_kosdaq_top()`
- 현재: `df.nlargest(top_n,"value")` (KOSDAQ 거래대금 top300)
- 설계: `universe = top300 ∪ {code_theme_strength의 is_leader=1 & best_theme_rank≤MAX & KOSDAQ}`
- 안전장치: `UNIVERSE_THEME_LEADER_MAX`(예30) 상한 / 테마 stale·없음→top300만(fail-safe) / dedup·KOSDAQ·SKIP_KW
- 검증: "universe→수집 100%" 확인됨 → union만으로 충분(전용버킷 b안 불필요)

### 1순위 — make_rt가 수집된 대장주를 160 컷에서 보호
- 파일: `make_rt_intraday_from_prices_1m_v7_23.py` (KOSDAQ 필터/최종 코드셋 산출부)
- 설계(EOD_PICK `_inject_theme_leaders` 미러링): 160 컷 후, **prices_1m에 있고 ts 신선하며 160 밖**인 강테마 대장주를 force-include
- 안전장치: `MAKE_RT_THEME_INJECT_MAX`(예10) / env `MAKE_RT_THEME_INJECT_ENABLE` / **신선 ts만 주입(stale 필터 일관, 007390류 재발 방지)** / sentinel 금지(정상 feature 계산분만)
- 효과: 수집 대장주가 거래대금 컷에 안 밀리고 풀 진입 → 보너스 유효

### 3순위 — 강테마 내 대장주 우선 (follower→leader)
- 문제: 403870(후발주) 49% 지배, 대장주 080220은 4회. make_rt 보너스는 이미 is_leader=1에만 → 후발주는 보너스0인데 base 모멘텀으로 이김 = **선택 문제**(보너스 추가 문제 아님).
- 데이터: `theme_strength.csv`에 `leader_code` 매핑 존재.
- 옵션: **A 대장주 치환**(rt_risk Top1이 강테마 후발주면 그 테마 leader가 풀에 있고 밴드내면 치환, TIE-BAND 패턴) / B 차등가점 / C 보너스강화(=4순위)
- ★권장 **SHADOW-first → A**: Phase1 `follower-Top1 vs leader-대안` compare 기록(무변경)→며칠 누적→대장주 익일/장중 수익이 후발주보다 나은가 검증→Phase2 치환.
- 위치: `rt_risk_engine_v6_6.py` Top1 정렬부(TIE-BAND 옆), env 토글 + compare 파일
- ⚠ **결정적 caveat**: 대장주 080220 ret_20d+89%(꼭지위험) vs 후발주 fresh일수도 = "대장주 꼭지 vs 후발주 눌림싸게" 논쟁. **대장주 항상우위 보장 X** → SHADOW 검증이 1·2순위보다 더 중요. `pullback_flag`(대장주 눌림 상태) 결합 시 "강테마+대장주+눌림"만 선호 가능.

---

## 3. 안전장치 요약
| 항목 | 장치 |
|---|---|
| 데이터 없음/stale | fail-safe (현행 유지 / 주입 skip) |
| 폭주 방지 | 상한(universe +30, make_rt +10) |
| sentinel/stale 매수 | 신선 ts만 주입(stale 필터 일관) |
| 롤백 | env 토글(2순위/1순위/3순위 각각) |
| 시장 | KOSDAQ 한정 |
| 회귀 | 주입=ADD(기존 컷 유지, 대체 아님) / 3순위=SHADOW 우선 |

## 4. 백테스트 계획 (적용 전 필수)
1. ✅ 풀 진입율 측정(완료): 22%→~100% 예상
2. ✅ changed 시뮬(완료): 현재 18.5%, 후발주 지배 발견
3. **수익 기여(전향 ~6/20+)**: 테마 대장주 진입 vs 기존 선별 익일/장중 수익. pullback_flag별 분리.
4. **leader vs follower 전향 수익**(3순위 검증): 강테마 대장주 vs 후발주 진입 수익. 꼭지(고 ret_20d)면 follower 승 가설 검증.
5. 회귀: 기존 거래대금 대장주가 밀려나지 않는지.

## 5. 리스크
- 풀 확대 → 경쟁 종목↑ → 1등 변동성↑(의도된 효과, 검증 필요)
- 수집 부하: universe +30 → 사이클 시간↑(CORE-SLIM 86~90s 여유 확인)
- 테마 대장주 ≠ 항상 좋음(M&G 장기≠단타, 꼭지). 특히 3순위.
- 실행 병목 별개: 선택돼도 limbo/conv로 0 fills(2026-06-05 현재) → 선별 개선과 별도로 실행 경로(limbo=내일 발효, conv=ride-floor-relax) 정상화 필요.

## 6. 관련
- 메모리: stockbot-20260605-theme-leader-pool-entry-bottleneck / -pullback-theme-leader-makert(6/4) / -theme-leader-eodpick-link(6/4) / -theme-collector-prototype(6/2)
- EOD_PICK은 `_inject_theme_leaders`(6/4)로 1순위 풀 주입 이미 적용(6/5 15:22 첫 라이브 검증) — PULLBACK에 동일 패턴 이식이 1순위.

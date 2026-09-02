# 지시서 — S01 v3 실전 연결 (조건부 사전승인 집행)

작성 2026-08-27 저녁 · 승인자 친구님 · 작성자 Claude
집행 시점: **2026-08-28 09:20 이후** (캡처 완료 후, 장중 편집 금지와 무관한 검증→마감 후 편집 권장)

## 0. 승인 근거 (8/27 저녁 대화, 8/13 선례)

> 친구님: "8/13 선례처럼 '재생 PASS하면 바로 연결해'"

- 조건: 8/28 재생 PASS일 때만. FAIL/BLOCKED이면 **연결 금지, 사유 보고만.**
- 내용(상시·만료 없음): ROCKET 3슬롯 · PULLBACK 3슬롯 · 총 6슬롯 · 종목당 1주(공용 SSOT).
- 고지·승인됨: v3 LIVE 전환 시 **레거시 STRONG_FLOW 레인 정지**(신호 소스 교체).
- 하드스톱·강제청산·그림자 비교·감사 기록은 전부 유지(TEST_TRUTH #5).

## 1. 절차 (순서 고정)

1. **재생** (09:20 이후 아무 때나):
   ```
   C:\python310\python.exe C:\stock_bot\RUN\s01_entry_v3_prod_replay_v1.py --date 20260828 --out C:\stock_bot\reports\verified_replay\20260828\s01_entry_v3.json
   ```
   판정: 출력 JSON `status=PASS` + `provenance=[PROD_REPLAY]` + violations 빈 배열.
   BLOCKED/violations 있으면 **여기서 중단·보고**. (주의: ready_cases=0이면
   NO_V3_READY_CASE_OBSERVED로 막힘 — 그날 READY 케이스가 없었다는 뜻이니 다음 거래일 재시도)
2. **런처 편집 2개** (마감 후 권장, .cmd = CRLF·ASCII, 바이너리 편집):
   - `RUN\hidden\SAFEPLUS_STRATEGY01_LIVE.cmd` · `RUN\hidden\SAFEPLUS_STRATEGY01_SIGNAL.cmd`
   - 각각 `set S01_ROCKET_LIVE=YES` 줄 다음에 추가:
     ```
     REM Owner 2026-08-27 conditional pre-approval, executed after 20260828 replay PASS.
     set S01_ENTRY_V3_MODE=LIVE
     ```
   - 백업 먼저: `RUN\backup\*_20260828_before_v3_live.cmd`
3. **재봉인**: `C:\python310\python.exe C:\stock_bot\RUN\update_s01_v3_live_manifest_20260828.py`
   (전제 자가검사 내장: LIVE 줄 존재·CRLF·ASCII 확인 후 CAS 봉인)
   이어서 관리자 기준표: `C:\python310\python.exe C:\stock_bot\RUN\morning_preflight_rehearsal_v1.py --rebaseline-elevated`
4. **검증**: 관문 4종 PASS(`live_owner_approval_guard_v1 --strategy S01/S02/S03/S06`) +
   elevated 대조 이상 0 + 집중 테스트 `-k "strategy_01 or entry_policy"`.
5. 재시작 불필요 — 다음 거래일(8/29) 08:55/08:59 자동 기동이 새 env 로드. **첫 실주문 8/29 09:00.**
6. 완료 보고: 재생 JSON 경로·해시, diff, 관문 결과. memory.md 갱신.

## 2. 금지

- 재생 PASS 전 어떤 활성화도 금지. 다른 전략 칸·매도 규칙·수량 변경 금지.
- 재생 결과가 상충하면 [UNVERIFIED]로 중단(TEST_TRUTH #4).

## 3. 현재 상태 (8/27 저녁 실측)

- 배선 완료: 엔진 총6·R3·P3(기동검증 포함) · 라우터 배치상한 R3/P3(8/27 수리) · 수량 1주 · 상시.
- `S01_ENTRY_V3_MODE` 미설정=SHADOW. 오늘 캡처는 옛 해시라 재생 불가(실측 `59874fa3≠af7ce60c`).
- 집중 테스트 116 passed / 1 failed(기존 — 공용 매도엔진 hard_stop 사유 라벨 건, 별건 안건).

# 레짐 반등 예외 작업 인계 — 2026-08-21

## 목표

코스닥이 -3% 이하인 동안 정상 매수는 막되, 시장 전체가 실제로 회복하고
S01/S02/S03 종목 신호가 살아 있을 때만 빠른 반등 후보를 놓치지 않도록 한다.

## 현재 완료 상태

- 실전 게이트는 변경하지 않았다. `broker_client.py`의 -3% 매수 차단은 그대로다.
- 별도 주문 0 태스크 `SAFEPLUS_REGIME_EXCEPTION_SHADOW`를 평일 08:59 실행으로 설치했다.
- `regime_recovery_gate_shadow_v1.py`가 다음 상태를 기록한다.
  - RED: 공식 코스닥 -3% 이하, 빠른 회복 미확인
  - FAST_AMBER: 전략 감시종목 실시간 대용지수로 빠른 회복 확인
  - AMBER: 이후 5분 주기 공식 코스닥 지수도 저점 회복을 확인
  - YELLOW: 코스닥 -3% 초과~-2% 이하
  - GREEN: 코스닥 -2% 초과
- 공식 코스닥 파일은 5분 주기라 RED 판정과 사후 확인에만 쓴다(허용 나이 360초).
- 빠른 판정은 `micro_watch_strategy_shared.json`의 전일종가와
  `live_micro_snapshot.json`의 1초 시세를 결합한 전략 감시종목 대용지수를 쓴다.
- FAST_AMBER 현재 그림자 문턱값(`[HYPOTHETICAL]`):
  - 중앙수익률 저점 대비 +0.40%p 이상 회복
  - 대용지수 저점 30초 미갱신
  - 회복 조건 15초 연속 유지(가장 빠른 전환 약 45초)
  - 상승종목 비율이 대용지수 저점 당시보다 +10%p 이상
  - 당일 신저가 부근 종목 비율이 5%p 이상 감소
- RED에서 발생한 S02/S03 역할 신호는 300초간 주문 없이 래치한다.
  FAST_AMBER/AMBER 때 저점 미갱신·현재 수급·체결강도·호가를 다시 통과해야 후보가 된다.
- S01 > S03 > S02 우선순위, 하루 한 종목, 재진입 차단을 유지한다.
- 모든 산출물은 `SHADOW_ORDER_ZERO`, `live_eligible=false`, `order_qty=0`이다.
- 집중 검증: 아래 명령으로 9건 통과.
  `C:\python310\python.exe -B -m unittest discover -s RUN -p "test_regime_*shadow*_v1.py"`

## 산출물

- 코드: `RUN\regime_recovery_gate_shadow_v1.py`
- 역할 분류: `RUN\regime_exception_role_shadow_v1.py`
- 자동 기록: `RUN\regime_exception_shadow_recorder_v1.py`
- 태스크 설치: `RUN\install_regime_exception_shadow_task_v1.ps1`
- 상태: `data\shadow\regime_recovery_gate_state_YYYYMMDD.json`
- 관측: `data\shadow\regime_exception_observations_YYYYMMDD.jsonl`
- 이벤트/래치: `data\shadow\regime_exception_events_YYYYMMDD.jsonl`

## 남은 일 — 순서 고정

1. 다음 장 시작 전 관리자 터미널에서 태스크 Enabled/Ready, 08:59 트리거와 실행 명령을 재확인한다.
   현재 세션에서는 태스크 재조회 권한이 거부됐으므로 설치 당시 확인값 이후 상태는 미확인이다.
2. 다음 실행 후 상태 파일이 갱신되고, `breadth_universe >= 30`인지 확인한다.
   레짐이 없는 날 WAIT/YELLOW/GREEN만 기록되는 것은 정상이다.
3. 실제 레짐일에 `CANDIDATE_LATCH_ARMED → FAST_AMBER → VIRTUAL_ENTRY_SELECTED`
   순서와 신저점 발생 시 래치 폐기를 실측 확인한다.
4. 오늘 코드는 장중 여러 번 바뀌었으므로 2026-08-21 부분 기록은 최종 성과 근거로 쓰지 않는다.
   다음 온전한 거래일의 시작부터 끝까지 보존된 입력을 첫 검증 표본으로 삼는다.
5. 보존 입력으로 현재 생산 진입·공통 청산 경로의 완전한 `[PROD_REPLAY]` 도구를 만든다.
   `performance_scope=FULL_ENTRY_EXIT`과 `RUN\trading_report_truth_gate_v1.py` 통과 전에는
   수익률·승률을 말하거나 실전에 연결하지 않는다.
6. 재생 통과 후에만 사용자에게 S01/S02/S03 대상, 정확한 조건, 수량, 슬롯,
   상시/기간, 프로세스 재시작 여부를 한 번에 제시하고 실전 승인을 받는다.

## 아직 하지 않은 것

- `broker_client.py` 면제 또는 실전 주문 배선
- FAST_AMBER/래치의 실제 수익 효과 검증
- 새 후보의 생산 공통 청산판정 연결
- 기존 8/18 자료를 이용한 완전 생산 진입-청산 재생(필수 입력 부족)

이 문서를 다음 작업의 기준으로 사용하고, 새 근거가 생기기 전에는 문턱값을 추가 조정하지 않는다.

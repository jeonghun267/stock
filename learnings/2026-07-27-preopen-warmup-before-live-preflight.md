# 2026-07-27 예약 작업이 Enabled여도 60초 워밍업이 사전점검 마감 뒤 끝나 실전이 시작되지 않는 문제

## 접근법
1. 필수 예약 작업의 Enabled, State, StartBoundary, NextRunTime, Action을 함께 조회한다.
2. 공통 사전점검의 입력 파일과 각 생성기의 시작 시각·워밍업·마감 시각을 역추적한다.
3. `micro_rank_engine_v1.py`의 `WARMUP_SEC=60`과 실제 작업 시작 08:59:59, 사전점검 마감 09:00:15를 비교한다.
4. 주문·매수·매도 조건은 유지하고 읽기 전용 `SAFEPLUS_MICRO_RANK_SHADOW`만 08:57로 앞당긴다.
5. 작업의 StartBoundary/NextRunTime/Running 상태, 오늘자 감시목록, 브로커 SetRealReg 200종목, 전략 회귀검사 108개와 슬롯 동시성 검사를 확인한다.

## 하지 않은 것 + 이유
- 사전점검의 승인/OFF 게이트는 제거하지 않음. 이유: 데이터 준비 지연을 승인 우회로 숨기면 신선하지 않은 호가로 실전 엔진이 열릴 수 있다.
- 전략 1~4의 매수·매도 조건은 수정하지 않음. 이유: 결함은 신호식이 아니라 읽기 전용 선행 작업의 시작 순서였다.
- 전략 3의 종목당 1회 제한은 6회로 늘리지 않음. 이유: 관련 테스트가 2차 진입 금지를 전략 고유 조건으로 명시한다.

## 재사용 규칙
실전 예약 작업을 점검할 때는 Enabled 여부만 보지 말고 선행 생성기의 워밍업 종료시각이 소비자 마감시각보다 충분히 이른지 계산하라.

## 관련 파일/커밋
- `RUN/hidden/SAFEPLUS_MICRO_RANK_SHADOW.cmd`
- `RUN/micro_rank_engine_v1.py`
- `RUN/strategy_all_auto_live_preflight_v1.py`
- `RUN/strategy_all_live_gate_launcher_v1.py`
- Windows 작업 `SAFEPLUS_MICRO_RANK_SHADOW`

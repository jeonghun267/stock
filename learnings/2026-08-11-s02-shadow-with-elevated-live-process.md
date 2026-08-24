# [2026-08-11] 관리자 권한 라이브 신호기와 분리한 S02 그림자 실행

## 접근법
1. 기존 S02 매수 경로를 바꾸지 않고 `detect_flow_book_exhaustion`을 주문 0 그림자 분기로 추가했다.
2. 그림자 신호를 별도 목록·CSV로 분리하고 `SHADOW_ORDER_ZERO`, `[HYPOTHETICAL]`을 기록했다.
3. 일반 셸의 종료 권한이 거부되어, 대상 PID·시작시각·주문엔진 PID를 검증하는 관리자 PowerShell을 UAC로 실행했다.
4. 구형 신호기만 종료하고 예약 작업으로 신호기를 재기동한 뒤 새 그림자 필드가 라이브 JSON에 생겼는지 확인했다.
5. 단위 테스트로 그림자 신호가 라이브 `signals` 목록에 들어가지 않는지 검증했다.

## 하지 않은 것과 이유
- 검증 없이 관리자 PID를 종료하지 않았다. 이유: 주문 엔진 오인 종료와 장중 서비스 중단 위험이 있다.
- 그림자 결과를 실거래 조건에 연결하지 않았다. 이유: `[PROD_REPLAY]` 통과 전에는 라이브 연결이 금지된다.
- 임시 비관리자 runner는 관리자 재기동 성공 후 종료했다. 이유: 중복 관측과 불필요한 부하를 남기지 않기 위해서다.

## 재사용 규칙
장중 관리자 권한 신호기를 교체할 때는 대상 PID·시작시각·주문엔진 lock PID를 먼저 검증하고, UAC 관리자 스크립트로 신호기만 종료한 뒤 예약 작업을 재실행하라.

## 관련 파일/명령
- `RUN/strategy_02_low_buy_signal_v1.py`
- `RUN/strategy_02_flow_book_shadow_runner_v1.py`
- `RUN/restart_s02_signal_admin_20260811.ps1`
- `tests/test_strategy_02_v1.py`
- `python -m unittest tests.test_strategy_02_v1`

# 2026-07-27 콜백은 도착했지만 중첩 IPC 폴링과 게이트 계약 불일치가 사전점검 PASS 뒤 실전 엔진 기동을 연쇄 차단했다

## 접근법
1. 공통 사전점검 로그와 브로커 저널을 대조해 `OnReceiveTrData`가 도착했는데 잔고조회만 TIMEOUT이 된 사실을 확인한다.
2. `QEventLoop.exec_()` 중에도 500ms poll timer가 재진입해 다음 TR이 전역 `tr_loop`와 `tr_output_fields`를 덮어쓰는 호출 순서를 추적한다.
3. 한 번의 IPC poll pass가 끝날 때까지 중첩 `poll_requests()`를 차단하고 브로커를 정상 종료·watchdog 재기동한 뒤 읽기 전용 잔고조회를 재검증한다.
4. 정식 사전점검 PASS 뒤 LIVE 작업이 종료 코드 2를 내는 로그를 확인하고, 게이트의 `--strategy`가 import한 엔진의 `argparse(--once)`까지 전달되는 계약 누수를 제거한다.
5. S01 bootstrap이 자기 LIVE 작업을 다시 실행하는 재귀를 제거한다.
6. 전략 4의 신선한 호가가 `DATA_WAIT`로 남는 원인을 추적해 공통 후보 발행기가 valley의 `all_meta.prev_close`를 덮어쓰는 문제를 수정한다.
7. 전략 4 사전점검에 신호 `status=LIVE`와 topbook 수를 필수화하고, 느린 예약작업 조회 뒤에는 실제 관측 시각으로 신선도를 계산한다.
8. 최종 통합 중계에서 전략 1·2·3·4가 모두 LIVE이고 heartbeat 1~2초, 공용 슬롯·실제 체결·완결 매매가 표시되는지 확인한다.

## 하지 않은 것 + 이유
- 승인 파일을 수동 생성하거나 OFF 파일을 직접 삭제하지 않음. 이유: 읽기 전용 검증 PASS 뒤 기존 정식 사전점검 함수만 승인 상태를 바꾸게 해야 감사 가능성과 실패 시 닫힘을 유지할 수 있다.
- 매수·매도 조건과 비용 임계값은 바꾸지 않음. 이유: 이번 장애는 신호 품질이 아니라 브로커 IPC와 실행 계약 문제였고, 장중 긴급 복구에서 전략 행동까지 바꾸면 원인 분리가 불가능하다.
- 도착한 TR 콜백을 임의 지연 재사용하지 않음. 이유: 잘못된 요청에 늦은 응답을 결합하면 잔고·미체결 진실값이 오염될 수 있어 요청 직렬화가 더 안전하다.

## 재사용 규칙
Qt 중첩 이벤트 루프에서 전역 응답 상태를 쓸 때는 폴링 재진입을 직렬화하고, 게이트가 엔진 `main()`을 import 호출할 때는 게이트 전용 `argv`를 제거한 뒤 실제 heartbeat까지 검증하라.

## 관련 파일/커밋
- `RUN/broker_gateway_v1.py`
- `RUN/strategy_all_auto_live_preflight_v1.py`
- `RUN/strategy_all_live_gate_launcher_v1.py`
- `RUN/strategy_01_bootstrap_v1.py`
- `RUN/strategy_common_candidate_context_v1.py`
- `RUN/strategy_04_preflight_v1.py`
- `RUN/strategy_04_live_gate_launcher_v1.py`
- `RUN/stockbot_live_broadcast_v1.py`

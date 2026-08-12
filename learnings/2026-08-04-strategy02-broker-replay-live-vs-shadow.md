# 2026-08-04 전략 2의 실브로커 실패 기록과 과거자료 SHADOW 체결 결과를 혼동하지 않고 매수·매도 시점을 확인

## 접근법
1. 운영 이벤트와 상태파일에서 당일 실브로커 주문 시도·실패 이유를 먼저 확인한다.
2. 당일 전략 2 신호파일에서 319400의 원본 BUY_READY 두 건을 추출한다.
3. `Strategy02Engine`과 실제 `StrategyBroker`의 SHADOW 주문경로를 임시 상태파일에 연결한다.
4. 저장된 고저폭 시세·수급·1분봉을 시간순으로 공급하고 공통매도까지 직접 실행한다.
5. MA3 보조기가 운영 전체 파일을 매 틱 다시 읽는 경로를 재생용 시점 파일로 고정해 반복 실행 시간을 줄인다.
6. 주문기록·체결상태·종료사유를 운영 실브로커 기록과 SHADOW 재생 결과로 나눠 보고한다.

## 하지 않은 것 + 이유
- SHADOW 재생 체결을 오늘 실계좌 체결이라고 표현하지 않음. 이유: 오늘 실브로커는 잔고 TR 타임아웃으로 주문 제출 전 중단됐다.
- 신호가격이나 매도 임계값을 결과에 맞춰 변경하지 않음. 이유: 이번 작업은 현재 운영코드의 실제 동작 확인이지 조건 최적화가 아니다.
- 장 마감 뒤 실주문을 강제로 제출하지 않음. 이유: 체결 가능한 시장이 아니며 과거 시점 검증은 SHADOW 브로커가 담당해야 한다.

## 재사용 규칙
과거 전략을 브로커로 재생할 때는 실브로커 운영증거와 SHADOW 재생결과를 분리하고 모든 보조 데이터 경로를 같은 재생 시계에 고정하라.

## 관련 파일/커밋
- RUN/strategy_02_rotation_engine_v1.py
- RUN/strategy_01_rotation_engine_v2.py
- RUN/strategy_common_order_v1.py
- data/strategy_02_low_buy_signal_v1.json
- data/strategy_02_rotation_v1/strategy_02_events_20260804.csv
- data/high_range_shadow_20260804.csv
- data/prices_1m_clean_20260804.csv

# 2026-08-04 장세 일회 판정과 누락된 실행 배선 때문에 유효한 종목 신호가 전략에 도달하지 못함

## 접근법
1. 장세 판정기가 생성하는 전략 OFF 깃발과 당일 판정 기록을 대조한다.
2. 각 신호 모듈의 클래스 존재 여부가 아니라 실제 실행기 import·호출 경로를 추적한다.
3. 전략 3의 장초 검출기와 장중 검출기를 시간대별로 분리 배선하고 계약 검증도 레인별로 나눈다.
4. 전략 1~6의 주문수량을 2주로 맞추고 전략 6을 기존 공용 6슬롯 장부에 연결한다.
5. 장세 판정기는 기록만 남기도록 바꾸고 과거 자동 OFF 깃발만 제거한다.
6. 319400 당일 자료 재생과 레인·계약·슬롯 회귀 테스트로 실행 경로를 검증한다.

## 하지 않은 것 + 이유
- 전략별 고유 매수조건을 하나로 합치지 않음. 이유: 전략은 동시에 열되 서로 다른 가격·수급 패턴을 독립적으로 판단해야 한다.
- 사람이 만든 수동 OFF 깃발을 장세 판정기가 임의로 지우게 만들지 않음. 이유: 자동 판정 해제와 사용자의 긴급 정지는 권한이 다르다.
- 기존 골짜기 헌터의 폐기 표시인 `valley_off.flag`를 제거하지 않음. 이유: 새 전략 3과 별개인 구형 주문 경로가 다시 살아날 수 있다.

## 재사용 규칙
여러 전략을 조건부 동시 운용할 때는 장세로 전략 전체를 끄지 말고 각 신호를 계속 평가하되 주문 직전에 공용 수량·슬롯·중복 관문으로 통제하라.

## 관련 파일/커밋
- RUN/regime_priority_judge_v1.py
- RUN/골짜기_급반등.py
- RUN/strategy_03_intraday_rebound_v1.py
- RUN/strategy_03_signal_contract_v1.py
- RUN/strategy_06_crash_low_chase_v1.py
- RUN/shared_slots.py
- tests/test_strategy_03_intraday_rebound_v1.py
- tests/test_strategy_06_crash_low_chase_v1.py
- tests/test_regime_priority_judge_v1.py

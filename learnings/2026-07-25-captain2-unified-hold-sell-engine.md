# [2026-07-25] 캡틴2 7개 진입전략의 상승보유·매도를 통합하되 프로필은 분리

## 접근법
1. 기존 엔진의 진입 경로를 추적해 EARLY 3경로, RAID, PULL, BASE, REACCEL의 7개 전략을 확정했다.
2. 7개 전략이 모두 `_hold_or_sell()`로 합류하는 사실과 전략별 예외를 코드와 실행 CMD에서 대조했다.
3. 하드손절 → 시간청산 → EARLY 추세판단 → MA3 상승보유 → 이익 트레일 → 돈마름 → 점수 → 흐름·구조 순서를 하나의 결정 엔진으로 고정했다.
4. EARLY 시간, PULL 손절·최소보유, RAID/PULL/BASE의 MA3 차이는 불변 전략 프로필로 분리했다.
5. 매도 판단은 주문을 직접 실행하지 않고 결정과 결정적 멱등성 키만 만들도록 분리했다.
6. 7전략 매핑, 우선순위, 타이머 초기화, 재시작 상태복원, 중복매도 억제를 20개 단위테스트로 검증했다.
7. 기존 공통기반 14개 테스트도 함께 실행해 새 모듈 추가가 기존 동작을 깨지 않았음을 확인했다.

## 하지 않은 것 + 이유
- 기존 `CAPTAIN2_MONEYFLOW_ENGINE_V1.py`에 연결하지 않음. 이유: 사용자 승인 전 실전 동작 변경을 막고 독립 검증을 먼저 끝내기 위해서다.
- 매수조건을 수정하지 않음. 이유: 현재 단계는 공통 상승보유·매도이며 매수조건은 마지막 단계로 확정됐다.
- 손절·시간·트레일·수급 임계값을 새로 튜닝하지 않음. 이유: 기존 확정 동작을 회귀기준으로 보존해야 효과를 분리할 수 있다.
- 실계좌 주문과 예약작업을 실행하지 않음. 이유: 안전 규칙상 mock·dry-run·단위테스트에서만 검증해야 한다.
- 새로운 꼭지점 임계값을 발명하지 않음. 이유: 기존 고점 트레일을 상태화했으며 새 숫자는 별도 데이터 검증과 승인이 필요하다.

## 재사용 규칙
여러 매수전략의 출구를 통합할 때는 판단 우선순위와 주문 경로는 하나로 모으고, 검증된 전략별 차이는 불변 프로필로 남겨라.

## 관련 파일/명령
- `RUN/captain2_common_hold_sell_v1.py`
- `tests/test_captain2_common_hold_sell_v1.py`
- `RUN/captain2_common_foundation_v1.py`
- `C:\python310\python.exe -B -m unittest discover -s tests -p test_captain2_common_hold_sell_v1.py -v`
- `C:\python310\python.exe -B -m unittest discover -s tests -p test_captain2_common_foundation_v1.py -v`

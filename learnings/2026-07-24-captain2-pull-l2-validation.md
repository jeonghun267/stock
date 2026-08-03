# 2026-07-24 캡틴2 PULL의 L2가 실제 재눌림 없이도 확정되는 구조 결함

## 접근법
1. `CAPTAIN2_MONEYFLOW_ENGINE_V1.py`의 PULL 저점탐색, RESET, 매수신호 순서를 직접 추적한다.
2. 2026-07-23~24 이벤트에서 PULL L1 확인 뒤 `LOW_UPDATED`가 발생한 경우와 발생하지 않은 경우를 분리한다.
3. 캡틴2 PULL RESET 373개를 원시 1초 체결자료에 연결해, 잘못된 짧은 진입창 대신 저점 이후 60초 동안 현재 5조건을 재계산한다.
4. 실제 재눌림이 있었던 156개와 없었던 217개의 5조건 신호 후 10분·30분 성과와 MFE·MAE를 비교한다.
5. L1 확인 직후 현재가를 L2 후보로 다시 넣는 코드 때문에, 후속 하락 없이 15초를 버티기만 해도 L2가 될 수 있음을 확인한다.

## 하지 않은 것 + 이유
- PULL 임계값이나 전략 코드는 수정하지 않음. 이유: 사용자가 먼저 기존 조건의 타당성 검토만 요청했고, 구조 결함 수정은 별도 승인이 필요하다.
- 과거 PULL 매수 0건을 5조건 탓으로 단정하지 않음. 이유: 당시 코드는 L2를 15초 동안 확인한 뒤에도 공통 진입창을 사용해 약 1초 만에 실패시키는 별도 시간창 결함이 있었고, 현재 코드는 PULL 60초 창으로 이미 분리되어 있다.
- 2일 결과만으로 수익성을 확정하지 않음. 이유: 표본 기간이 짧고 원시자료 재구성은 실제 주문·슬리피지를 포함한 체결 백테스트가 아니다.

## 재사용 규칙
상태 이름이 L1/L2·재눌림이라고 되어 있을 때는 주석을 믿지 말고, 중간 반등과 후속 하락을 강제하는 상태 전이가 실제 코드와 이벤트에 존재하는지 확인하라.

## 관련 파일/커밋
- `C:\stock_bot\RUN\CAPTAIN2_MONEYFLOW_ENGINE_V1.py`
- `C:\stock_bot\data\shadow\captain2_events_20260723.csv`
- `C:\stock_bot\data\shadow\captain2_events_20260724.csv`
- `C:\stock_bot\data\shadow\captain2_replay\captain2_1s_20260723.csv`
- `C:\stock_bot\data\shadow\captain2_replay\captain2_1s_20260724.old1.csv`
- `C:\stock_bot\data\shadow\captain2_replay\captain2_1s_20260724.csv`
- `C:\stock_bot\data\shadow\mf_1s_capture\mf_1s_20260723.csv`
- `C:\stock_bot\data\shadow\mf_1s_capture\mf_1s_20260724.csv`

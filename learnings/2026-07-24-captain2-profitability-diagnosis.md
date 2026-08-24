# [2026-07-24] 캡틴2 수익성 약점 진단

## 접근법
1. 실제 BUY부터 같은 종목의 다음 실제 SELL까지 완결 거래를 재구성하고 SHADOW 및 미청산 건을 제외한다.
2. 비용 전 수익률과 왕복비용 0.469%를 차감한 수익률을 분리해 거래별 기대값을 계산한다.
3. 보유시간, 청산 사유, 재진입 차수, 진입 레인별로 손익을 분해한다.
4. 리플레이가 연결되는 거래는 MFE/MAE를 계산해 진입 뒤 실제 상승 여력이 비용을 넘었는지 확인한다.
5. 실측 결과를 전략 코드의 진입 게이트, 시장 국면 필터, MA 사용 위치, 매도 우선순위와 교차검증한다.

## 하지 않은 것 + 이유
- 매도 조건만 원인으로 단정하지 않았다. 이유: 진입 후 MFE 자체가 비용보다 작은 거래가 많으면 매도 규칙만 바꿔도 양의 기대값을 만들기 어렵다.
- RAID, EARLY, PULL을 한 전략으로 합산해 평가하지 않았다. 이유: 실제 PULL 체결이 0건이라 의도한 눌림목 전략의 성과와 급등 추격 성과를 구분해야 한다.
- 같은 3일 데이터에 맞춘 임계값을 바로 제안하지 않았다. 이유: 장중 변경이 반복된 표본은 과최적화 위험이 크므로 고정 조건의 전진 검증이 먼저다.

## 재사용 규칙
초단타 전략의 수익성을 진단할 때는 승률보다 먼저 `진입 후 MFE 분포가 왕복비용을 충분히 넘는지`와 `실제 체결 레인이 설계 의도와 일치하는지`를 확인하라.

## 관련 파일/커밋
- C:\stock_bot\data\shadow\captain2_events_20260722.csv
- C:\stock_bot\data\shadow\captain2_events_20260723.csv
- C:\stock_bot\data\shadow\captain2_events_20260724.csv
- C:\stock_bot\data\shadow\captain2_replay\captain2_1s_*.csv
- C:\stock_bot\RUN\CAPTAIN2_MONEYFLOW_ENGINE_V1.py
- C:\stock_bot\RUN\captain2_evening_report_v1.py

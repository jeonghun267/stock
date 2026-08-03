# 2026-08-02 전략 6 단위시험 통과와 실제 저점 탐지 성능을 분리해 검증

## 접근법
1. 운영 소스의 `Config` 기본값과 SHA-256을 직접 읽어 재생 조건이 배포본과 같은지 고정한다.
2. 전일 일봉만으로 고저폭30 핵심확인대를 복원하고, 종가 기준 상승일은 결과 보고에서 제외한다.
3. 저장된 1초 시세를 종목별 시간순으로 정렬·중복 제거하고 09:00~14:30 신호에는 현재 시점까지의 가격·누적 매수/매도금액만 사용한다.
4. `-8% → +1.5% 첫 반등 → 0.4% 눌림 → 원저점+0.3% 높은 두 번째 저점 → +0.5% 재반등 → 수급역전·10초 재가속` 상태 전이를 운영 코드와 같은 실패폐쇄 방식으로 재생한다.
5. 신호가 확정된 뒤에만 15:20까지 신저점, MFE, MAE를 사후 평가하고 신호 생성과 분리한다.
6. 결과 CSV를 PowerShell로 별도 집계하고 운영 회귀시험 15개도 다시 실행해 수치와 상태기계를 각각 검산한다.

## 하지 않은 것 + 이유
- 단위시험 15/15를 실제 성능 검증으로 간주하지 않음. 이유: 단위시험은 만든 경로가 코드에서 동작하는지만 보장하고 역사적 발생빈도와 저점 정확도를 보장하지 않는다.
- 3건 결과로 조건을 더 조이거나 완화하지 않음. 이유: 표본이 작고 매수·매도 조건 변경은 사용자 승인 대상이다.
- 금요일 상승일을 보통·하락일 결과에 섞지 않음. 이유: 사용자가 상승일 제외를 요청했고 시장 국면이 결과를 크게 왜곡한다.
- 실제 주문을 실행하지 않음. 이유: 검증은 과거자료 재생과 그림자 단위시험으로만 수행해야 한다.

## 재사용 규칙
거래전략의 새 진입식이 단위시험을 통과했을 때는 "코드 동작"으로만 보고하고, 실제 저장시세의 시간순 재생에서 신호 수·사후 신저점·MFE까지 확인하기 전에는 "저점을 잘 잡는다"고 말하지 마라.

## 관련 파일/커맨드
- C:\Users\UserK\strategy6_analysis\strategy6_current_production_replay.py
- C:\Users\UserK\strategy6_analysis\outputs\strategy6_current_production_results.json
- C:\Users\UserK\strategy6_analysis\outputs\strategy6_current_production_entries.csv
- C:\stock_bot\RUN\strategy_06_crash_low_chase_v1.py
- `C:\python310\python.exe -m unittest discover -s tests -p test_strategy_06_crash_low_chase_v1.py -v`

# 2026-08-02 PowerShell에서 Python 표준입력으로 넘긴 한글 분류값이 깨져 모든 장세가 같은 값으로 비교된 문제

## 접근법
1. 후보 종목과 분봉 날짜의 교집합을 출력해 입력 데이터가 비어 있지 않은지 확인했다.
2. 날짜별 장세값의 `repr`과 상승일 비교 결과를 함께 출력해 NORMAL, DOWN, UP이 모두 `??`로 변환된 것을 확인했다.
3. Python 내부 상태값을 `UP`, `NORMAL`, `DOWN` ASCII 열거값으로 바꿔 분류를 다시 실행했다.
4. 상승일 행 0건, 시간대 비중 합계 100%, 전일 source_date 위반 0건, 익일 거래일 불일치 0건을 독립 검증했다.

## 하지 않은 것 + 이유
- 한글 출력 전체를 없애지는 않음. 이유: 문제는 사용자용 표시가 아니라 PowerShell here-string을 거치는 내부 비교값이었고, 내부 열거값만 ASCII로 고정하면 표시 언어를 유지할 수 있다.
- 깨진 값을 임의로 보통일로 처리하지 않음. 이유: 상승일이 섞이면 사용자의 핵심 제외 조건을 위반하고 결과 전체가 왜곡된다.

## 재사용 규칙
PowerShell에서 Python 표준입력으로 분류·상태 상수를 넘길 때는 내부 비교값을 ASCII 열거값으로 고정하고 `repr`로 서로 다른 값인지 먼저 검증하라.

## 관련 파일/커밋
- C:\Users\UserK\.codex\visualizations\2026\08\02\019fbffa-74c0-77c1-bdd4-55ae5fa23cc0\strategy6_low_time_analysis.py
- C:\Users\UserK\.codex\visualizations\2026\08\02\019fbffa-74c0-77c1-bdd4-55ae5fa23cc0\strategy6_low_time_results.json

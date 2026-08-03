# [2026-07-24] PARTIAL EOD 정식 파일 덮어쓰기 차단

## 문제
전종목 일봉 수집이 5시간 제한으로 중단되어 4,302종목 중 779종목만 수집됐는데도, 수집된 행 내부의 결측·신선도만 평가한 QA가 100점으로 계산되어 부분 파일이 `eod_daily_bars.csv`를 덮어썼다.

## 접근법
1. `collect_eod.done`, `collect_eod_qa.json`, `collect_eod_retry.json`을 함께 대조해 `PARTIAL`, 779코드, 재시도 3,369코드를 확인했다.
2. 수집기의 `aborted → done_status=PARTIAL` 경로와 `atomic_write()` 호출 분기를 추적했다.
3. 기존 SHRINK_GUARD가 80% 미만 급감만 막고 `KOSDAQ_ONLY`에서는 제외되는 사실을 확인했다.
4. `done_status == "PARTIAL"`을 종목 수 비교와 QA FAIL보다 먼저 처리해 정식 파일 저장을 차단하고 이전 정상 파일을 유지하도록 했다.
5. 문법 검사, diff 검사, AST 구조 검사로 PARTIAL 본문에 `atomic_write()`가 없음을 독립 검증했다.

## 하지 않은 것 + 이유
- QA 점수 임계값만 조정하지 않았다. 이유: 수집된 779종목의 행 품질은 100점일 수 있어도 목표 유니버스 완전성을 보장하지 못한다.
- 80% SHRINK_GUARD만 믿지 않았다. 이유: 80~99% 부분수집은 통과하고 코스닥 전용 모드에서는 보호가 꺼진다.
- 매수·매도 조건과 골짜기/캡틴2 전략을 변경하지 않았다. 이유: 이번 원인은 전략 문턱이 아니라 공용 입력 데이터의 게시 안전성이다.

## 재사용 규칙
수집 완료 상태가 `PARTIAL`이면 품질점수와 수집 비율을 보지 말고 정식 공용 데이터 게시를 금지하며, 마지막 정상본과 실패 상태 신호를 분리해서 보존하라.

## 관련 파일/명령
- `RUN/collect_eod_daily_bars_v2_4_SAFEPLUS_FINAL.py`
- `LOG/collect_eod.done`
- `LOG/collect_eod_qa.json`
- `LOG/collect_eod_retry.json`

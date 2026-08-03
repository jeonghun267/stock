# [2026-07-25] Windows 샌드박스에서 자동 생성 패치로 최소 변경하기

## 문제 한 줄
`apply_patch` 초기화 오류와 수동 hunk 오류가 반복되는 Windows 환경에서 기존 dirty worktree를 보존하며 승인된 파일만 안전하게 수정해야 했다.

## 접근법
1. 수정 전 대상 파일을 임시 백업하고 SHA-256을 기록한다.
2. 실제 파일은 그대로 둔 채 임시 desired 사본에 정확히 한 번만 일어나는 문자열 치환을 적용한다.
3. 원본과 desired 사본의 diff를 전부 검토하고 AST 및 `git diff --check`를 통과시킨다.
4. `git diff --no-index`가 만든 hunk의 헤더만 실제 상대경로로 바꾼다.
5. `git apply --check` 후 실제 파일에 적용하고 AST, mock 계약, 대상 경로 상태를 다시 검증한다.
6. `-B`와 전용 mock 분기로 엔진·스케줄러·브로커·주문 호출 및 바이트코드 쓰기를 막는다.

## 하지 않은 것 + 이유
- 실패한 `apply_patch`를 계속 재시도하지 않았다. 이유: Windows sandbox helper 초기화 오류가 3회 반복돼 같은 경로의 성공 가능성이 없었다.
- 수동으로 hunk 줄 수를 계산한 patch를 사용하지 않았다. 이유: 한글·긴 파일에서 hunk count와 문맥 오류가 반복돼 원인 추적과 안전성이 떨어졌다.
- desired 사본을 원본 위에 통째로 복사하지 않았다. 이유: 기존 사용자 변경을 보존했다는 증거와 적용 전 검토 단계를 잃기 때문이다.

## 진단 질문
- 실제 원본 해시가 사전 백업과 같은가?
- desired diff에 승인되지 않은 파일·함수·설정이 포함됐는가?
- 검증 명령이 엔진 `run()`이나 실계좌 연결 경로를 호출하는가?

## 재사용 규칙
Windows 샌드박스에서 직접 패치 도구가 반복 실패할 때는 원본을 덮어쓰지 말고, 해시가 고정된 원본과 desired 사본에서 diff를 자동 생성한 뒤 `git apply --check`를 통과한 patch만 적용하라.

## 관련 파일/명령
- `RUN/CAPTAIN2_MONEYFLOW_ENGINE_V1.py`
- `RUN/strategy_watchlist.py`
- `RUN/captain2_wiring_check_v1.py --mock-contracts`
- `git diff --no-index`, `git apply --check`, Python `ast.parse`
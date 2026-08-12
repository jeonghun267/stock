# [2026-08-04] 승인 검증을 조였더니 S06만 다음날 조용히 그림자로 떨어지게 돼 있었다

## 접근법

1. **깃발 내용을 실측했다.** S04·S05·S06 셋 다 `20260804` 날짜라 내일이면 무효.
   여기까지 보고 "셋 다 구멍"이라고 친구님께 보고했다 — **이게 성급했다.**
2. **갱신 주체를 하나씩 추적했다.** 깃발을 쓰는 코드를 전수 검색:
   - S01~S03 `strategy_all_auto_live_preflight_v1.py:278` 08:59:35 (점검 통과 시)
   - S04 `SAFEPLUS_STRATEGY04_PREFLIGHT.cmd` -> `strategy_04_preflight_v1.py --approve` 09:57
   - S05 `SAFEPLUS_STRATEGY05_LIVE.cmd` -> `strategy_05_preflight_v1.py --approve` 09:25
     (`strategy_05_preflight_v1` 은 S04 preflight 에 위임 — 그래서 approve 언급이 1건뿐)
   - **S06 없음**
   → 구멍은 셋이 아니라 **하나**였다. 보고를 정정했다.
3. **S06 태스크를 못 찾을 뻔했다.** 이름이 `SAFEPLUS_*` 가 아니라 `STRATEGY06_LIVE` 라
   접두어로 거른 목록에 안 나왔다. 실행 인자로 다시 훑어 찾았다(08:55·월~금).
4. **정지 스위치를 코드가 아니라 문서에서 찾았다.** `run_strategy_06_crash_low_chase.cmd`
   주석에 `off: create strategy_06_off.flag (buys only) / delete approval flag (full shadow)`.
   → **깃발의 존재 자체가 친구님의 상시 결정**이라는 뜻. 이걸 설계 근거로 삼았다.
5. **"날짜만 미는" 갱신기로 좁혔다.** 깃발이 이미 있고 형식이 맞을 때만 날짜를 오늘로.
   없으면 절대 만들지 않는다.
6. **사본으로 내일을 시뮬레이션했다.** 실물 깃발을 복사해 `now=8/5` 로 돌리고,
   `StrategyBroker._guard_decision` 까지 태워 `buy_allowed=True` 를 확인했다.
   배선 전 8/5 승인유효 False -> 배선 후 True.

## 하지 않은 것 + 이유

- **S04·S05 는 건드리지 않았다.** 이미 자기 preflight 가 매일 갱신한다. 확인 없이
  "셋 다 고치자"로 갔으면 멀쩡한 승인 경로를 두 겹으로 만들 뻔했다.
- **없는 깃발을 만들지 않는다.** 이게 이 파일의 핵심 제약이다. 없는 승인을 만들어내면
  갱신이 아니라 **무단 승인**이고, 친구님의 "전면 그림자" 스위치를 부수는 것이다.
- **점검 통과를 조건으로 걸지 않았다(S04·S05 방식).**
  이유: S06 에는 preflight 가 아예 없다. 새로 만들면 그 자체가 큰 신규 코드이고,
  오늘 밤에 검증 없이 넣을 물건이 아니다. 지금 배선은 **어제까지의 동작(영구 깃발 =
  매일 실전)을 그대로 유지**할 뿐 권한을 넓히지 않는다. S06 preflight 는 별건으로 남긴다.
- **미래 날짜 깃발은 끌어내리지 않는다.** 시계가 뒤로 갔을 때 승인을 과거로 되돌리면
  그것도 무단 변경이다. 손대지 않고 사유만 남긴다.

## 재사용 규칙

**"N개가 깨졌다"고 보고하기 전에 각각의 갱신/복구 주체를 따로 추적하라.**
같은 증상(깃발 날짜가 어제)이라도 스스로 낫는 것과 안 낫는 것이 섞여 있다.
실측 하나로 묶어서 보고하면 멀쩡한 걸 고치게 된다.

**보조 규칙 1:** 예약작업을 이름 접두어로 거르지 마라. `SAFEPLUS_*` 로 훑어서
`STRATEGY06_LIVE` 를 놓칠 뻔했다. **실행 인자로 훑어야** 전수가 된다.

**보조 규칙 2:** 정지 스위치가 코드에 안 보이면 **주석·문서를 봐라.** S06 의 두 스위치는
`.cmd` 주석에만 적혀 있었고, 그게 이 배선의 설계 근거가 됐다.

**보조 규칙 3(내가 어긴 것):** `.cmd` 를 Edit 로 고치면 **줄바꿈이 LF 로 바뀐다.**
원본은 CRLF 혼합이었는데 편집 후 전부 LF 가 됐다. 고친 뒤 CR/LF 개수를 세서
전부 CRLF 인지 확인하고 아니면 바이트로 다시 써야 한다. ([[feedback-cmd-must-be-crlf]])

## 관련 파일/커밋

- `RUN/strategy_06_daily_approve_v1.py` — 신규(갱신 전용, 생성 금지)
- `RUN/run_strategy_06_crash_low_chase.cmd` — 엔진 앞에 배선, ASCII·전부 CRLF 확인
- `tests/test_strategy_06_daily_approve_v1.py` — 신규 10건(갱신 3 / 절대금지 7)
- 백업: `RUN/backup/run_strategy_06_crash_low_chase_20260804_before_daily_approve.cmd`
- 증거: 사본 시뮬레이션 `배선 전 8/5 승인유효 False -> 배선 후 True ->
  buy_allowed=True`. 전체 **398 passed**, 기존 실패 7건 유지.

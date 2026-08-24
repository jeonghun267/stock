# [2026-08-04] 재생 검증기가 불일치를 기록해 놓고도 status 를 항상 "PASS" 로 써서, 게이트가 무조건 통과시키고 있었다

## 접근법

1. **게이트가 무엇을 근거로 판정하는지부터 읽었다.**
   `verified_replay_gate_v1.py:38`이 `report["status"] != "PASS"`만 본다 → 그 값을
   누가 쓰는지 역추적 → `verified_hold_sell_replay_v1.py:135`에서 **딕셔너리 리터럴로
   하드코딩**. 132~183줄 어디에서도 재할당되지 않음을 확인.
2. **불일치가 실제로 계산은 되고 있는지 확인했다.** `mismatches`(:107)에 담기고
   `capture_replay_mismatches`(:148)로 저장까지 된다. **계산은 맞고 판정만 없었다.**
   → 고칠 곳이 판정 한 줄임이 확정됐다.
3. **기존 테스트가 왜 못 잡았는지 봤다.** `test_verified_hold_sell_replay_v1.py:96,100`이
   일치 케이스만 검사. 불일치를 만드는 테스트가 아예 없었다.
4. **불일치를 만드는 방법을 설계했다.** 감사 파일은 해시 체인으로 잠겨 있어 사후
   변조가 불가능하다(기존 `test_tampered_audit_fails_closed`가 증명). 그래서
   **기록 시점부터 다른 판정을 적는** 레코더 서브클래스를 만들었다.
5. **종료코드도 같이 고쳤다.** status 를 고쳐도 `main()`이 항상 0을 반환하면
   예약작업·배치는 성공으로 읽는다.
6. **게이트 쪽도 막았다.** status 한 줄만 믿으면, 옛 판(backup 에 남아 있다)으로 뽑은
   리포트나 손으로 고친 리포트가 그대로 통과한다 → 게이트가 근거
   (`capture_replay_mismatches`)를 직접 확인하게 했다. 키가 없으면 거부(fail-closed).

## 하지 않은 것 + 이유

- **`production_code_changed`를 FAIL 조건에 넣지 않았다.**
  이유: 코드가 바뀐 뒤 과거 판정을 재현하는지 보는 게 재생의 목적이다. 코드가 바뀐 것
  자체는 FAIL 이 아니라 **재생을 돌려야 하는 이유**다. 불일치가 없으면 통과가 맞다.
- **실패 시 provenance 를 `[UNVERIFIED]`로 바꾸지 않았다.**
  이유: `[PROD_REPLAY]`는 "운영 재생에서 나온 리포트"라는 출처 표시고 그건 실패해도
  사실이다. 게이트는 provenance AND status 를 함께 보므로 status=FAIL 만으로 충분하다.
- **옛 리포트 일괄 폐기 스크립트를 만들지 않았다.**
  이유: `reports\verified_replay` 폴더와 승인 파일이 **0건**임을 먼저 확인했다.
  치울 게 없는데 도구부터 만드는 건 낭비다.

## 재사용 규칙

**검증 도구를 믿기 전에 "이 도구가 FAIL 을 내는 경로가 있는가"를 먼저 찾아라.**
FAIL 을 만드는 테스트가 없으면 그 도구는 검증하지 않는 것이다.

**보조 규칙(이번에 내가 틀린 것):** 모듈을 임시 폴더로 복사해 "수정 전 코드"를 검증하는
방법은 **`Path(__file__).resolve().parent` 기반 상수가 있는 모듈에서는 무효**다.
`ENGINE_PATH`가 임시 폴더를 가리켜 엉뚱한 실패 6건이 났다. 제자리에서 백업본으로
교체 → 테스트 → 복원이 맞고, 그때 정확히 의도한 3건만 실패했다.

## 관련 파일/커밋

- `RUN/verified_hold_sell_replay_v1.py` — status 산출(+`main()` 종료코드)
- `RUN/verified_replay_gate_v1.py` — 게이트가 불일치 기록을 직접 확인
- `tests/test_verified_hold_sell_replay_v1.py` — 신규 5건(불일치·게이트 거부·손편집·기록누락·종료코드)
- 백업: `RUN/backup/verified_hold_sell_replay_v1_20260804_before_status_fix.py`,
  `RUN/backup/verified_replay_gate_v1_20260804_before_status_fix.py`
- 증거: 수정 전 코드에서 신규 3건 실패 → 수정 후 10/10 통과. 전체 371 passed.
- ⚠️ 작업 중 **다른 세션이 18:41:57에 `hold_sell_audit_v1.py`·`strategy_03_rotation_engine_v1.py`·
  `verified_replay_gate_v1.py`를 동시 수정**했다(S03 해시 비대칭이 그때 해결됨).
  내가 세션 초반에 읽은 내용이 이미 옛것이었다 — **편집 직전 재확인이 필수**.

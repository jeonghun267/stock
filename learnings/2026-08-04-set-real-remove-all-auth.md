# [2026-08-04] 브로커를 살려 둔 채 전 종목 시세만 끊는 무인증 IPC 명령을 막았다

## 접근법

1. **위험도를 먼저 판정했다.** SHUTDOWN 은 브로커가 죽으니 워치독이 하트비트로 잡는다.
   `SET_REAL_REMOVE_ALL` 은 **브로커가 살아 있고 하트비트도 정상인데 실시간만 끊긴다**
   → 워치독의 두 감시축(하트비트·프리징)에 전부 안 걸린다. 더 은밀한 쪽을 먼저 골랐다.
2. **정당한 호출자를 전수 조사했다 — 이게 이번 작업의 분기점이었다.**
   `set_real_remove_all` / `SET_REAL_REMOVE_ALL` 전체 검색 → **호출자 0건**.
   `broker_client.py:385` 에 정의만 있고 부르는 곳이 없다(문서·게이트웨이 핸들러뿐).
   → **fail-closed 로 잠가도 깨질 경로가 없다**는 근거를 먼저 확보했다.
3. **서명 경로가 안전한지 확인했다.** `broker_client.request()` 에서 `request_id`·`ts`·
   `ttl_sec`·`caller` 가 전부 서명 **전**(211~217)에 들어가고 서명 후 추가되는 키가 없다
   → 기존 SENDORDER_REAL 이 동작하는 이유이자, 새 타입도 안전한 이유.
4. **기존 메커니즘을 확장했다.** 새 인증을 만들지 않고 `PROTECTED_TYPES` 집합으로
   대상만 넓혔다(`!= "SENDORDER_REAL"` → `not in PROTECTED_TYPES`).
5. **분기와 서명된 type 을 못박는 `expected_type` 을 넣었다.** 지금은 dispatch 가 같은
   필드를 읽으므로 중복이지만, 분기 기준이 바뀌면 그때 조용히 뚫린다.
6. **배선을 실제로 태워서 확인했다.** 단위 테스트는 서명 함수만 본다. `BrokerGateway`
   가 64비트 파이썬에서도 import 되는 걸 확인하고, `__new__` 로 OCX 없이 인스턴스를
   만들어 `process_request` 를 직접 돌렸다. 핸들러를 스텁으로 바꿔 **핸들러까지
   도달하는지**를 관찰했다.
7. **수정 전 코드로 되돌려 대조했다.** 무서명 요청이 `['REMOVE_ALL:req-remove-all-1']`
   로 핸들러에 도달 = 구멍의 직접 증거. 대조군(실주문)은 전후 모두 통과.
8. **브로커 런타임(32비트)에서 따로 확인했다.** 테스트는 64비트로 도는데 브로커는
   `C:\Python310-32` 다. 컴파일만 믿지 않고 import·서명·검증을 그쪽에서 실행했다.

## 하지 않은 것 + 이유

- **SHUTDOWN·DISCONNECT_SCR·SETREAL_REG 는 안 건드렸다.**
  이유: 지시받은 건 `SET_REAL_REMOVE_ALL` 하나다. 이제 `PROTECTED_TYPES` 에 문자열
  하나 추가하면 되지만, **호출자 전수 조사를 안 한 타입을 잠그면 내일 아침 기동이
  깨진다.** SETREAL_REG 는 정당한 호출자가 많다.
- **명령 자체를 삭제하지 않았다.** 호출자가 0건이니 지우는 게 제일 안전하긴 하다.
  이유: 문서에 "EOD 정리/킬스위치"로 명시된 기능이다. 기능 폐기는 내 판단 범위가
  아니라 친구님 결정 사항. 인증만 걸면 위험은 사라지고 기능은 남는다.
- **거부 시 프로세스 목록을 남기지 않았다.** `_log_shutdown_origin` 처럼 wmic 로
  발신자를 추적하고 싶었지만, **거부는 공격자가 반복 유발할 수 있는 경로**다.
  거기에 5초짜리 subprocess 를 걸면 그 자체가 서비스 거부 수단이 된다. 로그만 남겼다.
- **키를 테스트용 임시 키로 갈아끼우지 않았다.** `verify_order_request` 의
  `secret_path=SECRET_PATH` 는 **def 시점에 평가되는 기본 인자**라 모듈 속성을 나중에
  패치해도 안 바뀐다. 운영 키로 서명하고 같은 키로 검증하되, 키가 없는 환경에서는
  `skipUnless` 로 건너뛴다.

## 재사용 규칙

**무인증 명령을 fail-closed 로 잠그기 전에 정당한 호출자를 전수 조사하라.**
호출자가 0이면 즉시 잠가도 되고, 여럿이면 전부 서명 경로를 타는지 확인한 뒤에 잠가야
한다. 이 조사 없이 잠그는 건 보안 수리가 아니라 장애 유발이다.

**보조 규칙:** 인증을 "붙였다"의 증거는 서명 함수 단위 테스트가 아니라
**관문이 핸들러 앞에 서 있음**을 보이는 배선 테스트다. 핸들러를 스텁으로 바꿔
도달 여부를 관찰하면 OCX·외부 의존 없이 확인할 수 있다.

## 관련 파일/커밋

- `RUN/ipc_order_auth_v1.py` — `PROTECTED_TYPES` 도입 + `expected_type` 인자
- `RUN/broker_client.py` — 서명 조건을 `PROTECTED_TYPES` 로 확장
- `RUN/broker_gateway_v1.py:1527` — SET_REAL_REMOVE_ALL 분기에 관문 추가
  (`[SEC-REALREMOVE-AUTH]` 로그), SENDORDER_REAL 분기에 `expected_type` 명시
- `DOCS/broker_ipc_schema.md` 10번 항목 — 계약 변경 반영
- `tests/test_ipc_order_auth_v1.py` +8건 / `tests/test_ipc_realremove_auth_wiring_v1.py` 신규 5건
- 백업: `RUN/backup/*_20260804_before_realremove_auth.py` (3개)
- 증거: 수정 전 배선 테스트 4/5 실패(무서명 요청이 핸들러 도달) → 수정 후 5/5.
  전체 384 passed / 기존 실패 7건 유지.

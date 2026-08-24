# [2026-08-04] 승인 깃발 검증을 조였더니, 깃발이 깨지면 실포지션을 팔지도 않고 장부에서 지우는 구멍이 생겼다

## 접근법

1. **오늘 바뀐 것만 좁혔다.** mtime + `git status`로 89개 파일 확보 → 보안 관련
   신규/수정 파일 12개로 압축. 전체 코드를 읽지 않았다.
2. **바뀐 판정식의 소비자를 역추적했다.** `real_session`이
   `approval_path.exists()` → `legacy_daily_approval_valid()`(내용·날짜)로 바뀐 걸
   확인한 뒤, `real_session`을 읽는 지점을 전부 grep → `connect` `holdings`
   `open_orders` `submit` `cancel` `mode` 6곳.
3. **"깨지는 입력"을 먼저 찾았다.** `strategy_broker_live_guard.py:64`가
   `encoding="ascii", errors="strict"`로 읽는다 → BOM 3바이트면 UnicodeError →
   `approval_text=""` → 무효. 메모리에 BOM 실사고 이력이 있어 가설이 아니라 기정사실로 다뤘다.
4. **방어막이 왜 안 먹는지 확인했다.** `force_exit_only`가 엔진 `__init__`에서
   **1회만** 계산됨(`strategy_01_rotation_engine_v2.py:308`) → 장중 신규 매수는 미보호.
5. **`submit()`이 최악 지점이 아님을 발견했다.** 호출부를 거슬러 올라가니
   `_start_sell:1665` → `holdings()`가 `real_session` False일 때 **`None`이 아니라 `{}`**를
   반환(`:174`) → `:1674` `actual_qty<=0` → `_confirm_exit("BROKER_ALREADY_FLAT")`.
   **매도 시도조차 없이 포지션이 장부에서 삭제된다.** 여기서 수정 설계를 바꿨다.
6. **회귀 테스트를 먼저 쓰고, 수정 전 코드에 물려 실패를 확인했다.**
   sys.path 앞에 백업본을 끼워 로드 → 10건 중 4건 실패 → 껍데기 테스트가 아님을 증명.
7. **전체 스위트를 수정 전/후로 각각 돌려 대조했다.** 11 fail → 7 fail.
   남은 7건이 8/3부터 있던 MA3 상승보유 실패와 동일함을 확인.

## 하지 않은 것 + 이유

- **`submit()`에 `position_is_real` 인자를 넘기는 안은 버렸다.**
  이유: 5번에서 `holdings()`가 먼저 `{}`를 뱉는 걸 발견했다. `submit()`만 고치면
  거기까지 도달하지도 못한다. **반쪽 수정이 "고쳤다"는 착각을 만드는 게 더 위험하다.**
- **`real_session`을 `live_requested`만 보게 완화하지 않았다.**
  이유: 모의 진입(`real=False`) 포지션에 실매도 주문이 나간다. 메모리의 미해결 항목
  "모의OPEN 있으면 실매도주문"을 악화시킨다.
- **`holdings()`가 `{}` 대신 `None`을 반환하도록 고치지 않았다.**
  이유: `{}`(정상·보유없음)와 `None`(확인불가)의 계약은 옳다. 잘못된 건 반환값이 아니라
  **`real_session`이 False로 떨어진 것**이다. 증상이 아니라 원인을 고쳤다.
- **엔진마다 방어 코드를 넣지 않았다.**
  이유: S02·S04·S05는 공용코어 `strategy_01_rotation_engine_v2.py`를 쓴다.
  공용 지점 1곳 + 엔진 3곳 배선으로 6개 전략이 전부 덮인다.
- **판정 실패 시 fail-closed를 택하지 않았다.** 보유 판정이 예외를 던지면 `True`(실매도 허용).
  이유: 못 파는 쪽(유령 잔량)이 더 비싸다. 매수는 `valid`를 따로 요구하므로 안 열린다.

## 재사용 규칙

**판정식을 "존재 확인"에서 "내용 검증"으로 조일 때는, 그 값을 읽는 소비자를 전부 grep해서
매도·청산·취소 경로가 같이 잠기지 않는지 확인하라.** 강화는 매수에만 걸고,
청산은 별도 근거(포지션 자신의 `real` 플래그)로 열어 둬야 한다.

**보조 규칙:** `__init__`에서 1회 계산한 boolean이 장중에 변하는 사실을 나타낸다면
그건 스냅샷이 아니라 호출가능 객체여야 한다.

## 관련 파일/커밋

- `RUN/strategy_common_order_v1.py` — `force_exit_only`를 property로 (호출가능 객체 허용)
- `RUN/strategy_01_rotation_engine_v2.py:308` — 공용코어(S01~S05) 배선
- `RUN/strategy_06_crash_low_chase_v1.py:360` — S06 배선
- `RUN/strategy_01_open_surge_engine_v1.py:252` — 구 S01 엔진 배선
- `tests/test_strategy_common_order_sell_lock_v1.py` — 신규 회귀 10건
- 백업: `RUN/backup/*_20260804_before_sell_lock_fix.py` (4개)
- 증거: 수정 전 11 fail → 수정 후 7 fail(잔여 7건은 8/3 MA3 상승보유 기존 실패)

# 2026-08-10 매도 이후 생산 관측값 재생 경계

## 문제
기존 보유·매도 감사자료는 생산 엔진이 매도한 순간 끝나므로, 더 오래 보유하는 후보 조건이 이후 언제 매도했을지를 정확한 생산 경로로 검증할 수 없었다.

## 접근법
1. 기존 매도 판단과 주문 경로는 변경하지 않았다.
2. 청산된 포지션에 대해 60초 동안 기존 `_snapshot_point`와 `_build_observation`을 그대로 호출했다.
3. 결과를 별도 해시체인 JSONL에 기록해 기존 매도 감사자료와 섞이지 않게 했다.
4. 검증 재생기가 포지션 ID와 시간 연속성을 확인한 뒤 이 관측값을 이어서 재생하도록 했다.
5. 별도 기록 경로가 주문을 추가하지 않는지와 변조 검증을 집중 테스트했다.

## 하지 않은 것과 이유
- MA20 보유나 매도 임계값을 바로 변경하지 않았다. 이유: 기존 자료는 원래 매도 뒤의 체결량·체결강도·이평선 관측값이 없어 변경 결과가 `[PROD_REPLAY]`로 입증되지 않았기 때문이다.
- 기존 매도 감사 파일에 사후 관측값을 억지로 붙이지 않았다. 이유: 실제 생산 결정과 결정하지 않은 사후 관측을 같은 의미로 오인할 수 있기 때문이다.

## 재사용 규칙
현재 조건보다 오래 보유하는 매도 후보를 검증할 때는, 기존 매도 시점까지의 생산 감사와 매도 이후 별도 생산 관측 감사를 연결하라.

## 관련 파일/검증
- `RUN/hold_sell_audit_v1.py`
- `RUN/strategy_01_rotation_engine_v2.py`
- `RUN/verified_hold_sell_replay_v1.py`
- `python -m unittest tests.test_strategy_01_rotation_v2.Strategy01RotationV2Tests.test_post_exit_observation_capture_is_order_zero_and_hash_verified tests.test_verified_hold_sell_replay_v1 -v`

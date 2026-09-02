# 2026-08-27 저녁에 고친 실전 파일을 명부에 재봉인하지 않아, 다음날 아침 전 전략 엔진이 조용히 안 뜰 상태였다

## 접근법
1. 08:30 리허설 실패 플래그의 `S01:HASH_MISMATCH` 를 단서로 잡았다(추정하지 않고 단서로만 썼다).
2. 해시 장부 2종(`elevated_path_hashes.json` · `live_approved_hashes_v1.json`)을 실제 파일과
   **직접 대조**했다 — 장부 mtime 비교가 아니라 sha256 재계산.
3. 불일치 파일의 mtime 을 찍어 "전부 오늘 17:43~18:42 저녁 작업분"임을 확인했다(엉뚱한 변조 배제).
4. `strategy_all_auto_live_preflight_v1.py`(08:59 사전점검)를 grep 해 **해시 검사가 0건**임을 확인했다
   → 이 사고는 아침 로그에 경고를 남기지 않는다는 뜻.
5. 관문 `live_owner_approval_guard_v1.py` 를 4개 전략에 직접 실행해 **4/4 FAIL** 을 실측했다.
6. `strategy_all_live_gate_launcher_v1.py:81-88` 에서 `return 3` → `_engine_main()` 미도달을 읽고,
   S01·S02·S03 LIVE cmd 의 마지막 줄이 그 런처임을 확인해 "엔진 미기동"으로 확정했다.
7. 피해 범위를 갈랐다: 내일 재생 재료 `s01_entry_v3_exact_inputs_*.jsonl` 의 생성 주체를 grep 해
   **신호기(게이트 없음)** 임을 확인 → 재생 계획은 무사, 매매만 전멸.
8. 8/26 선례 `update_broker_s01_manifest_20260826.py` 를 그대로 본떠 CAS 재봉인 스크립트를 만들었다.

## 하지 않은 것 + 이유
- 08:30 리허설 FAIL 팝업을 근거로 "전략이 닫힌다"고 결론짓지 **않았다**. 이유: 8/17 정정대로 리허설은
  전략을 끄지 않는다(소비 코드 0건). 증상과 원인을 섞으면 엉뚱한 층을 고친다.
- 저녁에 준비돼 있던 `update_s01_v3_live_manifest_20260828.py` 를 쓰지 **않았다**. 이유: 그 스크립트는
  v3 LIVE 전환 전제 자가검사가 들어 있어 **활성화까지 바꾼다**. 지금 필요한 건 "코드 봉인"뿐이었다.
- 실전 cmd 의 env(`S01_ENTRY_V3_MODE=SHADOW` 등)를 건드리지 **않았다**. 이유: 승인 범위가 A안 2건이었고,
  활성화는 내일 재생 PASS 를 조건으로 한 별개 승인이다.
- pytest 전체를 돌리지 **않았다**. 이유: `RUN/backup/` 의 옛 사본들이 수집 오류를 내 기준선이 안 나온다.
  집중 테스트(`-k "strategy_01 or entry_policy"`)로 한정해 116/1 을 얻었다.
- 실패 1건을 "기존 실패"라고 추정하지 **않았다**. 이유: 공용 매도엔진·해당 테스트의 mtime 이 8/25 이고
  저녁 diff(94+/4-)에 hard_stop 줄이 0건임을 확인해 무관을 **실측**했다.

## 재사용 규칙
저녁에 실전 파일을 고쳤으면 그날 밤 안에 해시 장부 2종을 재봉인하라 —
아침 사전점검 로그는 이 사고를 경고하지 않고, 엔진만 조용히 안 뜬다.

## 관련 파일/커밋
- 원인: `RUN\strategy_01_rotation_engine_v2.py`(common 레코드) 18:34 수정 vs 명부 15:14
- 막는 곳: `RUN\strategy_all_live_gate_launcher_v1.py:81-88`
- 못 잡는 곳: `RUN\strategy_all_auto_live_preflight_v1.py` (해시 검사 0건)
- 수리: `RUN\update_s01_v3_wiring_manifest_20260827.py` (CAS 525ccf13→a2a461ef)
- 메모리: `stockbot-20260827-manifest-reseal-gate`

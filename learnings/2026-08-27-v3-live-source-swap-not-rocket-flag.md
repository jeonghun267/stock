# 2026-08-27 "v3 LIVE 전환에 S01_ROCKET_LIVE=YES가 필요하다"는 예상이 틀렸다 — 소스가 통째 교체된다

## 접근법
1. 지시서 문구(`set S01_ROCKET_LIVE=YES 줄 다음에 추가`)와 실제 cmd(`=NO`)의 불일치를 발견했다.
2. `S01_ROCKET_LIVE` 소비 지점을 grep → `rocket_live_enabled()` = env AND 명부 봉인.
3. 명부를 읽어 `live_features.S01_ROCKET = true` 확인 → 봉인은 이미 열려 있고 env 만 NO.
4. `promote_rocket_live()` docstring("other v3 lanes stay shadow")만 보고 "PULLBACK 이 안 산다"고
   결론낼 뻔했으나, **소비하는 쪽**을 마저 확인했다.
5. `strategy_01_signal_contract_v2.py:204-206` 에서 `ENTRY_V3_MODE == "LIVE"` 일 때
   `source_rows = payload["entry_v3_signals"]` 로 **소스가 통째 교체**됨을 확인 → 두 레인 모두 공급.
   `S01_ROCKET_LIVE` 는 레거시 `signals` 목록에 로켓을 끼워넣던 다리이고, 교체 후엔 소비되지 않는다.

## 하지 않은 것 + 이유
- 생산 함수의 docstring 만 보고 결론내지 **않았다**. 이유: 그 문장은 레거시 소비 시절 기준이었다.
  스위치의 의미는 **생산자가 아니라 소비자**를 읽어야 확정된다.
- 지시서대로 `S01_ROCKET_LIVE=YES` 를 켜라고 고치지 **않았다**. 이유: 켜도 소비되지 않아 무의미하고,
  실전 스위치를 근거 없이 늘리는 셈이 된다.
- cmd 를 지금 고치지 **않았다**. 이유: 활성화는 8/28 재생 PASS 조건부 승인 사항이다. 문서만 고쳤다.
- "추가"를 "교체"로 바꾸면서 재봉인 스크립트 전제검사(`b"set S01_ENTRY_V3_MODE=LIVE" in data`)가
  깨지는지 먼저 확인했다 — 교체로도 통과.

## 재사용 규칙
env 스위치가 실제로 무엇을 여는지 판단할 때는 그 스위치를 읽는 **생산 코드가 아니라,
결과를 소비하는 쪽**을 읽어라 — 소스 자체가 교체되면 생산 쪽 스위치는 죽은 다리가 된다.

## 관련 파일/커밋
- 근거: `RUN\strategy_01_signal_contract_v2.py:204-206` · `RUN\strategy_01_open_surge_signal_v2.py:1286-1310,1463-1470`
- 수정: `보고서\지시서_S01_v3실전연결_20260828.md` 2절 (백업 `RUN\backup\*_before_anchor_fix.md`)

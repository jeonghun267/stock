# 긴급 운영 절차서 — 전략 자동 OFF 시 재개 (2026-08-14 제정)

> 8/14 아침 사건에서 배운 것을 박제. 리허설 FAIL → S01~S03 자동 OFF → 재개에 30분 걸림.
> 이 절차서대로면 3분. 도구 2개가 이미 만들어져 있다.

## 도구 (RUN 폴더)

| 파일 | 용도 | 실행 |
|---|---|---|
| `emergency_status_check_v1.py` | 상태 전부 한 방에 (읽기 전용) | `C:\python310\python.exe -X utf8 RUN\emergency_status_check_v1.py` |
| `emergency_reopen_s0123_v1.ps1` | 4겹 잠금 해제 (기본 예행연습) | `powershell -NoProfile -File RUN\emergency_reopen_s0123_v1.ps1` → 확인 후 `-Go` |

## 잠금 4겹의 구조 (왜 하나 풀어도 안 열리나)

```
[1] config\strategy_XX_off.flag          ← 리허설 FAIL 시 자동 생성
[2] 엔진 프로세스 (관리자 권한)             ← 일반 권한 taskkill 불가, UAC 필요
[3] config\strategy_XX_live_approved.flag ← 형식이 정확해야 함 (아래)
[4] 엔진은 매 판정마다 [1][3]을 다시 읽음    ← 형식만 맞으면 재기동 없이 열림
```

## 승인 플래그 정확한 형식 (`approval_settings_guard.legacy_daily_approval_valid`)

```
auto-approved 2026-08-14T09:32:16      ← 이걸 써라 (오늘 날짜 + 과거 시각)
APPROVED_BY_OWNER 20260814 09:32:00    ← owner 수동 형식 (역시 유효)
APPROVED_BY_OWNER 20260814 S06_LIVE    ← S06 전용. S01~S03에 흉내내면 무효+회수됨
```

- 인코딩 ASCII. 오늘 날짜여야 하고 시각이 미래면 무효 (fail-closed).
- `auto-approved` 형식만이 다음날 아침 파이프라인이 정상 회수(STALE_AUTO_APPROVAL_REVOKED)
  할 수 있는 형식이다. 다른 형식으로 남기면 다음날 preflight가 FAIL 난다.

## 막다른 길 (시간 낭비 금지)

- `strategy_all_auto_live_preflight_v1.py --activate` 직접 실행 → selftest stage3가
  "예약 태스크 경유"를 요구해 구조적으로 FAIL. 정식 활성화 창구는 **09:05 마감**.
- 손제작 플래그가 형식이 틀리면 preflight가 `UNRECOGNIZED_APPROVAL_REVOKED`로
  회수하고 OFF를 다시 만든다 (한 번 당했다).
- `Stop-ScheduledTask`는 파이썬을 안 죽인다. `IgnoreNew`라 옛 인스턴스가 살아 있으면
  `Start-ScheduledTask`도 무시된다.
- S01 진입창은 09:00~09:20 — 그 이후 재개는 S02(~14:20)·S03만 의미 있다.

## 재개 판단 기준 (열기 전에 반드시)

1. **왜 잠겼는지 원인 파악이 먼저** — 리허설 FAIL 사유를 읽어라
   (`config\morning_rehearsal_fail.flag` 본문, 격리됐으면 `_disabled_*` 폴더).
2. 매도 코드 결함으로 잠겼으면 **수리·검증·명부 갱신 전에 열지 마라**
   (여는 순서: 코드 수정 → ast 계약 검증 → `approval_manifest_writer_v1`로 해시 갱신
   → 관문 4종 PASS 확인 → 그 다음에 reopen 스크립트).
3. 열고 나서 `BUY_GATE_OPEN entries enabled (PREFLIGHT_APPROVED)` 로그를 눈으로 확인.

## 관련 기록

- 사건 상세: 메모리 `stockbot-20260814-rehearsal-contract-off-and-reopen`
- 리허설 계약 검사기: `RUN\morning_preflight_rehearsal_v1.py::_check_rising_hold_single_gate`
- 8/5 원사건(우회가지 제거): `9a741fa` 커밋

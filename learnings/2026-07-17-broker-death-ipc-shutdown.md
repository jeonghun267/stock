# [2026-07-17] 브로커 "9시대 5회 사망" 원인 규명 — 크래시가 아니라 전부 IPC 정지명령이었다 + 재부팅 복구 사각(파이프라인 미기동) 발견

## 접근법
1. 워치독 로그(watchdog_broker_20260717.log)에서 사망 시각 5개(09:12·09:15·09:31·09:53·~10:35)를 먼저 확정했다.
2. 윈도우 이벤트 로그(Application Error)를 조회해 python.exe 크래시 이벤트가 **0건**임을 확인했다 — "OCX 크래시" 가설이 여기서 흔들렸다.
3. broker_journal.log에서 각 재로그인(OnEventConnect err_code=0)의 줄 번호를 찾고, 그 **직전 세션의 마지막 줄들**을 읽었다.
4. 다섯 번 모두 죽기 직전에 `IPC shutdown command received` → `CONNECTED → SHUTDOWN` → atexit 정상 종료 기록을 발견했다 — 사망이 아니라 정지명령 수신.
5. 같은 시간대에 진행된 ASTx 제거 작전(메모리 토픽 기록)과 대조해 "제거 시도 → 브로커 정지 → 워치독이 60초 내 부활 → 다시 정지"의 싸움이었다고 결론냈다.
6. 복구 검증: sell_liveness_guard가 10:15부터 CRITICAL(기존보유 5종목 매도 무방비)임을 발견 → SAFEPLUS_PIPELINE_0900 태스크 수동 기동 → 11:15 경보 해제를 외부 증거(로그+깃발 삭제)로 확인했다.

## 하지 않은 것 + 이유
- 브로커 코드(OCX 콜백·예외 처리) 디버깅은 하지 않음. 이유: 코드를 보기 전에 "죽은 순간의 로그"부터 봤고, 거기서 크래시가 아님이 3분 만에 판명됐다. 코드부터 팠으면 몇 시간을 버렸을 것.
- 워치독의 "broker DEAD detected" 메시지를 사망 증거로 믿지 않음. 이유: 워치독은 하트비트 부재만 보고 "죽음"이라 부른다 — 정상 종료·강제 종료·크래시를 구분 못 한다. 구분은 broker_journal의 마지막 줄만 할 수 있다.
- 파이프라인 복구 때 pipeline_runner를 env 없이 직접 실행하지 않음. 이유: 부팅 스크립트(run_safeplus_pipeline_0900.ps1)가 KIWOOM_ACCOUNT 등 env를 주입한다(7/6 계좌파싱 사고 전례). 대신 태스크 통째 실행이 안전한지 브로커 싱글턴 락 코드(sys.exit(1) 위치)를 먼저 읽고 확인했다.

## 재사용 규칙
브로커(장수명 프로세스)가 "죽었다"고 보고되면, 워치독/감시자 로그가 아니라 **그 프로세스 자신의 일지에서 죽기 직전 줄**을 먼저 읽어라 — IPC shutdown/atexit 기록이 있으면 사람이 끈 것이다. 그리고 장중 PC 재시작 복구는 SAFEPLUS_WATCHDOG_BROKER + SAFEPLUS_PIPELINE_0900 **둘 다** 기동하라(매도엔진은 파이프라인 소속).

## 관련 파일/커밋
- C:\stock_bot\LOG\watchdog_broker_20260717.log (사망 시각 5개)
- C:\stock_bot\LOG\broker_journal.log 줄 47792·48214·49894·52228·55864 부근 (IPC shutdown 증거)
- C:\stock_bot\RUN\run_safeplus_pipeline_0900.ps1 (표준 부팅 경로·env 주입)
- C:\stock_bot\data\LOG\sell_liveness_guard.log (10:15 CRITICAL → 11:15 해제)
- 메모리 토픽: stockbot-20260717-astx-kiwoom-login-block

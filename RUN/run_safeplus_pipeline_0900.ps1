# run_safeplus_pipeline_0900.ps1
# Task Scheduler SAFEPLUS_PIPELINE_0900 트리거 (매일 09:00)
# 역할: START_SAFEPLUS_AUTO.bat과 동일하게 3개 데몬 + 1분봉 워치독 자동 기동

# [SELF-HIDE 2026-06-12 ★친구님 지시 "파란 창 안 보이게"] 시작 직후 자기 창 숨김.
#   기능 무영향(작업은 그대로, 화면만 숨김). 되돌리기: 이 블록 삭제 또는 .bak_pre_selfhide_20260612 복원.
try {
    $sig = '[DllImport("kernel32.dll")] public static extern System.IntPtr GetConsoleWindow(); [DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);'
    $cw = Add-Type -MemberDefinition $sig -Name ConsoleHider -Namespace SafePlus -PassThru
    [void]$cw::ShowWindow($cw::GetConsoleWindow(), 0)
} catch { }

$env:REAL_TEST_MODE     = "true"
# [CAP2M 2026-05-12] 1000000→2000000. 운영 철학 전환: 대장 집중 + ADD_ON 증폭 구조 정렬.
#   100만에서 60:40 풀투입 시 available_krw=0 → ADD_ON 0원 결함 회피.
#   ENTRY_WEIGHTS [0.50, 0.25] (신규 75%) + reserve 25% → ADD_ON 자본 보존.
# [CAP1M 이력 2026-05-11] 2000000→1000000 (GPT 단계적 축소). 현재 2단계 확대 적용.
$env:REAL_TEST_CAPITAL  = "2000000"
$env:SAFEPLUS_CAPITAL   = "2000000"
# [R15 2026-05-14] buy_sender CommConnect timeout 20s → 60s 연장.
#   5/14 12:09 OCX LOGIN race 차단 패턴 회피 (broker peak load + AUTO 미설정 + 사용자 popup 클릭 여유).
#   broker N23 90s 와 정합. coden 무접촉, env 1줄.
$env:CONNECT_TIMEOUT_SEC = "60"

# [ACCT-FIX 2026-05-22] KIWOOM_ACCOUNT 환경변수 정정.
#   시스템 User scope 값은 오타(끝자리 01) → 오타 계좌 사용 시 ERROR -202 (OP_ERR_TRSEND).
#   13:48 broker IPC OPW00018 검증 (영웅문 값 일치).
#   buy_sender L4756 _env("KIWOOM_ACCOUNT") → BALANCE_TR input["계좌번호"] 사용.
#   시스템 환경변수 미변경 (영구 영향 회피), boot script에서 로드.
# [SECRETS 2026-07-24] 계좌번호 하드코딩 제거(git 업로드 대비) — config\secrets.ps1(비추적)에서 로드.
if (Test-Path "C:\stock_bot\config\secrets.ps1") {
    . "C:\stock_bot\config\secrets.ps1"
}
if (-not $env:KIWOOM_ACCOUNT) {
    Write-Warning "[SECRETS] config\secrets.ps1 로드 실패 — KIWOOM_ACCOUNT 미설정 (주문계통 -202 위험)"
}

# [SIGA-DISABLE 2026-05-27] 시가 매수 chain 비활성화 (종가 매수 chain 전환)
#   사유: 4-5월 데이터 분석 결과 종가 매수 EV +1.54% / 승률 62% / +5% 갭 14.3% 우위
#   siga_to_signal_bridge.py L60+ env 가드: SIGA_ENTRY_DISABLED=YES 시 즉시 HOLD
#   활성화 복원: 본 줄 제거 또는 env 값 변경
$env:SIGA_ENTRY_DISABLED = "YES"

# [RELAY-OPT 2026-05-25] RELAY 윈도우 09:25~09:30 정량 최적화
#   1분봉 백테 시뮬 (1ST 68건, 진입 09:07~09:15 × 청산 09:18~09:50):
#     - 09:18 청산: 평균 +0.49% (현 수정 2)
#     - 09:25 청산: 평균 +1.30% (10분 보유 보장)
#     - 09:30 청산: 평균 +3.70% (최고, 15~23분 보유)
#     - 평균 PnL = +4.66% (수수료 차감 후 +4.22%) — 현 수정 2의 9.5배
#   사용자 우려 "5분 보유 너무 짧음" 정확 검증: 5/8/10분 보유는 수수료 차감 후 적자
#   eo 13분 이상이 첫 양수 전환점. 09:25 시작 = 09:15 진입 시 최소 10분 보장
#   코드 흔적 09:18(siga_selection L19)은 2주 전 가설, 1분봉 실측이 진짜 정답
$env:RELAY_WINDOW_START = "925"
$env:RELAY_WINDOW_END   = "930"

$PY  = "C:\Python310-32\python.exe"
$RUN = "C:\stock_bot\RUN"
Set-Location $RUN

$logDir = "C:\stock_bot\DATA\LOG"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$bootLog = Join-Path $logDir ("pipeline_boot_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PIPELINE_0900 boot start" | Add-Content $bootLog

# [CACHE-WARM 2026-06-29 친구님] 일봉MA·시장레짐·정배열맵 캐시를 장 시작 전 미리 생성.
#   사유: 세 모듈(daily_ma/market_regime/trend_filter)이 255MB eod CSV를 lazy build → 캐시 파일명이 날짜별이라
#         매일 새로 빌드해야 함. 미리 안 데우면 09:00 개장때 각 실행기 첫 호출이 동시에 빌드 → IO/CPU 스파이크.
#   ★비차단(백그라운드 1프로세스에서 순차 실행=동시 255MB 읽기 회피)·broker 부팅 안 막음.
#   실패해도 무해: 실행기가 lazy build로 자동 폴백(기존 동작). 되돌리기: 이 블록 삭제.
$warmLog = Join-Path $logDir ("cache_warm_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
$warmCmd = "& '$PY' -X utf8 '$RUN\daily_ma.py' *> '$warmLog'; " +
           "& '$PY' -X utf8 '$RUN\market_regime.py' *>> '$warmLog'; " +
           "& '$PY' -X utf8 '$RUN\trend_filter.py' *>> '$warmLog'"
Start-Process -WindowStyle Hidden -FilePath "powershell.exe" -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-Command",$warmCmd
"[$(Get-Date -Format 'HH:mm:ss')] cache_warm (daily_ma/market_regime/trend_filter) launched (background)" | Add-Content $bootLog

# 0) [P4-BROKER-BOOT 2026-05-14] Broker Gateway v1 최우선 부팅
# broker_heartbeat.json 항상 fresh 유지 → SIGA sell STATE/ACCOUNT_INFO IPC 가용성 보장.
# S1 패치(24번째) 이후 collector opt10080/10059 routing은 broker 무시(direct OCX), broker 가동은
# rt_sell/buy_sender 의 STATE 조회 + SHADOW order mirror 보존 목적.
$broker = "$RUN\broker_gateway_v1.py"
# [DUP-BOOT-FIX 2026-07-29 owner approved] Skip boot when the broker is already alive.
#   7/28 08:40:02 this boot hit the singleton lock and self-terminated, but it froze the
#   running broker (PID 12564) for 37s -> watchdog false DEAD -> lock wiped -> 2 brokers
#   -> preflight BROKER_HOLDINGS 12s timeout -> S01/S03 entry window lost (2 days running).
#   Watchdog (08:35) already boots the broker, so this block is redundant, not primary.
#   Rollback: restore run_safeplus_pipeline_0900.ps1.bak_20260729_dupboot
$brokerAlive = $false
$brokerPid = 0
try {
    $brokerPid = [int](((Get-Content "C:\stock_bot\DATA\broker_gateway.lock" -ErrorAction Stop) -join '').Trim())
    # [PID-REUSE-GUARD 2026-07-29 owner approved] Verify the PID really belongs to python.
    #   The lock file survives taskkill/crash (atexit never runs), so a stale PID can be
    #   reassigned to an unrelated process -> "broker alive" false positive -> boot skipped
    #   -> market opens with no broker. Checking the process name closes that hole.
    #   Failing this check falls through to the heartbeat test below, exactly as before.
    #   Rollback: run_safeplus_pipeline_0900.ps1.bak_20260729_pidguard
    if ($brokerPid -gt 0) {
        $brokerProc = Get-Process -Id $brokerPid -ErrorAction SilentlyContinue
        if ($brokerProc -and ($brokerProc.ProcessName -like 'python*')) { $brokerAlive = $true }
    }
} catch { }
if (-not $brokerAlive) {
    try {
        $hbItem = Get-Item "C:\stock_bot\IPC\broker_heartbeat.json" -ErrorAction Stop
        if (((Get-Date) - $hbItem.LastWriteTime).TotalSeconds -lt 60) { $brokerAlive = $true }
    } catch { }
}
if ($brokerAlive) {
    "[$(Get-Date -Format 'HH:mm:ss')] broker_gateway_v1 already alive (PID=$brokerPid) - boot skipped" | Add-Content $bootLog
} elseif (Test-Path $broker) {
    $env:REAL_MICRO = "ON"   # [REAL-MICRO 2026-06-24] 실시간 체결강도(228)/호가(121·125) 구독 강제
    Start-Process -WindowStyle Normal -FilePath $PY -ArgumentList "-X","utf8",$broker
    "[$(Get-Date -Format 'HH:mm:ss')] broker_gateway_v1 started" | Add-Content $bootLog
    # broker LOGIN + heartbeat 초기화 60s warmup
    [System.Threading.Thread]::Sleep(60000)
    "[$(Get-Date -Format 'HH:mm:ss')] broker_gateway_v1 warmup wait done" | Add-Content $bootLog
}

# 1) 투자자 일별 수집 (CORE)
$invest = "C:\stock_bot\CORE\COLLECT\collect_investor_daily_opt10059_v1_SAFEPLUS_FINAL.py"
if (Test-Path $invest) {
    Start-Process -WindowStyle Minimized -FilePath $PY -ArgumentList "-X","utf8",$invest
    "[$(Get-Date -Format 'HH:mm:ss')] investor_daily started" | Add-Content $bootLog
    # [OCX-BOOT-FIX 2026-05-07] OCX 로그인창 동시 표출 방지 — investor_daily 로그인/초기화 완료 대기
    # [SLEEP-FIX 2026-05-08] Start-Sleep 5/8 실측 0초 미작동 → Thread.Sleep 직접 호출 (.NET API)
    # [PRE-BOOT 2026-05-08] 60s → 120s (08:40 사전 부팅 cascade에 맞춰 2분 간격)
    [System.Threading.Thread]::Sleep(120000)
    "[$(Get-Date -Format 'HH:mm:ss')] investor_daily warmup wait done" | Add-Content $bootLog
}

# 2) 메인 매매 데몬 [STDOUT-REDIRECT 2026-05-27] Hidden + stdout/stderr 파일 기록 (디버그용)
#    사유: 5/27 추적 결과 STEP 7 BUY ORDER 호출 후 buy_sender silent fail 의심 → 콘솔 stdout 파일 보존 필요
$pr_today = Get-Date -Format 'yyyyMMdd'
$pr_out = Join-Path "C:\stock_bot\data\LOG" "pipeline_runner_stdout_$pr_today.log"
$pr_err = Join-Path "C:\stock_bot\data\LOG" "pipeline_runner_stderr_$pr_today.log"
Start-Process -WindowStyle Hidden -FilePath $PY -ArgumentList "-X","utf8","$RUN\pipeline_runner.py" -RedirectStandardOutput $pr_out -RedirectStandardError $pr_err
"[$(Get-Date -Format 'HH:mm:ss')] pipeline_runner started" | Add-Content $bootLog
# [OCX-BOOT-FIX-2 2026-05-07] pipeline_runner의 SIGA step(siga_sell_strategy)과 collect_prices_1m가
#   거의 동시 OCX 로그인 시도 → 키움 로그인창 동시 표출 위험. investor_daily 후와 동일 간격.
# [SLEEP-FIX 2026-05-08] Start-Sleep → Thread.Sleep로 통일 / [PRE-BOOT 2026-05-08] 60s → 120s
[System.Threading.Thread]::Sleep(120000)
"[$(Get-Date -Format 'HH:mm:ss')] pipeline_runner warmup wait done" | Add-Content $bootLog

# 3) 1분봉 수집기 (rt_sell_engine 내장 호출) [VIEWFIX 2026-05-06] Minimized→Normal
Start-Process -WindowStyle Normal -FilePath $PY -ArgumentList "-X","utf8","$RUN\collect_prices_1m_kiwoom_opt10080_v4_16.py"
"[$(Get-Date -Format 'HH:mm:ss')] collect_prices_1m started" | Add-Content $bootLog

# 4) [WD-TASK-D 2026-05-07] watchdog_collect_1m → Task Scheduler 'SAFEPLUS_WATCHDOG_COLLECT_1M' 분리
#    이전: Start-Process spawn (부모 종료 동기 + UTF-8 BOM 누락으로 즉시 종료, 5/1 이후 0회 작동)
#    등록 스크립트: C:\stock_bot\RUN\register_watchdog_collect_1m_task.ps1 (매일 08:59 자동 기동)

# 5) 메인 파이프라인 워치독 (pipeline_runner 죽으면 자동 재시작)
Start-Process -WindowStyle Minimized -FilePath "powershell.exe" -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","$RUN\run_pipeline_watchdog.ps1"
"[$(Get-Date -Format 'HH:mm:ss')] pipeline_watchdog started" | Add-Content $bootLog

"[$(Get-Date -Format 'HH:mm:ss')] PIPELINE_0900 boot complete" | Add-Content $bootLog

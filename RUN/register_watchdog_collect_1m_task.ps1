# register_watchdog_collect_1m_task.ps1
# ════════════════════════════════════════════════════════════════════════
#  목적: watchdog_collect_1m_v6_4.ps1을 Task Scheduler 작업으로 등록
#  배경: 기존 부팅 스크립트(run_safeplus_pipeline_0900.ps1)의 Start-Process로
#        띄운 워치독이 부모 프로세스 종료와 함께 즉시 죽는 패턴 발견
#        (2026-05-07 진단: 5/1 이후 watchdog 0회 정상 동작 확정)
#
#  트리거: 매일 08:50 — 사전기동창(08:45~08:54) 안에서 워치독이 collect_prices_1m
#         사전 spawn → 09:00 부팅 스크립트의 OCX 로그인창과 시간차 분산.
#         부팅 스크립트의 Start-Process는 이중 기동 가드(line 688-694)에 자동 차단됨
#
#  사용법: 1회만 실행 (재실행은 동일 작업 갱신, 멱등)
#         powershell -NoProfile -ExecutionPolicy Bypass -File register_watchdog_collect_1m_task.ps1
#
#  권한: 현재 사용자(LogonType Interactive, RunLevel Limited) — 관리자 불필요
# ════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

$taskName = "SAFEPLUS_WATCHDOG_COLLECT_1M"
$psPath   = "powershell.exe"
$wdScript = "C:\stock_bot\RUN\watchdog_collect_1m_v6_4.ps1"

# ── 사전 검증 ──────────────────────────────────────────────────────────
if (-not (Test-Path $wdScript)) {
    Write-Error "watchdog 스크립트 없음: $wdScript"
    exit 1
}

# ── 기존 작업 제거 (재실행 = 갱신) ─────────────────────────────────────
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] 기존 작업 제거 후 재등록: $taskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# ── Action: PowerShell로 watchdog 실행 ─────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute $psPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wdScript`"" `
    -WorkingDirectory "C:\stock_bot\RUN"

# ── Trigger: 매일 08:50 (사전기동창 08:45~08:54 안에서 collect_prices_1m spawn) ──
# [TRIG-FIX 2026-05-07] 08:59 → 08:50 변경 이유:
#   워치독은 자체 OCX 미사용이지만 spawn하는 collect_prices_1m이 OCX 로그인 popup 띄움.
#   08:59 트리거 시 사전기동창(08:45~08:54) 이미 종료 → 09:00 장 시작 직후 spawn.
#   부팅 스크립트의 investor_daily(09:00)와 OCX popup 동시 표출 위험.
#   08:50로 당기면 사전기동창 안에 들어가 미리 spawn → popup 시간차 분산.
$trigger = New-ScheduledTaskTrigger -Daily -At 8:50AM

# ── Settings: 이중 기동 방지 + 실패 시 자동 재시작 + 강제 종료 차단 ────
# [FIX-D 2026-05-07] 최초 등록 후 30초 내 0xC000013A(STATUS_CONTROL_C_EXIT) 종료 발견:
#   - ExecutionTimeLimit (New-TimeSpan -Hours 0) → XML PT0S로 직렬화
#     일부 Windows에서 PT0S를 "즉시 종료"로 해석 → 30초 후 Ctrl+C signal 전송
#   - AllowHardTerminate=True (기본값) → Task Scheduler가 grace 종료 후 force-kill
#     finally 블록 실행 못 하고 강제 종료
# 해결:
#   - ExecutionTimeLimit (New-TimeSpan -Days 365) → P365D, 사실상 무제한 (1년)
#   - -DisallowHardTerminate 추가 → force-kill 차단, finally 블록 정상 실행 보장
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -DisallowHardTerminate `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

# ── Principal: 현재 사용자 (Interactive, 관리자 불필요) ────────────────
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# ── 등록 ───────────────────────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "SAFEPLUS collector_1m watchdog (옵션 D — 부팅 스크립트 독립 실행 / 2026-05-07 등록)" | Out-Null

# ── 검증 출력 ──────────────────────────────────────────────────────────
$task = Get-ScheduledTask -TaskName $taskName
Write-Host ""
Write-Host "════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "[OK] 작업 등록 완료: $taskName" -ForegroundColor Green
Write-Host "════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Action:    $psPath -NoProfile -ExecutionPolicy Bypass -File $wdScript"
Write-Host "  Trigger:   매일 08:50 (사전기동창 안에서 미리 spawn)"
Write-Host "  Policy:    이미 실행 중이면 무시 / 실패 시 1분 후 재시작 (최대 3회)"
Write-Host "  TimeLimit: 365일 (사실상 무제한 — 일별 트리거로 매일 갱신됨)"
Write-Host "  HardKill:  Disabled (graceful exit 보장 — finally 블록 정상 실행)"
Write-Host "  Principal: $env:USERDOMAIN\$env:USERNAME (Interactive, Limited)"
Write-Host "  State:     $($task.State)"
Write-Host ""
Write-Host "[다음 단계 — 사용자 권장 검증]" -ForegroundColor Cyan
Write-Host "  1) 즉시 1회 실행 테스트:"
Write-Host "     Start-ScheduledTask -TaskName $taskName"
Write-Host "  2) 30초 대기 후 로그 확인:"
Write-Host "     Get-Content C:\stock_bot\LOG\watchdog_collect_1m_$(Get-Date -Format 'yyyyMMdd').log -Tail 20"
Write-Host "  3) 정지하려면:"
Write-Host "     Stop-ScheduledTask -TaskName $taskName"
Write-Host "  4) 작업 제거하려면:"
Write-Host "     Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"

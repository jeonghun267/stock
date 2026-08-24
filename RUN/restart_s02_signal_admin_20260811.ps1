$ErrorActionPreference = "Stop"
$signalPid = 12632
$expectedStart = "2026-08-11 08:59:47"
$orderLock = "C:\stock_bot\DATA\strategy_02_rotation_v1.lock"
$statusPath = "C:\stock_bot\RUN\s02_signal_admin_restart_status.json"
$taskName = "SAFEPLUS_STRATEGY02_SIGNAL"

$status = [ordered]@{
    started_at = (Get-Date).ToString("s")
    old_signal_pid = $signalPid
    order_engine_pid = ""
    stopped = $false
    task_started = $false
    new_signal_pid = 0
    shadow_field_live = $false
    error = ""
}

try {
    $status.order_engine_pid = (Get-Content -LiteralPath $orderLock -Raw).Trim()
    if ($status.order_engine_pid -eq [string]$signalPid) {
        throw "Safety abort: target PID is the order engine"
    }
    $process = Get-Process -Id $signalPid -ErrorAction Stop
    if ($process.ProcessName -ne "python") {
        throw "Safety abort: target is not python"
    }
    if ($process.StartTime.ToString("yyyy-MM-dd HH:mm:ss") -ne $expectedStart) {
        throw "Safety abort: target start time changed"
    }

    Stop-Process -Id $signalPid -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 500
    if (Get-Process -Id $signalPid -ErrorAction SilentlyContinue) {
        throw "Old signal process is still running"
    }
    $status.stopped = $true

    schtasks.exe /Run /TN $taskName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Scheduled task start failed: $LASTEXITCODE"
    }
    $status.task_started = $true

    Start-Sleep -Seconds 4
    $newProcess = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match 'strategy_02_low_buy_signal_v1\.py'
    } | Sort-Object CreationDate -Descending | Select-Object -First 1
    if ($newProcess) {
        $status.new_signal_pid = [int]$newProcess.ProcessId
    }
    $livePath = "C:\stock_bot\DATA\strategy_02_low_buy_signal_v1.json"
    $status.shadow_field_live = [bool](
        Select-String -LiteralPath $livePath -SimpleMatch '"flow_book_shadow_candidates"' -Quiet
    )
} catch {
    $status.error = $_.Exception.Message
} finally {
    $status.finished_at = (Get-Date).ToString("s")
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

if ($status.error) { exit 1 }
exit 0

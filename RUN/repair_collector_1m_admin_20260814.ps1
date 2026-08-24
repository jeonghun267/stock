$ErrorActionPreference = "Stop"

$resultPath = "C:\stock_bot\data\repair_collector_1m_admin_20260814.json"
$oldPid = 15020
$lockPath = "C:\stock_bot\data\collector_1m.lock"
$pidPath = "C:\stock_bot\data\collector_1m.pid"
$collector = "C:\stock_bot\RUN\collect_prices_1m_kiwoom_opt10080_v4_16.py"
$python32 = "C:\Python310-32\python.exe"

try {
    & "C:\stock_bot\RUN\register_watchdog_collect_1m_task.ps1"
    $task = Get-ScheduledTask -TaskName "SAFEPLUS_WATCHDOG_COLLECT_1M"
    if ($task.Principal.RunLevel -ne "Highest") {
        throw "watchdog task RunLevel is not Highest"
    }

    $old = Get-Process -Id $oldPid -ErrorAction Stop
    if ($old.ProcessName -notlike "python*") {
        throw "PID $oldPid is not a Python process"
    }
    Stop-Process -Id $oldPid -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Process -Id $oldPid -ErrorAction SilentlyContinue) -and
           ((Get-Date) -lt $deadline)) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        throw "collector PID $oldPid did not exit"
    }

    if (Test-Path -LiteralPath $lockPath) {
        $lockPid = (Get-Content -LiteralPath $lockPath -Raw).Trim()
        if ($lockPid -eq [string]$oldPid) {
            Remove-Item -LiteralPath $lockPath -Force
        } else {
            throw "collector lock changed unexpectedly: $lockPid"
        }
    }
    if (Test-Path -LiteralPath $pidPath) {
        Remove-Item -LiteralPath $pidPath -Force
    }

    $new = Start-Process -FilePath $python32 `
        -ArgumentList "`"$collector`"" `
        -WorkingDirectory "C:\stock_bot\RUN" `
        -WindowStyle Hidden `
        -PassThru
    $new.Id | Set-Content -LiteralPath $pidPath -Encoding UTF8
    Start-Sleep -Seconds 3
    if (-not (Get-Process -Id $new.Id -ErrorAction SilentlyContinue)) {
        throw "new collector exited immediately: PID $($new.Id)"
    }

    [ordered]@{
        status = "PASS"
        completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        watchdog_run_level = [string]$task.Principal.RunLevel
        old_pid = $oldPid
        new_pid = $new.Id
    } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    [ordered]@{
        status = "FAIL"
        completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        error = [string]$_
    } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}

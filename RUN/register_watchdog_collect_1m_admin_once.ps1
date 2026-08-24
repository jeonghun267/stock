$ErrorActionPreference = "Stop"
$resultPath = "C:\stock_bot\data\register_watchdog_collect_1m_admin_once.json"

try {
    & "C:\stock_bot\RUN\register_watchdog_collect_1m_task.ps1"
    $task = Get-ScheduledTask -TaskName "SAFEPLUS_WATCHDOG_COLLECT_1M"
    if ($task.Principal.RunLevel -ne "Highest") {
        throw "watchdog task RunLevel is not Highest"
    }
    [ordered]@{
        status = "PASS"
        completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        run_level = [string]$task.Principal.RunLevel
    } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    [ordered]@{
        status = "FAIL"
        completed_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        error = [string]$_
    } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}

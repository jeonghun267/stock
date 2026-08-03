$ErrorActionPreference = 'Stop'
$prerequisites = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST',
    'SAFEPLUS_MICRO_RANK_SHADOW',
    'SAFEPLUS_MONEYFLOW_WATCH'
)
foreach ($name in $prerequisites) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        throw "Required task is missing: $name"
    }
    $task.Settings.StartWhenAvailable = $true
    Set-ScheduledTask -InputObject $task | Out-Null
}
$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')

$signalAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_SIGNAL.cmd'
$signalTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:20:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_SIGNAL' -Action $signalAction -Trigger $signalTrigger -Principal $principal -Settings $settings -Description '새전략 02 저점매수 매도소진 신호전용(주문 0)' -Force | Out-Null

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew
$liveAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd'
$liveTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:20:20')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_LIVE' -Action $liveAction -Trigger $liveTrigger -Principal $principal -Settings $settings -Description '새전략 02 독립매수·공통보유·공통매도(별도 승인 전 주문 0)' -Force | Out-Null

Get-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_SIGNAL','SAFEPLUS_STRATEGY02_LIVE' | Select-Object TaskName,State,@{n='Enabled';e={$_.Settings.Enabled}},@{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}
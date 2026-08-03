$ErrorActionPreference = 'Stop'
$prerequisites = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST',
    'SAFEPLUS_DEEP_SIGNAL_REC',
    'SAFEPLUS_KOSDAQ_IDX_REFRESH',
    'SAFEPLUS_PREFLIGHT_SELFTEST_HIGH',
    'SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED'
)
foreach ($name in $prerequisites) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        throw "Required task is missing: $name"
    }
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')

$signalAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY04_SIGNAL.cmd'
$signalTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'08:58:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY04_SIGNAL' -Action $signalAction -Trigger $signalTrigger -Principal $principal -Settings $settings -Description 'Strategy 04 pullback signal only; order capability zero' -Force | Out-Null

$preflightAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY04_PREFLIGHT.cmd'
$preflightTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:57:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY04_PREFLIGHT' -Action $preflightAction -Trigger $preflightTrigger -Principal $principal -Settings $settings -Description 'Strategy 04 read-only live preflight; never approves orders' -Force | Out-Null

$liveAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY04_LIVE.cmd'
$liveTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:58:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY04_LIVE' -Action $liveAction -Trigger $liveTrigger -Principal $principal -Settings $settings -Description 'Strategy 04 shared rotation; waits for explicit same-day owner approval' -Force | Out-Null

Get-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY04_SIGNAL','SAFEPLUS_STRATEGY04_PREFLIGHT','SAFEPLUS_STRATEGY04_LIVE' |
    Select-Object TaskName,State,@{n='Enabled';e={$_.Settings.Enabled}},@{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}

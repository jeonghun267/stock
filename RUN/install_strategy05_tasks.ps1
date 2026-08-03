$ErrorActionPreference = 'Stop'
$prerequisites = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST'
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

$signalAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY05_SIGNAL.cmd'
$signalTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'08:55:30')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY05_SIGNAL' -Action $signalAction -Trigger $signalTrigger -Principal $principal -Settings $settings -Description 'Strategy 05 base-breakout signal/watch only; order capability zero' -Force | Out-Null

$liveAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY05_LIVE.cmd'
$liveTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:25:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY05_LIVE' -Action $liveAction -Trigger $liveTrigger -Principal $principal -Settings $settings -Description 'Strategy 05 shared rotation; blocked by OFF and same-day approval gates' -Force | Out-Null

Get-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY05_SIGNAL','SAFEPLUS_STRATEGY05_LIVE' |
    Select-Object TaskName,State,@{n='Enabled';e={$_.Settings.Enabled}},@{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}

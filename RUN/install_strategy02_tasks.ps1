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
$signalTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:00:00')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_SIGNAL' -Action $signalAction -Trigger $signalTrigger -Principal $principal -Settings $settings -Description 'S02 low-buy sell-exhaustion: signal only (no orders)' -Force | Out-Null

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew
$liveAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd'
$liveTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]'09:00:20')
Register-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_LIVE' -Action $liveAction -Trigger $liveTrigger -Principal $principal -Settings $settings -Description 'S02 independent buy + common hold/sell (no orders until separately approved)' -Force | Out-Null

Get-ScheduledTask -TaskName 'SAFEPLUS_STRATEGY02_SIGNAL','SAFEPLUS_STRATEGY02_LIVE' | Select-Object TaskName,State,@{n='Enabled';e={$_.Settings.Enabled}},@{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}

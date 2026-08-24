$ErrorActionPreference = 'Stop'

$taskName = 'SAFEPLUS_REGIME_EXCEPTION_SHADOW'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_REGIME_EXCEPTION_SHADOW.cmd'
$trigger = New-ScheduledTaskTrigger `
    -Weekly -WeeksInterval 1 `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At ([datetime]'08:59:00')
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description 'Persistent S01/S02/S03 crash-regime recorder; SHADOW_ORDER_ZERO; no broker/order path' | Out-Null

Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State,
    @{n='Enabled';e={$_.Settings.Enabled}},
    @{n='StartBoundary';e={$_.Triggers[0].StartBoundary}},
    @{n='RunLevel';e={$_.Principal.RunLevel}}

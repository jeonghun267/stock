$ErrorActionPreference = 'Stop'

$taskName = 'SAFEPLUS_HIGH_RANGE_PAPER_LEDGER'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_HIGH_RANGE_PAPER_LEDGER.cmd'
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
    -Description 'S01-S06 high-range virtual entry/exit ledger; SHADOW_ORDER_ZERO; no broker/order path' | Out-Null

Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State,
    @{n='Enabled';e={$_.Settings.Enabled}},
    @{n='StartBoundary';e={$_.Triggers[0].StartBoundary}},
    @{n='RunLevel';e={$_.Principal.RunLevel}}

$ErrorActionPreference = 'Stop'

$backupDir = 'C:\stock_bot\DOCS\task_backup_20260726_strategy01'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

function Backup-TaskXml {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return
    }
    $safeName = $TaskName -replace '[^\w.-]', '_'
    Export-ScheduledTask -TaskName $TaskName |
        Set-Content -LiteralPath (Join-Path $backupDir "$safeName.xml") -Encoding Unicode
}

function Enable-MissedStart {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        throw "Required task is missing: $TaskName"
    }
    Backup-TaskXml $TaskName
    $task.Settings.StartWhenAvailable = $true
    Set-ScheduledTask -InputObject $task | Out-Null
}

$prerequisites = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST',
    'SAFEPLUS_MICRO_RANK_SHADOW',
    'SAFEPLUS_MONEYFLOW_WATCH'
)
foreach ($name in $prerequisites) {
    Enable-MissedStart $name
}

$retiredTasks = @(
    'SAFEPLUS_CAPTAIN2_BROADCAST',
    'SAFEPLUS_CAPTAIN2_C2_01_SHADOW',
    'SAFEPLUS_CAPTAIN2_EVENING_REPORT',
    'SAFEPLUS_CAPTAIN2_MORNING_CHECK',
    'SAFEPLUS_CAPTAIN2_SHADOW',
    'SAFEPLUS_CAPTAIN2_VERIFY6',
    'SAFEPLUS_CAPTAIN2_VS_BASE',
    'SAFEPLUS_CAPTAIN2_WIRING_CHECK'
)
foreach ($name in $retiredTasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Backup-TaskXml $name
        Disable-ScheduledTask -TaskName $name | Out-Null
    }
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) `
    -MultipleInstances IgnoreNew
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')

$signalName = 'SAFEPLUS_STRATEGY01_SIGNAL'
Backup-TaskXml $signalName
$signalAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY01_SIGNAL.cmd'
$signalTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek $days `
    -At ([datetime]'08:55:00')
Register-ScheduledTask `
    -TaskName $signalName `
    -Action $signalAction `
    -Trigger $signalTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description '새전략 01 장초반 급상승 신호전용 감시(주문 0)' `
    -Force | Out-Null

$engineName = 'SAFEPLUS_STRATEGY01_LIVE'
Backup-TaskXml $engineName
$engineAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY01_LIVE.cmd'
$engineTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek $days `
    -At ([datetime]'08:55:30')
Register-ScheduledTask `
    -TaskName $engineName `
    -Action $engineAction `
    -Trigger $engineTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description '새전략 01 독립 매수·공통 상승보유·공통매도(승인 전 주문 0)' `
    -Force | Out-Null

Get-ScheduledTask -TaskName $signalName, $engineName |
    Select-Object TaskName, State, @{n='Enabled';e={$_.Settings.Enabled}},
        @{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}

$ErrorActionPreference = 'Stop'

$root = 'C:\stock_bot'
$backupDir = Join-Path $root 'DOCS\task_backup_20260726_strategy03'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

function Backup-TaskXml {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return
    }
    $safeName = $TaskName -replace '[^\w.-]', '_'
    $target = Join-Path $backupDir "$safeName.xml"
    if (Test-Path -LiteralPath $target) {
        return
    }
    Export-ScheduledTask -TaskName $TaskName |
        Set-Content -LiteralPath $target -Encoding Unicode
}

$valleyOff = Join-Path $root 'config\valley_off.flag'
$strategy03Off = Join-Path $root 'config\strategy_03_off.flag'
$strategy03Approval = Join-Path $root 'config\strategy_03_live_approved.flag'
if (-not (Test-Path -LiteralPath $valleyOff)) {
    throw 'Refusing replacement: valley_off.flag is missing.'
}
if (-not (Test-Path -LiteralPath $strategy03Off)) {
    throw 'Refusing replacement: strategy_03_off.flag is missing.'
}
if (Test-Path -LiteralPath $strategy03Approval) {
    throw 'Refusing order-zero installation: Strategy 03 approval already exists.'
}

$prerequisites = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST',
    'SAFEPLUS_HIGH_RANGE_BOARD',
    'SAFEPLUS_MFLOW_BOARD',
    'SAFEPLUS_MICRO_RANK_SHADOW',
    'SAFEPLUS_MONEYFLOW_WATCH'
)
foreach ($name in $prerequisites) {
    if ($null -eq (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) {
        throw "Required task is missing: $name"
    }
}

$retiredTasks = @(
    'SAFEPLUS_VALLEY_HUNTER_LIVE',
    'SAFEPLUS_VALLEY_EXT_SHADOW',
    'SAFEPLUS_VALLEY_FLAT',
    'SAFEPLUS_VALLEY_GATE1_DIAG',
    'SAFEPLUS_VALLEY_COMMON_EXIT_SHADOW'
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

$contextName = 'SAFEPLUS_STRATEGY_COMMON_CONTEXT'
Backup-TaskXml $contextName
$contextAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY_COMMON_CONTEXT.cmd'
$contextTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek $days `
    -At ([datetime]'08:54:30')
Register-ScheduledTask `
    -TaskName $contextName `
    -Action $contextAction `
    -Trigger $contextTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Independent strategies common candidate context (order 0)' `
    -Force | Out-Null

$preflightName = 'SAFEPLUS_STRATEGY03_PREFLIGHT'
Backup-TaskXml $preflightName
$preflightAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY03_PREFLIGHT.cmd'
$preflightTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek $days `
    -At ([datetime]'08:59:35')
Register-ScheduledTask `
    -TaskName $preflightName `
    -Action $preflightAction `
    -Trigger $preflightTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Strategy 03 fail-closed automatic live preflight' `
    -Force | Out-Null
$signalName = 'SAFEPLUS_STRATEGY03_SIGNAL'
Backup-TaskXml $signalName
$signalAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd'
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
    -Description '새전략 03 골짜기 급반등 신호전용 감시(주문 0)' `
    -Force | Out-Null

$engineName = 'SAFEPLUS_STRATEGY03_LIVE'
Backup-TaskXml $engineName
$engineAction = New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\cmd.exe' `
    -Argument '/c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd'
$engineTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek $days `
    -At ([datetime]'08:59:36')
Register-ScheduledTask `
    -TaskName $engineName `
    -Action $engineAction `
    -Trigger $engineTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description '새전략 03 골짜기 급반등·공통보유·공통매도(승인 전 주문 0)' `
    -Force | Out-Null

Get-ScheduledTask -TaskName ($retiredTasks + @($contextName, $signalName, $preflightName, $engineName)) `
    -ErrorAction SilentlyContinue |
    Select-Object TaskName, State, @{n='Enabled';e={$_.Settings.Enabled}},
        @{n='StartWhenAvailable';e={$_.Settings.StartWhenAvailable}}

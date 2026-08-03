$ErrorActionPreference = 'Stop'

$root = 'C:\stock_bot'
$backupDir = Join-Path $root 'DOCS\task_backup_20260726_strategy_all_live'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

function Backup-TaskXml {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return
    }
    $safeName = $TaskName -replace '[^\w.-]', '_'
    $target = Join-Path $backupDir "$safeName.xml"
    if (-not (Test-Path -LiteralPath $target)) {
        Export-ScheduledTask -TaskName $TaskName |
            Set-Content -LiteralPath $target -Encoding Unicode
    }
}

$strategies = @(
    @{ Id = 'S01'; Off = 'strategy_01_off.flag'; Approval = 'strategy_01_live_approved.flag' },
    @{ Id = 'S02'; Off = 'strategy_02_off.flag'; Approval = 'strategy_02_live_approved.flag' },
    @{ Id = 'S03'; Off = 'strategy_03_off.flag'; Approval = 'strategy_03_live_approved.flag' }
)
foreach ($strategy in $strategies) {
    $off = Join-Path $root ('config\' + $strategy.Off)
    $approval = Join-Path $root ('config\' + $strategy.Approval)
    if (-not (Test-Path -LiteralPath $off)) {
        throw "Refusing install: $($strategy.Id) OFF is missing."
    }
    if (Test-Path -LiteralPath $approval) {
        throw "Refusing install: $($strategy.Id) approval already exists."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'config\valley_off.flag'))) {
    throw 'Refusing install: retired valley OFF is missing.'
}

$required = @(
    'SAFEPLUS_WATCHDOG_BROKER',
    'SAFEPLUS_STRATEGY_WATCHLIST',
    'SAFEPLUS_STRATEGY_COMMON_CONTEXT',
    'SAFEPLUS_STRATEGY01_SIGNAL',
    'SAFEPLUS_STRATEGY02_SIGNAL',
    'SAFEPLUS_STRATEGY03_SIGNAL',
    'SAFEPLUS_HIGH_RANGE_BOARD',
    'SAFEPLUS_MFLOW_BOARD',
    'SAFEPLUS_MICRO_RANK_SHADOW',
    'SAFEPLUS_MONEYFLOW_WATCH',
    'SAFEPLUS_PREFLIGHT_SELFTEST_HIGH',
    'SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED'
)
foreach ($name in $required) {
    if ($null -eq (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) {
        throw "Required task is missing: $name"
    }
}

$retired = @(
    'SAFEPLUS_VALLEY_HUNTER_LIVE',
    'SAFEPLUS_VALLEY_EXT_SHADOW',
    'SAFEPLUS_VALLEY_FLAT',
    'SAFEPLUS_VALLEY_GATE1_DIAG',
    'SAFEPLUS_VALLEY_COMMON_EXIT_SHADOW',
    'SAFEPLUS_STRATEGY03_PREFLIGHT'
)
foreach ($name in $retired) {
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

function Register-WeeklyCmdTask {
    param(
        [string]$Name,
        [string]$At,
        [string]$CmdPath,
        [string]$Description
    )
    Backup-TaskXml $Name
    $action = New-ScheduledTaskAction `
        -Execute 'C:\Windows\System32\cmd.exe' `
        -Argument ("/c " + $CmdPath)
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek $days `
        -At ([datetime]$At)
    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null
}

Register-WeeklyCmdTask `
    -Name 'SAFEPLUS_STRATEGY_ALL_PREFLIGHT' `
    -At '08:59:35' `
    -CmdPath 'C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY_ALL_PREFLIGHT.cmd' `
    -Description 'Strategies 01/02/03 fail-closed daily account and data preflight'
Register-WeeklyCmdTask `
    -Name 'SAFEPLUS_STRATEGY01_LIVE' `
    -At '08:59:36' `
    -CmdPath 'C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY01_LIVE.cmd' `
    -Description 'Strategy 01 live gate; starts only after today all-strategy PASS'
Register-WeeklyCmdTask `
    -Name 'SAFEPLUS_STRATEGY03_LIVE' `
    -At '08:59:36' `
    -CmdPath 'C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd' `
    -Description 'Strategy 03 live gate; starts only after today all-strategy PASS'
Register-WeeklyCmdTask `
    -Name 'SAFEPLUS_STRATEGY02_LIVE' `
    -At '09:20:20' `
    -CmdPath 'C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd' `
    -Description 'Strategy 02 live gate; starts only after today all-strategy PASS'

$resultNames = @(
    'SAFEPLUS_STRATEGY_ALL_PREFLIGHT',
    'SAFEPLUS_STRATEGY01_LIVE',
    'SAFEPLUS_STRATEGY02_LIVE',
    'SAFEPLUS_STRATEGY03_LIVE'
) + $retired
Get-ScheduledTask -TaskName $resultNames -ErrorAction SilentlyContinue |
    Select-Object TaskName, State, @{n='Enabled';e={$_.Settings.Enabled}}

$ErrorActionPreference = 'Stop'

# Installs the read-only data source early warning tasks.
#   BOARD   08:45:00  --phase board    high range board only
#   PREOPEN 08:55:00  --phase preopen  board + context, realtime sources are WARN
#   LIVE    09:00:20  --phase live     all four sources are FAIL, before S01 09:20
#   EOD     17:10:00  --phase eod      collector progress, timeout ratio, delayed callbacks
#
# The phase is passed explicitly instead of being guessed from the clock, so a
# delayed start can never run the wrong check. RunLevel stays Limited on purpose.
# MultipleInstances is Parallel so an undismissed popup cannot swallow a later run.

$root = 'C:\stock_bot'
$cmdPath = Join-Path $root 'RUN\SAFEPLUS_DATA_SOURCE_EARLY_WARN.cmd'
$backupDir = Join-Path $root 'DOCS\task_backup_20260817_source_early_warn'
$legacyName = 'SAFEPLUS_DATA_SOURCE_EARLY_WARN'

if (-not (Test-Path -LiteralPath $cmdPath)) {
    throw "launcher not found: $cmdPath"
}
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$definitions = @(
    @{ Name = 'SAFEPLUS_DATA_SOURCE_EARLY_WARN_BOARD';   At = '08:45:00'; Phase = 'board' },
    @{ Name = 'SAFEPLUS_DATA_SOURCE_EARLY_WARN_PREOPEN'; At = '08:55:00'; Phase = 'preopen' },
    @{ Name = 'SAFEPLUS_DATA_SOURCE_EARLY_WARN_LIVE';    At = '09:00:20'; Phase = 'live' },
    @{ Name = 'SAFEPLUS_DATA_SOURCE_EARLY_WARN_EOD';     At = '17:10:00'; Phase = 'eod' }
)

$userId = "$env:USERDOMAIN\$env:USERNAME"
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances Parallel

$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

foreach ($definition in $definitions) {
    $existing = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        $target = Join-Path $backupDir ($definition.Name + '.xml')
        if (-not (Test-Path -LiteralPath $target)) {
            Export-ScheduledTask -TaskName $definition.Name |
                Set-Content -LiteralPath $target -Encoding Unicode
        }
    }
    $action = New-ScheduledTaskAction `
        -Execute 'C:\Windows\System32\cmd.exe' `
        -Argument ('/c ' + $cmdPath + ' --phase ' + $definition.Phase)
    $trigger = New-ScheduledTaskTrigger `
        -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]$definition.At)
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description ('Read-only source early warning, phase ' + $definition.Phase +
                      '. Writes report and log only; never touches flags, approvals or processes.') `
        -Force | Out-Null
}

# The old single task guessed its phase from the clock. Replaced by the three above.
$legacy = Get-ScheduledTask -TaskName $legacyName -ErrorAction SilentlyContinue
if ($null -ne $legacy) {
    $target = Join-Path $backupDir ($legacyName + '.xml')
    if (-not (Test-Path -LiteralPath $target)) {
        Export-ScheduledTask -TaskName $legacyName |
            Set-Content -LiteralPath $target -Encoding Unicode
    }
    Unregister-ScheduledTask -TaskName $legacyName -Confirm:$false
    Write-Output "removed legacy task: $legacyName"
}

Get-ScheduledTask -TaskName ($definitions.Name) | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    [PSCustomObject]@{
        TaskName = $_.TaskName
        State    = $_.State
        Enabled  = $_.Settings.Enabled
        RunLevel = $_.Principal.RunLevel
        Start    = $_.Triggers[0].StartBoundary
        Argument = $_.Actions[0].Arguments
        NextRun  = $info.NextRunTime
    }
} | Format-List

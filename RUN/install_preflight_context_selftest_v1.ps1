$ErrorActionPreference = 'Stop'

$root = 'C:\stock_bot'
$backupDir = Join-Path $root 'DOCS\task_backup_20260727_preflight_selftest'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$definitions = @(
    @{
        Name = 'SAFEPLUS_PREFLIGHT_SELFTEST_HIGH'
        At = '08:30:00'
        Cmd = 'C:\stock_bot\RUN\hidden\SAFEPLUS_PREFLIGHT_SELFTEST_HIGH.cmd'
        RunLevel = 'Highest'
    },
    @{
        Name = 'SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED'
        At = '08:30:10'
        Cmd = 'C:\stock_bot\RUN\hidden\SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED.cmd'
        RunLevel = 'Limited'
    }
)

$userId = "$env:USERDOMAIN\$env:USERNAME"
$days = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

foreach ($definition in $definitions) {
    $existing = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        $target = Join-Path $backupDir ($definition.Name + '.xml')
        if (-not (Test-Path -LiteralPath $target)) {
            Export-ScheduledTask -TaskName $definition.Name |
                Set-Content -LiteralPath $target -Encoding Unicode
        }
    }
    $principal = New-ScheduledTaskPrincipal `
        -UserId $userId `
        -LogonType Interactive `
        -RunLevel $definition.RunLevel
    $action = New-ScheduledTaskAction `
        -Execute 'C:\Windows\System32\cmd.exe' `
        -Argument ('/c ' + $definition.Cmd)
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek $days `
        -At ([datetime]$definition.At)
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'Three-stage read-only task-context preflight; order and approval capability zero' `
        -Force | Out-Null
}

Get-ScheduledTask -TaskName ($definitions.Name) |
    Select-Object TaskName, State,
        @{n='Enabled';e={$_.Settings.Enabled}},
        @{n='RunLevel';e={$_.Principal.RunLevel}},
        @{n='UserId';e={$_.Principal.UserId}},
        @{n='StartBoundary';e={$_.Triggers[0].StartBoundary}},
        @{n='RestartCount';e={$_.Settings.RestartCount}}

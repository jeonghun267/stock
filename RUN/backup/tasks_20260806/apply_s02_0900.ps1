# apply_s02_0900.ps1  [2026-08-06 owner order: run non-pullback strategies from 09:00]
# Moves S02 SIGNAL/LIVE task start times earlier so S02 operates from 09:00.
# S02 engine + signal code are already coded ENTRY_START=09:00; the task time was the only gate.
# S04(pullback) and S05(base breakout) are intentionally NOT touched.
#
# MUST be run in an ELEVATED (Administrator) PowerShell.
# TIMING: run BEFORE 08:55 today or the 08:55 SIGNAL slot is already past and it will not fire today.
#   If you cannot run it before 08:55, run it AFTER market close so it takes effect tomorrow.
#
# Apply:    powershell -ExecutionPolicy Bypass -File apply_s02_0900.ps1
# Rollback: powershell -ExecutionPolicy Bypass -File apply_s02_0900.ps1 -Rollback
param([switch]$Rollback)
$ErrorActionPreference = 'Stop'

# integrity check - refuse to run non-elevated (would fail with Access denied mid-way)
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: not elevated. Right-click PowerShell -> Run as Administrator, then rerun." -ForegroundColor Red
    exit 1
}

function Set-Start($name, $newStart) {
    $t = Get-ScheduledTask -TaskName $name
    $old = $t.Triggers[0].StartBoundary
    $t.Triggers[0].StartBoundary = $newStart
    Set-ScheduledTask -TaskName $name -Trigger $t.Triggers | Out-Null
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host ("  {0}: {1} -> {2}  nextRun={3}" -f $name, $old, $newStart, $info.NextRunTime)
}

if ($Rollback) {
    Write-Host "ROLLBACK S02 to 09:20 ..."
    Set-Start 'SAFEPLUS_STRATEGY02_SIGNAL' '2026-07-26T09:20:00+09:00'
    Set-Start 'SAFEPLUS_STRATEGY02_LIVE'   '2026-07-26T09:20:20+09:00'
} else {
    Write-Host "APPLY S02 -> 09:00 operation (SIGNAL 08:55, LIVE 08:59:36) ..."
    Set-Start 'SAFEPLUS_STRATEGY02_SIGNAL' '2026-07-26T08:55:00+09:00'
    Set-Start 'SAFEPLUS_STRATEGY02_LIVE'   '2026-07-26T08:59:36+09:00'
}
Write-Host "Done. (full restore also possible from the .xml backups in this folder via Register-ScheduledTask -Xml)"

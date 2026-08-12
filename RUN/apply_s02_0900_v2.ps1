# One-time ADMIN action: move S02 tasks from 09:20 to 09:00.
#
# Why (2026-08-06, owner order "2 beon 09si ro bakkwo"):
#   S01 now buys only the shallow band (-3% .. +3%). Deep drops between
#   09:00 and 09:20 are therefore unowned. S02 already covers the deep side
#   and its engine entry_start is ALREADY 09:00 - only the task trigger was late.
#   Signal task keeps a 20 second head start over the rotation engine.
#
# Safety:
#   - Only the time part of StartBoundary changes. DaysOfWeek (62 = Mon..Fri),
#     repetition, MultipleInstances and ExecutionTimeLimit are untouched.
#   - Refuses to run without elevation instead of failing halfway.
#   - Prints before/after so the change is visible.
#
# Rollback: run the same script with $ROLLBACK = $true.

$ErrorActionPreference = 'Stop'
$ROLLBACK = $false          # set to $true to put the tasks back to 09:20

# Keep a transcript so the result can be read after the elevated window closes.
$LogPath = 'C:\stock_bot\data\LOG\apply_s02_0900.log'
try { Start-Transcript -Path $LogPath -Force | Out-Null } catch { }

$plan = @(
    @{ Name = 'SAFEPLUS_STRATEGY02_SIGNAL'; Live = '09:20:00'; Early = '09:00:00' },
    @{ Name = 'SAFEPLUS_STRATEGY02_LIVE';   Live = '09:20:20'; Early = '09:00:20' }
)

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'NOT ELEVATED.'
    Write-Host 'Open PowerShell with "Run as administrator" and run this file again.'
    exit 1
}

Write-Host '--- before ---'
foreach ($p in $plan) {
    $t = Get-ScheduledTask -TaskName $p.Name
    foreach ($tr in $t.Triggers) {
        Write-Host ('  {0,-28} {1}  days={2}' -f $p.Name, $tr.StartBoundary, $tr.DaysOfWeek)
    }
}

Write-Host ''
foreach ($p in $plan) {
    if ($ROLLBACK) { $from = $p.Early; $to = $p.Live } else { $from = $p.Live; $to = $p.Early }
    $t = Get-ScheduledTask -TaskName $p.Name
    $changed = $false
    foreach ($tr in $t.Triggers) {
        if ($tr.StartBoundary -like ('*T' + $from + '*')) {
            $tr.StartBoundary = $tr.StartBoundary.Replace('T' + $from, 'T' + $to)
            $changed = $true
        }
    }
    if (-not $changed) {
        Write-Host ('  SKIP {0} - no trigger at {1} (already changed?)' -f $p.Name, $from)
        continue
    }
    Set-ScheduledTask -TaskName $p.Name -Trigger $t.Triggers | Out-Null
    Write-Host ('  OK   {0} : {1} -> {2}' -f $p.Name, $from, $to)
}

Write-Host ''
Write-Host '--- after ---'
$bad = 0
foreach ($p in $plan) {
    $t = Get-ScheduledTask -TaskName $p.Name
    $i = $t | Get-ScheduledTaskInfo
    foreach ($tr in $t.Triggers) {
        Write-Host ('  {0,-28} {1}  days={2}  next={3}' -f $p.Name, $tr.StartBoundary, $tr.DaysOfWeek, $i.NextRunTime)
        if ($tr.DaysOfWeek -ne 62) { $bad = $bad + 1 }
    }
    if ($t.Principal.RunLevel -ne 'Highest') { $bad = $bad + 1 }
}
Write-Host ''
if ($bad -eq 0) {
    Write-Host 'Done. days=62 (Mon-Fri) and RunLevel=Highest are intact.'
} else {
    Write-Host 'WARNING: days or RunLevel changed - check the two tasks manually.'
}
try { Stop-Transcript | Out-Null } catch { }

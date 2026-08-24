# emergency_reopen_s0123_v1.ps1  (ASCII only per project rule)
# Reopen S01/S02/S03 buy gates after an auto-OFF (rehearsal fail etc.).
# Created 2026-08-14 after the 4-layer lockout incident. Korean runbook:
#   C:\stock_bot\DOCS\EMERGENCY_REOPEN_RUNBOOK_20260814.md
#
# DEFAULT IS DRY-RUN. Nothing is changed unless you pass -Go.
#   powershell -NoProfile -File C:\stock_bot\RUN\emergency_reopen_s0123_v1.ps1        # dry-run
#   powershell -NoProfile -File C:\stock_bot\RUN\emergency_reopen_s0123_v1.ps1 -Go   # execute
#
# The 4 locks and their release order:
#   1. Quarantine off/fail flags  (config\strategy_XX_off.flag, morning_rehearsal_fail.flag)
#   2. Kill elevated engine pythons via UAC prompt (owner must click Yes)
#   3. Restart the three LIVE scheduled tasks
#   4. Write approval flags in the EXACT format engines accept:
#        auto-approved YYYY-MM-DDTHH:MM:SS   (timestamp must be today, in the past)
#      Do NOT imitate the S06 format for S01-S03: preflight revokes it as fake.
#   5. Verify BUY_GATE_OPEN in the LIVE logs.
# NOTE: S01 entry window is 09:00-09:20. Reopening later only helps S02/S03.

param(
    [switch]$Go,
    [string]$KillPids = ""   # comma-separated PIDs to kill. Empty = kill step is SKIPPED even with -Go.
)

$ErrorActionPreference = 'Continue'
$cfg = 'C:\stock_bot\config'
$logs = 'C:\stock_bot\data\LOG'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$quarantine = Join-Path $cfg ("_disabled_" + $stamp)
$mode = 'DRY-RUN (pass -Go to execute)'
if ($Go) { $mode = 'EXECUTE' }
Write-Host ("=== emergency reopen S01-S03  mode: " + $mode + " ===")

# --- Step 1: off/fail flags ---
Write-Host "`n[1] off/fail flags"
$flags = @('strategy_01_off.flag','strategy_02_off.flag','strategy_03_off.flag','morning_rehearsal_fail.flag')
foreach ($f in $flags) {
    $p = Join-Path $cfg $f
    if (Test-Path $p) {
        Write-Host ("  found: " + $f)
        if ($Go) {
            if (-not (Test-Path $quarantine)) { New-Item -ItemType Directory -Force $quarantine | Out-Null }
            Move-Item $p (Join-Path $quarantine $f) -Force
            Write-Host ("  moved -> " + $quarantine)
        }
    } else {
        Write-Host ("  absent: " + $f)
    }
}

# --- Step 2: elevated engine pythons ---
Write-Host "`n[2] elevated engine pythons (blank cmdline, started today)"
$todayStart = (Get-Date).Date
$enginePids = @()
Get-WmiObject Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and -not $_.CommandLine -and
    $_.ConvertToDateTime($_.CreationDate) -ge $todayStart
} | ForEach-Object {
    $t = $_.ConvertToDateTime($_.CreationDate).ToString('HH:mm:ss')
    Write-Host ("  PID " + $_.ProcessId + "  started " + $t)
    $enginePids += $_.ProcessId
}
# SAFETY: the list above includes ALL hidden admin pythons - broker, collectors, etc.
# NEVER kill them all. Match start times against the LIVE tasks' LastRunTime, pick
# ONLY the engine PIDs, then pass them explicitly:  -Go -KillPids "5452,11648,8408"
foreach ($t in 'SAFEPLUS_STRATEGY01_LIVE','SAFEPLUS_STRATEGY02_LIVE','SAFEPLUS_STRATEGY03_LIVE') {
    try {
        $i = Get-ScheduledTask -TaskName $t -ErrorAction Stop | Get-ScheduledTaskInfo
        Write-Host ("  hint " + $t + " last started: " + $i.LastRunTime.ToString('HH:mm:ss'))
    } catch {}
}
if ($KillPids.Trim() -eq "") {
    Write-Host "  kill step SKIPPED (no -KillPids given). If engines hold old code, pass -KillPids."
} else {
    $targets = $KillPids -split ',' | ForEach-Object { [int]$_.Trim() }
    if ($Go) {
        $arg = ($targets | ForEach-Object { "/PID $_" }) -join ' '
        Write-Host ("  launching UAC prompt: taskkill /F " + $arg)
        Write-Host "  >>> OWNER MUST CLICK YES ON THE UAC PROMPT <<<"
        Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-Command',("taskkill /F " + $arg)
        $dead = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            if (-not (Get-Process -Id $targets -ErrorAction SilentlyContinue)) { $dead = $true; break }
        }
        if ($dead) { Write-Host "  all killed" } else { Write-Host "  WARNING: still alive - UAC not confirmed? aborting."; exit 2 }
    } else {
        Write-Host ("  would kill via UAC: " + ($targets -join ', '))
    }
}

# --- Step 3: restart LIVE tasks ---
Write-Host "`n[3] restart LIVE tasks"
$tasks = @('SAFEPLUS_STRATEGY01_LIVE','SAFEPLUS_STRATEGY02_LIVE','SAFEPLUS_STRATEGY03_LIVE')
foreach ($t in $tasks) {
    if ($Go) {
        Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName $t
        Write-Host ("  restarted: " + $t)
    } else {
        Write-Host ("  would restart: " + $t)
    }
}

# --- Step 4: approval flags (exact format) ---
Write-Host "`n[4] approval flags (auto-approved format)"
$ts = (Get-Date).AddSeconds(-30).ToString('yyyy-MM-ddTHH:mm:ss')
foreach ($n in '01','02','03') {
    $p = Join-Path $cfg ("strategy_" + $n + "_live_approved.flag")
    $content = "auto-approved " + $ts
    if ($Go) {
        [IO.File]::WriteAllText($p, $content, [Text.Encoding]::ASCII)
        Write-Host ("  wrote: strategy_" + $n + "_live_approved.flag  '" + $content + "'")
    } else {
        Write-Host ("  would write: strategy_" + $n + "_live_approved.flag  '" + $content + "'")
    }
}

# --- Step 5: verify gates ---
Write-Host "`n[5] verify BUY_GATE_OPEN (engines re-read flags every decision tick)"
if ($Go) {
    Start-Sleep -Seconds 25
    foreach ($f in 'sched_STRATEGY02_LIVE.log','sched_STRATEGY03_LIVE.log') {
        $p = Join-Path $logs $f
        if (Test-Path $p) {
            Write-Host ("  --- " + $f + " ---")
            Get-Content $p -Tail 3 | ForEach-Object { Write-Host ("  " + $_) }
        }
    }
    Write-Host "`nCheck above for: BUY_GATE_OPEN entries enabled (PREFLIGHT_APPROVED)"
} else {
    Write-Host "  (dry-run: would tail S02/S03 LIVE logs for BUY_GATE_OPEN)"
}
Write-Host "`n=== done ==="

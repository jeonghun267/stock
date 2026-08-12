param([switch]$NonInteractive)

# [SEC 2026-08-05] Close the privilege-escalation hole on the Python runtimes.
#
# ASCII ONLY. Windows PowerShell 5.1 reads a BOM-less .ps1 as cp949, so any
# non-ASCII byte here becomes mojibake and the script fails to parse.
#
# PROBLEM
#   C:\python310 (engine) and C:\Python310-32 (broker IPC) inherit
#   "Authenticated Users : Modify" from the C:\ root - every ACE shows (I).
#   Any account in Authenticated Users can rewrite site-packages\*.py or even
#   python.exe itself. 13 scheduled tasks run these interpreters at
#   RunLevel=Highest, so a non-admin file edit becomes ADMIN code execution
#   at 08:59. That in turn defeats the 2026-08-04 HMAC order authentication:
#   an admin can read config\ipc_order_auth.key and sign forged
#   SENDORDER_REAL requests. This single hole voids every other order guard.
#
#   This is not a Python installer bug. C:\ grants (OI)(CI)(IO)(M) to
#   Authenticated Users by default, so ANY folder created directly under C:\
#   is writable by every logged-on account. Installing the interpreters
#   outside C:\Program Files is what exposed them.
#
# ORDER MATTERS
#   UserK's write access to these folders comes ONLY from that same
#   Authenticated Users entry. Removing it first would break pip and
#   __pycache__ writes. So: break inheritance (no effective change), grant
#   UserK explicitly, verify, and only then remove Authenticated Users.
#
# WHY NOT DURING MARKET HOURS
#   Recursive ACL work on ~40k files takes minutes and the interpreters are
#   in use from 08:28. Run this after 15:30.
#
# ROLLBACK (pre-made backups from 2026-08-05 07:xx)
#   icacls C:\python310    /restore "C:\quarantine_malware_20260805\acl_backup_python310_20260805.txt"
#   icacls C:\Python310-32 /restore "C:\quarantine_malware_20260805\acl_backup_python310-32_20260805.txt"

$ErrorActionPreference = "Stop"

$TARGETS = @(
    @{ Path = "C:\python310";    Name = "python310"    },
    @{ Path = "C:\Python310-32"; Name = "python310-32" }
)
$SNAPDIR = "C:\stock_bot\config"

function Test-PythonRuns {
    param([string]$Root)
    $exe = Join-Path $Root "python.exe"
    if (-not (Test-Path $exe)) { return "python.exe missing" }
    try {
        $v = & $exe -c "import sys; sys.stdout.write('ok')" 2>&1
        if ($LASTEXITCODE -ne 0) { return ("exit=" + $LASTEXITCODE + " " + $v) }
        if ("$v" -notmatch "ok") { return ("unexpected output: " + $v) }
        return $null
    } catch {
        return $_.Exception.Message
    }
}

function Test-WriteProbe {
    param([string]$Root)
    $bad = @()
    foreach ($sub in @("", "Lib", "Lib\site-packages", "Scripts")) {
        $p = if ($sub) { Join-Path $Root $sub } else { $Root }
        if (-not (Test-Path $p)) { continue }
        $f = Join-Path $p ("_acl_probe_" + $PID + ".tmp")
        try {
            [IO.File]::WriteAllText($f, "probe")
            Remove-Item $f -Force
        } catch {
            $bad += $(if ($sub) { $sub } else { "(root)" })
        }
    }
    return $bad
}

Write-Host "=== [0/5] admin check ==="
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "!! Not elevated. Re-run from an ADMIN PowerShell." -ForegroundColor Red
    if (-not $NonInteractive) { Read-Host "Press Enter to close" }
    exit 1
}
Write-Host ("  OK (" + $id.Name + ")")

$hour = (Get-Date).Hour
$min  = (Get-Date).Minute
if ($hour -ge 8 -and ($hour -lt 15 -or ($hour -eq 15 -and $min -lt 30))) {
    Write-Host "!! Market session window (08:00-15:30). Interpreters are in use." -ForegroundColor Red
    Write-Host "   Re-run after 15:30, or pass -NonInteractive to override." -ForegroundColor Yellow
    if (-not $NonInteractive) {
        Read-Host "Press Enter to close"
        exit 1
    }
    Write-Host "   Override accepted - continuing." -ForegroundColor Yellow
}

foreach ($t in $TARGETS) {
    $TARGET = $t.Path
    $SNAP   = Join-Path $SNAPDIR ("acl_snapshot_" + $t.Name + "_20260805.txt")

    Write-Host ""
    Write-Host ("########## " + $TARGET + " ##########")

    if (-not (Test-Path $TARGET)) {
        Write-Host "  (not found - skipped)" -ForegroundColor Yellow
        continue
    }

    Write-Host "=== [1/5] save ACL snapshot for rollback ==="
    icacls $TARGET /save $SNAP /t /c | Out-Null
    if (-not (Test-Path $SNAP)) {
        Write-Host "!! snapshot failed - aborting, nothing changed" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Press Enter to close" }
        exit 1
    }
    Write-Host ("  saved: " + $SNAP)

    $pre = Test-PythonRuns -Root $TARGET
    if ($pre) {
        Write-Host ("!! interpreter already broken BEFORE any change: " + $pre) -ForegroundColor Red
        Write-Host "   Not touching ACLs - fix the interpreter first." -ForegroundColor Yellow
        if (-not $NonInteractive) { Read-Host "Press Enter to close" }
        exit 1
    }
    Write-Host "  interpreter runs OK (baseline)"

    Write-Host "=== [2/5] break inheritance (copies current rights, no effective change) ==="
    icacls $TARGET /inheritance:d | Out-Null

    Write-Host "=== [3/5] grant UserK Modify explicitly (additive only) ==="
    icacls $TARGET /grant "UserK:(OI)(CI)M" | Out-Null
    $bad = Test-WriteProbe -Root $TARGET
    if ($bad.Count -gt 0) {
        Write-Host ("!! write failing after grant: " + ($bad -join ", ") + " - rolling back") -ForegroundColor Red
        icacls $TARGET /restore $SNAP /c | Out-Null
        if (-not $NonInteractive) { Read-Host "Press Enter to close" }
        exit 1
    }
    Write-Host "  write OK"

    Write-Host "=== [4/5] remove Authenticated Users (the actual fix) ==="
    icacls $TARGET /remove:g "*S-1-5-11" /t /c | Out-Null
    $bad = Test-WriteProbe -Root $TARGET
    $run = Test-PythonRuns -Root $TARGET
    if ($bad.Count -gt 0 -or $run) {
        Write-Host "!! broken after removal - ROLLING BACK NOW" -ForegroundColor Red
        if ($bad.Count -gt 0) { Write-Host ("   write fail: " + ($bad -join ", ")) -ForegroundColor Red }
        if ($run)            { Write-Host ("   interpreter: " + $run) -ForegroundColor Red }
        icacls $TARGET /restore $SNAP /c | Out-Null
        Write-Host "  restored. Nothing changed." -ForegroundColor Yellow
        if (-not $NonInteractive) { Read-Host "Press Enter to close" }
        exit 1
    }
    Write-Host "  write OK (admin token) + interpreter runs OK"

    Write-Host "=== [5/5] residual Authenticated Users ACEs below the root ==="
    $left = (icacls $TARGET /t /c 2>$null | Select-String -Pattern "Authenticated Users" | Measure-Object).Count
    if ($left -gt 0) {
        Write-Host ("  !! " + $left + " explicit ACE(s) still reference Authenticated Users") -ForegroundColor Yellow
        Write-Host "     Inspect manually - inherited removal did not reach them." -ForegroundColor Yellow
    } else {
        Write-Host "  none left (clean)"
    }

    Write-Host "--- final ACL ---"
    icacls $TARGET
    Write-Host ("ROLLBACK: icacls " + $TARGET + " /restore `"" + $SNAP + "`"") -ForegroundColor Green
}

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "NEXT (required): from a NON-admin shell run" -ForegroundColor Yellow
Write-Host "  C:\python310\python.exe -c `"import sys;print(sys.version)`"" -ForegroundColor Yellow
Write-Host "  C:\Python310-32\python.exe -c `"import sys;print(sys.version)`"" -ForegroundColor Yellow
Write-Host "That is the Limited-task condition; the admin-token check above does not prove it." -ForegroundColor Yellow
if (-not $NonInteractive) { Read-Host "Press Enter to close" }

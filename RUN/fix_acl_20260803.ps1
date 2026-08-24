param([switch]$NonInteractive)

# [SEC 2026-08-03] Close privilege-escalation hole on C:\stock_bot
#
# ASCII ONLY. Windows PowerShell 5.1 reads a BOM-less .ps1 as cp949, so any
# non-ASCII byte here becomes mojibake and the script fails to parse.
#
# PROBLEM
#   C:\stock_bot inherits "Authenticated Users : Modify" from the C:\ root, so any
#   non-admin process can rewrite RUN\*.py. Meanwhile STRATEGY01_LIVE,
#   WATCHDOG_BROKER and PIPELINE_0900 run at RunLevel=Highest. A non-admin file
#   edit therefore becomes admin-level code execution at 08:59.
#
# ORDER MATTERS
#   UserK's write access comes ONLY from that Authenticated Users entry. Removing
#   it first would paralyze every Limited-level task (STRATEGY06_LIVE,
#   REGIME_PRIORITY_JUDGE ...) because they could no longer write logs or state.
#   So: grant UserK explicitly, verify, and only then remove Authenticated Users.
#
# ROLLBACK
#   icacls C:\stock_bot /restore "C:\stock_bot\config\acl_snapshot_20260803.txt"

$ErrorActionPreference = "Stop"
$TARGET = "C:\stock_bot"
$SNAP   = "C:\stock_bot\config\acl_snapshot_20260803.txt"
$AUTH_KEY = "C:\stock_bot\config\ipc_order_auth.key"
$DIRS   = @("RUN", "data", "LOG", "IPC", "config", "RUN\hidden", "data\LOG")

function Test-WriteAll {
    $bad = @()
    foreach ($d in $DIRS) {
        $p = Join-Path $TARGET $d
        if (-not (Test-Path $p)) { continue }
        $f = Join-Path $p ("_acl_probe_" + $PID + ".tmp")
        try {
            [IO.File]::WriteAllText($f, "probe")
            Remove-Item $f -Force
        } catch {
            $bad += $d
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

Write-Host "=== [1/5] save ACL snapshot for rollback ==="
icacls $TARGET /save $SNAP | Out-Null
if (-not (Test-Path $SNAP)) {
    Write-Host "!! snapshot failed - aborting, nothing changed" -ForegroundColor Red
    if (-not $NonInteractive) { Read-Host "Press Enter to close" }
    exit 1
}
Write-Host ("  saved: " + $SNAP)

Write-Host "=== [2/5] break inheritance (copies current rights, no effective change) ==="
icacls $TARGET /inheritance:d | Out-Null

Write-Host "=== [3/5] grant UserK Modify explicitly (additive only) ==="
icacls $TARGET /grant "UserK:(OI)(CI)M" | Out-Null
$bad = Test-WriteAll
if ($bad.Count -gt 0) {
    Write-Host ("!! write still failing after grant: " + ($bad -join ", ") + " - rolling back") -ForegroundColor Red
    icacls $TARGET /restore $SNAP | Out-Null
    if (-not $NonInteractive) { Read-Host "Press Enter to close" }
    exit 1
}
Write-Host ("  write OK (" + $DIRS.Count + " folders)")

Write-Host "=== [4/5] remove Authenticated Users (the actual fix) ==="
icacls $TARGET /remove:g "*S-1-5-11" | Out-Null
$bad = Test-WriteAll
if ($bad.Count -gt 0) {
    Write-Host ("!! write failing after removal: " + ($bad -join ", ") + " - ROLLING BACK NOW") -ForegroundColor Red
    icacls $TARGET /restore $SNAP | Out-Null
    Write-Host "  restored. Nothing changed." -ForegroundColor Yellow
    if (-not $NonInteractive) { Read-Host "Press Enter to close" }
    exit 1
}
Write-Host "  write OK (admin token)"

Write-Host "=== [5/6] create/protect SENDORDER_REAL HMAC key ==="
if (-not (Test-Path $AUTH_KEY)) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        [IO.File]::WriteAllBytes($AUTH_KEY, $bytes)
    } finally {
        $rng.Dispose()
    }
}
if ((Get-Item -LiteralPath $AUTH_KEY).Length -lt 32) {
    throw "IPC order auth key is invalid"
}
icacls $AUTH_KEY /inheritance:r /grant:r `
    ($id.Name + ":F") "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to protect IPC order auth key ACL" }
Write-Host "  key ready; content not displayed"

Write-Host "=== [6/6] final ACL ==="
icacls $TARGET
Write-Host ""
Write-Host ("DONE. Rollback: icacls " + $TARGET + " /restore `"" + $SNAP + "`"") -ForegroundColor Green
Write-Host "NEXT: verify writes from a NON-admin shell (that is the Limited-task condition)." -ForegroundColor Yellow
if (-not $NonInteractive) { Read-Host "Press Enter to close" }

# security_repair_20260807b.ps1  (ASCII only - PowerShell 5.1)
# Follow-up to security_repair_20260807.ps1
# Removes the 3 stale Defender exclusions using the supported cmdlet. Direct
# registry edits failed because Defender protects its own keys once running.
# C:\Windows\KTools.exe is kept on purpose (user decision 2026-08-07: removing it
# could let Defender quarantine the Windows activation tool).
# No scan is started here - scanning is a separate decision.

$ErrorActionPreference = 'Continue'
$log = "C:\stock_bot\backup_security_20260807\repair_log_b.txt"
function Say($m) { $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Write-Output $line; Add-Content -Path $log -Value $line -Encoding utf8 }

Say "==== follow-up start ===="
$pr = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Say "ABORT: not elevated"; exit 2 }

$stale = @('C:\KInstall\kPASC.exe',
           'C:\KInstall\OneDriveUnInstaller.exe',
           'C:\Program Files (x86)\KUtils\dControl\dControl.exe')
foreach ($p in $stale) {
    try { Remove-MpPreference -ExclusionPath $p -ErrorAction Stop; Say "  removed exclusion $p" }
    catch { Say "  FAILED exclusion $p : $($_.Exception.Message)" }
}
$left = (Get-MpPreference).ExclusionPath
Say ("  VERIFY exclusions left: " + ($left -join ' ; '))
Say "  (expected: only C:\Windows\KTools.exe)"
Say "==== follow-up done ===="

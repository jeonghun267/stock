# security_repair_20260807.ps1  (ASCII only - PowerShell 5.1)
# Admin-only steps 2..5 of the 2026-08-07 security repair plan.
# Run elevated. Every action is logged and verified. Rollback notes at the bottom.
#
# Step 2  Defender restore (policy keys removed, service Automatic+started,
#                           stale exclusions removed; KTools kept by user decision)
# Step 3  Python x2: owner -> Administrators, then UserK demoted to RX
# Step 4  _run_hidden*.vbs x2: UserK demoted to RX
# Step 5  IPC folder: remove inherited Users read
#
# Backups already taken by the caller in C:\stock_bot\backup_security_20260807

$ErrorActionPreference = 'Continue'
$log = "C:\stock_bot\backup_security_20260807\repair_log.txt"
$bk  = "C:\stock_bot\backup_security_20260807"

function Say($m) { $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Write-Output $line; Add-Content -Path $log -Value $line -Encoding utf8 }

Say "==== security repair start ===="
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Say "ABORT: not elevated"; exit 2
}
Say ("elevated OK as " + $id.Name)

# ---------------- Step 2: Defender ----------------
Say "-- step 2: Defender restore"
$root = "HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender"
$vals = @('DisableAntiSpyware','DisableRealtimeMonitoring','DisableAntiVirus','DisableAntiVirusKK',
          'DisableSpecialRunningModes','DisableRoutinelyTakingAction','ServiceKeepAlive',
          'ServiceStartStates','AllowFastServiceStartup')
foreach ($v in $vals) {
    try { Remove-ItemProperty -Path $root -Name $v -ErrorAction Stop; Say "  removed policy $v" }
    catch { Say "  skip policy $v ($($_.Exception.Message))" }
}
$rtp = "$root\Real-Time Protection"
foreach ($v in @('DisableRealtimeMonitoring','DisableBehaviorMonitoring','DisableOnAccessProtection','DisableScanOnRealtimeEnable')) {
    try { Remove-ItemProperty -Path $rtp -Name $v -ErrorAction Stop; Say "  removed RTP $v" }
    catch { Say "  skip RTP $v" }
}
$spy = "$root\Spynet"
foreach ($v in @('DisableBlockAtFirstSeen')) {
    try { Remove-ItemProperty -Path $spy -Name $v -ErrorAction Stop; Say "  removed Spynet $v" }
    catch { Say "  skip Spynet $v" }
}

# stale exclusions only. C:\Windows\KTools.exe is kept on purpose (user decision
# 2026-08-07: removing it may let Defender quarantine the activation tool).
$exc = "HKLM:\SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths"
foreach ($p in @('C:\Program Files (x86)\KUtils\dControl\dControl.exe',
                 'C:\KInstall\kPASC.exe','C:\KInstall\OneDriveUnInstaller.exe')) {
    try { Remove-ItemProperty -Path $exc -Name $p -ErrorAction Stop; Say "  removed exclusion $p" }
    catch { Say "  skip exclusion $p" }
}

try { Set-Service -Name WinDefend -StartupType Automatic -ErrorAction Stop; Say "  WinDefend -> Automatic" }
catch { Say "  WinDefend StartupType failed: $($_.Exception.Message)" }
try { Start-Service -Name WinDefend -ErrorAction Stop; Say "  WinDefend started" }
catch { Say "  WinDefend start failed: $($_.Exception.Message)" }
Start-Sleep -Seconds 5
try {
    $st = Get-MpComputerStatus -ErrorAction Stop
    Say ("  VERIFY AMService={0} RealTime={1} Antivirus={2}" -f $st.AMServiceEnabled, $st.RealTimeProtectionEnabled, $st.AntivirusEnabled)
    if (-not $st.RealTimeProtectionEnabled) {
        try { Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction Stop; Say "  forced RealTime on" } catch { Say "  Set-MpPreference failed" }
    }
} catch { Say "  Get-MpComputerStatus still failing: $($_.Exception.Message)" }

# ---------------- Step 3: Python ownership + ACL ----------------
Say "-- step 3: python ownership and ACL"
foreach ($d in @('C:\python310','C:\Python310-32')) {
    if (-not (Test-Path $d)) { Say "  MISSING $d"; continue }
    $o1 = (Get-Acl $d).Owner
    & takeown.exe /F $d /A /R /D Y | Out-Null
    $o2 = (Get-Acl $d).Owner
    Say ("  {0} owner {1} -> {2}" -f $d, $o1, $o2)
    & icacls.exe $d /remove:g "WIN10-01\UserK" /t /c /q | Out-Null
    & icacls.exe $d /grant "WIN10-01\UserK:(OI)(CI)(RX)" /t /c /q | Out-Null
    $now = (& icacls.exe $d | Select-Object -First 6) -join ' | '
    Say ("  VERIFY {0} -> {1}" -f $d, $now)
}

# ---------------- Step 4: vbs launchers ----------------
Say "-- step 4: _run_hidden vbs"
foreach ($f in @('C:\stock_bot\RUN\_run_hidden.vbs','C:\stock_bot\RUN\_run_hidden_wait.vbs')) {
    if (-not (Test-Path $f)) { Say "  MISSING $f"; continue }
    & takeown.exe /F $f /A | Out-Null
    & icacls.exe $f /inheritance:d /c /q | Out-Null
    & icacls.exe $f /remove:g "WIN10-01\UserK" /c /q | Out-Null
    & icacls.exe $f /grant "WIN10-01\UserK:(RX)" /c /q | Out-Null
    $now = (& icacls.exe $f | Select-Object -First 6) -join ' | '
    Say ("  VERIFY {0} -> {1}" -f (Split-Path $f -Leaf), $now)
}

# ---------------- Step 5: IPC folder ----------------
Say "-- step 5: IPC Users read removed"
$ipc = 'C:\stock_bot\IPC'
& icacls.exe $ipc /inheritance:d /t /c /q | Out-Null
& icacls.exe $ipc /remove:g "BUILTIN\Users" /t /c /q | Out-Null
$now = (& icacls.exe $ipc | Select-Object -First 8) -join ' | '
Say ("  VERIFY IPC -> {0}" -f $now)

Say "==== done ===="
Say "ROLLBACK:"
Say "  ACL   : icacls C:\ /restore $bk\acl_python310.txt   (same for _32 / ipc / vbs files)"
Say "  Defend: reg import $bk\defender_policy.reg  then  Set-Service WinDefend -StartupType Manual"
Say "  Tasks : XML in $bk\tasks"

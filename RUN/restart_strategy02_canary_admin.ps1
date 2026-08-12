$ErrorActionPreference = "Stop"

$lockPath = "C:\stock_bot\data\strategy_02_rotation_v1.lock"
$launcherPath = "C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd"
$expectedPid = 8816

if (-not (Test-Path -LiteralPath $lockPath)) {
    throw "S02 lock file is missing: $lockPath"
}
$lockedPid = [int](Get-Content -LiteralPath $lockPath -Raw)
if ($lockedPid -ne $expectedPid) {
    throw "S02 lock PID changed: expected $expectedPid, got $lockedPid"
}

Stop-Process -Id $expectedPid -Force
Start-Sleep -Seconds 2
if (Get-Process -Id $expectedPid -ErrorAction SilentlyContinue) {
    throw "S02 process $expectedPid did not stop"
}

$env:S02_PEAK_5_DROP_1P5_FLOW_3OF4_6S_DATE = "20260811"
Start-Process -FilePath "C:\Windows\System32\cmd.exe" `
    -ArgumentList "/c", $launcherPath `
    -WindowStyle Hidden

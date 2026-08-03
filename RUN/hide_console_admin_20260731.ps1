# hide_console_admin_20260731.ps1 — [2026-07-31 밤] 검은 콘솔 숨기기 · 관리자 권한 태스크 11개 몫
# 실행: 관리자 PowerShell에서  powershell -ExecutionPolicy Bypass -File C:\stock_bot\RUN\hide_console_admin_20260731.ps1
# 하는 일: cmd 직접실행 태스크 10개 → wscript+_run_hidden_wait.vbs 래핑 / PIPELINE_0900 → -WindowStyle Hidden 추가.
# 백업: DOCS\task_xml_backup_20260730_hide\<이름>.xml (7/30 오전 194개) — 되돌리기는 Register-ScheduledTask -Xml.
# 검증: 적용 후 읽어서 대조 + (PIPELINE_0900 제외) 1개씩 수동 실행 → 결과 확인 → 밤 수동분 정지.
$log = "C:\stock_bot\LOG\hide_console_admin_20260731.log"
function W($m) { $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m; $line | Out-File $log -Append -Encoding utf8; Write-Host $line }
$V = 'C:\stock_bot\RUN\_run_hidden_wait.vbs'
$H = 'C:\stock_bot\RUN\hidden'
$B = 'C:\stock_bot\DOCS\task_xml_backup_20260730_hide'
W "=== 관리자 몫 콘솔 숨기기 시작 ==="

$wrap = [ordered]@{
    'SAFEPLUS_PREFLIGHT_SELFTEST_HIGH'    = "$H\SAFEPLUS_PREFLIGHT_SELFTEST_HIGH.cmd"
    'SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED' = "$H\SAFEPLUS_PREFLIGHT_SELFTEST_LIMITED.cmd"
    'SAFEPLUS_STRATEGY01_LIVE'            = "$H\SAFEPLUS_STRATEGY01_LIVE.cmd"
    'SAFEPLUS_STRATEGY01_SIGNAL'          = "$H\SAFEPLUS_STRATEGY01_SIGNAL.cmd"
    'SAFEPLUS_STRATEGY02_LIVE'            = "$H\SAFEPLUS_STRATEGY02_LIVE.cmd"
    'SAFEPLUS_STRATEGY02_SIGNAL'          = "$H\SAFEPLUS_STRATEGY02_SIGNAL.cmd"
    'SAFEPLUS_STRATEGY03_LIVE'            = "$H\SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd"
    'SAFEPLUS_STRATEGY03_SIGNAL'          = "$H\SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd"
    'SAFEPLUS_STRATEGY_ALL_PREFLIGHT'     = "$H\SAFEPLUS_STRATEGY_ALL_PREFLIGHT.cmd"
    'SAFEPLUS_STRATEGY_COMMON_CONTEXT'    = "$H\SAFEPLUS_STRATEGY_COMMON_CONTEXT.cmd"
}
$fail = 0
foreach ($n in $wrap.Keys) {
    $new = $null; $cmd = $wrap[$n]
    if (-not (Test-Path "$B\$n.xml")) { W "건너뜀(백업없음) $n"; $fail++; continue }
    if (-not (Test-Path $cmd))        { W "건너뜀(cmd없음) $n : $cmd"; $fail++; continue }
    try {
        $new = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "//B `"$V`" `"$cmd`""
        Set-ScheduledTask -TaskName $n -Action $new -ErrorAction Stop | Out-Null
        $chk = (Get-ScheduledTask -TaskName $n).Actions[0]
        if ($chk.Execute -match 'wscript' -and $chk.Arguments -like "*$cmd*") { W "OK $n" }
        else { W "대조 불일치! $n -> $($chk.Execute) $($chk.Arguments)"; $fail++ }
    } catch { W "실패 $n : $($_.Exception.Message)"; $fail++ }
}

# PIPELINE_0900 — powershell 창 숨김 플래그만 추가 (vbs 불필요·밤 수동실행은 하지 않는다: 아침 파이프라인이라)
try {
    $new = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\stock_bot\RUN\run_safeplus_pipeline_0900.ps1'
    Set-ScheduledTask -TaskName 'SAFEPLUS_PIPELINE_0900' -Action $new -ErrorAction Stop | Out-Null
    W "OK SAFEPLUS_PIPELINE_0900 (-WindowStyle Hidden 추가)"
} catch { W "실패 SAFEPLUS_PIPELINE_0900 : $($_.Exception.Message)"; $fail++ }

# 검증 — 1개씩 수동 실행(PIPELINE_0900 제외). 장기형은 Running=정상, 확인 후 밤 수동분 정지.
foreach ($n in $wrap.Keys) {
    Start-ScheduledTask -TaskName $n
    $w = 0; do { Start-Sleep -Milliseconds 800; $st = (Get-ScheduledTask -TaskName $n).State; $w++ } while ($st -eq 'Running' -and $w -lt 25)
    $r = (Get-ScheduledTaskInfo -TaskName $n).LastTaskResult
    W ("검증 {0} 상태={1} 결과={2}" -f $n, $st, $r)
    if ($st -eq 'Running') { Stop-ScheduledTask -TaskName $n; W "  -> 밤 수동분 정지" }
}
W "=== 끝 · 문제 $fail 건 (0이어야 정상) ==="
if ($fail -eq 0) { Write-Host "`n전부 성공. 이 창은 닫아도 됩니다." } else { Write-Host "`n문제 $fail 건 — 로그 확인: $log" }
Read-Host "엔터를 누르면 닫힙니다"

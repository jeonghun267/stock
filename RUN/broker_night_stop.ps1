# broker_night_stop.ps1 — [2026-07-08 친구님] 밤 브로커/워치독 깨끗한 정지
# 목적: 22:45~익일 08:35는 브로커를 쓰는 태스크가 없음(전수조사). 밤새 방치하면 얼어붙어(좀비)
#       키움 세션을 쥔 채 새벽 EOD 수집·아침 기동을 오염(7/6~7/8 실증) → 밤엔 깨끗하게 꺼둔다.
# 재기동: 아침 08:35 SAFEPLUS_WATCHDOG_BROKER(기존 태스크)가 새로 켬 — 추가 작업 불필요.
# 롤백: 태스크 SAFEPLUS_BROKER_NIGHT_STOP 비활성화(Disable) 한 번.
$log = "C:\stock_bot\LOG\broker_night_stop.log"
function W($m){ ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) | Out-File -FilePath $log -Append -Encoding utf8 }
W "=== NIGHT STOP 시작 ==="

# 0) EOD 일봉 수집기가 아직 돌고 있으면 오늘 밤은 건너뜀(백필 도중 사살 방지)
try {
    $hb = Get-Item "C:\stock_bot\LOG\collect_eod.heartbeat" -ErrorAction Stop
    $age = (New-TimeSpan -Start $hb.LastWriteTime -End (Get-Date)).TotalMinutes
    if ($age -lt 10) { W "EOD 수집기 진행중(하트비트 $([int]$age)분 전) - 오늘 밤 정지 건너뜀"; exit 0 }
} catch {}

# 0.5) [2026-07-08 친구님 "더 당길 수 있니"] 이른 정지(20시 이전 트리거)는 조건부 —
#      오늘 일봉이 이미 잘 들어왔으면(=20:00 재시도 보험 불필요) 즉시 정지, 아니면 22:45 백스톱에 맡김.
#      주말(장 없음)은 무조건 즉시 정지.
$nowH = (Get-Date).Hour
$dow = (Get-Date).DayOfWeek
if ($nowH -lt 20 -and $dow -ne "Saturday" -and $dow -ne "Sunday") {
    $eodFresh = $false
    try {
        $eod = Get-Item "C:\stock_bot\DATA\eod_daily_bars.csv" -ErrorAction Stop
        if ($eod.LastWriteTime.Date -eq (Get-Date).Date -and $eod.LastWriteTime.Hour -ge 17) { $eodFresh = $true }
    } catch {}
    if (-not $eodFresh) { W "이른 정지 보류 - 오늘 일봉 미완성(20:00 재수집 보험 위해 브로커 유지, 22:45 백스톱이 정지)"; exit 0 }
    W "이른 정지 진행 - 오늘 일봉 완성 확인(17시 이후 갱신)"
}

# 1) 워치독 먼저 정지(안 끄면 브로커를 되살림)
try { Stop-ScheduledTask -TaskName "SAFEPLUS_WATCHDOG_BROKER" -ErrorAction Stop; W "워치독 태스크 인스턴스 정지" }
catch { W "워치독 태스크 정지 실패/미실행: $($_.Exception.Message)" }
try {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -match "watchdog_broker_gateway" } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction Stop; W "워치독 프로세스 종료 PID=$($_.ProcessId)" } catch {} }
} catch { W "워치독 프로세스 탐색 실패: $($_.Exception.Message)" }

# 2) 브로커 정지(하트비트 PID 우선 → 잔존 broker_gateway 정리)
try {
    $b = Get-Content "C:\stock_bot\IPC\broker_heartbeat.json" -Raw | ConvertFrom-Json
    if ($b.pid) {
        try { Stop-Process -Id $b.pid -Force -Confirm:$false -ErrorAction Stop; W "브로커 종료 PID=$($b.pid)" }
        catch { W "브로커 PID=$($b.pid) 이미 없음" }
    }
} catch { W "하트비트 읽기 실패: $($_.Exception.Message)" }
try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "broker_gateway_v1" } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction Stop; W "잔존 브로커 종료 PID=$($_.ProcessId)" } catch {} }
} catch {}

W "=== NIGHT STOP 완료 (아침 08:35 워치독이 새로 켬) ==="

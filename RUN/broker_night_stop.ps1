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

# 2) 브로커 정지 — ★[2026-07-31 친구님 승인] IPC SHUTDOWN(정상 종료)으로 교체.
#    기존 Stop-Process 는 브로커가 관리자 권한이라 Access denied 로 매일 밤 헛방이었고,
#    실패를 catch 가 "이미 없음"으로 기록해 성공(결과 0)처럼 보였다(7/31 새벽 실측·같은 방법으로
#    00:55 정상 정지 실증). 게다가 관리자 프로세스는 CommandLine 도 안 보여 잔존 정리도 0건이었다.
#    롤백: backup\broker_night_stop_20260731_stopproc.ps1 복원.
#    ★[2026-08-01 친구님 "밤 정지 스크립트부터 고쳐줘"] 따옴표 수리 — PS5.1이 python -c 인자의
#    큰따옴표를 벗겨 파이썬이 매번 SyntaxError로 죽었고 SHUTDOWN이 한 번도 전송된 적 없음(7/31 밤 2회 실측).
#    파이썬 코드를 작은따옴표만 쓰게 교체 + stderr를 로그에 남김 + "pid 소멸"과 "IPC 정상종료"를 구분.
#    롤백: backup\broker_night_stop_20260801_pyquote.ps1 복원.
$stopped = $false
$how = ""   # "IPC"=하트비트가 SHUTDOWN 확인 / "PIDGONE"=pid만 소멸(정상종료 기록 없음)
try {
    $b = Get-Content "C:\stock_bot\IPC\broker_heartbeat.json" -Raw | ConvertFrom-Json
    if ($b.state -eq "SHUTDOWN") { W "브로커 이미 SHUTDOWN 상태 - 보낼 것 없음"; $stopped = $true; $how = "IPC" }
} catch { W "하트비트 읽기 실패: $($_.Exception.Message)" }
if (-not $stopped) {
    # 큰따옴표 금지 — PS5.1이 네이티브 인자의 " 를 벗긴다. 파이썬 문자열은 전부 작은따옴표로.
    $py = "import sys; sys.path.insert(0, r'C:\stock_bot\RUN'); from broker_client import BrokerClient; r = BrokerClient().request({'type': 'SHUTDOWN'}, timeout_sec=10.0); print(r.get('status'))"
    $out = (& C:\python310\python.exe -c $py 2>&1 | ForEach-Object { "$_" }) -join " / "
    if (-not $out) { $out = "(무응답)" }
    W "IPC SHUTDOWN 전송 -> $out"
    foreach ($i in 1..10) {
        Start-Sleep -Seconds 2
        try {
            $b2 = Get-Content "C:\stock_bot\IPC\broker_heartbeat.json" -Raw | ConvertFrom-Json
            if ($b2.state -eq "SHUTDOWN") { $stopped = $true; $how = "IPC"; break }
            $alive = $false
            if ($b2.pid) { try { $null = Get-Process -Id ([int]$b2.pid) -ErrorAction Stop; $alive = $true } catch { $alive = $false } }
            if (-not $alive) { $stopped = $true; $how = "PIDGONE"; break }
        } catch {}
    }
}
if ($stopped) {
    if ($how -eq "PIDGONE") {
        W "브로커 프로세스 소멸 확인 - 단 IPC 정상종료(SHUTDOWN) 기록은 없음. 하트비트가 낡은 것이면 다른 브로커가 살아있을 수 있음(수동 확인 권장)"
    } else {
        W "브로커 정지 확인 (IPC 정상 종료)"
    }
} else {
    # 좀비(IPC 무응답)면 일반 권한으론 강제종료 불가 - 시도는 하되 실패를 실패로 남긴다(삼키기 금지)
    W "★정지 실패 - 브로커가 IPC 에 응답하지 않음(좀비 의심)"
    try {
        $b3 = Get-Content "C:\stock_bot\IPC\broker_heartbeat.json" -Raw | ConvertFrom-Json
        if ($b3.pid) { taskkill /PID $($b3.pid) /F 2>&1 | ForEach-Object { W "  taskkill: $_" } }
    } catch {}
    W "★수동 조치 필요: 관리자 셸에서 taskkill /F /PID <하트비트 pid>"
}

W "=== NIGHT STOP 완료 (아침 08:35 워치독이 새로 켬) ==="

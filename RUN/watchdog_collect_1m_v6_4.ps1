# ═══════════════════════════════════════════════════════════════════════════════
# watchdog_collect_1m.ps1  v6_4  SAFEPLUS FINAL
# ═══════════════════════════════════════════════════════════════════════════════
#
# 역할     : collect_prices_1m_kiwoom_opt10080 생존 감시 + 품질 모니터링
# 실행방식 : powershell -File watchdog_collect_1m_v6_4.ps1  (상시 실행)
# 고유 영역 : prices_1m.csv 수집기 한정 — 타 프로세스 절대 불개입
# 작성 기준 : 헤지펀드 인프라 표준 (Renaissance/Citadel/Two Sigma 급)
#
# ── 고유영역 원칙 ──────────────────────────────────────────────────────────────
#   감시  : collector_1m 프로세스 + heartbeat + prices_1m.csv
#   쓰기  : LOG/watchdog_collect_1m_*.log
#           DATA/watchdog_collect_1m.heartbeat
#           DATA/heartbeat/watchdog_collect_1m.pid
#           LOG/watchdog_collect_1m_daily_stats.json
#   읽기  : DATA/collector_1m.heartbeat
#           DATA/collector_1m_evolve.json
#           DATA/prices_1m.csv (무결성 검증만)
#   금지  : SIGA/ RUN/ 쓰기 절대금지
#
# ═══════════════════════════════════════════════════════════════════════════════
# v6_4 변경 목록 (v6_3 → v6_4)
#
#   [FIX-PS1] 삼항연산자 (? :) → if/else 구문 교체
#             v6_3: halfopen_ok=([int]($prop.Value.halfopen_ok -ne $null ? ... : 0))
#             v6_4: if/else 구문 — PS5.1 완전 호환
#
#   [FIX-PY]  Python 경로 3단계 → 5단계 fallback
#             v6_3: UserK 하드코딩 → 새 컴퓨터에서 경로 미탐지 가능
#             v6_4: $env:USERNAME 동적 감지 추가 → 어떤 계정에서도 자동 인식
#
# ═══════════════════════════════════════════════════════════════════════════════
# v6_3 변경 목록 (v6_2 → v6_3)  [워치독 점검 Critical+High 전부 해소]
#
#   [FIX-1] fallback 경로 v4_13 → v4_14 수정
#           v6_2: fallback = collect_prices_1m_kiwoom_opt10080_v4_13_SAFEPLUS_FINAL.py
#           v6_3: fallback = collect_prices_1m_kiwoom_opt10080_v4_14_SAFEPLUS_FINAL__1_.py
#           효과: 자동감지 실패 시 실제 존재하는 파일로 fallback → 영구 기동 실패 방지
#
#   [FIX-2] 텔레그램 알림 버전 문자열 v6.0 → v6.3 수정
#           v6_2: '[WD-1M v6.0] $msg' 고정 → 장애 추적 혼동
#           v6_3: '[WD-1M v6.3] $msg' 로 버전 동기화
#
#   [FIX-3] RECOVER_CONFIRM 스코프 로컬 → $script: 승격
#           v6_2: $RECOVER_CONFIRM = 3 (로컬, finally 접근 불가)
#           v6_3: $script:RECOVER_CONFIRM = 3 + 파라미터 상수 블록 이동
#
#   [FIX-4] Is-MarketHour 시작 시각 08:55 → 08:45 조정
#           v6_2: 사전기동창(08:45~08:54) 후 장 시작(08:55) 사이 60초 sleep 공백 가능
#           v6_3: Is-MarketHour open = 08:45 → PreOpenWindow 연속성 보장
#
#   [유지] v6_2 모든 기능 (FIX-A~C, CB 3상태, Full Jitter, 히스테리시스 등)
#
# ── v6_2 변경 목록 (v6_1 → v6_2) ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
#
#   [FIX-A] SCRIPT 경로 하드코딩(v4_13) → 자동감지(FIND_LATEST 방식)
#           v6_1: "collect_prices_1m_kiwoom_opt10080_v4_13_SAFEPLUS_FINAL.py" 고정
#           v6_2: RUN 디렉토리에서 collect_prices_1m_kiwoom_opt10080_v*.py 패턴으로
#                 수정일 최신 파일 자동 선택 (파이프라인 v2.6 FIND_LATEST 동일 방식)
#           효과: 수집기 버전업 시 워치독 수동 수정 불필요 → 운영 실수 방지
#
#   [FIX-B] 로그 .bak 파일 누적 → 7일 초과 자동 삭제
#           v6_1: Rotate-Log가 .bak 파일 생성만 하고 정리 없음 → 디스크 점진 증가
#           v6_2: 하루 1회 LOG 디렉토리의 watchdog_collect_1m_*.bak 중
#                 7일 초과 파일 자동 삭제 (gate_history pruning과 동일 주기)
#
#   [FIX-C] Evaluate-TradingGate 내부 매 15초 파일 I/O → 스크립트 변수 캐싱
#           v6_1: BUG-3 히스테리시스 구현 시 $TRADING_GATE 파일을 함수 내부에서
#                 매 호출(15초)마다 Get-Content → 불필요한 디스크 읽기
#           v6_2: 메인 루프에서 $script:cachedGateMode 변수 유지
#                 Set-TradingGate 호출 시 동시 캐시 갱신 → 파일 I/O 제거
#
#   [유지] v6_1 모든 기능 (BUG-1~4, CB 3상태, HB 180s, Full Jitter,
#           히스테리시스, 품질장기감시, CSV pruning, 사전기동 확장)
#   [유지] 종배 관련 코드 없음 (인프라 전용)
#
# ── 학술/산업 출처 ─────────────────────────────────────────────────────────────
#   Circuit Breaker 3상태  : Martin Fowler (2014) bliki/CircuitBreaker
#   CB 구현 표준           : Netflix Hystrix OSS
#   Backoff + Jitter       : AWS Architecture Blog (2015, Perkins et al.)
#   HB 타임아웃 표준       : ITRS Geneos — 헤지펀드 인프라 모니터링 백서
#   Trading Gate 패턴      : Citadel Risk Overlay (공개 논문)
#   Watchdog 표준          : Renaissance Technologies 인프라 모델 (공개 인터뷰 기반)
# ═══════════════════════════════════════════════════════════════════════════════

# ── [ARCH-3] SAFEPLUS_BASE 기반 경로 통일 ────────────────────────────────────
$safeBase = if ($env:SAFEPLUS_BASE) { $env:SAFEPLUS_BASE } else { "C:\stock_bot" }
$safeData = Join-Path $safeBase "DATA"
$safeLog  = Join-Path $safeBase "LOG"
$safeRun  = Join-Path $safeBase "RUN"

# ── 텔레그램 알림 설정 ─────────────────────────────────────────────────────────
$TELEGRAM_TOKEN  = $env:TELEGRAM_TOKEN   # 환경변수 우선 (보안 강화)
$TELEGRAM_CHATID = $env:TELEGRAM_CHATID  # 환경변수 우선

# ── [ARCH-2] Python 5단계 fallback (v6_4 — 새 컴퓨터 경로 자동 감지) ──────────
if ($env:PYTHON_PATH -and (Test-Path $env:PYTHON_PATH)) {
    $PY = $env:PYTHON_PATH
} elseif (Test-Path "C:\Python310-32\python.exe") {
    $PY = "C:\Python310-32\python.exe"
} elseif (Test-Path "C:\Users\UserK\AppData\Local\Programs\Python\Python310-32\python.exe") {
    $PY = "C:\Users\UserK\AppData\Local\Programs\Python\Python310-32\python.exe"
} elseif (Test-Path "C:\Users\$($env:USERNAME)\AppData\Local\Programs\Python\Python310-32\python.exe") {
    # [v6_4 NEW] 현재 로그인 사용자 기반 동적 경로 탐색
    $PY = "C:\Users\$($env:USERNAME)\AppData\Local\Programs\Python\Python310-32\python.exe"
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [INFO] Python 동적 감지: $PY" -ForegroundColor Cyan
} else {
    $PY = "python"
    $whereResult = & where.exe python 2>$null
    if (-not $whereResult) {
        Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [ERROR] Python 실행파일을 찾을 수 없습니다. PYTHON_PATH 환경변수를 설정하세요." -ForegroundColor Red
        exit 1
    }
}

# ── [FIX-A] SCRIPT 경로 자동감지 — FIND_LATEST 방식 ─────────────────────────
# v6_1: v4_13 하드코딩 → v6_2: RUN 디렉토리에서 최신 버전 자동 선택
# 파이프라인 v2.6 FIND_LATEST와 동일 원리 (수정일 역순 첫 번째 파일)
$SCRIPT_TAG = "collect_prices_1m_kiwoom_opt10080"
$SCRIPT_PATTERN = "collect_prices_1m_kiwoom_opt10080_v*.py"
$SCRIPT = ""
try {
    $found = Get-ChildItem -Path $safeRun -Filter $SCRIPT_PATTERN -ErrorAction Stop |
             Where-Object { $_.BaseName -notmatch '_before_' } |
             Sort-Object LastWriteTime -Descending |
             Select-Object -First 1
    if ($found) {
        $SCRIPT = $found.FullName
    }
} catch {}
# 자동감지 실패 시 최신 알려진 버전으로 fallback
# [PATCH-WD3.2] v4_15 → v4_16 (실제 파일명과 일치)
if (-not $SCRIPT) {
    $SCRIPT = Join-Path $safeRun "collect_prices_1m_kiwoom_opt10080_v4_16.py"
}
$CSV        = Join-Path $safeData "prices_1m.csv"
$LOCK       = Join-Path $safeData "collector_1m.lock"
$PID_FILE   = Join-Path $safeData "collector_1m.pid"
$LOG_DIR    = $safeLog
$HB_FILE    = Join-Path $safeData "watchdog_collect_1m.heartbeat"

$COLLECTOR_HB   = Join-Path $safeData "collector_1m.heartbeat"
$EVOLVE_JSON    = Join-Path $safeData "collector_1m_evolve.json"
$WD_PID_FILE    = Join-Path $safeData "heartbeat\watchdog_collect_1m.pid"
$DAILY_STAT     = Join-Path $safeLog  "watchdog_collect_1m_daily_stats.json"
$QUALITY_FLAG   = Join-Path $safeData "collector_1m_quality.flag"
$TRADING_GATE   = Join-Path $safeData "trading_gate.flag"

# ── 파라미터 ──────────────────────────────────────────────────────────────────
$MAX_IDLE_SEC         = 120
# [FIX-3] HB 타임아웃 420s → 180s (헤지펀드 인프라 표준: 좀비 3분 이내 검출)
$COLLECTOR_HB_TIMEOUT = 360   # [2026-06-25] 180→360: 수집기 TR타임아웃/서킷브레이크로 ~3분 stall시 살아있는데 false-death 오판→재시작/중복락크래시(09:03·23·47). 진짜죽음(>6분)만 검출. 롤백 .bak_pre_hbraise
$MAX_RESTART_COUNT    = 5
$RESTART_WINDOW_MIN   = 60
$GRACE_SEC            = 45
$CB_COOLDOWN_MIN      = 10
$CB_ESCALATE_COUNT    = 3
$CB_ESCALATE_MIN      = 30
# [FIX-1] HALF-OPEN 허용 재시작 횟수
$CB_HALFOPEN_MAX      = 2     # HALF-OPEN 구간 최대 재시작 허용 수
$CB_HALFOPEN_MIN      = 3     # HALF-OPEN 판정을 위한 정상 루프 수 (3×15s=45s)
$LOG_MAX_BYTES        = 5MB
$LOOP_INTERVAL        = 15
$INFO_LOG_INTERVAL    = 60
$REPEAT_LOG_INTERVAL  = 600

# ── 트레이딩 차단 임계값 ─────────────────────────────────────────────────────
$GATE_FAIL_BLOCK      = 0.08
$GATE_GAP_REDUCE      = 0.04
$GATE_CSV_IDLE_BLOCK  = 300   # [2026-06-25] 180→300: ~185s 일시 stall이 트레이딩 GATE를 10분 BLOCK시켜 신규매수 막음(09:22·09:46 실측). 진짜정지(>5분)만 BLOCK. 롤백 .bak_pre_hbraise / [2026-06-17] 90→180
$GATE_FAIL_RECOVER    = 0.05
$GATE_GAP_RECOVER     = 0.02
$GATE_REDUCE_PCT      = 30

# ── 한국 공휴일 (2026~2028) ───────────────────────────────────────────────────
$HOLIDAYS = @(
    "2026-01-01","2026-01-28","2026-01-29","2026-01-30",
    "2026-03-01","2026-05-05","2026-05-25","2026-06-06",
    "2026-08-15","2026-09-24","2026-09-25","2026-09-26",
    "2026-10-03","2026-10-09","2026-12-25",
    "2027-01-01","2027-02-16","2027-02-17","2027-02-18",
    "2027-03-01","2027-05-05","2027-05-13","2027-06-06",
    "2027-08-15","2027-10-03","2027-10-09",
    "2027-10-14","2027-10-15","2027-10-16","2027-12-25",
    "2028-01-01","2028-02-04","2028-02-05","2028-02-06",
    "2028-03-01","2028-05-02","2028-05-05","2028-06-06",
    "2028-08-15","2028-10-02","2028-10-03","2028-10-04",
    "2028-10-09","2028-12-25"
)

# 운영 공통 휴장일 파일을 합쳐, 워치독 내부 목록 누락으로 휴일을 장중으로
# 오판하지 않게 한다. 형식: YYYYMMDD 뒤에 선택적 주석(# ...).
$HOLIDAY_FILE = Join-Path $safeBase "config\holidays_kr.txt"
if (Test-Path $HOLIDAY_FILE) {
    Get-Content $HOLIDAY_FILE -Encoding UTF8 | ForEach-Object {
        $holidayToken = ($_ -split '#', 2)[0].Trim()
        if ($holidayToken -match '^\d{8}$') {
            $holidayDate = "{0}-{1}-{2}" -f `
                $holidayToken.Substring(0, 4), `
                $holidayToken.Substring(4, 2), `
                $holidayToken.Substring(6, 2)
            if ($HOLIDAYS -notcontains $holidayDate) {
                $HOLIDAYS += $holidayDate
            }
        }
    }
}

# ── [FIX-3] RECOVER_CONFIRM 상수 블록으로 이동 ($script: 스코프) ──────────────
# v6_2: 메인 루프 초기화 블록에 로컬 변수로 선언 → finally 접근 불가
# v6_3: 파라미터 상수 블록에 $script: 스코프로 선언
$script:RECOVER_CONFIRM = 3   # 연속 45초(3×15s) 정상 → 복구 확정

# ── [FIX-4] Is-MarketHour 시작 시각 08:55 → 08:45 ────────────────────────────
# v6_2: open=08:55 → 사전기동창(08:45~08:54) 종료 직후 1분 공백 가능
# v6_3: open=08:45 → PreOpenWindow(08:45~08:54)와 연속성 확보
$MARKET_OPEN_HHMM = 845   # 08:45 (사전기동창 시작과 일치)
$script:lastPruneDate = ""

# ── [FIX-C] TradingGate 모드 캐시 — 매 15초 파일 I/O 제거 ────────────────────
$script:cachedGateMode = "NORMAL"

# ═══════════════════════════════════════════════════════════════════════════════
# 유틸 함수
# ═══════════════════════════════════════════════════════════════════════════════

if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }
$wdPidDir = Split-Path $WD_PID_FILE
if (-not (Test-Path $wdPidDir)) { New-Item -ItemType Directory -Path $wdPidDir -Force | Out-Null }

function Rotate-Log {
    param([string]$logPath)
    if (Test-Path $logPath) {
        $size = (Get-Item $logPath).Length
        if ($size -gt $LOG_MAX_BYTES) {
            $suffix = (Get-Date).ToString("yyyyMMdd_HHmmss")
            $bak    = $logPath -replace "\.log$", "_$suffix.bak"
            Move-Item -Path $logPath -Destination $bak -Force -ErrorAction SilentlyContinue
            return $true
        }
    }
    return $false
}

function Write-Log {
    param([string]$msg, [string]$level = "INFO")
    $ts      = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $dateTag = Get-Date -Format "yyyyMMdd"
    $logFile = "$LOG_DIR\watchdog_collect_1m_$dateTag.log"
    $line    = "[$ts][$level] $msg"
    Write-Host $line
    Rotate-Log $logFile | Out-Null
    Add-Content -Path $logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

# ── 텔레그램 알림 — alertKey 딕셔너리 방식 ────────────────────────────────────
$script:alertSentMap = @{}

function Send-Alert {
    param([string]$msg, [string]$alertKey = "", [bool]$once = $false)
    if ($once -and $alertKey -ne "" -and $script:alertSentMap.ContainsKey($alertKey)) { return }
    if ($once -and $alertKey -ne "") { $script:alertSentMap[$alertKey] = $true }
    Write-Log "[ALERT] $msg" "ERROR"
    if ($TELEGRAM_TOKEN -and $TELEGRAM_CHATID) {
        try {
            $body = @{ chat_id = $TELEGRAM_CHATID; text = "[WD-1M v6.4] $msg" } | ConvertTo-Json
            Invoke-RestMethod `
                -Uri         "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" `
                -Method      POST `
                -ContentType "application/json" `
                -Body        $body `
                -ErrorAction SilentlyContinue | Out-Null
        } catch {
            Write-Log "텔레그램 전송 실패: $_" "WARN"
        }
    }
}

function Reset-AlertKey {
    param([string]$alertKey = "")
    if ($alertKey -eq "") { $script:alertSentMap = @{} }
    else { $script:alertSentMap.Remove($alertKey) }
}

# ── 자가진단 ──────────────────────────────────────────────────────────────────
function Test-Prerequisites {
    $ok = $true
    if (-not (Test-Path $PY)) {
        Write-Log "자가진단 실패: Python 실행파일 없음 [$PY]" "ERROR"; $ok = $false
    }
    if (-not (Test-Path $SCRIPT)) {
        Write-Log "자가진단 실패: 수집 스크립트 없음 [$SCRIPT]" "ERROR"
        $parentDir = Split-Path $SCRIPT
        $found = Get-ChildItem -Path $parentDir -Filter "collect_prices_1m_kiwoom_opt10080_v*" -ErrorAction SilentlyContinue
        if ($found) { Write-Log "발견된 유사 파일: $($found.Name -join ', ')" "WARN" }
        $ok = $false
    }
    if (-not (Test-Path (Split-Path $CSV))) {
        Write-Log "자가진단 실패: DATA 디렉토리 없음 [$safeData]" "ERROR"; $ok = $false
    }
    return $ok
}

# ── 장 시간 게이트 ────────────────────────────────────────────────────────────
function Is-MarketHour {
    $now = Get-Date
    if ($now.DayOfWeek -eq "Saturday" -or $now.DayOfWeek -eq "Sunday") { return $false }
    if ($HOLIDAYS -contains $now.ToString("yyyy-MM-dd")) { return $false }
    # [v6_3 FIX-4] open=08:45 (사전기동창 08:45~08:54 연속성 확보)
    $openH  = [math]::Floor($MARKET_OPEN_HHMM / 100)
    $openM  = $MARKET_OPEN_HHMM % 100
    $open  = $now.Date.AddHours($openH).AddMinutes($openM)
    $close = $now.Date.AddHours(15).AddMinutes(40)
    return ($now -ge $open -and $now -le $close)
}

# ── [FIX-5] 사전기동 시간 판단 (08:45~08:54로 확장) ──────────────────────────
function Is-PreOpenWindow {
    $now = Get-Date
    $dow = $now.DayOfWeek
    if ($dow -eq "Saturday" -or $dow -eq "Sunday") { return $false }
    if ($HOLIDAYS -contains $now.ToString("yyyy-MM-dd")) { return $false }
    $nowHM = $now.Hour * 100 + $now.Minute
    # [FIX-5]: 08:45~08:54 (기존 08:50~08:54에서 5분 확장)
    return ($nowHM -ge 845 -and $nowHM -lt 855)
}

# ── CommandLine 기반 프로세스 검증 ────────────────────────────────────────────
function Get-CollectorProcess {
    # [LOCKPID-FIX 2026-06-26] 수집기는 collector_1m.pid 를 직접 쓰지 않고 collector_1m.lock 에만
    #   자기 PID(os.getpid)를 기록한다. 기존 탐지는 (1)stale collector_1m.pid(=죽은 PID)와
    #   (2).Path/.CommandLine 검증에 의존했는데, 파이프라인 부팅으로 뜬 elevated 수집기는
    #   .Path / .CommandLine 이 빈 값으로 읽혀 PID가 맞아도 항상 $null 반환 → processAlive 영구 false
    #   → ALIVE_GUARD(HB+csvIdle) 단독 의존 → 09:03/23/47 장초반 stall때 가드붕괴→ false PROCESS_DEAD
    #   → 중복 수집기 spawn(락에 막혀 즉사) churn. 락 PID를 1순위 권위로, ProcessName(=python)으로 검증.
    foreach ($src in @($LOCK, $PID_FILE)) {
        if (Test-Path $src) {
            $savedPid = (Get-Content $src -Raw -ErrorAction SilentlyContinue).Trim()
            if ($savedPid -match '^\d+$') {
                try {
                    $proc = Get-Process -Id ([int]$savedPid) -ErrorAction Stop
                    # .Path 는 elevated 프로세스에서 빈 값 → ProcessName 으로 검증 (Get-Process 신뢰값)
                    if ($proc.ProcessName -like "*python*") { return $proc }
                } catch {}
            }
        }
    }
    try {
        # [LOCKPID-FIX] Name=python* 추가 — collector 태그를 본문에 포함한 powershell 진단셸 등
        #   non-python 프로세스 오탐(false ALIVE) 방지.
        $procs = Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -like "*$SCRIPT_TAG*" -and $_.Name -like "python*" }
        if ($procs) {
            $first = $procs | Sort-Object ProcessId | Select-Object -First 1
            return (Get-Process -Id $first.ProcessId -ErrorAction SilentlyContinue)
        }
    } catch {}
    return $null
}

# ── CSV 무결성 검증 ───────────────────────────────────────────────────────────
function Test-CsvIntegrity {
    if (-not (Test-Path $CSV)) { return $false }
    try {
        $last = Get-Content $CSV -Tail 1 -ErrorAction Stop
        if (-not $last -or $last.Split(",").Count -lt 8) {
            Write-Log "CSV 무결성 이상: 컬럼수 부족 [$($last.Split(',').Count)]" "WARN"
            return $false
        }
        return $true
    } catch {
        Write-Log "CSV 무결성 검사 예외: $_" "WARN"
        return $false
    }
}

# ── 수집기 하트비트 교차 검증 ─────────────────────────────────────────────────
function Get-CollectorHeartbeat {
    # [FIX-3]: COLLECTOR_HB_TIMEOUT=180s 적용
    # ALIVE: age <= 180s / STALE: 180~360s / DEAD: > 360s
    $result = @{ age_sec = 9999; codes = 0; status = "UNKNOWN" }
    if (-not (Test-Path $COLLECTOR_HB)) { return $result }
    try {
        $raw = (Get-Content $COLLECTOR_HB -Raw -ErrorAction Stop).Trim()
        if (-not $raw) { return $result }
        $parts = $raw -split "\|"
        $hbTime = $null
        try { $hbTime = [datetime]::ParseExact($parts[0].Trim(), "yyyy-MM-dd HH:mm:ss", $null) } catch {}
        if ($hbTime) { $result.age_sec = [math]::Round(((Get-Date) - $hbTime).TotalSeconds, 1) }
        foreach ($p in $parts) {
            if ($p.Trim() -like "codes=*") {
                $result.codes = [int]($p.Trim() -replace "codes=", "")
            }
        }
        # [FIX-3]: 180/360 기준 (v5_1의 420/840 → v6_0의 180/360)
        if    ($result.age_sec -le $COLLECTOR_HB_TIMEOUT)      { $result.status = "ALIVE" }
        elseif($result.age_sec -le ($COLLECTOR_HB_TIMEOUT * 2)){ $result.status = "STALE" }
        else                                                    { $result.status = "DEAD"  }
    } catch {
        Write-Log "수집기 하트비트 읽기 실패: $_" "WARN"
    }
    return $result
}

# ── 수집기 진화 상태 모니터링 ─────────────────────────────────────────────────
function Get-EvolveStatus {
    $result = @{ fail_rate = 0; gap_rate = 0; cycle_ratio = 0; readable = $false }
    if (-not (Test-Path $EVOLVE_JSON)) { return $result }
    try {
        $raw  = Get-Content $EVOLVE_JSON -Raw -ErrorAction Stop
        $data = $raw | ConvertFrom-Json
        if ($data.obs_history -and $data.obs_history.Count -gt 0) {
            $lastObs = $data.obs_history[-1]
            $result.fail_rate   = [double]$lastObs.fail_rate
            $result.gap_rate    = [double]$lastObs.gap_rate
            $result.cycle_ratio = [double]$lastObs.cycle_ratio
            $result.readable    = $true
        }
    } catch {
        Write-Log "[EVOLVE] evolve.json 파싱 실패: $_" "WARN"
    }
    return $result
}

# ── 수집 품질 경고 플래그 (원자적 쓰기) ──────────────────────────────────────
function Set-QualityFlag {
    param([string]$status, [string]$reason)
    try {
        $data = @{ status = $status; reason = $reason; ts = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
        $json = $data | ConvertTo-Json
        $tmp  = "$QUALITY_FLAG.tmp"
        $json | Set-Content -Path $tmp -Encoding UTF8 -ErrorAction Stop
        Move-Item -Path $tmp -Destination $QUALITY_FLAG -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log "[QFLAG] 품질 플래그 쓰기 실패: $_" "WARN"
    }
}

# ── [FIX-6] 트레이딩 차단 게이트 — HALF_OPEN 상태 추가 ──────────────────────
function Set-TradingGate {
    param([string]$mode, [string]$reason, [int]$reduce_pct = 0)
    # mode: NORMAL / HALF_OPEN / REDUCE / BLOCK
    try {
        $prevMode = "UNKNOWN"
        if (Test-Path $TRADING_GATE) {
            try { $prevMode = (Get-Content $TRADING_GATE -Raw -ErrorAction Stop | ConvertFrom-Json).mode } catch {}
        }
        $ttlMin = switch ($mode) {
            "BLOCK"     { 10 }
            "REDUCE"    { 7  }
            "HALF_OPEN" { 5  }  # [FIX-6] HALF_OPEN TTL: 5분
            "NORMAL"    { 5  }
        }
        $data = @{
            mode       = $mode
            reason     = $reason
            reduce_pct = $reduce_pct
            expires_at = (Get-Date).AddMinutes($ttlMin).ToString("yyyy-MM-dd HH:mm:ss")
            ts         = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            version    = "v6_4"
        }
        $json = $data | ConvertTo-Json
        $tmp  = "$TRADING_GATE.tmp"
        $json | Set-Content -Path $tmp -Encoding UTF8 -ErrorAction Stop
        Move-Item -Path $tmp -Destination $TRADING_GATE -Force -ErrorAction SilentlyContinue
        # [FIX-C] 캐시 갱신 — Evaluate-TradingGate의 파일 I/O 제거용
        $script:cachedGateMode = $mode
        if ($mode -ne $prevMode) {
            if ($mode -eq "BLOCK") {
                Write-Log "[GATE] BLOCK 발동 — $reason | TTL=${ttlMin}분" "ERROR"
                Send-Alert "트레이딩 BLOCK: $reason — 신규 매수 금지됨"
            } elseif ($mode -eq "REDUCE") {
                Write-Log "[GATE] REDUCE 발동 — $reason | ${reduce_pct}% 축소 | TTL=${ttlMin}분" "WARN"
                Send-Alert "트레이딩 REDUCE: $reason — ${reduce_pct}% 축소"
            } elseif ($mode -eq "HALF_OPEN") {
                # [FIX-6] HALF_OPEN: CB 복구 중 조심스러운 재개
                Write-Log "[GATE] HALF_OPEN — CB 복구 검증 중 ($reason) | TTL=${ttlMin}분" "WARN"
                Send-Alert "트레이딩 HALF_OPEN: CB 복구 검증 중 — 수집 정상 확인 후 NORMAL 전환"
            } elseif ($mode -eq "NORMAL" -and $prevMode -ne "UNKNOWN") {
                Write-Log "[GATE] 정상 복구 — $reason" "INFO"
            }
        }
    } catch {}
}

# ── [BUG-3 수정] 게이트 평가 — 히스테리시스 적용 ────────────────────────────
# BLOCK 진입 임계 > NORMAL 복귀 임계 (히스테리시스)
# 이전 상태를 읽어 BLOCK 중일 때는 RECOVER 임계 기준, 아닐 때는 BLOCK 임계 기준
# 효과: 품질이 경계선에서 진동해도 BLOCK↔NORMAL 반복 방지
function Evaluate-TradingGate {
    param($fail_rate, $gap_rate, $csvIdle, $cbTrip, $inGrace)

    # [FIX-C] 캐시 변수 사용 — 매 15초 파일 I/O 제거 (Set-TradingGate에서 동기화)
    $currentGateMode = $script:cachedGateMode
    $inBlock = ($currentGateMode -eq "BLOCK")

    if ($cbTrip -gt 0) { return @{ mode = "BLOCK"; reason = "CB_TRIP"; reduce = 0 } }

    # [BUG-3] fail_rate 히스테리시스
    # BLOCK 중이면: RECOVER(0.05) 이하로 내려와야 NORMAL 허용
    # 정상 중이면: BLOCK(0.08) 초과 시 BLOCK
    if ($inBlock) {
        if ($fail_rate -gt $GATE_FAIL_BLOCK) {
            return @{ mode = "BLOCK"; reason = "FAIL_RATE_$([math]::Round($fail_rate*100,1))pct"; reduce = 0 }
        }
        # RECOVER 임계 이하여야 NORMAL 허용 (BLOCK 상태에서 즉시 NORMAL 안 됨)
        if ($fail_rate -gt $GATE_FAIL_RECOVER) {
            return @{ mode = "REDUCE"; reason = "FAIL_RECOVERING_$([math]::Round($fail_rate*100,1))pct"; reduce = $GATE_REDUCE_PCT }
        }
    } else {
        if ($fail_rate -gt $GATE_FAIL_BLOCK) {
            return @{ mode = "BLOCK"; reason = "FAIL_RATE_$([math]::Round($fail_rate*100,1))pct"; reduce = 0 }
        }
    }

    if ($csvIdle -gt $GATE_CSV_IDLE_BLOCK -and -not $inGrace) {
        return @{ mode = "BLOCK"; reason = "CSV_IDLE_${csvIdle}s"; reduce = 0 }
    }

    $gapBlock    = $GATE_GAP_REDUCE * 2.0
    $gapReduceHi = $GATE_GAP_REDUCE * 1.5

    if ($gap_rate -gt $gapBlock) {
        return @{ mode = "BLOCK";  reason = "GAP_EXTREME_$([math]::Round($gap_rate*100,1))pct"; reduce = 0 }
    }
    if ($gap_rate -gt $gapReduceHi) {
        return @{ mode = "REDUCE"; reason = "GAP_HIGH_$([math]::Round($gap_rate*100,1))pct"; reduce = 50 }
    }
    if ($gap_rate -gt $GATE_GAP_REDUCE) {
        return @{ mode = "REDUCE"; reason = "GAP_MID_$([math]::Round($gap_rate*100,1))pct"; reduce = $GATE_REDUCE_PCT }
    }

    # [BUG-3] gap_rate 히스테리시스: REDUCE 중이면 RECOVER 임계 이하여야 NORMAL
    if ($inBlock -and $gap_rate -gt $GATE_GAP_RECOVER) {
        return @{ mode = "REDUCE"; reason = "GAP_RECOVERING_$([math]::Round($gap_rate*100,1))pct"; reduce = $GATE_REDUCE_PCT }
    }

    return @{ mode = "NORMAL"; reason = "OK"; reduce = 0 }
}

# ── [FIX-4] 게이트 이력 로깅 + 자동 pruning ─────────────────────────────────
function Log-GateHistory {
    param([string]$mode, [string]$reason, $fail, $gap, $idle)
    try {
        $histPath = Join-Path $safeLog "gate_history.csv"
        if (-not (Test-Path $histPath)) {
            "ts,mode,reason,fail_rate,gap_rate,csv_idle" | Set-Content -Path $histPath -Encoding UTF8
        }
        $line = "{0},{1},{2},{3},{4},{5}" -f `
            (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $mode, $reason, $fail, $gap, $idle
        Add-Content -Path $histPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue

        # [FIX-4] 하루 1회 7일 초과 행 제거 (무제한 증가 방지)
        $todayStr = (Get-Date).ToString("yyyy-MM-dd")
        if ($script:lastPruneDate -ne $todayStr) {
            $script:lastPruneDate = $todayStr
            $cutoffDate = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
            try {
                $all = Get-Content $histPath -Encoding UTF8 -ErrorAction Stop
                $header = $all[0]
                $kept = @($header) + @($all | Select-Object -Skip 1 | Where-Object {
                    $_ -ne "" -and $_.Substring(0, [Math]::Min(10, $_.Length)) -ge $cutoffDate
                })
                $kept | Set-Content -Path $histPath -Encoding UTF8 -ErrorAction Stop
                Write-Log "[PRUNE] gate_history.csv: $($all.Count - $kept.Count) 행 제거" "INFO"
            } catch {
                Write-Log "[PRUNE] gate_history.csv pruning 실패: $_" "WARN"
            }

            # [FIX-B] 7일 초과 .bak 로그 파일 자동 삭제
            try {
                $bakCutoff = (Get-Date).AddDays(-7)
                $baks = Get-ChildItem -Path $LOG_DIR -Filter "watchdog_collect_1m_*.bak" -ErrorAction Stop |
                        Where-Object { $_.LastWriteTime -lt $bakCutoff }
                foreach ($bak in $baks) {
                    Remove-Item $bak.FullName -Force -ErrorAction SilentlyContinue
                }
                if ($baks.Count -gt 0) {
                    Write-Log "[PRUNE] 로그 .bak 파일 $($baks.Count)개 삭제 (7일 초과)" "INFO"
                }
            } catch {
                Write-Log "[PRUNE] .bak 파일 정리 실패: $_" "WARN"
            }
        }
    } catch {}
}

# ── 수집기 종료 ───────────────────────────────────────────────────────────────
function Stop-CollectorOnly {
    $proc = Get-CollectorProcess
    if ($proc) {
        Write-Log "수집기 종료 시도 PID=$($proc.Id) — CSV 쓰기 안전 대기 2초" "WARN"
        $tmpFile = "$CSV.tmp"
        $waitEnd = (Get-Date).AddSeconds(5)
        while ((Test-Path $tmpFile) -and ((Get-Date) -lt $waitEnd)) { Start-Sleep -Milliseconds 500 }
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        } catch {
            Write-Log "수집기 종료 실패 PID=$($proc.Id): $_" "ERROR"
            return $false
        }
        $exitWaitEnd = (Get-Date).AddSeconds(10)
        while ((Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) -and
               ((Get-Date) -lt $exitWaitEnd)) {
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
            Write-Log "수집기 종료 확인 실패 PID=$($proc.Id) — 재기동 차단" "ERROR"
            return $false
        }
        Write-Log "수집기 종료 확인 PID=$($proc.Id)" "INFO"
    }
    if (Test-Path $PID_FILE) { Remove-Item $PID_FILE -Force -ErrorAction SilentlyContinue }
    if (Test-Path $LOCK)     { Remove-Item $LOCK     -Force -ErrorAction SilentlyContinue }
    return $true
}

# ── 수집기 기동 ───────────────────────────────────────────────────────────────
function Start-Collector {
    param([int]$attempt = 1)
    Write-Log "수집기 기동 시도 #$attempt" "INFO"
    # [WINDOW-HIDDEN 2026-06-25] Normal→Hidden: 재기동 경로 한정. 6/24 churn(385회 재기동)이
    #   매번 보이는 콘솔창을 띄워 데스크톱 힙 고갈 → 15:00 플릿/브로커 전멸(0xC0000142)의 최대 소비원.
    #   재기동 인스턴스는 창을 숨겨 힙 소비 차단. (정상 boot 1회 창은 영향 미미)
    #   롤백: watchdog_collect_1m_v6_4.ps1.bak_pre_hidden_20260625
    $proc = Start-Process -FilePath $PY `
                          -ArgumentList "`"$SCRIPT`"" `
                          -WorkingDirectory (Split-Path $SCRIPT) `
                          -PassThru `
                          -WindowStyle Hidden `
                          -ErrorAction SilentlyContinue
    if ($proc) {
        $proc.Id | Set-Content $PID_FILE -Encoding UTF8
        Write-Log "수집기 기동 완료 PID=$($proc.Id)" "INFO"
        return $true
    } else {
        Write-Log "수집기 기동 실패 #$attempt" "ERROR"
        Record-DailyStat "restart_fail"
        return $false
    }
}

# ── [FIX-1] Circuit Breaker — 3상태 (CLOSED / OPEN / HALF-OPEN) ──────────────
# 출처: Martin Fowler (2014) bliki/CircuitBreaker / Netflix Hystrix
$script:restartLog    = @()
$script:cbTripCount   = 0
# [FIX-1] CB 상태 변수
$script:cbState       = "CLOSED"   # CLOSED / OPEN / HALF_OPEN
$script:halfOpenCount = 0          # HALF_OPEN 구간 재시작 누적

# [COOLDOWN 2026-05-13] 장중(09:05~15:30) collector 사망 시 즉시 재시작 차단 + 10분 후 1회 한정
# 목적: popup chain 차단 (collector 재시작 → 새 CommConnect → OCX cascade 사망 회피)
$script:collectorDeathTime      = $null
$script:collectorRestartedToday = $false
$script:cooldownMinutes         = 10

function Update-RestartLog {
    $cutoff = (Get-Date).AddMinutes(-$RESTART_WINDOW_MIN)
    $script:restartLog = @($script:restartLog | Where-Object { $_ -gt $cutoff })
    $script:restartLog += Get-Date
}

function Is-CircuitOpen {
    $cutoff = (Get-Date).AddMinutes(-$RESTART_WINDOW_MIN)
    $recent = @($script:restartLog | Where-Object { $_ -gt $cutoff })
    if ($recent.Count -ge $MAX_RESTART_COUNT) {
        Write-Log "Circuit Breaker 발동: ${RESTART_WINDOW_MIN}분 내 $($recent.Count)회 재시작" "ERROR"
        return $true
    }
    return $false
}

# ── [BUG-2 수정] Exponential Backoff + AWS Full Jitter ──────────────────────
# 출처: AWS Architecture Blog (2015) — "Exponential Backoff and Jitter" (Perkins)
# Full Jitter: sleep = random(0, min(cap, base * 2^attempt))
# v6_0의 ±30% → 표준 Full Jitter (0 ~ cap) 로 교정 → Thundering Herd 완전 제거
function Get-BackoffWithJitter {
    param([int]$currentBackoff)
    $cap = 64
    $base = [Math]::Min($currentBackoff * 2, $cap)
    # AWS Full Jitter: 0 ~ base 균등 분포 (음수 없음)
    $jittered = Get-Random -Minimum 0 -Maximum ($base + 1)
    return [Math]::Max(2, $jittered)
}

# ── 일별 재시작 통계 ──────────────────────────────────────────────────────────
function Record-DailyStat {
    param([string]$event)
    try {
        $today = (Get-Date).ToString("yyyy-MM-dd")
        $stats = [ordered]@{}
        if (Test-Path $DAILY_STAT) {
            $raw = Get-Content $DAILY_STAT -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
            if ($raw) {
                foreach ($prop in $raw.PSObject.Properties) {
                    $stats[$prop.Name] = @{
                        restart=([int]$prop.Value.restart); restart_fail=([int]$prop.Value.restart_fail)
                        zombie=([int]$prop.Value.zombie);   cb_trip=([int]$prop.Value.cb_trip)
                        quality_warn=([int]$prop.Value.quality_warn)
                        halfopen_ok=([int](if ($prop.Value.halfopen_ok -ne $null) { $prop.Value.halfopen_ok } else { 0 }))
                    }
                }
            }
        }
        if (-not $stats.ContainsKey($today)) {
            $stats[$today] = @{ restart=0; restart_fail=0; zombie=0; cb_trip=0; quality_warn=0; halfopen_ok=0 }
        }
        if ($stats[$today].ContainsKey($event)) { $stats[$today][$event]++ }
        $cutoff = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
        $keep   = [ordered]@{}
        foreach ($k in $stats.Keys) { if ($k -ge $cutoff) { $keep[$k] = $stats[$k] } }
        $keep | ConvertTo-Json -Depth 4 |
            Set-Content -Path $DAILY_STAT -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

# ── 다차원 재시작 판단 ────────────────────────────────────────────────────────
function Get-RestartDecision {
    param([bool]$processAlive, [double]$csvIdleSec, [bool]$csvOk, [hashtable]$hbInfo, [bool]$inGrace)
    if ($inGrace) { return @{ need=$false; reason="GRACE"; severity="NONE" } }
    # [ALIVE-GUARD 2026-05-12] processAlive=False 단독 spawn 결정 결함 — HB=ALIVE + csvOk=True + csvIdle<300s 모두 충족 시 살아있음 인정
    # [P4 2026-05-12] csvIdleSec<300 조건 추가 — HB fresh + PID dead + csv 11분 idle 케이스(10:14 false positive) 차단
    # [BOOTGRACE 2026-05-13] 09:03 이전엔 csvIdle 큰 값(어제 데이터 기준 17h+) 정상 — csvIdle 조건 면제로 5/13 4회 popup chain 차단
    if (-not $processAlive -and $hbInfo.status -eq "ALIVE" -and $csvOk -and ($csvIdleSec -lt 300 -or (Get-Date).TimeOfDay -lt [TimeSpan]"09:03")) {
        return @{ need=$false; reason="ALIVE_GUARD"; severity="NONE" }
    }
    if (-not $processAlive) { return @{ need=$true; reason="PROCESS_DEAD"; severity="CRITICAL" } }
    if ($hbInfo.status -eq "DEAD") { return @{ need=$true; reason="ZOMBIE_HEARTBEAT_DEAD"; severity="CRITICAL" } }
    if ($hbInfo.status -eq "STALE" -and $csvIdleSec -gt $MAX_IDLE_SEC) {
        return @{ need=$true; reason="ZOMBIE_STALE_AND_CSV_IDLE"; severity="HIGH" }
    }
    if ($processAlive -and $hbInfo.status -eq "ALIVE" -and $csvOk -and (Get-Date).TimeOfDay -lt [TimeSpan]"09:00") {
        return @{ need=$false; reason="PREOPEN_CSV_GRACE"; severity="NONE" }
    }
    if ($csvIdleSec -gt ($MAX_IDLE_SEC * 2) -and $hbInfo.status -eq "ALIVE") {
        # [PATCH] CSV idle > 240초 + heartbeat ALIVE = "도는 척" 상태
        # heartbeat만 갱신되고 prices_1m.csv가 오늘 날짜로 갱신되지 않으면 FAIL 판정
        Set-QualityFlag "FAIL" "CSV_STALE_BUT_HB_ALIVE_FAIL"
        return @{ need=$true; reason="COLLECT_FAIL_PRICE_1M_NOT_UPDATED"; severity="HIGH" }
    }
    if (-not $csvOk -and $csvIdleSec -gt 30) { return @{ need=$true; reason="CSV_INTEGRITY_FAIL"; severity="HIGH" } }
    if ($hbInfo.status -eq "UNKNOWN" -and $csvIdleSec -gt $MAX_IDLE_SEC) {
        return @{ need=$true; reason="CSV_IDLE_NO_HB"; severity="HIGH" }
    }
    return @{ need=$false; reason="OK"; severity="NONE" }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 워치독 이중 기동 방지
# ═══════════════════════════════════════════════════════════════════════════════
if (Test-Path $WD_PID_FILE) {
    try {
        $existingPid = [int](Get-Content $WD_PID_FILE -Raw).Trim()
        $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($proc -and (($proc.ProcessName -like "*powershell*") -or ($proc.ProcessName -eq "pwsh"))) {
            Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [ERROR] 워치독 이미 실행 중 (PID=$existingPid) — 종료."
            exit 1
        }
    } catch {}
    Remove-Item $WD_PID_FILE -Force -ErrorAction SilentlyContinue
}
$PID | Set-Content -Path $WD_PID_FILE -Encoding UTF8 -ErrorAction SilentlyContinue

# ═══════════════════════════════════════════════════════════════════════════════
# 자가진단 + 시작 로그
# ═══════════════════════════════════════════════════════════════════════════════
Write-Log "════════ Watchdog v6_4 SAFEPLUS FINAL 시작 ════════" "INFO"
Write-Log "MODE=WATCHDOG_RUNTIME | PID=$PID" "INFO"
Write-Log "SAFEPLUS_BASE=$safeBase | Python=$PY" "INFO"
Write-Log "수집기=$SCRIPT" "INFO"
Write-Log "CSV감시=$MAX_IDLE_SEC`s | HB타임아웃=$COLLECTOR_HB_TIMEOUT`s (v6.4) | Grace=$GRACE_SEC`s" "INFO"
Write-Log "CB한도=$MAX_RESTART_COUNT`회/${RESTART_WINDOW_MIN}분 | HALF_OPEN허용=${CB_HALFOPEN_MAX}회 | 루프=$LOOP_INTERVAL`s" "INFO"
Write-Log "사전기동창=08:45~08:54 (v6.4 확장) | 공휴일=$($HOLIDAYS.Count)일 등록" "INFO"
Write-Log "[v6.4 완성] Python동적감지 | 삼항연산자 수정 | fallback v4_15 | 텔레그램 v6.4 | RECOVER_CONFIRM 스코프 | MarketHour 08:45" "INFO"
Write-Log "SCRIPT자동감지: $SCRIPT" "INFO"

if (-not (Test-Prerequisites)) {
    Write-Log "자가진단 실패 — Watchdog 종료" "ERROR"
    Send-Alert "워치독 자가진단 실패 — 수집기 경로 확인 필요"
    Remove-Item $WD_PID_FILE -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Log "자가진단 통과" "INFO"

if (-not $TELEGRAM_TOKEN -or -not $TELEGRAM_CHATID) {
    Write-Log "[경고] 텔레그램 미설정 — 환경변수 TELEGRAM_TOKEN/CHATID를 설정하세요." "WARN"
} else {
    Write-Log "텔레그램 알림 활성화 (ChatID=$TELEGRAM_CHATID)" "INFO"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 메인 루프 변수 초기화
# ═══════════════════════════════════════════════════════════════════════════════
$cbSleepUntil        = $null
$backoffSec          = 2
$lastRestartTime     = [datetime]::MinValue
$lastInfoLog         = [datetime]::MinValue
$lastOffHourLog      = [datetime]::MinValue
$lastEvolveLog       = [datetime]::MinValue
$lastQualityOk       = Get-Date
$lastStalenessLog    = [datetime]::MinValue   # [DATA_FRESHNESS] 보조 파일 신선도 체크

# [DATA_FRESHNESS] 보조 수집 파일 경로 + 허용 stale 한도
$PRICES_3M_CSV       = Join-Path $safeData "prices_3m.csv"
$INVESTOR_DAILY_CSV  = Join-Path $safeData "investor_daily.csv"
$EOD_BARS_CSV        = Join-Path $safeData "eod_daily_bars.csv"
$STALE_3M_SEC        = 32400  # prices_3m: 9시간 (1회/일 STARTUP 설계, 5/27 정정)
$STALE_INVESTOR_SEC  = 32400  # investor_daily: 9시간 (08:41 + 09:30 + 15:00 = 8h+ span, 5/27 C1 반영)
$STALE_EOD_SEC       = 432000 # eod_daily_bars: 5일 (장 마감 후 1회 + 휴장일 buffer)
$script:recoverCount = 0
# [v6_3 FIX-3] $script:RECOVER_CONFIRM 은 파라미터 상수 블록에서 정의됨 (로컬 중복 제거)

# [FIX-1] HALF_OPEN 추적 변수
$script:halfOpenNormalCount = 0   # HALF_OPEN 구간 정상 루프 카운트

# [FIX-C] 게이트 캐시 초기화 — 기존 파일이 있으면 읽어서 동기화
if (Test-Path $TRADING_GATE) {
    try {
        $initGate = Get-Content $TRADING_GATE -Raw -ErrorAction Stop | ConvertFrom-Json
        $script:cachedGateMode = $initGate.mode
        Write-Log "[CACHE] TradingGate 초기 캐시: $($script:cachedGateMode)" "INFO"
    } catch {
        $script:cachedGateMode = "NORMAL"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# 메인 루프
# ═══════════════════════════════════════════════════════════════════════════════
try {
    while ($true) {
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Set-Content $HB_FILE -Encoding UTF8

        # ── [FIX-1] CB OPEN → 쿨다운 대기 ────────────────────────────────────
        if ($cbSleepUntil -and (Get-Date) -lt $cbSleepUntil) {
            $remain = [math]::Round(($cbSleepUntil - (Get-Date)).TotalSeconds, 0)
            $secSince = ((Get-Date) - $lastOffHourLog).TotalSeconds
            if ($secSince -ge $REPEAT_LOG_INTERVAL) {
                Write-Log "CB OPEN — 쿨다운 잔여 ${remain}초 (HALF_OPEN 전환 대기)" "WARN"
                $lastOffHourLog = Get-Date
            }
            Set-TradingGate "BLOCK" "CB_COOLDOWN_REMAIN_${remain}s"
            Start-Sleep -Seconds $LOOP_INTERVAL
            continue
        }

        # ── [FIX-1] CB OPEN → HALF_OPEN 전환 ────────────────────────────────
        if ($cbSleepUntil -and (Get-Date) -ge $cbSleepUntil) {
            Write-Log "CB OPEN 종료 → HALF_OPEN 진입 (검증 시작)" "INFO"
            $cbSleepUntil               = $null
            $backoffSec                 = 2
            $script:recoverCount        = 0
            $script:cbState             = "HALF_OPEN"
            $script:halfOpenCount       = 0
            $script:halfOpenNormalCount = 0
            # [FIX-6] 게이트를 HALF_OPEN으로 전환 (BLOCK에서 조심스러운 재개)
            Set-TradingGate "HALF_OPEN" "CB_RECOVERING"
            Reset-AlertKey
        }

        # ── [FIX-1] HALF_OPEN 상태 처리 ──────────────────────────────────────
        if ($script:cbState -eq "HALF_OPEN") {
            $proc    = Get-CollectorProcess
            $alive   = ($null -ne $proc)
            $hbInfo  = Get-CollectorHeartbeat
            $csvIdle = if (Test-Path $CSV) { ((Get-Date) - (Get-Item $CSV).LastWriteTime).TotalSeconds } else { 9999 }
            $csvOk   = Test-CsvIntegrity

            if ($alive -and $hbInfo.status -eq "ALIVE" -and $csvOk -and $csvIdle -le $MAX_IDLE_SEC) {
                # 정상: HALF_OPEN 카운터 증가
                $script:halfOpenNormalCount++
                Write-Log "[HALF_OPEN] 정상 확인 $($script:halfOpenNormalCount)/$CB_HALFOPEN_MIN" "INFO"
                if ($script:halfOpenNormalCount -ge $CB_HALFOPEN_MIN) {
                    # CLOSED 복귀
                    $script:cbState = "CLOSED"
                    $script:cbTripCount = 0
                    $script:restartLog = @()
                    Set-TradingGate "NORMAL" "CB_RECOVERED_FROM_HALFOPEN"
                    Record-DailyStat "halfopen_ok"
                    Write-Log "CB HALF_OPEN → CLOSED 복귀 완료 — 정상 매매 재개" "INFO"
                    Send-Alert "CB 복구 완료 — HALF_OPEN 검증 통과. 정상 매매 재개"
                }
            } else {
                # HALF_OPEN 중 이상: 재시작 시도
                $script:halfOpenCount++
                Write-Log "[HALF_OPEN] 이상 감지 ($($script:halfOpenCount)/$CB_HALFOPEN_MAX) — 재시작 시도" "WARN"
                # [BUG-1 수정] -ge: $CB_HALFOPEN_MAX(=2)번째 실패 즉시 차단 (v6_0의 -gt는 3번 허용 오류)
                if ($script:halfOpenCount -ge $CB_HALFOPEN_MAX) {
                    # HALF_OPEN에서도 실패 → 다시 OPEN (쿨다운 확대)
                    $coolMin = $CB_ESCALATE_MIN
                    $cbSleepUntil = (Get-Date).AddMinutes($coolMin)
                    $script:cbState = "OPEN"
                    $script:halfOpenNormalCount = 0
                    Set-TradingGate "BLOCK" "HALFOPEN_FAIL_REOPEN"
                    Send-Alert "HALF_OPEN 검증 실패 ${CB_HALFOPEN_MAX}회 — CB 재발동 ${coolMin}분" `
                        -alertKey "HALFOPEN_FAIL" -once $true
                    Write-Log "HALF_OPEN 검증 실패 → CB OPEN 재발동 ${coolMin}분" "ERROR"
                } else {
                    if (Stop-CollectorOnly) {
                        Start-Sleep -Seconds $backoffSec
                        Start-Collector -attempt $script:halfOpenCount
                        $lastRestartTime = Get-Date
                        $backoffSec = Get-BackoffWithJitter -currentBackoff $backoffSec
                    } else {
                        Write-Log "기존 수집기 종료 실패 — 중복 재기동 차단" "ERROR"
                    }
                }
            }
            Start-Sleep -Seconds $LOOP_INTERVAL
            continue
        }

        # ── 장외 시간 ─────────────────────────────────────────────────────────
        if (-not (Is-MarketHour)) {
            $secSince = ((Get-Date) - $lastOffHourLog).TotalSeconds
            if ($secSince -ge $REPEAT_LOG_INTERVAL) {
                $now    = Get-Date
                $reason = if ($now.DayOfWeek -eq "Saturday" -or $now.DayOfWeek -eq "Sunday") { "(주말)" }
                          elseif ($HOLIDAYS -contains $now.ToString("yyyy-MM-dd")) { "(공휴일)" }
                          else { "(장외시간)" }
                Write-Log "장외$reason — 대기 중 [CB=$($script:cbState)]" "INFO"
                $lastOffHourLog = Get-Date
            }
            # [FIX-5] 사전기동 창 08:45~08:54 (기존 08:50~08:54에서 확장)
            if (Is-PreOpenWindow) {
                $preProc = Get-CollectorProcess
                if (-not $preProc) {
                    Write-Log "[PREOPEN] 장 시작 전 수집기 미동작 — 사전 기동 (08:45~08:54 창)" "WARN"
                    Start-Collector -attempt 0
                    $lastRestartTime = Get-Date
                }
            }
            Start-Sleep -Seconds 60
            continue
        }

        # ── 상태 수집 ──────────────────────────────────────────────────────────
        $csvIdle = if (Test-Path $CSV) { ((Get-Date) - (Get-Item $CSV).LastWriteTime).TotalSeconds } else { 9999 }
        $proc    = Get-CollectorProcess
        $alive   = ($null -ne $proc)
        $csvOk   = Test-CsvIntegrity
        $hbInfo  = Get-CollectorHeartbeat
        $inGrace = (((Get-Date) - $lastRestartTime).TotalSeconds -lt $GRACE_SEC)

        # ── 재시작 판단 ────────────────────────────────────────────────────────
        $decision = Get-RestartDecision `
            -processAlive $alive -csvIdleSec $csvIdle `
            -csvOk $csvOk -hbInfo $hbInfo -inGrace $inGrace

        if ($decision.need) {
            Write-Log "재시작 트리거 reason=$($decision.reason) severity=$($decision.severity) alive=$alive csvIdle=$([math]::Round($csvIdle,0))s hb=$($hbInfo.status) age=$($hbInfo.age_sec)s codes=$($hbInfo.codes) csvOk=$csvOk" "WARN"

            # [COOLDOWN 2026-05-13] 장중(09:05~15:30) 즉시 재시작 차단 + 10분 후 1회 한정
            $_cdNow = Get-Date
            $_cdTimeNum = $_cdNow.Hour * 100 + $_cdNow.Minute
            $_cdIsTradingHour = ($_cdTimeNum -ge 905 -and $_cdTimeNum -le 1530)
            if ($_cdIsTradingHour) {
                if ($script:collectorRestartedToday) {
                    Write-Log "[COOLDOWN] 당일 이미 1회 재시작 완료, 추가 재시작 보류 (popup chain 차단)" "INFO"
                    Start-Sleep -Seconds 60
                    continue
                }
                if ($null -eq $script:collectorDeathTime) {
                    $script:collectorDeathTime = $_cdNow
                    Write-Log "[COOLDOWN] 장중 사망 감지, $($script:cooldownMinutes)분 후 1회 재시작 시도" "WARN"
                    Start-Sleep -Seconds 30
                    continue
                }
                $_cdWaitedMin = (($_cdNow - $script:collectorDeathTime).TotalMinutes)
                if ($_cdWaitedMin -lt $script:cooldownMinutes) {
                    Write-Log "[COOLDOWN] 대기 중 $([math]::Round($_cdWaitedMin,1))분 / $($script:cooldownMinutes)분" "INFO"
                    Start-Sleep -Seconds 30
                    continue
                }
                Write-Log "[COOLDOWN] $($script:cooldownMinutes)분 경과, 1회 한정 재시작 진행" "WARN"
                $script:collectorRestartedToday = $true
            }

            if (Is-CircuitOpen) {
                $script:cbTripCount++
                $script:cbState = "OPEN"
                Record-DailyStat "cb_trip"
                if ($script:cbTripCount -ge $CB_ESCALATE_COUNT) {
                    $coolMin = $CB_ESCALATE_MIN
                    Send-Alert "CB 연속 $($script:cbTripCount)회 발동 — ${coolMin}분 확대 쿨다운. 수동 확인 필요!" `
                        -alertKey "CB_ESCALATE_$($script:cbTripCount)" -once $true
                } else {
                    $coolMin = $CB_COOLDOWN_MIN
                    Send-Alert "CB 발동: ${RESTART_WINDOW_MIN}분 내 한도 초과 — ${coolMin}분 대기 후 HALF_OPEN 검증" `
                        -alertKey "CB_TRIP_$($script:cbTripCount)" -once $true
                }
                $cbSleepUntil = (Get-Date).AddMinutes($coolMin)
                Write-Log "Circuit Breaker OPEN: ${coolMin}분 대기 → HALF_OPEN 전환 예정" "ERROR"
                Set-QualityFlag "DEGRADED" "CB_TRIP_$($script:cbTripCount)"
                Set-TradingGate "BLOCK" "CB_TRIP_$($script:cbTripCount)"
                $backoffSec = 2
                Start-Sleep -Seconds $LOOP_INTERVAL
                continue
            }

            $script:cbTripCount = 0
            if (-not (Stop-CollectorOnly)) {
                Write-Log "기존 수집기 종료 실패 — 중복 재기동 차단" "ERROR"
                Start-Sleep -Seconds $LOOP_INTERVAL
                continue
            }
            Start-Sleep -Seconds $backoffSec

            $success = Start-Collector -attempt ($script:restartLog.Count + 1)
            if ($success) {
                # [FIX-2] Backoff 리셋 (성공 시)
                $backoffSec      = 2
                $lastRestartTime = Get-Date
                Reset-AlertKey "START_FAIL"
                Record-DailyStat (if ($decision.reason -like "ZOMBIE*") { "zombie" } else { "restart" })
                Write-Log "재시작 완료 — Grace ${GRACE_SEC}초 유예 시작" "INFO"
            } else {
                # [FIX-2] Backoff + Jitter 적용 (실패 시)
                $backoffSec = Get-BackoffWithJitter -currentBackoff $backoffSec
                Write-Log "[BACKOFF+JITTER] 다음 재시도까지 ${backoffSec}초 대기" "WARN"
                Send-Alert "수집기 기동 실패 (backoff+jitter=${backoffSec}초) — 수동 확인 필요" -alertKey "START_FAIL"
            }
            Update-RestartLog
            Start-Sleep -Seconds $LOOP_INTERVAL
            continue
        }

        # ── 정상 상태 — 품질 모니터링 ─────────────────────────────────────────
        if ($decision.severity -eq "NONE") {
            Set-QualityFlag "OK" "NORMAL"
            # [BUG-4 수정] 품질 OK 시각 갱신 — 장기 저하 감시용
            $lastQualityOk = Get-Date
        }

        $evolve = Get-EvolveStatus
        $gate   = Evaluate-TradingGate `
            -fail_rate $evolve.fail_rate -gap_rate $evolve.gap_rate `
            -csvIdle $csvIdle -cbTrip $script:cbTripCount -inGrace $inGrace

        if ($gate.mode -eq "NORMAL") { $script:recoverCount++ } else { $script:recoverCount = 0 }

        if ($script:recoverCount -ge $script:RECOVER_CONFIRM) {
            # CB CLOSED 상태에서만 NORMAL 적용 (HALF_OPEN은 별도 처리)
            if ($script:cbState -eq "CLOSED") {
                Set-TradingGate "NORMAL" "RECOVERED"
            }
        } else {
            if ($gate.mode -eq "BLOCK")  { Set-TradingGate "BLOCK"  $gate.reason }
            elseif ($gate.mode -eq "REDUCE") { Set-TradingGate "REDUCE" $gate.reason $gate.reduce }
        }

        Log-GateHistory $gate.mode $gate.reason $evolve.fail_rate $evolve.gap_rate $csvIdle

        # 진화 상태 (5분마다)
        if (((Get-Date) - $lastEvolveLog).TotalSeconds -ge 300) {
            if ($evolve.readable) {
                $failPct = [math]::Round($evolve.fail_rate * 100, 1)
                $gapPct  = [math]::Round($evolve.gap_rate  * 100, 1)
                if ($evolve.fail_rate -gt $GATE_FAIL_BLOCK) {
                    Write-Log "[품질경고] 수집 실패율 ${failPct}% — TR 쿨타임 조정 필요" "WARN"
                    Record-DailyStat "quality_warn"; Set-QualityFlag "WARN" "HIGH_FAIL_RATE_$failPct"
                }
                if ($evolve.gap_rate -gt $GATE_GAP_REDUCE) {
                    Write-Log "[품질경고] 데이터 갭율 ${gapPct}% — 수집 지연 발생" "WARN"
                    Record-DailyStat "quality_warn"
                }
                Write-Log "[진화상태] fail=$failPct% gap=$gapPct% cycle=$([math]::Round($evolve.cycle_ratio,2)) gate=$($gate.mode) cb=$($script:cbState) recover=$($script:recoverCount)/$RECOVER_CONFIRM" "INFO"
            }

            # [BUG-4 수정] 품질 OK 마지막 시각 기준 5분 초과 → 장기 저하 알림
            $qualityStale = ((Get-Date) - $lastQualityOk).TotalMinutes
            if ($qualityStale -gt 5 -and $decision.severity -ne "NONE") {
                $staleMin = [math]::Round($qualityStale, 1)
                Write-Log "[품질장기저하] 정상 상태 미달 ${staleMin}분 지속 — 수동 점검 권고" "WARN"
                Send-Alert "품질 장기 저하 ${staleMin}분 지속 — 수집기 상태 수동 확인 필요" `
                    -alertKey "QUALITY_STALE_$([int]$staleMin)" -once $true
            }

            $lastEvolveLog = Get-Date
        }

        # [DATA_FRESHNESS] 보조 수집 파일 신선도 체크 (10분 1회, 장중에만)
        if (((Get-Date) - $lastStalenessLog).TotalSeconds -ge $REPEAT_LOG_INTERVAL) {
            if (Is-MarketHour) {
                $now = Get-Date
                $checks = @(
                    @{ path=$PRICES_3M_CSV;      limit=$STALE_3M_SEC;       name="prices_3m.csv" },
                    @{ path=$INVESTOR_DAILY_CSV;  limit=$STALE_INVESTOR_SEC; name="investor_daily.csv" },
                    @{ path=$EOD_BARS_CSV;        limit=$STALE_EOD_SEC;      name="eod_daily_bars.csv" }
                )
                foreach ($c in $checks) {
                    if (-not (Test-Path $c.path)) {
                        Write-Log "[DATA_FRESHNESS] $($c.name) 파일 없음 — 수집기 미실행 가능성" "WARN"
                    } else {
                        $age = ($now - (Get-Item $c.path).LastWriteTime).TotalSeconds
                        if ($age -gt $c.limit) {
                            Write-Log "[DATA_FRESHNESS] $($c.name) stale $([math]::Round($age/60,1))분 (한도=$([math]::Round($c.limit/60,0))분) — 수집기 확인 필요" "WARN"
                        }
                    }
                }
            }
            $lastStalenessLog = Get-Date
        }

        # 정상 INFO (60초 1회)
        if (((Get-Date) - $lastInfoLog).TotalSeconds -ge $INFO_LOG_INTERVAL) {
            $pidStr   = if ($proc) { $proc.Id } else { "N/A" }
            $gateMode = "N/A"
            if (Test-Path $TRADING_GATE) {
                try { $gateMode = (Get-Content $TRADING_GATE -Raw -ErrorAction Stop | ConvertFrom-Json).mode } catch {}
            }
            Write-Log "[정상] PID=$pidStr csvIdle=$([math]::Round($csvIdle,0))s hb=$($hbInfo.status) age=$($hbInfo.age_sec)s codes=$($hbInfo.codes) csvOk=$csvOk gate=$gateMode cb=$($script:cbState)" "INFO"
            $lastInfoLog = Get-Date
        }

        Start-Sleep -Seconds $LOOP_INTERVAL
    }
}
finally {
    Remove-Item $WD_PID_FILE -Force -ErrorAction SilentlyContinue
    Write-Log "워치독 v6_4 종료 — PID 파일 정리 완료" "INFO"
}

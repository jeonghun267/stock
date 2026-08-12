# =============================================================
# SAFEPLUS broker watchdog v1.0 (2026-05-15)
# =============================================================
# Purpose:
#   broker_gateway_v1.py self-death detection + auto restart.
#   5/15 11:50 broker self-death pattern (OCX BEX suspected).
#
# Verification:
#   1. heartbeat age < 30s
#   2. extract PID from heartbeat + Get-Process check (false positive guard)
#
# Protection:
#   - singleton lock (duplicate broker blocked by broker itself)
#   - max 5 restarts per day (popup storm guard)
#   - LOGIN OK verification within 60s after restart
#
# Trigger: SAFEPLUS_WATCHDOG_BROKER Task (daily 08:35)
# =============================================================

$ErrorActionPreference = "Continue"
$BASE          = "C:\stock_bot"
$BROKER_SCRIPT = "$BASE\RUN\broker_gateway_v1.py"
$HB_FILE       = "$BASE\IPC\broker_heartbeat.json"
$LOCK_FILE     = "$BASE\DATA\broker_gateway.lock"
$LOG_DIR       = "$BASE\LOG"
$LOG_FILE      = Join-Path $LOG_DIR ("watchdog_broker_{0}.log" -f (Get-Date -Format yyyyMMdd))
$PY            = "C:\Python310-32\python.exe"

$HB_STALE_SEC       = 30   # heartbeat stale threshold (broker 5s x 6)
$CHECK_INTERVAL_SEC = 60   # 1min cycle
$MAX_RESTARTS_DAY   = 15   # [2026-07-07] 5->15: opt10080 수집기 등 연속TR수집기 6개 OFF로 부하감소·프리징 빈도↓ 기대. 5는 오후에 소진돼 죽은채 방치됨. 여전히 무한루프 방지.
$LOGIN_WAIT_SEC     = 60   # LOGIN OK wait after restart

# [FROZEN-DETECT 2026-07-02] TR루프만 정지·하트비트 생존 모드 감지 (13:06 2차 프리징 재발방지)
# 정상: 요청파일은 수초내 소비됨. 프리징: last_request_ts 정지 + requests에 미처리 파일 방치.
# 두 조건 동시 성립시에만 발동 — 과부하(처리는 계속됨)시 last_request_ts 갱신되므로 오탐 없음.
$REQ_DIR            = "$BASE\IPC\requests"
$FROZEN_LASTREQ_SEC = 120  # 마지막 TR 처리 후 경과 (heartbeat.last_request_ts)
$FROZEN_PENDING_SEC = 180  # 가장 오래된 미처리 요청파일 나이 (janitor가 300s에 삭제하므로 그 이하)

if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

# [2026-07-08 친구님 "토·일·국경일엔 아무것도 안 뜨게"] 휴장일 게이트 — 주말/공휴일엔 브로커를 아예 안 켬.
#   브로커가 없으면 전 엔진이 "브로커 없음 → 건너뜀"으로 조용히 잠듦(키움 로그인 창도 안 뜸).
#   공휴일 목록: config\holidays_kr.txt (한 줄에 YYYYMMDD·# 주석 가능·KRX 임시휴장시 한 줄 추가).
$MKT_TODAY = Get-Date
$MKT_HOLIDAY = $false
try {
    $hfile = "$BASE\config\holidays_kr.txt"
    if (Test-Path $hfile) {
        $tstr = $MKT_TODAY.ToString("yyyyMMdd")
        foreach ($line in (Get-Content $hfile)) {
            $d = ($line -split "#")[0].Trim()
            if ($d -eq $tstr) { $MKT_HOLIDAY = $true; break }
        }
    }
} catch {}
if ($MKT_TODAY.DayOfWeek -eq "Saturday" -or $MKT_TODAY.DayOfWeek -eq "Sunday" -or $MKT_HOLIDAY) {
    $why = if ($MKT_HOLIDAY) { "공휴일(holidays_kr.txt)" } else { [string]$MKT_TODAY.DayOfWeek }
    $ts0 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts0] MARKET-CLOSED: $why - 워치독/브로커 기동 안 함(전 시스템 휴식)" | Add-Content $LOG_FILE
    exit 0
}

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Add-Content $LOG_FILE
}

function Is-Target-Pid-Alive($target_pid) {
    try {
        $proc = Get-Process -Id $target_pid -ErrorAction Stop
        return ($proc -ne $null)
    } catch {
        return $false
    }
}

function Get-Broker-Pid-From-Heartbeat() {
    if (-not (Test-Path $HB_FILE)) { return 0 }
    try {
        $hb = Get-Content $HB_FILE -Raw -Encoding UTF8 | ConvertFrom-Json
        return [int]$hb.pid
    } catch {
        return 0
    }
}

# [FROZEN-DETECT 2026-07-02] hb 신선+PID 생존이어도 TR루프 정지면 $true
function Is-Broker-Frozen() {
    try {
        $hb = Get-Content $HB_FILE -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $hb.last_request_ts) { return $false }  # 기동직후 등 — 판정불가시 정상 취급
        $since_req = ((Get-Date) - [datetime]$hb.last_request_ts).TotalSeconds
        if ($since_req -lt $FROZEN_LASTREQ_SEC) { return $false }
        $pend = Get-ChildItem $REQ_DIR -Filter *.json -File -ErrorAction SilentlyContinue
        if (-not $pend) { return $false }  # 대기 요청 없으면 한가한 것 (장외시간 등)
        $oldest = ($pend | Sort-Object LastWriteTime | Select-Object -First 1)
        $pend_age = ((Get-Date) - $oldest.LastWriteTime).TotalSeconds
        if ($pend_age -ge $FROZEN_PENDING_SEC) {
            Write-Log "FROZEN detected: last TR $([int]$since_req)s ago + oldest pending request $([int]$pend_age)s (count=$(@($pend).Count))"
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

function Restart-Broker() {
    Write-Log "broker restart attempt"

    # orphan lock cleanup
    if (Test-Path $LOCK_FILE) {
        try {
            Remove-Item $LOCK_FILE -Force
            Write-Log "  orphan lock removed"
        } catch {
            Write-Log "  orphan lock remove failed: $_"
        }
    }

    # broker spawn
    try {
        $env:REAL_MICRO = "ON"   # [REAL-MICRO 2026-06-24] 실시간 체결강도(228)/호가(121·125) 구독 강제 — setx 캐시 무관 보장
        $proc = Start-Process -FilePath $PY `
                              -ArgumentList "-X", "utf8", $BROKER_SCRIPT `
                              -WorkingDirectory $BASE `
                              -PassThru `
                              -WindowStyle Normal
        Write-Log "  broker spawn PID=$($proc.Id)"
    } catch {
        Write-Log "  broker spawn failed: $_"
        return $false
    }

    # LOGIN OK wait (heartbeat refresh check)
    $deadline = (Get-Date).AddSeconds($LOGIN_WAIT_SEC)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-Path $HB_FILE) {
            $age = ((Get-Date) - (Get-Item $HB_FILE).LastWriteTime).TotalSeconds
            if ($age -lt 15) {
                Write-Log "  LOGIN OK confirmed (heartbeat age=$([int]$age)s)"
                return $true
            }
        }
    }

    Write-Log "  LOGIN 60s timeout - popup not processed (user action needed)"
    return $false
}

# ----------------------------------------------------
# Main Loop
# ----------------------------------------------------
$today_date    = Get-Date -Format "yyyy-MM-dd"
$restart_count = 0
$last_date     = $today_date

Write-Log "==============================================="
Write-Log "watchdog_broker v1.0 START"
Write-Log "  PY=$PY"
Write-Log "  BROKER_SCRIPT=$BROKER_SCRIPT"
Write-Log "  HB_FILE=$HB_FILE"
Write-Log "  CHECK=${CHECK_INTERVAL_SEC}s HB_STALE=${HB_STALE_SEC}s MAX_RESTARTS=$MAX_RESTARTS_DAY"
Write-Log "==============================================="

# [STARTUP FROZEN-KILL 2026-07-03] 기동시 TR루프 프리징(heartbeat 신선하나 last_request_ts 정지) 브로커 즉시 정리.
# 승격 워치독이 프리징 브로커를 kill → 아래 메인루프가 dead 감지해 재기동+재로그인. (장전/장중 프리징 즉시복구)
try {
    if (Test-Path $HB_FILE) {
        $hb0 = Get-Content $HB_FILE -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($hb0.last_request_ts -and $hb0.pid) {
            $sr0 = ((Get-Date) - [datetime]$hb0.last_request_ts).TotalSeconds
            if ($sr0 -ge 120) {
                Write-Log "STARTUP FROZEN-KILL: last TR $([int]$sr0)s ago (>120) - kill PID=$($hb0.pid)"
                try { Stop-Process -Id ([int]$hb0.pid) -Force -ErrorAction Stop; Write-Log "  killed frozen broker" }
                catch { Write-Log "  kill failed: $_" }
            }
        }
    }
} catch { Write-Log "startup frozen-check err: $_" }

while ($true) {
    # daily counter reset
    $cur_date = Get-Date -Format "yyyy-MM-dd"
    if ($cur_date -ne $last_date) {
        Write-Log "date changed: $last_date -> $cur_date (restart_count reset)"
        $restart_count = 0
        $last_date = $cur_date
    }

    # 1. heartbeat age check
    $hb_alive = $false
    $age      = 9999
    if (Test-Path $HB_FILE) {
        $age = ((Get-Date) - (Get-Item $HB_FILE).LastWriteTime).TotalSeconds
        if ($age -lt $HB_STALE_SEC) {
            # 2. PID alive verification
            $broker_pid = Get-Broker-Pid-From-Heartbeat
            if ($broker_pid -gt 0) {
                if (Is-Target-Pid-Alive $broker_pid) {
                    $hb_alive = $true
                } else {
                    Write-Log "false positive: hb fresh($([int]$age)s) but PID=$broker_pid dead"
                }
            } else {
                # PID parse failed - fallback to hb age only (safe default)
                $hb_alive = $true
            }
        }
    }

    if ($hb_alive) {
        # [FROZEN-DETECT 2026-07-02] 살아 보여도 TR루프 정지면 kill 후 아래 재기동 경로로 진입
        if (Is-Broker-Frozen) {
            $frozen_pid = Get-Broker-Pid-From-Heartbeat
            Write-Log "frozen broker kill attempt: PID=$frozen_pid"
            try {
                Stop-Process -Id $frozen_pid -Force -ErrorAction Stop
                Write-Log "  frozen broker PID=$frozen_pid killed"
            } catch {
                Write-Log "  frozen broker kill failed: $_ - retry next cycle"
                Start-Sleep -Seconds $CHECK_INTERVAL_SEC
                continue
            }
            $hb_alive = $false
        } else {
            # broker alive - normal
            Start-Sleep -Seconds $CHECK_INTERVAL_SEC
            continue
        }
    }

    # 3. broker dead detected
    Write-Log "broker DEAD detected (hb age=$([int]$age)s, restart_count=$restart_count/$MAX_RESTARTS_DAY)"

    # daily restart limit
    if ($restart_count -ge $MAX_RESTARTS_DAY) {
        Write-Log "MAX_RESTARTS_DAY=$MAX_RESTARTS_DAY reached - restart stopped (user notify needed)"
        Start-Sleep -Seconds 300  # 5min wait then re-check
        continue
    }

    # 4. restart
    $restart_count += 1
    if (Restart-Broker) {
        Write-Log "restart success (count $restart_count/$MAX_RESTARTS_DAY)"
    } else {
        Write-Log "restart failed (count $restart_count/$MAX_RESTARTS_DAY) - retry next cycle"
    }

    Start-Sleep -Seconds $CHECK_INTERVAL_SEC
}

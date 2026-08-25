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
$CHECK_INTERVAL_SEC = 60   # 1min cycle (off-hours)

# [FAST-CYCLE 2026-08-04] 8/3 10:41 the broker was stopped by an IPC command and the
# price feed went blank for 27s. The watchdog polls every 60s, so in the worst case the
# engines trade blind for a full minute (stop-loss and trailing included).
# During market hours we poll 4x faster. IMPORTANT: only the heartbeat/PID check speeds
# up. Is-Broker-Frozen stays on a 60s gap because it lists IPC\requests, which is a hot
# path during trading - scanning it 4x more often could slow the broker's own IPC.
$CHECK_INTERVAL_MARKET_SEC = 15   # intraday cycle
$MARKET_WATCH_START_HOUR   = 8    # from 08:00
$MARKET_WATCH_END_HOUR     = 15   # until 15:40
$MARKET_WATCH_END_MINUTE   = 40
$FROZEN_CHECK_MIN_GAP_SEC  = 60   # frozen scan keeps the original 60s spacing
$MAX_RESTARTS_DAY   = 15   # [2026-07-07] 5->15: six continuous-TR collectors incl. opt10080 turned OFF, so lower load and fewer freezes expected. 5 ran out in the afternoon and left the broker dead. Still guards an infinite loop.
$LOGIN_WAIT_SEC     = 60   # LOGIN OK wait after restart

# [FROZEN-DETECT 2026-07-02] Detect "TR loop stopped but heartbeat still alive" (13:06 second freeze).
# Normal: request files are consumed within seconds. Frozen: last_request_ts stalls AND unprocessed
# files pile up under requests. Both must hold at once - under mere overload processing continues so
# last_request_ts keeps advancing, hence no false positive.
$REQ_DIR            = "$BASE\IPC\requests"
$FROZEN_LASTREQ_SEC = 120  # elapsed since the last TR was processed (heartbeat.last_request_ts)
$FROZEN_PENDING_SEC = 180  # age of the oldest unprocessed request file (below the janitor's 300s delete)

# [TR-JAM-DETECT 2026-08-13] Detect "responses still flow but almost all are TIMEOUT" (zombie screen).
# 08-12 and 08-13 both jammed at 08:43: Kiwoom kept replaying one stale TR response on one screen;
# the gateway discarded it (request mismatch) but never cleared the screen, so every later request
# timed out for 22 min while heartbeat/PID/last_request_ts all looked healthy (Is-Broker-Frozen
# cannot see it: requests ARE consumed, they just fail). Restart is the proven cure.
# Corrected offline replay reads each journal source exactly once.  It produced
# candidates at 08-12 08:48:55 and 08-13 08:48:58; this is threshold evidence,
# not proof that every candidate is a true zombie.
$JOURNAL_FILE         = "$BASE\LOG\broker_journal.log"
$JAM_WINDOW_SEC       = 300   # look-back window
$JAM_MAX_OK           = 1     # fire only when OK responses have almost vanished
$JAM_MIN_TIMEOUTS     = 12    # and timeouts keep flowing (rules out plain idle)
$JAM_TAIL_LINES       = 4000  # journal can carry ~5 noise lines/sec, so tail deep enough for 300s
$JAM_CHECK_START      = [timespan]"08:40:00"
$JAM_CHECK_END        = [timespan]"15:30:00"
$JAM_KILL_MIN_GAP_SEC = 600   # at most one jam-kill per 10 min

if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

# [2026-07-08 owner: "nothing should pop up on Sat/Sun/national holidays"] Market-closed gate -
#   on weekends and holidays the broker is not started at all.
#   With no broker every engine quietly skips ("no broker -> skip"); no Kiwoom login window either.
#   Holiday list: config\holidays_kr.txt (one YYYYMMDD per line, # comments allowed,
#   add one line for an ad-hoc KRX closure).
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
    $why = if ($MKT_HOLIDAY) { "holiday(holidays_kr.txt)" } else { [string]$MKT_TODAY.DayOfWeek }
    $ts0 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts0] MARKET-CLOSED: $why - watchdog/broker not started (whole system resting)" | Add-Content $LOG_FILE
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

# [FROZEN-DETECT 2026-07-02] $true when the TR loop has stalled even though hb is fresh and the PID is alive
function Is-Broker-Frozen() {
    try {
        $hb = Get-Content $HB_FILE -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $hb.last_request_ts) { return $false }  # just after startup etc - treat "cannot decide" as normal
        $since_req = ((Get-Date) - [datetime]$hb.last_request_ts).TotalSeconds
        if ($since_req -lt $FROZEN_LASTREQ_SEC) { return $false }
        $pend = Get-ChildItem $REQ_DIR -Filter *.json -File -ErrorAction SilentlyContinue
        if (-not $pend) { return $false }  # no pending requests means it is simply idle (off-hours etc)
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

# [TR-JAM-DETECT 2026-08-13] $true when the journal shows an OK famine while timeouts keep flowing.
# Reads only the journal tail; returns $false outside market hours and on any error (fail-open:
# never kill on uncertain data).
function Is-Broker-TrJammed([datetime]$NoOkSince = [datetime]::MinValue) {
    try {
        $now = Get-Date
        $tod = $now.TimeOfDay
        if ($tod -lt $JAM_CHECK_START -or $tod -gt $JAM_CHECK_END) { return $false }
        if (-not (Test-Path $JOURNAL_FILE)) { return $false }
        $tail = Get-Content $JOURNAL_FILE -Tail $JAM_TAIL_LINES -ErrorAction Stop
        $ok = 0; $to = 0; $new_ok = 0
        foreach ($ln in $tail) {
            if ($ln -notmatch '^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]') { continue }
            $t = [datetime]$Matches[1]
            if (($now - $t).TotalSeconds -gt $JAM_WINDOW_SEC) { continue }
            if ($ln -match 'RES [0-9a-f-]+ status=OK') {
                $ok++
                if ($NoOkSince -ne [datetime]::MinValue -and $t -ge $NoOkSince) {
                    $new_ok++
                }
            }
            elseif ($ln -match 'RES [0-9a-f-]+ status=TIMEOUT') { $to++ }
        }
        if ($new_ok -gt 0) {
            Write-Log "TR-JAM recovery observed: new OK=$new_ok since $($NoOkSince.ToString('HH:mm:ss'))"
            return $false
        }
        if ($ok -le $JAM_MAX_OK -and $to -ge $JAM_MIN_TIMEOUTS) {
            Write-Log "TR-JAM suspected: OK=$ok TIMEOUT=$to in last ${JAM_WINDOW_SEC}s"
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

# [FAST-CYCLE 2026-08-04] 15s during market hours, 60s otherwise.
function Get-Check-Interval() {
    $now = Get-Date
    if ($now.Hour -lt $MARKET_WATCH_START_HOUR) { return $CHECK_INTERVAL_SEC }
    if ($now.Hour -gt $MARKET_WATCH_END_HOUR)   { return $CHECK_INTERVAL_SEC }
    if ($now.Hour -eq $MARKET_WATCH_END_HOUR -and $now.Minute -gt $MARKET_WATCH_END_MINUTE) {
        return $CHECK_INTERVAL_SEC
    }
    return $CHECK_INTERVAL_MARKET_SEC
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
        $env:REAL_MICRO = "ON"   # [REAL-MICRO 2026-06-24] force realtime che-str(228)/quote(121,125) subscription - independent of the setx cache
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
$last_frozen_check = [datetime]::MinValue   # [FAST-CYCLE 2026-08-04]
$last_jam_kill     = [datetime]::MinValue   # [TR-JAM-DETECT 2026-08-13]

Write-Log "==============================================="
Write-Log "watchdog_broker v1.0 START"
Write-Log "  PY=$PY"
Write-Log "  BROKER_SCRIPT=$BROKER_SCRIPT"
Write-Log "  HB_FILE=$HB_FILE"
Write-Log "  CHECK=${CHECK_INTERVAL_SEC}s (market ${CHECK_INTERVAL_MARKET_SEC}s) HB_STALE=${HB_STALE_SEC}s MAX_RESTARTS=$MAX_RESTARTS_DAY"
Write-Log "==============================================="

# [STARTUP FROZEN-KILL 2026-07-03] At startup, immediately clear a broker whose TR loop is frozen
# (heartbeat fresh but last_request_ts stalled). The elevated watchdog kills it, the main loop below
# sees it dead and restarts + re-logs-in. Recovers a pre-market or intraday freeze at once.
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
        # [FROZEN-DETECT 2026-07-02] looks alive but TR loop stalled -> kill, then fall through to the restart path below
        # [FAST-CYCLE 2026-08-04] keep the frozen scan on its original 60s spacing -
        # it lists IPC\requests and that folder is hot during trading hours.
        $do_frozen_check = (((Get-Date) - $last_frozen_check).TotalSeconds -ge $FROZEN_CHECK_MIN_GAP_SEC)
        if ($do_frozen_check) { $last_frozen_check = Get-Date }
        $kill_reason = ""
        if ($do_frozen_check -and (Is-Broker-Frozen)) { $kill_reason = "frozen" }
        # [TR-JAM-DETECT 2026-08-13] same 60s spacing as the frozen scan; journal tail read only.
        if ($do_frozen_check -and $kill_reason -eq "") {
            $jam_gap_ok = (((Get-Date) - $last_jam_kill).TotalSeconds -ge $JAM_KILL_MIN_GAP_SEC)
            if ($jam_gap_ok -and (Is-Broker-TrJammed)) {
                # pre-kill recheck: guards the case where OK traffic resumed this very moment
                $jam_suspected_at = Get-Date
                Start-Sleep -Seconds 10
                if (Is-Broker-TrJammed -NoOkSince $jam_suspected_at) {
                    $kill_reason = "tr-jam"
                } else {
                    Write-Log "TR-JAM recheck: OK resumed during wait - kill skipped"
                }
            }
        }
        if ($kill_reason -ne "") {
            if ($restart_count -ge $MAX_RESTARTS_DAY) {
                Write-Log "$kill_reason kill skipped: restart limit $restart_count/$MAX_RESTARTS_DAY reached"
                Start-Sleep -Seconds (Get-Check-Interval)
                continue
            }
            $frozen_pid = Get-Broker-Pid-From-Heartbeat
            Write-Log "$kill_reason broker kill attempt: PID=$frozen_pid"
            try {
                Stop-Process -Id $frozen_pid -Force -ErrorAction Stop
                Write-Log "  $kill_reason broker PID=$frozen_pid killed"
                if ($kill_reason -eq "tr-jam") { $last_jam_kill = Get-Date }
            } catch {
                Write-Log "  $kill_reason broker kill failed: $_ - retry next cycle"
                Start-Sleep -Seconds (Get-Check-Interval)
                continue
            }
            $hb_alive = $false
        } else {
            # broker alive - normal
            Start-Sleep -Seconds (Get-Check-Interval)
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

    Start-Sleep -Seconds (Get-Check-Interval)
}

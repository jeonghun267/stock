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

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] A watcher for the EOD daily-bar collector only.
# 08-14: the 16:05 collector ran clean to 900/1821, then degraded (16:44-17:48 took 64 min for
# 100 codes, 62 of them failing) and finally stopped advancing entirely for the last 46 min,
# all while heartbeat and PID looked healthy.  The TR-JAM detector above cannot see this and is
# deliberately left untouched: it ends at 15:30, and it reads broker_journal.log, which mixes
# every client - other clients kept getting OK all through the jam (17:00 window OK=6 TO=33),
# so its OK-famine test can never hold.
# This watcher judges the collector by its OWN two artifacts and demands BOTH:
#   A. heartbeat fresh but its idx counter unmoved for EOD_IDX_STALL_SEC, and
#   B. over that same span the collector log shows zero successes and only timeouts.
# Either alone is ambiguous: idx also pauses on a slow save, and timeouts also occur in healthy
# runs (a partial jam still advances idx now and then).  Only the conjunction is a zombie.
# Every step is fail-closed: missing, unreadable, or thin evidence means NO action at all.
$EOD_HB_FILE        = "$BASE\LOG\collect_eod.heartbeat"
$EOD_LOG_FILE       = "$BASE\LOG\collect_eod_daily_bars.log"
$EOD_TASK_NAME      = "SAFEPLUS_COLLECT_EOD_BARS"
$EOD_HB_FRESH_SEC   = 300   # heartbeat older than this: collector already gone, nothing to do
$EOD_IDX_STALL_SEC  = 600   # idx unchanged this long = no progress
$EOD_MIN_TIMEOUTS   = 5     # fewer timeouts than this in the span = not enough evidence
$EOD_LOG_TAIL_LINES = 3000
$EOD_KILL_MIN_GAP_SEC = 1800  # at most one collector recovery per 30 min
$EOD_PID_EXIT_WAIT_SEC = 30   # wait for a killed PID to actually disappear
$EOD_CONNECT_WAIT_SEC  = 90   # wait for the NEW broker to report CONNECTED
$EOD_HB_CONNECT_MAX_AGE_SEC = 15  # broker heartbeat must be this fresh to count as connected

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

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] Read a JSON through a throwaway copy.
# On Windows an open read handle makes the writer's os.replace fail with WinError 5; on 08-10
# three engines died exactly that way because a diagnostic tool was reading their state files.
# Returns $null on any problem - callers treat $null as "cannot decide" and stop.
function Read-Json-Copy([string]$Path) {
    $tmp = $null
    try {
        if (-not (Test-Path $Path)) { return $null }
        $tmp = Join-Path $env:TEMP ("wd_" + [guid]::NewGuid().ToString("N") + ".json")
        Copy-Item -LiteralPath $Path -Destination $tmp -Force -ErrorAction Stop
        $raw = Get-Content -LiteralPath $tmp -Raw -ErrorAction Stop
        if (-not $raw) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    } finally {
        if ($tmp -and (Test-Path $tmp)) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
    }
}

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] Evidence B - the collector's own log over one span.
# verdict is "zombie" (no success, enough timeouts), "healthy" (>=1 success), or
# "insufficient" (log missing/unreadable/too thin).  A success is an explicit status=OK or a
# progress line; the collector prints one progress line per 100 codes and its ASCII tail
# "ETA=" is matched so this file stays ASCII-only.
function Get-Eod-Log-Verdict([datetime]$AsOf, [int]$WindowSec, [string]$LogPath = $EOD_LOG_FILE) {
    $res = [pscustomobject]@{ ok = 0; timeouts = 0; verdict = "insufficient" }
    try {
        if (-not (Test-Path $LogPath)) { return $res }
        $tail = Get-Content $LogPath -Tail $EOD_LOG_TAIL_LINES -ErrorAction Stop
        $lo = $AsOf.AddSeconds(-$WindowSec)
        $ok = 0; $to = 0
        foreach ($ln in $tail) {
            if ($ln -notmatch '^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)') { continue }
            $t = [datetime]$Matches[1]
            if ($t -lt $lo -or $t -gt $AsOf) { continue }
            if ($ln -match 'status=TIMEOUT') { $to++ }
            elseif ($ln -match 'status=OK' -or $ln -match 'ETA=') { $ok++ }
        }
        $res.ok = $ok
        $res.timeouts = $to
        if ($ok -gt 0) { $res.verdict = "healthy" }
        elseif ($to -ge $EOD_MIN_TIMEOUTS) { $res.verdict = "zombie" }
        else { $res.verdict = "insufficient" }
        return $res
    } catch {
        return $res
    }
}

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] Evidence A - heartbeat fresh but idx frozen, confirmed by B.
# The stall clock lives in script scope and only advances across real watchdog cycles, so a
# freshly started watchdog can never declare a stall it did not observe itself.
$script:EodLastIdx    = -1
$script:EodIdxMovedAt = [datetime]::MinValue
function Is-Eod-Collector-Zombie() {
    $hb = Read-Json-Copy $EOD_HB_FILE
    if ($hb -eq $null) { return $false }          # cannot decide -> no action
    try {
        $now = Get-Date
        $hb_age = (New-TimeSpan -Start ([datetime]$hb.ts) -End $now).TotalSeconds
        if ($hb_age -gt $EOD_HB_FRESH_SEC) { return $false }   # collector gone, not our case
        $idx = [int]$hb.idx
        if ($idx -ne $script:EodLastIdx) {                     # progress -> reset the clock
            $script:EodLastIdx = $idx
            $script:EodIdxMovedAt = $now
            return $false
        }
        if ($script:EodIdxMovedAt -eq [datetime]::MinValue) {  # first sighting proves nothing
            $script:EodIdxMovedAt = $now
            return $false
        }
        $stall = (New-TimeSpan -Start $script:EodIdxMovedAt -End $now).TotalSeconds
        if ($stall -lt $EOD_IDX_STALL_SEC) { return $false }
        $log = Get-Eod-Log-Verdict $now ([int]$stall)
        if ($log.verdict -ne "zombie") {
            Write-Log "EOD collector idx frozen at $idx for $([int]$stall)s but log verdict=$($log.verdict) (ok=$($log.ok) timeouts=$($log.timeouts)) - no action"
            return $false
        }
        Write-Log "EOD collector ZOMBIE: idx=$idx frozen $([int]$stall)s, log ok=0 timeouts=$($log.timeouts)"
        return $true
    } catch {
        Write-Log "EOD collector check failed ($_) - treated as normal, no action"
        return $false
    }
}

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] Stop a PID and confirm it is really gone.
# Stop-ScheduledTask does not kill the python process, so the PID is always killed directly.
function Stop-Pid-Confirmed([int]$TargetPid, [string]$Label) {
    if ($TargetPid -le 0) { return $false }
    if (-not (Is-Target-Pid-Alive $TargetPid)) {
        Write-Log "  $Label PID=$TargetPid already gone"
        return $true
    }
    try {
        Stop-Process -Id $TargetPid -Force -ErrorAction Stop
    } catch {
        Write-Log "  $Label PID=$TargetPid stop call failed: $_"
    }
    $deadline = (Get-Date).AddSeconds($EOD_PID_EXIT_WAIT_SEC)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (-not (Is-Target-Pid-Alive $TargetPid)) {
            Write-Log "  $Label PID=$TargetPid exit confirmed"
            return $true
        }
    }
    Write-Log "  $Label PID=$TargetPid STILL ALIVE after ${EOD_PID_EXIT_WAIT_SEC}s"
    return $false
}

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] $true only when the broker heartbeat proves a NEW, live,
# connected broker.  Four conditions, all required - 07-28 taught that a second broker started
# beside a surviving one is the worst outcome of all, and a stale heartbeat left by the dead
# broker can otherwise be mistaken for the new one being up.
function Test-Broker-Connected([int]$OldPid) {
    $hb = Read-Json-Copy $HB_FILE
    if ($hb -eq $null) { return $false }
    try {
        $age = ((Get-Date) - (Get-Item $HB_FILE).LastWriteTime).TotalSeconds
        if ($age -gt $EOD_HB_CONNECT_MAX_AGE_SEC) { return $false }   # stale file, not proof
        if ([string]$hb.state -ne "CONNECTED") { return $false }
        $newPid = [int]$hb.pid
        if ($newPid -le 0) { return $false }
        if ($newPid -eq $OldPid) { return $false }                    # same PID = old broker
        if (-not (Is-Target-Pid-Alive $newPid)) { return $false }
        return $true
    } catch {
        return $false
    }
}

# [EOD-COLLECTOR-ZOMBIE 2026-08-14] Recovery, in a fixed order, aborting on any doubt:
#   1. stop the collector task AND its PID (the task alone leaves python running)
#   2. stop the OLD broker PID and CONFIRM it exited  - no confirmation, no spawn (07-28)
#   3. spawn the new broker
#   4. require a NEW pid + state=CONNECTED + fresh heartbeat + live process
#   5. only then restart the collector task
# Steps 2 and 4 are what keep a duplicate broker from ever existing.
function Restart-Eod-Collector-Chain() {
    $chb = Read-Json-Copy $EOD_HB_FILE
    if ($chb -eq $null) {
        Write-Log "  EOD recovery aborted: collector heartbeat unreadable"
        return $false
    }
    $cpid = [int]$chb.pid
    $old_broker_hb = Read-Json-Copy $HB_FILE
    if ($old_broker_hb -eq $null) {
        Write-Log "  EOD recovery aborted: broker heartbeat unreadable (cannot prove single instance)"
        return $false
    }
    $old_broker_pid = [int]$old_broker_hb.pid
    if ($old_broker_pid -le 0) {
        Write-Log "  EOD recovery aborted: broker PID unknown (cannot prove single instance)"
        return $false
    }

    Write-Log "EOD recovery 1/5: stop collector task + PID=$cpid"
    try { Stop-ScheduledTask -TaskName $EOD_TASK_NAME -ErrorAction Stop } catch {}
    if (-not (Stop-Pid-Confirmed $cpid "collector")) {
        Write-Log "  EOD recovery aborted at step 1 (collector still alive)"
        return $false
    }

    Write-Log "EOD recovery 2/5: stop old broker PID=$old_broker_pid"
    if (-not (Stop-Pid-Confirmed $old_broker_pid "broker")) {
        Write-Log "  EOD recovery aborted at step 2 - NOT spawning a second broker"
        return $false
    }

    Write-Log "EOD recovery 3/5: spawn new broker"
    if (-not (Restart-Broker)) {
        Write-Log "  EOD recovery aborted at step 3 (spawn/login failed) - collector left down"
        return $false
    }

    Write-Log "EOD recovery 4/5: wait for CONNECTED with a new PID"
    $deadline = (Get-Date).AddSeconds($EOD_CONNECT_WAIT_SEC)
    $connected = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-Broker-Connected $old_broker_pid) { $connected = $true; break }
    }
    if (-not $connected) {
        Write-Log "  EOD recovery aborted at step 4: CONNECTED with a new PID not proven in ${EOD_CONNECT_WAIT_SEC}s - collector left down"
        return $false
    }
    $nb = Read-Json-Copy $HB_FILE
    Write-Log "  broker CONNECTED PID=$([int]$nb.pid) (was $old_broker_pid)"

    Write-Log "EOD recovery 5/5: restart collector task $EOD_TASK_NAME"
    try {
        Start-ScheduledTask -TaskName $EOD_TASK_NAME -ErrorAction Stop
        $script:EodLastIdx = -1
        $script:EodIdxMovedAt = [datetime]::MinValue
        Write-Log "  collector task started"
        return $true
    } catch {
        Write-Log "  collector task start failed: $_"
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
$last_eod_recovery = [datetime]::MinValue   # [EOD-COLLECTOR-ZOMBIE 2026-08-14]

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
        # [EOD-COLLECTOR-ZOMBIE 2026-08-14] Same 60s spacing, and placed BEFORE the broker
        # checks: when the collector is the stuck party its chain restarts the broker in the
        # correct order, whereas letting the broker path fire first would leave a live
        # collector talking to a broker that vanished under it.
        if ($do_frozen_check -and
            (((Get-Date) - $last_eod_recovery).TotalSeconds -ge $EOD_KILL_MIN_GAP_SEC) -and
            (Is-Eod-Collector-Zombie)) {
            $last_eod_recovery = Get-Date
            if (Restart-Eod-Collector-Chain) {
                Write-Log "EOD collector recovery completed"
            } else {
                Write-Log "EOD collector recovery incomplete - see steps above"
            }
            Start-Sleep -Seconds (Get-Check-Interval)
            continue
        }
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

@echo off
REM S06 capture-only input collection for exact replay.
REM Owner 2026-08-20: orders are structurally impossible here.
REM   - runner injects a no-order broker and a no-op slot holder
REM   - S06_LIVE is forced to NO
REM   - state/events/fills/log are isolated under data\s06_capture_only
REM The LIVE launcher is intentionally NOT re-approved yet (owner order).
REM off: setx S06_EXACT_RECORD NO   (or disable this task)
cd /d C:\stock_bot\RUN
set PYTHONDONTWRITEBYTECODE=1
set S06_EXACT_RECORD=YES
set S06_LIVE=NO
REM Capture the exact current one-share LIVE contract. Environment drift is pinned.
set LOW_REBOUND_DIRECT=YES
set S06_QTY=1
set S06_MAX_SLOTS=6
set S06_MAX_DAILY_CODES=20
set S06_MAX_ENTRIES_PER_CODE=2
set S06_CAPITAL_KRW=1000000
set S06_MAX_PRICE_KRW=300000
set S06_DROP_PCT=8.0
set S06_REBOUND_PCT=1.5
set S06_ENTRY_FLOOR_PCT=1.0
set S06_CHASE_CAP_PCT=2.0
set S06_EARLY_ENTRY_CAP_PCT=1.8
set S06_PULLBACK_MIN_PCT=0.4
set S06_HIGHER_LOW_BUFFER_PCT=0.3
set S06_SECOND_REBOUND_PCT=0.5
set S06_FLOW_ACCEL_WINDOW_SEC=10
set S06_OBSERVE_SEC=60
set S06_OBSERVE_MAX_SEC=720
set S06_REARM_DEEPER_PCT=1.0
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s06_capture_only_runner_v1.py >> C:\stock_bot\LOG\sched_S06_CAPTURE_ONLY.log 2>&1

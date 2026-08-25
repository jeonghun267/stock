@echo off
set S06_LIVE=YES
REM Owner 2026-08-13: common DIRECT_REBOUND lane live (no-pullback low rebound; per-strategy drops/caps kept). UNVERIFIED until first live replay.
set LOW_REBOUND_DIRECT=YES
set S06_QTY=1
REM Keep current LIVE band until the changed 0.5~1.5% default passes preserved-input PROD_REPLAY.
set S06_REBOUND_PCT=1.5
set S06_ENTRY_FLOOR_PCT=1.0
set S06_CHASE_CAP_PCT=2.0
set S06_EARLY_ENTRY_CAP_PCT=1.8
REM Keep current LIVE take-profit until the changed 5% default passes preserved-input PROD_REPLAY.
set S06_TP_PCT=10.0
set S06_MAX_SLOTS=6
set SHARED_MAX_SLOTS=6
set ONLY_MF_ALLOW=STRATEGY06
REM Strategy06 live enabled by owner on 2026-08-03; approval/OFF/manual gates remain mandatory.
REM off: create config\strategy_06_off.flag (buys only) / delete approval flag (full shadow)
cd /d C:\stock_bot\RUN
REM Fail closed if any owner-approved S06 production file changed.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\live_owner_approval_guard_v1.py --strategy S06 >> C:\stock_bot\LOG\sched_STRATEGY06_LIVE.log 2>&1
if errorlevel 1 exit /b 3
REM [S06-DAILY-APPROVE 2026-08-04] Push the standing approval date to today.
REM   S01-S03 renew at 08:59:35, S04 at 09:57, S05 at 09:25; S06 had no path,
REM   so from 8/5 the date check would have left it in shadow all day.
REM   Renews ONLY when the flag already exists - it never creates one, so both
REM   off switches above keep working. A failure here never blocks the engine.
C:\python310\python.exe strategy_06_daily_approve_v1.py >> C:\stock_bot\LOG\sched_STRATEGY06_LIVE.log 2>&1
C:\python310\python.exe strategy_06_crash_low_chase_v1.py >> C:\stock_bot\LOG\sched_STRATEGY06_LIVE.log 2>&1

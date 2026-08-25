@echo off
set S06_LIVE=YES
set S06_QTY=1
set S06_EARLY_ENTRY_CAP_PCT=1.8
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

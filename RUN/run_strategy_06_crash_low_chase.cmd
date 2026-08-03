@echo off
set S06_LIVE=YES
REM Strategy06 live enabled by owner on 2026-08-03; approval/OFF/manual gates remain mandatory.
REM off: create config\strategy_06_off.flag (buys only) / delete approval flag (full shadow)
cd /d C:\stock_bot\RUN
C:\python310\python.exe strategy_06_crash_low_chase_v1.py >> C:\stock_bot\LOG\sched_STRATEGY06_LIVE.log 2>&1

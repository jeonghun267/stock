@echo off
REM SAFEPLUS S02 low-finding shadow A - NO ORDERS, read only.
REM fixed floor 0.5 / cap 1.5 / no observe wait / flow checks ON
REM Writes only into data\shadow_s02_A\ - never touches live paths.
REM Starts 09:00:30 Mon-Fri so it can see the morning crash lows that the
REM live S02 signal (09:20) structurally cannot reach.
REM Rollback: schtasks /delete /tn SAFEPLUS_S02_SHADOW_A /f
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
set S02_SIX_ENTRY_FLOOR_PCT=0.5
set S02_SIX_CHASE_CAP_PCT=1.5
set S02_SIX_FIRST_REBOUND_PCT=1.0
set S02_OBSERVE_SEC=0
set S02_OUTPUT=C:\stock_bot\data\shadow_s02_A\signal_A.json
set S02_EVENT_DIR=C:\stock_bot\data\shadow_s02_A
REM 2026-08-27 owner fix: own singleton lock so this shadow never races the live
REM S02 signal task at 09:00 (the 2026-08-27 09:41 silent-death root cause).
set S02_LOCK_PATH=C:\stock_bot\data\shadow_s02_A\signal_A.lock
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_low_buy_signal_v1.py >> C:\stock_bot\data\shadow_s02_A\_sched.log 2>&1

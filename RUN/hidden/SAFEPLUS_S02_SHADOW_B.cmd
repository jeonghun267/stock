@echo off
REM SAFEPLUS S02 low-finding shadow B - NO ORDERS, read only.
REM price only - the three SIX flow gates are bypassed
REM Writes only into data\shadow_s02_B\ - never touches live paths.
REM Starts 09:00:30 Mon-Fri so it can see the morning crash lows that the
REM live S02 signal (09:20) structurally cannot reach.
REM Rollback: schtasks /delete /tn SAFEPLUS_S02_SHADOW_B /f
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
set S02_SIX_ENTRY_FLOOR_PCT=0.5
set S02_SIX_CHASE_CAP_PCT=1.5
set S02_SIX_FIRST_REBOUND_PCT=1.0
set S02_OBSERVE_SEC=0
set S02_OUTPUT=C:\stock_bot\data\shadow_s02_B\signal_B.json
set S02_EVENT_DIR=C:\stock_bot\data\shadow_s02_B
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_low_buy_signal_SHADOWB_v1.py >> C:\stock_bot\data\shadow_s02_B\_sched.log 2>&1

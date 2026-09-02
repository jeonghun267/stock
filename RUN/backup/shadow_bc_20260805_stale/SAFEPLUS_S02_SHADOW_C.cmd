@echo off
REM SAFEPLUS S02 low-finding shadow C - NO ORDERS, read only.
REM depth ladder - rebound threshold scales with the drop size
REM Writes only into data\shadow_s02_C\ - never touches live paths.
REM Starts 09:00:30 Mon-Fri so it can see the morning crash lows that the
REM live S02 signal (09:20) structurally cannot reach.
REM Rollback: schtasks /delete /tn SAFEPLUS_S02_SHADOW_C /f
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
set S02_OBSERVE_SEC=0
set S02_OUTPUT=C:\stock_bot\data\shadow_s02_C\signal_C.json
set S02_EVENT_DIR=C:\stock_bot\data\shadow_s02_C
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_low_buy_signal_SHADOWC_v1.py >> C:\stock_bot\data\shadow_s02_C\_sched.log 2>&1

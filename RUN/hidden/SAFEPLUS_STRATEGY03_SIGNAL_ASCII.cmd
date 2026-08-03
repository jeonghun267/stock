@echo off
REM Strategy 03 signal monitor. This launcher contains ASCII paths only.
set PYTHONDONTWRITEBYTECODE=1
set S03_WATCH=C:\stock_bot\IPC\micro_watch_valley.json
set S03_SNAPSHOT=C:\stock_bot\IPC\live_micro_snapshot.json
set S03_EOD=C:\stock_bot\data\eod_daily_bars.csv
set S03_NAMES=C:\stock_bot\data\_code_name_cache.json
set S03_LOOP_SEC=1
REM [SNAP-AGE 2026-08-03 owner approved] signal monitor only: 4 sec becomes 10 sec.
REM This monitor places no orders. The 4 sec gate made it skip the whole code,
REM not just the flow record. Measured 10:57: 63 pct of snapshot codes were older
REM than 4 sec, so thin tickers never built the 20 sec of flow history that the
REM acceleration check needs, and died as NO_FLOW_ACCEL_DATA.
REM Order-time safety is unchanged: STRATEGY03_LIVE_ASCII.cmd keeps 4 sec.
REM Rollback: set this back to 4 and restart the signal task.
set S03_SNAPSHOT_MAX_AGE_SEC=10
set S03_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
set S03_RESTARTS=0
:S03_RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_03_valley_signal_launcher_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY03_SIGNAL.log 2>&1
if %ERRORLEVEL% EQU 0 exit /b 0
set /a S03_RESTARTS+=1
if %S03_RESTARTS% GEQ 3 exit /b 1
echo %date% %time% S03_SIGNAL_RESTART %S03_RESTARTS%/3 >> C:\stock_bot\data\LOG\sched_STRATEGY03_SIGNAL.log
timeout /t 60 /nobreak >nul
goto S03_RUN

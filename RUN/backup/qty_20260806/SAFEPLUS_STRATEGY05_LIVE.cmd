@echo off
REM *2026-07-29 owner order (renew approval daily, automatically): --approve-on YYYYMMDD
REM   was a manual daily re-arm; forgetting it silently zeroed that strategy buys.
REM   -> switched to --approve (existing switch in strategy_04_preflight_v1: writes
REM   approval ONLY after every check passes; OFF gate and 08:45 daily flag reset
REM   remain). Same pattern as S01~S03 --activate. Rollback: restore *.bak_20260729_autodate.
REM Strategy 05 common rotation. Same-day approval and OFF gate remain mandatory.
set PYTHONDONTWRITEBYTECODE=1
set S05_LIVE=YES
set S05_QTY=2
set S05_MAX_SLOTS=6
set S05_MAX_DAILY_CODES=6
set S05_MAX_CYCLES_PER_CODE=2
set S05_ROTATION_CAPITAL_KRW=2000000
set S05_MAX_SELL_RETRIES=3
set S05_SIGNAL_MAX_AGE_SEC=5
set S05_SNAPSHOT_MAX_AGE_SEC=4
set S05_BOARD_MAX_AGE_SEC=8
set S05_FILL_WAIT_SEC=8
set ONLY_MF_ALLOW=STRATEGY05
set SAFEPLUS_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_05_preflight_v1.py --approve >> C:\stock_bot\data\LOG\sched_STRATEGY05_PREFLIGHT.log 2>&1
if errorlevel 1 exit /b %errorlevel%
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_05_rotation_engine_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY05_LIVE.log 2>&1

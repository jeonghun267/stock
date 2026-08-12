@echo off
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_engine_recovery_probe_v1.py --strategy S05 >> C:\stock_bot\data\LOG\sched_STRATEGY05_RECOVERY.log 2>&1
if errorlevel 1 exit /b 0
set PYTHONDONTWRITEBYTECODE=1
set STRATEGY_RECOVERY_EXIT_ONLY=YES
set S05_LIVE=YES
set S05_QTY=1
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
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_05_rotation_engine_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY05_RECOVERY.log 2>&1

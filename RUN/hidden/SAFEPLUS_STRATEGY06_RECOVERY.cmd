@echo off
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_engine_recovery_probe_v1.py --strategy S06 >> C:\stock_bot\data\LOG\sched_STRATEGY06_RECOVERY.log 2>&1
if errorlevel 1 exit /b 0
set PYTHONDONTWRITEBYTECODE=1
set STRATEGY_RECOVERY_EXIT_ONLY=YES
set S06_LIVE=YES
set S06_QTY=1
set S06_MAX_SLOTS=6
set SHARED_MAX_SLOTS=6
set ONLY_MF_ALLOW=STRATEGY06
set S06_EARLY_ENTRY_CAP_PCT=1.8
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_06_crash_low_chase_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY06_RECOVERY.log 2>&1

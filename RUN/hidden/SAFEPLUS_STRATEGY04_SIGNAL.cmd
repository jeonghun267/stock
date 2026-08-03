@echo off
REM Strategy 04 deep-W signal monitor. No broker import and no order submission.
set PYTHONDONTWRITEBYTECODE=1
set S04_WATCH=C:\stock_bot\IPC\micro_watch_valley.json
set S04_MAX_CYCLES_PER_CODE=2
set S04_OUTPUT=C:\stock_bot\data\strategy_04_pullback_signal_v1.json
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_04_pullback_signal_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY04_SIGNAL.log 2>&1

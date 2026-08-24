@echo off
REM Strategy 01 signal-only monitor. No broker import and no order submission.
set PYTHONDONTWRITEBYTECODE=1
set S01_WATCH=C:\stock_bot\IPC\micro_watch_strategy_shared.json
set S01_MAX_CYCLES_PER_CODE=2
set S01_OUTPUT=C:\stock_bot\data\strategy_01_open_surge_signal_v2.json
cd /d C:\stock_bot\RUN
REM Build order-zero A/B/C metadata before the signal monitor starts.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s01_trend_priority_board_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY01_SIGNAL.log 2>&1
REM S01 v3 relative-volume baseline; data preparation only, never submits orders.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_01_volume_baseline_v3.py >> C:\stock_bot\data\LOG\sched_STRATEGY01_SIGNAL.log 2>&1
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_01_open_surge_signal_v2.py >> C:\stock_bot\data\LOG\sched_STRATEGY01_SIGNAL.log 2>&1

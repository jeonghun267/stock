@echo off
REM Strategy 02 low-buy signal monitor. No broker import and no order submission.
set PYTHONDONTWRITEBYTECODE=1
set S02_WATCH=C:\stock_bot\IPC\micro_watch_strategy_shared.json
set S02_MAX_CYCLES_PER_CODE=2
set S02_OUTPUT=C:\stock_bot\data\strategy_02_low_buy_signal_v1.json
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_low_buy_signal_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY02_SIGNAL.log 2>&1
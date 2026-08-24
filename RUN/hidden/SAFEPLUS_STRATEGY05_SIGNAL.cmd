@echo off
REM Strategy 05 intraday base-breakout signal/watch monitor. Order capability zero.
set PYTHONDONTWRITEBYTECODE=1
set S05_MAX_CYCLES_PER_CODE=2
set S05_BASE_VOLX=3.0
set S05_MIN_BUY_MONEY_RATIO=0.58
set S05_MAX_ENTRY_SPREAD_BPS=35
set S05_MIN_MICROPRICE_EDGE_BPS=0
set S05_OUTPUT=C:\stock_bot\data\strategy_05_base_breakout_signal_v1.json
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_05_base_breakout_signal_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY05_SIGNAL.log 2>&1

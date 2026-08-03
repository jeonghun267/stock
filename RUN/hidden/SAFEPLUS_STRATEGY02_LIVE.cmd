@echo off
REM Strategy 02 live path. OFF flag and separate owner approval gate all real buys.
set PYTHONDONTWRITEBYTECODE=1
set S02_LIVE=YES
set S02_QTY=1
set S02_MAX_SLOTS=6
set S02_MAX_DAILY_CODES=15
set S02_MAX_CYCLES_PER_CODE=2
set S02_ROTATION_CAPITAL_KRW=2000000
set S02_MAX_SELL_RETRIES=3
set S02_SIGNAL_MAX_AGE_SEC=5
set S02_SNAPSHOT_MAX_AGE_SEC=4
set S02_BOARD_MAX_AGE_SEC=8
set S02_FILL_WAIT_SEC=8
set ONLY_MF_ALLOW=STRATEGY02
set SAFEPLUS_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_live_gate_launcher_v1.py --strategy S02 >> C:\stock_bot\data\LOG\sched_STRATEGY02_LIVE.log 2>&1
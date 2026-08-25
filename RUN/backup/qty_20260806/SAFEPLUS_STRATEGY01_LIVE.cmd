@echo off
REM Independent Strategy 01. Live buys require the separate owner approval flag.
set PYTHONDONTWRITEBYTECODE=1
set S01_LIVE=YES
set S01_QTY=2
set S01_MAX_SLOTS=6
set S01_MAX_DAILY_CODES=6
set S01_MAX_CYCLES_PER_CODE=2
set S01_ROTATION_CAPITAL_KRW=2000000
set S01_MAX_SELL_RETRIES=3
set S01_SIGNAL_MAX_AGE_SEC=5
set S01_SNAPSHOT_MAX_AGE_SEC=4
set S01_BOARD_MAX_AGE_SEC=8
set S01_FILL_WAIT_SEC=8
set ONLY_MF_ALLOW=STRATEGY01
set SAFEPLUS_MIN_PRICE=10000
set SAFEPLUS_MIN_MARKETCAP=50000000000
REM Wake prerequisites only on weekdays from 08:15 through 09:19.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_01_bootstrap_v1.py
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_live_gate_launcher_v1.py --strategy S01 >> C:\stock_bot\data\LOG\sched_STRATEGY01_LIVE.log 2>&1

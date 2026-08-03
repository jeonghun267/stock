@echo off
REM Strategy 04 live path. Today's owner approval and OFF gate are mandatory.
set PYTHONDONTWRITEBYTECODE=1
set S04_LIVE=YES
set S04_QTY=1
set S04_MAX_SLOTS=6
set S04_MAX_DAILY_CODES=6
set S04_MAX_CYCLES_PER_CODE=2
set S04_ROTATION_CAPITAL_KRW=2000000
set S04_MAX_SELL_RETRIES=3
set S04_SIGNAL_MAX_AGE_SEC=5
set S04_SNAPSHOT_MAX_AGE_SEC=4
set S04_BOARD_MAX_AGE_SEC=8
set S04_FILL_WAIT_SEC=8
set ONLY_MF_ALLOW=STRATEGY04
set SAFEPLUS_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_04_live_gate_launcher_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY04_LIVE.log 2>&1

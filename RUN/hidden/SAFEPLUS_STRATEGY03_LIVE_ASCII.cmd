@echo off
REM Strategy 03 replacement path. OFF flag and owner approval gate every real buy.
set PYTHONDONTWRITEBYTECODE=1
set S03_LIVE=YES
set S03_S06_CRASH_CLAIM_ENABLED=YES
set S03_EARLY_LOW_LIVE=AUTO
set S03_FLOW_TURN_FAST_LIVE=NO
set S03_MAX_SLOTS=6
set S03_MAX_DAILY_CODES=6
set S03_MAX_CYCLES_PER_CODE=2
set S03_MAX_SELL_RETRIES=3
set S03_SIGNAL_MAX_AGE_SEC=5
set S03_SNAPSHOT_MAX_AGE_SEC=4
set S03_BOARD_MAX_AGE_SEC=8
set S03_FILL_WAIT_SEC=8
set S03_LOOP_SEC=1
set ONLY_MF_ALLOW=STRATEGY03
set SAFEPLUS_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_live_gate_launcher_v1.py --strategy S03 >> C:\stock_bot\data\LOG\sched_STRATEGY03_LIVE.log 2>&1

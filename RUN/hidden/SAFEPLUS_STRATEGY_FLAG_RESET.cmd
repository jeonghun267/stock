@echo off

REM Daily pre-open reset of S01-S03 gate flags (delete approval, restore OFF).

REM Lets SAFEPLUS_STRATEGY_ALL_PREFLIGHT at 08:59:35 start from a clean state.

REM Idempotent, no broker, no TR, no orders. Refuses to run 08:59-16:00.

REM ASCII-only REM before any SET line (cp949 parse rule). No SET lines here anyway.

C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_flag_daily_reset_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY_FLAG_RESET.log 2>&1

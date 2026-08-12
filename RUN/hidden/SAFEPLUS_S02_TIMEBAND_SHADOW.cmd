@echo off
REM Strategy 02 afternoon-condition SHADOW (read only, NO ORDERS, TR 0).
REM Replays the day 1-second capture, scores afternoon-strength candidates
REM side by side, appends one row per candidate per day.
REM Friend 2026-08-03: afternoon needs stronger entry conditions.
REM Output: data\shadow\strategy_02_timeband_shadow.csv and _signals.csv
REM Rollback: disable task SAFEPLUS_S02_TIMEBAND_SHADOW
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\strategy_02_timeband_shadow_v1.py >> C:\stock_bot\data\LOG\sched_S02_TIMEBAND_SHADOW.log 2>&1

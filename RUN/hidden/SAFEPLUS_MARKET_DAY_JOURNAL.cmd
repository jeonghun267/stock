@echo off
REM Market day journal (read only, NO ORDERS, TR 0).
REM Aggregates data\high_range_shadow_*.csv into one row per day:
REM   close labels (pullback depth, fake bounce rate, fall timetable)
REM   + morning 09:30 gauges + provisional day label (strong/normal/down).
REM Friend approved 2026-08-08. Output CSV path is inside the py file.
REM Rollback: disable task SAFEPLUS_MARKET_DAY_JOURNAL.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\market_day_journal_v1.py >> C:\stock_bot\data\LOG\sched_MARKET_DAY_JOURNAL.log 2>&1

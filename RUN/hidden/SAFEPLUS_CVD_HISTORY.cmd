@echo off
REM CVD history recorder for S03 bottom detection research.
REM Read-only, ZERO Kiwoom TR, no orders. Self-exits at CVD_END.
REM Owner-approved 2026-07-29.
set PYTHONDONTWRITEBYTECODE=1
set CVD_LOOP_SEC=3
set CVD_DROP_PCT=-3.0
set CVD_MAX_CODES=60
set CVD_END=1535
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\cvd_history_recorder_v1.py >> C:\stock_bot\data\LOG\sched_CVD_HISTORY.log 2>&1

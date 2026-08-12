@echo off
REM Day judge (read only, NO ORDERS, TR 0).
REM Reads today mf_1s capture 09:00-09:30 slice, computes broken-bounce rate,
REM writes data\day_gate\day_judge_YYYYMMDD.json for the S02 buy gate.
REM suspect=true when rate >= 47 (12-day replay threshold, forward-validating).
REM Friend approved 2026-08-08. Rollback: disable task SAFEPLUS_DAY_JUDGE.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\day_judge_v1.py >> C:\stock_bot\data\LOG\sched_DAY_JUDGE.log 2>&1

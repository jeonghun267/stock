@echo off
REM [2026-08-06 owner order] S01 buy-method replacement check, full sample.
REM Runs after market close. Replays S02 buy logic over every day S01 traded
REM and writes a report. Read-only: no orders, no broker calls, no state writes.
REM The replay refuses to analyze unless it first reproduces known signals
REM (config\replay_contract_v1.json). Rollback: schtasks /delete /tn SAFEPLUS_S01_METHOD_REPLAY /f
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\replay_buy_method_v1.py --s01-compare >> C:\stock_bot\data\LOG\sched_S01_METHOD_REPLAY.log 2>&1

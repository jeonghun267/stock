@echo off
REM Strategy 01~05 sell-quality shadow audit. Observation only: no broker, no TR, no orders.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_shadow_exit_audit_v1.py >> C:\stock_bot\data\LOG\sched_SHADOW_EXIT_AUDIT.log 2>&1

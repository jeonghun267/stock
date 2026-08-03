@echo off
REM Shared candidate context only. It has no broker import and no order path.
set PYTHONDONTWRITEBYTECODE=1
set STRATEGY_CONTEXT_LOOP_SEC=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_common_candidate_context_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY_COMMON_CONTEXT.log 2>&1

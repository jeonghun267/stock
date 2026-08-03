@echo off
REM Read-only checks first; flags change only after every check passes.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_03_auto_live_preflight_v1.py --activate >> C:\stock_bot\data\LOG\sched_STRATEGY03_PREFLIGHT.log 2>&1

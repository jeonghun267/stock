@echo off
REM C2-01 open-surge observer. Read-only market files, zero broker/order imports.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\captain2_strategy_01_shadow_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_C2_01_SHADOW.log 2>&1

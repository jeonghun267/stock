@echo off
REM [2026-08-01 approved] latency probe 2 - snapshot lag shadow. read only, no orders.
REM stops at 15:40 by itself. off: disable task LATENCY_SNAPSHOT_LAG or delete this file.
cd /d C:\stock_bot\RUN
C:\python310\python.exe snapshot_lag_shadow_v1.py %* >> C:\stock_bot\LOG\sched_LATENCY_SNAPSHOT_LAG.log 2>&1

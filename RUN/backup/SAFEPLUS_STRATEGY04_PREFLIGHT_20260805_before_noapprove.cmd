@echo off
REM *2026-07-29 owner order (renew approval daily, automatically): --approve-on YYYYMMDD
REM   was a manual daily re-arm; forgetting it silently zeroed that strategy buys.
REM   -> switched to --approve (existing switch in strategy_04_preflight_v1: writes
REM   approval ONLY after every check passes; OFF gate and 08:45 daily flag reset
REM   remain). Same pattern as S01~S03 --activate. Rollback: restore *.bak_20260729_autodate.
REM 2026-07-27 owner authorization: approve only today after every preflight check passes.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_04_preflight_v1.py --approve >> C:\stock_bot\data\LOG\sched_STRATEGY04_PREFLIGHT.log 2>&1

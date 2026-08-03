@echo off
REM Three-stage read-only preflight self-test under the S04 task principal.
set PYTHONDONTWRITEBYTECODE=1
set SAFEPLUS_SCHEDULED_SELFTEST=limited
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\preflight_context_selftest_v1.py --profile limited --scheduled-context >> C:\stock_bot\data\LOG\sched_PREFLIGHT_SELFTEST_LIMITED.log 2>&1

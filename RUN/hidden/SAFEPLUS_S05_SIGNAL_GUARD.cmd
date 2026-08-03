@echo off
REM S05 signal watchdog: restart SAFEPLUS_STRATEGY05_SIGNAL when its output JSON goes stale.
REM Owner-approved 2026-07-29. Zero orders, zero Kiwoom TR (file mtime + schtasks only).
set PYTHONDONTWRITEBYTECODE=1
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s05_signal_guard_v1.py >> C:\stock_bot\data\LOG\sched_S05_SIGNAL_GUARD.log 2>&1

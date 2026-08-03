@echo off
REM ============================================================================
REM  CAPTAIN2 evening auto-report - read-only (no orders, no TR)   2026-07-22
REM ----------------------------------------------------------------------------
REM  Owner is away 7/23 ("do everything you can"). Writes the day's results
REM  (captain2 lane stats, PULL per-trade table, valley attempt/block stats,
REM  flags, crash stamps) to Desktop\captain2_evening_report + data\LOG.
REM  Task: Mon-Fri 15:45 single shot. ASCII-only REM (cp949 parse safety).
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\captain2_evening_report_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_EVENING_REPORT.log 2>&1

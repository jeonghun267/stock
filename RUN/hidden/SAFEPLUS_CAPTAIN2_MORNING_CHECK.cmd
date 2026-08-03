@echo off
REM ============================================================================
REM  CAPTAIN2 morning auto-check - read-only (no orders, no TR)  2026-07-22
REM ----------------------------------------------------------------------------
REM  Verifies the 7/22 surgeries every trading morning:
REM   broker FID15 [REAL-SIDE-VERIFY] / snapshot 4 side fields / MF1S capture
REM   / captain2 alive + crash-log stamp / side_exact=1 in events.
REM  Output: data\LOG\captain2_morning_check_YYYYMMDD.txt + Desktop copy.
REM  Task: Mon-Fri 09:06 + 10-min repeat x3 (late items re-checked).
REM  ASCII-only REM lines (cp949 parse safety).
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\captain2_morning_check_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_MORNING_CHECK.log 2>&1

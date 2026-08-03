@echo off
REM ============================================================================
REM  money_flow_1s_capture_v1 - zero orders, zero TR, zero new realtime reg
REM ----------------------------------------------------------------------------
REM  ASCII-only: Korean REM lines can break cmd parsing (UTF-8 read as cp949).
REM  Auto-registered 2026-07-22 so it can't be forgotten (was previously manual-only).
REM  Captures cum_vol/che_str/money_add_5s10s30s/che_delta_5s10s every second into a CSV.
REM  Read-only diagnostic: no orders, no new TR, no new SetRealReg - reads files
REM  that are already updated every second by other processes.
REM  money_flow_1s_capture_v1.py itself auto-exits at MF1S_END.
REM  2026-07-22 (approved): END extended 1035 -> 1531. The 10:35 default was a
REM  test window and killed the capture mid-day; Money Score retro-scoring needs
REM  full-day per-second data (baseline speed + all-codes coverage).
REM  Task: Mon-Fri 08:59 + 1-min IgnoreNew repeat (crash auto-restart; script
REM  has its own single-instance lock, stale 120s).
REM ============================================================================
set MF1S_END=1531
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\money_flow_1s_capture_v1.py >> C:\stock_bot\data\LOG\sched_MF1S_CAPTURE.log 2>&1

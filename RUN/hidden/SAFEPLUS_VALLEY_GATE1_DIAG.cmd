@echo off
REM ============================================================================
REM  Valley Gate1 diagnostic report - READ-ONLY       2026-07-19 (user-approved)
REM ----------------------------------------------------------------------------
REM  Runs once at 09:29 (task scheduled ONCE for 2026-07-20 per approval).
REM  Zero orders, zero Kiwoom TR - reads local files only:
REM    prev-top pool / snapshot / che_state / valley ledger / eod csv.
REM  Measures items 1-5 of the user's diagnostic protocol: fixed-pool size,
REM  snapshot coverage, che coverage, -5% touches, and per-stock rejection
REM  reasons the OLD che-based _crash_map path would have produced.
REM  Output: data\LOG\valley_gate1_diag.log + LOG\valley_gate1_diag.csv
REM  To make it daily: schtasks /change or re-register /sc WEEKLY /d MON-FRI.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set VH_LIVE=NO
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\valley_gate1_diag_v1.py >> C:\stock_bot\data\LOG\sched_VALLEY_GATE1_DIAG.log 2>&1

@echo off
REM Money-flow executor - LIVE. Isolation ON (only_moneyflow.flag). CAP 200k, MAXPOS 3.
REM ASCII-only: Korean REM before a SET line breaks cmd parsing (UTF-8 read as cp949) and skips the SET.
REM Rollback to shadow: set MF_EXEC_LIVE=NO
set MF_EXEC_LIVE=YES
set MF_EXEC_CAP=200000
REM [2026-07-08 4-directives] No position-count cap (opportunity-first). Real cap = daily buy budget 2,000,000 KRW (no refill).
set MF_EXEC_MAXPOS=99
set MF_BOARD_REFRESH=NO
set MF_MIN_PRICE=3000
REM [2026-07-08] Star small-money test: allow risk-regime (yellow) star candidates too.
REM Entry still requires confirm gate (momentum-up OR che bottom-rebound) = falling-knife blocked.
REM Rollback: delete next line or set MF_INCLUDE_RISK=NO
set MF_INCLUDE_RISK=YES
REM [2026-07-08 4-directives] Opportunity-first ALL DAY (no role slots). Rollback: 1030
set MF_MORNING_END=1530
REM [2026-07-08 correction] Same stock max 2 entries per day (1 buy + 1 re-entry). Different stocks keep rotating (global distinct cap 20).
set MF_MAX_ENTRIES=3
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\money_flow_exec_v1.py >> C:\stock_bot\data\LOG\sched_MFLOW_EXEC.log 2>&1

@echo off
REM ============================================================================
REM  Base-breakout SHADOW observer - zero orders, zero TR   2026-07-19 (approved)
REM ----------------------------------------------------------------------------
REM  User hypothesis: sideways base = energy coiling; catch the volume explosion,
REM  but enter on the RETEST of the breakout line (never chase the breakout bar).
REM  Backtest 26d: retest-limit +2%/-1.5% = 48 trades, 54% win, PF 1.18.
REM  This shadow runs the same logic live (virtual fills only) and records the
REM  one thing backtests cannot: real-time CHE(trade-strength) change at the
REM  breakout and at the retest fill. Universe = valley morning watchlist func.
REM  Task: Mon-Fri 09:00, repeat 20min x 6h30m, RUN_SEC 1190 (valley pattern).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set BB_BASE_N=30
set BB_TIGHT=3.0
set BB_VOLX=5.0
set BB_WAIT=10
set BB_TGT=2.0
set BB_STP=-1.5
set BB_MAX_TRADES=2
set BB_ENTRY=0930
set BB_ENTRY_END=1430
set BB_EXIT=1510
set BB_END=1512
set BB_LOOP_SEC=2
set BB_RUN_SEC=1190
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\base_breakout_shadow_v1.py >> C:\stock_bot\data\LOG\sched_BB_SHADOW.log 2>&1

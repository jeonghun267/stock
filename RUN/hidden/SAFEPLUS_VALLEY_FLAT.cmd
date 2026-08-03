@echo off
REM ============================================================================
REM  Valley Hunter - SAFETY FLAT-OUT       2026-07-19 (user-approved, live 07-20)
REM ----------------------------------------------------------------------------
REM  Runs at 15:13, AFTER the main valley task window. Same pattern as
REM  SAFEPLUS_CRASH_FLOW_FLAT: re-run the engine itself so it re-reads the
REM  ledger, sees the clock is past VH_EXIT(15:10), and flattens whatever is
REM  still open (engine-death safety net - captain once died at 55s).
REM  It can never buy: entry window (VH_ENTRY_END=1430) is long closed by 15:13.
REM  If the main engine already flattened, ledger pos=false -> does nothing.
REM  Idempotent. Sell fills are confirmed (pending_sell) like the main run.
REM
REM  VH_LIVE=YES unconditional ON PURPOSE (no valley_off.flag check here):
REM  a safety net must always be able to SELL real leftovers, even on a day
REM  the main engine was switched to shadow mid-way.
REM  Context: the 09:43 last-resort FLAT (crash_flat_v1) now EXCLUDES codes the
REM  valley ledger is managing - this task is the counterpart seller of last
REM  resort for those positions after 15:10.
REM  Env mirrors the LIVE cmd (unused at 15:13 but kept in sync on purpose).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set VH_LIVE=YES
set VH_CAP=300000
REM 2026-07-20 user-approved: account-vs-ledger check at this safety-net run only
REM   (main 09:00 LIVE cmd does NOT set this - zero behavior change there).
REM   Log/warn only - never auto buy/sell/create/delete ledger positions.
set VH_ACCT_CHECK=YES
REM mirror of LIVE cmd (FLAT cannot buy anyway - entry window closed at 15:13)
set VH_QTY_FIX=1
set VH_SLOTS=6
set SHARED_MAX_SLOTS=6
set VH_PVAL_MIN=700
set VH_PVAL_MAX=20000
set VH_GAP_TH=-3
set VH_ENTRY=0900
set VLA_ENTRY=0900
set VH_ENTRY_END=1430
set VH_EXIT=1510
set VH_END=1525
set VH_LOOP_SEC=3
set VH_RUN_SEC=600
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\valley_hunter_live_v1.py >> C:\stock_bot\data\LOG\sched_VALLEY_FLAT.log 2>&1

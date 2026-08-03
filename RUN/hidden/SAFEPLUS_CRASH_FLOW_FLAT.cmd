@echo off
REM ============================================================================
REM  Crash flow - SAFETY FLAT-OUT       2026-07-15 (premarket surgery #2)
REM ----------------------------------------------------------------------------
REM  Runs at 09:23, AFTER the main crash task has finished (deadline ~09:21:30,
REM  hard stop at 09:22), so the two never overlap and cannot double-sell.
REM
REM  Purpose: if the main engine died while holding (captain died at 55s once),
REM  or a sell got stuck, the position would sit there all day with no seller.
REM  This process re-reads the ledger, sees the clock is past CF_EXIT(09:20),
REM  and flattens whatever is still open. It never buys: the entry window
REM  (CF_ENTRY_END=0918) is long closed. If the main engine already flattened,
REM  the ledger says pos=false -> it does nothing. Idempotent.
REM
REM  CF_LIVE=YES unconditional ON PURPOSE (no crash_off.flag check here):
REM  a safety net must always be able to SELL real leftovers, even on a day
REM  the main engine was switched to shadow mid-way.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set CF_LIVE=YES
set CF_CAP=300000
set CF_SLOTS=6
set SHARED_MAX_SLOTS=6
REM ** 2026-07-16 noon user: floor back to 700 eok (mirror of LIVE cmd - keep in sync) **
set CF_PVAL_MIN=700
set CF_PVAL_MAX=20000
set CF_GAP_TH=-3
set CF_BUY_CHE=105
set CF_SELL_CHE=100
set CF_DEFENSE=d5
set CF_TRAIL=-2
set CF_STOP=-4
set CF_DROP=-4
set CF_GAP=0.5
set CF_ENTRY=0900
set CF_ENTRY_END=0918
set CF_EXIT=0920
set CF_END=0930
set CF_LOOP_SEC=3
set CF_RUN_SEC=120
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_flow_live_v1.py >> C:\stock_bot\data\LOG\sched_CRASH_FLOW_LIVE.log 2>&1

@echo off
REM ============================================================================
REM  FLAT safety net LAST RESORT (2026-07-16) - liquidate leftovers if engines died.
REM  Moved 09:21 -> 09:24 (surgery 7/16): runs AFTER main engines (~09:21:30) and
REM  per-strategy FLATs (09:22 captain / 09:23 crash) so nothing overlaps.
REM  Reads crash/captain ledgers, sells pos=True holdings at market, then writes
REM  pos=False back to the ledger (no double-sell by any later run). Sell-only.
REM  If engines already flat -> pos=False -> nothing to sell.
REM  FLAT_LIVE=NO to shadow. Window 09:24-09:35.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set FLAT_LIVE=YES
REM ** 2026-07-18: moved 09:24 -> 09:43. Captain MC_EXIT was extended to 09:40 (7/17) but this
REM    last-resort FLAT stayed at 09:24 - it would force-sell captain holdings mid-management
REM    (ledger pass + account-reconcile pass both hit them). Task trigger moved to 09:43 too.
REM    FLAT_END added: code default END=0935 would sit BEFORE the new start and exit instantly.
set FLAT_START=0943
set FLAT_END=0955
if exist C:\stock_bot\config\flat_off.flag set FLAT_LIVE=NO
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_flat_v1.py >> C:\stock_bot\data\LOG\sched_FLAT.log 2>&1

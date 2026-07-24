@echo off
REM ============================================================================
REM  Morning Captain - SAFETY FLAT-OUT       2026-07-15
REM ----------------------------------------------------------------------------
REM  ** 2026-07-17 user: LIVE's unconditional flat-out time moved 09:20 -> 09:40
REM     (hold allowed while d5/d10 support it). This task's own Windows Task
REM     Scheduler trigger MUST be moved 09:22 -> 09:42 to match (schtasks), else
REM     it fires while LIVE is still legitimately holding on d5/d10 support and
REM     force-sells it 2 minutes after the extended deadline was supposed to start
REM     mattering - defeating the whole point of the extension. This .cmd's own
REM     MC_EXIT/MC_END below are updated; the SCHEDULED TRIGGER TIME is a separate
REM     Task Scheduler setting and must be changed there too.
REM  Runs AFTER the main captain task has finished (it now ends ~09:41:30),
REM  so the two never overlap and cannot double-sell.
REM
REM  Purpose: if the main engine died while holding, the position would sit there
REM  all day. This process re-reads the ledger, sees the clock is past MC_EXIT,
REM  and flattens whatever is still open. It never enters (entry window is closed,
REM  and its own hm is already past EXIT_HM by the time it runs). If the main
REM  engine already flattened, the ledger says pos=false -> it does nothing. Idempotent.
REM
REM  MC_LIVE=YES unconditional ON PURPOSE (no captain_off.flag check here):
REM  a safety net must always be able to SELL real leftovers. Its own sell decision
REM  logic is UNCHANGED (still the plain "hm >= EXIT_HM -> flatten" branch) - only
REM  the clock it fires at moved, so it stays a true unconditional last resort.
REM  2026-07-15 surgery: slots 5 -> 6 (shared pool with crash flow, rotation).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set MC_LIVE=YES
REM ** 2026-07-16: keep sell mode in sync with LIVE cmd (classic rollback) **
set MC_SELL_MODE=classic
set MC_CAP=300000
REM mirror of LIVE cmd (FLAT cannot buy anyway - entry window closed by 09:42)
set MC_QTY_FIX=1
set MC_SLOTS=6
set SHARED_MAX_SLOTS=6
set MC_SELL_PB=0.5
set MC_BUY_UP=0.3
REM ** 2026-07-20: sync with LIVE cmd (-3, the 246d-backtested value). Was -4 (stale). **
set MC_STOP=-3
set MC_MAX_RE=0
set MC_TRAIL2=-2
set MC_ENTRY=0903
set MC_ENTRY_END=0906
set MC_EXIT=0940
set MC_END=0950
set MC_LOOP_SEC=3
set MC_RUN_SEC=120
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_captain_live_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN_LIVE.log 2>&1

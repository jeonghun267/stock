@echo off
REM ============================================================================
REM  KOSPI crash WATCHER (2026-07-16) - RECORD ONLY, NO ORDERS, after-close TR.
REM  User: "hae bwa" (go) - KOSPI 500eok-2jo band has 62 crash candidates/day
REM  (3.6x KOSDAQ) and same low-to-close rebound (+4.25% vs +4.34%), but we had
REM  no intraday data to verify the morning-V-shape. This backfills 1m bars for
REM  today's KOSPI crashers (opt10080, pace 0.35s, max 120 calls, after close)
REM  and scores morning-frame entries into data/shadow/kospi_crash/trades.csv.
REM  Runs 16:25 daily (after COLLECT_EOD_BARS 16:05 writes today's EOD rows).
REM  Kill: disable task SAFEPLUS_KOSPI_CRASH_WATCH. Test: KW_DRY=YES (TR 0).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\kospi_crash_watch_v1.py >> C:\stock_bot\data\LOG\sched_KOSPI_CRASH.log 2>&1

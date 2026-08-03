@echo off
REM ============================================================================
REM  Valley Hunter EXTENDED SHADOW (100~1000eok) - 2026-07-20 (user-approved)
REM ----------------------------------------------------------------------------
REM  Permanent shadow - zero orders. Tests whether widening the universe from
REM  700eok~2jo down to 100eok~1000eok would produce more real BUY conversions
REM  and profit, using real-time 2-second che/volume data that historical 1-min
REM  bars cannot reproduce (see 2026-07-20 backtest study - inconclusive due to
REM  1-min data granularity vs live 2-sec polling).
REM  Isolation (verified 2026-07-20): does NOT import shared_slots, does NOT
REM  import broker_client/BrokerClient/send_order_real, does NOT touch the real
REM  valley_hunter_live_ledger.json. Separate ledger/csv/log/sell_watch files.
REM  This cmd/task is fully independent of SAFEPLUS_VALLEY_HUNTER_LIVE.cmd -
REM  that file is untouched (hash-verified before/after this patch).
REM  Runs ONE continuous process 09:00-15:35 (no restart) - no ledger-reload-
REM  across-restart complexity needed since state lives only within this run.
REM  Min operating period per user: 5 trading days or 30 BUY_SHADOW trades
REM  before touching any parameter - do not shorten this window.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set VH_EXT_LIVE=NO
set VH_EXT_PVAL_MIN=100
set VH_EXT_PVAL_MAX=1000
set VH_EXT_SLOTS=6
set VH_EXT_LOOP_SEC=2
set VH_EXT_ENTRY=0900
set VH_EXT_END=1535
set VH_EXT_RUN_SEC=23700
set VH_EXT_DIAG_SEC=300
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\valley_hunter_extended_shadow_v1.py >> C:\stock_bot\data\LOG\sched_VALLEY_EXT_SHADOW.log 2>&1

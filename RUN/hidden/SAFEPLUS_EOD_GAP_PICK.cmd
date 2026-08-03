@echo off
REM 2026-07-22 sweep (10 trading days, prices_1m_clean): strategy-A upper-wick cap
REM   0.25 -> 0.50. Evidence: with jeongbae OFF sample, win 45%->54%, avg -0.39->+0.07;
REM   with jeongbae ON (current) wick value changes nothing (5 passes at any cap),
REM   so this is a zero-risk relax that only matters when uptrend returns.
REM   NOTE real blocker = jeongbae-strict gate in _buy_one (owner rule 7/17) -
REM   ALL variants are cost-negative over the 10d window; gate change = owner call.
set EOD_GAP_STRATA_UW_MAX=0.50
REM 2026-07-29 owner order: exempt closing-auction buys from the regime stop.
REM   Evidence (daily bars, 1 year, 1134 limit-up closes, sell at next open,
REM   0.38%% round-trip cost removed): crash days (market -3%% or worse)
REM   +6.262%%, win 73.1%% (67 samples) - better than the +5.976%% overall.
REM   The old "wiped out on crash days" note was based on 8 samples only.
REM   Intraday strategies S01-S05 stay blocked - do NOT add them here.
REM   Rollback: delete this line.
set REGIME_STOP_EXEMPT=EODGAP_
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py pick >> C:\stock_bot\data\LOG\eod_gap_live.log 2>&1

@echo off
REM 2026-08-27 owner-approved repair. Keep live disabled until saved-input replay passes.
set EOD_GAP_LIVE=NO
REM 2026-07-22 sweep (10 trading days, prices_1m_clean): strategy-A upper-wick cap
REM   0.25 -> 0.50. Evidence: with jeongbae OFF sample, win 45%->54%, avg -0.39->+0.07;
REM   with jeongbae ON (current) wick value changes nothing (5 passes at any cap),
REM   so this is a zero-risk relax that only matters when uptrend returns.
REM   NOTE real blocker = jeongbae-strict gate in _buy_one (owner rule 7/17) -
REM   ALL variants are cost-negative over the 10d window; gate change = owner call.
set EOD_GAP_STRATA_UW_MAX=0.50
REM 2026-08-18 owner-approved closing-auction upgrade. Capture real FID 23/24/21
REM first; switch to LIVE with MAX_POS=3 only after a saved-input PROD_REPLAY PASS.
set EOD_GAP_AUCTION_GATE_MODE=SHADOW
REM 2026-08-18 owner-approved live configuration for the 2026-08-19 run.
REM Owner-approved permanent automatic live gate: one share each, up to three names.
set EOD_GAP_MAX_POS=3
set EOD_GAP_LOCKED_QTY_ONE=YES
set EOD_GAP_QTY_ONE_ALL=YES
set EOD_GAP_LOCKED_FIRST=NO
set EOD_GAP_LOCKED_PRIORITY=NO
set EOD_GAP_BOARD_CACHE_FALLBACK=YES
set EOD_GAP_BOARD_MAX_AGE_SEC=600
REM 2026-08-27 owner-approved candidate-path cleanup.
set EOD_GAP_VR_MIN=0
set EOD_GAP_LIMITUP_ADD=NO
set EOD_GAP_LOCKED_D2_PRIORITY=NO
set EOD_GAP_CAPTURE_INPUTS=YES
REM 2026-07-29 owner order: exempt closing-auction buys from the regime stop.
REM   Evidence (daily bars, 1 year, 1134 limit-up closes, sell at next open,
REM   0.38%% round-trip cost removed): crash days (market -3%% or worse)
REM   +6.262%%, win 73.1%% (67 samples) - better than the +5.976%% overall.
REM   The old "wiped out on crash days" note was based on 8 samples only.
REM   Intraday strategies S01-S05 stay blocked - do NOT add them here.
REM   Rollback: delete this line.
set REGIME_STOP_EXEMPT=EODGAP_
REM Match the already-running broker gateway safety floor before candidate selection.
set SAFEPLUS_MIN_PRICE=10000
set SAFEPLUS_MIN_MARKETCAP=100000000000
REM Fail closed: only a previous-trading-day, current-engine PROD_REPLAY PASS enables orders.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py entry_replay_auto >> C:\stock_bot\data\LOG\eod_gap_live.log 2>&1
if errorlevel 1 goto EOD_GAP_PICK_RUN
set EOD_GAP_LIVE=YES
:EOD_GAP_PICK_RUN
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py pick >> C:\stock_bot\data\LOG\eod_gap_live.log 2>&1

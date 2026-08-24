@echo off
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
REM Buy up to three names; limit-up names remain capped at one share each.
set EOD_GAP_MAX_POS=1
set EOD_GAP_LOCKED_QTY_ONE=YES
REM Saved-input replay is not yet available. Owner approved one-share observation
REM for five trading sessions (2026-08-19 through 2026-08-25).
set EOD_GAP_LOCKED_D2_PRIORITY=YES
set EOD_GAP_LOCKED_D2_PRIORITY_UNTIL=20260825
REM 2026-07-29 owner order: exempt closing-auction buys from the regime stop.
REM   Evidence (daily bars, 1 year, 1134 limit-up closes, sell at next open,
REM   0.38%% round-trip cost removed): crash days (market -3%% or worse)
REM   +6.262%%, win 73.1%% (67 samples) - better than the +5.976%% overall.
REM   The old "wiped out on crash days" note was based on 8 samples only.
REM   Intraday strategies S01-S05 stay blocked - do NOT add them here.
REM   Rollback: delete this line.
set REGIME_STOP_EXEMPT=EODGAP_
REM 2026-08-20 owner in-session order: lift the 10,000 KRW floor for EOD_GAP only.
REM   Evidence: 2026-08-19 15:25 both picks (6,760 / 5,380) died at price_floor while
REM   backtest says low-scored cheap limit-ups earn 3.4x more (Q1 +12.49%% vs Q5 +3.67%%).
REM   Scoped here so every other strategy keeps the global user-env 10,000 floor.
REM   1,000 keeps the 2026-06-30 "no sub-1000 KRW penny stocks" rule intact.
REM   NOTE gateway second net still inherits 10,000 until its own fix deploys.
REM   Rollback: delete the next line.
set SAFEPLUS_MIN_PRICE=1000
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py pick >> C:\stock_bot\data\LOG\eod_gap_live.log 2>&1

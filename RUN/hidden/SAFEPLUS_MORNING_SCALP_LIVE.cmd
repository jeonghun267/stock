@echo off
REM ============================================================================
REM  Morning Scalp - NEW (shadow by default)      2026-07-17
REM ----------------------------------------------------------------------------
REM  User: "10 stocks by value x volatility, keep watching them, use our low-anchor
REM  buy/sell method, scalp small gains repeatedly in the morning volatility window."
REM  Universe = crash_flow_live_v1._crash_map() (money-flow board pool, 700eok~2jo,
REM  already-dipped candidates) - reused, no separate ranking logic (user's suggestion).
REM  Entry = low_anchor_buy_v1.LowAnchor (shared with crash_flow) - armed -5%, low reset,
REM  rebound +1~2% zone, buy-ratio 51.2% confirm.
REM  Exit = THIS engine's own logic (different from crash_flow): quick take-profit +1.5%,
REM  hard stop -4%, 60min forced timeout-exit. Not the crash_flow trail/top-candle/5MA exit.
REM
REM  Backtest (1min archive, 26 days, 700eok~2jo band): TP1.5% -> ~73-217 trades,
REM  win 79-85%, cost-adjusted avg +0.13~0.49%/trade depending on watchlist selection method.
REM
REM  SHADOW BY DEFAULT (MS_LIVE=NO) - this is a brand-new, never-live-tested strategy.
REM  Going live requires: 1) flip MS_LIVE=YES here 2) add MSCALP to ONLY_MF_ALLOW gate.
REM  KILL SWITCH: create C:\stock_bot\config\morning_scalp_off.flag
REM  Intraday stop = C:\stock_bot\config\manual_buy_block.flag (blocks buys only).
REM  Order isolation rqname = MSCALP_ (separate from crash flow / captain / eod gap).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set MS_LIVE=NO
if exist C:\stock_bot\config\morning_scalp_off.flag set MS_LIVE=NO
set MS_CAP=300000
set MS_SLOTS=3
REM 2026-07-17 user: NO fixed take-profit - peak-anchor volume-confirm sell (MS_SEG_CHE_TH tunable)
set MS_SEG_CHE_TH=105
set MS_ANCHOR_OBS_SEC=25
set MS_STOP=-4.0
set MS_ENTRY=0900
set MS_ENTRY_END=1030
set MS_TIMEOUT_MIN=60
set MS_LOOP_SEC=2
set MS_RUN_SEC=5700
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_scalp_live_v1.py >> C:\stock_bot\data\LOG\sched_MORNING_SCALP_LIVE.log 2>&1

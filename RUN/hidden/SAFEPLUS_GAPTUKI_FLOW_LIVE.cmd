@echo off
REM ============================================================================
REM  Gaptuki money-FLOW LIVE       2026-07-20 (user explicit order: deploy live)
REM ----------------------------------------------------------------------------
REM  Detection = gaptuki_flow_shadow_v1.Flow (5-stage, single source).
REM  Day-1 safety: 1 SHARE x 3 slots. Market order, fill-confirm via fills csv,
REM  open-order cancel on ghost. Sell chain: -2pct hard stop (pre-arm) /
REM  trail arm +1pct then peak -1pct / 120min timeout / 15:10 flat-out.
REM  KILL SWITCH: config\gaptuki_off.flag -> next start detect-only.
REM  Intraday stop: config\manual_buy_block.flag (buys blocked, sells work).
REM  Gate: ONLY_MF_ALLOW must contain GAPTUKI (set via setx 2026-07-20).
REM  NOTE: entry-rule backtests were cost-negative (see topic memory) - user
REM  explicitly overrode. Do not scale size without a positive verdict.
REM  ASCII-only REM (cp949 parse issue). Batch must stay CRLF.
REM ============================================================================
set GL_LIVE=YES
set GL_QTY_FIX=1
set GL_SLOTS=3
set GL_STOP=-2.0
set GL_TRAIL_ARM=1.0
set GL_TRAIL=1.0
set GL_HOLD_MAX=120
set GL_ENTRY_END=1430
set GL_EXIT=1510
set GL_END=1512
set GL_FILL_WAIT=8
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\gaptuki_flow_live_v1.py >> C:\stock_bot\data\LOG\sched_GAPTUKI_FLOW_LIVE.log 2>&1

@echo off
REM ============================================================================
REM  Gaptuki money-FLOW FLAT safety net   2026-07-20 - runs 15:14 after LIVE end
REM  Re-runs the engine: reloads ledger, clock past GL_EXIT(1510) -> sells any
REM  leftover (engine-death safety). Cannot buy: entry window closed at 14:30.
REM  GL_LIVE=YES unconditional ON PURPOSE (safety net must always sell).
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
set GL_END=1519
set GL_RUN_SEC=280
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\gaptuki_flow_live_v1.py >> C:\stock_bot\data\LOG\sched_GAPTUKI_FLOW_FLAT.log 2>&1

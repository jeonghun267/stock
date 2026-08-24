@echo off
REM Crash-bottom buy/sell-pressure SHADOW recorder (no real orders). Records 0900-0920 only.
REM ASCII-only: Korean REM before a SET line breaks cmd parsing (UTF-8 read as cp949).
REM Reads che_ts (trade-strength + orderbook) at each low+0.5pct bounce; pairs with outcome to 0920.
REM Idempotent: backfills all available che_ts days, dedups by date. Rollback: disable this task.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_bottom_flow_shadow_v1.py >> C:\stock_bot\data\LOG\sched_CRASH_FLOW.log 2>&1
REM Crash 20min-scalp STRATEGY shadow (che>=105 buy / bull->bear+che sell / 5min-MA defense / 0920). No real orders. Dedup by date.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_strategy_shadow_v1.py >> C:\stock_bot\data\LOG\sched_CRASH_STRATEGY.log 2>&1
REM PM(12:00-14:20) strategy shadow 2026-07-15: S1 crash-rebound / S2 base+flip (user idea) / S3 breakout / S4 pullback.
REM Same universe as crash live (prev value 700eok-2jo). No real orders. Dedup by date. Rollback: delete these lines.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_pm_shadow_v1.py >> C:\stock_bot\data\LOG\sched_CRASH_PM.log 2>&1

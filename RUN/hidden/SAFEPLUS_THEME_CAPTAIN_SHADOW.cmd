@echo off
REM ============================================================================
REM  Morning Captain SHADOW recorder  (NO ORDERS, TR 0)   2026-07-14 rewritten
REM ----------------------------------------------------------------------------
REM  Reads the CAPTAIN signal published by the selector (money_flow_board_v1)
REM  and records PnL only. Selector does the picking; this only records.
REM
REM  Selector conditions (verified 2026-07-14 09:03 with real Kiwoom TR data:
REM  it picked TECHWING which went +16.52%% that morning):
REM    rise >= 4%% vs 09:00 OPEN   (NOT vs prev close!)  captain rate 4.6%% -> 47%%
REM    high-break rate >= 35%%     captain 46.8%% vs non-captain 23.3%%
REM    bull-candle rate >= 60%%    captain 59.3%% vs non-captain 35.6%%
REM    cumulative value >= 50 eok  (20-50 eok band lost money: win rate 18%%)
REM    per-minute value >= 1 eok   (10M KRW order = under 10%% of 1min flow)
REM    market cap 1,000 eok ~ 2 trillion
REM
REM  Records TWO exit rules side by side for 5 days, then we pick the winner:
REM    A) 09:20 flat-out, stop -3%%                       backtest optimum (246d)
REM    B) 10:20 flat-out + top-sell(3min wick) + re-entry  user's rule
REM
REM  Old recorder (theme_captain_shadow_v1.py) is RETIRED - every condition it
REM  used was rejected by the 2026-07-14 verification (prev-day close position,
REM  surge multiple, dead-theme block...). Backup: .bak_old_20260714
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set MC_ON=YES
set MC_END=1030
set MC_LOOP_SEC=5
set MC_STOP=-3
set MC_DISASTER=-5
set MC_GRACE=3
set MC_TOP_POS=0.2
set MC_TOP_GRACE=9
set MC_EXIT_A=0920
set MC_EXIT_B=1020
set MC_REENTRY=1
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_captain_shadow_v1.py >> C:\stock_bot\data\LOG\sched_MORNING_CAPTAIN.log 2>&1

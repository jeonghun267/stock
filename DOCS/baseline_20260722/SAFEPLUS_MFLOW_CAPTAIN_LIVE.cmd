@echo off
REM ============================================================================
REM  Morning Captain - LIVE (small size)      2026-07-15
REM ----------------------------------------------------------------------------
REM  User: "tomorrow ONLY the theme-captain goes live, small size"
REM  User: "follow the captain, buy and sell at every pullback, keep following it"
REM  User: "but if the cash comes back to the account and something else buys
REM         with it, what then? that's my worry"
REM
REM  Lock so the cash cannot leak to a DIFFERENT strategy:
REM   1) ONLY_MF_ALLOW=MFLOWCAP  -> broker order gate rejects every other buy
REM      (deep-bottom sends MFLOW_BUY_..., EODGAP sends EODGAP_... : both blocked)
REM      SELL orders never hit that gate, so existing positions still liquidate.
REM  ** 2026-07-17 user: "delete the max-3-name pin, let money rotate to whichever
REM     qualifying captain candidate is next in priority when a slot frees up." **
REM  Stock-pin removed. Cash from selling A can now buy the next-highest-ranked
REM  captain candidate that hasn't been tried yet (not just re-buy A). Pool size is
REM  capped only by SHARED_MAX_SLOTS (shared with crash-flow). Candidate count itself
REM  is also uncapped now (board-side CAP_SLOTS removed) - as many names as pass the
REM  captain gate get ranked, not just top-3.
REM
REM  Sell / re-buy rules (backtest 246d: captain_causal_v37 / v38)
REM    -3%% from entry            -> hard stop, no grace
REM    -0.5%% from running peak   -> sell all immediately (do NOT wait for a bar)
REM    +0.3%% from running low    -> re-buy immediately, max 5 times (currently off, MC_MAX_RE=0)
REM  ** 2026-07-17 user: "09:20 unconditional flat-out is gone, only the SELL deadline moves to
REM     09:40 - entry window itself stays 09:20." ** MC_EXIT pushed 0920 -> 0940; MC_ENTRY_END
REM     stays the entry cutoff (now 0920, see below) - no new buys/rotation after that, existing
REM     positions just keep being managed until MC_EXIT.
REM  ** 2026-07-17 user: "d5 breakout + weak buy-strength = sell, that part alone is correct.
REM     d10 is just insurance - if that didn't manage to sell it, sell when d10 breaks too." **
REM     Two independent triggers now, not one 3-way AND: (a) below d5 AND che<D5_CHE -> sell.
REM     (b) below d10 (any che) -> sell (backstop for the GIGALANE case where che never dropped).
REM
REM  Every order logs [theory trigger price] vs [actual price at order time].
REM  That gap IS the loop-lag. Backtest break-even = 0.40%%.
REM    lag < 0.40%% -> swing beats holding (74k-79k/day vs 46.7k)
REM    lag > 0.40%% -> ROLL BACK to plain hold (set MC_SELL_PB 0 and MC_BUY_UP 0)
REM  -> C:\stock_bot\LOG\captain_lag.csv
REM
REM  KILL SWITCH: create C:\stock_bot\config\manual_buy_block.flag
REM  ROLLBACK   : setx ONLY_MF_ALLOW "MFLOW,EODGAP"   (restores deep-bottom+eodgap)
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
REM  2026-07-15 user: "5 names, 1.5M KRW"  -> 300,000 x 5 slots = 1,500,000
REM  NOTE: the captain filter only yields ~0.2-0.7 names/day, so 5 slots will
REM  rarely fill. Backtest: rank 1-3 = +16,885/day, rank 4-8 = -14,537/day.
REM  Slots 4-5 may bleed on the rare crowded day; accepted to widen the sample.
set MC_LIVE=YES
REM [7/16] kill switch - captain_off.flag present -> shadow (zero orders)
if exist C:\stock_bot\config\captain_off.flag set MC_LIVE=NO
REM [7/16 shared capital] 300k per name, common 6-slot pool (rotation with crash engine)
set MC_CAP=300000
REM 2026-07-19 user: captain too buys 1 SHARE per name (same as valley day-1 sizing).
REM   Remove this line to roll back to 300k KRW sizing.
set MC_QTY_FIX=1
set MC_SLOTS=6
REM ** 2026-07-16 user: ROLLBACK crash -> classic. Day-1 live proof: GIGALANE peak +13.6%
REM **   fell to +1.1% because crash-sell (bull->bear + che<100) never fires on a straight
REM **   waterfall and che stayed >=100 at the first dip. classic = sell ALL at peak-0.5%,
REM **   re-buy at low+0.3% (max 5) - the 246d-backtested captain way. Lag measured 0.000%
REM **   today, so the classic precondition (lag < 0.40%) is confirmed live.
set MC_SELL_MODE=classic
set SHARED_MAX_SLOTS=6
set MC_SELL_PB=0.5
set MC_BUY_UP=0.3
set MC_STOP=-3
REM ** 2026-07-16 user: DELETE re-buy (low+0.3pct x5). Sell once = done. **
REM ** MC_TRAIL2 = peak -2pct INSURANCE sell (backup in case the -0.5pct trail missed), like the d5 backup. **
set MC_MAX_RE=0
set MC_TRAIL2=-2
REM ** 2026-07-17 user: entry starts 09:00 not 09:03 - need to catch fast-flying names right
REM    at the open. Entry window still closes 09:20 (unchanged) - only the SELL deadline moved. **
set MC_ENTRY=0900
set MC_ENTRY_END=0920
REM ** 2026-07-17 user: unconditional flat-out time extended 09:20 -> 09:40 (entry window itself
REM    is unaffected, stays 09:00-09:20 above). END_HM/RUN_SEC pushed out to match (same +1.5min
REM    buffer ratio as before). FLAT safety-net task rescheduled 09:22 -> 09:42 to match.
set MC_EXIT=0940
set MC_END=0942
set MC_LOOP_SEC=2
set MC_RUN_SEC=2490
REM 2026-07-21 TEMP TEST (user-approved) - Money Flow candidate connection live test. 1-share sizing above.
set MC_MFE_ENABLE=YES
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_captain_live_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN_LIVE.log 2>&1

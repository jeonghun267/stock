@echo off
REM ============================================================================
REM  Crash 20min-scalp CHE-strategy runner       2026-07-15
REM ----------------------------------------------------------------------------
REM  User confirmed strategy (crash stocks, 09:00-09:20):
REM    BUY  : crash low (>-4%% before 09:10), trade-strength(che) >= 105, once, no averaging
REM    SELL : (1) top = bull->bear candle(completed) AND that bar's che < threshold
REM           (2) defense = daily 5-day MA break (shadow backtest best +2.57%%/89%%)
REM           (3) disaster stop -4%%   (4) 09:20 flat out
REM
REM  ***  CF_LIVE=YES  =>  REAL ORDERS (small size)  2026-07-15 user: "connect crash to LIVE"  ***
REM  User: deep-bottom underperforms; crash (che-strategy) is its upgraded replacement -> go live.
REM  Gate: ONLY_MF_ALLOW must include CRASHFLOW (else orders silently blocked, 7/14 incident).
REM        Now "CRASHFLOW,EODGAP,MFLOWCAP" => crash + eodgap + captain pass, deep-bottom(MFLOW) blocked (=off).
REM  KILL SWITCH (7/16 fix): create C:\stock_bot\config\crash_off.flag  -> next start runs shadow (no orders).
REM        Intraday stop = C:\stock_bot\config\manual_buy_block.flag (blocks buys NOW; sells keep working).
REM        NOTE "setx CF_LIVE NO" does NOT work - line below hardcodes YES and wins.
REM  Order isolation rqname = CRASHFLOW_ (separate from deep-bottom / captain).
REM  Size: 300,000 x 3 slots = 900,000 KRW. Change CF_CAP / CF_SLOTS to adjust.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
REM  *** 2026-07-16 night: today's live run lost -20,952 KRW (-6.98%%). 4 of 8 entries    ***
REM  *** got sold same-second by the old daily-5MA rule (entry price already below it);   ***
REM  *** the rest reversed within 3-9 min for -2.45%%/-2.49%%/-3.14%% -> entries were near ***
REM  *** the top of a bounce, not a real low. Fixed: entry logic (old ARM+7min-hold+0.5%%  ***
REM  *** rebound+flat che>=105) replaced by low_anchor_buy_v1.LowAnchor (same -5%% arm,     ***
REM  *** low keeps resetting on new low, wait for +1.2%% rebound, 3-tier che check: >=150  ***
REM  *** strong buy / 100-150 base buy / <100 wait-for-new-low). CF_BUY_CHE/CF_GAP below   ***
REM  *** are now dead (removed) - tune via LA_ARM_PCT/LA_OBS_PCT/LA_BUY_CHE/LA_STRONG_CHE  ***
REM  *** in low_anchor_buy_v1.py if needed. Backed up as .bak_lowanchor_20260716.          ***
REM ============================================================================
set CF_LIVE=YES
REM ★[7/16 안전수술③] 확실한 킬스위치 — crash_off.flag 있으면 그림자(주문0)로. (setx CF_LIVE NO 는 이 cmd가 이겨서 무효)
if exist C:\stock_bot\config\crash_off.flag set CF_LIVE=NO
REM ★[7/16 자본공유] 총 200만·종목당 30만·공통 6슬롯(아침대장과 로테이션). SLOTS/MAX 둘 다 6.
set CF_CAP=300000
set CF_SLOTS=6
set SHARED_MAX_SLOTS=6
REM ** 2026-07-15 user: select from prev-day trading value 700eok - 2jo (was 300) **
REM ** 2026-07-16 morning: lowered to 500eok ("too thin to select from").          **
REM ** 2026-07-16 noon user: RAISE BACK TO 700 - "slots are few anyway".           **
REM **   Evidence: backfill 700eok+ = +1.81pct/78pct vs 500-700 = +0.85pct/50pct.  **
REM **   Today live: 7 of 8 entries were 700eok+; the only 500-700 name (FADU,     **
REM **   prev-val 561eok) was the day's worst trade (-3.39pct).                    **
REM ** gap-down open (vs prev close -3pct) gets unconditional first priority, then depth **
set CF_PVAL_MIN=700
set CF_PVAL_MAX=20000
set CF_GAP_TH=-3
set CF_SELL_CHE=100
set CF_DEFENSE=d5
REM ** 2026-07-16 user: peak-trail sell - sell when 2pct down from peak(above entry) **
set CF_TRAIL=-2
set CF_STOP=-4
set CF_DROP=-4
set CF_ENTRY=0900
set CF_ENTRY_END=0918
set CF_EXIT=0920
set CF_END=0922
set CF_LOOP_SEC=2
set CF_RUN_SEC=1290
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_flow_live_v1.py >> C:\stock_bot\data\LOG\sched_CRASH_FLOW_LIVE.log 2>&1

@echo off
REM ============================================================================
REM  Valley Hunter 20min-scalp CHE-strategy runner       2026-07-18
REM ----------------------------------------------------------------------------
REM  Copy of SAFEPLUS_CRASH_FLOW_LIVE.cmd (crash stocks engine). Original crash
REM  engine is NOT modified per user instruction. This is a separate 09:30-start
REM  clone that shares the same buy/sell logic and the same shared slot pool
REM  (shared_slots.py) - crash engine exits by 09:22 so slots are free by 09:30.
REM  Only the entry-price (low-anchor) logic in valley_low_buy_v1.py is meant
REM  to diverge from the crash engine going forward.
REM
REM  ***  2026-07-19 user approval: LIVE from 2026-07-20. Kill switch below   ***
REM  ***  (valley_off.flag) still downgrades to shadow at next start.         ***
REM  Gate note: if switched to live, ONLY_MF_ALLOW must include VALLEY or orders
REM             will be silently blocked (same class of incident as 7/14).
REM  KILL SWITCH: create C:\stock_bot\config\valley_off.flag -> next start runs shadow.
REM        Intraday stop = C:\stock_bot\config\manual_buy_block.flag (shared with
REM        crash/captain engines - blocks buys NOW; sells keep working).
REM  Order isolation rqname = VALLEY_ (separate from CRASHFLOW_ / captain / deep-bottom).
REM  Size: 300,000 x 6 slots, SHARED with crash engine's pool (SHARED_MAX_SLOTS=6
REM        must match crash cmd's value - do not diverge, same pool file).
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set VH_LIVE=YES
REM kill switch - valley_off.flag forces shadow even if VH_LIVE above is YES
if exist C:\stock_bot\config\valley_off.flag set VH_LIVE=NO
REM shared capital pool with crash engine - same CAP/slots values as crash cmd
set VH_CAP=300000
REM 2026-07-19 user: day-1 live sizing = 1 SHARE per name (300k KRW "is the minimum,
REM   too much" for an unproven engine). Remove this line to roll back to 300k sizing.
set VH_QTY_FIX=1
REM 2026-07-19 late night user: 3rd gate = base-breakout (coil + volume burst + retest
REM   limit entry, own exit +2%/-1.5%/15:10). Backtest 26d PF 1.18. VH_BB=NO kills it.
set VH_BB=NO
set VH_SLOTS=6
set SHARED_MAX_SLOTS=6
REM Gate2/general universe remains 700eok+. Gate1 09:00-09:20 has its own wider
REM 100eok+ pool plus a 1000eok market-cap safety floor.
set VH_PVAL_MIN=700
set VH_PVAL_MAX=20000
set VH_MORNING_PVAL_MIN=100
set VH_MORNING_MCAP_MIN=1000
set VH_MORNING_MCAP_MAX_AGE_DAYS=7
set VH_GAP_TH=-3
REM 2026-07-19 late-night unified patch: VH_SELL_CHE/VH_DEFENSE/VH_TRAIL/VH_STOP/VH_DROP
REM   removed - dead in code now (STOP/TARGET_PROFIT_PCT/DROP filter deleted, DEFENSE
REM   replaced by MA5 reclaim-then-breach state machine in code, hard stop is -2.5%
REM   from valley_low_buy_v1.REBUY_STOP, no separate env for it).
REM schedule - 2026-07-18 night: low-anchor logic replaced with ma5-above-peak based
REM   trigger. Task trigger repeats every 20 min (see XML) so this process restarts
REM   through the whole window instead of running once - ledger reload on restart
REM   already handles continuity.
REM 2026-07-19: RUN_SEC 1290 -> 1190. 1290 (21.5min) overran the 20-min trigger
REM   interval and the task policy is IgnoreNew, so every other trigger was dropped:
REM   21.5min on / 18.5min DEAD, repeating. 1190 exits ~10s before the next trigger.
REM 2026-07-20 LIVE day-1: 1190 STILL not enough - process teardown (broker cleanup,
REM   final writes) ran past the :00 trigger, so 09:20 and 10:00 firings were BOTH
REM   skipped (log headers only at 09:00/09:40 - 20min on / 20min DEAD again).
REM   1190 -> 1140: loop exits 60s before the next trigger. User approved 10:5x.
REM   Task trigger also moved 0930 -> 0900 (+duration 6h -> 6h30m) same day, or the
REM   Gate1 window below could never run.
REM 2026-07-21: restart-gap redesign (user-approved). _run_hidden.vbs launched cmd
REM   ASYNC (sh.Run ...,False) so Task Scheduler only tracked wscript.exe's near-
REM   instant lifetime, not python.exe's - MultipleInstances=IgnoreNew gave ZERO real
REM   protection against overlap. Fixed with a Valley-only sync wrapper
REM   (_run_hidden_sync.vbs, ...,True) wired into this task's Action (other engines'
REM   tasks untouched). RUN_SEC raised to 30000 (comfortably covers 0900->END_HM=1512,
REM   exit is END_HM-gated in code, not RUN_SEC-gated) so the SAME python.exe process
REM   now stays alive the whole session instead of restarting every 20min - the actual
REM   fix for the restart-gap. Trigger repeat interval separately changed 20min->1min
REM   (crash-recovery watchdog only; IgnoreNew now blocks it for real while alive).
REM   Strategy/entry/exit/order logic untouched (scope: execution structure only).
REM 2026-07-18 night: forced time-liquidation extended from 14:30 to 15:10 (user request)
REM 2026-07-19 late-night: new-entry window now hard-stops at 14:30 (was 14:20)
REM 2026-07-20: Gate1 integration - crash engine's 09:00 morning window absorbed into this
REM   engine (entry_gate=MORNING_CRASH, prev-close -5% basis). VH_ENTRY moved 0930->0900.
REM   Gate2 (entry_gate=VALLEY_PEAK, existing 5MA-high -5% basis) still starts at 0930 -
REM   Gate1 runtime end is explicitly set to 0920 below; Gate2 remains 0930.
REM   crash_flow_live_v1.py itself is NOT touched/disabled yet - stays live in parallel
REM   until this engine's Gate1 shadow results are verified (user decision 2026-07-20).
set VH_ENTRY=0900
set VLA_ENTRY=0900
REM 2026-07-24 owner: Gate1 morning crash arms at previous-close -4% or lower.
set VLA_GATE1_ARM_PCT=-4
REM 2026-07-24 owner: no new MORNING_CRASH entries after 09:20; hold until 09:30
REM unless the entry-price -2% hard stop is hit.
set VLA_GATE1_END=0920
set VLA_GATE2_START=0930
set VH_MORNING_EXIT=0930
set VH_MORNING_STOP=-2
set VH_MORNING_REV_WATCH_SEC=10
set VH_SIDE_STALE_SEC=6
set VLA_GATE1_FAST=YES
set VLA_FAST_MIN_SEC=2
set VLA_FAST_MAX_SEC=6
set VLA_FAST_CONFIRM_SEC=2
set VLA_FAST_REBOUND_LO=0.6
set VLA_FAST_REBOUND_HI=3.0
set VLA_FAST_MIN_MONEY=10000000
set VLA_FAST_MIN_BUY_RATIO=0.70
set VH_ENTRY_END=1430
REM 2026-07-22 owner: retire Gate2 (VALLEY_PEAK, 5MA-high pullback) - CAPTAIN2 live
REM   covers money-driven rebounds better. Gate1 (morning crash) + BB gate + sells
REM   untouched. Rollback: delete this line (code default VH_GATE2=YES).
set VH_GATE2=NO
set VH_EXIT=1510
set VH_END=1512
set VH_LOOP_SEC=2
set VH_RUN_SEC=30000
REM 2026-07-21 TEMP TEST was VH_MFE_ENABLE=YES (MONEY_FLOW entry in valley).
REM 2026-07-22 owner: reverted ("CAPTAIN2 takes it") - money-flow hunting is now
REM   CAPTAIN2's exclusive job. Code default is NO; line kept explicit for clarity.
set VH_MFE_ENABLE=NO
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\valley_hunter_live_v1.py >> C:\stock_bot\data\LOG\sched_VALLEY_HUNTER_LIVE.log 2>&1

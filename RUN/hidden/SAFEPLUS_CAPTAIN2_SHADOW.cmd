@echo off
REM ============================================================================
REM  CAPTAIN2 RESET Money Flow Engine - LIVE                    2026-07-22
REM ----------------------------------------------------------------------------
REM  2026-07-22 evening: SHADOW -> LIVE by owner's explicit order ("shadow gets
REM  forgotten - apply live now"). 1 share x max 6 slots (account-shared via
REM  shared_slots.json). All 7/22 surgeries included: FID15 real-side calc,
REM  60s rolling exit, sustained-sell 15s, step trail, dryup exit, accel-hold
REM  guard, MA hold-permit, big-money surge floor, persistence gate.
REM
REM  Kill switch: create C:\stock_bot\config\captain2_off.flag -> forces SHADOW
REM  (same pattern as valley_off.flag). manual_buy_block.flag blocks new buys.
REM  Morning-flat safety: crash_flat_v1.py 09:43 account pass now EXCLUDES
REM  codes held by captain2 state (patched 7/22, valley pattern).
REM
REM  Order gates this process must pass (broker_client runs in-process):
REM   - ONLY_MF_ALLOW must contain CAPTAIN2 (set below; setx also done 7/22)
REM   - SAFEPLUS_MIN_PRICE=10000 (system) == engine's own 10k floor, OK
REM   - SAFEPLUS_MIN_MARKETCAP relaxed to 50B KRW for THIS process only:
REM     owner spec allows exactly two market filters (price>=10k, day
REM     value>=10B KRW); the system 100B mcap gate would silently block
REM     spec-valid buys. 50B follows the 7/13-14 MFLOW precedent; sub-50B
REM     micro caps stay blocked.
REM  Trail steps 2:1.0,4:1.25,7:1.5 - delegated choice (owner: "you decide"):
REM   today's replay showed the 0.8% first band shakes out big runners early
REM   (Samhyun +0.29% vs +3.94%); widened first/mid bands toward today's
REM   tournament winner (single 2.0/1.5) while keeping the step structure.
REM  ASCII-only REM before SET lines (cp949 parse issue).
REM ============================================================================
set CAPTAIN2_LIVE=YES
if exist C:\stock_bot\config\captain2_off.flag set CAPTAIN2_LIVE=NO
set CAPTAIN2_QTY_FIX=1
set CAPTAIN2_MAX_POSITIONS=6
REM Monday C2-01 one-share validation: one order attempt, all other live entry lanes isolated.
set CAPTAIN2_C2_01_ON=1
set CAPTAIN2_C2_01_MAX_ORDER_ATTEMPTS=1
set CAPTAIN2_C2_01_SIGNAL_MAX_AGE_SEC=5
set CAPTAIN2_EARLY_ON=0
set CAPTAIN2_ENTRY_START=2400
set CAPTAIN2_BASE_ON=0
set CAPTAIN2_REACCEL_START=0930
set CAPTAIN2_EARLY_END=0919
REM EARLY uses the qualified pre-open watch plus live FID15 inflow speed.
REM Three routes: direct, >=3pct gap, or below-open dip reclaim. No chase above open +3pct.
set CAPTAIN2_EARLY_MAX_ABOVE_OPEN_PCT=3.0
set CAPTAIN2_EARLY_GAP_MIN_PCT=3.0
set CAPTAIN2_EARLY_DIP_NO_NEW_SEC=2
set CAPTAIN2_EARLY_DECISION_HM=0920
set CAPTAIN2_EARLY_FORCE_EXIT_HM=0930
set CAPTAIN2_EARLY_TREND_MIN_BUY_RATIO=0.52
set CAPTAIN2_EARLY_TREND_SPEED_FRAC=0.5
REM Theme leader is a ranking bonus, never a hard exclusion.
set CAPTAIN2_THEME_LEADER_BONUS_ON=1
REM Completed 3m re-breakout + line hold + FID15 dominance + VWAP -> common 1-share order pool.
set CAPTAIN2_REACCEL_LIVE_ON=0
set CAPTAIN2_LOW_SEARCH_MAX=30
set CAPTAIN2_BUY_MAX_SEC=30
REM 0 = unlimited daily entries (rotation must not stop)
set CAPTAIN2_MAX_ENTRIES=0
REM Rotation capital: current holdings + pending buys <= 2,000,000 KRW; sold capital is reusable.
set CAPTAIN2_MAX_ACTIVE_CAPITAL_KRW=2000000
REM Test sample collection: do not stop new entries on daily/consecutive realized losses.
set CAPTAIN2_MAX_DAILY_LOSS_KRW=0
set CAPTAIN2_MAX_CONSECUTIVE_LOSSES=0
REM RAID 3m MA rider: arm when MA5/MA10 meet upward and MA20 rises.
REM General exits resume below MA20; hard stop and 15:10 exit always remain first.
set CAPTAIN2_MA3_RIDER_ON=1
set CAPTAIN2_MA3_CONVERGE_PCT=0.5
REM PULL high-zone block: require >=2pct depth and buy only in lower/middle 60pct.
set CAPTAIN2_PULL_MIN_DEPTH_PCT=2.0
set CAPTAIN2_PULL_MAX_RECOVERY_PCT=60
REM 2026-07-24 owner "fix the problems": widen trail bands toward measured normal
REM   pullback depth (7/23 leader study: median 2.4pct / p90 6.5pct). Old first
REM   band 1.0 sold HLB on a 1.4pct dip (kept rising after). Rollback: restore
REM   previous line 2:1.0,4:1.25,7:1.5
set CAPTAIN2_TRAIL_STEPS=2:1.5,4:2.0,7:2.5
REM 2026-07-22 night sweep (6 variants, today's 1s replay, final code): dryup confirm
REM   30s->60s = best balance. win 41% (best), cost-after -44.5%->-26.8%, dryup stays
REM   primary exit (22/39), stops 3->5. frac 0.1 and OFF rejected (0.1: win 35%,
REM   OFF: 8 hard-stops = abandons "exit when money leaves"). One declining morning
REM   of data - re-verify with live FID15 data at tomorrow's settlement.
set CAPTAIN2_DRYUP_CONFIRM_SEC=60
REM owner order 7/22: new entries end 14:20 (holding/sell management continues to force exit)
set CAPTAIN2_ENTRY_END=1420
REM owner order 7/23 morning: force exit 15:25 -> 15:10 (unified with valley 15:10 liquidation)
set CAPTAIN2_FORCE_EXIT=1510
set ONLY_MF_ALLOW=EODGAP,MFLOWCAP,VALLEY,GAPTUKI,CAPTAIN2
set SAFEPLUS_MIN_MARKETCAP=50000000000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\CAPTAIN2_MONEYFLOW_ENGINE_V1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_SHADOW.log 2>&1

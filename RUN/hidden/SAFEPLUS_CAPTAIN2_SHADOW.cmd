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
REM 0 = unlimited daily entries (rotation must not stop)
set CAPTAIN2_MAX_ENTRIES=0
set CAPTAIN2_TRAIL_STEPS=2:1.0,4:1.25,7:1.5
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

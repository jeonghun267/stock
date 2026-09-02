@echo off
REM Independent Strategy 01. Live buys require the separate owner approval flag.
set PYTHONDONTWRITEBYTECODE=1
set S01_LIVE=YES
REM Owner 2026-08-27: retire legacy EARLY/STRONG and FOLLOW; keep ROCKET/PULLBACK order-zero until replay passes.
set S01_LEGACY_ENTRY_LIVE=NO
REM Owner 2026-08-27 conditional pre-approval, executed after 20260828 replay PASS.
set S01_ENTRY_V3_MODE=LIVE
set S01_ROCKET_LIVE=NO
REM Owner 2026-08-13: MA5 trend hold permanently ON (S01 only; profit>0 AND price>MA5 AND MA5 rising AND price>=MA10 holds vs peak/flow exits; hard stop and time exit stay first). UNVERIFIED until the 2026-08-14 production replay.
set S01_MA5_TREND_HOLD_DATE=*
REM S01 trend priority remains SHADOW until current-path PROD_REPLAY passes.
set S01_TREND_PRIORITY_MODE=SHADOW
REM Owner wiring: always-on allocation after current-path PROD_REPLAY PASS; activation remains SHADOW until then.
set S01_MAX_SLOTS=6
set S01_ROCKET_MAX_SLOTS=3
set S01_PULLBACK_MAX_SLOTS=3
set S01_MAX_DAILY_CODES=6
set S01_MAX_CYCLES_PER_CODE=2
set S01_MAX_SELL_RETRIES=3
set S01_SIGNAL_MAX_AGE_SEC=5
set S01_SNAPSHOT_MAX_AGE_SEC=4
set S01_BOARD_MAX_AGE_SEC=8
set S01_FILL_WAIT_SEC=8
set ONLY_MF_ALLOW=STRATEGY01
set SAFEPLUS_MIN_PRICE=10000
set SAFEPLUS_MIN_MARKETCAP=50000000000
REM Wake prerequisites only on weekdays from 08:15 through 09:19.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_01_bootstrap_v1.py
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_live_gate_launcher_v1.py --strategy S01 >> C:\stock_bot\data\LOG\sched_STRATEGY01_LIVE.log 2>&1

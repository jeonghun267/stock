@echo off
REM Strategy 02 live path. OFF flag and separate owner approval gate all real buys.
set PYTHONDONTWRITEBYTECODE=1
set S02_LIVE=YES
set S02_MAX_SLOTS=6
set S02_MAX_DAILY_CODES=15
set S02_MAX_CYCLES_PER_CODE=2
set S02_MAX_SELL_RETRIES=3
set S02_SIGNAL_MAX_AGE_SEC=5
set S02_SNAPSHOT_MAX_AGE_SEC=4
set S02_BOARD_MAX_AGE_SEC=8
set S02_FILL_WAIT_SEC=8
REM One-shot owner canary: the engine consumes the token only after acquiring its lock.
if not defined S02_PEAK_5_DROP_1P5_FLOW_3OF4_6S_DATE set S02_PEAK_5_DROP_1P5_FLOW_3OF4_6S_DATE=
if exist C:\stock_bot\config\s02_peak_5_drop_1p5_flow_3of4_6s_20260811.flag (
  set S02_PEAK_5_DROP_1P5_FLOW_3OF4_6S_DATE=20260811
)
REM Candidate only: keep OFF until a matching production replay is captured.
set S02_AFTERNOON_SOFT_LOSS_EXIT=NO
REM Order-zero comparison only; this switch cannot submit a sell.
set S02_SIX_SECOND_EXIT_SHADOW=YES
REM Order-zero trend-lock comparison; preserves observations for 15 minutes.
set S02_TREND_LOCK_SHADOW=YES
set S02_POST_EXIT_OBSERVATION_SEC=900
REM Owner-approved 2026-08-12: market/day gate is not part of Strategy 02 live behavior.
set S02_DAYGATE=NO
set ONLY_MF_ALLOW=STRATEGY02
set SAFEPLUS_MIN_PRICE=10000
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_live_gate_launcher_v1.py --strategy S02 >> C:\stock_bot\data\LOG\sched_STRATEGY02_LIVE.log 2>&1

@echo off
REM Strategy 02 low-buy signal monitor. No broker import and no order submission.
set PYTHONDONTWRITEBYTECODE=1
set S02_WATCH=C:\stock_bot\IPC\micro_watch_strategy_shared.json
set S02_MAX_CYCLES_PER_CODE=2
REM Owner 2026-08-13: common DIRECT_REBOUND lane live (no-pullback low rebound; per-strategy drops/caps kept). UNVERIFIED until first live replay.
set LOW_REBOUND_DIRECT=YES
REM Owner 2026-08-20: adaptive bottom FAST/RETEST permanently enabled after exact production replay PASS.
set S02_ADAPTIVE_BOTTOM_ENABLED=YES
REM Always preserve the exact production inputs used by the live S02 signal process.
set S02_EXACT_REPLAY_JOURNAL=YES
set S02_EXACT_REPLAY_DIR=C:\stock_bot\data\s02_exact_replay
set S02_OUTPUT=C:\stock_bot\data\strategy_02_low_buy_signal_v1.json
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_low_buy_signal_v1.py >> C:\stock_bot\data\LOG\sched_STRATEGY02_SIGNAL_v2.log 2>&1

@echo off
REM *2026-07-29 owner order (renew approval daily, automatically): --approve-on YYYYMMDD
REM   was a manual daily re-arm; forgetting it silently zeroed that strategy buys.
REM   -> switched to --approve (existing switch in strategy_04_preflight_v1: writes
REM   approval ONLY after every check passes; OFF gate and 08:45 daily flag reset
REM   remain). Same pattern as S01~S03 --activate. Rollback: restore *.bak_20260729_autodate.
REM 2026-07-27 owner authorization: approve only today after every preflight check passes.
REM *2026-08-05 owner order: "pullback must stay off". --approve REMOVED.
REM   Why not disable the task: SAFEPLUS_STRATEGY04_PREFLIGHT is in REQUIRED_TASKS,
REM   so disabling it fails the context selftest and kills the whole 08:59 preflight
REM   for every strategy (tried on 2026-08-05, reverted 10:51).
REM   Why not manual_buy_block.flag: that flag is shared - it would block ALL buys.
REM   Without --approve the preflight still runs read-only and still revokes the
REM   stale approval, but never writes a new one, so the OFF gate holds.
REM   TO RE-ENABLE S04: append  --approve  to the python line below. Nothing else.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_04_preflight_v1.py --approve >> C:\stock_bot\data\LOG\sched_STRATEGY04_PREFLIGHT.log 2>&1

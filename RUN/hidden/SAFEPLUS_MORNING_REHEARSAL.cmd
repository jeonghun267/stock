@echo off
REM SAFEPLUS morning startup rehearsal - read only, ZERO orders, ZERO Kiwoom TR.
REM Runs 08:30 Mon-Fri, 30 minutes before the real 08:59 preflight, so anything
REM found here can still be fixed before the market opens.
REM
REM Why it exists (2026-08-05): four regressions from the previous day all
REM detonated at the next morning's first start. A running process keeps the old
REM code in memory, so the day you edit looks fine; the next morning it dies.
REM The 388 unit tests that night caught none of them.
REM
REM Checks: sys.path bootstrap on .cmd entry points, unregistered order_prefix
REM (the guard fails closed with no log), stale outputs, ModuleNotFoundError in
REM today's logs, syntax, required tasks enabled.
REM Pops a message box on FAIL - silent failure was the core of the incident.
REM Rollback: schtasks /delete /tn SAFEPLUS_MORNING_REHEARSAL /f
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\morning_preflight_rehearsal_v1.py >> C:\stock_bot\data\LOG\sched_MORNING_REHEARSAL.log 2>&1

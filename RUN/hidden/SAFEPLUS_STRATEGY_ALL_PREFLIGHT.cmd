@echo off
REM Read-only checks first; all three approvals change only after every check passes.
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_all_auto_live_preflight_v1.py --activate >> C:\stock_bot\data\LOG\sched_STRATEGY_ALL_PREFLIGHT.log 2>&1
if errorlevel 1 exit /b %errorlevel%
REM Strategy 02 now opens at 09:00. Existing 09:20 tasks remain as guarded recovery.
wscript.exe //B "C:\stock_bot\RUN\_run_hidden.vbs" "C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_SIGNAL.cmd"
wscript.exe //B "C:\stock_bot\RUN\_run_hidden.vbs" "C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd"

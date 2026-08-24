@echo off
REM S06 fail-closed auto release: exact replay -> truth gate -> atomic manifest swap.
cd /d C:\stock_bot\RUN
set PYTHONDONTWRITEBYTECODE=1
set LOW_REBOUND_DIRECT=YES
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s06_auto_replay_report_v1.py >> C:\stock_bot\LOG\sched_S06_AUTO_PROMOTE.log 2>&1
if errorlevel 1 exit /b 3
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\trading_report_truth_gate_v1.py C:\stock_bot\reports\verified_replay\s06_current_buy_latest.json >> C:\stock_bot\LOG\sched_S06_AUTO_PROMOTE.log 2>&1
if errorlevel 1 exit /b 4
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s06_atomic_promote_v1.py --report C:\stock_bot\reports\verified_replay\s06_current_buy_latest.json >> C:\stock_bot\LOG\sched_S06_AUTO_PROMOTE.log 2>&1
if errorlevel 1 exit /b 5
exit /b 0

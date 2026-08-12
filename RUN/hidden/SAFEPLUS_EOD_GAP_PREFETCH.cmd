@echo off
cd /d C:\stock_bot
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
C:\Python310-32\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py prefetch >> C:\stock_bot\data\LOG\eod_gap_live.log 2>&1
exit /b %errorlevel%

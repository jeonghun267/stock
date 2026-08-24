@echo off
REM [2026-06-19] Leader screener (READ-ONLY) - daily pre-market 08:50
C:\python310\python.exe -X utf8 C:\stock_bot\MONITOR\leader_screener_v1.py >> C:\stock_bot\LOG\leader_screener.log 2>&1

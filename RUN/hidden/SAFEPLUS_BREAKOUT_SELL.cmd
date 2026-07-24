@echo off
REM SAFEPLUS breakout EOD exit - 15:18 once.
REM ARMED LIVE 2026-06-26. Rollback to paper: set BRK_LIVE=NO below.
set BRK_LIVE=YES
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\breakout_live_executor_v1.py sell >> C:\stock_bot\data\LOG\breakout_live_run.log 2>&1

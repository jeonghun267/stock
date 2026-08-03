@echo off
REM Weekday logon catch-up. It exits without action outside 08:15-09:19.
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_01_bootstrap_v1.py

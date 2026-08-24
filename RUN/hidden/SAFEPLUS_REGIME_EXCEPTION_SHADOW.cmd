@echo off
REM S01/S02/S03 crash-regime evidence recorder. ORDER ZERO; no broker import.
C:\python310\python.exe -B C:\stock_bot\RUN\regime_exception_shadow_recorder_v1.py >> C:\stock_bot\data\LOG\sched_REGIME_EXCEPTION_SHADOW.log 2>&1

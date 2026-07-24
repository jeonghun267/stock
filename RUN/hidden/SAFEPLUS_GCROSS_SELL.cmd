@echo off
REM SAFEPLUS golden-cross 당일청산 - 15:18 force EOD sell. ★PAPER(주문0). 오버나잇 방지.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\golden_cross_live_executor_v1.py sell >> C:\stock_bot\data\LOG\golden_cross_live_run.log 2>&1

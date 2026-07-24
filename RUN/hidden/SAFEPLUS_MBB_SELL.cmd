@echo off
REM SAFEPLUS MBB auto executor - EOD force sell backstop 15:18.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_base_breakout_executor_v1.py sell_eod >> C:\stock_bot\data\LOG\mbb_pick_run.log 2>&1

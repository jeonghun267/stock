@echo off
set GAPLEAD_LIVE=YES
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\gap_leader_pullback_executor_v1.py sell >> C:\stock_bot\data\LOG\gap_leader_pullback_run.log 2>&1

@echo off
REM Afterhours common observer - MORNING. Read-only, ZERO Kiwoom TR, no orders.
REM Owner-approved 2026-07-28. Self-exits at AH_END_HM.
set AH_END_HM=0905
set AH_SAMPLE_SEC=5
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\afterhours_observer_v1.py >> C:\stock_bot\data\LOG\afterhours_observer.log 2>&1
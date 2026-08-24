@echo off
REM S02 adaptive-bottom observer: read-only, order zero, not wired to a live launcher.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_adaptive_bottom_shadow_v1.py >> C:\stock_bot\data\LOG\s02_adaptive_bottom_shadow.log 2>&1

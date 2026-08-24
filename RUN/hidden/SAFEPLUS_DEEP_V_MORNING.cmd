@echo off
REM SAFEPLUS deep-V scalp shadow - every 1min market hours. READ-ONLY, order=0.
REM Detects KOSDAQ leader deep-V (-6pct drop then bounce), logs bottom chejan strength for forward study.
C:\python310\python.exe -X utf8 C:\stock_bot\MONITOR\deep_v_morning_scalp_shadow_v1.py >> C:\stock_bot\data\LOG\deep_v_morning_shadow_run.log 2>&1

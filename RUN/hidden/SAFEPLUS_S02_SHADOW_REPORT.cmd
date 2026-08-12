@echo off
REM SAFEPLUS S02 low-finding shadow comparison report - read only, NO ORDERS.
REM Runs 15:45 Mon-Fri, after the close, and compares four paths:
REM   live (floor 1.0 / cap 1.5 / observe 60s / flow ON)
REM   A    (floor 0.5 / cap 1.5 / observe 0 / flow ON)
REM   B    (price only - the three SIX flow gates bypassed)
REM   C    (rebound threshold scales with the drop size)
REM Key metric is entry_gap_pct: how far above the low the signal fired.
REM Pops a message box once, when three shadow days have accumulated.
REM Rollback: schtasks /delete /tn SAFEPLUS_S02_SHADOW_REPORT /f
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\s02_shadow_compare_v1.py >> C:\stock_bot\data\LOG\sched_S02_SHADOW_REPORT.log 2>&1

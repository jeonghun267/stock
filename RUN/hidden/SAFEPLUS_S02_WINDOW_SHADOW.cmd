@echo off
REM S02 window-reset shadow. Read-only, ZERO Kiwoom TR. Mon-Fri 09:00, self-exits 15:30.
REM Owner-approved 2026-07-28. Observes only - never touches live code, state, or orders.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_02_window_shadow_v1.py >> C:\stock_bot\data\LOG\s02_window_shadow.log 2>&1
@echo off
REM Deep-bottom bottom-confirmation SIGNAL RECORDER (shadow, NO ORDERS, TR 0).
REM Records che_str / ask_tot / bid_tot / imb / 1m-bar wick / decel at the moment a deep-bottom
REM candidate enters the entry band. Fills 15/30/60min results. Consumed by nobody yet.
REM Rollback: disable task SAFEPLUS_DEEP_SIGNAL_REC
REM [PATH-FIX 2026-08-05] python._pth has only '.', so the script folder is NOT
REM on sys.path. Without this cd the recorder dies at
REM   ModuleNotFoundError: No module named 'ma3_backfill_v1'
REM and don_maek 1-minute bars stop updating, which breaks the shared
REM rising-hold (ma3_common_v1) for every strategy and blocks S05 preflight.
cd /d C:\stock_bot\RUN
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\deep_bottom_signal_recorder.py >> C:\stock_bot\data\LOG\sched_DEEP_SIGNAL_REC.log 2>&1

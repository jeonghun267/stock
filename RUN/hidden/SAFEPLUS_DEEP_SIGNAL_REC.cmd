@echo off
REM Deep-bottom bottom-confirmation SIGNAL RECORDER (shadow, NO ORDERS, TR 0).
REM Records che_str / ask_tot / bid_tot / imb / 1m-bar wick / decel at the moment a deep-bottom
REM candidate enters the entry band. Fills 15/30/60min results. Consumed by nobody yet.
REM Rollback: disable task SAFEPLUS_DEEP_SIGNAL_REC
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\deep_bottom_signal_recorder.py >> C:\stock_bot\data\LOG\sched_DEEP_SIGNAL_REC.log 2>&1

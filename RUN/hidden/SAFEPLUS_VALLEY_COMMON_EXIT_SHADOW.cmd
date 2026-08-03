@echo off
REM Valley MORNING_CRASH vs Captain2 common-exit observer.
REM ORDER 0: this process never imports the broker and never submits an order.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\valley_common_exit_shadow_v1.py >> C:\stock_bot\data\LOG\sched_VALLEY_COMMON_EXIT_SHADOW.log 2>&1

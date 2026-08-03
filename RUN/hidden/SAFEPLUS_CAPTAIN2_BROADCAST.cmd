@echo off
REM Stockbot live broadcast - reads S01-S04 state/events + fills, writes Desktop snapshot.
REM Read-only, ZERO Kiwoom TR. Auto-started by scheduled task 09:00-15:30 Mon-Fri, every 1 min.
REM ASCII-only REM before any SET line (cp949 parse rule). No SET lines here anyway.
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\stockbot_live_broadcast_v1.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_BROADCAST.log 2>&1

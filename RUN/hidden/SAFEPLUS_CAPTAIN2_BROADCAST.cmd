@echo off
REM Live broadcast - reads fills CSV + captain2_state.json, writes Desktop snapshot.
REM Read-only, ZERO Kiwoom TR. Auto-started by scheduled task 09:00-15:30 Mon-Fri, every 1 min.
REM ASCII-only REM before any SET line (cp949 parse rule). No SET lines here anyway.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\captain2_live_broadcast.py >> C:\stock_bot\data\LOG\sched_CAPTAIN2_BROADCAST.log 2>&1

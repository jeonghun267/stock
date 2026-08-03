@echo off
REM [2026-06-19] Leader pick outcome tracker (READ-ONLY) - daily EOD 16:30 after eod collected
C:\python310\python.exe -X utf8 C:\stock_bot\MONITOR\leader_track_v1.py >> C:\stock_bot\LOG\leader_track.log 2>&1

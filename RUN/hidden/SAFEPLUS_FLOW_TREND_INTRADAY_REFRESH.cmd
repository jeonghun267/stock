@echo off
setlocal
C:\python310\python.exe -u -B -X utf8 C:\stock_bot\RUN\flow_trend_intraday_refresh_v1.py --loop-sec 15 --until 15:20 >> C:\stock_bot\data\LOG\flow_trend_intraday_refresh_v1.log 2>&1
endlocal

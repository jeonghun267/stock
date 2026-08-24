@echo off
REM 유튜브 종가베팅 네 조건만 15:00~15:20 그림자 감시. 주문 호출 없음.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\youtube_eod_shadow_v1.py watch >> C:\stock_bot\data\LOG\youtube_eod_shadow.log 2>&1
exit /b %errorlevel%

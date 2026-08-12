@echo off
REM 유튜브 종가베팅 그림자: 다음 거래일용 400일 일봉/유통주식 준비 + 전일 신호 채점
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\youtube_eod_shadow_v1.py grade >> C:\stock_bot\data\LOG\youtube_eod_shadow.log 2>&1
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\youtube_eod_shadow_v1.py prepare >> C:\stock_bot\data\LOG\youtube_eod_shadow.log 2>&1

@echo off
REM [장전 예상체결가 감시] 08:30~09:00 매분. 전날 대장 구독→예상체결가 갭계산→갭업 대장 live 합류. 주문0.
REM  롤백: schtasks /delete /tn SAFEPLUS_PREMARKET_EXPECTED /f  또는 setx PREMARKET_MERGE_LIVE NO
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\premarket_expected_v1.py >> C:\stock_bot\data\LOG\premarket_expected.log 2>&1

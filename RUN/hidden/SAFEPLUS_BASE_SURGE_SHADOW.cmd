@echo off
REM [베이스+갑툭돌파 그림자 스크리너 — 친구님 2026-06-26] 매일 19:50(EOD확정 후).
REM   KOSDAQ 개별주만(ETF제외): 횡보베이스(6~18%) → 갑툭 +3%돌파 + 거래량 → 익일 눌림목 매수후보 모집단.
REM   관찰/검증용·주문0·실행기 연결없음. 출력 data/base_surge_shadow.txt + shadow CSV(전진추적).
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\base_surge_shadow_v1.py >> C:\stock_bot\data\LOG\base_surge_shadow_run.log 2>&1

@echo off
REM [스윙 셋업 그림자 스크리너 — 친구님 2026-06-25] 매일 19:45(EOD확정 후).
REM   KOSDAQ 개별주만(ETF제외): 갓 정배열+5일선위+종가강함+거래량2배 → 그림자 CSV(관찰/검증용·주문0·실행기 연결없음·스윙 막힘).
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\swing_jeongbae_shadow_v1.py >> C:\stock_bot\data\LOG\swing_jeongbae_shadow_run.log 2>&1

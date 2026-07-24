@echo off
REM [세력매집형 돌파 셋업 스크리너 — 친구님 2026-06-25] 매일 19:40(EOD확정+이평수렴 후).
REM   KOSDAQ 개별주만(ETF제외): 한달베이스→거래량2.5배터짐→음봉소화→양봉재개 → CSV발행(돌파실행기 _setup_zone_codes 병합).
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\base_thrust_setup_screener_v1.py >> C:\stock_bot\data\LOG\base_thrust_setup_run.log 2>&1

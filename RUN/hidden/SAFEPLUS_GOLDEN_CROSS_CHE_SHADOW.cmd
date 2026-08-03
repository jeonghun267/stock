@echo off
REM SAFEPLUS golden-cross chegang(체결강도) shadow - 09:00~15:20 every 3min. READ-ONLY, order=0.
REM 친구님 2026-06-30: 골든크로스(5선이 20선 상향돌파) 종목의 실시간 체결강도 누적 → 백테불가한 진짜 체결강도 검증.
REM 주문 절대 없음. micro_watch_goldencross.json 발행 + live_micro_snapshot 체결강도 기록만.
C:\python310\python.exe -X utf8 C:\stock_bot\MONITOR\golden_cross_che_shadow_v1.py >> C:\stock_bot\data\LOG\golden_cross_che_shadow_run.log 2>&1

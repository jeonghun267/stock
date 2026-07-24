@echo off
REM SAFEPLUS 아침 대장 그림자 - TOP10 장중(09:00~15:10) 계속 추격, 60선이탈/횡보5분 가상청산.
REM '무조건 매수가 맞는지' 검증용. ★주문 0·READ-ONLY. 출력 data/shadow/morning_leader/trades_<date>.csv
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_leader_shadow_v1.py >> C:\stock_bot\data\LOG\mlr_shadow_run.log 2>&1

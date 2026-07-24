@echo off
REM SAFEPLUS golden-cross 추세시작 executor - pick+manage 09:05~15:17 every 3min. ★PAPER(GCLIVE 미설정=NO·주문0).
REM 친구님 2026-06-30: 5/20 만나 오름 시작+60선↑+강한마감+체결강도120 → 당일 매수, 당일청산(15:18). 스윙 아님.
REM 실탄 전환은 검증 후 setx GCLIVE YES (지금은 페이퍼).
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\golden_cross_live_executor_v1.py pick >> C:\stock_bot\data\LOG\golden_cross_live_run.log 2>&1

@echo off
REM SAFEPLUS deep-V live executor - pick+manage every 1min 09:00-15:00.
REM Buys deep-V bottom (drop+bounce+dev5 bottomzone+chejan) until 10:30, manages exits all day, EOD sell 15:00.
REM ARMED LIVE 2026-06-26 (small amount). Rollback to paper: change next line to DEEPV_LIVE=NO.
set DEEPV_LIVE=YES
set DEEPV_CAP_KRW=150000
set DEEPV_MAX_POS=6
REM [딥 종일 2026-06-29 친구님 "오후 딥도 무조건·1순위"] 매수마감 10:30->14:50(오후 깊은딥도 잡음·EOD매도 15:00 유지)
set DEEPV_BUY_CUTOFF=1450
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\deep_v_live_executor_v1.py pick >> C:\stock_bot\data\LOG\deep_v_live_run.log 2>&1

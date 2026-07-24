@echo off
REM ============================================================================
REM  moneyflow_watch_v1 - zero orders, zero TR
REM ----------------------------------------------------------------------------
REM  2026-07-20(밤) 친구님 "돈맥 선별기 기준으로 워처 만들어줘" — money_flow_board_v1.py
REM  (돈맥 선별기) 출력을 읽기전용으로 지켜보며 종목별 최초포착·이탈시각만 기록.
REM  money_flow_board_v1.py 자체는 무수정. micro_rank_engine의 TOP20 진입시각과
REM  나중에 대조해 "선행시간"(몇 초 먼저 잡았는지) 계산하는 재료로 사용.
REM  Task: Mon-Fri 08:59, ExecutionTimeLimit 6h40m 자동종료.
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\moneyflow_watch_v1.py >> C:\stock_bot\data\LOG\sched_MONEYFLOW_WATCH.log 2>&1

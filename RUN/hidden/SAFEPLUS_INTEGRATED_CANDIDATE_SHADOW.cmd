@echo off
REM ============================================================================
REM  integrated_candidate_engine_v1 SHADOW - zero orders, zero TR, zero SetRealReg
REM ----------------------------------------------------------------------------
REM  2026-07-20(밤) 친구님 승인: micro_rank_board.json 위에서 attention/valley/
REM  breakout/ma_pullback 4점수 산출. 읽기전용, micro_rank_engine 미수정.
REM  기존 전략(골짜기/돌파/캡틴)·broker_gateway 무접촉. 실전 연결은 별도 승인 후.
REM  Task: Mon-Fri 08:59(micro_rank_engine과 동시), ExecutionTimeLimit 6h40m 자동종료.
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\integrated_candidate_engine_v1.py >> C:\stock_bot\data\LOG\sched_INTEGRATED_CANDIDATE.log 2>&1

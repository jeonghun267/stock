@echo off
REM ============================================================================
REM  micro_rank_engine_v1 SHADOW - zero orders, zero TR, zero SetRealReg
REM ----------------------------------------------------------------------------
REM  2026-07-20(밤) 친구님 승인: 이미 구독 중인 실시간 종목을 재활용해 상대랭킹.
REM  live_micro_snapshot.json 읽기전용 -> micro_rank_board.json 출력만.
REM  기존 전략(골짜기/돌파/캡틴)·broker_gateway 무접촉. 실전 연결은 별도 승인 후.
REM  Task: Mon-Fri 08:57, 단일기동(반복없음), ExecutionTimeLimit 6h40m로 자동종료.
REM  micro_rank_engine의 60초 WARMUP이 09:00:15 공통 사전점검 전에 끝나도록 2026-07-27 조정.
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\micro_rank_engine_v1.py >> C:\stock_bot\data\LOG\sched_MICRO_RANK.log 2>&1

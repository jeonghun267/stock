@echo off
REM ============================================================================
REM  daily_shadow_report_v1 - zero orders, zero TR
REM ----------------------------------------------------------------------------
REM  2026-07-20(밤) 친구님 "매일매일 보고해줘야 된다" — micro_rank_engine +
REM  integrated_candidate_engine 그림자 관찰 결과를 매일 텍스트로 정리.
REM  실전 매매 엔진(골짜기/돌파/캡틴)은 참조하지 않음.
REM  Task: Mon-Fri 15:40(그림자 엔진 종료 후), 단일기동.
REM ============================================================================
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\daily_shadow_report_v1.py >> C:\stock_bot\data\LOG\sched_DAILY_SHADOW_REPORT.log 2>&1

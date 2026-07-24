@echo off
REM ============================================================
REM [통합 대장 리더 엔진 2026-07-03 친구님 "C안 통합"]
REM   MLR라이더 + FAST_LEADER 를 하나로 통합(두 엔진 69% 중복·발산테스트 확인).
REM   진입 = che>=100 & 역배열아님 & ( ①강한대장:cur>3분60선&이격<=7%  OR  ②개장로켓:is_up(5>=20선&현재가>시가)&과열(20선)<=8% )
REM   랭킹 = che desc(매수세 1순위) -> 품질점수 desc(동점가리기·MLR_FAST 팩터 재사용, 하드필터 없이 가점만)
REM   청산 = 하드-3% -> 3분유예 -> vol_exit(수급·매수우위면 끌기) -> EOD 15:18
REM   TOPN 3 · CAP 30만 · 대장 top100 · 진입 09:00~11:00 · 매도 EOD까지
REM 안전: 대장필터·잡주게이트(broker단일점)·전역daily상한·재매수금지·실패상한·부분익절.
REM 롤백 = 아래 set UNIFIED_LEADER_LIVE 를 NO 로 or 이 태스크 비활성.
REM ============================================================
set UNIFIED_LEADER_LIVE=YES
set SAFEPLUS_CAP_KRW=300000
set UNIFIED_TOPN=10
set UNIFIED_LEADER_TOPN=100
set UNIFIED_END=1100
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\unified_leader_v1.py >> C:\stock_bot\data\LOG\unified_leader_run.log 2>&1

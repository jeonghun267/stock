@echo off
REM 장세 우선권 자동 판정 (주문 0) - 급상승일=1번 우선, 보통·급하락=6번·3번 우선
REM 문턱: 고저폭30 예상 갭 중앙값 +3%% (6개월 상위 10%% 경계, 조절: REGIME_SURGE_GAP_MED)
cd /d C:\stock_bot\RUN
C:\python310\python.exe regime_priority_judge_v1.py >> C:\stock_bot\LOG\sched_REGIME_PRIORITY.log 2>&1

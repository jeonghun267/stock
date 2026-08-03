@echo off
REM [2026-07-31 밤] 콘솔 숨김 래핑 - 원래 태스크가 python.exe 직접 실행이던 것을 vbs+cmd로 이전.
REM pythonw 전환은 print()가 터져 기각(8-6 검증에서 MA_FANOUT 즉사 실측). 출력은 로그로.
cd /d C:\stock_bot\RUN
C:\python310\python.exe "C:\stock_bot\RUN\ma_fanout_shadow_v1.py" >> C:\stock_bot\data\LOG\sched_MA_FANOUT_SHADOW.log 2>&1

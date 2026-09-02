@echo off
setlocal
REM ==[2026-09-02 owner-approved day-1 live]== 6종목x1주 소액. 재생검사만 첫날 대체.
REM   근거: AGENTS.md 5장 Bootstrap exception (owner-only, 2026-09-02 owner-added).
REM   S07M_DAY1_OVERRIDE 는 20260903 하루만 유효 - 날짜 불일치 시 자동 실효,
REM   9/4 부터는 정상 두 열쇠(전일 캡처 재생 PASS + ARM)로 복귀한다.
REM   롤백: 아래 세 줄을 지우고 set S07M_ARM=NO / set S07M_LIVE=NO 로 되돌린다.
set S07M_DAY1_OVERRIDE=20260903
set S07M_ARM=YES
set S07M_LIVE=YES
"C:\python310\python.exe" -B -X utf8 "C:\stock_bot\RUN\strategy_07_morning_launcher_v1.py" replay_auto >> C:\stock_bot\data\LOG\sched_S07_MORNING.log 2>&1
"C:\python310\python.exe" -B -X utf8 "C:\stock_bot\RUN\strategy_07_morning_launcher_v1.py" shadow --loop-sec 2 --until 11:35 >> C:\stock_bot\data\LOG\sched_S07_MORNING.log 2>&1
endlocal

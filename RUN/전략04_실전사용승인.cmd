@echo off
chcp 65001 >nul
title 전략 04 눌림목 실전사용 승인
echo.
echo [전략 04 — 눌림목]
echo - 1주, 공통 6슬롯, 총 회전한도 2,000,000원, 종목당 최대 6회
echo - 진입시간 10:00~12:00, 15:10 최종청산
echo - 실행하면 오늘 날짜의 실계좌 주문 승인을 만듭니다.
echo.
set /p S04_CONFIRM=계속하려면 정확히 실전승인 이라고 입력하세요:
if not "%S04_CONFIRM%"=="실전승인" (
  echo 승인하지 않았습니다. 전략 04는 주문 0 상태로 유지됩니다.
  pause
  exit /b 1
)
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\strategy_04_preflight_v1.py --approve
if not %errorlevel%==0 (
  echo 사전점검 실패. 승인 플래그를 만들지 않았습니다.
  pause
  exit /b 2
)
echo 오늘 전략 04 실전 승인이 완료되었습니다.
pause

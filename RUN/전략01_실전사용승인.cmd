@echo off
chcp 65001 >nul
title 새전략 01 실전사용 승인
echo.
echo [새전략 01 실전사용 승인]
echo - 월요일 자동 매수: 1주, 하루 최대 1회
echo - 상승보유/매도: 검증된 공통 엔진
echo - 캡틴2: 계속 OFF
echo - 이 승인은 실제 계좌 주문을 허용합니다.
echo.
set /p S01_CONFIRM=계속하려면 정확히 실전승인 이라고 입력하세요:
if not "%S01_CONFIRM%"=="실전승인" (
  echo 승인하지 않았습니다. 새전략 01은 주문 0 그림자로 실행됩니다.
  pause
  exit /b 1
)
if exist C:\stock_bot\config\strategy_01_off.flag move /Y C:\stock_bot\config\strategy_01_off.flag C:\stock_bot\config\strategy_01_off.flag.disabled >nul
>C:\stock_bot\config\strategy_01_live_approved.flag echo APPROVED_BY_OWNER
echo 관리자 권한으로 기존 캡틴2 예약을 끄고 새전략 예약을 확정합니다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\stock_bot\RUN\install_strategy01_tasks.ps1'"
if not %errorlevel%==0 (
  echo 예약작업 관리자 설치 확인이 필요합니다. 바탕화면의 자동시작 관리자설치를 실행하세요.
)
echo.
echo 승인 완료: 다음 예약 실행부터 새전략 01 실계좌 주문이 허용됩니다.
echo 컴퓨터를 켠 뒤 Windows 로그인과 키움 로그인을 완료해야 합니다.
pause

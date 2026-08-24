@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "SRC=%~dp0CAPTAIN2_MONEYFLOW_ENGINE_V1.py"
set "RUN=C:\stock_bot\RUN"
set "HIDDEN=C:\stock_bot\RUN\hidden"
set "PY=C:\Python310-32\python.exe"
set "TARGET=%RUN%\CAPTAIN2_MONEYFLOW_ENGINE_V1.py"
set "BACKUP=%RUN%\backup\captain2"

echo ============================================================
echo CAPTAIN2 SHADOW INSTALLER
echo - 기존 캡틴 파일을 덮어쓰지 않습니다.
echo - LIVE 연결을 하지 않습니다.
echo ============================================================

if not exist "%SRC%" (
    echo [ERROR] 원본 파일 없음: %SRC%
    pause
    exit /b 1
)

if not exist "%RUN%" (
    echo [ERROR] RUN 폴더 없음: %RUN%
    pause
    exit /b 1
)

if not exist "%PY%" (
    echo [ERROR] Python 없음: %PY%
    pause
    exit /b 1
)

if not exist "%BACKUP%" mkdir "%BACKUP%"
if not exist "%HIDDEN%" mkdir "%HIDDEN%"

if exist "%TARGET%" (
    for /f "tokens=1-4 delims=/-. " %%a in ("%date%") do set "D=%%a%%b%%c"
    for /f "tokens=1-3 delims=:., " %%a in ("%time%") do set "T=%%a%%b%%c"
    set "T=!T: =0!"
    copy /y "%TARGET%" "%BACKUP%\CAPTAIN2_MONEYFLOW_ENGINE_V1_!D!_!T!.py" >nul
    if errorlevel 1 (
        echo [ERROR] 기존 파일 백업 실패
        pause
        exit /b 1
    )
    echo [OK] 기존 파일 백업 완료
)

copy /y "%SRC%" "%TARGET%" >nul
if errorlevel 1 (
    echo [ERROR] RUN 복사 실패
    pause
    exit /b 1
)
echo [OK] 복사 완료: %TARGET%

"%PY%" -m py_compile "%TARGET%"
if errorlevel 1 (
    echo [ERROR] py_compile 실패. LIVE 연결 금지.
    pause
    exit /b 1
)
echo [OK] py_compile 통과

> "%HIDDEN%\SAFEPLUS_CAPTAIN2_SHADOW.cmd" (
    echo @echo off
    echo chcp 65001 ^>nul
    echo cd /d "C:\stock_bot\RUN"
    echo set CAPTAIN2_LIVE=NO
    echo set CAPTAIN2_QTY_FIX=1
    echo set CAPTAIN2_MAX_POSITIONS=1
    echo set CAPTAIN2_MAX_ENTRIES=3
    echo "C:\Python310-32\python.exe" "C:\stock_bot\RUN\CAPTAIN2_MONEYFLOW_ENGINE_V1.py"
)

echo [OK] SHADOW 실행 CMD 생성:
echo      %HIDDEN%\SAFEPLUS_CAPTAIN2_SHADOW.cmd
echo.
echo 주의:
echo 1. 작업스케줄러 등록은 아직 하지 않습니다.
echo 2. CAPTAIN2_LIVE=YES로 바꾸지 마십시오.
echo 3. Claude 점검 완료 후 전체 배선을 진행하십시오.
echo.
pause
exit /b 0

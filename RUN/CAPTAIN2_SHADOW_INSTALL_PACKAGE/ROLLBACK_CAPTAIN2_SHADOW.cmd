@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "TARGET=C:\stock_bot\RUN\CAPTAIN2_MONEYFLOW_ENGINE_V1.py"
set "LAUNCHER=C:\stock_bot\RUN\hidden\SAFEPLUS_CAPTAIN2_SHADOW.cmd"

echo CAPTAIN2 SHADOW 파일만 제거합니다.
echo 기존 morning_captain_live_v1.py 등은 건드리지 않습니다.

if exist "%TARGET%" del /f /q "%TARGET%"
if exist "%LAUNCHER%" del /f /q "%LAUNCHER%"

echo 제거 완료.
pause

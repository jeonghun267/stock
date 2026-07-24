@echo off
chcp 65001 >nul

REM SAFEPLUS bot manual start
REM Single source: run_safeplus_pipeline_0900.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\stock_bot\RUN\run_safeplus_pipeline_0900.ps1"

echo.
echo [OK] PIPELINE and watchdog started in background.
echo You can close this window.
pause

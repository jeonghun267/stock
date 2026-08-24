@echo off
set LOG=C:\stock_bot\data\LOG\eod_gap_prefetch_task_install.log
if not exist C:\stock_bot\data\LOG mkdir C:\stock_bot\data\LOG
echo [%date% %time%] install start > "%LOG%"
schtasks.exe /Create /TN "SAFEPLUS_EOD_GAP_PREFETCH" /TR "wscript.exe //B C:\stock_bot\RUN\_run_hidden_wait_exit.vbs C:\stock_bot\RUN\hidden\SAFEPLUS_EOD_GAP_PREFETCH.cmd" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:16 /F >> "%LOG%" 2>&1
echo PREFETCH_EXIT=%errorlevel% >> "%LOG%"

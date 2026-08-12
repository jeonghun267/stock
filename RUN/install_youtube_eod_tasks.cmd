@echo off
set LOG=C:\stock_bot\data\LOG\youtube_eod_task_install.log
if not exist C:\stock_bot\data\LOG mkdir C:\stock_bot\data\LOG
echo [%date% %time%] install start > "%LOG%"
schtasks.exe /Create /TN "SAFEPLUS_YOUTUBE_EOD_PREPARE" /TR "wscript.exe //B C:\stock_bot\RUN\_run_hidden.vbs C:\stock_bot\RUN\hidden\SAFEPLUS_YOUTUBE_EOD_PREPARE.cmd" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:40 /F >> "%LOG%" 2>&1
echo PREPARE_EXIT=%errorlevel% >> "%LOG%"
schtasks.exe /Create /TN "SAFEPLUS_YOUTUBE_EOD_WATCH" /TR "wscript.exe //B C:\stock_bot\RUN\_run_hidden_wait_exit.vbs C:\stock_bot\RUN\hidden\SAFEPLUS_YOUTUBE_EOD_WATCH.cmd" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 14:58 /F >> "%LOG%" 2>&1
echo WATCH_EXIT=%errorlevel% >> "%LOG%"

# run_pipeline_watchdog.ps1
# SAFEPLUS WATCHDOG 런처 — Task Scheduler 전용

# 중복 실행 방지
$running = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
           Where-Object { $_.CommandLine -like '*pipeline_watchdog*' }
if ($running) { exit 0 }

$d   = Get-Date -Format 'yyyyMMdd'
$log = "C:\stock_bot\DATA\LOG\watchdog_$d.log"
Set-Location 'C:\stock_bot\RUN'
& 'C:\Python310-32\python.exe' -X utf8 'C:\stock_bot\RUN\pipeline_watchdog.py' *>> $log

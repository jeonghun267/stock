@echo off
setlocal
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
rem Read-only data source early warning. Never edits flags or restarts tasks.
"C:\python310\python.exe" -X utf8 "C:\stock_bot\RUN\strategy_source_early_warning_v1.py" %*
exit /b %ERRORLEVEL%

@echo off
setlocal
cd /d C:\stock_bot
python -X utf8 RUN\broker_fill_outcome_recorder_v1.py >> data\LOG\broker_fill_outcome_audit.log 2>&1
exit /b %errorlevel%

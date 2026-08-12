@echo off
REM SAFEPLUS rider-gate daily report - read only, ZERO orders, ZERO Kiwoom TR.
REM Runs 15:45 Mon-Fri, after the 15:10 flush and the last audit write.
REM
REM Why it exists (2026-08-05 night): we measured for the first time WHERE the
REM rising-hold permit fails. On 8/5 the split was line-support 47%/42%,
REM buy-side 32%/32%, pass 22%/25% - so the buy-side gate rejects roughly 60%
REM of what clears line support. Nobody had measured that before.
REM But whether those rejections were RIGHT could not be told from one day:
REM the median 60s move was a single tick and S02 and S05 disagreed in sign.
REM So we collect the sample daily instead of guessing at the threshold.
REM
REM It never touches a decision. It only reads the hold_sell audit folder and
REM appends one row per position to \data\shadow\rider_gate_daily.csv.
REM Each row carries recon_pct: how well the reconstruction reproduces the
REM daily_ma_permit the engine actually wrote. Below 98 the row says trust=NO.
REM Rollback: schtasks /delete /tn SAFEPLUS_RIDER_GATE_REPORT /f
set PYTHONDONTWRITEBYTECODE=1
cd /d C:\stock_bot\RUN
C:\python310\python.exe -B -X utf8 C:\stock_bot\RUN\rider_gate_daily_report_v1.py >> C:\stock_bot\data\LOG\sched_RIDER_GATE_REPORT.log 2>&1

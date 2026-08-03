@echo off
REM [이평수렴 스캐너 일일 — 친구님 2026-06-23] 매일 19:30(EOD확정후). READ-ONLY·주문0.
C:\python310\python.exe -X utf8 C:\stock_bot\MONITOR\ma_convergence_scanner_v1.py >> C:\stock_bot\data\LOG\ma_convergence_scanner_run.log 2>&1

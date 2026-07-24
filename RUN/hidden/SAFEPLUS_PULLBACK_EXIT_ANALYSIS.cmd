@echo off
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_pullback_exit_rule_backtest.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_pullback_winner_features.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_pullback_hold_gate.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_mfe_bucket_study.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_pullback_profit_bucket.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_bucket_holdfeatures_v1.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1
C:\Python310-32\python.exe -X utf8 C:\stock_bot\MONITOR\run_survival_analysis_v1.py >> C:\stock_bot\LOG\pullback_exit_analysis.log 2>&1

@echo off
cd /d C:\stock_bot
type "C:\stock_bot\DOCS\claude_task_20260722_1600.txt" | "C:\Users\UserK\.local\bin\claude.exe" -p --permission-mode bypassPermissions --output-format text > "C:\stock_bot\DOCS\claude_task_20260722_1600_result.log" 2>&1

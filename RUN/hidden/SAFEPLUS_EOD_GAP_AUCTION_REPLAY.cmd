@echo off
REM Saved-input production decision replay. This command cannot place an order.
set EOD_GAP_LIVE=NO
set EOD_GAP_AUCTION_GATE_MODE=LIVE
set EOD_GAP_MAX_POS=3
set EOD_GAP_QTY_ONE_ALL=YES
set EOD_GAP_PORTFOLIO_V2=YES
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\eod_gap_live_executor_v1.py auction_replay >> C:\stock_bot\data\LOG\eod_gap_auction_capture.log 2>&1

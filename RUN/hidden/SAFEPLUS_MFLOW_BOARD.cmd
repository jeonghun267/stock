@echo off
REM Money-flow board (layer 2, supply). Read-only, no orders. Scans top MF_TOPN leaders for big-money inflow.
REM ASCII-only: Korean REM before a SET line breaks cmd parsing (UTF-8 read as cp949) and skips the SET.
REM Single-instance lock is in money_flow_board_v1.py __main__ (prevents pile-up under open TR congestion).
REM 2026-07-22 fix: captain-candidate calc window (_captain_map) was hardcoded 0902-0906,
REM one-shot per day with zero retry margin. 2026-07-21 the whole chain (board's own first
REM daily write + deep_signal_recorder's first bar) missed that 4-min window once, so
REM board["captain"] stayed empty ALL DAY (confirmed via daily_leader_board captain=0 at
REM close) - captain engine got zero buy candidates the entire session, no retry.
REM Widen end to 0920 to match captain's own ENTRY_END - gives the calc more chances to
REM catch a matching bar before captain stops accepting new buys anyway. Calc itself does
REM zero TR calls (pure in-memory over already-fetched bars), so the extra retries are cheap.
REM No trading condition (rise/hh/bull/che thresholds) touched - only WHEN it's allowed to try.
set MF_CAP_END=0920
set MF_TOPN=30
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\money_flow_board_v1.py >> C:\stock_bot\data\LOG\sched_MFLOW_BOARD.log 2>&1

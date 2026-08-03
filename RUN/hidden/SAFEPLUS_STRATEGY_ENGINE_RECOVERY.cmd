@echo off
REM ============================================================================
REM  Strategy engine crash-recovery relauncher (2026-07-27, owner approved).
REM  Task SAFEPLUS_STRATEGY_ENGINE_RECOVERY fires this every minute 09:02-15:12.
REM  Idempotent by design: each gate launcher re-checks today audit/approval/OFF,
REM  and each engine holds its own ProcessLock -> alive engine = instant exit 0,
REM  dead engine with positions = takeover in exit-only mode (resume built in).
REM ============================================================================
start "" /min cmd /c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY01_LIVE.cmd
start "" /min cmd /c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY02_LIVE.cmd
start "" /min cmd /c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd
start "" /min cmd /c C:\stock_bot\RUN\hidden\SAFEPLUS_STRATEGY04_LIVE.cmd

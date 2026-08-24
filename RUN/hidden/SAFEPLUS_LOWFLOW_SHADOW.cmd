@echo off
REM ============================================================================
REM  Low-anchored trade-strength SHADOW recorder      2026-07-16
REM ----------------------------------------------------------------------------
REM  User: "wire the shadow collection - low-anchored trade strength".
REM  Records, every morning 09:00-09:32 (orders 0, TR 0, snapshot polling only):
REM    per crash-universe stock (prev-day value 700eok-2jo, price 10k+):
REM    tick-rule buy/sell volume anchored at each intraday low, frozen at
REM    (a) low+150s survival point and (b) first touch of low+2.4 pct rebound,
REM    plus the legacy cumulative trade-strength at the same moment (A/B data).
REM  Output: data\shadow\lowflow_verdicts.csv (cumulative sample for the future
REM          entry-gate change: cumulative che 105 -> low-anchored dominance)
REM          data\shadow\lowflow_raw_YYYYMMDD.csv (1s raw for re-analysis)
REM  ASCII-only REM (cp949 parse issue). Batch must stay CRLF.
REM ============================================================================
set LF_START=0900
set LF_END=0932
set LF_POLL=1.0
set LF_FREEZE=150
set LF_REB_TH=2.4
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\crash_lowflow_shadow_v1.py >> C:\stock_bot\data\LOG\sched_LOWFLOW_SHADOW.log 2>&1

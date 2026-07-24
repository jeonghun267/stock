@echo off
REM ============================================================================
REM  Gaptuki-onset SHADOW recorder       2026-07-20 (user: make shadow, wire now)
REM ----------------------------------------------------------------------------
REM  Records 09:00-15:19 (orders 0, TR 0, snapshot 1s polling only):
REM  signal = 60min sideways (band<=3pct, 45+ bars) + FIRST break of 60min high
REM           + break bar +0.5pct up + bar value 5x avg per-min value + 0.5eok+
REM  entry proxy = first new tick after signal. Virtual tracking only:
REM  -2pct stop touch / +2 +3pct touch / 30-60-120min marks / max up-down.
REM  Evidence base: 26d 1min-archive study 2026-07-20 morning (chase=no edge,
REM  pullback median -1.53pct at ~12min, shallow-pullback rebreak 100pct).
REM  Output: data\shadow\gaptuki_onset_signals.csv
REM  ASCII-only REM (cp949 parse issue). Batch must stay CRLF.
REM ============================================================================
set GS_START=0900
set GS_END=1519
set GS_POLL=1.0
set GS_BAND_MAX=3.0
set GS_ONSET_RET=0.5
set GS_VOLX=5.0
set GS_MINVAL=50000000
set GS_STOP=-2.0
set GS_PXMIN=3000
set GS_DEDUP_MIN=30
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\gaptuki_onset_shadow_v1.py >> C:\stock_bot\data\LOG\sched_GAPTUKI_SHADOW.log 2>&1

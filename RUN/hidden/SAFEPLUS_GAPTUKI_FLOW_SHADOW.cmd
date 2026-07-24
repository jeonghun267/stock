@echo off
REM ============================================================================
REM  Gaptuki money-FLOW SHADOW (5-stage state machine)   2026-07-20
REM ----------------------------------------------------------------------------
REM  User integration-patch directive: independent module, existing engines
REM  untouched, Shadow -> verify -> live order enforced.
REM  Pipeline: 45min box(band<=3pct, range shrink, volume dry, d5-d20 gap<=3pct)
REM   -> spike (value 5x AND volume 5x AND tick-rule che>=130 AND price up)
REM   -> per-min money-flow scoring (che trend 3 / value pace 2 / volume 2)
REM   -> pullback check (box-low break / deep -2.5pct / money-dry = reject)
REM   -> restart confirm (+0.4pct off trough AND value 2x AND che>=110) = candidate.
REM  Program net-buy / orderbook feeds absent in IPC (checked 2026-07-20):
REM  spec items 4-5 scored 0 until feeds exist. Orders 0, TR 0. 1s polling.
REM  Output: data\shadow\gaptuki_flow_candidates.csv / gaptuki_flow_rejects.csv
REM  ASCII-only REM (cp949 parse issue). Batch must stay CRLF.
REM ============================================================================
set GF_START=0900
set GF_END=1519
set GF_POLL=1.0
set GF_BOX_MIN=45
set GF_BAND_MAX=3.0
set GF_DRY_RATIO=0.7
set GF_MA_GAP=3.0
set GF_VOLX=5.0
set GF_MINVAL=50000000
set GF_SPIKE_CHE=130
set GF_SPIKE_RET_MIN=0.3
set GF_PB_DEEP=-2.5
set GF_PB_CHE=90
set GF_REB=0.4
set GF_REB_CHE=110
set GF_TIMEOUT=40
set GF_PXMIN=3000
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\gaptuki_flow_shadow_v1.py >> C:\stock_bot\data\LOG\sched_GAPTUKI_FLOW_SHADOW.log 2>&1

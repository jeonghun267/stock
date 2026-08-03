@echo off
REM ==================================================================
REM  ★★★ 잠금(LOCKED) 2026-07-03 — 손대지 마세요 ★★★
REM ------------------------------------------------------------------
REM  사유: MLR라이더는 FAST_LEADER와 진입종목 69% 중복(발산테스트로 확인).
REM        큰 상승주는 둘 다 잡고 진입시각만 달랐음 -> 하나로 통합함.
REM        => 통합 엔진  unified_leader_v1.py (SAFEPLUS_UNIFIED_LEADER) 로 대체.
REM           MLR의 '60선 이격' 경로는 통합의 (1)강한대장 경로로 그대로 흡수됨.
REM  재가동 금지. 꼭 되살리려면: 먼저 통합엔진을 끄고(중복매수 방지) 아래 원본 복구.
REM      [원본]
REM        set MLR_LIVE=YES
REM        set MLR_TOPN=2
REM        C:\python310\python.exe -X utf8 C:\stock_bot\RUN\morning_leader_rider_v1.py >> C:\stock_bot\data\LOG\mlr_rider_run.log 2>&1
REM  ※ morning_leader_rider_v1.py 파일 자체는 삭제금지 —
REM    통합엔진/GC560/반전엔진이 헬퍼(_broker/_cur/_che 등)로 import 하고 있음.
REM ==================================================================
echo [LOCKED] SAFEPLUS_MLR_RIDER = 통합엔진(unified_leader)로 대체되어 잠김. 실행 안 함. >> C:\stock_bot\data\LOG\mlr_rider_run.log
exit /b 0

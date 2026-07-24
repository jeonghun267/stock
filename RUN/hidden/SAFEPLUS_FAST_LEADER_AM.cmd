@echo off
REM ==================================================================
REM  ★★★ 잠금(LOCKED) 2026-07-03 — 손대지 마세요 ★★★
REM ------------------------------------------------------------------
REM  사유: FAST_LEADER는 MLR라이더와 진입종목 69% 중복(발산테스트로 확인).
REM        큰 상승주는 둘 다 잡고 진입시각만 달랐음 -> 하나로 통합함.
REM        => 통합 엔진  unified_leader_v1.py (SAFEPLUS_UNIFIED_LEADER) 로 대체.
REM           FAST의 'is_up(5>=20선&시가위)' 경로는 통합의 (2)개장로켓 경로로 그대로 흡수됨.
REM  재가동 금지. 꼭 되살리려면: 먼저 통합엔진을 끄고(중복매수 방지) 아래 원본 복구.
REM      [원본]
REM        set FASTLDR_LIVE=YES
REM        set FASTLDR_CAP_KRW=100000
REM        set FASTLDR_TOPN=2
REM        set FASTLDR_END=1100
REM        C:\python310\python.exe -X utf8 C:\stock_bot\RUN\fast_leader_am_v1.py >> C:\stock_bot\data\LOG\fast_leader_am_run.log 2>&1
REM  ※ fast_leader_am_v1.py 파일 자체는 참고용으로 보존(삭제 무방하나 기록용 유지).
REM ==================================================================
echo [LOCKED] SAFEPLUS_FAST_LEADER_AM = 통합엔진(unified_leader)로 대체되어 잠김. 실행 안 함. >> C:\stock_bot\data\LOG\fast_leader_am_run.log
exit /b 0

@echo off
REM [전날 종가 기준 대장주 순위표] 매일 장전 1회 생성. 주문0.
REM  · 종가매수용 = 거래대금 순위(codes_by_value)  · 장중단타용 = 단타점수 순위(codes/board)
REM  · leader_filter 가 이 표를 우선 참조 → 돌파/골든크로스/라이더가 9시부터 전날 대장 참조.
REM  롤백(실시간 opt10032 로 되돌리기): setx LEADER_USE_BOARD NO
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\daily_leader_board_v1.py >> C:\stock_bot\data\LOG\daily_leader_board.log 2>&1

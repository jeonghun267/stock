@echo off
REM SAFEPLUS 3분봉 5/60 골든크로스 - 친구님 "5선이 60선 살짝 위=바닥 시작". 회복 초입 잡기.
REM 거래대금대장 ∩ 5선이 60선 상향돌파(이격 좁음) ∩ 현재가>60선 ∩ 체결강도. 매도=60선이탈/이격익절. 당일청산 15:18.
REM 실탄=GC560_LIVE(User env). 끄기 setx GC560_LIVE NO.
C:\python310\python.exe -X utf8 C:\stock_bot\RUN\golden_cross_560_v1.py >> C:\stock_bot\data\LOG\gc560_run.log 2>&1
